from __future__ import annotations

import io
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from pgc_trading.cli.main import CommandServices, main
from pgc_trading.services.common import RequestContext, ServiceResult


@dataclass(frozen=True)
class _FakePipelineData:
    pipeline_status: str = "pass"
    review_date: str = "20260508"
    next_trade_date: str | None = "20260511"
    daily_pick_id: int | None = 2
    trade_plan_id: int | None = 2
    agent_run_id: int | None = 6
    agent_decision_id: int | None = 7
    exit_decisions: int = 0
    report_markdown: str | None = "reports/daily_review_20260508.md"
    report_json: str | None = "reports/daily_review_20260508.json"
    changed: bool = False
    backup_path: str | None = None
    ledger_audit_ok: bool = True
    daily_close_status: str | None = "success"
    agent_status: str | None = "skipped"
    exit_status: str | None = "success"
    report_status: str | None = "success"
    report_would_write: bool = False
    market_review_run_id: int | None = None
    market_review_status: str | None = "skipped"
    market_plan_context_status: str | None = "skipped"
    market_review_would_write: bool = False
    market_plan_context_would_write: bool = False
    shadow_observation_status: str | None = "blocked"
    shadow_observation_top_candidates: str | None = "trend_extension_shadow[status=blocked,today=3]"
    shadow_observation_blockers: str | None = "operator_review_required:1"
    shadow_walk_forward_outcomes_status: str | None = "partial"
    shadow_walk_forward_outcomes_availability: str | None = "signals=12,complete=9,partial=3,missing_bars=0"
    shadow_walk_forward_outcomes_blockers: str | None = "shadow_walk_forward_partial_horizon"
    shadow_evidence_status: str | None = "blocked"
    shadow_evidence_artifacts: str | None = "dossier:pass;replay_backtest_evidence:blocked;review_request:missing;scorecard:pass"
    shadow_evidence_blockers: str | None = "shadow_review_request_json_missing;shadow_replay_backtest_evidence_missing"
    shadow_evidence_dashboard_history: str | None = "status=pass,empty_history_risk=false"
    shadow_evidence_replay_backtest: str | None = "accepted=1,rejected=0,missing=4"


class _FakeDailyPipelineService:
    calls: list[tuple[Path, object, RequestContext]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def run_daily_pipeline(self, request, ctx: RequestContext) -> ServiceResult[_FakePipelineData]:
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=_FakePipelineData(review_date=request.as_of_date),
        )


class CliDailyPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        _FakeDailyPipelineService.calls = []

    def test_ops_daily_pipeline_routes_to_service_and_prints_contract_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            db_path.touch()
            stdout = io.StringIO()
            code = main(
                [
                    "ops",
                    "daily-pipeline",
                    "--date",
                    "20260508",
                    "--account",
                    "paper-main",
                    "--operator",
                    "azboo",
                    "--db-path",
                    str(db_path),
                    "--dry-run",
                ],
                stdout=stdout,
                services=CommandServices(daily_pipeline_service_factory=_FakeDailyPipelineService),
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(_FakeDailyPipelineService.calls), 1)
        called_db_path, request, ctx = _FakeDailyPipelineService.calls[0]
        self.assertEqual(called_db_path, db_path)
        self.assertEqual(request.as_of_date, "20260508")
        self.assertEqual(request.account_key, "paper-main")
        self.assertFalse(request.include_market_review)
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.operator, "azboo")
        self.assertEqual(ctx.idempotency_key, "daily-pipeline:paper-main:20260508:cpb_6157@2026-05-03:paper")

        output = stdout.getvalue()
        self.assertIn("pipeline_status=pass", output)
        self.assertIn("review_date=20260508", output)
        self.assertIn("next_trade_date=20260511", output)
        self.assertIn("daily_pick_id=2", output)
        self.assertIn("trade_plan_id=2", output)
        self.assertIn("agent_run_id=6", output)
        self.assertIn("market_review_run_id=none", output)
        self.assertIn("exit_decisions=0", output)
        self.assertIn("report_markdown=reports/daily_review_20260508.md", output)
        self.assertIn("report_json=reports/daily_review_20260508.json", output)
        self.assertIn("changed=false", output)
        self.assertIn("report_would_write=false", output)
        self.assertIn("shadow_observation_status=blocked", output)
        self.assertIn("shadow_observation_top_candidates=trend_extension_shadow", output)
        self.assertIn("shadow_observation_blockers=operator_review_required:1", output)
        self.assertIn("shadow_walk_forward_outcomes_status=partial", output)
        self.assertIn("shadow_walk_forward_outcomes_availability=signals=12,complete=9,partial=3,missing_bars=0", output)
        self.assertIn("shadow_walk_forward_outcomes_blockers=shadow_walk_forward_partial_horizon", output)
        self.assertIn("shadow_evidence_status=blocked", output)
        self.assertIn("shadow_evidence_artifacts=dossier:pass", output)
        self.assertIn("shadow_evidence_blockers=shadow_review_request_json_missing", output)
        self.assertIn("shadow_evidence_dashboard_history=status=pass,empty_history_risk=false", output)
        self.assertIn("shadow_evidence_replay_backtest=accepted=1,rejected=0,missing=4", output)
        self.assertIn("shadow_evidence_notice=review package only", output)
        self.assertIn("market_review_status=skipped", output)
        self.assertIn("market_plan_context_status=skipped", output)
        self.assertIn("market_review_would_write=false", output)

    def test_ops_daily_pipeline_include_market_review_flag_reaches_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            db_path.touch()
            stdout = io.StringIO()
            code = main(
                [
                    "ops",
                    "daily-pipeline",
                    "--date",
                    "20260508",
                    "--account",
                    "paper-main",
                    "--operator",
                    "azboo",
                    "--db-path",
                    str(db_path),
                    "--include-market-review",
                    "--dry-run",
                ],
                stdout=stdout,
                services=CommandServices(daily_pipeline_service_factory=_FakeDailyPipelineService),
            )

        self.assertEqual(code, 0)
        _, request, _ = _FakeDailyPipelineService.calls[0]
        self.assertTrue(request.include_market_review)

    def test_apply_without_operator_fails_before_pipeline_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            db_path.touch()
            stdout = io.StringIO()
            code = main(
                [
                    "ops",
                    "daily-pipeline",
                    "--date",
                    "20260508",
                    "--db-path",
                    str(db_path),
                    "--apply",
                ],
                stdout=stdout,
            )

        self.assertEqual(code, 1)
        output = stdout.getvalue()
        self.assertIn("pipeline_status=failed", output)
        self.assertIn("OPERATOR_REQUIRED", output)

    def test_missing_database_fails_without_constructing_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            stdout = io.StringIO()
            code = main(
                [
                    "ops",
                    "daily-pipeline",
                    "--date",
                    "20260508",
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
                services=CommandServices(daily_pipeline_service_factory=_UnexpectedPipelineService),
            )

        self.assertEqual(code, 1)
        self.assertFalse(db_path.exists())
        self.assertIn("pipeline_status=failed", stdout.getvalue())
        self.assertIn("database not found", stdout.getvalue())


class _UnexpectedPipelineService:
    def __init__(self, db_path: Path):
        raise AssertionError(f"daily pipeline service should not be built for missing db: {db_path}")


if __name__ == "__main__":
    unittest.main()
