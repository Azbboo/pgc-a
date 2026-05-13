# M83-M86 Shadow Observation Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the visible shadow strategy lab into an auditable observation loop: score shadow candidates, show why they deserve observation, track daily outcomes, and prepare promotion dossiers without changing active strategy or trading state.

**Architecture:** Build a read-only shadow observation layer on top of existing `shadow_strategy_snapshot_v1`, monitor/preflight artifacts, market bars, and strategy hypotheses. The layer may generate scorecards, observation queues, report sections, and promotion dossier artifacts, but it must not mutate active CPB parameters, strategy versions, trade plans, trades, positions, paper/live behavior, broker execution, or timers.

**Tech Stack:** Python services and CLI, SQLite read paths, FastAPI read-only endpoints, static Dashboard JavaScript/CSS, Markdown/JSON reports, pytest/unittest.

---

## Baseline

- M79-M82 make shadow candidates visible through a read-only snapshot API, Dashboard Shadow Lab, daily report section, and guardrail tests.
- Shadow candidates remain `artifact-only`; promotion preflight remains blocked by default.
- Operators can inspect candidates, but cannot yet see a ranked observation scorecard, daily observation queue, or promotion dossier.
- This wave is still research/observation only. No task in this plan may place trades, alter paper/live behavior, or publish active strategy versions.

## Parallel Work Map

| Track | Task | Status | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- | --- |
| M83 | Shadow observation scorecard service and API | Done, Deployed | First | M79 snapshot, M78 monitor artifacts, market bars | Session A |
| M84 | Dashboard observation queue and attribution view | Done, Deployed | After M83 contract | M83 scorecard payload | Session B |
| M85 | Daily report, CLI, and pipeline observation artifacts | Done, Deployed | After M83 contract | M83 scorecard payload, M81 report plumbing | Session C |
| M86 | Promotion dossier, guardrails, and release gate | Done, Deployed | After M83-M85 shapes | M83-M85 outputs, M82 guardrails | Session D |

## M83: Shadow Observation Scorecard Service And API

**Goal:** Produce one normalized read-only scorecard that ranks shadow candidates by observed outcomes, coverage, blockers, and comparison versus frozen CPB.

**Expected scope:**
- Add a service that reads the latest shadow snapshot, monitor/preflight artifacts, `strategy_hypotheses`, and market bars.
- Compute candidate-level scorecard rows: sample size, T+1/T+2/T+5 outcome metrics, drawdown proxy, hit rates, coverage status, blocker count, and frozen-CPB delta.
- Expose a read-only API route and ops CLI command.
- Keep all writes out of scope; if source data is missing, return explicit `missing` or `insufficient_sample` states.

**Files:**
- Create: `src/pgc_trading/services/shadow_observation_service.py`
- Modify: `src/pgc_trading/api/routes.py`
- Modify: `src/pgc_trading/api/services.py`
- Modify: `src/pgc_trading/ops.py`
- Modify: `src/pgc_trading/cli/main.py`
- Create: `tests/test_shadow_observation_service.py`
- Modify: `tests/test_api_read_routes.py`
- Modify: `tests/test_ops.py`
- Modify: `tests/test_cli_main.py`

**Steps:**
1. Write a failing service test that seeds monitor/preflight artifacts plus market bars and expects a `shadow_observation_scorecard_v1` payload.
   Expected: the service does not exist yet, so the test fails.
2. Implement the minimal scorecard loader and normalizer.
   Expected: rows include `candidate_key`, `candidate_family`, `observation_status`, `sample_size`, outcome metrics, blocker count, and source artifact paths.
3. Add the read-only API route, for example `/api/shadow-observation-scorecard`.
   Expected: GET returns the same scorecard payload and uses `RequestContext(dry_run=True, source="api")`.
4. Add an ops CLI command, for example `ops shadow-observation`.
   Expected: compact output shows scorecard status, top candidates, coverage states, and no mutation flags.
5. Run:
   ```bash
   PYTHONPATH=src:. pytest -q tests/test_shadow_observation_service.py tests/test_api_read_routes.py tests/test_ops.py tests/test_cli_main.py
   PYTHONPATH=src:. pytest -q
   ```
   Expected: pass.

**Validation:**
- The scorecard must be read-only and artifact-only.
- Missing bars or too-small samples must block promotion readiness instead of being treated as success.

## M84: Dashboard Observation Queue And Attribution View

**Goal:** Extend the Dashboard Shadow Lab with a clear observation queue and attribution drawer so operators can see which shadow ideas are promising and why.

**Expected scope:**
- Add a read-only observation queue panel inside `影子实验室`.
- Show top shadow candidates, outcome score, sample coverage, blocker count, frozen-CPB delta, and evidence/market-data gaps.
- Add a candidate attribution drawer: observed days, best/worst outcomes, why it ranks where it ranks, and why promotion remains blocked.
- Do not add promote, trade, plan, or timer buttons.

