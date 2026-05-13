"""Strategy evolution hypothesis service.

This service turns market-review observations into research hypotheses only.
It does not mutate active strategy parameters, trade plans, positions, or
portfolio ledger state.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from pgc_trading.config import Paths
from pgc_trading.market.calendar import is_yyyymmdd
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult, ServiceWarning
from pgc_trading.services.strategy_hypothesis_backtest_service import (
    StrategyHypothesisBacktestArtifactReview,
    review_strategy_hypothesis_backtest_artifact,
)
from pgc_trading.storage.database import connect


VALID_HYPOTHESIS_STATUSES = {"proposed", "testing", "accepted", "rejected", "archived"}
VALID_PROPOSAL_REVIEW_DECISIONS = {"approve", "reject", "request_promotion"}
VALID_HYPOTHESIS_TRANSITIONS = {
    "proposed": {"proposed", "testing", "rejected", "archived"},
    "testing": {"testing", "accepted", "rejected", "archived"},
    "accepted": {"accepted", "archived"},
    "rejected": {"rejected", "archived"},
    "archived": {"archived"},
}
SECTOR_PERSISTENCE_THRESHOLD = 0.7
TOP_SECTOR_RANK_LIMIT = 5
SHADOW_RESEARCH_SOURCE = "m69_shadow_research"
SHADOW_RESEARCH_ARTIFACTS = {
    "shadow_review": "strategy_shadow_review_20260511.json",
    "shadow_backtest": "strategy_shadow_backtest_20260401_20260508.json",
    "preconfirm_watchlist": "preconfirm_watchlist_backtest.json",
    "dip_buy": "pgc_pullback_dip_buy.json",
}


@dataclass(frozen=True)
class ProposeStrategyHypothesesRequest:
    as_of_date: str


@dataclass(frozen=True)
class ListStrategyHypothesesRequest:
    status: str | None = None
    as_of_date: str | None = None
    limit: int | None = None


@dataclass(frozen=True)
class EvaluateStrategyHypothesesRequest:
    status: str | None = None
    as_of_date: str | None = None
    limit: int | None = 100


@dataclass(frozen=True)
class RegisterShadowStrategyCandidatesRequest:
    as_of_date: str
    shadow_review_artifact_path: str | None = None
    shadow_backtest_artifact_path: str | None = None
    preconfirm_watchlist_artifact_path: str | None = None
    dip_buy_artifact_path: str | None = None


@dataclass(frozen=True)
class MarkStrategyHypothesisRequest:
    hypothesis_id: int
    status: str
    review_note: str | None = None
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    backtest_artifact_path: str | None = None


@dataclass(frozen=True)
class CreateStrategyVersionProposalRequest:
    hypothesis_id: int
    output_path: str | None = None


@dataclass(frozen=True)
class CreateStrategyVersionProposalReviewRequest:
    hypothesis_id: int
    decision: str
    review_note: str | None = None
    proposal_artifact_path: str | None = None
    output_path: str | None = None


@dataclass(frozen=True)
class StrategyHypothesis:
    as_of_date: str
    hypothesis_type: str
    title: str
    rationale: str
    evidence: dict[str, Any]
    proposed_change: dict[str, Any]
    status: str = "proposed"
    hypothesis_id: int | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class ProposeStrategyHypothesesResult:
    as_of_date: str
    generated_count: int
    would_insert_count: int
    inserted_count: int
    skipped_existing_count: int
    hypotheses: list[StrategyHypothesis] = field(default_factory=list)


@dataclass(frozen=True)
class RegisterShadowStrategyCandidatesResult:
    as_of_date: str
    generated_count: int
    would_insert_count: int
    inserted_count: int
    skipped_existing_count: int
    artifact_paths: dict[str, str] = field(default_factory=dict)
    comparison_summary: dict[str, Any] = field(default_factory=dict)
    hypotheses: list[StrategyHypothesis] = field(default_factory=list)


@dataclass(frozen=True)
class ListStrategyHypothesesResult:
    hypotheses: list[StrategyHypothesis] = field(default_factory=list)


@dataclass(frozen=True)
class StrategyHypothesisEvaluation:
    hypothesis: StrategyHypothesis
    evidence_ids: list[str] = field(default_factory=list)
    backtest_artifacts: list[StrategyHypothesisBacktestArtifactReview] = field(default_factory=list)
    strategy_version_proposals: list["StrategyVersionProposalArtifactReview"] = field(default_factory=list)
    strategy_version_proposal_reviews: list["StrategyVersionProposalReviewArtifactReview"] = field(default_factory=list)
    validation_events: list[dict[str, Any]] = field(default_factory=list)
    acceptance_gate: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)
    shadow_comparison: dict[str, Any] = field(default_factory=dict)
    paper_observation_gate: dict[str, Any] = field(default_factory=dict)
    strategy_version_gate: dict[str, Any] = field(default_factory=dict)
    next_action: str = "review"
    next_action_label: str = "Review hypothesis."
    strategy_version_task: dict[str, Any] | None = None


@dataclass(frozen=True)
class StrategyHypothesisEvaluationWorkbenchResult:
    hypotheses: list[StrategyHypothesisEvaluation] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarkStrategyHypothesisResult:
    hypothesis: StrategyHypothesis
    previous_status: str
    operator: str | None = None
    review_note: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    backtest_artifact_paths: list[str] = field(default_factory=list)
    strategy_version_task_required: bool = False
    strategy_version_task: dict[str, Any] | None = None


@dataclass(frozen=True)
class StrategyVersionProposalArtifactReview:
    path: str
    exists: bool
    valid: bool
    artifact_type: str | None = None
    hypothesis_id: int | None = None
    hypothesis_matches: bool = False
    proposal_key: str | None = None
    strategy_version_task_key: str | None = None
    candidate_strategy_version: str | None = None
    active_params_mutated: bool | None = None
    wrote_strategy_versions: bool | None = None
    writes_trade_state: bool | None = None
    writes_paper_live_behavior: bool | None = None
    timer_mutated: bool | None = None
    error: str | None = None


@dataclass(frozen=True)
class StrategyVersionProposalReviewArtifactReview:
    path: str
    exists: bool
    valid: bool
    artifact_type: str | None = None
    hypothesis_id: int | None = None
    hypothesis_matches: bool = False
    proposal_key: str | None = None
    proposal_matches: bool = False
    review_key: str | None = None
    decision: str | None = None
    promotion_request_key: str | None = None
    active_params_mutated: bool | None = None
    wrote_strategy_versions: bool | None = None
    writes_trade_state: bool | None = None
    writes_paper_live_behavior: bool | None = None
    timer_mutated: bool | None = None
    error: str | None = None


@dataclass(frozen=True)
class ShadowPromotionDossierArtifactReview:
    path: str
    exists: bool
    valid: bool
    artifact_type: str | None = None
    dossier_contract: str | None = None
    candidate_count: int = 0
    review_ready_count: int = 0
    blocked_count: int = 0
    review_ready_candidates: list[str] = field(default_factory=list)
    replay_backtest_evidence_accepted_count: int = 0
    replay_backtest_evidence_rejected_count: int = 0
    replay_backtest_evidence_missing_count: int = 0
    replay_backtest_evidence_advisory_only: bool = True
    active_params_mutated: bool | None = None
    wrote_strategy_version: bool | None = None
    wrote_strategy_versions: bool | None = None
    writes_trade_state: bool | None = None
    writes_paper_live_behavior: bool | None = None
    timer_mutated: bool | None = None
    promotion_allowed: bool | None = None
    error: str | None = None


@dataclass(frozen=True)
class ShadowPromotionReviewRequestArtifactReview:
    path: str
    exists: bool
    valid: bool
    artifact_type: str | None = None
    review_request_contract: str | None = None
    source_dossier_contract: str | None = None
    candidate_count: int = 0
    review_ready_count: int = 0
    blocked_count: int = 0
    review_ready_candidates: list[str] = field(default_factory=list)
    blocked_candidate_keys: list[str] = field(default_factory=list)
    blocking_reason: str | None = None
    required_human_decisions_count: int = 0
    required_replay_backtest_evidence_count: int = 0
    review_ready_is_not_approval: bool | None = None
    manual_review_required: bool | None = None
    promotion_allowed: bool | None = None
    active_params_mutated: bool | None = None
    wrote_strategy_version: bool | None = None
    wrote_strategy_versions: bool | None = None
    writes_trade_state: bool | None = None
    writes_paper_live_behavior: bool | None = None
    timer_mutated: bool | None = None
    error: str | None = None


@dataclass(frozen=True)
class CreateStrategyVersionProposalResult:
    hypothesis_id: int | None = None
    hypothesis_status: str | None = None
    would_write_artifact: bool = False
    wrote_artifact: bool = False
    artifact_path: str | None = None
    proposal_key: str | None = None
    strategy_version_task_key: str | None = None
    active_params_mutated: bool = False
    wrote_strategy_version: bool = False
    writes_trade_state: bool = False
    writes_paper_live_behavior: bool = False
    timer_mutated: bool = False
    recorded_hypothesis_validation: bool = False
    validation_evidence_ids: list[str] = field(default_factory=list)
    backtest_artifact_paths: list[str] = field(default_factory=list)
    artifact: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CreateStrategyVersionProposalReviewResult:
    hypothesis_id: int | None = None
    hypothesis_status: str | None = None
    decision: str | None = None
    would_write_artifact: bool = False
    wrote_artifact: bool = False
    artifact_path: str | None = None
    proposal_artifact_path: str | None = None
    proposal_key: str | None = None
    review_key: str | None = None
    promotion_request_key: str | None = None
    active_params_mutated: bool = False
    wrote_strategy_version: bool = False
    writes_trade_state: bool = False
    writes_paper_live_behavior: bool = False
    timer_mutated: bool = False
    recorded_hypothesis_validation: bool = False
    artifact: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _MarketObservations:
    run_id: int | None
    regime: sqlite3.Row | None
    persistent_sectors: list[sqlite3.Row]
    leader_rows: list[sqlite3.Row]
    negative_news_rows: list[sqlite3.Row]
    conflicted_plan_rows: list[sqlite3.Row]


@dataclass(frozen=True)
class _ShadowResearchArtifacts:
    shadow_review_path: Path
    shadow_review: dict[str, Any]
    shadow_backtest_path: Path
    shadow_backtest: dict[str, Any]
    preconfirm_watchlist_path: Path
    preconfirm_watchlist: dict[str, Any]
    dip_buy_path: Path
    dip_buy: dict[str, Any]

    @property
    def paths(self) -> dict[str, str]:
        return {
            "shadow_review": str(self.shadow_review_path),
            "shadow_backtest": str(self.shadow_backtest_path),
            "preconfirm_watchlist": str(self.preconfirm_watchlist_path),
            "dip_buy": str(self.dip_buy_path),
        }


class StrategyEvolutionService:
    """Generate, list, and update controlled strategy hypotheses."""

    def __init__(self, db_path: Path | None = None, reports_dir: Path | None = None):
        self.db_path = db_path or Paths().db_path
        self.reports_dir = reports_dir or Paths().reports_dir

    def propose_hypotheses(
        self,
        request: ProposeStrategyHypothesesRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ProposeStrategyHypothesesResult]:
        validation_errors = _validate_propose_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=ProposeStrategyHypothesesResult(
                    as_of_date=request.as_of_date,
                    generated_count=0,
                    would_insert_count=0,
                    inserted_count=0,
                    skipped_existing_count=0,
                ),
                errors=validation_errors,
            )

        with connect(self.db_path) as conn:
            observations = _load_market_observations(conn, request.as_of_date)
            generated = _generate_hypotheses(request.as_of_date, observations)
            new_hypotheses = [item for item in generated if _find_existing_hypothesis_id(conn, item) is None]
            skipped_existing_count = len(generated) - len(new_hypotheses)

            if not generated:
                return ServiceResult(
                    status="skipped",
                    request_id=ctx.request_id,
                    data=ProposeStrategyHypothesesResult(
                        as_of_date=request.as_of_date,
                        generated_count=0,
                        would_insert_count=0,
                        inserted_count=0,
                        skipped_existing_count=0,
                        hypotheses=[],
                    ),
                    warnings=[
                        ServiceWarning(
                            code="NO_MARKET_REVIEW_OBSERVATIONS",
                            message=f"No strategy-evolution hypotheses were generated for {request.as_of_date}.",
                        )
                    ],
                    lineage={"as_of_date": request.as_of_date, "market_review_run_id": observations.run_id},
                )

            if ctx.dry_run:
                return ServiceResult(
                    status="success",
                    request_id=ctx.request_id,
                    data=ProposeStrategyHypothesesResult(
                        as_of_date=request.as_of_date,
                        generated_count=len(generated),
                        would_insert_count=len(new_hypotheses),
                        inserted_count=0,
                        skipped_existing_count=skipped_existing_count,
                        hypotheses=generated,
                    ),
                    lineage={"as_of_date": request.as_of_date, "market_review_run_id": observations.run_id},
                )

            inserted: list[StrategyHypothesis] = []
            inserted_ids: list[int] = []
            conn.execute("BEGIN")
            try:
                for hypothesis in new_hypotheses:
                    inserted_hypothesis = _insert_hypothesis(conn, hypothesis)
                    inserted.append(inserted_hypothesis)
                    if inserted_hypothesis.hypothesis_id is not None:
                        inserted_ids.append(inserted_hypothesis.hypothesis_id)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=ProposeStrategyHypothesesResult(
                as_of_date=request.as_of_date,
                generated_count=len(generated),
                would_insert_count=len(new_hypotheses),
                inserted_count=len(inserted),
                skipped_existing_count=skipped_existing_count,
                hypotheses=inserted,
            ),
            created_ids={"strategy_hypotheses": inserted_ids},
            lineage={"as_of_date": request.as_of_date, "market_review_run_id": observations.run_id},
        )

    def register_shadow_candidates(
        self,
        request: RegisterShadowStrategyCandidatesRequest,
        ctx: RequestContext,
    ) -> ServiceResult[RegisterShadowStrategyCandidatesResult]:
        validation_errors = _validate_shadow_register_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=RegisterShadowStrategyCandidatesResult(
                    as_of_date=request.as_of_date,
                    generated_count=0,
                    would_insert_count=0,
                    inserted_count=0,
                    skipped_existing_count=0,
                ),
                errors=validation_errors,
            )

        artifacts_or_errors = _load_shadow_research_artifacts(request, self.reports_dir)
        if isinstance(artifacts_or_errors, list):
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=RegisterShadowStrategyCandidatesResult(
                    as_of_date=request.as_of_date,
                    generated_count=0,
                    would_insert_count=0,
                    inserted_count=0,
                    skipped_existing_count=0,
                ),
                errors=artifacts_or_errors,
            )
        artifacts = artifacts_or_errors
        generated = _generate_shadow_candidates(request.as_of_date, artifacts)
        comparison_summary = _shadow_register_summary(generated)

        with connect(self.db_path) as conn:
            new_hypotheses = [item for item in generated if _find_existing_hypothesis_id(conn, item) is None]
            skipped_existing_count = len(generated) - len(new_hypotheses)

            if ctx.dry_run:
                return ServiceResult(
                    status="success",
                    request_id=ctx.request_id,
                    data=RegisterShadowStrategyCandidatesResult(
                        as_of_date=request.as_of_date,
                        generated_count=len(generated),
                        would_insert_count=len(new_hypotheses),
                        inserted_count=0,
                        skipped_existing_count=skipped_existing_count,
                        artifact_paths=artifacts.paths,
                        comparison_summary=comparison_summary,
                        hypotheses=generated,
                    ),
                    lineage={"as_of_date": request.as_of_date, "source": SHADOW_RESEARCH_SOURCE},
                )

            inserted: list[StrategyHypothesis] = []
            inserted_ids: list[int] = []
            conn.execute("BEGIN")
            try:
                for hypothesis in new_hypotheses:
                    inserted_hypothesis = _insert_hypothesis(conn, hypothesis)
                    inserted.append(inserted_hypothesis)
                    if inserted_hypothesis.hypothesis_id is not None:
                        inserted_ids.append(inserted_hypothesis.hypothesis_id)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=RegisterShadowStrategyCandidatesResult(
                as_of_date=request.as_of_date,
                generated_count=len(generated),
                would_insert_count=len(new_hypotheses),
                inserted_count=len(inserted),
                skipped_existing_count=skipped_existing_count,
                artifact_paths=artifacts.paths,
                comparison_summary=comparison_summary,
                hypotheses=inserted,
            ),
            created_ids={"strategy_hypotheses": inserted_ids},
            lineage={"as_of_date": request.as_of_date, "source": SHADOW_RESEARCH_SOURCE},
        )

    def list_hypotheses(
        self,
        request: ListStrategyHypothesesRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ListStrategyHypothesesResult]:
        validation_errors = _validate_list_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=ListStrategyHypothesesResult(),
                errors=validation_errors,
            )

        with connect(self.db_path) as conn:
            hypotheses = _list_hypotheses(conn, request)

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=ListStrategyHypothesesResult(hypotheses=hypotheses),
            lineage={"as_of_date": request.as_of_date, "status": request.status},
        )

    def evaluate_hypotheses(
        self,
        request: EvaluateStrategyHypothesesRequest,
        ctx: RequestContext,
    ) -> ServiceResult[StrategyHypothesisEvaluationWorkbenchResult]:
        validation_errors = _validate_evaluate_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=StrategyHypothesisEvaluationWorkbenchResult(),
                errors=validation_errors,
            )

        list_request = ListStrategyHypothesesRequest(
            status=request.status,
            as_of_date=request.as_of_date,
            limit=request.limit,
        )
        with connect(self.db_path) as conn:
            hypotheses = _list_hypotheses(conn, list_request)

        evaluations = [_evaluate_hypothesis(hypothesis) for hypothesis in hypotheses]
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=StrategyHypothesisEvaluationWorkbenchResult(
                hypotheses=evaluations,
                summary=_evaluation_summary(evaluations),
                source={
                    "tables": ["strategy_hypotheses"],
                    "artifact_type": "strategy_hypothesis_backtest_request",
                    "proposal_artifact_type": "strategy_version_proposal",
                    "proposal_review_artifact_type": "strategy_version_proposal_review",
                    "promotion_request_artifact_type": "strategy_version_promotion_request",
                    "shadow_research_source": SHADOW_RESEARCH_SOURCE,
                    "shadow_artifacts": sorted(SHADOW_RESEARCH_ARTIFACTS.values()),
                    "as_of_date": request.as_of_date,
                    "status": request.status,
                    "limit": request.limit,
                },
                safety={
                    "read_only": True,
                    "active_params_mutated": False,
                    "writes_trade_state": False,
                    "writes_paper_live_behavior": False,
                    "timer_mutated": False,
                    "accepted_creates_separate_strategy_version_task": True,
                    "proposal_artifacts_only": True,
                    "proposal_review_artifacts_only": True,
                    "promotion_request_artifacts_only": True,
                    "shadow_candidates_artifact_only": True,
                    "shadow_candidates_require_blocker_clearance": True,
                    "shadow_candidates_cannot_create_paper_observation": True,
                },
            ),
            lineage={"as_of_date": request.as_of_date, "status": request.status},
        )

    def mark_hypothesis(
        self,
        request: MarkStrategyHypothesisRequest,
        ctx: RequestContext,
    ) -> ServiceResult[MarkStrategyHypothesisResult]:
        validation_errors = _validate_mark_request(request)
        if validation_errors:
            return ServiceResult(status="validation_failed", request_id=ctx.request_id, errors=validation_errors)

        with connect(self.db_path) as conn:
            existing = _get_hypothesis(conn, request.hypothesis_id)
            if existing is None:
                return ServiceResult(
                    status="validation_failed",
                    request_id=ctx.request_id,
                    errors=[
                        ServiceError(
                            code="HYPOTHESIS_NOT_FOUND",
                            message=f"strategy hypothesis id={request.hypothesis_id} was not found.",
                            entity_type="strategy_hypothesis",
                            entity_id=request.hypothesis_id,
                        )
                    ],
                )

            previous_status = existing.status
            transition_errors = _validate_status_transition(previous_status, request.status)
            evidence_ids = _merge_validation_values(
                _validation_values(existing.evidence, "evidence_ids"),
                _normalized_evidence_ids(request.evidence_ids),
            )
            backtest_artifact_paths = _merge_validation_values(
                _validation_values(existing.evidence, "backtest_artifacts"),
                _normalized_backtest_artifact_paths(request.backtest_artifact_path),
            )
            acceptance_errors = _validate_acceptance_gate(
                existing,
                request.status,
                evidence_ids,
                backtest_artifact_paths,
            )
            if transition_errors or acceptance_errors:
                return ServiceResult(
                    status="validation_failed",
                    request_id=ctx.request_id,
                    errors=transition_errors + acceptance_errors,
                    lineage={
                        "hypothesis_id": request.hypothesis_id,
                        "previous_status": previous_status,
                        "requested_status": request.status,
                    },
                )

            updated_evidence = _append_validation_event(
                evidence=existing.evidence,
                previous_status=previous_status,
                next_status=request.status,
                operator=ctx.operator,
                review_note=request.review_note,
                evidence_ids=evidence_ids,
                backtest_artifact_paths=backtest_artifact_paths,
            )
            strategy_version_task = (
                _future_strategy_version_task_payload(existing, evidence_ids, backtest_artifact_paths)
                if request.status == "accepted"
                else None
            )
            conn.execute(
                """
                UPDATE strategy_hypotheses
                SET status = ?, evidence_json = ?
                WHERE id = ?
                """,
                (request.status, _json_dumps(updated_evidence), request.hypothesis_id),
            )
            updated = _get_hypothesis(conn, request.hypothesis_id)
            if updated is None:
                raise RuntimeError(f"strategy hypothesis id={request.hypothesis_id} disappeared during update")

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=MarkStrategyHypothesisResult(
                hypothesis=updated,
                previous_status=previous_status,
                operator=ctx.operator,
                review_note=request.review_note,
                evidence_ids=evidence_ids,
                backtest_artifact_paths=backtest_artifact_paths,
                strategy_version_task_required=request.status == "accepted",
                strategy_version_task=strategy_version_task,
            ),
            lineage={
                "hypothesis_id": request.hypothesis_id,
                "previous_status": previous_status,
                "status": request.status,
                "operator": ctx.operator,
                "strategy_version_task_key": (
                    strategy_version_task.get("task_key") if strategy_version_task is not None else None
                ),
            },
        )

    def create_strategy_version_proposal(
        self,
        request: CreateStrategyVersionProposalRequest,
        ctx: RequestContext,
    ) -> ServiceResult[CreateStrategyVersionProposalResult]:
        validation_errors = _validate_strategy_version_proposal_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=CreateStrategyVersionProposalResult(),
                errors=validation_errors,
            )

        with connect(self.db_path) as conn:
            hypothesis = _get_hypothesis(conn, request.hypothesis_id)
            if hypothesis is None:
                return ServiceResult(
                    status="validation_failed",
                    request_id=ctx.request_id,
                    data=CreateStrategyVersionProposalResult(),
                    errors=[
                        ServiceError(
                            code="HYPOTHESIS_NOT_FOUND",
                            message=f"strategy hypothesis id={request.hypothesis_id} was not found.",
                            entity_type="strategy_hypothesis",
                            entity_id=request.hypothesis_id,
                        )
                    ],
                )

            evidence_ids = _validation_values(hypothesis.evidence, "evidence_ids")
            backtest_artifact_paths = _validation_values(hypothesis.evidence, "backtest_artifacts")
            artifact_reviews = [
                review_strategy_hypothesis_backtest_artifact(
                    artifact_path,
                    expected_hypothesis_id=request.hypothesis_id,
                )
                for artifact_path in backtest_artifact_paths
            ]
            proposal_errors = _validate_strategy_version_proposal_gate(
                hypothesis,
                evidence_ids,
                artifact_reviews,
            )
            if proposal_errors:
                return ServiceResult(
                    status="validation_failed",
                    request_id=ctx.request_id,
                    data=CreateStrategyVersionProposalResult(
                        hypothesis_id=request.hypothesis_id,
                        hypothesis_status=hypothesis.status,
                        validation_evidence_ids=evidence_ids,
                        backtest_artifact_paths=backtest_artifact_paths,
                    ),
                    errors=proposal_errors,
                    lineage={
                        "hypothesis_id": request.hypothesis_id,
                        "hypothesis_status": hypothesis.status,
                    },
                )

            current_strategy = _load_current_strategy(
                conn,
                str(hypothesis.proposed_change.get("strategy_id") or "cpb_6157"),
            )

        strategy_version_task = _future_strategy_version_task_payload(
            hypothesis,
            evidence_ids,
            backtest_artifact_paths,
        )
        artifact = _build_strategy_version_proposal_artifact(
            hypothesis=hypothesis,
            evidence_ids=evidence_ids,
            backtest_artifact_paths=backtest_artifact_paths,
            strategy_version_task=strategy_version_task,
            current_strategy=current_strategy,
            operator=ctx.operator,
        )
        artifact_path = self._strategy_version_proposal_artifact_path(request)
        proposal = artifact.get("proposal", {})
        proposal_key = proposal.get("proposal_key") if isinstance(proposal, dict) else None
        strategy_version_task_key = proposal.get("strategy_version_task_key") if isinstance(proposal, dict) else None

        if ctx.dry_run:
            return ServiceResult(
                status="success",
                request_id=ctx.request_id,
                data=CreateStrategyVersionProposalResult(
                    hypothesis_id=request.hypothesis_id,
                    hypothesis_status=hypothesis.status,
                    would_write_artifact=True,
                    wrote_artifact=False,
                    artifact_path=None,
                    proposal_key=str(proposal_key) if proposal_key is not None else None,
                    strategy_version_task_key=(
                        str(strategy_version_task_key) if strategy_version_task_key is not None else None
                    ),
                    active_params_mutated=False,
                    wrote_strategy_version=False,
                    writes_trade_state=False,
                    writes_paper_live_behavior=False,
                    timer_mutated=False,
                    recorded_hypothesis_validation=False,
                    validation_evidence_ids=evidence_ids,
                    backtest_artifact_paths=backtest_artifact_paths,
                    artifact=artifact,
                ),
                warnings=[
                    ServiceWarning(
                        code="STRATEGY_VERSION_PROPOSAL_DRY_RUN",
                        message=(
                            "Strategy-version proposal artifact was built in memory only; no file, strategy "
                            "version, params, or trade state was written."
                        ),
                    )
                ],
                lineage={
                    "hypothesis_id": request.hypothesis_id,
                    "hypothesis_status": hypothesis.status,
                    "artifact_path": str(artifact_path),
                },
            )

        self._write_strategy_version_proposal_artifact(artifact_path, artifact)
        _record_strategy_version_proposal_artifact(
            self.db_path,
            request.hypothesis_id,
            artifact_path,
            artifact,
            ctx.operator,
        )
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=CreateStrategyVersionProposalResult(
                hypothesis_id=request.hypothesis_id,
                hypothesis_status=hypothesis.status,
                would_write_artifact=True,
                wrote_artifact=True,
                artifact_path=str(artifact_path),
                proposal_key=str(proposal_key) if proposal_key is not None else None,
                strategy_version_task_key=(
                    str(strategy_version_task_key) if strategy_version_task_key is not None else None
                ),
                active_params_mutated=False,
                wrote_strategy_version=False,
                writes_trade_state=False,
                writes_paper_live_behavior=False,
                timer_mutated=False,
                recorded_hypothesis_validation=True,
                validation_evidence_ids=evidence_ids,
                backtest_artifact_paths=backtest_artifact_paths,
                artifact=artifact,
            ),
            created_ids={"strategy_version_proposal_artifact": request.hypothesis_id},
            lineage={
                "hypothesis_id": request.hypothesis_id,
                "hypothesis_status": hypothesis.status,
                "artifact_path": str(artifact_path),
            },
        )

    def create_strategy_version_proposal_review(
        self,
        request: CreateStrategyVersionProposalReviewRequest,
        ctx: RequestContext,
    ) -> ServiceResult[CreateStrategyVersionProposalReviewResult]:
        validation_errors = _validate_strategy_version_proposal_review_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=CreateStrategyVersionProposalReviewResult(decision=request.decision),
                errors=validation_errors,
            )

        with connect(self.db_path) as conn:
            hypothesis = _get_hypothesis(conn, request.hypothesis_id)
            if hypothesis is None:
                return ServiceResult(
                    status="validation_failed",
                    request_id=ctx.request_id,
                    data=CreateStrategyVersionProposalReviewResult(
                        hypothesis_id=request.hypothesis_id,
                        decision=request.decision,
                    ),
                    errors=[
                        ServiceError(
                            code="HYPOTHESIS_NOT_FOUND",
                            message=f"strategy hypothesis id={request.hypothesis_id} was not found.",
                            entity_type="strategy_hypothesis",
                            entity_id=request.hypothesis_id,
                        )
                    ],
                )

            proposal_artifact_path = _proposal_artifact_path_for_review(hypothesis, request.proposal_artifact_path)
            proposal_review = (
                review_strategy_version_proposal_artifact(
                    proposal_artifact_path,
                    expected_hypothesis_id=request.hypothesis_id,
                )
                if proposal_artifact_path is not None
                else None
            )
            review_errors = _validate_strategy_version_proposal_review_gate(
                hypothesis,
                request,
                proposal_review,
            )
            if review_errors:
                return ServiceResult(
                    status="validation_failed",
                    request_id=ctx.request_id,
                    data=CreateStrategyVersionProposalReviewResult(
                        hypothesis_id=request.hypothesis_id,
                        hypothesis_status=hypothesis.status,
                        decision=request.decision,
                        proposal_artifact_path=str(proposal_artifact_path) if proposal_artifact_path else None,
                    ),
                    errors=review_errors,
                    lineage={
                        "hypothesis_id": request.hypothesis_id,
                        "hypothesis_status": hypothesis.status,
                        "decision": request.decision,
                    },
                )

        if proposal_review is None:
            raise RuntimeError("proposal review gate returned no errors without a proposal artifact path")
        artifact = _build_strategy_version_proposal_review_artifact(
            hypothesis=hypothesis,
            proposal_review=proposal_review,
            decision=request.decision,
            review_note=request.review_note,
            operator=ctx.operator,
            idempotency_key=ctx.idempotency_key,
        )
        artifact_path = self._strategy_version_proposal_review_artifact_path(request)
        review = artifact.get("review", {})
        promotion_request = artifact.get("promotion_request", {})
        review_key = review.get("review_key") if isinstance(review, dict) else None
        proposal_key = review.get("proposal_key") if isinstance(review, dict) else None
        promotion_request_key = (
            promotion_request.get("request_key") if isinstance(promotion_request, dict) else None
        )

        if ctx.dry_run:
            return ServiceResult(
                status="success",
                request_id=ctx.request_id,
                data=CreateStrategyVersionProposalReviewResult(
                    hypothesis_id=request.hypothesis_id,
                    hypothesis_status=hypothesis.status,
                    decision=request.decision,
                    would_write_artifact=True,
                    wrote_artifact=False,
                    artifact_path=None,
                    proposal_artifact_path=proposal_review.path,
                    proposal_key=str(proposal_key) if proposal_key is not None else None,
                    review_key=str(review_key) if review_key is not None else None,
                    promotion_request_key=(
                        str(promotion_request_key) if promotion_request_key is not None else None
                    ),
                    active_params_mutated=False,
                    wrote_strategy_version=False,
                    writes_trade_state=False,
                    writes_paper_live_behavior=False,
                    timer_mutated=False,
                    recorded_hypothesis_validation=False,
                    artifact=artifact,
                ),
                warnings=[
                    ServiceWarning(
                        code="STRATEGY_VERSION_PROPOSAL_REVIEW_DRY_RUN",
                        message=(
                            "Strategy-version proposal review artifact was built in memory only; no file, "
                            "strategy version, params, or trade state was written."
                        ),
                    )
                ],
                lineage={
                    "hypothesis_id": request.hypothesis_id,
                    "hypothesis_status": hypothesis.status,
                    "decision": request.decision,
                    "artifact_path": str(artifact_path),
                },
            )

        self._write_strategy_version_proposal_review_artifact(artifact_path, artifact)
        _record_strategy_version_proposal_review_artifact(
            self.db_path,
            request.hypothesis_id,
            artifact_path,
            artifact,
            ctx.operator,
        )
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=CreateStrategyVersionProposalReviewResult(
                hypothesis_id=request.hypothesis_id,
                hypothesis_status=hypothesis.status,
                decision=request.decision,
                would_write_artifact=True,
                wrote_artifact=True,
                artifact_path=str(artifact_path),
                proposal_artifact_path=proposal_review.path,
                proposal_key=str(proposal_key) if proposal_key is not None else None,
                review_key=str(review_key) if review_key is not None else None,
                promotion_request_key=str(promotion_request_key) if promotion_request_key is not None else None,
                active_params_mutated=False,
                wrote_strategy_version=False,
                writes_trade_state=False,
                writes_paper_live_behavior=False,
                timer_mutated=False,
                recorded_hypothesis_validation=True,
                artifact=artifact,
            ),
            created_ids={"strategy_version_proposal_review_artifact": request.hypothesis_id},
            lineage={
                "hypothesis_id": request.hypothesis_id,
                "hypothesis_status": hypothesis.status,
                "decision": request.decision,
                "artifact_path": str(artifact_path),
            },
        )

    def _strategy_version_proposal_artifact_path(self, request: CreateStrategyVersionProposalRequest) -> Path:
        if request.output_path is not None:
            return Path(request.output_path).expanduser()
        return (
            self.reports_dir
            / "strategy_version_proposals"
            / f"hypothesis_{request.hypothesis_id}_strategy_version_proposal.json"
        )

    def _write_strategy_version_proposal_artifact(self, path: Path, artifact: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json_dumps(artifact) + "\n", encoding="utf-8")

    def _strategy_version_proposal_review_artifact_path(
        self,
        request: CreateStrategyVersionProposalReviewRequest,
    ) -> Path:
        if request.output_path is not None:
            return Path(request.output_path).expanduser()
        if request.decision == "request_promotion":
            return (
                self.reports_dir
                / "strategy_promotion_requests"
                / f"hypothesis_{request.hypothesis_id}_strategy_promotion_request.json"
            )
        return (
            self.reports_dir
            / "strategy_proposal_reviews"
            / f"hypothesis_{request.hypothesis_id}_strategy_proposal_{request.decision}.json"
        )

    def _write_strategy_version_proposal_review_artifact(self, path: Path, artifact: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json_dumps(artifact) + "\n", encoding="utf-8")


def _validate_propose_request(request: ProposeStrategyHypothesesRequest) -> list[ServiceError]:
    if not is_yyyymmdd(request.as_of_date):
        return [ServiceError(code="VALIDATION_ERROR", message="as_of_date must use YYYYMMDD format.")]
    return []


def _validate_list_request(request: ListStrategyHypothesesRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if request.status is not None and request.status not in VALID_HYPOTHESIS_STATUSES:
        errors.append(ServiceError(code="VALIDATION_ERROR", message=f"invalid hypothesis status: {request.status}"))
    if request.as_of_date is not None and not is_yyyymmdd(request.as_of_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="as_of_date must use YYYYMMDD format."))
    if request.limit is not None and request.limit < 1:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="limit must be greater than zero."))
    return errors


def _validate_evaluate_request(request: EvaluateStrategyHypothesesRequest) -> list[ServiceError]:
    return _validate_list_request(
        ListStrategyHypothesesRequest(
            status=request.status,
            as_of_date=request.as_of_date,
            limit=request.limit,
        )
    )


def _validate_shadow_register_request(request: RegisterShadowStrategyCandidatesRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not is_yyyymmdd(request.as_of_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="as_of_date must use YYYYMMDD format."))
    for label, value in [
        ("shadow_review_artifact_path", request.shadow_review_artifact_path),
        ("shadow_backtest_artifact_path", request.shadow_backtest_artifact_path),
        ("preconfirm_watchlist_artifact_path", request.preconfirm_watchlist_artifact_path),
        ("dip_buy_artifact_path", request.dip_buy_artifact_path),
    ]:
        if value is not None and not str(value).strip():
            errors.append(ServiceError(code="VALIDATION_ERROR", message=f"{label} must not be blank."))
    return errors


def _validate_mark_request(request: MarkStrategyHypothesisRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if request.hypothesis_id < 1:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="hypothesis_id must be greater than zero."))
    if request.status not in VALID_HYPOTHESIS_STATUSES:
        errors.append(ServiceError(code="VALIDATION_ERROR", message=f"invalid hypothesis status: {request.status}"))
    if request.review_note is not None and not request.review_note.strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="review_note must not be blank."))
    for evidence_id in request.evidence_ids:
        if not str(evidence_id).strip():
            errors.append(ServiceError(code="VALIDATION_ERROR", message="evidence_id must not be blank."))
    if request.backtest_artifact_path is not None and not str(request.backtest_artifact_path).strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="backtest_artifact_path must not be blank."))
    return errors


def _validate_strategy_version_proposal_request(
    request: CreateStrategyVersionProposalRequest,
) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if request.hypothesis_id < 1:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="hypothesis_id must be greater than zero."))
    if request.output_path is not None and not str(request.output_path).strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="output_path must not be blank."))
    return errors


def _validate_strategy_version_proposal_review_request(
    request: CreateStrategyVersionProposalReviewRequest,
) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if request.hypothesis_id < 1:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="hypothesis_id must be greater than zero."))
    if request.decision not in VALID_PROPOSAL_REVIEW_DECISIONS:
        errors.append(ServiceError(code="VALIDATION_ERROR", message=f"invalid proposal review decision: {request.decision}"))
    if request.review_note is not None and not request.review_note.strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="review_note must not be blank."))
    if request.proposal_artifact_path is not None and not str(request.proposal_artifact_path).strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="proposal_artifact_path must not be blank."))
    if request.output_path is not None and not str(request.output_path).strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="output_path must not be blank."))
    return errors


def _validate_status_transition(previous_status: str, next_status: str) -> list[ServiceError]:
    allowed = VALID_HYPOTHESIS_TRANSITIONS.get(previous_status, set())
    if next_status in allowed:
        return []
    return [
        ServiceError(
            code="INVALID_HYPOTHESIS_STATUS_TRANSITION",
            message=f"strategy hypothesis cannot move from {previous_status} to {next_status}.",
            entity_type="strategy_hypothesis",
        )
    ]


def _validate_acceptance_gate(
    hypothesis: StrategyHypothesis,
    next_status: str,
    evidence_ids: list[str],
    backtest_artifact_paths: list[str],
) -> list[ServiceError]:
    if next_status != "accepted":
        return []

    errors: list[ServiceError] = []
    if not evidence_ids:
        errors.append(
            ServiceError(
                code="ACCEPTED_REQUIRES_VALIDATION_EVIDENCE",
                message="accepted strategy hypotheses require at least one validation evidence id.",
                entity_type="strategy_hypothesis",
                entity_id=hypothesis.hypothesis_id,
            )
        )
    if not backtest_artifact_paths:
        errors.append(
            ServiceError(
                code="ACCEPTED_REQUIRES_BACKTEST_ARTIFACT",
                message="accepted strategy hypotheses require a replay/backtest request artifact.",
                entity_type="strategy_hypothesis",
                entity_id=hypothesis.hypothesis_id,
            )
        )
    for artifact_path in backtest_artifact_paths:
        errors.extend(_validate_backtest_artifact(hypothesis, artifact_path))
    return errors


def _validate_backtest_artifact(hypothesis: StrategyHypothesis, artifact_path: str) -> list[ServiceError]:
    path = Path(artifact_path).expanduser()
    if not path.exists():
        return [
            ServiceError(
                code="BACKTEST_ARTIFACT_NOT_FOUND",
                message=f"backtest artifact was not found: {path}",
                entity_type="strategy_hypothesis",
                entity_id=hypothesis.hypothesis_id,
            )
        ]
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [
            ServiceError(
                code="BACKTEST_ARTIFACT_INVALID",
                message=f"backtest artifact is not valid JSON: {exc}",
                entity_type="strategy_hypothesis",
                entity_id=hypothesis.hypothesis_id,
            )
        ]
    if not isinstance(artifact, dict) or artifact.get("artifact_type") != "strategy_hypothesis_backtest_request":
        return [
            ServiceError(
                code="BACKTEST_ARTIFACT_INVALID",
                message="backtest artifact must be a strategy_hypothesis_backtest_request artifact.",
                entity_type="strategy_hypothesis",
                entity_id=hypothesis.hypothesis_id,
            )
        ]
    artifact_hypothesis = artifact.get("hypothesis", {})
    artifact_hypothesis_id = artifact_hypothesis.get("id") if isinstance(artifact_hypothesis, dict) else None
    try:
        parsed_artifact_hypothesis_id = int(artifact_hypothesis_id or 0)
    except (TypeError, ValueError):
        parsed_artifact_hypothesis_id = 0
    if parsed_artifact_hypothesis_id != int(hypothesis.hypothesis_id or 0):
        return [
            ServiceError(
                code="BACKTEST_ARTIFACT_HYPOTHESIS_MISMATCH",
                message="backtest artifact hypothesis id does not match the requested hypothesis.",
                entity_type="strategy_hypothesis",
                entity_id=hypothesis.hypothesis_id,
            )
        ]
    return []


def _validate_strategy_version_proposal_gate(
    hypothesis: StrategyHypothesis,
    evidence_ids: list[str],
    artifact_reviews: list[StrategyHypothesisBacktestArtifactReview],
) -> list[ServiceError]:
    if hypothesis.status != "accepted":
        return [
            ServiceError(
                code="PROPOSAL_REQUIRES_ACCEPTED_HYPOTHESIS",
                message="strategy-version proposal artifacts can only be created from accepted hypotheses.",
                entity_type="strategy_hypothesis",
                entity_id=hypothesis.hypothesis_id,
            )
        ]
    acceptance_gate = _acceptance_gate_payload(hypothesis, evidence_ids, artifact_reviews)
    if not acceptance_gate.get("accepted_complete"):
        return [
            ServiceError(
                code="PROPOSAL_REQUIRES_ACCEPTANCE_GATE",
                message="strategy-version proposal requires validation evidence and valid replay/backtest artifacts.",
                entity_type="strategy_hypothesis",
                entity_id=hypothesis.hypothesis_id,
            )
        ]
    shadow_blockers = _shadow_strategy_version_blockers(hypothesis)
    if shadow_blockers:
        return [
            ServiceError(
                code="SHADOW_PROPOSAL_REQUIRES_BLOCKER_CLEARANCE",
                message=(
                    "shadow strategy candidates require explicit blocker clearance before any "
                    "strategy-version proposal artifact."
                ),
                entity_type="strategy_hypothesis",
                entity_id=hypothesis.hypothesis_id,
            )
        ]
    return []


def _validate_strategy_version_proposal_review_gate(
    hypothesis: StrategyHypothesis,
    request: CreateStrategyVersionProposalReviewRequest,
    proposal_review: StrategyVersionProposalArtifactReview | None,
) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if hypothesis.status != "accepted":
        errors.append(
            ServiceError(
                code="PROPOSAL_REVIEW_REQUIRES_ACCEPTED_HYPOTHESIS",
                message="strategy-version proposal reviews can only be created for accepted hypotheses.",
                entity_type="strategy_hypothesis",
                entity_id=hypothesis.hypothesis_id,
            )
        )
    if proposal_review is None:
        errors.append(
            ServiceError(
                code="PROPOSAL_REVIEW_REQUIRES_PROPOSAL_ARTIFACT",
                message="proposal review requires an explicit or recorded strategy_version_proposal artifact.",
                entity_type="strategy_hypothesis",
                entity_id=hypothesis.hypothesis_id,
            )
        )
        return errors
    if not proposal_review.exists:
        errors.append(
            ServiceError(
                code="PROPOSAL_ARTIFACT_NOT_FOUND",
                message=f"strategy-version proposal artifact was not found: {proposal_review.path}",
                entity_type="strategy_hypothesis",
                entity_id=hypothesis.hypothesis_id,
            )
        )
    if request.decision in {"approve", "request_promotion"} and not proposal_review.valid:
        errors.append(
            ServiceError(
                code="PROPOSAL_REVIEW_REQUIRES_VALID_PROPOSAL",
                message="approval and promotion requests require a valid artifact-only strategy-version proposal.",
                entity_type="strategy_hypothesis",
                entity_id=hypothesis.hypothesis_id,
            )
        )
    return errors


def _append_validation_event(
    *,
    evidence: dict[str, Any],
    previous_status: str,
    next_status: str,
    operator: str | None,
    review_note: str | None,
    evidence_ids: list[str],
    backtest_artifact_paths: list[str],
) -> dict[str, Any]:
    updated = dict(evidence)
    validation = _validation_payload(updated)
    validation["evidence_ids"] = evidence_ids
    validation["backtest_artifacts"] = backtest_artifact_paths

    events = validation.get("review_events")
    if not isinstance(events, list):
        events = []
    events.append(
        {
            "from_status": previous_status,
            "to_status": next_status,
            "operator": operator,
            "review_note": review_note,
            "evidence_ids": evidence_ids,
            "backtest_artifact_paths": backtest_artifact_paths,
            "created_at": _utc_timestamp(),
        }
    )
    validation["review_events"] = events
    updated["validation"] = validation
    return updated


def _future_strategy_version_task_payload(
    hypothesis: StrategyHypothesis,
    evidence_ids: list[str],
    backtest_artifact_paths: list[str],
) -> dict[str, Any]:
    hypothesis_id = int(hypothesis.hypothesis_id or 0)
    proposed_change = {
        **hypothesis.proposed_change,
        "mutates_active_params": False,
    }
    shadow_blockers = _shadow_strategy_version_blockers(hypothesis)
    return {
        "task_key": f"strategy-hypothesis:{hypothesis_id}:strategy-version",
        "task_type": "create_candidate_strategy_version",
        "status": "blocked" if shadow_blockers else "pending",
        "strategy_id": str(proposed_change.get("strategy_id") or "cpb_6157"),
        "hypothesis_id": hypothesis_id,
        "hypothesis_type": hypothesis.hypothesis_type,
        "title": hypothesis.title,
        "research_outcome_status": "accepted",
        "validation_evidence_ids": evidence_ids,
        "backtest_artifact_paths": backtest_artifact_paths,
        "proposal_artifact_required": True,
        "proposal_artifact_type": "strategy_version_proposal",
        "proposed_change": proposed_change,
        "shadow_candidate": _is_shadow_candidate(hypothesis),
        "strategy_version_proposal_blockers": shadow_blockers,
        "acceptance_rules": [
            "Generate a strategy-version proposal artifact before creating any strategy_version row.",
            "Create a new draft or candidate strategy_version row rather than mutating the active version.",
            "Attach replay/backtest evidence to the promotion review.",
            "Keep paper/live deployments on the current version until explicit promotion approval.",
            "Do not write trade plans, trades, positions, or timer state from this task.",
        ],
    }


def review_strategy_version_proposal_artifact(
    artifact_path: str | Path,
    *,
    expected_hypothesis_id: int | None = None,
) -> StrategyVersionProposalArtifactReview:
    path = Path(artifact_path).expanduser()
    if not path.exists():
        return StrategyVersionProposalArtifactReview(
            path=str(path),
            exists=False,
            valid=False,
            error="strategy-version proposal artifact was not found.",
        )
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return StrategyVersionProposalArtifactReview(
            path=str(path),
            exists=True,
            valid=False,
            error=f"strategy-version proposal artifact is not valid JSON: {exc}",
        )
    if not isinstance(artifact, dict):
        return StrategyVersionProposalArtifactReview(
            path=str(path),
            exists=True,
            valid=False,
            error="strategy-version proposal artifact must be a JSON object.",
        )

    artifact_type = artifact.get("artifact_type")
    artifact_hypothesis = artifact.get("hypothesis", {})
    artifact_hypothesis_id = artifact_hypothesis.get("id") if isinstance(artifact_hypothesis, dict) else None
    parsed_hypothesis_id = _optional_int(artifact_hypothesis_id)
    hypothesis_matches = (
        parsed_hypothesis_id is not None
        if expected_hypothesis_id is None
        else parsed_hypothesis_id == expected_hypothesis_id
    )
    proposal = artifact.get("proposal", {})
    safety = artifact.get("safety", {})
    active_params_mutated = safety.get("active_params_mutated") if isinstance(safety, dict) else None
    wrote_strategy_versions = safety.get("wrote_strategy_versions") if isinstance(safety, dict) else None
    writes_trade_state = safety.get("writes_trade_state") if isinstance(safety, dict) else None
    writes_paper_live_behavior = safety.get("writes_paper_live_behavior") if isinstance(safety, dict) else None
    timer_mutated = safety.get("timer_mutated") if isinstance(safety, dict) else None
    valid_type = artifact_type == "strategy_version_proposal"
    valid_safety = not any(
        value is True
        for value in [
            active_params_mutated,
            wrote_strategy_versions,
            writes_trade_state,
            writes_paper_live_behavior,
            timer_mutated,
        ]
    )
    error = None
    if not valid_type:
        error = "strategy-version proposal artifact must use artifact_type=strategy_version_proposal."
    elif not hypothesis_matches:
        error = "strategy-version proposal artifact hypothesis id does not match."
    elif not valid_safety:
        error = "strategy-version proposal artifact reports forbidden state mutation."

    return StrategyVersionProposalArtifactReview(
        path=str(path),
        exists=True,
        valid=valid_type and hypothesis_matches and valid_safety,
        artifact_type=str(artifact_type) if artifact_type is not None else None,
        hypothesis_id=parsed_hypothesis_id,
        hypothesis_matches=hypothesis_matches,
        proposal_key=(
            str(proposal.get("proposal_key"))
            if isinstance(proposal, dict) and proposal.get("proposal_key") is not None
            else None
        ),
        strategy_version_task_key=(
            str(proposal.get("strategy_version_task_key"))
            if isinstance(proposal, dict) and proposal.get("strategy_version_task_key") is not None
            else None
        ),
        candidate_strategy_version=(
            str(proposal.get("candidate_strategy_version"))
            if isinstance(proposal, dict) and proposal.get("candidate_strategy_version") is not None
            else None
        ),
        active_params_mutated=bool(active_params_mutated) if active_params_mutated is not None else None,
        wrote_strategy_versions=bool(wrote_strategy_versions) if wrote_strategy_versions is not None else None,
        writes_trade_state=bool(writes_trade_state) if writes_trade_state is not None else None,
        writes_paper_live_behavior=(
            bool(writes_paper_live_behavior) if writes_paper_live_behavior is not None else None
        ),
        timer_mutated=bool(timer_mutated) if timer_mutated is not None else None,
        error=error,
    )


def review_strategy_version_proposal_review_artifact(
    artifact_path: str | Path,
    *,
    expected_hypothesis_id: int | None = None,
    expected_proposal_key: str | None = None,
) -> StrategyVersionProposalReviewArtifactReview:
    path = Path(artifact_path).expanduser()
    if not path.exists():
        return StrategyVersionProposalReviewArtifactReview(
            path=str(path),
            exists=False,
            valid=False,
            error="strategy-version proposal review artifact was not found.",
        )
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return StrategyVersionProposalReviewArtifactReview(
            path=str(path),
            exists=True,
            valid=False,
            error=f"strategy-version proposal review artifact is not valid JSON: {exc}",
        )
    if not isinstance(artifact, dict):
        return StrategyVersionProposalReviewArtifactReview(
            path=str(path),
            exists=True,
            valid=False,
            error="strategy-version proposal review artifact must be a JSON object.",
        )

    artifact_type = artifact.get("artifact_type")
    hypothesis = artifact.get("hypothesis", {})
    parsed_hypothesis_id = _optional_int(hypothesis.get("id") if isinstance(hypothesis, dict) else None)
    hypothesis_matches = (
        parsed_hypothesis_id is not None
        if expected_hypothesis_id is None
        else parsed_hypothesis_id == expected_hypothesis_id
    )
    review = artifact.get("review", {})
    proposal = artifact.get("proposal", {})
    promotion_request = artifact.get("promotion_request", {})
    decision = review.get("decision") if isinstance(review, dict) else None
    proposal_key = None
    if isinstance(review, dict) and review.get("proposal_key") is not None:
        proposal_key = review.get("proposal_key")
    elif isinstance(proposal, dict) and proposal.get("proposal_key") is not None:
        proposal_key = proposal.get("proposal_key")
    proposal_matches = (
        bool(proposal_key)
        if expected_proposal_key is None
        else proposal_key == expected_proposal_key
    )
    safety = artifact.get("safety", {})
    active_params_mutated = safety.get("active_params_mutated") if isinstance(safety, dict) else None
    wrote_strategy_versions = safety.get("wrote_strategy_versions") if isinstance(safety, dict) else None
    writes_trade_state = safety.get("writes_trade_state") if isinstance(safety, dict) else None
    writes_paper_live_behavior = safety.get("writes_paper_live_behavior") if isinstance(safety, dict) else None
    timer_mutated = safety.get("timer_mutated") if isinstance(safety, dict) else None
    valid_safety = not any(
        value is True
        for value in [
            active_params_mutated,
            wrote_strategy_versions,
            writes_trade_state,
            writes_paper_live_behavior,
            timer_mutated,
        ]
    )
    valid_type = artifact_type in {"strategy_version_proposal_review", "strategy_version_promotion_request"}
    promotion_request_key = (
        promotion_request.get("request_key")
        if isinstance(promotion_request, dict) and promotion_request.get("request_key") is not None
        else None
    )

    error = None
    if not valid_type:
        error = (
            "proposal review artifact must use artifact_type=strategy_version_proposal_review "
            "or strategy_version_promotion_request."
        )
    elif decision not in VALID_PROPOSAL_REVIEW_DECISIONS:
        error = "proposal review artifact has an invalid decision."
    elif not hypothesis_matches:
        error = "proposal review artifact hypothesis id does not match."
    elif not proposal_matches:
        error = "proposal review artifact proposal key does not match."
    elif not valid_safety:
        error = "proposal review artifact reports forbidden state mutation."
    elif artifact_type == "strategy_version_promotion_request" and decision != "request_promotion":
        error = "promotion request artifact must use decision=request_promotion."
    elif decision == "request_promotion" and not promotion_request_key:
        error = "promotion request artifact must include a promotion_request.request_key."

    return StrategyVersionProposalReviewArtifactReview(
        path=str(path),
        exists=True,
        valid=error is None,
        artifact_type=str(artifact_type) if artifact_type is not None else None,
        hypothesis_id=parsed_hypothesis_id,
        hypothesis_matches=hypothesis_matches,
        proposal_key=str(proposal_key) if proposal_key is not None else None,
        proposal_matches=proposal_matches,
        review_key=(
            str(review.get("review_key"))
            if isinstance(review, dict) and review.get("review_key") is not None
            else None
        ),
        decision=str(decision) if decision is not None else None,
        promotion_request_key=str(promotion_request_key) if promotion_request_key is not None else None,
        active_params_mutated=bool(active_params_mutated) if active_params_mutated is not None else None,
        wrote_strategy_versions=bool(wrote_strategy_versions) if wrote_strategy_versions is not None else None,
        writes_trade_state=bool(writes_trade_state) if writes_trade_state is not None else None,
        writes_paper_live_behavior=(
            bool(writes_paper_live_behavior) if writes_paper_live_behavior is not None else None
        ),
        timer_mutated=bool(timer_mutated) if timer_mutated is not None else None,
        error=error,
    )


def review_shadow_promotion_dossier_artifact(
    artifact_path: str | Path,
) -> ShadowPromotionDossierArtifactReview:
    path = Path(artifact_path).expanduser()
    if not path.exists():
        return ShadowPromotionDossierArtifactReview(
            path=str(path),
            exists=False,
            valid=False,
            error="shadow promotion dossier artifact was not found.",
        )
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ShadowPromotionDossierArtifactReview(
            path=str(path),
            exists=True,
            valid=False,
            error=f"shadow promotion dossier artifact is not valid JSON: {exc}",
        )
    if not isinstance(artifact, dict):
        return ShadowPromotionDossierArtifactReview(
            path=str(path),
            exists=True,
            valid=False,
            error="shadow promotion dossier artifact must be a JSON object.",
        )

    artifact_type = artifact.get("artifact_type")
    dossier_contract = artifact.get("dossier_contract")
    summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
    release_gate = artifact.get("release_gate") if isinstance(artifact.get("release_gate"), dict) else {}
    safety = artifact.get("safety") if isinstance(artifact.get("safety"), dict) else {}
    candidates = artifact.get("candidates") if isinstance(artifact.get("candidates"), list) else []
    candidate_dicts = [dict(item) for item in candidates if isinstance(item, dict)]
    review_ready_candidates = [
        str(item.get("candidate_key"))
        for item in candidate_dicts
        if item.get("review_status") == "review_ready" and item.get("candidate_key") is not None
    ]
    replay_status_counts: dict[str, int] = {}
    replay_evidence_promotes = False
    for item in candidate_dicts:
        replay_evidence = item.get("replay_backtest_evidence")
        if not isinstance(replay_evidence, dict):
            replay_status_counts["missing"] = replay_status_counts.get("missing", 0) + 1
            continue
        status = str(replay_evidence.get("status") or "missing")
        replay_status_counts[status] = replay_status_counts.get(status, 0) + 1
        replay_evidence_promotes = replay_evidence_promotes or any(
            bool(replay_evidence.get(key))
            for key in ("promotion_allowed", "paper_observation_allowed")
        )
    candidate_promotion_allowed = any(
        bool(item.get("promotion_allowed"))
        or (
            isinstance(item.get("promotion_gate"), dict)
            and bool(item["promotion_gate"].get("promotion_allowed"))
        )
        for item in candidate_dicts
    )
    active_params_mutated = bool(safety.get("active_params_mutated"))
    wrote_strategy_version = bool(safety.get("wrote_strategy_version"))
    wrote_strategy_versions = bool(safety.get("wrote_strategy_versions"))
    writes_trade_state = bool(safety.get("writes_trade_state"))
    writes_paper_live_behavior = bool(safety.get("writes_paper_live_behavior"))
    timer_mutated = bool(safety.get("timer_mutated"))
    promotion_allowed = any(
        bool(value)
        for value in (
            safety.get("promotion_allowed"),
            summary.get("promotion_allowed"),
            release_gate.get("promotion_allowed"),
            candidate_promotion_allowed,
            replay_evidence_promotes,
        )
    )
    valid_type = artifact_type == "shadow_promotion_dossier"
    valid_contract = dossier_contract == "shadow_promotion_dossier_v1"
    valid_safety = not any(
        [
            active_params_mutated,
            wrote_strategy_version,
            wrote_strategy_versions,
            writes_trade_state,
            writes_paper_live_behavior,
            timer_mutated,
            promotion_allowed,
        ]
    )
    error = None
    if not valid_type:
        error = "shadow promotion dossier artifact must use artifact_type=shadow_promotion_dossier."
    elif not valid_contract:
        error = "shadow promotion dossier artifact must use dossier_contract=shadow_promotion_dossier_v1."
    elif not valid_safety:
        error = "shadow promotion dossier reports mutation or promotion permission."

    return ShadowPromotionDossierArtifactReview(
        path=str(path),
        exists=True,
        valid=valid_type and valid_contract and valid_safety,
        artifact_type=str(artifact_type) if artifact_type is not None else None,
        dossier_contract=str(dossier_contract) if dossier_contract is not None else None,
        candidate_count=_optional_int(summary.get("candidate_count")) or len(candidate_dicts),
        review_ready_count=_optional_int(summary.get("review_ready_count")) or len(review_ready_candidates),
        blocked_count=_optional_int(summary.get("blocked_count"))
        or sum(1 for item in candidate_dicts if item.get("review_status") == "blocked"),
        review_ready_candidates=review_ready_candidates,
        replay_backtest_evidence_accepted_count=replay_status_counts.get("accepted", 0),
        replay_backtest_evidence_rejected_count=replay_status_counts.get("rejected", 0),
        replay_backtest_evidence_missing_count=replay_status_counts.get("missing", 0),
        replay_backtest_evidence_advisory_only=True,
        active_params_mutated=active_params_mutated,
        wrote_strategy_version=wrote_strategy_version,
        wrote_strategy_versions=wrote_strategy_versions,
        writes_trade_state=writes_trade_state,
        writes_paper_live_behavior=writes_paper_live_behavior,
        timer_mutated=timer_mutated,
        promotion_allowed=promotion_allowed,
        error=error,
    )


def review_shadow_promotion_review_request_artifact(
    artifact_path: str | Path,
) -> ShadowPromotionReviewRequestArtifactReview:
    path = Path(artifact_path).expanduser()
    if not path.exists():
        return ShadowPromotionReviewRequestArtifactReview(
            path=str(path),
            exists=False,
            valid=False,
            error="shadow promotion review request artifact was not found.",
        )
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ShadowPromotionReviewRequestArtifactReview(
            path=str(path),
            exists=True,
            valid=False,
            error=f"shadow promotion review request artifact is not valid JSON: {exc}",
        )
    if not isinstance(artifact, dict):
        return ShadowPromotionReviewRequestArtifactReview(
            path=str(path),
            exists=True,
            valid=False,
            error="shadow promotion review request artifact must be a JSON object.",
        )

    artifact_type = artifact.get("artifact_type")
    review_request_contract = artifact.get("review_request_contract")
    summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
    review_request = artifact.get("review_request") if isinstance(artifact.get("review_request"), dict) else {}
    source_dossier = artifact.get("source_dossier") if isinstance(artifact.get("source_dossier"), dict) else {}
    source_dossier_review = (
        artifact.get("source_dossier_review") if isinstance(artifact.get("source_dossier_review"), dict) else {}
    )
    safety = artifact.get("safety") if isinstance(artifact.get("safety"), dict) else {}
    source_dossier_summary = (
        source_dossier.get("summary") if isinstance(source_dossier.get("summary"), dict) else {}
    )
    candidate_dicts = [
        dict(item)
        for item in source_dossier.get("candidates", [])
        if isinstance(item, dict)
    ]
    review_ready_candidates = [
        str(item.get("candidate_key"))
        for item in candidate_dicts
        if item.get("review_status") == "review_ready" and item.get("candidate_key") is not None
    ]
    blocked_candidate_keys = [
        str(item.get("candidate_key"))
        for item in candidate_dicts
        if item.get("review_status") != "review_ready" and item.get("candidate_key") is not None
    ]
    candidate_count = _optional_int(summary.get("candidate_count")) or len(candidate_dicts)
    review_ready_count = _optional_int(summary.get("review_ready_count")) or len(review_ready_candidates)
    blocked_count = _optional_int(summary.get("blocked_count")) or len(blocked_candidate_keys)
    blocking_reason = _optional_text(review_request.get("blocking_reason"))
    required_human_decisions = _list_mapping(review_request.get("required_human_decisions"))
    required_replay_backtest_evidence = _list_mapping(review_request.get("required_replay_backtest_evidence"))
    rollback_notes = _list_text(review_request.get("rollback_notes"))
    safety_notes = _list_text(review_request.get("safety_notes"))
    review_ready_is_not_approval = bool(summary.get("review_ready_is_not_approval"))
    manual_review_required = bool(summary.get("manual_review_required"))
    promotion_allowed = any(
        bool(value)
        for value in (
            summary.get("promotion_allowed"),
            safety.get("promotion_allowed"),
            source_dossier_review.get("promotion_allowed"),
        )
    )
    active_params_mutated = bool(safety.get("active_params_mutated"))
    wrote_strategy_version = bool(safety.get("wrote_strategy_version"))
    wrote_strategy_versions = bool(safety.get("wrote_strategy_versions"))
    writes_trade_state = bool(safety.get("writes_trade_state"))
    writes_paper_live_behavior = bool(safety.get("writes_paper_live_behavior"))
    timer_mutated = bool(safety.get("timer_mutated"))
    valid_type = artifact_type == "shadow_promotion_review_request"
    valid_contract = review_request_contract == "shadow_promotion_review_request_v1"
    valid_safety = not any(
        [
            active_params_mutated,
            wrote_strategy_version,
            wrote_strategy_versions,
            writes_trade_state,
            writes_paper_live_behavior,
            timer_mutated,
            promotion_allowed,
            not review_ready_is_not_approval,
            not manual_review_required,
        ]
    )
    error = None
    if not valid_type:
        error = (
            "shadow promotion review request artifact must use "
            "artifact_type=shadow_promotion_review_request."
        )
    elif not valid_contract:
        error = (
            "shadow promotion review request artifact must use "
            "review_request_contract=shadow_promotion_review_request_v1."
        )
    elif not summary:
        error = "shadow promotion review request artifact must include a summary object."
    elif summary.get("status") not in {"blocked", "review_ready"}:
        error = "shadow promotion review request summary status must be blocked or review_ready."
    elif summary.get("status") == "blocked" and not blocking_reason:
        error = "blocked shadow promotion review request artifact must include a blocking reason."
    elif summary.get("status") == "review_ready" and not review_ready_candidates:
        error = "review-ready shadow promotion review request artifact must include a review-ready candidate."
    elif not required_human_decisions:
        error = "shadow promotion review request artifact must include required human decisions."
    elif not required_replay_backtest_evidence:
        error = "shadow promotion review request artifact must include required replay/backtest evidence."
    elif not rollback_notes:
        error = "shadow promotion review request artifact must include rollback notes."
    elif not safety_notes:
        error = "shadow promotion review request artifact must include safety notes."
    elif not valid_safety:
        error = "shadow promotion review request artifact reports mutation or promotion permission."
    elif source_dossier.get("artifact_type") != "shadow_promotion_dossier":
        error = "shadow promotion review request artifact must include a source shadow promotion dossier."
    elif source_dossier.get("dossier_contract") != "shadow_promotion_dossier_v1":
        error = "shadow promotion review request artifact must reference shadow_promotion_dossier_v1."
    elif bool(source_dossier_summary.get("promotion_allowed")):
        error = "source shadow promotion dossier must remain blocked."
    elif summary.get("candidate_count") is not None and int(summary.get("candidate_count") or 0) != candidate_count:
        error = "shadow promotion review request candidate count does not match the source dossier."
    elif summary.get("review_ready_count") is not None and int(summary.get("review_ready_count") or 0) != review_ready_count:
        error = "shadow promotion review request review-ready count does not match the source dossier."
    elif summary.get("blocked_count") is not None and int(summary.get("blocked_count") or 0) != blocked_count:
        error = "shadow promotion review request blocked count does not match the source dossier."

    return ShadowPromotionReviewRequestArtifactReview(
        path=str(path),
        exists=True,
        valid=error is None,
        artifact_type=str(artifact_type) if artifact_type is not None else None,
        review_request_contract=(
            str(review_request_contract) if review_request_contract is not None else None
        ),
        source_dossier_contract=(
            str(source_dossier.get("dossier_contract")) if source_dossier.get("dossier_contract") is not None else None
        ),
        candidate_count=candidate_count,
        review_ready_count=review_ready_count,
        blocked_count=blocked_count,
        review_ready_candidates=review_ready_candidates,
        blocked_candidate_keys=blocked_candidate_keys,
        blocking_reason=blocking_reason,
        required_human_decisions_count=len(required_human_decisions),
        required_replay_backtest_evidence_count=len(required_replay_backtest_evidence),
        review_ready_is_not_approval=review_ready_is_not_approval,
        manual_review_required=manual_review_required,
        promotion_allowed=promotion_allowed,
        active_params_mutated=active_params_mutated,
        wrote_strategy_version=wrote_strategy_version,
        wrote_strategy_versions=wrote_strategy_versions,
        writes_trade_state=writes_trade_state,
        writes_paper_live_behavior=writes_paper_live_behavior,
        timer_mutated=timer_mutated,
        error=error,
    )


def _proposal_artifact_path_for_review(hypothesis: StrategyHypothesis, explicit_path: str | None) -> Path | None:
    if explicit_path is not None:
        return Path(explicit_path).expanduser()
    proposal_paths = _validation_values(hypothesis.evidence, "strategy_version_proposals")
    if not proposal_paths:
        return None
    return Path(proposal_paths[-1]).expanduser()


def _build_strategy_version_proposal_review_artifact(
    *,
    hypothesis: StrategyHypothesis,
    proposal_review: StrategyVersionProposalArtifactReview,
    decision: str,
    review_note: str | None,
    operator: str | None,
    idempotency_key: str | None,
) -> dict[str, Any]:
    hypothesis_id = int(hypothesis.hypothesis_id or 0)
    review_key = f"strategy-hypothesis:{hypothesis_id}:strategy-proposal-review:{decision}"
    promotion_request_key = (
        f"strategy-hypothesis:{hypothesis_id}:strategy-version-promotion-request"
        if decision == "request_promotion"
        else None
    )
    artifact_type = (
        "strategy_version_promotion_request"
        if decision == "request_promotion"
        else "strategy_version_proposal_review"
    )
    artifact: dict[str, Any] = {
        "artifact_type": artifact_type,
        "artifact_version": 1,
        "created_at": _utc_timestamp(),
        "operator": operator,
        "idempotency_key": idempotency_key,
        "hypothesis": {
            "id": hypothesis_id,
            "as_of_date": hypothesis.as_of_date,
            "status": hypothesis.status,
            "hypothesis_type": hypothesis.hypothesis_type,
            "title": hypothesis.title,
        },
        "proposal": {
            "artifact_path": proposal_review.path,
            "proposal_key": proposal_review.proposal_key,
            "strategy_version_task_key": proposal_review.strategy_version_task_key,
            "candidate_strategy_version": proposal_review.candidate_strategy_version,
            "valid": proposal_review.valid,
        },
        "review": {
            "review_key": review_key,
            "proposal_key": proposal_review.proposal_key,
            "decision": decision,
            "status": _proposal_review_status(decision),
            "review_note": review_note,
            "artifact_only": True,
        },
        "promotion_gate": {
            "artifact_only": True,
            "creates_strategy_version_row": False,
            "active_params_mutated": False,
            "active_deployment_unchanged": True,
            "paper_live_behavior_unchanged": True,
            "allowed_decisions": sorted(VALID_PROPOSAL_REVIEW_DECISIONS),
        },
        "safety": {
            "active_params_mutated": False,
            "wrote_strategy_versions": False,
            "writes_trade_state": False,
            "writes_paper_live_behavior": False,
            "timer_mutated": False,
            "paper_live_deployment_changed": False,
        },
    }
    if promotion_request_key is not None:
        artifact["promotion_request"] = {
            "request_key": promotion_request_key,
            "status": "requested",
            "proposal_key": proposal_review.proposal_key,
            "candidate_strategy_version": proposal_review.candidate_strategy_version,
            "requires_separate_candidate_version_task": True,
            "requires_operator_promotion_approval": True,
            "artifact_only": True,
        }
    return artifact


def _proposal_review_status(decision: str) -> str:
    return {
        "approve": "approved",
        "reject": "rejected",
        "request_promotion": "promotion_requested",
    }.get(decision, "unknown")


def _build_strategy_version_proposal_artifact(
    *,
    hypothesis: StrategyHypothesis,
    evidence_ids: list[str],
    backtest_artifact_paths: list[str],
    strategy_version_task: dict[str, Any],
    current_strategy: sqlite3.Row | None,
    operator: str | None,
) -> dict[str, Any]:
    hypothesis_id = int(hypothesis.hypothesis_id or 0)
    strategy_id = str(
        strategy_version_task.get("strategy_id")
        or hypothesis.proposed_change.get("strategy_id")
        or "cpb_6157"
    )
    strategy = _current_strategy_payload(current_strategy, strategy_id)
    proposal_key = f"strategy-hypothesis:{hypothesis_id}:strategy-version-proposal"
    candidate_strategy_version = f"{strategy_id}-proposal-h{hypothesis_id}-{hypothesis.as_of_date}"
    proposed_change = {
        **hypothesis.proposed_change,
        "mutates_active_params": False,
    }
    return {
        "artifact_type": "strategy_version_proposal",
        "artifact_version": 1,
        "created_at": _utc_timestamp(),
        "operator": operator,
        "hypothesis": {
            "id": hypothesis_id,
            "as_of_date": hypothesis.as_of_date,
            "status": hypothesis.status,
            "hypothesis_type": hypothesis.hypothesis_type,
            "title": hypothesis.title,
            "rationale": hypothesis.rationale,
            "evidence": hypothesis.evidence,
            "proposed_change": proposed_change,
        },
        "base_strategy": strategy,
        "proposal": {
            "proposal_key": proposal_key,
            "strategy_version_task_key": strategy_version_task.get("task_key"),
            "task_type": "strategy_version_proposal_review",
            "status": "proposal_ready",
            "strategy_id": strategy_id,
            "base_strategy_version": strategy.get("current_strategy_version"),
            "candidate_strategy_version": candidate_strategy_version,
            "candidate_status": "draft",
            "validation_evidence_ids": evidence_ids,
            "backtest_artifact_paths": backtest_artifact_paths,
            "proposed_change": proposed_change,
        },
        "strategy_version_task": strategy_version_task,
        "promotion_gate": {
            "proposal_artifact_only": True,
            "creates_strategy_version_row": False,
            "required_before_candidate_creation": [
                "proposal_review",
                "operator_approval",
                "replay_backtest_passed",
            ],
            "active_deployment_unchanged": True,
        },
        "safety": {
            "active_params_mutated": False,
            "wrote_strategy_versions": False,
            "writes_trade_state": False,
            "writes_paper_live_behavior": False,
            "timer_mutated": False,
            "paper_live_deployment_changed": False,
        },
    }


def _record_strategy_version_proposal_artifact(
    db_path: Path,
    hypothesis_id: int,
    artifact_path: Path,
    artifact: dict[str, Any],
    operator: str | None,
) -> None:
    with connect(db_path) as conn:
        hypothesis = _get_hypothesis(conn, hypothesis_id)
        if hypothesis is None:
            raise RuntimeError(f"strategy hypothesis id={hypothesis_id} was not found while recording proposal")
        evidence = dict(hypothesis.evidence)
        validation = _validation_payload(evidence)
        proposal_paths = _merge_validation_values(
            _validation_values(evidence, "strategy_version_proposals"),
            [str(artifact_path)],
        )
        proposal = artifact.get("proposal", {})
        validation["strategy_version_proposals"] = proposal_paths
        validation["strategy_version_proposal_key"] = (
            proposal.get("proposal_key") if isinstance(proposal, dict) else None
        )
        validation["strategy_version_proposal_recorded_at"] = _utc_timestamp()
        validation["strategy_version_proposal_operator"] = operator
        evidence["validation"] = validation
        conn.execute(
            """
            UPDATE strategy_hypotheses
            SET evidence_json = ?
            WHERE id = ?
            """,
            (_json_dumps(evidence), hypothesis_id),
        )


def _record_strategy_version_proposal_review_artifact(
    db_path: Path,
    hypothesis_id: int,
    artifact_path: Path,
    artifact: dict[str, Any],
    operator: str | None,
) -> None:
    with connect(db_path) as conn:
        hypothesis = _get_hypothesis(conn, hypothesis_id)
        if hypothesis is None:
            raise RuntimeError(f"strategy hypothesis id={hypothesis_id} was not found while recording review")
        evidence = dict(hypothesis.evidence)
        validation = _validation_payload(evidence)
        review_paths = _merge_validation_values(
            _validation_values(evidence, "strategy_version_proposal_reviews"),
            [str(artifact_path)],
        )
        review = artifact.get("review", {})
        promotion_request = artifact.get("promotion_request", {})
        decision = review.get("decision") if isinstance(review, dict) else None
        validation["strategy_version_proposal_reviews"] = review_paths
        validation["latest_strategy_version_proposal_review_key"] = (
            review.get("review_key") if isinstance(review, dict) else None
        )
        validation["latest_strategy_version_proposal_review_decision"] = decision
        validation["latest_strategy_version_proposal_reviewed_at"] = _utc_timestamp()
        validation["latest_strategy_version_proposal_review_operator"] = operator
        if decision == "request_promotion":
            promotion_paths = _merge_validation_values(
                _validation_values(evidence, "strategy_version_promotion_requests"),
                [str(artifact_path)],
            )
            validation["strategy_version_promotion_requests"] = promotion_paths
            validation["latest_strategy_version_promotion_request_key"] = (
                promotion_request.get("request_key") if isinstance(promotion_request, dict) else None
            )
        evidence["validation"] = validation
        conn.execute(
            """
            UPDATE strategy_hypotheses
            SET evidence_json = ?
            WHERE id = ?
            """,
            (_json_dumps(evidence), hypothesis_id),
        )


def _is_shadow_candidate(hypothesis: StrategyHypothesis) -> bool:
    return (
        hypothesis.evidence.get("source") == SHADOW_RESEARCH_SOURCE
        or bool(hypothesis.evidence.get("artifact_only"))
        or bool(hypothesis.proposed_change.get("artifact_only"))
        or str(hypothesis.proposed_change.get("change_type") or "") == "shadow_candidate"
    )


def _shadow_paper_observation_gate(hypothesis: StrategyHypothesis) -> dict[str, Any]:
    return _shadow_gate_payload_from_evidence(hypothesis, "paper_observation_gate")


def _shadow_strategy_version_gate(hypothesis: StrategyHypothesis) -> dict[str, Any]:
    return _shadow_gate_payload_from_evidence(hypothesis, "strategy_version_gate")


def _shadow_gate_payload_from_evidence(hypothesis: StrategyHypothesis, key: str) -> dict[str, Any]:
    gate = hypothesis.evidence.get(key)
    if isinstance(gate, dict):
        return dict(gate)
    if not _is_shadow_candidate(hypothesis):
        return {}
    if key == "paper_observation_gate":
        blockers = hypothesis.proposed_change.get("paper_observation_blockers")
        return _blocked_gate_payload(
            "paper_observation",
            [str(blocker) for blocker in blockers] if isinstance(blockers, list) else _shadow_base_paper_blockers(),
        )
    blockers = hypothesis.proposed_change.get("strategy_version_proposal_blockers")
    return _blocked_gate_payload(
        "strategy_version_proposal",
        [str(blocker) for blocker in blockers]
        if isinstance(blockers, list)
        else _shadow_base_strategy_version_blockers(),
    )


def _shadow_comparison_from_evidence(hypothesis: StrategyHypothesis) -> dict[str, Any]:
    comparison = hypothesis.evidence.get("shadow_comparison")
    return dict(comparison) if isinstance(comparison, dict) else {}


def _shadow_paper_observation_blockers(hypothesis: StrategyHypothesis) -> list[str]:
    return _unresolved_shadow_blockers(
        hypothesis,
        _shadow_paper_observation_gate(hypothesis),
        "cleared_shadow_paper_observation_blockers",
    )


def _shadow_strategy_version_blockers(hypothesis: StrategyHypothesis) -> list[str]:
    return _unresolved_shadow_blockers(
        hypothesis,
        _shadow_strategy_version_gate(hypothesis),
        "cleared_shadow_strategy_version_blockers",
    )


def _unresolved_shadow_blockers(
    hypothesis: StrategyHypothesis,
    gate: dict[str, Any],
    cleared_key: str,
) -> list[str]:
    blockers = gate.get("blockers") if isinstance(gate, dict) else None
    if not isinstance(blockers, list):
        return []
    cleared = set(_validation_values(hypothesis.evidence, cleared_key))
    return [str(blocker) for blocker in blockers if str(blocker) and str(blocker) not in cleared]


def _evaluate_hypothesis(hypothesis: StrategyHypothesis) -> StrategyHypothesisEvaluation:
    evidence_ids = _validation_values(hypothesis.evidence, "evidence_ids")
    artifact_reviews = [
        review_strategy_hypothesis_backtest_artifact(
            artifact_path,
            expected_hypothesis_id=int(hypothesis.hypothesis_id or 0),
        )
        for artifact_path in _validation_values(hypothesis.evidence, "backtest_artifacts")
    ]
    proposal_reviews = [
        review_strategy_version_proposal_artifact(
            artifact_path,
            expected_hypothesis_id=int(hypothesis.hypothesis_id or 0),
        )
        for artifact_path in _validation_values(hypothesis.evidence, "strategy_version_proposals")
    ]
    expected_proposal_key = proposal_reviews[-1].proposal_key if proposal_reviews else None
    proposal_review_artifacts = [
        review_strategy_version_proposal_review_artifact(
            artifact_path,
            expected_hypothesis_id=int(hypothesis.hypothesis_id or 0),
            expected_proposal_key=expected_proposal_key,
        )
        for artifact_path in _validation_values(hypothesis.evidence, "strategy_version_proposal_reviews")
    ]
    validation_events = _validation_events(hypothesis.evidence)
    acceptance_gate = _acceptance_gate_payload(hypothesis, evidence_ids, artifact_reviews)
    shadow_comparison = _shadow_comparison_from_evidence(hypothesis)
    paper_observation_gate = _shadow_paper_observation_gate(hypothesis)
    strategy_version_gate = _shadow_strategy_version_gate(hypothesis)
    safety = _hypothesis_safety_payload(hypothesis, artifact_reviews, proposal_reviews, proposal_review_artifacts)
    next_action, next_action_label = _evaluation_next_action(
        hypothesis,
        acceptance_gate,
        safety,
        proposal_reviews,
        proposal_review_artifacts,
    )
    strategy_version_task = (
        _future_strategy_version_task_payload(
            hypothesis,
            evidence_ids,
            [artifact.path for artifact in artifact_reviews],
        )
        if hypothesis.status == "accepted"
        else None
    )
    return StrategyHypothesisEvaluation(
        hypothesis=hypothesis,
        evidence_ids=evidence_ids,
        backtest_artifacts=artifact_reviews,
        strategy_version_proposals=proposal_reviews,
        strategy_version_proposal_reviews=proposal_review_artifacts,
        validation_events=validation_events,
        acceptance_gate=acceptance_gate,
        safety=safety,
        shadow_comparison=shadow_comparison,
        paper_observation_gate=paper_observation_gate,
        strategy_version_gate=strategy_version_gate,
        next_action=next_action,
        next_action_label=next_action_label,
        strategy_version_task=strategy_version_task,
    )


def _acceptance_gate_payload(
    hypothesis: StrategyHypothesis,
    evidence_ids: list[str],
    artifact_reviews: list[StrategyHypothesisBacktestArtifactReview],
) -> dict[str, Any]:
    has_artifact = bool(artifact_reviews)
    artifacts_valid = bool(artifact_reviews) and all(artifact.valid for artifact in artifact_reviews)
    mutates_active_params = bool(hypothesis.proposed_change.get("mutates_active_params"))
    blocks: list[str] = []
    if hypothesis.status not in {"testing", "accepted"}:
        blocks.append("testing_status_required")
    if not evidence_ids:
        blocks.append("validation_evidence_required")
    if not has_artifact:
        blocks.append("backtest_artifact_required")
    elif not artifacts_valid:
        blocks.append("valid_backtest_artifact_required")
    if mutates_active_params:
        blocks.append("active_param_mutation_forbidden")
    shadow_paper_blockers = _shadow_paper_observation_blockers(hypothesis)
    shadow_strategy_version_blockers = _shadow_strategy_version_blockers(hypothesis)
    return {
        "can_accept": hypothesis.status == "testing" and not blocks,
        "accepted_complete": hypothesis.status == "accepted" and not blocks,
        "testing_required": hypothesis.status == "testing",
        "has_validation_evidence": bool(evidence_ids),
        "has_backtest_artifact": has_artifact,
        "backtest_artifacts_valid": artifacts_valid,
        "requires_replay_backtest": bool(hypothesis.proposed_change.get("requires_replay_backtest", True)),
        "blocks": blocks,
        "shadow_candidate": _is_shadow_candidate(hypothesis),
        "paper_observation_blockers": shadow_paper_blockers,
        "strategy_version_proposal_blockers": shadow_strategy_version_blockers,
    }


def _hypothesis_safety_payload(
    hypothesis: StrategyHypothesis,
    artifact_reviews: list[StrategyHypothesisBacktestArtifactReview],
    proposal_reviews: list[StrategyVersionProposalArtifactReview],
    proposal_review_artifacts: list[StrategyVersionProposalReviewArtifactReview],
) -> dict[str, Any]:
    artifact_reports_mutation = any(artifact.active_params_mutated is True for artifact in artifact_reviews)
    proposal_reports_mutation = any(proposal.active_params_mutated is True for proposal in proposal_reviews)
    review_reports_mutation = any(review.active_params_mutated is True for review in proposal_review_artifacts)
    proposal_wrote_strategy_versions = any(proposal.wrote_strategy_versions is True for proposal in proposal_reviews)
    review_wrote_strategy_versions = any(
        review.wrote_strategy_versions is True for review in proposal_review_artifacts
    )
    proposal_timer_mutated = any(proposal.timer_mutated is True for proposal in proposal_reviews)
    review_timer_mutated = any(review.timer_mutated is True for review in proposal_review_artifacts)
    paper_blockers = _shadow_paper_observation_blockers(hypothesis)
    strategy_version_blockers = _shadow_strategy_version_blockers(hypothesis)
    return {
        "read_only_evaluation": True,
        "proposed_change_mutates_active_params": bool(hypothesis.proposed_change.get("mutates_active_params")),
        "artifact_reports_active_param_mutation": (
            artifact_reports_mutation or proposal_reports_mutation or review_reports_mutation
        ),
        "proposal_wrote_strategy_versions": proposal_wrote_strategy_versions or review_wrote_strategy_versions,
        "proposal_timer_mutated": proposal_timer_mutated or review_timer_mutated,
        "proposal_artifacts_only": not (
            proposal_wrote_strategy_versions
            or review_wrote_strategy_versions
            or proposal_timer_mutated
            or review_timer_mutated
        ),
        "active_params_mutated": False,
        "writes_trade_state": False,
        "writes_paper_live_behavior": False,
        "timer_mutated": False,
        "accepted_creates_separate_strategy_version_task": hypothesis.status == "accepted",
        "proposal_review_artifacts_only": not (review_wrote_strategy_versions or review_timer_mutated),
        "shadow_candidate": _is_shadow_candidate(hypothesis),
        "paper_observation_blocked": bool(paper_blockers),
        "strategy_version_proposal_blocked": bool(strategy_version_blockers),
        "paper_observation_blockers": paper_blockers,
        "strategy_version_proposal_blockers": strategy_version_blockers,
    }


def _evaluation_next_action(
    hypothesis: StrategyHypothesis,
    acceptance_gate: dict[str, Any],
    safety: dict[str, Any],
    proposal_reviews: list[StrategyVersionProposalArtifactReview],
    proposal_review_artifacts: list[StrategyVersionProposalReviewArtifactReview],
) -> tuple[str, str]:
    if (
        safety["proposed_change_mutates_active_params"]
        or safety["artifact_reports_active_param_mutation"]
        or safety["proposal_wrote_strategy_versions"]
        or safety["proposal_timer_mutated"]
    ):
        return "reject_or_rewrite", "Rewrite or reject; active parameter, strategy-version, or timer mutation is forbidden."
    if hypothesis.status == "proposed":
        return "move_to_testing", "Move to testing before acceptance review."
    if hypothesis.status == "testing" and acceptance_gate["can_accept"]:
        return "ready_to_accept", "Evidence and backtest artifact are present; ready for acceptance review."
    if hypothesis.status == "testing":
        blocks = set(acceptance_gate.get("blocks", []))
        if "backtest_artifact_required" in blocks:
            return "create_backtest_artifact", "Create or attach a replay/backtest request artifact."
        if "valid_backtest_artifact_required" in blocks:
            return "fix_backtest_artifact", "Fix the attached replay/backtest artifact before acceptance."
        if "validation_evidence_required" in blocks:
            return "attach_validation_evidence", "Attach validation evidence ids before acceptance."
        return "continue_testing", "Continue validation before acceptance."
    if hypothesis.status == "accepted":
        if safety.get("strategy_version_proposal_blocked"):
            return (
                "shadow_gate_blocked",
                "Accepted is research-only; clear shadow paper/proposal blockers before observation or proposal.",
            )
        if not proposal_reviews:
            return (
                "create_strategy_version_proposal",
                "Accepted is a research outcome; create a separate strategy-version proposal artifact.",
            )
        if not all(proposal.valid for proposal in proposal_reviews):
            return "fix_strategy_version_proposal", "Fix the strategy-version proposal artifact before review."
        if proposal_review_artifacts and not all(review.valid for review in proposal_review_artifacts):
            return "fix_strategy_version_proposal_review", "Fix the proposal review artifact before promotion review."
        latest_review = proposal_review_artifacts[-1] if proposal_review_artifacts else None
        if latest_review is None:
            return (
                "review_strategy_version_proposal",
                "Review the strategy-version proposal artifact and approve, reject, or request promotion.",
            )
        if latest_review.decision == "reject":
            return "proposal_rejected", "Proposal review rejected the artifact; keep active strategy unchanged."
        if latest_review.decision == "approve":
            return (
                "request_strategy_promotion",
                "Proposal artifact is approved; create an explicit promotion-request artifact if desired.",
            )
        if latest_review.decision == "request_promotion":
            return (
                "promotion_requested",
                "Promotion-request artifact exists; a later task must create or promote candidate versions.",
            )
        return "proposal_ready", "Strategy-version proposal artifact is ready for separate candidate-version review."
    if hypothesis.status == "rejected":
        return "closed_rejected", "Rejected; keep as research record."
    if hypothesis.status == "archived":
        return "closed_archived", "Archived; no active review action."
    return "review", "Review hypothesis state."


def _evaluation_summary(evaluations: list[StrategyHypothesisEvaluation]) -> dict[str, Any]:
    by_status: dict[str, int] = {status: 0 for status in sorted(VALID_HYPOTHESIS_STATUSES)}
    by_next_action: dict[str, int] = {}
    artifact_count = 0
    invalid_artifact_count = 0
    proposal_artifact_count = 0
    invalid_proposal_artifact_count = 0
    proposal_review_artifact_count = 0
    invalid_proposal_review_artifact_count = 0
    proposal_review_approved_count = 0
    proposal_review_rejected_count = 0
    promotion_request_count = 0
    ready_to_accept_count = 0
    strategy_version_task_required_count = 0
    proposal_required_count = 0
    proposal_review_required_count = 0
    proposal_ready_count = 0
    shadow_candidate_count = 0
    shadow_comparison_count = 0
    shadow_gate_blocked_count = 0
    paper_observation_blocked_count = 0
    strategy_version_proposal_blocked_count = 0
    unsafe_count = 0
    for evaluation in evaluations:
        status = evaluation.hypothesis.status
        by_status[status] = by_status.get(status, 0) + 1
        by_next_action[evaluation.next_action] = by_next_action.get(evaluation.next_action, 0) + 1
        artifact_count += len(evaluation.backtest_artifacts)
        invalid_artifact_count += len([artifact for artifact in evaluation.backtest_artifacts if not artifact.valid])
        proposal_artifact_count += len(evaluation.strategy_version_proposals)
        invalid_proposal_artifact_count += len(
            [artifact for artifact in evaluation.strategy_version_proposals if not artifact.valid]
        )
        proposal_review_artifact_count += len(evaluation.strategy_version_proposal_reviews)
        invalid_proposal_review_artifact_count += len(
            [artifact for artifact in evaluation.strategy_version_proposal_reviews if not artifact.valid]
        )
        proposal_review_approved_count += len(
            [artifact for artifact in evaluation.strategy_version_proposal_reviews if artifact.decision == "approve"]
        )
        proposal_review_rejected_count += len(
            [artifact for artifact in evaluation.strategy_version_proposal_reviews if artifact.decision == "reject"]
        )
        promotion_request_count += len(
            [
                artifact
                for artifact in evaluation.strategy_version_proposal_reviews
                if artifact.decision == "request_promotion"
            ]
        )
        if evaluation.acceptance_gate.get("can_accept"):
            ready_to_accept_count += 1
        if evaluation.strategy_version_task is not None:
            strategy_version_task_required_count += 1
        if evaluation.next_action == "create_strategy_version_proposal":
            proposal_required_count += 1
        if evaluation.next_action == "review_strategy_version_proposal":
            proposal_review_required_count += 1
        if evaluation.next_action in {"proposal_ready", "review_strategy_version_proposal"}:
            proposal_ready_count += 1
        if evaluation.safety.get("shadow_candidate"):
            shadow_candidate_count += 1
        if evaluation.shadow_comparison:
            shadow_comparison_count += 1
        if evaluation.next_action == "shadow_gate_blocked":
            shadow_gate_blocked_count += 1
        if evaluation.safety.get("paper_observation_blocked"):
            paper_observation_blocked_count += 1
        if evaluation.safety.get("strategy_version_proposal_blocked"):
            strategy_version_proposal_blocked_count += 1
        if (
            evaluation.safety.get("proposed_change_mutates_active_params")
            or evaluation.safety.get("artifact_reports_active_param_mutation")
            or evaluation.safety.get("proposal_wrote_strategy_versions")
        ):
            unsafe_count += 1
    return {
        "total": len(evaluations),
        "by_status": by_status,
        "by_next_action": by_next_action,
        "ready_to_accept_count": ready_to_accept_count,
        "artifact_count": artifact_count,
        "invalid_artifact_count": invalid_artifact_count,
        "strategy_version_task_required_count": strategy_version_task_required_count,
        "proposal_required_count": proposal_required_count,
        "proposal_ready_count": proposal_ready_count,
        "proposal_artifact_count": proposal_artifact_count,
        "invalid_proposal_artifact_count": invalid_proposal_artifact_count,
        "proposal_review_required_count": proposal_review_required_count,
        "proposal_review_artifact_count": proposal_review_artifact_count,
        "invalid_proposal_review_artifact_count": invalid_proposal_review_artifact_count,
        "proposal_review_approved_count": proposal_review_approved_count,
        "proposal_review_rejected_count": proposal_review_rejected_count,
        "promotion_request_count": promotion_request_count,
        "shadow_candidate_count": shadow_candidate_count,
        "shadow_comparison_count": shadow_comparison_count,
        "shadow_gate_blocked_count": shadow_gate_blocked_count,
        "paper_observation_blocked_count": paper_observation_blocked_count,
        "strategy_version_proposal_blocked_count": strategy_version_proposal_blocked_count,
        "unsafe_count": unsafe_count,
    }


def _validation_events(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    events = _validation_payload(evidence).get("review_events")
    if not isinstance(events, list):
        return []
    return [dict(event) for event in events if isinstance(event, dict)]


def _validation_payload(evidence: dict[str, Any]) -> dict[str, Any]:
    validation = evidence.get("validation")
    return dict(validation) if isinstance(validation, dict) else {}


def _validation_values(evidence: dict[str, Any], key: str) -> list[str]:
    values = _validation_payload(evidence).get(key)
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _normalized_evidence_ids(values: tuple[str, ...]) -> list[str]:
    return [str(value).strip() for value in values if str(value).strip()]


def _normalized_backtest_artifact_paths(value: str | None) -> list[str]:
    if value is None:
        return []
    text = str(value).strip()
    return [str(Path(text).expanduser())] if text else []


def _merge_validation_values(existing: list[str], new_values: list[str]) -> list[str]:
    merged: list[str] = []
    for value in [*existing, *new_values]:
        if value and value not in merged:
            merged.append(value)
    return merged


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _list_mapping(value: object) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _list_text(value: object) -> list[str]:
    if isinstance(value, Mapping):
        return [str(item) for item in value.values() if item not in (None, "")]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    if value in (None, ""):
        return []
    return [str(value)]


def _load_current_strategy(conn: sqlite3.Connection, strategy_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, strategy_key, strategy_version, params_hash, status
        FROM strategy_versions
        WHERE strategy_key = ?
        ORDER BY
          CASE status
            WHEN 'live' THEN 0
            WHEN 'paper' THEN 1
            WHEN 'candidate' THEN 2
            WHEN 'research' THEN 3
            WHEN 'draft' THEN 4
            ELSE 5
          END,
          id DESC
        LIMIT 1
        """,
        (strategy_id,),
    ).fetchone()


