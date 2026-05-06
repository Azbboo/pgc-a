from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.storage.migrate import run_migrations


class BaseSchemaMigrationsTest(unittest.TestCase):
    def test_empty_database_migrates_through_base_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            result = run_migrations(db_path)

            self.assertIn("002_raw_market", result.applied)
            self.assertIn("003_accounts", result.applied)
            self.assertIn("004_meta", result.applied)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }

                self.assertIn("raw_import_batches", tables)
                self.assertIn("raw_events", tables)
                self.assertIn("market_fetch_runs", tables)
                self.assertIn("trade_calendar", tables)
                self.assertIn("market_bars", tables)
                self.assertIn("daily_basic_snapshots", tables)
                self.assertIn("portfolio_accounts", tables)
                self.assertIn("operation_requests", tables)
                self.assertIn("domain_events", tables)
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_base_schema_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")

                raw_columns = self._columns(conn, "raw_events")
                self.assertIn("import_batch_id", raw_columns)
                self.assertIn("is_valid", raw_columns)
                self.assertIn("invalid_reason", raw_columns)

                market_columns = self._columns(conn, "market_bars")
                self.assertIn("fetch_run_id", market_columns)
                self.assertIn("vol", market_columns)
                self.assertIn("provider", market_columns)

                account_id = self._insert_account(conn, account_key="paper-main")
                with self.assertRaises(sqlite3.IntegrityError):
                    self._insert_account(conn, account_key="paper-main")

                conn.execute(
                    """
                    INSERT INTO operation_requests
                      (idempotency_key, operation_type, account_id, request_json)
                    VALUES
                      ('review:paper-main:20260504', 'daily_review', ?, '{}')
                    """,
                    (account_id,),
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        """
                        INSERT INTO operation_requests
                          (idempotency_key, operation_type, account_id, request_json)
                        VALUES
                          ('review:paper-main:20260504', 'daily_review', ?, '{}')
                        """,
                        (account_id,),
                    )

                conn.execute(
                    """
                    INSERT INTO domain_events
                      (event_type, entity_type, entity_id, account_id, payload_json)
                    VALUES
                      ('account_created', 'portfolio_account', ?, ?, '{}')
                    """,
                    (account_id, account_id),
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        """
                        INSERT INTO domain_events
                          (event_type, entity_type, entity_id, account_id, payload_json)
                        VALUES
                          ('account_created', 'portfolio_account', 999, 999, '{}')
                        """
                    )

                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def _columns(self, conn: sqlite3.Connection, table_name: str) -> set[str]:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}

    def _insert_account(self, conn: sqlite3.Connection, account_key: str) -> int:
        cursor = conn.execute(
            """
            INSERT INTO portfolio_accounts
              (account_key, name, account_type, initial_cash, max_positions, position_sizing)
            VALUES
              (?, 'PGC paper account', 'paper', 200000, 3, 'equal_slots')
            """,
            (account_key,),
        )
        return int(cursor.lastrowid)


if __name__ == "__main__":
    unittest.main()
