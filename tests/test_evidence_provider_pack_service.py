from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.evidence_provider_pack_service import (
    BuildEvidenceProviderPackRequest,
    EvidenceProviderPackService,
)
from pgc_trading.services.evidence_coverage_ledger_service import (
    BuildEvidenceCoverageLedgerRequest,
    EvidenceCoverageLedgerService,
)
from pgc_trading.services.market_external_data_service import (
    ImportMarketExternalDataRequest,
    MarketExternalDataService,
    build_market_external_source_hash,
)
from pgc_trading.storage.migrate import run_migrations


class EvidenceProviderPackServiceTest(unittest.TestCase):
    def test_dry_run_builds_manifest_without_writing_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_trading.db"
            run_migrations(db_path)
            output_dir = Path(tmp) / "evidence_pack"
            market_file = Path(__file__).parent / "fixtures" / "market_review" / "external_items_20260508.json"
            agent_file = Path(__file__).parent / "fixtures" / "agent_external" / "20260508_301188.json"

            result = EvidenceProviderPackService(db_path).build_provider_pack(
                BuildEvidenceProviderPackRequest(
                    market_source_files=[market_file],
                    agent_source_files=[agent_file],
                    output_dir=output_dir,
                ),
                RequestContext(request_id="test-evidence-pack-preview", dry_run=True, operator="tester"),
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.data.pack_contract, "evidence_provider_pack_v1")
            self.assertFalse(result.data.apply)
            self.assertEqual(result.data.output_dir, str(output_dir))
            self.assertIsNone(result.data.manifest_path)
            self.assertEqual(result.data.copied_files, [])
            self.assertEqual(result.data.source_file_count, 2)
            self.assertEqual(result.data.manifest["provider_file_contracts"], ["market_external_v1", "agent_external_v1"])
            self.assertEqual([group["kind"] for group in result.data.manifest["groups"]], ["market_external", "agent_external"])
            self.assertFalse(output_dir.exists())
            self.assertFalse(result.data.manifest["groups"][0]["date_results"][0]["source_files"][0]["written"])
            self.assertEqual(
                result.data.manifest["groups"][0]["date_results"][0]["source_files"][0]["source_file_sha256"],
                self._sha256(market_file),
            )

    def test_apply_writes_manifest_and_copies_reviewed_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_trading.db"
            run_migrations(db_path)
            output_dir = Path(tmp) / "evidence_pack"
            market_file = Path(__file__).parent / "fixtures" / "market_review" / "external_items_20260508.json"
            agent_file = Path(__file__).parent / "fixtures" / "agent_external" / "20260508_301188.json"

            result = EvidenceProviderPackService(db_path).build_provider_pack(
                BuildEvidenceProviderPackRequest(
                    market_source_files=[market_file],
                    agent_source_files=[agent_file],
                    output_dir=output_dir,
                ),
                RequestContext(request_id="test-evidence-pack-apply", dry_run=False, operator="tester"),
            )

            self.assertTrue(result.ok)
            self.assertTrue(result.data.apply)
            self.assertEqual(result.data.manifest_path, str(output_dir / "manifest.json"))
            self.assertEqual(len(result.data.copied_files), 2)
            self.assertTrue((output_dir / "manifest.json").exists())
            market_output = output_dir / "market_external" / f"20260508__01__{market_file.name}"
            agent_output = output_dir / "agent_external" / f"20260508__01__{agent_file.name}"
            self.assertEqual(result.data.copied_files, [str(market_output), str(agent_output)])
            self.assertEqual(market_output.read_text(encoding="utf-8"), market_file.read_text(encoding="utf-8"))
            self.assertEqual(agent_output.read_text(encoding="utf-8"), agent_file.read_text(encoding="utf-8"))

            manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["pack_contract"], "evidence_provider_pack_v1")
            self.assertEqual(manifest["provider_file_contracts"], ["market_external_v1", "agent_external_v1"])
            self.assertEqual(manifest["source_file_count"], 2)
            self.assertEqual(manifest["groups"][0]["date_results"][0]["source_files"][0]["output_file"], str(market_output))
            self.assertTrue(manifest["groups"][0]["date_results"][0]["source_files"][0]["written"])
            self.assertEqual(
                manifest["groups"][1]["date_results"][0]["source_files"][0]["source_file_sha256"],
                self._sha256(agent_file),
            )

    def test_rejects_missing_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_trading.db"
            run_migrations(db_path)

            result = EvidenceProviderPackService(db_path).build_provider_pack(
                BuildEvidenceProviderPackRequest(),
                RequestContext(request_id="test-evidence-pack-empty", dry_run=True, operator="tester"),
            )

            self.assertEqual(result.status, "validation_failed")
            self.assertEqual(result.errors[0].code, "VALIDATION_ERROR")
            self.assertIn("at least one market_source_file or agent_source_file is required", result.errors[0].message)

    def test_coverage_ledger_surfaces_provider_pack_source_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_trading.db"
            run_migrations(db_path)
            provider_dir = Path(tmp) / "providers"
            provider_dir.mkdir()
            source_hash = build_market_external_source_hash(
                provider="ledger_fixture",
                scope_type="market",
                scope_key="A_SHARE",
                published_date="20260507",
                title="stale market note",
                summary="Reviewed cache for stale state.",
            )
            stale_record = {
                "as_of_date": "20260508",
                "scope_type": "market",
                "scope_key": "A_SHARE",
                "item_type": "news",
                "provider": "ledger_fixture",
                "published_date": "20260507",
                "source_hash": source_hash,
                "title": "stale market note",
                "summary": "Reviewed cache for stale state.",
                "sentiment": "neutral",
                "importance": "medium",
                "metadata": {},
            }
            import_result = MarketExternalDataService(db_path).import_external_data(
                ImportMarketExternalDataRequest(as_of_date="20260508", records=[stale_record]),
                RequestContext(request_id="test-ledger-import-stale", dry_run=False, operator="tester"),
            )
            self.assertTrue(import_result.ok)

            stale_file = provider_dir / "market_stale_duplicate.json"
            stale_file.write_text(
                json.dumps(
                    {
                        "provider_file_contract": "market_external_v1",
                        "as_of_date": "20260508",
                        "provider": "ledger_fixture",
                        "items": [stale_record, stale_record],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            mismatch_record = {
                **stale_record,
                "source_hash": "bad-hash",
                "title": "hash mismatch note",
                "summary": "This provider row carries an invalid source hash.",
            }
            mismatch_file = provider_dir / "market_mismatch.json"
            mismatch_file.write_text(
                json.dumps(
                    {
                        "provider_file_contract": "market_external_v1",
                        "as_of_date": "20260508",
                        "provider": "ledger_fixture",
                        "items": [mismatch_record],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manifest = provider_dir / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "pack_contract": "evidence_provider_pack_v1",
                        "groups": [
                            {
                                "kind": "market_external",
                                "provider_file_contract": "market_external_v1",
                                "date_results": [
                                    {
                                        "as_of_date": "20260508",
                                        "source_files": [
                                            {
                                                "source_file": str(stale_file),
                                                "source_file_sha256": self._sha256(stale_file),
                                            },
                                            {
                                                "source_file": str(mismatch_file),
                                                "source_file_sha256": self._sha256(mismatch_file),
                                            },
                                        ],
                                        "coverage_summary": {
                                            "market": "partial",
                                            "sector": "missing",
                                            "stock": "missing",
                                            "sentiment": "unavailable",
                                            "news": "available",
                                            "duplicates": "duplicate",
                                            "freshness": {"market": "stale"},
                                        },
                                        "unavailable_sources": [
                                            {
                                                "scope_type": "market",
                                                "item_type": "sentiment",
                                                "provider": "reviewed_sentiment_cache",
                                                "reason": "provider_file_absent",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = EvidenceCoverageLedgerService(db_path).build_coverage_ledger(
                BuildEvidenceCoverageLedgerRequest(as_of_date="20260508", manifest_files=[manifest]),
                RequestContext(request_id="test-ledger", dry_run=True, operator="tester"),
            )

            self.assertTrue(result.ok)
            self.assertTrue(result.data.safety["read_only"])
            self.assertFalse(result.data.safety["live_fetches"])
            self.assertFalse(result.data.safety["writes_trade_state"])
            for state in ("stale", "duplicate", "source-hash-mismatch", "partial", "missing", "unavailable"):
                self.assertGreater(result.data.state_counts.get(state, 0), 0, state)
            provider_rows = [entry for entry in result.data.entries if entry["source_kind"] == "provider_pack_row"]
            self.assertEqual(
                sorted(entry["source_state"] for entry in provider_rows),
                ["duplicate", "source-hash-mismatch", "stale"],
            )

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        digest.update(path.read_bytes())
        return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
