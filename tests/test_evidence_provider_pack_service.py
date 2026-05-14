from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.agent_external_data_service import build_agent_external_source_hash
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
            self.assertIn("qa_summary", result.data.manifest)
            self.assertEqual(result.data.qa_summary, result.data.manifest["qa_summary"])
            self.assertFalse(result.data.qa_summary["safety"]["live_fetches"])

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
            self.assertEqual(manifest["qa_summary"], result.data.qa_summary)

    def test_qa_summary_surfaces_closed_remaining_and_review_provider_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_trading.db"
            run_migrations(db_path)
            market_file = Path(tmp) / "market_external_20260508.json"
            market_file.write_text(
                json.dumps(
                    {
                        "provider_file_contract": "market_external_v1",
                        "as_of_date": "20260508",
                        "provider": "manual_reviewed_cache",
                        "items": [
                            self._market_record(
                                provider="manual_reviewed_cache",
                                scope_type="market",
                                scope_key="A_SHARE",
                                item_type="policy",
                                sentiment="neutral",
                            )
                        ],
                        "unavailable_sources": [
                            {
                                "scope_type": "sector",
                                "provider": "sector_cache",
                                "reason": "provider_file_absent",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            stale_agent_record = self._agent_record(
                published_date="20260507",
                item_type="announcement",
                title="历史公告摘要",
                summary="上一交易日公告摘要，复盘日需要更新。",
                sentiment="unknown",
            )
            agent_file = Path(tmp) / "agent_external_20260508.json"
            agent_file.write_text(
                json.dumps(
                    {
                        "provider_file_contract": "agent_external_v1",
                        "as_of_date": "20260508",
                        "provider": "manual_reviewed_cache",
                        "records": [stale_agent_record, stale_agent_record],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = EvidenceProviderPackService(db_path).build_provider_pack(
                BuildEvidenceProviderPackRequest(
                    market_source_files=[market_file],
                    agent_source_files=[agent_file],
                    output_dir=Path(tmp) / "evidence_pack",
                ),
                RequestContext(request_id="test-evidence-pack-qa", dry_run=True, operator="tester"),
            )

            self.assertTrue(result.ok)
            qa = result.data.qa_summary
            self.assertEqual(qa["status"], "needs_review")
            self.assertFalse(qa["safety"]["live_fetches"])
            self.assertIn(
                ("market_external", "sector", "unavailable"),
                {(gap["kind"], gap["section"], gap["state"]) for gap in qa["closed_gaps"]},
            )
            remaining = {(gap["kind"], gap["section"], gap["state"]) for gap in qa["remaining_gaps"]}
            self.assertIn(("market_external", "stock", "missing"), remaining)
            self.assertIn(("agent_external", "fundamental", "missing"), remaining)
            self.assertIn(("agent_external", "news", "missing"), remaining)
            self.assertIn(("agent_external", "sentiment", "missing"), remaining)
            self.assertIn(("agent_external", "freshness", "stale"), remaining)
            self.assertIn(("agent_external", "duplicates", "duplicate"), remaining)
            needed_sections = {(item["kind"], item["section"]) for item in qa["provider_files_needed"]}
            self.assertIn(("market_external", "stock"), needed_sections)
            self.assertIn(("agent_external", "news"), needed_sections)
            review_files = {Path(item["source_file"]).name for item in qa["provider_files_needing_review"]}
            self.assertIn(agent_file.name, review_files)

    def test_qa_summary_surfaces_date_provider_and_source_hash_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc_trading.db"
            run_migrations(db_path)
            output_dir = Path(tmp) / "evidence_pack"
            source_file = Path(tmp) / "bad_market_external.json"
            missing_provider_record = {
                "as_of_date": "20260508",
                "scope_type": "market",
                "scope_key": "A_SHARE",
                "item_type": "news",
                "published_date": "20260508",
                "source_hash": "bad-hash",
                "title": "缺少 provider 的摘要",
                "summary": "这条记录必须被人工复核。",
                "sentiment": "neutral",
                "importance": "medium",
                "metadata": {},
            }
            source_file.write_text(
                json.dumps(
                    {
                        "provider_file_contract": "market_external_v1",
                        "as_of_date": "20260508",
                        "items": [
                            self._market_record(
                                as_of_date="20260507",
                                source_hash="bad-hash",
                                title="日期与哈希不匹配摘要",
                                summary="这条记录的日期和 source_hash 均不应通过。",
                            ),
                            missing_provider_record,
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = EvidenceProviderPackService(db_path).build_provider_pack(
                BuildEvidenceProviderPackRequest(market_source_files=[source_file], output_dir=output_dir),
                RequestContext(request_id="test-evidence-pack-invalid", dry_run=False, operator="tester"),
            )

            self.assertEqual(result.status, "validation_failed")
            self.assertFalse(output_dir.exists())
            self.assertGreater(result.data.qa_summary["remaining_gap_count"], 0)
            self.assertEqual(result.data.qa_summary["status"], "needs_review")
            error_codes = {error.code for error in result.errors}
            self.assertIn("AS_OF_DATE_MISMATCH", error_codes)
            self.assertIn("SOURCE_HASH_MISMATCH", error_codes)
            self.assertIn("REQUIRED_FIELD", error_codes)
            gap_reasons = {gap.get("reason") for gap in result.data.qa_summary["remaining_gaps"]}
            self.assertIn("AS_OF_DATE_MISMATCH", gap_reasons)
            self.assertIn("SOURCE_HASH_MISMATCH", gap_reasons)
            review_files = {Path(item["source_file"]).name for item in result.data.qa_summary["provider_files_needing_review"]}
            self.assertEqual(review_files, {source_file.name})

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

    def _market_record(self, **overrides: object) -> dict[str, object]:
        record: dict[str, object] = {
            "as_of_date": "20260508",
            "scope_type": "market",
            "scope_key": "A_SHARE",
            "item_type": "news",
            "provider": "manual_fixture",
            "published_date": "20260508",
            "title": "A股市场摘要",
            "summary": "人工审核的全市场外部证据摘要。",
            "sentiment": "neutral",
            "importance": "medium",
            "metadata": {},
        }
        record.update(overrides)
        if "source_hash" not in overrides:
            record["source_hash"] = build_market_external_source_hash(
                provider=str(record["provider"]),
                scope_type=str(record["scope_type"]),
                scope_key=str(record["scope_key"]),
                published_date=str(record["published_date"]),
                title=str(record["title"]),
                summary=str(record["summary"]),
            )
        return record

    def _agent_record(self, **overrides: object) -> dict[str, object]:
        record: dict[str, object] = {
            "ts_code": "000001.SZ",
            "published_date": "20260508",
            "item_type": "announcement",
            "provider": "manual_fixture",
            "title": "盘后公告摘要",
            "summary": "公告摘要未发现重大利空。",
            "sentiment": "neutral",
            "importance": "medium",
            "metadata": {},
        }
        record.update(overrides)
        if "source_hash" not in overrides:
            record["source_hash"] = build_agent_external_source_hash(
                provider=str(record["provider"]),
                item_type=str(record["item_type"]),
                ts_code=str(record["ts_code"]),
                published_date=str(record["published_date"]),
                title=str(record["title"]),
                summary=str(record["summary"]),
            )
        return record


if __name__ == "__main__":
    unittest.main()