**Files:**
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/styles.css`
- Modify: `tests/test_dashboard_static.py`
- Modify: `tests/test_api_read_routes.py`

**Steps:**
1. Write a failing static test that expects the observation queue panel, scorecard API path, attribution drawer text, and no POST calls.
   Expected: the Dashboard does not render these yet, so the test fails.
2. Implement the smallest UI over the M83 scorecard contract.
   Expected: the Shadow Lab renders queue cards and opens a read-only detail drawer.
3. Run:
   ```bash
   node --check web/dashboard/app.js
   PYTHONPATH=src:. pytest -q tests/test_dashboard_static.py tests/test_api_read_routes.py
   ```
   Expected: pass.

**Validation:**
- The UI must state that observation is not paper trading.
- No UI control may create a trade plan, record a trade, approve a strategy version, or mutate timers.

## M85: Daily Report, CLI, And Pipeline Observation Artifacts

**Goal:** Make shadow observation part of the daily operating loop through report sections, compact CLI output, and generated artifacts.

**Expected scope:**
- Add a `shadow_observation` section to daily review JSON/Markdown.
- Add compact CLI output for top candidates, coverage blockers, and observation status.
- Optionally generate `reports/shadow_observation_scorecard_YYYYMMDD.{json,md}` from the existing monitor script or ops command.
- Keep daily pipeline integration read-only unless a later task explicitly authorizes writing observation artifacts.

**Files:**
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `scripts/monitor_shadow_strategies.py`
- Modify: `tests/test_daily_report.py`
- Modify: `tests/test_cli_main.py`
- Modify: `tests/test_shadow_strategy_monitor_script.py`
- Modify: `reports/daily_review_*.md`
- Modify: `reports/daily_review_*.json`

**Steps:**
1. Write a failing report test that expects `shadow_observation` with top candidate rows and explicit blockers.
   Expected: the daily report lacks the section, so the test fails.
2. Add report serialization and Markdown lines from the M83 scorecard service.
   Expected: unavailable or missing-scorecard states render as explicit blockers.
3. Add compact CLI/report artifact output.
   Expected: operators can read the daily observation status without opening the Dashboard.
4. Run:
   ```bash
   PYTHONPATH=src:. pytest -q tests/test_daily_report.py tests/test_cli_main.py tests/test_shadow_strategy_monitor_script.py
   PYTHONPATH=src:. pytest -q
   ```
   Expected: pass.

**Validation:**
- Daily reports must not convert observed shadow candidates into active daily picks.
- Observation artifacts must be source-referenced and date-scoped.

## M86: Promotion Dossier, Guardrails, And Release Gate

**Goal:** Prepare a formal promotion-review dossier for candidates that pass observation thresholds while keeping actual promotion blocked behind manual approval and future implementation.

**Expected scope:**
- Define threshold metadata for promotion review readiness: minimum sample, positive frozen-CPB delta, evidence coverage, drawdown cap, and blocker clearance.
- Generate a dossier artifact for candidates that are `review_ready`; generate blocked reasons for everyone else.
- Add regression tests proving dossier generation cannot mutate active CPB params, strategy versions, trade plans, trades, positions, paper/live behavior, broker execution, or timers.
- Update runbook and release gate wording for the new observation loop.

**Files:**
- Modify: `src/pgc_trading/services/shadow_observation_service.py`
- Modify: `src/pgc_trading/services/strategy_evolution_service.py`
- Modify: `scripts/monitor_shadow_strategies.py`
- Modify: `reports/operational_runbook_design.md`
- Modify: `tests/test_shadow_observation_service.py`
- Modify: `tests/test_strategy_evolution_service.py`
- Modify: `tests/test_operational_runbook_static.py`

**Steps:**
1. Write failing guardrail tests for no active strategy/trade/timer mutation while generating dossiers.
   Expected: tests fail until dossier and safety metadata exist.
2. Implement dossier metadata and blocked/readiness states.
   Expected: ready candidates produce review artifacts only; blocked candidates explain exact blockers.
3. Tighten runbook release-gate text.
   Expected: operators see that promotion dossier is evidence for a later manual strategy-version task, not an approval.
4. Run:
   ```bash
   PYTHONPATH=src:. pytest -q tests/test_shadow_observation_service.py tests/test_strategy_evolution_service.py tests/test_operational_runbook_static.py
   PYTHONPATH=src:. pytest -q
   git diff --check
   ```
   Expected: pass.

**Validation:**
- Active CPB params/hash must remain unchanged.
- Dossier generation must never write trade plans, trades, positions, paper/live behavior, broker state, or timer state.

## Parallelization Notes

- M83 should happen first because it defines the scorecard contract.
- M84 and M85 can run in parallel once M83 exists.
- M86 should start after M83-M85 are stable, or in parallel only for guardrail tests and runbook wording.
- None of these tasks should promote shadow candidates into active strategy behavior.
