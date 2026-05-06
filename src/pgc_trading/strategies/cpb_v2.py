"""CPB V2 strategy parameters and pure decision helpers."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping


STRATEGY_KEY = "cpb_v2"
STRATEGY_VERSION = "cpb_v2@2026-05-06"
STRATEGY_FAMILY_KEY = "contracting_pullback"


@dataclass(frozen=True)
class CpbV2Params:
    variant_id: str = "cpb_v2"
    excluded_industries: tuple[str, ...] = ("证券",)
    min_trigger_age_trading_days: int = 6
    min_gap_from_trigger_close: float = -0.03
    max_gap_from_trigger_close: float = 0.02
    elastic_industries: tuple[str, ...] = (
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
    )
    min_big_winner_potential_score: float = 65.0
    min_cpb_buy_point_score: float = 120.0
    min_bull_body: float = 0.02
    min_trigger_pct_chg: float = 0.017
    min_trigger_amount_to_ma10: float = 0.75
    max_amount_contract_ratio: float = 0.85
    short_sleeve_weight: float = 0.70
    observation_sleeve_weight: float = 0.30
    short_only_weight: float = 1.0
    observation_take_profit: float = 0.25
    observation_hard_stop: float = -0.15
    observation_max_holding_trading_days: int = 20

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def params_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CpbV2DecisionInput:
    industry: str | None
    trigger_age_trading_days: int | float | None
    gap_from_trigger_close: float | None = None
    trigger_close: float | None = None
    planned_buy_open: float | None = None
    big_winner_potential_score: float | None = None
    cpb_buy_point_score: float | None = None
    bull_body: float | None = None
    trigger_pct_chg: float | None = None
    trigger_amount_to_ma10: float | None = None
    amount_contract_ratio: float | None = None


@dataclass(frozen=True)
class CpbV2Decision:
    eligible: bool
    skip_reason: str | None
    observation_sleeve: bool
    short_sleeve_weight: float
    observation_sleeve_weight: float
    decision_notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PARAMS = CpbV2Params()
PARAMS_HASH = PARAMS.params_hash()
_EPSILON = 1e-12


def is_v2_trade(
    features: CpbV2DecisionInput | Mapping[str, Any],
    params: CpbV2Params = PARAMS,
) -> bool:
    """Return whether visible features pass V2 entry filters."""

    return position_plan(features, params).eligible


def is_swing_eligible(
    features: CpbV2DecisionInput | Mapping[str, Any],
    params: CpbV2Params = PARAMS,
) -> bool:
    """Return whether visible features qualify for the observation sleeve."""

    return position_plan(features, params).observation_sleeve


def position_plan(
    features: CpbV2DecisionInput | Mapping[str, Any],
    params: CpbV2Params = PARAMS,
) -> CpbV2Decision:
    """Build a deterministic V2 entry and sleeve decision from visible features."""

    item = _coerce_input(features)
    entry_skip = _entry_skip_reason(item, params)
    if entry_skip is not None:
        return CpbV2Decision(
            eligible=False,
            skip_reason=entry_skip,
            observation_sleeve=False,
            short_sleeve_weight=0.0,
            observation_sleeve_weight=0.0,
            decision_notes=(entry_skip,),
        )

    observation_skip = _observation_skip_reason(item, params)
    if observation_skip is not None:
        return CpbV2Decision(
            eligible=True,
            skip_reason=None,
            observation_sleeve=False,
            short_sleeve_weight=params.short_only_weight,
            observation_sleeve_weight=0.0,
            decision_notes=("entry_filters_passed", observation_skip, "short_sleeve_only"),
        )

    return CpbV2Decision(
        eligible=True,
        skip_reason=None,
        observation_sleeve=True,
        short_sleeve_weight=params.short_sleeve_weight,
        observation_sleeve_weight=params.observation_sleeve_weight,
        decision_notes=("entry_filters_passed", "observation_sleeve_eligible", "split_70_30"),
    )


def _entry_skip_reason(item: CpbV2DecisionInput, params: CpbV2Params) -> str | None:
    industry = _clean_text(item.industry)
    if not industry:
        return "missing_industry"
    if industry in params.excluded_industries:
        return "excluded_industry"
    trigger_age = _to_float(item.trigger_age_trading_days)
    if trigger_age is None:
        return "missing_trigger_age"
    if trigger_age < params.min_trigger_age_trading_days:
        return "trigger_age_below_min"
    gap = _gap_from_trigger_close(item)
    if gap is None:
        return "missing_gap_from_trigger_close"
    if gap > params.max_gap_from_trigger_close + _EPSILON:
        return "gap_above_max"
    if gap < params.min_gap_from_trigger_close - _EPSILON:
        return "gap_below_min"
    return None


def _observation_skip_reason(item: CpbV2DecisionInput, params: CpbV2Params) -> str | None:
    checks: tuple[tuple[str, bool], ...] = (
        ("non_elastic_industry", _clean_text(item.industry) not in params.elastic_industries),
        (
            "missing_big_winner_potential_score",
            _to_float(item.big_winner_potential_score) is None,
        ),
        (
            "big_winner_potential_score_below_min",
            _below(item.big_winner_potential_score, params.min_big_winner_potential_score),
        ),
        ("missing_cpb_buy_point_score", _to_float(item.cpb_buy_point_score) is None),
        (
            "cpb_buy_point_score_below_min",
            _below(item.cpb_buy_point_score, params.min_cpb_buy_point_score),
        ),
        ("missing_bull_body", _to_float(item.bull_body) is None),
        ("bull_body_below_min", _below(item.bull_body, params.min_bull_body)),
        ("missing_trigger_pct_chg", _to_float(item.trigger_pct_chg) is None),
        ("trigger_pct_chg_below_min", _below(item.trigger_pct_chg, params.min_trigger_pct_chg)),
        ("missing_trigger_amount_to_ma10", _to_float(item.trigger_amount_to_ma10) is None),
        (
            "trigger_amount_to_ma10_below_min",
            _below(item.trigger_amount_to_ma10, params.min_trigger_amount_to_ma10),
        ),
        ("missing_amount_contract_ratio", _to_float(item.amount_contract_ratio) is None),
        (
            "amount_contract_ratio_above_max",
            _above(item.amount_contract_ratio, params.max_amount_contract_ratio),
        ),
    )
    for reason, failed in checks:
        if failed:
            return reason
    return None


def _coerce_input(features: CpbV2DecisionInput | Mapping[str, Any]) -> CpbV2DecisionInput:
    if isinstance(features, CpbV2DecisionInput):
        return features
    return CpbV2DecisionInput(
        industry=_pick(features, "industry"),
        trigger_age_trading_days=_pick(features, "trigger_age_trading_days"),
        gap_from_trigger_close=_pick(features, "gap_from_trigger_close"),
        trigger_close=_pick(features, "trigger_close"),
        planned_buy_open=_pick(features, "planned_buy_open", "next_open", "buy_open"),
        big_winner_potential_score=_pick(features, "big_winner_potential_score", "bigwin_score"),
        cpb_buy_point_score=_pick(features, "cpb_buy_point_score", "score"),
        bull_body=_pick(features, "bull_body"),
        trigger_pct_chg=_pick(features, "trigger_pct_chg"),
        trigger_amount_to_ma10=_pick(features, "trigger_amount_to_ma10"),
        amount_contract_ratio=_pick(features, "amount_contract_ratio"),
    )


def _pick(features: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in features:
            return features[key]
    return None


def _gap_from_trigger_close(item: CpbV2DecisionInput) -> float | None:
    explicit_gap = _to_float(item.gap_from_trigger_close)
    if explicit_gap is not None:
        return explicit_gap
    trigger_close = _to_float(item.trigger_close)
    planned_buy_open = _to_float(item.planned_buy_open)
    if trigger_close is None or planned_buy_open is None or trigger_close == 0:
        return None
    return planned_buy_open / trigger_close - 1


def _below(value: float | int | None, threshold: float) -> bool:
    number = _to_float(value)
    return number is not None and number < threshold


def _above(value: float | int | None, threshold: float) -> bool:
    number = _to_float(value)
    return number is not None and number > threshold


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clean_text(value: str | None) -> str:
    return "" if value is None else str(value).strip()
