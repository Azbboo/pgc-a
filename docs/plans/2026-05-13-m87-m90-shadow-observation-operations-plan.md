# M87-M90 Shadow Observation Operations Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move the shadow observation loop from single-day visibility into repeatable history, comparison, manual promotion review, and evidence validation without changing active strategy or trading state.

**Architecture:** Build read-only services on top of existing shadow snapshot, observation scorecard, promotion dossier, report artifacts, and strategy hypothesis records. New code may create review/evidence artifacts, API payloads, CLI summaries, and Dashboard views, but must not mutate active CPB params, strategy versions, trade plans, trades, positions, paper/live behavior, broker execution, or timers.

**Tech Stack:** Python services and CLI, FastAPI read-only endpoints, static Dashboard JavaScript/CSS, JSON/Markdown artifacts, SQLite read paths, pytest/unittest.

---

## Baseline

- M83-M86 added the scorecard contract, Dashboard observation queue, daily observation reports, and promotion dossiers.
- Promotion dossiers are review evidence only; all candidates remain blocked for paper/live and strategy-version mutation.
- The next gap is operational continuity: compare candidates across dates, inspect score drift, attach replay/backtest evidence, and prepare a manual review package without letting it become an approval path.

## Parallel Work Map

| Track | Task | Status | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- | --- |
| M87 | Shadow observation history index and API | Next | First | M83-M86 artifacts | Session A |
| M88 | Dashboard observation timeline and comparison UX | Next | After M87 contract | M87 history payload | Session B |
| M89 | Promotion review request package | Next | Parallel with M87/M90 | M86 dossiers | Session C |
| M90 | Replay/backtest evidence bridge for shadow candidates | Next | Parallel with M87/M89 | M86 dossier checks, M50 validation concepts | Session D |

## M87: Shadow Observation History Index And API

**Goal:** Provide one read-only history payload across scorecard and dossier artifacts so operators can see how each shadow candidate changes over time.

**Expected scope:**
- Load `reports/shadow_observation_scorecard_YYYYMMDD.*` and `reports/shadow_promotion_dossier_YYYYMMDD.*`.
- Normalize candidate history rows by `candidate_key`, date, rank, score, sample size, coverage state, blockers, frozen-CPB delta, and promotion review status.
- Expose a read-only API route, for example `/api/shadow-observation-history`.
- Add an ops CLI command, for example `ops shadow-observation-history --date 20260513 --window 20`.
- No DB writes and no trading/promotion mutations.

**Files:**
- Create or extend: `src/pgc_trading/services/shadow_observation_service.py`
- Modify: `src/pgc_trading/api/routes.py`
- Modify: `src/pgc_trading/api/services.py`
- Modify: `src/pgc_trading/ops.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `tests/test_shadow_observation_service.py`
- Modify: `tests/test_api_read_routes.py`
- Modify: `tests/test_ops.py`
- Modify: `tests/test_cli_main.py`

**Validation:**
- `PYTHONPATH=src:. pytest -q tests/test_shadow_observation_service.py tests/test_api_read_routes.py tests/test_ops.py tests/test_cli_main.py`
- `PYTHONPATH=src:. pytest -q`
- Payload must stay read-only and must preserve missing-artifact states as explicit blockers.

## M88: Dashboard Observation Timeline And Comparison UX

**Goal:** Make `影子实验室` usable for multi-day observation, not just today's ranked queue.

**Expected scope:**
- Add a date/window selector and candidate history strip inside the Shadow Lab.
- Show score trend, rank trend, coverage/blocker trend, and frozen-CPB delta trend.
- Add a comparison drawer for one candidate across dates.
- Keep controls read-only: no promote, trade, plan, timer, or strategy-version write actions.

**Files:**
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/styles.css`
- Modify: `tests/test_dashboard_static.py`
- Modify: `tests/test_api_read_routes.py`

**Validation:**
- `node --check web/dashboard/app.js`
- `PYTHONPATH=src:. pytest -q tests/test_dashboard_static.py tests/test_api_read_routes.py`
- UI must clearly state observation history is research-only and not paper trading.

## M89: Promotion Review Request Package

**Goal:** Convert a blocked or review-ready promotion dossier into a manual review package that is easy to audit, while still preventing strategy activation.

**Expected scope:**
- Generate `reports/shadow_promotion_review_request_YYYYMMDD.{json,md}` from the latest dossier.
- Include candidate readiness checks, unresolved blockers, required human decisions, required replay/backtest evidence, and rollback/safety notes.
- If no candidate is `review_ready`, generate a blocked review request explaining why no promotion review should proceed.
- Do not create or update `strategy_versions`; do not change CPB params or paper/live state.

**Files:**
- Modify: `src/pgc_trading/services/shadow_observation_service.py`
- Modify: `src/pgc_trading/services/strategy_evolution_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `reports/operational_runbook_design.md`
- Modify: `tests/test_shadow_observation_service.py`
- Modify: `tests/test_strategy_evolution_service.py`
- Modify: `tests/test_operational_runbook_static.py`

**Validation:**
- `PYTHONPATH=src:. pytest -q tests/test_shadow_observation_service.py tests/test_strategy_evolution_service.py tests/test_operational_runbook_static.py`
- `git diff --check`
- Generated request packages must remain evidence artifacts only.

## M90: Replay/Backtest Evidence Bridge For Shadow Candidates

**Goal:** Give shadow candidates a validated evidence path for clearing replay/backtest blockers without accepting fabricated or stale artifacts.

**Expected scope:**
- Define a provider-file style contract for shadow replay/backtest results.
- Validate candidate key, date range, sample size, source hash, no-future boundary, and metric completeness.
- Surface accepted/rejected evidence in scorecards and promotion dossiers.
- Keep all accepted evidence advisory; it must not change active strategy params or paper/live execution.

**Files:**
- Create or extend: `src/pgc_trading/services/shadow_observation_service.py`
- Modify: `src/pgc_trading/services/strategy_evolution_service.py`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `scripts/monitor_shadow_strategies.py`
- Modify: `tests/test_shadow_observation_service.py`
- Modify: `tests/test_strategy_evolution_service.py`
- Modify: `tests/test_daily_report.py`
- Modify: `tests/test_shadow_strategy_monitor_script.py`

**Validation:**
- `PYTHONPATH=src:. pytest -q tests/test_shadow_observation_service.py tests/test_strategy_evolution_service.py tests/test_daily_report.py tests/test_shadow_strategy_monitor_script.py`
- `PYTHONPATH=src:. pytest -q`
- Rejected evidence must keep `replay_backtest_result_artifact_required` or a more specific blocker visible.

## Parallelization Notes

- M87 should run first because it defines the history payload that M88 consumes.
- M89 and M90 can run in parallel with M87 after agreeing on dossier/evidence field names.
- M88 should wait for M87's API contract, but static layout work can start with fixture payloads.
- None of these tasks may promote a shadow strategy, publish a strategy version, write trade state, change paper/live behavior, or mutate timers.
