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
                        '"summary":"本地快照支持当前计划。",'
                        '"analyst_reports":{'
                        '"technical":{"status":"available","summary":"技术面转强",'
                        '"supporting_points":["评分较强"],"risk_points":["高开波动"]},'
                        '"fundamental":{"status":"partial","summary":"估值数据有限",'
                        '"supporting_points":["市值适中"],"risk_points":["缺少财报快照"]},'
                        '"news":{"status":"unavailable","summary":"新闻源未接入",'
                        '"supporting_points":[],"risk_points":["不得编造新闻"]},'
                        '"sentiment":{"status":"partial","summary":"市场情绪偏热",'
                        '"supporting_points":["放量上涨"],"risk_points":["短线拥挤"]},'
                        '"sector":{"status":"unavailable","summary":"板块位置未接入",'
                        '"supporting_points":[],"risk_points":["不能编造板块强弱"]}},'
                        '"supporting_points":["评分较强"],'
                        '"risk_points":["注意开盘波动"]}'
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
        self.assertEqual(result.supporting_points, ["评分较强"])
        self.assertEqual(result.risk_points, ["注意开盘波动"])
        self.assertEqual(result.analyst_reports["technical"]["summary"], "技术面转强")
        self.assertEqual(result.analyst_reports["news"]["status"], "unavailable")
        self.assertEqual(result.raw_decision["execution_source"]["mode"], "local_snapshot_mode")
        self.assertIn("report_sections", result.raw_decision)
        self.assertEqual(result.raw_decision["report_sections"]["sector"]["status"], "unavailable")
        self.assertEqual(result.raw_decision["external_data_coverage"]["news"], "unavailable")
        self.assertIn("# TradingAgents 中文结构化复核", result.final_report)
        self.assertIn("来源：TradingAgents 本地快照模式", result.final_report)
        self.assertIn("## 技术/量价", result.final_report)
        self.assertIn("## 基本面", result.final_report)
        self.assertIn("## 板块位置", result.final_report)
        self.assertEqual(client_calls[0]["provider"], "deepseek")
        self.assertEqual(client_calls[0]["model"], "deepseek-v4-pro")
        self.assertIn("只允许使用下方本地数据库快照", prompt_calls[0])
        self.assertIn("external_data_coverage", prompt_calls[0])
        self.assertIn("candidate.evidence_context", prompt_calls[0])
        self.assertIn("系统确定性复盘事实", prompt_calls[0])
        self.assertIn("未接入/缺失警告", prompt_calls[0])
        self.assertIn("所有自然语言必须使用简体中文", prompt_calls[0])
        self.assertIn("板块位置", prompt_calls[0])
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
        self.assertIn("没有返回 JSON", result.risk_points[0])
        self.assertIn("parse_error", result.raw_decision)


def _snapshot() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "as_of_date": "20260507",
        "snapshot_type": "tradingagents_candidate_review",
        "external_data_coverage": {
            "fundamental": "partial",
            "news": "unavailable",
            "sentiment": "partial",
            "technical": "available",
            "sector": "unavailable",
        },
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
            "external_data_coverage": {
                "fundamental": "partial",
                "news": "unavailable",
                "sentiment": "partial",
                "technical": "available",
                "sector": "unavailable",
            },
            "evidence_context": {
                "system_review_facts": {
                    "label": "系统确定性复盘事实",
                    "status": "available",
                },
                "cached_technical_data": {
                    "label": "缓存技术数据",
                    "status": "available",
                },
                "cached_fundamental_data": {
                    "label": "缓存基本面数据",
                    "status": "partial",
                },
                "cached_news_announcement_data": {
                    "label": "缓存新闻/公告数据",
                    "status": "unavailable",
                },
                "cached_sentiment_data": {
                    "label": "缓存情绪数据",
                    "status": "partial",
                },
                "cached_sector_context": {
                    "label": "缓存板块位置",
                    "status": "unavailable",
                },
                "missing_data_warnings": ["新闻/公告未接入/数据不足。"],
                "source_boundary": ["外部证据不直接改变交易计划。"],
            },
        },
        "source_refs": ["daily_picks:1"],
    }
