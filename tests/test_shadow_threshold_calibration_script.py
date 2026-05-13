from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.shadow_observation_service import build_shadow_replay_backtest_source_hash
from pgc_trading.storage.migrate import run_migrations


ROOT = Path(__file__).resolve().parents[1]


def _load_calibration_module():
    module_path = ROOT / "scripts" / "calibrate_shadow_thresholds.py"
    spec = importlib.util.spec_from_file_location("calibrate_shadow_thresholds", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ShadowThresholdCalibrationScriptTest(unittest.TestCase):
    def test_script_generates_artifact_only_calibration_without_trade_state_writes(self) -> None:
        calibration = _load_calibration_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "pgc.db"
            reports_dir = tmp_path / "reports"
            output_path = reports_dir / "shadow_threshold_calibration_20260513.json"
            run_migrations(db_path)
            _write_calibration_inputs(reports_dir)
            before_counts = _state_counts(db_path)

            result = calibration.generate_shadow_threshold_calibration(
                db_path=db_path,
                reports_dir=reports_dir,
                as_of_date="20260513",
                output_path=output_path,
                dry_run=False,
                operator="azboo",
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "success")
            self.assertEqual(_state_counts(db_path), before_counts)
            data = result["data"]
            self.assertTrue(data["wrote_artifact"])
            self.assertTrue(Path(data["artifact_path"]).exists())
            self.assertTrue(Path(data["markdown_path"]).exists())
            self.assertTrue(data["review_valid"])
            self.assertFalse(data["safety"]["active_params_mutated"])
            self.assertFalse(data["safety"]["wrote_strategy_versions"])
            self.assertFalse(data["safety"]["writes_trade_state"])
            self.assertFalse(data["safety"]["writes_paper_live_behavior"])
            self.assertFalse(data["safety"]["timer_mutated"])
            artifact = json.loads(Path(data["artifact_path"]).read_text(encoding="utf-8"))
            self.assertEqual(artifact["calibration_contract"], "shadow_threshold_calibration_v1")
            self.assertFalse(artifact["release_gate"]["promotion_allowed"])
            self.assertGreaterEqual(artifact["summary"]["recommended_next_experiment_count"], 1)
            self.assertGreaterEqual(artifact["summary"]["rejected_variant_count"], 1)


def _state_counts(db_path: Path) -> dict[str, int]:
    with sqlite3.connect(db_path) as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("strategy_versions", "trade_plans", "trades", "positions")
        }


def _write_calibration_inputs(reports_dir: Path) -> None:
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
                        "t5_close_mean_pct": 2.0,
                    }
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    scorecard = {
        "artifact_type": "shadow_observation_scorecard",
        "scorecard_contract": "shadow_observation_scorecard_v1",
        "as_of_date": "20260513",
        "review_date": "20260513",
        "candidates": [
            {
                "candidate_key": "trend_extension_shadow",
                "candidate_family": "shadow_bucket",
                "walk_forward_progress": {
                    "required_days": 20,
                    "days": 24,
                    "t1_close_mean_pct": 2.2,
                    "t1_close_win_rate_pct": 62.0,
                    "t5_close_mean_pct": 4.4,
                    "t5_close_median_pct": 1.2,
                    "max_drawdown_pct": -5.0,
                },
                "comparison_vs_frozen_cpb": {"t5_close_mean_delta_pct": 2.4},
                "source_artifacts": ["reports/strategy_shadow_monitor_20260513.json"],
            }
        ],
        "safety": {
            "artifact_only": True,
            "active_params_mutated": False,
            "wrote_strategy_versions": False,
            "writes_trade_state": False,
            "writes_paper_live_behavior": False,
            "timer_mutated": False,
            "promotion_allowed": False,
        },
    }
    (reports_dir / "shadow_observation_scorecard_20260513.json").write_text(
        json.dumps(scorecard, sort_keys=True),
        encoding="utf-8",
    )
    metrics = {
        "t1_close_mean_pct": 2.2,
        "t1_close_win_rate_pct": 62.0,
        "t5_close_mean_pct": 4.4,
        "t5_close_median_pct": 1.2,
        "max_drawdown_pct": -5.0,
    }
    source_hash = build_shadow_replay_backtest_source_hash(
        provider="script_unit_test",
        candidate_key="trend_extension_shadow",
        start_date="20260409",
        end_date="20260513",
        sample_size=24,
        metrics=metrics,
    )
    evidence = {
        "artifact_type": "shadow_replay_backtest_evidence",
        "evidence_contract": "shadow_replay_backtest_evidence_v1",
        "provider": "script_unit_test",
        "as_of_date": "20260513",
        "results": [
            {
                "candidate_key": "trend_extension_shadow",
                "date_range": {"start_date": "20260409", "end_date": "20260513"},
                "sample_size": 24,
                "metrics": metrics,
                "source_hash": source_hash,
                "no_future_boundary": {
                    "passed": True,
                    "max_input_date": "20260513",
                    "data_cutoff_date": "20260513",
                },
            }
        ],
        "safety": {
            "active_params_mutated": False,
            "wrote_strategy_versions": False,
            "writes_trade_state": False,
            "writes_paper_live_behavior": False,
            "timer_mutated": False,
            "promotion_allowed": False,
            "paper_observation_allowed": False,
        },
    }
    (reports_dir / "shadow_replay_backtest_evidence_20260513_trend_extension_shadow.json").write_text(
        json.dumps(evidence, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
