from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.cli.main import main
from pgc_trading.services.common import RequestContext
from pgc_trading.services.execution_recording_service import (
    ExecutionRecordingService,
    RecordTradeRequest,
)
from pgc_trading.services.portfolio_planning_service import (
    GenerateBuyPlanRequest,
    PortfolioPlanningService,
)
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data


ACCOUNT_KEY = "paper-200k"
AS_OF_DATE = "20260504"
BUY_DATE = "20260505"
T2_DATE = "20260507"
T5_DATE = "20260512"


class CliPositionDecisionsTest(unittest.TestCase):
    def test_positions_lists_open_position_with_explicit_calendar_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            plan_id = self._ready_buy_plan(db_path)
            position_id = self._record_buy(db_path, plan_id)
            with sqlite3.connect(db_path) as conn:
                self._insert_market_bar(conn, T2_DATE, close=10.4)

            stdout = io.StringIO()
            code = main(
                [
                    "positions",
                    "--date",
                    "2026-05-07",
                    "--account",
                    ACCOUNT_KEY,
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
            )

            output = stdout.getvalue()
            self.assertEqual(code, 0, output)
            self.assertIn("positions as of 2026-05-07", output)
            self.assertIn(f"position_id={position_id}", output)
            self.assertIn(f"account={ACCOUNT_KEY}", output)
            self.assertIn("buy_date=2026-05-05", output)
            self.assertIn("planned_t2_date=2026-05-07", output)
            self.assertIn("planned_t5_date=2026-05-12", output)
            self.assertIn("due_stage=t2", output)
            self.assertIn("latest_close=10.40 on 2026-05-07", output)
            self.assertIn("unrealized_ret=4.00%", output)

    def test_exits_evaluate_generates_traceable_sell_plan_without_sell_trade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            plan_id = self._ready_buy_plan(db_path)
            position_id = self._record_buy(db_path, plan_id)
            with sqlite3.connect(db_path) as conn:
                self._insert_market_bar(conn, T2_DATE, close=10.4)
                account_id = int(
                    conn.execute(
                        "SELECT id FROM portfolio_accounts WHERE account_key = ?",
                        (ACCOUNT_KEY,),
                    ).fetchone()[0]
                )

            stdout = io.StringIO()
            code = main(
                [
                    "exits-evaluate",
                    "--date",
                    "2026-05-07",
                    "--account",
                    ACCOUNT_KEY,
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
            )

            output = stdout.getvalue()
            self.assertEqual(code, 0, output)
            self.assertIn("service returned success", output)
            self.assertIn("exit decisions:", output)
            self.assertIn(f"position_id={position_id}", output)
            self.assertIn(f"account_id={account_id}", output)
            self.assertIn(f"account={ACCOUNT_KEY}", output)
            self.assertIn("decision_date=2026-05-07", output)
            self.assertIn("planned_t2_date=2026-05-07", output)
            self.assertIn("planned_t5_date=2026-05-12", output)
            self.assertIn("planned_exit_date=2026-05-08", output)
            self.assertIn("decision=take_profit", output)
            self.assertIn("generated_trade_plan_id=", output)
            self.assertIn("sell trades recorded by this command: 0", output)

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "exit_decisions"), 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM trades WHERE side = 'sell'").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT status FROM positions WHERE id = ?", (position_id,)).fetchone()[0], "planned_exit")

                exit_decision = conn.execute(
                    """
                    SELECT id, position_id, account_id, decision, generated_trade_plan_id
                    FROM exit_decisions
                    """
                ).fetchone()
                self.assertEqual(exit_decision[1:4], (position_id, account_id, "take_profit"))
                self.assertIsNotNone(exit_decision[4])

                sell_plan = conn.execute(
                    """
                    SELECT id, account_id, action, status, plan_json
                    FROM trade_plans
                    WHERE action = 'sell_t2_take_profit'
                    """
                ).fetchone()
                self.assertEqual(sell_plan[0], exit_decision[4])
                self.assertEqual(sell_plan[1], account_id)
                self.assertEqual(sell_plan[2:4], ("sell_t2_take_profit", "active"))
                plan_json = json.loads(sell_plan[4])
                self.assertEqual(plan_json["position_id"], position_id)
                self.assertEqual(plan_json["exit_decision_id"], exit_decision[0])

                trade_sides = conn.execute("SELECT side FROM trades ORDER BY id").fetchall()
                self.assertEqual(trade_sides, [("buy",)])

    def _migrated_seeded_db(self, tmp: str) -> Path:
        db_path = Path(tmp) / "pgc.db"
        run_migrations(db_path)
        seed_reference_data(db_path)
        return db_path

    def _ready_buy_plan(self, db_path: Path) -> int:
        with sqlite3.connect(db_path) as conn:
            self._insert_calendar(conn)
            self._insert_daily_pick(conn)
        result = PortfolioPlanningService(db_path).generate_buy_plan(
            GenerateBuyPlanRequest(account_key=ACCOUNT_KEY, review_date=AS_OF_DATE),
            RequestContext(request_id="req-plan-cli-exits", operator="tester"),
        )
        self.assertEqual(result.status, "success")
        self.assertIsNotNone(result.data.trade_plan_id)
        return int(result.data.trade_plan_id)

    def _record_buy(self, db_path: Path, plan_id: int) -> int:
        result = ExecutionRecordingService(db_path).record_trade(
            RecordTradeRequest(
                account_key=ACCOUNT_KEY,
                trade_plan_id=plan_id,
                side="buy",
                executed_date=BUY_DATE,
                executed_price=10.0,
                shares=1000,
                source="paper_model",
            ),
            RequestContext(request_id=f"req-buy-cli-exits-{plan_id}", operator="tester"),
        )
        self.assertEqual(result.status, "success")
        self.assertIsNotNone(result.data.position_id)
        return int(result.data.position_id)

    def _insert_calendar(self, conn: sqlite3.Connection) -> None:
        conn.executemany(
            """
            INSERT OR REPLACE INTO trade_calendar
              (exchange, cal_date, is_open, pretrade_date)
            VALUES
              ('SSE', ?, ?, ?)
            """,
            [
                (AS_OF_DATE, 1, "20260501"),
                (BUY_DATE, 1, AS_OF_DATE),
                ("20260506", 1, BUY_DATE),
                (T2_DATE, 1, "20260506"),
                ("20260508", 1, T2_DATE),
                ("20260509", 0, "20260508"),
                ("20260510", 0, "20260508"),
                ("20260511", 1, "20260508"),
                (T5_DATE, 1, "20260511"),
                ("20260513", 1, T5_DATE),
            ],
        )

    def _insert_daily_pick(self, conn: sqlite3.Connection) -> int:
        strategy_version = conn.execute(
            """
            SELECT id, strategy_key, strategy_version, params_hash
            FROM strategy_versions
            WHERE strategy_version = 'cpb_6157@2026-05-03'
            """
        ).fetchone()
        raw_event = conn.execute(
            """
            INSERT INTO raw_events
              (ts_code, code, name, entry_date, entry_time, entry_price)
            VALUES
              ('000001.SZ', '000001', 'PGC Candidate', '20260427', '15:00', 10.0)
            """
        )
        feature_run = conn.execute(
            """
            INSERT INTO feature_runs (feature_version, as_of_date)
            VALUES ('contracting_pullback.v1', ?)
            """,
            (AS_OF_DATE,),
        )
        feature_snapshot = conn.execute(
            """
            INSERT INTO feature_snapshots
              (feature_run_id, raw_event_id, ts_code, review_date, feature_version, features_json, input_hash)
            VALUES
              (?, ?, '000001.SZ', ?, 'contracting_pullback.v1', '{}', 'cli-exit-test-hash')
            """,
            (int(feature_run.lastrowid), int(raw_event.lastrowid), AS_OF_DATE),
        )
        strategy_run = conn.execute(
            """
            INSERT INTO strategy_runs
              (strategy_version_id, strategy_key, strategy_version, as_of_date, params_json, params_hash, feature_run_id)
            VALUES
              (?, ?, ?, ?, '{}', ?, ?)
            """,
            (
                int(strategy_version[0]),
                strategy_version[1],
                strategy_version[2],
                AS_OF_DATE,
                strategy_version[3],
                int(feature_run.lastrowid),
            ),
        )
        signal = conn.execute(
            """
            INSERT INTO strategy_signals
              (strategy_run_id, feature_snapshot_id, raw_event_id, ts_code, name, review_date, planned_buy_date, score, signal_rank, signal_status, features_json)
            VALUES
              (?, ?, ?, '000001.SZ', 'PGC Candidate', ?, ?, 91.0, 1, 'daily_pick', '{}')
            """,
            (
                int(strategy_run.lastrowid),
                int(feature_snapshot.lastrowid),
                int(raw_event.lastrowid),
                AS_OF_DATE,
                BUY_DATE,
            ),
        )
        daily_pick = conn.execute(
            """
            INSERT INTO daily_picks
              (strategy_run_id, signal_id, review_date, planned_buy_date, score, selection_reason)
            VALUES
              (?, ?, ?, ?, 91.0, 'highest score')
            """,
            (int(strategy_run.lastrowid), int(signal.lastrowid), AS_OF_DATE, BUY_DATE),
        )
        self._insert_market_bar(conn, AS_OF_DATE, close=10.0)
        return int(daily_pick.lastrowid)

    def _insert_market_bar(self, conn: sqlite3.Connection, trade_date: str, close: float) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO market_bars
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
              ('000001.SZ', ?, ?, ?, ?, ?, 100000, 1000000, ?, ?, ?, ?)
            """,
            (trade_date, close, close, close, close, close, close, close, close),
        )

    def _count(self, conn: sqlite3.Connection, table: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
