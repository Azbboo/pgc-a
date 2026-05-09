from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.strategy_evolution_service import (
    ListStrategyHypothesesRequest,
    MarkStrategyHypothesisRequest,
    ProposeStrategyHypothesesRequest,
    StrategyEvolutionService,
)
from pgc_trading.storage.migrate import run_migrations


ROOT = Path(__file__).resolve().parents[1]
STRATEGY_PARAM_FILES = tuple(sorted((ROOT / "src" / "pgc_trading" / "strategies" / "params").glob("*.json")))


class StrategyEvolutionServiceTest(unittest.TestCase):
    def test_propose_preview_generates_hypotheses_without_writes_or_param_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)
            _seed_market_review_observations(db_path)
            params_before = _strategy_param_file_contents()

            service = StrategyEvolutionService(db_path)
            result = service.propose_hypotheses(
                ProposeStrategyHypothesesRequest(as_of_date="20260508"),
                RequestContext(request_id="test", dry_run=True, operator="azboo"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            assert result.data is not None
            self.assertEqual(result.data.generated_count, 4)
            self.assertEqual(result.data.would_insert_count, 4)
            self.assertEqual(result.data.inserted_count, 0)
            self.assertEqual(_count_hypotheses(db_path), 0)
            self.assertEqual(_strategy_param_file_contents(), params_before)
            self.assertEqual(
                {item.status for item in result.data.hypotheses},
                {"proposed"},
            )
            for hypothesis in result.data.hypotheses:
                self.assertTrue(hypothesis.evidence)
                self.assertTrue(hypothesis.proposed_change)
                self.assertTrue(hypothesis.proposed_change["requires_replay_backtest"])
                self.assertFalse(hypothesis.proposed_change["mutates_active_params"])

    def test_apply_stores_proposed_hypotheses_and_skips_existing_on_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)
            _seed_market_review_observations(db_path)

            service = StrategyEvolutionService(db_path)
            first = service.propose_hypotheses(
                ProposeStrategyHypothesesRequest(as_of_date="20260508"),
                RequestContext(request_id="test", dry_run=False, operator="azboo"),
            )
            second = service.propose_hypotheses(
                ProposeStrategyHypothesesRequest(as_of_date="20260508"),
                RequestContext(request_id="test", dry_run=False, operator="azboo"),
            )

            self.assertTrue(first.ok)
            self.assertIsNotNone(first.data)
            self.assertIsNotNone(second.data)
            assert first.data is not None
            assert second.data is not None
            self.assertEqual(first.data.inserted_count, 4)
            self.assertEqual(second.data.inserted_count, 0)
            self.assertEqual(second.data.skipped_existing_count, 4)
            self.assertEqual(_count_hypotheses(db_path), 4)
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT status, evidence_json, proposed_change_json FROM strategy_hypotheses"
                ).fetchall()
            self.assertEqual({row[0] for row in rows}, {"proposed"})
            for _, evidence_json, proposed_change_json in rows:
                self.assertIn("as_of_date", evidence_json)
                self.assertIn("requires_replay_backtest", proposed_change_json)

    def test_list_and_mark_review_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)
            _seed_market_review_observations(db_path)
            service = StrategyEvolutionService(db_path)
            proposed = service.propose_hypotheses(
                ProposeStrategyHypothesesRequest(as_of_date="20260508"),
                RequestContext(dry_run=False, operator="azboo"),
            )
            assert proposed.data is not None
            hypothesis_id = proposed.data.hypotheses[0].hypothesis_id
            assert hypothesis_id is not None

            mark = service.mark_hypothesis(
                MarkStrategyHypothesisRequest(hypothesis_id=hypothesis_id, status="testing"),
                RequestContext(request_id="mark", operator="azboo"),
            )
            listed = service.list_hypotheses(
                ListStrategyHypothesesRequest(status="testing", as_of_date="20260508"),
                RequestContext(request_id="list"),
            )

            self.assertEqual(mark.status, "success")
            self.assertIsNotNone(mark.data)
            assert mark.data is not None
            self.assertEqual(mark.data.previous_status, "proposed")
            self.assertEqual(mark.data.hypothesis.status, "testing")
            self.assertEqual(mark.data.operator, "azboo")
            self.assertIsNotNone(listed.data)
            assert listed.data is not None
            self.assertEqual(len(listed.data.hypotheses), 1)
            self.assertEqual(listed.data.hypotheses[0].hypothesis_id, hypothesis_id)

    def test_acceptance_requires_testing_evidence_and_backtest_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            artifact_path = Path(tmp) / "hypothesis_backtest_request.json"
            run_migrations(db_path)
            _seed_market_review_observations(db_path)
            params_before = _strategy_param_file_contents()
            strategy_versions_before = _count_strategy_versions(db_path)
            service = StrategyEvolutionService(db_path)
            proposed = service.propose_hypotheses(
                ProposeStrategyHypothesesRequest(as_of_date="20260508"),
                RequestContext(dry_run=False, operator="azboo"),
            )
            assert proposed.data is not None
            hypothesis_id = proposed.data.hypotheses[0].hypothesis_id
            assert hypothesis_id is not None
            _write_backtest_artifact(artifact_path, hypothesis_id)

            direct_accept = service.mark_hypothesis(
                MarkStrategyHypothesisRequest(
                    hypothesis_id=hypothesis_id,
                    status="accepted",
                    evidence_ids=("market_review_run:1",),
                    backtest_artifact_path=str(artifact_path),
                ),
                RequestContext(request_id="direct-accept", operator="azboo"),
            )
            self.assertEqual(direct_accept.status, "validation_failed")
            self.assertEqual([error.code for error in direct_accept.errors], ["INVALID_HYPOTHESIS_STATUS_TRANSITION"])

            testing = service.mark_hypothesis(
                MarkStrategyHypothesisRequest(
                    hypothesis_id=hypothesis_id,
                    status="testing",
                    review_note="Ready for replay/backtest.",
                ),
                RequestContext(request_id="testing", operator="azboo"),
            )
            missing_gate = service.mark_hypothesis(
                MarkStrategyHypothesisRequest(hypothesis_id=hypothesis_id, status="accepted"),
                RequestContext(request_id="missing-gate", operator="azboo"),
            )
            accepted = service.mark_hypothesis(
                MarkStrategyHypothesisRequest(
                    hypothesis_id=hypothesis_id,
                    status="accepted",
                    review_note="Replay request artifact and evidence are attached.",
                    evidence_ids=("market_review_run:1", "backtest_request:local"),
                    backtest_artifact_path=str(artifact_path),
                ),
                RequestContext(request_id="accepted", operator="azboo"),
            )

            self.assertTrue(testing.ok)
            self.assertEqual(missing_gate.status, "validation_failed")
            self.assertEqual(
                {error.code for error in missing_gate.errors},
                {"ACCEPTED_REQUIRES_VALIDATION_EVIDENCE", "ACCEPTED_REQUIRES_BACKTEST_ARTIFACT"},
            )
            self.assertEqual(accepted.status, "success")
            self.assertIsNotNone(accepted.data)
            assert accepted.data is not None
            self.assertEqual(accepted.data.previous_status, "testing")
            self.assertEqual(accepted.data.hypothesis.status, "accepted")
            self.assertTrue(accepted.data.strategy_version_task_required)
            self.assertIsNotNone(accepted.data.strategy_version_task)
            assert accepted.data.strategy_version_task is not None
            self.assertEqual(
                accepted.data.strategy_version_task["task_key"],
                f"strategy-hypothesis:{hypothesis_id}:strategy-version",
            )
            self.assertFalse(accepted.data.strategy_version_task["proposed_change"]["mutates_active_params"])
            self.assertEqual(_strategy_param_file_contents(), params_before)
            self.assertEqual(_count_strategy_versions(db_path), strategy_versions_before)

            validation = _hypothesis_validation(db_path, hypothesis_id)
            self.assertEqual(validation["evidence_ids"], ["market_review_run:1", "backtest_request:local"])
            self.assertEqual(validation["backtest_artifacts"], [str(artifact_path)])
            self.assertEqual([event["to_status"] for event in validation["review_events"]], ["testing", "accepted"])

    def test_no_observations_is_skipped_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            service = StrategyEvolutionService(db_path)
            result = service.propose_hypotheses(
                ProposeStrategyHypothesesRequest(as_of_date="20260508"),
                RequestContext(dry_run=False, operator="azboo"),
            )

            self.assertEqual(result.status, "skipped")
            self.assertEqual(_count_hypotheses(db_path), 0)
            self.assertEqual([warning.code for warning in result.warnings], ["NO_MARKET_REVIEW_OBSERVATIONS"])


