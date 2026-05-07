const DEFAULT_STRATEGY_VERSION = "cpb_6157@2026-05-03";
const DEFAULT_ACCOUNT_KEY = "paper-main";
const LEGACY_DEFAULT_ACCOUNT_KEY = "paper-200k";
const DEFAULT_API_BASE = window.location.pathname.startsWith("/pgc/") ? "/pgc" : "";
const CANCEL_REASON_CHOICES = ["高开过大", "停牌/不可交易", "重大利空", "人工跳过"];

const state = {
  apiBase: localStorage.getItem("pgc.dashboard.apiBase") || DEFAULT_API_BASE,
  accountKey: dashboardAccountKey(),
  accountId: localStorage.getItem("pgc.dashboard.accountId") || "",
  asOfDate: localStorage.getItem("pgc.dashboard.asOfDate") || localDateCompact(),
  strategyVersion: localStorage.getItem("pgc.dashboard.strategyVersion") || DEFAULT_STRATEGY_VERSION,
  operator: localStorage.getItem("pgc.dashboard.operator") || "",
  dryRun: localStorage.getItem("pgc.dashboard.dryRun") !== "false",
  activePage: "execution",
  busy: false,
  report: null,
  reportEnvelope: null,
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
    "nextActionDate",
    "nextActionBody",
    "blockerList",
    "candidateSummary",
    "rankedSignalsBody",
    "duePositionsBody",
    "agentSummary",
    "agentPageBody",
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
    "drawerBody",
    "closeDrawerButton",
    "confirmDialog",
    "confirmTitle",
    "confirmBody",
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
  els.clearRecordButton.addEventListener("click", clearRecordForm);
  els.closeDrawerButton.addEventListener("click", closeDrawer);

  els.preOpenChecklist.addEventListener("change", onPreOpenChecklistChange);
  els.openingPlanBody.addEventListener("click", onPlansTableClick);
  els.openingCancelQueue.addEventListener("click", onPlansTableClick);
  els.openingExitQueue.addEventListener("click", onRecordQueueClick);
  els.plansBody.addEventListener("click", onPlansTableClick);
  els.recordQueue.addEventListener("click", onRecordQueueClick);
  els.positionsBody.addEventListener("click", onPositionsTableClick);
}

function syncFormFromState() {
  els.apiBaseInput.value = state.apiBase;
  els.accountKeyInput.value = state.accountKey;
  els.accountIdInput.value = state.accountId;
  els.asOfDateInput.value = state.asOfDate;
  els.strategyInput.value = state.strategyVersion;
  els.operatorInput.value = state.operator;
  els.dryRunInput.checked = state.dryRun;
}

function readContextForm() {
  state.apiBase = els.apiBaseInput.value.trim().replace(/\/$/, "");
  state.accountKey = els.accountKeyInput.value.trim();
  state.accountId = els.accountIdInput.value.trim();
  state.asOfDate = normalizeDate(els.asOfDateInput.value);
  state.strategyVersion = els.strategyInput.value.trim() || DEFAULT_STRATEGY_VERSION;
  state.operator = els.operatorInput.value.trim();
  state.dryRun = els.dryRunInput.checked;
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

async function refreshAll() {
  setBusy(true);
  showNotice("");
  try {
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
    const payload = supportedWritePayload("review", {
      as_of_date: state.asOfDate,
      strategy_version: state.strategyVersion,
      force_new_review_run: false,
      max_daily_picks: 1,
      ...selectedAccountPayload(),
    });
    if (!state.dryRun) {
      const ok = await confirmAction({
        title: "确认运行复盘",
        body: `将对复盘日 ${displayDate(state.asOfDate)} 写入复盘结果和计划。`,
      });
      if (!ok.confirmed) return;
    }
    const envelope = await apiRequest("/api/review-runs", { method: "POST", body: payload });
    handleMutationEnvelope(envelope, "复盘请求已完成");
    await refreshAll();
  });
}

