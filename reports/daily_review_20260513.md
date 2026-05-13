# PGC 每日复盘报告

生成时间：2026-05-13T08:50:26.105550+00:00
复盘日：2026-05-13
最新行情日：2026-05-13
下一交易日：2026-05-14
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
- 最近 pipeline：skipped
- 当前阻断：MIN_PAPER_TRADES_NOT_MET
- 晋级 live 前还差什么：MIN_PAPER_TRADES_NOT_MET
- 晋级警告：AGENT_EVIDENCE_MISSING

## 纸盘每日运营验收

- 状态：阻断
- 验收摘要：纸盘每日运营验收阻断：1 项 blocker 需要先处理。
- 执行日：2026-05-14
- 数据新鲜度：通过；最新行情日 2026-05-13 / 复盘日 2026-05-13
- 证据覆盖：警告；全市场证据 0 条；Agent 覆盖 5 项；warning MARKET_EVIDENCE_MISSING
- Agent 状态：警告；skipped / no_opinion / risk unknown；warning AGENT_REVIEW_NOT_RUN
- open-execution 状态：通过；ready / record_sell
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
- [warning] 证据或行情不新鲜：2026-05-13 存在 MARKET_EVIDENCE_MISSING，需人工复核证据覆盖。
- [warning] Agent 复核缺失：2026-05-13 的 Agent 状态为 skipped / no_opinion / risk unknown。

## 下一交易日决策驾驶舱

- 状态：阻断
- 摘要：下一交易日决策被 1 项 blocker 阻断。
- 推荐人工动作：处理 paper acceptance 未处理 blocker。
- 执行日：2026-05-14
- 系统建议：录入卖出成交
- 目标：301188.SZ 力诺药包
- 计划 / 持仓：6 / 2
- 计划股数：2300
- 提醒：驾驶舱只读，不会执行交易、开启 timer 或修改策略参数。

决策清单：
- paper acceptance：阻断；纸盘每日运营验收阻断：1 项 blocker 需要先处理。；blocker MIN_PAPER_TRADES_NOT_MET；warning MARKET_EVIDENCE_MISSING, AGENT_REVIEW_NOT_RUN, AGENT_EVIDENCE_MISSING；下一步：处理 paper acceptance 未处理 blocker。
- 证据 freshness / coverage：警告；全市场证据 0 条；Agent 覆盖 5 项；warning MARKET_EVIDENCE_MISSING；下一步：补齐或确认 cached provider evidence，再重新运行只读验收。
- 全市场复盘 / 计划关系：警告；neutral / insufficient_evidence；Market regime neutral: breadth=0.62 trend=0.56 volume=0.36 persistence=0.18 coverage=1.00.；计划关系 missing；warning MARKET_PLAN_RELATIONSHIP_MISSING；下一步：人工复核全市场复盘给出的计划关系标签。
- open-execution 下一步：通过；ready / record_sell；下一步：人工核对卖出计划后录入卖出成交。
- 策略 proposal / hypothesis：通过；没有待审阅策略假设或 proposal。；下一步：无需策略参数动作；继续保持策略 evolution 只读边界。

策略 proposal / hypothesis：
- total=0 proposed=0 testing=0 accepted=0 review_required=0

动作日志 / 次日复核：
- 暂无驾驶舱动作日志；该日志只记录人工 follow/defer/override，不会执行交易或修改策略。

## 数据状态

- 结果：可交易
- 可交易：是
- 有效入池事件：262
- 阻断 / 警告：0 / 0
- 缺失行情：0

## 今日候选

- 股票：600397.SH 江钨装备
- 评分：121.2435
- 排名：1
- 计划买入日：2026-05-14
- 入选说明：highest_score_rank_1: 121.2435

| 排名 | 股票 | 评分 |
| ---: | --- | ---: |
| 1 | 600397.SH 江钨装备 | 121.2435 |

## 明日交易计划

- 动作：下一交易日开盘买入
- 状态：有效
- 计划交易日：2026-05-14
- 计划资金：67,607.00
- 计划股数：4400
- 原因：来自今日入选

## 全市场复盘

- 状态：已完成；中性（宽度0.62 / 趋势0.56 / 持续0.18）：Market regime neutral: breadth=0.62 trend=0.56 volume=0.36 persistence=0.18 coverage=1.00.
- 连续性判断：证据不足；缺少板块轮动、新闻/情绪证据，连续性不能当作安全信号。
- Top 5 板块：未找到板块轮动数据
- 代表个股：未找到代表个股
- 板块持续性：未找到持续性板块数据
- 外部证据覆盖：未找到全市场新闻/情绪证据；freshness market missing / sector missing / stock missing
- 策略假设：未生成策略假设
- 来源：market_review_runs:5 / market_regime_snapshots:5

## 全市场复盘与明日计划关系

- 市场状态：中性（宽度0.62 / 趋势0.56 / 持续0.18）：Market regime neutral: breadth=0.62 trend=0.56 volume=0.36 persistence=0.18 coverage=1.00.
- 强势板块：未找到板块轮动数据
- 候选板块匹配：未找到候选所属板块数据
- 新闻/情绪匹配：未找到新闻/情绪证据
- 计划关系：missing；计划关系缺少可用市场上下文，不能当作安全信号。
- 管理建议：人工复核；匹配 未知；风险 未知
- 理由：600397.SH lacks sector rotation and market-review external evidence for 20260513; manual review is required before acting on the plan.
- 来源：market_plan_contexts:5:5
- 提醒：该结论只提供管理建议，不会自动创建、取消或执行交易计划。

## 外部证据覆盖台账

