# M91-M94 Shadow Promotion Evidence Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the M87-M90 observation/review scaffolding into a repeatable evidence loop: generate validated replay evidence, show review requests in the Dashboard, close daily artifact generation, and calibrate shadow thresholds without activating any strategy.

**Architecture:** Keep the shadow system as a research-only layer. New tasks may generate replay/backtest evidence artifacts, read-only API payloads, Dashboard views, daily pipeline/report sections, and calibration artifacts, but they must not mutate active CPB params, publish strategy versions, create trade plans, record trades, alter positions, change paper/live behavior, trigger broker execution, or mutate timers.

**Tech Stack:** Python services and CLI, SQLite read paths, static Dashboard JavaScript/CSS, FastAPI read-only endpoints, Markdown/JSON reports, pytest/unittest.

---

## Baseline

- M87-M90 added cross-date observation history, Dashboard timeline/comparison, manual promotion review-request artifacts, and replay/backtest evidence validation.
- Current production evidence state is still intentionally blocked: replay/backtest evidence is mostly `missing`, review requests report `no_review_ready_candidates`, and promotion remains manual-only.
- The next wave should produce real validated evidence and make the review loop visible without converting any shadow candidate into live/paper behavior.

## Parallel Work Map

| Track | Task | Status | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- | --- |
| M91 | Shadow replay/backtest evidence producer | Done, Deployed | First | M90 evidence contract, market bars, shadow monitor artifacts | Session A |
| M92 | Dashboard promotion review workbench | Done, Deployed | Parallel after M89/M90 | M89 review request, M90 evidence status | Session B |
| M93 | Daily pipeline shadow evidence closure | Done, Deployed | Parallel after M91 shape | M87 history, M89 review request, M91 evidence artifacts | Session C |
| M94 | Shadow threshold calibration sandbox | Done, Deployed | After M91 evidence or with fixtures | M91 evidence metrics, M87 history | Session D |

## M91: Shadow Replay/Backtest Evidence Producer

**Goal:** Generate validated `shadow_replay_backtest_evidence_v1` artifacts for each shadow candidate family using local market data and the M90 source-hash contract.

**Expected scope:**
- Add a service or script that reads existing shadow monitor/history artifacts and market bars.
- Produce one evidence artifact per candidate key with date range, sample size, metrics, no-future boundary, source hash, and safety flags.
- Run the existing M90 validator immediately after generation.
- Keep failures explicit: insufficient sample, stale date range, missing bars, source hash mismatch, and metric gaps must remain blockers.

**Files:**
- Modify or create: `src/pgc_trading/services/shadow_observation_service.py`
- Modify or create: `scripts/generate_shadow_replay_backtest_evidence.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `tests/test_shadow_observation_service.py`
- Create or modify: `tests/test_shadow_replay_backtest_evidence_script.py`

**Validation:**
- `PYTHONPATH=src:. pytest -q tests/test_shadow_observation_service.py tests/test_shadow_replay_backtest_evidence_script.py tests/test_cli_main.py`
- Generated artifacts must validate through `review_shadow_replay_backtest_evidence_artifact`.
- No strategy/trade/paper-live/timer tables may change.

**M91 completion note (2026-05-13):** Added the read-only replay/backtest evidence producer in `ShadowObservationService`, the `scripts/generate_shadow_replay_backtest_evidence.py` entrypoint, and the `strategy-evolution shadow-replay-backtest-evidence` CLI command. Generated `reports/shadow_replay_backtest_evidence_20260513_{candidate}.json` for all five candidates: trend extension, breakout pressure, and low-price momentum validate as `accepted`; preconfirm watchlist remains `rejected` for stale source evidence; pullback dip-buy remains `rejected` for stale source evidence plus missing T1 replay metrics. Verification passed with `PYTHONPATH=src:. pytest -q tests/test_shadow_observation_service.py tests/test_shadow_replay_backtest_evidence_script.py tests/test_cli_main.py`; no strategy/trade/paper-live/timer mutation was enabled.

**Codex release review note (2026-05-13):** Added direct-script `src` path bootstrapping for the shadow monitor, replay evidence generator, and threshold calibration scripts so child sessions can run `python3 scripts/...` without manually setting `PYTHONPATH`. Release verification passed with `node --check web/dashboard/app.js`, Python compile checks, focused M91-M94 pytest (`168 passed, 1 skipped, 1 subtests passed`), full `PYTHONPATH=src:. pytest -q` (`462 passed, 3 skipped, 10 subtests passed`), `git diff --check`, direct script dry-runs, and secret/path scans. Release tag: `pgc-v0.1.0-20260513-m91-m94-r1`.

## M92: Dashboard Promotion Review Workbench

**Goal:** Add a read-only Dashboard view for promotion review requests, replay evidence status, required human decisions, and safety notes.

**Expected scope:**
- Add a Dashboard panel inside Shadow Lab or Strategy Evolution that loads the latest `shadow_promotion_review_request_v1`.
- Show candidate readiness, replay evidence accepted/rejected/missing counts, required decisions, rollback notes, and release gate blockers.
- Add a detail drawer for one candidate's review package.
- Do not add approve/promote/trade/plan/timer buttons.

**Files:**
- Modify: `src/pgc_trading/api/routes.py`
- Modify: `src/pgc_trading/api/services.py`
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/styles.css`
- Modify: `tests/test_api_read_routes.py`
- Modify: `tests/test_dashboard_static.py`

