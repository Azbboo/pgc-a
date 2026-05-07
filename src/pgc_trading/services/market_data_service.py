"""Application service for refreshing market data through an injectable adapter."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Sequence

from pgc_trading.config import Paths
from pgc_trading.market.calendar import compare_yyyymmdd, is_yyyymmdd, iter_calendar_dates
from pgc_trading.market.tushare_adapter import (
    DailyBasicSnapshot,
    MarketBar,
    MarketDataAdapter,
    MarketDataPayload,
    TradeCalendarDay,
    TushareAdapter,
)
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult, ServiceWarning
from pgc_trading.storage.database import connect


VALID_MARKET_SCOPES = {"valid_raw_events", "raw-events", "raw_events", "ts_codes"}


@dataclass(frozen=True)
class RefreshMarketDataRequest:
    start_date: str | None
    end_date: str
    scope: str = "valid_raw_events"
    ts_codes: list[str] | None = None
    provider: str = "tushare"
    include_daily_basic: bool = True


@dataclass(frozen=True)
class RefreshMarketDataResult:
    market_fetch_run_id: int | None
    ts_code_count: int
    bars_upserted: int
    daily_basic_upserted: int
    missing_ts_codes: list[str]
    coverage_start_date: str | None
    coverage_end_date: str | None


@dataclass(frozen=True)
class RefreshTradeCalendarRequest:
    start_date: str
    end_date: str
    exchange: str = "SSE"
    provider: str = "tushare"


@dataclass(frozen=True)
class RefreshTradeCalendarResult:
    exchange: str
    start_date: str
    end_date: str
    calendar_days_upserted: int
    open_days: int
    missing_dates: list[str]


@dataclass(frozen=True)
class _ResolvedMarketScope:
    ts_codes: list[str]
    start_date: str
    end_date: str


class MarketDataService:
    """Refresh market data without touching raw, feature, signal, or portfolio rows."""

    def __init__(self, db_path: Path | None = None, adapter: MarketDataAdapter | None = None):
        self.db_path = db_path or Paths().db_path
        self.adapter = adapter

    def refresh_market_data(
        self,
        request: RefreshMarketDataRequest,
        ctx: RequestContext,
    ) -> ServiceResult[RefreshMarketDataResult]:
        validation_errors = _validate_market_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_market_result(request),
                errors=validation_errors,
            )

        resolved = _resolve_market_scope(self.db_path, request)
        if ctx.dry_run:
            return ServiceResult(
                status="success",
                request_id=ctx.request_id,
                data=RefreshMarketDataResult(
                    market_fetch_run_id=None,
                    ts_code_count=len(resolved.ts_codes),
                    bars_upserted=0,
                    daily_basic_upserted=0,
                    missing_ts_codes=[],
                    coverage_start_date=resolved.start_date,
                    coverage_end_date=resolved.end_date,
                ),
                lineage={
                    "provider": request.provider,
                    "start_date": resolved.start_date,
                    "end_date": resolved.end_date,
                },
            )

        operation_id = None
        fetch_run_id = None
        with connect(self.db_path) as conn:
            conn.execute("BEGIN")
            try:
                previous = _completed_market_operation_result(conn, ctx)
                if previous is not None:
                    conn.commit()
                    return previous
                operation_id = _reserve_market_operation(conn, request, resolved, ctx)
                fetch_run_id = _insert_market_fetch_run(
                    conn,
                    request,
                    resolved,
                    status="started",
                    manifest={
                        "ts_codes": resolved.ts_codes,
                        "include_daily_basic": request.include_daily_basic,
                        "bars": 0,
                        "daily_basic": 0,
                    },
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        try:
            adapter = self.adapter or TushareAdapter()
            payload = adapter.fetch_market_data(
                resolved.ts_codes,
                resolved.start_date,
                resolved.end_date,
                include_daily_basic=request.include_daily_basic,
            )
        except Exception as exc:
            return _failed_market_fetch_result(
                self.db_path,
                request,
                resolved,
                ctx,
                operation_id,
                fetch_run_id,
                exc,
            )

        if fetch_run_id is None:
            raise RuntimeError("market fetch run was not reserved.")

        bars = tuple(payload.bars)
        daily_basic = tuple(payload.daily_basic)
        missing_ts_codes = _missing_ts_codes(resolved.ts_codes, payload, bars)
        coverage_start_date, coverage_end_date = _coverage_dates(bars)
        service_status = "partial_success" if missing_ts_codes else "success"
        fetch_status = "partial_success" if missing_ts_codes else "completed"
        fetch_manifest = {
            "ts_codes": resolved.ts_codes,
            "include_daily_basic": request.include_daily_basic,
            "bars": len(bars),
            "daily_basic": len(daily_basic),
            "missing_ts_codes": missing_ts_codes,
        }

        with connect(self.db_path) as conn:
            conn.execute("BEGIN")
            try:
                bars_upserted = _upsert_market_bars(conn, fetch_run_id, request.provider, bars)
                daily_basic_upserted = (
                    _upsert_daily_basic(conn, fetch_run_id, request.provider, daily_basic)
                    if request.include_daily_basic
                    else 0
                )
                data_quality_event_ids = _write_missing_market_events(
                    conn,
                    missing_ts_codes,
                    request,
                    resolved,
                    fetch_run_id,
                )

                result_data = RefreshMarketDataResult(
                    market_fetch_run_id=fetch_run_id,
                    ts_code_count=len(resolved.ts_codes),
                    bars_upserted=bars_upserted,
                    daily_basic_upserted=daily_basic_upserted,
                    missing_ts_codes=missing_ts_codes,
                    coverage_start_date=coverage_start_date,
                    coverage_end_date=coverage_end_date,
                )
                service_result = ServiceResult(
                    status=service_status,
                    request_id=ctx.request_id,
                    data=result_data,
                    created_ids={
                        "market_fetch_run_id": fetch_run_id,
                        "data_quality_event_ids": data_quality_event_ids,
                    },
                    warnings=_warnings_for_missing_ts_codes(missing_ts_codes),
                    lineage={
                        "market_fetch_run_id": fetch_run_id,
                        "provider": request.provider,
                        "start_date": resolved.start_date,
                        "end_date": resolved.end_date,
                    },
                )
                _finish_market_fetch_run(
                    conn,
                    fetch_run_id,
                    fetch_status,
                    service_result,
                    manifest=fetch_manifest,
                )
                _write_market_domain_event(conn, fetch_run_id, result_data, ctx)
                _finish_operation(conn, operation_id, _operation_status(service_result.status), service_result)
                conn.commit()
                return service_result
            except Exception:
                conn.rollback()
                raise

    def refresh_trade_calendar(
        self,
        request: RefreshTradeCalendarRequest,
        ctx: RequestContext,
    ) -> ServiceResult[RefreshTradeCalendarResult]:
        validation_errors = _validate_calendar_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_calendar_result(request),
                errors=validation_errors,
            )

        operation_id = None
        if not ctx.dry_run:
            with connect(self.db_path) as conn:
                conn.execute("BEGIN")
                try:
                    operation_id = _reserve_calendar_operation(conn, request, ctx)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

        try:
            adapter = self.adapter or TushareAdapter()
            calendar_days = tuple(
                adapter.fetch_trade_calendar(request.start_date, request.end_date, request.exchange)
            )
        except Exception as exc:
            result = ServiceResult(
                status="failed",
                request_id=ctx.request_id,
                data=_empty_calendar_result(request),
                errors=[ServiceError(code="MARKET_PROVIDER_ERROR", message=str(exc))],
            )
            if not ctx.dry_run:
                with connect(self.db_path) as conn:
                    conn.execute("BEGIN")
                    try:
                        _finish_operation(conn, operation_id, "failed", result)
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        raise
            return result

        missing_dates = _missing_calendar_dates(request, calendar_days)
        service_status = "partial_success" if missing_dates else "success"
        result_data = RefreshTradeCalendarResult(
            exchange=request.exchange,
            start_date=request.start_date,
            end_date=request.end_date,
            calendar_days_upserted=0 if ctx.dry_run else len(calendar_days),
            open_days=sum(1 for day in calendar_days if day.is_open),
            missing_dates=missing_dates,
        )
        service_result = ServiceResult(
            status=service_status,
            request_id=ctx.request_id,
            data=result_data,
            warnings=_warnings_for_missing_calendar_dates(missing_dates),
            lineage={
                "provider": request.provider,
                "exchange": request.exchange,
                "start_date": request.start_date,
                "end_date": request.end_date,
            },
        )
        if ctx.dry_run:
            return service_result

        with connect(self.db_path) as conn:
            conn.execute("BEGIN")
            try:
                _upsert_trade_calendar(conn, request.provider, calendar_days)
                data_quality_event_ids = _write_missing_calendar_events(
                    conn,
                    request,
                    missing_dates,
                )
                if data_quality_event_ids:
                    service_result.created_ids["data_quality_event_ids"] = data_quality_event_ids
                _write_calendar_domain_event(conn, operation_id, result_data, ctx)
                _finish_operation(conn, operation_id, _operation_status(service_result.status), service_result)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return service_result


def _validate_market_request(request: RefreshMarketDataRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if request.start_date is not None and not is_yyyymmdd(request.start_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="start_date must use YYYYMMDD format."))
    if not is_yyyymmdd(request.end_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="end_date must use YYYYMMDD format."))
    if (
        request.start_date is not None
        and is_yyyymmdd(request.start_date)
        and is_yyyymmdd(request.end_date)
        and compare_yyyymmdd(request.start_date, request.end_date) > 0
    ):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="start_date must be before end_date."))
    if request.scope not in VALID_MARKET_SCOPES:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="scope is invalid."))
    if not request.provider.strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="provider is required."))
    if request.ts_codes is not None and any(not code.strip() for code in request.ts_codes):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="ts_codes cannot contain blanks."))
    return errors


def _validate_calendar_request(request: RefreshTradeCalendarRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not is_yyyymmdd(request.start_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="start_date must use YYYYMMDD format."))
    if not is_yyyymmdd(request.end_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="end_date must use YYYYMMDD format."))
    if (
        is_yyyymmdd(request.start_date)
        and is_yyyymmdd(request.end_date)
        and compare_yyyymmdd(request.start_date, request.end_date) > 0
    ):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="start_date must be before end_date."))
    if not request.exchange.strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="exchange is required."))
    if not request.provider.strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="provider is required."))
    return errors


def _resolve_market_scope(db_path: Path, request: RefreshMarketDataRequest) -> _ResolvedMarketScope:
    if request.ts_codes is not None:
        ts_codes = sorted({code.strip() for code in request.ts_codes if code.strip()})
        return _ResolvedMarketScope(
            ts_codes=ts_codes,
            start_date=request.start_date or request.end_date,
            end_date=request.end_date,
        )

    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT ts_code, entry_date
            FROM raw_events
            WHERE is_valid = 1
              AND entry_date <= ?
            ORDER BY ts_code
            """,
            (request.end_date,),
        ).fetchall()

    ts_codes = sorted({row["ts_code"] for row in rows})
    if request.start_date is not None:
        start_date = request.start_date
    elif rows:
        start_date = min(row["entry_date"] for row in rows)
    else:
        start_date = request.end_date
    return _ResolvedMarketScope(ts_codes=ts_codes, start_date=start_date, end_date=request.end_date)


