const DEFAULT_STRATEGY_VERSION = "cpb_6157@2026-05-03";
const DEFAULT_ACCOUNT_KEY = "paper-main";
const LEGACY_DEFAULT_ACCOUNT_KEY = "paper-200k";
const DEFAULT_API_BASE = window.location.pathname.startsWith("/pgc/") ? "/pgc" : "";
const DEFAULT_OPERATOR = "azboo";
const CANCEL_REASON_CHOICES = ["高开过大", "停牌/不可交易", "重大利空", "人工跳过"];
const DRY_RUN_DEFAULT_VERSION = "20260508-live-writes-1";
const AGENT_ANALYST_SECTIONS = [
  ["fundamental", "基本面"],
  ["news", "新闻面"],
  ["sentiment", "情绪面"],
  ["technical", "技术/量价"],
  ["sector", "板块位置"],
];
const AGENT_REPORT_SECTIONS = [
  ["fundamental", "基本面"],
  ["news", "新闻"],
  ["sentiment", "情绪"],
  ["technical", "技术/量价"],
  ["sector", "板块位置"],
  ["risk", "风险"],
  ["conclusion", "结论"],
];

const state = {
  apiBase: localStorage.getItem("pgc.dashboard.apiBase") || DEFAULT_API_BASE,
  accountKey: dashboardAccountKey(),
  accountId: localStorage.getItem("pgc.dashboard.accountId") || "",
  asOfDate: localStorage.getItem("pgc.dashboard.asOfDate") || defaultReviewDate(),
  executionAsOfDate: localStorage.getItem("pgc.dashboard.executionAsOfDate") || "",
  executionDatePinned: Boolean(localStorage.getItem("pgc.dashboard.executionAsOfDate")),
  strategyVersion: localStorage.getItem("pgc.dashboard.strategyVersion") || DEFAULT_STRATEGY_VERSION,
  operator: dashboardOperator(),
  writeToken: localStorage.getItem("pgc.dashboard.writeToken") || "",
  dryRun: dashboardDryRun(),
  activePage: initialPage(),
  busy: false,
  reviewDatePinned: false,
  report: null,
  reportEnvelope: null,
  nextDayDecision: null,
  nextDayDecisionEnvelope: null,
  paperAcceptance: null,
  paperAcceptanceEnvelope: null,
  paperAcceptanceHistory: null,
  paperAcceptanceHistoryEnvelope: null,
  opsHistory: null,
  opsHistoryEnvelope: null,
  reviewHistory: [],
  reviewTimeline: [],
  reviewTimelineEnvelope: null,
  openExecution: null,
  openExecutionEnvelope: null,
  marketReviewHistory: [],
  marketAsOfDate: localStorage.getItem("pgc.dashboard.marketAsOfDate") || "",
  marketDatePinned: Boolean(localStorage.getItem("pgc.dashboard.marketAsOfDate")),
  marketReview: null,
  marketReviewEnvelope: null,
  marketSectors: [],
  marketSectorsEnvelope: null,
  marketExternalItems: [],
  marketExternalEnvelope: null,
  marketHypotheses: [],
  marketHypothesesEnvelope: null,
  marketPlanContexts: [],
  marketPlanContextEnvelope: null,
  strategyHypothesisAsOfDate: localStorage.getItem("pgc.dashboard.strategyHypothesisAsOfDate") || "",
  strategyHypothesisWorkbench: null,
  strategyHypothesisWorkbenchEnvelope: null,
  tradePlans: [],
  positions: [],
  qualityEvents: [],
  selectedPlan: null,
  selectedPosition: null,
  preOpenChecks: {
    notSuspended: false,
    noMajorBadNews: false,
    openNotExtremeHigh: false,
    cashSlotsChecked: false,
  },
};

const els = {};

document.addEventListener("DOMContentLoaded", () => {
  cacheElements();
  bindEvents();
  syncFormFromState();
  setActivePage(state.activePage);
  refreshAll();
});

function cacheElements() {
  const ids = [
    "contextForm",
    "accountKeyInput",
    "accountIdInput",
    "asOfDateInput",
    "strategyInput",
    "operatorInput",
    "writeTokenInput",
    "apiBaseInput",
    "dryRunInput",
    "executionBadge",
    "decisionBadge",
    "reloadDecisionButton",
    "decisionDateLabel",
    "decisionStatusPanel",
    "decisionSystemProposal",
    "decisionStrategyProposal",
    "decisionChecklist",
    "reloadExecutionButton",
    "executionEvaluateExitsButton",
    "openingWorkflowGuide",
    "openingReadinessSummary",
    "paperPromotionScorecard",
    "openingBlockerChip",
    "openingPlanBody",
    "preOpenChecklist",
    "preOpenChecklistState",
    "openingCancelQueue",
    "openingExitQueue",
    "statusAccount",
    "statusReviewDate",
    "statusNextDate",
    "statusMarketDate",
    "statusCapacity",
    "statusQuality",
    "noticeLine",
    "reviewBadge",
    "marketBadge",
    "acceptanceBadge",
    "reloadAcceptanceButton",
    "acceptanceDateLabel",
    "acceptanceStatusPanel",
    "acceptanceAlertList",
    "acceptanceOverviewGrid",
    "acceptanceGateBody",
    "acceptanceBlockerList",
    "acceptanceHistorySummary",
    "acceptanceHistoryList",
    "opsBadge",
    "reloadOpsHistoryButton",
    "opsHistorySummary",
    "opsHistoryCounts",
    "opsHistoryList",
    "hypothesesBadge",
    "reloadMarketButton",
    "marketReviewDateInput",
    "marketPrevDateButton",
    "marketNextDateButton",
    "marketLatestDateButton",
    "marketFollowReviewDateButton",
    "marketApplyDateButton",
    "marketReviewDateLabel",
    "marketHistoryStrip",
    "marketRegimeStrip",
    "marketSectorState",
    "marketSectorBody",
    "marketPlanContextPanel",
    "marketSentimentState",
    "openMarketNewsDrawerButton",
    "marketSentimentSummary",
    "marketHypothesisState",
    "marketHypothesesList",
    "strategyHypothesisDateInput",
    "strategyHypothesisStatusFilter",
    "strategyHypothesisClearDateButton",
    "reloadStrategyHypothesesButton",
    "strategyHypothesisWorkbenchSummary",
    "strategyHypothesisQueueState",
    "strategyHypothesisQueue",
    "strategyHypothesisSafetyPanel",
    "strategyHypothesisWorkbenchState",
    "strategyHypothesisWorkbenchList",
    "plansBadge",
    "recordBadge",
    "positionsBadge",
    "qualityBadge",
    "runReviewButton",
    "publishReviewPlanButton",
    "recordReviewPlanButton",
    "currentReviewDateLabel",
    "reviewDateInput",
    "reviewPrevDateButton",
    "reviewNextDateButton",
    "reviewLatestDateButton",
    "reviewApplyDateButton",
    "reviewTimelineState",
    "reviewTimelineList",
    "reviewHistoryState",
    "reloadReviewHistoryButton",
    "reviewHistoryList",
    "nextActionDate",
    "blockerReviewScope",
    "nextActionBody",
    "blockerList",
    "candidateReviewScope",
    "candidateSummary",
    "rankedSignalsBody",
    "dueReviewScope",
    "duePositionsBody",
    "agentReviewScope",
    "agentSummary",
    "agentPageBody",
    "openCandidateDetailButton",
    "openAgentDetailInlineButton",
    "openAgentDetailButton",
    "openLineageButton",
    "planStatusFilter",
    "reloadPlansButton",
    "plansBody",
    "recordQueue",
    "recordForm",
    "recordPlanId",
    "recordPositionId",
    "recordSide",
    "recordDate",
    "recordPrice",
    "recordShares",
    "recordFee",
    "recordTax",
    "recordSlippage",
    "recordPrefillHint",
    "recordPlanReference",
    "recordLockReasonInline",
    "recordValidationPanel",
    "recordModeChip",
    "clearRecordButton",
    "submitRecordButton",
    "evaluateExitsButton",
    "reloadPositionsButton",
    "positionsBody",
    "qualitySeverityFilter",
    "reloadQualityButton",
    "qualityBody",
    "detailDrawer",
    "drawerKicker",
    "drawerTitle",
    "drawerSubtitle",
    "drawerMeta",
    "drawerActions",
    "drawerBody",
    "closeDrawerButton",
    "confirmDialog",
    "confirmTitle",
    "confirmBody",
    "confirmSummary",
    "confirmInputLabel",
    "confirmInputText",
    "confirmInput",
    "confirmQuickChoices",
    "confirmSubmit",
  ];
  for (const id of ids) {
    els[id] = document.getElementById(id);
  }
}

function bindEvents() {
  els.contextForm.addEventListener("submit", (event) => {
    event.preventDefault();
    readContextForm();
    persistContext();
    refreshAll();
  });

  document.querySelectorAll("[data-page-button]").forEach((button) => {
    button.addEventListener("click", () => setActivePage(button.dataset.pageButton));
  });
  document.querySelectorAll("[data-page-jump]").forEach((button) => {
    button.addEventListener("click", () => setActivePage(button.dataset.pageJump));
  });

  els.runReviewButton.addEventListener("click", runReview);
  els.reviewApplyDateButton.addEventListener("click", applyReviewDateInput);
  els.reviewDateInput.addEventListener("change", applyReviewDateInput);
  els.reviewPrevDateButton.addEventListener("click", () => shiftReviewDate(-1));
  els.reviewNextDateButton.addEventListener("click", () => shiftReviewDate(1));
  els.reviewLatestDateButton.addEventListener("click", setLatestReviewDate);
  els.reloadReviewHistoryButton.addEventListener("click", loadReviewHistoryAndRender);
  els.reviewTimelineList.addEventListener("click", onReviewTimelineClick);
  els.reviewHistoryList.addEventListener("click", onReviewHistoryClick);
  els.reloadAcceptanceButton.addEventListener("click", loadPaperAcceptanceAndRender);
  els.acceptanceStatusPanel.addEventListener("click", onAcceptanceActionClick);
  els.acceptanceAlertList.addEventListener("click", onAcceptanceActionClick);
  els.acceptanceGateBody.addEventListener("click", onAcceptanceActionClick);
  els.acceptanceBlockerList.addEventListener("click", onAcceptanceActionClick);
  els.acceptanceHistoryList.addEventListener("click", onAcceptanceHistoryClick);
  els.reloadDecisionButton.addEventListener("click", loadNextDayDecisionAndRender);
  els.decisionStatusPanel.addEventListener("click", onDecisionActionClick);
  els.decisionSystemProposal.addEventListener("click", onDecisionActionClick);
  els.decisionStrategyProposal.addEventListener("click", onDecisionActionClick);
  els.decisionChecklist.addEventListener("click", onDecisionActionClick);
  els.reloadOpsHistoryButton.addEventListener("click", loadOpsHistoryAndRender);
  els.reloadMarketButton.addEventListener("click", loadMarketReviewAndRender);
  els.marketApplyDateButton.addEventListener("click", applyMarketReviewDateInput);
  els.marketReviewDateInput.addEventListener("change", applyMarketReviewDateInput);
  els.marketPrevDateButton.addEventListener("click", () => shiftMarketReviewDate(-1));
  els.marketNextDateButton.addEventListener("click", () => shiftMarketReviewDate(1));
  els.marketLatestDateButton.addEventListener("click", setLatestMarketReviewDate);
  els.marketFollowReviewDateButton.addEventListener("click", followReviewDateForMarket);
  els.marketHistoryStrip.addEventListener("click", onMarketHistoryClick);
  els.marketSectorBody.addEventListener("click", onMarketSectorClick);
  els.marketPlanContextPanel.addEventListener("click", onMarketPlanContextClick);
  els.openMarketNewsDrawerButton.addEventListener("click", () => openMarketNewsDrawer());
  els.marketHypothesesList.addEventListener("click", onMarketHypothesisClick);
  els.reloadStrategyHypothesesButton.addEventListener("click", loadStrategyHypothesisWorkbenchAndRender);
  els.strategyHypothesisStatusFilter.addEventListener("change", loadStrategyHypothesisWorkbenchAndRender);
  els.strategyHypothesisDateInput.addEventListener("change", applyStrategyHypothesisDateInput);
  els.strategyHypothesisClearDateButton.addEventListener("click", clearStrategyHypothesisDateFilter);
  els.strategyHypothesisWorkbenchList.addEventListener("click", onStrategyHypothesisWorkbenchClick);
  els.strategyHypothesisQueue.addEventListener("click", onStrategyHypothesisWorkbenchClick);
  els.reloadExecutionButton.addEventListener("click", refreshAll);
  els.executionEvaluateExitsButton.addEventListener("click", evaluateExits);
  els.publishReviewPlanButton.addEventListener("click", () => {
    const plan = state.report?.buy_plan;
    if (plan?.trade_plan_id) publishPlan(plan.trade_plan_id);
  });
  els.recordReviewPlanButton.addEventListener("click", () => {
    const plan = state.report?.buy_plan;
    if (!plan || plan.status !== "active") return;
    selectPlan(planFromReport(plan), { openRecordPage: true });
  });
  els.openLineageButton.addEventListener("click", openLineageDrawer);
  els.reloadPlansButton.addEventListener("click", loadPlansAndRender);
  els.planStatusFilter.addEventListener("change", loadPlansAndRender);
  els.reloadPositionsButton.addEventListener("click", loadPositionsAndRender);
  els.evaluateExitsButton.addEventListener("click", evaluateExits);
  els.reloadQualityButton.addEventListener("click", loadQualityAndRender);
  els.qualitySeverityFilter.addEventListener("change", loadQualityAndRender);
  els.recordForm.addEventListener("submit", submitTradeRecord);
  els.recordForm.addEventListener("input", setRecordFormState);
  els.recordForm.addEventListener("change", setRecordFormState);
  els.clearRecordButton.addEventListener("click", clearRecordForm);
  els.closeDrawerButton.addEventListener("click", closeDrawer);
  els.drawerActions.addEventListener("click", onDrawerActionClick);
  els.openCandidateDetailButton.addEventListener("click", openCandidateDrawer);
  els.openAgentDetailInlineButton.addEventListener("click", openAgentDrawer);
  els.openAgentDetailButton.addEventListener("click", openAgentDrawer);

  els.preOpenChecklist.addEventListener("change", onPreOpenChecklistChange);
  els.openingPlanBody.addEventListener("click", onPlansTableClick);
  els.openingCancelQueue.addEventListener("click", onPlansTableClick);
  els.openingExitQueue.addEventListener("click", onRecordQueueClick);
  els.plansBody.addEventListener("click", onPlansTableClick);
  els.recordQueue.addEventListener("click", onRecordQueueClick);
  els.positionsBody.addEventListener("click", onPositionsTableClick);
  els.qualityBody.addEventListener("click", onQualityTableClick);
  els.openingWorkflowGuide.addEventListener("click", onWorkflowGuideClick);
}

function syncFormFromState() {
  els.apiBaseInput.value = state.apiBase;
  els.accountKeyInput.value = state.accountKey;
  els.accountIdInput.value = state.accountId;
  els.asOfDateInput.value = state.asOfDate;
  els.reviewDateInput.value = dateInputValue(state.asOfDate);
  els.marketReviewDateInput.value = dateInputValue(marketReviewDate());
  els.strategyHypothesisDateInput.value = dateInputValue(state.strategyHypothesisAsOfDate);
  els.strategyInput.value = state.strategyVersion;
  els.operatorInput.value = state.operator;
  els.writeTokenInput.value = state.writeToken;
  els.dryRunInput.checked = state.dryRun;
}

function readContextForm() {
  const previousPreOpenContext = preOpenContextKey();
  state.apiBase = els.apiBaseInput.value.trim().replace(/\/$/, "");
  state.accountKey = els.accountKeyInput.value.trim();
  state.accountId = els.accountIdInput.value.trim();
  state.asOfDate = normalizeDate(els.asOfDateInput.value);
  state.strategyVersion = els.strategyInput.value.trim() || DEFAULT_STRATEGY_VERSION;
  state.operator = els.operatorInput.value.trim();
  state.writeToken = els.writeTokenInput.value.trim();
  state.dryRun = els.dryRunInput.checked;
  state.reviewDatePinned = true;
  state.executionAsOfDate = "";
  state.executionDatePinned = false;
  if (preOpenContextKey() !== previousPreOpenContext) resetPreOpenChecks();
  syncFormFromState();
}

function persistContext() {
  localStorage.setItem("pgc.dashboard.apiBase", state.apiBase);
  localStorage.setItem("pgc.dashboard.accountKey", state.accountKey);
  localStorage.setItem("pgc.dashboard.accountId", state.accountId);
  localStorage.setItem("pgc.dashboard.asOfDate", state.asOfDate);
  localStorage.setItem("pgc.dashboard.strategyVersion", state.strategyVersion);
  localStorage.setItem("pgc.dashboard.operator", state.operator);
  localStorage.setItem("pgc.dashboard.writeToken", state.writeToken);
  localStorage.setItem("pgc.dashboard.dryRun", String(state.dryRun));
  if (state.executionDatePinned && state.executionAsOfDate) {
    localStorage.setItem("pgc.dashboard.executionAsOfDate", state.executionAsOfDate);
  } else {
    localStorage.removeItem("pgc.dashboard.executionAsOfDate");
  }
  if (state.marketDatePinned && state.marketAsOfDate) {
    localStorage.setItem("pgc.dashboard.marketAsOfDate", state.marketAsOfDate);
  } else {
    localStorage.removeItem("pgc.dashboard.marketAsOfDate");
  }
  if (state.strategyHypothesisAsOfDate) {
    localStorage.setItem("pgc.dashboard.strategyHypothesisAsOfDate", state.strategyHypothesisAsOfDate);
  } else {
    localStorage.removeItem("pgc.dashboard.strategyHypothesisAsOfDate");
  }
}

async function applyReviewDateInput() {
  await setReviewDate(els.reviewDateInput.value);
}

async function shiftReviewDate(offset) {
  const adjacent = adjacentReviewHistoryDate(offset);
  if (!adjacent) {
    showNotice(offset < 0 ? "没有更早的复盘历史。" : "没有更新的复盘历史。");
    renderReviewHistoryNavigation();
    return;
  }
  await setReviewDate(adjacent);
}

async function setLatestReviewDate() {
  const latestDate = latestReviewHistoryDate();
  if (!latestDate) {
    showNotice("暂无可用复盘历史。");
    renderReviewHistoryNavigation();
    return;
  }
  await setReviewDate(latestDate);
}

async function applyMarketReviewDateInput() {
  await setMarketReviewDate(els.marketReviewDateInput.value);
}

async function applyStrategyHypothesisDateInput() {
  const nextDate = normalizeDate(els.strategyHypothesisDateInput.value);
  if (nextDate && !/^\d{8}$/.test(nextDate)) {
    showNotice("假设日期需要选择有效日期。");
    syncFormFromState();
    return;
  }
  state.strategyHypothesisAsOfDate = nextDate;
  persistContext();
  await loadStrategyHypothesisWorkbenchAndRender();
}

async function clearStrategyHypothesisDateFilter() {
  state.strategyHypothesisAsOfDate = "";
  persistContext();
  syncFormFromState();
  await loadStrategyHypothesisWorkbenchAndRender();
}

async function shiftMarketReviewDate(offset) {
  const adjacent = adjacentMarketReviewDate(offset);
  if (!adjacent) {
    showNotice(offset < 0 ? "没有更早的全市场复盘历史。" : "没有更新的全市场复盘历史。");
    renderMarketReviewNavigation();
    return;
  }
  await setMarketReviewDate(adjacent);
}

async function setLatestMarketReviewDate() {
  const latestDate = latestMarketReviewDate();
  if (!latestDate) {
    showNotice("暂无可用全市场复盘历史。");
    renderMarketReviewNavigation();
    return;
  }
  await setMarketReviewDate(latestDate);
}

async function followReviewDateForMarket() {
  state.marketAsOfDate = "";
  state.marketDatePinned = false;
  persistContext();
  syncFormFromState();
  await loadMarketReviewAndRender();
}

async function setMarketReviewDate(value) {
  const nextDate = normalizeDate(value);
  if (!/^\d{8}$/.test(nextDate)) {
    showNotice("全市场复盘日需要选择有效日期。");
    syncFormFromState();
    renderMarketReviewNavigation();
    return;
  }
  if (nextDate === marketReviewDate() && state.marketDatePinned) {
    renderMarketReviewNavigation();
    return;
  }
  state.marketAsOfDate = nextDate;
  state.marketDatePinned = true;
  persistContext();
  syncFormFromState();
  await loadMarketReviewAndRender();
}

async function setReviewDate(value, options = {}) {
  const nextDate = normalizeDate(value);
  if (!/^\d{8}$/.test(nextDate)) {
    showNotice("复盘日需要选择有效日期。");
    syncFormFromState();
    renderReviewHistoryNavigation();
    return;
  }
  if (nextDate === state.asOfDate) {
    renderReviewHistoryNavigation();
    return;
  }
  if (options.preserveExecutionDate !== false) lockExecutionDate(executionDate());
  state.asOfDate = nextDate;
  state.reviewDatePinned = true;
  syncFormFromState();
  persistContext();
  setActivePage("review");
  await refreshAll({ autoLatest: false });
}

async function refreshAll(options = {}) {
  setBusy(true);
  if (!options.keepNotice) showNotice("");
  try {
    await Promise.all([loadReviewHistory(), loadReviewTimeline()]);
    if (shouldAdoptLatestReviewDate(options)) {
      state.asOfDate = latestReviewHistoryDate();
      resetPreOpenChecks();
      syncFormFromState();
      persistContext();
    }
    await loadDailyReport();
    await Promise.all([
      loadPlans(),
      loadQuality(),
      loadPositions(),
      loadMarketReview(),
      loadOpenExecution(),
      loadNextDayDecision(),
      loadPaperAcceptance(),
      loadPaperAcceptanceHistory(),
      loadOpsHistory(),
      loadStrategyHypothesisWorkbench(),
    ]);
    renderAll();
  } catch (error) {
    showNotice(error.message || String(error));
    renderAll();
  } finally {
    setBusy(false);
  }
}

async function loadDailyReport() {
  const params = new URLSearchParams();
  params.set("strategy_version", state.strategyVersion);
  if (state.accountId) {
    params.set("account_id", state.accountId);
  } else if (state.accountKey) {
    params.set("account_key", state.accountKey);
  }
  const envelope = await apiRequest(`/api/daily-reviews/${state.asOfDate}?${params.toString()}`);
  state.reportEnvelope = envelope;
  state.report = envelope.data || null;
  syncExecutionDateFromReport();
}

async function loadNextDayDecision() {
  const params = new URLSearchParams();
  params.set("strategy_version", state.strategyVersion);
  params.set("request_id", requestId("next-day-decision"));
  const accountId = resolvedAccountId();
  if (accountId) {
    params.set("account_id", accountId);
  } else if (state.accountKey) {
    params.set("account_key", state.accountKey);
  } else {
    state.nextDayDecision = state.report?.next_day_decision || null;
    state.nextDayDecisionEnvelope = null;
    return;
  }
  const envelope = await apiRequest(`/api/next-day-decision-cockpit/${state.asOfDate}?${params.toString()}`);
  state.nextDayDecisionEnvelope = envelope;
  state.nextDayDecision = envelope.data || state.report?.next_day_decision || null;
}

async function loadPaperAcceptance() {
  const params = new URLSearchParams();
  params.set("strategy_version", state.strategyVersion);
  params.set("request_id", requestId("paper-acceptance"));
  const accountId = resolvedAccountId();
  if (accountId) {
    params.set("account_id", accountId);
  } else if (state.accountKey) {
    params.set("account_key", state.accountKey);
  } else {
    state.paperAcceptance = state.report?.paper_acceptance || null;
    state.paperAcceptanceEnvelope = null;
    return;
  }
  const envelope = await apiRequest(`/api/paper-acceptance/${state.asOfDate}?${params.toString()}`);
  state.paperAcceptanceEnvelope = envelope;
  state.paperAcceptance = envelope.data || state.report?.paper_acceptance || null;
}

async function loadPaperAcceptanceHistory() {
  const params = new URLSearchParams();
  params.set("strategy_version", state.strategyVersion);
  params.set("limit", "10");
  params.set("request_id", requestId("paper-acceptance-history"));
  const accountId = resolvedAccountId();
  if (accountId) {
    params.set("account_id", accountId);
  } else if (state.accountKey) {
    params.set("account_key", state.accountKey);
  } else {
    state.paperAcceptanceHistory = null;
    state.paperAcceptanceHistoryEnvelope = null;
    return;
  }
  const envelope = await apiRequest(`/api/paper-acceptance-history?${params.toString()}`);
  state.paperAcceptanceHistoryEnvelope = envelope;
  state.paperAcceptanceHistory = envelope.data || null;
}

async function loadOpsHistory() {
  const params = new URLSearchParams();
  params.set("strategy_version", state.strategyVersion);
  params.set("limit", "50");
  params.set("request_id", requestId("ops-history"));
  const accountId = resolvedAccountId();
  if (accountId) {
    params.set("account_id", accountId);
  } else if (state.accountKey) {
    params.set("account_key", state.accountKey);
  } else {
    state.opsHistory = null;
    state.opsHistoryEnvelope = null;
    return;
  }
  const envelope = await apiRequest(`/api/ops-history?${params.toString()}`);
  state.opsHistoryEnvelope = envelope;
  state.opsHistory = envelope.data || null;
}

async function loadReviewHistory() {
  const params = new URLSearchParams();
  params.set("strategy_version", state.strategyVersion);
  params.set("limit", "20");
  const accountId = resolvedAccountId();
  if (accountId) {
    params.set("account_id", accountId);
  } else if (state.accountKey) {
    params.set("account_key", state.accountKey);
  } else {
    state.reviewHistory = [];
    return;
  }
  const envelope = await apiRequest(`/api/daily-reviews?${params.toString()}`);
  if (envelope.status !== "success") {
    throw new Error(errorMessages(envelope).join("；") || "无法读取复盘历史列表。");
  }
  state.reviewHistory = envelope.data?.items || [];
}

async function loadReviewTimeline() {
  const params = new URLSearchParams();
  params.set("strategy_version", state.strategyVersion);
  params.set("limit", "20");
  const accountId = resolvedAccountId();
  if (accountId) {
    params.set("account_id", accountId);
  } else if (state.accountKey) {
    params.set("account_key", state.accountKey);
  } else {
    state.reviewTimeline = [];
    state.reviewTimelineEnvelope = null;
    return;
  }
  const envelope = await apiRequest(`/api/review-timeline?${params.toString()}`);
  if (envelope.status !== "success") {
    throw new Error(errorMessages(envelope).join("；") || "无法读取跨日复盘对比。");
  }
  state.reviewTimelineEnvelope = envelope;
  state.reviewTimeline = envelope.data?.items || [];
}

async function loadOpenExecution() {
  const accountId = resolvedAccountId();
  if (!accountId && !state.accountKey) {
    state.openExecution = null;
    state.openExecutionEnvelope = null;
    return;
  }
  const params = new URLSearchParams();
  params.set("as_of_date", executionDate());
  params.set("request_id", requestId("open-execution"));
  if (accountId) {
    params.set("account_id", accountId);
  } else if (state.accountKey) {
    params.set("account_key", state.accountKey);
  }
  const envelope = await apiRequest(`/api/open-execution?${params.toString()}`);
  state.openExecutionEnvelope = envelope;
  state.openExecution = envelope.data || null;
}

async function loadMarketReview() {
  const asOfDate = marketReviewDate();
  const contextPath = marketPlanContextApiPath(asOfDate);
  const [
    historyEnvelope,
    reviewEnvelope,
    sectorsEnvelope,
    externalEnvelope,
    hypothesesEnvelope,
    planContextEnvelope,
  ] = await Promise.all([
    apiRequest("/api/market-reviews?limit=20"),
    apiRequest(`/api/market-reviews/${asOfDate}`),
    apiRequest(`/api/market-reviews/${asOfDate}/sectors`),
    apiRequest(`/api/market-reviews/${asOfDate}/external-items`),
    apiRequest(`/api/market-reviews/${asOfDate}/hypotheses?limit=20`),
    apiRequest(contextPath),
  ]);
  state.marketReviewHistory = historyEnvelope.data?.reviews || [];
  state.marketReviewEnvelope = reviewEnvelope;
  state.marketReview = reviewEnvelope.data || null;
  state.marketSectorsEnvelope = sectorsEnvelope;
  state.marketSectors = sectorsEnvelope.data?.sectors || [];
  state.marketExternalEnvelope = externalEnvelope;
  state.marketExternalItems = externalEnvelope.data?.items || [];
  state.marketHypothesesEnvelope = hypothesesEnvelope;
  state.marketHypotheses = hypothesesEnvelope.data?.hypotheses || [];
  state.marketPlanContextEnvelope = planContextEnvelope;
  state.marketPlanContexts = planContextEnvelope.data?.contexts || [];
}

async function loadStrategyHypothesisWorkbench() {
  const params = new URLSearchParams();
  params.set("limit", "50");
  const status = els.strategyHypothesisStatusFilter.value;
  if (status) params.set("status", status);
  const asOfDate = normalizeDate(state.strategyHypothesisAsOfDate);
  if (/^\d{8}$/.test(asOfDate)) params.set("as_of_date", asOfDate);
  const envelope = await apiRequest(`/api/strategy-hypotheses/workbench?${params.toString()}`);
  state.strategyHypothesisWorkbenchEnvelope = envelope;
  state.strategyHypothesisWorkbench = envelope.data || null;
}

function latestReviewHistoryDate() {
  const dates = reviewHistoryDates();
  return dates.length ? dates[dates.length - 1] : "";
}

function reviewHistoryDates() {
  return [...new Set((state.reviewHistory || [])
    .map((item) => normalizeDate(item.review_date))
    .filter((value) => /^\d{8}$/.test(value)))]
    .sort();
}

function adjacentReviewHistoryDate(offset) {
  const dates = reviewHistoryDates();
  const current = normalizeDate(state.asOfDate);
  if (!dates.length || !/^\d{8}$/.test(current)) return "";
  if (offset < 0) {
    return [...dates].reverse().find((date) => date < current) || "";
  }
  return dates.find((date) => date > current) || "";
}

