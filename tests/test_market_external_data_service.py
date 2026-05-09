from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.market_external_data_service import (
    ImportMarketExternalDataRequest,
    MarketExternalDataService,
    build_market_external_source_hash,
)
from pgc_trading.storage.migrate import run_migrations


class MarketExternalDataServiceTest(unittest.TestCase):
    def test_dry_run_previews_fixture_without_writes_and_reports_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            service = MarketExternalDataService(db_path)

            result = service.import_external_data(
                ImportMarketExternalDataRequest(
                    as_of_date="20260508",
                    source_file=self._fixture_path(),
                ),
                RequestContext(request_id="test-market-external-preview", dry_run=True, operator="tester"),
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.data.row_count, 3)
            self.assertEqual(result.data.valid_count, 3)
            self.assertEqual(result.data.invalid_count, 0)
            self.assertEqual(result.data.would_insert_count, 3)
            self.assertEqual(result.data.inserted_count, 0)
            self.assertEqual(result.data.duplicate_count, 0)
            self.assertEqual(
                result.data.coverage_summary,
                {
                    "market": "available",
                    "sector": "partial",
                    "stock": "partial",
                    "sentiment": "partial",
                    "news": "available",
                },
            )
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "market_external_items"), 0)

    def test_apply_inserts_fixture_and_counts_duplicate_reimport(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            service = MarketExternalDataService(db_path)
            request = ImportMarketExternalDataRequest(as_of_date="20260508", source_file=self._fixture_path())

            first = service.import_external_data(
                request,
                RequestContext(request_id="test-market-external-apply", dry_run=False, operator="tester"),
            )
            second = service.import_external_data(
                request,
                RequestContext(request_id="test-market-external-repeat", dry_run=False, operator="tester"),
            )

            self.assertTrue(first.ok)
            self.assertEqual(first.data.inserted_count, 3)
            self.assertEqual(first.data.duplicate_count, 0)
            self.assertEqual(len(first.data.market_external_item_ids), 3)
            self.assertTrue(second.ok)
            self.assertEqual(second.data.inserted_count, 0)
            self.assertEqual(second.data.duplicate_count, 3)
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                self.assertEqual(self._count(conn, "market_external_items"), 3)
                item = conn.execute(
                    """
                    SELECT scope_type, scope_key, item_type, provider, title, summary,
                           sentiment, importance, metadata_json, source_hash
                    FROM market_external_items
                    WHERE scope_type = 'market'
                    """
                ).fetchone()
            self.assertEqual(item["scope_key"], "A_SHARE")
            self.assertEqual(item["item_type"], "policy")
            self.assertEqual(item["provider"], "manual_fixture")
            self.assertEqual(item["sentiment"], "neutral")
            self.assertEqual(item["importance"], "medium")
            self.assertEqual(json.loads(item["metadata_json"]), {"source_note": "manual test fixture"})
            self.assertEqual(
                item["source_hash"],
                build_market_external_source_hash(
                    provider="manual_fixture",
                    scope_type="market",
                    scope_key="A_SHARE",
                    published_date="20260508",
                    title="A股市场政策摘要",
                    summary="政策基调保持稳增长，流动性预期平稳；作为人工夹具，仅用于验证外部证据缓存。",
                ),
            )

    def test_rejects_future_dates_unknown_enums_and_invalid_metadata_without_partial_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            service = MarketExternalDataService(db_path)

            result = service.import_external_data(
                ImportMarketExternalDataRequest(
                    as_of_date="20260508",
                    records=[
                        self._record(),
                        self._record(title="未来新闻摘要", published_date="20260509"),
                        self._record(
                            scope_type="concept",
                            item_type="rumor",
                            sentiment="bullish",
                            importance="urgent",
                            metadata=[],
                        ),
                    ],
                ),
                RequestContext(request_id="test-market-external-invalid", dry_run=False, operator="tester"),
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "validation_failed")
            self.assertEqual(result.data.valid_count, 1)
            self.assertEqual(result.data.invalid_count, 2)
            self.assertEqual(result.data.would_insert_count, 1)
            self.assertEqual(
                {error.code for error in result.errors},
                {
                    "FUTURE_PUBLISHED_DATE",
                    "INVALID_SCOPE_TYPE",
                    "INVALID_ITEM_TYPE",
                    "INVALID_SENTIMENT",
                    "INVALID_IMPORTANCE",
                    "INVALID_METADATA",
                },
            )
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "market_external_items"), 0)

    def test_summarize_coverage_reports_missing_when_no_evidence_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            service = MarketExternalDataService(db_path)

            self.assertEqual(
                service.summarize_coverage("20260508"),
                {
                    "market": "missing",
                    "sector": "missing",
                    "stock": "missing",
                    "sentiment": "missing",
                    "news": "missing",
                },
            )

    def test_rejects_fixture_date_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            source_file = Path(tmp) / "external_items.json"
            source_file.write_text(
                json.dumps(
                    {
                        "as_of_date": "20260507",
                        "provider": "manual_fixture",
                        "items": [self._record()],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = MarketExternalDataService(db_path).import_external_data(
                ImportMarketExternalDataRequest(as_of_date="20260508", source_file=source_file),
                RequestContext(request_id="test-market-external-mismatch", dry_run=False, operator="tester"),
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "validation_failed")
            self.assertEqual(result.errors[0].code, "AS_OF_DATE_MISMATCH")
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "market_external_items"), 0)

    def _migrated_db(self, tmp: str) -> Path:
        db_path = Path(tmp) / "pgc_market_external.db"
        run_migrations(db_path)
        return db_path

    def _fixture_path(self) -> Path:
        return Path(__file__).parent / "fixtures" / "market_review" / "external_items_20260508.json"

    def _record(self, **overrides: object) -> dict[str, object]:
        record: dict[str, object] = {
            "as_of_date": "20260508",
            "scope_type": "market",
            "scope_key": "A_SHARE",
            "item_type": "policy",
            "provider": "manual_fixture",
            "published_date": "20260508",
            "title": "A股市场政策摘要",
            "summary": "政策基调保持稳增长，流动性预期平稳。",
            "sentiment": "neutral",
            "importance": "medium",
            "metadata": {"source_note": "unit test"},
        }
        record.update(overrides)
        return record

    def _count(self, conn: sqlite3.Connection, table_name: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
