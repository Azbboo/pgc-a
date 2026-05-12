# 2026-05-11 池内大涨股漏抓复盘与影子策略假设

> 口径：2026-05-11 涨幅只作为事后标签；影子规则只使用 2026-05-08 收盘前可见数据。本文不修改 active strategy params，不生成交易计划。

## 样本概况

- 池内股票数：241
- 当日涨幅 >=5%：33
- 当日涨幅 >=7%：14
- 当日接近涨停 / 大涨 >=9.9%：10
- 现行 CPB 当日正式信号：0
- 现行 CPB 已提前抓住：`301188.SZ 力诺药包` 是 2026-05-08 daily pick，计划 2026-05-11 执行。

## 大涨股为何没被 active CPB 抓住

| 原因 | >=5%大涨股数量 |
| --- | --- |
| contracting_pullback_not_detected | 26 |
| entry_price_below_min | 7 |

核心问题不是数据缺失，而是策略边界：`cpb_6157` 专门抓“缩量回调后的确认阳线”，对强趋势延续、放量突破、低价股涨停都比较保守。

## 影子规则 V0 分类

| 影子桶 | >=5%大涨股数量 |
| --- | --- |
| trend_extension_shadow | 14 |
| breakout_pressure_shadow | 10 |
| low_price_momentum_shadow | 7 |
| existing_cpb_pick | 1 |
| not_flagged_by_shadow_v0 | 1 |

解释：

- `existing_cpb_pick`：已经被 CPB 提前选中，不算漏抓。
- `trend_extension_shadow`：强趋势延续型，通常已经明显脱离入池价，active CPB 会因 `max_entry_runup=18%` 过滤。
- `breakout_pressure_shadow`：接近 20 日高位、前一交易日量能尚可，可能是突破前压力蓄势。
- `low_price_momentum_shadow`：低价股独立研究桶，不能直接并入主策略。
- `overheated_breakout_watch`：前一交易日已经高量过热，只能观察。

## 当日 Top 大涨股诊断

| 代码 | 名称 | 涨幅% | 入池日 | 入池价 | CPB失败原因 | 影子桶 | 入池至前日涨幅% | 前日距20日高点% |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 301188.SZ | 力诺药包 | 20.0 | 20260409 | 24.28 | contracting_pullback_not_detected | existing_cpb_pick | 13.26 | -5.98 |
| 688530.SH | 欧莱新材 | 12.97 | 20260409 | 32.13 | contracting_pullback_not_detected | trend_extension_shadow | 63.4 | -9.98 |
| 300570.SZ | 太辰光 | 10.3 | 20260413 | 131.0 | contracting_pullback_not_detected | trend_extension_shadow | 23.74 | -3.51 |
| 600379.SH | 宝光股份 | 10.03 | 20260424 | 12.8 | contracting_pullback_not_detected | not_flagged_by_shadow_v0 | 30.86 | -17.53 |
| 603757.SH | 大元泵业 | 10.01 | 20260403 | 43.55 | contracting_pullback_not_detected | trend_extension_shadow | 26.18 | -10.18 |
| 000791.SZ | 甘肃能源 | 10.0 | 20260320 | 8.55 | entry_price_below_min | low_price_momentum_shadow | 7.6 | -3.87 |
| 002943.SZ | 宇晶股份 | 10.0 | 20260414 | 52.05 | contracting_pullback_not_detected | trend_extension_shadow | 43.13 | -0.93 |
| 600184.SH | 光电股份 | 10.0 | 20260401 | 19.19 | contracting_pullback_not_detected | trend_extension_shadow | 29.23 | -6.73 |
| 600488.SH | 津药药业 | 10.0 | 20260409 | 7.2 | entry_price_below_min | low_price_momentum_shadow | -16.67 | -28.91 |
| 002645.SZ | 华宏科技 | 9.9 | 20260415 | 21.98 | contracting_pullback_not_detected | trend_extension_shadow | 24.57 | -0.73 |
| 300672.SZ | 国科微 | 9.76 | 20260408 | 159.32 | contracting_pullback_not_detected | trend_extension_shadow | 34.67 | -2.47 |
| 688450.SH | 光格科技 | 8.91 | 20260414 | 41.63 | contracting_pullback_not_detected | breakout_pressure_shadow | 10.5 | -6.31 |
| 603032.SH | 德新科技 | 7.19 | 20251114 | 24.39 | contracting_pullback_not_detected | breakout_pressure_shadow | 0.98 | -6.99 |
| 002428.SZ | 云南锗业 | 7.12 | 20251127 | 26.52 | contracting_pullback_not_detected | trend_extension_shadow | 224.55 | -2.44 |
| 300539.SZ | 横河精密 | 6.93 | 20260422 | 31.68 | contracting_pullback_not_detected | breakout_pressure_shadow | -1.17 | -2.64 |
| 688670.SH | 金迪克 | 6.78 | 20251112 | 26.46 | contracting_pullback_not_detected | breakout_pressure_shadow | -29.21 | -0.48 |
| 600664.SH | 哈药股份 | 6.65 | 20260417 | 4.29 | entry_price_below_min | low_price_momentum_shadow | -12.35 | -22.95 |
| 002081.SZ | 金螳螂 | 6.62 | 20260429 | 5.06 | entry_price_below_min | low_price_momentum_shadow | 34.39 | -5.29 |

## 优化空间

1. 新增 `trend_extension_shadow`，不要直接放松 `cpb_6157`。这类机会的收益来自强趋势延续，不是回调确认。
2. 对 `entry_runup > 18%` 的票单独建模，配合行业/题材证据、20 日高位、量能不过热、次日开盘不追高约束。
3. 把低价股做成独立 micro-sleeve 研究。今天确有低价股大涨，但风险和滑点不同，不应混入主策略仓位。
4. 把预警池升级为“次日确认任务”：前一日进入 preconfirm，次日满足收阳/放量不过热后才升级。

## 安全边界

- 未修改 active strategy params。
- 未生成 paper/live 交易计划。
- 未启用 timer。
- 这只是 shadow research，后续应进入 M69 shadow evaluation，而不是直接上线。
