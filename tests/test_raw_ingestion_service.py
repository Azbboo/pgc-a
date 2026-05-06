from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.raw_ingestion_service import (
    ImportRawEventsRequest,
    RawIngestionService,
)
from pgc_trading.storage.migrate import run_migrations


FIXTURES = Path(__file__).parent / "fixtures" / "raw"


class RawIngestionServiceTest(unittest.TestCase):
    def test_clean_raw_fixture_imports_batch_events_and_audit_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            service = RawIngestionService(db_path)

            result = service.import_raw_events(
                ImportRawEventsRequest(FIXTURES / "pgc_events_clean.json"),
                RequestContext(
                    request_id="req-clean",
                    idempotency_key="raw-import:clean",
                    operator="tester",
                ),
            )

            self.assertEqual(result.status, "success")
            self.assertTrue(result.ok)
            self.assertIsNotNone(result.data)
            self.assertEqual(result.data.row_count, 2)
            self.assertEqual(result.data.valid_count, 2)
            self.assertEqual(result.data.dirty_count, 0)
            self.assertEqual(result.data.duplicate_count, 0)
            self.assertIn("raw_import_batch_id", result.created_ids)

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "raw_import_batches"), 1)
                self.assertEqual(self._count(conn, "raw_events"), 2)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM raw_events WHERE is_valid = 1").fetchone()[0],
                    2,
                )
                self.assertEqual(self._count(conn, "data_quality_events"), 0)
                self.assertEqual(self._count(conn, "domain_events"), 1)
                operation = conn.execute(
                    "SELECT status, operation_type FROM operation_requests"
                ).fetchone()
                self.assertEqual(operation, ("success", "raw_import"))
                self.assertEqual(self._count(conn, "feature_snapshots"), 0)
                self.assertEqual(self._count(conn, "strategy_signals"), 0)
                self.assertEqual(self._count(conn, "portfolio_accounts"), 0)

    def test_csv_fixture_imports_with_date_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            service = RawIngestionService(db_path)

            result = service.import_raw_events(
                ImportRawEventsRequest(FIXTURES / "pgc_events_clean.csv"),
                RequestContext(request_id="req-csv"),
            )

            self.assertEqual(result.status, "success")
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT entry_date FROM raw_events ORDER BY ts_code"
                ).fetchall()
                self.assertEqual([row[0] for row in rows], ["20251110", "20251111"])

    def test_forbidden_fields_create_blocker_without_raw_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            service = RawIngestionService(db_path)

            result = service.import_raw_events(
                ImportRawEventsRequest(FIXTURES / "pgc_events_forbidden_fields.json"),
                RequestContext(
                    request_id="req-forbidden",
                    idempotency_key="raw-import:forbidden",
                    operator="tester",
                ),
            )

            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.errors[0].code, "FUTURE_DATA_DETECTED")
            self.assertEqual(result.errors[0].severity, "blocker")

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "raw_import_batches"), 0)
                self.assertEqual(self._count(conn, "raw_events"), 0)
                quality = conn.execute(
                    """
                    SELECT severity, event_code, entity_type, payload_json
                    FROM data_quality_events
                    """
                ).fetchone()
                self.assertEqual(quality[0], "blocker")
                self.assertEqual(quality[1], "RAW_FORBIDDEN_FIELDS")
                self.assertEqual(quality[2], "raw_import")
                self.assertIn("bull_prob", quality[3])
                self.assertEqual(
                    conn.execute("SELECT status, error_code FROM operation_requests").fetchone(),
                    ("failed", "FUTURE_DATA_DETECTED"),
                )

    def test_duplicate_source_hash_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            service = RawIngestionService(db_path)
            request = ImportRawEventsRequest(FIXTURES / "pgc_events_clean.json")

            first = service.import_raw_events(request, RequestContext(request_id="req-first"))
            second = service.import_raw_events(request, RequestContext(request_id="req-second"))

            self.assertEqual(first.status, "success")
            self.assertEqual(second.status, "skipped")
            self.assertEqual(first.data.raw_import_batch_id, second.data.raw_import_batch_id)
            self.assertEqual(second.data.duplicate_count, 2)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "raw_import_batches"), 1)
                self.assertEqual(self._count(conn, "raw_events"), 2)

    def test_duplicate_rows_do_not_duplicate_raw_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            service = RawIngestionService(db_path)

            result = service.import_raw_events(
                ImportRawEventsRequest(FIXTURES / "pgc_events_duplicate.json"),
                RequestContext(request_id="req-duplicates"),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.row_count, 3)
            self.assertEqual(result.data.valid_count, 3)
            self.assertEqual(result.data.duplicate_count, 1)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "raw_events"), 2)

    def test_known_dirty_longhua_event_is_marked_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            service = RawIngestionService(db_path)

            result = service.import_raw_events(
                ImportRawEventsRequest(FIXTURES / "pgc_events_dirty_longhua.json"),
                RequestContext(request_id="req-dirty"),
            )

            self.assertEqual(result.status, "partial_success")
            self.assertEqual(result.data.row_count, 2)
            self.assertEqual(result.data.valid_count, 1)
            self.assertEqual(result.data.dirty_count, 1)
            self.assertEqual(result.data.invalid_events[0].name, "隆化科技")

            with sqlite3.connect(db_path) as conn:
                dirty = conn.execute(
                    """
                    SELECT is_valid, invalid_reason
                    FROM raw_events
                    WHERE ts_code = '300263.SZ'
                    """
                ).fetchone()
                self.assertEqual(dirty, (0, "known_dirty_longhua_technology"))
                quality = conn.execute(
                    "SELECT severity, event_code FROM data_quality_events"
                ).fetchone()
                self.assertEqual(quality, ("warning", "RAW_KNOWN_DIRTY_EVENT"))
                self.assertEqual(self._count(conn, "feature_snapshots"), 0)
                self.assertEqual(self._count(conn, "strategy_signals"), 0)
                self.assertEqual(self._count(conn, "portfolio_accounts"), 0)

    def test_dry_run_validates_without_writing_any_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            service = RawIngestionService(db_path)

            result = service.import_raw_events(
                ImportRawEventsRequest(FIXTURES / "pgc_events_clean.json"),
                RequestContext(
                    request_id="req-dry-run",
                    idempotency_key="raw-import:dry-run",
                    dry_run=True,
                    operator="tester",
                ),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNone(result.data.raw_import_batch_id)
            with sqlite3.connect(db_path) as conn:
                for table in (
                    "raw_import_batches",
                    "raw_events",
                    "data_quality_events",
                    "domain_events",
                    "operation_requests",
                    "feature_snapshots",
                    "strategy_signals",
                    "portfolio_accounts",
                ):
                    self.assertEqual(self._count(conn, table), 0, table)

    def _migrated_db(self, tmp: str) -> Path:
        db_path = Path(tmp) / "pgc.db"
        run_migrations(db_path)
        return db_path

    def _count(self, conn: sqlite3.Connection, table: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


if __name__ == "__main__":
    unittest.main()

