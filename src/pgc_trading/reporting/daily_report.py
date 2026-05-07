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
from pgc_trading.storage.database import connect
from pgc_trading.strategies.cpb_6157 import STRATEGY_VERSION


@dataclass(frozen=True)
class DailyReportRequest:
    as_of_date: str
    account_key: str | None = DEFAULT_ACCOUNT_KEY
    account_id: int | None = None
    strategy_version: str = STRATEGY_VERSION


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
class AgentAdviceReport:
    agent_run_id: int | None
    agent_decision_id: int | None
    status: str
    action: str
    risk_level: str
    confidence: float | None
    summary: str | None
    note: str
    supporting_points: list[str] = field(default_factory=list)
    risk_points: list[str] = field(default_factory=list)
    artifacts: list[AgentArtifactReport] = field(default_factory=list)
    report_markdown: str | None = None


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
    candidate: CandidateReport | None
    no_candidate_reason: str | None
    buy_plan: BuyPlanReport | None
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

        with connect(self.db_path) as conn:
            account = _load_account(conn, request)
            candidate = _load_candidate(conn, request)
            buy_plan = _load_buy_plan(conn, candidate, account)
            agent_advice = _load_agent_advice(conn, candidate)
            positions = _load_positions(conn, request.as_of_date, account.account_id)
            no_candidate_reason = _no_candidate_reason(conn, request, candidate)
            latest_market_date = _latest_market_date(conn, request.as_of_date)
            next_trade_date = _next_trade_date(conn, request.as_of_date)

        data_quality = _data_quality_report(readiness)
        lineage = ReportLineage(
            feature_run_id=candidate.feature_run_id if candidate else _latest_feature_run_id(self.db_path, request),
            strategy_run_id=candidate.strategy_run_id if candidate else _latest_strategy_run_id(self.db_path, request),
            market_fetch_run_id=candidate.market_fetch_run_id if candidate else None,
            daily_pick_id=candidate.daily_pick_id if candidate else None,
            signal_id=candidate.signal_id if candidate else None,
            trade_plan_id=buy_plan.trade_plan_id if buy_plan else None,
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
            candidate=candidate,
            no_candidate_reason=no_candidate_reason,
            buy_plan=buy_plan,
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
            errors=readiness.errors,
            lineage={
                "as_of_date": request.as_of_date,
                "strategy_version": request.strategy_version,
                "account_id": account.account_id,
                "daily_pick_id": lineage.daily_pick_id,
                "trade_plan_id": lineage.trade_plan_id,
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
        "",
        "## 数据状态",
        "",
        f"- 结果：{_readiness_text(report.data_quality.readiness)}",
        f"- 可交易：{'是' if report.data_quality.can_trade else '否'}",
        f"- 有效入池事件：{report.data_quality.valid_raw_count}",
        f"- 阻断 / 警告：{report.data_quality.blocker_count} / {report.data_quality.warning_count}",
        f"- 缺失行情：{report.data_quality.missing_market_bar_count}",
    ]
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

    lines.extend(["", "## Agent 复核", ""])
    lines.extend(
        [
            f"- 状态：{_status_text(report.agent_advice.status)}",
            f"- 意见：{_agent_action_text(report.agent_advice.action)}",
            f"- 风险：{_risk_text(report.agent_advice.risk_level)}",
            f"- 摘要：{report.agent_advice.summary or report.agent_advice.note}",
            "- 提醒：Agent 只提供复核意见，不会自动改变交易计划。",
        ]
    )
    if report.agent_advice.supporting_points:
        lines.extend(["", "支持依据："])
        lines.extend(f"- {point}" for point in report.agent_advice.supporting_points)
    if report.agent_advice.risk_points:
        lines.extend(["", "风险提示："])
        lines.extend(f"- {point}" for point in report.agent_advice.risk_points)

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


def _data_quality_report(result: ServiceResult[Any]) -> DataQualityReport:
    data = result.data
    if data is None:
        return DataQualityReport(
            readiness="blocker",
            can_trade=False,
            blocker_count=len(result.errors),
            warning_count=len(result.warnings),
            valid_raw_count=0,
            market_coverage_ok=False,
            trade_calendar_ok=False,
            strategy_version_ok=False,
            account_ok=False,
            missing_market_bar_count=0,
        )
    return DataQualityReport(
        readiness=data.readiness,
        can_trade=data.readiness != "blocker",
        blocker_count=data.blocker_count,
        warning_count=data.warning_count,
        valid_raw_count=data.valid_raw_count,
        market_coverage_ok=data.market_coverage_ok,
        trade_calendar_ok=data.trade_calendar_ok,
        strategy_version_ok=data.strategy_version_ok,
        account_ok=data.account_ok,
        missing_market_bar_count=data.missing_market_bar_count,
        event_ids=list(data.data_quality_event_ids),
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
          ad.raw_decision_json
        FROM agent_runs ar
        LEFT JOIN agent_decisions ad ON ad.agent_run_id = ar.id
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
    supporting_points = _loads_json_list(row["supporting_points_json"])
    if not supporting_points:
        supporting_points = _string_list(raw_decision.get("supporting_points"))
    risk_points = _loads_json_list(row["risk_points_json"])
    if not risk_points:
        risk_points = _string_list(raw_decision.get("risk_points"))
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
        supporting_points=supporting_points,
        risk_points=risk_points,
        artifacts=artifacts,
        report_markdown=_load_agent_report_markdown(final_report_path),
    )


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


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


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


def _risk_text(value: str) -> str:
    return {
        "low": "低",
        "medium": "中",
        "high": "高",
        "unknown": "未知",
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
