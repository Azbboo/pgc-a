"""Daily close report query and Markdown/JSON rendering."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pgc_trading.config import Paths
from pgc_trading.market.calendar import is_yyyymmdd
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult
from pgc_trading.services.daily_close_workflow_service import DEFAULT_ACCOUNT_KEY
from pgc_trading.services.data_quality_service import (
    DailyReviewReadinessRequest,
    DataQualityService,
)
from pgc_trading.services.operational_readiness_service import (
    NextDayDecisionChecklistItem,
    NextDayDecisionSummary,
    OperationalReadinessService,
    PAPER_ACCEPTANCE_AGENT_REVIEW_CODES,
    PAPER_ACCEPTANCE_OPEN_EXECUTION_MISMATCH_CODES,
    PAPER_ACCEPTANCE_STALE_EVIDENCE_CODES,
    PaperReadinessRequest,
    PaperReadinessResult,
    summarize_next_day_decision,
)
from pgc_trading.services.open_execution_service import OpenExecutionRequest, OpenExecutionService
from pgc_trading.portfolio.state_machines import BUY_PLAN_ACTION, OPEN_POSITION_STATUSES, SELL_PLAN_ACTIONS
from pgc_trading.storage.database import connect
from pgc_trading.storage.invariant_checks import InvariantReport, check_database
from pgc_trading.strategies.cpb_6157 import STRATEGY_VERSION


@dataclass(frozen=True)
class DailyReportRequest:
    as_of_date: str
    account_key: str | None = DEFAULT_ACCOUNT_KEY
    account_id: int | None = None
    strategy_version: str = STRATEGY_VERSION


@dataclass(frozen=True)
class DailyReviewHistoryRequest:
    account_key: str | None = DEFAULT_ACCOUNT_KEY
    account_id: int | None = None
    strategy_version: str = STRATEGY_VERSION
    before_date: str | None = None
    limit: int = 20


@dataclass(frozen=True)
class ReviewTimelineRequest:
    account_key: str | None = DEFAULT_ACCOUNT_KEY
    account_id: int | None = None
    strategy_version: str = STRATEGY_VERSION
    before_date: str | None = None
    limit: int = 20


@dataclass(frozen=True)
class PaperAcceptanceHistoryRequest:
    account_key: str | None = DEFAULT_ACCOUNT_KEY
    account_id: int | None = None
    strategy_version: str = STRATEGY_VERSION
    before_date: str | None = None
    limit: int = 20


@dataclass(frozen=True)
class OpsHistoryRequest:
    account_key: str | None = DEFAULT_ACCOUNT_KEY
    account_id: int | None = None
    strategy_version: str = STRATEGY_VERSION
    before_date: str | None = None
    limit: int = 50


@dataclass(frozen=True)
class DataQualityReport:
    readiness: str
    can_trade: bool
    blocker_count: int
    warning_count: int
    valid_raw_count: int
    market_coverage_ok: bool
    trade_calendar_ok: bool
    strategy_version_ok: bool
    account_ok: bool
    missing_market_bar_count: int
    event_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class AccountReport:
    account_id: int | None
    account_key: str | None
    name: str | None
    account_type: str | None
    max_positions: int | None
    open_positions: int
    free_position_slots: int | None
    cash: float | None
    market_value: float | None
    total_equity: float | None
    equity_as_of_date: str | None


@dataclass(frozen=True)
class DailyReviewHistoryItem:
    review_date: str
    next_trade_date: str | None
    strategy_run_id: int
    review_status: str
    signals_count: int
    daily_pick_id: int | None
    signal_id: int | None
    ts_code: str | None
    name: str | None
    score: float | None
    planned_buy_date: str | None
    selection_reason: str | None
    trade_plan_id: int | None
    trade_plan_action: str | None
    trade_plan_status: str | None
    planned_trade_date: str | None
    agent_status: str | None
    agent_action: str | None
    agent_risk_level: str | None
    blocker_count: int
    warning_count: int
    created_at: str | None


@dataclass(frozen=True)
class DailyReviewHistory:
    strategy_version: str
    account: AccountReport
    items: list[DailyReviewHistoryItem]
    limit: int
    before_date: str | None = None


@dataclass(frozen=True)
class ReviewTimelineItem:
    review_date: str
    next_trade_date: str | None
    strategy_run_id: int
    review_status: str
    daily_pick_id: int | None
    ts_code: str | None
    name: str | None
    score: float | None
    trade_plan_id: int | None
    trade_plan_action: str | None
    trade_plan_status: str | None
    planned_trade_date: str | None
    market_review_run_id: int | None
    market_regime: str | None
    market_regime_summary: str | None
    market_breadth_score: float | None
    market_trend_score: float | None
    market_volume_score: float | None
    market_persistence_score: float | None
    plan_context_alignment: str | None
    plan_context_risk_level: str | None
    plan_context_management_action: str | None
    plan_context_rationale: str | None
    open_execution_as_of_date: str | None
    open_execution_status: str
    open_execution_next_action: str
    open_execution_primary_plan_id: int | None
    open_execution_primary_position_id: int | None
    open_execution_target_stock: str | None
    open_execution_target_name: str | None
    blocker_count: int
    warning_count: int
    created_at: str | None


@dataclass(frozen=True)
class ReviewTimeline:
    strategy_version: str
    account: AccountReport
    items: list[ReviewTimelineItem]
    limit: int
    before_date: str | None = None
    execution_context_note: str = (
        "Review timeline navigation is read-only and does not change the dashboard opening execution date."
    )


@dataclass(frozen=True)
class SignalReport:
    signal_id: int
    ts_code: str
    name: str
    score: float
    signal_rank: int | None


@dataclass(frozen=True)
class CandidateReport:
    daily_pick_id: int
    strategy_run_id: int
    feature_run_id: int | None
    market_fetch_run_id: int | None
    signal_id: int
    feature_snapshot_id: int | None
    ts_code: str
    name: str
    review_date: str
    planned_buy_date: str | None
    score: float
    signal_rank: int | None
    selection_reason: str
    selected_over_signal_count: int
    ranked_signals: list[SignalReport] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BuyPlanReport:
    trade_plan_id: int
    action: str
    status: str
    reason: str | None
    planned_trade_date: str | None
    planned_buy_date: str | None
    planned_cash: float | None
    planned_shares: int | None
    free_position_slots: int | None
    price_reference: float | None
    price_reference_date: str | None


@dataclass(frozen=True)
class AgentArtifactReport:
    artifact_id: int
    artifact_type: str
    content_hash: str | None


@dataclass(frozen=True)
class AgentAnalystReport:
    analyst_key: str
    analyst_name: str
    status: str
    summary: str
    supporting_points: list[str] = field(default_factory=list)
    risk_points: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentReportSection:
    section_key: str
    section_name: str
    status: str
    source_label: str
    summary: str
    supporting_points: list[str] = field(default_factory=list)
    risk_points: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentExternalEvidenceReport:
    source_ref: str
    source: str
    category: str
    published_date: str | None
    title: str
    summary: str
    sentiment: str | None = None
    importance: str | None = None


@dataclass(frozen=True)
class AgentAdviceReport:
    agent_run_id: int | None
    agent_decision_id: int | None
    status: str
    action: str
    risk_level: str
    confidence: float | None
    summary: str | None
    note: str
    execution_mode: str | None = None
    source_label: str | None = None
    supporting_points: list[str] = field(default_factory=list)
    risk_points: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    external_data_coverage: dict[str, str] = field(default_factory=dict)
    external_evidence: list[AgentExternalEvidenceReport] = field(default_factory=list)
    missing_data_warnings: list[str] = field(default_factory=list)
    analyst_reports: list[AgentAnalystReport] = field(default_factory=list)
    report_sections: list[AgentReportSection] = field(default_factory=list)
    artifacts: list[AgentArtifactReport] = field(default_factory=list)
    report_markdown: str | None = None


@dataclass(frozen=True)
class MarketPlanContextReport:
    market_review_run_id: int
    trade_plan_id: int
    alignment: str
    risk_level: str
    management_action: str
    rationale: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketSectorReport:
    sector_code: str
    sector_name: str
    rank_overall: int | None
    persistence_score: float | None
    breadth_score: float | None
    volume_score: float | None
    leader_count: int
    return_1d: float | None
    return_3d: float | None


@dataclass(frozen=True)
class StrategyHypothesisSummaryReport:
    hypothesis_id: int
    hypothesis_type: str
    title: str
    status: str
    rationale: str


@dataclass(frozen=True)
class MarketReviewReport:
    market_review_run_id: int
    status: str
    regime: str
    summary: str
    breadth_score: float | None
    trend_score: float | None
    volume_score: float | None
    sentiment_score: float | None
    persistence_score: float | None
    top_sectors: list[MarketSectorReport] = field(default_factory=list)
    sector_persistence: list[MarketSectorReport] = field(default_factory=list)
    external_evidence_coverage: dict[str, Any] = field(default_factory=dict)
    strategy_hypotheses: list[StrategyHypothesisSummaryReport] = field(default_factory=list)


@dataclass(frozen=True)
class PositionReport:
    position_id: int
    ts_code: str
    name: str
    buy_date: str
    buy_price: float
    shares: int
    status: str
    planned_t2_date: str | None
    planned_t5_date: str | None
    latest_trade_date: str | None
    latest_close: float | None
    action_due: str


@dataclass(frozen=True)
class ReportLineage:
    feature_run_id: int | None
    strategy_run_id: int | None
    market_fetch_run_id: int | None
    daily_pick_id: int | None
    signal_id: int | None
    trade_plan_id: int | None
    market_review_run_id: int | None
    agent_run_id: int | None
    agent_decision_id: int | None
    data_quality_event_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class DailyAcceptanceGate:
    key: str
    label: str
    status: str
    summary: str
    detail: str
    blocker_codes: list[str] = field(default_factory=list)
    warning_codes: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DailyAcceptanceAlert:
    severity: str
    code: str
    title: str
    summary: str
    as_of_date: str
    gate_key: str | None = None
    action: str = "quality"


@dataclass(frozen=True)
class DailyAcceptanceOpenExecution:
    as_of_date: str
    status: str
    next_action: str
    primary_plan_id: int | None
    primary_position_id: int | None
    target_stock: str | None
    target_name: str | None
    planned_trade_date: str | None
    planned_shares: int | None
    blocked_reasons: list[str] = field(default_factory=list)
    operator_required: bool = False


@dataclass(frozen=True)
class DailyAcceptanceReport:
    account_key: str | None
    as_of_date: str
    execution_date: str | None
    status: str
    summary: str
    data_freshness: DailyAcceptanceGate
    evidence_coverage: DailyAcceptanceGate
    agent_status: DailyAcceptanceGate
    open_execution: DailyAcceptanceOpenExecution
    open_execution_gate: DailyAcceptanceGate
    readiness_gates: list[DailyAcceptanceGate] = field(default_factory=list)
    unresolved_blockers: list[str] = field(default_factory=list)
    alerts: list[DailyAcceptanceAlert] = field(default_factory=list)
    advisory_note: str = (
        "Acceptance is read-only; it does not execute trades, cancel plans, or mutate strategy parameters."
    )


@dataclass(frozen=True)
class DailyAcceptanceHistoryItem:
    as_of_date: str
    execution_date: str | None
    status: str
    summary: str
    unresolved_blocker_count: int
    warning_count: int
    alert_count: int
    data_freshness_status: str
    evidence_coverage_status: str
    agent_status: str
    open_execution_status: str
    open_execution_next_action: str
    open_execution_mismatch: bool
    blocker_codes: list[str] = field(default_factory=list)
    warning_codes: list[str] = field(default_factory=list)
    alert_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DailyAcceptanceHistory:
    strategy_version: str
    account: AccountReport
    items: list[DailyAcceptanceHistoryItem]
    alerts: list[DailyAcceptanceAlert]
    summary: str
    trend: dict[str, int | str | None]
    limit: int
    before_date: str | None = None
    advisory_note: str = (
        "Paper acceptance history and alerts are read-only; they never execute trades or cancel plans."
    )


@dataclass(frozen=True)
class NextDayStrategyProposalSummary:
    total_count: int
    proposed_count: int
    testing_count: int
    accepted_count: int
    rejected_count: int
    archived_count: int
    review_required_count: int
    items: list[StrategyHypothesisSummaryReport] = field(default_factory=list)


@dataclass(frozen=True)
class NextDaySystemProposal:
    action: str
    target: str | None
    trade_plan_id: int | None
    position_id: int | None
    planned_trade_date: str | None
    planned_shares: int | None
    rationale: str


@dataclass(frozen=True)
class NextDayDecisionCockpit:
    account_key: str | None
    as_of_date: str
    execution_date: str | None
    status: str
    headline: str
    recommended_manual_action: str
    blocker_count: int
    warning_count: int
    system_proposal: NextDaySystemProposal
    checklist: list[NextDayDecisionChecklistItem] = field(default_factory=list)
    strategy_proposals: NextDayStrategyProposalSummary | None = None
    acceptance_status: str | None = None
    acceptance_summary: str | None = None
    open_execution: DailyAcceptanceOpenExecution | None = None
    market_review: MarketReviewReport | None = None
    market_plan_context: MarketPlanContextReport | None = None
    advisory_note: str = (
        "Next-day decision cockpit is read-only; it explains blockers and next manual actions "
        "but never executes trades, enables timers, or mutates strategy parameters."
    )


@dataclass(frozen=True)
class OpsHistoryItem:
    occurred_at: str
    category: str
    status: str
    title: str
    summary: str
    as_of_date: str | None = None
    source: str = "database"
    operation_id: int | None = None
    operation_type: str | None = None
    idempotency_key: str | None = None
    request_id: str | None = None
    operator: str | None = None
    log_file: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OpsHistory:
    items: list[OpsHistoryItem]
    summary: str
    counts: dict[str, int]
    limit: int
    before_date: str | None = None
    advisory_note: str = (
        "Ops history is read-only observability; it never enables timers, reruns jobs, executes trades, "
        "or mutates strategy state."
    )


@dataclass(frozen=True)
class DailyReport:
    generated_at: str
    as_of_date: str
    latest_market_date: str | None
    next_trade_date: str | None
    strategy_version: str
    account: AccountReport
    data_quality: DataQualityReport
    paper_promotion: PaperReadinessResult | None
    paper_acceptance: DailyAcceptanceReport | None
    next_day_decision: NextDayDecisionCockpit | None
    candidate: CandidateReport | None
    no_candidate_reason: str | None
    buy_plan: BuyPlanReport | None
    market_review: MarketReviewReport | None
    market_plan_context: MarketPlanContextReport | None
    agent_advice: AgentAdviceReport
    positions: list[PositionReport]
    due_positions: list[PositionReport]
    lineage: ReportLineage


class ReportingQueryService:
    """Read report-ready state without mutating trading facts."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def get_daily_report(
        self,
        request: DailyReportRequest,
        ctx: RequestContext | None = None,
    ) -> ServiceResult[DailyReport]:
        context = ctx or RequestContext(source="report")
        errors = _validate_request(request)
        if errors:
            return ServiceResult(status="validation_failed", request_id=context.request_id, errors=errors)

        readiness = DataQualityService(self.db_path).check_daily_review_readiness(
            DailyReviewReadinessRequest(
                as_of_date=request.as_of_date,
                strategy_version=request.strategy_version,
                account_key=request.account_key,
                account_id=request.account_id,
            ),
            RequestContext(
                request_id=context.request_id,
                dry_run=True,
                operator=context.operator,
                source=context.source,
            ),
        )
        invariant_report = check_database(self.db_path)
        paper_promotion = _paper_promotion_report(self.db_path, request, context)

        with connect(self.db_path) as conn:
            account = _load_account(conn, request)
            candidate = _load_candidate(conn, request)
            buy_plan = _load_buy_plan(conn, candidate, account)
            market_review = _load_market_review(conn, request.as_of_date)
            market_plan_context = _load_market_plan_context(conn, buy_plan, request.as_of_date)
            agent_advice = _load_agent_advice(conn, candidate)
            positions = _load_positions(conn, request.as_of_date, account.account_id)
            no_candidate_reason = _no_candidate_reason(conn, request, candidate)
            latest_market_date = _latest_market_date(conn, request.as_of_date)
            next_trade_date = _next_trade_date(conn, request.as_of_date)
            strategy_proposals = _load_next_day_strategy_proposals(conn, request.as_of_date)

        data_quality = _data_quality_report(readiness, invariant_report)
        open_execution = _open_execution_acceptance(
            self.db_path,
            request,
            context,
            next_trade_date or request.as_of_date,
        )
        lineage = ReportLineage(
            feature_run_id=candidate.feature_run_id if candidate else _latest_feature_run_id(self.db_path, request),
            strategy_run_id=candidate.strategy_run_id if candidate else _latest_strategy_run_id(self.db_path, request),
            market_fetch_run_id=candidate.market_fetch_run_id if candidate else None,
            daily_pick_id=candidate.daily_pick_id if candidate else None,
            signal_id=candidate.signal_id if candidate else None,
            trade_plan_id=buy_plan.trade_plan_id if buy_plan else None,
            market_review_run_id=(
                market_review.market_review_run_id
                if market_review
                else market_plan_context.market_review_run_id
                if market_plan_context
                else None
            ),
            agent_run_id=agent_advice.agent_run_id,
            agent_decision_id=agent_advice.agent_decision_id,
            data_quality_event_ids=data_quality.event_ids,
        )
        paper_acceptance = _daily_acceptance_report(
            request=request,
            account=account,
            data_quality=data_quality,
            paper_promotion=paper_promotion,
            latest_market_date=latest_market_date,
            next_trade_date=next_trade_date,
            buy_plan=buy_plan,
            market_review=market_review,
            market_plan_context=market_plan_context,
            agent_advice=agent_advice,
            positions=positions,
            due_positions=[position for position in positions if position.action_due != "none"],
            open_execution=open_execution,
            lineage=lineage,
        )
        next_day_decision = _next_day_decision_cockpit(
            report_request=request,
            account=account,
            paper_acceptance=paper_acceptance,
            market_review=market_review,
            market_plan_context=market_plan_context,
            strategy_proposals=strategy_proposals,
        )
        report = DailyReport(
            generated_at=datetime.now(UTC).isoformat(),
            as_of_date=request.as_of_date,
            latest_market_date=latest_market_date,
            next_trade_date=next_trade_date,
            strategy_version=request.strategy_version,
            account=account,
            data_quality=data_quality,
            paper_promotion=paper_promotion,
            paper_acceptance=paper_acceptance,
            next_day_decision=next_day_decision,
            candidate=candidate,
            no_candidate_reason=no_candidate_reason,
            buy_plan=buy_plan,
            market_review=market_review,
            market_plan_context=market_plan_context,
            agent_advice=agent_advice,
            positions=positions,
            due_positions=[position for position in positions if position.action_due != "none"],
            lineage=lineage,
        )
        return ServiceResult(
            status="success",
            request_id=context.request_id,
            data=report,
            warnings=readiness.warnings,
            errors=[*readiness.errors, *_invariant_report_errors(invariant_report)],
            lineage={
                "as_of_date": request.as_of_date,
                "strategy_version": request.strategy_version,
                "account_id": account.account_id,
                "daily_pick_id": lineage.daily_pick_id,
                "trade_plan_id": lineage.trade_plan_id,
            },
        )

    def get_daily_acceptance(
        self,
        request: DailyReportRequest,
        ctx: RequestContext | None = None,
    ) -> ServiceResult[DailyAcceptanceReport]:
        result = self.get_daily_report(request, ctx)
        if result.data is None:
            return ServiceResult(
                status=result.status,
                request_id=result.request_id,
                warnings=result.warnings,
                errors=result.errors,
                lineage=result.lineage,
            )
        return ServiceResult(
            status=result.status,
            request_id=result.request_id,
            data=result.data.paper_acceptance,
            warnings=result.warnings,
            errors=result.errors,
            lineage={
                **result.lineage,
                "acceptance_status": result.data.paper_acceptance.status
                if result.data.paper_acceptance
                else None,
            },
        )

    def get_next_day_decision_cockpit(
        self,
        request: DailyReportRequest,
        ctx: RequestContext | None = None,
    ) -> ServiceResult[NextDayDecisionCockpit]:
        result = self.get_daily_report(request, ctx)
        if result.data is None:
            return ServiceResult(
                status=result.status,
                request_id=result.request_id,
                warnings=result.warnings,
                errors=result.errors,
                lineage=result.lineage,
            )
        return ServiceResult(
            status=result.status,
            request_id=result.request_id,
            data=result.data.next_day_decision,
            warnings=result.warnings,
            errors=result.errors,
            lineage={
                **result.lineage,
                "next_day_decision_status": result.data.next_day_decision.status
                if result.data.next_day_decision
                else None,
                "read_only": True,
            },
        )

    def list_paper_acceptance_history(
        self,
        request: PaperAcceptanceHistoryRequest,
        ctx: RequestContext | None = None,
    ) -> ServiceResult[DailyAcceptanceHistory]:
        context = ctx or RequestContext(source="report")
        errors = _validate_acceptance_history_request(request)
        if errors:
            return ServiceResult(status="validation_failed", request_id=context.request_id, errors=errors)

        with connect(self.db_path) as conn:
            account = _load_account(
                conn,
                DailyReportRequest(
                    as_of_date=request.before_date or "99991231",
                    account_key=request.account_key,
                    account_id=request.account_id,
                    strategy_version=request.strategy_version,
                ),
            )
            review_dates = _load_acceptance_history_dates(conn, request)

        items: list[DailyAcceptanceHistoryItem] = []
        alerts: list[DailyAcceptanceAlert] = []
        for review_date in review_dates:
            child_context = RequestContext(
                request_id=f"{context.request_id}:acceptance:{review_date}" if context.request_id else None,
                dry_run=True,
                operator=context.operator,
                source=context.source,
            )
            result = self.get_daily_acceptance(
                DailyReportRequest(
                    as_of_date=review_date,
                    account_key=request.account_key,
                    account_id=request.account_id,
                    strategy_version=request.strategy_version,
                ),
                child_context,
            )
            if result.data is None:
                alert = DailyAcceptanceAlert(
                    severity="blocker",
                    code="PAPER_ACCEPTANCE_UNAVAILABLE",
                    title="验收历史不可用",
                    summary=f"{_date_text(review_date)} 的 paper acceptance 无法计算。",
                    as_of_date=review_date,
                    action="quality",
                )
                alerts.append(alert)
                items.append(_unavailable_acceptance_history_item(review_date, alert))
                continue
            items.append(_acceptance_history_item(result.data))
            alerts.extend(result.data.alerts)

        trend = _acceptance_history_trend(items)
        return ServiceResult(
            status="success",
            request_id=context.request_id,
            data=DailyAcceptanceHistory(
                strategy_version=request.strategy_version,
                account=account,
                items=items,
                alerts=alerts[: min(len(alerts), request.limit * 4)],
                summary=_acceptance_history_summary(trend),
                trend=trend,
                limit=request.limit,
                before_date=request.before_date,
            ),
            lineage={
                "strategy_version": request.strategy_version,
                "account_id": account.account_id,
                "review_count": len(items),
                "alert_count": len(alerts),
            },
        )

    def list_ops_history(
        self,
        request: OpsHistoryRequest,
        ctx: RequestContext | None = None,
    ) -> ServiceResult[OpsHistory]:
        context = ctx or RequestContext(source="report")
        errors = _validate_ops_history_request(request)
        if errors:
            return ServiceResult(status="validation_failed", request_id=context.request_id, errors=errors)

        with connect(self.db_path) as conn:
            account = _load_account(
                conn,
                DailyReportRequest(
                    as_of_date=request.before_date or "99991231",
                    account_key=request.account_key,
                    account_id=request.account_id,
                    strategy_version=request.strategy_version,
                ),
            )
            operation_items = _load_ops_history_operations(conn, request)
            acceptance_dates = _load_acceptance_history_dates(
                conn,
                PaperAcceptanceHistoryRequest(
                    account_key=request.account_key,
                    account_id=request.account_id,
                    strategy_version=request.strategy_version,
                    before_date=request.before_date,
                    limit=min(request.limit, 10),
                ),
            )

        acceptance_items: list[OpsHistoryItem] = []
        for review_date in acceptance_dates:
            acceptance_result = self.get_daily_acceptance(
                DailyReportRequest(
                    as_of_date=review_date,
                    account_key=request.account_key,
                    account_id=request.account_id,
                    strategy_version=request.strategy_version,
                ),
                RequestContext(
                    request_id=f"{context.request_id}:ops-acceptance:{review_date}" if context.request_id else None,
                    dry_run=True,
                    operator=context.operator,
                    source=context.source,
                ),
            )
            if acceptance_result.data is not None:
                acceptance_items.append(_ops_history_acceptance_item(acceptance_result.data))

        file_items = [
            *_load_ops_history_log_items(request),
            *_load_ops_history_release_items(request),
        ]
        items = _dedupe_ops_history_items([*operation_items, *acceptance_items, *file_items])
        items.sort(key=_ops_history_sort_key, reverse=True)
        items = items[: request.limit]
        counts = _ops_history_counts(items)
        return ServiceResult(
            status="success",
            request_id=context.request_id,
            data=OpsHistory(
                items=items,
                summary=_ops_history_summary(items, counts),
                counts=counts,
                limit=request.limit,
                before_date=request.before_date,
            ),
            lineage={
                "strategy_version": request.strategy_version,
                "account_id": account.account_id,
                "item_count": len(items),
                "read_only": True,
            },
        )

    def list_daily_review_history(
        self,
        request: DailyReviewHistoryRequest,
        ctx: RequestContext | None = None,
    ) -> ServiceResult[DailyReviewHistory]:
        context = ctx or RequestContext(source="report")
        errors = _validate_history_request(request)
        if errors:
            return ServiceResult(status="validation_failed", request_id=context.request_id, errors=errors)

        with connect(self.db_path) as conn:
            account = _load_account(
                conn,
                DailyReportRequest(
                    as_of_date=request.before_date or "99991231",
                    account_key=request.account_key,
                    account_id=request.account_id,
                    strategy_version=request.strategy_version,
                ),
            )
            items = _load_review_history(conn, request, account.account_id)

        return ServiceResult(
            status="success",
            request_id=context.request_id,
            data=DailyReviewHistory(
                strategy_version=request.strategy_version,
                account=account,
                items=items,
                limit=request.limit,
                before_date=request.before_date,
            ),
            lineage={
                "strategy_version": request.strategy_version,
                "account_id": account.account_id,
            },
        )

    def list_review_timeline(
        self,
        request: ReviewTimelineRequest,
        ctx: RequestContext | None = None,
    ) -> ServiceResult[ReviewTimeline]:
        context = ctx or RequestContext(source="report")
        errors = _validate_timeline_request(request)
        if errors:
            return ServiceResult(status="validation_failed", request_id=context.request_id, errors=errors)

        with connect(self.db_path) as conn:
            account = _load_account(
                conn,
                DailyReportRequest(
                    as_of_date=request.before_date or "99991231",
                    account_key=request.account_key,
                    account_id=request.account_id,
                    strategy_version=request.strategy_version,
                ),
            )
            items = _load_review_timeline(conn, request, account.account_id)

        return ServiceResult(
            status="success",
            request_id=context.request_id,
            data=ReviewTimeline(
                strategy_version=request.strategy_version,
                account=account,
                items=items,
                limit=request.limit,
                before_date=request.before_date,
            ),
            lineage={
                "strategy_version": request.strategy_version,
                "account_id": account.account_id,
                "review_count": len(items),
            },
        )


