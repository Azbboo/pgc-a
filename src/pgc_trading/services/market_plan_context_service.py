"""Link market-review context to a pending trade plan."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pgc_trading.config import Paths
from pgc_trading.market.calendar import is_yyyymmdd
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult, ServiceWarning
from pgc_trading.storage.database import connect


ALIGNMENTS = {"aligned", "neutral", "conflict", "unknown"}
RISK_LEVELS = {"low", "medium", "high", "unknown"}
MANAGEMENT_ACTIONS = {"proceed", "manual_review", "consider_cancel", "unknown"}
STRONG_SIGNAL_SCORE = 0.75
TOP_SECTOR_RANK = 3
PERSISTENT_SECTOR_SCORE = 0.5
WEAK_SECTOR_RANK = 10
WEAK_SECTOR_SCORE = 0.3


@dataclass(frozen=True)
class LinkMarketPlanContextRequest:
    as_of_date: str
    trade_plan_id: int


@dataclass(frozen=True)
class MarketPlanContextResult:
    market_review_run_id: int
    trade_plan_id: int
    alignment: str
    risk_level: str
    management_action: str
    rationale: str
    evidence: dict[str, object]


@dataclass(frozen=True)
class _CandidatePlan:
    trade_plan_id: int
    trade_plan_status: str
    trade_plan_action: str
    plan_as_of_date: str
    planned_trade_date: str | None
    daily_pick_id: int | None
    signal_id: int | None
    ts_code: str
    name: str
    score: float
    signal_rank: int | None


@dataclass(frozen=True)
class _MarketReviewRun:
    market_review_run_id: int
    as_of_date: str
    status: str
    regime: str
    breadth_score: float | None
    trend_score: float | None
    volume_score: float | None
    persistence_score: float | None
    sentiment_score: float | None
    summary: str


class MarketPlanContextService:
    """Create an advisory bridge from market review to a trade plan."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def link_plan_context(
        self,
        request: LinkMarketPlanContextRequest,
        ctx: RequestContext,
    ) -> ServiceResult[MarketPlanContextResult]:
        errors = _validate_request(request)
        if errors:
            return ServiceResult(status="validation_failed", request_id=ctx.request_id, errors=errors)

        with connect(self.db_path) as conn:
            review_run = _load_market_review_run(conn, request.as_of_date)
            if review_run is None:
                return ServiceResult(
                    status="validation_failed",
                    request_id=ctx.request_id,
                    errors=[
                        ServiceError(
                            "MARKET_REVIEW_RUN_NOT_FOUND",
                            f"No completed market_review_run was found for {request.as_of_date}.",
                        )
                    ],
                )

            plan = _load_candidate_plan(conn, request.trade_plan_id)
            if plan is None:
                return ServiceResult(
                    status="validation_failed",
                    request_id=ctx.request_id,
                    errors=[
                        ServiceError(
                            "TRADE_PLAN_NOT_FOUND",
                            f"Trade plan {request.trade_plan_id} was not found.",
                            entity_type="trade_plan",
                            entity_id=request.trade_plan_id,
                        )
                    ],
                    lineage={"market_review_run_id": review_run.market_review_run_id},
                )

            top_sectors = _load_top_sectors(conn, review_run.market_review_run_id)
            candidate_sector = _load_candidate_sector(conn, review_run.market_review_run_id, plan.ts_code)
            external_items = _load_relevant_external_items(
                conn,
                request.as_of_date,
                plan.ts_code,
                candidate_sector,
            )
            result = _build_context_result(
                review_run=review_run,
                plan=plan,
                top_sectors=top_sectors,
                candidate_sector=candidate_sector,
                external_items=external_items,
            )

            warnings = _build_warnings(plan, request.as_of_date, candidate_sector, external_items)
            changed = False
            context_id: int | None = None
            if not ctx.dry_run:
                conn.execute("BEGIN")
                try:
                    changed, context_id = _persist_context(conn, result)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=result,
            created_ids={"market_plan_context_id": context_id} if context_id is not None and changed else {},
            warnings=warnings,
            lineage={
                "market_review_run_id": result.market_review_run_id,
                "trade_plan_id": result.trade_plan_id,
                "changed": "true" if changed else "false",
            },
        )


