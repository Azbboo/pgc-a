from __future__ import annotations

import io
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path

from pgc_trading.cli.main import CommandServices, main
from pgc_trading.services.common import RequestContext, ServiceResult


@dataclass(frozen=True)
class _FakeReviewData:
    daily_pick_id: int | None


class _FakeReviewService:
    calls: list[tuple[Path, str, RequestContext]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def run_daily_review(self, request, ctx: RequestContext) -> ServiceResult[_FakeReviewData]:
        self.calls.append((self.db_path, request.as_of_date, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=_FakeReviewData(daily_pick_id=None),
        )


@dataclass(frozen=True)
class _FakeCloseCandidate:
    ts_code: str = "000001.SZ"
    name: str = "Close Pick"
    daily_pick_id: int | None = 11
    score: float = 123.4


@dataclass(frozen=True)
class _FakeClosePlan:
    trade_plan_id: int | None = 22
    action: str = "buy_next_open"
    status: str = "active"
    planned_trade_date: str | None = "20260505"
    planned_shares: int | None = 6600


@dataclass(frozen=True)
class _FakeCloseData:
    workflow_status: str = "plan_ready"
    readiness: str = "pass"
    review_status: str = "success"
    plan_status: str = "success"
    next_trade_date: str | None = "20260505"
    signals_count: int = 1
    candidate: _FakeCloseCandidate | None = field(default_factory=_FakeCloseCandidate)
    buy_plan: _FakeClosePlan | None = field(default_factory=_FakeClosePlan)


class _FakeCloseService:
    calls: list[tuple[Path, object, RequestContext]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def run_daily_close(self, request, ctx: RequestContext) -> ServiceResult[_FakeCloseData]:
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=_FakeCloseData(),
        )


class _UnexpectedCloseService:
    def __init__(self, db_path: Path):
        raise AssertionError(f"daily close service should not be built for missing db: {db_path}")


@dataclass(frozen=True)
class _FakePlanData:
    trade_plan_id: int | None = None
    action: str = "buy_next_open"
    status: str = "active"
    reason: str = "daily_pick"
    planned_trade_date: str | None = "20260505"
    planned_cash: float | None = 66666.67
    planned_shares: int | None = 6600
    free_position_slots: int = 2
    idempotent: bool = False


@dataclass(frozen=True)
class _FakeCancelPlanData:
    id: int = 1
    status: str = "cancelled"
    cancel_reason: str = "高开过大"


class _FakePlanningService:
    calls: list[tuple[Path, object, RequestContext]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def generate_buy_plan(self, request, ctx: RequestContext) -> ServiceResult[_FakePlanData]:
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=_FakePlanData(),
        )

    def cancel_plan(self, request, ctx: RequestContext) -> ServiceResult[_FakeCancelPlanData]:
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=_FakeCancelPlanData(id=request.trade_plan_id, cancel_reason=request.cancel_reason),
        )


class _UnexpectedPlanningService:
    def __init__(self, db_path: Path):
        raise AssertionError(f"planning service should not be built for missing db: {db_path}")


class _UnexpectedReviewService:
    def __init__(self, db_path: Path):
        raise AssertionError(f"review service should not be built for missing db: {db_path}")


@dataclass(frozen=True)
class _FakeReadinessData:
    account_key: str = "paper-main"
    as_of_date: str = "20260507"
    readiness: str = "pass"
    trades_count: int = 10
    closed_trades_count: int = 2
    win_rate: float | None = 0.5
    realized_pnl: float = 128.5
    avg_slippage: float | None = None
    last_pipeline_status: str | None = "success"
    open_positions_count: int = 0
    due_exit_positions_count: int = 0
    open_blockers_count: int = 0
    invariant_ok: bool = True
    ledger_blockers_count: int = 0
    invariant_violation_codes: list[str] = field(default_factory=list)
    promotion_blockers: list[str] = field(default_factory=list)
    promotion_warnings: list[str] = field(default_factory=lambda: ["AGENT_EVIDENCE_MISSING"])


class _FakeReadinessService:
    calls: list[tuple[Path, object, RequestContext]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def check_paper_readiness(self, request, ctx: RequestContext) -> ServiceResult[_FakeReadinessData]:
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=_FakeReadinessData(as_of_date=request.as_of_date),
        )


@dataclass(frozen=True)
class _FakeAgentReviewData:
    input_snapshot_id: int | None = 101
    agent_run_id: int | None = 202
    agent_decision_id: int | None = 303
    action: str | None = "caution"
    confidence: float | None = None
    risk_level: str | None = "medium"
    summary: str | None = "Agent advisory only."
    artifact_paths: list[str] = field(default_factory=lambda: ["/tmp/agent_run_000202_decision.json"])


class _FakeAgentReviewService:
    calls: list[tuple[Path, object, RequestContext]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def review_daily_pick(self, request, ctx: RequestContext) -> ServiceResult[_FakeAgentReviewData]:
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=_FakeAgentReviewData(),
        )


class _UnexpectedAgentReviewService:
    def __init__(self, db_path: Path):
        raise AssertionError(f"agent review service should not be built for missing db: {db_path}")


@dataclass(frozen=True)
class _FakeExternalDataImportData:
    row_count: int = 2
    valid_count: int = 2
    invalid_count: int = 0
    would_insert_count: int = 2
    would_update_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    agent_external_item_ids: list[int] = field(default_factory=list)
    invalid_records: list[object] = field(default_factory=list)


class _FakeAgentExternalDataService:
    calls: list[tuple[Path, object, RequestContext]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def import_external_data(self, request, ctx: RequestContext) -> ServiceResult[_FakeExternalDataImportData]:
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=_FakeExternalDataImportData(
                inserted_count=0 if ctx.dry_run else 2,
                agent_external_item_ids=[] if ctx.dry_run else [1, 2],
            ),
        )


class _UnexpectedAgentExternalDataService:
    def __init__(self, db_path: Path):
        raise AssertionError(f"agent external data service should not be built for missing db: {db_path}")


class CliMainTest(unittest.TestCase):
    def setUp(self) -> None:
        _FakeReviewService.calls = []
        _FakeCloseService.calls = []
        _FakePlanningService.calls = []
        _FakeReadinessService.calls = []
        _FakeAgentReviewService.calls = []
        _FakeAgentExternalDataService.calls = []

    def test_help_lists_command_surface(self) -> None:
        stdout = io.StringIO()
        with self.assertRaises(SystemExit) as raised:
            main(["--help"], stdout=stdout)

        self.assertEqual(raised.exception.code, 0)
        output = stdout.getvalue()
        for command in [
            "review",
            "daily-close",
            "plan",
            "plan-cancel",
            "report",
            "record-buy",
            "record-sell",
            "positions",
            "exits-evaluate",
            "paper-readiness",
            "agent",
            "ops",
        ]:
            self.assertIn(command, output)

    def test_review_routes_to_service_with_normalized_date_and_db_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_cli.db"
            db_path.touch()
            stdout = io.StringIO()
            code = main(
                ["review", "--date", "2026-05-04", "--db-path", str(db_path)],
                stdout=stdout,
                services=CommandServices(review_service_factory=_FakeReviewService),
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(_FakeReviewService.calls), 1)
        called_db_path, as_of_date, ctx = _FakeReviewService.calls[0]
        self.assertEqual(called_db_path, db_path)
        self.assertEqual(as_of_date, "20260504")
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.operator, "cli")
        self.assertEqual(ctx.source, "cli")
        self.assertIn("service returned success", stdout.getvalue())

    def test_review_missing_db_is_noop_and_does_not_create_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            stdout = io.StringIO()
            code = main(
                ["review", "--date", "2026-05-04", "--db-path", str(db_path)],
                stdout=stdout,
                services=CommandServices(review_service_factory=_UnexpectedReviewService),
            )

            self.assertEqual(code, 0)
            self.assertFalse(db_path.exists())
            self.assertIn("database not found", stdout.getvalue())
            self.assertIn("20260504", stdout.getvalue())

    def test_daily_close_routes_to_service_with_preview_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_close.db"
            db_path.touch()
            stdout = io.StringIO()
            code = main(
                ["daily-close", "--date", "2026-05-04", "--db-path", str(db_path)],
                stdout=stdout,
                services=CommandServices(daily_close_workflow_service_factory=_FakeCloseService),
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(_FakeCloseService.calls), 1)
        called_db_path, request, ctx = _FakeCloseService.calls[0]
        self.assertEqual(called_db_path, db_path)
        self.assertEqual(request.as_of_date, "20260504")
        self.assertEqual(request.strategy_version, "cpb_6157@2026-05-03")
        self.assertEqual(request.account_key, "paper-main")
        self.assertIsNone(request.account_id)
        self.assertEqual(request.run_type, "paper")
        self.assertFalse(request.force_new_review_run)
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.operator, "cli")
        self.assertEqual(ctx.source, "cli")
        self.assertTrue(ctx.idempotency_key.startswith("daily-close:paper-main:20260504:"))
        output = stdout.getvalue()
        self.assertIn("service returned success", output)
        self.assertIn("workflow_status=plan_ready", output)
        self.assertIn("buy_plan=id=22 action=buy_next_open status=active", output)

    def test_daily_close_apply_mode_uses_write_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_close_apply.db"
            db_path.touch()
            stdout = io.StringIO()
            code = main(
                [
                    "daily-close",
                    "--date",
                    "2026-05-04",
                    "--db-path",
                    str(db_path),
                    "--apply",
                    "--operator",
                    "tester",
                ],
                stdout=stdout,
                services=CommandServices(daily_close_workflow_service_factory=_FakeCloseService),
            )

        self.assertEqual(code, 0)
        _, request, ctx = _FakeCloseService.calls[0]
        self.assertEqual(request.as_of_date, "20260504")
        self.assertFalse(ctx.dry_run)
        self.assertEqual(ctx.operator, "tester")
        self.assertFalse(ctx.allow_live_writes)
        self.assertTrue(ctx.idempotency_key.startswith("daily-close:paper-main:20260504:"))
        self.assertIn("workflow_status=plan_ready", stdout.getvalue())

    def test_daily_close_live_writes_flag_reaches_service_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_live_apply.db"
            db_path.touch()
            stdout = io.StringIO()
            code = main(
                [
                    "daily-close",
                    "--date",
                    "2026-05-04",
                    "--db-path",
                    str(db_path),
                    "--account",
                    "live-main",
                    "--run-type",
                    "live",
                    "--apply",
                    "--allow-live-writes",
                    "--operator",
                    "tester",
                ],
                stdout=stdout,
                services=CommandServices(daily_close_workflow_service_factory=_FakeCloseService),
            )

        self.assertEqual(code, 0)
        _, request, ctx = _FakeCloseService.calls[0]
        self.assertEqual(request.account_key, "live-main")
        self.assertEqual(request.run_type, "live")
        self.assertFalse(ctx.dry_run)
        self.assertTrue(ctx.allow_live_writes)

    def test_daily_close_missing_db_fails_without_creating_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            stdout = io.StringIO()
            code = main(
                ["daily-close", "--date", "2026-05-04", "--db-path", str(db_path)],
                stdout=stdout,
                services=CommandServices(daily_close_workflow_service_factory=_UnexpectedCloseService),
            )

            self.assertEqual(code, 1)
            self.assertFalse(db_path.exists())
            self.assertIn("database not found", stdout.getvalue())
            self.assertIn("20260504", stdout.getvalue())

    def test_plan_routes_to_planning_service_with_preview_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_plan.db"
            db_path.touch()
            stdout = io.StringIO()
            code = main(
                [
                    "plan",
                    "--date",
                    "2026-05-04",
                    "--daily-pick-id",
                    "11",
                    "--planned-trade-date",
                    "2026-05-05",
                    "--account",
                    "paper-main",
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
                services=CommandServices(planning_service_factory=_FakePlanningService),
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(_FakePlanningService.calls), 1)
        called_db_path, request, ctx = _FakePlanningService.calls[0]
        self.assertEqual(called_db_path, db_path)
        self.assertEqual(request.account_key, "paper-main")
        self.assertIsNone(request.account_id)
        self.assertEqual(request.daily_pick_id, 11)
        self.assertEqual(request.review_date, "20260504")
        self.assertEqual(request.planned_trade_date, "20260505")
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.operator, "cli")
        self.assertEqual(ctx.source, "cli")
        self.assertEqual(ctx.idempotency_key, "plan-buy:paper-main:20260504:11")
        output = stdout.getvalue()
        self.assertIn("service returned success", output)
        self.assertIn("trade_plan=id=none action=buy_next_open status=active", output)
        self.assertIn("planned_trade_date=2026-05-05", output)
        self.assertIn("planned_shares=6600", output)

    def test_plan_apply_mode_uses_write_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_plan_apply.db"
            db_path.touch()
            stdout = io.StringIO()
            code = main(
                [
                    "plan",
                    "--date",
                    "2026-05-04",
                    "--db-path",
                    str(db_path),
                    "--apply",
                    "--operator",
                    "tester",
                ],
                stdout=stdout,
                services=CommandServices(planning_service_factory=_FakePlanningService),
            )

        self.assertEqual(code, 0)
        _, request, ctx = _FakePlanningService.calls[0]
        self.assertEqual(request.review_date, "20260504")
        self.assertIsNone(request.daily_pick_id)
        self.assertFalse(ctx.dry_run)
        self.assertEqual(ctx.operator, "tester")
        self.assertFalse(ctx.allow_live_writes)
        self.assertEqual(ctx.idempotency_key, "plan-buy:paper-main:20260504:20260504")
        self.assertIn("trade_plan=id=none action=buy_next_open status=active", stdout.getvalue())

    def test_plan_missing_db_fails_without_creating_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            stdout = io.StringIO()
            code = main(
                ["plan", "--date", "2026-05-04", "--db-path", str(db_path)],
                stdout=stdout,
                services=CommandServices(planning_service_factory=_UnexpectedPlanningService),
            )

            self.assertEqual(code, 1)
            self.assertFalse(db_path.exists())
            self.assertIn("database not found", stdout.getvalue())
            self.assertIn("20260504", stdout.getvalue())

    def test_plan_cancel_routes_to_planning_service_and_prints_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_plan_cancel.db"
            db_path.touch()
            stdout = io.StringIO()
            code = main(
                [
                    "plan-cancel",
                    "--plan-id",
                    "1",
                    "--reason",
                    "高开过大",
                    "--account",
                    "paper-main",
                    "--db-path",
                    str(db_path),
                    "--operator",
                    "azboo",
                ],
                stdout=stdout,
                services=CommandServices(planning_service_factory=_FakePlanningService),
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(_FakePlanningService.calls), 1)
        called_db_path, request, ctx = _FakePlanningService.calls[0]
        self.assertEqual(called_db_path, db_path)
        self.assertEqual(request.trade_plan_id, 1)
        self.assertEqual(request.cancel_reason, "高开过大")
        self.assertEqual(request.account_key, "paper-main")
        self.assertIsNone(request.account_id)
        self.assertEqual(ctx.request_id, "cli-plan-cancel")
        self.assertEqual(ctx.operator, "azboo")
        self.assertEqual(ctx.source, "cli")
        output = stdout.getvalue()
        self.assertIn("service returned success", output)
        self.assertIn("trade_plan=id=1 status=cancelled cancel_reason=高开过大", output)

    def test_plan_cancel_missing_db_fails_without_creating_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            stdout = io.StringIO()
            code = main(
                [
                    "plan-cancel",
                    "--plan-id",
                    "1",
                    "--reason",
                    "高开过大",
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
                services=CommandServices(planning_service_factory=_UnexpectedPlanningService),
            )

            self.assertEqual(code, 1)
            self.assertFalse(db_path.exists())
            self.assertIn("database not found", stdout.getvalue())
            self.assertIn("plan-id=1", stdout.getvalue())

    def test_plan_cancel_requires_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_plan_cancel.db"
            db_path.touch()
            stdout = io.StringIO()
            stderr = io.StringIO()

            with self.assertRaises(SystemExit) as raised:
                main(
                    ["plan-cancel", "--plan-id", "1", "--db-path", str(db_path)],
                    stdout=stdout,
                    stderr=stderr,
                    services=CommandServices(planning_service_factory=_FakePlanningService),
                )

        self.assertNotEqual(raised.exception.code, 0)
        self.assertEqual(_FakePlanningService.calls, [])
        self.assertIn("the following arguments are required: --reason", stderr.getvalue())

    def test_paper_readiness_routes_to_service_and_prints_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_readiness.db"
            db_path.touch()
            stdout = io.StringIO()
            code = main(
                [
                    "paper-readiness",
                    "--date",
                    "2026-05-07",
                    "--account",
                    "paper-main",
                    "--min-trades",
                    "12",
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
                services=CommandServices(operational_readiness_service_factory=_FakeReadinessService),
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(_FakeReadinessService.calls), 1)
        called_db_path, request, ctx = _FakeReadinessService.calls[0]
        self.assertEqual(called_db_path, db_path)
        self.assertEqual(request.as_of_date, "20260507")
        self.assertEqual(request.account_key, "paper-main")
        self.assertEqual(request.min_trades, 12)
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.operator, "cli")
        output = stdout.getvalue()
        self.assertIn("service returned success", output)
        self.assertIn("readiness=pass", output)
        self.assertIn("trades_count=10", output)
        self.assertIn("closed_trades_count=2", output)
        self.assertIn("win_rate=0.5", output)
        self.assertIn("realized_pnl=128.5", output)
        self.assertIn("avg_slippage=none", output)
        self.assertIn("last_pipeline_status=success", output)
        self.assertIn("open_positions_count=0", output)
        self.assertIn("due_exit_positions_count=0", output)
        self.assertIn("open_blockers_count=0", output)
        self.assertIn("invariant_ok=true", output)
        self.assertIn("promotion_warnings=AGENT_EVIDENCE_MISSING", output)

    def test_agent_review_routes_to_service_with_dry_run_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_agent.db"
            db_path.touch()
            stdout = io.StringIO()
            code = main(
                [
                    "agent",
                    "review",
                    "--daily-pick-id",
                    "1",
                    "--account",
                    "paper-main",
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
                services=CommandServices(agent_review_service_factory=_FakeAgentReviewService),
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(_FakeAgentReviewService.calls), 1)
        called_db_path, request, ctx = _FakeAgentReviewService.calls[0]
        self.assertEqual(called_db_path, db_path)
        self.assertEqual(request.daily_pick_id, 1)
        self.assertEqual(request.account_key, "paper-main")
        self.assertEqual(request.mode, "local_snapshot_mode")
        self.assertFalse(request.online_tools)
        self.assertEqual(request.llm_provider, "deepseek")
        self.assertEqual(request.deep_think_llm, "deepseek-v4-pro")
        self.assertEqual(request.quick_think_llm, "deepseek-v4-pro")
        self.assertEqual(request.max_debate_rounds, 3)
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.request_id, "cli-agent-review")
        self.assertEqual(ctx.operator, "cli")
        self.assertEqual(ctx.idempotency_key, "agent-review:paper-main:daily-pick-1")
        output = stdout.getvalue()
        self.assertIn("agent review command routed", output)
        self.assertIn("service returned success", output)
        self.assertIn("agent_review=input_snapshot_id=101 agent_run_id=202 agent_decision_id=303", output)
        self.assertIn("action=caution", output)
        self.assertIn("summary=Agent advisory only.", output)

    def test_agent_review_apply_mode_uses_write_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_agent_apply.db"
            db_path.touch()
            stdout = io.StringIO()
            code = main(
                [
                    "agent",
                    "review",
                    "--daily-pick-id",
                    "1",
                    "--db-path",
                    str(db_path),
                    "--apply",
                    "--operator",
                    "azboo",
                    "--mode",
                    "external_graph_mode",
                    "--online-tools",
                    "--llm-provider",
                    "openai",
                    "--deep-think-llm",
                    "gpt-5.4",
                    "--quick-think-llm",
                    "gpt-5.4-mini",
                    "--max-debate-rounds",
                    "2",
                    "--max-risk-discuss-rounds",
                    "2",
                ],
                stdout=stdout,
                services=CommandServices(agent_review_service_factory=_FakeAgentReviewService),
            )

        self.assertEqual(code, 0)
        _, request, ctx = _FakeAgentReviewService.calls[0]
        self.assertFalse(ctx.dry_run)
        self.assertEqual(ctx.operator, "azboo")
        self.assertEqual(request.mode, "external_graph_mode")
        self.assertTrue(request.online_tools)
        self.assertEqual(request.llm_provider, "openai")
        self.assertEqual(request.deep_think_llm, "gpt-5.4")
        self.assertEqual(request.quick_think_llm, "gpt-5.4-mini")
        self.assertEqual(request.max_debate_rounds, 2)
        self.assertEqual(request.max_risk_discuss_rounds, 2)

    def test_agent_review_missing_db_fails_without_creating_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            stdout = io.StringIO()
            code = main(
                ["agent", "review", "--daily-pick-id", "1", "--db-path", str(db_path)],
                stdout=stdout,
                services=CommandServices(agent_review_service_factory=_UnexpectedAgentReviewService),
            )

            self.assertEqual(code, 1)
            self.assertFalse(db_path.exists())
            self.assertIn("database not found", stdout.getvalue())
            self.assertIn("daily-pick-id=1", stdout.getvalue())

    def test_agent_external_data_import_routes_to_service_with_dry_run_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_agent_external.db"
            db_path.touch()
            source_file = Path(tmp) / "external_items.json"
            source_file.write_text("[]", encoding="utf-8")
            stdout = io.StringIO()
            code = main(
                [
                    "agent",
                    "external-data",
                    "import",
                    "--file",
                    str(source_file),
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
                services=CommandServices(
                    agent_external_data_service_factory=_FakeAgentExternalDataService,
                ),
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(_FakeAgentExternalDataService.calls), 1)
        called_db_path, request, ctx = _FakeAgentExternalDataService.calls[0]
        self.assertEqual(called_db_path, db_path)
        self.assertEqual(request.source_file, source_file)
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.request_id, "cli-agent-external-data-import")
        self.assertEqual(ctx.operator, "cli")
        self.assertEqual(ctx.source, "cli")
        output = stdout.getvalue()
        self.assertIn("agent external-data import command routed", output)
        self.assertIn("service returned success", output)
        self.assertIn("external_data_import=rows=2 valid=2 invalid=0", output)
        self.assertIn("would_insert=2", output)
        self.assertIn("inserted=0", output)

    def test_agent_external_data_import_apply_mode_uses_write_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_agent_external_apply.db"
            db_path.touch()
            source_file = Path(tmp) / "external_items.json"
            source_file.write_text("[]", encoding="utf-8")
            stdout = io.StringIO()
            code = main(
                [
                    "agent",
                    "external-data",
                    "import",
                    "--input",
                    str(source_file),
                    "--date",
                    "20260508",
                    "--source",
                    "tushare",
                    "--db-path",
                    str(db_path),
                    "--apply",
                    "--operator",
                    "azboo",
                    "--idempotency-key",
                    "external-data:test",
                ],
                stdout=stdout,
                services=CommandServices(
                    agent_external_data_service_factory=_FakeAgentExternalDataService,
                ),
            )

        self.assertEqual(code, 0)
        _, request, ctx = _FakeAgentExternalDataService.calls[0]
        self.assertEqual(request.source_file, source_file)
        self.assertEqual(request.default_published_date, "20260508")
        self.assertEqual(request.default_provider, "tushare")
        self.assertFalse(ctx.dry_run)
        self.assertEqual(ctx.operator, "azboo")
        self.assertEqual(ctx.idempotency_key, "external-data:test")
        self.assertIn("inserted=2", stdout.getvalue())

    def test_agent_external_data_import_missing_db_fails_without_creating_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            source_file = Path(tmp) / "external_items.json"
            source_file.write_text("[]", encoding="utf-8")
            stdout = io.StringIO()
            code = main(
                [
                    "agent",
                    "external-data",
                    "import",
                    "--file",
                    str(source_file),
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
                services=CommandServices(
                    agent_external_data_service_factory=_UnexpectedAgentExternalDataService,
                ),
            )

            self.assertEqual(code, 1)
            self.assertFalse(db_path.exists())
            self.assertIn("database not found", stdout.getvalue())
            self.assertIn("external_items.json", stdout.getvalue())

    def test_ops_version_prints_standard_release_tag(self) -> None:
        stdout = io.StringIO()
        code = main(
            ["ops", "version", "--date", "2026-05-08", "--git-sha", "abcdef123456"],
            stdout=stdout,
        )

        self.assertEqual(code, 0)
        output = stdout.getvalue()
        self.assertIn("package_version=0.1.0", output)
        self.assertIn("api_version=0.1.0", output)
        self.assertIn("release_tag=pgc-v0.1.0-20260508-gabcdef1", output)

    def test_ops_backup_creates_timestamped_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            backup_dir = Path(tmp) / "backups"
            db_path.write_text("payload", encoding="utf-8")
            stdout = io.StringIO()
            code = main(
                [
                    "ops",
                    "backup",
                    "--db-path",
                    str(db_path),
                    "--backup-dir",
                    str(backup_dir),
                    "--label",
                    "unit_ops",
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 0)
            backups = list(backup_dir.glob("*.db"))
            self.assertEqual(len(backups), 1)
            self.assertIn("unit_ops", backups[0].name)
            self.assertIn("backup_path=", stdout.getvalue())

    def test_ops_migrate_dry_run_does_not_create_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            stdout = io.StringIO()
            code = main(
                ["ops", "migrate", "--dry-run", "--backup", "--db-path", str(db_path)],
                stdout=stdout,
            )

            self.assertEqual(code, 0)
            self.assertFalse(db_path.exists())
            output = stdout.getvalue()
            self.assertIn("dry_run=true", output)
            self.assertIn("backup_path=none", output)
            self.assertIn("changed=true", output)

    def test_ops_health_requires_current_migrations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            stdout = io.StringIO()
            code = main(
                [
                    "ops",
                    "health",
                    "--db-path",
                    str(db_path),
                    "--require-current-migrations",
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 1)
            self.assertFalse(db_path.exists())
            output = stdout.getvalue()
            self.assertIn("status=missing_database", output)
            self.assertIn("database_exists=false", output)

    def test_report_command_routes_as_noop(self) -> None:
        stdout = io.StringIO()
        code = main(
            ["report", "--date", "2026-05-04", "--db-path", "/private/tmp/pgc_cli.db"],
            stdout=stdout,
        )

        self.assertEqual(code, 0)
        self.assertIn("report command routed for 20260504", stdout.getvalue())
        self.assertIn("no writes were performed", stdout.getvalue())

    def test_future_commands_have_routing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing_db = str(Path(tmp) / "missing.db")
            cases = [
                ["positions", "--date", "2026-05-07", "--db-path", missing_db],
            ]

            for argv in cases:
                with self.subTest(command=argv[0]):
                    stdout = io.StringIO()
                    code = main(argv, stdout=stdout)
                    self.assertEqual(code, 0)
                    self.assertIn(f"{argv[0]} command routed", stdout.getvalue())
                    self.assertIn("no writes were performed", stdout.getvalue())

    def test_record_command_missing_db_fails_without_creating_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            stdout = io.StringIO()
            code = main(
                [
                    "record-buy",
                    "--plan-id",
                    "101",
                    "--date",
                    "2026-05-05",
                    "--price",
                    "10.50",
                    "--shares",
                    "6600",
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 1)
            self.assertFalse(db_path.exists())
            self.assertIn("database not found", stdout.getvalue())

    def test_invalid_date_exits_nonzero_with_clear_message(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with self.assertRaises(SystemExit) as raised:
            main(
                ["review", "--date", "2026-99-99", "--db-path", "/private/tmp/pgc_cli.db"],
                stdout=stdout,
                stderr=stderr,
            )

        self.assertNotEqual(raised.exception.code, 0)
        self.assertIn("invalid date '2026-99-99': expected YYYY-MM-DD", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
