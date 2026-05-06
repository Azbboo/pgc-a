#!/usr/bin/env python3
"""Run raw-only PGC event study using cached Tushare daily data."""

from __future__ import annotations

import argparse
import json
from pandas.errors import EmptyDataError
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW_EVENTS_PATH = ROOT / "data" / "pgc_raw_events.json"
MARKET_DIR = ROOT / "data" / "tushare"
OUT_DIR = ROOT / "reports"
DATA_OUT = ROOT / "data" / "pgc_event_backtest.csv"
JSON_OUT = OUT_DIR / "pgc_event_backtest.json"
MD_OUT = OUT_DIR / "pgc_event_backtest.md"

HORIZONS = [1, 3, 5, 10, 20]
FEATURE_COLUMNS = [
    "entry_day_pct_chg",
    "entry_day_amp",
    "entry_price_pos_in_day",
    "entry_price_to_close",
    "pre_ret_1d",
    "pre_ret_3d",
    "pre_ret_5d",
    "pre_ret_10d",
    "pre_ret_20d",
    "pre_amount_ratio_5_20",
    "pre_volatility_20",
    "dist_ma5",
    "dist_ma10",
    "dist_ma20",
    "range_pos_20",
    "breakout_20",
    "signal_turnover_rate",
    "signal_volume_ratio",
]
EXIT_CONFIGS = [
    {"name": "TP6_SL6_10D", "take_profit": 0.06, "stop_loss": -0.06, "max_days": 10},
    {"name": "TP10_SL8_20D", "take_profit": 0.10, "stop_loss": -0.08, "max_days": 20},
    {"name": "TP15_SL10_20D", "take_profit": 0.15, "stop_loss": -0.10, "max_days": 20},
]


@dataclass(frozen=True)
class MarketData:
    frame: pd.DataFrame
    by_date: dict[str, int]


def pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"{value * 100:.2f}%"


def pct_num(value: float | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value) * 100, 4)


def round_num(value: float | None, digits: int = 4) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def quantile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    return sorted_values[int((len(sorted_values) - 1) * p)]


def summarize(values: Iterable[float]) -> dict:
    clean = sorted(float(value) for value in values if pd.notna(value))
    n = len(clean)
    if not n:
        return {
            "n": 0,
            "win_rate": None,
            "mean": None,
            "median": None,
            "p25": None,
            "p75": None,
            "min": None,
            "max": None,
            "avg_win": None,
            "avg_loss": None,
        }

    wins = [value for value in clean if value > 0]
    losses = [value for value in clean if value < 0]
    return {
        "n": n,
        "win_rate": round_num(len(wins) / n),
        "mean": round_num(sum(clean) / n),
        "median": round_num(quantile(clean, 0.5)),
        "p25": round_num(quantile(clean, 0.25)),
        "p75": round_num(quantile(clean, 0.75)),
        "min": round_num(clean[0]),
        "max": round_num(clean[-1]),
        "avg_win": round_num(sum(wins) / len(wins)) if wins else None,
        "avg_loss": round_num(sum(losses) / len(losses)) if losses else None,
    }


def summarize_table(df: pd.DataFrame, columns: list[str]) -> list[dict]:
    return [{"metric": column, **summarize(df[column].dropna())} for column in columns if column in df.columns]


def group_summary(df: pd.DataFrame, group_col: str, metric: str, min_n: int = 5) -> list[dict]:
    rows = []
    for key, group in df.groupby(group_col, dropna=False):
        stats = summarize(group[metric].dropna())
        if stats["n"] >= min_n:
            rows.append({"key": key, **stats})
    return sorted(rows, key=lambda item: (item["median"] is not None, item["median"]), reverse=True)


def load_events(path: Path) -> pd.DataFrame:
    with path.open("r", encoding="utf-8") as f:
        return pd.DataFrame(json.load(f))


def read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype={"trade_date": str})
    except EmptyDataError:
        return pd.DataFrame()


