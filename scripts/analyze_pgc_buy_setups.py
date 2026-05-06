#!/usr/bin/env python3
"""Study short-term buy setups after PGC pool entry.

PGC entry is treated as watchlist inclusion, not a buy signal. This script
looks for auditable post-entry buy setups using only data available by the
trigger day's close, then evaluates buying at the next trading day's open.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from analyze_pgc_event_backtest import (
    EXIT_CONFIGS,
    HORIZONS,
    MARKET_DIR,
    RAW_EVENTS_PATH,
    load_events,
    load_market,
    pct,
    ret_from_adj,
    round_num,
    simulate_exit,
    summarize,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports"
SIGNALS_CSV = ROOT / "data" / "pgc_buy_setups.csv"
CURRENT_CSV = ROOT / "data" / "pgc_current_watchlist.csv"
JSON_OUT = OUT_DIR / "pgc_buy_setups.json"
MD_OUT = OUT_DIR / "pgc_buy_setups.md"


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
        row.get("setup", row.get("metric", "")),
        row["n"],
        pct(row["win_rate"]),
        pct(row["mean"]),
        pct(row["median"]),
        pct(row["p25"]),
        pct(row["p75"]),
        pct(row["min"]),
        pct(row["max"]),
    ]


def first_index_after(frame: pd.DataFrame, date: str) -> int | None:
    matches = frame.index[frame["trade_date"] > str(date)].tolist()
    return int(matches[0]) if matches else None


def prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy().sort_values("trade_date").reset_index(drop=True)
    for ma in [3, 5, 10, 20]:
        df[f"amount_ma{ma}"] = df["amount"].rolling(ma, min_periods=max(2, ma // 2)).mean()
        df[f"adj_close_ma{ma}"] = df["adj_close"].rolling(ma, min_periods=max(2, ma // 2)).mean()
    df["high_6_prev"] = df["adj_high"].shift(1).rolling(6, min_periods=4).max()
    df["low_6_prev"] = df["adj_low"].shift(1).rolling(6, min_periods=4).min()
    df["amount_6_prev"] = df["amount"].shift(1).rolling(6, min_periods=4).mean()
    df["amount_20_prev"] = df["amount"].shift(1).rolling(20, min_periods=10).mean()
    df["high_10_prev"] = df["adj_high"].shift(1).rolling(10, min_periods=6).max()
    df["high_20_prev"] = df["adj_high"].shift(1).rolling(20, min_periods=10).max()
    df["range_6_prev"] = df["high_6_prev"] / df["low_6_prev"] - 1
    return df


def row_value(row: pd.Series, key: str, default=None):
    value = row.get(key, default)
    return default if pd.isna(value) else value


def setup_pullback_stabilization(df: pd.DataFrame, signal_idx: int, idx: int) -> tuple[bool, dict]:
    if idx < signal_idx + 3:
        return False, {}
    row = df.iloc[idx]
    prev = df.iloc[idx - 1]
    recent = df.iloc[max(signal_idx, idx - 3) : idx + 1]
    since_entry = df.iloc[signal_idx : idx + 1]
    peak = since_entry["adj_high"].max()
    entry_close = df.iloc[signal_idx]["adj_close"]
    peak_ret = ret_from_adj(entry_close, peak)
    drawdown = ret_from_adj(peak, row["adj_close"])
    amount_ma3 = recent["amount"].mean()
    amount_ma10 = row_value(row, "amount_ma10")
    amount_shrink = bool(amount_ma10 and amount_ma3 <= amount_ma10 * 0.82)
    low_stable = row["adj_low"] >= recent.iloc[:-1]["adj_low"].min() * 0.985 if len(recent) > 1 else False
    close_stable = row["adj_close"] >= prev["adj_close"] * 0.995
    near_ma10 = bool(row_value(row, "adj_close_ma10") and row["adj_close"] >= row["adj_close_ma10"] * 0.96)
    passed = (
        peak_ret is not None
        and peak_ret >= 0.03
        and drawdown is not None
        and -0.16 <= drawdown <= -0.035
        and amount_shrink
        and low_stable
        and close_stable
        and near_ma10
        and row["pct_chg"] > -3.0
    )
    return passed, {
        "post_entry_peak_ret": peak_ret,
        "setup_drawdown_from_peak": drawdown,
        "setup_amount_ma3_to_ma10": amount_ma3 / amount_ma10 if amount_ma10 else None,
        "setup_pct_chg": row["pct_chg"] / 100 if pd.notna(row["pct_chg"]) else None,
    }


def setup_contracting_pullback_bullish(df: pd.DataFrame, signal_idx: int, idx: int) -> tuple[bool, dict]:
    if idx < signal_idx + 3:
        return False, {}
    row = df.iloc[idx]
    prev = df.iloc[idx - 1]
    entry = df.iloc[signal_idx]
    amount_ma10 = row_value(row, "amount_ma10")
    if not amount_ma10:
        return False, {}

    best_features = None
    for lookback in range(2, 7):
        start = idx - lookback
        if start <= signal_idx:
            continue
        pullback = df.iloc[start:idx]
        if len(pullback) < 2:
            continue

        first_amount = pullback.iloc[0]["amount"]
        last_amount = pullback.iloc[-1]["amount"]
        first_close = pullback.iloc[0]["adj_close"]
        last_close = pullback.iloc[-1]["adj_close"]
        if not first_amount or not first_close:
            continue

        amount_ratio = last_amount / first_amount
        avg_amount_ratio = pullback["amount"].mean() / amount_ma10
        close_pullback = last_close / first_close - 1
        down_days = int((pullback["adj_close"].diff().dropna() <= 0).sum())
        peak_before = df.iloc[signal_idx:idx]["adj_high"].max()
        drawdown_from_peak = ret_from_adj(peak_before, last_close)

        volume_contracting = amount_ratio <= 0.95 and avg_amount_ratio <= 0.95
        price_pullback = (
            close_pullback <= -0.015
            and drawdown_from_peak is not None
            and -0.14 <= drawdown_from_peak <= -0.025
            and down_days >= max(1, lookback - 2)
        )
        if not (volume_contracting and price_pullback):
            continue

        bullish_body = row["adj_close"] >= row["adj_open"] * 1.012
        close_recovers = row["adj_close"] >= prev["adj_close"]
        low_holds = row["adj_low"] >= pullback["adj_low"].min() * 0.992
        moderate_volume = row["amount"] >= last_amount * 0.90 and row["amount"] <= amount_ma10 * 1.30
        not_extended = ret_from_adj(entry["adj_close"], row["adj_close"])
        if (
            bullish_body
            and close_recovers
            and low_holds
            and moderate_volume
            and row["pct_chg"] >= 0.0
            and not_extended is not None
            and not_extended <= 0.18
        ):
            best_features = {
                "setup_pullback_days": lookback,
                "setup_amount_contract_ratio": amount_ratio,
                "setup_pullback_avg_amount_to_ma10": avg_amount_ratio,
                "setup_pullback_close_ret": close_pullback,
                "setup_drawdown_from_peak": drawdown_from_peak,
                "setup_bull_body": row["adj_close"] / row["adj_open"] - 1,
                "setup_amount_to_last_pullback": row["amount"] / last_amount if last_amount else None,
                "setup_pct_chg": row["pct_chg"] / 100 if pd.notna(row["pct_chg"]) else None,
            }
            break

    return (best_features is not None), (best_features or {})


def setup_sideways_breakout(df: pd.DataFrame, signal_idx: int, idx: int) -> tuple[bool, dict]:
    if idx < signal_idx + 6:
        return False, {}
    row = df.iloc[idx]
    high_6_prev = row_value(row, "high_6_prev")
    range_6_prev = row_value(row, "range_6_prev")
    amount_6_prev = row_value(row, "amount_6_prev")
    amount_20_prev = row_value(row, "amount_20_prev")
    if not high_6_prev or not amount_6_prev:
        return False, {}
    compressed_volume = amount_20_prev is None or amount_6_prev <= amount_20_prev * 1.05
    breakout = row["adj_close"] >= high_6_prev * 0.995
    volume_reexpand = row["amount"] >= amount_6_prev * 1.20
    above_ma5 = bool(row_value(row, "adj_close_ma5") and row["adj_close"] >= row["adj_close_ma5"])
    passed = (
        range_6_prev is not None
        and range_6_prev <= 0.12
        and compressed_volume
        and breakout
        and volume_reexpand
        and above_ma5
        and row["pct_chg"] >= 1.0
    )
    return passed, {
        "setup_range_6": range_6_prev,
        "setup_amount_to_prev6": row["amount"] / amount_6_prev if amount_6_prev else None,
        "setup_pct_chg": row["pct_chg"] / 100 if pd.notna(row["pct_chg"]) else None,
    }


def setup_old_volume_reactivation(df: pd.DataFrame, signal_idx: int, idx: int) -> tuple[bool, dict]:
    if idx < signal_idx + 21:
        return False, {}
    row = df.iloc[idx]
    amount_20_prev = row_value(row, "amount_20_prev")
    high_20_prev = row_value(row, "high_20_prev")
    high_10_prev = row_value(row, "high_10_prev")
    if not amount_20_prev or not high_10_prev:
        return False, {}
    volume_ratio = row_value(row, "volume_ratio")
    amount_surge = row["amount"] >= amount_20_prev * 1.80
    price_reactivate = row["adj_close"] >= high_10_prev * 0.99 or (
        high_20_prev and row["adj_close"] >= high_20_prev * 0.97
    )
    above_ma20 = bool(row_value(row, "adj_close_ma20") and row["adj_close"] >= row["adj_close_ma20"])
    passed = (
        amount_surge
        and price_reactivate
        and above_ma20
        and row["pct_chg"] >= 2.0
        and (volume_ratio is None or volume_ratio >= 1.4)
    )
    return passed, {
        "setup_amount_to_20": row["amount"] / amount_20_prev if amount_20_prev else None,
        "setup_volume_ratio": volume_ratio,
        "setup_breakout_10": ret_from_adj(high_10_prev, row["adj_close"]),
        "setup_pct_chg": row["pct_chg"] / 100 if pd.notna(row["pct_chg"]) else None,
    }


SETUPS = [
    (
        "contracting_pullback_bullish",
        setup_contracting_pullback_bullish,
        20,
        "入池后20个交易日内，缩量回调后出现第一根确认阳线",
    ),
    ("pullback_stabilization", setup_pullback_stabilization, 20, "入池后20个交易日内，冲高后缩量回调并企稳"),
    ("sideways_breakout", setup_sideways_breakout, 20, "入池后20个交易日内，窄幅横盘后放量上沿突破"),
    ("old_volume_reactivation", setup_old_volume_reactivation, None, "入池20个交易日以后，突然放量并重新接近突破"),
]


def evaluate_signal(df: pd.DataFrame, event: pd.Series, setup: str, idx: int, features: dict) -> dict:
    trigger = df.iloc[idx]
    buy_idx = idx + 1
    row = {
        "event_id": event["event_id"],
        "ts_code": event["ts_code"],
        "code": event["code"],
        "name": event["name"],
        "entry_date": event["entry_date"],
        "entry_price": event["entry_price"],
        "entry_month": event["entry_month"],
        "price_bucket": event["price_bucket"],
        "setup": setup,
        "trigger_date": trigger["trade_date"],
        "trigger_age_trading_days": idx - int(event["signal_idx"]),
        "trigger_close": round_num(trigger["close"]),
        "trigger_pct_chg": round_num(trigger["pct_chg"] / 100) if pd.notna(trigger["pct_chg"]) else None,
        "trigger_amount": round_num(trigger["amount"]),
        "trigger_volume_ratio": round_num(row_value(trigger, "volume_ratio")),
        **{key: round_num(value) for key, value in features.items()},
    }
    if buy_idx >= len(df):
        row["buy_date"] = None
        row["buy_open"] = None
        return row

    buy = df.iloc[buy_idx]
    buy_adj_open = buy["adj_open"]
    row["buy_date"] = buy["trade_date"]
    row["buy_open"] = round_num(buy["open"])
    row["buy_gap_from_trigger_close"] = ret_from_adj(trigger["adj_close"], buy_adj_open)

    for horizon in HORIZONS:
        end_idx = buy_idx + horizon
        if end_idx < len(df):
            end = df.iloc[end_idx]
            row[f"ret_{horizon}d"] = ret_from_adj(buy_adj_open, end["adj_close"])
            window = df.iloc[buy_idx + 1 : end_idx + 1]
            if not window.empty:
                row[f"mfe_{horizon}d"] = ret_from_adj(buy_adj_open, window["adj_high"].max())
                row[f"mae_{horizon}d"] = ret_from_adj(buy_adj_open, window["adj_low"].min())

    for config in EXIT_CONFIGS:
        exit_result = simulate_exit(df, buy_idx, buy_adj_open, config)
        prefix = f"exit_{config['name']}"
        row[f"{prefix}_ret"] = exit_result["ret"]
        row[f"{prefix}_reason"] = exit_result["exit_reason"]
        row[f"{prefix}_date"] = exit_result["exit_date"]
        row[f"{prefix}_days_held"] = exit_result["days_held"]

    return row


def scan_event(event: pd.Series, market) -> list[dict]:
    if market is None:
        return []
    df = prepare_frame(market.frame)
    signal_idx = market.by_date.get(str(event["entry_date"]))
    if signal_idx is None:
        return []
    event = event.copy()
    event["signal_idx"] = signal_idx
    signals = []
    for setup_name, detector, max_age, _desc in SETUPS:
        end_idx = len(df) - 2
        if max_age is not None:
            end_idx = min(end_idx, signal_idx + max_age)
        found = False
        for idx in range(signal_idx + 1, end_idx + 1):
            passed, features = detector(df, signal_idx, idx)
            if passed:
                signals.append(evaluate_signal(df, event, setup_name, idx, features))
                found = True
                break
        if found:
            continue
    return signals


def latest_watchlist_row(event: pd.Series, market) -> dict | None:
    if market is None:
        return None
    df = prepare_frame(market.frame)
    signal_idx = market.by_date.get(str(event["entry_date"]))
    if signal_idx is None or len(df) == 0:
        return None
    latest_idx = len(df) - 1
    latest = df.iloc[latest_idx]
    age = latest_idx - signal_idx
    row = {
        "event_id": event["event_id"],
        "ts_code": event["ts_code"],
        "name": event["name"],
        "entry_date": event["entry_date"],
        "entry_price": event["entry_price"],
        "latest_trade_date": latest["trade_date"],
        "age_trading_days": age,
        "latest_close": round_num(latest["close"]),
        "latest_pct_chg": round_num(latest["pct_chg"] / 100) if pd.notna(latest["pct_chg"]) else None,
        "latest_volume_ratio": round_num(row_value(latest, "volume_ratio")),
        "latest_amount_to_20": round_num(latest["amount"] / latest["amount_20_prev"]) if row_value(latest, "amount_20_prev") else None,
        "watch_type": None,
    }
    if 0 <= age <= 20:
        row["watch_type"] = "fresh_within_20d"
        return row
    for lookback_idx in range(max(signal_idx + 21, latest_idx - 2), latest_idx + 1):
        passed, _features = setup_old_volume_reactivation(df, signal_idx, lookback_idx)
        if passed:
            row["watch_type"] = "old_recent_volume_reactivation"
            row["reactivation_date"] = df.iloc[lookback_idx]["trade_date"]
            return row
    return None


def setup_summary(signals: pd.DataFrame, metric: str) -> list[dict]:
    rows = []
    for setup, group in signals.groupby("setup", dropna=False):
        rows.append({"setup": setup, **summarize(group[metric].dropna())})
    return sorted(rows, key=lambda row: (row["median"] is not None, row["median"]), reverse=True)


def exit_summary(signals: pd.DataFrame) -> list[dict]:
    rows = []
    for config in EXIT_CONFIGS:
        col = f"exit_{config['name']}_ret"
        for setup, group in signals.groupby("setup", dropna=False):
            rows.append({"setup": f"{setup}:{config['name']}", **summarize(group[col].dropna())})
    return sorted(rows, key=lambda row: (row["setup"]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze short-term buy setups after PGC entry.")
    parser.add_argument("--events", default=str(RAW_EVENTS_PATH), help="Path to pgc_raw_events.json.")
    parser.add_argument("--market-dir", default=str(MARKET_DIR), help="Cached Tushare market data directory.")
    parser.add_argument("--signals-csv", default=str(SIGNALS_CSV), help="Output signal detail CSV.")
    parser.add_argument("--current-csv", default=str(CURRENT_CSV), help="Output current watchlist CSV.")
    parser.add_argument("--out-json", default=str(JSON_OUT), help="Output JSON summary.")
    parser.add_argument("--out-md", default=str(MD_OUT), help="Output Markdown report.")
    args = parser.parse_args()

    events = load_events(Path(args.events))
    market_dir = Path(args.market_dir)
    markets = {ts_code: load_market(ts_code, market_dir) for ts_code in sorted(events["ts_code"].dropna().unique())}

    signal_rows: list[dict] = []
    current_rows: list[dict] = []
    for _, event in events.iterrows():
        market = markets.get(event["ts_code"])
        signal_rows.extend(scan_event(event, market))
        watch_row = latest_watchlist_row(event, market)
        if watch_row is not None:
            current_rows.append(watch_row)

    signals = pd.DataFrame(signal_rows)
    current = pd.DataFrame(current_rows)
    Path(args.signals_csv).parent.mkdir(parents=True, exist_ok=True)
    signals.to_csv(args.signals_csv, index=False)
    current.to_csv(args.current_csv, index=False)

    ret_cols = [f"ret_{horizon}d" for horizon in HORIZONS]
    mfe_cols = [f"mfe_{horizon}d" for horizon in HORIZONS]
    mae_cols = [f"mae_{horizon}d" for horizon in HORIZONS]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "events": len(events),
        "signals": len(signals),
        "signals_by_setup": signals["setup"].value_counts().to_dict() if not signals.empty else {},
        "current_watchlist": len(current),
        "current_watchlist_by_type": current["watch_type"].value_counts().to_dict() if not current.empty else {},
        "ret_by_setup": {col: setup_summary(signals, col) for col in ret_cols if col in signals},
        "mfe_by_setup": {col: setup_summary(signals, col) for col in mfe_cols if col in signals},
        "mae_by_setup": {col: setup_summary(signals, col) for col in mae_cols if col in signals},
        "exit_by_setup": exit_summary(signals) if not signals.empty else [],
        "setup_definitions": [
            {"setup": name, "description": desc, "max_age": max_age} for name, _detector, max_age, desc in SETUPS
        ],
    }

    Path(args.out_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = f"""# PGC入池后短线买点研究

