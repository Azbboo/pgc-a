"""Read-only shadow observation scorecard service."""

from __future__ import annotations

import json
import hashlib
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
from pgc_trading.services.strategy_evolution_service import (
    review_shadow_promotion_dossier_artifact,
    review_shadow_promotion_review_request_artifact,
)


SHADOW_OBSERVATION_SCORECARD_CONTRACT = "shadow_observation_scorecard_v1"
SHADOW_OBSERVATION_HISTORY_CONTRACT = "shadow_observation_history_v1"
SHADOW_PROMOTION_DOSSIER_CONTRACT = "shadow_promotion_dossier_v1"
SHADOW_PROMOTION_REVIEW_REQUEST_CONTRACT = "shadow_promotion_review_request_v1"
SHADOW_REPLAY_BACKTEST_EVIDENCE_CONTRACT = "shadow_replay_backtest_evidence_v1"
SHADOW_DECISION_MEMO_CONTRACT = "shadow_decision_memo_v1"
SHADOW_DECISION_QUEUE_CONTRACT = "shadow_strategy_decision_queue_v1"
SHADOW_WALK_FORWARD_OUTCOMES_CONTRACT = "shadow_walk_forward_outcomes_v1"
SHADOW_WALK_FORWARD_OUTCOMES_PROVIDER = "pgc_shadow_walk_forward_outcome_accumulator_v1"
SHADOW_REPLAY_BACKTEST_EVIDENCE_PATTERN = "shadow_replay_backtest_evidence*.json"
SHADOW_REPLAY_BACKTEST_EVIDENCE_PROVIDER = "pgc_shadow_replay_backtest_evidence_producer_v1"
SHADOW_THRESHOLD_CALIBRATION_PATTERN = "shadow_threshold_calibration_*.json"
SHADOW_STRATEGY_EXPERIMENT_REGISTRY_PATTERN = "shadow_strategy_experiment_registry_*.json"
SHADOW_SCORECARD_ARTIFACT_PATTERN = "shadow_observation_scorecard_*.json"
SHADOW_WALK_FORWARD_OUTCOMES_PATTERN = "shadow_walk_forward_outcomes_*.json"
DEFAULT_REQUIRED_SAMPLE_SIZE = 20
DEFAULT_MIN_FROZEN_CPB_DELTA_PCT = 0.0
DEFAULT_MAX_DRAWDOWN_PCT = -8.0
DEFAULT_HISTORY_WINDOW = 20
SCORECARD_ARTIFACT_PATTERN = "shadow_observation_scorecard_*.json"
DOSSIER_ARTIFACT_PATTERN = "shadow_promotion_dossier_*.json"
REVIEW_REQUEST_ARTIFACT_PATTERN = "shadow_promotion_review_request_*.json"
REPLAY_BACKTEST_REQUIRED_BLOCKER = "replay_backtest_result_artifact_required"
REPLAY_BACKTEST_BLOCKERS = {REPLAY_BACKTEST_REQUIRED_BLOCKER}
REQUIRED_REPLAY_BACKTEST_METRICS = (
    "t1_close_mean_pct",
    "t1_close_win_rate_pct",
    "t5_close_mean_pct",
    "max_drawdown_pct",
)
FORBIDDEN_REPLAY_EVIDENCE_FLAGS = (
    "active_params_mutated",
    "wrote_strategy_version",
    "wrote_strategy_versions",
    "writes_trade_state",
    "writes_paper_live_behavior",
    "paper_live_deployment_changed",
    "timer_mutated",
    "promotion_allowed",
    "paper_observation_allowed",
)


@dataclass(frozen=True)
class GetShadowObservationScorecardRequest:
    as_of_date: str | None = None


@dataclass(frozen=True)
class ListShadowObservationHistoryRequest:
    as_of_date: str | None = None
    window: int = DEFAULT_HISTORY_WINDOW


@dataclass(frozen=True)
class BuildShadowPromotionDossierRequest:
    as_of_date: str | None = None
    output_path: str | None = None


@dataclass(frozen=True)
class BuildShadowPromotionReviewRequest:
    as_of_date: str | None = None
    output_path: str | None = None


@dataclass(frozen=True)
class BuildShadowReplayBacktestEvidenceRequest:
    as_of_date: str | None = None
    output_dir: str | None = None
    candidate_keys: tuple[str, ...] = ()
    required_sample_size: int = DEFAULT_REQUIRED_SAMPLE_SIZE


@dataclass(frozen=True)
class BuildShadowWalkForwardOutcomesRequest:
    as_of_date: str | None = None
    output_path: str | None = None
    horizon_days: int = 5


@dataclass(frozen=True)
class GetShadowPromotionReviewRequest:
    as_of_date: str | None = None


@dataclass(frozen=True)
class GetShadowDecisionMemoRequest:
    as_of_date: str | None = None


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
class ShadowObservationHistoryResult:
    history_contract: str = SHADOW_OBSERVATION_HISTORY_CONTRACT
    generated_at: str = ""
    db_path: str = ""
    reports_dir: str = ""
    as_of_date: str | None = None
    window: int = DEFAULT_HISTORY_WINDOW
    status: str = "unknown"
    read_only: bool = True
    artifact_only: bool = True
    research_only: bool = True
    source_artifacts: dict[str, dict[str, str | None]] = field(default_factory=dict)
    dates: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)


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


@dataclass(frozen=True)
class ShadowPromotionReviewRequestResult:
    review_request_contract: str = SHADOW_PROMOTION_REVIEW_REQUEST_CONTRACT
    generated_at: str = ""
    db_path: str = ""
    reports_dir: str = ""
    as_of_date: str | None = None
    source_dossier_path: str | None = None
    source_dossier_contract: str | None = None
    source_dossier_valid: bool = False
    source_dossier_status: str = "unknown"
    would_write_artifact: bool = True
    wrote_artifact: bool = False
    artifact_path: str | None = None
    markdown_path: str | None = None
    artifact: dict[str, Any] = field(default_factory=dict)
    active_params_mutated: bool = False
    wrote_strategy_version: bool = False
    wrote_strategy_versions: bool = False
    writes_trade_state: bool = False
    writes_paper_live_behavior: bool = False
    timer_mutated: bool = False


@dataclass(frozen=True)
class ShadowPromotionReviewWorkbenchResult:
    review_request_contract: str = SHADOW_PROMOTION_REVIEW_REQUEST_CONTRACT
    generated_at: str = ""
    db_path: str = ""
    reports_dir: str = ""
    as_of_date: str | None = None
    status: str = "missing"
    read_only: bool = True
    artifact_only: bool = True
    artifact_path: str | None = None
    markdown_path: str | None = None
    artifact_exists: bool = False
    artifact_valid: bool = False
    artifact_error: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    review_request: dict[str, Any] = field(default_factory=dict)
    candidate_readiness: list[dict[str, Any]] = field(default_factory=list)
    replay_backtest_evidence: dict[str, Any] = field(default_factory=dict)
    source_dossier_review: dict[str, Any] = field(default_factory=dict)
    source_artifacts: dict[str, str | None] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)
    artifact: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ShadowDecisionMemoResult:
    memo_contract: str = SHADOW_DECISION_MEMO_CONTRACT
    generated_at: str = ""
    db_path: str = ""
    reports_dir: str = ""
    as_of_date: str | None = None
    status: str = "blocked"
    language: str = "zh-CN"
    read_only: bool = True
    artifact_only: bool = True
    summary: dict[str, Any] = field(default_factory=dict)
    sections: dict[str, Any] = field(default_factory=dict)
    decision_queue: dict[str, Any] = field(default_factory=dict)
    candidate_memos: list[dict[str, Any]] = field(default_factory=list)
    promotion_review: dict[str, Any] = field(default_factory=dict)
    scorecard: dict[str, Any] = field(default_factory=dict)
    walk_forward: dict[str, Any] = field(default_factory=dict)
    walk_forward_outcomes: dict[str, Any] = field(default_factory=dict)
    replay_backtest_evidence: dict[str, Any] = field(default_factory=dict)
    calibration: dict[str, Any] = field(default_factory=dict)
    experiment_registry: dict[str, Any] = field(default_factory=dict)
    source_artifacts: dict[str, str | None] = field(default_factory=dict)
    source_status: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ShadowReplayBacktestEvidenceGenerationResult:
    evidence_contract: str = SHADOW_REPLAY_BACKTEST_EVIDENCE_CONTRACT
    generated_at: str = ""
    db_path: str = ""
    reports_dir: str = ""
    output_dir: str = ""
    as_of_date: str | None = None
    provider: str = SHADOW_REPLAY_BACKTEST_EVIDENCE_PROVIDER
    source_monitor_path: str | None = None
    candidate_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    missing_count: int = 0
    wrote_artifacts: bool = False
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)
    active_params_mutated: bool = False
    wrote_strategy_version: bool = False
    wrote_strategy_versions: bool = False
    writes_trade_state: bool = False
    writes_paper_live_behavior: bool = False
    timer_mutated: bool = False


@dataclass(frozen=True)
class ShadowWalkForwardOutcomesResult:
    outcomes_contract: str = SHADOW_WALK_FORWARD_OUTCOMES_CONTRACT
    generated_at: str = ""
    db_path: str = ""
    reports_dir: str = ""
    as_of_date: str | None = None
    provider: str = SHADOW_WALK_FORWARD_OUTCOMES_PROVIDER
    source_monitor_path: str | None = None
    would_write_artifact: bool = True
    wrote_artifact: bool = False
    artifact_path: str | None = None
    markdown_path: str | None = None
    status: str = "unknown"
    candidate_count: int = 0
    signal_count: int = 0
    complete_count: int = 0
    partial_horizon_count: int = 0
    missing_market_bar_count: int = 0
    summary: dict[str, Any] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    no_future_boundary: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)
    artifact: dict[str, Any] = field(default_factory=dict)
    active_params_mutated: bool = False
    wrote_strategy_version: bool = False
    wrote_strategy_versions: bool = False
    writes_trade_state: bool = False
    writes_paper_live_behavior: bool = False
    timer_mutated: bool = False


