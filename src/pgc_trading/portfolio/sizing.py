"""Position sizing helpers for portfolio services."""

from __future__ import annotations

from dataclasses import dataclass


BOARD_LOT_SIZE = 100


@dataclass(frozen=True)
class SizingPlan:
    planned_cash: float | None
    planned_shares: int | None
    free_position_slots: int
    price_reference: float | None = None


def free_position_slots(max_positions: int, open_positions: int) -> int:
    return max(max_positions - open_positions, 0)


def equal_slot_cash(cash: float, free_slots: int) -> float | None:
    if cash <= 0 or free_slots <= 0:
        return None
    return cash / free_slots


def floor_board_lot_shares(
    cash: float | None,
    price: float | None,
    lot_size: int = BOARD_LOT_SIZE,
) -> int | None:
    if cash is None or price is None:
        return None
    if cash <= 0 or price <= 0 or lot_size <= 0:
        return 0
    lots = int(cash // (price * lot_size))
    return lots * lot_size


def plan_equal_slot_sizing(
    *,
    cash: float,
    max_positions: int,
    open_positions: int,
    price_reference: float | None = None,
    lot_size: int = BOARD_LOT_SIZE,
) -> SizingPlan:
    slots = free_position_slots(max_positions, open_positions)
    planned_cash = equal_slot_cash(cash, slots)
    planned_shares = floor_board_lot_shares(planned_cash, price_reference, lot_size)
    return SizingPlan(
        planned_cash=planned_cash,
        planned_shares=planned_shares,
        free_position_slots=slots,
        price_reference=price_reference,
    )
