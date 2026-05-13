# Stock/InStock External Integration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Evaluate and, if justified, integrate `myhhub/stock` as an external research engine for indicators, screening, and backtest artifacts without importing its trading or UI stack.

**Architecture:** Keep PGC as the source of truth. Treat the upstream project as an external research provider whose outputs are normalized into our existing evidence, market-review, and strategy-evolution surfaces. Do not couple our SQLite schema to the upstream MySQL schema, and do not adopt its auto-trading path, web app, or scheduler.

**Tech Stack:** Python, existing PGC CLI/service/report stack, JSON/CSV artifact exchange, pytest/unittest, optional isolated upstream clone or container for inspection.

---

## Baseline

- Upstream `myhhub/stock` is a full InStock system with data ingestion, indicators, screening, backtesting, and auto-trading/UI capabilities.
- Our system already has market review, external evidence packs, strategy evolution, and dashboard/report surfaces.
- The only integration that makes sense here is a thin research bridge that feeds our existing advisory and reporting pipeline.
- If the upstream project duplicates what we already have, the plan should stop at an assessment memo and not proceed into code integration.

## Parallel Work Map

| Track | Task | Status | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- | --- |
| S1 | Capability matrix and integration boundary decision | Next | Yes | Upstream README, requirements, entrypoints | Session A |
| S2 | Artifact bridge PoC for one research output | Next | After S1 boundary | S1 decision, sample export format | Session B |
| S3 | Read-only report and Dashboard surface for imported research | Next | Yes, after S1 | S2 normalized artifact schema | Session C |
| S4 | Go/no-go gate and rollout note | Next | Yes | S1-S3 results | Session D |

## S1: Capability Matrix And Integration Boundary Decision

**Goal:** Decide whether the upstream project adds unique value beyond our current market review/evidence/strategy stack.

**Expected scope:**
- Inspect upstream README, requirements, package layout, and executable entrypoints.
- Build a matrix for: indicators, stock screeners, backtests, auto-trading, web UI, storage layer, and scheduling.
- Compare each capability against our existing services and note overlap, unique value, and risk.
- Output a written go/no-go recommendation before any code integration.

**Files:**
- Create: `reports/stock_instock_integration_assessment.md`
- Create: `reports/stock_instock_integration_assessment.json`
- Modify: `docs/plans/global-task-ledger.md`

**Steps:**
1. Clone the upstream repo into an isolated temp workspace and inspect `README.md`, `requirements.txt`, and package entrypoints.
   Run:
   ```bash
   git clone https://github.com/myhhub/stock /tmp/stock-upstream
   sed -n '1,220p' /tmp/stock-upstream/README.md
   sed -n '1,220p' /tmp/stock-upstream/requirements.txt
   find /tmp/stock-upstream -maxdepth 2 -type f | sort | sed -n '1,200p'
   ```
   Expected: a short inventory of upstream capabilities and the top-level modules to consider.
2. Write the capability matrix and recommendation into the assessment report.
   Expected: one clear recommendation, one explicit no-go condition, and one preferred integration mode.
3. Review the recommendation against our current surfaces: `market_review`, `evidence_provider_pack`, `strategy_evolution`, and `daily_report`.
   Expected: a clear decision boundary that says whether the upstream project adds net-new value.

**Validation:**
- The report must explicitly mark `auto-trading`, `web UI`, and `upstream DB coupling` as out of scope unless a later task changes that.
- The recommendation must be readable by another engineer without context.

## S2: Artifact Bridge PoC For One Research Output

**Goal:** Prove the upstream project can feed one normalized research artifact into PGC without touching trading state.

**Expected scope:**
- Build a thin adapter that ingests one upstream export format, normalizes it, and writes a PGC research artifact.
- Start with one narrow use case: indicator summary or screening/backtest result export.
- Keep the adapter file-based and offline; do not connect to upstream trading or scheduling.

**Files:**
- Create: `src/pgc_trading/integration/stock_bridge.py`
- Create: `scripts/sync_stock_research.py`
- Create: `tests/test_stock_bridge.py`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `src/pgc_trading/services/market_review_service.py`

**Steps:**
1. Write a failing test that loads one fixture export and asserts the normalized artifact shape.
   Expected: the bridge does not exist yet, so the test fails.
2. Implement the minimal parser/normalizer for the chosen export.
   Expected: the adapter returns a stable JSON structure with source metadata, date, and evidence refs.
3. Run the focused test and a syntax check.
   Run:
   ```bash
   PYTHONPATH=src:. pytest -q tests/test_stock_bridge.py
   python3 -m py_compile src/pgc_trading/integration/stock_bridge.py scripts/sync_stock_research.py
   ```
   Expected: pass.
4. Write one report artifact showing the imported upstream research as read-only evidence.
   Expected: no trade plans, positions, or timer state change.

**Validation:**
- The PoC must not write to the upstream database.
- The PoC must not call any auto-trading path.
- The bridge output must be explicit about source provenance and freshness.

## S3: Read-Only Report And Dashboard Surface

**Goal:** Make imported upstream research visible in our existing operational surfaces without making it a trading authority.

**Expected scope:**
- Surface the imported artifact in daily report coverage and market-review detail views.
- Show whether the imported research is fresh, stale, missing, or unavailable.
- Keep the Dashboard read-only and avoid any control that could mutate active strategy behavior.

**Files:**
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `src/pgc_trading/services/market_review_service.py`
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/styles.css`
- Create/Modify: `tests/test_daily_report.py`
- Create/Modify: `tests/test_api_read_routes.py`
- Create/Modify: `tests/test_dashboard_static.py`

**Steps:**
1. Write failing tests for one imported research artifact appearing in report/API/Dashboard.
   Expected: no upstream surface yet, so the tests fail.
2. Implement the minimal read-only payload plumbing.
   Expected: the artifact appears as evidence, not as an execution instruction.
3. Run the focused tests and browser-free static checks.
   Run:
   ```bash
   node --check web/dashboard/app.js
   PYTHONPATH=src:. pytest -q tests/test_daily_report.py tests/test_api_read_routes.py tests/test_dashboard_static.py
   ```
   Expected: pass.

**Validation:**
- The UI must still show explicit missing-data states if the imported artifact is absent.
- Nothing in this step may create or mutate trades, positions, or strategy params.

## S4: Go/No-Go Gate And Rollout Note

**Goal:** Decide whether the integration should stay as an external research bridge or stop at the assessment layer.

**Expected scope:**
- Compare the bridge’s value against existing PGC evidence and strategy surfaces.
- Confirm whether the integration adds net-new signal quality, better coverage, or better operator ergonomics.
- Record a clear rollout note or no-go note.

**Files:**
- Modify: `docs/plans/global-task-ledger.md`
- Create: `reports/stock_instock_integration_decision.md`

**Steps:**
1. Review the S1-S3 outputs and write the go/no-go decision.
   Expected: one sentence recommendation, one sentence rationale, one explicit out-of-scope list.
2. If go, add the integration to the ledger as the next tracked workstream.
   Expected: the follow-up sessions can pick up without re-discovering the boundary.
3. If no-go, stop at research-only notes and keep the upstream project external.
   Expected: no code path is added beyond the assessment artifacts.

**Validation:**
- The final decision must preserve the rule that upstream auto-trading stays out of scope.
- The decision must be legible to a future session opening only the ledger and this plan.

## Parallelization Notes

- S1 should run first and can block the rest if it returns a no-go.
- S2 and S3 can run in parallel once the artifact schema is fixed.
- S4 should wait for S1-S3 unless the result is an immediate no-go.
- None of these tasks should introduce direct upstream DB coupling or auto-trading.
