from __future__ import annotations

import unittest
from pathlib import Path

from pgc_trading.api.routes import (
    cancel_plan,
    evaluate_exits,
    generate_trade_plan,
    publish_plan,
    record_trade_execution,
    run_review_run,
)
from pgc_trading.api.services import ApiServices
from pgc_trading.api.settings import ApiSettings
from pgc_trading.services.common import ServiceError, ServiceResult


class _Response:
    status_code = 200


class _FakeWorkflowService:
    calls: list[tuple[Path, object, object]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def run_daily_close(self, request, ctx):
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data={"as_of_date": request.as_of_date, "dry_run": ctx.dry_run},
        )


class _FakePortfolioService:
    calls: list[tuple[str, Path, object, object]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def generate_buy_plan(self, request, ctx):
        self.calls.append(("generate_buy", self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data={
                "trade_plan_id": None if ctx.dry_run else 77,
                "action": "buy_next_open",
                "status": "active",
                "reason": "daily_pick",
                "planned_trade_date": request.planned_trade_date or request.review_date,
                "planned_cash": 66666.67,
                "planned_shares": 6600,
                "free_position_slots": 3,
            },
        )

    def publish_plan(self, request, ctx):
        self.calls.append(("publish", self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data={"trade_plan_id": request.trade_plan_id, "status": "active"},
            created_ids={"trade_plan_id": request.trade_plan_id},
        )

    def cancel_plan(self, request, ctx):
        self.calls.append(("cancel", self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data={
                "trade_plan_id": request.trade_plan_id,
                "status": "cancelled",
                "cancel_reason": request.cancel_reason,
            },
            created_ids={"trade_plan_id": request.trade_plan_id},
        )


class _FakeExecutionService:
    calls: list[tuple[str, Path, object, object]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def record_trade(self, request, ctx):
        self.calls.append(("trade_plan", self.db_path, request, ctx))
        if request.trade_plan_id == 99:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                errors=[
                    ServiceError(
                        code="ACCOUNT_MISMATCH",
                        message="Trade plan belongs to a different account.",
                    )
                ],
            )
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data={"trade_plan_id": request.trade_plan_id, "side": request.side},
        )

    def record_position_sell(self, request, ctx):
        self.calls.append(("position_sell", self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data={"position_id": request.position_id, "side": "sell"},
        )


class _FakePositionService:
    calls: list[tuple[Path, object, object]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def evaluate_exits(self, request, ctx):
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data={
                "as_of_date": request.as_of_date,
                "generate_sell_plans": request.generate_sell_plans,
            },
        )


class ApiWriteRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        _FakeWorkflowService.calls = []
        _FakePortfolioService.calls = []
        _FakeExecutionService.calls = []
        _FakePositionService.calls = []
        self.disabled = ApiSettings(db_path=Path("/tmp/api-write-routes.db"), enable_writes=False)
        self.enabled = ApiSettings(db_path=Path("/tmp/api-write-routes.db"), enable_writes=True)
        self.services = ApiServices(
            daily_close_workflow_service_factory=_FakeWorkflowService,
            execution_recording_service_factory=_FakeExecutionService,
            portfolio_planning_service_factory=_FakePortfolioService,
            position_lifecycle_service_factory=_FakePositionService,
        )

    def test_non_dry_write_is_rejected_when_writes_disabled(self) -> None:
        response = _Response()

        payload = run_review_run(
            self.disabled,
            self.services,
            response,
            payload={
                "as_of_date": "2026-05-04",
                "operator": "tester",
                "idempotency_key": "api:review:1",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(payload["status"], "forbidden")
        self.assertEqual(payload["errors"][0]["code"], "API_WRITES_DISABLED")
        self.assertEqual(_FakeWorkflowService.calls, [])

    def test_dry_run_review_is_allowed_when_writes_disabled(self) -> None:
        response = _Response()

        payload = run_review_run(
            self.disabled,
            self.services,
            response,
            payload={"as_of_date": "2026-05-04", "account_id": 3, "dry_run": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["data"], {"as_of_date": "20260504", "dry_run": True})
        _, request, ctx = _FakeWorkflowService.calls[0]
        self.assertEqual(request.as_of_date, "20260504")
        self.assertEqual(request.account_id, 3)
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.source, "api")
        self.assertIsNone(ctx.operator)
        self.assertIsNone(ctx.idempotency_key)

    def test_live_dry_run_review_is_routed_without_write_enablement(self) -> None:
        response = _Response()

        payload = run_review_run(
            self.disabled,
            self.services,
            response,
            payload={
                "as_of_date": "2026-05-04",
                "account_key": "live-main",
                "run_type": "live",
                "dry_run": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["data"], {"as_of_date": "20260504", "dry_run": True})
        _, request, ctx = _FakeWorkflowService.calls[0]
        self.assertEqual(request.account_key, "live-main")
        self.assertEqual(request.run_type, "live")
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.source, "api")

    def test_non_dry_write_requires_operator_and_idempotency_key(self) -> None:
        response = _Response()

        payload = evaluate_exits(
            self.enabled,
            self.services,
            response,
            payload={"as_of_date": "20260507"},
        )

        self.assertEqual(response.status_code, 400)
        messages = [error["message"] for error in payload["errors"]]
        self.assertIn("operator is required for non-dry API writes.", messages)
        self.assertIn("idempotency_key is required for non-dry API writes.", messages)
        self.assertEqual(_FakePositionService.calls, [])

    def test_publish_requires_account_selector_and_rejects_dry_run(self) -> None:
        response = _Response()

        dry_run_payload = publish_plan(
            self.enabled,
            self.services,
            response,
            trade_plan_id=42,
            payload={"dry_run": True},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(dry_run_payload["errors"][0]["code"], "DRY_RUN_NOT_SUPPORTED")

        response = _Response()
        missing_account = publish_plan(
            self.enabled,
            self.services,
            response,
            trade_plan_id=42,
            payload={"operator": "tester", "idempotency_key": "api:publish:1"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(missing_account["errors"][0]["message"], "account_key or account_id is required.")
        self.assertEqual(_FakePortfolioService.calls, [])

    def test_generate_trade_plan_routes_dry_run_with_review_date_alias(self) -> None:
        response = _Response()

        payload = generate_trade_plan(
            self.disabled,
            self.services,
            response,
            payload={
                "account_key": "paper-main",
                "daily_pick_id": 11,
                "as_of_date": "2026-05-04",
                "planned_trade_date": "2026-05-05",
                "agent_decision_id": 21,
                "dry_run": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["data"]["trade_plan_id"], None)
        self.assertEqual(payload["data"]["planned_trade_date"], "20260505")
        call = _FakePortfolioService.calls[0]
        self.assertEqual(call[0], "generate_buy")
        self.assertEqual(call[2].account_key, "paper-main")
        self.assertEqual(call[2].daily_pick_id, 11)
        self.assertEqual(call[2].review_date, "20260504")
        self.assertEqual(call[2].planned_trade_date, "20260505")
        self.assertEqual(call[2].agent_decision_id, 21)
        self.assertTrue(call[3].dry_run)
        self.assertEqual(call[3].source, "api")
        self.assertIsNone(call[3].operator)
        self.assertIsNone(call[3].idempotency_key)

    def test_generate_trade_plan_requires_operator_and_idempotency_for_non_dry(self) -> None:
        response = _Response()

        payload = generate_trade_plan(
            self.enabled,
            self.services,
            response,
            payload={
                "account_id": 3,
                "review_date": "2026-05-04",
            },
        )

        self.assertEqual(response.status_code, 400)
        messages = [error["message"] for error in payload["errors"]]
        self.assertIn("operator is required for non-dry API writes.", messages)
        self.assertIn("idempotency_key is required for non-dry API writes.", messages)
        self.assertEqual(_FakePortfolioService.calls, [])

    def test_generate_trade_plan_passes_write_context_to_service(self) -> None:
        response = _Response()

        payload = generate_trade_plan(
            self.enabled,
            self.services,
            response,
            payload={
                "account_key": "paper-main",
                "daily_pick_id": 11,
                "review_date": "2026-05-04",
                "planned_trade_date": "2026-05-05",
                "operator": "tester",
                "idempotency_key": "api:plan:11",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["data"]["trade_plan_id"], 77)
        self.assertEqual(payload["data"]["action"], "buy_next_open")
        call = _FakePortfolioService.calls[0]
        self.assertEqual(call[0], "generate_buy")
        self.assertEqual(call[2].review_date, "20260504")
        self.assertEqual(call[2].planned_trade_date, "20260505")
        self.assertEqual(call[3].operator, "tester")
        self.assertEqual(call[3].idempotency_key, "api:plan:11")
        self.assertFalse(call[3].dry_run)

    def test_publish_and_cancel_pass_write_context_to_service(self) -> None:
        publish_response = _Response()
        cancel_response = _Response()

        publish_plan(
            self.enabled,
            self.services,
            publish_response,
            trade_plan_id=42,
            payload={
                "account_key": "paper-main",
                "operator": "tester",
                "idempotency_key": "api:publish:42",
            },
        )
        cancel_plan(
            self.enabled,
            self.services,
            cancel_response,
            trade_plan_id=42,
            payload={
                "account_id": 1,
                "cancel_reason": "manual override",
                "operator": "tester",
                "idempotency_key": "api:cancel:42",
            },
        )

        self.assertEqual(publish_response.status_code, 200)
        self.assertEqual(cancel_response.status_code, 200)
        publish_call, cancel_call = _FakePortfolioService.calls
        self.assertEqual(publish_call[0], "publish")
        self.assertEqual(publish_call[2].account_key, "paper-main")
        self.assertEqual(publish_call[3].source, "api")
        self.assertEqual(publish_call[3].idempotency_key, "api:publish:42")
        self.assertEqual(cancel_call[0], "cancel")
        self.assertEqual(cancel_call[2].account_id, 1)
        self.assertEqual(cancel_call[2].cancel_reason, "manual override")
        self.assertEqual(cancel_call[3].operator, "tester")

    def test_trade_endpoint_records_by_plan_or_direct_position_sell(self) -> None:
        plan_response = _Response()
        position_response = _Response()

        record_trade_execution(
            self.enabled,
            self.services,
            plan_response,
            payload={
                "trade_plan_id": 7,
                "side": "buy",
                "executed_date": "2026-05-05",
                "executed_price": 10.5,
                "shares": 1000,
                "account_key": "paper-main",
                "operator": "tester",
                "idempotency_key": "api:trade:7",
            },
        )
        record_trade_execution(
            self.enabled,
            self.services,
            position_response,
            payload={
                "position_id": 8,
                "executed_date": "2026-05-07",
                "executed_price": "10.9",
                "shares": "1000",
                "account_id": 1,
                "operator": "tester",
                "idempotency_key": "api:position-sell:8",
            },
        )

        plan_call, position_call = _FakeExecutionService.calls
        self.assertEqual(plan_call[0], "trade_plan")
        self.assertEqual(plan_call[2].executed_date, "20260505")
        self.assertEqual(plan_call[2].side, "buy")
        self.assertEqual(plan_call[3].source, "api")
        self.assertEqual(plan_call[3].idempotency_key, "api:trade:7")
        self.assertEqual(position_call[0], "position_sell")
        self.assertEqual(position_call[2].position_id, 8)
        self.assertEqual(position_call[2].executed_date, "20260507")
        self.assertEqual(position_call[2].account_id, 1)

    def test_trade_endpoint_preserves_service_error_codes(self) -> None:
        response = _Response()

        payload = record_trade_execution(
            self.enabled,
            self.services,
            response,
            payload={
                "trade_plan_id": 99,
                "side": "buy",
                "executed_date": "20260505",
                "executed_price": 10.5,
                "shares": 1000,
                "account_key": "paper-main",
                "operator": "tester",
                "idempotency_key": "api:trade:account-mismatch",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["errors"][0]["code"], "ACCOUNT_MISMATCH")

    def test_exits_evaluate_passes_generate_sell_plans_and_context(self) -> None:
        response = _Response()

        payload = evaluate_exits(
            self.enabled,
            self.services,
            response,
            payload={
                "as_of_date": "2026-05-07",
                "account_key": "paper-main",
                "generate_sell_plans": False,
                "operator": "tester",
                "idempotency_key": "api:exits:20260507",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["data"], {"as_of_date": "20260507", "generate_sell_plans": False})
        _, request, ctx = _FakePositionService.calls[0]
        self.assertEqual(request.as_of_date, "20260507")
        self.assertFalse(request.generate_sell_plans)
        self.assertEqual(ctx.source, "api")
        self.assertFalse(ctx.dry_run)
        self.assertEqual(ctx.operator, "tester")
        self.assertEqual(ctx.idempotency_key, "api:exits:20260507")


if __name__ == "__main__":
    unittest.main()
