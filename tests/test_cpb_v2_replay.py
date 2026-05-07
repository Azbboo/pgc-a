from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from pgc_trading.strategies.cpb_v2 import position_plan


FIXTURE = Path(__file__).parent / "fixtures" / "replay" / "cpb_v2_golden_cases.json"
FORBIDDEN_TOKENS = ("future", "label", "mfe", "mae", "return_20d", "winner_ret")


class CpbV2ReplayTest(unittest.TestCase):
    def test_golden_replay_decisions_are_deterministic(self) -> None:
        cases = json.loads(FIXTURE.read_text(encoding="utf-8"))

        for case in cases:
            with self.subTest(case=case["case_id"]):
                self._assert_no_future_labels(case)
                first = position_plan(case["visible_features"]).to_dict()
                second = position_plan(case["visible_features"]).to_dict()

                self.assertEqual(first, second)
                expected = case["expected"]
                for key, value in expected.items():
                    self.assertEqual(first[key], value)

    def test_fixture_covers_required_research_examples(self) -> None:
        case_ids = {
            case["case_id"]
            for case in json.loads(FIXTURE.read_text(encoding="utf-8"))
        }

        self.assertEqual(
            case_ids,
            {
                "security_industry_filtered",
                "high_chase_open_filtered",
                "valid_normal_cpb_short_only",
                "valid_elastic_high_score_observation_sleeve",
            },
        )

    def _assert_no_future_labels(self, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                lowered = str(key).lower()
                self.assertFalse(
                    any(token in lowered for token in FORBIDDEN_TOKENS),
                    f"future label-like key found: {key}",
                )
                self._assert_no_future_labels(item)
        elif isinstance(value, list):
            for item in value:
                self._assert_no_future_labels(item)


if __name__ == "__main__":
    unittest.main()