@dataclass(frozen=True)
class ShadowReplayBacktestEvidenceReview:
    path: str | None = None
    exists: bool = False
    valid: bool = False
    status: str = "missing"
    artifact_type: str | None = None
    evidence_contract: str | None = None
    provider: str | None = None
    candidate_key: str | None = None
    as_of_date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    sample_size: int = 0
    required_sample_size: int = DEFAULT_REQUIRED_SAMPLE_SIZE
    source_hash: str | None = None
    expected_source_hash: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    no_future_boundary: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    error: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "valid": self.valid,
            "artifact_type": self.artifact_type,
            "evidence_contract": self.evidence_contract,
            "artifact_path": self.path,
            "provider": self.provider,
            "candidate_key": self.candidate_key,
            "as_of_date": self.as_of_date,
            "date_range": {
                "start_date": self.start_date,
                "end_date": self.end_date,
            },
            "sample_size": self.sample_size,
            "required_sample_size": self.required_sample_size,
            "source_hash": self.source_hash,
            "expected_source_hash": self.expected_source_hash,
            "metrics": self.metrics,
            "no_future_boundary": self.no_future_boundary,
            "safety": self.safety,
            "blockers": self.blockers,
            "error": self.error,
            "advisory_only": True,
            "promotion_allowed": False,
            "paper_observation_allowed": False,
        }


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
        replay_evidence_index = load_shadow_replay_backtest_evidence_index(
            self.reports_dir,
            as_of_date=getattr(snapshot, "as_of_date", None),
            candidate_required_samples=_candidate_required_samples(
                getattr(snapshot, "candidates", []) or [],
                _int_value(_mapping(getattr(snapshot, "walk_forward", {})).get("required_days"), DEFAULT_REQUIRED_SAMPLE_SIZE),
            ),
        )
        rows = _portable_artifact_paths(
            _scorecard_rows(
                snapshot,
                self.db_path,
                raw_rows_by_candidate,
                replay_evidence_by_candidate=replay_evidence_index["by_candidate"],
            ),
            artifact_root,
        )
        status = _scorecard_status(rows, getattr(snapshot, "status", "unknown"))
        counts = _scorecard_counts(rows)
        counts.update(_replay_evidence_counts_from_rows(rows))
        coverage = _coverage_payload(rows)
        coverage["replay_backtest_evidence"] = _portable_artifact_paths(
            replay_evidence_index["summary"],
            artifact_root,
        )
        summary = _scorecard_summary(rows, status)
        summary["replay_backtest_evidence"] = coverage["replay_backtest_evidence"]
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

    def list_history(
        self,
        request: ListShadowObservationHistoryRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ShadowObservationHistoryResult]:
        """Build a read-only cross-date history from scorecard and promotion dossier artifacts."""

        as_of_date = _compact_history_date(request.as_of_date)
        if request.as_of_date is not None and as_of_date is None:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=ShadowObservationHistoryResult(
                    generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    db_path=str(self.db_path),
                    reports_dir=str(self.reports_dir),
                    as_of_date=request.as_of_date,
                    window=request.window,
                    status="missing",
                    summary={
                        "status": "missing",
                        "operator_note": "Shadow observation history date must be YYYYMMDD or YYYY-MM-DD.",
                    },
                    safety=_observation_history_safety(),
                ),
                errors=[ServiceError("INVALID_AS_OF_DATE", "as_of_date must be YYYYMMDD or YYYY-MM-DD.")],
            )
        window = _bounded_history_window(request.window)
        history_dates = _history_dates(self.reports_dir, as_of_date, window)
        if as_of_date is not None and as_of_date not in history_dates:
            history_dates.append(as_of_date)
        date_summaries: list[dict[str, Any]] = []
        rows: list[dict[str, Any]] = []
        source_artifacts: dict[str, dict[str, str | None]] = {}
        artifact_root = self.reports_dir.parent
        for history_date in sorted(history_dates):
            scorecard_path = self.reports_dir / f"shadow_observation_scorecard_{history_date}.json"
            dossier_path = self.reports_dir / f"shadow_promotion_dossier_{history_date}.json"
            source_artifacts[history_date] = {
                "scorecard_json": _portable_optional_path(scorecard_path if scorecard_path.exists() else None, artifact_root),
                "dossier_json": _portable_optional_path(dossier_path if dossier_path.exists() else None, artifact_root),
            }
            scorecard, scorecard_blocker = _read_history_artifact(
                scorecard_path,
                missing_blocker="shadow_observation_scorecard_missing",
                invalid_blocker="shadow_observation_scorecard_invalid",
            )
            dossier, dossier_blocker = _read_history_artifact(
                dossier_path,
                missing_blocker="shadow_promotion_dossier_missing",
                invalid_blocker="shadow_promotion_dossier_invalid",
            )
            artifact_blockers = [blocker for blocker in [scorecard_blocker, dossier_blocker] if blocker]
            date_summaries.append(_history_date_summary(history_date, scorecard, dossier, artifact_blockers))
            if scorecard is None and dossier is None:
                continue
            rows.extend(_history_rows_for_date(history_date, scorecard, dossier, artifact_blockers))

        rows.sort(
            key=lambda item: (
                str(item.get("date") or ""),
                int(item.get("rank") or 9999),
                str(item.get("candidate_key") or ""),
            )
        )
        candidates = _candidate_histories(rows)
        result_as_of_date = as_of_date or (history_dates[0] if history_dates else None)
        status = _history_status(rows, date_summaries)
        result = ShadowObservationHistoryResult(
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            db_path=str(self.db_path),
            reports_dir=str(self.reports_dir),
            as_of_date=result_as_of_date,
            window=window,
            status=status,
            source_artifacts=source_artifacts,
            dates=sorted(date_summaries, key=lambda item: str(item.get("date") or ""), reverse=True),
            rows=rows,
            candidates=candidates,
            counts=_history_counts(rows, date_summaries, candidates),
            summary=_history_summary(rows, candidates, status),
            safety=_observation_history_safety(),
        )
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=result,
            lineage={
                "as_of_date": result.as_of_date,
                "window": str(window),
                "history_contract": SHADOW_OBSERVATION_HISTORY_CONTRACT,
                "candidate_count": result.counts.get("candidate_count", 0),
                "read_only": "true",
                "artifact_only": "true",
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
        replay_evidence_index = load_shadow_replay_backtest_evidence_index(
            self.reports_dir,
            as_of_date=getattr(snapshot, "as_of_date", None),
            candidate_required_samples=_candidate_required_samples(
                getattr(snapshot, "candidates", []) or [],
                _int_value(_mapping(getattr(snapshot, "walk_forward", {})).get("required_days"), DEFAULT_REQUIRED_SAMPLE_SIZE),
            ),
        )
        artifact = _portable_artifact_paths(
            _promotion_dossier_artifact(
                snapshot,
                replay_evidence_by_candidate=replay_evidence_index["by_candidate"],
            ),
            self.reports_dir.parent,
        )
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

    def build_promotion_review_request(
        self,
        request: BuildShadowPromotionReviewRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ShadowPromotionReviewRequestResult]:
        """Write a manual review package from the latest shadow promotion dossier."""

        dossier_path = _latest_shadow_promotion_dossier_path(self.reports_dir, request.as_of_date)
        source_root = self.reports_dir.parent
        source_dossier_error: str | None = None
        if dossier_path is None:
            as_of_date = request.as_of_date or datetime.now(timezone.utc).strftime("%Y%m%d")
            source_dossier_artifact = _shadow_promotion_dossier_placeholder(as_of_date, "missing", None)
            source_dossier_review = review_shadow_promotion_dossier_artifact(
                self.reports_dir / f"shadow_promotion_dossier_{as_of_date}.json"
            )
            source_dossier_error = "shadow promotion dossier artifact was not found."
            source_dossier_status = "missing"
        else:
            as_of_date = request.as_of_date or _artifact_date_from_name(dossier_path.name) or datetime.now(timezone.utc).strftime("%Y%m%d")
            source_dossier_review = review_shadow_promotion_dossier_artifact(dossier_path)
            try:
                raw_source_dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raw_source_dossier = None
                source_dossier_error = f"shadow promotion dossier artifact is not valid JSON: {exc}"
            if isinstance(raw_source_dossier, Mapping):
                source_dossier_artifact = _portable_artifact_paths(dict(raw_source_dossier), source_root)
                as_of_date = str(source_dossier_artifact.get("as_of_date") or as_of_date)
            else:
                source_dossier_artifact = _shadow_promotion_dossier_placeholder(as_of_date, "invalid", dossier_path)
                if source_dossier_error is None:
                    source_dossier_error = "shadow promotion dossier artifact must be a JSON object."
            source_dossier_status = "valid" if getattr(source_dossier_review, "valid", False) else "invalid"

        if source_dossier_error is not None:
            source_dossier_artifact["error"] = source_dossier_error
        review_request_artifact = _promotion_review_request_artifact(
            source_dossier=source_dossier_artifact,
            source_dossier_path=str(_portable_artifact_path(str(dossier_path), source_root)) if dossier_path else None,
            source_dossier_review=source_dossier_review,
            source_dossier_status=source_dossier_status,
            source_dossier_error=source_dossier_error,
            as_of_date=as_of_date,
            reports_dir=self.reports_dir,
        )
        artifact_path = (
            Path(request.output_path).expanduser()
            if request.output_path
            else self.reports_dir / f"shadow_promotion_review_request_{as_of_date}.json"
        )
        markdown_path = self.reports_dir / f"shadow_promotion_review_request_{as_of_date}.md"
        wrote_artifact = False
        if not ctx.dry_run:
            self.reports_dir.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text(
                json.dumps(review_request_artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            markdown_path.write_text(_promotion_review_request_markdown(review_request_artifact), encoding="utf-8")
            wrote_artifact = True

        summary = _mapping(review_request_artifact.get("summary"))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=ShadowPromotionReviewRequestResult(
                generated_at=str(review_request_artifact.get("generated_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")),
                db_path=str(self.db_path),
                reports_dir=str(self.reports_dir),
                as_of_date=str(review_request_artifact.get("as_of_date") or as_of_date),
                source_dossier_path=(
                    str(review_request_artifact.get("source_dossier_path"))
                    if review_request_artifact.get("source_dossier_path")
                    else None
                ),
                source_dossier_contract=str(review_request_artifact.get("source_dossier_contract") or SHADOW_PROMOTION_DOSSIER_CONTRACT),
                source_dossier_valid=bool(getattr(source_dossier_review, "valid", False)),
                source_dossier_status=str(source_dossier_status),
                would_write_artifact=True,
                wrote_artifact=wrote_artifact,
                artifact_path=str(artifact_path) if wrote_artifact else None,
                markdown_path=str(markdown_path) if wrote_artifact else None,
                artifact=review_request_artifact,
                active_params_mutated=False,
                wrote_strategy_version=False,
                wrote_strategy_versions=False,
                writes_trade_state=False,
                writes_paper_live_behavior=False,
                timer_mutated=False,
            ),
            lineage={
                "as_of_date": str(review_request_artifact.get("as_of_date") or as_of_date),
                "review_request_contract": SHADOW_PROMOTION_REVIEW_REQUEST_CONTRACT,
                "source_dossier_contract": str(review_request_artifact.get("source_dossier_contract") or SHADOW_PROMOTION_DOSSIER_CONTRACT),
                "source_dossier_status": source_dossier_status,
                "source_dossier_valid": str(bool(getattr(source_dossier_review, "valid", False))).lower(),
                "candidate_count": str(_int_value(summary.get("candidate_count"), 0)),
                "review_ready_count": str(_int_value(summary.get("review_ready_count"), 0)),
                "blocked_count": str(_int_value(summary.get("blocked_count"), 0)),
                "wrote_artifact": str(wrote_artifact).lower(),
            },
        )

    def build_replay_backtest_evidence(
        self,
        request: BuildShadowReplayBacktestEvidenceRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ShadowReplayBacktestEvidenceGenerationResult]:
        """Build validated replay/backtest evidence artifacts from shadow monitor inputs."""

        as_of_date = _compact_history_date(request.as_of_date)
        if request.as_of_date is not None and as_of_date is None:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_replay_backtest_generation_result(
                    self.db_path,
                    self.reports_dir,
                    request.output_dir,
                    request.as_of_date,
                    status="invalid_date",
                ),
                errors=[ServiceError("INVALID_AS_OF_DATE", "as_of_date must be YYYYMMDD or YYYY-MM-DD.")],
            )

        before_counts = _trade_state_counts(self.db_path)
        snapshot_result = self._snapshot_service.get_snapshot(
            GetShadowStrategySnapshotRequest(as_of_date=as_of_date),
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
                data=_empty_replay_backtest_generation_result(
                    self.db_path,
                    self.reports_dir,
                    request.output_dir,
                    as_of_date,
                    status="source_unavailable",
                ),
                warnings=snapshot_result.warnings,
                errors=snapshot_result.errors,
                lineage={
                    "read_only": "true",
                    "artifact_only": "true",
                    "wrote_artifacts": "false",
                },
            )

        snapshot = snapshot_result.data
        generation_date = str(getattr(snapshot, "as_of_date", None) or as_of_date or "")
        monitor_path = _resolve_shadow_artifact_path(
            _mapping(getattr(snapshot, "source_artifacts", {})).get("monitor_json"),
            self.reports_dir.parent,
        )
        if monitor_path is None:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_replay_backtest_generation_result(
                    self.db_path,
                    self.reports_dir,
                    request.output_dir,
                    generation_date,
                    status="source_unavailable",
                ),
                errors=[
                    ServiceError(
                        "SHADOW_MONITOR_ARTIFACT_NOT_FOUND",
                        "shadow monitor artifact path was not available from the snapshot.",
                    )
                ],
            )
        monitor, monitor_error = _load_json_object(monitor_path)
        if monitor_error is not None:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_replay_backtest_generation_result(
                    self.db_path,
                    self.reports_dir,
                    request.output_dir,
                    generation_date,
                    status="source_invalid",
                    source_monitor_path=str(monitor_path),
                ),
                errors=[ServiceError("SHADOW_MONITOR_ARTIFACT_INVALID", monitor_error)],
            )

        output_dir = Path(request.output_dir).expanduser() if request.output_dir else self.reports_dir
        requested_keys = {str(key).strip() for key in request.candidate_keys if str(key).strip()}
        candidate_monitors = [
            item
            for item in _list_mapping(monitor.get("candidate_monitors"))
            if not requested_keys or str(item.get("candidate_key") or "").strip() in requested_keys
        ]
        artifacts: list[dict[str, Any]] = []
        warnings: list[ServiceWarning] = []
        if not ctx.dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
        for candidate in candidate_monitors:
            candidate_key = str(candidate.get("candidate_key") or "").strip()
            if not candidate_key:
                continue
            artifact_path = output_dir / f"shadow_replay_backtest_evidence_{generation_date}_{candidate_key}.json"
            artifact = _shadow_replay_backtest_evidence_artifact(
                db_path=self.db_path,
                reports_dir=self.reports_dir,
                monitor=monitor,
                candidate=candidate,
                as_of_date=generation_date,
                required_sample_size=max(1, int(request.required_sample_size or DEFAULT_REQUIRED_SAMPLE_SIZE)),
                source_monitor_path=monitor_path,
            )
            if not ctx.dry_run:
                artifact_path.write_text(
                    json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                review = review_shadow_replay_backtest_evidence_artifact(
                    artifact_path,
                    expected_candidate_key=candidate_key,
                    expected_as_of_date=generation_date,
                    required_sample_size=max(1, int(request.required_sample_size or DEFAULT_REQUIRED_SAMPLE_SIZE)),
                )
            else:
                review = _best_replay_evidence_review(
                    _review_shadow_replay_backtest_evidence_file(
                        artifact_path,
                        artifact,
                        expected_as_of_date=generation_date,
                        candidate_required_samples={
                            candidate_key: max(1, int(request.required_sample_size or DEFAULT_REQUIRED_SAMPLE_SIZE))
                        },
                    )
                )
            review_payload = review.to_payload()
            generation = _mapping(_list_mapping(artifact.get("results"))[0].get("generation") if _list_mapping(artifact.get("results")) else {})
            if review.status != "accepted":
                warnings.append(
                    ServiceWarning(
                        code="SHADOW_REPLAY_BACKTEST_EVIDENCE_REJECTED",
                        message=f"{candidate_key} replay/backtest evidence is {review.status}: {review.error or 'blocked'}",
                    )
                )
            artifacts.append(
                {
                    "candidate_key": candidate_key,
                    "candidate_family": candidate.get("candidate_family"),
                    "artifact_path": str(artifact_path),
                    "wrote_artifact": not ctx.dry_run,
                    "status": review.status,
                    "valid": review.valid,
                    "sample_size": review.sample_size,
                    "required_sample_size": review.required_sample_size,
                    "source_hash": review.source_hash,
                    "blockers": review.blockers,
                    "generation": generation,
                    "review": review_payload,
                }
            )

        after_counts = _trade_state_counts(self.db_path)
        safety = _replay_generation_safety(before_counts, after_counts)
        if safety["changed_tables"]:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_replay_generation_result(
                    self.db_path,
                    self.reports_dir,
                    output_dir,
                    generation_date,
                    monitor_path,
                    artifacts,
                    wrote_artifacts=not ctx.dry_run,
                    safety=safety,
                ),
                warnings=warnings,
                errors=[
                    ServiceError(
                        "SHADOW_REPLAY_BACKTEST_MUTATION_RISK",
                        "shadow replay/backtest evidence generation changed protected trade state tables.",
                    )
                ],
            )

        result = _replay_generation_result(
            self.db_path,
            self.reports_dir,
            output_dir,
            generation_date,
            monitor_path,
            artifacts,
            wrote_artifacts=not ctx.dry_run,
            safety=safety,
        )
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=result,
            warnings=warnings,
            lineage={
                "as_of_date": generation_date,
                "candidate_count": str(result.candidate_count),
                "accepted_count": str(result.accepted_count),
                "rejected_count": str(result.rejected_count),
                "missing_count": str(result.missing_count),
                "wrote_artifacts": str(result.wrote_artifacts).lower(),
                "read_only": "true",
                "artifact_only": "true",
            },
        )

    def build_walk_forward_outcomes(
        self,
        request: BuildShadowWalkForwardOutcomesRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ShadowWalkForwardOutcomesResult]:
        """Accumulate post-close walk-forward outcomes from shadow monitor signals and market bars."""

        as_of_date = _compact_history_date(request.as_of_date)
        if request.as_of_date is not None and as_of_date is None:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_walk_forward_outcomes_result(
                    self.db_path,
                    self.reports_dir,
                    request.as_of_date,
                    status="invalid_date",
                ),
                errors=[ServiceError("INVALID_AS_OF_DATE", "as_of_date must be YYYYMMDD or YYYY-MM-DD.")],
            )

        before_counts = _trade_state_counts(self.db_path)
        snapshot_result = self._snapshot_service.get_snapshot(
            GetShadowStrategySnapshotRequest(as_of_date=as_of_date),
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
                data=_empty_walk_forward_outcomes_result(
                    self.db_path,
                    self.reports_dir,
                    as_of_date,
                    status="source_unavailable",
                ),
                warnings=snapshot_result.warnings,
                errors=snapshot_result.errors,
                lineage={"read_only": "true", "artifact_only": "true", "wrote_artifact": "false"},
            )

        snapshot = snapshot_result.data
        generation_date = str(getattr(snapshot, "as_of_date", None) or as_of_date or "")
        monitor_path = _resolve_shadow_artifact_path(
            _mapping(getattr(snapshot, "source_artifacts", {})).get("monitor_json"),
            self.reports_dir.parent,
        )
        if monitor_path is None:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_walk_forward_outcomes_result(
                    self.db_path,
                    self.reports_dir,
                    generation_date,
                    status="source_unavailable",
                ),
                errors=[
                    ServiceError(
                        "SHADOW_MONITOR_ARTIFACT_NOT_FOUND",
                        "shadow monitor artifact path was not available from the snapshot.",
                    )
                ],
            )
        monitor, monitor_error = _load_json_object(monitor_path, artifact_label="shadow monitor artifact")
        if monitor_error is not None:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_walk_forward_outcomes_result(
                    self.db_path,
                    self.reports_dir,
                    generation_date,
                    status="source_invalid",
                    source_monitor_path=str(monitor_path),
                ),
                errors=[ServiceError("SHADOW_MONITOR_ARTIFACT_INVALID", monitor_error)],
            )

        safety = _walk_forward_outcomes_safety(before_counts, _trade_state_counts(self.db_path))
        artifact = _shadow_walk_forward_outcomes_artifact(
            db_path=self.db_path,
            reports_dir=self.reports_dir,
            monitor=monitor,
            as_of_date=generation_date,
            source_monitor_path=monitor_path,
            horizon_days=max(1, int(request.horizon_days or 5)),
            safety=safety,
        )
        artifact_path = (
            Path(request.output_path).expanduser()
            if request.output_path
            else self.reports_dir / f"shadow_walk_forward_outcomes_{generation_date}.json"
        )
        markdown_path = artifact_path.with_suffix(".md")
        wrote_artifact = False
        if not ctx.dry_run:
            self.reports_dir.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            markdown_path.write_text(_shadow_walk_forward_outcomes_markdown(artifact), encoding="utf-8")
            wrote_artifact = True

        after_counts = _trade_state_counts(self.db_path)
        final_safety = _walk_forward_outcomes_safety(before_counts, after_counts)
        if final_safety["changed_tables"]:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_walk_forward_outcomes_result(
                    self.db_path,
                    self.reports_dir,
                    artifact,
                    monitor_path,
                    artifact_path,
                    markdown_path,
                    wrote_artifact=wrote_artifact,
                    safety=final_safety,
                ),
                errors=[
                    ServiceError(
                        "SHADOW_WALK_FORWARD_OUTCOMES_MUTATION_RISK",
                        "shadow walk-forward outcome accumulation changed protected trade state tables.",
                    )
                ],
            )

        result = _walk_forward_outcomes_result(
            self.db_path,
            self.reports_dir,
            artifact,
            monitor_path,
            artifact_path,
            markdown_path,
            wrote_artifact=wrote_artifact,
            safety=final_safety,
        )
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=result,
            lineage={
                "as_of_date": result.as_of_date,
                "outcomes_contract": SHADOW_WALK_FORWARD_OUTCOMES_CONTRACT,
                "candidate_count": str(result.candidate_count),
                "signal_count": str(result.signal_count),
                "status": result.status,
                "wrote_artifact": str(wrote_artifact).lower(),
                "read_only": "true",
                "artifact_only": "true",
            },
        )

    def get_promotion_review_request(
        self,
        request: GetShadowPromotionReviewRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ShadowPromotionReviewWorkbenchResult]:
        """Read the latest manual shadow promotion review request artifact."""

        as_of_date = _compact_history_date(request.as_of_date)
        if request.as_of_date is not None and as_of_date is None:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_promotion_review_workbench(
                    self.db_path,
                    self.reports_dir,
                    request.as_of_date,
                    artifact_error="as_of_date must be YYYYMMDD or YYYY-MM-DD.",
                ),
                errors=[ServiceError("INVALID_AS_OF_DATE", "as_of_date must be YYYYMMDD or YYYY-MM-DD.")],
            )

        artifact_root = self.reports_dir.parent
        artifact_path = _latest_shadow_promotion_review_request_path(self.reports_dir, as_of_date)
        if artifact_path is None:
            missing_date = as_of_date or datetime.now(timezone.utc).strftime("%Y%m%d")
            return ServiceResult(
                status="success",
                request_id=ctx.request_id,
                data=_empty_promotion_review_workbench(
                    self.db_path,
                    self.reports_dir,
                    missing_date,
                    artifact_error="shadow promotion review request artifact was not found.",
                ),
                warnings=[
                    ServiceWarning(
                        code="SHADOW_PROMOTION_REVIEW_REQUEST_MISSING",
                        message="shadow promotion review request artifact was not found.",
                    )
                ],
                lineage={
                    "as_of_date": missing_date,
                    "review_request_contract": SHADOW_PROMOTION_REVIEW_REQUEST_CONTRACT,
                    "read_only": "true",
                    "artifact_only": "true",
                    "status": "missing",
                },
            )

        review = review_shadow_promotion_review_request_artifact(artifact_path)
        artifact, read_error = _load_json_object(
            artifact_path,
            artifact_label="shadow promotion review request artifact",
        )
        if read_error is not None:
            result = _empty_promotion_review_workbench(
                self.db_path,
                self.reports_dir,
                as_of_date or _review_request_date_from_name(artifact_path.name),
                artifact_path=artifact_path,
                artifact_error=read_error,
            )
            return ServiceResult(
                status="success",
                request_id=ctx.request_id,
                data=result,
                warnings=[ServiceWarning(code="SHADOW_PROMOTION_REVIEW_REQUEST_INVALID", message=read_error)],
                lineage={
                    "as_of_date": result.as_of_date,
                    "review_request_contract": SHADOW_PROMOTION_REVIEW_REQUEST_CONTRACT,
                    "read_only": "true",
                    "artifact_only": "true",
                    "status": "invalid",
                },
            )

        artifact = _portable_artifact_paths(artifact, artifact_root)
        artifact = _promotion_review_artifact_with_current_replay_evidence(
            artifact,
            reports_dir=self.reports_dir,
            artifact_root=artifact_root,
        )
        summary = _mapping(artifact.get("summary"))
        review_request = _mapping(artifact.get("review_request"))
        replay_backtest_evidence = _mapping(artifact.get("replay_backtest_evidence"))
        source_dossier = _mapping(artifact.get("source_dossier"))
        source_dossier_review = _mapping(artifact.get("source_dossier_review"))
        safety = _mapping(artifact.get("safety")) or _promotion_review_request_safety()
        result_as_of_date = str(
            artifact.get("as_of_date")
            or as_of_date
            or _review_request_date_from_name(artifact_path.name)
            or ""
        ) or None
        status = str(
            summary.get("status")
            or review_request.get("request_status")
            or ("review_ready" if getattr(review, "review_ready_count", 0) else "blocked")
        )
        markdown_path = artifact_path.with_suffix(".md")
        result = ShadowPromotionReviewWorkbenchResult(
            generated_at=str(artifact.get("generated_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")),
            db_path=str(self.db_path),
            reports_dir=str(self.reports_dir),
            as_of_date=result_as_of_date,
            status=status,
            artifact_path=_portable_artifact_path(str(artifact_path), artifact_root),
            markdown_path=_portable_optional_path(markdown_path if markdown_path.exists() else None, artifact_root),
            artifact_exists=True,
            artifact_valid=bool(getattr(review, "valid", False)),
            artifact_error=getattr(review, "error", None),
            summary=summary,
            review_request=review_request,
            candidate_readiness=_list_mapping(source_dossier.get("candidates")),
            replay_backtest_evidence=replay_backtest_evidence,
            source_dossier_review=source_dossier_review,
            source_artifacts={
                "review_request_json": _portable_artifact_path(str(artifact_path), artifact_root),
                "review_request_markdown": _portable_optional_path(markdown_path if markdown_path.exists() else None, artifact_root),
                "source_dossier_json": _mapping(artifact.get("source_dossier_review")).get("path")
                or _optional_text(artifact.get("source_dossier_path")),
            },
            safety={
                **safety,
                "read_only": True,
                "artifact_only": True,
                "review_request_is_not_approval": True,
                "manual_review_required": True,
                "promotion_allowed": False,
                "active_params_mutated": False,
                "wrote_strategy_version": False,
                "wrote_strategy_versions": False,
                "writes_trade_state": False,
                "writes_paper_live_behavior": False,
                "timer_mutated": False,
            },
            artifact=artifact,
        )
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=result,
            lineage={
                "as_of_date": result.as_of_date,
                "review_request_contract": SHADOW_PROMOTION_REVIEW_REQUEST_CONTRACT,
                "artifact_valid": str(result.artifact_valid).lower(),
                "candidate_count": str(_int_value(summary.get("candidate_count"), len(result.candidate_readiness))),
                "review_ready_count": str(_int_value(summary.get("review_ready_count"), 0)),
                "blocked_count": str(_int_value(summary.get("blocked_count"), 0)),
                "read_only": "true",
                "artifact_only": "true",
            },
        )

    def get_decision_memo(
        self,
        request: GetShadowDecisionMemoRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ShadowDecisionMemoResult]:
        """Build a Chinese, read-only operator memo from shadow review artifacts."""

        as_of_date = _compact_history_date(request.as_of_date)
        if request.as_of_date is not None and as_of_date is None:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_shadow_decision_memo(
                    self.db_path,
                    self.reports_dir,
                    request.as_of_date,
                    status="invalid",
                    source_error="as_of_date must be YYYYMMDD or YYYY-MM-DD.",
                ),
                errors=[ServiceError("INVALID_AS_OF_DATE", "as_of_date must be YYYYMMDD or YYYY-MM-DD.")],
            )

        memo_date = as_of_date
        promotion_result = self.get_promotion_review_request(
            GetShadowPromotionReviewRequest(as_of_date=as_of_date),
            RequestContext(
                request_id=ctx.request_id,
                dry_run=True,
                operator=ctx.operator,
                source=ctx.source,
            ),
        )
        promotion = promotion_result.data or _empty_promotion_review_workbench(
            self.db_path,
            self.reports_dir,
            as_of_date,
            artifact_error="shadow promotion review request artifact was not available.",
        )
        memo_date = memo_date or promotion.as_of_date

        snapshot_result = self._snapshot_service.get_snapshot(
            GetShadowStrategySnapshotRequest(as_of_date=memo_date),
            RequestContext(
                request_id=ctx.request_id,
                dry_run=True,
                operator=ctx.operator,
                source=ctx.source,
            ),
        )
        snapshot = snapshot_result.data if snapshot_result.ok else None
        memo_date = memo_date or getattr(snapshot, "as_of_date", None)

        artifact_root = self.reports_dir.parent
        calibration = _load_shadow_decision_source_artifact(
            self.reports_dir,
            pattern=SHADOW_THRESHOLD_CALIBRATION_PATTERN,
            as_of_date=memo_date,
            artifact_root=artifact_root,
            expected_contract_key="calibration_contract",
            expected_contract="shadow_threshold_calibration_v1",
            missing_status="missing",
        )
        registry = _load_shadow_decision_source_artifact(
            self.reports_dir,
            pattern=SHADOW_STRATEGY_EXPERIMENT_REGISTRY_PATTERN,
            as_of_date=memo_date,
            artifact_root=artifact_root,
            expected_contract_key="registry_contract",
            expected_contract="shadow_strategy_experiment_registry_v1",
            missing_status="missing",
        )
        scorecard = _load_shadow_decision_source_artifact(
            self.reports_dir,
            pattern=SHADOW_SCORECARD_ARTIFACT_PATTERN,
            as_of_date=memo_date,
            artifact_root=artifact_root,
            expected_contract_key="scorecard_contract",
            expected_contract=SHADOW_OBSERVATION_SCORECARD_CONTRACT,
            missing_status="missing",
            expected_artifact_type="shadow_observation_scorecard",
        )
        walk_forward_outcomes = _load_shadow_decision_source_artifact(
            self.reports_dir,
            pattern=SHADOW_WALK_FORWARD_OUTCOMES_PATTERN,
            as_of_date=memo_date,
            artifact_root=artifact_root,
            expected_contract_key="outcomes_contract",
            expected_contract=SHADOW_WALK_FORWARD_OUTCOMES_CONTRACT,
            missing_status="missing",
            expected_artifact_type="shadow_walk_forward_outcomes",
        )

        promotion_payload = _shadow_promotion_workbench_payload(promotion)
        snapshot_payload = _shadow_snapshot_payload(snapshot, snapshot_result)
        memo_date = memo_date or _optional_text(promotion_payload.get("as_of_date")) or _optional_text(
            snapshot_payload.get("as_of_date")
        )
        result = _build_shadow_decision_memo_result(
            db_path=self.db_path,
            reports_dir=self.reports_dir,
            as_of_date=memo_date,
            promotion=promotion_payload,
            snapshot=snapshot_payload,
            calibration=calibration,
            registry=registry,
            scorecard=scorecard,
            walk_forward_outcomes=walk_forward_outcomes,
            promotion_status=promotion_result.status,
            snapshot_status=snapshot_result.status,
        )
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=result,
            warnings=[*promotion_result.warnings, *snapshot_result.warnings],
            lineage={
                "as_of_date": result.as_of_date,
                "memo_contract": SHADOW_DECISION_MEMO_CONTRACT,
                "status": result.status,
                "candidate_count": str(result.summary.get("candidate_count", 0)),
                "read_only": "true",
                "artifact_only": "true",
                "promotion_allowed": "false",
            },
        )


def _empty_walk_forward_outcomes_result(
    db_path: Path,
    reports_dir: Path,
    as_of_date: str | None,
    *,
    status: str,
    source_monitor_path: str | None = None,
) -> ShadowWalkForwardOutcomesResult:
    safety = _walk_forward_outcomes_safety({}, {})
    summary = {
        "status": status,
        "candidate_count": 0,
        "signal_count": 0,
        "complete_count": 0,
        "partial_horizon_count": 0,
        "missing_market_bar_count": 0,
        "promotion_allowed": False,
        "operator_note": "Walk-forward outcomes were not accumulated; shadow candidates remain review-only.",
    }
    return ShadowWalkForwardOutcomesResult(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        db_path=str(db_path),
        reports_dir=str(reports_dir),
        as_of_date=as_of_date,
        source_monitor_path=source_monitor_path,
        status=status,
        summary=summary,
        safety=safety,
        artifact={
            "artifact_type": "shadow_walk_forward_outcomes",
            "outcomes_contract": SHADOW_WALK_FORWARD_OUTCOMES_CONTRACT,
            "provider": SHADOW_WALK_FORWARD_OUTCOMES_PROVIDER,
            "as_of_date": as_of_date,
            "summary": summary,
            "safety": safety,
        },
    )


def _walk_forward_outcomes_result(
    db_path: Path,
    reports_dir: Path,
    artifact: Mapping[str, Any],
    source_monitor_path: Path,
    artifact_path: Path,
    markdown_path: Path,
    *,
    wrote_artifact: bool,
    safety: Mapping[str, Any],
) -> ShadowWalkForwardOutcomesResult:
    summary = _mapping(artifact.get("summary"))
    rows = _list_mapping(artifact.get("rows"))
    candidates = _list_mapping(artifact.get("candidates"))
    return ShadowWalkForwardOutcomesResult(
        generated_at=str(artifact.get("generated_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")),
        db_path=str(db_path),
        reports_dir=str(reports_dir),
        as_of_date=str(artifact.get("as_of_date") or "") or None,
        source_monitor_path=str(source_monitor_path),
        wrote_artifact=wrote_artifact,
        artifact_path=str(artifact_path) if wrote_artifact else None,
        markdown_path=str(markdown_path) if wrote_artifact else None,
        status=str(summary.get("status") or artifact.get("status") or "unknown"),
        candidate_count=_int_value(summary.get("candidate_count"), len(candidates)),
        signal_count=_int_value(summary.get("signal_count"), len(rows)),
        complete_count=_int_value(summary.get("complete_count"), 0),
        partial_horizon_count=_int_value(summary.get("partial_horizon_count"), 0),
        missing_market_bar_count=_int_value(summary.get("missing_market_bar_count"), 0),
        summary=summary,
        candidates=candidates,
        rows=rows,
        no_future_boundary=_mapping(artifact.get("no_future_boundary")),
        safety=dict(safety),
        artifact=dict(artifact),
        active_params_mutated=False,
        wrote_strategy_version=False,
        wrote_strategy_versions=False,
        writes_trade_state=False,
        writes_paper_live_behavior=False,
        timer_mutated=False,
    )


