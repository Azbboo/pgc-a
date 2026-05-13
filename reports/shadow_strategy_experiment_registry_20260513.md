# M97 Shadow Strategy Experiment Registry

- as_of_date: 20260513
- registry_contract=shadow_strategy_experiment_registry_v1
- artifact_only=true
- promotion_allowed=false
- active_params_mutated=false
- writes_trade_state=false
- timer_mutated=false
- experiments: 5
- blocked_by_replay_evidence: 5
- blocked_by_sample: 0

## Experiments

| Experiment | Candidate | Family | Variant | Replay | Sample | CPB Delta | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| trend_extension_shadow:collect_replay_evidence | trend_extension_shadow | shadow_bucket | collect_replay_evidence | missing | 24/20 | -7.90 | blocked |
| breakout_pressure_shadow:collect_replay_evidence | breakout_pressure_shadow | shadow_bucket | collect_replay_evidence | missing | 24/20 | -8.80 | blocked |
| low_price_momentum_shadow:collect_replay_evidence | low_price_momentum_shadow | shadow_bucket | collect_replay_evidence | missing | 24/20 | -7.37 | blocked |
| preconfirm_watchlist:collect_replay_evidence | preconfirm_watchlist | preconfirm_watchlist | collect_replay_evidence | missing | 37/20 | -6.79 | blocked |
| pullback_dip_buy:collect_replay_evidence | pullback_dip_buy | dip_buy | collect_replay_evidence | missing | 28/20 | - | blocked |

## Stop Rules

- trend_extension_shadow:collect_replay_evidence: stop_if_replay_evidence_not_accepted, stop_if_manual_approval_boundary_changes, calibration_blocker:accepted_replay_backtest_evidence_required, calibration_blocker:frozen_cpb_delta_below_threshold
- breakout_pressure_shadow:collect_replay_evidence: stop_if_replay_evidence_not_accepted, stop_if_manual_approval_boundary_changes, calibration_blocker:accepted_replay_backtest_evidence_required, calibration_blocker:win_rate_below_threshold, calibration_blocker:frozen_cpb_delta_below_threshold
- low_price_momentum_shadow:collect_replay_evidence: stop_if_replay_evidence_not_accepted, stop_if_manual_approval_boundary_changes, calibration_blocker:accepted_replay_backtest_evidence_required, calibration_blocker:frozen_cpb_delta_below_threshold
- preconfirm_watchlist:collect_replay_evidence: stop_if_replay_evidence_not_accepted, stop_if_metric_completeness_fails, stop_if_manual_approval_boundary_changes, calibration_blocker:accepted_replay_backtest_evidence_required, calibration_blocker:frozen_cpb_delta_below_threshold, calibration_blocker:drawdown_proxy_missing
- pullback_dip_buy:collect_replay_evidence: stop_if_replay_evidence_not_accepted, stop_if_metric_completeness_fails, stop_if_frozen_cpb_comparison_missing, stop_if_manual_approval_boundary_changes, calibration_blocker:accepted_replay_backtest_evidence_required, calibration_blocker:frozen_cpb_delta_missing

## Manual Boundaries

- manual_promotion_approval_required=true
- strategy_version_publication_allowed=false
- trade_state_writes_allowed=false
- paper_live_behavior_change_allowed=false
- timer_mutation_allowed=false
