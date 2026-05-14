"""Operational readiness checks for paper-to-live preparation."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from pgc_trading.config import Paths
from pgc_trading.market.calendar import is_yyyymmdd
from pgc_trading.portfolio.state_machines import OPEN_POSITION_STATUSES
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult, ServiceWarning
from pgc_trading.services.portfolio_planning_service import _resolve_account
from pgc_trading.storage.database import connect
from pgc_trading.storage.invariant_checks import check_database


DEFAULT_PAPER_ACCOUNT_KEY = "paper-main"
DEFAULT_MIN_PAPER_TRADES = 10
PAPER_ACCEPTANCE_STALE_EVIDENCE_CODES = frozenset(
    {
        "MARKET_DATA_MISSING",
        "STALE_MARKET_DATA",
        "MARKET_REVIEW_MISSING",
        "MARKET_EVIDENCE_MISSING",
        "MARKET_PLAN_CONTEXT_MISSING",
        "AGENT_EXTERNAL_EVIDENCE_MISSING",
    }
)
PAPER_ACCEPTANCE_AGENT_REVIEW_CODES = frozenset(
    {
        "AGENT_REVIEW_NOT_RUN",
        "AGENT_REVIEW_UNAVAILABLE",
    }
)
PAPER_ACCEPTANCE_OPEN_EXECUTION_MISMATCH_CODES = frozenset(
    {
        "OPEN_EXECUTION_BLOCKED",
        "OPEN_EXECUTION_UNAVAILABLE",
        "OPEN_EXECUTION_DATE_MISMATCH",
        "OPEN_EXECUTION_PLAN_DATE_MISMATCH",
    }
)
OPEN_POSITION_STATUS_VALUES = tuple(sorted(OPEN_POSITION_STATUSES))
T2_DECISION_DUE_STATUSES = ("open", "waiting_t2", "need_t2_decision")
T5_DECISION_DUE_STATUSES = ("holding_to_t5", "need_t5_exit")
READINESS_REQUIRED_COLUMNS = {
    "portfolio_accounts": (
        "id",
        "account_key",
        "account_type",
        "initial_cash",
        "max_positions",
        "position_sizing",
        "status",
    ),
    "trades": (
        "account_id",
        "agent_decision_id",
        "status",
        "side",
        "executed_price",
        "amount",
        "shares",
        "fee",
        "tax",
        "slippage",
    ),
    "trade_plans": ("account_id", "agent_decision_id"),
    "positions": (
        "account_id",
        "entry_trade_id",
        "exit_trade_id",
        "ts_code",
        "status",
        "cost",
        "planned_t2_date",
        "planned_t5_date",
    ),
    "data_quality_events": ("severity", "status"),
    "equity_snapshots": ("account_id", "as_of_date", "cash", "market_value", "total_equity"),
    "operation_requests": ("operation_type", "as_of_date", "status", "started_at", "finished_at"),
    "agent_decisions": ("id",),
    "market_external_items": ("as_of_date", "scope_type", "published_date", "source_hash"),
    "agent_external_items": ("ts_code", "published_date", "item_type", "source_hash"),
}


@dataclass(frozen=True)
class PaperReadinessRequest:
    as_of_date: str
    account_key: str | None = DEFAULT_PAPER_ACCOUNT_KEY
    account_id: int | None = None
    min_trades: int = DEFAULT_MIN_PAPER_TRADES


@dataclass(frozen=True)
class PaperReadinessGate:
    gate: str
    label: str
    status: str
    summary: str
    blocker_codes: list[str] = field(default_factory=list)
    warning_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NextDayDecisionChecklistItem:
    key: str
    label: str
    status: str
    summary: str
    manual_action: str
    detail: str
    blocker_codes: list[str] = field(default_factory=list)
    warning_codes: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NextDayDecisionSummary:
    status: str
    headline: str
    recommended_manual_action: str
    blocker_count: int
    warning_count: int


@dataclass(frozen=True)
class PaperReadinessProgress:
    required_completed_trades: int
    completed_trades: int
    executed_trades: int
    remaining_completed_trades: int
    progress_ratio: float
    status: str
    summary: str
    ready_after: str


@dataclass(frozen=True)
class PaperDueExitPosition:
    position_id: int
    ts_code: str
    name: str
    status: str
    due_stage: str
    planned_t2_date: str | None
    planned_t5_date: str | None
    manual_action: str


@dataclass(frozen=True)
class PaperExitLifecycleSummary:
    open_positions_count: int
    waiting_t2_count: int
    waiting_t5_count: int
    planned_exit_count: int
    overdue_t2_count: int
    overdue_t5_count: int
    due_exit_positions_count: int
    next_due_date: str | None
    summary: str
    manual_action: str


@dataclass(frozen=True)
class PaperLatestEvidenceStatus:
    agent_status: str
    latest_agent_decision_count: int
    latest_agent_decision_at: str | None
    market_evidence_status: str
    market_evidence_count: int
    latest_market_evidence_date: str | None
    agent_evidence_status: str
    agent_evidence_count: int
    latest_agent_evidence_date: str | None
    summary: str
    manual_action: str


@dataclass(frozen=True)
class PaperReadinessNextAction:
    status: str
    headline: str
    manual_action: str
    not_ready_reasons: list[str] = field(default_factory=list)
    ready_after: list[str] = field(default_factory=list)
    blocker_codes: list[str] = field(default_factory=list)
    warning_codes: list[str] = field(default_factory=list)
    safety_note: str = (
        "只读纸盘进度；不会自动创建交易计划、记录成交、晋级策略、启用券商或定时任务。"
    )


@dataclass(frozen=True)
class PaperReadinessResult:
    account_key: str
    as_of_date: str
    readiness: str
    trades_count: int
    closed_trades_count: int
    win_rate: float | None
    realized_pnl: float
    avg_slippage: float | None
    last_pipeline_status: str | None
    open_positions_count: int
    due_exit_positions_count: int
    open_blockers_count: int
    invariant_ok: bool
    ledger_blockers_count: int = 0
    invariant_violation_codes: list[str] = field(default_factory=list)
    promotion_blockers: list[str] = field(default_factory=list)
    promotion_warnings: list[str] = field(default_factory=list)
    readiness_gates: list[PaperReadinessGate] = field(default_factory=list)
    readiness_progress: PaperReadinessProgress | None = None
    exit_lifecycle: PaperExitLifecycleSummary | None = None
    due_exit_positions: list[PaperDueExitPosition] = field(default_factory=list)
    latest_evidence_status: PaperLatestEvidenceStatus | None = None
    readiness_next_action: PaperReadinessNextAction | None = None


class OperationalReadinessService:
    """Evaluate whether a paper account is ready for live-preparation work."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def check_paper_readiness(
        self,
        request: PaperReadinessRequest,
        ctx: RequestContext,
    ) -> ServiceResult[PaperReadinessResult]:
        validation_errors = _validate_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_result(
                    request,
                    "blocked",
                    promotion_blockers=[error.code for error in validation_errors],
                ),
                errors=validation_errors,
            )

        with connect(self.db_path) as conn:
            schema_errors = _schema_preflight_errors(conn)
            if schema_errors:
                return ServiceResult(
                    status="blocked",
                    request_id=ctx.request_id,
                    data=_empty_result(
                        request,
                        "blocked",
                        promotion_blockers=[error.code for error in schema_errors],
                    ),
                    errors=schema_errors,
                )

            account = _resolve_account(conn, request.account_key, request.account_id)
            if isinstance(account, ServiceError):
                return ServiceResult(
                    status="validation_failed",
                    request_id=ctx.request_id,
                    data=_empty_result(request, "blocked", promotion_blockers=[account.code]),
                    errors=[account],
                )

            trades_count = _count_executed_trades(conn, account.id)
            closed_stats = _closed_trade_stats(conn, account.id)
            avg_slippage = _avg_slippage(conn, account.id)
            last_pipeline_status = _last_pipeline_status(conn, request.as_of_date)
            exit_lifecycle, due_exit_positions = _exit_lifecycle(conn, account.id, request.as_of_date)
            open_positions_count = exit_lifecycle.open_positions_count
            due_exit_positions_count = exit_lifecycle.due_exit_positions_count
            open_blockers_count = _count_open_data_quality_blockers(conn)
            duplicate_open_positions = _duplicate_open_positions(conn, account.id)
            invariant_report = check_database(self.db_path)
            invariant_violation_codes = [violation.code for violation in invariant_report.violations]
            readiness_progress = _readiness_progress(
                min_trades=request.min_trades,
                trades_count=trades_count,
                closed_trades_count=closed_stats.closed_trades_count,
            )
            latest_evidence_status = _latest_evidence_status(conn, account.id, request.as_of_date)

            errors: list[ServiceError] = []
            if closed_stats.closed_trades_count < request.min_trades:
                errors.append(
                    ServiceError(
                        code="MIN_PAPER_TRADES_NOT_MET",
                        message=(
                            f"Paper account {account.account_key} has {closed_stats.closed_trades_count} completed "
                            f"paper trades; minimum is {request.min_trades}."
                        ),
                        entity_type="portfolio_account",
                        entity_id=account.id,
                    )
                )
            if duplicate_open_positions:
                duplicate_summary = ", ".join(
                    f"{row['ts_code']}={int(row['open_count'])}" for row in duplicate_open_positions
                )
                errors.append(
                    ServiceError(
                        code="DUPLICATE_OPEN_POSITIONS",
                        message=f"Duplicate open positions exist for account {account.account_key}: {duplicate_summary}.",
                        entity_type="portfolio_account",
                        entity_id=account.id,
                    )
                )
            if open_blockers_count > 0:
                errors.append(
                    ServiceError(
                        code="OPEN_DATA_QUALITY_BLOCKERS",
                        message=f"{open_blockers_count} open data quality blocker(s) must be resolved.",
                    )
                )
            if due_exit_positions_count > 0:
                errors.append(
                    ServiceError(
                        code="DUE_EXIT_DECISIONS",
                        message=(
                            f"{due_exit_positions_count} open position(s) have unhandled T+2/T+5 decisions "
                            f"as of {request.as_of_date}."
                        ),
                        entity_type="portfolio_account",
                        entity_id=account.id,
                    )
                )
            if not invariant_report.ok:
                codes = ", ".join(invariant_violation_codes)
                errors.append(
                    ServiceError(
                        code="DATABASE_INVARIANTS_FAILED",
                        message=f"Ledger/database invariant check failed: {codes}.",
                        severity="blocker",
                    )
                )

            cash_equity_warnings = _cash_equity_warnings(
                conn,
                account.id,
                request.as_of_date,
                open_positions_count,
            )
            agent_evidence_warnings = _agent_evidence_warnings(conn, account.id)
            warnings = [*cash_equity_warnings, *agent_evidence_warnings]
            readiness = "blocked" if errors else "warning" if warnings else "pass"
            promotion_blockers = [error.code for error in errors]
            promotion_warnings = [warning.code for warning in warnings]
            readiness_gates = _paper_readiness_gates(
                min_trades=request.min_trades,
                trades_count=trades_count,
                closed_trades_count=closed_stats.closed_trades_count,
                invariant_ok=invariant_report.ok,
                invariant_violation_codes=invariant_violation_codes,
                open_blockers_count=open_blockers_count,
                due_exit_positions_count=due_exit_positions_count,
                cash_equity_warnings=cash_equity_warnings,
                agent_evidence_warnings=agent_evidence_warnings,
                duplicate_open_positions=duplicate_open_positions,
            )
            readiness_next_action = _readiness_next_action(
                readiness=readiness,
                progress=readiness_progress,
                exit_lifecycle=exit_lifecycle,
                open_blockers_count=open_blockers_count,
                invariant_violation_codes=invariant_violation_codes,
                duplicate_open_positions=duplicate_open_positions,
                promotion_blockers=promotion_blockers,
                promotion_warnings=promotion_warnings,
                latest_evidence_status=latest_evidence_status,
            )
            data = PaperReadinessResult(
                account_key=account.account_key,
                as_of_date=request.as_of_date,
                readiness=readiness,
                trades_count=trades_count,
                closed_trades_count=closed_stats.closed_trades_count,
                win_rate=closed_stats.win_rate,
                realized_pnl=closed_stats.realized_pnl,
                avg_slippage=avg_slippage,
                last_pipeline_status=last_pipeline_status,
                open_positions_count=open_positions_count,
                due_exit_positions_count=due_exit_positions_count,
                open_blockers_count=open_blockers_count,
                invariant_ok=invariant_report.ok,
                ledger_blockers_count=len(invariant_report.violations),
                invariant_violation_codes=invariant_violation_codes,
                promotion_blockers=promotion_blockers,
                promotion_warnings=promotion_warnings,
                readiness_gates=readiness_gates,
                readiness_progress=readiness_progress,
                exit_lifecycle=exit_lifecycle,
                due_exit_positions=due_exit_positions,
                latest_evidence_status=latest_evidence_status,
                readiness_next_action=readiness_next_action,
            )
            return ServiceResult(
                status="blocked" if errors else "success",
                request_id=ctx.request_id,
                data=data,
                warnings=warnings,
                errors=errors,
                lineage={"account_id": account.id, "as_of_date": request.as_of_date},
            )


