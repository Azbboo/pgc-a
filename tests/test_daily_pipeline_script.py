from __future__ import annotations

import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers.daily_workflow_fixture import (
    AS_OF_DATE,
    PAPER_ACCOUNT_KEY,
    insert_contracting_pullback_case,
    insert_open_calendar,
    migrated_seeded_daily_close_db,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_daily_pipeline.sh"


class DailyPipelineScriptTest(unittest.TestCase):
    def test_latest_closed_resolves_date_and_runs_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = migrated_seeded_daily_close_db(root)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "Script Pipeline")

            env = _script_env(root)
            result = subprocess.run(
                [
                    "bash",
                    str(SCRIPT),
                    "--date",
                    "latest-closed",
                    "--account",
                    PAPER_ACCOUNT_KEY,
                    "--operator",
                    "tester",
                    "--db-path",
                    str(db_path),
                    "--dry-run",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(f"resolved_date={AS_OF_DATE}", result.stdout)
            self.assertIn("pipeline_status=pass", result.stdout)
            self.assertIn("report_would_write=true", result.stdout)
            log_path = root / "logs" / f"daily-pipeline-{AS_OF_DATE}.log"
            self.assertTrue(log_path.exists())
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn(f"resolved_date={AS_OF_DATE}", log_text)
            self.assertIn("duplicate_apply_count=0", log_text)
            self.assertIn("duplicate_write_guard=dry_run", log_text)
            self.assertIn("pipeline_status=pass", log_text)

    def test_evidence_run_preserves_numbered_dry_run_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = migrated_seeded_daily_close_db(root)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "Script Evidence")

            command = [
                "bash",
                str(SCRIPT),
                "--date",
                "latest-closed",
                "--account",
                PAPER_ACCOUNT_KEY,
                "--operator",
                "tester",
                "--db-path",
                str(db_path),
                "--dry-run",
                "--evidence-run",
                "m62-1",
            ]
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=_script_env(root),
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            log_path = root / "logs" / f"daily-pipeline-{AS_OF_DATE}-m62-1.log"
            self.assertTrue(log_path.exists())
            self.assertIn(f"log_file={log_path}", result.stdout)
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("evidence_run_id=m62-1", log_text)
            self.assertIn("evidence_log_role=dry_run_activation_evidence", log_text)
            self.assertIn("duplicate_apply_count=0", log_text)
            self.assertIn("pipeline_status=pass", log_text)

            duplicate = subprocess.run(
                command,
                cwd=ROOT,
                env=_script_env(root),
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(duplicate.returncode, 1)
            self.assertIn(f"evidence log already exists: {log_path}", duplicate.stderr)

    def test_evidence_run_refuses_apply_mode(self) -> None:
        result = subprocess.run(
            [
                "bash",
                str(SCRIPT),
                "--date",
                AS_OF_DATE,
                "--operator",
                "tester",
                "--apply",
                "--evidence-run",
                "m62-apply",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("--evidence-run is only valid with --dry-run", result.stderr)

    def test_latest_closed_refuses_missing_market_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = migrated_seeded_daily_close_db(root)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)

            result = subprocess.run(
                [
                    "bash",
                    str(SCRIPT),
                    "--date",
                    "latest-closed",
                    "--account",
                    PAPER_ACCOUNT_KEY,
                    "--operator",
                    "tester",
                    "--db-path",
                    str(db_path),
                    "--dry-run",
                ],
                cwd=ROOT,
                env=_script_env(root),
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(f"resolved_date={AS_OF_DATE}", result.stdout)
            self.assertIn(f"market data missing for resolved_date={AS_OF_DATE}", result.stderr)

    def test_apply_refuses_duplicate_completed_pipeline_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = migrated_seeded_daily_close_db(root)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "Script Duplicate Guard")
                conn.execute(
                    """
                    INSERT INTO operation_requests
                      (idempotency_key, operation_type, as_of_date, status, request_json, operator)
                    VALUES
                      ('daily-pipeline:existing:daily-close', 'daily_review', ?, 'success', ?, 'tester')
                    """,
                    (AS_OF_DATE, '{"dry_run": false}'),
                )

            result = subprocess.run(
                [
                    "bash",
                    str(SCRIPT),
                    "--date",
                    "latest-closed",
                    "--account",
                    PAPER_ACCOUNT_KEY,
                    "--operator",
                    "tester",
                    "--db-path",
                    str(db_path),
                    "--apply",
                ],
                cwd=ROOT,
                env=_script_env(root),
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(f"resolved_date={AS_OF_DATE}", result.stdout)
            self.assertIn("duplicate_apply_count=1", result.stdout)
            self.assertIn("duplicate_write_guard=blocked", result.stdout)
            self.assertIn("pass --allow-rerun only after operator review", result.stderr)
            log_path = root / "logs" / f"daily-pipeline-{AS_OF_DATE}.log"
            self.assertTrue(log_path.exists())
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("duplicate_apply_count=1", log_text)
            self.assertIn("duplicate_write_guard=blocked", log_text)


def _script_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PGC_DAILY_PIPELINE_LOG_DIR": str(root / "logs"),
            "PGC_DAILY_PIPELINE_NOW_DATE": AS_OF_DATE,
            "PGC_DAILY_PIPELINE_NOW_TIME": "160000",
        }
    )
    return env


if __name__ == "__main__":
    unittest.main()
