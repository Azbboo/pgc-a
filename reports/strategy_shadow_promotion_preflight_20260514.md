# 2026-05-14 Shadow Promotion Preflight

> Artifact-only preflight. It does not activate strategy params, write trade plans, write trades, change positions, or touch timers.

## Status

- Status: blocked
- Candidates: 5
- Blockers: 23
- Active params mutated: False
- Paper/live behavior written: False
- Release gate: blocked
- Timer mutated: False

## Candidate Gates

| Candidate | Walk-forward | Paper blockers | Proposal blockers |
| --- | --- | --- | --- |
| trend_extension_shadow | complete | 5 | 5 |
| breakout_pressure_shadow | complete | 5 | 5 |
| low_price_momentum_shadow | complete | 5 | 5 |
| preconfirm_watchlist | complete | 5 | 5 |
| pullback_dip_buy | artifact_summary_only | 5 | 5 |

## Top Blockers

- active_cpb_db_params_hash_mismatch: 1
- chase_gap_guard_required: 1
- close_return_stability_required: 1
- dip_buy_stop_and_sizing_required: 1
- falling_knife_guard_required: 1
- liquidity_slippage_review_required: 1
- micro_sleeve_risk_model_required: 1
- next_day_confirmation_rule_required: 1
- operator_promotion_approval_required: 5
- operator_review_required: 5
- paper_observation_not_authorized: 5
- proposal_review_required: 5
- replay_backtest_result_artifact_required: 5
- sector_evidence_confirmation_required: 1
- separate_breakout_pressure_candidate_required: 1
- separate_dip_buy_candidate_required: 1
- separate_low_price_micro_sleeve_required: 1
- separate_trend_extension_candidate_required: 1
- strategy_version_proposal_not_authorized: 5
- volume_overheat_guard_required: 1
