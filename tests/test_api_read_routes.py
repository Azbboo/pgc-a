from __future__ import annotations

import unittest
from pathlib import Path

from pgc_trading.api.routes import (
    get_daily_review,
    list_account_positions,
    list_data_quality_events,
    list_trade_plans,
)
from pgc_trading.api.services import ApiServices
from pgc_trading.api.settings import ApiSettings
from pgc_trading.services.common import ServiceError, ServiceResult


class _Response:
    status_code = 200


class _FakeReportService:
    calls: list[tuple[Path, object, object]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def get_daily_report(self, request, ctx):
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data={"as_of_date": request.as_of_date, "account_id": request.account_id},
            lineage={"account_id": request.account_id},
        )


class _FakeDataQualityService:
    calls: list[tuple[Path, object]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def list_events(self, request):
        self.calls.append((self.db_path, request))
        return ServiceResult(
            status="success",
            request_id=None,
            data=[{"id": 7, "severity": request.severity, "trade_date": request.trade_date}],
        )


class _FakePositionService:
    calls: list[tuple[Path, object, object]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def list_positions(self, request, ctx):
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data={"as_of_date": request.as_of_date, "account_id": request.account_id, "positions": []},
            lineage={"account_id": request.account_id},
        )


class _FakePortfolioService:
    calls: list[tuple[Path, object, object]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def list_trade_plans(self, request, ctx):
        self.calls.append((self.db_path, request, ctx))
        if request.account_id is None and request.account_key is None:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                errors=[ServiceError(code="VALIDATION_ERROR", message="account_key or account_id is required.")],
            )
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data={"account_id": request.account_id, "trade_plans": []},
            lineage={"account_id": request.account_id},
        )


class ApiReadRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        _FakeReportService.calls = []
        _FakeDataQualityService.calls = []
        _FakePositionService.calls = []
        _FakePortfolioService.calls = []
        self.settings = ApiSettings(db_path=Path("/tmp/api-read-routes.db"))
        self.services = ApiServices(
            report_service_factory=_FakeReportService,
            data_quality_service_factory=_FakeDataQualityService,
            portfolio_planning_service_factory=_FakePortfolioService,
            position_lifecycle_service_factory=_FakePositionService,
        )

    def test_daily_review_route_normalizes_date_and_uses_api_context(self) -> None:
        response = _Response()

        payload = get_daily_review(
            self.settings,
            self.services,
            response,
            as_of_date="2026-05-04",
            account_key=None,
            account_id=3,
            request_id="req-api-read",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["data"], {"as_of_date": "20260504", "account_id": 3})
        db_path, request, ctx = _FakeReportService.calls[0]
        self.assertEqual(db_path, self.settings.db_path)
        self.assertEqual(request.as_of_date, "20260504")
        self.assertEqual(request.account_id, 3)
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.source, "api")

    def test_data_quality_route_passes_read_filters(self) -> None:
        response = _Response()

        payload = list_data_quality_events(
            self.settings,
            self.services,
            response,
            status="open",
            severity="blocker",
            layer="market",
            trade_date="2026-05-04",
            limit=25,
        )

        self.assertEqual(payload["data"], [{"id": 7, "severity": "blocker", "trade_date": "20260504"}])
        _, request = _FakeDataQualityService.calls[0]
        self.assertEqual(request.status, "open")
        self.assertEqual(request.severity, "blocker")
        self.assertEqual(request.layer, "market")
        self.assertEqual(request.trade_date, "20260504")
        self.assertEqual(request.limit, 25)

    def test_positions_route_uses_explicit_path_account_id(self) -> None:
        response = _Response()

        payload = list_account_positions(
            self.settings,
            self.services,
            response,
            account_id=9,
            as_of_date="20260507",
            request_id="req-positions",
        )

        self.assertEqual(payload["data"]["account_id"], 9)
        _, request, ctx = _FakePositionService.calls[0]
        self.assertEqual(request.account_id, 9)
        self.assertIsNone(request.account_key)
        self.assertEqual(request.as_of_date, "20260507")
        self.assertEqual(ctx.source, "api")

    def test_trade_plans_route_calls_service_read_method(self) -> None:
        response = _Response()

        payload = list_trade_plans(
            self.settings,
            self.services,
            response,
            account_id=11,
            status="active",
            action="buy_next_open",
            as_of_date="2026-05-04",
            planned_trade_date="2026-05-05",
            limit=10,
            request_id="req-plans",
        )

        self.assertEqual(payload["status"], "success")
        _, request, ctx = _FakePortfolioService.calls[0]
        self.assertEqual(request.account_id, 11)
        self.assertEqual(request.status, "active")
        self.assertEqual(request.action, "buy_next_open")
        self.assertEqual(request.as_of_date, "20260504")
        self.assertEqual(request.planned_trade_date, "20260505")
        self.assertEqual(request.limit, 10)
        self.assertEqual(ctx.source, "api")

    def test_trade_plans_route_preserves_validation_status(self) -> None:
        response = _Response()

        payload = list_trade_plans(self.settings, self.services, response)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["status"], "validation_failed")
        self.assertEqual(payload["errors"][0]["code"], "VALIDATION_ERROR")


if __name__ == "__main__":
    unittest.main()
