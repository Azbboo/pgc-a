"""Reusable SQLite invariant checks for the PGC storage schema."""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from pgc_trading.config import Paths
from pgc_trading.portfolio.state_machines import OPEN_POSITION_STATUSES
from pgc_trading.storage.database import connect


RAW_EVENTS_FORBIDDEN_COLUMNS = {
    "bull_prob",
    "bull_reason",
    "latest_ret",
    "max_high",
    "status",
}

STRATEGY_SIGNALS_FORBIDDEN_COLUMNS = {
    "account_id",
    "agent_action",
    "agent_confidence",
    "agent_decision_id",
    "agent_reason",
    "agent_run_id",
    "agent_risk_level",
    "agent_summary",
    "order_id",
    "position_id",
    "trade_id",
    "trade_plan_id",
}

ACCOUNT_SCOPED_TABLES = {
    "trade_plans",
    "trades",
    "positions",
    "exit_decisions",
    "equity_snapshots",
}


@dataclass(frozen=True)
class InvariantViolation:
    code: str
    message: str
    details: dict[str, object] = field(default_factory=dict)
    severity: str = "blocker"

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class InvariantReport:
    db_path: Path | None
    violations: list[InvariantViolation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, object]:
        return {
            "db_path": str(self.db_path) if self.db_path is not None else None,
            "ok": self.ok,
            "violations": [violation.to_dict() for violation in self.violations],
        }


class InvariantCheckError(RuntimeError):
    """Raised when one or more storage invariants fail."""

    def __init__(self, report: InvariantReport):
        self.report = report
        codes = ", ".join(violation.code for violation in report.violations)
        super().__init__(f"Storage invariant check failed: {codes}")


def check_database(db_path: Path | None = None) -> InvariantReport:
    """Run invariant checks against a database path."""
    path = db_path or Paths().db_path
    with connect(path) as conn:
        return check_connection(conn, db_path=path)


def check_connection(conn: sqlite3.Connection, db_path: Path | None = None) -> InvariantReport:
    """Run invariant checks against an existing SQLite connection."""
    previous_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        violations: list[InvariantViolation] = []

        violations.extend(_check_integrity(conn))
        violations.extend(_check_foreign_keys(conn))
        violations.extend(_check_forbidden_columns(conn, "raw_events", RAW_EVENTS_FORBIDDEN_COLUMNS))
        violations.extend(
            _check_forbidden_columns(
                conn,
                "strategy_signals",
                STRATEGY_SIGNALS_FORBIDDEN_COLUMNS,
            )
        )
        violations.extend(_check_positions_entry_trade_contract(conn))
        violations.extend(_check_position_entry_trade_account_match(conn))
        violations.extend(_check_executed_trade_amounts(conn))
        violations.extend(_check_position_entry_trade_facts(conn))
        violations.extend(_check_executed_buy_plan_status(conn))
        violations.extend(_check_stale_active_buy_plans(conn))
        violations.extend(_check_latest_equity_snapshots(conn))
        violations.extend(_check_no_live_model_trades(conn))
        violations.extend(_check_daily_pick_uniqueness(conn))
        violations.extend(_check_account_scoped_tables(conn))
    finally:
        conn.row_factory = previous_row_factory

    return InvariantReport(db_path=db_path, violations=violations)


def assert_database_invariants(db_path: Path | None = None) -> InvariantReport:
    """Run invariant checks and raise when any invariant fails."""
    report = check_database(db_path)
    if not report.ok:
        raise InvariantCheckError(report)
    return report


def assert_connection_invariants(
    conn: sqlite3.Connection,
    db_path: Path | None = None,
) -> InvariantReport:
    """Run invariant checks on an existing connection and raise on failure."""
    report = check_connection(conn, db_path=db_path)
    if not report.ok:
        raise InvariantCheckError(report)
    return report


def run_invariant_checks(db_path: Path | None = None) -> InvariantReport:
    """Compatibility wrapper for callers that treat checks as a CI run."""
    return check_database(db_path)


def run_connection_invariant_checks(
    conn: sqlite3.Connection,
    db_path: Path | None = None,
) -> InvariantReport:
    """Compatibility wrapper for checking an already-open connection."""
    return check_connection(conn, db_path=db_path)


