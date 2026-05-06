"""Data-quality readiness checks before daily review runs."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any

from pgc_trading.config import Paths
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult, ServiceWarning
from pgc_trading.storage.database import connect


RUNNABLE_STRATEGY_STATUSES = {
    "research",
    "candidate",
    "paper",
    "live_candidate",
    "live",
}


@dataclass(frozen=True)
class DailyReviewReadinessRequest:
    as_of_date: str
    strategy_version: str
    account_key: str | None = None
    account_id: int | None = None
    exchange: str = "SSE"


@dataclass(frozen=True)
class DailyReviewReadinessResult:
    as_of_date: str
    readiness: str
    blocker_count: int
    warning_count: int
    valid_raw_count: int
    market_coverage_ok: bool
    trade_calendar_ok: bool
    strategy_version_ok: bool
    account_ok: bool
    missing_market_bar_count: int = 0
    strategy_version_id: int | None = None
    account_id: int | None = None
    data_quality_event_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class ListDataQualityEventsRequest:
    status: str | None = "open"
    severity: str | None = None
    layer: str | None = None
    trade_date: str | None = None
    limit: int = 100


@dataclass(frozen=True)
class DataQualityEventDTO:
    id: int
    layer: str
    severity: str
    event_code: str
    entity_type: str | None
    entity_id: int | None
    ts_code: str | None
    trade_date: str | None
    message: str
    payload_json: str | None
    status: str
    created_at: str
    resolved_at: str | None


@dataclass(frozen=True)
class ResolveDataQualityEventRequest:
    event_id: int
    status: str = "resolved"


@dataclass(frozen=True)
class ResolveDataQualityEventResult:
    event_id: int
    status: str
    resolved_at: str | None


@dataclass(frozen=True)
class _QualityFinding:
    layer: str
    severity: str
    event_code: str
    message: str
    entity_type: str | None = None
    entity_id: int | None = None
    ts_code: str | None = None
    trade_date: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _ReadinessEvaluation:
    strategy_version_id: int | None
    account_id: int | None
    strategy_version_ok: bool
    account_ok: bool
    trade_calendar_ok: bool
    market_coverage_ok: bool
    valid_raw_count: int
    missing_market_bar_count: int
    findings: list[_QualityFinding]


@dataclass(frozen=True)
class _EventSummary:
    blocker_count: int
    warning_count: int
    event_ids: list[int]


class DataQualityService:
    """Check data readiness without repairing raw, market, strategy, or portfolio data."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def check_daily_review_readiness(
        self,
        request: DailyReviewReadinessRequest,
        ctx: RequestContext,
    ) -> ServiceResult[DailyReviewReadinessResult]:
        validation_errors = _validate_readiness_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_readiness_result(request),
                errors=validation_errors,
            )

        with connect(self.db_path) as conn:
            conn.execute("BEGIN")
            try:
                if not ctx.dry_run:
                    previous = _completed_operation_result(conn, ctx)
                    if previous is not None:
                        conn.commit()
                        return previous

                evaluation = _evaluate_readiness(conn, request)
                operation_id = None
                if not ctx.dry_run:
                    operation_id = _reserve_operation(conn, request, ctx, evaluation.account_id)
                    _write_findings(conn, evaluation.findings)

                summary = _summarize_events(
                    conn,
                    request.as_of_date,
                    evaluation.findings,
                    include_unwritten=ctx.dry_run,
                )
                readiness = _readiness_for_summary(summary)
                result_data = DailyReviewReadinessResult(
                    as_of_date=request.as_of_date,
                    readiness=readiness,
                    blocker_count=summary.blocker_count,
                    warning_count=summary.warning_count,
                    valid_raw_count=evaluation.valid_raw_count,
                    market_coverage_ok=evaluation.market_coverage_ok,
                    trade_calendar_ok=evaluation.trade_calendar_ok,
                    strategy_version_ok=evaluation.strategy_version_ok,
                    account_ok=evaluation.account_ok,
                    missing_market_bar_count=evaluation.missing_market_bar_count,
                    strategy_version_id=evaluation.strategy_version_id,
                    account_id=evaluation.account_id,
                    data_quality_event_ids=summary.event_ids,
                )
                service_result = ServiceResult(
                    status=_service_status_for_readiness(readiness),
                    request_id=ctx.request_id,
                    data=result_data,
                    created_ids={},
                    warnings=_warnings_for_summary(summary),
                    errors=_errors_for_readiness(evaluation.findings, summary),
                    lineage={
                        "as_of_date": request.as_of_date,
                        "strategy_version_id": evaluation.strategy_version_id,
                        "account_id": evaluation.account_id,
                    },
                )
                if not ctx.dry_run:
                    _write_domain_event(conn, operation_id, result_data, ctx)
                    _finish_operation(conn, operation_id, service_result)
                conn.commit()
                return service_result
            except Exception:
                conn.rollback()
                raise

    def list_events(
        self,
        request: ListDataQualityEventsRequest,
    ) -> ServiceResult[list[DataQualityEventDTO]]:
        validation_errors = _validate_list_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=None,
                data=[],
                errors=validation_errors,
            )

        clauses: list[str] = []
        params: list[object] = []
        if request.status is not None:
            clauses.append("status = ?")
            params.append(request.status)
        if request.severity is not None:
            clauses.append("severity = ?")
            params.append(request.severity)
        if request.layer is not None:
            clauses.append("layer = ?")
            params.append(request.layer)
        if request.trade_date is not None:
            clauses.append("trade_date = ?")
            params.append(request.trade_date)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT
              id,
              layer,
              severity,
              event_code,
              entity_type,
              entity_id,
              ts_code,
              trade_date,
              message,
              payload_json,
              status,
              created_at,
              resolved_at
            FROM data_quality_events
            {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        """
        params.append(request.limit)
        with connect(self.db_path) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        return ServiceResult(
            status="success",
            request_id=None,
            data=[_event_dto(row) for row in rows],
        )

    def resolve_event(
        self,
        request: ResolveDataQualityEventRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ResolveDataQualityEventResult]:
        validation_errors = _validate_resolve_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=None,
                errors=validation_errors,
            )

        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id FROM data_quality_events WHERE id = ?",
                (request.event_id,),
            ).fetchone()
            if row is None:
                return ServiceResult(
                    status="validation_failed",
                    request_id=ctx.request_id,
                    data=None,
                    errors=[
                        ServiceError(
                            code="DATA_QUALITY_EVENT_NOT_FOUND",
                            message=f"data_quality_event was not found: {request.event_id}",
                            entity_type="data_quality_event",
                            entity_id=request.event_id,
                        )
                    ],
                )

            resolved_at_expr = "CURRENT_TIMESTAMP" if request.status == "resolved" else "NULL"
            conn.execute(
                f"""
                UPDATE data_quality_events
                SET status = ?,
                    resolved_at = {resolved_at_expr}
                WHERE id = ?
                """,
                (request.status, request.event_id),
            )
            updated = conn.execute(
                """
                SELECT id, status, resolved_at
                FROM data_quality_events
                WHERE id = ?
                """,
                (request.event_id,),
            ).fetchone()

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=ResolveDataQualityEventResult(
                event_id=int(updated["id"]),
                status=updated["status"],
                resolved_at=updated["resolved_at"],
            ),
        )


def _evaluate_readiness(
    conn: sqlite3.Connection,
    request: DailyReviewReadinessRequest,
) -> _ReadinessEvaluation:
    findings: list[_QualityFinding] = []
    strategy_version_id, strategy_version_ok = _check_strategy_version(conn, request, findings)
    account_id, account_ok = _check_account(conn, request, findings)
    trade_calendar_ok = _check_trade_calendar(conn, request, findings)
    candidates = _candidate_raw_events(conn, request.as_of_date)
    missing_market_bars = (
        _missing_market_bars(conn, request.as_of_date, candidates) if trade_calendar_ok else []
    )

    for candidate in missing_market_bars:
        findings.append(
            _QualityFinding(
                layer="market",
                severity="blocker",
                event_code="MARKET_BAR_MISSING",
                entity_type="raw_event",
                entity_id=int(candidate["id"]),
                ts_code=candidate["ts_code"],
                trade_date=request.as_of_date,
                message=(
                    "Candidate raw event is missing market_bars data "
                    f"for review date {request.as_of_date}."
                ),
                payload={
                    "raw_event_id": int(candidate["id"]),
                    "ts_code": candidate["ts_code"],
                    "entry_date": candidate["entry_date"],
                    "review_date": request.as_of_date,
                },
            )
        )

    return _ReadinessEvaluation(
        strategy_version_id=strategy_version_id,
        account_id=account_id,
        strategy_version_ok=strategy_version_ok,
        account_ok=account_ok,
        trade_calendar_ok=trade_calendar_ok,
        market_coverage_ok=trade_calendar_ok and not missing_market_bars,
        valid_raw_count=len(candidates),
        missing_market_bar_count=len(missing_market_bars),
        findings=findings,
    )


def _check_strategy_version(
    conn: sqlite3.Connection,
    request: DailyReviewReadinessRequest,
    findings: list[_QualityFinding],
) -> tuple[int | None, bool]:
    row = conn.execute(
        """
        SELECT id, status
        FROM strategy_versions
        WHERE strategy_version = ?
        """,
        (request.strategy_version,),
    ).fetchone()
    if row is None:
        findings.append(
            _QualityFinding(
                layer="signal",
                severity="blocker",
                event_code="STRATEGY_VERSION_NOT_FOUND",
                entity_type="strategy_version",
                trade_date=request.as_of_date,
                message=f"Strategy version was not found: {request.strategy_version}.",
                payload={
                    "strategy_version": request.strategy_version,
                    "review_date": request.as_of_date,
                },
            )
        )
        return None, False

    strategy_version_id = int(row["id"])
    if row["status"] not in RUNNABLE_STRATEGY_STATUSES:
        findings.append(
            _QualityFinding(
                layer="signal",
                severity="blocker",
                event_code="STRATEGY_VERSION_NOT_RUNNABLE",
                entity_type="strategy_version",
                entity_id=strategy_version_id,
                trade_date=request.as_of_date,
                message=(
                    f"Strategy version {request.strategy_version} is not runnable "
                    f"while status is {row['status']}."
                ),
                payload={
                    "strategy_version": request.strategy_version,
                    "strategy_version_id": strategy_version_id,
                    "status": row["status"],
                    "review_date": request.as_of_date,
                },
            )
        )
        return strategy_version_id, False

    return strategy_version_id, True


def _check_account(
    conn: sqlite3.Connection,
    request: DailyReviewReadinessRequest,
    findings: list[_QualityFinding],
) -> tuple[int | None, bool]:
    if request.account_id is None and request.account_key is None:
        return None, True

    if request.account_id is not None and request.account_key is not None:
        row = conn.execute(
            """
            SELECT id, account_key, status
            FROM portfolio_accounts
            WHERE id = ? AND account_key = ?
            """,
            (request.account_id, request.account_key),
        ).fetchone()
    elif request.account_id is not None:
        row = conn.execute(
            """
            SELECT id, account_key, status
            FROM portfolio_accounts
            WHERE id = ?
            """,
            (request.account_id,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT id, account_key, status
            FROM portfolio_accounts
            WHERE account_key = ?
            """,
            (request.account_key,),
        ).fetchone()

    if row is None:
        findings.append(
            _QualityFinding(
                layer="portfolio",
                severity="blocker",
                event_code="ACCOUNT_NOT_FOUND",
                entity_type="portfolio_account",
                entity_id=request.account_id,
                trade_date=request.as_of_date,
                message="Portfolio account was not found for readiness check.",
                payload={
                    "account_id": request.account_id,
                    "account_key": request.account_key,
                    "review_date": request.as_of_date,
                },
            )
        )
        return None, False

    account_id = int(row["id"])
    if row["status"] != "active":
        findings.append(
            _QualityFinding(
                layer="portfolio",
                severity="blocker",
                event_code="ACCOUNT_NOT_ACTIVE",
                entity_type="portfolio_account",
                entity_id=account_id,
                trade_date=request.as_of_date,
                message=f"Portfolio account {row['account_key']} is not active.",
                payload={
                    "account_id": account_id,
                    "account_key": row["account_key"],
                    "status": row["status"],
                    "review_date": request.as_of_date,
                },
            )
        )
        return account_id, False

    return account_id, True


