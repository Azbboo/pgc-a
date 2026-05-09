# M35-M42 Market Review And Strategy Evolution Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a full-market review layer that analyzes market regime, sector rotation, stock-level leadership, news, sentiment, persistence, and next-trading-day plan fit, then feeds a controlled strategy-evolution loop without letting unverified narrative automatically mutate trades.

**Architecture:** Keep the deterministic CPB strategy and portfolio ledger as the trading source of truth. Add a separate market-review domain with provider-tagged snapshots, sector/stock ranks, external evidence, market-plan links, and strategy hypotheses. Full-market review can annotate, warn, and generate research tasks; it must not directly create, cancel, or execute trade plans in v1.

**Tech Stack:** Python services and CLI, SQLite migration `012_market_review`, provider-agnostic JSON importers, Tushare/yfinance-compatible market data primitives, FastAPI read routes, static Dashboard tabs/drawers, Markdown/JSON reports, pytest/unittest.

---

## Product Scope

The full-market review must answer these questions every trading day:

1. **今天市场处于什么状态？**
   - index trend
   - breadth
   - volume/turnover
   - limit-up/limit-down pressure if data is available
   - risk-on/risk-off classification

2. **哪些板块强，强在哪里，是否持续？**
   - top sectors by return, volume, breadth, and leadership concentration
   - 3/5/10 trading-day persistence
   - first-day burst vs sustained trend
   - sector rotation compared with previous review

3. **板块内哪些个股是真正带队？**
   - sector constituents ranked by return, volume, score, and CPB feature fit
   - leader/follower distinction
   - whether the strategy candidate belongs to a strong, weakening, or unrelated sector

4. **新闻和情绪支持还是冲突？**
   - market-wide news
   - sector news
   - stock news/announcements
   - sentiment direction and confidence
   - explicit missing-data labels

5. **对下一个交易日计划有什么管理意义？**
   - plan is aligned with market context
   - plan needs manual review
   - plan has external risk
   - plan has weak sector confirmation
   - plan is only strategy-valid, not market-confirmed

6. **如何进化策略？**
   - generate evidence-backed hypotheses
   - run backtests/replays before changing live paper behavior
   - record accepted/rejected hypotheses
   - never overwrite active strategy parameters from a narrative report

## Parallel Work Map

| Track | Task | Can Run In Parallel? | Depends On | Suggested Session |
| --- | --- | --- | --- | --- |
| M35 | Market review schema and migration | Yes, should be first | Current storage migration style | Session A |
| M36 | Market breadth and regime service | Yes after M35 table contract | `market_bars`, `daily_basic_snapshots` | Session B |
| M37 | Sector rotation and sector-stock leadership | Yes after M35 | sector membership importer | Session C |
| M38 | News and sentiment evidence importer | Yes after M35 | external evidence fixture contract | Session D |
| M39 | Plan-context linking and risk annotations | After M36/M37 partially | `trade_plans`, `daily_picks` | Session E |
| M40 | Strategy evolution hypothesis loop | Yes after M35 | review outputs and reports | Session F |
| M41 | Dashboard full-market review tab | After M36-M39 API shapes settle | API read routes | Session G |
| M42 | Daily pipeline integration and reports | After M36-M40 | `daily_pipeline_service` | Review session |

Recommended order:

1. M35 first to freeze data contracts.
2. M36, M37, M38, and M40 can run in parallel after M35.
3. M39 starts when M36/M37 expose stable summary objects.
4. M41 should wait until M36-M39 read API shapes are stable.
5. M42 integrates everything into the daily pipeline after the pieces are tested.

---

## M35: Market Review Schema And Data Contracts

**Goal:** Create a clean database boundary for market-wide review data without polluting strategy, portfolio, or Agent tables.

**Files:**
- Create: `src/pgc_trading/storage/migrations/012_market_review.sql`
- Modify: `src/pgc_trading/storage/schema.sql`
- Test: `tests/test_schema_market_review_migration.py`
- Test: `tests/test_migrations.py`

**Task M35.1: Add migration tests first**

Create tests asserting these tables exist:

- `market_review_runs`
- `market_regime_snapshots`
- `sector_daily_snapshots`
- `sector_constituents`
- `market_external_items`
- `market_plan_contexts`
- `strategy_hypotheses`

