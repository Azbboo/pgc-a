# Market Review Data Source Design

日期：2026-05-09

## 1. 目标

本设计定义全市场复盘在生产环境如何接入真实市场、板块、新闻和情绪资料，同时明确测试 fixture 的边界。

核心约束：

- Fixture imports are for tests only.
- Tushare/official cached data is preferred for market and sector facts.
- Manual news/sentiment imports must include provider, title, date, summary, and source hash.
- Missing evidence is acceptable but must be explicit.
- No live web fetch inside daily trading path.

全市场复盘可以增强明日交易计划的人工判断，但不能自动改写策略参数、成交记录或持仓状态。所有资料都必须先进入受控缓存、数据库表或人工导入文件，再被 daily pipeline 读取。

## 2. 数据源分层

| 数据层 | 生产优先来源 | 允许缺失吗 | 生产落点 |
| --- | --- | --- | --- |
| 市场行情事实 | Tushare 缓存、交易所或官方缓存 | 不允许静默缺失 | `market_bars`、`trade_calendar`、`market_review_runs.coverage_json` |
| 板块事实 | Tushare/官方缓存、受控板块成分文件 | 可降级但必须显式 | `sector_daily_snapshots`、`sector_constituents` |
| 新闻/公告/情绪 | 人工审核后的 provider-tagged 缓存文件 | 允许缺失 | `market_external_items`、`coverage_summary` |
| 测试夹具 | `tests/fixtures/market_review` | 仅测试使用 | 临时测试库 |

manual_fixture is not a production provider. 它只用于单元测试、CLI contract test 和 golden replay。生产运行记录中若出现 `manual_fixture`，必须视为数据源配置错误或明确标记为演练。

## 3. Fixture 边界

Fixture imports are for tests only. 目前仓库中的示例文件，例如：

- `tests/fixtures/market_review/sector_memberships_20260508.json`
- `tests/fixtures/market_review/external_items_20260508.json`

只能用于：

1. 服务层单元测试；
2. CLI 路由测试；
3. golden replay 或迁移 smoke；
4. 文档示例。

禁止用于：

1. `data/pgc_trading.db` 的真实复盘日写入；
2. 远端 `/opt/pgc/data/pgc_trading.db`；
3. paper/live 明日交易计划；
4. 对外展示的生产日报。

如果需要做生产演练，文件名、provider 和运行记录必须写明 `drill` 或 `sandbox`，并使用独立演练库。

## 4. 市场与板块事实

Tushare/official cached data is preferred for market and sector facts. 生产复盘优先读取已缓存、可追溯、可重复的事实数据。

市场行情事实必须满足：

- `market_bars.trade_date <= as_of_date`；
- `trade_calendar` 覆盖复盘日、计划日、T+2 和 T+5；
- provider manifest 写入 `market_review_runs.provider_manifest_json`；
- coverage 写入 `market_review_runs.coverage_json`；
- 缺失时返回 blocker 或 warning，不能静默继续。

板块事实必须满足：

- provider 明确，例如 `tushare_concept_cache`、`exchange_industry_cache` 或其他官方缓存名；
- 成分股文件必须带 `as_of_date`；
- 导入前先 dry-run；
- 导入后能追溯到 `market_review_run_id`；
- 板块事实缺失时可以降级为 `missing` 或 `partial`，但日报和 Dashboard 必须显示。

yfinance 只能用于隔离的诊断行情，不替代 Tushare 生产行情、交易日历或 readiness gate。

## 5. 新闻与情绪资料

新闻、公告、政策、研究摘要和情绪数据必须先由人工或离线路径审核并缓存，再通过命令导入：

```bash
PYTHONPATH=src python3 -m pgc_trading.cli.main market-review external-data import \
  --date 20260508 \
  --file data/market_review/external_items_20260508.json \
  --db-path data/pgc_trading.db \
  --dry-run
```

确认无误后才允许 `--apply --operator azboo`。

Manual news/sentiment imports must include provider, title, date, summary, and source hash. 在当前落库模型中，单条记录至少应能形成并保存这些字段：

- `provider`：资料提供方或人工整理来源；
- `title`：标题；
- `published_date`：资料日期，等价于人工导入检查清单中的 date；
- `summary`：不超过服务层允许长度的摘要；
- `market_external_items.source_hash`：由 provider、scope、date、title 和 summary 生成或在导入清单中复核；
- `scope_type` 与 `scope_key`：明确资料作用于全市场、板块或个股；
- `sentiment` 与 `importance`：未知时使用 `unknown`，不能编造确定结论。

外部资料不能直接改变交易计划。它只能进入：

- 全市场复盘摘要；
- 明日计划关系说明；
- Agent input snapshot；
- 报告或 Dashboard 的外部证据区。

## 6. 缺失证据策略

Missing evidence is acceptable but must be explicit. 外部新闻/情绪缺失不是默认 blocker，但必须在运行输出中留下可见状态。

生产输出至少要区分：

- `available`：证据可用；
- `partial`：部分证据可用；
- `missing`：没有证据；
- `unknown`：资料存在但无法判断情绪或重要性。

`MarketExternalDataService.summarize_coverage` 输出的 `coverage_summary` 是新闻/情绪覆盖度的最小契约。报告、Dashboard 或明日计划关系不能把 `missing` 渲染成“无风险”；正确表述是“未接入/证据不足，需要人工判断”。

## 7. 禁止实时抓取

No live web fetch inside daily trading path. 以下路径不得在运行时请求网页、搜索引擎、新闻 API、社媒 API 或模型在线工具来补齐资料：

- `scripts/run_daily_pipeline.sh`
- `pgc daily-close`
- `pgc market-review run`
- `pgc market-review import-sectors`
- `pgc market-review external-data import`
- `pgc report daily`
- Dashboard read API

如果需要外部数据，必须在 daily trading path 之前完成离线缓存或人工整理，并保留 provider、文件 hash、导入命令、operator 和 run id。实时抓取失败不能在 pipeline 内被自动重试为另一种来源。

## 8. 生产操作顺序

推荐顺序：

1. 刷新 Tushare/官方缓存，确认 `market_bars` 和 `trade_calendar` 覆盖复盘日。
2. 准备板块成分缓存文件，使用生产 provider 名称，先 dry-run `market-review import-sectors`。
3. 准备新闻/情绪缓存文件，检查 provider、title、date、summary 和 source hash，先 dry-run `market-review external-data import`。
4. 运行 `market-review run --dry-run`，确认 coverage 和 provider manifest。
5. 运行 `scripts/run_daily_pipeline.sh --dry-run`，确认日报把缺失证据显式展示。
6. 只有当行情、交易日历、账户和 operator 门禁通过时，才执行 `--apply`。

## 9. 审计清单

每个生产复盘日必须能回答：

- 哪些数据来自 Tushare 或官方缓存；
- 哪些板块成分来自哪个 provider；
- 哪些新闻/情绪资料缺失；
- 哪些人工导入文件参与了复盘；
- `provider_manifest_json` 是否包含生产 provider；
- `coverage_summary` 是否没有把缺失证据伪装成可用；
- 是否没有在 daily trading path 内发生 live web fetch；
- 测试 fixture 是否没有写入生产库。
