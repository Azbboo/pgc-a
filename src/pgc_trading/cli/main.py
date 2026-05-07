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
from pgc_trading.services.daily_close_workflow_service import DEFAULT_ACCOUNT_KEY
from pgc_trading.services.daily_review_service import DailyReviewService, RunDailyReviewRequest
from pgc_trading.services.execution_recording_service import (
    ExecutionRecordingService,
    RecordPositionSellRequest,
    RecordTradeRequest,
)
from pgc_trading.strategies.cpb_6157 import STRATEGY_VERSION


ReviewServiceFactory = Callable[[Path], DailyReviewService]
ReportServiceFactory = Callable[[Path], ReportingQueryService]
ExecutionServiceFactory = Callable[[Path], ExecutionRecordingService]


@dataclass(frozen=True)
class CommandServices:
    review_service_factory: ReviewServiceFactory = DailyReviewService
    report_service_factory: ReportServiceFactory = ReportingQueryService
    execution_service_factory: ExecutionServiceFactory = ExecutionRecordingService


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

    plan = subparsers.add_parser(
        "plan",
        help="route a buy-plan draft request",
        stdout=stdout,
        stderr=stderr,
    )
    _add_date_argument(plan)
    _add_db_path_argument(plan)
    plan.set_defaults(handler=_run_placeholder)

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
    _add_db_path_argument(positions)
    positions.set_defaults(handler=_run_placeholder)

    exits_evaluate = subparsers.add_parser(
        "exits-evaluate",
        help="route position exit evaluation",
        stdout=stdout,
        stderr=stderr,
    )
    _add_date_argument(exits_evaluate)
    _add_db_path_argument(exits_evaluate)
    exits_evaluate.set_defaults(handler=_run_placeholder)

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


def _run_placeholder(args: argparse.Namespace, stdout: TextIO, services: CommandServices) -> int:
    del services
    _write_routed_message(
        stdout,
        args.command,
        args.date,
        _normalized_db_path(args.db_path),
        "service implementation pending; no writes were performed",
    )
    return 0


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


def _add_execution_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account", dest="account_key", default=DEFAULT_ACCOUNT_KEY, help="portfolio account key")
    parser.add_argument("--account-id", type=_positive_int, help="portfolio account id")
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


def _execution_context(args: argparse.Namespace, command: str) -> RequestContext:
    return RequestContext(
        request_id=f"cli-{command}",
        idempotency_key=args.idempotency_key,
        operator=args.operator,
        source=args.source,
    )


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


def _display_data(data: object) -> object:
    if is_dataclass(data):
        return asdict(data)
    return data


if __name__ == "__main__":
    raise SystemExit(main())
