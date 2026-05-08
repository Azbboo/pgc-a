"""Portfolio trade-plan application service."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

from pgc_trading.config import Paths
from pgc_trading.market.calendar import is_yyyymmdd
from pgc_trading.portfolio.sizing import SizingPlan, plan_equal_slot_sizing
from pgc_trading.portfolio.state_machines import (
    BUY_PLAN_ACTION,
    SELL_PLAN_ACTIONS,
    can_cancel_plan,
    can_publish_plan,
)
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult
from pgc_trading.storage.database import connect


@dataclass(frozen=True)
class GenerateBuyPlanRequest:
    account_key: str | None = None
    account_id: int | None = None
    daily_pick_id: int | None = None
    review_date: str | None = None
    planned_trade_date: str | None = None
    agent_decision_id: int | None = None


@dataclass(frozen=True)
class GenerateSellPlanRequest:
    account_key: str | None = None
    account_id: int | None = None
    position_id: int | None = None
    exit_decision_id: int | None = None
    decision_date: str | None = None
    action: str = "sell_t5_timeout"
    planned_trade_date: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PublishTradePlanRequest:
    trade_plan_id: int
    account_key: str | None = None
    account_id: int | None = None


@dataclass(frozen=True)
class CancelTradePlanRequest:
    trade_plan_id: int
    cancel_reason: str
    account_key: str | None = None
    account_id: int | None = None


@dataclass(frozen=True)
class ListTradePlansRequest:
    account_key: str | None = None
    account_id: int | None = None
    status: str | None = None
    action: str | None = None
    as_of_date: str | None = None
    planned_trade_date: str | None = None
    limit: int = 100


@dataclass(frozen=True)
class ListTradePlansResult:
    account_id: int | None
    trade_plans: list["TradePlanDTO"]


@dataclass(frozen=True)
class GenerateTradePlanResult:
    trade_plan_id: int | None
    action: str
    status: str
    reason: str
    planned_trade_date: str | None
    planned_cash: float | None
    planned_shares: int | None
    free_position_slots: int
    idempotent: bool = False


@dataclass(frozen=True)
class TradePlanDTO:
    id: int
    account_id: int
    action: str
    status: str
    as_of_date: str
    planned_trade_date: str | None
    planned_buy_date: str | None
    reason: str | None
    cancel_reason: str | None = None
    daily_pick_id: int | None = None
    signal_id: int | None = None
    planned_cash: float | None = None
    planned_shares: int | None = None
    ts_code: str | None = None
    name: str | None = None
    operator: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class _Account:
    id: int
    account_key: str
    account_type: str
    initial_cash: float
    max_positions: int
    position_sizing: str


@dataclass(frozen=True)
class _DailyPick:
    id: int
    strategy_run_id: int
    signal_id: int
    review_date: str
    planned_buy_date: str | None
    score: float
    ts_code: str
    name: str


class PortfolioPlanningService:
    """Generate and manage trade plans without recording executions."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def list_trade_plans(
        self,
        request: ListTradePlansRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ListTradePlansResult]:
        errors = _validate_list_trade_plans_request(request)
        if errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=ListTradePlansResult(account_id=request.account_id, trade_plans=[]),
                errors=errors,
            )

        with connect(self.db_path) as conn:
            account = _resolve_account(
                conn,
                request.account_key,
                request.account_id,
                allow_live_dry_run=True,
            )
            if isinstance(account, ServiceError):
                return ServiceResult(
                    status="validation_failed",
                    request_id=ctx.request_id,
                    data=ListTradePlansResult(account_id=request.account_id, trade_plans=[]),
                    errors=[account],
                )

            clauses = ["account_id = ?"]
            params: list[object] = [account.id]
            if request.status is not None:
                clauses.append("status = ?")
                params.append(request.status)
            if request.action is not None:
                clauses.append("action = ?")
                params.append(request.action)
            if request.as_of_date is not None:
                clauses.append("as_of_date = ?")
                params.append(request.as_of_date)
            if request.planned_trade_date is not None:
                clauses.append("planned_trade_date = ?")
                params.append(request.planned_trade_date)

            rows = conn.execute(
                f"""
                SELECT *
                FROM trade_plans
                WHERE {' AND '.join(clauses)}
                ORDER BY planned_trade_date DESC, id DESC
                LIMIT ?
                """,
                tuple([*params, request.limit]),
            ).fetchall()

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=ListTradePlansResult(
                account_id=account.id,
                trade_plans=[_trade_plan_dto(row) for row in rows],
            ),
            lineage={"account_id": account.id},
        )

    def generate_buy_plan(
        self,
        request: GenerateBuyPlanRequest,
        ctx: RequestContext,
    ) -> ServiceResult[GenerateTradePlanResult]:
        errors = _validate_buy_request(request)
        if errors:
            return _validation_failed(ctx, _empty_plan_result(BUY_PLAN_ACTION), errors)

        with connect(self.db_path) as conn:
            if ctx.dry_run:
                return _generate_buy_plan_in_tx(conn, request, ctx, write=False)

            conn.execute("BEGIN")
            try:
                operation_id = _reserve_operation(
                    conn,
                    "portfolio_generate_buy_plan",
                    ctx,
                    request,
                    account_id=request.account_id,
                    as_of_date=request.review_date,
                )
                result = _generate_buy_plan_in_tx(conn, request, ctx, write=True)
                _write_plan_event(conn, result, ctx, "trade_plan_generated")
                _finish_operation(conn, operation_id, result)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def generate_sell_plan(
        self,
        request: GenerateSellPlanRequest,
        ctx: RequestContext,
    ) -> ServiceResult[GenerateTradePlanResult]:
        errors = _validate_sell_request(request)
        if errors:
            return _validation_failed(ctx, _empty_plan_result(request.action), errors)

        with connect(self.db_path) as conn:
            if ctx.dry_run:
                return _generate_sell_plan_in_tx(conn, request, ctx, write=False)

            conn.execute("BEGIN")
            try:
                operation_id = _reserve_operation(
                    conn,
                    "portfolio_generate_sell_plan",
                    ctx,
                    request,
                    account_id=request.account_id,
                    as_of_date=request.decision_date,
                )
                result = _generate_sell_plan_in_tx(conn, request, ctx, write=True)
                _write_plan_event(conn, result, ctx, "trade_plan_generated")
                _finish_operation(conn, operation_id, result)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def publish_plan(
        self,
        request: PublishTradePlanRequest,
        ctx: RequestContext,
    ) -> ServiceResult[TradePlanDTO]:
        with connect(self.db_path) as conn:
            conn.execute("BEGIN")
            try:
                plan = _load_trade_plan(conn, request.trade_plan_id)
                if plan is None:
                    result = ServiceResult(
                        status="validation_failed",
                        request_id=ctx.request_id,
                        errors=[
                            ServiceError(
                                code="TRADE_PLAN_NOT_FOUND",
                                message=f"Trade plan was not found: {request.trade_plan_id}.",
                                entity_type="trade_plan",
                                entity_id=request.trade_plan_id,
                            )
                        ],
                    )
                    conn.commit()
                    return result
                account = _resolve_account(
                    conn,
                    request.account_key,
                    request.account_id or int(plan["account_id"]),
                    allow_live_writes=ctx.allow_live_writes,
                )
                if isinstance(account, ServiceError):
                    return _validation_failed(ctx, None, [account])
                if int(plan["account_id"]) != account.id:
                    return _validation_failed(ctx, None, [_account_mismatch_error(request.trade_plan_id)])
                if plan["status"] == "active":
                    conn.commit()
                    return ServiceResult(status="success", request_id=ctx.request_id, data=_trade_plan_dto(plan))
                if not can_publish_plan(plan["status"]):
                    return _validation_failed(
                        ctx,
                        None,
                        [
                            ServiceError(
                                code="INVALID_PLAN_STATUS",
                                message=f"Cannot publish plan in status: {plan['status']}.",
                                entity_type="trade_plan",
                                entity_id=request.trade_plan_id,
                            )
                        ],
                    )
                conn.execute(
                    """
                    UPDATE trade_plans
                    SET status = 'active',
                        operator = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (ctx.operator, request.trade_plan_id),
                )
                updated = _load_trade_plan(conn, request.trade_plan_id)
                _write_domain_event(
                    conn,
                    "trade_plan_published",
                    "trade_plan",
                    request.trade_plan_id,
                    account.id,
                    {"trade_plan_id": request.trade_plan_id},
                    ctx,
                )
                conn.commit()
                return ServiceResult(
                    status="success",
                    request_id=ctx.request_id,
                    data=_trade_plan_dto(updated),
                    created_ids={"trade_plan_id": request.trade_plan_id},
                )
            except Exception:
                conn.rollback()
                raise

    def cancel_plan(
        self,
        request: CancelTradePlanRequest,
        ctx: RequestContext,
    ) -> ServiceResult[TradePlanDTO]:
        if not request.cancel_reason.strip():
            return _validation_failed(
                ctx,
                None,
                [ServiceError(code="VALIDATION_ERROR", message="cancel_reason is required.")],
            )

        with connect(self.db_path) as conn:
            conn.execute("BEGIN")
            try:
                plan = _load_trade_plan(conn, request.trade_plan_id)
                if plan is None:
                    return _validation_failed(
                        ctx,
                        None,
                        [
                            ServiceError(
                                code="TRADE_PLAN_NOT_FOUND",
                                message=f"Trade plan was not found: {request.trade_plan_id}.",
                                entity_type="trade_plan",
                                entity_id=request.trade_plan_id,
                            )
                        ],
                    )
                account = _resolve_account(
                    conn,
                    request.account_key,
                    request.account_id or int(plan["account_id"]),
                    allow_live_writes=ctx.allow_live_writes,
                )
                if isinstance(account, ServiceError):
                    return _validation_failed(ctx, None, [account])
                if int(plan["account_id"]) != account.id:
                    return _validation_failed(ctx, None, [_account_mismatch_error(request.trade_plan_id)])
                if not can_cancel_plan(plan["status"]):
                    return _validation_failed(
                        ctx,
                        None,
                        [
                            ServiceError(
                                code="INVALID_PLAN_STATUS",
                                message=f"Cannot cancel plan in status: {plan['status']}.",
                                entity_type="trade_plan",
                                entity_id=request.trade_plan_id,
                            )
                        ],
                    )
                conn.execute(
                    """
                    UPDATE trade_plans
                    SET status = 'cancelled',
                        cancel_reason = ?,
                        operator = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (request.cancel_reason, ctx.operator, request.trade_plan_id),
                )
                updated = _load_trade_plan(conn, request.trade_plan_id)
                _write_domain_event(
                    conn,
                    "trade_plan_cancelled",
                    "trade_plan",
                    request.trade_plan_id,
                    account.id,
                    {"trade_plan_id": request.trade_plan_id, "cancel_reason": request.cancel_reason},
                    ctx,
                )
                conn.commit()
                return ServiceResult(
                    status="success",
                    request_id=ctx.request_id,
                    data=_trade_plan_dto(updated),
                    created_ids={"trade_plan_id": request.trade_plan_id},
                )
            except Exception:
                conn.rollback()
                raise


