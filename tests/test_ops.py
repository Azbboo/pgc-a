from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pgc_trading.ops import build_release_tag, run_ops_health_check, run_ops_migration_step
from pgc_trading.storage.migrate import discover_migrations, run_migrations


class OpsTest(unittest.TestCase):
    def test_release_tag_normalizes_date_and_short_sha(self) -> None:
        tag = build_release_tag(date="2026-05-08", git_sha="abcdef123456")

        self.assertEqual(tag, "pgc-v0.1.0-20260508-gabcdef1")

    def test_health_reports_missing_database_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            result = run_ops_health_check(db_path)

            self.assertEqual(result.status, "missing_database")
            self.assertFalse(result.database_exists)
            self.assertEqual(result.pending_migrations, [migration.label for migration in discover_migrations()])
            self.assertFalse(db_path.exists())

    def test_health_passes_for_current_migrated_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            expected = [migration.label for migration in discover_migrations()]
            run_migrations(db_path)

            result = run_ops_health_check(db_path)

            self.assertEqual(result.status, "ok")
            self.assertTrue(result.ok)
            self.assertEqual(result.applied_migrations, expected)
            self.assertEqual(result.latest_migration, expected[-1])
            self.assertEqual(result.pending_migrations, [])

    def test_migration_step_can_backup_existing_database_before_migrating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            backup_dir = Path(tmp) / "backups"
            run_migrations(db_path)

            result = run_ops_migration_step(db_path, backup=True, backup_dir=backup_dir)

            self.assertIsNotNone(result.backup_path)
            assert result.backup_path is not None
            self.assertEqual(result.backup_path.parent, backup_dir)
            self.assertTrue(result.backup_path.exists())
            self.assertEqual(result.applied, [])
            self.assertTrue(result.skipped)

    def test_dry_run_migration_step_does_not_backup_or_create_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"

            result = run_ops_migration_step(db_path, dry_run=True, backup=True)

            self.assertIsNone(result.backup_path)
            self.assertTrue(result.dry_run)
            self.assertFalse(db_path.exists())


if __name__ == "__main__":
    unittest.main()