def _current_strategy_payload(current_strategy: sqlite3.Row | None, strategy_id: str) -> dict[str, Any]:
    if current_strategy is None:
        return {
            "strategy_id": strategy_id,
            "current_strategy_version_id": None,
            "current_strategy_version": None,
            "current_params_hash": None,
            "current_status": None,
        }
    return {
        "strategy_id": strategy_id,
        "current_strategy_version_id": int(current_strategy["id"]),
        "current_strategy_version": current_strategy["strategy_version"],
        "current_params_hash": current_strategy["params_hash"],
        "current_status": current_strategy["status"],
    }


def _load_shadow_research_artifacts(
    request: RegisterShadowStrategyCandidatesRequest,
    reports_dir: Path,
) -> _ShadowResearchArtifacts | list[ServiceError]:
    paths = {
        "shadow_review": _shadow_artifact_path(
            reports_dir,
            request.shadow_review_artifact_path,
            SHADOW_RESEARCH_ARTIFACTS["shadow_review"],
        ),
        "shadow_backtest": _shadow_artifact_path(
            reports_dir,
            request.shadow_backtest_artifact_path,
            SHADOW_RESEARCH_ARTIFACTS["shadow_backtest"],
        ),
        "preconfirm_watchlist": _shadow_artifact_path(
            reports_dir,
            request.preconfirm_watchlist_artifact_path,
            SHADOW_RESEARCH_ARTIFACTS["preconfirm_watchlist"],
        ),
        "dip_buy": _shadow_artifact_path(
            reports_dir,
            request.dip_buy_artifact_path,
            SHADOW_RESEARCH_ARTIFACTS["dip_buy"],
        ),
    }
    loaded: dict[str, dict[str, Any]] = {}
    errors: list[ServiceError] = []
    for artifact_key, path in paths.items():
        payload_or_error = _read_shadow_json_artifact(path, artifact_key)
        if isinstance(payload_or_error, ServiceError):
            errors.append(payload_or_error)
        else:
            loaded[artifact_key] = payload_or_error
    if errors:
        return errors
    return _ShadowResearchArtifacts(
        shadow_review_path=paths["shadow_review"],
        shadow_review=loaded["shadow_review"],
        shadow_backtest_path=paths["shadow_backtest"],
        shadow_backtest=loaded["shadow_backtest"],
        preconfirm_watchlist_path=paths["preconfirm_watchlist"],
        preconfirm_watchlist=loaded["preconfirm_watchlist"],
        dip_buy_path=paths["dip_buy"],
        dip_buy=loaded["dip_buy"],
    )


