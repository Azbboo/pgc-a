# M59-M62 Paper Ops Evidence And Strategy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the shipped evidence, acceptance, strategy workbench, and timer gate into repeatable paper-trading operations.

**Architecture:** Keep operational actions explicit and auditable. Evidence backfills remain cached-data imports, strategy evolution produces proposal artifacts rather than live parameter changes, and timer enablement stays blocked until dry-run evidence plus operator approval are present.

**Tech Stack:** Python services and CLI, SQLite migrations through `012_market_review`, FastAPI read APIs, static Dashboard JavaScript/CSS, Bash ops scripts, Markdown/JSON reports, pytest/unittest, remote deployment on port `8020`.

---

## Baseline

- Latest planned release: `pgc-v0.1.0-20260510-m55-m58`
- M55/M56/M57/M58 are deployed in that release.
- Production timer remains disabled until explicit operator approval.
- Evidence imports and Agent context must use cached provider files; no live web fetch belongs in daily-close/open-execution/report/Dashboard paths.

## Parallel Work Map

| Track | Task | Status | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- | --- |
| M59 | Production evidence backfill execution | Next | Yes | M55 backfill tooling, M54 provider-file contracts | Session A |
| M60 | Strategy-version proposal workflow | Next | Yes | M56 workbench, M50 validation gates | Session B |
| M61 | Paper acceptance history and alerting | Next | Yes | M57 acceptance dashboard | Session C |
| M62 | Timer dry-run evidence collection | Blocked | After operator provides/approves dry-run window | M58 activation gate | Ops session |

## M59: Production Evidence Backfill Execution

**Goal:** Run the cached evidence backfill flow for recent review dates and store auditable coverage QA results.

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

**Review focus:** no live fetch in trading path; coverage QA must expose stale, missing, duplicate, and source-hash mismatch states.

## M60: Strategy-Version Proposal Workflow

**Goal:** Convert accepted hypotheses into separate strategy-version proposal artifacts without changing active strategy behavior.

**Files:**
- Modify: `src/pgc_trading/services/strategy_evolution_service.py`
- Modify: `src/pgc_trading/services/strategy_hypothesis_backtest_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `web/dashboard/app.js`
- Test: `tests/test_strategy_evolution_service.py`
- Test: `tests/test_strategy_hypothesis_backtest_service.py`
- Test: `tests/test_cli_market_review.py`
- Test: `tests/test_dashboard_static.py`

**Acceptance commands:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_strategy_evolution_service.py tests/test_strategy_hypothesis_backtest_service.py tests/test_cli_market_review.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** proposal artifacts only; no updates to active strategy params, trade plans, trades, positions, paper behavior, or live behavior.

## M61: Paper Acceptance History And Alerting

**Goal:** Track daily paper-acceptance history and alert on unresolved blockers, stale evidence, missing Agent review, or open-execution mismatch.

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

**Review focus:** alerts remain read-only; they must not execute trades, cancel plans, or hide evidence/data blockers.

## M62: Timer Dry-Run Evidence Collection

**Goal:** Collect the repeated successful dry-run evidence needed by the M58 activation gate while keeping production timer disabled.

**Files:**
- Modify: `scripts/run_daily_pipeline.sh`
- Modify: `scripts/install_remote_daily_pipeline_timer.sh`
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

**Review focus:** timer remains disabled unless operator explicitly approves; `--enable` requires evidence logs and approval id; rollback stays documented.
