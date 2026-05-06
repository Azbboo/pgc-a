"""Freeze prototype SQLite tables before target-schema migrations."""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from pgc_trading.config import Paths
from pgc_trading.storage.migrators.legacy_detector import (
    SchemaState,
    inspect_schema,
)


LEGACY_TABLE_RENAMES: tuple[tuple[str, str], ...] = (
    ("raw_events", "legacy_raw_events"),
    ("market_bars", "legacy_market_bars"),
    ("strategy_runs", "legacy_strategy_runs"),
    ("signals", "legacy_signals"),
    ("input_snapshots", "legacy_input_snapshots"),
    ("agent_runs", "legacy_agent_runs"),
    ("agent_artifacts", "legacy_agent_artifacts"),
    ("agent_decisions", "legacy_agent_decisions"),
    ("portfolio_accounts", "legacy_portfolio_accounts"),
    ("trades", "legacy_trades"),
    ("trade_plans", "legacy_trade_plans"),
    ("positions", "legacy_positions"),
    ("exits", "legacy_exits"),
    ("equity_snapshots", "legacy_equity_snapshots"),
)


@dataclass(frozen=True)
class LegacyTableRename:
    source_table: str
    target_table: str
    row_count: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "source_table": self.source_table,
            "target_table": self.target_table,
            "row_count": self.row_count,
        }


@dataclass(frozen=True)
class LegacyIndexDrop:
    index_name: str
    table_name: str
    sql: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "index_name": self.index_name,
            "table_name": self.table_name,
            "sql": self.sql,
        }


@dataclass(frozen=True)
class LegacyFreezeBlocker:
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
class LegacyFreezePlan:
    schema_state: SchemaState
    renames: tuple[LegacyTableRename, ...] = ()
    index_drops: tuple[LegacyIndexDrop, ...] = ()
    blockers: tuple[LegacyFreezeBlocker, ...] = ()
    legacy_markers: tuple[str, ...] = ()
    target_markers: tuple[str, ...] = ()

    @property
    def can_apply(self) -> bool:
        return self.schema_state == SchemaState.LEGACY and bool(self.renames) and not self.blockers

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_state": self.schema_state.value,
            "can_apply": self.can_apply,
            "renames": [rename.to_dict() for rename in self.renames],
            "index_drops": [index_drop.to_dict() for index_drop in self.index_drops],
            "blockers": [blocker.to_dict() for blocker in self.blockers],
            "legacy_markers": list(self.legacy_markers),
            "target_markers": list(self.target_markers),
        }


@dataclass(frozen=True)
class LegacyFreezeResult:
    db_path: Path
    plan: LegacyFreezePlan
    dry_run: bool = True
    backup_path: Path | None = None
    applied_renames: tuple[LegacyTableRename, ...] = ()
    dropped_indexes: tuple[LegacyIndexDrop, ...] = ()

    @property
    def changed(self) -> bool:
        return not self.dry_run and bool(self.applied_renames)

    @property
    def blockers(self) -> tuple[LegacyFreezeBlocker, ...]:
        return self.plan.blockers

    def to_dict(self) -> dict[str, object]:
        return {
            "db_path": str(self.db_path),
            "dry_run": self.dry_run,
            "changed": self.changed,
            "backup_path": str(self.backup_path) if self.backup_path is not None else None,
            "plan": self.plan.to_dict(),
            "applied_renames": [rename.to_dict() for rename in self.applied_renames],
            "dropped_indexes": [index_drop.to_dict() for index_drop in self.dropped_indexes],
        }


class LegacyFreezeError(RuntimeError):
    """Raised when legacy freeze cannot be run safely."""


def plan_legacy_freeze(conn: sqlite3.Connection) -> LegacyFreezePlan:
    """Return the table/index changes needed to freeze a prototype schema."""
    detection = inspect_schema(conn)
    blockers: list[LegacyFreezeBlocker] = []

    if detection.state != SchemaState.LEGACY:
        blockers.append(
            LegacyFreezeBlocker(
                code=f"schema_state_{detection.state.value}",
                message="Legacy freeze only applies to a pure prototype schema.",
                details={
                    "schema_state": detection.state.value,
                    "legacy_markers": list(detection.legacy_markers),
                    "target_markers": list(detection.target_markers),
                },
            )
        )
        return LegacyFreezePlan(
            schema_state=detection.state,
            blockers=tuple(blockers),
            legacy_markers=detection.legacy_markers,
            target_markers=detection.target_markers,
        )

    renames: list[LegacyTableRename] = []
    for source_table, target_table in LEGACY_TABLE_RENAMES:
        if source_table not in detection.tables:
            continue
        if target_table in detection.tables:
            blockers.append(
                LegacyFreezeBlocker(
                    code="legacy_destination_exists",
                    message="Legacy freeze would overwrite an existing destination table.",
                    details={"source_table": source_table, "target_table": target_table},
                )
            )
            continue
        renames.append(
            LegacyTableRename(
                source_table=source_table,
                target_table=target_table,
                row_count=_row_count(conn, source_table),
            )
        )

    if not renames:
        blockers.append(
            LegacyFreezeBlocker(
                code="no_freezable_tables",
                message="No prototype tables were available to freeze.",
            )
        )

    index_drops = _legacy_index_drops(conn, tuple(rename.source_table for rename in renames))
    return LegacyFreezePlan(
        schema_state=detection.state,
        renames=tuple(renames),
        index_drops=tuple(index_drops),
        blockers=tuple(blockers),
        legacy_markers=detection.legacy_markers,
        target_markers=detection.target_markers,
    )


