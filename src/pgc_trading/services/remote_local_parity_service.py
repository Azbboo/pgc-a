"""Read-only local/remote production parity checks."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pgc_trading.storage.migrate import discover_migrations


PARITY_CONTRACT = "remote_local_parity_v1"
BLOCKER = "blocker"
PASS = "pass"
WARNING = "warning"
_STATUS_RANK = {PASS: 0, WARNING: 1, BLOCKER: 2}
_ACTIVE_PLAN_STATUSES = ("draft", "active")
_OPEN_POSITION_STATUSES = (
    "open",
    "waiting_t2",
    "need_t2_decision",
    "holding_to_t5",
    "need_t5_exit",
    "planned_exit",
    "partially_closed",
)


@dataclass(frozen=True)
class BuildRemoteLocalParityRequest:
    """Inputs for a local/remote parity package."""

    as_of_date: str
    local_db_path: Path
    remote_db_path: Path
    local_reports_dir: Path | None = None
    remote_reports_dir: Path | None = None
    account_key: str = "paper-main"
    local_release_tag: str | None = None
    remote_release_tag: str | None = None
    local_git_sha: str | None = None
    remote_git_sha: str | None = None
    generated_at: str | None = None


@dataclass(frozen=True)
class RemoteLocalParityCheck:
    """One comparable parity surface."""

    key: str
    label: str
    status: str
    local_value: Any
    remote_value: Any
    detail: str
    next_command: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "local_value": self.local_value,
            "remote_value": self.remote_value,
            "detail": self.detail,
            "next_command": self.next_command,
        }


@dataclass(frozen=True)
class RemoteLocalParityResult:
    """Full M108 parity result."""

    contract: str
    as_of_date: str
    generated_at: str
    status: str
    account_key: str
    local: dict[str, Any]
    remote: dict[str, Any]
    checks: list[RemoteLocalParityCheck] = field(default_factory=list)
    safety: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status != BLOCKER

    @property
    def blocker_keys(self) -> list[str]:
        return [check.key for check in self.checks if check.status == BLOCKER]

    @property
    def warning_keys(self) -> list[str]:
        return [check.key for check in self.checks if check.status == WARNING]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "as_of_date": self.as_of_date,
            "generated_at": self.generated_at,
            "status": self.status,
            "account_key": self.account_key,
            "local": self.local,
            "remote": self.remote,
            "checks": [check.to_dict() for check in self.checks],
            "blocker_keys": self.blocker_keys,
            "warning_keys": self.warning_keys,
            "safety": self.safety,
        }


class RemoteLocalParityService:
    """Build local/remote parity evidence without mutating either database."""

    def build(self, request: BuildRemoteLocalParityRequest) -> RemoteLocalParityResult:
        generated_at = request.generated_at or datetime.now(UTC).replace(microsecond=0).isoformat()
        local = _build_endpoint_snapshot(
            label="local",
            db_path=Path(request.local_db_path),
            reports_dir=request.local_reports_dir,
            account_key=request.account_key,
            release_tag=request.local_release_tag,
            git_sha=request.local_git_sha,
        )
        remote = _build_endpoint_snapshot(
            label="remote",
            db_path=Path(request.remote_db_path),
            reports_dir=request.remote_reports_dir,
            account_key=request.account_key,
            release_tag=request.remote_release_tag,
            git_sha=request.remote_git_sha,
        )
        checks = _build_checks(request, local, remote)
        status = _overall_status(checks)
        return RemoteLocalParityResult(
            contract=PARITY_CONTRACT,
            as_of_date=request.as_of_date,
            generated_at=generated_at,
            status=status,
            account_key=request.account_key,
            local=local,
            remote=remote,
            checks=checks,
            safety={
                "read_only": True,
                "source_database_mutated": False,
                "strategy_state_mutated": False,
                "trade_state_mutated": False,
                "paper_live_state_mutated": False,
                "broker_order_mutated": False,
                "timer_mutated": False,
                "live_fetch_in_request_path": False,
            },
        )


def render_remote_local_parity_markdown(result: RemoteLocalParityResult) -> str:
    """Render the parity result as an operator-facing Markdown artifact."""

    lines = [
        f"# Remote/Local Parity {result.as_of_date}",
        "",
        f"- contract: `{result.contract}`",
        f"- generated_at: `{result.generated_at}`",
        f"- status: `{result.status}`",
        f"- account_key: `{result.account_key}`",
        f"- blockers: `{','.join(result.blocker_keys) if result.blocker_keys else 'none'}`",
        f"- warnings: `{','.join(result.warning_keys) if result.warning_keys else 'none'}`",
        "",
        "## Endpoint Summary",
        "",
        "| Surface | Local | Remote |",
        "| --- | --- | --- |",
    ]
    for key, label in (
        ("migration", "Latest migration"),
        ("market_bars", "Latest market bars"),
        ("daily_review", "Latest daily review"),
        ("market_review", "Latest market review"),
        ("evidence_imports", "Latest evidence imports"),
        ("paper_ledger", "Paper ledger"),
        ("release", "Release metadata"),
    ):
        lines.append(
            "| "
            f"{label} | "
            f"{_markdown_summary(result.local.get(key, {}))} | "
            f"{_markdown_summary(result.remote.get(key, {}))} |"
        )

    lines.extend(
        [
            "",
            "## Checks",
            "",
            "| Check | Status | Detail | Next command |",
            "| --- | --- | --- | --- |",
        ]
    )
    for check in result.checks:
        lines.append(
            "| "
            f"{check.label} | "
            f"`{check.status}` | "
            f"{_escape_markdown(check.detail)} | "
            f"{_escape_markdown(check.next_command or 'none')} |"
        )

    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Read-only parity package; no strategy, trade, paper/live, broker, or timer mutation.",
            "- No live web/provider fetch is performed inside the parity request path.",
            "",
        ]
    )
    return "\n".join(lines)


def _build_endpoint_snapshot(
    *,
    label: str,
    db_path: Path,
    reports_dir: Path | None,
    account_key: str,
    release_tag: str | None,
    git_sha: str | None,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "label": label,
        "database": {
            "path": str(db_path),
            "exists": db_path.exists(),
            "error": None,
        },
        "migration": _empty_migration_snapshot(db_path),
        "market_bars": _empty_surface_snapshot(),
        "daily_review": _empty_surface_snapshot(),
        "market_review": _empty_surface_snapshot(),
        "evidence_imports": _empty_evidence_snapshot(),
        "paper_ledger": _empty_paper_snapshot(account_key),
        "release": {
            "release_tag": _clean_optional(release_tag),
            "git_sha": _clean_optional(git_sha),
        },
    }
    if reports_dir is not None:
        snapshot["daily_review"].update(_daily_review_report_snapshot(Path(reports_dir)))
    else:
        snapshot["daily_review"]["reports_dir"] = None
        snapshot["daily_review"]["latest_report_date"] = None
        snapshot["daily_review"]["report_files"] = []

    if not db_path.exists():
        snapshot["database"]["error"] = "database_not_found"
        return snapshot

    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            snapshot["migration"] = _migration_snapshot(conn, db_path)
            snapshot["market_bars"] = _market_bar_snapshot(conn)
            snapshot["daily_review"].update(_daily_review_db_snapshot(conn))
            snapshot["market_review"] = _market_review_snapshot(conn)
            snapshot["evidence_imports"] = _evidence_snapshot(conn)
            snapshot["paper_ledger"] = _paper_ledger_snapshot(conn, account_key)
    except sqlite3.Error as exc:
        snapshot["database"]["error"] = str(exc)
    return snapshot


def _build_checks(
    request: BuildRemoteLocalParityRequest,
    local: dict[str, Any],
    remote: dict[str, Any],
) -> list[RemoteLocalParityCheck]:
    checks = [
        _compare_database(local, remote),
        _compare_exact_surface(
            "migration",
            "Migration state",
            local["migration"],
            remote["migration"],
            ["latest_migration", "pending_migrations"],
            BLOCKER,
            "Run deploy/migrate, then `pgc ops health --require-current-migrations` on both endpoints.",
        ),
        _compare_exact_surface(
            "market_bars",
            "Latest market bars",
            local["market_bars"],
            remote["market_bars"],
            ["latest_date", "latest_date_count", "latest_date_signature"],
            BLOCKER,
            "Refresh or copy the current market-bar database, then rerun parity.",
        ),
        _compare_daily_review(local["daily_review"], remote["daily_review"]),
        _compare_exact_surface(
            "market_review",
            "Latest market review",
            local["market_review"],
            remote["market_review"],
            ["latest_date", "latest_status", "latest_signature"],
            BLOCKER,
            "Run or sync the latest market-review rows, then rerun parity.",
        ),
        _compare_exact_surface(
            "evidence_imports",
            "Evidence imports",
            local["evidence_imports"],
            remote["evidence_imports"],
            [
                "market_external_latest_date",
                "market_external_count",
                "market_external_signature",
                "agent_external_latest_date",
                "agent_external_count",
                "agent_external_signature",
            ],
            BLOCKER,
            "Import reviewed provider files on the stale endpoint, then rerun parity.",
        ),
        _compare_exact_surface(
            "paper_ledger",
            "Paper ledger",
            local["paper_ledger"],
            remote["paper_ledger"],
            [
                "account_status",
                "positions_by_status",
                "positions_signature",
                "trade_plans_by_status",
                "trade_plans_signature",
                "executed_trades_count",
                "executed_trades_signature",
            ],
            BLOCKER,
            "Pull the production DB after guarded paper-ledger writes, then rerun parity.",
        ),
        _compare_release(local["release"], remote["release"]),
    ]
    return checks


def _compare_database(local: dict[str, Any], remote: dict[str, Any]) -> RemoteLocalParityCheck:
    local_db = local["database"]
    remote_db = remote["database"]
    if not local_db["exists"] or not remote_db["exists"] or local_db["error"] or remote_db["error"]:
        status = BLOCKER
        detail = "one or both database snapshots are missing or unreadable"
    else:
        status = PASS
        detail = "both database snapshots are readable"
    return RemoteLocalParityCheck(
        key="database",
        label="Database snapshots",
        status=status,
        local_value=local_db,
        remote_value=remote_db,
        detail=detail,
        next_command="Copy the remote SQLite snapshot locally, then rerun `pgc ops remote-local-parity`."
        if status == BLOCKER
        else None,
    )


def _compare_exact_surface(
    key: str,
    label: str,
    local_value: dict[str, Any],
    remote_value: dict[str, Any],
    fields: list[str],
    mismatch_status: str,
    next_command: str,
) -> RemoteLocalParityCheck:
    local_projection = {field: local_value.get(field) for field in fields}
    remote_projection = {field: remote_value.get(field) for field in fields}
    local_error = local_value.get("error")
    remote_error = remote_value.get("error")
    if local_error or remote_error:
        status = BLOCKER
        detail = "one or both surfaces are unreadable"
    elif local_projection == remote_projection:
        status = PASS
        detail = "local and remote values match"
    else:
        status = mismatch_status
        detail = "local and remote values differ"
    return RemoteLocalParityCheck(
        key=key,
        label=label,
        status=status,
        local_value=local_projection,
        remote_value=remote_projection,
        detail=detail,
        next_command=next_command if status != PASS else None,
    )


def _compare_daily_review(
    local_value: dict[str, Any],
    remote_value: dict[str, Any],
) -> RemoteLocalParityCheck:
    fields = ["latest_db_date", "latest_db_count", "latest_report_date", "report_files"]
    local_projection = {field: local_value.get(field) for field in fields}
    remote_projection = {field: remote_value.get(field) for field in fields}
    if local_value.get("error") or remote_value.get("error"):
        status = BLOCKER
        detail = "one or both daily-review surfaces are unreadable"
    elif local_projection == remote_projection:
        status = PASS
        detail = "database daily-review rows and report files match"
    elif local_value.get("reports_dir") is None or remote_value.get("reports_dir") is None:
        status = WARNING
        detail = "report directory metadata is incomplete"
    else:
        status = BLOCKER
        detail = "database daily-review rows or report files differ"
    return RemoteLocalParityCheck(
        key="daily_review",
        label="Daily review artifacts",
        status=status,
        local_value=local_projection,
        remote_value=remote_projection,
        detail=detail,
        next_command="Sync or regenerate daily_review_YYYYMMDD reports, then rerun parity."
        if status != PASS
        else None,
    )


def _compare_release(
    local_value: dict[str, Any],
    remote_value: dict[str, Any],
) -> RemoteLocalParityCheck:
    local_tag = local_value.get("release_tag")
    remote_tag = remote_value.get("release_tag")
    local_sha = _short_sha(local_value.get("git_sha"))
    remote_sha = _short_sha(remote_value.get("git_sha"))
    local_projection = {"release_tag": local_tag, "git_sha": local_sha}
    remote_projection = {"release_tag": remote_tag, "git_sha": remote_sha}
    if local_projection == remote_projection and (local_tag or local_sha):
        status = PASS
        detail = "release metadata matches"
    elif not (local_tag or remote_tag or local_sha or remote_sha):
        status = WARNING
        detail = "release metadata was not supplied"
    else:
        status = WARNING
        detail = "release metadata differs or is incomplete"
    return RemoteLocalParityCheck(
        key="release",
        label="Release metadata",
        status=status,
        local_value=local_projection,
        remote_value=remote_projection,
        detail=detail,
        next_command="Read /opt/pgc/.deployed-release and /opt/pgc/.deployed-revision, then rerun parity."
        if status != PASS
        else None,
    )


def _overall_status(checks: list[RemoteLocalParityCheck]) -> str:
    if not checks:
        return PASS
    return max((check.status for check in checks), key=lambda status: _STATUS_RANK[status])


def _empty_surface_snapshot() -> dict[str, Any]:
    return {
        "latest_date": None,
        "latest_date_count": 0,
        "latest_date_signature": None,
        "latest_db_date": None,
        "latest_db_count": 0,
        "latest_report_date": None,
        "latest_status": None,
        "latest_signature": None,
        "error": None,
    }


def _empty_migration_snapshot(db_path: Path) -> dict[str, Any]:
    return {
        "db_path": str(db_path),
        "latest_migration": None,
        "applied_migrations": [],
        "pending_migrations": [migration.label for migration in discover_migrations()],
        "error": None,
    }


def _empty_evidence_snapshot() -> dict[str, Any]:
    return {
        "market_external_latest_date": None,
        "market_external_count": 0,
        "market_external_signature": None,
        "agent_external_latest_date": None,
        "agent_external_count": 0,
        "agent_external_signature": None,
        "error": None,
    }


def _empty_paper_snapshot(account_key: str) -> dict[str, Any]:
    return {
        "account_key": account_key,
        "account_id": None,
        "account_status": None,
        "positions_by_status": {},
        "open_positions_count": 0,
        "positions_signature": None,
        "trade_plans_by_status": {},
        "active_trade_plans_count": 0,
        "trade_plans_signature": None,
        "executed_trades_count": 0,
        "executed_trades_signature": None,
        "error": None,
    }


def _migration_snapshot(conn: sqlite3.Connection, db_path: Path) -> dict[str, Any]:
    applied = _read_applied_migrations(conn)
    applied_versions = {label.split("_", 1)[0] for label in applied}
    pending = [migration.label for migration in discover_migrations() if migration.version not in applied_versions]
    return {
        "db_path": str(db_path),
        "latest_migration": applied[-1] if applied else None,
        "applied_migrations": applied,
        "pending_migrations": pending,
        "error": None,
    }


def _read_applied_migrations(conn: sqlite3.Connection) -> list[str]:
    if not _object_exists(conn, "schema_migrations"):
        return []
    rows = conn.execute("SELECT version, name FROM schema_migrations ORDER BY version").fetchall()
    return [f"{row['version']}_{row['name']}" for row in rows]


def _market_bar_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    if not _object_exists(conn, "market_bars"):
        return {**_empty_surface_snapshot(), "error": "market_bars table missing"}
    latest_date = _single_value(conn, "SELECT MAX(trade_date) AS value FROM market_bars")
    if latest_date is None:
        return {**_empty_surface_snapshot(), "total_count": 0}
    rows = conn.execute(
        """
        SELECT ts_code, trade_date, open, high, low, close, vol, amount, provider
        FROM market_bars
        WHERE trade_date = ?
        ORDER BY ts_code
        """,
        (latest_date,),
    ).fetchall()
    total = int(_single_value(conn, "SELECT COUNT(*) AS value FROM market_bars") or 0)
    return {
        "latest_date": latest_date,
        "latest_date_count": len(rows),
        "latest_date_signature": _rows_signature(rows),
        "total_count": total,
        "error": None,
    }


def _daily_review_db_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    if not _object_exists(conn, "v_daily_review"):
        return {"latest_db_date": None, "latest_db_count": 0}
    latest_date = _single_value(conn, "SELECT MAX(review_date) AS value FROM v_daily_review")
    if latest_date is None:
        return {"latest_db_date": None, "latest_db_count": 0}
    count = int(
        _single_value(
            conn,
            "SELECT COUNT(*) AS value FROM v_daily_review WHERE review_date = ?",
            (latest_date,),
        )
        or 0
    )
    return {"latest_db_date": latest_date, "latest_db_count": count}


def _daily_review_report_snapshot(reports_dir: Path) -> dict[str, Any]:
    snapshot = {
        "reports_dir": str(reports_dir),
        "latest_report_date": None,
        "report_files": [],
    }
    if not reports_dir.exists():
        snapshot["error"] = "reports_dir_not_found"
        return snapshot
    dates: set[str] = set()
    files_by_date: dict[str, list[str]] = {}
    for path in reports_dir.glob("daily_review_????????.*"):
        stem = path.stem
        date = stem.removeprefix("daily_review_")
        if len(date) != 8 or not date.isdigit():
            continue
        dates.add(date)
        files_by_date.setdefault(date, []).append(path.name)
    if not dates:
        return snapshot
    latest = max(dates)
    snapshot["latest_report_date"] = latest
    snapshot["report_files"] = sorted(files_by_date.get(latest, []))
    return snapshot


def _market_review_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    if not _object_exists(conn, "market_review_runs"):
        return {**_empty_surface_snapshot(), "error": "market_review_runs table missing"}
    row = conn.execute(
        """
        SELECT id, as_of_date, status, provider_manifest_json, coverage_json, summary_json
        FROM market_review_runs
        ORDER BY as_of_date DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return _empty_surface_snapshot()
    latest_date = str(row["as_of_date"])
    signature_rows = [row]
    for table in (
        "market_regime_snapshots",
        "sector_daily_snapshots",
        "sector_constituents",
        "market_plan_contexts",
        "strategy_hypotheses",
    ):
        signature_rows.extend(_market_review_related_rows(conn, table, latest_date, int(row["id"])))
    return {
        "latest_date": latest_date,
        "latest_status": row["status"],
        "latest_signature": _rows_signature(signature_rows),
        "error": None,
    }


