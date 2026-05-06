"""Trade execution recording service."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

from pgc_trading.config import Paths
from pgc_trading.market.calendar import is_yyyymmdd
from pgc_trading.portfolio.state_machines import (
    OPEN_POSITION_STATUSES,
    can_execute_plan,
    is_buy_action,
    is_sell_action,
    trade_source_allowed_for_account,
)
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult
from pgc_trading.services.portfolio_planning_service import (
    _domain_event_source,
    _load_trade_plan,
    _loads_json_object,
    _resolve_account,
)
from pgc_trading.storage.database import connect


@dataclass(frozen=True)
class RecordTradeRequest:
    trade_plan_id: int
    side: str
    executed_date: str
    executed_price: float
    shares: int
    account_key: str | None = None
    account_id: int | None = None
    fee: float = 0.0
    tax: float = 0.0
    source: str = "manual"
    slippage: float | None = None


@dataclass(frozen=True)
class RecordTradeResult:
    trade_id: int | None
    position_id: int | None
    equity_snapshot_id: int | None
    position_status: str | None
    cash_after: float | None
    planned_t2_date: str | None = None
    planned_t5_date: str | None = None


class ExecutionRecordingService:
    """Record executed trades and move position state from trade facts."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def record_trade(
        self,
        request: RecordTradeRequest,
        ctx: RequestContext,
    ) -> ServiceResult[RecordTradeResult]:
        errors = _validate_record_trade_request(request)
        if errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_record_result(),
                errors=errors,
            )

        with connect(self.db_path) as conn:
            if ctx.dry_run:
                return _record_trade_in_tx(conn, request, ctx, write=False)

            conn.execute("BEGIN")
            try:
                operation_id = _reserve_operation(conn, request, ctx)
                result = _record_trade_in_tx(conn, request, ctx, write=True)
                _write_record_trade_event(conn, result, ctx)
                _finish_operation(conn, operation_id, result)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise


def _record_trade_in_tx(
    conn: sqlite3.Connection,
    request: RecordTradeRequest,
    ctx: RequestContext,
    *,
    write: bool,
) -> ServiceResult[RecordTradeResult]:
    account = _resolve_account(conn, request.account_key, request.account_id)
    if isinstance(account, ServiceError):
        return _validation_failed(ctx, [account])
    if not trade_source_allowed_for_account(account.account_type, request.source):
        return _validation_failed(
            ctx,
            [
                ServiceError(
                    code="INVALID_TRADE_SOURCE",
                    message=f"Trade source {request.source!r} is not allowed for {account.account_type} accounts.",
                )
            ],
        )

    plan = _load_trade_plan(conn, request.trade_plan_id)
    if plan is None:
        return _validation_failed(
            ctx,
            [
                ServiceError(
                    code="TRADE_PLAN_NOT_FOUND",
                    message=f"Trade plan was not found: {request.trade_plan_id}.",
                    entity_type="trade_plan",
                    entity_id=request.trade_plan_id,
                )
            ],
        )
    if int(plan["account_id"]) != account.id:
        return _validation_failed(ctx, [_account_mismatch_error(request.trade_plan_id)])
    if not can_execute_plan(plan["status"]):
        return _validation_failed(
            ctx,
            [
                ServiceError(
                    code="INVALID_PLAN_STATUS",
                    message=f"Cannot execute plan in status: {plan['status']}.",
                    entity_type="trade_plan",
                    entity_id=request.trade_plan_id,
                )
            ],
        )
    if _duplicate_trade_exists(conn, request.trade_plan_id, request.side):
        return _validation_failed(
            ctx,
            [
                ServiceError(
                    code="DUPLICATE_TRADE",
                    message="Executed trade already exists for this plan and side.",
                    entity_type="trade_plan",
                    entity_id=request.trade_plan_id,
                )
            ],
        )

    if request.side == "buy":
        if not is_buy_action(plan["action"]):
            return _validation_failed(ctx, [_plan_side_error(request.trade_plan_id, "buy")])
        return _record_buy_trade(conn, request, ctx, account, plan, write=write)

    if not is_sell_action(plan["action"]):
        return _validation_failed(ctx, [_plan_side_error(request.trade_plan_id, "sell")])
    return _record_sell_trade(conn, request, ctx, account, plan, write=write)


