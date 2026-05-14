from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

from pgc_trading.agents.tradingagents_adapter import (
    TradingAgentsExecutionResult,
    TradingAgentsPaths,
    TradingAgentsRunConfig,
)
from pgc_trading.services.agent_review_service import AgentReviewService
from pgc_trading.services.common import RequestContext
from pgc_trading.services.daily_pipeline_service import DailyPipelineService, RunDailyPipelineRequest
from tests.helpers.daily_workflow_fixture import (
    AS_OF_DATE,
    BUY_DATE,
    PAPER_ACCOUNT_KEY,
    count_rows,
    insert_contracting_pullback_case,
    insert_open_calendar,
    migrated_seeded_daily_close_db,
)


class _FakeTradingAgentsRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], TradingAgentsRunConfig, TradingAgentsPaths]] = []

    def run(
        self,
        snapshot: dict[str, Any],
        config: TradingAgentsRunConfig,
        paths: TradingAgentsPaths,
    ) -> TradingAgentsExecutionResult:
        self.calls.append((snapshot, config, paths))
        return TradingAgentsExecutionResult(
            action="caution",
            confidence=0.62,
            risk_level="medium",
            summary="形态可复核，但开盘前需要人工检查。",
            supporting_points=["缩量回调后转强"],
            risk_points=["次日高开风险"],
            analyst_reports={
                "technical": {
                    "status": "available",
                    "summary": "技术面可复核。",
                    "supporting_points": ["缩量回调后转强"],
                    "risk_points": ["次日高开风险"],
                }
            },
            raw_decision={"action": "caution", "summary": "形态可复核"},
            raw_state={"ticker": snapshot["candidate"]["ts_code"]},
            final_report="# TradingAgents Advisory\n\nCaution until pre-open checks pass.\n",
        )


