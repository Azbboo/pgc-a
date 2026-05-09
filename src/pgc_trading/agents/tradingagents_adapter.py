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


REPORT_SECTION_ORDER = ("fundamental", "news", "sentiment", "technical", "sector", "risk", "conclusion")
ANALYST_SECTION_ORDER = ("technical", "fundamental", "news", "sentiment", "sector")
EVIDENCE_COVERAGE_KEYS = ("fundamental", "news", "sentiment", "technical", "sector")
REPORT_SECTION_NAMES = {
    "fundamental": "基本面",
    "news": "新闻",
    "sentiment": "情绪",
    "technical": "技术/量价",
    "sector": "板块位置",
    "risk": "风险",
    "conclusion": "结论",
}


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
    llm_provider: str = "deepseek"
    online_tools: bool = False
    deep_think_llm: str = "deepseek-v4-pro"
    quick_think_llm: str = "deepseek-v4-pro"
    max_debate_rounds: int = 3
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
    analyst_reports: dict[str, dict[str, Any]]
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
        if config.mode == "local_snapshot_mode":
            return self._run_local_snapshot_review(snapshot, config)
        return self._run_external_graph(snapshot, config, paths)

    def _run_external_graph(
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
                "llm_provider": config.llm_provider,
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
        return parse_tradingagents_output(raw_decision, final_state, config)

    def _run_local_snapshot_review(
        self,
        snapshot: dict[str, Any],
        config: TradingAgentsRunConfig,
    ) -> TradingAgentsExecutionResult:
        try:
            llm_clients_module = importlib.import_module("tradingagents.llm_clients")
        except ModuleNotFoundError as exc:
            raise TradingAgentsUnavailable(
                "optional package 'tradingagents' is not installed; install TauricResearch/TradingAgents to run external advisory"
            ) from exc

        create_llm_client = getattr(llm_clients_module, "create_llm_client")
        client = create_llm_client(
            provider=config.llm_provider,
            model=config.deep_think_llm,
            base_url=None,
        )
        response = client.get_llm().invoke(_build_local_snapshot_prompt(snapshot, config))
        return parse_local_snapshot_output(_response_text(response), snapshot, config)


def build_input_snapshot(candidate: dict, as_of_date: str, source_refs: list[str]) -> dict:
    payload = {
        "schema_version": "1.0",
        "as_of_date": as_of_date,
        "snapshot_type": "tradingagents_candidate_review",
        "candidate": candidate,
        "source_refs": source_refs,
    }
    coverage = _coverage_from_snapshot({"candidate": candidate})
    if coverage:
        payload["external_data_coverage"] = coverage
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "as_of_date": as_of_date,
        "snapshot_type": payload["snapshot_type"],
        "source_refs_json": json.dumps(source_refs, ensure_ascii=False),
        "content_hash": hashlib.sha256(encoded).hexdigest(),
        "payload": payload,
    }


def parse_tradingagents_output(
    raw_decision: Any,
    final_state: Any | None = None,
    config: TradingAgentsRunConfig | None = None,
) -> TradingAgentsExecutionResult:
    decision_text = _decision_text(raw_decision)
    action = _map_action(decision_text)
    risk_level = _map_risk_level(action, decision_text)
    summary = _summary_from_output(raw_decision, decision_text)
    execution_source = _execution_source(config, "TradingAgents 外部图模式" if config else "TradingAgents 原始输出")
    report_sections = _build_structured_report_sections(
        parsed=raw_decision if isinstance(raw_decision, dict) else {},
        analyst_reports={},
        summary=summary,
        supporting_points=[],
        risk_points=[],
        snapshot=None,
        config=config,
    )
    raw_decision_json = {
        "raw_decision": _json_safe(raw_decision),
        "mapped_action": action,
        "mapped_risk_level": risk_level,
        "execution_source": execution_source,
        "report_sections": report_sections,
    }
    return TradingAgentsExecutionResult(
        action=action,
        confidence=None,
        risk_level=risk_level,
        summary=summary,
        supporting_points=[],
        risk_points=[],
        analyst_reports={},
        raw_decision=raw_decision_json,
        raw_state=_json_safe(final_state) if final_state is not None else None,
        final_report=_format_local_snapshot_report(
            summary,
            report_sections,
            [],
            [],
            decision_text,
            execution_source,
        ),
    )


