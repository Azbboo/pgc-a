from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.cli.main import main
from pgc_trading.services.common import RequestContext
from pgc_trading.services.portfolio_planning_service import (
    GenerateBuyPlanRequest,
    PortfolioPlanningService,
)
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data


ACCOUNT_KEY = "paper-main"
AS_OF_DATE = "20260504"
BUY_DATE = "20260505"
T2_DATE = "20260507"


class CliExecutionRecordingTest(unittest.TestCase):
    def test_record_buy_creates_trade_and_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            plan_id = self._ready_buy_plan(db_path)

            stdout = io.StringIO()
            code = main(
                [
                    "record-buy",
                    "--plan-id",
                    str(plan_id),
                    "--date",
                    "2026-05-05",
                    "--price",
                    "10.00",
                    "--shares",
                    "1000",
                    "--account",
                    ACCOUNT_KEY,
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 0)
            self.assertIn("service returned success", stdout.getvalue())
            self.assertIn("waiting_t2", stdout.getvalue())
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "trades"), 1)
                self.assertEqual(self._count(conn, "positions"), 1)
                self.assertEqual(conn.execute("SELECT status FROM trade_plans").fetchone()[0], "executed")
                position = conn.execute(
                    "SELECT buy_date, buy_price, shares, planned_t2_date, status FROM positions"
                ).fetchone()
                self.assertEqual(position, (BUY_DATE, 10.0, 1000, T2_DATE, "waiting_t2"))

    def test_record_sell_by_position_closes_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            plan_id = self._ready_buy_plan(db_path)
            position_id = self._record_buy(db_path, plan_id)

            stdout = io.StringIO()
            code = main(
                [
                    "record-sell",
                    "--position-id",
                    str(position_id),
                    "--date",
                    "2026-05-07",
                    "--price",
                    "10.50",
                    "--shares",
                    "1000",
                    "--account",
                    ACCOUNT_KEY,
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 0)
            self.assertIn("service returned success", stdout.getvalue())
            self.assertIn("closed", stdout.getvalue())
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT status FROM positions").fetchone()[0], "closed")
                trades = conn.execute(
                    "SELECT side, trade_plan_id FROM trades ORDER BY id"
                ).fetchall()
                self.assertEqual(trades, [("buy", plan_id), ("sell", None)])

    def test_invalid_buy_plan_fails_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)

            stdout = io.StringIO()
            code = main(
                [
                    "record-buy",
                    "--plan-id",
                    "999",
                    "--date",
                    "2026-05-05",
                    "--price",
                    "10.00",
                    "--shares",
                    "1000",
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 1)
            self.assertIn("TRADE_PLAN_NOT_FOUND", stdout.getvalue())
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "trades"), 0)
                self.assertEqual(self._count(conn, "positions"), 0)

    def test_invalid_share_count_fails_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            plan_id = self._ready_buy_plan(db_path)

            stdout = io.StringIO()
            code = main(
                [
                    "record-buy",
                    "--plan-id",
                    str(plan_id),
                    "--date",
                    "2026-05-05",
                    "--price",
                    "10.00",
                    "--shares",
                    "99",
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 1)
            self.assertIn("A-share board lot", stdout.getvalue())
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(self._count(conn, "trades"), 0)
                self.assertEqual(self._count(conn, "positions"), 0)
                self.assertEqual(conn.execute("SELECT status FROM trade_plans").fetchone()[0], "active")

    def test_record_sell_enforces_account_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            plan_id = self._ready_buy_plan(db_path)
            position_id = self._record_buy(db_path, plan_id)
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO portfolio_accounts
                      (account_key, name, account_type, initial_cash, max_positions, position_sizing)
                    VALUES
                      ('paper-other', 'Other Paper', 'paper', 100000, 3, 'equal_slots')
                    """
                )

            stdout = io.StringIO()
            code = main(
                [
                    "record-sell",
                    "--position-id",
                    str(position_id),
                    "--date",
                    "2026-05-07",
                    "--price",
                    "10.50",
                    "--shares",
                    "1000",
                    "--account",
                    "paper-other",
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 1)
            self.assertIn("ACCOUNT_MISMATCH", stdout.getvalue())
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT status FROM positions").fetchone()[0], "waiting_t2")
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM trades WHERE side = 'sell'").fetchone()[0], 0)

    def test_ops_ledger_audit_reports_pass_for_consistent_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            plan_id = self._ready_buy_plan(db_path)
            self._record_buy(db_path, plan_id)

            stdout = io.StringIO()
            code = main(
                [
                    "ops",
                    "ledger-audit",
                    "--account",
                    ACCOUNT_KEY,
                    "--date",
                    BUY_DATE,
                    "--db-path",
                    str(db_path),
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 0, stdout.getvalue())
            output = stdout.getvalue()
            self.assertIn("ledger_audit_status=pass", output)
            self.assertIn(f"account_key={ACCOUNT_KEY}", output)
            self.assertIn(f"as_of_date={BUY_DATE}", output)
            self.assertIn("open_positions=1", output)
            self.assertIn("violations=0", output)

    def test_ops_ledger_repair_dry_run_prints_known_actions_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            plan_id = self._ready_buy_plan(db_path)
            self._record_buy(db_path, plan_id)
            self._corrupt_buy_ledger(db_path)

            stdout = io.StringIO()
            code = main(
                [
                    "ops",
                    "ledger-repair",
                    "--account",
                    ACCOUNT_KEY,
                    "--date",
                    BUY_DATE,
                    "--db-path",
                    str(db_path),
                    "--dry-run",
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 0, stdout.getvalue())
            output = stdout.getvalue()
            self.assertIn("ledger_repair_status=would_apply", output)
            self.assertIn("backup_required=true", output)
            self.assertIn("repair_action=code=TRADE_AMOUNT_MISMATCH", output)
            self.assertIn("repair_action=code=POSITION_ENTRY_TRADE_FACT_MISMATCH", output)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT amount FROM trades WHERE id = 1").fetchone()[0], 999.0)

    def test_ops_ledger_repair_apply_requires_operator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            plan_id = self._ready_buy_plan(db_path)
            self._record_buy(db_path, plan_id)
            self._corrupt_buy_ledger(db_path)

            stdout = io.StringIO()
            code = main(
                [
                    "ops",
                    "ledger-repair",
                    "--account",
                    ACCOUNT_KEY,
                    "--date",
                    BUY_DATE,
                    "--db-path",
                    str(db_path),
                    "--apply",
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 1)
            self.assertIn("ledger_repair_status=failed", stdout.getvalue())
            self.assertIn("OPERATOR_REQUIRED", stdout.getvalue())

    def test_ops_ledger_repair_apply_fixes_known_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            plan_id = self._ready_buy_plan(db_path)
            self._record_buy(db_path, plan_id)
            self._corrupt_buy_ledger(db_path)

            stdout = io.StringIO()
            code = main(
                [
                    "ops",
                    "ledger-repair",
                    "--account",
                    ACCOUNT_KEY,
                    "--date",
                    BUY_DATE,
                    "--db-path",
                    str(db_path),
                    "--operator",
                    "tester",
                    "--apply",
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 0, stdout.getvalue())
            output = stdout.getvalue()
            self.assertIn("ledger_repair_status=applied", output)
            backup_line = next(line for line in output.splitlines() if line.startswith("backup_path="))
            backup_path = Path(backup_line.removeprefix("backup_path="))
            self.assertTrue(backup_path.exists())
            audit_stdout = io.StringIO()
            audit_code = main(
                [
                    "ops",
                    "ledger-audit",
                    "--account",
                    ACCOUNT_KEY,
                    "--date",
                    BUY_DATE,
                    "--db-path",
                    str(db_path),
                ],
                stdout=audit_stdout,
            )
            self.assertEqual(audit_code, 0, audit_stdout.getvalue())
            self.assertIn("ledger_audit_status=pass", audit_stdout.getvalue())

    def test_ops_ledger_repair_apply_refuses_when_backup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._migrated_seeded_db(tmp)
            plan_id = self._ready_buy_plan(db_path)
            self._record_buy(db_path, plan_id)
            self._corrupt_buy_ledger(db_path)
            blocked_backup_dir = Path(tmp) / "not-a-directory"
            blocked_backup_dir.write_text("block backup mkdir", encoding="utf-8")

            stdout = io.StringIO()
            code = main(
                [
                    "ops",
                    "ledger-repair",
                    "--account",
                    ACCOUNT_KEY,
                    "--date",
                    BUY_DATE,
                    "--db-path",
                    str(db_path),
                    "--operator",
                    "tester",
                    "--backup-dir",
                    str(blocked_backup_dir),
                    "--apply",
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 1)
            output = stdout.getvalue()
            self.assertIn("ledger_repair_status=backup_failed", output)
            self.assertIn("backup_path=none", output)
            self.assertIn("LEDGER_REPAIR_BACKUP_FAILED", output)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT amount FROM trades WHERE id = 1").fetchone()[0], 999.0)

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
            RequestContext(request_id="req-plan-cli", operator="tester"),
        )
        self.assertEqual(result.status, "success")
        self.assertIsNotNone(result.data.trade_plan_id)
        return int(result.data.trade_plan_id)

    def _record_buy(self, db_path: Path, plan_id: int) -> int:
        stdout = io.StringIO()
        code = main(
            [
                "record-buy",
                "--plan-id",
                str(plan_id),
                "--date",
                "2026-05-05",
                "--price",
                "10.00",
                "--shares",
                "1000",
                "--account",
                ACCOUNT_KEY,
                "--db-path",
                str(db_path),
            ],
            stdout=stdout,
        )
        self.assertEqual(code, 0, stdout.getvalue())
        with sqlite3.connect(db_path) as conn:
            return int(conn.execute("SELECT id FROM positions").fetchone()[0])

    def _corrupt_buy_ledger(self, db_path: Path) -> None:
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE trades SET amount = 999 WHERE side = 'buy'")
            conn.execute("UPDATE positions SET buy_price = 9.0, shares = 900, cost = 999 WHERE id = 1")
            conn.execute("UPDATE equity_snapshots SET market_value = 999, total_equity = cash + 999 WHERE id = 1")

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
                ("20260512", 1, "20260511"),
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
              (?, ?, '000001.SZ', ?, 'contracting_pullback.v1', '{}', 'cli-recording-test-hash')
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
