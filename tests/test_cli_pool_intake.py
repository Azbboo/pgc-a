from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from pgc_trading.cli.main import main


class CliPoolIntakeTest(unittest.TestCase):
    def test_ops_pool_intake_dry_run_writes_summary_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pool = root / "pgc_pool.json"
            raw = root / "pgc_raw_events.json"
            source = root / "intake.json"
            output = root / "summary.json"
            self._write_json(pool, [])
            self._write_json(raw, [])
            self._write_json(
                source,
                [
                    {
                        "code": "000002",
                        "name": "New Candidate",
                        "entry_date": "20260512",
                        "entry_time": "10:05",
                        "entry_price": 12.34,
                        "source": "operator_screenshot",
                        "reason": "reviewed pool event",
                    }
                ],
            )
            stdout = io.StringIO()

            code = main(
                [
                    "ops",
                    "pool-intake",
                    "--file",
                    str(source),
                    "--pool-file",
                    str(pool),
                    "--raw-events-file",
                    str(raw),
                    "--output",
                    str(output),
                    "--dry-run",
                ],
                stdout=stdout,
            )

            self.assertEqual(code, 0, stdout.getvalue())
            self.assertIn("pool_intake_status=success", stdout.getvalue())
            self.assertIn("added_count=1", stdout.getvalue())
            summary = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(summary["mode"], "dry_run")
            self.assertEqual(summary["added_count"], 1)
            self.assertEqual(json.loads(pool.read_text(encoding="utf-8")), [])
            self.assertEqual(json.loads(raw.read_text(encoding="utf-8")), [])

    def _write_json(self, path: Path, payload: object) -> None:
        path.write_text(f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
