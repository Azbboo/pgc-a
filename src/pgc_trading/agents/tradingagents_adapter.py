"""Boundary adapter for TradingAgents.

TradingAgents is intentionally kept outside the core signal and portfolio
engines. This module owns paths, configuration hashes, and future subprocess
invocation so agent output can be stored without contaminating deterministic
strategy data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path

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
    online_tools: bool = True
    deep_think_llm: str = "o4-mini"
    quick_think_llm: str = "gpt-4o-mini"
    max_debate_rounds: int = 1
    max_risk_discuss_rounds: int = 1

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    def hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


def build_input_snapshot(candidate: dict, as_of_date: str, source_refs: list[str]) -> dict:
    payload = {
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
