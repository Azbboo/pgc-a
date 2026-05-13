#!/usr/bin/env python3
"""Analyze PGC dip-buy entries after a pullback from the post-entry peak."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from analyze_pgc_event_backtest import (
    EXIT_CONFIGS,
    HORIZONS,
    MARKET_DIR,
    MarketData,
    load_market,
    pct,
    ret_from_adj,
    round_num,
    simulate_exit,
    summarize,
)


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "pgc_trading.db"
SCORES_CSV = ROOT / "data" / "pgc_big_winner_scores.csv"
CURRENT_SCORES_CSV = ROOT / "data" / "pgc_big_winner_current_scores.csv"
TRADES_CSV = ROOT / "data" / "pgc_pullback_dip_buy_trades.csv"
CURRENT_LEVELS_CSV = ROOT / "data" / "pgc_pullback_dip_buy_current_levels.csv"
JSON_OUT = ROOT / "reports" / "pgc_pullback_dip_buy.json"
MD_OUT = ROOT / "reports" / "pgc_pullback_dip_buy.md"

DEFAULT_RETRACE_PCTS = [0.03, 0.05, 0.08, 0.10, 0.12, 0.15]
DEFAULT_MIN_AGES = [3, 6]
DEFAULT_MIN_PEAK_RUNUPS = [0.05, 0.08, 0.12]


def date_str(value) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def md_table(headers: list[str], rows: list[dict], row_fn) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row_fn(row)) + " |")
    return "\n".join(lines)


def stat_cells(row: dict, prefix: str) -> list[str]:
    return [
        row.get(f"{prefix}_n", 0),
        pct(row.get(f"{prefix}_win_rate")),
        pct(row.get(f"{prefix}_mean")),
        pct(row.get(f"{prefix}_median")),
        pct(row.get(f"{prefix}_p25")),
        pct(row.get(f"{prefix}_p75")),
    ]


def add_stat(prefix: str, values: pd.Series) -> dict:
    return {f"{prefix}_{key}": value for key, value in summarize(values.dropna()).items()}


def clean_value(value):
    if isinstance(value, bool) or isinstance(value, str):
        return value
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return round_num(value)
    return value


def variant_id(retrace_pct: float, min_age: int, min_peak_runup: float) -> str:
    return f"dip_r{int(round(retrace_pct * 100)):02d}_a{min_age}_run{int(round(min_peak_runup * 100)):02d}"


def load_market_with_db_overlay(ts_code: str, market_dir: Path, db_path: Path | None) -> MarketData | None:
    market = load_market(ts_code, market_dir)
    db_frame = _load_market_frame_from_db(ts_code, db_path)
    if db_frame.empty:
        return market
    frames = [db_frame]
    if market is not None and not market.frame.empty:
        frames.insert(0, market.frame)
    merged = pd.concat(frames, ignore_index=True, sort=False)
    merged["trade_date"] = merged["trade_date"].astype(str)
    merged = merged.sort_values("trade_date").drop_duplicates(["ts_code", "trade_date"], keep="last")
    merged = _normalize_market_frame(merged)
    by_date = {str(row.trade_date): int(index) for index, row in merged.iterrows()}
    return MarketData(frame=merged, by_date=by_date)


def _load_market_frame_from_db(ts_code: str, db_path: Path | None) -> pd.DataFrame:
    if db_path is None or not db_path.exists():
        return pd.DataFrame()
    try:
        with sqlite3.connect(db_path) as conn:
            return pd.read_sql_query(
                """
                SELECT ts_code, trade_date, open, high, low, close, vol, amount,
                       adj_factor, adj_open, adj_high, adj_low, adj_close
                FROM market_bars
                WHERE ts_code = ?
                ORDER BY trade_date
                """,
                conn,
                params=(ts_code,),
                dtype={"trade_date": str},
            )
    except (sqlite3.Error, pd.errors.DatabaseError):
        return pd.DataFrame()


def _normalize_market_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy().sort_values("trade_date").reset_index(drop=True)
    for column in [
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
        "adj_factor",
        "adj_open",
        "adj_high",
        "adj_low",
        "adj_close",
    ]:
        if column in out:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    if "adj_factor" not in out:
        out["adj_factor"] = None
    out["adj_factor"] = out["adj_factor"].ffill().bfill().fillna(1.0)
    for column in ["open", "high", "low", "close"]:
        adj_column = f"adj_{column}"
        if adj_column not in out:
            out[adj_column] = None
        out[adj_column] = pd.to_numeric(out[adj_column], errors="coerce")
        out[adj_column] = out[adj_column].fillna(out[column] * out["adj_factor"])
    return out


def market_date_range(markets: dict[str, MarketData | None]) -> dict[str, str | None]:
    dates = [
        str(market.frame.iloc[index]["trade_date"])
        for market in markets.values()
        if market is not None and not market.frame.empty
        for index in (0, len(market.frame) - 1)
    ]
    return {"market_data_start_date": min(dates) if dates else None, "market_data_end_date": max(dates) if dates else None}


def build_param_grid(retrace_pcts: list[float], min_ages: list[int], min_peak_runups: list[float]) -> list[dict]:
    rows = []
    for retrace_pct in retrace_pcts:
        for min_age in min_ages:
            for min_peak_runup in min_peak_runups:
                rows.append(
                    {
                        "variant_id": variant_id(retrace_pct, min_age, min_peak_runup),
                        "retrace_pct": retrace_pct,
                        "min_age": min_age,
                        "min_peak_runup": min_peak_runup,
                    }
                )
    return rows


def price_to_adj(price: float, row: pd.Series) -> float | None:
    factor = row.get("adj_factor")
    if not price or pd.isna(price) or not factor or pd.isna(factor):
        return None
    return float(price) * float(factor)


def find_dip_entry(frame: pd.DataFrame, signal_idx: int, entry_price: float, params: dict, max_age: int) -> dict | None:
    signal_row = frame.iloc[signal_idx]
    base_adj_entry = price_to_adj(entry_price, signal_row)
    if base_adj_entry is None:
        return None

    search_end = min(len(frame) - 1, signal_idx + max_age)
    peak_adj = float(signal_row["adj_high"])
    peak_idx = signal_idx

    for idx in range(signal_idx + 1, search_end + 1):
        age = idx - signal_idx
        row = frame.iloc[idx]

        prior_peak_adj = peak_adj
        prior_peak_idx = peak_idx
        peak_runup = ret_from_adj(base_adj_entry, prior_peak_adj)

        if age >= params["min_age"] and peak_runup is not None and peak_runup >= params["min_peak_runup"]:
            buy_adj_price = prior_peak_adj * (1 - params["retrace_pct"])
            low = float(row["adj_low"])
            high = float(row["adj_high"])
            if low <= buy_adj_price <= high or float(row["adj_open"]) <= buy_adj_price:
                buy_price = buy_adj_price / float(row["adj_factor"])
                return {
                    "buy_idx": idx,
                    "buy_date": row["trade_date"],
                    "buy_price": buy_price,
                    "buy_adj_price": buy_adj_price,
                    "trigger_age_trading_days": age,
                    "prior_peak_date": frame.iloc[prior_peak_idx]["trade_date"],
                    "prior_peak_price": prior_peak_adj / float(frame.iloc[prior_peak_idx]["adj_factor"]),
                    "peak_runup": peak_runup,
                    "pullback_from_peak": -params["retrace_pct"],
                    "entry_runup_at_buy": ret_from_adj(base_adj_entry, buy_adj_price),
                }

        if float(row["adj_high"]) > peak_adj:
            peak_adj = float(row["adj_high"])
            peak_idx = idx

    return None


def evaluate_trade(frame: pd.DataFrame, buy_idx: int, buy_adj_price: float) -> dict:
    row: dict = {}
    for horizon in HORIZONS:
        end_idx = buy_idx + horizon
        if end_idx < len(frame):
            end = frame.iloc[end_idx]
            row[f"ret_{horizon}d"] = ret_from_adj(buy_adj_price, end["adj_close"])
            window = frame.iloc[buy_idx + 1 : end_idx + 1]
            if not window.empty:
                row[f"mfe_{horizon}d"] = ret_from_adj(buy_adj_price, window["adj_high"].max())
                row[f"mae_{horizon}d"] = ret_from_adj(buy_adj_price, window["adj_low"].min())

    for config in EXIT_CONFIGS:
        exit_result = simulate_exit(frame, buy_idx, buy_adj_price, config)
        prefix = f"exit_{config['name']}"
        row[f"{prefix}_ret"] = exit_result["ret"]
        row[f"{prefix}_reason"] = exit_result["exit_reason"]
        row[f"{prefix}_date"] = exit_result["exit_date"]
        row[f"{prefix}_days_held"] = exit_result["days_held"]
    return row


def analyze_event(event: pd.Series, market, params: dict, max_age: int) -> dict | None:
    if market is None:
        return None
    entry_date = date_str(event.get("entry_date"))
    signal_idx = market.by_date.get(entry_date)
    if signal_idx is None:
        return None

    entry_price = float(event["entry_price"])
    found = find_dip_entry(market.frame, signal_idx, entry_price, params, max_age)
    if not found:
        return None

    result = {
        "event_id": int(event["event_id"]),
        "variant_id": params["variant_id"],
        "ts_code": event["ts_code"],
        "name": event["name"],
        "entry_date": entry_date,
        "entry_price": entry_price,
        "retrace_pct": params["retrace_pct"],
        "min_age": params["min_age"],
        "min_peak_runup": params["min_peak_runup"],
        "bigwin_score": round_num(event.get("bigwin_score")),
        "bigwin_grade": event.get("bigwin_grade"),
        "entry_price_pos_in_day": round_num(event.get("entry_price_pos_in_day")),
        "pre_ret_20d": round_num(event.get("pre_ret_20d")),
        "pre_amount_ratio_5_20": round_num(event.get("pre_amount_ratio_5_20")),
        "signal_volume_ratio": round_num(event.get("signal_volume_ratio")),
        **{key: round_num(value) for key, value in found.items() if key not in {"buy_idx", "buy_date"}},
        "buy_date": found["buy_date"],
        "buy_price": round_num(found["buy_price"], 4),
        "buy_gap_from_entry": round_num(found["buy_price"] / entry_price - 1),
    }
    result.update({key: clean_value(value) for key, value in evaluate_trade(market.frame, found["buy_idx"], found["buy_adj_price"]).items()})
    return result


def summarize_variants(trades: pd.DataFrame, params: list[dict], eligible_events: int) -> list[dict]:
    rows = []
    for param in params:
        part = trades[trades["variant_id"] == param["variant_id"]] if not trades.empty else pd.DataFrame()
        row = {
            **param,
            "eligible_events": eligible_events,
            "fill_n": int(len(part)),
            "fill_rate": round_num(len(part) / eligible_events) if eligible_events else None,
        }
        for metric in [
            "ret_1d",
            "mfe_1d",
            "mae_1d",
            "ret_3d",
            "ret_5d",
            "ret_10d",
            "mfe_10d",
            "mae_10d",
            "exit_TP6_SL6_10D_ret",
        ]:
            row.update(add_stat(metric, part[metric]) if metric in part else add_stat(metric, pd.Series(dtype=float)))
        row["research_score"] = rank_score(row)
        rows.append(row)
    return sorted(rows, key=lambda item: item["research_score"], reverse=True)


def rank_score(row: dict) -> float:
    n = row.get("ret_5d_n") or 0
    if n < 12:
        return -999.0
    median5 = row.get("ret_5d_median") or 0
    mean5 = row.get("ret_5d_mean") or 0
    p25_5 = row.get("ret_5d_p25") or 0
    win5 = row.get("ret_5d_win_rate") or 0
    fill_rate = row.get("fill_rate") or 0
    return round(float(median5 * 100 + mean5 * 35 + p25_5 * 70 + win5 * 4 + math.log1p(n) + fill_rate), 6)


def summarize_groups(trades: pd.DataFrame, selected_variant: str) -> dict:
    part = trades[trades["variant_id"] == selected_variant].copy()
    if part.empty:
        return {"score": [], "age": [], "entry_runup": []}

    score_groups = [
        ("全部", pd.Series(True, index=part.index)),
        ("潜力分>=75", part["bigwin_score"] >= 75),
        ("潜力分>=80", part["bigwin_score"] >= 80),
        ("潜力分<75", part["bigwin_score"] < 75),
    ]
    age_groups = [
        ("3-5天", part["trigger_age_trading_days"].between(3, 5)),
        ("6-8天", part["trigger_age_trading_days"].between(6, 8)),
        ("9-13天", part["trigger_age_trading_days"].between(9, 13)),
        ("14天以上", part["trigger_age_trading_days"] >= 14),
    ]
    runup_groups = [
        ("买入仍低于入池价", part["entry_runup_at_buy"] < 0),
        ("入池价上方0-5%", part["entry_runup_at_buy"].between(0, 0.05, inclusive="left")),
        ("入池价上方5-10%", part["entry_runup_at_buy"].between(0.05, 0.10, inclusive="left")),
        ("入池价上方>=10%", part["entry_runup_at_buy"] >= 0.10),
    ]

    def build(rows: list[tuple[str, pd.Series]]) -> list[dict]:
        out = []
        for name, mask in rows:
            group = part.loc[mask]
            row = {"group": name}
            for metric in ["ret_3d", "ret_5d", "ret_10d", "mfe_10d", "mae_10d"]:
                row.update(add_stat(metric, group[metric]))
            out.append(row)
        return out

    return {
        "score": build(score_groups),
        "age": build(age_groups),
        "entry_runup": build(runup_groups),
    }


def latest_current_levels(
    current: pd.DataFrame,
    markets: dict[str, MarketData | None],
    selected_params: dict,
) -> pd.DataFrame:
    rows = []
    for _, item in current.iterrows():
        market = markets.get(item["ts_code"])
        if market is None:
            continue
        entry_date = date_str(item.get("entry_date"))
        signal_idx = market.by_date.get(entry_date)
        if signal_idx is None:
            continue
        frame = market.frame
        review_idx = len(frame) - 1
        window = frame.iloc[signal_idx : review_idx + 1]
        if window.empty:
            continue
        peak_idx = int(window["adj_high"].idxmax())
        peak_row = frame.iloc[peak_idx]
        latest = frame.iloc[review_idx]
        latest_close = float(latest["close"])
        prior_peak = float(peak_row["adj_high"]) / float(peak_row["adj_factor"])

        row = {
            "ts_code": item["ts_code"],
            "name": item["name"],
            "entry_date": entry_date,
            "review_date": latest["trade_date"],
            "trigger_age_trading_days": int(review_idx - signal_idx),
            "entry_price": round_num(item.get("entry_price"), 4),
            "latest_close": round_num(latest_close, 4),
            "prior_peak_date": peak_row["trade_date"],
            "prior_peak_price": round_num(prior_peak, 4),
            "peak_runup": round_num(prior_peak / float(item["entry_price"]) - 1) if item.get("entry_price") else None,
            "combined_score": round_num(item.get("combined_score")),
            "bigwin_score": round_num(item.get("bigwin_score")),
        }
        for retrace_pct in DEFAULT_RETRACE_PCTS:
            level = prior_peak * (1 - retrace_pct)
            row[f"dip_{int(retrace_pct * 100)}_price"] = round_num(level, 2)
            row[f"dist_to_dip_{int(retrace_pct * 100)}"] = round_num(latest_close / level - 1) if level else None
        selected_retrace = int(round(selected_params["retrace_pct"] * 100))
        row["selected_dip_price"] = row.get(f"dip_{selected_retrace}_price")
        row["dist_to_selected_dip"] = row.get(f"dist_to_dip_{selected_retrace}")
        row["dip_ready"] = (
            bool(row["trigger_age_trading_days"] >= selected_params["min_age"])
            and row.get("peak_runup") is not None
            and bool(row["peak_runup"] >= selected_params["min_peak_runup"])
        )
        rows.append(row)
    return pd.DataFrame(rows)


def build_report(summary: dict) -> str:
    top_rows = summary["variants"][:12]
    selected = summary["selected_variant"]
    selected_params = summary["selected_params"]
    groups = summary["selected_groups"]
    current_levels = summary["current_levels"]

    top_table = md_table(
        [
            "策略",
            "触发N",
            "触发率",
            "T1胜率",
            "T1均值",
            "T5胜率",
            "T5均值",
            "T5中位",
            "T5 P25",
            "T10中位",
            "10日MFE中位",
            "10日MAE中位",
        ],
        top_rows,
        lambda r: [
            r["variant_id"],
            r["fill_n"],
            pct(r["fill_rate"]),
            pct(r["ret_1d_win_rate"]),
            pct(r["ret_1d_mean"]),
            pct(r["ret_5d_win_rate"]),
            pct(r["ret_5d_mean"]),
            pct(r["ret_5d_median"]),
            pct(r["ret_5d_p25"]),
            pct(r["ret_10d_median"]),
            pct(r["mfe_10d_median"]),
            pct(r["mae_10d_median"]),
        ],
    )

    score_table = md_table(
        ["分组", "T5样本", "T5胜率", "T5均值", "T5中位", "T5 P25", "T5 P75", "T10样本", "T10胜率", "T10均值", "T10中位"],
        groups["score"],
        lambda r: [r["group"], *stat_cells(r, "ret_5d"), *stat_cells(r, "ret_10d")[:4]],
    )
    age_table = md_table(
        ["触发时间", "T5样本", "T5胜率", "T5均值", "T5中位", "T5 P25", "T5 P75", "T10样本", "T10胜率", "T10均值", "T10中位"],
        groups["age"],
        lambda r: [r["group"], *stat_cells(r, "ret_5d"), *stat_cells(r, "ret_10d")[:4]],
    )
    runup_table = md_table(
        ["买入价相对入池价", "T5样本", "T5胜率", "T5均值", "T5中位", "T5 P25", "T5 P75", "T10样本", "T10胜率", "T10均值", "T10中位"],
        groups["entry_runup"],
        lambda r: [r["group"], *stat_cells(r, "ret_5d"), *stat_cells(r, "ret_10d")[:4]],
    )
    current_table = md_table(
        ["代码", "名称", "交易日", "现价", "阶段高点", "高点日", "资格", "8%观察", "12%一档", "15%二档", "距15%档", "综合分", "潜力分"],
        current_levels,
        lambda r: [
            r["ts_code"],
            r["name"],
            r["review_date"],
            f'{r["latest_close"]:.2f}',
            f'{r["prior_peak_price"]:.2f}',
            r["prior_peak_date"],
            "满足" if r.get("dip_ready") else "未满足",
            f'{r["dip_8_price"]:.2f}',
            f'{r["dip_12_price"]:.2f}',
            f'{r["dip_15_price"]:.2f}',
            pct(r["dist_to_dip_15"]),
            f'{r["combined_score"]:.1f}' if pd.notna(r.get("combined_score")) else "",
            f'{r["bigwin_score"]:.0f}' if pd.notna(r.get("bigwin_score")) else "",
        ],
    )

    return "\n".join(
        [
            "# PGC 回撤低吸策略研究",
            "",
            f"- 生成时间: {summary['generated_at']}",
            f"- 样本口径: `pgc_big_winner_scores.csv`，有行情且可定位入池日的事件 {summary['eligible_events']} 个。",
            "- 低吸定义: 入池后先形成阶段高点，随后从该高点回撤到指定比例的限价位；触发日只使用前一交易日以前已经形成的高点，避免当天高低点互相偷看。",
            "- 成交假设: 若日内最低价触及低吸价，按低吸价成交；若跳空低于低吸价，也保守按低吸价成交。",
            "",
            "## 参数搜索结论",
            "",
            "- 单纯“到某个回撤比例就买”的独立优势不强，明显弱于已有 CPB 阳线确认策略。",
            "- 本次搜索里，浅回撤 3%-10% 的 T5 中位数普遍为负；相对能看的组合集中在 12%-15% 深回撤，但 P25 仍然有较大回撤。",
            "",
            top_table,
            "",
            "## 当前选用的观察版",
            "",
            "```json",
            json.dumps(selected_params, ensure_ascii=False, indent=2),
            "```",
            "",
            f"- 观察版策略: `{selected}`。",
            "- 解释: 要求入池后至少有一段上冲，再等回撤到阶段高点下方的低吸档位。它比 CPB 阳线确认更早，但也更容易买在下跌途中，所以必须配合仓位和止损。",
            "",
            "## 潜力分过滤",
            "",
            score_table,
            "",
            "## 触发时间过滤",
            "",
            age_table,
            "",
            "## 买入价相对入池价",
            "",
            runup_table,
            "",
            "## 当前候选价位",
            "",
            current_table,
            "",
            "## 执行建议",
            "",
            "1. 不把 3%-10% 回撤当买点，只当提醒；历史样本里这些档位更像“还在半山腰”。",
            "2. 真正低吸档放在阶段高点回撤 12%-15%：12% 小试，15% 才是观察版主档。",
            "3. 只在入池后已经上冲过、且入池满 6 个交易日的票上低吸；否则容易把弱势阴跌误判成回调。",
            "4. 潜力分低于 75 的票不主动低吸；潜力分 75/80 以上时，历史 T5 均值明显改善，但仍要控制单票仓位。",
            "5. 低吸后若没有缩量止跌或 CPB 阳线确认，不继续摊；这套规则适合作为 CPB 的前置试仓层，不建议替代确认买点。",
            "",
            "完整输出:",
            "",
            f"- `{TRADES_CSV}`",
            f"- `{CURRENT_LEVELS_CSV}`",
            f"- `{JSON_OUT}`",
        ]
    )


def parse_float_list(text: str) -> list[float]:
    return [float(item.strip()) for item in text.split(",") if item.strip()]


def parse_int_list(text: str) -> list[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def run(args: argparse.Namespace) -> None:
    scores = pd.read_csv(args.scores)
    current_scores = pd.read_csv(args.current_scores) if args.current_scores.exists() else pd.DataFrame()
    params = build_param_grid(
        parse_float_list(args.retrace_pcts),
        parse_int_list(args.min_ages),
        parse_float_list(args.min_peak_runups),
    )
    market_dir = Path(args.market_dir)
    ts_codes = set(str(ts_code) for ts_code in scores["ts_code"].dropna().unique())
    if "ts_code" in current_scores:
        ts_codes.update(str(ts_code) for ts_code in current_scores["ts_code"].dropna().unique())
    markets = {ts_code: load_market_with_db_overlay(ts_code, market_dir, args.db_path) for ts_code in sorted(ts_codes)}
    eligible_events = int(
        sum(1 for _, row in scores.iterrows() if markets.get(row["ts_code"]) is not None and date_str(row.get("entry_date")) in markets[row["ts_code"]].by_date)
    )

    rows = []
    for param in params:
        for _, event in scores.iterrows():
            row = analyze_event(event, markets.get(event["ts_code"]), param, args.max_age)
            if row is not None:
                rows.append(row)
    trades = pd.DataFrame(rows)
    args.trades_out.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(args.trades_out, index=False)

    variants = summarize_variants(trades, params, eligible_events)
    selected_params = next(row for row in variants if row["research_score"] > -999)
    selected_variant = selected_params["variant_id"]
    selected_groups = summarize_groups(trades, selected_variant)

    current_levels = pd.DataFrame()
    if not current_scores.empty:
        current_levels = latest_current_levels(current_scores, markets, selected_params)
        current_levels.to_csv(args.current_levels_out, index=False)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "eligible_events": eligible_events,
        "parameter_count": len(params),
        "source_freshness": {
            **market_date_range(markets),
            "market_data_source": "cached_tushare_csv_with_sqlite_market_bars_overlay",
            "sqlite_market_bars": str(args.db_path),
        },
        "selected_variant": selected_variant,
        "selected_params": {
            "variant_id": selected_variant,
            "retrace_pct": selected_params["retrace_pct"],
            "min_age": selected_params["min_age"],
            "min_peak_runup": selected_params["min_peak_runup"],
            "max_age": args.max_age,
        },
        "variants": variants,
        "selected_groups": selected_groups,
        "current_levels": current_levels.to_dict("records"),
        "outputs": {
            "trades": str(args.trades_out),
            "current_levels": str(args.current_levels_out),
            "json": str(args.json_out),
            "markdown": str(args.md_out),
        },
    }

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.md_out.write_text(build_report(summary) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores", type=Path, default=SCORES_CSV)
    parser.add_argument("--current-scores", type=Path, default=CURRENT_SCORES_CSV)
    parser.add_argument("--market-dir", type=Path, default=MARKET_DIR)
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--trades-out", type=Path, default=TRADES_CSV)
    parser.add_argument("--current-levels-out", type=Path, default=CURRENT_LEVELS_CSV)
    parser.add_argument("--json-out", type=Path, default=JSON_OUT)
    parser.add_argument("--md-out", type=Path, default=MD_OUT)
    parser.add_argument("--retrace-pcts", default=",".join(str(item) for item in DEFAULT_RETRACE_PCTS))
    parser.add_argument("--min-ages", default=",".join(str(item) for item in DEFAULT_MIN_AGES))
    parser.add_argument("--min-peak-runups", default=",".join(str(item) for item in DEFAULT_MIN_PEAK_RUNUPS))
    parser.add_argument("--max-age", type=int, default=20)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
