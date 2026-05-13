# M79-M82 Shadow Strategy Visibility Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Surface shadow strategy candidates, monitor progress, and promotion blockers in read-only Dashboard, report, API, and CLI views so operators can inspect shadow research without turning it into active strategy.

**Architecture:** Keep the current shadow monitor and preflight artifacts as the source of truth. Normalize latest monitor/preflight snapshots plus `strategy_hypotheses` shadow rows into a read-only visibility layer. The visibility layer may summarize walk-forward progress, blockers, frozen-CPB comparison, and top candidates, but it must not mutate active strategy params, trade plans, trades, positions, paper/live behavior, broker execution, or timers.

**Tech Stack:** Python services and CLI, SQLite read paths, FastAPI read-only endpoints, static Dashboard JavaScript/CSS, Markdown/JSON reports, pytest/unittest.

---

## Baseline

- M78 already produces artifact-only shadow monitor and promotion-preflight outputs.
- Shadow candidates already exist as artifact-only hypothesis rows with gate/blocker metadata.
- The current Dashboard/report surfaces do not yet make shadow research a first-class operator view.
- This work is purely visibility and audit. Promotion remains blocked until a later task explicitly clears evidence gates.

## Parallel Work Map

| Track | Task | Status | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- | --- |
| M79 | Shadow snapshot feed and API contract | Done, Deployed | Yes | M78 monitor/preflight artifacts, M73 shadow hypothesis shape | Session A |
| M80 | Dashboard shadow lab view | Done, Deployed | After M79 contract | M79 normalized snapshot | Session B |
| M81 | Daily report and CLI shadow summary | Done, Deployed | Yes, after M79 | M79 snapshot feed | Session C |
| M82 | Guardrails, tests, and release gate | Done, Deployed | After M79-M81 | M79-M81 shapes | Session D |

## M79: Shadow Snapshot Feed And API Contract

**Goal:** Build a single read-only snapshot API that unifies the latest shadow monitor, promotion preflight, walk-forward progress, and candidate detail.

**Expected scope:**
- Add a shadow visibility service that reads the latest monitor/preflight artifacts and the shadow hypothesis rows.
- Normalize candidate families, blocker counts, walk-forward state, frozen-CPB comparison, and artifact paths into one payload.
- Expose a read-only API surface for the Dashboard and report layers.
- Keep all writes out of scope.

**Files:**
- Create: `src/pgc_trading/services/shadow_strategy_service.py`
- Modify: `src/pgc_trading/api/routes.py`
- Modify: `src/pgc_trading/api/services.py`
- Modify: `src/pgc_trading/ops.py`
- Create: `tests/test_shadow_strategy_service.py`
- Modify: `tests/test_api_read_routes.py`
- Modify: `tests/test_ops.py`

**Steps:**
1. Write a failing test for a `shadow-strategy snapshot` service call that returns the latest monitor/preflight summary.
   Expected: the service does not exist yet, so the test fails.
2. Implement the minimal snapshot loader and normalization logic.
   Expected: the payload includes latest dates, candidate counts, blocker counts, top buckets, and source artifact paths.
3. Wire the snapshot into one read-only API route and one CLI read command.
   Expected: both show the same normalized snapshot, and neither can mutate strategy state.
4. Run the focused tests and a syntax check.
   Run:
   ```bash
   PYTHONPATH=src:. pytest -q tests/test_shadow_strategy_service.py tests/test_api_read_routes.py tests/test_ops.py
   PYTHONPATH=src:. pytest -q
   ```
   Expected: pass.

**Validation:**
- The snapshot must label shadow items as artifact-only.
- The snapshot must clearly report active CPB integrity as unchanged.

## M80: Dashboard Shadow Lab View

**Goal:** Make shadow strategy visible in the Dashboard as a dedicated read-only lab view with candidate drill-down.

**Expected scope:**
- Add a Dashboard tab or panel for the shadow snapshot.
- Show candidate families, walk-forward completion, blocker counts, frozen-CPB comparison, and latest top candidates.
- Add a detail drawer for one selected shadow candidate with comparison metrics and artifact links.
- Preserve the existing read-only dashboard contract.