def _check_integrity(conn: sqlite3.Connection) -> list[InvariantViolation]:
    rows = conn.execute("PRAGMA integrity_check").fetchall()
    messages = [_first_column(row) for row in rows]
    if messages == ["ok"]:
        return []
    return [
        InvariantViolation(
            code="sqlite_integrity_check_failed",
            message="PRAGMA integrity_check did not return ok.",
            details={"messages": messages},
        )
    ]


def _check_foreign_keys(conn: sqlite3.Connection) -> list[InvariantViolation]:
    rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    if not rows:
        return []
    return [
        InvariantViolation(
            code="foreign_key_violation",
            message="PRAGMA foreign_key_check returned rows.",
            details={"rows": [_row_to_dict(row) for row in rows]},
        )
    ]


def _check_forbidden_columns(
    conn: sqlite3.Connection,
    table_name: str,
    forbidden_columns: Iterable[str],
) -> list[InvariantViolation]:
    if not _table_exists(conn, table_name):
        return [
            InvariantViolation(
                code=f"{table_name}_missing",
                message=f"Required table {table_name} is missing.",
                details={"table": table_name},
            )
        ]

    columns = set(_columns(conn, table_name))
    forbidden = sorted(columns & set(forbidden_columns))
    if not forbidden:
        return []

    return [
        InvariantViolation(
            code=f"{table_name}_forbidden_columns",
            message=f"{table_name} contains forbidden boundary columns.",
            details={"table": table_name, "columns": forbidden},
        )
    ]


def _check_positions_entry_trade_contract(conn: sqlite3.Connection) -> list[InvariantViolation]:
    if not _table_exists(conn, "positions"):
        return [
            InvariantViolation(
                code="positions_missing",
                message="Required table positions is missing.",
                details={"table": "positions"},
            )
        ]

    column_meta = _column_meta(conn, "positions")
    entry_trade = column_meta.get("entry_trade_id")
    if entry_trade is None:
        return [
            InvariantViolation(
                code="positions_entry_trade_id_missing",
                message="positions.entry_trade_id is required.",
                details={"table": "positions", "column": "entry_trade_id"},
            )
        ]

    violations: list[InvariantViolation] = []
    if not entry_trade["notnull"]:
        violations.append(
            InvariantViolation(
                code="positions_entry_trade_id_nullable",
                message="positions.entry_trade_id must be NOT NULL by schema.",
                details={"table": "positions", "column": "entry_trade_id"},
            )
        )

    if _table_exists(conn, "trades"):
        rows = conn.execute(
            """
            SELECT p.id
            FROM positions p
            LEFT JOIN trades t ON t.id = p.entry_trade_id
            WHERE t.id IS NULL
            """
        ).fetchall()
        if rows:
            violations.append(
                InvariantViolation(
                    code="positions_missing_entry_trade",
                    message="Every position must reference an existing entry trade.",
                    details={"position_ids": [_first_column(row) for row in rows]},
                )
            )

    return violations


def _check_position_entry_trade_account_match(conn: sqlite3.Connection) -> list[InvariantViolation]:
    if not (_table_exists(conn, "positions") and _table_exists(conn, "trades")):
        return []

    rows = conn.execute(
        """
        SELECT p.id AS position_id,
               p.account_id AS position_account_id,
               t.account_id AS trade_account_id
        FROM positions p
        JOIN trades t ON t.id = p.entry_trade_id
        WHERE p.account_id <> t.account_id
        """
    ).fetchall()
    if not rows:
        return []

    return [
        InvariantViolation(
            code="position_entry_trade_account_mismatch",
            message="Position and entry trade must belong to the same account.",
            details={"rows": [_row_to_dict(row) for row in rows]},
        )
    ]


def _check_executed_trade_amounts(conn: sqlite3.Connection) -> list[InvariantViolation]:
    if not _table_exists(conn, "trades"):
        return []

    rows = conn.execute(
        """
        SELECT id AS trade_id,
               account_id,
               side,
               executed_price,
               shares,
               amount,
               ROUND(executed_price * shares, 6) AS expected_amount
        FROM trades
        WHERE status = 'executed'
          AND executed_price IS NOT NULL
          AND shares IS NOT NULL
          AND amount IS NOT NULL
          AND ABS(amount - (executed_price * shares)) > 0.01
        ORDER BY id
        """
    ).fetchall()
    if not rows:
        return []

    return [
        InvariantViolation(
            code="TRADE_AMOUNT_MISMATCH",
            message="Executed trades must store amount as executed_price * shares.",
            details={"rows": [_row_to_dict(row) for row in rows]},
        )
    ]