def _check_trade_calendar(
    conn: sqlite3.Connection,
    request: DailyReviewReadinessRequest,
    findings: list[_QualityFinding],
) -> bool:
    row = conn.execute(
        """
        SELECT is_open
        FROM trade_calendar
        WHERE exchange = ? AND cal_date = ?
        """,
        (request.exchange, request.as_of_date),
    ).fetchone()
    if row is None:
        findings.append(
            _QualityFinding(
                layer="market",
                severity="blocker",
                event_code="TRADE_CALENDAR_MISSING",
                entity_type="trade_calendar",
                trade_date=request.as_of_date,
                message=f"Trade calendar is missing for {request.exchange} {request.as_of_date}.",
                payload={
                    "exchange": request.exchange,
                    "review_date": request.as_of_date,
                },
            )
        )
        return False

    if int(row["is_open"]) != 1:
        findings.append(
            _QualityFinding(
                layer="market",
                severity="blocker",
                event_code="TRADE_CALENDAR_CLOSED",
                entity_type="trade_calendar",
                trade_date=request.as_of_date,
                message=f"Review date {request.as_of_date} is not an open trading day.",
                payload={
                    "exchange": request.exchange,
                    "review_date": request.as_of_date,
                    "is_open": int(row["is_open"]),
                },
            )
        )
        return False

    return True


