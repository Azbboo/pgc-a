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

    def _insert_trade(self, conn: sqlite3.Connection, account_id: int) -> int:
        cursor = conn.execute(
            """
            INSERT INTO trades
              (account_id, ts_code, name, side, executed_date, executed_price, source, status)
            VALUES
              (?, '000001.SZ', 'PGC Candidate', 'buy', '20260505', 10.50, 'manual', 'executed')
            """,
            (account_id,),
        )
        return int(cursor.lastrowid)

    def _codes(self, report) -> set[str]:
        return {violation.code for violation in report.violations}


if __name__ == "__main__":
    unittest.main()
