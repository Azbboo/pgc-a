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
            self.assertFalse(config.online_tools)
            self.assertEqual(config.llm_provider, "deepseek")
            self.assertEqual(config.deep_think_llm, "deepseek-v4-pro")
            self.assertEqual(config.quick_think_llm, "deepseek-v4-pro")
            self.assertEqual(config.max_debate_rounds, 3)
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


if __name__ == "__main__":
    unittest.main()