def _candidate_raw_events(conn: sqlite3.Connection, as_of_date: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, ts_code, name, entry_date
            FROM raw_events
            WHERE is_valid = 1
              AND entry_date <= ?
            ORDER BY id
            """,
            (as_of_date,),
        ).fetchall()
    )


def _missing_market_bars(
    conn: sqlite3.Connection,
    as_of_date: str,
    candidates: list[sqlite3.Row],
) -> list[sqlite3.Row]:
    missing: list[sqlite3.Row] = []
    for candidate in candidates:
        row = conn.execute(
            """
            SELECT 1
            FROM market_bars
            WHERE ts_code = ?
              AND trade_date = ?
            """,
            (candidate["ts_code"], as_of_date),
        ).fetchone()
        if row is None:
            missing.append(candidate)
    return missing


def _write_findings(
    conn: sqlite3.Connection,
    findings: list[_QualityFinding],
) -> list[int]:
    return [_upsert_open_quality_event(conn, finding) for finding in findings]


def _upsert_open_quality_event(
    conn: sqlite3.Connection,
    finding: _QualityFinding,
) -> int:
    existing_id = _matching_open_event_id(conn, finding)
    payload_json = _json_dumps(finding.payload) if finding.payload else None
    if existing_id is not None:
        conn.execute(
            """
            UPDATE data_quality_events
            SET message = ?,
                payload_json = ?
            WHERE id = ?
            """,
            (finding.message, payload_json, existing_id),
        )
        return existing_id

    cursor = conn.execute(
        """
        INSERT INTO data_quality_events
          (
            layer,
            severity,
            event_code,
            entity_type,
            entity_id,
            ts_code,
            trade_date,
            message,
            payload_json
          )
        VALUES
          (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            finding.layer,
            finding.severity,
            finding.event_code,
            finding.entity_type,
            finding.entity_id,
            finding.ts_code,
            finding.trade_date,
            finding.message,
            payload_json,
        ),
    )
    return int(cursor.lastrowid)