def _generate_buy_plan_in_tx(
    conn: sqlite3.Connection,
    request: GenerateBuyPlanRequest,
    ctx: RequestContext,
    *,
    write: bool,
) -> ServiceResult[GenerateTradePlanResult]:
    account = _resolve_account(
        conn,
        request.account_key,
        request.account_id,
        allow_live_dry_run=ctx.dry_run,
        allow_live_writes=ctx.allow_live_writes,
    )
    if isinstance(account, ServiceError):
        return _validation_failed(ctx, _empty_plan_result(BUY_PLAN_ACTION), [account])

    daily_pick = _load_daily_pick(conn, request.daily_pick_id, request.review_date)
    if isinstance(daily_pick, ServiceError):
        return _validation_failed(ctx, _empty_plan_result(BUY_PLAN_ACTION), [daily_pick])

    existing = _find_existing_buy_plan(conn, account.id, daily_pick.signal_id)
    if existing is not None:
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=_plan_result_from_row(existing, idempotent=True),
            created_ids={"trade_plan_id": int(existing["id"])},
            lineage=_buy_lineage(account, daily_pick),
        )

    planned_trade_date = request.planned_trade_date or daily_pick.planned_buy_date
    if planned_trade_date is None:
        planned_trade_date = _next_open_date(conn, daily_pick.review_date)
    if planned_trade_date is None:
        return _validation_failed(
            ctx,
            _empty_plan_result(BUY_PLAN_ACTION),
            [
                ServiceError(
                    code="TRADE_CALENDAR_MISSING",
                    message=f"Next open trade date was not found after {daily_pick.review_date}.",
                    severity="blocker",
                )
            ],
        )

    sizing = _build_sizing(conn, account, daily_pick)
    action = BUY_PLAN_ACTION
    status = "active"
    reason = "daily_pick"
    if sizing.free_position_slots <= 0:
        action = "skip_max_positions"
        status = "skipped"
        reason = "max_positions"
    elif (sizing.planned_cash or 0.0) <= 0 or (sizing.planned_shares or 0) <= 0:
        action = "skip_no_cash"
        status = "skipped"
        reason = "no_cash_or_board_lot"

    if status == "skipped":
        skipped = _find_existing_skipped_plan(conn, account.id, daily_pick.signal_id, action, daily_pick.review_date)
        if skipped is not None:
            return ServiceResult(
                status="skipped",
                request_id=ctx.request_id,
                data=_plan_result_from_row(skipped, idempotent=True),
                created_ids={"trade_plan_id": int(skipped["id"])},
                lineage=_buy_lineage(account, daily_pick),
            )

    plan_id = None
    if write:
        plan_id = _insert_trade_plan(
            conn,
            account_id=account.id,
            daily_pick_id=daily_pick.id,
            signal_id=daily_pick.signal_id,
            agent_decision_id=request.agent_decision_id,
            as_of_date=daily_pick.review_date,
            planned_trade_date=planned_trade_date,
            planned_buy_date=planned_trade_date,
            action=action,
            reason=reason,
            status=status,
            plan_json={
                "daily_pick_id": daily_pick.id,
                "signal_id": daily_pick.signal_id,
                "ts_code": daily_pick.ts_code,
                "name": daily_pick.name,
                "score": daily_pick.score,
                "planned_cash": sizing.planned_cash,
                "planned_shares": sizing.planned_shares,
                "free_position_slots": sizing.free_position_slots,
                "price_reference": sizing.price_reference,
                "price_reference_date": daily_pick.review_date,
            },
            operator=ctx.operator,
        )

    data = GenerateTradePlanResult(
        trade_plan_id=plan_id,
        action=action,
        status=status,
        reason=reason,
        planned_trade_date=planned_trade_date,
        planned_cash=sizing.planned_cash,
        planned_shares=sizing.planned_shares,
        free_position_slots=sizing.free_position_slots,
    )
    return ServiceResult(
        status="skipped" if status == "skipped" else "success",
        request_id=ctx.request_id,
        data=data,
        created_ids={"trade_plan_id": plan_id} if plan_id is not None else {},
        lineage=_buy_lineage(account, daily_pick),
    )