def render_daily_report_json(report: DailyReport) -> str:
    return json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_daily_report_markdown(report: DailyReport) -> str:
    lines = [
        "# PGC 每日复盘报告",
        "",
        f"生成时间：{report.generated_at}",
        f"复盘日：{_date_text(report.as_of_date)}",
        f"最新行情日：{_date_text(report.latest_market_date)}",
        f"下一交易日：{_date_text(report.next_trade_date)}",
        f"策略版本：{report.strategy_version}",
        "",
        "## 账户",
        "",
        f"- 账户：{_account_name(report.account)}",
        f"- 账户类型：{report.account.account_type or '未确认'}",
        f"- 最大持仓：{_none_dash(report.account.max_positions)}",
        f"- 当前持仓：{report.account.open_positions}",
        f"- 空闲仓位：{_none_dash(report.account.free_position_slots)}",
        f"- 最新权益：{_money(report.account.total_equity)}",
    ]
    lines.extend(_paper_promotion_lines(report.paper_promotion))
    lines.extend(_daily_acceptance_lines(report.paper_acceptance))
    lines.extend(_next_day_decision_lines(report.next_day_decision))
    lines.extend([
        "",
        "## 数据状态",
        "",
        f"- 结果：{_readiness_text(report.data_quality.readiness)}",
        f"- 可交易：{'是' if report.data_quality.can_trade else '否'}",
        f"- 有效入池事件：{report.data_quality.valid_raw_count}",
        f"- 阻断 / 警告：{report.data_quality.blocker_count} / {report.data_quality.warning_count}",
        f"- 缺失行情：{report.data_quality.missing_market_bar_count}",
    ])
    if report.data_quality.event_ids:
        lines.append(f"- 质量事件：{', '.join(str(event_id) for event_id in report.data_quality.event_ids)}")

    lines.extend(["", "## 今日候选", ""])
    if report.candidate is None:
        lines.append(f"今日没有可执行候选。原因：{_reason_text(report.no_candidate_reason)}")
    else:
        candidate = report.candidate
        lines.extend(
            [
                f"- 股票：{candidate.ts_code} {candidate.name}",
                f"- 评分：{candidate.score:.4f}",
                f"- 排名：{_none_dash(candidate.signal_rank)}",
                f"- 计划买入日：{_date_text(candidate.planned_buy_date)}",
                f"- 入选说明：{_selection_text(candidate)}",
            ]
        )
        if candidate.ranked_signals:
            lines.extend(["", "| 排名 | 股票 | 评分 |", "| ---: | --- | ---: |"])
            for signal in candidate.ranked_signals[:5]:
                rank = signal.signal_rank if signal.signal_rank is not None else "-"
                lines.append(f"| {rank} | {signal.ts_code} {signal.name} | {signal.score:.4f} |")

    lines.extend(["", "## 明日交易计划", ""])
    if report.buy_plan is None:
        lines.append("当前没有已生成的明日交易计划。")
    else:
        plan = report.buy_plan
        lines.extend(
            [
                f"- 动作：{_action_text(plan.action)}",
                f"- 状态：{_status_text(plan.status)}",
                f"- 计划交易日：{_date_text(plan.planned_trade_date)}",
                f"- 计划资金：{_money(plan.planned_cash)}",
                f"- 计划股数：{_none_dash(plan.planned_shares)}",
                f"- 原因：{_reason_text(plan.reason)}",
            ]
        )

    lines.extend(_market_review_lines(report.market_review))
    lines.extend(_market_plan_context_lines(report.market_plan_context))

    lines.extend(["", "## Agent 复核", ""])
    lines.extend(
        [
            f"- 状态：{_status_text(report.agent_advice.status)}",
            f"- 来源：{report.agent_advice.source_label or _agent_source_label(report.agent_advice.execution_mode)}",
            f"- 运行模式：{report.agent_advice.execution_mode or 'unknown'}",
            f"- 意见：{_agent_action_text(report.agent_advice.action)}",
            f"- 风险：{_risk_text(report.agent_advice.risk_level)}",
            f"- 摘要：{report.agent_advice.summary or report.agent_advice.note}",
            "- 提醒：Agent 只提供复核意见，不会自动改变交易计划。",
        ]
    )
    if report.agent_advice.external_data_coverage:
        coverage = report.agent_advice.external_data_coverage
        lines.extend(
            [
                f"- 数据覆盖：技术面 {_agent_coverage_text(coverage.get('technical'))} / "
                f"基本面 {_agent_coverage_text(coverage.get('fundamental'))} / "
                f"新闻面 {_agent_coverage_text(coverage.get('news'))} / "
                f"情绪面 {_agent_coverage_text(coverage.get('sentiment'))}",
            ]
        )
    if report.agent_advice.external_evidence:
        lines.extend(["", "外部证据："])
        for evidence in report.agent_advice.external_evidence:
            lines.append(
                f"- [{_agent_evidence_category_text(evidence.category)}] {evidence.source} "
                f"{_date_text(evidence.published_date)} {evidence.title}：{evidence.summary}"
            )
    if report.agent_advice.missing_data_warnings:
        lines.extend(["", "未接入/缺失："])
        lines.extend(f"- {warning}" for warning in report.agent_advice.missing_data_warnings)
    if report.agent_advice.supporting_points:
        lines.extend(["", "支持依据："])
        lines.extend(f"- {point}" for point in report.agent_advice.supporting_points)
    if report.agent_advice.risk_points:
        lines.extend(["", "风险提示："])
        lines.extend(f"- {point}" for point in report.agent_advice.risk_points)
    if report.agent_advice.analyst_reports:
        lines.extend(["", "分项分析："])
        for analyst in report.agent_advice.analyst_reports:
            lines.extend(["", f"### {analyst.analyst_name}", "", analyst.summary])
            if analyst.supporting_points:
                lines.extend(["", "支持依据：", *[f"- {point}" for point in analyst.supporting_points]])
            if analyst.risk_points:
                lines.extend(["", "风险提示：", *[f"- {point}" for point in analyst.risk_points]])
    if report.agent_advice.report_sections:
        lines.extend(["", "中文结构化报告："])
        for section in report.agent_advice.report_sections:
            lines.extend(["", f"### {section.section_name}", "", f"来源：{section.source_label}", "", section.summary])
            if section.source_refs:
                lines.append(f"source_refs：{', '.join(section.source_refs)}")
            if section.supporting_points:
                lines.extend(["", "支持依据：", *[f"- {point}" for point in section.supporting_points]])
            if section.risk_points:
                lines.extend(["", "风险提示：", *[f"- {point}" for point in section.risk_points]])

    lines.extend(["", "## 当前持仓处理", ""])
    if not report.positions:
        lines.append("当前账户没有未平仓持仓。")
    else:
        lines.extend(
            [
                "| 股票 | 买入日 | 状态 | T+2 | T+5 | 当前处理 |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for position in report.positions:
            lines.append(
                "| "
                f"{position.ts_code} {position.name} | "
                f"{_date_text(position.buy_date)} | "
                f"{_status_text(position.status)} | "
                f"{_date_text(position.planned_t2_date)} | "
                f"{_date_text(position.planned_t5_date)} | "
                f"{_due_text(position.action_due)} |"
            )

    lines.extend(["", "## 数据血缘", ""])
    lineage_rows = [
        ("特征运行", report.lineage.feature_run_id),
        ("策略运行", report.lineage.strategy_run_id),
        ("行情抓取", report.lineage.market_fetch_run_id),
        ("入选记录", report.lineage.daily_pick_id),
        ("信号记录", report.lineage.signal_id),
        ("计划记录", report.lineage.trade_plan_id),
        ("全市场复盘", report.lineage.market_review_run_id),
        ("Agent 运行", report.lineage.agent_run_id),
        ("Agent 意见", report.lineage.agent_decision_id),
    ]
    lines.extend(["| 项目 | ID |", "| --- | ---: |"])
    for label, value in lineage_rows:
        lines.append(f"| {label} | {_none_dash(value)} |")
    if report.lineage.data_quality_event_ids:
        lines.append(f"| 数据质量事件 | {', '.join(str(event_id) for event_id in report.lineage.data_quality_event_ids)} |")

    return "\n".join(lines).rstrip() + "\n"


def _validate_request(request: DailyReportRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not is_yyyymmdd(request.as_of_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="as_of_date must use YYYYMMDD format."))
    if not request.strategy_version.strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="strategy_version is required."))
    if request.account_id is None and not request.account_key:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="account_key or account_id is required."))
    if request.account_id is not None and request.account_id <= 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="account_id must be positive."))
    return errors


def _validate_history_request(request: DailyReviewHistoryRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not request.strategy_version.strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="strategy_version is required."))
    if request.account_id is None and not request.account_key:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="account_key or account_id is required."))
    if request.account_id is not None and request.account_id <= 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="account_id must be positive."))
    if request.before_date is not None and not is_yyyymmdd(request.before_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="before_date must use YYYYMMDD format."))
    if request.limit < 1 or request.limit > 100:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="limit must be between 1 and 100."))
    return errors


