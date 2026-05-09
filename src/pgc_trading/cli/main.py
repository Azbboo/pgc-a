"""CLI entrypoints for PGC trading workflows."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, TextIO

from pgc_trading import __version__
from pgc_trading.config import Paths
from pgc_trading.ops import build_release_tag, run_ops_health_check, run_ops_migration_step
from pgc_trading.reporting.daily_report import (
    DailyReportRequest,
    ReportingQueryService,
    render_daily_report_json,
    render_daily_report_markdown,
)
from pgc_trading.services.agent_external_data_service import (
    AgentExternalDataService,
    ImportAgentExternalDataRequest,
)
from pgc_trading.services.agent_review_service import AgentReviewService, ReviewDailyPickRequest
from pgc_trading.services.common import RequestContext, ServiceResult
from pgc_trading.services.daily_pipeline_service import (
    DailyPipelineService,
    RunDailyPipelineRequest,
)
from pgc_trading.services.daily_close_workflow_service import (
    DEFAULT_ACCOUNT_KEY,
    DailyCloseWorkflowService,
    RunDailyCloseWorkflowRequest,
)
from pgc_trading.services.daily_review_service import DailyReviewService, RunDailyReviewRequest
from pgc_trading.services.execution_recording_service import (
    ExecutionRecordingService,
    LedgerAuditRequest,
    LedgerRepairRequest,
    RecordPositionSellRequest,
    RecordTradeRequest,
)
from pgc_trading.services.operational_readiness_service import (
    OperationalReadinessService,
    PaperReadinessRequest,
)
from pgc_trading.services.position_lifecycle_service import (
    EvaluateExitsRequest,
    ListPositionsRequest,
    PositionLifecycleService,
)
from pgc_trading.services.portfolio_planning_service import (
    CancelTradePlanRequest,
    GenerateBuyPlanRequest,
    PortfolioPlanningService,
)
from pgc_trading.strategies.cpb_6157 import STRATEGY_VERSION
from pgc_trading.storage.migrators.backup import backup_database


ReviewServiceFactory = Callable[[Path], DailyReviewService]
CloseServiceFactory = Callable[[Path], DailyCloseWorkflowService]
ReportServiceFactory = Callable[[Path], ReportingQueryService]
ExecutionServiceFactory = Callable[[Path], ExecutionRecordingService]
PositionServiceFactory = Callable[[Path], PositionLifecycleService]
OperationalReadinessServiceFactory = Callable[[Path], OperationalReadinessService]
PlanningServiceFactory = Callable[[Path], PortfolioPlanningService]
AgentReviewServiceFactory = Callable[[Path], AgentReviewService]
AgentExternalDataServiceFactory = Callable[[Path], AgentExternalDataService]
DailyPipelineServiceFactory = Callable[[Path], DailyPipelineService]


@dataclass(frozen=True)
class CommandServices:
    daily_close_workflow_service_factory: CloseServiceFactory = DailyCloseWorkflowService
    review_service_factory: ReviewServiceFactory = DailyReviewService
    report_service_factory: ReportServiceFactory = ReportingQueryService
    execution_service_factory: ExecutionServiceFactory = ExecutionRecordingService
    position_service_factory: PositionServiceFactory = PositionLifecycleService
    operational_readiness_service_factory: OperationalReadinessServiceFactory = OperationalReadinessService
    planning_service_factory: PlanningServiceFactory = PortfolioPlanningService
    agent_review_service_factory: AgentReviewServiceFactory = AgentReviewService
    agent_external_data_service_factory: AgentExternalDataServiceFactory = AgentExternalDataService
    daily_pipeline_service_factory: DailyPipelineServiceFactory = DailyPipelineService


class PgcArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that can write to injected streams for tests."""

    def __init__(self, *args: object, stdout: TextIO | None = None, stderr: TextIO | None = None, **kwargs: object):
        super().__init__(*args, **kwargs)
        self._stdout = stdout
        self._stderr = stderr

    def _print_message(self, message: str, file: TextIO | None = None) -> None:
        if not message:
            return
        target = file
        if target is None or target is sys.stdout:
            target = self._stdout or sys.stdout
        elif target is sys.stderr:
            target = self._stderr or sys.stderr
        target.write(message)


