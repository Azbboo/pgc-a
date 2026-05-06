import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const inputPath = process.argv[2] ? resolve(process.argv[2]) : resolve(ROOT, "data", "pgc_pool.json");
const outDir = resolve(ROOT, "reports");
const dataOutDir = resolve(ROOT, "data");
const rawEventsOut = resolve(dataOutDir, "pgc_raw_events.json");
const jsonOut = resolve(outDir, "pgc_raw_event_research.json");
const mdOut = resolve(outDir, "pgc_raw_event_research.md");

const sourceRows = JSON.parse(readFileSync(inputPath, "utf8"));

const RAW_FIELDS = ["ts_code", "code", "name", "entry_date", "entry_time", "entry_price"];
const EXCLUDED_FIELDS = [
  "latest_close",
  "latest_ret",
  "max_high",
  "max_high_date",
  "current_drawdown",
  "max_3d",
  "pnl3_reported",
  "bull_prob",
  "bull_reason",
  "status",
  "discard_reason",
  "industry",
  "day_pct",
  "main_attack",
  "limit_up_stars",
];

function parseDate(value) {
  const s = String(value ?? "");
  if (!/^\d{8}$/.test(s)) return null;
  return new Date(Date.UTC(Number(s.slice(0, 4)), Number(s.slice(4, 6)) - 1, Number(s.slice(6, 8))));
}

