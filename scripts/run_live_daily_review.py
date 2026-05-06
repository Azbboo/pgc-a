#!/usr/bin/env python3
"""Generate the daily live trade plan from the current cpb_6157 candidates."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pgc_trading.config import AccountConfig, Paths, StrategyConfig
from pgc_trading.storage.database import connect, init_db, seed_account
from pgc_trading.strategies.cpb_6157 import PARAMS


def pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"{value * 100:.2f}%"


def next_trade_date(cal_path: Path, after_date: str) -> str | None:
    if not cal_path.exists():
        return None
    cal = pd.read_csv(cal_path, dtype={"cal_date": str, "is_open": str})
    opens = sorted(cal[(cal["is_open"] == "1") & (cal["cal_date"] > str(after_date))]["cal_date"].unique())
    return str(opens[0]) if opens else None


def load_open_positions(account_id: int, db_path: Path) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, ts_code, name, buy_date, buy_price, shares, cost, planned_t2_date, planned_t5_date
            FROM positions
            WHERE account_id = ? AND status = 'open'
            ORDER BY buy_date, id
            """,
            (account_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def build_plan() -> dict:
    paths = Paths()
    strategy = StrategyConfig()
    account = AccountConfig()
    init_db(paths.db_path)
    account_id = seed_account(account, paths.db_path)
    open_positions = load_open_positions(account_id, paths.db_path)

    candidates = pd.DataFrame()
    if paths.current_candidates_csv.exists() and paths.current_candidates_csv.stat().st_size:
        candidates = pd.read_csv(paths.current_candidates_csv, dtype={"review_date": str, "entry_date": str})

    latest_review_date = None
    top_candidate = None
    if not candidates.empty:
        latest_review_date = str(candidates["review_date"].max())
        latest = candidates[candidates["review_date"] == latest_review_date].copy()
        latest = latest.sort_values(["score", "ts_code"], ascending=[False, True])
        top_candidate = latest.iloc[0].to_dict() if not latest.empty else None

    calendar_next = next_trade_date(paths.trade_calendar_csv, latest_review_date) if latest_review_date else None
    free_slots = max(account.max_positions - len(open_positions), 0)
    plan_action = "no_signal"
    if top_candidate and free_slots > 0:
        plan_action = "plan_buy_next_open"
    elif top_candidate:
        plan_action = "skip_max_positions"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "strategy": strategy.strategy_id,
        "strategy_version": strategy.strategy_version,
        "params": PARAMS.to_dict(),
        "account": {
            "id": account_id,
            "name": account.name,
            "initial_cash": account.initial_cash,
            "max_positions": account.max_positions,
            "open_positions": len(open_positions),
            "free_slots": free_slots,
        },
        "latest_review_date": latest_review_date,
        "next_trade_date_from_calendar": calendar_next,
        "plan_action": plan_action,
        "top_candidate": top_candidate,
        "open_positions": open_positions,
        "candidate_count": int(len(candidates[candidates["review_date"] == latest_review_date])) if latest_review_date else 0,
    }


def render_markdown(plan: dict) -> str:
    candidate = plan["top_candidate"]
    next_date = plan["next_trade_date_from_calendar"] or "交易日历未覆盖，请先刷新 Tushare trade_cal"
    if candidate:
        candidate_text = (
            f"{candidate['ts_code']} {candidate['name']}，评分 {candidate['score']}，"
            f"复盘日 {candidate['review_date']}，触发收盘 {candidate['trigger_close']}，"
            f"阳线实体 {pct(float(candidate['bull_body']))}，缩量比 {float(candidate['amount_contract_ratio']):.2f}"
        )
    else:
        candidate_text = "无"

    if plan["plan_action"] == "plan_buy_next_open":
        action_text = f"计划在下一交易日开盘买入。日历推算买入日：{next_date}"
    elif plan["plan_action"] == "skip_max_positions":
        action_text = "有信号，但当前已无空闲仓位，跳过新买入。"
    else:
        action_text = "无买入信号。"

    positions = plan["open_positions"]
    if positions:
        pos_lines = ["| 股票 | 买入日 | 买入价 | 股数 | 成本 | T+2计划 | T+5计划 |", "| --- | --- | ---: | ---: | ---: | --- | --- |"]
        for pos in positions:
            pos_lines.append(
                f"| {pos['ts_code']} {pos['name']} | {pos['buy_date']} | {pos['buy_price']} | "
                f"{pos['shares']} | {pos['cost']} | {pos['planned_t2_date'] or ''} | {pos['planned_t5_date'] or ''} |"
            )
        position_text = "\n".join(pos_lines)
    else:
        position_text = "当前数据库无未平仓持仓。"

    return f"""# PGC 实盘每日交易计划

生成时间：{plan["generated_at"]}

## 账户

- 账户：{plan["account"]["name"]}
- 最大持仓：{plan["account"]["max_positions"]}
- 当前持仓：{plan["account"]["open_positions"]}
- 空闲仓位：{plan["account"]["free_slots"]}

## 今日信号

- 策略：{plan["strategy"]}
- 最新复盘日：{plan["latest_review_date"]}
- 当日候选数：{plan["candidate_count"]}
- 最高分候选：{candidate_text}

## 明日计划

{action_text}

## 当前持仓

{position_text}
"""


def main() -> int:
    paths = Paths()
    plan = build_plan()
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    paths.live_plan_json.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths.live_plan_md.write_text(render_markdown(plan), encoding="utf-8")
    print(json.dumps({"plan_action": plan["plan_action"], "out_md": str(paths.live_plan_md)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
