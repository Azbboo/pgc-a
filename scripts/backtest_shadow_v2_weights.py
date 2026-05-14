#!/usr/bin/env python3
"""Backtest research-only shadow v2 weight variants."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from pgc_trading.config import Paths

from scripts.monitor_shadow_strategies import (
    DEFAULT_DATA_DIR,
    DEFAULT_DB_PATH,
    DEFAULT_REPORTS_DIR,
    SHADOW_BUCKETS,
    build_shadow_candidates,
    evaluate_candidates,
    walk_forward_date_pairs,
)


ARTIFACT_CONTRACT = "shadow_weight_optimization_v1"
OPTIMIZED_VARIANT = "shadow_v2_bucket_specific"
VARIANTS = ("current", OPTIMIZED_VARIANT)
TRADE_STATE_TABLES = ("strategy_versions", "trade_plans", "trades", "positions")
OUTPUT_COLUMNS = (
    "variant",
    "bucket",
    "signal_date",
    "planned_buy_date",
    "candidate_pool_size",
    "selection_rank_by_current_score",
    "ts_code",
    "name",
    "industry",
    "score",
    "variant_score",
    "entry_runup_pct",
    "ret3_pct",
    "ret5_pct",
    "ret10_pct",
    "dist20_high_pct",
    "dist5_high_pct",
    "close_pos20",
    "amount_to_ma10",
    "amount_to_ma20",
    "day_pct_chg",
    "next_open_gap_pct",
    "t1_close_ret_pct",
    "t1_high_ret_pct",
    "t1_low_ret_pct",
    "label_close_from_review_pct",
)


def main() -> int:
    args = parse_args()
    payload = generate_shadow_weight_optimization(
        db_path=args.db_path,
        review_date=args.date,
        reports_dir=args.reports_dir,
        data_dir=args.data_dir,
        walk_forward_days=args.walk_forward_days,
        apply=args.apply,
    )
    print_result(payload, compact=args.compact)
    return 0 if payload["ok"] else 1


def parse_args() -> argparse.Namespace:
    paths = Paths()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", "--as-of-date", dest="date", help="review date YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--db-path", type=Path, default=paths.db_path if paths.db_path else DEFAULT_DB_PATH)
    parser.add_argument("--reports-dir", type=Path, default=paths.reports_dir if paths.reports_dir else DEFAULT_REPORTS_DIR)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--walk-forward-days", type=int, default=20)
    parser.add_argument("--apply", action="store_true", help="write JSON/Markdown/CSV artifacts")
    parser.add_argument("--compact", action="store_true", help="print a compact status line")
    return parser.parse_args()


def generate_shadow_weight_optimization(
    *,
    db_path: Path,
    review_date: str | None,
    reports_dir: Path,
    data_dir: Path,
    walk_forward_days: int = 20,
    apply: bool = False,
) -> dict[str, Any]:
    as_of_date = normalize_date(review_date)
    before_counts = state_counts(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        date_pairs = walk_forward_date_pairs(conn, as_of_date, walk_forward_days)
        selection_rows, candidate_counts = build_variant_selection_rows(conn, date_pairs)
    after_counts = state_counts(db_path)

    summary = summarize_selection_rows(selection_rows)
    comparison = compare_variants(summary, baseline="current", candidate=OPTIMIZED_VARIANT)
    topline = build_topline(summary)
    payload = {
        "ok": before_counts == after_counts,
        "artifact_type": "shadow_weight_optimization",
        "optimization_contract": ARTIFACT_CONTRACT,
        "as_of_date": as_of_date,
        "review_date": as_of_date,
        "status": "success" if before_counts == after_counts else "blocked",
        "methodology": {
            "selection": "daily Top1 by variant score within each shadow bucket",
            "entry": "next trading day open",
            "exit_label": "same-day close/high labels; no paper/live order is written",
            "walk_forward_days": walk_forward_days,
            "variants": list(VARIANTS),
            "optimized_variant": OPTIMIZED_VARIANT,
        },
        "optimized_weight_policy": optimized_weight_policy(),
        "date_range": {
            "start_signal_date": date_pairs[0][0] if date_pairs else None,
            "latest_signal_date": date_pairs[-1][0] if date_pairs else None,
            "latest_outcome_date": date_pairs[-1][1] if date_pairs else None,
            "evaluable_signal_days": len(date_pairs),
        },
        "candidate_pool": {
            "total_candidates": sum(candidate_counts.values()),
            "counts_by_bucket_date": {
                f"{bucket}:{signal_date}": count
                for (bucket, signal_date), count in sorted(candidate_counts.items())
            },
        },
        "summary": summary,
        "comparison": comparison,
        "topline": topline,
        "safety": {
            "artifact_only": True,
            "active_params_mutated": False,
            "wrote_strategy_versions": False,
            "writes_trade_state": False,
            "writes_paper_live_behavior": False,
            "timer_mutated": False,
            "promotion_allowed": False,
            "trade_state_counts_unchanged": before_counts == after_counts,
            "changed_tables": [
                table for table in TRADE_STATE_TABLES if before_counts.get(table) != after_counts.get(table)
            ],
        },
        "outputs": {},
        "rows": selection_rows,
    }
    if apply:
        outputs = write_outputs(payload, reports_dir=reports_dir, data_dir=data_dir)
        payload["outputs"] = outputs
    return payload


def normalize_date(value: str | None) -> str:
    if not value:
        return datetime.now().strftime("%Y%m%d")
    return value.replace("-", "")


def build_variant_selection_rows(
    conn: sqlite3.Connection,
    date_pairs: list[tuple[str, str]],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], int]]:
    selection_rows: list[dict[str, Any]] = []
    candidate_counts: dict[tuple[str, str], int] = {}
    for signal_date, outcome_date in date_pairs:
        candidates = build_shadow_candidates(conn, signal_date)
        evaluated_rows = evaluate_candidates(conn, candidates, outcome_date)
        by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in evaluated_rows:
            by_bucket[str(row["bucket"])].append(row)
        for bucket in SHADOW_BUCKETS:
            bucket_rows = sorted(by_bucket.get(bucket, []), key=lambda item: (-safe_float(item.get("score")), item["ts_code"]))
            candidate_counts[(bucket, signal_date)] = len(bucket_rows)
            rank_by_code = {str(row["ts_code"]): idx + 1 for idx, row in enumerate(bucket_rows)}
            for variant in VARIANTS:
                best = select_top(bucket_rows, variant)
                if best is None:
                    continue
                item = compact_selection_row(
                    best,
                    variant=variant,
                    signal_date=signal_date,
                    outcome_date=outcome_date,
                    candidate_pool_size=len(bucket_rows),
                    rank_by_current_score=rank_by_code.get(str(best["ts_code"])),
                )
                selection_rows.append(item)
    return selection_rows, candidate_counts


def select_top(rows: list[dict[str, Any]], variant: str) -> dict[str, Any] | None:
    if not rows:
        return None
    scorer = variant_scorer(variant)
    return max(rows, key=lambda row: (scorer(row), str(row["ts_code"])))


def variant_scorer(variant: str) -> Callable[[Mapping[str, Any]], float]:
    if variant == "current":
        return current_score
    if variant == OPTIMIZED_VARIANT:
        return optimized_score
    raise ValueError(f"unknown variant: {variant}")


def current_score(row: Mapping[str, Any]) -> float:
    return safe_float(row.get("score"))


def optimized_score(row: Mapping[str, Any]) -> float:
    bucket = str(row.get("bucket") or "")
    score = current_score(row)
    if bucket == "trend_extension_shadow":
        return score
    if bucket == "breakout_pressure_shadow":
        return score - breakout_overheat_penalty(row)
    if bucket == "low_price_momentum_shadow":
        return score - low_price_stability_penalty(row)
    return score


def breakout_overheat_penalty(row: Mapping[str, Any]) -> float:
    day = safe_float(row.get("day_pct_chg"))
    amount10 = safe_float(row.get("amount_to_ma10"))
    close_pos20 = safe_float(row.get("close_pos20"))
    ret5 = safe_float(row.get("ret5_pct"))
    dist5 = safe_float(row.get("dist5_high_pct"), default=-20.0)
    penalty = max(day - 4.0, 0.0) * 0.75
    penalty += max(amount10 - 1.8, 0.0) * 2.0
    penalty += max(close_pos20 - 0.94, 0.0) * 9.0
    penalty += max(ret5 - 28.0, 0.0) * 0.16
    if day >= 9.7:
        penalty += 6.0
    if day >= 6.0 and close_pos20 >= 0.985:
        penalty += 4.0
    if day >= 5.0 and dist5 >= -0.5:
        penalty += 2.0
    return penalty


def low_price_stability_penalty(row: Mapping[str, Any]) -> float:
    day = safe_float(row.get("day_pct_chg"))
    amount10 = safe_float(row.get("amount_to_ma10"))
    close_pos20 = safe_float(row.get("close_pos20"))
    dist5 = safe_float(row.get("dist5_high_pct"), default=-20.0)
    penalty = 0.0
    if day < -2.0:
        penalty += (-2.0 - day) * 0.9
    elif day > 5.0:
        penalty += (day - 5.0) * 1.25
    if amount10 < 0.7:
        penalty += (0.7 - amount10) * 3.0
    elif amount10 > 1.9:
        penalty += (amount10 - 1.9) * 4.0
    if close_pos20 < 0.78:
        penalty += (0.78 - close_pos20) * 12.0
    elif close_pos20 > 0.95:
        penalty += (close_pos20 - 0.95) * 18.0
    if dist5 > -0.5:
        penalty += (dist5 + 0.5) * 0.6
    elif dist5 < -8.0:
        penalty += (-8.0 - dist5) * 0.25
    return penalty


def compact_selection_row(
    row: Mapping[str, Any],
    *,
    variant: str,
    signal_date: str,
    outcome_date: str,
    candidate_pool_size: int,
    rank_by_current_score: int | None,
) -> dict[str, Any]:
    result = {
        "variant": variant,
        "bucket": row.get("bucket"),
        "signal_date": signal_date,
        "planned_buy_date": outcome_date,
        "candidate_pool_size": candidate_pool_size,
        "selection_rank_by_current_score": rank_by_current_score,
        "variant_score": round(variant_scorer(variant)(row), 4),
    }
    for key in OUTPUT_COLUMNS:
        if key not in result:
            result[key] = row.get(key)
    return result


def summarize_selection_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["variant"]), str(row["bucket"]))].append(row)
    summary: list[dict[str, Any]] = []
    for variant in VARIANTS:
        for bucket in SHADOW_BUCKETS:
            sample = sorted(grouped.get((variant, bucket), []), key=lambda row: str(row["signal_date"]))
            item: dict[str, Any] = {
                "variant": variant,
                "bucket": bucket,
                "days": len({str(row["signal_date"]) for row in sample}),
                "start_signal_date": sample[0]["signal_date"] if sample else None,
                "latest_signal_date": sample[-1]["signal_date"] if sample else None,
            }
            item.update(period_metrics(sample, "all"))
            item.update(period_metrics(sample[-10:], "last10"))
            item.update(period_metrics(sample[-5:], "last5"))
            summary.append(item)
    return summary


def period_metrics(rows: list[Mapping[str, Any]], label: str) -> dict[str, Any]:
    close_values = [safe_float(row.get("t1_close_ret_pct")) for row in rows if row.get("t1_close_ret_pct") is not None]
    high_values = [safe_float(row.get("t1_high_ret_pct")) for row in rows if row.get("t1_high_ret_pct") is not None]
    low_values = [safe_float(row.get("t1_low_ret_pct")) for row in rows if row.get("t1_low_ret_pct") is not None]
    prefix = f"{label}_"
    return {
        f"{prefix}n": len(close_values),
        f"{prefix}t1_close_mean_pct": round(mean(close_values), 2) if close_values else None,
        f"{prefix}t1_close_median_pct": round(median(close_values), 2) if close_values else None,
        f"{prefix}t1_close_win_rate_pct": round(sum(value > 0 for value in close_values) / len(close_values) * 100, 1)
        if close_values
        else None,
        f"{prefix}t1_high_mean_pct": round(mean(high_values), 2) if high_values else None,
        f"{prefix}t1_high_ge3_rate_pct": round(sum(value >= 3.0 for value in high_values) / len(high_values) * 100, 1)
        if high_values
        else None,
        f"{prefix}t1_low_mean_pct": round(mean(low_values), 2) if low_values else None,
        f"{prefix}worst_close_pct": round(min(close_values), 2) if close_values else None,
    }


def compare_variants(summary: list[dict[str, Any]], *, baseline: str, candidate: str) -> list[dict[str, Any]]:
    by_key = {(item["variant"], item["bucket"]): item for item in summary}
    comparison = []
    for bucket in SHADOW_BUCKETS:
        base = by_key.get((baseline, bucket), {})
        cand = by_key.get((candidate, bucket), {})
        comparison.append(
            {
                "bucket": bucket,
                "baseline_variant": baseline,
                "candidate_variant": candidate,
                "all_t1_close_mean_delta_pct": diff(cand, base, "all_t1_close_mean_pct"),
                "all_win_rate_delta_pct": diff(cand, base, "all_t1_close_win_rate_pct"),
                "last10_t1_close_mean_delta_pct": diff(cand, base, "last10_t1_close_mean_pct"),
                "last10_win_rate_delta_pct": diff(cand, base, "last10_t1_close_win_rate_pct"),
                "last5_t1_close_mean_delta_pct": diff(cand, base, "last5_t1_close_mean_pct"),
                "last5_win_rate_delta_pct": diff(cand, base, "last5_t1_close_win_rate_pct"),
            }
        )
    return comparison


def build_topline(summary: list[dict[str, Any]]) -> dict[str, Any]:
    by_key = {(item["variant"], item["bucket"]): item for item in summary}
    low_current = by_key.get(("current", "low_price_momentum_shadow"), {})
    low_v2 = by_key.get((OPTIMIZED_VARIANT, "low_price_momentum_shadow"), {})
    breakout_current = by_key.get(("current", "breakout_pressure_shadow"), {})
    breakout_v2 = by_key.get((OPTIMIZED_VARIANT, "breakout_pressure_shadow"), {})
    trend_current = by_key.get(("current", "trend_extension_shadow"), {})
    trend_v2 = by_key.get((OPTIMIZED_VARIANT, "trend_extension_shadow"), {})
    return {
        "recommendation": "use optimized variant as research-only shadow_v2; do not promote to paper/live without more observation",
        "low_price_last5_delta_pct": diff(low_v2, low_current, "last5_t1_close_mean_pct"),
        "low_price_all_delta_pct": diff(low_v2, low_current, "all_t1_close_mean_pct"),
        "breakout_last5_delta_pct": diff(breakout_v2, breakout_current, "last5_t1_close_mean_pct"),
        "trend_last5_delta_pct": diff(trend_v2, trend_current, "last5_t1_close_mean_pct"),
        "decision": {
            "trend_extension_shadow": "keep current score",
            "breakout_pressure_shadow": "add mild overheat penalty; keep watch-only",
            "low_price_momentum_shadow": "prefer stable digestion over hot high-close extension",
        },
    }


def diff(left: Mapping[str, Any], right: Mapping[str, Any], key: str) -> float | None:
    if left.get(key) is None or right.get(key) is None:
        return None
    return round(safe_float(left.get(key)) - safe_float(right.get(key)), 2)


def optimized_weight_policy() -> dict[str, Any]:
    return {
        "trend_extension_shadow": {
            "action": "unchanged",
            "reason": "recent Top1 was not the weak bucket; avoid broad defensive rerank",
        },
        "breakout_pressure_shadow": {
            "action": "current_score minus mild overheat penalty",
            "penalty_terms": {
                "day_pct_chg_above_4": 0.75,
                "amount_to_ma10_above_1_8": 2.0,
                "close_pos20_above_0_94": 9.0,
                "ret5_pct_above_28": 0.16,
                "limit_like_day_extra": 6.0,
                "strong_high_close_extra": 4.0,
                "near_5d_high_big_day_extra": 2.0,
            },
        },
        "low_price_momentum_shadow": {
            "action": "current_score minus stability penalty",
            "target_zone": {
                "day_pct_chg": "-2 to 5",
                "amount_to_ma10": "0.7 to 1.9",
                "close_pos20": "0.78 to 0.95",
                "dist5_high_pct": "-8 to -0.5",
            },
        },
    }


def write_outputs(payload: dict[str, Any], *, reports_dir: Path, data_dir: Path) -> dict[str, str]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    as_of_date = str(payload["as_of_date"])
    json_path = reports_dir / f"shadow_weight_optimization_{as_of_date}.json"
    md_path = reports_dir / f"shadow_weight_optimization_{as_of_date}.md"
    csv_path = data_dir / f"shadow_weight_optimization_{as_of_date}.csv"
    json_payload = {key: value for key, value in payload.items() if key != "outputs"}
    json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(json_payload), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows([{key: row.get(key) for key in OUTPUT_COLUMNS} for row in payload["rows"]])
    return {
        "json": str(json_path),
        "markdown": str(md_path),
        "csv": str(csv_path),
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        f"# Shadow Weight Optimization {payload['as_of_date']}",
        "",
        "Research-only artifact. No strategy version, paper order, live order, trade plan, trade, or position is written.",
        "",
        "## Topline",
        "",
    ]
    topline = payload.get("topline", {})
    lines.extend(
        [
            f"- Recommendation: {topline.get('recommendation')}",
            f"- Low-price last5 mean delta: {fmt(topline.get('low_price_last5_delta_pct'))} pct",
            f"- Breakout last5 mean delta: {fmt(topline.get('breakout_last5_delta_pct'))} pct",
            f"- Trend last5 mean delta: {fmt(topline.get('trend_last5_delta_pct'))} pct",
            "",
            "## Summary",
            "",
            "| variant | bucket | all mean | all win | last10 mean | last10 win | last5 mean | last5 win |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in payload.get("summary", []):
        lines.append(
            "| {variant} | {bucket} | {all_mean} | {all_win} | {last10_mean} | {last10_win} | {last5_mean} | {last5_win} |".format(
                variant=item.get("variant"),
                bucket=item.get("bucket"),
                all_mean=fmt(item.get("all_t1_close_mean_pct")),
                all_win=fmt(item.get("all_t1_close_win_rate_pct")),
                last10_mean=fmt(item.get("last10_t1_close_mean_pct")),
                last10_win=fmt(item.get("last10_t1_close_win_rate_pct")),
                last5_mean=fmt(item.get("last5_t1_close_mean_pct")),
                last5_win=fmt(item.get("last5_t1_close_win_rate_pct")),
            )
        )
    lines.extend(["", "## Comparison", ""])
    lines.extend(
        [
            "| bucket | all mean delta | all win delta | last10 mean delta | last5 mean delta | last5 win delta |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for item in payload.get("comparison", []):
        lines.append(
            "| {bucket} | {all_mean} | {all_win} | {last10_mean} | {last5_mean} | {last5_win} |".format(
                bucket=item.get("bucket"),
                all_mean=fmt(item.get("all_t1_close_mean_delta_pct")),
                all_win=fmt(item.get("all_win_rate_delta_pct")),
                last10_mean=fmt(item.get("last10_t1_close_mean_delta_pct")),
                last5_mean=fmt(item.get("last5_t1_close_mean_delta_pct")),
                last5_win=fmt(item.get("last5_win_rate_delta_pct")),
            )
        )
    return "\n".join(lines) + "\n"


def print_result(payload: Mapping[str, Any], *, compact: bool) -> None:
    if compact:
        topline = payload.get("topline", {})
        print(
            "shadow_weight_optimization="
            f"status={payload.get('status')} "
            f"variant={OPTIMIZED_VARIANT} "
            f"low_last5_delta={fmt(topline.get('low_price_last5_delta_pct'))} "
            f"breakout_last5_delta={fmt(topline.get('breakout_last5_delta_pct'))} "
            f"trend_last5_delta={fmt(topline.get('trend_last5_delta_pct'))} "
            f"csv={payload.get('outputs', {}).get('csv', 'dry-run')}"
        )
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def state_counts(db_path: Path) -> dict[str, int]:
    with sqlite3.connect(db_path) as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in TRADE_STATE_TABLES
        }


def safe_float(value: Any, *, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