function shouldAdoptLatestReviewDate(options = {}) {
  if (options.autoLatest === false || state.reviewDatePinned) return false;
  const latestDate = latestReviewHistoryDate();
  return Boolean(latestDate && /^\d{8}$/.test(state.asOfDate) && latestDate > state.asOfDate);
}

async function loadPlans() {
  const params = new URLSearchParams();
  const accountId = resolvedAccountId();
  if (accountId) params.set("account_id", accountId);
  if (state.accountKey) params.set("account_key", state.accountKey);
  if (!accountId && !state.accountKey) {
    state.tradePlans = [];
    return;
  }
  params.set("limit", "100");
  const envelope = await apiRequest(`/api/trade-plans?${params.toString()}`);
  state.tradePlans = envelope.data?.trade_plans || [];
}

async function loadQuality() {
  const params = new URLSearchParams();
  params.set("status", "open");
  params.set("trade_date", state.asOfDate);
  if (els.qualitySeverityFilter.value) params.set("severity", els.qualitySeverityFilter.value);
  const envelope = await apiRequest(`/api/data-quality?${params.toString()}`);
  state.qualityEvents = Array.isArray(envelope.data) ? envelope.data : [];
}

async function loadPositions() {
  const accountId = resolvedAccountId();
  if (!accountId) {
    state.positions = [];
    return;
  }
  const params = new URLSearchParams();
  params.set("as_of_date", state.asOfDate);
  const envelope = await apiRequest(`/api/accounts/${accountId}/positions?${params.toString()}`);
  state.positions = envelope.data?.positions || [];
}

async function loadPlansAndRender() {
  await runWithNotice(async () => {
    await loadPlans();
    renderOpeningExecution();
    renderPlans();
    renderBadges();
  });
}

async function loadQualityAndRender() {
  await runWithNotice(async () => {
    await loadQuality();
    renderOpeningExecution();
    renderQuality();
    renderStatusBand();
    renderBadges();
  });
}

async function loadPositionsAndRender() {
  await runWithNotice(async () => {
    await loadPositions();
    renderOpeningExecution();
    renderPositions();
    renderDuePositions();
    renderBadges();
  });
}

async function loadReviewHistoryAndRender() {
  await runWithNotice(async () => {
    await Promise.all([loadReviewHistory(), loadReviewTimeline()]);
    renderReviewTimeline();
    renderReviewHistory();
  });
}

async function loadPaperAcceptanceAndRender() {
  await runWithNotice(async () => {
    await Promise.all([loadPaperAcceptance(), loadPaperAcceptanceHistory()]);
    renderPaperAcceptance();
    renderBadges();
  });
}

async function loadNextDayDecisionAndRender() {
  await runWithNotice(async () => {
    await loadNextDayDecision();
    renderNextDayDecision();
    renderBadges();
  });
}

async function loadOpsHistoryAndRender() {
  await runWithNotice(async () => {
    await loadOpsHistory();
    renderOpsHistory();
    renderBadges();
  });
}

async function loadMarketReviewAndRender() {
  await runWithNotice(async () => {
    await loadMarketReview();
    renderMarketReview();
    renderBadges();
  });
}

async function loadStrategyHypothesisWorkbenchAndRender() {
  await runWithNotice(async () => {
    await loadStrategyHypothesisWorkbench();
    renderStrategyHypothesisWorkbench();
    renderBadges();
  });
}

async function runWithNotice(task) {
  setBusy(true);
  showNotice("");
  try {
    await task();
  } catch (error) {
    showNotice(error.message || String(error));
  } finally {
    setBusy(false);
  }
}

async function runReview() {
  await runWithNotice(async () => {
    const ok = await confirmAction({
      title: "确认运行日终复盘",
      body: `将对复盘日 ${displayDate(state.asOfDate)} 运行日终复盘流程，可能生成候选和交易计划。`,
      details: writeConfirmationDetails({
        targetStock: reviewTargetText(),
        executionDay: state.report?.next_trade_date || executionDate(),
      }),
      submitLabel: confirmationSubmitLabel(),
    });
    if (!ok.confirmed) return;
    const payload = supportedWritePayload("review", {
      as_of_date: state.asOfDate,
      strategy_version: state.strategyVersion,
      force_new_review_run: false,
      max_daily_picks: 1,
      ...selectedAccountPayload(),
    });
    const envelope = await apiRequest("/api/review-runs", { method: "POST", body: payload });
    handleMutationEnvelope(envelope, mutationSuccessText("复盘请求已完成", "复盘 dry run 成功，未写入复盘结果。"));
    await refreshAll({ keepNotice: true });
  });
}

async function publishPlan(tradePlanId) {
  if (hasBlockingQuality()) {
    showNotice("存在数据质量 blocker，不能发布计划。");
    return;
  }
  const plan = selectedRecordPlan(tradePlanId);
  const ok = await confirmAction({
    title: "确认发布计划",
    body: `计划 ${tradePlanId} 将进入 active 状态。此操作不支持 dry run。`,
    details: writeConfirmationDetails({
      targetStock: planStockText(plan),
      planId: tradePlanId,
      executionDay: planTradeDate(plan) || executionDate(),
      dryRunSupported: false,
      applyOnly: true,
    }),
    submitLabel: confirmationSubmitLabel(true),
  });
  if (!ok.confirmed) return;
  await runWithNotice(async () => {
    const payload = requiredWritePayload(`publish:${tradePlanId}`, selectedAccountPayload());
    const envelope = await apiRequest(`/api/trade-plans/${tradePlanId}/publish`, {
      method: "POST",
      body: payload,
    });
    handleMutationEnvelope(envelope, "计划发布请求已完成");
    await refreshAll({ keepNotice: true });
  });
}

async function cancelPlan(tradePlanId) {
  const plan = selectedRecordPlan(tradePlanId);
  const ok = await confirmAction({
    title: "确认取消计划",
    body: `计划 ${tradePlanId} 将被标记为 cancelled。此操作不支持 dry run。`,
    inputLabel: "取消原因",
    quickChoices: CANCEL_REASON_CHOICES,
    details: writeConfirmationDetails({
      targetStock: planStockText(plan),
      planId: tradePlanId,
      executionDay: planTradeDate(plan) || executionDate(),
      dryRunSupported: false,
      applyOnly: true,
    }),
    submitLabel: confirmationSubmitLabel(true),
  });
  if (!ok.confirmed) return;
  const cancelReason = ok.value.trim();
  if (!cancelReason) {
    showNotice("取消计划需要填写原因。");
    return;
  }
  await runWithNotice(async () => {
    const payload = requiredWritePayload(`cancel:${tradePlanId}`, {
      ...selectedAccountPayload(),
      cancel_reason: cancelReason,
    });
    const envelope = await apiRequest(`/api/trade-plans/${tradePlanId}/cancel`, {
      method: "POST",
      body: payload,
    });
    handleMutationEnvelope(envelope, "计划取消请求已完成");
    await refreshAll({ keepNotice: true });
  });
}

async function submitTradeRecord(event) {
  event.preventDefault();
  await runWithNotice(async () => {
    const recordBlockers = recordFormIssues().filter((issue) => issue.severity === "blocker");
    if (recordBlockers.length) {
      throw new Error(recordBlockers.map((issue) => issue.text).join("；"));
    }
    const tradePlanId = parseOptionalInt(els.recordPlanId.value);
    const positionId = parseOptionalInt(els.recordPositionId.value);
    if (tradePlanId && positionId) {
      throw new Error("计划 ID 和持仓 ID 只能填写一个。");
    }
    if (!tradePlanId && !positionId) {
      throw new Error("成交录入需要计划 ID 或持仓 ID。");
    }
    if (tradePlanId) {
      const plan = findPlan(tradePlanId) || (state.report?.buy_plan?.trade_plan_id === tradePlanId ? planFromReport(state.report.buy_plan) : null);
      if (hasBlockingQuality()) {
        throw new Error("存在数据质量 blocker，不能录入计划成交。");
      }
      if (plan && plan.status !== "active") {
        throw new Error("只有 active 计划才能录入成交。");
      }
    }
    const basePayload = {
      trade_plan_id: tradePlanId || undefined,
      position_id: positionId || undefined,
      side: positionId ? undefined : els.recordSide.value,
      executed_date: normalizeDate(els.recordDate.value),
      executed_price: numericValue(els.recordPrice.value, "成交价"),
      shares: integerValue(els.recordShares.value, "股数"),
      fee: optionalNumber(els.recordFee.value) ?? 0,
      tax: optionalNumber(els.recordTax.value) ?? 0,
      slippage: optionalNumber(els.recordSlippage.value),
      source: "manual",
      ...selectedAccountPayload(),
    };
    const recordPlan = tradePlanId ? selectedRecordPlan(tradePlanId) : null;
    const recordPosition = positionId ? findPosition(positionId) : null;
    const targetStock = recordPlan ? planStockText(recordPlan) : positionStockText(recordPosition);
    const recordSideText = positionId || basePayload.side === "sell" ? "卖出" : "买入";
    const ok = await confirmAction({
      title: recordSideText === "卖出" ? "确认记录卖出成交" : "确认记录买入成交",
      body: `将记录 ${displayDate(basePayload.executed_date)} 的人工纸面${recordSideText}成交：${numberText(basePayload.executed_price, 4)} 元 / ${integerText(basePayload.shares)} 股。Dashboard 不会向券商下单。`,
      details: writeConfirmationDetails({
        targetStock,
        planId: tradePlanId,
        positionId,
        executionDay: basePayload.executed_date,
      }),
      submitLabel: confirmationSubmitLabel(),
    });
    if (!ok.confirmed) return;
    const payload = supportedWritePayload(`trade:${tradePlanId || positionId}`, basePayload);
    const envelope = await apiRequest("/api/trades", { method: "POST", body: payload });
    handleMutationEnvelope(envelope, mutationSuccessText(
      "成交录入请求已完成，持仓和计划状态已刷新。",
      "成交录入 dry run 成功，未写入持仓；关闭 Dry run 且服务端开启写入后才会落库。",
    ));
    clearRecordForm();
    await refreshAll({ keepNotice: true });
  });
}

async function evaluateExits() {
  await runWithNotice(async () => {
    const due = duePositions();
    const ok = await confirmAction({
      title: "确认评估退出",
      body: `将对复盘日 ${displayDate(state.asOfDate)} 到期持仓生成退出决策/卖出计划，不会记录卖出成交。`,
      details: writeConfirmationDetails({
        targetStock: due.length ? due.map(positionStockText).join("；") : "到期持仓",
        positionId: due.length === 1 ? due[0].position_id : due.length ? due.map((position) => position.position_id).join(", ") : "",
        executionDay: state.asOfDate,
      }),
      submitLabel: confirmationSubmitLabel(),
    });
    if (!ok.confirmed) return;
    const payload = supportedWritePayload("exits", {
      as_of_date: state.asOfDate,
      generate_sell_plans: true,
      ...selectedAccountPayload(),
    });
    const envelope = await apiRequest("/api/exits/evaluate", { method: "POST", body: payload });
    handleMutationEnvelope(envelope, mutationSuccessText("退出评估请求已完成", "退出评估 dry run 成功，未写入退出决策/计划。"));
    await refreshAll({ keepNotice: true });
  });
}

async function reviewStrategyVersionProposal(evaluation, decision) {
  const hypothesis = evaluation?.hypothesis || {};
  const proposal = latestStrategyVersionProposal(evaluation);
  if (!hypothesis.hypothesis_id || !decision) return;
  if (!proposal) {
    showNotice("没有可审阅的 strategy-version proposal artifact。");
    return;
  }
  const ok = await confirmAction({
    title: proposalReviewConfirmTitle(decision),
    body: proposalReviewConfirmBody(decision, hypothesis),
    inputLabel: "Review note",
    quickChoices: proposalReviewQuickChoices(decision),
    details: [
      ["假设 ID", hypothesis.hypothesis_id],
      ["Proposal key", proposal?.proposal_key || "-"],
      ["Proposal artifact", proposal?.path || "-"],
      ["Artifact-only", "不会写 strategy_versions、active params、trade_plans、trades、positions 或 paper/live 行为"],
      ["Dry-run / Apply", state.dryRun ? "Dry run：只预演 artifact" : "Apply：仅写 proposal review / promotion-request artifact"],
      ["操作者要求", state.dryRun ? `dry-run 可预演；apply 必填：${state.operator || "未填写"}` : `apply 必填：${state.operator || "未填写"}`],
    ],
    submitLabel: confirmationSubmitLabel(),
  });
  if (!ok.confirmed) return;
  await runWithNotice(async () => {
    const payload = supportedWritePayload(`strategy-proposal-review:${hypothesis.hypothesis_id}:${decision}`, {
      hypothesis_id: Number(hypothesis.hypothesis_id),
      decision,
      review_note: ok.value.trim() || proposalReviewDefaultNote(decision),
      proposal_artifact_path: proposal?.path,
    });
    const envelope = await apiRequest("/api/strategy-hypotheses/proposal-reviews", {
      method: "POST",
      body: payload,
    });
    handleMutationEnvelope(envelope, mutationSuccessText(
      "Proposal review artifact 已写入；策略版本和交易状态未改变。",
      "Proposal review dry run 成功，未写入 artifact、策略版本或交易状态。",
    ));
    await loadStrategyHypothesisWorkbenchAndRender();
  });
}

function handleMutationEnvelope(envelope, successText) {
  if (envelope.status !== "success" && envelope.status !== "skipped") {
    const messages = errorMessages(envelope).join("；") || `请求状态：${envelope.status}`;
    throw new Error(messages);
  }
  showNotice(successText, "ok");
}

function mutationSuccessText(writeText, dryRunText) {
  return state.dryRun ? dryRunText : writeText;
}

function writeConfirmationDetails({ targetStock = "-", planId = "", positionId = "", executionDay = executionDate(), dryRunSupported = true, applyOnly = false } = {}) {
  const idText = planId
    ? `计划 ${planId}`
    : positionId
      ? `持仓 ${positionId}`
      : "-";
  const operatorText = applyOnly || !state.dryRun
    ? `apply 必填：${state.operator || "未填写"}`
    : `dry-run 可预演；apply 必填：${state.operator || "未填写"}`;
  const modeText = applyOnly
    ? "Apply：此操作不支持 dry run"
    : state.dryRun
      ? "Dry run：预演不落库"
      : "Apply：服务端开启写入时会落库";
  return [
    ["账户", accountContextText()],
    ["复盘日", displayDate(state.asOfDate)],
    ["执行日", displayDate(executionDay)],
    ["目标股票", targetStock || "-"],
    ["计划/持仓 ID", idText],
    ["操作者要求", operatorText],
    ["Dry-run / Apply", dryRunSupported ? modeText : "Apply：此操作不支持 dry run"],
  ];
}

function accountContextText() {
  const account = state.report?.account;
  const parts = [];
  if (state.accountKey || account?.account_key) parts.push(`key=${state.accountKey || account.account_key}`);
  if (resolvedAccountId()) parts.push(`id=${resolvedAccountId()}`);
  return parts.join(" / ") || "-";
}

function confirmationSubmitLabel(applyOnly = false) {
  if (applyOnly) return "确认 apply";
  return state.dryRun ? "确认 dry run" : "确认 apply";
}

function renderAll() {
  renderOpeningExecution();
  renderStatusBand();
  renderReviewTimeline();
  renderReviewHistory();
  renderReviewScopeMarkers();
  renderReview();
  renderNextDayDecision();
  renderPaperAcceptance();
  renderOpsHistory();
  renderMarketReview();
  renderStrategyHypothesisWorkbench();
  renderPlans();
  renderRecordQueue();
  renderPositions();
  renderQuality();
  renderAgent();
  renderBadges();
}

function renderOpeningExecution() {
  const blocked = hasBlockingQuality();
  const executionPlanPanel = document.querySelector(".execution-plan-panel");
  const executionPlans = todaysBuyPlans();
  const activePlans = executionPlans.filter((plan) => plan.status === "active");
  const visiblePlans = executionPlans.length ? executionPlans : activeBuyPlans();
  const executionDay = executionDate();
  const readiness = openingReadiness(activePlans, executionDay, blocked);

  renderOpeningWorkflowGuide(readiness, executionPlans, executionDay);
  executionPlanPanel.classList.toggle("blocked", blocked);
  executionPlanPanel.classList.toggle("idle", !blocked && activePlans.length === 0);
  els.openingBlockerChip.textContent = blocked ? "数据阻断" : activePlans.length ? "可执行" : "无 active 买入计划";
  els.openingBlockerChip.className = `chip ${blocked ? "chip-red" : activePlans.length ? "chip-green" : "chip-neutral"}`;
  renderOpeningReadinessSummary(readiness);
  renderPaperPromotionScorecard();

  if (blocked) {
    const blockers = blockingEvents().slice(0, 2).map((item) => escapeHtml(item.message || item.code || "数据阻断")).join("；");
    const ledgerCount = ledgerBlockerCount();
    els.openingPlanBody.innerHTML = `
      <h3 class="action-title">数据质量 / 账本 blocker，买入执行按钮已禁用</h3>
      <p class="muted">${blockers || "请先处理数据质量页面中的 blocker。"}</p>
      ${ledgerCount ? `<p class="ledger-blocker-note">账本 invariant blocker 未清除前，发布、取消和成交录入会保持锁定。</p>` : ""}
      ${actionMetrics([
        ["执行日", displayDate(executionDay)],
        ["active 买入计划", String(activePlans.length)],
        ["阻断数", String(blockingEvents().length)],
        ["账本 blocker", String(ledgerCount)],
        ["账户容量", capacityText(state.report?.account)],
      ])}
    `;
  } else if (visiblePlans.length) {
    const advisory = executionPlans.length
      ? ""
      : `<p class="execution-advisory">没有计划交易日匹配执行日 ${displayDate(executionDay)} 的买入计划；下方仅展示其他未完成计划，录入按钮已锁定。</p>`;
    els.openingPlanBody.innerHTML = `${advisory}${visiblePlans.map((plan) => openingPlanCard(plan, executionDay)).join("")}`;
  } else {
    els.openingPlanBody.innerHTML = emptyState(`没有计划交易日为 ${displayDate(executionDay)} 的 active 买入计划。`);
  }

  renderPreOpenChecklist(activePlans, executionDay, blocked, readiness);
  renderOpeningCancelQueue();
  renderOpeningExitQueue();
}

function renderOpeningWorkflowGuide(readiness, executionPlans, executionDay) {
  const guidance = state.openExecution
    ? openExecutionGuidance(state.openExecution, readiness, executionPlans, executionDay)
    : openingWorkflowGuidance(readiness, executionPlans, executionDay);
  els.openingWorkflowGuide.className = `execution-command-center execution-command-center--${guidance.tone}`;
  els.openingWorkflowGuide.innerHTML = `
    <div class="workflow-guide__main">
      <span class="workflow-guide__kicker">今日操作导引 · 执行日 ${displayDate(executionDay)}</span>
      <h2>${escapeHtml(guidance.title)}</h2>
      <p>${escapeHtml(guidance.detail)}</p>
    </div>
    <div class="workflow-guide__facts">
      ${workflowFact("今天该做什么", guidance.what, guidance.whatTone)}
      ${workflowFact("为什么不能做", guidance.why, guidance.whyTone)}
      ${workflowFact("下一步点哪里", guidance.next, guidance.nextTone)}
      ${workflowFact("市场计划关系", guidance.marketContext || "未关联 market-plan context", guidance.marketContextTone || "idle")}
    </div>
    <div class="workflow-guide__actions">
      ${guidance.actions.map(workflowActionButton).join("")}
    </div>
  `;
}

function openExecutionGuidance(openExecution, readiness, executionPlans, executionDay) {
  const target = openExecutionTargetText(openExecution);
  const marketContext = marketPlanContextExecutionText(openExecution.market_plan_context);
  const marketContextTone = marketPlanContextExecutionTone(openExecution.market_plan_context);
  const contextFields = { marketContext, marketContextTone };

  if (openExecution.status === "blocked" || openExecution.next_action === "blocked") {
    const reason = (openExecution.blocked_reasons || [])[0] || errorMessages(state.openExecutionEnvelope).join("；") || "账本 invariant blocker 未处理。";
    return {
      ...contextFields,
      tone: "blocked",
      title: "今天先处理账本或数据阻断",
      detail: reason,
      what: "暂停开盘执行动作",
      why: reason,
      next: "检查数据质量和账本审计后刷新执行台",
      whatTone: "blocked",
      whyTone: "blocked",
      nextTone: "action",
      actions: [
        { label: "查看数据质量", action: "quality", primary: true },
        { label: "刷新执行台", action: "refresh" },
      ],
    };
  }

  if (readiness.blocked) {
    return {
      ...openingWorkflowGuidance(readiness, executionPlans, executionDay),
      ...contextFields,
    };
  }

  if (openExecution.next_action === "record_sell") {
    return {
      ...contextFields,
      tone: "ready",
      title: `按 active 退出计划录入 ${target} 卖出成交`,
      detail: "退出计划来自持仓生命周期；成交录入仍需人工确认日期、价格、股数和写入凭证。",
      what: `${displayDate(executionDay)} 录入人工纸面卖出成交`,
      why: "open-execution 找到执行日匹配的 active 卖出计划",
      next: "点“录入卖出成交”进入成交录入页",
      whatTone: "ready",
      whyTone: "ready",
      nextTone: "action",
      actions: [
        { label: "录入卖出成交", action: "record-plan", planId: openExecution.primary_plan_id, primary: true },
        { label: "查看交易计划", action: "plans" },
      ],
    };
  }

  if (openExecution.next_action === "record_buy" && readiness.manualComplete) {
    return {
      ...contextFields,
      tone: "ready",
      title: `按 active 计划录入 ${target} 买入成交`,
      detail: "开盘检查已完成；market-plan context 只给提示，不会自动取消或执行计划。",
      what: `${displayDate(executionDay)} 录入人工纸面买入成交`,
      why: "open-execution 找到执行日匹配的 active 买入计划",
      next: "点“录入买入成交”进入成交录入页",
      whatTone: "ready",
      whyTone: "ready",
      nextTone: "action",
      actions: [
        { label: "录入买入成交", action: "record-plan", planId: openExecution.primary_plan_id, primary: true },
        { label: "查看计划详情", action: "plan-detail", planId: openExecution.primary_plan_id },
      ],
    };
  }

  if (openExecution.next_action === "record_buy") {
    const unchecked = uncheckedPreOpenLabels();
    return {
      ...contextFields,
      tone: "waiting",
      title: "先完成开盘检查，再录入买入成交",
      detail: unchecked.length ? `待确认：${unchecked.join("、")}。` : "待确认开盘检查项。",
      what: `核对 ${target} 的开盘可交易条件`,
      why: "open-execution 已找到 active 买入计划，但人工开盘检查未完成",
      next: "点“定位检查清单”，逐项确认后再点录入",
      whatTone: "warning",
      whyTone: "blocked",
      nextTone: "action",
      actions: [
        { label: "定位检查清单", action: "checklist", primary: true },
        { label: "查看计划详情", action: "plan-detail", planId: openExecution.primary_plan_id },
      ],
    };
  }

  if (openExecution.next_action === "evaluate_exit") {
    return {
      ...contextFields,
      tone: "waiting",
      title: `今天优先评估 ${target} 的退出动作`,
      detail: "open-execution 找到 T+2 / T+5 到期待处理持仓；评估按钮仍走显式写入确认。",
      what: `${displayDate(executionDay)} 评估退出并按实际成交录入卖出`,
      why: "存在到期待处理持仓，尚未生成执行日卖出计划",
      next: "点“评估退出”生成决策/计划，或直接进入卖出录入",
      whatTone: "warning",
      whyTone: "ready",
      nextTone: "action",
      actions: [
        { label: "评估退出", action: "exits", primary: true },
        { label: "卖出录入", action: "record-position", positionId: openExecution.primary_position_id },
      ],
    };
  }

  if (openExecution.next_action === "wait") {
    return {
      ...contextFields,
      tone: "idle",
      title: "有 active 计划，但还没到执行日",
      detail: `下一计划交易日：${displayDate(openExecution.planned_trade_date)}。`,
      what: "等待计划交易日，不错日录入",
      why: "open-execution 未找到今天到期的 active 执行计划",
      next: "点“查看交易计划”核对具体日期",
      whatTone: "idle",
      whyTone: "blocked",
      nextTone: "action",
      actions: [
        { label: "查看交易计划", action: "plans", primary: true },
        { label: "刷新执行台", action: "refresh" },
      ],
    };
  }

  return {
    ...contextFields,
    tone: "idle",
    title: "今天没有主动买入或退出任务",
    detail: "open-execution 没有找到执行日计划或到期持仓。",
    what: "保留观察，必要时刷新复盘和计划列表",
    why: "没有 active 计划、卖出计划或 T+2 / T+5 退出任务",
    next: "点“查看每日复盘”确认无候选原因",
    whatTone: "idle",
    whyTone: "ready",
    nextTone: "action",
    actions: [
      { label: "查看每日复盘", action: "review", primary: true },
      { label: "刷新执行台", action: "refresh" },
    ],
  };
}

function openingWorkflowGuidance(readiness, executionPlans, executionDay) {
  const report = state.report;
  const due = duePositions();
  const draftExecutionPlans = executionPlans.filter((plan) => plan.status === "draft");
  const activeExecutionPlans = executionPlans.filter((plan) => plan.status === "active");
  const reportPlan = report?.buy_plan ? planFromReport(report.buy_plan) : null;
  const reportPlanMatchesExecutionDay = reportPlan && planTradeDate(reportPlan) === executionDay;
  const firstDraftPlan = draftExecutionPlans[0] || (reportPlanMatchesExecutionDay && reportPlan.status === "draft" ? reportPlan : null);
  const firstActivePlan = activeExecutionPlans[0] || (reportPlanMatchesExecutionDay && reportPlan.status === "active" ? reportPlan : null);
  const firstDuePosition = due[0];

  if (!report) {
    return {
      tone: "blocked",
      title: "先确认上下文，执行台还没有可用复盘报告",
      detail: "复盘报告读取失败时，不判断买入、卖出或持仓动作。",
      what: "检查账户、复盘日、策略版本和 API Base",
      why: "缺少复盘报告，无法确认执行日和计划状态",
      next: "点“刷新执行台”，仍失败时调整左侧页面上下文",
      whatTone: "warning",
      whyTone: "blocked",
      nextTone: "action",
      actions: [
        { label: "刷新执行台", action: "refresh", primary: true },
        { label: "检查上下文", action: "context" },
      ],
    };
  }

  if (readiness.blocked) {
    const reason = primaryBlockerReason();
    return {
      tone: "blocked",
      title: "今天先处理数据阻断，暂不做买入录入",
      detail: reason,
      what: "处理 open 数据质量 blocker",
      why: reason,
      next: "点“查看数据质量”，处理后回到执行台刷新",
      whatTone: "blocked",
      whyTone: "blocked",
      nextTone: "action",
      actions: [
        { label: "查看数据质量", action: "quality", primary: true },
        { label: "刷新执行台", action: "refresh" },
      ],
    };
  }

  if (firstActivePlan && readiness.ready) {
    return {
      tone: "ready",
      title: `按 active 计划录入 ${planStockText(firstActivePlan)} 买入成交`,
      detail: "开盘检查已完成；提交前仍需按真实成交日期、价格和股数核对。",
      what: `${displayDate(executionDay)} 录入人工纸面买入成交`,
      why: "没有锁定项，Dashboard 只记录事实，不会向券商下单",
      next: "点“录入买入成交”进入成交录入页",
      whatTone: "ready",
      whyTone: "ready",
      nextTone: "action",
      actions: [
        { label: "录入买入成交", action: "record-plan", planId: firstActivePlan.id, primary: true },
        { label: "查看计划详情", action: "plan-detail", planId: firstActivePlan.id },
      ],
    };
  }

  if (firstActivePlan && !readiness.manualComplete) {
    const unchecked = uncheckedPreOpenLabels();
    return {
      tone: "waiting",
      title: "先完成开盘检查，再录入买入成交",
      detail: unchecked.length ? `待确认：${unchecked.join("、")}。` : "待确认开盘检查项。",
      what: `核对 ${planStockText(firstActivePlan)} 的开盘可交易条件`,
      why: "开盘检查未完成，买入录入按钮会保持锁定",
      next: "点“定位检查清单”，逐项确认后再点录入",
      whatTone: "warning",
      whyTone: "blocked",
      nextTone: "action",
      actions: [
        { label: "定位检查清单", action: "checklist", primary: true },
        { label: "查看计划详情", action: "plan-detail", planId: firstActivePlan.id },
      ],
    };
  }

  if (firstDraftPlan) {
    return {
      tone: "waiting",
      title: "今天有草稿计划，先发布为 active",
      detail: "成交录入只接受 active 计划；草稿计划不会进入开盘录入队列。",
      what: `${displayDate(executionDay)} 计划发布后再录入成交`,
      why: "计划仍是草稿，尚未成为可执行计划",
      next: "点“发布计划”，发布成功后完成开盘检查",
      whatTone: "warning",
      whyTone: "blocked",
      nextTone: "action",
      actions: [
        { label: "发布计划", action: "publish-plan", planId: firstDraftPlan.id, primary: true },
        { label: "查看交易计划", action: "plans" },
      ],
    };
  }

  if (firstDuePosition) {
    return {
      tone: "waiting",
      title: "今天优先处理到期持仓退出任务",
      detail: "没有匹配执行日的 active 买入计划，但存在 T+2 / T+5 到期待处理持仓。",
      what: `${displayDate(executionDay)} 评估退出并按实际成交录入卖出`,
      why: "买入计划缺失；退出任务来自当前持仓生命周期",
      next: "点“评估退出”生成退出决策/计划，或直接进入卖出录入",
      whatTone: "warning",
      whyTone: "ready",
      nextTone: "action",
      actions: [
        { label: "评估退出", action: "exits", primary: true },
        { label: "卖出录入", action: "record-position", positionId: firstDuePosition.position_id },
      ],
    };
  }

  if (executionPlans.length) {
    const statusSummary = executionPlans.map((plan) => `计划 ${plan.id}：${statusText(plan.status)}`).join("；");
    return {
      tone: "idle",
      title: "今天没有 active 买入待录入",
      detail: statusSummary,
      what: "核对今日计划状态，确认是否已执行、取消或过期",
      why: "没有 active 状态的执行日买入计划",
      next: "点“查看交易计划”检查状态和原因",
      whatTone: "idle",
      whyTone: "blocked",
      nextTone: "action",
      actions: [
        { label: "查看交易计划", action: "plans", primary: true },
        { label: "查看每日复盘", action: "review" },
      ],
    };
  }

  if (activeBuyPlans().some((plan) => plan.status === "active")) {
    return {
      tone: "idle",
      title: "存在 active 买入计划，但不是今天执行",
      detail: "当前 active 买入计划的计划交易日与执行日不一致，不能在今天录入。",
      what: "核对计划交易日，避免错日录入成交",
      why: "计划交易日与执行日不一致",
      next: "点“查看交易计划”核对具体日期",
      whatTone: "idle",
      whyTone: "blocked",
      nextTone: "action",
      actions: [
        { label: "查看交易计划", action: "plans", primary: true },
        { label: "查看每日复盘", action: "review" },
      ],
    };
  }

  if (report.candidate) {
    return {
      tone: "waiting",
      title: "有复盘候选，但今天还没有可执行计划",
      detail: "候选不等于成交计划；需要在每日复盘和交易计划中确认计划生成状态。",
      what: "检查候选是否已生成并发布计划",
      why: "没有计划交易日匹配执行日的 active 买入计划",
      next: "点“查看每日复盘”确认候选和计划血缘",
      whatTone: "warning",
      whyTone: "blocked",
      nextTone: "action",
      actions: [
        { label: "查看每日复盘", action: "review", primary: true },
        { label: "查看交易计划", action: "plans" },
      ],
    };
  }

  return {
    tone: "idle",
    title: "今天没有主动买入或退出任务",
    detail: `复盘状态：${reasonText(report.no_candidate_reason)}。`,
    what: "保留观察，必要时刷新复盘和计划列表",
    why: "没有候选、active 买入计划或 T+2 / T+5 退出任务",
    next: "点“查看每日复盘”确认无候选原因",
    whatTone: "idle",
    whyTone: "ready",
    nextTone: "action",
    actions: [
      { label: "查看每日复盘", action: "review", primary: true },
      { label: "刷新执行台", action: "refresh" },
    ],
  };
}

