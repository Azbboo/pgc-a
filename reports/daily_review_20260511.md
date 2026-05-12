# PGC 每日复盘报告

生成时间：2026-05-12T08:29:16.956856+00:00
复盘日：2026-05-11
最新行情日：2026-05-11
下一交易日：2026-05-12
策略版本：cpb_6157@2026-05-03

## 账户

- 账户：paper-main（Paper Main）
- 账户类型：paper
- 最大持仓：3
- 当前持仓：2
- 空闲仓位：1
- 最新权益：200,000.00

## Paper 晋级分数卡

- 状态：阻断，不能晋级 live
- 样本交易：2
- 已闭环交易：0
- 累计实现盈亏：0.00
- 胜率：-
- 平均滑点：0.62%
- 最近 pipeline：success
- 当前阻断：MIN_PAPER_TRADES_NOT_MET
- 晋级 live 前还差什么：MIN_PAPER_TRADES_NOT_MET
- 晋级警告：AGENT_EVIDENCE_MISSING

## 纸盘每日运营验收

- 状态：阻断
- 验收摘要：纸盘每日运营验收阻断：1 项 blocker 需要先处理。
- 执行日：2026-05-12
- 数据新鲜度：通过；最新行情日 2026-05-11 / 复盘日 2026-05-11
- 证据覆盖：通过；全市场证据 4 条；Agent 覆盖 5 项
- Agent 状态：警告；not_run / no_opinion / risk unknown；warning AGENT_REVIEW_NOT_RUN
- open-execution 状态：通过；ready / evaluate_exit
- 提醒：只读验收面板，不会执行交易、取消计划或改策略参数。

readiness gates：
- daily review readiness gate：通过；readiness=pass
- 账户容量 gate：通过；持仓 2/3；空闲 1
- Paper 样本交易：阻断；2/10 笔 executed paper trades；blocker MIN_PAPER_TRADES_NOT_MET
- 账本 invariant：通过；账本 invariant 通过
- 数据质量 blocker：通过；0 个 open blocker
- T+2 / T+5 待处理：通过；0 个到期退出判断
- 现金 / 权益核对：通过；现金/权益核对未发现警告
- Agent 证据链路：警告；缺少账户级 Agent 证据链路；warning AGENT_EVIDENCE_MISSING

未处理 blocker：
- Paper 样本交易: MIN_PAPER_TRADES_NOT_MET

验收告警：
- [blocker] 未处理 blocker：1 项 blocker 仍未处理，paper acceptance 不能视为通过。
- [warning] Agent 复核缺失：2026-05-11 的 Agent 状态为 not_run / no_opinion / risk unknown。

## 下一交易日决策驾驶舱

- 状态：阻断
- 摘要：下一交易日决策被 1 项 blocker 阻断。
- 推荐人工动作：处理 paper acceptance 未处理 blocker。
- 执行日：2026-05-12
- 系统建议：评估退出
- 目标：002647.SZ 仁东控股
- 计划 / 持仓：- / 1
- 计划股数：4800
- 提醒：驾驶舱只读，不会执行交易、开启 timer 或修改策略参数。

决策清单：
- paper acceptance：阻断；纸盘每日运营验收阻断：1 项 blocker 需要先处理。；blocker MIN_PAPER_TRADES_NOT_MET；warning AGENT_REVIEW_NOT_RUN, AGENT_EVIDENCE_MISSING；下一步：处理 paper acceptance 未处理 blocker。
- 证据 freshness / coverage：通过；全市场证据 4 条；Agent 覆盖 5 项；下一步：证据覆盖通过，保留 source_refs 供人工抽查。
- 全市场复盘 / 计划关系：警告；neutral；Market regime neutral: breadth=0.57 trend=0.72 volume=0.54 persistence=0.41 coverage=1.00.；计划建议 missing；warning MARKET_PLAN_CONTEXT_MISSING；下一步：补齐全市场复盘与明日计划关系，或人工确认该计划无需市场上下文。
- open-execution 下一步：通过；ready / evaluate_exit；下一步：人工评估到期持仓并按显式流程生成退出动作。
- 策略 proposal / hypothesis：警告；3 项策略假设或 proposal 需要人工审阅；accepted=0 testing=0 proposed=3；warning STRATEGY_PROPOSAL_REVIEW_REQUIRED；下一步：审阅策略假设和 proposal artifact；不要直接改 active params 或 paper/live 行为。

