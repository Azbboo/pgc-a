# 2026-05-15 影子策略明日观察计划

生成依据：`2026-05-14` 收盘 shadow 候选、`shadow_v2_bucket_specific` 权重回测、`daily_review_20260514` 市场状态。

## 结论

- 明日 shadow 仅做研究观察，不写入正式 CPB 候选、paper 计划、live 计划或交易状态。
- 市场状态为 `risk_off`，不能扩大观察池；只看分桶 Top，且必须用开盘确认过滤。
- 优先级：低价动量 v2 > 趋势延伸验证 > 突破压力观察。
- 今日优化回测显示，低价桶 v2 近 5 日 T+1 均值 `+6.98%`，比 current 提升 `+4.98pct`；突破桶只小幅改善，趋势桶不改权重。

## 分桶观察名单

| 优先级 | 桶 | 代码 | 名称 | 2026-05-14 收盘 | v2 排名 | 观察定位 |
| --- | --- | --- | --- | ---: | ---: | --- |
| A1 | low_price_momentum_shadow | 002081.SZ | 金螳螂 | 7.93 | 1 | 低价桶主观察；形态更符合 v2 稳定消化 |
| A2 | low_price_momentum_shadow | 600488.SH | 津药药业 | 7.79 | 2 | current Top1，但日涨幅/5日涨幅偏热，只能低吸确认 |
| A3 | low_price_momentum_shadow | 002547.SZ | 春兴精工 | 3.29 | 3 | 低价备选；不追高 |
| A4 | low_price_momentum_shadow | 002329.SZ | 皇氏集团 | 4.76 | 4 | 低价备选；只看换手稳定 |
| B1 | trend_extension_shadow | 300632.SZ | 光莆股份 | 31.85 | 1 | 趋势桶主观察；趋势延伸但不涨停贴高 |
| B2 | trend_extension_shadow | 002428.SZ | 云南锗业 | 97.20 | 2 | 趋势强度验证；前期波动大，控制追高 |
| B3 | trend_extension_shadow | 301188.SZ | 力诺药包 | 36.85 | 4 | 趋势备选；5日涨幅偏大，等确认 |
| C1 | breakout_pressure_shadow | 300582.SZ | 英飞特 | 16.44 | 1 | 突破桶只观察；不作为主攻 |
| C2 | breakout_pressure_shadow | 301111.SZ | 粤万年青 | 24.15 | 2 | 突破桶观察；等开盘后强弱 |
| C3 | breakout_pressure_shadow | 002962.SZ | 五方光电 | 19.27 | 3 | 突破桶观察；只做记录 |

## 明日执行边界

- 不自动生成交易计划，不自动入 paper，不自动晋级策略版本。
- 若人工决定做纸面观察，只允许从 A 组低价桶中选择 1 只作为 micro sleeve 观察样本。
- C 组突破桶不做主攻，因为最近 5 日 current Top1 为 `-1.10%`，v2 后仍为 `-0.37%`。
- B 组趋势桶保持原权重，只验证强弱，不因单日强势扩大仓位假设。

## 开盘确认规则

- A 组低价桶：优先开盘区间为相对前收 `-2%` 到 `+3%`；高开超过 `+4%` 不追，低开超过 `-3%` 且 15 分钟不能收回前收则剔除。
- A 组必须满足开盘后量能温和放大，不能出现无承接冲高回落；若 30 分钟跌破开盘低点且放量，停止观察。
- B 组趋势桶：只看小幅高开或平开后能否站稳前收；涨停、接近涨停或跳空过大时不追。
- C 组突破桶：只记录是否放量站上开盘区间高点；不做纸面动作。

## 盘中记录点

- 09:35：记录开盘缺口、是否直接过热。
- 10:00：记录是否站稳前收、开盘区间高点、VWAP。
- 11:30：记录半日强弱和最高收益标签。
- 14:30：记录是否尾盘回落或放量分歧。
- 收盘后：补 `T+1 close/high/low` 标签，复跑 shadow v2 回测。

## 复盘命令

```bash
PYTHONPATH=src:. python3 scripts/backtest_shadow_v2_weights.py --date 20260515 --walk-forward-days 20 --apply --compact
PYTHONPATH=src:. python3 scripts/monitor_shadow_strategies.py --date 20260515 --compact
```
