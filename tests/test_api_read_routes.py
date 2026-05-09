from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pgc_trading.api.routes import (
    get_daily_review,
    get_open_execution,
    get_market_review,
    get_market_review_plan_context,
    list_account_positions,
    list_data_quality_events,
    list_daily_reviews,
    list_market_review_external_items,
    list_market_review_hypotheses,
    list_market_review_sectors,
    list_market_reviews,
    list_trade_plans,
)
from pgc_trading.api.services import ApiServices
from pgc_trading.api.settings import ApiSettings
from pgc_trading.services.common import ServiceError, ServiceResult
from pgc_trading.storage.migrate import run_migrations


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

    def list_daily_review_history(self, request, ctx):
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data={
                "strategy_version": request.strategy_version,
                "account_id": request.account_id,
                "before_date": request.before_date,
                "limit": request.limit,
            },
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


class _FakeMarketReviewReadService:
    calls: list[tuple[str, Path, object, object]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def list_market_reviews(self, request, ctx):
        return self._result("list_market_reviews", request, ctx, {"limit": request.limit})

    def get_market_review(self, request, ctx):
        return self._result("get_market_review", request, ctx, {"as_of_date": request.as_of_date})

    def list_market_review_sectors(self, request, ctx):
        return self._result("list_market_review_sectors", request, ctx, {"as_of_date": request.as_of_date})

    def list_market_review_external_items(self, request, ctx):
        return self._result("list_market_review_external_items", request, ctx, {"as_of_date": request.as_of_date})

    def list_market_review_hypotheses(self, request, ctx):
        return self._result(
            "list_market_review_hypotheses",
            request,
            ctx,
            {"as_of_date": request.as_of_date, "status": request.status, "limit": request.limit},
        )

    def get_market_review_plan_context(self, request, ctx):
        return self._result(
            "get_market_review_plan_context",
            request,
            ctx,
            {"as_of_date": request.as_of_date, "trade_plan_id": request.trade_plan_id},
        )

    def _result(self, method: str, request, ctx, data: dict[str, object]):
        self.calls.append((method, self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data={
                "method": method,
                **data,
                "source": {"tables": ["market_review_runs"]},
                "coverage": {"has_review": True},
                "missing_data": [],
            },
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


class _FakeOpenExecutionService:
    calls: list[tuple[Path, object, object]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def get_open_execution(self, request, ctx):
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data={
                "as_of_date": request.as_of_date,
                "account_key": request.account_key,
                "account_id": request.account_id,
                "next_action": "record_buy",
                "market_plan_context": {
                    "alignment": "aligned",
                    "risk_level": "medium",
                    "management_action": "manual_review",
                },
            },
            lineage={"as_of_date": request.as_of_date},
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
        _FakeMarketReviewReadService.calls = []
        _FakeOpenExecutionService.calls = []
        _FakePositionService.calls = []
        _FakePortfolioService.calls = []
        self.settings = ApiSettings(db_path=Path("/tmp/api-read-routes.db"))
        self.services = ApiServices(
            report_service_factory=_FakeReportService,
            data_quality_service_factory=_FakeDataQualityService,
            market_review_service_factory=_FakeMarketReviewReadService,
            open_execution_service_factory=_FakeOpenExecutionService,
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

    def test_daily_review_history_route_passes_filters_to_reporting_service(self) -> None:
        response = _Response()

        payload = list_daily_reviews(
            self.settings,
            self.services,
            response,
            account_key=None,
            account_id=3,
            strategy_version="cpb_6157@2026-05-03",
            before_date="2026-05-07",
            limit=12,
            request_id="req-review-history",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["data"]["before_date"], "20260507")
        self.assertEqual(payload["data"]["limit"], 12)
        _, request, ctx = _FakeReportService.calls[0]
        self.assertEqual(request.account_id, 3)
        self.assertEqual(request.account_key, None)
        self.assertEqual(request.strategy_version, "cpb_6157@2026-05-03")
        self.assertEqual(request.before_date, "20260507")
        self.assertEqual(request.limit, 12)
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.source, "api")

    def test_market_reviews_route_calls_read_service_with_api_context(self) -> None:
        response = _Response()

        payload = list_market_reviews(
            self.settings,
            self.services,
            response,
            limit=7,
            request_id="req-market-list",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["data"]["limit"], 7)
        method, db_path, request, ctx = _FakeMarketReviewReadService.calls[0]
        self.assertEqual(method, "list_market_reviews")
        self.assertEqual(db_path, self.settings.db_path)
        self.assertEqual(request.limit, 7)
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.source, "api")
        self.assertEqual(ctx.request_id, "req-market-list")

    def test_market_review_child_routes_normalize_dates_and_pass_filters(self) -> None:
        response = _Response()

        get_market_review(self.settings, self.services, response, as_of_date="2026-05-08")
        list_market_review_sectors(self.settings, self.services, response, as_of_date="2026-05-08")
        list_market_review_external_items(self.settings, self.services, response, as_of_date="2026-05-08")
        list_market_review_hypotheses(
            self.settings,
            self.services,
            response,
            as_of_date="2026-05-08",
            status="testing",
            limit=2,
        )
        payload = get_market_review_plan_context(
            self.settings,
            self.services,
            response,
            as_of_date="2026-05-08",
            trade_plan_id=2,
            request_id="req-plan-context",
        )

        self.assertEqual(payload["data"]["trade_plan_id"], 2)
        calls = {method: (request, ctx) for method, _, request, ctx in _FakeMarketReviewReadService.calls}
        for method in (
            "get_market_review",
            "list_market_review_sectors",
            "list_market_review_external_items",
            "list_market_review_hypotheses",
            "get_market_review_plan_context",
        ):
            self.assertEqual(calls[method][0].as_of_date, "20260508")
            self.assertTrue(calls[method][1].dry_run)
            self.assertEqual(calls[method][1].source, "api")
        self.assertEqual(calls["list_market_review_hypotheses"][0].status, "testing")
        self.assertEqual(calls["list_market_review_hypotheses"][0].limit, 2)
        self.assertEqual(calls["get_market_review_plan_context"][0].trade_plan_id, 2)
        self.assertEqual(calls["get_market_review_plan_context"][1].request_id, "req-plan-context")

    def test_market_review_detail_returns_stable_empty_state_when_no_review_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)
            response = _Response()

            payload = get_market_review(
                ApiSettings(db_path=db_path),
                ApiServices(),
                response,
                as_of_date="2026-05-08",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "success")
        self.assertFalse(payload["data"]["exists"])
        self.assertEqual(payload["data"]["status"], "missing")
        self.assertEqual(payload["data"]["as_of_date"], "20260508")
        self.assertIn("source", payload["data"])
        self.assertIn("coverage", payload["data"])
        self.assertIn("missing_data", payload["data"])
        self.assertIn("market_review_runs", payload["data"]["missing_data"])
        self.assertFalse(payload["data"]["coverage"]["has_review"])

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

    def test_open_execution_route_normalizes_date_and_returns_market_context(self) -> None:
        response = _Response()

        payload = get_open_execution(
            self.settings,
            self.services,
            response,
            as_of_date="2026-05-11",
            account_key="paper-main",
            account_id=None,
            request_id="req-open-execution",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["data"]["next_action"], "record_buy")
        self.assertEqual(payload["data"]["market_plan_context"]["management_action"], "manual_review")
        db_path, request, ctx = _FakeOpenExecutionService.calls[0]
        self.assertEqual(db_path, self.settings.db_path)
        self.assertEqual(request.as_of_date, "20260511")
        self.assertEqual(request.account_key, "paper-main")
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.source, "api")
        self.assertEqual(ctx.request_id, "req-open-execution")

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
