# M28-M34 Operating Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move the system from "feature complete for paper trading" to a safer daily operating loop that can survive real 2026-05-11 open execution, post-close automation, external Agent evidence, and paper-to-live promotion review.

**Architecture:** Keep the ledger, trade plans, trades, positions, reports, and daily pipeline as the source of truth. Add narrow operational services and API guards rather than letting Dashboard logic or shell scripts invent trading state. All non-dry writes must remain operator-tagged, idempotent, backed up when they mutate the database, and blocked by invariant failures.

**Tech Stack:** Python services and CLI, SQLite, FastAPI adapter, static Dashboard JavaScript/CSS, bash deployment and ops scripts, pytest/unittest, production API on port `8020`.

---

## Current Baseline

- Branch: `codex/m14b-yfinance`
- Latest pushed commit: `23b6468`
- Latest deployed release: `pgc-v0.1.0-20260509-g23b6468`
- Production API: `http://150.158.121.150:8020`
- Production DB: `/opt/pgc/data/pgc_trading.db`
- Last completed review date: `20260508`
- Next planned trade date: `20260511`
- Current open paper position:
  - `002647.SZ` / `仁东控股`
  - buy date `20260508`
  - buy price `13.92`
  - shares `4800`
  - status `waiting_t2`
  - T+2 `20260512`
  - T+5 `20260515`
- Current active buy plan:
  - `trade_plan_id=2`
  - `301188.SZ` / `力诺药包`
  - planned trade date `20260511`
  - planned shares `2400`
  - status `active`
- Current readiness:
  - ledger audit passes
  - paper-readiness still blocked by minimum paper trade count
  - current executed trades count is below the 10-trade gate

## Parallel Work Map

| Track | Task | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- |
| M28 | Ops acceptance and runbook refresh | Yes | M24-M27 deployed | Session A |
| M29 | 2026-05-11 open execution checkpoint | Partly; final execution is time-bound | Current production DB | Session Ops |
| M30 | Open execution service/API contract | Yes | Existing trade plan and position services | Session B |
| M31 | Scheduled daily pipeline on server | Yes, after M28 contract is frozen | `scripts/run_daily_pipeline.sh` | Session C |
| M32 | API write-token guard | Yes, high priority | Existing API write routes | Session D |
| M33 | Agent external data ingestion v2 | Yes | M26 coverage fields | Session E |
| M34 | Paper promotion scorecard | Yes | Ledger and readiness services | Session F |

Recommended order:

1. Run M28 first so the team has one acceptance gate for the deployed system.
2. Start M32 in parallel because production writes are currently enabled on the public service and only guarded by payload fields.
3. Run M29 as an ops checkpoint around the 2026-05-11 market open.
4. Build M30 after M29 exposes what was still confusing in the opening workflow.
5. Build M31 after M28 and M32 so scheduled writes use the final safety contract.
6. Run M33 and M34 in parallel; they do not need to block the opening execution loop.

---

## M28: Ops Acceptance And Runbook Refresh

**Goal:** Freeze the M24-M27 behavior into a repeatable acceptance gate and update the runbook so it describes the new daily pipeline instead of the older hand-chained CLI flow.

**Files:**
- Modify: `reports/operational_runbook_design.md`
- Modify: `tests/test_operational_runbook_static.py`
- Modify: `docs/plans/2026-05-09-m24-m28-next-stage-plan.md`

**Task M28.1: Update the runbook daily close section**

Replace the old primary flow:

```bash
pgc daily-close --date S --db-path data/pgc_trading.db --account paper-main --apply --operator azboo
```

with the new primary flow:

```bash
./scripts/run_daily_pipeline.sh --date S --account paper-main --operator azboo --apply
```

The runbook must state that `daily-pipeline` performs:

1. ledger audit
2. daily close
3. TradingAgents review or reuse/skip
4. exit evaluation
5. Markdown and JSON report refresh
6. backup before non-dry writes

**Task M28.2: Add acceptance checklist**

Add a section named `M28 验收门禁` with these required checks:

```bash
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

**Task M28.3: Static test the runbook contract**

Add assertions in `tests/test_operational_runbook_static.py` that verify the runbook contains:

- `scripts/run_daily_pipeline.sh`
- `ledger_audit_status=pass`
- `pipeline_status=pass`
- `backup before non-dry writes`
- `TradingAgents review`
- `operator`
- `/api/health`
- `/api/daily-reviews/20260508`

Run:

```bash
PYTHONPATH=src:. pytest -q tests/test_operational_runbook_static.py
```

Expected:

```text
passed
```

**M28 Acceptance:**

```bash
PYTHONPATH=src:. pytest -q tests/test_operational_runbook_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