def summarize_next_day_decision(
    checklist: list[NextDayDecisionChecklistItem],
    *,
    default_action: str = "人工确认下一交易日没有待执行动作。",
) -> NextDayDecisionSummary:
    """Summarize read-only next-day decision checks for operator review."""

    blocker_count = sum(1 for item in checklist if item.status == "blocked")
    warning_count = sum(1 for item in checklist if item.status == "warning")
    if blocker_count:
        first_blocker = next(item for item in checklist if item.status == "blocked")
        return NextDayDecisionSummary(
            status="blocked",
            headline=f"下一交易日决策被 {blocker_count} 项 blocker 阻断。",
            recommended_manual_action=first_blocker.manual_action,
            blocker_count=blocker_count,
            warning_count=warning_count,
        )
    if warning_count:
        first_warning = next(item for item in checklist if item.status == "warning")
        return NextDayDecisionSummary(
            status="review_required",
            headline=f"下一交易日决策需要人工复核 {warning_count} 项 warning。",
            recommended_manual_action=first_warning.manual_action,
            blocker_count=0,
            warning_count=warning_count,
        )
    return NextDayDecisionSummary(
        status="ready",
        headline="下一交易日决策清单通过；仍需人工确认实际开盘和成交事实。",
        recommended_manual_action=default_action,
        blocker_count=0,
        warning_count=0,
    )


