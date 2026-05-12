from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pgc_trading.ops import (
    build_release_tag,
    run_market_review_parity_check,
    run_ops_health_check,
    run_ops_migration_step,
)
from pgc_trading.storage.migrate import discover_migrations, run_migrations
from pgc_trading.storage.database import connect


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

    def test_market_review_parity_detects_matching_and_mismatched_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_db = Path(tmp) / "local.db"
            remote_db = Path(tmp) / "remote.db"
            for db_path in (local_db, remote_db):
                run_migrations(db_path)
                _seed_market_review_rows(db_path)

            matching = run_market_review_parity_check(local_db, remote_db, as_of_date="20260508")
            self.assertEqual(matching.status, "match")
            self.assertTrue(matching.ok)
            self.assertTrue(all(table.status == "match" for table in matching.tables))

            with connect(remote_db) as conn:
                conn.execute(
                    """
                    INSERT INTO strategy_hypotheses
                      (as_of_date, hypothesis_type, title, rationale, evidence_json, proposed_change_json, status)
                    VALUES ('20260508', 'sector_rotation', 'Extra remote hypothesis', 'Remote only.', '{}', '{}', 'proposed')
                    """
                )

            mismatched = run_market_review_parity_check(local_db, remote_db, as_of_date="20260508")
            table_status = {table.table: table.status for table in mismatched.tables}
            self.assertEqual(mismatched.status, "mismatch")
            self.assertEqual(table_status["strategy_hypotheses"], "mismatch")


def _seed_market_review_rows(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO market_review_runs
              (as_of_date, status, provider_manifest_json, coverage_json, summary_json)
            VALUES ('20260508', 'completed', '{}', '{}', '{}')
            """
        )
        run_id = int(conn.execute("SELECT id FROM market_review_runs WHERE as_of_date = '20260508'").fetchone()["id"])
        conn.execute(
            """
            INSERT INTO sector_daily_snapshots
              (market_review_run_id, as_of_date, sector_code, sector_name, provider, rank_overall, leader_count)
            VALUES (?, '20260508', 'AI', 'AI', 'reviewed_cache', 1, 3)
            """,
            (run_id,),
        )
        conn.execute(
            """
            INSERT INTO market_external_items
              (as_of_date, scope_type, scope_key, item_type, provider, title, summary,
               sentiment, importance, published_date, source_hash)
            VALUES
              ('20260508', 'market', 'A_SHARE', 'news', 'reviewed_cache',
               'Market note', 'Reviewed summary.', 'neutral', 'medium', '20260508', 'hash-market')
            """
        )
        conn.execute(
            """
            INSERT INTO strategy_hypotheses
              (as_of_date, hypothesis_type, title, rationale, evidence_json, proposed_change_json, status)
            VALUES ('20260508', 'breadth', 'Breadth hypothesis', 'Reviewed.', '{}', '{}', 'testing')
            """
        )


if __name__ == "__main__":
    unittest.main()
