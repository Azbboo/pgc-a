from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.shadow_observation_service import (
    BuildShadowPaperPreflightRequest,
    BuildShadowPromotionDossierRequest,
    BuildShadowPromotionReviewRequest,
    BuildShadowReplayBacktestEvidenceRequest,
    BuildShadowWalkForwardOutcomesRequest,
    GetShadowDecisionMemoRequest,
    GetShadowObservationScorecardRequest,
    GetShadowPromotionReviewRequest,
    ListShadowObservationHistoryRequest,
    ShadowObservationService,
    build_shadow_replay_backtest_source_hash,
    review_shadow_replay_backtest_evidence_artifact,
)
from pgc_trading.services.strategy_evolution_service import review_shadow_paper_preflight_artifact
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
            row_artifacts_json = json.dumps(result.data.rows[0].get("source_artifacts", []), ensure_ascii=False)
            self.assertNotIn("dict_values(", row_artifacts_json)

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

    def test_builds_blocked_review_request_from_latest_promotion_dossier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_shadow_observation_artifacts(reports_dir)
            before_counts = _state_counts(db_path)
            service = ShadowObservationService(db_path, reports_dir=reports_dir)

            dossier_result = service.build_promotion_dossier(
                BuildShadowPromotionDossierRequest(as_of_date="20260512"),
                RequestContext(request_id="req-shadow-dossier-write", dry_run=False, source="test"),
            )
            review_result = service.build_promotion_review_request(
                BuildShadowPromotionReviewRequest(),
                RequestContext(request_id="req-shadow-review-request", dry_run=False, source="test"),
            )

            self.assertTrue(dossier_result.ok, dossier_result.errors)
            self.assertTrue(review_result.ok, review_result.errors)
            self.assertEqual(_state_counts(db_path), before_counts)
            assert review_result.data is not None
            self.assertEqual(review_result.data.review_request_contract, "shadow_promotion_review_request_v1")
            self.assertTrue(review_result.data.wrote_artifact)
            artifact_path = reports_dir / "shadow_promotion_review_request_20260512.json"
            markdown_path = reports_dir / "shadow_promotion_review_request_20260512.md"
            self.assertTrue(artifact_path.exists())
            self.assertTrue(markdown_path.exists())
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["artifact_type"], "shadow_promotion_review_request")
            self.assertEqual(artifact["summary"]["status"], "blocked")
            self.assertEqual(artifact["summary"]["review_ready_count"], 0)
            self.assertEqual(artifact["review_request"]["blocking_reason"], "no_review_ready_candidates")
            decision_keys = [
                item["decision_key"]
                for item in artifact["review_request"]["required_human_decisions"]
            ]
            self.assertIn("manual_promotion_approval_required", decision_keys)
            self.assertIn("future_strategy_version_task_required", decision_keys)
            evidence_json = json.dumps(
                artifact["review_request"]["required_replay_backtest_evidence"],
                ensure_ascii=False,
            )
            self.assertIn("replay_backtest_result_artifact_required", evidence_json)
            self.assertFalse(artifact["safety"]["promotion_allowed"])
            self.assertFalse(artifact["safety"]["writes_trade_state"])
            artifact_json = json.dumps(artifact, ensure_ascii=False)
            self.assertNotIn(str(root), artifact_json)
            self.assertIn("reports/shadow_promotion_dossier_20260512.json", artifact_json)
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("no_review_ready_candidates", markdown)
            self.assertIn("Required Replay/Backtest Evidence", markdown)

    def test_get_promotion_review_request_overlays_current_replay_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_shadow_observation_artifacts(reports_dir)
            service = ShadowObservationService(db_path, reports_dir=reports_dir)

            dossier_result = service.build_promotion_dossier(
                BuildShadowPromotionDossierRequest(as_of_date="20260512"),
                RequestContext(request_id="req-shadow-dossier-write", dry_run=False, source="test"),
            )
            review_result = service.build_promotion_review_request(
                BuildShadowPromotionReviewRequest(as_of_date="20260512"),
                RequestContext(request_id="req-shadow-review-request", dry_run=False, source="test"),
            )
            self.assertTrue(dossier_result.ok, dossier_result.errors)
            self.assertTrue(review_result.ok, review_result.errors)
            stored_artifact = json.loads(
                (reports_dir / "shadow_promotion_review_request_20260512.json").read_text(encoding="utf-8")
            )
            self.assertEqual(stored_artifact["summary"]["replay_backtest_evidence"]["missing_count"], 2)

            _write_shadow_replay_backtest_evidence(
                reports_dir,
                candidate_key="trend_extension_shadow",
                as_of_date="20260512",
            )

            workbench = service.get_promotion_review_request(
                GetShadowPromotionReviewRequest(as_of_date="20260512"),
                RequestContext(request_id="req-shadow-review-workbench", dry_run=True, source="test"),
            )

            self.assertTrue(workbench.ok, workbench.errors)
            assert workbench.data is not None
            replay_summary = workbench.data.summary["replay_backtest_evidence"]
            self.assertEqual(replay_summary["accepted_count"], 1)
            self.assertEqual(replay_summary["missing_count"], 1)
            by_candidate = workbench.data.replay_backtest_evidence["by_candidate"]
            self.assertEqual(by_candidate["trend_extension_shadow"]["status"], "accepted")
            required = {
                item["candidate_key"]: item
                for item in workbench.data.review_request["required_replay_backtest_evidence"]
            }
            self.assertEqual(required["trend_extension_shadow"]["status"], "accepted")
            self.assertFalse(workbench.data.safety["promotion_allowed"])

    def test_shadow_decision_memo_exposes_governed_candidate_decision_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_market_bar(db_path, "300001.SZ", "20260512")
            _seed_shadow_observation_artifacts(reports_dir)
            _write_shadow_replay_backtest_evidence(
                reports_dir,
                candidate_key="trend_extension_shadow",
                as_of_date="20260512",
            )
            _write_shadow_decision_governance_source_artifacts(reports_dir)
            service = ShadowObservationService(db_path, reports_dir=reports_dir)
            before_counts = _state_counts(db_path)
            dossier_result = service.build_promotion_dossier(
                BuildShadowPromotionDossierRequest(as_of_date="20260512"),
                RequestContext(request_id="req-shadow-dossier-for-queue", dry_run=False, source="test"),
            )
            review_result = service.build_promotion_review_request(
                BuildShadowPromotionReviewRequest(as_of_date="20260512"),
                RequestContext(request_id="req-shadow-review-for-queue", dry_run=False, source="test"),
            )

            memo = service.get_decision_memo(
                GetShadowDecisionMemoRequest(as_of_date="20260512"),
                RequestContext(request_id="req-shadow-decision-queue", dry_run=True, source="test"),
            )

            self.assertTrue(dossier_result.ok, dossier_result.errors)
            self.assertTrue(review_result.ok, review_result.errors)
            self.assertTrue(memo.ok, memo.errors)
            self.assertEqual(_state_counts(db_path), before_counts)
            assert memo.data is not None
            queue = memo.data.decision_queue
            self.assertEqual(queue["queue_contract"], "shadow_strategy_decision_queue_v1")
            self.assertEqual(queue["language"], "zh-CN")
            self.assertFalse(queue["promotion_allowed"])
            self.assertEqual(queue["candidate_count"], 2)
            trend = next(
                item
                for item in queue["items"]
                if item["candidate_key"] == "trend_extension_shadow"
            )
            for key in (
                "current_readiness",
                "evidence_status",
                "walk_forward_sufficiency",
                "experiment_status",
                "required_human_decision",
                "stop_rule",
                "next_review_date",
                "promotion_boundary",
            ):
                self.assertIn(key, trend)
            self.assertEqual(trend["evidence_status"]["status"], "accepted")
            self.assertEqual(trend["walk_forward_sufficiency"]["status"], "sufficient")
            self.assertEqual(trend["experiment_status"]["status"], "registered")
            self.assertEqual(trend["next_review_date"], "20260513")
            self.assertIn("stop_if_manual_approval_boundary_changes", trend["stop_rule"]["rule_keys"])
            self.assertTrue(trend["required_human_decision"]["manual_promotion_approval_required"])
            self.assertFalse(trend["promotion_boundary"]["promotion_allowed"])
            self.assertFalse(trend["promotion_boundary"]["strategy_version_publication_allowed"])
            self.assertFalse(trend["promotion_boundary"]["trade_state_writes_allowed"])
            self.assertIn("broker_execution", trend["promotion_boundary"]["blocked_mutation_targets"])
            self.assertFalse(trend["promotion_allowed"])
            self.assertIn("决策队列", memo.data.sections)
            self.assertFalse(memo.data.safety["writes_trade_state"])
            self.assertFalse(memo.data.safety["timer_mutated"])

    def test_builds_manual_shadow_paper_preflight_without_trade_state_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_market_bar(db_path, "300001.SZ", "20260512")
            _seed_shadow_observation_artifacts(reports_dir)
            _write_shadow_replay_backtest_evidence(
                reports_dir,
                candidate_key="trend_extension_shadow",
                as_of_date="20260512",
            )
            _write_shadow_decision_governance_source_artifacts(reports_dir)
            service = ShadowObservationService(db_path, reports_dir=reports_dir)
            before_counts = _state_counts(db_path)
            dossier_result = service.build_promotion_dossier(
                BuildShadowPromotionDossierRequest(as_of_date="20260512"),
                RequestContext(request_id="req-shadow-dossier-for-paper", dry_run=False, source="test"),
            )
            review_result = service.build_promotion_review_request(
                BuildShadowPromotionReviewRequest(as_of_date="20260512"),
                RequestContext(request_id="req-shadow-review-for-paper", dry_run=False, source="test"),
            )

            result = service.build_paper_preflight(
                BuildShadowPaperPreflightRequest(as_of_date="20260512"),
                RequestContext(request_id="req-shadow-paper-preflight", dry_run=False, source="test"),
            )

            self.assertTrue(dossier_result.ok, dossier_result.errors)
            self.assertTrue(review_result.ok, review_result.errors)
            self.assertTrue(result.ok, result.errors)
            self.assertEqual(_state_counts(db_path), before_counts)
            assert result.data is not None
            self.assertEqual(result.data.paper_preflight_contract, "shadow_paper_preflight_v1")
            self.assertTrue(result.data.wrote_artifact)
            artifact_path = reports_dir / "shadow_paper_preflight_20260512.json"
            markdown_path = reports_dir / "shadow_paper_preflight_20260512.md"
            self.assertTrue(artifact_path.exists())
            self.assertTrue(markdown_path.exists())
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["artifact_type"], "shadow_paper_preflight")
            self.assertEqual(artifact["paper_preflight_contract"], "shadow_paper_preflight_v1")
            self.assertEqual(artifact["summary"]["status"], "blocked")
            self.assertEqual(artifact["summary"]["candidate_count"], 2)
            self.assertEqual(artifact["summary"]["future_paper_task_ready_count"], 0)
            self.assertFalse(artifact["summary"]["paper_candidate_allowed"])
            trend = next(
                item
                for item in artifact["candidates"]
                if item["candidate_key"] == "trend_extension_shadow"
            )
            self.assertGreaterEqual(trend["readiness_score"], 80)
            self.assertEqual(trend["evidence_sufficiency"]["status"], "accepted")
            self.assertEqual(trend["walk_forward_sufficiency"]["status"], "sufficient")
            self.assertFalse(trend["paper_candidate_allowed"])
            self.assertFalse(trend["strategy_version_publication_allowed"])
            self.assertFalse(trend["trade_state_writes_allowed"])
            self.assertFalse(trend["broker_execution_allowed"])
            self.assertIn("manual_promotion_approval_required", trend["blockers"])
            approval_keys = [item["approval_key"] for item in artifact["required_human_approvals"]]
            self.assertIn("manual_promotion_approval_required", approval_keys)
            self.assertIn("future_strategy_version_task_required", approval_keys)
            self.assertIn("broker_execution", artifact["release_boundary"]["blocked_mutation_targets"])
            self.assertFalse(artifact["safety"]["writes_trade_state"])
            self.assertFalse(artifact["safety"]["writes_paper_live_behavior"])
            self.assertFalse(artifact["safety"]["timer_mutated"])
            artifact_json = json.dumps(artifact, ensure_ascii=False)
            self.assertNotIn(str(root), artifact_json)
            review = review_shadow_paper_preflight_artifact(artifact_path)
            self.assertTrue(review.valid, review.error)
            self.assertFalse(review.paper_candidate_allowed)
            self.assertFalse(review.writes_trade_state)
            self.assertFalse(review.broker_execution_allowed)
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("纸面预检", markdown)
            self.assertIn("paper_candidate_allowed=false", markdown)

    def test_shadow_observation_history_indexes_scorecard_and_dossier_artifacts_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_shadow_history_artifacts(reports_dir)
            before_counts = _state_counts(db_path)

            result = ShadowObservationService(db_path, reports_dir=reports_dir).list_history(
                ListShadowObservationHistoryRequest(as_of_date="20260513", window=2),
                RequestContext(request_id="req-shadow-history", dry_run=True, source="test"),
            )

            self.assertTrue(result.ok, result.errors)
            self.assertEqual(_state_counts(db_path), before_counts)
            assert result.data is not None
            self.assertEqual(result.data.history_contract, "shadow_observation_history_v1")
            self.assertEqual(result.data.as_of_date, "20260513")
            self.assertEqual(result.data.window, 2)
            self.assertEqual(result.data.counts["date_count"], 2)
            self.assertEqual(result.data.counts["candidate_count"], 2)
            self.assertTrue(result.data.safety["observation_history_is_research_only"])
            self.assertFalse(result.data.safety["writes_trade_state"])
            trend = next(item for item in result.data.candidates if item["candidate_key"] == "trend_extension_shadow")
            self.assertEqual(trend["dates_observed"], 2)
            self.assertEqual(trend["latest_rank"], 1)
            self.assertEqual(trend["score_delta"], 6.0)
            self.assertEqual(trend["latest_review_status"], "blocked")
            self.assertEqual(trend["history"][0]["date"], "20260512")
            self.assertEqual(trend["history"][1]["date"], "20260513")
            self.assertIn("operator_review_required", trend["history"][1]["blockers"])

    def test_shadow_observation_history_keeps_missing_dossier_as_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _write_shadow_history_scorecard(reports_dir, "20260514", trend_score=53.0, breakout_score=45.0)

            result = ShadowObservationService(db_path, reports_dir=reports_dir).list_history(
                ListShadowObservationHistoryRequest(as_of_date="20260514", window=1),
                RequestContext(request_id="req-shadow-history-missing-dossier", dry_run=True, source="test"),
            )

            self.assertTrue(result.ok, result.errors)
            assert result.data is not None
            self.assertEqual(result.data.status, "blocked")
            self.assertEqual(result.data.counts["missing_artifact_date_count"], 1)
            self.assertIn("shadow_promotion_dossier_missing", result.data.rows[0]["missing_artifact_blockers"])
            self.assertIn("shadow_promotion_dossier_missing", result.data.rows[0]["blockers"])
            self.assertEqual(result.data.rows[0]["review_status"], "missing")

    def test_accepted_replay_backtest_evidence_clears_replay_blocker_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_market_bar(db_path, "300001.SZ", "20260512")
            _seed_shadow_observation_artifacts(reports_dir)
            _write_shadow_replay_backtest_evidence(
                reports_dir,
                candidate_key="trend_extension_shadow",
                as_of_date="20260512",
            )

            scorecard = ShadowObservationService(db_path, reports_dir=reports_dir).get_scorecard(
                GetShadowObservationScorecardRequest(as_of_date="20260512"),
                RequestContext(request_id="req-shadow-replay-evidence", dry_run=True, source="test"),
            )

            self.assertTrue(scorecard.ok, scorecard.errors)
            assert scorecard.data is not None
            top = next(row for row in scorecard.data.rows if row["candidate_key"] == "trend_extension_shadow")
            self.assertEqual(top["replay_backtest_evidence"]["status"], "accepted")
            self.assertNotIn("replay_backtest_result_artifact_required", top["blockers"])
            self.assertIn("operator_review_required", top["blockers"])
            self.assertEqual(scorecard.data.counts["replay_backtest_evidence_accepted_count"], 1)
            self.assertEqual(scorecard.data.counts["replay_backtest_evidence_missing_count"], 1)
            self.assertFalse(top["promotion_allowed"])

            dossier = ShadowObservationService(db_path, reports_dir=reports_dir).build_promotion_dossier(
                BuildShadowPromotionDossierRequest(as_of_date="20260512"),
                RequestContext(request_id="req-shadow-replay-dossier", dry_run=True, source="test"),
            )

            self.assertTrue(dossier.ok, dossier.errors)
            assert dossier.data is not None
            candidate = next(
                item
                for item in dossier.data.artifact["candidates"]
                if item["candidate_key"] == "trend_extension_shadow"
            )
            self.assertEqual(candidate["replay_backtest_evidence"]["status"], "accepted")
            self.assertTrue(candidate["readiness_checks"]["replay_backtest_evidence"]["passed"])
            self.assertFalse(dossier.data.artifact["summary"]["promotion_allowed"])

    def test_rejected_replay_backtest_evidence_keeps_specific_blocker_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_market_bar(db_path, "300001.SZ", "20260512")
            _seed_shadow_observation_artifacts(reports_dir)
            _write_shadow_replay_backtest_evidence(
                reports_dir,
                candidate_key="trend_extension_shadow",
                as_of_date="20260512",
                source_hash="bad-hash",
            )

            result = ShadowObservationService(db_path, reports_dir=reports_dir).get_scorecard(
                GetShadowObservationScorecardRequest(as_of_date="20260512"),
                RequestContext(request_id="req-shadow-replay-rejected", dry_run=True, source="test"),
            )

            self.assertTrue(result.ok, result.errors)
            assert result.data is not None
            top = next(row for row in result.data.rows if row["candidate_key"] == "trend_extension_shadow")
            self.assertEqual(top["replay_backtest_evidence"]["status"], "rejected")
            self.assertIn("shadow_replay_backtest_source_hash_mismatch", top["blockers"])
            self.assertIn("replay_backtest_result_artifact_required", top["blockers"])
            self.assertEqual(result.data.counts["replay_backtest_evidence_rejected_count"], 1)

    def test_replay_backtest_evidence_review_rejects_candidate_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp)
            artifact_path = _write_shadow_replay_backtest_evidence(
                reports_dir,
                candidate_key="breakout_pressure_shadow",
                as_of_date="20260512",
            )

            review = review_shadow_replay_backtest_evidence_artifact(
                artifact_path,
                expected_candidate_key="trend_extension_shadow",
                expected_as_of_date="20260512",
                required_sample_size=20,
            )

            self.assertFalse(review.valid)
            self.assertEqual(review.status, "rejected")
            self.assertIn("shadow_replay_backtest_candidate_key_mismatch", review.blockers)

    def test_builds_replay_backtest_evidence_artifacts_from_monitor_and_market_bars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_shadow_replay_market(db_path, sample_days=4)
            _seed_shadow_replay_monitor_artifacts(reports_dir, sample_days=4)
            before_counts = _state_counts(db_path)

            result = ShadowObservationService(db_path, reports_dir=reports_dir).build_replay_backtest_evidence(
                BuildShadowReplayBacktestEvidenceRequest(
                    as_of_date="20260512",
                    required_sample_size=3,
                ),
                RequestContext(request_id="req-shadow-replay-producer", dry_run=False, source="test"),
            )

            self.assertTrue(result.ok, result.errors)
            self.assertEqual(_state_counts(db_path), before_counts)
            assert result.data is not None
            self.assertEqual(result.data.evidence_contract, "shadow_replay_backtest_evidence_v1")
            self.assertTrue(result.data.wrote_artifacts)
            self.assertEqual(result.data.candidate_count, 2)
            self.assertEqual(result.data.accepted_count, 2)
            self.assertEqual(result.data.rejected_count, 0)
            self.assertFalse(result.data.safety["writes_trade_state"])
            accepted_path = reports_dir / "shadow_replay_backtest_evidence_20260512_trend_extension_shadow.json"
            dip_path = reports_dir / "shadow_replay_backtest_evidence_20260512_pullback_dip_buy.json"
            self.assertTrue(accepted_path.exists())
            self.assertTrue(dip_path.exists())
            accepted_review = review_shadow_replay_backtest_evidence_artifact(
                accepted_path,
                expected_candidate_key="trend_extension_shadow",
                expected_as_of_date="20260512",
                required_sample_size=3,
            )
            self.assertTrue(accepted_review.valid, accepted_review.blockers)
            self.assertEqual(accepted_review.status, "accepted")
            dip_review = review_shadow_replay_backtest_evidence_artifact(
                dip_path,
                expected_candidate_key="pullback_dip_buy",
                expected_as_of_date="20260512",
                required_sample_size=3,
            )
            self.assertTrue(dip_review.valid, dip_review.blockers)
            self.assertEqual(dip_review.status, "accepted")
            self.assertEqual(dip_review.metrics["t1_close_mean_pct"], 1.2)
            self.assertEqual(dip_review.metrics["t1_sample_size"], 6)
            artifact = json.loads(accepted_path.read_text(encoding="utf-8"))
            generation = artifact["results"][0]["generation"]
            self.assertEqual(generation["source_kind"], "shadow_monitor_walk_forward_market_bars")
            self.assertEqual(generation["t1_sample_size"], 4)
            self.assertFalse(artifact["safety"]["promotion_allowed"])

    def test_dip_buy_replay_evidence_keeps_metric_gap_when_t1_metrics_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_shadow_replay_market(db_path, sample_days=4)
            _seed_shadow_replay_monitor_artifacts(reports_dir, sample_days=4, dip_has_t1_metrics=False)

            result = ShadowObservationService(db_path, reports_dir=reports_dir).build_replay_backtest_evidence(
                BuildShadowReplayBacktestEvidenceRequest(
                    as_of_date="20260512",
                    required_sample_size=3,
                    candidate_keys=("pullback_dip_buy",),
                ),
                RequestContext(request_id="req-shadow-replay-dip-metric-gap", dry_run=False, source="test"),
            )

            self.assertTrue(result.ok, result.errors)
            assert result.data is not None
            self.assertEqual(result.data.accepted_count, 0)
            self.assertEqual(result.data.rejected_count, 1)
            review = review_shadow_replay_backtest_evidence_artifact(
                reports_dir / "shadow_replay_backtest_evidence_20260512_pullback_dip_buy.json",
                expected_candidate_key="pullback_dip_buy",
                expected_as_of_date="20260512",
                required_sample_size=3,
            )
            self.assertEqual(review.status, "rejected")
            self.assertIn("shadow_replay_backtest_metric_completeness_missing", review.blockers)

    def test_replay_backtest_evidence_generation_keeps_missing_bars_as_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_shadow_replay_market(db_path, sample_days=2)
            _seed_shadow_replay_monitor_artifacts(reports_dir, sample_days=4, include_dip=False)

            result = ShadowObservationService(db_path, reports_dir=reports_dir).build_replay_backtest_evidence(
                BuildShadowReplayBacktestEvidenceRequest(
                    as_of_date="20260512",
                    required_sample_size=4,
                ),
                RequestContext(request_id="req-shadow-replay-missing-bars", dry_run=False, source="test"),
            )

            self.assertTrue(result.ok, result.errors)
            assert result.data is not None
            self.assertEqual(result.data.accepted_count, 0)
            self.assertEqual(result.data.rejected_count, 1)
            artifact = json.loads(
                (reports_dir / "shadow_replay_backtest_evidence_20260512_trend_extension_shadow.json").read_text(
                    encoding="utf-8"
                )
            )
            generation = artifact["results"][0]["generation"]
            self.assertIn("shadow_replay_backtest_missing_bars", generation["blockers"])
            review = review_shadow_replay_backtest_evidence_artifact(
                reports_dir / "shadow_replay_backtest_evidence_20260512_trend_extension_shadow.json",
                expected_candidate_key="trend_extension_shadow",
                expected_as_of_date="20260512",
                required_sample_size=4,
            )
            self.assertEqual(review.status, "rejected")
            self.assertIn("shadow_replay_backtest_sample_size_insufficient", review.blockers)

    def test_builds_walk_forward_outcomes_artifact_without_trade_state_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_shadow_replay_market(db_path, sample_days=4)
            _seed_shadow_replay_monitor_artifacts(reports_dir, sample_days=4)
            before_counts = _state_counts(db_path)

            result = ShadowObservationService(db_path, reports_dir=reports_dir).build_walk_forward_outcomes(
                BuildShadowWalkForwardOutcomesRequest(as_of_date="20260512"),
                RequestContext(request_id="req-shadow-walk-forward-outcomes", dry_run=False, source="test"),
            )

            self.assertTrue(result.ok, result.errors)
            self.assertEqual(_state_counts(db_path), before_counts)
            assert result.data is not None
            self.assertEqual(result.data.outcomes_contract, "shadow_walk_forward_outcomes_v1")
            self.assertTrue(result.data.wrote_artifact)
            self.assertEqual(result.data.status, "partial")
            self.assertGreater(result.data.signal_count, 0)
            self.assertTrue(result.data.no_future_boundary["passed"])
            self.assertFalse(result.data.safety["writes_trade_state"])
            artifact_path = reports_dir / "shadow_walk_forward_outcomes_20260512.json"
            self.assertTrue(artifact_path.exists())
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["artifact_type"], "shadow_walk_forward_outcomes")
            self.assertEqual(artifact["outcomes_contract"], "shadow_walk_forward_outcomes_v1")
            trend = next(item for item in artifact["candidates"] if item["candidate_key"] == "trend_extension_shadow")
            self.assertEqual(trend["status"], "complete")
            self.assertEqual(trend["metrics"]["t1_sample_size"], 4)
            dip = next(item for item in artifact["candidates"] if item["candidate_key"] == "pullback_dip_buy")
            self.assertEqual(dip["status"], "missing")
            self.assertIn("shadow_walk_forward_source_rows_missing", dip["blockers"])

    def test_walk_forward_outcomes_records_missing_market_bars_and_partial_horizons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_shadow_replay_market(db_path, sample_days=2)
            _seed_shadow_replay_monitor_artifacts(reports_dir, sample_days=4, include_dip=False)

            result = ShadowObservationService(db_path, reports_dir=reports_dir).build_walk_forward_outcomes(
                BuildShadowWalkForwardOutcomesRequest(as_of_date="20260512", horizon_days=10),
                RequestContext(request_id="req-shadow-walk-forward-partial", dry_run=False, source="test"),
            )

            self.assertTrue(result.ok, result.errors)
            assert result.data is not None
            self.assertEqual(result.data.status, "partial")
            self.assertGreater(result.data.partial_horizon_count, 0)
            self.assertGreater(result.data.missing_market_bar_count, 0)
            artifact = json.loads(
                (reports_dir / "shadow_walk_forward_outcomes_20260512.json").read_text(encoding="utf-8")
            )
            trend = artifact["candidates"][0]
            self.assertIn("shadow_walk_forward_market_bars_missing", trend["blockers"])
            self.assertIn("shadow_walk_forward_partial_horizon", trend["blockers"])