Run:

```bash
PYTHONPATH=src:. pytest -q tests/test_schema_market_review_migration.py
```

Expected:

```text
fail because migration does not exist
```

**Task M35.2: Add migration `012_market_review.sql`**

Required table contracts:

```sql
CREATE TABLE IF NOT EXISTS market_review_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  as_of_date TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('started', 'completed', 'failed')),
  provider_manifest_json TEXT NOT NULL DEFAULT '{}',
  coverage_json TEXT NOT NULL DEFAULT '{}',
  summary_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at TEXT,
  UNIQUE(as_of_date)
);
```

```sql
CREATE TABLE IF NOT EXISTS market_regime_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_review_run_id INTEGER NOT NULL,
  as_of_date TEXT NOT NULL,
  regime TEXT NOT NULL CHECK (regime IN ('risk_on', 'neutral', 'risk_off', 'unknown')),
  breadth_score REAL,
  trend_score REAL,
  volume_score REAL,
  sentiment_score REAL,
  persistence_score REAL,
  summary TEXT NOT NULL,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (market_review_run_id) REFERENCES market_review_runs(id),
  UNIQUE(market_review_run_id)
);
```

```sql
CREATE TABLE IF NOT EXISTS sector_daily_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_review_run_id INTEGER NOT NULL,
  as_of_date TEXT NOT NULL,
  sector_code TEXT NOT NULL,
  sector_name TEXT NOT NULL,
  provider TEXT NOT NULL,
  rank_overall INTEGER,
  return_1d REAL,
  return_3d REAL,
  return_5d REAL,
  return_10d REAL,
  breadth_score REAL,
  volume_score REAL,
  persistence_score REAL,
  leader_count INTEGER NOT NULL DEFAULT 0,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (market_review_run_id) REFERENCES market_review_runs(id),
  UNIQUE(market_review_run_id, sector_code)
);
```

```sql
CREATE TABLE IF NOT EXISTS sector_constituents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_review_run_id INTEGER NOT NULL,
  sector_code TEXT NOT NULL,
  sector_name TEXT NOT NULL,
  ts_code TEXT NOT NULL,
  name TEXT,
  rank_in_sector INTEGER,
  role TEXT NOT NULL DEFAULT 'member'
    CHECK (role IN ('leader', 'follower', 'member', 'weak')),
  score REAL,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (market_review_run_id) REFERENCES market_review_runs(id),
  UNIQUE(market_review_run_id, sector_code, ts_code)
);
```

```sql
CREATE TABLE IF NOT EXISTS market_external_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  as_of_date TEXT NOT NULL,
  scope_type TEXT NOT NULL CHECK (scope_type IN ('market', 'sector', 'stock')),
  scope_key TEXT NOT NULL,
  item_type TEXT NOT NULL
    CHECK (item_type IN ('news', 'announcement', 'sentiment', 'policy', 'risk_note', 'research_note')),
  provider TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  url TEXT,
  sentiment TEXT NOT NULL DEFAULT 'unknown'
    CHECK (sentiment IN ('positive', 'neutral', 'negative', 'mixed', 'unknown')),
  importance TEXT NOT NULL DEFAULT 'unknown'
    CHECK (importance IN ('low', 'medium', 'high', 'unknown')),
  published_date TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  source_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(provider, source_hash)
);
```

```sql
CREATE TABLE IF NOT EXISTS market_plan_contexts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_review_run_id INTEGER NOT NULL,
  trade_plan_id INTEGER NOT NULL,
  alignment TEXT NOT NULL
    CHECK (alignment IN ('aligned', 'neutral', 'conflict', 'unknown')),
  risk_level TEXT NOT NULL
    CHECK (risk_level IN ('low', 'medium', 'high', 'unknown')),
  management_action TEXT NOT NULL
    CHECK (management_action IN ('proceed', 'manual_review', 'consider_cancel', 'unknown')),
  rationale TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (market_review_run_id) REFERENCES market_review_runs(id),
  FOREIGN KEY (trade_plan_id) REFERENCES trade_plans(id),
  UNIQUE(market_review_run_id, trade_plan_id)
);
```

