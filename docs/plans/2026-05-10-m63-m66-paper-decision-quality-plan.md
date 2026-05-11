# M63-M66 Paper Decision Quality Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the remaining evidence gaps and turn paper-trading operations into a clearer next-trading-day decision loop.

**Architecture:** Keep all market intelligence and strategy evolution advisory until a later explicit promotion task changes that contract. Evidence improvements use reviewed cached provider files; dashboards and APIs remain read-only unless they are existing guarded ledger endpoints.

**Tech Stack:** Python services and CLI, SQLite through `012_market_review`, FastAPI read APIs, static Dashboard JavaScript/CSS, Bash ops scripts, Markdown/JSON reports, pytest/unittest, remote deployment on port `8020`.

---

## Baseline

- Latest planned release: `pgc-v0.1.0-20260511-m63-m66`.
- M59-M62 are deployed in `pgc-v0.1.0-20260510-m59-m62`.
- Production timer remains disabled until three clean dry-run evidence logs and explicit operator approval exist.
- Evidence imports and Agent context must use cached provider files; no live web fetch belongs in daily-close/open-execution/report/Dashboard paths.
- Strategy proposal output must not mutate active strategy params, trade plans, trades, positions, paper behavior, or live behavior.

## Parallel Work Map

| Track | Task | Status | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- | --- |
| M63 | Evidence blocker closure for sector/news/sentiment | Done, Deployed | Yes | M59 backfill tooling, M54 provider-file contracts | Session A |
| M64 | Strategy proposal review and promotion gate | Done, Deployed | Yes | M60 proposal artifacts, M50 validation gates | Session B |
| M65 | Ops run history and evidence observability | Done, Deployed | Yes | M61 acceptance history, M62 evidence logs, M52 monitor | Session C |
| M66 | Next-trading-day decision cockpit | Done, Deployed | After M63-M65 data shapes are known | M59-M65 outputs | Integration session |

## M63: Evidence Blocker Closure For Sector/News/Sentiment

**Goal:** Convert the known missing sector and Agent announcement/news/sentiment blockers into reviewed cached evidence or explicit per-source unavailable states.

**Files:**
- Modify: `src/pgc_trading/services/market_external_data_service.py`
- Modify: `src/pgc_trading/services/agent_external_data_service.py`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `src/pgc_trading/cli/main.py`
- Test: `tests/test_market_external_data_service.py`
- Test: `tests/test_agent_external_data_service.py`
- Test: `tests/test_daily_report.py`
- Test: `tests/test_cli_market_review.py`

**Acceptance commands:**

```bash
PYTHONPATH=src:. pytest -q tests/test_market_external_data_service.py tests/test_agent_external_data_service.py tests/test_daily_report.py tests/test_cli_market_review.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** provider files only; no live fetch in trading path. Missing provider data must remain visible as `missing`, `partial`, or `unavailable`, never silently treated as safe.

**M63 completion note:** Implemented reviewed `unavailable_sources` provider-file handling for market sector and Agent announcement/news/sentiment gaps. Backfill QA now exposes gap summaries and CLI `evidence_gap_json`, while the daily report keeps missing/partial/unavailable evidence explicit instead of treating absent provider data as safe. Verified with targeted evidence/report tests, full suite, frontend/script syntax checks, and `git diff --check`.

## M64: Strategy Proposal Review And Promotion Gate

**Goal:** Let operators review accepted hypothesis proposal artifacts and create explicit promotion-request artifacts without changing active strategy behavior.

**Files:**
- Modify: `src/pgc_trading/services/strategy_evolution_service.py`
- Modify: `src/pgc_trading/api/routes.py`
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/styles.css`
- Test: `tests/test_strategy_evolution_service.py`
- Test: `tests/test_api_read_routes.py`
- Test: `tests/test_dashboard_static.py`

