"""Strategy hypothesis backtest request bridge.

The bridge turns a stored strategy hypothesis into an explicit replay/backtest
request artifact. It deliberately does not mutate strategy params, strategy
versions, trade plans, trades, positions, or backtest result tables.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pgc_trading.config import Paths, StrategyConfig
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult, ServiceWarning
from pgc_trading.storage.database import connect


@dataclass(frozen=True)
class CreateStrategyHypothesisBacktestRequest:
    hypothesis_id: int


@dataclass(frozen=True)
class StrategyHypothesisBacktestResult:
    hypothesis_id: int | None = None
    hypothesis_status: str | None = None
    strategy_version_task_required: bool = False
    would_write_artifact: bool = False
    wrote_artifact: bool = False
    artifact_path: str | None = None
    active_params_mutated: bool = False
    artifact: dict[str, Any] = field(default_factory=dict)


class StrategyHypothesisBacktestService:
    """Build replay/backtest requests from strategy-evolution hypotheses."""

    def __init__(self, db_path: Path | None = None, reports_dir: Path | None = None):
        self.db_path = db_path or Paths().db_path
        self.reports_dir = reports_dir or Paths().reports_dir

    def create_backtest_request(
        self,
        request: CreateStrategyHypothesisBacktestRequest,
        ctx: RequestContext,
    ) -> ServiceResult[StrategyHypothesisBacktestResult]:
        validation_errors = _validate_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=StrategyHypothesisBacktestResult(),
                errors=validation_errors,
            )

        with connect(self.db_path) as conn:
            hypothesis = _load_hypothesis(conn, request.hypothesis_id)
            if hypothesis is None:
                return ServiceResult(
                    status="validation_failed",
                    request_id=ctx.request_id,
                    data=StrategyHypothesisBacktestResult(),
                    errors=[
                        ServiceError(
                            code="HYPOTHESIS_NOT_FOUND",
                            message=f"strategy hypothesis id={request.hypothesis_id} was not found.",
                            entity_type="strategy_hypothesis",
                            entity_id=request.hypothesis_id,
                        )
                    ],
                )

            proposed_change = _json_loads(hypothesis["proposed_change_json"])
            if bool(proposed_change.get("mutates_active_params")):
                return ServiceResult(
                    status="validation_failed",
                    request_id=ctx.request_id,
                    data=StrategyHypothesisBacktestResult(
                        hypothesis_id=request.hypothesis_id,
                        hypothesis_status=hypothesis["status"],
                    ),
                    errors=[
                        ServiceError(
                            code="ACTIVE_PARAM_MUTATION_FORBIDDEN",
                            message=(
                                "strategy hypothesis proposed_change_json must not request active parameter mutation."
                            ),
                            entity_type="strategy_hypothesis",
                            entity_id=request.hypothesis_id,
                        )
                    ],
                )

            strategy_id = str(proposed_change.get("strategy_id") or StrategyConfig().strategy_id)
            current_strategy = _load_current_strategy(conn, strategy_id)

        artifact = _build_artifact(
            hypothesis=hypothesis,
            proposed_change=proposed_change,
            current_strategy=current_strategy,
            operator=ctx.operator,
        )
        status = str(hypothesis["status"])
        artifact_path = self._artifact_path(request.hypothesis_id)
        warnings = _build_warnings(status=status, current_strategy=current_strategy)

        if ctx.dry_run:
            warnings.append(
                ServiceWarning(
                    code="BACKTEST_REQUEST_DRY_RUN",
                    message="Backtest request artifact was built in memory only; no file or strategy state was written.",
                )
            )
            return ServiceResult(
                status="success",
                request_id=ctx.request_id,
                data=StrategyHypothesisBacktestResult(
                    hypothesis_id=request.hypothesis_id,
                    hypothesis_status=status,
                    strategy_version_task_required=status == "accepted",
                    would_write_artifact=True,
                    wrote_artifact=False,
                    artifact_path=None,
                    active_params_mutated=False,
                    artifact=artifact,
                ),
                warnings=warnings,
                lineage={
                    "hypothesis_id": request.hypothesis_id,
                    "hypothesis_status": status,
                    "artifact_path": str(artifact_path),
                },
            )

        self._write_artifact(artifact_path, artifact)
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=StrategyHypothesisBacktestResult(
                hypothesis_id=request.hypothesis_id,
                hypothesis_status=status,
                strategy_version_task_required=status == "accepted",
                would_write_artifact=True,
                wrote_artifact=True,
                artifact_path=str(artifact_path),
                active_params_mutated=False,
                artifact=artifact,
            ),
            created_ids={"strategy_hypothesis_backtest_artifact": request.hypothesis_id},
            warnings=warnings,
            lineage={
                "hypothesis_id": request.hypothesis_id,
                "hypothesis_status": status,
                "artifact_path": str(artifact_path),
            },
        )

    def _artifact_path(self, hypothesis_id: int) -> Path:
        return self.reports_dir / "strategy_hypothesis_backtests" / f"hypothesis_{hypothesis_id}_backtest_request.json"

    def _write_artifact(self, path: Path, artifact: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json_dumps(artifact) + "\n", encoding="utf-8")


def _validate_request(request: CreateStrategyHypothesisBacktestRequest) -> list[ServiceError]:
    if request.hypothesis_id < 1:
        return [ServiceError(code="VALIDATION_ERROR", message="hypothesis_id must be greater than zero.")]
    return []


def _load_hypothesis(conn: sqlite3.Connection, hypothesis_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM strategy_hypotheses
        WHERE id = ?
        """,
        (hypothesis_id,),
    ).fetchone()


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


