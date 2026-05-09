"""Read-only opening execution decision service."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pgc_trading.config import Paths
from pgc_trading.market.calendar import is_yyyymmdd
from pgc_trading.portfolio.state_machines import BUY_PLAN_ACTION, SELL_PLAN_ACTIONS, OPEN_POSITION_STATUSES
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult, ServiceWarning
from pgc_trading.services.portfolio_planning_service import _resolve_account
from pgc_trading.storage.database import connect
from pgc_trading.storage.invariant_checks import check_connection


@dataclass(frozen=True)
class OpenExecutionRequest:
    as_of_date: str
    account_key: str | None = "paper-main"
    account_id: int | None = None


@dataclass(frozen=True)
class MarketPlanContextSummary:
    market_plan_context_id: int
    market_review_run_id: int
    market_review_date: str
    trade_plan_id: int
    alignment: str
    risk_level: str
    management_action: str
    rationale: str
    created_at: str | None = None


@dataclass(frozen=True)
class OpenExecutionResult:
    as_of_date: str
    account_key: str
    status: str
    next_action: str
    blocked_reasons: list[str]
    primary_plan_id: int | None
    primary_position_id: int | None
    target_stock: str | None
    target_name: str | None
    planned_trade_date: str | None
    planned_shares: int | None
    operator_required: bool
    market_plan_context: MarketPlanContextSummary | None = None


class OpenExecutionService:
    """Summarize the next opening action without mutating trading state."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def get_open_execution(
        self,
        request: OpenExecutionRequest,
        ctx: RequestContext,
    ) -> ServiceResult[OpenExecutionResult]:
        errors = _validate_request(request)
        if errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_result(request, status="blocked", next_action="blocked", blocked_reasons=[]),
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
                    data=_empty_result(request, status="blocked", next_action="blocked", blocked_reasons=[]),
                    errors=[account],
                )

            invariant_report = check_connection(conn, db_path=self.db_path)
            if not invariant_report.ok:
                blocked_reasons = [violation.message for violation in invariant_report.violations]
                result = OpenExecutionResult(
                    as_of_date=request.as_of_date,
                    account_key=account.account_key,
                    status="blocked",
                    next_action="blocked",
                    blocked_reasons=blocked_reasons,
                    primary_plan_id=None,
                    primary_position_id=None,
                    target_stock=None,
                    target_name=None,
                    planned_trade_date=None,
                    planned_shares=None,
                    operator_required=False,
                    market_plan_context=None,
                )
                return ServiceResult(
                    status="blocked",
                    request_id=ctx.request_id,
                    data=result,
                    errors=[
                        ServiceError(code=violation.code, message=violation.message, severity=violation.severity)
                        for violation in invariant_report.violations
                    ],
                    lineage={"account_id": account.id, "as_of_date": request.as_of_date},
                )

            result = _build_open_execution_result(conn, request, account)

        warnings = _market_context_warnings(result.market_plan_context)
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=result,
            warnings=warnings,
            lineage={"account_id": account.id, "as_of_date": request.as_of_date},
        )


def _validate_request(request: OpenExecutionRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not is_yyyymmdd(request.as_of_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="as_of_date must use YYYYMMDD format."))
    if request.account_id is None and not request.account_key:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="account_key or account_id is required."))
    if request.account_id is not None and request.account_id <= 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="account_id must be positive."))
    if request.account_key is not None and not request.account_key.strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="account_key cannot be blank when provided."))
    return errors


def _empty_result(
    request: OpenExecutionRequest,
    *,
    status: str,
    next_action: str,
    blocked_reasons: list[str],
) -> OpenExecutionResult:
    return OpenExecutionResult(
        as_of_date=request.as_of_date,
        account_key=request.account_key or "",
        status=status,
        next_action=next_action,
        blocked_reasons=blocked_reasons,
        primary_plan_id=None,
        primary_position_id=None,
        target_stock=None,
        target_name=None,
        planned_trade_date=None,
        planned_shares=None,
        operator_required=False,
        market_plan_context=None,
    )


def _build_open_execution_result(
    conn: sqlite3.Connection,
    request: OpenExecutionRequest,
    account: Any,
) -> OpenExecutionResult:
    sell_plan = _load_due_active_plan(conn, account.id, request.as_of_date, SELL_PLAN_ACTIONS)
    if sell_plan is not None:
        return _result_from_plan(
            request,
            account.account_key,
            sell_plan,
            status="ready",
            next_action="record_sell",
        )

    buy_plan = _load_due_active_plan(conn, account.id, request.as_of_date, {BUY_PLAN_ACTION})
    if buy_plan is not None:
        return _result_from_plan(
            request,
            account.account_key,
            buy_plan,
            status="ready",
            next_action="record_buy",
            market_plan_context=_load_market_plan_context(conn, int(buy_plan["id"])),
        )

    due_position = _load_due_position(conn, account.id, request.as_of_date)
    if due_position is not None:
        return _result_from_position(
            request,
            account.account_key,
            due_position,
            status="ready",
            next_action="evaluate_exit",
        )

    future_plan = _load_future_active_plan(conn, account.id, request.as_of_date)
    if future_plan is not None:
        return _result_from_plan(
            request,
            account.account_key,
            future_plan,
            status="waiting",
            next_action="wait",
            market_plan_context=_load_market_plan_context(conn, int(future_plan["id"]))
            if future_plan["action"] == BUY_PLAN_ACTION
            else None,
        )

    return OpenExecutionResult(
        as_of_date=request.as_of_date,
        account_key=account.account_key,
        status="idle",
        next_action="none",
        blocked_reasons=[],
        primary_plan_id=None,
        primary_position_id=None,
        target_stock=None,
        target_name=None,
        planned_trade_date=None,
        planned_shares=None,
        operator_required=False,
        market_plan_context=None,
    )


