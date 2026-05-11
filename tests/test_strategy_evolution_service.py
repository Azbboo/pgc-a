from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.strategy_evolution_service import (
    CreateStrategyVersionProposalReviewRequest,
    CreateStrategyVersionProposalRequest,
    EvaluateStrategyHypothesesRequest,
    ListStrategyHypothesesRequest,
    MarkStrategyHypothesisRequest,
    ProposeStrategyHypothesesRequest,
    StrategyEvolutionService,
    review_strategy_version_proposal_review_artifact,
    review_strategy_version_proposal_artifact,
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

    def test_strategy_version_proposal_dry_run_builds_artifact_without_strategy_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            reports_dir = Path(tmp) / "reports"
            artifact_path = Path(tmp) / "hypothesis_backtest_request.json"
            run_migrations(db_path)
            _seed_market_review_observations(db_path)
            params_before = _strategy_param_file_contents()
            strategy_versions_before = _count_strategy_versions(db_path)
            service = StrategyEvolutionService(db_path, reports_dir=reports_dir)
            hypothesis_id = _accepted_hypothesis(service, artifact_path)

            result = service.create_strategy_version_proposal(
                CreateStrategyVersionProposalRequest(hypothesis_id=hypothesis_id),
                RequestContext(request_id="proposal-dry-run", dry_run=True, operator="azboo"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            assert result.data is not None
            self.assertTrue(result.data.would_write_artifact)
            self.assertFalse(result.data.wrote_artifact)
            self.assertIsNone(result.data.artifact_path)
            self.assertFalse(result.data.active_params_mutated)
            self.assertFalse(result.data.wrote_strategy_version)
            self.assertFalse((reports_dir / "strategy_version_proposals").exists())
            self.assertEqual(_strategy_param_file_contents(), params_before)
            self.assertEqual(_count_strategy_versions(db_path), strategy_versions_before)

            artifact = result.data.artifact
            self.assertEqual(artifact["artifact_type"], "strategy_version_proposal")
            self.assertEqual(artifact["hypothesis"]["id"], hypothesis_id)
            self.assertEqual(
                artifact["proposal"]["proposal_key"],
                f"strategy-hypothesis:{hypothesis_id}:strategy-version-proposal",
            )
            self.assertEqual(
                artifact["proposal"]["strategy_version_task_key"],
                f"strategy-hypothesis:{hypothesis_id}:strategy-version",
            )
            self.assertFalse(artifact["proposal"]["proposed_change"]["mutates_active_params"])
            self.assertFalse(artifact["safety"]["active_params_mutated"])
            self.assertFalse(artifact["safety"]["wrote_strategy_versions"])
            self.assertTrue(artifact["promotion_gate"]["proposal_artifact_only"])

    def test_strategy_version_proposal_apply_writes_artifact_and_records_validation_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            reports_dir = Path(tmp) / "reports"
            backtest_path = Path(tmp) / "hypothesis_backtest_request.json"
            output_path = Path(tmp) / "custom_strategy_version_proposal.json"
            run_migrations(db_path)
            _seed_market_review_observations(db_path)
            params_before = _strategy_param_file_contents()
            strategy_versions_before = _count_strategy_versions(db_path)
            service = StrategyEvolutionService(db_path, reports_dir=reports_dir)
            hypothesis_id = _accepted_hypothesis(service, backtest_path)

            result = service.create_strategy_version_proposal(
                CreateStrategyVersionProposalRequest(
                    hypothesis_id=hypothesis_id,
                    output_path=str(output_path),
                ),
                RequestContext(request_id="proposal-apply", dry_run=False, operator="azboo"),
            )
            evaluation = service.evaluate_hypotheses(
                EvaluateStrategyHypothesesRequest(status="accepted", as_of_date="20260508", limit=10),
                RequestContext(request_id="workbench", dry_run=True),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            assert result.data is not None
            self.assertTrue(result.data.wrote_artifact)
            self.assertTrue(output_path.exists())
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), result.data.artifact)
            validation = _hypothesis_validation(db_path, hypothesis_id)
            self.assertEqual(validation["strategy_version_proposals"], [str(output_path)])
            self.assertEqual(
                validation["strategy_version_proposal_key"],
                f"strategy-hypothesis:{hypothesis_id}:strategy-version-proposal",
            )
            self.assertEqual(_strategy_param_file_contents(), params_before)
            self.assertEqual(_count_strategy_versions(db_path), strategy_versions_before)

            self.assertIsNotNone(evaluation.data)
            assert evaluation.data is not None
            reviewed = evaluation.data.hypotheses[0].strategy_version_proposals[0]
            self.assertTrue(reviewed.valid)
            self.assertEqual(reviewed.proposal_key, f"strategy-hypothesis:{hypothesis_id}:strategy-version-proposal")
            self.assertEqual(evaluation.data.summary["proposal_artifact_count"], 1)
            self.assertEqual(evaluation.data.summary["proposal_ready_count"], 1)

    def test_strategy_version_proposal_review_dry_run_builds_artifact_without_strategy_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            reports_dir = Path(tmp) / "reports"
            backtest_path = Path(tmp) / "hypothesis_backtest_request.json"
            proposal_path = Path(tmp) / "strategy_version_proposal.json"
            run_migrations(db_path)
            _seed_market_review_observations(db_path)
            params_before = _strategy_param_file_contents()
            strategy_versions_before = _count_strategy_versions(db_path)
            service = StrategyEvolutionService(db_path, reports_dir=reports_dir)
            hypothesis_id = _accepted_hypothesis(service, backtest_path)
            proposal = service.create_strategy_version_proposal(
                CreateStrategyVersionProposalRequest(
                    hypothesis_id=hypothesis_id,
                    output_path=str(proposal_path),
                ),
                RequestContext(request_id="proposal-apply", dry_run=False, operator="azboo"),
            )
            assert proposal.ok

            result = service.create_strategy_version_proposal_review(
                CreateStrategyVersionProposalReviewRequest(
                    hypothesis_id=hypothesis_id,
                    decision="approve",
                    review_note="Proposal artifact is ready for promotion request review.",
                ),
                RequestContext(request_id="proposal-review-dry-run", dry_run=True, operator="azboo"),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            assert result.data is not None
            self.assertTrue(result.data.would_write_artifact)
            self.assertFalse(result.data.wrote_artifact)
            self.assertIsNone(result.data.artifact_path)
            self.assertEqual(result.data.proposal_artifact_path, str(proposal_path))
            self.assertEqual(result.data.decision, "approve")
            self.assertFalse(result.data.active_params_mutated)
            self.assertFalse(result.data.wrote_strategy_version)
            self.assertFalse(result.data.writes_trade_state)
            self.assertFalse(result.data.writes_paper_live_behavior)
            self.assertEqual(result.data.artifact["artifact_type"], "strategy_version_proposal_review")
            self.assertEqual(result.data.artifact["review"]["decision"], "approve")
            self.assertTrue(result.data.artifact["promotion_gate"]["artifact_only"])
            self.assertFalse((reports_dir / "strategy_proposal_reviews").exists())
            validation = _hypothesis_validation(db_path, hypothesis_id)
            self.assertNotIn("strategy_version_proposal_reviews", validation)
            self.assertEqual(_strategy_param_file_contents(), params_before)
            self.assertEqual(_count_strategy_versions(db_path), strategy_versions_before)

    def test_strategy_version_promotion_request_apply_records_review_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            reports_dir = Path(tmp) / "reports"
            backtest_path = Path(tmp) / "hypothesis_backtest_request.json"
            proposal_path = Path(tmp) / "strategy_version_proposal.json"
            promotion_path = Path(tmp) / "strategy_promotion_request.json"
            run_migrations(db_path)
            _seed_market_review_observations(db_path)
            params_before = _strategy_param_file_contents()
            strategy_versions_before = _count_strategy_versions(db_path)
            service = StrategyEvolutionService(db_path, reports_dir=reports_dir)
            hypothesis_id = _accepted_hypothesis(service, backtest_path)
            proposal = service.create_strategy_version_proposal(
                CreateStrategyVersionProposalRequest(
                    hypothesis_id=hypothesis_id,
                    output_path=str(proposal_path),
                ),
                RequestContext(request_id="proposal-apply", dry_run=False, operator="azboo"),
            )
            assert proposal.ok

            result = service.create_strategy_version_proposal_review(
                CreateStrategyVersionProposalReviewRequest(
                    hypothesis_id=hypothesis_id,
                    decision="request_promotion",
                    review_note="Request a candidate promotion task from the approved proposal.",
                    output_path=str(promotion_path),
                ),
                RequestContext(
                    request_id="promotion-request",
                    idempotency_key="test:promotion-request",
                    dry_run=False,
                    operator="azboo",
                ),
            )
            evaluation = service.evaluate_hypotheses(
                EvaluateStrategyHypothesesRequest(status="accepted", as_of_date="20260508", limit=10),
                RequestContext(request_id="workbench", dry_run=True),
            )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            assert result.data is not None
            self.assertTrue(result.data.wrote_artifact)
            self.assertEqual(result.data.decision, "request_promotion")
            self.assertEqual(result.data.proposal_artifact_path, str(proposal_path))
            self.assertTrue(promotion_path.exists())
            artifact = json.loads(promotion_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["artifact_type"], "strategy_version_promotion_request")
            self.assertEqual(artifact["promotion_request"]["status"], "requested")
            self.assertTrue(artifact["promotion_request"]["artifact_only"])
            validation = _hypothesis_validation(db_path, hypothesis_id)
            self.assertEqual(validation["strategy_version_proposal_reviews"], [str(promotion_path)])
            self.assertEqual(validation["strategy_version_promotion_requests"], [str(promotion_path)])
            self.assertEqual(validation["latest_strategy_version_proposal_review_decision"], "request_promotion")
            self.assertEqual(
                validation["latest_strategy_version_promotion_request_key"],
                f"strategy-hypothesis:{hypothesis_id}:strategy-version-promotion-request",
            )
            self.assertEqual(_strategy_param_file_contents(), params_before)
            self.assertEqual(_count_strategy_versions(db_path), strategy_versions_before)

            self.assertIsNotNone(evaluation.data)
            assert evaluation.data is not None
            reviewed = evaluation.data.hypotheses[0].strategy_version_proposal_reviews[0]
            self.assertTrue(reviewed.valid)
            self.assertEqual(reviewed.decision, "request_promotion")
            self.assertEqual(evaluation.data.hypotheses[0].next_action, "promotion_requested")
            self.assertEqual(evaluation.data.summary["proposal_review_artifact_count"], 1)
            self.assertEqual(evaluation.data.summary["promotion_request_count"], 1)

    def test_strategy_version_proposal_requires_accepted_hypothesis_and_valid_backtest_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            reports_dir = Path(tmp) / "reports"
            run_migrations(db_path)
            _seed_market_review_observations(db_path)
            service = StrategyEvolutionService(db_path, reports_dir=reports_dir)
            proposed = service.propose_hypotheses(
                ProposeStrategyHypothesesRequest(as_of_date="20260508"),
                RequestContext(dry_run=False, operator="azboo"),
            )
            assert proposed.data is not None
            hypothesis_id = proposed.data.hypotheses[0].hypothesis_id
            assert hypothesis_id is not None

            result = service.create_strategy_version_proposal(
                CreateStrategyVersionProposalRequest(hypothesis_id=hypothesis_id),
                RequestContext(request_id="proposal-blocked", dry_run=False, operator="azboo"),
            )

            self.assertEqual(result.status, "validation_failed")
            self.assertEqual([error.code for error in result.errors], ["PROPOSAL_REQUIRES_ACCEPTED_HYPOTHESIS"])
            self.assertFalse((reports_dir / "strategy_version_proposals").exists())

    def test_reviews_strategy_version_proposal_artifact_for_workbench_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_path = Path(tmp) / "strategy_version_proposal.json"
            _write_strategy_version_proposal_artifact(artifact_path, hypothesis_id=7)

            review = review_strategy_version_proposal_artifact(artifact_path, expected_hypothesis_id=7)
            mismatch = review_strategy_version_proposal_artifact(artifact_path, expected_hypothesis_id=8)
            missing = review_strategy_version_proposal_artifact(Path(tmp) / "missing.json", expected_hypothesis_id=7)

            self.assertTrue(review.exists)
            self.assertTrue(review.valid)
            self.assertEqual(review.hypothesis_id, 7)
            self.assertTrue(review.hypothesis_matches)
            self.assertEqual(review.proposal_key, "strategy-hypothesis:7:strategy-version-proposal")
            self.assertFalse(review.active_params_mutated)
            self.assertFalse(review.wrote_strategy_versions)
            self.assertFalse(mismatch.valid)
            self.assertEqual(mismatch.error, "strategy-version proposal artifact hypothesis id does not match.")
            self.assertFalse(missing.exists)
            self.assertFalse(missing.valid)

    def test_reviews_strategy_version_proposal_review_artifact_for_workbench_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            review_path = Path(tmp) / "strategy_version_proposal_review.json"
            promotion_path = Path(tmp) / "strategy_version_promotion_request.json"
            _write_strategy_version_proposal_review_artifact(review_path, hypothesis_id=7, decision="approve")
            _write_strategy_version_proposal_review_artifact(
                promotion_path,
                hypothesis_id=7,
                decision="request_promotion",
            )

            review = review_strategy_version_proposal_review_artifact(
                review_path,
                expected_hypothesis_id=7,
                expected_proposal_key="strategy-hypothesis:7:strategy-version-proposal",
            )
            promotion = review_strategy_version_proposal_review_artifact(
                promotion_path,
                expected_hypothesis_id=7,
                expected_proposal_key="strategy-hypothesis:7:strategy-version-proposal",
            )
            mismatch = review_strategy_version_proposal_review_artifact(
                review_path,
                expected_hypothesis_id=8,
            )

            self.assertTrue(review.exists)
            self.assertTrue(review.valid)
            self.assertEqual(review.decision, "approve")
            self.assertEqual(review.proposal_key, "strategy-hypothesis:7:strategy-version-proposal")
            self.assertFalse(review.active_params_mutated)
            self.assertTrue(promotion.valid)
            self.assertEqual(promotion.artifact_type, "strategy_version_promotion_request")
            self.assertEqual(promotion.promotion_request_key, "strategy-hypothesis:7:strategy-version-promotion-request")
            self.assertFalse(mismatch.valid)
            self.assertEqual(mismatch.error, "proposal review artifact hypothesis id does not match.")

    def test_strategy_version_proposal_review_requires_accepted_hypothesis_and_valid_proposal_for_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            reports_dir = Path(tmp) / "reports"
            invalid_proposal_path = Path(tmp) / "invalid_strategy_version_proposal.json"
            run_migrations(db_path)
            _seed_market_review_observations(db_path)
            service = StrategyEvolutionService(db_path, reports_dir=reports_dir)
            proposed = service.propose_hypotheses(
                ProposeStrategyHypothesesRequest(as_of_date="20260508"),
                RequestContext(dry_run=False, operator="azboo"),
            )
            assert proposed.data is not None
            hypothesis_id = proposed.data.hypotheses[0].hypothesis_id
            assert hypothesis_id is not None
            _write_strategy_version_proposal_artifact(invalid_proposal_path, hypothesis_id=hypothesis_id)
            invalid_artifact = json.loads(invalid_proposal_path.read_text(encoding="utf-8"))
            invalid_artifact["safety"]["wrote_strategy_versions"] = True
            invalid_proposal_path.write_text(json.dumps(invalid_artifact), encoding="utf-8")

            wrong_status = service.create_strategy_version_proposal_review(
                CreateStrategyVersionProposalReviewRequest(
                    hypothesis_id=hypothesis_id,
                    decision="approve",
                    proposal_artifact_path=str(invalid_proposal_path),
                ),
                RequestContext(request_id="proposal-review-blocked", dry_run=False, operator="azboo"),
            )

            self.assertEqual(wrong_status.status, "validation_failed")
            self.assertEqual(
                {error.code for error in wrong_status.errors},
                {"PROPOSAL_REVIEW_REQUIRES_ACCEPTED_HYPOTHESIS", "PROPOSAL_REVIEW_REQUIRES_VALID_PROPOSAL"},
            )
            self.assertFalse((reports_dir / "strategy_proposal_reviews").exists())

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

    def test_evaluation_workbench_reviews_evidence_and_backtest_artifacts_without_writes(self) -> None:
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
            testing = service.mark_hypothesis(
                MarkStrategyHypothesisRequest(
                    hypothesis_id=hypothesis_id,
                    status="testing",
                    evidence_ids=("market_review_run:1",),
                    backtest_artifact_path=str(artifact_path),
                ),
                RequestContext(request_id="testing", operator="azboo"),
            )

            result = service.evaluate_hypotheses(
                EvaluateStrategyHypothesesRequest(status="testing", as_of_date="20260508", limit=10),
                RequestContext(request_id="workbench", dry_run=True, operator="azboo"),
            )

            self.assertTrue(testing.ok)
            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.data)
            assert result.data is not None
            self.assertEqual(result.data.summary["total"], 1)
            self.assertEqual(result.data.summary["ready_to_accept_count"], 1)
            self.assertEqual(result.data.summary["artifact_count"], 1)
            self.assertEqual(result.data.summary["invalid_artifact_count"], 0)
            self.assertTrue(result.data.safety["read_only"])
            self.assertFalse(result.data.safety["active_params_mutated"])
            evaluation = result.data.hypotheses[0]
            self.assertEqual(evaluation.hypothesis.hypothesis_id, hypothesis_id)
            self.assertEqual(evaluation.next_action, "ready_to_accept")
            self.assertTrue(evaluation.acceptance_gate["can_accept"])
            self.assertEqual(evaluation.acceptance_gate["blocks"], [])
            self.assertEqual(evaluation.evidence_ids, ["market_review_run:1"])
            self.assertTrue(evaluation.backtest_artifacts[0].valid)
            self.assertEqual(evaluation.strategy_version_proposals, [])
            self.assertIsNone(evaluation.strategy_version_task)
            self.assertEqual(_strategy_param_file_contents(), params_before)
            self.assertEqual(_count_strategy_versions(db_path), strategy_versions_before)


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
                "validation_gate": {"accepted_is_research_outcome_only": True},
                "safety": {"active_params_mutated": False},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _accepted_hypothesis(service: StrategyEvolutionService, artifact_path: Path) -> int:
    proposed = service.propose_hypotheses(
        ProposeStrategyHypothesesRequest(as_of_date="20260508"),
        RequestContext(dry_run=False, operator="azboo"),
    )
    assert proposed.data is not None
    hypothesis_id = proposed.data.hypotheses[0].hypothesis_id
    assert hypothesis_id is not None
    _write_backtest_artifact(artifact_path, hypothesis_id)
    testing = service.mark_hypothesis(
        MarkStrategyHypothesisRequest(
            hypothesis_id=hypothesis_id,
            status="testing",
            review_note="Ready for replay/backtest.",
        ),
        RequestContext(request_id="testing", operator="azboo"),
    )
    accepted = service.mark_hypothesis(
        MarkStrategyHypothesisRequest(
            hypothesis_id=hypothesis_id,
            status="accepted",
            review_note="Replay request artifact and evidence are attached.",
            evidence_ids=("market_review_run:1",),
            backtest_artifact_path=str(artifact_path),
        ),
        RequestContext(request_id="accepted", operator="azboo"),
    )
    assert testing.ok
    assert accepted.ok
    return hypothesis_id


def _write_strategy_version_proposal_artifact(path: Path, hypothesis_id: int) -> None:
    path.write_text(
        json.dumps(
            {
                "artifact_type": "strategy_version_proposal",
                "hypothesis": {"id": hypothesis_id},
                "proposal": {
                    "proposal_key": f"strategy-hypothesis:{hypothesis_id}:strategy-version-proposal",
                    "strategy_version_task_key": f"strategy-hypothesis:{hypothesis_id}:strategy-version",
                    "candidate_strategy_version": f"cpb_6157-proposal-h{hypothesis_id}-20260508",
                },
                "promotion_gate": {"proposal_artifact_only": True},
                "safety": {
                    "active_params_mutated": False,
                    "wrote_strategy_versions": False,
                    "writes_trade_state": False,
                    "writes_paper_live_behavior": False,
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _write_strategy_version_proposal_review_artifact(path: Path, hypothesis_id: int, decision: str) -> None:
    proposal_key = f"strategy-hypothesis:{hypothesis_id}:strategy-version-proposal"
    payload = {
        "artifact_type": (
            "strategy_version_promotion_request"
            if decision == "request_promotion"
            else "strategy_version_proposal_review"
        ),
        "hypothesis": {"id": hypothesis_id},
        "proposal": {"proposal_key": proposal_key},
        "review": {
            "review_key": f"strategy-hypothesis:{hypothesis_id}:strategy-proposal-review:{decision}",
            "proposal_key": proposal_key,
            "decision": decision,
        },
        "promotion_gate": {"artifact_only": True},
        "safety": {
            "active_params_mutated": False,
            "wrote_strategy_versions": False,
            "writes_trade_state": False,
            "writes_paper_live_behavior": False,
        },
    }
    if decision == "request_promotion":
        payload["promotion_request"] = {
            "request_key": f"strategy-hypothesis:{hypothesis_id}:strategy-version-promotion-request",
            "artifact_only": True,
        }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


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
