from __future__ import annotations

import importlib.util
import unittest
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_daily_v2_review.py"
SPEC = importlib.util.spec_from_file_location("run_daily_v2_review", SCRIPT_PATH)
daily_v2 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(daily_v2)


PARAMS = {
    "variant_id": "test",
    "contract_max": 0.82,
    "avg_amount_max": 0.95,
    "min_drawdown": 0.025,
    "max_drawdown": 0.18,
    "bull_body_min": 0.012,
    "close_recover_min": 0.006,
    "pct_chg_min": 0.015,
    "trigger_amount_max": 1.30,
    "max_entry_runup": 0.25,
}


@dataclass
class _Market:
    frame: pd.DataFrame

    def __post_init__(self) -> None:
        self.by_date = {str(row.trade_date): idx for idx, row in self.frame.iterrows()}


class DailyV2ReviewScriptTest(unittest.TestCase):
    def test_pre_confirm_setup_is_not_a_confirmed_candidate(self) -> None:
        frame = daily_v2.prepare_frame(_market_frame())

        pre_confirmed, pre_features = daily_v2.detect_pre_confirm_setup(frame, 0, 5, PARAMS)
        confirmed, _ = daily_v2.detect_param_signal(frame, 0, 5, PARAMS)

        self.assertTrue(pre_confirmed)
        self.assertFalse(confirmed)
        self.assertAlmostEqual(pre_features["amount_contract_ratio"], 0.75)
        self.assertGreater(pre_features["confirm_close_min"], pre_features["watch_close"])
        self.assertIn("次日需", pre_features["confirm_note"])

    def test_confirmed_candidates_are_evaluated_at_requested_review_date(self) -> None:
        events = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "name": "Synthetic Pick",
                    "entry_date": "20260501",
                    "entry_price": 10.0,
                }
            ]
        )
        markets = {"000001.SZ": _Market(_market_frame())}

        pre_confirm_day = daily_v2.confirmed_candidates_at_date(events, markets, PARAMS, "20260506")
        confirm_day = daily_v2.confirmed_candidates_at_date(events, markets, PARAMS, "20260507")

        self.assertTrue(pre_confirm_day.empty)
        self.assertEqual(len(confirm_day), 1)
        row = confirm_day.iloc[0]
        self.assertEqual(row["review_date"], "20260507")
        self.assertEqual(row["trigger_age_trading_days"], 6)
        self.assertAlmostEqual(row["trigger_close"], 10.45)


def _market_frame() -> pd.DataFrame:
    rows = [
        ("20260501", 10.00, 10.20, 9.90, 10.00, 1000.0, 0.00),
        ("20260502", 10.80, 11.50, 10.70, 11.20, 1000.0, 12.00),
        ("20260503", 11.00, 11.10, 10.80, 10.90, 900.0, -2.68),
        ("20260504", 10.80, 10.90, 10.50, 10.60, 800.0, -2.75),
        ("20260505", 10.50, 10.60, 10.20, 10.30, 600.0, -2.83),
        ("20260506", 10.25, 10.35, 10.00, 10.10, 450.0, -1.94),
        ("20260507", 10.10, 10.50, 10.05, 10.45, 500.0, 3.47),
    ]
    frame = pd.DataFrame(rows, columns=["trade_date", "open", "high", "low", "close", "amount", "pct_chg"])
    for column in ["open", "high", "low", "close"]:
        frame[f"adj_{column}"] = frame[column]
    return frame


if __name__ == "__main__":
    unittest.main()