def _validate_request(request: PaperReadinessRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not is_yyyymmdd(request.as_of_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="as_of_date must use YYYYMMDD format."))
    if request.min_trades < 1:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="min_trades must be greater than zero."))
    return errors


@dataclass(frozen=True)
class _ClosedTradeStats:
    closed_trades_count: int
    win_rate: float | None
    realized_pnl: float


def _empty_result(
    request: PaperReadinessRequest,
    readiness: str,
    *,
    promotion_blockers: list[str] | None = None,
    promotion_warnings: list[str] | None = None,
) -> PaperReadinessResult:
    return PaperReadinessResult(
        account_key=request.account_key or "",
        as_of_date=request.as_of_date,
        readiness=readiness,
        trades_count=0,
        closed_trades_count=0,
        win_rate=None,
        realized_pnl=0.0,
        avg_slippage=None,
        last_pipeline_status=None,
        open_positions_count=0,
        due_exit_positions_count=0,
        open_blockers_count=0,
        invariant_ok=False,
        ledger_blockers_count=0,
        invariant_violation_codes=[],
        promotion_blockers=promotion_blockers or [],
        promotion_warnings=promotion_warnings or [],
        readiness_gates=[],
        readiness_progress=_readiness_progress(
            min_trades=request.min_trades,
            trades_count=0,
            closed_trades_count=0,
        ),
        exit_lifecycle=_empty_exit_lifecycle(),
        due_exit_positions=[],
        latest_evidence_status=_empty_evidence_status(),
        readiness_next_action=PaperReadinessNextAction(
            status=readiness,
            headline="Paper readiness 暂无可计算进度。",
            manual_action="先修复请求或 schema blocker，再重新运行只读 readiness 检查。",
            not_ready_reasons=promotion_blockers or [],
            ready_after=["请求和数据库 schema 通过校验"],
            blocker_codes=promotion_blockers or [],
            warning_codes=promotion_warnings or [],
        ),
    )


