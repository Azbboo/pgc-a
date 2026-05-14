# PGC 每日复盘报告

生成时间：2026-05-14T10:55:20.143979+00:00
复盘日：2026-05-14
最新行情日：2026-05-14
下一交易日：2026-05-15
策略版本：cpb_6157@2026-05-03

## 账户

- 账户：paper-main（Paper Main）
- 账户类型：paper
- 最大持仓：3
- 当前持仓：1
- 空闲仓位：2
- 最新权益：198,464.00

## Paper 晋级分数卡

- 状态：阻断，不能晋级 live
- 样本交易：3
- 已闭环交易：1
- 累计实现盈亏：-1,536.00
- 胜率：0.00%
- 平均滑点：0.62%
- 最近 pipeline：success
- 当前阻断：MIN_PAPER_TRADES_NOT_MET
- 晋级 live 前还差什么：MIN_PAPER_TRADES_NOT_MET
- 晋级警告：AGENT_EVIDENCE_MISSING

## 纸盘每日运营验收

- 状态：阻断
- 验收摘要：纸盘每日运营验收阻断：1 项 blocker 需要先处理。
- 执行日：2026-05-15
- 数据新鲜度：通过；最新行情日 2026-05-14 / 复盘日 2026-05-14
- 证据覆盖：警告；全市场证据 0 条；Agent 覆盖 0 项；warning MARKET_EVIDENCE_MISSING, AGENT_EXTERNAL_EVIDENCE_MISSING
- Agent 状态：警告；not_run / no_opinion / risk unknown；warning AGENT_REVIEW_NOT_RUN
- open-execution 状态：通过；idle / none
- 提醒：只读验收面板，不会执行交易、取消计划或改策略参数。

readiness gates：
- daily review readiness gate：通过；readiness=pass
- 账户容量 gate：通过；持仓 1/3；空闲 2
- Paper 样本交易：阻断；3/10 笔 executed paper trades；blocker MIN_PAPER_TRADES_NOT_MET
- 账本 invariant：通过；账本 invariant 通过
- 数据质量 blocker：通过；0 个 open blocker
- T+2 / T+5 待处理：通过；0 个到期退出判断
- 现金 / 权益核对：通过；现金/权益核对未发现警告
- Agent 证据链路：警告；缺少账户级 Agent 证据链路；warning AGENT_EVIDENCE_MISSING

未处理 blocker：
- Paper 样本交易: MIN_PAPER_TRADES_NOT_MET

验收告警：
- [blocker] 未处理 blocker：1 项 blocker 仍未处理，paper acceptance 不能视为通过。
- [warning] 证据或行情不新鲜：2026-05-14 存在 MARKET_EVIDENCE_MISSING, AGENT_EXTERNAL_EVIDENCE_MISSING，需人工复核证据覆盖。
- [warning] Agent 复核缺失：2026-05-14 的 Agent 状态为 not_run / no_opinion / risk unknown。

## 下一交易日决策驾驶舱

- 状态：阻断
- 摘要：下一交易日决策被 1 项 blocker 阻断。
- 推荐人工动作：处理 paper acceptance 未处理 blocker。
- 执行日：2026-05-15
- 系统建议：无动作
- 目标：-
- 计划 / 持仓：- / -
- 计划股数：-
- 提醒：驾驶舱只读，不会执行交易、开启 timer 或修改策略参数。

决策清单：
- paper acceptance：阻断；纸盘每日运营验收阻断：1 项 blocker 需要先处理。；blocker MIN_PAPER_TRADES_NOT_MET；warning MARKET_EVIDENCE_MISSING, AGENT_EXTERNAL_EVIDENCE_MISSING, AGENT_REVIEW_NOT_RUN, AGENT_EVIDENCE_MISSING；下一步：处理 paper acceptance 未处理 blocker。
- 证据 freshness / coverage：警告；全市场证据 0 条；Agent 覆盖 0 项；warning MARKET_EVIDENCE_MISSING, AGENT_EXTERNAL_EVIDENCE_MISSING；下一步：补齐或确认 cached provider evidence，再重新运行只读验收。
- 全市场复盘 / 计划关系：警告；risk_off / insufficient_evidence；Market regime risk_off: breadth=0.17 trend=0.26 volume=0.38 persistence=0.11 coverage=1.00.；计划关系 missing；warning MARKET_PLAN_CONTEXT_MISSING；下一步：补齐全市场复盘与明日计划关系，或人工确认该计划无需市场上下文。
- open-execution 下一步：通过；idle / none；下一步：下一交易日没有待执行动作，保持观察。
- 策略 proposal / hypothesis：通过；没有待审阅策略假设或 proposal。；下一步：无需策略参数动作；继续保持策略 evolution 只读边界。

