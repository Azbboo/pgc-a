# M95-M98 Shadow Evidence To Decision Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the M91-M94 shadow evidence package into a repeatable decision loop: close stale evidence, accumulate daily outcomes, register next experiments, and present a Chinese manual decision memo without activating any strategy.

**Architecture:** Keep the whole wave artifact-only and review-only. M95 repairs rejected source evidence, M96 appends walk-forward outcomes after each closed trading day, M97 turns calibration recommendations into explicit experiment registry artifacts, and M98 surfaces a Chinese decision memo in API/Dashboard/report. None of these tasks may mutate active CPB params, publish strategy versions, create trade plans, record trades, alter positions, change paper/live behavior, trigger broker execution, or mutate timers.

**Tech Stack:** Python services and CLI, SQLite read paths, local JSON/Markdown reports, static Dashboard JavaScript/CSS, FastAPI read-only endpoints, pytest/unittest.

---

## Baseline

- M91 generated `shadow_replay_backtest_evidence_v1` artifacts for five shadow candidates.
- Three candidates are accepted: `trend_extension_shadow`, `breakout_pressure_shadow`, `low_price_momentum_shadow`.
- Two candidates remain rejected:
  - `preconfirm_watchlist`: stale source evidence.
  - `pullback_dip_buy`: stale source evidence plus missing T1 metrics.
- M94 calibration is intentionally artifact-only and recommends next experiments, but does not create an active strategy version.

## Parallel Work Map

| Lane | Task | Status | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- | --- |
| A | M95 Rejected evidence source closure | Next | First or parallel with fixtures | M91 evidence contract, source research artifacts | Session A |
| B | M96 Shadow walk-forward outcome accumulator | Done, Local | Parallel | M87 history, M91 evidence shape, market bars | Session B |
| C | M97 Shadow experiment registry | Next | Parallel after M94, can use fixtures while M95 runs | M94 calibration artifact | Session C |
| D | M98 Chinese shadow decision memo workbench | Done, Local | Parallel after M92, can use current blocked package | M92 review workbench, M94 calibration | Session D |

## M95: Rejected Evidence Source Closure

**Goal:** Refresh the stale preconfirm and dip-buy source artifacts so replay/backtest evidence is current, metric-complete, and still no-future validated.

**Expected scope:**
- Refresh or rebuild the source artifacts behind `preconfirm_watchlist` and `pullback_dip_buy`.
- Add missing T1 metrics for pullback dip-buy evidence if source data supports it.
- Keep stale or incomplete states explicit if the data still cannot support acceptance.
- Regenerate M91 replay/backtest evidence for all five candidates and preserve source-hash validation.
- Do not loosen validation thresholds just to pass evidence.

**Files:**
- Modify: `scripts/backtest_preconfirm_watchlist.py`
- Modify: `scripts/analyze_pgc_pullback_dip_buy.py`
- Modify: `src/pgc_trading/services/shadow_observation_service.py`
- Modify or regenerate: `reports/preconfirm_watchlist_backtest.json`
- Modify or regenerate: `reports/pgc_pullback_dip_buy.json`
- Modify or regenerate: `reports/shadow_replay_backtest_evidence_20260513_*.json`
- Modify: `tests/test_shadow_observation_service.py`
- Modify: `tests/test_shadow_replay_backtest_evidence_script.py`

**Validation:**
- `python3 scripts/generate_shadow_replay_backtest_evidence.py --date 20260513 --reports-dir reports --output-dir reports --compact`
- `PYTHONPATH=src:. pytest -q tests/test_shadow_observation_service.py tests/test_shadow_replay_backtest_evidence_script.py`
- Evidence artifacts must still report `promotion_allowed=false`, `artifact_only=true`, and no trade/position/strategy/timer mutation.

## M96: Shadow Walk-Forward Outcome Accumulator

**Goal:** Add a daily post-close artifact that appends actual T+1/T+5 outcomes for shadow candidates, so evidence grows naturally instead of staying as one-off replay files.

**Expected scope:**
- Create a date-scoped `shadow_walk_forward_outcomes_v1` artifact from candidate signals and `market_bars`.
- Include outcome availability, partial horizon, missing bars, no-future boundary, and per-candidate metrics.
- Add the outcome artifact to monitor output, daily pipeline summaries, and daily report JSON/Markdown.
- Keep it read-only; outcome accumulation must not create paper trades or strategy versions.

**Files:**
- Modify: `src/pgc_trading/services/shadow_observation_service.py`
- Modify: `scripts/monitor_shadow_strategies.py`
- Modify: `src/pgc_trading/services/daily_pipeline_service.py`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Create or regenerate: `reports/shadow_walk_forward_outcomes_20260513.json`
- Modify: `tests/test_shadow_observation_service.py`
- Modify: `tests/test_shadow_strategy_monitor_script.py`
- Modify: `tests/test_cli_daily_pipeline.py`
- Modify: `tests/test_daily_report.py`