def _seed_shadow_history_artifacts(reports_dir: Path) -> None:
    _write_shadow_history_scorecard(reports_dir, "20260512", trend_score=44.0, breakout_score=48.0)
    _write_shadow_history_dossier(reports_dir, "20260512", trend_sample=20, breakout_sample=6)
    _write_shadow_history_scorecard(reports_dir, "20260513", trend_score=50.0, breakout_score=42.0)
    _write_shadow_history_dossier(reports_dir, "20260513", trend_sample=20, breakout_sample=7)


def _write_shadow_history_scorecard(
    reports_dir: Path,
    review_date: str,
    *,
    trend_score: float,
    breakout_score: float,
) -> None:
    scorecard = {
        "artifact_type": "shadow_observation_scorecard",
        "review_date": review_date,
        "status": "blocked",
        "read_only": True,
        "artifact_only": True,
        "candidate_count": 2,
        "blocked_candidate_count": 2,
        "candidates": [
            {
                "candidate_key": "trend_extension_shadow",
                "candidate_family": "shadow_bucket",
                "status": "blocked",
                "today_top": {"ts_code": "300001.SZ", "score": trend_score, "review_date": review_date},
                "walk_forward_status": "complete",
                "walk_forward_days": 20,
                "blocker_count": 1,
                "blockers": ["operator_review_required"],
                "comparison_vs_frozen_cpb": {"t1_close_mean_delta_pct": -1.2},
            },
            {
                "candidate_key": "breakout_pressure_shadow",
                "candidate_family": "shadow_bucket",
                "status": "blocked",
                "today_top": {"ts_code": "300002.SZ", "score": breakout_score, "review_date": review_date},
                "walk_forward_status": "partial",
                "walk_forward_days": 7,
                "blocker_count": 2,
                "blockers": ["operator_review_required", "insufficient_sample"],
                "comparison_vs_frozen_cpb": {"t1_close_mean_delta_pct": -3.0},
            },
        ],
        "source_artifacts": {"scorecard": f"reports/shadow_observation_scorecard_{review_date}.json"},
        "safety": {"read_only": True, "artifact_only": True, "promotion_allowed": False},
    }
    (reports_dir / f"shadow_observation_scorecard_{review_date}.json").write_text(
        json.dumps(scorecard),
        encoding="utf-8",
    )


