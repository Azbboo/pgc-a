"""Advisory action logs for the next-day decision cockpit."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pgc_trading.config import Paths
from pgc_trading.market.calendar import is_yyyymmdd
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult
from pgc_trading.services.daily_close_workflow_service import DEFAULT_ACCOUNT_KEY
from pgc_trading.services.portfolio_planning_service import _resolve_account
from pgc_trading.storage.database import connect


OPERATOR_DECISIONS = frozenset({"followed", "deferred", "overrode"})
COCKPIT_STATUSES = frozenset({"ready", "review_required", "blocked", "unknown"})
TARGET_TYPES = frozenset(
    {"trade_plan", "position", "strategy_proposal", "paper_acceptance", "market_review", "quality", "none", "other"}
)
TRADE_ACTIONS = frozenset({"record_buy", "record_sell"})


@dataclass(frozen=True)
class CreateDecisionActionLogRequest:
    review_date: str
    account_key: str | None = DEFAULT_ACCOUNT_KEY
    account_id: int | None = None
    execution_date: str | None = None
    cockpit_status: str = "unknown"
    system_action: str = "none"
    operator_decision: str = "deferred"
    operator_note: str = ""
    target_type: str = "none"
    target_id: int | None = None
    blocker_codes: list[str] = field(default_factory=list)
    warning_codes: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ListDecisionActionLogsRequest:
    review_date: str
    account_key: str | None = DEFAULT_ACCOUNT_KEY
    account_id: int | None = None
    limit: int = 20


@dataclass(frozen=True)
class DecisionActionOutcome:
    outcome_review_date: str | None
    outcome_status: str
    outcome_summary: str
    matched_trade_id: int | None = None
    matched_exit_decision_id: int | None = None


@dataclass(frozen=True)
class DecisionActionLogEntry:
    decision_action_log_id: int | None
    account_id: int | None
    account_key: str | None
    review_date: str
    execution_date: str | None
    cockpit_status: str
    system_action: str
    operator_decision: str
    operator_note: str
    target_type: str
    target_id: int | None
    blocker_codes: list[str] = field(default_factory=list)
    warning_codes: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    unresolved_blocker_codes: list[str] = field(default_factory=list)
    operator: str | None = None
    created_at: str | None = None
    outcome: DecisionActionOutcome | None = None
    would_write_action_log: bool = False
    wrote_action_log: bool = False
    writes_trade_state: bool = False
    writes_strategy_state: bool = False
    enables_timer: bool = False


@dataclass(frozen=True)
class DecisionActionLogList:
    account_id: int | None
    account_key: str | None
    review_date: str
    items: list[DecisionActionLogEntry]
    summary: str
    followed_count: int
    deferred_count: int
    override_count: int
    unresolved_blocker_codes: list[str] = field(default_factory=list)
    pending_outcome_count: int = 0
    advisory_note: str = (
        "Decision cockpit action logs are advisory audit records; they never execute trades, "
        "enable timers, or mutate strategy state."
    )


class DecisionActionLogService:
    """Record and review manual decisions made from the read-only cockpit."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def create_action_log(
        self,
        request: CreateDecisionActionLogRequest,
        ctx: RequestContext,
    ) -> ServiceResult[DecisionActionLogEntry]:
        errors = _validate_create_request(request)
        if not ctx.dry_run:
            if not ctx.operator:
                errors.append(ServiceError(code="VALIDATION_ERROR", message="operator is required for action log apply."))
            if not ctx.idempotency_key:
                errors.append(
                    ServiceError(code="VALIDATION_ERROR", message="idempotency_key is required for action log apply.")
                )
        if errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_preview_entry(request, None, None, ctx, would_write=not ctx.dry_run),
                errors=errors,
            )

        with connect(self.db_path) as conn:
            if not _table_exists(conn, "decision_action_logs"):
                return ServiceResult(
                    status="blocked",
                    request_id=ctx.request_id,
                    data=_preview_entry(request, None, None, ctx, would_write=not ctx.dry_run),
                    errors=[
                        ServiceError(
                            code="SCHEMA_MIGRATION_REQUIRED",
                            message="decision_action_logs table is missing; run migrations before applying action logs.",
                        )
                    ],
                )
            account = _resolve_account(
                conn,
                request.account_key,
                request.account_id,
                allow_live_dry_run=ctx.dry_run,
                allow_live_writes=ctx.allow_live_writes,
                live_block_code="LIVE_ACTION_LOG_APPLY_DISABLED",
                live_block_message="Live account action logs require explicit allow_live_writes approval.",
            )
            if isinstance(account, ServiceError):
                return ServiceResult(
                    status="validation_failed",
                    request_id=ctx.request_id,
                    data=_preview_entry(request, None, None, ctx, would_write=not ctx.dry_run),
                    errors=[account],
                )

            if ctx.dry_run:
                data = _preview_entry(request, account.id, account.account_key, ctx, would_write=True)
                return ServiceResult(
                    status="success",
                    request_id=ctx.request_id,
                    data=data,
                    lineage=_lineage(data),
                )

            operation_id = _reserve_operation(conn, request, ctx, account.id)
            assert operation_id is not None
            existing = conn.execute(
                """
                SELECT id
                FROM decision_action_logs
                WHERE operation_request_id = ?
                """,
                (operation_id,),
            ).fetchone()
            if existing is None:
                cursor = conn.execute(
                    """
                    INSERT INTO decision_action_logs
                      (
                        operation_request_id,
                        account_id,
                        review_date,
                        execution_date,
                        cockpit_status,
                        system_action,
                        operator_decision,
                        operator_note,
                        target_type,
                        target_id,
                        blocker_codes_json,
                        warning_codes_json,
                        source_refs_json,
                        operator
                      )
                    VALUES
                      (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        operation_id,
                        account.id,
                        request.review_date,
                        request.execution_date,
                        _normalized_cockpit_status(request.cockpit_status),
                        request.system_action,
                        request.operator_decision,
                        request.operator_note,
                        request.target_type,
                        request.target_id,
                        _json_dumps(_clean_string_list(request.blocker_codes)),
                        _json_dumps(_clean_string_list(request.warning_codes)),
                        _json_dumps(_clean_string_list(request.source_refs)),
                        ctx.operator,
                    ),
                )
                log_id = int(cursor.lastrowid)
            else:
                log_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE decision_action_logs
                    SET review_date = ?,
                        execution_date = ?,
                        cockpit_status = ?,
                        system_action = ?,
                        operator_decision = ?,
                        operator_note = ?,
                        target_type = ?,
                        target_id = ?,
                        blocker_codes_json = ?,
                        warning_codes_json = ?,
                        source_refs_json = ?,
                        operator = ?
                    WHERE id = ?
                    """,
                    (
                        request.review_date,
                        request.execution_date,
                        _normalized_cockpit_status(request.cockpit_status),
                        request.system_action,
                        request.operator_decision,
                        request.operator_note,
                        request.target_type,
                        request.target_id,
                        _json_dumps(_clean_string_list(request.blocker_codes)),
                        _json_dumps(_clean_string_list(request.warning_codes)),
                        _json_dumps(_clean_string_list(request.source_refs)),
                        ctx.operator,
                        log_id,
                    ),
                )

            conn.commit()
            entry = _load_entry(conn, log_id)
            _finish_operation(conn, operation_id, "success", entry)
            conn.commit()
            return ServiceResult(
                status="success",
                request_id=ctx.request_id,
                data=entry,
                created_ids={"decision_action_log_id": log_id},
                lineage=_lineage(entry),
            )

    def list_action_logs(
        self,
        request: ListDecisionActionLogsRequest,
        ctx: RequestContext | None = None,
    ) -> ServiceResult[DecisionActionLogList]:
        context = ctx or RequestContext(source="decision_action_log", dry_run=True)
        errors = _validate_list_request(request)
        if errors:
            return ServiceResult(
                status="validation_failed",
                request_id=context.request_id,
                data=_empty_list(request, None, None),
                errors=errors,
            )

        with connect(self.db_path) as conn:
            if not _table_exists(conn, "decision_action_logs"):
                data = _empty_list(request, None, request.account_key)
                return ServiceResult(
                    status="success",
                    request_id=context.request_id,
                    data=data,
                    warnings=[],
                    lineage={"review_date": request.review_date, "read_only": True},
                )
            account = _resolve_account(conn, request.account_key, request.account_id, allow_live_dry_run=True)
            if isinstance(account, ServiceError):
                return ServiceResult(
                    status="validation_failed",
                    request_id=context.request_id,
                    data=_empty_list(request, None, request.account_key),
                    errors=[account],
                )
            rows = conn.execute(
                """
                SELECT id
                FROM decision_action_logs
                WHERE account_id = ?
                  AND review_date = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (account.id, request.review_date, max(1, min(request.limit, 100))),
            ).fetchall()
            items = [_load_entry(conn, int(row["id"])) for row in rows]
            data = _build_list(account.id, account.account_key, request.review_date, items)
            return ServiceResult(
                status="success",
                request_id=context.request_id,
                data=data,
                lineage={
                    "account_id": account.id,
                    "account_key": account.account_key,
                    "review_date": request.review_date,
                    "action_log_count": len(items),
                    "read_only": True,
                },
            )


def _validate_create_request(request: CreateDecisionActionLogRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not is_yyyymmdd(request.review_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="review_date must use YYYYMMDD format."))
    if request.execution_date is not None and not is_yyyymmdd(request.execution_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="execution_date must use YYYYMMDD format."))
    if _normalized_cockpit_status(request.cockpit_status) not in COCKPIT_STATUSES:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="cockpit_status is invalid."))
    if not request.system_action.strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="system_action is required."))
    if request.operator_decision not in OPERATOR_DECISIONS:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="operator_decision is invalid."))
    if request.target_type not in TARGET_TYPES:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="target_type is invalid."))
    if request.target_id is not None and request.target_id <= 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="target_id must be positive when provided."))
    if request.operator_decision in {"deferred", "overrode"} and not request.operator_note.strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="operator_note is required for deferred/overrode."))
    return errors


def _validate_list_request(request: ListDecisionActionLogsRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not is_yyyymmdd(request.review_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="review_date must use YYYYMMDD format."))
    if request.limit <= 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="limit must be positive."))
    return errors


def _preview_entry(
    request: CreateDecisionActionLogRequest,
    account_id: int | None,
    account_key: str | None,
    ctx: RequestContext,
    *,
    would_write: bool,
) -> DecisionActionLogEntry:
    return DecisionActionLogEntry(
        decision_action_log_id=None,
        account_id=account_id,
        account_key=account_key or request.account_key,
        review_date=request.review_date,
        execution_date=request.execution_date,
        cockpit_status=_normalized_cockpit_status(request.cockpit_status),
        system_action=request.system_action,
        operator_decision=request.operator_decision,
        operator_note=request.operator_note,
        target_type=request.target_type,
        target_id=request.target_id,
        blocker_codes=_clean_string_list(request.blocker_codes),
        warning_codes=_clean_string_list(request.warning_codes),
        source_refs=_clean_string_list(request.source_refs),
        unresolved_blocker_codes=_clean_string_list(request.blocker_codes),
        operator=ctx.operator,
        outcome=DecisionActionOutcome(
            outcome_review_date=None,
            outcome_status="dry_run_preview" if ctx.dry_run else "not_written",
            outcome_summary="Preview only; no advisory action log was written.",
        ),
        would_write_action_log=would_write,
        wrote_action_log=False,
    )


def _load_entry(conn: sqlite3.Connection, log_id: int) -> DecisionActionLogEntry:
    row = conn.execute(
        """
        SELECT
          dal.id,
          dal.account_id,
          pa.account_key,
          dal.review_date,
          dal.execution_date,
          dal.cockpit_status,
          dal.system_action,
          dal.operator_decision,
          dal.operator_note,
          dal.target_type,
          dal.target_id,
          dal.blocker_codes_json,
          dal.warning_codes_json,
          dal.source_refs_json,
          dal.operator,
          dal.created_at
        FROM decision_action_logs dal
        JOIN portfolio_accounts pa ON pa.id = dal.account_id
        WHERE dal.id = ?
        """,
        (log_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"decision_action_log not found: {log_id}")
    blocker_codes = _loads_string_list(row["blocker_codes_json"])
    entry = DecisionActionLogEntry(
        decision_action_log_id=int(row["id"]),
        account_id=int(row["account_id"]),
        account_key=row["account_key"],
        review_date=row["review_date"],
        execution_date=row["execution_date"],
        cockpit_status=row["cockpit_status"],
        system_action=row["system_action"],
        operator_decision=row["operator_decision"],
        operator_note=row["operator_note"] or "",
        target_type=row["target_type"],
        target_id=None if row["target_id"] is None else int(row["target_id"]),
        blocker_codes=blocker_codes,
        warning_codes=_loads_string_list(row["warning_codes_json"]),
        source_refs=_loads_string_list(row["source_refs_json"]),
        unresolved_blocker_codes=blocker_codes,
        operator=row["operator"],
        created_at=row["created_at"],
        outcome=_compute_outcome(conn, row),
        would_write_action_log=False,
        wrote_action_log=True,
    )
    return entry


def _compute_outcome(conn: sqlite3.Connection, row: sqlite3.Row) -> DecisionActionOutcome:
    execution_date = row["execution_date"]
    outcome_review_date = _next_open_date(conn, execution_date or row["review_date"])
    operator_decision = str(row["operator_decision"])
    system_action = str(row["system_action"])
    account_id = int(row["account_id"])
    target_type = str(row["target_type"])
    target_id = None if row["target_id"] is None else int(row["target_id"])

    if operator_decision == "deferred":
        return DecisionActionOutcome(
            outcome_review_date=outcome_review_date,
            outcome_status="deferred",
            outcome_summary="Operator deferred the cockpit recommendation; no execution match is expected.",
        )

    if system_action in TRADE_ACTIONS:
        trade = _matching_trade(conn, account_id, target_type, target_id, system_action)
        if trade is not None:
            status = "matched" if operator_decision == "followed" else "override_executed"
            return DecisionActionOutcome(
                outcome_review_date=outcome_review_date,
                outcome_status=status,
                outcome_summary=(
                    f"Matched executed {trade['side']} trade {trade['id']} on {trade['executed_date']}; "
                    f"operator decision was {operator_decision}."
                ),
                matched_trade_id=int(trade["id"]),
            )
        return DecisionActionOutcome(
            outcome_review_date=outcome_review_date,
            outcome_status="pending_outcome" if operator_decision == "followed" else "override_recorded",
            outcome_summary="No matching executed trade has been recorded through guarded trade endpoints yet.",
        )

    if system_action == "evaluate_exit" and target_type == "position" and target_id is not None:
        exit_decision = _matching_exit_decision(conn, account_id, target_id, execution_date)
        if exit_decision is not None:
            return DecisionActionOutcome(
                outcome_review_date=outcome_review_date,
                outcome_status="matched" if operator_decision == "followed" else "override_reviewed",
                outcome_summary=(
                    f"Matched exit decision {exit_decision['id']} with decision={exit_decision['decision']}."
                ),
                matched_exit_decision_id=int(exit_decision["id"]),
            )
        return DecisionActionOutcome(
            outcome_review_date=outcome_review_date,
            outcome_status="pending_outcome",
            outcome_summary="No matching exit decision has been recorded yet.",
        )

    if system_action in {"wait", "none", "blocked"}:
        unexpected_trade = _trade_on_date(conn, account_id, execution_date)
        if unexpected_trade is not None:
            return DecisionActionOutcome(
                outcome_review_date=outcome_review_date,
                outcome_status="unexpected_trade_recorded",
                outcome_summary=(
                    f"System action was {system_action}, but trade {unexpected_trade['id']} "
                    f"was recorded on {unexpected_trade['executed_date']}."
                ),
                matched_trade_id=int(unexpected_trade["id"]),
            )
        return DecisionActionOutcome(
            outcome_review_date=outcome_review_date,
            outcome_status="matched" if operator_decision == "followed" else "override_recorded",
            outcome_summary=f"No guarded trade execution was recorded for system action {system_action}.",
        )

    return DecisionActionOutcome(
        outcome_review_date=outcome_review_date,
        outcome_status="review_only",
        outcome_summary=f"Recorded advisory operator decision for system action {system_action}.",
    )


def _matching_trade(
    conn: sqlite3.Connection,
    account_id: int,
    target_type: str,
    target_id: int | None,
    system_action: str,
) -> sqlite3.Row | None:
    side = "buy" if system_action == "record_buy" else "sell"
    if target_type == "trade_plan" and target_id is not None:
        return conn.execute(
            """
            SELECT id, side, executed_date
            FROM trades
            WHERE account_id = ?
              AND trade_plan_id = ?
              AND side = ?
              AND status = 'executed'
            ORDER BY executed_date DESC, id DESC
            LIMIT 1
            """,
            (account_id, target_id, side),
        ).fetchone()
    if target_type == "position" and target_id is not None and side == "sell":
        return conn.execute(
            """
            SELECT t.id, t.side, t.executed_date
            FROM positions p
            JOIN trades t ON t.id = p.exit_trade_id
            WHERE p.account_id = ?
              AND p.id = ?
              AND t.side = 'sell'
              AND t.status = 'executed'
            ORDER BY t.executed_date DESC, t.id DESC
            LIMIT 1
            """,
            (account_id, target_id),
        ).fetchone()
    return None


def _matching_exit_decision(
    conn: sqlite3.Connection,
    account_id: int,
    position_id: int,
    execution_date: str | None,
) -> sqlite3.Row | None:
    if execution_date:
        return conn.execute(
            """
            SELECT id, decision
            FROM exit_decisions
            WHERE account_id = ?
              AND position_id = ?
              AND decision_date >= ?
            ORDER BY decision_date, id
            LIMIT 1
            """,
            (account_id, position_id, execution_date),
        ).fetchone()
    return conn.execute(
        """
        SELECT id, decision
        FROM exit_decisions
        WHERE account_id = ?
          AND position_id = ?
        ORDER BY decision_date DESC, id DESC
        LIMIT 1
        """,
        (account_id, position_id),
    ).fetchone()


def _trade_on_date(conn: sqlite3.Connection, account_id: int, execution_date: str | None) -> sqlite3.Row | None:
    if execution_date is None:
        return None
    return conn.execute(
        """
        SELECT id, side, executed_date
        FROM trades
        WHERE account_id = ?
          AND executed_date = ?
          AND status = 'executed'
        ORDER BY id DESC
        LIMIT 1
        """,
        (account_id, execution_date),
    ).fetchone()


def _next_open_date(conn: sqlite3.Connection, as_of_date: str | None) -> str | None:
    if as_of_date is None:
        return None
    row = conn.execute(
        """
        SELECT cal_date
        FROM trade_calendar
        WHERE cal_date > ?
          AND is_open = 1
        ORDER BY cal_date
        LIMIT 1
        """,
        (as_of_date,),
    ).fetchone()
    return None if row is None else row["cal_date"]


def _build_list(
    account_id: int | None,
    account_key: str | None,
    review_date: str,
    items: list[DecisionActionLogEntry],
) -> DecisionActionLogList:
    followed_count = sum(1 for item in items if item.operator_decision == "followed")
    deferred_count = sum(1 for item in items if item.operator_decision == "deferred")
    override_count = sum(1 for item in items if item.operator_decision == "overrode")
    pending_outcome_count = sum(1 for item in items if item.outcome and item.outcome.outcome_status == "pending_outcome")
    unresolved_blocker_codes = sorted({code for item in items for code in item.unresolved_blocker_codes})
    summary = (
        f"Decision action log has {len(items)} entries: "
        f"followed={followed_count}, deferred={deferred_count}, overrode={override_count}."
    )
    if unresolved_blocker_codes:
        summary += f" Unresolved blockers recorded: {', '.join(unresolved_blocker_codes)}."
    if pending_outcome_count:
        summary += f" Pending outcome reviews: {pending_outcome_count}."
    return DecisionActionLogList(
        account_id=account_id,
        account_key=account_key,
        review_date=review_date,
        items=items,
        summary=summary,
        followed_count=followed_count,
        deferred_count=deferred_count,
        override_count=override_count,
        unresolved_blocker_codes=unresolved_blocker_codes,
        pending_outcome_count=pending_outcome_count,
    )


def _empty_list(
    request: ListDecisionActionLogsRequest,
    account_id: int | None,
    account_key: str | None,
) -> DecisionActionLogList:
    return _build_list(account_id, account_key, request.review_date, [])


def _reserve_operation(
    conn: sqlite3.Connection,
    request: CreateDecisionActionLogRequest,
    ctx: RequestContext,
    account_id: int,
) -> int | None:
    if ctx.idempotency_key is None:
        return None
    request_json = _json_dumps({"request": asdict(request), "dry_run": ctx.dry_run})
    existing = conn.execute(
        "SELECT id FROM operation_requests WHERE idempotency_key = ?",
        (ctx.idempotency_key,),
    ).fetchone()
    if existing is not None:
        conn.execute(
            """
            UPDATE operation_requests
            SET request_id = ?,
                operation_type = 'decision_action_log',
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
            (ctx.request_id, account_id, request.review_date, request_json, ctx.operator, existing["id"]),
        )
        return int(existing["id"])
    cursor = conn.execute(
        """
        INSERT INTO operation_requests
          (idempotency_key, request_id, operation_type, account_id, as_of_date, status, request_json, operator)
        VALUES
          (?, ?, 'decision_action_log', ?, ?, 'started', ?, ?)
        """,
        (ctx.idempotency_key, ctx.request_id, account_id, request.review_date, request_json, ctx.operator),
    )
    return int(cursor.lastrowid)


def _finish_operation(
    conn: sqlite3.Connection,
    operation_id: int,
    status: str,
    entry: DecisionActionLogEntry,
) -> None:
    conn.execute(
        """
        UPDATE operation_requests
        SET status = ?,
            response_json = ?,
            finished_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, _json_dumps(asdict(entry)), operation_id),
    )


def _lineage(entry: DecisionActionLogEntry) -> dict[str, int | str | None]:
    return {
        "decision_action_log_id": entry.decision_action_log_id,
        "account_id": entry.account_id,
        "account_key": entry.account_key,
        "review_date": entry.review_date,
        "execution_date": entry.execution_date,
        "system_action": entry.system_action,
        "operator_decision": entry.operator_decision,
        "advisory_only": "true",
    }


def _normalized_cockpit_status(value: str | None) -> str:
    text = str(value or "unknown").strip()
    return text if text in COCKPIT_STATUSES else "unknown"


def _loads_string_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return _clean_string_list(value)


def _clean_string_list(values: list[Any]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None