def _readiness_progress(
    *,
    min_trades: int,
    trades_count: int,
    closed_trades_count: int,
) -> PaperReadinessProgress:
    remaining = max(0, min_trades - closed_trades_count)
    ratio = min(1.0, closed_trades_count / min_trades) if min_trades else 0.0
    status = "pass" if remaining == 0 else "blocked"
    return PaperReadinessProgress(
        required_completed_trades=min_trades,
        completed_trades=closed_trades_count,
        executed_trades=trades_count,
        remaining_completed_trades=remaining,
        progress_ratio=ratio,
        status=status,
        summary=(
            f"已闭环 {closed_trades_count}/{min_trades} 笔；"
            f"已执行 {trades_count} 笔；还差 {remaining} 笔闭环交易。"
            if remaining
            else f"已闭环 {closed_trades_count}/{min_trades} 笔；10 笔闭环门槛已满足。"
        ),
        ready_after="10 笔闭环交易门槛已满足" if remaining == 0 else f"还需 {remaining} 笔已闭环交易",
    )


def _empty_exit_lifecycle() -> PaperExitLifecycleSummary:
    return PaperExitLifecycleSummary(
        open_positions_count=0,
        waiting_t2_count=0,
        waiting_t5_count=0,
        planned_exit_count=0,
        overdue_t2_count=0,
        overdue_t5_count=0,
        due_exit_positions_count=0,
        next_due_date=None,
        summary="暂无持仓退出生命周期数据。",
        manual_action="确认账户和持仓账本后重新运行只读 readiness 检查。",
    )


def _empty_evidence_status() -> PaperLatestEvidenceStatus:
    return PaperLatestEvidenceStatus(
        agent_status="unknown",
        latest_agent_decision_count=0,
        latest_agent_decision_at=None,
        market_evidence_status="unknown",
        market_evidence_count=0,
        latest_market_evidence_date=None,
        agent_evidence_status="unknown",
        agent_evidence_count=0,
        latest_agent_evidence_date=None,
        summary="暂无 Agent / evidence 状态。",
        manual_action="补齐或确认 reviewed evidence 后重新运行只读 readiness 检查。",
    )


