# PGC 实施基线记录

日期：2026-05-04

## 1. 基线目的

这份文档记录从“系统设计”切换到“开发实施”前的当前状态。

目标：

- 固定现有研究资产；
- 保护当前 SQLite 原型库；
- 明确哪些脚本是研究脚本，哪些逻辑后续要沉淀到 `src/pgc_trading`；
- 固定 `cpb_6157@2026-05-03` 策略参数；
- 确认真实 Tushare token 没有写入仓库文件。

## 2. 数据库基线

当前数据库：

```text
data/pgc_trading.db
```

迁移前备份：

```text
data/backups/pgc_trading_20260504_before_m0_m1.db
```

当前库是原型 schema，表包括：

```text
agent_artifacts
agent_decisions
agent_runs
equity_snapshots
exits
input_snapshots
market_bars
portfolio_accounts
positions
raw_events
signals
strategy_runs
trade_plans
trades
```

当前核心表行数：

| 表 | 行数 |
| --- | ---: |
| `raw_events` | 0 |
| `market_bars` | 0 |
| `strategy_runs` | 0 |
| `signals` | 0 |
| `portfolio_accounts` | 1 |
| `trade_plans` | 0 |
| `trades` | 0 |
| `positions` | 0 |
| `exits` | 0 |
| `equity_snapshots` | 0 |

结论：

- 当前数据库适合做 M1 migration runner 验证；
- 迁移正式执行前仍必须保留备份；
- 后续目标 schema 不能直接覆盖这些同名原型表，应先执行 legacy freeze。

## 3. 现有生产骨架

当前 `src/pgc_trading` 只有轻量骨架：

| 文件 | 当前职责 | 后续去向 |
| --- | --- | --- |
| `src/pgc_trading/config.py` | 路径、策略、账户默认配置 | 扩展为环境变量配置入口 |
| `src/pgc_trading/storage/schema.sql` | 原型 schema | 保留为 legacy 参考 |
| `src/pgc_trading/storage/database.py` | SQLite connect/init/seed account | 接入 migration runner |
| `src/pgc_trading/strategies/cpb_6157.py` | 当前策略参数对象 | 扩展参数 hash 和版本标识 |
| `src/pgc_trading/agents/tradingagents_adapter.py` | Agent adapter 原型 | 后续接入 advisory service |

## 4. 研究脚本归类

| 脚本 | 当前定位 | 生产化方向 |
| --- | --- | --- |
| `scripts/analyze_pgc_raw_events.mjs` | raw-only 研究/清洗 | `RawIngestionService` fixture 参考 |
| `scripts/fetch_tushare_market_data.py` | Tushare 行情缓存 | `MarketDataService` / `TushareAdapter` |
| `scripts/analyze_pgc_event_backtest.py` | 事件回测研究 | replay/golden test 参考 |
| `scripts/analyze_pgc_buy_setups.py` | 买点研究 | feature engine 参考 |
| `scripts/analyze_daily_review_strategy.py` | 每日一票回测 | `DailyReviewService` 和 replay 参考 |
| `scripts/deep_dive_contracting_pullback.py` | 参数深挖 | strategy governance artifact |
| `scripts/backtest_best_contracting_pullback_t1.py` | T+1 实验 | research/backtest 参考 |
| `scripts/init_trading_db.py` | 原型库初始化 | 后续由 migration runner 替代 |
| `scripts/run_live_daily_review.py` | 原型每日计划入口 | 后续由 CLI/service 替代 |
| `scripts/analyze_pgc_pool.mjs` | 兼容入口 | 保留研究兼容 |

## 5. 数据文件基线

核心数据资产：

| 路径 | 说明 |
| --- | --- |
| `data/pgc_pool.json` | 原始 PGC 股票池文件 |
| `data/pgc_raw_events.json` | raw-only 入池事件 |
| `data/tushare/` | Tushare 日线、复权因子、daily_basic、交易日历缓存 |
| `data/daily_review_candidates.csv` | 每日复盘候选 |
| `data/daily_review_picks.csv` | 每日最终 pick |
| `data/daily_review_picks_t2.csv` | T+2 口径 pick 明细 |
| `data/contracting_pullback_best_signals.csv` | 当前最优参数信号 |
| `data/contracting_pullback_current_candidates.csv` | 当前最新复盘日候选 |

## 6. 策略基线

当前策略：

```text
cpb_6157@2026-05-03
```

参数 canonical JSON：

```json
{"avg_amount_max":0.95,"bull_body_min":0.012,"close_recover_min":0.0,"contract_max":0.95,"max_drawdown":0.14,"max_entry_runup":0.18,"min_drawdown":0.025,"pct_chg_min":0.0,"trigger_amount_max":1.3,"variant_id":"cpb_6157"}
```

参数 SHA-256：

```text
c4908f5cabe061f4d58fcbdd740f0c255c7c4830f467a9ed1602726688367ddc
```

禁止作为策略输入：

- `bull_prob`
- `bull_reason`
- `latest_ret`
- `max_high`
- `status`
- T+1/T+2/T+5 未来收益字段
- 回测胜负标签

## 7. 配置和敏感信息基线

新增配置样例：

```text
.env.example
```

规则：

- 真实 Tushare token 只允许通过环境变量 `TUSHARE_TOKEN` 传入；
- `.env.example` 不写真实 token；
- 日志、报告、fixture 不输出 token；
- Agent artifact 必须保留在项目目录内。

当前静态检查：

```text
未在仓库文件中发现已知真实 token 片段。
```

## 8. 下一步开发票据

当前已完成 M0 的基线记录，可进入：

```text
M1-001: 实现 migration runner 和 schema_migrations
```

M1-001 范围：

- `schema_migrations` bootstrap；
- 按文件名执行 `storage/migrations/*.sql`；
- 重复运行幂等；
- migration 失败事务回滚；
- 空库验证；
- 原型库只做检测，不做正式 freeze。
