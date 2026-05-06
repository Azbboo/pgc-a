"""Application service for importing raw PGC pool events."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

from pgc_trading.config import Paths
from pgc_trading.ingestion.raw_importer import (
    InvalidRawEvent,
    RawEventRecord,
    RawImportBlocker,
    RawImportPayload,
    parse_raw_events_file,
)
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult, ServiceWarning
from pgc_trading.storage.database import connect


@dataclass(frozen=True)
class ImportRawEventsRequest:
    source_file: Path
    source_type: str = "pgc_pool"
    encoding: str = "utf-8"
    allow_dirty: bool = True


@dataclass(frozen=True)
class ImportRawEventsResult:
    raw_import_batch_id: int | None
    row_count: int
    valid_count: int
    dirty_count: int
    duplicate_count: int
    invalid_events: list[InvalidRawEvent]


class RawIngestionService:
    """Import raw events without touching market, feature, signal, or portfolio layers."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def import_raw_events(
        self,
        request: ImportRawEventsRequest,
        ctx: RequestContext,
    ) -> ServiceResult[ImportRawEventsResult]:
        validation_errors = self._validate_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=ImportRawEventsResult(
                    raw_import_batch_id=None,
                    row_count=0,
                    valid_count=0,
                    dirty_count=0,
                    duplicate_count=0,
                    invalid_events=[],
                ),
                errors=validation_errors,
            )

        try:
            payload = parse_raw_events_file(
                request.source_file,
                source_type=request.source_type,
                encoding=request.encoding,
                allow_dirty=request.allow_dirty,
            )
        except Exception as exc:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=ImportRawEventsResult(
                    raw_import_batch_id=None,
                    row_count=0,
                    valid_count=0,
                    dirty_count=0,
                    duplicate_count=0,
                    invalid_events=[],
                ),
                errors=[ServiceError(code="VALIDATION_ERROR", message=str(exc))],
            )

        if payload.blockers:
            return self._blocked_result(request, ctx, payload)

        if ctx.dry_run:
            duplicate_count = self._preview_duplicate_count(payload.events)
            return ServiceResult(
                status="partial_success" if payload.dirty_count else "success",
                request_id=ctx.request_id,
                data=ImportRawEventsResult(
                    raw_import_batch_id=None,
                    row_count=payload.row_count,
                    valid_count=payload.valid_count,
                    dirty_count=payload.dirty_count,
                    duplicate_count=duplicate_count,
                    invalid_events=list(payload.invalid_events),
                ),
                warnings=_warnings_for_payload(payload),
                lineage={"source_hash": payload.source_hash},
            )

        with connect(self.db_path) as conn:
            conn.execute("BEGIN")
            try:
                previous = _completed_operation_result(conn, ctx)
                if previous is not None:
                    conn.commit()
                    return previous

                operation_id = _reserve_operation(conn, request, ctx)
                existing_batch = _find_import_batch(conn, payload.source_hash)
                if existing_batch is not None:
                    result = _result_for_existing_batch(conn, existing_batch, payload)
                    service_result = ServiceResult(
                        status="skipped",
                        request_id=ctx.request_id,
                        data=result,
                        created_ids={"raw_import_batch_id": result.raw_import_batch_id}
                        if result.raw_import_batch_id is not None
                        else {},
                        lineage={
                            "raw_import_batch_id": result.raw_import_batch_id,
                            "source_hash": payload.source_hash,
                        },
                    )
                    _finish_operation(conn, operation_id, "skipped", service_result)
                    conn.commit()
                    return service_result

                batch_id = _insert_import_batch(conn, request, payload)
                duplicate_count, raw_event_ids, inserted_raw_event_ids = _write_raw_events(
                    conn,
                    batch_id,
                    payload.events,
                )
                _write_dirty_quality_events(conn, raw_event_ids, payload)

                result = ImportRawEventsResult(
                    raw_import_batch_id=batch_id,
                    row_count=payload.row_count,
                    valid_count=payload.valid_count,
                    dirty_count=payload.dirty_count,
                    duplicate_count=duplicate_count,
                    invalid_events=list(payload.invalid_events),
                )
                status = "partial_success" if payload.dirty_count else "success"
                service_result = ServiceResult(
                    status=status,
                    request_id=ctx.request_id,
                    data=result,
                    created_ids={
                        "raw_import_batch_id": batch_id,
                        "raw_event_ids": inserted_raw_event_ids,
                    },
                    warnings=_warnings_for_payload(payload),
                    lineage={
                        "raw_import_batch_id": batch_id,
                        "source_hash": payload.source_hash,
                    },
                )
                _write_domain_event(conn, batch_id, result, ctx)
                _finish_operation(conn, operation_id, _operation_status(status), service_result)
                conn.commit()
                return service_result
            except Exception:
                conn.rollback()
                raise

    def _blocked_result(
        self,
        request: ImportRawEventsRequest,
        ctx: RequestContext,
        payload: RawImportPayload,
    ) -> ServiceResult[ImportRawEventsResult]:
        errors = [_service_error_for_blockers(payload.blockers)]
        status = _blocked_status(payload.blockers)
        result = ImportRawEventsResult(
            raw_import_batch_id=None,
            row_count=payload.row_count,
            valid_count=0,
            dirty_count=0,
            duplicate_count=0,
            invalid_events=list(payload.invalid_events),
        )
        service_result = ServiceResult(
            status=status,
            request_id=ctx.request_id,
            data=result,
            errors=errors,
            lineage={"source_hash": payload.source_hash},
        )
        if ctx.dry_run:
            return service_result

        with connect(self.db_path) as conn:
            conn.execute("BEGIN")
            try:
                previous = _completed_operation_result(conn, ctx)
                if previous is not None:
                    conn.commit()
                    return previous
                operation_id = _reserve_operation(conn, request, ctx)
                _write_blocker_quality_events(conn, request, payload)
                _finish_operation(conn, operation_id, "failed", service_result)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return service_result

    def _validate_request(self, request: ImportRawEventsRequest) -> list[ServiceError]:
        errors: list[ServiceError] = []
        if not request.source_type.strip():
            errors.append(ServiceError(code="VALIDATION_ERROR", message="source_type is required."))
        if not Path(request.source_file).exists():
            errors.append(
                ServiceError(
                    code="VALIDATION_ERROR",
                    message=f"source_file does not exist: {request.source_file}",
                )
            )
        elif not Path(request.source_file).is_file():
            errors.append(
                ServiceError(
                    code="VALIDATION_ERROR",
                    message=f"source_file is not a file: {request.source_file}",
                )
            )
        return errors

    def _preview_duplicate_count(self, events: tuple[RawEventRecord, ...]) -> int:
        seen: set[tuple[str, str, str | None, float]] = set()
        unique_events: list[RawEventRecord] = []
        duplicates = 0
        for event in events:
            if event.key in seen:
                duplicates += 1
            else:
                seen.add(event.key)
                unique_events.append(event)

        if not self.db_path.exists():
            return duplicates

        with connect(self.db_path) as conn:
            for event in unique_events:
                if _find_raw_event(conn, event) is not None:
                    duplicates += 1
        return duplicates