def _write_shadow_history_dossier(
    reports_dir: Path,
    review_date: str,
    *,
    trend_sample: int,
    breakout_sample: int,
) -> None:
    dossier = {
        "artifact_type": "shadow_promotion_dossier",
        "dossier_contract": "shadow_promotion_dossier_v1",
        "as_of_date": review_date,
        "summary": {"candidate_count": 2, "review_ready_count": 0, "blocked_count": 2, "promotion_allowed": False},
        "candidates": [
            {
                "candidate_key": "trend_extension_shadow",
                "candidate_family": "shadow_bucket",
                "review_status": "blocked",
                "sample_size": trend_sample,
                "blocked_reasons": ["candidate_blockers_not_cleared"],
                "readiness_checks": {"minimum_sample": {"actual": trend_sample, "threshold": 20}},
            },
            {
                "candidate_key": "breakout_pressure_shadow",
                "candidate_family": "shadow_bucket",
                "review_status": "blocked",
                "sample_size": breakout_sample,
                "blocked_reasons": ["minimum_sample_not_met"],
                "readiness_checks": {"minimum_sample": {"actual": breakout_sample, "threshold": 20}},
            },
        ],
        "safety": {"read_only": True, "artifact_only": True, "promotion_allowed": False},
    }
    (reports_dir / f"shadow_promotion_dossier_{review_date}.json").write_text(
        json.dumps(dossier),
        encoding="utf-8",
    )


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


