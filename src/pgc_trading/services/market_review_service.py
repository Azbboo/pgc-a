"""Market review coordination service."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from pgc_trading.config import Paths
from pgc_trading.market.calendar import is_yyyymmdd
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult, ServiceWarning
from pgc_trading.services.sector_rotation_service import (
    ImportSectorMembershipRequest,
    ImportSectorMembershipResult,
    SectorRotationService,
)
from pgc_trading.storage.database import connect


@dataclass(frozen=True)
class RunMarketReviewRequest:
    as_of_date: str
    universe: str = "market_bars"
    min_coverage: float = 0.8


@dataclass(frozen=True)
class ListMarketReviewsRequest:
    limit: int = 20


@dataclass(frozen=True)
class GetMarketReviewRequest:
    as_of_date: str


@dataclass(frozen=True)
class ListMarketReviewSectorsRequest:
    as_of_date: str


@dataclass(frozen=True)
class ListMarketReviewExternalItemsRequest:
    as_of_date: str


@dataclass(frozen=True)
class ListMarketReviewHypothesesRequest:
    as_of_date: str
    status: str | None = None
    limit: int = 100


@dataclass(frozen=True)
class GetMarketReviewPlanContextRequest:
    as_of_date: str
    trade_plan_id: int | None = None


@dataclass(frozen=True)
class MarketRegimeResult:
    market_review_run_id: int | None
    as_of_date: str
    status: str
    regime: str
    breadth_score: float | None
    trend_score: float | None
    volume_score: float | None
    persistence_score: float | None
    coverage_ratio: float
    summary: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _MarketBar:
    ts_code: str
    trade_date: str
    close: float | None
    vol: float | None


@dataclass(frozen=True)
class _RegimeSnapshot:
    result: MarketRegimeResult
    metrics: dict[str, Any]
    coverage: dict[str, Any]
    manifest: dict[str, Any]
    warning_details: list[tuple[str, str]]


class MarketReviewService:
    """Coordinate market-review writes while keeping trading workflows untouched."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def list_market_reviews(
        self,
        request: ListMarketReviewsRequest,
        ctx: RequestContext,
    ) -> ServiceResult[dict[str, Any]]:
        validation_errors = _validate_list_market_reviews_request(request)
        if validation_errors:
            return ServiceResult(status="validation_failed", request_id=ctx.request_id, errors=validation_errors)

        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                  r.id,
                  r.as_of_date,
                  r.status,
                  r.provider_manifest_json,
                  r.coverage_json,
                  r.summary_json,
                  r.created_at,
                  r.completed_at,
                  m.regime,
                  m.breadth_score,
                  m.trend_score,
                  m.volume_score,
                  m.persistence_score,
                  m.summary AS regime_summary
                FROM market_review_runs r
                LEFT JOIN market_regime_snapshots m
                  ON m.market_review_run_id = r.id
                ORDER BY r.as_of_date DESC, r.id DESC
                LIMIT ?
                """,
                (request.limit,),
            ).fetchall()

        reviews = [_market_review_summary_payload(row) for row in rows]
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data={
                "reviews": reviews,
                "limit": request.limit,
                "source": _source_payload(["market_review_runs", "market_regime_snapshots"]),
                "coverage": {
                    "review_count": len(reviews),
                    "limit": request.limit,
                },
                "missing_data": [] if reviews else ["market_review_runs"],
            },
            lineage={"limit": request.limit},
        )

    def get_market_review(
        self,
        request: GetMarketReviewRequest,
        ctx: RequestContext,
    ) -> ServiceResult[dict[str, Any]]:
        validation_errors = _validate_market_review_date(request.as_of_date)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_market_review_detail(request.as_of_date),
                errors=validation_errors,
            )

        with connect(self.db_path) as conn:
            run = _find_market_review_run(conn, request.as_of_date)
            if run is None:
                data = _empty_market_review_detail(request.as_of_date)
            else:
                regime = _load_market_regime_snapshot(conn, int(run["id"]))
                sectors = _load_market_review_sector_payloads(conn, int(run["id"]))
                external_items = _load_market_external_item_payloads(conn, request.as_of_date)
                contexts = _load_market_plan_context_payloads(conn, int(run["id"]), trade_plan_id=None)
                data = _market_review_detail_payload(run, regime, sectors, external_items, contexts)
            data["diagnostics"] = _market_review_diagnostics(
                conn,
                self.db_path,
                request.as_of_date,
                run_id=int(run["id"]) if run is not None else None,
                missing_data=data["missing_data"],
            )

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=data,
            lineage={"as_of_date": request.as_of_date, "market_review_run_id": data["market_review_run_id"]},
        )

    def list_market_review_sectors(
        self,
        request: ListMarketReviewSectorsRequest,
        ctx: RequestContext,
    ) -> ServiceResult[dict[str, Any]]:
        validation_errors = _validate_market_review_date(request.as_of_date)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_sectors_payload(request.as_of_date, has_review=False),
                errors=validation_errors,
            )

        with connect(self.db_path) as conn:
            run = _find_market_review_run(conn, request.as_of_date)
            if run is None:
                data = _empty_sectors_payload(request.as_of_date, has_review=False)
            else:
                sectors = _load_market_review_sector_payloads(conn, int(run["id"]))
                data = _sectors_payload(request.as_of_date, int(run["id"]), sectors)

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=data,
            lineage={"as_of_date": request.as_of_date, "market_review_run_id": data["market_review_run_id"]},
        )

    def list_market_review_external_items(
        self,
        request: ListMarketReviewExternalItemsRequest,
        ctx: RequestContext,
    ) -> ServiceResult[dict[str, Any]]:
        validation_errors = _validate_market_review_date(request.as_of_date)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_external_items_payload(request.as_of_date, has_review=False),
                errors=validation_errors,
            )

        with connect(self.db_path) as conn:
            run = _find_market_review_run(conn, request.as_of_date)
            items = _load_market_external_item_payloads(conn, request.as_of_date)
            data = _external_items_payload(
                request.as_of_date,
                int(run["id"]) if run is not None else None,
                items,
            )

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=data,
            lineage={"as_of_date": request.as_of_date, "market_review_run_id": data["market_review_run_id"]},
        )

    def list_market_review_hypotheses(
        self,
        request: ListMarketReviewHypothesesRequest,
        ctx: RequestContext,
    ) -> ServiceResult[dict[str, Any]]:
        validation_errors = _validate_list_market_review_hypotheses_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_hypotheses_payload(request.as_of_date, has_review=False),
                errors=validation_errors,
            )

        with connect(self.db_path) as conn:
            run = _find_market_review_run(conn, request.as_of_date)
            hypotheses = _load_strategy_hypothesis_payloads(conn, request)
            data = _hypotheses_payload(
                request.as_of_date,
                int(run["id"]) if run is not None else None,
                hypotheses,
                request,
            )

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=data,
            lineage={"as_of_date": request.as_of_date, "market_review_run_id": data["market_review_run_id"]},
        )

    def get_market_review_plan_context(
        self,
        request: GetMarketReviewPlanContextRequest,
        ctx: RequestContext,
    ) -> ServiceResult[dict[str, Any]]:
        validation_errors = _validate_market_review_plan_context_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_plan_context_payload(request.as_of_date, has_review=False, trade_plan_id=request.trade_plan_id),
                errors=validation_errors,
            )

        with connect(self.db_path) as conn:
            run = _find_market_review_run(conn, request.as_of_date)
            if run is None:
                data = _empty_plan_context_payload(
                    request.as_of_date,
                    has_review=False,
                    trade_plan_id=request.trade_plan_id,
                )
            else:
                contexts = _load_market_plan_context_payloads(conn, int(run["id"]), request.trade_plan_id)
                data = _plan_context_payload(request.as_of_date, int(run["id"]), contexts, request.trade_plan_id)

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=data,
            lineage={"as_of_date": request.as_of_date, "market_review_run_id": data["market_review_run_id"]},
        )

    def run_market_review(
        self,
        request: RunMarketReviewRequest,
        ctx: RequestContext,
    ) -> ServiceResult[MarketRegimeResult]:
        validation_errors = _validate_market_review_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_regime_result(request, "blocked", "Market review request is invalid."),
                errors=validation_errors,
            )

        with connect(self.db_path) as conn:
            snapshot = _build_regime_snapshot(conn, request)

            warnings = [
                ServiceWarning(code=code, message=message)
                for code, message in snapshot.warning_details
            ]
            if snapshot.result.status == "blocked":
                return ServiceResult(
                    status="blocked",
                    request_id=ctx.request_id,
                    data=snapshot.result,
                    warnings=warnings,
                    errors=[
                        ServiceError(
                            code="MARKET_REVIEW_BLOCKED",
                            message=snapshot.result.summary,
                            severity="blocker",
                        )
                    ],
                    lineage=_regime_lineage(snapshot.result, changed="false"),
                )

            if ctx.dry_run:
                return ServiceResult(
                    status="success",
                    request_id=ctx.request_id,
                    data=snapshot.result,
                    warnings=warnings,
                    lineage=_regime_lineage(snapshot.result, changed="false"),
                )

            conn.execute("BEGIN")
            try:
                market_review_run_id, changed = _persist_regime_snapshot(conn, snapshot)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        persisted = MarketRegimeResult(
            market_review_run_id=market_review_run_id,
            as_of_date=snapshot.result.as_of_date,
            status=snapshot.result.status,
            regime=snapshot.result.regime,
            breadth_score=snapshot.result.breadth_score,
            trend_score=snapshot.result.trend_score,
            volume_score=snapshot.result.volume_score,
            persistence_score=snapshot.result.persistence_score,
            coverage_ratio=snapshot.result.coverage_ratio,
            summary=snapshot.result.summary,
            warnings=snapshot.result.warnings,
        )
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=persisted,
            warnings=warnings,
            created_ids={"market_review_run_id": market_review_run_id} if changed else {},
            lineage=_regime_lineage(persisted, changed="true" if changed else "false"),
        )

    def import_sector_memberships(
        self,
        request: ImportSectorMembershipRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ImportSectorMembershipResult]:
        if not is_yyyymmdd(request.as_of_date):
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                errors=[ServiceError("INVALID_AS_OF_DATE", "as_of_date must be compact YYYYMMDD.")],
            )

        sector_service = SectorRotationService(self.db_path)
        if ctx.dry_run:
            return sector_service.import_sector_memberships(request, ctx)

        preview = sector_service.import_sector_memberships(
            request,
            RequestContext(
                request_id=ctx.request_id,
                idempotency_key=ctx.idempotency_key,
                dry_run=True,
                operator=ctx.operator,
                source=ctx.source,
                allow_live_writes=ctx.allow_live_writes,
            ),
        )
        if not preview.ok or preview.data is None:
            return preview

        provider_manifest = {"sector_memberships": preview.data.provider}
        summary = {
            "sector_rotation": {
                "provider": preview.data.provider,
                "sector_count": preview.data.sector_count,
                "member_count": preview.data.member_count,
                "missing_bar_count": preview.data.missing_bar_count,
            }
        }
        market_review_run_id = self.ensure_market_review_run(
            request.as_of_date,
            provider_manifest=provider_manifest,
            summary=summary,
        )
        return sector_service.import_sector_memberships(
            request,
            ctx,
            market_review_run_id=market_review_run_id,
        )

    def ensure_market_review_run(
        self,
        as_of_date: str,
        *,
        provider_manifest: dict[str, Any] | None = None,
        coverage: dict[str, Any] | None = None,
        summary: dict[str, Any] | None = None,
    ) -> int:
        if not is_yyyymmdd(as_of_date):
            raise ValueError("as_of_date must be compact YYYYMMDD")
        with connect(self.db_path) as conn:
            conn.execute("BEGIN")
            try:
                run_id = _upsert_market_review_run(
                    conn,
                    as_of_date,
                    provider_manifest=provider_manifest or {},
                    coverage=coverage or {},
                    summary=summary or {},
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return run_id


def _validate_market_review_request(request: RunMarketReviewRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not is_yyyymmdd(request.as_of_date):
        errors.append(ServiceError("INVALID_AS_OF_DATE", "as_of_date must be compact YYYYMMDD."))
    if request.universe != "market_bars":
        errors.append(
            ServiceError(
                "UNSUPPORTED_MARKET_REVIEW_UNIVERSE",
                f"Unsupported market review universe: {request.universe}.",
            )
        )
    if request.min_coverage <= 0 or request.min_coverage > 1:
        errors.append(
            ServiceError(
                "INVALID_MIN_COVERAGE",
                "min_coverage must be greater than 0 and less than or equal to 1.",
            )
        )
    return errors


def _validate_list_market_reviews_request(request: ListMarketReviewsRequest) -> list[ServiceError]:
    if request.limit < 1:
        return [ServiceError("VALIDATION_ERROR", "limit must be greater than zero.")]
    return []


def _validate_market_review_date(as_of_date: str) -> list[ServiceError]:
    if not is_yyyymmdd(as_of_date):
        return [ServiceError("INVALID_AS_OF_DATE", "as_of_date must be compact YYYYMMDD.")]
    return []


def _validate_list_market_review_hypotheses_request(
    request: ListMarketReviewHypothesesRequest,
) -> list[ServiceError]:
    errors = _validate_market_review_date(request.as_of_date)
    if request.status is not None and request.status not in {
        "proposed",
        "testing",
        "accepted",
        "rejected",
        "archived",
    }:
        errors.append(ServiceError("VALIDATION_ERROR", f"invalid hypothesis status: {request.status}"))
    if request.limit < 1:
        errors.append(ServiceError("VALIDATION_ERROR", "limit must be greater than zero."))
    return errors


def _validate_market_review_plan_context_request(
    request: GetMarketReviewPlanContextRequest,
) -> list[ServiceError]:
    errors = _validate_market_review_date(request.as_of_date)
    if request.trade_plan_id is not None and request.trade_plan_id < 1:
        errors.append(ServiceError("VALIDATION_ERROR", "trade_plan_id must be greater than zero."))
    return errors


def _find_market_review_run(conn: sqlite3.Connection, as_of_date: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT
          id,
          as_of_date,
          status,
          provider_manifest_json,
          coverage_json,
          summary_json,
          created_at,
          completed_at
        FROM market_review_runs
        WHERE as_of_date = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (as_of_date,),
    ).fetchone()


def _load_market_regime_snapshot(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT
          market_review_run_id,
          as_of_date,
          regime,
          breadth_score,
          trend_score,
          volume_score,
          sentiment_score,
          persistence_score,
          summary,
          metrics_json
        FROM market_regime_snapshots
        WHERE market_review_run_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (run_id,),
    ).fetchone()


def _market_review_summary_payload(row: sqlite3.Row) -> dict[str, Any]:
    provider_manifest = _json_loads(row["provider_manifest_json"])
    coverage = _json_loads(row["coverage_json"])
    summary = _json_loads(row["summary_json"])
    return {
        "market_review_run_id": int(row["id"]),
        "as_of_date": row["as_of_date"],
        "status": row["status"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
        "regime": row["regime"],
        "scores": {
            "breadth": row["breadth_score"],
            "trend": row["trend_score"],
            "volume": row["volume_score"],
            "persistence": row["persistence_score"],
        },
        "summary": summary,
        "regime_summary": row["regime_summary"],
        "source": _source_payload(["market_review_runs", "market_regime_snapshots"], provider_manifest),
        "coverage": {"has_review": True, **coverage},
        "missing_data": [] if row["regime"] is not None else ["market_regime_snapshots"],
    }


def _market_review_detail_payload(
    run: sqlite3.Row,
    regime: sqlite3.Row | None,
    sectors: list[dict[str, Any]] | None = None,
    external_items: list[dict[str, Any]] | None = None,
    contexts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    provider_manifest = _json_loads(run["provider_manifest_json"])
    coverage = _json_loads(run["coverage_json"])
    summary = _json_loads(run["summary_json"])
    sector_payloads = sectors or []
    external_payloads = external_items or []
    context_payloads = contexts or []
    missing_data: list[str] = []
    if not provider_manifest:
        missing_data.append("provider_manifest_json")
    if not coverage:
        missing_data.append("coverage_json")
    if regime is None:
        missing_data.append("market_regime_snapshots")
    if not sector_payloads:
        missing_data.append("sector_daily_snapshots")
    if not external_payloads:
        missing_data.append("market_external_items")
    if not context_payloads:
        missing_data.append("market_plan_contexts")
    regime_payload = _regime_payload(regime) if regime is not None else None
    hierarchy = _market_review_hierarchy_payload(
        as_of_date=run["as_of_date"],
        run_id=int(run["id"]),
        regime=regime_payload,
        sectors=sector_payloads,
        external_items=external_payloads,
        contexts=context_payloads,
    )
    return {
        "market_review_run_id": int(run["id"]),
        "as_of_date": run["as_of_date"],
        "exists": True,
        "status": run["status"],
        "created_at": run["created_at"],
        "completed_at": run["completed_at"],
        "provider_manifest": provider_manifest,
        "summary": summary,
        "regime": regime_payload,
        "hierarchy": hierarchy,
        "source": _source_payload(["market_review_runs", "market_regime_snapshots"], provider_manifest),
        "coverage": {"has_review": True, **coverage, "hierarchy": hierarchy["coverage"]},
        "missing_data": missing_data,
    }


def _empty_market_review_detail(as_of_date: str) -> dict[str, Any]:
    return {
        "market_review_run_id": None,
        "as_of_date": as_of_date,
        "exists": False,
        "status": "missing",
        "created_at": None,
        "completed_at": None,
        "provider_manifest": {},
        "summary": {},
        "regime": None,
        "hierarchy": _empty_market_review_hierarchy(as_of_date),
        "source": _source_payload(["market_review_runs", "market_regime_snapshots"], {}),
        "coverage": {"has_review": False},
        "missing_data": [
            "market_review_runs",
            "market_regime_snapshots",
            "sector_daily_snapshots",
            "market_external_items",
            "strategy_hypotheses",
            "market_plan_contexts",
        ],
    }


def _empty_market_review_hierarchy(as_of_date: str) -> dict[str, Any]:
    return {
        "as_of_date": as_of_date,
        "market_review_run_id": None,
        "chain": ["regime", "sectors", "representative_stocks", "evidence", "continuity", "next_day_plan"],
        "regime": None,
        "sectors": [],
        "evidence_freshness": {"market": "missing", "sector": "missing", "stock": "missing"},
        "narrative": _empty_market_review_narrative(as_of_date),
        "continuity": {
            "label": "insufficient_evidence",
            "reason": "缺少 market_review_runs，无法建立全市场复盘解释链。",
            "inputs": {},
        },
        "plan_relationships": [],
        "source_refs": [],
        "coverage": {
            "sector_count": 0,
            "representative_stock_count": 0,
            "external_item_count": 0,
            "plan_context_count": 0,
            "has_complete_chain": False,
        },
    }


def _market_review_hierarchy_payload(
    *,
    as_of_date: str,
    run_id: int,
    regime: dict[str, Any] | None,
    sectors: list[dict[str, Any]],
    external_items: list[dict[str, Any]],
    contexts: list[dict[str, Any]],
) -> dict[str, Any]:
    sector_nodes = [_sector_hierarchy_payload(sector, external_items) for sector in sectors[:8]]
    representative_stock_count = sum(len(sector["representative_stocks"]) for sector in sector_nodes)
    continuity = _continuity_payload(regime, sectors, external_items)
    plan_relationships = [_plan_relationship_payload(context, continuity["label"]) for context in contexts]
    evidence_freshness = _external_freshness_coverage(external_items, as_of_date)
    source_refs = _market_hierarchy_source_refs(run_id, sector_nodes, external_items, contexts)
    narrative = build_market_review_narrative_payload(
        as_of_date=as_of_date,
        market_review_run_id=run_id,
        regime=regime,
        sectors=sector_nodes,
        external_items=external_items,
        continuity=continuity,
        plan_relationships=plan_relationships,
        source_refs=source_refs,
    )
    return {
        "as_of_date": as_of_date,
        "market_review_run_id": run_id,
        "chain": ["regime", "sectors", "representative_stocks", "evidence", "continuity", "next_day_plan"],
        "regime": regime,
        "sectors": sector_nodes,
        "evidence_freshness": evidence_freshness,
        "narrative": narrative,
        "continuity": continuity,
        "plan_relationships": plan_relationships,
        "source_refs": source_refs,
        "coverage": {
            "sector_count": len(sectors),
            "representative_stock_count": representative_stock_count,
            "external_item_count": len(external_items),
            "plan_context_count": len(contexts),
            "has_complete_chain": bool(regime and sectors and external_items and contexts),
        },
    }


def _empty_market_review_narrative(as_of_date: str) -> dict[str, Any]:
    evidence_freshness = {
        "market": "missing",
        "sector": "missing",
        "stock": "missing",
        "news": "missing",
        "sentiment": "missing",
    }
    return {
        "as_of_date": as_of_date,
        "market_review_run_id": None,
        "regime_conclusion": {
            "status": "insufficient_evidence",
            "summary": "全市场结论证据不足：市场状态缺失。",
            "reason": "缺少 market_review_runs 或 market_regime_snapshots。",
            "scores": {},
        },
        "sector_ranking_reason": {
            "status": "insufficient_evidence",
            "summary": "板块轮动数据缺失，无法解释哪些板块有持续性。",
            "sectors": [],
        },
        "representative_stock_reason": {
            "status": "insufficient_evidence",
            "summary": "代表个股证据不足：缺少板块成员排名。",
            "stocks": [],
        },
        "evidence_freshness": evidence_freshness,
        "evidence_gaps": _market_review_narrative_evidence_gaps(
            sectors=[],
            external_items=[],
            plan_relationships=[],
            evidence_freshness=evidence_freshness,
        ),
        "continuity_judgement": {
            "label": "insufficient_evidence",
            "summary": "连续性判断证据不足。",
            "reason": "缺少全市场、板块或外部证据输入。",
        },
        "next_day_plan_relationship": {
            "relationship_label": "missing",
            "summary": "明日计划关系缺失，不能从复盘自动推导交易动作。",
            "relationships": [],
        },
        "source_refs": [],
    }


def build_market_review_narrative_payload(
    *,
    as_of_date: str,
    market_review_run_id: int | None,
    regime: dict[str, Any] | None,
    sectors: list[dict[str, Any]],
    external_items: list[dict[str, Any]],
    continuity: dict[str, Any] | None,
    plan_relationships: list[dict[str, Any]],
    source_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble a Chinese operator narrative from stored market-review evidence only."""

    evidence_freshness = _narrative_evidence_freshness(external_items, as_of_date)
    continuity_payload = continuity if isinstance(continuity, dict) else {}
    return {
        "as_of_date": as_of_date,
        "market_review_run_id": market_review_run_id,
        "regime_conclusion": _narrative_regime_conclusion(regime),
        "sector_ranking_reason": _narrative_sector_ranking_reason(sectors),
        "representative_stock_reason": _narrative_representative_stock_reason(sectors),
        "evidence_freshness": evidence_freshness,
        "evidence_gaps": _market_review_narrative_evidence_gaps(
            sectors=sectors,
            external_items=external_items,
            plan_relationships=plan_relationships,
            evidence_freshness=evidence_freshness,
        ),
        "continuity_judgement": _narrative_continuity_judgement(continuity_payload),
        "next_day_plan_relationship": _narrative_next_day_plan_relationship(plan_relationships),
        "source_refs": source_refs or [],
    }


