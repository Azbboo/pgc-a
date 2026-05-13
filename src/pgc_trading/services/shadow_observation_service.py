"""Read-only shadow observation scorecard service."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from pgc_trading.config import Paths
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult, ServiceWarning
from pgc_trading.services.shadow_strategy_service import (
    GetShadowStrategySnapshotRequest,
    ShadowStrategyService,
)


SHADOW_OBSERVATION_SCORECARD_CONTRACT = "shadow_observation_scorecard_v1"
SHADOW_PROMOTION_DOSSIER_CONTRACT = "shadow_promotion_dossier_v1"
DEFAULT_REQUIRED_SAMPLE_SIZE = 20
DEFAULT_MIN_FROZEN_CPB_DELTA_PCT = 0.0
DEFAULT_MAX_DRAWDOWN_PCT = -8.0


@dataclass(frozen=True)
class GetShadowObservationScorecardRequest:
    as_of_date: str | None = None


@dataclass(frozen=True)
class BuildShadowPromotionDossierRequest:
    as_of_date: str | None = None
    output_path: str | None = None


@dataclass(frozen=True)
class ShadowObservationScorecardResult:
    scorecard_contract: str = SHADOW_OBSERVATION_SCORECARD_CONTRACT
    generated_at: str = ""
    db_path: str = ""
    reports_dir: str = ""
    as_of_date: str | None = None
    next_trade_date: str | None = None
    status: str = "unknown"
    read_only: bool = True
    artifact_only: bool = True
    source_snapshot_contract: str = "shadow_strategy_snapshot_v1"
    source_artifacts: dict[str, str | None] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    scorecard_rows: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ShadowPromotionDossierResult:
    dossier_contract: str = SHADOW_PROMOTION_DOSSIER_CONTRACT
    generated_at: str = ""
    as_of_date: str | None = None
    would_write_artifact: bool = True
    wrote_artifact: bool = False
    artifact_path: str | None = None
    markdown_path: str | None = None
    artifact: dict[str, Any] = field(default_factory=dict)
    active_params_mutated: bool = False
    wrote_strategy_version: bool = False
    writes_trade_state: bool = False
    writes_paper_live_behavior: bool = False
    timer_mutated: bool = False


class ShadowObservationService:
    """Build the normalized observation queue used by Dashboard and ops views."""

    def __init__(self, db_path: Path | None = None, *, reports_dir: Path | None = None):
        paths = Paths()
        self.db_path = Path(db_path) if db_path is not None else paths.db_path
        self.reports_dir = Path(reports_dir) if reports_dir is not None else paths.reports_dir
        self._snapshot_service = ShadowStrategyService(self.db_path, reports_dir=self.reports_dir)

    def get_scorecard(
        self,
        request: GetShadowObservationScorecardRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ShadowObservationScorecardResult]:
        snapshot_result = self._snapshot_service.get_snapshot(
            GetShadowStrategySnapshotRequest(as_of_date=request.as_of_date),
            RequestContext(
                request_id=ctx.request_id,
                dry_run=True,
                operator=ctx.operator,
                source=ctx.source,
            ),
        )
        if not snapshot_result.ok:
            snapshot_data = snapshot_result.data
            missing_artifact = any(
                error.code in {"SHADOW_MONITOR_ARTIFACT_NOT_FOUND", "SHADOW_PREFLIGHT_ARTIFACT_NOT_FOUND"}
                for error in snapshot_result.errors
            )
            missing_blockers = _snapshot_missing_blockers(snapshot_result.errors)
            return ServiceResult(
                status="success" if missing_artifact else snapshot_result.status,
                request_id=ctx.request_id,
                data=_empty_result(
                    self.db_path,
                    self.reports_dir,
                    getattr(snapshot_data, "as_of_date", request.as_of_date),
                    getattr(snapshot_data, "next_trade_date", None),
                    blockers=missing_blockers,
                ),
                warnings=snapshot_result.warnings,
                errors=[] if missing_artifact else snapshot_result.errors,
                lineage={
                    **snapshot_result.lineage,
                    "read_only": "true",
                    "scorecard_contract": SHADOW_OBSERVATION_SCORECARD_CONTRACT,
                    "artifact_only": "true",
                    "status": "missing",
                },
            )

        snapshot = snapshot_result.data
        if snapshot is None:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_result(self.db_path, self.reports_dir, request.as_of_date, None),
                errors=[ServiceError("SHADOW_SNAPSHOT_EMPTY", "shadow strategy snapshot returned no data.")],
            )

        raw_rows_by_candidate = _monitor_rows_by_candidate(getattr(snapshot, "source_artifacts", {}) or {})
        artifact_root = self.reports_dir.parent
        rows = _portable_artifact_paths(_scorecard_rows(snapshot, self.db_path, raw_rows_by_candidate), artifact_root)
        status = _scorecard_status(rows, getattr(snapshot, "status", "unknown"))
        counts = _scorecard_counts(rows)
        coverage = _coverage_payload(rows)
        summary = _scorecard_summary(rows, status)
        result = ShadowObservationScorecardResult(
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            db_path=str(self.db_path),
            reports_dir=str(self.reports_dir),
            as_of_date=getattr(snapshot, "as_of_date", None),
            next_trade_date=getattr(snapshot, "next_trade_date", None),
            status=status,
            source_snapshot_contract=getattr(snapshot, "snapshot_contract", "shadow_strategy_snapshot_v1"),
            source_artifacts=_portable_artifact_paths(dict(getattr(snapshot, "source_artifacts", {}) or {}), artifact_root),
            counts=counts,
            coverage=coverage,
            safety=_observation_safety(getattr(snapshot, "safety", {}) or {}),
            summary=summary,
            rows=rows,
            scorecard_rows=rows,
            candidates=rows,
        )
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=result,
            lineage={
                "as_of_date": result.as_of_date,
                "candidate_count": counts.get("candidate_count", 0),
                "read_only": "true",
                "artifact_only": "true",
                "scorecard_contract": SHADOW_OBSERVATION_SCORECARD_CONTRACT,
            },
        )

    def build_promotion_dossier(
        self,
        request: BuildShadowPromotionDossierRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ShadowPromotionDossierResult]:
        """Write a review-only promotion dossier artifact without strategy/trading mutation."""

        snapshot_result = self._snapshot_service.get_snapshot(
            GetShadowStrategySnapshotRequest(as_of_date=request.as_of_date),
            RequestContext(
                request_id=ctx.request_id,
                dry_run=True,
                operator=ctx.operator,
                source=ctx.source,
            ),
        )
        if not snapshot_result.ok or snapshot_result.data is None:
            return ServiceResult(
                status=snapshot_result.status,
                request_id=ctx.request_id,
                data=_empty_dossier(request.as_of_date),
                warnings=snapshot_result.warnings,
                errors=snapshot_result.errors,
                lineage={"read_only": "true", "artifact_only": "true", "wrote_artifact": "false"},
            )

        snapshot = snapshot_result.data
        artifact = _portable_artifact_paths(_promotion_dossier_artifact(snapshot), self.reports_dir.parent)
        as_of_date = str(artifact.get("as_of_date") or getattr(snapshot, "as_of_date", None) or request.as_of_date or "latest")
        artifact_path = Path(request.output_path).expanduser() if request.output_path else self.reports_dir / f"shadow_promotion_dossier_{as_of_date}.json"
        markdown_path = self.reports_dir / f"shadow_promotion_dossier_{as_of_date}.md"
        wrote_artifact = False
        if not ctx.dry_run:
            self.reports_dir.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            markdown_path.write_text(_promotion_dossier_markdown(artifact), encoding="utf-8")
            wrote_artifact = True

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=ShadowPromotionDossierResult(
                generated_at=str(artifact["generated_at"]),
                as_of_date=as_of_date,
                wrote_artifact=wrote_artifact,
                artifact_path=str(artifact_path) if wrote_artifact else None,
                markdown_path=str(markdown_path) if wrote_artifact else None,
                artifact=artifact,
                active_params_mutated=False,
                wrote_strategy_version=False,
                writes_trade_state=False,
                writes_paper_live_behavior=False,
                timer_mutated=False,
            ),
            lineage={
                "as_of_date": as_of_date,
                "dossier_contract": SHADOW_PROMOTION_DOSSIER_CONTRACT,
                "read_only": "true",
                "artifact_only": "true",
                "wrote_artifact": str(wrote_artifact).lower(),
            },
        )


def _empty_result(
    db_path: Path,
    reports_dir: Path,
    as_of_date: str | None,
    next_trade_date: str | None,
    *,
    blockers: list[str] | None = None,
) -> ShadowObservationScorecardResult:
    blockers = blockers or ["shadow_observation_source_missing"]
    return ShadowObservationScorecardResult(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        db_path=str(db_path),
        reports_dir=str(reports_dir),
        as_of_date=as_of_date,
        next_trade_date=next_trade_date,
        status="missing",
        counts={
            "candidate_count": 0,
            "blocked_candidate_count": 0,
            "insufficient_sample_count": 0,
            "market_data_gap_count": 0,
            "observed_candidate_count": 0,
            "insufficient_sample_candidate_count": 0,
            "missing_candidate_count": 0,
            "distinct_blocker_count": len(blockers),
        },
        coverage={
            "status": "missing",
            "state_counts": {"missing": 1},
            "market_data_state_counts": {},
            "missing_market_bar_count": 0,
        },
        safety=_observation_safety({}),
        summary={
            "status": "missing",
            "top_candidate_key": None,
            "blockers": blockers,
            "operator_note": "Shadow observation scorecard unavailable; promotion remains blocked.",
        },
    )


def _empty_dossier(as_of_date: str | None) -> ShadowPromotionDossierResult:
    return ShadowPromotionDossierResult(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        as_of_date=as_of_date,
        would_write_artifact=True,
        wrote_artifact=False,
        artifact_path=None,
        markdown_path=None,
        artifact={
            "artifact_type": "shadow_promotion_dossier",
            "dossier_contract": SHADOW_PROMOTION_DOSSIER_CONTRACT,
            "as_of_date": as_of_date,
            "summary": {
                "status": "unavailable",
                "candidate_count": 0,
                "review_ready_count": 0,
                "blocked_count": 0,
                "promotion_allowed": False,
            },
            "safety": _dossier_safety({}),
        },
    )


def _promotion_dossier_artifact(snapshot: object) -> dict[str, Any]:
    threshold_metadata = _promotion_threshold_metadata(snapshot)
    candidates = [
        _candidate_dossier(candidate, threshold_metadata)
        for candidate in getattr(snapshot, "candidates", []) or []
        if isinstance(candidate, Mapping)
    ]
    review_ready_count = sum(1 for item in candidates if item.get("review_status") == "review_ready")
    blocked_count = len(candidates) - review_ready_count
    return {
        "artifact_type": "shadow_promotion_dossier",
        "dossier_contract": SHADOW_PROMOTION_DOSSIER_CONTRACT,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of_date": getattr(snapshot, "as_of_date", None),
        "next_trade_date": getattr(snapshot, "next_trade_date", None),
        "threshold_metadata": threshold_metadata,
        "source_artifacts": dict(getattr(snapshot, "source_artifacts", {}) or {}),
        "summary": {
            "status": "blocked",
            "candidate_count": len(candidates),
            "review_ready_count": review_ready_count,
            "blocked_count": blocked_count,
            "review_ready_is_not_approval": True,
            "promotion_allowed": False,
            "read_only": True,
            "artifact_only": True,
        },
        "release_gate": _promotion_release_gate(getattr(snapshot, "release_gate", {}) or {}),
        "candidates": candidates,
        "safety": _dossier_safety(getattr(snapshot, "safety", {}) or {}),
    }


def _promotion_threshold_metadata(snapshot: object) -> dict[str, Any]:
    walk_forward = _mapping(getattr(snapshot, "walk_forward", {}))
    return {
        "minimum_sample": {
            "required_days": _int_value(walk_forward.get("required_days"), DEFAULT_REQUIRED_SAMPLE_SIZE),
            "reason": "minimum observation sample before promotion review readiness",
        },
        "positive_frozen_cpb_delta": {
            "minimum_delta_pct": DEFAULT_MIN_FROZEN_CPB_DELTA_PCT,
            "metric": "comparison_vs_frozen_cpb.t1_close_mean_delta_pct",
        },
        "evidence_coverage": {
            "requires_linked_shadow_hypothesis": True,
            "minimum_source_artifacts": 2,
        },
        "drawdown_cap": {
            "minimum_drawdown_proxy_pct": DEFAULT_MAX_DRAWDOWN_PCT,
            "metric": "max_drawdown_pct or mae_10d_median_pct",
        },
        "blocker_clearance": {
            "requires_zero_candidate_blockers": True,
            "manual_promotion_blocker_still_required": True,
        },
    }


def _candidate_dossier(candidate: Mapping[str, Any], threshold_metadata: Mapping[str, Any]) -> dict[str, Any]:
    walk = _mapping(candidate.get("walk_forward"))
    comparison = _mapping(candidate.get("comparison_vs_frozen_cpb"))
    blockers = _unique_texts(_list_text(candidate.get("blockers")))
    sample_size = _sample_size(walk, comparison)
    required_sample = _int_value(
        _mapping(threshold_metadata.get("minimum_sample")).get("required_days"),
        DEFAULT_REQUIRED_SAMPLE_SIZE,
    )
    frozen_delta = _float_or_none(comparison.get("t1_close_mean_delta_pct"))
    min_delta = _float_value(
        _mapping(threshold_metadata.get("positive_frozen_cpb_delta")).get("minimum_delta_pct"),
        DEFAULT_MIN_FROZEN_CPB_DELTA_PCT,
    )
    source_artifacts = _unique_texts(_list_text(candidate.get("source_artifacts")))
    linked_hypothesis = _mapping(candidate.get("linked_hypothesis"))
    min_source_artifacts = _int_value(
        _mapping(threshold_metadata.get("evidence_coverage")).get("minimum_source_artifacts"),
        2,
    )
    drawdown_proxy = _candidate_drawdown_proxy(walk)
    drawdown_floor = _float_value(
        _mapping(threshold_metadata.get("drawdown_cap")).get("minimum_drawdown_proxy_pct"),
        DEFAULT_MAX_DRAWDOWN_PCT,
    )
    checks = {
        "minimum_sample": {
            "passed": sample_size >= required_sample,
            "actual": sample_size,
            "threshold": required_sample,
        },
        "positive_frozen_cpb_delta": {
            "passed": frozen_delta is not None and frozen_delta > min_delta,
            "actual_pct": frozen_delta,
            "threshold_pct": min_delta,
        },
        "evidence_coverage": {
            "passed": bool(linked_hypothesis) and len(source_artifacts) >= min_source_artifacts,
            "linked_hypothesis": linked_hypothesis,
            "source_artifact_count": len(source_artifacts),
            "minimum_source_artifacts": min_source_artifacts,
        },
        "drawdown_cap": {
            "passed": drawdown_proxy is not None and drawdown_proxy >= drawdown_floor,
            "actual_pct": drawdown_proxy,
            "threshold_pct": drawdown_floor,
        },
        "blocker_clearance": {
            "passed": not blockers,
            "blocker_count": len(blockers),
            "blockers": blockers,
        },
    }
    blocked_reasons = _candidate_blocked_reasons(checks)
    review_status = "review_ready" if not blocked_reasons else "blocked"
    return {
        "candidate_key": str(candidate.get("candidate_key") or "unknown"),
        "candidate_family": str(candidate.get("candidate_family") or "unknown"),
        "review_status": review_status,
        "sample_size": sample_size,
        "frozen_cpb_delta_pct": frozen_delta,
        "drawdown_proxy_pct": drawdown_proxy,
        "readiness_checks": checks,
        "blocked_reasons": blocked_reasons,
        "source_artifacts": source_artifacts,
        "linked_hypothesis": linked_hypothesis or None,
        "promotion_gate": {
            "status": "blocked",
            "promotion_allowed": False,
            "paper_observation_allowed": False,
            "artifact_only": True,
            "blockers": [
                "manual_promotion_approval_required",
                "future_strategy_version_task_required",
                "paper_live_deployment_not_authorized",
            ],
        },
        "next_step": (
            "manual_strategy_version_review_task"
            if review_status == "review_ready"
            else "clear_observation_blockers"
        ),
    }


def _candidate_blocked_reasons(checks: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not _mapping(checks.get("minimum_sample")).get("passed"):
        reasons.append("minimum_sample_not_met")
    frozen_check = _mapping(checks.get("positive_frozen_cpb_delta"))
    if not frozen_check.get("passed"):
        reasons.append(
            "frozen_cpb_delta_missing"
            if frozen_check.get("actual_pct") is None
            else "frozen_cpb_delta_not_positive"
        )
    if not _mapping(checks.get("evidence_coverage")).get("passed"):
        reasons.append("evidence_coverage_missing")
    drawdown_check = _mapping(checks.get("drawdown_cap"))
    if not drawdown_check.get("passed"):
        reasons.append(
            "drawdown_proxy_missing"
            if drawdown_check.get("actual_pct") is None
            else "drawdown_cap_exceeded"
        )
    if not _mapping(checks.get("blocker_clearance")).get("passed"):
        reasons.append("candidate_blockers_not_cleared")
    return reasons


def _candidate_drawdown_proxy(walk: Mapping[str, Any]) -> float | None:
    return _first_float(walk, "max_drawdown_pct", "mae_10d_median_pct", "t1_low_mean_pct")


def _promotion_release_gate(snapshot_gate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **dict(snapshot_gate),
        "status": "blocked",
        "artifact_only": True,
        "review_ready_is_not_approval": True,
        "manual_approval_contract": "future_strategy_version_task_required",
        "manual_promotion_approval_required": True,
        "promotion_allowed": False,
        "paper_observation_allowed": False,
        "blocked_mutation_targets": [
            "active_cpb_params",
            "strategy_versions",
            "trade_plans",
            "trades",
            "positions",
            "paper_live_behavior",
            "broker_execution",
            "timer_state",
        ],
    }


def _dossier_safety(snapshot_safety: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "read_only": True,
        "artifact_only": True,
        "dossier_is_review_evidence_only": True,
        "active_params_mutated": bool(snapshot_safety.get("active_params_mutated", False)),
        "wrote_strategy_version": bool(snapshot_safety.get("wrote_strategy_version", False)),
        "wrote_strategy_versions": bool(snapshot_safety.get("wrote_strategy_versions", False)),
        "writes_trade_state": bool(snapshot_safety.get("writes_trade_state", False)),
        "writes_paper_live_behavior": bool(snapshot_safety.get("writes_paper_live_behavior", False)),
        "timer_mutated": bool(snapshot_safety.get("timer_mutated", False)),
        "promotion_allowed": False,
        "paper_observation_allowed": False,
    }


def _promotion_dossier_markdown(artifact: Mapping[str, Any]) -> str:
    summary = _mapping(artifact.get("summary"))
    lines = [
        f"# Shadow Promotion Dossier {artifact.get('as_of_date') or ''}".rstrip(),
        "",
        f"- contract: {artifact.get('dossier_contract')}",
        "- review_ready is not approval",
        f"- candidates: {summary.get('candidate_count', 0)}",
        f"- review_ready: {summary.get('review_ready_count', 0)}",
        f"- blocked: {summary.get('blocked_count', 0)}",
        "- promotion_allowed=false",
        "",
        "## Candidates",
    ]
    for candidate in _list_mapping(artifact.get("candidates")):
        reasons = ", ".join(_list_text(candidate.get("blocked_reasons"))) or "none"
        lines.append(
            f"- {candidate.get('candidate_key')}: {candidate.get('review_status')} "
            f"(blocked_reasons={reasons})"
        )
    lines.extend(
        [
            "",
            "## Release Gate",
            "- manual_promotion_approval_required",
            "- future_strategy_version_task_required",
            "- active CPB params/hash must remain unchanged",
            "- no strategy_versions, trade_plans, trades, positions, paper/live behavior, broker execution, or timer writes",
            "",
        ]
    )
    return "\n".join(lines)


def _portable_artifact_paths(value: Any, artifact_root: Path) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _portable_artifact_paths(item, artifact_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable_artifact_paths(item, artifact_root) for item in value]
    if isinstance(value, str):
        return _portable_artifact_path(value, artifact_root)
    return value


def _portable_artifact_path(value: str, artifact_root: Path) -> str:
    text = value.strip()
    if not text.startswith("/"):
        return value
    try:
        return str(Path(text).resolve().relative_to(artifact_root.resolve()))
    except (OSError, ValueError):
        pass
    marker = "/pgc/"
    if marker not in text:
        return value
    relative = text.split(marker, 1)[1].strip("/")
    return relative if relative and not relative.startswith("../") else value


def _list_mapping(value: object) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _scorecard_rows(
    snapshot: object,
    db_path: Path,
    raw_rows_by_candidate: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    snapshot_as_of = getattr(snapshot, "as_of_date", None)
    candidates = getattr(snapshot, "candidates", []) or []
    rows = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_key = str(candidate.get("candidate_key") or "")
        raw_rows = (raw_rows_by_candidate or {}).get(candidate_key, [])
        row = _candidate_scorecard_row(candidate, snapshot, db_path, snapshot_as_of, raw_rows)
        rows.append(row)

    rows.sort(key=lambda item: (-float(item.get("outcome_score") or 0), int(item.get("blocker_count") or 0), str(item["candidate_key"])))
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def _monitor_rows_by_candidate(source_artifacts: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    monitor_path = source_artifacts.get("monitor_json")
    if not monitor_path:
        return {}
    try:
        payload = json.loads(Path(str(monitor_path)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    walk = _mapping(payload.get("walk_forward_progress"))
    rows_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for raw in _list_value(walk.get("rows")):
        if not isinstance(raw, Mapping):
            continue
        candidate_key = str(raw.get("candidate_key") or raw.get("bucket") or "").strip()
        if not candidate_key:
            continue
        rows_by_candidate.setdefault(candidate_key, []).append(dict(raw))
    return rows_by_candidate


def _candidate_scorecard_row(
    candidate: Mapping[str, Any],
    snapshot: object,
    db_path: Path,
    snapshot_as_of: str | None,
    raw_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    walk = _mapping(candidate.get("walk_forward"))
    comparison = _mapping(candidate.get("comparison_vs_frozen_cpb"))
    blockers = _unique_texts(_list_text(candidate.get("blockers")))
    raw_rows = raw_rows or []
    raw_market_metrics = _raw_market_outcome_metrics(db_path, raw_rows)
    market_data_gaps = _market_data_gaps(db_path, candidate, snapshot_as_of)
    if raw_market_metrics["missing_market_bar_count"]:
        market_data_gaps = _unique_texts([*market_data_gaps, "market_bars_missing"])
    evidence_gaps = _evidence_gaps(blockers)
    coverage_gaps = _coverage_gaps(walk, comparison, market_data_gaps)
    sample_size = _sample_size(walk, comparison)
    required_sample = _int_value(walk.get("required_days"), _int_value(_mapping(getattr(snapshot, "walk_forward", {})).get("required_days"), 20))
    coverage_status = _coverage_status(walk, sample_size, required_sample, market_data_gaps)
    metrics = _metrics_payload(walk, comparison)
    metrics.update({key: value for key, value in raw_market_metrics.items() if key != "missing_market_bar_count"})
    if raw_market_metrics["t1_close_mean_pct"] is None and metrics.get("t1_close_mean_pct") is None:
        metrics["t1_close_mean_pct"] = _float_or_none(walk.get("t1_close_mean_pct"))
    blocker_count = int(candidate.get("blocker_count") or len(blockers))
    observation_status = _observation_status(candidate, coverage_status, blocker_count)
    market_data_coverage_status = _scorecard_market_data_status(raw_rows, raw_market_metrics)
    scorecard_blockers = _scorecard_blockers(blockers, coverage_status, market_data_coverage_status, comparison)
    blocker_count = len(scorecard_blockers)
    outcome_score = _outcome_score(metrics, blocker_count, coverage_status, len(market_data_gaps))
    source_artifacts = _unique_texts(
        [
            *_list_text(candidate.get("source_artifacts")),
            *_list_text(list(_mapping(getattr(snapshot, "source_artifacts", {})).values())),
        ]
    )

    return {
        "rank": 0,
        "candidate_key": str(candidate.get("candidate_key") or "unknown"),
        "candidate_family": str(candidate.get("candidate_family") or "unknown"),
        "observation_status": observation_status,
        "promotion_readiness": "blocked" if scorecard_blockers else "review_ready",
        "outcome_score": outcome_score,
        "sample_size": sample_size,
        "required_sample": required_sample,
        "required_sample_size": required_sample,
        "sample_coverage_status": coverage_status,
        "coverage_status": coverage_status,
        "market_data_coverage_status": market_data_coverage_status,
        "blocker_count": blocker_count,
        "blockers": scorecard_blockers,
        "frozen_cpb_delta_pct": _float_or_none(comparison.get("t1_close_mean_delta_pct")),
        "missing_market_bar_count": int(raw_market_metrics["missing_market_bar_count"]),
        "coverage_gaps": coverage_gaps,
        "evidence_gaps": evidence_gaps,
        "market_data_gaps": market_data_gaps,
        "observed_days": {
            "start_signal_date": walk.get("start_signal_date"),
            "latest_signal_date": walk.get("latest_signal_date"),
            "latest_outcome_date": _mapping(getattr(snapshot, "walk_forward", {})).get("latest_outcome_date"),
        },
        "best_outcome": _best_outcome(metrics),
        "worst_outcome": _worst_outcome(metrics),
        "ranking_rationale": _ranking_rationale(metrics, coverage_status, blocker_count),
        "promotion_blocked_reason": _promotion_blocked_reason(blockers, coverage_gaps),
        "source_artifacts": source_artifacts,
        "source_artifact_paths": source_artifacts,
        "metrics": metrics,
        "outcome_metrics": metrics,
        "t1_close_mean_pct": metrics.get("t1_close_mean_pct"),
        "t2_close_mean_pct": metrics.get("t2_close_mean_pct"),
        "t5_close_mean_pct": metrics.get("t5_close_mean_pct"),
        "drawdown_proxy_pct": metrics.get("drawdown_proxy_pct"),
        "hit_rate_pct": metrics.get("t1_close_win_rate_pct"),
        "today_top": _mapping(candidate.get("today_top")),
        "promotion_allowed": False,
        "artifact_only": True,
        "read_only_note": "Observation queue is not paper trading and cannot promote, trade, plan, or mutate timers.",
    }


def _metrics_payload(walk: Mapping[str, Any], comparison: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "t1_close_mean_pct": _float_or_none(walk.get("t1_close_mean_pct")),
        "t1_close_median_pct": _float_or_none(walk.get("t1_close_median_pct")),
        "t1_close_win_rate_pct": _float_or_none(walk.get("t1_close_win_rate_pct")),
        "t1_high_mean_pct": _float_or_none(walk.get("t1_high_mean_pct")),
        "t1_high_ge3_rate_pct": _float_or_none(walk.get("t1_high_ge3_rate_pct")),
        "t5_close_mean_pct": _first_float(walk, "t5_close_mean_pct", "next_open_ret_5d_mean_pct", "ret_5d_mean_pct"),
        "drawdown_proxy_pct": _first_float(walk, "mae_10d_median_pct", "t1_low_mean_pct"),
        "frozen_cpb_t1_close_mean_delta_pct": _float_or_none(comparison.get("t1_close_mean_delta_pct")),
        "frozen_cpb_t1_win_rate_delta_pct": _float_or_none(comparison.get("t1_close_win_rate_delta_pct")),
        "frozen_cpb_t5_close_mean_delta_pct": _float_or_none(comparison.get("t5_close_mean_delta_pct")),
        "sample_warning": comparison.get("sample_warning"),
    }


def _raw_market_outcome_metrics(db_path: Path, raw_rows: list[dict[str, Any]]) -> dict[str, Any]:
    t1_close = [_float_or_none(row.get("t1_close_ret_pct")) for row in raw_rows]
    t1_close_values = [value for value in t1_close if value is not None]
    t1_high = [_float_or_none(row.get("t1_high_ret_pct")) for row in raw_rows]
    t1_high_values = [value for value in t1_high if value is not None]
    t1_low = [_float_or_none(row.get("t1_low_ret_pct")) for row in raw_rows]
    drawdowns = [value for value in t1_low if value is not None]
    t2_close: list[float] = []
    t5_close: list[float] = []
    missing_market_bar_count = 0

    if not raw_rows:
        return {
            "t1_sample_size": 0,
            "t2_sample_size": 0,
            "t5_sample_size": 0,
            "t1_close_mean_pct": None,
            "t1_close_win_rate_pct": None,
            "t1_high_mean_pct": None,
            "t2_close_mean_pct": None,
            "t2_close_hit_rate_pct": None,
            "t5_close_mean_pct": None,
            "t5_close_hit_rate_pct": None,
            "drawdown_proxy_pct": None,
            "missing_market_bar_count": 0,
        }

    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                if not _table_exists(conn, "market_bars"):
                    missing_market_bar_count = len(raw_rows)
                else:
                    for row in raw_rows:
                        outcome = _market_bar_outcome(conn, row)
                        if outcome["missing"]:
                            missing_market_bar_count += 1
                            continue
                        if outcome["t2_close_pct"] is not None:
                            t2_close.append(float(outcome["t2_close_pct"]))
                        if outcome["t5_close_pct"] is not None:
                            t5_close.append(float(outcome["t5_close_pct"]))
                        if outcome["drawdown_proxy_pct"] is not None:
                            drawdowns.append(float(outcome["drawdown_proxy_pct"]))
        except sqlite3.Error:
            missing_market_bar_count = len(raw_rows)
    else:
        missing_market_bar_count = len(raw_rows)

    return {
        "t1_sample_size": len(t1_close_values),
        "t2_sample_size": len(t2_close),
        "t5_sample_size": len(t5_close),
        "t1_close_mean_pct": _mean(t1_close_values),
        "t1_close_win_rate_pct": _hit_rate(t1_close_values),
        "t1_high_mean_pct": _mean(t1_high_values),
        "t2_close_mean_pct": _mean(t2_close),
        "t2_close_hit_rate_pct": _hit_rate(t2_close),
        "t5_close_mean_pct": _mean(t5_close),
        "t5_close_hit_rate_pct": _hit_rate(t5_close),
        "drawdown_proxy_pct": min(drawdowns) if drawdowns else None,
        "missing_market_bar_count": missing_market_bar_count,
    }


def _market_bar_outcome(conn: sqlite3.Connection, row: Mapping[str, Any]) -> dict[str, Any]:
    ts_code = str(row.get("ts_code") or "").strip()
    planned_buy_date = str(row.get("planned_buy_date") or row.get("outcome_date") or "").strip()
    if not ts_code or not planned_buy_date:
        return _missing_market_outcome()
    bars = list(
        conn.execute(
            """
            SELECT trade_date, open, high, low, close
            FROM market_bars
            WHERE ts_code = ? AND trade_date >= ?
            ORDER BY trade_date
            LIMIT 5
            """,
            (ts_code, planned_buy_date),
        )
    )
    if not bars:
        return _missing_market_outcome()
    entry_price = _float_or_none(row.get("outcome_open")) or _float_or_none(bars[0]["open"]) or _float_or_none(bars[0]["close"])
    if entry_price is None or entry_price <= 0:
        return _missing_market_outcome()
    lows = [_float_or_none(bar["low"]) for bar in bars]
    drawdown = min((_pct_change(low, entry_price) for low in lows if low is not None), default=None)
    return {
        "missing": len(bars) < 5,
        "t2_close_pct": _bar_close_pct(bars, 1, entry_price),
        "t5_close_pct": _bar_close_pct(bars, 4, entry_price),
        "drawdown_proxy_pct": drawdown,
    }


def _missing_market_outcome() -> dict[str, Any]:
    return {"missing": True, "t2_close_pct": None, "t5_close_pct": None, "drawdown_proxy_pct": None}


def _bar_close_pct(bars: list[sqlite3.Row], index: int, entry_price: float) -> float | None:
    if len(bars) <= index:
        return None
    close = _float_or_none(bars[index]["close"])
    if close is None:
        return None
    return _pct_change(close, entry_price)


def _scorecard_market_data_status(raw_rows: list[dict[str, Any]], metrics: Mapping[str, Any]) -> str:
    if not raw_rows:
        return "summary_only"
    missing = _int_value(metrics.get("missing_market_bar_count"), 0)
    if missing >= len(raw_rows):
        return "missing"
    if missing or _int_value(metrics.get("t5_sample_size"), 0) < len(raw_rows):
        return "partial"
    return "complete"


def _scorecard_blockers(
    existing_blockers: list[str],
    coverage_status: str,
    market_data_status: str,
    comparison: Mapping[str, Any],
) -> list[str]:
    blockers = list(existing_blockers)
    if coverage_status == "missing":
        blockers.append("observation_sample_missing")
    elif coverage_status == "insufficient_sample":
        blockers.append("insufficient_sample")
    if market_data_status == "missing":
        blockers.append("market_bars_missing")
    elif market_data_status == "partial":
        blockers.append("market_bars_partial")
    if comparison.get("sample_warning"):
        blockers.append("frozen_cpb_baseline_insufficient_sample")
    return _unique_texts(blockers)


def _outcome_score(
    metrics: Mapping[str, Any],
    blocker_count: int,
    coverage_status: str,
    market_gap_count: int,
) -> float:
    t1_mean = _float_value(metrics.get("t1_close_mean_pct"))
    t1_win = _float_value(metrics.get("t1_close_win_rate_pct"), 50.0)
    t1_high = _float_value(metrics.get("t1_high_mean_pct"))
    frozen_delta = _float_value(metrics.get("frozen_cpb_t1_close_mean_delta_pct"))
    score = 50.0 + (t1_mean * 4.0) + ((t1_win - 50.0) * 0.25) + (t1_high * 1.25) + (frozen_delta * 1.5)
    score -= min(blocker_count, 12) * 1.5
    score -= market_gap_count * 5.0
    if coverage_status == "missing":
        score = min(score, 25.0)
    elif coverage_status in {"insufficient_sample", "artifact_summary_only"}:
        score = min(score, 60.0)
    return round(max(0.0, min(100.0, score)), 1)


def _scorecard_status(rows: list[dict[str, Any]], snapshot_status: str) -> str:
    if not rows:
        return "missing"
    if snapshot_status == "blocked" or any(row.get("observation_status") == "blocked" for row in rows):
        return "blocked"
    if any(row.get("market_data_gaps") for row in rows):
        return "blocked"
    if any(row.get("sample_coverage_status") in {"missing", "insufficient_sample"} for row in rows):
        return "insufficient_sample"
    return "observing"


def _scorecard_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "candidate_count": len(rows),
        "blocked_candidate_count": sum(1 for row in rows if row.get("observation_status") == "blocked"),
        "insufficient_sample_count": sum(
            1 for row in rows if row.get("sample_coverage_status") in {"missing", "insufficient_sample"}
        ),
        "observed_candidate_count": sum(1 for row in rows if row.get("coverage_status") == "complete"),
        "insufficient_sample_candidate_count": sum(1 for row in rows if row.get("coverage_status") == "insufficient_sample"),
        "missing_candidate_count": sum(1 for row in rows if row.get("coverage_status") == "missing"),
        "market_data_gap_count": sum(1 for row in rows if row.get("market_data_gaps")),
        "evidence_gap_count": sum(1 for row in rows if row.get("evidence_gaps")),
        "distinct_blocker_count": len({blocker for row in rows for blocker in _list_text(row.get("blockers"))}),
    }


def _scorecard_summary(rows: list[dict[str, Any]], status: str) -> dict[str, Any]:
    top = rows[0] if rows else {}
    return {
        "status": status,
        "top_candidate_key": top.get("candidate_key"),
        "top_outcome_score": top.get("outcome_score"),
        "top_sample_coverage_status": top.get("sample_coverage_status"),
        "operator_note": "Observation queue is read-only research; it is not paper trading and does not approve promotion.",
    }


def _coverage_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    state_counts: dict[str, int] = {}
    market_counts: dict[str, int] = {}
    for row in rows:
        state = str(row.get("coverage_status") or row.get("sample_coverage_status") or "unknown")
        market_state = str(row.get("market_data_coverage_status") or "unknown")
        state_counts[state] = state_counts.get(state, 0) + 1
        market_counts[market_state] = market_counts.get(market_state, 0) + 1
    return {
        "status": "missing" if not rows else ("complete" if set(state_counts) == {"complete"} else "partial"),
        "state_counts": state_counts,
        "market_data_state_counts": market_counts,
        "missing_market_bar_count": sum(_int_value(row.get("missing_market_bar_count"), 0) for row in rows),
    }


def _snapshot_missing_blockers(errors: list[ServiceError]) -> list[str]:
    blockers = []
    for error in errors:
        if error.code == "SHADOW_MONITOR_ARTIFACT_NOT_FOUND":
            blockers.append("shadow_monitor_artifact_missing")
        elif error.code == "SHADOW_PREFLIGHT_ARTIFACT_NOT_FOUND":
            blockers.append("shadow_preflight_artifact_missing")
    return blockers or ["shadow_observation_source_missing"]


def _observation_safety(snapshot_safety: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "read_only": True,
        "artifact_only": True,
        "observation_is_not_paper_trading": True,
        "active_params_mutated": bool(snapshot_safety.get("active_params_mutated", False)),
        "wrote_strategy_version": bool(snapshot_safety.get("wrote_strategy_version", False)),
        "writes_trade_state": bool(snapshot_safety.get("writes_trade_state", False)),
        "writes_paper_live_behavior": bool(snapshot_safety.get("writes_paper_live_behavior", False)),
        "timer_mutated": bool(snapshot_safety.get("timer_mutated", False)),
        "promotion_allowed": False,
        "trade_plan_allowed": False,
    }


def _sample_size(walk: Mapping[str, Any], comparison: Mapping[str, Any]) -> int:
    return _int_value(
        walk.get("days"),
        _int_value(
            walk.get("n"),
            _int_value(walk.get("observed_trades"), _int_value(comparison.get("candidate_days"), 0)),
        ),
    )


def _coverage_status(
    walk: Mapping[str, Any],
    sample_size: int,
    required_sample: int,
    market_data_gaps: list[str],
) -> str:
    status = str(walk.get("status") or "unknown")
    if market_data_gaps:
        return "missing"
    if status == "artifact_summary_only":
        return "artifact_summary_only"
    if sample_size <= 0:
        return "missing"
    if required_sample and sample_size < required_sample:
        return "insufficient_sample"
    return "complete" if status in {"complete", "unknown"} else status


def _observation_status(candidate: Mapping[str, Any], coverage_status: str, blocker_count: int) -> str:
    if coverage_status in {"missing", "insufficient_sample"}:
        return coverage_status
    if blocker_count or str(candidate.get("status") or "") == "blocked":
        return "blocked"
    return "observing"


def _coverage_gaps(
    walk: Mapping[str, Any],
    comparison: Mapping[str, Any],
    market_data_gaps: list[str],
) -> list[str]:
    gaps = []
    status = str(walk.get("status") or "unknown")
    if status not in {"complete", "unknown"}:
        gaps.append(f"walk_forward_{status}")
    sample_warning = comparison.get("sample_warning")
    if sample_warning:
        gaps.append(str(sample_warning))
    gaps.extend(market_data_gaps)
    return _unique_texts(gaps)


def _evidence_gaps(blockers: list[str]) -> list[str]:
    markers = ("evidence", "backtest", "replay", "proposal_review", "sector")
    return [blocker for blocker in blockers if any(marker in blocker for marker in markers)]


def _market_data_gaps(db_path: Path, candidate: Mapping[str, Any], snapshot_as_of: str | None) -> list[str]:
    top = _mapping(candidate.get("today_top"))
    ts_code = str(top.get("ts_code") or "")
    review_date = str(top.get("review_date") or snapshot_as_of or "")
    if not ts_code or not review_date:
        return []
    if not db_path.exists():
        return [f"market_bars_missing_db:{ts_code}:{review_date}"]
    try:
        with sqlite3.connect(db_path) as conn:
            if not _table_exists(conn, "market_bars"):
                return [f"market_bars_table_missing:{ts_code}:{review_date}"]
            row = conn.execute(
                """
                SELECT 1
                FROM market_bars
                WHERE ts_code = ? AND trade_date = ?
                LIMIT 1
                """,
                (ts_code, review_date),
            ).fetchone()
    except sqlite3.Error as exc:
        return [f"market_bars_query_failed:{exc}"]
    return [] if row else [f"market_bars_missing:{ts_code}:{review_date}"]


def _best_outcome(metrics: Mapping[str, Any]) -> dict[str, Any]:
    candidates = [
        ("T+1 high mean", metrics.get("t1_high_mean_pct")),
        ("T+5 close mean", metrics.get("t5_close_mean_pct")),
        ("T+1 close mean", metrics.get("t1_close_mean_pct")),
    ]
    label, value = max(candidates, key=lambda item: _float_value(item[1], -999.0))
    return {"label": label, "value_pct": value}


def _worst_outcome(metrics: Mapping[str, Any]) -> dict[str, Any]:
    candidates = [
        ("drawdown proxy", metrics.get("drawdown_proxy_pct")),
        ("frozen CPB T+1 delta", metrics.get("frozen_cpb_t1_close_mean_delta_pct")),
        ("T+1 close mean", metrics.get("t1_close_mean_pct")),
    ]
    label, value = min(candidates, key=lambda item: _float_value(item[1], 999.0))
    return {"label": label, "value_pct": value}


def _ranking_rationale(metrics: Mapping[str, Any], coverage_status: str, blocker_count: int) -> str:
    return (
        f"T+1 mean={_display_pct(metrics.get('t1_close_mean_pct'))}, "
        f"win={_display_pct(metrics.get('t1_close_win_rate_pct'))}, "
        f"frozen_delta={_display_pct(metrics.get('frozen_cpb_t1_close_mean_delta_pct'))}, "
        f"coverage={coverage_status}, blockers={blocker_count}."
    )


def _promotion_blocked_reason(blockers: list[str], coverage_gaps: list[str]) -> str:
    reasons = _unique_texts([*blockers, *coverage_gaps])
    if not reasons:
        reasons = ["manual_promotion_review_required"]
    return "; ".join(reasons[:8])


def _first_float(payload: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _float_or_none(payload.get(key))
        if value is not None:
            return value
    return None


def _float_value(value: object, default: float = 0.0) -> float:
    parsed = _float_or_none(value)
    return default if parsed is None else parsed


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _hit_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return round(100.0 * sum(1 for value in values if value > 0) / len(values), 2)


def _pct_change(value: float, basis: float) -> float:
    return round((float(value) - basis) / basis * 100.0, 2)


def _int_value(value: object, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _display_pct(value: object) -> str:
    parsed = _float_or_none(value)
    return "-" if parsed is None else f"{parsed:.2f}%"


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_text(value: object) -> list[str]:
    if isinstance(value, Mapping):
        return [str(item) for item in value.values() if item not in (None, "")]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    if value in (None, ""):
        return []
    return [str(value)]


def _list_value(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _unique_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None