def _record_buy_trade(
    conn: sqlite3.Connection,
    request: RecordTradeRequest,
    ctx: RequestContext,
    account: Any,
    plan: sqlite3.Row,
    *,
    write: bool,
) -> ServiceResult[RecordTradeResult]:
    signal = _load_signal(conn, plan["signal_id"])
    if isinstance(signal, ServiceError):
        return _validation_failed(ctx, [signal])
    planned_t2_date = _nth_open_date(conn, request.executed_date, 2)
    planned_t5_date = _nth_open_date(conn, request.executed_date, 5)
    if planned_t2_date is None or planned_t5_date is None:
        return _validation_failed(
            ctx,
            [
                ServiceError(
                    code="TRADE_CALENDAR_MISSING",
                    message="T+2/T+5 dates could not be derived from trade_calendar.",
                    severity="blocker",
                )
            ],
        )

    amount = request.executed_price * request.shares
    cash_before = _latest_cash(conn, account)
    cash_after = cash_before - amount - request.fee - request.tax
    if cash_after < -0.0001:
        return _validation_failed(
            ctx,
            [
                ServiceError(
                    code="INSUFFICIENT_CASH",
                    message="Buy trade would make account cash negative.",
                    entity_type="portfolio_account",
                    entity_id=account.id,
                )
            ],
        )

    trade_id = None
    position_id = None
    equity_snapshot_id = None
    if write:
        trade_id = _insert_trade(conn, request, plan, account.id, signal, amount)
        position_id = _insert_position(
            conn,
            account_id=account.id,
            signal_id=plan["signal_id"],
            entry_trade_id=trade_id,
            ts_code=signal["ts_code"],
            name=signal["name"],
            buy_date=request.executed_date,
            buy_price=request.executed_price,
            shares=request.shares,
            cost=amount + request.fee + request.tax,
            planned_t2_date=planned_t2_date,
            planned_t5_date=planned_t5_date,
        )
        _mark_plan_executed(conn, int(plan["id"]), ctx.operator)
        equity_snapshot_id = _upsert_equity_snapshot(conn, account, request.executed_date, cash_after)

    return ServiceResult(
        status="success",
        request_id=ctx.request_id,
        data=RecordTradeResult(
            trade_id=trade_id,
            position_id=position_id,
            equity_snapshot_id=equity_snapshot_id,
            position_status="waiting_t2",
            cash_after=cash_after,
            planned_t2_date=planned_t2_date,
            planned_t5_date=planned_t5_date,
        ),
        created_ids=_created_ids(trade_id, position_id, equity_snapshot_id),
        lineage={
            "account_id": account.id,
            "trade_plan_id": int(plan["id"]),
            "signal_id": int(plan["signal_id"]),
        },
    )