def load_market(ts_code: str, market_dir: Path) -> MarketData | None:
    daily = read_csv_if_exists(market_dir / "daily" / f"{ts_code}.csv")
    if daily.empty:
        return None

    adj = read_csv_if_exists(market_dir / "adj_factor" / f"{ts_code}.csv")
    if adj.empty:
        daily["adj_factor"] = 1.0
        merged = daily
    else:
        merged = daily.merge(adj[["ts_code", "trade_date", "adj_factor"]], on=["ts_code", "trade_date"], how="left")
        merged["adj_factor"] = merged["adj_factor"].ffill().bfill().fillna(1.0)

    basic = read_csv_if_exists(market_dir / "daily_basic" / f"{ts_code}.csv")
    if not basic.empty:
        merged = merged.merge(basic, on=["ts_code", "trade_date"], how="left", suffixes=("", "_basic"))

    for col in ["open", "high", "low", "close"]:
        merged[f"adj_{col}"] = merged[col] * merged["adj_factor"]

    merged = merged.sort_values("trade_date").reset_index(drop=True)
    by_date = {str(row.trade_date): int(index) for index, row in merged.iterrows()}
    return MarketData(frame=merged, by_date=by_date)


def first_index_after(frame: pd.DataFrame, date: str) -> int | None:
    matches = frame.index[frame["trade_date"] > str(date)].tolist()
    return int(matches[0]) if matches else None


def first_index_at_or_after(frame: pd.DataFrame, date: str) -> int | None:
    matches = frame.index[frame["trade_date"] >= str(date)].tolist()
    return int(matches[0]) if matches else None


def ret_from_adj(base_adj_price: float, target_adj_price: float) -> float | None:
    if not base_adj_price or pd.isna(base_adj_price) or base_adj_price <= 0:
        return None
    return float(target_adj_price / base_adj_price - 1)


def safe_mean(series: pd.Series) -> float | None:
    clean = series.dropna()
    if clean.empty:
        return None
    return float(clean.mean())


def safe_std(series: pd.Series) -> float | None:
    clean = series.dropna()
    if len(clean) < 2:
        return None
    return float(clean.std())


def add_pre_entry_features(result: dict, frame: pd.DataFrame, signal_idx: int, entry_price: float) -> None:
    row = frame.iloc[signal_idx]
    day_range = row["high"] - row["low"]
    result["entry_day_pct_chg"] = float(row["pct_chg"] / 100) if pd.notna(row.get("pct_chg")) else None
    result["entry_day_amp"] = float(day_range / row["pre_close"]) if pd.notna(row.get("pre_close")) and row["pre_close"] else None
    result["entry_price_pos_in_day"] = float((entry_price - row["low"]) / day_range) if day_range else None
    result["entry_price_to_close"] = float(entry_price / row["close"] - 1) if row["close"] else None
    result["entry_price_in_day_range"] = bool(entry_price >= row["low"] * 0.999 and entry_price <= row["high"] * 1.001)

    for lookback in [1, 3, 5, 10, 20]:
        base_idx = signal_idx - lookback
        if base_idx >= 0:
            result[f"pre_ret_{lookback}d"] = ret_from_adj(frame.iloc[base_idx]["adj_close"], row["adj_close"])

    if signal_idx >= 20:
        recent_5 = frame.iloc[max(0, signal_idx - 4) : signal_idx + 1]
        recent_20 = frame.iloc[signal_idx - 19 : signal_idx + 1]
        previous_20 = frame.iloc[max(0, signal_idx - 39) : signal_idx - 19]
        amount_5 = safe_mean(recent_5["amount"])
        amount_20 = safe_mean(previous_20["amount"]) or safe_mean(recent_20["amount"])
        if amount_5 is not None and amount_20:
            result["pre_amount_ratio_5_20"] = amount_5 / amount_20

        pct_std = safe_std(recent_20["pct_chg"] / 100)
        if pct_std is not None:
            result["pre_volatility_20"] = pct_std

        high_20 = recent_20["adj_high"].max()
        low_20 = recent_20["adj_low"].min()
        if high_20 != low_20:
            result["range_pos_20"] = float((row["adj_close"] - low_20) / (high_20 - low_20))

        previous_high_20 = frame.iloc[max(0, signal_idx - 20) : signal_idx]["adj_high"].max()
        if previous_high_20 and pd.notna(previous_high_20):
            result["breakout_20"] = ret_from_adj(previous_high_20, row["adj_close"])

    for ma in [5, 10, 20]:
        if signal_idx >= ma - 1:
            avg = safe_mean(frame.iloc[signal_idx - ma + 1 : signal_idx + 1]["adj_close"])
            if avg:
                result[f"dist_ma{ma}"] = ret_from_adj(avg, row["adj_close"])

    for col in ["turnover_rate", "volume_ratio"]:
        if col in row and pd.notna(row[col]):
            result[f"signal_{col}"] = float(row[col])