def _check_position_entry_trade_facts(conn: sqlite3.Connection) -> list[InvariantViolation]:
    if not (_table_exists(conn, "positions") and _table_exists(conn, "trades")):
        return []

    violations: list[InvariantViolation] = []
    entry_rows = conn.execute(
        """
        SELECT p.id AS position_id,
               p.account_id,
               p.entry_trade_id AS trade_id,
               t.side AS trade_side,
               t.status AS trade_status
        FROM positions p
        JOIN trades t ON t.id = p.entry_trade_id
        WHERE t.side <> 'buy'
           OR t.status <> 'executed'
        ORDER BY p.id
        """
    ).fetchall()
    if entry_rows:
        violations.append(
            InvariantViolation(
                code="POSITION_ENTRY_TRADE_MISMATCH",
                message="positions.entry_trade_id must point to an executed buy trade.",
                details={"rows": [_row_to_dict(row) for row in entry_rows]},
            )
        )

    fact_rows = conn.execute(
        """
        SELECT p.id AS position_id,
               p.account_id,
               p.entry_trade_id AS trade_id,
               p.buy_price,
               t.executed_price AS expected_buy_price,
               p.shares,
               t.shares AS expected_shares,
               p.cost,
               ROUND((t.executed_price * t.shares) + COALESCE(t.fee, 0) + COALESCE(t.tax, 0), 6) AS expected_cost
        FROM positions p
        JOIN trades t ON t.id = p.entry_trade_id
        WHERE t.side = 'buy'
          AND t.status = 'executed'
          AND t.executed_price IS NOT NULL
          AND t.shares IS NOT NULL
          AND t.amount IS NOT NULL
          AND (
            ABS(p.buy_price - t.executed_price) > 0.01
            OR p.shares <> t.shares
            OR ABS(p.cost - ((t.executed_price * t.shares) + COALESCE(t.fee, 0) + COALESCE(t.tax, 0))) > 0.01
          )
        ORDER BY p.id
        """
    ).fetchall()
    if fact_rows:
        violations.append(
            InvariantViolation(
                code="POSITION_ENTRY_TRADE_FACT_MISMATCH",
                message="Position entry facts must match the executed buy trade.",
                details={"rows": [_row_to_dict(row) for row in fact_rows]},
            )
        )

    return violations


def _check_executed_buy_plan_status(conn: sqlite3.Connection) -> list[InvariantViolation]:
    if not (_table_exists(conn, "trades") and _table_exists(conn, "trade_plans")):
        return []

    rows = conn.execute(
        """
        SELECT t.id AS trade_id,
               t.trade_plan_id,
               p.status AS trade_plan_status,
               t.account_id,
               t.executed_date
        FROM trades t
        JOIN trade_plans p ON p.id = t.trade_plan_id
        WHERE t.side = 'buy'
          AND t.status = 'executed'
          AND p.status <> 'executed'
        ORDER BY t.id
        """
    ).fetchall()
    if not rows:
        return []

    return [
        InvariantViolation(
            code="TRADE_PLAN_NOT_EXECUTED_FOR_BUY",
            message="Executed buy trades must point to an executed trade plan.",
            details={"rows": [_row_to_dict(row) for row in rows]},
        )
    ]


