"""Read-only evidence coverage ledger for provider packs and imported rows."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from pgc_trading.config import ROOT, Paths
from pgc_trading.services.agent_external_data_service import build_agent_external_source_hash
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult
from pgc_trading.services.evidence_provider_pack_service import EVIDENCE_PROVIDER_PACK_CONTRACT
from pgc_trading.services.market_external_data_service import build_market_external_source_hash
from pgc_trading.storage.database import connect


EVIDENCE_COVERAGE_LEDGER_CONTRACT = "evidence_coverage_ledger_v1"
BLOCKING_SOURCE_STATES = {"missing", "stale", "partial", "duplicate", "source-hash-mismatch"}


@dataclass(frozen=True)
class BuildEvidenceCoverageLedgerRequest:
    as_of_date: str | None = None
    manifest_files: list[Path] = field(default_factory=list)
    discover_manifests: bool = False
    encoding: str = "utf-8"


@dataclass(frozen=True)
class EvidenceCoverageLedgerResult:
    ledger_contract: str = EVIDENCE_COVERAGE_LEDGER_CONTRACT
    generated_at: str = ""
    db_path: str = ""
    as_of_date: str | None = None
    manifest_files: list[str] = field(default_factory=list)
    discovered_manifest_count: int = 0
    entry_count: int = 0
    blocking_entry_count: int = 0
    ready_dates: list[str] = field(default_factory=list)
    blocking_dates: list[str] = field(default_factory=list)
    state_counts: dict[str, int] = field(default_factory=dict)
    provider_counts: dict[str, int] = field(default_factory=dict)
    entries: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _ProviderRow:
    kind: str
    as_of_date: str
    provider: str
    entity_type: str
    entity_key: str
    item_type: str
    published_date: str
    source_hash: str | None
    expected_source_hash: str | None
    source_file: str
    manifest_file: str
    source_file_sha256: str | None = None
    source_file_hash_mismatch: bool = False
    source_hash_mismatch: bool = False
    validation_issue: str | None = None


class EvidenceCoverageLedgerService:
    """Build an auditable, read-only ledger for cached external evidence."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def build_coverage_ledger(
        self,
        request: BuildEvidenceCoverageLedgerRequest,
        ctx: RequestContext,
    ) -> ServiceResult[EvidenceCoverageLedgerResult]:
        as_of_date = _compact_date(request.as_of_date)
        if request.as_of_date is not None and (as_of_date is None or not _is_yyyymmdd(as_of_date)):
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_result(self.db_path, request.as_of_date, []),
                errors=[ServiceError("INVALID_AS_OF_DATE", "as_of_date must be compact YYYYMMDD.")],
            )

        explicit_manifests = [Path(path).expanduser() for path in request.manifest_files]
        discovered_manifests = _discover_manifest_files(as_of_date) if request.discover_manifests else []
        manifest_files = _dedupe_paths([*explicit_manifests, *discovered_manifests])
        missing_manifests = [path for path in explicit_manifests if not path.exists()]
        if missing_manifests:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_result(self.db_path, as_of_date, manifest_files),
                errors=[
                    ServiceError("VALIDATION_ERROR", f"manifest_file does not exist: {path}")
                    for path in missing_manifests
                ],
            )

        entries: list[dict[str, Any]] = []
        manifest_keys: set[tuple[str, str, str]] = set()
        manifest_dates: set[str] = set()
        errors: list[ServiceError] = []

        with connect(self.db_path) as conn:
            imported_rows = _load_imported_rows(conn)
            for manifest_file in manifest_files:
                manifest_entries, manifest_entry_keys, dates, manifest_errors = _ledger_entries_from_manifest(
                    manifest_file,
                    imported_rows,
                    as_of_date=as_of_date,
                    encoding=request.encoding,
                )
                entries.extend(manifest_entries)
                manifest_keys.update(manifest_entry_keys)
                manifest_dates.update(dates)
                errors.extend(manifest_errors)

            coverage_dates = sorted({as_of_date} if as_of_date else manifest_dates)
            entries.extend(_database_entries(conn, coverage_dates, manifest_keys))
            manifest_coverage_kinds = {
                (str(entry.get("kind")), str(entry.get("as_of_date")))
                for entry in entries
                if entry.get("source_kind") in {"coverage_status", "unavailable_source", "provider_pack_row"}
            }
            entries.extend(_database_coverage_entries(conn, coverage_dates, manifest_coverage_kinds))

        if as_of_date is not None:
            entries = [entry for entry in entries if entry.get("as_of_date") == as_of_date]

        result = _build_result(
            self.db_path,
            request_as_of_date=as_of_date,
            manifest_files=manifest_files,
            discovered_manifest_count=len(discovered_manifests),
            entries=entries,
        )
        return ServiceResult(
            status="validation_failed" if errors else "success",
            request_id=ctx.request_id,
            data=result,
            errors=errors,
            lineage={
                "as_of_date": as_of_date,
                "manifest_count": len(manifest_files),
                "read_only": "true",
            },
        )