def _narrative_regime_conclusion(regime: dict[str, Any] | None) -> dict[str, Any]:
    if not regime:
        return {
            "status": "insufficient_evidence",
            "summary": "全市场结论证据不足：市场状态缺失。",
            "reason": "缺少 market_regime_snapshots。",
            "scores": {},
        }
    regime_key = str(regime.get("regime") or "unknown")
    scores = {
        "breadth": _optional_float(regime.get("breadth_score")),
        "trend": _optional_float(regime.get("trend_score")),
        "volume": _optional_float(regime.get("volume_score")),
        "persistence": _optional_float(regime.get("persistence_score")),
    }
    score_parts = [
        f"{label}{score:.2f}"
        for label, score in (
            ("宽度", scores["breadth"]),
            ("趋势", scores["trend"]),
            ("量能", scores["volume"]),
            ("持续", scores["persistence"]),
        )
        if score is not None
    ]
    summary = f"全市场处于{_regime_label_zh(regime_key)}"
    if score_parts:
        summary += f"（{' / '.join(score_parts)}）"
    source_summary = str(regime.get("summary") or "").strip()
    if source_summary:
        summary += f"：{source_summary}"
    return {
        "status": "available" if regime_key != "unknown" else "insufficient_evidence",
        "summary": summary,
        "reason": source_summary or "依据市场宽度、趋势、量能和持续性评分生成。",
        "scores": scores,
    }


