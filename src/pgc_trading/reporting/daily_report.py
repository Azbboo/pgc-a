"""Daily close report query and Markdown/JSON rendering."""

from __future__ import annotations

import json
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
    OperationalReadinessService,
    PaperReadinessRequest,
    PaperReadinessResult,
)
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
class DailyReport:
    generated_at: str
    as_of_date: str
    latest_market_date: str | None
    next_trade_date: str | None
    strategy_version: str
    account: AccountReport
    data_quality: DataQualityReport
    paper_promotion: PaperReadinessResult | None
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

        data_quality = _data_quality_report(readiness, invariant_report)
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
        report = DailyReport(
            generated_at=datetime.now(UTC).isoformat(),
            as_of_date=request.as_of_date,
            latest_market_date=latest_market_date,
            next_trade_date=next_trade_date,
            strategy_version=request.strategy_version,
            account=account,
            data_quality=data_quality,
            paper_promotion=paper_promotion,
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
        SELECT scope_type, item_type, sentiment, importance, provider, COUNT(*) AS count
        FROM market_external_items
        WHERE as_of_date = ?
        GROUP BY scope_type, item_type, sentiment, importance, provider
        ORDER BY scope_type, item_type, sentiment, importance, provider
        """,
        (as_of_date,),
    ).fetchall()
    total_count = 0
    by_scope: dict[str, int] = {}
    by_item_type: dict[str, int] = {}
    by_sentiment: dict[str, int] = {}
    by_importance: dict[str, int] = {}
    by_provider: dict[str, int] = {}
    for row in rows:
        count = int(row["count"] or 0)
        total_count += count
        _increment_count(by_scope, row["scope_type"], count)
        _increment_count(by_item_type, row["item_type"], count)
        _increment_count(by_sentiment, row["sentiment"], count)
        _increment_count(by_importance, row["importance"], count)
        _increment_count(by_provider, row["provider"], count)
    return {
        "total_count": total_count,
        "coverage": "available" if total_count else "missing",
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
        if status in {"available", "partial", "unavailable"}:
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
        if status == "unavailable"
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
    return f"{total_count} 条；范围 {scope_text}；情绪 {sentiment_text}；来源 {provider_text}"


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
