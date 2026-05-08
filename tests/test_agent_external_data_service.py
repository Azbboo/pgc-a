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
            self.assertTrue(applied.ok)
            self.assertEqual(applied.data.inserted_count, 1)
            self.assertEqual(applied.data.updated_count, 1)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "agent_external_items"), 1)

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