def _validate_request(request: LinkMarketPlanContextRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not is_yyyymmdd(request.as_of_date):
        errors.append(ServiceError("INVALID_AS_OF_DATE", "as_of_date must be compact YYYYMMDD."))
    if request.trade_plan_id <= 0:
        errors.append(ServiceError("INVALID_TRADE_PLAN_ID", "trade_plan_id must be positive."))
    return errors


def _load_market_review_run(conn: Any, as_of_date: str) -> _MarketReviewRun | None:
    row = conn.execute(
        """
        SELECT
          mrr.id,
          mrr.as_of_date,
          mrr.status,
          mrs.regime,
          mrs.breadth_score,
          mrs.trend_score,
          mrs.volume_score,
          mrs.persistence_score,
          mrs.sentiment_score,
          mrs.summary
        FROM market_review_runs mrr
        LEFT JOIN market_regime_snapshots mrs ON mrs.market_review_run_id = mrr.id
        WHERE mrr.as_of_date = ?
        ORDER BY mrr.id DESC
        LIMIT 1
        """,
        (as_of_date,),
    ).fetchone()
    if row is None:
        return None
    return _MarketReviewRun(
        market_review_run_id=int(row["id"]),
        as_of_date=row["as_of_date"],
        status=row["status"],
        regime=row["regime"] or "unknown",
        breadth_score=_optional_float(row["breadth_score"]),
        trend_score=_optional_float(row["trend_score"]),
        volume_score=_optional_float(row["volume_score"]),
        persistence_score=_optional_float(row["persistence_score"]),
        sentiment_score=_optional_float(row["sentiment_score"]),
        summary=row["summary"] or "",
    )


def _load_candidate_plan(conn: Any, trade_plan_id: int) -> _CandidatePlan | None:
    row = conn.execute(
        """
        SELECT
          tp.id AS trade_plan_id,
          tp.status AS trade_plan_status,
          tp.action AS trade_plan_action,
          tp.as_of_date AS plan_as_of_date,
          tp.planned_trade_date,
          tp.daily_pick_id,
          tp.signal_id AS plan_signal_id,
          ss.id AS signal_id,
          ss.ts_code,
          ss.name,
          ss.score,
          ss.signal_rank
        FROM trade_plans tp
        LEFT JOIN strategy_signals ss ON ss.id = tp.signal_id
        WHERE tp.id = ?
        LIMIT 1
        """,
        (trade_plan_id,),
    ).fetchone()
    if row is None or row["signal_id"] is None:
        return None
    return _CandidatePlan(
        trade_plan_id=int(row["trade_plan_id"]),
        trade_plan_status=row["trade_plan_status"],
        trade_plan_action=row["trade_plan_action"],
        plan_as_of_date=row["plan_as_of_date"],
        planned_trade_date=row["planned_trade_date"],
        daily_pick_id=_optional_int(row["daily_pick_id"]),
        signal_id=_optional_int(row["signal_id"]),
        ts_code=row["ts_code"],
        name=row["name"],
        score=float(row["score"]),
        signal_rank=_optional_int(row["signal_rank"]),
    )


def _load_top_sectors(conn: Any, market_review_run_id: int) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
          sector_code,
          sector_name,
          rank_overall,
          persistence_score,
          breadth_score,
          volume_score,
          leader_count,
          return_1d,
          return_3d
        FROM sector_daily_snapshots
        WHERE market_review_run_id = ?
        ORDER BY rank_overall IS NULL, rank_overall, persistence_score DESC, sector_code
        LIMIT 5
        """,
        (market_review_run_id,),
    ).fetchall()
    return [_sector_snapshot_payload(row) for row in rows]


def _load_candidate_sector(conn: Any, market_review_run_id: int, ts_code: str) -> dict[str, object] | None:
    row = conn.execute(
        """
        SELECT
          sc.sector_code,
          sc.sector_name,
          sc.rank_in_sector,
          sc.role,
          sc.score,
          sc.metrics_json,
          sds.rank_overall,
          sds.persistence_score,
          sds.breadth_score,
          sds.volume_score,
          sds.leader_count,
          sds.return_1d,
          sds.return_3d
        FROM sector_constituents sc
        LEFT JOIN sector_daily_snapshots sds
          ON sds.market_review_run_id = sc.market_review_run_id
         AND sds.sector_code = sc.sector_code
        WHERE sc.market_review_run_id = ?
          AND sc.ts_code = ?
        ORDER BY sds.rank_overall IS NULL, sds.rank_overall, sc.rank_in_sector IS NULL, sc.rank_in_sector
        LIMIT 1
        """,
        (market_review_run_id, ts_code),
    ).fetchone()
    if row is None:
        return None
    payload = _sector_snapshot_payload(row)
    payload.update(
        {
            "rank_in_sector": _optional_int(row["rank_in_sector"]),
            "role": row["role"],
            "constituent_score": _optional_float(row["score"]),
            "metrics": _loads_json_object(row["metrics_json"]),
        }
    )
    return payload


def _load_relevant_external_items(
    conn: Any,
    as_of_date: str,
    ts_code: str,
    candidate_sector: dict[str, object] | None,
) -> list[dict[str, object]]:
    sector_keys = []
    if candidate_sector:
        for key in (candidate_sector.get("sector_code"), candidate_sector.get("sector_name")):
            if isinstance(key, str) and key:
                sector_keys.append(key)
    clauses = ["(scope_type = 'market')", "(scope_type = 'stock' AND scope_key = ?)"]
    params: list[object] = [as_of_date, ts_code]
    if sector_keys:
        placeholders = ", ".join("?" for _ in sector_keys)
        clauses.append(f"(scope_type = 'sector' AND scope_key IN ({placeholders}))")
        params.extend(sector_keys)

    rows = conn.execute(
        f"""
        SELECT
          id,
          scope_type,
          scope_key,
          item_type,
          provider,
          title,
          summary,
          sentiment,
          importance,
          published_date,
          url
        FROM market_external_items
        WHERE as_of_date = ?
          AND ({' OR '.join(clauses)})
        ORDER BY
          CASE importance WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END,
          CASE sentiment WHEN 'negative' THEN 0 WHEN 'mixed' THEN 1 WHEN 'positive' THEN 2 WHEN 'neutral' THEN 3 ELSE 4 END,
          id
        LIMIT 10
        """,
        tuple(params),
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "scope_type": row["scope_type"],
            "scope_key": row["scope_key"],
            "item_type": row["item_type"],
            "provider": row["provider"],
            "title": row["title"],
            "summary": row["summary"],
            "sentiment": row["sentiment"],
            "importance": row["importance"],
            "published_date": row["published_date"],
            "url": row["url"],
        }
        for row in rows
    ]


def _build_context_result(
    *,
    review_run: _MarketReviewRun,
    plan: _CandidatePlan,
    top_sectors: list[dict[str, object]],
    candidate_sector: dict[str, object] | None,
    external_items: list[dict[str, object]],
) -> MarketPlanContextResult:
    alignment = _determine_alignment(plan, candidate_sector, top_sectors, external_items)
    risk_level = _determine_risk_level(review_run, alignment, external_items)
    management_action = _determine_management_action(alignment, risk_level)
    rationale = _build_rationale(alignment, risk_level, management_action, review_run, plan, candidate_sector, external_items)
    evidence: dict[str, object] = {
        "market_regime": {
            "regime": review_run.regime,
            "breadth_score": review_run.breadth_score,
            "trend_score": review_run.trend_score,
            "volume_score": review_run.volume_score,
            "persistence_score": review_run.persistence_score,
            "sentiment_score": review_run.sentiment_score,
            "summary": review_run.summary,
        },
        "candidate": {
            "ts_code": plan.ts_code,
            "name": plan.name,
            "score": plan.score,
            "signal_rank": plan.signal_rank,
            "trade_plan_status": plan.trade_plan_status,
            "trade_plan_action": plan.trade_plan_action,
            "planned_trade_date": plan.planned_trade_date,
        },
        "candidate_sector": candidate_sector,
        "top_sectors": top_sectors,
        "external_items": external_items,
        "coverage": {
            "sector": "available" if candidate_sector is not None else "missing",
            "external_evidence": "available" if external_items else "missing",
        },
    }
    return MarketPlanContextResult(
        market_review_run_id=review_run.market_review_run_id,
        trade_plan_id=plan.trade_plan_id,
        alignment=alignment,
        risk_level=risk_level,
        management_action=management_action,
        rationale=rationale,
        evidence=evidence,
    )


def _determine_alignment(
    plan: _CandidatePlan,
    candidate_sector: dict[str, object] | None,
    top_sectors: list[dict[str, object]],
    external_items: list[dict[str, object]],
) -> str:
    if candidate_sector is None and not external_items:
        return "unknown"
    if candidate_sector is None:
        return "neutral"

    sector_code = candidate_sector.get("sector_code")
    top_sector_codes = {sector.get("sector_code") for sector in top_sectors[:TOP_SECTOR_RANK]}
    rank = _optional_int(candidate_sector.get("rank_overall"))
    persistence = _optional_float(candidate_sector.get("persistence_score"))
    role = str(candidate_sector.get("role") or "")

    is_top_persistent = (
        sector_code in top_sector_codes
        and rank is not None
        and rank <= TOP_SECTOR_RANK
        and persistence is not None
        and persistence >= PERSISTENT_SECTOR_SCORE
    )
    if is_top_persistent:
        return "aligned"

    is_weak_sector = (
        role == "weak"
        or (rank is not None and rank > WEAK_SECTOR_RANK)
        or (persistence is not None and persistence < WEAK_SECTOR_SCORE)
    )
    if is_weak_sector and plan.score >= STRONG_SIGNAL_SCORE:
        return "conflict"
    if is_weak_sector:
        return "neutral"
    return "neutral"


def _determine_risk_level(
    review_run: _MarketReviewRun,
    alignment: str,
    external_items: list[dict[str, object]],
) -> str:
    if not external_items:
        return "unknown"
    high_negative_stock = any(
        item.get("scope_type") == "stock"
        and item.get("sentiment") == "negative"
        and item.get("importance") == "high"
        for item in external_items
    )
    if high_negative_stock:
        return "high"
    if any(item.get("sentiment") in {"negative", "mixed"} for item in external_items):
        return "medium"
    if review_run.regime == "risk_off" or alignment == "conflict":
        return "medium"
    return "low"


def _determine_management_action(alignment: str, risk_level: str) -> str:
    if alignment == "unknown" or risk_level in {"high", "unknown"}:
        return "manual_review"
    if alignment == "conflict":
        return "manual_review"
    if alignment == "aligned" and risk_level == "low":
        return "proceed"
    return "manual_review"


def _build_rationale(
    alignment: str,
    risk_level: str,
    management_action: str,
    review_run: _MarketReviewRun,
    plan: _CandidatePlan,
    candidate_sector: dict[str, object] | None,
    external_items: list[dict[str, object]],
) -> str:
    if alignment == "unknown":
        return (
            f"{plan.ts_code} lacks sector rotation and market-review external evidence for "
            f"{review_run.as_of_date}; manual review is required before acting on the plan."
        )
    if risk_level == "high":
        return (
            f"{plan.ts_code} has high-importance negative stock evidence in the market review; "
            f"keep the plan unchanged but require manual review."
        )
    if alignment == "conflict":
        sector_name = candidate_sector.get("sector_name") if candidate_sector else "candidate sector"
        return (
            f"{plan.ts_code} has a strong stock signal, but {sector_name} is weak in the market review; "
            f"manual review is required before tomorrow's execution."
        )
    if management_action == "proceed":
        sector_name = candidate_sector.get("sector_name") if candidate_sector else "candidate sector"
        return (
            f"{plan.ts_code} belongs to a top persistent sector ({sector_name}) and no high-risk "
            f"stock evidence was found; proceed with normal pre-trade checks."
        )
    if external_items:
        return (
            f"{plan.ts_code} has partial market-review support, but the combined sector/news picture "
            f"is not strong enough for automatic proceed."
        )
    return f"{plan.ts_code} market-review context is incomplete; manual review is required."


def _build_warnings(
    plan: _CandidatePlan,
    as_of_date: str,
    candidate_sector: dict[str, object] | None,
    external_items: list[dict[str, object]],
) -> list[ServiceWarning]:
    warnings: list[ServiceWarning] = []
    if plan.plan_as_of_date != as_of_date:
        warnings.append(
            ServiceWarning(
                "TRADE_PLAN_DATE_MISMATCH",
                f"Trade plan {plan.trade_plan_id} was created for {plan.plan_as_of_date}, not {as_of_date}.",
                entity_type="trade_plan",
                entity_id=plan.trade_plan_id,
            )
        )
    if candidate_sector is None and not external_items:
        warnings.append(
            ServiceWarning(
                "MARKET_PLAN_CONTEXT_INCOMPLETE",
                "No sector rotation or market-review external evidence was found for the candidate.",
                entity_type="trade_plan",
                entity_id=plan.trade_plan_id,
            )
        )
    return warnings


def _persist_context(conn: Any, result: MarketPlanContextResult) -> tuple[bool, int]:
    evidence_json = json.dumps(result.evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    existing = conn.execute(
        """
        SELECT id, alignment, risk_level, management_action, rationale, evidence_json
        FROM market_plan_contexts
        WHERE market_review_run_id = ?
          AND trade_plan_id = ?
        """,
        (result.market_review_run_id, result.trade_plan_id),
    ).fetchone()
    if existing is not None:
        context_id = int(existing["id"])
        if (
            existing["alignment"] == result.alignment
            and existing["risk_level"] == result.risk_level
            and existing["management_action"] == result.management_action
            and existing["rationale"] == result.rationale
            and existing["evidence_json"] == evidence_json
        ):
            return False, context_id
        conn.execute(
            """
            UPDATE market_plan_contexts
            SET alignment = ?,
                risk_level = ?,
                management_action = ?,
                rationale = ?,
                evidence_json = ?,
                created_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                result.alignment,
                result.risk_level,
                result.management_action,
                result.rationale,
                evidence_json,
                context_id,
            ),
        )
        return True, context_id

    cursor = conn.execute(
        """
        INSERT INTO market_plan_contexts
          (market_review_run_id, trade_plan_id, alignment, risk_level, management_action, rationale, evidence_json)
        VALUES
          (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result.market_review_run_id,
            result.trade_plan_id,
            result.alignment,
            result.risk_level,
            result.management_action,
            result.rationale,
            evidence_json,
        ),
    )
    return True, int(cursor.lastrowid)


def _sector_snapshot_payload(row: Any) -> dict[str, object]:
    return {
        "sector_code": row["sector_code"],
        "sector_name": row["sector_name"],
        "rank_overall": _optional_int(row["rank_overall"]),
        "persistence_score": _optional_float(row["persistence_score"]),
        "breadth_score": _optional_float(row["breadth_score"]),
        "volume_score": _optional_float(row["volume_score"]),
        "leader_count": _optional_int(row["leader_count"]),
        "return_1d": _optional_float(row["return_1d"]),
        "return_3d": _optional_float(row["return_3d"]),
    }


def _loads_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)