def _ledger_entries_from_manifest(
    manifest_file: Path,
    imported_rows: dict[str, dict[tuple[str, str], sqlite3.Row]],
    *,
    as_of_date: str | None,
    encoding: str,
) -> tuple[list[dict[str, Any]], set[tuple[str, str, str]], set[str], list[ServiceError]]:
    manifest_path = manifest_file.expanduser()
    errors: list[ServiceError] = []
    if not manifest_path.exists():
        return [], set(), set(), [ServiceError("VALIDATION_ERROR", f"manifest_file does not exist: {manifest_path}")]
    if not manifest_path.is_file():
        return [], set(), set(), [ServiceError("VALIDATION_ERROR", f"manifest_file is not a file: {manifest_path}")]
    try:
        payload = json.loads(manifest_path.read_text(encoding=encoding))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], set(), set(), [ServiceError("VALIDATION_ERROR", f"manifest_file is not valid JSON: {exc}")]
    if not isinstance(payload, Mapping):
        return [], set(), set(), [ServiceError("VALIDATION_ERROR", "manifest_file JSON must be an object.")]
    if payload.get("pack_contract") != EVIDENCE_PROVIDER_PACK_CONTRACT:
        return [], set(), set(), [
            ServiceError(
                "UNSUPPORTED_PROVIDER_PACK_CONTRACT",
                f"pack_contract must be {EVIDENCE_PROVIDER_PACK_CONTRACT}.",
            )
        ]

    entries: list[dict[str, Any]] = []
    manifest_keys: set[tuple[str, str, str]] = set()
    dates: set[str] = set()
    seen_source_hashes: set[tuple[str, str, str]] = set()
    groups = payload.get("groups")
    if not isinstance(groups, list):
        return [], set(), set(), [ServiceError("VALIDATION_ERROR", "manifest groups must be a list.")]

    for group in groups:
        if not isinstance(group, Mapping):
            continue
        kind = str(group.get("kind") or "unknown")
        if kind not in {"market_external", "agent_external"}:
            continue
        date_results = group.get("date_results")
        if not isinstance(date_results, list):
            continue
        for date_result in date_results:
            if not isinstance(date_result, Mapping):
                continue
            result_date = _compact_date(_first_text(date_result, "as_of_date"))
            if result_date is None or not _is_yyyymmdd(result_date):
                continue
            if as_of_date is not None and result_date != as_of_date:
                continue
            dates.add(result_date)
            entries.extend(_coverage_entries_from_date_result(kind, result_date, date_result, manifest_path))
            entries.extend(_unavailable_entries_from_date_result(kind, result_date, date_result, manifest_path))
            source_files = date_result.get("source_files")
            if not isinstance(source_files, list):
                continue
            for source_file_payload in source_files:
                if not isinstance(source_file_payload, Mapping):
                    continue
                source_file = _resolve_provider_file(source_file_payload, manifest_path)
                expected_file_sha = _first_text(source_file_payload, "source_file_sha256")
                file_sha_mismatch = False
                if expected_file_sha and source_file.exists() and source_file.is_file():
                    file_sha_mismatch = _sha256_file(source_file) != expected_file_sha
                if not source_file.exists() or not source_file.is_file():
                    entries.append(
                        _base_entry(
                            as_of_date=result_date,
                            kind=kind,
                            provider="unknown",
                            entity_type="provider_file",
                            entity_key=source_file.name,
                            item_type="provider_file",
                            source_state="missing",
                            source_kind="provider_file",
                            manifest_file=str(manifest_path),
                            source_file=str(source_file),
                            reason="provider_file_missing",
                        )
                    )
                    continue
                rows, row_errors = _provider_rows_from_file(
                    source_file,
                    kind,
                    fallback_date=result_date,
                    manifest_file=manifest_path,
                    source_file_sha256=expected_file_sha,
                    source_file_hash_mismatch=file_sha_mismatch,
                    encoding=encoding,
                )
                errors.extend(row_errors)
                for row in rows:
                    state = _manifest_row_state(row, imported_rows, seen_source_hashes)
                    if row.source_hash:
                        key = (row.kind, row.provider, row.source_hash)
                        manifest_keys.add(key)
                        seen_source_hashes.add(key)
                    entries.append(_entry_from_provider_row(row, state, imported_rows))
    return entries, manifest_keys, dates, errors


