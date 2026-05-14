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
from pgc_trading.services.common import RequestContext, ServiceResult
from pgc_trading.services.shadow_observation_service import (
    GetShadowObservationScorecardRequest,
    ListShadowObservationHistoryRequest,
    ShadowObservationScorecardResult,
    ShadowObservationHistoryResult,
    ShadowObservationService,
)
from pgc_trading.services.shadow_strategy_service import (
    GetShadowStrategySnapshotRequest,
    ShadowStrategySnapshotResult,
    ShadowStrategyService,
)
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
DAILY_OPS_APPLY_OPERATION_TYPES = (
    "daily_review",
    "portfolio_generate_buy_plan",
    "portfolio_generate_sell_plan",
    "agent_review_daily_pick",
    "position_exit_evaluate",
)


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


@dataclass(frozen=True)
class DailyOpsStepCheck:
    step: str
    status: str
    required_for_apply: bool
    detail: str
    count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "status": self.status,
            "required_for_apply": self.required_for_apply,
            "detail": self.detail,
            "count": self.count,
        }


@dataclass(frozen=True)
class DailyOpsPreflightResult:
    as_of_date: str
    db_path: Path
    account_key: str | None
    account_id: int | None
    include_market_review: bool
    status: str
    duplicate_apply_count: int
    missing_steps: list[str] = field(default_factory=list)
    warning_steps: list[str] = field(default_factory=list)
    checks: list[DailyOpsStepCheck] = field(default_factory=list)
    pool_intake_status: str = "not_provided"
    pool_intake_mode: str | None = None
    pool_intake_input_count: int = 0
    pool_intake_added_count: int = 0
    pool_intake_rejected_count: int = 0
    pool_intake_dedupe_count: int = 0
    pool_intake_audit_path: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date,
            "db_path": str(self.db_path),
            "account_key": self.account_key,
            "account_id": self.account_id,
            "include_market_review": self.include_market_review,
            "status": self.status,
            "duplicate_apply_count": self.duplicate_apply_count,
            "missing_steps": self.missing_steps,
            "warning_steps": self.warning_steps,
            "checks": [check.to_dict() for check in self.checks],
            "pool_intake_status": self.pool_intake_status,
            "pool_intake_mode": self.pool_intake_mode,
            "pool_intake_input_count": self.pool_intake_input_count,
            "pool_intake_added_count": self.pool_intake_added_count,
            "pool_intake_rejected_count": self.pool_intake_rejected_count,
            "pool_intake_dedupe_count": self.pool_intake_dedupe_count,
            "pool_intake_audit_path": self.pool_intake_audit_path,
        }


@dataclass(frozen=True)
class DailyOpsPoolIntakeSummary:
    status: str
    audit_path: str | None = None
    mode: str | None = None
    input_count: int = 0
    added_count: int = 0
    rejected_count: int = 0
    dedupe_count: int = 0
    detail: str | None = None


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


