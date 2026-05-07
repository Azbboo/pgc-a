"""HTTP mapping helpers for service-layer results."""

from __future__ import annotations

from pgc_trading.services.common import ServiceResult


_HTTP_STATUS_BY_RESULT_STATUS = {
    "success": 200,
    "partial_success": 207,
    "skipped": 200,
    "validation_failed": 400,
    "blocked": 409,
    "failed": 500,
}


def service_result_http_status(result: ServiceResult[object]) -> int:
    """Map a service result status to an HTTP response code."""

    return _HTTP_STATUS_BY_RESULT_STATUS.get(result.status, 500)
