from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.shadow_observation_service import review_shadow_replay_backtest_evidence_artifact
from pgc_trading.storage.migrate import run_migrations


ROOT = Path(__file__).resolve().parents[1]


def _load_script_module():
    module_path = ROOT / "scripts" / "generate_shadow_replay_backtest_evidence.py"
    spec = importlib.util.spec_from_file_location("generate_shadow_replay_backtest_evidence", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ShadowReplayBacktestEvidenceScriptTest(unittest.TestCase):
    def test_script_writes_validated_evidence_without_trade_state_writes(self) -> None:
        script = _load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_market(db_path)
            _seed_monitor(reports_dir)
            before_counts = _state_counts(db_path)

            payload = script.generate_shadow_replay_backtest_evidence(
                db_path=db_path,
                reports_dir=reports_dir,
                as_of_date="20260512",
                required_sample_size=3,
                apply=True,
                operator="unit-test",
            )

            self.assertTrue(payload["ok"], payload.get("errors"))
            self.assertEqual(_state_counts(db_path), before_counts)
            self.assertEqual(payload["evidence_contract"], "shadow_replay_backtest_evidence_v1")
            self.assertEqual(payload["summary"]["accepted_count"], 1)
            self.assertEqual(payload["summary"]["rejected_count"], 0)
            self.assertFalse(payload["safety"]["writes_trade_state"])
            artifact_path = reports_dir / "shadow_replay_backtest_evidence_20260512_trend_extension_shadow.json"
            self.assertTrue(artifact_path.exists())
            review = review_shadow_replay_backtest_evidence_artifact(
                artifact_path,
                expected_candidate_key="trend_extension_shadow",
                expected_as_of_date="20260512",
                required_sample_size=3,
            )
            self.assertTrue(review.valid, review.blockers)


def _seed_monitor(reports_dir: Path) -> None:
    rows = [
        {
            "ts_code": f"300{day:03d}.SZ",
            "review_date": f"202605{day:02d}",
            "signal_date": f"202605{day:02d}",
            "planned_buy_date": f"202605{day:02d}",
            "bucket": "trend_extension_shadow",
        }
        for day in range(1, 4)
    ]
    monitor = {
        "review_date": "20260512",
        "next_trade_date": "20260513",
        "walk_forward_progress": {"status": "complete", "required_days": 3, "rows": rows},
        "candidate_monitors": [
            {
                "candidate_key": "trend_extension_shadow",
                "candidate_family": "shadow_bucket",
                "walk_forward_progress": {
                    "status": "complete",
                    "required_days": 3,
                    "days": 3,
                    "start_signal_date": "20260501",
                    "latest_signal_date": "20260503",
                    "latest_outcome_date": "20260512",
                },
                "comparison_vs_frozen_cpb": {"status": "compared", "candidate_days": 3},
                "promotion_gates": {
                    "paper_observation_gate": {"allowed": False, "artifact_only": True, "blockers": []},
                    "strategy_version_gate": {
                        "allowed": False,
                        "artifact_only": True,
                        "blockers": ["replay_backtest_result_artifact_required"],
                    },
                },
            }
        ],
        "safety": {
            "artifact_only": True,
            "active_params_mutated": False,
            "writes_trade_state": False,
            "writes_paper_live_behavior": False,
            "timer_mutated": False,
            "promotion_allowed": False,
            "paper_observation_allowed": False,
        },
    }
    preflight = {
        "review_date": "20260512",
        "next_trade_date": "20260513",
        "status": "blocked",
        "candidate_count": 1,
        "candidate_gates": [
            {
                "candidate_key": "trend_extension_shadow",
                "candidate_family": "shadow_bucket",
                "status": "blocked",
                "walk_forward_progress": monitor["candidate_monitors"][0]["walk_forward_progress"],
                "paper_observation_gate": {"allowed": False, "artifact_only": True, "blockers": []},
                "strategy_version_gate": {
                    "allowed": False,
                    "artifact_only": True,
                    "blockers": ["replay_backtest_result_artifact_required"],
                },
            }
        ],
        "safety": monitor["safety"],
    }
    (reports_dir / "strategy_shadow_monitor_20260512.json").write_text(json.dumps(monitor), encoding="utf-8")
    (reports_dir / "strategy_shadow_promotion_preflight_20260512.json").write_text(
        json.dumps(preflight),
        encoding="utf-8",
    )


def _seed_market(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        for day in range(1, 4):
            ts_code = f"300{day:03d}.SZ"
            for offset in range(5):
                open_price = 10.0 + day
                trade_day = day + offset
                conn.execute(
                    """
                    INSERT INTO market_bars
                      (ts_code, trade_date, open, high, low, close, vol, amount)
                    VALUES (?, ?, ?, ?, ?, ?, 100000.0, 1000.0)
                    """,
                    (
                        ts_code,
                        f"202605{trade_day:02d}",
                        open_price,
                        open_price * 1.04,
                        open_price * 0.97,
                        open_price * 1.02,
                    ),
                )


def _state_counts(db_path: Path) -> dict[str, int]:
    with sqlite3.connect(db_path) as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("strategy_versions", "trade_plans", "trades", "positions")
        }


if __name__ == "__main__":
    unittest.main()
