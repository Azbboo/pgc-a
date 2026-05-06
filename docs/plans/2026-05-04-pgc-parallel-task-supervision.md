# PGC Parallel Implementation & Supervision Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split the PGC trading-system implementation into safe sub-conversation work packages while the main thread supervises progress, integration quality, and architectural boundaries.

**Architecture:** The project stays a modular monolith. Sub-conversations work on bounded slices with explicit file ownership, while the main thread reviews changes, runs quality gates, and prevents raw/market/strategy/agent/portfolio data from crossing layers.

**Tech Stack:** Python 3, SQLite, local `unittest`, project package under `src/pgc_trading`, Markdown design docs.

---

## Current State

Completed:

- M0 baseline record: `reports/implementation_baseline_20260504.md`
- `.env.example` with no real token
- `cpb_6157@2026-05-03` params and hash
- M1-001 migration runner: `src/pgc_trading/storage/migrate.py`
- Migration 001: `src/pgc_trading/storage/migrations/001_schema_quality.sql`
- Migration tests: `tests/test_migrations.py`

Current safety status:

- Real database has been backed up to `data/backups/pgc_trading_20260504_before_m0_m1.db`
- Real `data/pgc_trading.db` has not been formally migrated to target schema
- Existing database is prototype/legacy schema
- Next work must not mutate the real database except by explicit user instruction

## Coordination Rules

Each sub-conversation must:

- Read this plan first.
- Read `reports/implementation_baseline_20260504.md`.
- Read the relevant design doc listed in its task package.
- Touch only its owned file set.
- Use `apply_patch` for manual edits.
- Avoid real Tushare token in code, docs, tests, logs, and fixture.
- Use temporary SQLite paths under `/private/tmp` for tests and smoke checks.
- End with changed files, commands run, test output summary, open risks.

The main supervision thread must:

- Review every sub-conversation result before starting dependent tasks.
- Run the project-level quality gate.
- Check that write scopes were respected.
- Update the progress board in this file or a follow-up status document.
- Reject changes that make CLI/API/Dashboard bypass Application Services.

## Project-Level Quality Gate

Run after every integrated task:

```bash
PYTHONPATH=/Users/azboo/Desktop/Person/pgc/src python3 -m unittest discover -s /Users/azboo/Desktop/Person/pgc/tests
```

Expected:

```text
OK
```

Run compile check:

```bash
PYTHONPATH=/Users/azboo/Desktop/Person/pgc/src python3 -m compileall -q /Users/azboo/Desktop/Person/pgc/src /Users/azboo/Desktop/Person/pgc/tests
```

Expected: no output and exit code 0.

Run token check:

```bash
TOKEN_PREFIX='replace-with-known-token-prefix' rg -n "$TOKEN_PREFIX" /Users/azboo/Desktop/Person/pgc --glob '!data/backups/**'
```

Expected: no matches. `rg` may exit 1 when no matches are found; that is acceptable.

Run migration smoke on a temp database:

```bash
PYTHONPATH=/Users/azboo/Desktop/Person/pgc/src python3 -m pgc_trading.storage.migrate --db-path /private/tmp/pgc_supervision_smoke.db
```

Expected:

- command succeeds;
- output JSON lists newly applied migrations on first run;
- second run lists them as skipped.

Run SQLite integrity checks on temp database:

```bash
sqlite3 /private/tmp/pgc_supervision_smoke.db 'PRAGMA integrity_check;'
sqlite3 /private/tmp/pgc_supervision_smoke.db 'PRAGMA foreign_key_check;'
```

Expected:

- `integrity_check` returns `ok`;
- `foreign_key_check` returns no rows.

## Progress Board

