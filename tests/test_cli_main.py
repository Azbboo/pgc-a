from __future__ import annotations

import io
import tempfile
import unittest
from dataclasses import dataclass
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


class _UnexpectedReviewService:
    def __init__(self, db_path: Path):
        raise AssertionError(f"review service should not be built for missing db: {db_path}")


class CliMainTest(unittest.TestCase):
    def setUp(self) -> None:
        _FakeReviewService.calls = []

    def test_help_lists_command_surface(self) -> None:
        stdout = io.StringIO()
        with self.assertRaises(SystemExit) as raised:
            main(["--help"], stdout=stdout)

        self.assertEqual(raised.exception.code, 0)
        output = stdout.getvalue()
        for command in ["review", "plan", "report", "record-buy", "record-sell", "positions"]:
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
        cases = [
            ["plan", "--date", "2026-05-04", "--db-path", "/private/tmp/pgc_cli.db"],
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
                "/private/tmp/pgc_cli.db",
            ],
            [
                "record-sell",
                "--position-id",
                "88",
                "--date",
                "2026-05-07",
                "--price",
                "10.92",
                "--shares",
                "6600",
                "--db-path",
                "/private/tmp/pgc_cli.db",
            ],
            ["positions", "--date", "2026-05-07", "--db-path", "/private/tmp/pgc_cli.db"],
        ]

        for argv in cases:
            with self.subTest(command=argv[0]):
                stdout = io.StringIO()
                code = main(argv, stdout=stdout)
                self.assertEqual(code, 0)
                self.assertIn(f"{argv[0]} command routed", stdout.getvalue())
                self.assertIn("no writes were performed", stdout.getvalue())

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