def _record_sell_trade(
    conn: sqlite3.Connection,
    request: RecordTradeRequest,
    ctx: RequestContext,
    account: Any,
    plan: sqlite3.Row,
    *,
    write: bool,
) -> ServiceResult[RecordTradeResult]:
    position = _position_for_sell_plan(conn, plan, account.id)
    if isinstance(position, ServiceError):
        return _validation_failed(ctx, [position])
    if request.shares != int(position["shares"]):
        return _validation_failed(
            ctx,
            [
                ServiceError(
                    code="PARTIAL_SELL_NOT_SUPPORTED",
                    message="WP12 skeleton requires full-share sell trades.",
                    entity_type="position",
                    entity_id=int(position["id"]),
                )
            ],
        )

    amount = request.executed_price * request.shares
    cash_before = _latest_cash(conn, account)
    cash_after = cash_before + amount - request.fee - request.tax

    trade_id = None
    equity_snapshot_id = None
    if write:
        signal = {
            "id": position["signal_id"],
            "ts_code": position["ts_code"],
            "name": position["name"],
        }
        trade_id = _insert_trade(conn, request, plan, account.id, signal, amount)
        conn.execute(
            """
            UPDATE positions
            SET status = 'closed',
                exit_trade_id = ?,
                closed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (trade_id, int(position["id"])),
        )
        _mark_plan_executed(conn, int(plan["id"]), ctx.operator)
        _mark_exit_decision_executed(conn, int(plan["id"]), trade_id)
        equity_snapshot_id = _upsert_equity_snapshot(conn, account, request.executed_date, cash_after)

    return ServiceResult(
        status="success",
        request_id=ctx.request_id,
        data=RecordTradeResult(
            trade_id=trade_id,
            position_id=int(position["id"]),
            equity_snapshot_id=equity_snapshot_id,
            position_status="closed",
            cash_after=cash_after,
        ),
        created_ids=_created_ids(trade_id, int(position["id"]), equity_snapshot_id),
        lineage={
            "account_id": account.id,
            "trade_plan_id": int(plan["id"]),
            "position_id": int(position["id"]),
        },
    )


def _validate_record_trade_request(request: RecordTradeRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if request.trade_plan_id <= 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="trade_plan_id must be positive."))
    if request.side not in {"buy", "sell"}:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="side must be buy or sell."))
    if not is_yyyymmdd(request.executed_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="executed_date must use YYYYMMDD format."))
    if request.executed_price <= 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="executed_price must be positive."))
    if request.shares <= 0 or request.shares % 100 != 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="shares must be a positive A-share board lot."))
    if request.fee < 0 or request.tax < 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="fee and tax cannot be negative."))
    return errors


def _load_signal(conn: sqlite3.Connection, signal_id: int | None) -> sqlite3.Row | ServiceError:
    if signal_id is None:
        return ServiceError(code="SIGNAL_NOT_FOUND", message="Trade plan has no signal_id.")
    row = conn.execute(
        "SELECT id, ts_code, name FROM strategy_signals WHERE id = ?",
        (signal_id,),
    ).fetchone()
    if row is None:
        return ServiceError(
            code="SIGNAL_NOT_FOUND",
            message=f"Signal was not found: {signal_id}.",
            entity_type="strategy_signal",
            entity_id=int(signal_id),
        )
    return row


def _position_for_sell_plan(
    conn: sqlite3.Connection,
    plan: sqlite3.Row,
    account_id: int,
) -> sqlite3.Row | ServiceError:
    payload = _loads_json_object(plan["plan_json"])
    position_id = payload.get("position_id")
    if position_id is not None:
        row = conn.execute(
            "SELECT * FROM positions WHERE id = ?",
            (int(position_id),),
        ).fetchone()
    else:
        row = conn.execute(
            f"""
            SELECT *
            FROM positions
            WHERE account_id = ?
              AND signal_id = ?
              AND status IN ({_status_placeholders()})
            ORDER BY id DESC
            LIMIT 1
            """,
            (account_id, plan["signal_id"], *_open_status_tuple()),
        ).fetchone()
    if row is None:
        return ServiceError(code="POSITION_NOT_FOUND", message="Open position was not found for sell plan.")
    if int(row["account_id"]) != account_id:
        return ServiceError(
            code="ACCOUNT_MISMATCH",
            message="Sell plan position belongs to a different account.",
            entity_type="position",
            entity_id=int(row["id"]),
        )
    if row["status"] not in OPEN_POSITION_STATUSES:
        return ServiceError(
            code="POSITION_NOT_OPEN",
            message=f"Position is not open: {row['status']}.",
            entity_type="position",
            entity_id=int(row["id"]),
        )
    return row


def _duplicate_trade_exists(conn: sqlite3.Connection, trade_plan_id: int, side: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM trades
        WHERE trade_plan_id = ?
          AND side = ?
          AND status IN ('executed', 'partial')
        LIMIT 1
        """,
        (trade_plan_id, side),
    ).fetchone()
    return row is not None


