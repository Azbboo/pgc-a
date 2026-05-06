from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.storage.database import SCHEMA_PATH
from pgc_trading.storage.migrators.legacy_detector import (
    SchemaState,
    detect_database_state,
    detect_schema_state,
    inspect_schema,
)


class LegacyDetectorTest(unittest.TestCase):
    def test_empty_temp_database_returns_empty(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            self.assertEqual(detect_schema_state(conn), SchemaState.EMPTY)

    def test_current_schema_returns_legacy(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            detection = inspect_schema(conn)

        self.assertEqual(detection.state, SchemaState.LEGACY)
        self.assertIn("signals_table", detection.legacy_markers)
        self.assertFalse(detection.target_markers)

    def test_target_marker_tables_return_target(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.executescript(
                """
                CREATE TABLE raw_events (
                  id INTEGER PRIMARY KEY,
                  import_batch_id INTEGER NOT NULL
                );
                CREATE TABLE market_bars (
                  ts_code TEXT NOT NULL,
                  fetch_run_id INTEGER NOT NULL
                );
                CREATE TABLE strategy_signals (
                  id INTEGER PRIMARY KEY
                );
                CREATE TABLE exit_decisions (
                  id INTEGER PRIMARY KEY
                );
                """
            )
            detection = inspect_schema(conn)

        self.assertEqual(detection.state, SchemaState.TARGET)
        self.assertFalse(detection.legacy_markers)
        self.assertIn("strategy_signals_table", detection.target_markers)

    def test_legacy_and_target_markers_return_mixed(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.executescript(
                """
                CREATE TABLE signals (
                  id INTEGER PRIMARY KEY
                );
                CREATE TABLE strategy_signals (
                  id INTEGER PRIMARY KEY
                );
                """
            )

            detection = inspect_schema(conn)

        self.assertEqual(detection.state, SchemaState.MIXED)
        self.assertIn("signals_table", detection.legacy_markers)
        self.assertIn("strategy_signals_table", detection.target_markers)

    def test_missing_database_path_does_not_create_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            detection = detect_database_state(db_path)

            self.assertEqual(detection.state, SchemaState.EMPTY)
            self.assertFalse(db_path.exists())


if __name__ == "__main__":
    unittest.main()