def _narrative_sector_ranking_reason(sectors: list[dict[str, Any]]) -> dict[str, Any]:
    if not sectors:
        return {
            "status": "insufficient_evidence",
            "summary": "板块轮动数据缺失，无法解释哪些板块有持续性。",
            "sectors": [],
        }
    sector_reasons = [_narrative_sector_reason(sector) for sector in sectors[:5]]
    summary = "前排板块排序理由：" + "；".join(item["reason"] for item in sector_reasons[:3])
    return {
        "status": "available",
        "summary": summary,
        "sectors": sector_reasons,
    }


def _narrative_sector_reason(sector: dict[str, Any]) -> dict[str, Any]:
    name = str(sector.get("sector_name") or sector.get("sector_code") or "未知板块")
    rank = _optional_int(sector.get("rank_overall"))
    persistence = _optional_float(sector.get("persistence_score"))
    breadth = _optional_float(sector.get("breadth_score"))
    volume = _optional_float(sector.get("volume_score"))
    evidence = sector.get("evidence") if isinstance(sector.get("evidence"), dict) else {}
    evidence_freshness = str(evidence.get("freshness") or sector.get("evidence_freshness") or "missing")
    rank_text = f"排名 #{rank}" if rank is not None else "排名缺失"
    score_text = _narrative_score_text(
        [
            ("持续", persistence),
            ("宽度", breadth),
            ("量能", volume),
        ]
    )
    reason = f"{name}{rank_text}"
    if score_text:
        reason += f"，{score_text}"
    reason += f"，板块证据{_evidence_status_zh(evidence_freshness)}"
    return {
        "sector_code": sector.get("sector_code"),
        "sector_name": name,
        "rank_overall": rank,
        "continuity_hint": sector.get("continuity_hint") or _sector_continuity_hint(sector),
        "evidence_freshness": evidence_freshness,
        "reason": reason,
    }


def _narrative_representative_stock_reason(sectors: list[dict[str, Any]]) -> dict[str, Any]:
    stocks: list[dict[str, Any]] = []
    for sector in sectors[:5]:
        for stock in _narrative_representatives(sector)[:3]:
            stocks.append(_narrative_stock_reason(sector, stock))
    if not stocks:
        return {
            "status": "insufficient_evidence",
            "summary": "代表个股证据不足：缺少 sector_constituents 或板块成员排名。",
            "stocks": [],
        }
    summary = "代表个股理由：" + "；".join(item["reason"] for item in stocks[:5])
    return {
        "status": "available",
        "summary": summary,
        "stocks": stocks,
    }


def _narrative_representatives(sector: dict[str, Any]) -> list[dict[str, Any]]:
    representatives = sector.get("representative_stocks")
    if isinstance(representatives, list):
        return [item for item in representatives if isinstance(item, dict)]
    constituents = sector.get("constituents")
    if isinstance(constituents, list):
        return [item for item in constituents if isinstance(item, dict)]
    return []


def _narrative_stock_reason(sector: dict[str, Any], stock: dict[str, Any]) -> dict[str, Any]:
    sector_name = str(sector.get("sector_name") or sector.get("sector_code") or "未知板块")
    ts_code = str(stock.get("ts_code") or "")
    name = str(stock.get("name") or "")
    rank = _optional_int(stock.get("rank_in_sector"))
    score = _optional_float(stock.get("score"))
    evidence = stock.get("evidence") if isinstance(stock.get("evidence"), dict) else {}
    evidence_freshness = str(evidence.get("freshness") or "missing")
    stock_name = " ".join(part for part in [ts_code, name] if part) or "未知个股"
    rank_text = f"板块内 #{rank}" if rank is not None else "板块内排名缺失"
    score_text = f"，评分 {score:.2f}" if score is not None else ""
    role_text = f"，角色 {stock.get('role')}" if stock.get("role") else ""
    reason = f"{stock_name} 来自{sector_name}，{rank_text}{score_text}{role_text}，个股证据{_evidence_status_zh(evidence_freshness)}"
    return {
        "ts_code": ts_code,
        "name": name,
        "sector_code": sector.get("sector_code"),
        "sector_name": sector_name,
        "rank_in_sector": rank,
        "role": stock.get("role"),
        "score": score,
        "evidence_freshness": evidence_freshness,
        "reason": reason,
    }


