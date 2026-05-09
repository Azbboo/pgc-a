"""Market review coordination service."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
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
                data = _market_review_detail_payload(run, regime)

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


def _market_review_detail_payload(run: sqlite3.Row, regime: sqlite3.Row | None) -> dict[str, Any]:
    provider_manifest = _json_loads(run["provider_manifest_json"])
    coverage = _json_loads(run["coverage_json"])
    summary = _json_loads(run["summary_json"])
    missing_data: list[str] = []
    if not provider_manifest:
        missing_data.append("provider_manifest_json")
    if not coverage:
        missing_data.append("coverage_json")
    if regime is None:
        missing_data.append("market_regime_snapshots")
    return {
        "market_review_run_id": int(run["id"]),
        "as_of_date": run["as_of_date"],
        "exists": True,
        "status": run["status"],
        "created_at": run["created_at"],
        "completed_at": run["completed_at"],
        "provider_manifest": provider_manifest,
        "summary": summary,
        "regime": _regime_payload(regime) if regime is not None else None,
        "source": _source_payload(["market_review_runs", "market_regime_snapshots"], provider_manifest),
        "coverage": {"has_review": True, **coverage},
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
        "coverage": {"has_review": has_review, "item_count": 0, "by_scope": {}, "by_sentiment": {}},
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
    return [
        {
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
        for row in rows
    ]


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
        "coverage": {"has_review": has_review, "context_count": 0, "trade_plan_id": trade_plan_id},
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
