from __future__ import annotations

import unittest

from pgc_trading.strategies.cpb_v2 import (
    CpbV2DecisionInput,
    is_swing_eligible,
    is_v2_trade,
    position_plan,
)


class CpbV2DecisionTest(unittest.TestCase):
    def test_securities_are_excluded(self) -> None:
        features = self._valid_features(industry="证券")

        decision = position_plan(features)

        self.assertFalse(decision.eligible)
        self.assertEqual(decision.skip_reason, "excluded_industry")
        self.assertFalse(is_v2_trade(features))

    def test_age_below_minimum_is_excluded(self) -> None:
        decision = position_plan(self._valid_features(trigger_age_trading_days=5))

        self.assertFalse(decision.eligible)
        self.assertEqual(decision.skip_reason, "trigger_age_below_min")

    def test_gap_above_max_is_excluded(self) -> None:
        decision = position_plan(self._valid_features(gap_from_trigger_close=0.0201))

        self.assertFalse(decision.eligible)
        self.assertEqual(decision.skip_reason, "gap_above_max")

    def test_gap_below_min_is_excluded(self) -> None:
        decision = position_plan(self._valid_features(gap_from_trigger_close=-0.0301))

        self.assertFalse(decision.eligible)
        self.assertEqual(decision.skip_reason, "gap_below_min")

    def test_elastic_high_score_setup_gets_observation_sleeve(self) -> None:
        features = self._valid_features()

        decision = position_plan(features)

        self.assertTrue(decision.eligible)
        self.assertIsNone(decision.skip_reason)
        self.assertTrue(decision.observation_sleeve)
        self.assertEqual(decision.short_sleeve_weight, 0.7)
        self.assertEqual(decision.observation_sleeve_weight, 0.3)
        self.assertTrue(is_swing_eligible(features))
        self.assertIn("split_70_30", decision.decision_notes)

    def test_non_elastic_valid_setup_gets_short_sleeve_only(self) -> None:
        decision = position_plan(self._valid_features(industry="食品饮料"))

        self.assertTrue(decision.eligible)
        self.assertIsNone(decision.skip_reason)
        self.assertFalse(decision.observation_sleeve)
        self.assertEqual(decision.short_sleeve_weight, 1.0)
        self.assertEqual(decision.observation_sleeve_weight, 0.0)
        self.assertIn("non_elastic_industry", decision.decision_notes)

    def test_missing_potential_score_does_not_crash_entry_decision(self) -> None:
        decision = position_plan(self._valid_features(big_winner_potential_score=None))

        self.assertTrue(decision.eligible)
        self.assertFalse(decision.observation_sleeve)
        self.assertEqual(decision.short_sleeve_weight, 1.0)
        self.assertIn("missing_big_winner_potential_score", decision.decision_notes)

    def test_gap_can_be_derived_from_trigger_close_and_planned_open(self) -> None:
        features = self._valid_features(gap_from_trigger_close=None, trigger_close=10.0, planned_buy_open=10.2)

        decision = position_plan(features)

        self.assertTrue(decision.eligible)
        self.assertTrue(decision.observation_sleeve)

    def test_dict_input_supports_research_aliases(self) -> None:
        features = {
            "industry": "软件服务",
            "trigger_age_trading_days": 7,
            "trigger_close": 20.0,
            "buy_open": 20.1,
            "bigwin_score": 80.0,
            "score": 130.0,
            "bull_body": 0.03,
            "trigger_pct_chg": 0.02,
            "trigger_amount_to_ma10": 0.9,
            "amount_contract_ratio": 0.7,
        }

        decision = position_plan(features)

        self.assertTrue(decision.eligible)
        self.assertTrue(decision.observation_sleeve)

    def _valid_features(self, **overrides: object) -> CpbV2DecisionInput:
        values: dict[str, object] = {
            "industry": "半导体",
            "trigger_age_trading_days": 6,
            "gap_from_trigger_close": 0.01,
            "trigger_close": 10.0,
            "planned_buy_open": 10.1,
            "big_winner_potential_score": 65.0,
            "cpb_buy_point_score": 120.0,
            "bull_body": 0.02,
            "trigger_pct_chg": 0.017,
            "trigger_amount_to_ma10": 0.75,
            "amount_contract_ratio": 0.85,
        }
        values.update(overrides)
        return CpbV2DecisionInput(**values)


if __name__ == "__main__":
    unittest.main()
