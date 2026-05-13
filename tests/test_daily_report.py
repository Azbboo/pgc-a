from __future__ import annotations

import json
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pgc_trading.cli.main import main
from pgc_trading.reporting.daily_report import (
    DailyReportRequest,
    DailyReviewHistoryRequest,
    OpsHistoryRequest,
    PaperAcceptanceHistoryRequest,
    ReviewTimelineRequest,
    ReportingQueryService,
    render_daily_report_json,
    render_daily_report_markdown,
)
from pgc_trading.services.common import RequestContext
from pgc_trading.services.daily_close_workflow_service import (
    DailyCloseWorkflowService,
    RunDailyCloseWorkflowRequest,
)
from pgc_trading.services.execution_recording_service import (
    ExecutionRecordingService,
    RecordTradeRequest,
)
from pgc_trading.services.shadow_observation_service import build_shadow_replay_backtest_source_hash
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data


ACCOUNT_KEY = "paper-main"
AS_OF_DATE = "20260504"
BUY_DATE = "20260505"
T2_DATE = "20260507"
ENTRY_DATE = "20260427"


class DailyReportTest(unittest.TestCase):
    def test_report_renders_markdown_and_stable_json_for_plan_ready_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._plan_ready_db(tmp)

            result = ReportingQueryService(db_path).get_daily_report(
                DailyReportRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-report"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            self.assertEqual(result.data.data_quality.readiness, "pass")
            self.assertIsNotNone(result.data.paper_promotion)
            self.assertEqual(result.data.paper_promotion.trades_count, 0)
            self.assertIn("MIN_PAPER_TRADES_NOT_MET", result.data.paper_promotion.promotion_blockers)
            self.assertIsNotNone(result.data.paper_acceptance)
            self.assertEqual(result.data.paper_acceptance.status, "blocked")
            self.assertEqual(result.data.paper_acceptance.data_freshness.status, "pass")
            self.assertEqual(result.data.paper_acceptance.open_execution.next_action, "record_buy")
            self.assertTrue(
                any("MIN_PAPER_TRADES_NOT_MET" in item for item in result.data.paper_acceptance.unresolved_blockers)
            )
            self.assertTrue(
                any(alert.code == "UNRESOLVED_ACCEPTANCE_BLOCKERS" for alert in result.data.paper_acceptance.alerts)
            )
            self.assertIsNotNone(result.data.next_day_decision)
            self.assertEqual(result.data.next_day_decision.status, "blocked")
            self.assertEqual(result.data.next_day_decision.system_proposal.action, "record_buy")
            self.assertIsNotNone(result.data.next_day_decision.action_log)
            self.assertEqual(result.data.next_day_decision.action_log.items, [])
            self.assertTrue(
                any(item.key == "paper_acceptance" for item in result.data.next_day_decision.checklist)
            )
            self.assertIn("MIN_PAPER_TRADES_NOT_MET", result.data.next_day_decision.checklist[0].blocker_codes)
            self.assertEqual(result.data.candidate.ts_code, "000001.SZ")
            self.assertEqual(result.data.buy_plan.status, "active")

            markdown = render_daily_report_markdown(result.data)
            self.assertIn("## Paper 晋级分数卡", markdown)
            self.assertIn("## 纸盘每日运营验收", markdown)
            self.assertIn("数据新鲜度", markdown)
            self.assertIn("证据覆盖", markdown)
            self.assertIn("open-execution 状态", markdown)
            self.assertIn("readiness gates", markdown)
            self.assertIn("验收告警", markdown)
            self.assertIn("只读验收面板，不会执行交易", markdown)
            self.assertIn("## 下一交易日决策驾驶舱", markdown)
            self.assertIn("推荐人工动作", markdown)
            self.assertIn("决策清单", markdown)
            self.assertIn("动作日志 / 次日复核", markdown)
            self.assertIn("不会执行交易、开启 timer 或修改策略参数", markdown)
            self.assertIn("样本交易", markdown)
            self.assertIn("晋级 live 前还差什么", markdown)
            self.assertIn("## 今日候选", markdown)
            self.assertIn("000001.SZ Report Pick", markdown)
            self.assertIn("下一交易日开盘买入", markdown)
            self.assertNotIn("daily_pick_id", markdown)
            self.assertNotIn("trade_plan_id", markdown)

            payload = json.loads(render_daily_report_json(result.data))
            self.assertIn("shadow_observation", payload)
            self.assertEqual(payload["as_of_date"], AS_OF_DATE)
            self.assertIn("paper_promotion", payload)
            self.assertIn("paper_acceptance", payload)
            self.assertIn("next_day_decision", payload)
            self.assertEqual(payload["paper_acceptance"]["open_execution"]["next_action"], "record_buy")
            self.assertEqual(payload["next_day_decision"]["system_proposal"]["action"], "record_buy")
            self.assertEqual(payload["next_day_decision"]["checklist"][0]["key"], "paper_acceptance")
            self.assertIn("action_log", payload["next_day_decision"])
            self.assertEqual(payload["next_day_decision"]["action_log"]["items"], [])
            self.assertIn("readiness_gates", payload["paper_acceptance"])
            self.assertIn("alerts", payload["paper_acceptance"])
            self.assertIn("MIN_PAPER_TRADES_NOT_MET", payload["paper_promotion"]["promotion_blockers"])
            self.assertEqual(payload["candidate"]["daily_pick_id"], result.data.candidate.daily_pick_id)
            self.assertIn("data_quality", payload)
            self.assertIn("lineage", payload)

    def test_report_includes_market_plan_context_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._plan_ready_db(tmp)
            with sqlite3.connect(db_path) as conn:
                market_review_run_id = self._insert_market_plan_context(conn)

            result = ReportingQueryService(db_path).get_daily_report(
                DailyReportRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-report-market-plan-context"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data.market_plan_context)
            self.assertEqual(result.data.market_plan_context.market_review_run_id, market_review_run_id)
            self.assertEqual(result.data.market_plan_context.management_action, "proceed")
            self.assertEqual(result.data.lineage.market_review_run_id, market_review_run_id)
            self.assertIsNotNone(result.data.next_day_decision)
            self.assertEqual(result.data.next_day_decision.market_review.market_review_run_id, market_review_run_id)
            self.assertEqual(result.data.next_day_decision.strategy_proposals.review_required_count, 1)
            self.assertTrue(
                any(item.key == "strategy_proposals" for item in result.data.next_day_decision.checklist)
            )

            markdown = render_daily_report_markdown(result.data)
            self.assertIn("## 全市场复盘", markdown)
            self.assertIn("Top 5 板块", markdown)
            self.assertIn("连续性判断", markdown)
            self.assertIn("代表个股", markdown)
            self.assertIn("板块持续性", markdown)
            self.assertIn("外部证据覆盖", markdown)
            self.assertIn("策略假设", markdown)
            self.assertIn("## 全市场复盘与明日计划关系", markdown)
            self.assertIn("## 外部证据覆盖台账", markdown)
            self.assertIn("市场状态", markdown)
            self.assertIn("强势板块", markdown)
            self.assertIn("候选板块匹配", markdown)
            self.assertIn("新闻/情绪匹配", markdown)
            self.assertIn("计划关系", markdown)
            self.assertIn("不会自动创建、取消或执行交易计划", markdown)

            payload = json.loads(render_daily_report_json(result.data))
            self.assertIn("shadow_observation", payload)
            self.assertEqual(payload["market_review"]["market_review_run_id"], market_review_run_id)
            self.assertEqual(payload["market_review"]["continuity_label"], "improving")
            self.assertEqual(payload["market_review"]["top_sectors"][0]["sector_name"], "人工智能")
            self.assertEqual(payload["market_review"]["top_sectors"][0]["representative_stocks"][0]["ts_code"], "000001.SZ")
            self.assertEqual(payload["market_review"]["evidence_freshness"]["sector"], "fresh")
            self.assertEqual(payload["market_review"]["external_evidence_coverage"]["total_count"], 1)
            self.assertEqual(payload["market_review"]["external_evidence_coverage"]["sector"], "partial")
            self.assertEqual(payload["market_review"]["external_evidence_coverage"]["market"], "missing")
            self.assertIn("market", payload["market_review"]["external_evidence_coverage"]["missing_scopes"])
            self.assertEqual(payload["market_review"]["strategy_hypotheses"][0]["status"], "proposed")
            self.assertEqual(payload["market_plan_context"]["management_action"], "proceed")
            self.assertEqual(payload["market_plan_context"]["relationship_label"], "aligned")
            self.assertTrue(payload["evidence_coverage_ledger"]["safety"]["read_only"])
            self.assertFalse(payload["evidence_coverage_ledger"]["safety"]["live_fetches"])
            self.assertIn("missing", payload["evidence_coverage_ledger"]["state_counts"])
            self.assertEqual(payload["lineage"]["market_review_run_id"], market_review_run_id)
            self.assertEqual(payload["market_plan_context"]["evidence"]["top_sectors"][0]["sector_name"], "人工智能")
            self.assertEqual(payload["next_day_decision"]["strategy_proposals"]["proposed_count"], 1)

    def test_report_surfaces_shadow_hypothesis_blockers_as_research_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._plan_ready_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_market_plan_context(conn)
                self._insert_shadow_hypothesis(conn)

            result = ReportingQueryService(db_path).get_daily_report(
                DailyReportRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-report-shadow"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            markdown = render_daily_report_markdown(result.data)
            self.assertIn("shadow 1 条", markdown)
            self.assertIn("paper/proposal blocker 1 条", markdown)

            payload = json.loads(render_daily_report_json(result.data))
            shadow = [
                item
                for item in payload["market_review"]["strategy_hypotheses"]
                if item["hypothesis_type"] == "shadow_trend_extension_shadow"
            ][0]
            self.assertEqual(shadow["shadow_comparison"]["candidate_key"], "trend_extension_shadow")
            self.assertEqual(shadow["paper_observation_gate"]["status"], "blocked")
            self.assertIn("strategy_version_proposal_not_authorized", shadow["strategy_version_gate"]["blockers"])

    def test_report_includes_shadow_strategy_snapshot_block_from_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._plan_ready_db(tmp)
            reports_dir = Path(tmp) / "reports"
            reports_dir.mkdir()
            self._write_shadow_strategy_artifacts(reports_dir)
            self._write_shadow_evidence_closure_artifacts(reports_dir)
            self._write_shadow_replay_backtest_evidence(reports_dir, "trend_extension_shadow")

            result = ReportingQueryService(db_path, reports_dir=reports_dir).get_daily_report(
                DailyReportRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-report-shadow-snapshot"),
            )

            self.assertEqual(result.status, "success")
            shadow = result.data.shadow_strategy
            self.assertEqual(shadow.status, "blocked")
            self.assertEqual(shadow.latest_monitor_date, AS_OF_DATE)
            self.assertEqual(shadow.latest_preflight_date, AS_OF_DATE)
            self.assertEqual(shadow.candidate_count, 2)
            self.assertEqual(shadow.blocked_candidate_count, 2)
            self.assertEqual(shadow.distinct_blocker_count, 3)
            self.assertEqual(shadow.blocker_counts["operator_review_required"], 2)
            self.assertEqual(shadow.top_candidates[0].candidate_key, "trend_extension_shadow")
            self.assertEqual(shadow.top_candidates[0].today_top["name"], "Shadow Top")
            self.assertEqual(shadow.top_candidates[0].replay_backtest_evidence["status"], "accepted")
            self.assertEqual(shadow.replay_backtest_evidence["accepted_count"], 1)
            self.assertEqual(shadow.replay_backtest_evidence["missing_count"], 1)
            self.assertFalse(shadow.top_candidates[0].promotion_allowed)
            self.assertEqual(result.data.candidate.name, "Report Pick")

            markdown = render_daily_report_markdown(result.data)
            self.assertIn("## Shadow 策略观察", markdown)
            self.assertIn("shadow_observation", markdown)
            self.assertIn("monitor 2026-05-04 / preflight 2026-05-04", markdown)
            self.assertIn("operator_review_required 2", markdown)
            self.assertIn("replay/backtest evidence：accepted 1 / rejected 0 / missing 1", markdown)
            self.assertIn("trend_extension_shadow", markdown)
            self.assertIn("| candidate | family | status | today | walk_forward | blockers | top |", markdown)
            self.assertIn("source_refs", markdown)
            self.assertIn("research-only", markdown)
            self.assertIn("不会进入今日候选、生成交易计划或开启 timer", markdown)
            self.assertIn("## Shadow Evidence Closure", markdown)
            self.assertIn("## Shadow Walk-forward Outcomes", markdown)
            self.assertIn("signals 3", markdown)
            self.assertIn("artifact parity：dossier=pass", markdown)
            self.assertIn("review_request=pass", markdown)
            self.assertIn("scorecard=pass", markdown)
            self.assertIn("walk_forward_outcomes=pass", markdown)
            self.assertIn("Dashboard history parity：pass", markdown)
            self.assertIn("review_ready 不是批准", markdown)
            self.assertIn("## Shadow 中文决策备忘录", markdown)
            self.assertIn("shadow_decision_memo_v1", markdown)
            self.assertIn("不 approve、不 promote、不创建交易计划、不记录成交、不改持仓、不改 paper/live、不改 timer", markdown)

            payload = json.loads(render_daily_report_json(result.data))
            self.assertEqual(payload["shadow_observation"]["status"], "blocked")
            self.assertEqual(payload["shadow_observation"]["top_candidates"][0]["today_top"]["name"], "Shadow Top")
            self.assertEqual(
                payload["shadow_observation"]["top_candidates"][0]["replay_backtest_evidence"]["status"],
                "accepted",
            )
            self.assertEqual(payload["shadow_strategy"]["status"], "blocked")
            self.assertEqual(payload["shadow_strategy"]["top_candidates"][0]["today_top"]["name"], "Shadow Top")
            self.assertEqual(payload["shadow_evidence"]["artifact_summary"]["scorecard"], "pass")
            self.assertEqual(payload["shadow_evidence"]["artifact_summary"]["dossier"], "pass")
            self.assertEqual(payload["shadow_evidence"]["artifact_summary"]["review_request"], "pass")
            self.assertEqual(payload["shadow_evidence"]["artifact_summary"]["walk_forward_outcomes"], "pass")
            self.assertEqual(payload["shadow_walk_forward_outcomes"]["summary"]["signal_count"], 3)
            self.assertTrue(payload["shadow_walk_forward_outcomes"]["no_future_boundary"]["passed"])
            self.assertEqual(payload["shadow_evidence"]["dashboard_history_parity"]["status"], "pass")
            self.assertIn("preconfirm_watchlist", ";".join(payload["shadow_evidence"]["missing_blockers"]))
            self.assertEqual(payload["shadow_decision_memo"]["memo_contract"], "shadow_decision_memo_v1")
            self.assertIn("候选概览", payload["shadow_decision_memo"]["sections"])
            self.assertIn("证据状态", payload["shadow_decision_memo"]["sections"])
            self.assertIn("阻断原因", payload["shadow_decision_memo"]["sections"])
            self.assertIn("下一步实验", payload["shadow_decision_memo"]["sections"])
            self.assertIn("人工决策", payload["shadow_decision_memo"]["sections"])
            self.assertIn("风险/回滚边界", payload["shadow_decision_memo"]["sections"])
            self.assertFalse(payload["shadow_decision_memo"]["safety"]["promotion_allowed"])
            self.assertFalse(payload["shadow_decision_memo"]["safety"]["writes_trade_state"])
            self.assertFalse(payload["shadow_decision_memo"]["safety"]["timer_mutated"])
            self.assertEqual(payload["candidate"]["name"], "Report Pick")
            self.assertFalse(payload["shadow_strategy"]["safety"]["promotion_allowed"])

    def test_report_includes_decision_action_log_review_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._plan_ready_db(tmp)
            with sqlite3.connect(db_path) as conn:
                trade_plan_id = int(conn.execute("SELECT id FROM trade_plans ORDER BY id DESC LIMIT 1").fetchone()[0])
                conn.execute(
                    """
                    INSERT INTO decision_action_logs
                      (
                        account_id,
                        review_date,
                        execution_date,
                        cockpit_status,
                        system_action,
                        operator_decision,
                        operator_note,
                        target_type,
                        target_id,
                        blocker_codes_json,
                        warning_codes_json,
                        source_refs_json,
                        operator
                      )
                    VALUES
                      (1, ?, ?, 'blocked', 'record_buy', 'deferred', 'Wait for evidence.', 'trade_plan', ?, ?, '[]', ?, 'tester')
                    """,
                    (
                        AS_OF_DATE,
                        BUY_DATE,
                        trade_plan_id,
                        json.dumps(["MARKET_EVIDENCE_MISSING"]),
                        json.dumps([f"trade_plans:{trade_plan_id}"]),
                    ),
                )

            result = ReportingQueryService(db_path).get_daily_report(
                DailyReportRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-report-action-log"),
            )

            self.assertEqual(result.status, "success")
            action_log = result.data.next_day_decision.action_log
            self.assertIsNotNone(action_log)
            self.assertEqual(action_log.deferred_count, 1)
            self.assertEqual(action_log.items[0].operator_decision, "deferred")
            self.assertEqual(action_log.items[0].outcome.outcome_status, "deferred")
            self.assertIn("MARKET_EVIDENCE_MISSING", action_log.unresolved_blocker_codes)

            markdown = render_daily_report_markdown(result.data)
            self.assertIn("动作日志 / 次日复核", markdown)
            self.assertIn("deferred record_buy", markdown)
            self.assertIn("outcome=deferred/deferred", markdown)
            payload = json.loads(render_daily_report_json(result.data))
            self.assertEqual(payload["next_day_decision"]["action_log"]["deferred_count"], 1)
            self.assertEqual(payload["next_day_decision"]["action_log"]["deferred_outcome_count"], 1)
            self.assertEqual(
                payload["next_day_decision"]["action_log"]["items"][0]["outcome"]["outcome_status"],
                "deferred",
            )
            self.assertEqual(
                payload["next_day_decision"]["action_log"]["items"][0]["outcome"]["outcome_bucket"],
                "deferred",
            )

    def test_review_history_lists_latest_runs_with_pick_plan_and_no_candidate_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._plan_ready_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_no_candidate_review_run(conn, "20260506")

            result = ReportingQueryService(db_path).list_daily_review_history(
                DailyReviewHistoryRequest(account_key=ACCOUNT_KEY, limit=10),
                RequestContext(request_id="req-review-history"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            self.assertEqual([item.review_date for item in result.data.items], ["20260506", AS_OF_DATE])
            self.assertEqual(result.data.account.account_key, ACCOUNT_KEY)
            self.assertIsNone(result.data.items[0].daily_pick_id)
            self.assertEqual(result.data.items[0].signals_count, 0)
            self.assertEqual(result.data.items[0].warning_count, 1)
            self.assertEqual(result.data.items[1].ts_code, "000001.SZ")
            self.assertEqual(result.data.items[1].trade_plan_status, "active")
            self.assertEqual(result.data.items[1].next_trade_date, BUY_DATE)

    def test_paper_acceptance_history_tracks_alerts_and_trends(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._plan_ready_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_no_candidate_review_run(conn, "20260506")

            result = ReportingQueryService(db_path).list_paper_acceptance_history(
                PaperAcceptanceHistoryRequest(account_key=ACCOUNT_KEY, limit=10),
                RequestContext(request_id="req-acceptance-history"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            self.assertEqual([item.as_of_date for item in result.data.items], ["20260506", AS_OF_DATE])
            self.assertEqual(result.data.account.account_key, ACCOUNT_KEY)
            self.assertEqual(result.data.trend["days"], 2)
            self.assertEqual(result.data.trend["blocked_days"], 2)
            self.assertEqual(result.data.trend["latest_as_of_date"], "20260506")
            self.assertGreaterEqual(result.data.trend["missing_agent_days"], 1)
            self.assertTrue(result.data.items[0].warning_count >= 1)
            self.assertTrue(result.data.items[0].unresolved_blocker_count >= 1)
            self.assertIn("UNRESOLVED_ACCEPTANCE_BLOCKERS", result.data.items[0].alert_codes)
            self.assertTrue(any(alert.code == "AGENT_REVIEW_MISSING" for alert in result.data.alerts))
            self.assertIn("近 2 日 paper acceptance", result.data.summary)
            self.assertIn("alert_count", result.lineage)

    def test_ops_history_combines_pipeline_steps_and_acceptance_snapshots_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._plan_ready_db(tmp)
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO operation_requests
                      (
                        idempotency_key,
                        request_id,
                        operation_type,
                        account_id,
                        as_of_date,
                        status,
                        request_json,
                        response_json,
                        operator,
                        started_at,
                        finished_at
                      )
                    VALUES
                      (?, 'req-pipeline', 'daily_review', 1, ?, 'success', ?, ?, 'tester',
                       '2026-05-10 16:20:00', '2026-05-10 16:20:03')
                    """,
                    (
                        f"daily-pipeline:{ACCOUNT_KEY}:{AS_OF_DATE}:cpb_6157@2026-05-03:paper:daily-close",
                        AS_OF_DATE,
                        '{"dry_run": false}',
                        '{"status": "success"}',
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO operation_requests
                      (
                        idempotency_key,
                        request_id,
                        operation_type,
                        account_id,
                        as_of_date,
                        status,
                        request_json,
                        response_json,
                        operator,
                        started_at,
                        finished_at
                      )
                    VALUES
                      (?, 'req-action-log', 'decision_action_log', 1, ?, 'success', ?, ?, 'tester',
                       '2026-05-10 16:25:00', '2026-05-10 16:25:01')
                    """,
                    (
                        f"decision-action-log:{ACCOUNT_KEY}:{AS_OF_DATE}:followed:record_buy",
                        AS_OF_DATE,
                        json.dumps(
                            {
                                "dry_run": False,
                                "request": {
                                    "operator_decision": "followed",
                                    "system_action": "record_buy",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "decision_action_log_id": 7,
                                "system_action": "record_buy",
                                "operator_decision": "followed",
                                "writes_trade_state": False,
                                "writes_strategy_state": False,
                                "enables_timer": False,
                                "outcome": {
                                    "outcome_bucket": "matched",
                                    "outcome_status": "matched",
                                    "outcome_review_date": "20260506",
                                    "matched_trade_id": 12,
                                },
                            }
                        ),
                    ),
                )

            log_dir = Path(tmp) / "empty-ops-logs"
            timer_dir = Path(tmp) / "empty-timer-logs"
            release_dir = Path(tmp) / "empty-release"
            log_dir.mkdir()
            timer_dir.mkdir()
            release_dir.mkdir()
            with patch.dict(
                "os.environ",
                {
                    "PGC_DAILY_PIPELINE_LOG_DIR": str(log_dir),
                    "PGC_TIMER_EVIDENCE_DIR": str(timer_dir),
                    "PGC_ARTIFACT_DIR": str(release_dir),
                },
            ):
                result = ReportingQueryService(db_path).list_ops_history(
                    OpsHistoryRequest(account_key=ACCOUNT_KEY, limit=20),
                    RequestContext(request_id="req-ops-history"),
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            categories = {item.category for item in result.data.items}
            self.assertIn("pipeline_step", categories)
            self.assertIn("paper_acceptance", categories)
            self.assertIn("decision_action_log", categories)
            pipeline_item = next(item for item in result.data.items if item.category == "pipeline_step")
            self.assertEqual(pipeline_item.source, "operation_requests")
            self.assertFalse(pipeline_item.details["dry_run"])
            action_log_item = next(item for item in result.data.items if item.category == "decision_action_log")
            self.assertIn("outcome=matched/matched", action_log_item.summary)
            self.assertEqual(action_log_item.details["outcome_bucket"], "matched")
            self.assertEqual(action_log_item.details["matched_trade_id"], 12)
            self.assertFalse(action_log_item.details["writes_trade_state"])
            self.assertTrue(action_log_item.details["advisory_only"])
            acceptance_item = next(item for item in result.data.items if item.category == "paper_acceptance")
            self.assertEqual(acceptance_item.as_of_date, AS_OF_DATE)
            self.assertTrue(acceptance_item.details["read_only_history"])
            self.assertTrue(result.lineage["read_only"])
            self.assertIn("Ops history", result.data.summary)

    def test_review_timeline_combines_review_market_plan_context_and_execution_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._plan_ready_db(tmp)
            with sqlite3.connect(db_path) as conn:
                market_review_run_id = self._insert_market_plan_context(conn)

            result = ReportingQueryService(db_path).list_review_timeline(
                ReviewTimelineRequest(account_key=ACCOUNT_KEY, limit=5),
                RequestContext(request_id="req-review-timeline"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            self.assertEqual(len(result.data.items), 1)
            item = result.data.items[0]
            self.assertEqual(item.review_date, AS_OF_DATE)
            self.assertEqual(item.next_trade_date, BUY_DATE)
            self.assertEqual(item.ts_code, "000001.SZ")
            self.assertEqual(item.trade_plan_status, "active")
            self.assertEqual(item.market_review_run_id, market_review_run_id)
            self.assertEqual(item.market_regime, "risk_on")
            self.assertEqual(item.plan_context_management_action, "proceed")
            self.assertEqual(item.plan_context_risk_level, "low")
            self.assertEqual(item.open_execution_as_of_date, BUY_DATE)
            self.assertEqual(item.open_execution_status, "ready")
            self.assertEqual(item.open_execution_next_action, "record_buy")
            self.assertEqual(item.open_execution_primary_plan_id, item.trade_plan_id)
            self.assertIn("does not change", result.data.execution_context_note)

    def test_report_includes_agent_points_and_report_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._plan_ready_db(tmp)
            report_path = Path(tmp) / "agent_report.md"
            report_path.write_text("# Agent Report\n\nDetailed advisory.\n", encoding="utf-8")
            with sqlite3.connect(db_path) as conn:
                self._insert_agent_review(conn, report_path)

            result = ReportingQueryService(db_path).get_daily_report(
                DailyReportRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-report-agent"),
            )

            self.assertEqual(result.status, "success")
            advice = result.data.agent_advice
            self.assertEqual(advice.status, "completed")
            self.assertEqual(advice.action, "support")
            self.assertEqual(advice.supporting_points, ["score is strong", "portfolio has room"])
            self.assertEqual(advice.risk_points, ["gap risk"])
            self.assertEqual(
                advice.source_refs,
                ["agent_external_items:42", "market_diagnostic_bars:yfinance:000001.SZ:20260504"],
            )
            self.assertEqual(
                advice.external_data_coverage,
                {
                    "fundamental": "partial",
                    "news": "unavailable",
                    "sector": "unavailable",
                    "sentiment": "partial",
                    "technical": "available",
                },
            )
            self.assertEqual([item.source_ref for item in advice.external_evidence], [
                "agent_external_items:42",
                "market_diagnostic_bars:yfinance:000001.SZ:20260504",
            ])
            self.assertEqual(advice.external_evidence[0].source, "tushare")
            self.assertEqual(advice.external_evidence[0].category, "fundamental")
            self.assertEqual(advice.missing_data_warnings, ["新闻/公告未接入/数据不足。"])
            self.assertEqual([report.analyst_key for report in advice.analyst_reports], ["fundamental", "technical"])
            self.assertEqual(advice.analyst_reports[1].summary, "技术面转强。")
            self.assertEqual(advice.execution_mode, "local_snapshot_mode")
            self.assertEqual(advice.source_label, "TradingAgents 本地快照模式")
            self.assertEqual([section.section_key for section in advice.report_sections], [
                "fundamental",
                "news",
                "sentiment",
                "technical",
                "sector",
                "risk",
                "conclusion",
            ])
            self.assertEqual(advice.report_markdown, "# Agent Report\n\nDetailed advisory.\n")
            self.assertEqual([artifact.artifact_type for artifact in advice.artifacts], ["decision_json", "final_report"])

            markdown = render_daily_report_markdown(result.data)
            self.assertIn("支持依据", markdown)
            self.assertIn("score is strong", markdown)
            self.assertIn("风险提示", markdown)
            self.assertIn("中文结构化报告", markdown)
            self.assertIn("运行模式：local_snapshot_mode", markdown)
            self.assertIn("### 板块位置", markdown)
            self.assertIn("数据覆盖", markdown)
            self.assertIn("外部证据", markdown)
            self.assertIn("未接入/缺失", markdown)
            payload = json.loads(render_daily_report_json(result.data))
            self.assertEqual(payload["agent_advice"]["supporting_points"], ["score is strong", "portfolio has room"])
            self.assertEqual(payload["agent_advice"]["source_refs"][0], "agent_external_items:42")
            self.assertEqual(payload["agent_advice"]["external_data_coverage"]["news"], "unavailable")
            self.assertEqual(payload["agent_advice"]["external_evidence"][0]["source"], "tushare")
            self.assertEqual(payload["agent_advice"]["missing_data_warnings"], ["新闻/公告未接入/数据不足。"])
            self.assertEqual(payload["agent_advice"]["analyst_reports"][0]["analyst_name"], "基本面")
            self.assertEqual(payload["agent_advice"]["report_sections"][4]["section_name"], "板块位置")
            self.assertEqual(payload["agent_advice"]["artifacts"][1]["artifact_type"], "final_report")
            self.assertNotIn("path", payload["agent_advice"]["artifacts"][1])

    def test_report_surfaces_explicit_no_candidate_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_calendar(conn)

            close = DailyCloseWorkflowService(db_path).run_daily_close(
                RunDailyCloseWorkflowRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-close-no-candidate", operator="tester"),
            )
            self.assertEqual(close.status, "skipped")

            result = ReportingQueryService(db_path).get_daily_report(
                DailyReportRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-report-no-candidate"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNone(result.data.candidate)
            self.assertEqual(result.data.no_candidate_reason, "no_strategy_signals")
            self.assertIn("今日没有可执行候选", render_daily_report_markdown(result.data))

    def test_report_lists_due_buy_day_two_position_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._plan_ready_db(tmp)
            with sqlite3.connect(db_path) as conn:
                plan_id = int(conn.execute("SELECT id FROM trade_plans").fetchone()[0])

            trade = ExecutionRecordingService(db_path).record_trade(
                RecordTradeRequest(
                    account_key=ACCOUNT_KEY,
                    trade_plan_id=plan_id,
                    side="buy",
                    executed_date=BUY_DATE,
                    executed_price=10.0,
                    shares=1000,
                    source="paper_model",
                ),
                RequestContext(request_id="req-buy-for-report", operator="tester"),
            )
            self.assertEqual(trade.status, "success")
            with sqlite3.connect(db_path) as conn:
                self._insert_market_bar(conn, "000001.SZ", T2_DATE, close=10.3)

            result = ReportingQueryService(db_path).get_daily_report(
                DailyReportRequest(as_of_date=T2_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-report-t2"),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(len(result.data.due_positions), 1)
            self.assertEqual(result.data.due_positions[0].action_due, "buy_day_2_decision")
            self.assertIn("需要 T+2 判断", render_daily_report_markdown(result.data))

    def test_cli_report_writes_to_explicit_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._plan_ready_db(tmp)
            output_path = Path(tmp) / "daily_review.md"
            stdout = io.StringIO()
            code = main(
                [
                    "report",
                    "daily",
                    "--as-of-date",
                    AS_OF_DATE,
                    "--account",
                    ACCOUNT_KEY,
                    "--db-path",
                    str(db_path),
                    "--output",
                    str(output_path),
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 0)
            self.assertIn("report written for 20260504", stdout.getvalue())
            self.assertTrue(output_path.exists())
            self.assertIn("PGC 每日复盘报告", output_path.read_text(encoding="utf-8"))

    def _plan_ready_db(self, tmp: str) -> Path:
        db_path = self._migrated_seeded_db(tmp)
        with sqlite3.connect(db_path) as conn:
            self._insert_calendar(conn)
            self._insert_contracting_pullback_case(conn)
        result = DailyCloseWorkflowService(db_path).run_daily_close(
            RunDailyCloseWorkflowRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
            RequestContext(
                request_id="req-close-report",
                idempotency_key=f"daily-close:report:{tmp}",
                operator="tester",
            ),
        )
        self.assertEqual(result.status, "success")
        return db_path

    def _migrated_seeded_db(self, tmp: str) -> Path:
        db_path = Path(tmp) / "pgc.db"
        run_migrations(db_path)
        seed_reference_data(db_path)
        return db_path

    def _insert_calendar(self, conn: sqlite3.Connection) -> None:
        conn.executemany(
            """
            INSERT OR REPLACE INTO trade_calendar
              (exchange, cal_date, is_open, pretrade_date)
            VALUES
              ('SSE', ?, ?, ?)
            """,
            [
                ("20260501", 1, "20260430"),
                (AS_OF_DATE, 1, "20260501"),
                (BUY_DATE, 1, AS_OF_DATE),
                ("20260506", 1, BUY_DATE),
                (T2_DATE, 1, "20260506"),
                ("20260508", 1, T2_DATE),
                ("20260509", 0, "20260508"),
                ("20260510", 0, "20260508"),
                ("20260511", 1, "20260508"),
                ("20260512", 1, "20260511"),
            ],
        )

    def _insert_contracting_pullback_case(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO raw_events
              (ts_code, code, name, entry_date, entry_time, entry_price)
            VALUES
              ('000001.SZ', '000001', 'Report Pick', ?, '15:00', 10.0)
            """,
            (ENTRY_DATE,),
        )
        bars = [
            ("20260424", 9.6, 9.8, 9.5, 9.7, 950.0),
            (ENTRY_DATE, 10.0, 10.2, 9.9, 10.0, 1000.0),
            ("20260428", 10.8, 11.2, 10.7, 11.0, 1200.0),
            ("20260429", 10.6, 10.7, 10.4, 10.5, 1000.0),
            ("20260430", 10.3, 10.4, 9.95, 10.0, 800.0),
            ("20260501", 9.8, 9.85, 9.55, 9.65, 700.0),
            (AS_OF_DATE, 9.7, 10.0, 9.6, 9.9, 900.0),
        ]
        for trade_date, open_price, high, low, close, amount in bars:
            self._insert_market_bar(
                conn,
                "000001.SZ",
                trade_date,
                open_price=open_price,
                high=high,
                low=low,
                close=close,
                amount=amount,
            )

    def _insert_agent_review(self, conn: sqlite3.Connection, report_path: Path) -> None:
        daily_pick = conn.execute("SELECT id, signal_id, review_date FROM daily_picks LIMIT 1").fetchone()
        snapshot_id = conn.execute(
            """
            INSERT INTO input_snapshots
              (snapshot_type, as_of_date, signal_id, daily_pick_id, source_refs_json, payload_json, content_hash)
            VALUES
              ('tradingagents_candidate_review', ?, ?, ?, ?, ?, 'agent-report-test')
            """,
            (
                daily_pick[2],
                daily_pick[1],
                daily_pick[0],
                json.dumps(
                    ["agent_external_items:42", "market_diagnostic_bars:yfinance:000001.SZ:20260504"],
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "external_data_coverage": {
                            "fundamental": "partial",
                            "news": "unavailable",
                            "sentiment": "partial",
                            "technical": "available",
                            "sector": "unavailable",
                        },
                        "candidate": {
                            "ts_code": "000001.SZ",
                            "external_data": {
                                "items": {
                                    "items": [
                                        {
                                            "id": 42,
                                            "published_date": "20260504",
                                            "item_type": "fundamental",
                                            "provider": "tushare",
                                            "title": "估值快照",
                                            "summary": "PE/PB/turnover fields from cached provider",
                                            "sentiment": "neutral",
                                            "importance": "medium",
                                        }
                                    ]
                                }
                            },
                            "analysis_contexts": {
                                "technical": {
                                    "external_market_diagnostics": {
                                        "providers": [
                                            {
                                                "provider": "yfinance",
                                                "last_trade_date": "20260504",
                                                "last_close": 10.4,
                                            }
                                        ]
                                    }
                                }
                            },
                            "evidence_context": {
                                "missing_data_warnings": ["新闻/公告未接入/数据不足。"]
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
            ),
        ).lastrowid
        run_id = conn.execute(
            """
            INSERT INTO agent_runs
              (agent_system, agent_version, signal_id, daily_pick_id, input_snapshot_id, as_of_date, config_json, config_hash, status)
            VALUES
              ('TradingAgents', 'external', ?, ?, ?, ?, '{}', 'agent-config-test', 'completed')
            """,
            (daily_pick[1], daily_pick[0], snapshot_id, daily_pick[2]),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO agent_decisions
              (agent_run_id, signal_id, daily_pick_id, action, confidence, risk_level, summary, supporting_points_json, risk_points_json, raw_decision_json)
            VALUES
              (?, ?, ?, 'support', 0.75, 'medium', 'Agent supports the plan.', ?, ?, ?)
            """,
            (
                run_id,
                daily_pick[1],
                daily_pick[0],
                json.dumps(["score is strong", "portfolio has room"], ensure_ascii=False),
                json.dumps(["gap risk"], ensure_ascii=False),
                json.dumps(
                    {
                        "execution_source": {
                            "mode": "local_snapshot_mode",
                            "source_label": "TradingAgents 本地快照模式",
                            "agent_system": "TradingAgents",
                        },
                        "supporting_points": ["fallback"],
                        "risk_points": ["fallback"],
                        "analyst_reports": {
                            "technical": {
                                "status": "available",
                                "summary": "技术面转强。",
                                "supporting_points": ["放量突破"],
                                "risk_points": ["高开回落"],
                            },
                            "fundamental": {
                                "status": "partial",
                                "summary": "基本面数据有限。",
                                "supporting_points": ["市值适中"],
                                "risk_points": ["缺少财报快照"],
                            },
                        },
                        "report_sections": {
                            "fundamental": {
                                "section_name": "基本面",
                                "status": "partial",
                                "source_label": "TradingAgents 本地快照模式；来源：daily_basic_snapshots",
                                "summary": "基本面数据有限。",
                                "supporting_points": ["市值适中"],
                                "risk_points": ["缺少财报快照"],
                            },
                            "news": {
                                "section_name": "新闻",
                                "status": "unavailable",
                                "source_label": "TradingAgents 本地快照模式；来源未接入/数据不足",
                                "summary": "新闻数据源未接入/数据不足。",
                                "supporting_points": [],
                                "risk_points": ["新闻缺少真实输入，不能编造相关证据。"],
                            },
                            "sentiment": {
                                "section_name": "情绪",
                                "status": "partial",
                                "source_label": "TradingAgents 本地快照模式；来源：market-derived",
                                "summary": "市场行为推断情绪偏热。",
                                "supporting_points": ["放量"],
                                "risk_points": ["拥挤"],
                            },
                            "technical": {
                                "section_name": "技术/量价",
                                "status": "available",
                                "source_label": "TradingAgents 本地快照模式；来源：market_bars",
                                "source_refs": ["market_diagnostic_bars:yfinance:000001.SZ:20260504"],
                                "summary": "技术面转强。",
                                "supporting_points": ["放量突破"],
                                "risk_points": ["高开回落"],
                            },
                            "sector": {
                                "section_name": "板块位置",
                                "status": "unavailable",
                                "source_label": "TradingAgents 本地快照模式；来源未接入/数据不足",
                                "summary": "板块位置数据源未接入/数据不足。",
                                "supporting_points": [],
                                "risk_points": ["板块位置缺少真实输入，不能编造相关证据。"],
                            },
                            "risk": {
                                "section_name": "风险",
                                "status": "available",
                                "source_label": "TradingAgents 本地快照模式；综合结构化复核输出",
                                "summary": "需要关注高开回落。",
                                "supporting_points": [],
                                "risk_points": ["gap risk"],
                            },
                            "conclusion": {
                                "section_name": "结论",
                                "status": "available",
                                "source_label": "TradingAgents 本地快照模式；综合结构化复核输出",
                                "summary": "Agent supports the plan.",
                                "supporting_points": ["score is strong"],
                                "risk_points": ["gap risk"],
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        conn.execute(
            """
            INSERT INTO agent_artifacts
              (agent_run_id, artifact_type, path, content_hash)
            VALUES
              (?, 'decision_json', ?, 'decision-hash'),
              (?, 'final_report', ?, 'report-hash')
            """,
            (run_id, str(report_path.with_suffix(".json")), run_id, str(report_path)),
        )

    def _insert_market_plan_context(self, conn: sqlite3.Connection) -> int:
        trade_plan_id = int(conn.execute("SELECT id FROM trade_plans ORDER BY id DESC LIMIT 1").fetchone()[0])
        run_id = int(
            conn.execute(
                """
                INSERT INTO market_review_runs
                  (as_of_date, status, provider_manifest_json, coverage_json, summary_json, completed_at)
                VALUES
                  (?, 'completed', '{}', '{}', '{}', CURRENT_TIMESTAMP)
                """,
                (AS_OF_DATE,),
            ).lastrowid
        )
        conn.execute(
            """
            INSERT INTO market_regime_snapshots
              (
                market_review_run_id,
                as_of_date,
                regime,
                breadth_score,
                trend_score,
                volume_score,
                sentiment_score,
                persistence_score,
                summary
              )
            VALUES
              (?, ?, 'risk_on', 0.72, 0.68, 0.66, 0.61, 0.80, 'Market review supports the plan.')
            """,
            (run_id, AS_OF_DATE),
        )
        conn.execute(
            """
            INSERT INTO sector_daily_snapshots
              (
                market_review_run_id,
                as_of_date,
                sector_code,
                sector_name,
                provider,
                rank_overall,
                return_1d,
                return_3d,
                breadth_score,
                volume_score,
                persistence_score,
                leader_count
              )
            VALUES
              (?, ?, 'AI', '人工智能', 'manual_test', 1, 0.023, 0.061, 0.82, 0.74, 0.80, 3)
            """,
            (run_id, AS_OF_DATE),
        )
        conn.execute(
            """
            INSERT INTO sector_constituents
              (market_review_run_id, sector_code, sector_name, ts_code, name, rank_in_sector, role, score)
            VALUES
              (?, 'AI', '人工智能', '000001.SZ', 'Report Pick', 1, 'leader', 0.91)
            """,
            (run_id,),
        )
        conn.execute(
            """
            INSERT INTO market_external_items
              (
                as_of_date,
                scope_type,
                scope_key,
                item_type,
                provider,
                title,
                summary,
                sentiment,
                importance,
                published_date,
                source_hash
              )
            VALUES
              (?, 'sector', 'AI', 'news', 'manual_test', '行业景气度改善', '需求改善。', 'positive', 'medium', ?, 'daily-report-ai-news')
            """,
            (AS_OF_DATE, AS_OF_DATE),
        )
        conn.execute(
            """
            INSERT INTO strategy_hypotheses
              (as_of_date, hypothesis_type, title, rationale, evidence_json, proposed_change_json, status)
            VALUES
              (?, 'sector_filter', '提高持续性板块权重', '人工智能板块持续性较强。', '{}', '{}', 'proposed')
            """,
            (AS_OF_DATE,),
        )
        evidence = {
            "market_regime": {
                "regime": "risk_on",
                "breadth_score": 0.72,
                "trend_score": 0.68,
                "persistence_score": 0.80,
                "summary": "Market review supports the plan.",
            },
            "top_sectors": [
                {
                    "sector_code": "AI",
                    "sector_name": "人工智能",
                    "rank_overall": 1,
                    "persistence_score": 0.80,
                }
            ],
            "candidate_sector": {
                "sector_code": "AI",
                "sector_name": "人工智能",
                "rank_overall": 1,
                "role": "leader",
                "persistence_score": 0.80,
            },
            "external_items": [
                {
                    "title": "行业景气度改善",
                    "sentiment": "positive",
                    "importance": "medium",
                }
            ],
        }
        conn.execute(
            """
            INSERT INTO market_plan_contexts
              (market_review_run_id, trade_plan_id, alignment, risk_level, management_action, rationale, evidence_json)
            VALUES
              (?, ?, 'aligned', 'low', 'proceed', 'Sector and evidence support the plan.', ?)
            """,
            (run_id, trade_plan_id, json.dumps(evidence, ensure_ascii=False)),
        )
        return run_id

    def _insert_shadow_hypothesis(self, conn: sqlite3.Connection) -> None:
        evidence = {
            "source": "m69_shadow_research",
            "as_of_date": AS_OF_DATE,
            "artifact_only": True,
            "shadow_comparison": {
                "candidate_key": "trend_extension_shadow",
                "daily_top1_metrics": {"n": 24, "t1_close_mean_pct": 1.11},
            },
            "paper_observation_gate": {
                "status": "blocked",
                "blockers": ["paper_observation_not_authorized"],
            },
            "strategy_version_gate": {
                "status": "blocked",
                "blockers": ["strategy_version_proposal_not_authorized"],
            },
        }
        proposed_change = {
            "strategy_id": "cpb_6157",
            "change_type": "shadow_candidate",
            "candidate_key": "trend_extension_shadow",
            "artifact_only": True,
            "requires_replay_backtest": True,
            "mutates_active_params": False,
        }
        conn.execute(
            """
            INSERT INTO strategy_hypotheses
              (as_of_date, hypothesis_type, title, rationale, evidence_json, proposed_change_json, status)
            VALUES
              (?, 'shadow_trend_extension_shadow', 'Shadow trend extension', 'Research only.', ?, ?, 'proposed')
            """,
            (
                AS_OF_DATE,
                json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                json.dumps(proposed_change, ensure_ascii=False, sort_keys=True),
            ),
        )

    def _write_shadow_strategy_artifacts(self, reports_dir: Path) -> None:
        gates = [
            {
                "candidate_key": "trend_extension_shadow",
                "candidate_family": "shadow_bucket",
                "status": "blocked",
                "walk_forward_progress": {"status": "partial", "required_days": 20, "days": 12},
                "paper_observation_gate": {
                    "status": "blocked",
                    "allowed": False,
                    "artifact_only": True,
                    "blockers": ["operator_review_required", "paper_observation_not_authorized"],
                },
                "strategy_version_gate": {
                    "status": "blocked",
                    "allowed": False,
                    "artifact_only": True,
                    "blockers": ["strategy_version_proposal_not_authorized"],
                },
            },
            {
                "candidate_key": "preconfirm_watchlist",
                "candidate_family": "preconfirm_watchlist",
                "status": "blocked",
                "walk_forward_progress": {"status": "complete", "required_days": 20, "days": 21},
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
                    "blockers": ["strategy_version_proposal_not_authorized"],
                },
            },
        ]
        monitor = {
            "generated_at": "2026-05-12T00:00:00+00:00",
            "review_date": AS_OF_DATE,
            "next_trade_date": BUY_DATE,
            "today_candidate_count": 11,
            "walk_forward_progress": {"status": "partial", "required_days": 20, "evaluable_signal_days": 12},
            "candidate_monitors": [
                {
                    "candidate_key": "trend_extension_shadow",
                    "candidate_family": "shadow_bucket",
                    "today_candidate_count": 6,
                    "today_top": {"ts_code": "300001.SZ", "name": "Shadow Top"},
                    "walk_forward_progress": gates[0]["walk_forward_progress"],
                    "promotion_gates": {
                        "paper_observation_gate": gates[0]["paper_observation_gate"],
                        "strategy_version_gate": gates[0]["strategy_version_gate"],
                    },
                },
                {
                    "candidate_key": "preconfirm_watchlist",
                    "candidate_family": "preconfirm_watchlist",
                    "today_candidate_count": 5,
                    "today_top": {"ts_code": "300002.SZ", "name": "Shadow Second"},
                    "walk_forward_progress": gates[1]["walk_forward_progress"],
                    "promotion_gates": {
                        "paper_observation_gate": gates[1]["paper_observation_gate"],
                        "strategy_version_gate": gates[1]["strategy_version_gate"],
                    },
                },
            ],
        }
        preflight = {
            "generated_at": "2026-05-12T00:00:01+00:00",
            "review_date": AS_OF_DATE,
            "next_trade_date": BUY_DATE,
            "status": "blocked",
            "candidate_count": 2,
            "candidate_gates": gates,
            "blocker_counts": {
                "operator_review_required": 2,
                "paper_observation_not_authorized": 1,
                "strategy_version_proposal_not_authorized": 2,
            },
            "safety": {
                "artifact_only": True,
                "promotion_allowed": False,
                "paper_observation_allowed": False,
                "writes_trade_state": False,
                "timer_mutated": False,
            },
        }
        (reports_dir / f"strategy_shadow_monitor_{AS_OF_DATE}.json").write_text(
            json.dumps(monitor, ensure_ascii=False),
            encoding="utf-8",
        )
        (reports_dir / f"strategy_shadow_promotion_preflight_{AS_OF_DATE}.json").write_text(
            json.dumps(preflight, ensure_ascii=False),
            encoding="utf-8",
        )

    def _write_shadow_evidence_closure_artifacts(self, reports_dir: Path) -> None:
        scorecard = {
            "artifact_type": "shadow_observation_scorecard",
            "generated_at": "2026-05-12T00:00:02+00:00",
            "review_date": AS_OF_DATE,
            "status": "blocked",
            "read_only": True,
            "artifact_only": True,
            "candidate_count": 2,
            "safety": {
                "writes_trade_state": False,
                "writes_paper_live_behavior": False,
                "timer_mutated": False,
                "promotion_allowed": False,
                "paper_observation_allowed": False,
            },
        }
        dossier = {
            "artifact_type": "shadow_promotion_dossier",
            "dossier_contract": "shadow_promotion_dossier_v1",
            "generated_at": "2026-05-12T00:00:03+00:00",
            "as_of_date": AS_OF_DATE,
            "summary": {
                "status": "blocked",
                "candidate_count": 2,
                "review_ready_is_not_approval": True,
                "promotion_allowed": False,
                "read_only": True,
                "artifact_only": True,
            },
            "safety": {
                "writes_trade_state": False,
                "writes_paper_live_behavior": False,
                "timer_mutated": False,
                "promotion_allowed": False,
                "paper_observation_allowed": False,
            },
        }
        review_request = {
            "artifact_type": "shadow_promotion_review_request",
            "review_request_contract": "shadow_promotion_review_request_v1",
            "generated_at": "2026-05-12T00:00:04+00:00",
            "as_of_date": AS_OF_DATE,
            "summary": {
                "status": "blocked",
                "candidate_count": 2,
                "review_ready_is_not_approval": True,
                "manual_review_required": True,
                "promotion_allowed": False,
            },
            "safety": {
                "writes_trade_state": False,
                "writes_paper_live_behavior": False,
                "timer_mutated": False,
                "promotion_allowed": False,
                "paper_observation_allowed": False,
            },
        }
        walk_forward_outcomes = {
            "artifact_type": "shadow_walk_forward_outcomes",
            "outcomes_contract": "shadow_walk_forward_outcomes_v1",
            "generated_at": "2026-05-12T00:00:05+00:00",
            "as_of_date": AS_OF_DATE,
            "summary": {
                "status": "complete",
                "candidate_count": 2,
                "signal_count": 3,
                "complete_count": 3,
                "partial_horizon_count": 0,
                "missing_market_bar_count": 0,
                "promotion_allowed": False,
            },
            "no_future_boundary": {
                "passed": True,
                "as_of_date": AS_OF_DATE,
                "max_input_date": AS_OF_DATE,
                "query_cutoff_enforced": True,
            },
            "candidates": [
                {
                    "candidate_key": "trend_extension_shadow",
                    "status": "complete",
                    "source_signal_count": 2,
                    "complete_count": 2,
                    "partial_horizon_count": 0,
                    "missing_market_bar_count": 0,
                    "metrics": {"t1_close_mean_pct": 2.0, "t5_close_mean_pct": 4.0},
                    "blockers": [],
                    "promotion_allowed": False,
                },
                {
                    "candidate_key": "preconfirm_watchlist",
                    "status": "complete",
                    "source_signal_count": 1,
                    "complete_count": 1,
                    "partial_horizon_count": 0,
                    "missing_market_bar_count": 0,
                    "metrics": {"t1_close_mean_pct": 1.0, "t5_close_mean_pct": 2.0},
                    "blockers": [],
                    "promotion_allowed": False,
                },
            ],
            "safety": {
                "read_only": True,
                "artifact_only": True,
                "writes_trade_state": False,
                "writes_paper_live_behavior": False,
                "timer_mutated": False,
                "promotion_allowed": False,
                "paper_observation_allowed": False,
            },
        }
        artifacts = {
            f"shadow_observation_scorecard_{AS_OF_DATE}": scorecard,
            f"shadow_promotion_dossier_{AS_OF_DATE}": dossier,
            f"shadow_promotion_review_request_{AS_OF_DATE}": review_request,
            f"shadow_walk_forward_outcomes_{AS_OF_DATE}": walk_forward_outcomes,
        }
        for stem, payload in artifacts.items():
            (reports_dir / f"{stem}.json").write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            (reports_dir / f"{stem}.md").write_text(f"# {stem}\n", encoding="utf-8")

    def _write_shadow_replay_backtest_evidence(self, reports_dir: Path, candidate_key: str) -> None:
        metrics = {
            "t1_close_mean_pct": 2.4,
            "t1_close_win_rate_pct": 65.0,
            "t5_close_mean_pct": 4.0,
            "max_drawdown_pct": -5.0,
        }
        provider = "daily_report_test"
        start_date = "20260409"
        source_hash = build_shadow_replay_backtest_source_hash(
            provider=provider,
            candidate_key=candidate_key,
            start_date=start_date,
            end_date=AS_OF_DATE,
            sample_size=20,
            metrics=metrics,
        )
        payload = {
            "artifact_type": "shadow_replay_backtest_evidence",
            "evidence_contract": "shadow_replay_backtest_evidence_v1",
            "provider": provider,
            "as_of_date": AS_OF_DATE,
            "results": [
                {
                    "candidate_key": candidate_key,
                    "date_range": {"start_date": start_date, "end_date": AS_OF_DATE},
                    "sample_size": 20,
                    "metrics": metrics,
                    "source_hash": source_hash,
                    "no_future_boundary": {
                        "passed": True,
                        "max_input_date": AS_OF_DATE,
                        "data_cutoff_date": AS_OF_DATE,
                    },
                }
            ],
            "safety": {
                "active_params_mutated": False,
                "wrote_strategy_versions": False,
                "writes_trade_state": False,
                "writes_paper_live_behavior": False,
                "timer_mutated": False,
                "promotion_allowed": False,
                "paper_observation_allowed": False,
            },
        }
        (reports_dir / f"shadow_replay_backtest_evidence_{AS_OF_DATE}_{candidate_key}.json").write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def _insert_no_candidate_review_run(self, conn: sqlite3.Connection, review_date: str) -> None:
        strategy = conn.execute(
            """
            SELECT id, strategy_key, strategy_version, params_hash
            FROM strategy_versions
            WHERE strategy_version = ?
            """,
            ("cpb_6157@2026-05-03",),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO strategy_runs
              (strategy_version_id, strategy_key, strategy_version, as_of_date, params_json, params_hash, status)
            VALUES
              (?, ?, ?, ?, '{}', ?, 'completed')
            """,
            (
                strategy[0],
                strategy[1],
                strategy[2],
                review_date,
                strategy[3],
            ),
        )
        conn.execute(
            """
            INSERT INTO data_quality_events
              (layer, severity, event_code, trade_date, message)
            VALUES
              ('market', 'warning', 'HISTORY_TEST_WARNING', ?, 'history warning')
            """,
            (review_date,),
        )

    def _insert_market_bar(
        self,
        conn: sqlite3.Connection,
        ts_code: str,
        trade_date: str,
        close: float,
        open_price: float | None = None,
        high: float | None = None,
        low: float | None = None,
        amount: float = 1000000,
    ) -> None:
        open_value = close if open_price is None else open_price
        high_value = close if high is None else high
        low_value = close if low is None else low
        conn.execute(
            """
            INSERT OR REPLACE INTO market_bars
              (
                ts_code,
                trade_date,
                open,
                high,
                low,
                close,
                vol,
                amount,
                adj_open,
                adj_high,
                adj_low,
                adj_close
              )
            VALUES
              (?, ?, ?, ?, ?, ?, 100000, ?, ?, ?, ?, ?)
            """,
            (
                ts_code,
                trade_date,
                open_value,
                high_value,
                low_value,
                close,
                amount,
                open_value,
                high_value,
                low_value,
                close,
            ),
        )


if __name__ == "__main__":
    unittest.main()