def _market_review_related_rows(
    conn: sqlite3.Connection,
    table: str,
    latest_date: str,
    run_id: int,
) -> list[sqlite3.Row]:
    if not _object_exists(conn, table):
        return []
    if table == "strategy_hypotheses":
        return conn.execute(
            """
            SELECT as_of_date, hypothesis_type, title, rationale, evidence_json, proposed_change_json, status
            FROM strategy_hypotheses
            WHERE as_of_date = ?
            ORDER BY hypothesis_type, title, status
            """,
            (latest_date,),
        ).fetchall()
    rows = conn.execute(
        f"SELECT * FROM {table} WHERE market_review_run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    return rows


def _evidence_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    snapshot = _empty_evidence_snapshot()
    market = _dated_table_snapshot(
        conn,
        table="market_external_items",
        date_column="as_of_date",
        order_columns=["scope_type", "scope_key", "item_type", "provider", "source_hash"],
    )
    agent = _dated_table_snapshot(
        conn,
        table="agent_external_items",
        date_column="published_date",
        order_columns=["ts_code", "item_type", "provider", "source_hash"],
    )
    snapshot.update(
        {
            "market_external_latest_date": market["latest_date"],
            "market_external_count": market["count"],
            "market_external_signature": market["signature"],
            "agent_external_latest_date": agent["latest_date"],
            "agent_external_count": agent["count"],
            "agent_external_signature": agent["signature"],
            "error": market["error"] or agent["error"],
        }
    )
    return snapshot


def _dated_table_snapshot(
    conn: sqlite3.Connection,
    *,
    table: str,
    date_column: str,
    order_columns: list[str],
) -> dict[str, Any]:
    if not _object_exists(conn, table):
        return {"latest_date": None, "count": 0, "signature": None, "error": f"{table} table missing"}
    latest_date = _single_value(conn, f"SELECT MAX({date_column}) AS value FROM {table}")
    if latest_date is None:
        return {"latest_date": None, "count": 0, "signature": None, "error": None}
    order_sql = ", ".join(order_columns)
    rows = conn.execute(
        f"SELECT * FROM {table} WHERE {date_column} = ? ORDER BY {order_sql}",
        (latest_date,),
    ).fetchall()
    return {"latest_date": latest_date, "count": len(rows), "signature": _rows_signature(rows), "error": None}


def _paper_ledger_snapshot(conn: sqlite3.Connection, account_key: str) -> dict[str, Any]:
    snapshot = _empty_paper_snapshot(account_key)
    if not _object_exists(conn, "portfolio_accounts"):
        return {**snapshot, "error": "portfolio_accounts table missing"}
    account = conn.execute(
        "SELECT id, account_key, status FROM portfolio_accounts WHERE account_key = ?",
        (account_key,),
    ).fetchone()
    if account is None:
        return {**snapshot, "error": f"account_not_found:{account_key}"}
    account_id = int(account["id"])
    positions = _status_counts(conn, "positions", account_id)
    trade_plans = _status_counts(conn, "trade_plans", account_id)
    position_rows = _paper_rows(conn, "positions", account_id, ["id"])
    plan_rows = _paper_rows(conn, "trade_plans", account_id, ["id"])
    trade_rows = _paper_rows(conn, "trades", account_id, ["executed_date", "id"])
    return {
        "account_key": account["account_key"],
        "account_id": account_id,
        "account_status": account["status"],
        "positions_by_status": positions,
        "open_positions_count": sum(positions.get(status, 0) for status in _OPEN_POSITION_STATUSES),
        "positions_signature": _rows_signature(position_rows),
        "trade_plans_by_status": trade_plans,
        "active_trade_plans_count": sum(trade_plans.get(status, 0) for status in _ACTIVE_PLAN_STATUSES),
        "trade_plans_signature": _rows_signature(plan_rows),
        "executed_trades_count": len(trade_rows),
        "executed_trades_signature": _rows_signature(trade_rows),
        "error": None,
    }


def _status_counts(conn: sqlite3.Connection, table: str, account_id: int) -> dict[str, int]:
    if not _object_exists(conn, table):
        return {}
    rows = conn.execute(
        f"SELECT status, COUNT(*) AS count FROM {table} WHERE account_id = ? GROUP BY status ORDER BY status",
        (account_id,),
    ).fetchall()
    return {str(row["status"]): int(row["count"]) for row in rows}


def _paper_rows(
    conn: sqlite3.Connection,
    table: str,
    account_id: int,
    order_columns: list[str],
) -> list[sqlite3.Row]:
    if not _object_exists(conn, table):
        return []
    order_sql = ", ".join(order_columns)
    return conn.execute(
        f"SELECT * FROM {table} WHERE account_id = ? ORDER BY {order_sql}",
        (account_id,),
    ).fetchall()


def _single_value(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...] = (),
) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row["value"] if row is not None else None


def _object_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ? AND type IN ('table', 'view')",
        (name,),
    ).fetchone()
    return row is not None


def _rows_signature(rows: list[sqlite3.Row]) -> str:
    payload = [dict(row) for row in rows]
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _short_sha(value: str | None) -> str | None:
    cleaned = _clean_optional(value)
    return cleaned[:12] if cleaned is not None else None


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _markdown_summary(value: dict[str, Any]) -> str:
    if not isinstance(value, dict):
        return "`n/a`"
    summary_keys = [
        "latest_migration",
        "pending_migrations",
        "latest_date",
        "latest_date_count",
        "latest_db_date",
        "latest_db_count",
        "latest_report_date",
        "market_external_latest_date",
        "market_external_count",
        "agent_external_latest_date",
        "agent_external_count",
        "open_positions_count",
        "active_trade_plans_count",
        "release_tag",
        "git_sha",
    ]
    parts: list[str] = []
    for key in summary_keys:
        if key == "latest_date_count" and value.get("latest_date") is None:
            continue
        if key in value and value[key] not in (None, [], {}):
            parts.append(f"{key}={value[key]}")
    if not parts:
        return "`none`"
    return "`" + _escape_markdown("; ".join(str(part) for part in parts)) + "`"


def _escape_markdown(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
