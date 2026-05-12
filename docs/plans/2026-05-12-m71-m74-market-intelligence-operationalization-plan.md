# M71-M74 Market Intelligence Operationalization Plan

**Goal:** Turn the M67-M70 foundation into a daily usable market-intelligence loop: reviewed evidence closes visible gaps, market-review empty states explain themselves, shadow research becomes gated artifacts, and cockpit decisions get next-day outcome review.

**Architecture:** Keep market intelligence advisory unless a later explicit task changes that contract. Evidence must enter through reviewed cached provider files or explicit unavailable states. Shadow strategy work may create artifacts and comparison reports, but must not mutate active strategy params, trade plans, trades, positions, paper/live behavior, broker execution, or timer state.

**Tech Stack:** Python services and CLI, SQLite through `013_decision_action_log`, FastAPI read/write-guarded APIs, static Dashboard JavaScript/CSS, Markdown/JSON reports, pytest/unittest, remote deployment on port `8020`.

---

## Baseline

- M67-M70 are completed and scheduled for release `pgc-v0.1.0-20260512-m67-m70`.
- Remote migration target is `013_decision_action_log`.
- 2026-05-11 market review has regime, sectors, plan context, and hypotheses, but market/Agent external evidence remains explicitly missing unless reviewed provider files are imported.
- M69 research is shadow-only and must stay separate from active CPB behavior until replay/paper gates are passed.

## Parallel Work Map

| Track | Task | Status | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- | --- |
| M71 | Evidence pack execution and 20260511 external coverage closure | Done | Yes | M68 evidence packs, reviewed provider files | Session A |
| M72 | Market review data sync and empty-state diagnostics | Done | Yes | M41B/M48 Dashboard, M65 ops history | Session B |
| M73 | Shadow strategy promotion workbench | Done | Yes | M69 shadow reports, M64/M50 gates | Session C |
| M74 | Decision action outcome review and ops audit hardening | Done | After M70 response shapes | Session D |

## M71: Evidence Pack Execution And 20260511 External Coverage Closure

**Goal:** Close 20260511 market/Agent evidence gaps with reviewed cached provider files or explicit unavailable-source records.

**Expected scope:**
- Use `ops evidence-pack` output as the controlled source for market and Agent external evidence.
- Import/backfill only reviewed provider files; do not live-fetch in daily-close, report rendering, API, or Dashboard paths.
- Re-render reports so coverage states show available, partial, missing, or unavailable accurately.
- Keep missing news/sentiment explicit when no reviewed evidence exists.

**Acceptance commands:**