def _provider_rows_from_file(
    source_file: Path,
    kind: str,
    *,
    fallback_date: str,
    manifest_file: Path,
    source_file_sha256: str | None,
    source_file_hash_mismatch: bool,
    encoding: str,
) -> tuple[list[_ProviderRow], list[ServiceError]]:
    try:
        payload = json.loads(source_file.read_text(encoding=encoding))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], [ServiceError("VALIDATION_ERROR", f"provider file is not valid JSON: {source_file}: {exc}")]
    if not isinstance(payload, Mapping):
        return [], [ServiceError("VALIDATION_ERROR", f"provider file JSON must be an object: {source_file}")]

    items = payload.get("items", payload.get("records"))
    if not isinstance(items, list):
        return [], []
    default_provider = _first_text(payload, "provider", "source", "data_source")
    payload_date = _compact_date(_first_text(payload, "as_of_date", "date", "trade_date")) or fallback_date

    rows: list[_ProviderRow] = []
    for index, raw_item in enumerate(items, start=1):
        if not isinstance(raw_item, Mapping):
            continue
        if kind == "market_external":
            rows.append(
                _market_provider_row(
                    raw_item,
                    index=index,
                    payload_date=payload_date,
                    default_provider=default_provider,
                    source_file=source_file,
                    manifest_file=manifest_file,
                    source_file_sha256=source_file_sha256,
                    source_file_hash_mismatch=source_file_hash_mismatch,
                )
            )
        elif kind == "agent_external":
            rows.append(
                _agent_provider_row(
                    raw_item,
                    index=index,
                    payload=payload,
                    payload_date=payload_date,
                    default_provider=default_provider,
                    source_file=source_file,
                    manifest_file=manifest_file,
                    source_file_sha256=source_file_sha256,
                    source_file_hash_mismatch=source_file_hash_mismatch,
                )
            )
    return rows, []


def _market_provider_row(
    item: Mapping[str, Any],
    *,
    index: int,
    payload_date: str,
    default_provider: str | None,
    source_file: Path,
    manifest_file: Path,
    source_file_sha256: str | None,
    source_file_hash_mismatch: bool,
) -> _ProviderRow:
    as_of_date = _compact_date(_first_text(item, "as_of_date", "date", "trade_date")) or payload_date
    provider = _first_text(item, "provider", "source", "data_source") or default_provider or "unknown"
    scope_type = _first_text(item, "scope_type", "scope") or "unknown"
    scope_key = _first_text(item, "scope_key", "key") or "unknown"
    item_type = _first_text(item, "item_type", "category", "type") or "unknown"
    published_date = _compact_date(_first_text(item, "published_date", "publish_date", "date")) or as_of_date
    title = _first_text(item, "title", "headline", "name")
    summary = _first_text(item, "summary", "abstract", "brief", "content")
    source_hash = _first_text(item, "source_hash")
    expected_source_hash = None
    validation_issue = None
    if provider != "unknown" and scope_type != "unknown" and scope_key != "unknown" and title and summary:
        expected_source_hash = build_market_external_source_hash(
            provider=provider,
            scope_type=scope_type,
            scope_key=scope_key,
            published_date=published_date,
            title=title,
            summary=summary,
        )
    if expected_source_hash is None:
        validation_issue = f"record_{index}_missing_hash_inputs"
    source_hash_mismatch = source_hash != expected_source_hash if source_hash and expected_source_hash else source_hash is None
    return _ProviderRow(
        kind="market_external",
        as_of_date=as_of_date,
        provider=provider,
        entity_type=scope_type,
        entity_key=scope_key,
        item_type=item_type,
        published_date=published_date,
        source_hash=source_hash,
        expected_source_hash=expected_source_hash,
        source_file=str(source_file),
        manifest_file=str(manifest_file),
        source_file_sha256=source_file_sha256,
        source_file_hash_mismatch=source_file_hash_mismatch,
        source_hash_mismatch=source_hash_mismatch,
        validation_issue=validation_issue,
    )


