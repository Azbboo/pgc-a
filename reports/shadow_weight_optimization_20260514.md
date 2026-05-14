# Shadow Weight Optimization 20260514

Research-only artifact. No strategy version, paper order, live order, trade plan, trade, or position is written.

## Topline

- Recommendation: use optimized variant as research-only shadow_v2; do not promote to paper/live without more observation
- Low-price last5 mean delta: 4.98 pct
- Breakout last5 mean delta: 0.73 pct
- Trend last5 mean delta: 0.00 pct

## Summary

| variant | bucket | all mean | all win | last10 mean | last10 win | last5 mean | last5 win |
|---|---:|---:|---:|---:|---:|---:|---:|
| current | trend_extension_shadow | 1.49 | 45.00 | 0.62 | 40.00 | 2.34 | 60.00 |
| current | breakout_pressure_shadow | 0.45 | 65.00 | 0.82 | 50.00 | -1.10 | 40.00 |
| current | low_price_momentum_shadow | 2.08 | 60.00 | 2.21 | 70.00 | 2.00 | 60.00 |
| shadow_v2_bucket_specific | trend_extension_shadow | 1.49 | 45.00 | 0.62 | 40.00 | 2.34 | 60.00 |
| shadow_v2_bucket_specific | breakout_pressure_shadow | 0.58 | 65.00 | 1.12 | 60.00 | -0.37 | 40.00 |
| shadow_v2_bucket_specific | low_price_momentum_shadow | 3.23 | 70.00 | 5.37 | 90.00 | 6.98 | 100.00 |

## Comparison

| bucket | all mean delta | all win delta | last10 mean delta | last5 mean delta | last5 win delta |
|---|---:|---:|---:|---:|---:|
| trend_extension_shadow | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| breakout_pressure_shadow | 0.13 | 0.00 | 0.30 | 0.73 | 0.00 |
| low_price_momentum_shadow | 1.15 | 10.00 | 3.16 | 4.98 | 40.00 |
