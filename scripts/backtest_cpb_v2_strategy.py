#!/usr/bin/env python3
"""Backtest the optimized CPB strategy.

V2 keeps the original CPB buy point, then adds three practical guards:
1. Exclude securities.
2. Do not chase: buy only when next open is not far above trigger close.
3. For strong elastic names, keep a small swing sleeve so a washout does not
   completely remove names that later start a main move.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from analyze_pgc_event_backtest import MARKET_DIR, load_market, pct, round_num, ret_from_adj


ROOT = Path(__file__).resolve().parents[1]
CPB_SIGNALS_CSV = ROOT / "data" / "contracting_pullback_best_signals.csv"
BIGWIN_SCORES_CSV = ROOT / "data" / "pgc_big_winner_scores.csv"
POOL_JSON = ROOT / "data" / "pgc_pool.json"
CURRENT_SCORES_CSV = ROOT / "data" / "pgc_big_winner_current_scores.csv"
CURRENT_LEVELS_CSV = ROOT / "data" / "pgc_buy_timing_current_levels.csv"
TRADES_OUT = ROOT / "data" / "cpb_v2_strategy_trades.csv"
CURRENT_OUT = ROOT / "data" / "cpb_v2_current_plan.csv"
JSON_OUT = ROOT / "reports" / "cpb_v2_strategy.json"
MD_OUT = ROOT / "reports" / "cpb_v2_strategy.md"

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


def load_industry_map(path: Path) -> dict[str, str]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {row["ts_code"]: row.get("industry", "") for row in rows if row.get("ts_code")}


def attach_context(cpb: pd.DataFrame, scores: pd.DataFrame, industry_map: dict[str, str]) -> pd.DataFrame:
    score_cols = [
        "ts_code",
        "entry_date",
        "bigwin_score",
        "bigwin_grade",
        "entry_price_pos_in_day",
        "buy_total_mv",
        "signal_volume_ratio",
        "range_pos_20",
        "dist_ma20",
        "score_notes",
    ]
    out = cpb.merge(scores[score_cols], on=["ts_code", "entry_date"], how="left")
    out["industry"] = out["ts_code"].map(industry_map).fillna("")

    trigger_closes = []
    gaps = []
    for _, row in out.iterrows():
        close = None
        market = load_market(row["ts_code"], MARKET_DIR)
        if market is not None:
            review_date = str(int(row["review_date"]))
            idx = market.by_date.get(review_date)
            if idx is not None:
                close = float(market.frame.iloc[idx]["close"])
        trigger_closes.append(close)
        gaps.append(float(row["buy_open"]) / close - 1 if close else None)
    out["trigger_close_calc"] = trigger_closes
    out["gap_from_trigger_close"] = gaps
    return out


def is_v2_trade(row: pd.Series) -> bool:
    if row.get("industry") == "证券":
        return False
    if safe(row.get("trigger_age_trading_days"), 0) < 6:
        return False
    gap = safe(row.get("gap_from_trigger_close"))
    if gap is None:
        return False
    return -0.03 <= gap <= 0.02


def is_swing_eligible(row: pd.Series) -> bool:
    if not is_v2_trade(row):
        return False
    if row.get("industry") not in ELASTIC_INDUSTRIES:
        return False
    if safe(row.get("bigwin_score"), 0) < 65:
        return False
    if safe(row.get("score"), 0) < 120:
        return False
    if safe(row.get("bull_body"), 0) < 0.02:
        return False
    if safe(row.get("trigger_pct_chg"), 0) < 0.017:
        return False
    if safe(row.get("trigger_amount_to_ma10"), 0) < 0.75:
        return False
    if safe(row.get("amount_contract_ratio"), 1) > 0.85:
        return False
    return True


def simulate_swing_sleeve(
    ts_code: str,
    buy_date: str,
    take_profit: float = 0.25,
    hard_stop: float = -0.15,
    max_days: int = 20,
) -> dict:
    market = load_market(ts_code, MARKET_DIR)
    if market is None:
        return {"swing_ret": None, "swing_reason": "no_market_data", "swing_exit_date": None, "swing_days": None}
    buy_idx = market.by_date.get(str(buy_date))
    if buy_idx is None:
        return {"swing_ret": None, "swing_reason": "no_buy_date", "swing_exit_date": None, "swing_days": None}

    frame = market.frame
    base = frame.iloc[buy_idx]["adj_open"]
    end_idx = min(len(frame) - 1, buy_idx + max_days)
    if end_idx <= buy_idx:
        return {"swing_ret": None, "swing_reason": "insufficient_data", "swing_exit_date": None, "swing_days": None}

    # A-share T+1: exits start from the next trading day.
    for idx in range(buy_idx + 1, end_idx + 1):
        row = frame.iloc[idx]
        low_ret = ret_from_adj(base, row["adj_low"])
        high_ret = ret_from_adj(base, row["adj_high"])
        if low_ret is not None and high_ret is not None and low_ret <= hard_stop and high_ret >= take_profit:
            return {
                "swing_ret": hard_stop,
                "swing_reason": "both_hit_stop_first",
                "swing_exit_date": row["trade_date"],
                "swing_days": idx - buy_idx,
            }
        if low_ret is not None and low_ret <= hard_stop:
            return {"swing_ret": hard_stop, "swing_reason": "hard_stop", "swing_exit_date": row["trade_date"], "swing_days": idx - buy_idx}
        if high_ret is not None and high_ret >= take_profit:
            return {
                "swing_ret": take_profit,
                "swing_reason": "swing_take_profit",
                "swing_exit_date": row["trade_date"],
                "swing_days": idx - buy_idx,
            }

    exit_row = frame.iloc[end_idx]
    reason = "swing_time_exit" if end_idx == buy_idx + max_days else "latest_available"
    return {
        "swing_ret": ret_from_adj(base, exit_row["adj_close"]),
        "swing_reason": reason,
        "swing_exit_date": exit_row["trade_date"],
        "swing_days": end_idx - buy_idx,
    }


def build_trades(cpb: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in cpb.iterrows():
        item = row.to_dict()
        item["v2_trade"] = is_v2_trade(row)
        item["swing_eligible"] = is_swing_eligible(row)
        swing = simulate_swing_sleeve(row["ts_code"], str(int(row["buy_date"]))) if pd.notna(row.get("buy_date")) else {}
        item.update(swing)

        short_ret = safe(row.get("decision_ret"))
        swing_ret = safe(item.get("swing_ret"))
        if item["v2_trade"] and short_ret is not None:
            if item["swing_eligible"] and swing_ret is not None:
                item["v2_ret"] = short_ret * 0.70 + swing_ret * 0.30
                item["v2_mode"] = "70%短线仓+30%波段观察仓"
            else:
                item["v2_ret"] = short_ret
                item["v2_mode"] = "短线仓"
        else:
            item["v2_ret"] = None
            item["v2_mode"] = "过滤"
        rows.append(item)
    return pd.DataFrame(rows)


def summarize_groups(trades: pd.DataFrame) -> list[dict]:
    groups = [
        ("V1全部CPB", trades["decision_ret"].notna()),
        ("V2过滤后", trades["v2_trade"] & trades["v2_ret"].notna()),
        ("V2短线仓", trades["v2_trade"] & ~trades["swing_eligible"] & trades["v2_ret"].notna()),
        ("V2含观察仓", trades["v2_trade"] & trades["swing_eligible"] & trades["v2_ret"].notna()),
    ]
    rows = []
    for name, mask in groups:
        part = trades[mask]
        rows.append({"group": name, **add_stat("ret", part["v2_ret"] if name.startswith("V2") else part["decision_ret"])})
    return rows


def build_current_plan(current_scores: pd.DataFrame, levels: pd.DataFrame, industry_map: dict[str, str]) -> pd.DataFrame:
    out = current_scores.merge(
        levels[["ts_code", "buy_zone_low", "buy_zone_high", "max_chase_price", "no_buy_above", "action"]],
        on=["ts_code"],
        how="left",
        suffixes=("", "_timing"),
    )
    out["industry"] = out["ts_code"].map(industry_map).fillna("")
    out["is_security"] = out["industry"].eq("证券")

    def current_swing_watch(row: pd.Series) -> bool:
        if row["is_security"]:
            return False
        if row.get("industry") not in ELASTIC_INDUSTRIES:
            return False
        if safe(row.get("trigger_age_trading_days"), 0) < 6:
            return False
        if safe(row.get("bigwin_score"), 0) < 65:
            return False
        if safe(row.get("score"), 0) < 120:
            return False
        if safe(row.get("bull_body"), 0) < 0.02:
            return False
        if safe(row.get("trigger_pct_chg"), 0) < 0.017:
            return False
        if safe(row.get("trigger_amount_to_ma10"), 0) < 0.75:
            return False
        if safe(row.get("amount_contract_ratio"), 1) > 0.85:
            return False
        return True

    out["swing_watch"] = out.apply(current_swing_watch, axis=1)

    def action(row: pd.Series) -> str:
        if row["is_security"]:
            return "剔除"
        if safe(row.get("combined_score"), 0) >= 72:
            return "优先买点"
        if safe(row.get("bigwin_score"), 0) >= 75:
            return "低吸观察"
        if safe(row.get("buy_point_percentile"), 0) >= 0.75:
            return "轻仓交易型"
        return "观察/放弃"

    out["v2_action"] = out.apply(action, axis=1)
    out["position_plan"] = out["swing_watch"].map(
        {True: "不追高成交后:70%短线仓+30%观察仓", False: "短线仓或不做"}
    )
    action_rank = {"优先买点": 1, "低吸观察": 2, "轻仓交易型": 3, "观察/放弃": 4, "剔除": 5}
    out["_action_rank"] = out["v2_action"].map(action_rank).fillna(9)
    cols = [
        "ts_code",
        "name",
        "industry",
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
        "score",
        "swing_watch",
        "position_plan",
        "v2_action",
        "_action_rank",
    ]
    return out[cols].sort_values(["_action_rank", "combined_score", "bigwin_score"], ascending=[True, False, False]).drop(
        columns=["_action_rank"]
    )


def top_rows(trades: pd.DataFrame, metric: str, n: int = 12, ascending: bool = False) -> list[dict]:
    cols = [
        "ts_code",
        "name",
        "industry",
        "entry_date",
        "review_date",
        "buy_date",
        "score",
        "bigwin_score",
        "decision_ret",
        "v2_ret",
        "v2_mode",
        "swing_ret",
        "swing_reason",
    ]
    sample = trades[trades["v2_trade"] & trades[metric].notna()].sort_values(metric, ascending=ascending).head(n)
    return sample[cols].to_dict("records")


def build_report(summary: list[dict], trades: pd.DataFrame, current: pd.DataFrame) -> str:
    summary_table = md_table(
        ["分组", "样本", "胜率", "平均", "中位", "P25", "P75", "最差", "最好"],
        summary,
        lambda r: [
            r["group"],
            r["ret_n"],
            pct(r["ret_win_rate"]),
            pct(r["ret_mean"]),
            pct(r["ret_median"]),
            pct(r["ret_p25"]),
            pct(r["ret_p75"]),
            pct(r["ret_min"]),
            pct(r["ret_max"]),
        ],
    )

    winners = top_rows(trades, "v2_ret", n=12, ascending=False)
    losers = top_rows(trades, "v2_ret", n=10, ascending=True)
    winners_table = md_table(
        ["股票", "行业", "买入日", "CPB分", "潜力分", "V1", "V2", "模式"],
        winners,
        lambda r: [
            r["name"],
            r["industry"],
            int(r["buy_date"]),
            f'{safe(r["score"], 0):.1f}',
            f'{safe(r["bigwin_score"], 0):.0f}',
            pct(r["decision_ret"]),
            pct(r["v2_ret"]),
            r["v2_mode"],
        ],
    )
    losers_table = md_table(
        ["股票", "行业", "买入日", "CPB分", "潜力分", "V1", "V2", "观察仓结果"],
        losers,
        lambda r: [
            r["name"],
            r["industry"],
            int(r["buy_date"]),
            f'{safe(r["score"], 0):.1f}',
            f'{safe(r["bigwin_score"], 0):.0f}',
            pct(r["decision_ret"]),
            pct(r["v2_ret"]),
            pct(r["swing_ret"]),
        ],
    )
    current_table = md_table(
        ["代码", "名称", "行业", "动作", "买区", "+2%上限", "+4%不追", "综合分", "潜力分", "仓位"],
        current.to_dict("records"),
        lambda r: [
            r["ts_code"],
            r["name"],
            r["industry"],
            r["v2_action"],
            f'{safe(r["buy_zone_low"], 0):.2f}-{safe(r["buy_zone_high"], 0):.2f}',
            f'{safe(r["max_chase_price"], 0):.2f}',
            f'{safe(r["no_buy_above"], 0):.2f}',
            f'{safe(r["combined_score"], 0):.1f}',
            f'{safe(r["bigwin_score"], 0):.0f}',
            r["position_plan"],
        ],
    )

    return "\n".join(
        [
            "# CPB V2优化策略",
            "",
            f"- 生成时间: {datetime.now(timezone.utc).isoformat()}",
            "- V2改动: 剔除证券；入池至少6个交易日；次日开盘不追高；强弹性票增加30%观察仓。",
            "- 观察仓不是加杠杆，是把原来会被短线止损完全洗掉的强票，保留一个小仓位观察主升。",
            "- 观察仓规则: 弹性行业、潜力分>=65、CPB分>=120、阳线实体>=2%、确认涨幅>=1.7%、量能不过分偏弱。",
            "- 观察仓退出: 20个交易日内+25%止盈，-15%硬止损，否则到期或用最新可得收盘。",
            "",
            "## 回测对比",
            "",
            summary_table,
            "",
            "## V2收益靠前",
            "",
            winners_table,
            "",
            "## V2亏损靠前",
            "",
            losers_table,
            "",
            "## 当前执行计划",
            "",
            current_table,
            "",
            "## 使用方式",
            "",
            "1. 先用V2过滤: 证券不做；入池不足6天不做；高开超过触发收盘价2%不追。",
            "2. 普通票按短线仓处理，T+2/T+5纪律不变。",
            "3. 强弹性票用70%短线仓+30%观察仓；短线仓止损后，观察仓只看-15%硬止损和+25%波段止盈。",
            "4. 若观察仓触发-15%硬止损，直接移出，不再二次尝试。",
            "",
        ]
    )


def run(args: argparse.Namespace) -> None:
    industry_map = load_industry_map(args.pool)
    cpb = pd.read_csv(args.cpb_signals)
    scores = pd.read_csv(args.bigwin_scores)
    trades = build_trades(attach_context(cpb, scores, industry_map))
    trades.to_csv(args.trades_out, index=False)

    current_scores = pd.read_csv(args.current_scores)
    levels = pd.read_csv(args.current_levels)
    current = build_current_plan(current_scores, levels, industry_map)
    current.to_csv(args.current_out, index=False)

    summary = summarize_groups(trades)
    report = build_report(summary, trades, current)
    Path(args.md_out).write_text(report, encoding="utf-8")
    Path(args.json_out).write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "outputs": {
                    "trades": str(args.trades_out),
                    "current": str(args.current_out),
                    "markdown": str(args.md_out),
                },
                "summary": summary,
                "current": current.to_dict("records"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpb-signals", type=Path, default=CPB_SIGNALS_CSV)
    parser.add_argument("--bigwin-scores", type=Path, default=BIGWIN_SCORES_CSV)
    parser.add_argument("--pool", type=Path, default=POOL_JSON)
    parser.add_argument("--current-scores", type=Path, default=CURRENT_SCORES_CSV)
    parser.add_argument("--current-levels", type=Path, default=CURRENT_LEVELS_CSV)
    parser.add_argument("--trades-out", type=Path, default=TRADES_OUT)
    parser.add_argument("--current-out", type=Path, default=CURRENT_OUT)
    parser.add_argument("--json-out", type=Path, default=JSON_OUT)
    parser.add_argument("--md-out", type=Path, default=MD_OUT)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
