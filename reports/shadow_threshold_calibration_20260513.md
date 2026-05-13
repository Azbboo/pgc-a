# M94 Shadow Threshold Calibration Sandbox

- as_of_date: 20260513
- artifact_only=true
- promotion_allowed=false
- active_params_mutated=false
- candidates: 5
- recommended_next_experiments: 5
- rejected_variants: 15

## Family Metrics

| Family | Candidates | Sample | Win % | Mean % | Median % | Drawdown % | CPB Delta % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dip_buy | 1 | 28 | 60.71 | 5.27 | 0.83 | -7.46 | - |
| preconfirm_watchlist | 1 | 37 | 67.57 | 7.57 | - | - | -6.79 |
| shadow_bucket | 3 | 72 | 54.13 | 7.37 | 4.88 | -6.43 | -8.02 |

## Recommended Next Experiments

- trend_extension_shadow: trend_extension_shadow:collect_replay_evidence (accepted replay/backtest evidence is missing or rejected; promotion_allowed=false)
- breakout_pressure_shadow: breakout_pressure_shadow:collect_replay_evidence (accepted replay/backtest evidence is missing or rejected; promotion_allowed=false)
- low_price_momentum_shadow: low_price_momentum_shadow:collect_replay_evidence (accepted replay/backtest evidence is missing or rejected; promotion_allowed=false)
- preconfirm_watchlist: preconfirm_watchlist:collect_replay_evidence (accepted replay/backtest evidence is missing or rejected; promotion_allowed=false)
- pullback_dip_buy: pullback_dip_buy:collect_replay_evidence (accepted replay/backtest evidence is missing or rejected; promotion_allowed=false)

## Rejected Variants

- trend_extension_shadow / current_shadow_review_gate: accepted_replay_backtest_evidence_required, frozen_cpb_delta_below_threshold
- trend_extension_shadow / quality_tighten_candidate: accepted_replay_backtest_evidence_required, sample_size_below_threshold, frozen_cpb_delta_below_threshold, drawdown_proxy_below_threshold
- trend_extension_shadow / exploratory_relaxed_sample: accepted_replay_backtest_evidence_required, frozen_cpb_delta_below_threshold
- breakout_pressure_shadow / current_shadow_review_gate: accepted_replay_backtest_evidence_required, win_rate_below_threshold, frozen_cpb_delta_below_threshold
- breakout_pressure_shadow / quality_tighten_candidate: accepted_replay_backtest_evidence_required, sample_size_below_threshold, win_rate_below_threshold, frozen_cpb_delta_below_threshold
- breakout_pressure_shadow / exploratory_relaxed_sample: accepted_replay_backtest_evidence_required, win_rate_below_threshold, frozen_cpb_delta_below_threshold
- low_price_momentum_shadow / current_shadow_review_gate: accepted_replay_backtest_evidence_required, frozen_cpb_delta_below_threshold
- low_price_momentum_shadow / quality_tighten_candidate: accepted_replay_backtest_evidence_required, sample_size_below_threshold, frozen_cpb_delta_below_threshold
- low_price_momentum_shadow / exploratory_relaxed_sample: accepted_replay_backtest_evidence_required, frozen_cpb_delta_below_threshold
- preconfirm_watchlist / current_shadow_review_gate: accepted_replay_backtest_evidence_required, frozen_cpb_delta_below_threshold, drawdown_proxy_missing
- preconfirm_watchlist / quality_tighten_candidate: accepted_replay_backtest_evidence_required, median_return_missing, frozen_cpb_delta_below_threshold, drawdown_proxy_missing
- preconfirm_watchlist / exploratory_relaxed_sample: accepted_replay_backtest_evidence_required, frozen_cpb_delta_below_threshold, drawdown_proxy_missing
- pullback_dip_buy / current_shadow_review_gate: accepted_replay_backtest_evidence_required, frozen_cpb_delta_missing
- pullback_dip_buy / quality_tighten_candidate: accepted_replay_backtest_evidence_required, sample_size_below_threshold, frozen_cpb_delta_missing, drawdown_proxy_below_threshold
- pullback_dip_buy / exploratory_relaxed_sample: accepted_replay_backtest_evidence_required, frozen_cpb_delta_missing
