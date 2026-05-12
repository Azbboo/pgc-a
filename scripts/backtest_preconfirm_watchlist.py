#!/usr/bin/env python3
"""Backtest the pre-confirm watchlist labels used by the daily V2 review."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from analyze_pgc_event_backtest import HORIZONS, MARKET_DIR, RAW_EVENTS_PATH, load_events, load_market, pct, ret_from_adj, round_num, summarize
from deep_dive_contracting_pullback import build_param_grid
from run_daily_v2_review import confirmed_candidates_at_date, load_industry_map, pre_confirm_watchlist_at_date


POOL_JSON = ROOT / "data" / "pgc_pool.json"
TRADES_OUT = ROOT / "data" / "preconfirm_watchlist_backtest_trades.csv"
SUMMARY_OUT = ROOT / "data" / "preconfirm_watchlist_backtest_summary.csv"
JSON_OUT = ROOT / "reports" / "preconfirm_watchlist_backtest.json"
MD_OUT = ROOT / "reports" / "preconfirm_watchlist_backtest.md"


def md_table(headers: list[str], rows: list[dict], row_fn) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row_fn(row)) + " |")
    return "\n".join(lines)


def stat(series: pd.Series) -> dict:
    return summarize(series.dropna()) if series is not None else summarize([])


def add_stat(prefix: str, series: pd.Series) -> dict:
    return {f"{prefix}_{key}": value for key, value in stat(series).items()}


def stat_cells(row: dict, prefix: str) -> list[str]:
    return [
        row.get(f"{prefix}_n", 0),
        pct(row.get(f"{prefix}_win_rate")),
        pct(row.get(f"{prefix}_mean")),
        pct(row.get(f"{prefix}_median")),
        pct(row.get(f"{prefix}_p25")),
        pct(row.get(f"{prefix}_p75")),
    ]


def open_dates(start: str, end: str) -> list[str]:
    path = MARKET_DIR / "trade_cal.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    cal = pd.read_csv(path, dtype={"cal_date": str, "is_open": str})
    return sorted(cal[(cal["is_open"] == "1") & (cal["cal_date"] >= start) & (cal["cal_date"] <= end)]["cal_date"].unique())


def latest_cached_market_date(markets: dict) -> str:
    dates = []
    for market in markets.values():
        if market is not None and not market.frame.empty:
            dates.append(str(market.frame.iloc[-1]["trade_date"]))
    if not dates:
        raise ValueError("No cached market data found.")
    return max(dates)


def returns_from_buy(frame: pd.DataFrame, buy_idx: int, prefix: str) -> dict:
    row = {}
    if buy_idx is None or buy_idx >= len(frame):
        return row
    base = frame.iloc[buy_idx]["adj_open"]
    row[f"{prefix}_date"] = frame.iloc[buy_idx]["trade_date"]
    row[f"{prefix}_open"] = round_num(frame.iloc[buy_idx]["open"], 4)
    for horizon in HORIZONS:
        end_idx = buy_idx + horizon
        if end_idx < len(frame):
            end = frame.iloc[end_idx]
            row[f"{prefix}_ret_{horizon}d"] = ret_from_adj(base, end["adj_close"])
            window = frame.iloc[buy_idx + 1 : end_idx + 1]
            if not window.empty:
                row[f"{prefix}_mfe_{horizon}d"] = ret_from_adj(base, window["adj_high"].max())
                row[f"{prefix}_mae_{horizon}d"] = ret_from_adj(base, window["adj_low"].min())
    return row


def returns_from_watch_close(frame: pd.DataFrame, review_idx: int) -> dict:
    row = {}
    base = frame.iloc[review_idx]["adj_close"]
    next_idx = review_idx + 1
    if next_idx >= len(frame):
        return row
    row["next_day"] = frame.iloc[next_idx]["trade_date"]
    row["next_open_gap"] = ret_from_adj(base, frame.iloc[next_idx]["adj_open"])
    row["next_close_ret_from_watch"] = ret_from_adj(base, frame.iloc[next_idx]["adj_close"])
    row["next_high_ret_from_watch"] = ret_from_adj(base, frame.iloc[next_idx]["adj_high"])
    for horizon in [3, 5, 10]:
        end_idx = review_idx + horizon
        if end_idx < len(frame):
            window = frame.iloc[review_idx + 1 : end_idx + 1]
            row[f"watch_mfe_{horizon}d"] = ret_from_adj(base, window["adj_high"].max())
            row[f"watch_ret_{horizon}d"] = ret_from_adj(base, frame.iloc[end_idx]["adj_close"])
    return row


def backtest(args: argparse.Namespace) -> tuple[pd.DataFrame, list[dict], dict]:
    events = load_events(args.events)
    industry_map = load_industry_map(args.pool)
    markets = {ts_code: load_market(ts_code, MARKET_DIR) for ts_code in sorted(events["ts_code"].dropna().unique())}
    params = build_param_grid()[int(args.variant_id.split("_")[1]) - 1]
    latest_date = args.end_date or latest_cached_market_date(markets)
    dates = open_dates(args.start_date, latest_date)

    rows = []
    for review_date in dates:
        prewatch = pre_confirm_watchlist_at_date(events, markets, params, review_date, industry_map)
        if prewatch.empty:
            continue
        date_pos = dates.index(review_date)
        next_date = dates[date_pos + 1] if date_pos + 1 < len(dates) else None
        confirmed_keys = set()
        if next_date:
            confirmed = confirmed_candidates_at_date(events, markets, params, next_date)
            if not confirmed.empty:
                confirmed_keys = set(zip(confirmed["ts_code"], confirmed["entry_date"].astype(str)))

        for _, signal in prewatch.iterrows():
            market = markets.get(signal["ts_code"])
            if market is None:
                continue
            review_idx = market.by_date.get(str(review_date))
            if review_idx is None:
                continue
            next_idx = review_idx + 1 if review_idx + 1 < len(market.frame) else None
            confirm_next_day = (signal["ts_code"], str(signal["entry_date"])) in confirmed_keys if next_date else None
            confirm_buy_idx = next_idx + 1 if confirm_next_day and next_idx is not None and next_idx + 1 < len(market.frame) else None

            row = {
                "review_date": review_date,
                "ts_code": signal["ts_code"],
                "name": signal["name"],
                "industry": signal.get("industry", ""),
                "entry_date": str(signal["entry_date"]),
                "entry_price": signal["entry_price"],
                "pre_action": signal["pre_action"],
                "bigwin_score": signal["bigwin_score"],
                "bigwin_grade": signal["bigwin_grade"],
                "watch_age_trading_days": signal["watch_age_trading_days"],
                "watch_close": signal["watch_close"],
                "watch_pct_chg": signal["watch_pct_chg"],
                "pullback_days": signal["pullback_days"],
                "amount_contract_ratio": signal["amount_contract_ratio"],
                "avg_amount_to_ma10": signal["avg_amount_to_ma10"],
                "pullback_close_ret": signal["pullback_close_ret"],
                "drawdown_from_peak": signal["drawdown_from_peak"],
                "entry_runup": signal["entry_runup"],
                "confirm_close_min": signal["confirm_close_min"],
                "confirm_next_day": confirm_next_day,
            }
            row.update(returns_from_watch_close(market.frame, review_idx))
            if next_idx is not None:
                row.update(returns_from_buy(market.frame, next_idx, "next_open"))
            if confirm_buy_idx is not None:
                row.update(returns_from_buy(market.frame, confirm_buy_idx, "confirmed_buy"))
            rows.append({key: round_num(value) if isinstance(value, float) else value for key, value in row.items()})

    trades = pd.DataFrame(rows)
    summary = summarize_groups(trades)
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "variant_id": args.variant_id,
        "start_date": args.start_date,
        "end_date": latest_date,
        "review_dates": len(dates),
        "signals": int(len(trades)),
        "outputs": {
            "trades": str(args.trades_out),
            "summary": str(args.summary_out),
            "json": str(args.json_out),
            "markdown": str(args.md_out),
        },
    }
    return trades, summary, meta


def summarize_groups(trades: pd.DataFrame) -> list[dict]:
    if trades.empty:
        return []
    order = {"高潜伏预警": 1, "普通预警": 2, "观察": 3, "全部": 9}
    groups: list[tuple[str, pd.DataFrame]] = [("全部", trades)]
    groups.extend((name, group) for name, group in trades.groupby("pre_action"))

    rows = []
    for name, group in groups:
        row = {
            "pre_action": name,
            "signals": int(len(group)),
            "review_days": int(group["review_date"].nunique()),
            "stocks": int(group[["ts_code", "entry_date"]].drop_duplicates().shape[0]),
            "confirm_next_day_n": int(group["confirm_next_day"].dropna().shape[0]),
            "confirm_next_day_rate": round_num(group["confirm_next_day"].dropna().astype(float).mean())
            if group["confirm_next_day"].dropna().shape[0]
            else None,
            "avg_bigwin_score": round_num(group["bigwin_score"].mean()),
        }
        for metric in [
            "next_close_ret_from_watch",
            "next_high_ret_from_watch",
            "watch_ret_5d",
            "watch_mfe_5d",
            "next_open_ret_1d",
            "next_open_ret_3d",
            "next_open_ret_5d",
            "next_open_mfe_3d",
            "confirmed_buy_ret_1d",
            "confirmed_buy_ret_3d",
            "confirmed_buy_ret_5d",
        ]:
            if metric in group:
                row.update(add_stat(metric, group[metric]))
        rows.append(row)
    return sorted(rows, key=lambda item: order.get(item["pre_action"], 8))


def build_report(trades: pd.DataFrame, summary: list[dict], meta: dict) -> str:
    high = trades[trades["pre_action"] == "高潜伏预警"].copy() if not trades.empty else pd.DataFrame()
    high_rows = []
    if not high.empty:
        cols = [
            "review_date",
            "ts_code",
            "name",
            "industry",
            "bigwin_score",
            "confirm_next_day",
            "next_close_ret_from_watch",
            "next_high_ret_from_watch",
            "next_open_ret_1d",
            "next_open_ret_3d",
            "next_open_ret_5d",
            "confirmed_buy_ret_3d",
        ]
        high_rows = high.sort_values(["review_date", "bigwin_score"], ascending=[False, False])[cols].head(30).to_dict("records")

    summary_table = md_table(
        [
            "分组",
            "信号N",
            "天数",
            "股票事件",
            "确认可评估N",
            "次日确认率",
            "次日收盘",
            "次日最高",
            "预警后5日收盘",
            "预警后5日MFE",
            "次开T1",
            "次开T3",
            "次开T5",
            "确认后T3",
        ],
        summary,
        lambda r: [
            r["pre_action"],
            r["signals"],
            r["review_days"],
            r["stocks"],
            r.get("confirm_next_day_n", 0),
            pct(r.get("confirm_next_day_rate")),
            pct(r.get("next_close_ret_from_watch_mean")),
            pct(r.get("next_high_ret_from_watch_mean")),
            pct(r.get("watch_ret_5d_mean")),
            pct(r.get("watch_mfe_5d_mean")),
            pct(r.get("next_open_ret_1d_mean")),
            pct(r.get("next_open_ret_3d_mean")),
            pct(r.get("next_open_ret_5d_mean")),
            pct(r.get("confirmed_buy_ret_3d_mean")),
        ],
    )
    detail_table = "无高潜伏预警样本。"
    if high_rows:
        detail_table = md_table(
            ["复盘日", "股票", "行业", "潜力分", "次日确认", "次日收盘", "次日最高", "次开T1", "次开T3", "次开T5", "确认后T3"],
            high_rows,
            lambda r: [
                r["review_date"],
                f'{r["ts_code"]} {r["name"]}',
                r["industry"],
                f'{r["bigwin_score"]:.0f}',
                "是" if r["confirm_next_day"] else "否",
                pct(r.get("next_close_ret_from_watch")),
                pct(r.get("next_high_ret_from_watch")),
                pct(r.get("next_open_ret_1d")),
                pct(r.get("next_open_ret_3d")),
                pct(r.get("next_open_ret_5d")),
                pct(r.get("confirmed_buy_ret_3d")),
            ],
        )

    high_summary = next((row for row in summary if row["pre_action"] == "高潜伏预警"), None)
    read_lines = []
    if high_summary:
        read_lines = [
            f"- 高潜伏预警样本 {high_summary['signals']} 条，覆盖 {high_summary['review_days']} 个复盘日 / {high_summary['stocks']} 个股票事件。",
            f"- 次日确认率 {pct(high_summary.get('confirm_next_day_rate'))}；这说明它更像“提前盯盘池”，不是自动买入池。",
            f"- 若预警次日开盘直接买，T1/T3/T5 均值分别为 {pct(high_summary.get('next_open_ret_1d_mean'))} / {pct(high_summary.get('next_open_ret_3d_mean'))} / {pct(high_summary.get('next_open_ret_5d_mean'))}。",
            f"- 若等次日确认后再买，确认后 T3 均值为 {pct(high_summary.get('confirmed_buy_ret_3d_mean'))}，样本数见 CSV。",
        ]

    return "\n".join(
        [
            "# Pre-confirm Watchlist Backtest",
            "",
            f"- 生成时间: {meta['generated_at']}",
            f"- 策略参数: `{meta['variant_id']}`",
            f"- 复盘区间: `{meta['start_date']}` 至 `{meta['end_date']}`",
            f"- 复盘交易日: {meta['review_dates']}",
            f"- 预警信号: {meta['signals']}",
            "- 口径: 复盘日收盘后进入确认前预警池；`次开` 表示下一交易日开盘买；`确认后` 表示下一交易日收盘确认，再后一交易日开盘买。",
            "",
            "## 快读",
            "",
            *(read_lines or ["- 无高潜伏预警样本。"]),
            "",
            "## 分组表现",
            "",
            summary_table,
            "",
            "## 高潜伏预警明细",
            "",
            detail_table,
            "",
            "## 输出",
            "",
            f"- `{meta['outputs']['trades']}`",
            f"- `{meta['outputs']['summary']}`",
            f"- `{meta['outputs']['json']}`",
        ]
    )


def run(args: argparse.Namespace) -> None:
    trades, summary, meta = backtest(args)
    args.trades_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(args.trades_out, index=False)
    pd.DataFrame(summary).to_csv(args.summary_out, index=False)
    args.json_out.write_text(json.dumps({"meta": meta, "summary": summary}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.md_out.write_text(build_report(trades, summary, meta) + "\n", encoding="utf-8")
    print(json.dumps({"signals": len(trades), "report": str(args.md_out)}, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="20251110")
    parser.add_argument("--end-date")
    parser.add_argument("--variant-id", default="cpb_6157")
    parser.add_argument("--events", type=Path, default=RAW_EVENTS_PATH)
    parser.add_argument("--pool", type=Path, default=POOL_JSON)
    parser.add_argument("--trades-out", type=Path, default=TRADES_OUT)
    parser.add_argument("--summary-out", type=Path, default=SUMMARY_OUT)
    parser.add_argument("--json-out", type=Path, default=JSON_OUT)
    parser.add_argument("--md-out", type=Path, default=MD_OUT)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
