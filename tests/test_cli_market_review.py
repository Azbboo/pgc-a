from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path

from pgc_trading.cli.main import CommandServices, main
from pgc_trading.services.common import RequestContext, ServiceResult
from pgc_trading.services.market_plan_context_service import MarketPlanContextResult
from pgc_trading.services.market_review_service import MarketRegimeResult
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data


class _FakeMarketReviewRunService:
    calls: list[tuple[Path, object, RequestContext]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def run_market_review(self, request, ctx: RequestContext) -> ServiceResult[MarketRegimeResult]:
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=MarketRegimeResult(
                market_review_run_id=None if ctx.dry_run else 42,
                as_of_date=request.as_of_date,
                status="success",
                regime="neutral",
                breadth_score=0.5,
                trend_score=0.5,
                volume_score=0.5,
                persistence_score=0.5,
                coverage_ratio=0.95,
                summary="Market is balanced.",
                warnings=[],
            ),
            lineage={"changed": "false" if ctx.dry_run else "true"},
        )

    def import_sector_memberships(self, request, ctx: RequestContext) -> ServiceResult[_FakeSectorImportData]:
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=_FakeSectorImportData(
                market_review_run_id=None if ctx.dry_run else 42,
                inserted_count=0 if ctx.dry_run else 9,
            ),
        )


class _UnexpectedMarketReviewRunService:
    def __init__(self, db_path: Path):
        raise AssertionError(f"market review service should not be built for missing db: {db_path}")


@dataclass(frozen=True)
class _FakeSectorImportData:
    as_of_date: str = "20260508"
    membership_as_of_date: str = "20260508"
    provider: str = "manual_fixture"
    market_review_run_id: int | None = None
    sector_count: int = 2
    member_count: int = 7
    missing_bar_count: int = 1
    would_insert_count: int = 9
    would_update_count: int = 0
    would_delete_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    deleted_count: int = 0
    unchanged_count: int = 0
    changed: bool = True
    snapshots: list[object] = field(default_factory=list)


@dataclass(frozen=True)
class _FakeMarketExternalImportData:
    as_of_date: str = "20260508"
    row_count: int = 3
    valid_count: int = 3
    invalid_count: int = 0
    would_insert_count: int = 3
    inserted_count: int = 0
    duplicate_count: int = 0
    coverage_summary: dict[str, object] = field(
        default_factory=lambda: {
            "market": "available",
            "sector": "partial",
            "stock": "partial",
            "sentiment": "partial",
            "news": "available",
            "duplicates": "none",
            "freshness": {
                "market": "fresh",
                "sector": "fresh",
                "stock": "fresh",
            },
        }
    )
    coverage_details: dict[str, object] = field(
        default_factory=lambda: {
            "as_of_date": "20260508",
            "total_count": 3,
            "duplicate_count": 0,
            "missing_scopes": [],
            "stale_scopes": [],
            "fresh_count": 3,
            "stale_count": 0,
            "by_scope": {"market": 1, "sector": 1, "stock": 1},
            "by_item_type": {"announcement": 1, "news": 1, "policy": 1},
            "sentiment": {"known_count": 2, "unknown_count": 1},
            "freshness": {
                "market": "fresh",
                "sector": "fresh",
                "stock": "fresh",
            },
        }
    )
    provider_file_contract: str = "market_external_v1"
    market_external_item_ids: list[int] = field(default_factory=list)
    invalid_records: list[object] = field(default_factory=list)


@dataclass(frozen=True)
class _FakeMarketExternalBackfillDateData:
    as_of_date: str = "20260508"
    source_files: list[str] = field(default_factory=lambda: ["external_items_20260508.json"])
    row_count: int = 3
    valid_count: int = 3
    invalid_count: int = 0
    would_insert_count: int = 3
    inserted_count: int = 0
    duplicate_count: int = 0
    coverage_summary: dict[str, object] = field(default_factory=_FakeMarketExternalImportData().coverage_summary.copy)
    coverage_details: dict[str, object] = field(default_factory=_FakeMarketExternalImportData().coverage_details.copy)