def run_daily_ops_preflight(
    db_path: Path,
    *,
    as_of_date: str,
    account_key: str | None = "paper-main",
    account_id: int | None = None,
    include_market_review: bool = False,
    pool_intake_summary_path: Path | None = None,
    require_pool_intake: bool = False,
    allow_rerun: bool = False,
    reports_dir: Path | None = None,
) -> DailyOpsPreflightResult:
    """Read-only daily ops checklist for the next daily-pipeline apply run."""

    path = Path(db_path)
    checks: list[DailyOpsStepCheck] = []
    duplicate_apply_count = 0
    report_root = reports_dir or Path("reports")
    pool_intake_summary = _daily_ops_pool_intake_summary(pool_intake_summary_path)

    if not path.exists():
        checks.append(DailyOpsStepCheck("database", "blocker", True, f"database not found: {path}"))
        return _daily_ops_result(
            as_of_date=as_of_date,
            db_path=path,
            account_key=account_key,
            account_id=account_id,
            include_market_review=include_market_review,
            duplicate_apply_count=0,
            checks=checks,
            pool_intake_summary=pool_intake_summary,
        )

    checks.append(DailyOpsStepCheck("database", "pass", True, "database exists"))

    try:
        pending = _pending_migrations(path)
    except sqlite3.Error as exc:
        checks.append(DailyOpsStepCheck("migrations", "blocker", True, f"migration state unreadable: {exc}"))
        return _daily_ops_result(
            as_of_date=as_of_date,
            db_path=path,
            account_key=account_key,
            account_id=account_id,
            include_market_review=include_market_review,
            duplicate_apply_count=0,
            checks=checks,
            pool_intake_summary=pool_intake_summary,
        )

    if pending:
        checks.append(
            DailyOpsStepCheck(
                "migrations",
                "blocker",
                True,
                f"pending migrations: {','.join(pending)}",
                count=len(pending),
            )
        )
        return _daily_ops_result(
            as_of_date=as_of_date,
            db_path=path,
            account_key=account_key,
            account_id=account_id,
            include_market_review=include_market_review,
            duplicate_apply_count=0,
            checks=checks,
            pool_intake_summary=pool_intake_summary,
        )
    checks.append(DailyOpsStepCheck("migrations", "pass", True, "migrations current", count=0))

    try:
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            checks.extend(
                [
                    _daily_ops_account_check(conn, account_key=account_key, account_id=account_id),
                    _daily_ops_trading_day_check(conn, as_of_date),
                    _daily_ops_raw_events_check(conn, as_of_date),
                    _daily_ops_market_data_check(conn, as_of_date),
                    _daily_ops_market_refresh_audit_check(conn, as_of_date),
                    _daily_ops_dry_run_audit_check(conn, as_of_date),
                    _daily_ops_market_review_check(conn, as_of_date, include_market_review),
                    _daily_ops_report_check(report_root, as_of_date),
                ]
            )
            duplicate_apply_count = _daily_ops_duplicate_apply_count(conn, as_of_date)
    except sqlite3.Error as exc:
        checks.append(
            DailyOpsStepCheck(
                "database_read",
                "blocker",
                True,
                f"daily ops preflight query failed: {exc}",
            )
        )

    checks.append(_daily_ops_duplicate_apply_check(duplicate_apply_count, allow_rerun=allow_rerun))
    checks.append(_daily_ops_pool_intake_check(pool_intake_summary, require_pool_intake=require_pool_intake))

    return _daily_ops_result(
        as_of_date=as_of_date,
        db_path=path,
        account_key=account_key,
        account_id=account_id,
        include_market_review=include_market_review,
        duplicate_apply_count=duplicate_apply_count,
        checks=checks,
        pool_intake_summary=pool_intake_summary,
    )


def run_shadow_strategy_snapshot(
    db_path: Path,
    *,
    as_of_date: str | None = None,
    reports_dir: Path | None = None,
) -> ServiceResult[ShadowStrategySnapshotResult]:
    """Build the read-only shadow strategy snapshot used by ops/API/CLI views."""

    service = ShadowStrategyService(Path(db_path), reports_dir=reports_dir)
    return service.get_snapshot(
        GetShadowStrategySnapshotRequest(as_of_date=as_of_date),
        RequestContext(request_id="ops-shadow-strategy-snapshot", dry_run=True, operator="cli", source="ops"),
    )


def run_shadow_observation_scorecard(
    db_path: Path,
    *,
    as_of_date: str | None = None,
    reports_dir: Path | None = None,
) -> ServiceResult[ShadowObservationScorecardResult]:
    """Build the read-only shadow observation scorecard used by ops/API/Dashboard views."""

    service = ShadowObservationService(Path(db_path), reports_dir=reports_dir)
    return service.get_scorecard(
        GetShadowObservationScorecardRequest(as_of_date=as_of_date),
        RequestContext(request_id="ops-shadow-observation-scorecard", dry_run=True, operator="cli", source="ops"),
    )