Expected:

```text
all tests pass
```

---

## M29: 2026-05-11 Open Execution Checkpoint

**Goal:** Execute the next paper-trading morning safely: verify the plan, avoid duplicate/future-date recording, then either record the real fill or cancel with an explicit reason.

**Files:**
- Usually no code changes.
- Possible report refresh: `reports/daily_review_20260508.md`
- Possible report refresh: `reports/daily_review_20260508.json`
- Possible DB mutation: `data/pgc_trading.db`

**Task M29.1: Pre-open production audit**

Run locally against the production DB if synced, or remotely on the server:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main ops ledger-audit --account paper-main --date 20260511 --db-path data/pgc_trading.db
```

Expected:

```text
ledger_audit_status=pass
active_plans=1
violations=0
```

Then query the deployed API:

```bash
curl -fsS 'http://150.158.121.150:8020/api/trade-plans?account_key=paper-main&status=active&planned_trade_date=20260511'
```

Expected:

```text
trade_plan_id=2 is visible
ts_code=301188.SZ
planned_trade_date=20260511
status=active
```

**Task M29.2: Dry-run the buy recording path before market execution**

Use the current plan values as placeholders only:

```bash
curl -fsS -X POST 'http://150.158.121.150:8020/api/trades' \
  -H 'Content-Type: application/json' \
  -d '{
    "dry_run": true,
    "account_key": "paper-main",
    "trade_plan_id": 2,
    "side": "buy",
    "executed_date": "20260511",
    "executed_price": 0,
    "shares": 2400,
    "source": "manual"
  }'
```

Expected:

```text
validation_failed if price is zero
no database write
```

Then dry-run with an estimated non-zero open price:

```bash
curl -fsS -X POST 'http://150.158.121.150:8020/api/trades' \
  -H 'Content-Type: application/json' \
  -d '{
    "dry_run": true,
    "account_key": "paper-main",
    "trade_plan_id": 2,
    "side": "buy",
    "executed_date": "20260511",
    "executed_price": 27.80,
    "shares": 2400,
    "source": "manual"
  }'
```

Expected:

```text
status=success or preview success
trade_plan_id=2
no persisted trade_id
```

**Task M29.3: Apply the real buy only after manual broker execution**

After the actual paper/broker fill is known, record the exact price and shares:

```bash
curl -fsS -X POST 'http://150.158.121.150:8020/api/trades' \
  -H 'Content-Type: application/json' \
  -d '{
    "dry_run": false,
    "request_id": "open-buy-20260511-301188",
    "idempotency_key": "paper-main:buy:trade-plan:2:20260511",
    "operator": "azboo",
    "account_key": "paper-main",
    "trade_plan_id": 2,
    "side": "buy",
    "executed_date": "20260511",
    "executed_price": ACTUAL_PRICE,
    "shares": ACTUAL_SHARES,
    "fee": ACTUAL_FEE,
    "source": "manual"
  }'
```

Expected:

```text
status=success
trade_id is created
position_id is created
trade_plan_id=2 becomes executed
```

**Task M29.4: If skipped, cancel instead of silently ignoring**

If the trade is not executed, cancel the plan through the service/API:

```bash
curl -fsS -X POST 'http://150.158.121.150:8020/api/trade-plans/2/cancel' \
  -H 'Content-Type: application/json' \
  -d '{
    "request_id": "cancel-20260511-301188",
    "idempotency_key": "paper-main:cancel:trade-plan:2:20260511",
    "operator": "azboo",
    "account_key": "paper-main",
    "cancel_reason": "manual skip: reason here"
  }'
```

Expected:

```text
status=success
trade_plan_id=2
status=cancelled
```

**M29 Acceptance:**

After apply or cancel:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main ops ledger-audit --account paper-main --date 20260511 --db-path data/pgc_trading.db
PYTHONPATH=src python3 -m pgc_trading.cli.main paper-readiness --date 20260511 --account paper-main --db-path data/pgc_trading.db
```

Expected:

```text
ledger_audit_status=pass
paper-readiness remains blocked only by known gates, not ledger drift
```

---

## M30: Open Execution Service And API Contract

**Goal:** Stop making the Dashboard infer opening duties from scattered review/plan/position payloads. Add one service/API response that says "today do this, blocked because this, next click is this".

