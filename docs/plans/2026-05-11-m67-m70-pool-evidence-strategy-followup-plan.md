# M67-M70 Pool, Evidence, Strategy, And Decision Follow-Up Plan

**Goal:** Turn the M63-M66 decision-quality foundation into repeatable daily operations, with safer stock-pool intake, evidence pack generation, strategy promotion shadow checks, and post-decision review.

**Architecture:** Keep trading actions explicit and manual. These tasks may validate data, create artifacts, and improve read-only observability, but they must not enable timers, place broker orders, mutate active strategy parameters, or silently treat missing evidence as safe.

**Tech Stack:** Python services and CLI, SQLite through `012_market_review`, FastAPI read APIs, static Dashboard JavaScript/CSS, Bash ops scripts, Markdown/JSON reports, pytest/unittest, remote deployment on port `8020`.

---

## Baseline

- Latest planned release before this wave: `pgc-v0.1.0-20260511-m63-m66`.
- `OPS-20260511` handles the immediate 2026-05-11 daily review and new stock入池 execution.
- Production timer remains disabled until three clean dry-run evidence logs and explicit operator approval exist.
- Evidence imports and Agent context must use cached provider files in trading paths.
- Strategy promotion requests are artifacts only until a later explicit activation task.

## Parallel Work Map

| Track | Task | Status | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- | --- |
| M67 | Stock pool intake validator and audit trail | Next | Yes | OPS-20260511 plan, pool/raw-event file formats | Session A |
| M68 | Evidence provider pack automation | Next | Yes | M63 unavailable-source states, M54 provider contracts | Session B |
| M69 | Strategy promotion shadow evaluation | Next | Yes | M64 promotion-request artifacts, M50 validation gates | Session C |
| M70 | Decision cockpit action log and review loop | Next | After M67-M69 data shapes are known | M66 cockpit, M65 ops history | Integration session |

## M67: Stock Pool Intake Validator And Audit Trail

**Goal:** Make new stock入池 repeatable and auditable before the daily review mutates pool/raw-event files.

**Expected scope:**
- Add a structured validator/deduper for `data/pgc_pool.json` and `data/pgc_raw_events.json`.
- Require stock code, event date, source, reason, and optional sector/theme metadata.
- Produce a dry-run summary with added/duplicate/invalid entries.
- Preserve existing JSON shape and avoid ad hoc string edits.

**Acceptance commands:**

```bash
PYTHONPATH=src:. pytest -q tests/test_raw_ingestion_service.py tests/test_market_data_service.py tests/test_daily_review_service.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** no duplicate pool entries, no malformed stock codes, and no direct trading writes.

## M68: Evidence Provider Pack Automation

**Goal:** Generate/import reviewed cached provider packs for sector/news/sentiment/announcement evidence so M63 unavailable gaps can close cleanly.

**Expected scope:**
- Build an ops-only provider pack command or script.
- Output provider-file manifests with source hashes and unavailable reasons.
- Reuse existing market/Agent external-data backfill validation.
- Keep live fetches out of daily-close/open-execution/report/Dashboard paths.

**Acceptance commands:**

```bash
PYTHONPATH=src:. pytest -q tests/test_market_external_data_service.py tests/test_agent_external_data_service.py tests/test_cli_market_review.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** provider packs are auditable cached inputs, not hidden live data dependencies.

## M69: Strategy Promotion Shadow Evaluation

**Goal:** Evaluate promotion-request artifacts against frozen strategy behavior before any future activation discussion.

**Expected scope:**
- Read `strategy_version_promotion_request` artifacts.
- Run replay/shadow comparison against current frozen strategy outputs.
- Produce win/loss/risk deltas and readiness blockers.
- Do not update `strategy_versions`, active params, trade plans, trades, positions, or paper/live behavior.

**Acceptance commands:**

```bash
PYTHONPATH=src:. pytest -q tests/test_strategy_evolution_service.py tests/test_strategy_hypothesis_backtest_service.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** shadow evaluation only; activation remains out of scope.

## M70: Decision Cockpit Action Log And Review Loop

**Goal:** Let operators record what manual decision they took from the cockpit and compare outcomes on the next review day.

**Expected scope:**
- Add an advisory action log artifact/API surface tied to review date and account.
- Link action log entries to next-day outcome review.
- Surface unresolved blockers and whether the operator followed, deferred, or overrode the recommendation.
- Keep execution recording in the existing guarded trade endpoints only.

**Acceptance commands:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_daily_report.py tests/test_api_read_routes.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** action log is advisory and auditable. It must not execute trades, enable timers, or mutate strategy state.

## Parallelization Notes

- M67, M68, and M69 can run independently.
- M70 should start after M66 response shapes are stable and can integrate M67/M68/M69 outputs when available.
- OPS-20260511 can run as an operational session in parallel with M67-M70, but it should not invent new task IDs or change strategy contracts.
