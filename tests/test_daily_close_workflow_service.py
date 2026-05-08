from __future__ import annotations

import sqlite3
import tempfile
import unittest

from pgc_trading.services.common import RequestContext
from pgc_trading.services.daily_close_workflow_service import (
    DailyCloseWorkflowService,
    RunDailyCloseWorkflowRequest,
)
from tests.helpers.daily_workflow_fixture import (
    AS_OF_DATE,
    BUY_DATE,
    PAPER_ACCOUNT_KEY,
    count_rows,
    insert_contracting_pullback_case,
    insert_open_calendar,
    migrated_seeded_daily_close_db,
)


ACCOUNT_KEY = PAPER_ACCOUNT_KEY


class DailyCloseWorkflowServiceTest(unittest.TestCase):
    def test_data_quality_blocker_prevents_review_and_plan_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = migrated_seeded_daily_close_db(tmp)
            with sqlite3.connect(db_path) as conn:
                insert_contracting_pullback_case(conn, "000001.SZ", "Blocked", 1.0)

            result = DailyCloseWorkflowService(db_path).run_daily_close(
                RunDailyCloseWorkflowRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-close-blocked", operator="tester"),
            )

            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.data.workflow_status, "data_quality_blocker")
            self.assertEqual(result.data.readiness, "blocker")
            self.assertEqual(result.errors[0].code, "TRADE_CALENDAR_MISSING")
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(count_rows(conn, "feature_runs"), 0)
                self.assertEqual(count_rows(conn, "strategy_runs"), 0)
                self.assertEqual(count_rows(conn, "daily_picks"), 0)
                self.assertEqual(count_rows(conn, "trade_plans"), 0)
                self.assertEqual(count_rows(conn, "trades"), 0)
                self.assertEqual(count_rows(conn, "positions"), 0)

    def test_no_candidate_returns_clear_no_pick_without_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = migrated_seeded_daily_close_db(tmp)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)

            result = DailyCloseWorkflowService(db_path).run_daily_close(
                RunDailyCloseWorkflowRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-close-no-pick", operator="tester"),
            )

            self.assertEqual(result.status, "skipped")
            self.assertEqual(result.data.workflow_status, "no_pick")
            self.assertEqual(result.data.skipped_reason, "no_valid_raw_events")
            self.assertEqual(result.data.signals_count, 0)
            self.assertIsNone(result.data.candidate)
            self.assertIsNone(result.data.buy_plan)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(count_rows(conn, "daily_picks"), 0)
                self.assertEqual(count_rows(conn, "trade_plans"), 0)

    def test_one_candidate_with_capacity_creates_active_buy_plan_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = migrated_seeded_daily_close_db(tmp)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "Workflow Pick", 1.0)

            result = DailyCloseWorkflowService(db_path).run_daily_close(
                RunDailyCloseWorkflowRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(
                    request_id="req-close-plan",
                    idempotency_key="daily-close:test:plan",
                    operator="tester",
                ),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.workflow_status, "plan_ready")
            self.assertEqual(result.data.next_trade_date, BUY_DATE)
            self.assertIsNotNone(result.data.candidate)
            self.assertEqual(result.data.candidate.ts_code, "000001.SZ")
            self.assertIsNotNone(result.data.buy_plan)
            self.assertEqual(result.data.buy_plan.action, "buy_next_open")
            self.assertEqual(result.data.buy_plan.status, "active")
            self.assertEqual(result.data.buy_plan.planned_trade_date, BUY_DATE)
            self.assertGreater(result.data.buy_plan.planned_shares, 0)

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(count_rows(conn, "daily_picks"), 1)
                self.assertEqual(count_rows(conn, "trade_plans"), 1)
                self.assertEqual(count_rows(conn, "trades"), 0)
                self.assertEqual(count_rows(conn, "positions"), 0)

    def test_buy_plan_preview_uses_unadjusted_close_not_adj_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = migrated_seeded_daily_close_db(tmp)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "Workflow Pick", 1.0)
                conn.execute(
                    """
                    UPDATE market_bars
                    SET adj_open = open * 3.8621,
                        adj_high = high * 3.8621,
                        adj_low = low * 3.8621,
                        adj_close = close * 3.8621
                    WHERE ts_code = '000001.SZ'
                    """
                )

            result = DailyCloseWorkflowService(db_path).run_daily_close(
                RunDailyCloseWorkflowRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(
                    request_id="req-close-plan-unadjusted",
                    idempotency_key=f"daily-close:unadjusted:{tmp}",
                    operator="tester",
                ),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data.buy_plan)
            self.assertEqual(result.data.buy_plan.planned_shares, 6700)

    def test_dry_run_previews_candidate_and_buy_plan_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = migrated_seeded_daily_close_db(tmp)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "Preview Pick", 1.0)

            result = DailyCloseWorkflowService(db_path).run_daily_close(
                RunDailyCloseWorkflowRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY),
                RequestContext(request_id="req-close-preview", dry_run=True, operator="tester"),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.workflow_status, "plan_ready")
            self.assertEqual(result.data.next_trade_date, BUY_DATE)
            self.assertIsNotNone(result.data.candidate)
            self.assertIsNone(result.data.candidate.daily_pick_id)
            self.assertIsNotNone(result.data.buy_plan)
            self.assertIsNone(result.data.buy_plan.trade_plan_id)
            self.assertEqual(result.data.buy_plan.action, "buy_next_open")
            self.assertEqual(result.data.buy_plan.status, "active")
            self.assertEqual(result.data.buy_plan.planned_trade_date, BUY_DATE)

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(count_rows(conn, "strategy_runs"), 0)
                self.assertEqual(count_rows(conn, "daily_picks"), 0)
                self.assertEqual(count_rows(conn, "trade_plans"), 0)
                self.assertEqual(count_rows(conn, "trades"), 0)
                self.assertEqual(count_rows(conn, "positions"), 0)

    def test_live_main_dry_run_builds_non_persisted_plan_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = migrated_seeded_daily_close_db(tmp)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "Live Dry Pick", 1.0)

            result = DailyCloseWorkflowService(db_path).run_daily_close(
                RunDailyCloseWorkflowRequest(as_of_date=AS_OF_DATE, account_key="live-main", run_type="live"),
                RequestContext(request_id="req-live-dry", dry_run=True, operator="tester"),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.workflow_status, "plan_ready")
            self.assertEqual(result.data.next_trade_date, BUY_DATE)
            self.assertIsNotNone(result.data.buy_plan)
            self.assertIsNone(result.data.buy_plan.trade_plan_id)
            self.assertEqual(result.data.buy_plan.action, "buy_next_open")
            self.assertEqual(result.data.buy_plan.status, "active")

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(count_rows(conn, "strategy_runs"), 0)
                self.assertEqual(count_rows(conn, "daily_picks"), 0)
                self.assertEqual(count_rows(conn, "trade_plans"), 0)
                self.assertEqual(count_rows(conn, "trades"), 0)
                self.assertEqual(count_rows(conn, "positions"), 0)

    def test_live_main_apply_is_blocked_until_explicit_live_enablement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = migrated_seeded_daily_close_db(tmp)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "Live Apply Pick", 1.0)

            result = DailyCloseWorkflowService(db_path).run_daily_close(
                RunDailyCloseWorkflowRequest(as_of_date=AS_OF_DATE, account_key="live-main", run_type="live"),
                RequestContext(request_id="req-live-apply", dry_run=False, operator="tester"),
            )

            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.data.workflow_status, "live_apply_disabled")
            self.assertEqual(result.errors[0].code, "LIVE_PLAN_APPLY_DISABLED")

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(count_rows(conn, "strategy_runs"), 0)
                self.assertEqual(count_rows(conn, "daily_picks"), 0)
                self.assertEqual(count_rows(conn, "trade_plans"), 0)
                self.assertEqual(count_rows(conn, "trades"), 0)
                self.assertEqual(count_rows(conn, "positions"), 0)

    def test_live_main_apply_with_explicit_enablement_creates_plan_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = migrated_seeded_daily_close_db(tmp)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "Live Enabled Pick", 1.0)

            result = DailyCloseWorkflowService(db_path).run_daily_close(
                RunDailyCloseWorkflowRequest(as_of_date=AS_OF_DATE, account_key="live-main", run_type="live"),
                RequestContext(
                    request_id="req-live-apply-enabled",
                    dry_run=False,
                    operator="tester",
                    allow_live_writes=True,
                ),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.workflow_status, "plan_ready")
            self.assertIsNotNone(result.data.buy_plan)
            self.assertIsNotNone(result.data.buy_plan.trade_plan_id)
            with sqlite3.connect(db_path) as conn:
                plan = conn.execute(
                    """
                    SELECT pa.account_key, tp.action, tp.status
                    FROM trade_plans tp
                    JOIN portfolio_accounts pa ON pa.id = tp.account_id
                    """
                ).fetchone()
                self.assertEqual(plan, ("live-main", "buy_next_open", "active"))
                self.assertEqual(count_rows(conn, "trades"), 0)
                self.assertEqual(count_rows(conn, "positions"), 0)

    def test_rerun_returns_existing_review_and_buy_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = migrated_seeded_daily_close_db(tmp)
            with sqlite3.connect(db_path) as conn:
                insert_open_calendar(conn)
                insert_contracting_pullback_case(conn, "000001.SZ", "Idempotent Pick", 1.0)

            service = DailyCloseWorkflowService(db_path)
            request = RunDailyCloseWorkflowRequest(as_of_date=AS_OF_DATE, account_key=ACCOUNT_KEY)
            ctx = RequestContext(
                request_id="req-close-idempotent-1",
                idempotency_key="daily-close:test:idempotent",
                operator="tester",
            )

            first = service.run_daily_close(request, ctx)
            second = service.run_daily_close(
                request,
                RequestContext(
                    request_id="req-close-idempotent-2",
                    idempotency_key="daily-close:test:idempotent",
                    operator="tester",
                ),
            )

            self.assertEqual(first.status, "success")
            self.assertEqual(second.status, "success")
            self.assertEqual(second.data.buy_plan.trade_plan_id, first.data.buy_plan.trade_plan_id)
            self.assertTrue(second.data.buy_plan.idempotent)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(count_rows(conn, "strategy_runs"), 1)
                self.assertEqual(count_rows(conn, "daily_picks"), 1)
                self.assertEqual(count_rows(conn, "trade_plans"), 1)


if __name__ == "__main__":
    unittest.main()