def main(
    argv: list[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    services: CommandServices | None = None,
) -> int:
    """Run the pgc CLI."""

    output = stdout or sys.stdout
    parser = build_parser(stdout=output, stderr=stderr)
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return int(handler(args, output, services or CommandServices()))


def build_parser(*, stdout: TextIO | None = None, stderr: TextIO | None = None) -> argparse.ArgumentParser:
    parser = PgcArgumentParser(
        prog="pgc",
        description="PGC daily review and paper-trading command line tools.",
        stdout=stdout,
        stderr=stderr,
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    review = subparsers.add_parser(
        "review",
        help="run the daily close review workflow preview",
        stdout=stdout,
        stderr=stderr,
    )
    _add_date_argument(review)
    _add_db_path_argument(review)
    review.set_defaults(handler=_run_review)

    daily_close = subparsers.add_parser(
        "daily-close",
        help="run the daily close workflow preview or apply",
        stdout=stdout,
        stderr=stderr,
    )
    _add_date_argument(daily_close)
    _add_db_path_argument(daily_close)
    _add_account_arguments(daily_close)
    daily_close.add_argument(
        "--strategy-version",
        default=STRATEGY_VERSION,
        help="strategy version to run in the daily close workflow",
    )
    daily_close.add_argument(
        "--run-type",
        choices=["research", "backtest", "validation", "paper", "live"],
        default="paper",
        help="workflow run type",
    )
    daily_close.add_argument(
        "--apply",
        action="store_true",
        help="persist the workflow result instead of running dry-run preview",
    )
    daily_close.add_argument(
        "--force-new-review-run",
        action="store_true",
        help="ignore any completed review with the same idempotency key",
    )
    _add_lifecycle_context_arguments(daily_close)
    _add_live_write_guard_argument(daily_close)
    daily_close.set_defaults(handler=_run_daily_close)

    plan = subparsers.add_parser(
        "plan",
        help="generate a buy-plan preview or apply it",
        stdout=stdout,
        stderr=stderr,
    )
    _add_date_argument(plan)
    _add_account_arguments(plan)
    plan.add_argument("--daily-pick-id", type=_positive_int, help="daily pick id to plan from")
    plan.add_argument(
        "--planned-trade-date",
        type=_parse_iso_date,
        metavar="YYYY-MM-DD",
        help="override the planned trade date",
    )
    plan.add_argument("--agent-decision-id", type=_positive_int, help="optional advisory agent decision id")
    plan.add_argument(
        "--apply",
        action="store_true",
        help="persist the generated buy plan instead of previewing it",
    )
    _add_lifecycle_context_arguments(plan)
    _add_live_write_guard_argument(plan)
    _add_db_path_argument(plan)
    plan.set_defaults(handler=_run_plan)

    plan_cancel = subparsers.add_parser(
        "plan-cancel",
        help="cancel an unexecuted paper trade plan",
        stdout=stdout,
        stderr=stderr,
    )
    plan_cancel.add_argument("--plan-id", type=_positive_int, required=True)
    plan_cancel.add_argument("--reason", type=_non_blank_text, required=True, help="manual cancellation reason")
    _add_account_arguments(plan_cancel)
    _add_lifecycle_context_arguments(plan_cancel)
    _add_live_write_guard_argument(plan_cancel)
    _add_db_path_argument(plan_cancel)
    plan_cancel.set_defaults(handler=_run_plan_cancel)

    report = subparsers.add_parser(
        "report",
        help="generate daily review report output",
        stdout=stdout,
        stderr=stderr,
    )
    report.add_argument("report_type", nargs="?", choices=["daily"], default="daily")
    _add_report_date_argument(report)
    report.add_argument("--account", dest="account_key", default=DEFAULT_ACCOUNT_KEY, help="portfolio account key")
    report.add_argument("--account-id", type=_positive_int, help="portfolio account id")
    report.add_argument("--strategy-version", default=STRATEGY_VERSION, help="strategy version to report")
    report.add_argument("--format", choices=["markdown", "json"], default="markdown", help="report output format")
    report.add_argument("--output", type=Path, help="write the rendered report to this path")
    report.add_argument(
        "--write-live-plan",
        action="store_true",
        help="write to reports/live_trade_plan.md or reports/live_trade_plan.json",
    )
    _add_db_path_argument(report)
    report.set_defaults(handler=_run_report)

    record_buy = subparsers.add_parser(
        "record-buy",
        help="route a manual buy execution",
        stdout=stdout,
        stderr=stderr,
    )
    record_buy.add_argument("--plan-id", type=_positive_int, required=True)
    _add_date_argument(record_buy)
    record_buy.add_argument("--price", type=_positive_float, required=True)
    record_buy.add_argument("--shares", type=_positive_int, required=True)
    _add_execution_common_arguments(record_buy)
    _add_db_path_argument(record_buy)
    record_buy.set_defaults(handler=_run_record_buy)

    record_sell = subparsers.add_parser(
        "record-sell",
        help="route a manual sell execution",
        stdout=stdout,
        stderr=stderr,
    )
    record_sell.add_argument("--position-id", type=_positive_int, required=True)
    _add_date_argument(record_sell)
    record_sell.add_argument("--price", type=_positive_float, required=True)
    record_sell.add_argument("--shares", type=_positive_int, required=True)
    _add_execution_common_arguments(record_sell)
    _add_db_path_argument(record_sell)
    record_sell.set_defaults(handler=_run_record_sell)

    positions = subparsers.add_parser(
        "positions",
        help="route position decision review",
        stdout=stdout,
        stderr=stderr,
    )
    _add_date_argument(positions)
    _add_account_arguments(positions)
    _add_db_path_argument(positions)
    positions.set_defaults(handler=_run_positions)

    exits_evaluate = subparsers.add_parser(
        "exits-evaluate",
        help="route position exit evaluation",
        stdout=stdout,
        stderr=stderr,
    )
    _add_date_argument(exits_evaluate)
    _add_account_arguments(exits_evaluate)
    exits_evaluate.add_argument(
        "--no-generate-sell-plans",
        action="store_true",
        help="create exit decisions without generating sell trade plans",
    )
    _add_lifecycle_context_arguments(exits_evaluate)
    _add_live_write_guard_argument(exits_evaluate)
    _add_db_path_argument(exits_evaluate)
    exits_evaluate.set_defaults(handler=_run_exits_evaluate)

    paper_readiness = subparsers.add_parser(
        "paper-readiness",
        help="check whether the paper account can enter live-preparation work",
        stdout=stdout,
        stderr=stderr,
    )
    _add_date_argument(paper_readiness)
    _add_account_arguments(paper_readiness)
    paper_readiness.add_argument(
        "--min-trades",
        type=_positive_int,
        default=10,
        help="minimum executed paper trades required to pass",
    )
    _add_db_path_argument(paper_readiness)
    paper_readiness.set_defaults(handler=_run_paper_readiness)

    agent = subparsers.add_parser(
        "agent",
        help="run advisory agent workflows",
        stdout=stdout,
        stderr=stderr,
    )
    agent_subparsers = agent.add_subparsers(dest="agent_command", metavar="agent-command")
    agent_review = agent_subparsers.add_parser(
        "review",
        help="run a TradingAgents advisory review for a daily pick",
        stdout=stdout,
        stderr=stderr,
    )
    agent_review.add_argument("--daily-pick-id", type=_positive_int, required=True)
    _add_account_arguments(agent_review)
    agent_review.add_argument(
        "--apply",
        action="store_true",
        help="persist the advisory run and decision; without this only builds a dry-run preview",
    )
    agent_review.add_argument(
        "--online-tools",
        action="store_true",
        help="allow external TradingAgents tools to fetch online data if the optional package is installed",
    )
    agent_review.add_argument(
        "--mode",
        choices=["local_snapshot_mode", "external_graph_mode"],
        default="local_snapshot_mode",
        help="TradingAgents execution mode; local_snapshot_mode uses PGC database snapshots only",
    )
    agent_review.add_argument(
        "--llm-provider",
        default="deepseek",
        help="TradingAgents LLM provider, for example deepseek, openai, google, anthropic, qwen",
    )
    agent_review.add_argument(
        "--deep-think-llm",
        default="deepseek-v4-pro",
        help="TradingAgents model for complex reasoning",
    )
    agent_review.add_argument(
        "--quick-think-llm",
        default="deepseek-v4-pro",
        help="TradingAgents model for quick tasks",
    )
    agent_review.add_argument(
        "--max-debate-rounds",
        type=_positive_int,
        default=3,
        help="TradingAgents bull/bear debate rounds",
    )
    agent_review.add_argument(
        "--max-risk-discuss-rounds",
        type=_positive_int,
        default=1,
        help="TradingAgents risk discussion rounds",
    )
    _add_lifecycle_context_arguments(agent_review)
    _add_db_path_argument(agent_review)
    agent_review.set_defaults(handler=_run_agent_review)

    agent_external_data = agent_subparsers.add_parser(
        "external-data",
        help="import cached external advisory data for Agent snapshots",
        stdout=stdout,
        stderr=stderr,
    )
    external_data_subparsers = agent_external_data.add_subparsers(
        dest="agent_external_data_command",
        metavar="external-data-command",
    )
    external_data_import = external_data_subparsers.add_parser(
        "import",
        help="preview or apply a JSON import into agent_external_items",
        stdout=stdout,
        stderr=stderr,
    )
    external_data_import.add_argument("--file", "--input", dest="source_file", type=Path, required=True)
    external_data_import.add_argument(
        "--date",
        dest="import_date",
        help="default compact YYYYMMDD published date for structured cached items",
    )
    external_data_import.add_argument(
        "--source",
        dest="import_source",
        help="default provider/source for structured cached items",
    )
    external_data_import.add_argument(
        "--apply",
        action="store_true",
        help="write agent_external_items instead of running a dry-run preview",
    )
    _add_lifecycle_context_arguments(external_data_import)
    _add_db_path_argument(external_data_import)
    external_data_import.set_defaults(handler=_run_agent_external_data_import)

    ops = subparsers.add_parser(
        "ops",
        help="run repeatable deployment and maintenance steps",
        stdout=stdout,
        stderr=stderr,
    )
    ops_subparsers = ops.add_subparsers(dest="ops_command", metavar="ops-command")

    ops_version = ops_subparsers.add_parser(
        "version",
        help="print the package version and standard release tag",
        stdout=stdout,
        stderr=stderr,
    )
    ops_version.add_argument("--date", type=_parse_report_date, help="release date in ISO or YYYYMMDD format")
    ops_version.add_argument("--git-sha", help="optional git commit sha to include in the release tag")
    ops_version.set_defaults(handler=_run_ops_version)

    ops_backup = ops_subparsers.add_parser(
        "backup",
        help="create a timestamped SQLite backup",
        stdout=stdout,
        stderr=stderr,
    )
    _add_db_path_argument(ops_backup)
    ops_backup.add_argument("--backup-dir", type=Path, help="backup destination directory")
    ops_backup.add_argument("--label", default="manual_ops_backup", help="label included in the backup filename")
    ops_backup.set_defaults(handler=_run_ops_backup)

    ops_migrate = ops_subparsers.add_parser(
        "migrate",
        help="run storage migrations with an optional pre-migration backup",
        stdout=stdout,
        stderr=stderr,
    )
    _add_db_path_argument(ops_migrate)
    ops_migrate.add_argument("--dry-run", action="store_true", help="show pending migrations without writing")
    ops_migrate.add_argument("--backup", action="store_true", help="backup the existing database before migrating")
    ops_migrate.add_argument("--backup-dir", type=Path, help="backup destination directory")
    ops_migrate.add_argument(
        "--backup-label",
        default="before_ops_migrate",
        help="label included in the pre-migration backup filename",
    )
    ops_migrate.set_defaults(handler=_run_ops_migrate)

    ops_health = ops_subparsers.add_parser(
        "health",
        help="check database migration state and optional API health",
        stdout=stdout,
        stderr=stderr,
    )
    _add_db_path_argument(ops_health)
    ops_health.add_argument("--health-url", help="optional API health URL to verify")
    ops_health.add_argument(
        "--require-current-migrations",
        action="store_true",
        help="return non-zero when storage migrations are pending",
    )
    ops_health.set_defaults(handler=_run_ops_health)

    ops_ledger_audit = ops_subparsers.add_parser(
        "ledger-audit",
        help="run read-only ledger consistency checks for an account",
        stdout=stdout,
        stderr=stderr,
    )
    _add_report_date_argument(ops_ledger_audit)
    _add_account_arguments(ops_ledger_audit)
    _add_db_path_argument(ops_ledger_audit)
    ops_ledger_audit.set_defaults(handler=_run_ops_ledger_audit)

    ops_ledger_repair = ops_subparsers.add_parser(
        "ledger-repair",
        help="preview or apply known ledger consistency repairs for an account",
        stdout=stdout,
        stderr=stderr,
    )
    _add_report_date_argument(ops_ledger_repair)
    _add_account_arguments(ops_ledger_repair)
    _add_db_path_argument(ops_ledger_repair)
    ledger_repair_mode = ops_ledger_repair.add_mutually_exclusive_group()
    ledger_repair_mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="preview repair SQL intents without writing; this is the default",
    )
    ledger_repair_mode.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="apply known repairs after printing SQL intents",
    )
    ops_ledger_repair.add_argument("--operator", help="operator name; required with --apply")
    ops_ledger_repair.add_argument("--backup-dir", type=Path, help="backup destination directory for --apply")
    ops_ledger_repair.set_defaults(handler=_run_ops_ledger_repair)

    ops_daily_pipeline = ops_subparsers.add_parser(
        "daily-pipeline",
        help="run the repeatable daily operating pipeline",
        stdout=stdout,
        stderr=stderr,
    )
    _add_report_date_argument(ops_daily_pipeline)
    _add_account_arguments(ops_daily_pipeline)
    ops_daily_pipeline.add_argument("--strategy-version", default=STRATEGY_VERSION, help="strategy version to run")
    ops_daily_pipeline.add_argument(
        "--run-type",
        choices=["research", "backtest", "validation", "paper", "live"],
        default="paper",
        help="workflow run type",
    )
    mode = ops_daily_pipeline.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="apply", action="store_false", help="preview pipeline writes")
    mode.add_argument("--apply", dest="apply", action="store_true", help="persist daily pipeline writes")
    ops_daily_pipeline.set_defaults(apply=False)
    ops_daily_pipeline.add_argument("--operator", help="operator name; required with --apply")
    ops_daily_pipeline.add_argument("--idempotency-key", help="optional base idempotency key for pipeline steps")
    ops_daily_pipeline.add_argument("--backup-dir", type=Path, help="backup destination directory for --apply")
    _add_live_write_guard_argument(ops_daily_pipeline)
    _add_db_path_argument(ops_daily_pipeline)
    ops_daily_pipeline.set_defaults(handler=_run_ops_daily_pipeline)

    return parser


