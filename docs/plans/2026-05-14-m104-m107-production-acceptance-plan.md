# M104-M107 Production Acceptance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move the M100-M103 Chinese ops quality wave from "implemented and deployed" to "daily production acceptance": visually verify the operator UI, run the latest daily data path safely, close external-evidence gaps with reviewed provider packs, and prepare a manual-only shadow-to-paper promotion gate.

**Architecture:** Keep the system advisory-first. Daily data, market review, Agent evidence, and shadow strategy outputs may prepare decision packages, but no task may auto-promote a strategy, auto-place trades, mutate paper/live state outside existing guarded ledger commands, enable timers, or fetch live web evidence inside trading/report request paths. Split work into four parallel lanes with separate write scopes.

**Tech Stack:** Static Dashboard JavaScript/CSS, Python services and CLI, SQLite, Markdown/JSON reports, provider-file evidence packs, pytest/unittest, browser visual QA, existing remote deploy script on port `8020`.

---

## Parallel Map

| Lane | Task | Can Run In Parallel | Primary Write Scope | Review Focus |
| --- | --- | --- | --- | --- |
| A | M104 Dashboard production visual QA | Yes | `web/dashboard/*`, `tests/test_dashboard_static.py`, optional screenshots in `reports/` | Chinese UI readability, modal/drawer polish, mobile/desktop no-overlap |
| B | M105 Latest daily data and stock-pool production runbook | Yes | `scripts/*daily*`, `src/pgc_trading/services/daily_pipeline_service.py`, runbook/tests/reports | 2026-05-14 daily path readiness, duplicate-write guard, operator evidence |
| C | M106 Reviewed evidence-pack automation for market/Agent gaps | Yes | evidence provider pack service/scripts/tests, provider manifest/report artifacts | Close gaps with reviewed files only; no live fetch in trading path |
| D | M107 Shadow-to-paper manual promotion preflight | Yes | strategy evolution/shadow services/scripts/tests/reports | Produce manual promotion package; no strategy-version/trade/timer mutation |

## M104: Dashboard Production Visual QA

**Goal:** Verify the deployed Chinese Dashboard is readable and operational on desktop/mobile, and fix remaining layout/English issues found by visual QA.

**Files:**
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/styles.css`
- Test: `tests/test_dashboard_static.py`
- Optional artifact: `reports/dashboard_visual_qa_20260514.md`

**Steps:**
1. Start local API/static Dashboard or use the deployed `http://150.158.121.150:8020/dashboard/` read-only pages.
2. Capture desktop and mobile screenshots for: 执行台、每日复盘、全市场复盘、证据/运维、影子策略.
3. Fix visible overlap, clipped text, raw English labels, overly-flat dense panels, and ugly detail drawer sections.
4. Add static regression tests for any discovered copy/layout contracts that can be tested without a browser.
5. Verify:
   - `node --check web/dashboard/app.js`
   - `PYTHONPATH=src:. pytest -q tests/test_dashboard_static.py`
   - `git diff --check`

## M105: Latest Daily Data And Stock-Pool Production Runbook

**Goal:** Make the latest trading-day daily review and new-stock intake path executable by a child session without guessing commands.

**Files:**
- Modify: `scripts/run_daily_pipeline.sh`
- Modify: `src/pgc_trading/services/daily_pipeline_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `reports/operational_runbook_design.md`
- Test: `tests/test_daily_pipeline_script.py`
- Test: `tests/test_daily_pipeline_service.py`
- Test: `tests/test_cli_daily_pipeline.py`
- Test: `tests/test_operational_runbook_static.py`

**Steps:**
1. Add or refine runbook text for the exact daily sequence: backup, market data refresh, pool intake dry-run/apply, daily preflight, daily pipeline dry-run/apply, report review, remote health.
2. Ensure `run_daily_pipeline.sh --dry-run` always remains usable for post-apply review while `--apply` blocks duplicate writes unless `--allow-rerun` is explicit.
3. Surface stock-pool intake audit path and counts in both preflight and pipeline outputs.
4. If the current latest trading day is ready, execute only with operator/idempotency/backup safeguards and record report paths.
5. Verify:
   - `bash -n scripts/run_daily_pipeline.sh`
   - `PYTHONPATH=src:. pytest -q tests/test_daily_pipeline_script.py tests/test_daily_pipeline_service.py tests/test_cli_daily_pipeline.py tests/test_operational_runbook_static.py`
   - `git diff --check`

## M106: Reviewed Evidence-Pack Automation For Market/Agent Gaps

**Goal:** Reduce empty or missing full-market/Agent evidence by making reviewed provider packs easier to generate, validate, import, and audit.

**Files:**
- Modify: `src/pgc_trading/services/evidence_provider_pack_service.py`
- Modify: `src/pgc_trading/services/market_external_data_service.py`
- Modify: `src/pgc_trading/services/agent_review_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Test: `tests/test_evidence_provider_pack_service.py`
- Test: `tests/test_market_external_data_service.py`
- Test: `tests/test_agent_review_service.py`
- Optional artifact: `reports/evidence_provider_pack_qa_20260514.{json,md}`