def _shadow_artifact_path(reports_dir: Path, explicit_path: str | None, default_name: str) -> Path:
    if explicit_path is not None:
        return Path(explicit_path).expanduser()
    return reports_dir / default_name


def _read_shadow_json_artifact(path: Path, artifact_key: str) -> dict[str, Any] | ServiceError:
    if not path.exists():
        return ServiceError(
            code="SHADOW_RESEARCH_ARTIFACT_NOT_FOUND",
            message=f"shadow research artifact was not found: {path}",
            entity_type=artifact_key,
        )
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ServiceError(
            code="SHADOW_RESEARCH_ARTIFACT_INVALID",
            message=f"shadow research artifact is not valid JSON: {path}: {exc}",
            entity_type=artifact_key,
        )
    if not isinstance(loaded, dict):
        return ServiceError(
            code="SHADOW_RESEARCH_ARTIFACT_INVALID",
            message=f"shadow research artifact must be a JSON object: {path}",
            entity_type=artifact_key,
        )
    return loaded


def _generate_shadow_candidates(
    as_of_date: str,
    artifacts: _ShadowResearchArtifacts,
) -> list[StrategyHypothesis]:
    candidates: list[StrategyHypothesis] = []
    for candidate_key, title, rationale in [
        (
            "trend_extension_shadow",
            "Shadow candidate: trend-extension continuation bucket.",
            "M69 shadow research showed strong-trend continuation misses that are outside frozen CPB pullback rules.",
        ),
        (
            "breakout_pressure_shadow",
            "Shadow candidate: breakout-pressure bucket.",
            "M69 shadow research found near-high pressure setups with intraday optionality but unstable close returns.",
        ),
        (
            "low_price_momentum_shadow",
            "Shadow candidate: low-price momentum micro-sleeve.",
            "Low-price movers explain part of CPB misses, but risk, liquidity, and sizing must remain separate.",
        ),
    ]:
        candidates.append(
            _shadow_bucket_hypothesis(
                as_of_date=as_of_date,
                candidate_key=candidate_key,
                title=title,
                rationale=rationale,
                artifacts=artifacts,
            )
        )
    candidates.append(_preconfirm_watchlist_shadow_hypothesis(as_of_date, artifacts))
    candidates.append(_dip_buy_shadow_hypothesis(as_of_date, artifacts))
    return candidates


