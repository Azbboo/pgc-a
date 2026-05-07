from __future__ import annotations

import contextlib
import io
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from collections.abc import Iterator
from pathlib import Path

from pgc_trading.market.tushare_adapter import (
    MarketBar,
    MarketDataPayload,
    TushareAdapter,
    TushareConfigurationError,
)
from pgc_trading.services.common import RequestContext
from pgc_trading.services.market_data_service import MarketDataService, RefreshMarketDataRequest
from pgc_trading.storage.migrate import run_migrations


class FakeTushareModule(types.SimpleNamespace):
    def __init__(self) -> None:
        super().__init__()
        self.set_tokens: list[str] = []
        self.pro_api_tokens: list[str] = []

    def set_token(self, token: str) -> None:
        self.set_tokens.append(token)

    def pro_api(self, token: str) -> object:
        self.pro_api_tokens.append(token)
        return object()


class StartedRunCheckingAdapter:
    provider = "mock"

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.run_seen: tuple[object, ...] | None = None
        self.operation_seen: tuple[object, ...] | None = None

    def fetch_market_data(
        self,
        ts_codes,
        start_date: str,
        end_date: str,
        include_daily_basic: bool = True,
    ) -> MarketDataPayload:
        with sqlite3.connect(self.db_path) as conn:
            self.run_seen = conn.execute(
                """
                SELECT provider, start_date, end_date, status, ts_code_count
                FROM market_fetch_runs
                """
            ).fetchone()
            self.operation_seen = conn.execute(
                """
                SELECT status, operation_type, as_of_date
                FROM operation_requests
                """
            ).fetchone()
        return MarketDataPayload(
            bars=[
                MarketBar(
                    ts_code=ts_codes[0],
                    trade_date=end_date,
                    open=10.0,
                    high=10.8,
                    low=9.9,
                    close=10.4,
                    vol=100000,
                    amount=1040000,
                    adj_factor=1.0,
                    adj_open=10.0,
                    adj_high=10.8,
                    adj_low=9.9,
                    adj_close=10.4,
                )
            ]
        )

    def fetch_trade_calendar(
        self,
        start_date: str,
        end_date: str,
        exchange: str = "SSE",
    ):
        raise AssertionError("Unexpected calendar adapter call.")


class TushareAdapterConfigTest(unittest.TestCase):
    def test_missing_or_blank_token_raises_clear_error_before_importing_tushare(self) -> None:
        env_var = "PGC_TEST_TUSHARE_RUNTIME_VALUE"
        for value in (None, "   "):
            with self.subTest(value=value), _patched_env(env_var, value):
                with self.assertRaises(TushareConfigurationError) as caught:
                    TushareAdapter(token_env_var=env_var)

            self.assertEqual(
                str(caught.exception),
                f"{env_var} is required in the environment for real Tushare fetches.",
            )

    def test_token_is_read_from_environment_without_printing_or_storing_it(self) -> None:
        env_var = "PGC_TEST_TUSHARE_RUNTIME_VALUE"
        env_value = "dev4-placeholder-value"
        fake_tushare = FakeTushareModule()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            _patched_env(env_var, env_value),
            _patched_module("tushare", fake_tushare),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            adapter = TushareAdapter(token_env_var=env_var)

        self.assertEqual(fake_tushare.set_tokens, [env_value])
        self.assertEqual(fake_tushare.pro_api_tokens, [env_value])
        self.assertNotIn(env_value, stdout.getvalue())
        self.assertNotIn(env_value, stderr.getvalue())
        self.assertNotIn(env_value, repr(adapter))
        self.assertFalse(hasattr(adapter, "_token"))

    def test_market_fetch_run_and_operation_are_recorded_before_external_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _migrated_db(tmp)
            with sqlite3.connect(db_path) as conn:
                _insert_raw_event(conn, "000001.SZ", "20260504")

            adapter = StartedRunCheckingAdapter(db_path)
            service = MarketDataService(db_path, adapter=adapter)
            result = service.refresh_market_data(
                RefreshMarketDataRequest(
                    start_date="20260504",
                    end_date="20260504",
                    provider="mock",
                    include_daily_basic=False,
                ),
                RequestContext(
                    request_id="req-dev4-started",
                    idempotency_key="dev4:started-run",
                    operator="tester",
                ),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(
                adapter.run_seen,
                ("mock", "20260504", "20260504", "started", 1),
            )
            self.assertEqual(
                adapter.operation_seen,
                ("started", "market_data_refresh", "20260504"),
            )
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(
                    conn.execute("SELECT status FROM market_fetch_runs").fetchone()[0],
                    "completed",
                )
                self.assertEqual(
                    conn.execute("SELECT status FROM operation_requests").fetchone()[0],
                    "success",
                )

    def test_missing_real_tushare_token_records_failed_fetch_without_network(self) -> None:
        old_token = os.environ.get("TUSHARE_TOKEN")
        os.environ.pop("TUSHARE_TOKEN", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                db_path = _migrated_db(tmp)
                with sqlite3.connect(db_path) as conn:
                    _insert_raw_event(conn, "000001.SZ", "20260504")

                service = MarketDataService(db_path)
                result = service.refresh_market_data(
                    RefreshMarketDataRequest(
                        start_date="20260504",
                        end_date="20260504",
                        provider="tushare",
                    ),
                    RequestContext(
                        request_id="req-dev4-missing-token",
                        idempotency_key="dev4:missing-token",
                    ),
                )

                self.assertEqual(result.status, "failed")
                self.assertEqual(result.errors[0].code, "MARKET_PROVIDER_ERROR")
                self.assertIn("TUSHARE_TOKEN is required", result.errors[0].message)
                self.assertIsNotNone(result.data)
                self.assertIsNotNone(result.data.market_fetch_run_id)
                with sqlite3.connect(db_path) as conn:
                    fetch_run = conn.execute(
                        """
                        SELECT provider, status, error_message
                        FROM market_fetch_runs
                        """
                    ).fetchone()
                    operation = conn.execute(
                        """
                        SELECT status, error_code, error_message
                        FROM operation_requests
                        """
                    ).fetchone()
                self.assertEqual(fetch_run[0], "tushare")
                self.assertEqual(fetch_run[1], "failed")
                self.assertIn("TUSHARE_TOKEN is required", fetch_run[2])
                self.assertEqual(operation[0], "failed")
                self.assertEqual(operation[1], "MARKET_PROVIDER_ERROR")
                self.assertIn("TUSHARE_TOKEN is required", operation[2])
        finally:
            if old_token is None:
                os.environ.pop("TUSHARE_TOKEN", None)
            else:
                os.environ["TUSHARE_TOKEN"] = old_token


@contextlib.contextmanager
def _patched_env(name: str, value: str | None) -> Iterator[None]:
    old_value = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if old_value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old_value


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


def _insert_raw_event(conn: sqlite3.Connection, ts_code: str, entry_date: str) -> int:
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


if __name__ == "__main__":
    unittest.main()
