const DEFAULT_STRATEGY_VERSION = "cpb_6157@2026-05-03";
const DEFAULT_ACCOUNT_KEY = "paper-main";
const LEGACY_DEFAULT_ACCOUNT_KEY = "paper-200k";
const DEFAULT_API_BASE = window.location.pathname.startsWith("/pgc/") ? "/pgc" : "";
const DEFAULT_OPERATOR = "azboo";
const CANCEL_REASON_CHOICES = ["高开过大", "停牌/不可交易", "重大利空", "人工跳过"];
const DRY_RUN_DEFAULT_VERSION = "20260508-live-writes-1";
const AGENT_ANALYST_SECTIONS = [
  ["technical", "技术面"],
  ["fundamental", "基本面"],
  ["news", "新闻面"],
  ["sentiment", "情绪面"],
];

const state = {
  apiBase: localStorage.getItem("pgc.dashboard.apiBase") || DEFAULT_API_BASE,
  accountKey: dashboardAccountKey(),
  accountId: localStorage.getItem("pgc.dashboard.accountId") || "",
  asOfDate: localStorage.getItem("pgc.dashboard.asOfDate") || defaultReviewDate(),
  strategyVersion: localStorage.getItem("pgc.dashboard.strategyVersion") || DEFAULT_STRATEGY_VERSION,
  operator: dashboardOperator(),
  dryRun: dashboardDryRun(),
  activePage: "execution",
  busy: false,
  reviewDatePinned: false,
  report: null,
  reportEnvelope: null,
  reviewHistory: [],
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
    "apiBaseInput",
    "dryRunInput",
    "executionBadge",
    "reloadExecutionButton",
    "executionEvaluateExitsButton",
    "openingWorkflowGuide",
    "openingReadinessSummary",
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
  els.reviewHistoryList.addEventListener("click", onReviewHistoryClick);
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
  els.strategyInput.value = state.strategyVersion;
  els.operatorInput.value = state.operator;
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
  state.dryRun = els.dryRunInput.checked;
  state.reviewDatePinned = true;
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
  localStorage.setItem("pgc.dashboard.dryRun", String(state.dryRun));
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

async function setReviewDate(value) {
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
  state.asOfDate = nextDate;
  state.reviewDatePinned = true;
  resetPreOpenChecks();
  syncFormFromState();
  persistContext();
  setActivePage("review");
  await refreshAll({ autoLatest: false });
}

async function refreshAll(options = {}) {
  setBusy(true);
  if (!options.keepNotice) showNotice("");
  try {
    await loadReviewHistory();
    if (shouldAdoptLatestReviewDate(options)) {
      state.asOfDate = latestReviewHistoryDate();
      resetPreOpenChecks();
      syncFormFromState();
      persistContext();
    }
    await loadDailyReport();
    await Promise.all([loadPlans(), loadQuality(), loadPositions()]);
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
    await loadReviewHistory();
    renderReviewHistory();
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
  renderReviewHistory();
  renderReviewScopeMarkers();
  renderReview();
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
  const guidance = openingWorkflowGuidance(readiness, executionPlans, executionDay);
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
    </div>
    <div class="workflow-guide__actions">
      ${guidance.actions.map(workflowActionButton).join("")}
    </div>
  `;
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

function openingPlanCard(plan, executionDay) {
  const isActive = plan.status === "active";
  const matchesExecutionDay = planTradeDate(plan) === executionDay;
  const lockReason = recordLockReasonForPlan(plan, executionDay);
  const canRecord = !lockReason;
  const canCancel = ["draft", "active"].includes(plan.status);
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
    </div>
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
  els.statusNextDate.textContent = displayDate(report?.next_trade_date);
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
  const execution = `执行日 ${displayDate(state.report?.next_trade_date)}`;
  els.currentReviewDateLabel.textContent = `当前复盘日：${displayDate(state.asOfDate)}`;
  els.blockerReviewScope.textContent = selected;
  els.candidateReviewScope.textContent = selected;
  els.dueReviewScope.textContent = `${selected} / ${execution}`;
  els.agentReviewScope.textContent = selected;
}

function renderNextAction() {
  const report = state.report;
  const panel = document.querySelector(".next-action-panel");
  const plan = report?.buy_plan;
  const candidate = report?.candidate;
  const blocked = hasBlockingQuality();
  els.nextActionDate.textContent = `复盘日 ${displayDate(report?.as_of_date || state.asOfDate)} / 执行日 ${displayDate(report?.next_trade_date)}`;
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

function renderAgentAdvice(advice, { expanded }) {
  const supportingPoints = listValue(advice.supporting_points);
  const riskPoints = listValue(advice.risk_points);
  const analystReports = normalizedAgentAnalystReports(advice);
  const artifacts = Array.isArray(advice.artifacts) ? advice.artifacts : [];
  const sourceRefs = listValue(advice.source_refs);
  const unavailable = agentAdviceUnavailable(advice);
  const summary = advice.summary || advice.note || agentUnavailableText(advice);
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
      </div>
      <div class="action-meta agent-report-metrics">
        <div class="metric"><span>运行状态</span><strong>${agentRunStatusText(advice.status)}</strong></div>
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
  const activePlans = state.tradePlans.filter((plan) => plan.status === "active").length;
  const draftPlans = state.tradePlans.filter((plan) => plan.status === "draft").length;
  const due = duePositions().length;
  els.executionBadge.textContent = String(todaysBuyPlans().filter((plan) => plan.status === "active").length + due);
  els.reviewBadge.textContent = blockers ? String(blockers) : state.report?.buy_plan ? "1" : "0";
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
    action.page ? `data-page="${escapeHtml(action.page)}"` : "",
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
  return [state.accountKey, state.accountId, state.asOfDate, state.strategyVersion].join("|");
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
  return normalizeDate(state.report?.next_trade_date || state.asOfDate);
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
    blocker: "阻断",
  }[value] || "-";
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
    raw_state: "运行状态",
    final_report: "复核报告",
    debug_log: "调试日志",
    memory_delta: "记忆变更",
    tool_trace: "工具轨迹",
  }[value] || dash(value);
}

function agentAnalystText(value) {
  return {
    technical: "技术面",
    fundamental: "基本面",
    news: "新闻面",
    sentiment: "情绪面",
  }[value] || dash(value);
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
        <div class="metric"><span>${escapeHtml(label)}</span><strong>${String(value)}</strong></div>
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