策略 proposal / hypothesis：
- total=0 proposed=0 testing=0 accepted=0 review_required=0

动作日志 / 次日复核：
- 暂无驾驶舱动作日志；该日志只记录人工 follow/defer/override，不会执行交易或修改策略。

## 数据状态

- 结果：可交易
- 可交易：是
- 有效入池事件：268
- 阻断 / 警告：0 / 0
- 缺失行情：0

## 今日候选

今日没有可执行候选。原因：策略未产生可执行信号

## 明日交易计划

当前没有已生成的明日交易计划。

## 全市场复盘

### 全市场结论

- 结论：全市场处于风险收缩（宽度0.17 / 趋势0.26 / 量能0.38 / 持续0.11）：Market regime risk_off: breadth=0.17 trend=0.26 volume=0.38 persistence=0.11 coverage=1.00.
- 状态：已完成；风险收缩（宽度0.17 / 趋势0.26 / 持续0.11）：Market regime risk_off: breadth=0.17 trend=0.26 volume=0.38 persistence=0.11 coverage=1.00.
- 连续性判断：证据不足；缺少板块轮动、新闻/情绪证据，连续性不能当作安全信号。

### 板块持续性

- Top 5 板块：未找到板块轮动数据
- 板块持续性：未找到持续性板块数据
- 排名理由：板块轮动数据缺失，无法解释哪些板块有持续性。

### 代表个股

- 代表个股：未找到代表个股
- 个股理由：代表个股证据不足：缺少 sector_constituents 或板块成员排名。

### 证据缺口

- 外部证据覆盖：未找到全市场新闻/情绪证据；freshness market missing / sector missing / stock missing
- 缺口：板块轮动数据缺失，板块排名和持续性证据不足。; 市场级新闻/情绪证据缺失，不能编造支持性证据。; 板块新闻/情绪证据缺失，不能编造支持性证据。; 个股新闻/情绪证据缺失，不能编造支持性证据。; 新闻证据缺失，不能编造支持性证据。; 情绪证据缺失，不能编造支持性证据。; 明日计划关系缺失，不能自动推导交易动作。
- 连续性叙事：连续性判断为证据不足；缺少板块轮动、新闻/情绪证据，连续性不能当作安全信号。

### 与明日计划关系

- 计划关系：明日计划关系缺失，不能从复盘自动推导交易动作。
- 策略假设：未生成策略假设
- 来源：market_review_runs:6 / market_regime_snapshots:6

## 全市场复盘与明日计划关系

- 状态：未生成全市场复盘与计划关系。
- 提醒：该部分只提供管理建议，不会自动创建、取消或执行交易计划。

## 外部证据覆盖台账

- 覆盖状态：entries=10；blocking=10；ready_dates=无；blocking_dates=20260514
- 状态计数：missing=10 / unavailable=0 / partial=0 / stale=0 / duplicate=0 / source_hash_mismatch=0
- Provider pack：manifest_count=0；discovered=0
- 安全边界：read_only=true；live_fetches=false；writes_trade_state=false

## Shadow 策略观察 (shadow_observation)

- section_key：shadow_observation
- 最新 artifact：monitor 2026-05-14 / preflight 2026-05-14；next_trade_date 2026-05-15
- 状态：blocked；candidate 5；blocked 5；distinct blockers 23；hypotheses 5
- blocker counts：active_cpb_db_params_hash_mismatch 1 / chase_gap_guard_required 1 / close_return_stability_required 1 / dip_buy_stop_and_sizing_required 1 / falling_knife_guard_required 1 / liquidity_slippage_review_required 1 / micro_sleeve_risk_model_required 1 / next_day_confirmation_rule_required 1 / operator_promotion_approval_required 5 / operator_review_required 5 / paper_observation_not_authorized 5 / proposal_review_required 5 / replay_backtest_result_artifact_required 5 / sector_evidence_confirmation_required 1 / separate_breakout_pressure_candidate_required 1 / separate_dip_buy_candidate_required 1 / separate_low_price_micro_sleeve_required 1 / separate_trend_extension_candidate_required 1 / strategy_version_proposal_not_authorized 5 / volume_overheat_guard_required 1 / walk_forward_shadow_monitor_20_trading_days_required 5 / watchlist_only_ui_lane_required 1 / watchlist_to_signal_contract_required 1
- replay/backtest evidence：accepted 5 / rejected 0 / missing 0
- top candidates：low_price_momentum_shadow（shadow_bucket，today 68，walk complete，replay accepted，blockers 10:liquidity_slippage_review_required/micro_sleeve_risk_model_required，top 600488.SH 津药药业）；breakout_pressure_shadow（shadow_bucket，today 62，walk complete，replay accepted，blockers 10:close_return_stability_required/operator_promotion_approval_required，top 301157.SZ 华塑科技）；trend_extension_shadow（shadow_bucket，today 40，walk complete，replay accepted，blockers 10:chase_gap_guard_required/operator_promotion_approval_required，top 300632.SZ 光莆股份）；另有 2 条
- 安全边界：read_only=true；artifact_only=true；writes_trade_state=false；promotion_allowed=false
- 提醒：Shadow 候选是 research-only，仅展示监控/预检 artifact，不会进入今日候选、生成交易计划或开启 timer。

