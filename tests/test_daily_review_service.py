from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.daily_review_service import (
    DailyReviewService,
    RunDailyReviewRequest,
)
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data
from pgc_trading.features.cpb_v2_inputs import CONTEXT_FEATURE_VERSIONS
from pgc_trading.strategies.cpb_6157 import STRATEGY_VERSION
from pgc_trading.strategies.cpb_v2 import STRATEGY_VERSION as CPB_V2_STRATEGY_VERSION


AS_OF_DATE = "20260504"
ENTRY_DATE = "20260427"


class DailyReviewServiceTest(unittest.TestCase):
    def test_run_daily_review_writes_strategy_artifacts_and_one_pick_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_open_calendar(conn)
                self._insert_contracting_pullback_case(conn, "000001.SZ", "High Score", 2.5)
                self._insert_contracting_pullback_case(conn, "000002.SZ", "Lower Score", 1.0)

            result = DailyReviewService(db_path).run_daily_review(
                RunDailyReviewRequest(as_of_date=AS_OF_DATE),
                RequestContext(
                    request_id="req-review",
                    idempotency_key="review:20260504:1",
                    operator="tester",
                ),
            )

            self.assertEqual(result.status, "success")
            self.assertTrue(result.ok)
            self.assertIsNotNone(result.data)
            self.assertIsNotNone(result.data.feature_run_id)
            self.assertIsNotNone(result.data.strategy_run_id)
            self.assertEqual(result.data.signals_count, 2)
            self.assertIsNotNone(result.data.daily_pick)
            self.assertEqual(result.data.daily_pick.ts_code, "000001.SZ")
            self.assertEqual(result.data.daily_pick.planned_buy_date, "20260505")
            self.assertEqual(result.data.skipped_reason, None)

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "feature_runs"), 1)
                self.assertEqual(self._count(conn, "feature_snapshots"), 2)
                self.assertEqual(self._count(conn, "strategy_runs"), 1)
                self.assertEqual(self._count(conn, "strategy_signals"), 2)
                self.assertEqual(self._count(conn, "daily_picks"), 1)
                self.assertEqual(self._count(conn, "trade_plans"), 0)
                self.assertEqual(self._count(conn, "trades"), 0)
                self.assertEqual(self._count(conn, "positions"), 0)

                signals = conn.execute(
                    """
                    SELECT ts_code, signal_rank, signal_status
                    FROM strategy_signals
                    ORDER BY signal_rank
                    """
                ).fetchall()
                self.assertEqual(
                    signals,
                    [("000001.SZ", 1, "daily_pick"), ("000002.SZ", 2, "candidate")],
                )
                operation = conn.execute(
                    """
                    SELECT status, operation_type, as_of_date
                    FROM operation_requests
                    """
                ).fetchone()
                self.assertEqual(operation, ("success", "daily_review", AS_OF_DATE))
                self.assertEqual(self._count(conn, "domain_events"), 1)

    def test_blocked_review_does_not_write_strategy_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_contracting_pullback_case(conn, "000001.SZ", "Blocked", 1.0)

            result = DailyReviewService(db_path).run_daily_review(
                RunDailyReviewRequest(as_of_date=AS_OF_DATE),
                RequestContext(
                    request_id="req-blocked",
                    idempotency_key="review:blocked",
                    operator="tester",
                ),
            )

            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.data.skipped_reason, "data_quality_blocker")
            self.assertEqual(result.errors[0].code, "TRADE_CALENDAR_MISSING")

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "feature_runs"), 0)
                self.assertEqual(self._count(conn, "feature_snapshots"), 0)
                self.assertEqual(self._count(conn, "strategy_runs"), 0)
                self.assertEqual(self._count(conn, "strategy_signals"), 0)
                self.assertEqual(self._count(conn, "daily_picks"), 0)
                self.assertEqual(self._count(conn, "data_quality_events"), 1)
                operation = conn.execute(
                    "SELECT status, operation_type FROM operation_requests"
                ).fetchone()
                self.assertEqual(operation, ("failed", "daily_review"))

    def test_dry_run_returns_preview_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_open_calendar(conn)
                self._insert_contracting_pullback_case(conn, "000001.SZ", "Preview", 1.0)

            result = DailyReviewService(db_path).run_daily_review(
                RunDailyReviewRequest(as_of_date=AS_OF_DATE),
                RequestContext(request_id="req-dry", dry_run=True, operator="tester"),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.feature_run_id, None)
            self.assertEqual(result.data.strategy_run_id, None)
            self.assertEqual(result.data.signals_count, 1)
            self.assertEqual(result.data.daily_pick_id, None)
            self.assertIsNotNone(result.data.daily_pick)

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "feature_runs"), 0)
                self.assertEqual(self._count(conn, "strategy_runs"), 0)
                self.assertEqual(self._count(conn, "daily_picks"), 0)
                self.assertEqual(self._count(conn, "operation_requests"), 0)

    def test_low_entry_price_still_blocks_active_cpb_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_open_calendar(conn)
                self._insert_contracting_pullback_case(
                    conn,
                    "000003.SZ",
                    "Low Price CPB",
                    0.5,
                )

            result = DailyReviewService(db_path).run_daily_review(
                RunDailyReviewRequest(as_of_date=AS_OF_DATE),
                RequestContext(request_id="req-low-price", operator="tester"),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.signals_count, 0)
            self.assertIsNone(result.data.daily_pick)
            self.assertEqual(result.data.skipped_reason, "no_strategy_signals")
            with sqlite3.connect(db_path) as conn:
                features = json.loads(
                    conn.execute(
                        """
                        SELECT features_json
                        FROM feature_snapshots
                        ORDER BY id DESC
                        LIMIT 1
                        """
                    ).fetchone()[0]
                )
                self.assertFalse(features["signal_passed"])
                self.assertEqual(features["invalid_reason"], "entry_price_below_min")
                self.assertEqual(features["min_entry_price"], 10.0)
                self.assertLess(features["entry_price"], 10.0)

    def test_cpb_v2_dry_run_uses_enriched_decision_without_portfolio_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_open_calendar(conn)
                raw_event_id = self._insert_contracting_pullback_case(
                    conn,
                    "000003.SZ",
                    "V2 Elastic",
                    2.5,
                    entry_date="20260424",
                )
                conn.execute(
                    """
                    UPDATE market_bars
                    SET amount = 500
                    WHERE ts_code = '000003.SZ'
                      AND trade_date = '20260501'
                    """
                )
                self._insert_cpb_v2_context(
                    conn,
                    raw_event_id,
                    "000003.SZ",
                    {
                        "industry": "软件服务",
                        "bigwin_score": 80.0,
                        "gap_from_trigger_close": 0.01,
                        "future_return_20d": 9.99,
                    },
                )

            result = DailyReviewService(db_path).run_daily_review(
                RunDailyReviewRequest(
                    as_of_date=AS_OF_DATE,
                    strategy_version=CPB_V2_STRATEGY_VERSION,
                ),
                RequestContext(request_id="req-v2-dry", dry_run=True, operator="tester"),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.signals_count, 1)
            self.assertIsNotNone(result.data.daily_pick)
            features = result.data.daily_pick.features
            self.assertTrue(features["signal_passed"])
            self.assertEqual(features["feature_name"], "contracting_pullback_cpb_v2")
            self.assertEqual(features["cpb_v2_non_security_result"], "passed")
            self.assertEqual(features["cpb_v2_no_chase_result"], "passed")
            self.assertTrue(features["cpb_v2_observation_sleeve"])
            self.assertEqual(features["cpb_v2_short_sleeve_weight"], 0.7)
            self.assertEqual(features["cpb_v2_observation_sleeve_weight"], 0.3)
            self.assertNotIn("future_return_20d", json.dumps(features, ensure_ascii=False))

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "feature_runs"), 1)
                self.assertEqual(self._count(conn, "strategy_runs"), 0)
                self.assertEqual(self._count(conn, "strategy_signals"), 0)
                self.assertEqual(self._count(conn, "trade_plans"), 0)
                self.assertEqual(self._count(conn, "trades"), 0)
                self.assertEqual(self._count(conn, "positions"), 0)

    def test_cpb_v2_missing_industry_writes_clear_feature_skip_without_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_open_calendar(conn)
                self._insert_contracting_pullback_case(
                    conn,
                    "000004.SZ",
                    "V2 Missing Industry",
                    1.5,
                    entry_date="20260424",
                )

            result = DailyReviewService(db_path).run_daily_review(
                RunDailyReviewRequest(
                    as_of_date=AS_OF_DATE,
                    strategy_version=CPB_V2_STRATEGY_VERSION,
                ),
                RequestContext(
                    request_id="req-v2-missing-industry",
                    idempotency_key="review:v2:missing-industry",
                    operator="tester",
                ),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.signals_count, 0)
            self.assertEqual(result.data.skipped_reason, "no_strategy_signals")
            with sqlite3.connect(db_path) as conn:
                features = json.loads(
                    conn.execute(
                        """
                        SELECT features_json
                        FROM feature_snapshots
                        ORDER BY id DESC
                        LIMIT 1
                        """
                    ).fetchone()[0]
                )
                self.assertFalse(features["signal_passed"])
                self.assertEqual(features["invalid_reason"], "cpb_v2_missing_industry")
                self.assertEqual(features["cpb_v2_non_security_result"], "missing_industry")
                self.assertEqual(self._count(conn, "strategy_signals"), 0)
                self.assertEqual(self._count(conn, "daily_picks"), 0)

    def test_review_feature_hash_ignores_future_market_bars_and_new_runs_do_not_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_open_calendar(conn)
                self._insert_contracting_pullback_case(conn, "000001.SZ", "Stable Hash", 1.0)

            service = DailyReviewService(db_path)
            first = service.run_daily_review(
                RunDailyReviewRequest(as_of_date=AS_OF_DATE),
                RequestContext(request_id="req-hash-1", idempotency_key="review:hash:1"),
            )
            first_hash, first_strategy_run_id = self._single_snapshot_hash_and_run_id(db_path)

            with sqlite3.connect(db_path) as conn:
                self._insert_market_bar(
                    conn,
                    ts_code="000001.SZ",
                    trade_date="20260506",
                    open_price=99.0,
                    high=110.0,
                    low=90.0,
                    close=105.0,
                    amount=999999.0,
                )

            second = service.run_daily_review(
                RunDailyReviewRequest(as_of_date=AS_OF_DATE),
                RequestContext(request_id="req-hash-2", idempotency_key="review:hash:2"),
            )
            second_hash, second_strategy_run_id = self._latest_snapshot_hash_and_run_id(db_path)

            self.assertEqual(first.status, "success")
            self.assertEqual(second.status, "success")
            self.assertEqual(first_hash, second_hash)
            self.assertNotEqual(first_strategy_run_id, second_strategy_run_id)
            with sqlite3.connect(db_path) as conn:
                features = json.loads(
                    conn.execute(
                        """
                        SELECT features_json
                        FROM feature_snapshots
                        ORDER BY id DESC
                        LIMIT 1
                        """
                    ).fetchone()[0]
                )
                self.assertEqual(features["latest_bar_date"], AS_OF_DATE)
                self.assertEqual(self._count(conn, "strategy_runs"), 2)

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
                ("20260505", AS_OF_DATE),
            ],
        )

    def _insert_contracting_pullback_case(
        self,
        conn: sqlite3.Connection,
        ts_code: str,
        name: str,
        price_scale: float,
        entry_date: str = ENTRY_DATE,
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO raw_events
              (ts_code, code, name, entry_date, entry_time, entry_price)
            VALUES
              (?, substr(?, 1, 6), ?, ?, '15:00', ?)
            """,
            (ts_code, ts_code, name, entry_date, 10.0 * price_scale),
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

    def _insert_cpb_v2_context(
        self,
        conn: sqlite3.Connection,
        raw_event_id: int,
        ts_code: str,
        features: dict[str, object],
    ) -> None:
        cursor = conn.execute(
            """
            INSERT INTO feature_runs (feature_version, as_of_date, status)
            VALUES (?, ?, 'completed')
            """,
            (CONTEXT_FEATURE_VERSIONS[0], AS_OF_DATE),
        )
        conn.execute(
            """
            INSERT INTO feature_snapshots
              (
                feature_run_id,
                raw_event_id,
                ts_code,
                review_date,
                feature_version,
                features_json,
                input_hash
              )
            VALUES
              (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(cursor.lastrowid),
                raw_event_id,
                ts_code,
                AS_OF_DATE,
                CONTEXT_FEATURE_VERSIONS[0],
                json.dumps(features, ensure_ascii=False, sort_keys=True),
                f"context-hash:{raw_event_id}",
            ),
        )

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

    def _single_snapshot_hash_and_run_id(self, db_path: Path) -> tuple[str, int]:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT fs.input_hash, sr.id
                FROM feature_snapshots fs
                JOIN strategy_runs sr ON sr.feature_run_id = fs.feature_run_id
                """
            ).fetchone()
        return row[0], int(row[1])

    def _latest_snapshot_hash_and_run_id(self, db_path: Path) -> tuple[str, int]:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT fs.input_hash, sr.id
                FROM feature_snapshots fs
                JOIN strategy_runs sr ON sr.feature_run_id = fs.feature_run_id
                ORDER BY fs.id DESC
                LIMIT 1
                """
            ).fetchone()
        return row[0], int(row[1])

    def _count(self, conn: sqlite3.Connection, table: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