def parse_local_snapshot_output(
    response_text: str,
    snapshot: dict[str, Any],
    config: TradingAgentsRunConfig,
) -> TradingAgentsExecutionResult:
    parsed, parse_error = _load_response_json(response_text)
    parse_failed = parsed is None
    candidate = snapshot.get("candidate", {})
    analyst_reports: dict[str, dict[str, Any]] = {}
    external_data_coverage = _coverage_from_snapshot(snapshot)
    execution_source = _execution_source(config, "TradingAgents 本地快照模式")
    if parse_failed:
        action = _map_action(response_text)
        risk_level = _map_risk_level(action, response_text)
        summary = _summary_from_output({}, response_text)
        supporting_points: list[str] = []
        risk_points = [parse_error] if parse_error else []
        parsed = {}
    else:
        action = _normalize_action(parsed.get("action"), response_text)
        risk_level = _normalize_risk_level(parsed.get("risk_level"), action, response_text)
        summary = _non_blank_or(parsed.get("summary"), _summary_from_output(parsed, response_text))
        analyst_reports = _normalize_analyst_reports(parsed.get("analyst_reports"))
        analyst_reports = _apply_snapshot_coverage_to_analyst_reports(analyst_reports, external_data_coverage)
        supporting_points = _string_list(parsed.get("supporting_points"))
        if not supporting_points:
            supporting_points = _aggregate_report_points(analyst_reports, "supporting_points")
        risk_points = _string_list(parsed.get("risk_points"))
        if not risk_points:
            risk_points = _aggregate_report_points(analyst_reports, "risk_points")
    if parse_failed:
        analyst_reports = _apply_snapshot_coverage_to_analyst_reports(analyst_reports, external_data_coverage)

    confidence = _normalize_confidence(parsed.get("confidence"))
    report_sections = _build_structured_report_sections(
        parsed=parsed,
        analyst_reports=analyst_reports,
        summary=summary,
        supporting_points=supporting_points,
        risk_points=risk_points,
        snapshot=snapshot,
        config=config,
    )
    raw_decision = {
        "schema_version": "1.0",
        "agent_system": config.agent_system,
        "mode": config.mode,
        "execution_source": execution_source,
        "llm_provider": config.llm_provider,
        "deep_think_llm": config.deep_think_llm,
        "quick_think_llm": config.quick_think_llm,
        "max_debate_rounds": config.max_debate_rounds,
        "max_risk_discuss_rounds": config.max_risk_discuss_rounds,
        "ticker": candidate.get("ts_code"),
        "action": action,
        "risk_level": risk_level,
        "summary": summary,
        "analyst_reports": analyst_reports,
        "report_sections": report_sections,
        "external_data_coverage": external_data_coverage,
        "supporting_points": supporting_points,
        "risk_points": risk_points,
        "raw_response": response_text,
    }
    if parse_error:
        raw_decision["parse_error"] = parse_error

    return TradingAgentsExecutionResult(
        action=action,
        confidence=confidence,
        risk_level=risk_level,
        summary=summary,
        supporting_points=supporting_points,
        risk_points=risk_points,
        analyst_reports=analyst_reports,
        raw_decision=raw_decision,
        raw_state={"snapshot": _json_safe(snapshot), "config": json.loads(config.to_json())},
        final_report=_format_local_snapshot_report(
            summary,
            report_sections,
            supporting_points,
            risk_points,
            response_text,
            execution_source,
        ),
    )