```sql
CREATE TABLE IF NOT EXISTS strategy_hypotheses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  as_of_date TEXT NOT NULL,
  hypothesis_type TEXT NOT NULL,
  title TEXT NOT NULL,
  rationale TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  proposed_change_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'proposed'
    CHECK (status IN ('proposed', 'testing', 'accepted', 'rejected', 'archived')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Add useful indexes by date, sector, stock, and plan id.

**Task M35.3: Update base schema and migrations list**

Mirror the migration in `src/pgc_trading/storage/schema.sql`.

Run:

```bash
PYTHONPATH=src:. pytest -q tests/test_schema_market_review_migration.py tests/test_migrations.py
```

Expected:

```text
passed
```

**M35 Acceptance:**

```bash
PYTHONPATH=src:. pytest -q tests/test_schema_market_review_migration.py tests/test_migrations.py
PYTHONPATH=src:. pytest -q
git diff --check
```

---

## M36: Market Breadth And Regime Service

**Goal:** Compute a deterministic market regime snapshot from existing market data, with explicit coverage warnings.

**Files:**
- Create: `src/pgc_trading/services/market_review_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Test: `tests/test_market_review_service.py`
- Test: `tests/test_cli_market_review.py`

**Task M36.1: Define service tests**

Test scenarios:

- enough market bars produce `regime=risk_on`, `neutral`, or `risk_off`
- missing market bars produce `status=blocked`
- dry-run does not write `market_review_runs`
- apply mode is idempotent by `as_of_date`
- future data after `as_of_date` is ignored

Run:

```bash
PYTHONPATH=src:. pytest -q tests/test_market_review_service.py
```

Expected:

```text
fail because service does not exist
```

**Task M36.2: Implement request/result dataclasses**

```python
@dataclass(frozen=True)
class RunMarketReviewRequest:
    as_of_date: str
    universe: str = "market_bars"
    min_coverage: float = 0.8

@dataclass(frozen=True)
class MarketRegimeResult:
    market_review_run_id: int | None
    as_of_date: str
    status: str
    regime: str
    breadth_score: float | None
    trend_score: float | None
    volume_score: float | None
    persistence_score: float | None
    coverage_ratio: float
    summary: str
    warnings: list[str]
```

Suggested deterministic metrics:

- `advance_decline_ratio`: stocks with close > previous close
- `above_ma5_ratio`: stocks with close > 5-day moving average
- `volume_expansion_ratio`: stocks with volume above 5-day average
- `new_5d_high_ratio`
- `new_5d_low_ratio`

First version can compute from available `market_bars`; index-specific logic can be added later.

**Task M36.3: Add CLI**

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main market-review run \
  --date 20260508 \
  --db-path data/pgc_trading.db \
  --dry-run
```

Expected output:

```text
market_review_status=success
as_of_date=20260508
regime=neutral
coverage_ratio=...
market_review_run_id=none
```

Apply:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main market-review run \
  --date 20260508 \
  --db-path data/pgc_trading.db \
  --operator azboo \
  --apply
```

Expected:

```text
market_review_run_id=<id>
changed=true|false
```

**M36 Acceptance:**

```bash
PYTHONPATH=src:. pytest -q tests/test_market_review_service.py tests/test_cli_market_review.py
PYTHONPATH=src:. pytest -q
git diff --check
```

---

## M37: Sector Rotation And Stock Leadership

**Goal:** Analyze from board/sector level down to constituent stocks, with persistence and leadership concentration.

**Files:**
- Modify: `src/pgc_trading/services/market_review_service.py`
- Create: `src/pgc_trading/services/sector_rotation_service.py`
- Create: `tests/fixtures/market_review/sector_memberships_20260508.json`
- Test: `tests/test_sector_rotation_service.py`
- Test: `tests/test_market_review_service.py`

**Task M37.1: Add sector membership importer**

Support provider-agnostic JSON:

```json
{
  "as_of_date": "20260508",
  "provider": "manual_fixture",
  "sectors": [
    {
      "sector_code": "PHARMA_PACKAGING",
      "sector_name": "医药包装",
      "members": [
        {"ts_code": "301188.SZ", "name": "力诺药包"}
      ]
    }
  ]
}
```