**Files:**
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/styles.css`
- Modify: `tests/test_dashboard_static.py`
- Modify: `tests/test_api_read_routes.py`

**Steps:**
1. Write failing tests that expect a shadow tab and a candidate detail panel in the Dashboard payload.
   Expected: the UI does not render them yet, so the tests fail.
2. Implement the smallest read-only UI surface for the shadow snapshot.
   Expected: the tab shows summary state and opens a detail drawer from the normalized snapshot.
3. Run the static check and focused tests.
   Run:
   ```bash
   node --check web/dashboard/app.js
   PYTHONPATH=src:. pytest -q tests/test_dashboard_static.py tests/test_api_read_routes.py
   ```
   Expected: pass.

**Validation:**
- The UI must clearly label shadow strategy as research-only.
- The UI must not expose any action that changes active strategy, trades, or timers.

## M81: Daily Report And CLI Shadow Summary

**Goal:** Put shadow strategy status into the daily report and a small CLI summary so operators can see it without opening the Dashboard.

**Expected scope:**
- Add a shadow strategy block to the daily review markdown/JSON.
- Surface latest monitor/preflight dates, candidate counts, blocker counts, and top candidates.
- Add a CLI command or subcommand that prints the current shadow snapshot in compact form.
- Keep the summary read-only and artifact-only.

**Files:**
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `reports/daily_review_*.md`
- Modify: `reports/daily_review_*.json`
- Modify: `tests/test_daily_report.py`
- Modify: `tests/test_cli_main.py`

**Steps:**
1. Write a failing daily-report test that expects a shadow section with blocker and candidate summaries.
   Expected: the report lacks the section, so the test fails.
2. Implement the report and CLI summary plumbing.
   Expected: the report and CLI both point to the same normalized snapshot feed.
3. Run the focused tests and the full suite if the first pass is green.
   Run:
   ```bash
   PYTHONPATH=src:. pytest -q tests/test_daily_report.py tests/test_cli_main.py
   PYTHONPATH=src:. pytest -q
   ```
   Expected: pass.

**Validation:**
- The daily report must not convert shadow candidates into active daily picks.
- The CLI must not imply that a blocked promotion preflight is ready for trading.

## M82: Guardrails, Tests, And Release Gate

**Goal:** Prove the visibility layer stays read-only and does not leak into active CPB, trade, or timer behavior.

**Expected scope:**
- Add regression coverage for no active strategy mutation and no trade/timer writes.
- Ensure the monitor/preflight outputs and dashboard/report snapshots stay artifact-only.
- Update the operational runbook or tests if the new shadow tab needs operator guidance.
- Keep the release gate explicit about what is displayed and what remains blocked.

**Files:**
- Modify: `src/pgc_trading/services/strategy_evolution_service.py`
- Modify: `src/pgc_trading/services/strategy_hypothesis_backtest_service.py`
- Modify: `scripts/monitor_shadow_strategies.py`
- Modify: `tests/test_strategy_evolution_service.py`
- Modify: `tests/test_strategy_hypothesis_backtest_service.py`
- Modify: `tests/test_operational_runbook_static.py`
- Modify: `tests/test_shadow_strategy_service.py`

**Steps:**
1. Write regression tests that the shadow visibility flow does not mutate active CPB params/hash or timer state.
   Expected: the tests fail until the guardrails are wired.
2. Tighten the service and artifact checks until those regressions pass.
   Expected: visibility artifacts remain read-only and artifact-only.
3. Run the focused tests, then the full suite, then `git diff --check`.
   Run:
   ```bash
   PYTHONPATH=src:. pytest -q tests/test_strategy_evolution_service.py tests/test_strategy_hypothesis_backtest_service.py tests/test_shadow_strategy_service.py tests/test_operational_runbook_static.py
   PYTHONPATH=src:. pytest -q
   git diff --check
   ```
   Expected: pass.

**Validation:**
- Active CPB params/hash must remain unchanged.
- No trade plans, trades, positions, paper/live behavior, or timer paths may be written.

**M82 completion note:** Added mutation-risk rejection to the shadow snapshot loader, read-only/release-gate metadata to shadow monitor/preflight artifacts, and regression coverage across strategy evolution, backtest request artifacts, shadow snapshots, monitor outputs, and the operational runbook. Also isolated ops-history log-dir tests so local `.pgc-runs` evidence cannot hide synthetic operation rows. Verification: focused M82 pytest `45 passed`; full `PYTHONPATH=src:. pytest -q` (`430 passed, 3 skipped, 10 subtests passed`); `git diff --check`.

## Parallelization Notes

- M79 should happen first because it defines the shared snapshot contract.
- M80 and M81 can run in parallel once M79 exists.
- M82 should start after M79-M81 are stable, or in parallel only if it is limited to read-only regression tests.
- None of these tasks should promote shadow candidates into active strategy behavior.
