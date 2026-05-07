from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.execution_recording_service import (
    ExecutionRecordingService,
    RecordTradeRequest,
)
from pgc_trading.services.portfolio_planning_service import (
    GenerateBuyPlanRequest,
    ListTradePlansRequest,
    PortfolioPlanningService,
)
from pgc_trading.services.position_lifecycle_service import (
    EvaluateExitsRequest,
    PositionLifecycleService,
)
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data


ACCOUNT_KEY = "paper-main"
AS_OF_DATE = "20260504"
BUY_DATE = "20260505"
T2_DATE = "20260507"
T5_DATE = "20260512"


class PortfolioLifecycleServiceTest(unittest.TestCase):
    def test_generate_buy_plan_does_not_create_trade_or_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_calendar(conn)
                self._insert_daily_pick(conn)

            result = PortfolioPlanningService(db_path).generate_buy_plan(
                GenerateBuyPlanRequest(account_key=ACCOUNT_KEY, review_date=AS_OF_DATE),
                RequestContext(request_id="req-plan", idempotency_key="plan:buy:1", operator="tester"),
            )
            second = PortfolioPlanningService(db_path).generate_buy_plan(
                GenerateBuyPlanRequest(account_key=ACCOUNT_KEY, review_date=AS_OF_DATE),
                RequestContext(request_id="req-plan-2", operator="tester"),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.action, "buy_next_open")
            self.assertEqual(result.data.status, "active")
            self.assertEqual(result.data.planned_trade_date, BUY_DATE)
            self.assertEqual(result.data.free_position_slots, 3)
            self.assertEqual(result.data.planned_shares, 6600)
            self.assertEqual(second.data.trade_plan_id, result.data.trade_plan_id)
            self.assertTrue(second.data.idempotent)

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "trade_plans"), 1)
                self.assertEqual(self._count(conn, "trades"), 0)
                self.assertEqual(self._count(conn, "positions"), 0)
                plan = conn.execute("SELECT status, action, plan_json FROM trade_plans").fetchone()
                self.assertEqual(plan[0], "active")
                self.assertEqual(plan[1], "buy_next_open")
                self.assertEqual(json.loads(plan[2])["planned_shares"], 6600)

    def test_live_buy_plan_dry_run_previews_without_persisting_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_calendar(conn)
                self._insert_daily_pick(conn)

            result = PortfolioPlanningService(db_path).generate_buy_plan(
                GenerateBuyPlanRequest(account_key="live-main", review_date=AS_OF_DATE),
                RequestContext(request_id="req-live-plan-dry", dry_run=True, operator="tester"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNone(result.data.trade_plan_id)
            self.assertEqual(result.data.action, "buy_next_open")
            self.assertEqual(result.data.status, "active")
            self.assertEqual(result.data.planned_trade_date, BUY_DATE)
            self.assertEqual(result.data.planned_shares, 6600)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "trade_plans"), 0)
                self.assertEqual(self._count(conn, "trades"), 0)
                self.assertEqual(self._count(conn, "positions"), 0)

    def test_live_buy_plan_apply_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_calendar(conn)
                self._insert_daily_pick(conn)

            result = PortfolioPlanningService(db_path).generate_buy_plan(
                GenerateBuyPlanRequest(account_key="live-main", review_date=AS_OF_DATE),
                RequestContext(request_id="req-live-plan-apply", operator="tester"),
            )

            self.assertEqual(result.status, "validation_failed")
            self.assertEqual(result.errors[0].code, "LIVE_PLAN_APPLY_DISABLED")
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "trade_plans"), 0)
                self.assertEqual(self._count(conn, "trades"), 0)
                self.assertEqual(self._count(conn, "positions"), 0)

    def test_record_buy_trade_creates_position_with_trade_calendar_t2_t5(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            plan_id = self._ready_buy_plan(db_path)

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
                RequestContext(request_id="req-buy", idempotency_key="trade:buy:1", operator="tester"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data.trade_id)
            self.assertIsNotNone(result.data.position_id)
            self.assertEqual(result.data.position_status, "waiting_t2")
            self.assertEqual(result.data.planned_t2_date, T2_DATE)
            self.assertEqual(result.data.planned_t5_date, T5_DATE)

            with sqlite3.connect(db_path) as conn:
                position = conn.execute(
                    """
                    SELECT buy_date, buy_price, shares, planned_t2_date, planned_t5_date, status
                    FROM positions
                    """
                ).fetchone()
                self.assertEqual(position, (BUY_DATE, 10.0, 1000, T2_DATE, T5_DATE, "waiting_t2"))
                self.assertEqual(conn.execute("SELECT status FROM trade_plans").fetchone()[0], "executed")
                self.assertEqual(self._count(conn, "trades"), 1)

    def test_t2_take_profit_generates_sell_plan_and_sell_trade_closes_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            buy_plan_id = self._ready_buy_plan(db_path)
            buy = self._record_buy(db_path, buy_plan_id)
            with sqlite3.connect(db_path) as conn:
                self._insert_market_bar(conn, "000001.SZ", T2_DATE, close=10.4)

            exits = PositionLifecycleService(db_path).evaluate_exits(
                EvaluateExitsRequest(account_key=ACCOUNT_KEY, as_of_date=T2_DATE),
                RequestContext(request_id="req-exit-t2", idempotency_key="exit:t2:1", operator="tester"),
            )

            self.assertEqual(exits.status, "success")
            self.assertEqual(exits.data.evaluated_positions, 1)
            self.assertEqual(len(exits.data.exit_decision_ids), 1)
            self.assertEqual(len(exits.data.generated_trade_plan_ids), 1)

            sell_plan_id = exits.data.generated_trade_plan_ids[0]
            sell = ExecutionRecordingService(db_path).record_trade(
                RecordTradeRequest(
                    account_key=ACCOUNT_KEY,
                    trade_plan_id=sell_plan_id,
                    side="sell",
                    executed_date="20260508",
                    executed_price=10.5,
                    shares=1000,
                    source="paper_model",
                ),
                RequestContext(request_id="req-sell", idempotency_key="trade:sell:1", operator="tester"),
            )

            self.assertEqual(sell.status, "success")
            self.assertEqual(sell.data.position_id, buy.data.position_id)
            self.assertEqual(sell.data.position_status, "closed")
            with sqlite3.connect(db_path) as conn:
                decision = conn.execute(
                    """
                    SELECT decision_stage, decision, reason, generated_trade_plan_id, executed_exit_trade_id
                    FROM exit_decisions
                    """
                ).fetchone()
                self.assertEqual(decision[0:3], ("t2", "executed", "take_profit_ge3"))
                self.assertEqual(decision[3], sell_plan_id)
                self.assertEqual(decision[4], sell.data.trade_id)
                position_status = conn.execute("SELECT status FROM positions").fetchone()[0]
                self.assertEqual(position_status, "closed")
                trade_sides = conn.execute("SELECT side FROM trades ORDER BY id").fetchall()
                self.assertEqual(trade_sides, [("buy",), ("sell",)])

    def test_t2_middle_holds_until_t5_timeout_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            buy_plan_id = self._ready_buy_plan(db_path)
            self._record_buy(db_path, buy_plan_id)
            with sqlite3.connect(db_path) as conn:
                self._insert_market_bar(conn, "000001.SZ", T2_DATE, close=10.1)
                self._insert_market_bar(conn, "000001.SZ", T5_DATE, close=10.2)

            t2 = PositionLifecycleService(db_path).evaluate_exits(
                EvaluateExitsRequest(account_key=ACCOUNT_KEY, as_of_date=T2_DATE),
                RequestContext(request_id="req-hold", idempotency_key="exit:hold:1", operator="tester"),
            )
            t5 = PositionLifecycleService(db_path).evaluate_exits(
                EvaluateExitsRequest(account_key=ACCOUNT_KEY, as_of_date=T5_DATE),
                RequestContext(request_id="req-t5", idempotency_key="exit:t5:1", operator="tester"),
            )

            self.assertEqual(t2.status, "success")
            self.assertEqual(t2.data.generated_trade_plan_ids, [])
            self.assertEqual(t5.status, "success")
            self.assertEqual(len(t5.data.generated_trade_plan_ids), 1)

            with sqlite3.connect(db_path) as conn:
                decisions = conn.execute(
                    "SELECT decision_stage, decision, reason FROM exit_decisions ORDER BY id"
                ).fetchall()
                self.assertEqual(
                    decisions,
                    [
                        ("t2", "hold_to_t5", "hold_middle_to_t5"),
                        ("t5", "timeout_exit", "timeout_t5"),
                    ],
                )
                sell_plan = conn.execute(
                    "SELECT action, planned_trade_date FROM trade_plans WHERE action = 'sell_t5_timeout'"
                ).fetchone()
                self.assertEqual(sell_plan, ("sell_t5_timeout", "20260513"))

    def test_trade_recording_enforces_account_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            plan_id = self._ready_buy_plan(db_path)
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO portfolio_accounts
                      (account_key, name, account_type, initial_cash, max_positions, position_sizing)
                    VALUES
                      ('paper-other', 'Other Paper', 'paper', 100000, 3, 'equal_slots')
                    """
                )

            result = ExecutionRecordingService(db_path).record_trade(
                RecordTradeRequest(
                    account_key="paper-other",
                    trade_plan_id=plan_id,
                    side="buy",
                    executed_date=BUY_DATE,
                    executed_price=10.0,
                    shares=1000,
                    source="paper_model",
                ),
                RequestContext(request_id="req-wrong-account", operator="tester"),
            )

            self.assertEqual(result.status, "validation_failed")
            self.assertEqual(result.errors[0].code, "ACCOUNT_MISMATCH")
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "trades"), 0)
                self.assertEqual(self._count(conn, "positions"), 0)

    def test_list_trade_plans_is_read_only_and_account_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            plan_id = self._ready_buy_plan(db_path)
            with sqlite3.connect(db_path) as conn:
                other = conn.execute(
                    """
                    INSERT INTO portfolio_accounts
                      (account_key, name, account_type, initial_cash, max_positions, position_sizing)
                    VALUES
                      ('paper-other', 'Other Paper', 'paper', 100000, 3, 'equal_slots')
                    """
                )
                conn.execute(
                    """
                    INSERT INTO trade_plans
                      (account_id, as_of_date, planned_trade_date, planned_buy_date, action, reason, plan_json, status)
                    VALUES
                      (?, ?, ?, ?, 'buy_next_open', 'other account plan', '{}', 'active')
                    """,
                    (int(other.lastrowid), AS_OF_DATE, BUY_DATE, BUY_DATE),
                )

            result = PortfolioPlanningService(db_path).list_trade_plans(
                ListTradePlansRequest(account_key=ACCOUNT_KEY, status="active", as_of_date=AS_OF_DATE),
                RequestContext(request_id="req-list-plans", source="api", dry_run=True),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.account_id, 1)
            self.assertEqual([plan.id for plan in result.data.trade_plans], [plan_id])
            plan = result.data.trade_plans[0]
            self.assertEqual(plan.action, "buy_next_open")
            self.assertEqual(result.lineage["account_id"], 1)
            with sqlite3.connect(db_path) as conn:
                stored = conn.execute(
                    """
                    SELECT daily_pick_id, signal_id, operator, created_at, plan_json
                    FROM trade_plans
                    WHERE id = ?
                    """,
                    (plan_id,),
                ).fetchone()
                plan_json = json.loads(stored[4])
                self.assertEqual(plan.daily_pick_id, stored[0])
                self.assertEqual(plan.signal_id, stored[1])
                self.assertEqual(plan.operator, stored[2])
                self.assertEqual(plan.created_at, stored[3])
                self.assertEqual(plan.planned_cash, plan_json["planned_cash"])
                self.assertEqual(plan.planned_shares, plan_json["planned_shares"])
                self.assertEqual(plan.ts_code, plan_json["ts_code"])
                self.assertEqual(plan.name, plan_json["name"])
                self.assertIsNotNone(plan.created_at)
                self.assertEqual(self._count(conn, "trade_plans"), 2)

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
            RequestContext(request_id="req-plan-helper", operator="tester"),
        )
        self.assertEqual(result.status, "success")
        self.assertIsNotNone(result.data.trade_plan_id)
        return int(result.data.trade_plan_id)

    def _record_buy(self, db_path: Path, plan_id: int):
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
            RequestContext(request_id=f"req-buy-{plan_id}", operator="tester"),
        )
        self.assertEqual(result.status, "success")
        return result

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

    def _insert_daily_pick(
        self,
        conn: sqlite3.Connection,
        ts_code: str = "000001.SZ",
        name: str = "PGC Candidate",
    ) -> int:
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
              (?, substr(?, 1, 6), ?, '20260427', '15:00', 10.0)
            """,
            (ts_code, ts_code, name),
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
              (?, ?, ?, ?, 'contracting_pullback.v1', '{}', 'portfolio-test-hash')
            """,
            (int(feature_run.lastrowid), int(raw_event.lastrowid), ts_code, AS_OF_DATE),
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
              (?, ?, ?, ?, ?, ?, ?, 91.0, 1, 'daily_pick', '{}')
            """,
            (
                int(strategy_run.lastrowid),
                int(feature_snapshot.lastrowid),
                int(raw_event.lastrowid),
                ts_code,
                name,
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
        self._insert_market_bar(conn, ts_code, AS_OF_DATE, close=10.0)
        return int(daily_pick.lastrowid)

    def _insert_market_bar(
        self,
        conn: sqlite3.Connection,
        ts_code: str,
        trade_date: str,
        close: float,
    ) -> None:
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
              (?, ?, ?, ?, ?, ?, 100000, 1000000, ?, ?, ?, ?)
            """,
            (
                ts_code,
                trade_date,
                close,
                close,
                close,
                close,
                close,
                close,
                close,
                close,
            ),
        )

    def _count(self, conn: sqlite3.Connection, table: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
