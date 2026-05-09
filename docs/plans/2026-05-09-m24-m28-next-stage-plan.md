# M24-M28 Next Stage Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the current paper-trading system from “usable after manual supervision” into a repeatable daily operating system with ledger self-checks, a first-class daily pipeline, richer Agent evidence, and safer Dashboard operation flows.

**Architecture:** Keep deterministic strategy, trade plans, trades, positions, and equity snapshots as the source of truth. TradingAgents and external data remain advisory only. All writes must go through service/CLI/API paths with idempotency, operator, backups, and invariant checks instead of ad hoc SQL.

**Tech Stack:** Python application services and CLI, SQLite, FastAPI routes, static Dashboard JavaScript/CSS, pytest/unittest, existing remote deploy script.

---

## Current Baseline

- Current branch: `codex/m14b-yfinance`
- Current deployed release: `pgc-v0.1.0-20260509-g58f8fd6`
- Current deployed revision: `58f8fd61d69659e3160b176dcf8f7e3307044c29`
- Production API: `http://150.158.121.150:8020`
- Production DB: `/opt/pgc/data/pgc_trading.db`
- Latest review date in scope: `20260508`
- Next trade date in scope: `20260511`
- Current paper position:
  - `002647.SZ 仁东控股`
  - buy date `20260508`
  - buy price `13.92`
  - shares `4800`
  - status `waiting_t2`
  - T+2 `20260512`
  - T+5 `20260515`
- Current active buy plan:
  - `trade_plan_id=2`
  - `301188.SZ 力诺药包`
  - planned trade date `20260511`
  - status `active`
- Current Agent state:
  - `agent_run_id=6`
  - `action=caution`
  - `confidence=0.62`

## Parallel Work Map

| Track | Task | Can Run In Parallel? | Depends On | Owner Session |
| --- | --- | --- | --- | --- |
| M24 | Ledger consistency, repair CLI, invariant expansion | Yes, but should be reviewed first | Current production DB facts | Session A |
| M25 | First-class daily pipeline command/script | Yes | M24 invariant API shape | Session B |
| M26 | TradingAgents external data coverage and source reporting | Yes | Existing Agent snapshot schema | Session C |
| M27 | Dashboard modal/confirmation flow and daily task clarity | Yes | M24/M25 API fields if added | Session D |
| M28 | Ops acceptance runbook and paper-trading promotion gates | After M24-M27 | All tracks | Review session |

Recommended order:

1. Start M24 first.
2. Start M26 and M27 in parallel after M24 test contract is clear.
3. Start M25 once M24 exposes a CLI or service-level invariant check.
4. Run M28 only after M24-M27 are merged and deployed.

---

## M24: Ledger Consistency And Repair Guardrails

**Goal:** Prevent a repeat of the M22 drift where trade, position, trade plan, equity snapshot, and report facts disagree.

**Files:**
- Modify: `src/pgc_trading/storage/invariant_checks.py`
- Modify: `src/pgc_trading/services/execution_recording_service.py`
- Modify: `src/pgc_trading/services/operational_readiness_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Test: `tests/test_invariant_checks.py`
- Test: `tests/test_cli_execution_recording.py`
- Test: `tests/test_operational_readiness_service.py`

**Task M24.1: Add invariant coverage for executed buy ledger facts**

Add checks that fail when:
- `trades.amount != trades.executed_price * trades.shares` for executed trades.
- `positions.entry_trade_id` does not point to the executed buy trade.
- `positions.buy_price`, `positions.shares`, and `positions.cost` do not match the entry trade.
- An executed buy `trade_plan_id` is not `executed`.
- An active buy plan exists for a past planned trade date while a matching executed trade exists.
- Latest `equity_snapshots.cash + equity_snapshots.market_value != equity_snapshots.total_equity`.
- Latest `equity_snapshots.market_value` does not equal open position cost under current paper accounting.

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_invariant_checks
```

Expected:

```text
OK
```

**Task M24.2: Add a read-only ledger audit CLI**

Add CLI:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main ops ledger-audit --account paper-main --date 20260508 --db-path data/pgc_trading.db
```

Expected output shape:

```text
ledger_audit_status=pass
account_key=paper-main
as_of_date=20260508
open_positions=1
active_plans=1
violations=0
```

If violations exist, output stable machine-readable lines:

```text
violation_code=POSITION_ENTRY_TRADE_MISMATCH entity=position:1 severity=blocker
```

**Task M24.3: Add a guarded repair command for known ledger drift**

Add CLI:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main ops ledger-repair \
  --account paper-main \
  --date 20260508 \
  --operator azboo \
  --db-path data/pgc_trading.db \
  --dry-run
```

Rules:
- Default is dry-run.
- Non-dry-run requires `--operator`.
- It must print every SQL-intent-level action before applying.
- It must refuse unknown repairs.
- It must not alter Agent tables, market data, strategy signals, or reports.

Expected dry-run output:

```text
ledger_repair_status=would_apply
backup_required=true
repair_actions=...
```

