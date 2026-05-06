#!/usr/bin/env python3
"""Parameter deep dive for the contracting-pullback bullish candle setup."""

from __future__ import annotations

import argparse
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from analyze_pgc_buy_setups import prepare_frame, row_value
from analyze_pgc_event_backtest import HORIZONS, MARKET_DIR, RAW_EVENTS_PATH, load_events, load_market, pct, ret_from_adj, round_num, summarize


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports"
SUMMARY_CSV = ROOT / "data" / "contracting_pullback_variants.csv"
BEST_SIGNALS_CSV = ROOT / "data" / "contracting_pullback_best_signals.csv"
CURRENT_CSV = ROOT / "data" / "contracting_pullback_current_candidates.csv"
JSON_OUT = OUT_DIR / "contracting_pullback_deep_dive.json"
MD_OUT = OUT_DIR / "contracting_pullback_deep_dive.md"


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
        row.get("name", row.get("variant_id", row.get("metric", ""))),
        row["n"],
        pct(row["win_rate"]),
        pct(row["mean"]),
        pct(row["median"]),
        pct(row["p25"]),
        pct(row["p75"]),
        pct(row["min"]),
        pct(row["max"]),
    ]


def safe(value, default=None):
    return default if value is None or pd.isna(value) else value


def cap(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def build_param_grid() -> list[dict]:
    grid = []
    contract_max_values = [0.70, 0.82, 0.95]
    avg_amount_max_values = [0.85, 0.95, 1.05]
    drawdown_ranges = [(0.025, 0.14), (0.025, 0.18), (0.04, 0.16), (0.05, 0.20)]
    bull_body_min_values = [0.0, 0.006, 0.012, 0.02]
    close_recover_min_values = [0.0, 0.006, 0.012]
    pct_chg_min_values = [0.0, 0.008, 0.015]
    trigger_amount_max_values = [1.30, 1.60, 2.00]
    max_entry_runup_values = [0.18, 0.25]

    for idx, values in enumerate(
        itertools.product(
            contract_max_values,
            avg_amount_max_values,
            drawdown_ranges,
            bull_body_min_values,
            close_recover_min_values,
            pct_chg_min_values,
            trigger_amount_max_values,
            max_entry_runup_values,
        ),
        start=1,
    ):
        contract_max, avg_amount_max, dd_range, body_min, close_recover_min, pct_chg_min, trigger_amount_max, max_runup = values
        min_dd, max_dd = dd_range
        grid.append(
            {
                "variant_id": f"cpb_{idx:04d}",
                "contract_max": contract_max,
                "avg_amount_max": avg_amount_max,
                "min_drawdown": min_dd,
                "max_drawdown": max_dd,
                "bull_body_min": body_min,
                "close_recover_min": close_recover_min,
                "pct_chg_min": pct_chg_min,
                "trigger_amount_max": trigger_amount_max,
                "max_entry_runup": max_runup,
            }
        )
    return grid


def detect_param_signal(df: pd.DataFrame, signal_idx: int, idx: int, params: dict) -> tuple[bool, dict]:
    if idx < signal_idx + 3:
        return False, {}
    row = df.iloc[idx]
    prev = df.iloc[idx - 1]
    entry = df.iloc[signal_idx]
    amount_ma10 = row_value(row, "amount_ma10")
    if not amount_ma10:
        return False, {}

    for lookback in range(2, 7):
        start = idx - lookback
        if start <= signal_idx:
            continue
        pullback = df.iloc[start:idx]
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
        if drawdown_from_peak is None:
            continue

        drawdown_abs = abs(drawdown_from_peak)
        bullish_body = row["adj_close"] / row["adj_open"] - 1 if row["adj_open"] else None
        close_recover = row["adj_close"] / prev["adj_close"] - 1 if prev["adj_close"] else None
        entry_runup = ret_from_adj(entry["adj_close"], row["adj_close"])

        if (
            amount_ratio <= params["contract_max"]
            and avg_amount_ratio <= params["avg_amount_max"]
            and close_pullback <= -0.015
            and params["min_drawdown"] <= drawdown_abs <= params["max_drawdown"]
            and down_days >= max(1, lookback - 2)
            and bullish_body is not None
            and bullish_body >= params["bull_body_min"]
            and close_recover is not None
            and close_recover >= params["close_recover_min"]
            and row["adj_low"] >= pullback["adj_low"].min() * 0.992
            and row["amount"] >= last_amount * 0.90
            and row["amount"] <= amount_ma10 * params["trigger_amount_max"]
            and row["pct_chg"] / 100 >= params["pct_chg_min"]
            and entry_runup is not None
            and entry_runup <= params["max_entry_runup"]
        ):
            return True, {
                "pullback_days": lookback,
                "amount_contract_ratio": amount_ratio,
                "avg_amount_to_ma10": avg_amount_ratio,
                "pullback_close_ret": close_pullback,
                "drawdown_from_peak": drawdown_from_peak,
                "bull_body": bullish_body,
                "close_recover": close_recover,
                "trigger_pct_chg": row["pct_chg"] / 100,
                "trigger_amount_to_ma10": row["amount"] / amount_ma10,
                "entry_runup": entry_runup,
            }
    return False, {}


def setup_score(event: pd.Series, features: dict) -> float:
    price = float(event["entry_price"])
    score = 100.0
    if price < 10:
        score -= 10
    elif 20 <= price <= 100:
        score += 8
    else:
        score += 3
    score += cap((0.82 - safe(features.get("amount_contract_ratio"), 0.82)) * 35, -4, 12)
    score += cap(10 - abs(abs(safe(features.get("drawdown_from_peak"), -0.08)) - 0.08) * 120, -5, 10)
    score += cap(safe(features.get("bull_body"), 0) * 180, 0, 12)
    score += cap(safe(features.get("trigger_pct_chg"), 0) * 80, 0, 8)
    return round(score, 4)


def eval_trade(df: pd.DataFrame, event: pd.Series, idx: int, features: dict, params: dict) -> dict | None:
    buy_idx = idx + 1
    if buy_idx >= len(df):
        return None
    trigger = df.iloc[idx]
    buy = df.iloc[buy_idx]
    base = buy["adj_open"]
    row = {
        "variant_id": params["variant_id"],
        "event_id": int(event["event_id"]),
        "ts_code": event["ts_code"],
        "name": event["name"],
        "entry_date": event["entry_date"],
        "entry_price": float(event["entry_price"]),
        "review_date": trigger["trade_date"],
        "buy_date": buy["trade_date"],
        "buy_open": round_num(buy["open"]),
        "trigger_age_trading_days": idx - int(event["signal_idx"]),
        "score": setup_score(event, features),
        **{k: round_num(v) for k, v in features.items()},
    }
    for horizon in HORIZONS:
        end_idx = buy_idx + horizon
        if end_idx < len(df):
            end = df.iloc[end_idx]
            row[f"ret_{horizon}d"] = ret_from_adj(base, end["adj_close"])
            window = df.iloc[buy_idx + 1 : end_idx + 1]
            if not window.empty:
                row[f"mfe_{horizon}d"] = ret_from_adj(base, window["adj_high"].max())
                row[f"mae_{horizon}d"] = ret_from_adj(base, window["adj_low"].min())

    t2_idx = buy_idx + 2
    t5_idx = buy_idx + 5
    if t2_idx < len(df):
        t2_ret = ret_from_adj(base, df.iloc[t2_idx]["adj_close"])
        row["fixed_t2_ret"] = t2_ret
        if t2_ret is not None and t2_ret >= 0.03:
            row["decision_ret"] = t2_ret
            row["decision_reason"] = "sell_t2_take_profit_ge3"
        elif t2_ret is not None and t2_ret <= -0.03:
            row["decision_ret"] = t2_ret
            row["decision_reason"] = "sell_t2_stop_le_neg3"
        elif t5_idx < len(df):
            row["decision_ret"] = ret_from_adj(base, df.iloc[t5_idx]["adj_close"])
            row["decision_reason"] = "hold_middle_to_t5"
    return row


def build_base_signal_pool(events: pd.DataFrame, markets: dict, min_entry_price: float = 10.0) -> pd.DataFrame:
    broad_params = {
        "variant_id": "base",
        "contract_max": 0.95,
        "avg_amount_max": 1.05,
        "min_drawdown": 0.025,
        "max_drawdown": 0.20,
        "bull_body_min": 0.0,
        "close_recover_min": 0.0,
        "pct_chg_min": 0.0,
        "trigger_amount_max": 2.00,
        "max_entry_runup": 0.25,
    }
    rows = []
    for _, event in events.iterrows():
        if float(event["entry_price"]) < min_entry_price:
            continue
        market = markets.get(event["ts_code"])
        if market is None:
            continue
        df = prepare_frame(market.frame)
        signal_idx = market.by_date.get(str(event["entry_date"]))
        if signal_idx is None:
            continue
        event = event.copy()
        event["signal_idx"] = signal_idx
        end_idx = min(len(df) - 2, signal_idx + 20)
        for idx in range(signal_idx + 1, end_idx + 1):
            passed, features = detect_param_signal(df, signal_idx, idx, broad_params)
            if passed:
                trade = eval_trade(df, event, idx, features, broad_params)
                if trade is not None:
                    trade["trigger_idx"] = idx
                    rows.append(trade)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def filter_base_signals(base: pd.DataFrame, params: dict) -> pd.DataFrame:
    if base.empty:
        return base.copy()
    mask = (
        (base["amount_contract_ratio"] <= params["contract_max"])
        & (base["avg_amount_to_ma10"] <= params["avg_amount_max"])
        & (base["drawdown_from_peak"].abs() >= params["min_drawdown"])
        & (base["drawdown_from_peak"].abs() <= params["max_drawdown"])
        & (base["bull_body"] >= params["bull_body_min"])
        & (base["close_recover"] >= params["close_recover_min"])
        & (base["trigger_pct_chg"] >= params["pct_chg_min"])
        & (base["trigger_amount_to_ma10"] <= params["trigger_amount_max"])
        & (base["entry_runup"] <= params["max_entry_runup"])
    )
    sample = base.loc[mask].copy()
    if sample.empty:
        return sample
    sample["variant_id"] = params["variant_id"]
    sample = sample.sort_values(["event_id", "review_date", "trigger_idx"])
    return sample.groupby("event_id", as_index=False).first()


def generate_variant_signals(events: pd.DataFrame, markets: dict, params: dict, min_entry_price: float = 10.0) -> pd.DataFrame:
    rows = []
    for _, event in events.iterrows():
        if float(event["entry_price"]) < min_entry_price:
            continue
        market = markets.get(event["ts_code"])
        if market is None:
            continue
        df = prepare_frame(market.frame)
        signal_idx = market.by_date.get(str(event["entry_date"]))
        if signal_idx is None:
            continue
        event = event.copy()
        event["signal_idx"] = signal_idx
        end_idx = min(len(df) - 2, signal_idx + 20)
        for idx in range(signal_idx + 1, end_idx + 1):
            passed, features = detect_param_signal(df, signal_idx, idx, params)
            if passed:
                trade = eval_trade(df, event, idx, features, params)
                if trade is not None:
                    rows.append(trade)
                break
    return pd.DataFrame(rows)


def daily_picks(signals: pd.DataFrame) -> pd.DataFrame:
    if signals.empty:
        return signals.copy()
    picks = []
    for _date, group in signals.sort_values(["review_date", "score"], ascending=[True, False]).groupby("review_date"):
        picks.append(group.sort_values(["score", "ts_code"], ascending=[False, True]).iloc[0].to_dict())
    return pd.DataFrame(picks)


def split_stats(df: pd.DataFrame, metric: str) -> dict:
    if df.empty or metric not in df:
        return {}
    train = df[df["review_date"] <= "20260331"]
    test = df[df["review_date"] >= "20260401"]
    return {
        "all": summarize(df[metric].dropna()),
        "train_to_202603": summarize(train[metric].dropna()),
        "test_202604": summarize(test[metric].dropna()),
    }


def compact_stats(prefix: str, stats: dict) -> dict:
    out = {}
    for split, item in stats.items():
        for key in ["n", "win_rate", "mean", "median", "p25", "p75", "min", "max"]:
            out[f"{prefix}_{split}_{key}"] = item.get(key)
    return out


def rank_score(row: dict) -> float:
    test_n = row.get("decision_test_202604_n") or 0
    all_n = row.get("decision_all_n") or 0
    if test_n < 8 or all_n < 25:
        return -999
    test_median = row.get("decision_test_202604_median") or -1
    all_median = row.get("decision_all_median") or -1
    test_win = row.get("decision_test_202604_win_rate") or 0
    p25 = row.get("decision_test_202604_p25") or -1
    return test_median * 100 + all_median * 60 + test_win * 15 + p25 * 20 + min(test_n, 30) * 0.05


def summarize_variant(events: pd.DataFrame, markets: dict, params: dict) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    signals = generate_variant_signals(events, markets, params)
    picks = daily_picks(signals)
    signal_stats = split_stats(signals, "decision_ret")
    pick_stats = split_stats(picks, "decision_ret")
    row = {
        **params,
        "signals": len(signals),
        "daily_picks": len(picks),
        **compact_stats("signal_decision", signal_stats),
        **compact_stats("decision", pick_stats),
    }
    row["rank_score"] = rank_score(row)
    return row, signals, picks


def summarize_variant_from_base(base: pd.DataFrame, params: dict) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    signals = filter_base_signals(base, params)
    picks = daily_picks(signals)
    signal_stats = split_stats(signals, "decision_ret")
    pick_stats = split_stats(picks, "decision_ret")
    row = {
        **params,
        "signals": len(signals),
        "daily_picks": len(picks),
        **compact_stats("signal_decision", signal_stats),
        **compact_stats("decision", pick_stats),
    }
    row["rank_score"] = rank_score(row)
    return row, signals, picks


def latest_current_candidates(events: pd.DataFrame, markets: dict, params: dict) -> pd.DataFrame:
    rows = []
    for _, event in events.iterrows():
        if float(event["entry_price"]) < 10:
            continue
        market = markets.get(event["ts_code"])
        if market is None:
            continue
        df = prepare_frame(market.frame)
        signal_idx = market.by_date.get(str(event["entry_date"]))
        if signal_idx is None:
            continue
        latest_idx = len(df) - 1
        if latest_idx > signal_idx + 20:
            continue
        passed, features = detect_param_signal(df, signal_idx, latest_idx, params)
        if passed:
            latest = df.iloc[latest_idx]
            event = event.copy()
            event["signal_idx"] = signal_idx
            rows.append(
                {
                    "ts_code": event["ts_code"],
                    "name": event["name"],
                    "entry_date": event["entry_date"],
                    "entry_price": float(event["entry_price"]),
                    "review_date": latest["trade_date"],
                    "trigger_age_trading_days": latest_idx - signal_idx,
                    "trigger_close": round_num(latest["close"]),
                    "score": setup_score(event, features),
                    **{k: round_num(v) for k, v in features.items()},
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("score", ascending=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Deep dive contracting pullback bullish candle setup.")
    parser.add_argument("--events", default=str(RAW_EVENTS_PATH), help="Path to pgc_raw_events.json.")
    parser.add_argument("--market-dir", default=str(MARKET_DIR), help="Cached Tushare data directory.")
    parser.add_argument("--limit", type=int, default=0, help="Optional parameter-grid limit for quick tests.")
    args = parser.parse_args()

    events = load_events(Path(args.events))
    markets = {ts_code: load_market(ts_code, Path(args.market_dir)) for ts_code in sorted(events["ts_code"].dropna().unique())}
    grid = build_param_grid()
    if args.limit:
        grid = grid[: args.limit]

    base = build_base_signal_pool(events, markets)
    rows = []
    best = None
    best_signals = pd.DataFrame()
    best_picks = pd.DataFrame()
    for params in grid:
        row, signals, picks = summarize_variant_from_base(base, params)
        rows.append(row)
        if best is None or row["rank_score"] > best["rank_score"]:
            best = row
            best_signals = signals
            best_picks = picks

    summary_df = pd.DataFrame(rows).sort_values("rank_score", ascending=False)
    Path(SUMMARY_CSV).parent.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(SUMMARY_CSV, index=False)
    best_signals.to_csv(BEST_SIGNALS_CSV, index=False)
    current = latest_current_candidates(events, markets, best)
    current.to_csv(CURRENT_CSV, index=False)

    top_rows = summary_df.head(15).to_dict(orient="records")
    best_params = {key: best[key] for key in build_param_grid()[0].keys() if key in best}
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "variants_tested": len(summary_df),
        "best_params": best_params,
        "best_summary": best,
        "top_variants": top_rows,
        "best_signal_stats": {
            "decision": split_stats(best_signals, "decision_ret"),
            "fixed_t2": split_stats(best_signals, "fixed_t2_ret"),
            "ret_5d": split_stats(best_signals, "ret_5d"),
            "mfe_5d": split_stats(best_signals, "mfe_5d"),
            "mae_5d": split_stats(best_signals, "mae_5d"),
        },
        "best_daily_pick_stats": {
            "decision": split_stats(best_picks, "decision_ret"),
            "fixed_t2": split_stats(best_picks, "fixed_t2_ret"),
        },
        "current_candidates": current.to_dict(orient="records"),
    }
    Path(JSON_OUT).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def variant_row(row: dict) -> list[str]:
        return [
            row["variant_id"],
            row["daily_picks"],
            round_num(row["rank_score"], 2),
            pct(row.get("decision_all_median")),
            pct(row.get("decision_all_win_rate")),
            row.get("decision_test_202604_n"),
            pct(row.get("decision_test_202604_median")),
            pct(row.get("decision_test_202604_win_rate")),
            pct(row.get("decision_test_202604_p25")),
            f"contract<={row['contract_max']}, avgAmt<={row['avg_amount_max']}, dd={row['min_drawdown']}-{row['max_drawdown']}, body>={row['bull_body_min']}, pct>={row['pct_chg_min']}",
        ]

    current_text = "无"
    if not current.empty:
        top = current.iloc[0]
        current_text = (
            f"{top['ts_code']} {top['name']}，评分 {top['score']}，"
            f"回调 {top['pullback_days']} 天，缩量比 {top['amount_contract_ratio']:.2f}，"
            f"阳线实体 {top['bull_body']:.2%}"
        )

    report = f"""# 缩量回调后一根阳线买点深挖

> 目标形态：PGC 入池后先缩量回调，随后出现一根确认阳线；复盘日收盘确认，次日开盘买入。所有参数只使用复盘日收盘前可见数据。

## 参数搜索

- 测试参数组合：{len(summary_df)}
- 训练/观察期：`review_date <= 2026-03-31`
- 近端验证期：`2026-04-01` 至 `2026-04-30`
- 最终评分优先看 4 月验证期中位收益、胜率、P25，并要求样本数不太小。

## 最优参数，当前第一版

```json
{json.dumps(best_params, ensure_ascii=False, indent=2)}
```

## Top 参数组合

{md_table(["参数ID", "每日入选N", "评分", "全样本中位", "全样本胜率", "4月N", "4月中位", "4月胜率", "4月P25", "参数"], top_rows, variant_row)}

## 最优参数：信号级统计

### T+2 判断后

{md_table(["区间", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], [{"metric": k, **v} for k, v in result["best_signal_stats"]["decision"].items()], stat_row)}

### 5日 MFE

{md_table(["区间", "N", "胜率", "均值", "中位", "P25", "P75", "最小", "最大"], [{"metric": k, **v} for k, v in result["best_signal_stats"]["mfe_5d"].items()], stat_row)}

## 最优参数：每日只选一只统计

### T+2 判断后

{md_table(["区间", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], [{"metric": k, **v} for k, v in result["best_daily_pick_stats"]["decision"].items()], stat_row)}

### T+2 固定卖出

{md_table(["区间", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], [{"metric": k, **v} for k, v in result["best_daily_pick_stats"]["fixed_t2"].items()], stat_row)}

## 当前最新候选

{current_text}

完整文件：

- `{SUMMARY_CSV}`
- `{BEST_SIGNALS_CSV}`
- `{CURRENT_CSV}`

## 初步结论

- 这个形态值得保留，但必须避免过拟合。看参数排名时优先关注 4 月验证期，而不是全样本最高收益。
- 如果最优参数的 4 月 P25 仍然较弱，实盘需要更严格的止损或市场环境过滤。
- 下一步可以把最优参数并回每日复盘策略，作为正式 `contracting_pullback_bullish_v2`。
"""
    Path(MD_OUT).write_text(report, encoding="utf-8")
    print(json.dumps({"variants": len(summary_df), "best": best_params["variant_id"], "out_md": str(MD_OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
