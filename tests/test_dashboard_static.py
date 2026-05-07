from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from pgc_trading.api import create_app
from pgc_trading.api.settings import ApiSettings


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = ROOT / "web" / "dashboard"


class DashboardStaticTest(unittest.TestCase):
    def test_dashboard_assets_exist_and_are_wired(self) -> None:
        index = (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")

        self.assertTrue((DASHBOARD_DIR / "styles.css").exists())
        self.assertTrue((DASHBOARD_DIR / "app.js").exists())
        self.assertIn('href="./styles.css"', index)
        self.assertIn('src="./app.js"', index)

    def test_dashboard_covers_p0_pages(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
            ]
        )

        for label in ["开盘执行", "每日复盘", "交易计划", "成交录入", "当前持仓", "数据质量", "Agent 复核"]:
            self.assertIn(label, source)
        self.assertIn("T+2", source)
        self.assertIn("T+5", source)
        self.assertIn("Agent 只提供复核意见", source)

    def test_dashboard_client_uses_http_api_only(self) -> None:
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        for endpoint in [
            "/api/daily-reviews/",
            "/api/trade-plans",
            "/api/data-quality",
            "/api/accounts/",
            "/api/review-runs",
            "/api/trades",
            "/api/exits/evaluate",
            "/publish",
            "/cancel",
        ]:
            self.assertIn(endpoint, script)
        self.assertNotIn("sqlite", script.lower())
        self.assertNotIn("pgc_trading.db", script)
        self.assertNotIn("data/pgc", script)

    def test_dashboard_p1_execution_workbench_is_visible(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
            ]
        )

        for label in [
            "今日主动计划",
            "开盘检查清单",
            "未停牌 / 可交易",
            "无重大利空",
            "开盘未极端高开",
            "现金 / 仓位已核对",
            "计划日是执行日",
            "数据质量 blocker",
        ]:
            self.assertIn(label, source)

    def test_dashboard_p1_cancel_and_execution_guardrails_are_visible(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
            ]
        )

        for reason in ["高开过大", "停牌/不可交易", "重大利空", "人工跳过"]:
            self.assertIn(reason, source)
        self.assertIn("取消原因必填", source)
        self.assertIn("此操作不支持 dry run", source)
        self.assertIn("Dashboard 不会向券商下单", source)
        self.assertIn("不会记录卖出成交", source)
        self.assertIn("recordReviewPlanButton.disabled = blocked", source)
        self.assertIn("submitRecordButton.disabled", source)

    def test_dashboard_p1_defaults_and_exit_queue_are_scoped(self) -> None:
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn('const DEFAULT_ACCOUNT_KEY = "paper-main"', script)
        self.assertIn('const LEGACY_DEFAULT_ACCOUNT_KEY = "paper-200k"', script)
        self.assertIn("accountKey: dashboardAccountKey()", script)
        self.assertIn("localStorage.setItem(\"pgc.dashboard.accountKey\", DEFAULT_ACCOUNT_KEY)", script)
        self.assertIn("function renderOpeningExitQueue()", script)
        self.assertIn("const due = duePositions();", script)
        self.assertIn("function isExitDuePosition", script)

    def test_dashboard_guardrails_are_visible_in_client(self) -> None:
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn("hasBlockingQuality", script)
        self.assertIn('plan.status !== "active"', script)
        self.assertIn("publishReviewPlanButton.disabled = blocked", script)
        self.assertIn("due_positions", script)
        self.assertIn("planned_t2_date", script)
        self.assertIn("planned_t5_date", script)

    def test_fastapi_mounts_dashboard_when_dependency_is_available(self) -> None:
        if importlib.util.find_spec("fastapi") is None:
            self.skipTest("FastAPI is not installed in this environment")

        app = create_app(ApiSettings(db_path=Path("/tmp/pgc-dashboard.db")))
        route_paths = {getattr(route, "path", None) for route in app.routes}
        route_names = {getattr(route, "name", None) for route in app.routes}

        self.assertIn("/dashboard", route_paths)
        self.assertIn("/dashboard/", route_paths)
        self.assertIn("pgc_dashboard_assets", route_names)


if __name__ == "__main__":
    unittest.main()
