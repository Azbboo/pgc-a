"""Daily close workflow application service."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pgc_trading.config import Paths
from pgc_trading.market.calendar import is_yyyymmdd
from pgc_trading.portfolio.sizing import plan_equal_slot_sizing
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult
from pgc_trading.services.daily_review_service import (
    DailyPickDTO,
    DailyReviewService,
    RunDailyReviewRequest,
    RunDailyReviewResult,
)
from pgc_trading.services.data_quality_service import (
    DailyReviewReadinessRequest,
    DailyReviewReadinessResult,
    DataQualityService,
)
from pgc_trading.services.portfolio_planning_service import (
    GenerateBuyPlanRequest,
    GenerateTradePlanResult,
    PortfolioPlanningService,
)
from pgc_trading.storage.database import connect
from pgc_trading.storage.invariant_checks import InvariantReport, check_database
from pgc_trading.strategies.cpb_6157 import STRATEGY_VERSION


DEFAULT_ACCOUNT_KEY = "paper-main"


@dataclass(frozen=True)
class RunDailyCloseWorkflowRequest:
    as_of_date: str
    strategy_version: str = STRATEGY_VERSION
    account_key: str | None = DEFAULT_ACCOUNT_KEY
    account_id: int | None = None
    max_daily_picks: int = 1
    run_type: str = "paper"
    force_new_review_run: bool = False


@dataclass(frozen=True)
class DailyCloseCandidateDTO:
    daily_pick_id: int | None
    signal_id: int | None
    ts_code: str
    name: str
    review_date: str
    planned_buy_date: str | None
    score: float
    signal_rank: int
    selection_reason: str
    features: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DailyClosePlanDTO:
    trade_plan_id: int | None
    action: str
    status: str
    reason: str
    planned_trade_date: str | None
    planned_cash: float | None
    planned_shares: int | None
    free_position_slots: int
    idempotent: bool = False


@dataclass(frozen=True)
class DailyCloseWorkflowResult:
    as_of_date: str
    next_trade_date: str | None
    readiness: str | None
    workflow_status: str
    invariant_ok: bool
    review_status: str | None
    plan_status: str | None
    signals_count: int
    candidate: DailyCloseCandidateDTO | None = None
    buy_plan: DailyClosePlanDTO | None = None
    skipped_reason: str | None = None
    data_quality_event_ids: list[int] = field(default_factory=list)
    invariant_violation_codes: list[str] = field(default_factory=list)


class DailyCloseWorkflowService:
    """Orchestrate daily close review and buy-plan draft generation."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def run_daily_close(
        self,
        request: RunDailyCloseWorkflowRequest,
        ctx: RequestContext,
    ) -> ServiceResult[DailyCloseWorkflowResult]:
        validation_errors = _validate_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_result(request, workflow_status="validation_failed"),
                errors=validation_errors,
            )

        invariant_report = check_database(self.db_path)
        if not invariant_report.ok:
            errors = _invariant_errors(invariant_report)
            return ServiceResult(
                status="blocked",
                request_id=ctx.request_id,
                data=_empty_result(
                    request,
                    workflow_status="invariant_blocker",
                    invariant_ok=False,
                    invariant_violation_codes=[violation.code for violation in invariant_report.violations],
                ),
                errors=errors,
                lineage=_base_lineage(request),
            )

        readiness = DataQualityService(self.db_path).check_daily_review_readiness(
            DailyReviewReadinessRequest(
                as_of_date=request.as_of_date,
                strategy_version=request.strategy_version,
                account_key=request.account_key,
                account_id=request.account_id,
            ),
            _child_context(ctx, request, "readiness"),
        )
        if readiness.status == "validation_failed" or readiness.data is None:
            return ServiceResult(
                status=readiness.status,
                request_id=ctx.request_id,
                data=_empty_result(request, workflow_status="readiness_failed"),
                warnings=readiness.warnings,
                errors=readiness.errors,
                lineage={**_base_lineage(request), **readiness.lineage},
            )

        if readiness.data.readiness == "blocker":
            return ServiceResult(
                status="blocked",
                request_id=ctx.request_id,
                data=_empty_result(
                    request,
                    readiness=readiness.data.readiness,
                    workflow_status="data_quality_blocker",
                    data_quality_event_ids=readiness.data.data_quality_event_ids,
                ),
                created_ids=readiness.created_ids,
                warnings=readiness.warnings,
                errors=readiness.errors,
                lineage={**_base_lineage(request), **readiness.lineage},
            )

        next_trade_date = _next_open_date(self.db_path, request.as_of_date)
        if next_trade_date is None:
            error = ServiceError(
                code="NEXT_TRADE_DATE_NOT_FOUND",
                message=f"Next open trading date was not found after {request.as_of_date}.",
                entity_type="trade_calendar",
                severity="blocker",
            )
            return ServiceResult(
                status="blocked",
                request_id=ctx.request_id,
                data=_empty_result(
                    request,
                    next_trade_date=None,
                    readiness=readiness.data.readiness,
                    workflow_status="next_trade_date_blocker",
                    data_quality_event_ids=readiness.data.data_quality_event_ids,
                ),
                warnings=readiness.warnings,
                errors=[*readiness.errors, error],
                lineage={**_base_lineage(request), **readiness.lineage},
            )

        review = DailyReviewService(self.db_path).run_daily_review(
            RunDailyReviewRequest(
                as_of_date=request.as_of_date,
                strategy_version=request.strategy_version,
                max_daily_picks=request.max_daily_picks,
                run_type=request.run_type,
                force_new_run=request.force_new_review_run,
            ),
            _child_context(ctx, request, "review"),
        )
        if review.status not in {"success", "partial_success"} or review.data is None:
            return ServiceResult(
                status=review.status,
                request_id=ctx.request_id,
                data=_empty_result(
                    request,
                    next_trade_date=next_trade_date,
                    readiness=readiness.data.readiness,
                    workflow_status="review_failed",
                    review_status=review.status,
                    data_quality_event_ids=readiness.data.data_quality_event_ids,
                ),
                created_ids={**readiness.created_ids, **review.created_ids},
                warnings=[*readiness.warnings, *review.warnings],
                errors=[*readiness.errors, *review.errors],
                lineage={**_base_lineage(request), **readiness.lineage, **review.lineage},
            )

        if review.data.daily_pick is None:
            result_data = DailyCloseWorkflowResult(
                as_of_date=request.as_of_date,
                next_trade_date=next_trade_date,
                readiness=readiness.data.readiness,
                workflow_status="no_pick",
                invariant_ok=True,
                review_status=review.status,
                plan_status=None,
                signals_count=review.data.signals_count,
                candidate=None,
                buy_plan=None,
                skipped_reason=review.data.skipped_reason or "no_daily_pick",
                data_quality_event_ids=readiness.data.data_quality_event_ids,
            )
            return ServiceResult(
                status="skipped",
                request_id=ctx.request_id,
                data=result_data,
                created_ids={**readiness.created_ids, **review.created_ids},
                warnings=[*readiness.warnings, *review.warnings],
                errors=[*readiness.errors, *review.errors],
                lineage={**_base_lineage(request), **readiness.lineage, **review.lineage},
            )

        if ctx.dry_run and review.data.daily_pick_id is None:
            plan = _preview_buy_plan(
                self.db_path,
                request,
                review.data.daily_pick,
                next_trade_date,
                ctx,
            )
        else:
            plan = PortfolioPlanningService(self.db_path).generate_buy_plan(
                GenerateBuyPlanRequest(
                    account_key=request.account_key,
                    account_id=request.account_id,
                    daily_pick_id=review.data.daily_pick_id,
                    review_date=request.as_of_date,
                    planned_trade_date=next_trade_date,
                ),
                _child_context(ctx, request, "buy-plan"),
            )
        result_data = _workflow_result(
            request=request,
            next_trade_date=next_trade_date,
            readiness=readiness.data,
            review=review.data,
            review_status=review.status,
            plan=plan.data,
            plan_status=plan.status,
        )
        status = "success" if plan.status == "success" else plan.status
        return ServiceResult(
            status=status,
            request_id=ctx.request_id,
            data=result_data,
            created_ids={**readiness.created_ids, **review.created_ids, **plan.created_ids},
            warnings=[*readiness.warnings, *review.warnings, *plan.warnings],
            errors=[*readiness.errors, *review.errors, *plan.errors],
            lineage={
                **_base_lineage(request),
                **readiness.lineage,
                **review.lineage,
                **plan.lineage,
            },
        )