def _write_shadow_decision_governance_source_artifacts(reports_dir: Path) -> None:
    scorecard = {
        "artifact_type": "shadow_observation_scorecard",
        "scorecard_contract": "shadow_observation_scorecard_v1",
        "review_date": "20260512",
        "as_of_date": "20260512",
        "status": "blocked",
        "candidate_count": 2,
        "candidates": [
            {
                "candidate_key": "trend_extension_shadow",
                "candidate_family": "shadow_bucket",
                "promotion_readiness": "blocked",
                "walk_forward_status": "complete",
                "walk_forward_days": 20,
                "required_sample_size": 20,
                "blockers": ["operator_review_required"],
                "replay_backtest_evidence": {"status": "accepted", "promotion_allowed": False},
            },
            {
                "candidate_key": "breakout_pressure_shadow",
                "candidate_family": "shadow_bucket",
                "promotion_readiness": "blocked",
                "walk_forward_status": "partial",
                "walk_forward_days": 6,
                "required_sample_size": 20,
                "blockers": ["walk_forward_shadow_monitor_20_trading_days_required"],
                "replay_backtest_evidence": {"status": "missing", "promotion_allowed": False},
            },
        ],
        "summary": {"promotion_allowed": False},
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
        "as_of_date": "20260512",
        "summary": {"status": "partial", "promotion_allowed": False},
        "candidates": [
            {
                "candidate_key": "trend_extension_shadow",
                "status": "complete",
                "signal_count": 20,
                "complete_count": 20,
                "t1_close_mean_pct": 2.4,
            },
            {
                "candidate_key": "breakout_pressure_shadow",
                "status": "partial",
                "signal_count": 6,
                "complete_count": 6,
            },
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
    registry = {
        "artifact_type": "shadow_strategy_experiment_registry",
        "registry_contract": "shadow_strategy_experiment_registry_v1",
        "as_of_date": "20260512",
        "summary": {"status": "artifact_only", "experiment_count": 1, "promotion_allowed": False},
        "experiments": [
            {
                "experiment_key": "trend_extension_shadow:quality_tighten_candidate",
                "candidate_key": "trend_extension_shadow",
                "candidate_family": "shadow_bucket",
                "status": "blocked",
                "required_evidence": [{"evidence_key": "manual_approval_boundary", "status": "required"}],
                "stop_rules": [
                    {
                        "rule_key": "stop_if_manual_approval_boundary_changes",
                        "status": "blocking",
                        "trigger": "promotion permission appears in any artifact",
                    }
                ],
                "rollback_rules": [
                    {"rule_key": "preserve_current_cpb", "writes_trade_state": False},
                ],
                "manual_approval_boundaries": {
                    "manual_promotion_approval_required": True,
                    "strategy_version_publication_allowed": False,
                    "trade_state_writes_allowed": False,
                },
                "release_gate": {"status": "blocked", "promotion_allowed": False},
                "safety": {"artifact_only": True, "promotion_allowed": False, "writes_trade_state": False},
                "artifact_only": True,
                "promotion_allowed": False,
            }
        ],
        "release_gate": {
            "status": "blocked",
            "promotion_allowed": False,
            "blocked_mutation_targets": [
                "active_cpb_params",
                "strategy_versions",
                "trade_plans",
                "trades",
                "positions",
                "paper_live_behavior",
                "broker_execution",
                "timer_state",
            ],
        },
        "manual_approval_boundaries": {
            "manual_promotion_approval_required": True,
            "strategy_version_publication_allowed": False,
            "trade_state_writes_allowed": False,
            "blocked_mutation_targets": [
                "active_cpb_params",
                "strategy_versions",
                "trade_plans",
                "trades",
                "positions",
                "paper_live_behavior",
                "broker_execution",
                "timer_state",
            ],
        },
        "safety": {
            "read_only": True,
            "artifact_only": True,
            "promotion_allowed": False,
            "active_params_mutated": False,
            "wrote_strategy_version": False,
            "wrote_strategy_versions": False,
            "writes_trade_state": False,
            "writes_paper_live_behavior": False,
            "timer_mutated": False,
        },
    }
    (reports_dir / "shadow_observation_scorecard_20260512.json").write_text(
        json.dumps(scorecard),
        encoding="utf-8",
    )
    (reports_dir / "shadow_walk_forward_outcomes_20260512.json").write_text(
        json.dumps(outcomes),
        encoding="utf-8",
    )
    (reports_dir / "shadow_strategy_experiment_registry_20260512.json").write_text(
        json.dumps(registry),
        encoding="utf-8",
    )


def _seed_shadow_replay_monitor_artifacts(
    reports_dir: Path,
    *,
    sample_days: int,
    include_dip: bool = True,
    dip_has_t1_metrics: bool = True,
) -> None:
    rows = []
    for day in range(1, sample_days + 1):
        rows.append(
            {
                "ts_code": f"300{day:03d}.SZ",
                "review_date": f"202605{day:02d}",
                "signal_date": f"202605{day:02d}",
                "planned_buy_date": f"202605{day:02d}",
                "bucket": "trend_extension_shadow",
            }
        )
    trend_monitor = {
        "candidate_key": "trend_extension_shadow",
        "candidate_family": "shadow_bucket",
        "walk_forward_progress": {
            "status": "complete",
            "required_days": sample_days,
            "days": sample_days,
            "start_signal_date": "20260501",
            "latest_signal_date": f"202605{sample_days:02d}",
            "latest_outcome_date": "20260512",
        },
        "comparison_vs_frozen_cpb": {"status": "compared", "candidate_days": sample_days},
        "promotion_gates": {
            "paper_observation_gate": {"allowed": False, "artifact_only": True, "blockers": []},
            "strategy_version_gate": {
                "allowed": False,
                "artifact_only": True,
                "blockers": ["replay_backtest_result_artifact_required"],
            },
        },
    }
    candidate_monitors = [trend_monitor]
    candidate_gates = [
        {
            "candidate_key": "trend_extension_shadow",
            "candidate_family": "shadow_bucket",
            "status": "blocked",
            "walk_forward_progress": trend_monitor["walk_forward_progress"],
            "paper_observation_gate": {"allowed": False, "artifact_only": True, "blockers": []},
            "strategy_version_gate": {
                "allowed": False,
                "artifact_only": True,
                "blockers": ["replay_backtest_result_artifact_required"],
            },
        }
    ]
    if include_dip:
        dip_path = reports_dir / "pgc_pullback_dip_buy.json"
        dip_path.write_text(
            json.dumps(
                {
                    "source_freshness": {
                        "market_data_start_date": "20260501",
                        "market_data_end_date": "20260512",
                    },
                    "selected_variant": "dip_r15_a6_run05",
                    "variants": [
                        {
                            "variant_id": "dip_r15_a6_run05",
                            "fill_n": 6,
                            **(
                                {
                                    "ret_1d_n": 6,
                                    "ret_1d_mean": 0.012,
                                    "ret_1d_win_rate": 0.5,
                                    "mfe_1d_mean": 0.024,
                                }
                                if dip_has_t1_metrics
                                else {}
                            ),
                            "ret_5d_n": 6,
                            "ret_5d_mean": 0.03,
                            "ret_5d_win_rate": 0.66,
                            "mae_10d_median": -0.04,
                        }
                    ],
                    "current_levels": [{"review_date": "20260512"}],
                }
            ),
            encoding="utf-8",
        )
        dip_monitor = {
            "candidate_key": "pullback_dip_buy",
            "candidate_family": "dip_buy",
            "walk_forward_progress": {
                "status": "artifact_summary_only",
                "required_days": 3,
                "observed_trades": 6,
                "source_artifact": str(dip_path),
            },
            "comparison_vs_frozen_cpb": {"status": "compared", "candidate_days": 6},
            "promotion_gates": {
                "paper_observation_gate": {"allowed": False, "artifact_only": True, "blockers": []},
                "strategy_version_gate": {
                    "allowed": False,
                    "artifact_only": True,
                    "blockers": ["replay_backtest_result_artifact_required"],
                },
            },
        }
        candidate_monitors.append(dip_monitor)
        candidate_gates.append(
            {
                "candidate_key": "pullback_dip_buy",
                "candidate_family": "dip_buy",
                "status": "blocked",
                "walk_forward_progress": dip_monitor["walk_forward_progress"],
                "paper_observation_gate": {"allowed": False, "artifact_only": True, "blockers": []},
                "strategy_version_gate": {
                    "allowed": False,
                    "artifact_only": True,
                    "blockers": ["replay_backtest_result_artifact_required"],
                },
            }
        )
    monitor = {
        "review_date": "20260512",
        "next_trade_date": "20260513",
        "walk_forward_progress": {
            "status": "complete",
            "required_days": sample_days,
            "rows": rows,
        },
        "candidate_monitors": candidate_monitors,
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
        "artifact_type": "shadow_strategy_promotion_preflight",
        "review_date": "20260512",
        "next_trade_date": "20260513",
        "status": "blocked",
        "candidate_count": len(candidate_monitors),
        "candidate_gates": candidate_gates,
        "blocker_counts": {"replay_backtest_result_artifact_required": len(candidate_monitors)},
        "safety": monitor["safety"],
    }
    (reports_dir / "strategy_shadow_monitor_20260512.json").write_text(
        json.dumps(monitor, ensure_ascii=False),
        encoding="utf-8",
    )
    (reports_dir / "strategy_shadow_promotion_preflight_20260512.json").write_text(
        json.dumps(preflight, ensure_ascii=False),
        encoding="utf-8",
    )


def _seed_shadow_replay_market(db_path: Path, *, sample_days: int) -> None:
    with sqlite3.connect(db_path) as conn:
        for day in range(1, sample_days + 1):
            ts_code = f"300{day:03d}.SZ"
            for offset in range(5):
                trade_day = day + offset
                open_price = 10.0 + day
                close_price = open_price * (1.01 + offset * 0.005)
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
                        close_price,
                    ),
                )


