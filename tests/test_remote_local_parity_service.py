from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from pgc_trading.cli.main import main
from pgc_trading.services.remote_local_parity_service import (
    BuildRemoteLocalParityRequest,
    RemoteLocalParityService,
    render_remote_local_parity_markdown,
)
from pgc_trading.storage.database import connect
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data


class RemoteLocalParityServiceTest(unittest.TestCase):
    def test_parity_passes_when_database_reports_evidence_and_release_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_db = root / "local.db"
            remote_db = root / "remote.db"
            local_reports = root / "local-reports"
            remote_reports = root / "remote-reports"
            for db_path in (local_db, remote_db):
                _seed_parity_database(db_path)
            _seed_reports(local_reports)
            _seed_reports(remote_reports)

            result = RemoteLocalParityService().build(
                BuildRemoteLocalParityRequest(
                    as_of_date="20260514",
                    local_db_path=local_db,
                    remote_db_path=remote_db,
                    local_reports_dir=local_reports,
                    remote_reports_dir=remote_reports,
                    local_release_tag="pgc-v0.1.0-20260514-test",
                    remote_release_tag="pgc-v0.1.0-20260514-test",
                    local_git_sha="abcdef1234567890",
                    remote_git_sha="abcdef1234567890",
                    generated_at="2026-05-14T12:00:00Z",
                )
            )

            self.assertEqual(result.status, "pass")
            self.assertTrue(result.ok)
            self.assertEqual(result.blocker_keys, [])
            self.assertTrue(result.safety["read_only"])
            self.assertFalse(result.safety["trade_state_mutated"])
            self.assertTrue(all(check.status == "pass" for check in result.checks))

    def test_parity_blocks_when_latest_market_bars_differ(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_db = root / "local.db"
            remote_db = root / "remote.db"
            for db_path in (local_db, remote_db):
                _seed_parity_database(db_path)
            with connect(remote_db) as conn:
                conn.execute(
                    """
                    INSERT INTO market_bars (ts_code, trade_date, open, high, low, close, vol, amount)
                    VALUES ('000002.SZ', '20260514', 9.0, 9.6, 8.9, 9.3, 2000, 20000.0)
                    """
                )

            result = RemoteLocalParityService().build(
                BuildRemoteLocalParityRequest(
                    as_of_date="20260514",
                    local_db_path=local_db,
                    remote_db_path=remote_db,
                    local_release_tag="same",
                    remote_release_tag="same",
                )
            )

            self.assertEqual(result.status, "blocker")
            self.assertIn("market_bars", result.blocker_keys)
            market_check = next(check for check in result.checks if check.key == "market_bars")
            self.assertEqual(market_check.status, "blocker")
            self.assertIn("differ", market_check.detail)

    def test_cli_writes_json_and_markdown_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_db = root / "local.db"
            remote_db = root / "remote.db"
            local_reports = root / "local-reports"
            remote_reports = root / "remote-reports"
            output_json = root / "parity.json"
            output_md = root / "parity.md"
            for db_path in (local_db, remote_db):
                _seed_parity_database(db_path)
            _seed_reports(local_reports)
            _seed_reports(remote_reports)
            stdout = io.StringIO()

            code = main(
                [
                    "ops",
                    "remote-local-parity",
                    "--date",
                    "2026-05-14",
                    "--db-path",
                    str(local_db),
                    "--remote-db-path",
                    str(remote_db),
                    "--reports-dir",
                    str(local_reports),
                    "--remote-reports-dir",
                    str(remote_reports),
                    "--local-release-tag",
                    "same-release",
                    "--remote-release-tag",
                    "same-release",
                    "--local-git-sha",
                    "abcdef1234567890",
                    "--remote-git-sha",
                    "abcdef1234567890",
                    "--output-json",
                    str(output_json),
                    "--output-md",
                    str(output_md),
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 0, stdout.getvalue())
            output = stdout.getvalue()
            self.assertIn("ops remote-local-parity command routed", output)
            self.assertIn("remote_local_parity_status=pass", output)
            self.assertIn("blockers=none", output)
            self.assertIn("remote_local_parity_notice=read-only", output)
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["contract"], "remote_local_parity_v1")
            self.assertEqual(payload["status"], "pass")
            markdown = output_md.read_text(encoding="utf-8")
            self.assertIn("# Remote/Local Parity 20260514", markdown)
            self.assertIn("latest_db_count=0", markdown)
            self.assertNotIn("latest_date_count=0; latest_db_date", markdown)

    def test_markdown_renderer_keeps_next_command_hints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_db = root / "local.db"
            remote_db = root / "remote.db"
            _seed_parity_database(local_db)
            result = RemoteLocalParityService().build(
                BuildRemoteLocalParityRequest(
                    as_of_date="20260514",
                    local_db_path=local_db,
                    remote_db_path=remote_db,
                    generated_at="2026-05-14T12:00:00Z",
                )
            )

            markdown = render_remote_local_parity_markdown(result)

            self.assertIn("Copy the remote SQLite snapshot locally", markdown)
            self.assertIn("no strategy, trade, paper/live, broker, or timer mutation", markdown)


def _seed_parity_database(db_path: Path) -> None:
    run_migrations(db_path)
    seed_reference_data(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO market_bars (ts_code, trade_date, open, high, low, close, vol, amount)
            VALUES ('000001.SZ', '20260514', 10.0, 10.8, 9.9, 10.5, 1000, 10000.0)
            """
        )
        conn.execute(
            """
            INSERT INTO market_review_runs
              (as_of_date, status, provider_manifest_json, coverage_json, summary_json)
            VALUES ('20260514', 'completed', '{}', '{}', '{}')
            """
        )
        conn.execute(
            """
            INSERT INTO market_external_items
              (as_of_date, scope_type, scope_key, item_type, provider, title, summary,
               sentiment, importance, published_date, source_hash)
            VALUES
              ('20260514', 'market', 'A_SHARE', 'news', 'reviewed_cache', 'Market note',
               'Reviewed summary.', 'neutral', 'medium', '20260514', 'market-hash')
            """
        )
        conn.execute(
            """
            INSERT INTO agent_external_items
              (ts_code, published_date, item_type, provider, title, summary, sentiment,
               importance, source_hash)
            VALUES
              ('000001.SZ', '20260514', 'news', 'reviewed_cache', 'Agent note',
               'Reviewed agent summary.', 'neutral', 'medium', 'agent-hash')
            """
        )


def _seed_reports(reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True)
    (reports_dir / "daily_review_20260514.json").write_text("{}\n", encoding="utf-8")
    (reports_dir / "daily_review_20260514.md").write_text("# Daily Review\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
