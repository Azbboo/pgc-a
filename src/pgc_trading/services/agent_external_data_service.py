"""Application service for importing cached advisory data for Agent reviews."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from pgc_trading.config import Paths
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult
from pgc_trading.storage.database import connect


VALID_AGENT_EXTERNAL_ITEM_TYPES = {
    "news",
    "announcement",
    "fundamental",
    "sentiment",
    "risk_note",
    "research_note",
}
VALID_AGENT_EXTERNAL_SENTIMENTS = {"positive", "neutral", "negative", "mixed", "unknown"}
VALID_AGENT_EXTERNAL_IMPORTANCE = {"low", "medium", "high", "unknown"}


@dataclass(frozen=True)
class ImportAgentExternalDataRequest:
    source_file: Path | None = None
    records: list[Mapping[str, Any]] | None = None
    encoding: str = "utf-8"


@dataclass(frozen=True)
class AgentExternalDataValidationIssue:
    index: int
    field: str | None
    code: str
    message: str


@dataclass(frozen=True)
class ImportAgentExternalDataResult:
    row_count: int
    valid_count: int
    invalid_count: int
    would_insert_count: int
    would_update_count: int
    inserted_count: int
    updated_count: int
    agent_external_item_ids: list[int] = field(default_factory=list)
    invalid_records: list[AgentExternalDataValidationIssue] = field(default_factory=list)


@dataclass(frozen=True)
class _PreparedExternalItem:
    ts_code: str
    published_date: str
    item_type: str
    provider: str
    title: str
    summary: str
    url: str | None
    sentiment: str
    importance: str
    metadata_json: str
    source_hash: str


class AgentExternalDataService:
    """Import cached external data without touching strategy, market, or ledger tables."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def import_external_data(
        self,
        request: ImportAgentExternalDataRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ImportAgentExternalDataResult]:
        records_result = _load_request_records(request)
        if isinstance(records_result, ServiceError):
            return _validation_failed_result(
                ctx,
                row_count=0,
                valid_items=[],
                invalid_records=[],
                errors=[records_result],
            )

        records = records_result
        prepared, invalid_records = _prepare_records(records)
        preview_insert_count = 0
        preview_update_count = 0
        if prepared:
            preview_insert_count, preview_update_count = _preview_upserts(self.db_path, prepared)

        if invalid_records:
            return _validation_failed_result(
                ctx,
                row_count=len(records),
                valid_items=prepared,
                invalid_records=invalid_records,
                errors=_service_errors_for_issues(invalid_records),
                would_insert_count=preview_insert_count,
                would_update_count=preview_update_count,
            )

        if ctx.dry_run:
            return ServiceResult(
                status="success",
                request_id=ctx.request_id,
                data=ImportAgentExternalDataResult(
                    row_count=len(records),
                    valid_count=len(prepared),
                    invalid_count=0,
                    would_insert_count=preview_insert_count,
                    would_update_count=preview_update_count,
                    inserted_count=0,
                    updated_count=0,
                    agent_external_item_ids=[],
                    invalid_records=[],
                ),
                lineage={"source_file": str(request.source_file) if request.source_file else None},
            )

        inserted_count = 0
        updated_count = 0
        item_ids: list[int] = []
        with connect(self.db_path) as conn:
            conn.execute("BEGIN")
            try:
                for item in prepared:
                    existing_id = _find_existing_item_id(conn, item)
                    item_id = _upsert_external_item(conn, item)
                    item_ids.append(item_id)
                    if existing_id is None:
                        inserted_count += 1
                    else:
                        updated_count += 1
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=ImportAgentExternalDataResult(
                row_count=len(records),
                valid_count=len(prepared),
                invalid_count=0,
                would_insert_count=inserted_count,
                would_update_count=updated_count,
                inserted_count=inserted_count,
                updated_count=updated_count,
                agent_external_item_ids=item_ids,
                invalid_records=[],
            ),
            created_ids={"agent_external_items": item_ids},
            lineage={"source_file": str(request.source_file) if request.source_file else None},
        )


