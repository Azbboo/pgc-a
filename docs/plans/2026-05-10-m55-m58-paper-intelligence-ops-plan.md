# M55-M58 Paper Intelligence Ops Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move from "market intelligence features are shipped" to "daily paper operation is evidence-rich, observable, and ready for disciplined strategy evolution."

**Architecture:** Keep execution and strategy mutation guarded. Evidence and Agent outputs remain advisory; paper operations use read-only summaries, explicit readiness gates, and operator actions. Any strategy-version change must be proposed as a separate future task after evidence and replay review.

**Tech Stack:** Python services and CLI, SQLite migrations through `012_market_review`, FastAPI read APIs, static Dashboard JavaScript/CSS, Bash ops scripts, Markdown/JSON reports, pytest/unittest, remote deployment on port `8020`.

---

## Baseline

- Latest planned release: `pgc-v0.1.0-20260510-m55-m58`
- M51/M52/M54 are deployed in that release.
- Timer remains disabled unless an operator explicitly enables it with `--enable`.
- Market/Agent evidence imports are cached-data operations; no live web fetch belongs in the trading path.

## Parallel Work Map

| Track | Task | Status | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- | --- |
| M55 | Historical evidence backfill and coverage QA | Done, Deployed | Yes | M54 provider-file contracts | Session A |
| M56 | Strategy hypothesis evaluation workbench | Done, Deployed | Yes | M50 validation gates, M44 backtest artifacts | Session B |
| M57 | Paper trading operations acceptance dashboard | Done, Deployed | Yes | M51 timeline, M52 ops monitor | Session C |
| M58 | Timer enablement decision and safe activation | Done, Deployed | After several successful dry-runs | M52 monitor, operator approval | Ops session |

## Local Verification Record

Verified on 2026-05-10:

```bash
PYTHONPATH=src:. pytest -q tests/test_market_external_data_service.py tests/test_agent_external_data_service.py tests/test_cli_market_review.py tests/test_strategy_evolution_service.py tests/test_strategy_hypothesis_backtest_service.py tests/test_api_read_routes.py tests/test_dashboard_static.py tests/test_daily_report.py tests/test_daily_pipeline_script.py tests/test_operational_runbook_static.py tests/test_cli_main.py tests/test_api_app.py
# 146 passed, 3 skipped, 1 subtests passed

node --check web/dashboard/app.js
bash -n scripts/run_daily_pipeline.sh scripts/install_remote_daily_pipeline_timer.sh
git diff --check

PYTHONPATH=src:. pytest -q
# 357 passed, 3 skipped, 10 subtests passed
```

Boundary checks found no new automatic trading writes, no market-review POST path, and no live evidence fetch in the trading path. M58 implements the safe activation gate; production timer remains disabled until explicit operator approval and evidence logs are provided.

## M55: Historical Evidence Backfill And Coverage QA

**Goal:** Backfill cached market/sector/stock evidence for prior review dates and make coverage quality visible before daily reviews depend on it.

**Files:**
- Modify: `src/pgc_trading/services/market_external_data_service.py`
- Modify: `src/pgc_trading/services/agent_external_data_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `reports/operational_runbook_design.md`
- Test: `tests/test_market_external_data_service.py`
- Test: `tests/test_agent_external_data_service.py`
- Test: `tests/test_cli_market_review.py`

**Acceptance commands:**

```bash
PYTHONPATH=src:. pytest -q tests/test_market_external_data_service.py tests/test_agent_external_data_service.py tests/test_cli_market_review.py
PYTHONPATH=src:. pytest -q
git diff --check
```

Local verification on 2026-05-10:

```bash
PYTHONPATH=src:. pytest -q tests/test_market_external_data_service.py tests/test_agent_external_data_service.py tests/test_cli_market_review.py
# 41 passed
PYTHONPATH=src:. pytest -q
# 351 passed, 3 skipped, 10 subtests passed
git diff --check
# clean
```

**Review focus:** no live web fetch in daily/opening/report/Dashboard paths; stale/missing/duplicate coverage remains explicit.

## M56: Strategy Hypothesis Evaluation Workbench

**Goal:** Make strategy hypotheses, evidence, and backtest artifacts reviewable before any future strategy-version proposal.

**Files:**
- Modify: `src/pgc_trading/services/strategy_evolution_service.py`
- Modify: `src/pgc_trading/services/strategy_hypothesis_backtest_service.py`
- Modify: `src/pgc_trading/api/routes.py`
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/styles.css`
- Test: `tests/test_strategy_evolution_service.py`
- Test: `tests/test_strategy_hypothesis_backtest_service.py`
- Test: `tests/test_api_read_routes.py`
- Test: `tests/test_dashboard_static.py`

**Acceptance commands:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_strategy_evolution_service.py tests/test_strategy_hypothesis_backtest_service.py tests/test_api_read_routes.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** accepted hypotheses still do not mutate active strategy params or paper/live trading behavior.

## M57: Paper Trading Operations Acceptance Dashboard

**Goal:** Give the operator a single daily acceptance view for paper trading: data freshness, evidence coverage, Agent status, open-execution state, readiness gates, and unresolved blockers.

**Files:**
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `src/pgc_trading/services/operational_readiness_service.py`
- Modify: `src/pgc_trading/api/routes.py`
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/styles.css`
- Test: `tests/test_daily_report.py`
- Test: `tests/test_api_read_routes.py`
- Test: `tests/test_dashboard_static.py`

**Acceptance commands:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_daily_report.py tests/test_api_read_routes.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** dashboard must not execute trades, cancel plans, or hide blocker/evidence gaps.

## M58: Timer Enablement Decision And Safe Activation

**Goal:** Decide whether to enable the post-close timer after repeated dry-run evidence and operator approval.

**Files:**
- Modify: `scripts/install_remote_daily_pipeline_timer.sh`
- Modify: `scripts/run_daily_pipeline.sh`
- Modify: `reports/operational_runbook_design.md`
- Test: `tests/test_daily_pipeline_script.py`
- Test: `tests/test_operational_runbook_static.py`

**Acceptance commands:**

```bash
bash -n scripts/run_daily_pipeline.sh scripts/install_remote_daily_pipeline_timer.sh
PYTHONPATH=src:. pytest -q tests/test_daily_pipeline_script.py tests/test_operational_runbook_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

Local M58 execution on 2026-05-10:

```bash
bash -n scripts/run_daily_pipeline.sh scripts/install_remote_daily_pipeline_timer.sh
# pass
PYTHONPATH=src:. pytest -q tests/test_daily_pipeline_script.py tests/test_operational_runbook_static.py
# 18 passed
PYTHONPATH=src:. pytest -q
# 352 passed, 3 skipped, 10 subtests passed
git diff --check
# clean
```

Decision: activation remains blocked. The installer now has a local `--check-activation` gate, and `--enable` refuses to proceed unless an operator supplies `--approval-id` plus at least three dry-run evidence logs containing `pipeline_status=pass`, `market_review_would_write=true`, `report_would_write=true`, `backup_path=none`, `changed=false`, `duplicate_apply_count=0`, and `duplicate_write_guard=dry_run`.

**Review focus:** `--enable` remains explicit; duplicate-write guard stays active; rollback is documented and tested.