def _shadow_bucket_hypothesis(
    *,
    as_of_date: str,
    candidate_key: str,
    title: str,
    rationale: str,
    artifacts: _ShadowResearchArtifacts,
) -> StrategyHypothesis:
    shadow_review = artifacts.shadow_review
    shadow_backtest = artifacts.shadow_backtest
    daily_metrics = _summary_row(shadow_backtest, f"daily_top1_{candidate_key}")
    all_metrics = _summary_row(shadow_backtest, f"all_{candidate_key}")
    active_metrics = _summary_row(shadow_backtest, "active_cpb_persisted_picks")
    missed_counts = shadow_review.get("gainer5_shadow_bucket_counts")
    shadow_rules = shadow_review.get("shadow_rule_v0")
    comparison = {
        "candidate_key": candidate_key,
        "candidate_family": "shadow_bucket",
        "review_window": {
            "start_date": shadow_backtest.get("start_date"),
            "end_date": shadow_backtest.get("end_date"),
            "days": daily_metrics.get("days"),
        },
        "missed_gainer5_count": (
            missed_counts.get(candidate_key)
            if isinstance(missed_counts, dict)
            else None
        ),
        "rule_summary": shadow_rules.get(candidate_key) if isinstance(shadow_rules, dict) else None,
        "daily_top1_metrics": _compact_shadow_metrics(daily_metrics),
        "all_candidate_metrics": _compact_shadow_metrics(all_metrics),
        "frozen_cpb_baseline": _compact_shadow_metrics(active_metrics),
        "source_artifacts": {
            "shadow_review": str(artifacts.shadow_review_path),
            "shadow_backtest": str(artifacts.shadow_backtest_path),
        },
        "limitations": [
            "Research-only shadow labels; no active CPB behavior changed.",
            "Frozen CPB baseline has a small persisted-pick sample in this window.",
            "Requires forward monitoring before paper observation.",
        ],
    }
    return _shadow_candidate_hypothesis(
        as_of_date=as_of_date,
        hypothesis_type=f"shadow_{candidate_key}",
        title=title,
        rationale=rationale,
        candidate_key=candidate_key,
        candidate_family="shadow_bucket",
        comparison=comparison,
        artifact_paths=[artifacts.shadow_review_path, artifacts.shadow_backtest_path],
        extra_paper_blockers=_candidate_specific_paper_blockers(candidate_key),
        extra_strategy_version_blockers=_candidate_specific_strategy_version_blockers(candidate_key),
    )