def _validate_timeline_request(request: ReviewTimelineRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not request.strategy_version.strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="strategy_version is required."))
    if request.account_id is None and not request.account_key:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="account_key or account_id is required."))
    if request.account_id is not None and request.account_id <= 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="account_id must be positive."))
    if request.before_date is not None and not is_yyyymmdd(request.before_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="before_date must use YYYYMMDD format."))
    if request.limit < 1 or request.limit > 100:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="limit must be between 1 and 100."))
    return errors


def _validate_acceptance_history_request(request: PaperAcceptanceHistoryRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not request.strategy_version.strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="strategy_version is required."))
    if request.account_id is None and not request.account_key:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="account_key or account_id is required."))
    if request.account_id is not None and request.account_id <= 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="account_id must be positive."))
    if request.before_date is not None and not is_yyyymmdd(request.before_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="before_date must use YYYYMMDD format."))
    if request.limit < 1 or request.limit > 60:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="limit must be between 1 and 60."))
    return errors


def _validate_ops_history_request(request: OpsHistoryRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not request.strategy_version.strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="strategy_version is required."))
    if request.account_id is None and not request.account_key:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="account_key or account_id is required."))
    if request.account_id is not None and request.account_id <= 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="account_id must be positive."))
    if request.before_date is not None and not is_yyyymmdd(request.before_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="before_date must use YYYYMMDD format."))
    if request.limit < 1 or request.limit > 200:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="limit must be between 1 and 200."))
    return errors


def _data_quality_report(
    result: ServiceResult[Any],
    invariant_report: InvariantReport | None = None,
) -> DataQualityReport:
    data = result.data
    invariant_blockers = 0 if invariant_report is None or invariant_report.ok else len(invariant_report.violations)
    if data is None:
        return DataQualityReport(
            readiness="blocker",
            can_trade=False,
            blocker_count=len(result.errors) + invariant_blockers,
            warning_count=len(result.warnings),
            valid_raw_count=0,
            market_coverage_ok=False,
            trade_calendar_ok=False,
            strategy_version_ok=False,
            account_ok=False,
            missing_market_bar_count=0,
        )
    readiness = "blocker" if invariant_blockers else data.readiness
    return DataQualityReport(
        readiness=readiness,
        can_trade=readiness != "blocker",
        blocker_count=data.blocker_count + invariant_blockers,
        warning_count=data.warning_count,
        valid_raw_count=data.valid_raw_count,
        market_coverage_ok=data.market_coverage_ok,
        trade_calendar_ok=data.trade_calendar_ok,
        strategy_version_ok=data.strategy_version_ok,
        account_ok=data.account_ok,
        missing_market_bar_count=data.missing_market_bar_count,
        event_ids=list(data.data_quality_event_ids),
    )


def _invariant_report_errors(report: InvariantReport) -> list[ServiceError]:
    if report.ok:
        return []
    codes = ", ".join(violation.code for violation in report.violations)
    return [
        ServiceError(
            code="DATABASE_INVARIANTS_FAILED",
            message=f"Ledger/database invariant check failed: {codes}.",
            severity="blocker",
        )
    ]


def _paper_promotion_report(
    db_path: Path,
    request: DailyReportRequest,
    context: RequestContext,
) -> PaperReadinessResult | None:
    result = OperationalReadinessService(db_path).check_paper_readiness(
        PaperReadinessRequest(
            as_of_date=request.as_of_date,
            account_key=request.account_key,
            account_id=request.account_id,
        ),
        RequestContext(
            request_id=f"{context.request_id}:paper-promotion" if context.request_id else None,
            dry_run=True,
            operator=context.operator,
            source=context.source,
        ),
    )
    return result.data


def _open_execution_acceptance(
    db_path: Path,
    request: DailyReportRequest,
    context: RequestContext,
    execution_date: str,
) -> DailyAcceptanceOpenExecution:
    result = OpenExecutionService(db_path).get_open_execution(
        OpenExecutionRequest(
            as_of_date=execution_date,
            account_key=request.account_key,
            account_id=request.account_id,
        ),
        RequestContext(
            request_id=f"{context.request_id}:open-execution" if context.request_id else None,
            dry_run=True,
            operator=context.operator,
            source=context.source,
        ),
    )
    data = result.data
    if data is None:
        return DailyAcceptanceOpenExecution(
            as_of_date=execution_date,
            status="blocked" if result.status in {"blocked", "validation_failed"} else result.status,
            next_action="blocked",
            primary_plan_id=None,
            primary_position_id=None,
            target_stock=None,
            target_name=None,
            planned_trade_date=None,
            planned_shares=None,
            blocked_reasons=[error.message for error in result.errors],
        )

    return DailyAcceptanceOpenExecution(
        as_of_date=data.as_of_date,
        status=data.status,
        next_action=data.next_action,
        primary_plan_id=data.primary_plan_id,
        primary_position_id=data.primary_position_id,
        target_stock=data.target_stock,
        target_name=data.target_name,
        planned_trade_date=data.planned_trade_date,
        planned_shares=data.planned_shares,
        blocked_reasons=list(data.blocked_reasons),
        operator_required=data.operator_required,
    )


def _daily_acceptance_report(
    *,
    request: DailyReportRequest,
    account: AccountReport,
    data_quality: DataQualityReport,
    paper_promotion: PaperReadinessResult | None,
    latest_market_date: str | None,
    next_trade_date: str | None,
    buy_plan: BuyPlanReport | None,
    market_review: MarketReviewReport | None,
    market_plan_context: MarketPlanContextReport | None,
    agent_advice: AgentAdviceReport,
    positions: list[PositionReport],
    due_positions: list[PositionReport],
    open_execution: DailyAcceptanceOpenExecution,
    lineage: ReportLineage,
) -> DailyAcceptanceReport:
    data_freshness = _acceptance_data_freshness_gate(
        request.as_of_date,
        latest_market_date,
        data_quality,
    )
    evidence_coverage = _acceptance_evidence_gate(
        market_review,
        market_plan_context,
        agent_advice,
        lineage,
    )
    agent_status = _acceptance_agent_gate(agent_advice, lineage)
    open_execution_gate = _acceptance_open_execution_gate(open_execution, next_trade_date)
    readiness_gates = _acceptance_readiness_gates(
        account,
        data_quality,
        paper_promotion,
        buy_plan,
        positions,
        due_positions,
    )
    all_gates = [data_freshness, evidence_coverage, agent_status, open_execution_gate, *readiness_gates]
    status = _combined_acceptance_status(all_gates)
    unresolved_blockers = _acceptance_blockers(all_gates, open_execution)
    alerts = _acceptance_alerts(
        as_of_date=request.as_of_date,
        data_freshness=data_freshness,
        evidence_coverage=evidence_coverage,
        agent_status=agent_status,
        open_execution=open_execution,
        open_execution_gate=open_execution_gate,
        unresolved_blockers=unresolved_blockers,
    )

    return DailyAcceptanceReport(
        account_key=account.account_key or request.account_key,
        as_of_date=request.as_of_date,
        execution_date=next_trade_date,
        status=status,
        summary=_acceptance_summary(status, unresolved_blockers, all_gates),
        data_freshness=data_freshness,
        evidence_coverage=evidence_coverage,
        agent_status=agent_status,
        open_execution=open_execution,
        open_execution_gate=open_execution_gate,
        readiness_gates=readiness_gates,
        unresolved_blockers=unresolved_blockers,
        alerts=alerts,
    )


def _next_day_decision_cockpit(
    *,
    report_request: DailyReportRequest,
    account: AccountReport,
    paper_acceptance: DailyAcceptanceReport,
    market_review: MarketReviewReport | None,
    market_plan_context: MarketPlanContextReport | None,
    strategy_proposals: NextDayStrategyProposalSummary,
) -> NextDayDecisionCockpit:
    system_proposal = _next_day_system_proposal(paper_acceptance.open_execution)
    checklist = [
        _next_day_acceptance_check(paper_acceptance),
        _next_day_evidence_check(paper_acceptance.evidence_coverage),
        _next_day_market_review_check(market_review, market_plan_context),
        _next_day_open_execution_check(paper_acceptance.open_execution, paper_acceptance.open_execution_gate),
        _next_day_strategy_proposal_check(strategy_proposals),
    ]
    decision: NextDayDecisionSummary = summarize_next_day_decision(
        checklist,
        default_action=system_proposal.rationale,
    )
    return NextDayDecisionCockpit(
        account_key=account.account_key or report_request.account_key,
        as_of_date=report_request.as_of_date,
        execution_date=paper_acceptance.execution_date,
        status=decision.status,
        headline=decision.headline,
        recommended_manual_action=decision.recommended_manual_action,
        blocker_count=decision.blocker_count,
        warning_count=decision.warning_count,
        system_proposal=system_proposal,
        checklist=checklist,
        strategy_proposals=strategy_proposals,
        acceptance_status=paper_acceptance.status,
        acceptance_summary=paper_acceptance.summary,
        open_execution=paper_acceptance.open_execution,
        market_review=market_review,
        market_plan_context=market_plan_context,
    )


def _next_day_system_proposal(open_execution: DailyAcceptanceOpenExecution) -> NextDaySystemProposal:
    target = " ".join(part for part in [open_execution.target_stock, open_execution.target_name] if part)
    action_text = {
        "record_buy": "人工核对开盘条件后录入买入成交。",
        "record_sell": "人工核对卖出计划后录入卖出成交。",
        "evaluate_exit": "人工评估到期持仓并按显式流程生成退出动作。",
        "wait": "等待未来计划交易日，不做当日成交录入。",
        "none": "下一交易日没有待执行动作，保持观察。",
        "blocked": "先处理 blocker，再重新刷新决策清单。",
    }.get(open_execution.next_action, "人工复核 open-execution 返回的下一步动作。")
    return NextDaySystemProposal(
        action=open_execution.next_action,
        target=target or None,
        trade_plan_id=open_execution.primary_plan_id,
        position_id=open_execution.primary_position_id,
        planned_trade_date=open_execution.planned_trade_date,
        planned_shares=open_execution.planned_shares,
        rationale=action_text,
    )


def _next_day_acceptance_check(acceptance: DailyAcceptanceReport) -> NextDayDecisionChecklistItem:
    return NextDayDecisionChecklistItem(
        key="paper_acceptance",
        label="paper acceptance",
        status=acceptance.status,
        summary=acceptance.summary,
        manual_action=(
            "处理 paper acceptance 未处理 blocker。"
            if acceptance.status == "blocked"
            else "人工复核 paper acceptance warning。"
            if acceptance.status == "warning"
            else "保持只读验收通过记录。"
        ),
        detail="汇总数据新鲜度、证据覆盖、Agent、open-execution 和 readiness gates。",
        blocker_codes=_gate_codes(_acceptance_all_gates(acceptance), include_blockers=True, include_warnings=False),
        warning_codes=_gate_codes(_acceptance_all_gates(acceptance), include_blockers=False, include_warnings=True),
        source_refs=_acceptance_source_refs(acceptance),
    )


def _next_day_evidence_check(gate: DailyAcceptanceGate) -> NextDayDecisionChecklistItem:
    return NextDayDecisionChecklistItem(
        key="evidence_blockers",
        label="证据 freshness / coverage",
        status=gate.status,
        summary=gate.summary,
        manual_action=(
            "补齐或确认 cached provider evidence，再重新运行只读验收。"
            if gate.status in {"blocked", "warning"}
            else "证据覆盖通过，保留 source_refs 供人工抽查。"
        ),
        detail=gate.detail,
        blocker_codes=list(gate.blocker_codes),
        warning_codes=list(gate.warning_codes),
        source_refs=list(gate.source_refs),
    )


def _next_day_market_review_check(
    market_review: MarketReviewReport | None,
    market_plan_context: MarketPlanContextReport | None,
) -> NextDayDecisionChecklistItem:
    if market_review is None:
        return NextDayDecisionChecklistItem(
            key="market_review",
            label="全市场复盘",
            status="warning",
            summary="未找到全市场复盘，市场状态和板块轮动需要人工复核。",
            manual_action="运行或导入只读全市场复盘证据，或人工记录缺失原因。",
            detail="缺失市场复盘不会被当作安全信号。",
            warning_codes=["MARKET_REVIEW_MISSING"],
        )
    warning_codes: list[str] = []
    status = "pass"
    manual_action = "按全市场复盘和计划关系继续人工核对。"
    if market_plan_context is None:
        status = "warning"
        warning_codes.append("MARKET_PLAN_CONTEXT_MISSING")
        manual_action = "补齐全市场复盘与明日计划关系，或人工确认该计划无需市场上下文。"
    elif market_plan_context.management_action in {"manual_review", "consider_cancel", "unknown"}:
        status = "warning"
        warning_codes.append(f"MARKET_ACTION_{market_plan_context.management_action.upper()}")
        manual_action = "人工复核全市场复盘给出的计划管理建议。"
    return NextDayDecisionChecklistItem(
        key="market_review",
        label="全市场复盘 / 计划关系",
        status=status,
        summary=(
            f"{market_review.regime}；{market_review.summary or '无摘要'}；"
            f"计划建议 {market_plan_context.management_action if market_plan_context else 'missing'}"
        ),
        manual_action=manual_action,
        detail="市场复盘只提供 advisory，不会创建、取消或执行交易计划。",
        warning_codes=warning_codes,
        source_refs=[
            f"market_review_runs:{market_review.market_review_run_id}",
            *(
                [f"market_plan_contexts:{market_plan_context.market_review_run_id}:{market_plan_context.trade_plan_id}"]
                if market_plan_context
                else []
            ),
        ],
    )


def _next_day_open_execution_check(
    open_execution: DailyAcceptanceOpenExecution,
    gate: DailyAcceptanceGate,
) -> NextDayDecisionChecklistItem:
    return NextDayDecisionChecklistItem(
        key="open_execution",
        label="open-execution 下一步",
        status=gate.status,
        summary=f"{open_execution.status} / {open_execution.next_action}",
        manual_action=(
            "先处理 open-execution blocker，再进入成交或退出流程。"
            if gate.status == "blocked"
            else _next_day_system_proposal(open_execution).rationale
        ),
        detail=gate.detail,
        blocker_codes=list(gate.blocker_codes),
        warning_codes=list(gate.warning_codes),
        source_refs=list(gate.source_refs),
    )


def _next_day_strategy_proposal_check(
    proposals: NextDayStrategyProposalSummary,
) -> NextDayDecisionChecklistItem:
    if proposals.review_required_count:
        return NextDayDecisionChecklistItem(
            key="strategy_proposals",
            label="策略 proposal / hypothesis",
            status="warning",
            summary=(
                f"{proposals.review_required_count} 项策略假设或 proposal 需要人工审阅；"
                f"accepted={proposals.accepted_count} testing={proposals.testing_count} proposed={proposals.proposed_count}"
            ),
            manual_action="审阅策略假设和 proposal artifact；不要直接改 active params 或 paper/live 行为。",
            detail="策略提案只生成研究/晋级任务线索，不会自动修改策略参数。",
            warning_codes=["STRATEGY_PROPOSAL_REVIEW_REQUIRED"],
            source_refs=[f"strategy_hypotheses:{item.hypothesis_id}" for item in proposals.items],
        )
    return NextDayDecisionChecklistItem(
        key="strategy_proposals",
        label="策略 proposal / hypothesis",
        status="pass",
        summary="没有待审阅策略假设或 proposal。",
        manual_action="无需策略参数动作；继续保持策略 evolution 只读边界。",
        detail="没有 active strategy 参数、trade plan、position 或 live 行为被修改。",
    )


def _acceptance_source_refs(acceptance: DailyAcceptanceReport) -> list[str]:
    refs: list[str] = []
    for gate in _acceptance_all_gates(acceptance):
        for ref in gate.source_refs:
            if ref not in refs:
                refs.append(ref)
    return refs


def _acceptance_data_freshness_gate(
    as_of_date: str,
    latest_market_date: str | None,
    data_quality: DataQualityReport,
) -> DailyAcceptanceGate:
    blocker_codes: list[str] = []
    warning_codes: list[str] = []
    status = "pass"
    if data_quality.readiness in {"blocker", "blocked"}:
        status = "blocked"
        blocker_codes.append("DATA_QUALITY_BLOCKER")
    elif not latest_market_date:
        status = "warning"
        warning_codes.append("MARKET_DATA_MISSING")
    elif latest_market_date < as_of_date:
        status = "warning"
        warning_codes.append("STALE_MARKET_DATA")
    if not data_quality.trade_calendar_ok:
        status = "blocked"
        blocker_codes.append("TRADE_CALENDAR_NOT_READY")
    if not data_quality.market_coverage_ok:
        status = "blocked"
        blocker_codes.append("MARKET_COVERAGE_NOT_READY")
    return DailyAcceptanceGate(
        key="data_freshness",
        label="数据新鲜度",
        status=status,
        summary=f"最新行情日 {_date_text(latest_market_date)} / 复盘日 {_date_text(as_of_date)}",
        detail=(
            f"有效入池 {data_quality.valid_raw_count}；"
            f"缺失行情 {data_quality.missing_market_bar_count}；"
            f"blocker/warning {data_quality.blocker_count}/{data_quality.warning_count}"
        ),
        blocker_codes=blocker_codes,
        warning_codes=warning_codes,
        source_refs=[f"data_quality_events:{event_id}" for event_id in data_quality.event_ids],
    )


def _acceptance_evidence_gate(
    market_review: MarketReviewReport | None,
    market_plan_context: MarketPlanContextReport | None,
    agent_advice: AgentAdviceReport,
    lineage: ReportLineage,
) -> DailyAcceptanceGate:
    warning_codes: list[str] = []
    source_refs: list[str] = []
    market_count = 0
    if market_review is None:
        warning_codes.append("MARKET_REVIEW_MISSING")
    else:
        market_count = _optional_int_from_any(market_review.external_evidence_coverage.get("total_count")) or 0
        source_refs.append(f"market_review_runs:{market_review.market_review_run_id}")
        if market_count <= 0:
            warning_codes.append("MARKET_EVIDENCE_MISSING")
    if market_plan_context is None and lineage.trade_plan_id is not None:
        warning_codes.append("MARKET_PLAN_CONTEXT_MISSING")
    elif market_plan_context is not None:
        source_refs.append(f"market_plan_contexts:{market_plan_context.market_review_run_id}:{market_plan_context.trade_plan_id}")

    coverage = agent_advice.external_data_coverage
    unavailable_count = sum(1 for value in coverage.values() if str(value) in {"missing", "unavailable"})
    if not coverage or unavailable_count == len(coverage):
        warning_codes.append("AGENT_EXTERNAL_EVIDENCE_MISSING")
    source_refs.extend(agent_advice.source_refs)

    return DailyAcceptanceGate(
        key="evidence_coverage",
        label="证据覆盖",
        status="warning" if warning_codes else "pass",
        summary=f"全市场证据 {market_count} 条；Agent 覆盖 {len(coverage)} 项",
        detail="Missing evidence is explicit and remains advisory; no cached evidence mutates strategy or trades.",
        warning_codes=warning_codes,
        source_refs=source_refs,
    )