def _agent_provider_row(
    item: Mapping[str, Any],
    *,
    index: int,
    payload: Mapping[str, Any],
    payload_date: str,
    default_provider: str | None,
    source_file: Path,
    manifest_file: Path,
    source_file_sha256: str | None,
    source_file_hash_mismatch: bool,
) -> _ProviderRow:
    as_of_date = _compact_date(_first_text(item, "_as_of_date", "as_of_date", "date", "trade_date")) or payload_date
    provider = _first_text(item, "provider", "source", "src", "data_source") or default_provider or "unknown"
    ts_code = _first_text(item, "ts_code", "code", "symbol") or _first_text(payload, "ts_code", "code", "symbol") or "unknown"
    item_type = _normalize_agent_item_type(_first_text(item, "item_type", "category", "type")) or "unknown"
    published_date = _compact_date(
        _first_text(item, "published_date", "publish_date", "ann_date", "trade_date", "date")
    ) or as_of_date
    title = _first_text(item, "title", "headline", "name", "subject")
    summary = _first_text(item, "summary", "abstract", "brief", "snippet", "content", "text", "description")
    source_hash = _first_text(item, "source_hash")
    expected_source_hash = None
    validation_issue = None
    if provider != "unknown" and ts_code != "unknown" and item_type != "unknown" and title and summary:
        expected_source_hash = build_agent_external_source_hash(
            provider=provider,
            item_type=item_type,
            ts_code=ts_code,
            published_date=published_date,
            title=title,
            summary=summary,
        )
    if expected_source_hash is None:
        validation_issue = f"record_{index}_missing_hash_inputs"
    source_hash_mismatch = bool(source_hash and expected_source_hash and source_hash != expected_source_hash)
    return _ProviderRow(
        kind="agent_external",
        as_of_date=as_of_date,
        provider=provider,
        entity_type="stock",
        entity_key=ts_code,
        item_type=item_type,
        published_date=published_date,
        source_hash=source_hash or expected_source_hash,
        expected_source_hash=expected_source_hash,
        source_file=str(source_file),
        manifest_file=str(manifest_file),
        source_file_sha256=source_file_sha256,
        source_file_hash_mismatch=source_file_hash_mismatch,
        source_hash_mismatch=source_hash_mismatch,
        validation_issue=validation_issue,
    )


def _manifest_row_state(
    row: _ProviderRow,
    imported_rows: dict[str, dict[tuple[str, str], sqlite3.Row]],
    seen_source_hashes: set[tuple[str, str, str]],
) -> str:
    if row.source_file_hash_mismatch or row.source_hash_mismatch:
        return "source-hash-mismatch"
    if not row.source_hash:
        return "source-hash-mismatch"
    key = (row.kind, row.provider, row.source_hash)
    if key in seen_source_hashes:
        return "duplicate"
    db_row = imported_rows.get(row.kind, {}).get((row.provider, row.source_hash))
    if db_row is None:
        return "missing"
    published_date = str(db_row["published_date"] or row.published_date)
    return "stale" if published_date < row.as_of_date else "imported"


