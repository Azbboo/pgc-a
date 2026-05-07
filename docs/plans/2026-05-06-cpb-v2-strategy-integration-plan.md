# CPB V2 Strategy Integration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add the researched CPB V2 strategy as a first-class strategy version in the PGC system without replacing `cpb_6157@2026-05-03`.

**Architecture:** CPB V2 stays inside the existing `contracting_pullback` strategy family as a separate strategy version. Research CSV/script artifacts are treated as source references only; production logic must move into pure strategy/feature modules under `src/pgc_trading`. Daily review, portfolio planning, execution recording, and observation-sleeve behavior must remain separate service responsibilities.

**Tech Stack:** Python 3, dataclasses, SQLite strategy governance tables, local `unittest`, existing `DailyReviewService` and feature snapshot pipeline.

---

## 1. Source Conversation Summary

Source thread:

```text
019dfc9f-4bd6-7203-866e-d914eb250945
```

Thread name:

```text
复盘今日数据和池内股票表现
```

Useful research artifacts currently present in the workspace:

- `scripts/backtest_cpb_v2_strategy.py`
- `reports/cpb_v2_strategy.md`
- `data/cpb_v2_strategy_trades.csv`
- `data/cpb_v2_current_plan.csv`

Important findings from that conversation:

- CPB V1 can identify strong buy points, but exits are too short for "先洗后拉" stocks.
- Guangpu stock example showed a high CPB buy-point score, short-term drawdown, then later large upside.
- The optimization should not overwrite V1; it should be a new V2 strategy version.
- Securities industry names should be excluded from CPB V2.
- Strong elastic names can use a split plan: short-term sleeve plus observation sleeve.

## 2. CPB V2 Rules To Preserve

### Entry Filters

CPB V2 starts from the existing contracting-pullback bullish-candle signal, then adds:

| Rule | Value |
| --- | --- |
| Exclude securities | `industry != "证券"` |
| Minimum age after pool entry | `trigger_age_trading_days >= 6` |
| Do not chase high open | next open no more than `+2%` above trigger close |
| Avoid weak crash open | next open no less than `-3%` below trigger close |

### Observation Sleeve Eligibility

A stock can receive observation-sleeve treatment only when all are true:

| Rule | Value |
| --- | --- |
| Industry | one of elastic industries |
| Big-winner potential score | `>= 65` |
| CPB buy-point score | `>= 120` |
| Bull candle body | `>= 2%` |
| Trigger day pct change | `>= 1.7%` |
| Trigger amount to MA10 | `>= 0.75` |
| Amount contraction ratio | `<= 0.85` |

Elastic industries from the research script:

```text
半导体, 元器件, 通信设备, 电气设备, 专用机械, 软件服务, IT设备,
汽车配件, 医疗保健, 电器仪表, 工程机械, 机械基件, 互联网
```

### Position Policy

For observation-sleeve eligible stocks:

```text
70% short-term sleeve + 30% observation sleeve
```

Observation sleeve exit:

```text
+25% take profit, -15% hard stop, max 20 trading days
```

For non-observation stocks:

```text
normal short-term CPB handling, T+2/T+5 discipline unchanged
```

## 3. Work Package Summary

| Task | Status | Owner Scope | Output |
| --- | --- | --- | --- |
| CPB2-001 Strategy parameter module | done | `src/pgc_trading/strategies/` | deterministic params and hash |
| CPB2-002 Strategy registry/seed support | done | `storage/seed.py`, tests | seed both V1 and V2 versions |
| CPB2-003 Feature input enrichment | done | `features/`, services/tests | industry and potential-score inputs without future data |
| CPB2-004 Pure V2 decision engine | done | `strategies/`, tests | entry/observation-sleeve decisions |
| CPB2-005 DailyReviewService strategy dispatch | done | services/tests | run V1 or V2 by strategy version |
| CPB2-006 Replay/golden validation | done | tests/fixtures/replay | no-future V2 regression |
| CPB2-007 Documentation and supervision update | done | docs/reports | supervision recorded; handoff ready |