def _shadow_walk_forward_outcomes_artifact(
    *,
    db_path: Path,
    reports_dir: Path,
    monitor: Mapping[str, Any],
    as_of_date: str,
    source_monitor_path: Path,
    horizon_days: int,
    safety: Mapping[str, Any],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for candidate in _list_mapping(monitor.get("candidate_monitors")):
        candidate_key = str(candidate.get("candidate_key") or "").strip()
        if not candidate_key:
            continue
        candidate_family = str(candidate.get("candidate_family") or "unknown")
        source_rows = _monitor_walk_forward_rows_for_candidate(monitor, candidate_key)
        outcome_rows = _walk_forward_outcome_rows(
            db_path=db_path,
            source_rows=source_rows,
            as_of_date=as_of_date,
            candidate_key=candidate_key,
            candidate_family=candidate_family,
            horizon_days=horizon_days,
        )
        rows.extend(outcome_rows)
        candidates.append(
            _walk_forward_candidate_summary(
                candidate=candidate,
                source_rows=source_rows,
                outcome_rows=outcome_rows,
                horizon_days=horizon_days,
            )
        )

    no_future_boundary = _walk_forward_no_future_boundary(rows, as_of_date)
    complete_count = sum(1 for row in rows if row.get("outcome_availability") == "complete")
    partial_count = sum(1 for row in rows if row.get("partial_horizon"))
    missing_count = sum(1 for row in rows if row.get("missing_market_bars"))
    signal_count = len(rows)
    candidate_state_counts: dict[str, int] = {}
    for candidate in candidates:
        state = str(candidate.get("status") or "unknown")
        candidate_state_counts[state] = candidate_state_counts.get(state, 0) + 1
    status = _walk_forward_outcomes_status(candidates, no_future_boundary)
    summary = {
        "status": status,
        "candidate_count": len(candidates),
        "signal_count": signal_count,
        "complete_count": complete_count,
        "partial_horizon_count": partial_count,
        "missing_market_bar_count": missing_count,
        "candidate_state_counts": dict(sorted(candidate_state_counts.items())),
        "horizon_days": horizon_days,
        "provider": SHADOW_WALK_FORWARD_OUTCOMES_PROVIDER,
        "outcomes_contract": SHADOW_WALK_FORWARD_OUTCOMES_CONTRACT,
        "read_only": True,
        "artifact_only": True,
        "promotion_allowed": False,
        "operator_note": (
            "Walk-forward outcomes append market-bar labels only; they do not create paper trades, "
            "strategy versions, trade plans, positions, or timers."
        ),
    }
    return _portable_artifact_paths(
        {
            "artifact_type": "shadow_walk_forward_outcomes",
            "outcomes_contract": SHADOW_WALK_FORWARD_OUTCOMES_CONTRACT,
            "provider": SHADOW_WALK_FORWARD_OUTCOMES_PROVIDER,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "as_of_date": as_of_date,
            "source_monitor_path": str(source_monitor_path),
            "source_artifacts": {
                "monitor_json": str(source_monitor_path),
            },
            "summary": summary,
            "no_future_boundary": no_future_boundary,
            "candidates": candidates,
            "rows": rows,
            "safety": dict(safety),
            "notice": (
                "This artifact is an advisory post-close label accumulator. It is not a promotion approval "
                "and cannot mutate active CPB params, strategy versions, trades, positions, paper/live behavior, or timers."
            ),
        },
        reports_dir.parent,
    )


def _walk_forward_outcome_rows(
    *,
    db_path: Path,
    source_rows: list[dict[str, Any]],
    as_of_date: str,
    candidate_key: str,
    candidate_family: str,
    horizon_days: int,
) -> list[dict[str, Any]]:
    if not source_rows:
        return []
    if not db_path.exists():
        return [
            _missing_walk_forward_outcome_row(
                row,
                candidate_key,
                candidate_family,
                as_of_date,
                horizon_days,
                "market_bars_db_missing",
            )
            for row in source_rows
        ]
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            if not _table_exists(conn, "market_bars"):
                return [
                    _missing_walk_forward_outcome_row(
                        row,
                        candidate_key,
                        candidate_family,
                        as_of_date,
                        horizon_days,
                        "market_bars_table_missing",
                    )
                    for row in source_rows
                ]
            return [
                _walk_forward_outcome_row_from_market(
                    conn,
                    row,
                    as_of_date,
                    candidate_key,
                    candidate_family,
                    horizon_days,
                )
                for row in source_rows
            ]
    except sqlite3.Error as exc:
        return [
            _missing_walk_forward_outcome_row(
                row,
                candidate_key,
                candidate_family,
                as_of_date,
                horizon_days,
                f"market_bars_query_failed:{exc}",
            )
            for row in source_rows
        ]


def _walk_forward_outcome_row_from_market(
    conn: sqlite3.Connection,
    source_row: Mapping[str, Any],
    as_of_date: str,
    candidate_key: str,
    candidate_family: str,
    horizon_days: int,
) -> dict[str, Any]:
    ts_code = str(source_row.get("ts_code") or "").strip()
    planned_buy_date = str(source_row.get("planned_buy_date") or source_row.get("outcome_date") or "").strip()
    signal_date = str(source_row.get("signal_date") or source_row.get("review_date") or "").strip()
    if not ts_code or not planned_buy_date:
        return _missing_walk_forward_outcome_row(
            source_row,
            candidate_key,
            candidate_family,
            as_of_date,
            horizon_days,
            "shadow_walk_forward_signal_row_incomplete",
        )
    if planned_buy_date > as_of_date:
        return _missing_walk_forward_outcome_row(
            source_row,
            candidate_key,
            candidate_family,
            as_of_date,
            horizon_days,
            "shadow_walk_forward_outcome_not_due",
        )
    bars = list(
        conn.execute(
            """
            SELECT trade_date, open, high, low, close
            FROM market_bars
            WHERE ts_code = ?
              AND trade_date >= ?
              AND trade_date <= ?
            ORDER BY trade_date
            LIMIT ?
            """,
            (ts_code, planned_buy_date, as_of_date, horizon_days),
        )
    )
    if not bars:
        return _missing_walk_forward_outcome_row(
            source_row,
            candidate_key,
            candidate_family,
            as_of_date,
            horizon_days,
            "market_bars_missing",
        )
    entry_price = _float_or_none(source_row.get("outcome_open")) or _float_or_none(bars[0]["open"]) or _float_or_none(bars[0]["close"])
    if entry_price is None or entry_price <= 0:
        return _missing_walk_forward_outcome_row(
            source_row,
            candidate_key,
            candidate_family,
            as_of_date,
            horizon_days,
            "market_bars_entry_price_missing",
        )
    lows = [_float_or_none(bar["low"]) for bar in bars]
    highs = [_float_or_none(bar["high"]) for bar in bars]
    max_input_date = max(str(bar["trade_date"]) for bar in bars)
    partial = len(bars) < horizon_days
    availability = "complete" if not partial else "partial"
    return {
        "candidate_key": candidate_key,
        "candidate_family": candidate_family,
        "ts_code": ts_code,
        "name": source_row.get("name"),
        "bucket": source_row.get("bucket") or candidate_key,
        "signal_date": signal_date or None,
        "planned_buy_date": planned_buy_date,
        "data_cutoff_date": as_of_date,
        "available_bar_count": len(bars),
        "required_horizon_days": horizon_days,
        "missing_bar_count": max(0, horizon_days - len(bars)),
        "missing_market_bars": False,
        "partial_horizon": partial,
        "outcome_availability": availability,
        "t1_available": True,
        "t5_available": len(bars) >= 5,
        "max_input_date": max_input_date,
        "available_dates": [str(bar["trade_date"]) for bar in bars],
        "metrics": {
            "entry_open": round(entry_price, 4),
            "t1_close_pct": _bar_close_pct(bars, 0, entry_price),
            "t1_high_pct": _bar_high_pct(bars, 0, entry_price),
            "t1_low_pct": _bar_low_pct(bars, 0, entry_price),
            "t5_close_pct": _bar_close_pct(bars, 4, entry_price),
            "max_runup_pct": max((_pct_change(high, entry_price) for high in highs if high is not None), default=None),
            "max_drawdown_pct": min((_pct_change(low, entry_price) for low in lows if low is not None), default=None),
        },
        "no_future_boundary": {
            "passed": max_input_date <= as_of_date and (not signal_date or signal_date <= as_of_date),
            "signal_date": signal_date or None,
            "max_input_date": max_input_date,
            "data_cutoff_date": as_of_date,
            "query_cutoff_enforced": True,
        },
        "source_signal": _compact_walk_forward_source_signal(source_row),
        "advisory_only": True,
        "promotion_allowed": False,
    }


def _missing_walk_forward_outcome_row(
    source_row: Mapping[str, Any],
    candidate_key: str,
    candidate_family: str,
    as_of_date: str,
    horizon_days: int,
    reason: str,
) -> dict[str, Any]:
    signal_date = str(source_row.get("signal_date") or source_row.get("review_date") or "").strip()
    planned_buy_date = str(source_row.get("planned_buy_date") or source_row.get("outcome_date") or "").strip()
    return {
        "candidate_key": candidate_key,
        "candidate_family": candidate_family,
        "ts_code": source_row.get("ts_code"),
        "name": source_row.get("name"),
        "bucket": source_row.get("bucket") or candidate_key,
        "signal_date": signal_date or None,
        "planned_buy_date": planned_buy_date or None,
        "data_cutoff_date": as_of_date,
        "available_bar_count": 0,
        "required_horizon_days": horizon_days,
        "missing_bar_count": horizon_days,
        "missing_market_bars": True,
        "missing_reason": reason,
        "partial_horizon": False,
        "outcome_availability": "missing",
        "t1_available": False,
        "t5_available": False,
        "max_input_date": signal_date or planned_buy_date or as_of_date,
        "available_dates": [],
        "metrics": {
            "entry_open": None,
            "t1_close_pct": None,
            "t1_high_pct": None,
            "t1_low_pct": None,
            "t5_close_pct": None,
            "max_runup_pct": None,
            "max_drawdown_pct": None,
        },
        "no_future_boundary": {
            "passed": True,
            "signal_date": signal_date or None,
            "max_input_date": signal_date or planned_buy_date or as_of_date,
            "data_cutoff_date": as_of_date,
            "query_cutoff_enforced": True,
        },
        "source_signal": _compact_walk_forward_source_signal(source_row),
        "advisory_only": True,
        "promotion_allowed": False,
    }


def _compact_walk_forward_source_signal(source_row: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "ts_code",
        "name",
        "bucket",
        "score",
        "signal_date",
        "review_date",
        "planned_buy_date",
        "outcome_date",
        "review_close",
    )
    return {key: source_row.get(key) for key in keys if source_row.get(key) not in (None, "")}


def _walk_forward_candidate_summary(
    *,
    candidate: Mapping[str, Any],
    source_rows: list[dict[str, Any]],
    outcome_rows: list[dict[str, Any]],
    horizon_days: int,
) -> dict[str, Any]:
    candidate_key = str(candidate.get("candidate_key") or "unknown")
    t1_close = _walk_forward_metric_values(outcome_rows, "t1_close_pct")
    t1_high = _walk_forward_metric_values(outcome_rows, "t1_high_pct")
    t5_close = _walk_forward_metric_values(outcome_rows, "t5_close_pct")
    drawdowns = _walk_forward_metric_values(outcome_rows, "max_drawdown_pct")
    missing_count = sum(1 for row in outcome_rows if row.get("missing_market_bars"))
    partial_count = sum(1 for row in outcome_rows if row.get("partial_horizon"))
    complete_count = sum(1 for row in outcome_rows if row.get("outcome_availability") == "complete")
    blockers: list[str] = []
    if not source_rows:
        blockers.append("shadow_walk_forward_source_rows_missing")
    if missing_count:
        blockers.append("shadow_walk_forward_market_bars_missing")
    if partial_count:
        blockers.append("shadow_walk_forward_partial_horizon")
    status = "complete"
    if not source_rows:
        status = "missing"
    elif missing_count >= len(source_rows):
        status = "missing"
    elif partial_count or missing_count:
        status = "partial"
    return {
        "candidate_key": candidate_key,
        "candidate_family": candidate.get("candidate_family") or "unknown",
        "status": status,
        "source_signal_count": len(source_rows),
        "evaluated_signal_count": len(outcome_rows),
        "complete_count": complete_count,
        "partial_horizon_count": partial_count,
        "missing_market_bar_count": missing_count,
        "required_horizon_days": horizon_days,
        "metrics": {
            "t1_sample_size": len(t1_close),
            "t1_close_mean_pct": _mean(t1_close),
            "t1_close_win_rate_pct": _hit_rate(t1_close),
            "t1_high_mean_pct": _mean(t1_high),
            "t5_sample_size": len(t5_close),
            "t5_close_mean_pct": _mean(t5_close),
            "t5_close_win_rate_pct": _hit_rate(t5_close),
            "max_drawdown_pct": min(drawdowns) if drawdowns else None,
        },
        "latest_signal_date": max((str(row.get("signal_date") or "") for row in outcome_rows), default=None),
        "latest_outcome_input_date": max((str(row.get("max_input_date") or "") for row in outcome_rows), default=None),
        "blockers": blockers,
        "advisory_only": True,
        "promotion_allowed": False,
    }


def _walk_forward_metric_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    values = []
    for row in rows:
        value = _float_or_none(_mapping(row.get("metrics")).get(key))
        if value is not None:
            values.append(value)
    return values


def _walk_forward_no_future_boundary(rows: list[dict[str, Any]], as_of_date: str) -> dict[str, Any]:
    max_input_date = max((str(row.get("max_input_date") or "") for row in rows), default=None)
    max_signal_date = max((str(row.get("signal_date") or "") for row in rows if row.get("signal_date")), default=None)
    future_rows = [
        {
            "candidate_key": row.get("candidate_key"),
            "ts_code": row.get("ts_code"),
            "max_input_date": row.get("max_input_date"),
        }
        for row in rows
        if str(row.get("max_input_date") or "") > as_of_date
    ]
    return {
        "passed": not future_rows,
        "as_of_date": as_of_date,
        "max_signal_date": max_signal_date,
        "max_input_date": max_input_date,
        "future_row_count": len(future_rows),
        "future_rows": future_rows[:10],
        "query_cutoff_enforced": True,
        "operator_note": "Outcome queries use market_bars.trade_date <= as_of_date.",
    }


def _walk_forward_outcomes_status(
    candidates: list[dict[str, Any]],
    no_future_boundary: Mapping[str, Any],
) -> str:
    if not candidates:
        return "missing"
    if not bool(no_future_boundary.get("passed", False)):
        return "blocked"
    states = {str(candidate.get("status") or "unknown") for candidate in candidates}
    if states == {"complete"}:
        return "complete"
    if states <= {"complete", "partial"}:
        return "partial"
    return "partial"


def _walk_forward_outcomes_safety(
    before_counts: Mapping[str, int],
    after_counts: Mapping[str, int],
) -> dict[str, Any]:
    changed_tables = [
        table
        for table in ("strategy_versions", "trade_plans", "trades", "positions")
        if before_counts.get(table, 0) != after_counts.get(table, before_counts.get(table, 0))
    ]
    return {
        "read_only": True,
        "artifact_only": True,
        "advisory_only": True,
        "outcome_accumulation_only": True,
        "trade_state_counts_before": dict(before_counts),
        "trade_state_counts_after": dict(after_counts),
        "trade_state_counts_unchanged": not changed_tables,
        "changed_tables": changed_tables,
        "active_params_mutated": False,
        "wrote_strategy_version": False,
        "wrote_strategy_versions": False,
        "writes_trade_state": False,
        "writes_paper_live_behavior": False,
        "paper_live_deployment_changed": False,
        "timer_mutated": False,
        "promotion_allowed": False,
        "paper_observation_allowed": False,
    }


def _shadow_walk_forward_outcomes_markdown(artifact: Mapping[str, Any]) -> str:
    summary = _mapping(artifact.get("summary"))
    lines = [
        f"# {artifact.get('as_of_date')} Shadow Walk-forward Outcomes",
        "",
        "> Read-only post-close labels from market bars. This artifact does not promote strategies or create trading state.",
        "",
        "## Summary",
        "",
        f"- Status: {summary.get('status', 'unknown')}",
        f"- Candidates: {summary.get('candidate_count', 0)}",
        f"- Signals: {summary.get('signal_count', 0)}",
        f"- Complete horizons: {summary.get('complete_count', 0)}",
        f"- Partial horizons: {summary.get('partial_horizon_count', 0)}",
        f"- Missing market bars: {summary.get('missing_market_bar_count', 0)}",
        f"- Promotion allowed: {str(bool(summary.get('promotion_allowed'))).lower()}",
        "",
        "## Candidate Metrics",
        "",
        "| candidate | status | signals | complete | partial | missing | T+1 mean | T+5 mean | blockers |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for candidate in _list_mapping(artifact.get("candidates")):
        metrics = _mapping(candidate.get("metrics"))
        lines.append(
            "| "
            f"{candidate.get('candidate_key')} | "
            f"{candidate.get('status')} | "
            f"{candidate.get('source_signal_count', 0)} | "
            f"{candidate.get('complete_count', 0)} | "
            f"{candidate.get('partial_horizon_count', 0)} | "
            f"{candidate.get('missing_market_bar_count', 0)} | "
            f"{_display_pct(metrics.get('t1_close_mean_pct'))} | "
            f"{_display_pct(metrics.get('t5_close_mean_pct'))} | "
            f"{';'.join(_list_text(candidate.get('blockers'))) or 'none'} |"
        )
    boundary = _mapping(artifact.get("no_future_boundary"))
    lines.extend(
        [
            "",
            "## No-future Boundary",
            "",
            f"- Passed: {str(bool(boundary.get('passed'))).lower()}",
            f"- Max signal date: {boundary.get('max_signal_date') or '-'}",
            f"- Max input date: {boundary.get('max_input_date') or '-'}",
            f"- Data cutoff date: {boundary.get('as_of_date') or artifact.get('as_of_date')}",
            "",
        ]
    )
    return "\n".join(lines)


def _empty_replay_backtest_generation_result(
    db_path: Path,
    reports_dir: Path,
    output_dir: str | None,
    as_of_date: str | None,
    *,
    status: str,
    source_monitor_path: str | None = None,
) -> ShadowReplayBacktestEvidenceGenerationResult:
    output = Path(output_dir).expanduser() if output_dir else reports_dir
    safety = _replay_generation_safety({}, {})
    return ShadowReplayBacktestEvidenceGenerationResult(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        db_path=str(db_path),
        reports_dir=str(reports_dir),
        output_dir=str(output),
        as_of_date=as_of_date,
        source_monitor_path=source_monitor_path,
        summary={
            "status": status,
            "candidate_count": 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "missing_count": 0,
            "operator_note": "Replay/backtest evidence was not generated; promotion remains blocked.",
            "promotion_allowed": False,
        },
        safety=safety,
    )


def _replay_generation_result(
    db_path: Path,
    reports_dir: Path,
    output_dir: Path,
    as_of_date: str,
    source_monitor_path: Path,
    artifacts: list[dict[str, Any]],
    *,
    wrote_artifacts: bool,
    safety: Mapping[str, Any],
) -> ShadowReplayBacktestEvidenceGenerationResult:
    status_counts: dict[str, int] = {}
    for artifact in artifacts:
        status = str(artifact.get("status") or "missing")
        status_counts[status] = status_counts.get(status, 0) + 1
    summary = {
        "status": "generated",
        "candidate_count": len(artifacts),
        "accepted_count": status_counts.get("accepted", 0),
        "rejected_count": status_counts.get("rejected", 0),
        "missing_count": status_counts.get("missing", 0),
        "state_counts": dict(sorted(status_counts.items())),
        "wrote_artifacts": wrote_artifacts,
        "evidence_contract": SHADOW_REPLAY_BACKTEST_EVIDENCE_CONTRACT,
        "provider": SHADOW_REPLAY_BACKTEST_EVIDENCE_PROVIDER,
        "advisory_only": True,
        "promotion_allowed": False,
        "operator_note": (
            "Replay/backtest evidence is advisory only and clears only the replay/backtest "
            "artifact blocker when accepted by the M90 validator."
        ),
    }
    return ShadowReplayBacktestEvidenceGenerationResult(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        db_path=str(db_path),
        reports_dir=str(reports_dir),
        output_dir=str(output_dir),
        as_of_date=as_of_date,
        source_monitor_path=str(source_monitor_path),
        candidate_count=len(artifacts),
        accepted_count=status_counts.get("accepted", 0),
        rejected_count=status_counts.get("rejected", 0),
        missing_count=status_counts.get("missing", 0),
        wrote_artifacts=wrote_artifacts,
        artifacts=artifacts,
        summary=summary,
        safety=dict(safety),
        active_params_mutated=False,
        wrote_strategy_version=False,
        wrote_strategy_versions=False,
        writes_trade_state=False,
        writes_paper_live_behavior=False,
        timer_mutated=False,
    )


def _shadow_replay_backtest_evidence_artifact(
    *,
    db_path: Path,
    reports_dir: Path,
    monitor: Mapping[str, Any],
    candidate: Mapping[str, Any],
    as_of_date: str,
    required_sample_size: int,
    source_monitor_path: Path,
) -> dict[str, Any]:
    candidate_key = str(candidate.get("candidate_key") or "").strip()
    candidate_family = str(candidate.get("candidate_family") or "unknown")
    evidence = _shadow_replay_candidate_evidence_source(
        db_path=db_path,
        reports_dir=reports_dir,
        monitor=monitor,
        candidate=candidate,
        as_of_date=as_of_date,
        required_sample_size=required_sample_size,
    )
    metrics = dict(evidence["metrics"])
    start_date = str(evidence.get("start_date") or as_of_date)
    end_date = str(evidence.get("end_date") or as_of_date)
    sample_size = _int_value(evidence.get("sample_size"), 0)
    source_hash = build_shadow_replay_backtest_source_hash(
        provider=SHADOW_REPLAY_BACKTEST_EVIDENCE_PROVIDER,
        candidate_key=candidate_key,
        start_date=start_date,
        end_date=end_date,
        sample_size=sample_size,
        metrics=metrics,
    )
    generation_blockers = _unique_texts(_list_text(evidence.get("blockers")))
    result = {
        "provider": SHADOW_REPLAY_BACKTEST_EVIDENCE_PROVIDER,
        "candidate_key": candidate_key,
        "candidate_family": candidate_family,
        "as_of_date": as_of_date,
        "date_range": {"start_date": start_date, "end_date": end_date},
        "sample_size": sample_size,
        "required_sample_size": required_sample_size,
        "metrics": metrics,
        "source_hash": source_hash,
        "no_future_boundary": evidence["no_future_boundary"],
        "generation": {
            "status": "generated_with_blockers" if generation_blockers else "generated",
            "blockers": generation_blockers,
            "source_row_count": evidence.get("source_row_count", 0),
            "t1_sample_size": metrics.get("t1_sample_size"),
            "t5_sample_size": metrics.get("t5_sample_size"),
            "missing_market_bar_count": evidence.get("missing_market_bar_count", 0),
            "partial_horizon_count": evidence.get("partial_horizon_count", 0),
            "source_kind": evidence.get("source_kind"),
            "advisory_only": True,
            "promotion_allowed": False,
        },
        "source_artifacts": evidence.get("source_artifacts", []),
        "safety": _shadow_replay_evidence_safety(),
    }
    return {
        "artifact_type": "shadow_replay_backtest_evidence",
        "evidence_contract": SHADOW_REPLAY_BACKTEST_EVIDENCE_CONTRACT,
        "provider": SHADOW_REPLAY_BACKTEST_EVIDENCE_PROVIDER,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of_date": as_of_date,
        "source_monitor_path": _portable_artifact_path(str(source_monitor_path), reports_dir.parent),
        "results": [result],
        "summary": {
            "candidate_count": 1,
            "candidate_key": candidate_key,
            "required_sample_size": required_sample_size,
            "generation_blockers": generation_blockers,
            "advisory_only": True,
            "promotion_allowed": False,
        },
        "safety": _shadow_replay_evidence_safety(),
    }


def _shadow_replay_candidate_evidence_source(
    *,
    db_path: Path,
    reports_dir: Path,
    monitor: Mapping[str, Any],
    candidate: Mapping[str, Any],
    as_of_date: str,
    required_sample_size: int,
) -> dict[str, Any]:
    candidate_key = str(candidate.get("candidate_key") or "").strip()
    if candidate_key in {"trend_extension_shadow", "breakout_pressure_shadow", "low_price_momentum_shadow"}:
        return _shadow_bucket_replay_evidence_source(
            db_path=db_path,
            monitor=monitor,
            candidate=candidate,
            as_of_date=as_of_date,
            required_sample_size=required_sample_size,
        )
    if candidate_key == "preconfirm_watchlist":
        return _preconfirm_replay_evidence_source(
            reports_dir=reports_dir,
            candidate=candidate,
            as_of_date=as_of_date,
            required_sample_size=required_sample_size,
        )
    if candidate_key == "pullback_dip_buy":
        return _dip_buy_replay_evidence_source(
            reports_dir=reports_dir,
            candidate=candidate,
            as_of_date=as_of_date,
            required_sample_size=required_sample_size,
        )
    return _summary_only_replay_evidence_source(
        candidate=candidate,
        as_of_date=as_of_date,
        required_sample_size=required_sample_size,
        blockers=["shadow_replay_backtest_candidate_source_unknown"],
    )


def _shadow_bucket_replay_evidence_source(
    *,
    db_path: Path,
    monitor: Mapping[str, Any],
    candidate: Mapping[str, Any],
    as_of_date: str,
    required_sample_size: int,
) -> dict[str, Any]:
    candidate_key = str(candidate.get("candidate_key") or "").strip()
    source_rows = _monitor_walk_forward_rows_for_candidate(monitor, candidate_key)
    progress = _mapping(candidate.get("walk_forward_progress"))
    outcomes: list[dict[str, Any]] = []
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                if _table_exists(conn, "market_bars"):
                    outcomes = [_market_replay_outcome(conn, row, as_of_date) for row in source_rows]
                else:
                    outcomes = [_missing_replay_outcome("market_bars_table_missing", row) for row in source_rows]
        except sqlite3.Error as exc:
            outcomes = [_missing_replay_outcome(f"market_bars_query_failed:{exc}", row) for row in source_rows]
    else:
        outcomes = [_missing_replay_outcome("market_bars_db_missing", row) for row in source_rows]

    t1_close = [value for value in (_float_or_none(item.get("t1_close_pct")) for item in outcomes) if value is not None]
    t1_high = [value for value in (_float_or_none(item.get("t1_high_pct")) for item in outcomes) if value is not None]
    t5_close = [value for value in (_float_or_none(item.get("t5_close_pct")) for item in outcomes) if value is not None]
    drawdowns = [value for value in (_float_or_none(item.get("drawdown_pct")) for item in outcomes) if value is not None]
    missing_count = sum(1 for item in outcomes if item.get("missing"))
    partial_count = sum(1 for item in outcomes if item.get("partial_horizon"))
    max_input_date = max((str(item.get("max_input_date") or "") for item in outcomes), default="")
    signal_dates = [
        str(row.get("signal_date") or row.get("review_date") or "")
        for row in source_rows
        if _is_compact_date(row.get("signal_date") or row.get("review_date"))
    ]
    metrics = {
        "t1_close_mean_pct": _mean(t1_close) if t1_close else _float_or_none(progress.get("t1_close_mean_pct")),
        "t1_close_win_rate_pct": _hit_rate(t1_close) if t1_close else _float_or_none(progress.get("t1_close_win_rate_pct")),
        "t1_high_mean_pct": _mean(t1_high) if t1_high else _float_or_none(progress.get("t1_high_mean_pct")),
        "t5_close_mean_pct": _mean(t5_close) if t5_close else _float_or_none(progress.get("t5_close_mean_pct")),
        "t5_close_win_rate_pct": _hit_rate(t5_close) if t5_close else _float_or_none(progress.get("t5_close_win_rate_pct")),
        "max_drawdown_pct": min(drawdowns) if drawdowns else _first_float(progress, "max_drawdown_pct", "mae_10d_median_pct", "t1_low_mean_pct"),
        "t1_sample_size": len(t1_close),
        "t5_sample_size": len(t5_close),
        "source_row_count": len(source_rows),
    }
    blockers: list[str] = []
    if not source_rows:
        blockers.append("shadow_replay_backtest_source_rows_missing")
    if missing_count:
        blockers.append("shadow_replay_backtest_missing_bars")
    if len(t1_close) < required_sample_size:
        blockers.append("shadow_replay_backtest_sample_size_insufficient")
    if any(metrics.get(key) in (None, "") for key in REQUIRED_REPLAY_BACKTEST_METRICS):
        blockers.append("shadow_replay_backtest_metric_gap")
    return {
        "source_kind": "shadow_monitor_walk_forward_market_bars",
        "start_date": min(signal_dates) if signal_dates else _optional_text(progress.get("start_signal_date")) or as_of_date,
        "end_date": as_of_date,
        "sample_size": len(t1_close),
        "source_row_count": len(source_rows),
        "missing_market_bar_count": missing_count,
        "partial_horizon_count": partial_count,
        "metrics": metrics,
        "no_future_boundary": {
            "passed": True,
            "max_input_date": max_input_date or as_of_date,
            "data_cutoff_date": as_of_date,
            "latest_market_date": max_input_date or as_of_date,
        },
        "source_artifacts": [],
        "blockers": blockers,
    }


def _preconfirm_replay_evidence_source(
    *,
    reports_dir: Path,
    candidate: Mapping[str, Any],
    as_of_date: str,
    required_sample_size: int,
) -> dict[str, Any]:
    source_path = _candidate_progress_source_artifact(candidate, reports_dir)
    blockers: list[str] = []
    if source_path is None:
        return _summary_only_replay_evidence_source(
            candidate=candidate,
            as_of_date=as_of_date,
            required_sample_size=required_sample_size,
            blockers=["shadow_replay_backtest_preconfirm_source_missing"],
        )
    payload, error = _load_json_object(source_path, artifact_label="preconfirm watchlist source artifact")
    if error is not None:
        return _summary_only_replay_evidence_source(
            candidate=candidate,
            as_of_date=as_of_date,
            required_sample_size=required_sample_size,
            blockers=["shadow_replay_backtest_preconfirm_source_invalid"],
            source_artifacts=[str(source_path)],
        )
    row = _summary_row_by_key(payload.get("summary"), "pre_action", "高潜伏预警") or _summary_row_by_key(
        payload.get("summary"),
        "pre_action",
        "全部",
    )
    meta = _mapping(payload.get("meta"))
    sample_size = _int_value(row.get("next_close_ret_from_watch_n"), _int_value(row.get("signals"), 0))
    metrics = {
        "t1_close_mean_pct": _ratio_to_pct(row.get("next_close_ret_from_watch_mean")),
        "t1_close_win_rate_pct": _ratio_to_pct(row.get("next_close_ret_from_watch_win_rate")),
        "t1_high_mean_pct": _ratio_to_pct(row.get("next_high_ret_from_watch_mean")),
        "t5_close_mean_pct": _ratio_to_pct(row.get("watch_ret_5d_mean")),
        "t5_close_win_rate_pct": _ratio_to_pct(row.get("watch_ret_5d_win_rate")),
        "max_drawdown_pct": _ratio_to_pct(row.get("watch_ret_5d_min") if row.get("watch_ret_5d_min") is not None else row.get("next_close_ret_from_watch_min")),
        "t1_sample_size": sample_size,
        "t5_sample_size": _int_value(row.get("watch_ret_5d_n"), 0),
        "source_row_count": _int_value(row.get("signals"), sample_size),
    }
    if sample_size < required_sample_size:
        blockers.append("shadow_replay_backtest_sample_size_insufficient")
    if any(metrics.get(key) in (None, "") for key in REQUIRED_REPLAY_BACKTEST_METRICS):
        blockers.append("shadow_replay_backtest_metric_gap")
    end_date = _compact_history_date(_optional_text(meta.get("end_date"))) or as_of_date
    return {
        "source_kind": "preconfirm_watchlist_backtest_artifact",
        "start_date": _compact_history_date(_optional_text(meta.get("start_date"))) or end_date,
        "end_date": end_date,
        "sample_size": sample_size,
        "source_row_count": metrics["source_row_count"],
        "missing_market_bar_count": 0,
        "partial_horizon_count": 0,
        "metrics": metrics,
        "no_future_boundary": {
            "passed": end_date <= as_of_date,
            "max_input_date": end_date,
            "data_cutoff_date": end_date,
            "latest_market_date": end_date,
        },
        "source_artifacts": [_portable_artifact_path(str(source_path), reports_dir.parent)],
        "blockers": blockers,
    }


def _dip_buy_replay_evidence_source(
    *,
    reports_dir: Path,
    candidate: Mapping[str, Any],
    as_of_date: str,
    required_sample_size: int,
) -> dict[str, Any]:
    source_path = _candidate_progress_source_artifact(candidate, reports_dir)
    if source_path is None:
        return _summary_only_replay_evidence_source(
            candidate=candidate,
            as_of_date=as_of_date,
            required_sample_size=required_sample_size,
            blockers=["shadow_replay_backtest_dip_buy_source_missing"],
        )
    payload, error = _load_json_object(source_path, artifact_label="pullback dip-buy source artifact")
    if error is not None:
        return _summary_only_replay_evidence_source(
            candidate=candidate,
            as_of_date=as_of_date,
            required_sample_size=required_sample_size,
            blockers=["shadow_replay_backtest_dip_buy_source_invalid"],
            source_artifacts=[str(source_path)],
        )
    selected_variant = payload.get("selected_variant")
    row = _summary_row_by_key(payload.get("variants"), "variant_id", str(selected_variant or ""))
    if not row and _list_mapping(payload.get("variants")):
        row = _list_mapping(payload.get("variants"))[0]
    freshness = _mapping(payload.get("source_freshness"))
    current_dates = [
        str(item.get("review_date"))
        for item in _list_mapping(payload.get("current_levels"))
        if _is_compact_date(item.get("review_date"))
    ]
    sample_size = _int_value(row.get("ret_5d_n"), _int_value(row.get("fill_n"), 0))
    t1_sample_size = _int_value(row.get("ret_1d_n"), 0)
    metrics = {
        "t1_close_mean_pct": _ratio_to_pct(row.get("ret_1d_mean")),
        "t1_close_win_rate_pct": _ratio_to_pct(row.get("ret_1d_win_rate")),
        "t1_high_mean_pct": _ratio_to_pct(row.get("mfe_1d_mean")),
        "t5_close_mean_pct": _ratio_to_pct(row.get("ret_5d_mean")),
        "t5_close_win_rate_pct": _ratio_to_pct(row.get("ret_5d_win_rate")),
        "max_drawdown_pct": _ratio_to_pct(row.get("mae_10d_median")),
        "t1_sample_size": t1_sample_size,
        "t5_sample_size": sample_size,
        "source_row_count": _int_value(row.get("fill_n"), sample_size),
    }
    blockers = []
    if sample_size < required_sample_size:
        blockers.append("shadow_replay_backtest_sample_size_insufficient")
    if any(metrics.get(key) in (None, "") for key in REQUIRED_REPLAY_BACKTEST_METRICS):
        blockers.append("shadow_replay_backtest_metric_gap")
    start_date = (
        _compact_history_date(_optional_text(freshness.get("market_data_start_date")))
        or (min(current_dates) if current_dates else None)
        or as_of_date
    )
    end_date = (
        _compact_history_date(_optional_text(freshness.get("market_data_end_date")))
        or (max(current_dates) if current_dates else None)
        or as_of_date
    )
    return {
        "source_kind": "pullback_dip_buy_artifact_summary",
        "start_date": start_date,
        "end_date": end_date,
        "sample_size": sample_size,
        "source_row_count": metrics["source_row_count"],
        "missing_market_bar_count": 0,
        "partial_horizon_count": 0,
        "metrics": metrics,
        "no_future_boundary": {
            "passed": end_date <= as_of_date,
            "max_input_date": end_date,
            "data_cutoff_date": end_date,
            "latest_market_date": end_date,
        },
        "source_artifacts": [_portable_artifact_path(str(source_path), reports_dir.parent)],
        "blockers": blockers,
    }


def _summary_only_replay_evidence_source(
    *,
    candidate: Mapping[str, Any],
    as_of_date: str,
    required_sample_size: int,
    blockers: list[str],
    source_artifacts: list[str] | None = None,
) -> dict[str, Any]:
    progress = _mapping(candidate.get("walk_forward_progress"))
    comparison = _mapping(candidate.get("comparison_vs_frozen_cpb"))
    sample_size = _sample_size(progress, comparison)
    metrics = {
        "t1_close_mean_pct": _first_float(progress, "t1_close_mean_pct", "next_open_ret_1d_mean_pct"),
        "t1_close_win_rate_pct": _first_float(progress, "t1_close_win_rate_pct", "ret_5d_win_rate_pct"),
        "t5_close_mean_pct": _first_float(progress, "t5_close_mean_pct", "next_open_ret_5d_mean_pct", "ret_5d_mean_pct"),
        "max_drawdown_pct": _first_float(progress, "max_drawdown_pct", "mae_10d_median_pct"),
        "t1_sample_size": sample_size,
        "t5_sample_size": sample_size,
        "source_row_count": sample_size,
    }
    generation_blockers = list(blockers)
    if sample_size < required_sample_size:
        generation_blockers.append("shadow_replay_backtest_sample_size_insufficient")
    if any(metrics.get(key) in (None, "") for key in REQUIRED_REPLAY_BACKTEST_METRICS):
        generation_blockers.append("shadow_replay_backtest_metric_gap")
    return {
        "source_kind": "summary_only",
        "start_date": _compact_history_date(_optional_text(progress.get("start_signal_date"))) or as_of_date,
        "end_date": _compact_history_date(_optional_text(progress.get("latest_outcome_date"))) or as_of_date,
        "sample_size": sample_size,
        "source_row_count": sample_size,
        "missing_market_bar_count": 0,
        "partial_horizon_count": 0,
        "metrics": metrics,
        "no_future_boundary": {
            "passed": True,
            "max_input_date": as_of_date,
            "data_cutoff_date": as_of_date,
            "latest_market_date": as_of_date,
        },
        "source_artifacts": source_artifacts or [],
        "blockers": generation_blockers,
    }


def _monitor_walk_forward_rows_for_candidate(
    monitor: Mapping[str, Any],
    candidate_key: str,
) -> list[dict[str, Any]]:
    rows = _list_mapping(_mapping(monitor.get("walk_forward_progress")).get("rows"))
    return [
        row
        for row in rows
        if str(row.get("candidate_key") or row.get("bucket") or "").strip() == candidate_key
    ]


def _market_replay_outcome(
    conn: sqlite3.Connection,
    source_row: Mapping[str, Any],
    as_of_date: str,
) -> dict[str, Any]:
    ts_code = str(source_row.get("ts_code") or "").strip()
    planned_buy_date = str(source_row.get("planned_buy_date") or source_row.get("outcome_date") or "").strip()
    if not ts_code or not planned_buy_date:
        return _missing_replay_outcome("shadow_replay_backtest_signal_row_incomplete", source_row)
    bars = list(
        conn.execute(
            """
            SELECT trade_date, open, high, low, close
            FROM market_bars
            WHERE ts_code = ?
              AND trade_date >= ?
              AND trade_date <= ?
            ORDER BY trade_date
            LIMIT 5
            """,
            (ts_code, planned_buy_date, as_of_date),
        )
    )
    if not bars:
        return _missing_replay_outcome("market_bars_missing", source_row)
    entry_price = _float_or_none(bars[0]["open"]) or _float_or_none(bars[0]["close"])
    if entry_price is None or entry_price <= 0:
        return _missing_replay_outcome("market_bars_entry_price_missing", source_row)
    lows = [_float_or_none(bar["low"]) for bar in bars]
    max_input_date = max(str(bar["trade_date"]) for bar in bars)
    return {
        "missing": False,
        "partial_horizon": len(bars) < 5,
        "max_input_date": max_input_date,
        "t1_close_pct": _bar_close_pct(bars, 0, entry_price),
        "t1_high_pct": _bar_high_pct(bars, 0, entry_price),
        "t5_close_pct": _bar_close_pct(bars, 4, entry_price),
        "drawdown_pct": min((_pct_change(low, entry_price) for low in lows if low is not None), default=None),
    }


def _missing_replay_outcome(reason: str, source_row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "missing": True,
        "partial_horizon": False,
        "missing_reason": reason,
        "max_input_date": source_row.get("planned_buy_date") or source_row.get("outcome_date"),
        "t1_close_pct": None,
        "t1_high_pct": None,
        "t5_close_pct": None,
        "drawdown_pct": None,
    }


def _bar_high_pct(bars: list[sqlite3.Row], index: int, entry_price: float) -> float | None:
    if len(bars) <= index:
        return None
    high = _float_or_none(bars[index]["high"])
    if high is None:
        return None
    return _pct_change(high, entry_price)


def _bar_low_pct(bars: list[sqlite3.Row], index: int, entry_price: float) -> float | None:
    if len(bars) <= index:
        return None
    low = _float_or_none(bars[index]["low"])
    if low is None:
        return None
    return _pct_change(low, entry_price)


def _candidate_progress_source_artifact(candidate: Mapping[str, Any], reports_dir: Path) -> Path | None:
    progress = _mapping(candidate.get("walk_forward_progress"))
    return _resolve_shadow_artifact_path(progress.get("source_artifact"), reports_dir.parent)


def _resolve_shadow_artifact_path(value: object, artifact_root: Path) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if path.is_absolute():
        return path
    candidates = [artifact_root / path, artifact_root / "reports" / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return artifact_root / path


def _summary_row_by_key(rows: object, key: str, expected: str) -> dict[str, Any]:
    for row in _list_mapping(rows):
        if str(row.get(key) or "") == expected:
            return row
    return {}


def _ratio_to_pct(value: object) -> float | None:
    parsed = _float_or_none(value)
    if parsed is None:
        return None
    return round(parsed * 100.0, 2) if abs(parsed) <= 1.0 else round(parsed, 2)


def _shadow_replay_evidence_safety() -> dict[str, Any]:
    return {
        "read_only": True,
        "artifact_only": True,
        "advisory_only": True,
        "active_params_mutated": False,
        "wrote_strategy_version": False,
        "wrote_strategy_versions": False,
        "writes_trade_state": False,
        "writes_paper_live_behavior": False,
        "paper_live_deployment_changed": False,
        "timer_mutated": False,
        "promotion_allowed": False,
        "paper_observation_allowed": False,
    }


def _replay_generation_safety(
    before_counts: Mapping[str, int],
    after_counts: Mapping[str, int],
) -> dict[str, Any]:
    changed_tables = [
        table
        for table in ("strategy_versions", "trade_plans", "trades", "positions")
        if before_counts.get(table, 0) != after_counts.get(table, before_counts.get(table, 0))
    ]
    return {
        "read_only": True,
        "artifact_only": True,
        "advisory_only": True,
        "trade_state_counts_before": dict(before_counts),
        "trade_state_counts_after": dict(after_counts),
        "trade_state_counts_unchanged": not changed_tables,
        "changed_tables": changed_tables,
        "active_params_mutated": False,
        "wrote_strategy_version": False,
        "wrote_strategy_versions": False,
        "writes_trade_state": False,
        "writes_paper_live_behavior": False,
        "timer_mutated": False,
        "promotion_allowed": False,
        "paper_observation_allowed": False,
    }


def _trade_state_counts(db_path: Path) -> dict[str, int]:
    tables = ("strategy_versions", "trade_plans", "trades", "positions")
    if not db_path.exists():
        return {table: 0 for table in tables}
    try:
        with sqlite3.connect(db_path) as conn:
            return {table: _table_count(conn, table) for table in tables}
    except sqlite3.Error:
        return {table: 0 for table in tables}


def _table_count(conn: sqlite3.Connection, table_name: str) -> int:
    if not _table_exists(conn, table_name):
        return 0
    row = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
    return int(row[0] or 0)


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


def _bounded_history_window(value: object) -> int:
    return max(1, min(60, _int_value(value, DEFAULT_HISTORY_WINDOW)))


def _history_dates(reports_dir: Path, as_of_date: str | None, window: int) -> list[str]:
    as_of = _compact_history_date(as_of_date)
    dates: set[str] = set()
    for pattern in ("shadow_observation_scorecard_*.json", "shadow_promotion_dossier_*.json"):
        for path in reports_dir.glob(pattern):
            date = path.stem.rsplit("_", 1)[-1]
            if len(date) == 8 and date.isdigit() and (not as_of or date <= as_of):
                dates.add(date)
    return sorted(dates, reverse=True)[:window]


def _compact_history_date(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("-", "")
    return text if len(text) == 8 and text.isdigit() else None


def _read_history_artifact(
    path: Path,
    *,
    missing_blocker: str,
    invalid_blocker: str,
) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, missing_blocker
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, invalid_blocker
    if not isinstance(payload, Mapping):
        return None, invalid_blocker
    return dict(payload), None


def _portable_optional_path(path: Path | None, artifact_root: Path) -> str | None:
    return _portable_artifact_path(str(path), artifact_root) if path is not None else None


def _history_date_summary(
    history_date: str,
    scorecard: Mapping[str, Any] | None,
    dossier: Mapping[str, Any] | None,
    artifact_blockers: list[str],
) -> dict[str, Any]:
    scorecard_summary = _mapping(scorecard.get("summary") if scorecard else None)
    dossier_summary = _mapping(dossier.get("summary") if dossier else None)
    scorecard_candidates = _scorecard_history_candidates(scorecard or {})
    top_candidate = (
        scorecard_summary.get("top_candidate_key")
        or (_mapping(scorecard_candidates[0]).get("candidate_key") if scorecard_candidates else None)
    )
    source_artifacts = _unique_texts(
        [
            *_list_text((scorecard or {}).get("source_artifacts")),
            *_list_text((dossier or {}).get("source_artifacts")),
        ]
    )
    return {
        "date": history_date,
        "status": (scorecard or {}).get("status") or scorecard_summary.get("status") or "missing",
        "scorecard_available": scorecard is not None,
        "dossier_available": dossier is not None,
        "artifact_blockers": artifact_blockers,
        "candidate_count": _int_value((scorecard or {}).get("candidate_count"), len(scorecard_candidates)),
        "blocked_candidate_count": _int_value((scorecard or {}).get("blocked_candidate_count"), 0),
        "review_ready_count": _int_value(dossier_summary.get("review_ready_count"), 0),
        "top_candidate_key": top_candidate,
        "source_artifacts": source_artifacts,
    }


def _scorecard_history_candidates(scorecard: Mapping[str, Any]) -> list[dict[str, Any]]:
    for key in ("rows", "scorecard_rows", "candidates", "top_candidates"):
        candidates = _list_mapping(scorecard.get(key))
        if candidates:
            return candidates
    return []


def _history_rows_for_date(
    history_date: str,
    scorecard: Mapping[str, Any] | None,
    dossier: Mapping[str, Any] | None,
    artifact_blockers: list[str],
) -> list[dict[str, Any]]:
    scorecard = scorecard or {}
    scorecard_candidates = _scorecard_history_candidates(scorecard)
    dossier_by_key = {
        str(item.get("candidate_key") or ""): item
        for item in _list_mapping((dossier or {}).get("candidates"))
        if item.get("candidate_key")
    }
    candidates_by_key = {
        str(candidate.get("candidate_key") or ""): candidate
        for candidate in scorecard_candidates
        if candidate.get("candidate_key")
    }
    for candidate_key, dossier_candidate in dossier_by_key.items():
        candidates_by_key.setdefault(candidate_key, {"candidate_key": candidate_key, **dossier_candidate})
    candidates = list(candidates_by_key.values())
    source_artifacts = _unique_texts(
        [
            *_list_text(scorecard.get("source_artifacts")),
            *_list_text((dossier or {}).get("source_artifacts")),
        ]
    )
    rows = []
    for index, candidate in enumerate(candidates, start=1):
        candidate_key = str(candidate.get("candidate_key") or "").strip()
        if not candidate_key:
            continue
        dossier_candidate = dossier_by_key.get(candidate_key, {})
        comparison = _mapping(candidate.get("comparison_vs_frozen_cpb"))
        today_top = _mapping(candidate.get("today_top"))
        readiness_checks = _mapping(dossier_candidate.get("readiness_checks"))
        minimum_sample = _mapping(readiness_checks.get("minimum_sample"))
        blocker_clearance = _mapping(readiness_checks.get("blocker_clearance"))
        blockers = _unique_texts(
            [
                *_list_text(candidate.get("blockers")),
                *_list_text(dossier_candidate.get("blocked_reasons")),
                *_list_text(blocker_clearance.get("blockers")),
                *artifact_blockers,
            ]
        )
        score = _history_score(candidate, today_top)
        sample_size = _int_value(
            candidate.get("sample_size"),
            _int_value(
                candidate.get("walk_forward_days"),
                _int_value(_mapping(candidate.get("comparison_vs_frozen_cpb")).get("candidate_days"), _int_value(minimum_sample.get("actual"), 0)),
            ),
        )
        required_sample = _int_value(
            candidate.get("required_sample"),
            _int_value(candidate.get("required_sample_size"), _int_value(minimum_sample.get("threshold"), DEFAULT_REQUIRED_SAMPLE_SIZE)),
        )
        coverage_status = _history_coverage_status(candidate, sample_size, required_sample)
        row_source_artifacts = _unique_texts(
            [
                *_list_text(candidate.get("source_artifacts")),
                *_list_text(dossier_candidate.get("source_artifacts")),
                *source_artifacts,
            ]
        )
        rows.append(
            {
                "date": history_date,
                "as_of_date": history_date,
                "candidate_key": candidate_key,
                "candidate_family": str(candidate.get("candidate_family") or dossier_candidate.get("candidate_family") or "unknown"),
                "rank": _int_value(candidate.get("rank"), index),
                "score": score,
                "outcome_score": score,
                "observation_status": str(candidate.get("observation_status") or candidate.get("status") or "unknown"),
                "review_status": str(dossier_candidate.get("review_status") or candidate.get("promotion_readiness") or "missing"),
                "sample_size": sample_size,
                "required_sample": required_sample,
                "coverage_status": coverage_status,
                "sample_coverage_status": coverage_status,
                "market_data_coverage_status": candidate.get("market_data_coverage_status"),
                "blocker_count": _int_value(candidate.get("blocker_count"), len(blockers)),
                "blockers": blockers,
                "blocked_reasons": _list_text(dossier_candidate.get("blocked_reasons")),
                "frozen_cpb_delta_pct": _first_float(candidate, "frozen_cpb_delta_pct")
                if _first_float(candidate, "frozen_cpb_delta_pct") is not None
                else _float_or_none(comparison.get("t1_close_mean_delta_pct")),
                "frozen_cpb_win_delta_pct": _float_or_none(comparison.get("t1_close_win_rate_delta_pct")),
                "today_top": today_top,
                "top_candidate": today_top,
                "source_artifacts": row_source_artifacts,
                "missing_artifact_blockers": artifact_blockers,
                "promotion_allowed": False,
                "paper_observation_allowed": False,
                "read_only_note": "Observation history is research-only and is not paper trading.",
            }
        )
    return rows


def _history_score(candidate: Mapping[str, Any], today_top: Mapping[str, Any]) -> float | None:
    score = _first_float(candidate, "outcome_score", "score")
    if score is not None:
        return score
    return _float_or_none(today_top.get("score"))


def _history_coverage_status(candidate: Mapping[str, Any], sample_size: int, required_sample: int) -> str:
    explicit = str(candidate.get("sample_coverage_status") or candidate.get("coverage_status") or "").strip()
    if explicit:
        return explicit
    walk_status = str(candidate.get("walk_forward_status") or "").strip()
    if walk_status == "artifact_summary_only":
        return "artifact_summary_only"
    if sample_size <= 0:
        return "missing"
    if required_sample and sample_size < required_sample:
        return "insufficient_sample"
    if walk_status in {"complete", ""}:
        return "complete"
    return walk_status


def _candidate_histories(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_candidate: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_candidate.setdefault(str(row.get("candidate_key") or ""), []).append(row)
    candidates = []
    for candidate_key, candidate_rows in by_candidate.items():
        chronology = sorted(candidate_rows, key=lambda item: str(item.get("date") or ""))
        latest = chronology[-1]
        first = chronology[0]
        candidates.append(
            {
                "candidate_key": candidate_key,
                "candidate_family": latest.get("candidate_family"),
                "dates_observed": len(chronology),
                "latest_date": latest.get("date"),
                "latest_rank": latest.get("rank"),
                "latest_score": latest.get("score"),
                "latest_status": latest.get("observation_status"),
                "latest_review_status": latest.get("review_status"),
                "latest_coverage_status": latest.get("coverage_status"),
                "latest_blocker_count": latest.get("blocker_count"),
                "latest_frozen_cpb_delta_pct": latest.get("frozen_cpb_delta_pct"),
                "score_delta": _numeric_delta(latest.get("score"), first.get("score")),
                "rank_delta": _numeric_delta(latest.get("rank"), first.get("rank")),
                "blocker_count_delta": _numeric_delta(latest.get("blocker_count"), first.get("blocker_count")),
                "frozen_cpb_delta_change_pct": _numeric_delta(
                    latest.get("frozen_cpb_delta_pct"),
                    first.get("frozen_cpb_delta_pct"),
                ),
                "coverage_states": _unique_texts([str(item.get("coverage_status") or "") for item in chronology]),
                "review_statuses": _unique_texts([str(item.get("review_status") or "") for item in chronology]),
                "history": chronology,
                "promotion_allowed": False,
                "paper_observation_allowed": False,
            }
        )
    candidates.sort(key=lambda item: (_int_value(item.get("latest_rank"), 9999), str(item.get("candidate_key") or "")))
    return candidates


def _numeric_delta(latest: object, first: object) -> float | None:
    latest_value = _float_or_none(latest)
    first_value = _float_or_none(first)
    if latest_value is None or first_value is None:
        return None
    return round(latest_value - first_value, 2)


def _history_status(rows: list[dict[str, Any]], date_summaries: list[dict[str, Any]]) -> str:
    if not date_summaries:
        return "missing"
    if any(item.get("artifact_blockers") for item in date_summaries):
        return "blocked"
    if any(row.get("observation_status") == "blocked" or _int_value(row.get("blocker_count"), 0) for row in rows):
        return "blocked"
    return "observing" if rows else "missing"


def _history_counts(
    rows: list[dict[str, Any]],
    date_summaries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        "date_count": len(date_summaries),
        "row_count": len(rows),
        "history_row_count": len(rows),
        "candidate_count": len(candidates),
        "blocked_candidate_count": sum(
            1
            for candidate in candidates
            if candidate.get("latest_status") == "blocked" or _int_value(candidate.get("latest_blocker_count"), 0)
        ),
        "review_ready_count": sum(1 for candidate in candidates if candidate.get("latest_review_status") == "review_ready"),
        "missing_artifact_date_count": sum(1 for item in date_summaries if item.get("artifact_blockers")),
        "missing_scorecard_count": sum(1 for item in date_summaries if not item.get("scorecard_available")),
        "missing_dossier_count": sum(1 for item in date_summaries if not item.get("dossier_available")),
    }


def _history_summary(rows: list[dict[str, Any]], candidates: list[dict[str, Any]], status: str) -> dict[str, Any]:
    latest_date = max((str(row.get("date") or "") for row in rows), default=None)
    latest_rows = [row for row in rows if row.get("date") == latest_date]
    latest_rows.sort(key=lambda item: _int_value(item.get("rank"), 9999))
    top = latest_rows[0] if latest_rows else {}
    return {
        "status": status,
        "latest_date": latest_date,
        "top_candidate_key": top.get("candidate_key"),
        "top_score": top.get("score"),
        "candidate_count": len(candidates),
        "operator_note": (
            "Shadow observation history is research-only; it compares artifacts across dates "
            "and does not approve promotion or enable paper trading."
        ),
    }


def _observation_history_safety() -> dict[str, Any]:
    return {
        "read_only": True,
        "artifact_only": True,
        "observation_history_is_research_only": True,
        "observation_is_not_paper_trading": True,
        "active_params_mutated": False,
        "wrote_strategy_version": False,
        "writes_trade_state": False,
        "writes_paper_live_behavior": False,
        "timer_mutated": False,
        "promotion_allowed": False,
        "trade_plan_allowed": False,
        "paper_observation_allowed": False,
    }


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


def _empty_promotion_review_workbench(
    db_path: Path,
    reports_dir: Path,
    as_of_date: str | None,
    *,
    artifact_path: Path | None = None,
    artifact_error: str | None = None,
) -> ShadowPromotionReviewWorkbenchResult:
    artifact_root = reports_dir.parent
    compact_date = _compact_history_date(as_of_date) or as_of_date
    safety = _promotion_review_request_safety()
    status = "missing" if artifact_path is None else "invalid"
    return ShadowPromotionReviewWorkbenchResult(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        db_path=str(db_path),
        reports_dir=str(reports_dir),
        as_of_date=compact_date,
        status=status,
        artifact_path=_portable_optional_path(artifact_path, artifact_root),
        artifact_exists=artifact_path is not None,
        artifact_valid=False,
        artifact_error=artifact_error,
        summary={
            "status": status,
            "candidate_count": 0,
            "review_ready_count": 0,
            "blocked_count": 0,
            "review_ready_is_not_approval": True,
            "manual_review_required": True,
            "promotion_allowed": False,
            "replay_backtest_evidence": _replay_evidence_summary_from_payloads([]),
            "operator_note": "Shadow promotion review request is unavailable; promotion remains blocked.",
        },
        review_request={
            "request_key": f"shadow-promotion-review-request:{compact_date or 'latest'}",
            "request_status": status,
            "blocking_reason": (
                "shadow_promotion_review_request_missing"
                if artifact_path is None
                else "shadow_promotion_review_request_invalid"
            ),
            "required_human_decisions": [
                {
                    "decision_key": "manual_promotion_approval_required",
                    "required": True,
                    "status": "blocked",
                    "note": "A valid review request artifact is required before any human review.",
                }
            ],
            "required_replay_backtest_evidence": [
                {
                    "candidate_key": None,
                    "status": "missing",
                    "evidence_contract": SHADOW_REPLAY_BACKTEST_EVIDENCE_CONTRACT,
                    "blockers": [REPLAY_BACKTEST_REQUIRED_BLOCKER],
                    "promotion_allowed": False,
                    "paper_observation_allowed": False,
                    "advisory_only": True,
                }
            ],
            "rollback_notes": _promotion_review_request_rollback_notes({}),
            "safety_notes": _promotion_review_request_safety_notes(),
            "review_ready_candidates": [],
            "blocked_candidate_keys": [],
        },
        replay_backtest_evidence={
            "summary": _replay_evidence_summary_from_payloads([]),
            "by_candidate": {},
            "orphaned": [],
        },
        source_artifacts={
            "review_request_json": _portable_optional_path(artifact_path, artifact_root),
            "review_request_markdown": None,
            "source_dossier_json": None,
        },
        safety=safety,
        artifact={
            "artifact_type": "shadow_promotion_review_request",
            "review_request_contract": SHADOW_PROMOTION_REVIEW_REQUEST_CONTRACT,
            "as_of_date": compact_date,
            "summary": {
                "status": status,
                "promotion_allowed": False,
            },
            "safety": safety,
        },
    )


def _empty_shadow_decision_memo(
    db_path: Path,
    reports_dir: Path,
    as_of_date: str | None,
    *,
    status: str = "blocked",
    source_error: str | None = None,
) -> ShadowDecisionMemoResult:
    safety = _shadow_decision_memo_safety()
    blockers = ["shadow_decision_memo_source_unavailable"]
    if source_error:
        blockers.append(source_error)
    return ShadowDecisionMemoResult(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        db_path=str(db_path),
        reports_dir=str(reports_dir),
        as_of_date=_compact_history_date(as_of_date) or as_of_date,
        status=status,
        summary={
            "status": status,
            "candidate_count": 0,
            "blocker_count": len(blockers),
            "conclusion_zh": "影子决策备忘录来源不可用，所有候选保持阻断。",
            "promotion_allowed": False,
            "manual_review_required": True,
        },
        sections=_shadow_decision_sections(
            candidate_overview=[],
            decision_queue=[],
            evidence_items=[],
            blockers=blockers,
            next_experiments=[],
            human_decisions=[],
            rollback_notes=["来源不可用时禁止晋升、交易、写计划或改 timer。"],
            safety=safety,
        ),
        decision_queue={
            "queue_contract": SHADOW_DECISION_QUEUE_CONTRACT,
            "language": "zh-CN",
            "as_of_date": _compact_history_date(as_of_date) or as_of_date,
            "status": status,
            "candidate_count": 0,
            "blocked_candidate_count": 0,
            "manual_review_required": True,
            "promotion_allowed": False,
            "artifact_only": True,
            "items": [],
        },
        source_status={
            "promotion_review": status,
            "snapshot": status,
            "calibration": "missing",
            "experiment_registry": "missing",
            "source_error": source_error,
        },
        safety=safety,
    )


def _build_shadow_decision_memo_result(
    *,
    db_path: Path,
    reports_dir: Path,
    as_of_date: str | None,
    promotion: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    calibration: Mapping[str, Any],
    registry: Mapping[str, Any],
    scorecard: Mapping[str, Any],
    walk_forward_outcomes: Mapping[str, Any],
    promotion_status: str,
    snapshot_status: str,
) -> ShadowDecisionMemoResult:
    artifact_root = reports_dir.parent
    safety = _shadow_decision_memo_safety()
    review_request = _mapping(promotion.get("review_request"))
    promotion_summary = _mapping(promotion.get("summary"))
    replay = _mapping(promotion.get("replay_backtest_evidence"))
    replay_summary = _mapping(_mapping(promotion_summary.get("replay_backtest_evidence")) or replay.get("summary"))
    candidate_memos = _shadow_decision_candidate_memos(
        promotion=promotion,
        snapshot=snapshot,
        calibration=calibration,
        registry=registry,
    )
    decision_queue = _shadow_decision_queue(
        as_of_date=as_of_date,
        promotion=promotion,
        snapshot=snapshot,
        scorecard=scorecard,
        walk_forward_outcomes=walk_forward_outcomes,
        registry=registry,
        candidate_memos=candidate_memos,
    )
    blockers = _shadow_decision_blockers(
        promotion=promotion,
        calibration=calibration,
        registry=registry,
        candidate_memos=candidate_memos,
    )
    next_experiments = _shadow_decision_next_experiments(calibration=calibration, registry=registry)
    human_decisions = _list_mapping(review_request.get("required_human_decisions"))
    rollback_notes = _unique_texts(
        [
            *_list_text(review_request.get("rollback_notes")),
            *_list_text(review_request.get("safety_notes")),
            *_shadow_decision_blocked_mutation_targets(calibration=calibration, registry=registry),
        ]
    )
    evidence_items = _shadow_decision_evidence_items(
        promotion=promotion,
        snapshot=snapshot,
        calibration=calibration,
        registry=registry,
        replay_summary=replay_summary,
    )
    status = "blocked" if blockers else "manual_review_required"
    review_ready_count = _int_value(promotion_summary.get("review_ready_count"), 0)
    source_artifacts = {
        "promotion_review_request": _optional_text(_mapping(promotion.get("source_artifacts")).get("review_request_json"))
        or _optional_text(promotion.get("artifact_path")),
        "shadow_snapshot_monitor": _optional_text(_mapping(snapshot.get("source_artifacts")).get("monitor_artifact")),
        "shadow_snapshot_preflight": _optional_text(
            _mapping(snapshot.get("source_artifacts")).get("promotion_preflight_artifact")
        ),
        "threshold_calibration": _optional_text(calibration.get("artifact_path")),
        "experiment_registry": _optional_text(registry.get("artifact_path")),
        "shadow_observation_scorecard": _optional_text(scorecard.get("artifact_path")),
        "shadow_walk_forward_outcomes": _optional_text(walk_forward_outcomes.get("artifact_path")),
    }
    source_artifacts = _portable_artifact_paths(source_artifacts, artifact_root)
    summary = {
        "status": status,
        "candidate_count": len(candidate_memos),
        "decision_queue_candidate_count": _int_value(decision_queue.get("candidate_count"), len(candidate_memos)),
        "review_ready_count": review_ready_count,
        "blocker_count": len(blockers),
        "next_experiment_count": len(next_experiments),
        "accepted_replay_evidence_count": _int_value(replay_summary.get("accepted_count"), 0),
        "rejected_replay_evidence_count": _int_value(replay_summary.get("rejected_count"), 0),
        "missing_replay_evidence_count": _int_value(replay_summary.get("missing_count"), 0),
        "conclusion_zh": _shadow_decision_conclusion_zh(
            status=status,
            review_ready_count=review_ready_count,
            blocker_count=len(blockers),
            registry_status=str(registry.get("status") or "missing"),
        ),
        "promotion_allowed": False,
        "manual_review_required": True,
        "memo_is_not_approval": True,
    }
    return ShadowDecisionMemoResult(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        db_path=str(db_path),
        reports_dir=str(reports_dir),
        as_of_date=as_of_date,
        status=status,
        summary=summary,
        sections=_shadow_decision_sections(
            candidate_overview=candidate_memos,
            decision_queue=_list_mapping(decision_queue.get("items")),
            evidence_items=evidence_items,
            blockers=blockers,
            next_experiments=next_experiments,
            human_decisions=human_decisions,
            rollback_notes=rollback_notes,
            safety=safety,
        ),
        decision_queue=decision_queue,
        candidate_memos=candidate_memos,
        promotion_review={
            "status": promotion.get("status"),
            "artifact_valid": bool(promotion.get("artifact_valid")),
            "summary": promotion_summary,
            "review_request": review_request,
        },
        scorecard=scorecard,
        walk_forward=_mapping(snapshot.get("walk_forward")),
        walk_forward_outcomes=walk_forward_outcomes,
        replay_backtest_evidence=replay,
        calibration=calibration,
        experiment_registry=registry,
        source_artifacts=source_artifacts,
        source_status={
            "promotion_review": promotion_status,
            "snapshot": snapshot_status,
            "calibration": calibration.get("status"),
            "experiment_registry": registry.get("status"),
            "shadow_observation_scorecard": scorecard.get("status"),
            "shadow_walk_forward_outcomes": walk_forward_outcomes.get("status"),
        },
        safety=safety,
    )


def _shadow_promotion_workbench_payload(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {
        "review_request_contract": getattr(value, "review_request_contract", SHADOW_PROMOTION_REVIEW_REQUEST_CONTRACT),
        "generated_at": getattr(value, "generated_at", None),
        "as_of_date": getattr(value, "as_of_date", None),
        "status": getattr(value, "status", "missing"),
        "artifact_path": getattr(value, "artifact_path", None),
        "markdown_path": getattr(value, "markdown_path", None),
        "artifact_exists": getattr(value, "artifact_exists", False),
        "artifact_valid": getattr(value, "artifact_valid", False),
        "artifact_error": getattr(value, "artifact_error", None),
        "summary": dict(getattr(value, "summary", {}) or {}),
        "review_request": dict(getattr(value, "review_request", {}) or {}),
        "candidate_readiness": list(getattr(value, "candidate_readiness", []) or []),
        "replay_backtest_evidence": dict(getattr(value, "replay_backtest_evidence", {}) or {}),
        "source_dossier_review": dict(getattr(value, "source_dossier_review", {}) or {}),
        "source_artifacts": dict(getattr(value, "source_artifacts", {}) or {}),
        "safety": dict(getattr(value, "safety", {}) or {}),
        "artifact": dict(getattr(value, "artifact", {}) or {}),
    }


def _shadow_snapshot_payload(value: object, result: ServiceResult[Any]) -> dict[str, Any]:
    if value is None:
        return {
            "status": "missing",
            "errors": [error.code for error in result.errors],
            "source_artifacts": {},
            "counts": {},
            "walk_forward": {},
            "candidates": [],
            "safety": {},
        }
    if isinstance(value, Mapping):
        return dict(value)
    return {
        "snapshot_contract": getattr(value, "snapshot_contract", "shadow_strategy_snapshot_v1"),
        "as_of_date": getattr(value, "as_of_date", None),
        "next_trade_date": getattr(value, "next_trade_date", None),
        "status": getattr(value, "status", "unknown"),
        "source_artifacts": dict(getattr(value, "source_artifacts", {}) or {}),
        "counts": dict(getattr(value, "counts", {}) or {}),
        "walk_forward": dict(getattr(value, "walk_forward", {}) or {}),
        "frozen_cpb_comparison": dict(getattr(value, "frozen_cpb_comparison", {}) or {}),
        "candidates": list(getattr(value, "candidates", []) or []),
        "safety": dict(getattr(value, "safety", {}) or {}),
        "release_gate": dict(getattr(value, "release_gate", {}) or {}),
        "errors": [error.code for error in result.errors],
    }


def _load_shadow_decision_source_artifact(
    reports_dir: Path,
    *,
    pattern: str,
    as_of_date: str | None,
    artifact_root: Path,
    expected_contract_key: str,
    expected_contract: str,
    missing_status: str,
    expected_artifact_type: str | None = None,
) -> dict[str, Any]:
    path = _latest_shadow_decision_source_path(reports_dir, pattern, as_of_date)
    source_key = pattern.replace("_*.json", "")
    if path is None:
        return {
            "status": missing_status,
            "valid": False,
            "artifact_path": None,
            "summary": {},
            "payload": {},
            "blockers": [f"{source_key}_missing"],
            "safety": _shadow_decision_memo_safety(),
        }
    artifact, load_error = _load_json_object(path, artifact_label=source_key)
    if load_error is not None:
        return {
            "status": "invalid",
            "valid": False,
            "artifact_path": _portable_artifact_path(str(path), artifact_root),
            "summary": {},
            "payload": {},
            "blockers": [f"{source_key}_invalid"],
            "error": load_error,
            "safety": _shadow_decision_memo_safety(),
        }
    artifact = _portable_artifact_paths(artifact, artifact_root)
    contract = _optional_text(artifact.get(expected_contract_key))
    contract_valid = contract == expected_contract
    safety = _mapping(artifact.get("safety"))
    artifact_type_valid = expected_artifact_type is None or artifact.get("artifact_type") == expected_artifact_type
    blockers = _shadow_decision_artifact_blockers(
        artifact,
        contract_valid=contract_valid,
        source_key=source_key,
        artifact_type_valid=artifact_type_valid,
    )
    return {
        "status": "available" if not blockers else "blocked",
        "valid": not blockers,
        "artifact_path": _portable_artifact_path(str(path), artifact_root),
        "contract": contract,
        "summary": _mapping(artifact.get("summary")),
        "payload": artifact,
        "blockers": blockers,
        "safety": {
            **safety,
            "promotion_allowed": False,
            "writes_trade_state": False,
            "writes_paper_live_behavior": False,
            "timer_mutated": False,
        },
    }


def _latest_shadow_decision_source_path(reports_dir: Path, pattern: str, as_of_date: str | None) -> Path | None:
    candidates = [path for path in reports_dir.glob(pattern) if path.is_file()]
    if as_of_date is not None:
        exact = [path for path in candidates if _shadow_decision_artifact_date(path.name) == as_of_date]
        return sorted(exact, key=lambda path: (path.stat().st_mtime, path.name))[-1] if exact else None
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda path: (_shadow_decision_artifact_date(path.name) or "", path.stat().st_mtime, path.name),
    )[-1]


def _shadow_decision_artifact_date(name: str) -> str | None:
    stem = name[:-5] if name.endswith(".json") else name
    candidate = stem.rsplit("_", 1)[-1]
    return candidate if len(candidate) == 8 and candidate.isdigit() else None


def _shadow_decision_artifact_blockers(
    artifact: Mapping[str, Any],
    *,
    contract_valid: bool,
    source_key: str,
    artifact_type_valid: bool = True,
) -> list[str]:
    blockers = []
    if not artifact_type_valid:
        blockers.append(f"{source_key}_artifact_type_invalid")
    if not contract_valid:
        blockers.append(f"{source_key}_contract_invalid")
    safety = _mapping(artifact.get("safety"))
    release_gate = _mapping(artifact.get("release_gate"))
    if bool(safety.get("promotion_allowed")) or bool(release_gate.get("promotion_allowed")):
        blockers.append(f"{source_key}_reports_promotion_allowed")
    for key in (
        "active_params_mutated",
        "active_params_mutated_by_calibration",
        "wrote_strategy_version",
        "wrote_strategy_versions",
        "writes_trade_state",
        "writes_paper_live_behavior",
        "timer_mutated",
    ):
        if bool(safety.get(key)):
            blockers.append(f"{source_key}_{key}")
    return blockers


def _shadow_decision_candidate_memos(
    *,
    promotion: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    calibration: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> list[dict[str, Any]]:
    promotion_candidates = _list_mapping(promotion.get("candidate_readiness"))
    snapshot_candidates = _list_mapping(snapshot.get("candidates"))
    candidates = promotion_candidates or snapshot_candidates
    evidence_by_candidate = _mapping(_mapping(promotion.get("replay_backtest_evidence")).get("by_candidate"))
    walk_by_candidate = _shadow_decision_walk_by_candidate(snapshot)
    calibration_by_candidate = {
        str(item.get("candidate_key")): item
        for item in _list_mapping(_mapping(calibration.get("payload")).get("candidates"))
        if item.get("candidate_key") is not None
    }
    registry_by_candidate = _shadow_decision_experiments_by_candidate(registry)
    rows = []
    for candidate in candidates:
        candidate_key = _optional_text(candidate.get("candidate_key")) or "-"
        evidence = _mapping(evidence_by_candidate.get(candidate_key))
        walk = _mapping(walk_by_candidate.get(candidate_key))
        calibration_candidate = _mapping(calibration_by_candidate.get(candidate_key))
        blockers = _unique_texts(
            [
                *_list_text(candidate.get("blocked_reasons")),
                *_list_text(candidate.get("blockers")),
                *_list_text(_mapping(_mapping(candidate.get("readiness_checks")).get("blocker_clearance")).get("blockers")),
                *_list_text(evidence.get("blockers")),
                *_shadow_decision_calibration_blockers(calibration_candidate),
            ]
        )
        experiments = registry_by_candidate.get(candidate_key) or _shadow_decision_calibration_experiments(
            calibration,
            candidate_key,
        )
        rows.append(
            {
                "candidate_key": candidate_key,
                "candidate_family": candidate.get("candidate_family") or calibration_candidate.get("candidate_family") or "shadow_candidate",
                "summary_zh": _shadow_decision_candidate_summary_zh(candidate_key, evidence, walk, blockers),
                "review_status": candidate.get("review_status") or candidate.get("promotion_readiness") or "blocked",
                "evidence_status": evidence.get("status") or "missing",
                "walk_forward_status": walk.get("status") or candidate.get("walk_forward_status") or "unknown",
                "walk_forward": walk,
                "sample_size": evidence.get("sample_size"),
                "required_sample_size": evidence.get("required_sample_size"),
                "t1_close_mean_pct": _mapping(evidence.get("metrics")).get("t1_close_mean_pct")
                or _mapping(calibration_candidate.get("metrics")).get("mean_return_pct"),
                "t1_close_win_rate_pct": _mapping(evidence.get("metrics")).get("t1_close_win_rate_pct")
                or _mapping(calibration_candidate.get("metrics")).get("win_rate_pct"),
                "frozen_cpb_delta_pct": _mapping(_mapping(calibration_candidate.get("metrics")).get("frozen_cpb_comparison")).get(
                    "mean_return_delta_pct"
                ),
                "blockers": blockers,
                "next_experiments": experiments,
                "replay_backtest_evidence": evidence,
                "manual_decision_zh": "保持影子观察；如需推进，先补齐证据并另开人工 strategy-version 任务。",
                "promotion_allowed": False,
            }
        )
    return rows


def _shadow_decision_queue(
    *,
    as_of_date: str | None,
    promotion: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    scorecard: Mapping[str, Any],
    walk_forward_outcomes: Mapping[str, Any],
    registry: Mapping[str, Any],
    candidate_memos: list[dict[str, Any]],
) -> dict[str, Any]:
    scorecard_candidates = _candidate_payloads_by_key(_mapping(scorecard.get("payload")).get("candidates"))
    outcome_candidates = _candidate_payloads_by_key(_mapping(walk_forward_outcomes.get("payload")).get("candidates"))
    registry_experiments = _shadow_decision_raw_registry_experiments_by_candidate(registry)
    human_decisions = _list_mapping(_mapping(promotion.get("review_request")).get("required_human_decisions"))
    release_gate = _mapping(_mapping(registry.get("payload")).get("release_gate"))
    manual_boundaries = _mapping(_mapping(registry.get("payload")).get("manual_approval_boundaries"))
    next_review_date = _optional_text(snapshot.get("next_trade_date")) or _optional_text(promotion.get("as_of_date")) or as_of_date
    items = []
    for memo in candidate_memos:
        candidate_key = _optional_text(memo.get("candidate_key")) or "unknown"
        scorecard_candidate = _mapping(scorecard_candidates.get(candidate_key))
        outcome_candidate = _mapping(outcome_candidates.get(candidate_key))
        experiments = registry_experiments.get(candidate_key, [])
        blockers = _unique_texts(
            [
                *_list_text(memo.get("blockers")),
                *_list_text(scorecard_candidate.get("blockers")),
                *_list_text(outcome_candidate.get("blockers")),
            ]
        )
        replay_evidence = _mapping(memo.get("replay_backtest_evidence"))
        walk = _mapping(memo.get("walk_forward")) or _mapping(scorecard_candidate.get("walk_forward_progress"))
        stop_rules = _shadow_decision_queue_stop_rules(blockers=blockers, experiments=experiments)
        items.append(
            {
                "candidate_key": candidate_key,
                "candidate_family": memo.get("candidate_family") or scorecard_candidate.get("candidate_family"),
                "summary_zh": _shadow_decision_candidate_summary_zh(candidate_key, replay_evidence, walk, blockers),
                "current_readiness": _shadow_decision_queue_readiness(memo, scorecard_candidate, blockers),
                "evidence_status": _shadow_decision_queue_evidence_status(replay_evidence),
                "walk_forward_sufficiency": _shadow_decision_queue_walk_forward_sufficiency(
                    walk=walk,
                    scorecard_candidate=scorecard_candidate,
                    outcome_candidate=outcome_candidate,
                ),
                "experiment_status": _shadow_decision_queue_experiment_status(registry, experiments),
                "required_human_decision": _shadow_decision_queue_human_decision(
                    candidate_key=candidate_key,
                    human_decisions=human_decisions,
                ),
                "stop_rule": {
                    "status": "blocking" if any(rule.get("status") == "blocking" for rule in stop_rules) else "clear",
                    "rule_count": len(stop_rules),
                    "rule_keys": [
                        str(rule.get("rule_key"))
                        for rule in stop_rules
                        if rule.get("rule_key") is not None
                    ],
                    "rules": stop_rules,
                    "promotion_allowed": False,
                },
                "next_review_date": next_review_date,
                "promotion_boundary": _shadow_decision_queue_promotion_boundary(
                    release_gate=release_gate,
                    manual_boundaries=manual_boundaries,
                ),
                "source_status": {
                    "scorecard": scorecard.get("status"),
                    "walk_forward_outcomes": walk_forward_outcomes.get("status"),
                    "experiment_registry": registry.get("status"),
                },
                "artifact_only": True,
                "promotion_allowed": False,
            }
        )
    status = "empty" if not items else ("blocked" if any(item["stop_rule"]["status"] == "blocking" for item in items) else "manual_review_required")
    return {
        "queue_contract": SHADOW_DECISION_QUEUE_CONTRACT,
        "language": "zh-CN",
        "as_of_date": as_of_date,
        "status": status,
        "candidate_count": len(items),
        "blocked_candidate_count": sum(1 for item in items if item["stop_rule"]["status"] == "blocking"),
        "manual_review_required": True,
        "promotion_allowed": False,
        "artifact_only": True,
        "items": items,
    }


def _candidate_payloads_by_key(value: object) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("candidate_key")): item
        for item in _list_mapping(value)
        if item.get("candidate_key") is not None
    }


def _shadow_decision_raw_registry_experiments_by_candidate(
    registry: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    payload = _mapping(registry.get("payload"))
    result: dict[str, list[dict[str, Any]]] = {}
    for experiment in _list_mapping(payload.get("experiments")):
        key = _optional_text(experiment.get("candidate_key"))
        if key:
            result.setdefault(key, []).append(experiment)
    return result


def _shadow_decision_queue_readiness(
    memo: Mapping[str, Any],
    scorecard_candidate: Mapping[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    status = (
        _optional_text(scorecard_candidate.get("promotion_readiness"))
        or _optional_text(memo.get("review_status"))
        or "blocked"
    )
    return {
        "status": status,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "summary_zh": "候选仍需人工复核；review_ready 也不等于批准。"
        if status == "review_ready"
        else "候选当前保持阻断，先处理证据、样本、实验或人工边界。",
        "promotion_allowed": False,
    }


def _shadow_decision_queue_evidence_status(replay_evidence: Mapping[str, Any]) -> dict[str, Any]:
    status = _optional_text(replay_evidence.get("status")) or "missing"
    return {
        "status": status,
        "accepted": status == "accepted",
        "sample_size": replay_evidence.get("sample_size"),
        "required_sample_size": replay_evidence.get("required_sample_size"),
        "artifact_path": replay_evidence.get("artifact_path"),
        "blockers": _list_text(replay_evidence.get("blockers")),
        "advisory_only": True,
        "promotion_allowed": False,
    }


def _shadow_decision_queue_walk_forward_sufficiency(
    *,
    walk: Mapping[str, Any],
    scorecard_candidate: Mapping[str, Any],
    outcome_candidate: Mapping[str, Any],
) -> dict[str, Any]:
    required_days = _int_value(
        walk.get("required_days"),
        _int_value(scorecard_candidate.get("required_sample_size"), DEFAULT_REQUIRED_SAMPLE_SIZE),
    )
    observed_days = _int_value(
        walk.get("days"),
        _int_value(
            walk.get("evaluable_signal_days"),
            _int_value(
                scorecard_candidate.get("walk_forward_days"),
                _int_value(outcome_candidate.get("complete_count"), 0),
            ),
        ),
    )
    walk_status = (
        _optional_text(walk.get("status"))
        or _optional_text(scorecard_candidate.get("walk_forward_status"))
        or _optional_text(outcome_candidate.get("status"))
        or "unknown"
    )
    sufficient = observed_days >= required_days and walk_status in {"complete", "available", "observing"}
    return {
        "status": "sufficient" if sufficient else "insufficient",
        "walk_forward_status": walk_status,
        "observed_days": observed_days,
        "required_days": required_days,
        "outcome_status": outcome_candidate.get("status"),
        "promotion_allowed": False,
    }


def _shadow_decision_queue_experiment_status(
    registry: Mapping[str, Any],
    experiments: list[dict[str, Any]],
) -> dict[str, Any]:
    blocking_stop_rules = [
        rule
        for experiment in experiments
        for rule in _list_mapping(experiment.get("stop_rules"))
        if rule.get("status") == "blocking"
    ]
    if experiments:
        status = "registered"
    elif registry.get("status") == "missing":
        status = "missing_registry"
    else:
        status = "not_scheduled"
    return {
        "status": status,
        "experiment_count": len(experiments),
        "experiment_keys": [
            str(experiment.get("experiment_key"))
            for experiment in experiments
            if experiment.get("experiment_key") is not None
        ],
        "blocking_stop_rule_count": len(blocking_stop_rules),
        "promotion_allowed": False,
    }


def _shadow_decision_queue_human_decision(
    *,
    candidate_key: str,
    human_decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    decision_keys = [
        str(decision.get("decision_key"))
        for decision in human_decisions
        if decision.get("decision_key") is not None
    ]
    return {
        "decision_key": f"manual_shadow_decision_required:{candidate_key}",
        "source_decision_keys": decision_keys
        or ["manual_promotion_approval_required", "future_strategy_version_task_required"],
        "status": "required",
        "decision_zh": "人工只能决定是否进入后续独立复核/补证据任务；本队列不批准晋升或交易。",
        "manual_promotion_approval_required": True,
        "future_strategy_version_task_required": True,
        "promotion_allowed": False,
    }


def _shadow_decision_queue_stop_rules(
    *,
    blockers: list[str],
    experiments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rules = [
        {
            "rule_key": str(rule.get("rule_key") or rule.get("trigger") or "registry_stop_rule"),
            "status": str(rule.get("status") or "blocking"),
            "trigger": rule.get("trigger"),
        }
        for experiment in experiments
        for rule in _list_mapping(experiment.get("stop_rules"))
    ]
    if not rules:
        rules = [
            {
                "rule_key": f"blocker:{blocker}",
                "status": "blocking",
                "trigger": blocker,
            }
            for blocker in blockers
        ]
    rules.append(
        {
            "rule_key": "manual_promotion_approval_required",
            "status": "blocking",
            "trigger": "manual approval must happen in a separate future strategy-version task",
        }
    )
    return _dedupe_stop_rules(rules)


def _dedupe_stop_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for rule in rules:
        key = str(rule.get("rule_key") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append({**rule, "promotion_allowed": False})
    return result


def _shadow_decision_queue_promotion_boundary(
    *,
    release_gate: Mapping[str, Any],
    manual_boundaries: Mapping[str, Any],
) -> dict[str, Any]:
    blocked_targets = _unique_texts(
        [
            *_list_text(release_gate.get("blocked_mutation_targets")),
            *_list_text(manual_boundaries.get("blocked_mutation_targets")),
        ]
    )
    if not blocked_targets:
        blocked_targets = [
            "active_cpb_params",
            "strategy_versions",
            "trade_plans",
            "trades",
            "positions",
            "paper_live_behavior",
            "broker_execution",
            "timer_state",
        ]
    return {
        "status": "blocked",
        "boundary_zh": "晋升、发版、交易、paper/live 行为和 timer 改动必须由单独批准任务处理；当前队列禁止。",
        "manual_promotion_approval_required": True,
        "future_strategy_version_task_required": True,
        "promotion_allowed": False,
        "paper_observation_allowed": False,
        "strategy_version_publication_allowed": False,
        "trade_state_writes_allowed": False,
        "broker_execution_allowed": False,
        "timer_mutation_allowed": False,
        "blocked_mutation_targets": blocked_targets,
    }


def _shadow_decision_walk_by_candidate(snapshot: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    walk_forward = _mapping(snapshot.get("walk_forward"))
    for item in _list_mapping(walk_forward.get("by_candidate")) + _list_mapping(walk_forward.get("summary")):
        key = _optional_text(item.get("candidate_key") or item.get("bucket"))
        if key:
            rows[key] = item
    for candidate in _list_mapping(snapshot.get("candidates")):
        key = _optional_text(candidate.get("candidate_key"))
        if key and key not in rows:
            rows[key] = _mapping(candidate.get("walk_forward"))
    return rows


def _shadow_decision_experiments_by_candidate(registry: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    payload = _mapping(registry.get("payload"))
    experiments = _list_mapping(payload.get("experiments")) or _list_mapping(payload.get("recommended_next_experiments"))
    result: dict[str, list[dict[str, Any]]] = {}
    for experiment in experiments:
        key = _optional_text(experiment.get("candidate_key"))
        if key:
            result.setdefault(key, []).append(_shadow_decision_experiment_payload(experiment, source="registry"))
    return result


def _shadow_decision_calibration_experiments(calibration: Mapping[str, Any], candidate_key: str) -> list[dict[str, Any]]:
    payload = _mapping(calibration.get("payload"))
    experiments = [
        item
        for item in _list_mapping(payload.get("recommended_next_experiments"))
        if str(item.get("candidate_key") or "") == candidate_key
    ]
    return [_shadow_decision_experiment_payload(item, source="calibration") for item in experiments]


def _shadow_decision_next_experiments(
    *,
    calibration: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> list[dict[str, Any]]:
    registry_payload = _mapping(registry.get("payload"))
    registry_experiments = _list_mapping(registry_payload.get("experiments"))
    if registry_experiments:
        return [_shadow_decision_experiment_payload(item, source="registry") for item in registry_experiments]
    calibration_payload = _mapping(calibration.get("payload"))
    experiments = _list_mapping(calibration_payload.get("recommended_next_experiments"))
    return [_shadow_decision_experiment_payload(item, source="calibration") for item in experiments]


def _shadow_decision_experiment_payload(experiment: Mapping[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "experiment_key": experiment.get("experiment_key") or experiment.get("key") or experiment.get("candidate_key"),
        "candidate_key": experiment.get("candidate_key"),
        "candidate_family": experiment.get("candidate_family"),
        "source": source,
        "next_step_zh": _shadow_decision_next_step_zh(experiment),
        "reason": experiment.get("reason"),
        "recommended_variant": experiment.get("recommended_variant"),
        "required_evidence": _list_text(experiment.get("required_evidence")),
        "stop_rules": _list_text(experiment.get("stop_rules")),
        "promotion_allowed": False,
        "artifact_only": True,
    }


def _shadow_decision_next_step_zh(experiment: Mapping[str, Any]) -> str:
    next_step = _optional_text(experiment.get("next_step"))
    if next_step:
        return next_step
    candidate_key = _optional_text(experiment.get("candidate_key")) or "候选"
    return f"{candidate_key} 继续补齐 replay/backtest 证据、样本和 frozen-CPB 对照后再进入人工复核。"


def _shadow_decision_calibration_blockers(candidate: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    for variant in _list_mapping(candidate.get("threshold_variant_results")):
        blockers.extend(_list_text(variant.get("blockers")))
    return _unique_texts(blockers)


def _shadow_decision_blockers(
    *,
    promotion: Mapping[str, Any],
    calibration: Mapping[str, Any],
    registry: Mapping[str, Any],
    candidate_memos: list[dict[str, Any]],
) -> list[str]:
    review_request = _mapping(promotion.get("review_request"))
    blockers = [
        *_list_text(review_request.get("blocking_reason")),
        *_list_text(promotion.get("artifact_error")),
        *_list_text(calibration.get("blockers")),
        *_list_text(registry.get("blockers")),
    ]
    for candidate in candidate_memos:
        blockers.extend(_list_text(candidate.get("blockers")))
    if registry.get("status") == "missing":
        blockers.append("shadow_strategy_experiment_registry_missing")
    return _unique_texts(blockers)


def _shadow_decision_blocked_mutation_targets(
    *,
    calibration: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> list[str]:
    targets = []
    for source in (calibration, registry):
        release_gate = _mapping(_mapping(source.get("payload")).get("release_gate"))
        targets.extend(_list_text(release_gate.get("blocked_mutation_targets")))
    return [f"禁止修改：{target}" for target in _unique_texts(targets)]


def _shadow_decision_evidence_items(
    *,
    promotion: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    calibration: Mapping[str, Any],
    registry: Mapping[str, Any],
    replay_summary: Mapping[str, Any],
) -> list[dict[str, Any]]:
    walk = _mapping(snapshot.get("walk_forward"))
    return [
        {
            "name": "promotion review request",
            "status": promotion.get("status") or _mapping(promotion.get("summary")).get("status") or "missing",
            "summary_zh": "人工评审请求只作为复核上下文，不是批准。",
            "artifact_path": promotion.get("artifact_path"),
        },
        {
            "name": "replay/backtest evidence",
            "status": "accepted" if _int_value(replay_summary.get("accepted_count"), 0) else "blocked",
            "summary_zh": (
                f"accepted {_int_value(replay_summary.get('accepted_count'), 0)} / "
                f"rejected {_int_value(replay_summary.get('rejected_count'), 0)} / "
                f"missing {_int_value(replay_summary.get('missing_count'), 0)}"
            ),
        },
        {
            "name": "walk-forward outcomes",
            "status": walk.get("status") or snapshot.get("status") or "missing",
            "summary_zh": (
                f"{_int_value(walk.get('evaluable_signal_days'), 0)}/"
                f"{_int_value(walk.get('required_days'), 0)} 个观察交易日；最新 outcome "
                f"{walk.get('latest_outcome_date') or '-'}"
            ),
        },
        {
            "name": "threshold calibration",
            "status": calibration.get("status") or "missing",
            "summary_zh": _shadow_decision_source_summary_zh(calibration, "calibration"),
            "artifact_path": calibration.get("artifact_path"),
        },
        {
            "name": "experiment registry",
            "status": registry.get("status") or "missing",
            "summary_zh": _shadow_decision_source_summary_zh(registry, "experiment registry"),
            "artifact_path": registry.get("artifact_path"),
        },
    ]


def _shadow_decision_source_summary_zh(source: Mapping[str, Any], label: str) -> str:
    if source.get("status") == "missing":
        return f"{label} artifact 未找到；不能据此放行晋升。"
    if source.get("status") == "invalid":
        return f"{label} artifact 无效；不能据此放行晋升。"
    summary = _mapping(source.get("summary"))
    count = summary.get("recommended_next_experiment_count") or summary.get("experiment_count")
    return f"{label} artifact 已读取；next experiments {count if count is not None else '-'}；仍为 artifact-only。"


def _shadow_decision_sections(
    *,
    candidate_overview: list[dict[str, Any]],
    decision_queue: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
    blockers: list[str],
    next_experiments: list[dict[str, Any]],
    human_decisions: list[dict[str, Any]],
    rollback_notes: list[str],
    safety: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "候选概览": {
            "summary_zh": f"当前纳入备忘录的 shadow 候选 {len(candidate_overview)} 个，全部保持人工复核边界。",
            "items": candidate_overview,
        },
        "决策队列": {
            "summary_zh": (
                f"当前决策队列 {len(decision_queue)} 个候选；队列只规范 readiness、证据、实验和回滚边界，"
                "不提供批准或交易动作。"
            ),
            "items": decision_queue,
        },
        "证据状态": {
            "summary_zh": "证据只用于判断下一步研究，不触发 approve、promote、trade、plan 或 timer。",
            "items": evidence_items,
        },
        "阻断原因": {
            "summary_zh": "存在任一 blocker 时不得进入策略发布或交易链路。",
            "items": blockers,
        },
        "下一步实验": {
            "summary_zh": "下一步只允许补证据、扩样本、重跑 artifact-only 实验。",
            "items": next_experiments,
        },
        "人工决策": {
            "summary_zh": "人工决策是后续复核任务输入，不是本备忘录内的批准动作。",
            "items": human_decisions,
        },
        "风险/回滚边界": {
            "summary_zh": "所有 active CPB、strategy_versions、trade state、paper/live 行为和 timers 必须保持不变。",
            "items": rollback_notes,
            "safety": dict(safety),
        },
    }


def _shadow_decision_candidate_summary_zh(
    candidate_key: str,
    evidence: Mapping[str, Any],
    walk: Mapping[str, Any],
    blockers: list[str],
) -> str:
    evidence_status = evidence.get("status") or "missing"
    walk_status = walk.get("status") or "unknown"
    return (
        f"{candidate_key}：replay/backtest={evidence_status}，walk-forward={walk_status}，"
        f"blockers={len(blockers)}；结论为继续人工复核/补证据，不允许晋升。"
    )


def _shadow_decision_conclusion_zh(
    *,
    status: str,
    review_ready_count: int,
    blocker_count: int,
    registry_status: str,
) -> str:
    if status == "blocked":
        return (
            f"当前仍为阻断：review_ready {review_ready_count} 个，blocker {blocker_count} 个，"
            f"experiment registry 状态 {registry_status}。"
        )
    return "证据可进入人工复核讨论，但本备忘录仍不批准晋升、交易或改参数。"


def _shadow_decision_memo_safety() -> dict[str, Any]:
    return {
        "read_only": True,
        "artifact_only": True,
        "memo_is_not_approval": True,
        "manual_review_required": True,
        "no_approve_controls": True,
        "no_promotion_controls": True,
        "no_trade_controls": True,
        "no_trade_plan_controls": True,
        "no_timer_controls": True,
        "promotion_allowed": False,
        "paper_observation_allowed": False,
        "trade_plan_allowed": False,
        "active_params_mutated": False,
        "wrote_strategy_version": False,
        "wrote_strategy_versions": False,
        "writes_trade_state": False,
        "writes_paper_live_behavior": False,
        "timer_mutated": False,
    }


def _promotion_dossier_artifact(
    snapshot: object,
    *,
    replay_evidence_by_candidate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    threshold_metadata = _promotion_threshold_metadata(snapshot)
    candidates = [
        _candidate_dossier(
            candidate,
            threshold_metadata,
            _mapping((replay_evidence_by_candidate or {}).get(str(candidate.get("candidate_key") or ""))),
        )
        for candidate in getattr(snapshot, "candidates", []) or []
        if isinstance(candidate, Mapping)
    ]
    review_ready_count = sum(1 for item in candidates if item.get("review_status") == "review_ready")
    blocked_count = len(candidates) - review_ready_count
    replay_summary = _replay_evidence_summary_from_payloads(
        [_mapping(candidate.get("replay_backtest_evidence")) for candidate in candidates]
    )
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
            "replay_backtest_evidence": replay_summary,
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
        "replay_backtest_evidence": {
            "required": True,
            "evidence_contract": SHADOW_REPLAY_BACKTEST_EVIDENCE_CONTRACT,
            "required_metrics": list(REQUIRED_REPLAY_BACKTEST_METRICS),
            "clears_blocker": REPLAY_BACKTEST_REQUIRED_BLOCKER,
            "advisory_only": True,
        },
    }


def _candidate_dossier(
    candidate: Mapping[str, Any],
    threshold_metadata: Mapping[str, Any],
    replay_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    walk = _mapping(candidate.get("walk_forward"))
    comparison = _mapping(candidate.get("comparison_vs_frozen_cpb"))
    replay_evidence_payload = _mapping(replay_evidence) or _missing_replay_evidence_payload(
        str(candidate.get("candidate_key") or "unknown"),
        _int_value(
            _mapping(threshold_metadata.get("minimum_sample")).get("required_days"),
            DEFAULT_REQUIRED_SAMPLE_SIZE,
        ),
    )
    blockers = apply_shadow_replay_backtest_evidence_to_blockers(
        _unique_texts(_list_text(candidate.get("blockers"))),
        replay_evidence_payload,
    )
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
        "replay_backtest_evidence": {
            "passed": replay_evidence_payload.get("status") == "accepted",
            "status": replay_evidence_payload.get("status") or "missing",
            "evidence_contract": replay_evidence_payload.get("evidence_contract"),
            "artifact_path": replay_evidence_payload.get("artifact_path"),
            "source_hash": replay_evidence_payload.get("source_hash"),
            "blockers": _list_text(replay_evidence_payload.get("blockers")),
            "advisory_only": True,
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
        "replay_backtest_evidence": replay_evidence_payload,
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
    replay_check = _mapping(checks.get("replay_backtest_evidence"))
    if not replay_check.get("passed"):
        status = str(replay_check.get("status") or "missing")
        reasons.append(
            "replay_backtest_evidence_missing"
            if status == "missing"
            else "replay_backtest_evidence_rejected"
        )
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
    replay = _mapping(summary.get("replay_backtest_evidence"))
    lines = [
        f"# Shadow Promotion Dossier {artifact.get('as_of_date') or ''}".rstrip(),
        "",
        f"- contract: {artifact.get('dossier_contract')}",
        "- review_ready is not approval",
        f"- candidates: {summary.get('candidate_count', 0)}",
        f"- review_ready: {summary.get('review_ready_count', 0)}",
        f"- blocked: {summary.get('blocked_count', 0)}",
        (
            "- replay_backtest_evidence: "
            f"accepted={replay.get('accepted_count', 0)} / "
            f"rejected={replay.get('rejected_count', 0)} / "
            f"missing={replay.get('missing_count', 0)}"
        ),
        "- promotion_allowed=false",
        "",
        "## Candidates",
    ]
    for candidate in _list_mapping(artifact.get("candidates")):
        reasons = ", ".join(_list_text(candidate.get("blocked_reasons"))) or "none"
        replay_status = _mapping(candidate.get("replay_backtest_evidence")).get("status") or "missing"
        lines.append(
            f"- {candidate.get('candidate_key')}: {candidate.get('review_status')} "
            f"(replay_backtest_evidence={replay_status}; blocked_reasons={reasons})"
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


def _promotion_review_request_artifact(
    *,
    source_dossier: Mapping[str, Any],
    source_dossier_path: str | None,
    source_dossier_review: object,
    source_dossier_status: str,
    source_dossier_error: str | None,
    as_of_date: str,
    reports_dir: Path,
) -> dict[str, Any]:
    artifact_root = reports_dir.parent
    source_dossier_artifact = _portable_artifact_paths(dict(source_dossier), artifact_root)
    source_dossier_summary = _mapping(source_dossier_artifact.get("summary"))
    source_dossier_release_gate = _mapping(source_dossier_artifact.get("release_gate"))
    source_dossier_candidates = _list_mapping(source_dossier_artifact.get("candidates"))
    threshold_metadata = _mapping(source_dossier_artifact.get("threshold_metadata"))
    minimum_sample = _mapping(threshold_metadata.get("minimum_sample"))
    replay_evidence_index = load_shadow_replay_backtest_evidence_index(
        reports_dir,
        as_of_date=as_of_date,
        candidate_required_samples=_candidate_required_samples(
            source_dossier_candidates,
            _int_value(minimum_sample.get("required_days"), DEFAULT_REQUIRED_SAMPLE_SIZE),
        ),
    )
    replay_evidence_index = _portable_artifact_paths(replay_evidence_index, artifact_root)
    review_ready_candidates = [
        str(candidate.get("candidate_key"))
        for candidate in source_dossier_candidates
        if candidate.get("review_status") == "review_ready" and candidate.get("candidate_key") is not None
    ]
    blocked_candidate_keys = [
        str(candidate.get("candidate_key"))
        for candidate in source_dossier_candidates
        if candidate.get("review_status") != "review_ready" and candidate.get("candidate_key") is not None
    ]
    candidate_count = _int_value(source_dossier_summary.get("candidate_count"), len(source_dossier_candidates))
    review_ready_count = _int_value(source_dossier_summary.get("review_ready_count"), len(review_ready_candidates))
    blocked_count = _int_value(source_dossier_summary.get("blocked_count"), len(blocked_candidate_keys))
    request_status = "review_ready" if review_ready_candidates else "blocked"
    if request_status == "review_ready":
        blocking_reason = None
    elif source_dossier_status == "missing":
        blocking_reason = "shadow_promotion_dossier_missing"
    elif source_dossier_status == "invalid":
        blocking_reason = "shadow_promotion_dossier_invalid"
    else:
        blocking_reason = "no_review_ready_candidates"
    required_human_decisions = _promotion_review_request_required_human_decisions(
        review_ready_candidates=review_ready_candidates,
        source_dossier_release_gate=source_dossier_release_gate,
        blocking_reason=blocking_reason,
    )
    required_replay_backtest_evidence = _promotion_review_request_required_replay_backtest_evidence(
        replay_evidence_index,
        source_dossier_candidates,
        source_dossier_status,
    )
    rollback_notes = _promotion_review_request_rollback_notes(source_dossier_release_gate)
    review_request = {
        "request_key": f"shadow-promotion-review-request:{as_of_date}",
        "request_status": request_status,
        "blocking_reason": blocking_reason,
        "required_human_decisions": required_human_decisions,
        "required_replay_backtest_evidence": required_replay_backtest_evidence,
        "rollback_notes": rollback_notes,
        "safety_notes": _promotion_review_request_safety_notes(),
        "review_ready_candidates": review_ready_candidates,
        "blocked_candidate_keys": blocked_candidate_keys,
    }
    summary = {
        "status": request_status,
        "candidate_count": candidate_count,
        "review_ready_count": review_ready_count,
        "blocked_count": blocked_count,
        "review_ready_candidate_keys": review_ready_candidates,
        "blocked_candidate_keys": blocked_candidate_keys,
        "review_ready_is_not_approval": True,
        "manual_review_required": True,
        "promotion_allowed": False,
        "source_dossier_status": source_dossier_status,
        "source_dossier_valid": bool(getattr(source_dossier_review, "valid", False)),
        "source_dossier_error": source_dossier_error,
        "replay_backtest_evidence": _mapping(replay_evidence_index.get("summary")),
    }
    source_dossier_review_payload = {
        "path": source_dossier_path,
        "exists": bool(getattr(source_dossier_review, "exists", False)),
        "valid": bool(getattr(source_dossier_review, "valid", False)),
        "artifact_type": getattr(source_dossier_review, "artifact_type", None),
        "dossier_contract": getattr(source_dossier_review, "dossier_contract", None)
        or source_dossier_artifact.get("dossier_contract")
        or SHADOW_PROMOTION_DOSSIER_CONTRACT,
        "candidate_count": _int_value(getattr(source_dossier_review, "candidate_count", None), candidate_count),
        "review_ready_count": _int_value(
            getattr(source_dossier_review, "review_ready_count", None),
            review_ready_count,
        ),
        "blocked_count": _int_value(getattr(source_dossier_review, "blocked_count", None), blocked_count),
        "review_ready_candidates": list(getattr(source_dossier_review, "review_ready_candidates", []) or review_ready_candidates),
        "promotion_allowed": bool(getattr(source_dossier_review, "promotion_allowed", False)),
        "error": getattr(source_dossier_review, "error", None),
    }
    artifact = {
        "artifact_type": "shadow_promotion_review_request",
        "review_request_contract": SHADOW_PROMOTION_REVIEW_REQUEST_CONTRACT,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of_date": as_of_date,
        "source_dossier_path": source_dossier_path,
        "source_dossier_contract": str(
            source_dossier_artifact.get("dossier_contract") or SHADOW_PROMOTION_DOSSIER_CONTRACT
        ),
        "source_dossier_review": source_dossier_review_payload,
        "source_dossier": source_dossier_artifact,
        "summary": summary,
        "review_request": review_request,
        "replay_backtest_evidence": replay_evidence_index,
        "safety": _promotion_review_request_safety(),
    }
    return artifact


def _promotion_review_artifact_with_current_replay_evidence(
    artifact: Mapping[str, Any],
    *,
    reports_dir: Path,
    artifact_root: Path,
) -> dict[str, Any]:
    refreshed = dict(artifact)
    as_of_date = _compact_history_date(_optional_text(refreshed.get("as_of_date")))
    source_dossier = _mapping(refreshed.get("source_dossier"))
    source_dossier_candidates = _list_mapping(source_dossier.get("candidates"))
    if as_of_date is None or not source_dossier_candidates:
        return refreshed

    threshold_metadata = _mapping(source_dossier.get("threshold_metadata"))
    minimum_sample = _mapping(threshold_metadata.get("minimum_sample"))
    replay_evidence_index = load_shadow_replay_backtest_evidence_index(
        reports_dir,
        as_of_date=as_of_date,
        candidate_required_samples=_candidate_required_samples(
            source_dossier_candidates,
            _int_value(minimum_sample.get("required_days"), DEFAULT_REQUIRED_SAMPLE_SIZE),
        ),
    )
    replay_evidence_index = _portable_artifact_paths(replay_evidence_index, artifact_root)

    summary = dict(_mapping(refreshed.get("summary")))
    review_request = dict(_mapping(refreshed.get("review_request")))
    source_dossier_status = str(summary.get("source_dossier_status") or "valid")
    summary["replay_backtest_evidence"] = _mapping(replay_evidence_index.get("summary"))
    review_request["required_replay_backtest_evidence"] = _promotion_review_request_required_replay_backtest_evidence(
        replay_evidence_index,
        source_dossier_candidates,
        source_dossier_status,
    )
    refreshed["summary"] = summary
    refreshed["review_request"] = review_request
    refreshed["replay_backtest_evidence"] = replay_evidence_index
    return refreshed


def _promotion_review_request_required_human_decisions(
    *,
    review_ready_candidates: list[str],
    source_dossier_release_gate: Mapping[str, Any],
    blocking_reason: str | None,
) -> list[dict[str, Any]]:
    decisions = [
        {
            "decision_key": "manual_promotion_approval_required",
            "required": True,
            "status": "required",
            "note": "review_ready is not approval; manual approval remains required before any follow-up.",
        },
        {
            "decision_key": "future_strategy_version_task_required",
            "required": True,
            "status": "required",
            "note": "Any follow-up must be a separate strategy-version review task and must not mutate active strategy state.",
        },
        {
            "decision_key": "candidate_selection",
            "required": bool(review_ready_candidates),
            "status": "pending" if review_ready_candidates else "blocked",
            "candidate_keys": review_ready_candidates,
            "note": (
                "Select the review-ready candidate(s) for a separate human review."
                if review_ready_candidates
                else "No candidate is review_ready, so promotion review should not proceed."
            ),
        },
    ]
    release_gate_blockers = _list_text(source_dossier_release_gate.get("blocked_mutation_targets"))
    if release_gate_blockers:
        decisions.append(
            {
                "decision_key": "rollback_scope_confirmation",
                "required": True,
                "status": "required",
                "blocked_mutation_targets": release_gate_blockers,
                "note": "Confirm that the blocked mutation targets remain unchanged during any follow-up work.",
            }
        )
    if blocking_reason and blocking_reason not in {"no_review_ready_candidates"}:
        decisions.append(
            {
                "decision_key": "blocking_reason_acknowledgement",
                "required": True,
                "status": "blocked",
                "note": blocking_reason,
            }
        )
    return decisions


def _promotion_review_request_required_replay_backtest_evidence(
    replay_evidence_index: Mapping[str, Any],
    source_dossier_candidates: list[dict[str, Any]],
    source_dossier_status: str,
) -> list[dict[str, Any]]:
    by_candidate = _mapping(replay_evidence_index.get("by_candidate"))
    payloads = [dict(payload) for _, payload in sorted(by_candidate.items(), key=lambda item: str(item[0])) if isinstance(payload, Mapping)]
    if payloads:
        return payloads
    if source_dossier_candidates:
        evidence: list[dict[str, Any]] = []
        for candidate in source_dossier_candidates:
            blockers = _list_text(_mapping(_mapping(candidate.get("readiness_checks")).get("blocker_clearance")).get("blockers"))
            evidence.append(
                {
                    "candidate_key": candidate.get("candidate_key"),
                    "status": "missing",
                    "evidence_contract": SHADOW_REPLAY_BACKTEST_EVIDENCE_CONTRACT,
                    "blockers": blockers or [REPLAY_BACKTEST_REQUIRED_BLOCKER],
                    "promotion_allowed": False,
                    "paper_observation_allowed": False,
                    "advisory_only": True,
                }
            )
        return evidence
    return [
        {
            "candidate_key": None,
            "status": "missing",
            "evidence_contract": SHADOW_REPLAY_BACKTEST_EVIDENCE_CONTRACT,
            "blockers": [REPLAY_BACKTEST_REQUIRED_BLOCKER],
            "promotion_allowed": False,
            "paper_observation_allowed": False,
            "advisory_only": True,
            "note": (
                "No candidate replay/backtest evidence is available because the source dossier "
                f"is {source_dossier_status}."
            ),
        }
    ]


def _promotion_review_request_rollback_notes(source_dossier_release_gate: Mapping[str, Any]) -> list[str]:
    blocked_targets = _list_text(source_dossier_release_gate.get("blocked_mutation_targets"))
    notes = [
        "review_ready is not approval",
        "keep active CPB params/hash unchanged",
        "do not create or update strategy_versions, trade_plans, trades, positions, paper/live behavior, broker execution, or timers",
    ]
    if blocked_targets:
        notes.append(f"blocked_mutation_targets={','.join(blocked_targets)}")
    return notes


def _promotion_review_request_safety() -> dict[str, Any]:
    return {
        "read_only": True,
        "artifact_only": True,
        "review_request_is_not_approval": True,
        "manual_review_required": True,
        "promotion_allowed": False,
        "active_params_mutated": False,
        "wrote_strategy_version": False,
        "wrote_strategy_versions": False,
        "writes_trade_state": False,
        "writes_paper_live_behavior": False,
        "timer_mutated": False,
    }


def _promotion_review_request_safety_notes() -> list[str]:
    return [
        "review_ready is not approval",
        "promotion_allowed=false",
        "manual review only; no active strategy, trade, or timer mutation",
    ]


def _promotion_review_request_markdown(artifact: Mapping[str, Any]) -> str:
    summary = _mapping(artifact.get("summary"))
    source_dossier = _mapping(artifact.get("source_dossier"))
    source_review = _mapping(artifact.get("source_dossier_review"))
    review_request = _mapping(artifact.get("review_request"))
    replay = _mapping(summary.get("replay_backtest_evidence"))
    lines = [
        f"# Shadow Promotion Review Request {artifact.get('as_of_date') or ''}".rstrip(),
        "",
        f"- contract: {artifact.get('review_request_contract')}",
        f"- source_dossier: {artifact.get('source_dossier_path') or 'missing'}",
        f"- source_dossier_status: {summary.get('source_dossier_status') or 'unknown'}",
        f"- status: {summary.get('status') or 'unknown'}",
        "- review_ready is not approval",
        f"- blocking_reason: {review_request.get('blocking_reason') or 'none'}",
        (
            "- replay_backtest_evidence: "
            f"accepted={replay.get('accepted_count', 0)} / "
            f"rejected={replay.get('rejected_count', 0)} / "
            f"missing={replay.get('missing_count', 0)}"
        ),
        "",
        "## Source Dossier",
        f"- candidates: {summary.get('candidate_count', 0)}",
        f"- review_ready: {summary.get('review_ready_count', 0)}",
        f"- blocked: {summary.get('blocked_count', 0)}",
        f"- valid: {str(bool(summary.get('source_dossier_valid', False))).lower()}",
        f"- review_ready_candidates: {', '.join(summary.get('review_ready_candidate_keys', [])) or 'none'}",
        "",
        "## Candidate Readiness",
    ]
    for candidate in _list_mapping(source_dossier.get("candidates")):
        blockers = ", ".join(
            _list_text(_mapping(_mapping(candidate.get("readiness_checks")).get("blocker_clearance")).get("blockers"))
        ) or "none"
        replay_status = _mapping(candidate.get("replay_backtest_evidence")).get("status") or "missing"
        lines.append(
            f"- {candidate.get('candidate_key')}: {candidate.get('review_status')} "
            f"(replay_backtest_evidence={replay_status}; blockers={blockers})"
        )
    if not _list_mapping(source_dossier.get("candidates")):
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Human Decisions",
        ]
    )
    for decision in _list_mapping(review_request.get("required_human_decisions")):
        note = decision.get("note") or "none"
        lines.append(
            f"- {decision.get('decision_key')}: {decision.get('status')} "
            f"(required={str(bool(decision.get('required', False))).lower()}; note={note})"
        )
    lines.extend(
        [
            "",
            "## Required Replay/Backtest Evidence",
        ]
    )
    for evidence in _list_mapping(review_request.get("required_replay_backtest_evidence")):
        blockers = ", ".join(_list_text(evidence.get("blockers"))) or "none"
        lines.append(
            f"- {evidence.get('candidate_key') or 'source'}: {evidence.get('status')} "
            f"(blockers={blockers})"
        )
    lines.extend(
        [
            "",
            "## Rollback / Safety",
        ]
    )
    for note in _list_text(review_request.get("rollback_notes")):
        lines.append(f"- {note}")
    for note in _list_text(review_request.get("safety_notes")):
        lines.append(f"- {note}")
    if source_review.get("error"):
        lines.extend(["", "## Source Dossier Review", f"- error: {source_review.get('error')}"])
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


def _shadow_promotion_dossier_placeholder(
    as_of_date: str,
    source_dossier_status: str,
    source_dossier_error: str | None,
) -> dict[str, Any]:
    artifact = dict(_empty_dossier(as_of_date).artifact)
    artifact["summary"] = {
        **_mapping(artifact.get("summary")),
        "status": "unavailable",
        "source_dossier_status": source_dossier_status,
    }
    artifact["release_gate"] = _promotion_release_gate({})
    artifact["source_artifacts"] = {}
    artifact["candidates"] = []
    if source_dossier_error:
        artifact["error"] = source_dossier_error
    return artifact


def _latest_shadow_promotion_dossier_path(reports_dir: Path, as_of_date: str | None) -> Path | None:
    candidates = [path for path in reports_dir.glob(DOSSIER_ARTIFACT_PATTERN) if path.is_file()]
    if as_of_date is not None:
        exact = [path for path in candidates if _artifact_date_from_name(path.name) == as_of_date]
        return sorted(exact, key=lambda path: (path.stat().st_mtime, path.name))[-1] if exact else None
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda path: (_artifact_date_from_name(path.name) or "", path.stat().st_mtime, path.name),
    )[-1]


def _latest_shadow_promotion_review_request_path(reports_dir: Path, as_of_date: str | None) -> Path | None:
    candidates = [path for path in reports_dir.glob(REVIEW_REQUEST_ARTIFACT_PATTERN) if path.is_file()]
    if as_of_date is not None:
        exact = [path for path in candidates if _review_request_date_from_name(path.name) == as_of_date]
        return sorted(exact, key=lambda path: (path.stat().st_mtime, path.name))[-1] if exact else None
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda path: (_review_request_date_from_name(path.name) or "", path.stat().st_mtime, path.name),
    )[-1]


def _artifact_date_from_name(name: str) -> str | None:
    prefix = "shadow_promotion_dossier_"
    suffix = ".json"
    if not name.startswith(prefix) or not name.endswith(suffix):
        return None
    candidate = name[len(prefix) : -len(suffix)]
    return candidate if len(candidate) == 8 and candidate.isdigit() else None


def _review_request_date_from_name(name: str) -> str | None:
    prefix = "shadow_promotion_review_request_"
    suffix = ".json"
    if not name.startswith(prefix) or not name.endswith(suffix):
        return None
    candidate = name[len(prefix) : -len(suffix)]
    return candidate if len(candidate) == 8 and candidate.isdigit() else None


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


def build_shadow_replay_backtest_source_hash(
    *,
    provider: str,
    candidate_key: str,
    start_date: str,
    end_date: str,
    sample_size: int,
    metrics: Mapping[str, Any],
) -> str:
    """Build the deterministic source hash used by shadow replay/backtest evidence files."""

    fingerprint = {
        "provider": provider,
        "candidate_key": candidate_key,
        "start_date": start_date,
        "end_date": end_date,
        "sample_size": int(sample_size),
        "metrics": {str(key): metrics[key] for key in sorted(metrics)},
    }
    canonical = json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def review_shadow_replay_backtest_evidence_artifact(
    artifact_path: str | Path,
    *,
    expected_candidate_key: str | None = None,
    expected_as_of_date: str | None = None,
    required_sample_size: int = DEFAULT_REQUIRED_SAMPLE_SIZE,
) -> ShadowReplayBacktestEvidenceReview:
    path = Path(artifact_path).expanduser()
    if not path.exists():
        return _missing_replay_evidence_review(
            expected_candidate_key or "unknown",
            required_sample_size,
            path=str(path),
            blockers=["shadow_replay_backtest_evidence_artifact_missing", REPLAY_BACKTEST_REQUIRED_BLOCKER],
        )
    artifact, load_error = _load_json_object(path)
    if load_error is not None:
        return ShadowReplayBacktestEvidenceReview(
            path=str(path),
            exists=True,
            valid=False,
            status="rejected",
            required_sample_size=required_sample_size,
            blockers=["shadow_replay_backtest_evidence_json_invalid", REPLAY_BACKTEST_REQUIRED_BLOCKER],
            error=load_error,
        )
    reviews = _review_shadow_replay_backtest_evidence_file(
        path,
        artifact,
        expected_as_of_date=expected_as_of_date,
        candidate_required_samples={expected_candidate_key: required_sample_size}
        if expected_candidate_key
        else {},
    )
    if expected_candidate_key is not None:
        matches = [review for review in reviews if review.candidate_key == expected_candidate_key]
        if matches:
            return _best_replay_evidence_review(matches)
        return ShadowReplayBacktestEvidenceReview(
            path=str(path),
            exists=True,
            valid=False,
            status="rejected",
            artifact_type=str(artifact.get("artifact_type")) if artifact.get("artifact_type") is not None else None,
            evidence_contract=(
                str(artifact.get("evidence_contract"))
                if artifact.get("evidence_contract") is not None
                else None
            ),
            candidate_key=expected_candidate_key,
            required_sample_size=required_sample_size,
            blockers=["shadow_replay_backtest_candidate_key_mismatch", REPLAY_BACKTEST_REQUIRED_BLOCKER],
            error="shadow replay/backtest evidence candidate key does not match.",
        )
    if reviews:
        return _best_replay_evidence_review(reviews)
    return ShadowReplayBacktestEvidenceReview(
        path=str(path),
        exists=True,
        valid=False,
        status="rejected",
        required_sample_size=required_sample_size,
        blockers=["shadow_replay_backtest_result_missing", REPLAY_BACKTEST_REQUIRED_BLOCKER],
        error="shadow replay/backtest evidence file contains no result rows.",
    )


def load_shadow_replay_backtest_evidence_index(
    reports_dir: Path,
    *,
    as_of_date: str | None,
    candidate_required_samples: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    expected_samples = {
        str(key): _int_value(value, DEFAULT_REQUIRED_SAMPLE_SIZE)
        for key, value in (candidate_required_samples or {}).items()
    }
    reviews: list[ShadowReplayBacktestEvidenceReview] = []
    orphaned: list[ShadowReplayBacktestEvidenceReview] = []
    for path in sorted(Path(reports_dir).glob(SHADOW_REPLAY_BACKTEST_EVIDENCE_PATTERN)):
        artifact, load_error = _load_json_object(path)
        if load_error is not None:
            orphaned.append(
                ShadowReplayBacktestEvidenceReview(
                    path=str(path),
                    exists=True,
                    valid=False,
                    status="rejected",
                    blockers=["shadow_replay_backtest_evidence_json_invalid", REPLAY_BACKTEST_REQUIRED_BLOCKER],
                    error=load_error,
                )
            )
            continue
        reviews.extend(
            _review_shadow_replay_backtest_evidence_file(
                path,
                artifact,
                expected_as_of_date=as_of_date,
                candidate_required_samples=expected_samples,
            )
        )

    by_candidate_reviews: dict[str, list[ShadowReplayBacktestEvidenceReview]] = {}
    for review in reviews:
        candidate_key = str(review.candidate_key or "").strip()
        if not candidate_key or (expected_samples and candidate_key not in expected_samples):
            orphaned.append(review)
            continue
        by_candidate_reviews.setdefault(candidate_key, []).append(review)

    by_candidate: dict[str, dict[str, Any]] = {}
    for candidate_key, required_sample in expected_samples.items():
        candidate_reviews = by_candidate_reviews.get(candidate_key, [])
        review = (
            _best_replay_evidence_review(candidate_reviews)
            if candidate_reviews
            else _missing_replay_evidence_review(candidate_key, required_sample)
        )
        by_candidate[candidate_key] = review.to_payload()

    if not expected_samples:
        for candidate_key, candidate_reviews in by_candidate_reviews.items():
            by_candidate[candidate_key] = _best_replay_evidence_review(candidate_reviews).to_payload()

    payloads = list(by_candidate.values())
    return {
        "by_candidate": by_candidate,
        "summary": _replay_evidence_summary_from_payloads(payloads),
        "orphaned": [review.to_payload() for review in orphaned],
        "source_file_count": len(list(Path(reports_dir).glob(SHADOW_REPLAY_BACKTEST_EVIDENCE_PATTERN))),
    }


def apply_shadow_replay_backtest_evidence_to_blockers(
    blockers: list[str],
    replay_evidence: Mapping[str, Any] | None,
) -> list[str]:
    evidence = _mapping(replay_evidence)
    status = str(evidence.get("status") or "missing")
    if status == "accepted":
        return _unique_texts([blocker for blocker in blockers if blocker not in REPLAY_BACKTEST_BLOCKERS])
    evidence_blockers = _list_text(evidence.get("blockers")) or [REPLAY_BACKTEST_REQUIRED_BLOCKER]
    return _unique_texts([*blockers, *evidence_blockers])


def _candidate_required_samples(candidates: list[Any], fallback_required_sample: int) -> dict[str, int]:
    required: dict[str, int] = {}
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_key = str(candidate.get("candidate_key") or "").strip()
        if not candidate_key:
            continue
        walk = _mapping(candidate.get("walk_forward"))
        required[candidate_key] = _int_value(walk.get("required_days"), fallback_required_sample)
    return required


def _review_shadow_replay_backtest_evidence_file(
    path: Path,
    artifact: Mapping[str, Any],
    *,
    expected_as_of_date: str | None,
    candidate_required_samples: Mapping[str, int],
) -> list[ShadowReplayBacktestEvidenceReview]:
    results = _shadow_replay_result_rows(artifact)
    if not results:
        return [
            ShadowReplayBacktestEvidenceReview(
                path=str(path),
                exists=True,
                valid=False,
                status="rejected",
                artifact_type=_optional_text(artifact.get("artifact_type")),
                evidence_contract=_optional_text(artifact.get("evidence_contract")),
                blockers=["shadow_replay_backtest_result_missing", REPLAY_BACKTEST_REQUIRED_BLOCKER],
                error="shadow replay/backtest evidence file contains no result rows.",
            )
        ]
    return [
        _review_shadow_replay_backtest_result(
            path,
            artifact,
            result,
            expected_as_of_date=expected_as_of_date,
            required_sample_size=_int_value(
                candidate_required_samples.get(str(result.get("candidate_key") or "")),
                DEFAULT_REQUIRED_SAMPLE_SIZE,
            ),
        )
        for result in results
    ]


def _review_shadow_replay_backtest_result(
    path: Path,
    artifact: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    expected_as_of_date: str | None,
    required_sample_size: int,
) -> ShadowReplayBacktestEvidenceReview:
    artifact_type = _optional_text(artifact.get("artifact_type"))
    evidence_contract = _optional_text(artifact.get("evidence_contract"))
    provider = _optional_text(result.get("provider")) or _optional_text(artifact.get("provider"))
    candidate_key = _optional_text(result.get("candidate_key"))
    as_of_date = _optional_text(result.get("as_of_date")) or _optional_text(artifact.get("as_of_date"))
    date_range = _mapping(result.get("date_range")) or _mapping(artifact.get("date_range"))
    start_date = _optional_text(result.get("start_date")) or _optional_text(date_range.get("start_date"))
    end_date = _optional_text(result.get("end_date")) or _optional_text(date_range.get("end_date"))
    metrics = _mapping(result.get("metrics")) or _mapping(result.get("outcome_metrics"))
    sample_size = _int_value(
        result.get("sample_size"),
        _int_value(result.get("n"), _int_value(metrics.get("sample_size"), 0)),
    )
    source_hash = _optional_text(result.get("source_hash")) or _optional_text(artifact.get("source_hash"))
    no_future_boundary = _mapping(result.get("no_future_boundary")) or _mapping(
        artifact.get("no_future_boundary")
    )
    safety = _mapping(artifact.get("safety"))
    safety.update(_mapping(result.get("safety")))

    blockers: list[str] = []
    if artifact_type != "shadow_replay_backtest_evidence":
        blockers.append("shadow_replay_backtest_evidence_type_invalid")
    if evidence_contract != SHADOW_REPLAY_BACKTEST_EVIDENCE_CONTRACT:
        blockers.append("shadow_replay_backtest_evidence_contract_invalid")
    if not provider:
        blockers.append("shadow_replay_backtest_provider_required")
    if not candidate_key:
        blockers.append("shadow_replay_backtest_candidate_key_missing")
    if not _is_compact_date(start_date) or not _is_compact_date(end_date) or str(start_date) > str(end_date):
        blockers.append("shadow_replay_backtest_date_range_invalid")
    if expected_as_of_date and _is_compact_date(end_date):
        if str(end_date) > str(expected_as_of_date):
            blockers.append("shadow_replay_backtest_no_future_boundary_failed")
        elif str(end_date) < str(expected_as_of_date):
            blockers.append("shadow_replay_backtest_evidence_stale")
    if sample_size < required_sample_size:
        blockers.append("shadow_replay_backtest_sample_size_insufficient")
    missing_metrics = [key for key in REQUIRED_REPLAY_BACKTEST_METRICS if metrics.get(key) in (None, "")]
    if missing_metrics:
        blockers.append("shadow_replay_backtest_metric_completeness_missing")
    boundary_blockers = _no_future_boundary_blockers(no_future_boundary, expected_as_of_date)
    blockers.extend(boundary_blockers)
    if _safety_reports_mutation(safety):
        blockers.append("shadow_replay_backtest_evidence_mutation_risk")

    expected_source_hash = None
    if provider and candidate_key and _is_compact_date(start_date) and _is_compact_date(end_date):
        expected_source_hash = build_shadow_replay_backtest_source_hash(
            provider=provider,
            candidate_key=candidate_key,
            start_date=str(start_date),
            end_date=str(end_date),
            sample_size=sample_size,
            metrics=metrics,
        )
    if not source_hash:
        blockers.append("shadow_replay_backtest_source_hash_required")
    elif expected_source_hash and source_hash != expected_source_hash:
        blockers.append("shadow_replay_backtest_source_hash_mismatch")

    blockers = _unique_texts(blockers)
    valid = not blockers
    status = "accepted" if valid else "rejected"
    return ShadowReplayBacktestEvidenceReview(
        path=str(path),
        exists=True,
        valid=valid,
        status=status,
        artifact_type=artifact_type,
        evidence_contract=evidence_contract,
        provider=provider,
        candidate_key=candidate_key,
        as_of_date=as_of_date,
        start_date=start_date,
        end_date=end_date,
        sample_size=sample_size,
        required_sample_size=required_sample_size,
        source_hash=source_hash,
        expected_source_hash=expected_source_hash,
        metrics=dict(metrics),
        no_future_boundary=dict(no_future_boundary),
        safety={
            **{key: bool(safety.get(key, False)) for key in FORBIDDEN_REPLAY_EVIDENCE_FLAGS},
            "read_only": True,
            "artifact_only": True,
            "advisory_only": True,
        },
        blockers=[] if valid else _unique_texts([*blockers, REPLAY_BACKTEST_REQUIRED_BLOCKER]),
        error=None if valid else "; ".join(blockers),
    )


def _shadow_replay_result_rows(artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    results = artifact.get("results")
    if isinstance(results, list):
        return [dict(item) for item in results if isinstance(item, Mapping)]
    if artifact.get("candidate_key") is not None:
        return [dict(artifact)]
    return []


def _missing_replay_evidence_payload(candidate_key: str, required_sample_size: int) -> dict[str, Any]:
    return _missing_replay_evidence_review(candidate_key, required_sample_size).to_payload()


def _missing_replay_evidence_review(
    candidate_key: str,
    required_sample_size: int,
    *,
    path: str | None = None,
    blockers: list[str] | None = None,
) -> ShadowReplayBacktestEvidenceReview:
    return ShadowReplayBacktestEvidenceReview(
        path=path,
        exists=path is not None,
        valid=False,
        status="missing",
        evidence_contract=SHADOW_REPLAY_BACKTEST_EVIDENCE_CONTRACT,
        candidate_key=candidate_key,
        required_sample_size=required_sample_size,
        blockers=blockers or [REPLAY_BACKTEST_REQUIRED_BLOCKER],
        error="validated shadow replay/backtest evidence artifact is required.",
    )


def _best_replay_evidence_review(
    reviews: list[ShadowReplayBacktestEvidenceReview],
) -> ShadowReplayBacktestEvidenceReview:
    return sorted(
        reviews,
        key=lambda review: (
            1 if review.valid else 0,
            str(review.end_date or ""),
            -len(review.blockers),
            str(review.path or ""),
        ),
        reverse=True,
    )[0]


def _replay_evidence_summary_from_payloads(payloads: list[Mapping[str, Any]]) -> dict[str, Any]:
    state_counts: dict[str, int] = {}
    for payload in payloads:
        status = str(payload.get("status") or "missing")
        state_counts[status] = state_counts.get(status, 0) + 1
    return {
        "evidence_contract": SHADOW_REPLAY_BACKTEST_EVIDENCE_CONTRACT,
        "candidate_count": len(payloads),
        "accepted_count": state_counts.get("accepted", 0),
        "rejected_count": state_counts.get("rejected", 0),
        "missing_count": state_counts.get("missing", 0),
        "state_counts": dict(sorted(state_counts.items())),
        "advisory_only": True,
        "promotion_allowed": False,
        "clears_only": [REPLAY_BACKTEST_REQUIRED_BLOCKER],
    }


def _no_future_boundary_blockers(boundary: Mapping[str, Any], expected_as_of_date: str | None) -> list[str]:
    blockers: list[str] = []
    if not boundary:
        return ["shadow_replay_backtest_no_future_boundary_missing"]
    if boundary.get("passed") is False:
        blockers.append("shadow_replay_backtest_no_future_boundary_failed")
    if expected_as_of_date:
        for key in ("max_input_date", "data_cutoff_date", "latest_market_date"):
            value = _optional_text(boundary.get(key))
            if _is_compact_date(value) and str(value) > str(expected_as_of_date):
                blockers.append("shadow_replay_backtest_no_future_boundary_failed")
    return _unique_texts(blockers)


def _safety_reports_mutation(safety: Mapping[str, Any]) -> bool:
    return any(bool(safety.get(key)) for key in FORBIDDEN_REPLAY_EVIDENCE_FLAGS)


def _load_json_object(
    path: Path,
    *,
    artifact_label: str = "shadow replay/backtest evidence artifact",
) -> tuple[dict[str, Any], str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"{artifact_label} is not valid JSON: {exc}"
    if not isinstance(value, dict):
        return {}, f"{artifact_label} must be a JSON object."
    return value, None


def _optional_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _is_compact_date(value: object) -> bool:
    text = str(value or "")
    return len(text) == 8 and text.isdigit()


def _scorecard_rows(
    snapshot: object,
    db_path: Path,
    raw_rows_by_candidate: dict[str, list[dict[str, Any]]] | None = None,
    *,
    replay_evidence_by_candidate: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    snapshot_as_of = getattr(snapshot, "as_of_date", None)
    candidates = getattr(snapshot, "candidates", []) or []
    rows = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_key = str(candidate.get("candidate_key") or "")
        raw_rows = (raw_rows_by_candidate or {}).get(candidate_key, [])
        row = _candidate_scorecard_row(
            candidate,
            snapshot,
            db_path,
            snapshot_as_of,
            raw_rows,
            _mapping((replay_evidence_by_candidate or {}).get(candidate_key)),
        )
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
    replay_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    walk = _mapping(candidate.get("walk_forward"))
    comparison = _mapping(candidate.get("comparison_vs_frozen_cpb"))
    required_sample = _int_value(walk.get("required_days"), _int_value(_mapping(getattr(snapshot, "walk_forward", {})).get("required_days"), 20))
    replay_evidence_payload = _mapping(replay_evidence) or _missing_replay_evidence_payload(
        str(candidate.get("candidate_key") or "unknown"),
        required_sample,
    )
    blockers = apply_shadow_replay_backtest_evidence_to_blockers(
        _unique_texts(_list_text(candidate.get("blockers"))),
        replay_evidence_payload,
    )
    raw_rows = raw_rows or []
    raw_market_metrics = _raw_market_outcome_metrics(db_path, raw_rows)
    market_data_gaps = _market_data_gaps(db_path, candidate, snapshot_as_of)
    if raw_market_metrics["missing_market_bar_count"]:
        market_data_gaps = _unique_texts([*market_data_gaps, "market_bars_missing"])
    evidence_gaps = _evidence_gaps(blockers)
    coverage_gaps = _coverage_gaps(walk, comparison, market_data_gaps)
    sample_size = _sample_size(walk, comparison)
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
            *_list_text(replay_evidence_payload.get("artifact_path")),
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
        "replay_backtest_evidence": replay_evidence_payload,
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


def _replay_evidence_counts_from_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    statuses = [
        str(_mapping(row.get("replay_backtest_evidence")).get("status") or "missing")
        for row in rows
    ]
    return {
        "replay_backtest_evidence_accepted_count": statuses.count("accepted"),
        "replay_backtest_evidence_rejected_count": statuses.count("rejected"),
        "replay_backtest_evidence_missing_count": statuses.count("missing"),
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
    replay_counts: dict[str, int] = {}
    for row in rows:
        state = str(row.get("coverage_status") or row.get("sample_coverage_status") or "unknown")
        market_state = str(row.get("market_data_coverage_status") or "unknown")
        replay_state = str(_mapping(row.get("replay_backtest_evidence")).get("status") or "missing")
        state_counts[state] = state_counts.get(state, 0) + 1
        market_counts[market_state] = market_counts.get(market_state, 0) + 1
        replay_counts[replay_state] = replay_counts.get(replay_state, 0) + 1
    return {
        "status": "missing" if not rows else ("complete" if set(state_counts) == {"complete"} else "partial"),
        "state_counts": state_counts,
        "market_data_state_counts": market_counts,
        "replay_backtest_evidence_state_counts": replay_counts,
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
