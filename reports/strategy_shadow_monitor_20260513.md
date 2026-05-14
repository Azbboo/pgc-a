# 2026-05-13 影子策略监控

> 研究专用：上一交易日 2026-05-12 收盘生成影子候选，用 2026-05-13 实际行情验算；同时给出 2026-05-13 收盘后的次日观察名单。不会生成 paper/live 计划。

## 结论

- 今日 >=5% 池内上涨票 32 只，影子三桶覆盖 27 只，覆盖率 84.4%。
- 今日收盘影子候选共 183 只；趋势/突破/低价分别为 49/68/66。
- 20 日 walk-forward 状态：complete，20260410 至 20260512 共 20 个可验算信号日。
- Promotion preflight：blocked；候选 5 类，blocker 23 项，全部仍为 artifact-only。
- 方向判断可以继续观察，但 paper/proposal/promotion 都必须等 evidence gate 显式清空。
- 决策队列：blocked；experiment registry=available；候选 5 个，仍不允许晋升。
- 纸面预检：blocked；可进入后续人工纸面任务 0 个；paper_candidate_allowed=false。

## 昨日影子候选今日表现

| 桶 | 候选数 | T+1收盘均值% | T+1收盘胜率% | T+1最高均值% | 最高>=3% |
| --- | --- | --- | --- | --- | --- |
| breakout_pressure_shadow | 69 | 1.54 | 63.8 | 3.48 | 47.8 |
| low_price_momentum_shadow | 72 | 1.49 | 69.4 | 3.38 | 43.1 |
| trend_extension_shadow | 47 | 3.48 | 83 | 5.49 | 72.3 |

## 20 日 Walk-forward

| 候选 | 状态 | 天数 | T+1收盘均值% | T+1胜率% | T+1最高均值% | 冻结CPB T+1均值差% |
| --- | --- | --- | --- | --- | --- | --- |
| trend_extension_shadow | complete | 20 | 1.67 | 50 | 4.42 | -7.9 |
| breakout_pressure_shadow | complete | 20 | 0.77 | 70 | 3.36 | -8.8 |
| low_price_momentum_shadow | complete | 20 | 2.2 | 60 | 5.73 | -7.37 |
| preconfirm_watchlist | complete | 29 | 2.03 | - | 13.25 | -7.54 |
| pullback_dip_buy | artifact_summary_only | - | - | 47.62 | - | - |

## Walk-forward Outcome Accumulator

- 状态：partial；signals 60；complete 48；partial 12；missing_bars 0。
- 边界：只追加 market_bars 标签，不写 strategy/trade/position/paper-live/timer。

## 冻结 CPB 对照

- 来源：`reports/strategy_shadow_backtest_20260401_20260508.json`
- 状态：available；样本提示：small_frozen_cpb_sample
- DB/参数完整性：db_hash_match=False；params_file_hash_match=True。

## Promotion Preflight

| 候选 | Paper gate | Proposal gate | 主要 blockers |
| --- | --- | --- | --- |
| trend_extension_shadow | blocked | blocked | paper_observation_not_authorized, walk_forward_shadow_monitor_20_trading_days_required, operator_review_required... |
| breakout_pressure_shadow | blocked | blocked | paper_observation_not_authorized, walk_forward_shadow_monitor_20_trading_days_required, operator_review_required... |
| low_price_momentum_shadow | blocked | blocked | paper_observation_not_authorized, walk_forward_shadow_monitor_20_trading_days_required, operator_review_required... |
| preconfirm_watchlist | blocked | blocked | paper_observation_not_authorized, walk_forward_shadow_monitor_20_trading_days_required, operator_review_required... |
| pullback_dip_buy | blocked | blocked | paper_observation_not_authorized, walk_forward_shadow_monitor_20_trading_days_required, operator_review_required... |

## 决策队列 / Stop Rules

| 候选 | 证据 | 样本 | 实验 | Stop rules | 下次复核 |
| --- | --- | --- | --- | --- | --- |
| trend_extension_shadow | accepted | sufficient | registered | stop_if_replay_evidence_not_accepted, stop_if_sample_size_below_required, stop_if_metric_completeness_fails | 20260514 |
| breakout_pressure_shadow | accepted | sufficient | registered | stop_if_replay_evidence_not_accepted, stop_if_sample_size_below_required, stop_if_metric_completeness_fails | 20260514 |
| low_price_momentum_shadow | accepted | sufficient | registered | stop_if_replay_evidence_not_accepted, stop_if_sample_size_below_required, stop_if_metric_completeness_fails | 20260514 |
| preconfirm_watchlist | accepted | sufficient | registered | stop_if_replay_evidence_not_accepted, stop_if_sample_size_below_required, stop_if_metric_completeness_fails | 20260514 |
| pullback_dip_buy | accepted | insufficient | registered | stop_if_replay_evidence_not_accepted, stop_if_sample_size_below_required, stop_if_metric_completeness_fails | 20260514 |

