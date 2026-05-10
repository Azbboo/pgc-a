"""Route registration for the PGC HTTP API."""

import hmac
from datetime import datetime
from typing import Any

from pgc_trading.api.errors import service_result_http_status
from pgc_trading.api.schemas import build_health_payload, service_result_envelope
from pgc_trading.api.services import ApiServices
from pgc_trading.api.settings import ApiSettings
from pgc_trading.reporting.daily_report import (
    DailyReportRequest,
    DailyReviewHistoryRequest,
    ReviewTimelineRequest,
)
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult
from pgc_trading.services.data_quality_service import ListDataQualityEventsRequest
from pgc_trading.services.daily_close_workflow_service import (
    DEFAULT_ACCOUNT_KEY,
    RunDailyCloseWorkflowRequest,
)
from pgc_trading.services.execution_recording_service import (
    RecordPositionSellRequest,
    RecordTradeRequest,
)
from pgc_trading.services.market_review_service import (
    GetMarketReviewPlanContextRequest,
    GetMarketReviewRequest,
    ListMarketReviewExternalItemsRequest,
    ListMarketReviewHypothesesRequest,
    ListMarketReviewsRequest,
    ListMarketReviewSectorsRequest,
)
from pgc_trading.services.open_execution_service import OpenExecutionRequest
from pgc_trading.services.portfolio_planning_service import (
    CancelTradePlanRequest,
    GenerateBuyPlanRequest,
    ListTradePlansRequest,
    PublishTradePlanRequest,
)
from pgc_trading.services.position_lifecycle_service import EvaluateExitsRequest, ListPositionsRequest
from pgc_trading.strategies.cpb_6157 import STRATEGY_VERSION


