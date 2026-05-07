"""Operational readiness checks for paper-to-live preparation."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
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
    "trades": ("account_id", "status"),
    "positions": (
        "account_id",
        "entry_trade_id",
        "ts_code",
        "status",
        "planned_t2_date",
        "planned_t5_date",
    ),
    "data_quality_events": ("severity", "status"),
    "equity_snapshots": ("account_id", "as_of_date", "cash", "market_value", "total_equity"),
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
    open_positions_count: int
    due_exit_positions_count: int
    open_blockers_count: int
    invariant_ok: bool


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
                data=_empty_result(request, "blocked"),
                errors=validation_errors,
            )

        with connect(self.db_path) as conn:
            schema_errors = _schema_preflight_errors(conn)
            if schema_errors:
                return ServiceResult(
                    status="blocked",
                    request_id=ctx.request_id,
                    data=_empty_result(request, "blocked"),
                    errors=schema_errors,
                )

            account = _resolve_account(conn, request.account_key, request.account_id)
            if isinstance(account, ServiceError):
                return ServiceResult(
                    status="validation_failed",
                    request_id=ctx.request_id,
                    data=_empty_result(request, "blocked"),
                    errors=[account],
                )

            trades_count = _count_executed_trades(conn, account.id)
            open_positions_count = _count_open_positions(conn, account.id)
            due_exit_positions_count = _count_due_exit_positions(conn, account.id, request.as_of_date)
            open_blockers_count = _count_open_data_quality_blockers(conn)
            duplicate_open_positions = _duplicate_open_positions(conn, account.id)
            invariant_report = check_database(self.db_path)

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
                codes = ", ".join(violation.code for violation in invariant_report.violations)
                errors.append(
                    ServiceError(
                        code="DATABASE_INVARIANTS_FAILED",
                        message=f"Database invariant check failed: {codes}.",
                    )
                )

            warnings = _cash_equity_warnings(conn, account.id, request.as_of_date, open_positions_count)
            readiness = "blocked" if errors else "warning" if warnings else "pass"
            data = PaperReadinessResult(
                account_key=account.account_key,
                as_of_date=request.as_of_date,
                readiness=readiness,
                trades_count=trades_count,
                open_positions_count=open_positions_count,
                due_exit_positions_count=due_exit_positions_count,
                open_blockers_count=open_blockers_count,
                invariant_ok=invariant_report.ok,
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


def _empty_result(request: PaperReadinessRequest, readiness: str) -> PaperReadinessResult:
    return PaperReadinessResult(
        account_key=request.account_key or "",
        as_of_date=request.as_of_date,
        readiness=readiness,
        trades_count=0,
        open_positions_count=0,
        due_exit_positions_count=0,
        open_blockers_count=0,
        invariant_ok=False,
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