def _exit_lifecycle(
    conn: sqlite3.Connection,
    account_id: int,
    as_of_date: str,
) -> tuple[PaperExitLifecycleSummary, list[PaperDueExitPosition]]:
    rows = conn.execute(
        f"""
        SELECT id, ts_code, name, status, planned_t2_date, planned_t5_date
        FROM positions
        WHERE account_id = ?
          AND status IN ({_placeholders(OPEN_POSITION_STATUS_VALUES)})
        ORDER BY
          COALESCE(planned_t2_date, planned_t5_date, '99999999'),
          id
        """,
        (account_id, *OPEN_POSITION_STATUS_VALUES),
    ).fetchall()

    waiting_t2_count = 0
    waiting_t5_count = 0
    planned_exit_count = 0
    overdue_t2_count = 0
    overdue_t5_count = 0
    due_positions: list[PaperDueExitPosition] = []
    future_due_dates: list[str] = []

    for row in rows:
        status = str(row["status"])
        planned_t2_date = row["planned_t2_date"]
        planned_t5_date = row["planned_t5_date"]
        due_stage: str | None = None
        if status in T2_DECISION_DUE_STATUSES and (
            status == "need_t2_decision" or (planned_t2_date is not None and str(planned_t2_date) <= as_of_date)
        ):
            due_stage = "t2"
            overdue_t2_count += 1
        elif status in T5_DECISION_DUE_STATUSES and (
            status == "need_t5_exit" or (planned_t5_date is not None and str(planned_t5_date) <= as_of_date)
        ):
            due_stage = "t5"
            overdue_t5_count += 1

        if status in {"open", "waiting_t2"} and due_stage is None:
            waiting_t2_count += 1
            if planned_t2_date and str(planned_t2_date) > as_of_date:
                future_due_dates.append(str(planned_t2_date))
        elif status == "holding_to_t5" and due_stage is None:
            waiting_t5_count += 1
            if planned_t5_date and str(planned_t5_date) > as_of_date:
                future_due_dates.append(str(planned_t5_date))
        elif status == "planned_exit":
            planned_exit_count += 1

        if due_stage is not None:
            due_positions.append(
                PaperDueExitPosition(
                    position_id=int(row["id"]),
                    ts_code=str(row["ts_code"]),
                    name=str(row["name"]),
                    status=status,
                    due_stage=due_stage,
                    planned_t2_date=None if planned_t2_date is None else str(planned_t2_date),
                    planned_t5_date=None if planned_t5_date is None else str(planned_t5_date),
                    manual_action=(
                        "人工评估 T+2 止盈/止损/持有到 T+5，并按结果记录或生成退出计划。"
                        if due_stage == "t2"
                        else "人工评估 T+5 超时退出，并按结果记录或生成退出计划。"
                    ),
                )
            )

    due_count = len(due_positions)
    next_due_date = min(future_due_dates) if future_due_dates else None
    if due_count:
        manual_action = f"先人工处理 {due_count} 个到期退出，再判断纸盘 readiness。"
    elif rows:
        manual_action = (
            f"当前无到期退出；等待下一到期日 {next_due_date}。"
            if next_due_date
            else "当前无到期退出；人工确认已有退出计划是否已完成。"
        )
    else:
        manual_action = "当前无开放持仓；继续人工记录完整买卖闭环。"

    summary = (
        f"开放持仓 {len(rows)}；等待 T+2 {waiting_t2_count}；等待 T+5 {waiting_t5_count}；"
        f"已有退出计划 {planned_exit_count}；到期 T+2/T+5 {overdue_t2_count}/{overdue_t5_count}。"
    )
    return (
        PaperExitLifecycleSummary(
            open_positions_count=len(rows),
            waiting_t2_count=waiting_t2_count,
            waiting_t5_count=waiting_t5_count,
            planned_exit_count=planned_exit_count,
            overdue_t2_count=overdue_t2_count,
            overdue_t5_count=overdue_t5_count,
            due_exit_positions_count=due_count,
            next_due_date=next_due_date,
            summary=summary,
            manual_action=manual_action,
        ),
        due_positions,
    )