def _narrative_evidence_freshness(items: list[dict[str, Any]], as_of_date: str) -> dict[str, str]:
    freshness = _external_freshness_coverage(items, as_of_date)
    news_like_types = {"news", "announcement", "policy", "risk_note", "research_note"}
    news_items = [
        item
        for item in items
        if str(item.get("item_type") or "unknown") in news_like_types
    ]
    sentiment_items = [
        item
        for item in items
        if str(item.get("sentiment") or "unknown") not in {"", "unknown", "none"}
    ]
    return {
        **freshness,
        "news": _external_scope_freshness(news_items, as_of_date),
        "sentiment": _external_scope_freshness(sentiment_items, as_of_date),
    }


def _market_review_narrative_evidence_gaps(
    *,
    sectors: list[dict[str, Any]],
    external_items: list[dict[str, Any]],
    plan_relationships: list[dict[str, Any]],
    evidence_freshness: dict[str, str],
) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    if not sectors:
        gaps.append(
            {
                "scope": "sector_data",
                "status": "missing",
                "message": "板块轮动数据缺失，板块排名和持续性证据不足。",
            }
        )
    for scope, label in (
        ("market", "市场级新闻/情绪证据"),
        ("sector", "板块新闻/情绪证据"),
        ("stock", "个股新闻/情绪证据"),
        ("news", "新闻证据"),
        ("sentiment", "情绪证据"),
    ):
        status = str(evidence_freshness.get(scope) or "missing")
        if status in {"missing", "stale", "partial", "unavailable"}:
            gaps.append(
                {
                    "scope": scope,
                    "status": status,
                    "message": f"{label}{_evidence_gap_suffix(status)}，不能编造支持性证据。",
                }
            )
    if not external_items and not any(gap["scope"] == "news" for gap in gaps):
        gaps.append({"scope": "news", "status": "missing", "message": "新闻证据缺失，不能编造新闻支持。"})
    if not plan_relationships:
        gaps.append(
            {
                "scope": "next_day_plan",
                "status": "missing",
                "message": "明日计划关系缺失，不能自动推导交易动作。",
            }
        )
    return gaps


def _narrative_continuity_judgement(continuity: dict[str, Any]) -> dict[str, Any]:
    label = str(continuity.get("label") or "insufficient_evidence")
    reason = str(continuity.get("reason") or "连续性输入缺失。")
    return {
        "label": label,
        "summary": f"连续性判断为{_continuity_label_zh(label)}；{reason}",
        "reason": reason,
        "inputs": continuity.get("inputs") if isinstance(continuity.get("inputs"), dict) else {},
    }


def _narrative_next_day_plan_relationship(plan_relationships: list[dict[str, Any]]) -> dict[str, Any]:
    if not plan_relationships:
        return {
            "relationship_label": "missing",
            "summary": "明日计划关系缺失，不能从复盘自动推导交易动作。",
            "relationships": [],
        }
    first = plan_relationships[0]
    label = str(first.get("relationship_label") or "missing")
    reason = str(first.get("relationship_reason") or "暂无计划关系说明。")
    return {
        "relationship_label": label,
        "summary": f"明日计划关系为{_plan_relationship_label_zh(label)}；{reason}",
        "relationships": plan_relationships,
    }


def _narrative_score_text(items: list[tuple[str, float | None]]) -> str:
    return " / ".join(f"{label}{score:.2f}" for label, score in items if score is not None)


def _regime_label_zh(value: str) -> str:
    return {
        "risk_on": "风险偏好",
        "neutral": "中性震荡",
        "risk_off": "风险收缩",
        "unknown": "未知",
    }.get(value, value)


def _continuity_label_zh(value: str) -> str:
    return {
        "improving": "改善",
        "fading": "转弱",
        "crowded": "拥挤",
        "divergent": "分化",
        "insufficient_evidence": "证据不足",
    }.get(value, value)


def _plan_relationship_label_zh(value: str) -> str:
    return {
        "aligned": "顺势匹配",
        "cautious": "谨慎观察",
        "blocked": "阻断",
        "missing": "缺失",
    }.get(value, value)


def _evidence_status_zh(value: str) -> str:
    return {
        "fresh": "新鲜",
        "available": "可用",
        "partial": "部分可用",
        "stale": "过期",
        "missing": "缺失",
        "unavailable": "不可用",
    }.get(value, value)


def _evidence_gap_suffix(status: str) -> str:
    return {
        "missing": "缺失",
        "stale": "过期/不可用",
        "partial": "不完整",
        "unavailable": "不可用",
    }.get(status, "证据不足")


def _sector_hierarchy_payload(
    sector: dict[str, Any],
    external_items: list[dict[str, Any]],
) -> dict[str, Any]:
    sector_code = str(sector.get("sector_code") or "")
    sector_name = str(sector.get("sector_name") or sector_code)
    sector_items = _external_items_for_sector(external_items, sector_code, sector_name)
    representative_stocks = [
        _representative_stock_payload(stock, external_items)
        for stock in (sector.get("constituents") or [])[:3]
        if isinstance(stock, dict)
    ]
    return {
        "sector_code": sector_code,
        "sector_name": sector_name,
        "rank_overall": sector.get("rank_overall"),
        "persistence_score": sector.get("persistence_score"),
        "breadth_score": sector.get("breadth_score"),
        "volume_score": sector.get("volume_score"),
        "leader_count": sector.get("leader_count"),
        "continuity_hint": _sector_continuity_hint(sector),
        "representative_stocks": representative_stocks,
        "evidence": _evidence_summary(sector_items),
        "source_refs": [f"sector_daily_snapshots:{sector_code}"] + [
            f"sector_constituents:{sector_code}:{stock['ts_code']}"
            for stock in representative_stocks
            if stock.get("ts_code")
        ],
    }


def _representative_stock_payload(
    stock: dict[str, Any],
    external_items: list[dict[str, Any]],
) -> dict[str, Any]:
    ts_code = str(stock.get("ts_code") or "")
    stock_items = _external_items_for_stock(external_items, ts_code)
    return {
        "ts_code": ts_code,
        "name": stock.get("name"),
        "rank_in_sector": stock.get("rank_in_sector"),
        "role": stock.get("role"),
        "score": stock.get("score"),
        "evidence": _evidence_summary(stock_items),
        "source_refs": [f"sector_constituents:{stock.get('sector_code')}:{ts_code}"] if ts_code else [],
    }


def _sector_continuity_hint(sector: dict[str, Any]) -> str:
    persistence = _optional_float(sector.get("persistence_score"))
    breadth = _optional_float(sector.get("breadth_score"))
    volume = _optional_float(sector.get("volume_score"))
    if persistence is None and breadth is None and volume is None:
        return "insufficient_evidence"
    if volume is not None and volume >= 0.75 and (breadth is None or breadth < 0.45):
        return "crowded"
    if persistence is not None and persistence >= 0.65 and (breadth is None or breadth >= 0.5):
        return "improving"
    if persistence is not None and persistence < 0.35:
        return "fading"
    return "divergent"


def _evidence_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "item_count": len(items),
        "freshness": (
            "missing"
            if not items
            else "fresh"
            if all(item.get("published_date") == item.get("as_of_date") for item in items)
            else "partial"
        ),
        "by_type": _count_by(items, "item_type"),
        "by_sentiment": _count_by(items, "sentiment"),
        "source_refs": [f"market_external_items:{item.get('market_external_item_id')}" for item in items],
    }


def _external_items_for_sector(
    items: list[dict[str, Any]],
    sector_code: str,
    sector_name: str,
) -> list[dict[str, Any]]:
    keys = {sector_code, sector_name}
    return [
        item
        for item in items
        if item.get("scope_type") == "sector" and str(item.get("scope_key") or "") in keys
    ]


def _external_items_for_stock(items: list[dict[str, Any]], ts_code: str) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if item.get("scope_type") == "stock" and str(item.get("scope_key") or "") == ts_code
    ]


def _continuity_payload(
    regime: dict[str, Any] | None,
    sectors: list[dict[str, Any]],
    external_items: list[dict[str, Any]],
) -> dict[str, Any]:
    if regime is None or not sectors or not external_items:
        missing: list[str] = []
        if regime is None:
            missing.append("market_regime_snapshots")
        if not sectors:
            missing.append("sector_daily_snapshots")
        if not external_items:
            missing.append("market_external_items")
        return {
            "label": "insufficient_evidence",
            "reason": f"缺少 {', '.join(missing)}，连续性判断保持证据不足。",
            "inputs": {"missing": missing},
        }

    scores = [
        _optional_float(regime.get("breadth_score")),
        _optional_float(regime.get("trend_score")),
        _optional_float(regime.get("volume_score")),
        _optional_float(regime.get("persistence_score")),
    ]
    known_scores = [score for score in scores if score is not None]
    top_sector = sectors[0] if sectors else {}
    top_persistence = _optional_float(top_sector.get("persistence_score"))
    breadth, trend, volume, persistence = scores

    if volume is not None and volume >= 0.75 and (breadth is None or breadth < 0.45):
        label = "crowded"
        reason = "量能较强但市场宽度不足，需防止拥挤交易。"
    elif known_scores and max(known_scores) - min(known_scores) >= 0.4:
        label = "divergent"
        reason = "市场宽度、趋势、量能或持续性分化较大。"
    elif (trend is not None and trend < 0.45) or (persistence is not None and persistence < 0.45):
        label = "fading"
        reason = "趋势或持续性偏弱，强势延续正在转弱。"
    elif (
        breadth is not None
        and breadth >= 0.55
        and trend is not None
        and trend >= 0.55
        and persistence is not None
        and persistence >= 0.55
        and (top_persistence is None or top_persistence >= 0.5)
    ):
        label = "improving"
        reason = "市场宽度、趋势和持续性同步改善，且前排板块未明显走弱。"
    else:
        label = "divergent"
        reason = "证据可用但尚未形成一致的改善或转弱信号。"

    return {
        "label": label,
        "reason": reason,
        "inputs": {
            "breadth_score": breadth,
            "trend_score": trend,
            "volume_score": volume,
            "persistence_score": persistence,
            "top_sector_persistence_score": top_persistence,
            "external_item_count": len(external_items),
        },
    }