def _insert_market_fetch_run(
    conn: sqlite3.Connection,
    request: RefreshMarketDataRequest,
    resolved: _ResolvedMarketScope,
    status: str,
    manifest: dict[str, Any],
    error_message: str | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO market_fetch_runs
          (provider, start_date, end_date, ts_code_count, status, manifest_json, error_message)
        VALUES
          (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request.provider,
            resolved.start_date,
            resolved.end_date,
            len(resolved.ts_codes),
            status,
            _json_dumps(manifest),
            error_message,
        ),
    )
    return int(cursor.lastrowid)


def _finish_market_fetch_run(
    conn: sqlite3.Connection,
    fetch_run_id: int,
    status: str,
    result: ServiceResult[RefreshMarketDataResult],
    manifest: dict[str, Any] | None = None,
) -> None:
    first_error = result.errors[0] if result.errors else None
    if manifest is None:
        conn.execute(
            """
            UPDATE market_fetch_runs
            SET status = ?,
                error_message = ?
            WHERE id = ?
            """,
            (
                status,
                first_error.message if first_error else None,
                fetch_run_id,
            ),
        )
        return
    conn.execute(
        """
        UPDATE market_fetch_runs
        SET status = ?,
            manifest_json = ?,
            error_message = ?
        WHERE id = ?
        """,
        (
            status,
            _json_dumps(manifest),
            first_error.message if first_error else None,
            fetch_run_id,
        ),
    )