CLI:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main market-review import-sectors \
  --date 20260508 \
  --input tests/fixtures/market_review/sector_memberships_20260508.json \
  --db-path data/pgc_trading.db \
  --operator azboo \
  --apply
```

Rules:

- No future memberships.
- Import is idempotent by provider/date/sector/stock.
- Missing stock market bars become warnings, not silent zeros.

**Task M37.2: Compute sector scores**

For each sector:

- `return_1d`
- `return_3d`
- `return_5d`
- `return_10d`
- `breadth_score`
- `volume_score`
- `persistence_score`
- `leader_count`

Leadership rules:

- `leader`: top 20% in sector score or top 3 when sector has many members
- `follower`: positive contribution but not leader
- `weak`: negative contribution or below sector median

**Task M37.3: Persist sector snapshots**

Apply mode writes:

- `sector_daily_snapshots`
- `sector_constituents`

Dry-run returns the same result shape without writes.

**M37 Acceptance:**

```bash
PYTHONPATH=src:. pytest -q tests/test_sector_rotation_service.py tests/test_market_review_service.py
PYTHONPATH=src:. pytest -q
git diff --check
```

---

## M38: Market News And Sentiment Evidence Importer

**Goal:** Import market/sector/stock news and sentiment into a cache that reports can cite honestly.

**Files:**
- Create: `src/pgc_trading/services/market_external_data_service.py`
- Create: `tests/fixtures/market_review/external_items_20260508.json`
- Modify: `src/pgc_trading/cli/main.py`
- Test: `tests/test_market_external_data_service.py`
- Test: `tests/test_cli_market_review.py`

**Task M38.1: Define fixture format**

```json
{
  "as_of_date": "20260508",
  "provider": "manual_fixture",
  "items": [
    {
      "scope_type": "market",
      "scope_key": "A_SHARE",
      "item_type": "policy",
      "published_date": "20260508",
      "title": "市场政策摘要",
      "summary": "不超过 200 字的摘要",
      "sentiment": "neutral",
      "importance": "medium",
      "url": null,
      "metadata": {}
    },
    {
      "scope_type": "sector",
      "scope_key": "PHARMA_PACKAGING",
      "item_type": "news",
      "published_date": "20260508",
      "title": "医药包装板块新闻",
      "summary": "摘要",
      "sentiment": "positive",
      "importance": "medium"
    },
    {
      "scope_type": "stock",
      "scope_key": "301188.SZ",
      "item_type": "announcement",
      "published_date": "20260508",
      "title": "力诺药包公告摘要",
      "summary": "摘要",
      "sentiment": "unknown",
      "importance": "unknown"
    }
  ]
}
```

Rules:

- Reject `published_date > as_of_date`.
- Reject unknown `scope_type`, `item_type`, sentiment, or importance.
- Compute `source_hash` from provider, scope, title, published date, and summary.
- Do not perform live web fetch in this service.

**Task M38.2: Add CLI**

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main market-review external-data import \
  --date 20260508 \
  --input tests/fixtures/market_review/external_items_20260508.json \
  --db-path data/pgc_trading.db \
  --operator azboo \
  --apply
```

Expected:

```text
market_external_import_status=success
inserted=...
duplicates=...
invalid=0
```

**Task M38.3: Coverage summary**

Expose coverage by scope:

```json
{
  "market": "available",
  "sector": "partial",
  "stock": "partial",
  "sentiment": "partial",
  "news": "available"
}
```

Missing evidence must be shown as missing, not filled with generated assumptions.

**M38 Acceptance:**

```bash
PYTHONPATH=src:. pytest -q tests/test_market_external_data_service.py tests/test_cli_market_review.py
PYTHONPATH=src:. pytest -q
git diff --check
```

---

## M39: Next-Day Plan Context And Management Link

**Goal:** Connect the full-market review to tomorrow's plan as a documented management argument, without automatically changing the plan.

**Files:**
- Create: `src/pgc_trading/services/market_plan_context_service.py`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `src/pgc_trading/cli/main.py`
- Test: `tests/test_market_plan_context_service.py`
- Test: `tests/test_daily_report.py`
- Test: `tests/test_cli_market_review.py`

**Task M39.1: Add plan context tests**

Cases:

