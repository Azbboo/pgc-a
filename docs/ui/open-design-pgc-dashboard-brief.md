# PGC Dashboard Open Design Brief

Date: 2026-05-04

## Goal

Use Open Design to produce a high-fidelity desktop dashboard prototype for the PGC short-term quant trading workflow.

The prototype is an operator workstation, not a marketing page. It should help one person complete the daily after-close workflow safely:

1. Check data readiness.
2. Run daily review for `cpb_6157@2026-05-03`.
3. Inspect the one daily pick.
4. Generate or inspect the next-trading-day trade plan.
5. Record paper execution.
6. Monitor T+2/T+5 position exits.
7. Read TradingAgents output as advisory review only.

## Open Design Setup

Recommended Open Design skill:

- `dashboard`

Recommended visual direction:

- `Tech Utility`

Recommended design system direction:

- Linear-like operational density, but with PGC-specific color semantics.

Open Design repo:

- https://github.com/nexu-io/open-design/tree/main

Open Design runtime notes from README:

- Requires Node `~24` and pnpm `10.33.x`.
- Quickstart is `git clone`, `corepack enable`, `pnpm install`, then `pnpm tools-dev run web`.
- The daemon creates local `.od/` runtime data and project artifacts.

## Product Tone

Quiet, dense, careful, professional.

This is closer to a trading operations terminal than a SaaS landing page. Avoid:

- hero sections;
- decorative gradients;
- oversized KPI cards;
- card-in-card layouts;
- vague "today/tomorrow" labels;
- AI advice styled as a trading command.

Use exact dates everywhere, such as `复盘日 20260504`, `计划买入 20260505`, `T+2 20260507`.

## Core Screens

### 1. 每日复盘

Primary question: after close, is there exactly one best action for the next trading day?

Layout:

- top status bar;
- left navigation;
- main action strip;
- candidate table;
- current position due queue;
- advisory Agent panel;
- lineage drawer trigger.

Required visible data:

- account: `paper-main`;
- account type: `paper`;
- review date: `20260504`;
- latest market date: `20260504`;
- strategy version: `cpb_6157@2026-05-03`;
- data quality: `pass`, `warning`, or `blocker`;
- free slots: `2/3`;
- daily pick: `000001.SZ PGC Candidate`;
- score: `91.00`;
- planned buy date: `20260505`;
- reason: `highest_score_rank_1`;
- Agent policy: `advisory`.

Main states:

- Pass: allow "生成计划".
- Warning: allow but highlight data quality.
- Blocker: disable plan generation and show blocker table.
- No signal: show no trade plan, not a skipped fake plan.

### 2. 交易计划

Primary question: which plans are draft, active, executed, skipped, expired?

Required table columns:

- plan id;
- account;
- action;
- status;
- stock;
- as-of date;
- planned trade date;
- planned shares;
- reason;
- linked daily pick;
- linked signal;
- operation buttons.

Actions:

- publish draft;
- cancel draft/active;
- jump to execution recording.

Important rule:

- `trade_plans` are plans only. Do not display them as executed trades.

### 3. 成交录入

Primary question: record a buy or sell execution from an active trade plan.

Layout:

- left pending plan queue;
- right execution form;
- bottom validation log.

Fields:

- trade plan id;
- side: buy/sell;
- executed date;
- executed price;
- shares;
- fee;
- tax;
- source: `paper_model` or `manual`;
- projected cash after trade.

Important rule:

- Position appears only after buy execution is recorded.

### 4. 当前持仓

Primary question: which positions need T+2 or T+5 action?

Required table columns:

- position id;
- stock;
- account;
- buy date;
- buy price;
- shares;
- status;
- planned T+2 date;
- planned T+5 date;
- latest close;
- unrealized return;
- next action.

States:

- `waiting_t2`;
- `need_t2_decision`;
- `holding_to_t5`;
- `need_t5_exit`;
- `planned_exit`;
- `closed`.

Important rule:

- T+2 and T+5 dates come from `trade_calendar`, not natural-day offsets.

### 5. 数据质量

Primary question: what blocks the daily workflow?

Required filters:

- status;
- severity;
- layer;
- trade date;
- event code.

Required table columns:

- severity;
- layer;
- event code;
- entity type;
- ts_code;
- trade date;
- message;
- status;
- created at;
- resolve action.

Visual priority:

- blocker must visually outrank returns and candidate score.

### 6. Agent 复核

Primary question: what did TradingAgents advise, and what was its evidence?

Required sections:

- run status;
- advisory action;
- risk level;
- confidence;
- summary;
- risk points;
- human checks;
- input snapshot hash;
- linked signal/daily pick.

Important rule:

- TradingAgents is advisory only. Do not style `agent_decisions` as buy/sell execution commands.

## Global Navigation

Left nav items:

- 每日复盘
- 交易计划
- 成交录入
- 当前持仓
- 账户资金
- Agent 复核
- 数据质量
- 策略研究
- 系统设置

