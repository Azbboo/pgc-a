"""Application service for importing market-review external evidence."""

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


VALID_MARKET_EXTERNAL_SCOPE_TYPES = {"market", "sector", "stock"}
VALID_MARKET_EXTERNAL_ITEM_TYPES = {
    "news",
    "announcement",
    "sentiment",
    "policy",
    "risk_note",
    "research_note",
}
VALID_MARKET_EXTERNAL_SENTIMENTS = {"positive", "neutral", "negative", "mixed", "unknown"}
VALID_MARKET_EXTERNAL_IMPORTANCE = {"low", "medium", "high", "unknown"}
NEWS_LIKE_ITEM_TYPES = {"news", "announcement", "policy", "risk_note", "research_note"}
MARKET_EXTERNAL_PROVIDER_FILE_CONTRACT = "market_external_v1"
VALID_MARKET_EXTERNAL_PROVIDER_FILE_CONTRACTS = {MARKET_EXTERNAL_PROVIDER_FILE_CONTRACT}
SUMMARY_MAX_CHARS = 200


@dataclass(frozen=True)
class ImportMarketExternalDataRequest:
    as_of_date: str
    source_file: Path | None = None
    records: list[Mapping[str, Any]] | None = None
    encoding: str = "utf-8"
    provider: str | None = None


@dataclass(frozen=True)
class MarketExternalDataValidationIssue:
    index: int
    field: str | None
    code: str
    message: str


@dataclass(frozen=True)
class ImportMarketExternalDataResult:
    as_of_date: str
    row_count: int
    valid_count: int
    invalid_count: int
    would_insert_count: int
    inserted_count: int
    duplicate_count: int
    coverage_summary: dict[str, Any]
    coverage_details: dict[str, Any] = field(default_factory=dict)
    provider_file_contract: str = MARKET_EXTERNAL_PROVIDER_FILE_CONTRACT
    market_external_item_ids: list[int] = field(default_factory=list)
    invalid_records: list[MarketExternalDataValidationIssue] = field(default_factory=list)


@dataclass(frozen=True)
class BackfillMarketExternalDataRequest:
    source_files: list[Path]
    encoding: str = "utf-8"


@dataclass(frozen=True)
class MarketExternalBackfillDateResult:
    as_of_date: str
    source_files: list[str]
    row_count: int
    valid_count: int
    invalid_count: int
    would_insert_count: int
    inserted_count: int
    duplicate_count: int
    coverage_summary: dict[str, Any]
    coverage_details: dict[str, Any]


@dataclass(frozen=True)
class BackfillMarketExternalDataResult:
    file_count: int
    date_count: int
    row_count: int
    valid_count: int
    invalid_count: int
    would_insert_count: int
    inserted_count: int
    duplicate_count: int
    coverage_qa: dict[str, Any]
    provider_file_contract: str = MARKET_EXTERNAL_PROVIDER_FILE_CONTRACT
    date_results: list[MarketExternalBackfillDateResult] = field(default_factory=list)
    invalid_records: list[MarketExternalDataValidationIssue] = field(default_factory=list)


@dataclass(frozen=True)
class _PreparedMarketExternalItem:
    as_of_date: str
    scope_type: str
    scope_key: str
    item_type: str
    provider: str
    title: str
    summary: str
    url: str | None
    sentiment: str
    importance: str
    published_date: str
    metadata_json: str
    source_hash: str


@dataclass(frozen=True)
class _CoverageItem:
    scope_type: str
    item_type: str
    sentiment: str
    published_date: str


@dataclass(frozen=True)
class _MarketExternalBackfillBatch:
    as_of_date: str
    source_files: list[Path]
    row_count: int
    prepared: list[_PreparedMarketExternalItem]
    invalid_records: list[MarketExternalDataValidationIssue]