- candidate belongs to top persistent sector -> `alignment=aligned`, `management_action=proceed`
- candidate sector is weak but stock signal is strong -> `alignment=conflict`, `management_action=manual_review`
- high-importance negative stock item -> `risk_level=high`, `management_action=manual_review`
- no sector/news data -> `alignment=unknown`, `management_action=manual_review`

Run:

```bash
PYTHONPATH=src:. pytest -q tests/test_market_plan_context_service.py
```

Expected:

```text
fail before implementation
```

**Task M39.2: Implement context output**

Result:

```python
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

Important rule:

- `management_action=consider_cancel` is only a recommendation label.
- It must not call `PortfolioPlanningService.cancel_plan`.

**Task M39.3: Add CLI**

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main market-review link-plan \
  --date 20260508 \
  --trade-plan-id 2 \
  --db-path data/pgc_trading.db \
  --operator azboo \
  --apply
```

Expected:

```text
market_plan_context_status=success
alignment=...
management_action=...
trade_plan_id=2
```

**Task M39.4: Add daily report section**

Add section:

```markdown
## 全市场复盘与明日计划关系
```

Content:

- market regime
- top sectors
- candidate sector fit
- news/sentiment fit
- management action
- reminder that this does not auto-change plan

**M39 Acceptance:**

```bash
PYTHONPATH=src:. pytest -q tests/test_market_plan_context_service.py tests/test_daily_report.py tests/test_cli_market_review.py
PYTHONPATH=src:. pytest -q
git diff --check
```

---

## M40: Strategy Evolution Hypothesis Loop

**Goal:** Convert daily market-review observations into testable strategy hypotheses, not immediate live behavior changes.