def _plan_relationship_payload(context: dict[str, Any], continuity_label: str) -> dict[str, Any]:
    label = _plan_relationship_label(context)
    evidence = context.get("evidence") if isinstance(context.get("evidence"), dict) else {}
    candidate = evidence.get("candidate") if isinstance(evidence.get("candidate"), dict) else {}
    return {
        "trade_plan_id": context.get("trade_plan_id"),
        "market_plan_context_id": context.get("market_plan_context_id"),
        "relationship_label": label,
        "relationship_reason": _plan_relationship_reason(context, label, continuity_label),
        "alignment": context.get("alignment"),
        "risk_level": context.get("risk_level"),
        "management_action": context.get("management_action"),
        "rationale": context.get("rationale"),
        "candidate": candidate,
        "source_refs": [
            f"market_plan_contexts:{context.get('market_review_run_id')}:{context.get('trade_plan_id')}"
        ],
    }


def _plan_relationship_label(context: dict[str, Any]) -> str:
    alignment = str(context.get("alignment") or "unknown")
    risk_level = str(context.get("risk_level") or "unknown")
    management_action = str(context.get("management_action") or "unknown")
    if management_action == "consider_cancel" or risk_level == "high" or alignment == "conflict":
        return "blocked"
    if alignment == "aligned" and risk_level == "low" and management_action == "proceed":
        return "aligned"
    if alignment == "unknown" or risk_level == "unknown" or management_action == "unknown":
        return "missing"
    return "cautious"


def _plan_relationship_reason(context: dict[str, Any], label: str, continuity_label: str) -> str:
    if label == "aligned":
        return f"计划与前排板块和证据方向一致；连续性为 {continuity_label}，仍需人工开盘检查。"
    if label == "blocked":
        return "计划存在冲突、高风险或考虑取消信号；系统只提示，不会自动取消或执行。"
    if label == "missing":
        return "计划关系缺少可用市场、板块或证据输入，不能当作安全信号。"
    return f"计划有部分支持但仍需谨慎；连续性为 {continuity_label}。"


def _market_hierarchy_source_refs(
    run_id: int,
    sector_nodes: list[dict[str, Any]],
    external_items: list[dict[str, Any]],
    contexts: list[dict[str, Any]],
) -> list[str]:
    refs = [f"market_review_runs:{run_id}", f"market_regime_snapshots:{run_id}"]
    for sector in sector_nodes:
        refs.extend(str(ref) for ref in sector.get("source_refs", []))
    refs.extend(f"market_external_items:{item.get('market_external_item_id')}" for item in external_items)
    refs.extend(
        f"market_plan_contexts:{context.get('market_review_run_id')}:{context.get('trade_plan_id')}"
        for context in contexts
    )
    deduped: list[str] = []
    for ref in refs:
        if ref and ref not in deduped:
            deduped.append(ref)
    return deduped


def _market_review_diagnostics(
    conn: sqlite3.Connection,
    db_path: Path,
    as_of_date: str,
    *,
    run_id: int | None,
    missing_data: list[str],
) -> dict[str, Any]:
    latest = _latest_market_review_run(conn)
    downstream = _market_review_downstream_status(conn, as_of_date, run_id)
    missing_downstream = [
        table
        for table, status in downstream.items()
        if table != "market_review_runs" and (not status["exists"] or int(status["count"] or 0) == 0)
    ]
    reasons = _market_review_empty_state_reasons(
        as_of_date,
        latest_date=latest["as_of_date"] if latest is not None else None,
        run_id=run_id,
        downstream=downstream,
        missing_data=missing_data,
    )
    return {
        "selected_market_date": as_of_date,
        "latest_market_review_date": latest["as_of_date"] if latest is not None else None,
        "latest_market_review_run_id": int(latest["id"]) if latest is not None else None,
        "source_db": _source_db_status(db_path),
        "downstream_tables": downstream,
        "missing_downstream_tables": missing_downstream,
        "empty_state_reasons": reasons,
    }


def _latest_market_review_run(conn: sqlite3.Connection) -> sqlite3.Row | None:
    if not _table_exists(conn, "market_review_runs"):
        return None
    return conn.execute(
        """
        SELECT id, as_of_date, completed_at, created_at
        FROM market_review_runs
        ORDER BY as_of_date DESC, id DESC
        LIMIT 1
        """
    ).fetchone()


def _market_review_downstream_status(
    conn: sqlite3.Connection,
    as_of_date: str,
    run_id: int | None,
) -> dict[str, dict[str, Any]]:
    return {
        "market_review_runs": _table_status(
            conn,
            "market_review_runs",
            "as_of_date = ?",
            (as_of_date,),
        ),
        "market_regime_snapshots": _table_status(
            conn,
            "market_regime_snapshots",
            "market_review_run_id = ?",
            (run_id,),
            require_run_id=run_id,
        ),
        "sector_daily_snapshots": _table_status(
            conn,
            "sector_daily_snapshots",
            "market_review_run_id = ?",
            (run_id,),
            require_run_id=run_id,
        ),
        "sector_constituents": _table_status(
            conn,
            "sector_constituents",
            "market_review_run_id = ?",
            (run_id,),
            require_run_id=run_id,
        ),
        "market_external_items": _table_status(
            conn,
            "market_external_items",
            "as_of_date = ?",
            (as_of_date,),
        ),
        "market_plan_contexts": _table_status(
            conn,
            "market_plan_contexts",
            "market_review_run_id = ?",
            (run_id,),
            require_run_id=run_id,
        ),
        "strategy_hypotheses": _table_status(
            conn,
            "strategy_hypotheses",
            "as_of_date = ?",
            (as_of_date,),
        ),
    }


def _table_status(
    conn: sqlite3.Connection,
    table: str,
    where_clause: str,
    params: tuple[Any, ...],
    *,
    require_run_id: int | None = None,
) -> dict[str, Any]:
    exists = _table_exists(conn, table)
    if not exists:
        return {"exists": False, "count": None, "status": "missing_table"}
    if require_run_id is None and "market_review_run_id" in where_clause:
        return {"exists": True, "count": 0, "status": "missing_review"}
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE {where_clause}", params).fetchone()
    count = int(row["count"]) if row is not None else 0
    return {"exists": True, "count": count, "status": "available" if count else "empty"}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _source_db_status(db_path: Path) -> dict[str, Any]:
    path = Path(db_path)
    exists = path.exists()
    payload: dict[str, Any] = {
        "configured": True,
        "exists": exists,
        "label": path.name,
        "modified_at": None,
        "size_bytes": None,
    }
    if not exists:
        payload["freshness"] = "missing"
        return payload
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    payload["modified_at"] = modified_at.isoformat().replace("+00:00", "Z")
    payload["size_bytes"] = stat.st_size
    payload["freshness"] = _source_db_freshness(stat.st_mtime)
    return payload


def _source_db_freshness(modified_at: float) -> str:
    age_seconds = max(0.0, datetime.now(tz=timezone.utc).timestamp() - modified_at)
    if age_seconds <= 36 * 60 * 60:
        return "fresh"
    if age_seconds <= 7 * 24 * 60 * 60:
        return "stale"
    return "old"


def _market_review_empty_state_reasons(
    as_of_date: str,
    *,
    latest_date: str | None,
    run_id: int | None,
    downstream: dict[str, dict[str, Any]],
    missing_data: list[str],
) -> list[dict[str, str]]:
    reasons: list[dict[str, str]] = []
    if run_id is None:
        reason = {
            "code": "MARKET_REVIEW_RUN_MISSING",
            "message": f"{as_of_date} 没有 market_review_runs 记录。",
        }
        if latest_date and latest_date != as_of_date:
            relation = "早于" if as_of_date < latest_date else "晚于"
            reason["message"] = (
                f"{as_of_date} 没有 market_review_runs 记录；最新全市场复盘是 {latest_date}，当前选择{relation}最新日期。"
            )
        reasons.append(reason)
        return reasons

    code_by_table = {
        "market_regime_snapshots": "MARKET_REGIME_SNAPSHOT_MISSING",
        "sector_daily_snapshots": "SECTOR_SNAPSHOTS_MISSING",
        "sector_constituents": "SECTOR_CONSTITUENTS_MISSING",
        "market_external_items": "MARKET_EXTERNAL_EVIDENCE_MISSING",
        "market_plan_contexts": "MARKET_PLAN_CONTEXT_MISSING",
        "strategy_hypotheses": "STRATEGY_HYPOTHESES_MISSING",
    }
    for table in missing_data:
        if table == "provider_manifest_json" or table == "coverage_json":
            reasons.append(
                {
                    "code": f"{table.upper()}_MISSING",
                    "message": f"{table} 为空，说明该复盘缺少来源或覆盖率元数据。",
                }
            )
            continue
        status = downstream.get(table)
        if status is None:
            continue
        reasons.append(
            {
                "code": code_by_table.get(table, f"{table.upper()}_MISSING"),
                "message": f"{table} 当前计数为 {status['count']}; 面板会保持空状态。",
            }
        )
    return reasons


