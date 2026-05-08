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
        self.assertIn('href="/dashboard/assets/styles.css', index)
        self.assertIn('src="/dashboard/assets/app.js', index)

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
            "执行准备",
            "执行日主动计划",
            "开盘检查清单",
            "未停牌 / 可交易",
            "无重大利空",
            "开盘未极端高开",
            "现金 / 仓位已核对",
            "计划日是执行日",
            "数据质量 blocker",
            "录入锁定原因",
        ]:
            self.assertIn(label, source)
        self.assertIn('id="openingReadinessSummary"', source)
        self.assertIn("function openingReadiness", source)
        self.assertIn("function openingRecordReady", source)
        self.assertIn("function manualPreOpenChecksComplete", source)
        self.assertIn("function resetPreOpenChecks", source)
        self.assertIn("function preOpenContextKey", source)

    def test_dashboard_review_history_controls_are_visible(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
            ]
        )

        for label in [
            "复盘历史",
            "复盘历史列表",
            "上一复盘日",
            "下一复盘日",
            "刷新历史",
            'id="reviewDateInput" type="date"',
        ]:
            self.assertIn(label, source)
        self.assertIn("/api/daily-reviews?", source)
        self.assertIn('params.set("before_date", state.asOfDate)', source)
        self.assertIn("function setReviewDate", source)
        self.assertIn("function offsetBusinessDate", source)
        self.assertIn("function loadReviewHistory", source)
        self.assertIn("function renderReviewHistory", source)
        self.assertIn("function renderReviewHistoryBadges", source)
        self.assertIn("function reviewRunStatusText", source)
        self.assertIn("function displayTimestamp", source)
        self.assertIn("history-badges", source)
        self.assertIn("复盘完成", source)
        self.assertIn("创建 ${displayTimestamp(item.created_at)}", source)
        self.assertIn("els.reviewDateInput.value = dateInputValue(state.asOfDate)", source)

    def test_dashboard_agent_report_display_is_chinese_and_traceable(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )

        for label in [
            "TradingAgents 输出",
            "系统复盘原始数据",
            "中文复核报告",
            "来源边界 source_refs",
            "未接入/数据不足",
            "技术面",
            "基本面",
            "新闻面",
            "情绪面",
            "不会自动发布、取消或记录成交，也不会向券商执行",
        ]:
            self.assertIn(label, source)
        self.assertIn("function renderAgentSourceRefs", source)
        self.assertIn("function normalizedAgentAnalystReports", source)
        self.assertIn("agent_external_items:", source)
        self.assertIn("market_diagnostic_bars:", source)
        self.assertIn("advice.source_refs", source)
        self.assertIn("agent-source-boundary", source)

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
        self.assertIn("成交价和股数必须来自实际成交", source)
        self.assertIn("成交日期必须与计划交易日", source)
        self.assertIn("该计划方向必须为", source)
        self.assertIn("股数必须是 100 的整数倍", source)
        self.assertIn("开盘检查未完成", source)
        self.assertIn('id="recordValidationPanel"', source)
        self.assertIn('id="recordDate" type="date"', source)
        self.assertIn("会自动带出计划 ID、方向、成交日期、股数和参考价", source)
        self.assertIn("function planReferencePrice", source)
        self.assertIn("function recordFormIssues", source)
        self.assertIn("recordForm.addEventListener(\"input\", setRecordFormState)", source)
        self.assertIn("recordBlockers.length > 0", source)
        self.assertIn("dateInputValue(recordDate)", source)
        self.assertIn("closeDrawer();\n    setActivePage(\"record\")", source)
        self.assertIn("成交录入 dry run 成功，未写入持仓", source)
        self.assertIn("refreshAll({ keepNotice: true })", source)
        self.assertIn("recordReviewPlanButton.disabled = blocked", source)
        self.assertIn("submitRecordButton.disabled", source)

    def test_dashboard_p1_defaults_and_exit_queue_are_scoped(self) -> None:
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn('const DEFAULT_ACCOUNT_KEY = "paper-main"', script)
        self.assertIn('const LEGACY_DEFAULT_ACCOUNT_KEY = "paper-200k"', script)
        self.assertIn('const DEFAULT_API_BASE = window.location.pathname.startsWith("/pgc/") ? "/pgc" : ""', script)
        self.assertIn('const DEFAULT_OPERATOR = "azboo"', script)
        self.assertIn('apiBase: localStorage.getItem("pgc.dashboard.apiBase") || DEFAULT_API_BASE', script)
        self.assertIn("accountKey: dashboardAccountKey()", script)
        self.assertIn("operator: dashboardOperator()", script)
        self.assertIn("function dashboardOperator()", script)
        self.assertIn("dryRun: dashboardDryRun()", script)
        self.assertIn('const DRY_RUN_DEFAULT_VERSION = "20260508-live-writes-1"', script)
        self.assertIn('localStorage.setItem("pgc.dashboard.dryRun", "false")', script)
        self.assertIn('asOfDate: localStorage.getItem("pgc.dashboard.asOfDate") || defaultReviewDate()', script)
        self.assertIn("function defaultReviewDate()", script)
        self.assertIn("localStorage.setItem(\"pgc.dashboard.accountKey\", DEFAULT_ACCOUNT_KEY)", script)
        self.assertIn("function renderOpeningExitQueue()", script)
        self.assertIn("const due = duePositions();", script)
        self.assertIn("function isExitDuePosition", script)
        self.assertIn("const canRecord = !lockReason;", script)
        self.assertIn("function positionPriceIsStale", script)
        self.assertIn("最近收盘价", script)
        self.assertIn("不是实时现价", script)
        self.assertIn('els.recordPrice.value = positionPriceIsStale(position) ? "" : inputNumber(position.latest_close)', script)
        self.assertIn("function recordLockReasonForPlan", script)
        self.assertIn("function recordLockReasonForPlanAction", script)

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
