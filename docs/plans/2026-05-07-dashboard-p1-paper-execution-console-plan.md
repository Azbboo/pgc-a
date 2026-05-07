# Dashboard P1 Paper Execution Console Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the DEV10 Dashboard from a P0 operations shell into a paper execution console that supports pre-open plan review, plan cancellation, buy execution recording, and exit workflow review without bypassing application services.

**Architecture:** Keep the Dashboard as an API-only client. Backend work adds or enriches service-backed API contracts; frontend work consumes `/api/*` only and never reads SQLite or local data files. Real order placement remains out of scope: the app records manual paper executions and explicit cancellations only.

**Tech Stack:** Python 3, SQLite, FastAPI route adapters, unittest/pytest, static HTML/CSS/JS Dashboard, existing `pgc_trading.services.*`.

---

## Coordination Rules

- Do not mutate `data/pgc_trading.db` in development tasks. Use temp DBs or fakes in tests.
- Do not commit secrets, tokens, broker credentials, server passwords, or `.env` values.
- CLI/API/Dashboard must call Application Services, not write tables directly.
- Only one frontend worker should own `web/dashboard/index.html`, `web/dashboard/styles.css`, and `web/dashboard/app.js` at a time unless a prior refactor creates clean module boundaries.
- Each worker should use a branch with prefix `codex/`, for example `codex/dashboard-p1a-api-plan-generate`.
- Each worker final report must include changed files, tests run, screenshots if UI, and open risks.

## Parallel Map

| Work Package | Can Run In Parallel? | Depends On | Write Ownership | Purpose |
| --- | --- | --- | --- | --- |
| P1A API Plan Generation + Plan Detail | yes | none | API routes, planning DTO/tests | Make Dashboard able to generate/inspect plans through HTTP contracts |
| P1B Dashboard Execution UX | yes, but only one frontend owner | none for layout; integrate P1A after merge | `web/dashboard/*`, `tests/test_dashboard_static.py` | Build pre-open plan review, cancellation, and execution ergonomics |
| P1C CLI Plan Cancel Safety Valve | yes | none | CLI/tests/README/runbook only | Add a non-UI fallback for cancelling active/draft plans |
| P1D Real-DB Paper Runbook Update | yes after P1B draft; low conflict if docs-only | P1B final wording preferred | docs/reports only | Document paper execution day workflow |
| P1E Integration Smoke + Review Gate | no | P1A + P1B + optional P1C | tests only unless fixes needed | Verify API + Dashboard + CLI surface together |

Recommended first wave: run P1A, P1B, and P1C in separate sessions. Hold P1E for supervisor review after those branches are ready.

## P1A: API Plan Generation + Plan Detail

**Priority:** P0

**Goal:** Add the missing HTTP contract for standalone buy-plan generation and enrich plan read responses enough for the Dashboard execution console.

**Files:**

- Modify: `src/pgc_trading/api/routes.py`
- Modify if needed: `src/pgc_trading/api/services.py`
- Modify: `src/pgc_trading/services/portfolio_planning_service.py`
- Test: `tests/test_api_write_routes.py`
- Test: `tests/test_api_read_routes.py`

**Required behavior:**

- Add `POST /api/trade-plans/generate`.
- Payload fields:
  - `account_key`, `account_id`
  - `daily_pick_id`
  - `review_date` or `as_of_date`
  - `planned_trade_date`
  - `agent_decision_id`
  - `dry_run`, `operator`, `idempotency_key`, `request_id`
- Route must call `PortfolioPlanningService.generate_buy_plan`.
- Dry-run is allowed and must not write plans.
- Non-dry requires `PGC_API_ENABLE_WRITES=1`, `operator`, and `idempotency_key`.
- Live account non-dry remains blocked by the service.
- Enrich `TradePlanDTO` or list response so Dashboard can show, when available:
  - `daily_pick_id`
  - `signal_id`
  - `planned_cash`
  - `planned_shares`
  - `ts_code`
  - `name`
  - `operator`
  - `created_at`

**Focused tests:**

```bash
PYTHONPATH=src python3 -m unittest tests.test_api_write_routes tests.test_api_read_routes
```

**Acceptance criteria:**

- API tests prove dry-run generation returns `trade_plan_id=None`.
- API tests prove non-dry generation writes one plan when writes are enabled.
- API tests prove writes-disabled and missing operator/idempotency are rejected.
- Read endpoint still does not import `sqlite3` from API routes.

## P1B: Dashboard Execution UX

**Priority:** P0

**Goal:** Make the Dashboard usable for the paper trading day: inspect active plan, cancel/skip safely, record actual buy execution, and review due exit tasks.

**Files:**

- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/styles.css`
- Modify: `web/dashboard/app.js`
- Test: `tests/test_dashboard_static.py`

**Required UX:**

- Add a first-screen “开盘执行” or strengthened “交易计划” area showing:
  - today active buy plans
  - planned date
  - action/status
  - stock code/name if API provides it
  - planned shares/cash if API provides it
  - data-quality blocker state
- Add a pre-open checklist with visible boolean items:
  - not suspended
  - no major bad news
  - open not extremely high
  - cash/slots checked
  - plan date is today
- Add cancel flow:
  - available for `draft`/`active`
  - reason required
  - common reason quick choices: `高开过大`, `停牌/不可交易`, `重大利空`, `人工跳过`
  - call `/api/trade-plans/{id}/cancel`
  - never dry-run cancel because API does not support dry-run cancel
- Improve buy execution form:
  - selecting an active buy plan auto-fills plan id, side buy, planned date, planned shares when available
  - requires actual executed price and shares
  - calls `/api/trades`
  - displays that no broker order is placed
- Improve exit queue visibility:
  - due T+2/T+5 positions are above ordinary holdings
  - `evaluate exits` button is clear that it generates decisions/plans, not sell executions

**Design constraints:**

- No landing page or marketing copy.
- Dense workstation layout; no decorative hero/cards.
- No direct SQLite/file reads in JS.
- Text must fit on mobile and desktop.

**Focused tests:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src python3 -m unittest tests.test_dashboard_static
```

**Acceptance criteria:**

- Static test proves the new checklist, cancel reason options, `/cancel`, `/api/trades`, and advisory/no-order labels exist.
- Buttons disable correctly when data quality has blockers or no active plan exists.
- UI remains API-only.

## P1C: CLI Plan Cancel Safety Valve

**Priority:** P1 but safe to parallelize

**Goal:** Provide a CLI fallback for canceling a paper plan before open, matching the Dashboard cancel behavior.

**Files:**

- Modify: `src/pgc_trading/cli/main.py`
- Modify: `tests/test_cli_main.py`
- Modify: `README.md`
- Modify: `reports/operational_runbook_design.md`

**Required behavior:**

- Add command:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main plan-cancel \
  --plan-id 1 \
  --reason 高开过大 \
  --db-path data/pgc_trading.db \
  --account paper-main \
  --operator azboo
```

- Command calls `PortfolioPlanningService.cancel_plan`.
- Missing DB returns nonzero and does not create a DB.
- Reason is required.
- Account selector is passed through.
- Output includes plan id, status, cancel reason.

**Focused tests:**

```bash
PYTHONPATH=src python3 -m unittest tests.test_cli_main
```

**Acceptance criteria:**

- CLI tests cover success routing, missing DB, and missing reason.
- No direct DB writes from CLI.

## P1D: Paper Execution Runbook Update

**Priority:** P1

**Goal:** Make the actual paper day procedure obvious enough that the user can follow it without guessing.

**Files:**

- Modify: `README.md`
- Modify: `reports/operational_runbook_design.md`
- Modify: `reports/api_cli_contract_design.md` only if API contracts change in P1A

**Required content:**

- Daily close previous day:
  - `daily-close` preview
  - `daily-close --apply`
- Before open:
  - inspect active plan in Dashboard
  - cancel if needed
- After manual paper buy:
  - record actual buy execution
- After close on T+2/T+5:
  - evaluate exits
  - record sell only after actual manual sell

**Acceptance criteria:**

- Docs do not claim automatic broker ordering exists.
- Docs do not document live `--apply`.
- Commands match current CLI/API names.

## P1E: Integration Smoke + Review Gate

**Priority:** P0 final gate

**Goal:** Review merged P1 work as a coherent operator workflow.

**Files:**

- Prefer tests only unless fixing discovered issues.

**Commands:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src python3 -m unittest tests.test_dashboard_static tests.test_api_read_routes tests.test_api_write_routes tests.test_cli_main
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m pytest -q
python3 -m compileall -q src tests
git diff --check
rg -n "(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{35}|AKIA[0-9A-Z]{16}|xox[baprs]-[0-9A-Za-z-]{10,}|-----BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----)" . --glob '!data/backups/**' --glob '!.env' --glob '!*.pyc'
```

**Dashboard manual smoke:**

- Start API with writes disabled first.
- Verify Dashboard loads.
- Verify non-dry writes are blocked.
- Start API with `PGC_API_ENABLE_WRITES=1` on a temp DB for write smoke.
- Verify cancel/record/evaluate calls show service envelopes.

**Acceptance criteria:**

- All tests pass.
- No real secrets found.
- No worker modified `data/pgc_trading.db`.
- Dashboard remains API-only.
- Paper execution workflow is usable without direct DB edits.