def _generate_sell_plan_in_tx(
    conn: sqlite3.Connection,
    request: GenerateSellPlanRequest,
    ctx: RequestContext,
    *,
    write: bool,
) -> ServiceResult[GenerateTradePlanResult]:
    account = _resolve_account(
        conn,
        request.account_key,
        request.account_id,
        allow_live_dry_run=ctx.dry_run,
        allow_live_writes=ctx.allow_live_writes,
    )
    if isinstance(account, ServiceError):
        return _validation_failed(ctx, _empty_plan_result(request.action), [account])

    position = _load_position(conn, request.position_id, request.exit_decision_id)
    if isinstance(position, ServiceError):
        return _validation_failed(ctx, _empty_plan_result(request.action), [position])
    if int(position["account_id"]) != account.id:
        return _validation_failed(ctx, _empty_plan_result(request.action), [_position_account_mismatch_error(int(position["id"]))])

    exit_decision = None
    if request.exit_decision_id is not None:
        exit_decision = _load_exit_decision(conn, request.exit_decision_id)
        if exit_decision is None:
            return _validation_failed(
                ctx,
                _empty_plan_result(request.action),
                [
                    ServiceError(
                        code="EXIT_DECISION_NOT_FOUND",
                        message=f"Exit decision was not found: {request.exit_decision_id}.",
                        entity_type="exit_decision",
                        entity_id=request.exit_decision_id,
                    )
                ],
            )
        if int(exit_decision["account_id"]) != account.id or int(exit_decision["position_id"]) != int(position["id"]):
            return _validation_failed(
                ctx,
                _empty_plan_result(request.action),
                [_exit_decision_mismatch_error(request.exit_decision_id)],
            )
        if exit_decision["generated_trade_plan_id"] is not None:
            existing = _load_trade_plan(conn, int(exit_decision["generated_trade_plan_id"]))
            if existing is not None:
                return ServiceResult(
                    status="success",
                    request_id=ctx.request_id,
                    data=_plan_result_from_row(existing, idempotent=True),
                    created_ids={"trade_plan_id": int(existing["id"])},
                    lineage=_sell_lineage(account, position, exit_decision),
                )

    decision_date = request.decision_date
    if decision_date is None and exit_decision is not None:
        decision_date = exit_decision["decision_date"]
    if decision_date is None:
        return _validation_failed(
            ctx,
            _empty_plan_result(request.action),
            [ServiceError(code="VALIDATION_ERROR", message="decision_date is required.")],
        )
    planned_trade_date = request.planned_trade_date
    if planned_trade_date is None and exit_decision is not None:
        planned_trade_date = exit_decision["planned_exit_date"]
    if planned_trade_date is None:
        planned_trade_date = _next_open_date(conn, decision_date)
    if planned_trade_date is None:
        return _validation_failed(
            ctx,
            _empty_plan_result(request.action),
            [
                ServiceError(
                    code="TRADE_CALENDAR_MISSING",
                    message=f"Next open trade date was not found after {decision_date}.",
                    severity="blocker",
                )
            ],
        )

    plan_id = None
    reason = request.reason or (exit_decision["reason"] if exit_decision is not None else "exit")
    if write:
        plan_id = _insert_trade_plan(
            conn,
            account_id=account.id,
            daily_pick_id=None,
            signal_id=position["signal_id"],
            agent_decision_id=None,
            as_of_date=decision_date,
            planned_trade_date=planned_trade_date,
            planned_buy_date=None,
            action=request.action,
            reason=reason,
            status="active",
            plan_json={
                "position_id": int(position["id"]),
                "exit_decision_id": request.exit_decision_id,
                "ts_code": position["ts_code"],
                "name": position["name"],
                "shares": int(position["shares"]),
                "buy_price": float(position["buy_price"]),
            },
            operator=ctx.operator,
        )
        if request.exit_decision_id is not None:
            conn.execute(
                """
                UPDATE exit_decisions
                SET generated_trade_plan_id = ?
                WHERE id = ?
                """,
                (plan_id, request.exit_decision_id),
            )

    data = GenerateTradePlanResult(
        trade_plan_id=plan_id,
        action=request.action,
        status="active",
        reason=reason,
        planned_trade_date=planned_trade_date,
        planned_cash=None,
        planned_shares=int(position["shares"]),
        free_position_slots=_free_slots(conn, account),
    )
    return ServiceResult(
        status="success",
        request_id=ctx.request_id,
        data=data,
        created_ids={"trade_plan_id": plan_id} if plan_id is not None else {},
        lineage=_sell_lineage(account, position, exit_decision),
    )