def register_routes(app: Any) -> None:
    """Register P0 API routes on a FastAPI app instance."""

    from fastapi import Body, Request, Response

    @app.get("/api/health", tags=["system"])
    def health() -> dict[str, object]:
        return build_health_payload(app.state.settings)

    @app.get("/api/daily-reviews", tags=["reports"])
    def daily_review_history(
        response: Response,
        account_key: str | None = DEFAULT_ACCOUNT_KEY,
        account_id: int | None = None,
        strategy_version: str = STRATEGY_VERSION,
        before_date: str | None = None,
        limit: int = 20,
        request_id: str | None = None,
    ) -> dict[str, object]:
        return list_daily_reviews(
            app.state.settings,
            app.state.services,
            response,
            account_key=_blank_to_none(account_key),
            account_id=account_id,
            strategy_version=strategy_version,
            before_date=_normalize_optional_date(before_date),
            limit=limit,
            request_id=request_id,
        )

    @app.get("/api/review-timeline", tags=["reports"])
    def review_timeline(
        response: Response,
        account_key: str | None = DEFAULT_ACCOUNT_KEY,
        account_id: int | None = None,
        strategy_version: str = STRATEGY_VERSION,
        before_date: str | None = None,
        limit: int = 20,
        request_id: str | None = None,
    ) -> dict[str, object]:
        return list_review_timeline(
            app.state.settings,
            app.state.services,
            response,
            account_key=_blank_to_none(account_key),
            account_id=account_id,
            strategy_version=strategy_version,
            before_date=_normalize_optional_date(before_date),
            limit=limit,
            request_id=request_id,
        )

    @app.get("/api/daily-reviews/{as_of_date}", tags=["reports"])
    def daily_review(
        as_of_date: str,
        response: Response,
        account_key: str | None = DEFAULT_ACCOUNT_KEY,
        account_id: int | None = None,
        strategy_version: str = STRATEGY_VERSION,
        request_id: str | None = None,
    ) -> dict[str, object]:
        return get_daily_review(
            app.state.settings,
            app.state.services,
            response,
            as_of_date=as_of_date,
            account_key=_blank_to_none(account_key),
            account_id=account_id,
            strategy_version=strategy_version,
            request_id=request_id,
        )

    @app.get("/api/market-reviews", tags=["market-review"])
    def market_review_history(
        response: Response,
        limit: int = 20,
        request_id: str | None = None,
    ) -> dict[str, object]:
        return list_market_reviews(
            app.state.settings,
            app.state.services,
            response,
            limit=limit,
            request_id=request_id,
        )

    @app.get("/api/market-reviews/{as_of_date}", tags=["market-review"])
    def market_review_detail(
        as_of_date: str,
        response: Response,
        request_id: str | None = None,
    ) -> dict[str, object]:
        return get_market_review(
            app.state.settings,
            app.state.services,
            response,
            as_of_date=as_of_date,
            request_id=request_id,
        )

    @app.get("/api/market-reviews/{as_of_date}/sectors", tags=["market-review"])
    def market_review_sectors(
        as_of_date: str,
        response: Response,
        request_id: str | None = None,
    ) -> dict[str, object]:
        return list_market_review_sectors(
            app.state.settings,
            app.state.services,
            response,
            as_of_date=as_of_date,
            request_id=request_id,
        )

    @app.get("/api/market-reviews/{as_of_date}/external-items", tags=["market-review"])
    def market_review_external_items(
        as_of_date: str,
        response: Response,
        request_id: str | None = None,
    ) -> dict[str, object]:
        return list_market_review_external_items(
            app.state.settings,
            app.state.services,
            response,
            as_of_date=as_of_date,
            request_id=request_id,
        )

    @app.get("/api/market-reviews/{as_of_date}/hypotheses", tags=["market-review"])
    def market_review_hypotheses(
        as_of_date: str,
        response: Response,
        status: str | None = None,
        limit: int = 100,
        request_id: str | None = None,
    ) -> dict[str, object]:
        return list_market_review_hypotheses(
            app.state.settings,
            app.state.services,
            response,
            as_of_date=as_of_date,
            status=_blank_to_none(status),
            limit=limit,
            request_id=request_id,
        )

    @app.get("/api/market-reviews/{as_of_date}/plan-context", tags=["market-review"])
    def market_review_plan_context(
        as_of_date: str,
        response: Response,
        trade_plan_id: int | None = None,
        request_id: str | None = None,
    ) -> dict[str, object]:
        return get_market_review_plan_context(
            app.state.settings,
            app.state.services,
            response,
            as_of_date=as_of_date,
            trade_plan_id=trade_plan_id,
            request_id=request_id,
        )

    @app.get("/api/data-quality", tags=["data-quality"])
    def data_quality(
        response: Response,
        status: str | None = "open",
        severity: str | None = None,
        layer: str | None = None,
        trade_date: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        return list_data_quality_events(
            app.state.settings,
            app.state.services,
            response,
            status=_blank_to_none(status),
            severity=_blank_to_none(severity),
            layer=_blank_to_none(layer),
            trade_date=_normalize_optional_date(trade_date),
            limit=limit,
        )

    @app.get("/api/open-execution", tags=["portfolio"])
    def open_execution(
        as_of_date: str,
        response: Response,
        account_key: str | None = DEFAULT_ACCOUNT_KEY,
        account_id: int | None = None,
        request_id: str | None = None,
    ) -> dict[str, object]:
        return get_open_execution(
            app.state.settings,
            app.state.services,
            response,
            as_of_date=as_of_date,
            account_key=_blank_to_none(account_key),
            account_id=account_id,
            request_id=request_id,
        )

    @app.get("/api/accounts/{account_id}/positions", tags=["portfolio"])
    def account_positions(
        account_id: int,
        as_of_date: str,
        response: Response,
        request_id: str | None = None,
    ) -> dict[str, object]:
        return list_account_positions(
            app.state.settings,
            app.state.services,
            response,
            account_id=account_id,
            as_of_date=as_of_date,
            request_id=request_id,
        )

    @app.get("/api/trade-plans", tags=["portfolio"])
    def trade_plans(
        response: Response,
        account_key: str | None = None,
        account_id: int | None = None,
        status: str | None = None,
        action: str | None = None,
        as_of_date: str | None = None,
        planned_trade_date: str | None = None,
        limit: int = 100,
        request_id: str | None = None,
    ) -> dict[str, object]:
        return list_trade_plans(
            app.state.settings,
            app.state.services,
            response,
            account_key=_blank_to_none(account_key),
            account_id=account_id,
            status=_blank_to_none(status),
            action=_blank_to_none(action),
            as_of_date=_normalize_optional_date(as_of_date),
            planned_trade_date=_normalize_optional_date(planned_trade_date),
            limit=limit,
            request_id=request_id,
        )

    @app.post("/api/trade-plans/generate", tags=["portfolio"])
    def generate_trade_plan_route(
        request: Request,
        response: Response,
        payload: dict[str, Any] | None = Body(default=None),
    ) -> dict[str, object]:
        return generate_trade_plan(
            app.state.settings,
            app.state.services,
            response,
            payload=payload or {},
            write_token_header=_request_write_token(request),
        )

    @app.post("/api/review-runs", tags=["workflow"])
    def review_run(
        request: Request,
        response: Response,
        payload: dict[str, Any] | None = Body(default=None),
    ) -> dict[str, object]:
        return run_review_run(
            app.state.settings,
            app.state.services,
            response,
            payload=payload or {},
            write_token_header=_request_write_token(request),
        )

    @app.post("/api/trade-plans/{trade_plan_id}/publish", tags=["portfolio"])
    def publish_trade_plan(
        trade_plan_id: int,
        request: Request,
        response: Response,
        payload: dict[str, Any] | None = Body(default=None),
    ) -> dict[str, object]:
        return publish_plan(
            app.state.settings,
            app.state.services,
            response,
            trade_plan_id=trade_plan_id,
            payload=payload or {},
            write_token_header=_request_write_token(request),
        )

    @app.post("/api/trade-plans/{trade_plan_id}/cancel", tags=["portfolio"])
    def cancel_trade_plan(
        trade_plan_id: int,
        request: Request,
        response: Response,
        payload: dict[str, Any] | None = Body(default=None),
    ) -> dict[str, object]:
        return cancel_plan(
            app.state.settings,
            app.state.services,
            response,
            trade_plan_id=trade_plan_id,
            payload=payload or {},
            write_token_header=_request_write_token(request),
        )

    @app.post("/api/trades", tags=["portfolio"])
    def trade_execution(
        request: Request,
        response: Response,
        payload: dict[str, Any] | None = Body(default=None),
    ) -> dict[str, object]:
        return record_trade_execution(
            app.state.settings,
            app.state.services,
            response,
            payload=payload or {},
            write_token_header=_request_write_token(request),
        )

    @app.post("/api/exits/evaluate", tags=["portfolio"])
    def exit_evaluation(
        request: Request,
        response: Response,
        payload: dict[str, Any] | None = Body(default=None),
    ) -> dict[str, object]:
        return evaluate_exits(
            app.state.settings,
            app.state.services,
            response,
            payload=payload or {},
            write_token_header=_request_write_token(request),
        )


def get_daily_review(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    as_of_date: str,
    account_key: str | None = DEFAULT_ACCOUNT_KEY,
    account_id: int | None = None,
    strategy_version: str = STRATEGY_VERSION,
    request_id: str | None = None,
) -> dict[str, object]:
    service = services.report_service_factory(settings.db_path)
    result = service.get_daily_report(
        DailyReportRequest(
            as_of_date=_normalize_date(as_of_date),
            account_key=account_key,
            account_id=account_id,
            strategy_version=strategy_version,
        ),
        RequestContext(request_id=request_id, dry_run=True, source="api"),
    )
    return _service_response(result, response)


def list_daily_reviews(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    account_key: str | None = DEFAULT_ACCOUNT_KEY,
    account_id: int | None = None,
    strategy_version: str = STRATEGY_VERSION,
    before_date: str | None = None,
    limit: int = 20,
    request_id: str | None = None,
) -> dict[str, object]:
    service = services.report_service_factory(settings.db_path)
    result = service.list_daily_review_history(
        DailyReviewHistoryRequest(
            account_key=account_key,
            account_id=account_id,
            strategy_version=strategy_version,
            before_date=_normalize_optional_date(before_date),
            limit=limit,
        ),
        RequestContext(request_id=request_id, dry_run=True, source="api"),
    )
    return _service_response(result, response)


def list_review_timeline(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    account_key: str | None = DEFAULT_ACCOUNT_KEY,
    account_id: int | None = None,
    strategy_version: str = STRATEGY_VERSION,
    before_date: str | None = None,
    limit: int = 20,
    request_id: str | None = None,
) -> dict[str, object]:
    service = services.report_service_factory(settings.db_path)
    result = service.list_review_timeline(
        ReviewTimelineRequest(
            account_key=account_key,
            account_id=account_id,
            strategy_version=strategy_version,
            before_date=_normalize_optional_date(before_date),
            limit=limit,
        ),
        RequestContext(request_id=request_id, dry_run=True, source="api"),
    )
    return _service_response(result, response)


def list_market_reviews(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    limit: int = 20,
    request_id: str | None = None,
) -> dict[str, object]:
    service = services.market_review_service_factory(settings.db_path)
    result = service.list_market_reviews(
        ListMarketReviewsRequest(limit=limit),
        RequestContext(request_id=request_id, dry_run=True, source="api"),
    )
    return _service_response(result, response)


def get_market_review(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    as_of_date: str,
    request_id: str | None = None,
) -> dict[str, object]:
    normalized_date = _normalize_date(as_of_date)
    service = services.market_review_service_factory(settings.db_path)
    result = service.get_market_review(
        GetMarketReviewRequest(as_of_date=normalized_date),
        RequestContext(request_id=request_id, dry_run=True, source="api"),
    )
    return _service_response(result, response)


def list_market_review_sectors(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    as_of_date: str,
    request_id: str | None = None,
) -> dict[str, object]:
    normalized_date = _normalize_date(as_of_date)
    service = services.market_review_service_factory(settings.db_path)
    result = service.list_market_review_sectors(
        ListMarketReviewSectorsRequest(as_of_date=normalized_date),
        RequestContext(request_id=request_id, dry_run=True, source="api"),
    )
    return _service_response(result, response)


def list_market_review_external_items(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    as_of_date: str,
    request_id: str | None = None,
) -> dict[str, object]:
    normalized_date = _normalize_date(as_of_date)
    service = services.market_review_service_factory(settings.db_path)
    result = service.list_market_review_external_items(
        ListMarketReviewExternalItemsRequest(as_of_date=normalized_date),
        RequestContext(request_id=request_id, dry_run=True, source="api"),
    )
    return _service_response(result, response)


def list_market_review_hypotheses(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    as_of_date: str,
    status: str | None = None,
    limit: int = 100,
    request_id: str | None = None,
) -> dict[str, object]:
    normalized_date = _normalize_date(as_of_date)
    service = services.market_review_service_factory(settings.db_path)
    result = service.list_market_review_hypotheses(
        ListMarketReviewHypothesesRequest(as_of_date=normalized_date, status=status, limit=limit),
        RequestContext(request_id=request_id, dry_run=True, source="api"),
    )
    return _service_response(result, response)


def get_market_review_plan_context(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    as_of_date: str,
    trade_plan_id: int | None = None,
    request_id: str | None = None,
) -> dict[str, object]:
    normalized_date = _normalize_date(as_of_date)
    service = services.market_review_service_factory(settings.db_path)
    result = service.get_market_review_plan_context(
        GetMarketReviewPlanContextRequest(as_of_date=normalized_date, trade_plan_id=trade_plan_id),
        RequestContext(request_id=request_id, dry_run=True, source="api"),
    )
    return _service_response(result, response)


def list_data_quality_events(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    status: str | None = "open",
    severity: str | None = None,
    layer: str | None = None,
    trade_date: str | None = None,
    limit: int = 100,
) -> dict[str, object]:
    service = services.data_quality_service_factory(settings.db_path)
    result = service.list_events(
        ListDataQualityEventsRequest(
            status=status,
            severity=severity,
            layer=layer,
            trade_date=_normalize_optional_date(trade_date),
            limit=limit,
        )
    )
    return _service_response(result, response)


def get_open_execution(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    as_of_date: str,
    account_key: str | None = DEFAULT_ACCOUNT_KEY,
    account_id: int | None = None,
    request_id: str | None = None,
) -> dict[str, object]:
    normalized_date = _normalize_date(as_of_date)
    service = services.open_execution_service_factory(settings.db_path)
    result = service.get_open_execution(
        OpenExecutionRequest(
            as_of_date=normalized_date,
            account_key=account_key,
            account_id=account_id,
        ),
        RequestContext(request_id=request_id, dry_run=True, source="api"),
    )
    return _service_response(result, response)


def list_account_positions(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    account_id: int,
    as_of_date: str,
    request_id: str | None = None,
) -> dict[str, object]:
    service = services.position_lifecycle_service_factory(settings.db_path)
    result = service.list_positions(
        ListPositionsRequest(
            as_of_date=_normalize_date(as_of_date),
            account_key=None,
            account_id=account_id,
        ),
        RequestContext(request_id=request_id, dry_run=True, source="api"),
    )
    return _service_response(result, response)


def list_trade_plans(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    account_key: str | None = None,
    account_id: int | None = None,
    status: str | None = None,
    action: str | None = None,
    as_of_date: str | None = None,
    planned_trade_date: str | None = None,
    limit: int = 100,
    request_id: str | None = None,
) -> dict[str, object]:
    service = services.portfolio_planning_service_factory(settings.db_path)
    result = service.list_trade_plans(
        ListTradePlansRequest(
            account_key=account_key,
            account_id=account_id,
            status=status,
            action=action,
            as_of_date=_normalize_optional_date(as_of_date),
            planned_trade_date=_normalize_optional_date(planned_trade_date),
            limit=limit,
        ),
        RequestContext(request_id=request_id, dry_run=True, source="api"),
    )
    return _service_response(result, response)


def generate_trade_plan(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    payload: dict[str, Any],
    write_token_header: str | None = None,
) -> dict[str, object]:
    ctx_or_response = _write_context_or_response(
        settings,
        response,
        payload,
        allow_dry_run=True,
        write_token_header=write_token_header,
    )
    if isinstance(ctx_or_response, dict):
        return ctx_or_response
    ctx = ctx_or_response

    errors: list[ServiceError] = []
    daily_pick_id = _optional_int_field(payload, "daily_pick_id", errors)
    agent_decision_id = _optional_int_field(payload, "agent_decision_id", errors)
    account_id = _optional_int_field(payload, "account_id", errors)
    review_date = _normalize_optional_date(_optional_text(payload.get("review_date")))
    as_of_date = _normalize_optional_date(_optional_text(payload.get("as_of_date")))
    if review_date is not None and as_of_date is not None and review_date != as_of_date:
        errors.append(
            ServiceError(
                code="VALIDATION_ERROR",
                message="review_date and as_of_date must match when both are provided.",
            )
        )
    planned_trade_date = _normalize_optional_date(_optional_text(payload.get("planned_trade_date")))
    if errors:
        return _api_error_response(response, "validation_failed", ctx.request_id, errors)

    service = services.portfolio_planning_service_factory(settings.db_path)
    result = service.generate_buy_plan(
        GenerateBuyPlanRequest(
            account_key=_optional_text(payload.get("account_key")),
            account_id=account_id,
            daily_pick_id=daily_pick_id,
            review_date=review_date or as_of_date,
            planned_trade_date=planned_trade_date,
            agent_decision_id=agent_decision_id,
        ),
        ctx,
    )
    return _service_response(result, response)


def run_review_run(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    payload: dict[str, Any],
    write_token_header: str | None = None,
) -> dict[str, object]:
    ctx_or_response = _write_context_or_response(
        settings,
        response,
        payload,
        allow_dry_run=True,
        write_token_header=write_token_header,
    )
    if isinstance(ctx_or_response, dict):
        return ctx_or_response
    ctx = ctx_or_response

    errors: list[ServiceError] = []
    as_of_date = _required_date(payload, "as_of_date", errors)
    max_daily_picks = _int_field(payload, "max_daily_picks", errors, default=1)
    account_id = _optional_int_field(payload, "account_id", errors)
    force_new = _bool_field(payload, "force_new_review_run", errors, default=False)
    if errors:
        return _api_error_response(response, "validation_failed", ctx.request_id, errors)

    service = services.daily_close_workflow_service_factory(settings.db_path)
    result = service.run_daily_close(
        RunDailyCloseWorkflowRequest(
            as_of_date=as_of_date,
            strategy_version=_text_field(payload, "strategy_version", STRATEGY_VERSION),
            account_key=_optional_text(payload.get("account_key"), default=DEFAULT_ACCOUNT_KEY),
            account_id=account_id,
            max_daily_picks=max_daily_picks,
            run_type=_text_field(payload, "run_type", "paper"),
            force_new_review_run=force_new,
        ),
        ctx,
    )
    return _service_response(result, response)


def publish_plan(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    trade_plan_id: int,
    payload: dict[str, Any],
    write_token_header: str | None = None,
) -> dict[str, object]:
    ctx_or_response = _write_context_or_response(
        settings,
        response,
        payload,
        allow_dry_run=False,
        write_token_header=write_token_header,
    )
    if isinstance(ctx_or_response, dict):
        return ctx_or_response
    ctx = ctx_or_response

    errors = _account_selector_errors(payload)
    account_id = _optional_int_field(payload, "account_id", errors)
    if errors:
        return _api_error_response(response, "validation_failed", ctx.request_id, errors)

    service = services.portfolio_planning_service_factory(settings.db_path)
    result = service.publish_plan(
        PublishTradePlanRequest(
            trade_plan_id=trade_plan_id,
            account_key=_optional_text(payload.get("account_key")),
            account_id=account_id,
        ),
        ctx,
    )
    return _service_response(result, response)


def cancel_plan(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    trade_plan_id: int,
    payload: dict[str, Any],
    write_token_header: str | None = None,
) -> dict[str, object]:
    ctx_or_response = _write_context_or_response(
        settings,
        response,
        payload,
        allow_dry_run=False,
        write_token_header=write_token_header,
    )
    if isinstance(ctx_or_response, dict):
        return ctx_or_response
    ctx = ctx_or_response

    errors = _account_selector_errors(payload)
    account_id = _optional_int_field(payload, "account_id", errors)
    cancel_reason = _required_text(payload, "cancel_reason", errors)
    if errors:
        return _api_error_response(response, "validation_failed", ctx.request_id, errors)

    service = services.portfolio_planning_service_factory(settings.db_path)
    result = service.cancel_plan(
        CancelTradePlanRequest(
            trade_plan_id=trade_plan_id,
            cancel_reason=cancel_reason,
            account_key=_optional_text(payload.get("account_key")),
            account_id=account_id,
        ),
        ctx,
    )
    return _service_response(result, response)


def record_trade_execution(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    payload: dict[str, Any],
    write_token_header: str | None = None,
) -> dict[str, object]:
    ctx_or_response = _write_context_or_response(
        settings,
        response,
        payload,
        allow_dry_run=True,
        write_token_header=write_token_header,
    )
    if isinstance(ctx_or_response, dict):
        return ctx_or_response
    ctx = ctx_or_response

    errors: list[ServiceError] = []
    trade_plan_id = _optional_int_field(payload, "trade_plan_id", errors)
    position_id = _optional_int_field(payload, "position_id", errors)
    if trade_plan_id is not None and position_id is not None:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="Provide either trade_plan_id or position_id, not both."))

    executed_date = _required_date(payload, "executed_date", errors)
    executed_price = _float_field(payload, "executed_price", errors, required=True)
    shares = _int_field(payload, "shares", errors, required=True)
    account_id = _optional_int_field(payload, "account_id", errors)
    fee = _float_field(payload, "fee", errors, default=0.0)
    tax = _float_field(payload, "tax", errors, default=0.0)
    slippage = _optional_float_field(payload, "slippage", errors)
    if errors:
        return _api_error_response(response, "validation_failed", ctx.request_id, errors)

    service = services.execution_recording_service_factory(settings.db_path)
    if position_id is not None:
        result = service.record_position_sell(
            RecordPositionSellRequest(
                position_id=position_id,
                executed_date=executed_date,
                executed_price=executed_price,
                shares=shares,
                account_key=_optional_text(payload.get("account_key")),
                account_id=account_id,
                fee=fee,
                tax=tax,
                source=_trade_source(payload),
                slippage=slippage,
            ),
            ctx,
        )
        return _service_response(result, response)

    if trade_plan_id is None:
        return _api_error_response(
            response,
            "validation_failed",
            ctx.request_id,
            [ServiceError(code="VALIDATION_ERROR", message="trade_plan_id or position_id is required.")],
        )
    side = _required_text(payload, "side", errors)
    if errors:
        return _api_error_response(response, "validation_failed", ctx.request_id, errors)
    result = service.record_trade(
        RecordTradeRequest(
            trade_plan_id=trade_plan_id,
            side=side,
            executed_date=executed_date,
            executed_price=executed_price,
            shares=shares,
            account_key=_optional_text(payload.get("account_key")),
            account_id=account_id,
            fee=fee,
            tax=tax,
            source=_trade_source(payload),
            slippage=slippage,
        ),
        ctx,
    )
    return _service_response(result, response)


