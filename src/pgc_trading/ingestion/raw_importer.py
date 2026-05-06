"""Parse and validate raw PGC event files before database writes."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any


ALLOWED_RAW_FIELDS = {
    "ts_code",
    "code",
    "name",
    "entry_date",
    "entry_time",
    "entry_price",
    "source",
}

# Metadata emitted by the current raw-only research script. These fields are
# allowed in source files but are intentionally not persisted to raw_events.
IGNORED_METADATA_FIELDS = {
    "event_id",
    "entry_month",
    "entry_weekday",
    "price_bucket",
}

FORBIDDEN_RAW_FIELDS = {
    "agent_action",
    "agent_confidence",
    "agent_decision",
    "backtest_result",
    "bull_prob",
    "bull_reason",
    "current_drawdown",
    "daily_pick",
    "day_pct",
    "days_since",
    "discard_reason",
    "exit_reason",
    "future_ret",
    "industry",
    "latest_close",
    "latest_ret",
    "limit_up_stars",
    "main_attack",
    "max_3d",
    "max_future_high",
    "max_high",
    "max_high_date",
    "pnl",
    "pnl3_reported",
    "ret",
    "return",
    "score",
    "signal_score",
    "source_sheet",
    "status",
    "strategy",
    "t1_ret",
    "t2_ret",
    "t3_ret",
    "t5_ret",
    "t10_ret",
    "t20_ret",
    "trade_id",
    "trade_status",
    "win_label",
}

KNOWN_DIRTY_NAMES = {"隆化科技", "隆华科技"}
KNOWN_DIRTY_TS_CODES = {"300263.SZ"}
KNOWN_DIRTY_REASON = "known_dirty_longhua_technology"


@dataclass(frozen=True)
class RawImportBlocker:
    code: str
    message: str
    row_number: int | None = None
    fields: tuple[str, ...] = ()
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class InvalidRawEvent:
    row_number: int
    ts_code: str | None
    name: str | None
    entry_date: str | None
    reason: str
    event_code: str = "RAW_KNOWN_DIRTY_EVENT"


@dataclass(frozen=True)
class RawEventRecord:
    row_number: int
    ts_code: str
    code: str | None
    name: str
    entry_date: str
    entry_time: str | None
    entry_price: float
    source: str
    is_valid: bool = True
    invalid_reason: str | None = None

    @property
    def key(self) -> tuple[str, str, str | None, float]:
        return (self.ts_code, self.entry_date, self.entry_time, self.entry_price)


@dataclass(frozen=True)
class RawImportPayload:
    source_file: Path
    source_hash: str
    row_count: int
    events: tuple[RawEventRecord, ...] = ()
    invalid_events: tuple[InvalidRawEvent, ...] = ()
    blockers: tuple[RawImportBlocker, ...] = ()

    @property
    def valid_count(self) -> int:
        return sum(1 for event in self.events if event.is_valid)

    @property
    def dirty_count(self) -> int:
        return sum(1 for event in self.events if not event.is_valid)


def parse_raw_events_file(
    source_file: Path,
    *,
    source_type: str = "pgc_pool",
    encoding: str = "utf-8",
    allow_dirty: bool = True,
) -> RawImportPayload:
    """Read, parse, and validate a raw JSON or CSV event file."""

    path = Path(source_file)
    raw_bytes = path.read_bytes()
    source_hash = hashlib.sha256(raw_bytes).hexdigest()
    text = raw_bytes.decode(encoding)
    rows = _load_rows(path, text)
    row_count = len(rows)

    field_names = _field_names(rows)
    forbidden_fields = _forbidden_fields(field_names)
    if forbidden_fields:
        return RawImportPayload(
            source_file=path,
            source_hash=source_hash,
            row_count=row_count,
            blockers=(
                RawImportBlocker(
                    code="RAW_FORBIDDEN_FIELDS",
                    message="Raw import contains fields outside the raw event boundary.",
                    fields=forbidden_fields,
                    payload={"fields": list(forbidden_fields)},
                ),
            ),
        )

    events: list[RawEventRecord] = []
    invalid_events: list[InvalidRawEvent] = []
    blockers: list[RawImportBlocker] = []

    for row_number, row in enumerate(rows, start=1):
        normalized, row_blockers = _normalize_row(row, row_number, source_type)
        blockers.extend(row_blockers)
        if normalized is None:
            continue

        dirty_reason = _dirty_reason(normalized)
        if dirty_reason and not allow_dirty:
            blockers.append(
                RawImportBlocker(
                    code="RAW_DIRTY_EVENT_BLOCKED",
                    message="Raw import contains a known dirty event and allow_dirty is false.",
                    row_number=row_number,
                    payload={
                        "ts_code": normalized.ts_code,
                        "name": normalized.name,
                        "entry_date": normalized.entry_date,
                        "reason": dirty_reason,
                    },
                )
            )
            continue
        if dirty_reason:
            normalized = RawEventRecord(
                row_number=normalized.row_number,
                ts_code=normalized.ts_code,
                code=normalized.code,
                name=normalized.name,
                entry_date=normalized.entry_date,
                entry_time=normalized.entry_time,
                entry_price=normalized.entry_price,
                source=normalized.source,
                is_valid=False,
                invalid_reason=dirty_reason,
            )
            invalid_events.append(
                InvalidRawEvent(
                    row_number=row_number,
                    ts_code=normalized.ts_code,
                    name=normalized.name,
                    entry_date=normalized.entry_date,
                    reason=dirty_reason,
                )
            )
        events.append(normalized)

    return RawImportPayload(
        source_file=path,
        source_hash=source_hash,
        row_count=row_count,
        events=tuple(events),
        invalid_events=tuple(invalid_events),
        blockers=tuple(blockers),
    )


def _load_rows(path: Path, text: str) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        document = json.loads(text)
        rows = _extract_json_rows(document)
    elif suffix == ".csv":
        rows = list(csv.DictReader(StringIO(text)))
    else:
        raise ValueError(f"Unsupported raw import file extension: {path.suffix}")

    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("Raw import file must contain object rows.")
    return [dict(row) for row in rows]


def _extract_json_rows(document: Any) -> list[dict[str, Any]]:
    if isinstance(document, list):
        return document
    if isinstance(document, dict):
        for key in ("events", "raw_events", "rows", "data"):
            value = document.get(key)
            if isinstance(value, list):
                return value
    raise ValueError("Raw JSON import must be a row list or contain events/raw_events/rows/data.")


def _field_names(rows: list[dict[str, Any]]) -> set[str]:
    fields: set[str] = set()
    for row in rows:
        fields.update(str(key) for key in row.keys() if key is not None)
    return fields


def _forbidden_fields(field_names: set[str]) -> tuple[str, ...]:
    lower_to_original = {field.lower(): field for field in field_names}
    allowed = ALLOWED_RAW_FIELDS | IGNORED_METADATA_FIELDS
    explicit = set(lower_to_original) & FORBIDDEN_RAW_FIELDS
    unknown = {field.lower() for field in field_names if field.lower() not in allowed}
    return tuple(sorted(lower_to_original[field] for field in explicit | unknown))


def _normalize_row(
    row: dict[str, Any],
    row_number: int,
    source_type: str,
) -> tuple[RawEventRecord | None, list[RawImportBlocker]]:
    blockers: list[RawImportBlocker] = []

    ts_code = _required_text(row.get("ts_code"))
    name = _required_text(row.get("name"))
    entry_date = _normalize_date(row.get("entry_date"))
    entry_price = _normalize_price(row.get("entry_price"))

    missing = []
    if not ts_code:
        missing.append("ts_code")
    if not name:
        missing.append("name")
    if not entry_date:
        missing.append("entry_date")
    if entry_price is None:
        missing.append("entry_price")

    if missing:
        blockers.append(
            RawImportBlocker(
                code="RAW_ROW_INVALID",
                message="Raw event row is missing required fields or has invalid values.",
                row_number=row_number,
                fields=tuple(missing),
                payload={"missing_or_invalid": missing},
            )
        )
        return None, blockers

    code = _optional_text(row.get("code"))
    if not code and "." in ts_code:
        code = ts_code.split(".", 1)[0]

    source = _optional_text(row.get("source")) or source_type
    return (
        RawEventRecord(
            row_number=row_number,
            ts_code=ts_code,
            code=code,
            name=name,
            entry_date=entry_date,
            entry_time=_optional_text(row.get("entry_time")),
            entry_price=entry_price,
            source=source,
        ),
        blockers,
    )


def _required_text(value: Any) -> str | None:
    text = _optional_text(value)
    return text or None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_date(value: Any) -> str | None:
    text = _required_text(value)
    if text is None:
        return None
    if re.fullmatch(r"\d{8}", text):
        return text
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text.replace("-", "")
    return None


def _normalize_price(value: Any) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return price


def _dirty_reason(event: RawEventRecord) -> str | None:
    if event.name in KNOWN_DIRTY_NAMES or event.ts_code in KNOWN_DIRTY_TS_CODES:
        return KNOWN_DIRTY_REASON
    return None

