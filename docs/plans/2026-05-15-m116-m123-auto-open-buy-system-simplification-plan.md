# M116-M123 Auto Open Buy And System Simplification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current manual opening checklist with a paper-only automatic open-price buy flow, then simplify the operator system so a user can understand "today buy or not, what happened, and what needs attention" within one screen.

**Architecture:** The first release is paper-ledger automation, not live broker auto-ordering. A valid active buy plan for the execution date is automatically filled at the official opening price once the open price is available, using strict idempotency and account guards. The UI becomes command-center first: primary action/status on the first screen, detail/evidence/research surfaces behind drawers or secondary tabs.

**Tech Stack:** Python services/CLI/API, SQLite, existing portfolio/trade ledger state machine, static Dashboard JavaScript/CSS, daily reports, pytest/unittest, remote deployment on port `8020`.

---

## Product Strategy

Current problem:
- Too many surfaces are visible at once: daily review, market review, evidence, Agent, shadow strategy, readiness, ops history, action logs, and opening execution all compete for attention.
- The "开盘执行" workflow still asks the operator to manually tick checks and manually enter price/date/shares, which defeats the goal of a simple paper strategy loop.
- The system has strong safety machinery, but the user-facing shape does not explain the daily workflow.

New target workflow:
1. 收盘后：系统生成明日有效买入计划。
2. 开盘后：系统读取该标的官方开盘价，自动按计划股数/金额写入纸盘买入成交。
3. 成交后：系统生成一条清楚的交易明细：计划、价格、股数、金额、手续费、仓位、来源、幂等键。
4. 操作台首页只显示：今日状态、自动成交明细、异常/阻断、下一步。
5. 证据、全市场、Agent、影子策略、运维全部变成可展开详情，不再铺满主屏。

Non-goals for this wave:
- 不接 live broker 自动下单。
- 不自动晋级影子策略。
- 不因为 market review / Agent 文本直接改写交易计划。
- 不在没有开盘价、没有有效计划、账户容量不足、重复持仓、数据质量 blocker 时强行成交。

## Parallel Map

| Lane | Task | Can Run In Parallel | Primary Write Scope | Review Focus |
| --- | --- | --- | --- | --- |
| A | M116 Auto-open buy contract and policy | Yes | service contract, CLI/API request models, tests | Define exact eligibility and why it may auto-fill without manual checklist |
| B | M117 Open-price paper fill engine | After M116 contract | portfolio execution service, DB writes, tests | Idempotent paper buy at official open price; creates trade + position + plan linkage |
| C | M118 Auto execution pipeline and audit artifact | After M117 | scripts/ops CLI/reports/tests | One command/timer-safe job produces auto-fill summary and audit trail |
| D | M119 Dashboard command center simplification | Parallel with B after API shape | `web/dashboard/*`, static/visual tests | First screen explains today status, auto trade details, blockers, next step |
| E | M120 Information architecture reset | Yes | Dashboard nav/layout/docs/tests | Collapse noisy pages into primary/secondary/research/ops groups |
| F | M121 Chinese terminology and state dictionary | Yes | UI label helpers, reports, tests | Replace raw internal labels with one consistent Chinese vocabulary |
| G | M122 Daily report simplification | Parallel with C | report renderer/tests/artifacts | Daily report summary first; evidence/research details folded below |
| H | M123 Release, migration, rollback, and adoption gate | Last | runbook/ledger/deploy tests | Deploy only after paper-only automation is proven and reversible |

## M116: Auto-Open Buy Contract And Policy

**Goal:** Define the exact policy for automatic open-price paper buys so child sessions do not improvise.