def _write_shadow_replay_backtest_evidence(
    reports_dir: Path,
    *,
    candidate_key: str,
    as_of_date: str,
    source_hash: str | None = None,
    sample_size: int = 20,
    end_date: str | None = None,
) -> Path:
    metrics = {
        "t1_close_mean_pct": 2.6,
        "t1_close_win_rate_pct": 65.0,
        "t5_close_mean_pct": 4.2,
        "max_drawdown_pct": -5.5,
    }
    start_date = "20260409"
    actual_end_date = end_date or as_of_date
    provider = "unit_test_backtest"
    expected_hash = build_shadow_replay_backtest_source_hash(
        provider=provider,
        candidate_key=candidate_key,
        start_date=start_date,
        end_date=actual_end_date,
        sample_size=sample_size,
        metrics=metrics,
    )
    payload = {
        "artifact_type": "shadow_replay_backtest_evidence",
        "evidence_contract": "shadow_replay_backtest_evidence_v1",
        "provider": provider,
        "as_of_date": as_of_date,
        "results": [
            {
                "candidate_key": candidate_key,
                "candidate_family": "shadow_bucket",
                "date_range": {"start_date": start_date, "end_date": actual_end_date},
                "sample_size": sample_size,
                "metrics": metrics,
                "source_hash": source_hash or expected_hash,
                "no_future_boundary": {
                    "passed": True,
                    "max_input_date": actual_end_date,
                    "data_cutoff_date": actual_end_date,
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
    path = reports_dir / f"shadow_replay_backtest_evidence_{as_of_date}_{candidate_key}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


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