| Work Package | Status | Dependency | Owner Scope |
| --- | --- | --- | --- |
| WP0 Baseline + M1-001 runner | done | none | config, baseline docs, migration runner |
| WP1 Legacy detector and backup helper | done | WP0 | storage migrators/tests |
| WP2 Legacy freeze dry-run | done | WP1 | storage migrators/tests |
| WP3 Target base DDL 002-004 | done | WP0 | SQL migrations/tests |
| WP4 Strategy/feature/signal DDL 005-006 | done | WP3 | SQL migrations/tests |
| WP5 Agent/portfolio/research DDL 007-009 | done | WP4 | SQL migrations/tests |
| WP6 Invariant checks | done | WP3-WP5 | invariant module/tests |
| WP7 Reference seed data | done | WP4 | seed service/tests |
| WP8 RawIngestionService P0 | done | WP3, WP6 | ingestion/service/tests |
| WP9 DataQualityService P0 | done | WP3, WP6 | service/repository/tests |
| WP10 MarketDataService adapter mock | done | WP3, WP9 | market/service/tests |
| WP11 DailyReviewService skeleton | done | WP4, WP8-WP10 | feature/strategy/service/tests |
| WP12 Portfolio plan/trade/position skeleton | done | WP5, WP11 | portfolio/service/tests |

## Wave 1: Storage Foundation

Wave 1 prepares safe migration of the existing prototype database. Do not implement raw import, strategy engine, Agent, or Dashboard in this wave.

### Task 1: Legacy Detector

**Files:**

- Create: `src/pgc_trading/storage/migrators/__init__.py`
- Create: `src/pgc_trading/storage/migrators/legacy_detector.py`
- Create: `tests/test_legacy_detector.py`

**Read:**

- `reports/database_migration_execution_design.md`
- `reports/implementation_baseline_20260504.md`

**Goal:** Detect whether a SQLite database is `empty`, `legacy`, `target`, or `mixed`.

**Implementation intent:**

- Inspect `sqlite_master`.
- Inspect columns with `PRAGMA table_info`.
- Legacy signals:
  - `raw_events` exists and lacks `import_batch_id`
  - `market_bars` exists and lacks `fetch_run_id`
  - `signals` exists
  - `trades` has `price` and lacks `executed_price`
  - `positions` lacks `entry_trade_id`
  - `exits` exists
- Target signals:
  - `raw_events` has `import_batch_id`
  - `market_bars` has `fetch_run_id`
  - `strategy_signals` exists
  - `exit_decisions` exists

**Acceptance criteria:**

- Empty temp DB returns `empty`.
- DB initialized with current `schema.sql` returns `legacy`.
- Hand-built DB with target marker tables returns `target`.
- DB with legacy and target markers returns `mixed`.
- No real project database is modified.

**Commands:**

```bash
PYTHONPATH=/Users/azboo/Desktop/Person/pgc/src python3 -m unittest /Users/azboo/Desktop/Person/pgc/tests/test_legacy_detector.py
```

Expected: `OK`.

**Supervisor review:**

- Confirm detector is read-only.
- Confirm no freeze or rename behavior is included yet.

### Task 2: Backup Helper

**Files:**

- Modify: `src/pgc_trading/storage/migrators/legacy_detector.py` only if needed for shared DTOs
- Create: `src/pgc_trading/storage/migrators/backup.py`
- Create: `tests/test_database_backup.py`

**Goal:** Create timestamped SQLite backups before any destructive or table-renaming migration step.

**Implementation intent:**

- Function: `backup_database(db_path: Path, backup_dir: Path | None = None, label: str = "before_migration") -> Path`
- Default backup dir: `db_path.parent / "backups"`
- Use `shutil.copy2`.
- Refuse to overwrite existing backup path.
- Raise clear error when source DB does not exist.

**Acceptance criteria:**

- Existing DB is copied.
- Backup path includes label.
- Missing source raises.
- Existing destination raises or generates a unique timestamp.

**Commands:**

```bash
PYTHONPATH=/Users/azboo/Desktop/Person/pgc/src python3 -m unittest /Users/azboo/Desktop/Person/pgc/tests/test_database_backup.py
```

Expected: `OK`.

**Supervisor review:**

- Confirm helper does not delete or mutate source.
- Confirm no real backup is created unless tests use temp dirs.

