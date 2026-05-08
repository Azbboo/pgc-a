"""Position lifecycle and exit-decision service."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any

from pgc_trading.config import Paths
from pgc_trading.market.calendar import is_yyyymmdd
from pgc_trading.portfolio.state_machines import OPEN_POSITION_STATUSES
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult
from pgc_trading.services.portfolio_planning_service import (
    GenerateSellPlanRequest,
    _domain_event_source,
    _generate_sell_plan_in_tx,
    _resolve_account,
)
from pgc_trading.storage.database import connect


TAKE_PROFIT_T2 = 0.03
STOP_LOSS_T2 = -0.03


@dataclass(frozen=True)
class EvaluateExitsRequest:
    as_of_date: str
    account_key: str | None = None
    account_id: int | None = None
    generate_sell_plans: bool = True


@dataclass(frozen=True)
class ListPositionsRequest:
    as_of_date: str
    account_key: str | None = None
    account_id: int | None = None


@dataclass(frozen=True)
class PositionDTO:
    position_id: int
    account_id: int
    account_key: str
    ts_code: str
    name: str
    buy_date: str
    buy_price: float
    shares: int
    cost: float
    planned_t2_date: str | None
    planned_t5_date: str | None
    status: str
    due_stage: str | None
    latest_trade_date: str | None
    latest_close: float | None
    unrealized_ret: float | None


@dataclass(frozen=True)
class ListPositionsResult:
    as_of_date: str
    positions: list[PositionDTO]


@dataclass(frozen=True)
class SkippedPositionDTO:
    position_id: int
    reason: str


@dataclass(frozen=True)
class ExitDecisionDTO:
    exit_decision_id: int
    position_id: int
    account_id: int
    account_key: str
    ts_code: str
    name: str
    decision_date: str
    decision_stage: str
    decision: str
    ret: float | None
    reason: str
    planned_t2_date: str | None
    planned_t5_date: str | None
    planned_exit_date: str | None
    generated_trade_plan_id: int | None


@dataclass(frozen=True)
class EvaluateExitsResult:
    evaluated_positions: int
    exit_decision_ids: list[int]
    generated_trade_plan_ids: list[int]
    skipped_positions: list[SkippedPositionDTO]
    exit_decisions: list[ExitDecisionDTO] = field(default_factory=list)


@dataclass(frozen=True)
class MarkPositionsDueRequest:
    as_of_date: str
    account_key: str | None = None
    account_id: int | None = None


@dataclass(frozen=True)
class MarkPositionsDueResult:
    marked_t2: int
    marked_t5: int


class PositionLifecycleService:
    """Evaluate open positions against T+2/T+5 exit rules."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def list_positions(
        self,
        request: ListPositionsRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ListPositionsResult]:
        if not is_yyyymmdd(request.as_of_date):
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=ListPositionsResult(as_of_date=request.as_of_date, positions=[]),
                errors=[ServiceError(code="VALIDATION_ERROR", message="as_of_date must use YYYYMMDD format.")],
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
                    data=ListPositionsResult(as_of_date=request.as_of_date, positions=[]),
                    errors=[account],
                )
            positions = [
                _position_dto(row, account.account_key, request.as_of_date)
                for row in _load_positions_for_review(conn, account.id, request.as_of_date)
            ]
            return ServiceResult(
                status="success",
                request_id=ctx.request_id,
                data=ListPositionsResult(as_of_date=request.as_of_date, positions=positions),
                lineage={"account_id": account.id, "as_of_date": request.as_of_date},
            )

    def evaluate_exits(
        self,
        request: EvaluateExitsRequest,
        ctx: RequestContext,
    ) -> ServiceResult[EvaluateExitsResult]:
        errors = _validate_evaluate_request(request)
        if errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_evaluate_result(),
                errors=errors,
            )

        with connect(self.db_path) as conn:
            if ctx.dry_run:
                return _evaluate_exits_in_tx(conn, request, ctx, write=False)

            conn.execute("BEGIN")
            try:
                operation_id = _reserve_operation(conn, "position_exit_evaluate", request, ctx)
                result = _evaluate_exits_in_tx(conn, request, ctx, write=True)
                _write_lifecycle_event(conn, result, ctx)
                _finish_operation(conn, operation_id, result)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def mark_positions_due(
        self,
        request: MarkPositionsDueRequest,
        ctx: RequestContext,
    ) -> ServiceResult[MarkPositionsDueResult]:
        if not is_yyyymmdd(request.as_of_date):
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=MarkPositionsDueResult(marked_t2=0, marked_t5=0),
                errors=[ServiceError(code="VALIDATION_ERROR", message="as_of_date must use YYYYMMDD format.")],
            )
        with connect(self.db_path) as conn:
            account = _resolve_account(
                conn,
                request.account_key,
                request.account_id,
                allow_live_dry_run=ctx.dry_run,
                allow_live_writes=ctx.allow_live_writes,
                live_block_code="LIVE_EXIT_EVALUATION_DISABLED",
                live_block_message="Live exit evaluation writes require explicit live write enablement.",
            )
            if isinstance(account, ServiceError):
                return ServiceResult(
                    status="validation_failed",
                    request_id=ctx.request_id,
                    data=MarkPositionsDueResult(marked_t2=0, marked_t5=0),
                    errors=[account],
                )
            conn.execute("BEGIN")
            try:
                marked_t2 = conn.execute(
                    """
                    UPDATE positions
                    SET status = 'need_t2_decision'
                    WHERE account_id = ?
                      AND status = 'waiting_t2'
                      AND planned_t2_date <= ?
                    """,
                    (account.id, request.as_of_date),
                ).rowcount
                marked_t5 = conn.execute(
                    """
                    UPDATE positions
                    SET status = 'need_t5_exit'
                    WHERE account_id = ?
                      AND status = 'holding_to_t5'
                      AND planned_t5_date <= ?
                    """,
                    (account.id, request.as_of_date),
                ).rowcount
                conn.commit()
                return ServiceResult(
                    status="success",
                    request_id=ctx.request_id,
                    data=MarkPositionsDueResult(marked_t2=marked_t2, marked_t5=marked_t5),
                )
            except Exception:
                conn.rollback()
                raise