def _preconfirm_watchlist_shadow_hypothesis(
    as_of_date: str,
    artifacts: _ShadowResearchArtifacts,
) -> StrategyHypothesis:
    preconfirm = artifacts.preconfirm_watchlist
    high_potential = _preconfirm_summary_row(preconfirm, "高潜伏预警")
    all_watch = _preconfirm_summary_row(preconfirm, "全部")
    active_metrics = _summary_row(artifacts.shadow_backtest, "active_cpb_persisted_picks")
    comparison = {
        "candidate_key": "preconfirm_watchlist",
        "candidate_family": "preconfirm_watchlist",
        "review_window": {
            "start_date": preconfirm.get("meta", {}).get("start_date") if isinstance(preconfirm.get("meta"), dict) else None,
            "end_date": preconfirm.get("meta", {}).get("end_date") if isinstance(preconfirm.get("meta"), dict) else None,
            "review_days": high_potential.get("review_days"),
        },
        "high_potential_metrics": _compact_preconfirm_metrics(high_potential),
        "all_watchlist_metrics": _compact_preconfirm_metrics(all_watch),
        "frozen_cpb_baseline": _compact_shadow_metrics(active_metrics),
        "source_artifacts": {"preconfirm_watchlist": str(artifacts.preconfirm_watchlist_path)},
        "limitations": [
            "Pre-confirm output is a watchlist, not an automatic buy list.",
            "Next-day confirmation and operator review are required before paper observation.",
        ],
    }
    return _shadow_candidate_hypothesis(
        as_of_date=as_of_date,
        hypothesis_type="shadow_preconfirm_watchlist",
        title="Shadow candidate: pre-confirm watchlist observation lane.",
        rationale=(
            "M69 pre-confirm research can surface names before CPB confirmation, but its low confirmation rate "
            "requires an explicit observation lane rather than trade-plan generation."
        ),
        candidate_key="preconfirm_watchlist",
        candidate_family="preconfirm_watchlist",
        comparison=comparison,
        artifact_paths=[artifacts.preconfirm_watchlist_path],
        extra_paper_blockers=_candidate_specific_paper_blockers("preconfirm_watchlist"),
        extra_strategy_version_blockers=_candidate_specific_strategy_version_blockers("preconfirm_watchlist"),
    )


