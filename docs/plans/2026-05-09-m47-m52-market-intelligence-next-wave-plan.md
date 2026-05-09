# M47-M52 Market Intelligence Next Wave Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade full-market review from a readable advisory page into a traceable market-intelligence loop that can inform, but never automatically mutate, next-day trading decisions.

**Architecture:** Keep market review, TradingAgents, and strategy evolution as advisory layers. Evidence is imported or cached before the trading path runs; daily/opening workflows only read persisted evidence and must expose missing coverage explicitly. Strategy changes remain gated by replay/backtest and paper observation.

**Tech Stack:** Python services and CLI, SQLite migration stack through `012_market_review`, FastAPI read APIs, static Dashboard JavaScript/CSS, TradingAgents adapter, Markdown/JSON reports, pytest/unittest, remote deployment on port `8020`.

---

## Current Baseline

- Branch: `codex/m14b-yfinance`
- Latest deployed release: `pgc-v0.1.0-20260509-m41b-m46`
- Remote migration state: `012_market_review`, `pending_migrations=none`
- M41B/M42/M45/M46 are done and deployed.
- M47/M48/M49/M50 are implemented and locally verified; they are not yet committed, pushed, or deployed in this batch.
- M46 systemd timer is previewed but not enabled.
- Full-market review is advisory only.

## Non-Negotiable Boundaries

- No market-review task may write `trades`, `positions`, or active strategy parameters.
- Market-plan context may warn, but must not cancel or execute a trade plan automatically.
- Missing news, sector, sentiment, or TradingAgents evidence must be visible as `missing`, `partial`, or `unknown`.
- No live web fetch inside the daily trading path; online data must be imported/cached first.
- TradingAgents output must be labeled as TradingAgents output, not silently rewritten as system facts.
- Any accepted strategy hypothesis creates a separate strategy-version task; it does not mutate live/paper behavior directly.

## Parallel Work Map

| Track | Task | Status | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- | --- |
| M47A | Evidence import and coverage contract | Done / Local verification | Yes | M43 source policy, M41A read APIs | Session A |
| M48A | Full-market Dashboard interaction upgrade | Done / Local verification | Yes | M41B full-market tab | Session B |
| M49A | TradingAgents Chinese structured report | Done / Local verification | Yes | M15/M26 agent bridge, external evidence cache | Session C |
| M50A | Strategy hypothesis validation loop | Done / Local verification | Yes | M44 backtest bridge, M40 hypotheses | Session D |
| M51 | Review timeline and cross-day comparison | Next | After M47/M48 data shape stabilizes | M12 history, M41B market page | Follow-up |
| M52 | Scheduled pipeline activation and ops monitor | Next | After M47/M49 evidence gates are stable | M46 timer installer | Ops follow-up |

## M47-M50 Local Verification Record

Verified on 2026-05-09:

```bash
PYTHONPATH=src:. pytest -q tests/test_market_external_data_service.py tests/test_market_review_service.py tests/test_cli_market_review.py tests/test_dashboard_static.py tests/test_tradingagents_adapter.py tests/test_agent_review_service.py tests/test_daily_report.py tests/test_strategy_evolution_service.py tests/test_strategy_hypothesis_backtest_service.py
# 70 passed, 1 skipped, 3 subtests passed

node --check web/dashboard/app.js
git diff --check
python3 -m py_compile src/pgc_trading/agents/tradingagents_adapter.py src/pgc_trading/cli/main.py src/pgc_trading/reporting/daily_report.py src/pgc_trading/services/agent_review_service.py src/pgc_trading/services/market_external_data_service.py src/pgc_trading/services/market_review_service.py src/pgc_trading/services/strategy_evolution_service.py src/pgc_trading/services/strategy_hypothesis_backtest_service.py

PYTHONPATH=src:. pytest -q
# 334 passed, 3 skipped, 10 subtests passed
```

Release status: local only. Commit, push, deploy, and remote health remain separate follow-up actions.

## M47: Data Evidence Closed Loop

**Goal:** Make full-market review evidence reliable enough to support day-to-day decisions.

**Files:**
- Modify: `src/pgc_trading/services/market_external_data_service.py`
- Modify: `src/pgc_trading/services/market_review_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `reports/operational_runbook_design.md`
- Test: `tests/test_market_external_data_service.py`
- Test: `tests/test_market_review_service.py`
- Test: `tests/test_cli_market_review.py`
- Fixture: `tests/fixtures/market_review/external_items_20260508.json`

**Required behavior:**
- Import provider-tagged news, policy, announcement, sentiment, and research-note evidence.
- Validate `provider`, `published_date`, `scope_type`, `scope_key`, `item_type`, `sentiment`, `importance`, `title`, `summary`, and `source_hash`.
- Add coverage/freshness summary by market, sector, and stock scope.
- Treat stale, missing, or duplicate evidence as explicit coverage states.
- Keep imports dry-run by default; apply requires existing write context.

**Acceptance commands:**

```bash
PYTHONPATH=src:. pytest -q tests/test_market_external_data_service.py tests/test_market_review_service.py tests/test_cli_market_review.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Reviewer focus:**
- No live web calls in service or daily pipeline.
- No secrets in fixtures or docs.
- Missing evidence stays visible to API, report, and Dashboard.

