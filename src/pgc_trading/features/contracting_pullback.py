"""Contracting-pullback feature calculation.

The functions in this module are pure and only use the market bars supplied by
the caller. DailyReviewService is responsible for passing bars capped at the
review date.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from pgc_trading.strategies.cpb_6157 import Cpb6157Params, PARAMS


FEATURE_VERSION = "contracting_pullback.v1"
MIN_ENTRY_PRICE = 10.0


@dataclass(frozen=True)
class RawEventInput:
    id: int
    ts_code: str
    code: str | None
    name: str
    entry_date: str
    entry_time: str | None
    entry_price: float


@dataclass(frozen=True)
class MarketBarInput:
    ts_code: str
    trade_date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    vol: float | None = None
    amount: float | None = None
    adj_open: float | None = None
    adj_high: float | None = None
    adj_low: float | None = None
    adj_close: float | None = None


@dataclass(frozen=True)
class ContractingPullbackSnapshot:
    raw_event_id: int
    ts_code: str
    review_date: str
    feature_version: str
    features: dict[str, Any]
    input_hash: str

    @property
    def signal_passed(self) -> bool:
        return bool(self.features.get("signal_passed", False))

    @property
    def score(self) -> float | None:
        value = self.features.get("score")
        return None if value is None else float(value)


@dataclass(frozen=True)
class _PreparedBar:
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    amount: float
    adj_open: float
    adj_high: float
    adj_low: float
    adj_close: float
    pct_chg: float | None


def build_contracting_pullback_snapshot(
    event: RawEventInput,
    bars: Sequence[MarketBarInput],
    review_date: str,
    params: Cpb6157Params = PARAMS,
    min_entry_price: float = MIN_ENTRY_PRICE,
) -> ContractingPullbackSnapshot:
    """Build a deterministic feature snapshot for one raw event."""

    prepared = _prepare_bars(bars, review_date)
    input_hash = _feature_input_hash(event, prepared, review_date, params, min_entry_price)
    features = _base_features(event, prepared, review_date, min_entry_price)

    invalid_reason = _precheck_invalid_reason(event, prepared, review_date, min_entry_price)
    if invalid_reason is not None:
        features["invalid_reason"] = invalid_reason
        return ContractingPullbackSnapshot(
            raw_event_id=event.id,
            ts_code=event.ts_code,
            review_date=review_date,
            feature_version=FEATURE_VERSION,
            features=features,
            input_hash=input_hash,
        )

    by_date = {bar.trade_date: idx for idx, bar in enumerate(prepared)}
    signal_idx = by_date[event.entry_date]
    review_idx = by_date[review_date]
    passed, setup_features = _detect_contracting_pullback(prepared, signal_idx, review_idx, params)
    if not passed:
        features["invalid_reason"] = "contracting_pullback_not_detected"
        return ContractingPullbackSnapshot(
            raw_event_id=event.id,
            ts_code=event.ts_code,
            review_date=review_date,
            feature_version=FEATURE_VERSION,
            features=features,
            input_hash=input_hash,
        )

    score = _score_candidate(event, setup_features)
    features.update(setup_features)
    features.update(
        {
            "signal_passed": True,
            "invalid_reason": None,
            "score": score,
        }
    )
    return ContractingPullbackSnapshot(
        raw_event_id=event.id,
        ts_code=event.ts_code,
        review_date=review_date,
        feature_version=FEATURE_VERSION,
        features=features,
        input_hash=input_hash,
    )


def features_json(features: dict[str, Any]) -> str:
    return _json_dumps(features)


def _prepare_bars(
    bars: Sequence[MarketBarInput],
    review_date: str,
) -> list[_PreparedBar]:
    capped = sorted((bar for bar in bars if bar.trade_date <= review_date), key=lambda item: item.trade_date)
    prepared: list[_PreparedBar] = []
    previous_close: float | None = None
    for bar in capped:
        open_price = _coalesce_number(bar.adj_open, bar.open)
        high = _coalesce_number(bar.adj_high, bar.high)
        low = _coalesce_number(bar.adj_low, bar.low)
        close = _coalesce_number(bar.adj_close, bar.close)
        raw_open = _coalesce_number(bar.open, bar.adj_open)
        raw_high = _coalesce_number(bar.high, bar.adj_high)
        raw_low = _coalesce_number(bar.low, bar.adj_low)
        raw_close = _coalesce_number(bar.close, bar.adj_close)
        amount = _coalesce_number(bar.amount, 0.0)
        if (
            open_price is None
            or high is None
            or low is None
            or close is None
            or raw_open is None
            or raw_high is None
            or raw_low is None
            or raw_close is None
            or amount is None
        ):
            previous_close = close
            continue
        pct_chg = _ret(previous_close, close) if previous_close else None
        prepared.append(
            _PreparedBar(
                trade_date=bar.trade_date,
                open=raw_open,
                high=raw_high,
                low=raw_low,
                close=raw_close,
                amount=amount,
                adj_open=open_price,
                adj_high=high,
                adj_low=low,
                adj_close=close,
                pct_chg=pct_chg,
            )
        )
        previous_close = close
    return prepared


def _base_features(
    event: RawEventInput,
    bars: list[_PreparedBar],
    review_date: str,
    min_entry_price: float,
) -> dict[str, Any]:
    return {
        "feature_name": "contracting_pullback_bullish",
        "review_date": review_date,
        "raw_event_id": event.id,
        "ts_code": event.ts_code,
        "entry_date": event.entry_date,
        "entry_price": round(float(event.entry_price), 6),
        "min_entry_price": min_entry_price,
        "bars_used": len(bars),
        "latest_bar_date": bars[-1].trade_date if bars else None,
        "signal_passed": False,
        "score": None,
    }


def _precheck_invalid_reason(
    event: RawEventInput,
    bars: list[_PreparedBar],
    review_date: str,
    min_entry_price: float,
) -> str | None:
    by_date = {bar.trade_date: idx for idx, bar in enumerate(bars)}
    if review_date not in by_date:
        return "review_bar_missing"
    if event.entry_date not in by_date:
        return "entry_bar_missing"
    if float(event.entry_price) < min_entry_price:
        return "entry_price_below_min"
    signal_idx = by_date[event.entry_date]
    review_idx = by_date[review_date]
    if review_idx < signal_idx + 3:
        return "insufficient_post_entry_bars"
    return None


def _detect_contracting_pullback(
    bars: list[_PreparedBar],
    signal_idx: int,
    review_idx: int,
    params: Cpb6157Params,
) -> tuple[bool, dict[str, Any]]:
    row = bars[review_idx]
    prev = bars[review_idx - 1]
    entry = bars[signal_idx]
    amount_ma10 = _moving_average([bar.amount for bar in bars], review_idx, window=10, min_periods=5)
    if amount_ma10 is None or amount_ma10 <= 0:
        return False, {}

    for lookback in range(2, 7):
        start = review_idx - lookback
        if start <= signal_idx:
            continue
        pullback = bars[start:review_idx]
        if len(pullback) < 2:
            continue

        first_amount = pullback[0].amount
        last_amount = pullback[-1].amount
        first_close = pullback[0].adj_close
        last_close = pullback[-1].adj_close
        if first_amount <= 0 or first_close <= 0:
            continue

        amount_ratio = last_amount / first_amount
        avg_amount_ratio = sum(bar.amount for bar in pullback) / len(pullback) / amount_ma10
        close_pullback = last_close / first_close - 1
        down_days = sum(
            1
            for left, right in zip(pullback, pullback[1:])
            if right.adj_close - left.adj_close <= 0
        )
        peak_before = max(bar.adj_high for bar in bars[signal_idx:review_idx])
        drawdown_from_peak = _ret(peak_before, last_close)
        bullish_body = _ret(row.adj_open, row.adj_close)
        close_recover = _ret(prev.adj_close, row.adj_close)
        entry_runup = _ret(entry.adj_close, row.adj_close)
        trigger_amount_to_ma10 = row.amount / amount_ma10 if amount_ma10 else None
        low_holds = row.adj_low >= min(bar.adj_low for bar in pullback) * 0.992

        if (
            drawdown_from_peak is not None
            and bullish_body is not None
            and close_recover is not None
            and entry_runup is not None
            and trigger_amount_to_ma10 is not None
            and amount_ratio <= params.contract_max
            and avg_amount_ratio <= params.avg_amount_max
            and close_pullback <= -0.015
            and params.min_drawdown <= abs(drawdown_from_peak) <= params.max_drawdown
            and down_days >= max(1, lookback - 2)
            and bullish_body >= params.bull_body_min
            and close_recover >= params.close_recover_min
            and low_holds
            and row.amount >= last_amount * 0.90
            and trigger_amount_to_ma10 <= params.trigger_amount_max
            and (row.pct_chg or 0.0) >= params.pct_chg_min
            and entry_runup <= params.max_entry_runup
        ):
            return True, {
                "pullback_days": lookback,
                "amount_contract_ratio": _round(amount_ratio),
                "avg_amount_to_ma10": _round(avg_amount_ratio),
                "pullback_close_ret": _round(close_pullback),
                "drawdown_from_peak": _round(drawdown_from_peak),
                "bull_body": _round(bullish_body),
                "close_recover": _round(close_recover),
                "trigger_pct_chg": _round(row.pct_chg),
                "trigger_amount_to_ma10": _round(trigger_amount_to_ma10),
                "entry_runup": _round(entry_runup),
                "trigger_close": _round(row.close),
                "trigger_amount": _round(row.amount),
                "amount_ma10": _round(amount_ma10),
            }
    return False, {}


def _score_candidate(event: RawEventInput, features: dict[str, Any]) -> float:
    price = float(event.entry_price)
    score = 100.0
    if price < 10:
        score -= 10
    elif 20 <= price <= 100:
        score += 8
    else:
        score += 3
    score += _cap((0.82 - _safe(features.get("amount_contract_ratio"), 0.82)) * 35, -4, 12)
    score += _cap(10 - abs(abs(_safe(features.get("drawdown_from_peak"), -0.08)) - 0.08) * 120, -5, 10)
    score += _cap(_safe(features.get("bull_body"), 0.0) * 180, 0, 12)
    score += _cap(_safe(features.get("trigger_pct_chg"), 0.0) * 80, 0, 8)
    return round(score, 4)


def _feature_input_hash(
    event: RawEventInput,
    bars: list[_PreparedBar],
    review_date: str,
    params: Cpb6157Params,
    min_entry_price: float,
) -> str:
    payload = {
        "event": asdict(event),
        "review_date": review_date,
        "params": params.to_dict(),
        "min_entry_price": min_entry_price,
        "bars": [asdict(bar) for bar in bars],
    }
    return hashlib.sha256(_json_dumps(payload).encode("utf-8")).hexdigest()


def _moving_average(
    values: list[float],
    idx: int,
    window: int,
    min_periods: int,
) -> float | None:
    start = max(0, idx - window + 1)
    sample = values[start : idx + 1]
    if len(sample) < min_periods:
        return None
    return sum(sample) / len(sample)


def _ret(base: float | None, value: float | None) -> float | None:
    if base is None or value is None or base == 0:
        return None
    return value / base - 1


def _safe(value: Any, default: float) -> float:
    return default if value is None else float(value)


def _cap(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)


def _coalesce_number(*values: float | int | None) -> float | None:
    for value in values:
        if value is not None:
            return float(value)
    return None


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
