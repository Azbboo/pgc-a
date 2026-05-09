from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "reports" / "operational_runbook_design.md"
BACKUP_SCRIPT = ROOT / "scripts" / "backup_remote_pgc_db.sh"
RESTORE_SCRIPT = ROOT / "scripts" / "restore_remote_pgc_db.sh"
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy_remote.sh"


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


if __name__ == "__main__":
    unittest.main()
