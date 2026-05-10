from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.agent_external_data_service import (
    AgentExternalDataService,
    ImportAgentExternalDataRequest,
    build_agent_external_source_hash,
)
from pgc_trading.services.common import RequestContext
from pgc_trading.storage.migrate import run_migrations


class AgentExternalDataServiceTest(unittest.TestCase):
    def test_dry_run_previews_counts_and_validation_errors_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            service = AgentExternalDataService(db_path)

            result = service.import_external_data(
                ImportAgentExternalDataRequest(
                    records=[
                        self._record(),
                        self._record(published_date="2026-05-04", title="日期格式错误"),
                    ]
                ),
                RequestContext(request_id="test-external-preview", dry_run=True, operator="tester"),
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "validation_failed")
            self.assertEqual(result.data.row_count, 2)
            self.assertEqual(result.data.valid_count, 1)
            self.assertEqual(result.data.invalid_count, 1)
            self.assertEqual(result.data.would_insert_count, 1)
            self.assertEqual(result.data.inserted_count, 0)
            self.assertEqual(result.errors[0].code, "INVALID_PUBLISHED_DATE")
            self.assertEqual(result.data.coverage_summary["announcement"], "available")
            self.assertEqual(result.data.coverage_summary["freshness"], "unknown")
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "agent_external_items"), 0)

    def test_apply_upserts_items_idempotently_from_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            source_file = Path(tmp) / "external_items.json"
            source_file.write_text(
                json.dumps(
                    {
                        "records": [
                            self._record(metadata={"source": "fixture", "rank": 1}),
                            self._record(
                                published_date="20260505",
                                item_type="risk_note",
                                title="未来风险摘要",
                                summary="这条未来摘要可以存储，但快照应按 review_date 过滤。",
                                sentiment="negative",
                                importance="high",
                            ),
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            service = AgentExternalDataService(db_path)
            request = ImportAgentExternalDataRequest(source_file=source_file)

            first = service.import_external_data(
                request,
                RequestContext(request_id="test-external-apply", dry_run=False, operator="tester"),
            )
            second = service.import_external_data(
                request,
                RequestContext(request_id="test-external-repeat", dry_run=False, operator="tester"),
            )

            self.assertTrue(first.ok)
            self.assertEqual(first.data.inserted_count, 2)
            self.assertEqual(first.data.updated_count, 0)
            self.assertEqual(len(first.data.agent_external_item_ids), 2)
            self.assertTrue(second.ok)
            self.assertEqual(second.data.inserted_count, 0)
            self.assertEqual(second.data.updated_count, 2)
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                self.assertEqual(self._count(conn, "agent_external_items"), 2)
                self.assertEqual(self._count(conn, "agent_runs"), 0)
                self.assertEqual(self._count(conn, "market_bars"), 0)
                self.assertEqual(self._count(conn, "trade_plans"), 0)
                item = conn.execute(
                    """
                    SELECT ts_code, published_date, item_type, provider, sentiment, importance,
                           metadata_json, source_hash
                    FROM agent_external_items
                    WHERE title = '盘后公告摘要'
                    """
                ).fetchone()
                self.assertEqual(item["ts_code"], "000001.SZ")
                self.assertEqual(item["published_date"], "20260504")
                self.assertEqual(item["item_type"], "announcement")
                self.assertEqual(item["provider"], "manual")
                self.assertEqual(item["sentiment"], "neutral")
                self.assertEqual(item["importance"], "medium")
                self.assertEqual(json.loads(item["metadata_json"]), {"rank": 1, "source": "fixture"})
                self.assertEqual(
                    item["source_hash"],
                    build_agent_external_source_hash(
                        provider="manual",
                        item_type="announcement",
                        ts_code="000001.SZ",
                        published_date="20260504",
                        title="盘后公告摘要",
                        summary="公告摘要未发现重大利空。",
                    ),
                )

    def test_apply_imports_structured_cached_agent_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            source_file = Path(tmp) / "structured_agent_cache.json"
            source_file.write_text(
                json.dumps(
                    {
                        "source": "tushare",
                        "date": "20260508",
                        "fundamental_snapshots": [
                            {
                                "ts_code": "000001.SZ",
                                "pe_ttm": 8.5,
                                "pb": 0.72,
                                "total_mv": 2100000,
                            }
                        ],
                        "announcements": [
                            {
                                "ts_code": "000001.SZ",
                                "ann_date": "2026-05-08",
                                "title": "年度权益分派提示",
                                "summary": "公司公告权益分派安排，未见重大利空。",
                                "importance": "important",
                            }
                        ],
                        "news_snippets": [
                            {
                                "ts_code": "000001.SZ",
                                "title": "行业新闻摘要",
                                "content": "行业景气度维持平稳。",
                                "url": "https://example.test/news/1",
                            }
                        ],
                        "sentiment_snippets": [
                            {
                                "ts_code": "000001.SZ",
                                "sentiment_label": "bullish",
                                "score": 0.64,
                                "text": "投资者讨论偏正面，但样本有限。",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = AgentExternalDataService(db_path).import_external_data(
                ImportAgentExternalDataRequest(source_file=source_file),
                RequestContext(request_id="test-structured-cache", dry_run=False, operator="tester"),
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.data.inserted_count, 4)
            self.assertEqual(result.data.as_of_date, "20260508")
            self.assertEqual(result.data.coverage_summary["stock_count"], 1)
            self.assertEqual(result.data.coverage_summary["missing_item_types"], [])
            self.assertEqual(result.data.coverage_summary["freshness"], "fresh")
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT item_type, provider, published_date, title, summary, sentiment, importance, metadata_json
                    FROM agent_external_items
                    ORDER BY item_type
                    """
                ).fetchall()
            by_type = {row["item_type"]: row for row in rows}
            self.assertEqual(set(by_type), {"announcement", "fundamental", "news", "sentiment"})
            self.assertEqual({row["provider"] for row in rows}, {"tushare"})
            self.assertEqual({row["published_date"] for row in rows}, {"20260508"})
            self.assertIn("PE-TTM=8.5", by_type["fundamental"]["summary"])
            self.assertEqual(by_type["announcement"]["importance"], "high")
            self.assertEqual(by_type["sentiment"]["sentiment"], "positive")
            self.assertEqual(json.loads(by_type["fundamental"]["metadata_json"])["cache_item_type"], "fundamental")

    def test_apply_imports_normalized_agent_external_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            source_file = Path(__file__).parent / "fixtures" / "agent_external" / "20260508_301188.json"

            result = AgentExternalDataService(db_path).import_external_data(
                ImportAgentExternalDataRequest(source_file=source_file),
                RequestContext(request_id="test-normalized-fixture", dry_run=False, operator="tester"),
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.data.inserted_count, 1)
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                item = conn.execute(
                    """
                    SELECT ts_code, published_date, item_type, provider, title, summary, metadata_json
                    FROM agent_external_items
                    """
                ).fetchone()
                self.assertEqual(self._count(conn, "market_bars"), 0)
                self.assertEqual(self._count(conn, "strategy_signals"), 0)
            metadata = json.loads(item["metadata_json"])
            self.assertEqual(item["ts_code"], "301188.SZ")
            self.assertEqual(item["published_date"], "20260508")
            self.assertEqual(item["item_type"], "fundamental")
            self.assertEqual(item["provider"], "tushare")
            self.assertEqual(item["title"], "valuation snapshot")
            self.assertEqual(item["summary"], "PE/PB/turnover fields from cached provider")
            self.assertEqual(metadata["fixture_format"], "agent_external_v2")
            self.assertEqual(metadata["as_of_date"], "20260508")
            self.assertEqual(metadata["source"], "tushare")
            self.assertEqual(metadata["category"], "fundamental")
            self.assertEqual(metadata["payload"]["pe_ttm"], 31.2)

    def test_rejects_normalized_fixture_items_after_as_of_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            source_file = Path(tmp) / "future_agent_cache.json"
            source_file.write_text(
                json.dumps(
                    {
                        "as_of_date": "20260508",
                        "ts_code": "301188.SZ",
                        "items": [
                            {
                                "source": "tushare",
                                "category": "fundamental",
                                "published_date": "20260509",
                                "title": "future valuation snapshot",
                                "summary": "Future data must not enter the review snapshot.",
                                "payload": {"pe_ttm": 30.1},
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = AgentExternalDataService(db_path).import_external_data(
                ImportAgentExternalDataRequest(source_file=source_file),
                RequestContext(request_id="test-normalized-future", dry_run=False, operator="tester"),
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "validation_failed")
            self.assertEqual(result.data.valid_count, 0)
            self.assertEqual(result.errors[0].code, "FUTURE_PUBLISHED_DATE")
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "agent_external_items"), 0)

    def test_apply_rejects_invalid_records_without_partial_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            service = AgentExternalDataService(db_path)

            result = service.import_external_data(
                ImportAgentExternalDataRequest(
                    records=[
                        self._record(),
                        self._record(item_type="rumor", metadata={"source": object()}),
                    ]
                ),
                RequestContext(request_id="test-external-invalid", dry_run=False, operator="tester"),
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "validation_failed")
            self.assertEqual(result.data.valid_count, 1)
            self.assertEqual(result.data.invalid_count, 1)
            self.assertEqual({error.code for error in result.errors}, {"INVALID_ITEM_TYPE", "INVALID_METADATA"})
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "agent_external_items"), 0)

    def test_dry_run_reports_existing_rows_as_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            service = AgentExternalDataService(db_path)
            request = ImportAgentExternalDataRequest(records=[self._record()])

            applied = service.import_external_data(
                request,
                RequestContext(request_id="test-external-apply-once", dry_run=False),
            )
            preview = service.import_external_data(
                request,
                RequestContext(request_id="test-external-preview-repeat", dry_run=True),
            )

            self.assertTrue(applied.ok)
            self.assertTrue(preview.ok)
            self.assertEqual(preview.data.would_insert_count, 0)
            self.assertEqual(preview.data.would_update_count, 1)
            self.assertEqual(preview.data.inserted_count, 0)
            self.assertEqual(preview.data.updated_count, 0)

    def test_dry_run_counts_duplicate_source_hash_like_apply_would(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            service = AgentExternalDataService(db_path)
            request = ImportAgentExternalDataRequest(records=[self._record(), self._record()])

            preview = service.import_external_data(
                request,
                RequestContext(request_id="test-external-preview-dupe", dry_run=True),
            )
            applied = service.import_external_data(
                request,
                RequestContext(request_id="test-external-apply-dupe", dry_run=False),
            )

            self.assertTrue(preview.ok)
            self.assertEqual(preview.data.would_insert_count, 1)
            self.assertEqual(preview.data.would_update_count, 1)
            self.assertEqual(preview.data.coverage_summary["duplicates"], "duplicate")
            self.assertEqual(preview.data.coverage_summary["duplicate_count"], 1)
            self.assertTrue(applied.ok)
            self.assertEqual(applied.data.inserted_count, 1)
            self.assertEqual(applied.data.updated_count, 1)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "agent_external_items"), 1)

    def test_coverage_reports_stale_missing_and_contract_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            source_file = Path(tmp) / "agent_external.json"
            source_file.write_text(
                json.dumps(
                    {
                        "provider_file_contract": "agent_external_v1",
                        "as_of_date": "20260508",
                        "records": [
                            self._record(published_date="20260507", as_of_date="20260508"),
                            self._record(published_date="20260507", as_of_date="20260508"),
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = AgentExternalDataService(db_path).import_external_data(
                ImportAgentExternalDataRequest(source_file=source_file),
                RequestContext(request_id="test-agent-coverage", dry_run=True, operator="tester"),
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.data.provider_file_contract, "agent_external_v1")
            self.assertEqual(result.data.as_of_date, "20260508")
            self.assertEqual(result.data.coverage_summary["duplicates"], "duplicate")
            self.assertEqual(result.data.coverage_summary["duplicate_count"], 1)
            self.assertEqual(result.data.coverage_summary["freshness"], "stale")
            self.assertEqual(result.data.coverage_summary["stale_count"], 2)
            self.assertEqual(result.data.coverage_summary["missing_item_types"], ["fundamental", "news", "sentiment"])

    def test_rejects_agent_source_hash_mismatch_when_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)

            result = AgentExternalDataService(db_path).import_external_data(
                ImportAgentExternalDataRequest(records=[self._record(source_hash="bad-hash")]),
                RequestContext(request_id="test-agent-source-hash", dry_run=False, operator="tester"),
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "validation_failed")
            self.assertEqual(result.errors[0].code, "SOURCE_HASH_MISMATCH")
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "agent_external_items"), 0)

    def test_rejects_unsupported_agent_provider_file_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            source_file = Path(tmp) / "agent_external.json"
            source_file.write_text(
                json.dumps({"provider_file_contract": "unknown_contract", "records": []}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = AgentExternalDataService(db_path).import_external_data(
                ImportAgentExternalDataRequest(source_file=source_file),
                RequestContext(request_id="test-agent-contract-reject", dry_run=True, operator="tester"),
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.errors[0].code, "UNSUPPORTED_PROVIDER_FILE_CONTRACT")

    def _migrated_db(self, tmp: str) -> Path:
        db_path = Path(tmp) / "pgc_external_data.db"
        run_migrations(db_path)
        return db_path

    def _record(self, **overrides: object) -> dict[str, object]:
        record: dict[str, object] = {
            "ts_code": "000001.SZ",
            "published_date": "20260504",
            "item_type": "announcement",
            "provider": "manual",
            "title": "盘后公告摘要",
            "summary": "公告摘要未发现重大利空。",
            "url": "https://example.test/000001",
            "sentiment": "neutral",
            "importance": "medium",
            "metadata": {"source": "fixture"},
        }
        record.update(overrides)
        return record

    def _count(self, conn: sqlite3.Connection, table_name: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