def _latest_evidence_status(
    conn: sqlite3.Connection,
    account_id: int,
    as_of_date: str,
) -> PaperLatestEvidenceStatus:
    agent_linkage = conn.execute(
        """
        SELECT COUNT(DISTINCT ad.id) AS linked_count,
               MAX(ad.created_at) AS latest_created_at
        FROM agent_decisions ad
        LEFT JOIN trade_plans tp ON tp.agent_decision_id = ad.id
        LEFT JOIN trades t ON t.agent_decision_id = ad.id
        WHERE tp.account_id = ?
           OR t.account_id = ?
        """,
        (account_id, account_id),
    ).fetchone()
    linked_agent_count = int(agent_linkage["linked_count"] or 0)
    agent_status = "linked" if linked_agent_count else "missing"

    market_evidence = conn.execute(
        """
        SELECT COUNT(*) AS evidence_count,
               MAX(as_of_date) AS latest_evidence_date
        FROM market_external_items
        WHERE as_of_date <= ?
        """,
        (as_of_date,),
    ).fetchone()
    market_evidence_count = int(market_evidence["evidence_count"] or 0)
    latest_market_date = market_evidence["latest_evidence_date"]

    ts_codes = [
        str(row["ts_code"])
        for row in conn.execute(
            """
            SELECT DISTINCT ts_code
            FROM (
              SELECT ts_code FROM trades WHERE account_id = ?
              UNION
              SELECT ts_code FROM positions WHERE account_id = ?
            )
            ORDER BY ts_code
            """,
            (account_id, account_id),
        ).fetchall()
    ]
    agent_evidence_count = 0
    latest_agent_evidence_date: str | None = None
    if ts_codes:
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS evidence_count,
                   MAX(published_date) AS latest_evidence_date
            FROM agent_external_items
            WHERE published_date <= ?
              AND ts_code IN ({_placeholders(tuple(ts_codes))})
            """,
            (as_of_date, *ts_codes),
        ).fetchone()
        agent_evidence_count = int(row["evidence_count"] or 0)
        latest_agent_evidence_date = row["latest_evidence_date"]

    market_status = "available" if market_evidence_count else "missing"
    agent_evidence_status = "available" if agent_evidence_count else "missing"
    missing_parts = [
        label
        for label, status in [
            ("Agent 决策链路", agent_status),
            ("全市场证据", market_status),
            ("账户标的证据", agent_evidence_status),
        ]
        if status == "missing"
    ]
    return PaperLatestEvidenceStatus(
        agent_status=agent_status,
        latest_agent_decision_count=linked_agent_count,
        latest_agent_decision_at=agent_linkage["latest_created_at"],
        market_evidence_status=market_status,
        market_evidence_count=market_evidence_count,
        latest_market_evidence_date=None if latest_market_date is None else str(latest_market_date),
        agent_evidence_status=agent_evidence_status,
        agent_evidence_count=agent_evidence_count,
        latest_agent_evidence_date=None if latest_agent_evidence_date is None else str(latest_agent_evidence_date),
        summary=(
            f"Agent 链路 {linked_agent_count}；全市场证据 {market_evidence_count}；"
            f"账户标的证据 {agent_evidence_count}。"
        ),
        manual_action=(
            f"补齐或确认已审核证据：{', '.join(missing_parts)}。"
            if missing_parts
            else "Agent 和 evidence 状态可供人工抽查；继续保持只读。"
        ),
    )


def _readiness_next_action(
    *,
    readiness: str,
    progress: PaperReadinessProgress,
    exit_lifecycle: PaperExitLifecycleSummary,
    open_blockers_count: int,
    invariant_violation_codes: list[str],
    duplicate_open_positions: list[sqlite3.Row],
    promotion_blockers: list[str],
    promotion_warnings: list[str],
    latest_evidence_status: PaperLatestEvidenceStatus,
) -> PaperReadinessNextAction:
    not_ready_reasons: list[str] = []
    ready_after: list[str] = []
    if progress.remaining_completed_trades:
        not_ready_reasons.append(progress.ready_after)
        ready_after.append(f"完成并记录 {progress.remaining_completed_trades} 笔买入+卖出闭环")
    if exit_lifecycle.due_exit_positions_count:
        not_ready_reasons.append(f"{exit_lifecycle.due_exit_positions_count} 个 T+2/T+5 到期退出待处理")
        ready_after.append(exit_lifecycle.manual_action)
    if open_blockers_count:
        not_ready_reasons.append(f"{open_blockers_count} 个 open 数据质量 blocker")
        ready_after.append("关闭 open data_quality blocker")
    if invariant_violation_codes:
        not_ready_reasons.append(f"账本 invariant 失败：{', '.join(invariant_violation_codes)}")
        ready_after.append("修复账本 invariant")
    if duplicate_open_positions:
        duplicate_symbols = ", ".join(str(row["ts_code"]) for row in duplicate_open_positions)
        not_ready_reasons.append(f"重复开放持仓：{duplicate_symbols}")
        ready_after.append("合并或修正重复开放持仓")
    if promotion_warnings:
        ready_after.append(f"人工复核警告：{', '.join(promotion_warnings)}")

    if exit_lifecycle.due_exit_positions_count:
        manual_action = exit_lifecycle.manual_action
    elif open_blockers_count:
        manual_action = "先清理数据质量 blocker，再重新运行 paper-readiness。"
    elif invariant_violation_codes or duplicate_open_positions:
        manual_action = "先修复账本 invariant / 重复持仓，再重新运行 paper-readiness。"
    elif progress.remaining_completed_trades:
        manual_action = (
            f"继续人工记录纸盘完整买卖闭环；还需 {progress.remaining_completed_trades} 笔已闭环交易。"
        )
    elif promotion_warnings:
        manual_action = latest_evidence_status.manual_action
    else:
        manual_action = "可进入下一步人工晋级复核；仍不自动交易、不自动晋级。"

    if readiness == "blocked":
        headline = f"纸盘 readiness 未就绪：{len(not_ready_reasons) or len(promotion_blockers)} 项 blocker。"
    elif readiness == "warning":
        headline = f"纸盘 readiness 门槛通过，但有 {len(promotion_warnings)} 项 warning 需要人工复核。"
    else:
        headline = "纸盘 readiness 通过；只表示可人工复核下一阶段。"

    return PaperReadinessNextAction(
        status=readiness,
        headline=headline,
        manual_action=manual_action,
        not_ready_reasons=not_ready_reasons or promotion_blockers,
        ready_after=ready_after or ["保持人工复核记录完整"],
        blocker_codes=promotion_blockers,
        warning_codes=promotion_warnings,
    )


def _paper_readiness_gates(
    *,
    min_trades: int,
    trades_count: int,
    closed_trades_count: int,
    invariant_ok: bool,
    invariant_violation_codes: list[str],
    open_blockers_count: int,
    due_exit_positions_count: int,
    cash_equity_warnings: list[ServiceWarning],
    agent_evidence_warnings: list[ServiceWarning],
    duplicate_open_positions: list[sqlite3.Row],
) -> list[PaperReadinessGate]:
    duplicate_codes = ["DUPLICATE_OPEN_POSITIONS"] if duplicate_open_positions else []
    return [
        PaperReadinessGate(
            gate="completed_trade_sample",
            label="10 笔闭环交易",
            status="pass" if closed_trades_count >= min_trades else "blocked",
            summary=f"已闭环 {closed_trades_count}/{min_trades} 笔；已执行 {trades_count} 笔",
            blocker_codes=[] if closed_trades_count >= min_trades else ["MIN_PAPER_TRADES_NOT_MET"],
        ),
        PaperReadinessGate(
            gate="ledger_invariants",
            label="账本 invariant",
            status="pass" if invariant_ok and not duplicate_codes else "blocked",
            summary="账本 invariant 通过" if invariant_ok and not duplicate_codes else "账本 invariant 或重复持仓未清除",
            blocker_codes=[*invariant_violation_codes, *duplicate_codes],
        ),
        PaperReadinessGate(
            gate="data_quality_blockers",
            label="数据质量 blocker",
            status="pass" if open_blockers_count == 0 else "blocked",
            summary=f"{open_blockers_count} 个 open blocker",
            blocker_codes=[] if open_blockers_count == 0 else ["OPEN_DATA_QUALITY_BLOCKERS"],
        ),
        PaperReadinessGate(
            gate="exit_decisions",
            label="T+2 / T+5 待处理",
            status="pass" if due_exit_positions_count == 0 else "blocked",
            summary=f"{due_exit_positions_count} 个到期退出判断",
            blocker_codes=[] if due_exit_positions_count == 0 else ["DUE_EXIT_DECISIONS"],
        ),
        PaperReadinessGate(
            gate="cash_equity_reconciliation",
            label="现金 / 权益核对",
            status="warning" if cash_equity_warnings else "pass",
            summary="存在现金/权益核对警告" if cash_equity_warnings else "现金/权益核对未发现警告",
            warning_codes=[warning.code for warning in cash_equity_warnings],
        ),
        PaperReadinessGate(
            gate="agent_evidence_linkage",
            label="Agent 证据链路",
            status="warning" if agent_evidence_warnings else "pass",
            summary="缺少账户级 Agent 证据链路" if agent_evidence_warnings else "Agent 证据已关联计划或成交",
            warning_codes=[warning.code for warning in agent_evidence_warnings],
        ),
    ]


def _schema_preflight_errors(conn: sqlite3.Connection) -> list[ServiceError]:
    errors: list[ServiceError] = []
    for table_name, required_columns in READINESS_REQUIRED_COLUMNS.items():
        if not _table_exists(conn, table_name):
            errors.append(
                ServiceError(
                    code="READINESS_SCHEMA_INCOMPATIBLE",
                    message=f"Required table {table_name} is missing; run storage migrations before paper readiness.",
                    entity_type=table_name,
                )
            )
            continue

        columns = _table_columns(conn, table_name)
        missing = [column for column in required_columns if column not in columns]
        if missing:
            missing_columns = ", ".join(missing)
            errors.append(
                ServiceError(
                    code="READINESS_SCHEMA_INCOMPATIBLE",
                    message=(
                        f"Table {table_name} is missing required readiness column(s): {missing_columns}; "
                        "run storage migrations before paper readiness."
                    ),
                    entity_type=table_name,
                )
            )
    return errors


def _count_executed_trades(conn: sqlite3.Connection, account_id: int) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM trades
            WHERE account_id = ?
              AND status = 'executed'
            """,
            (account_id,),
        ).fetchone()[0]
    )


