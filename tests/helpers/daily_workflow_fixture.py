from __future__ import annotations

import sqlite3
from pathlib import Path

from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data


PAPER_ACCOUNT_KEY = "paper-main"
AS_OF_DATE = "20260504"
ENTRY_DATE = "20260427"
BUY_DATE = "20260505"


def migrated_seeded_daily_close_db(tmp: str | Path) -> Path:
    db_path = Path(tmp) / "pgc.db"
    run_migrations(db_path)
    seed_reference_data(db_path)
    return db_path


def insert_open_calendar(conn: sqlite3.Connection) -> None:
    conn.executemany(
        """
        INSERT INTO trade_calendar (exchange, cal_date, is_open, pretrade_date)
        VALUES ('SSE', ?, 1, ?)
        """,
        [
            (AS_OF_DATE, "20260501"),
            (BUY_DATE, AS_OF_DATE),
            ("20260506", BUY_DATE),
        ],
    )


def insert_contracting_pullback_case(
    conn: sqlite3.Connection,
    ts_code: str,
    name: str,
    price_scale: float = 1.0,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO raw_events
          (ts_code, code, name, entry_date, entry_time, entry_price)
        VALUES
          (?, substr(?, 1, 6), ?, ?, '15:00', ?)
        """,
        (ts_code, ts_code, name, ENTRY_DATE, 10.0 * price_scale),
    )
    raw_event_id = int(cursor.lastrowid)
    bars = [
        ("20260424", 9.6, 9.8, 9.5, 9.7, 950.0),
        (ENTRY_DATE, 10.0, 10.2, 9.9, 10.0, 1000.0),
        ("20260428", 10.8, 11.2, 10.7, 11.0, 1200.0),
        ("20260429", 10.6, 10.7, 10.4, 10.5, 1000.0),
        ("20260430", 10.3, 10.4, 9.95, 10.0, 800.0),
        ("20260501", 9.8, 9.85, 9.55, 9.65, 700.0),
        (AS_OF_DATE, 9.7, 10.0, 9.6, 9.9, 900.0),
    ]
    for trade_date, open_price, high, low, close, amount in bars:
        insert_market_bar(
            conn,
            ts_code=ts_code,
            trade_date=trade_date,
            open_price=open_price * price_scale,
            high=high * price_scale,
            low=low * price_scale,
            close=close * price_scale,
            amount=amount,
        )
    return raw_event_id


def insert_market_bar(
    conn: sqlite3.Connection,
    ts_code: str,
    trade_date: str,
    open_price: float,
    high: float,
    low: float,
    close: float,
    amount: float,
) -> None:
    conn.execute(
        """
        INSERT INTO market_bars
          (
            ts_code,
            trade_date,
            open,
            high,
            low,
            close,
            vol,
            amount,
            adj_open,
            adj_high,
            adj_low,
            adj_close
          )
        VALUES
          (?, ?, ?, ?, ?, ?, 100000, ?, ?, ?, ?, ?)
        """,
        (
            ts_code,
            trade_date,
            open_price,
            high,
            low,
            close,
            amount,
            open_price,
            high,
            low,
            close,
        ),
    )


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