def _entry_from_provider_row(
    row: _ProviderRow,
    state: str,
    imported_rows: dict[str, dict[tuple[str, str], sqlite3.Row]],
) -> dict[str, Any]:
    db_row = imported_rows.get(row.kind, {}).get((row.provider, row.source_hash or ""))
    entry = _base_entry(
        as_of_date=row.as_of_date,
        kind=row.kind,
        provider=row.provider,
        entity_type=row.entity_type,
        entity_key=row.entity_key,
        item_type=row.item_type,
        source_state=state,
        source_kind="provider_pack_row",
        manifest_file=row.manifest_file,
        source_file=row.source_file,
        source_hash=row.source_hash,
        published_date=row.published_date,
    )
    entry.update(
        {
            "expected_source_hash": row.expected_source_hash,
            "source_file_sha256": row.source_file_sha256,
            "source_file_hash_mismatch": row.source_file_hash_mismatch,
            "source_hash_mismatch": row.source_hash_mismatch,
            "validation_issue": row.validation_issue,
            "database_item_id": int(db_row["id"]) if db_row is not None else None,
        }
    )
    return entry


def _coverage_entries_from_date_result(
    kind: str,
    as_of_date: str,
    date_result: Mapping[str, Any],
    manifest_file: Path,
) -> list[dict[str, Any]]:
    coverage = date_result.get("coverage_summary")
    entries: list[dict[str, Any]] = []
    if not isinstance(coverage, Mapping):
        return entries
    if kind == "market_external":
        for key in ("market", "sector", "stock", "news", "sentiment", "duplicates"):
            entries.extend(_coverage_status_entries(kind, as_of_date, coverage, key, manifest_file))
        freshness = coverage.get("freshness")
        if isinstance(freshness, Mapping):
            for scope, status in freshness.items():
                entries.extend(
                    _coverage_status_entries(
                        kind,
                        as_of_date,
                        {"freshness": status},
                        "freshness",
                        manifest_file,
                        entity_type=str(scope),
                    )
                )
    elif kind == "agent_external":
        for key in ("fundamental", "announcement", "news", "sentiment", "risk_or_research", "duplicates", "freshness"):
            entries.extend(_coverage_status_entries(kind, as_of_date, coverage, key, manifest_file))
    return entries


def _coverage_status_entries(
    kind: str,
    as_of_date: str,
    coverage: Mapping[str, Any],
    key: str,
    manifest_file: Path | None,
    *,
    entity_type: str | None = None,
) -> list[dict[str, Any]]:
    status = _normalize_source_state(coverage.get(key))
    if status is None:
        return []
    return [
        _base_entry(
            as_of_date=as_of_date,
            kind=kind,
            provider="coverage_summary",
            entity_type=entity_type or ("coverage" if key not in {"market", "sector", "stock"} else key),
            entity_key=key,
            item_type=key,
            source_state=status,
            source_kind="coverage_status",
            manifest_file=str(manifest_file) if manifest_file is not None else None,
        )
    ]


def _unavailable_entries_from_date_result(
    kind: str,
    as_of_date: str,
    date_result: Mapping[str, Any],
    manifest_file: Path,
) -> list[dict[str, Any]]:
    sources = date_result.get("unavailable_sources")
    if not isinstance(sources, list):
        return []
    return [
        _unavailable_entry(kind, as_of_date, source, manifest_file=str(manifest_file))
        for source in sources
        if isinstance(source, Mapping)
    ]


def _unavailable_entry(
    kind: str,
    as_of_date: str,
    source: Mapping[str, Any],
    *,
    manifest_file: str | None,
) -> dict[str, Any]:
    if kind == "market_external":
        entity_type = _first_text(source, "scope_type", "scope") or "coverage"
        entity_key = _first_text(source, "scope_key", "key") or entity_type
        item_type = _first_text(source, "item_type", "category", "type") or "unknown"
    else:
        entity_type = "stock"
        entity_key = _first_text(source, "ts_code", "code", "symbol") or "all"
        item_type = _normalize_agent_item_type(_first_text(source, "item_type", "category", "type")) or "unknown"
    entry = _base_entry(
        as_of_date=as_of_date,
        kind=kind,
        provider=_first_text(source, "provider", "source", "data_source") or "unknown",
        entity_type=entity_type,
        entity_key=entity_key,
        item_type=item_type,
        source_state="unavailable",
        source_kind="unavailable_source",
        manifest_file=manifest_file,
    )
    entry["reason"] = _first_text(source, "reason", "code") or "provider_unavailable"
    entry["note"] = _first_text(source, "note", "message", "summary")
    return entry