**Acceptance commands:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_strategy_evolution_service.py tests/test_api_read_routes.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** proposal review may approve, reject, or request promotion as artifacts only. It must not update `strategy_versions`, active params, trade plans, trades, positions, paper behavior, or live behavior.

**M64 completion note:** Implemented `strategy_version_proposal_review` and `strategy_version_promotion_request` artifact flows from accepted hypotheses with valid proposal artifacts. The service records only proposal-review metadata on `strategy_hypotheses.validation`, the API exposes guarded artifact-only creation at `/api/strategy-hypotheses/proposal-reviews`, and the Dashboard can approve, reject, or request promotion while keeping strategy versions, active params, trade plans, trades, positions, paper behavior, and live behavior unchanged. Verified with:

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_strategy_evolution_service.py tests/test_api_read_routes.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

## M65: Ops Run History And Evidence Observability

**Goal:** Give operators one read-only history for daily pipeline runs, backups, release tags, remote health, paper acceptance snapshots, and timer dry-run evidence attempts.

**Files:**
- Modify: `scripts/run_daily_pipeline.sh`
- Modify: `scripts/install_remote_daily_pipeline_timer.sh`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `src/pgc_trading/api/routes.py`
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/styles.css`
- Test: `tests/test_daily_pipeline_script.py`
- Test: `tests/test_api_read_routes.py`
- Test: `tests/test_dashboard_static.py`

**Acceptance commands:**

```bash
bash -n scripts/run_daily_pipeline.sh scripts/install_remote_daily_pipeline_timer.sh
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_daily_pipeline_script.py tests/test_api_read_routes.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** history is observability only. It must not enable timers, rerun apply jobs, create trades, cancel plans, or mutate strategy state.

**M65 completion note:** Implemented read-only ops history through `/api/ops-history` and Dashboard 运维历史, covering operation requests, pipeline/evidence logs, backups, release artifacts, health evidence, paper acceptance snapshots, and timer action evidence. Pipeline/timer scripts emit `ops_history_*` fields, but do not enable timers, rerun apply jobs, create trades, cancel plans, or mutate strategy state. Verified with targeted API/script/Dashboard tests, full suite, and `git diff --check`.

## M66: Next-Trading-Day Decision Cockpit

**Goal:** Show one operator checklist for the next trading day: what the system proposes, why it is allowed or blocked, what evidence is fresh or missing, and which manual action is next.

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

**Review focus:** the cockpit can explain next actions and blockers, but it must not execute trades, enable timers, or hide unresolved evidence gaps.

**M66 completion note:** Implemented a read-only next-trading-day decision cockpit in the report payload, API, and Dashboard. The cockpit combines paper acceptance, evidence freshness/coverage, full-market review and plan context, open-execution next action, and strategy hypothesis/proposal review state into a single operator checklist with a recommended manual action. It does not add any trade execution, timer enablement, or strategy-parameter mutation path. Verified with:

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_daily_report.py tests/test_api_read_routes.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q tests/test_api_app.py
git diff --check
```

## Parallelization Notes

- M63, M64, and M65 can run in parallel because their primary write scopes are evidence services, strategy proposal review, and ops observability.
- M66 should start after the first three tasks expose stable response shapes, or it should restrict itself to mock/read-only integration until those shapes land.
- M62 timer activation remains a separate operator decision. These tasks may improve evidence collection and visibility, but they must not enable production timer by default.

## Release Verification

Local release verification on 2026-05-11:

```bash
node --check web/dashboard/app.js
bash -n scripts/run_daily_pipeline.sh scripts/install_remote_daily_pipeline_timer.sh
PYTHONPATH=src:. pytest -q
git diff --check
# 379 passed, 3 skipped, 10 subtests passed
```

Boundary result: M63-M66 remains advisory and operational tooling. Evidence gaps stay explicit, proposal review/promotion artifacts do not mutate active strategy or paper/live trading behavior, ops history is read-only, the cockpit does not execute trades, and timer enablement remains gated by approval plus clean dry-run evidence.
