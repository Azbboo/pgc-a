# 2026-05-13 池内大涨股漏抓复盘

> 口径：20260513 涨幅只作事后标签；归因/影子分类只使用 20260512 收盘前可见数据。

## 样本概况
- raw_event_count: 256
- unique_symbol_count: 253
- market_bar_count: 253
- feature_snapshot_count_latest_run: 256
- strategy_signal_count_latest_run: 0
- active_buy_plan_for_20260513: []
- ge_5pct: 32
- ge_7pct: 22
- ge_9_8pct: 13
- positive: 157
- nonpositive: 96

## >=5% 大涨股失败原因
- contracting_pullback_not_detected: 31
- insufficient_post_entry_bars: 1

## 影子桶分类
- trend_extension_shadow: 13
- low_price_momentum_shadow: 9
- not_flagged_by_shadow_v0: 5
- breakout_pressure_shadow: 5

## Top 大涨股
| 代码 | 名称 | 涨幅% | 最高涨幅% | 入池日 | 入池价 | CPB原因 | 影子桶 | 入池至前日% | 前日距20日高点% |
| --- | --- | ---: | ---: | --- | ---: | --- | --- | ---: | ---: |
| 000889.SZ | 中嘉博创 | 10.08 | 10.08 | 20260424 | 4.54 | contracting_pullback_not_detected | low_price_momentum_shadow | 11.45 | -14.09 |
| 002629.SZ | 仁智股份 | 10.06 | 10.06 | 20260421 | 7.0 | contracting_pullback_not_detected | low_price_momentum_shadow | -0.57 | -5.05 |
| 000993.SZ | 闽东电力 | 10.02 | 10.02 | 20260318 | 14.25 | contracting_pullback_not_detected | breakout_pressure_shadow | -6.81 | -1.34 |
| 000601.SZ | 韶能股份 | 10.01 | 10.01 | 20260327 | 8.37 | contracting_pullback_not_detected | low_price_momentum_shadow | -3.35 | 0.0 |
| 002842.SZ | 翔鹭钨业 | 10.01 | 10.01 | 20251118 | 12.2 | contracting_pullback_not_detected | trend_extension_shadow | 197.38 | -9.75 |
| 002885.SZ | 京泉华 | 10.01 | 10.01 | 20260429 | 30.65 | contracting_pullback_not_detected | trend_extension_shadow | 26.17 | -5.38 |
| 600379.SH | 宝光股份 | 10.01 | 10.01 | 20260424 | 12.8 | contracting_pullback_not_detected | not_flagged_by_shadow_v0 | 34.3 | -15.36 |
| 603890.SH | 春秋电子 | 10.01 | 10.01 | 20260414 | 16.5 | contracting_pullback_not_detected | trend_extension_shadow | 21.09 | -4.86 |
| 605168.SH | 三人行 | 10.01 | 10.01 | 20260430 | 48.49 | contracting_pullback_not_detected | breakout_pressure_shadow | 12.91 | -3.59 |
| 600726.SH | 华电能源 | 10.0 | 10.0 | 20260331 | 5.6 | contracting_pullback_not_detected | low_price_momentum_shadow | 37.5 | -6.21 |
| 002805.SZ | 丰元股份 | 9.99 | 9.99 | 20260416 | 18.43 | contracting_pullback_not_detected | trend_extension_shadow | 34.67 | -6.34 |
| 002940.SZ | 昂利康 | 9.99 | 9.99 | 20260511 | 33.88 | insufficient_post_entry_bars | breakout_pressure_shadow | -2.24 | -5.86 |
| 000533.SZ | 顺钠股份 | 9.98 | 9.98 | 20260319 | 19.89 | contracting_pullback_not_detected | not_flagged_by_shadow_v0 | -32.48 | -19.96 |
| 600410.SH | 华胜天成 | 9.23 | 9.99 | 20260401 | 26.11 | contracting_pullback_not_detected | not_flagged_by_shadow_v0 | -14.52 | -25.53 |
| 300632.SZ | 光莆股份 | 7.98 | 17.01 | 20260409 | 16.72 | contracting_pullback_not_detected | trend_extension_shadow | 70.22 | -5.13 |
| 603881.SH | 数据港 | 7.9 | 9.99 | 20260408 | 37.79 | contracting_pullback_not_detected | trend_extension_shadow | 6.46 | -9.02 |
| 300895.SZ | 铜牛信息 | 7.86 | 9.38 | 20260325 | 68.76 | contracting_pullback_not_detected | breakout_pressure_shadow | 1.82 | -4.1 |
| 002902.SZ | 铭普光磁 | 7.45 | 10.01 | 20260413 | 28.75 | contracting_pullback_not_detected | trend_extension_shadow | 29.32 | -6.56 |
