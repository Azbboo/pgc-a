from __future__ import annotations

import json
import unittest

from pgc_trading.features.cpb_v2_inputs import build_cpb_v2_feature_enrichment


class CpbV2FeatureInputsTest(unittest.TestCase):
    def test_missing_industry_blocks_with_clear_reason(self) -> None:
        enrichment = build_cpb_v2_feature_enrichment(
            self._base_features(),
            base_input_hash="base-hash",
            trigger_age_trading_days=6,
            planned_buy_date="20260505",
            context={"gap_from_trigger_close": 0.01, "bigwin_score": 80},
        )

        self.assertFalse(enrichment.features["signal_passed"])
        self.assertEqual(enrichment.features["invalid_reason"], "cpb_v2_missing_industry")
        self.assertEqual(enrichment.features["cpb_v2_non_security_result"], "missing_industry")
        self.assertIn("industry", enrichment.features["cpb_v2_missing_entry_inputs"])

    def test_missing_potential_score_keeps_valid_entry_short_only(self) -> None:
        enrichment = build_cpb_v2_feature_enrichment(
            self._base_features(),
            base_input_hash="base-hash",
            trigger_age_trading_days=6,
            planned_buy_date="20260505",
            context={"industry": "半导体", "gap_from_trigger_close": 0.01},
        )

        decision = enrichment.features["cpb_v2_decision"]
        self.assertTrue(enrichment.features["signal_passed"])
        self.assertTrue(decision["eligible"])
        self.assertFalse(decision["observation_sleeve"])
        self.assertEqual(decision["short_sleeve_weight"], 1.0)
        self.assertIn("missing_big_winner_potential_score", decision["decision_notes"])

    def test_elastic_high_score_context_gets_observation_sleeve(self) -> None:
        enrichment = build_cpb_v2_feature_enrichment(
            self._base_features(),
            base_input_hash="base-hash",
            trigger_age_trading_days=6,
            planned_buy_date="20260505",
            context={"industry": "软件服务", "buy_open": 10.1, "bigwin_score": 80},
        )

        self.assertTrue(enrichment.features["signal_passed"])
        self.assertEqual(enrichment.features["gap_from_trigger_close"], 0.01)
        self.assertTrue(enrichment.features["cpb_v2_observation_sleeve"])
        self.assertEqual(enrichment.features["cpb_v2_short_sleeve_weight"], 0.7)
        self.assertEqual(enrichment.features["cpb_v2_observation_sleeve_weight"], 0.3)

    def test_context_future_labels_are_not_copied_to_features_or_hash_payload(self) -> None:
        first = build_cpb_v2_feature_enrichment(
            self._base_features(),
            base_input_hash="base-hash",
            trigger_age_trading_days=6,
            planned_buy_date="20260505",
            context={
                "industry": "软件服务",
                "gap_from_trigger_close": 0.01,
                "bigwin_score": 80,
                "future_return_20d": 9.99,
                "next_open_mfe_20d": 8.88,
                "outcome_label": "winner",
            },
        )
        second = build_cpb_v2_feature_enrichment(
            self._base_features(),
            base_input_hash="base-hash",
            trigger_age_trading_days=6,
            planned_buy_date="20260505",
            context={
                "industry": "软件服务",
                "gap_from_trigger_close": 0.01,
                "bigwin_score": 80,
                "future_return_20d": -9.99,
                "next_open_mfe_20d": -8.88,
                "outcome_label": "loser",
            },
        )

        encoded = json.dumps(first.features, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("future_return_20d", encoded)
        self.assertNotIn("next_open_mfe_20d", encoded)
        self.assertNotIn("outcome_label", encoded)
        self.assertEqual(first.input_hash, second.input_hash)

    def _base_features(self) -> dict[str, object]:
        return {
            "feature_name": "contracting_pullback_bullish",
            "review_date": "20260504",
            "raw_event_id": 1,
            "ts_code": "000001.SZ",
            "entry_date": "20260427",
            "entry_price": 10.0,
            "bars_used": 7,
            "latest_bar_date": "20260504",
            "signal_passed": True,
            "invalid_reason": None,
            "score": 130.0,
            "bull_body": 0.03,
            "trigger_pct_chg": 0.02,
            "trigger_amount_to_ma10": 0.9,
            "amount_contract_ratio": 0.7,
            "trigger_close": 10.0,
        }


if __name__ == "__main__":
    unittest.main()