def _acceptance_agent_gate(
    agent_advice: AgentAdviceReport,
    lineage: ReportLineage,
) -> DailyAcceptanceGate:
    warning_codes: list[str] = []
    if agent_advice.status in {"failed", "unavailable"}:
        warning_codes.append("AGENT_REVIEW_UNAVAILABLE")
    elif agent_advice.status in {"not_run", "skipped"} or agent_advice.agent_run_id is None:
        warning_codes.append("AGENT_REVIEW_NOT_RUN")
    return DailyAcceptanceGate(
        key="agent_status",
        label="Agent 状态",
        status="warning" if warning_codes else "pass",
        summary=f"{agent_advice.status} / {agent_advice.action} / risk {agent_advice.risk_level}",
        detail=agent_advice.summary or agent_advice.note or "Agent 只读 advisory。",
        warning_codes=warning_codes,
        source_refs=[f"agent_runs:{lineage.agent_run_id}"] if lineage.agent_run_id else [],
    )


def _acceptance_open_execution_gate(
    open_execution: DailyAcceptanceOpenExecution,
    expected_execution_date: str | None,
) -> DailyAcceptanceGate:
    blocker_codes: list[str] = []
    warning_codes: list[str] = []
    if open_execution.status == "blocked" or open_execution.next_action == "blocked":
        blocker_codes.append("OPEN_EXECUTION_BLOCKED")
    elif open_execution.status == "unavailable":
        warning_codes.append("OPEN_EXECUTION_UNAVAILABLE")
    if expected_execution_date and open_execution.as_of_date != expected_execution_date:
        warning_codes.append("OPEN_EXECUTION_DATE_MISMATCH")
    if (
        expected_execution_date
        and open_execution.planned_trade_date is not None
        and open_execution.planned_trade_date != expected_execution_date
    ):
        warning_codes.append("OPEN_EXECUTION_PLAN_DATE_MISMATCH")
    return DailyAcceptanceGate(
        key="open_execution",
        label="open-execution 状态",
        status="blocked" if blocker_codes else "warning" if warning_codes else "pass",
        summary=f"{open_execution.status} / {open_execution.next_action}",
        detail=(
            f"执行日 {_date_text(open_execution.as_of_date)}；"
            f"预期 {_date_text(expected_execution_date)}；"
            f"计划 {open_execution.primary_plan_id or '-'}；"
            f"持仓 {open_execution.primary_position_id or '-'}"
        ),
        blocker_codes=blocker_codes,
        warning_codes=warning_codes,
        source_refs=[
            ref
            for ref in [
                f"trade_plans:{open_execution.primary_plan_id}" if open_execution.primary_plan_id else "",
                f"positions:{open_execution.primary_position_id}" if open_execution.primary_position_id else "",
            ]
            if ref
        ],
    )


def _acceptance_readiness_gates(
    account: AccountReport,
    data_quality: DataQualityReport,
    paper_promotion: PaperReadinessResult | None,
    buy_plan: BuyPlanReport | None,
    positions: list[PositionReport],
    due_positions: list[PositionReport],
) -> list[DailyAcceptanceGate]:
    gates = [
        DailyAcceptanceGate(
            key="daily_review_readiness",
            label="daily review readiness gate",
            status="blocked" if data_quality.readiness in {"blocker", "blocked"} else "pass",
            summary=f"readiness={data_quality.readiness}",
            detail=f"可交易 {'是' if data_quality.can_trade else '否'}；质量事件 {len(data_quality.event_ids)} 个",
            blocker_codes=["DAILY_REVIEW_READINESS_BLOCKED"]
            if data_quality.readiness in {"blocker", "blocked"}
            else [],
            source_refs=[f"data_quality_events:{event_id}" for event_id in data_quality.event_ids],
        ),
        DailyAcceptanceGate(
            key="account_capacity",
            label="账户容量 gate",
            status="blocked" if buy_plan is not None and (account.free_position_slots or 0) <= 0 else "pass",
            summary=f"持仓 {account.open_positions}/{account.max_positions or '-'}；空闲 {account.free_position_slots}",
            detail=f"当前持仓 {len(positions)}；T+2/T+5 待处理 {len(due_positions)}",
            blocker_codes=["NO_FREE_POSITION_SLOTS"]
            if buy_plan is not None and (account.free_position_slots or 0) <= 0
            else [],
        ),
    ]
    if paper_promotion is None:
        gates.append(
            DailyAcceptanceGate(
                key="paper_readiness",
                label="paper-readiness gate",
                status="warning",
                summary="未计算 paper-readiness",
                detail="Paper 晋级和账本 gate 暂无结果。",
                warning_codes=["PAPER_READINESS_MISSING"],
            )
        )
        return gates

    for gate in paper_promotion.readiness_gates:
        gates.append(
            DailyAcceptanceGate(
                key=f"paper_{gate.gate}",
                label=gate.label,
                status=gate.status,
                summary=gate.summary,
                detail="来自 paper-readiness；用于暴露晋级和账本 gate，不会自动执行任何交易动作。",
                blocker_codes=list(gate.blocker_codes),
                warning_codes=list(gate.warning_codes),
            )
        )
    return gates


def _combined_acceptance_status(gates: list[DailyAcceptanceGate]) -> str:
    if any(gate.status == "blocked" for gate in gates):
        return "blocked"
    if any(gate.status == "warning" for gate in gates):
        return "warning"
    return "pass"


def _acceptance_blockers(
    gates: list[DailyAcceptanceGate],
    open_execution: DailyAcceptanceOpenExecution,
) -> list[str]:
    blockers: list[str] = []
    for gate in gates:
        for code in gate.blocker_codes:
            blockers.append(f"{gate.label}: {code}")
    for reason in open_execution.blocked_reasons:
        blockers.append(f"open-execution: {reason}")
    return blockers


def _acceptance_summary(
    status: str,
    unresolved_blockers: list[str],
    gates: list[DailyAcceptanceGate],
) -> str:
    if status == "blocked":
        return f"纸盘每日运营验收阻断：{len(unresolved_blockers)} 项 blocker 需要先处理。"
    warnings = sum(1 for gate in gates if gate.status == "warning")
    if status == "warning":
        return f"纸盘每日运营验收有 {warnings} 项证据或 advisory 警告，需人工复核后继续。"
    return "纸盘每日运营验收通过；仍需人工确认开盘检查和成交事实。"


def _acceptance_alerts(
    *,
    as_of_date: str,
    data_freshness: DailyAcceptanceGate,
    evidence_coverage: DailyAcceptanceGate,
    agent_status: DailyAcceptanceGate,
    open_execution: DailyAcceptanceOpenExecution,
    open_execution_gate: DailyAcceptanceGate,
    unresolved_blockers: list[str],
) -> list[DailyAcceptanceAlert]:
    alerts: list[DailyAcceptanceAlert] = []
    if unresolved_blockers:
        alerts.append(
            DailyAcceptanceAlert(
                severity="blocker",
                code="UNRESOLVED_ACCEPTANCE_BLOCKERS",
                title="未处理 blocker",
                summary=f"{len(unresolved_blockers)} 项 blocker 仍未处理，paper acceptance 不能视为通过。",
                as_of_date=as_of_date,
                gate_key="unresolved_blockers",
                action="quality",
            )
        )

    stale_codes = _matching_codes([data_freshness, evidence_coverage], PAPER_ACCEPTANCE_STALE_EVIDENCE_CODES)
    if stale_codes:
        alerts.append(
            DailyAcceptanceAlert(
                severity="warning",
                code="STALE_OR_MISSING_EVIDENCE",
                title="证据或行情不新鲜",
                summary=f"{_date_text(as_of_date)} 存在 {', '.join(stale_codes[:4])}，需人工复核证据覆盖。",
                as_of_date=as_of_date,
                gate_key="evidence_coverage",
                action="market",
            )
        )

    agent_codes = _matching_codes([agent_status], PAPER_ACCEPTANCE_AGENT_REVIEW_CODES)
    if agent_codes:
        alerts.append(
            DailyAcceptanceAlert(
                severity="warning",
                code="AGENT_REVIEW_MISSING",
                title="Agent 复核缺失",
                summary=f"{_date_text(as_of_date)} 的 Agent 状态为 {agent_status.summary}。",
                as_of_date=as_of_date,
                gate_key="agent_status",
                action="agent",
            )
        )

    open_execution_codes = _matching_codes([open_execution_gate], PAPER_ACCEPTANCE_OPEN_EXECUTION_MISMATCH_CODES)
    if open_execution_codes or _open_execution_mismatch(open_execution_gate, open_execution):
        alerts.append(
            DailyAcceptanceAlert(
                severity="blocker" if "OPEN_EXECUTION_BLOCKED" in open_execution_codes else "warning",
                code="OPEN_EXECUTION_MISMATCH",
                title="open-execution 不匹配",
                summary=f"{_date_text(as_of_date)} open-execution 为 {open_execution.status}/{open_execution.next_action}。",
                as_of_date=as_of_date,
                gate_key="open_execution",
                action="execution",
            )
        )
    return alerts


def _acceptance_history_item(acceptance: DailyAcceptanceReport) -> DailyAcceptanceHistoryItem:
    gates = _acceptance_all_gates(acceptance)
    return DailyAcceptanceHistoryItem(
        as_of_date=acceptance.as_of_date,
        execution_date=acceptance.execution_date,
        status=acceptance.status,
        summary=acceptance.summary,
        unresolved_blocker_count=len(acceptance.unresolved_blockers),
        warning_count=sum(len(gate.warning_codes) for gate in gates),
        alert_count=len(acceptance.alerts),
        data_freshness_status=acceptance.data_freshness.status,
        evidence_coverage_status=acceptance.evidence_coverage.status,
        agent_status=acceptance.agent_status.status,
        open_execution_status=acceptance.open_execution.status,
        open_execution_next_action=acceptance.open_execution.next_action,
        open_execution_mismatch=_open_execution_mismatch(acceptance.open_execution_gate, acceptance.open_execution),
        blocker_codes=_gate_codes(gates, include_blockers=True, include_warnings=False),
        warning_codes=_gate_codes(gates, include_blockers=False, include_warnings=True),
        alert_codes=[alert.code for alert in acceptance.alerts],
    )


def _unavailable_acceptance_history_item(
    review_date: str,
    alert: DailyAcceptanceAlert,
) -> DailyAcceptanceHistoryItem:
    return DailyAcceptanceHistoryItem(
        as_of_date=review_date,
        execution_date=None,
        status="blocked",
        summary=alert.summary,
        unresolved_blocker_count=1,
        warning_count=0,
        alert_count=1,
        data_freshness_status="blocked",
        evidence_coverage_status="blocked",
        agent_status="blocked",
        open_execution_status="blocked",
        open_execution_next_action="blocked",
        open_execution_mismatch=True,
        blocker_codes=[alert.code],
        warning_codes=[],
        alert_codes=[alert.code],
    )


def _acceptance_all_gates(acceptance: DailyAcceptanceReport) -> list[DailyAcceptanceGate]:
    return [
        acceptance.data_freshness,
        acceptance.evidence_coverage,
        acceptance.agent_status,
        acceptance.open_execution_gate,
        *acceptance.readiness_gates,
    ]


def _matching_codes(gates: list[DailyAcceptanceGate], candidates: frozenset[str]) -> list[str]:
    matches: list[str] = []
    for gate in gates:
        for code in [*gate.blocker_codes, *gate.warning_codes]:
            if code in candidates and code not in matches:
                matches.append(code)
    return matches


def _gate_codes(
    gates: list[DailyAcceptanceGate],
    *,
    include_blockers: bool,
    include_warnings: bool,
) -> list[str]:
    codes: list[str] = []
    for gate in gates:
        if include_blockers:
            codes.extend(code for code in gate.blocker_codes if code not in codes)
        if include_warnings:
            codes.extend(code for code in gate.warning_codes if code not in codes)
    return codes


def _open_execution_mismatch(
    gate: DailyAcceptanceGate,
    open_execution: DailyAcceptanceOpenExecution,
) -> bool:
    codes = set(gate.warning_codes) | set(gate.blocker_codes)
    if codes.intersection(PAPER_ACCEPTANCE_OPEN_EXECUTION_MISMATCH_CODES):
        return True
    if open_execution.status == "blocked" or open_execution.next_action == "blocked":
        return True
    return False


def _acceptance_history_trend(items: list[DailyAcceptanceHistoryItem]) -> dict[str, int | str | None]:
    blocked_days = sum(1 for item in items if item.status == "blocked")
    warning_days = sum(1 for item in items if item.status == "warning")
    pass_days = sum(1 for item in items if item.status == "pass")
    return {
        "days": len(items),
        "blocked_days": blocked_days,
        "warning_days": warning_days,
        "pass_days": pass_days,
        "latest_status": items[0].status if items else None,
        "latest_as_of_date": items[0].as_of_date if items else None,
        "unresolved_blocker_days": sum(1 for item in items if item.unresolved_blocker_count > 0),
        "stale_evidence_days": sum(1 for item in items if "STALE_OR_MISSING_EVIDENCE" in item.alert_codes),
        "missing_agent_days": sum(1 for item in items if "AGENT_REVIEW_MISSING" in item.alert_codes),
        "open_execution_mismatch_days": sum(1 for item in items if item.open_execution_mismatch),
    }


def _acceptance_history_summary(trend: dict[str, int | str | None]) -> str:
    days = int(trend["days"] or 0)
    if days == 0:
        return "暂无 paper acceptance 历史。"
    return (
        f"近 {days} 日 paper acceptance："
        f"阻断 {trend['blocked_days']} 日，警告 {trend['warning_days']} 日，通过 {trend['pass_days']} 日；"
        f"最新 {_date_text(str(trend['latest_as_of_date']))} 为 {_acceptance_status_text(str(trend['latest_status']))}。"
    )


