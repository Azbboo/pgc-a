from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.storage.migrate import run_migrations


class MarketReviewSchemaMigrationTest(unittest.TestCase):
    def test_empty_database_migrates_market_review_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            result = run_migrations(db_path)

            self.assertIn("012_market_review", result.applied)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                tables = self._objects(conn, "table")

                for table_name in (
                    "market_review_runs",
                    "market_regime_snapshots",
                    "sector_daily_snapshots",
                    "sector_constituents",
                    "market_external_items",
                    "market_plan_contexts",
                    "strategy_hypotheses",
                ):
                    self.assertIn(table_name, tables)

                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_market_review_table_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")

                self.assertEqual(
                    self._required_columns(conn, "market_review_runs"),
                    {
                        "as_of_date",
                        "status",
                        "provider_manifest_json",
                        "coverage_json",
                        "summary_json",
                        "created_at",
                    },
                )
                self.assertEqual(
                    self._required_columns(conn, "market_regime_snapshots"),
                    {"market_review_run_id", "as_of_date", "regime", "summary", "metrics_json"},
                )
                self.assertEqual(
                    self._required_columns(conn, "sector_daily_snapshots"),
                    {
                        "market_review_run_id",
                        "as_of_date",
                        "sector_code",
                        "sector_name",
                        "provider",
                        "leader_count",
                        "metrics_json",
                    },
                )
                self.assertEqual(
                    self._required_columns(conn, "sector_constituents"),
                    {"market_review_run_id", "sector_code", "sector_name", "ts_code", "role", "metrics_json"},
                )
                self.assertEqual(
                    self._required_columns(conn, "market_external_items"),
                    {
                        "as_of_date",
                        "scope_type",
                        "scope_key",
                        "item_type",
                        "provider",
                        "title",
                        "summary",
                        "sentiment",
                        "importance",
                        "published_date",
                        "metadata_json",
                        "source_hash",
                        "created_at",
                    },
                )
                self.assertEqual(
                    self._required_columns(conn, "market_plan_contexts"),
                    {
                        "market_review_run_id",
                        "trade_plan_id",
                        "alignment",
                        "risk_level",
                        "management_action",
                        "rationale",
                        "evidence_json",
                        "created_at",
                    },
                )
                self.assertEqual(
                    self._required_columns(conn, "strategy_hypotheses"),
                    {
                        "as_of_date",
                        "hypothesis_type",
                        "title",
                        "rationale",
                        "evidence_json",
                        "proposed_change_json",
                        "status",
                        "created_at",
                    },
                )

                self._assert_foreign_key(conn, "market_regime_snapshots", "market_review_runs")
                self._assert_foreign_key(conn, "sector_daily_snapshots", "market_review_runs")
                self._assert_foreign_key(conn, "sector_constituents", "market_review_runs")
                self._assert_foreign_key(conn, "market_plan_contexts", "market_review_runs")
                self._assert_foreign_key(conn, "market_plan_contexts", "trade_plans")

    def test_market_review_constraints_and_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                run_id = self._insert_market_review_run(conn)

                with self.assertRaises(sqlite3.IntegrityError):
                    self._insert_market_review_run(conn)

                conn.execute(
                    """
                    INSERT INTO market_regime_snapshots
                      (market_review_run_id, as_of_date, regime, summary)
                    VALUES
                      (?, '20260508', 'neutral', 'Market is balanced.')
                    """,
                    (run_id,),
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        """
                        INSERT INTO market_regime_snapshots
                          (market_review_run_id, as_of_date, regime, summary)
                        VALUES
                          (?, '20260508', 'euphoric', 'Invalid regime.')
                        """,
                        (run_id,),
                    )

                conn.execute(
                    """
                    INSERT INTO sector_daily_snapshots
                      (market_review_run_id, as_of_date, sector_code, sector_name, provider)
                    VALUES
                      (?, '20260508', 'BK001', 'Semiconductors', 'manual')
                    """,
                    (run_id,),
                )
                conn.execute(
                    """
                    INSERT INTO sector_constituents
                      (market_review_run_id, sector_code, sector_name, ts_code)
                    VALUES
                      (?, 'BK001', 'Semiconductors', '000001.SZ')
                    """,
                    (run_id,),
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        """
                        INSERT INTO sector_constituents
                          (market_review_run_id, sector_code, sector_name, ts_code, role)
                        VALUES
                          (?, 'BK001', 'Semiconductors', '000002.SZ', 'champion')
                        """,
                        (run_id,),
                    )

                conn.execute(
                    """
                    INSERT INTO market_external_items
                      (
                        as_of_date,
                        scope_type,
                        scope_key,
                        item_type,
                        provider,
                        title,
                        summary,
                        published_date,
                        source_hash
                      )
                    VALUES
                      (
                        '20260508',
                        'sector',
                        'BK001',
                        'news',
                        'manual',
                        'Sector news',
                        'Policy support continued.',
                        '20260508',
                        'manual:sector:bk001:20260508'
                      )
                    """
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        """
                        INSERT INTO market_external_items
                          (as_of_date, scope_type, scope_key, item_type, provider, title, summary, published_date, source_hash)
                        VALUES
                          ('20260508', 'sector', 'BK001', 'rumor', 'manual', 'Invalid item', 'Bad type.', '20260508', 'manual:bad-type')
                        """
                    )

                expected_indexes = {
                    "idx_market_review_runs_as_of_date",
                    "idx_market_regime_snapshots_date",
                    "idx_sector_daily_snapshots_date_rank",
                    "idx_sector_daily_snapshots_sector",
                    "idx_sector_constituents_stock",
                    "idx_sector_constituents_sector_rank",
                    "idx_market_external_items_date_scope",
                    "idx_market_external_items_stock_date",
                    "idx_market_plan_contexts_plan",
                    "idx_strategy_hypotheses_date_status",
                }
                indexes = self._all_indexes(conn)
                self.assertTrue(expected_indexes <= indexes)
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def _objects(self, conn: sqlite3.Connection, object_type: str) -> set[str]:
        return {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = ?",
                (object_type,),
            ).fetchall()
        }

    def _required_columns(self, conn: sqlite3.Connection, table_name: str) -> set[str]:
        return {
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            if row[3]
        }

    def _assert_foreign_key(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        referenced_table: str,
    ) -> None:
        referenced_tables = {
            row[2]
            for row in conn.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
        }
        self.assertIn(referenced_table, referenced_tables)

    def _all_indexes(self, conn: sqlite3.Connection) -> set[str]:
        return {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
            if row[0]
        }

    def _insert_market_review_run(self, conn: sqlite3.Connection) -> int:
        cursor = conn.execute(
            """
            INSERT INTO market_review_runs
              (as_of_date, status)
            VALUES
              ('20260508', 'started')
            """
        )
        return int(cursor.lastrowid)


if __name__ == "__main__":
    unittest.main()
