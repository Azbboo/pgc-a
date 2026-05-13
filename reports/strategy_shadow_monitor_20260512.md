# 2026-05-12 影子策略监控

> 研究专用：上一交易日 2026-05-11 收盘生成影子候选，用 2026-05-12 实际行情验算；同时给出 2026-05-12 收盘后的次日观察名单。不会生成 paper/live 计划。

## 结论

- 今日 >=5% 池内上涨票 18 只，影子三桶覆盖 14 只，覆盖率 77.8%。
- 今日收盘影子候选共 188 只；趋势/突破/低价分别为 47/69/72。
- 20 日 walk-forward 状态：complete，20260409 至 20260511 共 20 个可验算信号日。
- Promotion preflight：blocked；候选 5 类，blocker 23 项，全部仍为 artifact-only。
- 方向判断可以继续观察，但 paper/proposal/promotion 都必须等 evidence gate 显式清空。

## 昨日影子候选今日表现

| 桶 | 候选数 | T+1收盘均值% | T+1收盘胜率% | T+1最高均值% | 最高>=3% |
| --- | --- | --- | --- | --- | --- |
| breakout_pressure_shadow | 71 | -0.63 | 31 | 2.29 | 28.2 |
| low_price_momentum_shadow | 72 | -1 | 22.2 | 1.85 | 22.2 |
| trend_extension_shadow | 50 | -1.15 | 30 | 2.99 | 34 |

## 20 日 Walk-forward

| 候选 | 状态 | 天数 | T+1收盘均值% | T+1胜率% | T+1最高均值% | 冻结CPB T+1均值差% |
| --- | --- | --- | --- | --- | --- | --- |
| trend_extension_shadow | complete | 20 | 1.46 | 45 | 4.25 | -8.11 |
| breakout_pressure_shadow | complete | 20 | 0.56 | 65 | 3.2 | -9.01 |
| low_price_momentum_shadow | complete | 20 | 2.09 | 60 | 5.66 | -7.48 |
| preconfirm_watchlist | complete | 27 | 2.78 | - | 13.03 | -6.79 |
| pullback_dip_buy | artifact_summary_only | - | - | 53.54 | - | - |

## 冻结 CPB 对照

- 来源：`/Users/azboo/Desktop/Person/pgc/reports/strategy_shadow_backtest_20260401_20260508.json`
- 状态：available；样本提示：small_frozen_cpb_sample
- DB/参数完整性：db_hash_match=False；params_file_hash_match=True。

## Promotion Preflight

| 候选 | Paper gate | Proposal gate | 主要 blockers |
| --- | --- | --- | --- |
| trend_extension_shadow | blocked | blocked | paper_observation_not_authorized, walk_forward_shadow_monitor_20_trading_days_required, operator_review_required... |
| breakout_pressure_shadow | blocked | blocked | paper_observation_not_authorized, walk_forward_shadow_monitor_20_trading_days_required, operator_review_required... |
| low_price_momentum_shadow | blocked | blocked | paper_observation_not_authorized, walk_forward_shadow_monitor_20_trading_days_required, operator_review_required... |
| preconfirm_watchlist | blocked | blocked | paper_observation_not_authorized, walk_forward_shadow_monitor_20_trading_days_required, operator_review_required... |
| pullback_dip_buy | blocked | blocked | paper_observation_not_authorized, walk_forward_shadow_monitor_20_trading_days_required, operator_review_required... |

## 昨日各桶 Top1

| 桶 | 代码 | 名称 | 评分 | 开盘缺口% | 收盘收益% | 最高收益% |
| --- | --- | --- | --- | --- | --- | --- |
| trend_extension_shadow | 002428.SZ | 云南锗业 | 124.8259 | -1 | 11.11 | 11.11 |
| breakout_pressure_shadow | 300085.SZ | 银之杰 | 107.3468 | -0.88 | -1.26 | 2.47 |
| low_price_momentum_shadow | 002081.SZ | 金螳螂 | 117.1679 | 2.48 | 7.4 | 7.4 |

## 今日收盘次日观察 Top12

| 桶 | 代码 | 名称 | 评分 | 收盘 | 入池至今% | 5日% | 距20日高点% | 量/MA10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| trend_extension_shadow | 002428.SZ | 云南锗业 | 124.8948 | 101.42 | 282.43 | 44.87 | 0 | 1.2552 |
| trend_extension_shadow | 301373.SZ | 凌玮科技 | 122.9325 | 147.95 | 125.95 | 27.57 | -3.72 | 1.0015 |
| trend_extension_shadow | 001359.SZ | 平安电工 | 120.9624 | 108.52 | 92.45 | 23.67 | 0 | 1.663 |
| trend_extension_shadow | 600184.SH | 光电股份 | 120.4641 | 29.08 | 51.54 | 32.97 | -3.03 | 2.2156 |
| trend_extension_shadow | 603399.SH | 永杉锂业 | 119.8864 | 24.08 | 79.43 | 24.19 | -5.64 | 1.5046 |
| trend_extension_shadow | 300632.SZ | 光莆股份 | 119.2071 | 28.46 | 70.22 | 16.31 | -5.13 | 2.0159 |
| trend_extension_shadow | 000066.SZ | 中国长城 | 119.1185 | 25.36 | 42.79 | 27.95 | -1.48 | 1.8896 |
| trend_extension_shadow | 600105.SH | 永鼎股份 | 119.0383 | 52.32 | 85.4 | 23.37 | -6.55 | 1.2131 |
| trend_extension_shadow | 688028.SH | 沃尔德 | 119.0223 | 131.68 | 98.55 | 12.74 | -5.27 | 1.2378 |
| trend_extension_shadow | 002580.SZ | 圣阳股份 | 118.8982 | 34.17 | 74.87 | 24.34 | -5.58 | 1.1869 |
| trend_extension_shadow | 002980.SZ | 华盛昌 | 118.6803 | 82.5 | 248.1 | 3.2 | -6.25 | 0.7763 |
| trend_extension_shadow | 300548.SZ | 长芯博创 | 118.3707 | 271.8 | 173.69 | 5.89 | -6.28 | 0.8726 |

## 操作建议

- 明天先按观察名单盯盘，不把它直接混进 CPB 正式候选。
- 若要 paper 试跑，先补独立 observation lane 规则和 gap/liquidity/stop/sizing guard。
- 即便 walk-forward 样本已满 20 日，也只代表 preflight 输入具备；promotion blocker 仍需人工 artifact 审核后逐项清除。