@dataclass(frozen=True)
class _FakeMarketExternalBackfillData:
    file_count: int = 2
    date_count: int = 2
    row_count: int = 4
    valid_count: int = 4
    invalid_count: int = 0
    would_insert_count: int = 4
    inserted_count: int = 0
    duplicate_count: int = 0
    coverage_qa: dict[str, object] = field(
        default_factory=lambda: {
            "date_count": 2,
            "dates": ["20260507", "20260508"],
            "ready_dates": ["20260508"],
            "blocking_dates": ["20260507"],
            "missing_scope_dates": {"market": [], "sector": ["20260507"], "stock": ["20260507"]},
            "stale_scope_dates": {"market": ["20260507"], "sector": [], "stock": []},
            "duplicate_dates": [],
        }
    )
    provider_file_contract: str = "market_external_v1"
    date_results: list[_FakeMarketExternalBackfillDateData] = field(
        default_factory=lambda: [
            _FakeMarketExternalBackfillDateData(
                as_of_date="20260507",
                source_files=["external_items_20260507.json"],
                row_count=1,
                valid_count=1,
                would_insert_count=1,
            ),
            _FakeMarketExternalBackfillDateData(),
        ]
    )
    invalid_records: list[object] = field(default_factory=list)


class _FakeMarketExternalDataService:
    calls: list[tuple[Path, object, RequestContext]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def import_external_data(self, request, ctx: RequestContext) -> ServiceResult[_FakeMarketExternalImportData]:
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=_FakeMarketExternalImportData(
                inserted_count=0 if ctx.dry_run else 3,
                market_external_item_ids=[] if ctx.dry_run else [1, 2, 3],
            ),
        )

    def backfill_external_data(self, request, ctx: RequestContext) -> ServiceResult[_FakeMarketExternalBackfillData]:
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=_FakeMarketExternalBackfillData(inserted_count=0 if ctx.dry_run else 4),
        )


class _UnexpectedMarketExternalDataService:
    def __init__(self, db_path: Path):
        raise AssertionError(f"market external data service should not be built for missing db: {db_path}")


class _FakeMarketPlanContextService:
    calls: list[tuple[Path, object, RequestContext]] = []

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def link_plan_context(self, request, ctx: RequestContext) -> ServiceResult[MarketPlanContextResult]:
        self.calls.append((self.db_path, request, ctx))
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=MarketPlanContextResult(
                market_review_run_id=42,
                trade_plan_id=request.trade_plan_id,
                alignment="aligned",
                risk_level="low",
                management_action="proceed",
                rationale="Candidate aligns with market review.",
                evidence={"candidate": {"ts_code": "000001.SZ"}},
            ),
            lineage={"changed": "false" if ctx.dry_run else "true"},
        )


class _UnexpectedMarketPlanContextService:
    def __init__(self, db_path: Path):
        raise AssertionError(f"market plan context service should not be built for missing db: {db_path}")


class CliMarketReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        _FakeMarketReviewRunService.calls = []
        _FakeMarketExternalDataService.calls = []
        _FakeMarketPlanContextService.calls = []

    def test_market_review_run_routes_to_service_with_dry_run_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_market_review.db"
            db_path.touch()
            stdout = io.StringIO()
            code = main(
                [
                    "market-review",
                    "run",
                    "--date",
                    "20260508",
                    "--db-path",
                    str(db_path),
                    "--dry-run",
                ],
                stdout=stdout,
                services=CommandServices(market_review_service_factory=_FakeMarketReviewRunService),
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(_FakeMarketReviewRunService.calls), 1)
        called_db_path, request, ctx = _FakeMarketReviewRunService.calls[0]
        self.assertEqual(called_db_path, db_path)
        self.assertEqual(request.as_of_date, "20260508")
        self.assertEqual(request.universe, "market_bars")
        self.assertEqual(request.min_coverage, 0.8)
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.request_id, "cli-market-review")
        self.assertEqual(ctx.operator, "cli")
        output = stdout.getvalue()
        self.assertIn("market_review_status=success", output)
        self.assertIn("as_of_date=20260508", output)
        self.assertIn("regime=neutral", output)
        self.assertIn("coverage_ratio=0.9500", output)
        self.assertIn("market_review_run_id=none", output)
        self.assertIn("changed=false", output)

    def test_market_review_run_apply_mode_uses_operator_and_prints_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_market_review.db"
            db_path.touch()
            stdout = io.StringIO()
            code = main(
                [
                    "market-review",
                    "run",
                    "--date",
                    "2026-05-08",
                    "--db-path",
                    str(db_path),
                    "--operator",
                    "azboo",
                    "--apply",
                ],
                stdout=stdout,
                services=CommandServices(market_review_service_factory=_FakeMarketReviewRunService),
            )

        self.assertEqual(code, 0)
        _, request, ctx = _FakeMarketReviewRunService.calls[0]
        self.assertEqual(request.as_of_date, "20260508")
        self.assertFalse(ctx.dry_run)
        self.assertEqual(ctx.operator, "azboo")
        self.assertIn("market_review_run_id=42", stdout.getvalue())
        self.assertIn("changed=true", stdout.getvalue())

    def test_market_review_run_missing_db_fails_without_creating_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            stdout = io.StringIO()
            code = main(
                ["market-review", "run", "--date", "20260508", "--db-path", str(db_path)],
                stdout=stdout,
                services=CommandServices(market_review_service_factory=_UnexpectedMarketReviewRunService),
            )

            self.assertEqual(code, 1)
            self.assertFalse(db_path.exists())
            self.assertIn("market_review_status=failed", stdout.getvalue())
            self.assertIn("database not found", stdout.getvalue())

    def test_sector_membership_import_routes_to_service_with_dry_run_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_market_review.db"
            db_path.touch()
            source_file = Path(tmp) / "sector_memberships.json"
            source_file.write_text('{"as_of_date":"20260508","provider":"manual","sectors":[]}', encoding="utf-8")
            stdout = io.StringIO()
            code = main(
                [
                    "market-review",
                    "import-sectors",
                    "--date",
                    "20260508",
                    "--input",
                    str(source_file),
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
                services=CommandServices(market_review_service_factory=_FakeMarketReviewRunService),
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(_FakeMarketReviewRunService.calls), 1)
        called_db_path, request, ctx = _FakeMarketReviewRunService.calls[0]
        self.assertEqual(called_db_path, db_path)
        self.assertEqual(request.as_of_date, "20260508")
        self.assertEqual(request.source_file, source_file)
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.request_id, "cli-market-review-import-sectors")
        self.assertEqual(ctx.operator, "cli")
        self.assertEqual(ctx.source, "cli")
        output = stdout.getvalue()
        self.assertIn("market-review import-sectors command routed", output)
        self.assertIn("sector_import_status=success", output)
        self.assertIn("members=7", output)
        self.assertIn("missing_bars=1", output)

    def test_sector_membership_import_apply_mode_uses_write_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_market_review_apply.db"
            db_path.touch()
            source_file = Path(tmp) / "sector_memberships.json"
            source_file.write_text('{"as_of_date":"20260508","provider":"manual","sectors":[]}', encoding="utf-8")
            stdout = io.StringIO()
            code = main(
                [
                    "market-review",
                    "import-sectors",
                    "--date",
                    "2026-05-08",
                    "--file",
                    str(source_file),
                    "--db-path",
                    str(db_path),
                    "--apply",
                    "--operator",
                    "azboo",
                    "--idempotency-key",
                    "market-sectors:test",
                ],
                stdout=stdout,
                services=CommandServices(market_review_service_factory=_FakeMarketReviewRunService),
            )

        self.assertEqual(code, 0)
        _, request, ctx = _FakeMarketReviewRunService.calls[0]
        self.assertEqual(request.as_of_date, "20260508")
        self.assertFalse(ctx.dry_run)
        self.assertEqual(ctx.operator, "azboo")
        self.assertEqual(ctx.idempotency_key, "market-sectors:test")
        self.assertIn("market_review_run_id=42", stdout.getvalue())

    def test_sector_membership_import_missing_db_fails_without_creating_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            source_file = Path(tmp) / "sector_memberships.json"
            source_file.write_text('{"as_of_date":"20260508","provider":"manual","sectors":[]}', encoding="utf-8")
            stdout = io.StringIO()
            code = main(
                [
                    "market-review",
                    "import-sectors",
                    "--date",
                    "20260508",
                    "--input",
                    str(source_file),
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
                services=CommandServices(market_review_service_factory=_UnexpectedMarketReviewRunService),
            )

            self.assertEqual(code, 1)
            self.assertFalse(db_path.exists())
            self.assertIn("database not found", stdout.getvalue())
            self.assertIn("sector_memberships.json", stdout.getvalue())

    def test_market_external_data_import_routes_to_service_with_dry_run_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_market_review.db"
            db_path.touch()
            source_file = Path(tmp) / "external_items.json"
            source_file.write_text('{"as_of_date":"20260508","provider":"manual","items":[]}', encoding="utf-8")
            stdout = io.StringIO()
            code = main(
                [
                    "market-review",
                    "external-data",
                    "import",
                    "--date",
                    "20260508",
                    "--input",
                    str(source_file),
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
                services=CommandServices(
                    market_external_data_service_factory=_FakeMarketExternalDataService,
                ),
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(_FakeMarketExternalDataService.calls), 1)
        called_db_path, request, ctx = _FakeMarketExternalDataService.calls[0]
        self.assertEqual(called_db_path, db_path)
        self.assertEqual(request.as_of_date, "20260508")
        self.assertEqual(request.source_file, source_file)
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.request_id, "cli-market-external-data-import")
        self.assertEqual(ctx.operator, "cli")
        self.assertEqual(ctx.source, "cli")
        output = stdout.getvalue()
        self.assertIn("market-review external-data import command routed", output)
        self.assertIn("market_external_import_status=success", output)
        self.assertIn("provider_file_contract=market_external_v1", output)
        self.assertIn("inserted=0", output)
        self.assertIn("duplicates=0", output)
        self.assertIn("invalid=0", output)
        self.assertIn('"sector":"partial"', output)
        self.assertIn('"duplicates":"none"', output)
        self.assertIn('"freshness":{"market":"fresh","sector":"fresh","stock":"fresh"}', output)
        self.assertIn("coverage_details_json=", output)
        self.assertIn('"missing_scopes":[]', output)

    def test_market_external_data_import_apply_mode_uses_write_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_market_review_apply.db"
            db_path.touch()
            source_file = Path(tmp) / "external_items.json"
            source_file.write_text('{"as_of_date":"20260508","provider":"manual","items":[]}', encoding="utf-8")
            stdout = io.StringIO()
            code = main(
                [
                    "market-review",
                    "external-data",
                    "import",
                    "--date",
                    "2026-05-08",
                    "--file",
                    str(source_file),
                    "--db-path",
                    str(db_path),
                    "--apply",
                    "--operator",
                    "azboo",
                    "--idempotency-key",
                    "market-external:test",
                ],
                stdout=stdout,
                services=CommandServices(
                    market_external_data_service_factory=_FakeMarketExternalDataService,
                ),
            )

        self.assertEqual(code, 0)
        _, request, ctx = _FakeMarketExternalDataService.calls[0]
        self.assertEqual(request.as_of_date, "20260508")
        self.assertEqual(request.source_file, source_file)
        self.assertFalse(ctx.dry_run)
        self.assertEqual(ctx.operator, "azboo")
        self.assertEqual(ctx.idempotency_key, "market-external:test")
        self.assertIn("inserted=3", stdout.getvalue())

    def test_market_external_data_backfill_routes_to_service_with_coverage_qa(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_market_review.db"
            db_path.touch()
            first_file = Path(tmp) / "external_items_20260507.json"
            second_file = Path(tmp) / "external_items_20260508.json"
            first_file.write_text('{"as_of_date":"20260507","provider":"manual","items":[]}', encoding="utf-8")
            second_file.write_text('{"as_of_date":"20260508","provider":"manual","items":[]}', encoding="utf-8")
            stdout = io.StringIO()
            code = main(
                [
                    "market-review",
                    "external-data",
                    "backfill",
                    "--input",
                    str(first_file),
                    str(second_file),
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
                services=CommandServices(
                    market_external_data_service_factory=_FakeMarketExternalDataService,
                ),
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(_FakeMarketExternalDataService.calls), 1)
        called_db_path, request, ctx = _FakeMarketExternalDataService.calls[0]
        self.assertEqual(called_db_path, db_path)
        self.assertEqual(request.source_files, [first_file, second_file])
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.request_id, "cli-market-external-data-backfill")
        output = stdout.getvalue()
        self.assertIn("market-review external-data backfill command routed", output)
        self.assertIn("market_external_backfill_status=success", output)
        self.assertIn("backfill_totals=files=2 dates=2 rows=4 valid=4 invalid=0", output)
        self.assertIn("coverage_qa_json=", output)
        self.assertIn('"ready_dates":["20260508"]', output)
        self.assertIn("backfill_dates:", output)

    def test_market_external_data_import_missing_db_fails_without_creating_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            source_file = Path(tmp) / "external_items.json"
            source_file.write_text('{"as_of_date":"20260508","provider":"manual","items":[]}', encoding="utf-8")
            stdout = io.StringIO()
            code = main(
                [
                    "market-review",
                    "external-data",
                    "import",
                    "--date",
                    "20260508",
                    "--input",
                    str(source_file),
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
                services=CommandServices(
                    market_external_data_service_factory=_UnexpectedMarketExternalDataService,
                ),
            )

            self.assertEqual(code, 1)
            self.assertFalse(db_path.exists())
            self.assertIn("database not found", stdout.getvalue())
            self.assertIn("external_items.json", stdout.getvalue())

    def test_market_external_data_import_cli_applies_fixture_to_migrated_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_market_review_integration.db"
            run_migrations(db_path)
            source_file = Path(__file__).parent / "fixtures" / "market_review" / "external_items_20260508.json"
            stdout = io.StringIO()

            code = main(
                [
                    "market-review",
                    "external-data",
                    "import",
                    "--date",
                    "20260508",
                    "--input",
                    str(source_file),
                    "--db-path",
                    str(db_path),
                    "--apply",
                    "--operator",
                    "azboo",
                ],
                stdout=stdout,
            )

        self.assertEqual(code, 0)
        output = stdout.getvalue()
        self.assertIn("market_external_import_status=success", output)
        self.assertIn("provider_file_contract=market_external_v1", output)
        self.assertIn("inserted=3", output)
        self.assertIn("duplicates=0", output)
        self.assertIn("invalid=0", output)
        self.assertIn('"freshness":{"market":"fresh","sector":"fresh","stock":"fresh"}', output)
        self.assertIn("coverage_details_json=", output)

    def test_strategy_evolution_propose_list_and_mark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)
            _seed_risk_off_review(db_path)

            preview_stdout = io.StringIO()
            preview_code = main(
                [
                    "strategy-evolution",
                    "propose",
                    "--date",
                    "20260508",
                    "--db-path",
                    str(db_path),
                ],
                stdout=preview_stdout,
            )

            self.assertEqual(preview_code, 0)
            self.assertIn("strategy-evolution propose command routed for 20260508", preview_stdout.getvalue())
            self.assertIn("generated=1", preview_stdout.getvalue())
            self.assertIn("inserted=0", preview_stdout.getvalue())
            self.assertEqual(_count_hypotheses(db_path), 0)

            apply_stdout = io.StringIO()
            apply_code = main(
                [
                    "strategy-evolution",
                    "propose",
                    "--date",
                    "20260508",
                    "--db-path",
                    str(db_path),
                    "--operator",
                    "azboo",
                    "--apply",
                ],
                stdout=apply_stdout,
            )

            self.assertEqual(apply_code, 0)
            self.assertIn("generated=1", apply_stdout.getvalue())
            self.assertIn("inserted=1", apply_stdout.getvalue())
            hypothesis_id = _first_hypothesis_id(db_path)

            list_stdout = io.StringIO()
            list_code = main(
                [
                    "strategy-evolution",
                    "list",
                    "--status",
                    "proposed",
                    "--db-path",
                    str(db_path),
                ],
                stdout=list_stdout,
            )

            self.assertEqual(list_code, 0)
            self.assertIn("hypotheses_count=1", list_stdout.getvalue())
            self.assertIn("market_regime_position_sizing", list_stdout.getvalue())

            mark_stdout = io.StringIO()
            mark_code = main(
                [
                    "strategy-evolution",
                    "mark",
                    "--hypothesis-id",
                    str(hypothesis_id),
                    "--status",
                    "testing",
                    "--operator",
                    "azboo",
                    "--db-path",
                    str(db_path),
                ],
                stdout=mark_stdout,
            )

            self.assertEqual(mark_code, 0)
            mark_output = mark_stdout.getvalue()
            self.assertIn("strategy-evolution mark command routed", mark_output)
            self.assertIn("previous_status=proposed", mark_output)
            self.assertIn("status=testing", mark_output)
            self.assertIn("operator=azboo", mark_output)

            testing_stdout = io.StringIO()
            testing_code = main(
                [
                    "strategy-evolution",
                    "list",
                    "--status",
                    "testing",
                    "--date",
                    "2026-05-08",
                    "--db-path",
                    str(db_path),
                ],
                stdout=testing_stdout,
            )

            self.assertEqual(testing_code, 0)
            self.assertIn("hypotheses_count=1", testing_stdout.getvalue())
            self.assertIn(f"id={hypothesis_id}", testing_stdout.getvalue())

    def test_strategy_evolution_backtest_dry_run_routes_without_state_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)
            seed_reference_data(db_path)
            _seed_risk_off_review(db_path)
            apply_stdout = io.StringIO()
            apply_code = main(
                [
                    "strategy-evolution",
                    "propose",
                    "--date",
                    "20260508",
                    "--db-path",
                    str(db_path),
                    "--apply",
                ],
                stdout=apply_stdout,
            )
            hypothesis_id = _first_hypothesis_id(db_path)
            strategy_versions_before = _count_strategy_versions(db_path)

            stdout = io.StringIO()
            code = main(
                [
                    "strategy-evolution",
                    "backtest",
                    "--hypothesis-id",
                    str(hypothesis_id),
                    "--db-path",
                    str(db_path),
                    "--dry-run",
                ],
                stdout=stdout,
            )

            self.assertEqual(apply_code, 0)
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("strategy-evolution backtest command routed", output)
            self.assertIn(f"hypothesis-id={hypothesis_id}", output)
            self.assertIn(f"task_key=strategy-hypothesis:{hypothesis_id}:backtest", output)
            self.assertIn("strategy_version_task_required=false", output)
            self.assertIn("would_write_artifact=true", output)
            self.assertIn("wrote_artifact=false", output)
            self.assertIn("active_params_mutated=false", output)
            self.assertIn("BACKTEST_REQUEST_DRY_RUN", output)
            self.assertEqual(_count_strategy_versions(db_path), strategy_versions_before)

    def test_strategy_evolution_acceptance_requires_validation_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            artifact_path = Path(tmp) / "hypothesis_backtest_request.json"
            run_migrations(db_path)
            seed_reference_data(db_path)
            _seed_risk_off_review(db_path)
            apply_stdout = io.StringIO()
            apply_code = main(
                [
                    "strategy-evolution",
                    "propose",
                    "--date",
                    "20260508",
                    "--db-path",
                    str(db_path),
                    "--apply",
                ],
                stdout=apply_stdout,
            )
            hypothesis_id = _first_hypothesis_id(db_path)
            _write_backtest_artifact(artifact_path, hypothesis_id)
            strategy_versions_before = _count_strategy_versions(db_path)

            testing_stdout = io.StringIO()
            testing_code = main(
                [
                    "strategy-evolution",
                    "mark",
                    "--hypothesis-id",
                    str(hypothesis_id),
                    "--status",
                    "testing",
                    "--review-note",
                    "Ready for replay/backtest.",
                    "--operator",
                    "azboo",
                    "--db-path",
                    str(db_path),
                ],
                stdout=testing_stdout,
            )
            accepted_stdout = io.StringIO()
            accepted_code = main(
                [
                    "strategy-evolution",
                    "mark",
                    "--hypothesis-id",
                    str(hypothesis_id),
                    "--status",
                    "accepted",
                    "--evidence-id",
                    "market_review_run:1",
                    "--backtest-artifact",
                    str(artifact_path),
                    "--review-note",
                    "Replay artifact attached; promote only to future strategy-version task.",
                    "--operator",
                    "azboo",
                    "--db-path",
                    str(db_path),
                ],
                stdout=accepted_stdout,
            )

            self.assertEqual(apply_code, 0)
            self.assertEqual(testing_code, 0)
            self.assertEqual(accepted_code, 0)
            output = accepted_stdout.getvalue()
            self.assertIn("strategy-evolution mark command routed", output)
            self.assertIn("previous_status=testing", output)
            self.assertIn("status=accepted", output)
            self.assertIn("strategy_version_task_required=true", output)
            self.assertIn("validation_evidence_ids=market_review_run:1", output)
            self.assertIn(f"backtest_artifacts={artifact_path}", output)
            self.assertIn(f"future_strategy_version_task_key=strategy-hypothesis:{hypothesis_id}:strategy-version", output)
            self.assertEqual(_count_strategy_versions(db_path), strategy_versions_before)

    def test_strategy_evolution_missing_db_fails_without_creating_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            stdout = io.StringIO()
            code = main(
                [
                    "strategy-evolution",
                    "propose",
                    "--date",
                    "20260508",
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 1)
            self.assertFalse(db_path.exists())
            self.assertIn("database not found", stdout.getvalue())
            self.assertIn("no writes were performed", stdout.getvalue())

    def test_market_review_link_plan_routes_to_service_with_dry_run_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_market_review.db"
            db_path.touch()
            stdout = io.StringIO()
            code = main(
                [
                    "market-review",
                    "link-plan",
                    "--date",
                    "20260508",
                    "--trade-plan-id",
                    "7",
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
                services=CommandServices(market_plan_context_service_factory=_FakeMarketPlanContextService),
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(_FakeMarketPlanContextService.calls), 1)
        called_db_path, request, ctx = _FakeMarketPlanContextService.calls[0]
        self.assertEqual(called_db_path, db_path)
        self.assertEqual(request.as_of_date, "20260508")
        self.assertEqual(request.trade_plan_id, 7)
        self.assertTrue(ctx.dry_run)
        self.assertEqual(ctx.request_id, "cli-market-review-link-plan")
        self.assertEqual(ctx.operator, "cli")
        output = stdout.getvalue()
        self.assertIn("market-review link-plan command routed", output)
        self.assertIn("market_plan_context_status=success", output)
        self.assertIn("market_review_run_id=42", output)
        self.assertIn("trade_plan_id=7", output)
        self.assertIn("alignment=aligned", output)
        self.assertIn("management_action=proceed", output)
        self.assertIn("changed=false", output)

    def test_market_review_link_plan_apply_mode_uses_operator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_market_review.db"
            db_path.touch()
            stdout = io.StringIO()
            code = main(
                [
                    "market-review",
                    "link-plan",
                    "--date",
                    "2026-05-08",
                    "--trade-plan-id",
                    "7",
                    "--operator",
                    "azboo",
                    "--apply",
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
                services=CommandServices(market_plan_context_service_factory=_FakeMarketPlanContextService),
            )

        self.assertEqual(code, 0)
        _, request, ctx = _FakeMarketPlanContextService.calls[0]
        self.assertEqual(request.as_of_date, "20260508")
        self.assertFalse(ctx.dry_run)
        self.assertEqual(ctx.operator, "azboo")
        self.assertIn("changed=true", stdout.getvalue())

    def test_market_review_link_plan_missing_db_fails_without_creating_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            stdout = io.StringIO()
            code = main(
                [
                    "market-review",
                    "link-plan",
                    "--date",
                    "20260508",
                    "--trade-plan-id",
                    "7",
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
                services=CommandServices(market_plan_context_service_factory=_UnexpectedMarketPlanContextService),
            )

            self.assertEqual(code, 1)
            self.assertFalse(db_path.exists())
            self.assertIn("database not found", stdout.getvalue())
            self.assertIn("no writes were performed", stdout.getvalue())


def _seed_risk_off_review(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.execute(
            """
            INSERT INTO market_review_runs
              (as_of_date, status, provider_manifest_json, coverage_json, summary_json, completed_at)
            VALUES
              ('20260508', 'completed', '{}', '{}', '{"summary":"risk off"}', CURRENT_TIMESTAMP)
            """
        )
        run_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO market_regime_snapshots
              (market_review_run_id, as_of_date, regime, sentiment_score, summary)
            VALUES
              (?, '20260508', 'risk_off', 0.20, 'Risk-off sentiment.')
            """,
            (run_id,),
        )


def _count_hypotheses(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM strategy_hypotheses").fetchone()[0])


def _count_strategy_versions(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM strategy_versions").fetchone()[0])


def _first_hypothesis_id(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute("SELECT id FROM strategy_hypotheses ORDER BY id LIMIT 1").fetchone()[0])


def _write_backtest_artifact(path: Path, hypothesis_id: int) -> None:
    path.write_text(
        json.dumps(
            {
                "artifact_type": "strategy_hypothesis_backtest_request",
                "hypothesis": {"id": hypothesis_id},
                "backtest_request": {"task_key": f"strategy-hypothesis:{hypothesis_id}:backtest"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