def _load_account(conn: Any, request: DailyReportRequest) -> AccountReport:
    if request.account_id is not None:
        row = conn.execute(
            """
            SELECT id, account_key, name, account_type, max_positions
            FROM portfolio_accounts
            WHERE id = ?
            """,
            (request.account_id,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT id, account_key, name, account_type, max_positions
            FROM portfolio_accounts
            WHERE account_key = ?
            """,
            (request.account_key,),
        ).fetchone()

    if row is None:
        return AccountReport(
            account_id=request.account_id,
            account_key=request.account_key,
            name=None,
            account_type=None,
            max_positions=None,
            open_positions=0,
            free_position_slots=None,
            cash=None,
            market_value=None,
            total_equity=None,
            equity_as_of_date=None,
        )

    account_id = int(row["id"])
    open_positions = _open_position_count(conn, account_id)
    max_positions = int(row["max_positions"])
    equity = conn.execute(
        """
        SELECT as_of_date, cash, market_value, total_equity
        FROM equity_snapshots
        WHERE account_id = ?
        ORDER BY as_of_date DESC, id DESC
        LIMIT 1
        """,
        (account_id,),
    ).fetchone()
    return AccountReport(
        account_id=account_id,
        account_key=row["account_key"],
        name=row["name"],
        account_type=row["account_type"],
        max_positions=max_positions,
        open_positions=open_positions,
        free_position_slots=max(max_positions - open_positions, 0),
        cash=_optional_float(equity["cash"]) if equity is not None else None,
        market_value=_optional_float(equity["market_value"]) if equity is not None else None,
        total_equity=_optional_float(equity["total_equity"]) if equity is not None else None,
        equity_as_of_date=equity["as_of_date"] if equity is not None else None,
    )


def _load_candidate(conn: Any, request: DailyReportRequest) -> CandidateReport | None:
    row = conn.execute(
        """
        SELECT
          dp.id AS daily_pick_id,
          dp.strategy_run_id,
          sr.feature_run_id,
          fr.input_market_fetch_run_id,
          dp.signal_id,
          ss.feature_snapshot_id,
          ss.ts_code,
          ss.name,
          dp.review_date,
          dp.planned_buy_date,
          dp.score,
          ss.signal_rank,
          dp.selection_reason,
          ss.features_json
        FROM daily_picks dp
        JOIN strategy_runs sr ON sr.id = dp.strategy_run_id
        JOIN strategy_signals ss ON ss.id = dp.signal_id
        LEFT JOIN feature_runs fr ON fr.id = sr.feature_run_id
        WHERE dp.review_date = ?
          AND sr.strategy_version = ?
        ORDER BY dp.id DESC
        LIMIT 1
        """,
        (request.as_of_date, request.strategy_version),
    ).fetchone()
    if row is None:
        return None

    ranked_signals = _load_ranked_signals(conn, int(row["strategy_run_id"]))
    return CandidateReport(
        daily_pick_id=int(row["daily_pick_id"]),
        strategy_run_id=int(row["strategy_run_id"]),
        feature_run_id=_optional_int(row["feature_run_id"]),
        market_fetch_run_id=_optional_int(row["input_market_fetch_run_id"]),
        signal_id=int(row["signal_id"]),
        feature_snapshot_id=_optional_int(row["feature_snapshot_id"]),
        ts_code=row["ts_code"],
        name=row["name"],
        review_date=row["review_date"],
        planned_buy_date=row["planned_buy_date"],
        score=float(row["score"]),
        signal_rank=_optional_int(row["signal_rank"]),
        selection_reason=row["selection_reason"],
        selected_over_signal_count=max(len(ranked_signals) - 1, 0),
        ranked_signals=ranked_signals,
        features=_loads_json_object(row["features_json"]),
    )


def _load_ranked_signals(conn: Any, strategy_run_id: int) -> list[SignalReport]:
    rows = conn.execute(
        """
        SELECT id, ts_code, name, score, signal_rank
        FROM strategy_signals
        WHERE strategy_run_id = ?
        ORDER BY signal_rank IS NULL, signal_rank, score DESC, id
        LIMIT 10
        """,
        (strategy_run_id,),
    ).fetchall()
    return [
        SignalReport(
            signal_id=int(row["id"]),
            ts_code=row["ts_code"],
            name=row["name"],
            score=float(row["score"]),
            signal_rank=_optional_int(row["signal_rank"]),
        )
        for row in rows
    ]


def _load_review_history(
    conn: Any,
    request: DailyReviewHistoryRequest,
    account_id: int | None,
) -> list[DailyReviewHistoryItem]:
    rows = conn.execute(
        """
        WITH latest_runs AS (
          SELECT MAX(id) AS strategy_run_id
          FROM strategy_runs
          WHERE strategy_version = ?
            AND (? IS NULL OR as_of_date <= ?)
          GROUP BY as_of_date
          ORDER BY as_of_date DESC, MAX(id) DESC
          LIMIT ?
        )
        SELECT
          sr.id AS strategy_run_id,
          sr.as_of_date AS review_date,
          sr.status AS review_status,
          sr.created_at,
          dp.id AS daily_pick_id,
          dp.planned_buy_date,
          dp.score,
          dp.selection_reason,
          ss.id AS signal_id,
          ss.ts_code,
          ss.name,
          tp.id AS trade_plan_id,
          tp.action AS trade_plan_action,
          tp.status AS trade_plan_status,
          tp.planned_trade_date,
          ar.status AS agent_status,
          ad.action AS agent_action,
          ad.risk_level AS agent_risk_level,
          (
            SELECT COUNT(*)
            FROM strategy_signals ss_count
            WHERE ss_count.strategy_run_id = sr.id
          ) AS signals_count,
          (
            SELECT COUNT(*)
            FROM data_quality_events dqe
            WHERE dqe.trade_date = sr.as_of_date
              AND dqe.status = 'open'
              AND dqe.severity = 'blocker'
          ) AS blocker_count,
          (
            SELECT COUNT(*)
            FROM data_quality_events dqe
            WHERE dqe.trade_date = sr.as_of_date
              AND dqe.status = 'open'
              AND dqe.severity = 'warning'
          ) AS warning_count,
          (
            SELECT cal_date
            FROM trade_calendar tc
            WHERE tc.is_open = 1
              AND tc.cal_date > sr.as_of_date
            ORDER BY tc.cal_date
            LIMIT 1
          ) AS next_trade_date
        FROM latest_runs lr
        JOIN strategy_runs sr ON sr.id = lr.strategy_run_id
        LEFT JOIN daily_picks dp
          ON dp.strategy_run_id = sr.id
         AND dp.review_date = sr.as_of_date
        LEFT JOIN strategy_signals ss ON ss.id = dp.signal_id
        LEFT JOIN trade_plans tp
          ON tp.id = (
            SELECT MAX(tp2.id)
            FROM trade_plans tp2
            WHERE tp2.daily_pick_id = dp.id
              AND tp2.account_id = ?
          )
        LEFT JOIN agent_runs ar
          ON ar.id = (
            SELECT MAX(ar2.id)
            FROM agent_runs ar2
            WHERE ar2.daily_pick_id = dp.id
          )
        LEFT JOIN agent_decisions ad ON ad.agent_run_id = ar.id
        ORDER BY sr.as_of_date DESC, sr.id DESC
        """,
        (
            request.strategy_version,
            request.before_date,
            request.before_date,
            request.limit,
            account_id,
        ),
    ).fetchall()
    return [
        DailyReviewHistoryItem(
            review_date=row["review_date"],
            next_trade_date=row["next_trade_date"],
            strategy_run_id=int(row["strategy_run_id"]),
            review_status=row["review_status"],
            signals_count=int(row["signals_count"]),
            daily_pick_id=_optional_int(row["daily_pick_id"]),
            signal_id=_optional_int(row["signal_id"]),
            ts_code=row["ts_code"],
            name=row["name"],
            score=_optional_float(row["score"]),
            planned_buy_date=row["planned_buy_date"],
            selection_reason=row["selection_reason"],
            trade_plan_id=_optional_int(row["trade_plan_id"]),
            trade_plan_action=row["trade_plan_action"],
            trade_plan_status=row["trade_plan_status"],
            planned_trade_date=row["planned_trade_date"],
            agent_status=row["agent_status"],
            agent_action=row["agent_action"],
            agent_risk_level=row["agent_risk_level"],
            blocker_count=int(row["blocker_count"]),
            warning_count=int(row["warning_count"]),
            created_at=row["created_at"],
        )
        for row in rows
    ]


def _load_acceptance_history_dates(conn: Any, request: PaperAcceptanceHistoryRequest) -> list[str]:
    rows = conn.execute(
        """
        WITH latest_runs AS (
          SELECT MAX(id) AS strategy_run_id
          FROM strategy_runs
          WHERE strategy_version = ?
            AND (? IS NULL OR as_of_date <= ?)
          GROUP BY as_of_date
          ORDER BY as_of_date DESC, MAX(id) DESC
          LIMIT ?
        )
        SELECT sr.as_of_date AS review_date
        FROM latest_runs lr
        JOIN strategy_runs sr ON sr.id = lr.strategy_run_id
        ORDER BY sr.as_of_date DESC, sr.id DESC
        """,
        (
            request.strategy_version,
            request.before_date,
            request.before_date,
            request.limit,
        ),
    ).fetchall()
    return [str(row["review_date"]) for row in rows]


def _load_ops_history_operations(conn: Any, request: OpsHistoryRequest) -> list[OpsHistoryItem]:
    rows = conn.execute(
        """
        SELECT
          id,
          idempotency_key,
          request_id,
          operation_type,
          account_id,
          as_of_date,
          status,
          request_json,
          response_json,
          error_code,
          error_message,
          operator,
          started_at,
          finished_at,
          COALESCE(finished_at, started_at) AS occurred_at
        FROM operation_requests
        WHERE (? IS NULL OR as_of_date IS NULL OR as_of_date <= ?)
        ORDER BY COALESCE(finished_at, started_at) DESC, id DESC
        LIMIT ?
        """,
        (request.before_date, request.before_date, request.limit * 3),
    ).fetchall()

    items: list[OpsHistoryItem] = []
    for row in rows:
        operation_type = str(row["operation_type"])
        idempotency_key = row["idempotency_key"]
        category = _ops_operation_category(operation_type, idempotency_key)
        request_payload = _loads_json_object(row["request_json"])
        response_payload = _loads_json_object(row["response_json"])
        items.append(
            OpsHistoryItem(
                occurred_at=str(row["occurred_at"] or row["started_at"] or ""),
                category=category,
                status=str(row["status"]),
                title=_ops_operation_title(operation_type, idempotency_key),
                summary=_ops_operation_summary(row, request_payload, response_payload),
                as_of_date=row["as_of_date"],
                source="operation_requests",
                operation_id=int(row["id"]),
                operation_type=operation_type,
                idempotency_key=idempotency_key,
                request_id=row["request_id"],
                operator=row["operator"],
                details={
                    "account_id": row["account_id"],
                    "dry_run": _ops_request_dry_run(request_payload),
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                    "error_code": row["error_code"],
                    "error_message": row["error_message"],
                    "response_keys": sorted(response_payload.keys()),
                    "read_only_history": True,
                },
            )
        )
    return items


def _ops_history_acceptance_item(acceptance: DailyAcceptanceReport) -> OpsHistoryItem:
    return OpsHistoryItem(
        occurred_at=acceptance.as_of_date,
        category="paper_acceptance",
        status=acceptance.status,
        title="Paper acceptance snapshot",
        summary=acceptance.summary,
        as_of_date=acceptance.as_of_date,
        source="computed_acceptance_history",
        details={
            "execution_date": acceptance.execution_date,
            "unresolved_blocker_count": len(acceptance.unresolved_blockers),
            "alert_count": len(acceptance.alerts),
            "open_execution_next_action": acceptance.open_execution.next_action,
            "read_only_history": True,
        },
    )


def _load_ops_history_log_items(request: OpsHistoryRequest) -> list[OpsHistoryItem]:
    items: list[OpsHistoryItem] = []
    seen_paths: set[Path] = set()
    for log_dir in _ops_history_log_dirs():
        if not log_dir.exists() or not log_dir.is_dir():
            continue
        for path in sorted(log_dir.glob("*.log")):
            resolved = path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            payload = _parse_ops_log_file(path)
            if not payload:
                continue
            as_of_date = payload.get("resolved_date") or payload.get("review_date") or _date_from_filename(path.name)
            if request.before_date is not None and as_of_date is not None and as_of_date > request.before_date:
                continue
            items.extend(_ops_history_items_from_log(path, payload, as_of_date))
    return items


def _load_ops_history_release_items(request: OpsHistoryRequest) -> list[OpsHistoryItem]:
    release_dir = Path(os.environ.get("PGC_ARTIFACT_DIR", ".pgc-release"))
    if not release_dir.exists() or not release_dir.is_dir():
        return []

    items: list[OpsHistoryItem] = []
    for path in sorted(release_dir.glob("pgc-v*.tar.gz")):
        as_of_date = _date_from_filename(path.name)
        if request.before_date is not None and as_of_date is not None and as_of_date > request.before_date:
            continue
        stat = path.stat()
        release_tag = path.name.removesuffix(".tar.gz")
        items.append(
            OpsHistoryItem(
                occurred_at=_iso_from_timestamp(stat.st_mtime),
                category="release",
                status="artifact",
                title="Release artifact",
                summary=f"{release_tag} is available in {release_dir}.",
                as_of_date=as_of_date,
                source="release_artifact_dir",
                log_file=str(path),
                details={
                    "release_tag": release_tag,
                    "artifact_path": str(path),
                    "size_bytes": stat.st_size,
                    "read_only_history": True,
                },
            )
        )
    return items


def _ops_history_items_from_log(path: Path, payload: dict[str, str], as_of_date: str | None) -> list[OpsHistoryItem]:
    status = payload.get("pipeline_status") or payload.get("activation_decision") or payload.get("action") or "observed"
    category = "timer_evidence" if _is_timer_evidence_log(payload) else "daily_pipeline"
    title = "Timer dry-run evidence" if category == "timer_evidence" else "Daily pipeline log"
    if payload.get("ops_history_event") == "timer_action":
        category = "timer_action"
        title = "Timer action evidence"
    occurred_at = payload.get("ops_history_occurred_at") or _iso_from_timestamp(path.stat().st_mtime)
    summary_parts = [
        f"date={as_of_date or 'unknown'}",
        f"status={status}",
    ]
    if payload.get("duplicate_apply_count") is not None:
        summary_parts.append(f"duplicate_apply_count={payload['duplicate_apply_count']}")
    if payload.get("backup_path") and payload.get("backup_path") != "none":
        summary_parts.append("backup recorded")
    items = [
        OpsHistoryItem(
            occurred_at=occurred_at,
            category=category,
            status=status,
            title=title,
            summary="; ".join(summary_parts),
            as_of_date=as_of_date,
            source="local_log",
            operator=payload.get("operator"),
            log_file=str(path),
            details={
                "evidence_run_id": payload.get("evidence_run_id"),
                "evidence_log_role": payload.get("evidence_log_role"),
                "duplicate_apply_count": payload.get("duplicate_apply_count"),
                "duplicate_write_guard": payload.get("duplicate_write_guard"),
                "backup_path": payload.get("backup_path"),
                "changed": payload.get("changed"),
                "health_url": payload.get("health_url"),
                "health_command": payload.get("health_command"),
                "release_tag": payload.get("release_tag"),
                "read_only_history": True,
            },
        )
    ]
    backup_path = payload.get("backup_path")
    if backup_path and backup_path != "none":
        items.append(
            OpsHistoryItem(
                occurred_at=occurred_at,
                category="backup",
                status="recorded",
                title="Pipeline backup",
                summary=f"Backup captured before apply: {backup_path}",
                as_of_date=as_of_date,
                source="local_log",
                log_file=str(path),
                details={
                    "backup_path": backup_path,
                    "pipeline_status": payload.get("pipeline_status"),
                    "read_only_history": True,
                },
            )
        )
    if payload.get("health_url") or payload.get("health_command"):
        items.append(
            OpsHistoryItem(
                occurred_at=occurred_at,
                category="health",
                status=payload.get("health_status") or "observed",
                title="Remote health evidence",
                summary=payload.get("health_url") or payload.get("health_command") or "Health command was recorded.",
                as_of_date=as_of_date,
                source="local_log",
                log_file=str(path),
                details={
                    "health_url": payload.get("health_url"),
                    "health_command": payload.get("health_command"),
                    "read_only_history": True,
                },
            )
        )
    return items


def _ops_history_log_dirs() -> list[Path]:
    candidates = [
        os.environ.get("PGC_DAILY_PIPELINE_LOG_DIR"),
        os.environ.get("PGC_TIMER_EVIDENCE_DIR"),
        ".pgc-runs",
        ".pgc-runs/timer-evidence",
    ]
    dirs: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        dirs.append(path)
    return dirs


def _parse_ops_log_file(path: Path) -> dict[str, str]:
    payload: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return payload
    for line in lines:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or " " in key:
            continue
        payload[key] = value.strip()
    return payload


def _parse_bool_text(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _ops_request_dry_run(payload: dict[str, Any]) -> bool | None:
    if "dry_run" in payload:
        return _parse_bool_text(payload.get("dry_run"))
    request_payload = payload.get("request")
    if isinstance(request_payload, dict) and "dry_run" in request_payload:
        return _parse_bool_text(request_payload.get("dry_run"))
    return None


def _ops_operation_category(operation_type: str, idempotency_key: str | None) -> str:
    if operation_type == "ops_backup":
        return "backup"
    if operation_type == "ops_health":
        return "health"
    if operation_type == "ops_release":
        return "release"
    if idempotency_key and idempotency_key.startswith("daily-pipeline:"):
        return "pipeline_step"
    return "operation"


def _ops_operation_title(operation_type: str, idempotency_key: str | None) -> str:
    if idempotency_key and idempotency_key.startswith("daily-pipeline:"):
        step = idempotency_key.split(":")[-1]
        return f"Daily pipeline step: {step}"
    return operation_type.replace("_", " ")


def _ops_operation_summary(row: Any, request_payload: dict[str, Any], response_payload: dict[str, Any]) -> str:
    dry_run = _ops_request_dry_run(request_payload)
    mode = "dry-run" if dry_run is True else "apply" if dry_run is False else "unknown mode"
    status = row["status"]
    as_of_date = row["as_of_date"] or "no date"
    error = row["error_code"] or row["error_message"]
    if error:
        return f"{row['operation_type']} {mode} for {as_of_date} ended {status}: {error}"
    response_status = response_payload.get("status") or response_payload.get("pipeline_status")
    if response_status:
        return f"{row['operation_type']} {mode} for {as_of_date} ended {status}; response={response_status}."
    return f"{row['operation_type']} {mode} for {as_of_date} ended {status}."


def _is_timer_evidence_log(payload: dict[str, str]) -> bool:
    return payload.get("evidence_log_role") == "dry_run_activation_evidence" or bool(payload.get("evidence_run_id"))


def _date_from_filename(name: str) -> str | None:
    match = re.search(r"(20\d{6})", name)
    return match.group(1) if match else None


def _iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


def _dedupe_ops_history_items(items: list[OpsHistoryItem]) -> list[OpsHistoryItem]:
    deduped: list[OpsHistoryItem] = []
    seen: set[tuple[Any, ...]] = set()
    for item in items:
        key = (
            item.category,
            item.operation_id,
            item.log_file,
            item.as_of_date,
            item.title,
            item.summary,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _ops_history_sort_key(item: OpsHistoryItem) -> str:
    return item.occurred_at or item.as_of_date or ""


def _ops_history_counts(items: list[OpsHistoryItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.category] = counts.get(item.category, 0) + 1
    return counts


def _ops_history_summary(items: list[OpsHistoryItem], counts: dict[str, int]) -> str:
    if not items:
        return "暂无 ops run history；该视图只读，不会主动运行远端命令。"
    parts = [
        f"{label} {counts[key]}"
        for key, label in [
            ("daily_pipeline", "pipeline log"),
            ("pipeline_step", "pipeline step"),
            ("backup", "backup"),
            ("health", "health"),
            ("release", "release"),
            ("paper_acceptance", "paper acceptance"),
            ("timer_evidence", "timer evidence"),
            ("timer_action", "timer action"),
        ]
        if counts.get(key)
    ]
    return f"Ops history 共 {len(items)} 条；" + " / ".join(parts) + "。"


def _load_review_timeline(
    conn: Any,
    request: ReviewTimelineRequest,
    account_id: int | None,
) -> list[ReviewTimelineItem]:
    rows = conn.execute(
        """
        WITH latest_runs AS (
          SELECT MAX(id) AS strategy_run_id
          FROM strategy_runs
          WHERE strategy_version = ?
            AND (? IS NULL OR as_of_date <= ?)
          GROUP BY as_of_date
          ORDER BY as_of_date DESC, MAX(id) DESC
          LIMIT ?
        )
        SELECT
          sr.id AS strategy_run_id,
          sr.as_of_date AS review_date,
          sr.status AS review_status,
          sr.created_at,
          dp.id AS daily_pick_id,
          dp.planned_buy_date,
          dp.score,
          ss.ts_code,
          ss.name,
          tp.id AS trade_plan_id,
          tp.action AS trade_plan_action,
          tp.status AS trade_plan_status,
          tp.planned_trade_date,
          mrr.id AS market_review_run_id,
          mrs.regime AS market_regime,
          mrs.summary AS market_regime_summary,
          mrs.breadth_score AS market_breadth_score,
          mrs.trend_score AS market_trend_score,
          mrs.volume_score AS market_volume_score,
          mrs.persistence_score AS market_persistence_score,
          mpc.alignment AS plan_context_alignment,
          mpc.risk_level AS plan_context_risk_level,
          mpc.management_action AS plan_context_management_action,
          mpc.rationale AS plan_context_rationale,
          (
            SELECT COUNT(*)
            FROM data_quality_events dqe
            WHERE dqe.trade_date = sr.as_of_date
              AND dqe.status = 'open'
              AND dqe.severity = 'blocker'
          ) AS blocker_count,
          (
            SELECT COUNT(*)
            FROM data_quality_events dqe
            WHERE dqe.trade_date = sr.as_of_date
              AND dqe.status = 'open'
              AND dqe.severity = 'warning'
          ) AS warning_count,
          (
            SELECT cal_date
            FROM trade_calendar tc
            WHERE tc.is_open = 1
              AND tc.cal_date > sr.as_of_date
            ORDER BY tc.cal_date
            LIMIT 1
          ) AS next_trade_date
        FROM latest_runs lr
        JOIN strategy_runs sr ON sr.id = lr.strategy_run_id
        LEFT JOIN daily_picks dp
          ON dp.strategy_run_id = sr.id
         AND dp.review_date = sr.as_of_date
        LEFT JOIN strategy_signals ss ON ss.id = dp.signal_id
        LEFT JOIN trade_plans tp
          ON tp.id = (
            SELECT MAX(tp2.id)
            FROM trade_plans tp2
            WHERE tp2.daily_pick_id = dp.id
              AND tp2.account_id = ?
          )
        LEFT JOIN market_review_runs mrr
          ON mrr.id = (
            SELECT MAX(mrr2.id)
            FROM market_review_runs mrr2
            WHERE mrr2.as_of_date = sr.as_of_date
          )
        LEFT JOIN market_regime_snapshots mrs
          ON mrs.id = (
            SELECT MAX(mrs2.id)
            FROM market_regime_snapshots mrs2
            WHERE mrs2.market_review_run_id = mrr.id
          )
        LEFT JOIN market_plan_contexts mpc
          ON mpc.id = (
            SELECT MAX(mpc2.id)
            FROM market_plan_contexts mpc2
            WHERE mpc2.trade_plan_id = tp.id
              AND mpc2.market_review_run_id = mrr.id
          )
        ORDER BY sr.as_of_date DESC, sr.id DESC
        """,
        (
            request.strategy_version,
            request.before_date,
            request.before_date,
            request.limit,
            account_id,
        ),
    ).fetchall()

    items: list[ReviewTimelineItem] = []
    for row in rows:
        execution = _load_timeline_execution_state(conn, account_id, row["next_trade_date"])
        items.append(
            ReviewTimelineItem(
                review_date=row["review_date"],
                next_trade_date=row["next_trade_date"],
                strategy_run_id=int(row["strategy_run_id"]),
                review_status=row["review_status"],
                daily_pick_id=_optional_int(row["daily_pick_id"]),
                ts_code=row["ts_code"],
                name=row["name"],
                score=_optional_float(row["score"]),
                trade_plan_id=_optional_int(row["trade_plan_id"]),
                trade_plan_action=row["trade_plan_action"],
                trade_plan_status=row["trade_plan_status"],
                planned_trade_date=row["planned_trade_date"],
                market_review_run_id=_optional_int(row["market_review_run_id"]),
                market_regime=row["market_regime"],
                market_regime_summary=row["market_regime_summary"],
                market_breadth_score=_optional_float(row["market_breadth_score"]),
                market_trend_score=_optional_float(row["market_trend_score"]),
                market_volume_score=_optional_float(row["market_volume_score"]),
                market_persistence_score=_optional_float(row["market_persistence_score"]),
                plan_context_alignment=row["plan_context_alignment"],
                plan_context_risk_level=row["plan_context_risk_level"],
                plan_context_management_action=row["plan_context_management_action"],
                plan_context_rationale=row["plan_context_rationale"],
                open_execution_as_of_date=execution["as_of_date"],
                open_execution_status=execution["status"],
                open_execution_next_action=execution["next_action"],
                open_execution_primary_plan_id=execution["primary_plan_id"],
                open_execution_primary_position_id=execution["primary_position_id"],
                open_execution_target_stock=execution["target_stock"],
                open_execution_target_name=execution["target_name"],
                blocker_count=int(row["blocker_count"]),
                warning_count=int(row["warning_count"]),
                created_at=row["created_at"],
            )
        )
    return items


def _load_timeline_execution_state(
    conn: Any,
    account_id: int | None,
    as_of_date: str | None,
) -> dict[str, Any]:
    if account_id is None:
        return _timeline_execution_payload(as_of_date, "unavailable", "account_missing")
    if as_of_date is None:
        return _timeline_execution_payload(None, "unavailable", "next_trade_date_missing")

    sell_plan = _load_timeline_due_active_plan(conn, account_id, as_of_date, SELL_PLAN_ACTIONS)
    if sell_plan is not None:
        return _timeline_execution_from_plan(as_of_date, sell_plan, "ready", "record_sell")

    buy_plan = _load_timeline_due_active_plan(conn, account_id, as_of_date, {BUY_PLAN_ACTION})
    if buy_plan is not None:
        return _timeline_execution_from_plan(as_of_date, buy_plan, "ready", "record_buy")

    due_position = _load_timeline_due_position(conn, account_id, as_of_date)
    if due_position is not None:
        return _timeline_execution_from_position(as_of_date, due_position, "ready", "evaluate_exit")

    future_plan = _load_timeline_future_active_plan(conn, account_id, as_of_date)
    if future_plan is not None:
        return _timeline_execution_from_plan(as_of_date, future_plan, "waiting", "wait")

    return _timeline_execution_payload(as_of_date, "idle", "none")


def _load_timeline_due_active_plan(
    conn: Any,
    account_id: int,
    as_of_date: str,
    actions: set[str],
) -> Any | None:
    placeholders = ", ".join("?" for _ in actions)
    return conn.execute(
        f"""
        SELECT *
        FROM trade_plans
        WHERE account_id = ?
          AND status = 'active'
          AND action IN ({placeholders})
          AND planned_trade_date = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        (account_id, *sorted(actions), as_of_date),
    ).fetchone()


def _load_timeline_future_active_plan(conn: Any, account_id: int, as_of_date: str) -> Any | None:
    return conn.execute(
        """
        SELECT *
        FROM trade_plans
        WHERE account_id = ?
          AND status = 'active'
          AND planned_trade_date > ?
        ORDER BY planned_trade_date ASC, id ASC
        LIMIT 1
        """,
        (account_id, as_of_date),
    ).fetchone()


def _load_timeline_due_position(conn: Any, account_id: int, as_of_date: str) -> Any | None:
    status_values = tuple(sorted(OPEN_POSITION_STATUSES))
    placeholders = ", ".join("?" for _ in status_values)
    return conn.execute(
        f"""
        SELECT *
        FROM positions
        WHERE account_id = ?
          AND status IN ({placeholders})
          AND (
            (
              status IN ('open', 'waiting_t2', 'need_t2_decision')
              AND planned_t2_date IS NOT NULL
              AND planned_t2_date <= ?
            )
            OR (
              status IN ('holding_to_t5', 'need_t5_exit')
              AND planned_t5_date IS NOT NULL
              AND planned_t5_date <= ?
            )
          )
        ORDER BY
          CASE
            WHEN status IN ('need_t5_exit', 'holding_to_t5') THEN 0
            ELSE 1
          END,
          id ASC
        LIMIT 1
        """,
        (account_id, *status_values, as_of_date, as_of_date),
    ).fetchone()


def _timeline_execution_from_plan(
    as_of_date: str,
    row: Any,
    status: str,
    next_action: str,
) -> dict[str, Any]:
    payload = _loads_json_object(row["plan_json"])
    return _timeline_execution_payload(
        as_of_date,
        status,
        next_action,
        primary_plan_id=int(row["id"]),
        primary_position_id=_optional_int_from_any(payload.get("position_id")),
        target_stock=_optional_text_value(payload.get("ts_code")),
        target_name=_optional_text_value(payload.get("name")),
    )


def _timeline_execution_from_position(
    as_of_date: str,
    row: Any,
    status: str,
    next_action: str,
) -> dict[str, Any]:
    return _timeline_execution_payload(
        as_of_date,
        status,
        next_action,
        primary_position_id=int(row["id"]),
        target_stock=row["ts_code"],
        target_name=row["name"],
    )


def _timeline_execution_payload(
    as_of_date: str | None,
    status: str,
    next_action: str,
    *,
    primary_plan_id: int | None = None,
    primary_position_id: int | None = None,
    target_stock: str | None = None,
    target_name: str | None = None,
) -> dict[str, Any]:
    return {
        "as_of_date": as_of_date,
        "status": status,
        "next_action": next_action,
        "primary_plan_id": primary_plan_id,
        "primary_position_id": primary_position_id,
        "target_stock": target_stock,
        "target_name": target_name,
    }


def _load_buy_plan(
    conn: Any,
    candidate: CandidateReport | None,
    account: AccountReport,
) -> BuyPlanReport | None:
    if candidate is None or account.account_id is None:
        return None
    row = conn.execute(
        """
        SELECT
          id,
          action,
          status,
          reason,
          planned_trade_date,
          planned_buy_date,
          plan_json
        FROM trade_plans
        WHERE account_id = ?
          AND daily_pick_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (account.account_id, candidate.daily_pick_id),
    ).fetchone()
    if row is None:
        return None
    payload = _loads_json_object(row["plan_json"])
    return BuyPlanReport(
        trade_plan_id=int(row["id"]),
        action=row["action"],
        status=row["status"],
        reason=row["reason"],
        planned_trade_date=row["planned_trade_date"],
        planned_buy_date=row["planned_buy_date"],
        planned_cash=_optional_float(payload.get("planned_cash")),
        planned_shares=_optional_int(payload.get("planned_shares")),
        free_position_slots=_optional_int(payload.get("free_position_slots")),
        price_reference=_optional_float(payload.get("price_reference")),
        price_reference_date=payload.get("price_reference_date"),
    )


def _load_market_review(conn: Any, as_of_date: str) -> MarketReviewReport | None:
    row = conn.execute(
        """
        SELECT
          mrr.id AS market_review_run_id,
          mrr.status,
          mrs.regime,
          mrs.breadth_score,
          mrs.trend_score,
          mrs.volume_score,
          mrs.sentiment_score,
          mrs.persistence_score,
          mrs.summary
        FROM market_review_runs mrr
        LEFT JOIN market_regime_snapshots mrs ON mrs.market_review_run_id = mrr.id
        WHERE mrr.as_of_date = ?
        ORDER BY mrr.id DESC
        LIMIT 1
        """,
        (as_of_date,),
    ).fetchone()
    if row is None:
        return None
    run_id = int(row["market_review_run_id"])
    return MarketReviewReport(
        market_review_run_id=run_id,
        status=row["status"],
        regime=row["regime"] or "unknown",
        summary=row["summary"] or "",
        breadth_score=_optional_float(row["breadth_score"]),
        trend_score=_optional_float(row["trend_score"]),
        volume_score=_optional_float(row["volume_score"]),
        sentiment_score=_optional_float(row["sentiment_score"]),
        persistence_score=_optional_float(row["persistence_score"]),
        top_sectors=_load_market_review_top_sectors(conn, run_id),
        sector_persistence=_load_market_review_sector_persistence(conn, run_id),
        external_evidence_coverage=_load_market_external_evidence_coverage(conn, as_of_date),
        strategy_hypotheses=_load_strategy_hypothesis_summaries(conn, as_of_date),
    )


def _load_market_review_top_sectors(conn: Any, market_review_run_id: int) -> list[MarketSectorReport]:
    rows = conn.execute(
        """
        SELECT
          sector_code,
          sector_name,
          rank_overall,
          persistence_score,
          breadth_score,
          volume_score,
          leader_count,
          return_1d,
          return_3d
        FROM sector_daily_snapshots
        WHERE market_review_run_id = ?
        ORDER BY rank_overall IS NULL, rank_overall, persistence_score DESC, sector_code
        LIMIT 5
        """,
        (market_review_run_id,),
    ).fetchall()
    return [_market_sector_report(row) for row in rows]


def _load_market_review_sector_persistence(conn: Any, market_review_run_id: int) -> list[MarketSectorReport]:
    rows = conn.execute(
        """
        SELECT
          sector_code,
          sector_name,
          rank_overall,
          persistence_score,
          breadth_score,
          volume_score,
          leader_count,
          return_1d,
          return_3d
        FROM sector_daily_snapshots
        WHERE market_review_run_id = ?
          AND persistence_score IS NOT NULL
        ORDER BY persistence_score DESC, rank_overall IS NULL, rank_overall, sector_code
        LIMIT 5
        """,
        (market_review_run_id,),
    ).fetchall()
    return [_market_sector_report(row) for row in rows]


def _market_sector_report(row: Any) -> MarketSectorReport:
    return MarketSectorReport(
        sector_code=row["sector_code"],
        sector_name=row["sector_name"],
        rank_overall=_optional_int(row["rank_overall"]),
        persistence_score=_optional_float(row["persistence_score"]),
        breadth_score=_optional_float(row["breadth_score"]),
        volume_score=_optional_float(row["volume_score"]),
        leader_count=int(row["leader_count"] or 0),
        return_1d=_optional_float(row["return_1d"]),
        return_3d=_optional_float(row["return_3d"]),
    )


def _load_market_external_evidence_coverage(conn: Any, as_of_date: str) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT scope_type, item_type, sentiment, importance, provider, published_date, COUNT(*) AS count
        FROM market_external_items
        WHERE as_of_date = ?
        GROUP BY scope_type, item_type, sentiment, importance, provider, published_date
        ORDER BY scope_type, item_type, sentiment, importance, provider, published_date
        """,
        (as_of_date,),
    ).fetchall()
    total_count = 0
    by_scope: dict[str, int] = {}
    by_item_type: dict[str, int] = {}
    by_sentiment: dict[str, int] = {}
    by_importance: dict[str, int] = {}
    by_provider: dict[str, int] = {}
    fresh_count = 0
    stale_count = 0
    for row in rows:
        count = int(row["count"] or 0)
        total_count += count
        _increment_count(by_scope, row["scope_type"], count)
        _increment_count(by_item_type, row["item_type"], count)
        _increment_count(by_sentiment, row["sentiment"], count)
        _increment_count(by_importance, row["importance"], count)
        _increment_count(by_provider, row["provider"], count)
        if row["published_date"] == as_of_date:
            fresh_count += count
        elif str(row["published_date"] or "") < as_of_date:
            stale_count += count
    known_sentiment_count = sum(count for sentiment, count in by_sentiment.items() if sentiment != "unknown")
    if total_count == 0:
        sentiment_status = "missing"
    elif known_sentiment_count == 0:
        sentiment_status = "missing"
    elif known_sentiment_count == total_count:
        sentiment_status = "available"
    else:
        sentiment_status = "partial"
    scope_status = {
        "market": "available" if by_scope.get("market", 0) else "missing",
        "sector": "partial" if by_scope.get("sector", 0) else "missing",
        "stock": "partial" if by_scope.get("stock", 0) else "missing",
    }
    news_like_types = {"news", "announcement", "policy", "risk_note", "research_note"}
    return {
        "total_count": total_count,
        "coverage": "available" if total_count else "missing",
        **scope_status,
        "news": "available" if any(by_item_type.get(item_type, 0) for item_type in news_like_types) else "missing",
        "sentiment": sentiment_status,
        "missing_scopes": [scope for scope, status in scope_status.items() if status == "missing"],
        "fresh_count": fresh_count,
        "stale_count": stale_count,
        "by_scope": by_scope,
        "by_item_type": by_item_type,
        "by_sentiment": by_sentiment,
        "by_importance": by_importance,
        "by_provider": by_provider,
    }


def _increment_count(target: dict[str, int], key: object, count: int) -> None:
    label = str(key or "unknown")
    target[label] = target.get(label, 0) + count


def _load_strategy_hypothesis_summaries(conn: Any, as_of_date: str) -> list[StrategyHypothesisSummaryReport]:
    rows = conn.execute(
        """
        SELECT id, hypothesis_type, title, status, rationale
        FROM strategy_hypotheses
        WHERE as_of_date = ?
        ORDER BY id
        LIMIT 5
        """,
        (as_of_date,),
    ).fetchall()
    return [
        StrategyHypothesisSummaryReport(
            hypothesis_id=int(row["id"]),
            hypothesis_type=row["hypothesis_type"],
            title=row["title"],
            status=row["status"],
            rationale=row["rationale"],
        )
        for row in rows
    ]


def _load_next_day_strategy_proposals(conn: Any, as_of_date: str) -> NextDayStrategyProposalSummary:
    count_rows = conn.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM strategy_hypotheses
        WHERE as_of_date = ?
        GROUP BY status
        """,
        (as_of_date,),
    ).fetchall()
    counts = {key: 0 for key in ("proposed", "testing", "accepted", "rejected", "archived")}
    for row in count_rows:
        status = str(row["status"])
        if status in counts:
            counts[status] = int(row["count"] or 0)

    rows = conn.execute(
        """
        SELECT id, hypothesis_type, title, status, rationale
        FROM strategy_hypotheses
        WHERE as_of_date = ?
        ORDER BY
          CASE status
            WHEN 'accepted' THEN 1
            WHEN 'testing' THEN 2
            WHEN 'proposed' THEN 3
            WHEN 'rejected' THEN 4
            ELSE 9
          END,
          id
        LIMIT 20
        """,
        (as_of_date,),
    ).fetchall()
    items: list[StrategyHypothesisSummaryReport] = []
    for row in rows:
        status = str(row["status"])
        items.append(
            StrategyHypothesisSummaryReport(
                hypothesis_id=int(row["id"]),
                hypothesis_type=row["hypothesis_type"],
                title=row["title"],
                status=status,
                rationale=row["rationale"],
            )
        )
    review_required_count = counts["proposed"] + counts["testing"] + counts["accepted"]
    return NextDayStrategyProposalSummary(
        total_count=sum(counts.values()),
        proposed_count=counts["proposed"],
        testing_count=counts["testing"],
        accepted_count=counts["accepted"],
        rejected_count=counts["rejected"],
        archived_count=counts["archived"],
        review_required_count=review_required_count,
        items=items,
    )


def _load_market_plan_context(
    conn: Any,
    buy_plan: BuyPlanReport | None,
    as_of_date: str,
) -> MarketPlanContextReport | None:
    if buy_plan is None:
        return None
    row = conn.execute(
        """
        SELECT
          mpc.market_review_run_id,
          mpc.trade_plan_id,
          mpc.alignment,
          mpc.risk_level,
          mpc.management_action,
          mpc.rationale,
          mpc.evidence_json
        FROM market_plan_contexts mpc
        JOIN market_review_runs mrr ON mrr.id = mpc.market_review_run_id
        WHERE mpc.trade_plan_id = ?
          AND mrr.as_of_date = ?
        ORDER BY mpc.id DESC
        LIMIT 1
        """,
        (buy_plan.trade_plan_id, as_of_date),
    ).fetchone()
    if row is None:
        return None
    return MarketPlanContextReport(
        market_review_run_id=int(row["market_review_run_id"]),
        trade_plan_id=int(row["trade_plan_id"]),
        alignment=row["alignment"],
        risk_level=row["risk_level"],
        management_action=row["management_action"],
        rationale=row["rationale"],
        evidence=_loads_json_object(row["evidence_json"]),
    )


def _load_agent_advice(conn: Any, candidate: CandidateReport | None) -> AgentAdviceReport:
    placeholder = AgentAdviceReport(
        agent_run_id=None,
        agent_decision_id=None,
        status="not_run",
        action="no_opinion",
        risk_level="unknown",
        confidence=None,
        summary=None,
        note="Agent 复核尚未接入本次日报；确定性策略和人工检查优先。",
    )
    if candidate is None:
        return placeholder
    row = conn.execute(
        """
        SELECT
          ar.id AS agent_run_id,
          ar.status,
          ar.error_message,
          ad.id AS agent_decision_id,
          ad.action,
          ad.risk_level,
          ad.confidence,
          ad.summary,
          ad.supporting_points_json,
          ad.risk_points_json,
          ad.raw_decision_json,
          ins.source_refs_json,
          ins.payload_json
        FROM agent_runs ar
        LEFT JOIN agent_decisions ad ON ad.agent_run_id = ar.id
        LEFT JOIN input_snapshots ins ON ins.id = ar.input_snapshot_id
        WHERE ar.daily_pick_id = ?
        ORDER BY ar.id DESC
        LIMIT 1
        """,
        (candidate.daily_pick_id,),
    ).fetchone()
    if row is None:
        return placeholder
    status = row["status"]
    raw_decision = _loads_json_object(row["raw_decision_json"])
    payload = _loads_json_object(row["payload_json"])
    supporting_points = _loads_json_list(row["supporting_points_json"])
    if not supporting_points:
        supporting_points = _string_list(raw_decision.get("supporting_points"))
    risk_points = _loads_json_list(row["risk_points_json"])
    if not risk_points:
        risk_points = _string_list(raw_decision.get("risk_points"))
    source_refs = _loads_json_list(row["source_refs_json"])
    external_data_coverage = _load_agent_external_data_coverage(payload, raw_decision)
    external_evidence = _load_agent_external_evidence(payload)
    missing_data_warnings = _load_agent_missing_data_warnings(payload, raw_decision, external_data_coverage)
    analyst_reports = _load_agent_analyst_reports(raw_decision.get("analyst_reports"))
    execution_source = raw_decision.get("execution_source")
    if not isinstance(execution_source, dict):
        execution_source = {}
    execution_mode = _optional_text_value(execution_source.get("mode"))
    source_label = _optional_text_value(execution_source.get("source_label")) or _agent_source_label(execution_mode)
    report_sections = _load_agent_report_sections(raw_decision.get("report_sections"), source_label)
    artifacts, final_report_path = _load_agent_artifacts(conn, int(row["agent_run_id"]))
    return AgentAdviceReport(
        agent_run_id=int(row["agent_run_id"]),
        agent_decision_id=_optional_int(row["agent_decision_id"]),
        status=status,
        action=row["action"] or "no_opinion",
        risk_level=row["risk_level"] or "unknown",
        confidence=_optional_float(row["confidence"]),
        summary=row["summary"] or row["error_message"],
        note="Agent 复核失败，需人工复核。" if status == "failed" else "Agent 复核仅作参考。",
        execution_mode=execution_mode,
        source_label=source_label,
        supporting_points=supporting_points,
        risk_points=risk_points,
        source_refs=source_refs,
        external_data_coverage=external_data_coverage,
        external_evidence=external_evidence,
        missing_data_warnings=missing_data_warnings,
        analyst_reports=analyst_reports,
        report_sections=report_sections,
        artifacts=artifacts,
        report_markdown=_load_agent_report_markdown(final_report_path),
    )


def _load_agent_external_data_coverage(payload: dict[str, Any], raw_decision: dict[str, Any]) -> dict[str, str]:
    raw_coverage = payload.get("external_data_coverage")
    if not isinstance(raw_coverage, dict):
        candidate = payload.get("candidate")
        raw_coverage = candidate.get("external_data_coverage") if isinstance(candidate, dict) else None
    if not isinstance(raw_coverage, dict):
        raw_coverage = raw_decision.get("external_data_coverage")
    if not isinstance(raw_coverage, dict):
        return {}
    coverage: dict[str, str] = {}
    for key in ("fundamental", "news", "sentiment", "technical", "sector"):
        status = str(raw_coverage.get(key) or "").strip().lower()
        if status in {"available", "partial", "unavailable", "missing"}:
            coverage[key] = status
    return coverage


def _load_agent_external_evidence(payload: dict[str, Any]) -> list[AgentExternalEvidenceReport]:
    candidate = payload.get("candidate")
    if not isinstance(candidate, dict):
        return []
    evidence: list[AgentExternalEvidenceReport] = []
    external_data = candidate.get("external_data")
    external_items = _external_items_from_snapshot(external_data)
    for item in external_items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        category = str(item.get("item_type") or "external")
        source = str(item.get("provider") or item.get("source") or "unknown")
        evidence.append(
            AgentExternalEvidenceReport(
                source_ref=f"agent_external_items:{item_id}" if item_id is not None else f"{source}:{category}",
                source=source,
                category=category,
                published_date=_optional_text_value(item.get("published_date")),
                title=str(item.get("title") or "外部证据"),
                summary=str(item.get("summary") or ""),
                sentiment=_optional_text_value(item.get("sentiment")),
                importance=_optional_text_value(item.get("importance")),
            )
        )
    evidence.extend(_technical_evidence_from_snapshot(candidate))
    evidence.extend(_sector_evidence_from_snapshot(candidate))
    return evidence[:24]


def _external_items_from_snapshot(external_data: Any) -> list[Any]:
    if not isinstance(external_data, dict):
        return []
    items_section = external_data.get("items")
    if not isinstance(items_section, dict):
        return []
    items = items_section.get("items")
    return items if isinstance(items, list) else []


def _technical_evidence_from_snapshot(candidate: dict[str, Any]) -> list[AgentExternalEvidenceReport]:
    analysis_contexts = candidate.get("analysis_contexts")
    technical = analysis_contexts.get("technical") if isinstance(analysis_contexts, dict) else None
    diagnostics = technical.get("external_market_diagnostics") if isinstance(technical, dict) else None
    if not isinstance(diagnostics, dict):
        external_data = candidate.get("external_data")
        diagnostics = external_data.get("market_diagnostics") if isinstance(external_data, dict) else None
    if not isinstance(diagnostics, dict):
        return []
    ts_code = str(candidate.get("ts_code") or "")
    rows: list[AgentExternalEvidenceReport] = []
    providers = diagnostics.get("providers")
    if not isinstance(providers, list):
        return rows
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        provider_name = str(provider.get("provider") or "unknown")
        last_trade_date = _optional_text_value(provider.get("last_trade_date"))
        summary_parts = []
        if provider.get("last_close") is not None:
            summary_parts.append(f"last_close={provider.get('last_close')}")
        if provider.get("recent_5d_ret") is not None:
            summary_parts.append(f"recent_5d_ret={provider.get('recent_5d_ret')}")
        if provider.get("recent_10d_ret") is not None:
            summary_parts.append(f"recent_10d_ret={provider.get('recent_10d_ret')}")
        rows.append(
            AgentExternalEvidenceReport(
                source_ref=f"market_diagnostic_bars:{provider_name}:{ts_code}:{last_trade_date}",
                source=provider_name,
                category="technical",
                published_date=last_trade_date,
                title="诊断行情缓存",
                summary="；".join(summary_parts) if summary_parts else "诊断行情缓存已接入。",
                sentiment=None,
                importance=None,
            )
        )
    return rows


def _sector_evidence_from_snapshot(candidate: dict[str, Any]) -> list[AgentExternalEvidenceReport]:
    analysis_contexts = candidate.get("analysis_contexts")
    sector = analysis_contexts.get("sector") if isinstance(analysis_contexts, dict) else None
    if not isinstance(sector, dict):
        external_data = candidate.get("external_data")
        sector = external_data.get("sector_context") if isinstance(external_data, dict) else None
    if not isinstance(sector, dict) or sector.get("status") != "available":
        return []
    sector_code = str(sector.get("sector_code") or "unknown")
    as_of_date = _optional_text_value(sector.get("as_of_date"))
    summary_parts = [
        f"sector={sector.get('sector_name') or sector_code}",
        f"rank_overall={sector.get('rank_overall')}",
        f"rank_in_sector={sector.get('rank_in_sector')}",
        f"role={sector.get('role')}",
    ]
    return [
        AgentExternalEvidenceReport(
            source_ref=f"sector_constituents:{sector_code}:{as_of_date}",
            source=str(sector.get("provider") or "market_review"),
            category="sector",
            published_date=as_of_date,
            title="板块位置缓存",
            summary="；".join(part for part in summary_parts if not part.endswith("=None")),
            sentiment=None,
            importance=None,
        )
    ]


def _load_agent_missing_data_warnings(
    payload: dict[str, Any],
    raw_decision: dict[str, Any],
    external_data_coverage: dict[str, str],
) -> list[str]:
    candidate = payload.get("candidate")
    evidence_context = candidate.get("evidence_context") if isinstance(candidate, dict) else None
    if isinstance(evidence_context, dict):
        warnings = _string_list(evidence_context.get("missing_data_warnings"))
        if warnings:
            return warnings
    warnings = _string_list(raw_decision.get("missing_data_warnings"))
    if warnings:
        return warnings
    labels = {
        "technical": "技术面",
        "fundamental": "基本面",
        "news": "新闻/公告",
        "sentiment": "情绪面",
        "sector": "板块位置",
    }
    return [
        f"{labels[key]}未接入/数据不足。"
        for key, status in external_data_coverage.items()
        if status in {"unavailable", "missing"}
    ]


def _load_agent_analyst_reports(value: Any) -> list[AgentAnalystReport]:
    if not isinstance(value, dict):
        return []
    reports: list[AgentAnalystReport] = []
    for key, name in (
        ("fundamental", "基本面"),
        ("news", "新闻"),
        ("sentiment", "情绪"),
        ("technical", "技术/量价"),
        ("sector", "板块位置"),
    ):
        payload = value.get(key)
        if not isinstance(payload, dict):
            continue
        reports.append(
            AgentAnalystReport(
                analyst_key=key,
                analyst_name=name,
                status=str(payload.get("status") or "partial"),
                summary=str(payload.get("summary") or "该分析维度没有返回摘要。"),
                supporting_points=_string_list(payload.get("supporting_points")),
                risk_points=_string_list(payload.get("risk_points")),
            )
        )
    return reports


def _load_agent_report_sections(value: Any, source_label: str) -> list[AgentReportSection]:
    if not isinstance(value, dict):
        return []
    sections: list[AgentReportSection] = []
    for key, name in (
        ("fundamental", "基本面"),
        ("news", "新闻"),
        ("sentiment", "情绪"),
        ("technical", "技术/量价"),
        ("sector", "板块位置"),
        ("risk", "风险"),
        ("conclusion", "结论"),
    ):
        payload = value.get(key)
        if not isinstance(payload, dict):
            continue
        sections.append(
            AgentReportSection(
                section_key=key,
                section_name=str(payload.get("section_name") or name),
                status=str(payload.get("status") or "partial"),
                source_label=str(payload.get("source_label") or source_label),
                source_refs=_string_list(payload.get("source_refs")),
                summary=str(payload.get("summary") or "该结构化段落没有返回摘要。"),
                supporting_points=_string_list(payload.get("supporting_points")),
                risk_points=_string_list(payload.get("risk_points")),
            )
        )
    return sections


def _load_agent_artifacts(conn: Any, agent_run_id: int) -> tuple[list[AgentArtifactReport], str | None]:
    rows = conn.execute(
        """
        SELECT id, artifact_type, path, content_hash
        FROM agent_artifacts
        WHERE agent_run_id = ?
        ORDER BY
          CASE artifact_type
            WHEN 'decision_json' THEN 1
            WHEN 'raw_state' THEN 2
            WHEN 'final_report' THEN 3
            ELSE 9
          END,
          id
        """,
        (agent_run_id,),
    ).fetchall()
    artifacts = [
        AgentArtifactReport(
            artifact_id=int(row["id"]),
            artifact_type=row["artifact_type"],
            content_hash=row["content_hash"],
        )
        for row in rows
    ]
    final_report_path = next((row["path"] for row in rows if row["artifact_type"] == "final_report"), None)
    return artifacts, final_report_path


def _load_agent_report_markdown(final_report_path: str | None) -> str | None:
    if not final_report_path:
        return None
    path = Path(final_report_path)
    try:
        if not path.is_file() or path.stat().st_size > 64_000:
            return None
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _load_positions(conn: Any, as_of_date: str, account_id: int | None) -> list[PositionReport]:
    if account_id is None:
        return []
    rows = conn.execute(
        """
        SELECT
          p.id,
          p.ts_code,
          p.name,
          p.buy_date,
          p.buy_price,
          p.shares,
          p.status,
          p.planned_t2_date,
          p.planned_t5_date,
          mb.trade_date AS latest_trade_date,
          mb.close AS latest_close
        FROM positions p
        LEFT JOIN market_bars mb
          ON mb.ts_code = p.ts_code
         AND mb.trade_date = (
            SELECT MAX(mb2.trade_date)
            FROM market_bars mb2
            WHERE mb2.ts_code = p.ts_code
              AND mb2.trade_date <= ?
         )
        WHERE p.account_id = ?
          AND p.status NOT IN ('closed', 'cancelled')
        ORDER BY p.buy_date, p.id
        """,
        (as_of_date, account_id),
    ).fetchall()
    return [
        PositionReport(
            position_id=int(row["id"]),
            ts_code=row["ts_code"],
            name=row["name"],
            buy_date=row["buy_date"],
            buy_price=float(row["buy_price"]),
            shares=int(row["shares"]),
            status=row["status"],
            planned_t2_date=row["planned_t2_date"],
            planned_t5_date=row["planned_t5_date"],
            latest_trade_date=row["latest_trade_date"],
            latest_close=_optional_float(row["latest_close"]),
            action_due=_position_action_due(row, as_of_date),
        )
        for row in rows
    ]


def _no_candidate_reason(
    conn: Any,
    request: DailyReportRequest,
    candidate: CandidateReport | None,
) -> str | None:
    if candidate is not None:
        return None
    row = conn.execute(
        """
        SELECT sr.id, COUNT(ss.id) AS signal_count
        FROM strategy_runs sr
        LEFT JOIN strategy_signals ss ON ss.strategy_run_id = sr.id
        WHERE sr.as_of_date = ?
          AND sr.strategy_version = ?
        GROUP BY sr.id
        ORDER BY sr.id DESC
        LIMIT 1
        """,
        (request.as_of_date, request.strategy_version),
    ).fetchone()
    if row is None:
        return "review_not_run"
    if int(row["signal_count"]) == 0:
        return "no_strategy_signals"
    return "no_daily_pick"


def _latest_market_date(conn: Any, as_of_date: str) -> str | None:
    row = conn.execute(
        """
        SELECT MAX(trade_date) AS latest_market_date
        FROM market_bars
        WHERE trade_date <= ?
        """,
        (as_of_date,),
    ).fetchone()
    return None if row is None else row["latest_market_date"]


def _next_trade_date(conn: Any, as_of_date: str) -> str | None:
    row = conn.execute(
        """
        SELECT cal_date
        FROM trade_calendar
        WHERE is_open = 1
          AND cal_date > ?
        ORDER BY cal_date
        LIMIT 1
        """,
        (as_of_date,),
    ).fetchone()
    return None if row is None else row["cal_date"]


def _latest_strategy_run_id(db_path: Path, request: DailyReportRequest) -> int | None:
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id
            FROM strategy_runs
            WHERE as_of_date = ?
              AND strategy_version = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (request.as_of_date, request.strategy_version),
        ).fetchone()
    return None if row is None else int(row["id"])


def _latest_feature_run_id(db_path: Path, request: DailyReportRequest) -> int | None:
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT feature_run_id
            FROM strategy_runs
            WHERE as_of_date = ?
              AND strategy_version = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (request.as_of_date, request.strategy_version),
        ).fetchone()
    return None if row is None or row["feature_run_id"] is None else int(row["feature_run_id"])


def _open_position_count(conn: Any, account_id: int) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM positions
            WHERE account_id = ?
              AND status NOT IN ('closed', 'cancelled')
            """,
            (account_id,),
        ).fetchone()[0]
    )


