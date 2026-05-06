# PGC Development Supervision Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement each assigned work package task-by-task.

**Goal:** Move the PGC system from completed P0 backend skeleton into a usable daily close review and paper-trading workflow.

**Architecture:** Continue as a modular monolith. All CLI, API, and future Dashboard surfaces must call Application Services instead of writing database tables directly. Strategy signals, daily picks, trade plans, executions, positions, Agent advisory, and data quality events stay in separate bounded tables and service modules.

**Tech Stack:** Python 3, SQLite for local canonical store, unittest, Tushare adapter, optional MySQL/Redis integration for test-server sync, Open Design prototype for UI exploration.

---

## 1. Current Status

As of 2026-05-06:

- WP0-WP12 are complete in `docs/plans/2026-05-04-pgc-parallel-task-supervision.md`.
- Current quality gate passed:
  - `python3 -m unittest discover -s tests`: 64 tests OK.
  - `compileall`: OK.
  - known Tushare token prefix scan: no matches.
- Target SQLite migrations `001-009` exist and pass tests on temp databases.
- Core service skeletons exist under `src/pgc_trading/services/`.
- The real database `data/pgc_trading.db` must not be mutated unless the user explicitly approves.
- Dashboard prototype is exploratory only. Production Dashboard must wait until CLI/service workflow is stable.

## 2. Development Direction

The next milestone is not a full web app. The next milestone is:

```text
Daily close review CLI v0.1:
after market close, run checks, produce one next-day candidate, generate a buy plan draft, and output a human-readable report.
```

Principles:

- CLI/service workflow first, Dashboard later.
- Real external calls must not run inside long SQLite transactions.
- No real secret, token, server password, or broker credential may be committed.
- Every write operation must be idempotent or explicitly guarded.
- Data quality blockers outrank scores, returns, Agent advice, and UI convenience.
- TradingAgents remains advisory only.

## 3. Test Server Record

This section records only non-sensitive infrastructure facts for coordination. Do not commit plaintext credentials.

| Item | Value |
| --- | --- |
| SSH host | `150.158.121.150` |
| SSH user | `root` |
| SSH password | Provided by user in chat; do not write to repo, docs, tests, logs, or fixtures. |
| MySQL host | `150.158.121.150` |
| MySQL database | `dbeeda2c6c6d9a31` |
| MySQL user/password | Not confirmed; treat as secret runtime config. |
| Redis | Available on test server; host/port/auth not yet confirmed. |

Runtime secret handling:

- Put real values only in ignored local files such as `.env` or `.env.test-server`.
- `.gitignore` already ignores `.env` and `.env.*`.
- `.env.example` may include placeholders only.
- Before every handoff or commit, run a token/secret scan.

Suggested local-only environment keys:

```bash
PGC_TEST_SSH_HOST=150.158.121.150
PGC_TEST_SSH_USER=root
PGC_TEST_SSH_PASSWORD=<local-only-secret>
PGC_TEST_MYSQL_HOST=150.158.121.150
PGC_TEST_MYSQL_DATABASE=dbeeda2c6c6d9a31
PGC_TEST_MYSQL_USER=<local-only-secret>
PGC_TEST_MYSQL_PASSWORD=<local-only-secret>
PGC_TEST_REDIS_HOST=150.158.121.150
PGC_TEST_REDIS_PORT=6379
PGC_TEST_REDIS_PASSWORD=<local-only-secret-or-empty>
```

## 4. Master Progress Board