function workflowFact(label, value, tone) {
  return `
    <div class="workflow-guide__fact workflow-guide__fact--${tone || "idle"}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `;
}

function workflowActionButton(action) {
  const attrs = [
    `data-guidance-action="${escapeHtml(action.action)}"`,
    action.planId ? `data-plan-id="${escapeHtml(action.planId)}"` : "",
    action.positionId ? `data-position-id="${escapeHtml(action.positionId)}"` : "",
  ].filter(Boolean).join(" ");
  return `<button type="button" ${attrs} class="${action.primary ? "primary-button" : ""}">${escapeHtml(action.label)}</button>`;
}

function openExecutionTargetText(openExecution) {
  const stock = [openExecution?.target_stock, openExecution?.target_name].filter(Boolean).join(" ");
  if (stock) return stock;
  if (openExecution?.primary_plan_id) return `计划 ${openExecution.primary_plan_id}`;
  if (openExecution?.primary_position_id) return `持仓 ${openExecution.primary_position_id}`;
  return "当前标的";
}

function marketPlanContextExecutionText(context) {
  if (!context) return "未关联 market-plan context";
  const action = managementActionText(context.management_action);
  return `${alignmentText(context.alignment)} / ${riskText(context.risk_level)} / ${action}`;
}

function marketPlanContextExecutionTone(context) {
  if (!context) return "idle";
  if (context.management_action === "consider_cancel" || context.alignment === "conflict") return "blocked";
  if (context.management_action === "manual_review" || context.risk_level === "medium") return "warning";
  if (context.management_action === "proceed" && context.alignment === "aligned") return "ready";
  return "idle";
}

function primaryBlockerReason() {
  const blockers = blockingEvents();
  const first = blockers[0];
  const reason = first?.message || first?.code || "存在数据质量 blocker。";
  return blockers.length > 1 ? `${reason}（另有 ${blockers.length - 1} 项）` : reason;
}

function uncheckedPreOpenLabels() {
  const labels = {
    notSuspended: "未停牌 / 可交易",
    noMajorBadNews: "无重大利空",
    openNotExtremeHigh: "开盘未极端高开",
    cashSlotsChecked: "现金 / 仓位已核对",
  };
  return Object.entries(labels)
    .filter(([key]) => !state.preOpenChecks[key])
    .map(([, label]) => label);
}

function renderOpeningReadinessSummary(readiness) {
  const items = [
    ["数据质量", readiness.blocked ? `${readiness.blockerCount} blocker` : "可交易", readiness.blocked ? "danger" : "ready"],
    ["当日 active 计划", readiness.hasExecutionPlan ? `${readiness.matchingActiveCount} 个` : "缺失", readiness.hasExecutionPlan ? "ready" : "idle"],
    ["开盘检查", `${readiness.checkedCount}/${readiness.totalChecks}`, readiness.manualComplete && readiness.hasExecutionPlan ? "ready" : "waiting"],
    ["买入录入", readiness.ready ? "可录入" : "锁定", readiness.ready ? "ready" : "locked"],
  ];
  els.openingReadinessSummary.innerHTML = `
    <div class="readiness-title">
      <span>执行准备</span>
      ${chipHtml(readiness.ready ? "全部就绪" : readiness.lockReason, readiness.ready ? "chip-green" : readiness.blocked ? "chip-red" : "chip-amber")}
    </div>
    <div class="readiness-steps">
      ${items.map(([label, value, tone]) => `
        <div class="readiness-step readiness-step--${tone}">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(value)}</strong>
        </div>
      `).join("")}
    </div>
    <p>录入锁定原因：${escapeHtml(readiness.ready ? "无，仍需按实际成交价和股数核对后提交。" : readiness.lockReason)}</p>
  `;
}

function renderPaperPromotionScorecard() {
  const promotion = state.report?.paper_promotion;
  if (!promotion) {
    els.paperPromotionScorecard.innerHTML = emptyState("Paper 晋级分数卡暂无数据。");
    return;
  }
  const blockers = listValue(promotion.promotion_blockers);
  const warnings = listValue(promotion.promotion_warnings);
  const nextSteps = promotionNextSteps(promotion, blockers, warnings);
  const rows = [
    ["样本交易", integerText(promotion.trades_count), promotion.trades_count >= 10 ? "ready" : "waiting"],
    ["已闭环交易", integerText(promotion.closed_trades_count), promotion.closed_trades_count > 0 ? "ready" : "idle"],
    ["累计实现盈亏", money(promotion.realized_pnl), Number(promotion.realized_pnl || 0) >= 0 ? "ready" : "danger"],
    ["胜率", percent(promotion.win_rate), promotion.win_rate == null ? "idle" : "ready"],
    ["当前阻断", blockers.length ? blockers.join(" / ") : "无", blockers.length ? "danger" : "ready"],
    ["晋级 live 前还差什么", nextSteps, blockers.length ? "danger" : warnings.length ? "waiting" : "ready"],
  ];
  els.paperPromotionScorecard.innerHTML = `
    <div class="paper-promotion-scorecard__head">
      <span>Paper 晋级分数卡</span>
      ${chipHtml(promotionReadinessText(promotion.readiness), promotionReadinessClass(promotion.readiness))}
    </div>
    <div class="paper-promotion-scorecard__grid">
      ${rows.map(([label, value, tone]) => `
        <div class="paper-promotion-scorecard__item paper-promotion-scorecard__item--${tone}">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(value)}</strong>
        </div>
      `).join("")}
    </div>
    <p>最近 pipeline：${escapeHtml(promotion.last_pipeline_status || "无记录")}；平均滑点：${escapeHtml(percent(promotion.avg_slippage))}；晋级警告：${escapeHtml(warnings.length ? warnings.join(" / ") : "无")}</p>
  `;
}

function promotionNextSteps(promotion, blockers = listValue(promotion?.promotion_blockers), warnings = listValue(promotion?.promotion_warnings)) {
  if (blockers.length) return blockers.join(" / ");
  if (warnings.length) return warnings.join(" / ");
  return "已满足当前 paper 晋级检查";
}

function openingPlanCard(plan, executionDay) {
  const isActive = plan.status === "active";
  const matchesExecutionDay = planTradeDate(plan) === executionDay;
  const lockReason = recordLockReasonForPlan(plan, executionDay);
  const canRecord = !lockReason;
  const canCancel = ["draft", "active"].includes(plan.status);
  const marketContext = marketContextForPlan(plan.id);
  return `
    <div class="execution-plan-card">
      <div class="plan-title-line">
        <strong>${escapeHtml(planStockText(plan))}</strong>
        <span>${chipHtml(statusText(plan.status), statusClass(plan.status))}</span>
      </div>
      ${actionMetrics([
        ["计划 ID", dash(plan.id)],
        ["动作", actionText(plan.action)],
        ["复盘日", displayDate(plan.as_of_date || state.report?.as_of_date || state.asOfDate)],
        ["执行日", displayDate(executionDay)],
        ["计划交易日", displayDate(planTradeDate(plan))],
        ["执行日匹配", matchesExecutionDay ? "是" : "否"],
        ["计划股数", integerText(plannedShares(plan))],
        ["计划资金", money(plannedCash(plan))],
      ])}
      <div class="row-actions">
        <button type="button" data-plan-action="record" data-plan-id="${plan.id}" title="${escapeHtml(lockReason || "按该 active 计划录入人工买入成交")}" ${canRecord ? "" : "disabled"}>录入买入成交</button>
        <button type="button" data-plan-action="cancel" data-plan-id="${plan.id}" ${canCancel ? "" : "disabled"}>取消计划</button>
        <button type="button" data-plan-action="detail" data-plan-id="${plan.id}">详情</button>
      </div>
      ${lockReason ? `<p class="plan-lock-note">录入锁定：${escapeHtml(lockReason)}</p>` : ""}
      ${marketContextPlanNote(marketContext)}
    </div>
  `;
}

function marketContextForPlan(planId) {
  const openContext = state.openExecution?.market_plan_context;
  if (openContext && Number(openContext.trade_plan_id) === Number(planId)) return openContext;
  return (state.marketPlanContexts || []).find((context) => Number(context.trade_plan_id) === Number(planId)) || null;
}

function marketContextPlanNote(context) {
  if (!context) return "";
  const warning = context.management_action === "consider_cancel"
    ? "；仅提示考虑取消，不会自动取消计划"
    : "";
  return `
    <p class="plan-market-context-note">
      市场计划关系：${escapeHtml(marketPlanContextExecutionText(context))}${escapeHtml(warning)}
    </p>
  `;
}

function renderPreOpenChecklist(activePlans, executionDay, blocked, readiness = openingReadiness(activePlans, executionDay, blocked)) {
  const hasExecutionPlan = readiness.hasExecutionPlan;
  const items = [
    ["notSuspended", "未停牌 / 可交易", state.preOpenChecks.notSuspended, false],
    ["noMajorBadNews", "无重大利空", state.preOpenChecks.noMajorBadNews, false],
    ["openNotExtremeHigh", "开盘未极端高开", state.preOpenChecks.openNotExtremeHigh, false],
    ["cashSlotsChecked", "现金 / 仓位已核对", state.preOpenChecks.cashSlotsChecked, false],
    ["planDateToday", `计划日是执行日 ${displayDate(executionDay)}`, hasExecutionPlan, true],
  ];
  els.preOpenChecklist.innerHTML = items.map(([key, label, checked, auto]) => `
    <label class="checklist-item ${auto ? "auto" : ""}">
      <input type="checkbox" data-preopen-check="${key}" ${checked ? "checked" : ""} ${auto ? "disabled" : ""} />
      <span>${escapeHtml(label)}</span>
    </label>
  `).join("");
  els.preOpenChecklistState.textContent = readiness.ready ? `${readiness.checkedCount}/${readiness.totalChecks} 可录入` : `${readiness.checkedCount}/${readiness.totalChecks} 待确认`;
  els.preOpenChecklistState.className = `chip ${readiness.ready ? "chip-green" : blocked ? "chip-red" : "chip-amber"}`;
}

function renderOpeningCancelQueue() {
  const plans = state.tradePlans.filter((plan) => ["draft", "active"].includes(plan.status));
  els.openingCancelQueue.innerHTML = plans.length
    ? plans.map((plan) => `
      <div class="list-row">
        ${chipHtml(statusText(plan.status), statusClass(plan.status))}
        <span>计划 ${plan.id} / ${escapeHtml(planStockText(plan))} / ${displayDate(planTradeDate(plan))}</span>
        <button type="button" data-plan-action="cancel" data-plan-id="${plan.id}">取消</button>
      </div>
    `).join("")
    : emptyState("没有可取消的 draft / active 计划。");
}

function renderOpeningExitQueue() {
  const due = duePositions();
  els.openingExitQueue.innerHTML = due.length
    ? due.map((position) => {
      const due = position.due_stage || position.action_due;
      return `
        <div class="list-row">
          ${chipHtml(dueText(due), dueClass(due))}
          <span>持仓 ${position.position_id} / ${escapeHtml(position.ts_code)} ${escapeHtml(position.name)} / T+2 ${displayDate(position.planned_t2_date)} / T+5 ${displayDate(position.planned_t5_date)}</span>
          <button type="button" data-record-position-id="${position.position_id}">卖出录入</button>
        </div>
      `;
    }).join("")
    : emptyState("当前没有持仓退出任务。");
}

function onPreOpenChecklistChange(event) {
  const input = event.target.closest("input[data-preopen-check]");
  if (!input || input.disabled) return;
  const key = input.dataset.preopenCheck;
  if (Object.prototype.hasOwnProperty.call(state.preOpenChecks, key)) {
    state.preOpenChecks[key] = input.checked;
    renderOpeningExecution();
    setRecordFormState();
  }
}

function renderStatusBand() {
  const report = state.report;
  const account = report?.account;
  const quality = report?.data_quality;
  els.statusAccount.textContent = accountName(account);
  els.statusReviewDate.textContent = displayDate(report?.as_of_date || state.asOfDate);
  els.statusNextDate.textContent = displayDate(executionDate());
  els.statusMarketDate.textContent = displayDate(report?.latest_market_date);
  els.statusCapacity.textContent = capacityText(account);

  const qualityText = readinessText(quality?.readiness);
  els.statusQuality.textContent = qualityText;
  els.statusQuality.className = `chip ${qualityClass(quality?.readiness)}`;
}

function renderReview() {
  renderNextAction();
  renderBlockers();
  renderCandidate();
  renderDuePositions();
  renderAgent();
}

function renderNextDayDecision() {
  const cockpit = nextDayDecisionData();
  els.decisionDateLabel.textContent = cockpit
    ? `复盘日 ${displayDate(cockpit.as_of_date)} / 执行日 ${displayDate(cockpit.execution_date)}`
    : `复盘日 ${displayDate(state.asOfDate)}`;
  if (!cockpit) {
    els.decisionStatusPanel.className = "acceptance-status-panel decision-status-panel";
    els.decisionStatusPanel.innerHTML = emptyState("下一交易日决策驾驶舱暂无数据。");
    els.decisionSystemProposal.innerHTML = emptyState("暂无系统建议。");
    els.decisionStrategyProposal.innerHTML = emptyState("暂无策略 proposal 摘要。");
    els.decisionChecklist.innerHTML = emptyState("暂无决策清单。");
    return;
  }

  const proposal = cockpit.system_proposal || {};
  els.decisionStatusPanel.className = `acceptance-status-panel decision-status-panel decision-status-panel--${escapeHtml(cockpit.status || "review_required")}`;
  els.decisionStatusPanel.innerHTML = `
    <div class="acceptance-status-main">
      <span class="workflow-guide__kicker">只读驾驶舱 · 不执行交易 / 不开 timer</span>
      <h2>${escapeHtml(decisionStatusText(cockpit.status))}</h2>
      <p>${escapeHtml(cockpit.headline || "下一交易日决策状态待确认。")}</p>
    </div>
    ${actionMetrics([
      ["复盘日", displayDate(cockpit.as_of_date)],
      ["执行日", displayDate(cockpit.execution_date)],
      ["建议动作", openExecutionActionText(proposal.action)],
      ["blocker", String(cockpit.blocker_count || 0)],
      ["warning", String(cockpit.warning_count || 0)],
      ["人工下一步", cockpit.recommended_manual_action || "-"],
    ])}
    <div class="acceptance-actions">
      <button type="button" data-decision-action="execution">开盘执行</button>
      <button type="button" data-decision-action="acceptance">运营验收</button>
      <button type="button" data-decision-action="refresh">刷新驾驶舱</button>
    </div>
  `;

  els.decisionSystemProposal.innerHTML = `
    <div class="decision-proposal-card">
      ${chipHtml(openExecutionActionText(proposal.action), decisionStatusClass(cockpit.status))}
      <strong>${escapeHtml(proposal.rationale || "等待人工复核。")}</strong>
      ${actionMetrics([
        ["目标", proposal.target || "-"],
        ["计划 ID", dash(proposal.trade_plan_id)],
        ["持仓 ID", dash(proposal.position_id)],
        ["计划交易日", displayDate(proposal.planned_trade_date)],
        ["计划股数", integerText(proposal.planned_shares)],
      ])}
      <button type="button" class="link-button" data-decision-action="execution">查看 open-execution</button>
    </div>
  `;

  renderDecisionStrategyProposal(cockpit.strategy_proposals);
  const items = Array.isArray(cockpit.checklist) ? cockpit.checklist : [];
  els.decisionChecklist.innerHTML = items.length
    ? items.map(decisionChecklistCard).join("")
    : emptyState("暂无决策清单。");
}

function nextDayDecisionData() {
  return state.nextDayDecision || state.report?.next_day_decision || null;
}

function renderDecisionStrategyProposal(proposals) {
  if (!proposals) {
    els.decisionStrategyProposal.innerHTML = emptyState("暂无策略 proposal 摘要。");
    return;
  }
  const items = Array.isArray(proposals.items) ? proposals.items : [];
  els.decisionStrategyProposal.innerHTML = `
    <div class="decision-proposal-card">
      ${chipHtml(`${proposals.review_required_count || 0} 待审阅`, proposals.review_required_count ? "chip-amber" : "chip-green")}
      <strong>total ${integerText(proposals.total_count)} / accepted ${integerText(proposals.accepted_count)}</strong>
      ${actionMetrics([
        ["proposed", integerText(proposals.proposed_count)],
        ["testing", integerText(proposals.testing_count)],
        ["accepted", integerText(proposals.accepted_count)],
        ["rejected", integerText(proposals.rejected_count)],
      ])}
      <div class="compact-list">
        ${items.length ? items.slice(0, 4).map((item) => `
          <div class="list-row">
            ${chipHtml(statusText(item.status), item.status === "accepted" ? "chip-amber" : "chip-neutral")}
            <span>${escapeHtml(item.title || `hypothesis ${item.hypothesis_id}`)}</span>
            <button type="button" data-decision-action="hypotheses">审阅</button>
          </div>
        `).join("") : emptyState("没有待审阅策略假设或 proposal。")}
      </div>
    </div>
  `;
}

function decisionChecklistCard(item) {
  const action = decisionActionForItem(item);
  const blockers = listValue(item.blocker_codes);
  const warnings = listValue(item.warning_codes);
  const refs = listValue(item.source_refs);
  return `
    <article class="acceptance-gate acceptance-gate--${escapeHtml(item.status || "warning")} decision-check-card">
      <div class="acceptance-gate__head">
        <strong>${escapeHtml(item.label || item.key || "decision check")}</strong>
        ${chipHtml(decisionItemStatusText(item.status), acceptanceStatusClass(item.status))}
      </div>
      <p>${escapeHtml(item.summary || "-")}</p>
      <span>${escapeHtml(item.detail || "只读检查项。")}</span>
      <span><b>下一步：</b>${escapeHtml(item.manual_action || "-")}</span>
      ${blockers.length ? `<div class="acceptance-code-row">${blockers.map((code) => chipHtml(code, "chip-red")).join("")}</div>` : ""}
      ${warnings.length ? `<div class="acceptance-code-row">${warnings.map((code) => chipHtml(code, "chip-amber")).join("")}</div>` : ""}
      ${refs.length ? `<div class="acceptance-source-refs">${refs.slice(0, 4).map((ref) => chipHtml(sourceRefText(ref), sourceRefClass(ref))).join("")}</div>` : ""}
      <button type="button" class="link-button" data-decision-action="${escapeHtml(action)}">${escapeHtml(decisionActionText(action))}</button>
    </article>
  `;
}

function decisionActionForItem(item) {
  const key = String(item?.key || "");
  if (key === "paper_acceptance") return "acceptance";
  if (key === "evidence_blockers") return item?.status === "blocked" ? "quality" : "market";
  if (key === "market_review") return "market";
  if (key === "open_execution") return "execution";
  if (key === "strategy_proposals") return "hypotheses";
  return "acceptance";
}

function onDecisionActionClick(event) {
  const button = event.target.closest("button[data-decision-action]");
  if (!button) return;
  const action = button.dataset.decisionAction;
  if (action === "refresh") loadNextDayDecisionAndRender();
  if (action === "execution") setActivePage("execution");
  if (action === "acceptance") setActivePage("acceptance");
  if (action === "market") setActivePage("market");
  if (action === "quality") setActivePage("quality");
  if (action === "hypotheses") setActivePage("hypotheses");
}

function renderPaperAcceptance() {
  const acceptance = paperAcceptanceData();
  els.acceptanceDateLabel.textContent = acceptance
    ? `复盘日 ${displayDate(acceptance.as_of_date)} / 执行日 ${displayDate(acceptance.execution_date)}`
    : `复盘日 ${displayDate(state.asOfDate)}`;
  if (!acceptance) {
    els.acceptanceStatusPanel.className = "acceptance-status-panel acceptance-status-panel--warning";
    els.acceptanceStatusPanel.innerHTML = emptyState("纸盘每日运营验收暂无数据。");
    renderAcceptanceAlerts(null, paperAcceptanceHistoryData());
    renderAcceptanceHistory(paperAcceptanceHistoryData());
    els.acceptanceOverviewGrid.innerHTML = "";
    els.acceptanceGateBody.innerHTML = emptyState("readiness gates 暂无数据。");
    els.acceptanceBlockerList.innerHTML = emptyState("无法确认未处理 blocker。");
    return;
  }

  const blockers = acceptanceBlockerList(acceptance);
  const warningCount = acceptanceWarningCount(acceptance);
  const openExecution = acceptance.open_execution || {};
  els.acceptanceStatusPanel.className = `acceptance-status-panel acceptance-status-panel--${acceptance.status || "warning"}`;
  els.acceptanceStatusPanel.innerHTML = `
    <div class="acceptance-status-main">
      <span class="workflow-guide__kicker">只读验收面板 · Dashboard 不会执行交易</span>
      <h2>${escapeHtml(acceptanceStatusText(acceptance.status))}</h2>
      <p>${escapeHtml(acceptance.summary || "纸盘每日运营验收状态待确认。")}</p>
    </div>
    ${actionMetrics([
      ["账户", acceptance.account_key || accountContextText()],
      ["复盘日", displayDate(acceptance.as_of_date)],
      ["执行日", displayDate(acceptance.execution_date)],
      ["open-execution", openExecutionActionText(openExecution.next_action)],
      ["未处理 blocker", String(blockers.length)],
      ["advisory 警告", String(warningCount)],
    ])}
    <div class="acceptance-actions">
      <button type="button" data-acceptance-action="execution">查看开盘执行</button>
      <button type="button" data-acceptance-action="quality">查看数据质量</button>
      <button type="button" data-acceptance-action="refresh">刷新验收</button>
    </div>
  `;
  renderAcceptanceAlerts(acceptance, paperAcceptanceHistoryData());

  const overviewGates = [
    acceptance.data_freshness,
    acceptance.evidence_coverage,
    acceptance.agent_status,
    acceptance.open_execution_gate,
  ].filter(Boolean);
  els.acceptanceOverviewGrid.innerHTML = overviewGates.map(acceptanceGateCard).join("");

  const readinessGates = acceptance.readiness_gates || [];
  els.acceptanceGateBody.innerHTML = readinessGates.length
    ? readinessGates.map(acceptanceGateCard).join("")
    : emptyState("readiness gates 暂无数据。");

  els.acceptanceBlockerList.innerHTML = blockers.length
    ? blockers.map((blocker) => `
      <div class="list-row">
        ${chipHtml("blocker", "chip-red")}
        <span>${escapeHtml(blocker)}</span>
        <button type="button" data-acceptance-action="quality">定位</button>
      </div>
    `).join("")
    : emptyState("没有未处理 blocker；仍需人工核对开盘检查和成交事实。");
  renderAcceptanceHistory(paperAcceptanceHistoryData());
}

function paperAcceptanceData() {
  return state.paperAcceptance || state.report?.paper_acceptance || null;
}

function paperAcceptanceHistoryData() {
  return state.paperAcceptanceHistory || null;
}

function renderAcceptanceAlerts(acceptance, history) {
  const alerts = acceptanceAlertList(acceptance, history);
  els.acceptanceAlertList.innerHTML = alerts.length
    ? alerts.slice(0, 8).map((alert) => `
      <div class="acceptance-alert acceptance-alert--${escapeHtml(alert.severity || "warning")}">
        ${chipHtml(alert.severity === "blocker" ? "blocker" : "warning", alert.severity === "blocker" ? "chip-red" : "chip-amber")}
        <div>
          <strong>${escapeHtml(alert.title || alert.code || "acceptance alert")}</strong>
          <span>${escapeHtml(alert.summary || "-")}</span>
        </div>
        <small>${escapeHtml(displayDate(alert.as_of_date))}</small>
        <button type="button" data-acceptance-action="${escapeHtml(alert.action || "quality")}">${escapeHtml(acceptanceActionText(alert.action || "quality"))}</button>
      </div>
    `).join("")
    : emptyState("暂无 acceptance 告警；历史趋势仍保持只读。");
}

function renderAcceptanceHistory(history) {
  const items = Array.isArray(history?.items) ? history.items : [];
  els.acceptanceHistorySummary.textContent = history?.summary || "暂无 paper acceptance 历史。";
  els.acceptanceHistoryList.innerHTML = items.length
    ? items.map((item) => `
      <button type="button" class="acceptance-history-card acceptance-history-card--${escapeHtml(item.status || "warning")}" data-acceptance-history-date="${escapeHtml(item.as_of_date)}">
        <strong>${escapeHtml(displayDate(item.as_of_date))}</strong>
        ${chipHtml(acceptanceStatusText(item.status), acceptanceStatusClass(item.status))}
        <span>执行 ${escapeHtml(displayDate(item.execution_date))} · ${escapeHtml(openExecutionActionText(item.open_execution_next_action))}</span>
        <span>blocker ${escapeHtml(String(item.unresolved_blocker_count || 0))} · warning ${escapeHtml(String(item.warning_count || 0))} · alert ${escapeHtml(String(item.alert_count || 0))}</span>
      </button>
    `).join("")
    : emptyState("暂无 paper acceptance 历史；运行日终复盘后会出现在这里。");
}