- 覆盖状态：entries=10；blocking=10；ready_dates=无；blocking_dates=20260513
- 状态计数：missing=10 / unavailable=0 / partial=0 / stale=0 / duplicate=0 / source_hash_mismatch=0
- Provider pack：manifest_count=0；discovered=0
- 安全边界：read_only=true；live_fetches=false；writes_trade_state=false

## Shadow 策略观察

- 最新 artifact：monitor 2026-05-12 / preflight 2026-05-12；next_trade_date 2026-05-13
- 状态：blocked；candidate 5；blocked 5；distinct blockers 23；hypotheses 5
- blocker counts：active_cpb_db_params_hash_mismatch 1 / chase_gap_guard_required 1 / close_return_stability_required 1 / dip_buy_stop_and_sizing_required 1 / falling_knife_guard_required 1 / liquidity_slippage_review_required 1 / micro_sleeve_risk_model_required 1 / next_day_confirmation_rule_required 1 / operator_promotion_approval_required 5 / operator_review_required 5 / paper_observation_not_authorized 5 / proposal_review_required 5 / replay_backtest_result_artifact_required 5 / sector_evidence_confirmation_required 1 / separate_breakout_pressure_candidate_required 1 / separate_dip_buy_candidate_required 1 / separate_low_price_micro_sleeve_required 1 / separate_trend_extension_candidate_required 1 / strategy_version_proposal_not_authorized 5 / volume_overheat_guard_required 1 / walk_forward_shadow_monitor_20_trading_days_required 5 / watchlist_only_ui_lane_required 1 / watchlist_to_signal_contract_required 1
- top candidates：low_price_momentum_shadow（shadow_bucket，today 72，walk complete，blockers 10:liquidity_slippage_review_required/micro_sleeve_risk_model_required，top 600719.SH 大连热电）；breakout_pressure_shadow（shadow_bucket，today 69，walk complete，blockers 10:close_return_stability_required/operator_promotion_approval_required，top 603042.SH 华脉科技）；trend_extension_shadow（shadow_bucket，today 47，walk complete，blockers 10:chase_gap_guard_required/operator_promotion_approval_required，top 002428.SZ 云南锗业）；另有 2 条
- 安全边界：read_only=true；artifact_only=true；writes_trade_state=false；promotion_allowed=false
- 提醒：Shadow 候选是 research-only，仅展示监控/预检 artifact，不会进入今日候选、生成交易计划或开启 timer。

## Agent 复核

- 状态：已跳过
- 来源：TradingAgents 不可用 fallback
- 运行模式：unavailable_fallback
- 意见：无有效意见
- 风险：未知
- 摘要：optional package 'tradingagents' is not installed; install TauricResearch/TradingAgents to run external advisory
- 提醒：Agent 只提供复核意见，不会自动改变交易计划。
- 数据覆盖：技术面 可用 / 基本面 部分 / 新闻面 未接入 / 情绪面 部分

外部证据：
- [sector] pgc_pool_industry 2026-05-11 板块位置缓存：sector=专用机械；rank_overall=13；rank_in_sector=6；role=follower

未接入/缺失：
- 基本面仅部分接入：当前仅有估值、市值、换手率等 daily_basic 字段。
- 新闻/公告未接入/数据不足：600397.SH 江钨装备 截至 20260513 的新闻/公告数据源尚未接入本地库；Agent 不得编造新闻。
- 情绪面仅部分接入：当前情绪面只由价格、成交额、换手率等市场行为推断。

风险提示：
- optional package 'tradingagents' is not installed; install TauricResearch/TradingAgents to run external advisory

中文结构化报告：

### 基本面

来源：TradingAgents 不可用 fallback

基本面数据源未接入/数据不足。

风险提示：
- 基本面缺少真实输入，不能编造相关证据。

### 新闻

来源：TradingAgents 不可用 fallback

新闻面数据源未接入/数据不足。

风险提示：
- 新闻面缺少真实输入，不能编造相关证据。

### 情绪

来源：TradingAgents 不可用 fallback

情绪面数据源未接入/数据不足。

风险提示：
- 情绪面缺少真实输入，不能编造相关证据。

### 技术/量价

来源：TradingAgents 不可用 fallback

技术面数据源未接入/数据不足。

风险提示：
- 技术面缺少真实输入，不能编造相关证据。

### 板块位置

来源：TradingAgents 不可用 fallback

板块位置数据源未接入/数据不足。

风险提示：
- 板块位置缺少真实输入，不能编造相关证据。

### 风险

来源：TradingAgents 不可用 fallback

optional package 'tradingagents' is not installed; install TauricResearch/TradingAgents to run external advisory

风险提示：
- optional package 'tradingagents' is not installed; install TauricResearch/TradingAgents to run external advisory

### 结论

来源：TradingAgents 不可用 fallback

optional package 'tradingagents' is not installed; install TauricResearch/TradingAgents to run external advisory

风险提示：
- optional package 'tradingagents' is not installed; install TauricResearch/TradingAgents to run external advisory

## 当前持仓处理

| 股票 | 买入日 | 状态 | T+2 | T+5 | 当前处理 |
| --- | --- | --- | --- | --- | --- |
| 301188.SZ 力诺药包 | 2026-05-11 | 已有退出计划 | 2026-05-13 | 2026-05-18 | 已有卖出计划 |

## 数据血缘

| 项目 | ID |
| --- | ---: |
| 特征运行 | 6 |
| 策略运行 | 6 |
| 行情抓取 | 7 |
| 入选记录 | 3 |
| 信号记录 | 6 |
| 计划记录 | 5 |
| 全市场复盘 | 5 |
| Agent 运行 | 7 |
| Agent 意见 | 7 |
