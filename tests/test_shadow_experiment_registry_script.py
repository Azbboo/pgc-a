from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from pgc_trading.storage.migrate import run_migrations


ROOT = Path(__file__).resolve().parents[1]


def _load_registry_module():
    module_path = ROOT / "scripts" / "build_shadow_experiment_registry.py"
    spec = importlib.util.spec_from_file_location("build_shadow_experiment_registry", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ShadowExperimentRegistryScriptTest(unittest.TestCase):
    def test_script_generates_artifact_only_registry_without_trade_state_writes(self) -> None:
        registry = _load_registry_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "pgc.db"
            reports_dir = tmp_path / "reports"
            output_path = reports_dir / "shadow_strategy_experiment_registry_20260513.json"
            run_migrations(db_path)
            _write_calibration_artifact(reports_dir)
            _write_observed_outcome_artifacts(reports_dir)
            before_counts = _state_counts(db_path)

            result = registry.generate_shadow_experiment_registry(
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
            self.assertEqual(artifact["registry_contract"], "shadow_strategy_experiment_registry_v1")
            self.assertEqual(artifact["source_calibration"]["calibration_contract"], "shadow_threshold_calibration_v1")
            self.assertFalse(artifact["release_gate"]["promotion_allowed"])
            self.assertFalse(artifact["manual_approval_boundaries"]["strategy_version_publication_allowed"])
            self.assertGreaterEqual(artifact["summary"]["experiment_count"], 1)
            self.assertEqual(artifact["observed_outcomes"]["scorecard"]["status"], "available")
            self.assertEqual(artifact["observed_outcomes"]["walk_forward_outcomes"]["status"], "available")
            self.assertEqual(artifact["experiments"][0]["latest_observed_outcomes"]["walk_forward_status"], "complete")
            self.assertIn("operator_review_required", artifact["experiments"][0]["current_blockers"])


def _state_counts(db_path: Path) -> dict[str, int]:
    with sqlite3.connect(db_path) as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("strategy_versions", "trade_plans", "trades", "positions")
        }


def _write_calibration_artifact(reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    artifact = {
        "artifact_type": "shadow_threshold_calibration",
        "calibration_contract": "shadow_threshold_calibration_v1",
        "artifact_version": 1,
        "as_of_date": "20260513",
        "generated_at": "2026-05-13T08:00:00Z",
        "source_artifacts": {
            "shadow_observation_scorecard": "reports/shadow_observation_scorecard_20260513.json",
            "frozen_cpb_baseline": "reports/strategy_shadow_backtest_20260401_20260508.json",
        },
        "summary": {
            "status": "artifact_only",
            "candidate_count": 1,
            "family_count": 1,
            "variant_count": 2,
            "recommended_next_experiment_count": 1,
            "rejected_variant_count": 1,
            "artifact_only": True,
            "promotion_allowed": False,
            "active_params_mutated": False,
        },
        "threshold_variants": [
            {
                "variant_key": "current_shadow_review_gate",
                "min_sample_size": 20,
                "requires_accepted_replay_evidence": True,
            },
            {
                "variant_key": "quality_tighten_candidate",
                "min_sample_size": 30,
                "min_win_rate_pct": 55.0,
                "min_mean_return_pct": 1.0,
                "min_median_return_pct": 0.0,
                "min_frozen_cpb_delta_pct": 0.5,
                "min_drawdown_proxy_pct": -6.0,
                "requires_accepted_replay_evidence": True,
            },
        ],
        "family_metrics": [],
        "candidates": [
            {
                "candidate_key": "trend_extension_shadow",
                "candidate_family": "shadow_bucket",
                "metrics": {
                    "sample_size": 32,
                    "win_rate_pct": 62.5,
                    "mean_return_pct": 4.4,
                    "median_return_pct": 1.2,
                    "drawdown_proxy_pct": -5.0,
                    "metric_source_artifact": "reports/strategy_shadow_backtest_20260401_20260508.json",
                    "source_metric_keys": ["sample_size", "win_rate_pct", "mean_return_pct"],
                    "frozen_cpb_comparison": {
                        "status": "compared",
                        "baseline_label": "active_cpb_persisted_picks",
                        "mean_return_delta_pct": 2.4,
                        "source_artifact": "reports/strategy_shadow_backtest_20260401_20260508.json",
                    },
                    "evidence_coverage": {
                        "status": "accepted",
                        "valid": True,
                        "candidate_key": "trend_extension_shadow",
                        "evidence_contract": "shadow_replay_backtest_evidence_v1",
                        "artifact_path": "reports/shadow_replay_backtest_evidence_20260513_trend_extension_shadow.json",
                        "source_hash": "unit-test-source-hash",
                        "source_artifacts": [
                            "reports/shadow_replay_backtest_evidence_20260513_trend_extension_shadow.json"
                        ],
                        "blockers": [],
                        "advisory_only": True,
                        "promotion_allowed": False,
                    },
                },
                "threshold_variant_results": [
                    {
                        "variant_key": "current_shadow_review_gate",
                        "status": "passed",
                        "passed": True,
                        "blockers": [],
                        "thresholds": {"min_sample_size": 20, "requires_accepted_replay_evidence": True},
                        "artifact_only": True,
                        "promotion_allowed": False,
                    },
                    {
                        "variant_key": "quality_tighten_candidate",
                        "status": "passed",
                        "passed": True,
                        "blockers": [],
                        "thresholds": {
                            "min_sample_size": 30,
                            "min_win_rate_pct": 55.0,
                            "min_mean_return_pct": 1.0,
                            "min_median_return_pct": 0.0,
                            "min_frozen_cpb_delta_pct": 0.5,
                            "min_drawdown_proxy_pct": -6.0,
                            "requires_accepted_replay_evidence": True,
                        },
                        "artifact_only": True,
                        "promotion_allowed": False,
                    },
                ],
                "artifact_only": True,
                "promotion_allowed": False,
            }
        ],
        "recommended_next_experiments": [
            {
                "candidate_key": "trend_extension_shadow",
                "candidate_family": "shadow_bucket",
                "experiment_key": "trend_extension_shadow:quality_tighten_candidate",
                "recommended_variant": "quality_tighten_candidate",
                "reason": "candidate metrics pass this artifact-only threshold variant",
                "next_step": "rerun replay/backtest on the next closed evidence window",
                "artifact_only": True,
                "promotion_allowed": False,
            }
        ],
        "rejected_variants": [
            {
                "candidate_key": "trend_extension_shadow",
                "candidate_family": "shadow_bucket",
                "variant_key": "current_shadow_review_gate",
                "reasons": ["sample_size_below_threshold"],
                "artifact_only": True,
                "promotion_allowed": False,
            }
        ],
        "release_gate": {
            "status": "blocked",
            "artifact_only": True,
            "promotion_allowed": False,
            "paper_observation_allowed": False,
        },
        "safety": {
            "read_only": True,
            "artifact_only": True,
            "promotion_allowed": False,
            "paper_observation_allowed": False,
            "active_params_mutated": False,
            "wrote_strategy_version": False,
            "wrote_strategy_versions": False,
            "writes_trade_state": False,
            "writes_paper_live_behavior": False,
            "timer_mutated": False,
        },
    }
    (reports_dir / "shadow_threshold_calibration_20260513.json").write_text(
        json.dumps(artifact, sort_keys=True),
        encoding="utf-8",
    )


def _write_observed_outcome_artifacts(reports_dir: Path) -> None:
    scorecard = {
        "artifact_type": "shadow_observation_scorecard",
        "scorecard_contract": "shadow_observation_scorecard_v1",
        "review_date": "20260513",
        "as_of_date": "20260513",
        "summary": {"status": "blocked", "promotion_allowed": False},
        "candidates": [
            {
                "candidate_key": "trend_extension_shadow",
                "candidate_family": "shadow_bucket",
                "status": "blocked",
                "blockers": ["operator_review_required"],
                "walk_forward_status": "complete",
                "walk_forward_days": 32,
            }
        ],
        "safety": {
            "read_only": True,
            "artifact_only": True,
            "promotion_allowed": False,
            "writes_trade_state": False,
            "writes_paper_live_behavior": False,
            "timer_mutated": False,
        },
    }
    outcomes = {
        "artifact_type": "shadow_walk_forward_outcomes",
        "outcomes_contract": "shadow_walk_forward_outcomes_v1",
        "as_of_date": "20260513",
        "summary": {"status": "complete", "promotion_allowed": False},
        "candidates": [
            {
                "candidate_key": "trend_extension_shadow",
                "status": "complete",
                "signal_count": 32,
                "complete_count": 32,
            }
        ],
        "safety": {
            "read_only": True,
            "artifact_only": True,
            "promotion_allowed": False,
            "writes_trade_state": False,
            "writes_paper_live_behavior": False,
            "timer_mutated": False,
        },
    }
    (reports_dir / "shadow_observation_scorecard_20260513.json").write_text(
        json.dumps(scorecard, sort_keys=True),
        encoding="utf-8",
    )
    (reports_dir / "shadow_walk_forward_outcomes_20260513.json").write_text(
        json.dumps(outcomes, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
