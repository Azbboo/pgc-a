"""Read-only SQLite schema state detector."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from urllib.parse import quote


class SchemaState(StrEnum):
    EMPTY = "empty"
    LEGACY = "legacy"
    TARGET = "target"
    MIXED = "mixed"


@dataclass(frozen=True)
class SchemaDetection:
    state: SchemaState
    tables: frozenset[str] = field(default_factory=frozenset)
    columns_by_table: dict[str, frozenset[str]] = field(default_factory=dict)
    legacy_markers: tuple[str, ...] = ()
    target_markers: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return self.state == SchemaState.EMPTY

    @property
    def has_legacy(self) -> bool:
        return bool(self.legacy_markers)

    @property
    def has_target(self) -> bool:
        return bool(self.target_markers)


def detect_schema_state(conn: sqlite3.Connection) -> SchemaState:
    return inspect_schema(conn).state


def detect_database_state(db_path: Path) -> SchemaDetection:
    if not db_path.exists():
        return SchemaDetection(state=SchemaState.EMPTY)

    uri = f"file:{quote(str(db_path), safe='/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.row_factory = sqlite3.Row
        return inspect_schema(conn)
    finally:
        conn.close()


def inspect_schema(conn: sqlite3.Connection) -> SchemaDetection:
    tables = _table_names(conn)
    columns_by_table = {table: _column_names(conn, table) for table in tables}

    legacy_markers = _legacy_markers(tables, columns_by_table)
    target_markers = _target_markers(tables, columns_by_table)
    state = _classify(legacy_markers, target_markers)

    return SchemaDetection(
        state=state,
        tables=frozenset(tables),
        columns_by_table=columns_by_table,
        legacy_markers=tuple(legacy_markers),
        target_markers=tuple(target_markers),
    )


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    return {str(row["name"] if isinstance(row, sqlite3.Row) else row[0]) for row in rows}


def _column_names(conn: sqlite3.Connection, table: str) -> frozenset[str]:
    rows = conn.execute(f"PRAGMA table_info({_quote_identifier(table)})").fetchall()
    return frozenset(str(row["name"] if isinstance(row, sqlite3.Row) else row[1]) for row in rows)


def _legacy_markers(tables: set[str], columns_by_table: dict[str, frozenset[str]]) -> list[str]:
    markers: list[str] = []

    if _has_table_without_column(tables, columns_by_table, "raw_events", "import_batch_id"):
        markers.append("raw_events_missing_import_batch_id")
    if _has_table_without_column(tables, columns_by_table, "market_bars", "fetch_run_id"):
        markers.append("market_bars_missing_fetch_run_id")
    if "signals" in tables:
        markers.append("signals_table")
    trade_columns = columns_by_table.get("trades", frozenset())
    if "price" in trade_columns and "executed_price" not in trade_columns:
        markers.append("trades_price_missing_executed_price")
    if _has_table_without_column(tables, columns_by_table, "positions", "entry_trade_id"):
        markers.append("positions_missing_entry_trade_id")
    if "exits" in tables:
        markers.append("exits_table")

    return markers


def _target_markers(tables: set[str], columns_by_table: dict[str, frozenset[str]]) -> list[str]:
    markers: list[str] = []

    if _has_table_with_column(tables, columns_by_table, "raw_events", "import_batch_id"):
        markers.append("raw_events_import_batch_id")
    if _has_table_with_column(tables, columns_by_table, "market_bars", "fetch_run_id"):
        markers.append("market_bars_fetch_run_id")
    if "strategy_signals" in tables:
        markers.append("strategy_signals_table")
    if "exit_decisions" in tables:
        markers.append("exit_decisions_table")

    return markers


def _classify(legacy_markers: list[str], target_markers: list[str]) -> SchemaState:
    has_legacy = bool(legacy_markers)
    has_target = bool(target_markers)

    if has_legacy and has_target:
        return SchemaState.MIXED
    if has_legacy:
        return SchemaState.LEGACY
    if has_target:
        return SchemaState.TARGET
    return SchemaState.EMPTY


def _has_table_with_column(
    tables: set[str],
    columns_by_table: dict[str, frozenset[str]],
    table: str,
    column: str,
) -> bool:
    return table in tables and column in columns_by_table.get(table, frozenset())


def _has_table_without_column(
    tables: set[str],
    columns_by_table: dict[str, frozenset[str]],
    table: str,
    column: str,
) -> bool:
    return table in tables and column not in columns_by_table.get(table, frozenset())


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'

