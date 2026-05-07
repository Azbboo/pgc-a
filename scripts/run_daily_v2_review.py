#!/usr/bin/env python3
"""Generate a daily PGC review and next-day V2 plan."""

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

from analyze_pgc_event_backtest import MARKET_DIR, RAW_EVENTS_PATH, load_events, load_market, pct, round_num
from deep_dive_contracting_pullback import build_param_grid, latest_current_candidates
from score_pgc_big_winner_potential import score_big_winner_potential


POOL_JSON = ROOT / "data" / "pgc_pool.json"
EVENT_BACKTEST_CSV = ROOT / "data" / "pgc_event_backtest.csv"
PREVIOUS_PLAN_CSV = ROOT / "data" / "cpb_v2_current_plan.csv"
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"

ELASTIC_INDUSTRIES = {
    "半导体",
    "元器件",
    "通信设备",
    "电气设备",
    "专用机械",
    "软件服务",
    "IT设备",
    "汽车配件",
    "医疗保健",
    "电器仪表",
    "工程机械",
    "机械基件",
    "互联网",
}


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


def load_industry_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {row["ts_code"]: row.get("industry", "") for row in rows if row.get("ts_code")}


def latest_trade_date(events: pd.DataFrame) -> str:
    dates = []
    for ts_code in events["ts_code"].dropna().unique():
        market = load_market(ts_code, MARKET_DIR)
        if market is None or market.frame.empty:
            continue
        dates.append(str(market.frame.iloc[-1]["trade_date"]))
    if not dates:
        raise ValueError("No market data found.")
    return max(dates)


def next_trade_date(after_date: str) -> str | None:
    path = MARKET_DIR / "trade_cal.csv"
    if not path.exists():
        return None
    cal = pd.read_csv(path, dtype={"cal_date": str, "is_open": str})
    opens = sorted(cal[(cal["is_open"] == "1") & (cal["cal_date"] > str(after_date))]["cal_date"].unique())
    return str(opens[0]) if opens else None


def pool_performance(events: pd.DataFrame, industry_map: dict[str, str], review_date: str) -> pd.DataFrame:
    rows = []
    for _, event in events.iterrows():
        market = load_market(event["ts_code"], MARKET_DIR)
        if market is None:
            continue
        idx = market.by_date.get(str(review_date))
        if idx is None:
            continue
        row = market.frame.iloc[idx]
        entry_price = float(event["entry_price"])
        rows.append(
            {
                "event_id": event.get("event_id"),
                "ts_code": event["ts_code"],
                "name": event["name"],
                "industry": industry_map.get(event["ts_code"], ""),
                "entry_date": str(event["entry_date"]),
                "entry_price": entry_price,
                "trade_date": row["trade_date"],
                "open": round_num(row["open"], 2),
                "high": round_num(row["high"], 2),
                "low": round_num(row["low"], 2),
                "close": round_num(row["close"], 2),
                "pct_chg": round_num(row["pct_chg"] / 100 if pd.notna(row.get("pct_chg")) else None),
                "amount": round_num(row["amount"], 2),
                "ret_from_entry": round_num(row["close"] / entry_price - 1) if entry_price else None,
            }
        )
    return pd.DataFrame(rows)


