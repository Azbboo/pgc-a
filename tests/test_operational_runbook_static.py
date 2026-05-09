from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "reports" / "operational_runbook_design.md"
MARKET_REVIEW_DATA_SOURCE_DESIGN = ROOT / "reports" / "market_review_data_source_design.md"
BACKUP_SCRIPT = ROOT / "scripts" / "backup_remote_pgc_db.sh"
RESTORE_SCRIPT = ROOT / "scripts" / "restore_remote_pgc_db.sh"
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy_remote.sh"
DAILY_PIPELINE_SCRIPT = ROOT / "scripts" / "run_daily_pipeline.sh"
DAILY_PIPELINE_TIMER_SCRIPT = ROOT / "scripts" / "install_remote_daily_pipeline_timer.sh"


class OperationalRunbookStaticTest(unittest.TestCase):
    def test_m15a_runbook_documents_backup_restore_and_health_gate(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")

        for text in [
            "scripts/backup_remote_pgc_db.sh",
            "scripts/restore_remote_pgc_db.sh",
            "/opt/pgc/data/pgc_trading.db",
            "/opt/pgc/backups/pgc_trading-YYYYMMDD-HHMMSS.db",
            "systemctl restart pgc-api.service",
            "/api/health",
            "writes_enabled=true",
            "PGC_API_ENABLE_WRITES=1",
            "dry-run trade smoke",
            "operator",
        ]:
            self.assertIn(text, source)

    def test_m15a_remote_db_scripts_are_guarded_and_parseable(self) -> None:
        for script in [BACKUP_SCRIPT, RESTORE_SCRIPT]:
            self.assertTrue(script.exists(), f"missing {script}")
            source = script.read_text(encoding="utf-8")
            self.assertIn("root@150.158.121.150", source)
            self.assertIn("/opt/pgc/data/pgc_trading.db", source)
            self.assertIn("/opt/pgc/backups", source)
            self.assertIn("--help", source)
            self.assertNotIn("rm -rf", source)
            self.assertNotIn("rm -f", source)

        backup_source = BACKUP_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('sqlite3 "$db_path" ".backup $backup_path"', backup_source)

        restore_source = RESTORE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Usage: restore_remote_pgc_db.sh BACKUP_PATH", restore_source)
        self.assertIn('REMOTE_SERVICE="${PGC_REMOTE_SERVICE:-pgc-api.service}"', restore_source)
        self.assertIn('"$backup_dir"/*.db', restore_source)
        self.assertIn("backup path must not be the target database path", restore_source)
        self.assertIn('systemctl stop "$service"', restore_source)
        self.assertIn('systemctl restart "$service"', restore_source)
        self.assertIn("/api/health", restore_source)

        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is not installed")
        for script in [BACKUP_SCRIPT, RESTORE_SCRIPT]:
            subprocess.run([bash, "-n", str(script)], check=True)

    def test_m20_runbook_documents_standard_ops_release_flow(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")

        for text in [
            "M20 部署运维标准化",
            "pgc ops version",
            "pgc ops migrate --dry-run",
            "pgc ops health",
            "--require-current-migrations",
            "scripts/deploy_remote.sh --dry-run",
            "release_tag",
            "backup_path",
            "systemctl restart pgc-api.service",
            "/api/health",
        ]:
            self.assertIn(text, source)

    def test_m28_runbook_documents_daily_pipeline_acceptance_gate(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")

        for text in [
            "M28 验收门禁",
            "scripts/run_daily_pipeline.sh",
            "ledger_audit_status=pass",
            "pipeline_status=pass",
            "backup before non-dry writes",
            "TradingAgents review",
            "operator",
            "/api/health",
            "/api/daily-reviews/20260508",
        ]:
            self.assertIn(text, source)

    def test_m40_runbook_documents_strategy_evolution_policy(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")

        for text in [
            "M40 策略演化假设治理",
            "strategy-evolution propose",
            "strategy-evolution list --status proposed",
            "strategy-evolution mark --hypothesis-id 1 --status testing",
            "hypothesis must pass replay/backtest before accepted",
            "accepted hypothesis creates a separate strategy-version task",
            "active paper/live strategy params are not mutated by reports",
            "src/pgc_trading/strategies/params/*.json",
        ]:
            self.assertIn(text, source)

    def test_m50_runbook_documents_strategy_hypothesis_validation_loop(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")

        for text in [
            "M50 策略假设验证 / 回测闭环",
            "proposed -> testing -> accepted/rejected",
            "strategy-evolution backtest",
            "--evidence-id market_review_run:RUN_ID",
            "--backtest-artifact reports/strategy_hypothesis_backtests/hypothesis_1_backtest_request.json",
            "`accepted` requires validation evidence ids",
            "`accepted` requires a readable backtest request artifact",
            "accepted hypotheses create a separate future strategy-version task only",
            "no active strategy or trading behavior mutation is allowed",
        ]:
            self.assertIn(text, source)

    def test_m42_runbook_documents_market_review_daily_pipeline_contract(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")

        for text in [
            "M42 之后，带全市场复盘的收盘后主入口增加显式开关",
            "./scripts/run_daily_pipeline.sh --date S --account paper-main --operator azboo --include-market-review --dry-run",
            "./scripts/run_daily_pipeline.sh --date S --account paper-main --operator azboo --include-market-review --apply",
            "market review",
            "plan-context linking",
            "market_review_would_write=true",
            "report_would_write=true",
            "market_review_runs",
            "market_plan_contexts",
            "market_review_run_id + trade_plan_id",
            "## 全市场复盘",
            "## 全市场复盘与明日计划关系",
            "market regime summary",
            "top 5 sectors",
            "sector persistence",
            "external evidence coverage",
            "strategy hypotheses generated",
        ]:
            self.assertIn(text, source)

    def test_m43_runbook_documents_market_review_data_source_policy(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")

        for text in [
            "M43 全市场复盘生产数据源策略",
            "reports/market_review_data_source_design.md",
            "Fixture imports are for tests only.",
            "Tushare/official cached data is preferred for market and sector facts.",
            "Manual news/sentiment imports must include provider, title, date, summary, and source hash.",
            "Missing evidence is acceptable but must be explicit.",
            "No live web fetch inside daily trading path.",
            "market_review_runs.provider_manifest_json",
            "coverage_summary",
            "scripts/run_daily_pipeline.sh",
            "manual_fixture",
            "tests/fixtures/market_review",
        ]:
            self.assertIn(text, source)

    def test_m43_market_review_data_source_design_freezes_production_boundaries(self) -> None:
        self.assertTrue(MARKET_REVIEW_DATA_SOURCE_DESIGN.exists())
        source = MARKET_REVIEW_DATA_SOURCE_DESIGN.read_text(encoding="utf-8")

        for text in [
            "Fixture imports are for tests only.",
            "Tushare/official cached data is preferred for market and sector facts.",
            "Manual news/sentiment imports must include provider, title, date, summary, and source hash.",
            "Missing evidence is acceptable but must be explicit.",
            "No live web fetch inside daily trading path.",
            "tests/fixtures/market_review",
            "manual_fixture is not a production provider",
            "market_external_items.source_hash",
            "coverage_summary",
            "provider_manifest_json",
            "market-review external-data import",
            "scripts/run_daily_pipeline.sh",
            "/opt/pgc/data/pgc_trading.db",
        ]:
            self.assertIn(text, source)

    def test_m20_deploy_script_is_guarded_and_parseable(self) -> None:
        self.assertTrue(DEPLOY_SCRIPT.exists(), f"missing {DEPLOY_SCRIPT}")
        source = DEPLOY_SCRIPT.read_text(encoding="utf-8")

        for text in [
            "--dry-run",
            "PGC_RELEASE_TAG",
            "unittest discover -s tests",
            "scripts/backup_remote_pgc_db.sh",
            "git archive --format=tar.gz",
            "python3 -m pgc_trading.storage.migrate",
            "PGC_DB_PATH",
            "systemctl daemon-reload",
            'systemctl restart "$service"',
            'curl -fsS "$health_url"',
            "/opt/pgc/.deployed-revision",
            "/opt/pgc/.deployed-release",
            "root@150.158.121.150",
            "/opt/pgc/data/pgc_trading.db",
            "/opt/pgc/releases",
            "PGC_API_WRITE_TOKEN=<redacted>",
            "PGC_API_WRITE_TOKEN=<preserve-existing-if-present>",
            "preserve_existing_api_write_token",
            "^Environment=PGC_API_WRITE_TOKEN=",
        ]:
            self.assertIn(text, source)

        self.assertNotIn("rm -rf", source)
        self.assertNotIn("rm -f", source)

        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is not installed")
        subprocess.run([bash, "-n", str(DEPLOY_SCRIPT)], check=True)

    def test_m46_scheduled_pipeline_documents_timer_and_apply_guards(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")

        for text in [
            "M46 收盘后定时流水线",
            "scripts/install_remote_daily_pipeline_timer.sh --dry-run",
            "scripts/install_remote_daily_pipeline_timer.sh --operator system-daily-pipeline --mode apply",
            "systemctl status pgc-daily-pipeline.timer --no-pager",
            "journalctl -u pgc-daily-pipeline.service -n 100 --no-pager",
            "systemctl disable --now pgc-daily-pipeline.timer",
            "./scripts/run_daily_pipeline.sh --date latest-closed --account paper-main --operator system-daily-pipeline --include-market-review --apply",
            "resolved_date=YYYYMMDD",
            "/opt/pgc/logs",
            "/opt/pgc/backups",
            "/api/health",
            "PGC_API_WRITE_TOKEN=<preserve-existing-if-present>",
        ]:
            self.assertIn(text, source)

    def test_m46_daily_pipeline_scripts_are_guarded_and_parseable(self) -> None:
        self.assertTrue(DAILY_PIPELINE_SCRIPT.exists(), f"missing {DAILY_PIPELINE_SCRIPT}")
        self.assertTrue(DAILY_PIPELINE_TIMER_SCRIPT.exists(), f"missing {DAILY_PIPELINE_TIMER_SCRIPT}")

        pipeline_source = DAILY_PIPELINE_SCRIPT.read_text(encoding="utf-8")
        for text in [
            "latest-closed",
            "resolved_date=",
            "market data missing for resolved_date",
            "PGC_DAILY_PIPELINE_LOG_DIR",
            "--backup-dir",
            "--include-market-review",
        ]:
            self.assertIn(text, pipeline_source)

        timer_source = DAILY_PIPELINE_TIMER_SCRIPT.read_text(encoding="utf-8")
        for text in [
            "pgc-daily-pipeline.service",
            "pgc-daily-pipeline.timer",
            "Mon..Fri *-*-* 16:20:00 Asia/Shanghai",
            'REMOTE_CURRENT_DIR="${PGC_REMOTE_CURRENT_DIR:-/opt/pgc/app}"',
            'REMOTE_DB_PATH="${PGC_REMOTE_DB_PATH:-/opt/pgc/data/pgc_trading.db}"',
            'REMOTE_BACKUP_DIR="${PGC_REMOTE_BACKUP_DIR:-/opt/pgc/backups}"',
            'REMOTE_LOG_DIR="${PGC_REMOTE_LOG_DIR:-/opt/pgc/logs}"',
            "WorkingDirectory=$working_dir",
            "Environment=PGC_DB_PATH=$db_path",
            "Environment=PGC_DAILY_PIPELINE_LOG_DIR=$log_dir",
            "ExecStartPre=/usr/bin/curl -fsS",
            "--date latest-closed",
            "--operator ${OPERATOR}",
            "--backup-dir ${REMOTE_BACKUP_DIR}",
            "--include-market-review ${MODE_FLAG}",
            "systemctl enable --now",
            "journalctl -u",
            "systemctl disable --now",
        ]:
            self.assertIn(text, timer_source)

        self.assertNotIn("rm -rf", timer_source)
        self.assertNotIn("rm -f", timer_source)

        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is not installed")
        for script in [DAILY_PIPELINE_SCRIPT, DAILY_PIPELINE_TIMER_SCRIPT]:
            subprocess.run([bash, "-n", str(script)], check=True)


if __name__ == "__main__":
    unittest.main()