def _evaluate_exits_in_tx(
    conn: sqlite3.Connection,
    request: EvaluateExitsRequest,
    ctx: RequestContext,
    *,
    write: bool,
) -> ServiceResult[EvaluateExitsResult]:
    account = _resolve_account(
        conn,
        request.account_key,
        request.account_id,
        allow_live_dry_run=ctx.dry_run,
        allow_live_writes=ctx.allow_live_writes,
        live_block_code="LIVE_EXIT_EVALUATION_DISABLED",
        live_block_message="Live exit evaluation writes require explicit live write enablement.",
    )
    if isinstance(account, ServiceError):
        return ServiceResult(
            status="validation_failed",
            request_id=ctx.request_id,
            data=_empty_evaluate_result(),
            errors=[account],
        )

    exit_decision_ids: list[int] = []
    generated_trade_plan_ids: list[int] = []
    skipped: list[SkippedPositionDTO] = []
    positions = _load_open_positions(conn, account.id)

    for position in positions:
        stage = _due_stage(position, request.as_of_date)
        if stage is None:
            skipped.append(SkippedPositionDTO(position_id=int(position["id"]), reason="not_due"))
            continue

        existing = _existing_exit_decision(conn, int(position["id"]), stage, request.as_of_date)
        if existing is not None:
            exit_decision_ids.append(int(existing["id"]))
            plan_id = existing["generated_trade_plan_id"]
            if plan_id is not None:
                generated_trade_plan_ids.append(int(plan_id))
            elif request.generate_sell_plans and existing["decision"] in {"take_profit", "stop_loss", "timeout_exit"}:
                plan_id = _ensure_sell_plan_for_decision(conn, account.id, existing, ctx, write=write)
                if plan_id is not None:
                    generated_trade_plan_ids.append(plan_id)
            continue

        close_price = _close_on_date(conn, position["ts_code"], request.as_of_date)
        if close_price is None:
            skipped.append(SkippedPositionDTO(position_id=int(position["id"]), reason="missing_market_bar"))
            continue

        exit_eval = _build_exit_evaluation(position, stage, request.as_of_date, close_price)
        if exit_eval["needs_sell_plan"]:
            planned_exit_date = _next_open_date(conn, request.as_of_date)
            if planned_exit_date is None:
                skipped.append(SkippedPositionDTO(position_id=int(position["id"]), reason="missing_exit_trade_date"))
                continue
            exit_eval["planned_exit_date"] = planned_exit_date

        decision_id = None
        if write:
            decision_id = _insert_exit_decision(conn, account.id, position, exit_eval, ctx)
            exit_decision_ids.append(decision_id)
            _update_position_after_decision(conn, int(position["id"]), exit_eval)
            if exit_eval["needs_sell_plan"] and request.generate_sell_plans:
                plan_id = _ensure_sell_plan_for_decision_by_id(
                    conn,
                    account.id,
                    decision_id,
                    exit_eval,
                    ctx,
                    write=True,
                )
                if plan_id is not None:
                    generated_trade_plan_ids.append(plan_id)
        else:
            exit_decision_ids.append(-1)

    decision_details = _load_exit_decision_details(
        conn,
        [decision_id for decision_id in exit_decision_ids if decision_id > 0],
    )

    return ServiceResult(
        status="success",
        request_id=ctx.request_id,
        data=EvaluateExitsResult(
            evaluated_positions=len(positions) - len([item for item in skipped if item.reason == "not_due"]),
            exit_decision_ids=exit_decision_ids,
            generated_trade_plan_ids=generated_trade_plan_ids,
            skipped_positions=skipped,
            exit_decisions=decision_details,
        ),
        created_ids={
            "exit_decision_ids": exit_decision_ids,
            "generated_trade_plan_ids": generated_trade_plan_ids,
        },
        lineage={"account_id": account.id, "as_of_date": request.as_of_date},
    )


