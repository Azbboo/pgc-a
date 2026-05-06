#!/usr/bin/env python3
"""Backtest daily after-close review: pick one PGC candidate, buy next open."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from analyze_pgc_buy_setups import SETUPS, prepare_frame
from analyze_pgc_event_backtest import MARKET_DIR, RAW_EVENTS_PATH, load_events, load_market, pct, ret_from_adj, round_num, summarize


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports"
CANDIDATES_CSV = ROOT / "data" / "daily_review_candidates.csv"
PICKS_CSV = ROOT / "data" / "daily_review_picks.csv"
PICKS_T2_CSV = ROOT / "data" / "daily_review_picks_t2.csv"
JSON_OUT = OUT_DIR / "daily_review_strategy.json"
MD_OUT = OUT_DIR / "daily_review_strategy.md"


SETUP_BASE_SCORE = {
    "sideways_breakout": 100.0,
    "contracting_pullback_bullish": 96.0,
    "old_volume_reactivation": 86.0,
    "pullback_stabilization": 78.0,
}


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


def capped(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe(value, default=None):
    return default if value is None or pd.isna(value) else value


def score_candidate(setup: str, event: pd.Series, features: dict) -> tuple[float, list[str]]:
    score = SETUP_BASE_SCORE[setup]
    reasons = [setup]
    price = float(event["entry_price"])
    if price < 5:
        score -= 12
        reasons.append("low_price_penalty")
    elif price < 10:
        score -= 5
        reasons.append("sub10_penalty")
    elif 20 <= price <= 100:
        score += 8
        reasons.append("preferred_price_20_100")
    elif price >= 10:
        score += 4
        reasons.append("price_ge_10")

    pct_chg = safe(features.get("setup_pct_chg"), 0.0)
    score += capped(pct_chg * 120, -5, 12)

    if setup == "sideways_breakout":
        amount_to_prev = safe(features.get("setup_amount_to_prev6"), 1.0)
        range_6 = safe(features.get("setup_range_6"), 0.12)
        score += capped((amount_to_prev - 1.2) * 12, 0, 18)
        score += capped((0.12 - range_6) * 120, 0, 10)
        reasons.append("range_breakout")
    elif setup == "contracting_pullback_bullish":
        contract_ratio = safe(features.get("setup_amount_contract_ratio"), 0.82)
        drawdown = safe(features.get("setup_drawdown_from_peak"), -0.08)
        bull_body = safe(features.get("setup_bull_body"), 0.01)
        score += capped((0.82 - contract_ratio) * 35, 0, 12)
        score += capped(10 - abs(abs(drawdown) - 0.08) * 120, -4, 10)
        score += capped(bull_body * 180, 0, 12)
        reasons.append("contracting_pullback_bullish")
    elif setup == "old_volume_reactivation":
        amount_to_20 = safe(features.get("setup_amount_to_20"), 1.0)
        breakout_10 = safe(features.get("setup_breakout_10"), 0.0)
        score += capped((amount_to_20 - 1.8) * 7, 0, 20)
        score += capped(breakout_10 * 80, -5, 12)
        reasons.append("old_volume_reactivation")
    elif setup == "pullback_stabilization":
        drawdown = safe(features.get("setup_drawdown_from_peak"), -0.08)
        amount_ratio = safe(features.get("setup_amount_ma3_to_ma10"), 0.82)
        ideal_drawdown_bonus = 10 - abs(abs(drawdown) - 0.08) * 120
        score += capped(ideal_drawdown_bonus, -5, 10)
        score += capped((0.82 - amount_ratio) * 25, 0, 10)
        reasons.append("pullback_stable")

    return round(score, 4), reasons


def build_candidate(event: pd.Series, setup: str, idx: int, features: dict, df: pd.DataFrame) -> dict | None:
    buy_idx = idx + 1
    if buy_idx >= len(df):
        return None
    trigger = df.iloc[idx]
    buy = df.iloc[buy_idx]
    score, reasons = score_candidate(setup, event, features)
    return {
        "event_id": int(event["event_id"]),
        "ts_code": event["ts_code"],
        "code": event["code"],
        "name": event["name"],
        "entry_date": event["entry_date"],
        "entry_price": float(event["entry_price"]),
        "entry_month": event["entry_month"],
        "price_bucket": event["price_bucket"],
        "setup": setup,
        "score": score,
        "score_reasons": ",".join(reasons),
        "review_date": trigger["trade_date"],
        "trigger_age_trading_days": idx - int(event["signal_idx"]),
        "trigger_close": round_num(trigger["close"]),
        "trigger_pct_chg": round_num(trigger["pct_chg"] / 100) if pd.notna(trigger["pct_chg"]) else None,
        "trigger_volume_ratio": round_num(safe(trigger.get("volume_ratio"))),
        "buy_idx": buy_idx,
        "buy_date": buy["trade_date"],
        "buy_open": round_num(buy["open"]),
        "buy_gap_from_trigger_close": ret_from_adj(trigger["adj_close"], buy["adj_open"]),
        **{key: round_num(value) for key, value in features.items()},
    }


def generate_candidates(events: pd.DataFrame, markets: dict) -> tuple[pd.DataFrame, list[dict]]:
    rows = []
    current_rows = []
    for _, event in events.iterrows():
        market = markets.get(event["ts_code"])
        if market is None:
            continue
        df = prepare_frame(market.frame)
        signal_idx = market.by_date.get(str(event["entry_date"]))
        if signal_idx is None:
            continue
        event = event.copy()
        event["signal_idx"] = signal_idx
        latest_idx = len(df) - 1

        for setup_name, detector, max_age, _desc in SETUPS:
            end_idx = latest_idx - 1
            if max_age is not None:
                end_idx = min(end_idx, signal_idx + max_age)
            for idx in range(signal_idx + 1, end_idx + 1):
                passed, features = detector(df, signal_idx, idx)
                if not passed:
                    continue
                candidate = build_candidate(event, setup_name, idx, features, df)
                if candidate is not None:
                    rows.append(candidate)

        # Latest review candidates do not require a future buy day; useful for today's plan.
        latest_event = event.copy()
        for setup_name, detector, max_age, _desc in SETUPS:
            if max_age is not None and latest_idx > signal_idx + max_age:
                continue
            passed, features = detector(df, signal_idx, latest_idx)
            if passed:
                score, reasons = score_candidate(setup_name, latest_event, features)
                latest = df.iloc[latest_idx]
                current_rows.append(
                    {
                        "event_id": int(event["event_id"]),
                        "ts_code": event["ts_code"],
                        "name": event["name"],
                        "entry_date": event["entry_date"],
                        "entry_price": float(event["entry_price"]),
                        "setup": setup_name,
                        "score": score,
                        "score_reasons": ",".join(reasons),
                        "review_date": latest["trade_date"],
                        "trigger_age_trading_days": latest_idx - signal_idx,
                        "trigger_close": round_num(latest["close"]),
                        "trigger_pct_chg": round_num(latest["pct_chg"] / 100) if pd.notna(latest["pct_chg"]) else None,
                        "trigger_volume_ratio": round_num(safe(latest.get("volume_ratio"))),
                        **{key: round_num(value) for key, value in features.items()},
                    }
                )
    return pd.DataFrame(rows), current_rows


def fixed_horizon_and_decision(candidate: pd.Series, markets: dict, horizon: int) -> dict:
    market = markets[candidate["ts_code"]]
    df = prepare_frame(market.frame)
    buy_idx = int(candidate["buy_idx"])
    buy = df.iloc[buy_idx]
    buy_adj_open = buy["adj_open"]
    prefix = f"t{horizon}"
    result = {
        f"fixed_{prefix}_ret": None,
        f"fixed_{prefix}_exit_date": None,
        f"decision_{prefix}_ret": None,
        f"decision_{prefix}_exit_date": None,
        f"decision_{prefix}_reason": None,
    }
    exit_idx = buy_idx + horizon
    if exit_idx >= len(df):
        return result
    exit_bar = df.iloc[exit_idx]
    horizon_ret = ret_from_adj(buy_adj_open, exit_bar["adj_close"])
    result[f"fixed_{prefix}_ret"] = horizon_ret
    result[f"fixed_{prefix}_exit_date"] = exit_bar["trade_date"]
    if horizon_ret is None:
        return result
    if horizon_ret >= 0.03:
        result[f"decision_{prefix}_ret"] = horizon_ret
        result[f"decision_{prefix}_exit_date"] = exit_bar["trade_date"]
        result[f"decision_{prefix}_reason"] = f"sell_{prefix}_take_profit_ge3"
        return result
    if horizon_ret <= -0.03:
        result[f"decision_{prefix}_ret"] = horizon_ret
        result[f"decision_{prefix}_exit_date"] = exit_bar["trade_date"]
        result[f"decision_{prefix}_reason"] = f"sell_{prefix}_stop_le_neg3"
        return result

    end_idx = buy_idx + 5
    if end_idx >= len(df):
        return result
    end = df.iloc[end_idx]
    result[f"decision_{prefix}_ret"] = ret_from_adj(buy_adj_open, end["adj_close"])
    result[f"decision_{prefix}_exit_date"] = end["trade_date"]
    result[f"decision_{prefix}_reason"] = f"hold_middle_to_t5_after_{prefix}"
    return result


def select_daily_picks(candidates: pd.DataFrame, markets: dict, active_horizon: int) -> pd.DataFrame:
    if candidates.empty:
        return candidates.copy()
    picks = []
    active_until: dict[str, str] = {}
    for review_date, group in candidates.sort_values(["review_date", "score"], ascending=[True, False]).groupby("review_date"):
        active_until = {code: date for code, date in active_until.items() if str(date) > str(review_date)}
        ranked = group.sort_values(["score", "setup", "ts_code"], ascending=[False, True, True])
        selected = None
        for _, row in ranked.iterrows():
            if row["ts_code"] in active_until:
                continue
            selected = row.copy()
            break
        if selected is None:
            continue
        selected["active_horizon"] = f"T+{active_horizon}"
        for horizon in (1, 2):
            exit_result = fixed_horizon_and_decision(selected, markets, horizon)
            for key, value in exit_result.items():
                selected[key] = value
        active_exit_key = f"fixed_t{active_horizon}_exit_date"
        if selected.get(active_exit_key):
            active_until[selected["ts_code"]] = selected[active_exit_key]
        picks.append(selected.to_dict())
    return pd.DataFrame(picks)


def group_stats(df: pd.DataFrame, group_col: str, metric: str) -> list[dict]:
    rows = []
    if df.empty:
        return rows
    for key, group in df.groupby(group_col, dropna=False):
        rows.append({"key": key, **summarize(group[metric].dropna())})
    return sorted(rows, key=lambda row: (row["median"] is not None, row["median"]), reverse=True)


def metric_summary(df: pd.DataFrame, metric: str) -> dict:
    return summarize(df[metric].dropna()) if metric in df else summarize([])


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest daily after-close PGC review strategy.")
    parser.add_argument("--events", default=str(RAW_EVENTS_PATH), help="Path to pgc_raw_events.json.")
    parser.add_argument("--market-dir", default=str(MARKET_DIR), help="Cached Tushare market data directory.")
    parser.add_argument("--candidates-csv", default=str(CANDIDATES_CSV), help="Output all candidates CSV.")
    parser.add_argument("--picks-csv", default=str(PICKS_CSV), help="Output T+1 daily picks CSV.")
    parser.add_argument("--picks-t2-csv", default=str(PICKS_T2_CSV), help="Output T+2 comparison daily picks CSV.")
    parser.add_argument("--out-json", default=str(JSON_OUT), help="Output JSON summary.")
    parser.add_argument("--out-md", default=str(MD_OUT), help="Output Markdown report.")
    parser.add_argument("--min-entry-price", type=float, default=10.0, help="Minimum original entry_price for daily final picks.")
    args = parser.parse_args()

    events = load_events(Path(args.events))
    markets = {ts_code: load_market(ts_code, Path(args.market_dir)) for ts_code in sorted(events["ts_code"].dropna().unique())}
    candidates, current_candidates = generate_candidates(events, markets)
    eligible_candidates = candidates[candidates["entry_price"] >= args.min_entry_price].copy() if not candidates.empty else candidates
    picks_t1 = select_daily_picks(eligible_candidates, markets, active_horizon=1)
    picks_t2 = select_daily_picks(eligible_candidates, markets, active_horizon=2)

    Path(args.candidates_csv).parent.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(args.candidates_csv, index=False)
    picks_t1.to_csv(args.picks_csv, index=False)
    picks_t2.to_csv(args.picks_t2_csv, index=False)

    latest_review_date = None
    current_pick = None
    if current_candidates:
        latest_review_date = max(row["review_date"] for row in current_candidates)
        latest_candidates = [
            row
            for row in current_candidates
            if row["review_date"] == latest_review_date and row["entry_price"] >= args.min_entry_price
        ]
        latest_candidates = sorted(latest_candidates, key=lambda row: row["score"], reverse=True)
        current_pick = latest_candidates[0] if latest_candidates else None

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "events": len(events),
        "candidates": len(candidates),
        "eligible_candidates": len(eligible_candidates),
        "daily_picks_t1": len(picks_t1),
        "daily_picks_t2": len(picks_t2),
        "candidate_by_setup": candidates["setup"].value_counts().to_dict() if not candidates.empty else {},
        "eligible_candidate_by_setup": eligible_candidates["setup"].value_counts().to_dict() if not eligible_candidates.empty else {},
        "pick_by_setup_t1": picks_t1["setup"].value_counts().to_dict() if not picks_t1.empty else {},
        "pick_by_setup_t2": picks_t2["setup"].value_counts().to_dict() if not picks_t2.empty else {},
        "fixed_t1": metric_summary(picks_t1, "fixed_t1_ret"),
        "decision_t1": metric_summary(picks_t1, "decision_t1_ret"),
        "fixed_t1_by_setup": group_stats(picks_t1, "setup", "fixed_t1_ret") if "fixed_t1_ret" in picks_t1 else [],
        "decision_t1_by_setup": group_stats(picks_t1, "setup", "decision_t1_ret") if "decision_t1_ret" in picks_t1 else [],
        "decision_t1_reason_counts": picks_t1["decision_t1_reason"].value_counts().to_dict() if "decision_t1_reason" in picks_t1 else {},
        "fixed_t2": metric_summary(picks_t2, "fixed_t2_ret"),
        "decision_t2": metric_summary(picks_t2, "decision_t2_ret"),
        "fixed_t2_by_setup": group_stats(picks_t2, "setup", "fixed_t2_ret") if "fixed_t2_ret" in picks_t2 else [],
        "decision_t2_by_setup": group_stats(picks_t2, "setup", "decision_t2_ret") if "decision_t2_ret" in picks_t2 else [],
        "decision_t2_reason_counts": picks_t2["decision_t2_reason"].value_counts().to_dict() if "decision_t2_reason" in picks_t2 else {},
        "latest_review_date": latest_review_date,
        "current_pick": current_pick,
        "assumptions": {
            "review": "Select after review_date close.",
            "buy": "Buy next trading day open.",
            "t1": "T+1 means the first trading day after buy day, sold or reviewed at close.",
            "t2": "T+2 means the second trading day after buy day, sold or reviewed at close.",
            "position_overlap": "One new pick per review day is allowed; the same symbol is not picked while its prior fixed-horizon position is active.",
            "min_entry_price": args.min_entry_price,
        },
    }
    Path(args.out_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    current_pick_text = "无"
    if current_pick:
        current_pick_text = (
            f"{current_pick['ts_code']} {current_pick['name']}，买点 `{current_pick['setup']}`，"
            f"评分 {current_pick['score']}，复盘日 {current_pick['review_date']}"
        )

    report = f"""# PGC每日收盘复盘选一只策略