def _matching_open_event_id(
    conn: sqlite3.Connection,
    finding: _QualityFinding,
) -> int | None:
    row = conn.execute(
        """
        SELECT id
        FROM data_quality_events
        WHERE status = 'open'
          AND layer = ?
          AND severity = ?
          AND event_code = ?
          AND ((entity_type IS NULL AND ? IS NULL) OR entity_type = ?)
          AND ((entity_id IS NULL AND ? IS NULL) OR entity_id = ?)
          AND ((ts_code IS NULL AND ? IS NULL) OR ts_code = ?)
          AND ((trade_date IS NULL AND ? IS NULL) OR trade_date = ?)
        ORDER BY id
        LIMIT 1
        """,
        (
            finding.layer,
            finding.severity,
            finding.event_code,
            finding.entity_type,
            finding.entity_type,
            finding.entity_id,
            finding.entity_id,
            finding.ts_code,
            finding.ts_code,
            finding.trade_date,
            finding.trade_date,
        ),
    ).fetchone()
    if row is None:
        return None
    return int(row["id"])


def _summarize_events(
    conn: sqlite3.Connection,
    as_of_date: str,
    findings: list[_QualityFinding],
    include_unwritten: bool,
) -> _EventSummary:
    rows = conn.execute(
        """
        SELECT id, severity
        FROM data_quality_events
        WHERE status = 'open'
          AND (trade_date = ? OR trade_date IS NULL)
        ORDER BY id
        """,
        (as_of_date,),
    ).fetchall()
    blocker_count = sum(1 for row in rows if row["severity"] in {"blocker", "error"})
    warning_count = sum(1 for row in rows if row["severity"] == "warning")
    event_ids = [int(row["id"]) for row in rows]

    if include_unwritten:
        for finding in findings:
            if _matching_open_event_id(conn, finding) is not None:
                continue
            if finding.severity in {"blocker", "error"}:
                blocker_count += 1
            elif finding.severity == "warning":
                warning_count += 1

    return _EventSummary(
        blocker_count=blocker_count,
        warning_count=warning_count,
        event_ids=event_ids,
    )