def _regime_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "market_review_run_id": int(row["market_review_run_id"]),
        "as_of_date": row["as_of_date"],
        "regime": row["regime"],
        "breadth_score": row["breadth_score"],
        "trend_score": row["trend_score"],
        "volume_score": row["volume_score"],
        "sentiment_score": row["sentiment_score"],
        "persistence_score": row["persistence_score"],
        "summary": row["summary"],
        "metrics": _json_loads(row["metrics_json"]),
    }


def _load_market_review_sector_payloads(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
    sector_rows = conn.execute(
        """
        SELECT
          market_review_run_id,
          as_of_date,
          sector_code,
          sector_name,
          provider,
          rank_overall,
          return_1d,
          return_3d,
          return_5d,
          return_10d,
          breadth_score,
          volume_score,
          persistence_score,
          leader_count,
          metrics_json
        FROM sector_daily_snapshots
        WHERE market_review_run_id = ?
        ORDER BY rank_overall IS NULL, rank_overall ASC, sector_code ASC
        """,
        (run_id,),
    ).fetchall()
    constituent_rows = conn.execute(
        """
        SELECT
          market_review_run_id,
          sector_code,
          sector_name,
          ts_code,
          name,
          rank_in_sector,
          role,
          score,
          metrics_json
        FROM sector_constituents
        WHERE market_review_run_id = ?
        ORDER BY sector_code ASC, rank_in_sector IS NULL, rank_in_sector ASC, ts_code ASC
        """,
        (run_id,),
    ).fetchall()

    constituents_by_sector: dict[str, list[dict[str, Any]]] = {}
    for row in constituent_rows:
        constituents_by_sector.setdefault(row["sector_code"], []).append(
            {
                "market_review_run_id": int(row["market_review_run_id"]),
                "sector_code": row["sector_code"],
                "sector_name": row["sector_name"],
                "ts_code": row["ts_code"],
                "name": row["name"],
                "rank_in_sector": row["rank_in_sector"],
                "role": row["role"],
                "score": row["score"],
                "metrics": _json_loads(row["metrics_json"]),
            }
        )

    sectors: list[dict[str, Any]] = []
    for row in sector_rows:
        sectors.append(
            {
                "market_review_run_id": int(row["market_review_run_id"]),
                "as_of_date": row["as_of_date"],
                "sector_code": row["sector_code"],
                "sector_name": row["sector_name"],
                "provider": row["provider"],
                "rank_overall": row["rank_overall"],
                "return_1d": row["return_1d"],
                "return_3d": row["return_3d"],
                "return_5d": row["return_5d"],
                "return_10d": row["return_10d"],
                "breadth_score": row["breadth_score"],
                "volume_score": row["volume_score"],
                "persistence_score": row["persistence_score"],
                "leader_count": row["leader_count"],
                "metrics": _json_loads(row["metrics_json"]),
                "constituents": constituents_by_sector.get(row["sector_code"], []),
            }
        )
    return sectors


def _sectors_payload(as_of_date: str, run_id: int, sectors: list[dict[str, Any]]) -> dict[str, Any]:
    constituent_count = sum(len(sector["constituents"]) for sector in sectors)
    missing_data: list[str] = []
    if not sectors:
        missing_data.append("sector_daily_snapshots")
    elif constituent_count == 0:
        missing_data.append("sector_constituents")
    return {
        "market_review_run_id": run_id,
        "as_of_date": as_of_date,
        "sectors": sectors,
        "source": _source_payload(["market_review_runs", "sector_daily_snapshots", "sector_constituents"]),
        "coverage": {
            "has_review": True,
            "sector_count": len(sectors),
            "constituent_count": constituent_count,
        },
        "missing_data": missing_data,
    }


def _empty_sectors_payload(as_of_date: str, *, has_review: bool) -> dict[str, Any]:
    missing_data = ["sector_daily_snapshots", "sector_constituents"]
    if not has_review:
        missing_data.insert(0, "market_review_runs")
    return {
        "market_review_run_id": None,
        "as_of_date": as_of_date,
        "sectors": [],
        "source": _source_payload(["market_review_runs", "sector_daily_snapshots", "sector_constituents"]),
        "coverage": {"has_review": has_review, "sector_count": 0, "constituent_count": 0},
        "missing_data": missing_data,
    }


def _load_market_external_item_payloads(conn: sqlite3.Connection, as_of_date: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          id,
          as_of_date,
          scope_type,
          scope_key,
          item_type,
          provider,
          title,
          summary,
          url,
          sentiment,
          importance,
          published_date,
          metadata_json,
          source_hash,
          created_at
        FROM market_external_items
        WHERE as_of_date = ?
        ORDER BY published_date DESC, importance DESC, id DESC
        """,
        (as_of_date,),
    ).fetchall()
    return [
        {
            "market_external_item_id": int(row["id"]),
            "as_of_date": row["as_of_date"],
            "scope_type": row["scope_type"],
            "scope_key": row["scope_key"],
            "item_type": row["item_type"],
            "provider": row["provider"],
            "title": row["title"],
            "summary": row["summary"],
            "url": row["url"],
            "sentiment": row["sentiment"],
            "importance": row["importance"],
            "published_date": row["published_date"],
            "metadata": _json_loads(row["metadata_json"]),
            "source_hash": row["source_hash"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _external_items_payload(
    as_of_date: str,
    run_id: int | None,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    missing_data: list[str] = []
    if run_id is None:
        missing_data.append("market_review_runs")
    if not items:
        missing_data.append("market_external_items")
    return {
        "market_review_run_id": run_id,
        "as_of_date": as_of_date,
        "items": items,
        "source": _source_payload(["market_review_runs", "market_external_items"]),
        "coverage": {
            "has_review": run_id is not None,
            "item_count": len(items),
            "by_scope": _count_by(items, "scope_type"),
            "by_sentiment": _count_by(items, "sentiment"),
            "scope": _external_scope_coverage(items),
            "freshness": _external_freshness_coverage(items, as_of_date),
            "source_hash": _external_source_hash_coverage(items),
        },
        "missing_data": missing_data,
    }


def _empty_external_items_payload(as_of_date: str, *, has_review: bool) -> dict[str, Any]:
    missing_data = ["market_external_items"]
    if not has_review:
        missing_data.insert(0, "market_review_runs")
    return {
        "market_review_run_id": None,
        "as_of_date": as_of_date,
        "items": [],
        "source": _source_payload(["market_review_runs", "market_external_items"]),
        "coverage": {
            "has_review": has_review,
            "item_count": 0,
            "by_scope": {},
            "by_sentiment": {},
            "scope": {"market": "missing", "sector": "missing", "stock": "missing"},
            "freshness": {"market": "missing", "sector": "missing", "stock": "missing"},
            "source_hash": "missing",
        },
        "missing_data": missing_data,
    }


def _load_strategy_hypothesis_payloads(
    conn: sqlite3.Connection,
    request: ListMarketReviewHypothesesRequest,
) -> list[dict[str, Any]]:
    clauses = ["as_of_date = ?"]
    params: list[Any] = [request.as_of_date]
    if request.status is not None:
        clauses.append("status = ?")
        params.append(request.status)
    params.append(request.limit)
    rows = conn.execute(
        f"""
        SELECT
          id,
          as_of_date,
          hypothesis_type,
          title,
          rationale,
          evidence_json,
          proposed_change_json,
          status,
          created_at
        FROM strategy_hypotheses
        WHERE {" AND ".join(clauses)}
        ORDER BY id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        {
            "hypothesis_id": int(row["id"]),
            "as_of_date": row["as_of_date"],
            "hypothesis_type": row["hypothesis_type"],
            "title": row["title"],
            "rationale": row["rationale"],
            "evidence": _json_loads(row["evidence_json"]),
            "proposed_change": _json_loads(row["proposed_change_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _hypotheses_payload(
    as_of_date: str,
    run_id: int | None,
    hypotheses: list[dict[str, Any]],
    request: ListMarketReviewHypothesesRequest,
) -> dict[str, Any]:
    missing_data: list[str] = []
    if run_id is None:
        missing_data.append("market_review_runs")
    if not hypotheses:
        missing_data.append("strategy_hypotheses")
    return {
        "market_review_run_id": run_id,
        "as_of_date": as_of_date,
        "status_filter": request.status,
        "limit": request.limit,
        "hypotheses": hypotheses,
        "source": _source_payload(["market_review_runs", "strategy_hypotheses"]),
        "coverage": {
            "has_review": run_id is not None,
            "hypothesis_count": len(hypotheses),
            "by_status": _count_by(hypotheses, "status"),
        },
        "missing_data": missing_data,
    }


def _empty_hypotheses_payload(as_of_date: str, *, has_review: bool) -> dict[str, Any]:
    missing_data = ["strategy_hypotheses"]
    if not has_review:
        missing_data.insert(0, "market_review_runs")
    return {
        "market_review_run_id": None,
        "as_of_date": as_of_date,
        "status_filter": None,
        "limit": 0,
        "hypotheses": [],
        "source": _source_payload(["market_review_runs", "strategy_hypotheses"]),
        "coverage": {"has_review": has_review, "hypothesis_count": 0, "by_status": {}},
        "missing_data": missing_data,
    }


def _load_market_plan_context_payloads(
    conn: sqlite3.Connection,
    run_id: int,
    trade_plan_id: int | None,
) -> list[dict[str, Any]]:
    clauses = ["market_review_run_id = ?"]
    params: list[Any] = [run_id]
    if trade_plan_id is not None:
        clauses.append("trade_plan_id = ?")
        params.append(trade_plan_id)
    rows = conn.execute(
        f"""
        SELECT
          id,
          market_review_run_id,
          trade_plan_id,
          alignment,
          risk_level,
          management_action,
          rationale,
          evidence_json,
          created_at
        FROM market_plan_contexts
        WHERE {" AND ".join(clauses)}
        ORDER BY id ASC
        """,
        params,
    ).fetchall()
    contexts: list[dict[str, Any]] = []
    for row in rows:
        context = {
            "market_plan_context_id": int(row["id"]),
            "market_review_run_id": int(row["market_review_run_id"]),
            "trade_plan_id": int(row["trade_plan_id"]),
            "alignment": row["alignment"],
            "risk_level": row["risk_level"],
            "management_action": row["management_action"],
            "rationale": row["rationale"],
            "evidence": _json_loads(row["evidence_json"]),
            "created_at": row["created_at"],
        }
        label = _plan_relationship_label(context)
        context["relationship_label"] = label
        context["relationship_reason"] = _plan_relationship_reason(context, label, "unknown")
        context["source_refs"] = [
            f"market_plan_contexts:{context['market_review_run_id']}:{context['trade_plan_id']}"
        ]
        contexts.append(context)
    return contexts


def _plan_context_payload(
    as_of_date: str,
    run_id: int,
    contexts: list[dict[str, Any]],
    trade_plan_id: int | None,
) -> dict[str, Any]:
    return {
        "market_review_run_id": run_id,
        "as_of_date": as_of_date,
        "trade_plan_id": trade_plan_id,
        "contexts": contexts,
        "source": _source_payload(["market_review_runs", "market_plan_contexts"]),
        "coverage": {
            "has_review": True,
            "context_count": len(contexts),
            "trade_plan_id": trade_plan_id,
            "by_relationship": _count_by(contexts, "relationship_label"),
        },
        "missing_data": [] if contexts else ["market_plan_contexts"],
    }


def _empty_plan_context_payload(
    as_of_date: str,
    *,
    has_review: bool,
    trade_plan_id: int | None,
) -> dict[str, Any]:
    missing_data = ["market_plan_contexts"]
    if not has_review:
        missing_data.insert(0, "market_review_runs")
    return {
        "market_review_run_id": None,
        "as_of_date": as_of_date,
        "trade_plan_id": trade_plan_id,
        "contexts": [],
        "source": _source_payload(["market_review_runs", "market_plan_contexts"]),
        "coverage": {
            "has_review": has_review,
            "context_count": 0,
            "trade_plan_id": trade_plan_id,
            "by_relationship": {},
        },
        "missing_data": missing_data,
    }


def _source_payload(tables: list[str], provider_manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"tables": tables}
    if provider_manifest is not None:
        payload["provider_manifest"] = provider_manifest
    return payload


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = item.get(key)
        label = "unknown" if value is None else str(value)
        counts[label] = counts.get(label, 0) + 1
    return counts


def _external_scope_coverage(items: list[dict[str, Any]]) -> dict[str, str]:
    return {
        "market": "available" if _items_for_scope(items, "market") else "missing",
        "sector": "partial" if _items_for_scope(items, "sector") else "missing",
        "stock": "partial" if _items_for_scope(items, "stock") else "missing",
    }


def _external_freshness_coverage(items: list[dict[str, Any]], as_of_date: str) -> dict[str, str]:
    return {
        scope_type: _external_scope_freshness(_items_for_scope(items, scope_type), as_of_date)
        for scope_type in ("market", "sector", "stock")
    }


def _external_scope_freshness(items: list[dict[str, Any]], as_of_date: str) -> str:
    if not items:
        return "missing"
    fresh_count = sum(1 for item in items if item.get("published_date") == as_of_date)
    if fresh_count == len(items):
        return "fresh"
    if fresh_count == 0:
        return "stale"
    return "partial"


def _external_source_hash_coverage(items: list[dict[str, Any]]) -> str:
    if not items:
        return "missing"
    hashed_count = sum(1 for item in items if str(item.get("source_hash") or "").strip())
    if hashed_count == len(items):
        return "available"
    if hashed_count == 0:
        return "missing"
    return "partial"


def _items_for_scope(items: list[dict[str, Any]], scope_type: str) -> list[dict[str, Any]]:
    return [item for item in items if item.get("scope_type") == scope_type]


def _build_regime_snapshot(conn: sqlite3.Connection, request: RunMarketReviewRequest) -> _RegimeSnapshot:
    bars_by_code = _load_regime_market_bars(conn, request.as_of_date)
    universe_count = len(bars_by_code)
    covered_codes = [
        ts_code
        for ts_code, bars in bars_by_code.items()
        if bars and bars[-1].trade_date == request.as_of_date and bars[-1].close is not None
    ]
    covered_count = len(covered_codes)
    coverage_ratio = _rounded_ratio(covered_count, universe_count)
    coverage = _regime_coverage_payload(request, universe_count, covered_count, coverage_ratio)
    manifest = _regime_manifest_payload(request)

    if universe_count == 0 or covered_count == 0 or coverage_ratio < request.min_coverage:
        warning = (
            "MARKET_REVIEW_COVERAGE_LOW",
            (
                "Market review coverage is below the required threshold: "
                f"{covered_count}/{universe_count} ({coverage_ratio:.4f}) for {request.as_of_date}."
            ),
        )
        summary = (
            "Market review blocked: market_bars coverage is below "
            f"{request.min_coverage:.2f} for {request.as_of_date}."
        )
        result = MarketRegimeResult(
            market_review_run_id=None,
            as_of_date=request.as_of_date,
            status="blocked",
            regime="unknown",
            breadth_score=None,
            trend_score=None,
            volume_score=None,
            persistence_score=None,
            coverage_ratio=coverage_ratio,
            summary=summary,
            warnings=[warning[1]],
        )
        return _RegimeSnapshot(
            result=result,
            metrics={
                "advance_decline_ratio": None,
                "above_ma5_ratio": None,
                "volume_expansion_ratio": None,
                "new_5d_high_ratio": None,
                "new_5d_low_ratio": None,
                "persistence_score": None,
            },
            coverage=coverage,
            manifest=manifest,
            warning_details=[warning],
        )

    metrics, warning_details = _calculate_regime_metrics(bars_by_code, covered_codes)
    breadth_score = metrics["advance_decline_ratio"]
    trend_score = _average_optional(
        [
            metrics["above_ma5_ratio"],
            metrics["new_5d_high_ratio"],
            _inverse_optional(metrics["new_5d_low_ratio"]),
        ]
    )
    volume_score = metrics["volume_expansion_ratio"]
    persistence_score = metrics["persistence_score"]
    regime = _classify_regime(breadth_score, trend_score, volume_score, persistence_score)
    summary = _summarize_regime(
        regime=regime,
        breadth_score=breadth_score,
        trend_score=trend_score,
        volume_score=volume_score,
        persistence_score=persistence_score,
        coverage_ratio=coverage_ratio,
    )
    metrics = {
        **metrics,
        "breadth_score": breadth_score,
        "trend_score": trend_score,
        "volume_score": volume_score,
        "regime": regime,
        "covered_symbol_count": covered_count,
    }
    result = MarketRegimeResult(
        market_review_run_id=None,
        as_of_date=request.as_of_date,
        status="success",
        regime=regime,
        breadth_score=breadth_score,
        trend_score=trend_score,
        volume_score=volume_score,
        persistence_score=persistence_score,
        coverage_ratio=coverage_ratio,
        summary=summary,
        warnings=[message for _, message in warning_details],
    )
    return _RegimeSnapshot(
        result=result,
        metrics=metrics,
        coverage=coverage,
        manifest=manifest,
        warning_details=warning_details,
    )


def _load_regime_market_bars(conn: sqlite3.Connection, as_of_date: str) -> dict[str, list[_MarketBar]]:
    rows = conn.execute(
        """
        SELECT ts_code, trade_date, close, vol
        FROM market_bars
        WHERE trade_date <= ?
        ORDER BY ts_code, trade_date
        """,
        (as_of_date,),
    ).fetchall()
    bars_by_code: dict[str, list[_MarketBar]] = {}
    for row in rows:
        bars_by_code.setdefault(row["ts_code"], []).append(
            _MarketBar(
                ts_code=row["ts_code"],
                trade_date=row["trade_date"],
                close=_optional_float(row["close"]),
                vol=_optional_float(row["vol"]),
            )
        )
    return bars_by_code


def _calculate_regime_metrics(
    bars_by_code: dict[str, list[_MarketBar]],
    covered_codes: list[str],
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    advanced: list[bool] = []
    above_ma5: list[bool] = []
    volume_expansion: list[bool] = []
    new_5d_high: list[bool] = []
    new_5d_low: list[bool] = []
    persistence: list[bool] = []
    shallow_history_count = 0

    for ts_code in covered_codes:
        bars = bars_by_code[ts_code]
        closes = [bar.close for bar in bars if bar.close is not None]
        volumes = [bar.vol for bar in bars if bar.vol is not None]
        if len(closes) >= 2:
            advanced.append(closes[-1] > closes[-2])
        else:
            shallow_history_count += 1
        if len(closes) >= 5:
            last5 = closes[-5:]
            above_ma5.append(closes[-1] > mean(last5))
            new_5d_high.append(closes[-1] >= max(last5))
            new_5d_low.append(closes[-1] <= min(last5))
        else:
            shallow_history_count += 1
        if len(volumes) >= 5:
            volume_expansion.append(volumes[-1] > mean(volumes[-5:]))
        else:
            shallow_history_count += 1
        if len(closes) >= 3:
            persistence.append(closes[-1] > closes[-2] > closes[-3])
        else:
            shallow_history_count += 1

    warnings: list[tuple[str, str]] = []
    if shallow_history_count:
        warnings.append(
            (
                "MARKET_REVIEW_HISTORY_SHALLOW",
                f"{shallow_history_count} metric input(s) lacked enough history for a full 5-day review.",
            )
        )
    return (
        {
            "advance_decline_ratio": _ratio(advanced),
            "above_ma5_ratio": _ratio(above_ma5),
            "volume_expansion_ratio": _ratio(volume_expansion),
            "new_5d_high_ratio": _ratio(new_5d_high),
            "new_5d_low_ratio": _ratio(new_5d_low),
            "persistence_score": _ratio(persistence),
        },
        warnings,
    )


def _persist_regime_snapshot(conn: sqlite3.Connection, snapshot: _RegimeSnapshot) -> tuple[int, bool]:
    result = snapshot.result
    provider_manifest = {"market_regime": snapshot.manifest}
    coverage = {"market_regime": snapshot.coverage}
    summary = {
        "market_regime": {
            "status": result.status,
            "regime": result.regime,
            "summary": result.summary,
            "warnings": result.warnings,
            "metrics": snapshot.metrics,
        }
    }

    existing = conn.execute(
        """
        SELECT id, status, provider_manifest_json, coverage_json, summary_json
        FROM market_review_runs
        WHERE as_of_date = ?
        """,
        (result.as_of_date,),
    ).fetchone()
    if existing is None:
        run_id = _upsert_market_review_run(
            conn,
            result.as_of_date,
            provider_manifest=provider_manifest,
            coverage=coverage,
            summary=summary,
        )
        _upsert_regime_snapshot(conn, run_id, snapshot)
        return run_id, True

    run_id = int(existing["id"])
    merged_provider_manifest = _merge_json(existing["provider_manifest_json"], provider_manifest)
    merged_coverage = _merge_json(existing["coverage_json"], coverage)
    merged_summary = _merge_json(existing["summary_json"], summary)
    existing_snapshot = _load_regime_snapshot_payload(conn, run_id)
    next_snapshot = _regime_snapshot_payload(run_id, snapshot)
    changed = (
        existing["status"] != "completed"
        or existing["provider_manifest_json"] != _json_dumps(merged_provider_manifest)
        or existing["coverage_json"] != _json_dumps(merged_coverage)
        or existing["summary_json"] != _json_dumps(merged_summary)
        or existing_snapshot != next_snapshot
    )
    if changed:
        _upsert_market_review_run(
            conn,
            result.as_of_date,
            provider_manifest=provider_manifest,
            coverage=coverage,
            summary=summary,
        )
        _upsert_regime_snapshot(conn, run_id, snapshot)
    return run_id, changed


def _upsert_regime_snapshot(conn: sqlite3.Connection, run_id: int, snapshot: _RegimeSnapshot) -> None:
    payload = _regime_snapshot_payload(run_id, snapshot)
    conn.execute(
        """
        INSERT INTO market_regime_snapshots
          (
            market_review_run_id,
            as_of_date,
            regime,
            breadth_score,
            trend_score,
            volume_score,
            persistence_score,
            summary,
            metrics_json
          )
        VALUES
          (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(market_review_run_id) DO UPDATE SET
          as_of_date = excluded.as_of_date,
          regime = excluded.regime,
          breadth_score = excluded.breadth_score,
          trend_score = excluded.trend_score,
          volume_score = excluded.volume_score,
          persistence_score = excluded.persistence_score,
          summary = excluded.summary,
          metrics_json = excluded.metrics_json
        """,
        (
            run_id,
            payload["as_of_date"],
            payload["regime"],
            payload["breadth_score"],
            payload["trend_score"],
            payload["volume_score"],
            payload["persistence_score"],
            payload["summary"],
            payload["metrics_json"],
        ),
    )


def _load_regime_snapshot_payload(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
          market_review_run_id,
          as_of_date,
          regime,
          breadth_score,
          trend_score,
          volume_score,
          persistence_score,
          summary,
          metrics_json
        FROM market_regime_snapshots
        WHERE market_review_run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "market_review_run_id": int(row["market_review_run_id"]),
        "as_of_date": row["as_of_date"],
        "regime": row["regime"],
        "breadth_score": row["breadth_score"],
        "trend_score": row["trend_score"],
        "volume_score": row["volume_score"],
        "persistence_score": row["persistence_score"],
        "summary": row["summary"],
        "metrics_json": row["metrics_json"],
    }


def _regime_snapshot_payload(run_id: int, snapshot: _RegimeSnapshot) -> dict[str, Any]:
    result = snapshot.result
    return {
        "market_review_run_id": run_id,
        "as_of_date": result.as_of_date,
        "regime": result.regime,
        "breadth_score": result.breadth_score,
        "trend_score": result.trend_score,
        "volume_score": result.volume_score,
        "persistence_score": result.persistence_score,
        "summary": result.summary,
        "metrics_json": _json_dumps(snapshot.metrics),
    }


def _regime_coverage_payload(
    request: RunMarketReviewRequest,
    universe_count: int,
    covered_count: int,
    coverage_ratio: float,
) -> dict[str, Any]:
    return {
        "as_of_date": request.as_of_date,
        "universe": request.universe,
        "universe_count": universe_count,
        "covered_count": covered_count,
        "coverage_ratio": coverage_ratio,
        "min_coverage": request.min_coverage,
    }


def _regime_manifest_payload(request: RunMarketReviewRequest) -> dict[str, Any]:
    return {
        "as_of_date": request.as_of_date,
        "source_table": "market_bars",
        "universe": request.universe,
        "version": "market_regime_v1",
    }


def _classify_regime(
    breadth_score: float | None,
    trend_score: float | None,
    volume_score: float | None,
    persistence_score: float | None,
) -> str:
    if breadth_score is None or trend_score is None:
        return "unknown"
    volume_component = volume_score if volume_score is not None else 0.5
    persistence_component = persistence_score if persistence_score is not None else 0.5
    overall = (
        breadth_score * 0.40
        + trend_score * 0.35
        + persistence_component * 0.15
        + volume_component * 0.10
    )
    if overall >= 0.62 and breadth_score >= 0.55 and trend_score >= 0.55:
        return "risk_on"
    if overall <= 0.38 and breadth_score <= 0.45 and trend_score <= 0.45:
        return "risk_off"
    return "neutral"


def _summarize_regime(
    *,
    regime: str,
    breadth_score: float | None,
    trend_score: float | None,
    volume_score: float | None,
    persistence_score: float | None,
    coverage_ratio: float,
) -> str:
    return (
        f"Market regime {regime}: "
        f"breadth={_summary_number(breadth_score)} "
        f"trend={_summary_number(trend_score)} "
        f"volume={_summary_number(volume_score)} "
        f"persistence={_summary_number(persistence_score)} "
        f"coverage={coverage_ratio:.2f}."
    )


def _empty_regime_result(
    request: RunMarketReviewRequest,
    status: str,
    summary: str,
) -> MarketRegimeResult:
    return MarketRegimeResult(
        market_review_run_id=None,
        as_of_date=request.as_of_date,
        status=status,
        regime="unknown",
        breadth_score=None,
        trend_score=None,
        volume_score=None,
        persistence_score=None,
        coverage_ratio=0.0,
        summary=summary,
    )


def _regime_lineage(result: MarketRegimeResult, *, changed: str) -> dict[str, int | str | None]:
    return {
        "market_review_run_id": result.market_review_run_id,
        "as_of_date": result.as_of_date,
        "changed": changed,
    }


def _average_optional(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return round(mean(present), 4)


def _inverse_optional(value: float | None) -> float | None:
    if value is None:
        return None
    return round(1 - value, 4)


def _ratio(values: list[bool]) -> float | None:
    if not values:
        return None
    return _rounded_ratio(sum(1 for value in values if value), len(values))


def _rounded_ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)


def _summary_number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _upsert_market_review_run(
    conn: sqlite3.Connection,
    as_of_date: str,
    *,
    provider_manifest: dict[str, Any],
    coverage: dict[str, Any],
    summary: dict[str, Any],
) -> int:
    existing = conn.execute(
        """
        SELECT id, provider_manifest_json, coverage_json, summary_json
        FROM market_review_runs
        WHERE as_of_date = ?
        """,
        (as_of_date,),
    ).fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO market_review_runs
              (as_of_date, status, provider_manifest_json, coverage_json, summary_json, completed_at)
            VALUES (?, 'completed', ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                as_of_date,
                _json_dumps(provider_manifest),
                _json_dumps(coverage),
                _json_dumps(summary),
            ),
        )
        row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
        return int(row["id"])

    merged_provider_manifest = _merge_json(existing["provider_manifest_json"], provider_manifest)
    merged_coverage = _merge_json(existing["coverage_json"], coverage)
    merged_summary = _merge_json(existing["summary_json"], summary)
    conn.execute(
        """
        UPDATE market_review_runs
        SET status = 'completed',
            provider_manifest_json = ?,
            coverage_json = ?,
            summary_json = ?,
            completed_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            _json_dumps(merged_provider_manifest),
            _json_dumps(merged_coverage),
            _json_dumps(merged_summary),
            int(existing["id"]),
        ),
    )
    return int(existing["id"])


def _merge_json(existing_json: str, incoming: dict[str, Any]) -> dict[str, Any]:
    try:
        existing = json.loads(existing_json or "{}")
    except json.JSONDecodeError:
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    return {**existing, **incoming}


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(payload: str | None) -> dict[str, Any]:
    try:
        loaded = json.loads(payload or "{}")
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}