def _validate_buy_request(request: GenerateBuyPlanRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if request.daily_pick_id is None and request.review_date is None:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="daily_pick_id or review_date is required."))
    if request.review_date is not None and not is_yyyymmdd(request.review_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="review_date must use YYYYMMDD format."))
    if request.planned_trade_date is not None and not is_yyyymmdd(request.planned_trade_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="planned_trade_date must use YYYYMMDD format."))
    return errors


def _validate_sell_request(request: GenerateSellPlanRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if request.action not in SELL_PLAN_ACTIONS:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="Unsupported sell plan action."))
    if request.position_id is None and request.exit_decision_id is None:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="position_id or exit_decision_id is required."))
    if request.decision_date is not None and not is_yyyymmdd(request.decision_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="decision_date must use YYYYMMDD format."))
    if request.planned_trade_date is not None and not is_yyyymmdd(request.planned_trade_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="planned_trade_date must use YYYYMMDD format."))
    return errors


def _resolve_account(
    conn: sqlite3.Connection,
    account_key: str | None,
    account_id: int | None,
    *,
    allow_live_dry_run: bool = False,
    allow_live_writes: bool = False,
    live_block_code: str = "LIVE_PLAN_APPLY_DISABLED",
    live_block_message: str = "Live account planning is dry-run only until live enablement is approved.",
) -> _Account | ServiceError:
    if account_id is None and not account_key:
        return ServiceError(code="VALIDATION_ERROR", message="account_key or account_id is required.")
    if account_id is not None:
        row = conn.execute(
            """
            SELECT id, account_key, account_type, initial_cash, max_positions, position_sizing, status
            FROM portfolio_accounts
            WHERE id = ?
            """,
            (account_id,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT id, account_key, account_type, initial_cash, max_positions, position_sizing, status
            FROM portfolio_accounts
            WHERE account_key = ?
            """,
            (account_key,),
        ).fetchone()
    if row is None:
        return ServiceError(code="ACCOUNT_NOT_FOUND", message="Portfolio account was not found.")
    if account_key and row["account_key"] != account_key:
        return ServiceError(code="ACCOUNT_MISMATCH", message="account_key and account_id point to different accounts.")
    if row["status"] != "active":
        return ServiceError(code="ACCOUNT_INACTIVE", message=f"Account is not active: {row['account_key']}.")
    if row["account_type"] == "live" and (allow_live_dry_run or allow_live_writes):
        return _Account(
            id=int(row["id"]),
            account_key=row["account_key"],
            account_type=row["account_type"],
            initial_cash=float(row["initial_cash"]),
            max_positions=int(row["max_positions"]),
            position_sizing=row["position_sizing"],
        )
    if row["account_type"] != "paper":
        return ServiceError(
            code=live_block_code if row["account_type"] == "live" else "UNSUPPORTED_ACCOUNT_TYPE",
            message=live_block_message,
            entity_type="portfolio_account",
            entity_id=int(row["id"]),
            severity="blocker",
        )
    return _Account(
        id=int(row["id"]),
        account_key=row["account_key"],
        account_type=row["account_type"],
        initial_cash=float(row["initial_cash"]),
        max_positions=int(row["max_positions"]),
        position_sizing=row["position_sizing"],
    )


def _load_daily_pick(
    conn: sqlite3.Connection,
    daily_pick_id: int | None,
    review_date: str | None,
) -> _DailyPick | ServiceError:
    where = "dp.id = ?"
    params: tuple[object, ...] = (daily_pick_id,)
    if daily_pick_id is None:
        where = "dp.review_date = ?"
        params = (review_date,)
    row = conn.execute(
        f"""
        SELECT
          dp.id,
          dp.strategy_run_id,
          dp.signal_id,
          dp.review_date,
          dp.planned_buy_date,
          dp.score,
          ss.ts_code,
          ss.name
        FROM daily_picks dp
        JOIN strategy_signals ss ON ss.id = dp.signal_id
        WHERE {where}
        ORDER BY dp.id DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    if row is None:
        return ServiceError(code="DAILY_PICK_NOT_FOUND", message="Daily pick was not found.")
    return _DailyPick(
        id=int(row["id"]),
        strategy_run_id=int(row["strategy_run_id"]),
        signal_id=int(row["signal_id"]),
        review_date=row["review_date"],
        planned_buy_date=row["planned_buy_date"],
        score=float(row["score"]),
        ts_code=row["ts_code"],
        name=row["name"],
    )


def _build_sizing(
    conn: sqlite3.Connection,
    account: _Account,
    daily_pick: _DailyPick,
) -> SizingPlan:
    cash = _latest_cash(conn, account)
    open_positions = _open_position_count(conn, account.id)
    price_reference = _latest_close(conn, daily_pick.ts_code, daily_pick.review_date)
    return plan_equal_slot_sizing(
        cash=cash,
        max_positions=account.max_positions,
        open_positions=open_positions,
        price_reference=price_reference,
    )


def _latest_cash(conn: sqlite3.Connection, account: _Account) -> float:
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
        return account.initial_cash
    return float(row["cash"])


def _latest_close(conn: sqlite3.Connection, ts_code: str, as_of_date: str) -> float | None:
    row = conn.execute(
        """
        SELECT close AS close_price
        FROM market_bars
        WHERE ts_code = ?
          AND trade_date <= ?
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        (ts_code, as_of_date),
    ).fetchone()
    if row is None or row["close_price"] is None:
        return None
    return float(row["close_price"])


def _open_position_count(conn: sqlite3.Connection, account_id: int) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM positions
            WHERE account_id = ?
              AND status IN (
                'open',
                'waiting_t2',
                'need_t2_decision',
                'holding_to_t5',
                'need_t5_exit',
                'planned_exit',
                'partially_closed'
              )
            """,
            (account_id,),
        ).fetchone()[0]
    )


def _free_slots(conn: sqlite3.Connection, account: _Account) -> int:
    return max(account.max_positions - _open_position_count(conn, account.id), 0)


def _next_open_date(conn: sqlite3.Connection, after_date: str) -> str | None:
    row = conn.execute(
        """
        SELECT cal_date
        FROM trade_calendar
        WHERE is_open = 1
          AND cal_date > ?
        ORDER BY cal_date
        LIMIT 1
        """,
        (after_date,),
    ).fetchone()
    return None if row is None else row["cal_date"]


def _find_existing_buy_plan(
    conn: sqlite3.Connection,
    account_id: int,
    signal_id: int,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM trade_plans
        WHERE account_id = ?
          AND signal_id = ?
          AND action = 'buy_next_open'
          AND status IN ('draft', 'active')
        ORDER BY id DESC
        LIMIT 1
        """,
        (account_id, signal_id),
    ).fetchone()


def _find_existing_skipped_plan(
    conn: sqlite3.Connection,
    account_id: int,
    signal_id: int,
    action: str,
    as_of_date: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM trade_plans
        WHERE account_id = ?
          AND signal_id = ?
          AND action = ?
          AND as_of_date = ?
          AND status = 'skipped'
        ORDER BY id DESC
        LIMIT 1
        """,
        (account_id, signal_id, action, as_of_date),
    ).fetchone()


def _insert_trade_plan(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    daily_pick_id: int | None,
    signal_id: int | None,
    agent_decision_id: int | None,
    as_of_date: str,
    planned_trade_date: str | None,
    planned_buy_date: str | None,
    action: str,
    reason: str,
    status: str,
    plan_json: dict[str, Any],
    operator: str | None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO trade_plans
          (
            account_id,
            daily_pick_id,
            signal_id,
            agent_decision_id,
            as_of_date,
            planned_trade_date,
            planned_buy_date,
            action,
            reason,
            plan_json,
            status,
            operator
          )
        VALUES
          (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account_id,
            daily_pick_id,
            signal_id,
            agent_decision_id,
            as_of_date,
            planned_trade_date,
            planned_buy_date,
            action,
            reason,
            _json_dumps(plan_json),
            status,
            operator,
        ),
    )
    return int(cursor.lastrowid)


def _load_position(
    conn: sqlite3.Connection,
    position_id: int | None,
    exit_decision_id: int | None,
) -> sqlite3.Row | ServiceError:
    if position_id is not None:
        row = conn.execute("SELECT * FROM positions WHERE id = ?", (position_id,)).fetchone()
    else:
        row = conn.execute(
            """
            SELECT p.*
            FROM positions p
            JOIN exit_decisions ed ON ed.position_id = p.id
            WHERE ed.id = ?
            """,
            (exit_decision_id,),
        ).fetchone()
    if row is None:
        return ServiceError(code="POSITION_NOT_FOUND", message="Position was not found.")
    if row["status"] == "closed":
        return ServiceError(
            code="POSITION_CLOSED",
            message=f"Position is already closed: {row['id']}.",
            entity_type="position",
            entity_id=int(row["id"]),
        )
    return row


def _load_exit_decision(conn: sqlite3.Connection, exit_decision_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM exit_decisions WHERE id = ?", (exit_decision_id,)).fetchone()


def _load_trade_plan(conn: sqlite3.Connection, trade_plan_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM trade_plans WHERE id = ?", (trade_plan_id,)).fetchone()


def _trade_plan_dto(row: sqlite3.Row) -> TradePlanDTO:
    payload = _loads_json_object(row["plan_json"])
    planned_shares = payload.get("planned_shares")
    if planned_shares is None:
        planned_shares = payload.get("shares")
    ts_code = payload.get("ts_code")
    name = payload.get("name")
    return TradePlanDTO(
        id=int(row["id"]),
        account_id=int(row["account_id"]),
        action=row["action"],
        status=row["status"],
        as_of_date=row["as_of_date"],
        planned_trade_date=row["planned_trade_date"],
        planned_buy_date=row["planned_buy_date"],
        reason=row["reason"],
        cancel_reason=row["cancel_reason"],
        daily_pick_id=_optional_int(row["daily_pick_id"]),
        signal_id=_optional_int(row["signal_id"]),
        planned_cash=_optional_float(payload.get("planned_cash")),
        planned_shares=_optional_int(planned_shares),
        ts_code=None if ts_code is None else str(ts_code),
        name=None if name is None else str(name),
        operator=row["operator"],
        created_at=row["created_at"],
    )


def _validate_list_trade_plans_request(request: ListTradePlansRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if request.account_id is None and not request.account_key:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="account_key or account_id is required."))
    if request.account_id is not None and request.account_id <= 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="account_id must be positive."))
    if request.account_key is not None and not request.account_key.strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="account_key cannot be blank when provided."))
    if request.limit <= 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="limit must be positive."))
    if request.limit > 500:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="limit must be 500 or less."))
    if request.status is not None and request.status not in {
        "draft",
        "active",
        "executed",
        "skipped",
        "cancelled",
        "expired",
        "superseded",
    }:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="status is invalid."))
    if request.action is not None and request.action not in {
        "buy_next_open",
        "skip_no_cash",
        "skip_max_positions",
        "skip_agent_risk",
        "skip_manual",
        "hold",
        "sell_t2_take_profit",
        "sell_t2_stop_loss",
        "sell_t5_timeout",
        "manual_review",
    }:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="action is invalid."))
    if request.as_of_date is not None and not is_yyyymmdd(request.as_of_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="as_of_date must use YYYYMMDD format."))
    if request.planned_trade_date is not None and not is_yyyymmdd(request.planned_trade_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="planned_trade_date must use YYYYMMDD format."))
    return errors


