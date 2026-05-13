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
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )

        for label in ["开盘执行", "决策驾驶舱", "每日复盘", "运营验收", "运维历史", "交易计划", "成交录入", "当前持仓", "数据质量", "智能体复核"]:
            self.assertIn(label, source)
        self.assertIn("T+2", source)
        self.assertIn("T+5", source)
        self.assertIn("智能体只提供复核意见", source)

    def test_dashboard_client_uses_http_api_only(self) -> None:
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        for endpoint in [
            "/api/daily-reviews/",
            "/api/paper-acceptance/",
            "/api/paper-acceptance-history",
            "/api/next-day-decision-cockpit/",
            "/api/decision-action-log",
            "/api/ops-history",
            "/api/shadow-strategy-snapshot",
            "/api/shadow-observation-scorecard",
            "/api/shadow-observation-history",
            "/api/shadow-promotion-review-request",
            "/api/shadow-decision-memo",
            "/api/review-timeline",
            "/api/trade-plans",
            "/api/open-execution",
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

    def test_dashboard_user_visible_copy_is_chinese_first(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
            ]
        )

        for label in [
            "影子策略实验室",
            "影子快照",
            "晋升阻断",
            "跟踪验证",
            "候选就绪与回放证据",
            "无批准 / 晋升 / 交易 / 计划 / 定时任务控件",
            "运维运行历史",
            "纸盘验收历史",
            "策略提案",
            "记录跟随",
            "记录暂缓",
            "记录改写",
        ]:
            self.assertIn(label, source)

        for phrase in [
            "Shadow strategy lab",
            "Shadow snapshot",
            "Promotion blocker",
            "required human decisions",
            "candidate readiness / replay evidence",
            "rollback / release gate",
            "no approve/promote/trade/plan/timer controls",
            "review package remains manual-only",
            "evidence accepted",
            "walk-forward 完成",
            "Ops run history",
            "只记录人工 follow / defer / override",
        ]:
            self.assertNotIn(phrase, source)

    def test_dashboard_m65_ops_history_is_visible_and_read_only(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )

        for label in [
            "运维历史",
            "运维运行历史",
            "日终流水线",
            "备份",
            "发布标签",
            "远端健康检查",
            "纸盘验收快照",
            "定时任务预演证据",
            "不会启用定时任务、重跑正式写入、创建交易或修改策略状态",
            'id="opsHistoryList"',
            'id="opsHistoryCounts"',
        ]:
            self.assertIn(label, source)
        self.assertIn("/api/ops-history", source)
        self.assertIn("function loadOpsHistory", source)
        self.assertIn("function renderOpsHistory", source)
        self.assertIn("function opsHistoryCard", source)
        self.assertIn(".ops-history-card", source)

    def test_dashboard_p1_execution_workbench_is_visible(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
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
            "数据质量阻断",
            "录入锁定原因",
            "纸盘晋级分数卡",
            "样本交易",
            "已闭环交易",
            "累计实现盈亏",
            "胜率",
            "当前阻断",
            "晋级实盘前还差什么",
        ]:
            self.assertIn(label, source)
        self.assertIn('id="openingReadinessSummary"', source)
        self.assertIn('id="paperPromotionScorecard"', source)
        self.assertIn("function openingReadiness", source)
        self.assertIn("function renderPaperPromotionScorecard", source)
        self.assertIn("function promotionNextSteps", source)
        self.assertIn("function openingRecordReady", source)
        self.assertIn("function manualPreOpenChecksComplete", source)
        self.assertIn("function resetPreOpenChecks", source)
        self.assertIn("function preOpenContextKey", source)
        self.assertIn(".paper-promotion-scorecard", source)

    def test_dashboard_m17_execution_guidance_is_visible(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )

        for label in [
            "今日操作导引",
            "今天该做什么",
            "为什么不能做",
            "下一步点哪里",
            "市场计划关系",
            "定位检查清单",
            "查看数据质量",
            "录入买入成交",
            "计划交易日与执行日不一致",
        ]:
            self.assertIn(label, source)
        self.assertIn('id="openingWorkflowGuide"', source)
        self.assertIn("function renderOpeningWorkflowGuide", source)
        self.assertIn("function openExecutionGuidance", source)
        self.assertIn("function loadOpenExecution", source)
        self.assertIn("function marketPlanContextExecutionText", source)
        self.assertIn("function openingWorkflowGuidance", source)
        self.assertIn("function onWorkflowGuideClick", source)
        self.assertIn('data-guidance-action="${escapeHtml(action.action)}"', source)
        self.assertIn(".execution-command-center", source)

    def test_dashboard_m45_open_execution_market_context_is_advisory(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        for label in [
            "/api/open-execution?",
            "openExecutionEnvelope",
            "开盘执行服务找到执行日匹配的有效买入计划",
            "计划上下文只给提示，不会自动取消或执行计划",
            "仅提示考虑取消，不会自动取消计划",
            "plan-market-context-note",
        ]:
            self.assertIn(label, source)
        self.assertIn("function openExecutionGuidance", script)
        self.assertIn("function marketContextForPlan", script)
        self.assertIn("function marketContextPlanNote", script)
        self.assertNotIn("openExecution.cancel", script)
        self.assertNotIn("consider_cancel_plan", script)

    def test_dashboard_m21_detail_drawer_entries_are_visible(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )

        for label in [
            'role="dialog"',
            'id="drawerSubtitle"',
            'id="drawerMeta"',
            'id="drawerActions"',
            'id="openCandidateDetailButton"',
            'id="openAgentDetailInlineButton"',
            'id="openAgentDetailButton"',
            'id="openLineageButton"',
            'data-plan-action="detail"',
            'data-position-action="detail"',
            'data-quality-action="detail"',
            "候选详情",
            "智能体详情",
            "统一详情面板",
            "主体只保留候选摘要",
        ]:
            self.assertIn(label, source)
        for fn_name in [
            "function openDetailDrawer",
            "function detailSection",
            "function detailRows",
            "function detailMetrics",
            "function openCandidateDrawer",
            "function openQualityEventDrawer",
            "function openAgentDrawer",
            "function onQualityTableClick",
            "function onDrawerActionClick",
        ]:
            self.assertIn(fn_name, source)
        self.assertIn('data-drawer-action="${escapeHtml(action.action)}"', source)
        self.assertIn(".drawer-section", source)
        self.assertIn(".drawer-metrics", source)
        self.assertNotIn("priority-lane", source)
        self.assertNotIn("priorityLane", source)

    def test_dashboard_review_history_controls_are_visible(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )

        for label in [
            "跨日复盘对比",
            "复盘历史",
            "复盘历史列表",
            "上一复盘日",
            "下一复盘日",
            "刷新历史",
            'id="reviewDateInput" type="date"',
            'id="reviewTimelineList"',
        ]:
            self.assertIn(label, source)
        self.assertIn("/api/daily-reviews?", source)
        self.assertIn("/api/review-timeline?", source)
        self.assertIn("function loadReviewTimeline", source)
        self.assertIn("function renderReviewTimeline", source)
        self.assertIn("function onReviewTimelineClick", source)
        self.assertIn("function reviewTimelineExecutionText", source)
        self.assertIn("open_execution_next_action", source)
        self.assertIn("function latestReviewHistoryDate", source)
        self.assertIn("function shouldAdoptLatestReviewDate", source)
        self.assertIn("state.reviewDatePinned = true", source)
        self.assertIn("await refreshAll({ autoLatest: false })", source)
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

    def test_dashboard_m51_timeline_keeps_opening_execution_context_independent(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        for label in [
            "跨日复盘对比",
            "候选",
            "市场",
            "计划关系",
            "open-execution",
            "开盘执行日保持",
            "复盘下一交易日",
        ]:
            self.assertIn(label, source)
        for fn_name in [
            "function lockExecutionDate",
            "function syncExecutionDateFromReport",
            "function openExecutionActionText",
            "function openExecutionStatusText",
            "function managementActionShortText",
        ]:
            self.assertIn(fn_name, source)
        self.assertIn('executionAsOfDate: localStorage.getItem("pgc.dashboard.executionAsOfDate") || ""', script)
        self.assertIn("executionDatePinned: Boolean(localStorage.getItem(\"pgc.dashboard.executionAsOfDate\"))", script)
        self.assertIn("setReviewDate(button.dataset.reviewTimelineDate, { preserveExecutionDate: true })", script)
        self.assertIn("if (options.preserveExecutionDate !== false) lockExecutionDate(executionDate())", script)
        self.assertIn('localStorage.setItem("pgc.dashboard.executionAsOfDate", state.executionAsOfDate)', script)
        self.assertIn(".review-timeline-row", source)

    def test_dashboard_m27_operation_modals_and_review_navigation_are_visible(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )

        for label in [
            "运行日终复盘",
            "最新可用",
            "当前复盘日",
            "计划价格参考",
            "计划日期已用日期选择器锁定",
            "录入锁定原因：",
            "预演 / 正式写入",
            "操作者要求",
            "正式写入：此操作不支持预演",
            "预演：不落库",
            "确认记录买入成交",
            "确认记录卖出成交",
            "确认评估退出",
        ]:
            self.assertIn(label, source)
        for html_id in [
            'id="reviewLatestDateButton"',
            'id="currentReviewDateLabel"',
            'id="blockerReviewScope"',
            'id="candidateReviewScope"',
            'id="dueReviewScope"',
            'id="agentReviewScope"',
            'id="recordPlanReference"',
            'id="recordLockReasonInline"',
            'id="confirmSummary"',
        ]:
            self.assertIn(html_id, source)
        for fn_name in [
            "function writeConfirmationDetails",
            "function renderReviewHistoryNavigation",
            "function adjacentReviewHistoryDate",
            "function setLatestReviewDate",
            "function renderReviewScopeMarkers",
            "function setRecordDateConstraint",
            "function renderRecordReferencePanel",
        ]:
            self.assertIn(fn_name, source)
        self.assertIn("els.reviewPrevDateButton.disabled = !previousDate", source)
        self.assertIn("els.reviewNextDateButton.disabled = !nextDate", source)
        self.assertIn("els.reviewLatestDateButton.disabled", source)
        self.assertIn("els.recordDate.min = inputDate", source)
        self.assertIn("els.recordDate.max = inputDate", source)

    def test_dashboard_agent_report_display_is_chinese_and_traceable(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )

        for label in [
            "TradingAgents 智能体输出",
            "系统复盘原始数据",
            "外部证据",
            "中文复核报告",
            "TradingAgents 中文结构化报告",
            "输出来源",
            "TradingAgents 本地快照模式",
            "TradingAgents 外部图模式",
            "TradingAgents 不可用兜底模式",
            "来源边界",
            "外部数据覆盖",
            "智能体是否影响交易计划：否，仅供参考",
            "未接入/缺失",
            "未接入/数据不足",
            "基本面",
            "新闻",
            "情绪",
            "技术/量价",
            "板块位置",
            "风险",
            "结论",
            "不会自动发布、取消或记录成交，也不会向券商执行",
        ]:
            self.assertIn(label, source)
        self.assertIn("function renderAgentStructuredSections", source)
        self.assertIn("function normalizedAgentReportSections", source)
        self.assertIn("function renderAgentSourceRefs", source)
        self.assertIn("function renderAgentCoverage", source)
        self.assertIn("function renderAgentEvidence", source)
        self.assertIn("function renderAgentMissingDataWarnings", source)
        self.assertIn("function normalizedAgentCoverage", source)
        self.assertIn("function normalizedAgentAnalystReports", source)
        self.assertIn("advice.external_data_coverage", source)
        self.assertIn("advice.external_evidence", source)
        self.assertIn("advice.missing_data_warnings", source)
        self.assertIn("advice.report_sections", source)
        self.assertIn("advice.source_label", source)
        self.assertIn("agent_external_items:", source)
        self.assertIn("market_diagnostic_bars:", source)
        self.assertIn("sector_constituents:", source)
        self.assertIn("advice.source_refs", source)
        self.assertIn("agent-source-boundary", source)
        self.assertIn("agent-coverage", source)
        self.assertIn("agent-evidence", source)
        self.assertIn("agent-structured-report", source)

    def test_dashboard_m41b_full_market_view_is_read_only_and_traceable(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        for label in [
            "全市场",
            "market-reviews",
            "板块轮动",
            "持续性",
            "情绪",
            "明日计划关系",
            "策略假设",
            "个股领涨",
            "提供方/日期/情绪",
            "市场复盘不会自动改变明日计划",
        ]:
            self.assertIn(label, source)
        for html_id in [
            'id="marketBadge"',
            'id="marketRegimeStrip"',
            'id="marketSectorBody"',
            'id="marketPlanContextPanel"',
            'id="marketSentimentSummary"',
            'id="marketHypothesesList"',
        ]:
            self.assertIn(html_id, source)
        for endpoint in [
            "/api/market-reviews?limit=20",
            "/api/market-reviews/${asOfDate}",
            "/api/market-reviews/${asOfDate}/sectors",
            "/api/market-reviews/${asOfDate}/external-items",
            "/api/market-reviews/${asOfDate}/hypotheses?limit=20",
            "/api/market-reviews/${asOfDate}/plan-context",
        ]:
            self.assertIn(endpoint, script)
        for fn_name in [
            "function loadMarketReview",
            "function renderMarketReview",
            "function renderMarketSectors",
            "function openMarketSectorDrawer",
            "function openMarketNewsDrawer",
            "function renderMarketHypotheses",
            "function marketPlanContextApiPath",
        ]:
            self.assertIn(fn_name, source)
        self.assertIn("data-market-sector-action=\"detail\"", source)
        self.assertIn('data-evidence-columns="提供方/日期/情绪"', source)
        self.assertNotIn("POST /api/market-reviews", source)
        self.assertNotIn('apiRequest("/api/market-reviews", { method: "POST"', script)
        self.assertNotIn("market-review write", source.lower())

    def test_dashboard_m57_paper_acceptance_panel_is_read_only(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        for label in [
            "运营验收",
            "纸盘每日运营验收",
            "数据新鲜度",
            "证据覆盖",
            "智能体状态",
            "开盘执行状态",
            "就绪门禁",
            "未处理阻断",
            "纸盘验收历史",
            "验收告警",
            "历史趋势",
            "只读验收面板",
            "操作台不会执行交易",
            "不会自动取消或执行计划",
        ]:
            self.assertIn(label, source)
        for html_id in [
            'id="acceptanceBadge"',
            'id="acceptanceStatusPanel"',
            'id="acceptanceAlertList"',
            'id="acceptanceOverviewGrid"',
            'id="acceptanceGateBody"',
            'id="acceptanceBlockerList"',
            'id="acceptanceHistorySummary"',
            'id="acceptanceHistoryList"',
            'id="reloadAcceptanceButton"',
        ]:
            self.assertIn(html_id, source)
        for fn_name in [
            "function loadPaperAcceptance",
            "function loadPaperAcceptanceHistory",
            "function renderPaperAcceptance",
            "function renderAcceptanceAlerts",
            "function renderAcceptanceHistory",
            "function acceptanceGateCard",
            "function acceptanceStatusText",
            "function acceptanceBlockerList",
            "function acceptanceAlertList",
            "function onAcceptanceHistoryClick",
            "function paperAcceptanceAction",
            "function onAcceptanceActionClick",
        ]:
            self.assertIn(fn_name, source)
        self.assertIn("/api/paper-acceptance/${state.asOfDate}", script)
        self.assertIn("/api/paper-acceptance-history?${params.toString()}", script)
        self.assertIn('data-page-button="acceptance"', source)
        self.assertNotIn("paperAcceptanceExecute", script)
        self.assertNotIn('apiRequest("/api/paper-acceptance", { method: "POST"', script)
        self.assertNotIn('apiRequest("/api/paper-acceptance-history", { method: "POST"', script)

    def test_dashboard_m66_next_day_decision_cockpit_is_read_only(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        for label in [
            "决策驾驶舱",
            "下一交易日决策驾驶舱",
            "系统建议",
            "策略提案",
            "决策清单",
            "可执行 / 阻断 / 需人工复核",
            "操作台不会执行交易、开启定时任务或修改策略参数",
            "/api/next-day-decision-cockpit/",
        ]:
            self.assertIn(label, source)
        for html_id in [
            'id="decisionBadge"',
            'id="decisionDateLabel"',
            'id="decisionStatusPanel"',
            'id="decisionSystemProposal"',
            'id="decisionStrategyProposal"',
            'id="decisionChecklist"',
            'id="reloadDecisionButton"',
        ]:
            self.assertIn(html_id, source)
        for fn_name in [
            "function loadNextDayDecision",
            "function renderNextDayDecision",
            "function renderDecisionStrategyProposal",
            "function decisionChecklistCard",
            "function decisionStatusText",
            "function onDecisionActionClick",
        ]:
            self.assertIn(fn_name, source)
        self.assertIn('data-page-button="decision"', source)
        self.assertNotIn("nextDayDecisionExecute", script)
        self.assertNotIn('apiRequest("/api/next-day-decision-cockpit", { method: "POST"', script)

    def test_dashboard_m70_decision_action_log_is_advisory(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        for label in [
            "动作日志 / 次日复核",
            "只记录人工跟随 / 暂缓 / 改写",
            "记录跟随",
            "记录暂缓",
            "记录改写",
            "复核结果",
            "非预期成交",
            "不会执行交易、开启定时任务或修改策略参数",
            "/api/decision-action-log",
        ]:
            self.assertIn(label, source)
        for html_id in [
            'id="decisionActionLog"',
        ]:
            self.assertIn(html_id, source)
        for fn_name in [
            "function loadDecisionActionLog",
            "function renderDecisionActionLog",
            "function recordDecisionActionLog",
            "function decisionActionLogTarget",
            "function decisionChecklistCodes",
            "function decisionOutcomeClass",
            "function openDecisionActionLogDetail",
        ]:
            self.assertIn(fn_name, source)
        self.assertIn('apiRequest("/api/decision-action-log"', script)
        self.assertIn("writes_trade_state", script)
        self.assertIn("matched_outcome_count", script)
        self.assertIn("unexpected_trade_count", script)
        self.assertIn('["decision_action_log", "动作日志"]', script)
        self.assertNotIn("recordDecisionActionLogExecute", script)
        self.assertNotIn("trade_record_from_decision_action_log", script)

    def test_dashboard_m48_market_interactions_are_read_only_and_cross_day(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        for label in [
            "上一全市场",
            "下一全市场",
            "最新全市场",
            "跟随复盘日",
            "全市场历史",
            "相关明日计划",
            "来源哈希",
            "来源元数据",
            "计划详情",
        ]:
            self.assertIn(label, source)
        for html_id in [
            'id="marketReviewDateInput" type="date"',
            'id="marketPrevDateButton"',
            'id="marketNextDateButton"',
            'id="marketLatestDateButton"',
            'id="marketFollowReviewDateButton"',
            'id="marketHistoryStrip"',
        ]:
            self.assertIn(html_id, source)
        for fn_name in [
            "function setMarketReviewDate",
            "function marketReviewDate",
            "function renderMarketHistoryStrip",
            "function adjacentMarketReviewDate",
            "function renderMarketLinkedPlan",
            "function marketPlanForContext",
            "function onMarketPlanContextClick",
            "function itemTypeText",
            "function importanceText",
        ]:
            self.assertIn(fn_name, source)
        self.assertIn('data-market-history-date="${escapeHtml(date)}"', source)
        self.assertIn('data-market-plan-action="detail"', source)
        self.assertIn('localStorage.setItem("pgc.dashboard.marketAsOfDate"', source)
        self.assertNotIn("POST /api/market-reviews", source)
        self.assertNotIn('apiRequest("/api/market-reviews", { method: "POST"', script)

    def test_dashboard_m72_market_empty_state_diagnostics_are_visible(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        for label in [
            'id="marketDiagnosticsPanel"',
            "API 地址",
            "源数据库",
            "missing_downstream_tables",
            "empty_state_reasons",
            "localStorage 固定",
            "下游表状态未知",
        ]:
            self.assertIn(label, source)
        for fn_name in [
            "function renderMarketDiagnostics",
            "function marketDiagnosticTableChips",
            "function marketDiagnosticReasonText",
            "function sourceDbFreshnessText",
            "function sourceDbFreshnessClass",
        ]:
            self.assertIn(fn_name, script)
        self.assertNotIn("POST /api/market-reviews", source)

    def test_dashboard_m76_market_hierarchy_and_plan_relationship_are_visible(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        for label in [
            'id="marketHierarchyPanel"',
            "全市场复盘解释链",
            "市场状态 -> 板块 -> 个股 -> 证据 -> 连续性 -> 次日计划",
            "证据新鲜度",
            "连续性判断",
            "明日计划关系",
            "顺风一致",
            "谨慎推进",
            "冲突阻断",
            "证据缺失",
            "来源引用",
        ]:
            self.assertIn(label, source)
        for fn_name in [
            "function renderMarketReviewHierarchy",
            "function marketReviewHierarchy",
            "function marketHierarchyPlanRelationships",
            "function marketPlanRelationshipLabel",
            "function marketPlanRelationshipText",
            "function continuityText",
        ]:
            self.assertIn(fn_name, script)
        self.assertIn(".market-hierarchy-panel", source)
        self.assertNotIn('apiRequest("/api/market-reviews", { method: "POST"', script)

    def test_dashboard_m56_strategy_hypothesis_workbench_is_read_only(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        for label in [
            "假设评估",
            "策略假设评估工作台",
            "验证队列",
            "安全边界",
            "接受门禁",
            "回测产物",
            "验证事件",
            "已接受",
            "单独创建策略版本提案",
            "策略版本提案产物",
            "提案复核 / 晋升申请产物",
            "提案复核",
            "晋升申请产物",
            "待提案复核",
            "复核产物",
            "晋升申请",
            "proposal_artifact_count",
            "proposal_ready_count",
            "proposal_review_artifact_count",
            "promotion_request_count",
            "proposal_artifacts_only",
            "proposal_review_artifacts_only",
            "不修改纸盘/实盘行为",
            "/api/strategy-hypotheses/workbench",
            "/api/strategy-hypotheses/proposal-reviews",
        ]:
            self.assertIn(label, source)
        for html_id in [
            'id="hypothesesBadge"',
            'id="strategyHypothesisDateInput" type="date"',
            'id="strategyHypothesisStatusFilter"',
            'id="strategyHypothesisWorkbenchSummary"',
            'id="strategyHypothesisQueue"',
            'id="strategyHypothesisSafetyPanel"',
            'id="strategyHypothesisWorkbenchList"',
        ]:
            self.assertIn(html_id, source)
        for fn_name in [
            "function loadStrategyHypothesisWorkbench",
            "function renderStrategyHypothesisWorkbench",
            "function openStrategyHypothesisEvaluationDrawer",
            "function strategyHypothesisGateRows",
            "function strategyHypothesisProposalRows",
            "function strategyHypothesisProposalReviewRows",
            "function reviewStrategyVersionProposal",
            "function strategyProposalReviewActions",
            "function strategyProposalReviewButtons",
            "function proposalReviewDecisionText",
            "function findStrategyHypothesisEvaluation",
            "function hypothesisNextActionText",
        ]:
            self.assertIn(fn_name, source)
        self.assertIn("active_params_mutated", source)
        self.assertIn("writes_trade_state", source)
        self.assertIn("create_strategy_version_proposal", source)
        self.assertIn("review_strategy_version_proposal", source)
        self.assertIn("request_strategy_promotion", source)
        self.assertIn("promotion_requested", source)
        self.assertIn("data-strategy-proposal-review", source)
        self.assertIn("proposal_ready", source)
        self.assertNotIn("POST /api/strategy-hypotheses", source)
        self.assertNotIn('apiRequest("/api/strategy-hypotheses", { method: "POST"', script)

    def test_dashboard_m80_shadow_lab_is_visible_and_read_only(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        for label in [
            "影子实验室",
            "影子策略实验室",
            "影子快照",
            "仅用于研究观察",
            "打开候选详情",
            "晋升阻断",
            "冻结 CPB 对照",
            "跟踪验证",
            "影子策略快照",
            "不创建计划、不发布策略、不写纸盘/实盘或定时任务",
            "/api/shadow-strategy-snapshot",
        ]:
            self.assertIn(label, source)
        for html_id in [
            'id="shadowBadge"',
            'id="shadowSnapshotDateLabel"',
            'id="reloadShadowStrategyButton"',
            'id="shadowSummaryPanel"',
            'id="shadowFamilyGrid"',
            'id="shadowWalkForwardPanel"',
            'id="shadowBlockerPanel"',
            'id="shadowFrozenCpbPanel"',
            'id="shadowCandidateState"',
            'id="shadowCandidateList"',
            'id="shadowSafetyPanel"',
        ]:
            self.assertIn(html_id, source)
        for fn_name in [
            "function loadShadowStrategySnapshot",
            "function renderShadowStrategyLab",
            "function renderShadowCandidates",
            "function openShadowCandidateDrawer",
            "function onShadowCandidateClick",
            "function shadowBadgeText",
            "function findShadowCandidate",
            "function shadowArtifactRows",
        ]:
            self.assertIn(fn_name, source)
        self.assertIn("data-shadow-candidate-key", source)
        self.assertIn("active_params_mutated", source)
        self.assertIn("writes_trade_state", source)
        self.assertIn("timer_mutated", source)
        self.assertNotIn('apiRequest("/api/shadow-strategy-snapshot", { method: "POST"', script)

    def test_dashboard_m84_shadow_observation_queue_is_visible_and_read_only(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        for label in [
            "观察队列",
            "归因抽屉",
            "shadow_observation_scorecard_v1",
            "观察不是纸盘交易",
            "结果评分",
            "样本覆盖",
            "冻结 CPB 差异",
            "晋升保持阻断",
            "无晋升 / 交易 / 计划 / 定时任务控件",
            "/api/shadow-observation-scorecard",
        ]:
            self.assertIn(label, source)
        for html_id in [
            'id="shadowObservationQueueState"',
            'id="shadowObservationQueue"',
        ]:
            self.assertIn(html_id, source)
        for fn_name in [
            "function loadShadowObservationScorecard",
            "function renderShadowObservationQueue",
            "function openShadowObservationDrawer",
            "function onShadowObservationClick",
            "function findShadowObservationRow",
            "function sampleCoverageText",
        ]:
            self.assertIn(fn_name, source)
        self.assertIn("data-shadow-observation-key", source)
        self.assertIn("observation_is_not_paper_trading", source)
        self.assertIn("trade_plan_allowed", source)
        self.assertNotIn('apiRequest("/api/shadow-observation-scorecard", { method: "POST"', script)
        self.assertNotIn("data-shadow-promote", source)
        self.assertNotIn("data-shadow-trade", source)
        self.assertNotIn("data-shadow-timer", source)

    def test_dashboard_m88_shadow_observation_history_timeline_is_visible_and_read_only(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        for label in [
            "观察历史",
            "影子观察历史筛选",
            "观察截止日",
            "窗口",
            "shadow_observation_history_v1",
            "仅研究观察",
            "不是纸盘交易",
            "打开候选对比",
            "observation_history_is_research_only",
            "/api/shadow-observation-history",
        ]:
            self.assertIn(label, source)
        for html_id in [
            'id="shadowHistoryDateInput" type="date"',
            'id="shadowHistoryWindowSelect"',
            'id="shadowHistoryApplyButton"',
            'id="shadowObservationHistoryState"',
            'id="shadowObservationHistoryStrip"',
            'id="shadowObservationHistoryList"',
        ]:
            self.assertIn(html_id, source)
        for fn_name in [
            "function loadShadowObservationHistory",
            "function renderShadowObservationHistory",
            "function shadowObservationHistoryCard",
            "function openShadowObservationHistoryDrawer",
            "function findShadowObservationHistoryCandidate",
            "function onShadowObservationHistoryClick",
            "function shadowHistoryDate",
        ]:
            self.assertIn(fn_name, source)
        self.assertIn("data-shadow-history-key", source)
        self.assertIn("data-shadow-history-date", source)
        self.assertIn("promotion_allowed", source)
        self.assertIn("trade_plan_allowed", source)
        self.assertNotIn('apiRequest("/api/shadow-observation-history", { method: "POST"', script)
        self.assertNotIn("data-shadow-promote", source)
        self.assertNotIn("data-shadow-trade", source)
        self.assertNotIn("data-shadow-timer", source)

    def test_dashboard_m92_shadow_promotion_review_workbench_is_visible_and_read_only(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        for label in [
            "晋升评审工作台",
            "shadow_promotion_review_request_v1",
            "可复核”不是批准",
            "必需人工决策",
            "候选就绪与回放证据",
            "回滚与发布门禁",
            "无批准 / 晋升 / 交易 / 计划 / 定时任务控件",
            "评审申请不是批准",
            "/api/shadow-promotion-review-request",
        ]:
            self.assertIn(label, source)
        for html_id in [
            'id="shadowPromotionReviewState"',
            'id="shadowPromotionReviewWorkbench"',
        ]:
            self.assertIn(html_id, source)
        for fn_name in [
            "function loadShadowPromotionReviewRequest",
            "function renderShadowPromotionReviewWorkbench",
            "function shadowPromotionReviewCandidateCard",
            "function openShadowPromotionReviewDrawer",
            "function onShadowPromotionReviewClick",
            "function findShadowPromotionReviewCandidate",
            "function shadowPromotionEvidenceForCandidate",
        ]:
            self.assertIn(fn_name, source)
        self.assertIn("data-shadow-review-key", source)
        self.assertIn("required_replay_backtest_evidence", source)
        self.assertIn("rollback_notes", source)
        self.assertIn("safety_notes", source)
        self.assertNotIn('apiRequest("/api/shadow-promotion-review-request", { method: "POST"', script)
        self.assertNotIn("data-shadow-review-approve", source)
        self.assertNotIn("data-shadow-review-promote", source)
        self.assertNotIn("data-shadow-review-trade", source)
        self.assertNotIn("data-shadow-review-plan", source)
        self.assertNotIn("data-shadow-review-timer", source)

    def test_dashboard_m98_shadow_decision_memo_is_visible_and_read_only(self) -> None:
        source = "\n".join(
            [
                (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
                (DASHBOARD_DIR / "styles.css").read_text(encoding="utf-8"),
            ]
        )
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        for label in [
            "中文决策备忘录",
            "shadow_decision_memo_v1",
            "候选概览",
            "证据状态",
            "阻断原因",
            "下一步实验",
            "人工决策",
            "风险/回滚边界",
            "不批准、不晋升、不交易、不写计划、不改定时任务",
            "/api/shadow-decision-memo",
            'id="shadowDecisionMemoState"',
            'id="shadowDecisionMemoWorkbench"',
            "function loadShadowDecisionMemo",
            "function renderShadowDecisionMemo",
            "function shadowDecisionMemoCandidateCard",
            "function openShadowDecisionMemoDrawer",
            ".shadow-decision-grid",
        ]:
            self.assertIn(label, source)

        self.assertIn("data-shadow-decision-key", source)
        self.assertNotIn('apiRequest("/api/shadow-decision-memo", { method: "POST"', script)
        self.assertNotIn("data-shadow-decision-approve", source)
        self.assertNotIn("data-shadow-decision-promote", source)
        self.assertNotIn("data-shadow-decision-trade", source)
        self.assertNotIn("data-shadow-decision-plan", source)
        self.assertNotIn("data-shadow-decision-timer", source)

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
        self.assertIn("此操作不支持预演", source)
        self.assertIn("操作台不会向券商下单", source)
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
        self.assertIn("成交录入预演成功，未写入持仓", source)
        self.assertIn("refreshAll({ keepNotice: true })", source)
        self.assertIn("recordReviewPlanButton.disabled = blocked", source)
        self.assertIn("submitRecordButton.disabled", source)
        self.assertIn("数据质量 / 账本阻断，买入执行按钮已禁用", source)
        self.assertIn("账本不变量阻断未处理", source)
        self.assertIn("function ledgerBlockerCount", source)
        self.assertIn("DATABASE_INVARIANTS_FAILED", source)

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
        self.assertIn('writeToken: localStorage.getItem("pgc.dashboard.writeToken") || ""', script)
        self.assertIn('localStorage.setItem("pgc.dashboard.writeToken", state.writeToken)', script)
        self.assertIn('fetchOptions.headers["X-PGC-Write-Token"] = state.writeToken', script)
        self.assertIn("function shouldAttachWriteToken", script)
        self.assertIn("reviewDatePinned: false", script)
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

    def test_dashboard_write_token_field_is_password_and_not_summarized(self) -> None:
        index = (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")
        script = (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn("写入令牌", index)
        self.assertIn('id="writeTokenInput"', index)
        self.assertIn('type="password"', index)
        self.assertIn("writeTokenInput", script)
        self.assertNotIn("写入令牌", script)

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