**Task M24.4: Dashboard and readiness must surface ledger blockers**

If `check_database()` fails, the Dashboard should show a data-quality blocker and disable write buttons.

Files:
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/styles.css`
- Test: `tests/test_dashboard_static.py`

Run:

```bash
node --check web/dashboard/app.js
PYTHONPATH=src python3 -m unittest tests.test_dashboard_static
```

Expected:

```text
OK
```

**M24 Acceptance:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q
git diff --check
```

Expected:

```text
230+ tests pass, skipped count unchanged unless tests were added.
```

---

## M25: First-Class Daily Pipeline

**Goal:** Replace manually chained daily-close, Agent review, exit evaluation, and report refresh with one repeatable command.

**Files:**
- Create: `scripts/run_daily_pipeline.sh`
- Create or modify: `src/pgc_trading/services/daily_pipeline_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Test: `tests/test_cli_daily_pipeline.py`
- Test: `tests/test_daily_pipeline_service.py`

**Task M25.1: Define pipeline CLI contract**

Add command:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main ops daily-pipeline \
  --date 20260508 \
  --account paper-main \
  --operator azboo \
  --db-path data/pgc_trading.db \
  --dry-run
```

Required steps:

1. Run ledger audit.
2. Run daily close.
3. Run TradingAgents review if candidate exists.
4. Run position exit evaluation.
5. Generate Markdown and JSON reports.
6. Print summary with IDs.

Expected output:

```text
pipeline_status=pass
review_date=20260508
next_trade_date=20260511
daily_pick_id=2
trade_plan_id=2
agent_run_id=6
exit_decisions=0
report_markdown=reports/daily_review_20260508.md
report_json=reports/daily_review_20260508.json
```

**Task M25.2: Add idempotency and apply mode**

Non-dry-run requires:
- `--operator`
- stable idempotency key per step
- pre-run DB backup path in output

Run:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main ops daily-pipeline \
  --date 20260508 \
  --account paper-main \
  --operator azboo \
  --db-path data/pgc_trading.db \
  --apply
```

Expected:

```text
pipeline_status=pass
changed=false
```

when rerun on the same date.

**Task M25.3: Shell wrapper for server ops**

Create:

```bash
scripts/run_daily_pipeline.sh
```

Contract:

```bash
./scripts/run_daily_pipeline.sh --date 20260508 --account paper-main --operator azboo --apply
```

The wrapper must:
- set `PYTHONPATH=src`
- default `PGC_DB_PATH` to `data/pgc_trading.db` locally
- refuse apply without operator
- write logs to `.pgc-runs/daily-pipeline-YYYYMMDD.log`
- exit non-zero if any step fails

**M25 Acceptance:**

```bash
bash -n scripts/run_daily_pipeline.sh
PYTHONPATH=src:. pytest -q tests/test_cli_daily_pipeline.py tests/test_daily_pipeline_service.py
PYTHONPATH=src:. pytest -q
```

---

## M26: TradingAgents Evidence Coverage

**Goal:** Make Agent reports honestly richer: technical, fundamental, news, and sentiment sections should show which external sources were available and which were missing.

**Files:**
- Modify: `src/pgc_trading/services/agent_external_data_service.py`
- Modify: `src/pgc_trading/services/agent_review_service.py`
- Modify: `src/pgc_trading/agents/tradingagents_adapter.py`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `web/dashboard/app.js`
- Test: `tests/test_agent_external_data_service.py`
- Test: `tests/test_agent_review_service.py`
- Test: `tests/test_daily_report.py`
- Test: `tests/test_dashboard_static.py`

**Task M26.1: Add external data coverage summary**

Agent snapshot should include:

```json
{
  "external_data_coverage": {
    "fundamental": "partial",
    "news": "unavailable",
    "sentiment": "partial",
    "technical": "available"
  }
}
```

Rules:
- Missing data must be explicit.
- The adapter must not invent news or sentiment evidence.
- Dashboard should show source coverage next to the Agent result.

**Task M26.2: Import richer cached data when available**

Add importer support for:
- fundamental snapshots
- company announcements/news snippets
- sentiment snippets

Use existing `agent_external_items` storage; do not add tables unless the current schema cannot represent the source.

Example command:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main agent external-data import \
  --date 20260508 \
  --source tushare \
  --input data/external/agent/20260508.json \
  --operator azboo \
  --db-path data/pgc_trading.db
```

**Task M26.3: Dashboard display**

Dashboard Agent drawer must answer:
- 这是 TradingAgents 输出还是系统复盘原始数据？
- 每个分析面用了什么数据？
- 哪些数据未接入？
- Agent 是否影响交易计划？答案必须是“否，仅供参考”。

**M26 Acceptance:**

```bash
PYTHONPATH=src:. pytest -q tests/test_agent_external_data_service.py tests/test_agent_review_service.py tests/test_daily_report.py
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q
```

---

## M27: Dashboard Operation Flow And Modal Cleanup

**Goal:** Make Dashboard stop feeling flat and make high-risk operations feel deliberate.