**Files:**
- Create: `src/pgc_trading/services/strategy_evolution_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `reports/operational_runbook_design.md`
- Test: `tests/test_strategy_evolution_service.py`
- Test: `tests/test_cli_market_review.py`

**Task M40.1: Generate hypotheses**

Examples:

- "Only buy CPB candidates when their sector persistence score is above threshold."
- "Reduce position size when market regime is risk_off."
- "Require manual review for candidates with high negative stock news importance."
- "Boost rank when stock is sector leader and sector is in top 5."

Rules:

- Store in `strategy_hypotheses`.
- Include evidence JSON.
- Include proposed change JSON.
- Status starts as `proposed`.
- Do not update `strategies/params/*.json`.

CLI:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main strategy-evolution propose \
  --date 20260508 \
  --db-path data/pgc_trading.db \
  --operator azboo \
  --apply
```

**Task M40.2: Add hypothesis review commands**

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main strategy-evolution list --status proposed
PYTHONPATH=src python3 -m pgc_trading.cli.main strategy-evolution mark --hypothesis-id 1 --status testing --operator azboo
PYTHONPATH=src python3 -m pgc_trading.cli.main strategy-evolution mark --hypothesis-id 1 --status rejected --operator azboo
```

**Task M40.3: Runbook strategy-evolution policy**

Document:

- hypothesis must pass replay/backtest before accepted
- accepted hypothesis creates a separate strategy-version task
- active paper/live strategy params are not mutated by reports

**M40 Acceptance:**

```bash
PYTHONPATH=src:. pytest -q tests/test_strategy_evolution_service.py tests/test_cli_market_review.py tests/test_operational_runbook_static.py
PYTHONPATH=src:. pytest -q
git diff --check
```

---

## M41: Dashboard Full-Market Review Tab

**Goal:** Add a usable Dashboard view for full-market review that is not a flat wall of cards.

**Files:**
- Modify: `src/pgc_trading/api/services.py`
- Modify: `src/pgc_trading/api/routes.py`
- Modify: `web/dashboard/index.html`
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/styles.css`
- Test: `tests/test_api_read_routes.py`
- Test: `tests/test_dashboard_static.py`

**Task M41.1: Add read API**

Routes:

```text
GET /api/market-reviews?limit=20
GET /api/market-reviews/{as_of_date}
GET /api/market-reviews/{as_of_date}/sectors
GET /api/market-reviews/{as_of_date}/plan-context?trade_plan_id=2
```

Read-only only. No write route in v1 Dashboard.

**Task M41.2: Dashboard IA**

Add a top-level tab:

```text
全市场
```

Sections:

- market regime strip
- sector rotation table
- sector detail drawer
- stock leadership table inside selected sector
- news/sentiment drawer
- next-plan relationship panel
- strategy hypotheses list

Use drawers/modals for details:

- sector detail
- stock evidence
- news/sentiment source list
- hypothesis detail

Avoid:

- huge flat cards
- hidden source provenance
- generated claims without evidence labels

**Task M41.3: Static dashboard checks**

`tests/test_dashboard_static.py` should assert:

- `全市场`
- `market-reviews`
- `板块轮动`
- `持续性`
- `情绪`
- `明日计划关系`
- no write mutation endpoint is called from the market-review tab

Run:

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_api_read_routes.py tests/test_dashboard_static.py
```

Expected:

```text
passed
```

**M41 Acceptance:**

```bash
node --check web/dashboard/app.js
PYTHONPATH=src:. pytest -q tests/test_api_read_routes.py tests/test_dashboard_static.py
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

Check desktop and mobile:

- no blank screen
- no overlapping text
- sector drawer opens
- news drawer has source labels
- plan relationship panel is readable

---

## M42: Daily Pipeline Integration And Report Output

**Goal:** Make full-market review part of the daily operating loop, while preserving dry-run safety and idempotency.

**Files:**
- Modify: `src/pgc_trading/services/daily_pipeline_service.py`
- Modify: `scripts/run_daily_pipeline.sh`
- Modify: `src/pgc_trading/reporting/daily_report.py`
- Modify: `reports/operational_runbook_design.md`
- Test: `tests/test_daily_pipeline_service.py`
- Test: `tests/test_cli_daily_pipeline.py`
- Test: `tests/test_daily_report.py`

**Task M42.1: Add pipeline options**

CLI:

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main ops daily-pipeline \
  --date 20260508 \
  --account paper-main \
  --operator azboo \
  --include-market-review \
  --dry-run
```

Shell:

```bash
./scripts/run_daily_pipeline.sh --date 20260508 --account paper-main --operator azboo --include-market-review --dry-run
```

Default decision:

- If full-market review is stable, make it default-on in dry-run.
- Keep apply default explicit until M42 acceptance passes on production.

**Task M42.2: Integrate steps**

Pipeline order:

1. ledger audit
2. daily close
3. Agent review
4. market review
5. plan context linking
6. exit evaluation
7. report refresh

Dry-run:

- no writes to `market_review_runs`
- no writes to reports
- prints `market_review_would_write=true`

Apply:

- backup before writes remains mandatory
- market review is idempotent by date
- plan context is idempotent by review run + trade plan

**Task M42.3: Report output**

`reports/daily_review_YYYYMMDD.md` and JSON should include:

- market regime summary
- top 5 sectors
- sector persistence
- external evidence coverage
- tomorrow plan fit
- strategy hypotheses generated

**M42 Acceptance:**

```bash
bash -n scripts/run_daily_pipeline.sh
PYTHONPATH=src:. pytest -q tests/test_daily_pipeline_service.py tests/test_cli_daily_pipeline.py tests/test_daily_report.py
PYTHONPATH=src:. pytest -q
git diff --check
```

Post-deploy smoke:

```bash
./scripts/run_daily_pipeline.sh --date 20260508 --account paper-main --operator azboo --include-market-review --dry-run
curl -fsS 'http://150.158.121.150:8020/api/market-reviews/20260508'
```

Expected:

```text
pipeline_status=pass
market_review_status=success|skipped
API returns 200 when review exists
```

---

## Review Rules

Reject any change that:

- lets market review automatically create, cancel, publish, or execute trade plans
- stores uncited news/sentiment as if it were factual market data
- uses future news or future prices for an earlier review date
- mutates CPB strategy params from a daily report
- hides missing market, sector, news, or sentiment coverage
- lets TradingAgents or market review bypass ledger audit/readiness gates
- expands Dashboard write surface for market review v1

## Immediate Next Actions

1. Keep M28/M32 as the near-term safety priority.
2. Start M35 in parallel to lay the market-review schema.
3. After M35, run M36/M37/M38/M40 in parallel.
4. Do M39 before Dashboard work so the "明日计划关系" has a real service contract.
5. Do M41/M42 last, then deploy as a separate release.
