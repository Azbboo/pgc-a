#!/usr/bin/env python3
"""Generate research-only shadow strategy monitoring artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pgc_trading.services.common import RequestContext
from pgc_trading.services.shadow_observation_service import (
    BuildShadowPromotionDossierRequest,
    BuildShadowPromotionReviewRequest,
    ShadowObservationService,
    apply_shadow_replay_backtest_evidence_to_blockers,
    load_shadow_replay_backtest_evidence_index,
)


DEFAULT_DB_PATH = ROOT / "data" / "pgc_trading.db"
DEFAULT_REPORTS_DIR = ROOT / "reports"
DEFAULT_DATA_DIR = ROOT / "data"
DEFAULT_FROZEN_CPB_ARTIFACT = DEFAULT_REPORTS_DIR / "strategy_shadow_backtest_20260401_20260508.json"
DEFAULT_PRECONFIRM_ARTIFACT = DEFAULT_REPORTS_DIR / "preconfirm_watchlist_backtest.json"
DEFAULT_DIP_BUY_ARTIFACT = DEFAULT_REPORTS_DIR / "pgc_pullback_dip_buy.json"

SHADOW_BUCKETS = (
    "trend_extension_shadow",
    "breakout_pressure_shadow",
    "low_price_momentum_shadow",
)
PREFLIGHT_CANDIDATES = SHADOW_BUCKETS + (
    "preconfirm_watchlist",
    "pullback_dip_buy",
)
EXPECTED_CPB = {
    "strategy_key": "cpb_6157",
    "strategy_version": "cpb_6157@2026-05-03",
    "params_hash": "c4908f5cabe061f4d58fcbdd740f0c255c7c4830f467a9ed1602726688367ddc",
    "min_entry_price": 10.0,
}
BASE_PAPER_BLOCKERS = (
    "paper_observation_not_authorized",
    "walk_forward_shadow_monitor_20_trading_days_required",
    "operator_review_required",
)
BASE_STRATEGY_VERSION_BLOCKERS = (
    "strategy_version_proposal_not_authorized",
    "replay_backtest_result_artifact_required",
    "proposal_review_required",
    "operator_promotion_approval_required",
)
CANDIDATE_PAPER_BLOCKERS = {
    "trend_extension_shadow": ("sector_evidence_confirmation_required", "chase_gap_guard_required"),
    "breakout_pressure_shadow": ("volume_overheat_guard_required", "close_return_stability_required"),
    "low_price_momentum_shadow": ("micro_sleeve_risk_model_required", "liquidity_slippage_review_required"),
    "preconfirm_watchlist": ("next_day_confirmation_rule_required", "watchlist_only_ui_lane_required"),
    "pullback_dip_buy": ("dip_buy_stop_and_sizing_required", "falling_knife_guard_required"),
}
CANDIDATE_STRATEGY_VERSION_BLOCKERS = {
    "trend_extension_shadow": ("separate_trend_extension_candidate_required",),
    "breakout_pressure_shadow": ("separate_breakout_pressure_candidate_required",),
    "low_price_momentum_shadow": ("separate_low_price_micro_sleeve_required",),
    "preconfirm_watchlist": ("watchlist_to_signal_contract_required",),
    "pullback_dip_buy": ("separate_dip_buy_candidate_required",),
}
TRADE_STATE_TABLES = ("strategy_versions", "trade_plans", "trades", "positions")


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
        walk_forward_days=args.walk_forward_days,
        frozen_cpb_artifact_path=args.frozen_cpb_artifact,
        preconfirm_watchlist_artifact_path=args.preconfirm_watchlist_artifact,
        dip_buy_artifact_path=args.dip_buy_artifact,
    )
    print(json.dumps(report["outputs"], ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Outcome/review date YYYYMMDD.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--walk-forward-days", type=int, default=20)
    parser.add_argument("--frozen-cpb-artifact", type=Path, default=DEFAULT_FROZEN_CPB_ARTIFACT)
    parser.add_argument("--preconfirm-watchlist-artifact", type=Path, default=DEFAULT_PRECONFIRM_ARTIFACT)
    parser.add_argument("--dip-buy-artifact", type=Path, default=DEFAULT_DIP_BUY_ARTIFACT)
    return parser.parse_args()


def repo_portable_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): repo_portable_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [repo_portable_payload(item) for item in value]
    if isinstance(value, str):
        return repo_portable_path(value)
    return value


def repo_portable_path(value: str) -> str:
    text = value.strip()
    if not text.startswith("/"):
        return value
    try:
        return str(Path(text).resolve().relative_to(ROOT.resolve()))
    except (OSError, ValueError):
        return value


def generate_shadow_monitor(
    *,
    db_path: Path,
    review_date: str,
    reports_dir: Path,
    data_dir: Path,
    walk_forward_days: int = 20,
    frozen_cpb_artifact_path: Path = DEFAULT_FROZEN_CPB_ARTIFACT,
    preconfirm_watchlist_artifact_path: Path = DEFAULT_PRECONFIRM_ARTIFACT,
    dip_buy_artifact_path: Path = DEFAULT_DIP_BUY_ARTIFACT,
) -> dict[str, Any]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        state_counts_before = trade_state_counts(conn)
        prior_date = pretrade_date(conn, review_date)
        next_date = next_trade_date(conn, review_date)
        prior_candidates = build_shadow_candidates(conn, prior_date)
        today_candidates = build_shadow_candidates(conn, review_date)
        outcome_rows = evaluate_candidates(conn, prior_candidates, review_date)
        coverage = actual_mover_coverage(conn, prior_candidates, prior_date, review_date)
        walk_forward = build_walk_forward_progress(conn, review_date, walk_forward_days)
        active_cpb_integrity = inspect_active_cpb_integrity(conn)
        state_counts_after = trade_state_counts(conn)
        read_only_guard = build_read_only_guard(state_counts_before, state_counts_after, active_cpb_integrity)

    prior_top_by_bucket = top_by_bucket(prior_candidates)
    today_top_by_bucket = top_by_bucket(today_candidates)
    today_combined = combined_watchlist(today_candidates, limit=12)
    frozen_cpb_baseline = load_frozen_cpb_baseline(frozen_cpb_artifact_path)
    candidate_monitors = build_candidate_monitors(
        prior_candidates=prior_candidates,
        today_candidates=today_candidates,
        walk_forward=walk_forward,
        frozen_cpb_baseline=frozen_cpb_baseline,
        preconfirm_watchlist_artifact_path=preconfirm_watchlist_artifact_path,
        dip_buy_artifact_path=dip_buy_artifact_path,
    )
    promotion_preflight = build_promotion_preflight(
        review_date=review_date,
        next_date=next_date,
        candidate_monitors=candidate_monitors,
        active_cpb_integrity=active_cpb_integrity,
        frozen_cpb_baseline=frozen_cpb_baseline,
        required_walk_forward_days=walk_forward_days,
        read_only_guard=read_only_guard,
    )

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
            "monitored_candidates": list(PREFLIGHT_CANDIDATES),
            "promotion_preflight": "artifact_only; blocked until evidence gates are explicitly cleared",
        },
        "prior_candidate_count": len(prior_candidates),
        "today_candidate_count": len(today_candidates),
        "prior_bucket_counts": dict(Counter(item.bucket for item in prior_candidates)),
        "today_bucket_counts": dict(Counter(item.bucket for item in today_candidates)),
        "prior_outcome_summary": summarize_outcomes(outcome_rows),
        "actual_mover_coverage": coverage,
        "walk_forward_progress": walk_forward,
        "frozen_cpb_baseline": frozen_cpb_baseline,
        "active_cpb_integrity": active_cpb_integrity,
        "read_only_guard": read_only_guard,
        "candidate_monitors": candidate_monitors,
        "promotion_preflight": promotion_preflight,
        "api_summary": build_api_summary(
            review_date=review_date,
            next_date=next_date,
            candidate_monitors=candidate_monitors,
            walk_forward=walk_forward,
            promotion_preflight=promotion_preflight,
        ),
        "prior_top_by_bucket": attach_outcomes(prior_top_by_bucket, outcome_rows),
        "today_top_by_bucket": [item.to_dict() for item in prior_order(today_top_by_bucket)],
        "today_combined_watchlist": [item.to_dict() for item in today_combined],
    }
    replay_evidence_index = load_shadow_replay_backtest_evidence_index(
        reports_dir,
        as_of_date=review_date,
        candidate_required_samples=candidate_required_samples(candidate_monitors, walk_forward),
    )
    summary["replay_backtest_evidence"] = replay_evidence_index

    json_path = reports_dir / f"strategy_shadow_monitor_{review_date}.json"
    md_path = reports_dir / f"strategy_shadow_monitor_{review_date}.md"
    preflight_json_path = reports_dir / f"strategy_shadow_promotion_preflight_{review_date}.json"
    preflight_md_path = reports_dir / f"strategy_shadow_promotion_preflight_{review_date}.md"
    scorecard_json_path = reports_dir / f"shadow_observation_scorecard_{review_date}.json"
    scorecard_md_path = reports_dir / f"shadow_observation_scorecard_{review_date}.md"
    prior_csv_path = data_dir / f"strategy_shadow_outcome_{prior_date}_to_{review_date}.csv"
    walk_csv_path = data_dir / f"strategy_shadow_walk_forward_{review_date}.csv"
    watch_csv_path = data_dir / f"strategy_shadow_watchlist_{review_date}.csv"
    scorecard = build_shadow_observation_scorecard(
        summary,
        source_artifacts={
            "strategy_shadow_monitor_json": str(json_path),
            "strategy_shadow_monitor_report": str(md_path),
            "promotion_preflight_json": str(preflight_json_path),
            "promotion_preflight_report": str(preflight_md_path),
            "walk_forward_csv": str(walk_csv_path),
            "watchlist_csv": str(watch_csv_path),
        },
    )

    portable_summary = repo_portable_payload(summary)
    portable_preflight = repo_portable_payload(promotion_preflight)
    portable_scorecard = repo_portable_payload(scorecard)
    json_path.write_text(json.dumps(portable_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(portable_summary), encoding="utf-8")
    preflight_json_path.write_text(json.dumps(portable_preflight, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    preflight_md_path.write_text(render_preflight_markdown(portable_summary), encoding="utf-8")
    scorecard_json_path.write_text(json.dumps(portable_scorecard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scorecard_md_path.write_text(render_shadow_observation_scorecard_markdown(portable_scorecard), encoding="utf-8")
    write_csv(prior_csv_path, outcome_rows)
    write_csv(walk_csv_path, walk_forward["rows"])
    write_csv(watch_csv_path, [item.to_dict() for item in today_combined])
    dossier_result = ShadowObservationService(db_path, reports_dir=reports_dir).build_promotion_dossier(
        BuildShadowPromotionDossierRequest(as_of_date=review_date),
        RequestContext(request_id=f"shadow-promotion-dossier-{review_date}", dry_run=False, source="monitor-script"),
    )
    review_request_result = ShadowObservationService(db_path, reports_dir=reports_dir).build_promotion_review_request(
        BuildShadowPromotionReviewRequest(as_of_date=review_date),
        RequestContext(
            request_id=f"shadow-promotion-review-request-{review_date}",
            dry_run=False,
            source="monitor-script",
        ),
    )
    summary["promotion_dossier"] = (
        dossier_result.data.artifact
        if dossier_result.ok and dossier_result.data is not None
        else {
            "artifact_type": "shadow_promotion_dossier",
            "dossier_contract": "shadow_promotion_dossier_v1",
            "status": "unavailable",
            "errors": [error.code for error in dossier_result.errors],
            "promotion_allowed": False,
        }
    )
    summary["promotion_review_request"] = (
        review_request_result.data.artifact
        if review_request_result.ok and review_request_result.data is not None
        else {
            "artifact_type": "shadow_promotion_review_request",
            "review_request_contract": "shadow_promotion_review_request_v1",
            "as_of_date": review_date,
            "status": review_request_result.status,
            "errors": [error.code for error in review_request_result.errors],
            "promotion_allowed": False,
        }
    )

    summary["outputs"] = {
        "report": str(md_path),
        "json": str(json_path),
        "promotion_preflight_report": str(preflight_md_path),
        "promotion_preflight_json": str(preflight_json_path),
        "promotion_dossier_report": dossier_result.data.markdown_path if dossier_result.data else None,
        "promotion_dossier_json": dossier_result.data.artifact_path if dossier_result.data else None,
        "promotion_review_request_report": (
            review_request_result.data.markdown_path if review_request_result.data else None
        ),
        "promotion_review_request_json": (
            review_request_result.data.artifact_path if review_request_result.data else None
        ),
        "shadow_observation_scorecard_report": str(scorecard_md_path),
        "shadow_observation_scorecard_json": str(scorecard_json_path),
        "prior_outcome_csv": str(prior_csv_path),
        "walk_forward_csv": str(walk_csv_path),
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


def build_walk_forward_progress(
    conn: sqlite3.Connection,
    review_date: str,
    required_days: int,
) -> dict[str, Any]:
    date_pairs = walk_forward_date_pairs(conn, review_date, required_days)
    rows: list[dict[str, Any]] = []
    for signal_date, outcome_date in date_pairs:
        candidates = top_by_bucket(build_shadow_candidates(conn, signal_date))
        for row in evaluate_candidates(conn, candidates, outcome_date):
            row["signal_date"] = signal_date
            row["planned_buy_date"] = outcome_date
            rows.append(row)
    bucket_summary = summarize_walk_forward_rows(rows, required_days)
    return {
        "status": "complete" if all(row.get("status") == "complete" for row in bucket_summary) else "collecting",
        "required_days": required_days,
        "evaluable_signal_days": len(date_pairs),
        "start_signal_date": date_pairs[0][0] if date_pairs else None,
        "latest_signal_date": date_pairs[-1][0] if date_pairs else None,
        "latest_outcome_date": date_pairs[-1][1] if date_pairs else None,
        "methodology": {
            "selection": "daily Top1 by score within each shadow bucket",
            "entry": "next trading day open",
            "exit_label": "same-day close/high labels; no paper/live order is written",
            "candidate_buckets": list(SHADOW_BUCKETS),
        },
        "summary": bucket_summary,
        "rows": rows,
    }


def walk_forward_date_pairs(
    conn: sqlite3.Connection,
    review_date: str,
    required_days: int,
) -> list[tuple[str, str]]:
    rows = conn.execute(
        """
        SELECT cal_date
        FROM trade_calendar
        WHERE is_open = 1 AND cal_date <= ?
        ORDER BY cal_date
        """,
        (review_date,),
    ).fetchall()
    dates = [str(row["cal_date"]) for row in rows]
    pairs = [(dates[idx], dates[idx + 1]) for idx in range(len(dates) - 1)]
    return pairs[-required_days:] if required_days > 0 else pairs


def summarize_walk_forward_rows(rows: list[dict[str, Any]], required_days: int) -> list[dict[str, Any]]:
    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_bucket[str(row["bucket"])].append(row)
    summaries: list[dict[str, Any]] = []
    for bucket in SHADOW_BUCKETS:
        sample = by_bucket.get(bucket, [])
        dates = sorted({str(row.get("signal_date") or row.get("review_date")) for row in sample})
        base = summarize_outcomes(sample)
        item = base[0] if base else {"bucket": bucket, "n": 0}
        item.update(
            {
                "candidate_key": bucket,
                "required_days": required_days,
                "days": len(dates),
                "start_signal_date": dates[0] if dates else None,
                "latest_signal_date": dates[-1] if dates else None,
                "status": "complete" if len(dates) >= required_days else "collecting",
            }
        )
        summaries.append(item)
    return summaries


def load_frozen_cpb_baseline(path: Path) -> dict[str, Any]:
    payload = read_json_object(path)
    if payload is None:
        return {
            "status": "missing",
            "source_artifact": str(path),
            "metrics": {},
            "blockers": ["frozen_cpb_baseline_artifact_missing"],
        }
    metrics = artifact_summary_row(payload, "active_cpb_persisted_picks")
    active_picks = payload.get("active_cpb_picks")
    return {
        "status": "available" if metrics else "missing_metrics",
        "source_artifact": str(path),
        "metrics": compact_metrics(
            metrics,
            [
                "label",
                "n",
                "days",
                "t1_close_mean_pct",
                "t1_close_median_pct",
                "t1_close_win_rate_pct",
                "t1_high_mean_pct",
                "t1_high_ge3_rate_pct",
                "t5_close_mean_pct",
                "t5_close_win_rate_pct",
                "max_t1_loss_pct",
                "max_t1_gain_pct",
            ],
        ),
        "sample_warning": "small_frozen_cpb_sample" if int(metrics.get("n") or 0) < 20 else None,
        "active_pick_count": len(active_picks) if isinstance(active_picks, list) else None,
        "blockers": [] if metrics else ["frozen_cpb_baseline_metrics_missing"],
    }


def inspect_active_cpb_integrity(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT strategy_key, strategy_version, params_hash, status
        FROM strategy_versions
        WHERE strategy_key = ? AND strategy_version = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (EXPECTED_CPB["strategy_key"], EXPECTED_CPB["strategy_version"]),
    ).fetchone()
    params_path = ROOT / "src" / "pgc_trading" / "strategies" / "params" / "cpb_6157_2026_05_03.json"
    params_payload = read_json_object(params_path) or {}
    params_file_hash = params_payload.get("params_hash") if isinstance(params_payload, dict) else None
    db_hash = row["params_hash"] if row is not None else None
    blockers = []
    if row is None:
        blockers.append("active_cpb_strategy_version_missing")
    elif db_hash != EXPECTED_CPB["params_hash"]:
        blockers.append("active_cpb_db_params_hash_mismatch")
    if params_file_hash != EXPECTED_CPB["params_hash"]:
        blockers.append("active_cpb_params_file_hash_mismatch")
    return {
        "expected": dict(EXPECTED_CPB),
        "db_strategy_version": {
            "exists": row is not None,
            "strategy_key": row["strategy_key"] if row is not None else None,
            "strategy_version": row["strategy_version"] if row is not None else None,
            "params_hash": db_hash,
            "status": row["status"] if row is not None else None,
            "params_hash_matches_expected": db_hash == EXPECTED_CPB["params_hash"],
        },
        "params_file": {
            "path": str(params_path),
            "params_hash": params_file_hash,
            "params_hash_matches_expected": params_file_hash == EXPECTED_CPB["params_hash"],
        },
        "trade_state_counts": {
            "strategy_versions": count_table(conn, "strategy_versions"),
            "trade_plans": count_table(conn, "trade_plans"),
            "trades": count_table(conn, "trades"),
            "positions": count_table(conn, "positions"),
        },
        "blockers": blockers,
        "safety": artifact_safety_flags(),
    }


def count_table(conn: sqlite3.Connection, table_name: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table_name}").fetchone()
    except sqlite3.Error:
        return 0
    return int(row["n"] or 0)


def trade_state_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {table_name: count_table(conn, table_name) for table_name in TRADE_STATE_TABLES}


def build_read_only_guard(
    counts_before: dict[str, int],
    counts_after: dict[str, int],
    active_cpb_integrity: dict[str, Any],
) -> dict[str, Any]:
    safety = active_cpb_integrity.get("safety") if isinstance(active_cpb_integrity.get("safety"), dict) else {}
    changed_tables = [
        table_name
        for table_name in TRADE_STATE_TABLES
        if counts_before.get(table_name) != counts_after.get(table_name)
    ]
    forbidden_safety_flags = [
        flag
        for flag in (
            "active_params_mutated",
            "wrote_strategy_version",
            "writes_trade_state",
            "writes_paper_live_behavior",
            "timer_mutated",
        )
        if bool(safety.get(flag))
    ]
    status = "pass" if not changed_tables and not forbidden_safety_flags else "blocked"
    return {
        "status": status,
        "guard_type": "shadow_visibility_read_only",
        "trade_state_tables": list(TRADE_STATE_TABLES),
        "trade_state_counts_before": counts_before,
        "trade_state_counts_after": counts_after,
        "trade_state_counts_unchanged": not changed_tables,
        "changed_tables": changed_tables,
        "active_cpb_params_hash_matches_expected": bool(
            active_cpb_integrity.get("db_strategy_version", {}).get("params_hash_matches_expected")
            and active_cpb_integrity.get("params_file", {}).get("params_hash_matches_expected")
        ),
        "forbidden_safety_flags": forbidden_safety_flags,
        "active_params_mutated": False,
        "writes_trade_state": False,
        "writes_paper_live_behavior": False,
        "timer_mutated": False,
    }


def build_candidate_monitors(
    *,
    prior_candidates: list[ShadowCandidate],
    today_candidates: list[ShadowCandidate],
    walk_forward: dict[str, Any],
    frozen_cpb_baseline: dict[str, Any],
    preconfirm_watchlist_artifact_path: Path,
    dip_buy_artifact_path: Path,
) -> list[dict[str, Any]]:
    walk_summary = {row["candidate_key"]: row for row in walk_forward.get("summary", [])}
    monitors: list[dict[str, Any]] = []
    for bucket in SHADOW_BUCKETS:
        progress = walk_summary.get(bucket, {})
        monitors.append(
            {
                "candidate_key": bucket,
                "candidate_family": "shadow_bucket",
                "signal_source": "raw_events + market_bars daily bucket classifier",
                "prior_candidate_count": count_candidates(prior_candidates, bucket),
                "today_candidate_count": count_candidates(today_candidates, bucket),
                "today_top": first_candidate_dict(top_by_bucket([item for item in today_candidates if item.bucket == bucket])),
                "walk_forward_progress": progress,
                "comparison_vs_frozen_cpb": compare_to_frozen_cpb(progress, frozen_cpb_baseline.get("metrics", {})),
                "promotion_gates": candidate_promotion_gates(bucket),
            }
        )
    monitors.append(build_preconfirm_monitor(preconfirm_watchlist_artifact_path, frozen_cpb_baseline.get("metrics", {})))
    monitors.append(build_dip_buy_monitor(dip_buy_artifact_path, frozen_cpb_baseline.get("metrics", {})))
    return monitors


def build_preconfirm_monitor(path: Path, frozen_metrics: dict[str, Any]) -> dict[str, Any]:
    payload = read_json_object(path)
    if payload is None:
        progress = missing_artifact_progress("preconfirm_watchlist", path)
        comparison = {"status": "missing", "blockers": ["preconfirm_watchlist_artifact_missing"]}
        source = {}
    else:
        high = preconfirm_summary_row(payload, "高潜伏预警")
        all_watch = preconfirm_summary_row(payload, "全部")
        observed_days = optional_int(high.get("review_days"))
        progress = {
            "candidate_key": "preconfirm_watchlist",
            "status": "complete" if observed_days is not None and observed_days >= 20 else "collecting",
            "required_days": 20,
            "days": observed_days,
            "signals": high.get("signals"),
            "stocks": high.get("stocks"),
            "confirm_next_day_rate_pct": ratio_to_pct(high.get("confirm_next_day_rate")),
            "next_open_ret_1d_mean_pct": ratio_to_pct(high.get("next_open_ret_1d_mean")),
            "next_open_ret_5d_mean_pct": ratio_to_pct(high.get("next_open_ret_5d_mean")),
            "watch_mfe_5d_mean_pct": ratio_to_pct(high.get("watch_mfe_5d_mean")),
            "all_watchlist_signals": all_watch.get("signals"),
            "source_artifact": str(path),
        }
        comparison = compare_to_frozen_cpb(
            {
                "t1_close_mean_pct": progress.get("next_open_ret_1d_mean_pct"),
                "t5_close_mean_pct": progress.get("next_open_ret_5d_mean_pct"),
                "t1_close_win_rate_pct": ratio_to_pct(high.get("next_open_ret_1d_win_rate")),
                "days": observed_days,
            },
            frozen_metrics,
        )
        source = payload.get("meta", {}) if isinstance(payload.get("meta"), dict) else {}
    return {
        "candidate_key": "preconfirm_watchlist",
        "candidate_family": "preconfirm_watchlist",
        "signal_source": "preconfirm_watchlist_backtest artifact",
        "source": source,
        "walk_forward_progress": progress,
        "comparison_vs_frozen_cpb": comparison,
        "promotion_gates": candidate_promotion_gates("preconfirm_watchlist"),
    }


def build_dip_buy_monitor(path: Path, frozen_metrics: dict[str, Any]) -> dict[str, Any]:
    payload = read_json_object(path)
    if payload is None:
        progress = missing_artifact_progress("pullback_dip_buy", path)
        comparison = {"status": "missing", "blockers": ["dip_buy_artifact_missing"]}
        selected_params = {}
    else:
        selected_params = dict(payload.get("selected_params") or {})
        selected_variant = payload.get("selected_variant")
        selected_row = first_variant_row(payload.get("variants"), selected_variant)
        selected_groups = payload.get("selected_groups") if isinstance(payload.get("selected_groups"), dict) else {}
        high_score = first_group_row(selected_groups.get("score"), "潜力分>=75")
        progress = {
            "candidate_key": "pullback_dip_buy",
            "status": "artifact_summary_only",
            "required_days": 20,
            "days": None,
            "observed_trades": selected_row.get("ret_5d_n"),
            "fill_rate_pct": ratio_to_pct(selected_row.get("fill_rate")),
            "ret_5d_mean_pct": ratio_to_pct(selected_row.get("ret_5d_mean")),
            "ret_5d_win_rate_pct": ratio_to_pct(selected_row.get("ret_5d_win_rate")),
            "mfe_10d_median_pct": ratio_to_pct(selected_row.get("mfe_10d_median")),
            "mae_10d_median_pct": ratio_to_pct(selected_row.get("mae_10d_median")),
            "high_score_ret_5d_mean_pct": ratio_to_pct(high_score.get("ret_5d_mean")),
            "source_artifact": str(path),
            "blockers": ["daily_walk_forward_monitor_required_for_dip_buy"],
        }
        comparison = compare_to_frozen_cpb(
            {
                "t5_close_mean_pct": progress.get("ret_5d_mean_pct"),
                "t5_close_win_rate_pct": progress.get("ret_5d_win_rate_pct"),
                "days": None,
            },
            frozen_metrics,
        )
    return {
        "candidate_key": "pullback_dip_buy",
        "candidate_family": "dip_buy",
        "signal_source": "pgc_pullback_dip_buy artifact",
        "selected_params": selected_params,
        "walk_forward_progress": progress,
        "comparison_vs_frozen_cpb": comparison,
        "promotion_gates": candidate_promotion_gates("pullback_dip_buy"),
    }


def build_promotion_preflight(
    *,
    review_date: str,
    next_date: str | None,
    candidate_monitors: list[dict[str, Any]],
    active_cpb_integrity: dict[str, Any],
    frozen_cpb_baseline: dict[str, Any],
    required_walk_forward_days: int,
    read_only_guard: dict[str, Any],
) -> dict[str, Any]:
    candidate_gates = []
    blocker_counts: Counter[str] = Counter()
    for monitor in candidate_monitors:
        paper_gate = monitor["promotion_gates"]["paper_observation_gate"]
        strategy_gate = monitor["promotion_gates"]["strategy_version_gate"]
        blockers = list(paper_gate["blockers"]) + list(strategy_gate["blockers"])
        blocker_counts.update(blockers)
        candidate_gates.append(
            {
                "candidate_key": monitor["candidate_key"],
                "candidate_family": monitor["candidate_family"],
                "walk_forward_progress": monitor["walk_forward_progress"],
                "comparison_vs_frozen_cpb": monitor["comparison_vs_frozen_cpb"],
                "paper_observation_gate": paper_gate,
                "strategy_version_gate": strategy_gate,
                "status": "blocked",
            }
        )
    blocker_counts.update(active_cpb_integrity.get("blockers", []))
    blocker_counts.update(frozen_cpb_baseline.get("blockers", []))
    return {
        "artifact_type": "shadow_strategy_promotion_preflight",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "review_date": review_date,
        "next_trade_date": next_date,
        "status": "blocked",
        "required_walk_forward_days": required_walk_forward_days,
        "candidate_count": len(candidate_monitors),
        "candidate_gates": candidate_gates,
        "blockers": sorted(blocker_counts),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "frozen_cpb_baseline": frozen_cpb_baseline,
        "active_cpb_integrity": active_cpb_integrity,
        "read_only_guard": read_only_guard,
        "release_gate": build_release_gate(read_only_guard),
        "safety": {
            **artifact_safety_flags(),
            "artifact_only": True,
            "promotion_allowed": False,
            "paper_observation_allowed": False,
            "requires_explicit_blocker_clearance": True,
        },
    }


def build_release_gate(read_only_guard: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "blocked",
        "artifact_only": True,
        "promotion_allowed": False,
        "paper_observation_allowed": False,
        "displayed_surfaces": [
            "strategy_shadow_monitor artifact",
            "strategy_shadow_promotion_preflight artifact",
            "shadow_observation_scorecard artifact",
            "shadow_strategy_snapshot API/CLI",
            "Dashboard Shadow Lab",
            "daily review shadow_observation section",
        ],
        "blocked_paths": [
            "active_cpb_params",
            "strategy_versions",
            "trade_plans",
            "trades",
            "positions",
            "paper_live_behavior",
            "pgc-daily-pipeline.timer",
        ],
        "trade_state_counts_unchanged": bool(read_only_guard.get("trade_state_counts_unchanged")),
        "active_params_mutated": False,
        "writes_trade_state": False,
        "writes_paper_live_behavior": False,
        "timer_mutated": False,
        "requires_explicit_blocker_clearance": True,
    }


def build_api_summary(
    *,
    review_date: str,
    next_date: str | None,
    candidate_monitors: list[dict[str, Any]],
    walk_forward: dict[str, Any],
    promotion_preflight: dict[str, Any],
) -> dict[str, Any]:
    return {
        "review_date": review_date,
        "next_trade_date": next_date,
        "read_only": True,
        "walk_forward_progress": {
            "status": walk_forward.get("status"),
            "required_days": walk_forward.get("required_days"),
            "evaluable_signal_days": walk_forward.get("evaluable_signal_days"),
            "start_signal_date": walk_forward.get("start_signal_date"),
            "latest_signal_date": walk_forward.get("latest_signal_date"),
            "summary": walk_forward.get("summary", []),
        },
        "promotion_preflight": {
            "status": promotion_preflight.get("status"),
            "candidate_count": promotion_preflight.get("candidate_count"),
            "blockers": promotion_preflight.get("blockers", []),
            "release_gate": promotion_preflight.get("release_gate", {}),
            "safety": promotion_preflight.get("safety", {}),
        },
        "candidates": [
            {
                "candidate_key": item["candidate_key"],
                "candidate_family": item["candidate_family"],
                "walk_forward_status": item.get("walk_forward_progress", {}).get("status"),
                "paper_blocker_count": len(item.get("promotion_gates", {}).get("paper_observation_gate", {}).get("blockers", [])),
                "strategy_version_blocker_count": len(
                    item.get("promotion_gates", {}).get("strategy_version_gate", {}).get("blockers", [])
                ),
                "comparison_vs_frozen_cpb": item.get("comparison_vs_frozen_cpb", {}),
            }
            for item in candidate_monitors
        ],
    }


def candidate_required_samples(
    candidate_monitors: list[dict[str, Any]],
    walk_forward: dict[str, Any],
) -> dict[str, int]:
    fallback = optional_int(walk_forward.get("required_days")) or 20
    required: dict[str, int] = {}
    for monitor in candidate_monitors:
        candidate_key = str(monitor.get("candidate_key") or "").strip()
        if not candidate_key:
            continue
        progress = monitor.get("walk_forward_progress", {})
        required[candidate_key] = optional_int(progress.get("required_days")) or fallback
    return required


def candidate_promotion_gates(candidate_key: str) -> dict[str, Any]:
    paper_blockers = merge_unique(list(BASE_PAPER_BLOCKERS), list(CANDIDATE_PAPER_BLOCKERS.get(candidate_key, ())))
    strategy_blockers = merge_unique(
        list(BASE_STRATEGY_VERSION_BLOCKERS),
        list(CANDIDATE_STRATEGY_VERSION_BLOCKERS.get(candidate_key, ())),
    )
    return {
        "paper_observation_gate": blocked_gate("paper_observation", paper_blockers),
        "strategy_version_gate": blocked_gate("strategy_version_proposal", strategy_blockers),
    }


def blocked_gate(gate_type: str, blockers: list[str]) -> dict[str, Any]:
    return {
        "gate_type": gate_type,
        "status": "blocked",
        "allowed": False,
        "artifact_only": True,
        "clearance_required": True,
        "blockers": blockers,
    }


def compare_to_frozen_cpb(metrics: dict[str, Any], frozen_metrics: dict[str, Any]) -> dict[str, Any]:
    if not frozen_metrics:
        return {"status": "missing_baseline", "blockers": ["frozen_cpb_baseline_metrics_missing"]}
    return {
        "status": "compared",
        "baseline_label": frozen_metrics.get("label"),
        "baseline_days": frozen_metrics.get("days"),
        "candidate_days": metrics.get("days"),
        "t1_close_mean_delta_pct": delta(metrics.get("t1_close_mean_pct"), frozen_metrics.get("t1_close_mean_pct")),
        "t1_close_win_rate_delta_pct": delta(
            metrics.get("t1_close_win_rate_pct"),
            frozen_metrics.get("t1_close_win_rate_pct"),
        ),
        "t5_close_mean_delta_pct": delta(metrics.get("t5_close_mean_pct"), frozen_metrics.get("t5_close_mean_pct")),
        "sample_warning": "baseline_sample_lt_20"
        if optional_int(frozen_metrics.get("n")) is not None and int(frozen_metrics.get("n")) < 20
        else None,
    }


def artifact_safety_flags() -> dict[str, bool]:
    return {
        "active_params_mutated": False,
        "wrote_strategy_version": False,
        "writes_trade_state": False,
        "writes_paper_live_behavior": False,
        "timer_mutated": False,
    }


def count_candidates(candidates: list[ShadowCandidate], bucket: str) -> int:
    return len([item for item in candidates if item.bucket == bucket])


def first_candidate_dict(candidates: list[ShadowCandidate]) -> dict[str, Any] | None:
    return candidates[0].to_dict() if candidates else None


def read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def artifact_summary_row(payload: dict[str, Any], label: str) -> dict[str, Any]:
    rows = payload.get("summary")
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if isinstance(row, dict) and row.get("label") == label:
            return dict(row)
    return {}


def preconfirm_summary_row(payload: dict[str, Any], pre_action: str) -> dict[str, Any]:
    rows = payload.get("summary")
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if isinstance(row, dict) and row.get("pre_action") == pre_action:
            return dict(row)
    return {}


def first_variant_row(rows: Any, variant_id: Any) -> dict[str, Any]:
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if isinstance(row, dict) and row.get("variant_id") == variant_id:
            return dict(row)
    return dict(rows[0]) if rows and isinstance(rows[0], dict) else {}


def first_group_row(rows: Any, group: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if isinstance(row, dict) and row.get("group") == group:
            return dict(row)
    return {}


def missing_artifact_progress(candidate_key: str, path: Path) -> dict[str, Any]:
    return {
        "candidate_key": candidate_key,
        "status": "missing_artifact",
        "required_days": 20,
        "days": None,
        "source_artifact": str(path),
        "blockers": [f"{candidate_key}_artifact_missing"],
    }


def compact_metrics(row: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: row.get(key) for key in keys if key in row}


def ratio_to_pct(value: Any) -> float | None:
    value_float = to_float_or_none(value)
    return round(value_float * 100, 2) if value_float is not None else None


def delta(value: Any, baseline: Any) -> float | None:
    value_float = to_float_or_none(value)
    baseline_float = to_float_or_none(baseline)
    if value_float is None or baseline_float is None:
        return None
    return round(value_float - baseline_float, 2)


def optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def merge_unique(base: list[str], extra: list[str]) -> list[str]:
    seen = set()
    merged = []
    for item in base + extra:
        if item not in seen:
            seen.add(item)
            merged.append(item)
    return merged


def build_shadow_observation_scorecard(
    summary: dict[str, Any],
    *,
    source_artifacts: dict[str, str],
) -> dict[str, Any]:
    preflight = summary["promotion_preflight"]
    replay_evidence_index = summary.get("replay_backtest_evidence", {})
    replay_evidence_by_candidate = (
        replay_evidence_index.get("by_candidate", {}) if isinstance(replay_evidence_index, dict) else {}
    )
    candidates = []
    for monitor in summary["candidate_monitors"]:
        gates = monitor.get("promotion_gates", {})
        paper_gate = gates.get("paper_observation_gate", {})
        proposal_gate = gates.get("strategy_version_gate", {})
        candidate_key = str(monitor.get("candidate_key") or "")
        replay_evidence = (
            replay_evidence_by_candidate.get(candidate_key, {})
            if isinstance(replay_evidence_by_candidate, dict)
            else {}
        )
        blockers = merge_unique(
            list(paper_gate.get("blockers", [])),
            list(proposal_gate.get("blockers", [])),
        )
        blockers = apply_shadow_replay_backtest_evidence_to_blockers(blockers, replay_evidence)
        progress = monitor.get("walk_forward_progress", {})
        candidates.append(
            {
                "candidate_key": candidate_key or monitor.get("candidate_key"),
                "candidate_family": monitor.get("candidate_family"),
                "status": "blocked" if blockers else str(progress.get("status") or "observing"),
                "today_candidate_count": monitor.get("today_candidate_count"),
                "today_top": monitor.get("today_top") or {},
                "walk_forward_status": progress.get("status"),
                "walk_forward_days": progress.get("days") or progress.get("evaluable_signal_days"),
                "paper_observation_allowed": bool(paper_gate.get("allowed")),
                "promotion_allowed": bool(proposal_gate.get("allowed")),
                "blocker_count": len(blockers),
                "blockers": blockers,
                "replay_backtest_evidence": replay_evidence,
                "comparison_vs_frozen_cpb": monitor.get("comparison_vs_frozen_cpb", {}),
            }
        )
    blocker_counts = dict(sorted(Counter(blocker for item in candidates for blocker in item["blockers"]).items()))
    replay_summary = (
        replay_evidence_index.get("summary", {}) if isinstance(replay_evidence_index, dict) else {}
    )
    return {
        "artifact_type": "shadow_observation_scorecard",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "review_date": summary["review_date"],
        "next_trade_date": summary.get("next_trade_date"),
        "status": preflight.get("status", "unknown"),
        "read_only": True,
        "artifact_only": True,
        "candidate_count": len(candidates),
        "blocked_candidate_count": sum(1 for item in candidates if item["blocker_count"]),
        "distinct_blocker_count": len(blocker_counts),
        "coverage_blockers": [
            {"code": key, "count": blocker_counts[key]}
            for key in sorted(blocker_counts)
        ],
        "replay_backtest_evidence_summary": replay_summary,
        "top_candidates": sorted(
            candidates,
            key=lambda item: (-(optional_int(item.get("today_candidate_count")) or 0), -item["blocker_count"], str(item["candidate_key"])),
        )[:5],
        "candidates": candidates,
        "source_artifacts": source_artifacts,
        "safety": {
            **artifact_safety_flags(),
            "read_only": True,
            "artifact_only": True,
            "promotion_allowed": False,
            "paper_observation_allowed": False,
        },
        "notice": "Observation scorecard is research-only and does not create active picks, trade plans, paper/live behavior, or timers.",
    }


def render_shadow_observation_scorecard_markdown(scorecard: dict[str, Any]) -> str:
    lines = [
        f"# {format_date(scorecard['review_date'])} Shadow Observation Scorecard",
        "",
        "> Research-only scorecard. It does not create active daily picks, trade plans, paper/live behavior, or timers.",
        "",
        "## Status",
        "",
        f"- Status: {scorecard['status']}",
        f"- Candidates: {scorecard['candidate_count']}",
        f"- Blocked candidates: {scorecard['blocked_candidate_count']}",
        f"- Distinct blockers: {scorecard['distinct_blocker_count']}",
        f"- Read only: {scorecard['read_only']}",
        f"- Artifact only: {scorecard['artifact_only']}",
        (
            "- Replay/backtest evidence: "
            f"accepted={scorecard.get('replay_backtest_evidence_summary', {}).get('accepted_count', 0)} / "
            f"rejected={scorecard.get('replay_backtest_evidence_summary', {}).get('rejected_count', 0)} / "
            f"missing={scorecard.get('replay_backtest_evidence_summary', {}).get('missing_count', 0)}"
        ),
        "",
        "## Coverage Blockers",
        "",
    ]
    blockers = scorecard.get("coverage_blockers", [])
    if blockers:
        for blocker in blockers:
            lines.append(f"- {blocker['code']}: {blocker['count']}")
    else:
        lines.append("- none")
    lines.extend(["", "## Top Candidates", ""])
    lines.extend(
        table(
            ["Candidate", "Family", "Status", "Today", "Walk-forward", "Replay", "Blockers", "Top"],
            [
                [
                    item.get("candidate_key"),
                    item.get("candidate_family"),
                    item.get("status"),
                    item.get("today_candidate_count") if item.get("today_candidate_count") is not None else "-",
                    item.get("walk_forward_status") or "-",
                    (item.get("replay_backtest_evidence") or {}).get("status", "missing"),
                    ", ".join(item.get("blockers", [])[:3]) + ("..." if len(item.get("blockers", [])) > 3 else ""),
                    top_candidate_text(item.get("today_top")),
                ]
                for item in scorecard.get("top_candidates", [])
            ],
        )
    )
    lines.extend(["", "## Source Artifacts", ""])
    for label, path in sorted(scorecard.get("source_artifacts", {}).items()):
        lines.append(f"- {label}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def top_candidate_text(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return "-"
    stock = " ".join(str(part) for part in [value.get("ts_code"), value.get("name")] if part)
    return stock or "-"


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
    walk_forward = summary["walk_forward_progress"]
    lines.append(
        f"- 20 日 walk-forward 状态：{walk_forward['status']}，"
        f"{walk_forward['start_signal_date']} 至 {walk_forward['latest_signal_date']} "
        f"共 {walk_forward['evaluable_signal_days']} 个可验算信号日。"
    )
    lines.append(
        f"- Promotion preflight：{summary['promotion_preflight']['status']}；"
        f"候选 {summary['promotion_preflight']['candidate_count']} 类，"
        f"blocker {len(summary['promotion_preflight']['blockers'])} 项，全部仍为 artifact-only。"
    )
    lines.append("- 方向判断可以继续观察，但 paper/proposal/promotion 都必须等 evidence gate 显式清空。")
    lines.extend(["", "## 昨日影子候选今日表现", ""])
    lines.extend(table(["桶", "候选数", "T+1收盘均值%", "T+1收盘胜率%", "T+1最高均值%", "最高>=3%"], summary_rows(summary)))
    lines.extend(["", "## 20 日 Walk-forward", ""])
    lines.extend(
        table(
            ["候选", "状态", "天数", "T+1收盘均值%", "T+1胜率%", "T+1最高均值%", "冻结CPB T+1均值差%"],
            candidate_monitor_rows(summary),
        )
    )
    lines.extend(["", "## 冻结 CPB 对照", ""])
    baseline = summary["frozen_cpb_baseline"]
    lines.append(f"- 来源：`{baseline.get('source_artifact')}`")
    lines.append(f"- 状态：{baseline.get('status')}；样本提示：{baseline.get('sample_warning') or '无'}")
    lines.append(
        "- DB/参数完整性："
        f"db_hash_match={summary['active_cpb_integrity']['db_strategy_version']['params_hash_matches_expected']}；"
        f"params_file_hash_match={summary['active_cpb_integrity']['params_file']['params_hash_matches_expected']}。"
    )
    lines.extend(["", "## Promotion Preflight", ""])
    lines.extend(
        table(
            ["候选", "Paper gate", "Proposal gate", "主要 blockers"],
            preflight_rows(summary["promotion_preflight"]),
        )
    )
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
    lines.append("- 若要 paper 试跑，先补独立 observation lane 规则和 gap/liquidity/stop/sizing guard。")
    lines.append("- 即便 walk-forward 样本已满 20 日，也只代表 preflight 输入具备；promotion blocker 仍需人工 artifact 审核后逐项清除。")
    lines.append("")
    return "\n".join(lines)


def render_preflight_markdown(summary: dict[str, Any]) -> str:
    preflight = summary["promotion_preflight"]
    lines = [
        f"# {format_date(summary['review_date'])} Shadow Promotion Preflight",
        "",
        "> Artifact-only preflight. It does not activate strategy params, write trade plans, write trades, change positions, or touch timers.",
        "",
        "## Status",
        "",
        f"- Status: {preflight['status']}",
        f"- Candidates: {preflight['candidate_count']}",
        f"- Blockers: {len(preflight['blockers'])}",
        f"- Active params mutated: {preflight['safety']['active_params_mutated']}",
        f"- Paper/live behavior written: {preflight['safety']['writes_paper_live_behavior']}",
        f"- Release gate: {preflight['release_gate']['status']}",
        f"- Timer mutated: {preflight['release_gate']['timer_mutated']}",
        "",
        "## Candidate Gates",
        "",
    ]
    lines.extend(
        table(
            ["Candidate", "Walk-forward", "Paper blockers", "Proposal blockers"],
            [
                [
                    row["candidate_key"],
                    row["walk_forward_progress"].get("status"),
                    len(row["paper_observation_gate"].get("blockers", [])),
                    len(row["strategy_version_gate"].get("blockers", [])),
                ]
                for row in preflight["candidate_gates"]
            ],
        )
    )
    lines.extend(["", "## Top Blockers", ""])
    for blocker, count in list(preflight["blocker_counts"].items())[:20]:
        lines.append(f"- {blocker}: {count}")
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


def candidate_monitor_rows(summary: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for monitor in summary["candidate_monitors"]:
        progress = monitor.get("walk_forward_progress", {})
        comparison = monitor.get("comparison_vs_frozen_cpb", {})
        rows.append(
            [
                monitor["candidate_key"],
                progress.get("status", "-"),
                fmt(progress.get("days")),
                fmt(progress.get("t1_close_mean_pct") or progress.get("next_open_ret_1d_mean_pct")),
                fmt(progress.get("t1_close_win_rate_pct") or progress.get("ret_5d_win_rate_pct")),
                fmt(progress.get("t1_high_mean_pct") or progress.get("watch_mfe_5d_mean_pct")),
                fmt(comparison.get("t1_close_mean_delta_pct")),
            ]
        )
    return rows


def preflight_rows(preflight: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for gate in preflight["candidate_gates"]:
        blockers = gate["paper_observation_gate"].get("blockers", []) + gate["strategy_version_gate"].get("blockers", [])
        rows.append(
            [
                gate["candidate_key"],
                gate["paper_observation_gate"].get("status"),
                gate["strategy_version_gate"].get("status"),
                ", ".join(blockers[:3]) + ("..." if len(blockers) > 3 else ""),
            ]
        )
    return rows


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
