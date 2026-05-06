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
from pgc_trading.services.common import RequestContext, ServiceResult
from pgc_trading.services.daily_review_service import DailyReviewService, RunDailyReviewRequest


ReviewServiceFactory = Callable[[Path], DailyReviewService]


@dataclass(frozen=True)
class CommandServices:
    review_service_factory: ReviewServiceFactory = DailyReviewService


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
        help="route daily review report output",
        stdout=stdout,
        stderr=stderr,
    )
    _add_date_argument(report)
    _add_db_path_argument(report)
    report.set_defaults(handler=_run_placeholder)

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
    _add_db_path_argument(record_buy)
    record_buy.set_defaults(handler=_run_placeholder)

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
    _add_db_path_argument(record_sell)
    record_sell.set_defaults(handler=_run_placeholder)

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


def _add_date_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--date",
        required=True,
        type=_parse_iso_date,
        metavar="YYYY-MM-DD",
        help="review or execution date in ISO format",
    )


def _add_db_path_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Paths().db_path,
        help="SQLite database path",
    )


def _parse_iso_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}: expected YYYY-MM-DD") from exc
    if parsed.strftime("%Y-%m-%d") != value:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}: expected YYYY-MM-DD")
    return parsed.strftime("%Y%m%d")


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


def _normalized_db_path(db_path: Path) -> Path:
    return db_path.expanduser()


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