async function publishPlan(tradePlanId) {
  if (hasBlockingQuality()) {
    showNotice("存在数据质量 blocker，不能发布计划。");
    return;
  }
  const payload = requiredWritePayload(`publish:${tradePlanId}`, selectedAccountPayload());
  const ok = await confirmAction({
    title: "确认发布计划",
    body: `计划 ${tradePlanId} 将进入 active 状态。此操作不支持 dry run。`,
  });
  if (!ok.confirmed) return;
  await runWithNotice(async () => {
    const envelope = await apiRequest(`/api/trade-plans/${tradePlanId}/publish`, {
      method: "POST",
      body: payload,
    });
    handleMutationEnvelope(envelope, "计划发布请求已完成");
    await refreshAll();
  });
}

async function cancelPlan(tradePlanId) {
  const ok = await confirmAction({
    title: "确认取消计划",
    body: `计划 ${tradePlanId} 将被标记为 cancelled。此操作不支持 dry run。`,
    inputLabel: "取消原因",
    quickChoices: CANCEL_REASON_CHOICES,
  });
  if (!ok.confirmed) return;
  const cancelReason = ok.value.trim();
  if (!cancelReason) {
    showNotice("取消计划需要填写原因。");
    return;
  }
  const payload = requiredWritePayload(`cancel:${tradePlanId}`, {
    ...selectedAccountPayload(),
    cancel_reason: cancelReason,
  });
  await runWithNotice(async () => {
    const envelope = await apiRequest(`/api/trade-plans/${tradePlanId}/cancel`, {
      method: "POST",
      body: payload,
    });
    handleMutationEnvelope(envelope, "计划取消请求已完成");
    await refreshAll();
  });
}

async function submitTradeRecord(event) {
  event.preventDefault();
  await runWithNotice(async () => {
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
    const payload = supportedWritePayload(`trade:${tradePlanId || positionId}`, {
      trade_plan_id: tradePlanId || undefined,
      position_id: positionId || undefined,
      side: positionId ? undefined : els.recordSide.value,
      executed_date: normalizeDate(els.recordDate.value),
      executed_price: numericValue(els.recordPrice.value, "成交价"),
      shares: integerValue(els.recordShares.value, "股数"),
      fee: optionalNumber(els.recordFee.value) ?? 0,
      tax: optionalNumber(els.recordTax.value) ?? 0,
      slippage: optionalNumber(els.recordSlippage.value),
      source: "dashboard",
      ...selectedAccountPayload(),
    });
    if (!state.dryRun) {
      const ok = await confirmAction({
        title: "确认记录成交",
        body: `将写入成交日期 ${displayDate(payload.executed_date)} 的成交事实；Dashboard 不会向券商下单。`,
      });
      if (!ok.confirmed) return;
    }
    const envelope = await apiRequest("/api/trades", { method: "POST", body: payload });
    handleMutationEnvelope(envelope, "成交录入请求已完成");
    clearRecordForm();
    await refreshAll();
  });
}

async function evaluateExits() {
  await runWithNotice(async () => {
    const payload = supportedWritePayload("exits", {
      as_of_date: state.asOfDate,
      generate_sell_plans: true,
      ...selectedAccountPayload(),
    });
    if (!state.dryRun) {
      const ok = await confirmAction({
        title: "确认评估退出",
        body: `将对复盘日 ${displayDate(state.asOfDate)} 到期持仓生成退出决策/卖出计划，不会记录卖出成交。`,
      });
      if (!ok.confirmed) return;
    }
    const envelope = await apiRequest("/api/exits/evaluate", { method: "POST", body: payload });
    handleMutationEnvelope(envelope, "退出评估请求已完成");
    await refreshAll();
  });
}

function handleMutationEnvelope(envelope, successText) {
  if (envelope.status !== "success" && envelope.status !== "skipped") {
    const messages = errorMessages(envelope).join("；") || `请求状态：${envelope.status}`;
    throw new Error(messages);
  }
  showNotice(successText, "ok");
}

