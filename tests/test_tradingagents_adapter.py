from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pgc_trading.agents.tradingagents_adapter import (
    TradingAgentsPaths,
    TradingAgentsRunConfig,
    TradingAgentsRunner,
    parse_local_snapshot_output,
)


class TradingAgentsAdapterTest(unittest.TestCase):
    def test_local_snapshot_mode_uses_tradingagents_llm_client_without_graph_tools(self) -> None:
        prompt_calls: list[str] = []
        client_calls: list[dict[str, object]] = []
        imported_modules: list[str] = []

        class FakeLLM:
            def invoke(self, prompt: str) -> SimpleNamespace:
                prompt_calls.append(prompt)
                return SimpleNamespace(
                    content=(
                        "```json\n"
                        '{"action":"support","confidence":0.71,"risk_level":"low",'
                        '"summary":"Local snapshot supports the plan.",'
                        '"supporting_points":["score is strong"],'
                        '"risk_points":["watch the open"]}'
                        "\n```"
                    )
                )

        class FakeClient:
            def get_llm(self) -> FakeLLM:
                return FakeLLM()

        def create_llm_client(**kwargs: object) -> FakeClient:
            client_calls.append(kwargs)
            return FakeClient()

        def fake_import_module(name: str) -> SimpleNamespace:
            imported_modules.append(name)
            if name == "tradingagents.llm_clients":
                return SimpleNamespace(create_llm_client=create_llm_client)
            raise ModuleNotFoundError(name)

        with tempfile.TemporaryDirectory() as tmp, patch(
            "pgc_trading.agents.tradingagents_adapter.importlib.import_module",
            side_effect=fake_import_module,
        ):
            result = TradingAgentsRunner().run(
                _snapshot(),
                TradingAgentsRunConfig(),
                TradingAgentsPaths(
                    results_dir=Path(tmp) / "results",
                    cache_dir=Path(tmp) / "cache",
                    memory_log_path=Path(tmp) / "memory" / "trading_memory.md",
                ),
            )

        self.assertEqual(result.action, "support")
        self.assertEqual(result.confidence, 0.71)
        self.assertEqual(result.risk_level, "low")
        self.assertEqual(result.supporting_points, ["score is strong"])
        self.assertEqual(result.risk_points, ["watch the open"])
        self.assertEqual(client_calls[0]["provider"], "deepseek")
        self.assertEqual(client_calls[0]["model"], "deepseek-v4-pro")
        self.assertIn("Use only the supplied local database snapshot", prompt_calls[0])
        self.assertIn('"ts_code": "000001.SZ"', prompt_calls[0])
        self.assertNotIn("tradingagents.graph.trading_graph", imported_modules)

    def test_local_snapshot_parser_falls_back_when_response_is_not_json(self) -> None:
        result = parse_local_snapshot_output(
            "This is a neutral HOLD because the setup needs pre-open confirmation.",
            _snapshot(),
            TradingAgentsRunConfig(),
        )

        self.assertEqual(result.action, "caution")
        self.assertEqual(result.risk_level, "medium")
        self.assertEqual(result.confidence, None)
        self.assertIn("not JSON", result.risk_points[0])
        self.assertIn("parse_error", result.raw_decision)


def _snapshot() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "as_of_date": "20260507",
        "snapshot_type": "tradingagents_candidate_review",
        "candidate": {
            "daily_pick_id": 1,
            "signal_id": 1,
            "ts_code": "000001.SZ",
            "name": "PGC Candidate",
            "score": 91.0,
            "selection_reason": "contracting pullback",
            "market_summary": {
                "last_trade_date": "20260507",
                "last_close": 10.25,
                "recent_5d_ret": 0.05,
                "recent_bars": [],
            },
            "portfolio_context": {
                "account_key": "paper-main",
                "open_positions": 0,
                "free_slots": 3,
            },
        },
        "source_refs": ["daily_picks:1"],
    }