**Validation:**
- `node --check web/dashboard/app.js`
- `PYTHONPATH=src:. pytest -q tests/test_api_read_routes.py tests/test_dashboard_static.py`
- Static tests must prove no review package UI control can mutate strategy/trading/timer state.

## M93: Daily Pipeline Shadow Evidence Closure

**Goal:** Make shadow evidence generation, review request refresh, and history indexing part of the daily operating loop with explicit artifact parity checks.

**Expected scope:**
- Extend daily pipeline/report logic to refresh or verify scorecard, dossier, review request, and replay evidence artifacts.
- Add compact CLI output for shadow evidence status and missing artifact blockers.
- Add remote/local parity diagnostics so the Dashboard does not silently show empty history.
- Keep the daily pipeline read-only for strategy and trading state.

**Files:**
- Modify: `src/pgc_trading/services/daily_pipeline_service.py`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `scripts/monitor_shadow_strategies.py`
- Modify: `tests/test_cli_daily_pipeline.py`
- Modify: `tests/test_daily_report.py`
- Modify: `tests/test_shadow_strategy_monitor_script.py`

**Validation:**
- `PYTHONPATH=src:. pytest -q tests/test_cli_daily_pipeline.py tests/test_daily_report.py tests/test_shadow_strategy_monitor_script.py tests/test_cli_main.py`
- Report JSON/Markdown must show evidence status without implying promotion approval.

## M94: Shadow Threshold Calibration Sandbox

**Goal:** Compare threshold variants for shadow candidate families and produce calibration artifacts that can inform future strategy work without changing active params.

**Expected scope:**
- Add a calibration artifact comparing current shadow buckets against candidate threshold variants.
- Include metrics by family: sample size, win rate, mean/median returns, drawdown proxy, frozen-CPB comparison, and evidence coverage.
- Produce recommended next experiments and rejected variants with reasons.
- Keep results artifact-only; do not edit CPB params or strategy versions.

**Files:**
- Modify or create: `src/pgc_trading/services/strategy_evolution_service.py`
- Modify or create: `scripts/calibrate_shadow_thresholds.py`
- Modify: `reports/operational_runbook_design.md`
- Modify: `tests/test_strategy_evolution_service.py`
- Modify or create: `tests/test_shadow_threshold_calibration_script.py`
- Modify: `tests/test_operational_runbook_static.py`

**Validation:**
- `PYTHONPATH=src:. pytest -q tests/test_strategy_evolution_service.py tests/test_shadow_threshold_calibration_script.py tests/test_operational_runbook_static.py`
- Calibration output must state `artifact_only=true`, `promotion_allowed=false`, and `active_params_mutated=false`.

## Parallelization Notes

- M91 should run first if possible because it produces the evidence artifacts M92-M94 can consume.
- M92 can start immediately using current M89/M90 review-request fixtures, then wire in M91 evidence status when available.
- M93 can start with artifact parity and report plumbing, then add M91 generated evidence once the producer is stable.
- M94 should use fixture evidence until M91 lands, then switch to generated evidence for final verification.
- None of these tasks may promote a strategy, publish a strategy version, write trade state, change paper/live behavior, or mutate timers.
