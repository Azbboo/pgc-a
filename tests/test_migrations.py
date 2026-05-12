from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.storage.migrate import MigrationError, discover_migrations, run_migrations


class MigrationRunnerTest(unittest.TestCase):
    def test_empty_database_runs_migrations_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            expected = [migration.label for migration in discover_migrations()]
            result = run_migrations(db_path)
            self.assertEqual(result.applied, expected)
            self.assertFalse(result.skipped)

            second = run_migrations(db_path)
            self.assertFalse(second.applied)
            self.assertEqual(second.skipped, expected)

            with sqlite3.connect(db_path) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                self.assertIn("schema_migrations", tables)
                self.assertIn("data_quality_events", tables)
                self.assertIn("market_review_runs", tables)
                self.assertIn("decision_action_logs", tables)

    def test_dry_run_does_not_create_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            expected = [migration.label for migration in discover_migrations()]
            result = run_migrations(db_path, dry_run=True)
            self.assertEqual(result.applied, expected)
            self.assertTrue(result.dry_run)
            self.assertFalse(db_path.exists())

    def test_failed_migration_rolls_back_version_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            migrations_dir = Path(tmp) / "migrations"
            migrations_dir.mkdir()
            (migrations_dir / "001_valid.sql").write_text(
                "CREATE TABLE ok_table (id INTEGER PRIMARY KEY);\n",
                encoding="utf-8",
            )
            (migrations_dir / "002_bad.sql").write_text(
                "CREATE TABLE broken_table (\n",
                encoding="utf-8",
            )
            db_path = Path(tmp) / "pgc.db"

            with self.assertRaises(MigrationError):
                run_migrations(db_path, migrations_dir)

            with sqlite3.connect(db_path) as conn:
                versions = [
                    row[0]
                    for row in conn.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    ).fetchall()
                ]
                self.assertEqual(versions, ["001"])


if __name__ == "__main__":
    unittest.main()
