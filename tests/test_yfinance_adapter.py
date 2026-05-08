from __future__ import annotations

import contextlib
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from collections.abc import Iterator
from pathlib import Path

from pgc_trading.market.yfinance_adapter import (
    YFinanceAdapter,
    YFinanceUnsupportedError,
    yahoo_ticker_mapping,
)
from pgc_trading.services.common import RequestContext
from pgc_trading.services.market_data_service import (
    MarketDataService,
    RefreshMarketDataRequest,
    RefreshTradeCalendarRequest,
)
from pgc_trading.storage.migrate import run_migrations


class YFinanceAdapterTest(unittest.TestCase):
    def test_maps_ts_code_to_yahoo_symbol(self) -> None:
        self.assertEqual(yahoo_ticker_mapping("600519.SH").yahoo_symbol, "600519.SS")
        self.assertEqual(yahoo_ticker_mapping("000001.SZ").yahoo_symbol, "000001.SZ")

        beijing = yahoo_ticker_mapping("830799.BJ")
        self.assertEqual(beijing.yahoo_symbol, "830799.BJ")
        self.assertTrue(beijing.best_effort)

        with self.assertRaises(ValueError):
            yahoo_ticker_mapping("AAPL")

    def test_fetch_market_data_converts_download_records_without_daily_basic(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_download(ticker: str, **kwargs: object) -> list[dict[str, object]]:
            calls.append({"ticker": ticker, **kwargs})
            return [
                {
                    "Date": "2026-05-04",
                    "Open": 10.0,
                    "High": 11.0,
                    "Low": 9.5,
                    "Close": 10.0,
                    "Adj Close": 11.0,
                    "Volume": 123400,
                }
            ]

        payload = YFinanceAdapter(download=fake_download).fetch_market_data(
            ["600519.SH"],
            "20260504",
            "20260505",
            include_daily_basic=True,
        )

        self.assertEqual(len(payload.bars), 1)
        bar = payload.bars[0]
        self.assertEqual(bar.ts_code, "600519.SH")
        self.assertEqual(bar.trade_date, "20260504")
        self.assertEqual(bar.amount, None)
        self.assertAlmostEqual(bar.adj_factor or 0.0, 1.1)
        self.assertAlmostEqual(bar.adj_open or 0.0, 11.0)
        self.assertAlmostEqual(bar.adj_high or 0.0, 12.1)
        self.assertEqual(bar.adj_close, 11.0)
        self.assertEqual(payload.daily_basic, ())
        self.assertEqual(payload.missing_ts_codes, ())
        self.assertEqual(calls[0]["ticker"], "600519.SS")
        self.assertEqual(calls[0]["start"], "2026-05-04")
        self.assertEqual(calls[0]["end"], "2026-05-06")
        self.assertEqual(calls[0]["auto_adjust"], False)
        self.assertEqual(calls[0]["actions"], False)
        self.assertEqual(calls[0]["threads"], False)
        self.assertEqual(calls[0]["progress"], False)
        self.assertEqual(payload.metadata["yfinance"]["daily_basic_supported"], False)

    def test_empty_download_marks_ts_code_missing(self) -> None:
        payload = YFinanceAdapter(download=lambda *_args, **_kwargs: []).fetch_market_data(
            ["000001.SZ"],
            "20260504",
            "20260504",
            include_daily_basic=False,
        )

        self.assertEqual(payload.bars, ())
        self.assertEqual(payload.missing_ts_codes, ("000001.SZ",))

    def test_trade_calendar_is_explicitly_unsupported(self) -> None:
        with self.assertRaises(YFinanceUnsupportedError):
            YFinanceAdapter(download=lambda *_args, **_kwargs: []).fetch_trade_calendar(
                "20260504",
                "20260505",
            )


class YFinanceMarketDataServiceTest(unittest.TestCase):
    def test_provider_yfinance_records_bars_metadata_and_daily_basic_warning(self) -> None:
        fake_yfinance = types.SimpleNamespace()
        calls: list[dict[str, object]] = []

        def fake_download(ticker: str, **kwargs: object) -> list[dict[str, object]]:
            calls.append({"ticker": ticker, **kwargs})
            return [
                {
                    "Date": "2026-05-04",
                    "Open": 10.0,
                    "High": 10.8,
                    "Low": 9.9,
                    "Close": 10.4,
                    "Adj Close": 10.4,
                    "Volume": 100000,
                }
            ]

        fake_yfinance.download = fake_download

        with tempfile.TemporaryDirectory() as tmp, _patched_module("yfinance", fake_yfinance):
            db_path = _migrated_db(tmp)
            service = MarketDataService(db_path)

            result = service.refresh_market_data(
                RefreshMarketDataRequest(
                    start_date="20260504",
                    end_date="20260504",
                    scope="ts_codes",
                    ts_codes=["600519.SH"],
                    provider="yfinance",
                    include_daily_basic=True,
                ),
                RequestContext(
                    request_id="req-yfinance",
                    idempotency_key="market:yfinance",
                    operator="tester",
                ),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.bars_upserted, 1)
            self.assertEqual(result.data.daily_basic_upserted, 0)
            self.assertEqual(result.warnings[0].code, "YFINANCE_DAILY_BASIC_UNSUPPORTED")
            self.assertEqual(calls[0]["ticker"], "600519.SS")
            self.assertEqual(calls[0]["end"], "2026-05-05")

            with sqlite3.connect(db_path) as conn:
                bar = conn.execute(
                    """
                    SELECT provider, amount, close
                    FROM market_diagnostic_bars
                    WHERE ts_code = '600519.SH'
                    """
                ).fetchone()
                self.assertEqual(bar, ("yfinance", None, 10.4))
                self.assertEqual(_count(conn, "market_bars"), 0)
                fetch_run = conn.execute(
                    "SELECT provider, status, manifest_json FROM market_fetch_runs"
                ).fetchone()

            self.assertEqual(fetch_run[0], "yfinance")
            self.assertEqual(fetch_run[1], "completed")
            manifest = json.loads(fetch_run[2])
            self.assertEqual(manifest["include_daily_basic"], True)
            self.assertEqual(manifest["effective_include_daily_basic"], False)
            self.assertEqual(manifest["storage_table"], "market_diagnostic_bars")
            mapping = manifest["provider_metadata"]["yfinance"]["ticker_mappings"][0]
            self.assertEqual(mapping["yahoo_symbol"], "600519.SS")
            self.assertEqual(manifest["provider_metadata"]["yfinance"]["amount_supported"], False)

    def test_provider_yfinance_missing_rows_do_not_create_production_quality_blockers(self) -> None:
        fake_yfinance = types.SimpleNamespace(download=lambda *_args, **_kwargs: [])

        with tempfile.TemporaryDirectory() as tmp, _patched_module("yfinance", fake_yfinance):
            db_path = _migrated_db(tmp)
            service = MarketDataService(db_path)

            result = service.refresh_market_data(
                RefreshMarketDataRequest(
                    start_date="20260504",
                    end_date="20260504",
                    scope="ts_codes",
                    ts_codes=["600519.SH"],
                    provider="yfinance",
                    include_daily_basic=False,
                ),
                RequestContext(
                    request_id="req-yfinance-missing",
                    idempotency_key="market:yfinance-missing",
                    operator="tester",
                ),
            )

            self.assertEqual(result.status, "partial_success")
            self.assertEqual(result.data.missing_ts_codes, ["600519.SH"])
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(_count(conn, "market_bars"), 0)
                self.assertEqual(_count(conn, "market_diagnostic_bars"), 0)
                self.assertEqual(_count(conn, "data_quality_events"), 0)

    def test_provider_yfinance_trade_calendar_returns_provider_error_without_dependency(self) -> None:
        result = MarketDataService(Path("/tmp/nonexistent-pgc-test.db")).refresh_trade_calendar(
            RefreshTradeCalendarRequest(
                start_date="20260504",
                end_date="20260505",
                provider="yfinance",
            ),
            RequestContext(request_id="req-calendar", dry_run=True),
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.errors[0].code, "MARKET_PROVIDER_ERROR")
        self.assertIn("does not provide a reliable trade calendar", result.errors[0].message)


@contextlib.contextmanager
def _patched_module(name: str, module: object) -> Iterator[None]:
    old_module = sys.modules.get(name)
    had_module = name in sys.modules
    sys.modules[name] = module
    try:
        yield
    finally:
        if had_module:
            sys.modules[name] = old_module
        else:
            sys.modules.pop(name, None)


def _migrated_db(tmp: str) -> Path:
    db_path = Path(tmp) / "pgc.db"
    run_migrations(db_path)
    return db_path


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
