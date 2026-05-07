"""Route registration for the PGC HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgc_trading.api.errors import service_result_http_status
from pgc_trading.api.schemas import build_health_payload, service_result_envelope
from pgc_trading.api.services import ApiServices
from pgc_trading.api.settings import ApiSettings
from pgc_trading.reporting.daily_report import DailyReportRequest
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
from pgc_trading.services.portfolio_planning_service import (
    CancelTradePlanRequest,
    ListTradePlansRequest,
    PublishTradePlanRequest,
)
from pgc_trading.services.position_lifecycle_service import EvaluateExitsRequest, ListPositionsRequest
from pgc_trading.strategies.cpb_6157 import STRATEGY_VERSION


def register_routes(app: Any) -> None:
    """Register P0 API routes on a FastAPI app instance."""

    from fastapi import Body, Response

    @app.get("/api/health", tags=["system"])
    def health() -> dict[str, object]:
        return build_health_payload(app.state.settings)

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

    @app.post("/api/review-runs", tags=["workflow"])
    def review_run(
        response: Response,
        payload: dict[str, Any] | None = Body(default=None),
    ) -> dict[str, object]:
        return run_review_run(app.state.settings, app.state.services, response, payload=payload or {})

    @app.post("/api/trade-plans/{trade_plan_id}/publish", tags=["portfolio"])
    def publish_trade_plan(
        trade_plan_id: int,
        response: Response,
        payload: dict[str, Any] | None = Body(default=None),
    ) -> dict[str, object]:
        return publish_plan(
            app.state.settings,
            app.state.services,
            response,
            trade_plan_id=trade_plan_id,
            payload=payload or {},
        )

    @app.post("/api/trade-plans/{trade_plan_id}/cancel", tags=["portfolio"])
    def cancel_trade_plan(
        trade_plan_id: int,
        response: Response,
        payload: dict[str, Any] | None = Body(default=None),
    ) -> dict[str, object]:
        return cancel_plan(
            app.state.settings,
            app.state.services,
            response,
            trade_plan_id=trade_plan_id,
            payload=payload or {},
        )

    @app.post("/api/trades", tags=["portfolio"])
    def trade_execution(
        response: Response,
        payload: dict[str, Any] | None = Body(default=None),
    ) -> dict[str, object]:
        return record_trade_execution(app.state.settings, app.state.services, response, payload=payload or {})

    @app.post("/api/exits/evaluate", tags=["portfolio"])
    def exit_evaluation(
        response: Response,
        payload: dict[str, Any] | None = Body(default=None),
    ) -> dict[str, object]:
        return evaluate_exits(app.state.settings, app.state.services, response, payload=payload or {})


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


def run_review_run(
    settings: ApiSettings,
    services: ApiServices,
    response: Any,
    *,
    payload: dict[str, Any],
) -> dict[str, object]:
    ctx_or_response = _write_context_or_response(settings, response, payload, allow_dry_run=True)
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
) -> dict[str, object]:
    ctx_or_response = _write_context_or_response(settings, response, payload, allow_dry_run=False)
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
) -> dict[str, object]:
    ctx_or_response = _write_context_or_response(settings, response, payload, allow_dry_run=False)
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
) -> dict[str, object]:
    ctx_or_response = _write_context_or_response(settings, response, payload, allow_dry_run=True)
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
                source=_text_field(payload, "source", "manual"),
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
            source=_text_field(payload, "source", "manual"),
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
) -> dict[str, object]:
    ctx_or_response = _write_context_or_response(settings, response, payload, allow_dry_run=True)
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
) -> RequestContext | dict[str, object]:
    errors: list[ServiceError] = []
    dry_run = _bool_field(payload, "dry_run", errors, default=False)
    request_id = _optional_text(payload.get("request_id"))
    idempotency_key = _optional_text(payload.get("idempotency_key"))
    operator = _optional_text(payload.get("operator"))

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
    )


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