function formatDate(value) {
  const s = String(value ?? "");
  return /^\d{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}` : "";
}

function weekdayName(value) {
  const date = parseDate(value);
  if (!date) return "";
  return ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][date.getUTCDay()];
}

function quantile(sorted, p) {
  if (!sorted.length) return null;
  return sorted[Math.floor((sorted.length - 1) * p)];
}

function round(value, digits = 2) {
  return Number.isFinite(value) ? Number(value.toFixed(digits)) : null;
}

function summarize(values) {
  const sorted = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
  const n = sorted.length;
  if (!n) {
    return { n: 0, min: null, p25: null, median: null, p75: null, max: null, mean: null };
  }
  return {
    n,
    min: round(sorted[0]),
    p25: round(quantile(sorted, 0.25)),
    median: round(quantile(sorted, 0.5)),
    p75: round(quantile(sorted, 0.75)),
    max: round(sorted.at(-1)),
    mean: round(sorted.reduce((sum, value) => sum + value, 0) / n),
  };
}

function groupCount(rows, keyFn) {
  const counts = new Map();
  for (const row of rows) {
    const key = keyFn(row);
    if (key == null || key === "") continue;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([key, count]) => ({ key, count, pct: round((count / rows.length) * 100, 1) }))
    .sort((a, b) => b.count - a.count || String(a.key).localeCompare(String(b.key)));
}

function priceBucket(price) {
  if (!Number.isFinite(price)) return "missing";
  if (price < 5) return "<5";
  if (price < 10) return "5-10";
  if (price < 20) return "10-20";
  if (price < 50) return "20-50";
  if (price < 100) return "50-100";
  return ">=100";
}

const rawEvents = sourceRows.map((row, index) => {
  const event = {
    event_id: index + 1,
    ts_code: row.ts_code ?? null,
    code: row.code ?? null,
    name: row.name ?? null,
    entry_date: row.entry_date ?? null,
    entry_time: row.entry_time ?? null,
    entry_price: Number.isFinite(Number(row.entry_price)) ? Number(row.entry_price) : null,
  };
  event.entry_month = /^\d{8}$/.test(String(event.entry_date ?? "")) ? String(event.entry_date).slice(0, 6) : null;
  event.entry_weekday = weekdayName(event.entry_date);
  event.price_bucket = priceBucket(event.entry_price);
  return event;
});

const eventKeyCounts = new Map();
for (const event of rawEvents) {
  const key = `${event.ts_code}|${event.entry_date}|${event.entry_price}`;
  eventKeyCounts.set(key, (eventKeyCounts.get(key) ?? 0) + 1);
}

const codeCounts = new Map();
for (const event of rawEvents) {
  codeCounts.set(event.ts_code, (codeCounts.get(event.ts_code) ?? 0) + 1);
}

const entryDates = rawEvents.map((event) => event.entry_date).filter((value) => /^\d{8}$/.test(String(value ?? ""))).sort();
const missing = Object.fromEntries(
  RAW_FIELDS.map((field) => [
    field,
    rawEvents.filter((event) => event[field] === null || event[field] === undefined || event[field] === "").length,
  ]),
);

const analysis = {
  generated_at: new Date().toISOString(),
  input_path: inputPath,
  methodology: {
    raw_fields_used: RAW_FIELDS,
    explicitly_excluded_fields: EXCLUDED_FIELDS,
    rule: "Only entry facts are used. Existing score, reason, status, industry, and post-entry performance fields are ignored.",
  },
  data_quality: {
    rows: rawEvents.length,
    entry_date_min: formatDate(entryDates[0]),
    entry_date_max: formatDate(entryDates.at(-1)),
    unique_ts_code: new Set(rawEvents.map((event) => event.ts_code)).size,
    duplicate_exact_events: [...eventKeyCounts.entries()].filter(([, count]) => count > 1).length,
    weekend_entries: rawEvents
      .filter((event) => ["Sat", "Sun"].includes(event.entry_weekday))
      .map((event) => ({
        ts_code: event.ts_code,
        name: event.name,
        entry_date: event.entry_date,
        entry_weekday: event.entry_weekday,
        entry_price: event.entry_price,
      })),
    repeated_ts_code_events: [...codeCounts.entries()]
      .filter(([, count]) => count > 1)
      .map(([ts_code, count]) => ({ ts_code, count })),
    missing,
  },
  raw_statistics: {
    entry_price: summarize(rawEvents.map((event) => event.entry_price)),
    entry_month: groupCount(rawEvents, (event) => event.entry_month).sort((a, b) => String(a.key).localeCompare(String(b.key))),
    entry_weekday: groupCount(rawEvents, (event) => event.entry_weekday),
    entry_date_top20: groupCount(rawEvents, (event) => event.entry_date).slice(0, 20),
    price_bucket: groupCount(rawEvents, (event) => event.price_bucket),
  },
  next_research_requires_market_data: {
    post_entry_labels: [
      "t+1/t+3/t+5/t+10/t+20 returns",
      "MFE: max favorable excursion after entry",
      "MAE: max adverse excursion after entry",
      "time to first target / first stop",
      "gap and limit-up/limit-down tradability",
    ],
    pre_entry_features: [
      "pre-entry 1/3/5/10/20 day returns",
      "volume and turnover acceleration",
      "volatility and ATR",
      "distance from moving averages",
      "new high / breakout / pullback structure before entry",
      "market index and industry regime before entry",
    ],
  },
};

function mdTable(headers, rows, rowFn) {
  return [
    `| ${headers.join(" | ")} |`,
    `| ${headers.map(() => "---").join(" | ")} |`,
    ...rows.map((row) => `| ${rowFn(row).join(" | ")} |`),
  ].join("\n");
}

const report = `# PGC原始入池事件统计研究

> 这份报告只使用原始入池事实：\`${RAW_FIELDS.join("`, `")}\`。已有 JSON 中的 \`bull_prob/bull_reason/status/industry/latest_ret/max_high/max_3d/current_drawdown\` 等字段全部视为不可用，不参与任何策略筛选。

## 结论

上一版“PGC高概率回调健康趋势延续策略”应废弃，原因是它依赖 \`bull_prob/bull_reason\`，而这两个字段不属于当前确认的原始数据。

在只有入池时间和入池价格的前提下，我们目前只能做两类研究：

1. **原始事件分布研究**：入池频率、价格带、日期集中度、重复入池。
2. **事件回测研究设计**：补齐逐日行情后，从入池事件出发重新计算收益、回撤、止盈止损、持有期表现。

不能直接得出胜率、期望收益、最大回撤或最佳止盈止损，因为这些都需要入池后的真实行情。

## 数据概况

- 样本数：${analysis.data_quality.rows}
- 入池日期：${analysis.data_quality.entry_date_min} 至 ${analysis.data_quality.entry_date_max}
- 唯一股票数：${analysis.data_quality.unique_ts_code}
- 完全重复事件数：${analysis.data_quality.duplicate_exact_events}
- 重复入池股票数：${analysis.data_quality.repeated_ts_code_events.length}
- 缺失入池日期：${analysis.data_quality.missing.entry_date}
- 缺失入池时间：${analysis.data_quality.missing.entry_time}
- 缺失入池价格：${analysis.data_quality.missing.entry_price}
- 周末入池日期记录：${analysis.data_quality.weekend_entries.length}

## 入池价格分布

- 最低价：${analysis.raw_statistics.entry_price.min}
- 25分位：${analysis.raw_statistics.entry_price.p25}
- 中位数：${analysis.raw_statistics.entry_price.median}
- 75分位：${analysis.raw_statistics.entry_price.p75}
- 最高价：${analysis.raw_statistics.entry_price.max}
- 均值：${analysis.raw_statistics.entry_price.mean}

${mdTable(
  ["价格带", "数量", "占比"],
  analysis.raw_statistics.price_bucket,
  (row) => [row.key, row.count, `${row.pct}%`],
)}

## 入池时间分布

### 月度分布

${mdTable(
  ["月份", "数量", "占比"],
  analysis.raw_statistics.entry_month,
  (row) => [row.key, row.count, `${row.pct}%`],
)}

### 星期分布

${mdTable(
  ["星期", "数量", "占比"],
  analysis.raw_statistics.entry_weekday,
  (row) => [row.key, row.count, `${row.pct}%`],
)}

### 入池最多的日期

${mdTable(
  ["日期", "数量", "占比"],
  analysis.raw_statistics.entry_date_top20,
  (row) => [formatDate(row.key), row.count, `${row.pct}%`],
)}

## 正确的下一步统计研究

### 1. 纯入池事件基准

补齐行情后，先不做任何筛选，测试所有入池事件：

- 买入：入池日收盘后收到信号，次一交易日开盘或 VWAP 买入
- 持有：1、3、5、10、20 个交易日
- 输出：胜率、中位收益、均值、P25/P75、最大亏损、最大有利波动 MFE、最大不利波动 MAE

这一步回答：PGC入池本身是否有统计优势。

### 2. 只使用原始字段的过滤器

在没有其他特征前，只允许研究：

- 入池价格带：如 <5、5-10、10-20、20-50、50-100、>=100
- 入池月份/星期/时段：如果未来有更完整的 \`entry_time\`
- 重复入池：同一股票再次入池是否更强或更弱

这一步回答：最朴素的原始事件字段有没有边际价值。

### 3. 用行情重新计算入池前特征

后续可以加入特征，但必须从行情数据计算，且只使用 \`entry_date\` 当天或之前可见的数据：

- 入池前 1/3/5/10/20 日涨跌幅
- 成交额、换手率、量比、波动率
- 均线距离、突破、回踩、趋势强度
- 大盘和行业环境

这样生成的新 \`score/reason\` 才是可审计、可复算、无未来函数的。

## 防未来函数规则

- 买入条件只能使用 \`entry_date\` 当天收盘前已知的信息。
- 结果字段只能用于标签和评估，不能用于筛选。
- 研究中挑出的规则必须在后续新增样本上走前验证。
- 回测成交价不能默认等于 \`entry_price\`；应测试次日开盘、次日 VWAP 或可成交价。
- 必须处理涨跌停、停牌、ST、手续费、滑点、T+1。
`;

mkdirSync(outDir, { recursive: true });
mkdirSync(dataOutDir, { recursive: true });
writeFileSync(rawEventsOut, `${JSON.stringify(rawEvents, null, 2)}\n`);
writeFileSync(jsonOut, `${JSON.stringify(analysis, null, 2)}\n`);
writeFileSync(mdOut, report);

console.log(`Wrote ${rawEventsOut}`);
console.log(`Wrote ${jsonOut}`);
console.log(`Wrote ${mdOut}`);
