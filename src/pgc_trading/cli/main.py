"""CLI entrypoints for PGC trading workflows."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, TextIO

from pgc_trading.config import Paths
from pgc_trading.reporting.daily_report import (
    DailyReportRequest,
    ReportingQueryService,
    render_daily_report_json,
    render_daily_report_markdown,
)
from pgc_trading.services.common import RequestContext, ServiceResult
from pgc_trading.services.daily_close_workflow_service import (
    DEFAULT_ACCOUNT_KEY,
    DailyCloseWorkflowService,
    RunDailyCloseWorkflowRequest,
)
from pgc_trading.services.daily_review_service import DailyReviewService, RunDailyReviewRequest
from pgc_trading.services.execution_recording_service import (
    ExecutionRecordingService,
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


ReviewServiceFactory = Callable[[Path], DailyReviewService]
CloseServiceFactory = Callable[[Path], DailyCloseWorkflowService]
ReportServiceFactory = Callable[[Path], ReportingQueryService]
ExecutionServiceFactory = Callable[[Path], ExecutionRecordingService]
PositionServiceFactory = Callable[[Path], PositionLifecycleService]
OperationalReadinessServiceFactory = Callable[[Path], OperationalReadinessService]
PlanningServiceFactory = Callable[[Path], PortfolioPlanningService]


@dataclass(frozen=True)
class CommandServices:
    daily_close_workflow_service_factory: CloseServiceFactory = DailyCloseWorkflowService
    review_service_factory: ReviewServiceFactory = DailyReviewService
    report_service_factory: ReportServiceFactory = ReportingQueryService
    execution_service_factory: ExecutionServiceFactory = ExecutionRecordingService
    position_service_factory: PositionServiceFactory = PositionLifecycleService
    operational_readiness_service_factory: OperationalReadinessServiceFactory = OperationalReadinessService
    planning_service_factory: PlanningServiceFactory = PortfolioPlanningService


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


def _display_data(data: object) -> object:
    if is_dataclass(data):
        return asdict(data)
    return data


if __name__ == "__main__":
    raise SystemExit(main())