| Work Package | Status | Dependency | Owner Scope | Primary Output |
| --- | --- | --- | --- | --- |
| DEV0 Baseline Commit & Tracking | done | WP0-WP12 | git/docs only | clean baseline commit and status board |
| DEV1 CLI Command Skeleton | done | DEV0 | CLI package/tests | `pgc` command entrypoints |
| DEV2A CPB V2 Strategy Integration | todo | DEV0, WP11 | strategies/features/seed/tests | `cpb_v2@2026-05-06` candidate strategy |
| DEV2 DailyCloseWorkflowService | todo | WP8-WP12 | services/workflow/tests | one-call daily close orchestration |
| DEV3 Daily Review Report Output | todo | DEV2 | reporting/templates/tests | Markdown/JSON daily report |
| DEV4 Tushare Runtime Adapter Hardening | todo | WP10 | market adapter/config/tests | env-driven real fetch guardrails |
| DEV5 Execution Recording CLI | todo | DEV1, WP12 | CLI + portfolio services/tests | record buy/sell execution safely |
| DEV6 Position Exit Decision CLI | todo | DEV5 | position lifecycle/tests | T+2/T+5 review commands |
| DEV7 Replay & Golden Regression | todo | DEV2-DEV6 | tests/fixtures/replay | no-future replay gate |
| DEV8 Test Server Sync POC | todo | DEV3, DEV7 | scripts/adapters/docs | optional MySQL/Redis sync, no secrets |
| DEV9 HTTP API P0 | deferred | DEV1-DEV7 | API layer/tests | service-backed API |
| DEV10 Dashboard P0 | deferred | DEV9 | frontend/API only | production Dashboard |

## 5. Work Packages

### DEV0: Baseline Commit & Tracking

**Priority:** P0

**Goal:** Make the current repository state reviewable before more parallel work begins.

**Files:**

- Modify: `docs/plans/2026-05-06-pgc-development-supervision-plan.md`
- No code changes.

**Scope:**

- Run full test gate.
- Run compile check.
- Run token/secret scan.
- Review `git status --short`.
- Commit current baseline only after user approval.

**Out of scope:**

- No feature development.
- No database migration on `data/pgc_trading.db`.
- No server connection.

**Commands:**

```bash
PYTHONPATH=/Users/azboo/Desktop/Person/pgc/src python3 -m unittest discover -s /Users/azboo/Desktop/Person/pgc/tests
PYTHONPATH=/Users/azboo/Desktop/Person/pgc/src python3 -m compileall -q /Users/azboo/Desktop/Person/pgc/src /Users/azboo/Desktop/Person/pgc/tests
if [ -n "${PGC_TOKEN_SCAN_PREFIX:-}" ]; then rg -n "$PGC_TOKEN_SCAN_PREFIX" /Users/azboo/Desktop/Person/pgc --glob '!data/backups/**'; fi
rg -n "(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{35}|AKIA[0-9A-Z]{16}|xox[baprs]-[0-9A-Za-z-]{10,}|-----BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----)" /Users/azboo/Desktop/Person/pgc --glob '!data/backups/**' --glob '!.env' --glob '!*.pyc'
git status --short
```

**Acceptance criteria:**

- Tests pass.
- Compile passes.
- No plaintext secret appears in tracked files.
- Baseline can be committed cleanly.

**DEV0 execution record (2026-05-06):**

- `unittest discover`: passed, 82 tests.
- `compileall`: passed with no output.
- Secret scan: no common plaintext secret pattern matches; token prefix scan skipped because `PGC_TOKEN_SCAN_PREFIX` was not set.
- `git status --short`: reviewed before initial baseline commit.

### DEV1: CLI Command Skeleton

**Priority:** P0

**Goal:** Create a stable `pgc` CLI surface that calls service-layer functions.

**Files:**

- Create: `src/pgc_trading/cli/__init__.py`
- Create: `src/pgc_trading/cli/main.py`
- Create: `tests/test_cli_main.py`
- Modify only if necessary: `README.md`, `.env.example`

**Commands to support first:**

```bash
pgc --help
pgc review --date 2026-05-04 --db-path /private/tmp/pgc_cli.db
pgc report --date 2026-05-04 --db-path /private/tmp/pgc_cli.db
```

**Implementation notes:**

- Use standard library `argparse` unless a CLI dependency already exists.
- CLI must not write tables directly.
- CLI should parse ISO dates and normalize internally to project trading date format.
- CLI should accept `--db-path` for temp DB tests.

**Acceptance criteria:**

- Help output includes `review`, `plan`, `report`, `record-buy`, `record-sell`, `positions`.
- Initial commands can be no-op or call existing skeletons, but command routing must be tested.
- Invalid date exits nonzero with a clear message.

### DEV2: DailyCloseWorkflowService

**Priority:** P0

**Goal:** Provide one Application Service that orchestrates daily close review without crossing domain boundaries.

**Files:**

