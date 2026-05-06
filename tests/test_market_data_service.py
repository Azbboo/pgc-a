from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.market.tushare_adapter import (
    DailyBasicSnapshot,
    MarketBar,
    MarketDataPayload,
    TradeCalendarDay,
)
from pgc_trading.services.common import RequestContext
from pgc_trading.services.market_data_service import (
    RefreshMarketDataRequest,
    RefreshTradeCalendarRequest,
    MarketDataService,
)
from pgc_trading.storage.migrate import run_migrations


class MockMarketDataAdapter:
    provider = "mock"

    def __init__(
        self,
        payloads: list[MarketDataPayload] | None = None,
        calendar_days: list[TradeCalendarDay] | None = None,
    ):
        self.payloads = payloads or []
        self.calendar_days = calendar_days or []
        self.market_calls: list[dict[str, object]] = []
        self.calendar_calls: list[dict[str, object]] = []

    def fetch_market_data(
        self,
        ts_codes,
        start_date: str,
        end_date: str,
        include_daily_basic: bool = True,
    ) -> MarketDataPayload:
        self.market_calls.append(
            {
                "ts_codes": list(ts_codes),
                "start_date": start_date,
                "end_date": end_date,
                "include_daily_basic": include_daily_basic,
            }
        )
        if not self.payloads:
            raise AssertionError("Unexpected market-data adapter call.")
        return self.payloads.pop(0)

    def fetch_trade_calendar(
        self,
        start_date: str,
        end_date: str,
        exchange: str = "SSE",
    ):
        self.calendar_calls.append(
            {
                "start_date": start_date,
                "end_date": end_date,
                "exchange": exchange,
            }
        )
        return tuple(self.calendar_days)