def _dip_buy_shadow_hypothesis(
    as_of_date: str,
    artifacts: _ShadowResearchArtifacts,
) -> StrategyHypothesis:
    dip_buy = artifacts.dip_buy
    selected_groups = dip_buy.get("selected_groups")
    score_groups = selected_groups.get("score") if isinstance(selected_groups, dict) else []
    age_groups = selected_groups.get("age") if isinstance(selected_groups, dict) else []
    all_score = _first_group_row(score_groups, "全部")
    high_score = _first_group_row(score_groups, "潜力分>=75")
    age_9_13 = _first_group_row(age_groups, "9-13天")
    comparison = {
        "candidate_key": "pullback_dip_buy",
        "candidate_family": "dip_buy",
        "selected_variant": dip_buy.get("selected_variant"),
        "selected_params": dip_buy.get("selected_params"),
        "all_score_metrics": _compact_dip_buy_metrics(all_score),
        "high_score_metrics": _compact_dip_buy_metrics(high_score),
        "age_9_13_metrics": _compact_dip_buy_metrics(age_9_13),
        "source_artifacts": {"dip_buy": str(artifacts.dip_buy_path)},
        "limitations": [
            "Dip-buy entries are earlier than CPB confirmation and can buy into drawdown.",
            "Requires sizing, stop, and observation rules before any paper use.",
        ],
    }
    return _shadow_candidate_hypothesis(
        as_of_date=as_of_date,
        hypothesis_type="shadow_pullback_dip_buy",
        title="Shadow candidate: pullback dip-buy observation lane.",
        rationale=(
            "M69 dip-buy research found a possible deep-retrace observation variant, but it must stay separate "
            "from confirmed CPB entries until drawdown controls are validated."
        ),
        candidate_key="pullback_dip_buy",
        candidate_family="dip_buy",
        comparison=comparison,
        artifact_paths=[artifacts.dip_buy_path],
        extra_paper_blockers=_candidate_specific_paper_blockers("pullback_dip_buy"),
        extra_strategy_version_blockers=_candidate_specific_strategy_version_blockers("pullback_dip_buy"),
    )