> 流程假设：复盘日 S 收盘后筛选最符合条件的一只股票；S+1 开盘买入；买入日记为 T；T+1 表示买入后第 1 个交易日尾盘。本报告只使用复盘日收盘前可见信息打分，买入收益从次日开盘开始计算。

## 执行规则

1. 每天收盘后扫描 PGC 观察池。
2. 候选买点包括：缩量回调后阳线确认、缩量回调企稳、横盘震荡突破、老票放量再激活。
3. 默认只允许 `entry_price >= {args.min_entry_price:g}` 进入每日最终买入池；低价候选保留在候选明细中，但不参与最终选一只。
4. 次一交易日开盘买入。
5. T+1 主回测给两个评估口径：
   - `fixed_t1`：无条件 T+1 收盘卖出。
   - `decision_t1`：若 T+1 收益 >= 3% 则止盈卖出；若 <= -3% 则控制亏损卖出；中间态继续持有到 T+5 收盘。
6. 保留 T+2 作为对照：同样按 T+2 持仓占用期重新选股，不混用 T+1 的入选序列。

## 覆盖

- 原始入池事件：{summary["events"]}
- 历史候选买点：{summary["candidates"]}
- 满足最终价格过滤的候选买点：{summary["eligible_candidates"]}
- T+1 每日最终入选：{summary["daily_picks_t1"]}
- T+2 对照每日最终入选：{summary["daily_picks_t2"]}
- 候选买点分布：{json.dumps(summary["candidate_by_setup"], ensure_ascii=False)}
- 价格过滤后候选分布：{json.dumps(summary["eligible_candidate_by_setup"], ensure_ascii=False)}
- T+1 入选买点分布：{json.dumps(summary["pick_by_setup_t1"], ensure_ascii=False)}
- T+2 入选买点分布：{json.dumps(summary["pick_by_setup_t2"], ensure_ascii=False)}