候选明细：

| candidate | family | status | today | walk_forward | blockers | top |
| --- | --- | --- | ---: | --- | --- | --- |
| low_price_momentum_shadow | shadow_bucket | blocked | 68 | complete | 10:liquidity_slippage_review_required/micro_sleeve_risk_model_required/operator_promotion_approval_required/operator_review_required/paper_observation_not_authorized/proposal_review_required/replay_backtest_result_artifact_required/separate_low_price_micro_sleeve_required/strategy_version_proposal_not_authorized/walk_forward_shadow_monitor_20_trading_days_required | 600488.SH 津药药业 |
| breakout_pressure_shadow | shadow_bucket | blocked | 62 | complete | 10:close_return_stability_required/operator_promotion_approval_required/operator_review_required/paper_observation_not_authorized/proposal_review_required/replay_backtest_result_artifact_required/separate_breakout_pressure_candidate_required/strategy_version_proposal_not_authorized/volume_overheat_guard_required/walk_forward_shadow_monitor_20_trading_days_required | 301157.SZ 华塑科技 |
| trend_extension_shadow | shadow_bucket | blocked | 40 | complete | 10:chase_gap_guard_required/operator_promotion_approval_required/operator_review_required/paper_observation_not_authorized/proposal_review_required/replay_backtest_result_artifact_required/sector_evidence_confirmation_required/separate_trend_extension_candidate_required/strategy_version_proposal_not_authorized/walk_forward_shadow_monitor_20_trading_days_required | 300632.SZ 光莆股份 |
| pullback_dip_buy | dip_buy | blocked | - | artifact_summary_only | 11:daily_walk_forward_monitor_required_for_dip_buy/dip_buy_stop_and_sizing_required/falling_knife_guard_required/operator_promotion_approval_required/operator_review_required/paper_observation_not_authorized/proposal_review_required/replay_backtest_result_artifact_required/separate_dip_buy_candidate_required/strategy_version_proposal_not_authorized/walk_forward_shadow_monitor_20_trading_days_required | - |
| preconfirm_watchlist | preconfirm_watchlist | blocked | - | complete | 10:next_day_confirmation_rule_required/operator_promotion_approval_required/operator_review_required/paper_observation_not_authorized/proposal_review_required/replay_backtest_result_artifact_required/strategy_version_proposal_not_authorized/walk_forward_shadow_monitor_20_trading_days_required/watchlist_only_ui_lane_required/watchlist_to_signal_contract_required | - |

source_refs：monitor_json=/Users/azboo/Desktop/Person/pgc/reports/strategy_shadow_monitor_20260514.json; monitor_markdown=/Users/azboo/Desktop/Person/pgc/reports/strategy_shadow_monitor_20260514.md; promotion_preflight_json=/Users/azboo/Desktop/Person/pgc/reports/strategy_shadow_promotion_preflight_20260514.json; promotion_preflight_markdown=/Users/azboo/Desktop/Person/pgc/reports/strategy_shadow_promotion_preflight_20260514.md

## Shadow Walk-forward Outcomes

- 状态：partial；candidate 5；signals 60；complete 48；partial 12；missing_bars 0
- no-future boundary：passed=true；max_input_date=20260514；cutoff=20260514
- blockers：trend_extension_shadow:shadow_walk_forward_partial_horizon;breakout_pressure_shadow:shadow_walk_forward_partial_horizon;low_price_momentum_shadow:shadow_walk_forward_partial_horizon;preconfirm_watchlist:shadow_walk_forward_source_rows_missing;pullback_dip_buy:shadow_walk_forward_source_rows_missing
- 边界：post-close label accumulator only；不会写策略版本、交易计划、成交、持仓或 timer。

