from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data


ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    module_path = ROOT / "scripts" / "backtest_shadow_v2_weights.py"
    spec = importlib.util.spec_from_file_location("backtest_shadow_v2_weights", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ShadowV2WeightBacktestScriptTest(unittest.TestCase):
    def test_v2_penalizes_overheated_low_price_and_breakout_candidates(self) -> None:
        module = _load_module()
        hot_low = {
            "bucket": "low_price_momentum_shadow",
            "score": 118.0,
            "day_pct_chg": 10.05,
            "amount_to_ma10": 2.15,
            "close_pos20": 1.0,
            "dist5_high_pct": 0.0,
        }
        stable_low = {
            "bucket": "low_price_momentum_shadow",
            "score": 112.0,
            "day_pct_chg": -1.2,
            "amount_to_ma10": 1.1,
            "close_pos20": 0.86,
            "dist5_high_pct": -5.0,
        }
        hot_breakout = {
            "bucket": "breakout_pressure_shadow",
            "score": 107.0,
            "day_pct_chg": 10.0,
            "amount_to_ma10": 1.3,
            "close_pos20": 1.0,
            "ret5_pct": 30.0,
            "dist5_high_pct": 0.0,
        }
        stable_breakout = {
            "bucket": "breakout_pressure_shadow",
            "score": 106.0,
            "day_pct_chg": 1.5,
            "amount_to_ma10": 1.2,
            "close_pos20": 0.88,
            "ret5_pct": 12.0,
            "dist5_high_pct": -3.0,
        }

        self.assertGreater(module.current_score(hot_low), module.current_score(stable_low))
        self.assertLess(module.optimized_score(hot_low), module.optimized_score(stable_low))
        self.assertGreater(module.current_score(hot_breakout), module.current_score(stable_breakout))
        self.assertLess(module.optimized_score(hot_breakout), module.optimized_score(stable_breakout))

    def test_generates_research_only_artifacts_without_trade_state_writes(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "pgc.db"
            reports_dir = tmp_path / "reports"
            data_dir = tmp_path / "data"
            run_migrations(db_path)
            seed_reference_data(db_path)
            _seed_shadow_market(db_path)
            before_counts = _state_counts(db_path)

            result = module.generate_shadow_weight_optimization(
                db_path=db_path,
                review_date="20260514",
                reports_dir=reports_dir,
                data_dir=data_dir,
                walk_forward_days=3,
                apply=True,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "success")
            self.assertEqual(_state_counts(db_path), before_counts)
            self.assertEqual(result["optimization_contract"], "shadow_weight_optimization_v1")
            self.assertFalse(result["safety"]["writes_trade_state"])
            self.assertFalse(result["safety"]["writes_paper_live_behavior"])
            self.assertFalse(result["safety"]["wrote_strategy_versions"])
            self.assertTrue(Path(result["outputs"]["json"]).exists())
            self.assertTrue(Path(result["outputs"]["markdown"]).exists())
            self.assertTrue(Path(result["outputs"]["csv"]).exists())
            variants = {item["variant"] for item in result["summary"]}
            self.assertEqual(variants, {"current", module.OPTIMIZED_VARIANT})


def _seed_shadow_market(db_path: Path) -> None:
    dates = [f"202605{day:02d}" for day in range(1, 15)]
    with sqlite3.connect(db_path) as conn:
        for idx, trade_date in enumerate(dates):
            pretrade_date = dates[idx - 1] if idx else "20260430"
            conn.execute(
                """
                INSERT INTO trade_calendar (exchange, cal_date, is_open, pretrade_date)
                VALUES ('SSE', ?, 1, ?)
                """,
                (trade_date, pretrade_date),
            )
        for ts_code, code, name, entry_price in [
            ("000001.SZ", "000001", "Trend", 10.0),
            ("000002.SZ", "000002", "Breakout", 20.0),
            ("000003.SZ", "000003", "Low", 5.0),
        ]:
            conn.execute(
                """
                INSERT INTO raw_events (ts_code, code, name, entry_date, entry_time, entry_price)
                VALUES (?, ?, ?, '20260501', '15:00', ?)
                """,
                (ts_code, code, name, entry_price),
            )
        for idx, trade_date in enumerate(dates):
            _insert_bar(conn, "000001.SZ", trade_date, 12.0 + idx * 0.3)
            _insert_bar(conn, "000002.SZ", trade_date, 20.8 + idx * 0.08)
            _insert_bar(conn, "000003.SZ", trade_date, 5.4 + idx * 0.08)


def _insert_bar(conn: sqlite3.Connection, ts_code: str, trade_date: str, close: float) -> None:
    conn.execute(
        """
        INSERT INTO market_bars (ts_code, trade_date, open, high, low, close, vol, amount)
        VALUES (?, ?, ?, ?, ?, ?, 1000.0, 1000.0)
        """,
        (ts_code, trade_date, close * 0.995, close * 1.01, close * 0.99, close),
    )


def _state_counts(db_path: Path) -> dict[str, int]:
    with sqlite3.connect(db_path) as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("strategy_versions", "trade_plans", "trades", "positions")
        }
