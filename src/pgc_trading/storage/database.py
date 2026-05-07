"""SQLite database utilities."""

from __future__ import annotations

import re
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
    run_migrations(path)
    return path


def seed_account(config: AccountConfig | None = None, db_path: Path | None = None) -> int:
    account = config or AccountConfig()
    account_key = _account_key(account)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO portfolio_accounts
              (account_key, name, account_type, initial_cash, max_positions, position_sizing, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_key) DO UPDATE SET
              name = excluded.name,
              account_type = excluded.account_type,
              initial_cash = excluded.initial_cash,
              max_positions = excluded.max_positions,
              position_sizing = excluded.position_sizing,
              status = excluded.status
            """,
            (
                account_key,
                account.name,
                account.account_type,
                account.initial_cash,
                account.max_positions,
                account.position_sizing,
                account.status,
            ),
        )
        row = conn.execute("SELECT id FROM portfolio_accounts WHERE account_key = ?", (account_key,)).fetchone()
    return int(row["id"])


def _account_key(account: AccountConfig) -> str:
    if account.account_key:
        return str(account.account_key)

    slug = re.sub(r"[^a-z0-9]+", "-", account.name.lower()).strip("-")
    if not slug:
        return f"{account.account_type}-account"
    if slug == account.account_type or slug.startswith(f"{account.account_type}-"):
        return slug
    return f"{account.account_type}-{slug}"
