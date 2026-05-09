# M39-M46 Market Review Integration Implementation Plan

**Goal:** Integrate the completed full-market review services into next-day plan management, Dashboard read views, daily pipeline output, deployment migration, and strategy-evolution governance without allowing market narrative to auto-mutate trades.

**Architecture:** Treat M36/M37/M38/M40 as analysis producers. M39 creates the management bridge to tomorrow's trade plan. M41 exposes read-only APIs and Dashboard views. M42 plugs market review into the daily pipeline and reports. M43-M46 handle deployment, real-data operations, and strategy-evolution validation.

**Tech Stack:** Python services and CLI, SQLite migration `012_market_review`, FastAPI read routes, static Dashboard JavaScript/CSS, daily pipeline service/script, Markdown/JSON reports, pytest/unittest, remote deployment on port `8020`.

---

## Current State

- Local branch: `codex/m14b-yfinance`
- R0 release checkpoint is complete and remote is aligned through `3ff703e`.
- M39, M41A, M43, and M44 are implemented in this checkpoint.
- M41B, M42, M45, and M46 remain as the next integration wave.
- Verification already run for M39/M41A/M43/M44:
  - targeted tests: `54 passed, 2 skipped`
  - full tests: `308 passed, 3 skipped, 10 subtests passed`
  - `git diff --check`: pass
  - `market-review run --dry-run --date 20260508`: works locally
- Local and remote databases must be checked with `ops health --require-current-migrations` before running M39/M44 commands against a formal database.

## Parallel Work Map

| Track | Task | Status | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- | --- |
| R0 | Commit/push/deploy current M28-M40 and run `012_market_review` | Done | No | Current reviewed code | Release session |
| M39 | Plan-context linking service and report section | Done | Yes | M36/M37/M38 outputs | Session A |
| M41A | Market review read API | Done | Yes | M36-M39 tables | Session B |
| M41B | Dashboard full-market tab | Next | Yes | M41A route contract | Session C |
| M42 | Daily pipeline integration and report output | Next | Yes after M39 | M36-M39 services | Session D |
| M43 | Production market-review runbook and fixtures-to-real-data policy | Done | Yes | M36/M37/M38 CLI | Session E |
| M44 | Strategy hypothesis backtest bridge | Done | Yes | `strategy_hypotheses`, existing replay/backtest tests | Session F |
| M45 | M30 open-execution service alignment | Next | Yes, separate product track | Existing execution services | Session G |
| M46 | M31 scheduled post-close pipeline | Next | After M42 and write-token deploy | `run_daily_pipeline.sh` | Ops session |

Recommended order from this checkpoint:

1. Release the M39/M41A/M43/M44 checkpoint with a normal commit, push, deploy, and migration health check.
2. Run local and remote migration health checks before formal M39/M44 commands.
3. Start M41B and M42 in parallel.
4. Start M45 after the Dashboard contract is clear enough to show market-plan context in the open-execution flow.
5. Start M46 only after M42 is accepted and the scheduled command is stable.

---

## R0: Commit, Push, Deploy, And Migrate

**Goal:** Get the already-reviewed M28-M40 work onto remote/server before building more layers on top.

**Files:**
- No feature code changes expected.
- Commit current M36/M37/M38/M40 files.

**Step 1: Re-run release checks**

```bash
PYTHONPATH=src:. pytest -q
git diff --check
bash -n scripts/deploy_remote.sh
```

Expected:

```text
all tests pass
diff check pass
deploy script parses
```

**Step 2: Commit M36-M40**

Suggested message:

```bash
git add reports/operational_runbook_design.md src/pgc_trading/cli/main.py tests/test_cli_main.py tests/test_operational_runbook_static.py src/pgc_trading/services/market_external_data_service.py src/pgc_trading/services/market_review_service.py src/pgc_trading/services/sector_rotation_service.py src/pgc_trading/services/strategy_evolution_service.py tests/fixtures/market_review tests/test_cli_market_review.py tests/test_market_external_data_service.py tests/test_market_review_service.py tests/test_sector_rotation_service.py tests/test_strategy_evolution_service.py
git commit -m "Add market review services and strategy hypotheses"
```

**Step 3: Push**

```bash
git push origin codex/m14b-yfinance
```

**Step 4: Deploy with write token preserved**