| candidate | status | signals | complete | partial | missing | T+1 mean | T+5 mean |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| trend_extension_shadow | partial | 20 | 16 | 4 | 0 | 1.49% | 2.46% |
| breakout_pressure_shadow | partial | 20 | 16 | 4 | 0 | 0.45% | 8.25% |
| low_price_momentum_shadow | partial | 20 | 16 | 4 | 0 | 2.08% | 2.76% |
| preconfirm_watchlist | missing | 0 | 0 | 0 | 0 | - | - |
| pullback_dip_buy | missing | 0 | 0 | 0 | 0 | - | - |

## Shadow Evidence Closure

- 状态：pass；missing blockers 0
- artifact parity：dossier=pass / replay_backtest_evidence=pass / review_request=pass / scorecard=pass / walk_forward_outcomes=pass
- replay/backtest evidence：accepted 5 / rejected 0 / missing 0
- Dashboard history parity：pass；empty_history_risk=false
- local/remote parity：pass；remote_sync_required=true
- missing blockers：none
- 边界：review package only；review_ready 不是批准；不会 promote、写交易计划、成交、持仓或 timer。

## Shadow 中文决策备忘录

- contract：shadow_decision_memo_v1
- 状态：blocked；候选 5
- 结论：当前仍为阻断：review_ready 0 个，blocker 29 个，experiment registry 状态 missing。
- replay/backtest：accepted 5 / rejected 0 / missing 0
- 阻断原因：no_review_ready_candidates;shadow_threshold_calibration_missing;shadow_strategy_experiment_registry_missing;frozen_cpb_delta_not_positive;drawdown_proxy_missing;candidate_blockers_not_cleared;chase_gap_guard_required;operator_promotion_approval_required
- 下一步实验：0 项；来源只允许 artifact-only 补证据/扩样本。
- 人工决策：4 项；本备忘录不是 approval。
- 风险/回滚边界：不 approve、不 promote、不创建交易计划、不记录成交、不改持仓、不改 paper/live、不改 timer。

证据状态：

- promotion review request: blocked；人工评审请求只作为复核上下文，不是批准。
- replay/backtest evidence: accepted；accepted 5 / rejected 0 / missing 0
- walk-forward outcomes: complete；20/20 个观察交易日；最新 outcome 20260514
- threshold calibration: missing；calibration artifact 未找到；不能据此放行晋升。
- experiment registry: missing；experiment registry artifact 未找到；不能据此放行晋升。

| candidate | evidence | walk_forward | blockers | 下一步 |
| --- | --- | --- | ---: | --- |
| trend_extension_shadow | accepted | complete | 12 | 补齐证据后再人工复核 |
| breakout_pressure_shadow | accepted | complete | 12 | 补齐证据后再人工复核 |
| low_price_momentum_shadow | accepted | complete | 12 | 补齐证据后再人工复核 |
| preconfirm_watchlist | accepted | complete | 12 | 补齐证据后再人工复核 |
| pullback_dip_buy | accepted | artifact_summary_only | 12 | 补齐证据后再人工复核 |

回滚/安全 notes：review_ready is not approval;keep active CPB params/hash unchanged;do not create or update strategy_versions, trade_plans, trades, positions, paper/live behavior, broker execution, or timers;blocked_mutation_targets=active_cpb_params,strategy_versions,trade_plans,trades,positions,paper_live_behavior,broker_execution,timer_state;promotion_allowed=false;manual review only; no active strategy, trade, or timer mutation

## Agent 复核

- 状态：未运行
- 来源：TradingAgents 输出
- 运行模式：unknown
- 意见：无有效意见
- 风险：未知
- 摘要：Agent 复核尚未接入本次日报；确定性策略和人工检查优先。
- 提醒：Agent 只提供复核意见，不会自动改变交易计划。

## 当前持仓处理

| 股票 | 买入日 | 状态 | T+2 | T+5 | 当前处理 |
| --- | --- | --- | --- | --- | --- |
| 301188.SZ 力诺药包 | 2026-05-11 | 已有退出计划 | 2026-05-13 | 2026-05-18 | 已有卖出计划 |

## 数据血缘

| 项目 | ID |
| --- | ---: |
| 特征运行 | 7 |
| 策略运行 | 7 |
| 行情抓取 | - |
| 入选记录 | - |
| 信号记录 | - |
| 计划记录 | - |
| 全市场复盘 | 6 |
| Agent 运行 | - |
| Agent 意见 | - |