function renderAll() {
  renderOpeningExecution();
  renderStatusBand();
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
  const activePlans = todaysBuyPlans().filter((plan) => plan.status === "active");
  const visiblePlans = todaysBuyPlans().length ? todaysBuyPlans() : activeBuyPlans();
  const executionDay = executionDate();

  executionPlanPanel.classList.toggle("blocked", blocked);
  executionPlanPanel.classList.toggle("idle", !blocked && activePlans.length === 0);
  els.openingBlockerChip.textContent = blocked ? "数据阻断" : activePlans.length ? "可执行" : "无 active 买入计划";
  els.openingBlockerChip.className = `chip ${blocked ? "chip-red" : activePlans.length ? "chip-green" : "chip-neutral"}`;

  if (blocked) {
    const blockers = blockingEvents().slice(0, 2).map((item) => escapeHtml(item.message || item.code || "数据阻断")).join("；");
    els.openingPlanBody.innerHTML = `
      <h3 class="action-title">数据质量 blocker，买入执行按钮已禁用</h3>
      <p class="muted">${blockers || "请先处理数据质量页面中的 blocker。"}</p>
      ${actionMetrics([
        ["执行日", displayDate(executionDay)],
        ["active 买入计划", String(activePlans.length)],
        ["阻断数", String(blockingEvents().length)],
        ["账户容量", capacityText(state.report?.account)],
      ])}
    `;
  } else if (visiblePlans.length) {
    els.openingPlanBody.innerHTML = visiblePlans.map((plan) => openingPlanCard(plan, executionDay)).join("");
  } else {
    els.openingPlanBody.innerHTML = emptyState(`没有计划交易日为 ${displayDate(executionDay)} 的 active 买入计划。`);
  }

  renderPreOpenChecklist(activePlans, executionDay, blocked);
  renderOpeningCancelQueue();
  renderOpeningExitQueue();
}

function openingPlanCard(plan, executionDay) {
  const isActive = plan.status === "active";
  const canRecord = isActive && !hasBlockingQuality();
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
        ["计划交易日", displayDate(planTradeDate(plan))],
        ["执行日匹配", planTradeDate(plan) === executionDay ? "是" : "否"],
        ["计划股数", integerText(plannedShares(plan))],
        ["计划资金", money(plannedCash(plan))],
      ])}
      <div class="row-actions">
        <button type="button" data-plan-action="record" data-plan-id="${plan.id}" ${canRecord ? "" : "disabled"}>录入买入成交</button>
        <button type="button" data-plan-action="cancel" data-plan-id="${plan.id}" ${canCancel ? "" : "disabled"}>取消计划</button>
        <button type="button" data-plan-action="detail" data-plan-id="${plan.id}">详情</button>
      </div>
    </div>
  `;
}

function renderPreOpenChecklist(activePlans, executionDay, blocked) {
  const hasExecutionPlan = activePlans.some((plan) => planTradeDate(plan) === executionDay);
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
  const checkedCount = items.filter(([, , checked]) => checked).length;
  els.preOpenChecklistState.textContent = `${checkedCount}/${items.length} 已确认`;
  els.preOpenChecklistState.className = `chip ${!blocked && checkedCount === items.length ? "chip-green" : "chip-amber"}`;
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
    renderPreOpenChecklist(todaysBuyPlans().filter((plan) => plan.status === "active"), executionDate(), hasBlockingQuality());
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

function renderNextAction() {
  const report = state.report;
  const panel = document.querySelector(".next-action-panel");
  const plan = report?.buy_plan;
  const candidate = report?.candidate;
  const blocked = hasBlockingQuality();
  els.nextActionDate.textContent = `下一交易日 ${displayDate(report?.next_trade_date)}`;
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
    els.candidateSummary.innerHTML = emptyState(`无候选：${reasonText(state.report?.no_candidate_reason)}`);
    els.rankedSignalsBody.innerHTML = emptyRow(4, "没有候选明细。");
    return;
  }
  const features = candidate.features || {};
  els.candidateSummary.innerHTML = `
    <div class="action-meta">
      <div class="metric"><span>股票</span><strong>${escapeHtml(candidate.ts_code)} ${escapeHtml(candidate.name)}</strong></div>
      <div class="metric"><span>评分</span><strong>${numberText(candidate.score, 4)}</strong></div>
      <div class="metric"><span>计划买入日</span><strong>${displayDate(candidate.planned_buy_date)}</strong></div>
      <div class="metric"><span>胜出信号数</span><strong>${dash(candidate.selected_over_signal_count)}</strong></div>
      <div class="metric"><span>回撤幅度</span><strong>${percent(features.drawdown_from_peak)}</strong></div>
      <div class="metric"><span>缩量比</span><strong>${numberText(features.amount_contract_ratio, 2)}</strong></div>
      <div class="metric"><span>阳线实体</span><strong>${percent(features.bull_body)}</strong></div>
      <div class="metric"><span>血缘</span><strong>信号 ${candidate.signal_id}</strong></div>
    </div>
  `;
  const rows = candidate.ranked_signals || [];
  els.rankedSignalsBody.innerHTML = rows.length
    ? rows.map((signal) => `
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
    const html = emptyState("暂无 Agent 复核数据。");
    els.agentSummary.innerHTML = html;
    els.agentPageBody.innerHTML = html;
    return;
  }
  els.agentSummary.innerHTML = renderAgentAdvice(advice, { expanded: false });
  els.agentPageBody.innerHTML = renderAgentAdvice(advice, { expanded: true });
}