def _check_stale_active_buy_plans(conn: sqlite3.Connection) -> list[InvariantViolation]:
    if not (_table_exists(conn, "trade_plans") and _table_exists(conn, "trades")):
        return []

    rows = conn.execute(
        """
        SELECT p.id AS trade_plan_id,
               p.account_id,
               p.signal_id,
               p.planned_trade_date,
               t.id AS trade_id,
               t.executed_date
        FROM trade_plans p
        JOIN trades t
          ON t.account_id = p.account_id
         AND t.signal_id IS p.signal_id
         AND t.side = 'buy'
         AND t.status = 'executed'
        WHERE p.action = 'buy_next_open'
          AND p.status = 'active'
          AND p.planned_trade_date IS NOT NULL
          AND t.executed_date IS NOT NULL
          AND p.planned_trade_date <= t.executed_date
        ORDER BY p.id
        """
    ).fetchall()
    if not rows:
        return []

    return [
        InvariantViolation(
            code="ACTIVE_BUY_PLAN_WITH_EXECUTED_TRADE",
            message="Active buy plans may not remain open after a matching buy trade is executed.",
            details={"rows": [_row_to_dict(row) for row in rows]},
        )
    ]


def _check_latest_equity_snapshots(conn: sqlite3.Connection) -> list[InvariantViolation]:
    if not (_table_exists(conn, "equity_snapshots") and _table_exists(conn, "positions")):
        return []

    latest_rows = conn.execute(
        """
        WITH latest AS (
          SELECT account_id, MAX(as_of_date) AS as_of_date
          FROM equity_snapshots
          GROUP BY account_id
        ),
        latest_ids AS (
          SELECT s.account_id, s.as_of_date, MAX(s.id) AS id
          FROM equity_snapshots s
          JOIN latest l
            ON l.account_id = s.account_id
           AND l.as_of_date = s.as_of_date
          GROUP BY s.account_id, s.as_of_date
        )
        SELECT s.id AS equity_snapshot_id,
               s.account_id,
               s.as_of_date,
               s.cash,
               s.market_value,
               s.total_equity,
               ROUND(s.cash + s.market_value, 6) AS expected_total_equity
        FROM equity_snapshots s
        JOIN latest_ids l ON l.id = s.id
        WHERE ABS((s.cash + s.market_value) - s.total_equity) > 0.01
        ORDER BY s.account_id
        """
    ).fetchall()

    violations: list[InvariantViolation] = []
    if latest_rows:
        violations.append(
            InvariantViolation(
                code="EQUITY_SNAPSHOT_TOTAL_MISMATCH",
                message="Latest equity snapshots must satisfy cash + market_value = total_equity.",
                details={"rows": [_row_to_dict(row) for row in latest_rows]},
            )
        )

    open_statuses = tuple(sorted(OPEN_POSITION_STATUSES))
    market_rows = conn.execute(
        f"""
        WITH latest AS (
          SELECT account_id, MAX(as_of_date) AS as_of_date
          FROM equity_snapshots
          GROUP BY account_id
        ),
        latest_ids AS (
          SELECT s.account_id, s.as_of_date, MAX(s.id) AS id
          FROM equity_snapshots s
          JOIN latest l
            ON l.account_id = s.account_id
           AND l.as_of_date = s.as_of_date
          GROUP BY s.account_id, s.as_of_date
        ),
        open_costs AS (
          SELECT account_id, COALESCE(SUM(cost), 0) AS expected_market_value
          FROM positions
          WHERE status IN ({_placeholders(open_statuses)})
          GROUP BY account_id
        )
        SELECT s.id AS equity_snapshot_id,
               s.account_id,
               s.as_of_date,
               s.market_value,
               COALESCE(o.expected_market_value, 0) AS expected_market_value
        FROM equity_snapshots s
        JOIN latest_ids l ON l.id = s.id
        LEFT JOIN open_costs o ON o.account_id = s.account_id
        WHERE ABS(s.market_value - COALESCE(o.expected_market_value, 0)) > 0.01
        ORDER BY s.account_id
        """,
        open_statuses,
    ).fetchall()
    if market_rows:
        violations.append(
            InvariantViolation(
                code="EQUITY_SNAPSHOT_MARKET_VALUE_MISMATCH",
                message="Latest equity snapshot market_value must equal open position cost under paper accounting.",
                details={"rows": [_row_to_dict(row) for row in market_rows]},
            )
        )

    return violations