def unavailable_result(message: str) -> TradingAgentsExecutionResult:
    execution_source = {
        "agent_system": "TradingAgents",
        "mode": "unavailable_fallback",
        "source_label": "TradingAgents 不可用 fallback",
        "online_tools": False,
    }
    report_sections = _unavailable_report_sections(message, execution_source["source_label"])
    return TradingAgentsExecutionResult(
        action="no_opinion",
        confidence=None,
        risk_level="unknown",
        summary=message,
        supporting_points=[],
        risk_points=[message],
        analyst_reports={},
        raw_decision={
            "schema_version": "1.0",
            "agent_system": "TradingAgents",
            "action": "no_opinion",
            "risk_level": "unknown",
            "summary": message,
            "execution_source": execution_source,
            "report_sections": report_sections,
        },
        final_report=_format_local_snapshot_report(
            message,
            report_sections,
            [],
            [message],
            "",
            execution_source,
        ),
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
    return compact[:240] if compact else "TradingAgents 未返回可读复核意见。"


def _build_local_snapshot_prompt(snapshot: dict[str, Any], config: TradingAgentsRunConfig) -> str:
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2)
    return f"""你是纸面交易系统中的 TradingAgents 复核层。

只允许使用下方本地数据库快照。不要请求实时价格、新闻、基本面网页或任何外部工具。
确定性策略和组合系统仍是事实来源；你的输出只作为复核意见，不是交易指令。
快照里的 external_data、analysis_contexts 和 external_data_coverage 是已落库资料；
可以引用，但不得补写未提供事实。
快照里的 candidate.evidence_context 已分离为：
系统确定性复盘事实、缓存技术数据、缓存基本面数据、缓存新闻/公告数据、
缓存情绪数据、未接入/缺失警告。请优先使用这个分层来组织结论。

请分别扮演技术/量价、基本面、新闻、情绪、板块位置五个分析师，基于 snapshot.analysis_contexts
对应分区给出分析。若 external_data_coverage 标记某个分区为 unavailable，
必须明确写出“数据源未接入/数据不足”，
不要编造新闻、公告、社媒情绪或基本面事实。

请在内部最多进行 {config.max_debate_rounds} 轮简洁的多空权衡，然后只返回一个 JSON 对象。
除 JSON 键名、action/risk_level 枚举值、股票代码和必要指标名外，所有自然语言必须使用简体中文。
summary、supporting_points、risk_points 必须是中文。

JSON schema:
{{
  "action": "support | caution | reject | no_opinion",
  "confidence": 0.0,
  "risk_level": "low | medium | high | unknown",
  "summary": "一句简短中文复核摘要",
  "analyst_reports": {{
    "technical": {{
      "status": "available | partial | unavailable",
      "summary": "中文技术面结论",
      "supporting_points": ["中文支持依据"],
      "risk_points": ["中文风险提示"]
    }},
    "fundamental": {{
      "status": "available | partial | unavailable",
      "summary": "中文基本面结论",
      "supporting_points": ["中文支持依据"],
      "risk_points": ["中文风险提示"]
    }},
    "news": {{
      "status": "available | partial | unavailable",
      "summary": "中文新闻面结论",
      "supporting_points": ["中文支持依据"],
      "risk_points": ["中文风险提示"]
    }},
    "sentiment": {{
      "status": "available | partial | unavailable",
      "summary": "中文情绪面结论",
      "supporting_points": ["中文支持依据"],
      "risk_points": ["中文风险提示"]
    }},
    "sector": {{
      "status": "available | partial | unavailable",
      "summary": "中文板块位置结论",
      "supporting_points": ["中文支持依据"],
      "risk_points": ["中文风险提示"]
    }}
  }},
  "report_sections": {{
    "fundamental": {{"summary": "中文基本面", "supporting_points": ["中文"], "risk_points": ["中文"]}},
    "news": {{"summary": "中文新闻", "supporting_points": ["中文"], "risk_points": ["中文"]}},
    "sentiment": {{"summary": "中文情绪", "supporting_points": ["中文"], "risk_points": ["中文"]}},
    "technical": {{"summary": "中文技术/量价", "supporting_points": ["中文"], "risk_points": ["中文"]}},
    "sector": {{"summary": "中文板块位置", "supporting_points": ["中文"], "risk_points": ["中文"]}},
    "risk": {{"summary": "中文综合风险", "supporting_points": [], "risk_points": ["中文"]}},
    "conclusion": {{"summary": "中文结论", "supporting_points": ["中文"], "risk_points": ["中文"]}}
  }},
  "supporting_points": ["来自快照的中文支持依据"],
  "risk_points": ["来自快照的中文风险提示"]
}}

本地快照:
{snapshot_json}
"""


def _response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(part for part in parts if part).strip()
    return str(content).strip()


def _load_response_json(response_text: str) -> tuple[dict[str, Any] | None, str | None]:
    stripped = _strip_code_fence(response_text)
    try:
        loaded = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end <= start:
            return None, "TradingAgents 本地快照复核没有返回 JSON。"
        try:
            loaded = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            return None, f"TradingAgents 本地快照复核 JSON 解析失败：{exc}"
    if not isinstance(loaded, dict):
        return None, "TradingAgents 本地快照复核 JSON 不是对象。"
    return loaded, None


