from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.market_review_service import (
    GetMarketReviewRequest,
    ListMarketReviewExternalItemsRequest,
    MarketReviewService,
    RunMarketReviewRequest,
)
from pgc_trading.services.sector_rotation_service import ImportSectorMembershipRequest
from pgc_trading.storage.migrate import run_migrations


AS_OF_DATE = "20260508"
SECTOR_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "market_review" / "sector_memberships_20260508.json"


class MarketReviewServiceTest(unittest.TestCase):
    def test_enough_market_bars_produce_expected_regimes(self) -> None:
        scenarios = [
            ("risk_on", [10.0, 10.2, 10.6, 10.9, 11.3], 1000.0),
            ("neutral", [10.0, 10.4, 10.2, 10.3, 10.3], 1000.0),
            ("risk_off", [11.2, 10.9, 10.5, 10.2, 9.8], 1000.0),
        ]

        for expected_regime, closes, base_vol in scenarios:
            with self.subTest(expected_regime=expected_regime), tempfile.TemporaryDirectory() as tmp:
                db_path = self._migrated_db(tmp)
                with sqlite3.connect(db_path) as conn:
                    for idx in range(6):
                        self._insert_bars(conn, f"00000{idx}.SZ", closes, base_vol + idx * 25)

                result = MarketReviewService(db_path).run_market_review(
                    RunMarketReviewRequest(as_of_date=AS_OF_DATE),
                    RequestContext(request_id=f"req-{expected_regime}", dry_run=True),
                )

                self.assertEqual(result.status, "success")
                self.assertTrue(result.ok)
                self.assertIsNotNone(result.data)
                self.assertEqual(result.data.status, "success")
                self.assertEqual(result.data.regime, expected_regime)
                self.assertEqual(result.data.coverage_ratio, 1.0)
                self.assertIsNone(result.data.market_review_run_id)
                self.assertIsNotNone(result.data.breadth_score)
                self.assertIsNotNone(result.data.trend_score)
                self.assertIsNotNone(result.data.volume_score)
                self.assertIsNotNone(result.data.persistence_score)

    def test_missing_market_bars_produce_blocked_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)

            result = MarketReviewService(db_path).run_market_review(
                RunMarketReviewRequest(as_of_date=AS_OF_DATE),
                RequestContext(request_id="req-blocked", dry_run=True),
            )

            self.assertEqual(result.status, "blocked")
            self.assertIsNotNone(result.data)
            self.assertEqual(result.data.status, "blocked")
            self.assertEqual(result.data.regime, "unknown")
            self.assertEqual(result.data.coverage_ratio, 0.0)
            self.assertEqual(result.errors[0].code, "MARKET_REVIEW_BLOCKED")
            self.assertEqual(result.warnings[0].code, "MARKET_REVIEW_COVERAGE_LOW")

    def test_dry_run_does_not_write_market_review_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            with sqlite3.connect(db_path) as conn:
                for idx in range(4):
                    self._insert_bars(conn, f"00000{idx}.SZ", [10.0, 10.2, 10.6, 10.9, 11.3])

            result = MarketReviewService(db_path).run_market_review(
                RunMarketReviewRequest(as_of_date=AS_OF_DATE),
                RequestContext(request_id="req-dry-run", dry_run=True),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNone(result.data.market_review_run_id)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "market_review_runs"), 0)
                self.assertEqual(self._count(conn, "market_regime_snapshots"), 0)

    def test_apply_mode_is_idempotent_by_as_of_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            with sqlite3.connect(db_path) as conn:
                for idx in range(4):
                    self._insert_bars(conn, f"00000{idx}.SZ", [10.0, 10.2, 10.6, 10.9, 11.3])

            service = MarketReviewService(db_path)
            request = RunMarketReviewRequest(as_of_date=AS_OF_DATE)
            first = service.run_market_review(
                request,
                RequestContext(request_id="req-apply-1", dry_run=False, operator="tester"),
            )
            second = service.run_market_review(
                request,
                RequestContext(request_id="req-apply-2", dry_run=False, operator="tester"),
            )

            self.assertEqual(first.status, "success")
            self.assertEqual(second.status, "success")
            self.assertIsNotNone(first.data.market_review_run_id)
            self.assertEqual(second.data.market_review_run_id, first.data.market_review_run_id)
            self.assertEqual(first.lineage["changed"], "true")
            self.assertEqual(second.lineage["changed"], "false")

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "market_review_runs"), 1)
                self.assertEqual(self._count(conn, "market_regime_snapshots"), 1)
                run = conn.execute(
                    "SELECT as_of_date, status FROM market_review_runs"
                ).fetchone()
                self.assertEqual(run, (AS_OF_DATE, "completed"))

    def test_future_data_after_as_of_date_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            with sqlite3.connect(db_path) as conn:
                for idx in range(5):
                    ts_code = f"00000{idx}.SZ"
                    self._insert_bars(conn, ts_code, [11.2, 10.9, 10.5, 10.2, 9.8])
                    self._insert_bar(conn, ts_code, "20260509", close=12.5, vol=5000.0)

            result = MarketReviewService(db_path).run_market_review(
                RunMarketReviewRequest(as_of_date=AS_OF_DATE),
                RequestContext(request_id="req-future", dry_run=True),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.regime, "risk_off")
            self.assertLess(result.data.breadth_score, 0.2)

    def test_sector_membership_import_creates_review_run_and_persists_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            with sqlite3.connect(db_path) as conn:
                for ts_code in ["301188.SZ", "300111.SZ", "002222.SZ", "300001.SZ", "300002.SZ", "300003.SZ"]:
                    self._insert_sector_bars(conn, ts_code)

            service = MarketReviewService(db_path)
            request = ImportSectorMembershipRequest(as_of_date=AS_OF_DATE, source_file=SECTOR_FIXTURE_PATH)
            first = service.import_sector_memberships(
                request,
                RequestContext(request_id="req-sector-1", dry_run=False, operator="tester"),
            )
            second = service.import_sector_memberships(
                request,
                RequestContext(request_id="req-sector-2", dry_run=False, operator="tester"),
            )

            self.assertEqual(first.status, "success")
            self.assertEqual(second.status, "success")
            self.assertIsNotNone(first.data.market_review_run_id)
            self.assertEqual(second.data.market_review_run_id, first.data.market_review_run_id)
            self.assertTrue(first.data.changed)
            self.assertFalse(second.data.changed)
            self.assertEqual(first.data.missing_bar_count, 1)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "market_review_runs"), 1)
                self.assertEqual(self._count(conn, "sector_daily_snapshots"), 2)
                self.assertEqual(self._count(conn, "sector_constituents"), 7)

    def test_external_item_read_payload_reports_scope_freshness_and_hash_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO market_review_runs
                      (as_of_date, status, provider_manifest_json, coverage_json, summary_json, completed_at)
                    VALUES
                      (?, 'completed', '{}', '{}', '{}', CURRENT_TIMESTAMP)
                    """,
                    (AS_OF_DATE,),
                )
                conn.execute(
                    """
                    INSERT INTO market_external_items
                      (
                        as_of_date, scope_type, scope_key, item_type, provider, title, summary,
                        sentiment, importance, published_date, source_hash
                      )
                    VALUES
                      (?, 'market', 'A_SHARE', 'policy', 'manual_fixture', '市场政策', '政策摘要',
                       'neutral', 'medium', ?, 'hash-market'),
                      (?, 'sector', 'PHARMA_PACKAGING', 'news', 'manual_fixture', '板块新闻', '板块摘要',
                       'positive', 'medium', '20260507', 'hash-sector')
                    """,
                    (AS_OF_DATE, AS_OF_DATE, AS_OF_DATE),
                )

            result = MarketReviewService(db_path).list_market_review_external_items(
                ListMarketReviewExternalItemsRequest(as_of_date=AS_OF_DATE),
                RequestContext(request_id="req-external-items", dry_run=True),
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.data["coverage"]["scope"]["market"], "available")
            self.assertEqual(result.data["coverage"]["scope"]["sector"], "partial")
            self.assertEqual(result.data["coverage"]["scope"]["stock"], "missing")
            self.assertEqual(result.data["coverage"]["freshness"]["market"], "fresh")
            self.assertEqual(result.data["coverage"]["freshness"]["sector"], "stale")
            self.assertEqual(result.data["coverage"]["freshness"]["stock"], "missing")
            self.assertEqual(result.data["coverage"]["source_hash"], "available")

    def test_market_review_detail_includes_hierarchy_and_plan_relationship(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            with sqlite3.connect(db_path) as conn:
                run_id = int(
                    conn.execute(
                        """
                        INSERT INTO market_review_runs
                          (as_of_date, status, provider_manifest_json, coverage_json, summary_json, completed_at)
                        VALUES
                          (?, 'completed', '{"fixture":"m76"}', '{"fixture":true}', '{}', CURRENT_TIMESTAMP)
                        """,
                        (AS_OF_DATE,),
                    ).lastrowid
                )
                conn.execute(
                    """
                    INSERT INTO market_regime_snapshots
                      (
                        market_review_run_id, as_of_date, regime, breadth_score, trend_score,
                        volume_score, persistence_score, summary
                      )
                    VALUES
                      (?, ?, 'risk_on', 0.72, 0.68, 0.66, 0.80, 'Market breadth and trend improved.')
                    """,
                    (run_id, AS_OF_DATE),
                )
                conn.execute(
                    """
                    INSERT INTO sector_daily_snapshots
                      (
                        market_review_run_id, as_of_date, sector_code, sector_name, provider,
                        rank_overall, breadth_score, volume_score, persistence_score, leader_count
                      )
                    VALUES
                      (?, ?, 'AI', '人工智能', 'manual_test', 1, 0.82, 0.74, 0.80, 3)
                    """,
                    (run_id, AS_OF_DATE),
                )
                conn.execute(
                    """
                    INSERT INTO sector_constituents
                      (market_review_run_id, sector_code, sector_name, ts_code, name, rank_in_sector, role, score)
                    VALUES
                      (?, 'AI', '人工智能', '000001.SZ', 'M76 Leader', 1, 'leader', 0.91)
                    """,
                    (run_id,),
                )
                conn.execute(
                    """
                    INSERT INTO market_external_items
                      (
                        as_of_date, scope_type, scope_key, item_type, provider, title, summary,
                        sentiment, importance, published_date, source_hash
                      )
                    VALUES
                      (?, 'sector', 'AI', 'news', 'manual_fixture', '板块新闻', '板块摘要',
                       'positive', 'medium', ?, 'hash-sector'),
                      (?, 'stock', '000001.SZ', 'news', 'manual_fixture', '个股新闻', '个股摘要',
                       'positive', 'medium', ?, 'hash-stock')
                    """,
                    (AS_OF_DATE, AS_OF_DATE, AS_OF_DATE, AS_OF_DATE),
                )
                conn.execute(
                    """
                    INSERT INTO market_plan_contexts
                      (market_review_run_id, trade_plan_id, alignment, risk_level, management_action, rationale, evidence_json)
                    VALUES
                      (?, 42, 'aligned', 'low', 'proceed', 'Sector and evidence support the plan.', '{"candidate":{"ts_code":"000001.SZ"}}')
                    """,
                    (run_id,),
                )

            result = MarketReviewService(db_path).get_market_review(
                GetMarketReviewRequest(as_of_date=AS_OF_DATE),
                RequestContext(request_id="req-m76-hierarchy", dry_run=True),
            )

            self.assertTrue(result.ok)
            hierarchy = result.data["hierarchy"]
            self.assertEqual(hierarchy["chain"][-1], "next_day_plan")
            self.assertEqual(hierarchy["continuity"]["label"], "improving")
            self.assertEqual(hierarchy["sectors"][0]["representative_stocks"][0]["ts_code"], "000001.SZ")
            self.assertEqual(hierarchy["sectors"][0]["evidence"]["freshness"], "fresh")
            self.assertEqual(hierarchy["evidence_freshness"]["sector"], "fresh")
            self.assertEqual(hierarchy["evidence_freshness"]["stock"], "fresh")
            self.assertEqual(hierarchy["plan_relationships"][0]["relationship_label"], "aligned")
            self.assertTrue(hierarchy["coverage"]["has_complete_chain"])
            self.assertIn(f"market_review_runs:{run_id}", hierarchy["source_refs"])
            self.assertEqual(result.data["coverage"]["hierarchy"]["plan_context_count"], 1)
            narrative = hierarchy["narrative"]
            self.assertIn("风险偏好", narrative["regime_conclusion"]["summary"])
            self.assertEqual(narrative["sector_ranking_reason"]["status"], "available")
            self.assertIn("人工智能", narrative["sector_ranking_reason"]["summary"])
            self.assertEqual(narrative["representative_stock_reason"]["stocks"][0]["ts_code"], "000001.SZ")
            self.assertIn("代表个股", narrative["representative_stock_reason"]["summary"])
            self.assertEqual(narrative["evidence_freshness"]["sector"], "fresh")
            self.assertEqual(narrative["evidence_freshness"]["stock"], "fresh")
            self.assertIn("market", {gap["scope"] for gap in narrative["evidence_gaps"]})
            self.assertEqual(narrative["continuity_judgement"]["label"], "improving")
            self.assertEqual(narrative["next_day_plan_relationship"]["relationship_label"], "aligned")
            self.assertIn("明日计划", narrative["next_day_plan_relationship"]["summary"])

    def test_market_review_narrative_marks_missing_evidence_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            with sqlite3.connect(db_path) as conn:
                run_id = int(
                    conn.execute(
                        """
                        INSERT INTO market_review_runs
                          (as_of_date, status, provider_manifest_json, coverage_json, summary_json, completed_at)
                        VALUES
                          (?, 'completed', '{"fixture":"m101"}', '{"fixture":true}', '{}', CURRENT_TIMESTAMP)
                        """,
                        (AS_OF_DATE,),
                    ).lastrowid
                )
                conn.execute(
                    """
                    INSERT INTO market_regime_snapshots
                      (
                        market_review_run_id, as_of_date, regime, breadth_score, trend_score,
                        volume_score, persistence_score, summary
                      )
                    VALUES
                      (?, ?, 'neutral', 0.50, 0.51, 0.48, 0.49, 'Regime only, no downstream evidence.')
                    """,
                    (run_id, AS_OF_DATE),
                )

            result = MarketReviewService(db_path).get_market_review(
                GetMarketReviewRequest(as_of_date=AS_OF_DATE),
                RequestContext(request_id="req-m101-missing-narrative", dry_run=True),
            )

            self.assertTrue(result.ok)
            narrative = result.data["hierarchy"]["narrative"]
            self.assertEqual(narrative["sector_ranking_reason"]["status"], "insufficient_evidence")
            self.assertIn("板块轮动数据缺失", narrative["sector_ranking_reason"]["summary"])
            self.assertEqual(narrative["representative_stock_reason"]["status"], "insufficient_evidence")
            self.assertIn("代表个股证据不足", narrative["representative_stock_reason"]["summary"])
            self.assertEqual(narrative["continuity_judgement"]["label"], "insufficient_evidence")
            self.assertEqual(narrative["next_day_plan_relationship"]["relationship_label"], "missing")
            gap_messages = "；".join(gap["message"] for gap in narrative["evidence_gaps"])
            self.assertIn("新闻证据缺失", gap_messages)
            self.assertIn("情绪证据缺失", gap_messages)
            self.assertIn("明日计划关系缺失", gap_messages)

    def _migrated_db(self, tmp: str) -> Path:
        db_path = Path(tmp) / "pgc.db"
        run_migrations(db_path)
        return db_path

    def _insert_bars(
        self,
        conn: sqlite3.Connection,
        ts_code: str,
        closes: list[float],
        base_vol: float = 1000.0,
    ) -> None:
        trade_dates = ["20260504", "20260505", "20260506", "20260507", AS_OF_DATE]
        for offset, (trade_date, close) in enumerate(zip(trade_dates, closes, strict=True)):
            self._insert_bar(conn, ts_code, trade_date, close=close, vol=base_vol + offset * 100)

    def _insert_bar(
        self,
        conn: sqlite3.Connection,
        ts_code: str,
        trade_date: str,
        *,
        close: float,
        vol: float,
    ) -> None:
        conn.execute(
            """
            INSERT INTO market_bars
              (ts_code, trade_date, open, high, low, close, vol, amount)
            VALUES
              (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts_code,
                trade_date,
                close,
                close + 0.2,
                max(close - 0.2, 0.0),
                close,
                vol,
                vol * close,
            ),
        )

    def _insert_sector_bars(self, conn: sqlite3.Connection, ts_code: str) -> None:
        trade_dates = [
            "20260423",
            "20260424",
            "20260427",
            "20260428",
            "20260429",
            "20260430",
            "20260504",
            "20260505",
            "20260506",
            "20260507",
            AS_OF_DATE,
        ]
        for index, trade_date in enumerate(trade_dates, start=1):
            close = 10.0 + index * 0.1
            vol = 1000.0 + index * 100.0
            self._insert_bar(conn, ts_code, trade_date, close=close, vol=vol)

    def _count(self, conn: sqlite3.Connection, table_name: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
