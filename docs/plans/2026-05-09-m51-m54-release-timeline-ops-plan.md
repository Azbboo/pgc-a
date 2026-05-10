# M51-M54 Release, Timeline, And Ops Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship the locally verified M47-M50 market-intelligence work, then complete the next operational loop: cross-day review, scheduled pipeline monitoring, and real evidence import operations.

**Architecture:** Release comes first so remote and local behavior stop diverging. M51 remains read-oriented Dashboard/API work, M52 remains explicit operator-controlled ops work, and M54 turns evidence imports into a repeatable cached-data operation without adding live web fetches to the trading path.

**Tech Stack:** Python services and CLI, SQLite migrations through `012_market_review`, FastAPI read APIs, static Dashboard JavaScript/CSS, Bash deploy/timer scripts, Markdown/JSON reports, pytest/unittest, remote deployment on port `8020`.

---

## Current Baseline

- Branch: `codex/m14b-yfinance`
- Latest deployed release: `pgc-v0.1.0-20260510-m51-m54`
- Latest pushed M47-M50 commit: `159382f`
- M47/M48/M49/M50 are deployed through release `pgc-v0.1.0-20260509-m47-m50`.
- M51/M52/M54 are implemented and deployed in release `pgc-v0.1.0-20260510-m51-m54`.
- Remote migration state before this wave: `012_market_review`, `pending_migrations=none`.
- M46 timer installer has passed dry-run preview, but the real systemd timer is not enabled.

## Non-Negotiable Boundaries

- No task in this wave may write `trades`, `positions`, or active strategy parameters from market-review output.
- Dashboard market-review/timeline views remain read-only.
- Timer activation requires explicit operator confirmation and a dry-run preview.
- Evidence import work may fetch or prepare data outside the trading path only; daily/opening workflows must consume cached local evidence.
- Missing or stale evidence remains visible as `missing`, `partial`, `stale`, or `unknown`.

## Parallel Work Map

| Track | Task | Status | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- | --- |
| M53 | Release M47-M50 checkpoint | Done, Deployed | No, do first | M47-M50 pushed commit `159382f` | Release session |
| M51 | Review timeline and cross-day comparison | Done, Deployed | Yes after M53 starts or completes | M47/M48 data shape | Session A |
| M52 | Scheduled pipeline activation and ops monitor | Done, Deployed | Yes after M53 deploy health | M46 timer installer, M47/M49 evidence gates | Session B |
| M54 | Production evidence import operations | Done, Deployed | Yes after M53 deploy health | M47 evidence contract, M49 Agent evidence cache | Session C |

## M53: Release M47-M50 Checkpoint

**Goal:** Deploy the pushed M47-M50 work to the server and update the global ledger from local verification to deployed.

**Files:**
- Modify: `docs/plans/global-task-ledger.md`
- Modify: `docs/plans/2026-05-09-m47-m52-market-intelligence-next-wave-plan.md`
- No feature-code changes expected.

**Steps:**

1. Confirm clean working tree or only planned doc changes.
2. Run release checks:

```bash
PYTHONPATH=src:. pytest -q
git diff --check
```

3. Deploy:

```bash
bash scripts/deploy_remote.sh --release-tag pgc-v0.1.0-20260509-m47-m50
```

4. Verify remote health:

```bash
ssh root@150.158.121.150 "cd /opt/pgc/app && PYTHONPATH=src python3 -m pgc_trading.cli.main ops health --db-path /opt/pgc/data/pgc_trading.db --health-url http://127.0.0.1:8020/api/health --require-current-migrations"
```

**Acceptance:**
- Deploy script test suite passes.
- Remote API health returns HTTP `200`.
- Remote migration state remains `012_market_review`, `pending_migrations=none`.
- Global ledger marks M47-M50 as `Done, Deployed`.
- M46/M52 timer remains disabled unless explicitly enabled by a separate operator decision.

## M51: Review Timeline And Cross-Day Comparison

**Goal:** Let the operator compare daily review, full-market review, plan context, and execution state across dates without losing execution-day context.

**Files:**
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `src/pgc_trading/api/routes.py`
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/styles.css`
- Test: `tests/test_daily_report.py`
- Test: `tests/test_api_read_routes.py`
- Test: `tests/test_dashboard_static.py`

**Required behavior:**
- Add a cross-day timeline payload or compose from existing read APIs.
- Show review date, next trade date, pick, market regime, plan context, and open-execution state.
- Add previous/next/latest controls for review dates.
- Do not let review-date navigation auto-change the execution date used for opening actions.
- Keep the view read-only.

**Acceptance commands:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_daily_report.py tests/test_api_read_routes.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

Local verification on 2026-05-10:

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_daily_report.py tests/test_api_read_routes.py tests/test_dashboard_static.py
# included in combined target run: 117 passed, 1 skipped, 1 subtests passed
PYTHONPATH=src:. pytest -q
# 343 passed, 3 skipped, 10 subtests passed
git diff --check
```

