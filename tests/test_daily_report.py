from __future__ import annotations

import json
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.cli.main import main
from pgc_trading.reporting.daily_report import (
    DailyReportRequest,
    DailyReviewHistoryRequest,
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
            self.assertEqual(result.data.candidate.ts_code, "000001.SZ")
            self.assertEqual(result.data.buy_plan.status, "active")

            markdown = render_daily_report_markdown(result.data)
            self.assertIn("## Paper 晋级分数卡", markdown)
            self.assertIn("样本交易", markdown)
            self.assertIn("晋级 live 前还差什么", markdown)
            self.assertIn("## 今日候选", markdown)
            self.assertIn("000001.SZ Report Pick", markdown)
            self.assertIn("下一交易日开盘买入", markdown)
            self.assertNotIn("daily_pick_id", markdown)
            self.assertNotIn("trade_plan_id", markdown)

            payload = json.loads(render_daily_report_json(result.data))
            self.assertEqual(payload["as_of_date"], AS_OF_DATE)
            self.assertIn("paper_promotion", payload)
            self.assertIn("MIN_PAPER_TRADES_NOT_MET", payload["paper_promotion"]["promotion_blockers"])
            self.assertEqual(payload["candidate"]["daily_pick_id"], result.data.candidate.daily_pick_id)
            self.assertIn("data_quality", payload)
            self.assertIn("lineage", payload)

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
            self.assertEqual([report.analyst_key for report in advice.analyst_reports], ["technical", "fundamental"])
            self.assertEqual(advice.analyst_reports[0].summary, "技术面转强。")
            self.assertEqual(advice.report_markdown, "# Agent Report\n\nDetailed advisory.\n")
            self.assertEqual([artifact.artifact_type for artifact in advice.artifacts], ["decision_json", "final_report"])

            markdown = render_daily_report_markdown(result.data)
            self.assertIn("支持依据", markdown)
            self.assertIn("score is strong", markdown)
            self.assertIn("风险提示", markdown)
            self.assertIn("数据覆盖", markdown)
            self.assertIn("外部证据", markdown)
            self.assertIn("未接入/缺失", markdown)
            payload = json.loads(render_daily_report_json(result.data))
            self.assertEqual(payload["agent_advice"]["supporting_points"], ["score is strong", "portfolio has room"])
            self.assertEqual(payload["agent_advice"]["source_refs"][0], "agent_external_items:42")
            self.assertEqual(payload["agent_advice"]["external_data_coverage"]["news"], "unavailable")
            self.assertEqual(payload["agent_advice"]["external_evidence"][0]["source"], "tushare")
            self.assertEqual(payload["agent_advice"]["missing_data_warnings"], ["新闻/公告未接入/数据不足。"])
            self.assertEqual(payload["agent_advice"]["analyst_reports"][1]["analyst_name"], "基本面")
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