def _validate_evaluate_request(request: EvaluateExitsRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not is_yyyymmdd(request.as_of_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="as_of_date must use YYYYMMDD format."))
    return errors


def _load_open_positions(conn: sqlite3.Connection, account_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        f"""
        SELECT *
        FROM positions
        WHERE account_id = ?
          AND status IN ({_status_placeholders()})
        ORDER BY id
        """,
        (account_id, *_open_status_tuple()),
    ).fetchall()


def _load_positions_for_review(
    conn: sqlite3.Connection,
    account_id: int,
    as_of_date: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        f"""
        SELECT
          p.*,
          mb.trade_date AS latest_trade_date,
          COALESCE(NULLIF(mb.adj_close, 0), mb.close) AS latest_close
        FROM positions p
        LEFT JOIN market_bars mb
          ON mb.ts_code = p.ts_code
         AND mb.trade_date = (
            SELECT MAX(mb2.trade_date)
            FROM market_bars mb2
            WHERE mb2.ts_code = p.ts_code
              AND mb2.trade_date <= ?
         )
        WHERE p.account_id = ?
          AND p.status IN ({_status_placeholders()})
        ORDER BY p.id
        """,
        (as_of_date, account_id, *_open_status_tuple()),
    ).fetchall()


def _position_dto(row: sqlite3.Row, account_key: str, as_of_date: str) -> PositionDTO:
    latest_close = row["latest_close"]
    unrealized_ret = None
    if latest_close is not None:
        unrealized_ret = (float(latest_close) - float(row["buy_price"])) / float(row["buy_price"])
    return PositionDTO(
        position_id=int(row["id"]),
        account_id=int(row["account_id"]),
        account_key=account_key,
        ts_code=row["ts_code"],
        name=row["name"],
        buy_date=row["buy_date"],
        buy_price=float(row["buy_price"]),
        shares=int(row["shares"]),
        cost=float(row["cost"]),
        planned_t2_date=row["planned_t2_date"],
        planned_t5_date=row["planned_t5_date"],
        status=row["status"],
        due_stage=_display_due_stage(row, as_of_date),
        latest_trade_date=row["latest_trade_date"],
        latest_close=float(latest_close) if latest_close is not None else None,
        unrealized_ret=unrealized_ret,
    )


def _display_due_stage(position: sqlite3.Row, as_of_date: str) -> str | None:
    stage = _due_stage(position, as_of_date)
    if stage is not None:
        return stage
    if position["status"] == "planned_exit":
        return "exit_planned"
    return None


def _due_stage(position: sqlite3.Row, as_of_date: str) -> str | None:
    status = position["status"]
    planned_t2_date = position["planned_t2_date"]
    planned_t5_date = position["planned_t5_date"]
    if status in {"waiting_t2", "need_t2_decision", "open"}:
        if planned_t2_date is not None and as_of_date >= planned_t2_date:
            return "t2"
        return None
    if status in {"holding_to_t5", "need_t5_exit"}:
        if planned_t5_date is not None and as_of_date >= planned_t5_date:
            return "t5"
        return None
    return None


