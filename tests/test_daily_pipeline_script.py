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
            self.assertTrue((root / "logs" / f"daily-pipeline-{AS_OF_DATE}.log").exists())

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