**Validation:**
- `python3 scripts/monitor_shadow_strategies.py --date 20260513 --reports-dir reports --compact`
- `PYTHONPATH=src:. pytest -q tests/test_shadow_observation_service.py tests/test_shadow_strategy_monitor_script.py tests/test_cli_daily_pipeline.py tests/test_daily_report.py`
- Full-suite regression before handoff.

## M97: Shadow Experiment Registry

**Goal:** Convert M94 calibration recommendations into a structured experiment registry that records what to test next, why, required evidence, stop conditions, and manual approval boundaries.

**Expected scope:**
- Add `shadow_strategy_experiment_registry_v1` JSON/Markdown artifacts.
- Link each experiment to calibration variant, candidate family, replay evidence status, sample requirements, frozen-CPB comparison, and rollback/stop rules.
- Add review functions that reject artifacts if they imply active promotion, strategy-version publication, or trade-state writes.
- Keep registry advisory: no writes to `strategy_versions`, `trade_plans`, `trades`, or `positions`.

**Files:**
- Modify: `src/pgc_trading/services/strategy_evolution_service.py`
- Create or modify: `scripts/build_shadow_experiment_registry.py`
- Create or regenerate: `reports/shadow_strategy_experiment_registry_20260513.json`
- Create or regenerate: `reports/shadow_strategy_experiment_registry_20260513.md`
- Modify: `reports/operational_runbook_design.md`
- Modify: `tests/test_strategy_evolution_service.py`
- Create: `tests/test_shadow_experiment_registry_script.py`
- Modify: `tests/test_operational_runbook_static.py`

**Validation:**
- `python3 scripts/build_shadow_experiment_registry.py --date 20260513 --reports-dir reports --compact`
- `PYTHONPATH=src:. pytest -q tests/test_strategy_evolution_service.py tests/test_shadow_experiment_registry_script.py tests/test_operational_runbook_static.py`
- Registry safety fields must include `artifact_only=true`, `promotion_allowed=false`, `active_params_mutated=false`, `writes_trade_state=false`, and `timer_mutated=false`.

## M98: Chinese Shadow Decision Memo Workbench

**Codex completion note (2026-05-13):** Added read-only `shadow_decision_memo_v1` through `/api/shadow-decision-memo`, Shadow Lab 中文决策备忘录, and daily report JSON/Markdown. The memo links promotion review request, replay evidence, walk-forward outcomes, M94 calibration, and the experiment registry, with Chinese operator sections for 候选概览、证据状态、阻断原因、下一步实验、人工决策、风险/回滚边界. Verification passed: `node --check web/dashboard/app.js`, Python compile for touched modules, focused M98 pytest (`67 passed, 1 skipped`), full `PYTHONPATH=src:. pytest -q` (`471 passed, 3 skipped, 10 subtests passed`), `git diff --check`, and direct service smoke for `20260513`. No approve/promote/trade/plan/timer controls were added.

**Goal:** Present a Chinese, operator-readable manual decision memo that ties together promotion review request, replay evidence, walk-forward outcomes, calibration, and experiment registry.

**Expected scope:**
- Add read-only API payload for a `shadow_decision_memo_v1`.
- Add Dashboard panel/drawer inside Shadow Lab with Chinese sections: 候选概览、证据状态、阻断原因、下一步实验、人工决策、风险/回滚边界.
- Add daily report Markdown/JSON memo summary.
- Do not add approval, promotion, trade, plan, or timer buttons.

**Files:**
- Modify: `src/pgc_trading/api/routes.py`
- Modify: `src/pgc_trading/api/services.py`
- Modify: `src/pgc_trading/services/shadow_observation_service.py`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/styles.css`
- Modify: `tests/test_api_read_routes.py`
- Modify: `tests/test_dashboard_static.py`
- Modify: `tests/test_daily_report.py`

**Validation:**
- `node --check web/dashboard/app.js`
- `PYTHONPATH=src:. pytest -q tests/test_api_read_routes.py tests/test_dashboard_static.py tests/test_daily_report.py`
- Static tests must prove no memo UI control can mutate strategy/trading/timer state.

## Release Gate For M95-M98

- `node --check web/dashboard/app.js`
- `python3 -m py_compile src/pgc_trading/services/shadow_observation_service.py src/pgc_trading/services/strategy_evolution_service.py scripts/monitor_shadow_strategies.py scripts/generate_shadow_replay_backtest_evidence.py scripts/calibrate_shadow_thresholds.py src/pgc_trading/cli/main.py`
- `PYTHONPATH=src:. pytest -q`
- `git diff --check`
- Secret/path scan:
  - `rg -n "sk-[A-Za-z0-9]|api key|API_KEY|TUSHARE_TOKEN|DEEPSEEK|OPENAI" src scripts tests docs reports web`
  - `rg -n "/Users/azboo/Desktop/Person/pgc|/private/tmp" reports/shadow_*.json reports/shadow_*.md`

## Non-Negotiable Safety Rules

- No active CPB param mutation.
- No strategy version publication.
- No trade plan/trade/position writes.
- No paper/live behavior changes.
- No broker execution.
- No timer enablement or mutation.
- Evidence acceptance is not promotion approval.
