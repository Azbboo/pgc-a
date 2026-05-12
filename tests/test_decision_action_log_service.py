from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.decision_action_log_service import (
    CreateDecisionActionLogRequest,
    DecisionActionLogService,
    ListDecisionActionLogsRequest,
)
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data


class DecisionActionLogServiceTest(unittest.TestCase):
    def test_dry_run_previews_advisory_log_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._db(tmp)

            result = DecisionActionLogService(db_path).create_action_log(
                CreateDecisionActionLogRequest(
                    review_date="20260504",
                    execution_date="20260505",
                    system_action="record_buy",
                    operator_decision="followed",
                    target_type="trade_plan",
                    target_id=12,
                    blocker_codes=["MARKET_EVIDENCE_MISSING"],
                ),
                RequestContext(request_id="req-dry-log", dry_run=True, operator="tester"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            self.assertTrue(result.data.would_write_action_log)
            self.assertFalse(result.data.wrote_action_log)
            self.assertFalse(result.data.writes_trade_state)
            with sqlite3.connect(db_path) as conn:
                count = conn.execute("SELECT COUNT(*) FROM decision_action_logs").fetchone()[0]
            self.assertEqual(count, 0)

    def test_apply_logs_decision_and_lists_outcome_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._db(tmp)

            result = DecisionActionLogService(db_path).create_action_log(
                CreateDecisionActionLogRequest(
                    review_date="20260504",
                    execution_date="20260505",
                    system_action="record_buy",
                    operator_decision="deferred",
                    operator_note="Evidence blocker still open.",
                    target_type="trade_plan",
                    target_id=12,
                    blocker_codes=["MARKET_EVIDENCE_MISSING"],
                    source_refs=["market_review_runs:1"],
                ),
                RequestContext(
                    request_id="req-apply-log",
                    idempotency_key="decision-log:paper-main:20260504:record-buy",
                    operator="tester",
                ),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            self.assertTrue(result.data.wrote_action_log)
            self.assertEqual(result.data.outcome.outcome_status, "deferred")
            self.assertEqual(result.data.outcome.outcome_review_date, "20260506")
            self.assertFalse(result.data.writes_trade_state)
            self.assertFalse(result.data.enables_timer)

            listed = DecisionActionLogService(db_path).list_action_logs(
                ListDecisionActionLogsRequest(review_date="20260504", account_key="paper-main"),
                RequestContext(request_id="req-list-log", dry_run=True),
            )

            self.assertEqual(listed.status, "success")
            self.assertEqual(listed.data.deferred_count, 1)
            self.assertEqual(listed.data.items[0].operator_decision, "deferred")
            self.assertIn("MARKET_EVIDENCE_MISSING", listed.data.unresolved_blocker_codes)
            with sqlite3.connect(db_path) as conn:
                op_type = conn.execute("SELECT operation_type FROM operation_requests").fetchone()[0]
            self.assertEqual(op_type, "decision_action_log")

    def test_outcome_review_buckets_matched_pending_and_unexpected_trades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._db(tmp)
            service = DecisionActionLogService(db_path)

            for key, request in [
                (
                    "matched",
                    CreateDecisionActionLogRequest(
                        review_date="20260504",
                        execution_date="20260505",
                        system_action="record_buy",
                        operator_decision="followed",
                        target_type="trade_plan",
                        target_id=12,
                    ),
                ),
                (
                    "pending",
                    CreateDecisionActionLogRequest(
                        review_date="20260504",
                        execution_date="20260506",
                        system_action="record_sell",
                        operator_decision="followed",
                        target_type="position",
                        target_id=4,
                    ),
                ),
                (
                    "unexpected",
                    CreateDecisionActionLogRequest(
                        review_date="20260504",
                        execution_date="20260505",
                        system_action="wait",
                        operator_decision="followed",
                        target_type="none",
                    ),
                ),
            ]:
                result = service.create_action_log(
                    request,
                    RequestContext(
                        request_id=f"req-{key}",
                        idempotency_key=f"decision-log:paper-main:20260504:{key}",
                        operator="tester",
                    ),
                )
                self.assertEqual(result.status, "success")

            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO trades
                      (
                        account_id,
                        trade_plan_id,
                        ts_code,
                        name,
                        side,
                        planned_date,
                        executed_date,
                        executed_price,
                        amount,
                        shares,
                        status,
                        source,
                        operator
                      )
                    VALUES
                      (1, 12, '000001.SZ', 'Matched Buy', 'buy', '20260505', '20260505',
                       10.0, 1000.0, 100, 'executed', 'manual', 'tester')
                    """
                )

            listed = service.list_action_logs(
                ListDecisionActionLogsRequest(review_date="20260504", account_key="paper-main", limit=10),
                RequestContext(request_id="req-list-buckets", dry_run=True),
            )

            self.assertEqual(listed.status, "success")
            self.assertEqual(listed.data.outcome_counts["matched"], 1)
            self.assertEqual(listed.data.outcome_counts["pending"], 1)
            self.assertEqual(listed.data.outcome_counts["unexpected"], 1)
            self.assertEqual(listed.data.matched_outcome_count, 1)
            self.assertEqual(listed.data.pending_outcome_count, 1)
            self.assertEqual(listed.data.unexpected_trade_count, 1)
            statuses_by_action = {item.system_action: item.outcome.outcome_status for item in listed.data.items}
            self.assertEqual(statuses_by_action["record_buy"], "matched")
            self.assertEqual(statuses_by_action["record_sell"], "pending_outcome")
            self.assertEqual(statuses_by_action["wait"], "unexpected_trade_recorded")
            self.assertIn("Outcomes: matched=1", listed.data.summary)

    def _db(self, tmp: str) -> Path:
        db_path = Path(tmp) / "pgc.db"
        run_migrations(db_path)
        seed_reference_data(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO trade_calendar
                  (exchange, cal_date, is_open, pretrade_date)
                VALUES
                  ('SSE', ?, ?, ?)
                """,
                [
                    ("20260504", 1, "20260501"),
                    ("20260505", 1, "20260504"),
                    ("20260506", 1, "20260505"),
                ],
            )
        return db_path


if __name__ == "__main__":
    unittest.main()
