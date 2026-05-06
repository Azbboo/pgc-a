from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.storage.database import SCHEMA_PATH
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.migrators.backup import backup_database
from pgc_trading.storage.migrators.legacy_detector import SchemaState
from pgc_trading.storage.migrators.legacy_freezer import (
    LEGACY_TABLE_RENAMES,
    LegacyFreezeError,
    freeze_legacy_tables,
    plan_legacy_freeze,
)


class LegacyFreezerTest(unittest.TestCase):
    def test_current_schema_produces_table_and_index_plan(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

            plan = plan_legacy_freeze(conn)

        self.assertEqual(plan.schema_state, SchemaState.LEGACY)
        self.assertTrue(plan.can_apply)
        self.assertFalse(plan.blockers)
        self.assertEqual(
            [(rename.source_table, rename.target_table) for rename in plan.renames],
            list(LEGACY_TABLE_RENAMES),
        )
        self.assertIn(
            "idx_positions_account_status",
            {index_drop.index_name for index_drop in plan.index_drops},
        )
        self.assertIn(
            "idx_agent_runs_signal",
            {index_drop.index_name for index_drop in plan.index_drops},
        )

    def test_dry_run_does_not_rename_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            _create_current_schema(db_path)

            result = freeze_legacy_tables(db_path)

            self.assertTrue(result.dry_run)
            self.assertFalse(result.changed)
            self.assertTrue(result.plan.can_apply)
            with sqlite3.connect(db_path) as conn:
                self.assertTrue(_table_exists(conn, "raw_events"))
                self.assertFalse(_table_exists(conn, "legacy_raw_events"))

    def test_existing_legacy_destination_produces_blocker(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            conn.executescript(
                """
                CREATE TABLE raw_events (
                  id INTEGER PRIMARY KEY,
                  ts_code TEXT NOT NULL
                );
                CREATE TABLE legacy_raw_events (
                  id INTEGER PRIMARY KEY,
                  ts_code TEXT NOT NULL
                );
                """
            )

            plan = plan_legacy_freeze(conn)

        self.assertFalse(plan.can_apply)
        self.assertIn("legacy_destination_exists", {blocker.code for blocker in plan.blockers})

    def test_mixed_schema_refuses_to_freeze(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            conn.executescript(
                """
                CREATE TABLE signals (
                  id INTEGER PRIMARY KEY
                );
                CREATE TABLE strategy_signals (
                  id INTEGER PRIMARY KEY
                );
                """
            )

            plan = plan_legacy_freeze(conn)

        self.assertEqual(plan.schema_state, SchemaState.MIXED)
        self.assertFalse(plan.can_apply)
        self.assertIn("schema_state_mixed", {blocker.code for blocker in plan.blockers})

    def test_non_dry_run_requires_explicit_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            _create_current_schema(db_path)

            with self.assertRaisesRegex(LegacyFreezeError, "backup_path"):
                freeze_legacy_tables(db_path, dry_run=False)

    def test_freeze_then_migrations_create_target_tables_without_index_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            _create_current_schema(db_path)
            backup_path = backup_database(db_path, backup_dir=Path(tmp) / "backups")

            freeze_result = freeze_legacy_tables(db_path, dry_run=False, backup_path=backup_path)
            migration_result = run_migrations(db_path)

            self.assertTrue(freeze_result.changed)
            self.assertTrue(migration_result.changed)
            with sqlite3.connect(db_path) as conn:
                self.assertTrue(_table_exists(conn, "legacy_raw_events"))
                self.assertTrue(_table_exists(conn, "raw_events"))
                self.assertTrue(_index_belongs_to(conn, "idx_positions_account_status", "positions"))
                self.assertTrue(_index_belongs_to(conn, "idx_agent_runs_signal", "agent_runs"))


def _create_current_schema(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _index_belongs_to(conn: sqlite3.Connection, index_name: str, table_name: str) -> bool:
    row = conn.execute(
        "SELECT tbl_name FROM sqlite_master WHERE type = 'index' AND name = ?",
        (index_name,),
    ).fetchone()
    return row is not None and row[0] == table_name


if __name__ == "__main__":
    unittest.main()
