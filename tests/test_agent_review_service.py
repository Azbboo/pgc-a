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
    TradingAgentsUnavailable,
)
from pgc_trading.services.agent_review_service import AgentReviewService, ReviewDailyPickRequest
from pgc_trading.services.common import RequestContext
from pgc_trading.storage.migrate import run_migrations


class _FakeTradingAgentsRunner:
    calls: list[tuple[dict[str, Any], TradingAgentsRunConfig, TradingAgentsPaths]]

    def __init__(self) -> None:
        self.calls = []

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
            raw_decision={"decision": "HOLD", "summary": "形态可复核"},
            raw_state={"ticker": snapshot["candidate"]["ts_code"]},
            final_report="# TradingAgents Advisory\n\nHOLD until pre-open checks pass.\n",
        )


class _UnavailableRunner:
    def run(
        self,
        snapshot: dict[str, Any],
        config: TradingAgentsRunConfig,
        paths: TradingAgentsPaths,
    ) -> TradingAgentsExecutionResult:
        raise TradingAgentsUnavailable("optional package 'tradingagents' is not installed")


class AgentReviewServiceTest(unittest.TestCase):
    def test_dry_run_builds_snapshot_without_writes_or_runner_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._build_db(Path(tmp))
            runner = _FakeTradingAgentsRunner()
            service = AgentReviewService(db_path, runner=runner, paths=self._paths(Path(tmp)))

            result = service.review_daily_pick(
                ReviewDailyPickRequest(daily_pick_id=1, account_key="paper-main"),
                RequestContext(request_id="test-agent", dry_run=True, operator="tester", source="test"),
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.action, "no_opinion")
            self.assertEqual(len(runner.calls), 0)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM input_snapshots").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM agent_decisions").fetchone()[0], 0)

    def test_apply_writes_agent_run_decision_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = self._build_db(root)
            runner = _FakeTradingAgentsRunner()
            service = AgentReviewService(db_path, runner=runner, paths=self._paths(root))

            result = service.review_daily_pick(
                ReviewDailyPickRequest(daily_pick_id=1, account_key="paper-main"),
                RequestContext(
                    request_id="test-agent",
                    idempotency_key="agent-review:test:1",
                    dry_run=False,
                    operator="tester",
                    source="test",
                ),
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.action, "caution")
            self.assertEqual(result.data.risk_level, "medium")
            self.assertEqual(len(runner.calls), 1)
            snapshot, config, paths = runner.calls[0]
            self.assertEqual(snapshot["snapshot_type"], "tradingagents_candidate_review")
            self.assertEqual(snapshot["candidate"]["ts_code"], "000001.SZ")
            self.assertEqual(snapshot["candidate"]["portfolio_context"]["account_key"], "paper-main")
            self.assertIn("analysis_contexts", snapshot["candidate"])
            self.assertEqual(snapshot["candidate"]["analysis_contexts"]["technical"]["status"], "available")
            self.assertEqual(snapshot["candidate"]["analysis_contexts"]["fundamental"]["status"], "unavailable")
            self.assertEqual(snapshot["candidate"]["analysis_contexts"]["news"]["status"], "unavailable")
            self.assertEqual(snapshot["candidate"]["analysis_contexts"]["sentiment"]["status"], "partial")
            self.assertEqual(snapshot["candidate"]["analysis_contexts"]["sector"]["status"], "unavailable")
            evidence_context = snapshot["candidate"]["evidence_context"]
            self.assertEqual(evidence_context["system_review_facts"]["label"], "系统确定性复盘事实")
            self.assertEqual(evidence_context["cached_technical_data"]["label"], "缓存技术数据")
            self.assertEqual(evidence_context["cached_fundamental_data"]["status"], "unavailable")
            self.assertEqual(evidence_context["cached_sector_context"]["label"], "缓存板块位置")
            self.assertTrue(any("新闻/公告未接入/数据不足" in item for item in evidence_context["missing_data_warnings"]))
            self.assertIn("外部证据不直接改变交易计划。", evidence_context["source_boundary"])
            self.assertEqual(
                snapshot["external_data_coverage"],
                {
                    "fundamental": "unavailable",
                    "news": "unavailable",
                    "sector": "unavailable",
                    "sentiment": "partial",
                    "technical": "available",
                },
            )
            self.assertEqual(snapshot["candidate"]["external_data_coverage"], snapshot["external_data_coverage"])
            self.assertFalse(config.online_tools)
            self.assertEqual(config.llm_provider, "deepseek")
            self.assertEqual(config.deep_think_llm, "deepseek-v4-pro")
            self.assertEqual(config.quick_think_llm, "deepseek-v4-pro")
            self.assertEqual(config.max_debate_rounds, 3)
            self.assertIsNone(result.data.execution_mode)
            self.assertIsNone(result.data.source_label)
            self.assertTrue(str(paths.results_dir).startswith(str(root)))
            self.assertTrue(result.data.artifact_paths)
            for artifact_path in result.data.artifact_paths:
                self.assertTrue(Path(artifact_path).exists())

            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                run = conn.execute("SELECT * FROM agent_runs").fetchone()
                decision = conn.execute("SELECT * FROM agent_decisions").fetchone()
                operation = conn.execute("SELECT * FROM operation_requests").fetchone()
                self.assertEqual(run["status"], "completed")
                self.assertEqual(run["agent_system"], "TradingAgents")
                self.assertEqual(decision["action"], "caution")
                self.assertEqual(decision["risk_level"], "medium")
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM agent_artifacts").fetchone()[0], 3)
                self.assertEqual(operation["status"], "success")

    def test_apply_enriches_snapshot_with_cached_external_agent_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = self._build_db(root)
            with sqlite3.connect(db_path) as conn:
                self._insert_cached_external_agent_data(conn)
            runner = _FakeTradingAgentsRunner()
            service = AgentReviewService(db_path, runner=runner, paths=self._paths(root))

            result = service.review_daily_pick(
                ReviewDailyPickRequest(daily_pick_id=1, account_key="paper-main"),
                RequestContext(
                    request_id="test-agent-external",
                    idempotency_key="agent-review:test:external",
                    dry_run=False,
                    operator="tester",
                    source="test",
                ),
            )

            self.assertTrue(result.ok)
            snapshot = runner.calls[0][0]
            source_refs = snapshot["source_refs"]
            self.assertIn("agent_external_items:1", source_refs)
            self.assertIn("agent_external_items:2", source_refs)
            self.assertNotIn("agent_external_items:3", source_refs)
            self.assertIn("market_diagnostic_bars:yfinance:000001.SZ:20260504", source_refs)

            contexts = snapshot["candidate"]["analysis_contexts"]
            self.assertEqual(contexts["news"]["status"], "available")
            self.assertEqual(contexts["news"]["items"][0]["title"], "盘后公告摘要")
            self.assertEqual(contexts["fundamental"]["status"], "partial")
            self.assertEqual(contexts["fundamental"]["external_items"][0]["title"], "财务摘要")
            self.assertEqual(contexts["sentiment"]["external_items"][0]["sentiment"], "neutral")
            self.assertEqual(
                snapshot["external_data_coverage"],
                {
                    "fundamental": "partial",
                    "news": "available",
                    "sector": "unavailable",
                    "sentiment": "partial",
                    "technical": "available",
                },
            )
            diagnostics = contexts["technical"]["external_market_diagnostics"]
            self.assertEqual(diagnostics["status"], "partial")
            self.assertEqual(diagnostics["providers"][0]["provider"], "yfinance")
            self.assertNotIn("badprovider", {item["provider"] for item in diagnostics["providers"]})
            self.assertEqual(diagnostics["providers"][0]["last_trade_date"], "20260504")
            self.assertEqual(snapshot["candidate"]["external_data"]["items"]["status"], "available")

    def test_unavailable_tradingagents_records_skipped_no_opinion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = self._build_db(root)
            service = AgentReviewService(db_path, runner=_UnavailableRunner(), paths=self._paths(root))

            result = service.review_daily_pick(
                ReviewDailyPickRequest(daily_pick_id=1, account_key="paper-main"),
                RequestContext(
                    request_id="test-agent",
                    idempotency_key="agent-review:test:missing-package",
                    dry_run=False,
                    operator="tester",
                    source="test",
                ),
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "skipped")
            self.assertEqual(result.data.action, "no_opinion")
            self.assertEqual(result.data.risk_level, "unknown")
            self.assertEqual(result.warnings[0].code, "TRADINGAGENTS_UNAVAILABLE")
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                run = conn.execute("SELECT * FROM agent_runs").fetchone()
                decision = conn.execute("SELECT * FROM agent_decisions").fetchone()
                self.assertEqual(run["status"], "skipped")
                self.assertIn("not installed", run["error_message"])
                self.assertEqual(decision["action"], "no_opinion")

    def test_missing_daily_pick_is_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._build_db(Path(tmp))
            service = AgentReviewService(db_path, runner=_FakeTradingAgentsRunner(), paths=self._paths(Path(tmp)))

            result = service.review_daily_pick(
                ReviewDailyPickRequest(daily_pick_id=99, account_key="paper-main"),
                RequestContext(request_id="test-agent", dry_run=True, operator="tester", source="test"),
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "validation_failed")
            self.assertEqual(result.errors[0].code, "DAILY_PICK_NOT_FOUND")

    def _paths(self, root: Path) -> TradingAgentsPaths:
        return TradingAgentsPaths(
            results_dir=root / "agents" / "results",
            cache_dir=root / "agents" / "cache",
            memory_log_path=root / "agents" / "memory" / "trading_memory.md",
        )

    def _build_db(self, root: Path) -> Path:
        db_path = root / "pgc_agent_review.db"
        run_migrations(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            account_id = self._insert_account(conn)
            self._insert_signal_chain(conn)
            self._insert_market_bar(conn)
            self.assertEqual(account_id, 1)
        return db_path

    def _insert_account(self, conn: sqlite3.Connection) -> int:
        cursor = conn.execute(
            """
            INSERT INTO portfolio_accounts
              (account_key, name, account_type, initial_cash, max_positions, position_sizing)
            VALUES
              ('paper-main', 'Paper Main', 'paper', 200000, 3, 'equal_slots')
            """
        )
        return int(cursor.lastrowid)

    def _insert_signal_chain(self, conn: sqlite3.Connection) -> None:
        family_id = conn.execute(
            """
            INSERT INTO strategy_families (family_key, name, description, owner)
            VALUES ('contracting_pullback', 'Contracting Pullback', 'PGC strategy', 'research')
            """
        ).lastrowid
        strategy_version_id = conn.execute(
            """
            INSERT INTO strategy_versions
              (strategy_family_id, strategy_key, strategy_version, params_hash, status)
            VALUES
              (?, 'cpb_6157', 'cpb_6157@2026-05-03', 'params-hash', 'paper')
            """,
            (family_id,),
        ).lastrowid
        raw_event_id = conn.execute(
            """
            INSERT INTO raw_events
              (ts_code, code, name, entry_date, entry_time, entry_price)
            VALUES
              ('000001.SZ', '000001', 'PGC Candidate', '20260504', '09:45:00', 10.25)
            """
        ).lastrowid
        feature_run_id = conn.execute(
            """
            INSERT INTO feature_runs (feature_version, as_of_date)
            VALUES ('contracting_pullback.v1', '20260504')
            """
        ).lastrowid
        feature_snapshot_id = conn.execute(
            """
            INSERT INTO feature_snapshots
              (feature_run_id, raw_event_id, ts_code, review_date, feature_version, features_json, input_hash)
            VALUES
              (?, ?, '000001.SZ', '20260504', 'contracting_pullback.v1', ?, 'feature-input')
            """,
            (feature_run_id, raw_event_id, '{"pullback_days": 3, "trigger_pct_chg": 0.04}'),
        ).lastrowid
        strategy_run_id = conn.execute(
            """
            INSERT INTO strategy_runs
              (strategy_version_id, strategy_key, strategy_version, as_of_date, params_json, params_hash, feature_run_id)
            VALUES
              (?, 'cpb_6157', 'cpb_6157@2026-05-03', '20260504', '{}', 'params-hash', ?)
            """,
            (strategy_version_id, feature_run_id),
        ).lastrowid
        signal_id = conn.execute(
            """
            INSERT INTO strategy_signals
              (strategy_run_id, feature_snapshot_id, raw_event_id, ts_code, name, review_date, planned_buy_date, score, signal_rank, features_json)
            VALUES
              (?, ?, ?, '000001.SZ', 'PGC Candidate', '20260504', '20260505', 91.0, 1, ?)
            """,
            (strategy_run_id, feature_snapshot_id, raw_event_id, '{"pullback_days": 3}'),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO daily_picks
              (strategy_run_id, signal_id, review_date, planned_buy_date, score, selection_reason)
            VALUES
              (?, ?, '20260504', '20260505', 91.0, 'highest_score_rank_1')
            """,
            (strategy_run_id, signal_id),
        )

    def _insert_market_bar(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO market_bars
              (ts_code, trade_date, open, high, low, close, vol, amount, provider)
            VALUES
              ('000001.SZ', '20260504', 10.0, 10.8, 9.9, 10.5, 100000, 1050000, 'test')
            """
        )

    def _insert_cached_external_agent_data(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO market_diagnostic_bars
              (ts_code, trade_date, provider, open, high, low, close, vol, amount)
            VALUES
              ('000001.SZ', '20260503', 'yfinance', 9.8, 10.4, 9.7, 10.1, 120000, NULL),
              ('000001.SZ', '20260504', 'yfinance', 10.0, 10.7, 9.9, 10.4, 130000, NULL),
              ('000001.SZ', '20260505', 'yfinance', 10.5, 10.9, 10.2, 10.8, 140000, NULL),
              ('000001.SZ', '2026-12-31', 'badprovider', 11.0, 11.5, 10.8, 11.2, 150000, NULL)
            """
        )
        conn.execute(
            """
            INSERT INTO agent_external_items
              (
                ts_code,
                published_date,
                item_type,
                provider,
                title,
                summary,
                sentiment,
                importance,
                metadata_json,
                source_hash
              )
            VALUES
              ('000001.SZ', '20260504', 'announcement', 'manual', '盘后公告摘要', '公告摘要未发现重大利空。', 'neutral', 'medium', '{"source":"fixture"}', 'manual:announcement:000001:20260504'),
              ('000001.SZ', '20260503', 'fundamental', 'manual', '财务摘要', '估值和市值处于可观察区间。', 'neutral', 'low', '{"source":"fixture"}', 'manual:fundamental:000001:20260503'),
              ('000001.SZ', '20260505', 'news', 'manual', '未来新闻摘要', '这条新闻晚于复核日，不能进入快照。', 'negative', 'high', '{"source":"fixture"}', 'manual:news:000001:20260505')
            """
        )


if __name__ == "__main__":
    unittest.main()