def evaluate_exits(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    payload: dict[str, Any],
    write_token_header: str | None = None,
) -> dict[str, object]:
    ctx_or_response = _write_context_or_response(
        settings,
        response,
        payload,
        allow_dry_run=True,
        write_token_header=write_token_header,
    )
    if isinstance(ctx_or_response, dict):
        return ctx_or_response
    ctx = ctx_or_response

    errors: list[ServiceError] = []
    as_of_date = _required_date(payload, "as_of_date", errors)
    account_id = _optional_int_field(payload, "account_id", errors)
    generate_sell_plans = _bool_field(payload, "generate_sell_plans", errors, default=True)
    if errors:
        return _api_error_response(response, "validation_failed", ctx.request_id, errors)

    service = services.position_lifecycle_service_factory(settings.db_path)
    result = service.evaluate_exits(
        EvaluateExitsRequest(
            as_of_date=as_of_date,
            account_key=_optional_text(payload.get("account_key"), default=DEFAULT_ACCOUNT_KEY),
            account_id=account_id,
            generate_sell_plans=generate_sell_plans,
        ),
        ctx,
    )
    return _service_response(result, response)


def _service_response(result: ServiceResult[object], response: Any) -> dict[str, object]:
    response.status_code = service_result_http_status(result)
    return service_result_envelope(result)