def run_shadow_observation_history(
    db_path: Path,
    *,
    as_of_date: str | None = None,
    window: int = 20,
    reports_dir: Path | None = None,
) -> ServiceResult[ShadowObservationHistoryResult]:
    """Build the read-only cross-date shadow observation history used by ops/API/Dashboard views."""

    service = ShadowObservationService(Path(db_path), reports_dir=reports_dir)
    return service.list_history(
        ListShadowObservationHistoryRequest(as_of_date=as_of_date, window=window),
        RequestContext(request_id="ops-shadow-observation-history", dry_run=True, operator="cli", source="ops"),
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


def _daily_ops_result(
    *,
    as_of_date: str,
    db_path: Path,
    account_key: str | None,
    account_id: int | None,
    include_market_review: bool,
    duplicate_apply_count: int,
    checks: list[DailyOpsStepCheck],
    pool_intake_summary: DailyOpsPoolIntakeSummary,
) -> DailyOpsPreflightResult:
    missing_steps = [check.step for check in checks if check.required_for_apply and check.status == "blocker"]
    warning_steps = [check.step for check in checks if check.status == "warning"]
    return DailyOpsPreflightResult(
        as_of_date=as_of_date,
        db_path=db_path,
        account_key=account_key,
        account_id=account_id,
        include_market_review=include_market_review,
        status="blocked" if missing_steps else "pass",
        duplicate_apply_count=duplicate_apply_count,
        missing_steps=missing_steps,
        warning_steps=warning_steps,
        checks=checks,
        pool_intake_status=pool_intake_summary.status,
        pool_intake_mode=pool_intake_summary.mode,
        pool_intake_input_count=pool_intake_summary.input_count,
        pool_intake_added_count=pool_intake_summary.added_count,
        pool_intake_rejected_count=pool_intake_summary.rejected_count,
        pool_intake_dedupe_count=pool_intake_summary.dedupe_count,
        pool_intake_audit_path=pool_intake_summary.audit_path,
    )


def _daily_ops_account_check(
    conn: sqlite3.Connection,
    *,
    account_key: str | None,
    account_id: int | None,
) -> DailyOpsStepCheck:
    if not _ops_table_exists(conn, "portfolio_accounts"):
        return DailyOpsStepCheck("account", "blocker", True, "portfolio_accounts table missing")
    if account_id is not None:
        row = conn.execute(
            "SELECT account_key, status FROM portfolio_accounts WHERE id = ?",
            (account_id,),
        ).fetchone()
        ref = f"account_id={account_id}"
    else:
        row = conn.execute(
            "SELECT account_key, status FROM portfolio_accounts WHERE account_key = ?",
            (account_key,),
        ).fetchone()
        ref = f"account_key={account_key or 'none'}"
    if row is None:
        return DailyOpsStepCheck("account", "blocker", True, f"{ref} not found")
    if row["status"] != "active":
        return DailyOpsStepCheck("account", "blocker", True, f"{row['account_key']} status={row['status']}")
    return DailyOpsStepCheck("account", "pass", True, f"{row['account_key']} active")


def _daily_ops_trading_day_check(conn: sqlite3.Connection, as_of_date: str) -> DailyOpsStepCheck:
    if not _ops_table_exists(conn, "trade_calendar"):
        return DailyOpsStepCheck("trading_day", "blocker", True, "trade_calendar table missing")
    row = conn.execute(
        "SELECT is_open FROM trade_calendar WHERE cal_date = ? ORDER BY exchange LIMIT 1",
        (as_of_date,),
    ).fetchone()
    if row is None:
        return DailyOpsStepCheck("trading_day", "blocker", True, f"{as_of_date} missing from trade_calendar")
    if int(row["is_open"]) != 1:
        return DailyOpsStepCheck("trading_day", "blocker", True, f"{as_of_date} is not an open trading day")
    return DailyOpsStepCheck("trading_day", "pass", True, f"{as_of_date} is an open trading day")


def _daily_ops_raw_events_check(conn: sqlite3.Connection, as_of_date: str) -> DailyOpsStepCheck:
    if not _ops_table_exists(conn, "raw_events"):
        return DailyOpsStepCheck("raw_events", "blocker", True, "raw_events table missing")
    count = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM raw_events
            WHERE entry_date <= ?
              AND COALESCE(is_valid, 1) = 1
            """,
            (as_of_date,),
        ).fetchone()[0]
    )
    if count <= 0:
        return DailyOpsStepCheck("raw_events", "blocker", True, "no valid raw events available", count=0)
    return DailyOpsStepCheck("raw_events", "pass", True, f"{count} valid raw event(s) available", count=count)


def _daily_ops_market_data_check(conn: sqlite3.Connection, as_of_date: str) -> DailyOpsStepCheck:
    if not _ops_table_exists(conn, "market_bars"):
        return DailyOpsStepCheck("market_data", "blocker", True, "market_bars table missing")
    count = int(conn.execute("SELECT COUNT(*) FROM market_bars WHERE trade_date = ?", (as_of_date,)).fetchone()[0])
    if count <= 0:
        return DailyOpsStepCheck("market_data", "blocker", True, f"market_bars missing for {as_of_date}", count=0)
    return DailyOpsStepCheck("market_data", "pass", True, f"{count} market_bars row(s) for {as_of_date}", count=count)


def _daily_ops_market_refresh_audit_check(conn: sqlite3.Connection, as_of_date: str) -> DailyOpsStepCheck:
    if not _ops_table_exists(conn, "market_fetch_runs"):
        return DailyOpsStepCheck("market_refresh_audit", "warning", False, "market_fetch_runs table missing")
    row = conn.execute(
        """
        SELECT status, ts_code_count
        FROM market_fetch_runs
        WHERE end_date >= ?
        ORDER BY end_date DESC, id DESC
        LIMIT 1
        """,
        (as_of_date,),
    ).fetchone()
    if row is None:
        return DailyOpsStepCheck(
            "market_refresh_audit",
            "warning",
            False,
            f"no market_fetch_runs audit row covers {as_of_date}",
        )
    status = row["status"]
    count = int(row["ts_code_count"] or 0)
    if status not in {"completed", "partial_success"}:
        return DailyOpsStepCheck("market_refresh_audit", "warning", False, f"latest market refresh status={status}", count=count)
    return DailyOpsStepCheck("market_refresh_audit", "pass", False, f"latest market refresh status={status}", count=count)


def _daily_ops_dry_run_audit_check(conn: sqlite3.Connection, as_of_date: str) -> DailyOpsStepCheck:
    count = _daily_ops_pipeline_dry_run_count(conn, as_of_date)
    if count <= 0:
        return DailyOpsStepCheck(
            "daily_pipeline_dry_run",
            "warning",
            False,
            f"no previous daily-pipeline dry-run audit found for {as_of_date}",
            count=0,
        )
    return DailyOpsStepCheck("daily_pipeline_dry_run", "pass", False, f"{count} daily-pipeline dry-run audit row(s) found", count=count)


def _daily_ops_market_review_check(
    conn: sqlite3.Connection,
    as_of_date: str,
    include_market_review: bool,
) -> DailyOpsStepCheck:
    if not include_market_review:
        return DailyOpsStepCheck("market_review", "pass", False, "not requested")
    if not _ops_table_exists(conn, "market_review_runs"):
        return DailyOpsStepCheck("market_review", "warning", False, "market_review_runs table missing")
    row = conn.execute(
        "SELECT status FROM market_review_runs WHERE as_of_date = ? ORDER BY id DESC LIMIT 1",
        (as_of_date,),
    ).fetchone()
    if row is None:
        return DailyOpsStepCheck(
            "market_review",
            "warning",
            False,
            f"no completed market review yet for {as_of_date}; daily-pipeline apply can create it",
        )
    status = "pass" if row["status"] == "completed" else "warning"
    return DailyOpsStepCheck("market_review", status, False, f"market_review_runs status={row['status']}")


def _daily_ops_report_check(reports_dir: Path, as_of_date: str) -> DailyOpsStepCheck:
    markdown = reports_dir / f"daily_review_{as_of_date}.md"
    payload = reports_dir / f"daily_review_{as_of_date}.json"
    if markdown.exists() and payload.exists():
        return DailyOpsStepCheck("report_refresh", "pass", False, "daily report markdown/json already exist")
    missing = [str(path) for path in (markdown, payload) if not path.exists()]
    return DailyOpsStepCheck("report_refresh", "warning", False, f"report file(s) pending refresh: {','.join(missing)}")


def _daily_ops_duplicate_apply_check(duplicate_apply_count: int, *, allow_rerun: bool) -> DailyOpsStepCheck:
    if duplicate_apply_count <= 0:
        return DailyOpsStepCheck("duplicate_apply", "pass", True, "no completed non-dry daily apply writes found", count=0)
    if allow_rerun:
        return DailyOpsStepCheck(
            "duplicate_apply",
            "warning",
            False,
            "completed non-dry daily apply writes found; allow_rerun acknowledged",
            count=duplicate_apply_count,
        )
    return DailyOpsStepCheck(
        "duplicate_apply",
        "blocker",
        True,
        "completed non-dry daily apply writes already exist; review before rerun",
        count=duplicate_apply_count,
    )


def _daily_ops_pool_intake_summary(pool_intake_summary_path: Path | None) -> DailyOpsPoolIntakeSummary:
    if pool_intake_summary_path is None:
        return DailyOpsPoolIntakeSummary(status="not_provided")
    path = Path(pool_intake_summary_path)
    if not path.exists():
        return DailyOpsPoolIntakeSummary(
            status="missing",
            audit_path=str(path),
            detail=f"pool intake summary not found: {path}",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return DailyOpsPoolIntakeSummary(
            status="unreadable",
            audit_path=str(path),
            detail=f"pool intake summary unreadable: {exc}",
        )
    if not isinstance(payload, dict):
        return DailyOpsPoolIntakeSummary(
            status="unreadable",
            audit_path=str(path),
            detail="pool intake summary must be a JSON object",
        )
    return DailyOpsPoolIntakeSummary(
        status="available",
        audit_path=str(path),
        mode=str(payload.get("mode") or "unknown"),
        input_count=_daily_ops_int_value(payload.get("input_count")),
        added_count=_daily_ops_int_value(payload.get("added_count")),
        rejected_count=_daily_ops_int_value(payload.get("invalid_count")),
        dedupe_count=_daily_ops_int_value(payload.get("duplicate_count")),
    )


def _daily_ops_pool_intake_check(
    summary: DailyOpsPoolIntakeSummary,
    *,
    require_pool_intake: bool,
) -> DailyOpsStepCheck:
    if summary.status == "not_provided":
        status = "blocker" if require_pool_intake else "warning"
        return DailyOpsStepCheck("pool_intake", status, require_pool_intake, "pool intake summary not provided")
    if summary.status == "missing":
        status = "blocker" if require_pool_intake else "warning"
        return DailyOpsStepCheck("pool_intake", status, require_pool_intake, summary.detail or "pool intake summary missing")
    if summary.status == "unreadable":
        return DailyOpsStepCheck("pool_intake", "blocker", True, summary.detail or "pool intake summary unreadable")
    detail = (
        f"mode={summary.mode or 'unknown'} "
        f"input={summary.input_count} "
        f"added={summary.added_count} "
        f"duplicate={summary.dedupe_count} "
        f"invalid={summary.rejected_count}"
    )
    if summary.rejected_count:
        return DailyOpsStepCheck("pool_intake", "blocker", True, detail, count=summary.added_count)
    if require_pool_intake and summary.mode != "apply":
        return DailyOpsStepCheck(
            "pool_intake",
            "blocker",
            True,
            f"{detail}; apply summary required before daily-pipeline apply",
            count=summary.added_count,
        )
    return DailyOpsStepCheck("pool_intake", "pass", require_pool_intake, detail, count=summary.added_count)


def _daily_ops_int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _daily_ops_pipeline_dry_run_count(conn: sqlite3.Connection, as_of_date: str) -> int:
    if not _ops_table_exists(conn, "operation_requests"):
        return 0
    rows = conn.execute(
        """
        SELECT request_json
        FROM operation_requests
        WHERE as_of_date = ?
          AND status IN ('success', 'partial_success', 'skipped')
          AND idempotency_key LIKE 'daily-pipeline:%'
        """,
        (as_of_date,),
    ).fetchall()
    return sum(1 for row in rows if _loads_json_object(row["request_json"]).get("dry_run") is True)


def _daily_ops_duplicate_apply_count(conn: sqlite3.Connection, as_of_date: str) -> int:
    if not _ops_table_exists(conn, "operation_requests"):
        return 0
    rows = conn.execute(
        f"""
        SELECT request_json
        FROM operation_requests
        WHERE as_of_date = ?
          AND status IN ('success', 'partial_success', 'skipped')
          AND operation_type IN ({','.join('?' for _ in DAILY_OPS_APPLY_OPERATION_TYPES)})
        """,
        (as_of_date, *DAILY_OPS_APPLY_OPERATION_TYPES),
    ).fetchall()
    return sum(1 for row in rows if _loads_json_object(row["request_json"]).get("dry_run") is False)


def _loads_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


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