**Files:**
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/styles.css`
- Test: `tests/test_dashboard_static.py`

**Task M27.1: Convert write actions to confirmation modals**

Use modal/drawer patterns for:
- publish plan
- cancel plan
- record buy trade
- record sell trade
- run daily close
- run Agent review
- run exit evaluation

Each modal must show:
- account
- review date
- execution date
- target stock
- plan ID or position ID
- operator requirement
- dry-run/apply status

**Task M27.2: Improve record-trade form**

The buy/sell record modal should:
- use date picker input for trade date
- prefill planned date, planned price reference, planned shares
- require explicit operator for non-dry-run
- show disabled reason inline when locked
- avoid freeform date-only UX when a planned date exists

**Task M27.3: Add daily review history navigation polish**

Daily review should support:
- previous/next review date
- latest available review
- disabled state when no prior/next date
- visible “current selected review date” in every relevant section

**M27 Acceptance:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src python3 -m unittest tests.test_dashboard_static
PYTHONPATH=src:. pytest -q
```

Manual smoke:

```bash
PGC_API_ENABLE_WRITES=0 .venv/bin/python -m uvicorn 'pgc_trading.api:create_app' --factory --host 127.0.0.1 --port 8000
```

Then open:

```text
http://127.0.0.1:8000/dashboard/
```

Check:
- no blank screen
- no overlapping text on desktop and mobile widths
- write buttons show confirmation modal
- future plan is locked until its planned date

---

## M28: Ops Acceptance And Runbook Refresh

**Goal:** Freeze the M24-M27 behavior into a repeatable acceptance gate and update the runbook so daily operations use the one-command pipeline instead of a hand-chained CLI flow.

**Files:**
- Modify: `reports/operational_runbook_design.md`
- Modify: `docs/plans/2026-05-09-m24-m28-next-stage-plan.md`
- Modify: `tests/test_operational_runbook_static.py`

**Acceptance checklist:**

- Runbook names `scripts/run_daily_pipeline.sh` as the daily close primary command.
- Runbook states that `daily-pipeline` performs ledger audit, daily close, TradingAgents review or reuse/skip, exit evaluation, Markdown and JSON report refresh, and backup before non-dry writes.
- Runbook contains an `M28 验收门禁` section with local test, ledger audit, daily pipeline dry-run, health, and daily-review API checks.
- Static tests assert the runbook contract so future edits do not drift back to the old hand-chained flow.
- No manual SQL is needed for normal daily acceptance.

**Final verification commands:**

```bash
PYTHONPATH=src:. pytest -q tests/test_operational_runbook_static.py
PYTHONPATH=src:. pytest -q
git diff --check
PYTHONPATH=src python3 -m pgc_trading.cli.main ops ledger-audit --account paper-main --date 20260508 --db-path data/pgc_trading.db
./scripts/run_daily_pipeline.sh --date 20260508 --account paper-main --operator azboo --dry-run
curl -fsS http://150.158.121.150:8020/api/health
curl -fsS 'http://150.158.121.150:8020/api/daily-reviews/20260508?account_key=paper-main'
```

Expected:

```text
tests pass
ledger_audit_status=pass
pipeline_status=pass
health status ok
daily review API returns 200
```

---

## Recommended Session Split

### Session A: M24 Ledger Consistency

Owns:
- `src/pgc_trading/storage/invariant_checks.py`
- `src/pgc_trading/cli/main.py` ledger audit/repair commands
- invariant and CLI tests

Do not touch Dashboard styling except blocker text if needed.

### Session B: M25 Daily Pipeline

Owns:
- `src/pgc_trading/services/daily_pipeline_service.py`
- `scripts/run_daily_pipeline.sh`
- daily pipeline tests

Coordinate with Session A on the audit command output.

### Session C: M26 Agent Evidence

Owns:
- `src/pgc_trading/services/agent_external_data_service.py`
- `src/pgc_trading/services/agent_review_service.py`
- `src/pgc_trading/agents/tradingagents_adapter.py`
- Agent/report tests

Do not change trade plan/trade/position behavior.

### Session D: M27 Dashboard Modals

Owns:
- `web/dashboard/index.html`
- `web/dashboard/app.js`
- `web/dashboard/styles.css`
- `tests/test_dashboard_static.py`

Coordinate with Sessions A/B if new API fields are required.

### Review Session: M28 Integration

Owns:
- merge review
- full tests
- production deploy
- post-deploy DB/API verification
- update runbook

---

## Reviewer Checklist For Codex

For every submitted session:

1. Run `git diff --stat` and confirm the write scope matches the task.
2. Run targeted tests listed in the task.
3. Run full tests before merge:

```bash
PYTHONPATH=src:. pytest -q
```

4. Reject any change that:
   - lets TradingAgents mutate plans, trades, positions, or market data;
   - bypasses operator requirement for apply writes;
   - writes production facts without backup/idempotency;
   - hides missing news/fundamental/sentiment data;
   - makes Dashboard write buttons available when date, account, or ledger state is unsafe.
