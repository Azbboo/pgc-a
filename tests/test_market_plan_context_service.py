from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.market_plan_context_service import (
    LinkMarketPlanContextRequest,
    MarketPlanContextService,
)
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data
from pgc_trading.strategies.cpb_6157 import STRATEGY_VERSION


AS_OF_DATE = "20260508"


class MarketPlanContextServiceTest(unittest.TestCase):
    def test_top_persistent_sector_allows_proceed_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                trade_plan_id = self._insert_candidate_plan(conn, score=0.86)
                run_id = self._insert_market_review(conn, regime="risk_on")
                self._insert_sector(
                    conn,
                    run_id,
                    sector_code="AI",
                    sector_name="人工智能",
                    rank_overall=1,
                    persistence_score=0.82,
                    role="leader",
                )
                self._insert_external_item(conn, "market", "ALL", sentiment="positive", importance="medium")

            result = MarketPlanContextService(db_path).link_plan_context(
                LinkMarketPlanContextRequest(as_of_date=AS_OF_DATE, trade_plan_id=trade_plan_id),
                RequestContext(request_id="req-m39-aligned", dry_run=False, operator="tester"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            self.assertEqual(result.data.alignment, "aligned")
            self.assertEqual(result.data.risk_level, "low")
            self.assertEqual(result.data.management_action, "proceed")
            self.assertIn("top persistent sector", result.data.rationale)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "market_plan_contexts"), 1)
                self.assertEqual(
                    conn.execute("SELECT status FROM trade_plans WHERE id = ?", (trade_plan_id,)).fetchone()[0],
                    "active",
                )

    def test_weak_sector_with_strong_stock_signal_requires_manual_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                trade_plan_id = self._insert_candidate_plan(conn, score=0.91)
                run_id = self._insert_market_review(conn, regime="neutral")
                self._insert_sector(
                    conn,
                    run_id,
                    sector_code="WEAK",
                    sector_name="弱势题材",
                    rank_overall=18,
                    persistence_score=0.12,
                    role="weak",
                )
                self._insert_external_item(conn, "stock", "000001.SZ", sentiment="neutral", importance="medium")

            result = MarketPlanContextService(db_path).link_plan_context(
                LinkMarketPlanContextRequest(as_of_date=AS_OF_DATE, trade_plan_id=trade_plan_id),
                RequestContext(request_id="req-m39-conflict", dry_run=True, operator="tester"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            self.assertEqual(result.data.alignment, "conflict")
            self.assertEqual(result.data.management_action, "manual_review")
            self.assertEqual(result.lineage["changed"], "false")
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "market_plan_contexts"), 0)

    def test_high_importance_negative_stock_item_sets_high_risk_without_cancelling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                trade_plan_id = self._insert_candidate_plan(conn, score=0.87)
                run_id = self._insert_market_review(conn, regime="risk_on")
                self._insert_sector(
                    conn,
                    run_id,
                    sector_code="AI",
                    sector_name="人工智能",
                    rank_overall=1,
                    persistence_score=0.74,
                    role="leader",
                )
                self._insert_external_item(
                    conn,
                    "stock",
                    "000001.SZ",
                    sentiment="negative",
                    importance="high",
                    title="重大负面公告",
                )
                before_counts = self._counts(conn, ["trade_plans", "trades", "positions", "daily_picks", "strategy_signals"])

            result = MarketPlanContextService(db_path).link_plan_context(
                LinkMarketPlanContextRequest(as_of_date=AS_OF_DATE, trade_plan_id=trade_plan_id),
                RequestContext(request_id="req-m39-risk", dry_run=False, operator="tester"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            self.assertEqual(result.data.alignment, "aligned")
            self.assertEqual(result.data.risk_level, "high")
            self.assertEqual(result.data.management_action, "manual_review")
            with sqlite3.connect(db_path) as conn:
                after_counts = self._counts(conn, ["trade_plans", "trades", "positions", "daily_picks", "strategy_signals"])
                self.assertEqual(after_counts, before_counts)
                self.assertEqual(self._count(conn, "market_plan_contexts"), 1)
                self.assertEqual(
                    conn.execute("SELECT status FROM trade_plans WHERE id = ?", (trade_plan_id,)).fetchone()[0],
                    "active",
                )

    def test_no_sector_or_news_data_marks_unknown_and_manual_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                trade_plan_id = self._insert_candidate_plan(conn, score=0.84)
                self._insert_market_review(conn, regime="neutral")

            result = MarketPlanContextService(db_path).link_plan_context(
                LinkMarketPlanContextRequest(as_of_date=AS_OF_DATE, trade_plan_id=trade_plan_id),
                RequestContext(request_id="req-m39-missing", dry_run=False, operator="tester"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            self.assertEqual(result.data.alignment, "unknown")
            self.assertEqual(result.data.risk_level, "unknown")
            self.assertEqual(result.data.management_action, "manual_review")
            self.assertEqual(result.warnings[0].code, "MARKET_PLAN_CONTEXT_INCOMPLETE")

    def _migrated_seeded_db(self, tmp: str) -> Path:
        db_path = Path(tmp) / "pgc.db"
        run_migrations(db_path)
        seed_reference_data(db_path)
        return db_path

    def _insert_candidate_plan(
        self,
        conn: sqlite3.Connection,
        *,
        score: float,
        ts_code: str = "000001.SZ",
        name: str = "M39 Candidate",
    ) -> int:
        strategy = conn.execute(
            """
            SELECT id, strategy_key, strategy_version, params_hash
            FROM strategy_versions
            WHERE strategy_version = ?
            """,
            (STRATEGY_VERSION,),
        ).fetchone()
        strategy_run_id = int(
            conn.execute(
                """
                INSERT INTO strategy_runs
                  (strategy_version_id, strategy_key, strategy_version, as_of_date, params_json, params_hash, status)
                VALUES
                  (?, ?, ?, ?, '{}', ?, 'completed')
                """,
                (strategy[0], strategy[1], strategy[2], AS_OF_DATE, strategy[3]),
            ).lastrowid
        )
        signal_id = int(
            conn.execute(
                """
                INSERT INTO strategy_signals
                  (strategy_run_id, ts_code, name, review_date, planned_buy_date, score, signal_rank, features_json)
                VALUES
                  (?, ?, ?, ?, '20260511', ?, 1, ?)
                """,
                (
                    strategy_run_id,
                    ts_code,
                    name,
                    AS_OF_DATE,
                    score,
                    json.dumps({"m39": "signal"}, ensure_ascii=False),
                ),
            ).lastrowid
        )
        daily_pick_id = int(
            conn.execute(
                """
                INSERT INTO daily_picks
                  (strategy_run_id, signal_id, review_date, planned_buy_date, score, selection_reason)
                VALUES
                  (?, ?, ?, '20260511', ?, 'M39 fixture pick')
                """,
                (strategy_run_id, signal_id, AS_OF_DATE, score),
            ).lastrowid
        )
        account_id = int(conn.execute("SELECT id FROM portfolio_accounts WHERE account_key = 'paper-main'").fetchone()[0])
        return int(
            conn.execute(
                """
                INSERT INTO trade_plans
                  (
                    account_id,
                    daily_pick_id,
                    signal_id,
                    as_of_date,
                    planned_trade_date,
                    planned_buy_date,
                    action,
                    reason,
                    plan_json,
                    status,
                    operator
                  )
                VALUES
                  (?, ?, ?, ?, '20260511', '20260511', 'buy_next_open', 'M39 fixture plan', '{}', 'active', 'tester')
                """,
                (account_id, daily_pick_id, signal_id, AS_OF_DATE),
            ).lastrowid
        )

    def _insert_market_review(self, conn: sqlite3.Connection, *, regime: str) -> int:
        run_id = int(
            conn.execute(
                """
                INSERT INTO market_review_runs
                  (as_of_date, status, provider_manifest_json, coverage_json, summary_json, completed_at)
                VALUES
                  (?, 'completed', '{}', '{}', '{}', CURRENT_TIMESTAMP)
                """,
                (AS_OF_DATE,),
            ).lastrowid
        )
        conn.execute(
            """
            INSERT INTO market_regime_snapshots
              (
                market_review_run_id,
                as_of_date,
                regime,
                breadth_score,
                trend_score,
                volume_score,
                sentiment_score,
                persistence_score,
                summary
              )
            VALUES
              (?, ?, ?, 0.70, 0.68, 0.65, 0.60, 0.72, 'M39 market review fixture.')
            """,
            (run_id, AS_OF_DATE, regime),
        )
        return run_id

    def _insert_sector(
        self,
        conn: sqlite3.Connection,
        run_id: int,
        *,
        sector_code: str,
        sector_name: str,
        rank_overall: int,
        persistence_score: float,
        role: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO sector_daily_snapshots
              (
                market_review_run_id,
                as_of_date,
                sector_code,
                sector_name,
                provider,
                rank_overall,
                breadth_score,
                volume_score,
                persistence_score,
                leader_count,
                metrics_json
              )
            VALUES
              (?, ?, ?, ?, 'fixture', ?, 0.70, 0.65, ?, 3, '{}')
            """,
            (run_id, AS_OF_DATE, sector_code, sector_name, rank_overall, persistence_score),
        )
        conn.execute(
            """
            INSERT INTO sector_constituents
              (market_review_run_id, sector_code, sector_name, ts_code, name, rank_in_sector, role, score, metrics_json)
            VALUES
              (?, ?, ?, '000001.SZ', 'M39 Candidate', 1, ?, 0.88, '{}')
            """,
            (run_id, sector_code, sector_name, role),
        )

    def _insert_external_item(
        self,
        conn: sqlite3.Connection,
        scope_type: str,
        scope_key: str,
        *,
        sentiment: str,
        importance: str,
        title: str = "M39 external item",
    ) -> None:
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
                sentiment,
                importance,
                published_date,
                source_hash
              )
            VALUES
              (?, ?, ?, 'news', 'fixture', ?, 'M39 fixture evidence.', ?, ?, ?, ?)
            """,
            (
                AS_OF_DATE,
                scope_type,
                scope_key,
                title,
                sentiment,
                importance,
                AS_OF_DATE,
                f"{scope_type}:{scope_key}:{sentiment}:{importance}:{title}",
            ),
        )

    def _count(self, conn: sqlite3.Connection, table_name: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])

    def _counts(self, conn: sqlite3.Connection, table_names: list[str]) -> dict[str, int]:
        return {table_name: self._count(conn, table_name) for table_name in table_names}


if __name__ == "__main__":
    unittest.main()
