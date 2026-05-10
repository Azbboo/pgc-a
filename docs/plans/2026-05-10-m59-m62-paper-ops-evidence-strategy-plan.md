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
| M59 | Production evidence backfill execution | Done, Deployed | Yes | M55 backfill tooling, M54 provider-file contracts | Session A |
| M60 | Strategy-version proposal workflow | Done, Deployed | Yes | M56 workbench, M50 validation gates | Session B |
| M61 | Paper acceptance history and alerting | Done, Deployed | Yes | M57 acceptance dashboard | Session C |
| M62 | Timer dry-run evidence collection | Done, Deployed; Gate Evidence Pending | After next clean dry-run window | M58 activation gate | Ops session |

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

Production execution on 2026-05-10:

```bash
scripts/backup_remote_pgc_db.sh
# /opt/pgc/backups/pgc_trading-20260510-193204.db

PYTHONPATH=/opt/pgc/app/src python3 -m pgc_trading.cli.main market-review external-data backfill \
  --input /opt/pgc/data/evidence_backfill/m59-20260510/provider-files/market_external_20260507.json \
          /opt/pgc/data/evidence_backfill/m59-20260510/provider-files/market_external_20260508.json \
  --db-path /opt/pgc/data/pgc_trading.db --apply --operator codex-m59
# inserted=4, invalid=0, duplicates=0

PYTHONPATH=/opt/pgc/app/src python3 -m pgc_trading.cli.main agent external-data backfill \
  --input /opt/pgc/data/evidence_backfill/m59-20260510/provider-files/agent_external_20260507.json \
          /opt/pgc/data/evidence_backfill/m59-20260510/provider-files/agent_external_20260508.json \
  --db-path /opt/pgc/data/pgc_trading.db --apply --operator codex-m59
# inserted=6, updated=0, invalid=0
```

Evidence files and logs:

- Provider files: `/opt/pgc/data/evidence_backfill/m59-20260510/provider-files/`.
- Dry-run/apply logs: `/opt/pgc/logs/m59-20260510/market_backfill_*` and `/opt/pgc/logs/m59-20260510/agent_backfill_*`.
- Refreshed market review runs: `market_review_runs:1` for `20260507`, `market_review_runs:2` for `20260508`.
- Refreshed reports: `/opt/pgc/reports/daily_review_20260507.{json,md}` and `/opt/pgc/reports/daily_review_20260508.{json,md}`.

Coverage QA outcome:

- Market backfill: `20260507` and `20260508` inserted fresh market + stock cached research notes. `sector` remains missing for both dates because no cached sector provider file was present.
- Agent backfill: each date inserted cached `fundamental`, `research_note`, and `risk_note` rows. `announcement`, `news`, and `sentiment` remain missing because no reviewed provider files existed; existing Agent runs were not rerun.
- Report refresh now shows full-market external evidence as 2 rows per date, with `MARKET_PLAN_CONTEXT_MISSING` and `AGENT_EXTERNAL_EVIDENCE_MISSING` still explicit. No live fetch, strategy mutation, trade write, position write, or timer enablement was performed.

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

**M60 completion note:** Implemented `strategy-evolution proposal` as a dry-run/apply workflow that builds `strategy_version_proposal` JSON artifacts from accepted hypotheses, records only proposal artifact metadata on `strategy_hypotheses.validation`, and keeps `strategy_versions`, active params, trade plans, trades, positions, paper behavior, and live behavior unchanged. Verified with:

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_strategy_evolution_service.py tests/test_strategy_hypothesis_backtest_service.py tests/test_cli_market_review.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

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

**M61 completion note:** Implemented read-only paper acceptance history and alerting through reporting/API/Dashboard. The history derives from existing daily review dates, surfaces blocker/evidence/Agent/open-execution trend counts, and adds alert rows without any trade execution, plan cancellation, or strategy mutation path. Verified with:

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_daily_report.py tests/test_api_read_routes.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

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

**M62 execution note:** Implemented numbered dry-run evidence logs with `--evidence-run`, refusal to overwrite existing evidence logs, stricter activation validation for `evidence_log_role=dry_run_activation_evidence`, and a `--collect-evidence` installer action that runs remote dry-runs only, copies the log into `.pgc-runs/timer-evidence`, and leaves systemd timer state unchanged. Verified with:

```bash
bash -n scripts/run_daily_pipeline.sh scripts/install_remote_daily_pipeline_timer.sh
PYTHONPATH=src:. pytest -q tests/test_daily_pipeline_script.py tests/test_operational_runbook_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

Remote dry-run evidence attempt on 2026-05-10:

```bash
scp scripts/run_daily_pipeline.sh root@150.158.121.150:/tmp/run_daily_pipeline_m62.sh
ssh root@150.158.121.150 'cd /opt/pgc/app && PGC_DAILY_PIPELINE_LOG_DIR=/opt/pgc/logs PGC_DB_PATH=/opt/pgc/data/pgc_trading.db bash /tmp/run_daily_pipeline_m62.sh --date latest-closed --account paper-main --operator system-daily-pipeline --db-path /opt/pgc/data/pgc_trading.db --backup-dir /opt/pgc/backups --include-market-review --dry-run --evidence-run m62-1'
scp root@150.158.121.150:/opt/pgc/logs/daily-pipeline-20260508-m62-1.log .pgc-runs/timer-evidence/daily-pipeline-20260508-m62-1.log
```

Outcome: the remote dry-run returned `pipeline_status=pass`, `backup_path=none`, `changed=false`, `report_would_write=true`, and `market_review_would_write=true`, but it also returned `duplicate_apply_count=2` for `resolved_date=20260508` because completed daily-review and buy-plan apply writes already exist for that date. Therefore the M62 collection feature is complete, but this log is not M58 activation-ready, the required three `duplicate_apply_count=0` evidence logs remain pending, and production timer enablement remains blocked. No systemd service/timer write, deployment, apply write, strategy mutation, trade write, or timer enablement was performed.

## Release Verification

Local release verification on 2026-05-10:

```bash
node --check web/dashboard/app.js
bash -n scripts/run_daily_pipeline.sh scripts/install_remote_daily_pipeline_timer.sh
PYTHONPATH=src:. pytest -q
git diff --check
# 367 passed, 3 skipped, 10 subtests passed
```

Boundary result: M59-M62 remains advisory/operational tooling. Strategy proposals do not mutate active strategy versions or paper/live behavior, acceptance history remains read-only, and timer evidence collection still requires explicit approval before production timer enablement.