def _readiness_for_summary(summary: _EventSummary) -> str:
    if summary.blocker_count:
        return "blocker"
    if summary.warning_count:
        return "warning"
    return "pass"


def _service_status_for_readiness(readiness: str) -> str:
    if readiness == "blocker":
        return "blocked"
    if readiness == "warning":
        return "partial_success"
    return "success"


def _errors_for_readiness(
    findings: list[_QualityFinding],
    summary: _EventSummary,
) -> list[ServiceError]:
    if summary.blocker_count == 0:
        return []

    errors: list[ServiceError] = []
    missing_market_count = sum(1 for finding in findings if finding.event_code == "MARKET_BAR_MISSING")
    for finding in findings:
        if finding.severity not in {"blocker", "error"}:
            continue
        if finding.event_code == "MARKET_BAR_MISSING":
            continue
        errors.append(
            ServiceError(
                code=finding.event_code,
                message=finding.message,
                entity_type=finding.entity_type,
                entity_id=finding.entity_id,
                severity="blocker",
            )
        )

    if missing_market_count:
        errors.append(
            ServiceError(
                code="MARKET_DATA_NOT_READY",
                message=f"{missing_market_count} candidate raw event(s) are missing market bars.",
                severity="blocker",
            )
        )

    if errors:
        return errors
    return [
        ServiceError(
            code="DATA_QUALITY_BLOCKED",
            message="Open data-quality blocker event(s) are present.",
            severity="blocker",
        )
    ]


def _warnings_for_summary(summary: _EventSummary) -> list[ServiceWarning]:
    if summary.warning_count == 0:
        return []
    return [
        ServiceWarning(
            code="DATA_QUALITY_WARNINGS_PRESENT",
            message=f"{summary.warning_count} open data-quality warning(s) are present.",
            severity="warning",
        )
    ]


