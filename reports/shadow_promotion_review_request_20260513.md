# Shadow Promotion Review Request 20260513

- contract: shadow_promotion_review_request_v1
- source_dossier: reports/shadow_promotion_dossier_20260513.json
- source_dossier_status: valid
- status: blocked
- review_ready is not approval
- blocking_reason: no_review_ready_candidates
- replay_backtest_evidence: accepted=5 / rejected=0 / missing=0

## Source Dossier
- candidates: 5
- review_ready: 0
- blocked: 5
- valid: true
- review_ready_candidates: none

## Candidate Readiness
- trend_extension_shadow: blocked (replay_backtest_evidence=accepted; blockers=chase_gap_guard_required, operator_promotion_approval_required, operator_review_required, paper_observation_not_authorized, proposal_review_required, sector_evidence_confirmation_required, separate_trend_extension_candidate_required, strategy_version_proposal_not_authorized, walk_forward_shadow_monitor_20_trading_days_required)
- breakout_pressure_shadow: blocked (replay_backtest_evidence=accepted; blockers=close_return_stability_required, operator_promotion_approval_required, operator_review_required, paper_observation_not_authorized, proposal_review_required, separate_breakout_pressure_candidate_required, strategy_version_proposal_not_authorized, volume_overheat_guard_required, walk_forward_shadow_monitor_20_trading_days_required)
- low_price_momentum_shadow: blocked (replay_backtest_evidence=accepted; blockers=liquidity_slippage_review_required, micro_sleeve_risk_model_required, operator_promotion_approval_required, operator_review_required, paper_observation_not_authorized, proposal_review_required, separate_low_price_micro_sleeve_required, strategy_version_proposal_not_authorized, walk_forward_shadow_monitor_20_trading_days_required)
- preconfirm_watchlist: blocked (replay_backtest_evidence=accepted; blockers=next_day_confirmation_rule_required, operator_promotion_approval_required, operator_review_required, paper_observation_not_authorized, proposal_review_required, strategy_version_proposal_not_authorized, walk_forward_shadow_monitor_20_trading_days_required, watchlist_only_ui_lane_required, watchlist_to_signal_contract_required)
- pullback_dip_buy: blocked (replay_backtest_evidence=accepted; blockers=daily_walk_forward_monitor_required_for_dip_buy, dip_buy_stop_and_sizing_required, falling_knife_guard_required, operator_promotion_approval_required, operator_review_required, paper_observation_not_authorized, proposal_review_required, separate_dip_buy_candidate_required, strategy_version_proposal_not_authorized, walk_forward_shadow_monitor_20_trading_days_required)

## Human Decisions
- manual_promotion_approval_required: required (required=true; note=review_ready is not approval; manual approval remains required before any follow-up.)
- future_strategy_version_task_required: required (required=true; note=Any follow-up must be a separate strategy-version review task and must not mutate active strategy state.)
- candidate_selection: blocked (required=false; note=No candidate is review_ready, so promotion review should not proceed.)
- rollback_scope_confirmation: required (required=true; note=Confirm that the blocked mutation targets remain unchanged during any follow-up work.)

## Required Replay/Backtest Evidence
- breakout_pressure_shadow: accepted (blockers=none)
- low_price_momentum_shadow: accepted (blockers=none)
- preconfirm_watchlist: accepted (blockers=none)
- pullback_dip_buy: accepted (blockers=none)
- trend_extension_shadow: accepted (blockers=none)

## Rollback / Safety
- review_ready is not approval
- keep active CPB params/hash unchanged
- do not create or update strategy_versions, trade_plans, trades, positions, paper/live behavior, broker execution, or timers
- blocked_mutation_targets=active_cpb_params,strategy_versions,trade_plans,trades,positions,paper_live_behavior,broker_execution,timer_state
- review_ready is not approval
- promotion_allowed=false
- manual review only; no active strategy, trade, or timer mutation

## Release Gate
- manual_promotion_approval_required
- future_strategy_version_task_required
- active CPB params/hash must remain unchanged
- no strategy_versions, trade_plans, trades, positions, paper/live behavior, broker execution, or timer writes