def _strip_code_fence(value: str) -> str:
    stripped = value.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _normalize_action(value: Any, fallback_text: str) -> str:
    action = str(value or "").strip().lower()
    if action in {"support", "caution", "reject", "no_opinion"}:
        return action
    return _map_action(fallback_text)


def _normalize_risk_level(value: Any, action: str, fallback_text: str) -> str:
    risk_level = str(value or "").strip().lower()
    if risk_level in {"low", "medium", "high", "unknown"}:
        return risk_level
    return _map_risk_level(action, fallback_text)


def _normalize_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence < 0 or confidence > 1:
        return None
    return confidence


def _coverage_from_snapshot(snapshot: dict[str, Any]) -> dict[str, str]:
    raw_coverage = snapshot.get("external_data_coverage")
    if not isinstance(raw_coverage, dict):
        candidate = snapshot.get("candidate", {})
        raw_coverage = candidate.get("external_data_coverage") if isinstance(candidate, dict) else None
    if not isinstance(raw_coverage, dict):
        return {}
    coverage: dict[str, str] = {}
    for key in EVIDENCE_COVERAGE_KEYS:
        status = str(raw_coverage.get(key) or "").strip().lower()
        if status in {"available", "partial", "unavailable"}:
            coverage[key] = status
    return coverage


def _apply_snapshot_coverage_to_analyst_reports(
    analyst_reports: dict[str, dict[str, Any]],
    external_data_coverage: dict[str, str],
) -> dict[str, dict[str, Any]]:
    if not external_data_coverage:
        return analyst_reports
    reports = {key: dict(value) for key, value in analyst_reports.items()}
    for key, coverage_status in external_data_coverage.items():
        report = dict(reports.get(key, {}))
        report["status"] = coverage_status
        if coverage_status == "unavailable":
            report["summary"] = _coverage_unavailable_summary(key)
            report["supporting_points"] = []
            risk_points = _string_list(report.get("risk_points"))
            warning = _coverage_unavailable_risk(key)
            if warning not in risk_points:
                risk_points.append(warning)
            report["risk_points"] = risk_points
        else:
            report["summary"] = _non_blank_or(report.get("summary"), _coverage_available_summary(key, coverage_status))
            report["supporting_points"] = _string_list(report.get("supporting_points"))
            report["risk_points"] = _string_list(report.get("risk_points"))
        reports[key] = report
    return reports


def _coverage_available_summary(key: str, status: str) -> str:
    label = {
        "technical": "技术面",
        "fundamental": "基本面",
        "news": "新闻面",
        "sentiment": "情绪面",
        "sector": "板块位置",
    }.get(key, key)
    return f"{label}数据覆盖为{status}。"


def _coverage_unavailable_summary(key: str) -> str:
    label = {
        "technical": "技术面",
        "fundamental": "基本面",
        "news": "新闻面",
        "sentiment": "情绪面",
        "sector": "板块位置",
    }.get(key, key)
    return f"{label}数据源未接入/数据不足。"


def _coverage_unavailable_risk(key: str) -> str:
    label = {
        "technical": "技术面",
        "fundamental": "基本面",
        "news": "新闻面",
        "sentiment": "情绪面",
        "sector": "板块位置",
    }.get(key, key)
    return f"{label}缺少真实输入，不能编造相关证据。"


