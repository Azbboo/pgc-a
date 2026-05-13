from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.shadow_observation_service import (
    BuildShadowPromotionDossierRequest,
    GetShadowObservationScorecardRequest,
    ShadowObservationService,
)
from pgc_trading.storage.migrate import run_migrations


class ShadowObservationServiceTest(unittest.TestCase):
    def test_builds_read_only_scorecard_from_shadow_snapshot_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_market_bar(db_path, "300001.SZ", "20260512")
            _seed_shadow_observation_artifacts(reports_dir)
            before_counts = _state_counts(db_path)

            result = ShadowObservationService(db_path, reports_dir=reports_dir).get_scorecard(
                GetShadowObservationScorecardRequest(as_of_date="20260512"),
                RequestContext(request_id="req-shadow-observation", dry_run=True, source="test"),
            )

            self.assertTrue(result.ok, result.errors)
            self.assertEqual(_state_counts(db_path), before_counts)
            assert result.data is not None
            self.assertEqual(result.data.scorecard_contract, "shadow_observation_scorecard_v1")
            self.assertEqual(result.data.as_of_date, "20260512")
            self.assertEqual(result.data.status, "blocked")
            self.assertTrue(result.data.read_only)
            self.assertTrue(result.data.artifact_only)
            self.assertEqual(result.data.counts["candidate_count"], 2)
            self.assertEqual(result.data.counts["insufficient_sample_count"], 1)
            self.assertEqual(result.data.summary["top_candidate_key"], "trend_extension_shadow")
            top = result.data.rows[0]
            self.assertEqual(top["candidate_key"], "trend_extension_shadow")
            self.assertEqual(top["rank"], 1)
            self.assertEqual(top["sample_size"], 20)
            self.assertEqual(top["sample_coverage_status"], "complete")
            self.assertIn("operator_review_required", top["promotion_blocked_reason"])
            self.assertIn("not paper trading", top["read_only_note"])
            self.assertTrue(result.data.safety["observation_is_not_paper_trading"])
            self.assertFalse(result.data.safety["writes_trade_state"])
            self.assertFalse(result.data.safety["timer_mutated"])
            self.assertFalse(result.data.safety["promotion_allowed"])
            source_artifacts_json = json.dumps(result.data.source_artifacts, ensure_ascii=False)
            self.assertNotIn(str(root), source_artifacts_json)
            self.assertIn("reports/strategy_shadow_monitor_20260512.json", source_artifacts_json)

    def test_missing_market_bar_is_explicit_data_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_shadow_observation_artifacts(reports_dir)

            result = ShadowObservationService(db_path, reports_dir=reports_dir).get_scorecard(
                GetShadowObservationScorecardRequest(as_of_date="20260512"),
                RequestContext(request_id="req-shadow-observation-gap", dry_run=True, source="test"),
            )

            self.assertTrue(result.ok, result.errors)
            assert result.data is not None
            top = next(row for row in result.data.rows if row["candidate_key"] == "trend_extension_shadow")
            self.assertEqual(top["sample_coverage_status"], "missing")
            self.assertEqual(result.data.counts["market_data_gap_count"], 1)
            self.assertIn("market_bars_missing:300001.SZ:20260512", top["market_data_gaps"])

    def test_promotion_dossier_uses_portable_artifact_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_shadow_observation_artifacts(reports_dir)

            result = ShadowObservationService(db_path, reports_dir=reports_dir).build_promotion_dossier(
                BuildShadowPromotionDossierRequest(as_of_date="20260512"),
                RequestContext(request_id="req-shadow-dossier", dry_run=True, source="test"),
            )

            self.assertTrue(result.ok, result.errors)
            assert result.data is not None
            artifact_json = json.dumps(result.data.artifact, ensure_ascii=False)
            self.assertNotIn(str(root), artifact_json)
            self.assertIn("reports/strategy_shadow_monitor_20260512.json", artifact_json)