def _api_error_response(
    response: Any,
    status: str,
    request_id: str | None,
    errors: list[ServiceError],
) -> dict[str, object]:
    return _service_response(
        ServiceResult(status=status, request_id=request_id, errors=errors),
        response,
    )


def _write_context_or_response(
    settings: ApiSettings,
    response: Any,
    payload: dict[str, Any],
    *,
    allow_dry_run: bool,
    write_token_header: str | None = None,
) -> RequestContext | dict[str, object]:
    errors: list[ServiceError] = []
    dry_run = _bool_field(payload, "dry_run", errors, default=False)
    request_id = _optional_text(payload.get("request_id"))
    idempotency_key = _optional_text(payload.get("idempotency_key"))
    operator = _optional_text(payload.get("operator"))
    allow_live_writes = _bool_field(payload, "allow_live_writes", errors, default=False)

    if dry_run and not allow_dry_run:
        errors.append(ServiceError(code="DRY_RUN_NOT_SUPPORTED", message="dry_run is not supported for this endpoint."))
    if not dry_run and not settings.enable_writes:
        return _api_error_response(
            response,
            "forbidden",
            request_id,
            [
                ServiceError(
                    code="API_WRITES_DISABLED",
                    message="API writes are disabled. Set PGC_API_ENABLE_WRITES=1 to enable non-dry writes.",
                )
            ],
        )
    expected_write_token = _blank_to_none(settings.write_token)
    if not dry_run and expected_write_token is not None and not _write_token_matches(expected_write_token, write_token_header):
        return _api_error_response(
            response,
            "forbidden",
            request_id,
            [
                ServiceError(
                    code="API_WRITE_TOKEN_REQUIRED",
                    message="valid X-PGC-Write-Token is required for non-dry API writes",
                )
            ],
        )
    if not dry_run and operator is None:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="operator is required for non-dry API writes."))
    if not dry_run and idempotency_key is None:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="idempotency_key is required for non-dry API writes."))
    if errors:
        return _api_error_response(response, "validation_failed", request_id, errors)

    return RequestContext(
        request_id=request_id,
        idempotency_key=idempotency_key,
        dry_run=dry_run,
        operator=operator,
        source="api",
        allow_live_writes=allow_live_writes,
    )


