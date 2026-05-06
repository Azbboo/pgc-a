from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.storage.migrate import run_migrations


class StrategySchemaMigrationsTest(unittest.TestCase):
    def test_empty_database_migrates_through_strategy_feature_signal_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            result = run_migrations(db_path)

            self.assertIn("005_strategy_governance", result.applied)
            self.assertIn("006_feature_signal", result.applied)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }

                self.assertIn("strategy_families", tables)
                self.assertIn("strategy_versions", tables)
                self.assertIn("parameter_sets", tables)
                self.assertIn("strategy_deployments", tables)
                self.assertIn("feature_runs", tables)
                self.assertIn("feature_snapshots", tables)
                self.assertIn("strategy_runs", tables)
                self.assertIn("strategy_signals", tables)
                self.assertIn("daily_picks", tables)
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_strategy_governance_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")

                family_id = self._insert_strategy_family(conn, "contracting_pullback")
                version_id = self._insert_strategy_version(conn, family_id)

                agent_policy = conn.execute(
                    "SELECT agent_policy FROM strategy_versions WHERE id = ?",
                    (version_id,),
                ).fetchone()[0]
                self.assertEqual(agent_policy, "advisory")

                with self.assertRaises(sqlite3.IntegrityError):
                    self._insert_strategy_version(conn, family_id)

                conn.execute(
                    """
                    INSERT INTO parameter_sets (strategy_version_id, params_json, params_hash)
                    VALUES (?, '{"variant_id":"cpb_6157"}', 'params-hash')
                    """,
                    (version_id,),
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        """
                        INSERT INTO parameter_sets
                          (strategy_version_id, params_json, params_hash)
                        VALUES
                          (?, '{"variant_id":"cpb_6157"}', 'params-hash')
                        """,
                        (version_id,),
                    )

                account_id = self._insert_account(conn, "paper-main")
                conn.execute(
                    """
                    INSERT INTO strategy_deployments
                      (strategy_version_id, account_id, deployment_type, start_date)
                    VALUES
                      (?, ?, 'paper', '20260504')
                    """,
                    (version_id, account_id),
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        """
                        INSERT INTO strategy_deployments
                          (strategy_version_id, account_id, deployment_type, start_date)
                        VALUES
                          (?, ?, 'paper', '20260504')
                        """,
                        (version_id, account_id),
                    )

                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_feature_signal_lineage_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")

                family_id = self._insert_strategy_family(conn, "contracting_pullback")
                version_id = self._insert_strategy_version(conn, family_id)
                raw_event_id = self._insert_raw_event(conn)
                feature_run_id = self._insert_feature_run(conn)
                feature_snapshot_id = self._insert_feature_snapshot(
                    conn,
                    feature_run_id=feature_run_id,
                    raw_event_id=raw_event_id,
                )

                with self.assertRaises(sqlite3.IntegrityError):
                    self._insert_feature_snapshot(
                        conn,
                        feature_run_id=feature_run_id,
                        raw_event_id=999,
                    )

                strategy_run_id = self._insert_strategy_run(
                    conn,
                    strategy_version_id=version_id,
                    feature_run_id=feature_run_id,
                )
                signal_id = self._insert_strategy_signal(
                    conn,
                    strategy_run_id=strategy_run_id,
                    feature_snapshot_id=feature_snapshot_id,
                    raw_event_id=raw_event_id,
                    rank=1,
                )

                with self.assertRaises(sqlite3.IntegrityError):
                    self._insert_strategy_signal(
                        conn,
                        strategy_run_id=999,
                        feature_snapshot_id=feature_snapshot_id,
                        raw_event_id=raw_event_id,
                        rank=2,
                    )

                conn.execute(
                    """
                    INSERT INTO daily_picks
                      (strategy_run_id, signal_id, review_date, planned_buy_date, score, selection_reason)
                    VALUES
                      (?, ?, '20260504', '20260505', 91.0, 'highest score')
                    """,
                    (strategy_run_id, signal_id),
                )
                second_signal_id = self._insert_strategy_signal(
                    conn,
                    strategy_run_id=strategy_run_id,
                    feature_snapshot_id=feature_snapshot_id,
                    raw_event_id=raw_event_id,
                    rank=2,
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        """
                        INSERT INTO daily_picks
                          (strategy_run_id, signal_id, review_date, planned_buy_date, score, selection_reason)
                        VALUES
                          (?, ?, '20260504', '20260505', 89.0, 'duplicate daily pick')
                        """,
                        (strategy_run_id, second_signal_id),
                    )

                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_strategy_signals_exclude_agent_and_trade_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                columns = self._columns(conn, "strategy_signals")
                forbidden_columns = {
                    "account_id",
                    "agent_action",
                    "agent_decision_id",
                    "agent_run_id",
                    "order_id",
                    "position_id",
                    "trade_id",
                    "trade_plan_id",
                }
                self.assertFalse(columns & forbidden_columns)

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

    def _insert_strategy_family(self, conn: sqlite3.Connection, family_key: str) -> int:
        cursor = conn.execute(
            """
            INSERT INTO strategy_families (family_key, name, description, owner)
            VALUES (?, 'Contracting Pullback', 'PGC contraction pullback strategy', 'research')
            """,
            (family_key,),
        )
        return int(cursor.lastrowid)

    def _insert_strategy_version(
        self,
        conn: sqlite3.Connection,
        strategy_family_id: int,
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO strategy_versions
              (strategy_family_id, strategy_key, strategy_version, params_hash)
            VALUES
              (?, 'cpb_6157', 'cpb_6157@2026-05-03', 'params-hash')
            """,
            (strategy_family_id,),
        )
        return int(cursor.lastrowid)

    def _insert_raw_event(self, conn: sqlite3.Connection) -> int:
        cursor = conn.execute(
            """
            INSERT INTO raw_events
              (ts_code, code, name, entry_date, entry_time, entry_price)
            VALUES
              ('000001.SZ', '000001', 'PGC Candidate', '20260504', '09:45:00', 10.25)
            """
        )
        return int(cursor.lastrowid)

    def _insert_feature_run(self, conn: sqlite3.Connection) -> int:
        cursor = conn.execute(
            """
            INSERT INTO feature_runs (feature_version, as_of_date)
            VALUES ('contracting_pullback.v1', '20260504')
            """
        )
        return int(cursor.lastrowid)

    def _insert_feature_snapshot(
        self,
        conn: sqlite3.Connection,
        feature_run_id: int,
        raw_event_id: int,
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO feature_snapshots
              (feature_run_id, raw_event_id, ts_code, review_date, feature_version, features_json, input_hash)
            VALUES
              (?, ?, '000001.SZ', '20260504', 'contracting_pullback.v1', '{}', ?)
            """,
            (feature_run_id, raw_event_id, f"feature-input-{raw_event_id}"),
        )
        return int(cursor.lastrowid)

    def _insert_strategy_run(
        self,
        conn: sqlite3.Connection,
        strategy_version_id: int,
        feature_run_id: int,
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO strategy_runs
              (strategy_version_id, strategy_key, strategy_version, as_of_date, params_json, params_hash, feature_run_id)
            VALUES
              (?, 'cpb_6157', 'cpb_6157@2026-05-03', '20260504', '{}', 'params-hash', ?)
            """,
            (strategy_version_id, feature_run_id),
        )
        return int(cursor.lastrowid)

    def _insert_strategy_signal(
        self,
        conn: sqlite3.Connection,
        strategy_run_id: int,
        feature_snapshot_id: int,
        raw_event_id: int,
        rank: int,
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO strategy_signals
              (strategy_run_id, feature_snapshot_id, raw_event_id, ts_code, name, review_date, planned_buy_date, score, signal_rank, features_json)
            VALUES
              (?, ?, ?, '000001.SZ', 'PGC Candidate', '20260504', '20260505', ?, ?, '{}')
            """,
            (strategy_run_id, feature_snapshot_id, raw_event_id, 100.0 - rank, rank),
        )
        return int(cursor.lastrowid)


if __name__ == "__main__":
    unittest.main()
