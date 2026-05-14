# 2026-05-14 影子策略监控

> 研究专用：上一交易日 2026-05-13 收盘生成影子候选，用 2026-05-14 实际行情验算；同时给出 2026-05-14 收盘后的次日观察名单。不会生成 paper/live 计划。

## 结论

- 今日 >=5% 池内上涨票 16 只，影子三桶覆盖 9 只，覆盖率 56.2%。
- 今日收盘影子候选共 170 只；趋势/突破/低价分别为 40/62/68。
- 20 日 walk-forward 状态：complete，20260413 至 20260513 共 20 个可验算信号日。
- Promotion preflight：blocked；候选 5 类，blocker 23 项，全部仍为 artifact-only。
- 方向判断可以继续观察，但 paper/proposal/promotion 都必须等 evidence gate 显式清空。
- 决策队列：blocked；experiment registry=available；候选 5 个，仍不允许晋升。
- 纸面预检：blocked；可进入后续人工纸面任务 0 个；paper_candidate_allowed=false。

## 昨日影子候选今日表现

| 桶 | 候选数 | T+1收盘均值% | T+1收盘胜率% | T+1最高均值% | 最高>=3% |
| --- | --- | --- | --- | --- | --- |
| breakout_pressure_shadow | 68 | -3.05 | 7.4 | 1.71 | 16.2 |
| low_price_momentum_shadow | 66 | -3.04 | 12.1 | 1.57 | 16.7 |
| trend_extension_shadow | 49 | -3.36 | 16.3 | 2.8 | 36.7 |

## 20 日 Walk-forward

| 候选 | 状态 | 天数 | T+1收盘均值% | T+1胜率% | T+1最高均值% | 冻结CPB T+1均值差% |
| --- | --- | --- | --- | --- | --- | --- |
| trend_extension_shadow | complete | 20 | 1.49 | 45 | 4.59 | -8.08 |
| breakout_pressure_shadow | complete | 20 | 0.45 | 65 | 3.21 | -9.12 |
| low_price_momentum_shadow | complete | 20 | 2.08 | 60 | 5.88 | -7.49 |
| preconfirm_watchlist | complete | 30 | 1.61 | - | 13.25 | -7.96 |
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
| trend_extension_shadow | accepted | sufficient | registered | stop_if_replay_evidence_not_accepted, stop_if_sample_size_below_required, stop_if_metric_completeness_fails | 20260515 |
| breakout_pressure_shadow | accepted | sufficient | registered | stop_if_replay_evidence_not_accepted, stop_if_sample_size_below_required, stop_if_metric_completeness_fails | 20260515 |
| low_price_momentum_shadow | accepted | sufficient | registered | stop_if_replay_evidence_not_accepted, stop_if_sample_size_below_required, stop_if_metric_completeness_fails | 20260515 |
| preconfirm_watchlist | accepted | sufficient | registered | stop_if_replay_evidence_not_accepted, stop_if_sample_size_below_required, stop_if_metric_completeness_fails | 20260515 |
| pullback_dip_buy | accepted | insufficient | registered | stop_if_replay_evidence_not_accepted, stop_if_sample_size_below_required, stop_if_metric_completeness_fails | 20260515 |

## 手动纸面预检

- 结论：当前 5 个 shadow 候选均不得进入纸面候选；最高预检分 breakout_pressure_shadow=60/100，仍需独立人工 strategy-version 任务和风险/回滚确认。
| 候选 | 预检分 | 证据 | Walk-forward | Stop rules | 纸面候选 |
| --- | --- | --- | --- | --- | --- |
| breakout_pressure_shadow | 60 | accepted | sufficient | blocking | false |
| low_price_momentum_shadow | 60 | accepted | sufficient | blocking | false |
| preconfirm_watchlist | 60 | accepted | sufficient | blocking | false |
| trend_extension_shadow | 60 | accepted | sufficient | blocking | false |
| pullback_dip_buy | 30 | accepted | insufficient | blocking | false |

## 昨日各桶 Top1

| 桶 | 代码 | 名称 | 评分 | 开盘缺口% | 收盘收益% | 最高收益% |
| --- | --- | --- | --- | --- | --- | --- |
| trend_extension_shadow | 002428.SZ | 云南锗业 | 124.0459 | -1.49 | -2.8 | 5.17 |
| breakout_pressure_shadow | 002112.SZ | 三变科技 | 106.364 | -1.13 | -6.18 | 0 |
| low_price_momentum_shadow | 600719.SH | 大连热电 | 115.3768 | -4.62 | -5.61 | 3 |

## 今日收盘次日观察 Top12

| 桶 | 代码 | 名称 | 评分 | 收盘 | 入池至今% | 5日% | 距20日高点% | 量/MA10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| trend_extension_shadow | 300632.SZ | 光莆股份 | 121.4576 | 31.85 | 90.49 | 28.58 | -4.35 | 1.4455 |
| trend_extension_shadow | 002428.SZ | 云南锗业 | 121.4217 | 97.2 | 266.52 | 21.2 | -7.58 | 1.1508 |
| trend_extension_shadow | 002980.SZ | 华盛昌 | 120.712 | 94.67 | 299.45 | 13.51 | 0 | 1.0454 |
| trend_extension_shadow | 301188.SZ | 力诺药包 | 120.2224 | 36.85 | 51.77 | 40.22 | -2.44 | 1.4993 |
| trend_extension_shadow | 600105.SH | 永鼎股份 | 118.9527 | 53.99 | 91.32 | 13.62 | -4.26 | 1.2172 |
| trend_extension_shadow | 002943.SZ | 宇晶股份 | 118.7416 | 86.5 | 66.19 | 23.94 | -2.46 | 1.1462 |
| trend_extension_shadow | 301373.SZ | 凌玮科技 | 118.0207 | 143 | 118.39 | 2.18 | -9.26 | 0.895 |
| trend_extension_shadow | 002885.SZ | 京泉华 | 117.824 | 44.76 | 46.04 | 21.37 | -3.39 | 1.7658 |
| trend_extension_shadow | 002842.SZ | 翔鹭钨业 | 117.3667 | 38.14 | 212.62 | -2.53 | -7.83 | 1.0944 |
| trend_extension_shadow | 600184.SH | 光电股份 | 117.0236 | 29.3 | 52.68 | 22.24 | -5.15 | 1.4485 |
| trend_extension_shadow | 300672.SZ | 国科微 | 116.6929 | 245 | 53.78 | 21.89 | -4.03 | 0.9962 |
| low_price_momentum_shadow | 600488.SH | 津药药业 | 116.1386 | 7.79 | 3.18 | 30.49 | -1.64 | 1.9276 |

## 操作建议

- 明天先按观察名单盯盘，不把它直接混进 CPB 正式候选。
- 若要 paper 试跑，先补独立 observation lane 规则和 gap/liquidity/stop/sizing guard。
- 即便 walk-forward 样本已满 20 日，也只代表 preflight 输入具备；promotion blocker 仍需人工 artifact 审核后逐项清除。