## 回测结果

### T+1 固定卖出

{md_table(["指标", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], [{"metric": "fixed_t1", **summary["fixed_t1"]}], stat_row)}

### T+1 判断后可延长

{md_table(["指标", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], [{"metric": "decision_t1", **summary["decision_t1"]}], stat_row)}

### T+1 固定卖出，按买点类型

{md_table(["买点", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], summary["fixed_t1_by_setup"], stat_row)}

### T+1 判断卖出，按买点类型

{md_table(["买点", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], summary["decision_t1_by_setup"], stat_row)}

### T+2 固定卖出对照

{md_table(["指标", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], [{"metric": "fixed_t2", **summary["fixed_t2"]}], stat_row)}

### T+2 判断后可延长对照

{md_table(["指标", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], [{"metric": "decision_t2", **summary["decision_t2"]}], stat_row)}

### T+2 固定卖出对照，按买点类型

{md_table(["买点", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], summary["fixed_t2_by_setup"], stat_row)}

### T+2 判断卖出对照，按买点类型

{md_table(["买点", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], summary["decision_t2_by_setup"], stat_row)}

## 当前最新复盘候选

最新复盘日：{summary["latest_review_date"]}

当前最高分候选：{current_pick_text}

完整候选和历史入选明细：

- `{args.candidates_csv}`
- `{args.picks_csv}`
- `{args.picks_t2_csv}`

## 初步解读

- 这比“入池即买”更接近你的短线思路：先观察，等二次结构确认。
- 如果 `fixed_t1` 明显弱于 `decision_t1`，说明 T+1 不宜机械卖出，需要根据强弱延长。
- 如果按买点类型分化明显，下一步应调整评分权重，让每日唯一名额更多落到表现更好的买点。
"""
    Path(args.out_md).write_text(report, encoding="utf-8")
    print(
        json.dumps(
            {
                "candidates": len(candidates),
                "picks_t1": len(picks_t1),
                "picks_t2": len(picks_t2),
                "out_md": args.out_md,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
