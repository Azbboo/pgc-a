"""Small response builders shared by API route adapters."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from pgc_trading import __version__
from pgc_trading.api.settings import ApiSettings
from pgc_trading.services.common import ServiceResult


def build_health_payload(settings: ApiSettings) -> dict[str, object]:
    """Build a stable, non-sensitive health response."""

    return {
        "status": "ok",
        "service": "pgc-trading-api",
        "api_version": __version__,
        "writes_enabled": settings.enable_writes,
        "database_configured": bool(settings.db_path),
    }


def service_result_envelope(result: ServiceResult[Any]) -> dict[str, object]:
    """Convert a service result into the common API response envelope."""

    return {
        "status": result.status,
        "request_id": result.request_id,
        "data": _jsonable(result.data),
        "created_ids": result.created_ids,
        "warnings": [_jsonable(warning) for warning in result.warnings],
        "errors": [_jsonable(error) for error in result.errors],
        "lineage": result.lineage,
    }


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value
