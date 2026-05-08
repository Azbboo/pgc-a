# M14A yfinance 接入评估

日期：2026-05-08

## 结论

`yfinance` 不适合作为当前 PGC Market 层的 Tushare 替换源。它可以作为实验性备用 OHLCV 数据源或诊断工具接入，但不能作为日常复盘、数据质量 blocker、T+2/T+5 交易日推导、`daily_basic` 特征和生产回测的唯一行情来源。

建议：

- 保持 `tushare` 为默认和生产主行情源；
- 若进入 M14B，仅以可选依赖和显式 `provider="yfinance"` 接入；
- `yfinance` 接入首版只覆盖历史日线 OHLCV，不覆盖交易日历和 `daily_basic`；
- 默认测试套件不得依赖 Yahoo 网络，真实请求只做手动 smoke；
- 在 README/运行手册中标注 Yahoo 数据使用条款与非官方来源风险。

## 评估依据

### 外部资料

- PyPI 显示 `yfinance` 最新版本为 `1.3.0`，发布时间为 2026-04-16：<https://pypi.org/project/yfinance/>
- yfinance 官方文档说明其是非官方 Yahoo Finance 工具，面向研究和教育用途，并提醒 Yahoo Finance API intended for personal use only：<https://ranaroussi.github.io/yfinance/>
- `yfinance.download` 当前支持批量 ticker、`start`/`end`、`period`、日线和分钟级 interval；`auto_adjust=True` 为默认；分钟级数据不能超过最近 60 天：<https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html>
- yfinance 的 price repair 文档提示非美国市场数据质量可能不稳定，需要修复逻辑兜底：<https://ranaroussi.github.io/yfinance/advanced/price_repair.html>
- Yahoo Developer API Terms 说明 Yahoo 可自行施加 rate limits，也可变更、暂停或终止 API 可用性：<https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html>

### 本地代码契约

当前生产接口是 `src/pgc_trading/market/tushare_adapter.py` 中的 `MarketDataAdapter`：

- `fetch_market_data(ts_codes, start_date, end_date, include_daily_basic=True)` 返回 `MarketDataPayload`；
- `fetch_trade_calendar(start_date, end_date, exchange="SSE")` 返回交易日历；
- `MarketBar` 当前字段包括 `open/high/low/close/vol/amount/adj_factor/adj_*`；
- `DailyBasicSnapshot` 当前字段包括换手率、量比、估值、市值和股本等；
- `MarketDataService` 会把 `request.provider` 写入 `market_fetch_runs`、`market_bars`、`daily_basic_snapshots` 和 `trade_calendar`；因此非生产 provider 不能直接写入生产 `market_bars`，否则会因 `(ts_code, trade_date)` 主键覆盖 Tushare 行情。

这意味着 `yfinance` 不能只“能拉价格”就算完整接入；它必须满足或明确降级这些服务契约。

## A 股可用性探针

本地依赖状态：

```text
yfinance False
pandas True
```

直接探测 Yahoo chart/quote API，样例覆盖深市、沪市和北交所代码：

| 样例 | Yahoo symbol | Endpoint | 结果 |
| --- | --- | --- | --- |
| 300077.SZ | `300077.SZ` | `query1.finance.yahoo.com/v8/finance/chart` | `429 Edge: Too Many Requests` |
| 600519.SH | `600519.SS` | `query1.finance.yahoo.com/v8/finance/chart` | `429 Edge: Too Many Requests` |
| 000001.SZ | `000001.SZ` | `query1.finance.yahoo.com/v8/finance/chart` | `429 Edge: Too Many Requests` |
| 830799.BJ | `830799.BJ` | `query1.finance.yahoo.com/v8/finance/chart` | `429 Edge: Too Many Requests` |
| 300077.SZ | `300077.SZ` | `query2.finance.yahoo.com/v8/finance/chart` with UA | `403 Yahoo error page` |
| 600519.SH | `600519.SS` | `query2.finance.yahoo.com/v8/finance/chart` with UA | `403 Yahoo error page` |
| 300077.SZ | `300077.SZ` | `query1.finance.yahoo.com/v7/finance/quote` with UA | `403 Yahoo error page` |
| 600519.SH | `600519.SS` | `query1.finance.yahoo.com/v7/finance/quote` with UA | `403 Yahoo error page` |

