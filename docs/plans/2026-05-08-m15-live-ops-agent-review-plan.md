# M15 Live Ops And Agent Review Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the already deployed paper-trading system safe for real non-dry-run operation while turning TradingAgents reviews into traceable Chinese advisory output backed by cached external data.

**Architecture:** Keep deterministic PGC strategy, trade plans, trades, positions, and readiness gates as the only execution facts. Agent and external data stay advisory: they may enrich `input_snapshots`, artifacts, and Dashboard review displays, but must not mutate strategy signals, trade plans, trades, positions, or production market bars.

**Tech Stack:** Python stdlib services and `unittest`, SQLite migrations, FastAPI API routes, vanilla Dashboard JS/CSS, systemd deployment on `150.158.121.150:8020`.

---

## Current Baseline

Completed before M15:

- `M12B`: Dashboard review history can request historical rows using `before_date`.
- `M13`: Execution console has stronger readiness, record form, and manual trade UX.
- `M14C`: Agent snapshot can include cached external items and isolated diagnostic market data.

Supervisor review fixes already applied:

- Agent external dates are filtered as compact `YYYYMMDD`; migration rejects invalid `agent_external_items.published_date`.
- Dashboard resets pre-open checks when account/date/strategy changes.
- Dashboard blocks record submission when plan side, plan trade date, or A-share board-lot share rules do not match service validation.

Validation baseline:

```bash
node --check web/dashboard/app.js
PYTHONPATH=src python3 -m unittest tests.test_agent_review_service tests.test_schema_portfolio_agent_migrations tests.test_dashboard_static
PYTHONPATH=src python3 -m unittest discover tests
git diff --check
```

Expected: all pass.

## Parallelization Map

Can run in parallel:

- `M15A` and `M15C`: ops safety and external-data ingestion touch different areas.
- `M15A` and `M15D`: runbook/ops versus Dashboard Agent display are mostly independent.
- `M15C` and `M15E`: ingestion service versus review archive/reporting can be split if they avoid editing the same Dashboard files.

Should be sequential:

- `M15B` depends on `M15A`; do not perform the first real write before backup/restore is documented and tested.
- `M15D` should integrate after `M15C` if it renders newly ingested item types from live DB rather than existing snapshots.
- Any two Dashboard tasks that edit `web/dashboard/app.js`, `web/dashboard/index.html`, or `web/dashboard/styles.css` should not run at the same time unless file ownership is explicitly split by section.

## M15A: Online Write Safety Net And Rollback

**Goal:** Before the first real non-dry-run paper trade write, make backup, restore, health verification, and rollback steps repeatable.

**Files:**

- Create: `scripts/backup_remote_pgc_db.sh`
- Create: `scripts/restore_remote_pgc_db.sh`
- Modify: `reports/operational_runbook_design.md`
- Test: `tests/test_operational_runbook_static.py`

**Steps:**

1. Write static tests asserting the runbook contains backup path, restore path, `systemctl restart pgc-api.service`, and `/api/health` verification.
2. Create a backup script that SSHes to `root@150.158.121.150`, copies `/opt/pgc/data/pgc_trading.db` to `/opt/pgc/backups/pgc_trading-YYYYMMDD-HHMMSS.db`, and prints the backup path.
3. Create a restore script that requires an explicit backup path argument, stops/restarts `pgc-api.service`, and verifies `/api/health`.
4. Document the exact pre-write checklist: service status, migration applied, `writes_enabled=true`, backup created, dry-run trade smoke, operator set.
5. Run focused static tests and `shellcheck` only if available; otherwise run the scripts with `--help` or dry-run mode.

**Acceptance:**

- No script deletes data without an explicit backup path.
- Runbook has a copy-pasteable backup and restore sequence.
- Supervisor can verify without touching production writes.

## M15B: First Real Write Drill

**Goal:** Execute one real non-dry-run paper trade only after `M15A` passes, then verify ledger state.

**Files:**

- Modify: `reports/operational_runbook_design.md`
- Optional create: `reports/live_write_drill_20260508.md`

**Steps:**