def _upsert_market_bars(
    conn: sqlite3.Connection,
    fetch_run_id: int,
    provider: str,
    bars: Sequence[MarketBar],
) -> int:
    for bar in bars:
        conn.execute(
            """
            INSERT INTO market_bars
              (
                ts_code,
                trade_date,
                open,
                high,
                low,
                close,
                vol,
                amount,
                adj_factor,
                adj_open,
                adj_high,
                adj_low,
                adj_close,
                provider,
                fetch_run_id,
                updated_at
              )
            VALUES
              (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(ts_code, trade_date) DO UPDATE SET
              open = excluded.open,
              high = excluded.high,
              low = excluded.low,
              close = excluded.close,
              vol = excluded.vol,
              amount = excluded.amount,
              adj_factor = excluded.adj_factor,
              adj_open = excluded.adj_open,
              adj_high = excluded.adj_high,
              adj_low = excluded.adj_low,
              adj_close = excluded.adj_close,
              provider = excluded.provider,
              fetch_run_id = excluded.fetch_run_id,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                bar.ts_code,
                bar.trade_date,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.vol,
                bar.amount,
                bar.adj_factor,
                bar.adj_open,
                bar.adj_high,
                bar.adj_low,
                bar.adj_close,
                provider,
                fetch_run_id,
            ),
        )
    return len(bars)


def _upsert_daily_basic(
    conn: sqlite3.Connection,
    fetch_run_id: int,
    provider: str,
    snapshots: Sequence[DailyBasicSnapshot],
) -> int:
    for snapshot in snapshots:
        conn.execute(
            """
            INSERT INTO daily_basic_snapshots
              (
                ts_code,
                trade_date,
                turnover_rate,
                turnover_rate_f,
                volume_ratio,
                pe,
                pe_ttm,
                pb,
                ps,
                ps_ttm,
                dv_ratio,
                total_share,
                float_share,
                free_share,
                total_mv,
                circ_mv,
                provider,
                fetch_run_id,
                updated_at
              )
            VALUES
              (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(ts_code, trade_date) DO UPDATE SET
              turnover_rate = excluded.turnover_rate,
              turnover_rate_f = excluded.turnover_rate_f,
              volume_ratio = excluded.volume_ratio,
              pe = excluded.pe,
              pe_ttm = excluded.pe_ttm,
              pb = excluded.pb,
              ps = excluded.ps,
              ps_ttm = excluded.ps_ttm,
              dv_ratio = excluded.dv_ratio,
              total_share = excluded.total_share,
              float_share = excluded.float_share,
              free_share = excluded.free_share,
              total_mv = excluded.total_mv,
              circ_mv = excluded.circ_mv,
              provider = excluded.provider,
              fetch_run_id = excluded.fetch_run_id,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                snapshot.ts_code,
                snapshot.trade_date,
                snapshot.turnover_rate,
                snapshot.turnover_rate_f,
                snapshot.volume_ratio,
                snapshot.pe,
                snapshot.pe_ttm,
                snapshot.pb,
                snapshot.ps,
                snapshot.ps_ttm,
                snapshot.dv_ratio,
                snapshot.total_share,
                snapshot.float_share,
                snapshot.free_share,
                snapshot.total_mv,
                snapshot.circ_mv,
                provider,
                fetch_run_id,
            ),
        )
    return len(snapshots)