class MarketExternalDataService:
    """Import provider-tagged external evidence without fetching live web data."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def import_external_data(
        self,
        request: ImportMarketExternalDataRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ImportMarketExternalDataResult]:
        as_of_date = _compact_date(request.as_of_date)
        if as_of_date is None or not _is_yyyymmdd(as_of_date):
            return _validation_failed_result(
                ctx,
                as_of_date=request.as_of_date,
                row_count=0,
                valid_items=[],
                invalid_records=[],
                errors=[ServiceError("INVALID_AS_OF_DATE", "as_of_date must be a compact YYYYMMDD date.")],
                coverage_summary=_empty_coverage_summary(),
                coverage_details=_empty_coverage_details(request.as_of_date),
            )

        records_result = _load_request_records(request, as_of_date)
        if isinstance(records_result, ServiceError):
            return _validation_failed_result(
                ctx,
                as_of_date=as_of_date,
                row_count=0,
                valid_items=[],
                invalid_records=[],
                errors=[records_result],
                coverage_summary=self._coverage_for_import(as_of_date, []),
                coverage_details=self._coverage_details_for_import(as_of_date, []),
            )

        records = records_result
        prepared, invalid_records = _prepare_records(as_of_date, records)
        would_insert_count, duplicate_count = (0, 0)
        if prepared:
            would_insert_count, duplicate_count = _preview_inserts(self.db_path, prepared)
        coverage_summary = self._coverage_for_import(as_of_date, prepared, duplicate_count=duplicate_count)
        coverage_details = self._coverage_details_for_import(
            as_of_date,
            prepared,
            duplicate_count=duplicate_count,
        )

        if invalid_records:
            return _validation_failed_result(
                ctx,
                as_of_date=as_of_date,
                row_count=len(records),
                valid_items=prepared,
                invalid_records=invalid_records,
                errors=_service_errors_for_issues(invalid_records),
                would_insert_count=would_insert_count,
                duplicate_count=duplicate_count,
                coverage_summary=coverage_summary,
                coverage_details=coverage_details,
            )

        if ctx.dry_run:
            return ServiceResult(
                status="success",
                request_id=ctx.request_id,
                data=ImportMarketExternalDataResult(
                    as_of_date=as_of_date,
                    row_count=len(records),
                    valid_count=len(prepared),
                    invalid_count=0,
                    would_insert_count=would_insert_count,
                    inserted_count=0,
                    duplicate_count=duplicate_count,
                    coverage_summary=coverage_summary,
                    coverage_details=coverage_details,
                    market_external_item_ids=[],
                    invalid_records=[],
                ),
                lineage={"source_file": str(request.source_file) if request.source_file else None},
            )

        inserted_count = 0
        apply_duplicate_count = 0
        item_ids: list[int] = []
        with connect(self.db_path) as conn:
            conn.execute("BEGIN")
            try:
                inserted_count, apply_duplicate_count, item_ids = _insert_items(conn, prepared)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=ImportMarketExternalDataResult(
                as_of_date=as_of_date,
                row_count=len(records),
                valid_count=len(prepared),
                invalid_count=0,
                would_insert_count=inserted_count,
                inserted_count=inserted_count,
                duplicate_count=apply_duplicate_count,
                coverage_summary=self.summarize_coverage(as_of_date),
                coverage_details=self.summarize_coverage_details(
                    as_of_date,
                    duplicate_count=apply_duplicate_count,
                ),
                market_external_item_ids=item_ids,
                invalid_records=[],
            ),
            created_ids={"market_external_items": item_ids},
            lineage={"source_file": str(request.source_file) if request.source_file else None},
        )

    def backfill_external_data(
        self,
        request: BackfillMarketExternalDataRequest,
        ctx: RequestContext,
    ) -> ServiceResult[BackfillMarketExternalDataResult]:
        source_files = [Path(path) for path in request.source_files]
        if not source_files:
            return _market_backfill_failed_result(
                ctx,
                db_path=self.db_path,
                file_count=0,
                batches=[],
                invalid_records=[],
                errors=[ServiceError("VALIDATION_ERROR", "at least one source_file is required for backfill.")],
                preview_counts={},
            )

        batches_by_date: dict[str, _MarketExternalBackfillBatch] = {}
        errors: list[ServiceError] = []
        for source_file in source_files:
            as_of_date_or_error = _source_file_as_of_date(
                source_file,
                encoding=request.encoding,
                expected_contract=MARKET_EXTERNAL_PROVIDER_FILE_CONTRACT,
            )
            if isinstance(as_of_date_or_error, ServiceError):
                errors.append(as_of_date_or_error)
                continue

            as_of_date = as_of_date_or_error
            records_result = _load_request_records(
                ImportMarketExternalDataRequest(
                    as_of_date=as_of_date,
                    source_file=source_file,
                    encoding=request.encoding,
                ),
                as_of_date,
            )
            if isinstance(records_result, ServiceError):
                errors.append(records_result)
                continue

            records = records_result
            prepared, invalid_records = _prepare_records(as_of_date, records)
            if invalid_records:
                errors.extend(_service_errors_for_issues(invalid_records))

            existing_batch = batches_by_date.get(as_of_date)
            if existing_batch is None:
                batches_by_date[as_of_date] = _MarketExternalBackfillBatch(
                    as_of_date=as_of_date,
                    source_files=[source_file],
                    row_count=len(records),
                    prepared=prepared,
                    invalid_records=invalid_records,
                )
            else:
                batches_by_date[as_of_date] = _MarketExternalBackfillBatch(
                    as_of_date=as_of_date,
                    source_files=[*existing_batch.source_files, source_file],
                    row_count=existing_batch.row_count + len(records),
                    prepared=[*existing_batch.prepared, *prepared],
                    invalid_records=[*existing_batch.invalid_records, *invalid_records],
                )

        batches = [batches_by_date[date] for date in sorted(batches_by_date)]
        preview_counts = _preview_backfill_inserts(self.db_path, batches)
        if errors:
            return _market_backfill_failed_result(
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
                data=_build_market_backfill_result(
                    self.db_path,
                    file_count=len(source_files),
                    batches=batches,
                    preview_counts=preview_counts,
                    inserted_counts={date: (0, 0) for date in preview_counts},
                    invalid_records=[],
                ),
                lineage={"source_files": str(len(source_files))},
            )

        inserted_counts: dict[str, tuple[int, int]] = {}
        item_ids: list[int] = []
        with connect(self.db_path) as conn:
            conn.execute("BEGIN")
            try:
                inserted_counts, item_ids = _insert_backfill_items(conn, batches)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=_build_market_backfill_result(
                self.db_path,
                file_count=len(source_files),
                batches=batches,
                preview_counts=preview_counts,
                inserted_counts=inserted_counts,
                invalid_records=[],
                use_persisted_coverage=True,
            ),
            created_ids={"market_external_items": item_ids},
            lineage={"source_files": str(len(source_files))},
        )

    def summarize_coverage(self, as_of_date: str) -> dict[str, Any]:
        compact_date = _compact_date(as_of_date)
        if compact_date is None or not _is_yyyymmdd(compact_date):
            return _empty_coverage_summary()
        with connect(self.db_path) as conn:
            return build_market_external_coverage_summary(_load_coverage_items(conn, compact_date), compact_date)

    def summarize_coverage_details(self, as_of_date: str, *, duplicate_count: int = 0) -> dict[str, Any]:
        compact_date = _compact_date(as_of_date)
        if compact_date is None or not _is_yyyymmdd(compact_date):
            return _empty_coverage_details(as_of_date)
        with connect(self.db_path) as conn:
            return build_market_external_coverage_details(
                _load_coverage_items(conn, compact_date),
                compact_date,
                duplicate_count=duplicate_count,
            )

    def _coverage_for_import(
        self,
        as_of_date: str,
        prepared: Sequence[_PreparedMarketExternalItem],
        *,
        duplicate_count: int = 0,
    ) -> dict[str, Any]:
        with connect(self.db_path) as conn:
            items = _load_coverage_items(conn, as_of_date)
        items.extend(
            _CoverageItem(item.scope_type, item.item_type, item.sentiment, item.published_date)
            for item in prepared
        )
        return build_market_external_coverage_summary(items, as_of_date, duplicate_count=duplicate_count)

    def _coverage_details_for_import(
        self,
        as_of_date: str,
        prepared: Sequence[_PreparedMarketExternalItem],
        *,
        duplicate_count: int = 0,
    ) -> dict[str, Any]:
        with connect(self.db_path) as conn:
            items = _load_coverage_items(conn, as_of_date)
        items.extend(
            _CoverageItem(item.scope_type, item.item_type, item.sentiment, item.published_date)
            for item in prepared
        )
        return build_market_external_coverage_details(items, as_of_date, duplicate_count=duplicate_count)


def build_market_external_source_hash(
    *,
    provider: str,
    scope_type: str,
    scope_key: str,
    published_date: str,
    title: str,
    summary: str,
) -> str:
    """Build a deterministic hash for market-review evidence de-duplication."""

    fingerprint = {
        "provider": provider,
        "scope_type": scope_type,
        "scope_key": scope_key,
        "published_date": published_date,
        "title": title,
        "summary": summary,
    }
    canonical = json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_market_external_coverage_summary(
    items: Sequence[_CoverageItem],
    as_of_date: str,
    *,
    duplicate_count: int = 0,
) -> dict[str, Any]:
    has_market = any(item.scope_type == "market" for item in items)
    has_sector = any(item.scope_type == "sector" for item in items)
    has_stock = any(item.scope_type == "stock" for item in items)
    known_sentiment_count = sum(1 for item in items if item.sentiment != "unknown")
    has_news = any(item.item_type in NEWS_LIKE_ITEM_TYPES for item in items)

    if not items:
        sentiment_status = "missing"
    elif known_sentiment_count == 0:
        sentiment_status = "missing"
    elif known_sentiment_count == len(items):
        sentiment_status = "available"
    else:
        sentiment_status = "partial"

    return {
        "market": "available" if has_market else "missing",
        "sector": "partial" if has_sector else "missing",
        "stock": "partial" if has_stock else "missing",
        "sentiment": sentiment_status,
        "news": "available" if has_news else "missing",
        "duplicates": "duplicate" if duplicate_count else "none",
        "freshness": _freshness_summary(items, as_of_date),
    }


def build_market_external_coverage_details(
    items: Sequence[_CoverageItem],
    as_of_date: str,
    *,
    duplicate_count: int = 0,
) -> dict[str, Any]:
    freshness = _freshness_summary(items, as_of_date)
    stale_scopes = [scope for scope, status in freshness.items() if status in {"stale", "partial"}]
    return {
        "as_of_date": as_of_date,
        "total_count": len(items),
        "duplicate_count": duplicate_count,
        "missing_scopes": [
            scope
            for scope in ("market", "sector", "stock")
            if not any(item.scope_type == scope for item in items)
        ],
        "stale_scopes": stale_scopes,
        "fresh_count": sum(1 for item in items if item.published_date == as_of_date),
        "stale_count": sum(1 for item in items if item.published_date < as_of_date),
        "by_scope": _count_by(items, "scope_type"),
        "by_item_type": _count_by(items, "item_type"),
        "sentiment": {
            "known_count": sum(1 for item in items if item.sentiment != "unknown"),
            "unknown_count": sum(1 for item in items if item.sentiment == "unknown"),
        },
        "freshness": freshness,
    }


def build_market_external_backfill_coverage_qa(
    date_results: Sequence[MarketExternalBackfillDateResult],
) -> dict[str, Any]:
    dates = [result.as_of_date for result in date_results]
    missing_scope_dates = {
        scope: [
            result.as_of_date
            for result in date_results
            if scope in result.coverage_details.get("missing_scopes", [])
        ]
        for scope in ("market", "sector", "stock")
    }
    stale_scope_dates = {
        scope: [
            result.as_of_date
            for result in date_results
            if scope in result.coverage_details.get("stale_scopes", [])
        ]
        for scope in ("market", "sector", "stock")
    }
    duplicate_dates = [
        result.as_of_date
        for result in date_results
        if int(result.coverage_details.get("duplicate_count") or 0) > 0
    ]
    invalid_dates = [result.as_of_date for result in date_results if result.invalid_count > 0]
    blocking_dates = sorted(
        set(
            invalid_dates
            + duplicate_dates
            + [
                date
                for dates_for_scope in missing_scope_dates.values()
                for date in dates_for_scope
            ]
            + [
                date
                for dates_for_scope in stale_scope_dates.values()
                for date in dates_for_scope
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
        "missing_scope_dates": missing_scope_dates,
        "stale_scope_dates": stale_scope_dates,
        "freshness_by_date": {
            result.as_of_date: result.coverage_summary.get("freshness", {})
            for result in date_results
        },
        "total_count_by_date": {
            result.as_of_date: result.coverage_details.get("total_count", 0)
            for result in date_results
        },
    }


def _load_request_records(
    request: ImportMarketExternalDataRequest,
    as_of_date: str,
) -> list[Mapping[str, Any]] | ServiceError:
    if request.source_file is None and request.records is None:
        return ServiceError("VALIDATION_ERROR", "source_file or records is required.")
    if request.source_file is not None and request.records is not None:
        return ServiceError("VALIDATION_ERROR", "choose either source_file or records, not both.")
    if request.records is not None:
        return _validated_import_records(
            list(request.records),
            as_of_date=as_of_date,
            default_provider=request.provider,
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

    if not isinstance(payload, Mapping):
        return ServiceError("VALIDATION_ERROR", "source_file JSON must be an object with as_of_date, provider, and items.")

    contract = _first_text(payload, "provider_file_contract", "contract_version")
    if contract is not None and contract not in VALID_MARKET_EXTERNAL_PROVIDER_FILE_CONTRACTS:
        return ServiceError(
            "UNSUPPORTED_PROVIDER_FILE_CONTRACT",
            f"provider_file_contract must be {MARKET_EXTERNAL_PROVIDER_FILE_CONTRACT}.",
        )

    fixture_date = _compact_date(_first_text(payload, "as_of_date"))
    if fixture_date is None or not _is_yyyymmdd(fixture_date):
        return ServiceError("INVALID_AS_OF_DATE", "fixture as_of_date must be a compact YYYYMMDD date.")
    if fixture_date != as_of_date:
        return ServiceError(
            "AS_OF_DATE_MISMATCH",
            f"fixture as_of_date {fixture_date} does not match request date {as_of_date}.",
        )

    items = payload.get("items")
    if not isinstance(items, list):
        return ServiceError("VALIDATION_ERROR", "source_file field items must be a list.")

    provider = _first_text(payload, "provider") or request.provider
    return _validated_import_records(items, as_of_date=as_of_date, default_provider=provider)


def _source_file_as_of_date(
    source_file: Path,
    *,
    encoding: str,
    expected_contract: str,
) -> str | ServiceError:
    if not source_file.exists():
        return ServiceError("VALIDATION_ERROR", f"source_file does not exist: {source_file}")
    if not source_file.is_file():
        return ServiceError("VALIDATION_ERROR", f"source_file is not a file: {source_file}")

    try:
        payload = json.loads(source_file.read_text(encoding=encoding))
    except UnicodeDecodeError as exc:
        return ServiceError("VALIDATION_ERROR", f"source_file could not be decoded: {exc}")
    except json.JSONDecodeError as exc:
        return ServiceError("VALIDATION_ERROR", f"source_file is not valid JSON: {exc}")
    if not isinstance(payload, Mapping):
        return ServiceError("VALIDATION_ERROR", "source_file JSON must be an object with as_of_date.")

    contract = _first_text(payload, "provider_file_contract", "contract_version")
    if contract is not None and contract != expected_contract:
        return ServiceError(
            "UNSUPPORTED_PROVIDER_FILE_CONTRACT",
            f"provider_file_contract must be {expected_contract}.",
        )
    as_of_date = _compact_date(_first_text(payload, "as_of_date", "date", "trade_date"))
    if as_of_date is None or not _is_yyyymmdd(as_of_date):
        return ServiceError("INVALID_AS_OF_DATE", "source_file as_of_date must be a compact YYYYMMDD date.")
    return as_of_date


def _validated_import_records(
    records: list[Any],
    *,
    as_of_date: str,
    default_provider: str | None,
) -> list[Mapping[str, Any]] | ServiceError:
    if not all(isinstance(record, Mapping) for record in records):
        return ServiceError("VALIDATION_ERROR", "each market external data item must be a JSON object.")
    return [
        _apply_import_defaults(record, as_of_date=as_of_date, default_provider=default_provider)
        for record in records
    ]


def _apply_import_defaults(
    record: Mapping[str, Any],
    *,
    as_of_date: str,
    default_provider: str | None,
) -> dict[str, Any]:
    normalized = dict(record)
    if not _first_text(normalized, "as_of_date"):
        normalized["as_of_date"] = as_of_date
    if default_provider and not _first_text(normalized, "provider"):
        normalized["provider"] = default_provider
    return normalized


def _prepare_records(
    as_of_date: str,
    records: list[Mapping[str, Any]],
) -> tuple[list[_PreparedMarketExternalItem], list[MarketExternalDataValidationIssue]]:
    prepared: list[_PreparedMarketExternalItem] = []
    invalid_records: list[MarketExternalDataValidationIssue] = []

    for index, record in enumerate(records, start=1):
        item, issues = _prepare_record(as_of_date, index, record)
        invalid_records.extend(issues)
        if item is not None:
            prepared.append(item)

    return prepared, invalid_records


def _prepare_record(
    as_of_date: str,
    index: int,
    record: Mapping[str, Any],
) -> tuple[_PreparedMarketExternalItem | None, list[MarketExternalDataValidationIssue]]:
    issues: list[MarketExternalDataValidationIssue] = []
    record_as_of_date = _optional_date(record, index, "as_of_date", issues, required=False)
    scope_type = _required_text(record, index, "scope_type", issues)
    scope_key = _required_text(record, index, "scope_key", issues)
    item_type = _required_text(record, index, "item_type", issues)
    provider = _required_text(record, index, "provider", issues)
    published_date = _optional_date(record, index, "published_date", issues, required=True)
    source_hash = _required_text(record, index, "source_hash", issues)
    title = _required_text(record, index, "title", issues)
    summary = _required_text(record, index, "summary", issues)

    if record_as_of_date and record_as_of_date != as_of_date:
        issues.append(
            MarketExternalDataValidationIssue(
                index=index,
                field="as_of_date",
                code="AS_OF_DATE_MISMATCH",
                message=f"record as_of_date {record_as_of_date} does not match request date {as_of_date}.",
            )
        )
    if published_date and published_date > as_of_date:
        issues.append(
            MarketExternalDataValidationIssue(
                index=index,
                field="published_date",
                code="FUTURE_PUBLISHED_DATE",
                message="published_date must not be later than as_of_date.",
            )
        )
    if scope_type and scope_type not in VALID_MARKET_EXTERNAL_SCOPE_TYPES:
        issues.append(
            MarketExternalDataValidationIssue(
                index=index,
                field="scope_type",
                code="INVALID_SCOPE_TYPE",
                message=f"scope_type must be one of: {', '.join(sorted(VALID_MARKET_EXTERNAL_SCOPE_TYPES))}.",
            )
        )
    if item_type and item_type not in VALID_MARKET_EXTERNAL_ITEM_TYPES:
        issues.append(
            MarketExternalDataValidationIssue(
                index=index,
                field="item_type",
                code="INVALID_ITEM_TYPE",
                message=f"item_type must be one of: {', '.join(sorted(VALID_MARKET_EXTERNAL_ITEM_TYPES))}.",
            )
        )
    if summary and len(summary) > SUMMARY_MAX_CHARS:
        issues.append(
            MarketExternalDataValidationIssue(
                index=index,
                field="summary",
                code="SUMMARY_TOO_LONG",
                message=f"summary must be {SUMMARY_MAX_CHARS} characters or fewer.",
            )
        )

    url = _optional_text(record, index, "url", issues)
    sentiment = _optional_choice(
        record,
        index,
        "sentiment",
        VALID_MARKET_EXTERNAL_SENTIMENTS,
        default="unknown",
        invalid_code="INVALID_SENTIMENT",
        issues=issues,
    )
    importance = _optional_choice(
        record,
        index,
        "importance",
        VALID_MARKET_EXTERNAL_IMPORTANCE,
        default="unknown",
        invalid_code="INVALID_IMPORTANCE",
        issues=issues,
    )
    metadata_json = _metadata_json(record, index, issues)

    expected_source_hash: str | None = None
    if provider and scope_type and scope_key and published_date and title and summary:
        expected_source_hash = build_market_external_source_hash(
            provider=provider,
            scope_type=scope_type,
            scope_key=scope_key,
            published_date=published_date,
            title=title,
            summary=summary,
        )
        if source_hash and source_hash != expected_source_hash:
            issues.append(
                MarketExternalDataValidationIssue(
                    index=index,
                    field="source_hash",
                    code="SOURCE_HASH_MISMATCH",
                    message="source_hash does not match provider, scope, date, title, and summary.",
                )
            )

    if issues:
        return None, issues

    assert scope_type is not None
    assert scope_key is not None
    assert item_type is not None
    assert provider is not None
    assert published_date is not None
    assert source_hash is not None
    assert title is not None
    assert summary is not None
    assert expected_source_hash is not None
    return (
        _PreparedMarketExternalItem(
            as_of_date=as_of_date,
            scope_type=scope_type,
            scope_key=scope_key,
            item_type=item_type,
            provider=provider,
            title=title,
            summary=summary,
            url=url,
            sentiment=sentiment,
            importance=importance,
            published_date=published_date,
            metadata_json=metadata_json,
            source_hash=expected_source_hash,
        ),
        [],
    )


def _required_text(
    record: Mapping[str, Any],
    index: int,
    field: str,
    issues: list[MarketExternalDataValidationIssue],
) -> str | None:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        issues.append(
            MarketExternalDataValidationIssue(
                index=index,
                field=field,
                code="REQUIRED_FIELD",
                message=f"{field} is required and must be a non-blank string.",
            )
        )
        return None
    return " ".join(value.split())


def _optional_text(
    record: Mapping[str, Any],
    index: int,
    field: str,
    issues: list[MarketExternalDataValidationIssue],
) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    issues.append(
        MarketExternalDataValidationIssue(
            index=index,
            field=field,
            code="INVALID_FIELD",
            message=f"{field} must be a string when provided.",
        )
    )
    return None


def _optional_date(
    record: Mapping[str, Any],
    index: int,
    field: str,
    issues: list[MarketExternalDataValidationIssue],
    *,
    required: bool,
) -> str | None:
    value = record.get(field)
    if value is None:
        if required:
            issues.append(
                MarketExternalDataValidationIssue(
                    index=index,
                    field=field,
                    code="REQUIRED_FIELD",
                    message=f"{field} is required and must be a compact YYYYMMDD date.",
                )
            )
        return None
    if not isinstance(value, str) or not value.strip():
        issues.append(
            MarketExternalDataValidationIssue(
                index=index,
                field=field,
                code="INVALID_DATE",
                message=f"{field} must be a compact YYYYMMDD date.",
            )
        )
        return None
    compact = _compact_date(value)
    if compact is None or not _is_yyyymmdd(compact):
        issues.append(
            MarketExternalDataValidationIssue(
                index=index,
                field=field,
                code="INVALID_DATE",
                message=f"{field} must be a compact YYYYMMDD date.",
            )
        )
        return None
    return compact


def _optional_choice(
    record: Mapping[str, Any],
    index: int,
    field: str,
    choices: set[str],
    *,
    default: str,
    invalid_code: str,
    issues: list[MarketExternalDataValidationIssue],
) -> str:
    value = record.get(field, default)
    if value is None or value == "":
        return default
    if not isinstance(value, str) or value not in choices:
        issues.append(
            MarketExternalDataValidationIssue(
                index=index,
                field=field,
                code=invalid_code,
                message=f"{field} must be one of: {', '.join(sorted(choices))}.",
            )
        )
        return default
    return value


def _metadata_json(
    record: Mapping[str, Any],
    index: int,
    issues: list[MarketExternalDataValidationIssue],
) -> str:
    metadata = record.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, Mapping):
        issues.append(
            MarketExternalDataValidationIssue(
                index=index,
                field="metadata",
                code="INVALID_METADATA",
                message="metadata must be a JSON object.",
            )
        )
        return "{}"
    try:
        normalized = json.loads(json.dumps(metadata, ensure_ascii=False))
        return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        issues.append(
            MarketExternalDataValidationIssue(
                index=index,
                field="metadata",
                code="INVALID_METADATA",
                message=f"metadata must be JSON-serializable: {exc}",
            )
        )
        return "{}"


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


def _first_text(source: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = source.get(key)
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _preview_inserts(db_path: Path, prepared: Sequence[_PreparedMarketExternalItem]) -> tuple[int, int]:
    insert_count = 0
    duplicate_count = 0
    seen_in_batch: set[tuple[str, str]] = set()
    with connect(db_path) as conn:
        for item in prepared:
            key = (item.provider, item.source_hash)
            if key in seen_in_batch or _find_existing_item_id(conn, item) is not None:
                duplicate_count += 1
            else:
                insert_count += 1
            seen_in_batch.add(key)
    return insert_count, duplicate_count


def _preview_backfill_inserts(
    db_path: Path,
    batches: Sequence[_MarketExternalBackfillBatch],
) -> dict[str, tuple[int, int]]:
    counts: dict[str, tuple[int, int]] = {}
    seen_in_batch: set[tuple[str, str]] = set()
    with connect(db_path) as conn:
        for batch in batches:
            insert_count = 0
            duplicate_count = 0
            for item in batch.prepared:
                key = (item.provider, item.source_hash)
                if key in seen_in_batch or _find_existing_item_id(conn, item) is not None:
                    duplicate_count += 1
                else:
                    insert_count += 1
                seen_in_batch.add(key)
            counts[batch.as_of_date] = (insert_count, duplicate_count)
    return counts


def _insert_items(
    conn: sqlite3.Connection,
    prepared: Sequence[_PreparedMarketExternalItem],
) -> tuple[int, int, list[int]]:
    inserted_count = 0
    duplicate_count = 0
    inserted_ids: list[int] = []
    seen_in_batch: set[tuple[str, str]] = set()

    for item in prepared:
        key = (item.provider, item.source_hash)
        existing_id = _find_existing_item_id(conn, item)
        if key in seen_in_batch or existing_id is not None:
            duplicate_count += 1
            seen_in_batch.add(key)
            continue

        item_id = _insert_external_item(conn, item)
        inserted_ids.append(item_id)
        inserted_count += 1
        seen_in_batch.add(key)

    return inserted_count, duplicate_count, inserted_ids


def _insert_backfill_items(
    conn: sqlite3.Connection,
    batches: Sequence[_MarketExternalBackfillBatch],
) -> tuple[dict[str, tuple[int, int]], list[int]]:
    counts: dict[str, tuple[int, int]] = {}
    inserted_ids: list[int] = []
    seen_in_batch: set[tuple[str, str]] = set()

    for batch in batches:
        inserted_count = 0
        duplicate_count = 0
        for item in batch.prepared:
            key = (item.provider, item.source_hash)
            existing_id = _find_existing_item_id(conn, item)
            if key in seen_in_batch or existing_id is not None:
                duplicate_count += 1
                seen_in_batch.add(key)
                continue
            item_id = _insert_external_item(conn, item)
            inserted_ids.append(item_id)
            inserted_count += 1
            seen_in_batch.add(key)
        counts[batch.as_of_date] = (inserted_count, duplicate_count)

    return counts, inserted_ids


def _find_existing_item_id(conn: sqlite3.Connection, item: _PreparedMarketExternalItem) -> int | None:
    row = conn.execute(
        """
        SELECT id
        FROM market_external_items
        WHERE provider = ? AND source_hash = ?
        """,
        (item.provider, item.source_hash),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def _insert_external_item(conn: sqlite3.Connection, item: _PreparedMarketExternalItem) -> int:
    conn.execute(
        """
        INSERT INTO market_external_items
          (
            as_of_date,
            scope_type,
            scope_key,
            item_type,
            provider,
            title,
            summary,
            url,
            sentiment,
            importance,
            published_date,
            metadata_json,
            source_hash
          )
        VALUES
          (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item.as_of_date,
            item.scope_type,
            item.scope_key,
            item.item_type,
            item.provider,
            item.title,
            item.summary,
            item.url,
            item.sentiment,
            item.importance,
            item.published_date,
            item.metadata_json,
            item.source_hash,
        ),
    )
    item_id = _find_existing_item_id(conn, item)
    if item_id is None:  # pragma: no cover - defensive guard around SQLite insert behavior
        raise RuntimeError("market_external_items insert did not return a row.")
    return item_id