def plan_performance(previous_plan: pd.DataFrame, review_date: str) -> pd.DataFrame:
    rows = []
    if previous_plan.empty:
        return pd.DataFrame()
    for _, plan in previous_plan.iterrows():
        market = load_market(plan["ts_code"], MARKET_DIR)
        if market is None:
            continue
        idx = market.by_date.get(str(review_date))
        if idx is None:
            continue
        row = market.frame.iloc[idx]
        zone_low = float(plan["buy_zone_low"])
        zone_high = float(plan["buy_zone_high"])
        max_chase = float(plan["max_chase_price"])
        no_buy_above = float(plan["no_buy_above"])
        touched_zone = bool(row["low"] <= zone_high and row["high"] >= zone_low)
        open_ok = bool(row["open"] <= max_chase)
        if touched_zone:
            assumed_buy = min(max(float(row["open"]), zone_low), zone_high)
        elif open_ok and row["open"] <= max_chase:
            assumed_buy = float(row["open"])
        else:
            assumed_buy = None
        rows.append(
            {
                "ts_code": plan["ts_code"],
                "name": plan["name"],
                "industry": plan.get("industry", ""),
                "prior_action": plan.get("v2_action", plan.get("action", "")),
                "position_plan": plan.get("position_plan", ""),
                "trigger_close": float(plan["trigger_close"]),
                "buy_zone_low": zone_low,
                "buy_zone_high": zone_high,
                "max_chase_price": max_chase,
                "no_buy_above": no_buy_above,
                "trade_date": review_date,
                "open": round_num(row["open"], 2),
                "high": round_num(row["high"], 2),
                "low": round_num(row["low"], 2),
                "close": round_num(row["close"], 2),
                "pct_chg": round_num(row["pct_chg"] / 100 if pd.notna(row.get("pct_chg")) else None),
                "open_vs_trigger": round_num(row["open"] / float(plan["trigger_close"]) - 1),
                "close_vs_trigger": round_num(row["close"] / float(plan["trigger_close"]) - 1),
                "touched_buy_zone": touched_zone,
                "open_ok": open_ok,
                "assumed_buy": round_num(assumed_buy, 2),
                "close_ret_from_assumed_buy": round_num(row["close"] / assumed_buy - 1) if assumed_buy else None,
            }
        )
    return pd.DataFrame(rows)


def score_candidates(candidates: pd.DataFrame, industry_map: dict[str, str]) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    event_backtest = pd.read_csv(EVENT_BACKTEST_CSV, dtype={"entry_date": str})
    candidates = candidates.copy()
    candidates["entry_date"] = candidates["entry_date"].astype(str)
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
    ]
    out = candidates.merge(event_backtest[feature_cols], on=["ts_code", "entry_date"], how="left")
    score_cols = out.apply(score_big_winner_potential, axis=1, result_type="expand")
    out = pd.concat([out, score_cols], axis=1)
    out["industry"] = out["ts_code"].map(industry_map).fillna("")
    out["buy_zone_low"] = (out["trigger_close"] * 0.98).round(2)
    out["buy_zone_high"] = out["trigger_close"].round(2)
    out["max_chase_price"] = (out["trigger_close"] * 1.02).round(2)
    out["no_buy_above"] = (out["trigger_close"] * 1.04).round(2)
    out["financial_flag"] = out["industry"].eq("证券")

    def swing_watch(row: pd.Series) -> bool:
        return bool(
            row["industry"] in ELASTIC_INDUSTRIES
            and safe(row.get("bigwin_score"), 0) >= 65
            and safe(row.get("score"), 0) >= 120
            and safe(row.get("bull_body"), 0) >= 0.02
            and safe(row.get("trigger_pct_chg"), 0) >= 0.017
            and safe(row.get("trigger_amount_to_ma10"), 0) >= 0.75
            and safe(row.get("amount_contract_ratio"), 1) <= 0.85
        )

    out["swing_watch"] = out.apply(swing_watch, axis=1)

    def action(row: pd.Series) -> str:
        if row["industry"] == "证券":
            return "剔除"
        if safe(row.get("bigwin_score"), 0) >= 75 and safe(row.get("score"), 0) >= 125:
            return "优先买点"
        if safe(row.get("bigwin_score"), 0) >= 65:
            return "低吸观察"
        if safe(row.get("score"), 0) >= 128:
            return "交易型轻仓"
        return "观察/放弃"

    out["v2_action"] = out.apply(action, axis=1)
    out["position_plan"] = out["swing_watch"].map(
        {True: "不追高成交后:70%短线+30%观察", False: "短线仓或不做"}
    )
    order = {"优先买点": 1, "低吸观察": 2, "交易型轻仓": 3, "观察/放弃": 4, "剔除": 5}
    out["_rank"] = out["v2_action"].map(order).fillna(9)
    return out.sort_values(["_rank", "score", "bigwin_score"], ascending=[True, False, False]).drop(columns=["_rank"])


def daily_summary(pool: pd.DataFrame) -> dict:
    return {
        "n": int(len(pool)),
        "up": int((pool["pct_chg"] > 0).sum()),
        "flat": int((pool["pct_chg"] == 0).sum()),
        "down": int((pool["pct_chg"] < 0).sum()),
        "avg_pct_chg": round_num(pool["pct_chg"].mean()),
        "median_pct_chg": round_num(pool["pct_chg"].median()),
        "limit_up_like": int((pool["pct_chg"] >= 0.099).sum()),
        "limit_down_like": int((pool["pct_chg"] <= -0.099).sum()),
    }


