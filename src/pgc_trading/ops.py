"""Repeatable deployment and operations helpers for PGC."""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pgc_trading import __version__
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.migrators.backup import backup_database


API_VERSION = __version__
RELEASE_TAG_PREFIX = "pgc"


@dataclass(frozen=True)
class HttpHealthResult:
    url: str
    ok: bool
    status_code: int | None = None
    payload: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "ok": self.ok,
            "status_code": self.status_code,
            "payload": self.payload,
            "error": self.error,
        }


@dataclass(frozen=True)
class OpsHealthResult:
    db_path: Path
    database_exists: bool
    status: str
    package_version: str = __version__
    api_version: str = API_VERSION
    latest_migration: str | None = None
    applied_migrations: list[str] = field(default_factory=list)
    pending_migrations: list[str] = field(default_factory=list)
    api_health: HttpHealthResult | None = None
    database_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "db_path": str(self.db_path),
            "database_exists": self.database_exists,
            "status": self.status,
            "package_version": self.package_version,
            "api_version": self.api_version,
            "latest_migration": self.latest_migration,
            "applied_migrations": self.applied_migrations,
            "pending_migrations": self.pending_migrations,
            "api_health": self.api_health.to_dict() if self.api_health is not None else None,
            "database_error": self.database_error,
        }


@dataclass(frozen=True)
class OpsMigrationResult:
    db_path: Path
    backup_path: Path | None
    applied: list[str]
    skipped: list[str]
    dry_run: bool

    @property
    def changed(self) -> bool:
        return bool(self.applied)

    def to_dict(self) -> dict[str, Any]:
        return {
            "db_path": str(self.db_path),
            "backup_path": str(self.backup_path) if self.backup_path is not None else None,
            "applied": self.applied,
            "skipped": self.skipped,
            "dry_run": self.dry_run,
            "changed": self.changed,
        }


def build_release_tag(
    *,
    version: str = __version__,
    date: str | None = None,
    git_sha: str | None = None,
) -> str:
    """Build the standard M20 release tag."""

    date_part = _normalize_release_date(date)
    tag = f"{RELEASE_TAG_PREFIX}-v{version}-{date_part}"
    short_sha = _short_git_sha(git_sha)
    if short_sha is not None:
        tag = f"{tag}-g{short_sha}"
    return tag


def run_ops_migration_step(
    db_path: Path,
    *,
    dry_run: bool = False,
    backup: bool = False,
    backup_dir: Path | None = None,
    backup_label: str = "before_ops_migrate",
) -> OpsMigrationResult:
    """Run the standard migration step with an optional pre-migration backup."""

    path = Path(db_path)
    backup_path = None
    if backup and not dry_run and path.exists():
        backup_path = backup_database(path, backup_dir=backup_dir, label=backup_label)

    result = run_migrations(path, dry_run=dry_run)
    return OpsMigrationResult(
        db_path=result.db_path,
        backup_path=backup_path,
        applied=result.applied,
        skipped=result.skipped,
        dry_run=result.dry_run,
    )


def run_ops_health_check(
    db_path: Path,
    *,
    health_url: str | None = None,
    timeout_seconds: float = 2.0,
) -> OpsHealthResult:
    """Inspect local database migration state and optionally an API health URL."""

    path = Path(db_path)
    database_exists = path.exists()
    applied: list[str] = []
    latest: str | None = None
    database_error: str | None = None

    if database_exists:
        try:
            applied = _read_applied_migrations(path)
            latest = applied[-1] if applied else None
        except sqlite3.Error as exc:
            database_error = str(exc)

    pending: list[str] = []
    if database_error is None:
        try:
            pending = _pending_migrations(path)
        except sqlite3.Error as exc:
            database_error = str(exc)
    api_health = _check_http_health(health_url, timeout_seconds) if health_url else None
    status = _ops_health_status(
        database_exists=database_exists,
        database_error=database_error,
        pending_migrations=pending,
        api_health=api_health,
    )

    return OpsHealthResult(
        db_path=path,
        database_exists=database_exists,
        status=status,
        latest_migration=latest,
        applied_migrations=applied,
        pending_migrations=pending,
        api_health=api_health,
        database_error=database_error,
    )


def _read_applied_migrations(db_path: Path) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
        if exists is None:
            return []
        rows = conn.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
    return [f"{row[0]}_{row[1]}" for row in rows]


def _pending_migrations(db_path: Path) -> list[str]:
    result = run_migrations(db_path, dry_run=True)
    return result.applied


def _check_http_health(url: str, timeout_seconds: float) -> HttpHealthResult:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(response.status)
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return HttpHealthResult(url=url, ok=False, status_code=exc.code, error=str(exc))
    except urllib.error.URLError as exc:
        return HttpHealthResult(url=url, ok=False, error=str(exc.reason))
    except TimeoutError as exc:
        return HttpHealthResult(url=url, ok=False, error=str(exc))

    payload: dict[str, Any] | None = None
    if body.strip():
        try:
            decoded = json.loads(body)
            payload = decoded if isinstance(decoded, dict) else {"body": decoded}
        except json.JSONDecodeError:
            payload = {"body": body}
    ok = status_code == 200 and (payload is None or payload.get("status") == "ok")
    return HttpHealthResult(url=url, ok=ok, status_code=status_code, payload=payload)


def _ops_health_status(
    *,
    database_exists: bool,
    database_error: str | None,
    pending_migrations: list[str],
    api_health: HttpHealthResult | None,
) -> str:
    if not database_exists:
        return "missing_database"
    if database_error is not None:
        return "database_unreadable"
    if api_health is not None and not api_health.ok:
        return "api_unhealthy"
    if pending_migrations:
        return "pending_migrations"
    return "ok"


def _normalize_release_date(value: str | None) -> str:
    if value is None:
        return datetime.now().strftime("%Y%m%d")
    if len(value) == 8 and value.isdigit():
        datetime.strptime(value, "%Y%m%d")
        return value
    parsed = datetime.strptime(value, "%Y-%m-%d")
    return parsed.strftime("%Y%m%d")


def _short_git_sha(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:7]