def _reserve_operation(
    conn: sqlite3.Connection,
    request: DailyReviewReadinessRequest,
    ctx: RequestContext,
    account_id: int | None,
) -> int | None:
    if not ctx.idempotency_key:
        return None

    request_json = _json_dumps(
        {
            "as_of_date": request.as_of_date,
            "strategy_version": request.strategy_version,
            "account_key": request.account_key,
            "account_id": request.account_id,
            "exchange": request.exchange,
            "dry_run": ctx.dry_run,
        }
    )
    existing = conn.execute(
        "SELECT id FROM operation_requests WHERE idempotency_key = ?",
        (ctx.idempotency_key,),
    ).fetchone()
    if existing is not None:
        conn.execute(
            """
            UPDATE operation_requests
            SET status = 'started',
                request_id = ?,
                operation_type = 'data_quality_check',
                account_id = ?,
                as_of_date = ?,
                request_json = ?,
                response_json = NULL,
                error_code = NULL,
                error_message = NULL,
                operator = ?,
                started_at = CURRENT_TIMESTAMP,
                finished_at = NULL
            WHERE id = ?
            """,
            (
                ctx.request_id,
                account_id,
                request.as_of_date,
                request_json,
                ctx.operator,
                existing["id"],
            ),
        )
        return int(existing["id"])

    cursor = conn.execute(
        """
        INSERT INTO operation_requests
          (
            idempotency_key,
            request_id,
            operation_type,
            account_id,
            as_of_date,
            status,
            request_json,
            operator
          )
        VALUES
          (?, ?, 'data_quality_check', ?, ?, 'started', ?, ?)
        """,
        (
            ctx.idempotency_key,
            ctx.request_id,
            account_id,
            request.as_of_date,
            request_json,
            ctx.operator,
        ),
    )
    return int(cursor.lastrowid)


def _completed_operation_result(
    conn: sqlite3.Connection,
    ctx: RequestContext,
) -> ServiceResult[DailyReviewReadinessResult] | None:
    if not ctx.idempotency_key:
        return None
    row = conn.execute(
        """
        SELECT response_json
        FROM operation_requests
        WHERE idempotency_key = ?
          AND status IN ('success', 'partial_success', 'skipped')
          AND response_json IS NOT NULL
        """,
        (ctx.idempotency_key,),
    ).fetchone()
    if row is None:
        return None
    return _service_result_from_json(row["response_json"], ctx.request_id)


