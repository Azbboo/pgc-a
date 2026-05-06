#!/usr/bin/env python3
"""T+1 daily-one-pick backtest for the best contracting-pullback variant."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from analyze_pgc_event_backtest import pct, summarize


ROOT = Path(__file__).resolve().parents[1]
BEST_SIGNALS_CSV = ROOT / "data" / "contracting_pullback_best_signals.csv"
PICKS_CSV = ROOT / "data" / "contracting_pullback_best_daily_t1_picks.csv"
JSON_OUT = ROOT / "reports" / "contracting_pullback_best_t1_daily.json"
MD_OUT = ROOT / "reports" / "contracting_pullback_best_t1_daily.md"


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
        row["metric"],
        row["n"],
        pct(row["win_rate"]),
        pct(row["mean"]),
        pct(row["median"]),
        pct(row["p25"]),
        pct(row["p75"]),
        pct(row["min"]),
        pct(row["max"]),
    ]


def split_stats(df: pd.DataFrame, metric: str) -> dict:
    train = df[df["review_date"] <= "20260331"]
    test = df[df["review_date"] >= "20260401"]
    return {
        "all": summarize(df[metric].dropna()),
        "train_to_202603": summarize(train[metric].dropna()),
        "test_202604": summarize(test[metric].dropna()),
    }


def add_t1_decision(picks: pd.DataFrame) -> pd.DataFrame:
    picks = picks.copy()
    picks["fixed_t1_ret"] = picks["ret_1d"]
    picks["decision_t1_ret"] = pd.NA
    picks["decision_t1_reason"] = pd.NA

    for idx, row in picks.iterrows():
        ret_1d = row.get("ret_1d")
        if pd.isna(ret_1d):
            continue
        if ret_1d >= 0.03:
            picks.at[idx, "decision_t1_ret"] = ret_1d
            picks.at[idx, "decision_t1_reason"] = "sell_t1_take_profit_ge3"
        elif ret_1d <= -0.03:
            picks.at[idx, "decision_t1_ret"] = ret_1d
            picks.at[idx, "decision_t1_reason"] = "sell_t1_stop_le_neg3"
        elif pd.notna(row.get("ret_5d")):
            picks.at[idx, "decision_t1_ret"] = row["ret_5d"]
            picks.at[idx, "decision_t1_reason"] = "hold_middle_to_t5_after_t1"
    return picks


def main() -> int:
    signals = pd.read_csv(BEST_SIGNALS_CSV, dtype={"review_date": str, "buy_date": str, "entry_date": str})
    picks = (
        signals.sort_values(["review_date", "score", "ts_code"], ascending=[True, False, True])
        .groupby("review_date", as_index=False)
        .first()
    )
    picks = add_t1_decision(picks)
    PICKS_CSV.parent.mkdir(parents=True, exist_ok=True)
    picks.to_csv(PICKS_CSV, index=False)

    stats = {
        "fixed_t1": split_stats(picks, "fixed_t1_ret"),
        "decision_t1": split_stats(picks, "decision_t1_ret"),
        "fixed_t2_reference": split_stats(picks, "fixed_t2_ret"),
        "decision_t2_reference": split_stats(picks, "decision_ret"),
    }
    reason_counts = picks["decision_t1_reason"].value_counts(dropna=False).astype(int).to_dict()
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_signals": str(BEST_SIGNALS_CSV),
        "variant_id": picks["variant_id"].dropna().iloc[0] if not picks.empty else None,
        "signals": len(signals),
        "daily_picks": len(picks),
        "first_review_date": picks["review_date"].min() if not picks.empty else None,
        "last_review_date": picks["review_date"].max() if not picks.empty else None,
        "stats": stats,
        "decision_t1_reason_counts": {str(key): value for key, value in reason_counts.items()},
    }
    JSON_OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def stats_rows(metric_key: str) -> list[dict]:
        return [{"metric": split, **item} for split, item in stats[metric_key].items()]

    report = f"""# cpb_6157 最优参数 T+1 每日最多一只回测

> 参数来源：`contracting_pullback_best_signals.csv`，即 `cpb_6157` 最优缩量回调后一根阳线参数。每天同一复盘日只保留评分最高的一只，复盘日收盘确认，次一交易日开盘买入。

## 覆盖

- 原始最优参数信号：{summary["signals"]}
- 每日最多一只后的入选：{summary["daily_picks"]}
- 复盘日期范围：{summary["first_review_date"]} 至 {summary["last_review_date"]}
- T+1 判断规则：T+1 收益 >= 3% 止盈；<= -3% 止损；中间态延到 T+5 收盘。
- T+1 判断原因分布：{json.dumps(summary["decision_t1_reason_counts"], ensure_ascii=False)}

## T+1 固定卖出

{md_table(["区间", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], stats_rows("fixed_t1"), stat_row)}

## T+1 判断后可延长

{md_table(["区间", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], stats_rows("decision_t1"), stat_row)}

## T+2 对照：固定卖出

{md_table(["区间", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], stats_rows("fixed_t2_reference"), stat_row)}

## T+2 对照：判断后可延长

{md_table(["区间", "N", "胜率", "均值", "中位", "P25", "P75", "最差", "最好"], stats_rows("decision_t2_reference"), stat_row)}

## 明细

- `{PICKS_CSV}`
- `{JSON_OUT}`
"""
    MD_OUT.write_text(report, encoding="utf-8")
    print(json.dumps({"daily_picks": len(picks), "out_md": str(MD_OUT), "out_csv": str(PICKS_CSV)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