def _database_entries(
    conn: sqlite3.Connection,
    as_of_dates: Sequence[str],
    manifest_keys: set[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    if not as_of_dates:
        return []
    entries: list[dict[str, Any]] = []
    placeholders = ",".join("?" for _ in as_of_dates)
    market_rows = conn.execute(
        f"""
        SELECT id, as_of_date, scope_type, scope_key, item_type, provider, published_date, source_hash
        FROM market_external_items
        WHERE as_of_date IN ({placeholders})
        ORDER BY as_of_date, provider, scope_type, scope_key, item_type, id
        """,
        tuple(as_of_dates),
    ).fetchall()
    for row in market_rows:
        key = ("market_external", row["provider"], row["source_hash"])
        if key in manifest_keys:
            continue
        state = "stale" if str(row["published_date"] or "") < str(row["as_of_date"]) else "imported"
        entry = _base_entry(
            as_of_date=row["as_of_date"],
            kind="market_external",
            provider=row["provider"],
            entity_type=row["scope_type"],
            entity_key=row["scope_key"],
            item_type=row["item_type"],
            source_state=state,
            source_kind="database_row",
            source_hash=row["source_hash"],
            published_date=row["published_date"],
        )
        entry["database_item_id"] = int(row["id"])
        entries.append(entry)

    agent_rows = conn.execute(
        f"""
        SELECT id, ts_code, published_date, item_type, provider, source_hash
        FROM agent_external_items
        WHERE published_date IN ({placeholders})
        ORDER BY published_date, provider, ts_code, item_type, id
        """,
        tuple(as_of_dates),
    ).fetchall()
    for row in agent_rows:
        key = ("agent_external", row["provider"], row["source_hash"])
        if key in manifest_keys:
            continue
        entry = _base_entry(
            as_of_date=row["published_date"],
            kind="agent_external",
            provider=row["provider"],
            entity_type="stock",
            entity_key=row["ts_code"],
            item_type=row["item_type"],
            source_state="imported",
            source_kind="database_row",
            source_hash=row["source_hash"],
            published_date=row["published_date"],
        )
        entry["database_item_id"] = int(row["id"])
        entries.append(entry)
    return entries


def _database_coverage_entries(
    conn: sqlite3.Connection,
    as_of_dates: Sequence[str],
    manifest_coverage_kinds: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for as_of_date in as_of_dates:
        if ("market_external", as_of_date) in manifest_coverage_kinds:
            market_counts = []
        else:
            market_counts = conn.execute(
                """
                SELECT scope_type, item_type, sentiment, published_date, COUNT(*) AS count
                FROM market_external_items
                WHERE as_of_date = ?
                GROUP BY scope_type, item_type, sentiment, published_date
                """,
                (as_of_date,),
            ).fetchall()
        if ("agent_external", as_of_date) in manifest_coverage_kinds:
            agent_counts = []
        else:
            agent_counts = conn.execute(
                """
                SELECT item_type, sentiment, published_date, COUNT(*) AS count
                FROM agent_external_items
                WHERE published_date = ?
                GROUP BY item_type, sentiment, published_date
                """,
                (as_of_date,),
            ).fetchall()
        if ("market_external", as_of_date) in manifest_coverage_kinds:
            pass
        else:
            entries.extend(_market_database_coverage_entries(as_of_date, market_counts))
        if ("agent_external", as_of_date) in manifest_coverage_kinds:
            pass
        else:
            entries.extend(_agent_database_coverage_entries(as_of_date, agent_counts))
    return entries


def _market_database_coverage_entries(as_of_date: str, market_counts: Sequence[sqlite3.Row]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    market_by_scope = {str(row["scope_type"]): int(row["count"] or 0) for row in market_counts}
    market_by_item = _count_rows(market_counts, "item_type")
    market_known_sentiment = sum(int(row["count"] or 0) for row in market_counts if row["sentiment"] != "unknown")
    market_total = sum(int(row["count"] or 0) for row in market_counts)
    news_like = {"news", "announcement", "policy", "risk_note", "research_note"}
    market_coverage = {
        "market": "available" if market_by_scope.get("market") else "missing",
        "sector": "partial" if market_by_scope.get("sector") else "missing",
        "stock": "partial" if market_by_scope.get("stock") else "missing",
        "news": "available" if any(market_by_item.get(item_type) for item_type in news_like) else "missing",
        "sentiment": "missing"
        if market_known_sentiment == 0
        else "available"
        if market_known_sentiment == market_total
        else "partial",
    }
    for key in ("market", "sector", "stock", "news", "sentiment"):
        entries.extend(_coverage_status_entries("market_external", as_of_date, market_coverage, key, None))
    return entries


def _agent_database_coverage_entries(as_of_date: str, agent_counts: Sequence[sqlite3.Row]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    agent_by_item = _count_rows(agent_counts, "item_type")
    agent_coverage = {
        "fundamental": "available" if agent_by_item.get("fundamental") else "missing",
        "announcement": "available" if agent_by_item.get("announcement") else "missing",
        "news": "available" if agent_by_item.get("news") else "missing",
        "sentiment": "available" if agent_by_item.get("sentiment") else "missing",
        "risk_or_research": "available"
        if agent_by_item.get("risk_note") or agent_by_item.get("research_note")
        else "missing",
    }
    for key in ("fundamental", "announcement", "news", "sentiment", "risk_or_research"):
        entries.extend(_coverage_status_entries("agent_external", as_of_date, agent_coverage, key, None))
    return entries


def _load_imported_rows(conn: sqlite3.Connection) -> dict[str, dict[tuple[str, str], sqlite3.Row]]:
    market_rows = conn.execute(
        """
        SELECT id, as_of_date, provider, source_hash, published_date
        FROM market_external_items
        """
    ).fetchall()
    agent_rows = conn.execute(
        """
        SELECT id, provider, source_hash, published_date
        FROM agent_external_items
        """
    ).fetchall()
    return {
        "market_external": {(row["provider"], row["source_hash"]): row for row in market_rows},
        "agent_external": {(row["provider"], row["source_hash"]): row for row in agent_rows},
    }


def _build_result(
    db_path: Path,
    *,
    request_as_of_date: str | None,
    manifest_files: Sequence[Path],
    discovered_manifest_count: int,
    entries: list[dict[str, Any]],
) -> EvidenceCoverageLedgerResult:
    state_counts = _counts_by(entries, "source_state")
    provider_counts = _counts_by(entries, "provider")
    dates = sorted({str(entry["as_of_date"]) for entry in entries if entry.get("as_of_date")})
    blocking_dates = sorted(
        {
            str(entry["as_of_date"])
            for entry in entries
            if entry.get("source_state") in BLOCKING_SOURCE_STATES and entry.get("as_of_date")
        }
    )
    ready_dates = [date for date in dates if date not in blocking_dates]
    blocking_entry_count = sum(1 for entry in entries if entry.get("source_state") in BLOCKING_SOURCE_STATES)
    summary = {
        "dates": dates,
        "manifest_count": len(manifest_files),
        "blocking_states": sorted(BLOCKING_SOURCE_STATES),
        "state_counts": state_counts,
        "provider_counts": provider_counts,
        "missing_count": state_counts.get("missing", 0),
        "unavailable_count": state_counts.get("unavailable", 0),
        "partial_count": state_counts.get("partial", 0),
        "stale_count": state_counts.get("stale", 0),
        "duplicate_count": state_counts.get("duplicate", 0),
        "source_hash_mismatch_count": state_counts.get("source-hash-mismatch", 0),
    }
    return EvidenceCoverageLedgerResult(
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        db_path=str(db_path),
        as_of_date=request_as_of_date,
        manifest_files=[_portable_path(path) for path in manifest_files],
        discovered_manifest_count=discovered_manifest_count,
        entry_count=len(entries),
        blocking_entry_count=blocking_entry_count,
        ready_dates=ready_dates,
        blocking_dates=blocking_dates,
        state_counts=state_counts,
        provider_counts=provider_counts,
        entries=entries,
        summary=summary,
        safety={
            "read_only": True,
            "live_fetches": False,
            "writes_trade_state": False,
            "writes_strategy_state": False,
            "enables_timer": False,
        },
    )


def _empty_result(db_path: Path, as_of_date: str | None, manifest_files: Sequence[Path]) -> EvidenceCoverageLedgerResult:
    return _build_result(
        db_path,
        request_as_of_date=_compact_date(as_of_date),
        manifest_files=manifest_files,
        discovered_manifest_count=0,
        entries=[],
    )


def _base_entry(
    *,
    as_of_date: str,
    kind: str,
    provider: str,
    entity_type: str,
    entity_key: str,
    item_type: str,
    source_state: str,
    source_kind: str,
    manifest_file: str | None = None,
    source_file: str | None = None,
    source_hash: str | None = None,
    published_date: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "as_of_date": as_of_date,
        "kind": kind,
        "provider": provider,
        "entity_type": entity_type,
        "entity_key": entity_key,
        "item_type": item_type,
        "source_state": source_state,
        "source_kind": source_kind,
        "published_date": published_date,
        "source_hash": source_hash,
        "manifest_file": _portable_path(manifest_file),
        "source_file": _portable_path(source_file),
        "reason": reason,
    }


def _portable_path(value: str | Path | None) -> str | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    candidate = path if path.is_absolute() else ROOT / path
    try:
        return candidate.resolve(strict=False).relative_to(ROOT).as_posix()
    except ValueError:
        return str(value)


def _normalize_source_state(value: Any) -> str | None:
    if value is None:
        return None
    status = str(value).strip().lower()
    if status in {"available", "fresh", "none"}:
        return None
    if status in {"duplicate", "missing", "unavailable", "partial", "stale", "source-hash-mismatch"}:
        return status
    return None


def _resolve_provider_file(source_file_payload: Mapping[str, Any], manifest_file: Path) -> Path:
    path_text = _first_text(source_file_payload, "output_file") or _first_text(source_file_payload, "source_file")
    if path_text is None:
        return manifest_file.parent / "missing-provider-file"
    raw_path = Path(path_text).expanduser()
    candidates = [raw_path]
    if not raw_path.is_absolute():
        candidates.extend([ROOT / raw_path, manifest_file.parent / raw_path])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _discover_manifest_files(as_of_date: str | None) -> list[Path]:
    runs_dir = ROOT / ".pgc-runs"
    if not runs_dir.exists():
        return []
    manifests = sorted(runs_dir.glob("**/manifest.json"))
    if as_of_date is None:
        return manifests
    return [manifest for manifest in manifests if _manifest_mentions_date(manifest, as_of_date)]


def _manifest_mentions_date(manifest_file: Path, as_of_date: str) -> bool:
    try:
        payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(payload, Mapping):
        return False
    return _date_in_object(payload, as_of_date)


def _date_in_object(value: Any, as_of_date: str) -> bool:
    if isinstance(value, str):
        return _compact_date(value) == as_of_date
    if isinstance(value, Mapping):
        return any(_date_in_object(item, as_of_date) for item in value.values())
    if isinstance(value, list):
        return any(_date_in_object(item, as_of_date) for item in value)
    return False


def _count_rows(rows: Sequence[sqlite3.Row], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        label = str(row[key] or "unknown")
        counts[label] = counts.get(label, 0) + int(row["count"] or 0)
    return counts


def _counts_by(entries: Sequence[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        value = str(entry.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _dedupe_paths(paths: Sequence[Path]) -> list[Path]:
    seen: set[str] = set()
    deduped: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_agent_item_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    mapping = {
        "fundamentals": "fundamental",
        "fundamental_snapshot": "fundamental",
        "fundamental_snapshots": "fundamental",
        "announcement": "announcement",
        "announcements": "announcement",
        "company_announcement": "announcement",
        "company_announcements": "announcement",
        "news_snippet": "news",
        "news_snippets": "news",
        "sentiments": "sentiment",
        "sentiment_snippet": "sentiment",
        "sentiment_snippets": "sentiment",
        "risk": "risk_note",
        "risk_notes": "risk_note",
        "research": "research_note",
        "research_notes": "research_note",
    }
    return mapping.get(normalized, normalized)


def _first_text(source: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
        elif isinstance(value, int):
            return str(value)
        elif isinstance(value, float) and value.is_integer():
            return str(int(value))
    return None


def _compact_date(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        return text
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError:
        return text


def _is_yyyymmdd(value: str) -> bool:
    if len(value) != 8 or not value.isdigit():
        return False
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return parsed.strftime("%Y%m%d") == value
