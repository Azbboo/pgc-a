# 影子到纸面预检 Shadow Paper Preflight 20260514

- contract: shadow_paper_preflight_v1
- 结论：本预检只生成手动晋级材料，不授权纸面候选、交易计划、paper/live 行为或 timer。
- 状态：blocked
- 候选数：5
- 可进入后续人工纸面任务：0
- paper_candidate_allowed=false
- 中文结论：当前 5 个 shadow 候选均不得进入纸面候选；最高预检分 breakout_pressure_shadow=60/100，仍需独立人工 strategy-version 任务和风险/回滚确认。

## 候选预检
- breakout_pressure_shadow: score=60/100; evidence=accepted; walk_forward=sufficient; stop_rule=blocking; paper_candidate_allowed=false; blockers=experiment_registry_not_ready, stop_rules_blocking, blocker:frozen_cpb_delta_not_positive, blocker:drawdown_proxy_missing, blocker:candidate_blockers_not_cleared
- low_price_momentum_shadow: score=60/100; evidence=accepted; walk_forward=sufficient; stop_rule=blocking; paper_candidate_allowed=false; blockers=experiment_registry_not_ready, stop_rules_blocking, blocker:frozen_cpb_delta_not_positive, blocker:drawdown_proxy_missing, blocker:candidate_blockers_not_cleared
- preconfirm_watchlist: score=60/100; evidence=accepted; walk_forward=sufficient; stop_rule=blocking; paper_candidate_allowed=false; blockers=experiment_registry_not_ready, stop_rules_blocking, blocker:frozen_cpb_delta_not_positive, blocker:drawdown_proxy_missing, blocker:candidate_blockers_not_cleared
- trend_extension_shadow: score=60/100; evidence=accepted; walk_forward=sufficient; stop_rule=blocking; paper_candidate_allowed=false; blockers=experiment_registry_not_ready, stop_rules_blocking, blocker:frozen_cpb_delta_not_positive, blocker:drawdown_proxy_missing, blocker:candidate_blockers_not_cleared
- pullback_dip_buy: score=30/100; evidence=accepted; walk_forward=insufficient; stop_rule=blocking; paper_candidate_allowed=false; blockers=walk_forward_insufficient, experiment_registry_not_ready, stop_rules_blocking, blocker:frozen_cpb_delta_missing, blocker:candidate_blockers_not_cleared

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
