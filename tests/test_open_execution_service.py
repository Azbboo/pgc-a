from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.open_execution_service import OpenExecutionRequest, OpenExecutionService
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data


ACCOUNT_KEY = "paper-main"
AS_OF_DATE = "20260511"
FUTURE_DATE = "20260512"
T2_DATE = "20260507"


class OpenExecutionServiceTest(unittest.TestCase):
    def test_active_buy_plan_due_today_returns_record_buy_with_market_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                account_id = self._account_id(conn)
                plan_id = self._insert_plan(conn, account_id, planned_trade_date=AS_OF_DATE)
                self._insert_market_plan_context(conn, plan_id)

            result = OpenExecutionService(db_path).get_open_execution(
                OpenExecutionRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-open-exec", dry_run=True, source="test"),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.status, "ready")
            self.assertEqual(result.data.next_action, "record_buy")
            self.assertEqual(result.data.primary_plan_id, plan_id)
            self.assertEqual(result.data.target_stock, "000001.SZ")
            self.assertTrue(result.data.operator_required)
            self.assertIsNotNone(result.data.market_plan_context)
            self.assertEqual(result.data.market_plan_context.alignment, "aligned")
            self.assertEqual(result.data.market_plan_context.risk_level, "medium")
            self.assertEqual(result.data.market_plan_context.management_action, "manual_review")
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "trade_plans"), 1)
                self.assertEqual(self._count(conn, "trades"), 0)

    def test_active_buy_plan_in_future_returns_wait(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                plan_id = self._insert_plan(conn, self._account_id(conn), planned_trade_date=FUTURE_DATE)

            result = OpenExecutionService(db_path).get_open_execution(
                OpenExecutionRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-open-future", dry_run=True, source="test"),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.status, "waiting")
            self.assertEqual(result.data.next_action, "wait")
            self.assertEqual(result.data.primary_plan_id, plan_id)
            self.assertEqual(result.data.planned_trade_date, FUTURE_DATE)
            self.assertFalse(result.data.operator_required)

    def test_consider_cancel_context_warns_without_cancelling_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                account_id = self._account_id(conn)
                plan_id = self._insert_plan(conn, account_id, planned_trade_date=AS_OF_DATE)
                self._insert_market_plan_context(conn, plan_id, management_action="consider_cancel")

            result = OpenExecutionService(db_path).get_open_execution(
                OpenExecutionRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-open-consider-cancel", dry_run=True, source="test"),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.next_action, "record_buy")
            self.assertEqual(result.data.market_plan_context.management_action, "consider_cancel")
            self.assertEqual(result.warnings[0].code, "MARKET_PLAN_CONTEXT_CONSIDER_CANCEL")
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT status FROM trade_plans WHERE id = ?", (plan_id,)).fetchone()[0], "active")
                self.assertEqual(self._count(conn, "trades"), 0)

    def test_executed_plan_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_plan(conn, self._account_id(conn), planned_trade_date=AS_OF_DATE, status="executed")

            result = OpenExecutionService(db_path).get_open_execution(
                OpenExecutionRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-open-none", dry_run=True, source="test"),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.status, "idle")
            self.assertEqual(result.data.next_action, "none")
            self.assertIsNone(result.data.primary_plan_id)
            self.assertFalse(result.data.operator_required)

    def test_due_t2_position_returns_evaluate_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                account_id = self._account_id(conn)
                position_id = self._insert_open_position(conn, account_id, planned_t2_date=T2_DATE)

            result = OpenExecutionService(db_path).get_open_execution(
                OpenExecutionRequest(as_of_date=T2_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-open-exit", dry_run=True, source="test"),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.status, "ready")
            self.assertEqual(result.data.next_action, "evaluate_exit")
            self.assertEqual(result.data.primary_position_id, position_id)
            self.assertEqual(result.data.target_stock, "000001.SZ")
            self.assertTrue(result.data.operator_required)

    def test_due_sell_plan_returns_record_sell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                account_id = self._account_id(conn)
                position_id = self._insert_open_position(conn, account_id, planned_t2_date=T2_DATE)
                sell_plan_id = self._insert_plan(
                    conn,
                    account_id,
                    planned_trade_date=T2_DATE,
                    action="sell_t2_take_profit",
                    plan_json={
                        "position_id": position_id,
                        "ts_code": "000001.SZ",
                        "name": "PGC Candidate",
                        "shares": 1000,
                    },
                )

            result = OpenExecutionService(db_path).get_open_execution(
                OpenExecutionRequest(as_of_date=T2_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-open-sell", dry_run=True, source="test"),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.status, "ready")
            self.assertEqual(result.data.next_action, "record_sell")
            self.assertEqual(result.data.primary_plan_id, sell_plan_id)
            self.assertEqual(result.data.primary_position_id, position_id)
            self.assertEqual(result.data.planned_shares, 1000)

    def test_invariant_failure_returns_blocked_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                account_id = self._account_id(conn)
                self._insert_open_position(conn, account_id, planned_t2_date=T2_DATE)
                conn.execute("UPDATE trades SET amount = 999 WHERE id = 1")

            result = OpenExecutionService(db_path).get_open_execution(
                OpenExecutionRequest(as_of_date=T2_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-open-blocked", dry_run=True, source="test"),
            )

            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.data.status, "blocked")
            self.assertEqual(result.data.next_action, "blocked")
            self.assertTrue(result.data.blocked_reasons)
            self.assertEqual(result.errors[0].code, "TRADE_AMOUNT_MISMATCH")
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "trades"), 1)
                self.assertEqual(self._count(conn, "positions"), 1)

    def _migrated_seeded_db(self, tmp: str) -> Path:
        db_path = Path(tmp) / "pgc.db"
        run_migrations(db_path)
        seed_reference_data(db_path)
        return db_path

    def _account_id(self, conn: sqlite3.Connection) -> int:
        return int(conn.execute("SELECT id FROM portfolio_accounts WHERE account_key = ?", (ACCOUNT_KEY,)).fetchone()[0])

    def _insert_plan(
        self,
        conn: sqlite3.Connection,
        account_id: int,
        *,
        planned_trade_date: str,
        action: str = "buy_next_open",
        status: str = "active",
        plan_json: dict[str, object] | None = None,
    ) -> int:
        payload = plan_json or {
            "ts_code": "000001.SZ",
            "name": "PGC Candidate",
            "planned_shares": 1000,
            "planned_cash": 10000.0,
        }
        cursor = conn.execute(
            """
            INSERT INTO trade_plans
              (account_id, as_of_date, planned_trade_date, planned_buy_date, action, reason, plan_json, status)
            VALUES
              (?, '20260510', ?, ?, ?, 'open-execution-test', ?, ?)
            """,
            (
                account_id,
                planned_trade_date,
                planned_trade_date if action == "buy_next_open" else None,
                action,
                json.dumps(payload, sort_keys=True),
                status,
            ),
        )
        return int(cursor.lastrowid)

    def _insert_open_position(self, conn: sqlite3.Connection, account_id: int, *, planned_t2_date: str) -> int:
        plan_id = self._insert_plan(conn, account_id, planned_trade_date="20260505", status="executed")
        trade = conn.execute(
            """
            INSERT INTO trades
              (
                account_id, trade_plan_id, ts_code, name, side, planned_date,
                executed_date, executed_price, amount, shares, status, source
              )
            VALUES
              (?, ?, '000001.SZ', 'PGC Candidate', 'buy', '20260505', '20260505', 10.0, 10000.0, 1000, 'executed', 'manual')
            """,
            (account_id, plan_id),
        )
        position = conn.execute(
            """
            INSERT INTO positions
              (
                account_id, entry_trade_id, ts_code, name, buy_date, buy_price,
                shares, cost, planned_t2_date, planned_t5_date, status
              )
            VALUES
              (?, ?, '000001.SZ', 'PGC Candidate', '20260505', 10.0, 1000, 10000.0, ?, '20260512', 'waiting_t2')
            """,
            (account_id, int(trade.lastrowid), planned_t2_date),
        )
        return int(position.lastrowid)

    def _insert_market_plan_context(
        self,
        conn: sqlite3.Connection,
        trade_plan_id: int,
        *,
        management_action: str = "manual_review",
    ) -> None:
        run = conn.execute(
            """
            INSERT INTO market_review_runs
              (as_of_date, status, provider_manifest_json, coverage_json, summary_json, completed_at)
            VALUES
              ('20260510', 'completed', '{}', '{}', '{}', CURRENT_TIMESTAMP)
            """
        )
        conn.execute(
            """
            INSERT INTO market_plan_contexts
              (market_review_run_id, trade_plan_id, alignment, risk_level, management_action, rationale, evidence_json)
            VALUES
              (?, ?, 'aligned', 'medium', ?, 'Market context requires manual review.', '{}')
            """,
            (int(run.lastrowid), trade_plan_id, management_action),
        )

    def _count(self, conn: sqlite3.Connection, table: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
