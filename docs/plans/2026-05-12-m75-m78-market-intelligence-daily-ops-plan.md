# M75-M78 Market Intelligence Daily Ops Plan

**Goal:** Move the market-intelligence system from "data exists" to a repeatable daily operating loop: daily stock-pool intake and review are closed, full-market review explains regime/sector/stock evidence, external evidence quality is auditable, and shadow strategy evolution stays research-only until promotion gates are cleared.

**Architecture:** Trading execution remains guarded and manual. Evidence enters through reviewed cached files or explicit unavailable states. Shadow strategy candidates may create reports, monitors, and proposal artifacts, but must not mutate active strategy params, trade plans, trades, positions, paper/live behavior, broker execution, or timer state.

**Tech Stack:** Python services and CLI, SQLite through `013_decision_action_log`, FastAPI read/write-guarded APIs, static Dashboard JavaScript/CSS, Markdown/JSON reports, pytest/unittest, remote deployment on port `8020`.

---

## Baseline

- M71-M74 are completed and scheduled for release `pgc-v0.1.0-20260512-m71-m74`.
- Current remote migration target remains `013_decision_action_log`.
- M71 closed reviewed 20260511 evidence gaps where provider files existed; missing news/sentiment/announcement evidence remains explicit.
- M72 added diagnostics for empty full-market panels and local/remote parity checks.
- M73 registered shadow candidates as artifact-only and Codex review restored the active CPB `min_entry_price=10.0` boundary.
- M74 added decision action outcome review and ops audit hardening.

## Parallel Work Map

| Track | Task | Status | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- | --- |
| M75 | Daily review and stock-pool intake closure for 20260512+ | Next | Yes | OPS-20260511, M67, M71 | Session A |
| M76 | Full-market review hierarchy and plan linkage UX | Next | Yes | M72, M48, M66 | Session B |
| M77 | External evidence provider QA and coverage ledger | Next | Yes | M68, M71, M72 | Session C |
| M78 | Shadow strategy monitor and promotion preflight | Next | Yes | M73, M50, M64 | Session D |

## M75: Daily Review And Stock-Pool Intake Closure For 20260512+

**Goal:** Make the next daily ops session able to ingest new stock data, run daily review, refresh reports, and leave a clear audit record.

**Expected scope:**
- Define the exact 20260512+ runbook for stock-pool intake, market data refresh, daily-close/daily-review, market-review, Agent/evidence status, and report refresh.
- Add or improve CLI checks that show which daily step is missing before apply.
- Keep non-dry-run writes operator/idempotency guarded.
- Do not enable the production timer without explicit operator approval.

**Acceptance commands:**

```bash
PYTHONPATH=src:. pytest -q tests/test_cli_main.py tests/test_ops.py tests/test_daily_report.py tests/test_pool_intake_service.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** daily ops must be repeatable, auditable, and should not silently rerun apply writes.

## M76: Full-Market Review Hierarchy And Plan Linkage UX

**Goal:** Turn the all-market review page/report into a readable chain: market regime -> sector rotation -> stock evidence -> news/sentiment -> continuity judgement -> next-trading-day plan relationship.

**Expected scope:**
- Add API/report/Dashboard grouping for regime, sectors, representative stocks, evidence freshness, and source refs.
- Surface continuity labels such as improving, fading, crowded, divergent, or insufficient evidence.
- Link each next-day plan/pick to the relevant market-review context and explain aligned, cautious, blocked, or missing.
- Preserve read-only market-review UI and explicit empty states from M72.

**Acceptance commands:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_api_read_routes.py tests/test_daily_report.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** no fabricated news/sentiment; UI must explain missing data instead of hiding it.

## M77: External Evidence Provider QA And Coverage Ledger

**Goal:** Make evidence quality trackable across dates and providers, not just visible inside one daily report.

**Expected scope:**
- Add an evidence coverage ledger by date/provider/entity type/source state.
- Compare provider-pack manifest rows with imported `market_external_items` and `agent_external_items`.
- Surface stale, missing, unavailable, partial, duplicate, and source-hash-mismatch states in CLI/API/report.
- Keep live fetches outside trading paths; provider files must remain reviewed/cached inputs.

**Acceptance commands:**

```bash
PYTHONPATH=src:. pytest -q tests/test_evidence_provider_pack_service.py tests/test_agent_external_data_service.py tests/test_market_external_data_service.py tests/test_daily_report.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** evidence coverage should be auditable without inventing unavailable external data.

## M78: Shadow Strategy Monitor And Promotion Preflight

**Goal:** Convert shadow candidates into a daily walk-forward monitor and keep promotion blocked until evidence gates are explicitly cleared.

**Expected scope:**
- Formalize shadow monitor outputs for trend-extension, breakout-pressure, low-price momentum, pre-confirm watchlist, and dip-buy candidates.
- Add report/API summaries for 20-trading-day walk-forward progress, blockers, and comparison against frozen CPB.
- Add regression checks that active CPB params/hash and paper/live trading behavior are unchanged.
- Produce promotion preflight artifacts only; do not activate strategy params.

**Acceptance commands:**

```bash
python3 -m py_compile scripts/monitor_shadow_strategies.py
PYTHONPATH=src:. pytest -q tests/test_strategy_evolution_service.py tests/test_strategy_hypothesis_backtest_service.py tests/test_daily_review_service.py tests/test_reference_seed.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** shadow research can inform future proposals but cannot directly change active strategy, trades, positions, timers, or broker behavior.

## Parallelization Notes

- M75, M76, M77, and M78 can run in parallel if they keep file ownership separated.
- M76 and M77 should coordinate payload naming for evidence coverage fields.
- M78 must not reuse M75 daily ops apply paths for shadow promotion.
- None of these tasks should enable the production timer or perform irreversible trading actions.