解读：

- 当前环境不能稳定直连 Yahoo 数据接口；
- 这类失败和 Yahoo Terms 中的 rate limits/availability 风险一致；
- 即使 `yfinance` 客户端可通过 cookie/cache 做更多处理，也不能把它设计为每日复盘的强依赖；
- M14B 如做实现，应把网络失败降级为 `MARKET_PROVIDER_ERROR`，并保留 Tushare 作为主路径。

## 字段差距矩阵

| 当前需求 | Tushare 路径 | yfinance 可行性 | 风险/差距 |
| --- | --- | --- | --- |
| A 股 ts_code | 原生 `300077.SZ`、`600519.SH` | 需映射沪市 `.SH -> .SS`，深市 `.SZ` 基本保持 | 北交所和部分特殊证券覆盖不确定 |
| 日线 OHLC | `daily` | `download/history` 可取 | Yahoo 可用性和口径需逐票校验 |
| 成交量 `vol` | Tushare `vol` | Yahoo `Volume` | 单位口径可能不同，不能和旧特征混用前不做归一 |
| 成交额 `amount` | Tushare `amount` | 无稳定等价字段 | 不建议用 `close * volume` 伪造 |
| 复权因子 | `adj_factor` | 无 Tushare 等价因子 | 可用 `Adj Close / Close` 近似复权比例，但口径不同 |
| `adj_open/high/low/close` | `daily + adj_factor` | 可用 `auto_adjust=False` 后按 `Adj Close/Close` 合成 | 必须标记 provider，不能与 Tushare adj_factor 直接比较 |
| `daily_basic` | `daily_basic` | 无完整等价 | 换手率、量比、估值、市值、股本缺失 |
| 交易日历 | `trade_cal` | 无可靠未来日历 | 只能从历史 bars 推断开市日，不能支撑 S+1/T+2/T+5 blocker |
| 停牌/缺行情判断 | Tushare + calendar | 只能观察空 bars | 难区分停牌、未覆盖、接口失败 |
| 合规/稳定性 | 官方 token 接口 | 非官方 Yahoo 数据路径 | 个人使用、限流、服务变更风险高 |

## 代码接入方案

若推进 M14B，建议最小实现如下。

### 依赖边界

`pyproject.toml` 增加可选 extra，而不是默认依赖：

```toml
[project.optional-dependencies]
yfinance = [
  "yfinance>=1.3,<2",
]
```

原因：

- 当前生产测试不依赖网络；
- 没装 yfinance 时不影响 Tushare 主路径；
- 可通过 `python3 -m pip install -e '.[yfinance]'` 显式启用。

### 新模块

新增 `src/pgc_trading/market/yfinance_adapter.py`：

- `provider = "yfinance"`；
- 实现 `MarketDataAdapter.fetch_market_data`；
- `fetch_trade_calendar` 首版返回配置错误或明确的 unsupported error，不从 bars 伪造未来交易日历；
- ticker 映射函数：
  - `*.SH -> *.SS`
  - `*.SZ -> *.SZ`
  - `*.BJ -> *.BJ`，但默认标记为 best-effort；
- date 映射：
  - 输入仍用项目标准 `YYYYMMDD`；
  - 调用 yfinance 前转为 `YYYY-MM-DD`；
  - 注意 yfinance `end` 是 exclusive，需传入 `end_date + 1 day`。

### 数据口径

首版建议：

- 调用 `yf.download(..., auto_adjust=False, actions=False, threads=False, timeout=10, progress=False)`；
- `open/high/low/close` 写 Yahoo 原始 OHLC；
- `vol` 写 Yahoo `Volume`，不做 Tushare 单位假定；
- `amount = None`；
- 若存在 `Adj Close` 且 `Close > 0`：
  - `adj_factor = Adj Close / Close`；
  - `adj_close = Adj Close`；
  - `adj_open/high/low = raw * adj_factor`；
