# 2026-05-12 池内大涨股漏抓复盘（低价限制已放开）

> 口径：使用最新 feature_run_id=5 / strategy_run_id=5；`min_entry_price=0.0`。20260512 涨幅只作为事后标签，影子桶只使用 20260511 收盘前可见数据。

## 结论

- 低价限制已经放开，`entry_price_below_min` 不再出现。
- 重跑 20260512 后仍然没有正式 CPB 候选：`strategy_signals=0`。
- 原来被低价挡掉的票继续进入 CPB 形态判断后，仍未出现“缩量回调后阳线确认”；所以今天不是价格地板问题，而是形态/策略族问题。

## 数据校验

- 有效入池事件：256；去重股票：253
- 20260512 行情条数：253
- 最新特征快照：256；最新策略信号：0
- 最新全池 CPB 拒绝原因：contracting_pullback_not_detected=237，insufficient_post_entry_bars=19

## 池内涨幅分布

- >=5%：18 只
- >=7%：11 只
- >=9.8%：8 只
- 上涨 / 非上涨：72 / 175

## 大涨股 CPB 失败原因（放开低价后）

| 原因 | >=5% 大涨股数量 |
| --- | ---: |
| contracting_pullback_not_detected | 17 |
| insufficient_post_entry_bars | 1 |

## 影子桶归因

| 影子桶 | >=5% 大涨股数量 |
| --- | ---: |
| trend_extension_shadow | 7 |
| low_price_momentum_shadow | 6 |
| breakout_pressure_shadow | 3 |
| not_flagged_by_shadow_v0 | 2 |

## Top 大涨股诊断

| 代码 | 名称 | 涨幅% | 入池日 | 入池价 | CPB失败原因 | 影子桶 | 入池至前日% | 前日距20日高点% | 前日量/MA10 |
| --- | --- | ---: | --- | ---: | --- | --- | ---: | ---: | ---: |
| 300632.SZ | 光莆股份 | 13.79 | 20260409 | 16.72 | contracting_pullback_not_detected | trend_extension_shadow | 49.58 | -4.03 | 1.5172 |
| 000601.SZ | 韶能股份 | 10.07 | 20260327 | 8.37 | contracting_pullback_not_detected | low_price_momentum_shadow | -12.19 | -3.67 | 0.8866 |
| 002081.SZ | 金螳螂 | 10.07 | 20260429 | 5.06 | contracting_pullback_not_detected | low_price_momentum_shadow | 43.28 | -3.07 | 1.6325 |
| 600719.SH | 大连热电 | 10.05 | 20260326 | 7.53 | contracting_pullback_not_detected | low_price_momentum_shadow | 28.15 | -6.31 | 2.318 |
| 001359.SZ | 平安电工 | 10.01 | 20251125 | 56.39 | contracting_pullback_not_detected | trend_extension_shadow | 74.94 | -2.81 | 1.6134 |
| 002428.SZ | 云南锗业 | 10 | 20251127 | 26.52 | contracting_pullback_not_detected | trend_extension_shadow | 247.66 | -0.09 | 1.134 |
| 002606.SZ | 大连电瓷 | 10 | 20260415 | 12.28 | contracting_pullback_not_detected | not_flagged_by_shadow_v0 | 25.41 | -4.35 | 0.5022 |
| 600488.SH | 津药药业 | 10 | 20260409 | 7.2 | contracting_pullback_not_detected | low_price_momentum_shadow | -8.33 | -14.51 | 1.1292 |
| 000066.SZ | 中国长城 | 8.38 | 20260428 | 17.76 | contracting_pullback_not_detected | trend_extension_shadow | 31.76 | -5.53 | 1.7714 |
| 002637.SZ | 赞宇科技 | 7.51 | 20260318 | 14.3 | contracting_pullback_not_detected | breakout_pressure_shadow | -16.22 | -9.24 | 0.6437 |
| 300267.SZ | 尔康制药 | 7.08 | 20260410 | 4.05 | contracting_pullback_not_detected | low_price_momentum_shadow | 11.6 | -4.24 | 0.9463 |
| 600184.SH | 光电股份 | 6.6 | 20260401 | 19.19 | contracting_pullback_not_detected | trend_extension_shadow | 42.16 | 0 | 0.8684 |
| 301373.SZ | 凌玮科技 | 6.45 | 20260325 | 65.48 | contracting_pullback_not_detected | trend_extension_shadow | 112.26 | -3.43 | 0.8001 |
| 301123.SZ | 奕东电子 | 5.22 | 20260408 | 57.7 | contracting_pullback_not_detected | trend_extension_shadow | 24.61 | -1.48 | 1.4101 |
| 600537.SH | 亿晶光电 | 5.15 | 20260424 | 3.52 | contracting_pullback_not_detected | low_price_momentum_shadow | -6.25 | -24.83 | 0.5859 |
| 002112.SZ | 三变科技 | 5.02 | 20260323 | 23.95 | contracting_pullback_not_detected | breakout_pressure_shadow | -12.61 | -7.02 | 1.2377 |
| 002856.SZ | 美芝股份 | 5.01 | 20260423 | 12.07 | contracting_pullback_not_detected | not_flagged_by_shadow_v0 | 22.45 | 0 | 0.38 |
| 300607.SZ | 拓斯达 | 5.01 | 20260508 | 32.02 | insufficient_post_entry_bars | breakout_pressure_shadow | -1.47 | -4.57 | 0.8043 |

## 今日新入池检查

| 代码 | 名称 | 入池价 | 收盘/入池% | 最高/入池% | CPB状态 | bars_used |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| 603391.SH | 力聚热能 | 68 | -3.19 | 0.68 | insufficient_post_entry_bars | 1 |
| 300084.SZ | 海默科技 | 13.15 | 0.46 | 1.67 | insufficient_post_entry_bars | 1 |
| 603466.SH | 风语筑 | 10.54 | -0.76 | 0.28 | insufficient_post_entry_bars | 1 |
| 688472.SH | 阿特斯 | 15.65 | -1.15 | 0.89 | insufficient_post_entry_bars | 1 |
| 300260.SZ | 新莱应材 | 57.81 | 3.23 | 3.7 | insufficient_post_entry_bars | 1 |
| 002896.SZ | 中大力德 | 80.08 | 0.4 | 3.8 | insufficient_post_entry_bars | 1 |

## 后续动作

- Low-price floor is no longer the blocker; remaining misses require non-CPB trend/breakout logic or relaxed CPB shape rules.
- Do not assume low-price unlock alone creates candidates: 20260512 still has zero formal CPB signals.
- If low-price momentum should be traded, promote it as a separate rule with its own sizing/stop constraints rather than forcing CPB to chase non-pullback boards.

## 安全边界

- 已修改 active CPB 的低价门槛为 0。
- 已重跑 daily review，但未生成 paper/live 交易计划。
