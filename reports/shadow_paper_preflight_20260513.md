# 影子到纸面预检 Shadow Paper Preflight 20260513

- contract: shadow_paper_preflight_v1
- 结论：本预检只生成手动晋级材料，不授权纸面候选、交易计划、paper/live 行为或 timer。
- 状态：blocked
- 候选数：5
- 可进入后续人工纸面任务：0
- paper_candidate_allowed=false
- 中文结论：当前 5 个 shadow 候选均不得进入纸面候选；最高预检分 breakout_pressure_shadow=80/100，仍需独立人工 strategy-version 任务和风险/回滚确认。

## 候选预检
- breakout_pressure_shadow: score=80/100; evidence=accepted; walk_forward=sufficient; stop_rule=blocking; paper_candidate_allowed=false; blockers=stop_rules_blocking, stop_if_replay_evidence_not_accepted, stop_if_sample_size_below_required, stop_if_metric_completeness_fails, stop_if_frozen_cpb_comparison_missing
- low_price_momentum_shadow: score=80/100; evidence=accepted; walk_forward=sufficient; stop_rule=blocking; paper_candidate_allowed=false; blockers=stop_rules_blocking, stop_if_replay_evidence_not_accepted, stop_if_sample_size_below_required, stop_if_metric_completeness_fails, stop_if_frozen_cpb_comparison_missing
- preconfirm_watchlist: score=80/100; evidence=accepted; walk_forward=sufficient; stop_rule=blocking; paper_candidate_allowed=false; blockers=stop_rules_blocking, stop_if_replay_evidence_not_accepted, stop_if_sample_size_below_required, stop_if_metric_completeness_fails, stop_if_frozen_cpb_comparison_missing
- trend_extension_shadow: score=80/100; evidence=accepted; walk_forward=sufficient; stop_rule=blocking; paper_candidate_allowed=false; blockers=stop_rules_blocking, stop_if_replay_evidence_not_accepted, stop_if_sample_size_below_required, stop_if_metric_completeness_fails, stop_if_frozen_cpb_comparison_missing
- pullback_dip_buy: score=50/100; evidence=accepted; walk_forward=insufficient; stop_rule=blocking; paper_candidate_allowed=false; blockers=walk_forward_insufficient, stop_rules_blocking, stop_if_replay_evidence_not_accepted, stop_if_sample_size_below_required, stop_if_metric_completeness_fails

## 必需人工批准
- manual_promotion_approval_required: required - 人工批准只允许在后续独立任务中记录；本预检不批准晋升。
- future_strategy_version_task_required: required - 若要推进，必须另开 strategy-version proposal/review 任务。
- paper_risk_rollback_confirmation_required: required - 确认 active CPB、交易状态、paper/live 行为、券商执行和 timer 均保持不变。

## 风险 / 回滚
- review_ready is not approval
- keep active CPB params/hash unchanged
- do not create or update strategy_versions, trade_plans, trades, positions, paper/live behavior, broker execution, or timers
- blocked_mutation_targets=active_cpb_params,strategy_versions,trade_plans,trades,positions,paper_live_behavior,broker_execution,timer_state
- promotion_allowed=false
- manual review only; no active strategy, trade, or timer mutation
- 禁止修改：active_cpb_params
- 禁止修改：strategy_versions
- 禁止修改：trade_plans
- 禁止修改：trades
- 禁止修改：positions
- 禁止修改：paper_live_behavior
- 禁止修改：broker_execution
- 禁止修改：timer_state
- paper_candidate_allowed=false
- future paper candidate work requires a separate strategy-version proposal/review task

## 禁止修改
- active_cpb_params
- strategy_versions
- trade_plans
- trades
- positions
- paper_live_behavior
- broker_execution
- timer_state