def _plan_result_from_row(row: sqlite3.Row, *, idempotent: bool) -> GenerateTradePlanResult:
    payload = _loads_json_object(row["plan_json"])
    return GenerateTradePlanResult(
        trade_plan_id=int(row["id"]),
        action=row["action"],
        status=row["status"],
        reason=row["reason"] or "",
        planned_trade_date=row["planned_trade_date"],
        planned_cash=_optional_float(payload.get("planned_cash")),
        planned_shares=_optional_int(payload.get("planned_shares") or payload.get("shares")),
        free_position_slots=int(payload.get("free_position_slots", 0) or 0),
        idempotent=idempotent,
    )


def _empty_plan_result(action: str) -> GenerateTradePlanResult:
    return GenerateTradePlanResult(
        trade_plan_id=None,
        action=action,
        status="validation_failed",
        reason="validation_failed",
        planned_trade_date=None,
        planned_cash=None,
        planned_shares=None,
        free_position_slots=0,
    )


def _validation_failed(
    ctx: RequestContext,
    data: GenerateTradePlanResult | TradePlanDTO | None,
    errors: list[ServiceError],
) -> ServiceResult[Any]:
    return ServiceResult(status="validation_failed", request_id=ctx.request_id, data=data, errors=errors)


def _buy_lineage(account: _Account, daily_pick: _DailyPick) -> dict[str, int | str | None]:
    return {
        "account_id": account.id,
        "account_key": account.account_key,
        "daily_pick_id": daily_pick.id,
        "signal_id": daily_pick.signal_id,
        "review_date": daily_pick.review_date,
    }