def _insert_import_batch(
    conn: sqlite3.Connection,
    request: ImportRawEventsRequest,
    payload: RawImportPayload,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO raw_import_batches
          (source_file, source_hash, source_type, row_count, valid_count, dirty_count, status, notes)
        VALUES
          (?, ?, ?, ?, ?, ?, 'completed', ?)
        """,
        (
            str(request.source_file),
            payload.source_hash,
            request.source_type,
            payload.row_count,
            payload.valid_count,
            payload.dirty_count,
            _json_dumps({"allow_dirty": request.allow_dirty}),
        ),
    )
    return int(cursor.lastrowid)


def _write_raw_events(
    conn: sqlite3.Connection,
    batch_id: int,
    events: tuple[RawEventRecord, ...],
) -> tuple[int, dict[int, int], list[int]]:
    duplicate_count = 0
    raw_event_ids: dict[int, int] = {}
    inserted_raw_event_ids: list[int] = []

    for event in events:
        existing = _find_raw_event(conn, event)
        if existing is not None:
            duplicate_count += 1
            raw_event_id = int(existing["id"])
            if not event.is_valid:
                conn.execute(
                    """
                    UPDATE raw_events
                    SET is_valid = 0,
                        invalid_reason = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (event.invalid_reason, raw_event_id),
                )
            raw_event_ids[event.row_number] = raw_event_id
            continue

        cursor = conn.execute(
            """
            INSERT INTO raw_events
              (
                import_batch_id,
                ts_code,
                code,
                name,
                entry_date,
                entry_time,
                entry_price,
                source,
                is_valid,
                invalid_reason
              )
            VALUES
              (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                event.ts_code,
                event.code,
                event.name,
                event.entry_date,
                event.entry_time,
                event.entry_price,
                event.source,
                1 if event.is_valid else 0,
                event.invalid_reason,
            ),
        )
        raw_event_id = int(cursor.lastrowid)
        raw_event_ids[event.row_number] = raw_event_id
        inserted_raw_event_ids.append(raw_event_id)

    notes = _json_dumps({"duplicate_count": duplicate_count})
    conn.execute("UPDATE raw_import_batches SET notes = ? WHERE id = ?", (notes, batch_id))
    return duplicate_count, raw_event_ids, inserted_raw_event_ids


def _write_dirty_quality_events(
    conn: sqlite3.Connection,
    raw_event_ids: dict[int, int],
    payload: RawImportPayload,
) -> None:
    for invalid_event in payload.invalid_events:
        raw_event_id = raw_event_ids.get(invalid_event.row_number)
        conn.execute(
            """
            INSERT INTO data_quality_events
              (
                layer,
                severity,
                event_code,
                entity_type,
                entity_id,
                ts_code,
                trade_date,
                message,
                payload_json
              )
            VALUES
              ('raw', 'warning', ?, 'raw_event', ?, ?, ?, ?, ?)
            """,
            (
                invalid_event.event_code,
                raw_event_id,
                invalid_event.ts_code,
                invalid_event.entry_date,
                "Known dirty raw event marked invalid.",
                _json_dumps(invalid_event),
            ),
        )


def _write_blocker_quality_events(
    conn: sqlite3.Connection,
    request: ImportRawEventsRequest,
    payload: RawImportPayload,
) -> None:
    for blocker in payload.blockers:
        conn.execute(
            """
            INSERT INTO data_quality_events
              (
                layer,
                severity,
                event_code,
                entity_type,
                message,
                payload_json
              )
            VALUES
              ('raw', 'blocker', ?, 'raw_import', ?, ?)
            """,
            (
                blocker.code,
                blocker.message,
                _json_dumps(
                    {
                        "source_file": str(request.source_file),
                        "source_hash": payload.source_hash,
                        "row_number": blocker.row_number,
                        "fields": list(blocker.fields),
                        "payload": blocker.payload,
                    }
                ),
            ),
        )


def _find_import_batch(conn: sqlite3.Connection, source_hash: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, row_count, valid_count, dirty_count
        FROM raw_import_batches
        WHERE source_hash = ?
        """,
        (source_hash,),
    ).fetchone()