class DailyPipelineServiceTest(unittest.TestCase):
    def test_apply_runs_all_steps_and_rerun_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = migrated_seeded_daily_close_db(root)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "Pipeline Pick")

            runner = _FakeTradingAgentsRunner()
            service = DailyPipelineService(
                db_path,
                reports_dir=root / "reports",
                agent_review_service_factory=self._agent_factory(root, runner),
            )
            request = RunDailyPipelineRequest(as_of_date=AS_OF_DATE, account_key=PAPER_ACCOUNT_KEY)
            ctx = RequestContext(
                request_id="pipeline-1",
                idempotency_key="daily-pipeline:test",
                dry_run=False,
                operator="tester",
                source="test",
            )

            first = service.run_daily_pipeline(request, ctx)
            second = service.run_daily_pipeline(
                request,
                RequestContext(
                    request_id="pipeline-2",
                    idempotency_key="daily-pipeline:test",
                    dry_run=False,
                    operator="tester",
                    source="test",
                ),
            )

            self.assertTrue(first.ok)
            self.assertEqual(first.data.pipeline_status, "pass")
            self.assertEqual(first.data.review_date, AS_OF_DATE)
            self.assertEqual(first.data.next_trade_date, BUY_DATE)
            self.assertIsNotNone(first.data.daily_pick_id)
            self.assertIsNotNone(first.data.trade_plan_id)
            self.assertIsNotNone(first.data.agent_run_id)
            self.assertEqual(first.data.exit_decisions, 0)
            self.assertTrue(first.data.changed)
            self.assertTrue(Path(first.data.backup_path).exists())
            self.assertTrue(Path(first.data.report_markdown).exists())
            self.assertTrue(Path(first.data.report_json).exists())
            self.assertEqual(first.data.market_review_status, "skipped")
            self.assertEqual(first.data.market_plan_context_status, "skipped")
            self.assertFalse(first.data.market_review_would_write)
            self.assertEqual(first.data.daily_operating_state, "apply_complete")
            self.assertTrue(first.data.can_run_today)
            self.assertEqual(first.data.write_intent, "apply_writes_with_backup")
            self.assertEqual(first.data.missing_requirements, [])

            self.assertFalse(second.ok)
            self.assertEqual(second.status, "blocked")
            self.assertEqual(second.data.pipeline_status, "blocked")
            self.assertEqual(second.data.daily_operating_state, "duplicate_apply_blocked")
            self.assertIn("duplicate_apply_review", second.data.missing_requirements)
            self.assertGreater(second.data.duplicate_apply_count, 0)

            post_apply_review = service.run_daily_pipeline(
                request,
                RequestContext(
                    request_id="pipeline-post-apply-dry-run",
                    idempotency_key="daily-pipeline:test",
                    dry_run=True,
                    operator="tester",
                    source="test",
                ),
            )

            self.assertTrue(post_apply_review.ok)
            self.assertEqual(post_apply_review.data.daily_operating_state, "dry_run_ready")
            self.assertGreater(post_apply_review.data.duplicate_apply_count, 0)
            self.assertIn("post-apply report review", post_apply_review.data.next_command)
            self.assertIn("--allow-rerun", post_apply_review.data.next_command)

            rerun_request = RunDailyPipelineRequest(
                as_of_date=AS_OF_DATE,
                account_key=PAPER_ACCOUNT_KEY,
                allow_rerun=True,
            )
            allowed_second = service.run_daily_pipeline(
                rerun_request,
                RequestContext(
                    request_id="pipeline-2-allowed",
                    idempotency_key="daily-pipeline:test",
                    dry_run=False,
                    operator="tester",
                    source="test",
                ),
            )

            self.assertTrue(allowed_second.ok)
            self.assertEqual(allowed_second.data.pipeline_status, "pass")
            self.assertTrue(allowed_second.data.changed)
            self.assertEqual(allowed_second.data.daily_pick_id, first.data.daily_pick_id)
            self.assertEqual(allowed_second.data.trade_plan_id, first.data.trade_plan_id)
            self.assertEqual(allowed_second.data.agent_run_id, first.data.agent_run_id)
            self.assertFalse(allowed_second.data.report_would_write)
            self.assertEqual(len(runner.calls), 1)

            Path(first.data.report_markdown).unlink()
            third = service.run_daily_pipeline(
                rerun_request,
                RequestContext(
                    request_id="pipeline-3",
                    idempotency_key="daily-pipeline:test",
                    dry_run=False,
                    operator="tester",
                    source="test",
                ),
            )

            self.assertTrue(third.ok)
            self.assertTrue(third.data.changed)
            self.assertTrue(Path(third.data.report_markdown).exists())
            self.assertFalse(third.data.report_would_write)

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(count_rows(conn, "daily_picks"), 1)
                self.assertEqual(count_rows(conn, "trade_plans"), 1)
                self.assertEqual(count_rows(conn, "agent_runs"), 1)
                self.assertEqual(count_rows(conn, "agent_decisions"), 1)
                self.assertEqual(count_rows(conn, "market_review_runs"), 0)
                self.assertEqual(count_rows(conn, "market_plan_contexts"), 0)
                self.assertEqual(count_rows(conn, "exit_decisions"), 0)

    def test_include_market_review_apply_persists_review_context_and_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = migrated_seeded_daily_close_db(root)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "Pipeline Market Review")

            runner = _FakeTradingAgentsRunner()
            service = DailyPipelineService(
                db_path,
                reports_dir=root / "reports",
                agent_review_service_factory=self._agent_factory(root, runner),
            )
            request = RunDailyPipelineRequest(
                as_of_date=AS_OF_DATE,
                account_key=PAPER_ACCOUNT_KEY,
                include_market_review=True,
            )
            ctx = RequestContext(
                request_id="pipeline-market-review-1",
                idempotency_key="daily-pipeline:market-review",
                dry_run=False,
                operator="tester",
                source="test",
            )

            first = service.run_daily_pipeline(request, ctx)
            second = service.run_daily_pipeline(
                request,
                RequestContext(
                    request_id="pipeline-market-review-2",
                    idempotency_key="daily-pipeline:market-review",
                    dry_run=False,
                    operator="tester",
                    source="test",
                ),
            )

            self.assertTrue(first.ok)
            self.assertEqual(first.data.market_review_status, "success")
            self.assertEqual(first.data.market_plan_context_status, "success")
            self.assertIsNotNone(first.data.market_review_run_id)
            self.assertFalse(first.data.market_review_would_write)
            self.assertIn("## 全市场复盘", Path(first.data.report_markdown).read_text(encoding="utf-8"))

            self.assertFalse(second.ok)
            self.assertEqual(second.data.daily_operating_state, "duplicate_apply_blocked")
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(count_rows(conn, "market_review_runs"), 1)
                self.assertEqual(count_rows(conn, "market_plan_contexts"), 1)

    def test_dry_run_previews_without_persisting_pipeline_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = migrated_seeded_daily_close_db(root)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "Pipeline Preview")

            runner = _FakeTradingAgentsRunner()
            result = DailyPipelineService(
                db_path,
                reports_dir=root / "reports",
                agent_review_service_factory=self._agent_factory(root, runner),
            ).run_daily_pipeline(
                RunDailyPipelineRequest(as_of_date=AS_OF_DATE, account_key=PAPER_ACCOUNT_KEY),
                RequestContext(
                    request_id="pipeline-dry-run",
                    idempotency_key="daily-pipeline:dry",
                    dry_run=True,
                    operator="tester",
                    source="test",
                ),
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.data.pipeline_status, "pass")
            self.assertIsNone(result.data.daily_pick_id)
            self.assertIsNone(result.data.agent_run_id)
            self.assertFalse(result.data.changed)
            self.assertIsNone(result.data.backup_path)
            self.assertEqual(result.data.report_status, "skipped")
            self.assertTrue(result.data.report_would_write)
            self.assertEqual(result.data.daily_operating_state, "dry_run_ready")
            self.assertTrue(result.data.can_run_today)
            self.assertEqual(result.data.write_intent, "dry_run_no_writes")
            self.assertIsNotNone(result.data.report_markdown)
            self.assertIsNotNone(result.data.report_json)
            self.assertFalse(Path(result.data.report_markdown).exists())
            self.assertFalse(Path(result.data.report_json).exists())
            self.assertFalse((root / "reports").exists())
            self.assertEqual(len(runner.calls), 0)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(count_rows(conn, "daily_picks"), 0)
                self.assertEqual(count_rows(conn, "trade_plans"), 0)
                self.assertEqual(count_rows(conn, "agent_runs"), 0)

    def test_include_market_review_dry_run_does_not_persist_market_review_or_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = migrated_seeded_daily_close_db(root)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "Pipeline Market Preview")

            runner = _FakeTradingAgentsRunner()
            result = DailyPipelineService(
                db_path,
                reports_dir=root / "reports",
                agent_review_service_factory=self._agent_factory(root, runner),
            ).run_daily_pipeline(
                RunDailyPipelineRequest(
                    as_of_date=AS_OF_DATE,
                    account_key=PAPER_ACCOUNT_KEY,
                    include_market_review=True,
                ),
                RequestContext(
                    request_id="pipeline-market-dry-run",
                    idempotency_key="daily-pipeline:market-dry",
                    dry_run=True,
                    operator="tester",
                    source="test",
                ),
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.data.pipeline_status, "pass")
            self.assertEqual(result.data.market_review_status, "success")
            self.assertIsNone(result.data.market_review_run_id)
            self.assertTrue(result.data.market_review_would_write)
            self.assertEqual(result.data.market_plan_context_status, "skipped")
            self.assertEqual(result.data.daily_operating_state, "evidence_pack_needed")
            self.assertFalse(result.data.can_run_today)
            self.assertIn("evidence_pack", result.data.missing_requirements)
            self.assertFalse(Path(result.data.report_markdown).exists())
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(count_rows(conn, "market_review_runs"), 0)
                self.assertEqual(count_rows(conn, "market_plan_contexts"), 0)

    def test_state_machine_blocks_when_data_refresh_is_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = migrated_seeded_daily_close_db(root)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                conn.execute(
                    """
                    INSERT INTO raw_events
                      (ts_code, code, name, entry_date, entry_time, entry_price)
                    VALUES
                      ('000001.SZ', '000001', 'Missing Bars', '20260427', '15:00', 10.0)
                    """
                )

            result = DailyPipelineService(db_path, reports_dir=root / "reports").run_daily_pipeline(
                RunDailyPipelineRequest(as_of_date=AS_OF_DATE, account_key=PAPER_ACCOUNT_KEY),
                RequestContext(
                    request_id="pipeline-missing-data",
                    idempotency_key="daily-pipeline:missing-data",
                    dry_run=True,
                    operator="tester",
                    source="test",
                ),
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.data.daily_operating_state, "data_refresh_needed")
            self.assertIn("market_data", result.data.missing_requirements)
            self.assertFalse(result.data.can_run_today)

    def test_state_machine_requires_pool_intake_apply_summary_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = migrated_seeded_daily_close_db(root)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "Pool Intake Pending")

            missing_summary = root / "daily_review_intake_apply.json"
            result = DailyPipelineService(db_path, reports_dir=root / "reports").run_daily_pipeline(
                RunDailyPipelineRequest(
                    as_of_date=AS_OF_DATE,
                    account_key=PAPER_ACCOUNT_KEY,
                    pool_intake_summary_path=missing_summary,
                    require_pool_intake=True,
                ),
                RequestContext(
                    request_id="pipeline-pool-pending",
                    idempotency_key="daily-pipeline:pool-pending",
                    dry_run=True,
                    operator="tester",
                    source="test",
                ),
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.data.daily_operating_state, "pool_intake_pending")
            self.assertEqual(result.data.pool_intake_status, "missing")
            self.assertIn("pool_intake", result.data.missing_requirements)

    def test_pipeline_surfaces_pool_intake_artifact_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = migrated_seeded_daily_close_db(root)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "Pipeline Pool Summary")
            summary = root / "daily_review_intake_apply.json"
            summary.write_text(
                json.dumps(
                    {
                        "mode": "apply",
                        "input_count": 4,
                        "added_count": 2,
                        "duplicate_count": 1,
                        "invalid_count": 1,
                        "source_hash": "hash-intake",
                    }
                ),
                encoding="utf-8",
            )

            result = DailyPipelineService(db_path, reports_dir=root / "reports").run_daily_pipeline(
                RunDailyPipelineRequest(
                    as_of_date=AS_OF_DATE,
                    account_key=PAPER_ACCOUNT_KEY,
                    pool_intake_summary_path=summary,
                ),
                RequestContext(
                    request_id="pipeline-pool-summary",
                    idempotency_key="daily-pipeline:pool-summary",
                    dry_run=True,
                    operator="tester",
                    source="test",
                ),
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.data.daily_operating_state, "pool_intake_pending")
            self.assertEqual(result.data.pool_intake_status, "available")
            self.assertEqual(result.data.pool_intake_mode, "apply")
            self.assertEqual(result.data.pool_intake_input_count, 4)
            self.assertEqual(result.data.pool_intake_added_count, 2)
            self.assertEqual(result.data.pool_intake_dedupe_count, 1)
            self.assertEqual(result.data.pool_intake_rejected_count, 1)
            self.assertEqual(result.data.pool_intake_audit_path, str(summary))

    def _agent_factory(
        self,
        root: Path,
        runner: _FakeTradingAgentsRunner,
    ):
        def factory(db_path: Path) -> AgentReviewService:
            return AgentReviewService(
                db_path,
                runner=runner,
                paths=TradingAgentsPaths(
                    results_dir=root / "agents" / "results",
                    cache_dir=root / "agents" / "cache",
                    memory_log_path=root / "agents" / "memory" / "trading_memory.md",
                ),
            )

        return factory


if __name__ == "__main__":
    unittest.main()