Generate release tag:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main ops version --date 2026-05-09 --git-sha <short-sha>
```

Deploy:

```bash
bash scripts/deploy_remote.sh --release-tag <tag>
```

Expected:

```text
remote migrations include 012_market_review
/api/health returns ok
remote release marker matches tag
```

**Step 5: Post-deploy migration smoke**

```bash
ssh root@150.158.121.150 'PYTHONPATH=/opt/pgc/app/src python3 -m pgc_trading.cli.main strategy-evolution list --db-path /opt/pgc/data/pgc_trading.db --limit 5'
ssh root@150.158.121.150 'PYTHONPATH=/opt/pgc/app/src python3 -m pgc_trading.cli.main market-review run --date 20260508 --db-path /opt/pgc/data/pgc_trading.db --dry-run'
```

Expected:

```text
strategy-evolution list does not fail with missing table
market_review_status=success or blocked with explicit coverage reason
```

---

## M39: Plan Context Linking

**Goal:** Connect full-market review to the next trading plan with explicit management guidance, without creating/canceling/executing plans.

**Files:**
- Create: `src/pgc_trading/services/market_plan_context_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Test: `tests/test_market_plan_context_service.py`
- Test: `tests/test_cli_market_review.py`
- Test: `tests/test_daily_report.py`

**Contract:**

```python
@dataclass(frozen=True)
class LinkMarketPlanContextRequest:
    as_of_date: str
    trade_plan_id: int

@dataclass(frozen=True)
class MarketPlanContextResult:
    market_review_run_id: int
    trade_plan_id: int
    alignment: str
    risk_level: str
    management_action: str
    rationale: str
    evidence: dict[str, object]
```

Allowed values:

- `alignment`: `aligned`, `neutral`, `conflict`, `unknown`
- `risk_level`: `low`, `medium`, `high`, `unknown`
- `management_action`: `proceed`, `manual_review`, `consider_cancel`, `unknown`

Rules:

- It may write only `market_plan_contexts`.
- It must not call `PortfolioPlanningService.cancel_plan`.
- It must not update `trade_plans`, `trades`, `positions`, `daily_picks`, or `strategy_signals`.
- Missing sector/news data should produce `alignment=unknown`, `management_action=manual_review`.

CLI:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main market-review link-plan \
  --date 20260508 \
  --trade-plan-id 2 \
  --db-path data/pgc_trading.db \
  --operator azboo \
  --apply
```

Acceptance:

```bash
PYTHONPATH=src:. pytest -q tests/test_market_plan_context_service.py tests/test_cli_market_review.py tests/test_daily_report.py
PYTHONPATH=src:. pytest -q
git diff --check
```

---

## M41A: Market Review Read API

**Goal:** Expose full-market review as read-only API payloads for Dashboard and future reports.

**Files:**
- Modify: `src/pgc_trading/api/services.py`
- Modify: `src/pgc_trading/api/routes.py`
- Test: `tests/test_api_read_routes.py`
- Test: `tests/test_api_app.py`

Routes:

```text
GET /api/market-reviews?limit=20
GET /api/market-reviews/{as_of_date}
GET /api/market-reviews/{as_of_date}/sectors
GET /api/market-reviews/{as_of_date}/external-items
GET /api/market-reviews/{as_of_date}/hypotheses
GET /api/market-reviews/{as_of_date}/plan-context?trade_plan_id=2
```

Rules:

- Read-only only.
- No Dashboard market-review write endpoints in v1.
- Responses must include source/coverage/missing-data fields.
- If no review exists, return a stable empty state, not a 500.

Acceptance:

```bash
PYTHONPATH=src:. pytest -q tests/test_api_read_routes.py tests/test_api_app.py
PYTHONPATH=src:. pytest -q
git diff --check
```

---

## M41B: Dashboard Full-Market Tab

**Goal:** Add a usable "全市场" Dashboard view with tables and drawers, not another flat wall of cards.

**Files:**
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/styles.css`
- Test: `tests/test_dashboard_static.py`

UI sections:

- market regime strip
- sector rotation table
- sector detail drawer
- stock leadership table inside selected sector
- news/sentiment drawer
- next-plan relationship panel
- strategy hypotheses list

Static assertions:

- `全市场`
- `market-reviews`
- `板块轮动`
- `持续性`
- `情绪`
- `明日计划关系`
- `策略假设`
- no `POST /api/market-reviews`
- no market tab write mutation calls

Acceptance:

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_dashboard_static.py tests/test_api_read_routes.py
PYTHONPATH=src:. pytest -q
git diff --check
```

Manual smoke:

```bash
PGC_API_ENABLE_WRITES=0 .venv/bin/python -m uvicorn 'pgc_trading.api:create_app' --factory --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/dashboard/
```

Check:

- no blank screen
- no overlapping text on desktop/mobile
- sector drawer opens
- evidence drawer shows provider/date/sentiment
- plan-context panel explicitly says it does not auto-change the plan

---

## M42: Daily Pipeline And Report Integration

**Goal:** Make market review part of the repeatable daily close loop.

**Files:**
- Modify: `src/pgc_trading/services/daily_pipeline_service.py`
- Modify: `scripts/run_daily_pipeline.sh`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `reports/operational_runbook_design.md`
- Test: `tests/test_daily_pipeline_service.py`
- Test: `tests/test_cli_daily_pipeline.py`
- Test: `tests/test_daily_report.py`
- Test: `tests/test_operational_runbook_static.py`

Add CLI/script flag:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main ops daily-pipeline --date 20260508 --account paper-main --operator azboo --include-market-review --dry-run
./scripts/run_daily_pipeline.sh --date 20260508 --account paper-main --operator azboo --include-market-review --dry-run
```