def _check_no_live_model_trades(conn: sqlite3.Connection) -> list[InvariantViolation]:
    if not (_table_exists(conn, "trades") and _table_exists(conn, "portfolio_accounts")):
        return []

    rows = conn.execute(
        """
        SELECT t.id, t.account_id
        FROM trades t
        JOIN portfolio_accounts a ON a.id = t.account_id
        WHERE t.source = 'model'
          AND a.account_type = 'live'
        """
    ).fetchall()
    if not rows:
        return []

    return [
        InvariantViolation(
            code="live_trade_model_source",
            message="Live account trades may not use source='model'.",
            details={"rows": [_row_to_dict(row) for row in rows]},
        )
    ]


def _check_daily_pick_uniqueness(conn: sqlite3.Connection) -> list[InvariantViolation]:
    if not _table_exists(conn, "daily_picks"):
        return [
            InvariantViolation(
                code="daily_picks_missing",
                message="Required table daily_picks is missing.",
                details={"table": "daily_picks"},
            )
        ]

    rows = conn.execute(
        """
        SELECT strategy_run_id, review_date, COUNT(*) AS count
        FROM daily_picks
        GROUP BY strategy_run_id, review_date
        HAVING count > 1
        """
    ).fetchall()
    if not rows:
        return []

    return [
        InvariantViolation(
            code="daily_picks_duplicate_strategy_review_date",
            message="Each strategy run may have at most one daily pick per review date.",
            details={"rows": [_row_to_dict(row) for row in rows]},
        )
    ]


def _check_account_scoped_tables(conn: sqlite3.Connection) -> list[InvariantViolation]:
    violations: list[InvariantViolation] = []
    for table_name in sorted(ACCOUNT_SCOPED_TABLES):
        if not _table_exists(conn, table_name):
            violations.append(
                InvariantViolation(
                    code=f"{table_name}_missing",
                    message=f"Required account-scoped table {table_name} is missing.",
                    details={"table": table_name},
                )
            )
            continue

        column_meta = _column_meta(conn, table_name)
        account_id = column_meta.get("account_id")
        if account_id is None:
            violations.append(
                InvariantViolation(
                    code=f"{table_name}_account_id_missing",
                    message=f"{table_name} must include account_id for account isolation.",
                    details={"table": table_name},
                )
            )
        elif not account_id["notnull"]:
            violations.append(
                InvariantViolation(
                    code=f"{table_name}_account_id_nullable",
                    message=f"{table_name}.account_id must be NOT NULL for account isolation.",
                    details={"table": table_name, "column": "account_id"},
                )
            )

        if account_id is not None and not _has_account_leading_index(conn, table_name):
            violations.append(
                InvariantViolation(
                    code=f"{table_name}_account_id_index_missing",
                    message=f"{table_name} needs an account_id-leading index for account-scoped queries.",
                    details={"table": table_name, "column": "account_id"},
                )
            )

    return violations


def _has_account_leading_index(conn: sqlite3.Connection, table_name: str) -> bool:
    for index in conn.execute(f"PRAGMA index_list({table_name})").fetchall():
        index_name = str(_row_value(index, "name", 1))
        columns = [
            _row_value(row, "name", 2)
            for row in conn.execute(f"PRAGMA index_info({index_name})").fetchall()
        ]
        if columns and columns[0] == "account_id":
            return True
    return False


def _placeholders(values: Iterable[object]) -> str:
    return ", ".join("?" for _ in values)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    return [
        str(_row_value(row, "name", 1))
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    ]


def _column_meta(conn: sqlite3.Connection, table_name: str) -> dict[str, dict[str, object]]:
    return {
        str(_row_value(row, "name", 1)): {
            "notnull": bool(_row_value(row, "notnull", 3)),
            "type": _row_value(row, "type", 2),
        }
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _row_to_dict(row: sqlite3.Row) -> dict[str, object]:
    if isinstance(row, sqlite3.Row):
        return {key: row[key] for key in row.keys()}
    return {str(index): value for index, value in enumerate(row)}


def _first_column(row: sqlite3.Row) -> object:
    if isinstance(row, sqlite3.Row):
        return row[0]
    return row[0]


def _row_value(row: sqlite3.Row, key: str, index: int) -> object:
    if isinstance(row, sqlite3.Row):
        return row[key]
    return row[index]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run PGC storage invariant checks.")
    parser.add_argument("--db-path", type=Path, default=Paths().db_path)
    args = parser.parse_args(argv)

    report = check_database(args.db_path)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
