"""Route registration for the PGC HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgc_trading.api.errors import service_result_http_status
from pgc_trading.api.schemas import build_health_payload, service_result_envelope
from pgc_trading.api.services import ApiServices
from pgc_trading.api.settings import ApiSettings
from pgc_trading.reporting.daily_report import DailyReportRequest
from pgc_trading.services.common import RequestContext, ServiceResult
from pgc_trading.services.data_quality_service import ListDataQualityEventsRequest
from pgc_trading.services.daily_close_workflow_service import DEFAULT_ACCOUNT_KEY
from pgc_trading.services.portfolio_planning_service import ListTradePlansRequest
from pgc_trading.services.position_lifecycle_service import ListPositionsRequest
from pgc_trading.strategies.cpb_6157 import STRATEGY_VERSION


def register_routes(app: Any) -> None:
    """Register P0 API routes on a FastAPI app instance."""

    from fastapi import Response

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


def _service_response(result: ServiceResult[object], response: Any) -> dict[str, object]:
    response.status_code = service_result_http_status(result)
    return service_result_envelope(result)


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