def _normalize_analyst_reports(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    reports: dict[str, dict[str, Any]] = {}
    for key in ANALYST_SECTION_ORDER:
        report = value.get(key)
        if not isinstance(report, dict):
            continue
        status = str(report.get("status") or "partial").strip().lower()
        if status not in {"available", "partial", "unavailable"}:
            status = "partial"
        reports[key] = {
            "status": status,
            "summary": _non_blank_or(report.get("summary"), "该分析维度没有返回摘要。"),
            "supporting_points": _string_list(report.get("supporting_points")),
            "risk_points": _string_list(report.get("risk_points")),
        }
    return reports


def _aggregate_report_points(analyst_reports: dict[str, dict[str, Any]], field: str) -> list[str]:
    points: list[str] = []
    for key in ANALYST_SECTION_ORDER:
        report = analyst_reports.get(key, {})
        points.extend(_string_list(report.get(field)))
    return points[:8]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _non_blank_or(value: Any, fallback: str) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized else fallback


def _execution_source(config: TradingAgentsRunConfig | None, source_label: str) -> dict[str, Any]:
    return {
        "agent_system": config.agent_system if config else "TradingAgents",
        "mode": config.mode if config else "unknown",
        "source_label": source_label,
        "llm_provider": config.llm_provider if config else None,
        "deep_think_llm": config.deep_think_llm if config else None,
        "quick_think_llm": config.quick_think_llm if config else None,
        "online_tools": bool(config.online_tools) if config else None,
    }


def _build_structured_report_sections(
    *,
    parsed: Any,
    analyst_reports: dict[str, dict[str, Any]],
    summary: str,
    supporting_points: list[str],
    risk_points: list[str],
    snapshot: dict[str, Any] | None,
    config: TradingAgentsRunConfig | None,
) -> dict[str, dict[str, Any]]:
    raw_sections = parsed.get("report_sections") if isinstance(parsed, dict) else None
    if not isinstance(raw_sections, dict) and isinstance(parsed, dict):
        raw_sections = parsed.get("sections")
    if not isinstance(raw_sections, dict):
        raw_sections = {}
    coverage = _coverage_from_snapshot(snapshot or {})

    sections: dict[str, dict[str, Any]] = {}
    for key in REPORT_SECTION_ORDER:
        raw_section = raw_sections.get(key)
        if not isinstance(raw_section, dict):
            raw_section = analyst_reports.get(key, {}) if key in ANALYST_SECTION_ORDER else {}
        sections[key] = _normalize_report_section(
            key=key,
            value=raw_section,
            summary=summary,
            supporting_points=supporting_points,
            risk_points=risk_points,
            coverage=coverage,
            snapshot=snapshot,
            config=config,
        )
    return sections


def _normalize_report_section(
    *,
    key: str,
    value: dict[str, Any],
    summary: str,
    supporting_points: list[str],
    risk_points: list[str],
    coverage: dict[str, str],
    snapshot: dict[str, Any] | None,
    config: TradingAgentsRunConfig | None,
) -> dict[str, Any]:
    status = str(value.get("status") or coverage.get(key) or "partial").strip().lower()
    if key in {"risk", "conclusion"}:
        status = "available"
    elif status not in {"available", "partial", "unavailable"}:
        status = "partial"

    section_summary = _non_blank_or(value.get("summary"), _default_section_summary(key, summary, risk_points))
    section_supporting = _string_list(value.get("supporting_points"))
    section_risks = _string_list(value.get("risk_points"))

    if key == "risk" and not section_risks:
        section_risks = list(risk_points)
    if key == "conclusion":
        if not section_supporting:
            section_supporting = list(supporting_points[:4])
        if not section_risks:
            section_risks = list(risk_points[:4])

    if status == "unavailable":
        section_summary = _coverage_unavailable_summary(key)
        section_supporting = []
        warning = _coverage_unavailable_risk(key)
        if warning not in section_risks:
            section_risks.append(warning)

    return {
        "section_key": key,
        "section_name": REPORT_SECTION_NAMES[key],
        "status": status,
        "source_label": _section_source_label(key, snapshot, config),
        "source_refs": _section_source_refs(key, snapshot),
        "summary": section_summary,
        "supporting_points": section_supporting,
        "risk_points": section_risks,
    }


def _default_section_summary(key: str, summary: str, risk_points: list[str]) -> str:
    if key == "risk":
        return risk_points[0] if risk_points else "未返回独立风险段，需结合各分项风险人工复核。"
    if key == "conclusion":
        return summary
    return "该分析维度没有返回摘要。"


def _section_source_label(
    key: str,
    snapshot: dict[str, Any] | None,
    config: TradingAgentsRunConfig | None,
) -> str:
    mode = config.mode if config else "unknown"
    if mode == "local_snapshot_mode":
        mode_label = "TradingAgents 本地快照模式"
    elif mode == "external_graph_mode":
        mode_label = "TradingAgents 外部图模式"
    else:
        mode_label = "TradingAgents 输出"
    if key in {"risk", "conclusion"}:
        return f"{mode_label}；综合结构化复核输出"
    if not isinstance(snapshot, dict) and mode == "external_graph_mode":
        return f"{mode_label}；来源：TradingAgents 原始输出/外部工具"

    context = _analysis_context(snapshot, key)
    source = str(context.get("source") or "").strip() if isinstance(context, dict) else ""
    if source:
        return f"{mode_label}；来源：{source}"
    return f"{mode_label}；来源未接入/数据不足"


def _analysis_context(snapshot: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    candidate = snapshot.get("candidate")
    if not isinstance(candidate, dict):
        return {}
    contexts = candidate.get("analysis_contexts")
    if not isinstance(contexts, dict):
        return {}
    context = contexts.get(key)
    return context if isinstance(context, dict) else {}


def _section_source_refs(key: str, snapshot: dict[str, Any] | None) -> list[str]:
    if not isinstance(snapshot, dict):
        return []
    refs = snapshot.get("source_refs")
    source_refs = [str(ref) for ref in refs if str(ref).strip()] if isinstance(refs, list) else []
    prefixes = {
        "technical": ("market_bars:", "market_diagnostic_bars:", "strategy_signals:"),
        "fundamental": ("daily_basic_snapshots:", "agent_external_items:"),
        "news": ("agent_external_items:",),
        "sentiment": ("agent_external_items:", "market_bars:", "daily_basic_snapshots:"),
        "sector": ("market_review_runs:", "sector_daily_snapshots:", "sector_constituents:", "market_plan_contexts:"),
    }.get(key)
    if prefixes is None:
        return source_refs[:12]
    filtered = [ref for ref in source_refs if ref.startswith(prefixes)]
    return filtered[:12]


def _unavailable_report_sections(message: str, source_label: str) -> dict[str, dict[str, Any]]:
    sections: dict[str, dict[str, Any]] = {}
    for key in REPORT_SECTION_ORDER:
        sections[key] = {
            "section_key": key,
            "section_name": REPORT_SECTION_NAMES[key],
            "status": "unavailable" if key not in {"risk", "conclusion"} else "available",
            "source_label": source_label,
            "source_refs": [],
            "summary": message if key in {"risk", "conclusion"} else _coverage_unavailable_summary(key),
            "supporting_points": [],
            "risk_points": [message] if key in {"risk", "conclusion"} else [_coverage_unavailable_risk(key)],
        }
    return sections


def _format_local_snapshot_report(
    summary: str,
    report_sections: dict[str, dict[str, Any]],
    supporting_points: list[str],
    risk_points: list[str],
    response_text: str,
    execution_source: dict[str, Any],
) -> str:
    source_label = str(execution_source.get("source_label") or "TradingAgents 输出")
    mode = str(execution_source.get("mode") or "unknown")
    lines = [
        "# TradingAgents 中文结构化复核",
        "",
        f"来源：{source_label}",
        f"运行模式：{mode}",
        "",
        "## 结论摘要",
        "",
        summary,
    ]
    for key in REPORT_SECTION_ORDER:
        report = report_sections.get(key)
        if not report:
            continue
        title = str(report.get("section_name") or REPORT_SECTION_NAMES.get(key, key))
        lines.extend(["", f"## {title}", "", f"来源：{report.get('source_label') or source_label}", ""])
        source_refs = _string_list(report.get("source_refs"))
        if source_refs:
            lines.append(f"source_refs：{', '.join(source_refs)}")
            lines.append("")
        lines.append(str(report.get("summary") or "无摘要。"))
        report_supporting = _string_list(report.get("supporting_points"))
        if report_supporting:
            lines.extend(["", "支持依据：", *[f"- {point}" for point in report_supporting]])
        report_risks = _string_list(report.get("risk_points"))
        if report_risks:
            lines.extend(["", "风险提示：", *[f"- {point}" for point in report_risks]])
    if supporting_points:
        lines.extend(["", "## 综合支持依据", *[f"- {point}" for point in supporting_points]])
    if risk_points:
        lines.extend(["", "## 综合风险提示", *[f"- {point}" for point in risk_points]])
    if response_text:
        lines.extend(["", "## 原始输出", response_text])
    return "\n".join(lines).strip() + "\n"


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
