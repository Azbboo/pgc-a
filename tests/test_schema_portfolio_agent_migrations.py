from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.storage.migrate import run_migrations


class PortfolioAgentSchemaMigrationsTest(unittest.TestCase):
    def test_empty_database_migrates_through_agent_portfolio_research_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            result = run_migrations(db_path)

            self.assertIn("007_agent", result.applied)
            self.assertIn("008_portfolio", result.applied)
            self.assertIn("009_research_views", result.applied)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                tables = self._objects(conn, "table")
                views = self._objects(conn, "view")

                self.assertIn("input_snapshots", tables)
                self.assertIn("agent_runs", tables)
                self.assertIn("agent_artifacts", tables)
                self.assertIn("agent_decisions", tables)
                self.assertIn("trade_plans", tables)
                self.assertIn("trades", tables)
                self.assertIn("positions", tables)
                self.assertIn("exit_decisions", tables)
                self.assertIn("equity_snapshots", tables)
                self.assertIn("research_experiments", tables)
                self.assertIn("backtest_runs", tables)
                self.assertIn("backtest_trades", tables)
                self.assertIn("v_daily_review", views)
                self.assertIn("v_open_positions", views)
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_agent_advisory_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                signal_ids = self._insert_signal_chain(conn)
                input_snapshot_id = self._insert_input_snapshot(conn, signal_ids)
                agent_run_id = self._insert_agent_run(conn, signal_ids, input_snapshot_id)

                for action in ("support", "caution", "reject", "review_required", "no_opinion"):
                    local_run_id = (
                        agent_run_id
                        if action == "support"
                        else self._insert_agent_run(
                            conn,
                            signal_ids,
                            input_snapshot_id,
                            config_hash=f"agent-config-{action}",
                        )
                    )
                    conn.execute(
                        """
                        INSERT INTO agent_decisions
                          (agent_run_id, signal_id, daily_pick_id, action, confidence, raw_decision_json)
                        VALUES
                          (?, ?, ?, ?, 0.5, '{}')
                        """,
                        (
                            local_run_id,
                            signal_ids["signal_id"],
                            signal_ids["daily_pick_id"],
                            action,
                        ),
                    )

                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        """
                        INSERT INTO agent_decisions
                          (agent_run_id, action, raw_decision_json)
                        VALUES
                          (?, 'block_trade', '{}')
                        """,
                        (self._insert_agent_run(conn, signal_ids, input_snapshot_id, "bad-action"),),
                    )

                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        """
                        INSERT INTO agent_decisions
                          (agent_run_id, action, confidence, raw_decision_json)
                        VALUES
                          (?, 'no_opinion', 1.5, '{}')
                        """,
                        (self._insert_agent_run(conn, signal_ids, input_snapshot_id, "bad-confidence"),),
                    )

                agent_columns = self._columns(conn, "agent_decisions")
                self.assertFalse(
                    agent_columns
                    & {"account_id", "trade_plan_id", "trade_id", "position_id", "exit_decision_id"}
                )
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_portfolio_lifecycle_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                signal_ids = self._insert_signal_chain(conn)
                input_snapshot_id = self._insert_input_snapshot(conn, signal_ids)
                agent_run_id = self._insert_agent_run(conn, signal_ids, input_snapshot_id)
                agent_decision_id = self._insert_agent_decision(conn, signal_ids, agent_run_id)
                account_id = self._insert_account(conn)
                trade_plan_id = self._insert_trade_plan(
                    conn,
                    account_id=account_id,
                    signal_ids=signal_ids,
                    agent_decision_id=agent_decision_id,
                )

                with self.assertRaises(sqlite3.IntegrityError):
                    self._insert_trade_plan(
                        conn,
                        account_id=account_id,
                        signal_ids=signal_ids,
                        agent_decision_id=agent_decision_id,
                    )

                trade_id = self._insert_trade(conn, account_id, trade_plan_id, signal_ids)
                position_id = self._insert_position(conn, account_id, trade_id, signal_ids)
                conn.execute(
                    """
                    INSERT INTO exit_decisions
                      (position_id, account_id, decision_date, decision_stage, decision, reason)
                    VALUES
                      (?, ?, '20260507', 't2', 'hold_to_t5', 'hold_middle_to_t5')
                    """,
                    (position_id, account_id),
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        """
                        INSERT INTO positions
                          (account_id, signal_id, ts_code, name, buy_date, buy_price, shares, cost)
                        VALUES
                          (?, ?, '000001.SZ', 'PGC Candidate', '20260505', 10.50, 100, 1050.00)
                        """,
                        (account_id, signal_ids["signal_id"]),
                    )

                trade_columns = self._columns(conn, "trades")
                position_columns = self._column_meta(conn, "positions")
                self.assertIn("executed_price", trade_columns)
                self.assertNotIn("price", trade_columns)
                self.assertEqual(position_columns["entry_trade_id"]["notnull"], 1)
                self.assertNotIn("exits", self._objects(conn, "table"))
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_research_tables_and_views_are_separate_from_trade_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                signal_ids = self._insert_signal_chain(conn)
                account_id = self._insert_account(conn, account_key="backtest-main", account_type="backtest")
                experiment_id = self._insert_research_experiment(
                    conn,
                    signal_ids["strategy_version_id"],
                )
                backtest_run_id = self._insert_backtest_run(
                    conn,
                    experiment_id=experiment_id,
                    strategy_version_id=signal_ids["strategy_version_id"],
                    account_id=account_id,
                )

                conn.execute(
                    """
                    INSERT INTO backtest_trades
                      (backtest_run_id, signal_id, ts_code, name, buy_date, buy_price, shares, ret)
                    VALUES
                      (?, ?, '000001.SZ', 'PGC Candidate', '20260505', 10.50, 100, 0.03)
                    """,
                    (backtest_run_id, signal_ids["signal_id"]),
                )

                self.assertIn("backtest_trades", self._objects(conn, "table"))
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM backtest_trades").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)

                daily_review = conn.execute("SELECT * FROM v_daily_review").fetchall()
                self.assertEqual(len(daily_review), 1)

                open_positions = conn.execute("SELECT * FROM v_open_positions").fetchall()
                self.assertEqual(open_positions, [])
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def _objects(self, conn: sqlite3.Connection, object_type: str) -> set[str]:
        return {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = ?",
                (object_type,),
            ).fetchall()
        }

    def _columns(self, conn: sqlite3.Connection, table_name: str) -> set[str]:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}

    def _column_meta(self, conn: sqlite3.Connection, table_name: str) -> dict[str, dict[str, int]]:
        return {
            row[1]: {"notnull": row[3]}
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }

    def _insert_account(
        self,
        conn: sqlite3.Connection,
        account_key: str = "paper-main",
        account_type: str = "paper",
    ) -> int:
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

    def _insert_signal_chain(self, conn: sqlite3.Connection) -> dict[str, int]:
        family_id = self._insert_strategy_family(conn)
        strategy_version_id = self._insert_strategy_version(conn, family_id)
        raw_event_id = self._insert_raw_event(conn)
        feature_run_id = self._insert_feature_run(conn)
        feature_snapshot_id = self._insert_feature_snapshot(conn, feature_run_id, raw_event_id)
        strategy_run_id = self._insert_strategy_run(conn, strategy_version_id, feature_run_id)
        signal_id = self._insert_strategy_signal(
            conn,
            strategy_run_id,
            feature_snapshot_id,
            raw_event_id,
        )
        daily_pick_id = self._insert_daily_pick(conn, strategy_run_id, signal_id)
        return {
            "strategy_version_id": strategy_version_id,
            "strategy_run_id": strategy_run_id,
            "signal_id": signal_id,
            "daily_pick_id": daily_pick_id,
        }

    def _insert_strategy_family(self, conn: sqlite3.Connection) -> int:
        cursor = conn.execute(
            """
            INSERT INTO strategy_families (family_key, name, description, owner)
            VALUES ('contracting_pullback', 'Contracting Pullback', 'PGC contraction pullback strategy', 'research')
            """
        )
        return int(cursor.lastrowid)

    def _insert_strategy_version(self, conn: sqlite3.Connection, strategy_family_id: int) -> int:
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
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO strategy_signals
              (strategy_run_id, feature_snapshot_id, raw_event_id, ts_code, name, review_date, planned_buy_date, score, signal_rank, features_json)
            VALUES
              (?, ?, ?, '000001.SZ', 'PGC Candidate', '20260504', '20260505', 91.0, 1, '{}')
            """,
            (strategy_run_id, feature_snapshot_id, raw_event_id),
        )
        return int(cursor.lastrowid)

    def _insert_daily_pick(
        self,
        conn: sqlite3.Connection,
        strategy_run_id: int,
        signal_id: int,
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO daily_picks
              (strategy_run_id, signal_id, review_date, planned_buy_date, score, selection_reason)
            VALUES
              (?, ?, '20260504', '20260505', 91.0, 'highest score')
            """,
            (strategy_run_id, signal_id),
        )
        return int(cursor.lastrowid)

    def _insert_input_snapshot(
        self,
        conn: sqlite3.Connection,
        signal_ids: dict[str, int],
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO input_snapshots
              (snapshot_type, as_of_date, signal_id, daily_pick_id, source_refs_json, payload_json, content_hash)
            VALUES
              ('daily_pick_review', '20260504', ?, ?, '{}', '{}', 'input-hash')
            """,
            (signal_ids["signal_id"], signal_ids["daily_pick_id"]),
        )
        return int(cursor.lastrowid)

    def _insert_agent_run(
        self,
        conn: sqlite3.Connection,
        signal_ids: dict[str, int],
        input_snapshot_id: int,
        config_hash: str = "agent-config",
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO agent_runs
              (agent_system, agent_version, signal_id, daily_pick_id, input_snapshot_id, as_of_date, config_json, config_hash)
            VALUES
              ('tradingagents', 'local-dev', ?, ?, ?, '20260504', '{}', ?)
            """,
            (
                signal_ids["signal_id"],
                signal_ids["daily_pick_id"],
                input_snapshot_id,
                config_hash,
            ),
        )
        return int(cursor.lastrowid)

    def _insert_agent_decision(
        self,
        conn: sqlite3.Connection,
        signal_ids: dict[str, int],
        agent_run_id: int,
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO agent_decisions
              (agent_run_id, signal_id, daily_pick_id, action, confidence, raw_decision_json)
            VALUES
              (?, ?, ?, 'support', 0.7, '{}')
            """,
            (agent_run_id, signal_ids["signal_id"], signal_ids["daily_pick_id"]),
        )
        return int(cursor.lastrowid)

    def _insert_trade_plan(
        self,
        conn: sqlite3.Connection,
        account_id: int,
        signal_ids: dict[str, int],
        agent_decision_id: int,
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO trade_plans
              (account_id, daily_pick_id, signal_id, agent_decision_id, as_of_date, planned_trade_date, planned_buy_date, action, plan_json, status)
            VALUES
              (?, ?, ?, ?, '20260504', '20260505', '20260505', 'buy_next_open', '{}', 'active')
            """,
            (
                account_id,
                signal_ids["daily_pick_id"],
                signal_ids["signal_id"],
                agent_decision_id,
            ),
        )
        return int(cursor.lastrowid)

    def _insert_trade(
        self,
        conn: sqlite3.Connection,
        account_id: int,
        trade_plan_id: int,
        signal_ids: dict[str, int],
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO trades
              (account_id, trade_plan_id, signal_id, ts_code, name, side, planned_date, executed_date, executed_price, amount, shares, status, source)
            VALUES
              (?, ?, ?, '000001.SZ', 'PGC Candidate', 'buy', '20260505', '20260505', 10.50, 1050.00, 100, 'executed', 'paper_model')
            """,
            (account_id, trade_plan_id, signal_ids["signal_id"]),
        )
        return int(cursor.lastrowid)

    def _insert_position(
        self,
        conn: sqlite3.Connection,
        account_id: int,
        entry_trade_id: int,
        signal_ids: dict[str, int],
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO positions
              (account_id, signal_id, entry_trade_id, ts_code, name, buy_date, buy_price, shares, cost, planned_t2_date, planned_t5_date)
            VALUES
              (?, ?, ?, '000001.SZ', 'PGC Candidate', '20260505', 10.50, 100, 1050.00, '20260507', '20260512')
            """,
            (account_id, signal_ids["signal_id"], entry_trade_id),
        )
        return int(cursor.lastrowid)

    def _insert_research_experiment(
        self,
        conn: sqlite3.Connection,
        strategy_version_id: int,
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO research_experiments
              (strategy_version_id, experiment_key, name, status)
            VALUES
              (?, 'cpb_6157_smoke', 'CPB 6157 smoke test', 'running')
            """,
            (strategy_version_id,),
        )
        return int(cursor.lastrowid)

    def _insert_backtest_run(
        self,
        conn: sqlite3.Connection,
        experiment_id: int,
        strategy_version_id: int,
        account_id: int,
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO backtest_runs
              (experiment_id, strategy_version_id, account_id, run_key, sample_type, start_date, end_date, params_hash, input_hash, metrics_json)
            VALUES
              (?, ?, ?, 'cpb_6157_full_smoke', 'full', '20260101', '20260504', 'params-hash', 'input-hash', '{}')
            """,
            (experiment_id, strategy_version_id, account_id),
        )
        return int(cursor.lastrowid)


if __name__ == "__main__":
    unittest.main()