## M52: Scheduled Pipeline Activation And Ops Monitor

**Goal:** Turn the M46 timer installer into a safe operational flow with status, journal, and rollback visibility.

**Files:**
- Modify: `scripts/install_remote_daily_pipeline_timer.sh`
- Modify: `scripts/run_daily_pipeline.sh`
- Modify: `reports/operational_runbook_design.md`
- Test: `tests/test_daily_pipeline_script.py`
- Test: `tests/test_operational_runbook_static.py`

**Required behavior:**
- Add an apply-mode activation checklist to the runbook.
- Document status, journal, dry-run, manual-run, and rollback commands.
- Add guardrails against duplicate daily-close writes.
- Keep timer disabled by default; enabling it is an explicit operator action.

**Acceptance commands:**

```bash
bash -n scripts/run_daily_pipeline.sh scripts/install_remote_daily_pipeline_timer.sh
PYTHONPATH=src:. pytest -q tests/test_daily_pipeline_script.py tests/test_operational_runbook_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Ops smoke:**

```bash
scripts/install_remote_daily_pipeline_timer.sh --dry-run --mode apply --operator system-daily-pipeline
```

Expected: prints service path, timer path, schedule, command, status command, journal command, and rollback command without enabling the timer.

Local verification on 2026-05-10:

```bash
bash -n scripts/run_daily_pipeline.sh scripts/install_remote_daily_pipeline_timer.sh
PYTHONPATH=src:. pytest -q tests/test_daily_pipeline_script.py tests/test_operational_runbook_static.py
# 15 passed
scripts/install_remote_daily_pipeline_timer.sh --dry-run --mode apply --operator system-daily-pipeline
# action=preview, timer_enablement=preview_only, status/journal/rollback/manual commands printed
PYTHONPATH=src:. pytest -q
# 343 passed, 3 skipped, 10 subtests passed
git diff --check
node --check web/dashboard/app.js
```

Remote read-only monitor on 2026-05-10 returned `api_health_status_code=200`, `pending_migrations=none`, timer `not-found`/`inactive`, and no `pgc-daily-pipeline.service` journal entries. Timer remains disabled until a deployed operator run explicitly uses `scripts/install_remote_daily_pipeline_timer.sh --enable --operator system-daily-pipeline --mode apply`.

## M54: Production Evidence Import Operations

**Goal:** Make market/sector/stock evidence import repeatable for real operating days using cached provider files and explicit coverage checks.

**Files:**
- Modify: `src/pgc_trading/services/market_external_data_service.py`
- Modify: `src/pgc_trading/services/agent_external_data_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `reports/operational_runbook_design.md`
- Test: `tests/test_market_external_data_service.py`
- Test: `tests/test_agent_external_data_service.py`
- Test: `tests/test_cli_market_review.py`
- Test: `tests/test_operational_runbook_static.py`

**Required behavior:**
- Define an operator-facing provider file contract for market-level, sector-level, and stock-level evidence.
- Add a dry-run command path that reports coverage before apply.
- Add stale/duplicate/missing evidence summaries for the selected as-of date.
- Keep all imports idempotent by source hash.
- Do not fetch live web data inside daily-close, open-execution, report rendering, or Dashboard request handling.

**Acceptance commands:**

```bash
PYTHONPATH=src:. pytest -q tests/test_market_external_data_service.py tests/test_agent_external_data_service.py tests/test_cli_market_review.py tests/test_operational_runbook_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

Local verification on 2026-05-10:

```bash
PYTHONPATH=src:. pytest -q tests/test_market_external_data_service.py tests/test_agent_external_data_service.py tests/test_cli_market_review.py tests/test_operational_runbook_static.py
# included in combined target run: 117 passed, 1 skipped, 1 subtests passed
PYTHONPATH=src:. pytest -q
# 343 passed, 3 skipped, 10 subtests passed
git diff --check
```

## Handoff Rule

Every child session should start by reading:

1. `docs/plans/global-task-ledger.md`
2. This plan file
3. The task-specific files listed above

Every child session should end by updating the global ledger status for its task before reporting completion.
