# M100-M103 Chinese Ops Quality Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the current post-M99 system into a Chinese-first, operator-readable daily workflow where Dashboard pages, full-market review, daily data intake, and shadow-strategy decisions all explain "what happened, why it matters, what to do next" without exposing raw English contracts as the primary UI.

**Architecture:** Keep the existing safety boundary: market review, TradingAgents, strategy evolution, and shadow strategy outputs remain advisory unless a later task explicitly enables write behavior. Split the work into parallel-safe lanes with disjoint primary write sets so child sessions can execute without drifting into their own plans. Every task must update this ledger when completed and must keep API/internal contract keys stable while translating user-facing labels.

**Tech Stack:** Python services and CLI, SQLite, FastAPI read routes, static Dashboard JavaScript/CSS, Markdown/JSON reports, pytest/unittest, `node --check`, existing remote deploy and health scripts.

---

## Coordination Rules

- Start each child session by reading this plan and `docs/plans/global-task-ledger.md`.
- Do not add new task IDs without updating `docs/plans/global-task-ledger.md`.
- Keep write scopes disjoint. If a task needs to touch another lane's primary files, stop and ask the review session to coordinate.
- Do not enable strategy promotion, trade execution, paper/live mutation, broker actions, or timer activation.
- User-facing Dashboard/report text should be Chinese-first. Internal API keys, artifact contracts, and database column names may remain English but must be translated at display boundaries.
- Every lane must run `git diff --check` and its lane-specific tests before review.

## Parallel Map

| Lane | Task | Can Run In Parallel | Primary Write Scope | Review Focus |
| --- | --- | --- | --- | --- |
| A | M100 Dashboard Chinese IA and detail surfaces | Yes, except with other Dashboard tasks | `web/dashboard/*`, `tests/test_dashboard_static.py` | Remaining English, flat layout, drawer/modal readability, no write-safety regression |
| B | M101 Full-market review narrative depth | Yes | `src/pgc_trading/services/market_review_service.py`, `src/pgc_trading/reporting/daily_report.py`, market-review tests/reports | Sector-to-stock reasoning, news/sentiment/evidence continuity, no fabricated evidence |
| C | M102 Daily data and stock-pool intake operating loop | Yes | `scripts/run_daily_pipeline.sh`, `src/pgc_trading/services/daily_pipeline_service.py`, CLI/pipeline tests/runbook | One repeatable daily path, duplicate-write guard, operator/idempotency clarity |
| D | M103 Shadow strategy decision governance | Yes | `src/pgc_trading/services/shadow_observation_service.py`, `src/pgc_trading/services/strategy_evolution_service.py`, shadow scripts/tests/reports | Promotion readiness, stop rules, manual decision package, advisory-only boundary |

## M100: Dashboard Chinese IA And Detail Surfaces

**Goal:** Make the Dashboard understandable without reading English domain keys, and reduce the "everything is flat" feeling by moving dense details into consistent drawers/modals.