def _insert_trade(
    conn: sqlite3.Connection,
    request: RecordTradeRequest,
    plan: sqlite3.Row,
    account_id: int,
    signal: sqlite3.Row | dict[str, Any],
    amount: float,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO trades
          (
            account_id,
            trade_plan_id,
            signal_id,
            agent_decision_id,
            ts_code,
            name,
            side,
            planned_date,
            executed_date,
            executed_price,
            amount,
            shares,
            fee,
            tax,
            slippage,
            status,
            source
          )
        VALUES
          (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'executed', ?)
        """,
        (
            account_id,
            int(plan["id"]),
            plan["signal_id"],
            plan["agent_decision_id"],
            signal["ts_code"],
            signal["name"],
            request.side,
            plan["planned_trade_date"],
            request.executed_date,
            request.executed_price,
            amount,
            request.shares,
            request.fee,
            request.tax,
            request.slippage,
            request.source,
        ),
    )
    return int(cursor.lastrowid)


def _insert_position(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    signal_id: int,
    entry_trade_id: int,
    ts_code: str,
    name: str,
    buy_date: str,
    buy_price: float,
    shares: int,
    cost: float,
    planned_t2_date: str,
    planned_t5_date: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO positions
          (
            account_id,
            signal_id,
            entry_trade_id,
            ts_code,
            name,
            buy_date,
            buy_price,
            shares,
            cost,
            planned_t2_date,
            planned_t5_date,
            status
          )
        VALUES
          (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'waiting_t2')
        """,
        (
            account_id,
            signal_id,
            entry_trade_id,
            ts_code,
            name,
            buy_date,
            buy_price,
            shares,
            cost,
            planned_t2_date,
            planned_t5_date,
        ),
    )
    return int(cursor.lastrowid)