def _seed_market_review_observations(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.execute(
            """
            INSERT INTO market_review_runs
              (as_of_date, status, provider_manifest_json, coverage_json, summary_json, completed_at)
            VALUES
              ('20260508', 'completed', '{}', '{}', '{"summary":"risk off but chips persisted"}', CURRENT_TIMESTAMP)
            """
        )
        run_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO market_regime_snapshots
              (
                market_review_run_id,
                as_of_date,
                regime,
                breadth_score,
                trend_score,
                volume_score,
                sentiment_score,
                persistence_score,
                summary
              )
            VALUES
              (?, '20260508', 'risk_off', 0.30, 0.35, 0.40, 0.20, 0.45, 'Risk-off breadth and sentiment.')
            """,
            (run_id,),
        )
        conn.execute(
            """
            INSERT INTO sector_daily_snapshots
              (
                market_review_run_id,
                as_of_date,
                sector_code,
                sector_name,
                provider,
                rank_overall,
                return_5d,
                persistence_score,
                leader_count
              )
            VALUES
              (?, '20260508', 'BK001', 'Semiconductors', 'manual', 1, 8.5, 0.82, 2)
            """,
            (run_id,),
        )
        conn.execute(
            """
            INSERT INTO sector_constituents
              (market_review_run_id, sector_code, sector_name, ts_code, name, rank_in_sector, role, score)
            VALUES
              (?, 'BK001', 'Semiconductors', '301188.SZ', 'Semiconductor Leader', 1, 'leader', 91.5)
            """,
            (run_id,),
        )
        conn.execute(
            """
            INSERT INTO market_external_items
              (
                as_of_date,
                scope_type,
                scope_key,
                item_type,
                provider,
                title,
                summary,
                sentiment,
                importance,
                published_date,
                source_hash
              )
            VALUES
              (
                '20260508',
                'stock',
                '301188.SZ',
                'news',
                'manual',
                'Customer order warning',
                'A key customer warned that orders may slow.',
                'negative',
                'high',
                '20260508',
                'manual:301188:warning'
              )
            """
        )


def _count_hypotheses(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM strategy_hypotheses").fetchone()[0])


def _count_strategy_versions(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM strategy_versions").fetchone()[0])


def _strategy_param_file_contents() -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in STRATEGY_PARAM_FILES}


def _write_backtest_artifact(path: Path, hypothesis_id: int) -> None:
    path.write_text(
        json.dumps(
            {
                "artifact_type": "strategy_hypothesis_backtest_request",
                "hypothesis": {"id": hypothesis_id},
                "backtest_request": {"task_key": f"strategy-hypothesis:{hypothesis_id}:backtest"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _hypothesis_validation(db_path: Path, hypothesis_id: int) -> dict[str, object]:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT evidence_json FROM strategy_hypotheses WHERE id = ?",
            (hypothesis_id,),
        ).fetchone()
    assert row is not None
    evidence = json.loads(row[0])
    validation = evidence.get("validation")
    assert isinstance(validation, dict)
    return validation


if __name__ == "__main__":
    unittest.main()