def _load_coverage_items(conn: sqlite3.Connection, as_of_date: str) -> list[_CoverageItem]:
    rows = conn.execute(
        """
        SELECT scope_type, item_type, sentiment, published_date
        FROM market_external_items
        WHERE as_of_date = ? AND published_date <= ?
        """,
        (as_of_date, as_of_date),
    ).fetchall()
    return [
        _CoverageItem(
            scope_type=str(row["scope_type"]),
            item_type=str(row["item_type"]),
            sentiment=str(row["sentiment"]),
            published_date=str(row["published_date"]),
        )
        for row in rows
    ]


def _empty_coverage_summary() -> dict[str, Any]:
    return {
        "market": "missing",
        "sector": "missing",
        "stock": "missing",
        "sentiment": "missing",
        "news": "missing",
        "duplicates": "none",
        "freshness": {
            "market": "missing",
            "sector": "missing",
            "stock": "missing",
        },
    }


def _empty_coverage_details(as_of_date: str | None = None) -> dict[str, Any]:
    compact_date = _compact_date(as_of_date) if as_of_date else None
    return {
        "as_of_date": compact_date or as_of_date or "unknown",
        "total_count": 0,
        "duplicate_count": 0,
        "missing_scopes": ["market", "sector", "stock"],
        "stale_scopes": [],
        "fresh_count": 0,
        "stale_count": 0,
        "by_scope": {},
        "by_item_type": {},
        "sentiment": {"known_count": 0, "unknown_count": 0},
        "freshness": {
            "market": "missing",
            "sector": "missing",
            "stock": "missing",
        },
    }


