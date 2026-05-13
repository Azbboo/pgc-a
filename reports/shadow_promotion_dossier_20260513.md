# Shadow Promotion Dossier 20260513

- contract: shadow_promotion_dossier_v1
- review_ready is not approval
- candidates: 5
- review_ready: 0
- blocked: 5
- replay_backtest_evidence: accepted=5 / rejected=0 / missing=0
- promotion_allowed=false

## Candidates
- trend_extension_shadow: blocked (replay_backtest_evidence=accepted; blocked_reasons=frozen_cpb_delta_not_positive, drawdown_proxy_missing, candidate_blockers_not_cleared)
- breakout_pressure_shadow: blocked (replay_backtest_evidence=accepted; blocked_reasons=frozen_cpb_delta_not_positive, drawdown_proxy_missing, candidate_blockers_not_cleared)
- low_price_momentum_shadow: blocked (replay_backtest_evidence=accepted; blocked_reasons=frozen_cpb_delta_not_positive, drawdown_proxy_missing, candidate_blockers_not_cleared)
- preconfirm_watchlist: blocked (replay_backtest_evidence=accepted; blocked_reasons=frozen_cpb_delta_not_positive, drawdown_proxy_missing, candidate_blockers_not_cleared)
- pullback_dip_buy: blocked (replay_backtest_evidence=accepted; blocked_reasons=frozen_cpb_delta_missing, candidate_blockers_not_cleared)

## Release Gate
- manual_promotion_approval_required
- future_strategy_version_task_required
- active CPB params/hash must remain unchanged
- no strategy_versions, trade_plans, trades, positions, paper/live behavior, broker execution, or timer writes