def _validate_request(request: RunDailyCloseWorkflowRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not is_yyyymmdd(request.as_of_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="as_of_date must use YYYYMMDD format."))
    if not request.strategy_version.strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="strategy_version is required."))
    if request.account_id is None and not request.account_key:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="account_key or account_id is required."))
    if request.max_daily_picks < 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="max_daily_picks cannot be negative."))
    if request.max_daily_picks > 1:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="Daily close workflow supports at most one pick."))
    return errors


def _workflow_result(
    *,
    request: RunDailyCloseWorkflowRequest,
    next_trade_date: str,
    readiness: DailyReviewReadinessResult,
    review: RunDailyReviewResult,
    review_status: str,
    plan: GenerateTradePlanResult | None,
    plan_status: str,
) -> DailyCloseWorkflowResult:
    plan_dto = _plan_dto(plan)
    return DailyCloseWorkflowResult(
        as_of_date=request.as_of_date,
        next_trade_date=next_trade_date,
        readiness=readiness.readiness,
        workflow_status="plan_ready" if plan_status == "success" else "plan_skipped",
        invariant_ok=True,
        review_status=review_status,
        plan_status=plan_status,
        signals_count=review.signals_count,
        candidate=_candidate_dto(review.daily_pick),
        buy_plan=plan_dto,
        skipped_reason=None if plan_status == "success" else (plan.reason if plan else plan_status),
        data_quality_event_ids=readiness.data_quality_event_ids,
    )


