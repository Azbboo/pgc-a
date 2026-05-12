# Shadow Strategy Backtest 20260401-20260508

> Research-only. No active strategy params were changed. Signals are formed after each review-date close and evaluated from the next trading day's open.

## Methodology

- Review dates: `20260401` to `20260508` open trading days.
- Universe: valid PGC raw events available on or before each review date.
- Entry: next trading day open.
- Labels: T+1 close return, T+1 intraday high, T+3 max high, T+5 close return.
- Feature boundary: only raw event facts and market bars through review-date close.

## Daily Top1 Results

| label | n | days | t1_close_mean_pct | t1_close_median_pct | t1_close_win_rate_pct | t1_high_mean_pct | t1_high_ge3_rate_pct | t3_high_mean_pct | t3_high_ge5_rate_pct | t5_close_mean_pct | t5_close_win_rate_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| daily_top1_breakout_pressure_shadow | 24 | 24 | 0.22 | -0.48 | 45.8 | 3.45 | 58.3 | 8.57 | 62.5 | 4.77 | 50.0 |
| daily_top1_low_price_momentum_shadow | 24 | 24 | 2.61 | 2.75 | 58.3 | 5.49 | 70.8 | 11.89 | 75.0 | 9.97 | 65.0 |
| daily_top1_overheated_breakout_watch | 22 | 22 | 0.98 | 0.78 | 59.1 | 4.6 | 63.6 | 7.79 | 54.5 | 3.47 | 72.2 |
| daily_top1_trend_extension_shadow | 24 | 24 | 1.11 | 0.68 | 58.3 | 4.64 | 62.5 | 8.94 | 66.7 | 7.38 | 80.0 |
| daily_top1_combined_no_overheated | 24 | 24 | 1.11 | 0.68 | 58.3 | 4.64 | 62.5 | 8.94 | 66.7 | 7.38 | 80.0 |
| active_cpb_persisted_picks | 2 | 2 | 9.57 | 9.57 | 50.0 | 10.29 | 50.0 | 10.29 | 50.0 | None | None |

## All Candidate Distribution

| label | n | days | t1_close_mean_pct | t1_close_median_pct | t1_close_win_rate_pct | t1_high_mean_pct | t1_high_ge3_rate_pct | t5_close_mean_pct | t5_close_win_rate_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all_breakout_pressure_shadow | 1095 | 24 | 0.67 | 0.37 | 54.9 | 2.96 | 36.9 | 3.18 | 61.0 |
| all_low_price_momentum_shadow | 553 | 24 | 0.19 | -0.16 | 46.7 | 2.54 | 28.8 | 0.94 | 49.5 |
| all_overheated_breakout_watch | 127 | 22 | 0.6 | 0.43 | 58.3 | 3.34 | 44.9 | 3.18 | 59.2 |
| all_trend_extension_shadow | 467 | 24 | 1.18 | 0.62 | 56.3 | 4.17 | 54.0 | 5.86 | 68.8 |

## Combined Top1 Trades

| review_date | planned_buy_date | ts_code | name | bucket | score | next_open_gap_pct | t1_close_ret_pct | t1_high_ret_pct | t3_high_ret_pct | t5_close_ret_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20260408 | 20260409 | 300548.SZ | 长芯博创 | trend_extension_shadow | 111.8804 | -3.04 | 15.87 | 16.44 | 16.84 | 18.33 |
| 20260409 | 20260410 | 300548.SZ | 长芯博创 | trend_extension_shadow | 112.13 | -0.82 | -2.68 | 1.67 | 3.65 | 4.91 |
| 20260410 | 20260413 | 300548.SZ | 长芯博创 | trend_extension_shadow | 106.1697 | -0.21 | 0.75 | 1.76 | 9.66 | 16.45 |
| 20260413 | 20260414 | 003018.SZ | 金富科技 | trend_extension_shadow | 110.7274 | 0.06 | 5.24 | 7.52 | 7.52 | 21.52 |
| 20260414 | 20260415 | 002240.SZ | 盛新锂能 | trend_extension_shadow | 112.0441 | -1.05 | -3.54 | 0.06 | 7.3 | 1.0 |
| 20260415 | 20260416 | 002980.SZ | 华盛昌 | trend_extension_shadow | 113.7509 | 0.52 | -6.26 | 2.24 | 12.2 | 14.54 |
| 20260416 | 20260417 | 002240.SZ | 盛新锂能 | trend_extension_shadow | 108.8575 | -0.44 | 1.45 | 3.81 | 3.81 | -6.62 |
| 20260417 | 20260420 | 002980.SZ | 华盛昌 | trend_extension_shadow | 111.2149 | 2.82 | 3.75 | 5.83 | 12.02 | 9.46 |
| 20260420 | 20260421 | 002428.SZ | 云南锗业 | trend_extension_shadow | 112.0869 | 0.18 | 0.12 | 3.16 | 21.14 | 6.56 |
| 20260421 | 20260422 | 003018.SZ | 金富科技 | trend_extension_shadow | 110.7555 | 4.53 | 5.24 | 5.24 | 16.94 | 11.31 |
| 20260422 | 20260423 | 003018.SZ | 金富科技 | trend_extension_shadow | 113.2587 | 5.36 | -0.42 | 4.4 | 5.45 | 0.11 |
| 20260423 | 20260424 | 600105.SH | 永鼎股份 | trend_extension_shadow | 108.034 | 0 | 1.05 | 5.15 | 5.15 | -12.56 |
| 20260424 | 20260427 | 003018.SZ | 金富科技 | trend_extension_shadow | 111.0652 | -2.32 | -0.75 | 1.88 | 4.11 | -10.96 |
| 20260427 | 20260428 | 688530.SH | 欧莱新材 | trend_extension_shadow | 105.4113 | 8.23 | 8.78 | 10.44 | 12.68 | 14.4 |
| 20260428 | 20260429 | 002980.SZ | 华盛昌 | trend_extension_shadow | 99.4705 | -1.25 | -3.15 | 1.17 | 1.17 | 0.17 |
| 20260429 | 20260430 | 001203.SZ | 大中矿业 | trend_extension_shadow | 111.0533 | 1.36 | 0.6 | 5.1 | 5.1 | -10.77 |
| 20260430 | 20260506 | 002842.SZ | 翔鹭钨业 | trend_extension_shadow | 114.395 | 1.4 | 0.87 | 1.59 | 3.0 | None |
| 20260506 | 20260507 | 001316.SZ | 润贝航科 | trend_extension_shadow | 113.4804 | -0.77 | 5.86 | 9.06 | 12.22 | None |
| 20260507 | 20260508 | 002342.SZ | 巨力索具 | trend_extension_shadow | 111.5818 | 0 | -0.05 | 8.5 | 8.5 | None |
| 20260508 | 20260511 | 600105.SH | 永鼎股份 | trend_extension_shadow | 108.4589 | 1.28 | 1.62 | 3.8 | 3.8 | None |

## Preliminary Read

- `trend_extension_shadow` has the strongest next-day profile in this small sample, but it is explicitly a different regime from CPB pullback.
- `breakout_pressure_shadow` produces many candidates with positive intraday optionality, but median close return is less stable.
- `low_price_momentum_shadow` has enough winners to study, but risk and sizing should remain separate.
- The combined Top1 should be treated as a shadow benchmark only; it needs walk-forward monitoring before paper use.

## Artifacts

- `data/strategy_shadow_backtest_20260401_20260508_trades.csv`
- `data/strategy_shadow_backtest_20260401_20260508_summary.csv`
- `reports/strategy_shadow_backtest_20260401_20260508.json`