def freeze_legacy_tables(
    db_path: Path,
    dry_run: bool = True,
    *,
    backup_path: Path | None = None,
) -> LegacyFreezeResult:
    """Freeze prototype tables as ``legacy_*`` tables.

    Dry-runs open the database read-only. Non-dry-runs require an explicit
    existing backup path so callers prove the backup step already happened.
    """
    path = Path(db_path)
    if not path.exists():
        plan = LegacyFreezePlan(
            schema_state=SchemaState.EMPTY,
            blockers=(
                LegacyFreezeBlocker(
                    code="database_missing",
                    message="Database does not exist.",
                    details={"db_path": str(path)},
                ),
            ),
        )
        return LegacyFreezeResult(db_path=path, plan=plan, dry_run=dry_run, backup_path=backup_path)

    if dry_run:
        with _connect_read_only(path) as conn:
            plan = plan_legacy_freeze(conn)
        return LegacyFreezeResult(db_path=path, plan=plan, dry_run=True, backup_path=backup_path)

    backup = _validate_backup_path(path, backup_path)
    with _connect(path) as conn:
        plan = plan_legacy_freeze(conn)
        if not plan.can_apply:
            return LegacyFreezeResult(db_path=path, plan=plan, dry_run=False, backup_path=backup)

        try:
            conn.execute("BEGIN")
            for index_drop in plan.index_drops:
                conn.execute(f"DROP INDEX {_quote_identifier(index_drop.index_name)}")
            for rename in plan.renames:
                conn.execute(
                    f"ALTER TABLE {_quote_identifier(rename.source_table)} "
                    f"RENAME TO {_quote_identifier(rename.target_table)}"
                )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise LegacyFreezeError(f"Failed to freeze legacy tables: {exc}") from exc

    return LegacyFreezeResult(
        db_path=path,
        plan=plan,
        dry_run=False,
        backup_path=backup,
        applied_renames=plan.renames,
        dropped_indexes=plan.index_drops,
    )


def _legacy_index_drops(conn: sqlite3.Connection, table_names: tuple[str, ...]) -> list[LegacyIndexDrop]:
    if not table_names:
        return []

    placeholders = ", ".join("?" for _ in table_names)
    rows = conn.execute(
        f"""
        SELECT name, tbl_name, sql
        FROM sqlite_master
        WHERE type = 'index'
          AND name NOT LIKE 'sqlite_%'
          AND tbl_name IN ({placeholders})
        ORDER BY tbl_name, name
        """,
        table_names,
    ).fetchall()
    return [
        LegacyIndexDrop(
            index_name=str(_row_value(row, "name", 0)),
            table_name=str(_row_value(row, "tbl_name", 1)),
            sql=_optional_str(_row_value(row, "sql", 2)),
        )
        for row in rows
    ]


def _row_count(conn: sqlite3.Connection, table_name: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table_name)}").fetchone()
    return int(_row_value(row, "count", 0))


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _connect_read_only(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(db_path), safe='/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _validate_backup_path(db_path: Path, backup_path: Path | None) -> Path:
    if backup_path is None:
        raise LegacyFreezeError("Refusing to freeze legacy tables without an explicit backup_path.")

    backup = Path(backup_path)
    if not backup.exists():
        raise LegacyFreezeError(f"Backup path does not exist: {backup}")
    if not backup.is_file():
        raise LegacyFreezeError(f"Backup path is not a file: {backup}")
    if backup.resolve() == db_path.resolve():
        raise LegacyFreezeError("Backup path must not be the source database path.")
    return backup


def _row_value(row: object, key: str, index: int) -> object:
    if isinstance(row, sqlite3.Row) and key in row.keys():
        return row[key]
    return row[index]  # type: ignore[index]


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze prototype SQLite tables as legacy_* tables.")
    parser.add_argument("--db-path", type=Path, default=Paths().db_path)
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--backup-path", type=Path)
    args = parser.parse_args(argv)

    result = freeze_legacy_tables(
        args.db_path,
        dry_run=args.dry_run,
        backup_path=args.backup_path,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 1 if result.blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