function acceptanceAlertList(acceptance, history) {
  const currentAlerts = Array.isArray(acceptance?.alerts) ? acceptance.alerts : [];
  const historyAlerts = Array.isArray(history?.alerts) ? history.alerts : [];
  const alerts = [...currentAlerts, ...historyAlerts];
  const seen = new Set();
  return alerts.filter((alert) => {
    const key = `${alert.as_of_date || ""}:${alert.code || ""}:${alert.gate_key || ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function renderOpsHistory() {
  const history = opsHistoryData();
  const items = Array.isArray(history?.items) ? history.items : [];
  els.opsHistorySummary.textContent = history?.summary || "暂无 ops run history；该视图不会主动运行远端命令。";
  els.opsHistoryCounts.innerHTML = opsHistoryCountChips(history?.counts || {});
  els.opsHistoryList.innerHTML = items.length
    ? items.map(opsHistoryCard).join("")
    : emptyState("暂无 pipeline / backup / release / health / timer evidence 历史。");
}

function opsHistoryData() {
  return state.opsHistory || null;
}

function opsHistoryCountChips(counts) {
  const entries = [
    ["daily_pipeline", "pipeline"],
    ["pipeline_step", "step"],
    ["backup", "backup"],
    ["release", "release"],
    ["health", "health"],
    ["paper_acceptance", "acceptance"],
    ["timer_evidence", "timer evidence"],
    ["timer_action", "timer action"],
  ];
  const chips = entries
    .filter(([key]) => Number(counts[key] || 0) > 0)
    .map(([key, label]) => chipHtml(`${label} ${counts[key]}`, opsHistoryCategoryClass(key)));
  return chips.length ? chips.join("") : chipHtml("0", "chip-neutral");
}

function opsHistoryCard(item) {
  const details = item.details || {};
  const detailRows = [
    ["来源", item.source],
    ["日期", displayDate(item.as_of_date)],
    ["操作者", item.operator || "-"],
    ["operation", item.operation_type || "-"],
    ["log", item.log_file || "-"],
    ["backup", details.backup_path || "-"],
    ["duplicate", details.duplicate_apply_count ?? "-"],
    ["health", details.health_url || details.health_command || "-"],
    ["release", details.release_tag || "-"],
  ].filter(([, value]) => value !== "-" && value !== "" && value !== null && value !== undefined);
  return `
    <article class="ops-history-card ops-history-card--${escapeHtml(item.category || "operation")}">
      <div class="ops-history-card__head">
        <div>
          <strong>${escapeHtml(item.title || opsHistoryCategoryText(item.category))}</strong>
          <span>${escapeHtml(displayTimestamp(item.occurred_at) || displayDate(item.as_of_date))}</span>
        </div>
        <div class="ops-history-card__chips">
          ${chipHtml(opsHistoryCategoryText(item.category), opsHistoryCategoryClass(item.category))}
          ${chipHtml(opsHistoryStatusText(item.status), opsHistoryStatusClass(item.status))}
        </div>
      </div>
      <p>${escapeHtml(item.summary || "-")}</p>
      ${detailRows.length ? `
        <div class="ops-history-card__details">
          ${detailRows.slice(0, 6).map(([label, value]) => `
            <span><b>${escapeHtml(label)}</b>${escapeHtml(String(value))}</span>
          `).join("")}
        </div>
      ` : ""}
    </article>
  `;
}

function acceptanceGateCard(gate) {
  const action = paperAcceptanceAction(gate);
  const blockers = listValue(gate.blocker_codes);
  const warnings = listValue(gate.warning_codes);
  const refs = listValue(gate.source_refs);
  return `
    <article class="acceptance-gate acceptance-gate--${escapeHtml(gate.status || "warning")}">
      <div class="acceptance-gate__head">
        <strong>${escapeHtml(gate.label || gate.key || "gate")}</strong>
        ${chipHtml(acceptanceStatusText(gate.status), acceptanceStatusClass(gate.status))}
      </div>
      <p>${escapeHtml(gate.summary || "-")}</p>
      <span>${escapeHtml(gate.detail || "只读 gate，不会触发写入。")}</span>
      ${blockers.length ? `<div class="acceptance-code-row">${blockers.map((code) => chipHtml(code, "chip-red")).join("")}</div>` : ""}
      ${warnings.length ? `<div class="acceptance-code-row">${warnings.map((code) => chipHtml(code, "chip-amber")).join("")}</div>` : ""}
      ${refs.length ? `<div class="acceptance-source-refs">${refs.slice(0, 4).map((ref) => chipHtml(sourceRefText(ref), sourceRefClass(ref))).join("")}</div>` : ""}
      <button type="button" class="link-button" data-acceptance-action="${escapeHtml(action)}">${escapeHtml(acceptanceActionText(action))}</button>
    </article>
  `;
}

function onAcceptanceActionClick(event) {
  const button = event.target.closest("button[data-acceptance-action]");
  if (!button) return;
  const action = button.dataset.acceptanceAction;
  if (action === "refresh") loadPaperAcceptanceAndRender();
  if (action === "quality") setActivePage("quality");
  if (action === "execution") setActivePage("execution");
  if (action === "agent") openAgentDrawer();
  if (action === "market") setActivePage("market");
}

function onAcceptanceHistoryClick(event) {
  const button = event.target.closest("[data-acceptance-history-date]");
  if (!button) return;
  const reviewDate = button.dataset.acceptanceHistoryDate;
  if (!reviewDate) return;
  state.asOfDate = reviewDate;
  state.reviewDatePinned = true;
  resetPreOpenChecks();
  syncFormFromState();
  persistContext();
  refreshAll({ keepNotice: true });
}

function paperAcceptanceAction(gate) {
  const key = String(gate?.key || "");
  if (key.includes("agent")) return "agent";
  if (key.includes("evidence") || key.includes("market")) return "market";
  if (key.includes("open_execution")) return "execution";
  if (key.includes("data") || key.includes("readiness") || key.includes("ledger")) return "quality";
  return "execution";
}

function acceptanceActionText(action) {
  return {
    agent: "查看 Agent",
    execution: "查看开盘执行",
    market: "查看证据",
    quality: "查看 blocker",
    refresh: "刷新验收",
  }[action] || "查看";
}

function acceptanceBlockerList(acceptance) {
  return listValue(acceptance?.unresolved_blockers);
}

function acceptanceWarningCount(acceptance) {
  const gates = [
    acceptance?.data_freshness,
    acceptance?.evidence_coverage,
    acceptance?.agent_status,
    acceptance?.open_execution_gate,
    ...(acceptance?.readiness_gates || []),
  ].filter(Boolean);
  return gates.reduce((count, gate) => count + listValue(gate.warning_codes).length, 0);
}

function renderReviewTimeline() {
  const items = state.reviewTimeline || [];
  const latestDate = items[0]?.review_date || latestReviewHistoryDate();
  const executionText = `开盘执行日保持 ${displayDate(executionDate())}`;
  els.reviewTimelineState.textContent = items.length
    ? `只读 · ${items.length} 日 · ${executionText}`
    : `只读 · 无记录 · ${executionText}`;
  els.reviewTimelineList.innerHTML = items.length
    ? items.map((item) => {
      const selected = normalizeDate(item.review_date) === normalizeDate(state.asOfDate);
      return `
        <button type="button" class="review-timeline-row ${selected ? "active" : ""}" data-review-timeline-date="${escapeHtml(item.review_date)}">
          <span class="timeline-date">
            <strong>${displayDate(item.review_date)}</strong>
            <em>下一交易日 ${displayDate(item.next_trade_date)}</em>
          </span>
          <span class="timeline-cell">
            <b>候选</b>
            <em>${escapeHtml(reviewTimelinePickText(item))}</em>
          </span>
          <span class="timeline-cell">
            <b>市场</b>
            <em>${escapeHtml(reviewTimelineMarketText(item))}</em>
          </span>
          <span class="timeline-cell">
            <b>计划关系</b>
            <em>${escapeHtml(reviewTimelinePlanContextText(item))}</em>
          </span>
          <span class="timeline-cell timeline-cell--execution">
            <b>open-execution</b>
            <em>${escapeHtml(reviewTimelineExecutionText(item))}</em>
          </span>
          <span class="history-badges">
            ${renderReviewTimelineBadges(item)}
          </span>
        </button>
      `;
    }).join("")
    : emptyState(latestDate ? `暂无跨日复盘对比；最新复盘日 ${displayDate(latestDate)}。` : "暂无跨日复盘对比。");
}

function renderReviewHistory() {
  const items = state.reviewHistory || [];
  const latestDate = latestReviewHistoryDate();
  const historyScope = latestDate ? `最新 ${displayDate(latestDate)}` : `截至 ${displayDate(state.asOfDate)}`;
  els.reviewHistoryState.textContent = items.length
    ? `${historyScope} · ${items.length} 条`
    : `${historyScope} · 无记录`;
  els.reviewHistoryList.innerHTML = items.length
    ? items.map((item) => {
      const selected = item.review_date === state.asOfDate;
      const meta = reviewHistoryMetaText(item);
      return `
        <button type="button" class="history-list-row ${selected ? "active" : ""}" data-review-date="${item.review_date}">
          <span class="history-date">${displayDate(item.review_date)}</span>
          <span class="history-main">
            <strong>${escapeHtml(reviewHistoryTitle(item))}</strong>
            <em>${escapeHtml(reviewHistorySubtext(item))}</em>
            ${meta ? `<span class="history-meta">${escapeHtml(meta)}</span>` : ""}
          </span>
          <span class="history-badges">
            ${renderReviewHistoryBadges(item)}
          </span>
        </button>
      `;
    }).join("")
    : emptyState("暂无复盘历史；运行复盘后会出现在这里。");
  renderReviewHistoryNavigation();
}

function renderReviewHistoryNavigation() {
  const previousDate = adjacentReviewHistoryDate(-1);
  const nextDate = adjacentReviewHistoryDate(1);
  const latestDate = latestReviewHistoryDate();
  const hasHistory = reviewHistoryDates().length > 0;
  els.reviewPrevDateButton.disabled = !previousDate;
  els.reviewNextDateButton.disabled = !nextDate;
  els.reviewLatestDateButton.disabled = !hasHistory || latestDate === normalizeDate(state.asOfDate);
  els.reviewPrevDateButton.title = previousDate ? `上一复盘日 ${displayDate(previousDate)}` : "没有更早的复盘历史";
  els.reviewNextDateButton.title = nextDate ? `下一复盘日 ${displayDate(nextDate)}` : "没有更新的复盘历史";
  els.reviewLatestDateButton.title = latestDate ? `最新可用复盘日 ${displayDate(latestDate)}` : "暂无复盘历史";
}

function renderReviewScopeMarkers() {
  const selected = `复盘日 ${displayDate(state.asOfDate)}`;
  const reviewNext = `复盘下一交易日 ${displayDate(state.report?.next_trade_date)}`;
  const execution = `开盘执行日 ${displayDate(executionDate())}`;
  els.currentReviewDateLabel.textContent = `当前复盘日：${displayDate(state.asOfDate)}`;
  els.blockerReviewScope.textContent = selected;
  els.candidateReviewScope.textContent = selected;
  els.dueReviewScope.textContent = `${selected} / ${reviewNext} / ${execution}`;
  els.agentReviewScope.textContent = selected;
}

function renderNextAction() {
  const report = state.report;
  const panel = document.querySelector(".next-action-panel");
  const plan = report?.buy_plan;
  const candidate = report?.candidate;
  const blocked = hasBlockingQuality();
  els.nextActionDate.textContent = `复盘日 ${displayDate(report?.as_of_date || state.asOfDate)} / 下一交易日 ${displayDate(report?.next_trade_date)} / 开盘执行日 ${displayDate(executionDate())}`;
  panel.classList.toggle("blocked", blocked);
  panel.classList.toggle("no-action", !blocked && !plan && !candidate);

  if (!report) {
    els.nextActionBody.innerHTML = emptyState("无法读取复盘报告。请确认 API Base、复盘日和账户。");
    setReviewButtons();
    return;
  }

  if (blocked) {
    els.nextActionBody.innerHTML = `
      <h3 class="action-title">数据阻断，不能发布计划</h3>
      <p class="muted">请先处理 blocker；页面不会把阻断状态降级成可执行动作。</p>
      ${actionMetrics([
        ["复盘日", displayDate(report.as_of_date)],
        ["下一交易日", displayDate(report.next_trade_date)],
        ["阻断数", String(report.data_quality?.blocker_count ?? blockingEvents().length)],
        ["警告数", String(report.data_quality?.warning_count ?? 0)],
      ])}
    `;
    setReviewButtons();
    return;
  }

  if (plan) {
    const title = plan.action === "buy_next_open" ? "存在买入计划" : actionText(plan.action);
    els.nextActionBody.innerHTML = `
      <h3 class="action-title">${escapeHtml(title)}</h3>
      <p>${candidate ? `${escapeHtml(candidate.ts_code)} ${escapeHtml(candidate.name)}` : "计划已生成，未关联候选摘要。"}</p>
      ${actionMetrics([
        ["计划状态", chipHtml(statusText(plan.status), statusClass(plan.status))],
        ["计划交易日", displayDate(plan.planned_trade_date || plan.planned_buy_date)],
        ["计划股数", dash(plan.planned_shares)],
        ["计划资金", money(plan.planned_cash)],
      ])}
    `;
    setReviewButtons();
    return;
  }

  if (candidate) {
    els.nextActionBody.innerHTML = `
      <h3 class="action-title">候选已产生，尚无交易计划</h3>
      <p>${escapeHtml(candidate.ts_code)} ${escapeHtml(candidate.name)}，评分 ${numberText(candidate.score, 4)}。</p>
      ${actionMetrics([
        ["复盘日", displayDate(candidate.review_date)],
        ["计划买入日", displayDate(candidate.planned_buy_date)],
        ["空闲仓位", dash(report.account?.free_position_slots)],
        ["入选原因", escapeHtml(reasonText(candidate.selection_reason))],
      ])}
    `;
  } else {
    els.nextActionBody.innerHTML = `
      <h3 class="action-title">无可执行候选</h3>
      <p class="muted">状态来自日级复盘结果，不写入 trade_plans.action。</p>
      ${actionMetrics([
        ["复盘日", displayDate(report.as_of_date)],
        ["原因", reasonText(report.no_candidate_reason)],
        ["下一交易日", displayDate(report.next_trade_date)],
        ["账户容量", capacityText(report.account)],
      ])}
    `;
  }
  setReviewButtons();
}

function onReviewHistoryClick(event) {
  const button = event.target.closest("button[data-review-date]");
  if (!button) return;
  setReviewDate(button.dataset.reviewDate);
}

function onReviewTimelineClick(event) {
  const button = event.target.closest("button[data-review-timeline-date]");
  if (!button) return;
  setReviewDate(button.dataset.reviewTimelineDate, { preserveExecutionDate: true });
}

function setReviewButtons() {
  const plan = state.report?.buy_plan;
  const blocked = hasBlockingQuality();
  els.publishReviewPlanButton.disabled = blocked || !plan || plan.status !== "draft";
  els.recordReviewPlanButton.disabled = blocked || !plan || plan.status !== "active";
}

function renderBlockers() {
  const blockers = blockingEvents();
  if (!blockers.length) {
    els.blockerList.innerHTML = emptyState("当前复盘日没有 open blocker。");
    return;
  }
  els.blockerList.innerHTML = blockers
    .map((item) => `
      <div class="list-row">
        ${chipHtml("阻断", "chip-red")}
        <span>${escapeHtml(item.message || item.code || "未命名阻断")}</span>
        <button type="button" data-page-jump="quality">处理</button>
      </div>
    `)
    .join("");
  els.blockerList.querySelectorAll("[data-page-jump]").forEach((button) => {
    button.addEventListener("click", () => setActivePage(button.dataset.pageJump));
  });
}

function renderCandidate() {
  const candidate = state.report?.candidate;
  if (!candidate) {
    els.openCandidateDetailButton.disabled = true;
    els.candidateSummary.innerHTML = emptyState(`无候选：${reasonText(state.report?.no_candidate_reason)}`);
    els.rankedSignalsBody.innerHTML = emptyRow(4, "没有候选明细。");
    return;
  }
  els.openCandidateDetailButton.disabled = false;
  els.candidateSummary.innerHTML = `
    <div class="action-meta action-meta--summary">
      <div class="metric"><span>股票</span><strong>${escapeHtml(candidate.ts_code)} ${escapeHtml(candidate.name)}</strong></div>
      <div class="metric"><span>评分</span><strong>${numberText(candidate.score, 4)}</strong></div>
      <div class="metric"><span>计划买入日</span><strong>${displayDate(candidate.planned_buy_date)}</strong></div>
      <div class="metric"><span>胜出信号数</span><strong>${dash(candidate.selected_over_signal_count)}</strong></div>
    </div>
    <p class="summary-footnote">主体只保留候选摘要；特征、血缘和 ranked signals 在详情面板查看。</p>
  `;
  const rows = candidate.ranked_signals || [];
  els.rankedSignalsBody.innerHTML = rows.length
    ? rows.slice(0, 5).map((signal) => `
      <tr>
        <td>${dash(signal.signal_rank)}</td>
        <td>${escapeHtml(signal.ts_code)} ${escapeHtml(signal.name)}</td>
        <td class="num">${numberText(signal.score, 4)}</td>
        <td>${signal.signal_id}</td>
      </tr>
    `).join("")
    : emptyRow(4, "没有 ranked signals。");
}

function renderDuePositions() {
  const due = duePositions();
  els.duePositionsBody.innerHTML = due.length
    ? due.map((position) => `
      <tr>
        <td>${escapeHtml(position.ts_code)} ${escapeHtml(position.name)}</td>
        <td>${displayDate(position.buy_date)}</td>
        <td>${displayDate(position.planned_t2_date)}</td>
        <td>${displayDate(position.planned_t5_date)}</td>
        <td>${chipHtml(dueText(position.action_due || position.due_stage), dueClass(position.action_due || position.due_stage))}</td>
      </tr>
    `).join("")
    : emptyRow(5, "没有 T+2 / T+5 到期待处理持仓。");
}

function renderAgent() {
  const advice = state.report?.agent_advice;
  if (!advice) {
    const html = emptyState("TradingAgents 未运行或不可用；本页只展示系统复盘原始数据。");
    els.agentSummary.innerHTML = html;
    els.agentPageBody.innerHTML = html;
    els.openAgentDetailInlineButton.disabled = true;
    els.openAgentDetailButton.disabled = true;
    return;
  }
  els.openAgentDetailInlineButton.disabled = false;
  els.openAgentDetailButton.disabled = false;
  els.agentSummary.innerHTML = renderAgentAdvice(advice, { expanded: false });
  els.agentPageBody.innerHTML = `
    ${renderAgentAdvice(advice, { expanded: false })}
    <div class="drawer-entry-row">
      <button type="button" class="primary-button" data-agent-drawer-open>打开统一详情面板</button>
    </div>
  `;
  els.agentPageBody.querySelector("[data-agent-drawer-open]")?.addEventListener("click", openAgentDrawer);
}

function renderMarketReview() {
  renderMarketReviewNavigation();
  renderMarketHistoryStrip();
  renderMarketScopeMarkers();
  renderMarketRegimeStrip();
  renderMarketSectors();
  renderMarketPlanContext();
  renderMarketSentimentSummary();
  renderMarketHypotheses();
}

function renderStrategyHypothesisWorkbench() {
  const workbench = state.strategyHypothesisWorkbench;
  const evaluations = strategyHypothesisEvaluations();
  const summary = workbench?.summary || {};
  const statusFilter = els.strategyHypothesisStatusFilter.value || "全部状态";
  const dateFilter = state.strategyHypothesisAsOfDate ? displayDate(state.strategyHypothesisAsOfDate) : "全部日期";
  els.strategyHypothesisWorkbenchState.textContent = evaluations.length
    ? `${dateFilter} · ${statusFilter} · ${evaluations.length} 条`
    : `${dateFilter} · ${statusFilter} · 无记录`;
  renderStrategyHypothesisSummary(summary);
  renderStrategyHypothesisQueue(evaluations);
  renderStrategyHypothesisSafety(workbench?.safety || {});
  renderStrategyHypothesisList(evaluations);
}

function renderStrategyHypothesisSummary(summary) {
  const byStatus = summary.by_status || {};
  els.strategyHypothesisWorkbenchSummary.innerHTML = actionMetrics([
    ["策略假设", integerText(summary.total || 0)],
    ["验证中", integerText(byStatus.testing || 0)],
    ["可进入接受复核", integerText(summary.ready_to_accept_count || 0)],
    ["待 strategy-version task", integerText(summary.strategy_version_task_required_count || 0)],
    ["待 proposal artifact", integerText(summary.proposal_required_count || 0)],
    ["待 proposal review", integerText(summary.proposal_review_required_count || 0)],
    ["proposal ready", integerText(summary.proposal_ready_count || 0)],
    ["review artifacts", integerText(summary.proposal_review_artifact_count || 0)],
    ["promotion requests", integerText(summary.promotion_request_count || 0)],
    ["Backtest artifacts", integerText(summary.artifact_count || 0)],
    ["Proposal artifacts", integerText(summary.proposal_artifact_count || 0)],
    ["异常 artifacts", integerText(
      (summary.invalid_artifact_count || 0)
      + (summary.invalid_proposal_artifact_count || 0)
      + (summary.invalid_proposal_review_artifact_count || 0),
    )],
  ]);
}

function renderStrategyHypothesisQueue(evaluations) {
  const queue = [...evaluations]
    .filter((evaluation) => !["closed_rejected", "closed_archived"].includes(evaluation.next_action))
    .sort(strategyHypothesisQueueSort)
    .slice(0, 6);
  els.strategyHypothesisQueueState.textContent = queue.length ? `${queue.length} 项待审阅` : "无待审阅项";
  els.strategyHypothesisQueue.innerHTML = queue.length
    ? queue.map((evaluation) => {
      const hypothesis = evaluation.hypothesis || {};
      return `
        <article class="hypothesis-queue-card">
          <div>
            ${chipHtml(hypothesisNextActionText(evaluation.next_action), hypothesisNextActionClass(evaluation.next_action))}
            <strong>${escapeHtml(hypothesis.title || `假设 ${hypothesis.hypothesis_id}`)}</strong>
            <span>${escapeHtml(evaluation.next_action_label || "-")}</span>
          </div>
          <button type="button" class="link-button" data-strategy-hypothesis-id="${escapeHtml(hypothesis.hypothesis_id)}">审阅</button>
        </article>
      `;
    }).join("")
    : emptyState("当前筛选下没有需要推进的策略假设。");
}

function renderStrategyHypothesisSafety(safety) {
  els.strategyHypothesisSafetyPanel.innerHTML = `
    <p class="market-readonly-note">策略假设评估工作台只读：不会修改 active strategy params，不写 trade_plans、trades、positions，也不会改变 paper/live 交易行为。</p>
    ${actionMetrics([
      ["read_only", safety.read_only ? "是" : "-"],
      ["active_params_mutated", safety.active_params_mutated ? "是" : "否"],
      ["writes_trade_state", safety.writes_trade_state ? "是" : "否"],
      ["paper/live 行为", safety.writes_paper_live_behavior ? "会改变" : "不改变"],
      ["accepted 后续", safety.accepted_creates_separate_strategy_version_task ? "单独 proposal" : "-"],
      ["proposal_artifacts_only", safety.proposal_artifacts_only ? "是" : "-"],
      ["proposal_review_artifacts_only", safety.proposal_review_artifacts_only ? "是" : "-"],
      ["API", "/api/strategy-hypotheses/workbench"],
      ["Review API", "/api/strategy-hypotheses/proposal-reviews"],
    ])}
  `;
}

function renderStrategyHypothesisList(evaluations) {
  els.strategyHypothesisWorkbenchList.innerHTML = evaluations.length
    ? evaluations.map(renderStrategyHypothesisCard).join("")
    : emptyState(errorMessages(state.strategyHypothesisWorkbenchEnvelope || {}).join("；") || "暂无策略假设评估数据。");
}

function renderStrategyHypothesisCard(evaluation) {
  const hypothesis = evaluation.hypothesis || {};
  const gate = evaluation.acceptance_gate || {};
  const safety = evaluation.safety || {};
  const artifactCount = (evaluation.backtest_artifacts || []).length;
  const proposalCount = (evaluation.strategy_version_proposals || []).length;
  const proposalReviewCount = (evaluation.strategy_version_proposal_reviews || []).length;
  const latestReview = latestStrategyProposalReview(evaluation);
  const gateClass = safety.proposed_change_mutates_active_params || safety.artifact_reports_active_param_mutation
    ? "chip-red"
    : gate.can_accept
      ? "chip-green"
      : gate.accepted_complete
        ? "chip-blue"
        : gate.blocks?.length
          ? "chip-amber"
          : "chip-neutral";
  return `
    <article class="hypothesis-workbench-card">
      <div class="hypothesis-workbench-card__head">
        <div>
          <span class="market-regime-kicker">strategy_hypotheses · ${escapeHtml(hypothesis.hypothesis_type || "-")}</span>
          <strong>${escapeHtml(hypothesis.title || `假设 ${hypothesis.hypothesis_id}`)}</strong>
        </div>
        <div class="hypothesis-chip-stack">
          ${chipHtml(hypothesisStatusText(hypothesis.status), hypothesisStatusClass(hypothesis.status))}
          ${chipHtml(hypothesisNextActionText(evaluation.next_action), hypothesisNextActionClass(evaluation.next_action))}
        </div>
      </div>
      <p>${escapeHtml(hypothesis.rationale || "暂无 rationale。")}</p>
      <div class="hypothesis-gate-strip">
        ${chipHtml(gate.has_validation_evidence ? "evidence 已附" : "缺 validation evidence", gate.has_validation_evidence ? "chip-green" : "chip-amber")}
        ${chipHtml(artifactCount ? `${artifactCount} artifact` : "缺 backtest artifact", artifactCount ? "chip-blue" : "chip-amber")}
        ${chipHtml(gate.backtest_artifacts_valid ? "artifact 有效" : "artifact 待确认", gate.backtest_artifacts_valid ? "chip-green" : "chip-neutral")}
        ${chipHtml(proposalCount ? `${proposalCount} proposal` : "缺 proposal artifact", proposalCount ? "chip-indigo" : "chip-neutral")}
        ${chipHtml(proposalReviewCount ? `${proposalReviewCount} review` : "待 proposal review", proposalReviewCount ? "chip-blue" : "chip-neutral")}
        ${chipHtml(latestReview?.decision ? proposalReviewDecisionText(latestReview.decision) : "未请求 promotion", latestReview?.decision ? proposalReviewDecisionClass(latestReview.decision) : "chip-neutral")}
        ${chipHtml(gate.can_accept ? "可接受复核" : gate.accepted_complete ? "accepted 完整" : "gate 未完成", gateClass)}
      </div>
      <div class="row-actions">
        <button type="button" data-strategy-hypothesis-id="${escapeHtml(hypothesis.hypothesis_id)}">评估详情</button>
        <button type="button" data-page-jump="market">回到全市场</button>
      </div>
      ${strategyProposalReviewButtons(evaluation)}
    </article>
  `;
}

function renderMarketScopeMarkers() {
  const selected = `全市场日 ${displayDate(marketReviewDate())}`;
  const reviewContext = normalizeDate(state.asOfDate);
  const latest = state.marketReviewHistory[0]?.as_of_date;
  const contextText = reviewContext && reviewContext !== marketReviewDate()
    ? ` / 交易上下文 ${displayDate(reviewContext)}`
    : "";
  els.marketReviewDateLabel.textContent = latest && latest !== marketReviewDate()
    ? `${selected}${contextText} / 最新全市场 ${displayDate(latest)}`
    : `${selected}${contextText}`;
}

function renderMarketReviewNavigation() {
  const previousDate = adjacentMarketReviewDate(-1);
  const nextDate = adjacentMarketReviewDate(1);
  const latestDate = latestMarketReviewDate();
  const hasHistory = marketReviewHistoryDates().length > 0;
  const selectedDate = marketReviewDate();
  els.marketReviewDateInput.value = dateInputValue(selectedDate);
  els.marketPrevDateButton.disabled = !previousDate;
  els.marketNextDateButton.disabled = !nextDate;
  els.marketLatestDateButton.disabled = !hasHistory || latestDate === selectedDate;
  els.marketFollowReviewDateButton.disabled = !state.marketDatePinned && selectedDate === normalizeDate(state.asOfDate);
  els.marketPrevDateButton.title = previousDate ? `上一全市场 ${displayDate(previousDate)}` : "没有更早的全市场复盘历史";
  els.marketNextDateButton.title = nextDate ? `下一全市场 ${displayDate(nextDate)}` : "没有更新的全市场复盘历史";
  els.marketLatestDateButton.title = latestDate ? `最新全市场 ${displayDate(latestDate)}` : "暂无全市场复盘历史";
}

function renderMarketHistoryStrip() {
  const items = state.marketReviewHistory || [];
  const selectedDate = marketReviewDate();
  els.marketHistoryStrip.innerHTML = items.length
    ? `
      <span class="market-history-strip__label">全市场历史</span>
      <div class="market-history-strip__items">
        ${items.slice(0, 8).map((item) => {
          const date = normalizeDate(item.as_of_date);
          const selected = date === selectedDate;
          return `
            <button type="button" class="market-history-pill ${selected ? "active" : ""}" data-market-history-date="${escapeHtml(date)}">
              <strong>${displayDate(date)}</strong>
              <span>${escapeHtml(marketRegimeText(item.regime || item.status))}</span>
            </button>
          `;
        }).join("")}
      </div>
    `
    : emptyState(`暂无全市场历史；当前查看 ${displayDate(selectedDate)}。`);
}

function onMarketHistoryClick(event) {
  const button = event.target.closest("button[data-market-history-date]");
  if (!button) return;
  setMarketReviewDate(button.dataset.marketHistoryDate);
}

function marketReviewHistoryDates() {
  return [...new Set((state.marketReviewHistory || [])
    .map((item) => normalizeDate(item.as_of_date))
    .filter((value) => /^\d{8}$/.test(value)))]
    .sort();
}

function latestMarketReviewDate() {
  const dates = marketReviewHistoryDates();
  return dates.length ? dates[dates.length - 1] : "";
}

function adjacentMarketReviewDate(offset) {
  const dates = marketReviewHistoryDates();
  const current = marketReviewDate();
  if (!dates.length || !/^\d{8}$/.test(current)) return "";
  if (offset < 0) {
    return [...dates].reverse().find((date) => date < current) || "";
  }
  return dates.find((date) => date > current) || "";
}

function marketReviewDate() {
  return normalizeDate(state.marketAsOfDate || state.asOfDate);
}

function renderMarketRegimeStrip() {
  const review = state.marketReview;
  const regime = review?.regime;
  const exists = marketReviewExists();
  if (!exists) {
    const missing = marketMissingDataText(review);
    els.marketRegimeStrip.innerHTML = `
      <div class="market-regime-card market-regime-card--empty">
        <span class="market-regime-kicker">market-reviews</span>
        <strong>暂无全市场复盘</strong>
        <p>${escapeHtml(missing || `全市场日 ${displayDate(marketReviewDate())} 尚未生成 market-reviews 记录。`)}</p>
      </div>
    `;
    return;
  }

  els.marketRegimeStrip.innerHTML = `
    <div class="market-regime-card market-regime-card--hero">
      <span class="market-regime-kicker">market-reviews</span>
      <strong>${escapeHtml(marketRegimeText(regime?.regime || review.status))}</strong>
      <p>${escapeHtml(regime?.summary || review.regime_summary || marketSummaryText(review.summary))}</p>
    </div>
    ${marketRegimeMetric("宽度", regime?.breadth_score ?? review.scores?.breadth, "breadth")}
    ${marketRegimeMetric("趋势", regime?.trend_score ?? review.scores?.trend, "trend")}
    ${marketRegimeMetric("量能", regime?.volume_score ?? review.scores?.volume, "volume")}
    ${marketRegimeMetric("持续性", regime?.persistence_score ?? review.scores?.persistence, "persistence")}
    ${marketRegimeMetric("情绪", regime?.sentiment_score, "sentiment")}
  `;
}

function marketRegimeMetric(label, value, key) {
  return `
    <div class="market-regime-card market-regime-card--metric" data-regime-metric="${escapeHtml(key)}">
      <span>${escapeHtml(label)}</span>
      <strong>${scoreText(value)}</strong>
    </div>
  `;
}

function renderMarketSectors() {
  const sectors = orderedMarketSectors();
  els.marketSectorState.textContent = sectors.length
    ? `${sectors.length} 个板块 / ${marketConstituentCount()} 只成分股`
    : "无板块快照";
  els.marketSectorBody.innerHTML = sectors.length
    ? sectors.map((sector) => {
      const sentiment = sectorSentiment(sector);
      return `
        <tr>
          <td>${dash(sector.rank_overall)}</td>
          <td>
            <strong>${escapeHtml(sector.sector_name || sector.sector_code)}</strong>
            <span class="table-subtext">${escapeHtml(sector.sector_code || "-")} · ${escapeHtml(sector.provider || "unknown")}</span>
          </td>
          <td class="num">${percent(sector.return_1d)}</td>
          <td class="num">${percent(sector.return_5d)}</td>
          <td class="num">${scoreText(sector.persistence_score)}</td>
          <td>${chipHtml(sentimentText(sentiment), sentimentClass(sentiment))}</td>
          <td class="num">${integerText(sector.leader_count ?? sector.constituents?.length)}</td>
          <td><button type="button" data-market-sector-action="detail" data-sector-code="${escapeHtml(sector.sector_code)}">详情</button></td>
        </tr>
      `;
    }).join("")
    : emptyRow(8, marketMissingDataText(state.marketSectorsEnvelope?.data) || "暂无板块轮动数据。");
}

function renderMarketPlanContext() {
  const planId = marketContextPlanId();
  const contexts = state.marketPlanContexts || [];
  const header = `
    <p class="market-readonly-note">Plan-context 只读：市场复盘不会自动改变明日计划，不会发布、取消、修改或执行 trade_plans。</p>
  `;
  if (!contexts.length) {
    const missing = marketMissingDataText(state.marketPlanContextEnvelope?.data);
    els.marketPlanContextPanel.innerHTML = `
      ${header}
      ${renderMarketLinkedPlan({ trade_plan_id: planId })}
      ${actionMetrics([
        ["关联计划", planId ? `计划 ${planId}` : "当前无明日计划"],
        ["上下文记录", "0"],
        ["来源", "market_plan_contexts"],
        ["状态", missing || "暂无关系记录"],
      ])}
    `;
    return;
  }

  els.marketPlanContextPanel.innerHTML = `
    ${header}
    <div class="market-context-list">
      ${contexts.map((context) => `
        <article class="market-context-card">
          <div class="market-plan-context-pair">
            <div class="market-context-main">
              <div class="market-context-card__head">
                <strong>计划 ${escapeHtml(context.trade_plan_id)}</strong>
                <span>
                  ${chipHtml(alignmentText(context.alignment), alignmentClass(context.alignment))}
                  ${chipHtml(riskText(context.risk_level), riskClass(context.risk_level))}
                </span>
              </div>
              <p>${escapeHtml(context.rationale || "暂无 rationale。")}</p>
              <dl class="market-context-meta">
                <dt>管理建议</dt>
                <dd>${escapeHtml(managementActionText(context.management_action))}</dd>
                <dt>创建时间</dt>
                <dd>${escapeHtml(displayTimestamp(context.created_at))}</dd>
              </dl>
            </div>
            ${renderMarketLinkedPlan(context)}
          </div>
        </article>
      `).join("")}
    </div>
  `;
}

function renderMarketLinkedPlan(context) {
  const planId = context?.trade_plan_id || marketContextPlanId();
  const plan = marketPlanForContext(planId);
  if (!planId) {
    return `
      <aside class="market-linked-plan market-linked-plan--empty">
        <span>相关明日计划</span>
        <strong>当前无明日计划</strong>
        <p>Plan-context 会靠近相关计划展示；没有计划时只保留市场建议。</p>
      </aside>
    `;
  }
  if (!plan) {
    return `
      <aside class="market-linked-plan market-linked-plan--empty">
        <span>相关明日计划</span>
        <strong>计划 ${escapeHtml(planId)}</strong>
        <p>当前上下文未加载该计划详情；关系记录仍保持只读。</p>
      </aside>
    `;
  }
  return `
    <aside class="market-linked-plan" data-plan-context-view="明日计划关系">
      <span>相关明日计划</span>
      <strong>${escapeHtml(planStockText(plan))}</strong>
      <dl>
        <dt>计划 ID</dt>
        <dd>${escapeHtml(plan.id)}</dd>
        <dt>状态</dt>
        <dd>${escapeHtml(statusText(plan.status))}</dd>
        <dt>交易日</dt>
        <dd>${displayDate(planTradeDate(plan))}</dd>
        <dt>动作</dt>
        <dd>${escapeHtml(actionText(plan.action))}</dd>
      </dl>
      <button type="button" class="link-button" data-market-plan-action="detail" data-plan-id="${escapeHtml(plan.id)}">计划详情</button>
    </aside>
  `;
}

function renderMarketSentimentSummary() {
  const items = state.marketExternalItems || [];
  const counts = state.marketExternalEnvelope?.data?.coverage?.by_sentiment || {};
  const dominant = dominantSentiment(counts);
  els.marketSentimentState.textContent = items.length
    ? `情绪 ${sentimentText(dominant)} · ${items.length} 条`
    : "情绪 -";
  els.openMarketNewsDrawerButton.disabled = items.length === 0;
  if (!items.length) {
    els.marketSentimentSummary.innerHTML = emptyState(marketMissingDataText(state.marketExternalEnvelope?.data) || "暂无新闻 / 情绪证据。");
    return;
  }
  const countChips = Object.entries(counts)
    .map(([sentiment, count]) => chipHtml(`${sentimentText(sentiment)} ${count}`, sentimentClass(sentiment)))
    .join("");
  els.marketSentimentSummary.innerHTML = `
    <div class="market-sentiment-chips">${countChips}</div>
    <div class="market-evidence-list market-evidence-list--compact">
      ${items.slice(0, 4).map(renderMarketEvidenceItem).join("")}
    </div>
  `;
}

function renderMarketHypotheses() {
  const hypotheses = state.marketHypotheses || [];
  els.marketHypothesisState.textContent = hypotheses.length ? `${hypotheses.length} 条` : "无策略假设";
  els.marketHypothesesList.innerHTML = hypotheses.length
    ? hypotheses.map((item) => `
      <article class="market-hypothesis-card">
        <div class="market-hypothesis-card__head">
          <strong>${escapeHtml(item.title)}</strong>
          ${chipHtml(hypothesisStatusText(item.status), hypothesisStatusClass(item.status))}
        </div>
        <p>${escapeHtml(item.rationale || "暂无 rationale。")}</p>
        <button type="button" class="link-button" data-market-hypothesis-id="${escapeHtml(item.hypothesis_id)}">假设详情</button>
      </article>
    `).join("")
    : emptyState(marketMissingDataText(state.marketHypothesesEnvelope?.data) || "暂无策略假设。");
}

function renderMarketEvidenceItem(item) {
  return `
    <article class="market-evidence-item" data-evidence-columns="provider/date/sentiment">
      <div class="market-evidence-item__head">
        <strong>${escapeHtml(item.title || "外部证据")}</strong>
        ${chipHtml(sentimentText(item.sentiment), sentimentClass(item.sentiment))}
      </div>
      <p>${escapeHtml(item.summary || "暂无摘要。")}</p>
      <dl>
        <dt>provider</dt>
        <dd>${escapeHtml(item.provider || "unknown")}</dd>
        <dt>date</dt>
        <dd>${displayDate(item.published_date)}</dd>
        <dt>source_hash</dt>
        <dd>${escapeHtml(item.source_hash || "-")}</dd>
        <dt>type</dt>
        <dd>${escapeHtml(itemTypeText(item.item_type))}</dd>
        <dt>importance</dt>
        <dd>${escapeHtml(importanceText(item.importance))}</dd>
        <dt>scope</dt>
        <dd>${escapeHtml(scopeText(item.scope_type, item.scope_key))}</dd>
      </dl>
      <div class="market-evidence-source">
        <span>source metadata</span>
        ${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">来源链接</a>` : `<em>无 URL</em>`}
      </div>
    </article>
  `;
}

function renderAgentAdvice(advice, { expanded }) {
  const supportingPoints = listValue(advice.supporting_points);
  const riskPoints = listValue(advice.risk_points);
  const analystReports = normalizedAgentAnalystReports(advice);
  const reportSections = normalizedAgentReportSections(advice);
  const artifacts = Array.isArray(advice.artifacts) ? advice.artifacts : [];
  const sourceRefs = listValue(advice.source_refs);
  const unavailable = agentAdviceUnavailable(advice);
  const summary = advice.summary || advice.note || agentUnavailableText(advice);
  const sourceLabel = advice.source_label || agentSourceText(advice.execution_mode);
  const quickPoints = !expanded && (supportingPoints.length || riskPoints.length)
    ? `
      <div class="agent-quick-points">
        ${supportingPoints[0] ? `<p><span>支持</span>${escapeHtml(supportingPoints[0])}</p>` : ""}
        ${riskPoints[0] ? `<p><span>风险</span>${escapeHtml(riskPoints[0])}</p>` : ""}
      </div>
    `
    : "";
  const detail = expanded
    ? `
      ${unavailable ? emptyState(agentUnavailableText(advice)) : ""}
      <div class="agent-detail-grid">
        ${renderAgentPointSection("支持依据", supportingPoints, "暂无支持依据。")}
        ${renderAgentPointSection("风险提示", riskPoints, "暂无风险提示。")}
      </div>
      <div class="agent-analyst-grid">
        ${analystReports.map(renderAgentAnalystCard).join("")}
      </div>
      ${renderAgentStructuredSections(reportSections)}
      ${renderAgentEvidence(advice.external_evidence)}
      ${renderAgentMissingDataWarnings(advice.missing_data_warnings)}
      ${renderAgentSourceRefs(sourceRefs)}
      ${artifacts.length ? `
        <div class="agent-artifacts">
          <h3>复核产物</h3>
          <div class="agent-artifact-list">
            ${artifacts.map((artifact) => `
              <span>${escapeHtml(agentArtifactText(artifact.artifact_type))} #${dash(artifact.artifact_id)}</span>
            `).join("")}
          </div>
        </div>
      ` : ""}
      ${advice.report_markdown ? `
        <details class="agent-report">
          <summary>原始报告</summary>
          <pre>${escapeHtml(advice.report_markdown)}</pre>
        </details>
      ` : ""}
    `
    : "";
  return `
    <div class="agent-report-card ${unavailable ? "agent-report-card--empty" : ""}">
      <div class="agent-report-head">
        <div>
          <span class="agent-kicker">TradingAgents 输出</span>
          <h3>${unavailable ? "未返回可用复核意见" : "中文复核报告"}</h3>
        </div>
        ${chipHtml("只读 advisory", "chip-agent")}
      </div>
      <div class="agent-source-boundary" aria-label="Agent 来源边界">
        <span>TradingAgents 输出：意见、置信度、风险和分析摘要</span>
        <span>系统复盘原始数据：候选、计划、数据质量和成交事实</span>
        <span>外部证据：仅展示已缓存的技术、基本面、新闻公告和情绪资料</span>
      </div>
      <div class="action-meta agent-report-metrics">
        <div class="metric"><span>运行状态</span><strong>${agentRunStatusText(advice.status)}</strong></div>
        <div class="metric"><span>输出来源</span><strong>${escapeHtml(sourceLabel)}</strong></div>
        <div class="metric"><span>意见</span><strong>${agentActionText(advice.action)}</strong></div>
        <div class="metric"><span>风险等级</span><strong>${riskText(advice.risk_level)}</strong></div>
        <div class="metric"><span>置信度</span><strong>${advice.confidence == null ? "-" : numberText(advice.confidence, 2)}</strong></div>
      </div>
      ${renderAgentCoverage(advice.external_data_coverage)}
      <p class="agent-summary-text">${escapeHtml(summary)}</p>
      ${!expanded ? renderAgentSourceRefs(sourceRefs, { compact: true }) : ""}
      ${quickPoints}
      ${detail}
      <p class="muted">Agent 只提供复核意见，不会自动发布、取消或记录成交，也不会向券商执行。</p>
    </div>
  `;
}

function renderAgentAnalystCard(report) {
  const supportingPoints = listValue(report.supporting_points);
  const riskPoints = listValue(report.risk_points);
  const summary = report.summary || "未接入/数据不足。";
  return `
    <section class="agent-analyst-card">
      <div class="agent-analyst-head">
        <h3>${escapeHtml(report.analyst_name || agentAnalystText(report.analyst_key))}</h3>
        ${chipHtml(agentAnalystStatusText(report.status), agentAnalystStatusClass(report.status))}
      </div>
      <p>${escapeHtml(summary)}</p>
      <div class="agent-analyst-points">
        <div>
          <span>支持</span>
          ${supportingPoints.length
            ? `<ul>${supportingPoints.map((point) => `<li>${escapeHtml(point)}</li>`).join("")}</ul>`
            : `<em>暂无</em>`}
        </div>
        <div>
          <span>风险</span>
          ${riskPoints.length
            ? `<ul>${riskPoints.map((point) => `<li>${escapeHtml(point)}</li>`).join("")}</ul>`
            : `<em>暂无</em>`}
        </div>
      </div>
    </section>
  `;
}

function normalizedAgentReportSections(advice) {
  const sections = Array.isArray(advice.report_sections) ? advice.report_sections : [];
  const byKey = Object.fromEntries(
    sections
      .filter((section) => section && section.section_key)
      .map((section) => [section.section_key, section])
  );
  return AGENT_REPORT_SECTIONS.map(([key, name]) => {
    const section = byKey[key];
    if (section) {
      return { ...section, section_key: key, section_name: section.section_name || name };
    }
    return {
      section_key: key,
      section_name: name,
      status: key === "risk" || key === "conclusion" ? "partial" : "unavailable",
      source_label: advice.source_label || agentSourceText(advice.execution_mode),
      source_refs: [],
      summary: key === "conclusion"
        ? (advice.summary || advice.note || "未返回结论。")
        : "未接入/数据不足。",
      supporting_points: [],
      risk_points: key === "risk" ? listValue(advice.risk_points) : [],
    };
  });
}

function renderAgentStructuredSections(sections) {
  return `
    <section class="agent-structured-report">
      <div class="agent-structured-report__head">
        <h3>TradingAgents 中文结构化报告</h3>
        ${chipHtml("基本面 / 新闻 / 情绪 / 技术/量价 / 板块位置 / 风险 / 结论", "chip-agent")}
      </div>
      <div class="agent-structured-report__grid">
        ${sections.map(renderAgentStructuredSection).join("")}
      </div>
    </section>
  `;
}

function renderAgentStructuredSection(section) {
  const supportingPoints = listValue(section.supporting_points);
  const riskPoints = listValue(section.risk_points);
  const sourceRefs = listValue(section.source_refs);
  return `
    <article class="agent-structured-section">
      <div class="agent-structured-section__head">
        <h3>${escapeHtml(section.section_name || agentReportSectionText(section.section_key))}</h3>
        ${chipHtml(agentAnalystStatusText(section.status), agentAnalystStatusClass(section.status))}
      </div>
      <p class="agent-section-source">${escapeHtml(section.source_label || "TradingAgents 输出")}</p>
      <p>${escapeHtml(section.summary || "未接入/数据不足。")}</p>
      ${sourceRefs.length ? `<div class="agent-section-refs">${sourceRefs.map((ref) => chipHtml(sourceRefText(ref), sourceRefClass(ref))).join("")}</div>` : ""}
      ${supportingPoints.length ? `<div class="agent-section-points"><span>支持</span><ul>${supportingPoints.map((point) => `<li>${escapeHtml(point)}</li>`).join("")}</ul></div>` : ""}
      ${riskPoints.length ? `<div class="agent-section-points"><span>风险</span><ul>${riskPoints.map((point) => `<li>${escapeHtml(point)}</li>`).join("")}</ul></div>` : ""}
    </article>
  `;
}

function normalizedAgentAnalystReports(advice) {
  const reports = Array.isArray(advice.analyst_reports) ? advice.analyst_reports : [];
  const byKey = Object.fromEntries(
    reports
      .filter((report) => report && report.analyst_key)
      .map((report) => [report.analyst_key, report])
  );
  return AGENT_ANALYST_SECTIONS.map(([key, name]) => {
    const report = byKey[key];
    if (report) {
      return { ...report, analyst_key: key, analyst_name: report.analyst_name || name };
    }
    return {
      analyst_key: key,
      analyst_name: name,
      status: "unavailable",
      summary: "未接入/数据不足。",
      supporting_points: [],
      risk_points: [],
    };
  });
}

function normalizedAgentCoverage(coverage) {
  const source = coverage && typeof coverage === "object" ? coverage : {};
  return AGENT_ANALYST_SECTIONS.map(([key, name]) => {
    const status = ["available", "partial", "unavailable"].includes(source[key])
      ? source[key]
      : "unavailable";
    return { key, name, status };
  });
}

function renderAgentCoverage(coverage) {
  const items = normalizedAgentCoverage(coverage);
  return `
    <section class="agent-coverage" aria-label="Agent 外部数据覆盖">
      <div class="agent-coverage__head">
        <span>数据覆盖 external_data_coverage</span>
        ${chipHtml("Agent 是否影响交易计划：否，仅供参考", "chip-agent")}
      </div>
      <div class="agent-coverage__grid">
        ${items.map((item) => `
          <div class="agent-coverage__item">
            <span>${escapeHtml(item.name)}</span>
            ${chipHtml(agentCoverageText(item.status), agentCoverageClass(item.status))}
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function renderAgentEvidence(evidence) {
  const rows = Array.isArray(evidence) ? evidence.filter(Boolean).slice(0, 24) : [];
  return `
    <section class="agent-evidence" aria-label="Agent 外部证据">
      <div class="agent-evidence__head">
        <span>外部证据</span>
        ${chipHtml(rows.length ? `${rows.length} 条缓存` : "未接入/缺失", rows.length ? "chip-indigo" : "chip-neutral")}
      </div>
      ${rows.length ? `
        <div class="agent-evidence-list">
          ${rows.map((item) => `
            <article class="agent-evidence-item">
              <div>
                <strong>${escapeHtml(item.title || "外部证据")}</strong>
                <span>${escapeHtml(agentEvidenceCategoryText(item.category))} · ${escapeHtml(item.source || "unknown")} · ${dash(item.published_date)}</span>
              </div>
              <p>${escapeHtml(item.summary || "已缓存，暂无摘要。")}</p>
            </article>
          `).join("")}
        </div>
      ` : `<p class="muted">未接入/缺失：没有可展示的外部证据，Agent 不得补写或猜测外部资料。</p>`}
    </section>
  `;
}

function renderAgentMissingDataWarnings(warnings) {
  const rows = listValue(warnings);
  if (!rows.length) return "";
  return `
    <section class="agent-missing-data" aria-label="Agent 未接入或缺失数据">
      <div class="agent-missing-data__head">
        <span>未接入/缺失</span>
        ${chipHtml(`${rows.length} 条提醒`, "chip-neutral")}
      </div>
      <ul>
        ${rows.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    </section>
  `;
}

function renderAgentSourceRefs(sourceRefs, { compact = false } = {}) {
  const visibleRefs = compact ? sourceRefs.slice(0, 4) : sourceRefs;
  const moreCount = sourceRefs.length - visibleRefs.length;
  return `
    <section class="agent-source-refs">
      <div class="agent-source-refs__head">
        <span>来源边界 source_refs</span>
        ${chipHtml(sourceRefs.length ? `${sourceRefs.length} 个来源` : "未接入/数据不足", sourceRefs.length ? "chip-blue" : "chip-neutral")}
      </div>
      ${visibleRefs.length ? `
        <div class="agent-source-ref-list">
          ${visibleRefs.map((ref) => chipHtml(sourceRefText(ref), sourceRefClass(ref))).join("")}
          ${moreCount > 0 ? chipHtml(`+${moreCount}`, "chip-neutral") : ""}
        </div>
      ` : `<p class="muted">未接入/数据不足：没有可展示的 TradingAgents 输入来源，不能补写或猜测外部资料。</p>`}
    </section>
  `;
}

function agentAdviceUnavailable(advice) {
  return !advice.agent_run_id || ["not_run", "skipped", "unavailable"].includes(advice.status);
}

function agentUnavailableText(advice) {
  if (advice.status === "failed") return advice.note || "TradingAgents 复核失败，需人工复核。";
  if (advice.status === "skipped") return advice.note || "TradingAgents 已跳过；未产生可展示的 Agent 输出。";
  return advice.note || "TradingAgents 未运行或不可用；未产生可展示的 Agent 输出。";
}

function sourceRefText(ref) {
  const text = String(ref || "").trim();
  return text || "未接入/数据不足";
}

function sourceRefClass(ref) {
  const text = String(ref || "");
  if (text.startsWith("agent_external_items:")) return "chip-indigo";
  if (text.startsWith("market_diagnostic_bars:")) return "chip-amber";
  if (text.startsWith("market_review_runs:") || text.startsWith("sector_daily_snapshots:") || text.startsWith("sector_constituents:")) return "chip-green";
  if (text.startsWith("market_bars:") || text.startsWith("daily_basic_snapshots:")) return "chip-blue";
  return "chip-neutral";
}

function renderAgentPointSection(title, points, emptyText) {
  return `
    <section class="agent-point-section">
      <h3>${escapeHtml(title)}</h3>
      ${points.length
        ? `<ul>${points.map((point) => `<li>${escapeHtml(point)}</li>`).join("")}</ul>`
        : `<p class="muted">${escapeHtml(emptyText)}</p>`}
    </section>
  `;
}

function renderPlans() {
  const blocked = hasBlockingQuality();
  const plans = filteredTradePlans();
  els.plansBody.innerHTML = plans.length
    ? plans.map((plan) => {
      const canPublish = !blocked && plan.status === "draft";
      const canCancel = ["draft", "active"].includes(plan.status);
      const recordLockReason = recordLockReasonForPlanAction(plan);
      const canRecord = !recordLockReason;
      return `
        <tr>
          <td>${plan.id}</td>
          <td>${escapeHtml(planStockText(plan))}</td>
          <td>${chipHtml(actionText(plan.action), actionClass(plan.action))}</td>
          <td>${chipHtml(statusText(plan.status), statusClass(plan.status))}</td>
          <td>${displayDate(plan.as_of_date)}</td>
          <td>${displayDate(planTradeDate(plan))}</td>
          <td class="num">${integerText(plannedShares(plan))}</td>
          <td class="num">${money(plannedCash(plan))}</td>
          <td>${escapeHtml(reasonText(plan.reason))}</td>
          <td>
            <div class="row-actions">
              <button type="button" data-plan-action="detail" data-plan-id="${plan.id}">详情</button>
              <button type="button" data-plan-action="publish" data-plan-id="${plan.id}" ${canPublish ? "" : "disabled"}>发布</button>
              <button type="button" data-plan-action="record" data-plan-id="${plan.id}" title="${escapeHtml(recordLockReason || "录入成交")}" ${canRecord ? "" : "disabled"}>成交</button>
              <button type="button" data-plan-action="cancel" data-plan-id="${plan.id}" ${canCancel ? "" : "disabled"}>取消</button>
            </div>
          </td>
        </tr>
      `;
    }).join("")
    : emptyRow(10, "没有交易计划。");
  renderRecordQueue();
}

function renderRecordQueue() {
  const activePlans = state.tradePlans.filter((plan) => plan.status === "active");
  const due = duePositions();
  const planRows = activePlans.map((plan) => {
    const lockReason = recordLockReasonForPlanAction(plan);
    return `
      <div class="list-row">
        ${chipHtml(actionText(plan.action), actionClass(plan.action))}
        <span>计划 ${plan.id} / ${escapeHtml(planStockText(plan))} / 交易日 ${displayDate(planTradeDate(plan))} / 股数 ${integerText(plannedShares(plan))}${lockReason ? ` / 锁定：${escapeHtml(lockReason)}` : ""}</span>
        <button type="button" data-record-plan-id="${plan.id}" title="${escapeHtml(lockReason || "录入成交")}" ${lockReason ? "disabled" : ""}>录入</button>
      </div>
    `;
  });
  const positionRows = due.map((position) => `
    <div class="list-row">
      ${chipHtml(dueText(position.action_due || position.due_stage), dueClass(position.action_due || position.due_stage))}
      <span>持仓 ${position.position_id} / ${escapeHtml(position.ts_code)} ${escapeHtml(position.name)}</span>
      <button type="button" data-record-position-id="${position.position_id}">卖出</button>
    </div>
  `);
  els.recordQueue.innerHTML = [...planRows, ...positionRows].join("") || emptyState("没有待录入的 active 计划或到期持仓。");
  setRecordFormState();
}

function renderPositions() {
  const ordered = orderedPositions();
  els.positionsBody.innerHTML = ordered.length
    ? ordered.map((position) => `
      <tr class="${position.due_stage || position.action_due ? "row-due" : ""}">
        <td>${position.position_id}</td>
        <td>${escapeHtml(position.ts_code)} ${escapeHtml(position.name)}</td>
        <td>${displayDate(position.buy_date)}</td>
        <td class="num">${numberText(position.buy_price, 2)}</td>
        <td class="num">${integerText(position.shares)}</td>
        <td>${displayDate(position.planned_t2_date)}</td>
        <td>${displayDate(position.planned_t5_date)}</td>
        <td>${chipHtml(statusText(position.status), statusClass(position.status))}</td>
        <td class="num ${returnClass(position.unrealized_ret)}">${percent(position.unrealized_ret)}</td>
        <td>
          <div class="row-actions">
            <button type="button" data-position-action="detail" data-position-id="${position.position_id}">详情</button>
            <button type="button" data-position-action="sell" data-position-id="${position.position_id}">卖出</button>
          </div>
        </td>
      </tr>
    `).join("")
    : emptyRow(10, "当前账户没有未平仓持仓。");
}

function renderQuality() {
  els.qualityBody.innerHTML = state.qualityEvents.length
    ? state.qualityEvents.map((event) => `
      <tr>
        <td>${event.id}</td>
        <td>${chipHtml(severityText(event.severity), severityClass(event.severity))}</td>
        <td>${escapeHtml(event.layer)}</td>
        <td>${escapeHtml(event.event_code)}</td>
        <td>${displayDate(event.trade_date)}</td>
        <td>${escapeHtml(event.ts_code || "-")}</td>
        <td>${escapeHtml(event.message)}</td>
        <td>${statusText(event.status)}</td>
        <td>
          <button type="button" data-quality-action="detail" data-quality-id="${event.id}">详情</button>
        </td>
      </tr>
    `).join("")
    : emptyRow(9, "当前筛选下没有 open 数据质量事件。");
}

function renderBadges() {
  const blockers = blockingEvents().length;
  const acceptance = paperAcceptanceData();
  const decision = nextDayDecisionData();
  const acceptanceBlockers = acceptanceBlockerList(acceptance).length;
  const activePlans = state.tradePlans.filter((plan) => plan.status === "active").length;
  const draftPlans = state.tradePlans.filter((plan) => plan.status === "draft").length;
  const due = duePositions().length;
  els.executionBadge.textContent = String(todaysBuyPlans().filter((plan) => plan.status === "active").length + due);
  els.decisionBadge.textContent = decision?.blocker_count ? String(decision.blocker_count) : decisionStatusText(decision?.status);
  els.reviewBadge.textContent = blockers ? String(blockers) : state.report?.buy_plan ? "1" : "0";
  els.marketBadge.textContent = state.marketReview?.exists ? String(state.marketSectors.length || 1) : "0";
  els.acceptanceBadge.textContent = acceptanceBlockers ? String(acceptanceBlockers) : acceptanceStatusText(acceptance?.status);
  els.opsBadge.textContent = String(state.opsHistory?.items?.length || 0);
  els.hypothesesBadge.textContent = String(state.strategyHypothesisWorkbench?.summary?.total || 0);
  els.plansBadge.textContent = String(activePlans + draftPlans);
  els.recordBadge.textContent = String(activePlans + due);
  els.positionsBadge.textContent = String(state.positions.length);
  els.qualityBadge.textContent = String(blockers);
}

function onPlansTableClick(event) {
  const button = event.target.closest("button[data-plan-action]");
  if (!button) return;
  const plan = findPlan(Number(button.dataset.planId));
  if (!plan) return;
  const action = button.dataset.planAction;
  if (action === "detail") selectPlan(plan);
  if (action === "publish") publishPlan(plan.id);
  if (action === "cancel") cancelPlan(plan.id);
  if (action === "record") selectPlan(plan, { openRecordPage: true });
}

function onRecordQueueClick(event) {
  const planButton = event.target.closest("button[data-record-plan-id]");
  if (planButton) {
    const plan = findPlan(Number(planButton.dataset.recordPlanId));
    if (plan) selectPlan(plan, { openRecordPage: true });
    return;
  }
  const positionButton = event.target.closest("button[data-record-position-id]");
  if (positionButton) {
    const position = findPosition(Number(positionButton.dataset.recordPositionId));
    if (position) selectPosition(position, { openRecordPage: true });
  }
}

function onWorkflowGuideClick(event) {
  const button = event.target.closest("button[data-guidance-action]");
  if (!button) return;
  const action = button.dataset.guidanceAction;
  const planId = Number(button.dataset.planId);
  const positionId = Number(button.dataset.positionId);
  const plan = planId ? selectedRecordPlan(planId) : null;
  const position = positionId ? findPosition(positionId) : null;

  if (action === "refresh") refreshAll();
  if (action === "context") focusContextForm();
  if (action === "quality") setActivePage("quality");
  if (action === "review") setActivePage("review");
  if (action === "plans") setActivePage("plans");
  if (action === "checklist") focusPreOpenChecklist();
  if (action === "exits") evaluateExits();
  if (action === "record-plan" && plan) selectPlan(plan, { openRecordPage: true });
  if (action === "plan-detail" && plan) selectPlan(plan);
  if (action === "publish-plan" && planId) publishPlan(planId);
  if (action === "record-position" && position) selectPosition(position, { openRecordPage: true });
}

function focusContextForm() {
  els.contextForm.scrollIntoView({ block: "center", behavior: "smooth" });
  els.asOfDateInput.focus();
}

function focusPreOpenChecklist() {
  els.preOpenChecklist.scrollIntoView({ block: "center", behavior: "smooth" });
  const firstUnchecked = els.preOpenChecklist.querySelector("input[data-preopen-check]:not(:checked):not(:disabled)");
  if (firstUnchecked) firstUnchecked.focus();
}

function onPositionsTableClick(event) {
  const button = event.target.closest("button[data-position-action]");
  if (!button) return;
  const position = findPosition(Number(button.dataset.positionId));
  if (!position) return;
  if (button.dataset.positionAction === "detail") selectPosition(position);
  if (button.dataset.positionAction === "sell") selectPosition(position, { openRecordPage: true });
}

function onQualityTableClick(event) {
  const button = event.target.closest("button[data-quality-action]");
  if (!button) return;
  const qualityEvent = findQualityEvent(Number(button.dataset.qualityId));
  if (qualityEvent) openQualityEventDrawer(qualityEvent);
}

function onMarketSectorClick(event) {
  const button = event.target.closest("button[data-market-sector-action]");
  if (!button) return;
  const sector = findMarketSector(button.dataset.sectorCode);
  if (sector) openMarketSectorDrawer(sector);
}

function onMarketPlanContextClick(event) {
  const button = event.target.closest("button[data-market-plan-action]");
  if (!button) return;
  const plan = marketPlanForContext(button.dataset.planId);
  if (plan) selectPlan(plan);
}

function onMarketHypothesisClick(event) {
  const button = event.target.closest("button[data-market-hypothesis-id]");
  if (!button) return;
  const hypothesis = findMarketHypothesis(Number(button.dataset.marketHypothesisId));
  if (hypothesis) openMarketHypothesisDrawer(hypothesis);
}

function onStrategyHypothesisWorkbenchClick(event) {
  const pageButton = event.target.closest("button[data-page-jump]");
  if (pageButton) {
    setActivePage(pageButton.dataset.pageJump);
    return;
  }
  const reviewButton = event.target.closest("button[data-strategy-proposal-review]");
  if (reviewButton) {
    const evaluation = findStrategyHypothesisEvaluation(Number(reviewButton.dataset.strategyHypothesisId));
    if (evaluation) reviewStrategyVersionProposal(evaluation, reviewButton.dataset.strategyProposalReview);
    return;
  }
  const button = event.target.closest("button[data-strategy-hypothesis-id]");
  if (!button) return;
  const evaluation = findStrategyHypothesisEvaluation(Number(button.dataset.strategyHypothesisId));
  if (evaluation) openStrategyHypothesisEvaluationDrawer(evaluation);
}

function onDrawerActionClick(event) {
  const button = event.target.closest("button[data-drawer-action]");
  if (!button) return;
  const action = button.dataset.drawerAction;
  const planId = Number(button.dataset.planId);
  const positionId = Number(button.dataset.positionId);
  const plan = planId ? selectedRecordPlan(planId) : null;
  const position = positionId ? findPosition(positionId) : null;

  if (action === "page" && button.dataset.page) setActivePage(button.dataset.page);
  if (action === "lineage") openLineageDrawer();
  if (action === "candidate") openCandidateDrawer();
  if (action === "agent") openAgentDrawer();
  if (action === "market-news") openMarketNewsDrawer(button.dataset.scopeType, button.dataset.scopeKey);
  if (action === "strategy-proposal-review") {
    const evaluation = findStrategyHypothesisEvaluation(Number(button.dataset.strategyHypothesisId));
    if (evaluation) reviewStrategyVersionProposal(evaluation, button.dataset.decision);
  }
  if (action === "record-plan" && plan) selectPlan(plan, { openRecordPage: true });
  if (action === "publish-plan" && planId) publishPlan(planId);
  if (action === "cancel-plan" && planId) cancelPlan(planId);
  if (action === "record-position" && position) selectPosition(position, { openRecordPage: true });
}

function selectPlan(plan, options = {}) {
  state.selectedPlan = plan;
  if (options.openRecordPage) {
    fillRecordFromPlan(plan);
    closeDrawer();
    setActivePage("record");
    return;
  }
  const recordLockReason = recordLockReasonForPlanAction(plan);
  openDetailDrawer({
    kicker: "交易计划",
    title: `计划 ${plan.id} · ${planStockText(plan)}`,
    subtitle: "计划、信号、成交入口在统一详情面板中核对；计划不是成交事实。",
    meta: [
      [statusText(plan.status), statusClass(plan.status)],
      [actionText(plan.action), actionClass(plan.action)],
      [`交易日 ${displayDate(planTradeDate(plan))}`, "chip-neutral"],
    ],
    actions: [
      { label: "录入成交", action: "record-plan", planId: plan.id, primary: true, disabled: Boolean(recordLockReason), title: recordLockReason || "按该计划录入成交" },
      { label: "发布计划", action: "publish-plan", planId: plan.id, disabled: hasBlockingQuality() || plan.status !== "draft" },
      { label: "取消计划", action: "cancel-plan", planId: plan.id, disabled: !["draft", "active"].includes(plan.status) },
    ],
    sections: [
      detailSection("摘要", detailMetrics([
        ["计划 ID", plan.id],
        ["股票", planStockText(plan)],
        ["计划股数", integerText(plannedShares(plan))],
        ["计划资金", money(plannedCash(plan))],
      ])),
      detailSection("计划边界", detailRows([
        ["账户 ID", plan.account_id],
        ["生成日", displayDate(plan.as_of_date)],
        ["计划交易日", displayDate(planTradeDate(plan))],
        ["操作者", dash(plan.operator)],
        ["创建时间", dash(plan.created_at)],
      ])),
      detailSection("血缘与原因", detailRows([
        ["入选记录", dash(planDailyPickId(plan))],
        ["信号记录", dash(planSignalId(plan))],
        ["原因", reasonText(plan.reason)],
        ["取消原因", plan.cancel_reason || "-"],
        ["录入锁定", recordLockReason || "无"],
      ])),
    ],
  });
}

function selectPosition(position, options = {}) {
  state.selectedPosition = position;
  if (options.openRecordPage) {
    fillRecordFromPosition(position);
    closeDrawer();
    setActivePage("record");
    return;
  }
  const returnChipClass = position.unrealized_ret == null ? "chip-neutral" : Number(position.unrealized_ret) >= 0 ? "chip-green" : "chip-red";
  openDetailDrawer({
    kicker: "持仓",
    title: `${position.ts_code} ${position.name}`,
    subtitle: "持仓详情只展示账本与行情派生状态；卖出仍需人工成交事实。",
    meta: [
      [statusText(position.status), statusClass(position.status)],
      [dueText(position.due_stage || position.action_due), dueClass(position.due_stage || position.action_due)],
      [`收益 ${percent(position.unrealized_ret)}`, returnChipClass],
    ],
    actions: [
      { label: "卖出录入", action: "record-position", positionId: position.position_id, primary: true },
      { label: "查看持仓页", action: "page", page: "positions" },
    ],
    sections: [
      detailSection("摘要", detailMetrics([
        ["持仓 ID", position.position_id],
        ["股数", integerText(position.shares)],
        ["买入价", numberText(position.buy_price, 2)],
        ["收益", percent(position.unrealized_ret)],
      ])),
      detailSection("生命周期", detailRows([
        ["账户 ID", position.account_id],
        ["买入日", displayDate(position.buy_date)],
        ["T+2", displayDate(position.planned_t2_date)],
        ["T+5", displayDate(position.planned_t5_date)],
        ["到期阶段", dueText(position.due_stage || position.action_due)],
      ])),
      detailSection("行情边界", detailRows([
        ["最新行情日", displayDate(position.latest_trade_date)],
        ["最近收盘价", positionLatestCloseNote(position)],
        ["状态", statusText(position.status)],
      ])),
    ],
  });
}

function fillRecordFromPlan(plan) {
  clearRecordForm(false);
  const recordDate = planTradeDate(plan) || state.report?.next_trade_date || "";
  const shares = plannedShares(plan);
  const price = planReferencePrice(plan);
  els.recordPlanId.value = plan.id;
  els.recordPositionId.value = "";
  els.recordSide.value = actionIsSell(plan.action) ? "sell" : "buy";
  els.recordDate.value = dateInputValue(recordDate);
  els.recordShares.value = shares || "";
  els.recordPrice.value = inputNumber(price);
  els.recordFee.value = "0";
  els.recordTax.value = "0";
  els.recordSlippage.value = "";
  setRecordDateConstraint(recordDate);
  renderRecordReferencePanel([
    ["计划 ID", plan.id],
    ["计划日期", displayDate(recordDate)],
    ["计划价格参考", price != null ? inputNumber(price) : "-"],
    ["计划股数", integerText(shares)],
    ["目标股票", planStockText(plan)],
  ]);
  els.recordPrefillHint.textContent = `已从计划 ${plan.id} 预填：计划日期 ${displayDate(recordDate)}、计划股数 ${integerText(shares)}${price != null ? `、计划价格参考 ${inputNumber(price)}` : ""}。计划日期已用日期选择器锁定，成交价请按实际开盘成交核对。`;
  els.recordModeChip.textContent = plan.status === "active" ? "按 active 计划录入" : "计划未激活";
  els.recordModeChip.className = `chip ${plan.status === "active" ? "chip-blue" : "chip-amber"}`;
  setRecordFormState();
}

function fillRecordFromPosition(position) {
  clearRecordForm(false);
  els.recordPlanId.value = "";
  els.recordPositionId.value = position.position_id;
  els.recordSide.value = "sell";
  els.recordDate.value = dateInputValue(state.asOfDate);
  els.recordShares.value = position.shares || "";
  els.recordPrice.value = positionPriceIsStale(position) ? "" : inputNumber(position.latest_close);
  els.recordFee.value = "0";
  els.recordTax.value = "0";
  els.recordSlippage.value = "";
  setRecordDateConstraint("");
  renderRecordReferencePanel([
    ["持仓 ID", position.position_id],
    ["买入日", displayDate(position.buy_date)],
    ["持仓股数", integerText(position.shares)],
    ["最近收盘价", position.latest_close != null ? inputNumber(position.latest_close) : "-"],
    ["目标股票", positionStockText(position)],
  ]);
  const priceHint = position.latest_close != null
    ? `、最近收盘价 ${inputNumber(position.latest_close)}（行情日 ${displayDate(position.latest_trade_date)}，不是实时现价）`
    : "";
  els.recordPrefillHint.textContent = `已从持仓 ${position.position_id} 预填：成交日期 ${displayDate(state.asOfDate)}、股数 ${integerText(position.shares)}${priceHint}。卖出价请按实际成交填写。`;
  els.recordModeChip.textContent = "按持仓卖出录入";
  els.recordModeChip.className = "chip chip-amber";
  setRecordFormState();
}

function clearRecordForm(resetChip = true) {
  els.recordPlanId.value = "";
  els.recordPositionId.value = "";
  els.recordSide.value = "buy";
  els.recordDate.value = dateInputValue(state.report?.next_trade_date || state.asOfDate);
  els.recordPrice.value = "";
  els.recordShares.value = "";
  els.recordFee.value = "0";
  els.recordTax.value = "0";
  els.recordSlippage.value = "";
  setRecordDateConstraint("");
  clearRecordReferencePanel();
  els.recordPrefillHint.textContent = "从待录入队列选择计划后，会自动带出计划 ID、方向、成交日期、股数和参考价。";
  if (resetChip) {
    els.recordModeChip.textContent = "未选择";
    els.recordModeChip.className = "chip chip-neutral";
  }
  setRecordFormState();
}

function setRecordDateConstraint(plannedDate) {
  const inputDate = dateInputValue(plannedDate);
  els.recordDate.min = inputDate;
  els.recordDate.max = inputDate;
  els.recordDate.title = inputDate
    ? `计划日期已锁定为 ${displayDate(plannedDate)}`
    : "请选择实际成交日期";
}

function renderRecordReferencePanel(rows) {
  els.recordPlanReference.hidden = false;
  els.recordPlanReference.innerHTML = `
    <strong>计划参考</strong>
    <dl class="record-reference-grid">
      ${rows.map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(String(value ?? "-"))}</dd>`).join("")}
    </dl>
  `;
}

function clearRecordReferencePanel() {
  els.recordPlanReference.hidden = true;
  els.recordPlanReference.innerHTML = "";
}

function openLineageDrawer() {
  const lineage = state.report?.lineage;
  if (!lineage) {
    openDrawer("数据血缘", "暂无血缘", [["状态", "复盘报告未返回 lineage"]]);
    return;
  }
  openDetailDrawer({
    kicker: "数据血缘",
    title: `复盘日 ${displayDate(state.report.as_of_date)}`,
    subtitle: "血缘只解释本次复盘来源，不作为交易事实源。",
    meta: [
      [`策略 ${dash(lineage.strategy_run_id)}`, "chip-blue"],
      [`信号 ${dash(lineage.signal_id)}`, "chip-neutral"],
      [`计划 ${dash(lineage.trade_plan_id)}`, "chip-neutral"],
    ],
    actions: [
      { label: "候选详情", action: "candidate" },
      { label: "Agent 详情", action: "agent" },
    ],
    sections: [
      detailSection("运行链路", detailRows([
        ["特征运行", dash(lineage.feature_run_id)],
        ["策略运行", dash(lineage.strategy_run_id)],
        ["行情抓取", dash(lineage.market_fetch_run_id)],
      ])),
      detailSection("业务记录", detailRows([
        ["入选记录", dash(lineage.daily_pick_id)],
        ["信号记录", dash(lineage.signal_id)],
        ["计划记录", dash(lineage.trade_plan_id)],
        ["Agent 运行", dash(lineage.agent_run_id)],
        ["Agent 意见", dash(lineage.agent_decision_id)],
        ["质量事件", (lineage.data_quality_event_ids || []).join(", ") || "-"],
      ])),
    ],
  });
}

function openCandidateDrawer() {
  const candidate = state.report?.candidate;
  if (!candidate) {
    openDrawer("候选详情", "暂无候选", [["状态", `无候选：${reasonText(state.report?.no_candidate_reason)}`]]);
    return;
  }
  const features = candidate.features || {};
  const featureRows = Object.entries(features).map(([key, value]) => [featureLabel(key), featureValue(key, value)]);
  const signals = candidate.ranked_signals || [];
  openDetailDrawer({
    kicker: "候选详情",
    title: `${candidate.ts_code} ${candidate.name}`,
    subtitle: "候选是策略信号，不等于交易计划或已成交持仓。",
    meta: [
      [`评分 ${numberText(candidate.score, 4)}`, "chip-blue"],
      [`计划买入 ${displayDate(candidate.planned_buy_date)}`, "chip-neutral"],
      [`信号 ${dash(candidate.signal_id)}`, "chip-neutral"],
    ],
    actions: [
      { label: "查看血缘", action: "lineage" },
      { label: "交易计划", action: "page", page: "plans" },
    ],
    sections: [
      detailSection("候选摘要", detailMetrics([
        ["复盘日", displayDate(candidate.review_date || state.report?.as_of_date)],
        ["计划买入日", displayDate(candidate.planned_buy_date)],
        ["胜出信号数", dash(candidate.selected_over_signal_count)],
        ["入选原因", reasonText(candidate.selection_reason)],
      ])),
      detailSection("策略特征", featureRows.length ? detailRows(featureRows) : emptyState("候选未返回特征快照。")),
      detailSection("Ranked signals", signals.length ? detailRows(signals.map((signal) => [
        `#${dash(signal.signal_rank)} ${signal.ts_code} ${signal.name}`,
        `评分 ${numberText(signal.score, 4)} / 信号 ${dash(signal.signal_id)}`,
      ])) : emptyState("没有 ranked signals。")),
    ],
  });
}

function openQualityEventDrawer(event) {
  openDetailDrawer({
    kicker: "数据质量事件",
    title: `${event.event_code || "QUALITY_EVENT"} #${event.id}`,
    subtitle: "质量事件只解释数据状态；blocker 会阻断计划发布和成交录入。",
    meta: [
      [severityText(event.severity), severityClass(event.severity)],
      [statusText(event.status), statusClass(event.status)],
      [`交易日 ${displayDate(event.trade_date)}`, "chip-neutral"],
    ],
    actions: [
      { label: "数据质量页", action: "page", page: "quality" },
    ],
    sections: [
      detailSection("事件摘要", detailRows([
        ["事件 ID", event.id],
        ["层级", event.layer],
        ["代码", event.event_code],
        ["严重度", severityText(event.severity)],
        ["状态", statusText(event.status)],
      ])),
      detailSection("影响对象", detailRows([
        ["交易日", displayDate(event.trade_date)],
        ["股票", event.ts_code || "-"],
        ["说明", event.message || "-"],
      ])),
    ],
  });
}

function openMarketSectorDrawer(sector) {
  const sectorItems = marketItemsForScope("sector", sector.sector_code);
  openDetailDrawer({
    kicker: "板块详情",
    title: `${sector.sector_name || sector.sector_code}`,
    subtitle: "板块详情展示持续性、个股领涨和已缓存的新闻 / 情绪证据；只读，不改写计划。",
    meta: [
      [`排名 ${dash(sector.rank_overall)}`, "chip-blue"],
      [`持续性 ${scoreText(sector.persistence_score)}`, persistenceClass(sector.persistence_score)],
      [sentimentText(sectorSentiment(sector)), sentimentClass(sectorSentiment(sector))],
    ],
    actions: [
      { label: "证据详情", action: "market-news", scopeType: "sector", scopeKey: sector.sector_code },
      { label: "全市场页", action: "page", page: "market" },
    ],
    sections: [
      detailSection("板块轮动", detailMetrics([
        ["1日涨跌", percent(sector.return_1d)],
        ["3日涨跌", percent(sector.return_3d)],
        ["5日涨跌", percent(sector.return_5d)],
        ["10日涨跌", percent(sector.return_10d)],
        ["宽度", scoreText(sector.breadth_score)],
        ["量能", scoreText(sector.volume_score)],
      ])),
      detailSection("个股领涨", marketLeadershipTable(sector.constituents || [])),
      detailSection("新闻 / 情绪", sectorItems.length ? marketEvidenceTable(sectorItems) : emptyState("该板块暂无外部证据。")),
    ],
  });
}

function openMarketNewsDrawer(scopeType = "", scopeKey = "") {
  const items = scopeType && scopeKey ? marketItemsForScope(scopeType, scopeKey) : state.marketExternalItems;
  const title = scopeType && scopeKey ? `证据 · ${scopeText(scopeType, scopeKey)}` : "新闻 / 情绪证据";
  const counts = countBy(items || [], "sentiment");
  openDetailDrawer({
    kicker: "新闻 / 情绪",
    title,
    subtitle: "证据抽屉按 provider/date/sentiment 追溯来源，结论只用于人工复核。",
    meta: [
      [`证据 ${items.length}`, "chip-blue"],
      [sentimentText(dominantSentiment(counts)), sentimentClass(dominantSentiment(counts))],
      [`全市场日 ${displayDate(marketReviewDate())}`, "chip-neutral"],
    ],
    actions: [
      { label: "全市场页", action: "page", page: "market" },
    ],
    sections: [
      detailSection("证据列表", items.length ? marketEvidenceTable(items) : emptyState("暂无新闻 / 情绪证据。")),
    ],
  });
}

function openMarketHypothesisDrawer(hypothesis) {
  const evaluation = findStrategyHypothesisEvaluation(hypothesis.hypothesis_id);
  openDetailDrawer({
    kicker: "策略假设",
    title: hypothesis.title || `假设 ${hypothesis.hypothesis_id}`,
    subtitle: "策略假设进入研究和回测流程，不直接改策略参数或交易计划。",
    meta: [
      [hypothesisStatusText(hypothesis.status), hypothesisStatusClass(hypothesis.status)],
      [dash(hypothesis.hypothesis_type), "chip-neutral"],
      [`复盘日 ${displayDate(hypothesis.as_of_date)}`, "chip-neutral"],
    ],
    actions: [
      { label: "评估工作台", action: "page", page: "hypotheses" },
    ],
    sections: [
      detailSection("假设摘要", detailRows([
        ["假设 ID", hypothesis.hypothesis_id],
        ["状态", hypothesisStatusText(hypothesis.status)],
        ["创建时间", displayTimestamp(hypothesis.created_at)],
        ["Rationale", hypothesis.rationale || "-"],
        ["评估状态", evaluation ? hypothesisNextActionText(evaluation.next_action) : "未加载评估工作台"],
      ])),
      detailSection("证据", marketObjectRows(hypothesis.evidence)),
      detailSection("拟议变更", marketObjectRows(hypothesis.proposed_change)),
      evaluation ? detailSection("评估 gate", strategyHypothesisGateRows(evaluation)) : "",
    ],
  });
}

function openStrategyHypothesisEvaluationDrawer(evaluation) {
  const hypothesis = evaluation.hypothesis || {};
  const gate = evaluation.acceptance_gate || {};
  const safety = evaluation.safety || {};
  openDetailDrawer({
    kicker: "策略假设评估",
    title: hypothesis.title || `假设 ${hypothesis.hypothesis_id}`,
    subtitle: "评估工作台只读审阅 evidence/backtest artifact；accepted 仍需单独 strategy-version proposal。",
    meta: [
      [hypothesisStatusText(hypothesis.status), hypothesisStatusClass(hypothesis.status)],
      [hypothesisNextActionText(evaluation.next_action), hypothesisNextActionClass(evaluation.next_action)],
      [`复盘日 ${displayDate(hypothesis.as_of_date)}`, "chip-neutral"],
    ],
    actions: [
      { label: "假设评估页", action: "page", page: "hypotheses" },
      { label: "全市场页", action: "page", page: "market" },
      ...strategyProposalReviewDrawerActions(evaluation),
    ],
    sections: [
      detailSection("Acceptance gate", strategyHypothesisGateRows(evaluation)),
      detailSection("假设摘要", detailRows([
        ["假设 ID", hypothesis.hypothesis_id],
        ["类型", hypothesis.hypothesis_type],
        ["状态", hypothesisStatusText(hypothesis.status)],
        ["创建时间", displayTimestamp(hypothesis.created_at)],
        ["下一步", evaluation.next_action_label || "-"],
        ["Rationale", hypothesis.rationale || "-"],
      ])),
      detailSection("Backtest artifacts", strategyHypothesisArtifactRows(evaluation.backtest_artifacts || [])),
      detailSection(
        "Strategy-version proposal artifacts",
        strategyHypothesisProposalRows(evaluation.strategy_version_proposals || []),
      ),
      detailSection(
        "Proposal review / promotion-request artifacts",
        strategyHypothesisProposalReviewRows(evaluation.strategy_version_proposal_reviews || []),
      ),
      detailSection("Validation events", strategyHypothesisValidationEvents(evaluation.validation_events || [])),
      detailSection("Safety", detailRows([
        ["只读评估", safety.read_only_evaluation ? "是" : "-"],
        ["拟议变更是否改 active params", safety.proposed_change_mutates_active_params ? "是" : "否"],
        ["artifact 是否报告 active param mutation", safety.artifact_reports_active_param_mutation ? "是" : "否"],
        ["proposal 是否 artifact-only", safety.proposal_artifacts_only ? "是" : "-"],
        ["proposal review 是否 artifact-only", safety.proposal_review_artifacts_only ? "是" : "-"],
        ["proposal 是否写 strategy_versions", safety.proposal_wrote_strategy_versions ? "是" : "否"],
        ["本工作台写交易状态", safety.writes_trade_state ? "是" : "否"],
        ["本工作台改变 paper/live", safety.writes_paper_live_behavior ? "是" : "否"],
      ])),
      detailSection("证据", marketObjectRows(hypothesis.evidence)),
      detailSection("拟议变更", marketObjectRows(hypothesis.proposed_change)),
      evaluation.strategy_version_task
        ? detailSection("未来 strategy-version task", marketObjectRows(evaluation.strategy_version_task))
        : "",
    ],
  });
}

function openAgentDrawer() {
  const advice = state.report?.agent_advice;
  if (!advice) {
    openDrawer("Agent 详情", "暂无复核输出", [["状态", "TradingAgents 未运行或不可用"]]);
    return;
  }
  openDetailDrawer({
    kicker: "Agent 详情",
    title: "TradingAgents 中文复核报告",
    subtitle: "Agent 只读 advisory，不自动发布、取消、记录成交或向券商执行。",
    meta: [
      [agentRunStatusText(advice.status), agentRunStatusClass(advice.status)],
      [agentActionText(advice.action), "chip-agent"],
      [riskText(advice.risk_level), riskClass(advice.risk_level)],
    ],
    actions: [
      { label: "查看血缘", action: "lineage" },
      { label: "每日复盘", action: "page", page: "review" },
    ],
    sections: [
      detailSection("复核详情", renderAgentAdvice(advice, { expanded: true })),
    ],
  });
}

function openDrawer(kicker, title, rows) {
  openDetailDrawer({
    kicker,
    title,
    sections: [
      detailSection("详情", detailRows(rows)),
    ],
  });
}

function openDetailDrawer({ kicker, title, subtitle = "", meta = [], actions = [], sections = [] }) {
  els.drawerKicker.textContent = kicker;
  els.drawerTitle.textContent = title;
  els.drawerSubtitle.textContent = subtitle;
  els.drawerSubtitle.hidden = !subtitle;
  els.drawerMeta.hidden = meta.length === 0;
  els.drawerMeta.innerHTML = meta.map(([label, className]) => chipHtml(label, className)).join("");
  els.drawerActions.hidden = actions.length === 0;
  els.drawerActions.innerHTML = actions.map(drawerActionButton).join("");
  els.drawerBody.innerHTML = sections.join("") || emptyState("没有可展示的详情。");
  els.detailDrawer.hidden = false;
}

function drawerActionButton(action) {
  const attrs = [
    `data-drawer-action="${escapeHtml(action.action)}"`,
    action.planId ? `data-plan-id="${escapeHtml(action.planId)}"` : "",
    action.positionId ? `data-position-id="${escapeHtml(action.positionId)}"` : "",
    action.hypothesisId ? `data-strategy-hypothesis-id="${escapeHtml(action.hypothesisId)}"` : "",
    action.decision ? `data-decision="${escapeHtml(action.decision)}"` : "",
    action.page ? `data-page="${escapeHtml(action.page)}"` : "",
    action.scopeType ? `data-scope-type="${escapeHtml(action.scopeType)}"` : "",
    action.scopeKey ? `data-scope-key="${escapeHtml(action.scopeKey)}"` : "",
    action.title ? `title="${escapeHtml(action.title)}"` : "",
    action.disabled ? "disabled" : "",
  ].filter(Boolean).join(" ");
  return `<button type="button" ${attrs} class="${action.primary ? "primary-button" : ""}">${escapeHtml(action.label)}</button>`;
}

function detailSection(title, bodyHtml) {
  return `
    <section class="drawer-section">
      <h3>${escapeHtml(title)}</h3>
      ${bodyHtml}
    </section>
  `;
}

function detailRows(rows) {
  return `
    <dl class="kv detail-kv">
      ${rows.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(String(value ?? "-"))}</dd>`).join("")}
    </dl>
  `;
}

function detailMetrics(items) {
  return `
    <div class="drawer-metrics">
      ${items.map(([label, value]) => `
        <div class="drawer-metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value ?? "-"))}</strong></div>
      `).join("")}
    </div>
  `;
}

function closeDrawer() {
  els.detailDrawer.hidden = true;
  els.drawerBody.innerHTML = "";
  els.drawerActions.innerHTML = "";
  els.drawerMeta.innerHTML = "";
}

function setActivePage(page) {
  state.activePage = page;
  document.querySelectorAll("[data-page]").forEach((section) => {
    section.classList.toggle("active", section.dataset.page === page);
  });
  document.querySelectorAll("[data-page-button]").forEach((button) => {
    button.classList.toggle("active", button.dataset.pageButton === page);
  });
}

async function apiRequest(path, options = {}) {
  const url = `${state.apiBase}${path}`;
  const fetchOptions = {
    method: options.method || "GET",
    headers: { Accept: "application/json" },
  };
  if (shouldAttachWriteToken(options)) {
    fetchOptions.headers["X-PGC-Write-Token"] = state.writeToken;
  }
  if (options.body !== undefined) {
    fetchOptions.headers["Content-Type"] = "application/json";
    fetchOptions.body = JSON.stringify(stripUndefined(options.body));
  }
  const response = await fetch(url, fetchOptions);
  const text = await response.text();
  let payload;
  try {
    payload = text ? JSON.parse(text) : {};
  } catch (error) {
    throw new Error(`API 返回了非 JSON 响应：${response.status}`);
  }
  if (!response.ok && !("status" in payload)) {
    throw new Error(`API 请求失败：${response.status}`);
  }
  return payload;
}

function shouldAttachWriteToken(options = {}) {
  if (!state.writeToken) return false;
  const method = String(options.method || "GET").toUpperCase();
  if (method === "GET") return false;
  const body = options.body || {};
  if (body.dry_run === true) return false;
  return Boolean(body.operator && body.idempotency_key);
}

function supportedWritePayload(scope, body) {
  const payload = {
    ...body,
    dry_run: state.dryRun,
    request_id: requestId(scope),
  };
  if (!state.dryRun) {
    if (!state.operator) throw new Error("非 dry-run 写请求需要填写操作者。");
    payload.operator = state.operator;
    payload.idempotency_key = idempotencyKey(scope);
  }
  return payload;
}

function requiredWritePayload(scope, body) {
  if (!state.operator) throw new Error("写请求需要填写操作者。");
  return {
    ...body,
    request_id: requestId(scope),
    operator: state.operator,
    idempotency_key: idempotencyKey(scope),
  };
}

function selectedAccountPayload() {
  const payload = {};
  const accountId = resolvedAccountId();
  if (state.accountKey) payload.account_key = state.accountKey;
  if (accountId) payload.account_id = Number(accountId);
  return payload;
}

function resolvedAccountId() {
  return state.accountId || state.report?.account?.account_id || "";
}

function requestId(scope) {
  return `dashboard:${scope}:${state.asOfDate}:${Date.now()}`;
}

function idempotencyKey(scope) {
  return `dashboard:${scope}:${state.asOfDate}:${Date.now()}`;
}

function hasBlockingQuality() {
  return state.report?.data_quality?.readiness === "blocker" || blockingEvents().length > 0;
}

function openingReadiness(activePlans, executionDay, blocked = hasBlockingQuality()) {
  const matchingActivePlans = activePlans.filter((plan) => planTradeDate(plan) === executionDay);
  const manualComplete = manualPreOpenChecksComplete();
  const hasExecutionPlan = matchingActivePlans.length > 0;
  const checkedCount = Object.values(state.preOpenChecks).filter(Boolean).length + (hasExecutionPlan ? 1 : 0);
  const totalChecks = Object.keys(state.preOpenChecks).length + 1;
  let lockReason = "";
  if (blocked) {
    lockReason = ledgerBlockerCount() ? "账本 invariant blocker 未处理" : "数据质量 blocker 未处理";
  } else if (!hasExecutionPlan) {
    lockReason = "没有计划交易日匹配执行日的 active 买入计划";
  } else if (!manualComplete) {
    lockReason = "开盘检查未完成";
  }
  return {
    ready: !lockReason,
    lockReason,
    blocked,
    blockerCount: blockingEvents().length,
    hasExecutionPlan,
    matchingActiveCount: matchingActivePlans.length,
    manualComplete,
    checkedCount,
    totalChecks,
  };
}

function manualPreOpenChecksComplete() {
  return Object.values(state.preOpenChecks).every(Boolean);
}

function resetPreOpenChecks() {
  for (const key of Object.keys(state.preOpenChecks)) {
    state.preOpenChecks[key] = false;
  }
}

function preOpenContextKey() {
  return [state.accountKey, state.accountId, executionDate(), state.strategyVersion].join("|");
}

function openingRecordReady(activePlans, executionDay, blocked = hasBlockingQuality()) {
  return openingReadiness(activePlans, executionDay, blocked).ready;
}

function recordLockReasonForPlan(plan, executionDay) {
  if (hasBlockingQuality()) return ledgerBlockerCount() ? "账本 invariant blocker 未处理" : "数据质量 blocker 未处理";
  if (plan.status !== "active") return "计划不是 active";
  if (planTradeDate(plan) !== executionDay) return "计划交易日与执行日不一致";
  if (!manualPreOpenChecksComplete()) return "开盘检查未完成";
  return "";
}

function recordLockReasonForPlanAction(plan, executionDay = executionDate()) {
  if (isBuyPlan(plan)) return recordLockReasonForPlan(plan, executionDay);
  if (hasBlockingQuality()) return ledgerBlockerCount() ? "账本 invariant blocker 未处理" : "数据质量 blocker 未处理";
  if (plan.status !== "active") return "计划不是 active";
  return "";
}

function blockingEvents() {
  const envelopeErrors = (state.reportEnvelope?.errors || []).filter((error) => {
    return error.severity === "blocker" || error.code === "VALIDATION_ERROR";
  });
  const ledgerErrors = envelopeErrors.filter(isLedgerInvariantError);
  const otherEnvelopeErrors = envelopeErrors.filter((error) => !isLedgerInvariantError(error));
  const qualityBlockers = state.qualityEvents.filter((event) => event.severity === "blocker");
  const readinessBlocker = state.report?.data_quality?.readiness === "blocker"
    ? [{
      severity: "blocker",
      code: "READINESS_BLOCKER",
      message: ledgerErrors.length
        ? `复盘日 ${displayDate(state.asOfDate)} 账本 invariant 检查失败。`
        : `复盘日 ${displayDate(state.asOfDate)} 数据状态为 blocker。`,
    }]
    : [];
  return [...ledgerErrors, ...readinessBlocker, ...otherEnvelopeErrors, ...qualityBlockers];
}

function isLedgerInvariantError(error) {
  return error?.code === "DATABASE_INVARIANTS_FAILED" || String(error?.code || "").includes("INVARIANT");
}

function ledgerBlockerCount() {
  return (state.reportEnvelope?.errors || []).filter(isLedgerInvariantError).length;
}

function duePositions() {
  const reportDue = (state.report?.due_positions || []).filter(isExitDuePosition);
  if (reportDue.length) return reportDue;
  return state.positions.filter(isExitDuePosition);
}

function isExitDuePosition(position) {
  const marker = position?.due_stage ?? position?.action_due;
  return marker != null && !["", "none", "null", "undefined"].includes(String(marker));
}

function orderedPositions() {
  return [...state.positions].sort((a, b) => {
    const aDue = a.due_stage || a.action_due ? 0 : 1;
    const bDue = b.due_stage || b.action_due ? 0 : 1;
    if (aDue !== bDue) return aDue - bDue;
    return String(a.planned_t2_date || "").localeCompare(String(b.planned_t2_date || ""));
  });
}

function filteredTradePlans() {
  const status = els.planStatusFilter.value;
  return status ? state.tradePlans.filter((plan) => plan.status === status) : state.tradePlans;
}

function activeBuyPlans() {
  return state.tradePlans.filter((plan) => isBuyPlan(plan) && ["draft", "active"].includes(plan.status));
}

function todaysBuyPlans() {
  const day = executionDate();
  return activeBuyPlans().filter((plan) => planTradeDate(plan) === day);
}

function executionDate() {
  return normalizeDate(state.executionAsOfDate || state.report?.next_trade_date || state.asOfDate);
}

function lockExecutionDate(value) {
  const nextDate = normalizeDate(value);
  if (!/^\d{8}$/.test(nextDate)) return;
  state.executionAsOfDate = nextDate;
  state.executionDatePinned = true;
}

function syncExecutionDateFromReport() {
  const nextDate = normalizeDate(state.report?.next_trade_date);
  if (state.executionDatePinned || !/^\d{8}$/.test(nextDate)) return;
  state.executionAsOfDate = nextDate;
}

function findPlan(id) {
  return state.tradePlans.find((plan) => Number(plan.id) === Number(id));
}

function findPosition(id) {
  return state.positions.find((position) => Number(position.position_id) === Number(id));
}

function findQualityEvent(id) {
  return state.qualityEvents.find((event) => Number(event.id) === Number(id));
}

function positionPriceIsStale(position) {
  const marketDate = normalizeDate(position?.latest_trade_date);
  const asOfDate = normalizeDate(state.asOfDate);
  return Boolean(marketDate && asOfDate && marketDate < asOfDate);
}

function positionLatestCloseNote(position) {
  if (position?.latest_close == null || position.latest_close === "") return "-";
  const marketDate = displayDate(position.latest_trade_date);
  const prefix = `${numberText(position.latest_close, 2)} / ${marketDate} 收盘`;
  return positionPriceIsStale(position) ? `${prefix}，不是实时现价` : prefix;
}

function planFromReport(plan) {
  const candidate = state.report?.candidate;
  return {
    id: plan.trade_plan_id,
    account_id: state.report?.account?.account_id,
    action: plan.action,
    status: plan.status,
    as_of_date: state.report?.as_of_date,
    planned_trade_date: plan.planned_trade_date,
    planned_buy_date: plan.planned_buy_date,
    reason: plan.reason,
    cancel_reason: null,
    daily_pick_id: candidate?.daily_pick_id || state.report?.lineage?.daily_pick_id,
    signal_id: candidate?.signal_id || state.report?.lineage?.signal_id,
    ts_code: candidate?.ts_code,
    name: candidate?.name,
    planned_cash: plan.planned_cash,
    planned_shares: plan.planned_shares,
    price_reference: plan.price_reference,
    price_reference_date: plan.price_reference_date,
  };
}

function planTradeDate(plan) {
  return normalizeDate(plan?.planned_trade_date || plan?.planned_buy_date || "");
}

function planStockText(plan) {
  const tsCode = plan?.ts_code || plan?.stock_code || plan?.symbol || plan?.plan_json?.ts_code;
  const name = plan?.name || plan?.stock_name || plan?.plan_json?.name;
  if (tsCode && name) return `${tsCode} ${name}`;
  return tsCode || name || "-";
}

function positionStockText(position) {
  if (!position) return "-";
  const tsCode = position.ts_code || position.stock_code || position.symbol;
  const name = position.name || position.stock_name;
  if (tsCode && name) return `${tsCode} ${name}`;
  return tsCode || name || "-";
}

function reviewTargetText() {
  const plan = state.report?.buy_plan ? planFromReport(state.report.buy_plan) : null;
  if (plan) return planStockText(plan);
  const candidate = state.report?.candidate;
  if (candidate) return `${candidate.ts_code || ""} ${candidate.name || ""}`.trim();
  return "策略按复盘日自动选择";
}

function plannedShares(plan) {
  return plan?.planned_shares ?? plan?.shares ?? plan?.plan_json?.planned_shares ?? plan?.plan_json?.shares ?? null;
}

function plannedCash(plan) {
  return plan?.planned_cash ?? plan?.planned_amount ?? plan?.plan_json?.planned_cash ?? null;
}

function planReferencePrice(plan) {
  const reportPlan = matchingReportPlan(plan);
  const explicit = firstFiniteNumber(
    plan?.price_reference,
    plan?.plan_json?.price_reference,
    reportPlan?.price_reference,
  );
  if (explicit != null) return explicit;

  const cash = firstFiniteNumber(plannedCash(plan), reportPlan?.planned_cash);
  const shares = firstFiniteNumber(plannedShares(plan), reportPlan?.planned_shares);
  if (cash != null && shares != null && shares > 0) return cash / shares;
  return null;
}

function matchingReportPlan(plan) {
  const reportPlan = state.report?.buy_plan;
  if (!plan || !reportPlan) return null;
  const reportPlanId = reportPlan.trade_plan_id || reportPlan.id;
  const planId = plan.id || plan.trade_plan_id;
  return Number(reportPlanId) === Number(planId) ? reportPlan : null;
}

function firstFiniteNumber(...values) {
  for (const value of values) {
    if (value == null || value === "") continue;
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }
  return null;
}

function planDailyPickId(plan) {
  return plan?.daily_pick_id ?? plan?.plan_json?.daily_pick_id ?? null;
}

function planSignalId(plan) {
  return plan?.signal_id ?? plan?.plan_json?.signal_id ?? null;
}

function isBuyPlan(plan) {
  return plan?.action === "buy_next_open" || String(plan?.action || "").startsWith("buy");
}

function setRecordFormState() {
  const issues = recordFormIssues();
  const recordBlockers = issues.filter((issue) => issue.severity === "blocker");
  els.submitRecordButton.disabled = recordBlockers.length > 0;
  els.recordLockReasonInline.hidden = recordBlockers.length === 0;
  els.recordLockReasonInline.textContent = recordBlockers.length
    ? `录入锁定原因：${recordBlockers.map((issue) => issue.text).join("；")}`
    : "";
  renderRecordValidationPanel(issues);
}

function renderRecordValidationPanel(issues) {
  if (!els.recordValidationPanel) return;
  const tone = issues.some((issue) => issue.severity === "blocker")
    ? "blocked"
    : issues.some((issue) => issue.severity === "warning")
      ? "warning"
      : "ready";
  els.recordValidationPanel.className = `validation-panel validation-panel--${tone}`;
  els.recordValidationPanel.innerHTML = `
    <strong>${tone === "ready" ? "成交录入校验通过" : tone === "warning" ? "成交录入提示" : "成交录入暂不可提交"}</strong>
    <ul>
      ${(issues.length ? issues : [{ severity: "ok", text: "成交价和股数必须来自实际成交；提交只记录事实，不会触发券商下单。" }])
        .map((issue) => `<li>${escapeHtml(issue.text)}</li>`)
        .join("")}
    </ul>
  `;
}

function recordFormIssues() {
  const issues = [];
  const tradePlanId = positiveIntegerOrNull(els.recordPlanId.value);
  const positionId = positiveIntegerOrNull(els.recordPositionId.value);
  const plan = tradePlanId ? selectedRecordPlan(tradePlanId) : null;
  const position = positionId ? findPosition(positionId) : null;
  const side = els.recordSide.value;
  const recordDate = normalizeDate(els.recordDate.value);
  const price = positiveNumberOrNull(els.recordPrice.value);
  const shares = positiveIntegerOrNull(els.recordShares.value);

  if (tradePlanId && positionId) {
    issues.push({ severity: "blocker", text: "计划 ID 和持仓 ID 只能填写一个。" });
  } else if (!tradePlanId && !positionId) {
    issues.push({ severity: "blocker", text: "请先从待录入队列选择 active 计划或待卖出持仓。" });
  }

  if (tradePlanId) {
    if (!plan) {
      issues.push({ severity: "blocker", text: "计划未在当前账户计划列表中，请刷新或重新选择。" });
    } else {
      const expectedSide = actionIsSell(plan.action) ? "sell" : "buy";
      const expectedSideText = expectedSide === "buy" ? "买入" : "卖出";
      const planDate = planTradeDate(plan);
      if (plan.status !== "active") {
        issues.push({ severity: "blocker", text: "只有 active 计划可以录入成交。" });
      }
      if (side !== expectedSide) {
        issues.push({ severity: "blocker", text: `该计划方向必须为${expectedSideText}。` });
      }
      if (/^\d{8}$/.test(recordDate) && planDate && recordDate !== planDate) {
        issues.push({ severity: "blocker", text: `成交日期必须与计划交易日 ${displayDate(planDate)} 一致。` });
      }
      if (isBuyPlan(plan)) {
        const lockReason = recordLockReasonForPlan(plan, executionDate());
        if (lockReason) issues.push({ severity: "blocker", text: lockReason });
      }
      if (!plannedShares(plan)) {
        issues.push({ severity: "warning", text: "计划没有返回计划股数，提交前请人工核对股数。" });
      }
    }
  }

  if (positionId) {
    if (!position) {
      issues.push({ severity: "blocker", text: "持仓未在当前账户持仓列表中，请刷新或重新选择。" });
    }
    if (side !== "sell") {
      issues.push({ severity: "blocker", text: "按持仓录入时方向必须为卖出。" });
    }
    if (position && /^\d{8}$/.test(recordDate)) {
      const buyDate = normalizeDate(position.buy_date);
      if (/^\d{8}$/.test(buyDate) && recordDate < buyDate) {
        issues.push({ severity: "blocker", text: `卖出成交日期不能早于买入日 ${displayDate(buyDate)}。` });
      }
    }
  }

  if (!/^\d{8}$/.test(recordDate)) {
    issues.push({ severity: "blocker", text: "成交日期必须是有效日期。" });
  }
  if (!state.dryRun && !state.operator) {
    issues.push({ severity: "blocker", text: "非 dry-run 成交录入需要填写操作者。" });
  }
  if (price == null) {
    issues.push({ severity: "blocker", text: "成交价必须大于 0，且来自实际成交。" });
  }
  if (shares == null) {
    issues.push({ severity: "blocker", text: "股数必须是正整数，且来自实际成交。" });
  } else if (shares % 100 !== 0) {
    issues.push({ severity: "blocker", text: "股数必须是 100 的整数倍，与服务端 A 股整手校验一致。" });
  }
  if (!nonNegativeOptionalNumber(els.recordFee.value)) {
    issues.push({ severity: "blocker", text: "手续费必须为空或大于等于 0。" });
  }
  if (!nonNegativeOptionalNumber(els.recordTax.value)) {
    issues.push({ severity: "blocker", text: "印花税必须为空或大于等于 0。" });
  }
  return issues;
}

function selectedRecordPlan(id) {
  if (state.selectedPlan && Number(state.selectedPlan.id) === Number(id)) return state.selectedPlan;
  const plan = findPlan(id);
  if (plan) return plan;
  const reportPlan = state.report?.buy_plan;
  if (reportPlan && Number(reportPlan.trade_plan_id || reportPlan.id) === Number(id)) {
    return planFromReport(reportPlan);
  }
  return null;
}

function marketPlanContextApiPath(asOfDate) {
  const params = new URLSearchParams();
  const planId = marketContextPlanId();
  if (planId) params.set("trade_plan_id", planId);
  const suffix = params.toString();
  return `/api/market-reviews/${asOfDate}/plan-context${suffix ? `?${suffix}` : ""}`;
}

function marketContextPlanId() {
  const reportPlanId = state.report?.buy_plan?.trade_plan_id || state.report?.buy_plan?.id;
  if (reportPlanId) return reportPlanId;
  const executionDay = executionDate();
  const plan = state.tradePlans.find((item) => {
    return ["draft", "active"].includes(item.status) && planTradeDate(item) === executionDay;
  });
  return plan?.id || "";
}

function marketPlanForContext(planId) {
  if (!planId) return null;
  const loadedPlan = findPlan(Number(planId));
  if (loadedPlan) return loadedPlan;
  const reportPlan = state.report?.buy_plan;
  const reportPlanId = reportPlan?.trade_plan_id || reportPlan?.id;
  if (reportPlan && Number(reportPlanId) === Number(planId)) {
    return planFromReport(reportPlan);
  }
  return null;
}

function marketReviewExists() {
  return Boolean(state.marketReview?.exists || state.marketReview?.market_review_run_id);
}

function marketMissingDataText(payload) {
  const missing = payload?.missing_data || [];
  if (!missing.length) return "";
  return `缺少 ${missing.join(", ")}`;
}

function marketSummaryText(summary) {
  if (!summary || typeof summary !== "object") return "暂无市场摘要。";
  const parts = [];
  if (summary.summary) parts.push(summary.summary);
  if (summary.regime) parts.push(`regime=${summary.regime}`);
  if (summary.coverage_ratio != null) parts.push(`coverage=${percent(summary.coverage_ratio)}`);
  return parts.join(" / ") || JSON.stringify(summary);
}

function orderedMarketSectors() {
  return [...(state.marketSectors || [])].sort((a, b) => {
    const aRank = Number.isFinite(Number(a.rank_overall)) ? Number(a.rank_overall) : 999999;
    const bRank = Number.isFinite(Number(b.rank_overall)) ? Number(b.rank_overall) : 999999;
    if (aRank !== bRank) return aRank - bRank;
    return String(a.sector_code || "").localeCompare(String(b.sector_code || ""));
  });
}

function marketConstituentCount() {
  return (state.marketSectors || []).reduce((total, sector) => total + (sector.constituents || []).length, 0);
}

function findMarketSector(sectorCode) {
  return (state.marketSectors || []).find((sector) => String(sector.sector_code) === String(sectorCode));
}

function findMarketHypothesis(id) {
  return (state.marketHypotheses || []).find((item) => Number(item.hypothesis_id) === Number(id));
}

function strategyHypothesisEvaluations() {
  return state.strategyHypothesisWorkbench?.hypotheses || [];
}

function findStrategyHypothesisEvaluation(id) {
  return strategyHypothesisEvaluations().find((item) => Number(item.hypothesis?.hypothesis_id) === Number(id));
}

function latestStrategyVersionProposal(evaluation) {
  const proposals = evaluation?.strategy_version_proposals || [];
  return proposals.length ? proposals[proposals.length - 1] : null;
}

function latestStrategyProposalReview(evaluation) {
  const reviews = evaluation?.strategy_version_proposal_reviews || [];
  return reviews.length ? reviews[reviews.length - 1] : null;
}

function strategyProposalReviewButtons(evaluation) {
  const actions = strategyProposalReviewActions(evaluation);
  if (!actions.length) return "";
  const hypothesisId = evaluation?.hypothesis?.hypothesis_id;
  return `
    <div class="proposal-review-actions" aria-label="proposal review artifact actions">
      ${actions.map((action) => `
        <button
          type="button"
          data-strategy-hypothesis-id="${escapeHtml(hypothesisId)}"
          data-strategy-proposal-review="${escapeHtml(action.decision)}"
          ${action.disabled ? "disabled" : ""}
          title="${escapeHtml(action.title)}"
        >${escapeHtml(action.label)}</button>
      `).join("")}
    </div>
  `;
}

function strategyProposalReviewActions(evaluation) {
  const hypothesis = evaluation?.hypothesis || {};
  const proposals = evaluation?.strategy_version_proposals || [];
  if (hypothesis.status !== "accepted" || !proposals.length) return [];
  const hasValidProposal = proposals.some((proposal) => proposal.valid);
  const latestReview = latestStrategyProposalReview(evaluation);
  return [
    {
      decision: "approve",
      label: "批准 proposal",
      title: "写入 proposal review artifact，不创建策略版本。",
      disabled: !hasValidProposal || latestReview?.decision === "request_promotion",
    },
    {
      decision: "reject",
      label: "拒绝 artifact",
      title: "写入 rejection review artifact，active strategy 不变。",
      disabled: latestReview?.decision === "request_promotion",
    },
    {
      decision: "request_promotion",
      label: "生成 promotion-request",
      title: "写入 promotion-request artifact，不创建/提升 strategy_version。",
      disabled: !hasValidProposal || latestReview?.decision === "request_promotion",
    },
  ];
}

function strategyProposalReviewDrawerActions(evaluation) {
  const hypothesisId = evaluation?.hypothesis?.hypothesis_id;
  if (!hypothesisId) return [];
  return strategyProposalReviewActions(evaluation).map((action) => ({
    label: action.label,
    action: "strategy-proposal-review",
    hypothesisId,
    decision: action.decision,
    disabled: action.disabled,
    title: action.title,
    primary: action.decision === "request_promotion",
  }));
}

function strategyHypothesisQueueSort(a, b) {
  const priority = {
    reject_or_rewrite: 0,
    ready_to_accept: 1,
    fix_backtest_artifact: 2,
    create_backtest_artifact: 3,
    attach_validation_evidence: 4,
    move_to_testing: 5,
    create_strategy_version_proposal: 6,
    fix_strategy_version_proposal: 7,
    review_strategy_version_proposal: 8,
    fix_strategy_version_proposal_review: 9,
    request_strategy_promotion: 10,
    promotion_requested: 11,
    proposal_rejected: 12,
    proposal_ready: 13,
    strategy_version_task_required: 14,
  };
  const aPriority = priority[a.next_action] ?? 99;
  const bPriority = priority[b.next_action] ?? 99;
  if (aPriority !== bPriority) return aPriority - bPriority;
  return String(b.hypothesis?.as_of_date || "").localeCompare(String(a.hypothesis?.as_of_date || ""));
}

function strategyHypothesisGateRows(evaluation) {
  const gate = evaluation.acceptance_gate || {};
  return detailRows([
    ["can_accept", gate.can_accept ? "是" : "否"],
    ["accepted_complete", gate.accepted_complete ? "是" : "否"],
    ["testing_required", gate.testing_required ? "是" : "否"],
    ["has_validation_evidence", gate.has_validation_evidence ? "是" : "否"],
    ["has_backtest_artifact", gate.has_backtest_artifact ? "是" : "否"],
    ["backtest_artifacts_valid", gate.backtest_artifacts_valid ? "是" : "否"],
    ["requires_replay_backtest", gate.requires_replay_backtest ? "是" : "否"],
    ["blocks", listValue(gate.blocks).join(" / ") || "无"],
    ["evidence_ids", listValue(evaluation.evidence_ids).join(" / ") || "-"],
  ]);
}

function strategyHypothesisArtifactRows(artifacts) {
  if (!artifacts.length) return emptyState("暂无 backtest artifact；接受前必须创建或附加 replay/backtest request artifact。");
  return `
    <div class="table-wrap market-leadership-table">
      <table>
        <thead>
          <tr>
            <th>路径</th>
            <th>状态</th>
            <th>假设 ID</th>
            <th>任务 key</th>
            <th>错误</th>
          </tr>
        </thead>
        <tbody>
          ${artifacts.map((artifact) => `
            <tr>
              <td>${escapeHtml(artifact.path || "-")}</td>
              <td>${chipHtml(artifact.valid ? "有效" : artifact.exists ? "无效" : "缺失", artifact.valid ? "chip-green" : "chip-red")}</td>
              <td>${dash(artifact.hypothesis_id)}</td>
              <td>${escapeHtml(artifact.backtest_task_key || "-")}</td>
              <td>${escapeHtml(artifact.error || "-")}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function strategyHypothesisProposalRows(artifacts) {
  if (!artifacts.length) return emptyState("暂无 strategy-version proposal artifact；accepted 后必须单独创建 proposal 工件。");
  return `
    <div class="table-wrap market-leadership-table">
      <table>
        <thead>
          <tr>
            <th>路径</th>
            <th>状态</th>
            <th>Proposal key</th>
            <th>候选版本名</th>
            <th>安全边界</th>
            <th>错误</th>
          </tr>
        </thead>
        <tbody>
          ${artifacts.map((artifact) => `
            <tr>
              <td>${escapeHtml(artifact.path || "-")}</td>
              <td>${chipHtml(artifact.valid ? "有效" : artifact.exists ? "无效" : "缺失", artifact.valid ? "chip-green" : "chip-red")}</td>
              <td>${escapeHtml(artifact.proposal_key || "-")}</td>
              <td>${escapeHtml(artifact.candidate_strategy_version || "-")}</td>
              <td>${artifact.wrote_strategy_versions ? "写 strategy_versions" : "artifact-only"}</td>
              <td>${escapeHtml(artifact.error || "-")}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function strategyHypothesisProposalReviewRows(artifacts) {
  if (!artifacts.length) {
    return emptyState("暂无 proposal review artifact；可 approve、reject 或生成 promotion-request artifact。");
  }
  return `
    <div class="table-wrap market-leadership-table">
      <table>
        <thead>
          <tr>
            <th>路径</th>
            <th>状态</th>
            <th>Decision</th>
            <th>Review key</th>
            <th>Promotion request</th>
            <th>安全边界</th>
            <th>错误</th>
          </tr>
        </thead>
        <tbody>
          ${artifacts.map((artifact) => `
            <tr>
              <td>${escapeHtml(artifact.path || "-")}</td>
              <td>${chipHtml(artifact.valid ? "有效" : artifact.exists ? "无效" : "缺失", artifact.valid ? "chip-green" : "chip-red")}</td>
              <td>${chipHtml(proposalReviewDecisionText(artifact.decision), proposalReviewDecisionClass(artifact.decision))}</td>
              <td>${escapeHtml(artifact.review_key || "-")}</td>
              <td>${escapeHtml(artifact.promotion_request_key || "-")}</td>
              <td>${artifact.wrote_strategy_versions ? "写 strategy_versions" : "artifact-only"}</td>
              <td>${escapeHtml(artifact.error || "-")}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function strategyHypothesisValidationEvents(events) {
  if (!events.length) return emptyState("暂无 review_events；状态流转和验证记录会显示在这里。");
  return `
    <div class="table-wrap market-leadership-table">
      <table>
        <thead>
          <tr>
            <th>流转</th>
            <th>操作者</th>
            <th>时间</th>
            <th>备注</th>
          </tr>
        </thead>
        <tbody>
          ${events.map((event) => `
            <tr>
              <td>${escapeHtml(`${dash(event.from_status)} → ${dash(event.to_status)}`)}</td>
              <td>${escapeHtml(event.operator || "-")}</td>
              <td>${displayTimestamp(event.created_at)}</td>
              <td>${escapeHtml(event.review_note || "-")}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function marketItemsForScope(scopeType, scopeKey) {
  const normalizedType = String(scopeType || "").toLowerCase();
  const normalizedKey = String(scopeKey || "");
  const sector = normalizedType === "sector" ? findMarketSector(normalizedKey) : null;
  return (state.marketExternalItems || []).filter((item) => {
    if (String(item.scope_type || "").toLowerCase() !== normalizedType) return false;
    if (String(item.scope_key || "") === normalizedKey) return true;
    if (sector && String(item.scope_key || "") === String(sector.sector_name || "")) return true;
    return false;
  });
}

function sectorSentiment(sector) {
  const counts = countBy(marketItemsForScope("sector", sector.sector_code), "sentiment");
  return dominantSentiment(counts);
}

function dominantSentiment(counts) {
  const entries = Object.entries(counts || {}).sort((a, b) => Number(b[1]) - Number(a[1]));
  return entries[0]?.[0] || "unknown";
}

function countBy(items, key) {
  const counts = {};
  for (const item of items || []) {
    const value = item?.[key] == null || item?.[key] === "" ? "unknown" : String(item[key]);
    counts[value] = (counts[value] || 0) + 1;
  }
  return counts;
}

function marketLeadershipTable(constituents) {
  const rows = [...(constituents || [])].sort((a, b) => {
    const aRank = Number.isFinite(Number(a.rank_in_sector)) ? Number(a.rank_in_sector) : 999999;
    const bRank = Number.isFinite(Number(b.rank_in_sector)) ? Number(b.rank_in_sector) : 999999;
    return aRank - bRank;
  });
  if (!rows.length) return emptyState("该板块暂无个股领涨数据。");
  return `
    <div class="table-wrap market-leadership-table">
      <table>
        <thead>
          <tr>
            <th>排名</th>
            <th>股票</th>
            <th>角色</th>
            <th class="num">评分</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((item) => `
            <tr>
              <td>${dash(item.rank_in_sector)}</td>
              <td>${escapeHtml(item.ts_code)} ${escapeHtml(item.name || "")}</td>
              <td>${escapeHtml(marketRoleText(item.role))}</td>
              <td class="num">${scoreText(item.score)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function marketEvidenceTable(items) {
  return `
    <div class="market-evidence-list">
      ${(items || []).map(renderMarketEvidenceItem).join("")}
    </div>
  `;
}

function marketObjectRows(value) {
  if (!value || typeof value !== "object") return emptyState("暂无结构化数据。");
  const rows = Object.entries(value).map(([key, item]) => [
    key,
    typeof item === "object" ? JSON.stringify(item) : String(item ?? "-"),
  ]);
  return rows.length ? detailRows(rows) : emptyState("暂无结构化数据。");
}

function setBusy(value) {
  state.busy = value;
  document.querySelectorAll("button, input, select").forEach((control) => {
    if (control.closest(".confirm-dialog")) return;
    if (control.id === "dryRunInput") return;
    control.classList.toggle("busy", value);
  });
}

function showNotice(message, tone = "error") {
  if (!message) {
    els.noticeLine.hidden = true;
    els.noticeLine.textContent = "";
    return;
  }
  els.noticeLine.hidden = false;
  els.noticeLine.textContent = message;
  els.noticeLine.style.borderColor = tone === "ok" ? "#bbf7d0" : "#fecaca";
  els.noticeLine.style.background = tone === "ok" ? "#f0fdf4" : "#fef2f2";
  els.noticeLine.style.color = tone === "ok" ? "#065f46" : "#991b1b";
}

function confirmAction({ title, body, inputLabel, quickChoices = [], details = [], submitLabel = "确认" }) {
  const summaryText = details.map(([label, value]) => `${label}: ${value ?? "-"}`).join("\n");
  if (!els.confirmDialog.showModal) {
    const confirmed = window.confirm(summaryText ? `${body}\n\n${summaryText}` : body);
    const value = inputLabel && confirmed ? window.prompt(inputLabel, "") || "" : "";
    return Promise.resolve({ confirmed, value });
  }
  els.confirmTitle.textContent = title;
  els.confirmBody.textContent = body;
  els.confirmSummary.hidden = details.length === 0;
  els.confirmSummary.innerHTML = details.map(([label, value]) => `
    <div class="confirm-summary__item">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(String(value ?? "-"))}</strong>
    </div>
  `).join("");
  els.confirmInput.value = "";
  els.confirmInputLabel.hidden = !inputLabel;
  els.confirmInputText.textContent = inputLabel || "";
  els.confirmInput.required = Boolean(inputLabel);
  els.confirmQuickChoices.hidden = !quickChoices.length;
  els.confirmQuickChoices.innerHTML = quickChoices.map((choice) => (
    `<button type="button" data-confirm-choice="${escapeHtml(choice)}">${escapeHtml(choice)}</button>`
  )).join("");
  els.confirmQuickChoices.querySelectorAll("[data-confirm-choice]").forEach((button) => {
    button.addEventListener("click", () => {
      els.confirmInput.value = button.dataset.confirmChoice || "";
      els.confirmInput.focus();
    });
  });
  els.confirmSubmit.textContent = submitLabel;
  return new Promise((resolve) => {
    const onClose = () => {
      els.confirmDialog.removeEventListener("close", onClose);
      resolve({
        confirmed: els.confirmDialog.returnValue === "confirm",
        value: els.confirmInput.value,
      });
    };
    els.confirmDialog.addEventListener("close", onClose);
    els.confirmDialog.showModal();
    if (inputLabel) els.confirmInput.focus();
  });
}

function compactDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}${month}${day}`;
}

function localDateCompact() {
  return compactDate(new Date());
}

function defaultReviewDate() {
  const date = new Date();
  date.setDate(date.getDate() - 1);
  while (date.getDay() === 0 || date.getDay() === 6) {
    date.setDate(date.getDate() - 1);
  }
  return compactDate(date);
}

function initialPage() {
  const page = String(window.location.hash || "").replace(/^#/, "");
  return ["execution", "decision", "review", "market", "acceptance", "ops", "hypotheses", "plans", "record", "positions", "quality", "agent"].includes(page)
    ? page
    : "execution";
}

function offsetBusinessDate(value, offset) {
  const date = parseCompactDate(value) || new Date();
  const direction = offset >= 0 ? 1 : -1;
  let remaining = Math.abs(offset);
  while (remaining > 0) {
    date.setDate(date.getDate() + direction);
    if (date.getDay() !== 0 && date.getDay() !== 6) {
      remaining -= 1;
    }
  }
  return compactDate(date);
}

function parseCompactDate(value) {
  const text = normalizeDate(value);
  if (!/^\d{8}$/.test(text)) return null;
  const year = Number(text.slice(0, 4));
  const month = Number(text.slice(4, 6));
  const day = Number(text.slice(6, 8));
  const date = new Date(year, month - 1, day);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
    return null;
  }
  return date;
}

function dashboardAccountKey() {
  const saved = localStorage.getItem("pgc.dashboard.accountKey");
  if (!saved || saved === LEGACY_DEFAULT_ACCOUNT_KEY) {
    if (saved === LEGACY_DEFAULT_ACCOUNT_KEY) {
      localStorage.setItem("pgc.dashboard.accountKey", DEFAULT_ACCOUNT_KEY);
    }
    return DEFAULT_ACCOUNT_KEY;
  }
  return saved;
}

function dashboardDryRun() {
  if (localStorage.getItem("pgc.dashboard.dryRunDefaultVersion") !== DRY_RUN_DEFAULT_VERSION) {
    localStorage.setItem("pgc.dashboard.dryRun", "false");
    localStorage.setItem("pgc.dashboard.dryRunDefaultVersion", DRY_RUN_DEFAULT_VERSION);
    return false;
  }
  return localStorage.getItem("pgc.dashboard.dryRun") === "true";
}

function dashboardOperator() {
  const saved = String(localStorage.getItem("pgc.dashboard.operator") || "").trim();
  if (saved) return saved;
  localStorage.setItem("pgc.dashboard.operator", DEFAULT_OPERATOR);
  return DEFAULT_OPERATOR;
}

function normalizeDate(value) {
  return String(value || "").trim().replaceAll("-", "");
}

function displayDate(value) {
  if (value == null || value === "") return "-";
  const text = String(value);
  if (/^\d{8}$/.test(text)) return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`;
  return text;
}

function dateInputValue(value) {
  const text = normalizeDate(value);
  if (/^\d{8}$/.test(text)) return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`;
  return "";
}

function inputNumber(value, decimals = 4) {
  const number = firstFiniteNumber(value);
  if (number == null) return "";
  return String(Number(number.toFixed(decimals)));
}

function accountName(account) {
  if (!account) return state.accountKey || state.accountId || "-";
  const key = account.account_key || state.accountKey || "-";
  const type = account.account_type || "未确认";
  const name = account.name ? ` / ${account.name}` : "";
  return `${key}${name} (${type})`;
}

function capacityText(account) {
  if (!account) return "-";
  return `${dash(account.open_positions)}/${dash(account.max_positions)}，空闲 ${dash(account.free_position_slots)}`;
}

function readinessText(value) {
  return {
    pass: "可交易",
    warning: "警告",
    blocked: "阻断",
    blocker: "阻断",
  }[value] || "-";
}

function promotionReadinessText(value) {
  return {
    pass: "可晋级",
    warning: "警告",
    blocked: "阻断",
  }[value] || readinessText(value);
}

function promotionReadinessClass(value) {
  if (value === "pass") return "chip-green";
  if (value === "warning") return "chip-amber";
  if (value === "blocked") return "chip-red";
  return "chip-neutral";
}

function acceptanceStatusText(value) {
  return {
    pass: "通过",
    warning: "警告",
    blocked: "阻断",
  }[value] || "-";
}

function acceptanceStatusClass(value) {
  return {
    pass: "chip-green",
    warning: "chip-amber",
    blocked: "chip-red",
  }[value] || "chip-neutral";
}

function decisionStatusText(value) {
  return {
    ready: "就绪",
    review_required: "需复核",
    blocked: "阻断",
  }[value] || "-";
}

function decisionItemStatusText(value) {
  return {
    pass: "通过",
    warning: "警告",
    blocked: "阻断",
  }[value] || decisionStatusText(value);
}

function decisionStatusClass(value) {
  return {
    ready: "chip-green",
    review_required: "chip-amber",
    blocked: "chip-red",
  }[value] || acceptanceStatusClass(value);
}

function decisionActionText(value) {
  return {
    execution: "开盘执行",
    acceptance: "运营验收",
    market: "全市场",
    quality: "数据质量",
    hypotheses: "假设评估",
    refresh: "刷新",
  }[value] || "查看";
}

function opsHistoryCategoryText(value) {
  return {
    daily_pipeline: "pipeline",
    pipeline_step: "pipeline step",
    backup: "backup",
    release: "release",
    health: "health",
    paper_acceptance: "acceptance",
    timer_evidence: "timer evidence",
    timer_action: "timer action",
    operation: "operation",
  }[value] || dash(value);
}

function opsHistoryCategoryClass(value) {
  return {
    daily_pipeline: "chip-blue",
    pipeline_step: "chip-indigo",
    backup: "chip-amber",
    release: "chip-green",
    health: "chip-agent",
    paper_acceptance: "chip-blue",
    timer_evidence: "chip-amber",
    timer_action: "chip-indigo",
  }[value] || "chip-neutral";
}

function opsHistoryStatusText(value) {
  return {
    pass: "通过",
    success: "成功",
    ready: "ready",
    artifact: "artifact",
    recorded: "已记录",
    blocked: "阻断",
    failed: "失败",
    not_evaluated: "未评估",
    preview: "preview",
    observed: "observed",
  }[value] || dash(value);
}

function opsHistoryStatusClass(value) {
  if (["pass", "success", "ready", "recorded", "artifact"].includes(value)) return "chip-green";
  if (["blocked", "failed"].includes(value)) return "chip-red";
  if (["not_evaluated", "preview", "observed"].includes(value)) return "chip-amber";
  return "chip-neutral";
}

function statusText(value) {
  return {
    draft: "草稿",
    active: "有效",
    executed: "已成交",
    skipped: "已跳过",
    cancelled: "已取消",
    expired: "已过期",
    superseded: "已替代",
    waiting_t2: "等待 T+2",
    need_t2_decision: "T+2 到期",
    holding_to_t5: "持有到 T+5",
    need_t5_exit: "T+5 到期",
    planned_exit: "退出计划",
    open: "未平仓",
    closed: "已平仓",
    not_run: "未运行",
    failed: "失败",
    success: "成功",
    open_event: "open",
    resolved: "已处理",
  }[value] || dash(value);
}

function actionText(value) {
  return {
    buy_next_open: "次一交易日买入",
    skip_max_positions: "仓位已满跳过",
    skip_no_cash: "现金不足跳过",
    sell_t2_take_profit: "T+2 止盈卖出",
    sell_t2_stop_loss: "T+2 控亏卖出",
    sell_t5_timeout: "T+5 到期卖出",
  }[value] || dash(value);
}

function openExecutionActionText(value) {
  return {
    record_buy: "记录买入",
    record_sell: "记录卖出",
    evaluate_exit: "评估退出",
    wait: "等待后续计划",
    none: "无执行任务",
    blocked: "执行阻断",
    account_missing: "账户缺失",
    next_trade_date_missing: "缺少下一交易日",
  }[value] || dash(value);
}

function openExecutionStatusText(value) {
  return {
    ready: "执行就绪",
    waiting: "等待",
    idle: "空闲",
    blocked: "阻断",
    unavailable: "不可用",
  }[value] || dash(value);
}

function openExecutionStatusClass(value) {
  return {
    ready: "chip-green",
    waiting: "chip-amber",
    idle: "chip-neutral",
    blocked: "chip-red",
    unavailable: "chip-neutral",
  }[value] || "chip-neutral";
}

function agentActionText(value) {
  return {
    no_opinion: "无意见",
    support: "支持",
    caution: "谨慎",
    reject: "反对",
  }[value] || dash(value);
}

function riskText(value) {
  return {
    low: "低",
    medium: "中",
    high: "高",
    unknown: "未知",
  }[value] || dash(value);
}

function riskClass(value) {
  return {
    low: "chip-green",
    medium: "chip-amber",
    high: "chip-red",
    unknown: "chip-neutral",
  }[value] || "chip-neutral";
}

function marketRegimeText(value) {
  return {
    risk_on: "风险偏好回升",
    neutral: "中性震荡",
    risk_off: "风险偏好回落",
    completed: "复盘完成",
    missing: "复盘缺失",
    success: "复盘成功",
    blocked: "复盘阻断",
  }[value] || dash(value);
}

function sentimentText(value) {
  return {
    positive: "正面",
    neutral: "中性",
    negative: "负面",
    mixed: "分歧",
    unknown: "未知",
  }[value] || dash(value);
}

function sentimentClass(value) {
  return {
    positive: "chip-green",
    neutral: "chip-blue",
    negative: "chip-red",
    mixed: "chip-amber",
    unknown: "chip-neutral",
  }[value] || "chip-neutral";
}

function persistenceClass(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "chip-neutral";
  if (number >= 0.66) return "chip-green";
  if (number >= 0.4) return "chip-amber";
  return "chip-red";
}

function alignmentText(value) {
  return {
    aligned: "顺风",
    neutral: "中性",
    conflict: "冲突",
    unknown: "未知",
  }[value] || dash(value);
}

function alignmentClass(value) {
  return {
    aligned: "chip-green",
    neutral: "chip-blue",
    conflict: "chip-red",
    unknown: "chip-neutral",
  }[value] || "chip-neutral";
}

function managementActionText(value) {
  return {
    proceed: "按原计划进入人工开盘检查",
    manual_review: "人工复核后再执行",
    consider_cancel: "考虑取消但不自动取消",
    unknown: "未知，保持计划不变",
  }[value] || dash(value);
}

function managementActionShortText(value) {
  return {
    proceed: "可推进",
    manual_review: "人工复核",
    consider_cancel: "考虑取消",
    unknown: "未知",
  }[value] || dash(value);
}

function managementActionClass(value) {
  return {
    proceed: "chip-green",
    manual_review: "chip-amber",
    consider_cancel: "chip-red",
    unknown: "chip-neutral",
  }[value] || "chip-neutral";
}

function hypothesisStatusText(value) {
  return {
    proposed: "待验证",
    testing: "验证中",
    accepted: "已接受",
    rejected: "已拒绝",
    archived: "已归档",
  }[value] || dash(value);
}

function hypothesisStatusClass(value) {
  return {
    proposed: "chip-blue",
    testing: "chip-amber",
    accepted: "chip-green",
    rejected: "chip-red",
    archived: "chip-neutral",
  }[value] || "chip-neutral";
}

function proposalReviewConfirmTitle(decision) {
  return {
    approve: "批准 strategy-version proposal artifact",
    reject: "拒绝 strategy-version proposal artifact",
    request_promotion: "生成 promotion-request artifact",
  }[decision] || "审阅 strategy-version proposal artifact";
}

function proposalReviewConfirmBody(decision, hypothesis) {
  const title = hypothesis?.title || `假设 ${hypothesis?.hypothesis_id || "-"}`;
  return {
    approve: `将批准 proposal artifact：${title}。只写 review artifact，不创建策略版本。`,
    reject: `将拒绝 proposal artifact：${title}。只写 rejection artifact，不改变策略状态。`,
    request_promotion: `将为 ${title} 生成 promotion-request artifact。后续仍需单独任务创建或提升候选策略版本。`,
  }[decision] || `将审阅 proposal artifact：${title}。`;
}

function proposalReviewQuickChoices(decision) {
  return {
    approve: ["证据完整，允许进入 promotion request", "artifact-only 边界已核对"],
    reject: ["证据不足，拒绝 proposal", "安全边界不清晰，退回重写"],
    request_promotion: ["请求创建候选 strategy version", "请求进入独立 promotion gate"],
  }[decision] || ["人工审阅完成"];
}

function proposalReviewDefaultNote(decision) {
  return {
    approve: "Approved proposal artifact for separate promotion request review.",
    reject: "Rejected proposal artifact; active strategy remains unchanged.",
    request_promotion: "Requested explicit promotion artifact; candidate creation remains a separate task.",
  }[decision] || "Reviewed proposal artifact.";
}

function proposalReviewDecisionText(value) {
  return {
    approve: "proposal approved",
    reject: "proposal rejected",
    request_promotion: "promotion requested",
  }[value] || dash(value);
}

function proposalReviewDecisionClass(value) {
  return {
    approve: "chip-green",
    reject: "chip-red",
    request_promotion: "chip-indigo",
  }[value] || "chip-neutral";
}

function hypothesisNextActionText(value) {
  return {
    move_to_testing: "进入 testing",
    create_backtest_artifact: "创建回测 artifact",
    attach_validation_evidence: "补验证证据",
    fix_backtest_artifact: "修复 artifact",
    continue_testing: "继续验证",
    ready_to_accept: "可接受复核",
    create_strategy_version_proposal: "创建 proposal",
    fix_strategy_version_proposal: "修复 proposal",
    review_strategy_version_proposal: "审阅 proposal",
    fix_strategy_version_proposal_review: "修复 review artifact",
    request_strategy_promotion: "请求 promotion",
    promotion_requested: "promotion requested",
    proposal_rejected: "proposal rejected",
    proposal_ready: "proposal ready",
    strategy_version_task_required: "单独策略版本任务",
    reject_or_rewrite: "拒绝或重写",
    closed_rejected: "已关闭：拒绝",
    closed_archived: "已关闭：归档",
    review: "人工审阅",
  }[value] || dash(value);
}

function hypothesisNextActionClass(value) {
  return {
    move_to_testing: "chip-blue",
    create_backtest_artifact: "chip-amber",
    attach_validation_evidence: "chip-amber",
    fix_backtest_artifact: "chip-red",
    continue_testing: "chip-amber",
    ready_to_accept: "chip-green",
    create_strategy_version_proposal: "chip-indigo",
    fix_strategy_version_proposal: "chip-red",
    review_strategy_version_proposal: "chip-indigo",
    fix_strategy_version_proposal_review: "chip-red",
    request_strategy_promotion: "chip-indigo",
    promotion_requested: "chip-green",
    proposal_rejected: "chip-red",
    proposal_ready: "chip-green",
    strategy_version_task_required: "chip-indigo",
    reject_or_rewrite: "chip-red",
    closed_rejected: "chip-neutral",
    closed_archived: "chip-neutral",
    review: "chip-neutral",
  }[value] || "chip-neutral";
}

function marketRoleText(value) {
  return {
    leader: "领涨",
    strong: "强势",
    neutral: "中性",
    weak: "弱势",
  }[value] || dash(value);
}

function itemTypeText(value) {
  return {
    news: "新闻",
    announcement: "公告",
    policy: "政策",
    sentiment: "情绪",
    research_note: "研究纪要",
    risk_note: "风险提示",
  }[value] || dash(value);
}

function importanceText(value) {
  return {
    high: "高",
    medium: "中",
    low: "低",
    unknown: "未知",
  }[value] || dash(value);
}

function scopeText(scopeType, scopeKey) {
  return `${dash(scopeType)}:${dash(scopeKey)}`;
}

function featureLabel(key) {
  return {
    drawdown_from_peak: "回撤幅度",
    amount_contract_ratio: "缩量比",
    bull_body: "阳线实体",
    avg_amount_to_ma10: "回调均额/10日均额",
    trigger_amount_to_ma10: "确认日成交额/10日均额",
    pullback_days: "回调天数",
    entry_runup: "入池后涨幅",
    entry_price: "入池价",
    trigger_close: "复盘日收盘",
  }[key] || key;
}

function featureValue(key, value) {
  if (value == null || value === "") return "-";
  if (["drawdown_from_peak", "bull_body", "entry_runup"].includes(key)) return percent(value);
  if (typeof value === "number") return numberText(value, 4);
  return String(value);
}

function agentArtifactText(value) {
  return {
    decision_json: "决策 JSON",
    raw_response: "原始输出",
    raw_state: "运行状态",
    final_report: "复核报告",
    debug_log: "调试日志",
    memory_delta: "记忆变更",
    tool_trace: "工具轨迹",
  }[value] || dash(value);
}

function agentAnalystText(value) {
  return {
    fundamental: "基本面",
    news: "新闻面",
    sentiment: "情绪面",
    technical: "技术/量价",
    sector: "板块位置",
  }[value] || dash(value);
}

function agentReportSectionText(value) {
  return {
    fundamental: "基本面",
    news: "新闻",
    sentiment: "情绪",
    technical: "技术/量价",
    sector: "板块位置",
    risk: "风险",
    conclusion: "结论",
  }[value] || dash(value);
}

function agentSourceText(value) {
  return {
    local_snapshot_mode: "TradingAgents 本地快照模式",
    external_graph_mode: "TradingAgents 外部图模式",
    unavailable_fallback: "TradingAgents 不可用 fallback",
    dry_run: "dry-run preview",
  }[value] || "TradingAgents 输出";
}

function agentAnalystStatusText(value) {
  return {
    available: "已接入",
    partial: "部分数据",
    unavailable: "未接入",
  }[value] || dash(value);
}

function agentCoverageText(value) {
  return {
    available: "已接入",
    partial: "部分数据",
    unavailable: "未接入",
  }[value] || "未接入";
}

function agentCoverageClass(value) {
  return {
    available: "chip-green",
    partial: "chip-amber",
    unavailable: "chip-neutral",
  }[value] || "chip-neutral";
}

function agentEvidenceCategoryText(value) {
  return {
    technical: "技术面",
    fundamental: "基本面",
    news: "新闻面",
    announcement: "公告",
    sentiment: "情绪面",
    risk_note: "风险提示",
    research_note: "研究摘要",
  }[value] || (value || "外部证据");
}

function agentAnalystStatusClass(value) {
  return {
    available: "chip-green",
    partial: "chip-amber",
    unavailable: "chip-neutral",
  }[value] || "chip-neutral";
}

function severityText(value) {
  return {
    blocker: "阻断",
    warning: "警告",
  }[value] || dash(value);
}

function dueText(value) {
  return {
    t2: "T+2 到期",
    t5: "T+5 到期",
    buy_day_2_decision: "T+2 判断",
    buy_day_5_exit: "T+5 退出",
    exit_planned: "已有退出计划",
    sell_plan_exists: "已有卖出计划",
    none: "无",
    null: "无",
    undefined: "无",
  }[String(value)] || dash(value);
}

function reasonText(value) {
  return {
    daily_pick: "复盘候选",
    max_positions: "仓位已满",
    no_cash_or_board_lot: "现金或整手不足",
    review_not_run: "复盘未运行",
    no_strategy_signals: "无策略信号",
    no_daily_pick: "没有日级入选记录",
    highest_score_with_free_slot: "最高评分且有空闲仓位",
  }[value] || dash(value);
}

function reviewHistoryTitle(item) {
  if (item.ts_code || item.name) return `${item.ts_code || ""} ${item.name || ""}`.trim();
  if (Number(item.signals_count || 0) > 0) return "有信号但未入选";
  return "无策略候选";
}

function reviewHistorySubtext(item) {
  const parts = [
    `执行日 ${displayDate(item.planned_trade_date || item.planned_buy_date || item.next_trade_date)}`,
    `信号 ${integerText(item.signals_count)}`,
  ];
  if (item.score != null) parts.push(`评分 ${numberText(item.score, 2)}`);
  if (item.agent_action) parts.push(`AI ${agentActionText(item.agent_action)}`);
  return parts.join(" / ");
}

function reviewHistoryMetaText(item) {
  const parts = [];
  if (item.created_at) parts.push(`创建 ${displayTimestamp(item.created_at)}`);
  if (Number(item.blocker_count || 0) > 0) parts.push(`${integerText(item.blocker_count)} blocker`);
  if (Number(item.warning_count || 0) > 0) parts.push(`${integerText(item.warning_count)} warning`);
  if (item.agent_status) parts.push(`Agent ${agentRunStatusText(item.agent_status)}`);
  return parts.join(" / ");
}

function reviewTimelinePickText(item) {
  if (item.ts_code || item.name) {
    const stock = `${item.ts_code || ""} ${item.name || ""}`.trim();
    return item.score != null ? `${stock} / 评分 ${numberText(item.score, 2)}` : stock;
  }
  return "无复盘候选";
}

function reviewTimelineMarketText(item) {
  const regime = marketRegimeText(item.market_regime || (item.market_review_run_id ? "completed" : "missing"));
  if (item.market_persistence_score != null) return `${regime} / 持续性 ${scoreText(item.market_persistence_score)}`;
  return regime;
}

function reviewTimelinePlanContextText(item) {
  if (!item.plan_context_management_action) {
    return item.trade_plan_id ? "暂无 plan-context" : "无关联计划";
  }
  return `${alignmentText(item.plan_context_alignment)} / ${riskText(item.plan_context_risk_level)} / ${managementActionText(item.plan_context_management_action)}`;
}

function reviewTimelineExecutionText(item) {
  const action = openExecutionActionText(item.open_execution_next_action);
  const day = displayDate(item.open_execution_as_of_date || item.next_trade_date);
  const target = [item.open_execution_target_stock, item.open_execution_target_name].filter(Boolean).join(" ");
  const targetText = target || (item.open_execution_primary_plan_id ? `计划 ${item.open_execution_primary_plan_id}` : "");
  return [day, action, targetText].filter(Boolean).join(" / ");
}

function renderReviewTimelineBadges(item) {
  const chips = [
    chipHtml(reviewRunStatusText(item.review_status), reviewRunStatusClass(item.review_status)),
    chipHtml(openExecutionStatusText(item.open_execution_status), openExecutionStatusClass(item.open_execution_status)),
  ];
  if (item.market_regime || item.market_review_run_id) {
    chips.push(chipHtml(marketRegimeText(item.market_regime || "completed"), "chip-blue"));
  }
  if (item.plan_context_management_action) {
    chips.push(chipHtml(managementActionShortText(item.plan_context_management_action), managementActionClass(item.plan_context_management_action)));
  }
  if (Number(item.blocker_count || 0) > 0) {
    chips.push(chipHtml(`${integerText(item.blocker_count)} blocker`, "chip-red"));
  } else if (Number(item.warning_count || 0) > 0) {
    chips.push(chipHtml(`${integerText(item.warning_count)} warning`, "chip-amber"));
  }
  return chips.join("");
}

function renderReviewHistoryBadges(item) {
  const chips = [chipHtml(reviewRunStatusText(item.review_status), reviewRunStatusClass(item.review_status))];
  if (item.trade_plan_status) {
    chips.push(chipHtml(statusText(item.trade_plan_status), statusClass(item.trade_plan_status)));
  }
  if (item.agent_status) {
    chips.push(chipHtml(`Agent ${agentRunStatusText(item.agent_status)}`, agentRunStatusClass(item.agent_status)));
  }
  if (Number(item.blocker_count || 0) > 0) {
    chips.push(chipHtml(`${integerText(item.blocker_count)} blocker`, "chip-red"));
  } else if (Number(item.warning_count || 0) > 0) {
    chips.push(chipHtml(`${integerText(item.warning_count)} warning`, "chip-amber"));
  } else if (item.daily_pick_id) {
    chips.push(chipHtml("有候选", "chip-blue"));
  } else {
    chips.push(chipHtml("无候选", "chip-neutral"));
  }
  return chips.join("");
}

function reviewRunStatusText(value) {
  return {
    completed: "复盘完成",
    blocked: "复盘阻断",
    failed: "复盘失败",
    skipped: "复盘跳过",
    running: "复盘运行中",
    planned: "复盘待定",
    success: "复盘成功",
  }[value] || dash(value);
}

function reviewRunStatusClass(value) {
  return {
    completed: "chip-green",
    success: "chip-green",
    blocked: "chip-red",
    failed: "chip-red",
    skipped: "chip-neutral",
    running: "chip-amber",
    planned: "chip-neutral",
  }[value] || "chip-neutral";
}

function agentRunStatusText(value) {
  return {
    completed: "已完成",
    failed: "失败",
    skipped: "跳过",
    running: "运行中",
    planned: "待定",
    not_run: "未运行",
    unavailable: "不可用",
    success: "已完成",
  }[value] || dash(value);
}

function agentRunStatusClass(value) {
  return {
    completed: "chip-indigo",
    success: "chip-indigo",
    failed: "chip-red",
    skipped: "chip-neutral",
    running: "chip-amber",
    planned: "chip-neutral",
    not_run: "chip-neutral",
    unavailable: "chip-neutral",
  }[value] || "chip-neutral";
}

function displayTimestamp(value) {
  if (value == null || value === "") return "-";
  const text = String(value).trim().replace("T", " ").replace("Z", "");
  if (text.length >= 16) return text.slice(0, 16);
  return text;
}

function qualityClass(value) {
  return {
    pass: "chip-green",
    warning: "chip-amber",
    blocker: "chip-red",
  }[value] || "chip-neutral";
}

function statusClass(value) {
  if (["active", "success"].includes(value)) return "chip-blue";
  if (["executed", "closed"].includes(value)) return "chip-green";
  if (["need_t2_decision", "need_t5_exit", "failed"].includes(value)) return "chip-red";
  if (["expired", "planned_exit", "holding_to_t5", "waiting_t2"].includes(value)) return "chip-amber";
  return "chip-neutral";
}

function actionClass(value) {
  if (value === "buy_next_open") return "chip-blue";
  if (String(value || "").startsWith("sell_")) return "chip-amber";
  if (String(value || "").startsWith("skip_")) return "chip-neutral";
  return "chip-neutral";
}

function severityClass(value) {
  return value === "blocker" ? "chip-red" : value === "warning" ? "chip-amber" : "chip-neutral";
}

function dueClass(value) {
  if (["t2", "t5", "buy_day_2_decision", "buy_day_5_exit"].includes(value)) return "chip-red";
  if (["exit_planned", "sell_plan_exists"].includes(value)) return "chip-amber";
  return "chip-neutral";
}

function actionIsSell(action) {
  return String(action || "").startsWith("sell_");
}

function returnClass(value) {
  if (value == null) return "";
  return Number(value) >= 0 ? "text-profit" : "text-loss";
}

function actionMetrics(items) {
  return `
    <div class="action-meta">
      ${items.map(([label, value]) => `
        <div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>
      `).join("")}
    </div>
  `;
}

function chipHtml(label, className) {
  return `<span class="chip ${className}">${escapeHtml(label)}</span>`;
}

function emptyState(text) {
  return `<div class="empty-state">${escapeHtml(text)}</div>`;
}

function emptyRow(columns, text) {
  return `<tr><td colspan="${columns}"><div class="empty-state">${escapeHtml(text)}</div></td></tr>`;
}

function errorMessages(envelope) {
  return (envelope.errors || []).map((error) => error.message || error.code);
}

function money(value) {
  if (value == null || value === "") return "-";
  return Number(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function numberText(value, digits = 2) {
  if (value == null || value === "") return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return number.toFixed(digits);
}

function scoreText(value) {
  if (value == null || value === "") return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return number.toFixed(2);
}

function integerText(value) {
  if (value == null || value === "") return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return String(Math.trunc(number));
}

function percent(value) {
  if (value == null || value === "") return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return `${(number * 100).toFixed(2)}%`;
}

function dash(value) {
  return value == null || value === "" ? "-" : String(value);
}

function listValue(value) {
  return Array.isArray(value) ? value.filter((item) => item != null && String(item).trim() !== "").map(String) : [];
}

function parseOptionalInt(value) {
  const text = String(value || "").trim();
  return text ? integerValue(text, "整数") : null;
}

function positiveIntegerOrNull(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  const number = Number(text);
  return Number.isInteger(number) && number > 0 ? number : null;
}

function positiveNumberOrNull(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  const number = Number(text);
  return Number.isFinite(number) && number > 0 ? number : null;
}

function nonNegativeOptionalNumber(value) {
  const text = String(value || "").trim();
  if (!text) return true;
  const number = Number(text);
  return Number.isFinite(number) && number >= 0;
}

function integerValue(value, label) {
  const number = Number(value);
  if (!Number.isInteger(number) || number <= 0) {
    throw new Error(`${label} 必须是正整数。`);
  }
  return number;
}

function numericValue(value, label) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) {
    throw new Error(`${label} 必须是正数。`);
  }
  return number;
}

function optionalNumber(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  const number = Number(text);
  if (!Number.isFinite(number)) return null;
  return number;
}

function stripUndefined(value) {
  if (Array.isArray(value)) return value.map(stripUndefined);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([, item]) => item !== undefined && item !== null && item !== "")
        .map(([key, item]) => [key, stripUndefined(item)])
    );
  }
  return value;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