## M48: Full-Market Dashboard Interaction Upgrade

**Goal:** Make the full-market page usable for decision review instead of a flat wall of information.

**Files:**
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/styles.css`
- Test: `tests/test_dashboard_static.py`

**Required behavior:**
- Add sector drill-down drawers or modals.
- Add news/sentiment evidence detail drawer with provider/date/source metadata.
- Add cross-day market-review selector using existing history APIs.
- Show "明日计划关系" next to the relevant plan context.
- Keep all market-review UI read-only.

**Acceptance commands:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_dashboard_static.py tests/test_api_read_routes.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Manual smoke:**

```bash
PYTHONPATH=src PGC_API_ENABLE_WRITES=0 .venv/bin/python -m uvicorn 'pgc_trading.api:create_app' --factory --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/dashboard/` and verify desktop/mobile layout, drawers, no blank screen, and no market-review POST calls.

## M49: TradingAgents Chinese Structured Report

**Goal:** Surface TradingAgents reasoning as Chinese structured analysis with clear source boundaries.

**Files:**
- Modify: `src/pgc_trading/agents/tradingagents_adapter.py`
- Modify: `src/pgc_trading/services/agent_review_service.py`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `web/dashboard/app.js`
- Test: `tests/test_tradingagents_adapter.py`
- Test: `tests/test_agent_review_service.py`
- Test: `tests/test_daily_report.py`
- Test: `tests/test_dashboard_static.py`

**Required behavior:**
- Normalize TradingAgents output into Chinese sections: 基本面, 新闻, 情绪, 技术/量价, 板块位置, 风险, 结论.
- Persist raw artifacts and structured summary separately.
- Display whether the output came from real TradingAgents, local snapshot mode, or unavailable fallback.
- Do not fabricate basic/news/sentiment analysis when TradingAgents is unavailable.

**Acceptance commands:**

```bash
PYTHONPATH=src:. pytest -q tests/test_tradingagents_adapter.py tests/test_agent_review_service.py tests/test_daily_report.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Reviewer focus:**
- Chinese report is source-labeled.
- Raw artifact paths remain accessible.
- Unavailable package still produces an honest `no_opinion` / unavailable state.

## M50: Strategy Evolution Validation Loop

**Goal:** Turn strategy hypotheses into a controlled validation workflow before any strategy changes.

**Files:**
- Modify: `src/pgc_trading/services/strategy_evolution_service.py`
- Modify: `src/pgc_trading/services/strategy_hypothesis_backtest_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `reports/operational_runbook_design.md`
- Test: `tests/test_strategy_evolution_service.py`
- Test: `tests/test_strategy_hypothesis_backtest_service.py`
- Test: `tests/test_cli_market_review.py`

**Required behavior:**
- Add explicit statuses or review notes for proposed -> testing -> accepted/rejected.
- Require evidence IDs and backtest request artifacts before `accepted`.
- Keep `accepted` as a research outcome only.
- Generate a separate future strategy-version task when a hypothesis is accepted.

**Acceptance commands:**

```bash
PYTHONPATH=src:. pytest -q tests/test_strategy_evolution_service.py tests/test_strategy_hypothesis_backtest_service.py tests/test_cli_market_review.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Reviewer focus:**
- No active parameter mutation.
- No trading behavior changes.
- Accepted hypotheses are traceable to evidence and backtest artifacts.

## M51: Review Timeline And Cross-Day Comparison

**Goal:** Let the operator compare daily review, full-market review, plan context, and execution state across dates.

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
- Add cross-day timeline payload or compose from existing read APIs.
- Show review date, next trade date, pick, market regime, plan context, and open-execution state.
- Support "previous review" and "next review" navigation without changing execution context accidentally.

**Acceptance commands:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_daily_report.py tests/test_api_read_routes.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

## M52: Scheduled Pipeline Activation And Ops Monitor

**Goal:** Decide whether and how to enable the M46 timer safely in production.

**Files:**
- Modify: `scripts/install_remote_daily_pipeline_timer.sh`
- Modify: `scripts/run_daily_pipeline.sh`
- Modify: `reports/operational_runbook_design.md`
- Test: `tests/test_daily_pipeline_script.py`
- Test: `tests/test_operational_runbook_static.py`

**Required behavior:**
- Add a documented apply-mode activation checklist.
- Add status/journal/rollback commands to runbook.
- Confirm timer health without running duplicate daily-close writes.
- Keep timer disabled until an explicit operator decision enables it.

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

## Handoff Rule

Each child session should start by reading:

1. `docs/plans/global-task-ledger.md`
2. This plan file
3. The task-specific files listed above

Each child session should end with:

1. Task-specific tests
2. `PYTHONPATH=src:. pytest -q` when blast radius is not trivial
3. `git diff --check`
4. A short review note describing any write-boundary or data-freshness risks
