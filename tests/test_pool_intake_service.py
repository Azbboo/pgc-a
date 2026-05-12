from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pgc_trading.services.common import RequestContext
from pgc_trading.services.pool_intake_service import PoolIntakeRequest, PoolIntakeService


class PoolIntakeServiceTest(unittest.TestCase):
    def test_dry_run_reports_added_duplicate_and_invalid_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_existing_files(Path(tmp))
            source = Path(tmp) / "intake.json"
            self._write_json(
                source,
                {
                    "review_date": "2026-05-12",
                    "source": "operator_screenshot",
                    "reason": "reviewed pool event",
                    "rows": [
                        {
                            "code": "000002",
                            "name": "New Candidate",
                            "entry_time": "09:31",
                            "entry_price": 12.34,
                            "sector": "software",
                            "theme": "ai",
                        },
                        {
                            "ts_code": "000001.SZ",
                            "name": "Existing Candidate",
                            "entry_time": "09:30",
                            "entry_price": 10.0,
                        },
                        {
                            "code": "12",
                            "name": "Broken Candidate",
                            "entry_time": "09:32",
                            "entry_price": 8.0,
                        },
                    ],
                },
            )
            before_pool = paths["pool"].read_text(encoding="utf-8")
            before_raw = paths["raw"].read_text(encoding="utf-8")

            result = PoolIntakeService().validate_and_apply(
                PoolIntakeRequest(source_file=source, pool_file=paths["pool"], raw_events_file=paths["raw"]),
                RequestContext(request_id="req-dry", dry_run=True, operator="tester"),
            )

            self.assertEqual(result.status, "validation_failed")
            self.assertEqual(result.data.input_count, 3)
            self.assertEqual(result.data.added_count, 1)
            self.assertEqual(result.data.duplicate_count, 1)
            self.assertEqual(result.data.invalid_count, 1)
            self.assertEqual(result.data.rows[0].status, "would_insert")
            self.assertEqual(result.data.rows[1].status, "duplicate")
            self.assertIn("stock code", result.data.invalid_entries[0].reasons[0])
            self.assertEqual(paths["pool"].read_text(encoding="utf-8"), before_pool)
            self.assertEqual(paths["raw"].read_text(encoding="utf-8"), before_raw)

    def test_apply_appends_pool_and_raw_rows_preserving_existing_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_existing_files(Path(tmp))
            source = Path(tmp) / "intake.json"
            self._write_json(
                source,
                [
                    {
                        "ts_code": "000002.SZ",
                        "name": "New Candidate",
                        "entry_date": "20260512",
                        "entry_time": "10:05",
                        "entry_price": 12.34,
                        "source": "operator_screenshot",
                        "reason": "reviewed pool event",
                        "sector": "software",
                        "theme": "ai",
                    }
                ],
            )

            result = PoolIntakeService().validate_and_apply(
                PoolIntakeRequest(source_file=source, pool_file=paths["pool"], raw_events_file=paths["raw"]),
                RequestContext(request_id="req-apply", dry_run=False, operator="tester"),
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(result.data.added_count, 1)
            pool_rows = json.loads(paths["pool"].read_text(encoding="utf-8"))
            raw_rows = json.loads(paths["raw"].read_text(encoding="utf-8"))
            self.assertEqual(len(pool_rows), 2)
            self.assertEqual(len(raw_rows), 2)
            self.assertEqual(list(pool_rows[1].keys()), list(pool_rows[0].keys()))
            self.assertEqual(list(raw_rows[1].keys()), list(raw_rows[0].keys()))
            self.assertEqual(pool_rows[1]["ts_code"], "000002.SZ")
            self.assertEqual(pool_rows[1]["industry"], "software")
            self.assertEqual(pool_rows[1]["source_sheet"], "operator_screenshot")
            self.assertIsNone(pool_rows[1]["bull_reason"])
            self.assertNotIn("reason", pool_rows[1])
            self.assertEqual(raw_rows[1]["event_id"], 2)
            self.assertEqual(raw_rows[1]["entry_month"], "202605")
            self.assertEqual(raw_rows[1]["entry_weekday"], "Tue")
            self.assertEqual(raw_rows[1]["price_bucket"], "10-20")

    def test_apply_requires_operator_before_file_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_existing_files(Path(tmp))
            source = Path(tmp) / "intake.json"
            self._write_json(
                source,
                [
                    {
                        "code": "000002",
                        "name": "New Candidate",
                        "entry_date": "20260512",
                        "entry_price": 12.34,
                        "source": "operator_screenshot",
                        "reason": "reviewed pool event",
                    }
                ],
            )
            before_pool = paths["pool"].read_text(encoding="utf-8")

            result = PoolIntakeService().validate_and_apply(
                PoolIntakeRequest(source_file=source, pool_file=paths["pool"], raw_events_file=paths["raw"]),
                RequestContext(request_id="req-operator", dry_run=False, operator=None),
            )

            self.assertEqual(result.status, "validation_failed")
            self.assertEqual(result.errors[0].code, "OPERATOR_REQUIRED")
            self.assertEqual(paths["pool"].read_text(encoding="utf-8"), before_pool)

    def test_output_file_cannot_overwrite_pool_or_raw_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_existing_files(Path(tmp))
            source = Path(tmp) / "intake.json"
            self._write_json(source, [])

            result = PoolIntakeService().validate_and_apply(
                PoolIntakeRequest(
                    source_file=source,
                    pool_file=paths["pool"],
                    raw_events_file=paths["raw"],
                    output_file=paths["pool"],
                ),
                RequestContext(request_id="req-output", dry_run=True, operator="tester"),
            )

            self.assertEqual(result.status, "validation_failed")
            self.assertEqual(result.errors[0].code, "VALIDATION_ERROR")
            self.assertIn("output_file must not overwrite pool_file", result.errors[0].message)

    def _write_existing_files(self, tmp: Path) -> dict[str, Path]:
        pool = tmp / "pgc_pool.json"
        raw = tmp / "pgc_raw_events.json"
        self._write_json(
            pool,
            [
                {
                    "ts_code": "000001.SZ",
                    "code": "000001",
                    "name": "Existing Candidate",
                    "entry_date": "20260512",
                    "entry_time": "09:30",
                    "entry_price": 10.0,
                    "pnl3_reported": None,
                    "status": "watching",
                    "days_since": 0,
                    "latest_close": None,
                    "latest_ret": None,
                    "max_high": 0,
                    "max_high_date": "20260512",
                    "current_drawdown": 0,
                    "max_3d": 0,
                    "industry": "",
                    "strategy": "operator_screenshot",
                    "source_sheet": "operator_screenshot",
                    "bull_prob": 0,
                    "bull_reason": None,
                }
            ],
        )
        self._write_json(
            raw,
            [
                {
                    "event_id": 1,
                    "ts_code": "000001.SZ",
                    "code": "000001",
                    "name": "Existing Candidate",
                    "entry_date": "20260512",
                    "entry_time": "09:30",
                    "entry_price": 10.0,
                    "entry_month": "202605",
                    "entry_weekday": "Tue",
                    "price_bucket": "10-20",
                }
            ],
        )
        return {"pool": pool, "raw": raw}

    def _write_json(self, path: Path, payload: object) -> None:
        path.write_text(f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