- Create: `src/pgc_trading/services/daily_close_workflow_service.py`
- Create: `tests/test_daily_close_workflow_service.py`
- Modify if needed: `src/pgc_trading/services/__init__.py`

**Workflow:**

1. Check database invariants.
2. Check data quality for review date and next trading date.
3. Ensure market data availability.
4. Run daily review service.
5. Select at most one daily candidate.
6. Ask portfolio planning service to create a buy plan draft only if data quality allows it.
7. Return a structured result with report-ready fields.

**Out of scope:**

- No TradingAgents call.
- No HTTP API.
- No Dashboard.
- No direct table writes outside downstream services.

**Acceptance criteria:**

- Data quality blocker prevents plan creation.
- No candidate produces a clear no-pick result.
- One candidate with capacity produces one draft/active buy plan, depending existing service contract.
- Re-running for same date is idempotent or clearly returns existing result.

### DEV3: Daily Review Report Output

**Priority:** P0

**Goal:** Produce human-readable Markdown and machine-readable JSON after each daily close review.

**Files:**

- Create: `src/pgc_trading/reporting/__init__.py`
- Create: `src/pgc_trading/reporting/daily_report.py`
- Create: `tests/test_daily_report.py`
- Modify: `src/pgc_trading/cli/main.py`

**Report must show:**

- review date and next trading date;
- data check result: can trade, warning, or blocked;
- one candidate or explicit no-candidate state;
- why it was selected over other signals;
- buy plan status;
- current positions needing buy-after-day-2 or buy-after-day-5 decisions;
- advisory note placeholder, clearly not automatic trading.

**Acceptance criteria:**

- Markdown contains no database-field jargon in user-facing headings.
- JSON preserves stable keys for future API/Dashboard use.
- Report command can write to `reports/live_trade_plan.md` only when user asks; tests write under temp paths.

### DEV4: Tushare Runtime Adapter Hardening

**Priority:** P0

**Goal:** Make real market fetching safe, explicit, and environment-driven.

**Files:**

- Modify: `src/pgc_trading/market/tushare_adapter.py`
- Modify: `src/pgc_trading/services/market_data_service.py`
- Create or modify: `tests/test_tushare_adapter_config.py`

**Scope:**

- Read token from environment only.
- Refuse real fetch when token is missing.
- Keep mock adapter path for tests.
- Never print token.
- Add request/run records around external calls, not inside long DB transactions.

**Acceptance criteria:**

- Missing token gives clear error.
- Tests do not require network.
- Token prefix scan remains clean.

### DEV5: Execution Recording CLI

**Priority:** P0

**Goal:** Allow manual recording of buy/sell executions after paper trades.

**Files:**

- Modify: `src/pgc_trading/cli/main.py`
- Modify only through service contract if needed: `src/pgc_trading/services/execution_recording_service.py`
- Create: `tests/test_cli_execution_recording.py`

**Commands:**

```bash
pgc record-buy --plan-id 101 --date 2026-05-05 --price 10.50 --shares 6600 --db-path /private/tmp/pgc_cli.db
pgc record-sell --position-id 88 --date 2026-05-07 --price 10.92 --shares 6600 --db-path /private/tmp/pgc_cli.db
```

**Acceptance criteria:**

- Buy execution creates or updates position via service layer.
- Sell execution reduces/closes position via service layer.
- Invalid plan or share count fails safely.
- Account isolation is enforced.

### DEV6: Position Exit Decision CLI

**Priority:** P0

**Goal:** Surface buy-after-day-2 and buy-after-day-5 decisions for current positions.

**Files:**

- Modify: `src/pgc_trading/cli/main.py`
- Modify if needed: `src/pgc_trading/services/position_lifecycle_service.py`
- Create: `tests/test_cli_position_decisions.py`

**Commands:**

```bash
pgc positions --date 2026-05-07 --db-path /private/tmp/pgc_cli.db
pgc exits-evaluate --date 2026-05-07 --db-path /private/tmp/pgc_cli.db
```

**Acceptance criteria:**

- Explicit calendar dates are shown, not only T+2/T+5 shorthand.
- Generated exit plan is traceable to position and account.
- No sell execution is recorded unless user runs record-sell.

### DEV7: Replay & Golden Regression

