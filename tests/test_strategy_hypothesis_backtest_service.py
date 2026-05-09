from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

from pgc_trading.services.common import RequestContext
from pgc_trading.services.strategy_hypothesis_backtest_service import (
    CreateStrategyHypothesisBacktestRequest,
    StrategyHypothesisBacktestService,
)
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data


ROOT = Path(__file__).resolve().parents[1]
STRATEGY_PARAM_FILES = tuple(sorted((ROOT / "src" / "pgc_trading" / "strategies" / "params").glob("*.json")))


class StrategyHypothesisBacktestServiceTest(unittest.TestCase):
    def test_dry_run_builds_backtest_request_without_writes_or_param_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            reports_dir = Path(tmp) / "reports"
            run_migrations(db_path)
            seed_reference_data(db_path)
            hypothesis_id = _insert_hypothesis(db_path, status="proposed")
            params_before = _strategy_param_file_contents()
            strategy_versions_before = _count_rows(db_path, "strategy_versions")

            service = StrategyHypothesisBacktestService(db_path, reports_dir=reports_dir)
            result = service.create_backtest_request(
                CreateStrategyHypothesisBacktestRequest(hypothesis_id=hypothesis_id),
                RequestContext(request_id="backtest-dry-run", dry_run=True, operator="azboo"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            assert result.data is not None
            self.assertTrue(result.data.would_write_artifact)
            self.assertFalse(result.data.wrote_artifact)
            self.assertIsNone(result.data.artifact_path)
            self.assertFalse(result.data.active_params_mutated)
            self.assertFalse((reports_dir / "strategy_hypothesis_backtests").exists())
            self.assertEqual(_strategy_param_file_contents(), params_before)
            self.assertEqual(_count_rows(db_path, "strategy_versions"), strategy_versions_before)
            self.assertEqual([warning.code for warning in result.warnings], ["BACKTEST_REQUEST_DRY_RUN"])

            artifact = result.data.artifact
            self.assertEqual(artifact["artifact_type"], "strategy_hypothesis_backtest_request")
            self.assertEqual(artifact["hypothesis"]["id"], hypothesis_id)
            self.assertEqual(artifact["backtest_request"]["task_key"], f"strategy-hypothesis:{hypothesis_id}:backtest")
            self.assertTrue(artifact["backtest_request"]["proposed_change"]["requires_replay_backtest"])
            self.assertFalse(artifact["backtest_request"]["proposed_change"]["mutates_active_params"])
            self.assertFalse(artifact["safety"]["active_params_mutated"])
            self.assertTrue(artifact["safety"]["requires_replay_before_param_change"])

    def test_apply_writes_request_artifact_but_not_strategy_version_or_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            reports_dir = Path(tmp) / "reports"
            run_migrations(db_path)
            seed_reference_data(db_path)
            hypothesis_id = _insert_hypothesis(db_path, status="proposed")
            params_before = _strategy_param_file_contents()
            strategy_versions_before = _count_rows(db_path, "strategy_versions")

            service = StrategyHypothesisBacktestService(db_path, reports_dir=reports_dir)
            result = service.create_backtest_request(
                CreateStrategyHypothesisBacktestRequest(hypothesis_id=hypothesis_id),
                RequestContext(request_id="backtest-apply", dry_run=False, operator="azboo"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            assert result.data is not None
            self.assertTrue(result.data.wrote_artifact)
            self.assertIsNotNone(result.data.artifact_path)
            assert result.data.artifact_path is not None
            artifact_path = Path(result.data.artifact_path)
            self.assertTrue(artifact_path.exists())
            self.assertEqual(json.loads(artifact_path.read_text(encoding="utf-8")), result.data.artifact)
            self.assertEqual(_strategy_param_file_contents(), params_before)
            self.assertEqual(_count_rows(db_path, "strategy_versions"), strategy_versions_before)

    def test_accepted_hypothesis_creates_separate_strategy_version_task_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            reports_dir = Path(tmp) / "reports"
            run_migrations(db_path)
            seed_reference_data(db_path)
            hypothesis_id = _insert_hypothesis(db_path, status="accepted")
            params_before = _strategy_param_file_contents()
            strategy_versions_before = _count_rows(db_path, "strategy_versions")

            service = StrategyHypothesisBacktestService(db_path, reports_dir=reports_dir)
            result = service.create_backtest_request(
                CreateStrategyHypothesisBacktestRequest(hypothesis_id=hypothesis_id),
                RequestContext(request_id="accepted-backtest", dry_run=True, operator="azboo"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            assert result.data is not None
            self.assertTrue(result.data.strategy_version_task_required)
            task = result.data.artifact["strategy_version_task"]
            self.assertEqual(task["task_type"], "create_candidate_strategy_version")
            self.assertEqual(task["task_key"], f"strategy-hypothesis:{hypothesis_id}:strategy-version")
            self.assertFalse(task["proposed_change"]["mutates_active_params"])
            self.assertEqual(_strategy_param_file_contents(), params_before)
            self.assertEqual(_count_rows(db_path, "strategy_versions"), strategy_versions_before)
            self.assertIn("STRATEGY_VERSION_TASK_REQUIRED", {warning.code for warning in result.warnings})

    def test_rejects_hypothesis_that_requests_active_param_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            reports_dir = Path(tmp) / "reports"
            run_migrations(db_path)
            seed_reference_data(db_path)
            hypothesis_id = _insert_hypothesis(
                db_path,
                status="proposed",
                proposed_change={"strategy_id": "cpb_6157", "mutates_active_params": True},
            )

            service = StrategyHypothesisBacktestService(db_path, reports_dir=reports_dir)
            result = service.create_backtest_request(
                CreateStrategyHypothesisBacktestRequest(hypothesis_id=hypothesis_id),
                RequestContext(request_id="unsafe-backtest", dry_run=False, operator="azboo"),
            )

            self.assertEqual(result.status, "validation_failed")
            self.assertEqual([error.code for error in result.errors], ["ACTIVE_PARAM_MUTATION_FORBIDDEN"])
            self.assertFalse((reports_dir / "strategy_hypothesis_backtests").exists())


def _insert_hypothesis(
    db_path: Path,
    *,
    status: str,
    proposed_change: dict[str, Any] | None = None,
) -> int:
    change = proposed_change or {
        "strategy_id": "cpb_6157",
        "change_type": "risk_control",
        "rule": {"when": {"market_regime": "risk_off"}, "position_size_multiplier": 0.5},
        "requires_replay_backtest": True,
        "mutates_active_params": False,
    }
    evidence = {
        "source": "market_regime_snapshots",
        "as_of_date": "20260508",
        "regime": "risk_off",
    }
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO strategy_hypotheses
              (as_of_date, hypothesis_type, title, rationale, evidence_json, proposed_change_json, status)
            VALUES
              (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "20260508",
                "market_regime_position_sizing",
                "Reduce position size when market regime is risk_off.",
                "Risk-off market-review evidence should be validated with lower exposure.",
                json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                json.dumps(change, ensure_ascii=False, sort_keys=True),
                status,
            ),
        )
        return int(cursor.lastrowid)


def _count_rows(db_path: Path, table: str) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _strategy_param_file_contents() -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in STRATEGY_PARAM_FILES}


if __name__ == "__main__":
    unittest.main()