def _existing_exit_decision(
    conn: sqlite3.Connection,
    position_id: int,
    stage: str,
    decision_date: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM exit_decisions
        WHERE position_id = ?
          AND decision_stage = ?
          AND decision_date = ?
          AND decision <> 'executed'
        ORDER BY id DESC
        LIMIT 1
        """,
        (position_id, stage, decision_date),
    ).fetchone()


def _close_on_date(conn: sqlite3.Connection, ts_code: str, trade_date: str) -> float | None:
    row = conn.execute(
        """
        SELECT COALESCE(NULLIF(adj_close, 0), close) AS close_price
        FROM market_bars
        WHERE ts_code = ?
          AND trade_date = ?
        """,
        (ts_code, trade_date),
    ).fetchone()
    if row is None or row["close_price"] is None:
        return None
    return float(row["close_price"])


def _build_exit_evaluation(
    position: sqlite3.Row,
    stage: str,
    decision_date: str,
    close_price: float,
) -> dict[str, Any]:
    ret = (close_price - float(position["buy_price"])) / float(position["buy_price"])
    if stage == "t5":
        return {
            "decision_stage": "t5",
            "decision": "timeout_exit",
            "reason": "timeout_t5",
            "ret": ret,
            "decision_date": decision_date,
            "planned_exit_date": None,
            "position_status": "planned_exit",
            "action": "sell_t5_timeout",
            "needs_sell_plan": True,
        }
    if ret >= TAKE_PROFIT_T2:
        return {
            "decision_stage": "t2",
            "decision": "take_profit",
            "reason": "take_profit_ge3",
            "ret": ret,
            "decision_date": decision_date,
            "planned_exit_date": None,
            "position_status": "planned_exit",
            "action": "sell_t2_take_profit",
            "needs_sell_plan": True,
        }
    if ret <= STOP_LOSS_T2:
        return {
            "decision_stage": "t2",
            "decision": "stop_loss",
            "reason": "stop_loss_le_neg3",
            "ret": ret,
            "decision_date": decision_date,
            "planned_exit_date": None,
            "position_status": "planned_exit",
            "action": "sell_t2_stop_loss",
            "needs_sell_plan": True,
        }
    return {
        "decision_stage": "t2",
        "decision": "hold_to_t5",
        "reason": "hold_middle_to_t5",
        "ret": ret,
        "decision_date": decision_date,
        "planned_exit_date": None,
        "position_status": "holding_to_t5",
        "action": None,
        "needs_sell_plan": False,
    }


def _insert_exit_decision(
    conn: sqlite3.Connection,
    account_id: int,
    position: sqlite3.Row,
    exit_eval: dict[str, Any],
    ctx: RequestContext,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO exit_decisions
          (
            position_id,
            account_id,
            decision_date,
            decision_stage,
            decision,
            ret,
            reason,
            planned_exit_date,
            operator
          )
        VALUES
          (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(position["id"]),
            account_id,
            exit_eval["decision_date"],
            exit_eval["decision_stage"],
            exit_eval["decision"],
            exit_eval["ret"],
            exit_eval["reason"],
            exit_eval["planned_exit_date"],
            ctx.operator,
        ),
    )
    decision_id = int(cursor.lastrowid)
    conn.execute(
        """
        INSERT INTO domain_events
          (event_type, entity_type, entity_id, account_id, payload_json, source, operator)
        VALUES
          ('exit_decision_created', 'exit_decision', ?, ?, ?, ?, ?)
        """,
        (
            decision_id,
            account_id,
            _json_dumps(
                {
                    "position_id": int(position["id"]),
                    "decision": exit_eval["decision"],
                    "reason": exit_eval["reason"],
                    "ret": exit_eval["ret"],
                }
            ),
            _domain_event_source(ctx.source),
            ctx.operator,
        ),
    )
    return decision_id


def _update_position_after_decision(
    conn: sqlite3.Connection,
    position_id: int,
    exit_eval: dict[str, Any],
) -> None:
    conn.execute(
        """
        UPDATE positions
        SET status = ?
        WHERE id = ?
        """,
        (exit_eval["position_status"], position_id),
    )


def _ensure_sell_plan_for_decision_by_id(
    conn: sqlite3.Connection,
    account_id: int,
    exit_decision_id: int,
    exit_eval: dict[str, Any],
    ctx: RequestContext,
    *,
    write: bool,
) -> int | None:
    decision = conn.execute("SELECT * FROM exit_decisions WHERE id = ?", (exit_decision_id,)).fetchone()
    if decision is None:
        return None
    return _ensure_sell_plan_for_decision(conn, account_id, decision, ctx, write=write, exit_eval=exit_eval)


def _ensure_sell_plan_for_decision(
    conn: sqlite3.Connection,
    account_id: int,
    decision: sqlite3.Row,
    ctx: RequestContext,
    *,
    write: bool,
    exit_eval: dict[str, Any] | None = None,
) -> int | None:
    action = _action_for_decision(decision["decision"])
    if action is None:
        return None
    result = _generate_sell_plan_in_tx(
        conn,
        GenerateSellPlanRequest(
            account_id=account_id,
            exit_decision_id=int(decision["id"]),
            decision_date=decision["decision_date"],
            action=action,
            planned_trade_date=decision["planned_exit_date"],
            reason=decision["reason"],
        ),
        ctx,
        write=write,
    )
    if result.data is None:
        return None
    if result.status != "success":
        return None
    return result.data.trade_plan_id


def _load_exit_decision_details(
    conn: sqlite3.Connection,
    exit_decision_ids: list[int],
) -> list[ExitDecisionDTO]:
    if not exit_decision_ids:
        return []
    placeholders = ", ".join("?" for _ in exit_decision_ids)
    rows = conn.execute(
        f"""
        SELECT
          ed.id AS exit_decision_id,
          ed.position_id,
          ed.account_id,
          pa.account_key,
          p.ts_code,
          p.name,
          ed.decision_date,
          ed.decision_stage,
          ed.decision,
          ed.ret,
          ed.reason,
          p.planned_t2_date,
          p.planned_t5_date,
          ed.planned_exit_date,
          ed.generated_trade_plan_id
        FROM exit_decisions ed
        JOIN positions p ON p.id = ed.position_id
        JOIN portfolio_accounts pa ON pa.id = ed.account_id
        WHERE ed.id IN ({placeholders})
        """,
        tuple(exit_decision_ids),
    ).fetchall()
    by_id = {int(row["exit_decision_id"]): row for row in rows}
    details: list[ExitDecisionDTO] = []
    for exit_decision_id in exit_decision_ids:
        row = by_id.get(exit_decision_id)
        if row is None:
            continue
        details.append(
            ExitDecisionDTO(
                exit_decision_id=int(row["exit_decision_id"]),
                position_id=int(row["position_id"]),
                account_id=int(row["account_id"]),
                account_key=row["account_key"],
                ts_code=row["ts_code"],
                name=row["name"],
                decision_date=row["decision_date"],
                decision_stage=row["decision_stage"],
                decision=row["decision"],
                ret=float(row["ret"]) if row["ret"] is not None else None,
                reason=row["reason"],
                planned_t2_date=row["planned_t2_date"],
                planned_t5_date=row["planned_t5_date"],
                planned_exit_date=row["planned_exit_date"],
                generated_trade_plan_id=(
                    int(row["generated_trade_plan_id"])
                    if row["generated_trade_plan_id"] is not None
                    else None
                ),
            )
        )
    return details


def _action_for_decision(decision: str) -> str | None:
    if decision == "take_profit":
        return "sell_t2_take_profit"
    if decision == "stop_loss":
        return "sell_t2_stop_loss"
    if decision == "timeout_exit":
        return "sell_t5_timeout"
    return None


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


def _status_placeholders() -> str:
    return ", ".join("?" for _ in OPEN_POSITION_STATUSES)


def _open_status_tuple() -> tuple[str, ...]:
    return tuple(sorted(OPEN_POSITION_STATUSES))


def _empty_evaluate_result() -> EvaluateExitsResult:
    return EvaluateExitsResult(
        evaluated_positions=0,
        exit_decision_ids=[],
        generated_trade_plan_ids=[],
        skipped_positions=[],
    )


def _reserve_operation(
    conn: sqlite3.Connection,
    operation_type: str,
    request: EvaluateExitsRequest,
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
            (
                ctx.request_id,
                operation_type,
                request.account_id,
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
          (?, ?, ?, ?, ?, 'started', ?, ?)
        """,
        (
            ctx.idempotency_key,
            ctx.request_id,
            operation_type,
            request.account_id,
            request.as_of_date,
            request_json,
            ctx.operator,
        ),
    )
    return int(cursor.lastrowid)


def _finish_operation(
    conn: sqlite3.Connection,
    operation_id: int | None,
    result: ServiceResult[EvaluateExitsResult],
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


def _write_lifecycle_event(
    conn: sqlite3.Connection,
    result: ServiceResult[EvaluateExitsResult],
    ctx: RequestContext,
) -> None:
    if result.data is None or not result.data.exit_decision_ids:
        return
    first_decision_id = next((item for item in result.data.exit_decision_ids if item > 0), None)
    if first_decision_id is None:
        return
    conn.execute(
        """
        INSERT INTO domain_events
          (event_type, entity_type, entity_id, account_id, payload_json, source, operator)
        VALUES
          ('position_exits_evaluated', 'exit_decision', ?, ?, ?, ?, ?)
        """,
        (
            first_decision_id,
            result.lineage.get("account_id"),
            _json_dumps(
                {
                    "exit_decision_ids": result.data.exit_decision_ids,
                    "generated_trade_plan_ids": result.data.generated_trade_plan_ids,
                    "skipped_positions": result.data.skipped_positions,
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
