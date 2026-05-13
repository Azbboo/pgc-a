"""First-class daily operating pipeline service."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pgc_trading.config import Paths
from pgc_trading.market.calendar import is_yyyymmdd
from pgc_trading.reporting.daily_report import (
    DailyReportRequest,
    ReportingQueryService,
    render_daily_report_json,
    render_daily_report_markdown,
)
from pgc_trading.services.agent_review_service import AgentReviewResult, AgentReviewService, ReviewDailyPickRequest
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult, ServiceWarning
from pgc_trading.services.daily_close_workflow_service import (
    DEFAULT_ACCOUNT_KEY,
    DailyCloseWorkflowService,
    RunDailyCloseWorkflowRequest,
)
from pgc_trading.services.market_plan_context_service import (
    LinkMarketPlanContextRequest,
    MarketPlanContextService,
)
from pgc_trading.services.market_review_service import MarketReviewService, RunMarketReviewRequest
from pgc_trading.services.position_lifecycle_service import EvaluateExitsRequest, PositionLifecycleService
from pgc_trading.storage.database import connect
from pgc_trading.storage.invariant_checks import check_database
from pgc_trading.storage.migrators.backup import backup_database
from pgc_trading.strategies.cpb_6157 import STRATEGY_VERSION


DailyCloseFactory = Callable[[Path], DailyCloseWorkflowService]
AgentReviewFactory = Callable[[Path], AgentReviewService]
MarketReviewFactory = Callable[[Path], MarketReviewService]
MarketPlanContextFactory = Callable[[Path], MarketPlanContextService]
PositionLifecycleFactory = Callable[[Path], PositionLifecycleService]
ReportFactory = Callable[[Path], ReportingQueryService]
BackupFunc = Callable[[Path, Path | None, str], Path]


_CHANGE_TABLES = (
    "feature_runs",
    "feature_snapshots",
    "strategy_runs",
    "strategy_signals",
    "daily_picks",
    "trade_plans",
    "input_snapshots",
    "agent_runs",
    "agent_artifacts",
    "agent_decisions",
    "market_review_runs",
    "market_regime_snapshots",
    "market_plan_contexts",
    "exit_decisions",
)


@dataclass(frozen=True)
class RunDailyPipelineRequest:
    as_of_date: str
    account_key: str | None = DEFAULT_ACCOUNT_KEY
    account_id: int | None = None
    strategy_version: str = STRATEGY_VERSION
    run_type: str = "paper"
    backup_dir: Path | None = None
    include_market_review: bool = False


@dataclass(frozen=True)
class PipelineStepSummary:
    status: str
    detail: str | None = None


@dataclass(frozen=True)
class DailyPipelineResult:
    pipeline_status: str
    review_date: str
    next_trade_date: str | None
    daily_pick_id: int | None
    trade_plan_id: int | None
    agent_run_id: int | None
    agent_decision_id: int | None
    exit_decisions: int
    report_markdown: str | None
    report_json: str | None
    changed: bool
    backup_path: str | None = None
    ledger_audit_ok: bool = False
    daily_close_status: str | None = None
    agent_status: str | None = None
    exit_status: str | None = None
    report_status: str | None = None
    report_would_write: bool = False
    market_review_run_id: int | None = None
    market_review_status: str | None = None
    market_plan_context_status: str | None = None
    market_review_would_write: bool = False
    market_plan_context_would_write: bool = False
    shadow_observation_status: str | None = None
    shadow_observation_top_candidates: str | None = None
    shadow_observation_blockers: str | None = None
    invariant_violation_codes: list[str] = field(default_factory=list)
    step_summaries: dict[str, PipelineStepSummary] = field(default_factory=dict)


class DailyPipelineService:
    """Orchestrate ledger audit, daily close, agent review, exits, and reports."""

    def __init__(
        self,
        db_path: Path | None = None,
        *,
        reports_dir: Path | None = None,
        daily_close_service_factory: DailyCloseFactory = DailyCloseWorkflowService,
        agent_review_service_factory: AgentReviewFactory = AgentReviewService,
        market_review_service_factory: MarketReviewFactory = MarketReviewService,
        market_plan_context_service_factory: MarketPlanContextFactory = MarketPlanContextService,
        position_service_factory: PositionLifecycleFactory = PositionLifecycleService,
        report_service_factory: ReportFactory = ReportingQueryService,
        backup_func: BackupFunc = backup_database,
    ):
        self.db_path = db_path or Paths().db_path
        self.reports_dir = reports_dir or Paths().reports_dir
        self.daily_close_service_factory = daily_close_service_factory
        self.agent_review_service_factory = agent_review_service_factory
        self.market_review_service_factory = market_review_service_factory
        self.market_plan_context_service_factory = market_plan_context_service_factory
        self.position_service_factory = position_service_factory
        self.report_service_factory = report_service_factory
        self.backup_func = backup_func

    def run_daily_pipeline(
        self,
        request: RunDailyPipelineRequest,
        ctx: RequestContext,
    ) -> ServiceResult[DailyPipelineResult]:
        errors = _validate_request(request, ctx)
        if errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_result(request, "failed"),
                errors=errors,
            )

        backup_path: Path | None = None
        before_counts = _table_counts(self.db_path)
        if not ctx.dry_run:
            try:
                backup_path = self.backup_func(
                    self.db_path,
                    request.backup_dir,
                    f"before_daily_pipeline_{request.as_of_date}",
                )
            except (FileNotFoundError, ValueError, FileExistsError) as exc:
                error = ServiceError(
                    code="PIPELINE_BACKUP_FAILED",
                    message=f"Daily pipeline backup failed: {exc}",
                    severity="blocker",
                )
                return ServiceResult(
                    status="blocked",
                    request_id=ctx.request_id,
                    data=_empty_result(request, "blocked", backup_path=None),
                    errors=[error],
                )

        ledger_report = check_database(self.db_path)
        if not ledger_report.ok:
            errors = [
                ServiceError(
                    code=violation.code.upper(),
                    message=violation.message,
                    severity="blocker",
                )
                for violation in ledger_report.violations
            ]
            result = _empty_result(
                request,
                "blocked",
                backup_path=str(backup_path) if backup_path is not None else None,
                invariant_violation_codes=[violation.code for violation in ledger_report.violations],
                ledger_audit_ok=False,
            )
            return ServiceResult(
                status="blocked",
                request_id=ctx.request_id,
                data=result,
                errors=errors,
            )

        base_key = _base_idempotency_key(request, ctx)
        warnings: list[ServiceWarning] = []
        step_summaries: dict[str, PipelineStepSummary] = {
            "ledger_audit": PipelineStepSummary(status="success", detail="invariants_ok"),
        }

        daily_close = self.daily_close_service_factory(self.db_path).run_daily_close(
            RunDailyCloseWorkflowRequest(
                as_of_date=request.as_of_date,
                strategy_version=request.strategy_version,
                account_key=request.account_key,
                account_id=request.account_id,
                run_type=request.run_type,
                force_new_review_run=False,
            ),
            _child_context(ctx, base_key, "daily-close"),
        )
        warnings.extend(daily_close.warnings)
        step_summaries["daily_close"] = PipelineStepSummary(status=daily_close.status)
        if not daily_close.ok or daily_close.data is None:
            return _failed_pipeline_result(
                request=request,
                ctx=ctx,
                status=daily_close.status,
                backup_path=backup_path,
                ledger_audit_ok=True,
                step_summaries=step_summaries,
                warnings=warnings,
                errors=daily_close.errors,
            )

        daily_pick_id = _daily_pick_id(daily_close.data)
        trade_plan_id = _trade_plan_id(daily_close.data)
        next_trade_date = getattr(daily_close.data, "next_trade_date", None)

        agent_result = _run_or_load_agent_review(
            self.db_path,
            daily_pick_id=daily_pick_id,
            request=request,
            ctx=ctx,
            base_key=base_key,
            agent_review_service_factory=self.agent_review_service_factory,
        )
        warnings.extend(agent_result.warnings)
        step_summaries["agent_review"] = PipelineStepSummary(status=agent_result.status)
        if not agent_result.ok or agent_result.data is None:
            return _failed_pipeline_result(
                request=request,
                ctx=ctx,
                status=agent_result.status,
                backup_path=backup_path,
                ledger_audit_ok=True,
                daily_close_status=daily_close.status,
                next_trade_date=next_trade_date,
                daily_pick_id=daily_pick_id,
                trade_plan_id=trade_plan_id,
                step_summaries=step_summaries,
                warnings=warnings,
                errors=agent_result.errors,
            )

        market_review_run_id: int | None = None
        market_review_status = "skipped"
        market_plan_context_status = "skipped"
        market_review_would_write = False
        market_plan_context_would_write = False

        if request.include_market_review:
            market_review = self.market_review_service_factory(self.db_path).run_market_review(
                RunMarketReviewRequest(as_of_date=request.as_of_date),
                _child_context(ctx, base_key, "market-review"),
            )
            warnings.extend(market_review.warnings)
            market_review_status = market_review.status
            market_review_would_write = ctx.dry_run
            step_summaries["market_review"] = PipelineStepSummary(status=market_review.status)
            if not market_review.ok or market_review.data is None:
                return _failed_pipeline_result(
                    request=request,
                    ctx=ctx,
                    status=market_review.status,
                    backup_path=backup_path,
                    ledger_audit_ok=True,
                    daily_close_status=daily_close.status,
                    agent_status=agent_result.status,
                    next_trade_date=next_trade_date,
                    daily_pick_id=daily_pick_id,
                    trade_plan_id=trade_plan_id,
                    agent_run_id=agent_result.data.agent_run_id,
                    agent_decision_id=agent_result.data.agent_decision_id,
                    market_review_status=market_review_status,
                    market_review_would_write=market_review_would_write,
                    step_summaries=step_summaries,
                    warnings=warnings,
                    errors=market_review.errors,
                )
            market_review_run_id = market_review.data.market_review_run_id
        else:
            step_summaries["market_review"] = PipelineStepSummary(status="skipped", detail="not_requested")

        if request.include_market_review and trade_plan_id is not None:
            if ctx.dry_run and market_review_run_id is None:
                market_plan_context_would_write = True
                step_summaries["market_plan_context"] = PipelineStepSummary(
                    status="skipped",
                    detail="market_review_not_persisted_in_dry_run",
                )
                warnings.append(
                    ServiceWarning(
                        code="MARKET_PLAN_CONTEXT_DRY_RUN_PENDING_REVIEW",
                        message=(
                            "Market-plan context would be linked after an apply run persists "
                            "the market review."
                        ),
                    )
                )
            else:
                plan_context = self.market_plan_context_service_factory(self.db_path).link_plan_context(
                    LinkMarketPlanContextRequest(
                        as_of_date=request.as_of_date,
                        trade_plan_id=trade_plan_id,
                    ),
                    _child_context(ctx, base_key, f"market-plan-context:trade-plan-{trade_plan_id}"),
                )
                warnings.extend(plan_context.warnings)
                market_plan_context_status = plan_context.status
                market_plan_context_would_write = ctx.dry_run
                step_summaries["market_plan_context"] = PipelineStepSummary(status=plan_context.status)
                if not plan_context.ok or plan_context.data is None:
                    return _failed_pipeline_result(
                        request=request,
                        ctx=ctx,
                        status=plan_context.status,
                        backup_path=backup_path,
                        ledger_audit_ok=True,
                        daily_close_status=daily_close.status,
                        agent_status=agent_result.status,
                        next_trade_date=next_trade_date,
                        daily_pick_id=daily_pick_id,
                        trade_plan_id=trade_plan_id,
                        agent_run_id=agent_result.data.agent_run_id,
                        agent_decision_id=agent_result.data.agent_decision_id,
                        market_review_run_id=market_review_run_id,
                        market_review_status=market_review_status,
                        market_plan_context_status=market_plan_context_status,
                        market_review_would_write=market_review_would_write,
                        market_plan_context_would_write=market_plan_context_would_write,
                        step_summaries=step_summaries,
                        warnings=warnings,
                        errors=plan_context.errors,
                    )
        else:
            step_summaries["market_plan_context"] = PipelineStepSummary(
                status="skipped",
                detail="no_trade_plan" if request.include_market_review else "not_requested",
            )

        exits = self.position_service_factory(self.db_path).evaluate_exits(
            EvaluateExitsRequest(
                as_of_date=request.as_of_date,
                account_key=request.account_key,
                account_id=request.account_id,
            ),
            _child_context(ctx, base_key, "exits-evaluate"),
        )
        warnings.extend(exits.warnings)
        step_summaries["exits_evaluate"] = PipelineStepSummary(status=exits.status)
        if not exits.ok or exits.data is None:
            return _failed_pipeline_result(
                request=request,
                ctx=ctx,
                status=exits.status,
                backup_path=backup_path,
                ledger_audit_ok=True,
                daily_close_status=daily_close.status,
                agent_status=agent_result.status,
                next_trade_date=next_trade_date,
                daily_pick_id=daily_pick_id,
                trade_plan_id=trade_plan_id,
                agent_run_id=agent_result.data.agent_run_id,
                agent_decision_id=agent_result.data.agent_decision_id,
                market_review_run_id=market_review_run_id,
                market_review_status=market_review_status,
                market_plan_context_status=market_plan_context_status,
                market_review_would_write=market_review_would_write,
                market_plan_context_would_write=market_plan_context_would_write,
                step_summaries=step_summaries,
                warnings=warnings,
                errors=exits.errors,
            )

        report_result = self._write_reports(request, ctx)
        warnings.extend(report_result.warnings)
        step_summaries["reports"] = PipelineStepSummary(status=report_result.status)
        if not report_result.ok or report_result.data is None:
            return _failed_pipeline_result(
                request=request,
                ctx=ctx,
                status=report_result.status,
                backup_path=backup_path,
                ledger_audit_ok=True,
                daily_close_status=daily_close.status,
                agent_status=agent_result.status,
                exit_status=exits.status,
                next_trade_date=next_trade_date,
                daily_pick_id=daily_pick_id,
                trade_plan_id=trade_plan_id,
                agent_run_id=agent_result.data.agent_run_id,
                agent_decision_id=agent_result.data.agent_decision_id,
                exit_decisions=_exit_decision_count(exits.data),
                market_review_run_id=market_review_run_id,
                market_review_status=market_review_status,
                market_plan_context_status=market_plan_context_status,
                market_review_would_write=market_review_would_write,
                market_plan_context_would_write=market_plan_context_would_write,
                step_summaries=step_summaries,
                warnings=warnings,
                errors=report_result.errors,
            )

        after_counts = _table_counts(self.db_path)
        changed = _counts_changed(before_counts, after_counts) or report_result.data.changed
        data = DailyPipelineResult(
            pipeline_status="pass",
            review_date=request.as_of_date,
            next_trade_date=next_trade_date,
            daily_pick_id=daily_pick_id,
            trade_plan_id=trade_plan_id,
            agent_run_id=agent_result.data.agent_run_id,
            agent_decision_id=agent_result.data.agent_decision_id,
            exit_decisions=_exit_decision_count(exits.data),
            report_markdown=str(report_result.data.markdown_path),
            report_json=str(report_result.data.json_path),
            changed=changed,
            backup_path=str(backup_path) if backup_path is not None else None,
            ledger_audit_ok=True,
            daily_close_status=daily_close.status,
            agent_status=agent_result.status,
            exit_status=exits.status,
            report_status=report_result.status,
            report_would_write=report_result.data.would_write,
            market_review_run_id=market_review_run_id,
            market_review_status=market_review_status,
            market_plan_context_status=market_plan_context_status,
            market_review_would_write=market_review_would_write,
            market_plan_context_would_write=market_plan_context_would_write,
            shadow_observation_status=report_result.data.shadow_observation_status,
            shadow_observation_top_candidates=report_result.data.shadow_observation_top_candidates,
            shadow_observation_blockers=report_result.data.shadow_observation_blockers,
            step_summaries=step_summaries,
        )
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=data,
            warnings=warnings,
            lineage={
                "as_of_date": request.as_of_date,
                "account_key": request.account_key,
                "daily_pick_id": daily_pick_id,
                "trade_plan_id": trade_plan_id,
                "agent_run_id": agent_result.data.agent_run_id,
                "market_review_run_id": market_review_run_id,
            },
        )

    def _write_reports(
        self,
        request: RunDailyPipelineRequest,
        ctx: RequestContext,
    ) -> ServiceResult["_ReportWriteResult"]:
        report = self.report_service_factory(self.db_path).get_daily_report(
            DailyReportRequest(
                as_of_date=request.as_of_date,
                account_key=request.account_key,
                account_id=request.account_id,
                strategy_version=request.strategy_version,
            ),
            RequestContext(request_id=_child_request_id(ctx, "reports"), dry_run=True, operator=ctx.operator, source=ctx.source),
        )
        if not report.ok or report.data is None:
            return ServiceResult(
                status=report.status,
                request_id=ctx.request_id,
                data=None,
                warnings=report.warnings,
                errors=report.errors,
            )

        markdown_path = self.reports_dir / f"daily_review_{request.as_of_date}.md"
        json_path = self.reports_dir / f"daily_review_{request.as_of_date}.json"
        markdown = render_daily_report_markdown(report.data)
        payload_json = render_daily_report_json(report.data)
        shadow_observation = getattr(report.data, "shadow_observation", None)
        shadow_status = _shadow_observation_status(shadow_observation)
        shadow_top_candidates = _shadow_observation_top_candidates(shadow_observation)
        shadow_blockers = _shadow_observation_blockers(shadow_observation)

        if ctx.dry_run:
            return ServiceResult(
                status="skipped",
                request_id=ctx.request_id,
                data=_ReportWriteResult(
                    markdown_path=markdown_path,
                    json_path=json_path,
                    changed=False,
                    would_write=True,
                    shadow_observation_status=shadow_status,
                    shadow_observation_top_candidates=shadow_top_candidates,
                    shadow_observation_blockers=shadow_blockers,
                ),
                warnings=report.warnings,
            )

        self.reports_dir.mkdir(parents=True, exist_ok=True)
        changed = _write_text_if_changed(markdown_path, markdown)
        changed = _write_text_if_changed(json_path, payload_json) or changed
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=_ReportWriteResult(
                markdown_path=markdown_path,
                json_path=json_path,
                changed=changed,
                would_write=False,
                shadow_observation_status=shadow_status,
                shadow_observation_top_candidates=shadow_top_candidates,
                shadow_observation_blockers=shadow_blockers,
            ),
            warnings=report.warnings,
        )


@dataclass(frozen=True)
class _ReportWriteResult:
    markdown_path: Path
    json_path: Path
    changed: bool
    would_write: bool = False
    shadow_observation_status: str | None = None
    shadow_observation_top_candidates: str | None = None
    shadow_observation_blockers: str | None = None


def _shadow_observation_status(shadow: object | None) -> str:
    if shadow is None:
        return "unavailable"
    return str(getattr(shadow, "status", "unknown") or "unknown")


def _shadow_observation_top_candidates(shadow: object | None) -> str:
    if shadow is None:
        return "none"
    candidates = getattr(shadow, "top_candidates", []) or []
    parts: list[str] = []
    for candidate in list(candidates)[:3]:
        today_top = getattr(candidate, "today_top", {}) or {}
        stock = ""
        if isinstance(today_top, dict):
            stock = " ".join(str(part) for part in [today_top.get("ts_code"), today_top.get("name")] if part)
        parts.append(
            f"{getattr(candidate, 'candidate_key', 'unknown')}"
            f"[status={getattr(candidate, 'status', 'unknown')},"
            f"today={getattr(candidate, 'today_candidate_count', None) or 'none'},"
            f"walk={getattr(candidate, 'walk_forward_status', 'unknown')},"
            f"top={stock or 'none'}]"
        )
    return ";".join(parts) if parts else "none"


def _shadow_observation_blockers(shadow: object | None) -> str:
    if shadow is None:
        return "shadow_observation_unavailable"
    counts = getattr(shadow, "blocker_counts", {}) or {}
    if isinstance(counts, dict) and counts:
        return ";".join(f"{key}:{counts[key]}" for key in sorted(counts))
    reason = getattr(shadow, "unavailable_reason", None)
    return str(reason) if reason else "none"


def _validate_request(request: RunDailyPipelineRequest, ctx: RequestContext) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not is_yyyymmdd(request.as_of_date):
        errors.append(ServiceError("VALIDATION_ERROR", "as_of_date must use YYYYMMDD format."))
    if request.account_id is None and not request.account_key:
        errors.append(ServiceError("VALIDATION_ERROR", "account_key or account_id is required."))
    if not request.strategy_version.strip():
        errors.append(ServiceError("VALIDATION_ERROR", "strategy_version is required."))
    if not ctx.dry_run and not (ctx.operator or "").strip():
        errors.append(ServiceError("OPERATOR_REQUIRED", "operator is required for daily-pipeline --apply."))
    return errors


def _run_or_load_agent_review(
    db_path: Path,
    *,
    daily_pick_id: int | None,
    request: RunDailyPipelineRequest,
    ctx: RequestContext,
    base_key: str,
    agent_review_service_factory: AgentReviewFactory,
) -> ServiceResult[AgentReviewResult]:
    if daily_pick_id is None:
        return ServiceResult(
            status="skipped",
            request_id=_child_request_id(ctx, "agent-review"),
            data=AgentReviewResult(
                input_snapshot_id=None,
                agent_run_id=None,
                agent_decision_id=None,
                action="no_opinion",
                confidence=None,
                risk_level="unknown",
                summary="no persisted daily pick available for TradingAgents review",
            ),
            warnings=[
                ServiceWarning(
                    code="AGENT_REVIEW_SKIPPED_NO_PICK",
                    message="TradingAgents review was skipped because no persisted daily pick exists.",
                )
            ],
        )

    existing = _existing_agent_review(db_path, daily_pick_id)
    if existing is not None:
        return ServiceResult(
            status="skipped",
            request_id=_child_request_id(ctx, "agent-review"),
            data=existing,
            warnings=[
                ServiceWarning(
                    code="AGENT_REVIEW_ALREADY_EXISTS",
                    message=f"Using existing TradingAgents review for daily_pick_id={daily_pick_id}.",
                )
            ],
        )

    return agent_review_service_factory(db_path).review_daily_pick(
        ReviewDailyPickRequest(
            daily_pick_id=daily_pick_id,
            account_key=request.account_key,
            account_id=request.account_id,
        ),
        _child_context(ctx, base_key, f"agent-review:daily-pick-{daily_pick_id}"),
    )


def _existing_agent_review(db_path: Path, daily_pick_id: int) -> AgentReviewResult | None:
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
              snap.id AS input_snapshot_id,
              ar.id AS agent_run_id,
              ad.id AS agent_decision_id,
              ad.action,
              ad.confidence,
              ad.risk_level,
              ad.summary
            FROM agent_decisions ad
            JOIN agent_runs ar ON ar.id = ad.agent_run_id
            LEFT JOIN input_snapshots snap ON snap.id = ar.input_snapshot_id
            WHERE ad.daily_pick_id = ?
            ORDER BY ad.id DESC
            LIMIT 1
            """,
            (daily_pick_id,),
        ).fetchone()
    if row is None:
        return None
    return AgentReviewResult(
        input_snapshot_id=row["input_snapshot_id"],
        agent_run_id=row["agent_run_id"],
        agent_decision_id=row["agent_decision_id"],
        action=row["action"],
        confidence=row["confidence"],
        risk_level=row["risk_level"],
        summary=row["summary"],
        artifact_paths=[],
    )


