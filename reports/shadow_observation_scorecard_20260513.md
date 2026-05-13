# 2026-05-13 Shadow Observation Scorecard

> Research-only scorecard. It does not create active daily picks, trade plans, paper/live behavior, or timers.

## Status

- Status: blocked
- Candidates: 5
- Blocked candidates: 5
- Distinct blockers: 21
- Read only: True
- Artifact only: True
- Replay/backtest evidence: accepted=5 / rejected=0 / missing=0

## Coverage Blockers

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
- sector_evidence_confirmation_required: 1
- separate_breakout_pressure_candidate_required: 1
- separate_dip_buy_candidate_required: 1
- separate_low_price_micro_sleeve_required: 1
- separate_trend_extension_candidate_required: 1
- strategy_version_proposal_not_authorized: 5
- volume_overheat_guard_required: 1
- walk_forward_shadow_monitor_20_trading_days_required: 5
- watchlist_only_ui_lane_required: 1
- watchlist_to_signal_contract_required: 1

## Top Candidates

| Candidate | Family | Status | Today | Walk-forward | Replay | Blockers | Top |
| --- | --- | --- | --- | --- | --- | --- | --- |
| breakout_pressure_shadow | shadow_bucket | blocked | 68 | complete | accepted | paper_observation_not_authorized, walk_forward_shadow_monitor_20_trading_days_required, operator_review_required... | 002112.SZ 三变科技 |
| low_price_momentum_shadow | shadow_bucket | blocked | 66 | complete | accepted | paper_observation_not_authorized, walk_forward_shadow_monitor_20_trading_days_required, operator_review_required... | 600719.SH 大连热电 |
| trend_extension_shadow | shadow_bucket | blocked | 49 | complete | accepted | paper_observation_not_authorized, walk_forward_shadow_monitor_20_trading_days_required, operator_review_required... | 002428.SZ 云南锗业 |
| preconfirm_watchlist | preconfirm_watchlist | blocked | - | complete | accepted | paper_observation_not_authorized, walk_forward_shadow_monitor_20_trading_days_required, operator_review_required... | - |
| pullback_dip_buy | dip_buy | blocked | - | artifact_summary_only | accepted | paper_observation_not_authorized, walk_forward_shadow_monitor_20_trading_days_required, operator_review_required... | - |

## Source Artifacts

- promotion_preflight_json: `reports/strategy_shadow_promotion_preflight_20260513.json`
- promotion_preflight_report: `reports/strategy_shadow_promotion_preflight_20260513.md`
- strategy_shadow_monitor_json: `reports/strategy_shadow_monitor_20260513.json`
- strategy_shadow_monitor_report: `reports/strategy_shadow_monitor_20260513.md`
- walk_forward_csv: `data/strategy_shadow_walk_forward_20260513.csv`
- watchlist_csv: `data/strategy_shadow_watchlist_20260513.csv`
