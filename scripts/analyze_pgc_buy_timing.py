#!/usr/bin/env python3
"""Analyze when to buy after a PGC pool entry or CPB trigger."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from analyze_pgc_event_backtest import MARKET_DIR, load_market, pct, round_num


ROOT = Path(__file__).resolve().parents[1]
SCORES_CSV = ROOT / "data" / "pgc_big_winner_scores.csv"
CPB_SIGNALS_CSV = ROOT / "data" / "contracting_pullback_best_signals.csv"
CURRENT_SCORES_CSV = ROOT / "data" / "pgc_big_winner_current_scores.csv"
CURRENT_LEVELS_CSV = ROOT / "data" / "pgc_buy_timing_current_levels.csv"
JSON_OUT = ROOT / "reports" / "pgc_buy_timing_study.json"
MD_OUT = ROOT / "reports" / "pgc_buy_timing_study.md"


def md_table(headers: list[str], rows: list[dict], row_fn) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row_fn(row)) + " |")
    return "\n".join(lines)


def safe(value, default=None):
    return default if value is None or pd.isna(value) else value


def stat(series: pd.Series) -> dict:
    clean = series.dropna().astype(float)
    if clean.empty:
        return {
            "n": 0,
            "win_rate": None,
            "mean": None,
            "median": None,
            "p25": None,
            "p75": None,
            "min": None,
            "max": None,
        }
    return {
        "n": len(clean),
        "win_rate": round_num((clean > 0).mean()),
        "mean": round_num(clean.mean()),
        "median": round_num(clean.median()),
        "p25": round_num(clean.quantile(0.25)),
        "p75": round_num(clean.quantile(0.75)),
        "min": round_num(clean.min()),
        "max": round_num(clean.max()),
    }


def add_stat(prefix: str, series: pd.Series) -> dict:
    return {f"{prefix}_{key}": value for key, value in stat(series).items()}


def current_action(row: pd.Series) -> str:
    combined = safe(row.get("combined_score"), 0)
    age = safe(row.get("trigger_age_trading_days"), 0)
    bigwin = safe(row.get("bigwin_score"), 0)
    if combined >= 72 and age >= 6:
        return "优先:等确认价附近"
    if bigwin >= 75 and age >= 6:
        return "可做:只低吸不追"
    if combined >= 55 and age >= 6:
        return "交易型:轻仓确认"
    return "观察/放弃"


def attach_trigger_close(cpb: pd.DataFrame) -> pd.DataFrame:
    closes = []
    for _, row in cpb.iterrows():
        market = load_market(row["ts_code"], MARKET_DIR)
        close = None
        if market is not None:
            review_date = str(int(row["review_date"]))
            idx = market.by_date.get(review_date)
            if idx is not None:
                close = float(market.frame.iloc[idx]["close"])
        closes.append(close)
    out = cpb.copy()
    out["trigger_close"] = closes
    out["buy_gap_from_trigger_close"] = out["buy_open"] / out["trigger_close"] - 1
    return out


def summarize_next_open(scored: pd.DataFrame) -> list[dict]:
    groups = [
        ("全部入池次日买", scored["next_open_ret_5d"].notna()),
        ("潜力分>=75", scored["bigwin_score"] >= 75),
        ("潜力分>=80", scored["bigwin_score"] >= 80),
        ("潜力分>=85", scored["bigwin_score"] >= 85),
        ("潜力分<75", scored["bigwin_score"] < 75),
    ]
    rows = []
    for name, mask in groups:
        part = scored[mask]
        rows.append(
            {
                "group": name,
                **add_stat("t1", part["next_open_ret_1d"]),
                **add_stat("t5", part["next_open_ret_5d"]),
                **add_stat("t20", part["next_open_ret_20d"]),
                "mfe20_hit_rate": round_num((part["next_open_mfe_20d"] >= 0.30).mean()),
            }
        )
    return rows


def summarize_entry_gap(scored: pd.DataFrame) -> list[dict]:
    groups = [
        ("次日开盘<=入池价", scored["buy_gap_from_entry"] <= 0),
        ("入池价上方0-3%", scored["buy_gap_from_entry"].gt(0) & scored["buy_gap_from_entry"].le(0.03)),
        ("入池价上方3-6%", scored["buy_gap_from_entry"].gt(0.03) & scored["buy_gap_from_entry"].le(0.06)),
        ("入池价上方>6%", scored["buy_gap_from_entry"] > 0.06),
    ]
    rows = []
    for name, mask in groups:
        part = scored[mask]
        rows.append(
            {
                "group": name,
                **add_stat("t1", part["next_open_ret_1d"]),
                **add_stat("t5", part["next_open_ret_5d"]),
                "mfe20_hit_rate": round_num((part["next_open_mfe_20d"] >= 0.30).mean()),
            }
        )
    return rows


def summarize_cpb(cpb: pd.DataFrame) -> tuple[list[dict], list[dict], list[dict]]:
    cpb = cpb.copy()

    age_bins = [
        ("4-5天", cpb["trigger_age_trading_days"].between(4, 5)),
        ("6-8天", cpb["trigger_age_trading_days"].between(6, 8)),
        ("9-13天", cpb["trigger_age_trading_days"].between(9, 13)),
        ("14天以上", cpb["trigger_age_trading_days"] >= 14),
    ]
    age_rows = [
        {"group": name, **add_stat("decision", cpb.loc[mask, "decision_ret"]), **add_stat("ret5", cpb.loc[mask, "ret_5d"])}
        for name, mask in age_bins
    ]

    gap_bins = [
        ("低开>2%", cpb["buy_gap_from_trigger_close"] <= -0.02),
        ("-2%到平开", cpb["buy_gap_from_trigger_close"].gt(-0.02) & cpb["buy_gap_from_trigger_close"].le(0)),
        ("平开到+2%", cpb["buy_gap_from_trigger_close"].gt(0) & cpb["buy_gap_from_trigger_close"].le(0.02)),
        ("+2%到+4%", cpb["buy_gap_from_trigger_close"].gt(0.02) & cpb["buy_gap_from_trigger_close"].le(0.04)),
        ("高开>4%", cpb["buy_gap_from_trigger_close"] > 0.04),
    ]
    gap_rows = [
        {"group": name, **add_stat("decision", cpb.loc[mask, "decision_ret"]), **add_stat("ret5", cpb.loc[mask, "ret_5d"])}
        for name, mask in gap_bins
    ]

    combo_bins = [
        ("入池>=6天且开盘<=+2%", (cpb["trigger_age_trading_days"] >= 6) & (cpb["buy_gap_from_trigger_close"] <= 0.02)),
        ("入池>=6天且开盘<=+4%", (cpb["trigger_age_trading_days"] >= 6) & (cpb["buy_gap_from_trigger_close"] <= 0.04)),
        ("入池<6天", cpb["trigger_age_trading_days"] < 6),
    ]
    combo_rows = [
        {"group": name, **add_stat("decision", cpb.loc[mask, "decision_ret"]), **add_stat("ret5", cpb.loc[mask, "ret_5d"])}
        for name, mask in combo_bins
    ]
    return age_rows, gap_rows, combo_rows


def build_current_levels(current: pd.DataFrame) -> pd.DataFrame:
    out = current.copy()
    out["buy_zone_low"] = (out["trigger_close"] * 0.98).round(2)
    out["buy_zone_high"] = out["trigger_close"].round(2)
    out["max_chase_price"] = (out["trigger_close"] * 1.02).round(2)
    out["no_buy_above"] = (out["trigger_close"] * 1.04).round(2)
    out["action"] = out.apply(current_action, axis=1)
    cols = [
        "ts_code",
        "name",
        "review_date",
        "trigger_age_trading_days",
        "trigger_close",
        "buy_zone_low",
        "buy_zone_high",
        "max_chase_price",
        "no_buy_above",
        "combined_score",
        "bigwin_score",
        "buy_point_percentile",
        "action",
    ]
    return out[cols].sort_values(["combined_score", "bigwin_score"], ascending=False)


def stat_cells(row: dict, prefix: str) -> list[str]:
    return [
        row[f"{prefix}_n"],
        pct(row[f"{prefix}_win_rate"]),
        pct(row[f"{prefix}_mean"]),
        pct(row[f"{prefix}_median"]),
        pct(row[f"{prefix}_p25"]),
        pct(row[f"{prefix}_p75"]),
    ]


def build_report(
    next_rows: list[dict],
    entry_gap_rows: list[dict],
    age_rows: list[dict],
    cpb_gap_rows: list[dict],
    combo_rows: list[dict],
    current_levels: pd.DataFrame,
) -> str:
    current_table = md_table(
        ["代码", "名称", "动作", "触发价", "优先买区", "+2%上限", "+4%不追", "综合分", "潜力分"],
        current_levels.to_dict("records"),
        lambda r: [
            r["ts_code"],
            r["name"],
            r["action"],
            f'{r["trigger_close"]:.2f}',
            f'{r["buy_zone_low"]:.2f}-{r["buy_zone_high"]:.2f}',
            f'{r["max_chase_price"]:.2f}',
            f'{r["no_buy_above"]:.2f}',
            f'{r["combined_score"]:.1f}',
            f'{r["bigwin_score"]:.0f}',
        ],
    )

    next_table = md_table(
        ["分组", "T1样本", "T1胜率", "T1均值", "T1中位", "T5样本", "T5胜率", "T5均值", "T5中位", "MFE20>=30"],
        next_rows,
        lambda r: [
            r["group"],
            r["t1_n"],
            pct(r["t1_win_rate"]),
            pct(r["t1_mean"]),
            pct(r["t1_median"]),
            r["t5_n"],
            pct(r["t5_win_rate"]),
            pct(r["t5_mean"]),
            pct(r["t5_median"]),
            pct(r["mfe20_hit_rate"]),
        ],
    )

    entry_gap_table = md_table(
        ["次日开盘相对入池价", "T1样本", "T1胜率", "T1均值", "T1中位", "T5样本", "T5胜率", "T5均值", "T5中位", "MFE20>=30"],
        entry_gap_rows,
        lambda r: [
            r["group"],
            r["t1_n"],
            pct(r["t1_win_rate"]),
            pct(r["t1_mean"]),
            pct(r["t1_median"]),
            r["t5_n"],
            pct(r["t5_win_rate"]),
            pct(r["t5_mean"]),
            pct(r["t5_median"]),
            pct(r["mfe20_hit_rate"]),
        ],
    )

    cpb_age_table = md_table(
        ["CPB出现时间", "决策样本", "决策胜率", "决策均值", "决策中位", "T5样本", "T5胜率", "T5均值", "T5中位"],
        age_rows,
        lambda r: [r["group"], *stat_cells(r, "decision")[:4], *stat_cells(r, "ret5")[:4]],
    )

    cpb_gap_table = md_table(
        ["CPB次日开盘相对触发收盘", "决策样本", "决策胜率", "决策均值", "决策中位", "T5样本", "T5胜率", "T5均值", "T5中位"],
        cpb_gap_rows,
        lambda r: [r["group"], *stat_cells(r, "decision")[:4], *stat_cells(r, "ret5")[:4]],
    )

    combo_table = md_table(
        ["组合条件", "决策样本", "决策胜率", "决策均值", "决策中位", "T5样本", "T5胜率", "T5均值", "T5中位"],
        combo_rows,
        lambda r: [r["group"], *stat_cells(r, "decision")[:4], *stat_cells(r, "ret5")[:4]],
    )

    return "\n".join(
        [
            "# PGC买点时机研究",
            "",
            f"- 生成时间: {datetime.now(timezone.utc).isoformat()}",
            "- 买点目标: 把“大涨潜力票”转成可执行买点，避免入池后追高。",
            "- 当前结论: 入池次日直接买不是稳定优势；更稳的是入池后等待缩量回调、阳线确认，再在确认K线收盘价附近买。",
            "",
            "## 当前候选执行价位",
            "",
            current_table,
            "",
            "## 入池次日直接买",
            "",
            next_table,
            "",
            "## 入池次日追高过滤",
            "",
            entry_gap_table,
            "",
            "## CPB触发时间",
            "",
            cpb_age_table,
            "",
            "## CPB次日开盘位置",
            "",
            cpb_gap_table,
            "",
            "## 组合校准",
            "",
            combo_table,
            "",
            "## 执行规则",
            "",
            "1. 潜力分只是决定观察优先级，不直接买。",
            "2. 标准买点是入池后第6个交易日以后，出现缩量回调后的阳线确认。",
            "3. 信号出现后，次日优先买区是触发日收盘价的-2%到0%；高于触发收盘价2%以上不追。",
            "4. 若开盘高于触发收盘价2%-4%，只等盘中回落到确认价附近；高于4%视为错过。",
            "5. 入池不足6个交易日的CPB信号历史表现偏弱，除非是A档潜力票，否则不提前做。",
            "",
        ]
    )


def run(args: argparse.Namespace) -> None:
    scored = pd.read_csv(args.scores)
    cpb = attach_trigger_close(pd.read_csv(args.cpb_signals))
    cpb = cpb.merge(scored[["ts_code", "entry_date", "bigwin_score"]], on=["ts_code", "entry_date"], how="left")
    current = pd.read_csv(args.current_scores)

    next_rows = summarize_next_open(scored)
    entry_gap_rows = summarize_entry_gap(scored)
    age_rows, cpb_gap_rows, combo_rows = summarize_cpb(cpb)
    current_levels = build_current_levels(current)
    current_levels.to_csv(args.current_levels_out, index=False)

    report = build_report(next_rows, entry_gap_rows, age_rows, cpb_gap_rows, combo_rows, current_levels)
    Path(args.md_out).write_text(report, encoding="utf-8")
    Path(args.json_out).write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "outputs": {
                    "current_levels": str(args.current_levels_out),
                    "markdown": str(args.md_out),
                },
                "next_open": next_rows,
                "entry_gap": entry_gap_rows,
                "cpb_age": age_rows,
                "cpb_gap": cpb_gap_rows,
                "combo": combo_rows,
                "current_levels": current_levels.to_dict("records"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores", type=Path, default=SCORES_CSV)
    parser.add_argument("--cpb-signals", type=Path, default=CPB_SIGNALS_CSV)
    parser.add_argument("--current-scores", type=Path, default=CURRENT_SCORES_CSV)
    parser.add_argument("--current-levels-out", type=Path, default=CURRENT_LEVELS_CSV)
    parser.add_argument("--json-out", type=Path, default=JSON_OUT)
    parser.add_argument("--md-out", type=Path, default=MD_OUT)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