def _load_due_active_plan(
    conn: sqlite3.Connection,
    account_id: int,
    as_of_date: str,
    actions: set[str],
) -> sqlite3.Row | None:
    placeholders = ", ".join("?" for _ in actions)
    return conn.execute(
        f"""
        SELECT *
        FROM trade_plans
        WHERE account_id = ?
          AND status = 'active'
          AND action IN ({placeholders})
          AND planned_trade_date = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        (account_id, *sorted(actions), as_of_date),
    ).fetchone()


def _load_future_active_plan(conn: sqlite3.Connection, account_id: int, as_of_date: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM trade_plans
        WHERE account_id = ?
          AND status = 'active'
          AND planned_trade_date > ?
        ORDER BY planned_trade_date ASC, id ASC
        LIMIT 1
        """,
        (account_id, as_of_date),
    ).fetchone()


def _load_due_position(conn: sqlite3.Connection, account_id: int, as_of_date: str) -> sqlite3.Row | None:
    return conn.execute(
        f"""
        SELECT *
        FROM positions
        WHERE account_id = ?
          AND status IN ({_status_placeholders()})
          AND (
            (
              status IN ('open', 'waiting_t2', 'need_t2_decision')
              AND planned_t2_date IS NOT NULL
              AND planned_t2_date <= ?
            )
            OR (
              status IN ('holding_to_t5', 'need_t5_exit')
              AND planned_t5_date IS NOT NULL
              AND planned_t5_date <= ?
            )
          )
        ORDER BY
          CASE
            WHEN status IN ('need_t5_exit', 'holding_to_t5') THEN 0
            ELSE 1
          END,
          id ASC
        LIMIT 1
        """,
        (account_id, *_open_status_tuple(), as_of_date, as_of_date),
    ).fetchone()


def _result_from_plan(
    request: OpenExecutionRequest,
    account_key: str,
    row: sqlite3.Row,
    *,
    status: str,
    next_action: str,
    market_plan_context: MarketPlanContextSummary | None = None,
) -> OpenExecutionResult:
    payload = _loads_json_object(row["plan_json"])
    position_id = _optional_int(payload.get("position_id"))
    shares = payload.get("planned_shares", payload.get("shares"))
    return OpenExecutionResult(
        as_of_date=request.as_of_date,
        account_key=account_key,
        status=status,
        next_action=next_action,
        blocked_reasons=[],
        primary_plan_id=int(row["id"]),
        primary_position_id=position_id,
        target_stock=_optional_text(payload.get("ts_code")),
        target_name=_optional_text(payload.get("name")),
        planned_trade_date=row["planned_trade_date"],
        planned_shares=_optional_int(shares),
        operator_required=next_action in {"record_buy", "record_sell"},
        market_plan_context=market_plan_context,
    )


def _result_from_position(
    request: OpenExecutionRequest,
    account_key: str,
    row: sqlite3.Row,
    *,
    status: str,
    next_action: str,
) -> OpenExecutionResult:
    return OpenExecutionResult(
        as_of_date=request.as_of_date,
        account_key=account_key,
        status=status,
        next_action=next_action,
        blocked_reasons=[],
        primary_plan_id=None,
        primary_position_id=int(row["id"]),
        target_stock=row["ts_code"],
        target_name=row["name"],
        planned_trade_date=request.as_of_date,
        planned_shares=int(row["shares"]),
        operator_required=next_action == "evaluate_exit",
        market_plan_context=None,
    )


def _load_market_plan_context(conn: sqlite3.Connection, trade_plan_id: int) -> MarketPlanContextSummary | None:
    row = conn.execute(
        """
        SELECT
          mpc.id,
          mpc.market_review_run_id,
          mrr.as_of_date AS market_review_date,
          mpc.trade_plan_id,
          mpc.alignment,
          mpc.risk_level,
          mpc.management_action,
          mpc.rationale,
          mpc.created_at
        FROM market_plan_contexts mpc
        JOIN market_review_runs mrr ON mrr.id = mpc.market_review_run_id
        WHERE mpc.trade_plan_id = ?
        ORDER BY mrr.as_of_date DESC, mpc.id DESC
        LIMIT 1
        """,
        (trade_plan_id,),
    ).fetchone()
    if row is None:
        return None
    return MarketPlanContextSummary(
        market_plan_context_id=int(row["id"]),
        market_review_run_id=int(row["market_review_run_id"]),
        market_review_date=row["market_review_date"],
        trade_plan_id=int(row["trade_plan_id"]),
        alignment=row["alignment"],
        risk_level=row["risk_level"],
        management_action=row["management_action"],
        rationale=row["rationale"],
        created_at=row["created_at"],
    )


def _market_context_warnings(context: MarketPlanContextSummary | None) -> list[ServiceWarning]:
    if context is None or context.management_action != "consider_cancel":
        return []
    return [
        ServiceWarning(
            code="MARKET_PLAN_CONTEXT_CONSIDER_CANCEL",
            message="Market-plan context recommends considering cancellation; no automatic cancel was performed.",
            entity_type="trade_plan",
            entity_id=context.trade_plan_id,
        )
    ]


def _loads_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _status_placeholders() -> str:
    return ", ".join("?" for _ in OPEN_POSITION_STATUSES)


def _open_status_tuple() -> tuple[str, ...]:
    return tuple(sorted(OPEN_POSITION_STATUSES))
