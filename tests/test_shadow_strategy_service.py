from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.shadow_strategy_service import (
    GetShadowStrategySnapshotRequest,
    SHADOW_STRATEGY_SNAPSHOT_CONTRACT,
    ShadowStrategyService,
)
from pgc_trading.storage.database import connect
from pgc_trading.storage.migrate import run_migrations


class ShadowStrategyServiceTest(unittest.TestCase):
    def test_snapshot_normalizes_latest_artifacts_and_shadow_hypotheses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_shadow_hypotheses(db_path)
            _write_shadow_artifacts(reports_dir)
            before_count = _hypothesis_count(db_path)

            result = ShadowStrategyService(db_path, reports_dir=reports_dir).get_snapshot(
                GetShadowStrategySnapshotRequest(),
                RequestContext(request_id="shadow-snapshot-test", dry_run=True, source="test"),
            )

            self.assertTrue(result.ok)
            assert result.data is not None
            snapshot = result.data
            self.assertEqual(snapshot.snapshot_contract, SHADOW_STRATEGY_SNAPSHOT_CONTRACT)
            self.assertEqual(snapshot.as_of_date, "20260512")
            self.assertEqual(snapshot.status, "blocked")
            self.assertTrue(snapshot.read_only)
            self.assertTrue(snapshot.artifact_only)
            self.assertEqual(snapshot.counts["candidate_count"], 2)
            self.assertEqual(snapshot.counts["today_candidate_count"], 11)
            self.assertEqual(snapshot.counts["shadow_hypothesis_count"], 2)
            self.assertEqual(snapshot.blocker_counts["operator_review_required"], 2)
            self.assertEqual(snapshot.candidate_families["shadow_bucket"], 1)
            self.assertEqual(snapshot.walk_forward["status"], "partial")
            self.assertEqual(snapshot.source_artifacts["monitor_json"], str(reports_dir / "strategy_shadow_monitor_20260512.json"))
            self.assertEqual(
                snapshot.source_artifacts["promotion_preflight_json"],
                str(reports_dir / "strategy_shadow_promotion_preflight_20260512.json"),
            )
            self.assertFalse(snapshot.safety["active_params_mutated"])
            self.assertFalse(snapshot.safety["writes_trade_state"])
            self.assertTrue(snapshot.safety["artifact_only"])
            self.assertFalse(snapshot.safety["promotion_allowed"])
            self.assertEqual(snapshot.active_cpb_integrity["status"], "unchanged")
            self.assertEqual(snapshot.release_gate["status"], "blocked")
            self.assertFalse(snapshot.release_gate["timer_mutated"])

            trend = snapshot.candidates[0]
            self.assertEqual(trend["candidate_key"], "trend_extension_shadow")
            self.assertEqual(trend["walk_forward_status"], "partial")
            self.assertEqual(trend["paper_blocker_count"], 2)
            self.assertEqual(trend["strategy_version_blocker_count"], 2)
            self.assertEqual(trend["linked_hypothesis"]["status"], "testing")
            self.assertTrue(trend["artifact_only"])

            self.assertEqual(_hypothesis_count(db_path), before_count)

    def test_snapshot_can_load_a_requested_artifact_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_shadow_hypotheses(db_path)
            _write_shadow_artifacts(reports_dir)
            (reports_dir / "strategy_shadow_monitor_20260511.json").write_text(
                json.dumps({"review_date": "20260511", "candidate_monitors": []}),
                encoding="utf-8",
            )
            (reports_dir / "strategy_shadow_promotion_preflight_20260511.json").write_text(
                json.dumps({"review_date": "20260511", "status": "blocked", "candidate_gates": []}),
                encoding="utf-8",
            )

            result = ShadowStrategyService(db_path, reports_dir=reports_dir).get_snapshot(
                GetShadowStrategySnapshotRequest(as_of_date="2026-05-11"),
                RequestContext(request_id="shadow-snapshot-date", dry_run=True, source="test"),
            )

            self.assertTrue(result.ok)
            assert result.data is not None
            self.assertEqual(result.data.as_of_date, "20260511")
            self.assertEqual(result.data.counts["candidate_count"], 0)

    def test_snapshot_rejects_artifacts_that_report_visibility_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "pgc.db"
            reports_dir = root / "reports"
            reports_dir.mkdir()
            run_migrations(db_path)
            _seed_shadow_hypotheses(db_path)
            _write_shadow_artifacts(reports_dir)
            preflight_path = reports_dir / "strategy_shadow_promotion_preflight_20260512.json"
            preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
            preflight["safety"]["timer_mutated"] = True
            preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
            before_count = _hypothesis_count(db_path)

            result = ShadowStrategyService(db_path, reports_dir=reports_dir).get_snapshot(
                GetShadowStrategySnapshotRequest(as_of_date="20260512"),
                RequestContext(request_id="shadow-snapshot-unsafe", dry_run=True, source="test"),
            )

            self.assertEqual(result.status, "validation_failed")
            self.assertIn("SHADOW_VISIBILITY_MUTATION_RISK", {error.code for error in result.errors})
            assert result.data is not None
            self.assertEqual(result.data.status, "unavailable")
            self.assertFalse(result.data.safety["timer_mutated"])
            self.assertEqual(_hypothesis_count(db_path), before_count)