## 手动纸面预检

- 结论：当前 5 个 shadow 候选均不得进入纸面候选；最高预检分 breakout_pressure_shadow=80/100，仍需独立人工 strategy-version 任务和风险/回滚确认。
| 候选 | 预检分 | 证据 | Walk-forward | Stop rules | 纸面候选 |
| --- | --- | --- | --- | --- | --- |
| breakout_pressure_shadow | 80 | accepted | sufficient | blocking | false |
| low_price_momentum_shadow | 80 | accepted | sufficient | blocking | false |
| preconfirm_watchlist | 80 | accepted | sufficient | blocking | false |
| trend_extension_shadow | 80 | accepted | sufficient | blocking | false |
| pullback_dip_buy | 50 | accepted | insufficient | blocking | false |

## 昨日各桶 Top1

| 桶 | 代码 | 名称 | 评分 | 开盘缺口% | 收盘收益% | 最高收益% |
| --- | --- | --- | --- | --- | --- | --- |
| trend_extension_shadow | 002428.SZ | 云南锗业 | 124.8948 | -1.4 | 1.51 | 5.1 |
| breakout_pressure_shadow | 603042.SH | 华脉科技 | 107.9674 | -2.71 | 3.61 | 5.22 |
| low_price_momentum_shadow | 600719.SH | 大连热电 | 117.9918 | 3.58 | -1.55 | 6.18 |

## 今日收盘次日观察 Top12

| 桶 | 代码 | 名称 | 评分 | 收盘 | 入池至今% | 5日% | 距20日高点% | 量/MA10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| trend_extension_shadow | 002428.SZ | 云南锗业 | 124.0459 | 101.51 | 282.77 | 31.81 | -3.42 | 1.2684 |
| trend_extension_shadow | 001359.SZ | 平安电工 | 123.7208 | 114.4 | 102.87 | 26.35 | -0.44 | 1.7389 |
| trend_extension_shadow | 301373.SZ | 凌玮科技 | 122.5118 | 149.8 | 128.77 | 22.94 | -2.51 | 0.9103 |
| trend_extension_shadow | 688028.SH | 沃尔德 | 121.6797 | 139.05 | 109.67 | 13.98 | -1.38 | 1.3535 |
| trend_extension_shadow | 002980.SZ | 华盛昌 | 121.1849 | 86.06 | 263.12 | 13.51 | -2.2 | 0.8196 |
| trend_extension_shadow | 300632.SZ | 光莆股份 | 120.4127 | 30.73 | 83.79 | 25.07 | -7.72 | 1.8276 |
| trend_extension_shadow | 002842.SZ | 翔鹭钨业 | 120.007 | 39.91 | 227.13 | 1.37 | -0.72 | 0.7743 |
| trend_extension_shadow | 300548.SZ | 长芯博创 | 118.8384 | 273.1 | 175 | 8.17 | -5.83 | 0.8738 |
| trend_extension_shadow | 301188.SZ | 力诺药包 | 118.7097 | 34.94 | 43.9 | 34.49 | -2.05 | 1.3648 |
| trend_extension_shadow | 002580.SZ | 圣阳股份 | 118.2721 | 34.8 | 78.1 | 16.86 | -3.84 | 1.0253 |
| trend_extension_shadow | 600184.SH | 光电股份 | 118.1073 | 29.12 | 51.75 | 24.44 | -2.9 | 1.5351 |
| trend_extension_shadow | 300672.SZ | 国科微 | 117.6385 | 242.63 | 52.29 | 27.7 | -4.15 | 1.2037 |

## 操作建议

- 明天先按观察名单盯盘，不把它直接混进 CPB 正式候选。
- 若要 paper 试跑，先补独立 observation lane 规则和 gap/liquidity/stop/sizing guard。
- 即便 walk-forward 样本已满 20 日，也只代表 preflight 输入具备；promotion blocker 仍需人工 artifact 审核后逐项清除。