> 口径：PGC 入池只是观察池事件，不直接买入。买点触发只使用触发日收盘前可见的日线、成交额、量比和复权价格；实际买入统一按下一交易日开盘，卖出遵守 T+1。

## 买点定义，第一版

- `pullback_stabilization`：入池后20个交易日内，先冲高至少3%，再从高点回撤3.5%-16%，缩量并企稳。
- `contracting_pullback_bullish`：入池后20个交易日内，先出现2-6天缩量回调，再出现一根收阳、收盘高于前一日且不破回调低点的确认阳线。
- `sideways_breakout`：入池后20个交易日内，6日窄幅横盘，量能不扩张，当日放量并接近上沿突破。
- `old_volume_reactivation`：入池超过20个交易日后，成交额相对20日均值明显放大，价格重新接近10/20日高点。

## 信号覆盖

- 原始入池事件：{summary["events"]}
- 检测到的买点信号：{summary["signals"]}
- 当前观察列表：{summary["current_watchlist"]}
- 当前观察列表类型：{json.dumps(summary["current_watchlist_by_type"], ensure_ascii=False)}

## 买点后固定持有收益

### 3日

{md_table(["买点", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], summary["ret_by_setup"].get("ret_3d", []), stat_row)}

### 5日

{md_table(["买点", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], summary["ret_by_setup"].get("ret_5d", []), stat_row)}