- `daily_basic` 始终为空，并在 `include_daily_basic=True` 时返回 warning 或在调用层强制关闭。

### 服务层策略

不建议改造 `MarketDataService` 的主流程；应继续通过现有 `adapter` 注入点接入：

- CLI/API 后续可以接受 `--provider yfinance`；
- 当 `provider="yfinance"` 且 `include_daily_basic=True` 时，CLI 应提示该 provider 不支持 daily basic；
- data quality readiness 不能把 yfinance 当作交易日历来源；
- `market_fetch_runs.manifest_json` 记录 ticker 映射、原始 Yahoo symbol、成功/失败票、复权口径说明。

## 测试建议

默认测试：

- ticker 映射单元测试；
- yfinance DataFrame 到 `MarketBar` 的转换测试，使用手工构造 DataFrame；
- empty frame 写 `missing_ts_codes`；
- `include_daily_basic=True` 不写 fake basic；
- `fetch_trade_calendar` 不支持时返回明确错误；
- `MarketDataService` 使用 yfinance provider 后只写 `market_fetch_runs` 和隔离的诊断行情表，不写生产 `market_bars`，也不创建生产 data-quality blocker。

手动 smoke：

- 使用环境变量开关，例如 `PGC_ENABLE_YFINANCE_SMOKE=1`；
- 对 `300077.SZ`、`600519.SH`、`000001.SZ` 做 1 个月日线请求；
- 网络 `403/429/timeout` 只记录为 smoke 失败，不进入默认 CI gate。

对账验证：

- 选 20 只 PGC 样本股票；
- 用同一日期区间比较 Tushare 与 yfinance 的 open/high/low/close/volume 缺失率和价格偏差；
- 只有当缺失率、复权口径和单位口径能解释清楚，才允许用于研究报告。

## M14A 验收结果

| 项目 | 结果 |
| --- | --- |
| 能否作为 Tushare 替代 | 不通过 |
| 能否作为实验性备用 OHLCV 源 | 有条件通过 |
| 是否应接入默认依赖 | 不应接入 |
| 是否可支撑交易日历 | 不通过 |
| 是否可支撑 `daily_basic` 特征 | 不通过 |
| 是否可支撑研究对账/诊断 | 有条件通过 |
| 当前网络可用性 | 探针失败，出现 `403/429` |

最终建议：M14A 可以关闭为“评估完成”。若继续 M14B，实现范围应限制为可选 `YFinanceAdapter`、离线单元测试和手动 smoke，不改变 Tushare 主路径，也不让 yfinance 数据进入生产 readiness gate。

## M14B 实施结果

M14B 按最小接入范围完成：

- 新增 `pgc_trading.market.yfinance_adapter.YFinanceAdapter`；
- `pyproject.toml` 新增可选 extra：`python3 -m pip install -e '.[yfinance]'`；
- `MarketDataService` 在无显式 adapter 注入时支持 `provider="yfinance"`；
- yfinance 只写隔离诊断表中的历史日线 OHLCV，`amount=None`，`daily_basic` 始终不写；
- `Adj Close / Close` 可用时记录为近似 `adj_factor`，并生成 `adj_open/high/low/close`；
- `market_fetch_runs.manifest_json` 记录 Yahoo ticker 映射、诊断存储表、daily_basic/trade_calendar/amount 不支持等 metadata；
- `fetch_trade_calendar` 对 yfinance 明确返回 provider error，不伪造交易日历；
- 新增离线单元测试，使用 fake yfinance module/下载函数，不访问 Yahoo 网络。

保留限制：

- Tushare 仍是默认和生产主 provider；
- yfinance 不能进入 daily readiness gate 或 T+2/T+5 日期推导；
- 真实 Yahoo smoke 仍需人工通过环境开关单独执行，不进入默认测试套件。