**Files:**
- Create: `src/pgc_trading/services/open_execution_service.py`
- Modify: `src/pgc_trading/api/services.py`
- Modify: `src/pgc_trading/api/routes.py`
- Modify: `src/pgc_trading/api/schemas.py` if envelope examples need updating
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/styles.css`
- Test: `tests/test_open_execution_service.py`
- Test: `tests/test_api_read_routes.py`
- Test: `tests/test_cli_main.py`
- Test: `tests/test_dashboard_static.py`

**Task M30.1: Write service tests first**

Create `tests/test_open_execution_service.py` covering:

- active buy plan due today returns `next_action=record_buy`
- active buy plan in the future returns `next_action=wait`
- executed plan returns `next_action=none`
- due T+2 position returns `next_action=evaluate_exit`
- due sell plan returns `next_action=record_sell`
- invariant failure returns `status=blocked`

Run:

```bash
PYTHONPATH=src:. pytest -q tests/test_open_execution_service.py
```

Expected:

```text
fail because service does not exist
```

**Task M30.2: Implement service result shape**

Add dataclasses:

```python
@dataclass(frozen=True)
class OpenExecutionRequest:
    as_of_date: str
    account_key: str | None = "paper-main"
    account_id: int | None = None

@dataclass(frozen=True)
class OpenExecutionResult:
    as_of_date: str
    account_key: str
    status: str
    next_action: str
    blocked_reasons: list[str]
    primary_plan_id: int | None
    primary_position_id: int | None
    target_stock: str | None
    target_name: str | None
    planned_trade_date: str | None
    planned_shares: int | None
    operator_required: bool
```

Allowed `next_action` values:

- `record_buy`
- `record_sell`
- `evaluate_exit`
- `wait`
- `none`
- `blocked`

Run:

```bash
PYTHONPATH=src:. pytest -q tests/test_open_execution_service.py
```

Expected:

```text
passed
```

**Task M30.3: Add API route**

Add:

```text
GET /api/open-execution?account_key=paper-main&as_of_date=20260511
```

Expected response data:

```json
{
  "as_of_date": "20260511",
  "account_key": "paper-main",
  "status": "ready",
  "next_action": "record_buy",
  "primary_plan_id": 2,
  "target_stock": "301188.SZ",
  "target_name": "力诺药包",
  "planned_trade_date": "20260511",
  "planned_shares": 2400,
  "operator_required": true
}
```

Run:

```bash
PYTHONPATH=src:. pytest -q tests/test_api_read_routes.py
```

Expected:

```text
passed
```

**Task M30.4: Add CLI command**

Add:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main ops open-execution \
  --date 20260511 \
  --account paper-main \
  --db-path data/pgc_trading.db
```

Expected output:

```text
open_execution_status=ready
next_action=record_buy
trade_plan_id=2
target=301188.SZ
planned_trade_date=20260511
```

**Task M30.5: Use it in Dashboard**

Dashboard execution page should render this service as the top decision strip:

- `今天该做什么`
- `为什么不能做`
- `下一步按钮`
- `关联计划/持仓`

The existing modal write flows remain responsible for actual mutation.

Run:

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_dashboard_static.py
```

Expected:

```text
passed
```

**M30 Acceptance:**

```bash
PYTHONPATH=src:. pytest -q tests/test_open_execution_service.py tests/test_api_read_routes.py tests/test_cli_main.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

---

## M31: Scheduled Daily Pipeline On Server

**Goal:** Make post-close review repeatable on the server without hand-typing the whole command every day.

**Files:**
- Modify: `scripts/run_daily_pipeline.sh`
- Create: `scripts/install_remote_daily_pipeline_timer.sh`
- Modify: `reports/operational_runbook_design.md`
- Test: `tests/test_operational_runbook_static.py`
- Test: `tests/test_cli_daily_pipeline.py`

**Task M31.1: Add latest-closed date mode**

Extend `scripts/run_daily_pipeline.sh`:

```bash
./scripts/run_daily_pipeline.sh --date latest-closed --account paper-main --operator system-daily-pipeline --dry-run
```

Rules:

- `latest-closed` resolves through the DB trading calendar.
- It must not select a future date.
- It should refuse to run if market data for the resolved date is missing.
- It must print `resolved_date=YYYYMMDD`.

Run:

```bash
bash -n scripts/run_daily_pipeline.sh
PYTHONPATH=src:. pytest -q tests/test_cli_daily_pipeline.py
```

Expected:

```text
passed
```

**Task M31.2: Add systemd timer installer**

Create `scripts/install_remote_daily_pipeline_timer.sh`.

Contract:

