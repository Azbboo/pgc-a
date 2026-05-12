#!/usr/bin/env python3
"""Generate research-only shadow strategy monitoring artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "pgc_trading.db"
DEFAULT_REPORTS_DIR = ROOT / "reports"
DEFAULT_DATA_DIR = ROOT / "data"

SHADOW_BUCKETS = (
    "trend_extension_shadow",
    "breakout_pressure_shadow",
    "low_price_momentum_shadow",
)


@dataclass(frozen=True)
class ShadowCandidate:
    ts_code: str
    name: str
    industry: str
    entry_date: str
    entry_price: float
    review_date: str
    review_close: float
    bucket: str
    score: float
    entry_runup_pct: float | None
    ret3_pct: float | None
    ret5_pct: float | None
    ret10_pct: float | None
    dist20_high_pct: float | None
    dist5_high_pct: float | None
    close_pos20: float | None
    amount_to_ma10: float | None
    amount_to_ma20: float | None
    day_pct_chg: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts_code": self.ts_code,
            "name": self.name,
            "industry": self.industry,
            "entry_date": self.entry_date,
            "entry_price": self.entry_price,
            "review_date": self.review_date,
            "review_close": self.review_close,
            "bucket": self.bucket,
            "score": self.score,
            "entry_runup_pct": self.entry_runup_pct,
            "ret3_pct": self.ret3_pct,
            "ret5_pct": self.ret5_pct,
            "ret10_pct": self.ret10_pct,
            "dist20_high_pct": self.dist20_high_pct,
            "dist5_high_pct": self.dist5_high_pct,
            "close_pos20": self.close_pos20,
            "amount_to_ma10": self.amount_to_ma10,
            "amount_to_ma20": self.amount_to_ma20,
            "day_pct_chg": self.day_pct_chg,
        }


def main() -> int:
    args = parse_args()
    report = generate_shadow_monitor(
        db_path=args.db_path,
        review_date=args.date,
        reports_dir=args.reports_dir,
        data_dir=args.data_dir,
    )
    print(json.dumps(report["outputs"], ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Outcome/review date YYYYMMDD.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    return parser.parse_args()


def generate_shadow_monitor(
    *,
    db_path: Path,
    review_date: str,
    reports_dir: Path,
    data_dir: Path,
) -> dict[str, Any]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        prior_date = pretrade_date(conn, review_date)
        next_date = next_trade_date(conn, review_date)
        prior_candidates = build_shadow_candidates(conn, prior_date)
        today_candidates = build_shadow_candidates(conn, review_date)
        outcome_rows = evaluate_candidates(conn, prior_candidates, review_date)
        coverage = actual_mover_coverage(conn, prior_candidates, prior_date, review_date)

    prior_top_by_bucket = top_by_bucket(prior_candidates)
    today_top_by_bucket = top_by_bucket(today_candidates)
    today_combined = combined_watchlist(today_candidates, limit=12)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "review_date": review_date,
        "prior_review_date": prior_date,
        "next_trade_date": next_date,
        "methodology": {
            "status": "research_only",
            "signal_timing": "shadow candidates are selected after review-date close",
            "execution_assumption": "next trading day open, no paper/live plan is written",
            "active_strategy_mutated": False,
            "score_version": "shadow_monitor_v1",
        },
        "prior_candidate_count": len(prior_candidates),
        "today_candidate_count": len(today_candidates),
        "prior_bucket_counts": dict(Counter(item.bucket for item in prior_candidates)),
        "today_bucket_counts": dict(Counter(item.bucket for item in today_candidates)),
        "prior_outcome_summary": summarize_outcomes(outcome_rows),
        "actual_mover_coverage": coverage,
        "prior_top_by_bucket": attach_outcomes(prior_top_by_bucket, outcome_rows),
        "today_top_by_bucket": [item.to_dict() for item in prior_order(today_top_by_bucket)],
        "today_combined_watchlist": [item.to_dict() for item in today_combined],
    }

    json_path = reports_dir / f"strategy_shadow_monitor_{review_date}.json"
    md_path = reports_dir / f"strategy_shadow_monitor_{review_date}.md"
    prior_csv_path = data_dir / f"strategy_shadow_outcome_{prior_date}_to_{review_date}.csv"
    watch_csv_path = data_dir / f"strategy_shadow_watchlist_{review_date}.csv"

    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    write_csv(prior_csv_path, outcome_rows)
    write_csv(watch_csv_path, [item.to_dict() for item in today_combined])

    summary["outputs"] = {
        "report": str(md_path),
        "json": str(json_path),
        "prior_outcome_csv": str(prior_csv_path),
        "watchlist_csv": str(watch_csv_path),
    }
    return summary


def pretrade_date(conn: sqlite3.Connection, date: str) -> str:
    row = conn.execute("SELECT pretrade_date FROM trade_calendar WHERE cal_date = ?", (date,)).fetchone()
    if row is None or not row["pretrade_date"]:
        raise ValueError(f"pretrade_date not found for {date}")
    return str(row["pretrade_date"])


def next_trade_date(conn: sqlite3.Connection, date: str) -> str | None:
    row = conn.execute(
        """
        SELECT min(cal_date) AS next_date
        FROM trade_calendar
        WHERE is_open = 1 AND cal_date > ?
        """,
        (date,),
    ).fetchone()
    return str(row["next_date"]) if row and row["next_date"] else None


def build_shadow_candidates(conn: sqlite3.Connection, review_date: str) -> list[ShadowCandidate]:
    sector_map = load_sector_map(conn, review_date)
    candidates: list[ShadowCandidate] = []
    for event in latest_events(conn, review_date):
        bars = market_bars(conn, event["ts_code"], review_date)
        metrics = calculate_metrics(bars, float(event["entry_price"]))
        if metrics is None:
            continue
        bucket = classify_bucket(float(event["entry_price"]), metrics)
        if bucket not in SHADOW_BUCKETS:
            continue
        score = score_candidate(bucket, metrics)
        candidates.append(
            ShadowCandidate(
                ts_code=str(event["ts_code"]),
                name=str(event["name"]),
                industry=sector_map.get(str(event["ts_code"]), ""),
                entry_date=str(event["entry_date"]),
                entry_price=round(float(event["entry_price"]), 4),
                review_date=review_date,
                review_close=round(float(metrics["close"]), 4),
                bucket=bucket,
                score=round(score, 4),
                entry_runup_pct=metrics["entry_runup_pct"],
                ret3_pct=metrics["ret3_pct"],
                ret5_pct=metrics["ret5_pct"],
                ret10_pct=metrics["ret10_pct"],
                dist20_high_pct=metrics["dist20_high_pct"],
                dist5_high_pct=metrics["dist5_high_pct"],
                close_pos20=metrics["close_pos20"],
                amount_to_ma10=metrics["amount_to_ma10"],
                amount_to_ma20=metrics["amount_to_ma20"],
                day_pct_chg=metrics["day_pct_chg"],
            )
        )
    return sorted(candidates, key=lambda item: (-item.score, item.ts_code))


def latest_events(conn: sqlite3.Connection, review_date: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM (
              SELECT re.*,
                     row_number() OVER (
                       PARTITION BY ts_code
                       ORDER BY entry_date DESC, id DESC
                     ) AS rn
              FROM raw_events re
              WHERE re.is_valid = 1
                AND re.entry_date <= ?
            )
            WHERE rn = 1
            ORDER BY ts_code
            """,
            (review_date,),
        )
    )


