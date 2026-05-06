"""Reusable SQLite invariant checks for the PGC storage schema."""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from pgc_trading.config import Paths
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

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
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