def _closed_trade_stats(conn: sqlite3.Connection, account_id: int) -> _ClosedTradeStats:
    row = conn.execute(
        """
        WITH closed AS (
          SELECT
            p.id AS position_id,
            (
              COALESCE(exit_trade.amount, exit_trade.executed_price * exit_trade.shares, 0)
              - COALESCE(exit_trade.fee, 0)
              - COALESCE(exit_trade.tax, 0)
              - COALESCE(p.cost, entry_trade.amount + COALESCE(entry_trade.fee, 0) + COALESCE(entry_trade.tax, 0), 0)
            ) AS realized_pnl
          FROM positions p
          JOIN trades entry_trade ON entry_trade.id = p.entry_trade_id
          JOIN trades exit_trade ON exit_trade.id = p.exit_trade_id
          WHERE p.account_id = ?
            AND p.status = 'closed'
            AND entry_trade.status = 'executed'
            AND entry_trade.side = 'buy'
            AND exit_trade.status = 'executed'
            AND exit_trade.side = 'sell'
        )
        SELECT
          COUNT(*) AS closed_trades_count,
          COALESCE(SUM(realized_pnl), 0) AS realized_pnl,
          COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END), 0) AS winning_trades
        FROM closed
        """,
        (account_id,),
    ).fetchone()
    closed_trades_count = int(row["closed_trades_count"])
    winning_trades = int(row["winning_trades"])
    win_rate = winning_trades / closed_trades_count if closed_trades_count else None
    return _ClosedTradeStats(
        closed_trades_count=closed_trades_count,
        win_rate=win_rate,
        realized_pnl=float(row["realized_pnl"] or 0.0),
    )


