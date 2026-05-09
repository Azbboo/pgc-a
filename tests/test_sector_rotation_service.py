from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.sector_rotation_service import (
    ImportSectorMembershipRequest,
    SectorRotationService,
)
from pgc_trading.storage.migrate import run_migrations


AS_OF_DATE = "20260508"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "market_review" / "sector_memberships_20260508.json"


class SectorRotationServiceTest(unittest.TestCase):
    def test_dry_run_scores_sector_leadership_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_sector_market_bars(conn)

            result = SectorRotationService(db_path).import_sector_memberships(
                ImportSectorMembershipRequest(as_of_date=AS_OF_DATE, source_file=FIXTURE_PATH),
                RequestContext(request_id="sector-preview", dry_run=True, operator="tester"),
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            self.assertIsNone(result.data.market_review_run_id)
            self.assertEqual(result.data.sector_count, 2)
            self.assertEqual(result.data.member_count, 7)
            self.assertEqual(result.data.missing_bar_count, 1)
            self.assertEqual(result.data.would_insert_count, 9)
            self.assertEqual(result.data.inserted_count, 0)
            self.assertEqual(result.warnings[0].code, "MISSING_MARKET_BAR")

            pharma = self._snapshot_by_code(result.data.snapshots, "PHARMA_PACKAGING")
            self.assertEqual(pharma.rank_overall, 1)
            self.assertGreater(pharma.return_1d, 0)
            self.assertGreater(pharma.return_10d, 0)
            self.assertEqual(pharma.leader_count, 1)
            leaders = [item for item in pharma.constituents if item.role == "leader"]
            self.assertEqual([item.ts_code for item in leaders], ["301188.SZ"])
            missing = next(item for item in pharma.constituents if item.ts_code == "688999.SH")
            self.assertEqual(missing.role, "weak")
            self.assertTrue(missing.metrics["missing_bar"])

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "market_review_runs"), 0)
                self.assertEqual(self._count(conn, "sector_daily_snapshots"), 0)
                self.assertEqual(self._count(conn, "sector_constituents"), 0)

    def test_apply_persists_snapshots_idempotently_for_review_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_sector_market_bars(conn)
                run_id = self._insert_market_review_run(conn)

            service = SectorRotationService(db_path)
            request = ImportSectorMembershipRequest(as_of_date=AS_OF_DATE, source_file=FIXTURE_PATH)
            first = service.import_sector_memberships(
                request,
                RequestContext(request_id="sector-apply-1", dry_run=False, operator="tester"),
                market_review_run_id=run_id,
            )
            second = service.import_sector_memberships(
                request,
                RequestContext(request_id="sector-apply-2", dry_run=False, operator="tester"),
                market_review_run_id=run_id,
            )

            self.assertTrue(first.ok)
            self.assertTrue(second.ok)
            self.assertTrue(first.data.changed)
            self.assertFalse(second.data.changed)
            self.assertEqual(first.data.inserted_count, 9)
            self.assertEqual(second.data.unchanged_count, 9)

            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                self.assertEqual(self._count(conn, "sector_daily_snapshots"), 2)
                self.assertEqual(self._count(conn, "sector_constituents"), 7)
                top_sector = conn.execute(
                    """
                    SELECT sector_code, rank_overall, leader_count, metrics_json
                    FROM sector_daily_snapshots
                    ORDER BY rank_overall
                    LIMIT 1
                    """
                ).fetchone()
                self.assertEqual(top_sector["sector_code"], "PHARMA_PACKAGING")
                self.assertEqual(top_sector["leader_count"], 1)
                self.assertEqual(json.loads(top_sector["metrics_json"])["available_member_count"], 3)
                leader = conn.execute(
                    """
                    SELECT ts_code, role, rank_in_sector
                    FROM sector_constituents
                    WHERE sector_code = 'PHARMA_PACKAGING'
                    ORDER BY rank_in_sector IS NULL, rank_in_sector
                    LIMIT 1
                    """
                ).fetchone()
                self.assertEqual((leader["ts_code"], leader["role"], leader["rank_in_sector"]), ("301188.SZ", "leader", 1))

    def test_rejects_future_membership_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_db(tmp)
            payload = {
                "as_of_date": "20260509",
                "provider": "manual_fixture",
                "sectors": [
                    {
                        "sector_code": "FUTURE",
                        "sector_name": "Future Sector",
                        "members": [{"ts_code": "000001.SZ", "name": "Future"}],
                    }
                ],
            }

            result = SectorRotationService(db_path).import_sector_memberships(
                ImportSectorMembershipRequest(as_of_date=AS_OF_DATE, payload=payload),
                RequestContext(request_id="sector-future", dry_run=False, operator="tester"),
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "validation_failed")
            self.assertEqual(result.errors[0].code, "FUTURE_SECTOR_MEMBERSHIP")
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "sector_daily_snapshots"), 0)

    def _migrated_db(self, tmp: str) -> Path:
        db_path = Path(tmp) / "pgc.db"
        run_migrations(db_path)
        return db_path

    def _insert_sector_market_bars(self, conn: sqlite3.Connection) -> None:
        self._insert_bars(conn, "301188.SZ", [8.0, 8.1, 8.2, 8.4, 8.6, 8.9, 9.3, 9.8, 10.4, 11.0, 12.0])
        self._insert_bars(conn, "300111.SZ", [10.0, 10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 11.0])
        self._insert_bars(conn, "002222.SZ", [10.0, 10.1, 10.2, 10.1, 10.0, 9.9, 9.8, 9.7, 9.6, 9.5, 9.4])
        self._insert_bars(conn, "300001.SZ", [20.0, 20.2, 20.1, 20.2, 20.3, 20.4, 20.3, 20.5, 20.6, 20.7, 20.8])
        self._insert_bars(conn, "300002.SZ", [18.0, 18.1, 18.0, 18.0, 17.9, 17.8, 17.7, 17.8, 17.7, 17.6, 17.5])
        self._insert_bars(conn, "300003.SZ", [15.0, 15.0, 15.1, 15.1, 15.2, 15.3, 15.2, 15.3, 15.4, 15.4, 15.5])

    def _insert_bars(self, conn: sqlite3.Connection, ts_code: str, closes: list[float]) -> None:
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
        for index, (trade_date, close) in enumerate(zip(trade_dates, closes, strict=True), start=1):
            amount = 1000.0 + index * 100.0
            if ts_code == "301188.SZ":
                amount *= 2.0
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
                    amount,
                    amount * close,
                ),
            )

    def _insert_market_review_run(self, conn: sqlite3.Connection) -> int:
        conn.execute(
            """
            INSERT INTO market_review_runs
              (as_of_date, status, provider_manifest_json, coverage_json, summary_json)
            VALUES
              (?, 'completed', '{}', '{}', '{}')
            """,
            (AS_OF_DATE,),
        )
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    def _snapshot_by_code(self, snapshots, sector_code: str):
        return next(snapshot for snapshot in snapshots if snapshot.sector_code == sector_code)

    def _count(self, conn: sqlite3.Connection, table_name: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