def build_agent_external_source_hash(
    *,
    provider: str,
    item_type: str,
    ts_code: str,
    published_date: str,
    title: str,
    summary: str,
) -> str:
    """Build a deterministic hash for external advisory item de-duplication."""

    fingerprint = {
        "provider": provider,
        "item_type": item_type,
        "ts_code": ts_code,
        "published_date": published_date,
        "title": title,
        "summary": summary,
    }
    canonical = json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_request_records(request: ImportAgentExternalDataRequest) -> list[Mapping[str, Any]] | ServiceError:
    if request.source_file is None and request.records is None:
        return ServiceError("VALIDATION_ERROR", "source_file or records is required.")
    if request.source_file is not None and request.records is not None:
        return ServiceError("VALIDATION_ERROR", "choose either source_file or records, not both.")
    if request.records is not None:
        records = list(request.records)
        if not all(isinstance(record, Mapping) for record in records):
            return ServiceError("VALIDATION_ERROR", "each external data record must be a JSON object.")
        return records

    source_file = Path(request.source_file) if request.source_file is not None else None
    if source_file is None:
        return ServiceError("VALIDATION_ERROR", "source_file is required.")
    if not source_file.exists():
        return ServiceError("VALIDATION_ERROR", f"source_file does not exist: {source_file}")
    if not source_file.is_file():
        return ServiceError("VALIDATION_ERROR", f"source_file is not a file: {source_file}")

    try:
        payload = json.loads(source_file.read_text(encoding=request.encoding))
    except UnicodeDecodeError as exc:
        return ServiceError("VALIDATION_ERROR", f"source_file could not be decoded: {exc}")
    except json.JSONDecodeError as exc:
        return ServiceError("VALIDATION_ERROR", f"source_file is not valid JSON: {exc}")

    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict) and isinstance(payload.get("records"), list):
        records = payload["records"]
    elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
        records = payload["items"]
    else:
        return ServiceError(
            "VALIDATION_ERROR",
            "source_file JSON must be a list, or an object with a records/items list.",
        )

    if not all(isinstance(record, Mapping) for record in records):
        return ServiceError("VALIDATION_ERROR", "each external data record must be a JSON object.")
    return list(records)


def _prepare_records(
    records: list[Mapping[str, Any]],
) -> tuple[list[_PreparedExternalItem], list[AgentExternalDataValidationIssue]]:
    prepared: list[_PreparedExternalItem] = []
    invalid_records: list[AgentExternalDataValidationIssue] = []

    for index, record in enumerate(records, start=1):
        item, issues = _prepare_record(index, record)
        invalid_records.extend(issues)
        if item is not None:
            prepared.append(item)

    return prepared, invalid_records


def _prepare_record(
    index: int,
    record: Mapping[str, Any],
) -> tuple[_PreparedExternalItem | None, list[AgentExternalDataValidationIssue]]:
    issues: list[AgentExternalDataValidationIssue] = []
    ts_code = _required_text(record, index, "ts_code", issues)
    published_date = _required_text(record, index, "published_date", issues)
    item_type = _required_text(record, index, "item_type", issues)
    provider = _required_text(record, index, "provider", issues)
    title = _required_text(record, index, "title", issues)
    summary = _required_text(record, index, "summary", issues)

    if published_date and not _is_yyyymmdd(published_date):
        issues.append(
            AgentExternalDataValidationIssue(
                index=index,
                field="published_date",
                code="INVALID_PUBLISHED_DATE",
                message="published_date must be a compact YYYYMMDD date.",
            )
        )
    if item_type and item_type not in VALID_AGENT_EXTERNAL_ITEM_TYPES:
        issues.append(
            AgentExternalDataValidationIssue(
                index=index,
                field="item_type",
                code="INVALID_ITEM_TYPE",
                message=f"item_type must be one of: {', '.join(sorted(VALID_AGENT_EXTERNAL_ITEM_TYPES))}.",
            )
        )

    url = _optional_text(record, index, "url", issues)
    sentiment = _optional_choice(
        record,
        index,
        "sentiment",
        VALID_AGENT_EXTERNAL_SENTIMENTS,
        default="unknown",
        issues=issues,
    )
    importance = _optional_choice(
        record,
        index,
        "importance",
        VALID_AGENT_EXTERNAL_IMPORTANCE,
        default="unknown",
        issues=issues,
    )
    metadata_json = _metadata_json(record, index, issues)

    if issues:
        return None, issues

    assert ts_code is not None
    assert published_date is not None
    assert item_type is not None
    assert provider is not None
    assert title is not None
    assert summary is not None
    source_hash = build_agent_external_source_hash(
        provider=provider,
        item_type=item_type,
        ts_code=ts_code,
        published_date=published_date,
        title=title,
        summary=summary,
    )
    return (
        _PreparedExternalItem(
            ts_code=ts_code,
            published_date=published_date,
            item_type=item_type,
            provider=provider,
            title=title,
            summary=summary,
            url=url,
            sentiment=sentiment,
            importance=importance,
            metadata_json=metadata_json,
            source_hash=source_hash,
        ),
        [],
    )


def _required_text(
    record: Mapping[str, Any],
    index: int,
    field: str,
    issues: list[AgentExternalDataValidationIssue],
) -> str | None:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        issues.append(
            AgentExternalDataValidationIssue(
                index=index,
                field=field,
                code="REQUIRED_FIELD",
                message=f"{field} is required and must be a non-blank string.",
            )
        )
        return None
    return value.strip()


