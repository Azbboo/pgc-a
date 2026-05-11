"""Application service for importing cached advisory data for Agent reviews."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

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
AGENT_EXTERNAL_PROVIDER_FILE_CONTRACT = "agent_external_v1"
VALID_AGENT_EXTERNAL_PROVIDER_FILE_CONTRACTS = {AGENT_EXTERNAL_PROVIDER_FILE_CONTRACT}
UNAVAILABLE_SOURCE_DEFAULT_REASON = "provider_unavailable"
STRUCTURED_EXTERNAL_COLLECTIONS = {
    "fundamental_snapshots": "fundamental",
    "fundamentals": "fundamental",
    "announcements": "announcement",
    "company_announcements": "announcement",
    "news": "news",
    "news_snippets": "news",
    "sentiments": "sentiment",
    "sentiment_snippets": "sentiment",
}


@dataclass(frozen=True)
class ImportAgentExternalDataRequest:
    source_file: Path | None = None
    records: list[Mapping[str, Any]] | None = None
    encoding: str = "utf-8"
    default_provider: str | None = None
    default_published_date: str | None = None


@dataclass(frozen=True)
class AgentExternalDataValidationIssue:
    index: int
    field: str | None
    code: str
    message: str


@dataclass(frozen=True)
class ImportAgentExternalDataResult:
    as_of_date: str | None
    row_count: int
    valid_count: int
    invalid_count: int
    would_insert_count: int
    would_update_count: int
    inserted_count: int
    updated_count: int
    coverage_summary: dict[str, Any] = field(default_factory=dict)
    provider_file_contract: str = AGENT_EXTERNAL_PROVIDER_FILE_CONTRACT
    agent_external_item_ids: list[int] = field(default_factory=list)
    unavailable_sources: list[dict[str, Any]] = field(default_factory=list)
    invalid_records: list[AgentExternalDataValidationIssue] = field(default_factory=list)


@dataclass(frozen=True)
class BackfillAgentExternalDataRequest:
    source_files: list[Path]
    encoding: str = "utf-8"
    default_provider: str | None = None


@dataclass(frozen=True)
class AgentExternalBackfillDateResult:
    as_of_date: str
    source_files: list[str]
    row_count: int
    valid_count: int
    invalid_count: int
    would_insert_count: int
    would_update_count: int
    inserted_count: int
    updated_count: int
    coverage_summary: dict[str, Any]
    unavailable_sources: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class BackfillAgentExternalDataResult:
    file_count: int
    date_count: int
    row_count: int
    valid_count: int
    invalid_count: int
    would_insert_count: int
    would_update_count: int
    inserted_count: int
    updated_count: int
    coverage_qa: dict[str, Any]
    provider_file_contract: str = AGENT_EXTERNAL_PROVIDER_FILE_CONTRACT
    date_results: list[AgentExternalBackfillDateResult] = field(default_factory=list)
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


@dataclass(frozen=True)
class _AgentCoverageItem:
    ts_code: str
    item_type: str
    sentiment: str
    published_date: str


@dataclass(frozen=True)
class _UnavailableAgentExternalSource:
    item_type: str
    provider: str
    reason: str
    ts_code: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class _AgentExternalInput:
    records: list[Mapping[str, Any]]
    unavailable_sources: list[_UnavailableAgentExternalSource]
    as_of_date: str | None


@dataclass(frozen=True)
class _AgentExternalBackfillBatch:
    as_of_date: str
    source_files: list[Path]
    row_count: int
    prepared: list[_PreparedExternalItem]
    unavailable_sources: list[_UnavailableAgentExternalSource]
    invalid_records: list[AgentExternalDataValidationIssue]


class AgentExternalDataService:
    """Import cached external data without touching strategy, market, or ledger tables."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def import_external_data(
        self,
        request: ImportAgentExternalDataRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ImportAgentExternalDataResult]:
        input_result = _load_request_input(request)
        if isinstance(input_result, ServiceError):
            return _validation_failed_result(
                ctx,
                as_of_date=_compact_structured_date(request.default_published_date),
                row_count=0,
                valid_items=[],
                invalid_records=[],
                errors=[input_result],
            )

        records = input_result.records
        unavailable_sources = input_result.unavailable_sources
        prepared, invalid_records = _prepare_records(records)
        coverage_as_of_date = _coverage_as_of_date(request, records, input_as_of_date=input_result.as_of_date)
        preview_insert_count = 0
        preview_update_count = 0
        if prepared:
            preview_insert_count, preview_update_count = _preview_upserts(self.db_path, prepared)
        coverage_summary = self._coverage_for_import(
            coverage_as_of_date,
            prepared,
            unavailable_sources=unavailable_sources,
            duplicate_count=preview_update_count,
        )

        if invalid_records:
            return _validation_failed_result(
                ctx,
                as_of_date=coverage_as_of_date,
                row_count=len(records),
                valid_items=prepared,
                invalid_records=invalid_records,
                errors=_service_errors_for_issues(invalid_records),
                would_insert_count=preview_insert_count,
                would_update_count=preview_update_count,
                coverage_summary=coverage_summary,
                unavailable_sources=unavailable_sources,
            )

        if ctx.dry_run:
            return ServiceResult(
                status="success",
                request_id=ctx.request_id,
                data=ImportAgentExternalDataResult(
                    as_of_date=coverage_as_of_date,
                    row_count=len(records),
                    valid_count=len(prepared),
                    invalid_count=0,
                    would_insert_count=preview_insert_count,
                    would_update_count=preview_update_count,
                    inserted_count=0,
                    updated_count=0,
                    coverage_summary=coverage_summary,
                    agent_external_item_ids=[],
                    unavailable_sources=_unavailable_source_payloads(unavailable_sources),
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
                as_of_date=coverage_as_of_date,
                row_count=len(records),
                valid_count=len(prepared),
                invalid_count=0,
                would_insert_count=inserted_count,
                would_update_count=updated_count,
                inserted_count=inserted_count,
                updated_count=updated_count,
                coverage_summary=self.summarize_coverage(
                    coverage_as_of_date,
                    unavailable_sources=unavailable_sources,
                    duplicate_count=updated_count,
                ),
                agent_external_item_ids=item_ids,
                unavailable_sources=_unavailable_source_payloads(unavailable_sources),
                invalid_records=[],
            ),
            created_ids={"agent_external_items": item_ids},
            lineage={"source_file": str(request.source_file) if request.source_file else None},
        )

    def backfill_external_data(
        self,
        request: BackfillAgentExternalDataRequest,
        ctx: RequestContext,
    ) -> ServiceResult[BackfillAgentExternalDataResult]:
        source_files = [Path(path) for path in request.source_files]
        if not source_files:
            return _agent_backfill_failed_result(
                ctx,
                db_path=self.db_path,
                file_count=0,
                batches=[],
                invalid_records=[],
                errors=[ServiceError("VALIDATION_ERROR", "at least one source_file is required for backfill.")],
                preview_counts={},
            )

        batches_by_date: dict[str, _AgentExternalBackfillBatch] = {}
        errors: list[ServiceError] = []
        for source_file in source_files:
            input_result = _load_request_input(
                ImportAgentExternalDataRequest(
                    source_file=source_file,
                    encoding=request.encoding,
                    default_provider=request.default_provider,
                )
            )
            if isinstance(input_result, ServiceError):
                errors.append(input_result)
                continue

            records = input_result.records
            prepared, invalid_records = _prepare_records(records)
            coverage_as_of_date = _coverage_as_of_date(
                ImportAgentExternalDataRequest(
                    source_file=source_file,
                    encoding=request.encoding,
                    default_provider=request.default_provider,
                ),
                records,
                input_as_of_date=input_result.as_of_date,
            )
            if coverage_as_of_date is None or not _is_yyyymmdd(coverage_as_of_date):
                errors.append(
                    ServiceError(
                        "MISSING_BACKFILL_AS_OF_DATE",
                        f"source_file must include a valid as_of_date/date/trade_date for backfill: {source_file}",
                    )
                )
                continue
            if invalid_records:
                errors.extend(_service_errors_for_issues(invalid_records))

            existing_batch = batches_by_date.get(coverage_as_of_date)
            if existing_batch is None:
                batches_by_date[coverage_as_of_date] = _AgentExternalBackfillBatch(
                    as_of_date=coverage_as_of_date,
                    source_files=[source_file],
                    row_count=len(records),
                    prepared=prepared,
                    unavailable_sources=input_result.unavailable_sources,
                    invalid_records=invalid_records,
                )
            else:
                batches_by_date[coverage_as_of_date] = _AgentExternalBackfillBatch(
                    as_of_date=coverage_as_of_date,
                    source_files=[*existing_batch.source_files, source_file],
                    row_count=existing_batch.row_count + len(records),
                    prepared=[*existing_batch.prepared, *prepared],
                    unavailable_sources=[*existing_batch.unavailable_sources, *input_result.unavailable_sources],
                    invalid_records=[*existing_batch.invalid_records, *invalid_records],
                )

        batches = [batches_by_date[date] for date in sorted(batches_by_date)]
        preview_counts = _preview_backfill_upserts(self.db_path, batches)
        if errors:
            return _agent_backfill_failed_result(
                ctx,
                db_path=self.db_path,
                file_count=len(source_files),
                batches=batches,
                invalid_records=[
                    issue
                    for batch in batches
                    for issue in batch.invalid_records
                ],
                errors=errors,
                preview_counts=preview_counts,
            )

        if ctx.dry_run:
            return ServiceResult(
                status="success",
                request_id=ctx.request_id,
                data=_build_agent_backfill_result(
                    self.db_path,
                    file_count=len(source_files),
                    batches=batches,
                    preview_counts=preview_counts,
                    write_counts={date: (0, 0) for date in preview_counts},
                    invalid_records=[],
                ),
                lineage={"source_files": str(len(source_files))},
            )

        write_counts: dict[str, tuple[int, int]] = {}
        item_ids: list[int] = []
        with connect(self.db_path) as conn:
            conn.execute("BEGIN")
            try:
                write_counts, item_ids = _upsert_backfill_items(conn, batches)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=_build_agent_backfill_result(
                self.db_path,
                file_count=len(source_files),
                batches=batches,
                preview_counts=preview_counts,
                write_counts=write_counts,
                invalid_records=[],
                use_persisted_coverage=True,
            ),
            created_ids={"agent_external_items": item_ids},
            lineage={"source_files": str(len(source_files))},
        )

    def summarize_coverage(
        self,
        as_of_date: str | None,
        *,
        unavailable_sources: Sequence[_UnavailableAgentExternalSource] = (),
        duplicate_count: int = 0,
    ) -> dict[str, Any]:
        compact_date = _compact_structured_date(as_of_date)
        if compact_date is None or not _is_yyyymmdd(compact_date):
            return build_agent_external_coverage_summary(
                [],
                None,
                unavailable_sources=unavailable_sources,
                duplicate_count=duplicate_count,
            )
        with connect(self.db_path) as conn:
            return build_agent_external_coverage_summary(
                _load_agent_coverage_items(conn, compact_date),
                compact_date,
                unavailable_sources=unavailable_sources,
                duplicate_count=duplicate_count,
            )

    def _coverage_for_import(
        self,
        as_of_date: str | None,
        prepared: Sequence[_PreparedExternalItem],
        *,
        unavailable_sources: Sequence[_UnavailableAgentExternalSource] = (),
        duplicate_count: int = 0,
    ) -> dict[str, Any]:
        compact_date = _compact_structured_date(as_of_date)
        items: list[_AgentCoverageItem] = []
        if compact_date is not None and _is_yyyymmdd(compact_date):
            with connect(self.db_path) as conn:
                items = _load_agent_coverage_items(conn, compact_date)
        items.extend(
            _AgentCoverageItem(
                ts_code=item.ts_code,
                item_type=item.item_type,
                sentiment=item.sentiment,
                published_date=item.published_date,
            )
            for item in prepared
        )
        return build_agent_external_coverage_summary(
            items,
            compact_date if compact_date is not None and _is_yyyymmdd(compact_date) else None,
            unavailable_sources=unavailable_sources,
            duplicate_count=duplicate_count,
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


def build_agent_external_coverage_summary(
    items: Sequence[_AgentCoverageItem],
    as_of_date: str | None,
    *,
    unavailable_sources: Sequence[_UnavailableAgentExternalSource] = (),
    duplicate_count: int = 0,
) -> dict[str, Any]:
    by_item_type = _count_agent_by(items, "item_type")
    freshness = _agent_freshness(items, as_of_date)
    unavailable_item_types = _unavailable_item_type_set(unavailable_sources)
    item_type_statuses = {
        item_type: _agent_item_type_status(by_item_type, item_type, unavailable_item_types)
        for item_type in ("fundamental", "announcement", "news", "sentiment")
    }
    missing_item_types = [
        item_type
        for item_type in ("fundamental", "announcement", "news", "sentiment")
        if item_type_statuses[item_type] == "missing"
    ]
    unavailable_item_type_list = [
        item_type
        for item_type in ("fundamental", "announcement", "news", "sentiment")
        if item_type_statuses[item_type] == "unavailable"
    ]
    return {
        "as_of_date": as_of_date or "unknown",
        "total_count": len(items),
        "stock_count": len({item.ts_code for item in items}),
        "fundamental": item_type_statuses["fundamental"],
        "announcement": item_type_statuses["announcement"],
        "news": item_type_statuses["news"],
        "sentiment": _agent_sentiment_status(items, unavailable_item_types),
        "risk_or_research": "available"
        if by_item_type.get("risk_note", 0) or by_item_type.get("research_note", 0)
        else "missing",
        "duplicates": "duplicate" if duplicate_count else "none",
        "duplicate_count": duplicate_count,
        "missing_item_types": missing_item_types,
        "unavailable_count": len(unavailable_sources),
        "unavailable_item_types": unavailable_item_type_list,
        "unavailable_sources": _unavailable_source_payloads(unavailable_sources),
        "freshness": freshness,
        "fresh_count": _agent_fresh_count(items, as_of_date),
        "stale_count": _agent_stale_count(items, as_of_date),
        "by_item_type": by_item_type,
    }


def build_agent_external_backfill_coverage_qa(
    date_results: Sequence[AgentExternalBackfillDateResult],
) -> dict[str, Any]:
    dates = [result.as_of_date for result in date_results]
    missing_item_type_dates = {
        item_type: [
            result.as_of_date
            for result in date_results
            if item_type in result.coverage_summary.get("missing_item_types", [])
        ]
        for item_type in ("fundamental", "announcement", "news", "sentiment")
    }
    unavailable_item_type_dates = {
        item_type: [
            result.as_of_date
            for result in date_results
            if item_type in result.coverage_summary.get("unavailable_item_types", [])
        ]
        for item_type in ("fundamental", "announcement", "news", "sentiment")
    }
    stale_dates = [
        result.as_of_date
        for result in date_results
        if result.coverage_summary.get("freshness") in {"stale", "partial"}
    ]
    duplicate_dates = [
        result.as_of_date
        for result in date_results
        if int(result.coverage_summary.get("duplicate_count") or 0) > 0
    ]
    invalid_dates = [result.as_of_date for result in date_results if result.invalid_count > 0]
    blocking_dates = sorted(
        set(
            invalid_dates
            + stale_dates
            + duplicate_dates
            + [
                date
                for dates_for_type in missing_item_type_dates.values()
                for date in dates_for_type
            ]
        )
    )
    return {
        "date_count": len(date_results),
        "dates": dates,
        "ready_dates": [date for date in dates if date not in blocking_dates],
        "blocking_dates": blocking_dates,
        "invalid_dates": invalid_dates,
        "duplicate_dates": duplicate_dates,
        "stale_dates": stale_dates,
        "missing_item_type_dates": missing_item_type_dates,
        "unavailable_item_type_dates": unavailable_item_type_dates,
        "freshness_by_date": {
            result.as_of_date: result.coverage_summary.get("freshness", "unknown")
            for result in date_results
        },
        "stock_count_by_date": {
            result.as_of_date: result.coverage_summary.get("stock_count", 0)
            for result in date_results
        },
        "total_count_by_date": {
            result.as_of_date: result.coverage_summary.get("total_count", 0)
            for result in date_results
        },
    }


def _load_request_input(request: ImportAgentExternalDataRequest) -> _AgentExternalInput | ServiceError:
    if request.source_file is None and request.records is None:
        return ServiceError("VALIDATION_ERROR", "source_file or records is required.")
    if request.source_file is not None and request.records is not None:
        return ServiceError("VALIDATION_ERROR", "choose either source_file or records, not both.")
    if request.records is not None:
        records = _validated_import_records(
            list(request.records),
            default_provider=request.default_provider,
            default_published_date=request.default_published_date,
        )
        if isinstance(records, ServiceError):
            return records
        return _AgentExternalInput(
            records=records,
            unavailable_sources=[],
            as_of_date=_compact_structured_date(request.default_published_date),
        )

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

    return _input_from_payload(payload, request)


def _load_request_records(request: ImportAgentExternalDataRequest) -> list[Mapping[str, Any]] | ServiceError:
    input_result = _load_request_input(request)
    if isinstance(input_result, ServiceError):
        return input_result
    return input_result.records


def _records_from_payload(
    payload: Any,
    request: ImportAgentExternalDataRequest,
) -> list[Mapping[str, Any]] | ServiceError:
    input_result = _input_from_payload(payload, request)
    if isinstance(input_result, ServiceError):
        return input_result
    return input_result.records


def _input_from_payload(
    payload: Any,
    request: ImportAgentExternalDataRequest,
) -> _AgentExternalInput | ServiceError:
    if isinstance(payload, list):
        records = _validated_import_records(
            payload,
            default_provider=request.default_provider,
            default_published_date=request.default_published_date,
        )
        if isinstance(records, ServiceError):
            return records
        return _AgentExternalInput(
            records=records,
            unavailable_sources=[],
            as_of_date=_compact_structured_date(request.default_published_date),
        )
    if not isinstance(payload, Mapping):
        return ServiceError(
            "VALIDATION_ERROR",
            "source_file JSON must be a list, records/items object, or supported structured cache object.",
        )

    contract = _first_text(payload, "provider_file_contract", "contract_version")
    if contract is not None and contract not in VALID_AGENT_EXTERNAL_PROVIDER_FILE_CONTRACTS:
        return ServiceError(
            "UNSUPPORTED_PROVIDER_FILE_CONTRACT",
            f"provider_file_contract must be {AGENT_EXTERNAL_PROVIDER_FILE_CONTRACT}.",
        )

    default_provider = request.default_provider or _first_text(payload, "provider", "source", "data_source")
    default_published_date = request.default_published_date or _first_text(
        payload,
        "published_date",
        "date",
        "as_of_date",
        "trade_date",
    )
    payload_as_of_date = _compact_structured_date(default_published_date)
    unavailable_sources = _unavailable_sources_from_payload(
        payload,
        as_of_date=payload_as_of_date,
        default_provider=default_provider,
    )
    if isinstance(unavailable_sources, ServiceError):
        return unavailable_sources

    if _looks_like_normalized_fixture(payload):
        records = _records_from_normalized_fixture(
            payload,
            default_provider=default_provider,
            default_published_date=default_published_date,
        )
        if isinstance(records, ServiceError):
            return records
        fixture_date = _compact_structured_date(_first_text(payload, "as_of_date", "date", "trade_date"))
        return _AgentExternalInput(records=records, unavailable_sources=unavailable_sources, as_of_date=fixture_date)
    for key in ("records", "items"):
        if key not in payload:
            continue
        records = payload[key]
        if not isinstance(records, list):
            return ServiceError("VALIDATION_ERROR", f"source_file field {key} must be a list.")
        validated = _validated_import_records(
            records,
            default_provider=default_provider,
            default_published_date=default_published_date,
        )
        if isinstance(validated, ServiceError):
            return validated
        return _AgentExternalInput(
            records=validated,
            unavailable_sources=unavailable_sources,
            as_of_date=payload_as_of_date,
        )

    normalized: list[Mapping[str, Any]] = []
    for collection_key, item_type in STRUCTURED_EXTERNAL_COLLECTIONS.items():
        if collection_key not in payload:
            continue
        collection = payload[collection_key]
        if not isinstance(collection, list):
            return ServiceError("VALIDATION_ERROR", f"source_file field {collection_key} must be a list.")
        for record in collection:
            if not isinstance(record, Mapping):
                return ServiceError("VALIDATION_ERROR", "each external data record must be a JSON object.")
            normalized.append(
                _normalize_structured_external_record(
                    record,
                    item_type=item_type,
                    default_provider=default_provider,
                    default_published_date=default_published_date,
                )
            )

    if normalized:
        return _AgentExternalInput(
            records=normalized,
            unavailable_sources=unavailable_sources,
            as_of_date=payload_as_of_date,
        )
    if unavailable_sources:
        return _AgentExternalInput(
            records=[],
            unavailable_sources=unavailable_sources,
            as_of_date=payload_as_of_date,
        )
    return ServiceError(
        "VALIDATION_ERROR",
        "source_file JSON must be a list, an object with records/items, or structured keys like "
        "fundamental_snapshots, announcements, news, or sentiment_snippets.",
    )


def _unavailable_sources_from_payload(
    payload: Mapping[str, Any],
    *,
    as_of_date: str | None,
    default_provider: str | None,
) -> list[_UnavailableAgentExternalSource] | ServiceError:
    raw_sources = payload.get("unavailable_sources", payload.get("unavailable"))
    if raw_sources is None:
        return []
    if not isinstance(raw_sources, list):
        return ServiceError("INVALID_UNAVAILABLE_SOURCE", "unavailable_sources must be a list.")

    unavailable_sources: list[_UnavailableAgentExternalSource] = []
    for index, raw_source in enumerate(raw_sources, start=1):
        if not isinstance(raw_source, Mapping):
            return ServiceError(
                "INVALID_UNAVAILABLE_SOURCE",
                f"unavailable_sources[{index}] must be a JSON object.",
            )
        source_date = _compact_structured_date(
            _first_text(raw_source, "as_of_date", "date", "published_date") or as_of_date
        )
        if as_of_date is not None and (source_date is None or source_date != as_of_date):
            return ServiceError(
                "INVALID_UNAVAILABLE_SOURCE",
                f"unavailable_sources[{index}].as_of_date must match {as_of_date}.",
            )
        item_type = _normalize_fixture_category(_first_text(raw_source, "item_type", "category", "type"))
        if item_type not in VALID_AGENT_EXTERNAL_ITEM_TYPES:
            return ServiceError(
                "INVALID_UNAVAILABLE_SOURCE",
                f"unavailable_sources[{index}].item_type must be one of: "
                f"{', '.join(sorted(VALID_AGENT_EXTERNAL_ITEM_TYPES))}.",
            )
        provider = _first_text(raw_source, "provider", "source", "data_source") or default_provider
        if provider is None:
            return ServiceError(
                "INVALID_UNAVAILABLE_SOURCE",
                f"unavailable_sources[{index}].provider is required when the provider file has no provider.",
            )
        reason = _first_text(raw_source, "reason", "code") or UNAVAILABLE_SOURCE_DEFAULT_REASON
        unavailable_sources.append(
            _UnavailableAgentExternalSource(
                item_type=item_type,
                ts_code=_first_text(raw_source, "ts_code", "code", "symbol"),
                provider=provider,
                reason=reason,
                note=_first_text(raw_source, "note", "message", "summary"),
            )
        )
    return unavailable_sources


def _looks_like_normalized_fixture(payload: Mapping[str, Any]) -> bool:
    return (
        "items" in payload
        and isinstance(payload.get("items"), list)
        and _first_text(payload, "as_of_date") is not None
        and _first_text(payload, "ts_code", "code", "symbol") is not None
    )


def _records_from_normalized_fixture(
    payload: Mapping[str, Any],
    *,
    default_provider: str | None,
    default_published_date: str | None,
) -> list[Mapping[str, Any]] | ServiceError:
    as_of_date = _compact_structured_date(
        _first_text(payload, "as_of_date", "date", "trade_date") or default_published_date
    )
    ts_code = _first_text(payload, "ts_code", "code", "symbol")
    if as_of_date is None or not _is_yyyymmdd(as_of_date):
        return ServiceError("VALIDATION_ERROR", "as_of_date must be a compact YYYYMMDD date.")
    if ts_code is None:
        return ServiceError("VALIDATION_ERROR", "ts_code is required for normalized agent external fixture.")
    items = payload.get("items")
    if not isinstance(items, list):
        return ServiceError("VALIDATION_ERROR", "source_file field items must be a list.")

    normalized: list[Mapping[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            return ServiceError("VALIDATION_ERROR", "each external data record must be a JSON object.")
        normalized.append(
            _normalize_fixture_item(
                item,
                ts_code=ts_code,
                as_of_date=as_of_date,
                default_provider=default_provider,
            )
        )
    return normalized


def _normalize_fixture_item(
    item: Mapping[str, Any],
    *,
    ts_code: str,
    as_of_date: str,
    default_provider: str | None,
) -> dict[str, Any]:
    source = _first_text(item, "source", "provider", "src", "data_source") or default_provider
    category = _normalize_fixture_category(_first_text(item, "category", "item_type", "type"))
    published_date = _compact_structured_date(
        _first_text(item, "published_date", "publish_date", "ann_date", "trade_date", "date") or as_of_date
    )
    payload_value = item.get("payload", {})
    metadata = item.get("metadata")
    metadata_obj = dict(metadata) if isinstance(metadata, Mapping) else {}
    metadata_obj.update(
        {
            "fixture_format": "agent_external_v2",
            "as_of_date": as_of_date,
            "source": source,
            "category": category,
            "payload": payload_value,
        }
    )
    normalized = dict(item)
    normalized["ts_code"] = ts_code
    normalized["_as_of_date"] = as_of_date
    if source:
        normalized["provider"] = source
    if category:
        normalized["item_type"] = category
    if published_date:
        normalized["published_date"] = published_date
    normalized["title"] = _first_text(item, "title", "headline", "name", "subject") or _structured_title(
        normalized,
        category or "research_note",
    )
    normalized["summary"] = _truncate_text(
        _first_text(item, "summary", "abstract", "brief", "snippet", "content", "text", "description")
        or _structured_summary(normalized, category or "research_note"),
        600,
    )
    url = _first_text(item, "url", "link", "source_url")
    if url:
        normalized["url"] = url
    sentiment = _first_text(item, "sentiment", "sentiment_label", "polarity")
    if sentiment:
        normalized["sentiment"] = _normalize_structured_sentiment(sentiment)
    importance = _first_text(item, "importance", "priority", "level")
    if importance:
        normalized["importance"] = _normalize_structured_importance(importance)
    normalized["metadata"] = metadata_obj
    return normalized


def _normalize_fixture_category(value: str | None) -> str | None:
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


def _validated_import_records(
    records: list[Any],
    *,
    default_provider: str | None,
    default_published_date: str | None,
) -> list[Mapping[str, Any]] | ServiceError:
    if not all(isinstance(record, Mapping) for record in records):
        return ServiceError("VALIDATION_ERROR", "each external data record must be a JSON object.")
    return [
        _apply_import_defaults(
            record,
            default_provider=default_provider,
            default_published_date=default_published_date,
        )
        for record in records
    ]


def _apply_import_defaults(
    record: Mapping[str, Any],
    *,
    default_provider: str | None,
    default_published_date: str | None,
) -> dict[str, Any]:
    normalized = dict(record)
    provider = _first_text(normalized, "provider", "source", "src", "data_source") or default_provider
    published_date = _first_text(normalized, "published_date") or default_published_date
    if provider and not _first_text(normalized, "provider"):
        normalized["provider"] = provider
    if published_date and not _first_text(normalized, "published_date"):
        normalized["published_date"] = published_date
    if default_published_date and not _first_text(normalized, "_as_of_date", "as_of_date"):
        normalized["_as_of_date"] = _compact_structured_date(default_published_date)
    return normalized


def _normalize_structured_external_record(
    record: Mapping[str, Any],
    *,
    item_type: str,
    default_provider: str | None,
    default_published_date: str | None,
) -> dict[str, Any]:
    published_date = _first_text(
        record,
        "published_date",
        "publish_date",
        "ann_date",
        "trade_date",
        "date",
        "report_date",
        "end_date",
    )
    provider = _first_text(record, "provider", "source", "src", "data_source") or default_provider
    normalized = dict(record)
    normalized["item_type"] = _first_text(record, "item_type") or item_type
    if provider:
        normalized["provider"] = provider
    if published_date or default_published_date:
        normalized["published_date"] = _compact_structured_date(published_date or default_published_date)
    if default_published_date:
        normalized["_as_of_date"] = _compact_structured_date(default_published_date)
    title = _first_text(record, "title", "headline", "name", "subject") or _structured_title(record, item_type)
    summary = _first_text(
        record,
        "summary",
        "abstract",
        "brief",
        "snippet",
        "content",
        "text",
        "description",
    ) or _structured_summary(record, item_type)
    normalized["title"] = title
    normalized["summary"] = _truncate_text(summary, 600)
    url = _first_text(record, "url", "link", "source_url")
    if url:
        normalized["url"] = url
    sentiment = _first_text(record, "sentiment", "sentiment_label", "polarity")
    if sentiment:
        normalized["sentiment"] = _normalize_structured_sentiment(sentiment)
    importance = _first_text(record, "importance", "priority", "level")
    if importance:
        normalized["importance"] = _normalize_structured_importance(importance)
    normalized["metadata"] = _structured_metadata(record, item_type)
    return normalized


def _first_text(source: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = source.get(key)
        text = _text_value(value)
        if text:
            return text
    return None


def _text_value(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return None


def _compact_structured_date(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        return text
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError:
        return text


def _structured_title(record: Mapping[str, Any], item_type: str) -> str:
    ts_code = _first_text(record, "ts_code", "code", "symbol") or "unknown"
    published_date = _compact_structured_date(
        _first_text(record, "published_date", "publish_date", "ann_date", "trade_date", "date", "report_date", "end_date")
    )
    date_text = f" {published_date}" if published_date else ""
    return {
        "fundamental": f"{ts_code} 基本面快照{date_text}",
        "announcement": f"{ts_code} 公告摘要{date_text}",
        "news": f"{ts_code} 新闻摘要{date_text}",
        "sentiment": f"{ts_code} 情绪摘要{date_text}",
    }.get(item_type, f"{ts_code} 外部资料{date_text}")


def _structured_summary(record: Mapping[str, Any], item_type: str) -> str:
    if item_type == "fundamental":
        metrics = []
        for key, label in (
            ("pe", "PE"),
            ("pe_ttm", "PE-TTM"),
            ("pb", "PB"),
            ("ps", "PS"),
            ("ps_ttm", "PS-TTM"),
            ("dv_ratio", "股息率"),
            ("turnover_rate", "换手率"),
            ("volume_ratio", "量比"),
            ("total_mv", "总市值"),
            ("circ_mv", "流通市值"),
            ("revenue", "营业收入"),
            ("net_profit", "净利润"),
        ):
            if record.get(key) is not None:
                metrics.append(f"{label}={record[key]}")
        return "；".join(metrics) if metrics else "基本面快照已缓存；详细字段见 metadata。"
    if item_type == "sentiment":
        sentiment = _first_text(record, "sentiment", "sentiment_label", "polarity") or "unknown"
        score = _first_text(record, "score", "sentiment_score")
        if score:
            return f"情绪标签 {sentiment}，分数 {score}；详细字段见 metadata。"
        return f"情绪标签 {sentiment}；详细字段见 metadata。"
    return "外部资料摘要已缓存；详细字段见 metadata。"


def _truncate_text(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _normalize_structured_sentiment(value: str) -> str:
    normalized = value.strip().lower()
    mapping = {
        "bullish": "positive",
        "positive": "positive",
        "pos": "positive",
        "利好": "positive",
        "bearish": "negative",
        "negative": "negative",
        "neg": "negative",
        "利空": "negative",
        "neutral": "neutral",
        "中性": "neutral",
        "mixed": "mixed",
        "分歧": "mixed",
        "unknown": "unknown",
    }
    return mapping.get(normalized, normalized if normalized in VALID_AGENT_EXTERNAL_SENTIMENTS else "unknown")


def _normalize_structured_importance(value: str) -> str:
    normalized = value.strip().lower()
    mapping = {
        "high": "high",
        "important": "high",
        "重大": "high",
        "medium": "medium",
        "normal": "medium",
        "中": "medium",
        "low": "low",
        "minor": "low",
        "低": "low",
        "unknown": "unknown",
    }
    return mapping.get(normalized, normalized if normalized in VALID_AGENT_EXTERNAL_IMPORTANCE else "unknown")


def _structured_metadata(record: Mapping[str, Any], item_type: str) -> dict[str, Any]:
    existing = record.get("metadata")
    metadata = dict(existing) if isinstance(existing, Mapping) else {}
    metadata["cache_item_type"] = item_type
    metadata["raw"] = {key: value for key, value in record.items() if key != "metadata"}
    return metadata


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
    provided_source_hash = _optional_text(record, index, "source_hash", issues)

    if published_date and not _is_yyyymmdd(published_date):
        issues.append(
            AgentExternalDataValidationIssue(
                index=index,
                field="published_date",
                code="INVALID_PUBLISHED_DATE",
                message="published_date must be a compact YYYYMMDD date.",
            )
        )
    as_of_date = _optional_as_of_date(record, index, issues)
    if published_date and as_of_date and _is_yyyymmdd(published_date) and published_date > as_of_date:
        issues.append(
            AgentExternalDataValidationIssue(
                index=index,
                field="published_date",
                code="FUTURE_PUBLISHED_DATE",
                message="published_date must not be later than as_of_date.",
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
    if provided_source_hash and provided_source_hash != source_hash:
        return (
            None,
            [
                AgentExternalDataValidationIssue(
                    index=index,
                    field="source_hash",
                    code="SOURCE_HASH_MISMATCH",
                    message="source_hash does not match provider, item type, ts_code, date, title, and summary.",
                )
            ],
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


def _optional_as_of_date(
    record: Mapping[str, Any],
    index: int,
    issues: list[AgentExternalDataValidationIssue],
) -> str | None:
    value = record.get("_as_of_date", record.get("as_of_date"))
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        issues.append(
            AgentExternalDataValidationIssue(
                index=index,
                field="as_of_date",
                code="INVALID_AS_OF_DATE",
                message="as_of_date must be a compact YYYYMMDD date.",
            )
        )
        return None
    compact = _compact_structured_date(value.strip())
    if compact is None or not _is_yyyymmdd(compact):
        issues.append(
            AgentExternalDataValidationIssue(
                index=index,
                field="as_of_date",
                code="INVALID_AS_OF_DATE",
                message="as_of_date must be a compact YYYYMMDD date.",
            )
        )
        return None
    return compact


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


def _preview_backfill_upserts(
    db_path: Path,
    batches: Sequence[_AgentExternalBackfillBatch],
) -> dict[str, tuple[int, int]]:
    counts: dict[str, tuple[int, int]] = {}
    seen_in_batch: set[tuple[str, str]] = set()
    with connect(db_path) as conn:
        for batch in batches:
            insert_count = 0
            update_count = 0
            for item in batch.prepared:
                key = (item.provider, item.source_hash)
                if key in seen_in_batch or _find_existing_item_id(conn, item) is not None:
                    update_count += 1
                else:
                    insert_count += 1
                seen_in_batch.add(key)
            counts[batch.as_of_date] = (insert_count, update_count)
    return counts


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


def _upsert_backfill_items(
    conn: sqlite3.Connection,
    batches: Sequence[_AgentExternalBackfillBatch],
) -> tuple[dict[str, tuple[int, int]], list[int]]:
    counts: dict[str, tuple[int, int]] = {}
    item_ids: list[int] = []
    seen_in_batch: set[tuple[str, str]] = set()

    for batch in batches:
        inserted_count = 0
        updated_count = 0
        for item in batch.prepared:
            key = (item.provider, item.source_hash)
            existing_id = _find_existing_item_id(conn, item)
            item_id = _upsert_external_item(conn, item)
            item_ids.append(item_id)
            if key in seen_in_batch or existing_id is not None:
                updated_count += 1
            else:
                inserted_count += 1
            seen_in_batch.add(key)
        counts[batch.as_of_date] = (inserted_count, updated_count)

    return counts, item_ids


def _coverage_as_of_date(
    request: ImportAgentExternalDataRequest,
    records: list[Mapping[str, Any]],
    *,
    input_as_of_date: str | None = None,
) -> str | None:
    request_date = _compact_structured_date(request.default_published_date)
    if request_date is not None and _is_yyyymmdd(request_date):
        return request_date
    if input_as_of_date is not None and _is_yyyymmdd(input_as_of_date):
        return input_as_of_date
    for record in records:
        value = _compact_structured_date(_first_text(record, "_as_of_date", "as_of_date"))
        if value is not None and _is_yyyymmdd(value):
            return value
    return None


def _load_agent_coverage_items(conn: sqlite3.Connection, as_of_date: str) -> list[_AgentCoverageItem]:
    rows = conn.execute(
        """
        SELECT ts_code, item_type, sentiment, published_date
        FROM agent_external_items
        WHERE published_date <= ?
        """,
        (as_of_date,),
    ).fetchall()
    return [
        _AgentCoverageItem(
            ts_code=str(row["ts_code"]),
            item_type=str(row["item_type"]),
            sentiment=str(row["sentiment"]),
            published_date=str(row["published_date"]),
        )
        for row in rows
    ]


def _agent_sentiment_status(items: Sequence[_AgentCoverageItem], unavailable_item_types: set[str]) -> str:
    sentiment_items = [item for item in items if item.item_type == "sentiment" or item.sentiment != "unknown"]
    if not sentiment_items:
        return "unavailable" if "sentiment" in unavailable_item_types else "missing"
    known_count = sum(1 for item in sentiment_items if item.sentiment != "unknown")
    if known_count == 0:
        return "unavailable" if "sentiment" in unavailable_item_types else "missing"
    if known_count == len(sentiment_items):
        return "available"
    return "partial"


def _agent_freshness(items: Sequence[_AgentCoverageItem], as_of_date: str | None) -> str:
    if not items:
        return "missing"
    if as_of_date is None:
        return "unknown"
    fresh_count = _agent_fresh_count(items, as_of_date)
    if fresh_count == len(items):
        return "fresh"
    if fresh_count == 0:
        return "stale"
    return "partial"


def _agent_fresh_count(items: Sequence[_AgentCoverageItem], as_of_date: str | None) -> int:
    if as_of_date is None:
        return 0
    return sum(1 for item in items if item.published_date == as_of_date)


def _agent_stale_count(items: Sequence[_AgentCoverageItem], as_of_date: str | None) -> int:
    if as_of_date is None:
        return 0
    return sum(1 for item in items if item.published_date < as_of_date)


def _count_agent_by(items: Sequence[_AgentCoverageItem], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = getattr(item, field)
        counts[value] = counts.get(value, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _agent_item_type_status(
    by_item_type: Mapping[str, int],
    item_type: str,
    unavailable_item_types: set[str],
) -> str:
    if by_item_type.get(item_type, 0) > 0:
        return "available"
    if item_type in unavailable_item_types:
        return "unavailable"
    return "missing"


def _unavailable_item_type_set(sources: Sequence[_UnavailableAgentExternalSource]) -> set[str]:
    return {source.item_type for source in sources}


def _unavailable_source_payloads(
    sources: Sequence[_UnavailableAgentExternalSource],
) -> list[dict[str, Any]]:
    return [
        {
            "item_type": source.item_type,
            "ts_code": source.ts_code,
            "provider": source.provider,
            "reason": source.reason,
            "note": source.note,
        }
        for source in sources
    ]


def _validation_failed_result(
    ctx: RequestContext,
    *,
    as_of_date: str | None,
    row_count: int,
    valid_items: list[_PreparedExternalItem],
    invalid_records: list[AgentExternalDataValidationIssue],
    errors: list[ServiceError],
    would_insert_count: int = 0,
    would_update_count: int = 0,
    coverage_summary: dict[str, Any] | None = None,
    unavailable_sources: Sequence[_UnavailableAgentExternalSource] = (),
) -> ServiceResult[ImportAgentExternalDataResult]:
    return ServiceResult(
        status="validation_failed",
        request_id=ctx.request_id,
        data=ImportAgentExternalDataResult(
            as_of_date=as_of_date,
            row_count=row_count,
            valid_count=len(valid_items),
            invalid_count=len({issue.index for issue in invalid_records}),
            would_insert_count=would_insert_count,
            would_update_count=would_update_count,
            inserted_count=0,
            updated_count=0,
            coverage_summary=coverage_summary
            or build_agent_external_coverage_summary(
                [],
                as_of_date,
                unavailable_sources=unavailable_sources,
            ),
            agent_external_item_ids=[],
            unavailable_sources=_unavailable_source_payloads(unavailable_sources),
            invalid_records=invalid_records,
        ),
        errors=errors,
    )


def _agent_backfill_failed_result(
    ctx: RequestContext,
    *,
    db_path: Path,
    file_count: int,
    batches: Sequence[_AgentExternalBackfillBatch],
    invalid_records: list[AgentExternalDataValidationIssue],
    errors: list[ServiceError],
    preview_counts: dict[str, tuple[int, int]],
) -> ServiceResult[BackfillAgentExternalDataResult]:
    return ServiceResult(
        status="validation_failed",
        request_id=ctx.request_id,
        data=_build_agent_backfill_result(
            db_path,
            file_count=file_count,
            batches=batches,
            preview_counts=preview_counts,
            write_counts={date: (0, update_count) for date, (_, update_count) in preview_counts.items()},
            invalid_records=invalid_records,
        ),
        errors=errors,
    )


def _build_agent_backfill_result(
    db_path: Path,
    *,
    file_count: int,
    batches: Sequence[_AgentExternalBackfillBatch],
    preview_counts: dict[str, tuple[int, int]],
    write_counts: dict[str, tuple[int, int]],
    invalid_records: list[AgentExternalDataValidationIssue],
    use_persisted_coverage: bool = False,
) -> BackfillAgentExternalDataResult:
    date_results: list[AgentExternalBackfillDateResult] = []
    with connect(db_path) as conn:
        for batch in batches:
            would_insert_count, would_update_count = preview_counts.get(batch.as_of_date, (0, 0))
            inserted_count, updated_count = write_counts.get(batch.as_of_date, (0, would_update_count))
            coverage_duplicate_count = updated_count if use_persisted_coverage else would_update_count
            if use_persisted_coverage:
                coverage_items = _load_agent_coverage_items(conn, batch.as_of_date)
            else:
                coverage_items = _load_agent_coverage_items(conn, batch.as_of_date)
                coverage_items.extend(
                    _AgentCoverageItem(
                        ts_code=item.ts_code,
                        item_type=item.item_type,
                        sentiment=item.sentiment,
                        published_date=item.published_date,
                    )
                    for item in batch.prepared
                )
            coverage_summary = build_agent_external_coverage_summary(
                coverage_items,
                batch.as_of_date,
                unavailable_sources=batch.unavailable_sources,
                duplicate_count=coverage_duplicate_count,
            )
            date_results.append(
                AgentExternalBackfillDateResult(
                    as_of_date=batch.as_of_date,
                    source_files=[str(path) for path in batch.source_files],
                    row_count=batch.row_count,
                    valid_count=len(batch.prepared),
                    invalid_count=len({issue.index for issue in batch.invalid_records}),
                    would_insert_count=would_insert_count,
                    would_update_count=would_update_count,
                    inserted_count=inserted_count,
                    updated_count=updated_count,
                    coverage_summary=coverage_summary,
                    unavailable_sources=_unavailable_source_payloads(batch.unavailable_sources),
                )
            )

    coverage_qa = build_agent_external_backfill_coverage_qa(date_results)
    return BackfillAgentExternalDataResult(
        file_count=file_count,
        date_count=len(date_results),
        row_count=sum(result.row_count for result in date_results),
        valid_count=sum(result.valid_count for result in date_results),
        invalid_count=sum(result.invalid_count for result in date_results),
        would_insert_count=sum(result.would_insert_count for result in date_results),
        would_update_count=sum(result.would_update_count for result in date_results),
        inserted_count=sum(result.inserted_count for result in date_results),
        updated_count=sum(result.updated_count for result in date_results),
        coverage_qa=coverage_qa,
        date_results=date_results,
        invalid_records=invalid_records,
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