def render_report(
    review_date: str,
    next_date: str | None,
    variant_id: str,
    pool: pd.DataFrame,
    prior: pd.DataFrame,
    candidates: pd.DataFrame,
    ref_candidates: pd.DataFrame,
) -> str:
    summary = daily_summary(pool)
    top_gainers = pool.sort_values("pct_chg", ascending=False).head(12).to_dict("records")
    top_losers = pool.sort_values("pct_chg", ascending=True).head(10).to_dict("records")
    long_winners = pool.sort_values("ret_from_entry", ascending=False).head(10).to_dict("records")

    summary_lines = [
        f"- 复盘日: {review_date}",
        f"- 明日交易日: {next_date or '交易日历未覆盖'}",
        f"- 池内样本: {summary['n']}",
        f"- 上涨/平/下跌: {summary['up']}/{summary['flat']}/{summary['down']}",
        f"- 平均涨跌幅: {pct(summary['avg_pct_chg'])}",
        f"- 中位涨跌幅: {pct(summary['median_pct_chg'])}",
        f"- 近似涨停/跌停: {summary['limit_up_like']}/{summary['limit_down_like']}",
        f"- 主策略参数: 冻结 {variant_id}",
    ]

    prior_table = "无上一交易计划记录。"
    if not prior.empty:
        prior_table = md_table(
            ["股票", "动作", "开盘", "最高", "最低", "收盘", "涨跌", "触达买区", "收盘/假定买入"],
            prior.to_dict("records"),
            lambda r: [
                r["name"],
                r["prior_action"],
                f'{safe(r["open"], 0):.2f}',
                f'{safe(r["high"], 0):.2f}',
                f'{safe(r["low"], 0):.2f}',
                f'{safe(r["close"], 0):.2f}',
                pct(r["pct_chg"]),
                "是" if r["touched_buy_zone"] else "否",
                pct(r["close_ret_from_assumed_buy"]),
            ],
        )

    candidate_table = "无主策略候选。"
    if not candidates.empty:
        candidate_table = md_table(
            ["股票", "行业", "动作", "触发价", "买区", "+2%上限", "+4%不追", "CPB分", "潜力分", "仓位"],
            candidates.to_dict("records"),
            lambda r: [
                f'{r["ts_code"]} {r["name"]}',
                r["industry"],
                r["v2_action"],
                f'{safe(r["trigger_close"], 0):.2f}',
                f'{safe(r["buy_zone_low"], 0):.2f}-{safe(r["buy_zone_high"], 0):.2f}',
                f'{safe(r["max_chase_price"], 0):.2f}',
                f'{safe(r["no_buy_above"], 0):.2f}',
                f'{safe(r["score"], 0):.1f}',
                f'{safe(r["bigwin_score"], 0):.0f}',
                r["position_plan"],
            ],
        )

    ref_table = "无参考候选。"
    if not ref_candidates.empty:
        ref_table = md_table(
            ["股票", "行业", "触发价", "CPB分", "潜力分", "备注"],
            ref_candidates.to_dict("records"),
            lambda r: [
                f'{r["ts_code"]} {r["name"]}',
                r["industry"],
                f'{safe(r["trigger_close"], 0):.2f}',
                f'{safe(r["score"], 0):.1f}',
                f'{safe(r["bigwin_score"], 0):.0f}',
                r["v2_action"],
            ],
        )

    return "\n".join(
        [
            f"# PGC每日复盘 {review_date}",
            "",
            *summary_lines,
            "",
            "## 今日池内涨幅靠前",
            "",
            md_table(
                ["股票", "行业", "收盘", "涨跌", "入池以来"],
                top_gainers,
                lambda r: [f'{r["ts_code"]} {r["name"]}', r["industry"], f'{safe(r["close"], 0):.2f}', pct(r["pct_chg"]), pct(r["ret_from_entry"])],
            ),
            "",
            "## 今日池内跌幅靠前",
            "",
            md_table(
                ["股票", "行业", "收盘", "涨跌", "入池以来"],
                top_losers,
                lambda r: [f'{r["ts_code"]} {r["name"]}', r["industry"], f'{safe(r["close"], 0):.2f}', pct(r["pct_chg"]), pct(r["ret_from_entry"])],
            ),
            "",
            "## 入池以来表现靠前",
            "",
            md_table(
                ["股票", "行业", "收盘", "今日", "入池以来"],
                long_winners,
                lambda r: [f'{r["ts_code"]} {r["name"]}', r["industry"], f'{safe(r["close"], 0):.2f}', pct(r["pct_chg"]), pct(r["ret_from_entry"])],
            ),
            "",
            "## 今日计划执行复盘",
            "",
            prior_table,
            "",
            "## 明日主计划",
            "",
            candidate_table,
            "",
            "## 参数重搜参考",
            "",
            "这部分只作参考，不直接替换冻结策略，避免每日重选参数造成过拟合。",
            "",
            ref_table,
            "",
            "## 执行规则",
            "",
            "1. 不追高: 明日开盘高于+2%上限，不追；高于+4%直接视为错过。",
            "2. 只排除证券；多元金融按正常候选评分执行。",
            "3. 观察仓只给弹性行业且潜力分、CPB分都合格的票；短线仓按T+2/T+5纪律。",
            "4. 今日新重搜参数只作观察，不用于替换冻结V2。",
            "",
        ]
    )


