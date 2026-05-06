"""SQLite database utilities."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pgc_trading.config import AccountConfig, Paths
from pgc_trading.storage.migrate import run_migrations


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or Paths().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | None = None) -> Path:
    path = db_path or Paths().db_path
    with connect(path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _migrate(conn)
    run_migrations(path)
    return path


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row["name"] == column for row in conn.execute(f"PRAGMA table_info({table})").fetchall())


def _migrate(conn: sqlite3.Connection) -> None:
    if not _has_column(conn, "trades", "agent_decision_id"):
        conn.execute("ALTER TABLE trades ADD COLUMN agent_decision_id INTEGER REFERENCES agent_decisions(id)")


def seed_account(config: AccountConfig | None = None, db_path: Path | None = None) -> int:
    account = config or AccountConfig()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO portfolio_accounts
              (name, account_type, initial_cash, max_positions, position_sizing)
            VALUES (?, 'paper', ?, ?, ?)
            """,
            (account.name, account.initial_cash, account.max_positions, account.position_sizing),
        )
        row = conn.execute("SELECT id FROM portfolio_accounts WHERE name = ?", (account.name,)).fetchone()
    return int(row["id"])
