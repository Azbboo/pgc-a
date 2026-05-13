from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from pgc_trading.ops import (
    build_release_tag,
    run_daily_ops_preflight,
    run_market_review_parity_check,
    run_ops_health_check,
    run_ops_migration_step,
    run_shadow_observation_scorecard,
    run_shadow_strategy_snapshot,
)
from pgc_trading.storage.migrate import discover_migrations, run_migrations
from pgc_trading.storage.database import connect
from pgc_trading.storage.seed import seed_reference_data


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

    def test_daily_ops_preflight_names_missing_steps_before_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)
            seed_reference_data(db_path)
            with connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO trade_calendar (exchange, cal_date, is_open, pretrade_date)
                    VALUES ('SSE', '20260512', 1, '20260511')
                    """
                )

            result = run_daily_ops_preflight(db_path, as_of_date="20260512", include_market_review=True)

            self.assertEqual(result.status, "blocked")
            self.assertFalse(result.ok)
            self.assertIn("raw_events", result.missing_steps)
            self.assertIn("market_data", result.missing_steps)
            self.assertEqual(_step_status(result, "trading_day"), "pass")
            self.assertEqual(_step_status(result, "market_review"), "warning")

    def test_daily_ops_preflight_blocks_duplicate_apply_writes_unless_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)
            seed_reference_data(db_path)
            _seed_daily_preflight_ready_rows(db_path)
            with connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO operation_requests
                      (idempotency_key, operation_type, as_of_date, status, request_json, operator)
                    VALUES
                      ('daily-pipeline:paper-main:20260512:cpb:paper:daily-close',
                       'daily_review', '20260512', 'success', '{"dry_run": false}', 'tester')
                    """
                )

            blocked = run_daily_ops_preflight(db_path, as_of_date="20260512")
            allowed = run_daily_ops_preflight(db_path, as_of_date="20260512", allow_rerun=True)

            self.assertEqual(blocked.status, "blocked")
            self.assertEqual(blocked.duplicate_apply_count, 1)
            self.assertIn("duplicate_apply", blocked.missing_steps)
            self.assertEqual(allowed.status, "pass")
            self.assertEqual(_step_status(allowed, "duplicate_apply"), "warning")

    def test_daily_ops_preflight_requires_apply_pool_intake_summary_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            summary = root / "intake.json"
            run_migrations(db_path)
            seed_reference_data(db_path)
            _seed_daily_preflight_ready_rows(db_path)
            summary.write_text(
                '{"mode":"dry_run","added_count":1,"duplicate_count":0,"invalid_count":0}\n',
                encoding="utf-8",
            )

            result = run_daily_ops_preflight(
                db_path,
                as_of_date="20260512",
                pool_intake_summary_path=summary,
                require_pool_intake=True,
            )

            self.assertEqual(result.status, "blocked")
            self.assertIn("pool_intake", result.missing_steps)
            self.assertIn("apply summary required", _step_detail(result, "pool_intake"))

    def test_shadow_strategy_snapshot_helper_routes_read_only_feed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_shadow_snapshot_artifacts(reports_dir)

            result = run_shadow_strategy_snapshot(db_path, as_of_date="20260512", reports_dir=reports_dir)

            self.assertTrue(result.ok)
            self.assertEqual(result.request_id, "ops-shadow-strategy-snapshot")
            assert result.data is not None
            self.assertEqual(result.data.as_of_date, "20260512")
            self.assertTrue(result.data.read_only)
            self.assertTrue(result.data.artifact_only)
            self.assertEqual(result.data.counts["candidate_count"], 1)
            self.assertEqual(result.data.blocker_counts["operator_review_required"], 1)
            self.assertFalse(result.data.safety["writes_trade_state"])

    def test_shadow_observation_helper_routes_read_only_scorecard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_shadow_snapshot_artifacts(reports_dir)

            result = run_shadow_observation_scorecard(db_path, as_of_date="20260512", reports_dir=reports_dir)

            self.assertTrue(result.ok, result.errors)
            self.assertEqual(result.request_id, "ops-shadow-observation-scorecard")
            assert result.data is not None
            self.assertEqual(result.data.scorecard_contract, "shadow_observation_scorecard_v1")
            self.assertEqual(result.data.as_of_date, "20260512")
            self.assertTrue(result.data.read_only)
            self.assertTrue(result.data.safety["observation_is_not_paper_trading"])
            self.assertFalse(result.data.safety["writes_trade_state"])
            self.assertFalse(result.data.safety["timer_mutated"])
            self.assertEqual(result.data.rows[0]["candidate_key"], "trend_extension_shadow")

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


def _seed_daily_preflight_ready_rows(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO trade_calendar (exchange, cal_date, is_open, pretrade_date)
            VALUES ('SSE', '20260512', 1, '20260511')
            """
        )
        conn.execute(
            """
            INSERT INTO raw_events
              (ts_code, code, name, entry_date, entry_time, entry_price, source)
            VALUES
              ('000001.SZ', '000001', 'Ready Candidate', '20260512', '09:30', 10.0, 'operator_screenshot')
            """
        )
        conn.execute(
            """
            INSERT INTO market_bars
              (ts_code, trade_date, open, high, low, close, vol, amount)
            VALUES
              ('000001.SZ', '20260512', 10.0, 10.5, 9.9, 10.2, 100000, 1000.0)
            """
        )


def _seed_shadow_snapshot_artifacts(reports_dir: Path) -> None:
    monitor = {
        "review_date": "20260512",
        "next_trade_date": "20260513",
        "today_candidate_count": 1,
        "walk_forward_progress": {"status": "partial", "required_days": 20, "evaluable_signal_days": 5},
        "candidate_monitors": [
            {
                "candidate_key": "trend_extension_shadow",
                "candidate_family": "shadow_bucket",
                "walk_forward_progress": {"status": "partial", "required_days": 20, "days": 5},
                "promotion_gates": {
                    "paper_observation_gate": {
                        "status": "blocked",
                        "allowed": False,
                        "artifact_only": True,
                        "blockers": ["operator_review_required"],
                    },
                    "strategy_version_gate": {
                        "status": "blocked",
                        "allowed": False,
                        "artifact_only": True,
                        "blockers": ["proposal_review_required"],
                    },
                },
            }
        ],
    }
    preflight = {
        "review_date": "20260512",
        "next_trade_date": "20260513",
        "status": "blocked",
        "candidate_count": 1,
        "candidate_gates": [
            {
                "candidate_key": "trend_extension_shadow",
                "candidate_family": "shadow_bucket",
                "status": "blocked",
                "paper_observation_gate": {
                    "status": "blocked",
                    "allowed": False,
                    "artifact_only": True,
                    "blockers": ["operator_review_required"],
                },
                "strategy_version_gate": {
                    "status": "blocked",
                    "allowed": False,
                    "artifact_only": True,
                    "blockers": ["proposal_review_required"],
                },
            }
        ],
        "blocker_counts": {"operator_review_required": 1, "proposal_review_required": 1},
        "safety": {"artifact_only": True, "writes_trade_state": False, "promotion_allowed": False},
    }
    (reports_dir / "strategy_shadow_monitor_20260512.json").write_text(json.dumps(monitor), encoding="utf-8")
    (reports_dir / "strategy_shadow_promotion_preflight_20260512.json").write_text(
        json.dumps(preflight),
        encoding="utf-8",
    )


def _step_status(result, step: str) -> str | None:
    for check in result.checks:
        if check.step == step:
            return check.status
    return None


def _step_detail(result, step: str) -> str:
    for check in result.checks:
        if check.step == step:
            return check.detail
    return ""


if __name__ == "__main__":
    unittest.main()