class MarketDataServiceTest(unittest.TestCase):
    def test_refresh_market_data_uses_mock_adapter_and_writes_market_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_raw_event(conn, "000001.SZ", entry_date="20260503")

            adapter = MockMarketDataAdapter(
                payloads=[
                    MarketDataPayload(
                        bars=[
                            self._bar("000001.SZ", "20260503", close=10.1),
                            self._bar("000001.SZ", "20260504", close=10.4),
                        ],
                        daily_basic=[
                            DailyBasicSnapshot(
                                ts_code="000001.SZ",
                                trade_date="20260504",
                                turnover_rate=2.3,
                                pe=12.4,
                            )
                        ],
                    )
                ]
            )
            service = MarketDataService(db_path, adapter=adapter)

            result = service.refresh_market_data(
                RefreshMarketDataRequest(
                    start_date=None,
                    end_date="20260504",
                    provider="mock",
                ),
                RequestContext(
                    request_id="req-market",
                    idempotency_key="market:20260504",
                    operator="tester",
                ),
            )

            self.assertEqual(result.status, "success")
            self.assertTrue(result.ok)
            self.assertEqual(result.data.ts_code_count, 1)
            self.assertEqual(result.data.bars_upserted, 2)
            self.assertEqual(result.data.daily_basic_upserted, 1)
            self.assertEqual(result.data.coverage_start_date, "20260503")
            self.assertEqual(result.data.coverage_end_date, "20260504")
            self.assertEqual(
                adapter.market_calls,
                [
                    {
                        "ts_codes": ["000001.SZ"],
                        "start_date": "20260503",
                        "end_date": "20260504",
                        "include_daily_basic": True,
                    }
                ],
            )

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "market_fetch_runs"), 1)
                fetch_run = conn.execute(
                    "SELECT provider, start_date, end_date, ts_code_count, status FROM market_fetch_runs"
                ).fetchone()
                self.assertEqual(fetch_run, ("mock", "20260503", "20260504", 1, "completed"))
                self.assertEqual(self._count(conn, "market_bars"), 2)
                self.assertEqual(self._count(conn, "daily_basic_snapshots"), 1)
                self.assertEqual(self._count(conn, "data_quality_events"), 0)
                self.assertEqual(self._count(conn, "domain_events"), 1)
                operation = conn.execute(
                    "SELECT status, operation_type, as_of_date FROM operation_requests"
                ).fetchone()
                self.assertEqual(operation, ("success", "market_data_refresh", "20260504"))
                self.assertEqual(self._count(conn, "raw_events"), 1)
                self.assertEqual(self._count(conn, "feature_snapshots"), 0)
                self.assertEqual(self._count(conn, "strategy_signals"), 0)

    def test_repeated_refresh_upserts_market_bars_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_raw_event(conn, "000001.SZ", entry_date="20260504")

            adapter = MockMarketDataAdapter(
                payloads=[
                    MarketDataPayload(bars=[self._bar("000001.SZ", "20260504", close=10.4)]),
                    MarketDataPayload(bars=[self._bar("000001.SZ", "20260504", close=11.2)]),
                ]
            )
            service = MarketDataService(db_path, adapter=adapter)
            request = RefreshMarketDataRequest(
                start_date="20260504",
                end_date="20260504",
                provider="mock",
                include_daily_basic=False,
            )

            first = service.refresh_market_data(request, RequestContext(request_id="req-first"))
            second = service.refresh_market_data(request, RequestContext(request_id="req-second"))

            self.assertEqual(first.status, "success")
            self.assertEqual(second.status, "success")
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "market_fetch_runs"), 2)
                self.assertEqual(self._count(conn, "market_bars"), 1)
                row = conn.execute(
                    "SELECT close, fetch_run_id FROM market_bars WHERE ts_code = '000001.SZ'"
                ).fetchone()
                self.assertEqual(row[0], 11.2)
                self.assertEqual(row[1], second.data.market_fetch_run_id)

    def test_missing_ts_code_returns_partial_success_and_writes_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_raw_event(conn, "000001.SZ", entry_date="20260504")
                self._insert_raw_event(conn, "000002.SZ", entry_date="20260504")

            adapter = MockMarketDataAdapter(
                payloads=[
                    MarketDataPayload(
                        bars=[self._bar("000001.SZ", "20260504", close=10.4)],
                        missing_ts_codes=["000002.SZ"],
                    )
                ]
            )
            service = MarketDataService(db_path, adapter=adapter)

            result = service.refresh_market_data(
                RefreshMarketDataRequest(
                    start_date="20260504",
                    end_date="20260504",
                    provider="mock",
                    include_daily_basic=False,
                ),
                RequestContext(request_id="req-missing", idempotency_key="market:missing"),
            )

            self.assertEqual(result.status, "partial_success")
            self.assertEqual(result.data.missing_ts_codes, ["000002.SZ"])
            self.assertEqual(result.warnings[0].code, "MARKET_DATA_MISSING")

            with sqlite3.connect(db_path) as conn:
                fetch_run = conn.execute("SELECT status FROM market_fetch_runs").fetchone()
                self.assertEqual(fetch_run[0], "partial_success")
                event = conn.execute(
                    """
                    SELECT layer, severity, event_code, entity_type, ts_code, trade_date, status
                    FROM data_quality_events
                    """
                ).fetchone()
                self.assertEqual(
                    event,
                    (
                        "market",
                        "blocker",
                        "MARKET_DATA_MISSING",
                        "market_bar",
                        "000002.SZ",
                        "20260504",
                        "open",
                    ),
                )
                operation = conn.execute(
                    "SELECT status, operation_type FROM operation_requests"
                ).fetchone()
                self.assertEqual(operation, ("partial_success", "market_data_refresh"))

    def test_token_from_environment_is_not_written_when_adapter_is_mocked(self) -> None:
        old_token = os.environ.get("TUSHARE_TOKEN")
        secret = "secret-token-value-wp10"
        os.environ["TUSHARE_TOKEN"] = secret
        try:
            with tempfile.TemporaryDirectory() as tmp:
                db_path = self._migrated_db(tmp)
                with sqlite3.connect(db_path) as conn:
                    self._insert_raw_event(conn, "000001.SZ", entry_date="20260504")

                adapter = MockMarketDataAdapter(
                    payloads=[
                        MarketDataPayload(bars=[self._bar("000001.SZ", "20260504", close=10.4)])
                    ]
                )
                service = MarketDataService(db_path, adapter=adapter)
                result = service.refresh_market_data(
                    RefreshMarketDataRequest(
                        start_date="20260504",
                        end_date="20260504",
                        provider="mock",
                    ),
                    RequestContext(
                        request_id="req-token",
                        idempotency_key="market:token",
                        operator="tester",
                    ),
                )

                self.assertEqual(result.status, "success")
                with sqlite3.connect(db_path) as conn:
                    stored_text = "\n".join(
                        str(row[0])
                        for query in (
                            "SELECT manifest_json FROM market_fetch_runs",
                            "SELECT request_json FROM operation_requests",
                            "SELECT response_json FROM operation_requests",
                            "SELECT payload_json FROM domain_events",
                        )
                        for row in conn.execute(query).fetchall()
                    )
                self.assertNotIn(secret, stored_text)
        finally:
            if old_token is None:
                os.environ.pop("TUSHARE_TOKEN", None)
            else:
                os.environ["TUSHARE_TOKEN"] = old_token

    def test_dry_run_resolves_scope_without_calling_adapter_or_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_raw_event(conn, "000001.SZ", entry_date="20260504")

            adapter = MockMarketDataAdapter()
            service = MarketDataService(db_path, adapter=adapter)

            result = service.refresh_market_data(
                RefreshMarketDataRequest(
                    start_date=None,
                    end_date="20260504",
                    provider="mock",
                ),
                RequestContext(request_id="req-dry", dry_run=True),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.ts_code_count, 1)
            self.assertEqual(result.data.coverage_start_date, "20260504")
            self.assertEqual(adapter.market_calls, [])
            with sqlite3.connect(db_path) as conn:
                for table in (
                    "market_fetch_runs",
                    "market_bars",
                    "daily_basic_snapshots",
                    "data_quality_events",
                    "domain_events",
                    "operation_requests",
                ):
                    self.assertEqual(self._count(conn, table), 0, table)

    def test_refresh_trade_calendar_upserts_mock_calendar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            adapter = MockMarketDataAdapter(
                calendar_days=[
                    TradeCalendarDay("SSE", "20260504", True, "20260430"),
                    TradeCalendarDay("SSE", "20260505", False, "20260504"),
                ]
            )
            service = MarketDataService(db_path, adapter=adapter)

            result = service.refresh_trade_calendar(
                RefreshTradeCalendarRequest(
                    start_date="20260504",
                    end_date="20260505",
                    exchange="SSE",
                    provider="mock",
                ),
                RequestContext(
                    request_id="req-calendar",
                    idempotency_key="calendar:20260505",
                ),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.calendar_days_upserted, 2)
            self.assertEqual(result.data.open_days, 1)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "trade_calendar"), 2)
                self.assertEqual(self._count(conn, "domain_events"), 1)
                operation = conn.execute(
                    "SELECT status, operation_type FROM operation_requests"
                ).fetchone()
                self.assertEqual(operation, ("success", "trade_calendar_refresh"))

    def _migrated_db(self, tmp: str) -> Path:
        db_path = Path(tmp) / "pgc.db"
        run_migrations(db_path)
        return db_path

    def _insert_raw_event(
        self,
        conn: sqlite3.Connection,
        ts_code: str,
        entry_date: str,
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
                is_valid
              )
            VALUES
              (?, substr(?, 1, 6), 'PGC candidate', ?, '15:00', 10.0, 'pgc_pool', 1)
            """,
            (ts_code, ts_code, entry_date),
        )
        return int(cursor.lastrowid)

    def _bar(self, ts_code: str, trade_date: str, close: float) -> MarketBar:
        return MarketBar(
            ts_code=ts_code,
            trade_date=trade_date,
            open=10.0,
            high=10.8,
            low=9.9,
            close=close,
            vol=100000,
            amount=1040000,
            adj_factor=1.0,
            adj_open=10.0,
            adj_high=10.8,
            adj_low=9.9,
            adj_close=close,
        )

    def _count(self, conn: sqlite3.Connection, table: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


if __name__ == "__main__":
    unittest.main()