def _result_for_existing_batch(
    conn: sqlite3.Connection,
    batch: sqlite3.Row,
    payload: RawImportPayload,
) -> ImportRawEventsResult:
    invalid_events = [
        InvalidRawEvent(
            row_number=0,
            ts_code=row["ts_code"],
            name=row["name"],
            entry_date=row["entry_date"],
            reason=row["invalid_reason"] or "invalid",
        )
        for row in conn.execute(
            """
            SELECT ts_code, name, entry_date, invalid_reason
            FROM raw_events
            WHERE import_batch_id = ? AND is_valid = 0
            ORDER BY id
            """,
            (batch["id"],),
        ).fetchall()
    ]
    return ImportRawEventsResult(
        raw_import_batch_id=int(batch["id"]),
        row_count=int(batch["row_count"]),
        valid_count=int(batch["valid_count"]),
        dirty_count=int(batch["dirty_count"]),
        duplicate_count=payload.row_count,
        invalid_events=invalid_events,
    )


def _find_raw_event(conn: sqlite3.Connection, event: RawEventRecord) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, is_valid, invalid_reason
        FROM raw_events
        WHERE ts_code = ?
          AND entry_date = ?
          AND ((entry_time IS NULL AND ? IS NULL) OR entry_time = ?)
          AND entry_price = ?
        """,
        (event.ts_code, event.entry_date, event.entry_time, event.entry_time, event.entry_price),
    ).fetchone()


def _write_domain_event(
    conn: sqlite3.Connection,
    batch_id: int,
    result: ImportRawEventsResult,
    ctx: RequestContext,
) -> None:
    conn.execute(
        """
        INSERT INTO domain_events
          (event_type, entity_type, entity_id, payload_json, source, operator)
        VALUES
          ('raw_import_completed', 'raw_import_batch', ?, ?, ?, ?)
        """,
        (
            batch_id,
            _json_dumps(result),
            _domain_event_source(ctx.source),
            ctx.operator,
        ),
    )


def _reserve_operation(
    conn: sqlite3.Connection,
    request: ImportRawEventsRequest,
    ctx: RequestContext,
) -> int | None:
    if not ctx.idempotency_key:
        return None

    request_json = _json_dumps(
        {
            "source_file": str(request.source_file),
            "source_type": request.source_type,
            "encoding": request.encoding,
            "allow_dirty": request.allow_dirty,
            "dry_run": ctx.dry_run,
        }
    )
    existing = conn.execute(
        "SELECT id FROM operation_requests WHERE idempotency_key = ?",
        (ctx.idempotency_key,),
    ).fetchone()
    if existing is not None:
        conn.execute(
            """
            UPDATE operation_requests
            SET status = 'started',
                request_id = ?,
                request_json = ?,
                response_json = NULL,
                error_code = NULL,
                error_message = NULL,
                operator = ?,
                started_at = CURRENT_TIMESTAMP,
                finished_at = NULL
            WHERE id = ?
            """,
            (ctx.request_id, request_json, ctx.operator, existing["id"]),
        )
        return int(existing["id"])

    cursor = conn.execute(
        """
        INSERT INTO operation_requests
          (idempotency_key, request_id, operation_type, status, request_json, operator)
        VALUES
          (?, ?, 'raw_import', 'started', ?, ?)
        """,
        (ctx.idempotency_key, ctx.request_id, request_json, ctx.operator),
    )
    return int(cursor.lastrowid)


def _completed_operation_result(
    conn: sqlite3.Connection,
    ctx: RequestContext,
) -> ServiceResult[ImportRawEventsResult] | None:
    if not ctx.idempotency_key:
        return None
    row = conn.execute(
        """
        SELECT response_json
        FROM operation_requests
        WHERE idempotency_key = ?
          AND status IN ('success', 'partial_success', 'skipped')
          AND response_json IS NOT NULL
        """,
        (ctx.idempotency_key,),
    ).fetchone()
    if row is None:
        return None
    return _service_result_from_json(row["response_json"], ctx.request_id)


def _finish_operation(
    conn: sqlite3.Connection,
    operation_id: int | None,
    status: str,
    result: ServiceResult[ImportRawEventsResult],
) -> None:
    if operation_id is None:
        return
    first_error = result.errors[0] if result.errors else None
    conn.execute(
        """
        UPDATE operation_requests
        SET status = ?,
            response_json = ?,
            error_code = ?,
            error_message = ?,
            finished_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            status,
            _json_dumps(result),
            first_error.code if first_error else None,
            first_error.message if first_error else None,
            operation_id,
        ),
    )