def _run_review(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    db_path = _normalized_db_path(args.db_path)
    review_date = args.date

    if not db_path.exists():
        _write_routed_message(
            stdout,
            args.command,
            review_date,
            db_path,
            "database not found; review service was not run and no writes were performed",
        )
        return 0

    service = services.review_service_factory(db_path)
    request = RunDailyReviewRequest(as_of_date=review_date)
    ctx = RequestContext(dry_run=True, operator="cli", source="cli")
    try:
        result = service.run_daily_review(request, ctx)
    except sqlite3.OperationalError as exc:
        stdout.write(f"review failed for {review_date}: database is not initialized or is incompatible: {exc}\n")
        return 1

    _write_service_result(stdout, args.command, review_date, db_path, result)
    return 0 if result.ok else 1


def _run_daily_close(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    db_path = _normalized_db_path(args.db_path)
    as_of_date = args.date

    if not db_path.exists():
        _write_routed_message(
            stdout,
            args.command,
            as_of_date,
            db_path,
            "database not found; daily close workflow was not run and no writes were performed",
        )
        return 1

    service = services.daily_close_workflow_service_factory(db_path)
    request = RunDailyCloseWorkflowRequest(
        as_of_date=as_of_date,
        strategy_version=args.strategy_version,
        account_key=args.account_key,
        account_id=args.account_id,
        run_type=args.run_type,
        force_new_review_run=args.force_new_review_run,
    )
    ctx = RequestContext(
        request_id="cli-daily-close",
        idempotency_key=args.idempotency_key or _daily_close_idempotency_key(args),
        dry_run=not args.apply,
        operator=args.operator,
        source="cli",
        allow_live_writes=args.allow_live_writes,
    )
    try:
        result = service.run_daily_close(request, ctx)
    except sqlite3.OperationalError as exc:
        stdout.write(f"daily-close failed for {as_of_date}: database is not initialized or is incompatible: {exc}\n")
        return 1

    _write_daily_close_result(stdout, args.command, as_of_date, db_path, result)
    return 0 if result.ok else 1


def _run_plan(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    db_path = _normalized_db_path(args.db_path)
    review_date = args.date

    if not db_path.exists():
        _write_routed_message(
            stdout,
            args.command,
            review_date,
            db_path,
            "database not found; planning service was not run and no writes were performed",
        )
        return 1

    service = services.planning_service_factory(db_path)
    request = GenerateBuyPlanRequest(
        account_key=args.account_key,
        account_id=args.account_id,
        daily_pick_id=args.daily_pick_id,
        review_date=review_date,
        planned_trade_date=args.planned_trade_date,
        agent_decision_id=args.agent_decision_id,
    )
    ctx = RequestContext(
        request_id="cli-plan",
        idempotency_key=args.idempotency_key or _plan_idempotency_key(args),
        dry_run=not args.apply,
        operator=args.operator,
        source="cli",
        allow_live_writes=args.allow_live_writes,
    )
    try:
        result = service.generate_buy_plan(request, ctx)
    except sqlite3.OperationalError as exc:
        stdout.write(f"plan failed for {review_date}: database is not initialized or is incompatible: {exc}\n")
        return 1

    _write_plan_result(stdout, args.command, review_date, db_path, result)
    return 0 if result.ok else 1


def _run_plan_cancel(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    db_path = _normalized_db_path(args.db_path)

    if not db_path.exists():
        _write_routed_message(
            stdout,
            args.command,
            f"plan-id={args.plan_id}",
            db_path,
            "database not found; planning service was not run and no writes were performed",
        )
        return 1

    service = services.planning_service_factory(db_path)
    request = CancelTradePlanRequest(
        trade_plan_id=args.plan_id,
        cancel_reason=args.reason,
        account_key=args.account_key,
        account_id=args.account_id,
    )
    ctx = RequestContext(
        request_id="cli-plan-cancel",
        idempotency_key=args.idempotency_key,
        operator=args.operator,
        source="cli",
        allow_live_writes=args.allow_live_writes,
    )
    try:
        result = service.cancel_plan(request, ctx)
    except sqlite3.OperationalError as exc:
        stdout.write(f"plan-cancel failed for plan-id={args.plan_id}: database is not initialized or is incompatible: {exc}\n")
        return 1

    _write_plan_cancel_result(stdout, args.command, args.plan_id, db_path, result)
    return 0 if result.ok else 1


def _run_record_buy(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    db_path = _normalized_db_path(args.db_path)
    executed_date = args.date

    if not db_path.exists():
        _write_routed_message(
            stdout,
            args.command,
            executed_date,
            db_path,
            "database not found; execution service was not run and no writes were performed",
        )
        return 1

    service = services.execution_service_factory(db_path)
    request = RecordTradeRequest(
        trade_plan_id=args.plan_id,
        side="buy",
        executed_date=executed_date,
        executed_price=args.price,
        shares=args.shares,
        account_key=args.account_key,
        account_id=args.account_id,
        fee=args.fee,
        tax=args.tax,
        source=args.source,
    )
    try:
        result = service.record_trade(request, _execution_context(args, "record-buy"))
    except sqlite3.OperationalError as exc:
        stdout.write(f"record-buy failed for {executed_date}: database is not initialized or is incompatible: {exc}\n")
        return 1

    _write_service_result(stdout, args.command, executed_date, db_path, result)
    return 0 if result.ok else 1


def _run_record_sell(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    db_path = _normalized_db_path(args.db_path)
    executed_date = args.date

    if not db_path.exists():
        _write_routed_message(
            stdout,
            args.command,
            executed_date,
            db_path,
            "database not found; execution service was not run and no writes were performed",
        )
        return 1

    service = services.execution_service_factory(db_path)
    request = RecordPositionSellRequest(
        position_id=args.position_id,
        executed_date=executed_date,
        executed_price=args.price,
        shares=args.shares,
        account_key=args.account_key,
        account_id=args.account_id,
        fee=args.fee,
        tax=args.tax,
        source=args.source,
    )
    try:
        result = service.record_position_sell(request, _execution_context(args, "record-sell"))
    except sqlite3.OperationalError as exc:
        stdout.write(f"record-sell failed for {executed_date}: database is not initialized or is incompatible: {exc}\n")
        return 1

    _write_service_result(stdout, args.command, executed_date, db_path, result)
    return 0 if result.ok else 1


def _run_positions(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    db_path = _normalized_db_path(args.db_path)
    as_of_date = args.date

    if not db_path.exists():
        _write_routed_message(
            stdout,
            args.command,
            as_of_date,
            db_path,
            "database not found; position service was not run and no writes were performed",
        )
        return 0

    service = services.position_service_factory(db_path)
    request = ListPositionsRequest(
        as_of_date=as_of_date,
        account_key=args.account_key,
        account_id=args.account_id,
    )
    try:
        ctx = RequestContext(request_id="cli-positions", operator="cli", source="cli")
        result = service.list_positions(request, ctx)
    except sqlite3.OperationalError as exc:
        stdout.write(f"positions failed for {as_of_date}: database is not initialized or is incompatible: {exc}\n")
        return 1

    _write_positions_result(stdout, args.command, as_of_date, db_path, result)
    return 0 if result.ok else 1


def _run_exits_evaluate(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    db_path = _normalized_db_path(args.db_path)
    as_of_date = args.date

    if not db_path.exists():
        _write_routed_message(
            stdout,
            args.command,
            as_of_date,
            db_path,
            "database not found; position service was not run and no writes were performed",
        )
        return 1

    service = services.position_service_factory(db_path)
    request = EvaluateExitsRequest(
        as_of_date=as_of_date,
        account_key=args.account_key,
        account_id=args.account_id,
        generate_sell_plans=not args.no_generate_sell_plans,
    )
    ctx = RequestContext(
        request_id="cli-exits-evaluate",
        idempotency_key=args.idempotency_key or _exit_idempotency_key(args),
        operator=args.operator,
        source="cli",
        allow_live_writes=args.allow_live_writes,
    )
    try:
        result = service.evaluate_exits(request, ctx)
    except sqlite3.OperationalError as exc:
        stdout.write(f"exits-evaluate failed for {as_of_date}: database is not initialized or is incompatible: {exc}\n")
        return 1

    _write_exit_evaluation_result(stdout, args.command, as_of_date, db_path, result)
    return 0 if result.ok else 1


def _run_paper_readiness(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    db_path = _normalized_db_path(args.db_path)
    as_of_date = args.date

    if not db_path.exists():
        _write_routed_message(
            stdout,
            args.command,
            as_of_date,
            db_path,
            "database not found; paper readiness gate was not run and no writes were performed",
        )
        return 1

    service = services.operational_readiness_service_factory(db_path)
    request = PaperReadinessRequest(
        as_of_date=as_of_date,
        account_key=args.account_key,
        account_id=args.account_id,
        min_trades=args.min_trades,
    )
    ctx = RequestContext(request_id="cli-paper-readiness", dry_run=True, operator="cli", source="cli")
    try:
        result = service.check_paper_readiness(request, ctx)
    except sqlite3.OperationalError as exc:
        stdout.write(f"paper-readiness failed for {as_of_date}: database is not initialized or is incompatible: {exc}\n")
        return 1

    _write_paper_readiness_result(stdout, args.command, as_of_date, db_path, result)
    return 0 if result.ok else 1


def _run_agent_review(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    db_path = _normalized_db_path(args.db_path)
    command = "agent review"

    if not db_path.exists():
        _write_routed_message(
            stdout,
            command,
            f"daily-pick-id={args.daily_pick_id}",
            db_path,
            "database not found; agent review service was not run and no writes were performed",
        )
        return 1

    service = services.agent_review_service_factory(db_path)
    request = ReviewDailyPickRequest(
        daily_pick_id=args.daily_pick_id,
        account_key=args.account_key,
        account_id=args.account_id,
        mode=args.mode,
        online_tools=args.online_tools,
        llm_provider=args.llm_provider,
        deep_think_llm=args.deep_think_llm,
        quick_think_llm=args.quick_think_llm,
        max_debate_rounds=args.max_debate_rounds,
        max_risk_discuss_rounds=args.max_risk_discuss_rounds,
    )
    ctx = RequestContext(
        request_id="cli-agent-review",
        idempotency_key=args.idempotency_key or _agent_review_idempotency_key(args),
        dry_run=not args.apply,
        operator=args.operator,
        source="cli",
    )
    try:
        result = service.review_daily_pick(request, ctx)
    except sqlite3.OperationalError as exc:
        stdout.write(
            f"agent review failed for daily-pick-id={args.daily_pick_id}: "
            f"database is not initialized or is incompatible: {exc}\n"
        )
        return 1

    _write_agent_review_result(stdout, command, args.daily_pick_id, db_path, result)
    return 0 if result.ok else 1


def _run_agent_external_data_import(
    args: argparse.Namespace,
    stdout: TextIO,
    services: CommandServices,
) -> int:
    db_path = _normalized_db_path(args.db_path)
    source_file = _normalized_db_path(args.source_file)
    command = "agent external-data import"

    if not db_path.exists():
        _write_routed_message(
            stdout,
            command,
            f"file={source_file}",
            db_path,
            "database not found; external data import service was not run and no writes were performed",
        )
        return 1

    service = services.agent_external_data_service_factory(db_path)
    request = ImportAgentExternalDataRequest(
        source_file=source_file,
        default_provider=args.import_source,
        default_published_date=args.import_date,
    )
    ctx = RequestContext(
        request_id="cli-agent-external-data-import",
        idempotency_key=args.idempotency_key,
        dry_run=not args.apply,
        operator=args.operator,
        source="cli",
    )
    try:
        result = service.import_external_data(request, ctx)
    except sqlite3.OperationalError as exc:
        stdout.write(
            f"agent external-data import failed for file={source_file}: "
            f"database is not initialized or is incompatible: {exc}\n"
        )
        return 1

    _write_agent_external_data_import_result(stdout, command, source_file, db_path, result)
    return 0 if result.ok else 1


def _run_report(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    db_path = _normalized_db_path(args.db_path)
    report_date = args.date

    if args.output is not None and args.write_live_plan:
        stdout.write("report failed: choose either --output or --write-live-plan, not both.\n")
        return 1

    if not db_path.exists():
        _write_routed_message(
            stdout,
            args.command,
            report_date,
            db_path,
            "database not found; report service was not run and no writes were performed",
        )
        return 0

    service = services.report_service_factory(db_path)
    try:
        result = service.get_daily_report(
            DailyReportRequest(
                as_of_date=report_date,
                account_key=args.account_key,
                account_id=args.account_id,
                strategy_version=args.strategy_version,
            ),
            RequestContext(request_id="cli-report", operator="cli", source="cli"),
        )
    except sqlite3.OperationalError as exc:
        stdout.write(f"report failed for {report_date}: database is not initialized or is incompatible: {exc}\n")
        return 1

    if result.data is None:
        _write_service_result(stdout, args.command, report_date, db_path, result)
        return 0 if result.ok else 1

    rendered = (
        render_daily_report_json(result.data)
        if args.format == "json"
        else render_daily_report_markdown(result.data)
    )
    output_path = _report_output_path(args)
    if output_path is None:
        stdout.write(rendered)
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    stdout.write(f"report written for {report_date}: {output_path}\n")
    return 0


def _run_ops_version(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    tag = build_release_tag(date=args.date, git_sha=args.git_sha)
    stdout.write("ops version command routed.\n")
    stdout.write(f"package_version={__version__}\n")
    stdout.write(f"api_version={__version__}\n")
    stdout.write(f"release_tag={tag}\n")
    return 0


def _run_ops_backup(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    db_path = _normalized_db_path(args.db_path)
    backup_dir = _normalized_db_path(args.backup_dir) if args.backup_dir is not None else None
    try:
        backup_path = backup_database(db_path, backup_dir=backup_dir, label=args.label)
    except (FileNotFoundError, ValueError, FileExistsError) as exc:
        stdout.write(f"ops backup failed: {exc}\n")
        return 1

    stdout.write(f"ops backup command routed using database {db_path}.\n")
    stdout.write(f"backup_path={backup_path}\n")
    return 0


def _run_ops_migrate(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    db_path = _normalized_db_path(args.db_path)
    backup_dir = _normalized_db_path(args.backup_dir) if args.backup_dir is not None else None
    try:
        result = run_ops_migration_step(
            db_path,
            dry_run=args.dry_run,
            backup=args.backup,
            backup_dir=backup_dir,
            backup_label=args.backup_label,
        )
    except Exception as exc:
        stdout.write(f"ops migrate failed: {exc}\n")
        return 1

    stdout.write(f"ops migrate command routed using database {result.db_path}.\n")
    stdout.write(f"dry_run={str(result.dry_run).lower()}\n")
    stdout.write(f"backup_path={result.backup_path if result.backup_path is not None else 'none'}\n")
    stdout.write(f"applied={_display_list(result.applied)}\n")
    stdout.write(f"skipped={_display_list(result.skipped)}\n")
    stdout.write(f"changed={str(result.changed).lower()}\n")
    return 0


def _run_ops_health(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    db_path = _normalized_db_path(args.db_path)
    result = run_ops_health_check(db_path, health_url=args.health_url)

    stdout.write(f"ops health command routed using database {result.db_path}.\n")
    stdout.write(f"status={result.status}\n")
    stdout.write(f"database_exists={str(result.database_exists).lower()}\n")
    stdout.write(f"latest_migration={result.latest_migration or 'none'}\n")
    stdout.write(f"pending_migrations={_display_list(result.pending_migrations)}\n")
    stdout.write(f"package_version={result.package_version}\n")
    stdout.write(f"api_version={result.api_version}\n")
    if result.database_error is not None:
        stdout.write(f"database_error={result.database_error}\n")
    if result.api_health is not None:
        stdout.write(f"api_health_ok={str(result.api_health.ok).lower()}\n")
        stdout.write(f"api_health_url={result.api_health.url}\n")
        if result.api_health.status_code is not None:
            stdout.write(f"api_health_status_code={result.api_health.status_code}\n")
        if result.api_health.error is not None:
            stdout.write(f"api_health_error={result.api_health.error}\n")

    if not result.database_exists or result.database_error is not None:
        return 1
    if result.api_health is not None and not result.api_health.ok:
        return 1
    if args.require_current_migrations and result.pending_migrations:
        return 1
    return 0


def _run_ops_ledger_audit(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    db_path = _normalized_db_path(args.db_path)
    if not db_path.exists():
        stdout.write("ledger_audit_status=failed\n")
        stdout.write(f"account_key={args.account_key or 'none'}\n")
        stdout.write(f"as_of_date={args.date}\n")
        stdout.write(f"database={db_path}\n")
        stdout.write("error=database not found; ledger audit was not run and no writes were performed\n")
        return 1

    service = services.execution_service_factory(db_path)
    result = service.audit_ledger(
        LedgerAuditRequest(
            as_of_date=args.date,
            account_key=args.account_key,
            account_id=args.account_id,
        ),
        RequestContext(request_id="cli-ops-ledger-audit", dry_run=True, operator="cli", source="cli"),
    )
    _write_ledger_audit_result(stdout, result)
    return 0 if result.data is not None and result.data.ok else 1


def _run_ops_ledger_repair(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    db_path = _normalized_db_path(args.db_path)
    if not db_path.exists():
        stdout.write("ledger_repair_status=failed\n")
        stdout.write(f"account_key={args.account_key or 'none'}\n")
        stdout.write(f"as_of_date={args.date}\n")
        stdout.write(f"database={db_path}\n")
        stdout.write("error=database not found; ledger repair was not run and no writes were performed\n")
        return 1

    service = services.execution_service_factory(db_path)
    result = service.repair_ledger(
        LedgerRepairRequest(
            as_of_date=args.date,
            account_key=args.account_key,
            account_id=args.account_id,
            backup_dir=_normalized_db_path(args.backup_dir) if args.backup_dir is not None else None,
        ),
        RequestContext(
            request_id="cli-ops-ledger-repair",
            dry_run=args.dry_run,
            operator=args.operator,
            source="cli",
        ),
    )
    _write_ledger_repair_result(stdout, result)
    return 0 if result.data is not None and result.data.status in {"clean", "would_apply", "applied"} else 1


def _run_ops_daily_pipeline(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    db_path = _normalized_db_path(args.db_path)
    as_of_date = args.date

    if not db_path.exists():
        stdout.write(f"pipeline_status=failed\n")
        stdout.write(f"review_date={as_of_date}\n")
        stdout.write(f"database={db_path}\n")
        stdout.write("error=database not found; daily pipeline was not run and no writes were performed\n")
        return 1

    service = services.daily_pipeline_service_factory(db_path)
    request = RunDailyPipelineRequest(
        as_of_date=as_of_date,
        account_key=args.account_key,
        account_id=args.account_id,
        strategy_version=args.strategy_version,
        run_type=args.run_type,
        backup_dir=_normalized_db_path(args.backup_dir) if args.backup_dir is not None else None,
    )
    account_ref = args.account_key or f"account-id-{args.account_id}"
    ctx = RequestContext(
        request_id="cli-daily-pipeline",
        idempotency_key=args.idempotency_key
        or f"daily-pipeline:{account_ref}:{as_of_date}:{args.strategy_version}:{args.run_type}",
        dry_run=not args.apply,
        operator=args.operator or ("cli" if not args.apply else None),
        source="cli",
        allow_live_writes=args.allow_live_writes,
    )
    try:
        result = service.run_daily_pipeline(request, ctx)
    except sqlite3.OperationalError as exc:
        stdout.write("pipeline_status=failed\n")
        stdout.write(f"review_date={as_of_date}\n")
        stdout.write(f"database_error={exc}\n")
        return 1

    _write_daily_pipeline_result(stdout, result)
    return 0 if result.ok else 1


def _add_date_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--date",
        required=True,
        type=_parse_iso_date,
        metavar="YYYY-MM-DD",
        help="review or execution date in ISO format",
    )


def _add_report_date_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--date",
        "--as-of-date",
        required=True,
        dest="date",
        type=_parse_report_date,
        metavar="YYYY-MM-DD|YYYYMMDD",
        help="review date in ISO or YYYYMMDD format",
    )


def _add_db_path_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Paths().db_path,
        help="SQLite database path",
    )


def _add_account_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account", dest="account_key", default=DEFAULT_ACCOUNT_KEY, help="portfolio account key")
    parser.add_argument("--account-id", type=_positive_int, help="portfolio account id")


def _add_lifecycle_context_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--operator", default="cli", help="operator name for audit fields")
    parser.add_argument("--idempotency-key", help="optional idempotency key for audit logging")


def _add_live_write_guard_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--allow-live-writes",
        action="store_true",
        help="explicitly allow live account ledger writes; does not place broker orders",
    )


def _add_execution_common_arguments(parser: argparse.ArgumentParser) -> None:
    _add_account_arguments(parser)
    parser.add_argument("--fee", type=_non_negative_float, default=0.0, help="execution fee")
    parser.add_argument("--tax", type=_non_negative_float, default=0.0, help="execution tax")
    parser.add_argument(
        "--source",
        choices=["manual", "paper_model", "model", "broker_import", "correction"],
        default="manual",
        help="trade execution source",
    )
    parser.add_argument("--operator", default="cli", help="operator name for audit fields")
    parser.add_argument("--idempotency-key", help="optional idempotency key for audit logging")
    _add_live_write_guard_argument(parser)


def _parse_iso_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}: expected YYYY-MM-DD") from exc
    if parsed.strftime("%Y-%m-%d") != value:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}: expected YYYY-MM-DD")
    return parsed.strftime("%Y%m%d")


def _parse_report_date(value: str) -> str:
    if len(value) == 8 and value.isdigit():
        try:
            parsed = datetime.strptime(value, "%Y%m%d")
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid date {value!r}: expected YYYYMMDD or YYYY-MM-DD") from exc
        if parsed.strftime("%Y%m%d") != value:
            raise argparse.ArgumentTypeError(f"invalid date {value!r}: expected YYYYMMDD or YYYY-MM-DD")
        return value
    return _parse_iso_date(value)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer {value!r}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"value must be greater than zero: {value!r}")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid number {value!r}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"value must be greater than zero: {value!r}")
    return parsed


def _non_negative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid number {value!r}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"value must be zero or greater: {value!r}")
    return parsed


def _non_blank_text(value: str) -> str:
    parsed = value.strip()
    if not parsed:
        raise argparse.ArgumentTypeError("value must not be blank")
    return parsed


def _execution_context(args: argparse.Namespace, command: str) -> RequestContext:
    return RequestContext(
        request_id=f"cli-{command}",
        idempotency_key=args.idempotency_key,
        operator=args.operator,
        source=args.source,
        allow_live_writes=args.allow_live_writes,
    )


def _daily_close_idempotency_key(args: argparse.Namespace) -> str:
    account_ref = args.account_key or f"account-id-{args.account_id}"
    return f"daily-close:{account_ref}:{args.date}:{args.strategy_version}:{args.run_type}"


def _plan_idempotency_key(args: argparse.Namespace) -> str:
    account_ref = args.account_key or f"account-id-{args.account_id}"
    pick_ref = args.daily_pick_id if args.daily_pick_id is not None else args.date
    return f"plan-buy:{account_ref}:{args.date}:{pick_ref}"


def _exit_idempotency_key(args: argparse.Namespace) -> str:
    account_ref = args.account_key or f"account-id-{args.account_id}"
    return f"exit-eval:{account_ref}:{args.date}"


def _agent_review_idempotency_key(args: argparse.Namespace) -> str:
    account_ref = args.account_key or f"account-id-{args.account_id}"
    return f"agent-review:{account_ref}:daily-pick-{args.daily_pick_id}"


def _normalized_db_path(db_path: Path) -> Path:
    return db_path.expanduser()


def _report_output_path(args: argparse.Namespace) -> Path | None:
    if args.output is not None:
        return _normalized_db_path(args.output)
    if not args.write_live_plan:
        return None
    paths = Paths()
    return paths.live_plan_json if args.format == "json" else paths.live_plan_md


def _write_routed_message(
    stdout: TextIO,
    command: str,
    date: str,
    db_path: Path,
    detail: str,
) -> None:
    stdout.write(f"{command} command routed for {date} using database {db_path}.\n")
    stdout.write(f"{detail}.\n")


def _write_service_result(
    stdout: TextIO,
    command: str,
    date: str,
    db_path: Path,
    result: ServiceResult[object],
) -> None:
    _write_routed_message(stdout, command, date, db_path, f"service returned {result.status}")
    if result.warnings:
        stdout.write("warnings:\n")
        for warning in result.warnings:
            stdout.write(f"- {warning.code}: {warning.message}\n")
    if result.errors:
        stdout.write("errors:\n")
        for error in result.errors:
            stdout.write(f"- {error.code}: {error.message}\n")
    if result.data is not None:
        stdout.write(f"data: {_display_data(result.data)}\n")


def _write_daily_close_result(
    stdout: TextIO,
    command: str,
    date: str,
    db_path: Path,
    result: ServiceResult[object],
) -> None:
    _write_routed_message(stdout, command, date, db_path, f"service returned {result.status}")
    _write_warnings_and_errors(stdout, result)
    data = result.data
    if data is None:
        return

    stdout.write(f"workflow_status={getattr(data, 'workflow_status', 'n/a')}\n")
    stdout.write(f"readiness={getattr(data, 'readiness', 'n/a')}\n")
    stdout.write(f"review_status={getattr(data, 'review_status', 'n/a')}\n")
    stdout.write(f"plan_status={getattr(data, 'plan_status', 'n/a')}\n")
    stdout.write(f"next_trade_date={_display_date(getattr(data, 'next_trade_date', None))}\n")
    stdout.write(f"signals_count={getattr(data, 'signals_count', 0)}\n")

    candidate = getattr(data, "candidate", None)
    if candidate is not None:
        stdout.write(
            "candidate="
            f"{candidate.ts_code} {candidate.name} "
            f"daily_pick_id={_display_optional_int(candidate.daily_pick_id)} "
            f"score={candidate.score:.2f}\n"
        )
    else:
        stdout.write("candidate=none\n")

    buy_plan = getattr(data, "buy_plan", None)
    if buy_plan is not None:
        stdout.write(
            "buy_plan="
            f"id={_display_optional_int(buy_plan.trade_plan_id)} "
            f"action={buy_plan.action} "
            f"status={buy_plan.status} "
            f"planned_trade_date={_display_date(buy_plan.planned_trade_date)} "
            f"planned_shares={_display_optional_int(buy_plan.planned_shares)}\n"
        )
    else:
        stdout.write("buy_plan=none\n")


def _write_plan_result(
    stdout: TextIO,
    command: str,
    date: str,
    db_path: Path,
    result: ServiceResult[object],
) -> None:
    _write_routed_message(stdout, command, date, db_path, f"service returned {result.status}")
    _write_warnings_and_errors(stdout, result)
    data = result.data
    if data is None:
        return

    stdout.write(
        "trade_plan="
        f"id={_display_optional_int(getattr(data, 'trade_plan_id', None))} "
        f"action={getattr(data, 'action', 'n/a')} "
        f"status={getattr(data, 'status', 'n/a')} "
        f"reason={getattr(data, 'reason', 'n/a')} "
        f"planned_trade_date={_display_date(getattr(data, 'planned_trade_date', None))} "
        f"planned_cash={_display_optional_float(getattr(data, 'planned_cash', None))} "
        f"planned_shares={_display_optional_int(getattr(data, 'planned_shares', None))} "
        f"free_position_slots={getattr(data, 'free_position_slots', 'n/a')} "
        f"idempotent={str(bool(getattr(data, 'idempotent', False))).lower()}\n"
    )


def _write_plan_cancel_result(
    stdout: TextIO,
    command: str,
    plan_id: int,
    db_path: Path,
    result: ServiceResult[object],
) -> None:
    _write_routed_message(stdout, command, f"plan-id={plan_id}", db_path, f"service returned {result.status}")
    _write_warnings_and_errors(stdout, result)
    data = result.data
    if data is None:
        return

    stdout.write(
        "trade_plan="
        f"id={_display_optional_int(getattr(data, 'id', None))} "
        f"status={getattr(data, 'status', 'n/a')} "
        f"cancel_reason={getattr(data, 'cancel_reason', None) or 'n/a'}\n"
    )


def _write_positions_result(
    stdout: TextIO,
    command: str,
    date: str,
    db_path: Path,
    result: ServiceResult[object],
) -> None:
    _write_routed_message(stdout, command, date, db_path, f"service returned {result.status}")
    _write_warnings_and_errors(stdout, result)
    data = result.data
    if data is None or not getattr(data, "positions", []):
        stdout.write(f"positions as of {_display_date(date)}: none\n")
        return

    stdout.write(f"positions as of {_display_date(data.as_of_date)}:\n")
    for position in data.positions:
        latest = "n/a"
        if position.latest_close is not None:
            latest = f"{position.latest_close:.2f} on {_display_date(position.latest_trade_date)}"
        ret = _display_percent(position.unrealized_ret)
        due_stage = position.due_stage or "not_due"
        stdout.write(
            "- "
            f"position_id={position.position_id} "
            f"account_id={position.account_id} "
            f"account={position.account_key} "
            f"{position.ts_code} {position.name} "
            f"shares={position.shares} "
            f"status={position.status} "
            f"buy_date={_display_date(position.buy_date)} "
            f"planned_t2_date={_display_date(position.planned_t2_date)} "
            f"planned_t5_date={_display_date(position.planned_t5_date)} "
            f"due_stage={due_stage} "
            f"latest_close={latest} "
            f"unrealized_ret={ret}\n"
        )


def _write_exit_evaluation_result(
    stdout: TextIO,
    command: str,
    date: str,
    db_path: Path,
    result: ServiceResult[object],
) -> None:
    _write_routed_message(stdout, command, date, db_path, f"service returned {result.status}")
    _write_warnings_and_errors(stdout, result)
    data = result.data
    if data is None:
        return

    stdout.write(f"evaluated_positions={data.evaluated_positions}\n")
    if data.exit_decisions:
        stdout.write("exit decisions:\n")
        for decision in data.exit_decisions:
            stdout.write(
                "- "
                f"exit_decision_id={decision.exit_decision_id} "
                f"position_id={decision.position_id} "
                f"account_id={decision.account_id} "
                f"account={decision.account_key} "
                f"{decision.ts_code} {decision.name} "
                f"decision_date={_display_date(decision.decision_date)} "
                f"stage={decision.decision_stage} "
                f"decision={decision.decision} "
                f"reason={decision.reason} "
                f"return={_display_percent(decision.ret)} "
                f"planned_t2_date={_display_date(decision.planned_t2_date)} "
                f"planned_t5_date={_display_date(decision.planned_t5_date)} "
                f"planned_exit_date={_display_date(decision.planned_exit_date)} "
                f"generated_trade_plan_id={_display_optional_int(decision.generated_trade_plan_id)}\n"
            )
    else:
        stdout.write("exit decisions: none\n")

    if data.generated_trade_plan_ids:
        ids = ", ".join(str(item) for item in data.generated_trade_plan_ids)
        stdout.write(f"generated_trade_plan_ids={ids}\n")
    else:
        stdout.write("generated_trade_plan_ids=none\n")

    if data.skipped_positions:
        stdout.write("skipped positions:\n")
        for skipped in data.skipped_positions:
            stdout.write(f"- position_id={skipped.position_id} reason={skipped.reason}\n")

    stdout.write("sell trades recorded by this command: 0\n")


def _write_paper_readiness_result(
    stdout: TextIO,
    command: str,
    date: str,
    db_path: Path,
    result: ServiceResult[object],
) -> None:
    _write_routed_message(stdout, command, date, db_path, f"service returned {result.status}")
    _write_warnings_and_errors(stdout, result)
    data = result.data
    if data is None:
        return

    stdout.write(f"readiness={getattr(data, 'readiness', 'n/a')}\n")
    stdout.write(f"trades_count={getattr(data, 'trades_count', 0)}\n")
    stdout.write(f"open_positions_count={getattr(data, 'open_positions_count', 0)}\n")
    stdout.write(f"due_exit_positions_count={getattr(data, 'due_exit_positions_count', 0)}\n")
    stdout.write(f"open_blockers_count={getattr(data, 'open_blockers_count', 0)}\n")
    invariant_ok = bool(getattr(data, "invariant_ok", False))
    stdout.write(f"invariant_ok={str(invariant_ok).lower()}\n")
    stdout.write(f"ledger_blockers_count={getattr(data, 'ledger_blockers_count', 0)}\n")
    stdout.write(f"invariant_violation_codes={_display_list(getattr(data, 'invariant_violation_codes', []))}\n")


def _write_agent_review_result(
    stdout: TextIO,
    command: str,
    daily_pick_id: int,
    db_path: Path,
    result: ServiceResult[object],
) -> None:
    _write_routed_message(
        stdout,
        command,
        f"daily-pick-id={daily_pick_id}",
        db_path,
        f"service returned {result.status}",
    )
    _write_warnings_and_errors(stdout, result)
    data = result.data
    if data is None:
        return

    stdout.write(
        "agent_review="
        f"input_snapshot_id={_display_optional_int(getattr(data, 'input_snapshot_id', None))} "
        f"agent_run_id={_display_optional_int(getattr(data, 'agent_run_id', None))} "
        f"agent_decision_id={_display_optional_int(getattr(data, 'agent_decision_id', None))} "
        f"action={getattr(data, 'action', None) or 'n/a'} "
        f"risk_level={getattr(data, 'risk_level', None) or 'n/a'} "
        f"confidence={_display_optional_float(getattr(data, 'confidence', None))}\n"
    )
    summary = getattr(data, "summary", None)
    if summary:
        stdout.write(f"summary={summary}\n")
    artifact_paths = getattr(data, "artifact_paths", [])
    if artifact_paths:
        stdout.write("artifacts:\n")
        for path in artifact_paths:
            stdout.write(f"- {path}\n")


def _write_agent_external_data_import_result(
    stdout: TextIO,
    command: str,
    source_file: Path,
    db_path: Path,
    result: ServiceResult[object],
) -> None:
    _write_routed_message(
        stdout,
        command,
        f"file={source_file}",
        db_path,
        f"service returned {result.status}",
    )
    _write_warnings_and_errors(stdout, result)
    data = result.data
    if data is None:
        return

    stdout.write(
        "external_data_import="
        f"rows={getattr(data, 'row_count', 0)} "
        f"valid={getattr(data, 'valid_count', 0)} "
        f"invalid={getattr(data, 'invalid_count', 0)} "
        f"would_insert={getattr(data, 'would_insert_count', 0)} "
        f"would_update={getattr(data, 'would_update_count', 0)} "
        f"inserted={getattr(data, 'inserted_count', 0)} "
        f"updated={getattr(data, 'updated_count', 0)}\n"
    )
    invalid_records = getattr(data, "invalid_records", [])
    if invalid_records:
        stdout.write("invalid_records:\n")
        for issue in invalid_records:
            field = getattr(issue, "field", None) or "record"
            stdout.write(
                "- "
                f"record={getattr(issue, 'index', 'n/a')} "
                f"field={field} "
                f"code={getattr(issue, 'code', 'n/a')} "
                f"message={getattr(issue, 'message', 'n/a')}\n"
            )


def _write_daily_pipeline_result(stdout: TextIO, result: ServiceResult[object]) -> None:
    data = result.data
    if data is None:
        stdout.write(f"pipeline_status={result.status}\n")
        _write_warnings_and_errors(stdout, result)
        return

    stdout.write(f"pipeline_status={getattr(data, 'pipeline_status', result.status)}\n")
    stdout.write(f"review_date={getattr(data, 'review_date', 'n/a')}\n")
    stdout.write(f"next_trade_date={getattr(data, 'next_trade_date', None) or 'none'}\n")
    stdout.write(f"daily_pick_id={_display_optional_int(getattr(data, 'daily_pick_id', None))}\n")
    stdout.write(f"trade_plan_id={_display_optional_int(getattr(data, 'trade_plan_id', None))}\n")
    stdout.write(f"agent_run_id={_display_optional_int(getattr(data, 'agent_run_id', None))}\n")
    stdout.write(f"agent_decision_id={_display_optional_int(getattr(data, 'agent_decision_id', None))}\n")
    stdout.write(f"exit_decisions={getattr(data, 'exit_decisions', 0)}\n")
    stdout.write(f"report_markdown={getattr(data, 'report_markdown', None) or 'none'}\n")
    stdout.write(f"report_json={getattr(data, 'report_json', None) or 'none'}\n")
    stdout.write(f"backup_path={getattr(data, 'backup_path', None) or 'none'}\n")
    stdout.write(f"changed={str(bool(getattr(data, 'changed', False))).lower()}\n")
    stdout.write(f"ledger_audit_ok={str(bool(getattr(data, 'ledger_audit_ok', False))).lower()}\n")
    stdout.write(f"daily_close_status={getattr(data, 'daily_close_status', None) or 'none'}\n")
    stdout.write(f"agent_status={getattr(data, 'agent_status', None) or 'none'}\n")
    stdout.write(f"exit_status={getattr(data, 'exit_status', None) or 'none'}\n")
    stdout.write(f"report_status={getattr(data, 'report_status', None) or 'none'}\n")
    stdout.write(f"report_would_write={str(bool(getattr(data, 'report_would_write', False))).lower()}\n")
    _write_warnings_and_errors(stdout, result)


def _write_ledger_audit_result(stdout: TextIO, result: ServiceResult[object]) -> None:
    data = result.data
    if data is None:
        stdout.write("ledger_audit_status=failed\n")
        _write_warnings_and_errors(stdout, result)
        return

    violations = getattr(data, "violations", [])
    stdout.write(f"ledger_audit_status={'pass' if not violations else 'fail'}\n")
    stdout.write(f"account_key={getattr(data, 'account_key', 'n/a')}\n")
    stdout.write(f"account_id={getattr(data, 'account_id', 'n/a')}\n")
    stdout.write(f"as_of_date={getattr(data, 'as_of_date', 'n/a')}\n")
    stdout.write(f"open_positions={getattr(data, 'open_positions', 0)}\n")
    stdout.write(f"active_plans={getattr(data, 'active_plans', 0)}\n")
    stdout.write(f"violations={len(violations)}\n")
    _write_invariant_violation_lines(stdout, violations)


def _write_ledger_repair_result(stdout: TextIO, result: ServiceResult[object]) -> None:
    data = result.data
    if data is None:
        stdout.write("ledger_repair_status=failed\n")
        _write_warnings_and_errors(stdout, result)
        return

    actions = getattr(data, "actions", [])
    unknown = getattr(data, "unknown_violations", [])
    remaining = getattr(data, "remaining_violations", [])
    stdout.write(f"ledger_repair_status={getattr(data, 'status', result.status)}\n")
    stdout.write(f"account_key={getattr(data, 'account_key', 'n/a')}\n")
    stdout.write(f"account_id={getattr(data, 'account_id', 'n/a')}\n")
    stdout.write(f"as_of_date={getattr(data, 'as_of_date', 'n/a')}\n")
    stdout.write(f"dry_run={str(bool(getattr(data, 'dry_run', True))).lower()}\n")
    stdout.write(f"backup_required={str(bool(getattr(data, 'backup_required', False))).lower()}\n")
    stdout.write(f"backup_path={getattr(data, 'backup_path', None) or 'none'}\n")
    stdout.write(f"repair_actions={len(actions)}\n")
    for action in actions:
        stdout.write(
            "repair_action="
            f"code={getattr(action, 'code', 'n/a')} "
            f"entity={getattr(action, 'entity', 'database')} "
            f"intent={_shell_value(getattr(action, 'intent', 'n/a'))} "
            f"sql={_shell_value(getattr(action, 'sql', ''))} "
            f"params={_shell_value(_display_params(getattr(action, 'params', ())))}\n"
        )
    if unknown:
        stdout.write(f"unknown_violations={len(unknown)}\n")
        _write_invariant_violation_lines(stdout, unknown)
    if getattr(data, "status", "") == "applied_with_remaining_violations":
        stdout.write(f"remaining_violations={len(remaining)}\n")
        _write_invariant_violation_lines(stdout, remaining)
    _write_warnings_and_errors(stdout, result)


def _write_invariant_violation_lines(stdout: TextIO, violations: list[object]) -> None:
    for violation in violations:
        code = getattr(violation, "code", "UNKNOWN")
        severity = getattr(violation, "severity", "blocker")
        for entity in _violation_entities(violation):
            stdout.write(f"violation_code={code} entity={entity} severity={severity}\n")


def _violation_entities(violation: object) -> list[str]:
    details = getattr(violation, "details", {}) or {}
    rows = details.get("rows") if isinstance(details, dict) else None
    if isinstance(rows, list) and rows:
        return [_entity_for_row(row) for row in rows if isinstance(row, dict)] or ["database"]
    for key, prefix in (
        ("position_ids", "position"),
        ("trade_ids", "trade"),
        ("trade_plan_ids", "trade_plan"),
        ("equity_snapshot_ids", "equity_snapshot"),
    ):
        values = details.get(key) if isinstance(details, dict) else None
        if isinstance(values, list) and values:
            return [f"{prefix}:{value}" for value in values]
    return ["database"]


def _entity_for_row(row: dict[str, object]) -> str:
    for key, prefix in (
        ("position_id", "position"),
        ("trade_id", "trade"),
        ("trade_plan_id", "trade_plan"),
        ("equity_snapshot_id", "equity_snapshot"),
        ("account_id", "account"),
    ):
        value = row.get(key)
        if value is not None:
            return f"{prefix}:{value}"
    return "database"


def _display_params(params: tuple[object, ...]) -> str:
    return "[" + ",".join("null" if value is None else str(value) for value in params) + "]"


def _shell_value(value: object) -> str:
    text = str(value).replace("\n", " ")
    if not text:
        return "''"
    if any(char.isspace() for char in text):
        return repr(text)
    return text


def _write_warnings_and_errors(stdout: TextIO, result: ServiceResult[object]) -> None:
    if result.warnings:
        stdout.write("warnings:\n")
        for warning in result.warnings:
            stdout.write(f"- {warning.code}: {warning.message}\n")
    if result.errors:
        stdout.write("errors:\n")
        for error in result.errors:
            stdout.write(f"- {error.code}: {error.message}\n")


def _display_date(value: str | None) -> str:
    if value is None:
        return "n/a"
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def _display_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def _display_optional_int(value: int | None) -> str:
    return "none" if value is None else str(value)


def _display_optional_float(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _display_list(values: list[str]) -> str:
    return ",".join(values) if values else "none"


def _display_data(data: object) -> object:
    if is_dataclass(data):
        return asdict(data)
    return data


if __name__ == "__main__":
    raise SystemExit(main())