def _freshness_summary(items: Sequence[_CoverageItem], as_of_date: str) -> dict[str, str]:
    return {
        scope_type: _freshness_for_scope(
            [item for item in items if item.scope_type == scope_type],
            as_of_date,
        )
        for scope_type in ("market", "sector", "stock")
    }


def _freshness_for_scope(items: Sequence[_CoverageItem], as_of_date: str) -> str:
    if not items:
        return "missing"
    fresh_count = sum(1 for item in items if item.published_date == as_of_date)
    if fresh_count == len(items):
        return "fresh"
    if fresh_count == 0:
        return "stale"
    return "partial"


def _count_by(items: Sequence[_CoverageItem], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = getattr(item, field)
        counts[value] = counts.get(value, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _validation_failed_result(
    ctx: RequestContext,
    *,
    as_of_date: str,
    row_count: int,
    valid_items: list[_PreparedMarketExternalItem],
    invalid_records: list[MarketExternalDataValidationIssue],
    errors: list[ServiceError],
    coverage_summary: dict[str, Any],
    coverage_details: dict[str, Any],
    would_insert_count: int = 0,
    duplicate_count: int = 0,
) -> ServiceResult[ImportMarketExternalDataResult]:
    return ServiceResult(
        status="validation_failed",
        request_id=ctx.request_id,
        data=ImportMarketExternalDataResult(
            as_of_date=as_of_date,
            row_count=row_count,
            valid_count=len(valid_items),
            invalid_count=len({issue.index for issue in invalid_records}),
            would_insert_count=would_insert_count,
            inserted_count=0,
            duplicate_count=duplicate_count,
            coverage_summary=coverage_summary,
            coverage_details=coverage_details,
            market_external_item_ids=[],
            invalid_records=invalid_records,
        ),
        errors=errors,
    )


def _market_backfill_failed_result(
    ctx: RequestContext,
    *,
    db_path: Path,
    file_count: int,
    batches: Sequence[_MarketExternalBackfillBatch],
    invalid_records: list[MarketExternalDataValidationIssue],
    errors: list[ServiceError],
    preview_counts: dict[str, tuple[int, int]],
) -> ServiceResult[BackfillMarketExternalDataResult]:
    return ServiceResult(
        status="validation_failed",
        request_id=ctx.request_id,
        data=_build_market_backfill_result(
            db_path,
            file_count=file_count,
            batches=batches,
            preview_counts=preview_counts,
            inserted_counts={date: (0, duplicate_count) for date, (_, duplicate_count) in preview_counts.items()},
            invalid_records=invalid_records,
        ),
        errors=errors,
    )


def _build_market_backfill_result(
    db_path: Path,
    *,
    file_count: int,
    batches: Sequence[_MarketExternalBackfillBatch],
    preview_counts: dict[str, tuple[int, int]],
    inserted_counts: dict[str, tuple[int, int]],
    invalid_records: list[MarketExternalDataValidationIssue],
    use_persisted_coverage: bool = False,
) -> BackfillMarketExternalDataResult:
    date_results: list[MarketExternalBackfillDateResult] = []
    with connect(db_path) as conn:
        for batch in batches:
            would_insert_count, preview_duplicate_count = preview_counts.get(batch.as_of_date, (0, 0))
            inserted_count, duplicate_count = inserted_counts.get(batch.as_of_date, (0, preview_duplicate_count))
            coverage_duplicate_count = duplicate_count if use_persisted_coverage else preview_duplicate_count
            if use_persisted_coverage:
                coverage_items = _load_coverage_items(conn, batch.as_of_date)
            else:
                coverage_items = _load_coverage_items(conn, batch.as_of_date)
                coverage_items.extend(
                    _CoverageItem(item.scope_type, item.item_type, item.sentiment, item.published_date)
                    for item in batch.prepared
                )
            coverage_summary = build_market_external_coverage_summary(
                coverage_items,
                batch.as_of_date,
                duplicate_count=coverage_duplicate_count,
            )
            coverage_details = build_market_external_coverage_details(
                coverage_items,
                batch.as_of_date,
                duplicate_count=coverage_duplicate_count,
            )
            date_results.append(
                MarketExternalBackfillDateResult(
                    as_of_date=batch.as_of_date,
                    source_files=[str(path) for path in batch.source_files],
                    row_count=batch.row_count,
                    valid_count=len(batch.prepared),
                    invalid_count=len({issue.index for issue in batch.invalid_records}),
                    would_insert_count=would_insert_count,
                    inserted_count=inserted_count,
                    duplicate_count=coverage_duplicate_count,
                    coverage_summary=coverage_summary,
                    coverage_details=coverage_details,
                )
            )

    coverage_qa = build_market_external_backfill_coverage_qa(date_results)
    return BackfillMarketExternalDataResult(
        file_count=file_count,
        date_count=len(date_results),
        row_count=sum(result.row_count for result in date_results),
        valid_count=sum(result.valid_count for result in date_results),
        invalid_count=sum(result.invalid_count for result in date_results),
        would_insert_count=sum(result.would_insert_count for result in date_results),
        inserted_count=sum(result.inserted_count for result in date_results),
        duplicate_count=sum(result.duplicate_count for result in date_results),
        coverage_qa=coverage_qa,
        date_results=date_results,
        invalid_records=invalid_records,
    )


def _service_errors_for_issues(issues: list[MarketExternalDataValidationIssue]) -> list[ServiceError]:
    return [
        ServiceError(
            code=issue.code,
            message=f"record {issue.index}: {issue.message}",
            entity_type="market_external_record",
            entity_id=issue.index,
        )
        for issue in issues
    ]
