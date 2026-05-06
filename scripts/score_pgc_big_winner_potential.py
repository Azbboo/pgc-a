#!/usr/bin/env python3
"""Score PGC pool entries for post-entry big-winner potential.

The score is intentionally simple and auditable. It is not a fitted model:
weights come from the factor study around 20-day MFE >= 30%, then are kept
coarse to avoid turning a small sample into a curve-fit.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from analyze_pgc_event_backtest import pct, round_num


ROOT = Path(__file__).resolve().parents[1]
EVENT_BACKTEST_CSV = ROOT / "data" / "pgc_event_backtest.csv"
CURRENT_CANDIDATES_CSV = ROOT / "data" / "contracting_pullback_current_candidates.csv"
CPB_SIGNALS_CSV = ROOT / "data" / "contracting_pullback_best_signals.csv"
HIST_SCORE_CSV = ROOT / "data" / "pgc_big_winner_scores.csv"
CURRENT_SCORE_CSV = ROOT / "data" / "pgc_big_winner_current_scores.csv"
JSON_OUT = ROOT / "reports" / "pgc_big_winner_score.json"
MD_OUT = ROOT / "reports" / "pgc_big_winner_score.md"


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


def score_big_winner_potential(row: pd.Series) -> dict:
    """Return a 0-100 score and component notes.

    Components:
    - core 45: price band plus intraday position on the original pool-entry day.
    - liquidity 25: market-cap band plus signal-day volume ratio.
    - trend 15: 20-day range position and MA20 relationship.
    - execution 15: next-open gap after pool entry.
    """

    price = safe(row.get("entry_price"))
    pos = safe(row.get("entry_price_pos_in_day"))
    total_mv = safe(row.get("buy_total_mv"))
    volume_ratio = safe(row.get("signal_volume_ratio"))
    range_pos = safe(row.get("range_pos_20"))
    dist_ma20 = safe(row.get("dist_ma20"))
    buy_gap = safe(row.get("buy_gap_from_entry"))

    score = 0
    core_score = 0
    liquidity_score = 0
    trend_score = 0
    execution_score = 0
    notes: list[str] = []

    if price is not None and pos is not None and 10 <= price <= 100 and pos <= 0.44:
        core_score = 45
        notes.append("核心强:价格10-100且入池价低半区")
    elif price is not None and pos is not None and 10 <= price <= 100 and pos <= 0.70:
        core_score = 25
        notes.append("价格10-100但入池价中位")
    elif price is not None and 10 <= price <= 100:
        core_score = 12
        notes.append("价格合格但入池价偏高")
    elif price is not None and 5 <= price < 10:
        core_score = 4
        notes.append("低价扣分")
    elif price is not None and price > 100 and pos is not None and pos <= 0.70:
        core_score = 10
        notes.append("高价股扣分")
    else:
        notes.append("价格/日内位置不理想")

    if total_mv is not None and volume_ratio is not None:
        in_mv = 300000 <= total_mv <= 1500000
        near_mv = (150000 <= total_mv < 300000) or (1500000 < total_mv <= 3000000)
        in_volume = 1 <= volume_ratio <= 5
        near_volume = (0.7 <= volume_ratio < 1) or (5 < volume_ratio <= 7)

        if in_mv and in_volume:
            liquidity_score = 25
            notes.append("市值30-150亿且量比温和")
        elif near_mv and in_volume:
            liquidity_score = 15
            notes.append("市值邻近区间且量比温和")
        elif in_mv and near_volume:
            liquidity_score = 12
            notes.append("市值合格但量比边缘")
        elif in_volume:
            liquidity_score = 8
            notes.append("量比温和但市值不在优选")
        else:
            notes.append("市值/量比不理想")

    if range_pos is not None and dist_ma20 is not None:
        if 0.55 <= range_pos <= 0.95 and dist_ma20 > 0:
            trend_score = 15
            notes.append("趋势中高位且站上MA20")
        elif 0.40 <= range_pos < 0.55:
            trend_score = 5
            notes.append("趋势位置中低")
        elif range_pos > 0.95 and dist_ma20 > 0:
            trend_score = 5
            notes.append("趋势过高")
        else:
            notes.append("趋势不占优")

    if buy_gap is not None:
        if buy_gap <= 0.03:
            execution_score = 15
            notes.append("入池次日不追高")
        elif buy_gap <= 0.06:
            execution_score = 5
            notes.append("入池次日小追高")
        else:
            notes.append("入池次日追高")

    score = min(core_score + liquidity_score + trend_score + execution_score, 100)
    return {
        "bigwin_score": score,
        "core_score": core_score,
        "liquidity_score": liquidity_score,
        "trend_score": trend_score,
        "execution_score": execution_score,
        "bigwin_grade": grade(score),
        "score_notes": "；".join(notes),
    }


def grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 75:
        return "B+"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def score_frame(df: pd.DataFrame) -> pd.DataFrame:
    scored = df.copy()
    score_cols = scored.apply(score_big_winner_potential, axis=1, result_type="expand")
    return pd.concat([scored, score_cols], axis=1)


def summarize_bins(scored: pd.DataFrame) -> list[dict]:
    valid = scored[scored["next_open_mfe_20d"].notna()].copy()
    valid["bigwin_hit"] = valid["next_open_mfe_20d"] >= 0.30
    bins = [
        ("85-100", 85, 101),
        ("75-84", 75, 85),
        ("65-74", 65, 75),
        ("50-64", 50, 65),
        ("0-49", 0, 50),
    ]
    rows = []
    for name, low, high in bins:
        part = valid[(valid["bigwin_score"] >= low) & (valid["bigwin_score"] < high)]
        if part.empty:
            continue
        rows.append(
            {
                "score_bin": name,
                "n": len(part),
                "hit": int(part["bigwin_hit"].sum()),
                "hit_rate": round_num(part["bigwin_hit"].mean()),
                "mfe20_median": round_num(part["next_open_mfe_20d"].median()),
                "ret20_median": round_num(part["next_open_ret_20d"].median()),
            }
        )
    return rows


def summarize_thresholds(scored: pd.DataFrame) -> list[dict]:
    valid = scored[scored["next_open_mfe_20d"].notna()].copy()
    valid["bigwin_hit"] = valid["next_open_mfe_20d"] >= 0.30
    base_rate = valid["bigwin_hit"].mean()
    rows = []
    for threshold in [50, 60, 65, 70, 75, 80, 85, 90]:
        part = valid[valid["bigwin_score"] >= threshold]
        if part.empty:
            continue
        hit_rate = part["bigwin_hit"].mean()
        rows.append(
            {
                "threshold": threshold,
                "n": len(part),
                "hit": int(part["bigwin_hit"].sum()),
                "hit_rate": round_num(hit_rate),
                "lift": round_num(hit_rate / base_rate) if base_rate else None,
                "mfe20_median": round_num(part["next_open_mfe_20d"].median()),
                "ret20_median": round_num(part["next_open_ret_20d"].median()),
            }
        )
    return rows


def rule_stat(df: pd.DataFrame, mask: pd.Series, name: str) -> dict:
    valid = df[df["next_open_mfe_20d"].notna()].copy()
    base_rate = (valid["next_open_mfe_20d"] >= 0.30).mean()
    part = valid[mask.reindex(valid.index).fillna(False)]
    if part.empty:
        return {
            "rule": name,
            "n": 0,
            "hit": 0,
            "hit_rate": None,
            "lift": None,
            "mfe20_median": None,
            "ret20_median": None,
            "names": "",
        }
    hit = part["next_open_mfe_20d"] >= 0.30
    hit_rate = hit.mean()
    return {
        "rule": name,
        "n": len(part),
        "hit": int(hit.sum()),
        "hit_rate": round_num(hit_rate),
        "lift": round_num(hit_rate / base_rate) if base_rate else None,
        "mfe20_median": round_num(part["next_open_mfe_20d"].median()),
        "ret20_median": round_num(part["next_open_ret_20d"].median()),
        "names": ",".join(part["name"].head(12).astype(str).tolist()),
    }


def build_current_scores(scored: pd.DataFrame, current: pd.DataFrame, cpb: pd.DataFrame) -> pd.DataFrame:
    feature_cols = [
        "ts_code",
        "entry_date",
        "entry_price_pos_in_day",
        "buy_gap_from_entry",
        "pre_ret_20d",
        "pre_amount_ratio_5_20",
        "range_pos_20",
        "dist_ma20",
        "signal_turnover_rate",
        "signal_volume_ratio",
        "buy_total_mv",
        "buy_circ_mv",
        "bigwin_score",
        "core_score",
        "liquidity_score",
        "trend_score",
        "execution_score",
        "bigwin_grade",
        "score_notes",
    ]
    merged = current.merge(scored[feature_cols], on=["ts_code", "entry_date"], how="left")
    historical_scores = cpb["score"].dropna()
    if historical_scores.empty:
        merged["buy_point_percentile"] = None
    else:
        merged["buy_point_percentile"] = merged["score"].apply(lambda value: round_num((historical_scores <= value).mean()))
    merged["combined_score"] = (
        merged["bigwin_score"].fillna(0) * 0.70 + merged["buy_point_percentile"].fillna(0) * 100 * 0.30
    ).round(1)
    merged["combined_grade"] = merged["combined_score"].apply(grade)
    return merged.sort_values(["combined_score", "bigwin_score"], ascending=False)


def build_report(
    scored: pd.DataFrame,
    current_scored: pd.DataFrame,
    bin_rows: list[dict],
    threshold_rows: list[dict],
    rule_rows: list[dict],
) -> str:
    valid = scored[scored["next_open_mfe_20d"].notna()].copy()
    base_hit = (valid["next_open_mfe_20d"] >= 0.30).mean()
    as_of = ""
    if not current_scored.empty and "review_date" in current_scored:
        as_of = str(int(current_scored["review_date"].max()))

    current_headers = ["代码", "名称", "综合分", "潜力分", "买点分位", "评级", "入池位置", "市值亿", "量比", "备注"]
    current_table = md_table(
        current_headers,
        current_scored.to_dict("records"),
        lambda r: [
            r["ts_code"],
            r["name"],
            f'{r["combined_score"]:.1f}',
            f'{r["bigwin_score"]:.0f}',
            pct(r.get("buy_point_percentile")),
            r["combined_grade"],
            f'{safe(r.get("entry_price_pos_in_day"), 0):.3f}',
            f'{safe(r.get("buy_total_mv"), 0) / 10000:.1f}',
            f'{safe(r.get("signal_volume_ratio"), 0):.2f}',
            r.get("score_notes", ""),
        ],
    )
    bin_table = md_table(
        ["分数段", "样本", "命中", "命中率", "MFE20中位", "Ret20中位"],
        bin_rows,
        lambda r: [
            r["score_bin"],
            r["n"],
            r["hit"],
            pct(r["hit_rate"]),
            pct(r["mfe20_median"]),
            pct(r["ret20_median"]),
        ],
    )
    threshold_table = md_table(
        ["阈值", "样本", "命中", "命中率", "提升", "MFE20中位", "Ret20中位"],
        threshold_rows,
        lambda r: [
            f'>={r["threshold"]}',
            r["n"],
            r["hit"],
            pct(r["hit_rate"]),
            f'{safe(r["lift"], 0):.2f}x',
            pct(r["mfe20_median"]),
            pct(r["ret20_median"]),
        ],
    )
    rule_table = md_table(
        ["规则", "样本", "命中", "命中率", "提升", "MFE20中位", "Ret20中位"],
        rule_rows,
        lambda r: [
            r["rule"],
            r["n"],
            r["hit"],
            pct(r["hit_rate"]),
            f'{safe(r["lift"], 0):.2f}x',
            pct(r["mfe20_median"]),
            pct(r["ret20_median"]),
        ],
    )

    return "\n".join(
        [
            "# PGC大涨潜力评分",
            "",
            f"- 生成时间: {datetime.now(timezone.utc).isoformat()}",
            f"- 当前候选复盘日: {as_of}",
            f"- 历史有效样本: {len(valid)}",
            f"- 基准命中率: {pct(base_hit)}",
            "- 命中定义: 买入基准为入池次日开盘，20个交易日内最大浮盈 MFE >= 30%。",
            "- 注意: 这不是拟合模型，只是把当前发现的关键因子做成可审计评分。",
            "",
            "## 当前候选评分",
            "",
            current_table,
            "",
            "## 历史分数段校准",
            "",
            bin_table,
            "",
            "## 阈值校准",
            "",
            threshold_table,
            "",
            "## 当前候选相似规则",
            "",
            rule_table,
            "",
        ]
    )


def run(args: argparse.Namespace) -> None:
    scored = score_frame(pd.read_csv(args.event_backtest))
    scored.to_csv(args.hist_out, index=False)

    current = pd.read_csv(args.current_candidates)
    cpb = pd.read_csv(args.cpb_signals) if Path(args.cpb_signals).exists() else pd.DataFrame()
    current_scored = build_current_scores(scored, current, cpb)
    current_scored.to_csv(args.current_out, index=False)

    bin_rows = summarize_bins(scored)
    threshold_rows = summarize_thresholds(scored)
    rule_rows = [
        rule_stat(
            scored,
            scored["entry_price"].between(10, 100) & (scored["entry_price_pos_in_day"] <= 0.44),
            "价格10-100 & 入池价低半区",
        ),
        rule_stat(
            scored,
            scored["entry_price"].between(10, 100)
            & (scored["entry_price_pos_in_day"] <= 0.44)
            & scored["signal_volume_ratio"].between(1, 5)
            & scored["buy_total_mv"].between(150000, 3000000)
            & scored["range_pos_20"].between(0.55, 0.95)
            & (scored["dist_ma20"] > 0),
            "数据港相似:低半区+温和量比+邻近市值+趋势中高",
        ),
        rule_stat(
            scored,
            scored["entry_price"].between(10, 100)
            & (scored["entry_price_pos_in_day"] <= 0.70)
            & scored["buy_total_mv"].between(300000, 1500000)
            & scored["signal_volume_ratio"].between(1, 5)
            & scored["range_pos_20"].between(0.55, 0.95)
            & (scored["dist_ma20"] > 0)
            & (scored["buy_gap_from_entry"] <= 0.03),
            "值得买相似:中位以内+优选市值+温和量比+趋势",
        ),
    ]

    report = build_report(scored, current_scored, bin_rows, threshold_rows, rule_rows)
    Path(args.md_out).write_text(report, encoding="utf-8")
    Path(args.json_out).write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "score_outputs": {
                    "historical": str(args.hist_out),
                    "current": str(args.current_out),
                    "markdown": str(args.md_out),
                },
                "bin_summary": bin_rows,
                "threshold_summary": threshold_rows,
                "rule_summary": rule_rows,
                "current": current_scored.to_dict("records"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-backtest", type=Path, default=EVENT_BACKTEST_CSV)
    parser.add_argument("--current-candidates", type=Path, default=CURRENT_CANDIDATES_CSV)
    parser.add_argument("--cpb-signals", type=Path, default=CPB_SIGNALS_CSV)
    parser.add_argument("--hist-out", type=Path, default=HIST_SCORE_CSV)
    parser.add_argument("--current-out", type=Path, default=CURRENT_SCORE_CSV)
    parser.add_argument("--json-out", type=Path, default=JSON_OUT)
    parser.add_argument("--md-out", type=Path, default=MD_OUT)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