def _shadow_candidate_hypothesis(
    *,
    as_of_date: str,
    hypothesis_type: str,
    title: str,
    rationale: str,
    candidate_key: str,
    candidate_family: str,
    comparison: dict[str, Any],
    artifact_paths: list[Path],
    extra_paper_blockers: list[str],
    extra_strategy_version_blockers: list[str],
) -> StrategyHypothesis:
    paper_blockers = _shadow_base_paper_blockers() + extra_paper_blockers
    strategy_version_blockers = _shadow_base_strategy_version_blockers() + extra_strategy_version_blockers
    evidence = {
        "source": SHADOW_RESEARCH_SOURCE,
        "as_of_date": as_of_date,
        "artifact_only": True,
        "candidate_key": candidate_key,
        "candidate_family": candidate_family,
        "artifact_paths": [str(path) for path in artifact_paths],
        "shadow_comparison": comparison,
        "paper_observation_gate": _blocked_gate_payload("paper_observation", paper_blockers),
        "strategy_version_gate": _blocked_gate_payload("strategy_version_proposal", strategy_version_blockers),
    }
    proposed_change = {
        "strategy_id": "cpb_6157",
        "change_type": "shadow_candidate",
        "candidate_key": candidate_key,
        "candidate_family": candidate_family,
        "artifact_only": True,
        "requires_replay_backtest": True,
        "requires_shadow_comparison": True,
        "paper_observation_allowed": False,
        "strategy_version_proposal_allowed": False,
        "paper_observation_blockers": paper_blockers,
        "strategy_version_proposal_blockers": strategy_version_blockers,
        "mutates_active_params": False,
    }
    return StrategyHypothesis(
        as_of_date=as_of_date,
        hypothesis_type=hypothesis_type,
        title=title,
        rationale=rationale,
        evidence=evidence,
        proposed_change=proposed_change,
    )


def _blocked_gate_payload(gate_type: str, blockers: list[str]) -> dict[str, Any]:
    return {
        "gate_type": gate_type,
        "status": "blocked",
        "allowed": False,
        "blockers": _merge_validation_values([], blockers),
        "clearance_required": True,
        "artifact_only": True,
    }


def _shadow_base_paper_blockers() -> list[str]:
    return [
        "paper_observation_not_authorized",
        "walk_forward_shadow_monitor_20_trading_days_required",
        "operator_review_required",
    ]


def _shadow_base_strategy_version_blockers() -> list[str]:
    return [
        "strategy_version_proposal_not_authorized",
        "replay_backtest_result_artifact_required",
        "proposal_review_required",
        "operator_promotion_approval_required",
    ]


def _candidate_specific_paper_blockers(candidate_key: str) -> list[str]:
    mapping = {
        "trend_extension_shadow": ["sector_evidence_confirmation_required", "chase_gap_guard_required"],
        "breakout_pressure_shadow": ["volume_overheat_guard_required", "close_return_stability_required"],
        "low_price_momentum_shadow": ["micro_sleeve_risk_model_required", "liquidity_slippage_review_required"],
        "preconfirm_watchlist": ["next_day_confirmation_rule_required", "watchlist_only_ui_lane_required"],
        "pullback_dip_buy": ["dip_buy_stop_and_sizing_required", "falling_knife_guard_required"],
    }
    return mapping.get(candidate_key, [])


def _candidate_specific_strategy_version_blockers(candidate_key: str) -> list[str]:
    mapping = {
        "trend_extension_shadow": ["separate_trend_extension_candidate_required"],
        "breakout_pressure_shadow": ["separate_breakout_pressure_candidate_required"],
        "low_price_momentum_shadow": ["separate_low_price_micro_sleeve_required"],
        "preconfirm_watchlist": ["watchlist_to_signal_contract_required"],
        "pullback_dip_buy": ["separate_dip_buy_candidate_required"],
    }
    return mapping.get(candidate_key, [])


def _summary_row(payload: dict[str, Any], label: str) -> dict[str, Any]:
    rows = payload.get("summary")
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if isinstance(row, dict) and row.get("label") == label:
            return dict(row)
    return {}


def _preconfirm_summary_row(payload: dict[str, Any], pre_action: str) -> dict[str, Any]:
    rows = payload.get("summary")
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if isinstance(row, dict) and row.get("pre_action") == pre_action:
            return dict(row)
    return {}


