# M71-M74 Market Intelligence Operationalization Plan

**Goal:** Turn the M67-M70 foundation into a daily usable market-intelligence loop: reviewed evidence closes visible gaps, market-review empty states explain themselves, shadow research becomes gated artifacts, and cockpit decisions get next-day outcome review.

**Architecture:** Keep market intelligence advisory unless a later explicit task changes that contract. Evidence must enter through reviewed cached provider files or explicit unavailable states. Shadow strategy work may create artifacts and comparison reports, but must not mutate active strategy params, trade plans, trades, positions, paper/live behavior, broker execution, or timer state.

**Tech Stack:** Python services and CLI, SQLite through `013_decision_action_log`, FastAPI read/write-guarded APIs, static Dashboard JavaScript/CSS, Markdown/JSON reports, pytest/unittest, remote deployment on port `8020`.

---

## Baseline

- M67-M70 are completed and scheduled for release `pgc-v0.1.0-20260512-m67-m70`.
- Remote migration target is `013_decision_action_log`.
- 2026-05-11 market review has regime, sectors, plan context, and hypotheses, but market/Agent external evidence remains explicitly missing unless reviewed provider files are imported.
- M69 research is shadow-only and must stay separate from active CPB behavior until replay/paper gates are passed.

## Parallel Work Map

| Track | Task | Status | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- | --- |
| M71 | Evidence pack execution and 20260511 external coverage closure | Next | Yes | M68 evidence packs, reviewed provider files | Session A |
| M72 | Market review data sync and empty-state diagnostics | Next | Yes | M41B/M48 Dashboard, M65 ops history | Session B |
| M73 | Shadow strategy promotion workbench | Next | Yes | M69 shadow reports, M64/M50 gates | Session C |
| M74 | Decision action outcome review and ops audit hardening | Next | After M70 response shapes | Session D |

## M71: Evidence Pack Execution And 20260511 External Coverage Closure

**Goal:** Close 20260511 market/Agent evidence gaps with reviewed cached provider files or explicit unavailable-source records.

**Expected scope:**
- Use `ops evidence-pack` output as the controlled source for market and Agent external evidence.
- Import/backfill only reviewed provider files; do not live-fetch in daily-close, report rendering, API, or Dashboard paths.
- Re-render reports so coverage states show available, partial, missing, or unavailable accurately.
- Keep missing news/sentiment explicit when no reviewed evidence exists.

**Acceptance commands:**

```bash
PYTHONPATH=src:. pytest -q tests/test_market_external_data_service.py tests/test_agent_external_data_service.py tests/test_cli_market_review.py tests/test_daily_report.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** no fabricated external evidence, no trading writes, and Dashboard/report coverage wording remains honest.

## M72: Market Review Data Sync And Empty-State Diagnostics

**Goal:** Make the Dashboard explain why full-market panels are empty instead of leaving the operator guessing.

**Expected scope:**
- Add API/Dashboard diagnostics for selected market date, latest market-review date, API base, source DB freshness, and missing downstream tables.
- Add an ops check for local/remote market-review parity across `market_review_runs`, `sector_daily_snapshots`, `market_external_items`, `market_plan_contexts`, and `strategy_hypotheses`.
- Preserve read-only market-review UI.
- Keep latest-date navigation clear when localStorage pins an older date.

**Acceptance commands:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_api_read_routes.py tests/test_dashboard_static.py tests/test_operational_runbook_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** empty states identify root cause without hiding missing evidence or silently switching trading context.

## M73: Shadow Strategy Promotion Workbench

**Goal:** Convert M69 shadow research into a controlled workbench that can compare candidate ideas against frozen CPB.

**Expected scope:**
- Register M69 shadow outputs as artifact-only hypothesis candidates.
- Add replay/shadow comparison summaries for trend extension, breakout pressure, low-price momentum, pre-confirm watchlist, and dip-buy variants.
- Require explicit blockers before any paper observation or strategy-version proposal.
- Do not create or activate strategy params.

**Acceptance commands:**

```bash
PYTHONPATH=src:. pytest -q tests/test_strategy_evolution_service.py tests/test_strategy_hypothesis_backtest_service.py tests/test_daily_report.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** research artifacts only; no trade plans, no active params, no paper/live behavior mutation.

## M74: Decision Action Outcome Review And Ops Audit Hardening

**Goal:** Make M70 action logs useful during the next review day and visible in ops history.

**Expected scope:**
- Surface action-log outcome review in report/API/Dashboard with matched, deferred, pending, and unexpected-trade states.
- Link action logs into ops history and release/audit trails.
- Improve Dashboard controls for reviewing followed/deferred/overrode decisions without cluttering execution flow.
- Keep trade execution in existing guarded endpoints only.

**Acceptance commands:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_decision_action_log_service.py tests/test_api_read_routes.py tests/test_daily_report.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** action logs are advisory audit records and cannot place trades, enable timers, or mutate strategy state.

## Parallelization Notes

- M71, M72, and M73 can run in parallel.
- M74 can start in parallel if it only reads the M70 action-log shape; deeper integration should wait for any M72 ops-history shape changes.
- None of these tasks should enable the production timer or perform irreversible trading actions.