**Steps:**
1. Add tests for provider-pack manifest validation: date, provider, source hash, unavailable state, duplicate items, stale date, missing sentiment/news/announcement sections.
2. Add QA output that tells the operator which gaps are closed, which remain explicit, and which provider files need review.
3. Keep imports provider-file based. Do not add live web fetches to daily-close, report rendering, API request handling, or Dashboard request paths.
4. Connect QA summary to daily report or ops-history if existing surfaces already support it.
5. Verify:
   - `PYTHONPATH=src:. pytest -q tests/test_evidence_provider_pack_service.py tests/test_market_external_data_service.py tests/test_agent_review_service.py`
   - `python3 -m compileall -q src scripts`
   - `git diff --check`

## M107: Shadow-To-Paper Manual Promotion Preflight

**Goal:** Prepare a manual-only promotion package that says whether any shadow candidate is mature enough for a future paper candidate task, without publishing strategy versions or changing paper/live behavior.

**Files:**
- Modify: `src/pgc_trading/services/strategy_evolution_service.py`
- Modify: `src/pgc_trading/services/shadow_observation_service.py`
- Modify: `scripts/monitor_shadow_strategies.py`
- Test: `tests/test_strategy_evolution_service.py`
- Test: `tests/test_shadow_observation_service.py`
- Test: `tests/test_shadow_strategy_monitor_script.py`
- Optional artifacts: `reports/shadow_paper_preflight_20260514.{json,md}`

**Steps:**
1. Add a `shadow_paper_preflight_v1` package with readiness score, evidence sufficiency, walk-forward sufficiency, stop-rule status, risk/rollback notes, and required human approvals.
2. Mark all candidates `paper_candidate_allowed=false` unless a separate future task explicitly approves a strategy-version proposal.
3. Add regression tests proving no writes to strategy versions, trade plans, trades, positions, paper/live state, broker execution, or timers.
4. Surface a concise Chinese summary in report/CLI artifacts.
5. Verify:
   - `PYTHONPATH=src:. pytest -q tests/test_strategy_evolution_service.py tests/test_shadow_observation_service.py tests/test_shadow_strategy_monitor_script.py`
   - `python3 -m compileall -q src scripts`
   - `git diff --check`

## Integration Gate

After M104-M107 complete:

1. Run focused checks:
   - `node --check web/dashboard/app.js`
   - `bash -n scripts/run_daily_pipeline.sh`
   - `python3 -m compileall -q src scripts`
   - `PYTHONPATH=src:. pytest -q tests/test_dashboard_static.py tests/test_daily_pipeline_script.py tests/test_daily_pipeline_service.py tests/test_cli_daily_pipeline.py tests/test_operational_runbook_static.py tests/test_evidence_provider_pack_service.py tests/test_market_external_data_service.py tests/test_agent_review_service.py tests/test_strategy_evolution_service.py tests/test_shadow_observation_service.py tests/test_shadow_strategy_monitor_script.py`
2. Run full suite:
   - `PYTHONPATH=src:. pytest -q`
3. Commit, push, deploy, and health-check:
   - `git commit -m "Complete M104-M107 production acceptance wave"`
   - `git push`
   - `bash scripts/deploy_remote.sh --release-tag pgc-v0.1.0-20260514-m104-m107-production-acceptance-r1`
   - `ssh root@150.158.121.150 "cd /opt/pgc/app && PYTHONPATH=src python3 -m pgc_trading.cli.main ops health --db-path /opt/pgc/data/pgc_trading.db --health-url http://127.0.0.1:8020/api/health --require-current-migrations"`