def _mark_plan_executed(conn: sqlite3.Connection, trade_plan_id: int, operator: str | None) -> None:
    conn.execute(
        """
        UPDATE trade_plans
        SET status = 'executed',
            operator = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (operator, trade_plan_id),
    )


def _mark_exit_decision_executed(
    conn: sqlite3.Connection,
    generated_trade_plan_id: int,
    trade_id: int,
) -> None:
    conn.execute(
        """
        UPDATE exit_decisions
        SET decision = 'executed',
            executed_exit_trade_id = ?
        WHERE generated_trade_plan_id = ?
        """,
        (trade_id, generated_trade_plan_id),
    )


def _nth_open_date(conn: sqlite3.Connection, after_date: str, n: int) -> str | None:
    rows = conn.execute(
        """
        SELECT cal_date
        FROM trade_calendar
        WHERE is_open = 1
          AND cal_date > ?
        ORDER BY cal_date
        LIMIT ?
        """,
        (after_date, n),
    ).fetchall()
    if len(rows) < n:
        return None
    return rows[-1]["cal_date"]


def _latest_cash(conn: sqlite3.Connection, account: Any) -> float:
    row = conn.execute(
        """
        SELECT cash
        FROM equity_snapshots
        WHERE account_id = ?
        ORDER BY as_of_date DESC, id DESC
        LIMIT 1
        """,
        (account.id,),
    ).fetchone()
    if row is None:
        return float(account.initial_cash)
    return float(row["cash"])


def _upsert_equity_snapshot(
    conn: sqlite3.Connection,
    account: Any,
    as_of_date: str,
    cash: float,
) -> int:
    market_value = _open_position_market_value(conn, account.id)
    total_equity = cash + market_value
    conn.execute(
        """
        INSERT INTO equity_snapshots
          (account_id, as_of_date, snapshot_type, cash, market_value, total_equity)
        VALUES
          (?, ?, 'after_trade', ?, ?, ?)
        ON CONFLICT(account_id, as_of_date, snapshot_type) DO UPDATE SET
          cash = excluded.cash,
          market_value = excluded.market_value,
          total_equity = excluded.total_equity
        """,
        (account.id, as_of_date, cash, market_value, total_equity),
    )
    row = conn.execute(
        """
        SELECT id
        FROM equity_snapshots
        WHERE account_id = ?
          AND as_of_date = ?
          AND snapshot_type = 'after_trade'
        """,
        (account.id, as_of_date),
    ).fetchone()
    return int(row["id"])


def _open_position_market_value(conn: sqlite3.Connection, account_id: int) -> float:
    rows = conn.execute(
        f"""
        SELECT COALESCE(SUM(cost), 0) AS market_value
        FROM positions
        WHERE account_id = ?
          AND status IN ({_status_placeholders()})
        """,
        (account_id, *_open_status_tuple()),
    ).fetchone()
    return float(rows["market_value"] or 0.0)


def _status_placeholders() -> str:
    return ", ".join("?" for _ in OPEN_POSITION_STATUSES)


def _open_status_tuple() -> tuple[str, ...]:
    return tuple(sorted(OPEN_POSITION_STATUSES))


def _created_ids(
    trade_id: int | None,
    position_id: int | None,
    equity_snapshot_id: int | None,
) -> dict[str, int]:
    created: dict[str, int] = {}
    if trade_id is not None:
        created["trade_id"] = trade_id
    if position_id is not None:
        created["position_id"] = position_id
    if equity_snapshot_id is not None:
        created["equity_snapshot_id"] = equity_snapshot_id
    return created


def _validation_failed(
    ctx: RequestContext,
    errors: list[ServiceError],
) -> ServiceResult[RecordTradeResult]:
    return ServiceResult(
        status="validation_failed",
        request_id=ctx.request_id,
        data=_empty_record_result(),
        errors=errors,
    )


def _empty_record_result() -> RecordTradeResult:
    return RecordTradeResult(
        trade_id=None,
        position_id=None,
        equity_snapshot_id=None,
        position_status=None,
        cash_after=None,
    )


def _account_mismatch_error(trade_plan_id: int) -> ServiceError:
    return ServiceError(
        code="ACCOUNT_MISMATCH",
        message="Trade plan belongs to a different account.",
        entity_type="trade_plan",
        entity_id=trade_plan_id,
    )


def _plan_side_error(trade_plan_id: int, side: str) -> ServiceError:
    return ServiceError(
        code="PLAN_SIDE_MISMATCH",
        message=f"Trade plan cannot record a {side} execution.",
        entity_type="trade_plan",
        entity_id=trade_plan_id,
    )


def _reserve_operation(
    conn: sqlite3.Connection,
    request: RecordTradeRequest,
    ctx: RequestContext,
) -> int | None:
    if not ctx.idempotency_key:
        return None
    request_json = _json_dumps({"request": request, "dry_run": ctx.dry_run})
    existing = conn.execute(
        "SELECT id FROM operation_requests WHERE idempotency_key = ?",
        (ctx.idempotency_key,),
    ).fetchone()
    if existing is not None:
        conn.execute(
            """
            UPDATE operation_requests
            SET request_id = ?,
                operation_type = 'trade_record',
                account_id = ?,
                as_of_date = ?,
                status = 'started',
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
                request.account_id,
                request.executed_date,
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
          (?, ?, 'trade_record', ?, ?, 'started', ?, ?)
        """,
        (
            ctx.idempotency_key,
            ctx.request_id,
            request.account_id,
            request.executed_date,
            request_json,
            ctx.operator,
        ),
    )
    return int(cursor.lastrowid)


def _finish_operation(
    conn: sqlite3.Connection,
    operation_id: int | None,
    result: ServiceResult[RecordTradeResult],
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
            "success" if result.status == "success" else "failed",
            _json_dumps(result),
            first_error.code if first_error else None,
            first_error.message if first_error else None,
            operation_id,
        ),
    )


def _write_record_trade_event(
    conn: sqlite3.Connection,
    result: ServiceResult[RecordTradeResult],
    ctx: RequestContext,
) -> None:
    if result.data is None or result.data.trade_id is None:
        return
    account_id = result.lineage.get("account_id")
    conn.execute(
        """
        INSERT INTO domain_events
          (event_type, entity_type, entity_id, account_id, payload_json, source, operator)
        VALUES
          ('trade_recorded', 'trade', ?, ?, ?, ?, ?)
        """,
        (
            result.data.trade_id,
            account_id,
            _json_dumps(
                {
                    "trade_id": result.data.trade_id,
                    "position_id": result.data.position_id,
                    "position_status": result.data.position_status,
                    "equity_snapshot_id": result.data.equity_snapshot_id,
                }
            ),
            _domain_event_source(ctx.source),
            ctx.operator,
        ),
    )


def _json_dumps(value: Any) -> str:
    return json.dumps(_to_jsonable(value), ensure_ascii=True, sort_keys=True)


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