def _request_write_token(request: Any) -> str | None:
    return request.headers.get("X-PGC-Write-Token")


def _write_token_matches(expected: str, candidate: str | None) -> bool:
    if candidate is None:
        return False
    return hmac.compare_digest(candidate, expected)


def _normalize_date(value: str) -> str:
    candidate = value.strip()
    if len(candidate) == 10:
        try:
            return datetime.strptime(candidate, "%Y-%m-%d").strftime("%Y%m%d")
        except ValueError:
            return candidate
    return candidate


def _normalize_optional_date(value: str | None) -> str | None:
    value = _blank_to_none(value)
    return _normalize_date(value) if value is not None else None


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _optional_text(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default
    if not isinstance(value, str):
        return str(value)
    return _blank_to_none(value)


def _text_field(payload: dict[str, Any], key: str, default: str) -> str:
    value = _optional_text(payload.get(key))
    return value if value is not None else default


def _trade_source(payload: dict[str, Any]) -> str:
    source = _text_field(payload, "source", "manual")
    if source == "dashboard":
        return "manual"
    return source


def _required_text(payload: dict[str, Any], key: str, errors: list[ServiceError]) -> str:
    value = _optional_text(payload.get(key))
    if value is None:
        errors.append(ServiceError(code="VALIDATION_ERROR", message=f"{key} is required."))
        return ""
    return value


def _required_date(payload: dict[str, Any], key: str, errors: list[ServiceError]) -> str:
    value = _required_text(payload, key, errors)
    return _normalize_date(value) if value else value


def _bool_field(payload: dict[str, Any], key: str, errors: list[ServiceError], *, default: bool) -> bool:
    value = payload.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    errors.append(ServiceError(code="VALIDATION_ERROR", message=f"{key} must be a boolean."))
    return default


def _int_field(
    payload: dict[str, Any],
    key: str,
    errors: list[ServiceError],
    *,
    required: bool = False,
    default: int = 0,
) -> int:
    value = payload.get(key)
    if value is None:
        if required:
            errors.append(ServiceError(code="VALIDATION_ERROR", message=f"{key} is required."))
        return default
    if isinstance(value, bool):
        errors.append(ServiceError(code="VALIDATION_ERROR", message=f"{key} must be an integer."))
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        errors.append(ServiceError(code="VALIDATION_ERROR", message=f"{key} must be an integer."))
        return default


def _optional_int_field(payload: dict[str, Any], key: str, errors: list[ServiceError]) -> int | None:
    if payload.get(key) is None:
        return None
    return _int_field(payload, key, errors)


def _float_field(
    payload: dict[str, Any],
    key: str,
    errors: list[ServiceError],
    *,
    required: bool = False,
    default: float = 0.0,
) -> float:
    value = payload.get(key)
    if value is None:
        if required:
            errors.append(ServiceError(code="VALIDATION_ERROR", message=f"{key} is required."))
        return default
    if isinstance(value, bool):
        errors.append(ServiceError(code="VALIDATION_ERROR", message=f"{key} must be a number."))
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append(ServiceError(code="VALIDATION_ERROR", message=f"{key} must be a number."))
        return default


def _optional_float_field(payload: dict[str, Any], key: str, errors: list[ServiceError]) -> float | None:
    if payload.get(key) is None:
        return None
    return _float_field(payload, key, errors)


def _account_selector_errors(payload: dict[str, Any]) -> list[ServiceError]:
    if _optional_text(payload.get("account_key")) is None and payload.get("account_id") is None:
        return [ServiceError(code="VALIDATION_ERROR", message="account_key or account_id is required.")]
    return []
