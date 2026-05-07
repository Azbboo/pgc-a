"""Boundary adapter for TradingAgents.

TradingAgents is intentionally kept outside the core signal and portfolio
engines. This module owns paths, configuration hashes, and future subprocess
invocation so agent output can be stored without contaminating deterministic
strategy data.
"""

from __future__ import annotations

import hashlib
import json
import importlib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from pgc_trading.config import ROOT


AGENT_ROOT = ROOT / "data" / "agents" / "tradingagents"


@dataclass(frozen=True)
class TradingAgentsPaths:
    results_dir: Path = AGENT_ROOT / "results"
    cache_dir: Path = AGENT_ROOT / "cache"
    memory_log_path: Path = AGENT_ROOT / "memory" / "trading_memory.md"

    def ensure(self) -> None:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.memory_log_path.parent.mkdir(parents=True, exist_ok=True)

    def env(self) -> dict[str, str]:
        return {
            "TRADINGAGENTS_RESULTS_DIR": str(self.results_dir),
            "TRADINGAGENTS_CACHE_DIR": str(self.cache_dir),
            "TRADINGAGENTS_MEMORY_LOG_PATH": str(self.memory_log_path),
        }


@dataclass(frozen=True)
class TradingAgentsRunConfig:
    agent_system: str = "TradingAgents"
    agent_version: str = "external"
    mode: str = "local_snapshot_mode"
    online_tools: bool = False
    deep_think_llm: str = "gpt-5.4"
    quick_think_llm: str = "gpt-5.4-mini"
    max_debate_rounds: int = 1
    max_risk_discuss_rounds: int = 1

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    def hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TradingAgentsExecutionResult:
    """Normalized result returned by the external TradingAgents boundary."""

    action: str
    confidence: float | None
    risk_level: str
    summary: str
    supporting_points: list[str]
    risk_points: list[str]
    raw_decision: dict[str, Any]
    raw_state: dict[str, Any] | None = None
    final_report: str | None = None


class TradingAgentsUnavailable(RuntimeError):
    """Raised when the optional external TradingAgents package is unavailable."""


class TradingAgentsRunner:
    """Thin optional-import runner for TauricResearch/TradingAgents."""

    def run(
        self,
        snapshot: dict[str, Any],
        config: TradingAgentsRunConfig,
        paths: TradingAgentsPaths,
    ) -> TradingAgentsExecutionResult:
        try:
            graph_module = importlib.import_module("tradingagents.graph.trading_graph")
            default_config_module = importlib.import_module("tradingagents.default_config")
        except ModuleNotFoundError as exc:
            raise TradingAgentsUnavailable(
                "optional package 'tradingagents' is not installed; install TauricResearch/TradingAgents to run external advisory"
            ) from exc

        graph_cls = getattr(graph_module, "TradingAgentsGraph")
        default_config = dict(getattr(default_config_module, "DEFAULT_CONFIG", {}))
        default_config.update(
            {
                "project_dir": str(paths.results_dir),
                "results_dir": str(paths.results_dir),
                "data_cache_dir": str(paths.cache_dir),
                "memory_log_path": str(paths.memory_log_path),
                "online_tools": config.online_tools,
                "deep_think_llm": config.deep_think_llm,
                "quick_think_llm": config.quick_think_llm,
                "max_debate_rounds": config.max_debate_rounds,
                "max_risk_discuss_rounds": config.max_risk_discuss_rounds,
            }
        )
        analysts = ["market"]
        candidate = snapshot["candidate"]
        ticker = str(candidate["ts_code"])
        as_of_date = _yyyymmdd_to_iso(str(snapshot["as_of_date"]))
        graph = graph_cls(analysts, config=default_config, debug=False)
        final_state, raw_decision = graph.propagate(ticker, as_of_date)
        return parse_tradingagents_output(raw_decision, final_state)


def build_input_snapshot(candidate: dict, as_of_date: str, source_refs: list[str]) -> dict:
    payload = {
        "schema_version": "1.0",
        "as_of_date": as_of_date,
        "snapshot_type": "tradingagents_candidate_review",
        "candidate": candidate,
        "source_refs": source_refs,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "as_of_date": as_of_date,
        "snapshot_type": payload["snapshot_type"],
        "source_refs_json": json.dumps(source_refs, ensure_ascii=False),
        "content_hash": hashlib.sha256(encoded).hexdigest(),
        "payload": payload,
    }


def parse_tradingagents_output(raw_decision: Any, final_state: Any | None = None) -> TradingAgentsExecutionResult:
    decision_text = _decision_text(raw_decision)
    action = _map_action(decision_text)
    risk_level = _map_risk_level(action, decision_text)
    summary = _summary_from_output(raw_decision, decision_text)
    raw_decision_json = {
        "raw_decision": _json_safe(raw_decision),
        "mapped_action": action,
        "mapped_risk_level": risk_level,
    }
    return TradingAgentsExecutionResult(
        action=action,
        confidence=None,
        risk_level=risk_level,
        summary=summary,
        supporting_points=[],
        risk_points=[],
        raw_decision=raw_decision_json,
        raw_state=_json_safe(final_state) if final_state is not None else None,
        final_report=decision_text,
    )


def unavailable_result(message: str) -> TradingAgentsExecutionResult:
    return TradingAgentsExecutionResult(
        action="no_opinion",
        confidence=None,
        risk_level="unknown",
        summary=message,
        supporting_points=[],
        risk_points=[message],
        raw_decision={
            "schema_version": "1.0",
            "agent_system": "TradingAgents",
            "action": "no_opinion",
            "risk_level": "unknown",
            "summary": message,
        },
    )


def _decision_text(raw_decision: Any) -> str:
    if isinstance(raw_decision, str):
        return raw_decision
    if isinstance(raw_decision, dict):
        for key in ("decision", "final_decision", "recommendation", "action", "summary"):
            value = raw_decision.get(key)
            if value:
                return str(value)
    return str(raw_decision)


def _map_action(decision_text: str) -> str:
    normalized = decision_text.lower()
    if "strong buy" in normalized or "buy" in normalized:
        return "support"
    if "sell" in normalized or "avoid" in normalized:
        return "reject"
    if "hold" in normalized or "neutral" in normalized:
        return "caution"
    return "no_opinion"


def _map_risk_level(action: str, decision_text: str) -> str:
    normalized = decision_text.lower()
    if "high risk" in normalized or action == "reject":
        return "high"
    if "low risk" in normalized or action == "support":
        return "low"
    if action == "caution":
        return "medium"
    return "unknown"


def _summary_from_output(raw_decision: Any, decision_text: str) -> str:
    if isinstance(raw_decision, dict):
        summary = raw_decision.get("summary")
        if summary:
            return str(summary)
    compact = " ".join(decision_text.split())
    return compact[:240] if compact else "TradingAgents returned no readable advisory."


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return repr(value)


def _yyyymmdd_to_iso(value: str) -> str:
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value