def _failed_pipeline_result(
    *,
    request: RunDailyPipelineRequest,
    ctx: RequestContext,
    status: str,
    backup_path: Path | None,
    ledger_audit_ok: bool,
    step_summaries: dict[str, PipelineStepSummary],
    warnings: list[ServiceWarning],
    errors: list[ServiceError],
    daily_close_status: str | None = None,
    agent_status: str | None = None,
    exit_status: str | None = None,
    next_trade_date: str | None = None,
    daily_pick_id: int | None = None,
    trade_plan_id: int | None = None,
    agent_run_id: int | None = None,
    agent_decision_id: int | None = None,
    market_review_run_id: int | None = None,
    market_review_status: str | None = None,
    market_plan_context_status: str | None = None,
    market_review_would_write: bool = False,
    market_plan_context_would_write: bool = False,
    exit_decisions: int = 0,
) -> ServiceResult[DailyPipelineResult]:
    pipeline_status = "blocked" if status == "blocked" else "failed"
    return ServiceResult(
        status=status,
        request_id=ctx.request_id,
        data=DailyPipelineResult(
            pipeline_status=pipeline_status,
            review_date=request.as_of_date,
            next_trade_date=next_trade_date,
            daily_pick_id=daily_pick_id,
            trade_plan_id=trade_plan_id,
            agent_run_id=agent_run_id,
            agent_decision_id=agent_decision_id,
            exit_decisions=exit_decisions,
            report_markdown=None,
            report_json=None,
            changed=False,
            backup_path=str(backup_path) if backup_path is not None else None,
            ledger_audit_ok=ledger_audit_ok,
            daily_close_status=daily_close_status,
            agent_status=agent_status,
            exit_status=exit_status,
            report_status=None,
            market_review_run_id=market_review_run_id,
            market_review_status=market_review_status,
            market_plan_context_status=market_plan_context_status,
            market_review_would_write=market_review_would_write,
            market_plan_context_would_write=market_plan_context_would_write,
            step_summaries=step_summaries,
        ),
        warnings=warnings,
        errors=errors,
    )