def _build_artifact(
    *,
    hypothesis: sqlite3.Row,
    proposed_change: dict[str, Any],
    current_strategy: sqlite3.Row | None,
    operator: str | None,
) -> dict[str, Any]:
    hypothesis_id = int(hypothesis["id"])
    status = str(hypothesis["status"])
    strategy_id = str(proposed_change.get("strategy_id") or StrategyConfig().strategy_id)
    strategy = _strategy_payload(current_strategy, strategy_id)
    backtest_request = _backtest_request_payload(
        hypothesis_id=hypothesis_id,
        hypothesis=hypothesis,
        proposed_change=proposed_change,
        strategy=strategy,
    )
    strategy_version_task = None
    if status == "accepted":
        strategy_version_task = _strategy_version_task_payload(
            hypothesis_id=hypothesis_id,
            hypothesis=hypothesis,
            proposed_change=proposed_change,
            strategy=strategy,
        )

    return {
        "artifact_type": "strategy_hypothesis_backtest_request",
        "artifact_version": 1,
        "operator": operator,
        "hypothesis": {
            "id": hypothesis_id,
            "as_of_date": hypothesis["as_of_date"],
            "status": status,
            "hypothesis_type": hypothesis["hypothesis_type"],
            "title": hypothesis["title"],
            "rationale": hypothesis["rationale"],
            "evidence": _json_loads(hypothesis["evidence_json"]),
            "proposed_change": proposed_change,
        },
        "strategy": strategy,
        "backtest_request": backtest_request,
        "strategy_version_task": strategy_version_task,
        "safety": {
            "active_params_mutated": False,
            "writes_trade_state": False,
            "writes_backtest_results": False,
            "requires_replay_before_param_change": True,
            "accepted_creates_separate_strategy_version_task": status == "accepted",
        },
    }


def _strategy_payload(current_strategy: sqlite3.Row | None, strategy_id: str) -> dict[str, Any]:
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


def _backtest_request_payload(
    *,
    hypothesis_id: int,
    hypothesis: sqlite3.Row,
    proposed_change: dict[str, Any],
    strategy: dict[str, Any],
) -> dict[str, Any]:
    return {
        "task_key": f"strategy-hypothesis:{hypothesis_id}:backtest",
        "task_type": "replay_backtest_request",
        "status": "pending",
        "strategy_id": strategy["strategy_id"],
        "base_strategy_version": strategy["current_strategy_version"],
        "hypothesis_type": hypothesis["hypothesis_type"],
        "sample_type": "full",
        "run_type": "backtest",
        "objective": (
            "Validate the hypothesis with replay/backtest evidence before any strategy parameter or code change."
        ),
        "proposed_change": {
            **proposed_change,
            "requires_replay_backtest": True,
            "mutates_active_params": False,
        },
        "validation_commands": [
            "PYTHONPATH=src:. pytest -q tests/test_cpb_v2_replay.py tests/test_daily_workflow_replay.py",
            "PYTHONPATH=src:. pytest -q tests/test_strategy_evolution_service.py",
        ],
        "acceptance_rules": [
            "Do not edit src/pgc_trading/strategies/params/*.json in this task.",
            "Record replay/backtest evidence before marking the hypothesis accepted.",
            "If accepted, create a separate candidate strategy-version task.",
        ],
    }


def _strategy_version_task_payload(
    *,
    hypothesis_id: int,
    hypothesis: sqlite3.Row,
    proposed_change: dict[str, Any],
    strategy: dict[str, Any],
) -> dict[str, Any]:
    return {
        "task_key": f"strategy-hypothesis:{hypothesis_id}:strategy-version",
        "task_type": "create_candidate_strategy_version",
        "status": "pending",
        "strategy_id": strategy["strategy_id"],
        "base_strategy_version": strategy["current_strategy_version"],
        "hypothesis_type": hypothesis["hypothesis_type"],
        "title": hypothesis["title"],
        "proposed_change": {
            **proposed_change,
            "mutates_active_params": False,
        },
        "acceptance_rules": [
            "Create a new draft or candidate strategy_version row rather than mutating the active version.",
            "Attach replay/backtest evidence to the promotion review.",
            "Keep paper/live deployments on the current version until explicit promotion approval.",
        ],
    }


def _build_warnings(status: str, current_strategy: sqlite3.Row | None) -> list[ServiceWarning]:
    warnings: list[ServiceWarning] = []
    if current_strategy is None:
        warnings.append(
            ServiceWarning(
                code="CURRENT_STRATEGY_VERSION_NOT_FOUND",
                message="No current strategy_version row matched the hypothesis strategy_id.",
            )
        )
    if status == "accepted":
        warnings.append(
            ServiceWarning(
                code="STRATEGY_VERSION_TASK_REQUIRED",
                message="Accepted hypothesis requires a separate strategy-version task; active params were not mutated.",
            )
        )
    return warnings


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(payload: str) -> dict[str, Any]:
    loaded = json.loads(payload or "{}")
    return loaded if isinstance(loaded, dict) else {}
