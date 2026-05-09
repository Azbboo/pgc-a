from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pgc_trading.services.common import RequestContext
from pgc_trading.services.operational_readiness_service import (
    PaperReadinessRequest,
    OperationalReadinessService,
)
from pgc_trading.storage.invariant_checks import InvariantReport, InvariantViolation
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data


ACCOUNT_KEY = "paper-main"
AS_OF_DATE = "20260507"


class OperationalReadinessServiceTest(unittest.TestCase):
    def test_blocks_when_database_schema_is_not_readiness_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "legacy.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE portfolio_accounts (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      name TEXT NOT NULL UNIQUE
                    )
                    """
                )

            result = OperationalReadinessService(db_path).check_paper_readiness(
                PaperReadinessRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-schema", source="cli", dry_run=True),
            )

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.data.readiness, "blocked")
        self.assertIn("READINESS_SCHEMA_INCOMPATIBLE", [error.code for error in result.errors])

    def test_blocks_when_minimum_trade_count_is_not_met(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)

            result = OperationalReadinessService(db_path).check_paper_readiness(
                PaperReadinessRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-readiness", source="cli", dry_run=True),
            )

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.data.readiness, "blocked")
        self.assertEqual(result.data.trades_count, 0)
        self.assertIn("MIN_PAPER_TRADES_NOT_MET", [error.code for error in result.errors])

    def test_blocks_when_invariant_check_returns_violations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_executed_trades(conn, 10)

            invariant_report = InvariantReport(
                db_path=db_path,
                violations=[
                    InvariantViolation(
                        code="synthetic_violation",
                        message="Synthetic invariant failure for readiness tests.",
                    )
                ],
            )
            with patch(
                "pgc_trading.services.operational_readiness_service.check_database",
                return_value=invariant_report,
            ):
                result = OperationalReadinessService(db_path).check_paper_readiness(
                    PaperReadinessRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                    RequestContext(request_id="req-invariant", source="cli", dry_run=True),
                )

        self.assertEqual(result.status, "blocked")
        self.assertFalse(result.data.invariant_ok)
        self.assertEqual(result.data.ledger_blockers_count, 1)
        self.assertEqual(result.data.invariant_violation_codes, ["synthetic_violation"])
        self.assertIn("DATABASE_INVARIANTS_FAILED", [error.code for error in result.errors])
        self.assertIn("blocker", [error.severity for error in result.errors])

    def test_blocks_when_open_data_quality_blocker_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_executed_trades(conn, 10)
                conn.execute(
                    """
                    INSERT INTO data_quality_events
                      (layer, severity, event_code, message, status)
                    VALUES
                      ('market', 'blocker', 'MISSING_BAR', 'market bar missing', 'open')
                    """
                )

            result = OperationalReadinessService(db_path).check_paper_readiness(
                PaperReadinessRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-blocker", source="cli", dry_run=True),
            )

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.data.open_blockers_count, 1)
        self.assertIn("OPEN_DATA_QUALITY_BLOCKERS", [error.code for error in result.errors])

    def test_blocks_when_due_exit_decisions_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                account_id = self._paper_account_id(conn)
                trade_ids = self._insert_executed_trades(conn, 10)
                conn.execute(
                    """
                    INSERT INTO positions
                      (
                        account_id,
                        entry_trade_id,
                        ts_code,
                        name,
                        buy_date,
                        buy_price,
                        shares,
                        cost,
                        planned_t2_date,
                        planned_t5_date,
                        status
                      )
                    VALUES
                      (?, ?, '000001.SZ', 'Due Exit', '20260505', 10.0, 1000, 10000, '20260507', '20260512', 'waiting_t2')
                    """,
                    (account_id, trade_ids[0]),
                )

            result = OperationalReadinessService(db_path).check_paper_readiness(
                PaperReadinessRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-due", source="cli", dry_run=True),
            )

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.data.due_exit_positions_count, 1)
        self.assertIn("DUE_EXIT_DECISIONS", [error.code for error in result.errors])

    def test_blocks_when_duplicate_open_positions_exist_for_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                account_id = self._paper_account_id(conn)
                trade_ids = self._insert_executed_trades(conn, 10)
                for trade_id, name in zip(trade_ids[:2], ["Duplicate A", "Duplicate B"], strict=True):
                    conn.execute(
                        """
                        INSERT INTO positions
                          (
                            account_id,
                            entry_trade_id,
                            ts_code,
                            name,
                            buy_date,
                            buy_price,
                            shares,
                            cost,
                            planned_t2_date,
                            planned_t5_date,
                            status
                          )
                        VALUES
                          (?, ?, '000001.SZ', ?, '20260505', 10.0, 1000, 10000, '20260508', '20260512', 'waiting_t2')
                        """,
                        (account_id, trade_id, name),
                    )
                conn.execute(
                    """
                    INSERT INTO equity_snapshots
                      (account_id, as_of_date, cash, market_value, total_equity)
                    VALUES
                      (?, ?, 80000, 20000, 100000)
                    """,
                    (account_id, AS_OF_DATE),
                )

            result = OperationalReadinessService(db_path).check_paper_readiness(
                PaperReadinessRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-duplicate", source="cli", dry_run=True),
            )

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.data.open_positions_count, 2)
        self.assertIn("DUPLICATE_OPEN_POSITIONS", [error.code for error in result.errors])

    def test_warns_when_agent_evidence_is_missing_but_paper_gate_is_met(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                self._insert_executed_trades(conn, 10)

            result = OperationalReadinessService(db_path).check_paper_readiness(
                PaperReadinessRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-pass", source="cli", dry_run=True),
            )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.data.readiness, "warning")
        self.assertEqual(result.data.trades_count, 10)
        self.assertEqual(result.data.closed_trades_count, 0)
        self.assertIsNone(result.data.win_rate)
        self.assertEqual(result.data.realized_pnl, 0.0)
        self.assertEqual(result.data.open_positions_count, 0)
        self.assertEqual(result.data.due_exit_positions_count, 0)
        self.assertEqual(result.data.open_blockers_count, 0)
        self.assertTrue(result.data.invariant_ok)
        self.assertEqual(result.errors, [])
        self.assertEqual([warning.code for warning in result.warnings], ["AGENT_EVIDENCE_MISSING"])
        self.assertEqual(result.data.promotion_blockers, [])
        self.assertEqual(result.data.promotion_warnings, ["AGENT_EVIDENCE_MISSING"])

    def test_calculates_promotion_scorecard_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            with sqlite3.connect(db_path) as conn:
                account_id = self._paper_account_id(conn)
                self._insert_executed_trades(conn, 6)
                self._insert_closed_position_pair(
                    conn,
                    account_id=account_id,
                    ts_code="100001.SZ",
                    buy_price=10.0,
                    sell_price=11.2,
                    slippages=(0.01, 0.02),
                )
                self._insert_closed_position_pair(
                    conn,
                    account_id=account_id,
                    ts_code="100002.SZ",
                    buy_price=20.0,
                    sell_price=19.0,
                    slippages=(0.03, 0.04),
                )
                conn.execute(
                    """
                    INSERT INTO operation_requests
                      (idempotency_key, request_id, operation_type, account_id, as_of_date, status, request_json, finished_at)
                    VALUES
                      ('daily-pipeline:test:20260507', 'req-pipeline', 'daily_review', ?, ?, 'success', '{}', CURRENT_TIMESTAMP)
                    """,
                    (account_id, AS_OF_DATE),
                )

            result = OperationalReadinessService(db_path).check_paper_readiness(
                PaperReadinessRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-scorecard", source="cli", dry_run=True),
            )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.data.trades_count, 10)
        self.assertEqual(result.data.closed_trades_count, 2)
        self.assertEqual(result.data.win_rate, 0.5)
        self.assertAlmostEqual(result.data.realized_pnl, 20.0)
        self.assertAlmostEqual(result.data.avg_slippage, 0.025)
        self.assertEqual(result.data.last_pipeline_status, "success")

    def _migrated_seeded_db(self, tmp: str) -> Path:
        db_path = Path(tmp) / "pgc.db"
        run_migrations(db_path)
        seed_reference_data(db_path)
        return db_path

    def _insert_executed_trades(self, conn: sqlite3.Connection, count: int) -> list[int]:
        account_id = self._paper_account_id(conn)
        trade_ids: list[int] = []
        for index in range(count):
            cursor = conn.execute(
                """
                INSERT INTO trades
                  (
                    account_id,
                    ts_code,
                    name,
                    side,
                    planned_date,
                    executed_date,
                    executed_price,
                    amount,
                    shares,
                    status,
                    source
                  )
                VALUES
                  (?, ?, ?, 'buy', ?, ?, 10.0, 10000, 1000, 'executed', 'paper_model')
                """,
                (
                    account_id,
                    f"{index:06d}.SZ",
                    f"Paper Trade {index}",
                    f"202605{index + 1:02d}",
                    f"202605{index + 1:02d}",
                ),
            )
            trade_ids.append(int(cursor.lastrowid))
        return trade_ids

    def _paper_account_id(self, conn: sqlite3.Connection) -> int:
        return int(
            conn.execute(
                "SELECT id FROM portfolio_accounts WHERE account_key = ?",
                (ACCOUNT_KEY,),
            ).fetchone()[0]
        )

    def _insert_closed_position_pair(
        self,
        conn: sqlite3.Connection,
        *,
        account_id: int,
        ts_code: str,
        buy_price: float,
        sell_price: float,
        slippages: tuple[float, float],
    ) -> None:
        buy_amount = buy_price * 100
        sell_amount = sell_price * 100
        buy_cursor = conn.execute(
            """
            INSERT INTO trades
              (
                account_id,
                ts_code,
                name,
                side,
                planned_date,
                executed_date,
                executed_price,
                amount,
                shares,
                fee,
                tax,
                slippage,
                status,
                source
              )
            VALUES
              (?, ?, ?, 'buy', '20260501', '20260501', ?, ?, 100, 0, 0, ?, 'executed', 'paper_model')
            """,
            (account_id, ts_code, f"Closed {ts_code}", buy_price, buy_amount, slippages[0]),
        )
        sell_cursor = conn.execute(
            """
            INSERT INTO trades
              (
                account_id,
                ts_code,
                name,
                side,
                planned_date,
                executed_date,
                executed_price,
                amount,
                shares,
                fee,
                tax,
                slippage,
                status,
                source
              )
            VALUES
              (?, ?, ?, 'sell', '20260507', '20260507', ?, ?, 100, 0, 0, ?, 'executed', 'paper_model')
            """,
            (account_id, ts_code, f"Closed {ts_code}", sell_price, sell_amount, slippages[1]),
        )
        conn.execute(
            """
            INSERT INTO positions
              (
                account_id,
                entry_trade_id,
                exit_trade_id,
                ts_code,
                name,
                buy_date,
                buy_price,
                shares,
                cost,
                planned_t2_date,
                planned_t5_date,
                status,
                closed_at
              )
            VALUES
              (?, ?, ?, ?, ?, '20260501', ?, 100, ?, '20260505', '20260508', 'closed', CURRENT_TIMESTAMP)
            """,
            (
                account_id,
                int(buy_cursor.lastrowid),
                int(sell_cursor.lastrowid),
                ts_code,
                f"Closed {ts_code}",
                buy_price,
                buy_amount,
            ),
        )


if __name__ == "__main__":
    unittest.main()