def _first_group_row(rows: object, group: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if isinstance(row, dict) and row.get("group") == group:
            return dict(row)
    return {}


def _compact_shadow_metrics(row: dict[str, Any]) -> dict[str, Any]:
    return _compact_metrics(
        row,
        [
            "label",
            "n",
            "days",
            "t1_close_mean_pct",
            "t1_close_median_pct",
            "t1_close_win_rate_pct",
            "t1_high_mean_pct",
            "t1_high_ge3_rate_pct",
            "t3_high_mean_pct",
            "t3_high_ge5_rate_pct",
            "t5_close_mean_pct",
            "t5_close_win_rate_pct",
            "max_t1_loss_pct",
            "max_t1_gain_pct",
        ],
    )


def _compact_preconfirm_metrics(row: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_metrics(
        row,
        [
            "pre_action",
            "signals",
            "review_days",
            "stocks",
            "confirm_next_day_n",
            "avg_bigwin_score",
            "next_open_ret_1d_n",
            "next_open_ret_3d_n",
            "next_open_ret_5d_n",
        ],
    )
    for source_key, target_key in [
        ("confirm_next_day_rate", "confirm_next_day_rate_pct"),
        ("next_open_ret_1d_mean", "next_open_ret_1d_mean_pct"),
        ("next_open_ret_3d_mean", "next_open_ret_3d_mean_pct"),
        ("next_open_ret_5d_mean", "next_open_ret_5d_mean_pct"),
        ("watch_mfe_5d_mean", "watch_mfe_5d_mean_pct"),
    ]:
        if source_key in row:
            compact[target_key] = _ratio_to_pct(row.get(source_key))
    return compact


def _compact_dip_buy_metrics(row: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_metrics(
        row,
        [
            "group",
            "ret_3d_n",
            "ret_5d_n",
            "ret_10d_n",
            "mfe_10d_n",
            "mae_10d_n",
        ],
    )
    for source_key, target_key in [
        ("ret_5d_win_rate", "ret_5d_win_rate_pct"),
        ("ret_5d_mean", "ret_5d_mean_pct"),
        ("ret_5d_median", "ret_5d_median_pct"),
        ("ret_5d_p25", "ret_5d_p25_pct"),
        ("ret_10d_median", "ret_10d_median_pct"),
        ("mfe_10d_median", "mfe_10d_median_pct"),
        ("mae_10d_median", "mae_10d_median_pct"),
    ]:
        if source_key in row:
            compact[target_key] = _ratio_to_pct(row.get(source_key))
    return compact


def _compact_metrics(row: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: row.get(key) for key in keys if key in row}


def _ratio_to_pct(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value) * 100, 4)
    except (TypeError, ValueError):
        return None


def _shadow_register_summary(hypotheses: list[StrategyHypothesis]) -> dict[str, Any]:
    by_family: dict[str, int] = {}
    blockers: dict[str, int] = {}
    for hypothesis in hypotheses:
        family = str(hypothesis.proposed_change.get("candidate_family") or "unknown")
        by_family[family] = by_family.get(family, 0) + 1
        for blocker in _shadow_strategy_version_blockers(hypothesis):
            blockers[blocker] = blockers.get(blocker, 0) + 1
    return {
        "shadow_candidate_count": len(hypotheses),
        "by_candidate_family": by_family,
        "strategy_version_blocked_count": len(
            [hypothesis for hypothesis in hypotheses if _shadow_strategy_version_blockers(hypothesis)]
        ),
        "paper_observation_blocked_count": len(
            [hypothesis for hypothesis in hypotheses if _shadow_paper_observation_blockers(hypothesis)]
        ),
        "top_strategy_version_blockers": blockers,
        "artifact_only": True,
        "safety": {
            "active_params_mutated": False,
            "wrote_strategy_versions": False,
            "writes_trade_state": False,
            "writes_paper_live_behavior": False,
            "timer_mutated": False,
            "shadow_candidates_artifact_only": True,
        },
    }


def _load_market_observations(conn: sqlite3.Connection, as_of_date: str) -> _MarketObservations:
    run = conn.execute(
        """
        SELECT id
        FROM market_review_runs
        WHERE as_of_date = ? AND status = 'completed'
        ORDER BY id DESC
        LIMIT 1
        """,
        (as_of_date,),
    ).fetchone()
    run_id = int(run["id"]) if run is not None else None

    regime = conn.execute(
        """
        SELECT *
        FROM market_regime_snapshots
        WHERE as_of_date = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (as_of_date,),
    ).fetchone()

    persistent_sectors = conn.execute(
        """
        SELECT *
        FROM sector_daily_snapshots
        WHERE as_of_date = ?
          AND rank_overall IS NOT NULL
          AND rank_overall <= ?
          AND persistence_score IS NOT NULL
        ORDER BY rank_overall ASC, persistence_score DESC
        LIMIT 10
        """,
        (as_of_date, TOP_SECTOR_RANK_LIMIT),
    ).fetchall()
    persistent_sectors = [
        row for row in persistent_sectors if _score_meets(row["persistence_score"], SECTOR_PERSISTENCE_THRESHOLD)
    ]

    leader_rows = conn.execute(
        """
        SELECT
          s.market_review_run_id,
          s.as_of_date,
          s.sector_code,
          s.sector_name,
          s.rank_overall,
          s.persistence_score,
          c.ts_code,
          c.name,
          c.rank_in_sector,
          c.role,
          c.score
        FROM sector_daily_snapshots s
        JOIN sector_constituents c
          ON c.market_review_run_id = s.market_review_run_id
         AND c.sector_code = s.sector_code
        WHERE s.as_of_date = ?
          AND s.rank_overall IS NOT NULL
          AND s.rank_overall <= ?
          AND c.role = 'leader'
        ORDER BY s.rank_overall ASC, c.rank_in_sector ASC
        LIMIT 20
        """,
        (as_of_date, TOP_SECTOR_RANK_LIMIT),
    ).fetchall()

    negative_news_rows = conn.execute(
        """
        SELECT id, as_of_date, scope_key, title, summary, provider, published_date, url
        FROM market_external_items
        WHERE as_of_date = ?
          AND scope_type = 'stock'
          AND sentiment = 'negative'
          AND importance = 'high'
        ORDER BY published_date DESC, id DESC
        LIMIT 20
        """,
        (as_of_date,),
    ).fetchall()

    conflicted_plan_rows: list[sqlite3.Row] = []
    if run_id is not None:
        conflicted_plan_rows = conn.execute(
            """
            SELECT id, market_review_run_id, trade_plan_id, alignment, risk_level, management_action, rationale
            FROM market_plan_contexts
            WHERE market_review_run_id = ?
              AND (
                alignment = 'conflict'
                OR risk_level = 'high'
                OR management_action IN ('manual_review', 'consider_cancel')
              )
            ORDER BY id ASC
            LIMIT 20
            """,
            (run_id,),
        ).fetchall()

    return _MarketObservations(
        run_id=run_id,
        regime=regime,
        persistent_sectors=persistent_sectors,
        leader_rows=leader_rows,
        negative_news_rows=negative_news_rows,
        conflicted_plan_rows=conflicted_plan_rows,
    )


def _generate_hypotheses(as_of_date: str, observations: _MarketObservations) -> list[StrategyHypothesis]:
    hypotheses: list[StrategyHypothesis] = []
    if observations.regime is not None and observations.regime["regime"] == "risk_off":
        hypotheses.append(_risk_off_position_size_hypothesis(as_of_date, observations.regime))
    if observations.persistent_sectors:
        hypotheses.append(_sector_persistence_hypothesis(as_of_date, observations.persistent_sectors))
    if observations.negative_news_rows:
        hypotheses.append(_negative_news_manual_review_hypothesis(as_of_date, observations.negative_news_rows))
    if observations.leader_rows:
        hypotheses.append(_sector_leader_rank_boost_hypothesis(as_of_date, observations.leader_rows))
    if observations.conflicted_plan_rows:
        hypotheses.append(_plan_conflict_manual_review_hypothesis(as_of_date, observations.conflicted_plan_rows))
    return hypotheses


def _risk_off_position_size_hypothesis(as_of_date: str, row: sqlite3.Row) -> StrategyHypothesis:
    evidence = {
        "source": "market_regime_snapshots",
        "market_review_run_id": row["market_review_run_id"],
        "as_of_date": as_of_date,
        "regime": row["regime"],
        "scores": {
            "breadth": row["breadth_score"],
            "trend": row["trend_score"],
            "volume": row["volume_score"],
            "sentiment": row["sentiment_score"],
            "persistence": row["persistence_score"],
        },
        "summary": row["summary"],
    }
    proposed_change = {
        "strategy_id": "cpb_6157",
        "change_type": "risk_control",
        "rule": {
            "when": {"market_regime": "risk_off"},
            "position_size_multiplier": 0.5,
        },
        "requires_replay_backtest": True,
        "mutates_active_params": False,
    }
    return StrategyHypothesis(
        as_of_date=as_of_date,
        hypothesis_type="market_regime_position_sizing",
        title="Reduce position size when market regime is risk_off.",
        rationale="The market-review regime snapshot flagged risk_off, so CPB entries should be tested with lower exposure.",
        evidence=evidence,
        proposed_change=proposed_change,
    )


def _sector_persistence_hypothesis(as_of_date: str, rows: list[sqlite3.Row]) -> StrategyHypothesis:
    sectors = [
        {
            "sector_code": row["sector_code"],
            "sector_name": row["sector_name"],
            "rank_overall": row["rank_overall"],
            "persistence_score": row["persistence_score"],
            "return_5d": row["return_5d"],
            "leader_count": row["leader_count"],
        }
        for row in rows
    ]
    evidence = {
        "source": "sector_daily_snapshots",
        "as_of_date": as_of_date,
        "threshold": SECTOR_PERSISTENCE_THRESHOLD,
        "top_sector_rank_limit": TOP_SECTOR_RANK_LIMIT,
        "sectors": sectors,
    }
    proposed_change = {
        "strategy_id": "cpb_6157",
        "change_type": "candidate_filter",
        "rule": {
            "require_sector_rank_lte": TOP_SECTOR_RANK_LIMIT,
            "require_persistence_score_gte": SECTOR_PERSISTENCE_THRESHOLD,
        },
        "requires_replay_backtest": True,
        "mutates_active_params": False,
    }
    return StrategyHypothesis(
        as_of_date=as_of_date,
        hypothesis_type="sector_persistence_filter",
        title="Only buy CPB candidates when their sector persistence score is above threshold.",
        rationale="Top-ranked sectors with persistent strength may improve CPB selectivity and reduce weak-theme entries.",
        evidence=evidence,
        proposed_change=proposed_change,
    )


def _negative_news_manual_review_hypothesis(as_of_date: str, rows: list[sqlite3.Row]) -> StrategyHypothesis:
    items = [
        {
            "external_item_id": row["id"],
            "ts_code": row["scope_key"],
            "title": row["title"],
            "summary": row["summary"],
            "provider": row["provider"],
            "published_date": row["published_date"],
            "url": row["url"],
        }
        for row in rows
    ]
    evidence = {
        "source": "market_external_items",
        "as_of_date": as_of_date,
        "filter": {"scope_type": "stock", "sentiment": "negative", "importance": "high"},
        "items": items,
    }
    proposed_change = {
        "strategy_id": "cpb_6157",
        "change_type": "manual_review_gate",
        "rule": {"when_stock_news": {"sentiment": "negative", "importance": "high"}},
        "requires_replay_backtest": True,
        "mutates_active_params": False,
    }
    return StrategyHypothesis(
        as_of_date=as_of_date,
        hypothesis_type="negative_news_manual_review",
        title="Require manual review for candidates with high negative stock news importance.",
        rationale="High-importance negative stock-level evidence should be tested as a manual gate before CPB buys.",
        evidence=evidence,
        proposed_change=proposed_change,
    )


def _sector_leader_rank_boost_hypothesis(as_of_date: str, rows: list[sqlite3.Row]) -> StrategyHypothesis:
    leaders = [
        {
            "market_review_run_id": row["market_review_run_id"],
            "sector_code": row["sector_code"],
            "sector_name": row["sector_name"],
            "sector_rank": row["rank_overall"],
            "ts_code": row["ts_code"],
            "name": row["name"],
            "rank_in_sector": row["rank_in_sector"],
            "score": row["score"],
        }
        for row in rows
    ]
    evidence = {
        "source": "sector_daily_snapshots+sector_constituents",
        "as_of_date": as_of_date,
        "top_sector_rank_limit": TOP_SECTOR_RANK_LIMIT,
        "leaders": leaders,
    }
    proposed_change = {
        "strategy_id": "cpb_6157",
        "change_type": "ranking_feature",
        "rule": {"boost_when": {"sector_rank_lte": TOP_SECTOR_RANK_LIMIT, "sector_role": "leader"}},
        "requires_replay_backtest": True,
        "mutates_active_params": False,
    }
    return StrategyHypothesis(
        as_of_date=as_of_date,
        hypothesis_type="sector_leader_rank_boost",
        title="Boost rank when stock is sector leader and sector is in top 5.",
        rationale="Sector leaders inside top sectors may deserve a scoring boost, but this needs replay validation first.",
        evidence=evidence,
        proposed_change=proposed_change,
    )


def _plan_conflict_manual_review_hypothesis(as_of_date: str, rows: list[sqlite3.Row]) -> StrategyHypothesis:
    contexts = [
        {
            "market_plan_context_id": row["id"],
            "market_review_run_id": row["market_review_run_id"],
            "trade_plan_id": row["trade_plan_id"],
            "alignment": row["alignment"],
            "risk_level": row["risk_level"],
            "management_action": row["management_action"],
            "rationale": row["rationale"],
        }
        for row in rows
    ]
    evidence = {
        "source": "market_plan_contexts",
        "as_of_date": as_of_date,
        "contexts": contexts,
    }
    proposed_change = {
        "strategy_id": "cpb_6157",
        "change_type": "manual_review_gate",
        "rule": {
            "when_market_plan_context": {
                "alignment": "conflict",
                "risk_level": "high",
                "management_action": ["manual_review", "consider_cancel"],
            }
        },
        "requires_replay_backtest": True,
        "mutates_active_params": False,
    }
    return StrategyHypothesis(
        as_of_date=as_of_date,
        hypothesis_type="market_plan_conflict_manual_review",
        title="Require manual review when market-plan context conflicts with a candidate.",
        rationale="Market-plan conflicts should become a tested review gate rather than an automatic plan change.",
        evidence=evidence,
        proposed_change=proposed_change,
    )


def _score_meets(value: object, threshold: float) -> bool:
    if value is None:
        return False
    score = float(value)
    comparable_threshold = threshold * 100 if score > 1 else threshold
    return score >= comparable_threshold


def _find_existing_hypothesis_id(conn: sqlite3.Connection, hypothesis: StrategyHypothesis) -> int | None:
    row = conn.execute(
        """
        SELECT id
        FROM strategy_hypotheses
        WHERE as_of_date = ?
          AND hypothesis_type = ?
          AND title = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        (hypothesis.as_of_date, hypothesis.hypothesis_type, hypothesis.title),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def _insert_hypothesis(conn: sqlite3.Connection, hypothesis: StrategyHypothesis) -> StrategyHypothesis:
    cursor = conn.execute(
        """
        INSERT INTO strategy_hypotheses
          (as_of_date, hypothesis_type, title, rationale, evidence_json, proposed_change_json, status)
        VALUES
          (?, ?, ?, ?, ?, ?, 'proposed')
        """,
        (
            hypothesis.as_of_date,
            hypothesis.hypothesis_type,
            hypothesis.title,
            hypothesis.rationale,
            _json_dumps(hypothesis.evidence),
            _json_dumps(hypothesis.proposed_change),
        ),
    )
    inserted_id = int(cursor.lastrowid)
    inserted = _get_hypothesis(conn, inserted_id)
    if inserted is None:
        raise RuntimeError(f"inserted strategy hypothesis id={inserted_id} was not found")
    return inserted


def _list_hypotheses(
    conn: sqlite3.Connection,
    request: ListStrategyHypothesesRequest,
) -> list[StrategyHypothesis]:
    clauses: list[str] = []
    params: list[object] = []
    if request.status is not None:
        clauses.append("status = ?")
        params.append(request.status)
    if request.as_of_date is not None:
        clauses.append("as_of_date = ?")
        params.append(request.as_of_date)

    sql = "SELECT * FROM strategy_hypotheses"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY as_of_date DESC, id DESC"
    if request.limit is not None:
        sql += " LIMIT ?"
        params.append(request.limit)

    return [_hypothesis_from_row(row) for row in conn.execute(sql, params).fetchall()]


def _get_hypothesis(conn: sqlite3.Connection, hypothesis_id: int) -> StrategyHypothesis | None:
    row = conn.execute("SELECT * FROM strategy_hypotheses WHERE id = ?", (hypothesis_id,)).fetchone()
    if row is None:
        return None
    return _hypothesis_from_row(row)


def _hypothesis_from_row(row: sqlite3.Row) -> StrategyHypothesis:
    return StrategyHypothesis(
        hypothesis_id=int(row["id"]),
        as_of_date=row["as_of_date"],
        hypothesis_type=row["hypothesis_type"],
        title=row["title"],
        rationale=row["rationale"],
        evidence=_json_loads(row["evidence_json"]),
        proposed_change=_json_loads(row["proposed_change_json"]),
        status=row["status"],
        created_at=row["created_at"],
    )


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(payload: str) -> dict[str, Any]:
    loaded = json.loads(payload or "{}")
    return loaded if isinstance(loaded, dict) else {}