def _position_action_due(row: Any, as_of_date: str) -> str:
    status = row["status"]
    planned_t2_date = row["planned_t2_date"]
    planned_t5_date = row["planned_t5_date"]
    if status == "need_t2_decision" or (
        status == "waiting_t2" and planned_t2_date is not None and planned_t2_date <= as_of_date
    ):
        return "buy_day_2_decision"
    if status == "need_t5_exit" or (
        status == "holding_to_t5" and planned_t5_date is not None and planned_t5_date <= as_of_date
    ):
        return "buy_day_5_exit"
    if status == "planned_exit":
        return "sell_plan_exists"
    return "none"


def _loads_json_object(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        loaded = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _loads_json_list(payload: str | None) -> list[str]:
    if not payload:
        return []
    try:
        loaded = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return []
    return _string_list(loaded)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _optional_text_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _paper_promotion_lines(promotion: PaperReadinessResult | None) -> list[str]:
    if promotion is None:
        return [
            "",
            "## Paper 晋级分数卡",
            "",
            "- 状态：未计算",
        ]

    blockers = ", ".join(promotion.promotion_blockers) if promotion.promotion_blockers else "无"
    warnings = ", ".join(promotion.promotion_warnings) if promotion.promotion_warnings else "无"
    next_steps = _promotion_next_steps(promotion)
    return [
        "",
        "## Paper 晋级分数卡",
        "",
        f"- 状态：{_readiness_text(promotion.readiness)}",
        f"- 样本交易：{promotion.trades_count}",
        f"- 已闭环交易：{promotion.closed_trades_count}",
        f"- 累计实现盈亏：{_money(promotion.realized_pnl)}",
        f"- 胜率：{_ratio_text(promotion.win_rate)}",
        f"- 平均滑点：{_ratio_text(promotion.avg_slippage)}",
        f"- 最近 pipeline：{promotion.last_pipeline_status or '无记录'}",
        f"- 当前阻断：{blockers}",
        f"- 晋级 live 前还差什么：{next_steps}",
        f"- 晋级警告：{warnings}",
    ]


def _daily_acceptance_lines(acceptance: DailyAcceptanceReport | None) -> list[str]:
    if acceptance is None:
        return [
            "",
            "## 纸盘每日运营验收",
            "",
            "- 状态：未计算",
            "- 提醒：只读验收面板，不会执行交易、取消计划或改策略参数。",
        ]

    lines = [
        "",
        "## 纸盘每日运营验收",
        "",
        f"- 状态：{_acceptance_status_text(acceptance.status)}",
        f"- 验收摘要：{acceptance.summary}",
        f"- 执行日：{_date_text(acceptance.execution_date)}",
        f"- 数据新鲜度：{_acceptance_gate_text(acceptance.data_freshness)}",
        f"- 证据覆盖：{_acceptance_gate_text(acceptance.evidence_coverage)}",
        f"- Agent 状态：{_acceptance_gate_text(acceptance.agent_status)}",
        f"- open-execution 状态：{_acceptance_gate_text(acceptance.open_execution_gate)}",
        "- 提醒：只读验收面板，不会执行交易、取消计划或改策略参数。",
        "",
        "readiness gates：",
    ]
    if acceptance.readiness_gates:
        lines.extend(f"- {gate.label}：{_acceptance_gate_text(gate)}" for gate in acceptance.readiness_gates)
    else:
        lines.append("- 未返回 readiness gates。")
    lines.extend(["", "未处理 blocker："])
    if acceptance.unresolved_blockers:
        lines.extend(f"- {blocker}" for blocker in acceptance.unresolved_blockers)
    else:
        lines.append("- 无。")
    lines.extend(["", "验收告警："])
    if acceptance.alerts:
        lines.extend(f"- [{alert.severity}] {alert.title}：{alert.summary}" for alert in acceptance.alerts)
    else:
        lines.append("- 无。")
    return lines


def _next_day_decision_lines(cockpit: NextDayDecisionCockpit | None) -> list[str]:
    if cockpit is None:
        return [
            "",
            "## 下一交易日决策驾驶舱",
            "",
            "- 状态：未计算",
            "- 提醒：驾驶舱只读，不会执行交易、开启 timer 或修改策略参数。",
        ]

    proposal = cockpit.system_proposal
    lines = [
        "",
        "## 下一交易日决策驾驶舱",
        "",
        f"- 状态：{_decision_status_text(cockpit.status)}",
        f"- 摘要：{cockpit.headline}",
        f"- 推荐人工动作：{cockpit.recommended_manual_action}",
        f"- 执行日：{_date_text(cockpit.execution_date)}",
        f"- 系统建议：{_open_execution_action_text(proposal.action)}",
        f"- 目标：{proposal.target or '-'}",
        f"- 计划 / 持仓：{proposal.trade_plan_id or '-'} / {proposal.position_id or '-'}",
        f"- 计划股数：{_none_dash(proposal.planned_shares)}",
        "- 提醒：驾驶舱只读，不会执行交易、开启 timer 或修改策略参数。",
        "",
        "决策清单：",
    ]
    if cockpit.checklist:
        for item in cockpit.checklist:
            blockers = f"；blocker {', '.join(item.blocker_codes)}" if item.blocker_codes else ""
            warnings = f"；warning {', '.join(item.warning_codes)}" if item.warning_codes else ""
            lines.append(
                f"- {item.label}：{_acceptance_status_text(item.status)}；"
                f"{item.summary}{blockers}{warnings}；下一步：{item.manual_action}"
            )
    else:
        lines.append("- 暂无 checklist。")
    if cockpit.strategy_proposals is not None:
        proposals = cockpit.strategy_proposals
        lines.extend(
            [
                "",
                "策略 proposal / hypothesis：",
                (
                    f"- total={proposals.total_count} proposed={proposals.proposed_count} "
                    f"testing={proposals.testing_count} accepted={proposals.accepted_count} "
                    f"review_required={proposals.review_required_count}"
                ),
            ]
        )
        if proposals.items:
            lines.extend(f"- {item.title}（{_status_text(item.status)}）" for item in proposals.items[:5])
    return lines


def _decision_status_text(value: str) -> str:
    return {
        "ready": "就绪",
        "review_required": "需要人工复核",
        "blocked": "阻断",
    }.get(value, value)


def _open_execution_action_text(value: str) -> str:
    return {
        "record_buy": "录入买入成交",
        "record_sell": "录入卖出成交",
        "evaluate_exit": "评估退出",
        "wait": "等待",
        "none": "无动作",
        "blocked": "阻断",
    }.get(value, value)


def _acceptance_gate_text(gate: DailyAcceptanceGate) -> str:
    blockers = f"；blocker {', '.join(gate.blocker_codes)}" if gate.blocker_codes else ""
    warnings = f"；warning {', '.join(gate.warning_codes)}" if gate.warning_codes else ""
    return f"{_acceptance_status_text(gate.status)}；{gate.summary}{blockers}{warnings}"


def _acceptance_status_text(value: str) -> str:
    return {
        "pass": "通过",
        "warning": "警告",
        "blocked": "阻断",
    }.get(value, value)


def _market_review_lines(review: MarketReviewReport | None) -> list[str]:
    lines = ["", "## 全市场复盘", ""]
    if review is None:
        lines.append("- 状态：未生成全市场复盘。")
        lines.append("- 外部证据覆盖：未接入。")
        lines.append("- 策略假设：未生成。")
        return lines

    regime_payload = {
        "regime": review.regime,
        "breadth_score": review.breadth_score,
        "trend_score": review.trend_score,
        "volume_score": review.volume_score,
        "persistence_score": review.persistence_score,
        "summary": review.summary,
    }
    top_sector_payloads = [asdict(sector) for sector in review.top_sectors]
    lines.extend(
        [
            f"- 状态：{_status_text(review.status)}；{_market_regime_text(regime_payload)}",
            f"- Top 5 板块：{_top_sectors_text(top_sector_payloads)}",
            f"- 板块持续性：{_sector_persistence_text(review.sector_persistence)}",
            f"- 外部证据覆盖：{_external_coverage_text(review.external_evidence_coverage)}",
            f"- 策略假设：{_strategy_hypotheses_text(review.strategy_hypotheses)}",
        ]
    )
    return lines


def _market_plan_context_lines(context: MarketPlanContextReport | None) -> list[str]:
    lines = ["", "## 全市场复盘与明日计划关系", ""]
    if context is None:
        lines.append("- 状态：未生成全市场复盘与计划关系。")
        lines.append("- 提醒：该部分只提供管理建议，不会自动创建、取消或执行交易计划。")
        return lines

    evidence = context.evidence
    market_regime = _dict_value(evidence.get("market_regime"))
    top_sectors = _dict_list(evidence.get("top_sectors"))
    candidate_sector = _dict_value(evidence.get("candidate_sector"))
    external_items = _dict_list(evidence.get("external_items"))
    lines.extend(
        [
            f"- 市场状态：{_market_regime_text(market_regime)}",
            f"- 强势板块：{_top_sectors_text(top_sectors)}",
            f"- 候选板块匹配：{_candidate_sector_fit_text(candidate_sector)}",
            f"- 新闻/情绪匹配：{_external_fit_text(external_items)}",
            (
                "- 管理建议："
                f"{_management_action_text(context.management_action)}；"
                f"匹配 {_alignment_text(context.alignment)}；"
                f"风险 {_risk_text(context.risk_level)}"
            ),
            f"- 理由：{context.rationale}",
            "- 提醒：该结论只提供管理建议，不会自动创建、取消或执行交易计划。",
        ]
    )
    return lines


def _dict_value(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _market_regime_text(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "未知"
    regime = {
        "risk_on": "风险偏好",
        "neutral": "中性",
        "risk_off": "风险收缩",
        "unknown": "未知",
    }.get(str(payload.get("regime") or "unknown"), str(payload.get("regime") or "unknown"))
    summary = _optional_text_value(payload.get("summary"))
    scores = []
    for label, key in [("宽度", "breadth_score"), ("趋势", "trend_score"), ("持续", "persistence_score")]:
        score = _optional_float_from_any(payload.get(key))
        if score is not None:
            scores.append(f"{label}{score:.2f}")
    score_text = f"（{' / '.join(scores)}）" if scores else ""
    return f"{regime}{score_text}" + (f"：{summary}" if summary else "")


def _top_sectors_text(sectors: list[dict[str, Any]]) -> str:
    if not sectors:
        return "未找到板块轮动数据"
    parts = []
    for sector in sectors[:3]:
        name = str(sector.get("sector_name") or sector.get("sector_code") or "未知板块")
        rank = _optional_int_from_any(sector.get("rank_overall"))
        persistence = _optional_float_from_any(sector.get("persistence_score"))
        rank_text = f"#{rank}" if rank is not None else "#-"
        persistence_text = f"，持续 {persistence:.2f}" if persistence is not None else ""
        parts.append(f"{name}{rank_text}{persistence_text}")
    return "；".join(parts)


def _candidate_sector_fit_text(sector: dict[str, Any] | None) -> str:
    if not sector:
        return "未找到候选所属板块数据"
    name = str(sector.get("sector_name") or sector.get("sector_code") or "未知板块")
    rank = _optional_int_from_any(sector.get("rank_overall"))
    role = str(sector.get("role") or "unknown")
    persistence = _optional_float_from_any(sector.get("persistence_score"))
    rank_text = f"全市场排名 #{rank}" if rank is not None else "全市场排名未知"
    persistence_text = f"，持续 {persistence:.2f}" if persistence is not None else ""
    return f"{name}，{rank_text}，个股角色 {role}{persistence_text}"


def _external_fit_text(items: list[dict[str, Any]]) -> str:
    if not items:
        return "未找到新闻/情绪证据"
    high_negative_count = sum(
        1
        for item in items
        if item.get("sentiment") == "negative" and item.get("importance") == "high"
    )
    first = items[0]
    title = str(first.get("title") or "未命名证据")
    sentiment = str(first.get("sentiment") or "unknown")
    importance = str(first.get("importance") or "unknown")
    return f"{len(items)} 条证据，高重要度负面 {high_negative_count} 条；首要证据：{title}（{sentiment}/{importance}）"


def _sector_persistence_text(sectors: list[MarketSectorReport]) -> str:
    if not sectors:
        return "未找到持续性板块数据"
    parts = []
    for sector in sectors[:5]:
        persistence = _optional_float_from_any(sector.persistence_score)
        persistence_text = f"{persistence:.2f}" if persistence is not None else "未知"
        rank_text = f"#{sector.rank_overall}" if sector.rank_overall is not None else "#-"
        parts.append(f"{sector.sector_name or sector.sector_code}{rank_text} 持续 {persistence_text}")
    return "；".join(parts)


def _external_coverage_text(coverage: dict[str, Any]) -> str:
    total_count = _optional_int_from_any(coverage.get("total_count")) or 0
    if total_count <= 0:
        return "未找到全市场新闻/情绪证据"
    scope = coverage.get("by_scope")
    sentiment = coverage.get("by_sentiment")
    provider = coverage.get("by_provider")
    scope_text = _count_dict_text(scope if isinstance(scope, dict) else {})
    sentiment_text = _count_dict_text(sentiment if isinstance(sentiment, dict) else {})
    provider_text = _count_dict_text(provider if isinstance(provider, dict) else {})
    status_parts = []
    for label, key in (("市场", "market"), ("板块", "sector"), ("个股", "stock"), ("新闻", "news"), ("情绪", "sentiment")):
        value = _optional_text_value(coverage.get(key))
        if value:
            status_parts.append(f"{label}{_evidence_status_text(value)}")
    status_text = f"；状态 {' / '.join(status_parts)}" if status_parts else ""
    return f"{total_count} 条；范围 {scope_text}；情绪 {sentiment_text}；来源 {provider_text}{status_text}"


def _evidence_status_text(value: str) -> str:
    return {
        "available": "可用",
        "partial": "部分",
        "missing": "缺失",
        "unavailable": "不可用",
    }.get(value, value)


def _strategy_hypotheses_text(hypotheses: list[StrategyHypothesisSummaryReport]) -> str:
    if not hypotheses:
        return "未生成策略假设"
    parts = [f"{item.title}（{_status_text(item.status)}）" for item in hypotheses[:3]]
    suffix = f"；另有 {len(hypotheses) - 3} 条" if len(hypotheses) > 3 else ""
    return f"{len(hypotheses)} 条；" + "；".join(parts) + suffix


def _count_dict_text(counts: dict[Any, Any]) -> str:
    if not counts:
        return "无"
    parts = []
    for key in sorted(counts):
        value = _optional_int_from_any(counts[key]) or 0
        parts.append(f"{key} {value}")
    return " / ".join(parts)


def _optional_int_from_any(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float_from_any(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _promotion_next_steps(promotion: PaperReadinessResult) -> str:
    if promotion.promotion_blockers:
        return ", ".join(promotion.promotion_blockers)
    if promotion.promotion_warnings:
        return ", ".join(promotion.promotion_warnings)
    return "已满足当前 paper 晋级检查。"


def _ratio_text(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.2f}%"


def _date_text(value: str | None) -> str:
    if value is None:
        return "-"
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def _none_dash(value: object) -> str:
    return "-" if value is None else str(value)


def _money(value: float | None) -> str:
    return "-" if value is None else f"{value:,.2f}"


def _account_name(account: AccountReport) -> str:
    if account.account_key and account.name:
        return f"{account.account_key}（{account.name}）"
    return account.account_key or account.name or "未找到"


def _readiness_text(value: str) -> str:
    return {
        "pass": "可交易",
        "warning": "有警告，可继续但需留意",
        "blocked": "阻断，不能晋级 live",
        "blocker": "阻断，不能生成交易动作",
    }.get(value, value)


def _selection_text(candidate: CandidateReport) -> str:
    if candidate.selected_over_signal_count <= 0:
        return candidate.selection_reason
    return (
        f"排名第 {_none_dash(candidate.signal_rank)}，评分高于 "
        f"{candidate.selected_over_signal_count} 个同日信号；{candidate.selection_reason}"
    )


def _action_text(value: str) -> str:
    return {
        "buy_next_open": "下一交易日开盘买入",
        "skip_no_cash": "跳过：现金不足或不足一手",
        "skip_max_positions": "跳过：无空闲仓位",
        "skip_agent_risk": "跳过：Agent 风险提示",
        "skip_manual": "人工跳过",
        "hold": "继续持有",
        "sell_t2_take_profit": "T+2 止盈卖出",
        "sell_t2_stop_loss": "T+2 止损卖出",
        "sell_t5_timeout": "T+5 到期卖出",
        "manual_review": "人工复核",
    }.get(value, value)


def _status_text(value: str) -> str:
    return {
        "active": "有效",
        "draft": "草稿",
        "executed": "已执行",
        "skipped": "已跳过",
        "cancelled": "已取消",
        "expired": "已过期",
        "superseded": "已被替代",
        "waiting_t2": "等待 T+2",
        "need_t2_decision": "需要 T+2 决策",
        "holding_to_t5": "持有到 T+5",
        "need_t5_exit": "需要 T+5 退出",
        "planned_exit": "已有退出计划",
        "partially_closed": "部分平仓",
        "not_run": "未运行",
        "completed": "已完成",
        "failed": "失败",
        "running": "运行中",
        "planned": "计划中",
    }.get(value, value)


def _agent_action_text(value: str) -> str:
    return {
        "support": "支持",
        "caution": "谨慎",
        "reject": "反对",
        "review_required": "需要人工复核",
        "no_opinion": "无有效意见",
    }.get(value, value)


def _agent_source_label(value: str | None) -> str:
    return {
        "local_snapshot_mode": "TradingAgents 本地快照模式",
        "external_graph_mode": "TradingAgents 外部图模式",
        "unavailable_fallback": "TradingAgents 不可用 fallback",
        "dry_run": "dry-run preview",
    }.get(value or "", "TradingAgents 输出")


def _risk_text(value: str) -> str:
    return {
        "low": "低",
        "medium": "中",
        "high": "高",
        "unknown": "未知",
    }.get(value, value)


def _alignment_text(value: str) -> str:
    return {
        "aligned": "顺势",
        "neutral": "中性",
        "conflict": "冲突",
        "unknown": "未知",
    }.get(value, value)


def _management_action_text(value: str) -> str:
    return {
        "proceed": "按计划推进",
        "manual_review": "人工复核",
        "consider_cancel": "考虑取消",
        "unknown": "未知",
    }.get(value, value)


def _agent_coverage_text(value: str | None) -> str:
    return {
        "available": "可用",
        "partial": "部分",
        "missing": "缺失",
        "unavailable": "未接入",
    }.get(value or "", value or "未知")


def _agent_evidence_category_text(value: str) -> str:
    return {
        "technical": "技术面",
        "fundamental": "基本面",
        "news": "新闻",
        "announcement": "公告",
        "sentiment": "情绪",
        "risk_note": "风险提示",
        "research_note": "研究摘要",
    }.get(value, value)


def _due_text(value: str) -> str:
    return {
        "buy_day_2_decision": "需要 T+2 判断",
        "buy_day_5_exit": "需要 T+5 退出判断",
        "sell_plan_exists": "已有卖出计划",
        "none": "暂无动作",
    }.get(value, value)


def _reason_text(value: str | None) -> str:
    return {
        None: "-",
        "review_not_run": "尚未运行当日复盘",
        "no_strategy_signals": "策略未产生可执行信号",
        "no_daily_pick": "有信号但未生成今日入选",
        "no_valid_raw_events": "没有有效入池事件",
        "daily_pick": "来自今日入选",
        "max_positions": "无空闲仓位",
        "no_cash_or_board_lot": "现金不足或不足一手",
    }.get(value, value or "-")