function renderAgentAdvice(advice, { expanded }) {
  const supportingPoints = listValue(advice.supporting_points);
  const riskPoints = listValue(advice.risk_points);
  const analystReports = Array.isArray(advice.analyst_reports) ? advice.analyst_reports : [];
  const artifacts = Array.isArray(advice.artifacts) ? advice.artifacts : [];
  const summary = advice.summary || advice.note || "Agent 复核尚未接入本次复盘。";
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
      <div class="agent-detail-grid">
        ${renderAgentPointSection("支持依据", supportingPoints, "暂无支持依据。")}
        ${renderAgentPointSection("风险提示", riskPoints, "暂无风险提示。")}
      </div>
      ${analystReports.length ? `
        <div class="agent-analyst-grid">
          ${analystReports.map(renderAgentAnalystCard).join("")}
        </div>
      ` : ""}
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
    <div class="action-meta">
      <div class="metric"><span>运行状态</span><strong>${statusText(advice.status)}</strong></div>
      <div class="metric"><span>意见</span><strong>${agentActionText(advice.action)}</strong></div>
      <div class="metric"><span>风险等级</span><strong>${riskText(advice.risk_level)}</strong></div>
      <div class="metric"><span>置信度</span><strong>${advice.confidence == null ? "-" : numberText(advice.confidence, 2)}</strong></div>
    </div>
    <p class="agent-summary-text">${escapeHtml(summary)}</p>
    ${quickPoints}
    ${detail}
    <p class="muted">Agent 只提供复核意见，不会自动发布、取消或记录成交。</p>
  `;
}

function renderAgentAnalystCard(report) {
  const supportingPoints = listValue(report.supporting_points);
  const riskPoints = listValue(report.risk_points);
  return `
    <section class="agent-analyst-card">
      <div class="agent-analyst-head">
        <h3>${escapeHtml(report.analyst_name || agentAnalystText(report.analyst_key))}</h3>
        ${chipHtml(agentAnalystStatusText(report.status), agentAnalystStatusClass(report.status))}
      </div>
      <p>${escapeHtml(report.summary || "该分析维度没有返回摘要。")}</p>
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
      const canRecord = !blocked && plan.status === "active";
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
              <button type="button" data-plan-action="record" data-plan-id="${plan.id}" ${canRecord ? "" : "disabled"}>成交</button>
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
  const planRows = activePlans.map((plan) => `
    <div class="list-row">
      ${chipHtml(actionText(plan.action), actionClass(plan.action))}
      <span>计划 ${plan.id} / ${escapeHtml(planStockText(plan))} / 交易日 ${displayDate(planTradeDate(plan))} / 股数 ${integerText(plannedShares(plan))}</span>
      <button type="button" data-record-plan-id="${plan.id}" ${hasBlockingQuality() ? "disabled" : ""}>录入</button>
    </div>
  `);
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
      </tr>
    `).join("")
    : emptyRow(8, "当前筛选下没有 open 数据质量事件。");
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

function onPositionsTableClick(event) {
  const button = event.target.closest("button[data-position-action]");
  if (!button) return;
  const position = findPosition(Number(button.dataset.positionId));
  if (!position) return;
  if (button.dataset.positionAction === "detail") selectPosition(position);
  if (button.dataset.positionAction === "sell") selectPosition(position, { openRecordPage: true });
}

function selectPlan(plan, options = {}) {
  state.selectedPlan = plan;
  openDrawer("交易计划", `计划 ${plan.id}`, [
    ["计划 ID", plan.id],
    ["账户 ID", plan.account_id],
    ["股票", planStockText(plan)],
    ["动作", actionText(plan.action)],
    ["状态", statusText(plan.status)],
    ["生成日", displayDate(plan.as_of_date)],
    ["计划交易日", displayDate(planTradeDate(plan))],
    ["计划股数", integerText(plannedShares(plan))],
    ["计划资金", money(plannedCash(plan))],
    ["入选记录", dash(planDailyPickId(plan))],
    ["信号记录", dash(planSignalId(plan))],
    ["操作者", dash(plan.operator)],
    ["创建时间", dash(plan.created_at)],
    ["原因", reasonText(plan.reason)],
    ["取消原因", plan.cancel_reason || "-"],
  ]);
  if (options.openRecordPage) {
    fillRecordFromPlan(plan);
    setActivePage("record");
  }
}

function selectPosition(position, options = {}) {
  state.selectedPosition = position;
  openDrawer("持仓", `${position.ts_code} ${position.name}`, [
    ["持仓 ID", position.position_id],
    ["账户 ID", position.account_id],
    ["买入日", displayDate(position.buy_date)],
    ["买入价", numberText(position.buy_price, 2)],
    ["股数", integerText(position.shares)],
    ["T+2", displayDate(position.planned_t2_date)],
    ["T+5", displayDate(position.planned_t5_date)],
    ["最新行情日", displayDate(position.latest_trade_date)],
    ["最新价", numberText(position.latest_close, 2)],
    ["收益", percent(position.unrealized_ret)],
    ["状态", statusText(position.status)],
    ["到期阶段", dueText(position.due_stage)],
  ]);
  if (options.openRecordPage) {
    fillRecordFromPosition(position);
    setActivePage("record");
  }
}

function fillRecordFromPlan(plan) {
  clearRecordForm(false);
  els.recordPlanId.value = plan.id;
  els.recordPositionId.value = "";
  els.recordSide.value = actionIsSell(plan.action) ? "sell" : "buy";
  els.recordDate.value = planTradeDate(plan) || state.report?.next_trade_date || "";
  els.recordShares.value = plannedShares(plan) || "";
  els.recordModeChip.textContent = plan.status === "active" ? "按 active 计划录入" : "计划未激活";
  els.recordModeChip.className = `chip ${plan.status === "active" ? "chip-blue" : "chip-amber"}`;
  setRecordFormState();
}

function fillRecordFromPosition(position) {
  clearRecordForm(false);
  els.recordPlanId.value = "";
  els.recordPositionId.value = position.position_id;
  els.recordSide.value = "sell";
  els.recordDate.value = state.asOfDate;
  els.recordShares.value = position.shares || "";
  els.recordPrice.value = position.latest_close || "";
  els.recordModeChip.textContent = "按持仓卖出录入";
  els.recordModeChip.className = "chip chip-amber";
}

function clearRecordForm(resetChip = true) {
  els.recordPlanId.value = "";
  els.recordPositionId.value = "";
  els.recordSide.value = "buy";
  els.recordDate.value = state.report?.next_trade_date || state.asOfDate;
  els.recordPrice.value = "";
  els.recordShares.value = "";
  els.recordFee.value = "0";
  els.recordTax.value = "0";
  els.recordSlippage.value = "";
  if (resetChip) {
    els.recordModeChip.textContent = "未选择";
    els.recordModeChip.className = "chip chip-neutral";
  }
  setRecordFormState();
}

function openLineageDrawer() {
  const lineage = state.report?.lineage;
  if (!lineage) {
    openDrawer("数据血缘", "暂无血缘", [["状态", "复盘报告未返回 lineage"]]);
    return;
  }
  openDrawer("数据血缘", `复盘日 ${displayDate(state.report.as_of_date)}`, [
    ["特征运行", dash(lineage.feature_run_id)],
    ["策略运行", dash(lineage.strategy_run_id)],
    ["行情抓取", dash(lineage.market_fetch_run_id)],
    ["入选记录", dash(lineage.daily_pick_id)],
    ["信号记录", dash(lineage.signal_id)],
    ["计划记录", dash(lineage.trade_plan_id)],
    ["Agent 运行", dash(lineage.agent_run_id)],
    ["Agent 意见", dash(lineage.agent_decision_id)],
    ["质量事件", (lineage.data_quality_event_ids || []).join(", ") || "-"],
  ]);
}

function openDrawer(kicker, title, rows) {
  els.drawerKicker.textContent = kicker;
  els.drawerTitle.textContent = title;
  els.drawerBody.innerHTML = `
    <dl class="kv">
      ${rows.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(String(value ?? "-"))}</dd>`).join("")}
    </dl>
  `;
  els.detailDrawer.hidden = false;
}