def _sell_lineage(
    account: _Account,
    position: sqlite3.Row,
    exit_decision: sqlite3.Row | None,
) -> dict[str, int | str | None]:
    return {
        "account_id": account.id,
        "account_key": account.account_key,
        "position_id": int(position["id"]),
        "signal_id": position["signal_id"],
        "exit_decision_id": None if exit_decision is None else int(exit_decision["id"]),
    }


def _account_mismatch_error(trade_plan_id: int) -> ServiceError:
    return ServiceError(
        code="ACCOUNT_MISMATCH",
        message="Trade plan belongs to a different account.",
        entity_type="trade_plan",
        entity_id=trade_plan_id,
    )


def _position_account_mismatch_error(position_id: int) -> ServiceError:
    return ServiceError(
        code="ACCOUNT_MISMATCH",
        message="Position belongs to a different account.",
        entity_type="position",
        entity_id=position_id,
    )


def _exit_decision_mismatch_error(exit_decision_id: int) -> ServiceError:
    return ServiceError(
        code="EXIT_DECISION_MISMATCH",
        message="Exit decision does not match the requested account or position.",
        entity_type="exit_decision",
        entity_id=exit_decision_id,
    )


def _reserve_operation(
    conn: sqlite3.Connection,
    operation_type: str,
    ctx: RequestContext,
    request: Any,
    *,
    account_id: int | None,
    as_of_date: str | None,
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
                operation_type = ?,
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
            (ctx.request_id, operation_type, account_id, as_of_date, request_json, ctx.operator, existing["id"]),
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
          (?, ?, ?, ?, ?, 'started', ?, ?)
        """,
        (ctx.idempotency_key, ctx.request_id, operation_type, account_id, as_of_date, request_json, ctx.operator),
    )
    return int(cursor.lastrowid)


def _finish_operation(
    conn: sqlite3.Connection,
    operation_id: int | None,
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
            _operation_status(result.status),
            _json_dumps(result),
            first_error.code if first_error else None,
            first_error.message if first_error else None,
            operation_id,
        ),
    )


def _operation_status(status: str) -> str:
    if status in {"success", "partial_success", "skipped"}:
        return status
    return "failed"


def _write_plan_event(
    conn: sqlite3.Connection,
    result: ServiceResult[GenerateTradePlanResult],
    ctx: RequestContext,
    event_type: str,
) -> None:
    if result.data is None or result.data.trade_plan_id is None:
        return
    if result.data.idempotent:
        return
    payload = {
        "trade_plan_id": result.data.trade_plan_id,
        "action": result.data.action,
        "status": result.data.status,
        "reason": result.data.reason,
    }
    account_id = _trade_plan_account_id(conn, result.data.trade_plan_id)
    _write_domain_event(
        conn,
        event_type,
        "trade_plan",
        result.data.trade_plan_id,
        account_id,
        payload,
        ctx,
    )


def _trade_plan_account_id(conn: sqlite3.Connection, trade_plan_id: int) -> int | None:
    row = conn.execute("SELECT account_id FROM trade_plans WHERE id = ?", (trade_plan_id,)).fetchone()
    return None if row is None else int(row["account_id"])


def _write_domain_event(
    conn: sqlite3.Connection,
    event_type: str,
    entity_type: str,
    entity_id: int,
    account_id: int | None,
    payload: dict[str, Any],
    ctx: RequestContext,
) -> None:
    conn.execute(
        """
        INSERT INTO domain_events
          (event_type, entity_type, entity_id, account_id, payload_json, source, operator)
        VALUES
          (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            entity_type,
            entity_id,
            account_id,
            _json_dumps(payload),
            _domain_event_source(ctx.source),
            ctx.operator,
        ),
    )


def _domain_event_source(source: str) -> str:
    if source in {"manual", "scheduler", "broker_import", "migration"}:
        return source
    return "system"


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


def _loads_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    payload = json.loads(value)
    return payload if isinstance(payload, dict) else {}


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)