def _seed_shadow_observation_artifacts(reports_dir: Path) -> None:
    monitor = {
        "review_date": "20260512",
        "next_trade_date": "20260513",
        "today_candidate_count": 2,
        "walk_forward_progress": {
            "status": "partial",
            "required_days": 20,
            "evaluable_signal_days": 20,
            "latest_outcome_date": "20260512",
        },
        "candidate_monitors": [
            {
                "candidate_key": "trend_extension_shadow",
                "candidate_family": "shadow_bucket",
                "today_candidate_count": 1,
                "today_top": {"ts_code": "300001.SZ", "name": "Observation A", "review_date": "20260512"},
                "walk_forward_progress": {
                    "status": "complete",
                    "required_days": 20,
                    "days": 20,
                    "start_signal_date": "20260409",
                    "latest_signal_date": "20260511",
                    "t1_close_mean_pct": 2.4,
                    "t1_close_win_rate_pct": 65.0,
                    "t1_high_mean_pct": 5.5,
                    "t1_high_ge3_rate_pct": 70.0,
                },
                "comparison_vs_frozen_cpb": {
                    "status": "compared",
                    "baseline_label": "active_cpb_persisted_picks",
                    "baseline_days": 20,
                    "candidate_days": 20,
                    "t1_close_mean_delta_pct": 1.2,
                    "t1_close_win_rate_delta_pct": 10.0,
                    "t5_close_mean_delta_pct": 2.0,
                },
                "promotion_gates": {
                    "paper_observation_gate": {
                        "status": "blocked",
                        "allowed": False,
                        "artifact_only": True,
                        "blockers": ["operator_review_required"],
                    },
                    "strategy_version_gate": {
                        "status": "blocked",
                        "allowed": False,
                        "artifact_only": True,
                        "blockers": ["replay_backtest_result_artifact_required"],
                    },
                },
            },
            {
                "candidate_key": "breakout_pressure_shadow",
                "candidate_family": "shadow_bucket",
                "walk_forward_progress": {
                    "status": "partial",
                    "required_days": 20,
                    "days": 6,
                    "t1_close_mean_pct": 1.0,
                    "t1_close_win_rate_pct": 55.0,
                },
                "comparison_vs_frozen_cpb": {
                    "status": "compared",
                    "baseline_label": "active_cpb_persisted_picks",
                    "candidate_days": 6,
                    "t1_close_mean_delta_pct": -1.0,
                    "sample_warning": "baseline_sample_lt_20",
                },
                "promotion_gates": {
                    "paper_observation_gate": {
                        "status": "blocked",
                        "allowed": False,
                        "artifact_only": True,
                        "blockers": ["walk_forward_shadow_monitor_20_trading_days_required"],
                    },
                    "strategy_version_gate": {
                        "status": "blocked",
                        "allowed": False,
                        "artifact_only": True,
                        "blockers": ["proposal_review_required"],
                    },
                },
            },
        ],
    }
    preflight = {
        "review_date": "20260512",
        "next_trade_date": "20260513",
        "status": "blocked",
        "candidate_count": 2,
        "candidate_gates": [
            {
                "candidate_key": "trend_extension_shadow",
                "candidate_family": "shadow_bucket",
                "status": "blocked",
                "paper_observation_gate": {
                    "status": "blocked",
                    "allowed": False,
                    "artifact_only": True,
                    "blockers": ["operator_review_required"],
                },
                "strategy_version_gate": {
                    "status": "blocked",
                    "allowed": False,
                    "artifact_only": True,
                    "blockers": ["replay_backtest_result_artifact_required"],
                },
            },
            {
                "candidate_key": "breakout_pressure_shadow",
                "candidate_family": "shadow_bucket",
                "status": "blocked",
                "paper_observation_gate": {
                    "status": "blocked",
                    "allowed": False,
                    "artifact_only": True,
                    "blockers": ["walk_forward_shadow_monitor_20_trading_days_required"],
                },
                "strategy_version_gate": {
                    "status": "blocked",
                    "allowed": False,
                    "artifact_only": True,
                    "blockers": ["proposal_review_required"],
                },
            },
        ],
        "blocker_counts": {
            "operator_review_required": 1,
            "proposal_review_required": 1,
            "replay_backtest_result_artifact_required": 1,
            "walk_forward_shadow_monitor_20_trading_days_required": 1,
        },
        "safety": {
            "artifact_only": True,
            "active_params_mutated": False,
            "writes_trade_state": False,
            "writes_paper_live_behavior": False,
            "timer_mutated": False,
            "promotion_allowed": False,
        },
    }
    (reports_dir / "strategy_shadow_monitor_20260512.json").write_text(json.dumps(monitor), encoding="utf-8")
    (reports_dir / "strategy_shadow_promotion_preflight_20260512.json").write_text(
        json.dumps(preflight),
        encoding="utf-8",
    )


def _seed_market_bar(db_path: Path, ts_code: str, trade_date: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO market_bars
              (ts_code, trade_date, open, high, low, close, vol, amount)
            VALUES (?, ?, 10.0, 10.8, 9.8, 10.5, 100000.0, 1000.0)
            """,
            (ts_code, trade_date),
        )


def _state_counts(db_path: Path) -> dict[str, int]:
    with sqlite3.connect(db_path) as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("strategy_versions", "trade_plans", "trades", "positions")
        }


if __name__ == "__main__":
    unittest.main()