**Files:**
- Create: `src/pgc_trading/services/auto_open_buy_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `src/pgc_trading/api.py` if API route is added
- Test: `tests/test_auto_open_buy_service.py`
- Test: `tests/test_cli_auto_open_buy.py`

**Policy contract:**
- Account: `paper-main` by default; live accounts are rejected.
- Plan eligibility:
  - `trade_plans.account_id` matches account.
  - `trade_plans.status = active`.
  - plan action is buy / next-trading-day buy.
  - `planned_trade_date == execution_date`.
  - exactly one eligible buy plan exists, unless future config explicitly allows priority ranking.
- Open price:
  - use official `market_bars.open` for `ts_code` and `execution_date`.
  - never use yfinance diagnostic price.
  - never use current browser-entered price.
  - if open price is missing, result is `waiting_open_price`, no write.
- Idempotency:
  - key format: `auto-open-buy:<account_key>:<execution_date>:<trade_plan_id>`.
  - rerun with same key returns existing trade detail, not a duplicate trade.
- Guards:
  - no open data-quality blocker.
  - account has free capacity.
  - no duplicate open position for the same `ts_code`.
  - no existing executed trade for the same `trade_plan_id`.
  - write mode requires operator `system:auto-open-buy` or configured operator.

**Steps:**
1. Add dataclasses:
   - `AutoOpenBuyRequest(execution_date, account_key, apply, operator, idempotency_key=None)`.
   - `AutoOpenBuyResult(status, eligible_plan, open_price, would_write, trade_detail, blockers, audit)`.
2. Add a dry-run service path returning `ready_to_fill` or blocker state.
3. Add tests for no plan, multiple plans, missing open price, duplicate position, non-paper account rejection, and ready dry-run.
4. Add CLI command:
   - `pgc ops auto-open-buy --date YYYYMMDD --account paper-main --dry-run`
   - `pgc ops auto-open-buy --date YYYYMMDD --account paper-main --apply --operator system:auto-open-buy`
5. Verify:
   - `PYTHONPATH=src:. pytest -q tests/test_auto_open_buy_service.py tests/test_cli_auto_open_buy.py`
   - `python3 -m compileall -q src scripts`

## M117: Open-Price Paper Fill Engine

**Goal:** When M116 policy says ready, write the paper buy trade and resulting position automatically at the official open price.

**Files:**
- Modify: `src/pgc_trading/services/auto_open_buy_service.py`
- Reuse or modify: `src/pgc_trading/services/execution_recording_service.py`
- Test: `tests/test_auto_open_buy_service.py`
- Test: `tests/test_execution_recording_service.py` only if shared behavior changes

**Write behavior:**
- Create a buy trade linked to `trade_plan_id`.
- `executed_date = execution_date`.
- `executed_price = market_bars.open`.
- `shares = planned_shares` when present; otherwise calculate from planned cash using lot size 100.
- fee/tax/slippage follows existing paper execution defaults.
- Mark plan `executed`.
- Create/update position through the existing ledger state machine.
- Return a normalized `trade_detail` with trade id, position id, price, shares, gross amount, fee, total cash impact, source rows, and idempotency key.

**Steps:**
1. Write failing tests proving a ready plan creates exactly one trade and one open/waiting position.
2. Implement apply path by calling existing execution recording primitives where possible.
3. Add idempotent rerun test: second apply returns the first trade id and does not change table counts.
4. Add no-future test: cannot use an open price from a later date.
5. Add account isolation test: live account and wrong account are rejected.
6. Verify:
   - `PYTHONPATH=src:. pytest -q tests/test_auto_open_buy_service.py tests/test_execution_recording_service.py`
   - `PYTHONPATH=src:. pytest -q tests/test_storage_invariants.py` if invariant tests exist.

## M118: Auto Execution Pipeline And Audit Artifact

**Goal:** Make the automatic open buy runnable by a job and visible as an audit artifact.

**Files:**
- Create: `scripts/run_open_buy_auto.sh`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Add artifact pattern: `reports/auto_open_buy_YYYYMMDD.{json,md}`
- Test: `tests/test_auto_open_buy_script.py`
- Test: `tests/test_daily_report.py`

**Steps:**
1. Add a script that runs:
   - health check/preflight.
   - dry-run auto-open-buy.
   - apply only when status is `ready_to_fill` and `PGC_AUTO_OPEN_BUY_ENABLED=1`.
   - post-apply readback and invariant check.
2. Output a Markdown/JSON audit report with:
   - status.
   - plan id.
   - stock.
   - open price.
   - shares.
   - trade id.
   - position id.
   - idempotency key.
   - blockers or skipped reason.
3. Add report integration: daily report shows "今日自动成交" near the top.
4. Add systemd/timer installer only in preview mode. Real timer activation remains a separate deployment decision.
5. Verify:
   - `bash -n scripts/run_open_buy_auto.sh`
   - `PYTHONPATH=src:. pytest -q tests/test_auto_open_buy_script.py tests/test_daily_report.py`

## M119: Dashboard Command Center Simplification

**Goal:** Replace the current cluttered first impression with one command-center view.

**Files:**
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/styles.css`
- Test: `tests/test_dashboard_static.py`

**New first screen sections:**
1. `今日状态`
   - 自动买入：已成交 / 等开盘价 / 无有效计划 / 阻断。
   - 执行日 and account.
2. `今日自动成交明细`
   - trade id, position id, stock, open price, shares, amount, source.
3. `异常与阻断`
   - only show blockers that require attention.
4. `下一步`
   - e.g. "等待 T+2", "查看成交明细", "处理数据缺口".

**UI rules:**
- Manual opening checklist is hidden or removed from the primary path.
- Full-market, evidence, Agent, shadow, ops move to secondary drawers/tabs.
- No raw keys like `paper_live`, `source_refs`, `open_execution`, `strategy_hypothesis` in visible primary copy.