def run(args: argparse.Namespace) -> None:
    events = load_events(Path(args.events))
    review_date = args.date or latest_trade_date(events)
    industry_map = load_industry_map(args.pool)
    next_date = args.next_date or next_trade_date(review_date)

    markets = {ts_code: load_market(ts_code, MARKET_DIR) for ts_code in sorted(events["ts_code"].dropna().unique())}
    variant_idx = int(args.variant_id.split("_")[1]) - 1
    params = build_param_grid()[variant_idx]
    candidates = latest_current_candidates(events, markets, params)
    candidates = score_candidates(candidates, industry_map)

    ref_idx = int(args.reference_variant_id.split("_")[1]) - 1
    ref_candidates = latest_current_candidates(events, markets, build_param_grid()[ref_idx])
    ref_candidates = score_candidates(ref_candidates, industry_map)

    pool = pool_performance(events, industry_map, review_date)
    previous_plan = pd.read_csv(args.previous_plan) if Path(args.previous_plan).exists() else pd.DataFrame()
    prior = plan_performance(previous_plan, review_date)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    pool_out = DATA_DIR / f"daily_review_{review_date}_pool_performance.csv"
    prior_out = DATA_DIR / f"daily_review_{review_date}_prior_plan.csv"
    candidates_out = DATA_DIR / f"daily_review_{review_date}_v2_candidates.csv"
    ref_out = DATA_DIR / f"daily_review_{review_date}_reference_candidates.csv"
    report_out = REPORTS_DIR / f"daily_review_{review_date}.md"
    json_out = REPORTS_DIR / f"daily_review_{review_date}.json"

    pool.to_csv(pool_out, index=False)
    prior.to_csv(prior_out, index=False)
    candidates.to_csv(candidates_out, index=False)
    ref_candidates.to_csv(ref_out, index=False)
    report = render_report(review_date, next_date, args.variant_id, pool, prior, candidates, ref_candidates)
    report_out.write_text(report, encoding="utf-8")
    json_out.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "review_date": review_date,
                "next_trade_date": next_date,
                "variant_id": args.variant_id,
                "reference_variant_id": args.reference_variant_id,
                "outputs": {
                    "pool": str(pool_out),
                    "prior_plan": str(prior_out),
                    "candidates": str(candidates_out),
                    "reference_candidates": str(ref_out),
                    "report": str(report_out),
                },
                "pool_summary": daily_summary(pool),
                "candidates": candidates.to_dict("records"),
                "reference_candidates": ref_candidates.to_dict("records"),
                "prior_plan": prior.to_dict("records"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"report": str(report_out), "candidates": len(candidates), "pool": len(pool)}, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="Review date YYYYMMDD. Defaults to latest cached trade date.")
    parser.add_argument("--next-date", help="Next trade date YYYYMMDD when the cached calendar does not cover future dates.")
    parser.add_argument("--events", default=str(RAW_EVENTS_PATH))
    parser.add_argument("--pool", type=Path, default=POOL_JSON)
    parser.add_argument("--previous-plan", type=Path, default=PREVIOUS_PLAN_CSV)
    parser.add_argument("--variant-id", default="cpb_6157")
    parser.add_argument("--reference-variant-id", default="cpb_5240")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
