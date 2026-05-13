from __future__ import annotations

import shutil
import subprocess
import tempfile
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

    def test_m54_runbook_documents_production_evidence_import_operations(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")

        for text in [
            "M54 生产证据导入运营化",
            "provider_file_contract=market_external_v1",
            "provider_file_contract=agent_external_v1",
            "coverage_details_json",
            "coverage_json",
            "missing_scopes",
            "missing_item_types",
            "stale_scopes",
            "duplicate_count",
            "stale_count",
            "provider/source hash",
            "daily-close、open-execution、report rendering 或 Dashboard request handling 中 live web fetch",
            "market-review external-data import --date YYYYMMDD",
            "agent external-data import --date YYYYMMDD",
        ]:
            self.assertIn(text, source)

    def test_m55_runbook_documents_historical_evidence_backfill_qa(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")

        for text in [
            "M55 历史证据回补和覆盖率 QA",
            "market-review external-data backfill --input",
            "agent external-data backfill --input",
            "coverage_qa_json",
            "backfill_totals",
            "backfill_dates",
            "ready_dates",
            "blocking_dates",
            "missing_scope_dates",
            "missing_item_type_dates",
            "stale_scope_dates",
            "duplicate_dates",
            "缺少 backfill as-of date",
            "整批 apply 必须拒绝并保持无部分写入",
            "不得改写交易计划、持仓、成交或活跃策略参数",
        ]:
            self.assertIn(text, source)

    def test_m72_runbook_documents_market_review_empty_state_diagnostics(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")

        for text in [
            "M72 全市场复盘空状态诊断",
            "GET /api/market-reviews/{YYYYMMDD}",
            "diagnostics",
            "selected market date",
            "latest market-review date",
            "source DB freshness",
            "missing downstream tables",
            "empty-state reasons",
            "API Base",
            "localStorage",
            "pgc ops market-review-parity",
            "--remote-db-path",
            "market_review_runs",
            "sector_daily_snapshots",
            "market_external_items",
            "market_plan_contexts",
            "strategy_hypotheses",
            "parity_status=match",
        ]:
            self.assertIn(text, source)

    def test_m75_runbook_documents_daily_ops_preflight_and_pool_intake_closure(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")

        for text in [
            "M75 20260512+ 日常复盘与股票池摄入闭环",
            "ops pool-intake",
            "data/daily_review_S_intake_dry_run.json",
            "data/daily_review_S_intake_apply.json",
            "invalid_count=0",
            "ops daily-preflight",
            "--pool-intake-summary data/daily_review_S_intake_apply.json",
            "--require-pool-intake",
            "daily_preflight_status",
            "missing_steps",
            "duplicate_apply_count",
            "daily_step=... status=...",
            "missing_steps=none",
            "duplicate_apply",
            "./scripts/run_daily_pipeline.sh --date S --account paper-main --operator azboo --include-market-review --dry-run",
            "./scripts/run_daily_pipeline.sh --date S --account paper-main --operator azboo --include-market-review --apply",
            "duplicate_write_guard=dry_run",
            "market_review_would_write=true",
            "report_would_write=true",
            "backup_path",
            "M75 不启用生产 timer",
            "scripts/install_remote_daily_pipeline_timer.sh --enable",
        ]:
            self.assertIn(text, source)

    def test_m82_runbook_documents_shadow_visibility_release_gate(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")

        for text in [
            "M82 影子策略可视化发布门禁",
            "shadow visibility remains artifact-only",
            "strategy_shadow_monitor_YYYYMMDD.json",
            "strategy_shadow_promotion_preflight_YYYYMMDD.json",
            "read_only_guard",
            "release_gate",
            "shadow_strategy_snapshot API/CLI",
            "Dashboard Shadow Lab",
            "daily review shadow_strategy section",
            "active CPB params/hash must remain unchanged",
            "trade_plans, trades, positions",
            "pgc-daily-pipeline.timer",
            "promotion_allowed=false",
            "timer_mutated=false",
            "PYTHONPATH=src:. pytest -q tests/test_strategy_evolution_service.py tests/test_strategy_hypothesis_backtest_service.py tests/test_shadow_strategy_service.py tests/test_operational_runbook_static.py",
        ]:
            self.assertIn(text, source)

    def test_m86_runbook_documents_shadow_promotion_dossier_release_gate(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")

        for text in [
            "M86 影子策略 promotion dossier 发布门禁",
            "shadow_promotion_dossier_YYYYMMDD.json",
            "shadow_promotion_dossier_v1",
            "review_ready is not approval",
            "minimum_sample",
            "positive_frozen_cpb_delta",
            "evidence_coverage",
            "drawdown_cap",
            "blocker_clearance",
            "future_strategy_version_task_required",
            "manual_promotion_approval_required",
            "promotion_allowed=false",
            "active CPB params/hash must remain unchanged",
            "strategy_versions, trade_plans, trades, positions",
            "paper/live behavior",
            "pgc-daily-pipeline.timer",
            "PYTHONPATH=src:. pytest -q tests/test_shadow_observation_service.py tests/test_strategy_evolution_service.py tests/test_operational_runbook_static.py",
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
            "scripts/install_remote_daily_pipeline_timer.sh --dry-run --operator system-daily-pipeline --mode apply",
            "scripts/install_remote_daily_pipeline_timer.sh --enable --operator system-daily-pipeline --mode apply",
            "scripts/install_remote_daily_pipeline_timer.sh --status",
            "systemctl list-timers --all pgc-daily-pipeline.timer --no-pager",
            "systemctl status pgc-daily-pipeline.timer --no-pager",
            "systemctl status pgc-daily-pipeline.service --no-pager",
            "journalctl -u pgc-daily-pipeline.service -n 100 --no-pager",
            "systemctl disable --now pgc-daily-pipeline.timer",
            "./scripts/run_daily_pipeline.sh --date latest-closed --account paper-main --operator system-daily-pipeline --include-market-review --apply",
            "./scripts/run_daily_pipeline.sh --date latest-closed --account paper-main --operator system-daily-pipeline --include-market-review --dry-run",
            "resolved_date=YYYYMMDD",
            "duplicate_write_guard=pass",
            "--allow-rerun",
            "manual_dry_run_command",
            "manual_apply_command",
            "health_command",
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
            "--allow-rerun",
            "--evidence-run",
            "evidence_log_role=dry_run_activation_evidence",
            "evidence log already exists",
            "duplicate_apply_count=",
            "duplicate_write_guard=blocked",
            "duplicate_write_guard=dry_run",
            'tee -a "$LOG_FILE"',
        ]:
            self.assertIn(text, pipeline_source)

        timer_source = DAILY_PIPELINE_TIMER_SCRIPT.read_text(encoding="utf-8")
        for text in [
            "Preview is the default",
            "--enable",
            "--collect-evidence",
            "--check-activation",
            "--status",
            "--approval-id",
            "--dry-run-evidence",
            "--min-dry-runs",
            "--evidence-run",
            "--evidence-dir",
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
            "manual_dry_run_command=",
            "manual_apply_command=",
            "collect_dry_run_evidence_command=",
            "local_evidence_dir=",
            "evidence_run_id=",
            "health_command=",
            "minimum_dry_run_evidence=",
            "activation_approval_id=",
            "dry_run_evidence_run_id",
            "dry_run_evidence_role",
            "activation_decision_error=missing_approval_id",
            "activation_decision_error=insufficient_dry_run_evidence",
            "evidence_collection_error=evidence_run_id_required",
            "evidence_collection_error=local_evidence_file_exists",
            "timer_state=unchanged_disabled_until_enable_gate",
            "duplicate_apply_count_zero",
            "timer_list_command=systemctl list-timers --all",
            "duplicate_write_guard=run_daily_pipeline.sh blocks completed apply runs unless --allow-rerun is passed",
            "scp",
            "systemctl enable --now",
            "systemctl is-enabled",
            "systemctl is-active",
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

        preview = subprocess.run(
            [
                bash,
                str(DAILY_PIPELINE_TIMER_SCRIPT),
                "--operator",
                "system-daily-pipeline",
                "--mode",
                "apply",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
        self.assertIn("action=preview", preview.stdout)
        self.assertIn("timer_enablement=preview_only", preview.stdout)
        self.assertIn("manual_dry_run_command=", preview.stdout)
        self.assertIn("manual_apply_command=", preview.stdout)
        self.assertIn("collect_dry_run_evidence_command=", preview.stdout)
        self.assertIn("evidence_run_id=missing", preview.stdout)
        self.assertIn("activation_decision=preview_only", preview.stdout)
        self.assertIn("would_enable_timer=systemctl enable --now pgc-daily-pipeline.timer only after --enable", preview.stdout)

    def test_m58_timer_activation_requires_approval_and_repeated_dry_run_evidence(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")
        for text in [
            "M58 定时器启用决策",
            "scripts/install_remote_daily_pipeline_timer.sh --check-activation",
            "--approval-id OPS-YYYYMMDD",
            "--dry-run-evidence .pgc-runs/daily-pipeline-YYYYMMDD-1.log",
            "minimum_dry_run_evidence=3",
            "activation_decision=blocked",
            "activation_decision=ready",
            "duplicate_apply_count=0",
            "duplicate_write_guard=dry_run",
            "systemctl disable --now pgc-daily-pipeline.timer",
        ]:
            self.assertIn(text, source)

        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is not installed")

        blocked = subprocess.run(
            [
                bash,
                str(DAILY_PIPELINE_TIMER_SCRIPT),
                "--enable",
                "--operator",
                "system-daily-pipeline",
                "--mode",
                "apply",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("activation_decision_error=missing_approval_id", blocked.stderr)
        self.assertIn("activation_decision_error=insufficient_dry_run_evidence required=3 actual=0", blocked.stderr)
        self.assertIn("activation_decision=blocked", blocked.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            evidence_paths = []
            for index, date in enumerate(["20260506", "20260507", "20260508"], start=1):
                path = Path(tmp) / f"daily-pipeline-{date}-{index}.log"
                path.write_text(
                    "\n".join(
                        [
                            f"resolved_date={date}",
                            f"log_file={path}",
                            f"evidence_run_id=m62-{index}",
                            "evidence_log_role=dry_run_activation_evidence",
                            "duplicate_apply_count=0",
                            "duplicate_write_guard=dry_run",
                            "pipeline_status=pass",
                            "backup_path=none",
                            "changed=false",
                            "report_would_write=true",
                            "market_review_would_write=true",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
                evidence_paths.extend(["--dry-run-evidence", str(path)])

            ready = subprocess.run(
                [
                    bash,
                    str(DAILY_PIPELINE_TIMER_SCRIPT),
                    "--check-activation",
                    "--operator",
                    "system-daily-pipeline",
                    "--mode",
                    "apply",
                    "--approval-id",
                    "OPS-20260510",
                    *evidence_paths,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(ready.returncode, 0, ready.stdout + ready.stderr)
            self.assertIn("activation_decision=ready", ready.stdout)
            self.assertIn("dry_run_evidence_count=3", ready.stdout)
            self.assertIn("activation_approval_id=OPS-20260510", ready.stdout)

    def test_m62_runbook_documents_timer_dry_run_evidence_collection(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")
        for text in [
            "M62 定时器 dry-run 证据采集",
            "scripts/install_remote_daily_pipeline_timer.sh --collect-evidence --operator system-daily-pipeline --mode apply --evidence-run m62-1",
            "PGC_TIMER_EVIDENCE_DIR=.pgc-runs/timer-evidence",
            "./scripts/run_daily_pipeline.sh --date latest-closed --account paper-main --operator system-daily-pipeline --include-market-review --dry-run --evidence-run m62-1",
            "daily-pipeline-YYYYMMDD-m62-1.log",
            "evidence_log_role=dry_run_activation_evidence",
            "dry_run_evidence_arg=--dry-run-evidence",
            "timer_state=unchanged_disabled_until_enable_gate",
            "activation_decision=not_evaluated",
            "activation_decision=ready",
            "systemctl disable --now pgc-daily-pipeline.timer",
        ]:
            self.assertIn(text, source)

        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is not installed")

        missing_run_id = subprocess.run(
            [
                bash,
                str(DAILY_PIPELINE_TIMER_SCRIPT),
                "--collect-evidence",
                "--operator",
                "system-daily-pipeline",
                "--mode",
                "apply",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(missing_run_id.returncode, 2)
        self.assertIn("action=collect-evidence", missing_run_id.stdout)
        self.assertIn("timer_enablement=evidence_collection", missing_run_id.stdout)
        self.assertIn("evidence_collection_error=evidence_run_id_required", missing_run_id.stderr)

        preview = subprocess.run(
            [
                bash,
                str(DAILY_PIPELINE_TIMER_SCRIPT),
                "--dry-run",
                "--operator",
                "system-daily-pipeline",
                "--mode",
                "apply",
                "--evidence-run",
                "m62-1",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
        self.assertIn("collect_dry_run_evidence_command=", preview.stdout)
        self.assertIn("--evidence-run m62-1", preview.stdout)
        self.assertIn("local_evidence_dir=.pgc-runs/timer-evidence", preview.stdout)


if __name__ == "__main__":
    unittest.main()