**Priority:** P0

**Goal:** Prove the daily workflow does not use future data and remains stable on known fixtures.

**Files:**

- Create: `tests/test_daily_workflow_replay.py`
- Create fixtures only under: `tests/fixtures/replay/`

**Acceptance criteria:**

- Replay uses only data visible by the review date.
- Golden result includes selected candidate, planned date, and no-future proof fields.
- Changing strategy inputs changes hash or fails test.

### DEV8: Test Server Sync POC

**Priority:** P1

**Goal:** Explore syncing selected derived datasets or reports to test-server MySQL/Redis without making them the source of truth.

**Files:**

- Create: `scripts/sync_reports_to_test_server.py`
- Create: `docs/plans/2026-05-06-test-server-sync-notes.md`
- Create: `tests/test_test_server_sync_config.py`

**Scope:**

- Read MySQL/Redis config from environment only.
- Do not depend on real network in unit tests.
- SQLite remains canonical local store.
- MySQL/Redis are test-server integration targets only.

**Out of scope:**

- No production deployment.
- No plaintext password.
- No Dashboard dependency.

**Acceptance criteria:**

- Missing env vars fail with clear instructions.
- Dry-run prints target host/database without passwords.
- Unit tests use fake clients.

## 6. Handoff Template For New Development Sessions

Use this prompt when opening a new development conversation:

```text
你负责 PGC 项目的 <DEVx 工作包名称>。

请先阅读：
- /Users/azboo/Desktop/Person/pgc/docs/plans/2026-05-06-pgc-development-supervision-plan.md
- /Users/azboo/Desktop/Person/pgc/docs/plans/2026-05-04-pgc-parallel-task-supervision.md
- /Users/azboo/Desktop/Person/pgc/reports/implementation_baseline_20260504.md
- 与本工作包相关的 reports/*.md

硬性要求：
- 只改本工作包拥有的文件。
- 不修改真实 data/pgc_trading.db。
- 不把 token、服务器密码、MySQL 密码、Redis 密码写进代码、文档、测试、日志或 fixture。
- 写库逻辑必须走 service 层。
- 完成后汇报 changed files、commands、test summary、open risks。

当前工作包：
<粘贴 DEVx 小节>
```

## 7. Supervisor Checklist

Each returned work package must be reviewed for:

- file ownership respected;
- tests added or updated;
- full test suite still passes;
- no plaintext secrets;
- no direct DB writes from CLI/API/Dashboard;
- no mutation of `data/pgc_trading.db`;
- data quality blocker behavior preserved;
- Agent advisory does not affect signal/plan tables unless explicitly modeled as advisory reference;
- T+2/T+5 shown with explicit trading dates.

Project-level gate:

```bash
PYTHONPATH=/Users/azboo/Desktop/Person/pgc/src python3 -m unittest discover -s /Users/azboo/Desktop/Person/pgc/tests
PYTHONPATH=/Users/azboo/Desktop/Person/pgc/src python3 -m compileall -q /Users/azboo/Desktop/Person/pgc/src /Users/azboo/Desktop/Person/pgc/tests
if [ -n "${PGC_TOKEN_SCAN_PREFIX:-}" ]; then rg -n "$PGC_TOKEN_SCAN_PREFIX" /Users/azboo/Desktop/Person/pgc --glob '!data/backups/**'; fi
rg -n "(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{35}|AKIA[0-9A-Z]{16}|xox[baprs]-[0-9A-Za-z-]{10,}|-----BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----)" /Users/azboo/Desktop/Person/pgc --glob '!data/backups/**' --glob '!.env' --glob '!*.pyc'
```

Expected:

- tests OK;
- compile command has no output and exit code 0;
- secret scan has no matches in tracked project files.

## 8. Immediate Recommendation

Start with:

```text
DEV0 Baseline Commit & Tracking
```

Then run separate development sessions:

```text
DEV1 CLI Command Skeleton
DEV2A CPB V2 Strategy Integration
DEV2 DailyCloseWorkflowService
```

DEV1 and DEV2A can proceed in parallel if they avoid touching shared service files. Prefer finishing DEV2A before DEV2 if the first daily workflow should support the new CPB V2 strategy from day one.
