"""CPB V2 feature input enrichment.

This module stays pure: callers provide already-visible CPB shape features and
optional persisted context. It never reads research CSVs or market data files.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from pgc_trading.strategies.cpb_v2 import (
    CpbV2DecisionInput,
    CpbV2Params,
    PARAMS,
    position_plan,
)


FEATURE_VERSION = "contracting_pullback.cpb_v2_inputs.v1"
CONTEXT_FEATURE_VERSIONS = ("cpb_v2.context.v1", "big_winner_potential.v1")

_FUTURE_LABEL_TOKENS = (
    "future",
    "label",
    "mfe",
    "mae",
    "ret_",
    "_ret",
)


@dataclass(frozen=True)
class CpbV2FeatureEnrichment:
    features: dict[str, Any]
    input_hash: str


def build_cpb_v2_feature_enrichment(
    base_features: Mapping[str, Any],
    *,
    base_input_hash: str,
    trigger_age_trading_days: int | None,
    planned_buy_date: str | None,
    context: Mapping[str, Any] | None = None,
    params: CpbV2Params = PARAMS,
) -> CpbV2FeatureEnrichment:
    """Return CPB V2 features and a hash from visible inputs only."""

    clean_context = _clean_context(context or {})
    features = dict(base_features)
    base_signal_passed = bool(base_features.get("signal_passed", False))
    decision_input = CpbV2DecisionInput(
        industry=clean_context.get("industry"),
        trigger_age_trading_days=trigger_age_trading_days,
        gap_from_trigger_close=clean_context.get("gap_from_trigger_close"),
        trigger_close=base_features.get("trigger_close"),
        planned_buy_open=clean_context.get("planned_buy_open"),
        big_winner_potential_score=clean_context.get("big_winner_potential_score"),
        cpb_buy_point_score=base_features.get("score"),
        bull_body=base_features.get("bull_body"),
        trigger_pct_chg=base_features.get("trigger_pct_chg"),
        trigger_amount_to_ma10=base_features.get("trigger_amount_to_ma10"),
        amount_contract_ratio=base_features.get("amount_contract_ratio"),
    )
    decision = position_plan(decision_input, params)

    features.update(
        {
            "feature_name": "contracting_pullback_cpb_v2",
            "base_feature_name": base_features.get("feature_name"),
            "base_signal_passed": base_signal_passed,
            "planned_buy_date": planned_buy_date,
            "trigger_age_trading_days": trigger_age_trading_days,
            "industry": clean_context.get("industry"),
            "big_winner_potential_score": clean_context.get("big_winner_potential_score"),
            "planned_buy_open": clean_context.get("planned_buy_open"),
            "gap_from_trigger_close": _decision_gap(decision_input),
            "cpb_v2_non_security_result": _non_security_result(decision_input, params),
            "cpb_v2_no_chase_result": _no_chase_result(decision_input, params),
            "cpb_v2_missing_entry_inputs": _missing_entry_inputs(decision_input),
            "cpb_v2_missing_observation_inputs": _missing_observation_inputs(decision_input),
            "cpb_v2_decision": decision.to_dict(),
            "cpb_v2_observation_sleeve": decision.observation_sleeve,
            "cpb_v2_short_sleeve_weight": decision.short_sleeve_weight,
            "cpb_v2_observation_sleeve_weight": decision.observation_sleeve_weight,
        }
    )
    if clean_context.get("source_feature_version") is not None:
        features["cpb_v2_context_source_feature_version"] = clean_context["source_feature_version"]
    if clean_context.get("source_review_date") is not None:
        features["cpb_v2_context_source_review_date"] = clean_context["source_review_date"]

    if base_signal_passed:
        features["signal_passed"] = decision.eligible
        features["invalid_reason"] = None if decision.eligible else f"cpb_v2_{decision.skip_reason}"
    else:
        features["signal_passed"] = False

    input_hash = _hash_visible_inputs(
        base_input_hash=base_input_hash,
        trigger_age_trading_days=trigger_age_trading_days,
        planned_buy_date=planned_buy_date,
        context=clean_context,
        params=params,
    )
    return CpbV2FeatureEnrichment(features=features, input_hash=input_hash)


def _clean_context(context: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "industry": _clean_text(_pick(context, "industry")),
        "big_winner_potential_score": _to_float(
            _pick(context, "big_winner_potential_score", "bigwin_score")
        ),
        "planned_buy_open": _to_float(_pick(context, "planned_buy_open", "buy_open", "next_open")),
        "gap_from_trigger_close": _to_float(_pick(context, "gap_from_trigger_close")),
        "source_feature_version": _clean_text(_pick(context, "source_feature_version")),
        "source_review_date": _clean_text(_pick(context, "source_review_date")),
    }


def _pick(context: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if _is_future_label_key(key):
            continue
        if key in context:
            return context[key]
    return None


def _decision_gap(item: CpbV2DecisionInput) -> float | None:
    explicit_gap = _to_float(item.gap_from_trigger_close)
    if explicit_gap is not None:
        return explicit_gap
    trigger_close = _to_float(item.trigger_close)
    planned_buy_open = _to_float(item.planned_buy_open)
    if trigger_close is None or planned_buy_open is None or trigger_close == 0:
        return None
    return round(planned_buy_open / trigger_close - 1, 6)


def _non_security_result(item: CpbV2DecisionInput, params: CpbV2Params) -> str:
    industry = _clean_text(item.industry)
    if industry is None:
        return "missing_industry"
    if industry in params.excluded_industries:
        return "excluded_security_industry"
    return "passed"


def _no_chase_result(item: CpbV2DecisionInput, params: CpbV2Params) -> str:
    gap = _decision_gap(item)
    if gap is None:
        return "missing_gap_from_trigger_close"
    if gap > params.max_gap_from_trigger_close:
        return "gap_above_max"
    if gap < params.min_gap_from_trigger_close:
        return "gap_below_min"
    return "passed"


def _missing_entry_inputs(item: CpbV2DecisionInput) -> list[str]:
    missing: list[str] = []
    if _clean_text(item.industry) is None:
        missing.append("industry")
    if _to_float(item.trigger_age_trading_days) is None:
        missing.append("trigger_age_trading_days")
    if _decision_gap(item) is None:
        missing.append("gap_from_trigger_close")
    return missing


def _missing_observation_inputs(item: CpbV2DecisionInput) -> list[str]:
    checks = {
        "big_winner_potential_score": item.big_winner_potential_score,
        "cpb_buy_point_score": item.cpb_buy_point_score,
        "bull_body": item.bull_body,
        "trigger_pct_chg": item.trigger_pct_chg,
        "trigger_amount_to_ma10": item.trigger_amount_to_ma10,
        "amount_contract_ratio": item.amount_contract_ratio,
    }
    return [key for key, value in checks.items() if _to_float(value) is None]


def _hash_visible_inputs(
    *,
    base_input_hash: str,
    trigger_age_trading_days: int | None,
    planned_buy_date: str | None,
    context: Mapping[str, Any],
    params: CpbV2Params,
) -> str:
    payload = {
        "base_input_hash": base_input_hash,
        "trigger_age_trading_days": trigger_age_trading_days,
        "planned_buy_date": planned_buy_date,
        "context": {
            key: value
            for key, value in sorted(context.items())
            if value is not None and not _is_future_label_key(key)
        },
        "params": params.to_dict(),
    }
    return hashlib.sha256(_json_dumps(payload).encode("utf-8")).hexdigest()


def _is_future_label_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in _FUTURE_LABEL_TOKENS)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _json_dumps(value: Any) -> str:
    return json.dumps(_to_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value