1. Create a remote DB backup using `M15A`.
2. Confirm `/api/health` returns `writes_enabled=true`.
3. Submit one non-dry-run trade for the active `paper-main` plan after checking Dashboard readiness.
4. Query and record `trades`, `positions`, `trade_plans`, `equity_snapshots`, and latest Dashboard state.
5. If any verification fails, restore from backup and record the failure.

**Acceptance:**

- Exactly one intended trade is inserted.
- The linked plan transitions as expected.
- Position and equity snapshot reflect the trade.
- A rollback path exists and was not needed, or was executed cleanly.

## M15C: Cached External Data Ingestion

**Goal:** Make `agent_external_items` usable without hand-writing SQL.

**Files:**

- Create: `src/pgc_trading/services/agent_external_data_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Test: `tests/test_agent_external_data_service.py`
- Test: `tests/test_cli_main.py`

**Steps:**

1. Add a service request model for importing JSON records with `ts_code`, `published_date`, `item_type`, `provider`, `title`, `summary`, optional `url`, `sentiment`, `importance`, and `metadata`.
2. Validate `published_date` as `YYYYMMDD`, `item_type` against migration values, and `metadata` as JSON-serializable.
3. Generate deterministic `source_hash` from provider, type, code, date, title, and summary.
4. Insert with idempotent upsert semantics so repeated imports do not duplicate rows.
5. Add CLI command `pgc agent external-data import --file path.json --apply`; default is dry-run.

**Acceptance:**

- Dry-run previews counts and validation errors without writing.
- Apply writes only `agent_external_items`.
- Future-dated rows can be stored, but Agent snapshots only read rows with `published_date <= review_date`.

## M15D: Chinese Agent Report Display

**Goal:** Make the Dashboard clearly show what TradingAgents actually said, in Chinese, with source boundaries visible.

**Files:**

- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/styles.css`
- Test: `tests/test_dashboard_static.py`

**Steps:**

1. Add a compact Agent report section with action, confidence, risk level, and summary.
2. Render analyst sections for technical, fundamental, news, and sentiment when artifact JSON is available.
3. Display `source_refs` chips, including `agent_external_items:*` and `market_diagnostic_bars:*`.
4. Show a Chinese empty state when TradingAgents is skipped or unavailable.
5. Keep the wording advisory: no copy should imply automatic trading, automatic cancellation, or broker execution.

**Acceptance:**

- Page answers: “这是 TradingAgents 输出还是系统复盘原始数据？”
- Missing external data is shown as “未接入/数据不足”, not hallucinated.
- `node --check web/dashboard/app.js` and Dashboard static tests pass.

## M15E: Review Archive And Historical Comparison

**Goal:** Make previous daily reviews easier to audit and compare without relying on one current page state.

**Files:**

- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `src/pgc_trading/api/routes.py`
- Modify: `web/dashboard/app.js`
- Test: `tests/test_daily_report.py`
- Test: `tests/test_api_read_routes.py`
- Test: `tests/test_dashboard_static.py`

**Steps:**

1. Ensure `/api/daily-reviews/{date}` is the single source for the selected date.
2. Add previous/next history navigation tests around `before_date`.
3. Add optional comparison fields: current pick versus previous pick, blocker count delta, plan status delta.
4. Render comparison as compact badges, not as a new landing page.
5. Confirm historical review selection does not change execution readiness for the current execution date unless the user explicitly applies that date.

**Acceptance:**

- User can select an older date and understand that date's pick, plan, Agent status, and blockers.
- Historical browsing does not accidentally enable today’s trade buttons.

## Supervisor Gate For Completed M15 Tasks

Run after each child session:

```bash
node --check web/dashboard/app.js
PYTHONPATH=src python3 -m unittest discover tests
git diff --check
rg -n "sk-[A-Za-z0-9]|api[_-]?key|password|secret|TUSHARE_TOKEN|DEEPSEEK|OPENAI_API_KEY" README.md docs reports src tests web pyproject.toml
```

Expected:

- JS syntax passes.
- Full unittest suite passes.
- `git diff --check` has no output.
- Secret scan has no real secret values; placeholder docs are acceptable only after inspection.
