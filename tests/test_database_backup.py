from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pgc_trading.storage.migrators.backup import backup_database


class DatabaseBackupTest(unittest.TestCase):
    def test_existing_database_is_copied_to_default_backup_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            db_path.write_bytes(b"sqlite payload")

            backup_path = backup_database(db_path, label="unit_test")

            self.assertEqual(backup_path.parent, db_path.parent / "backups")
            self.assertIn("unit_test", backup_path.name)
            self.assertEqual(backup_path.read_bytes(), b"sqlite payload")
            self.assertEqual(db_path.read_bytes(), b"sqlite payload")

    def test_custom_backup_dir_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            backup_dir = Path(tmp) / "custom_backups"
            db_path.write_text("payload", encoding="utf-8")

            backup_path = backup_database(db_path, backup_dir=backup_dir)

            self.assertEqual(backup_path.parent, backup_dir)
            self.assertTrue(backup_path.exists())

    def test_missing_source_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"

            with self.assertRaisesRegex(FileNotFoundError, "Source database does not exist"):
                backup_database(db_path)

            self.assertFalse((Path(tmp) / "backups").exists())

    def test_existing_destination_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            backup_dir = Path(tmp) / "backups"
            db_path.write_text("source", encoding="utf-8")

            first = backup_database(db_path, backup_dir=backup_dir, label="same_label")
            second = backup_database(db_path, backup_dir=backup_dir, label="same_label")

            self.assertNotEqual(first, second)
            self.assertEqual(first.read_text(encoding="utf-8"), "source")
            self.assertEqual(second.read_text(encoding="utf-8"), "source")


if __name__ == "__main__":
    unittest.main()
