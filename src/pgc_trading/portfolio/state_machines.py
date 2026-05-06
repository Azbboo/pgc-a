"""Lifecycle state helpers for portfolio services."""

from __future__ import annotations


BUY_PLAN_ACTION = "buy_next_open"
SELL_PLAN_ACTIONS = {
    "sell_t2_take_profit",
    "sell_t2_stop_loss",
    "sell_t5_timeout",
}

OPEN_POSITION_STATUSES = {
    "open",
    "waiting_t2",
    "need_t2_decision",
    "holding_to_t5",
    "need_t5_exit",
    "planned_exit",
    "partially_closed",
}

TERMINAL_PLAN_STATUSES = {
    "executed",
    "skipped",
    "cancelled",
    "expired",
    "superseded",
}


def is_open_position_status(status: str) -> bool:
    return status in OPEN_POSITION_STATUSES


def can_publish_plan(status: str) -> bool:
    return status == "draft"


def can_cancel_plan(status: str) -> bool:
    return status in {"draft", "active"}


def can_execute_plan(status: str) -> bool:
    return status in {"draft", "active"}


def is_buy_action(action: str) -> bool:
    return action == BUY_PLAN_ACTION


def is_sell_action(action: str) -> bool:
    return action in SELL_PLAN_ACTIONS


def trade_source_allowed_for_account(account_type: str, source: str) -> bool:
    if account_type == "live":
        return source in {"manual", "broker_import"}
    if account_type == "paper":
        return source in {"manual", "model", "paper_model", "correction"}
    if account_type == "backtest":
        return source in {"model", "paper_model"}
    return False