Pipeline order:

1. ledger audit
2. daily close
3. TradingAgents review
4. market review
5. plan-context linking
6. exit evaluation
7. report refresh

Dry-run rules:

- no writes to `market_review_runs`
- no writes to `market_plan_contexts`
- no report writes
- print `market_review_would_write=true`

Apply rules:

- backup before writes remains mandatory
- market review idempotent by `as_of_date`
- plan context idempotent by `market_review_run_id + trade_plan_id`

Report section:

```markdown
## 全市场复盘
## 全市场复盘与明日计划关系
```

Acceptance:

```bash
bash -n scripts/run_daily_pipeline.sh
PYTHONPATH=src:. pytest -q tests/test_daily_pipeline_service.py tests/test_cli_daily_pipeline.py tests/test_daily_report.py tests/test_operational_runbook_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

---

## M43: Production Market Review Runbook

**Goal:** Define how real market/sector/news data enters production without pretending fixtures are real sources.

**Files:**
- Modify: `reports/operational_runbook_design.md`
- Create: `reports/market_review_data_source_design.md`
- Test: `tests/test_operational_runbook_static.py`

Document:

- Fixture imports are for tests only.
- Tushare/official cached data is preferred for market and sector facts.
- Manual news/sentiment imports must include provider, title, date, summary, and source hash.
- Missing evidence is acceptable but must be explicit.
- No live web fetch inside daily trading path.

Acceptance:

```bash
PYTHONPATH=src:. pytest -q tests/test_operational_runbook_static.py
git diff --check
```

---

## M44: Strategy Hypothesis Backtest Bridge

**Goal:** Turn M40 hypotheses into replay/backtest tasks before any strategy parameter changes.

**Files:**
- Create: `src/pgc_trading/services/strategy_hypothesis_backtest_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Test: `tests/test_strategy_hypothesis_backtest_service.py`
- Test: `tests/test_cli_market_review.py`

CLI:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main strategy-evolution backtest \
  --hypothesis-id 1 \
  --db-path data/pgc_trading.db \
  --dry-run
```

Rules:

- First version can produce a backtest request artifact instead of changing strategy code.
- `accepted` still must not mutate active params.
- Any accepted hypothesis should create a separate strategy-version task.

Acceptance:

```bash
PYTHONPATH=src:. pytest -q tests/test_strategy_hypothesis_backtest_service.py tests/test_cli_market_review.py
PYTHONPATH=src:. pytest -q
git diff --check
```

---

## M45: Open Execution Alignment

**Goal:** Keep the operational "today do what" workflow aligned with market-plan context.

This is the earlier M30 task, now with market-review context added.

Add to the future open-execution result:

```json
{
  "next_action": "record_buy",
  "market_plan_context": {
    "alignment": "aligned",
    "risk_level": "medium",
    "management_action": "manual_review"
  }
}
```

Rules:

- `management_action=consider_cancel` can display a warning.
- It must not cancel automatically.
- The execution modal must still require operator/idempotency/write token for non-dry writes.

---

## M46: Scheduled Pipeline

**Goal:** Only schedule post-close automation after M42 and write-token deployment are stable.

This is the earlier M31 task, but now the scheduled command should include market-review once M42 is accepted:

```bash
./scripts/run_daily_pipeline.sh --date latest-closed --account paper-main --operator system-daily-pipeline --include-market-review --apply
```

Rules:

- Must run after A-share close.
- Must backup before apply.
- Must preserve API write token through deploy.
- Must log to `/opt/pgc/logs` or `.pgc-runs`.

---

## Reviewer Checklist

For every submitted task:

```bash
git diff --stat
PYTHONPATH=src:. pytest -q
git diff --check
```

Also reject any change that:

- writes `trade_plans`, `trades`, `positions`, or strategy params from market review
- hides missing market/sector/news/sentiment data
- uses future prices or future evidence for an earlier review date
- adds market-review write routes to Dashboard
- lets scheduled pipeline write without backup
- bypasses API write-token requirements for non-dry writes

## Immediate Next Actions

1. Push and deploy the M39/M41A/M43/M44 checkpoint after review.
2. Run `ops health --require-current-migrations` locally and remotely.
3. Start M41B Dashboard full-market tab and M42 daily pipeline/report integration in parallel.
4. Keep M45 and M46 as follow-up tasks after M41B/M42 contracts are stable.