### Task 3: Legacy Freeze Dry-Run

**Files:**

- Create: `src/pgc_trading/storage/migrators/legacy_freezer.py`
- Create: `tests/test_legacy_freezer.py`

**Depends on:** Task 1 and Task 2.

**Goal:** Provide a dry-run plan for renaming prototype tables to `legacy_*`.

**Implementation intent:**

- Function: `plan_legacy_freeze(conn) -> LegacyFreezePlan`
- Function: `freeze_legacy_tables(db_path: Path, dry_run: bool = True) -> LegacyFreezeResult`
- In dry-run, return planned renames and blockers.
- In non-dry-run, require caller has made a backup first.
- Stop if any `legacy_*` destination already exists.

**Acceptance criteria:**

- Current prototype schema in temp DB produces planned renames.
- Dry-run does not rename tables.
- Existing `legacy_raw_events` produces blocker.
- Mixed schema refuses to freeze.

**Commands:**

```bash
PYTHONPATH=/Users/azboo/Desktop/Person/pgc/src python3 -m unittest /Users/azboo/Desktop/Person/pgc/tests/test_legacy_freezer.py
```

Expected: `OK`.

**Supervisor review:**

- Confirm default is `dry_run=True`.
- Confirm no code path silently overwrites existing `legacy_*`.

## Wave 2: Target Schema DDL

Wave 2 creates target schema in migrations. This wave may require updating `tests/test_migrations.py` so expected applied migrations are discovered dynamically instead of hard-coded to `001_schema_quality`.

### Task 4: Base DDL 002-004

**Files:**

- Create: `src/pgc_trading/storage/migrations/002_raw_market.sql`
- Create: `src/pgc_trading/storage/migrations/003_accounts.sql`
- Create: `src/pgc_trading/storage/migrations/004_meta.sql`
- Create: `tests/test_schema_base_migrations.py`
- Modify: `tests/test_migrations.py` only if necessary to remove hard-coded single-migration assumptions.

**Read:**

- `reports/database_schema_ddl_design.md`
- `reports/database_migration_execution_design.md`

**Goal:** Create target Raw, Market, Account, and Meta schema on empty DB.

**Acceptance criteria:**

- Empty temp DB migrates through 004.
- Raw table contains `import_batch_id`, `is_valid`, `invalid_reason`.
- Market bars contain `fetch_run_id`, `vol`, provider.
- `portfolio_accounts.account_key` is unique.
- `operation_requests.idempotency_key` is unique.
- `domain_events.account_id` references account.
- `PRAGMA foreign_key_check` returns no rows.

**Commands:**

```bash
PYTHONPATH=/Users/azboo/Desktop/Person/pgc/src python3 -m unittest /Users/azboo/Desktop/Person/pgc/tests/test_schema_base_migrations.py
```

Expected: `OK`.

### Task 5: Strategy/Feature/Signal DDL 005-006

**Files:**

- Create: `src/pgc_trading/storage/migrations/005_strategy_governance.sql`
- Create: `src/pgc_trading/storage/migrations/006_feature_signal.sql`
- Create: `tests/test_schema_strategy_migrations.py`

**Depends on:** Task 4.

**Goal:** Create strategy governance and deterministic signal layer.

**Acceptance criteria:**

- `strategy_versions.strategy_version` is unique.
- `agent_policy` defaults to `advisory`.
- `feature_snapshots` references `raw_events`.
- `strategy_signals` references `strategy_runs`.
- `daily_picks` enforces one pick per `strategy_run_id + review_date`.
- `strategy_signals` has no Agent or trade fields.

### Task 6: Agent/Portfolio/Research DDL 007-009

**Files:**

- Create: `src/pgc_trading/storage/migrations/007_agent.sql`
- Create: `src/pgc_trading/storage/migrations/008_portfolio.sql`
- Create: `src/pgc_trading/storage/migrations/009_research_views.sql`
- Create: `tests/test_schema_portfolio_agent_migrations.py`

**Depends on:** Task 5.

