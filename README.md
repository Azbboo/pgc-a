# PGC量化选股交易系统

这是PGC股票池的第一版研究工作区。当前确认可用的原始数据只有入池事件本身：股票、入池时间、入池价格。其他字段如果出现在 JSON 中，暂时都不能作为信号使用，必须视为待审计或结果字段。

## 当前产物

- `data/pgc_pool.json`：原始导入文件
- `data/pgc_raw_events.json`：只保留原始入池事实后的事件表
- `scripts/analyze_pgc_raw_events.mjs`：raw-only 统计研究脚本
- `scripts/fetch_tushare_market_data.py`：Tushare 日线、复权因子、daily_basic 缓存脚本
- `scripts/analyze_pgc_event_backtest.py`：基于 Tushare 缓存的事件回测脚本
- `scripts/analyze_pgc_buy_setups.py`：入池后短线买点研究脚本
- `scripts/analyze_daily_review_strategy.py`：每日收盘复盘只选一只的组合级回测脚本
- `scripts/deep_dive_contracting_pullback.py`：缩量回调后一根阳线买点参数深挖脚本
- `scripts/init_trading_db.py`：初始化实盘/模拟盘 SQLite 状态库
- `scripts/run_live_daily_review.py`：按当前 `cpb_6157` 实盘口径生成每日交易计划
- `scripts/analyze_pgc_pool.mjs`：兼容入口，现在会转向 raw-only 研究
- `data/tushare/`：Tushare 行情缓存
- `data/pgc_event_backtest.csv`：逐事件回测明细
- `data/pgc_buy_setups.csv`：入池后买点信号明细
- `data/pgc_current_watchlist.csv`：当前观察池和老票再激活列表
- `data/daily_review_candidates.csv`：每日复盘候选明细
- `data/daily_review_picks.csv`：每日最终入选明细
- `data/contracting_pullback_variants.csv`：缩量回调阳线形态参数搜索结果
- `data/contracting_pullback_best_signals.csv`：当前最优参数对应的信号明细
- `data/contracting_pullback_current_candidates.csv`：当前最新复盘日匹配最优参数的候选
- `reports/pgc_raw_event_research.md`：原始入池事件统计报告
- `reports/pgc_raw_event_research.json`：结构化 raw-only 分析结果
- `reports/pgc_event_backtest.md`：事件回测研究报告
- `reports/pgc_event_backtest.json`：结构化事件回测结果
- `reports/pgc_buy_setups.md`：短线买点研究报告
- `reports/pgc_buy_setups.json`：结构化买点研究结果
- `reports/daily_review_strategy.md`：每日收盘复盘选一只策略报告
- `reports/daily_review_strategy.json`：结构化每日复盘策略结果
- `reports/contracting_pullback_deep_dive.md`：缩量回调阳线形态深挖报告
- `reports/contracting_pullback_deep_dive.json`：结构化深挖结果
- `reports/system_design.md`：实盘系统架构设计
- `reports/dashboard_interaction_detail_design.md`：Dashboard 页面字段、按钮状态和操作流详细设计
- `reports/live_trade_plan.md`：每日实盘交易计划

## 运行

```bash
node scripts/analyze_pgc_raw_events.mjs
```

拉取或刷新 Tushare 行情缓存时，通过环境变量传入 token，不要写入文件：

```bash
TUSHARE_TOKEN='你的token' python3 scripts/fetch_tushare_market_data.py --end-date 20260430
```

运行事件回测：

```bash
python3 scripts/analyze_pgc_event_backtest.py
```

研究入池后的短线买点：

```bash
python3 scripts/analyze_pgc_buy_setups.py
```

回测每天收盘后只选一只、次日开盘买入、T+2 尾盘判断卖出的流程：

```bash
python3 scripts/analyze_daily_review_strategy.py
```

深挖“缩量回调后一根阳线，次日买入”这个形态：

```bash
python3 scripts/deep_dive_contracting_pullback.py
```

初始化实盘/模拟盘状态库：

```bash
python3 scripts/init_trading_db.py
```

生成每日实盘交易计划：

```bash
python3 scripts/run_live_daily_review.py
```

使用 `gpt-image-2` 生成原型图片时，把图片接口密钥放在本地 `.env` 的 `PGC_IMAGE_API_KEY`，不要提交真实密钥：

```bash
python3 scripts/gen_gpt_image2.py --prompt-file docs/ui/open-design-pgc-dashboard-brief.md
```

兼容旧入口：

```bash
node scripts/analyze_pgc_pool.mjs
```

也可以传入其他PGC池文件：

```bash
node scripts/analyze_pgc_raw_events.mjs path/to/pgc_pool.json
```

## 当前研究原则

上一版“PGC高概率回调健康趋势延续策略”已废弃，因为它依赖 `bull_prob/bull_reason`，而这两个字段不属于当前确认的原始数据。

当前只允许使用：

- `ts_code`
- `code`
- `name`
- `entry_date`
- `entry_time`
- `entry_price`

要判断 PGC 入池是否有交易价值，下一步必须补齐逐日行情，然后从入池事件重新计算 t+1/t+3/t+5/t+10/t+20 收益、MFE、MAE、止盈止损和可成交性。

## 当前研究结论

全量 PGC 入池事件在“次一交易日开盘买入，遵守 T+1，固定持有”的口径下，中位收益暂时不理想；10 日持有中位收益约为负。更有价值的方向是研究入池后的冲高机会和入池前特征过滤。

当前探索性较好的候选方向：

- 入池日量比处于中高区间：`1.62 < volume_ratio <= 2.54`
- 20 日波动率处于中高区间：`3.64% < pre_volatility_20 <= 4.71%`
- 过滤低价股：优先看 `entry_price >= 10`，更严格可看 `20 <= entry_price <= 100`

这些阈值来自当前样本内统计，只能作为模拟盘和后续走前验证的候选规则。

## 当前短线买点假设

PGC 入池先作为观察池，不作为直接买入信号。第一版买点分三类：

- `contracting_pullback_bullish`：入池后20个交易日内，先缩量回调，随后出现一根确认阳线，次日买入
- `pullback_stabilization`：入池后20个交易日内，冲高后缩量回调并企稳
- `sideways_breakout`：入池后20个交易日内，横盘震荡后放量突破
- `old_volume_reactivation`：入池超过20个交易日后，突然放量并重新接近突破

第一轮结果显示，缩量回调后阳线确认和横盘突破更像可执行买点；泛化缩量回调和老票再激活更适合研究短线止盈、移动止盈和快进快出。

每日只选一只的第一版流程默认过滤 `entry_price < 10`。T+2 尾盘判断规则为：收益 `>= 3%` 止盈，收益 `<= -3%` 控亏，中间态继续持有到 T+5 收盘。

缩量回调阳线形态的当前深挖参数为：回调 2-6 天、回调整体量能低于 10 日均量、从高点回撤约 2.5%-14%、确认阳线实体至少 1.2%、阳线当天成交额不超过 10 日均额的 1.3 倍、入池以来涨幅不超过 18%。
