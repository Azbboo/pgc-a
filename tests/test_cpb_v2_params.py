from __future__ import annotations

import hashlib
import json
import unittest

from pgc_trading.strategies.cpb_v2 import (
    PARAMS,
    PARAMS_HASH,
    STRATEGY_FAMILY_KEY,
    STRATEGY_KEY,
    STRATEGY_VERSION,
)


class CpbV2ParamsTest(unittest.TestCase):
    def test_strategy_identity_is_separate_from_cpb_6157(self) -> None:
        self.assertEqual(STRATEGY_KEY, "cpb_v2")
        self.assertEqual(STRATEGY_VERSION, "cpb_v2@2026-05-06")
        self.assertEqual(STRATEGY_FAMILY_KEY, "contracting_pullback")
        self.assertEqual(PARAMS.variant_id, "cpb_v2")

    def test_params_json_contains_v2_rules(self) -> None:
        params = json.loads(PARAMS.canonical_json())

        self.assertEqual(params["variant_id"], "cpb_v2")
        self.assertEqual(params["excluded_industries"], ["证券"])
        self.assertEqual(params["min_trigger_age_trading_days"], 6)
        self.assertEqual(params["max_gap_from_trigger_close"], 0.02)
        self.assertEqual(params["min_gap_from_trigger_close"], -0.03)
        self.assertIn("半导体", params["elastic_industries"])
        self.assertEqual(params["min_big_winner_potential_score"], 65.0)
        self.assertEqual(params["min_cpb_buy_point_score"], 120.0)
        self.assertEqual(params["short_sleeve_weight"], 0.7)
        self.assertEqual(params["observation_sleeve_weight"], 0.3)
        self.assertEqual(params["observation_take_profit"], 0.25)
        self.assertEqual(params["observation_hard_stop"], -0.15)
        self.assertEqual(params["observation_max_holding_trading_days"], 20)

    def test_params_hash_is_stable(self) -> None:
        expected = hashlib.sha256(PARAMS.canonical_json().encode("utf-8")).hexdigest()

        self.assertEqual(PARAMS_HASH, expected)
        self.assertEqual(PARAMS.params_hash(), expected)
        self.assertEqual(PARAMS.canonical_json(), PARAMS.canonical_json())


if __name__ == "__main__":
    unittest.main()