function closeDrawer() {
  els.detailDrawer.hidden = true;
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

function blockingEvents() {
  const envelopeErrors = (state.reportEnvelope?.errors || []).filter((error) => {
    return error.severity === "blocker" || error.code === "VALIDATION_ERROR";
  });
  const qualityBlockers = state.qualityEvents.filter((event) => event.severity === "blocker");
  const readinessBlocker = state.report?.data_quality?.readiness === "blocker"
    ? [{
      severity: "blocker",
      code: "READINESS_BLOCKER",
      message: `复盘日 ${displayDate(state.asOfDate)} 数据状态为 blocker。`,
    }]
    : [];
  return [...readinessBlocker, ...envelopeErrors, ...qualityBlockers];
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

function plannedShares(plan) {
  return plan?.planned_shares ?? plan?.shares ?? plan?.plan_json?.planned_shares ?? plan?.plan_json?.shares ?? null;
}

function plannedCash(plan) {
  return plan?.planned_cash ?? plan?.planned_amount ?? plan?.plan_json?.planned_cash ?? null;
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
  const planId = Number(String(els.recordPlanId.value || "").trim());
  const plan = Number.isFinite(planId) && planId > 0 ? findPlan(planId) : null;
  els.submitRecordButton.disabled = Boolean(plan && hasBlockingQuality());
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

function confirmAction({ title, body, inputLabel, quickChoices = [] }) {
  if (!els.confirmDialog.showModal) {
    const confirmed = window.confirm(body);
    const value = inputLabel && confirmed ? window.prompt(inputLabel, "") || "" : "";
    return Promise.resolve({ confirmed, value });
  }
  els.confirmTitle.textContent = title;
  els.confirmBody.textContent = body;
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
  els.confirmSubmit.textContent = "确认";
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

function localDateCompact() {
  const date = new Date();
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}${month}${day}`;
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

function normalizeDate(value) {
  return String(value || "").trim().replaceAll("-", "");
}

function displayDate(value) {
  if (value == null || value === "") return "-";
  const text = String(value);
  if (/^\d{8}$/.test(text)) return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`;
  return text;
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
