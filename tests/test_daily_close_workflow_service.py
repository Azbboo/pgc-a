from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.daily_close_workflow_service import (
    DailyCloseWorkflowService,
    RunDailyCloseWorkflowRequest,
)
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data


ACCOUNT_KEY = "paper-200k"
AS_OF_DATE = "20260504"
ENTRY_DATE = "20260427"
BUY_DATE = "20260505"


class DailyCloseWorkflowServiceTest(unittest.TestCase):
    def test_data_quality_blocker_prevents_review_and_plan_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_contracting_pullback_case(conn, "000001.SZ", "Blocked", 1.0)

            result = DailyCloseWorkflowService(db_path).run_daily_close(
                RunDailyCloseWorkflowRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-close-blocked", operator="tester"),
            )

            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.data.workflow_status, "data_quality_blocker")
            self.assertEqual(result.data.readiness, "blocker")
            self.assertEqual(result.errors[0].code, "TRADE_CALENDAR_MISSING")
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "feature_runs"), 0)
                self.assertEqual(self._count(conn, "strategy_runs"), 0)
                self.assertEqual(self._count(conn, "daily_picks"), 0)
                self.assertEqual(self._count(conn, "trade_plans"), 0)
                self.assertEqual(self._count(conn, "trades"), 0)
                self.assertEqual(self._count(conn, "positions"), 0)

    def test_no_candidate_returns_clear_no_pick_without_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_open_calendar(conn)

            result = DailyCloseWorkflowService(db_path).run_daily_close(
                RunDailyCloseWorkflowRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-close-no-pick", operator="tester"),
            )

            self.assertEqual(result.status, "skipped")
            self.assertEqual(result.data.workflow_status, "no_pick")
            self.assertEqual(result.data.skipped_reason, "no_valid_raw_events")
            self.assertEqual(result.data.signals_count, 0)
            self.assertIsNone(result.data.candidate)
            self.assertIsNone(result.data.buy_plan)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "daily_picks"), 0)
                self.assertEqual(self._count(conn, "trade_plans"), 0)

    def test_one_candidate_with_capacity_creates_active_buy_plan_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_open_calendar(conn)
                self._insert_contracting_pullback_case(conn, "000001.SZ", "Workflow Pick", 1.0)

            result = DailyCloseWorkflowService(db_path).run_daily_close(
                RunDailyCloseWorkflowRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(
                    request_id="req-close-plan",
                    idempotency_key="daily-close:test:plan",
                    operator="tester",
                ),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.workflow_status, "plan_ready")
            self.assertEqual(result.data.next_trade_date, BUY_DATE)
            self.assertIsNotNone(result.data.candidate)
            self.assertEqual(result.data.candidate.ts_code, "000001.SZ")
            self.assertIsNotNone(result.data.buy_plan)
            self.assertEqual(result.data.buy_plan.action, "buy_next_open")
            self.assertEqual(result.data.buy_plan.status, "active")
            self.assertEqual(result.data.buy_plan.planned_trade_date, BUY_DATE)
            self.assertGreater(result.data.buy_plan.planned_shares, 0)

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "daily_picks"), 1)
                self.assertEqual(self._count(conn, "trade_plans"), 1)
                self.assertEqual(self._count(conn, "trades"), 0)
                self.assertEqual(self._count(conn, "positions"), 0)

    def test_rerun_returns_existing_review_and_buy_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_open_calendar(conn)
                self._insert_contracting_pullback_case(conn, "000001.SZ", "Idempotent Pick", 1.0)

            service = DailyCloseWorkflowService(db_path)
            request = RunDailyCloseWorkflowRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY)
            ctx = RequestContext(
                request_id="req-close-idempotent-1",
                idempotency_key="daily-close:test:idempotent",
                operator="tester",
            )

            first = service.run_daily_close(request, ctx)
            second = service.run_daily_close(
                request,
                RequestContext(
                    request_id="req-close-idempotent-2",
                    idempotency_key="daily-close:test:idempotent",
                    operator="tester",
                ),
            )

            self.assertEqual(first.status, "success")
            self.assertEqual(second.status, "success")
            self.assertEqual(second.data.buy_plan.trade_plan_id, first.data.buy_plan.trade_plan_id)
            self.assertTrue(second.data.buy_plan.idempotent)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "strategy_runs"), 1)
                self.assertEqual(self._count(conn, "daily_picks"), 1)
                self.assertEqual(self._count(conn, "trade_plans"), 1)

    def _migrated_seeded_db(self, tmp: str) -> Path:
        db_path = Path(tmp) / "pgc.db"
        run_migrations(db_path)
        seed_reference_data(db_path)
        return db_path

    def _insert_open_calendar(self, conn: sqlite3.Connection) -> None:
        conn.executemany(
            """
            INSERT INTO trade_calendar (exchange, cal_date, is_open, pretrade_date)
            VALUES ('SSE', ?, 1, ?)
            """,
            [
                (AS_OF_DATE, "20260501"),
                (BUY_DATE, AS_OF_DATE),
                ("20260506", BUY_DATE),
            ],
        )

    def _insert_contracting_pullback_case(
        self,
        conn: sqlite3.Connection,
        ts_code: str,
        name: str,
        price_scale: float,
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO raw_events
              (ts_code, code, name, entry_date, entry_time, entry_price)
            VALUES
              (?, substr(?, 1, 6), ?, ?, '15:00', ?)
            """,
            (ts_code, ts_code, name, ENTRY_DATE, 10.0 * price_scale),
        )
        raw_event_id = int(cursor.lastrowid)
        bars = [
            ("20260424", 9.6, 9.8, 9.5, 9.7, 950.0),
            (ENTRY_DATE, 10.0, 10.2, 9.9, 10.0, 1000.0),
            ("20260428", 10.8, 11.2, 10.7, 11.0, 1200.0),
            ("20260429", 10.6, 10.7, 10.4, 10.5, 1000.0),
            ("20260430", 10.3, 10.4, 9.95, 10.0, 800.0),
            ("20260501", 9.8, 9.85, 9.55, 9.65, 700.0),
            (AS_OF_DATE, 9.7, 10.0, 9.6, 9.9, 900.0),
        ]
        for trade_date, open_price, high, low, close, amount in bars:
            self._insert_market_bar(
                conn,
                ts_code=ts_code,
                trade_date=trade_date,
                open_price=open_price * price_scale,
                high=high * price_scale,
                low=low * price_scale,
                close=close * price_scale,
                amount=amount,
            )
        return raw_event_id

    def _insert_market_bar(
        self,
        conn: sqlite3.Connection,
        ts_code: str,
        trade_date: str,
        open_price: float,
        high: float,
        low: float,
        close: float,
        amount: float,
    ) -> None:
        conn.execute(
            """
            INSERT INTO market_bars
              (
                ts_code,
                trade_date,
                open,
                high,
                low,
                close,
                vol,
                amount,
                adj_open,
                adj_high,
                adj_low,
                adj_close
              )
            VALUES
              (?, ?, ?, ?, ?, ?, 100000, ?, ?, ?, ?, ?)
            """,
            (
                ts_code,
                trade_date,
                open_price,
                high,
                low,
                close,
                amount,
                open_price,
                high,
                low,
                close,
            ),
        )

    def _count(self, conn: sqlite3.Connection, table: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