def simulate_exit(frame: pd.DataFrame, buy_idx: int, buy_adj_open: float, config: dict) -> dict:
    max_days = config["max_days"]
    take_profit = config["take_profit"]
    stop_loss = config["stop_loss"]
    end_idx = buy_idx + max_days
    if end_idx >= len(frame):
        return {"ret": None, "exit_reason": "insufficient_data", "exit_date": None, "days_held": None}

    # A-share T+1: if bought at open on buy_idx, first allowed sell day is buy_idx + 1.
    for idx in range(buy_idx + 1, end_idx + 1):
        row = frame.iloc[idx]
        high_ret = ret_from_adj(buy_adj_open, row["adj_high"])
        low_ret = ret_from_adj(buy_adj_open, row["adj_low"])
        if low_ret is not None and high_ret is not None and low_ret <= stop_loss and high_ret >= take_profit:
            return {
                "ret": stop_loss,
                "exit_reason": "both_hit_stop_first",
                "exit_date": row["trade_date"],
                "days_held": idx - buy_idx,
            }
        if low_ret is not None and low_ret <= stop_loss:
            return {"ret": stop_loss, "exit_reason": "stop_loss", "exit_date": row["trade_date"], "days_held": idx - buy_idx}
        if high_ret is not None and high_ret >= take_profit:
            return {
                "ret": take_profit,
                "exit_reason": "take_profit",
                "exit_date": row["trade_date"],
                "days_held": idx - buy_idx,
            }

    row = frame.iloc[end_idx]
    return {
        "ret": ret_from_adj(buy_adj_open, row["adj_close"]),
        "exit_reason": "time_exit",
        "exit_date": row["trade_date"],
        "days_held": end_idx - buy_idx,
    }


def analyze_event(event: pd.Series, market: MarketData | None) -> dict:
    result = event.to_dict()
    ts_code = event["ts_code"]
    entry_date = str(event["entry_date"])
    entry_price = float(event["entry_price"])

    result.update(
        {
            "has_market_data": market is not None,
            "signal_trade_date": None,
            "entry_close": None,
            "entry_vs_close_ret": None,
            "buy_date": None,
            "buy_open": None,
            "buy_gap_from_entry": None,
        }
    )

    if market is None:
        return result

    frame = market.frame
    signal_idx = market.by_date.get(entry_date)
    if signal_idx is None:
        signal_idx = first_index_at_or_after(frame, entry_date)
    if signal_idx is not None:
        signal_row = frame.iloc[signal_idx]
        result["signal_trade_date"] = signal_row["trade_date"]
        result["entry_close"] = round_num(signal_row["close"], 4)
        result["entry_vs_close_ret"] = round_num(entry_price / signal_row["close"] - 1) if signal_row["close"] else None
        add_pre_entry_features(result, frame, signal_idx, entry_price)

        base_adj_entry = entry_price * signal_row["adj_factor"]
        for horizon in HORIZONS:
            end_idx = signal_idx + horizon
            if end_idx < len(frame):
                end_row = frame.iloc[end_idx]
                result[f"signal_anchor_ret_{horizon}d"] = ret_from_adj(base_adj_entry, end_row["adj_close"])
                window = frame.iloc[signal_idx + 1 : end_idx + 1]
                if not window.empty:
                    result[f"signal_anchor_mfe_{horizon}d"] = ret_from_adj(base_adj_entry, window["adj_high"].max())
                    result[f"signal_anchor_mae_{horizon}d"] = ret_from_adj(base_adj_entry, window["adj_low"].min())

    buy_idx = first_index_after(frame, entry_date)
    if buy_idx is None:
        return result

    buy_row = frame.iloc[buy_idx]
    buy_adj_open = buy_row["adj_open"]
    result["buy_date"] = buy_row["trade_date"]
    result["buy_open"] = round_num(buy_row["open"], 4)
    result["buy_gap_from_entry"] = round_num(buy_row["open"] / entry_price - 1) if entry_price else None

    for horizon in HORIZONS:
        # T+1 aware: horizon=1 sells at next trading day's close after buy date.
        end_idx = buy_idx + horizon
        if end_idx < len(frame):
            end_row = frame.iloc[end_idx]
            result[f"next_open_ret_{horizon}d"] = ret_from_adj(buy_adj_open, end_row["adj_close"])
            window = frame.iloc[buy_idx + 1 : end_idx + 1]
            if not window.empty:
                result[f"next_open_mfe_{horizon}d"] = ret_from_adj(buy_adj_open, window["adj_high"].max())
                result[f"next_open_mae_{horizon}d"] = ret_from_adj(buy_adj_open, window["adj_low"].min())

    for config in EXIT_CONFIGS:
        exit_result = simulate_exit(frame, buy_idx, buy_adj_open, config)
        prefix = f"exit_{config['name']}"
        result[f"{prefix}_ret"] = exit_result["ret"]
        result[f"{prefix}_reason"] = exit_result["exit_reason"]
        result[f"{prefix}_date"] = exit_result["exit_date"]
        result[f"{prefix}_days_held"] = exit_result["days_held"]

    if "turnover_rate" in buy_row:
        for col in ["turnover_rate", "volume_ratio", "total_mv", "circ_mv"]:
            if col in buy_row:
                result[f"buy_{col}"] = round_num(buy_row[col])

    return result