def _finish_operation(
    conn: sqlite3.Connection,
    operation_id: int | None,
    result: ServiceResult[DailyReviewReadinessResult],
) -> None:
    if operation_id is None:
        return
    first_error = result.errors[0] if result.errors else None
    conn.execute(
        """
        UPDATE operation_requests
        SET status = ?,
            response_json = ?,
            error_code = ?,
            error_message = ?,
            finished_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            "failed" if result.status == "blocked" else result.status,
            _json_dumps(result),
            first_error.code if first_error else None,
            first_error.message if first_error else None,
            operation_id,
        ),
    )


def _write_domain_event(
    conn: sqlite3.Connection,
    operation_id: int | None,
    result: DailyReviewReadinessResult,
    ctx: RequestContext,
) -> None:
    if operation_id is None:
        return
    conn.execute(
        """
        INSERT INTO domain_events
          (event_type, entity_type, entity_id, account_id, payload_json, source, operator)
        VALUES
          ('data_quality_readiness_checked', 'operation_request', ?, ?, ?, ?, ?)
        """,
        (
            operation_id,
            result.account_id,
            _json_dumps(result),
            _domain_event_source(ctx.source),
            ctx.operator,
        ),
    )


def _validate_readiness_request(request: DailyReviewReadinessRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not _is_yyyymmdd(request.as_of_date):
        errors.append(
            ServiceError(
                code="VALIDATION_ERROR",
                message="as_of_date must use YYYYMMDD format.",
            )
        )
    if not request.strategy_version.strip():
        errors.append(
            ServiceError(
                code="VALIDATION_ERROR",
                message="strategy_version is required.",
            )
        )
    if request.account_id is not None and request.account_id <= 0:
        errors.append(
            ServiceError(
                code="VALIDATION_ERROR",
                message="account_id must be positive when provided.",
            )
        )
    if request.account_key is not None and not request.account_key.strip():
        errors.append(
            ServiceError(
                code="VALIDATION_ERROR",
                message="account_key cannot be blank when provided.",
            )
        )
    if not request.exchange.strip():
        errors.append(
            ServiceError(
                code="VALIDATION_ERROR",
                message="exchange is required.",
            )
        )
    return errors


def _validate_list_request(request: ListDataQualityEventsRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if request.limit <= 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="limit must be positive."))
    if request.status is not None and request.status not in {
        "open",
        "acknowledged",
        "resolved",
        "ignored",
    }:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="status is invalid."))
    if request.severity is not None and request.severity not in {
        "info",
        "warning",
        "error",
        "blocker",
    }:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="severity is invalid."))
    if request.layer is not None and request.layer not in {
        "raw",
        "market",
        "feature",
        "signal",
        "agent",
        "portfolio",
        "report",
    }:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="layer is invalid."))
    if request.trade_date is not None and not _is_yyyymmdd(request.trade_date):
        errors.append(
            ServiceError(
                code="VALIDATION_ERROR",
                message="trade_date must use YYYYMMDD format.",
            )
        )
    return errors


def _validate_resolve_request(request: ResolveDataQualityEventRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if request.event_id <= 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="event_id must be positive."))
    if request.status not in {"acknowledged", "resolved", "ignored"}:
        errors.append(
            ServiceError(
                code="VALIDATION_ERROR",
                message="status must be acknowledged, resolved, or ignored.",
            )
        )
    return errors


def _empty_readiness_result(
    request: DailyReviewReadinessRequest,
) -> DailyReviewReadinessResult:
    return DailyReviewReadinessResult(
        as_of_date=request.as_of_date,
        readiness="blocker",
        blocker_count=0,
        warning_count=0,
        valid_raw_count=0,
        market_coverage_ok=False,
        trade_calendar_ok=False,
        strategy_version_ok=False,
        account_ok=False,
    )


def _is_yyyymmdd(value: str) -> bool:
    return len(value) == 8 and value.isdigit()


def _event_dto(row: sqlite3.Row) -> DataQualityEventDTO:
    return DataQualityEventDTO(
        id=int(row["id"]),
        layer=row["layer"],
        severity=row["severity"],
        event_code=row["event_code"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        ts_code=row["ts_code"],
        trade_date=row["trade_date"],
        message=row["message"],
        payload_json=row["payload_json"],
        status=row["status"],
        created_at=row["created_at"],
        resolved_at=row["resolved_at"],
    )


def _service_result_from_json(
    response_json: str,
    request_id: str | None,
) -> ServiceResult[DailyReviewReadinessResult]:
    payload = json.loads(response_json)
    data = payload.get("data")
    result = None
    if data is not None:
        result = DailyReviewReadinessResult(
            as_of_date=data["as_of_date"],
            readiness=data["readiness"],
            blocker_count=int(data.get("blocker_count", 0)),
            warning_count=int(data.get("warning_count", 0)),
            valid_raw_count=int(data.get("valid_raw_count", 0)),
            market_coverage_ok=bool(data.get("market_coverage_ok", False)),
            trade_calendar_ok=bool(data.get("trade_calendar_ok", False)),
            strategy_version_ok=bool(data.get("strategy_version_ok", False)),
            account_ok=bool(data.get("account_ok", False)),
            missing_market_bar_count=int(data.get("missing_market_bar_count", 0)),
            strategy_version_id=data.get("strategy_version_id"),
            account_id=data.get("account_id"),
            data_quality_event_ids=list(data.get("data_quality_event_ids", [])),
        )
    return ServiceResult(
        status=payload["status"],
        request_id=request_id,
        data=result,
        created_ids=payload.get("created_ids", {}),
        warnings=[
            ServiceWarning(
                code=item["code"],
                message=item["message"],
                entity_type=item.get("entity_type"),
                entity_id=item.get("entity_id"),
                severity=item.get("severity", "warning"),
            )
            for item in payload.get("warnings", [])
        ],
        errors=[
            ServiceError(
                code=item["code"],
                message=item["message"],
                entity_type=item.get("entity_type"),
                entity_id=item.get("entity_id"),
                severity=item.get("severity", "error"),
            )
            for item in payload.get("errors", [])
        ],
        lineage=payload.get("lineage", {}),
    )


def _domain_event_source(source: str) -> str:
    if source in {"manual", "scheduler", "migration"}:
        return source
    return "system"


def _json_dumps(value: Any) -> str:
    return json.dumps(_to_jsonable(value), ensure_ascii=False, sort_keys=True)


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value