Top bar fixed order:

1. account;
2. account type;
3. review date;
4. latest market date;
5. strategy version;
6. position capacity;
7. data quality.

## Color Semantics

Use colors only for semantics:

- background: `#F7F8FA`;
- panel: `#FFFFFF`;
- text: `#111827`;
- secondary text: `#6B7280`;
- border: `#E5E7EB`;
- primary action: `#2563EB`;
- profit/take-profit: `#059669`;
- blocker/stop-loss: `#DC2626`;
- warning/manual review: `#D97706`;
- neutral/skipped/expired: `#64748B`;
- Agent advisory: `#4F46E5`.

Do not let purple dominate the whole product. Purple is only for Agent review.

## Prototype Data

Use this sample state in the prototype:

```json
{
  "account": {
    "account_key": "paper-main",
    "account_type": "paper",
    "initial_cash": 200000,
    "max_positions": 3,
    "open_positions": 1,
    "free_slots": 2
  },
  "review": {
    "review_date": "20260504",
    "latest_market_date": "20260504",
    "next_trade_date": "20260505",
    "strategy_version": "cpb_6157@2026-05-03",
    "data_quality": "pass"
  },
  "daily_pick": {
    "ts_code": "000001.SZ",
    "name": "PGC Candidate",
    "score": 91.0,
    "rank": 1,
    "review_date": "20260504",
    "planned_buy_date": "20260505",
    "selection_reason": "highest_score_rank_1",
    "features": {
      "pullback_days": 4,
      "amount_contract_ratio": 0.58,
      "avg_amount_to_ma10": 0.74,
      "drawdown_from_peak": -0.08,
      "bull_body": 0.0206,
      "close_recover": 0.0259,
      "trigger_amount_to_ma10": 0.92
    }
  },
  "trade_plan": {
    "id": 101,
    "action": "buy_next_open",
    "status": "active",
    "planned_trade_date": "20260505",
    "planned_shares": 6600,
    "reason": "daily_pick"
  },
  "position_due": {
    "position_id": 88,
    "ts_code": "000002.SZ",
    "name": "Existing Position",
    "buy_date": "20260430",
    "buy_price": 10.0,
    "shares": 1000,
    "status": "need_t2_decision",
    "planned_t2_date": "20260504",
    "planned_t5_date": "20260508",
    "latest_close": 10.4,
    "unrealized_ret": 0.04,
    "next_action": "sell_t2_take_profit"
  },
  "agent": {
    "agent_policy": "advisory",
    "run_status": "completed",
    "action": "caution",
    "risk_level": "medium",
    "confidence": 0.62,
    "summary": "趋势延续结构成立，但成交额确认偏弱，建议人工复核盘口和公告风险。"
  }
}
```

## Open Design Prompt

Paste this prompt into Open Design with skill `dashboard`:

```text
Design a high-fidelity desktop dashboard prototype for a Chinese PGC short-term quant trading system.

This is a daily after-close trading operations workstation, not a marketing dashboard. It must feel quiet, dense, professional, and safety-oriented. Use exact trading dates everywhere. Never show vague labels like today or tomorrow without the exact YYYYMMDD date.

Build a multi-section prototype with these screens represented in a single desktop artifact:
1. 每日复盘
2. 交易计划
3. 成交录入
4. 当前持仓
5. 数据质量
6. Agent 复核

The first viewport should be the actual daily review workspace, not a landing page. Use a fixed top status bar and left navigation. Use dense tables, segmented controls, status chips, compact buttons with icons, and right-side drawers. Cards are allowed only for individual business objects; avoid card-in-card layouts and decorative gradients.

Critical business rules:
- Raw PGC data only has ts_code, code, name, entry_date, entry_time, entry_price.
- Strategy is cpb_6157@2026-05-03.
- Daily review can produce feature runs, strategy signals, and at most one daily pick.
- DailyReviewService must not create trade plans, trades, or positions.
- trade_plans are plans, not executions.
- positions only appear after buy trade execution.
- T+2 and T+5 are trading-calendar dates, not natural-day offsets.
- TradingAgents is advisory only. Agent output must not be styled as a buy/sell command.

Use the sample data from the brief. Highlight data-quality blocker as the highest visual priority. Purple/indigo may only be used for Agent advisory, not the whole application.

Produce a polished operational dashboard artifact with Chinese UI labels and realistic sample data.
```

## Acceptance Checklist

- The first screen is the daily review workbench.
- There is no hero page or marketing copy.
- Candidate, daily pick, trade plan, trade execution, and position are visually separated.
- Trade plan is never displayed as a completed trade.
- Position does not appear before buy execution.
- T+2/T+5 dates are explicit and tied to trading calendar.
- Agent section is marked advisory.
- Data quality blocker disables plan generation.
- Text fits in table cells and controls.
- UI remains usable at desktop and tablet widths.