**Files:**
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/styles.css`
- Test: `tests/test_dashboard_static.py`

**Steps:**

1. Add or extend static tests that fail on visible English regressions in key Dashboard surfaces.
   - Assert Chinese labels for execution, daily review history, full-market review, evidence ledger, paper acceptance, TradingAgents, strategy workbench, Shadow Lab, decision memo, and detail drawer titles.
   - Allow English only for API paths, code keys inside `data-*`, and known artifact contract constants.
   - Run: `PYTHONPATH=src:. pytest -q tests/test_dashboard_static.py`
   - Expected: fails before implementation if visible English remains unhandled.

2. Centralize display translation for raw keys.
   - Extend existing helpers in `web/dashboard/app.js` such as `uiLabelText()`, `uiValueText()`, `sourceRefText()`, candidate-name helpers, status helpers, and table/detail row rendering.
   - Add translations for any remaining visible raw keys found during the audit: provider/source/status fields, shadow evidence fields, market diagnostics, action-log fields, and ops history fields.
   - Keep internal object keys unchanged.

3. Improve dense detail surfaces.
   - Reuse the existing detail drawer/modal pattern rather than adding isolated one-off markup.
   - Dense JSON-like blocks should become Chinese section cards: "结论", "证据", "阻断原因", "下一步", "来源".
   - Preserve keyboard/accessibility basics already present in the Dashboard.

4. Polish layout where pages still read as flat lists.
   - Convert repeated full-width loose sections into grouped panels, tabs, or drawers only inside `web/dashboard/*`.
   - Keep data-dense operational pages restrained; do not introduce marketing-style hero sections or decorative backgrounds.

5. Verify.
   - Run: `node --check web/dashboard/app.js`
   - Run: `PYTHONPATH=src:. pytest -q tests/test_dashboard_static.py`
   - Run: `git diff --check`
   - Optional browser verification if UI changed materially: open `http://127.0.0.1:8000/dashboard/` or the current dev server and check desktop/mobile screenshots.

## M101: Full-Market Review Narrative Depth

**Goal:** Make full-market review answer the operator's real questions: which regime, which sectors have continuity, which stocks represent them, what evidence supports it, what is missing, and how it connects to the next trading-day plan.

**Files:**
- Modify: `src/pgc_trading/services/market_review_service.py`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `tests/test_market_review_service.py`
- Modify: `tests/test_daily_report.py`
- Modify or regenerate: `reports/daily_review_*.json`, `reports/daily_review_*.md` only when the test fixture/report path requires it.

**Steps:**

1. Add tests for a Chinese narrative layer in the market review payload/report.
   - Expected fields: regime conclusion, sector ranking reason, representative stock reason, evidence freshness, evidence gaps, continuity judgement, next-day plan relationship.
   - Missing news/sentiment/sector evidence must be rendered as explicit "缺失/不可用/证据不足", never silently positive.

2. Implement the narrative assembler in `market_review_service.py`.
   - Use existing market-review runs, sector data, external evidence coverage, and plan-context fields.
   - Do not fetch live web data.
   - Do not invent news or sentiment; summarize only stored/imported evidence and explicit unavailable states.

3. Surface the narrative in `daily_report.py`.
   - Add concise Markdown sections: "全市场结论", "板块持续性", "代表个股", "证据缺口", "与明日计划关系".
   - Preserve existing JSON fields so current Dashboard routes do not break.

4. Verify.
   - Run: `PYTHONPATH=src:. pytest -q tests/test_market_review_service.py tests/test_daily_report.py`
   - Run: `PYTHONPATH=src:. pytest -q tests/test_api_read_routes.py` if API payload shape changes.
   - Run: `git diff --check`

## M102: Daily Data And Stock-Pool Intake Operating Loop

**Goal:** Make "每日复盘 + 新股票数据入池" a single repeatable operating loop with preflight, dry-run, apply, audit, and re-run guards that a separate daily session can execute safely.

**Files:**
- Modify: `scripts/run_daily_pipeline.sh`
- Modify: `src/pgc_trading/services/daily_pipeline_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `tests/test_daily_pipeline_script.py`
- Modify: `tests/test_daily_pipeline_service.py`
- Modify: `tests/test_cli_daily_pipeline.py`
- Modify: `reports/operational_runbook_design.md`
- Test: `tests/test_operational_runbook_static.py`

**Steps:**

1. Add tests for a clear daily operating state machine.
   - States should include: data refresh needed, evidence pack needed, pool intake pending, dry-run ready, apply blocked, apply complete, duplicate apply blocked.
   - Non-dry-run writes must require operator and idempotency/write-token rules already used by the project.

2. Extend the pipeline summary output.
   - Emit Chinese summary lines and JSON fields that tell the operator: "今天是否能跑", "缺什么", "下一步命令", "是否会写库".
   - Keep script stdout parseable for existing tests.

3. Add stock-pool intake linkage.
   - If pool intake artifacts exist, surface count, rejected count, dedupe count, and audit path in the daily pipeline result.
   - Do not silently add symbols without source/reason/event-date validation.

4. Update runbook.
   - Document the exact daily sequence for a child session: backup, fetch/import, preflight, dry-run, apply, report, health.
   - Include failure recovery and duplicate apply handling.

5. Verify.
   - Run: `bash -n scripts/run_daily_pipeline.sh`
   - Run: `PYTHONPATH=src:. pytest -q tests/test_daily_pipeline_script.py tests/test_daily_pipeline_service.py tests/test_cli_daily_pipeline.py tests/test_operational_runbook_static.py`
   - Run: `git diff --check`

## M103: Shadow Strategy Decision Governance

**Goal:** Turn the shadow-strategy lab from "many artifacts" into a governed decision queue with explicit readiness, required human decision, stop rules, next experiment, and rollback boundaries.

**Files:**
- Modify: `src/pgc_trading/services/shadow_observation_service.py`
- Modify: `src/pgc_trading/services/strategy_evolution_service.py`
- Modify: `scripts/monitor_shadow_strategies.py`
- Modify: `scripts/build_shadow_experiment_registry.py`
- Modify: `tests/test_shadow_observation_service.py`
- Modify: `tests/test_strategy_evolution_service.py`
- Modify: `tests/test_shadow_strategy_monitor_script.py`
- Modify: `tests/test_shadow_experiment_registry_script.py`
- Modify or regenerate: `reports/shadow_*_20260513.json`, `reports/shadow_*_20260513.md` as needed.

**Steps:**

1. Add tests for a decision queue.
   - Each candidate should have: current readiness, evidence status, walk-forward sufficiency, experiment status, required human decision, stop rule, next review date, and promotion boundary.
   - `promotion_allowed` must remain false unless a separate approved promotion task changes the contract.

2. Implement a normalized decision queue payload.
   - Reuse scorecard, dossier, review request, replay evidence, walk-forward outcomes, and experiment registry.
   - Output should be Chinese-first in summaries while keeping artifact contract keys stable.

3. Connect monitor and registry artifacts.
   - Monitor output should reference the current experiment registry and stop rules.
   - Registry should reference latest observed outcomes and blockers without mutating active strategy params.

4. Verify safety boundaries.
   - Tests must assert no writes to strategy versions, trade plans, trades, positions, paper/live state, broker path, or timers.
   - Run direct script smoke for monitor/registry if fixtures allow.

5. Verify.
   - Run: `PYTHONPATH=src:. pytest -q tests/test_shadow_observation_service.py tests/test_strategy_evolution_service.py tests/test_shadow_strategy_monitor_script.py tests/test_shadow_experiment_registry_script.py`
   - Run: `python3 -m compileall -q src scripts`
   - Run: `git diff --check`

## Integration Review Gate

After all lanes complete:

1. Run focused checks for all touched lanes:
   - `node --check web/dashboard/app.js`
   - `bash -n scripts/run_daily_pipeline.sh`
   - `python3 -m compileall -q src scripts`
   - `PYTHONPATH=src:. pytest -q tests/test_dashboard_static.py tests/test_market_review_service.py tests/test_daily_report.py tests/test_daily_pipeline_script.py tests/test_daily_pipeline_service.py tests/test_cli_daily_pipeline.py tests/test_shadow_observation_service.py tests/test_strategy_evolution_service.py tests/test_shadow_strategy_monitor_script.py tests/test_shadow_experiment_registry_script.py tests/test_operational_runbook_static.py`
2. Run full suite:
   - `PYTHONPATH=src:. pytest -q`
3. Check release safety:
   - `git diff --check`
   - Confirm Dashboard/market/shadow outputs remain advisory unless a write task explicitly changes the boundary.
4. If clean, commit, push, deploy:
   - `git commit -m "Complete M100-M103 Chinese ops quality wave"`
   - `git push`
   - `bash scripts/deploy_remote.sh --release-tag pgc-v0.1.0-20260513-m100-m103-cn-ops-quality-r1`
   - `ssh root@150.158.121.150 "cd /opt/pgc/app && PYTHONPATH=src python3 -m pgc_trading.cli.main ops health --db-path /opt/pgc/data/pgc_trading.db --health-url http://127.0.0.1:8020/api/health --require-current-migrations"`

