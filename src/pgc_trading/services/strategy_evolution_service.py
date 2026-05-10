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
from typing import Any

from pgc_trading.config import Paths
from pgc_trading.market.calendar import is_yyyymmdd
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult, ServiceWarning
from pgc_trading.services.strategy_hypothesis_backtest_service import (
    StrategyHypothesisBacktestArtifactReview,
    review_strategy_hypothesis_backtest_artifact,
)
from pgc_trading.storage.database import connect


VALID_HYPOTHESIS_STATUSES = {"proposed", "testing", "accepted", "rejected", "archived"}
VALID_HYPOTHESIS_TRANSITIONS = {
    "proposed": {"proposed", "testing", "rejected", "archived"},
    "testing": {"testing", "accepted", "rejected", "archived"},
    "accepted": {"accepted", "archived"},
    "rejected": {"rejected", "archived"},
    "archived": {"archived"},
}
SECTOR_PERSISTENCE_THRESHOLD = 0.7
TOP_SECTOR_RANK_LIMIT = 5


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
class MarkStrategyHypothesisRequest:
    hypothesis_id: int
    status: str
    review_note: str | None = None
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    backtest_artifact_path: str | None = None


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
class ListStrategyHypothesesResult:
    hypotheses: list[StrategyHypothesis] = field(default_factory=list)


@dataclass(frozen=True)
class StrategyHypothesisEvaluation:
    hypothesis: StrategyHypothesis
    evidence_ids: list[str] = field(default_factory=list)
    backtest_artifacts: list[StrategyHypothesisBacktestArtifactReview] = field(default_factory=list)
    validation_events: list[dict[str, Any]] = field(default_factory=list)
    acceptance_gate: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)
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
class _MarketObservations:
    run_id: int | None
    regime: sqlite3.Row | None
    persistent_sectors: list[sqlite3.Row]
    leader_rows: list[sqlite3.Row]
    negative_news_rows: list[sqlite3.Row]
    conflicted_plan_rows: list[sqlite3.Row]


class StrategyEvolutionService:
    """Generate, list, and update controlled strategy hypotheses."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

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
                    "as_of_date": request.as_of_date,
                    "status": request.status,
                    "limit": request.limit,
                },
                safety={
                    "read_only": True,
                    "active_params_mutated": False,
                    "writes_trade_state": False,
                    "writes_paper_live_behavior": False,
                    "accepted_creates_separate_strategy_version_task": True,
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
    return {
        "task_key": f"strategy-hypothesis:{hypothesis_id}:strategy-version",
        "task_type": "create_candidate_strategy_version",
        "status": "pending",
        "strategy_id": str(proposed_change.get("strategy_id") or "cpb_6157"),
        "hypothesis_id": hypothesis_id,
        "hypothesis_type": hypothesis.hypothesis_type,
        "title": hypothesis.title,
        "research_outcome_status": "accepted",
        "validation_evidence_ids": evidence_ids,
        "backtest_artifact_paths": backtest_artifact_paths,
        "proposed_change": proposed_change,
        "acceptance_rules": [
            "Create a new draft or candidate strategy_version row rather than mutating the active version.",
            "Attach replay/backtest evidence to the promotion review.",
            "Keep paper/live deployments on the current version until explicit promotion approval.",
        ],
    }


def _evaluate_hypothesis(hypothesis: StrategyHypothesis) -> StrategyHypothesisEvaluation:
    evidence_ids = _validation_values(hypothesis.evidence, "evidence_ids")
    artifact_reviews = [
        review_strategy_hypothesis_backtest_artifact(
            artifact_path,
            expected_hypothesis_id=int(hypothesis.hypothesis_id or 0),
        )
        for artifact_path in _validation_values(hypothesis.evidence, "backtest_artifacts")
    ]
    validation_events = _validation_events(hypothesis.evidence)
    acceptance_gate = _acceptance_gate_payload(hypothesis, evidence_ids, artifact_reviews)
    safety = _hypothesis_safety_payload(hypothesis, artifact_reviews)
    next_action, next_action_label = _evaluation_next_action(hypothesis, acceptance_gate, safety)
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
        validation_events=validation_events,
        acceptance_gate=acceptance_gate,
        safety=safety,
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
    return {
        "can_accept": hypothesis.status == "testing" and not blocks,
        "accepted_complete": hypothesis.status == "accepted" and not blocks,
        "testing_required": hypothesis.status == "testing",
        "has_validation_evidence": bool(evidence_ids),
        "has_backtest_artifact": has_artifact,
        "backtest_artifacts_valid": artifacts_valid,
        "requires_replay_backtest": bool(hypothesis.proposed_change.get("requires_replay_backtest", True)),
        "blocks": blocks,
    }


def _hypothesis_safety_payload(
    hypothesis: StrategyHypothesis,
    artifact_reviews: list[StrategyHypothesisBacktestArtifactReview],
) -> dict[str, Any]:
    artifact_reports_mutation = any(artifact.active_params_mutated is True for artifact in artifact_reviews)
    return {
        "read_only_evaluation": True,
        "proposed_change_mutates_active_params": bool(hypothesis.proposed_change.get("mutates_active_params")),
        "artifact_reports_active_param_mutation": artifact_reports_mutation,
        "active_params_mutated": False,
        "writes_trade_state": False,
        "writes_paper_live_behavior": False,
        "accepted_creates_separate_strategy_version_task": hypothesis.status == "accepted",
    }


def _evaluation_next_action(
    hypothesis: StrategyHypothesis,
    acceptance_gate: dict[str, Any],
    safety: dict[str, Any],
) -> tuple[str, str]:
    if safety["proposed_change_mutates_active_params"] or safety["artifact_reports_active_param_mutation"]:
        return "reject_or_rewrite", "Rewrite or reject; active parameter mutation is forbidden."
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
        return "strategy_version_task_required", "Accepted is a research outcome; create a separate strategy-version task."
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
    ready_to_accept_count = 0
    strategy_version_task_required_count = 0
    unsafe_count = 0
    for evaluation in evaluations:
        status = evaluation.hypothesis.status
        by_status[status] = by_status.get(status, 0) + 1
        by_next_action[evaluation.next_action] = by_next_action.get(evaluation.next_action, 0) + 1
        artifact_count += len(evaluation.backtest_artifacts)
        invalid_artifact_count += len([artifact for artifact in evaluation.backtest_artifacts if not artifact.valid])
        if evaluation.acceptance_gate.get("can_accept"):
            ready_to_accept_count += 1
        if evaluation.strategy_version_task is not None:
            strategy_version_task_required_count += 1
        if (
            evaluation.safety.get("proposed_change_mutates_active_params")
            or evaluation.safety.get("artifact_reports_active_param_mutation")
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