def _upsert_trade_calendar(
    conn: sqlite3.Connection,
    provider: str,
    days: Sequence[TradeCalendarDay],
) -> None:
    for day in days:
        conn.execute(
            """
            INSERT INTO trade_calendar
              (exchange, cal_date, is_open, pretrade_date, provider, updated_at)
            VALUES
              (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(exchange, cal_date) DO UPDATE SET
              is_open = excluded.is_open,
              pretrade_date = excluded.pretrade_date,
              provider = excluded.provider,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                day.exchange,
                day.cal_date,
                1 if day.is_open else 0,
                day.pretrade_date,
                provider,
            ),
        )


def _write_missing_market_events(
    conn: sqlite3.Connection,
    missing_ts_codes: Sequence[str],
    request: RefreshMarketDataRequest,
    resolved: _ResolvedMarketScope,
    fetch_run_id: int,
) -> list[int]:
    event_ids: list[int] = []
    for ts_code in missing_ts_codes:
        payload = {
            "provider": request.provider,
            "start_date": resolved.start_date,
            "end_date": resolved.end_date,
            "market_fetch_run_id": fetch_run_id,
        }
        event_ids.append(
            _upsert_open_quality_event(
                conn,
                layer="market",
                severity="blocker",
                event_code="MARKET_DATA_MISSING",
                entity_type="market_bar",
                entity_id=None,
                ts_code=ts_code,
                trade_date=resolved.end_date,
                message=f"Market data is missing for {ts_code} through {resolved.end_date}.",
                payload=payload,
            )
        )
    return event_ids


def _write_missing_calendar_events(
    conn: sqlite3.Connection,
    request: RefreshTradeCalendarRequest,
    missing_dates: Sequence[str],
) -> list[int]:
    event_ids: list[int] = []
    for cal_date in missing_dates:
        event_ids.append(
            _upsert_open_quality_event(
                conn,
                layer="market",
                severity="blocker",
                event_code="TRADE_CALENDAR_MISSING",
                entity_type="trade_calendar",
                entity_id=None,
                ts_code=None,
                trade_date=cal_date,
                message=f"Trade calendar is missing for {request.exchange} {cal_date}.",
                payload={"exchange": request.exchange, "provider": request.provider},
            )
        )
    return event_ids


def _upsert_open_quality_event(
    conn: sqlite3.Connection,
    *,
    layer: str,
    severity: str,
    event_code: str,
    entity_type: str | None,
    entity_id: int | None,
    ts_code: str | None,
    trade_date: str | None,
    message: str,
    payload: dict[str, Any],
) -> int:
    existing = conn.execute(
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
            layer,
            severity,
            event_code,
            entity_type,
            entity_type,
            entity_id,
            entity_id,
            ts_code,
            ts_code,
            trade_date,
            trade_date,
        ),
    ).fetchone()
    payload_json = _json_dumps(payload)
    if existing is not None:
        conn.execute(
            """
            UPDATE data_quality_events
            SET message = ?,
                payload_json = ?
            WHERE id = ?
            """,
            (message, payload_json, existing["id"]),
        )
        return int(existing["id"])

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
            layer,
            severity,
            event_code,
            entity_type,
            entity_id,
            ts_code,
            trade_date,
            message,
            payload_json,
        ),
    )
    return int(cursor.lastrowid)


def _reserve_market_operation(
    conn: sqlite3.Connection,
    request: RefreshMarketDataRequest,
    resolved: _ResolvedMarketScope,
    ctx: RequestContext,
) -> int | None:
    if not ctx.idempotency_key:
        return None
    request_json = _json_dumps(
        {
            "start_date": resolved.start_date,
            "end_date": resolved.end_date,
            "scope": request.scope,
            "ts_codes": resolved.ts_codes,
            "provider": request.provider,
            "include_daily_basic": request.include_daily_basic,
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
                operation_type = 'market_data_refresh',
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
            (ctx.request_id, resolved.end_date, request_json, ctx.operator, existing["id"]),
        )
        return int(existing["id"])

    cursor = conn.execute(
        """
        INSERT INTO operation_requests
          (idempotency_key, request_id, operation_type, as_of_date, status, request_json, operator)
        VALUES
          (?, ?, 'market_data_refresh', ?, 'started', ?, ?)
        """,
        (ctx.idempotency_key, ctx.request_id, resolved.end_date, request_json, ctx.operator),
    )
    return int(cursor.lastrowid)


def _reserve_calendar_operation(
    conn: sqlite3.Connection,
    request: RefreshTradeCalendarRequest,
    ctx: RequestContext,
) -> int | None:
    if not ctx.idempotency_key:
        return None
    request_json = _json_dumps(
        {
            "start_date": request.start_date,
            "end_date": request.end_date,
            "exchange": request.exchange,
            "provider": request.provider,
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
                operation_type = 'trade_calendar_refresh',
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
            (ctx.request_id, request.end_date, request_json, ctx.operator, existing["id"]),
        )
        return int(existing["id"])

    cursor = conn.execute(
        """
        INSERT INTO operation_requests
          (idempotency_key, request_id, operation_type, as_of_date, status, request_json, operator)
        VALUES
          (?, ?, 'trade_calendar_refresh', ?, 'started', ?, ?)
        """,
        (ctx.idempotency_key, ctx.request_id, request.end_date, request_json, ctx.operator),
    )
    return int(cursor.lastrowid)


def _completed_market_operation_result(
    conn: sqlite3.Connection,
    ctx: RequestContext,
) -> ServiceResult[RefreshMarketDataResult] | None:
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
    return _market_service_result_from_json(row["response_json"], ctx.request_id)


def _finish_operation(
    conn: sqlite3.Connection,
    operation_id: int | None,
    status: str,
    result: ServiceResult[Any],
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
            status,
            _json_dumps(result),
            first_error.code if first_error else None,
            first_error.message if first_error else None,
            operation_id,
        ),
    )


def _write_market_domain_event(
    conn: sqlite3.Connection,
    fetch_run_id: int,
    result: RefreshMarketDataResult,
    ctx: RequestContext,
) -> None:
    conn.execute(
        """
        INSERT INTO domain_events
          (event_type, entity_type, entity_id, payload_json, source, operator)
        VALUES
          ('market_data_refreshed', 'market_fetch_run', ?, ?, ?, ?)
        """,
        (fetch_run_id, _json_dumps(result), _domain_event_source(ctx.source), ctx.operator),
    )


def _write_calendar_domain_event(
    conn: sqlite3.Connection,
    operation_id: int | None,
    result: RefreshTradeCalendarResult,
    ctx: RequestContext,
) -> None:
    if operation_id is None:
        return
    conn.execute(
        """
        INSERT INTO domain_events
          (event_type, entity_type, entity_id, payload_json, source, operator)
        VALUES
          ('trade_calendar_refreshed', 'operation_request', ?, ?, ?, ?)
        """,
        (operation_id, _json_dumps(result), _domain_event_source(ctx.source), ctx.operator),
    )


def _failed_market_fetch_result(
    db_path: Path,
    request: RefreshMarketDataRequest,
    resolved: _ResolvedMarketScope,
    ctx: RequestContext,
    operation_id: int | None,
    fetch_run_id: int | None,
    exc: Exception,
) -> ServiceResult[RefreshMarketDataResult]:
    error = ServiceError(code="MARKET_PROVIDER_ERROR", message=str(exc))
    error_manifest = {
        "ts_codes": resolved.ts_codes,
        "include_daily_basic": request.include_daily_basic,
        "bars": 0,
        "daily_basic": 0,
        "error_code": error.code,
    }
    with connect(db_path) as conn:
        conn.execute("BEGIN")
        try:
            if fetch_run_id is None:
                fetch_run_id = _insert_market_fetch_run(
                    conn,
                    request,
                    resolved,
                    status="failed",
                    manifest=error_manifest,
                    error_message=error.message,
                )
            result_data = RefreshMarketDataResult(
                market_fetch_run_id=fetch_run_id,
                ts_code_count=len(resolved.ts_codes),
                bars_upserted=0,
                daily_basic_upserted=0,
                missing_ts_codes=resolved.ts_codes,
                coverage_start_date=None,
                coverage_end_date=None,
            )
            service_result = ServiceResult(
                status="failed",
                request_id=ctx.request_id,
                data=result_data,
                created_ids={"market_fetch_run_id": fetch_run_id},
                errors=[error],
                lineage={
                    "market_fetch_run_id": fetch_run_id,
                    "provider": request.provider,
                    "start_date": resolved.start_date,
                    "end_date": resolved.end_date,
                },
            )
            _finish_market_fetch_run(
                conn,
                fetch_run_id,
                "failed",
                service_result,
                manifest=error_manifest,
            )
            _finish_operation(conn, operation_id, "failed", service_result)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return service_result


def _missing_ts_codes(
    requested_ts_codes: Sequence[str],
    payload: MarketDataPayload,
    bars: Sequence[MarketBar],
) -> list[str]:
    bar_codes = {bar.ts_code for bar in bars}
    missing = set(payload.missing_ts_codes)
    missing.update(ts_code for ts_code in requested_ts_codes if ts_code not in bar_codes)
    return sorted(missing)


def _coverage_dates(bars: Sequence[MarketBar]) -> tuple[str | None, str | None]:
    if not bars:
        return None, None
    dates = [bar.trade_date for bar in bars]
    return min(dates), max(dates)


def _missing_calendar_dates(
    request: RefreshTradeCalendarRequest,
    days: Sequence[TradeCalendarDay],
) -> list[str]:
    returned_dates = {day.cal_date for day in days if day.exchange == request.exchange}
    return [date for date in iter_calendar_dates(request.start_date, request.end_date) if date not in returned_dates]


def _warnings_for_missing_ts_codes(missing_ts_codes: Sequence[str]) -> list[ServiceWarning]:
    if not missing_ts_codes:
        return []
    return [
        ServiceWarning(
            code="MARKET_DATA_MISSING",
            message=f"{len(missing_ts_codes)} ts_code(s) are missing market data.",
            severity="warning",
        )
    ]


def _warnings_for_missing_calendar_dates(missing_dates: Sequence[str]) -> list[ServiceWarning]:
    if not missing_dates:
        return []
    return [
        ServiceWarning(
            code="TRADE_CALENDAR_MISSING",
            message=f"{len(missing_dates)} calendar date(s) are missing.",
            severity="warning",
        )
    ]


def _empty_market_result(request: RefreshMarketDataRequest) -> RefreshMarketDataResult:
    return RefreshMarketDataResult(
        market_fetch_run_id=None,
        ts_code_count=len(request.ts_codes or []),
        bars_upserted=0,
        daily_basic_upserted=0,
        missing_ts_codes=[],
        coverage_start_date=request.start_date,
        coverage_end_date=None,
    )


def _empty_calendar_result(request: RefreshTradeCalendarRequest) -> RefreshTradeCalendarResult:
    return RefreshTradeCalendarResult(
        exchange=request.exchange,
        start_date=request.start_date,
        end_date=request.end_date,
        calendar_days_upserted=0,
        open_days=0,
        missing_dates=[],
    )


def _operation_status(service_status: str) -> str:
    if service_status == "success":
        return "success"
    if service_status == "partial_success":
        return "partial_success"
    if service_status == "skipped":
        return "skipped"
    return "failed"


def _domain_event_source(source: str) -> str:
    if source in {"system", "manual", "scheduler", "broker_import", "migration"}:
        return source
    if source == "cli":
        return "manual"
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


def _market_service_result_from_json(
    response_json: str,
    request_id: str | None,
) -> ServiceResult[RefreshMarketDataResult]:
    payload = json.loads(response_json)
    data = payload.get("data")
    result = None
    if data is not None:
        result = RefreshMarketDataResult(
            market_fetch_run_id=data.get("market_fetch_run_id"),
            ts_code_count=int(data.get("ts_code_count", 0)),
            bars_upserted=int(data.get("bars_upserted", 0)),
            daily_basic_upserted=int(data.get("daily_basic_upserted", 0)),
            missing_ts_codes=list(data.get("missing_ts_codes", [])),
            coverage_start_date=data.get("coverage_start_date"),
            coverage_end_date=data.get("coverage_end_date"),
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
