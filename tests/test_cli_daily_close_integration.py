from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest

from pgc_trading.cli.main import main as cli_main
from tests.helpers.daily_workflow_fixture import (
    count_rows,
    insert_contracting_pullback_case,
    insert_open_calendar,
    migrated_seeded_daily_close_db,
)


class CliDailyCloseIntegrationTest(unittest.TestCase):
    def test_daily_close_apply_creates_paper_plan_through_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = migrated_seeded_daily_close_db(tmp)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "CLI Paper Pick")

            stdout = io.StringIO()
            code = cli_main(
                [
                    "daily-close",
                    "--date",
                    "2026-05-04",
                    "--db-path",
                    str(db_path),
                    "--account",
                    "paper-main",
                    "--apply",
                    "--operator",
                    "tester",
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("workflow_status=plan_ready", output)
            self.assertIn("readiness=pass", output)
            self.assertIn("buy_plan=id=", output)
            self.assertIn("action=buy_next_open", output)

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(count_rows(conn, "daily_picks"), 1)
                self.assertEqual(count_rows(conn, "trade_plans"), 1)
                self.assertEqual(count_rows(conn, "trades"), 0)
                self.assertEqual(count_rows(conn, "positions"), 0)

    def test_daily_close_preview_does_not_persist_pick_or_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = migrated_seeded_daily_close_db(tmp)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "CLI Preview Pick")

            stdout = io.StringIO()
            code = cli_main(
                [
                    "daily-close",
                    "--date",
                    "2026-05-04",
                    "--db-path",
                    str(db_path),
                    "--account",
                    "paper-main",
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("workflow_status=plan_ready", output)
            self.assertIn("candidate=000001.SZ CLI Preview Pick daily_pick_id=none", output)
            self.assertIn("buy_plan=id=none action=buy_next_open status=active", output)

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(count_rows(conn, "daily_picks"), 0)
                self.assertEqual(count_rows(conn, "trade_plans"), 0)
                self.assertEqual(count_rows(conn, "trades"), 0)
                self.assertEqual(count_rows(conn, "positions"), 0)


if __name__ == "__main__":
    unittest.main()