def _avg_slippage(conn: sqlite3.Connection, account_id: int) -> float | None:
    row = conn.execute(
        """
        SELECT AVG(slippage) AS avg_slippage
        FROM trades
        WHERE account_id = ?
          AND status = 'executed'
          AND slippage IS NOT NULL
        """,
        (account_id,),
    ).fetchone()
    value = row["avg_slippage"]
    return None if value is None else float(value)


def _last_pipeline_status(conn: sqlite3.Connection, as_of_date: str) -> str | None:
    row = conn.execute(
        """
        SELECT status
        FROM operation_requests
        WHERE as_of_date IS NOT NULL
          AND as_of_date <= ?
          AND operation_type IN (
            'daily_pipeline',
            'daily_review',
            'market_data_refresh',
            'trade_calendar_refresh',
            'data_quality_check',
            'agent_review_daily_pick'
          )
        ORDER BY as_of_date DESC,
                 COALESCE(finished_at, started_at) DESC,
                 id DESC
        LIMIT 1
        """,
        (as_of_date,),
    ).fetchone()
    return None if row is None else str(row["status"])


def _count_open_positions(conn: sqlite3.Connection, account_id: int) -> int:
    return int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM positions
            WHERE account_id = ?
              AND status IN ({_placeholders(OPEN_POSITION_STATUS_VALUES)})
            """,
            (account_id, *OPEN_POSITION_STATUS_VALUES),
        ).fetchone()[0]
    )


def _count_due_exit_positions(conn: sqlite3.Connection, account_id: int, as_of_date: str) -> int:
    return int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM positions
            WHERE account_id = ?
              AND (
                (
                  status IN ({_placeholders(T2_DECISION_DUE_STATUSES)})
                  AND planned_t2_date IS NOT NULL
                  AND planned_t2_date <= ?
                )
                OR (
                  status IN ({_placeholders(T5_DECISION_DUE_STATUSES)})
                  AND planned_t5_date IS NOT NULL
                  AND planned_t5_date <= ?
                )
              )
            """,
            (account_id, *T2_DECISION_DUE_STATUSES, as_of_date, *T5_DECISION_DUE_STATUSES, as_of_date),
        ).fetchone()[0]
    )


def _count_open_data_quality_blockers(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM data_quality_events
            WHERE status = 'open'
              AND severity = 'blocker'
            """
        ).fetchone()[0]
    )


def _duplicate_open_positions(conn: sqlite3.Connection, account_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        f"""
        SELECT ts_code, COUNT(*) AS open_count
        FROM positions
        WHERE account_id = ?
          AND status IN ({_placeholders(OPEN_POSITION_STATUS_VALUES)})
        GROUP BY ts_code
        HAVING COUNT(*) > 1
        ORDER BY ts_code
        """,
        (account_id, *OPEN_POSITION_STATUS_VALUES),
    ).fetchall()


def _cash_equity_warnings(
    conn: sqlite3.Connection,
    account_id: int,
    as_of_date: str,
    open_positions_count: int,
) -> list[ServiceWarning]:
    if open_positions_count == 0:
        return []

    row = conn.execute(
        """
        SELECT cash, market_value, total_equity, as_of_date
        FROM equity_snapshots
        WHERE account_id = ?
          AND as_of_date <= ?
        ORDER BY as_of_date DESC, id DESC
        LIMIT 1
        """,
        (account_id, as_of_date),
    ).fetchone()
    if row is None:
        return [
            ServiceWarning(
                code="CASH_EQUITY_RECONCILIATION_UNPROVEN",
                message="No equity snapshot exists for open positions; cash/equity reconciliation could not be proven.",
                entity_type="portfolio_account",
                entity_id=account_id,
            )
        ]

    expected_total = float(row["cash"]) + float(row["market_value"])
    if abs(expected_total - float(row["total_equity"])) <= 0.01:
        return []

    return [
        ServiceWarning(
            code="EQUITY_SNAPSHOT_MISMATCH",
            message=(
                f"Latest equity snapshot on {row['as_of_date']} has cash + market_value "
                f"{expected_total:.2f} but total_equity {float(row['total_equity']):.2f}."
            ),
            entity_type="portfolio_account",
            entity_id=account_id,
        )
    ]


def _agent_evidence_warnings(conn: sqlite3.Connection, account_id: int) -> list[ServiceWarning]:
    row = conn.execute(
        """
        SELECT 1
        FROM agent_decisions ad
        LEFT JOIN trade_plans tp ON tp.agent_decision_id = ad.id
        LEFT JOIN trades t ON t.agent_decision_id = ad.id
        WHERE tp.account_id = ?
           OR t.account_id = ?
        LIMIT 1
        """,
        (account_id, account_id),
    ).fetchone()
    if row is not None:
        return []
    return [
        ServiceWarning(
            code="AGENT_EVIDENCE_MISSING",
            message="No account-scoped Agent evidence is linked to paper plans or trades; promotion can proceed only as a warning state.",
            entity_type="portfolio_account",
            entity_id=account_id,
        )
    ]


def _placeholders(values: tuple[object, ...]) -> str:
    return ", ".join("?" for _ in values)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