策略 proposal / hypothesis：
- total=3 proposed=3 testing=0 accepted=0 review_required=3
- Only buy CPB candidates when their sector persistence score is above threshold.（proposed）
- Boost rank when stock is sector leader and sector is in top 5.（proposed）
- Require manual review when market-plan context conflicts with a candidate.（proposed）

动作日志 / 次日复核：
- 暂无驾驶舱动作日志；该日志只记录人工 follow/defer/override，不会执行交易或修改策略。

## 数据状态

- 结果：可交易
- 可交易：是
- 有效入池事件：250
- 阻断 / 警告：0 / 0
- 缺失行情：0

## 今日候选

今日没有可执行候选。原因：策略未产生可执行信号

## 明日交易计划

当前没有已生成的明日交易计划。

## 全市场复盘

- 状态：已完成；中性（宽度0.57 / 趋势0.72 / 持续0.41）：Market regime neutral: breadth=0.57 trend=0.72 volume=0.54 persistence=0.41 coverage=1.00.
- Top 5 板块：装修装饰#1，持续 1.00；半导体#2，持续 1.00；玻璃#3，持续 1.00
- 板块持续性：装修装饰#1 持续 1.00；半导体#2 持续 1.00；玻璃#3 持续 1.00；矿物制品#4 持续 1.00；机床制造#5 持续 1.00
- 外部证据覆盖：4 条；范围 market 1 / sector 1 / stock 2；情绪 unknown 4；来源 pgc_reviewed_cache_m71 4；状态 市场可用 / 板块部分 / 个股部分 / 新闻可用 / 情绪缺失
- 策略假设：3 条；Only buy CPB candidates when their sector persistence score is above threshold.（proposed）；Boost rank when stock is sector leader and sector is in top 5.（proposed）；Require manual review when market-plan context conflicts with a candidate.（proposed）

## 全市场复盘与明日计划关系

- 状态：未生成全市场复盘与计划关系。
- 提醒：该部分只提供管理建议，不会自动创建、取消或执行交易计划。

## Agent 复核

- 状态：未运行
- 来源：TradingAgents 输出
- 运行模式：unknown
- 意见：无有效意见
- 风险：未知
- 摘要：Agent 复核尚未接入本次日报；确定性策略和人工检查优先。
- 提醒：Agent 只提供复核意见，不会自动改变交易计划。
- 数据覆盖：技术面 未知 / 基本面 可用 / 新闻面 缺失 / 情绪面 缺失

未接入/缺失：
- Agent cached provider evidence 缺失：公告/新闻/情绪。

## 当前持仓处理

| 股票 | 买入日 | 状态 | T+2 | T+5 | 当前处理 |
| --- | --- | --- | --- | --- | --- |
| 002647.SZ 仁东控股 | 2026-05-08 | 等待 T+2 | 2026-05-12 | 2026-05-15 | 暂无动作 |
| 301188.SZ 力诺药包 | 2026-05-11 | 等待 T+2 | 2026-05-13 | 2026-05-18 | 暂无动作 |

## 数据血缘

| 项目 | ID |
| --- | ---: |
| 特征运行 | 3 |
| 策略运行 | 3 |
| 行情抓取 | - |
| 入选记录 | - |
| 信号记录 | - |
| 计划记录 | - |
| 全市场复盘 | 3 |
| Agent 运行 | - |
| Agent 意见 | - |