**Steps:**
1. Add static tests for the four command-center labels.
2. Add a read model function that consumes auto-open-buy audit + existing report state.
3. Build a dense command-center layout, not a marketing page.
4. Move old panels behind "详情" drawers where still useful.
5. Verify:
   - `node --check web/dashboard/app.js`
   - `PYTHONPATH=src:. pytest -q tests/test_dashboard_static.py`
   - browser screenshot QA in M114 style if available.

## M120: Information Architecture Reset

**Goal:** Make the system understandable by reducing top-level pages.

**Files:**
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/styles.css`
- Modify: `reports/product_information_architecture.md`
- Test: `tests/test_dashboard_static.py`

**Target navigation:**
- `今日操作`: command center, auto buy result, blockers, next step.
- `复盘`: daily review + market review history.
- `持仓`: positions, exits, paper readiness.
- `研究`: Agent, full-market evidence, shadow strategy, strategy evolution.
- `运维`: deployment, pipeline, parity, evidence pack, health.

**Steps:**
1. Map every current tab to one of the five target groups.
2. Keep URLs/IDs stable where possible; only change visible IA and grouping.
3. Add a "这是干嘛" one-line Chinese summary for each group, but avoid long in-app docs.
4. Add tests that old noisy labels are not primary nav labels.
5. Verify Dashboard static and visual smoke.

## M121: Chinese Terminology And State Dictionary

**Goal:** Stop the page from mixing English/internal states with Chinese workflow language.

**Files:**
- Modify: `web/dashboard/app.js`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Add or modify: a shared label map if one exists
- Test: `tests/test_dashboard_static.py`
- Test: `tests/test_daily_report.py`

**Dictionary examples:**
- `paper` -> `纸盘`
- `live` -> `实盘`
- `open_execution` -> `开盘执行`
- `auto_open_buy` -> `自动开盘买入`
- `ready_to_fill` -> `可自动成交`
- `waiting_open_price` -> `等待开盘价`
- `blocked` -> `阻断`
- `warning` -> `需复核`
- `shadow` -> `影子策略`
- `evidence` -> `证据`

**Steps:**
1. Add tests for visible copy in Dashboard and daily report.
2. Centralize label rendering so new statuses do not leak raw keys.
3. Update report sections to use the same terms as Dashboard.
4. Verify no raw internal keys in primary UI/report summaries.

## M122: Daily Report Simplification

**Goal:** Make daily reports readable again by putting the answer first and details later.

**Files:**
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Refresh: `reports/daily_review_YYYYMMDD.{json,md}` for latest relevant dates
- Test: `tests/test_daily_report.py`

**New report order:**
1. `今日结论`
2. `自动成交明细`
3. `明日/下一步`
4. `持仓与退出`
5. `数据和证据异常`
6. `全市场/Agent/影子策略详情`
7. `审计与来源`

**Steps:**
1. Add tests for section order.
2. Add compact auto-open-buy summary fields to report JSON.
3. Move verbose evidence/shadow sections below the top-level summary.
4. Verify Markdown contains fewer raw IDs in the first 80 lines.

## M123: Release, Migration, Rollback, And Adoption Gate

**Goal:** Deploy the simplified automatic paper-open flow safely and make rollback obvious.

**Files:**
- Modify: `reports/operational_runbook_design.md`
- Modify: `docs/plans/global-task-ledger.md`
- Modify: deployment docs/scripts only if needed
- Test: ops/runbook static tests

**Steps:**
1. Document enablement:
   - default disabled.
   - enable with `PGC_AUTO_OPEN_BUY_ENABLED=1`.
   - paper account only.
2. Document rollback:
   - disable env flag.
   - stop timer.
   - restore DB backup if a wrong paper fill was written.
3. Add release checklist:
   - auto-open-buy dry-run.
   - apply on test date.
   - idempotency rerun.
   - Dashboard command center screenshot.
   - remote health.
4. Update ledger and deploy:
   - `bash scripts/deploy_remote.sh --release-tag pgc-v0.1.0-20260515-m116-m123-auto-open-buy-simplify-r1`
   - remote `ops health --require-current-migrations`.

## Integration Gate

Before final deployment:

```bash
node --check web/dashboard/app.js
bash -n scripts/run_open_buy_auto.sh
python3 -m compileall -q src scripts
PYTHONPATH=src:. pytest -q tests/test_auto_open_buy_service.py tests/test_cli_auto_open_buy.py tests/test_auto_open_buy_script.py tests/test_dashboard_static.py tests/test_daily_report.py
PYTHONPATH=src:. pytest -q
git diff --check
```

Expected final behavior:
- The operator no longer manually checks pre-open boxes before paper buy.
- If a valid active plan and official open price exist, paper buy trade details are written exactly once.
- If not ready, the system says one clear reason, not ten panels of unrelated evidence.
- Dashboard first screen is understandable without knowing internal task history.

