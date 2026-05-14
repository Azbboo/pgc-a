# 20260514 Shadow Walk-forward Outcomes

> Read-only post-close labels from market bars. This artifact does not promote strategies or create trading state.

## Summary

- Status: partial
- Candidates: 5
- Signals: 60
- Complete horizons: 48
- Partial horizons: 12
- Missing market bars: 0
- Promotion allowed: false

## Candidate Metrics

| candidate | status | signals | complete | partial | missing | T+1 mean | T+5 mean | blockers |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| trend_extension_shadow | partial | 20 | 16 | 4 | 0 | 1.49% | 2.46% | shadow_walk_forward_partial_horizon |
| breakout_pressure_shadow | partial | 20 | 16 | 4 | 0 | 0.45% | 8.25% | shadow_walk_forward_partial_horizon |
| low_price_momentum_shadow | partial | 20 | 16 | 4 | 0 | 2.08% | 2.76% | shadow_walk_forward_partial_horizon |
| preconfirm_watchlist | missing | 0 | 0 | 0 | 0 | - | - | shadow_walk_forward_source_rows_missing |
| pullback_dip_buy | missing | 0 | 0 | 0 | 0 | - | - | shadow_walk_forward_source_rows_missing |

## No-future Boundary

- Passed: true
- Max signal date: 20260513
- Max input date: 20260514
- Data cutoff date: 20260514