## 4. Task Details

### CPB2-001: Strategy Parameter Module

**Files:**

- Create: `src/pgc_trading/strategies/cpb_v2.py`
- Create: `tests/test_cpb_v2_params.py`

**Goal:** Define CPB V2 params without importing research scripts or pandas.

**Implementation notes:**

- Use a frozen dataclass.
- Include only deterministic rule parameters.
- Include `canonical_json()` and `params_hash()`, matching the style of `cpb_6157.py`.
- Do not include future returns or backtest labels.

**Expected constants:**

```python
STRATEGY_KEY = "cpb_v2"
STRATEGY_VERSION = "cpb_v2@2026-05-06"
STRATEGY_FAMILY_KEY = "contracting_pullback"
```

**Acceptance criteria:**

- Params hash is stable.
- `variant_id == "cpb_v2"`.
- Params JSON contains entry filters, observation-sleeve thresholds, and sleeve sizing.

### CPB2-002: Strategy Registry/Seed Support

**Files:**

- Modify: `src/pgc_trading/storage/seed.py`
- Modify: `tests/test_reference_seed.py`

**Goal:** Seed both V1 and V2 strategy versions idempotently.

**Implementation notes:**

- Keep one strategy family: `contracting_pullback`.
- Seed existing `cpb_6157@2026-05-03` unchanged.
- Seed new `cpb_v2@2026-05-06` as status `candidate` or `paper`, depending user approval.
- Initial recommendation: `candidate`, because sample size is still small and V2 includes new observation-sleeve logic.
- `agent_policy` remains `advisory`.

**Acceptance criteria:**

- Re-running seed is idempotent.
- Both parameter sets exist.
- Existing tests for V1 still pass.
- V2 does not become default strategy unless explicitly configured.

### CPB2-003: Feature Input Enrichment

**Files:**

- Modify or create under: `src/pgc_trading/features/`
- Modify if needed: `src/pgc_trading/services/daily_review_service.py`
- Create: `tests/test_cpb_v2_feature_inputs.py`

**Goal:** Make CPB V2 inputs available without reading ignored `data/*.csv` directly in production services.

**Required inputs:**

- industry;
- trigger age in trading days;
- trigger close;
- next planned buy date;
- big-winner potential score or equivalent persisted feature;
- existing CPB shape features.

**Design constraint:**

- If potential score is not yet persisted in target schema, V2 must return a clear missing-input warning or remain in candidate/research mode.
- Do not silently read `data/pgc_big_winner_scores.csv` from production code.

**Acceptance criteria:**

- Missing industry blocks or downgrades V2 decision with a clear reason.
- Missing potential score does not crash.
- No future bar after review date is used for signal scoring.

### CPB2-004: Pure V2 Decision Engine

**Files:**

- Create or modify: `src/pgc_trading/strategies/cpb_v2.py`
- Create: `tests/test_cpb_v2_decisions.py`

**Goal:** Move these research-script functions into pure tested production code:

- `is_v2_trade`
- `is_swing_eligible`
- `position_plan`

**Rules:**

- Input is a plain dataclass or dict of already-visible features.
- Output includes:
  - `eligible: bool`
  - `skip_reason: str | None`
  - `observation_sleeve: bool`
  - `short_sleeve_weight`
  - `observation_sleeve_weight`
  - `decision_notes`

**Acceptance criteria:**

- Securities are excluded.
- Age `< 6` is excluded.
- Gap above `+2%` is excluded.
- Gap below `-3%` is excluded.
- Elastic high-score setup gets `70/30`.
- Non-elastic valid setup gets short sleeve only.

### CPB2-005: DailyReviewService Strategy Dispatch

**Files:**

- Modify: `src/pgc_trading/services/daily_review_service.py`
- Create or modify tests: `tests/test_daily_review_service.py`

**Goal:** Let daily review run V1 or V2 by strategy version without hard-coding only `cpb_6157`.

**Current issue:**

`DailyReviewService` currently rejects strategy keys other than `cpb_6157`.

**Implementation direction:**

- Add a small strategy registry/dispatcher, for example:

