"""Runtime configuration for the PGC trading system."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class StrategyConfig:
    strategy_id: str = "cpb_6157"
    strategy_version: str = "cpb_6157@2026-05-03"
    params_hash: str = "c4908f5cabe061f4d58fcbdd740f0c255c7c4830f467a9ed1602726688367ddc"
    min_entry_price: float = 10.0
    max_age_trading_days: int = 20
    take_profit_t2: float = 0.03
    stop_loss_t2: float = -0.03
    fallback_exit_day: int = 5


@dataclass(frozen=True)
class AccountConfig:
    account_key: str | None = "paper-main"
    name: str = "Paper Main"
    account_type: str = "paper"
    initial_cash: float = 200000.0
    max_positions: int = 3
    position_sizing: str = "equal_slots"
    status: str = "active"


@dataclass(frozen=True)
class Paths:
    data_dir: Path = ROOT / "data"
    reports_dir: Path = ROOT / "reports"
    db_path: Path = ROOT / "data" / "pgc_trading.db"
    current_candidates_csv: Path = ROOT / "data" / "contracting_pullback_current_candidates.csv"
    trade_calendar_csv: Path = ROOT / "data" / "tushare" / "trade_cal.csv"
    live_plan_md: Path = ROOT / "reports" / "live_trade_plan.md"
    live_plan_json: Path = ROOT / "reports" / "live_trade_plan.json"
