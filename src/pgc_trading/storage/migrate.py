"""SQLite migration runner for the PGC trading store."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from pgc_trading.config import Paths


MIGRATIONS_DIR = Path(__file__).with_name("migrations")
MIGRATION_RE = re.compile(r"^(?P<version>\d{3})_(?P<name>[a-z0-9_]+)\.sql$")


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path

    @property
    def label(self) -> str:
        return f"{self.version}_{self.name}"


@dataclass(frozen=True)
class MigrationResult:
    db_path: Path
    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.applied)

    def to_dict(self) -> dict:
        return {
            "db_path": str(self.db_path),
            "applied": self.applied,
            "skipped": self.skipped,
            "dry_run": self.dry_run,
            "changed": self.changed,
        }


class MigrationError(RuntimeError):
    """Raised when a migration file is invalid or fails to apply."""


def parse_migration(path: Path) -> Migration:
    match = MIGRATION_RE.match(path.name)
    if not match:
        raise MigrationError(f"Invalid migration filename: {path.name}")
    return Migration(version=match.group("version"), name=match.group("name"), path=path)


def discover_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[Migration]:
    if not migrations_dir.exists():
        return []
    migrations = [parse_migration(path) for path in sorted(migrations_dir.glob("*.sql"))]
    seen: set[str] = set()
    for migration in migrations:
        if migration.version in seen:
            raise MigrationError(f"Duplicate migration version: {migration.version}")
        seen.add(migration.version)
    return migrations


def bootstrap_schema_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def applied_versions(conn: sqlite3.Connection) -> set[str]:
    if not table_exists(conn, "schema_migrations"):
        return set()
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {str(row["version"]) for row in rows}


def _apply_migration(conn: sqlite3.Connection, migration: Migration) -> None:
    sql = migration.path.read_text(encoding="utf-8")
    try:
        conn.executescript("BEGIN;\n" + sql)
        conn.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (migration.version, migration.name),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise MigrationError(f"Failed to apply migration {migration.label}: {exc}") from exc


def connect_for_migration(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def run_migrations(
    db_path: Path | None = None,
    migrations_dir: Path = MIGRATIONS_DIR,
    dry_run: bool = False,
) -> MigrationResult:
    path = db_path or Paths().db_path
    migrations = discover_migrations(migrations_dir)

    if dry_run:
        applied: set[str] = set()
        if path.exists():
            with connect_for_migration(path) as conn:
                applied = applied_versions(conn)
        pending = [migration for migration in migrations if migration.version not in applied]
        return MigrationResult(
            db_path=path,
            applied=[migration.label for migration in pending],
            skipped=[migration.label for migration in migrations if migration.version in applied],
            dry_run=True,
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with connect_for_migration(path) as conn:
        bootstrap_schema_migrations(conn)
        applied = applied_versions(conn)
        pending = [migration for migration in migrations if migration.version not in applied]

        applied_labels: list[str] = []
        for migration in pending:
            _apply_migration(conn, migration)
            applied_labels.append(migration.label)

        return MigrationResult(
            db_path=path,
            applied=applied_labels,
            skipped=[migration.label for migration in migrations if migration.version in applied],
            dry_run=False,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run PGC SQLite migrations.")
    parser.add_argument("--db-path", type=Path, default=Paths().db_path)
    parser.add_argument("--migrations-dir", type=Path, default=MIGRATIONS_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    result = run_migrations(args.db_path, args.migrations_dir, dry_run=args.dry_run)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
