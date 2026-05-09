from __future__ import annotations

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

            self.assertTrue(second.ok)
            self.assertEqual(second.data.pipeline_status, "pass")
            self.assertTrue(second.data.changed)
            self.assertEqual(second.data.daily_pick_id, first.data.daily_pick_id)
            self.assertEqual(second.data.trade_plan_id, first.data.trade_plan_id)
            self.assertEqual(second.data.agent_run_id, first.data.agent_run_id)
            self.assertFalse(second.data.report_would_write)
            self.assertEqual(len(runner.calls), 1)

            Path(first.data.report_markdown).unlink()
            third = service.run_daily_pipeline(
                request,
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
                self.assertEqual(count_rows(conn, "exit_decisions"), 0)

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
