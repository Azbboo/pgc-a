"""Repeatable deployment and operations helpers for PGC."""

from __future__ import annotations

import json
import hashlib
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
MARKET_REVIEW_PARITY_TABLES = [
    "market_review_runs",
    "sector_daily_snapshots",
    "market_external_items",
    "market_plan_contexts",
    "strategy_hypotheses",
]


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


@dataclass(frozen=True)
class MarketReviewParityTableResult:
    table: str
    local_count: int | None
    remote_count: int | None
    local_signature: str | None
    remote_signature: str | None
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "local_count": self.local_count,
            "remote_count": self.remote_count,
            "local_signature": self.local_signature,
            "remote_signature": self.remote_signature,
            "status": self.status,
        }


@dataclass(frozen=True)
class MarketReviewParityResult:
    as_of_date: str
    local_db_path: Path
    remote_db_path: Path
    status: str
    latest_local_date: str | None
    latest_remote_date: str | None
    tables: list[MarketReviewParityTableResult] = field(default_factory=list)
    local_error: str | None = None
    remote_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "match"

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date,
            "local_db_path": str(self.local_db_path),
            "remote_db_path": str(self.remote_db_path),
            "status": self.status,
            "latest_local_date": self.latest_local_date,
            "latest_remote_date": self.latest_remote_date,
            "tables": [table.to_dict() for table in self.tables],
            "local_error": self.local_error,
            "remote_error": self.remote_error,
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


def run_market_review_parity_check(
    local_db_path: Path,
    remote_db_path: Path,
    *,
    as_of_date: str,
) -> MarketReviewParityResult:
    """Compare local and remote market-review rows for one review date without writing."""

    local = _market_review_parity_snapshot(Path(local_db_path), as_of_date)
    remote = _market_review_parity_snapshot(Path(remote_db_path), as_of_date)
    table_results: list[MarketReviewParityTableResult] = []

    for table in MARKET_REVIEW_PARITY_TABLES:
        local_table = local["tables"].get(table, {})
        remote_table = remote["tables"].get(table, {})
        local_error = local_table.get("error")
        remote_error = remote_table.get("error")
        if local_error or remote_error:
            table_status = "unreadable"
        elif not local_table.get("exists") or not remote_table.get("exists"):
            table_status = "missing_table"
        elif (
            local_table.get("count") == remote_table.get("count")
            and local_table.get("signature") == remote_table.get("signature")
        ):
            table_status = "match"
        else:
            table_status = "mismatch"
        table_results.append(
            MarketReviewParityTableResult(
                table=table,
                local_count=local_table.get("count"),
                remote_count=remote_table.get("count"),
                local_signature=local_table.get("signature"),
                remote_signature=remote_table.get("signature"),
                status=table_status,
            )
        )

    if local.get("error") or remote.get("error"):
        status = "unreadable"
    elif all(table.status == "match" for table in table_results):
        status = "match"
    else:
        status = "mismatch"

    return MarketReviewParityResult(
        as_of_date=as_of_date,
        local_db_path=Path(local_db_path),
        remote_db_path=Path(remote_db_path),
        status=status,
        latest_local_date=local.get("latest_date"),
        latest_remote_date=remote.get("latest_date"),
        tables=table_results,
        local_error=local.get("error"),
        remote_error=remote.get("error"),
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


def _market_review_parity_snapshot(db_path: Path, as_of_date: str) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "latest_date": None,
            "tables": {table: {"exists": False, "count": None, "signature": None} for table in MARKET_REVIEW_PARITY_TABLES},
            "error": "database_not_found",
        }

    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            latest_date = _market_review_latest_date(conn)
            run_id = _market_review_run_id(conn, as_of_date)
            return {
                "latest_date": latest_date,
                "tables": {
                    table: _market_review_table_signature(conn, table, as_of_date, run_id)
                    for table in MARKET_REVIEW_PARITY_TABLES
                },
                "error": None,
            }
    except sqlite3.Error as exc:
        return {
            "latest_date": None,
            "tables": {table: {"exists": False, "count": None, "signature": None} for table in MARKET_REVIEW_PARITY_TABLES},
            "error": str(exc),
        }


def _market_review_latest_date(conn: sqlite3.Connection) -> str | None:
    if not _ops_table_exists(conn, "market_review_runs"):
        return None
    row = conn.execute("SELECT MAX(as_of_date) AS latest_date FROM market_review_runs").fetchone()
    return row["latest_date"] if row is not None else None


def _market_review_run_id(conn: sqlite3.Connection, as_of_date: str) -> int | None:
    if not _ops_table_exists(conn, "market_review_runs"):
        return None
    row = conn.execute(
        "SELECT id FROM market_review_runs WHERE as_of_date = ? ORDER BY id DESC LIMIT 1",
        (as_of_date,),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def _market_review_table_signature(
    conn: sqlite3.Connection,
    table: str,
    as_of_date: str,
    run_id: int | None,
) -> dict[str, Any]:
    if not _ops_table_exists(conn, table):
        return {"exists": False, "count": None, "signature": None}
    query, params = _market_review_signature_query(table, as_of_date, run_id)
    rows = conn.execute(query, params).fetchall()
    payload = [dict(row) for row in rows]
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return {
        "exists": True,
        "count": len(payload),
        "signature": hashlib.sha256(encoded).hexdigest()[:16],
    }


def _market_review_signature_query(table: str, as_of_date: str, run_id: int | None) -> tuple[str, tuple[Any, ...]]:
    if table == "market_review_runs":
        return (
            """
            SELECT as_of_date, status, provider_manifest_json, coverage_json, summary_json
            FROM market_review_runs
            WHERE as_of_date = ?
            ORDER BY as_of_date
            """,
            (as_of_date,),
        )
    if table == "sector_daily_snapshots":
        return (
            """
            SELECT as_of_date, sector_code, sector_name, provider, rank_overall, leader_count, metrics_json
            FROM sector_daily_snapshots
            WHERE market_review_run_id = ?
            ORDER BY sector_code
            """,
            (run_id,),
        )
    if table == "market_external_items":
        return (
            """
            SELECT as_of_date, scope_type, scope_key, item_type, provider, published_date,
                   sentiment, importance, source_hash
            FROM market_external_items
            WHERE as_of_date = ?
            ORDER BY scope_type, scope_key, item_type, provider, source_hash
            """,
            (as_of_date,),
        )
    if table == "market_plan_contexts":
        return (
            """
            SELECT trade_plan_id, alignment, risk_level, management_action, rationale, evidence_json
            FROM market_plan_contexts
            WHERE market_review_run_id = ?
            ORDER BY trade_plan_id
            """,
            (run_id,),
        )
    if table == "strategy_hypotheses":
        return (
            """
            SELECT as_of_date, hypothesis_type, title, rationale, evidence_json, proposed_change_json, status
            FROM strategy_hypotheses
            WHERE as_of_date = ?
            ORDER BY hypothesis_type, title, status
            """,
            (as_of_date,),
        )
    raise ValueError(f"unsupported market-review parity table: {table}")


def _ops_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


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