def _warnings_for_payload(payload: RawImportPayload) -> list[ServiceWarning]:
    if not payload.invalid_events:
        return []
    return [
        ServiceWarning(
            code="RAW_DIRTY_EVENTS_MARKED_INVALID",
            message=f"{len(payload.invalid_events)} raw event(s) were marked invalid.",
            severity="warning",
        )
    ]


def _service_error_for_blockers(blockers: tuple[RawImportBlocker, ...]) -> ServiceError:
    fields = sorted({field for blocker in blockers for field in blocker.fields})
    if any(blocker.code == "RAW_FORBIDDEN_FIELDS" for blocker in blockers):
        suffix = f": {', '.join(fields)}" if fields else ""
        return ServiceError(
            code="FUTURE_DATA_DETECTED",
            message=f"Raw import contains forbidden fields{suffix}.",
            severity="blocker",
        )
    if any(blocker.code == "RAW_DIRTY_EVENT_BLOCKED" for blocker in blockers):
        return ServiceError(
            code="DATA_QUALITY_BLOCKED",
            message="Raw import contains known dirty events and allow_dirty is false.",
            severity="blocker",
        )
    return ServiceError(
        code="VALIDATION_ERROR",
        message="Raw import contains invalid rows.",
        severity="error",
    )


def _blocked_status(blockers: tuple[RawImportBlocker, ...]) -> str:
    if any(blocker.code in {"RAW_FORBIDDEN_FIELDS", "RAW_DIRTY_EVENT_BLOCKED"} for blocker in blockers):
        return "blocked"
    return "validation_failed"