### 10日

{md_table(["买点", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], summary["ret_by_setup"].get("ret_10d", []), stat_row)}

## 买点后 MFE

MFE 用来判断短线冲高空间。

### 5日 MFE

{md_table(["买点", "N", "胜率", "均值", "中位", "P25", "P75", "最小", "最大"], summary["mfe_by_setup"].get("mfe_5d", []), stat_row)}

### 10日 MFE

{md_table(["买点", "N", "胜率", "均值", "中位", "P25", "P75", "最小", "最大"], summary["mfe_by_setup"].get("mfe_10d", []), stat_row)}

## 买点后 MAE

MAE 用来判断止损空间。

### 5日 MAE

{md_table(["买点", "N", "胜率", "均值", "中位", "P25", "P75", "最小", "最大"], summary["mae_by_setup"].get("mae_5d", []), stat_row)}

### 10日 MAE

{md_table(["买点", "N", "胜率", "均值", "中位", "P25", "P75", "最小", "最大"], summary["mae_by_setup"].get("mae_10d", []), stat_row)}

## 止盈止损模拟

同一天同时触发止盈和止损时按先止损处理，属于日线级别的保守假设。

{md_table(["买点:规则", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], summary["exit_by_setup"], stat_row)}

## 当前可观察标的

详见 `{args.current_csv}`。`fresh_within_20d` 是仍在入池后20个交易日内的观察对象，`old_recent_volume_reactivation` 是老入池但近3个交易日出现再放量迹象的对象。

## 初步解读

- 这份报告回答“入池后买点”而不是“入池当天买不买”。
- 若某类买点固定持有收益不高但 MFE 明显为正，应优先研究分批止盈和移动止盈。
- 当前规则是第一版结构化假设，下一步要调阈值、加入市场环境过滤，并用新增样本走前验证。
"""

    Path(args.out_md).write_text(report, encoding="utf-8")
    print(json.dumps({"signals": len(signals), "current": len(current), "out_md": args.out_md}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