```bash
scripts/install_remote_daily_pipeline_timer.sh --dry-run
scripts/install_remote_daily_pipeline_timer.sh --operator system-daily-pipeline --mode dry-run
scripts/install_remote_daily_pipeline_timer.sh --operator system-daily-pipeline --mode apply
```

Rules:

- Default to dry-run mode.
- Non-dry apply mode requires explicit `--mode apply`.
- Timer should run after A-share close, for example `16:20 Asia/Shanghai`.
- Service should use:
  - `WorkingDirectory=/opt/pgc/app`
  - `PGC_DB_PATH=/opt/pgc/data/pgc_trading.db`
  - logs under `/opt/pgc/logs`
- Installer must print unit paths and timer status commands.

**Task M31.3: Update runbook**

Add:

```bash
systemctl status pgc-daily-pipeline.timer
journalctl -u pgc-daily-pipeline.service -n 100 --no-pager
```

and rollback instructions:

```bash
systemctl disable --now pgc-daily-pipeline.timer
```

**M31 Acceptance:**

```bash
bash -n scripts/run_daily_pipeline.sh
bash -n scripts/install_remote_daily_pipeline_timer.sh
PYTHONPATH=src:. pytest -q tests/test_cli_daily_pipeline.py tests/test_operational_runbook_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

---

## M32: API Write Token Guard

**Goal:** Prevent public non-dry API writes from relying only on `operator` and `idempotency_key`. Dry-run and read endpoints stay open; non-dry writes require a server-side token.

**Files:**
- Modify: `src/pgc_trading/api/settings.py`
- Modify: `src/pgc_trading/api/routes.py`
- Modify: `src/pgc_trading/api/app.py` if dependency injection is cleaner there
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/styles.css`
- Modify: `scripts/deploy_remote.sh`
- Test: `tests/test_api_app.py`
- Test: `tests/test_api_write_routes.py`
- Test: `tests/test_dashboard_static.py`

**Task M32.1: Add settings and health safety test**

Add environment setting:

```text
PGC_API_WRITE_TOKEN
```

Rules:

- If `PGC_API_ENABLE_WRITES=1` and `PGC_API_WRITE_TOKEN` is set, every non-dry write requires header `X-PGC-Write-Token`.
- If writes are disabled, behavior stays the same.
- Health payload must never expose token existence, length, or value.

Run:

```bash
PYTHONPATH=src:. pytest -q tests/test_api_app.py tests/test_api_write_routes.py
```

Expected:

```text
new token tests fail before implementation, then pass
```

**Task M32.2: Thread headers through write context**

Route functions need access to request headers. Use FastAPI `Request` only in route wrappers, not in service functions.

Expected rejection:

```json
{
  "status": "forbidden",
  "errors": [
    {
      "code": "API_WRITE_TOKEN_REQUIRED",
      "message": "valid X-PGC-Write-Token is required for non-dry API writes"
    }
  ]
}
```

**Task M32.3: Dashboard token field**

Add an operator-panel field:

- label: `写入令牌`
- input type: `password`
- stored in `localStorage` as `pgc.dashboard.writeToken`
- only sent on non-dry write requests
- never displayed in mutation summaries, drawers, errors, or logs

Run:

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_dashboard_static.py
```

Expected:

```text
passed
```

**Task M32.4: Deploy script support**

Add optional deploy env passthrough:

```text
PGC_API_WRITE_TOKEN
```

Do not print the token in dry-run or deploy logs.

**M32 Acceptance:**

```bash
PYTHONPATH=src:. pytest -q tests/test_api_app.py tests/test_api_write_routes.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

Manual server check after deploy:

```bash
curl -fsS -X POST 'http://150.158.121.150:8020/api/trades' \
  -H 'Content-Type: application/json' \
  -d '{"dry_run":false,"operator":"azboo","idempotency_key":"token-test","trade_plan_id":2}'
```

Expected:

```text
403 API_WRITE_TOKEN_REQUIRED
```

---

## M33: Agent External Data Ingestion V2

**Goal:** Move from "coverage labels are honest" to "TradingAgents has useful cached external evidence when available", without allowing live web/network calls inside the trading decision path.

**Files:**
- Modify: `src/pgc_trading/services/agent_external_data_service.py`
- Modify: `src/pgc_trading/services/agent_review_service.py`
- Modify: `src/pgc_trading/agents/tradingagents_adapter.py`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `web/dashboard/app.js`
- Test: `tests/test_agent_external_data_service.py`
- Test: `tests/test_agent_review_service.py`
- Test: `tests/test_tradingagents_adapter.py`
- Test: `tests/test_daily_report.py`
- Test: `tests/test_dashboard_static.py`
- Fixture: `tests/fixtures/agent_external/20260508_301188.json`