def _operation_status(status: str) -> str:
    if status == "partial_success":
        return "partial_success"
    if status == "skipped":
        return "skipped"
    return "success"


def _domain_event_source(source: str) -> str:
    if source in {"manual", "scheduler", "migration"}:
        return source
    return "system"


def _service_result_from_json(
    response_json: str,
    request_id: str | None,
) -> ServiceResult[ImportRawEventsResult]:
    payload = json.loads(response_json)
    data = payload.get("data")
    result = None
    if data is not None:
        result = ImportRawEventsResult(
            raw_import_batch_id=data.get("raw_import_batch_id"),
            row_count=int(data.get("row_count", 0)),
            valid_count=int(data.get("valid_count", 0)),
            dirty_count=int(data.get("dirty_count", 0)),
            duplicate_count=int(data.get("duplicate_count", 0)),
            invalid_events=[
                InvalidRawEvent(
                    row_number=int(item.get("row_number", 0)),
                    ts_code=item.get("ts_code"),
                    name=item.get("name"),
                    entry_date=item.get("entry_date"),
                    reason=item.get("reason", "invalid"),
                    event_code=item.get("event_code", "RAW_KNOWN_DIRTY_EVENT"),
                )
                for item in data.get("invalid_events", [])
            ],
        )
    return ServiceResult(
        status=payload["status"],
        request_id=request_id,
        data=result,
        created_ids=payload.get("created_ids", {}),
        warnings=[
            ServiceWarning(
                code=item["code"],
                message=item["message"],
                entity_type=item.get("entity_type"),
                entity_id=item.get("entity_id"),
                severity=item.get("severity", "warning"),
            )
            for item in payload.get("warnings", [])
        ],
        errors=[
            ServiceError(
                code=item["code"],
                message=item["message"],
                entity_type=item.get("entity_type"),
                entity_id=item.get("entity_id"),
                severity=item.get("severity", "error"),
            )
            for item in payload.get("errors", [])
        ],
        lineage=payload.get("lineage", {}),
    )


def _json_dumps(value: Any) -> str:
    return json.dumps(_to_jsonable(value), ensure_ascii=False, sort_keys=True)


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value
