from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data


ROOT = Path(__file__).resolve().parents[1]


def _load_monitor_module():
    module_path = ROOT / "scripts" / "monitor_shadow_strategies.py"
    spec = importlib.util.spec_from_file_location("monitor_shadow_strategies", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ShadowStrategyMonitorScriptTest(unittest.TestCase):
    def test_generates_m78_preflight_artifacts_without_db_trade_state_writes(self) -> None:
        monitor = _load_monitor_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "pgc.db"
            reports_dir = tmp_path / "reports"
            data_dir = tmp_path / "data"
            run_migrations(db_path)
            seed_reference_data(db_path)
            _seed_shadow_market(db_path)
            _write_research_artifacts(reports_dir)
            before_counts = _state_counts(db_path)

            summary = monitor.generate_shadow_monitor(
                db_path=db_path,
                review_date="20260514",
                reports_dir=reports_dir,
                data_dir=data_dir,
                walk_forward_days=3,
                frozen_cpb_artifact_path=reports_dir / "strategy_shadow_backtest_20260401_20260508.json",
                preconfirm_watchlist_artifact_path=reports_dir / "preconfirm_watchlist_backtest.json",
                dip_buy_artifact_path=reports_dir / "pgc_pullback_dip_buy.json",
            )

            self.assertEqual(_state_counts(db_path), before_counts)
            self.assertEqual(summary["read_only_guard"]["status"], "pass")
            self.assertTrue(summary["read_only_guard"]["trade_state_counts_unchanged"])
            self.assertEqual(summary["read_only_guard"]["changed_tables"], [])
            self.assertEqual(summary["walk_forward_progress"]["status"], "complete")
            self.assertEqual(summary["walk_forward_progress"]["required_days"], 3)
            self.assertEqual(
                [item["candidate_key"] for item in summary["candidate_monitors"]],
                [
                    "trend_extension_shadow",
                    "breakout_pressure_shadow",
                    "low_price_momentum_shadow",
                    "preconfirm_watchlist",
                    "pullback_dip_buy",
                ],
            )
            preflight = summary["promotion_preflight"]
            self.assertEqual(preflight["artifact_type"], "shadow_strategy_promotion_preflight")
            self.assertEqual(preflight["status"], "blocked")
            self.assertEqual(preflight["candidate_count"], 5)
            self.assertFalse(preflight["safety"]["active_params_mutated"])
            self.assertFalse(preflight["safety"]["writes_trade_state"])
            self.assertFalse(preflight["safety"]["writes_paper_live_behavior"])
            self.assertFalse(preflight["safety"]["timer_mutated"])
            self.assertEqual(preflight["release_gate"]["status"], "blocked")
            self.assertTrue(preflight["release_gate"]["artifact_only"])
            self.assertFalse(preflight["release_gate"]["promotion_allowed"])
            self.assertFalse(preflight["release_gate"]["timer_mutated"])
            self.assertTrue(preflight["release_gate"]["trade_state_counts_unchanged"])
            self.assertTrue(summary["api_summary"]["read_only"])
            self.assertEqual(summary["api_summary"]["promotion_preflight"]["release_gate"]["status"], "blocked")
            self.assertTrue(Path(summary["outputs"]["promotion_preflight_json"]).exists())
            self.assertTrue(Path(summary["outputs"]["walk_forward_csv"]).exists())


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


def _write_research_artifacts(reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "strategy_shadow_backtest_20260401_20260508.json").write_text(
        json.dumps(
            {
                "summary": [
                    {
                        "label": "active_cpb_persisted_picks",
                        "n": 20,
                        "days": 20,
                        "t1_close_mean_pct": 1.0,
                        "t1_close_win_rate_pct": 55.0,
                        "t1_high_mean_pct": 3.0,
                        "t1_high_ge3_rate_pct": 50.0,
                        "t5_close_mean_pct": 2.0,
                        "t5_close_win_rate_pct": 60.0,
                    }
                ],
                "active_cpb_picks": [{"review_date": "20260501"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (reports_dir / "preconfirm_watchlist_backtest.json").write_text(
        json.dumps(
            {
                "meta": {"start_date": "20260401", "end_date": "20260514"},
                "summary": [
                    {
                        "pre_action": "高潜伏预警",
                        "signals": 30,
                        "review_days": 21,
                        "stocks": 10,
                        "confirm_next_day_rate": 0.25,
                        "next_open_ret_1d_mean": 0.02,
                        "next_open_ret_1d_win_rate": 0.6,
                        "next_open_ret_5d_mean": 0.05,
                        "watch_mfe_5d_mean": 0.08,
                    },
                    {"pre_action": "全部", "signals": 60},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (reports_dir / "pgc_pullback_dip_buy.json").write_text(
        json.dumps(
            {
                "selected_variant": "dip_r15_a6_run05",
                "selected_params": {"variant_id": "dip_r15_a6_run05", "retrace_pct": 0.15},
                "variants": [
                    {
                        "variant_id": "dip_r15_a6_run05",
                        "fill_rate": 0.45,
                        "ret_5d_n": 25,
                        "ret_5d_mean": 0.03,
                        "ret_5d_win_rate": 0.56,
                        "mfe_10d_median": 0.09,
                        "mae_10d_median": -0.07,
                    }
                ],
                "selected_groups": {"score": [{"group": "潜力分>=75", "ret_5d_mean": 0.04}]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _state_counts(db_path: Path) -> dict[str, int]:
    with sqlite3.connect(db_path) as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("strategy_versions", "trade_plans", "trades", "positions")
        }