**Task M33.1: Define normalized fixture format**

Create fixture shape:

```json
{
  "as_of_date": "20260508",
  "ts_code": "301188.SZ",
  "items": [
    {
      "source": "tushare",
      "category": "fundamental",
      "published_date": "20260508",
      "title": "valuation snapshot",
      "summary": "PE/PB/turnover fields from cached provider",
      "payload": {
        "pe_ttm": 31.2,
        "pb": 2.6,
        "turnover_rate": 4.1
      }
    }
  ]
}
```

Rules:

- Reject items with `published_date > as_of_date`.
- Keep source references visible.
- Do not overwrite strategy market data.

**Task M33.2: Add import validation**

Run:

```bash
PYTHONPATH=src:. pytest -q tests/test_agent_external_data_service.py
```

Expected:

```text
passed
```

**Task M33.3: Improve Agent snapshot language**

The snapshot should clearly separate:

- system deterministic review facts
- cached technical data
- cached fundamental data
- cached news/announcement data
- cached sentiment data
- missing data warnings

The adapter prompt/output should keep Chinese labels for Dashboard and reports.

**Task M33.4: Dashboard evidence drawer**

Agent detail drawer must show:

- `TradingAgents 输出`
- `系统复盘原始数据`
- `外部证据`
- `未接入/缺失`
- `不直接改变交易计划`

**M33 Acceptance:**

```bash
PYTHONPATH=src:. pytest -q tests/test_agent_external_data_service.py tests/test_agent_review_service.py tests/test_tradingagents_adapter.py tests/test_daily_report.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

---

## M34: Paper Promotion Scorecard

**Goal:** Turn "minimum 10 paper trades" into a useful promotion dashboard: trade sample, closed P/L, adherence, data-quality incidents, and recent pipeline health.

**Files:**
- Modify: `src/pgc_trading/services/operational_readiness_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/styles.css`
- Test: `tests/test_operational_readiness_service.py`
- Test: `tests/test_cli_main.py`
- Test: `tests/test_daily_report.py`
- Test: `tests/test_dashboard_static.py`

**Task M34.1: Extend readiness result**

Add fields:

```python
closed_trades_count: int
win_rate: float | None
realized_pnl: float
avg_slippage: float | None
last_pipeline_status: str | None
promotion_blockers: list[str]
promotion_warnings: list[str]
```

Rules:

- Promotion still blocks when executed trade count is below 10.
- Promotion blocks when ledger invariants fail.
- Promotion blocks when open blocker data-quality events exist.
- Promotion warns, not blocks, when Agent evidence is missing.

**Task M34.2: CLI output**

Expected:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main paper-readiness --date 20260511 --account paper-main --db-path data/pgc_trading.db
```

Output shape:

```text
readiness=blocked
trades_count=2
closed_trades_count=0
win_rate=none
realized_pnl=0.0
promotion_blockers=MIN_PAPER_TRADES_NOT_MET
```

**Task M34.3: Dashboard scorecard**

Add a compact scorecard near account readiness:

- `样本交易`
- `已闭环交易`
- `累计实现盈亏`
- `胜率`
- `当前阻断`
- `晋级 live 前还差什么`

Avoid making this a marketing-style hero. It should be dense, quiet, and operational.

**M34 Acceptance:**

```bash
PYTHONPATH=src:. pytest -q tests/test_operational_readiness_service.py tests/test_cli_main.py tests/test_daily_report.py tests/test_dashboard_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

---

## Reviewer Checklist

For every submitted session:

1. Confirm scope with:

```bash
git diff --stat
```

2. Run the task-specific tests in the section.

3. Run full verification before merge:

```bash
PYTHONPATH=src:. pytest -q
git diff --check
node --check web/dashboard/app.js
```

4. Reject changes that:

- let TradingAgents mutate trades, plans, positions, market data, or readiness gates
- allow non-dry API writes without operator and idempotency key
- expose API write token in health payload, logs, Dashboard text, or reports
- let Dashboard record a trade for the wrong date or a future plan
- make scheduled jobs write without backups
- hide missing fundamental, news, or sentiment data
- bypass ledger audit before daily pipeline writes

## Immediate Next Actions

1. Session A: implement M28 runbook acceptance.
2. Session D: implement M32 API write-token guard.
3. Ops session on 2026-05-11: execute M29 open checkpoint.
4. Session B: implement M30 open execution service after the 2026-05-11 workflow reveals any remaining confusion.
5. Session C/E/F can run in parallel once A/D are green.