def _candidate_dto(pick: DailyPickDTO | None) -> DailyCloseCandidateDTO | None:
    if pick is None:
        return None
    return DailyCloseCandidateDTO(
        daily_pick_id=pick.id,
        signal_id=pick.signal_id,
        ts_code=pick.ts_code,
        name=pick.name,
        review_date=pick.review_date,
        planned_buy_date=pick.planned_buy_date,
        score=pick.score,
        signal_rank=pick.signal_rank,
        selection_reason=pick.selection_reason,
        features=pick.features,
    )


def _preview_buy_plan(
    db_path: Path,
    request: RunDailyCloseWorkflowRequest,
    daily_pick: DailyPickDTO,
    planned_trade_date: str,
    ctx: RequestContext,
) -> ServiceResult[GenerateTradePlanResult]:
    with connect(db_path) as conn:
        account = _load_preview_account(conn, request.account_key, request.account_id)
        if isinstance(account, ServiceError):
            return _preview_plan_validation_failed(ctx, account)

        cash = _latest_cash(conn, account)
        open_positions = _open_position_count(conn, account["id"])
        price_reference = _latest_close(conn, daily_pick.ts_code, daily_pick.review_date)

    sizing = plan_equal_slot_sizing(
        cash=cash,
        max_positions=int(account["max_positions"]),
        open_positions=open_positions,
        price_reference=price_reference,
    )
    action = "buy_next_open"
    status = "active"
    reason = "daily_pick_preview"
    if sizing.free_position_slots <= 0:
        action = "skip_max_positions"
        status = "skipped"
        reason = "max_positions"
    elif (sizing.planned_cash or 0.0) <= 0 or (sizing.planned_shares or 0) <= 0:
        action = "skip_no_cash"
        status = "skipped"
        reason = "no_cash_or_board_lot"

    return ServiceResult(
        status="skipped" if status == "skipped" else "success",
        request_id=ctx.request_id,
        data=GenerateTradePlanResult(
            trade_plan_id=None,
            action=action,
            status=status,
            reason=reason,
            planned_trade_date=planned_trade_date,
            planned_cash=sizing.planned_cash,
            planned_shares=sizing.planned_shares,
            free_position_slots=sizing.free_position_slots,
        ),
        lineage={
            "account_key": account["account_key"],
            "daily_pick_id": None,
            "signal_id": None,
            "review_date": daily_pick.review_date,
            "dry_run_preview": "true",
        },
    )


def _plan_dto(plan: GenerateTradePlanResult | None) -> DailyClosePlanDTO | None:
    if plan is None:
        return None
    return DailyClosePlanDTO(
        trade_plan_id=plan.trade_plan_id,
        action=plan.action,
        status=plan.status,
        reason=plan.reason,
        planned_trade_date=plan.planned_trade_date,
        planned_cash=plan.planned_cash,
        planned_shares=plan.planned_shares,
        free_position_slots=plan.free_position_slots,
        idempotent=plan.idempotent,
    )