**Goal:** Create advisory Agent tables, portfolio lifecycle tables, research/backtest tables, and read-only views.

**Acceptance criteria:**

- `agent_decisions.action` enum includes `support/caution/reject/review_required/no_opinion`.
- `trade_plans` references account, daily pick, signal, optional Agent decision.
- `trades.executed_price` exists; no `price` field in target trades.
- `positions.entry_trade_id` is NOT NULL.
- `exit_decisions` exists; target table is not named `exits`.
- `backtest_trades` is separate from `trades`.

## Wave 3: Verification & Seed

### Task 7: Invariant Checks

**Files:**

- Create: `src/pgc_trading/storage/invariant_checks.py`
- Create: `tests/test_invariant_checks.py`

**Depends on:** Tasks 4-6.

**Goal:** Provide reusable invariant checks for migration and CI.

**Checks:**

- `PRAGMA foreign_key_check`
- `PRAGMA integrity_check`
- `raw_events` forbidden columns absent
- `strategy_signals` Agent fields absent
- `positions.entry_trade_id` exists and is non-null by schema
- no live trade with `source = 'model'`
- account isolation query patterns require account id

**Acceptance criteria:**

- Clean migrated temp DB passes.
- Synthetic DB with violation fails with clear code.

### Task 8: Reference Seed Data

**Files:**

- Create: `src/pgc_trading/storage/seed.py`
- Create: `tests/test_reference_seed.py`

**Depends on:** Task 5.

**Goal:** Seed `cpb_6157@2026-05-03` and paper account reference data idempotently.

**Acceptance criteria:**

- Seeds strategy family `contracting_pullback`.
- Seeds strategy version `cpb_6157@2026-05-03`.
- Seeds parameter set with hash `c4908f5cabe061f4d58fcbdd740f0c255c7c4830f467a9ed1602726688367ddc`.
- Seeds paper account from config, not hard-coded live account.
- Running twice does not duplicate rows.

## Wave 4: Data Services P0

Start Wave 4 only after Wave 1-3 quality gate passes.

### Task 9: RawIngestionService

**Files:**

- Create: `src/pgc_trading/services/common.py`
- Create: `src/pgc_trading/ingestion/raw_importer.py`
- Create: `src/pgc_trading/services/raw_ingestion_service.py`
- Create: `tests/test_raw_ingestion_service.py`
- Create fixtures under `tests/fixtures/raw/`

**Read:**

- `reports/application_service_interface_design.md`
- `reports/testing_validation_design.md`

**Goal:** Import raw PGC events into target raw tables with field whitelist and dirty-data handling.

**Acceptance criteria:**

- Clean raw fixture imports.
- Forbidden fields produce blocker.
- Duplicate import is idempotent.
- Known dirty event can be marked invalid.
- Service does not write feature/signal/portfolio tables.

### Task 10: DataQualityService

**Files:**

- Create: `src/pgc_trading/services/data_quality_service.py`
- Create: `tests/test_data_quality_service.py`

**Depends on:** Task 9.

**Goal:** Check daily review readiness before strategy run.

**Acceptance criteria:**

- Missing trade calendar returns blocker.
- Missing market bars for candidate returns blocker.
- Warnings do not block.
- Readiness response can be used by CLI/API later.

### Task 11: MarketDataService Mock First

**Files:**

- Create: `src/pgc_trading/market/calendar.py`
- Create: `src/pgc_trading/market/tushare_adapter.py`
- Create: `src/pgc_trading/services/market_data_service.py`
- Create: `tests/test_market_data_service.py`

**Depends on:** Task 10.

**Goal:** Implement market service with mock adapter tests before real network use.

**Acceptance criteria:**

- Adapter interface can be mocked.
- Service writes `market_fetch_runs`.
- Service upserts `market_bars`.
- Token is read from env only and never logged.
- Tests do not require network.

## Wave 5: Strategy & Portfolio P0

Start only after Wave 4 quality gate passes.

### Task 12: DailyReviewService Skeleton

**Files:**