def _empty_result(
    request: RunDailyPipelineRequest,
    pipeline_status: str,
    *,
    backup_path: str | None = None,
    invariant_violation_codes: list[str] | None = None,
    ledger_audit_ok: bool = False,
) -> DailyPipelineResult:
    return DailyPipelineResult(
        pipeline_status=pipeline_status,
        review_date=request.as_of_date,
        next_trade_date=None,
        daily_pick_id=None,
        trade_plan_id=None,
        agent_run_id=None,
        agent_decision_id=None,
        exit_decisions=0,
        report_markdown=None,
        report_json=None,
        changed=False,
        backup_path=backup_path,
        ledger_audit_ok=ledger_audit_ok,
        invariant_violation_codes=invariant_violation_codes or [],
    )


def _child_context(ctx: RequestContext, base_key: str, step: str) -> RequestContext:
    return RequestContext(
        request_id=_child_request_id(ctx, step),
        idempotency_key=f"{base_key}:{step}",
        dry_run=ctx.dry_run,
        operator=ctx.operator or "cli",
        source=ctx.source,
        allow_live_writes=ctx.allow_live_writes,
    )


def _child_request_id(ctx: RequestContext, step: str) -> str:
    return f"{ctx.request_id or 'daily-pipeline'}:{step}"


def _base_idempotency_key(request: RunDailyPipelineRequest, ctx: RequestContext) -> str:
    if ctx.idempotency_key:
        return ctx.idempotency_key
    account_ref = request.account_key or f"account-id-{request.account_id}"
    return f"daily-pipeline:{account_ref}:{request.as_of_date}:{request.strategy_version}:{request.run_type}"


def _daily_pick_id(data: object) -> int | None:
    candidate = getattr(data, "candidate", None)
    if candidate is None:
        return None
    return getattr(candidate, "daily_pick_id", None)


def _trade_plan_id(data: object) -> int | None:
    buy_plan = getattr(data, "buy_plan", None)
    if buy_plan is None:
        return None
    return getattr(buy_plan, "trade_plan_id", None)


def _exit_decision_count(data: object) -> int:
    return len([item for item in getattr(data, "exit_decision_ids", []) if int(item) > 0])


def _table_counts(db_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    with connect(db_path) as conn:
        existing = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ({})".format(
                    ",".join("?" for _ in _CHANGE_TABLES)
                ),
                _CHANGE_TABLES,
            ).fetchall()
        }
        for table_name in _CHANGE_TABLES:
            if table_name in existing:
                counts[table_name] = int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
    return counts


def _counts_changed(before: dict[str, int], after: dict[str, int]) -> bool:
    keys = set(before) | set(after)
    return any(before.get(key, 0) != after.get(key, 0) for key in keys)


def _write_text_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True