```text
strategy_key -> feature builder + decision/scoring adapter
```

- Keep V1 behavior exactly unchanged.
- V2 should enrich `features_json` with human-readable V2 decisions:
  - non-security filter result;
  - no-chase result;
  - observation-sleeve flag;
  - position split recommendation.

**Out of scope:**

- Do not create trades or positions here.
- Do not implement observation-sleeve execution in `DailyReviewService`.
- Do not call TradingAgents.

**Acceptance criteria:**

- V1 tests remain unchanged.
- V2 strategy version can produce strategy signals in dry-run fixtures.
- V2 daily pick remains at most one per strategy run.
- V2 features do not include future return labels.

### CPB2-006: Replay/Golden Validation

**Files:**

- Create: `tests/test_cpb_v2_replay.py`
- Create fixtures only under: `tests/fixtures/replay/`

**Goal:** Preserve the research insight without overfitting silently.

**Golden examples to include:**

- A securities stock is filtered.
- A high-chase open is filtered.
- A valid normal CPB setup passes.
- A valid elastic high-score setup receives observation-sleeve recommendation.

**Acceptance criteria:**

- Replay data is visible only up to review date.
- Expected decisions are deterministic.
- No fixture includes future winner/loser labels as inputs.

### CPB2-007: Documentation and Supervision Update

**Files:**

- Modify: `docs/plans/2026-05-06-pgc-development-supervision-plan.md`
- Create or update: `reports/cpb_v2_strategy.md` only if needed.

**Acceptance criteria:**

- Main supervision board includes CPB V2 integration status.
- CPB V2 is described as a candidate strategy version, not a replacement for V1.
- Open risks are listed:
  - small sample size;
  - potential-score persistence not fully modeled yet;
  - observation-sleeve execution requires portfolio lifecycle follow-up.

## 5. Quality Gate

Run after each completed CPB2 task:

```bash
PYTHONPATH=/Users/azboo/Desktop/Person/pgc/src python3 -m unittest discover -s /Users/azboo/Desktop/Person/pgc/tests
PYTHONPATH=/Users/azboo/Desktop/Person/pgc/src python3 -m compileall -q /Users/azboo/Desktop/Person/pgc/src /Users/azboo/Desktop/Person/pgc/tests
TOKEN_PREFIX="${PGC_TOKEN_SCAN_PREFIX:-replace-with-known-token-prefix}" rg -n "$TOKEN_PREFIX" /Users/azboo/Desktop/Person/pgc --glob '!data/backups/**'
```

Expected:

- tests OK;
- compile command exits 0;
- secret scan has no matches.

## 6. Handoff Prompt

Use this prompt in a new development session:

```text
你负责 PGC 项目的 CPB2 策略接入工作。

请先阅读：
- /Users/azboo/Desktop/Person/pgc/docs/plans/2026-05-06-cpb-v2-strategy-integration-plan.md
- /Users/azboo/Desktop/Person/pgc/docs/plans/2026-05-06-pgc-development-supervision-plan.md
- /Users/azboo/Desktop/Person/pgc/reports/cpb_v2_strategy.md
- /Users/azboo/Desktop/Person/pgc/scripts/backtest_cpb_v2_strategy.py
- /Users/azboo/Desktop/Person/pgc/src/pgc_trading/strategies/cpb_6157.py
- /Users/azboo/Desktop/Person/pgc/src/pgc_trading/services/daily_review_service.py

目标：
把 CPB V2 作为新策略版本 cpb_v2@2026-05-06 接入系统，不覆盖 cpb_6157@2026-05-03。

硬性要求：
- 不修改真实 data/pgc_trading.db。
- 不把 token、服务器密码、未来收益标签写入代码、文档、测试或 fixture。
- DailyReviewService 只产出信号和每日候选，不创建成交或持仓。
- V2 用到的行业和潜力分必须有明确来源；缺失时要有清晰降级或阻断。
- 完成后汇报 changed files、commands、test summary、open risks。

先从 CPB2-001 和 CPB2-004 开始。
```
