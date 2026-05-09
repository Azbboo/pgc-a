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
}


@dataclass(frozen=True)
class PaperReadinessRequest:
    as_of_date: str
    account_key: str | None = DEFAULT_PAPER_ACCOUNT_KEY
    account_id: int | None = None
    min_trades: int = DEFAULT_MIN_PAPER_TRADES


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
            open_positions_count = _count_open_positions(conn, account.id)
            due_exit_positions_count = _count_due_exit_positions(conn, account.id, request.as_of_date)
            open_blockers_count = _count_open_data_quality_blockers(conn)
            duplicate_open_positions = _duplicate_open_positions(conn, account.id)
            invariant_report = check_database(self.db_path)
            invariant_violation_codes = [violation.code for violation in invariant_report.violations]

            errors: list[ServiceError] = []
            if trades_count < request.min_trades:
                errors.append(
                    ServiceError(
                        code="MIN_PAPER_TRADES_NOT_MET",
                        message=(
                            f"Paper account {account.account_key} has {trades_count} executed trades; "
                            f"minimum is {request.min_trades}."
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

            warnings = [
                *_cash_equity_warnings(conn, account.id, request.as_of_date, open_positions_count),
                *_agent_evidence_warnings(conn, account.id),
            ]
            readiness = "blocked" if errors else "warning" if warnings else "pass"
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
                promotion_blockers=[error.code for error in errors],
                promotion_warnings=[warning.code for warning in warnings],
            )
            return ServiceResult(
                status="blocked" if errors else "success",
                request_id=ctx.request_id,
                data=data,
                warnings=warnings,
                errors=errors,
                lineage={"account_id": account.id, "as_of_date": request.as_of_date},
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
    )


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