```bash
PYTHONPATH=src:. pytest -q tests/test_market_external_data_service.py tests/test_agent_external_data_service.py tests/test_cli_market_review.py tests/test_daily_report.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** no fabricated external evidence, no trading writes, and Dashboard/report coverage wording remains honest.

**M71 completion note:** Executed reviewed local-cache provider pack for `20260511` through `ops evidence-pack` with `evidence_provider_pack_v1`, copied audited market/Agent provider files into `.pgc-runs/m71-evidence-pack-20260512/pack/`, and applied only those copied files into `market_external_items` and `agent_external_items`. Market evidence inserted 4 fresh rows covering market/sector/stock, Agent evidence inserted 6 fresh cached rows covering fundamentals plus risk/research context, and absent announcement/news/sentiment provider files remain explicit as missing/unavailable rather than fabricated. Re-rendered `reports/daily_review_20260511.{json,md}` so paper evidence coverage passes with source refs while Agent review itself remains not-run. Verified with targeted M71 pytest, full `PYTHONPATH=src:. pytest -q`, and `git diff --check`.

## M72: Market Review Data Sync And Empty-State Diagnostics

**Goal:** Make the Dashboard explain why full-market panels are empty instead of leaving the operator guessing.

**Expected scope:**
- Add API/Dashboard diagnostics for selected market date, latest market-review date, API base, source DB freshness, and missing downstream tables.
- Add an ops check for local/remote market-review parity across `market_review_runs`, `sector_daily_snapshots`, `market_external_items`, `market_plan_contexts`, and `strategy_hypotheses`.
- Preserve read-only market-review UI.
- Keep latest-date navigation clear when localStorage pins an older date.

**Acceptance commands:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_api_read_routes.py tests/test_dashboard_static.py tests/test_operational_runbook_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** empty states identify root cause without hiding missing evidence or silently switching trading context.

**M72 completion note:** Added `diagnostics` to market-review detail payloads, a Dashboard all-market diagnostic strip showing API Base, selected/latest market dates, localStorage pinning, source DB freshness, downstream table counts and empty-state reasons, plus a read-only `pgc ops market-review-parity` check for local/remote parity across `market_review_runs`, `sector_daily_snapshots`, `market_external_items`, `market_plan_contexts`, and `strategy_hypotheses`. Runbook and static tests document the workflow. Verified with `node --check web/dashboard/app.js`, targeted M72 pytest, full `PYTHONPATH=src:. pytest -q`, and `git diff --check`.

## M73: Shadow Strategy Promotion Workbench

**Goal:** Convert M69 shadow research into a controlled workbench that can compare candidate ideas against frozen CPB.

**Expected scope:**
- Register M69 shadow outputs as artifact-only hypothesis candidates.
- Add replay/shadow comparison summaries for trend extension, breakout pressure, low-price momentum, pre-confirm watchlist, and dip-buy variants.
- Require explicit blockers before any paper observation or strategy-version proposal.
- Do not create or activate strategy params.

**Acceptance commands:**

```bash
PYTHONPATH=src:. pytest -q tests/test_strategy_evolution_service.py tests/test_strategy_hypothesis_backtest_service.py tests/test_daily_report.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** research artifacts only; no trade plans, no active params, no paper/live behavior mutation.

**M73 completion note:** Added `strategy-evolution register-shadow` to register M69 research outputs as artifact-only `strategy_hypotheses`, with replay/shadow comparison summaries for `trend_extension_shadow`, `breakout_pressure_shadow`, `low_price_momentum_shadow`, `preconfirm_watchlist`, and `pullback_dip_buy`. The strategy workbench now surfaces shadow comparison payloads plus explicit blocked gates for paper observation and strategy-version proposal; accepted shadow candidates stay research-only until blockers are cleared. Registered 5 local 20260511 shadow candidates in `data/pgc_trading.db`. Codex review restored the active CPB `min_entry_price=10.0`/params hash boundary and added regression coverage so shadow candidates cannot silently broaden the active strategy. Verified with targeted M73 pytest, full `PYTHONPATH=src:. pytest -q`, and `git diff --check`. No active strategy params, trade plans, trades, positions, paper/live behavior, broker execution, or timer state were changed.

## M74: Decision Action Outcome Review And Ops Audit Hardening

**Goal:** Make M70 action logs useful during the next review day and visible in ops history.

**Expected scope:**
- Surface action-log outcome review in report/API/Dashboard with matched, deferred, pending, and unexpected-trade states.
- Link action logs into ops history and release/audit trails.
- Improve Dashboard controls for reviewing followed/deferred/overrode decisions without cluttering execution flow.
- Keep trade execution in existing guarded endpoints only.

**Acceptance commands:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_decision_action_log_service.py tests/test_api_read_routes.py tests/test_daily_report.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

**Review focus:** action logs are advisory audit records and cannot place trades, enable timers, or mutate strategy state.

**M74 completion note:** Implemented local outcome-review hardening for decision action logs: outcome buckets/counts for matched, deferred, pending, unexpected, override, and review-only states; execution-date constrained trade matching; unexpected-trade detection; ops-history summaries/details for action-log audit records; and Dashboard outcome drill-down controls. Safety flags remain false for trade state, strategy state, and timer mutation. Verified with `node --check web/dashboard/app.js`, targeted M74 pytest, full `PYTHONPATH=src:. pytest -q` (`405 passed, 3 skipped, 10 subtests passed`), and `git diff --check`.

## Parallelization Notes

- M71, M72, and M73 can run in parallel.
- M74 can start in parallel if it only reads the M70 action-log shape; deeper integration should wait for any M72 ops-history shape changes.
- None of these tasks should enable the production timer or perform irreversible trading actions.
