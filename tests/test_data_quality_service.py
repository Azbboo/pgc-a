from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.data_quality_service import (
    DailyReviewReadinessRequest,
    DataQualityService,
    ListDataQualityEventsRequest,
    ResolveDataQualityEventRequest,
)
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data
from pgc_trading.strategies.cpb_6157 import STRATEGY_VERSION


AS_OF_DATE = "20260504"


class DataQualityServiceTest(unittest.TestCase):
    def test_clean_readiness_passes_with_valid_candidate_market_and_calendar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            service = DataQualityService(db_path)
            with sqlite3.connect(db_path) as conn:
                raw_event_id = self._insert_raw_event(conn)
                self._insert_open_calendar(conn)
                self._insert_market_bar(conn, ts_code="000001.SZ")

            result = service.check_daily_review_readiness(
                DailyReviewReadinessRequest(
                    as_of_date=AS_OF_DATE,
                    strategy_version=STRATEGY_VERSION,
                    account_key="paper-main",
                ),
                RequestContext(
                    request_id="req-clean",
                    idempotency_key="dq:paper-main:20260504",
                    operator="tester",
                ),
            )

            self.assertEqual(result.status, "success")
            self.assertTrue(result.ok)
            self.assertIsNotNone(result.data)
            self.assertEqual(result.data.readiness, "pass")
            self.assertEqual(result.data.valid_raw_count, 1)
            self.assertTrue(result.data.trade_calendar_ok)
            self.assertTrue(result.data.market_coverage_ok)
            self.assertTrue(result.data.strategy_version_ok)
            self.assertTrue(result.data.account_ok)
            self.assertEqual(result.data.missing_market_bar_count, 0)

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "data_quality_events"), 0)
                operation = conn.execute(
                    """
                    SELECT status, operation_type, as_of_date
                    FROM operation_requests
                    """
                ).fetchone()
                self.assertEqual(operation, ("success", "data_quality_check", AS_OF_DATE))
                self.assertEqual(self._count(conn, "domain_events"), 1)
                self.assertEqual(
                    conn.execute("SELECT id FROM raw_events").fetchone()[0],
                    raw_event_id,
                )

    def test_missing_trade_calendar_returns_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            service = DataQualityService(db_path)
            with sqlite3.connect(db_path) as conn:
                self._insert_raw_event(conn)

            result = service.check_daily_review_readiness(
                DailyReviewReadinessRequest(
                    as_of_date=AS_OF_DATE,
                    strategy_version=STRATEGY_VERSION,
                    account_key="paper-main",
                ),
                RequestContext(request_id="req-calendar"),
            )

            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.errors[0].code, "TRADE_CALENDAR_MISSING")
            self.assertEqual(result.data.readiness, "blocker")
            self.assertEqual(result.data.blocker_count, 1)
            self.assertFalse(result.data.trade_calendar_ok)
            self.assertFalse(result.data.market_coverage_ok)

            with sqlite3.connect(db_path) as conn:
                event = conn.execute(
                    """
                    SELECT layer, severity, event_code, entity_type, trade_date, status
                    FROM data_quality_events
                    """
                ).fetchone()
                self.assertEqual(
                    event,
                    (
                        "market",
                        "blocker",
                        "TRADE_CALENDAR_MISSING",
                        "trade_calendar",
                        AS_OF_DATE,
                        "open",
                    ),
                )

    def test_missing_market_bars_for_candidate_returns_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            service = DataQualityService(db_path)
            with sqlite3.connect(db_path) as conn:
                raw_event_id = self._insert_raw_event(conn, ts_code="000002.SZ")
                self._insert_open_calendar(conn)

            result = service.check_daily_review_readiness(
                DailyReviewReadinessRequest(
                    as_of_date=AS_OF_DATE,
                    strategy_version=STRATEGY_VERSION,
                    account_key="paper-main",
                ),
                RequestContext(request_id="req-market"),
            )

            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.errors[0].code, "MARKET_DATA_NOT_READY")
            self.assertEqual(result.data.readiness, "blocker")
            self.assertEqual(result.data.blocker_count, 1)
            self.assertEqual(result.data.missing_market_bar_count, 1)
            self.assertFalse(result.data.market_coverage_ok)

            with sqlite3.connect(db_path) as conn:
                event = conn.execute(
                    """
                    SELECT layer, severity, event_code, entity_type, entity_id, ts_code, trade_date
                    FROM data_quality_events
                    """
                ).fetchone()
                self.assertEqual(
                    event,
                    (
                        "market",
                        "blocker",
                        "MARKET_BAR_MISSING",
                        "raw_event",
                        raw_event_id,
                        "000002.SZ",
                        AS_OF_DATE,
                    ),
                )

    def test_open_warning_does_not_block_readiness_and_invalid_raw_is_not_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            service = DataQualityService(db_path)
            with sqlite3.connect(db_path) as conn:
                self._insert_raw_event(conn, ts_code="000001.SZ")
                self._insert_raw_event(
                    conn,
                    ts_code="000003.SZ",
                    is_valid=False,
                    invalid_reason="known_dirty_fixture",
                )
                self._insert_open_calendar(conn)
                self._insert_market_bar(conn, ts_code="000001.SZ")
                conn.execute(
                    """
                    INSERT INTO data_quality_events
                      (
                        layer,
                        severity,
                        event_code,
                        entity_type,
                        ts_code,
                        trade_date,
                        message
                      )
                    VALUES
                      (
                        'raw',
                        'warning',
                        'RAW_KNOWN_DIRTY_EVENT',
                        'raw_event',
                        '000003.SZ',
                        ?,
                        'Known dirty raw event marked invalid.'
                      )
                    """,
                    (AS_OF_DATE,),
                )

            result = service.check_daily_review_readiness(
                DailyReviewReadinessRequest(
                    as_of_date=AS_OF_DATE,
                    strategy_version=STRATEGY_VERSION,
                    account_key="paper-main",
                ),
                RequestContext(request_id="req-warning"),
            )

            self.assertEqual(result.status, "partial_success")
            self.assertTrue(result.ok)
            self.assertEqual(result.data.readiness, "warning")
            self.assertEqual(result.data.blocker_count, 0)
            self.assertEqual(result.data.warning_count, 1)
            self.assertEqual(result.data.valid_raw_count, 1)
            self.assertEqual(result.data.missing_market_bar_count, 0)
            self.assertEqual(result.warnings[0].code, "DATA_QUALITY_WARNINGS_PRESENT")
            self.assertEqual(result.errors, [])

    def test_list_and_resolve_events_support_quality_follow_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            service = DataQualityService(db_path)
            with sqlite3.connect(db_path) as conn:
                event_id = self._insert_warning_event(conn)

            listed = service.list_events(ListDataQualityEventsRequest(status="open"))

            self.assertEqual(listed.status, "success")
            self.assertEqual(len(listed.data), 1)
            self.assertEqual(listed.data[0].id, event_id)

            resolved = service.resolve_event(
                ResolveDataQualityEventRequest(event_id=event_id),
                RequestContext(request_id="req-resolve", operator="tester"),
            )

            self.assertEqual(resolved.status, "success")
            self.assertEqual(resolved.data.status, "resolved")
            self.assertIsNotNone(resolved.data.resolved_at)
            self.assertEqual(
                service.list_events(ListDataQualityEventsRequest(status="open")).data,
                [],
            )

    def _migrated_seeded_db(self, tmp: str) -> Path:
        db_path = Path(tmp) / "pgc.db"
        run_migrations(db_path)
        seed_reference_data(db_path)
        return db_path

    def _insert_open_calendar(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO trade_calendar (exchange, cal_date, is_open, pretrade_date)
            VALUES ('SSE', ?, 1, '20260430')
            """,
            (AS_OF_DATE,),
        )

    def _insert_market_bar(self, conn: sqlite3.Connection, ts_code: str) -> None:
        conn.execute(
            """
            INSERT INTO market_bars
              (ts_code, trade_date, open, high, low, close, vol, amount)
            VALUES
              (?, ?, 10.0, 10.6, 9.9, 10.4, 100000, 1040000)
            """,
            (ts_code, AS_OF_DATE),
        )

    def _insert_raw_event(
        self,
        conn: sqlite3.Connection,
        ts_code: str = "000001.SZ",
        is_valid: bool = True,
        invalid_reason: str | None = None,
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO raw_events
              (
                ts_code,
                code,
                name,
                entry_date,
                entry_time,
                entry_price,
                source,
                is_valid,
                invalid_reason
              )
            VALUES
              (?, substr(?, 1, 6), 'PGC candidate', '20260503', '15:00', 10.0, 'pgc_pool', ?, ?)
            """,
            (ts_code, ts_code, 1 if is_valid else 0, invalid_reason),
        )
        return int(cursor.lastrowid)

    def _insert_warning_event(self, conn: sqlite3.Connection) -> int:
        cursor = conn.execute(
            """
            INSERT INTO data_quality_events
              (layer, severity, event_code, entity_type, trade_date, message)
            VALUES
              ('raw', 'warning', 'RAW_KNOWN_DIRTY_EVENT', 'raw_event', ?, 'Known dirty row.')
            """,
            (AS_OF_DATE,),
        )
        return int(cursor.lastrowid)

    def _count(self, conn: sqlite3.Connection, table: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