def market_bars(conn: sqlite3.Connection, ts_code: str, review_date: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT trade_date, open, high, low, close, amount
            FROM market_bars
            WHERE ts_code = ? AND trade_date <= ?
            ORDER BY trade_date
            """,
            (ts_code, review_date),
        )
    )


def load_sector_map(conn: sqlite3.Connection, review_date: str) -> dict[str, str]:
    run = conn.execute(
        """
        SELECT mrr.id
        FROM market_review_runs mrr
        WHERE mrr.as_of_date <= ?
          AND EXISTS (
            SELECT 1
            FROM sector_constituents sc
            WHERE sc.market_review_run_id = mrr.id
          )
        ORDER BY mrr.as_of_date DESC, mrr.id DESC
        LIMIT 1
        """,
        (review_date,),
    ).fetchone()
    if run is None:
        return {}
    return {
        str(row["ts_code"]): str(row["sector_name"])
        for row in conn.execute(
            "SELECT ts_code, sector_name FROM sector_constituents WHERE market_review_run_id = ?",
            (int(run["id"]),),
        )
    }


def calculate_metrics(bars: list[sqlite3.Row], entry_price: float) -> dict[str, float | None] | None:
    if len(bars) < 10:
        return None
    latest = bars[-1]
    close = to_float(latest["close"])
    amount = to_float(latest["amount"])
    if close is None or amount is None:
        return None

    last20 = bars[-20:]
    last5 = bars[-5:]
    high20 = max_number(row["high"] for row in last20)
    low20 = min_number(row["low"] for row in last20)
    high5 = max_number(row["high"] for row in last5)
    amount10 = average_number(row["amount"] for row in bars[-10:])
    amount20 = average_number(row["amount"] for row in bars[-20:])
    previous_close = to_float(bars[-2]["close"]) if len(bars) >= 2 else None
    close_pos20 = None
    if high20 is not None and low20 is not None and high20 > low20:
        close_pos20 = round((close - low20) / (high20 - low20), 4)
    return {
        "close": close,
        "entry_runup_pct": pct(entry_price, close),
        "ret3_pct": rolling_pct(bars, close, 3),
        "ret5_pct": rolling_pct(bars, close, 5),
        "ret10_pct": rolling_pct(bars, close, 10),
        "dist20_high_pct": pct(high20, close),
        "dist5_high_pct": pct(high5, close),
        "close_pos20": close_pos20,
        "amount_to_ma10": round(amount / amount10, 4) if amount10 else None,
        "amount_to_ma20": round(amount / amount20, 4) if amount20 else None,
        "day_pct_chg": pct(previous_close, close),
    }


def classify_bucket(entry_price: float, metrics: dict[str, float | None]) -> str | None:
    dist20 = metrics["dist20_high_pct"]
    amount10 = metrics["amount_to_ma10"]
    ret5 = metrics["ret5_pct"]
    runup = metrics["entry_runup_pct"]
    near20 = dist20 is not None and dist20 >= -12.0
    constructive_volume = amount10 is not None and amount10 >= 0.6
    no_severe_5d = ret5 is None or ret5 >= -8.0
    if entry_price < 10.0:
        if constructive_volume and no_severe_5d:
            return "low_price_momentum_shadow"
        return None
    if near20 and amount10 is not None and amount10 > 2.4:
        return "overheated_breakout_watch"
    if runup is not None and runup > 18.0 and near20 and constructive_volume and no_severe_5d:
        return "trend_extension_shadow"
    if near20 and constructive_volume and no_severe_5d:
        return "breakout_pressure_shadow"
    return None


def score_candidate(bucket: str, metrics: dict[str, float | None]) -> float:
    close_pos = metrics["close_pos20"] or 0.0
    ret5 = metrics["ret5_pct"] or 0.0
    ret10 = metrics["ret10_pct"] or 0.0
    runup = metrics["entry_runup_pct"] or 0.0
    amount10 = min(metrics["amount_to_ma10"] or 0.0, 2.2)
    dist20 = metrics["dist20_high_pct"] or -20.0
    if bucket == "trend_extension_shadow":
        return 100.0 + close_pos * 9.0 + min(max(runup, 0.0), 120.0) * 0.08 + ret5 * 0.12 + amount10 * 2.0 + dist20 * 0.08
    if bucket == "low_price_momentum_shadow":
        return 95.0 + close_pos * 8.0 + ret5 * 0.22 + ret10 * 0.08 + amount10 * 2.0 + dist20 * 0.05
    return 92.0 + close_pos * 8.0 + ret5 * 0.18 + amount10 * 2.2 + dist20 * 0.06


def evaluate_candidates(
    conn: sqlite3.Connection,
    candidates: list[ShadowCandidate],
    outcome_date: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        outcome = conn.execute(
            """
            SELECT open, high, low, close
            FROM market_bars
            WHERE ts_code = ? AND trade_date = ?
            """,
            (candidate.ts_code, outcome_date),
        ).fetchone()
        item = candidate.to_dict()
        item["outcome_date"] = outcome_date
        if outcome is None:
            item.update(
                {
                    "next_open_gap_pct": None,
                    "t1_close_ret_pct": None,
                    "t1_high_ret_pct": None,
                    "t1_low_ret_pct": None,
                }
            )
        else:
            open_price = to_float(outcome["open"])
            item.update(
                {
                    "outcome_open": open_price,
                    "outcome_high": to_float(outcome["high"]),
                    "outcome_low": to_float(outcome["low"]),
                    "outcome_close": to_float(outcome["close"]),
                    "next_open_gap_pct": pct(candidate.review_close, open_price),
                    "t1_close_ret_pct": pct(open_price, to_float(outcome["close"])),
                    "t1_high_ret_pct": pct(open_price, to_float(outcome["high"])),
                    "t1_low_ret_pct": pct(open_price, to_float(outcome["low"])),
                    "label_close_from_review_pct": pct(candidate.review_close, to_float(outcome["close"])),
                }
            )
        rows.append(item)
    return rows


def actual_mover_coverage(
    conn: sqlite3.Connection,
    candidates: list[ShadowCandidate],
    prior_date: str,
    outcome_date: str,
) -> dict[str, Any]:
    candidate_bucket_by_code: dict[str, str] = {candidate.ts_code: candidate.bucket for candidate in candidates}
    movers = []
    covered = Counter()
    for event in latest_events(conn, prior_date):
        prior = conn.execute(
            "SELECT close FROM market_bars WHERE ts_code = ? AND trade_date = ?",
            (event["ts_code"], prior_date),
        ).fetchone()
        outcome = conn.execute(
            "SELECT close FROM market_bars WHERE ts_code = ? AND trade_date = ?",
            (event["ts_code"], outcome_date),
        ).fetchone()
        if prior is None or outcome is None:
            continue
        ret = pct(prior["close"], outcome["close"])
        if ret is None or ret < 5.0:
            continue
        bucket = candidate_bucket_by_code.get(str(event["ts_code"]))
        if bucket:
            covered[bucket] += 1
        movers.append(
            {
                "ts_code": str(event["ts_code"]),
                "name": str(event["name"]),
                "label_close_from_prior_pct": ret,
                "covered_bucket": bucket,
            }
        )
    return {
        "actual_ge5_count": len(movers),
        "covered_ge5_count": sum(covered.values()),
        "coverage_pct": round(sum(covered.values()) / len(movers) * 100, 1) if movers else None,
        "covered_by_bucket": dict(covered),
        "uncovered": [item for item in movers if not item["covered_bucket"]],
    }


def summarize_outcomes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_bucket[str(row["bucket"])].append(row)
    summaries = []
    for bucket in sorted(by_bucket):
        sample = by_bucket[bucket]
        close_values = [float(row["t1_close_ret_pct"]) for row in sample if row.get("t1_close_ret_pct") is not None]
        high_values = [float(row["t1_high_ret_pct"]) for row in sample if row.get("t1_high_ret_pct") is not None]
        summaries.append(
            {
                "bucket": bucket,
                "n": len(sample),
                "t1_close_mean_pct": round(mean(close_values), 2) if close_values else None,
                "t1_close_median_pct": round(median(close_values), 2) if close_values else None,
                "t1_close_win_rate_pct": round(sum(value > 0 for value in close_values) / len(close_values) * 100, 1)
                if close_values
                else None,
                "t1_high_mean_pct": round(mean(high_values), 2) if high_values else None,
                "t1_high_ge3_rate_pct": round(sum(value >= 3 for value in high_values) / len(high_values) * 100, 1)
                if high_values
                else None,
            }
        )
    return summaries


def top_by_bucket(candidates: list[ShadowCandidate]) -> list[ShadowCandidate]:
    best: dict[str, ShadowCandidate] = {}
    for candidate in candidates:
        if candidate.bucket not in best or candidate.score > best[candidate.bucket].score:
            best[candidate.bucket] = candidate
    return prior_order(best.values())


def prior_order(candidates: Any) -> list[ShadowCandidate]:
    order = {bucket: idx for idx, bucket in enumerate(SHADOW_BUCKETS)}
    return sorted(list(candidates), key=lambda item: (order.get(item.bucket, 99), -item.score, item.ts_code))


def combined_watchlist(candidates: list[ShadowCandidate], limit: int) -> list[ShadowCandidate]:
    return sorted(
        [candidate for candidate in candidates if candidate.bucket in SHADOW_BUCKETS],
        key=lambda item: (-item.score, item.ts_code),
    )[:limit]


def attach_outcomes(candidates: list[ShadowCandidate], outcome_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {(row["ts_code"], row["bucket"]): row for row in outcome_rows}
    return [by_key.get((candidate.ts_code, candidate.bucket), candidate.to_dict()) for candidate in candidates]


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        f"# {format_date(summary['review_date'])} 影子策略监控",
        "",
        (
            f"> 研究专用：上一交易日 {format_date(summary['prior_review_date'])} 收盘生成影子候选，"
            f"用 {format_date(summary['review_date'])} 实际行情验算；同时给出 "
            f"{format_date(summary['review_date'])} 收盘后的次日观察名单。不会生成 paper/live 计划。"
        ),
        "",
        "## 结论",
        "",
    ]
    coverage = summary["actual_mover_coverage"]
    lines.append(
        f"- 今日 >=5% 池内上涨票 {coverage['actual_ge5_count']} 只，影子三桶覆盖 "
        f"{coverage['covered_ge5_count']} 只，覆盖率 {coverage['coverage_pct']}%。"
    )
    lines.append(
        f"- 今日收盘影子候选共 {summary['today_candidate_count']} 只；"
        f"趋势/突破/低价分别为 {bucket_count(summary, 'today_bucket_counts', 'trend_extension_shadow')}/"
        f"{bucket_count(summary, 'today_bucket_counts', 'breakout_pressure_shadow')}/"
        f"{bucket_count(summary, 'today_bucket_counts', 'low_price_momentum_shadow')}。"
    )
    lines.append("- 这说明方向判断有效，但还需要把“研究桶”升级成可观测策略账本，再谈 paper 小仓。")
    lines.extend(["", "## 昨日影子候选今日表现", ""])
    lines.extend(table(["桶", "候选数", "T+1收盘均值%", "T+1收盘胜率%", "T+1最高均值%", "最高>=3%"], summary_rows(summary)))
    lines.extend(["", "## 昨日各桶 Top1", ""])
    lines.extend(
        table(
            ["桶", "代码", "名称", "评分", "开盘缺口%", "收盘收益%", "最高收益%"],
            [
                [
                    row["bucket"],
                    row["ts_code"],
                    row["name"],
                    fmt(row.get("score")),
                    fmt(row.get("next_open_gap_pct")),
                    fmt(row.get("t1_close_ret_pct")),
                    fmt(row.get("t1_high_ret_pct")),
                ]
                for row in summary["prior_top_by_bucket"]
            ],
        )
    )
    lines.extend(["", "## 今日收盘次日观察 Top12", ""])
    lines.extend(
        table(
            ["桶", "代码", "名称", "评分", "收盘", "入池至今%", "5日%", "距20日高点%", "量/MA10"],
            [
                [
                    row["bucket"],
                    row["ts_code"],
                    row["name"],
                    fmt(row.get("score")),
                    fmt(row.get("review_close")),
                    fmt(row.get("entry_runup_pct")),
                    fmt(row.get("ret5_pct")),
                    fmt(row.get("dist20_high_pct")),
                    fmt(row.get("amount_to_ma10")),
                ]
                for row in summary["today_combined_watchlist"]
            ],
        )
    )
    lines.extend(["", "## 操作建议", ""])
    lines.append("- 明天先按观察名单盯盘，不把它直接混进 CPB 正式候选。")
    lines.append("- 若要 paper 试跑，建议新建独立 `shadow_momentum_v1` 小仓规则：只买一只、开盘高开超过 4% 不追、低价桶减半仓位。")
    lines.append("- 继续累计至少 20 个交易日 walk-forward，再决定是否进入 paper observation gate。")
    lines.append("")
    return "\n".join(lines)


def summary_rows(summary: dict[str, Any]) -> list[list[Any]]:
    return [
        [
            row["bucket"],
            row["n"],
            fmt(row["t1_close_mean_pct"]),
            fmt(row["t1_close_win_rate_pct"]),
            fmt(row["t1_high_mean_pct"]),
            fmt(row["t1_high_ge3_rate_pct"]),
        ]
        for row in summary["prior_outcome_summary"]
    ]


def table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return lines


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def bucket_count(summary: dict[str, Any], section: str, bucket: str) -> int:
    return int(summary[section].get(bucket, 0))


def rolling_pct(bars: list[sqlite3.Row], close: float, lookback: int) -> float | None:
    if len(bars) <= lookback:
        return None
    return pct(bars[-1 - lookback]["close"], close)


def pct(base: Any, value: Any) -> float | None:
    base_value = to_float(base)
    value_value = to_float(value)
    if base_value is None or value_value is None or base_value == 0:
        return None
    return round((value_value / base_value - 1) * 100, 2)


def average_number(values: Any) -> float | None:
    cleaned = [value for value in (to_float(item) for item in values) if value is not None]
    return sum(cleaned) / len(cleaned) if cleaned else None


def max_number(values: Any) -> float | None:
    cleaned = [value for value in (to_float(item) for item in values) if value is not None]
    return max(cleaned) if cleaned else None


def min_number(values: Any) -> float | None:
    cleaned = [value for value in (to_float(item) for item in values) if value is not None]
    return min(cleaned) if cleaned else None


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def format_date(value: str | None) -> str:
    if not value or len(value) != 8:
        return str(value)
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


if __name__ == "__main__":
    raise SystemExit(main())