def _optional_text(
    record: Mapping[str, Any],
    index: int,
    field: str,
    issues: list[AgentExternalDataValidationIssue],
) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    issues.append(
        AgentExternalDataValidationIssue(
            index=index,
            field=field,
            code="INVALID_FIELD",
            message=f"{field} must be a string when provided.",
        )
    )
    return None


def _optional_choice(
    record: Mapping[str, Any],
    index: int,
    field: str,
    choices: set[str],
    *,
    default: str,
    issues: list[AgentExternalDataValidationIssue],
) -> str:
    value = record.get(field, default)
    if value is None or value == "":
        return default
    if not isinstance(value, str) or value not in choices:
        issues.append(
            AgentExternalDataValidationIssue(
                index=index,
                field=field,
                code="INVALID_FIELD",
                message=f"{field} must be one of: {', '.join(sorted(choices))}.",
            )
        )
        return default
    return value


def _metadata_json(
    record: Mapping[str, Any],
    index: int,
    issues: list[AgentExternalDataValidationIssue],
) -> str:
    metadata = record.get("metadata", {})
    if metadata is None:
        metadata = {}
    try:
        normalized = json.loads(json.dumps(metadata, ensure_ascii=False))
        return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        issues.append(
            AgentExternalDataValidationIssue(
                index=index,
                field="metadata",
                code="INVALID_METADATA",
                message=f"metadata must be JSON-serializable: {exc}",
            )
        )
        return "{}"


def _is_yyyymmdd(value: str) -> bool:
    if len(value) != 8 or not value.isdigit():
        return False
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return parsed.strftime("%Y%m%d") == value


def _preview_upserts(db_path: Path, prepared: list[_PreparedExternalItem]) -> tuple[int, int]:
    insert_count = 0
    update_count = 0
    seen_in_batch: set[tuple[str, str]] = set()
    with connect(db_path) as conn:
        for item in prepared:
            key = (item.provider, item.source_hash)
            if key in seen_in_batch or _find_existing_item_id(conn, item) is not None:
                update_count += 1
            else:
                insert_count += 1
            seen_in_batch.add(key)
    return insert_count, update_count


def _find_existing_item_id(conn: sqlite3.Connection, item: _PreparedExternalItem) -> int | None:
    row = conn.execute(
        """
        SELECT id
        FROM agent_external_items
        WHERE provider = ? AND source_hash = ?
        """,
        (item.provider, item.source_hash),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def _upsert_external_item(conn: sqlite3.Connection, item: _PreparedExternalItem) -> int:
    conn.execute(
        """
        INSERT INTO agent_external_items
          (
            ts_code,
            published_date,
            item_type,
            provider,
            title,
            summary,
            url,
            sentiment,
            importance,
            metadata_json,
            source_hash
          )
        VALUES
          (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, source_hash) DO UPDATE SET
          ts_code = excluded.ts_code,
          published_date = excluded.published_date,
          item_type = excluded.item_type,
          title = excluded.title,
          summary = excluded.summary,
          url = excluded.url,
          sentiment = excluded.sentiment,
          importance = excluded.importance,
          metadata_json = excluded.metadata_json
        """,
        (
            item.ts_code,
            item.published_date,
            item.item_type,
            item.provider,
            item.title,
            item.summary,
            item.url,
            item.sentiment,
            item.importance,
            item.metadata_json,
            item.source_hash,
        ),
    )
    item_id = _find_existing_item_id(conn, item)
    if item_id is None:  # pragma: no cover - defensive guard around SQLite upsert behavior
        raise RuntimeError("agent_external_items upsert did not return a row.")
    return item_id


def _validation_failed_result(
    ctx: RequestContext,
    *,
    row_count: int,
    valid_items: list[_PreparedExternalItem],
    invalid_records: list[AgentExternalDataValidationIssue],
    errors: list[ServiceError],
    would_insert_count: int = 0,
    would_update_count: int = 0,
) -> ServiceResult[ImportAgentExternalDataResult]:
    return ServiceResult(
        status="validation_failed",
        request_id=ctx.request_id,
        data=ImportAgentExternalDataResult(
            row_count=row_count,
            valid_count=len(valid_items),
            invalid_count=len({issue.index for issue in invalid_records}),
            would_insert_count=would_insert_count,
            would_update_count=would_update_count,
            inserted_count=0,
            updated_count=0,
            agent_external_item_ids=[],
            invalid_records=invalid_records,
        ),
        errors=errors,
    )


def _service_errors_for_issues(issues: list[AgentExternalDataValidationIssue]) -> list[ServiceError]:
    return [
        ServiceError(
            code=issue.code,
            message=f"record {issue.index}: {issue.message}",
            entity_type="agent_external_record",
            entity_id=issue.index,
        )
        for issue in issues
    ]