def md_table(headers: list[str], rows: list[dict], row_fn) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row_fn(row)) + " |")
    return "\n".join(lines)


def stat_row(row: dict) -> list[str]:
    return [
        row.get("metric", row.get("key", "")),
        row["n"],
        pct(row["win_rate"]),
        pct(row["mean"]),
        pct(row["median"]),
        pct(row["p25"]),
        pct(row["p75"]),
        pct(row["min"]),
        pct(row["max"]),
    ]


def exit_reason_counts(df: pd.DataFrame, prefix: str) -> list[dict]:
    reason_col = f"{prefix}_reason"
    if reason_col not in df.columns:
        return []
    counts = df[reason_col].dropna().value_counts()
    total = int(counts.sum())
    return [
        {"reason": reason, "count": int(count), "pct": round_num(count / total) if total else None}
        for reason, count in counts.items()
    ]


def feature_bucket_summary(df: pd.DataFrame, feature: str, metric: str, q: int = 4) -> list[dict]:
    if feature not in df.columns or metric not in df.columns:
        return []
    sample = df[[feature, metric]].dropna()
    if len(sample) < 40 or sample[feature].nunique() < 4:
        return []
    try:
        sample = sample.assign(bucket=pd.qcut(sample[feature], q=q, duplicates="drop"))
    except ValueError:
        return []
    rows = []
    for bucket, group in sample.groupby("bucket", observed=True):
        stats = summarize(group[metric])
        rows.append(
            {
                "feature": feature,
                "bucket": str(bucket),
                "feature_min": round_num(group[feature].min()),
                "feature_max": round_num(group[feature].max()),
                **stats,
            }
        )
    return rows


def top_feature_buckets(df: pd.DataFrame, metric: str, min_n: int = 25) -> list[dict]:
    rows = []
    for feature in FEATURE_COLUMNS:
        rows.extend(feature_bucket_summary(df, feature, metric))
    rows = [row for row in rows if row["n"] >= min_n]
    return sorted(rows, key=lambda row: (row["median"] is not None, row["median"]), reverse=True)