def _seed_shadow_hypotheses(db_path: Path) -> None:
    with connect(db_path) as conn:
        _insert_hypothesis(conn, "trend_extension_shadow", "testing")
        _insert_hypothesis(conn, "preconfirm_watchlist", "proposed")
        conn.execute(
            """
            INSERT INTO strategy_hypotheses
              (as_of_date, hypothesis_type, title, rationale, evidence_json, proposed_change_json, status)
            VALUES ('20260512', 'breadth', 'Breadth', 'Non-shadow row.', '{}', '{}', 'proposed')
            """
        )


def _insert_hypothesis(conn, candidate_key: str, status: str) -> None:
    evidence = {
        "source": "m69_shadow_research",
        "artifact_only": True,
        "candidate_key": candidate_key,
        "candidate_family": "shadow_bucket" if candidate_key.endswith("_shadow") else candidate_key,
        "artifact_paths": [f"reports/{candidate_key}.json"],
        "paper_observation_gate": {
            "status": "blocked",
            "allowed": False,
            "artifact_only": True,
            "blockers": ["paper_observation_not_authorized", "operator_review_required"],
        },
        "strategy_version_gate": {
            "status": "blocked",
            "allowed": False,
            "artifact_only": True,
            "blockers": ["strategy_version_proposal_not_authorized", "proposal_review_required"],
        },
    }
    proposed_change = {
        "change_type": "shadow_candidate",
        "candidate_key": candidate_key,
        "candidate_family": evidence["candidate_family"],
        "artifact_only": True,
        "mutates_active_params": False,
    }
    conn.execute(
        """
        INSERT INTO strategy_hypotheses
          (as_of_date, hypothesis_type, title, rationale, evidence_json, proposed_change_json, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "20260512",
            f"shadow_{candidate_key}",
            f"{candidate_key} candidate",
            "Research-only shadow candidate.",
            json.dumps(evidence),
            json.dumps(proposed_change),
            status,
        ),
    )


def _write_shadow_artifacts(reports_dir: Path) -> None:
    candidate_gates = [
        {
            "candidate_key": "trend_extension_shadow",
            "candidate_family": "shadow_bucket",
            "walk_forward_progress": {"status": "partial", "required_days": 20, "days": 12},
            "comparison_vs_frozen_cpb": {
                "status": "compared",
                "baseline_label": "active_cpb_persisted_picks",
                "candidate_days": 12,
                "t1_close_mean_delta_pct": -1.2,
            },
            "paper_observation_gate": {
                "status": "blocked",
                "allowed": False,
                "artifact_only": True,
                "blockers": ["paper_observation_not_authorized", "operator_review_required"],
            },
            "strategy_version_gate": {
                "status": "blocked",
                "allowed": False,
                "artifact_only": True,
                "blockers": ["strategy_version_proposal_not_authorized", "proposal_review_required"],
            },
            "status": "blocked",
        },
        {
            "candidate_key": "preconfirm_watchlist",
            "candidate_family": "preconfirm_watchlist",
            "walk_forward_progress": {"status": "complete", "required_days": 20, "days": 21},
            "comparison_vs_frozen_cpb": {
                "status": "compared",
                "baseline_label": "active_cpb_persisted_picks",
                "candidate_days": 21,
            },
            "paper_observation_gate": {
                "status": "blocked",
                "allowed": False,
                "artifact_only": True,
                "blockers": ["paper_observation_not_authorized", "operator_review_required"],
            },
            "strategy_version_gate": {
                "status": "blocked",
                "allowed": False,
                "artifact_only": True,
                "blockers": ["strategy_version_proposal_not_authorized", "proposal_review_required"],
            },
            "status": "blocked",
        },
    ]
    monitor = {
        "generated_at": "2026-05-12T00:00:00+00:00",
        "review_date": "20260512",
        "prior_review_date": "20260511",
        "next_trade_date": "20260513",
        "methodology": {"status": "research_only", "active_strategy_mutated": False},
        "prior_candidate_count": 9,
        "today_candidate_count": 11,
        "today_bucket_counts": {"trend_extension_shadow": 6, "preconfirm_watchlist": 5},
        "walk_forward_progress": {
            "status": "partial",
            "required_days": 20,
            "evaluable_signal_days": 12,
            "summary": [{"candidate_key": "trend_extension_shadow", "status": "partial", "days": 12}],
        },
        "frozen_cpb_baseline": {
            "status": "available",
            "metrics": {"label": "active_cpb_persisted_picks", "n": 2},
        },
        "active_cpb_integrity": {
            "blockers": [],
            "safety": {
                "active_params_mutated": False,
                "writes_trade_state": False,
                "timer_mutated": False,
            },
        },
        "candidate_monitors": [
            {
                "candidate_key": "trend_extension_shadow",
                "candidate_family": "shadow_bucket",
                "today_candidate_count": 6,
                "today_top": {"ts_code": "000001.SZ", "name": "Top A"},
                "walk_forward_progress": candidate_gates[0]["walk_forward_progress"],
                "comparison_vs_frozen_cpb": candidate_gates[0]["comparison_vs_frozen_cpb"],
                "promotion_gates": {
                    "paper_observation_gate": candidate_gates[0]["paper_observation_gate"],
                    "strategy_version_gate": candidate_gates[0]["strategy_version_gate"],
                },
            },
            {
                "candidate_key": "preconfirm_watchlist",
                "candidate_family": "preconfirm_watchlist",
                "today_candidate_count": 5,
                "walk_forward_progress": candidate_gates[1]["walk_forward_progress"],
                "comparison_vs_frozen_cpb": candidate_gates[1]["comparison_vs_frozen_cpb"],
                "promotion_gates": {
                    "paper_observation_gate": candidate_gates[1]["paper_observation_gate"],
                    "strategy_version_gate": candidate_gates[1]["strategy_version_gate"],
                },
            },
        ],
    }
    preflight = {
        "artifact_type": "shadow_strategy_promotion_preflight",
        "generated_at": "2026-05-12T00:00:01+00:00",
        "review_date": "20260512",
        "next_trade_date": "20260513",
        "status": "blocked",
        "required_walk_forward_days": 20,
        "candidate_count": 2,
        "candidate_gates": candidate_gates,
        "blockers": [
            "operator_review_required",
            "paper_observation_not_authorized",
            "strategy_version_proposal_not_authorized",
        ],
        "blocker_counts": {
            "operator_review_required": 2,
            "paper_observation_not_authorized": 2,
            "strategy_version_proposal_not_authorized": 2,
        },
        "frozen_cpb_baseline": monitor["frozen_cpb_baseline"],
        "active_cpb_integrity": monitor["active_cpb_integrity"],
        "safety": {
            "active_params_mutated": False,
            "writes_trade_state": False,
            "artifact_only": True,
            "promotion_allowed": False,
            "paper_observation_allowed": False,
        },
    }
    (reports_dir / "strategy_shadow_monitor_20260512.json").write_text(json.dumps(monitor), encoding="utf-8")
    (reports_dir / "strategy_shadow_monitor_20260512.md").write_text("# monitor\n", encoding="utf-8")
    (reports_dir / "strategy_shadow_promotion_preflight_20260512.json").write_text(
        json.dumps(preflight),
        encoding="utf-8",
    )
    (reports_dir / "strategy_shadow_promotion_preflight_20260512.md").write_text("# preflight\n", encoding="utf-8")


def _hypothesis_count(db_path: Path) -> int:
    with connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM strategy_hypotheses").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
