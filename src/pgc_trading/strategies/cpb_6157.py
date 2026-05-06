"""Best contracting-pullback bullish-candle strategy parameters."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict


STRATEGY_KEY = "cpb_6157"
STRATEGY_VERSION = "cpb_6157@2026-05-03"


@dataclass(frozen=True)
class Cpb6157Params:
    variant_id: str = "cpb_6157"
    contract_max: float = 0.95
    avg_amount_max: float = 0.95
    min_drawdown: float = 0.025
    max_drawdown: float = 0.14
    bull_body_min: float = 0.012
    close_recover_min: float = 0.0
    pct_chg_min: float = 0.0
    trigger_amount_max: float = 1.3
    max_entry_runup: float = 0.18

    def to_dict(self) -> dict:
        return asdict(self)

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def params_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


PARAMS = Cpb6157Params()
PARAMS_HASH = PARAMS.params_hash()