- Create: `src/pgc_trading/features/contracting_pullback.py`
- Create: `src/pgc_trading/services/daily_review_service.py`
- Create: `tests/test_daily_review_service.py`

**Goal:** Produce feature run, strategy run, signals, and daily pick without trade plan.

**Acceptance criteria:**

- `review_date = S` reads only market data `<= S`.
- Daily max one pick.
- No trade plan, trade, or position is created.
- Feature hash stable.

### Task 13: Portfolio Planning & Execution Skeleton

**Files:**

- Create: `src/pgc_trading/portfolio/sizing.py`
- Create: `src/pgc_trading/portfolio/state_machines.py`
- Create: `src/pgc_trading/services/portfolio_planning_service.py`
- Create: `src/pgc_trading/services/execution_recording_service.py`
- Create: `src/pgc_trading/services/position_lifecycle_service.py`
- Create: `tests/test_portfolio_lifecycle.py`

**Goal:** Plan -> trade -> position -> exit lifecycle for paper account.

**Acceptance criteria:**

- Plan does not create position.
- Buy trade creates position.
- T+2/T+5 use trade calendar.
- Sell trade closes position.
- Account isolation enforced.

## Sub-Conversation Prompt Template

Use this for each new sub-conversation:

```text
你正在推进 PGC 量化选股交易系统的一个子任务。请先阅读：

1. /Users/azboo/Desktop/Person/pgc/docs/plans/2026-05-04-pgc-parallel-task-supervision.md
2. /Users/azboo/Desktop/Person/pgc/reports/implementation_baseline_20260504.md
3. 与本任务相关的设计文档

你的任务包是：<填入 WP/Task 名称>

严格要求：
- 只修改任务包列出的文件范围。
- 不修改真实 data/pgc_trading.db。
- 测试只能使用 /private/tmp 或 tempfile。
- 不写真实 Tushare token。
- 使用 apply_patch 修改文件。
- 完成后汇报 changed files、commands run、test result、open risks。

开始前先复述你的 owned files 和 out-of-scope。
```

## Supervisor Review Checklist

For every sub-conversation result:

```text
[ ] Changed files are within owned scope.
[ ] No real Tushare token appears.
[ ] Real data/pgc_trading.db was not modified unless explicitly approved.
[ ] Tests include temp database usage.
[ ] Migration tests pass.
[ ] compileall passes.
[ ] foreign_key_check passes on temp migrated DB.
[ ] New code follows layer boundary.
[ ] No strategy code writes portfolio facts.
[ ] No Agent code writes signal or trade facts.
[ ] No report/dashboard code is used as fact source.
```

## Integration Order

The main thread should integrate in this order:

```text
1. WP1 Legacy detector
2. WP2 Backup helper
3. WP3 Legacy freeze dry-run
4. WP3/WP4/WP5 DDL migrations
5. WP6 Invariant checks
6. WP7 Reference seed
7. WP8-WP10 data services
8. WP11 daily review service
9. WP12 portfolio lifecycle
```

Parallel-safe work:

- WP1 and Task 4 can be developed in separate sub-conversations only if Task 4 owns any necessary updates to `tests/test_migrations.py`.
- Documentation-only review can run anytime.
- Wave 4 and Wave 5 should not start until storage schema is integrated.

## Stop Conditions

Pause and return to supervisor if any of these occur:

- A task needs to modify files outside its owned scope.
- A migration would touch real `data/pgc_trading.db`.
- A test requires network access.
- A design conflict appears between DDL and Application Service.
- A sub-conversation finds existing data that cannot be safely migrated.
- A proposed shortcut mixes raw/market/feature/signal/agent/portfolio layers.

## Current Recommended Next Sub-Conversations

Start these first:

1. **WP1 Legacy detector**
2. **WP4 Strategy/feature/signal DDL 005-006**

Keep these under main supervision:

- **WP2 Backup helper** after WP1
- **WP3 Legacy freeze dry-run** after WP1 + WP2

Do not start service-layer implementation until storage schema and invariant checks are merged.
