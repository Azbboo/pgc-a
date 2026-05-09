from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.storage.invariant_checks import (
    InvariantCheckError,
    assert_database_invariants,
    check_connection,
    check_database,
)
from pgc_trading.storage.migrate import run_migrations


class InvariantChecksTest(unittest.TestCase):
    def test_clean_migrated_database_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            report = assert_database_invariants(db_path)

            self.assertTrue(report.ok)
            self.assertEqual(report.violations, [])

    def test_forbidden_raw_column_fails_with_clear_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("ALTER TABLE raw_events ADD COLUMN bull_prob REAL")

            report = check_database(db_path)

            self.assertFalse(report.ok)
            self.assertIn("raw_events_forbidden_columns", self._codes(report))

    def test_live_model_trade_fails_with_clear_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                account_id = self._insert_account(conn, "live-main", "live")
                conn.execute(
                    """
                    INSERT INTO trades (account_id, ts_code, name, side, source)
                    VALUES (?, '000001.SZ', 'PGC Candidate', 'buy', 'model')
                    """,
                    (account_id,),
                )

                report = check_connection(conn, db_path=db_path)

            self.assertFalse(report.ok)
            self.assertIn("live_trade_model_source", self._codes(report))

    def test_position_entry_trade_account_mismatch_fails_with_clear_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                trade_account_id = self._insert_account(conn, "paper-main", "paper")
                position_account_id = self._insert_account(conn, "paper-alt", "paper")
                trade_id = self._insert_trade(conn, trade_account_id)
                conn.execute(
                    """
                    INSERT INTO positions
                      (account_id, entry_trade_id, ts_code, name, buy_date, buy_price, shares, cost)
                    VALUES
                      (?, ?, '000001.SZ', 'PGC Candidate', '20260505', 10.50, 100, 1050.00)
                    """,
                    (position_account_id, trade_id),
                )

                report = check_connection(conn, db_path=db_path)

            self.assertFalse(report.ok)
            self.assertIn("position_entry_trade_account_mismatch", self._codes(report))

    def test_executed_trade_amount_mismatch_fails_with_clear_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                account_id = self._insert_account(conn, "paper-main", "paper")
                conn.execute(
                    """
                    INSERT INTO trades
                      (account_id, ts_code, name, side, executed_date, executed_price, amount, shares, source, status)
                    VALUES
                      (?, '000001.SZ', 'PGC Candidate', 'buy', '20260505', 10.50, 999.00, 100, 'manual', 'executed')
                    """,
                    (account_id,),
                )

                report = check_connection(conn, db_path=db_path)

            self.assertFalse(report.ok)
            self.assertIn("TRADE_AMOUNT_MISMATCH", self._codes(report))

    def test_position_entry_trade_must_be_executed_buy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                account_id = self._insert_account(conn, "paper-main", "paper")
                trade_id = self._insert_trade(conn, account_id, side="sell")
                conn.execute(
                    """
                    INSERT INTO positions
                      (account_id, entry_trade_id, ts_code, name, buy_date, buy_price, shares, cost)
                    VALUES
                      (?, ?, '000001.SZ', 'PGC Candidate', '20260505', 10.50, 100, 1050.00)
                    """,
                    (account_id, trade_id),
                )

                report = check_connection(conn, db_path=db_path)

            self.assertFalse(report.ok)
            self.assertIn("POSITION_ENTRY_TRADE_MISMATCH", self._codes(report))

    def test_position_entry_facts_must_match_trade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                account_id = self._insert_account(conn, "paper-main", "paper")
                trade_id = self._insert_trade(conn, account_id, amount=1050.0, shares=100)
                conn.execute(
                    """
                    INSERT INTO positions
                      (account_id, entry_trade_id, ts_code, name, buy_date, buy_price, shares, cost)
                    VALUES
                      (?, ?, '000001.SZ', 'PGC Candidate', '20260505', 9.50, 200, 1900.00)
                    """,
                    (account_id, trade_id),
                )

                report = check_connection(conn, db_path=db_path)

            self.assertFalse(report.ok)
            self.assertIn("POSITION_ENTRY_TRADE_FACT_MISMATCH", self._codes(report))

    def test_executed_buy_plan_and_stale_active_plan_fail_with_clear_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                account_id = self._insert_account(conn, "paper-main", "paper")
                plan_id = self._insert_buy_plan(conn, account_id, status="active")
                self._insert_trade(
                    conn,
                    account_id,
                    trade_plan_id=plan_id,
                    amount=1050.0,
                    shares=100,
                )

                report = check_connection(conn, db_path=db_path)

            self.assertFalse(report.ok)
            self.assertIn("TRADE_PLAN_NOT_EXECUTED_FOR_BUY", self._codes(report))
            self.assertIn("ACTIVE_BUY_PLAN_WITH_EXECUTED_TRADE", self._codes(report))

    def test_latest_equity_snapshot_mismatches_fail_with_clear_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                account_id = self._insert_account(conn, "paper-main", "paper")
                trade_id = self._insert_trade(conn, account_id, amount=1050.0, shares=100)
                conn.execute(
                    """
                    INSERT INTO positions
                      (account_id, entry_trade_id, ts_code, name, buy_date, buy_price, shares, cost, status)
                    VALUES
                      (?, ?, '000001.SZ', 'PGC Candidate', '20260505', 10.50, 100, 1050.00, 'waiting_t2')
                    """,
                    (account_id, trade_id),
                )
                conn.execute(
                    """
                    INSERT INTO equity_snapshots
                      (account_id, as_of_date, cash, market_value, total_equity)
                    VALUES
                      (?, '20260505', 198950.00, 1000.00, 199900.00)
                    """,
                    (account_id,),
                )

                report = check_connection(conn, db_path=db_path)

            self.assertFalse(report.ok)
            self.assertIn("EQUITY_SNAPSHOT_TOTAL_MISMATCH", self._codes(report))
            self.assertIn("EQUITY_SNAPSHOT_MARKET_VALUE_MISMATCH", self._codes(report))

    def test_broken_foreign_key_fails_with_clear_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = OFF")
                conn.execute(
                    """
                    INSERT INTO trades (account_id, ts_code, name, side, source)
                    VALUES (999, '000001.SZ', 'PGC Candidate', 'buy', 'manual')
                    """
                )
                conn.commit()

                report = check_connection(conn, db_path=db_path)

            self.assertFalse(report.ok)
            self.assertIn("foreign_key_violation", self._codes(report))

    def test_account_scoped_trade_index_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("DROP INDEX idx_trades_account_date")
                report = check_connection(conn, db_path=db_path)

            self.assertFalse(report.ok)
            self.assertIn("trades_account_id_index_missing", self._codes(report))

    def test_assert_database_invariants_raises_with_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("ALTER TABLE strategy_signals ADD COLUMN agent_action TEXT")

            with self.assertRaises(InvariantCheckError) as raised:
                assert_database_invariants(db_path)

            self.assertIn("strategy_signals_forbidden_columns", self._codes(raised.exception.report))

    def _insert_account(self, conn: sqlite3.Connection, account_key: str, account_type: str) -> int:
        cursor = conn.execute(
            """
            INSERT INTO portfolio_accounts
              (account_key, name, account_type, initial_cash, max_positions, position_sizing)
            VALUES
              (?, 'PGC account', ?, 200000, 3, 'equal_slots')
            """,
            (account_key, account_type),
        )
        return int(cursor.lastrowid)

    def _insert_buy_plan(self, conn: sqlite3.Connection, account_id: int, *, status: str) -> int:
        cursor = conn.execute(
            """
            INSERT INTO trade_plans
              (account_id, as_of_date, planned_trade_date, action, plan_json, status)
            VALUES
              (?, '20260504', '20260505', 'buy_next_open', '{}', ?)
            """,
            (account_id, status),
        )
        return int(cursor.lastrowid)

    def _insert_trade(
        self,
        conn: sqlite3.Connection,
        account_id: int,
        *,
        side: str = "buy",
        trade_plan_id: int | None = None,
        amount: float = 1050.0,
        shares: int = 100,
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO trades
              (account_id, trade_plan_id, ts_code, name, side, executed_date, executed_price, amount, shares, source, status)
            VALUES
              (?, ?, '000001.SZ', 'PGC Candidate', ?, '20260505', 10.50, ?, ?, 'manual', 'executed')
            """,
            (account_id, trade_plan_id, side, amount, shares),
        )
        return int(cursor.lastrowid)

    def _codes(self, report) -> set[str]:
        return {violation.code for violation in report.violations}


if __name__ == "__main__":
    unittest.main()