def candidate_rule_summary(df: pd.DataFrame, metric: str) -> list[dict]:
    rules = [
        ("baseline_all", pd.Series(True, index=df.index), "全量PGC入池基准"),
        (
            "volume_ratio_1_62_2_54",
            df["signal_volume_ratio"].between(1.62, 2.54),
            "入池日量比处于中高区间，避免极端放量",
        ),
        (
            "volatility_3_64_4_71pct",
            df["pre_volatility_20"].between(0.0364, 0.0471),
            "20日波动率处于中高区间",
        ),
        ("price_ge_20", df["entry_price"].ge(20), "过滤低价股"),
        (
            "volume_and_price_ge_10",
            df["signal_volume_ratio"].between(1.62, 2.54) & df["entry_price"].ge(10),
            "中高量比 + 非低价",
        ),
        (
            "volatility_and_price_ge_10",
            df["pre_volatility_20"].between(0.0364, 0.0471) & df["entry_price"].ge(10),
            "中高波动 + 非低价",
        ),
        (
            "volume_and_price_20_100",
            df["signal_volume_ratio"].between(1.62, 2.54) & df["entry_price"].between(20, 100),
            "中高量比 + 20到100元价格带",
        ),
        (
            "volume_volatility_price_ge_10",
            df["signal_volume_ratio"].between(1.62, 2.54)
            & df["pre_volatility_20"].between(0.0364, 0.0471)
            & df["entry_price"].ge(10),
            "中高量比 + 中高波动 + 非低价",
        ),
    ]
    rows = []
    for name, condition, note in rules:
        stats = summarize(df.loc[condition, metric].dropna())
        rows.append({"rule": name, "note": note, **stats})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze PGC raw entry events with cached Tushare data.")
    parser.add_argument("--events", default=str(RAW_EVENTS_PATH), help="Path to pgc_raw_events.json.")
    parser.add_argument("--market-dir", default=str(MARKET_DIR), help="Cached Tushare data directory.")
    parser.add_argument("--out-csv", default=str(DATA_OUT), help="Per-event output CSV.")
    parser.add_argument("--out-json", default=str(JSON_OUT), help="Summary JSON output.")
    parser.add_argument("--out-md", default=str(MD_OUT), help="Markdown report output.")
    args = parser.parse_args()

    events = load_events(Path(args.events))
    market_dir = Path(args.market_dir)
    markets = {ts_code: load_market(ts_code, market_dir) for ts_code in sorted(events["ts_code"].dropna().unique())}

    event_rows = [analyze_event(event, markets.get(event["ts_code"])) for _, event in events.iterrows()]
    event_df = pd.DataFrame(event_rows)

    ret_cols = [f"next_open_ret_{horizon}d" for horizon in HORIZONS]
    signal_cols = [f"signal_anchor_ret_{horizon}d" for horizon in HORIZONS]
    mfe_cols = [f"next_open_mfe_{horizon}d" for horizon in HORIZONS]
    mae_cols = [f"next_open_mae_{horizon}d" for horizon in HORIZONS]
    exit_cols = [f"exit_{config['name']}_ret" for config in EXIT_CONFIGS]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "events": len(event_df),
        "market_data_events": int(event_df["has_market_data"].sum()),
        "no_market_data_events": int((~event_df["has_market_data"]).sum()),
        "entry_price_match": {
            "available": int(event_df["entry_vs_close_ret"].notna().sum()),
            "within_0_5pct": int((event_df["entry_vs_close_ret"].abs() <= 0.005).sum()),
            "inside_entry_day_range": int(event_df["entry_price_in_day_range"].fillna(False).sum())
            if "entry_price_in_day_range" in event_df.columns
            else 0,
            "summary": summarize(event_df["entry_vs_close_ret"].dropna()),
        },
        "buy_gap_from_entry": summarize(event_df["buy_gap_from_entry"].dropna()),
        "next_open_returns": summarize_table(event_df, ret_cols),
        "signal_anchor_returns": summarize_table(event_df, signal_cols),
        "next_open_mfe": summarize_table(event_df, mfe_cols),
        "next_open_mae": summarize_table(event_df, mae_cols),
        "exit_rules": summarize_table(event_df, exit_cols),
        "groups": {
            "price_bucket_ret_5d": group_summary(event_df, "price_bucket", "next_open_ret_5d"),
            "price_bucket_ret_10d": group_summary(event_df, "price_bucket", "next_open_ret_10d"),
            "entry_month_ret_10d": group_summary(event_df, "entry_month", "next_open_ret_10d"),
            "entry_weekday_ret_10d": group_summary(event_df, "entry_weekday", "next_open_ret_10d"),
        },
        "exit_reason_counts": {
            config["name"]: exit_reason_counts(event_df, f"exit_{config['name']}") for config in EXIT_CONFIGS
        },
        "feature_buckets": {
            "next_open_ret_5d": top_feature_buckets(event_df, "next_open_ret_5d"),
            "next_open_ret_10d": top_feature_buckets(event_df, "next_open_ret_10d"),
        },
        "candidate_rules": {
            "next_open_ret_10d": candidate_rule_summary(event_df, "next_open_ret_10d"),
            "next_open_ret_5d": candidate_rule_summary(event_df, "next_open_ret_5d"),
        },
    }

    Path(args.out_csv).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    event_df.to_csv(args.out_csv, index=False)
    Path(args.out_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    next_open_rows = summary["next_open_returns"]
    signal_rows = summary["signal_anchor_returns"]
    exit_rows = summary["exit_rules"]

    report = f"""# PGC入池事件回测研究

> 口径：只使用 `pgc_raw_events.json` 中的入池事件作为信号，Tushare 行情只用于计算入池后的收益、波动和交易可行性。没有使用 `bull_prob/bull_reason/status`。

## 数据覆盖

- 入池事件数：{summary["events"]}
- 有行情缓存的事件数：{summary["market_data_events"]}
- 无行情缓存的事件数：{summary["no_market_data_events"]}
- 入池价可与 Tushare 入池日收盘价对比的事件数：{summary["entry_price_match"]["available"]}
- 入池价与收盘价误差在 0.5% 内：{summary["entry_price_match"]["within_0_5pct"]}
- 入池价落在入池日日内高低价区间内：{summary["entry_price_match"]["inside_entry_day_range"]}
- 次日开盘相对入池价的中位跳空：{pct(summary["buy_gap_from_entry"]["median"])}

## 可交易口径：次一交易日开盘买入，T+1 后按持有期收盘卖出

这里的 `1d` 表示次日开盘买入后，至少遵守 T+1，下一交易日收盘卖出。

{md_table(["持有期", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], next_open_rows, stat_row)}

## 信号质量口径：以入池价为锚点的未来收益

这不是严格可交易口径，主要用于判断 PGC 入池价本身是否有统计预测力。

{md_table(["周期", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], signal_rows, stat_row)}

## MFE / MAE

MFE 是买入后最大有利波动，MAE 是最大不利波动。它们用于设计止盈止损，不代表一定可成交。

### MFE

{md_table(["周期", "N", "胜率", "均值", "中位", "P25", "P75", "最小", "最大"], summary["next_open_mfe"], stat_row)}

### MAE

{md_table(["周期", "N", "胜率", "均值", "中位", "P25", "P75", "最小", "最大"], summary["next_open_mae"], stat_row)}

## 止盈止损模拟

日线无法判断同日先后触发；若同一天同时触发止盈和止损，本报告按保守的先止损处理。卖出最早从买入后的下一交易日开始，遵守 T+1。

{md_table(["规则", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], exit_rows, stat_row)}

## 价格带分组

### 5日

{md_table(["价格带", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], summary["groups"]["price_bucket_ret_5d"], stat_row)}

### 10日

{md_table(["价格带", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], summary["groups"]["price_bucket_ret_10d"], stat_row)}

## 时间分组

### 月份，10日持有

{md_table(["月份", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], summary["groups"]["entry_month_ret_10d"], stat_row)}

### 星期，10日持有

{md_table(["星期", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], summary["groups"]["entry_weekday_ret_10d"], stat_row)}

## 入池前特征分层，探索性

这些特征只使用入池日收盘及之前的 Tushare 行情计算，没有用入池后的收益。下面列出 10 日可交易收益中位数靠前的分层，只能作为下一步建模线索，不能直接当最终策略。

{md_table(
        ["特征", "分层", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"],
        summary["feature_buckets"]["next_open_ret_10d"][:12],
        lambda row: [
            row["feature"],
            row["bucket"],
            row["n"],
            pct(row["win_rate"]),
            pct(row["mean"]),
            pct(row["median"]),
            pct(row["p25"]),
            pct(row["p75"]),
            pct(row["min"]),
            pct(row["max"]),
        ],
    )}

## 候选规则，探索性

这些规则只用原始入池价格和入池日前可见行情。阈值来自当前样本的分层观察，仍有样本内选参风险；真正可用前必须走前验证。

{md_table(
        ["规则", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好", "说明"],
        summary["candidate_rules"]["next_open_ret_10d"],
        lambda row: [
            row["rule"],
            row["n"],
            pct(row["win_rate"]),
            pct(row["mean"]),
            pct(row["median"]),
            pct(row["p25"]),
            pct(row["p75"]),
            pct(row["min"]),
            pct(row["max"]),
            row["note"],
        ],
    )}

## 初步解读

- 先看 `可交易口径`，不要被入池价锚点收益迷惑。
- 如果短周期中位数为正且 MAE 可控，PGC 入池事件本身才有继续开发价值。
- 如果 MFE 明显高于持有期收益，说明需要研究止盈/移动止盈，而不是固定持有。
- 分组结果只用于发现方向，不能直接选参；后续要用新增样本做走前验证。
"""

    Path(args.out_md).write_text(report, encoding="utf-8")
    print(json.dumps({"out_csv": args.out_csv, "out_json": args.out_json, "out_md": args.out_md}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
