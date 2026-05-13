"""Read-only shadow strategy visibility snapshot service."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from pgc_trading.config import Paths
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult


SHADOW_STRATEGY_SNAPSHOT_CONTRACT = "shadow_strategy_snapshot_v1"
MONITOR_ARTIFACT_PATTERN = "strategy_shadow_monitor_*.json"
PREFLIGHT_ARTIFACT_PATTERN = "strategy_shadow_promotion_preflight_*.json"
FORBIDDEN_VISIBILITY_MUTATION_FLAGS = (
    "active_strategy_mutated",
    "active_params_mutated",
    "wrote_strategy_version",
    "wrote_strategy_versions",
    "writes_trade_state",
    "writes_paper_live_behavior",
    "paper_live_deployment_changed",
    "timer_mutated",
)


@dataclass(frozen=True)
class GetShadowStrategySnapshotRequest:
    as_of_date: str | None = None


@dataclass(frozen=True)
class ShadowStrategySnapshotResult:
    snapshot_contract: str = SHADOW_STRATEGY_SNAPSHOT_CONTRACT
    generated_at: str = ""
    db_path: str = ""
    reports_dir: str = ""
    as_of_date: str | None = None
    next_trade_date: str | None = None
    status: str = "unknown"
    read_only: bool = True
    artifact_only: bool = True
    latest: dict[str, Any] = field(default_factory=dict)
    source_artifacts: dict[str, str | None] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    blocker_counts: dict[str, int] = field(default_factory=dict)
    candidate_families: dict[str, int] = field(default_factory=dict)
    walk_forward: dict[str, Any] = field(default_factory=dict)
    frozen_cpb_comparison: dict[str, Any] = field(default_factory=dict)
    active_cpb_integrity: dict[str, Any] = field(default_factory=dict)
    release_gate: dict[str, Any] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    hypotheses: list[dict[str, Any]] = field(default_factory=list)
    safety: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)


class ShadowStrategyService:
    """Normalize artifact-only shadow strategy monitor/preflight state."""

    def __init__(self, db_path: Path | None = None, *, reports_dir: Path | None = None):
        paths = Paths()
        self.db_path = Path(db_path) if db_path is not None else paths.db_path
        self.reports_dir = Path(reports_dir) if reports_dir is not None else paths.reports_dir

    def get_snapshot(
        self,
        request: GetShadowStrategySnapshotRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ShadowStrategySnapshotResult]:
        as_of_date = _compact_date(request.as_of_date)
        if request.as_of_date is not None and not _is_yyyymmdd(as_of_date):
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_result(self.db_path, self.reports_dir, request.as_of_date),
                errors=[ServiceError("INVALID_AS_OF_DATE", "as_of_date must be compact YYYYMMDD.")],
            )

        errors: list[ServiceError] = []
        monitor_path = _latest_artifact(self.reports_dir, MONITOR_ARTIFACT_PATTERN, as_of_date)
        if monitor_path is None:
            errors.append(
                ServiceError(
                    "SHADOW_MONITOR_ARTIFACT_NOT_FOUND",
                    f"shadow monitor artifact not found in {self.reports_dir}",
                )
            )
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_result(self.db_path, self.reports_dir, as_of_date),
                errors=errors,
            )

        monitor, monitor_errors = _read_json_object(monitor_path, "shadow monitor")
        errors.extend(monitor_errors)
        snapshot_date = as_of_date or _compact_date(_first_text(monitor, "review_date"))
        preflight_path = _latest_artifact(self.reports_dir, PREFLIGHT_ARTIFACT_PATTERN, snapshot_date)
        preflight: dict[str, Any] = {}
        if preflight_path is None:
            errors.append(
                ServiceError(
                    "SHADOW_PREFLIGHT_ARTIFACT_NOT_FOUND",
                    f"shadow promotion preflight artifact not found in {self.reports_dir}",
                )
            )
        else:
            preflight, preflight_errors = _read_json_object(preflight_path, "shadow promotion preflight")
            errors.extend(preflight_errors)
        artifact_root = self.reports_dir.parent
        monitor = _normalize_embedded_artifact_paths(monitor, artifact_root)
        preflight = _normalize_embedded_artifact_paths(preflight, artifact_root)
        errors.extend(_mutation_guard_errors(monitor, preflight))

        if errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_result(self.db_path, self.reports_dir, snapshot_date),
                errors=errors,
            )

        snapshot_date = snapshot_date or _compact_date(_first_text(preflight, "review_date"))
        hypotheses = _load_shadow_hypotheses(self.db_path, snapshot_date)
        snapshot = _build_snapshot(
            db_path=self.db_path,
            reports_dir=self.reports_dir,
            monitor_path=monitor_path,
            preflight_path=preflight_path,
            monitor=monitor,
            preflight=preflight,
            hypotheses=hypotheses,
        )
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=snapshot,
            lineage={
                "as_of_date": snapshot.as_of_date,
                "monitor_artifact": str(monitor_path),
                "promotion_preflight_artifact": str(preflight_path),
                "shadow_hypothesis_count": len(hypotheses),
                "read_only": "true",
            },
        )


def _build_snapshot(
    *,
    db_path: Path,
    reports_dir: Path,
    monitor_path: Path,
    preflight_path: Path,
    monitor: dict[str, Any],
    preflight: dict[str, Any],
    hypotheses: list[dict[str, Any]],
) -> ShadowStrategySnapshotResult:
    monitor_date = _compact_date(_first_text(monitor, "review_date"))
    preflight_date = _compact_date(_first_text(preflight, "review_date"))
    as_of_date = preflight_date or monitor_date
    next_trade_date = _first_text(preflight, "next_trade_date") or _first_text(monitor, "next_trade_date")
    source_artifacts = _source_artifacts(monitor_path, preflight_path)
    hypothesis_by_key = {item["candidate_key"]: item for item in hypotheses if item.get("candidate_key")}
    candidates = _normalize_candidates(
        monitor=monitor,
        preflight=preflight,
        hypotheses_by_key=hypothesis_by_key,
        source_artifacts=source_artifacts,
    )
    candidate_families = dict(Counter(str(item.get("candidate_family") or "unknown") for item in candidates))
    blocker_counts = _blocker_counts(preflight, candidates)
    walk_forward = _walk_forward_payload(monitor, preflight, candidates)
    active_cpb_integrity = _active_cpb_integrity(preflight, monitor)
    release_gate = _release_gate_payload(preflight, monitor)
    safety = _safety_payload(preflight, monitor)
    candidate_count = _int_value(preflight.get("candidate_count"), len(candidates))

    counts = {
        "candidate_count": candidate_count,
        "monitor_candidate_count": len(_list_value(monitor.get("candidate_monitors"))),
        "preflight_candidate_count": len(_list_value(preflight.get("candidate_gates"))),
        "prior_candidate_count": _int_value(monitor.get("prior_candidate_count"), 0),
        "today_candidate_count": _int_value(monitor.get("today_candidate_count"), 0),
        "shadow_hypothesis_count": len(hypotheses),
        "artifact_only_hypothesis_count": sum(1 for item in hypotheses if bool(item.get("artifact_only"))),
        "distinct_blocker_count": len(blocker_counts),
        "blocked_candidate_count": sum(1 for item in candidates if item.get("status") == "blocked"),
    }
    status = str(preflight.get("status") or ("blocked" if blocker_counts else "available"))
    latest = {
        "monitor_review_date": monitor_date,
        "promotion_preflight_review_date": preflight_date,
        "monitor_generated_at": _first_text(monitor, "generated_at"),
        "promotion_preflight_generated_at": _first_text(preflight, "generated_at"),
        "next_trade_date": next_trade_date,
    }
    summary = {
        "status": status,
        "read_only": True,
        "artifact_only": True,
        "candidate_count": counts["candidate_count"],
        "blocked_candidate_count": counts["blocked_candidate_count"],
        "distinct_blocker_count": counts["distinct_blocker_count"],
        "active_cpb_integrity_status": active_cpb_integrity.get("status"),
        "release_gate_status": release_gate.get("status"),
    }

    return ShadowStrategySnapshotResult(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        db_path=str(db_path),
        reports_dir=str(reports_dir),
        as_of_date=as_of_date,
        next_trade_date=next_trade_date,
        status=status,
        latest=latest,
        source_artifacts=source_artifacts,
        counts=counts,
        blocker_counts=blocker_counts,
        candidate_families=candidate_families,
        walk_forward=walk_forward,
        frozen_cpb_comparison=_frozen_cpb_comparison(preflight, monitor, candidates),
        active_cpb_integrity=active_cpb_integrity,
        release_gate=release_gate,
        candidates=candidates,
        hypotheses=hypotheses,
        safety=safety,
        summary=summary,
    )


def _normalize_candidates(
    *,
    monitor: dict[str, Any],
    preflight: dict[str, Any],
    hypotheses_by_key: dict[str, dict[str, Any]],
    source_artifacts: dict[str, str | None],
) -> list[dict[str, Any]]:
    monitor_candidates = _list_value(monitor.get("candidate_monitors"))
    preflight_gates = {
        str(item.get("candidate_key")): item
        for item in _list_value(preflight.get("candidate_gates"))
        if isinstance(item, Mapping) and item.get("candidate_key")
    }
    if not monitor_candidates:
        monitor_candidates = list(preflight_gates.values())

    candidates: list[dict[str, Any]] = []
    for raw in monitor_candidates:
        if not isinstance(raw, Mapping):
            continue
        candidate_key = str(raw.get("candidate_key") or "")
        if not candidate_key:
            continue
        gate = preflight_gates.get(candidate_key, {})
        hypothesis = hypotheses_by_key.get(candidate_key)
        candidate_family = str(raw.get("candidate_family") or gate.get("candidate_family") or "unknown")
        paper_gate = _first_mapping(
            _nested_mapping(raw, "promotion_gates", "paper_observation_gate"),
            gate.get("paper_observation_gate"),
            hypothesis.get("paper_observation_gate") if hypothesis else None,
        )
        strategy_gate = _first_mapping(
            _nested_mapping(raw, "promotion_gates", "strategy_version_gate"),
            gate.get("strategy_version_gate"),
            hypothesis.get("strategy_version_gate") if hypothesis else None,
        )
        walk_forward = _first_mapping(raw.get("walk_forward_progress"), gate.get("walk_forward_progress"))
        comparison = _first_mapping(raw.get("comparison_vs_frozen_cpb"), gate.get("comparison_vs_frozen_cpb"))
        paper_blockers = _text_list(paper_gate.get("blockers"))
        strategy_blockers = _text_list(strategy_gate.get("blockers"))
        blockers = _unique_texts([*paper_blockers, *strategy_blockers, *_text_list(walk_forward.get("blockers"))])
        artifact_paths = _candidate_artifact_paths(raw, gate, hypothesis, source_artifacts)
        linked_hypothesis = None
        if hypothesis is not None:
            linked_hypothesis = {
                "hypothesis_id": hypothesis.get("hypothesis_id"),
                "as_of_date": hypothesis.get("as_of_date"),
                "status": hypothesis.get("status"),
                "title": hypothesis.get("title"),
            }
        candidates.append(
            {
                "candidate_key": candidate_key,
                "candidate_family": candidate_family,
                "status": str(gate.get("status") or ("blocked" if blockers else "available")),
                "artifact_only": True,
                "signal_source": raw.get("signal_source") or gate.get("signal_source"),
                "prior_candidate_count": raw.get("prior_candidate_count"),
                "today_candidate_count": raw.get("today_candidate_count"),
                "today_top": raw.get("today_top"),
                "walk_forward_status": str(walk_forward.get("status") or "unknown"),
                "walk_forward": walk_forward,
                "comparison_vs_frozen_cpb": comparison,
                "paper_observation_gate": paper_gate,
                "strategy_version_gate": strategy_gate,
                "paper_blockers": paper_blockers,
                "strategy_version_blockers": strategy_blockers,
                "paper_blocker_count": len(paper_blockers),
                "strategy_version_blocker_count": len(strategy_blockers),
                "blockers": blockers,
                "blocker_count": len(blockers),
                "source_artifacts": artifact_paths,
                "linked_hypothesis": linked_hypothesis,
                "promotion_allowed": False,
                "paper_observation_allowed": False,
            }
        )
    return candidates


def _load_shadow_hypotheses(db_path: Path, as_of_date: str | None) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn, "strategy_hypotheses"):
            return []
        clauses: list[str] = []
        params: list[str] = []
        if as_of_date is not None:
            clauses.append("as_of_date <= ?")
            params.append(as_of_date)
        sql = "SELECT * FROM strategy_hypotheses"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY as_of_date DESC, id DESC"
        rows = conn.execute(sql, params).fetchall()

    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        evidence = _loads_json_object(row["evidence_json"])
        proposed_change = _loads_json_object(row["proposed_change_json"])
        candidate_key = _first_text(evidence, "candidate_key") or _first_text(proposed_change, "candidate_key")
        if not candidate_key or not _is_shadow_hypothesis(evidence, proposed_change):
            continue
        if candidate_key in by_key:
            continue
        paper_gate = _first_mapping(evidence.get("paper_observation_gate"))
        strategy_gate = _first_mapping(evidence.get("strategy_version_gate"))
        by_key[candidate_key] = {
            "hypothesis_id": int(row["id"]),
            "as_of_date": str(row["as_of_date"]),
            "hypothesis_type": str(row["hypothesis_type"]),
            "title": str(row["title"]),
            "rationale": str(row["rationale"]),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "candidate_key": candidate_key,
            "candidate_family": _first_text(evidence, "candidate_family")
            or _first_text(proposed_change, "candidate_family")
            or "unknown",
            "artifact_only": bool(evidence.get("artifact_only") or proposed_change.get("artifact_only")),
            "artifact_paths": _text_list(evidence.get("artifact_paths")),
            "paper_observation_gate": paper_gate,
            "strategy_version_gate": strategy_gate,
            "paper_blockers": _text_list(paper_gate.get("blockers")),
            "strategy_version_blockers": _text_list(strategy_gate.get("blockers")),
            "shadow_comparison": _first_mapping(evidence.get("shadow_comparison")),
            "proposed_change": proposed_change,
        }
    return sorted(by_key.values(), key=lambda item: str(item["candidate_key"]))


def _is_shadow_hypothesis(evidence: dict[str, Any], proposed_change: dict[str, Any]) -> bool:
    return (
        evidence.get("source") == "m69_shadow_research"
        or proposed_change.get("change_type") == "shadow_candidate"
        or bool(evidence.get("artifact_only") and (evidence.get("candidate_key") or proposed_change.get("candidate_key")))
    )


def _blocker_counts(preflight: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, int]:
    raw_counts = preflight.get("blocker_counts")
    if isinstance(raw_counts, Mapping):
        return {str(key): _int_value(value, 0) for key, value in sorted(raw_counts.items())}
    counts: Counter[str] = Counter()
    for candidate in candidates:
        counts.update(_text_list(candidate.get("blockers")))
    counts.update(_text_list(preflight.get("blockers")))
    return dict(sorted(counts.items()))


def _walk_forward_payload(
    monitor: dict[str, Any],
    preflight: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    raw = _first_mapping(monitor.get("walk_forward_progress"))
    by_candidate = []
    for candidate in candidates:
        walk = _first_mapping(candidate.get("walk_forward"))
        by_candidate.append(
            {
                "candidate_key": candidate.get("candidate_key"),
                "candidate_family": candidate.get("candidate_family"),
                "status": walk.get("status") or candidate.get("walk_forward_status"),
                "required_days": walk.get("required_days") or preflight.get("required_walk_forward_days"),
                "days": walk.get("days") or walk.get("n"),
                "start_signal_date": walk.get("start_signal_date"),
                "latest_signal_date": walk.get("latest_signal_date"),
                "source_artifact": walk.get("source_artifact"),
                "blockers": _text_list(walk.get("blockers")),
            }
        )
    return {
        "status": raw.get("status") or "unknown",
        "required_days": raw.get("required_days") or preflight.get("required_walk_forward_days"),
        "evaluable_signal_days": raw.get("evaluable_signal_days"),
        "start_signal_date": raw.get("start_signal_date"),
        "latest_signal_date": raw.get("latest_signal_date"),
        "latest_outcome_date": raw.get("latest_outcome_date"),
        "summary": _list_value(raw.get("summary")),
        "by_candidate": by_candidate,
    }


def _frozen_cpb_comparison(
    preflight: dict[str, Any],
    monitor: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline = _first_mapping(preflight.get("frozen_cpb_baseline"), monitor.get("frozen_cpb_baseline"))
    return {
        "baseline": baseline,
        "by_candidate": [
            {
                "candidate_key": item.get("candidate_key"),
                "candidate_family": item.get("candidate_family"),
                "comparison": item.get("comparison_vs_frozen_cpb") or {},
            }
            for item in candidates
        ],
    }


def _active_cpb_integrity(preflight: dict[str, Any], monitor: dict[str, Any]) -> dict[str, Any]:
    raw = dict(_first_mapping(preflight.get("active_cpb_integrity"), monitor.get("active_cpb_integrity")))
    integrity_safety = _first_mapping(raw.get("safety"))
    visibility_unchanged = not any(
        bool(integrity_safety.get(key))
        for key in (
            "active_params_mutated",
            "wrote_strategy_version",
            "writes_trade_state",
            "writes_paper_live_behavior",
            "timer_mutated",
        )
    )
    raw["status"] = "unchanged" if visibility_unchanged else "mutation_risk"
    raw["visibility_layer_mutated_active_cpb"] = False
    raw["blockers"] = _text_list(raw.get("blockers"))
    return raw


def _release_gate_payload(preflight: dict[str, Any], monitor: dict[str, Any]) -> dict[str, Any]:
    gate = _first_mapping(preflight.get("release_gate"), monitor.get("release_gate"))
    if not gate:
        gate = {
            "status": "blocked",
            "displayed_surfaces": ["monitor_artifact", "promotion_preflight_artifact", "shadow_snapshot_api"],
            "blocked_paths": [
                "active_cpb_params",
                "strategy_versions",
                "trade_plans",
                "trades",
                "positions",
                "paper_live_behavior",
                "timer",
            ],
        }
    gate["status"] = str(gate.get("status") or "blocked")
    gate["artifact_only"] = bool(gate.get("artifact_only", True))
    gate["promotion_allowed"] = bool(gate.get("promotion_allowed", False))
    gate["timer_mutated"] = bool(gate.get("timer_mutated", False))
    return gate


def _safety_payload(preflight: dict[str, Any], monitor: dict[str, Any]) -> dict[str, Any]:
    raw = dict(_first_mapping(preflight.get("safety"), monitor.get("safety")))
    raw.update(
        {
            "read_only": True,
            "artifact_only": True,
            "active_params_mutated": bool(raw.get("active_params_mutated", False)),
            "wrote_strategy_version": bool(raw.get("wrote_strategy_version", False)),
            "writes_trade_state": bool(raw.get("writes_trade_state", False)),
            "writes_paper_live_behavior": bool(raw.get("writes_paper_live_behavior", False)),
            "timer_mutated": bool(raw.get("timer_mutated", False)),
            "promotion_allowed": bool(raw.get("promotion_allowed", False)),
            "paper_observation_allowed": bool(raw.get("paper_observation_allowed", False)),
            "visibility_layer_writes": False,
        }
    )
    return raw


def _mutation_guard_errors(monitor: dict[str, Any], preflight: dict[str, Any]) -> list[ServiceError]:
    errors: list[ServiceError] = []
    checked_payloads = [
        ("shadow monitor methodology", _first_mapping(monitor.get("methodology"))),
        ("shadow monitor safety", _first_mapping(monitor.get("safety"))),
        ("shadow preflight safety", _first_mapping(preflight.get("safety"))),
        (
            "shadow monitor active CPB integrity safety",
            _first_mapping(_first_mapping(monitor.get("active_cpb_integrity")).get("safety")),
        ),
        (
            "shadow preflight active CPB integrity safety",
            _first_mapping(_first_mapping(preflight.get("active_cpb_integrity")).get("safety")),
        ),
        ("shadow preflight release gate", _first_mapping(preflight.get("release_gate"))),
    ]
    for label, payload in checked_payloads:
        for flag in FORBIDDEN_VISIBILITY_MUTATION_FLAGS:
            if bool(payload.get(flag)):
                errors.append(
                    ServiceError(
                        "SHADOW_VISIBILITY_MUTATION_RISK",
                        f"{label} reports {flag}=true; shadow visibility must remain artifact-only.",
                    )
                )
    safety = _first_mapping(preflight.get("safety"), monitor.get("safety"))
    if bool(safety.get("promotion_allowed")) or bool(safety.get("paper_observation_allowed")):
        errors.append(
            ServiceError(
                "SHADOW_VISIBILITY_PROMOTION_RISK",
                "shadow visibility artifact reports paper observation or promotion as allowed.",
            )
        )
    return errors


def _source_artifacts(monitor_path: Path, preflight_path: Path) -> dict[str, str | None]:
    monitor_md = monitor_path.with_suffix(".md")
    preflight_md = preflight_path.with_suffix(".md")
    return {
        "monitor_json": str(monitor_path),
        "monitor_markdown": str(monitor_md) if monitor_md.exists() else None,
        "promotion_preflight_json": str(preflight_path),
        "promotion_preflight_markdown": str(preflight_md) if preflight_md.exists() else None,
    }


def _candidate_artifact_paths(
    raw: Mapping[str, Any],
    gate: Mapping[str, Any],
    hypothesis: dict[str, Any] | None,
    source_artifacts: dict[str, str | None],
) -> list[str]:
    paths: list[str] = [path for path in source_artifacts.values() if path]
    source = _first_mapping(raw.get("source"), gate.get("source"))
    outputs = _first_mapping(source.get("outputs"))
    paths.extend(_text_list(list(outputs.values())))
    for payload in (raw, gate):
        walk = _first_mapping(payload.get("walk_forward_progress"))
        paths.extend(_text_list(walk.get("source_artifact")))
    if hypothesis is not None:
        paths.extend(_text_list(hypothesis.get("artifact_paths")))
    return _unique_texts(paths)


def _latest_artifact(reports_dir: Path, pattern: str, as_of_date: str | None) -> Path | None:
    if as_of_date is not None:
        suffix = f"_{as_of_date}.json"
        exact = sorted(path for path in reports_dir.glob(pattern) if path.name.endswith(suffix))
        return exact[-1] if exact else None
    candidates = [path for path in reports_dir.glob(pattern) if path.is_file()]
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: (_artifact_date(path), path.stat().st_mtime, path.name))[-1]


def _artifact_date(path: Path) -> str:
    match = re.search(r"_(\d{8})\.json$", path.name)
    return match.group(1) if match else ""


def _read_json_object(path: Path, label: str) -> tuple[dict[str, Any], list[ServiceError]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [ServiceError("INVALID_SHADOW_ARTIFACT", f"{label} artifact is not valid JSON: {path}: {exc}")]
    if not isinstance(payload, Mapping):
        return {}, [ServiceError("INVALID_SHADOW_ARTIFACT", f"{label} artifact must be a JSON object: {path}")]
    return dict(payload), []


def _normalize_embedded_artifact_paths(value: Any, artifact_root: Path) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalize_embedded_artifact_paths(item, artifact_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_embedded_artifact_paths(item, artifact_root) for item in value]
    if isinstance(value, str):
        return _normalize_embedded_artifact_path(value, artifact_root)
    return value


def _normalize_embedded_artifact_path(value: str, artifact_root: Path) -> str:
    text = value.strip()
    if not text.startswith("/"):
        return value
    marker = "/pgc/"
    if marker not in text:
        return value
    relative = text.split(marker, 1)[1].strip("/")
    if not relative or relative.startswith("../"):
        return value
    return str(artifact_root / relative)


def _empty_result(db_path: Path, reports_dir: Path, as_of_date: str | None) -> ShadowStrategySnapshotResult:
    return ShadowStrategySnapshotResult(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        db_path=str(db_path),
        reports_dir=str(reports_dir),
        as_of_date=_compact_date(as_of_date),
        status="unavailable",
        latest={},
        source_artifacts={},
        safety={
            "read_only": True,
            "artifact_only": True,
            "visibility_layer_writes": False,
            "active_params_mutated": False,
            "wrote_strategy_version": False,
            "writes_trade_state": False,
            "writes_paper_live_behavior": False,
            "timer_mutated": False,
        },
        summary={"status": "unavailable", "read_only": True, "artifact_only": True},
    )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _loads_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _nested_mapping(payload: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key)
    return dict(current) if isinstance(current, Mapping) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [str(item) for item in value.values() if item is not None]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _unique_texts(values: list[str]) -> list[str]:
    return sorted({str(value) for value in values if str(value)})


def _first_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _compact_date(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return f"{text[:4]}{text[5:7]}{text[8:10]}"
    return text or None


def _is_yyyymmdd(value: str | None) -> bool:
    return value is not None and len(value) == 8 and value.isdigit()
