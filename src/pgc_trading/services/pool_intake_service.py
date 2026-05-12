"""Validate and apply stock pool intake rows before JSON pool mutations."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

from pgc_trading.config import Paths
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult, ServiceWarning


_ROW_KEYS = ("events", "raw_events", "rows", "data")
_TS_CODE_RE = re.compile(r"^(?P<code>\d{6})(?:\.(?P<exchange>SH|SZ|BJ))?$", re.IGNORECASE)


@dataclass(frozen=True)
class PoolIntakeRequest:
    source_file: Path
    pool_file: Path = field(default_factory=lambda: Paths().data_dir / "pgc_pool.json")
    raw_events_file: Path = field(default_factory=lambda: Paths().data_dir / "pgc_raw_events.json")
    output_file: Path | None = None
    encoding: str = "utf-8"


@dataclass(frozen=True)
class PoolIntakeInvalidEntry:
    row_number: int
    code: str | None
    ts_code: str | None
    name: str | None
    reasons: list[str]
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PoolIntakeRowAudit:
    row_number: int
    ts_code: str
    code: str
    name: str
    entry_date: str
    entry_time: str | None
    entry_price: float
    source: str
    reason: str
    sector: str | None
    theme: str | None
    status: str
    pool_duplicate: bool
    raw_duplicate: bool


@dataclass(frozen=True)
class PoolIntakeResult:
    generated_at: str
    mode: str
    source_file: str
    source_hash: str
    pool_file: str
    raw_events_file: str
    output_file: str | None
    input_count: int
    added_count: int
    duplicate_count: int
    invalid_count: int
    pool_rows_before: int
    raw_rows_before: int
    pool_rows_after_preview: int
    raw_rows_after_preview: int
    rows: list[PoolIntakeRowAudit]
    invalid_entries: list[PoolIntakeInvalidEntry]
    guardrails: dict[str, object]


@dataclass(frozen=True)
class _JsonRows:
    path: Path
    document: Any
    rows: list[dict[str, Any]]
    row_key: str | None


@dataclass(frozen=True)
class _NormalizedPoolIntakeRow:
    row_number: int
    ts_code: str
    code: str
    name: str
    entry_date: str
    entry_time: str | None
    entry_price: float
    source: str
    reason: str
    sector: str | None
    theme: str | None
    raw: dict[str, Any]

    @property
    def key(self) -> tuple[str, str, str | None, float]:
        return (self.ts_code, self.entry_date, self.entry_time, self.entry_price)


class PoolIntakeService:
    """Validate and optionally append reviewed stock pool intake rows."""

    def validate_and_apply(
        self,
        request: PoolIntakeRequest,
        ctx: RequestContext,
    ) -> ServiceResult[PoolIntakeResult]:
        validation_errors = _validate_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_result(request, ctx, validation_errors),
                errors=validation_errors,
            )

        try:
            source_rows, source_hash = _load_source_rows(request.source_file, request.encoding)
            pool_doc = _load_json_rows(request.pool_file, request.encoding)
            raw_doc = _load_json_rows(request.raw_events_file, request.encoding)
        except Exception as exc:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                errors=[ServiceError(code="VALIDATION_ERROR", message=str(exc))],
            )

        normalized_rows, invalid_entries = _normalize_rows(source_rows)
        result = _build_result(
            request=request,
            ctx=ctx,
            source_hash=source_hash,
            input_count=len(source_rows),
            pool_rows=pool_doc.rows,
            raw_rows=raw_doc.rows,
            normalized_rows=normalized_rows,
            invalid_entries=invalid_entries,
        )

        status = _status_for_result(result, ctx)
        warnings = _warnings_for_result(result)
        errors = _errors_for_result(result, ctx)
        if request.output_file is not None:
            _write_result_file(request.output_file, result)

        if status not in {"success", "partial_success", "skipped"}:
            return ServiceResult(
                status=status,
                request_id=ctx.request_id,
                data=result,
                warnings=warnings,
                errors=errors,
                lineage={"source_hash": source_hash},
            )

        if ctx.dry_run or result.added_count == 0:
            return ServiceResult(
                status=status,
                request_id=ctx.request_id,
                data=result,
                warnings=warnings,
                lineage={"source_hash": source_hash},
            )

        rows_to_add = [
            row
            for row, audit in zip(normalized_rows, result.rows, strict=True)
            if audit.status == "inserted"
        ]
        _write_json_rows(
            pool_doc,
            [*pool_doc.rows, *[_pool_row_from_intake(row, pool_doc.rows) for row in rows_to_add]],
            request.encoding,
        )
        _write_json_rows(
            raw_doc,
            [*raw_doc.rows, *_raw_rows_from_intake(rows_to_add, raw_doc.rows)],
            request.encoding,
        )

        return ServiceResult(
            status=status,
            request_id=ctx.request_id,
            data=result,
            warnings=warnings,
            lineage={"source_hash": source_hash},
        )


def _validate_request(request: PoolIntakeRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    for field_name, path in (
        ("source_file", request.source_file),
        ("pool_file", request.pool_file),
        ("raw_events_file", request.raw_events_file),
    ):
        if not Path(path).exists():
            errors.append(
                ServiceError(
                    code="VALIDATION_ERROR",
                    message=f"{field_name} does not exist: {path}",
                )
            )
        elif not Path(path).is_file():
            errors.append(
                ServiceError(
                    code="VALIDATION_ERROR",
                    message=f"{field_name} is not a file: {path}",
                )
            )
    if request.output_file is not None:
        for field_name, path in (
            ("source_file", request.source_file),
            ("pool_file", request.pool_file),
            ("raw_events_file", request.raw_events_file),
        ):
            if _same_path(request.output_file, path):
                errors.append(
                    ServiceError(
                        code="VALIDATION_ERROR",
                        message=f"output_file must not overwrite {field_name}: {path}",
                    )
                )
    return errors


def _empty_result(
    request: PoolIntakeRequest,
    ctx: RequestContext,
    errors: list[ServiceError],
) -> PoolIntakeResult:
    return PoolIntakeResult(
        generated_at=_now_utc(),
        mode="dry_run" if ctx.dry_run else "apply",
        source_file=str(request.source_file),
        source_hash="",
        pool_file=str(request.pool_file),
        raw_events_file=str(request.raw_events_file),
        output_file=str(request.output_file) if request.output_file is not None else None,
        input_count=0,
        added_count=0,
        duplicate_count=0,
        invalid_count=len(errors),
        pool_rows_before=0,
        raw_rows_before=0,
        pool_rows_after_preview=0,
        raw_rows_after_preview=0,
        rows=[],
        invalid_entries=[],
        guardrails=_guardrails(ctx),
    )


def _load_source_rows(path: Path, encoding: str) -> tuple[list[dict[str, Any]], str]:
    raw_bytes = Path(path).read_bytes()
    source_hash = hashlib.sha256(raw_bytes).hexdigest()
    text = raw_bytes.decode(encoding)
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        document = json.loads(text)
        return _extract_source_rows(document), source_hash
    if suffix == ".csv":
        return list(csv.DictReader(StringIO(text))), source_hash
    raise ValueError(f"Unsupported pool intake file extension: {Path(path).suffix}")


def _extract_source_rows(document: Any) -> list[dict[str, Any]]:
    if isinstance(document, list):
        return _require_object_rows(document)
    if isinstance(document, dict):
        for key in _ROW_KEYS:
            value = document.get(key)
            if isinstance(value, list):
                rows = _require_object_rows(value)
                return [_with_document_defaults(row, document) for row in rows]
    raise ValueError("Pool intake JSON must be a row list or contain events/raw_events/rows/data.")


def _with_document_defaults(row: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    merged = dict(row)
    for source_key, row_key in (
        ("review_date", "entry_date"),
        ("event_date", "entry_date"),
        ("source", "source"),
        ("reason", "reason"),
        ("sector", "sector"),
        ("theme", "theme"),
        ("source_image", "source_image"),
    ):
        if _optional_text(merged.get(row_key)) is None and document.get(source_key) is not None:
            merged[row_key] = document[source_key]
    return merged


def _require_object_rows(rows: list[Any]) -> list[dict[str, Any]]:
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("Pool intake rows must be JSON objects.")
    return [dict(row) for row in rows]


def _load_json_rows(path: Path, encoding: str) -> _JsonRows:
    document = json.loads(Path(path).read_text(encoding=encoding))
    if isinstance(document, list):
        return _JsonRows(path=path, document=document, rows=[dict(row) for row in document], row_key=None)
    if isinstance(document, dict):
        for key in _ROW_KEYS:
            rows = document.get(key)
            if isinstance(rows, list):
                return _JsonRows(path=path, document=document, rows=[dict(row) for row in rows], row_key=key)
    raise ValueError(f"{path} must be a JSON list or contain events/raw_events/rows/data.")


def _write_json_rows(doc: _JsonRows, rows: list[dict[str, Any]], encoding: str) -> None:
    if doc.row_key is None:
        document = rows
    else:
        document = dict(doc.document)
        document[doc.row_key] = rows
    Path(doc.path).write_text(f"{json.dumps(document, ensure_ascii=False, indent=2)}\n", encoding=encoding)


def _normalize_rows(
    source_rows: list[dict[str, Any]],
) -> tuple[list[_NormalizedPoolIntakeRow], list[PoolIntakeInvalidEntry]]:
    normalized_rows: list[_NormalizedPoolIntakeRow] = []
    invalid_entries: list[PoolIntakeInvalidEntry] = []

    for row_number, row in enumerate(source_rows, start=1):
        reasons: list[str] = []
        ts_code, code, code_reason = _normalize_ts_code(_first_value(row, "ts_code", "stock_code", "code"))
        if code_reason is not None:
            reasons.append(code_reason)

        name = _optional_text(_first_value(row, "name", "stock_name"))
        if name is None:
            reasons.append("name is required")

        entry_date = _normalize_date(_first_value(row, "entry_date", "event_date", "date", "review_date"))
        if entry_date is None:
            reasons.append("entry_date/event_date must be YYYYMMDD or YYYY-MM-DD")

        entry_time = _normalize_time(_first_value(row, "entry_time", "event_time", "time"))
        if entry_time == "":
            reasons.append("entry_time must be HH:MM when provided")

        entry_price = _normalize_price(_first_value(row, "entry_price", "price"))
        if entry_price is None:
            reasons.append("entry_price is required and must be greater than zero")

        source = _optional_text(_first_value(row, "source", "source_sheet", "provider"))
        if source is None:
            reasons.append("source is required")

        reason = _optional_text(_first_value(row, "reason", "intake_reason"))
        if reason is None:
            reasons.append("reason is required")

        sector = _optional_text(_first_value(row, "sector", "industry"))
        theme = _optional_text(row.get("theme"))

        if reasons:
            invalid_entries.append(
                PoolIntakeInvalidEntry(
                    row_number=row_number,
                    code=_optional_text(row.get("code")),
                    ts_code=_optional_text(row.get("ts_code")),
                    name=name,
                    reasons=reasons,
                    payload=_json_payload(row),
                )
            )
            continue

        normalized_rows.append(
            _NormalizedPoolIntakeRow(
                row_number=row_number,
                ts_code=ts_code or "",
                code=code or "",
                name=name or "",
                entry_date=entry_date or "",
                entry_time=entry_time or None,
                entry_price=entry_price or 0.0,
                source=source or "",
                reason=reason or "",
                sector=sector,
                theme=theme,
                raw=dict(row),
            )
        )

    return normalized_rows, invalid_entries


def _build_result(
    *,
    request: PoolIntakeRequest,
    ctx: RequestContext,
    source_hash: str,
    input_count: int,
    pool_rows: list[dict[str, Any]],
    raw_rows: list[dict[str, Any]],
    normalized_rows: list[_NormalizedPoolIntakeRow],
    invalid_entries: list[PoolIntakeInvalidEntry],
) -> PoolIntakeResult:
    pool_keys = {_row_key(row) for row in pool_rows}
    raw_keys = {_row_key(row) for row in raw_rows}
    seen_pool_keys: set[tuple[str, str, str | None, float]] = set()
    seen_raw_keys: set[tuple[str, str, str | None, float]] = set()
    audits: list[PoolIntakeRowAudit] = []
    added_count = 0
    duplicate_count = 0

    for row in normalized_rows:
        key = row.key
        pool_duplicate = key in pool_keys or key in seen_pool_keys
        raw_duplicate = key in raw_keys or key in seen_raw_keys
        duplicate = pool_duplicate or raw_duplicate
        if duplicate:
            status = "duplicate"
            duplicate_count += 1
        else:
            status = "would_insert" if ctx.dry_run else "inserted"
            added_count += 1
            seen_pool_keys.add(key)
            seen_raw_keys.add(key)

        audits.append(
            PoolIntakeRowAudit(
                row_number=row.row_number,
                ts_code=row.ts_code,
                code=row.code,
                name=row.name,
                entry_date=row.entry_date,
                entry_time=row.entry_time,
                entry_price=row.entry_price,
                source=row.source,
                reason=row.reason,
                sector=row.sector,
                theme=row.theme,
                status=status,
                pool_duplicate=pool_duplicate,
                raw_duplicate=raw_duplicate,
            )
        )

    return PoolIntakeResult(
        generated_at=_now_utc(),
        mode="dry_run" if ctx.dry_run else "apply",
        source_file=str(request.source_file),
        source_hash=source_hash,
        pool_file=str(request.pool_file),
        raw_events_file=str(request.raw_events_file),
        output_file=str(request.output_file) if request.output_file is not None else None,
        input_count=input_count,
        added_count=added_count,
        duplicate_count=duplicate_count,
        invalid_count=len(invalid_entries),
        pool_rows_before=len(pool_rows),
        raw_rows_before=len(raw_rows),
        pool_rows_after_preview=len(pool_rows) + added_count,
        raw_rows_after_preview=len(raw_rows) + added_count,
        rows=audits,
        invalid_entries=invalid_entries,
        guardrails=_guardrails(ctx),
    )


def _status_for_result(result: PoolIntakeResult, ctx: RequestContext) -> str:
    if result.invalid_count:
        return "validation_failed"
    if not ctx.dry_run and not ctx.operator:
        return "validation_failed"
    if result.added_count == 0 and result.duplicate_count:
        return "skipped"
    return "success"


def _warnings_for_result(result: PoolIntakeResult) -> list[ServiceWarning]:
    warnings: list[ServiceWarning] = []
    if result.duplicate_count:
        warnings.append(
            ServiceWarning(
                code="POOL_INTAKE_DUPLICATES_SKIPPED",
                message=f"{result.duplicate_count} duplicate intake row(s) were skipped.",
            )
        )
    return warnings


def _errors_for_result(result: PoolIntakeResult, ctx: RequestContext) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if result.invalid_count:
        errors.append(
            ServiceError(
                code="POOL_INTAKE_INVALID",
                message=f"{result.invalid_count} pool intake row(s) failed validation.",
            )
        )
    if not ctx.dry_run and not ctx.operator:
        errors.append(
            ServiceError(
                code="OPERATOR_REQUIRED",
                message="operator is required before applying pool intake JSON mutations.",
            )
        )
    return errors


def _write_result_file(path: Path, result: PoolIntakeResult) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(f"{json.dumps(asdict(result), ensure_ascii=False, indent=2)}\n", encoding="utf-8")


def _pool_row_from_intake(row: _NormalizedPoolIntakeRow, existing_rows: list[dict[str, Any]]) -> dict[str, Any]:
    base = {
        "ts_code": row.ts_code,
        "code": row.code,
        "name": row.name,
        "entry_date": row.entry_date,
        "entry_time": row.entry_time,
        "entry_price": row.entry_price,
        "pnl3_reported": None,
        "status": "watching",
        "days_since": 0,
        "latest_close": None,
        "latest_ret": None,
        "max_high": 0,
        "max_high_date": row.entry_date,
        "current_drawdown": 0,
        "max_3d": 0,
        "industry": row.sector or "",
        "strategy": _optional_text(row.raw.get("strategy")) or row.source,
        "source_sheet": row.source,
        "bull_prob": 0,
        "bull_reason": None,
    }
    return _shape_like_existing(base, existing_rows)


def _raw_rows_from_intake(
    rows: list[_NormalizedPoolIntakeRow],
    existing_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    next_event_id = _next_event_id(existing_rows)
    raw_rows: list[dict[str, Any]] = []
    for offset, row in enumerate(rows):
        base = {
            "event_id": next_event_id + offset,
            "ts_code": row.ts_code,
            "code": row.code,
            "name": row.name,
            "entry_date": row.entry_date,
            "entry_time": row.entry_time,
            "entry_price": row.entry_price,
            "entry_month": row.entry_date[:6],
            "entry_weekday": _weekday_name(row.entry_date),
            "price_bucket": _price_bucket(row.entry_price),
        }
        raw_rows.append(_shape_like_existing(base, existing_rows))
    return raw_rows


def _shape_like_existing(base: dict[str, Any], existing_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not existing_rows:
        return dict(base)

    shaped: dict[str, Any] = {}
    for key in existing_rows[0].keys():
        shaped[key] = base.get(key)
    for key, value in base.items():
        if key not in shaped:
            shaped[key] = value
    return shaped


def _next_event_id(existing_rows: list[dict[str, Any]]) -> int:
    ids = []
    for row in existing_rows:
        try:
            ids.append(int(row.get("event_id")))
        except (TypeError, ValueError):
            continue
    return (max(ids) if ids else 0) + 1


def _row_key(row: dict[str, Any]) -> tuple[str, str, str | None, float] | None:
    ts_code, _, _ = _normalize_ts_code(_first_value(row, "ts_code", "stock_code", "code"))
    entry_date = _normalize_date(_first_value(row, "entry_date", "event_date", "date", "review_date"))
    entry_time = _normalize_time(_first_value(row, "entry_time", "event_time", "time"))
    entry_price = _normalize_price(_first_value(row, "entry_price", "price"))
    if ts_code is None or entry_date is None or entry_time == "" or entry_price is None:
        return None
    return (ts_code, entry_date, entry_time or None, entry_price)


def _normalize_ts_code(value: Any) -> tuple[str | None, str | None, str | None]:
    text = _optional_text(value)
    if text is None:
        return None, None, "stock code is required"
    match = _TS_CODE_RE.fullmatch(text.upper())
    if match is None:
        return None, None, "stock code must be six digits with optional .SH/.SZ/.BJ suffix"
    code = match.group("code")
    exchange = match.group("exchange")
    if exchange is None:
        exchange = _infer_exchange(code)
    if exchange is None:
        return None, None, "stock code exchange could not be inferred"
    return f"{code}.{exchange.upper()}", code, None


def _infer_exchange(code: str) -> str | None:
    if code.startswith(("0", "2", "3")):
        return "SZ"
    if code.startswith(("6", "9")):
        return "SH"
    if code.startswith(("4", "8")):
        return "BJ"
    return None


def _normalize_date(value: Any) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    if re.fullmatch(r"\d{8}", text):
        candidate = text
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        candidate = text.replace("-", "")
    else:
        return None
    try:
        datetime.strptime(candidate, "%Y%m%d")
    except ValueError:
        return None
    return candidate


def _normalize_time(value: Any) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    if not re.fullmatch(r"\d{2}:\d{2}", text):
        return ""
    hour = int(text[:2])
    minute = int(text[3:])
    if hour > 23 or minute > 59:
        return ""
    return text


def _normalize_price(value: Any) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return price


def _weekday_name(entry_date: str) -> str:
    parsed = datetime.strptime(entry_date, "%Y%m%d")
    return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][parsed.weekday()]


def _price_bucket(price: float) -> str:
    if price < 5:
        return "<5"
    if price < 10:
        return "5-10"
    if price < 20:
        return "10-20"
    if price < 50:
        return "20-50"
    if price < 100:
        return "50-100"
    return ">=100"


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if _optional_text(value) is not None:
            return value
    return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _json_payload(row: dict[str, Any]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in row.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            payload[str(key)] = value
        else:
            payload[str(key)] = str(value)
    return payload


def _same_path(left: Path, right: Path) -> bool:
    return Path(left).expanduser().resolve(strict=False) == Path(right).expanduser().resolve(strict=False)


def _guardrails(ctx: RequestContext) -> dict[str, object]:
    return {
        "production_timer_enabled": False,
        "broker_auto_order": False,
        "active_strategy_params_mutated": False,
        "apply_requires_operator": True,
        "operator": ctx.operator,
    }


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