def _load_preview_account(
    conn: Any,
    account_key: str | None,
    account_id: int | None,
) -> dict[str, Any] | ServiceError:
    if account_id is None and not account_key:
        return ServiceError(code="VALIDATION_ERROR", message="account_key or account_id is required.")
    if account_id is not None:
        row = conn.execute(
            """
            SELECT id, account_key, account_type, initial_cash, max_positions, position_sizing, status
            FROM portfolio_accounts
            WHERE id = ?
            """,
            (account_id,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT id, account_key, account_type, initial_cash, max_positions, position_sizing, status
            FROM portfolio_accounts
            WHERE account_key = ?
            """,
            (account_key,),
        ).fetchone()
    if row is None:
        return ServiceError(code="ACCOUNT_NOT_FOUND", message="Portfolio account was not found.")
    if account_key and row["account_key"] != account_key:
        return ServiceError(code="ACCOUNT_MISMATCH", message="account_key and account_id point to different accounts.")
    if row["status"] != "active":
        return ServiceError(code="ACCOUNT_INACTIVE", message=f"Account is not active: {row['account_key']}.")
    if row["account_type"] != "paper":
        return ServiceError(
            code="UNSUPPORTED_ACCOUNT_TYPE",
            message="Daily close dry-run buy-plan preview currently supports paper accounts only.",
            entity_type="portfolio_account",
            entity_id=int(row["id"]),
            severity="blocker",
        )
    return dict(row)


def _latest_cash(conn: Any, account: dict[str, Any]) -> float:
    row = conn.execute(
        """
        SELECT cash
        FROM equity_snapshots
        WHERE account_id = ?
        ORDER BY as_of_date DESC, id DESC
        LIMIT 1
        """,
        (account["id"],),
    ).fetchone()
    if row is None:
        return float(account["initial_cash"])
    return float(row["cash"])


def _latest_close(conn: Any, ts_code: str, as_of_date: str) -> float | None:
    row = conn.execute(
        """
        SELECT COALESCE(NULLIF(adj_close, 0), close) AS close_price
        FROM market_bars
        WHERE ts_code = ?
          AND trade_date <= ?
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        (ts_code, as_of_date),
    ).fetchone()
    if row is None or row["close_price"] is None:
        return None
    return float(row["close_price"])


def _open_position_count(conn: Any, account_id: int) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM positions
            WHERE account_id = ?
              AND status IN (
                'open',
                'waiting_t2',
                'need_t2_decision',
                'holding_until_t5',
                'need_t5_exit'
              )
            """,
            (account_id,),
        ).fetchone()[0]
    )


def _preview_plan_validation_failed(
    ctx: RequestContext,
    error: ServiceError,
) -> ServiceResult[GenerateTradePlanResult]:
    return ServiceResult(
        status="validation_failed",
        request_id=ctx.request_id,
        data=GenerateTradePlanResult(
            trade_plan_id=None,
            action="buy_next_open",
            status="validation_failed",
            reason=error.code,
            planned_trade_date=None,
            planned_cash=None,
            planned_shares=None,
            free_position_slots=0,
        ),
        errors=[error],
    )


def _empty_result(
    request: RunDailyCloseWorkflowRequest,
    *,
    workflow_status: str,
    next_trade_date: str | None = None,
    readiness: str | None = None,
    invariant_ok: bool = True,
    review_status: str | None = None,
    plan_status: str | None = None,
    data_quality_event_ids: list[int] | None = None,
    invariant_violation_codes: list[str] | None = None,
) -> DailyCloseWorkflowResult:
    return DailyCloseWorkflowResult(
        as_of_date=request.as_of_date,
        next_trade_date=next_trade_date,
        readiness=readiness,
        workflow_status=workflow_status,
        invariant_ok=invariant_ok,
        review_status=review_status,
        plan_status=plan_status,
        signals_count=0,
        data_quality_event_ids=list(data_quality_event_ids or []),
        invariant_violation_codes=list(invariant_violation_codes or []),
    )


def _next_open_date(db_path: Path, as_of_date: str) -> str | None:
    with connect(db_path) as conn:
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


def _child_context(
    ctx: RequestContext,
    request: RunDailyCloseWorkflowRequest,
    step: str,
) -> RequestContext:
    base_key = ctx.idempotency_key or (
        f"daily-close:{request.strategy_version}:{request.as_of_date}:"
        f"{request.account_id or request.account_key}"
    )
    return RequestContext(
        request_id=f"{ctx.request_id}:{step}" if ctx.request_id else None,
        idempotency_key=f"{base_key}:{step}",
        dry_run=ctx.dry_run,
        operator=ctx.operator,
        source=ctx.source,
    )


def _invariant_errors(report: InvariantReport) -> list[ServiceError]:
    return [
        ServiceError(
            code="DATABASE_INVARIANT_FAILED",
            message=f"{violation.code}: {violation.message}",
            severity="blocker",
        )
        for violation in report.violations
    ]


def _base_lineage(request: RunDailyCloseWorkflowRequest) -> dict[str, int | str | None]:
    return {
        "as_of_date": request.as_of_date,
        "strategy_version": request.strategy_version,
        "account_key": request.account_key,
        "account_id": request.account_id,
    }
