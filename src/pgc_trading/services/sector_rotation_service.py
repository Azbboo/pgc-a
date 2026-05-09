"""Sector rotation and constituent leadership service."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from pgc_trading.config import Paths
from pgc_trading.market.calendar import is_yyyymmdd
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult, ServiceWarning
from pgc_trading.storage.database import connect


@dataclass(frozen=True)
class ImportSectorMembershipRequest:
    as_of_date: str
    source_file: Path | None = None
    payload: Mapping[str, Any] | None = None
    encoding: str = "utf-8"
    provider: str | None = None


@dataclass(frozen=True)
class SectorConstituentSnapshot:
    ts_code: str
    name: str | None
    rank_in_sector: int | None
    role: str
    score: float | None
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SectorDailySnapshot:
    sector_code: str
    sector_name: str
    provider: str
    rank_overall: int | None
    return_1d: float | None
    return_3d: float | None
    return_5d: float | None
    return_10d: float | None
    breadth_score: float | None
    volume_score: float | None
    persistence_score: float | None
    leader_count: int
    metrics: dict[str, Any] = field(default_factory=dict)
    constituents: list[SectorConstituentSnapshot] = field(default_factory=list)


@dataclass(frozen=True)
class ImportSectorMembershipResult:
    market_review_run_id: int | None
    as_of_date: str
    membership_as_of_date: str
    provider: str
    sector_count: int
    member_count: int
    missing_bar_count: int
    would_insert_count: int
    would_update_count: int
    would_delete_count: int
    inserted_count: int
    updated_count: int
    deleted_count: int
    unchanged_count: int
    changed: bool
    snapshots: list[SectorDailySnapshot] = field(default_factory=list)


@dataclass(frozen=True)
class _SectorInput:
    sector_code: str
    sector_name: str
    members: list["_MemberInput"]


@dataclass(frozen=True)
class _MemberInput:
    ts_code: str
    name: str | None


@dataclass(frozen=True)
class _PreparedMemberships:
    provider: str
    membership_as_of_date: str
    sectors: list[_SectorInput]


@dataclass(frozen=True)
class _MemberMetrics:
    ts_code: str
    name: str | None
    close: float | None
    return_1d: float | None
    return_3d: float | None
    return_5d: float | None
    return_10d: float | None
    volume_expansion: bool | None
    volume_ratio: float | None
    persistence_score: float | None
    score: float | None
    missing_bar: bool


class SectorRotationService:
    """Import sector memberships and score sector-stock leadership."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def import_sector_memberships(
        self,
        request: ImportSectorMembershipRequest,
        ctx: RequestContext,
        *,
        market_review_run_id: int | None = None,
    ) -> ServiceResult[ImportSectorMembershipResult]:
        prepared_or_error = _load_and_prepare_memberships(request)
        if isinstance(prepared_or_error, ServiceError):
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_import_result(request.as_of_date),
                errors=[prepared_or_error],
                lineage=_lineage(request),
            )
        prepared = prepared_or_error

        snapshots, warnings = self._build_snapshots(request.as_of_date, prepared)
        member_count = sum(len(sector.members) for sector in prepared.sectors)
        missing_bar_count = sum(
            1
            for snapshot in snapshots
            for constituent in snapshot.constituents
            if constituent.metrics.get("missing_bar")
        )

        if ctx.dry_run:
            would_insert_count, would_update_count, would_delete_count, unchanged_count = self._preview_changes(
                request.as_of_date,
                snapshots,
            )
            return ServiceResult(
                status="success",
                request_id=ctx.request_id,
                data=ImportSectorMembershipResult(
                    market_review_run_id=None,
                    as_of_date=request.as_of_date,
                    membership_as_of_date=prepared.membership_as_of_date,
                    provider=prepared.provider,
                    sector_count=len(snapshots),
                    member_count=member_count,
                    missing_bar_count=missing_bar_count,
                    would_insert_count=would_insert_count,
                    would_update_count=would_update_count,
                    would_delete_count=would_delete_count,
                    inserted_count=0,
                    updated_count=0,
                    deleted_count=0,
                    unchanged_count=unchanged_count,
                    changed=bool(would_insert_count or would_update_count or would_delete_count),
                    snapshots=snapshots,
                ),
                warnings=warnings,
                lineage=_lineage(request),
            )

        if market_review_run_id is None:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_import_result(
                    request.as_of_date,
                    membership_as_of_date=prepared.membership_as_of_date,
                    provider=prepared.provider,
                    snapshots=snapshots,
                ),
                errors=[
                    ServiceError(
                        "MARKET_REVIEW_RUN_REQUIRED",
                        "market_review_run_id is required when importing sector memberships in apply mode.",
                    )
                ],
                warnings=warnings,
                lineage=_lineage(request),
            )

        inserted_count, updated_count, deleted_count, unchanged_count = self._persist_snapshots(
            market_review_run_id,
            request.as_of_date,
            snapshots,
        )
        changed = bool(inserted_count or updated_count or deleted_count)
        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=ImportSectorMembershipResult(
                market_review_run_id=market_review_run_id,
                as_of_date=request.as_of_date,
                membership_as_of_date=prepared.membership_as_of_date,
                provider=prepared.provider,
                sector_count=len(snapshots),
                member_count=member_count,
                missing_bar_count=missing_bar_count,
                would_insert_count=inserted_count,
                would_update_count=updated_count,
                would_delete_count=deleted_count,
                inserted_count=inserted_count,
                updated_count=updated_count,
                deleted_count=deleted_count,
                unchanged_count=unchanged_count,
                changed=changed,
                snapshots=snapshots,
            ),
            warnings=warnings,
            lineage=_lineage(request),
        )

    def _build_snapshots(
        self,
        as_of_date: str,
        prepared: _PreparedMemberships,
    ) -> tuple[list[SectorDailySnapshot], list[ServiceWarning]]:
        all_ts_codes = sorted({member.ts_code for sector in prepared.sectors for member in sector.members})
        bars_by_code = self._load_bars(all_ts_codes, as_of_date)
        snapshots: list[SectorDailySnapshot] = []
        warnings: list[ServiceWarning] = []

        for sector in prepared.sectors:
            member_metrics: list[_MemberMetrics] = []
            for member in sector.members:
                metrics = _compute_member_metrics(member, bars_by_code.get(member.ts_code, []), as_of_date)
                member_metrics.append(metrics)
                if metrics.missing_bar:
                    warnings.append(
                        ServiceWarning(
                            "MISSING_MARKET_BAR",
                            f"{member.ts_code} has no market_bars close on {as_of_date}; excluded from sector scoring.",
                            entity_type="stock",
                        )
                    )
            snapshots.append(_build_sector_snapshot(sector, prepared, member_metrics))

        ranked = sorted(
            snapshots,
            key=lambda snapshot: (
                snapshot.metrics.get("sector_score") is not None,
                snapshot.metrics.get("sector_score") or -math.inf,
                snapshot.return_1d is not None,
                snapshot.return_1d or -math.inf,
            ),
            reverse=True,
        )
        rank_by_code = {snapshot.sector_code: index for index, snapshot in enumerate(ranked, start=1)}
        return [
            SectorDailySnapshot(
                sector_code=snapshot.sector_code,
                sector_name=snapshot.sector_name,
                provider=snapshot.provider,
                rank_overall=rank_by_code.get(snapshot.sector_code),
                return_1d=snapshot.return_1d,
                return_3d=snapshot.return_3d,
                return_5d=snapshot.return_5d,
                return_10d=snapshot.return_10d,
                breadth_score=snapshot.breadth_score,
                volume_score=snapshot.volume_score,
                persistence_score=snapshot.persistence_score,
                leader_count=snapshot.leader_count,
                metrics=snapshot.metrics,
                constituents=snapshot.constituents,
            )
            for snapshot in snapshots
        ], warnings

    def _load_bars(self, ts_codes: Sequence[str], as_of_date: str) -> dict[str, list[sqlite3.Row]]:
        if not ts_codes:
            return {}
        placeholders = ",".join("?" for _ in ts_codes)
        with connect(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT ts_code, trade_date, close, amount, vol
                FROM market_bars
                WHERE trade_date <= ?
                  AND ts_code IN ({placeholders})
                ORDER BY ts_code, trade_date
                """,
                (as_of_date, *ts_codes),
            ).fetchall()
        bars_by_code: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            bars_by_code.setdefault(str(row["ts_code"]), []).append(row)
        return bars_by_code

    def _preview_changes(
        self,
        as_of_date: str,
        snapshots: list[SectorDailySnapshot],
    ) -> tuple[int, int, int, int]:
        with connect(self.db_path) as conn:
            run_id = _find_market_review_run_id(conn, as_of_date)
            if run_id is None:
                return _snapshot_record_count(snapshots), 0, 0, 0
            return _diff_existing_snapshots(conn, run_id, as_of_date, snapshots)

    def _persist_snapshots(
        self,
        market_review_run_id: int,
        as_of_date: str,
        snapshots: list[SectorDailySnapshot],
    ) -> tuple[int, int, int, int]:
        with connect(self.db_path) as conn:
            conn.execute("BEGIN")
            try:
                inserted_count, updated_count, deleted_count, unchanged_count = _diff_existing_snapshots(
                    conn,
                    market_review_run_id,
                    as_of_date,
                    snapshots,
                )
                _delete_stale_snapshot_rows(conn, market_review_run_id, snapshots)
                for snapshot in snapshots:
                    _upsert_sector_snapshot(conn, market_review_run_id, as_of_date, snapshot)
                    for constituent in snapshot.constituents:
                        _upsert_sector_constituent(conn, market_review_run_id, snapshot, constituent)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return inserted_count, updated_count, deleted_count, unchanged_count


def _load_and_prepare_memberships(
    request: ImportSectorMembershipRequest,
) -> _PreparedMemberships | ServiceError:
    if not is_yyyymmdd(request.as_of_date):
        return ServiceError("INVALID_AS_OF_DATE", "as_of_date must be compact YYYYMMDD.")
    if request.source_file is None and request.payload is None:
        return ServiceError("VALIDATION_ERROR", "source_file or payload is required.")
    if request.source_file is not None and request.payload is not None:
        return ServiceError("VALIDATION_ERROR", "choose either source_file or payload, not both.")

    payload: Any
    if request.payload is not None:
        payload = request.payload
    else:
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
        return ServiceError("VALIDATION_ERROR", "sector membership JSON must be an object.")

    membership_as_of_date = _normalize_date_text(str(payload.get("as_of_date", request.as_of_date)))
    if membership_as_of_date is None:
        return ServiceError("INVALID_MEMBERSHIP_DATE", "payload as_of_date must be YYYYMMDD or YYYY-MM-DD.")
    if membership_as_of_date > request.as_of_date:
        return ServiceError(
            "FUTURE_SECTOR_MEMBERSHIP",
            f"payload as_of_date {membership_as_of_date} is after review date {request.as_of_date}.",
        )

    provider = _clean_text(request.provider) or _clean_text(payload.get("provider")) or "manual_fixture"
    raw_sectors = payload.get("sectors")
    if not isinstance(raw_sectors, list) or not raw_sectors:
        return ServiceError("INVALID_SECTORS", "payload.sectors must be a non-empty list.")

    sectors: list[_SectorInput] = []
    seen_sectors: set[str] = set()
    for index, raw_sector in enumerate(raw_sectors, start=1):
        if not isinstance(raw_sector, Mapping):
            return ServiceError("INVALID_SECTOR", f"sector #{index} must be an object.")
        sector_date = _normalize_date_text(str(raw_sector.get("as_of_date", membership_as_of_date)))
        if sector_date is None:
            return ServiceError("INVALID_SECTOR_DATE", f"sector #{index} as_of_date is invalid.")
        if sector_date > request.as_of_date:
            return ServiceError(
                "FUTURE_SECTOR_MEMBERSHIP",
                f"sector #{index} as_of_date {sector_date} is after review date {request.as_of_date}.",
            )
        sector_code = _clean_text(raw_sector.get("sector_code"))
        sector_name = _clean_text(raw_sector.get("sector_name")) or sector_code
        if not sector_code:
            return ServiceError("INVALID_SECTOR_CODE", f"sector #{index} is missing sector_code.")
        if sector_code in seen_sectors:
            return ServiceError("DUPLICATE_SECTOR", f"duplicate sector_code in payload: {sector_code}")
        seen_sectors.add(sector_code)

        raw_members = raw_sector.get("members")
        if not isinstance(raw_members, list) or not raw_members:
            return ServiceError("INVALID_MEMBERS", f"sector {sector_code} members must be a non-empty list.")
        members: list[_MemberInput] = []
        seen_members: set[str] = set()
        for member_index, raw_member in enumerate(raw_members, start=1):
            if not isinstance(raw_member, Mapping):
                return ServiceError("INVALID_MEMBER", f"sector {sector_code} member #{member_index} must be an object.")
            member_date = _normalize_date_text(str(raw_member.get("as_of_date", sector_date)))
            if member_date is None:
                return ServiceError("INVALID_MEMBER_DATE", f"sector {sector_code} member #{member_index} date is invalid.")
            if member_date > request.as_of_date:
                return ServiceError(
                    "FUTURE_SECTOR_MEMBERSHIP",
                    f"sector {sector_code} member #{member_index} date {member_date} is after review date {request.as_of_date}.",
                )
            ts_code = _clean_text(raw_member.get("ts_code"))
            if not ts_code:
                return ServiceError("INVALID_TS_CODE", f"sector {sector_code} member #{member_index} is missing ts_code.")
            if ts_code in seen_members:
                continue
            seen_members.add(ts_code)
            members.append(_MemberInput(ts_code=ts_code, name=_clean_text(raw_member.get("name"))))
        sectors.append(_SectorInput(sector_code=sector_code, sector_name=sector_name or sector_code, members=members))

    return _PreparedMemberships(
        provider=provider,
        membership_as_of_date=membership_as_of_date,
        sectors=sectors,
    )


def _compute_member_metrics(
    member: _MemberInput,
    bars: Sequence[sqlite3.Row],
    as_of_date: str,
) -> _MemberMetrics:
    as_of_index = next((index for index, row in enumerate(bars) if row["trade_date"] == as_of_date), None)
    if as_of_index is None:
        return _MemberMetrics(
            ts_code=member.ts_code,
            name=member.name,
            close=None,
            return_1d=None,
            return_3d=None,
            return_5d=None,
            return_10d=None,
            volume_expansion=None,
            volume_ratio=None,
            persistence_score=None,
            score=None,
            missing_bar=True,
        )

    close = _to_float(bars[as_of_index]["close"])
    if close is None or close <= 0:
        return _MemberMetrics(
            ts_code=member.ts_code,
            name=member.name,
            close=close,
            return_1d=None,
            return_3d=None,
            return_5d=None,
            return_10d=None,
            volume_expansion=None,
            volume_ratio=None,
            persistence_score=None,
            score=None,
            missing_bar=True,
        )

    returns = {
        "return_1d": _return_since(bars, as_of_index, 1, close),
        "return_3d": _return_since(bars, as_of_index, 3, close),
        "return_5d": _return_since(bars, as_of_index, 5, close),
        "return_10d": _return_since(bars, as_of_index, 10, close),
    }
    current_volume = _bar_volume(bars[as_of_index])
    previous_volumes = [_bar_volume(row) for row in bars[max(0, as_of_index - 5) : as_of_index]]
    previous_volumes = [value for value in previous_volumes if value is not None and value > 0]
    volume_ratio = None
    volume_expansion = None
    if current_volume is not None and current_volume > 0 and previous_volumes:
        avg_volume = sum(previous_volumes) / len(previous_volumes)
        if avg_volume > 0:
            volume_ratio = current_volume / avg_volume
            volume_expansion = volume_ratio > 1.0

    available_persistence_returns = [
        value for value in (returns["return_3d"], returns["return_5d"], returns["return_10d"]) if value is not None
    ]
    persistence_score = (
        sum(1 for value in available_persistence_returns if value > 0) / len(available_persistence_returns)
        if available_persistence_returns
        else None
    )
    score = _member_score(
        returns["return_1d"],
        returns["return_3d"],
        returns["return_5d"],
        returns["return_10d"],
        volume_ratio,
        persistence_score,
    )
    return _MemberMetrics(
        ts_code=member.ts_code,
        name=member.name,
        close=close,
        return_1d=returns["return_1d"],
        return_3d=returns["return_3d"],
        return_5d=returns["return_5d"],
        return_10d=returns["return_10d"],
        volume_expansion=volume_expansion,
        volume_ratio=volume_ratio,
        persistence_score=persistence_score,
        score=score,
        missing_bar=False,
    )


def _build_sector_snapshot(
    sector: _SectorInput,
    prepared: _PreparedMemberships,
    member_metrics: list[_MemberMetrics],
) -> SectorDailySnapshot:
    return_1d = _average([metrics.return_1d for metrics in member_metrics])
    return_3d = _average([metrics.return_3d for metrics in member_metrics])
    return_5d = _average([metrics.return_5d for metrics in member_metrics])
    return_10d = _average([metrics.return_10d for metrics in member_metrics])
    available_1d = [metrics.return_1d for metrics in member_metrics if metrics.return_1d is not None]
    breadth_score = sum(1 for value in available_1d if value > 0) / len(available_1d) if available_1d else None
    volume_flags = [metrics.volume_expansion for metrics in member_metrics if metrics.volume_expansion is not None]
    volume_score = sum(1 for value in volume_flags if value) / len(volume_flags) if volume_flags else None
    persistence_values = [
        value for value in (return_3d, return_5d, return_10d) if value is not None
    ]
    persistence_score = (
        sum(1 for value in persistence_values if value > 0) / len(persistence_values)
        if persistence_values
        else None
    )
    sector_score = _sector_score(
        return_1d,
        return_3d,
        return_5d,
        return_10d,
        breadth_score,
        volume_score,
        persistence_score,
    )
    constituents = _rank_constituents(member_metrics)
    leader_count = sum(1 for constituent in constituents if constituent.role == "leader")
    missing_members = [metrics.ts_code for metrics in member_metrics if metrics.missing_bar]
    available_members = sum(1 for metrics in member_metrics if not metrics.missing_bar)
    return SectorDailySnapshot(
        sector_code=sector.sector_code,
        sector_name=sector.sector_name,
        provider=prepared.provider,
        rank_overall=None,
        return_1d=return_1d,
        return_3d=return_3d,
        return_5d=return_5d,
        return_10d=return_10d,
        breadth_score=breadth_score,
        volume_score=volume_score,
        persistence_score=persistence_score,
        leader_count=leader_count,
        metrics={
            "sector_score": sector_score,
            "membership_as_of_date": prepared.membership_as_of_date,
            "member_count": len(member_metrics),
            "available_member_count": available_members,
            "missing_members": missing_members,
        },
        constituents=constituents,
    )


def _rank_constituents(member_metrics: list[_MemberMetrics]) -> list[SectorConstituentSnapshot]:
    ranked_metrics = sorted(
        member_metrics,
        key=lambda metrics: (
            metrics.score is not None,
            metrics.score if metrics.score is not None else -math.inf,
            metrics.return_1d if metrics.return_1d is not None else -math.inf,
            metrics.ts_code,
        ),
        reverse=True,
    )
    scored = [metrics for metrics in ranked_metrics if metrics.score is not None]
    leader_slots = _leader_slots(len(scored))
    score_median = median([metrics.score for metrics in scored]) if scored else None
    constituents: list[SectorConstituentSnapshot] = []
    for index, metrics in enumerate(ranked_metrics, start=1):
        rank = index
        if metrics.score is None:
            role = "weak"
        elif index <= leader_slots:
            role = "leader"
        elif metrics.score < 0 or (score_median is not None and metrics.score < score_median):
            role = "weak"
        else:
            role = "follower"
        constituents.append(
            SectorConstituentSnapshot(
                ts_code=metrics.ts_code,
                name=metrics.name,
                rank_in_sector=rank,
                role=role,
                score=metrics.score,
                metrics={
                    "close": metrics.close,
                    "return_1d": metrics.return_1d,
                    "return_3d": metrics.return_3d,
                    "return_5d": metrics.return_5d,
                    "return_10d": metrics.return_10d,
                    "volume_ratio": metrics.volume_ratio,
                    "persistence_score": metrics.persistence_score,
                    "missing_bar": metrics.missing_bar,
                },
            )
        )
    return constituents


def _leader_slots(scored_count: int) -> int:
    if scored_count <= 0:
        return 0
    base_slots = max(1, math.ceil(scored_count * 0.2))
    if scored_count >= 10:
        return max(base_slots, 3)
    return base_slots


def _return_since(
    bars: Sequence[sqlite3.Row],
    as_of_index: int,
    offset: int,
    close: float,
) -> float | None:
    previous_index = as_of_index - offset
    if previous_index < 0:
        return None
    previous_close = _to_float(bars[previous_index]["close"])
    if previous_close is None or previous_close <= 0:
        return None
    return (close / previous_close) - 1.0


def _member_score(
    return_1d: float | None,
    return_3d: float | None,
    return_5d: float | None,
    return_10d: float | None,
    volume_ratio: float | None,
    persistence_score: float | None,
) -> float | None:
    weighted_returns = [
        (return_1d, 0.35),
        (return_3d, 0.25),
        (return_5d, 0.20),
        (return_10d, 0.10),
    ]
    available = [(value, weight) for value, weight in weighted_returns if value is not None]
    if not available:
        return None
    return_score = sum(value * 100.0 * weight for value, weight in available) / sum(weight for _, weight in available)
    volume_score = 0.0
    if volume_ratio is not None:
        volume_score = max(-1.0, min(volume_ratio - 1.0, 1.0))
    persistence_component = (persistence_score - 0.5) if persistence_score is not None else 0.0
    return return_score + volume_score * 0.25 + persistence_component * 0.5


def _sector_score(
    return_1d: float | None,
    return_3d: float | None,
    return_5d: float | None,
    return_10d: float | None,
    breadth_score: float | None,
    volume_score: float | None,
    persistence_score: float | None,
) -> float | None:
    return_component = _member_score(return_1d, return_3d, return_5d, return_10d, None, persistence_score)
    if return_component is None and breadth_score is None and volume_score is None and persistence_score is None:
        return None
    score = return_component or 0.0
    if breadth_score is not None:
        score += (breadth_score - 0.5) * 2.0
    if volume_score is not None:
        score += (volume_score - 0.5) * 0.75
    if persistence_score is not None:
        score += (persistence_score - 0.5) * 1.0
    return score


def _average(values: Sequence[float | None]) -> float | None:
    available = [value for value in values if value is not None]
    if not available:
        return None
    return sum(available) / len(available)


def _bar_volume(row: sqlite3.Row) -> float | None:
    amount = _to_float(row["amount"])
    if amount is not None and amount > 0:
        return amount
    return _to_float(row["vol"])


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_date_text(value: str) -> str | None:
    text = value.strip()
    if is_yyyymmdd(text):
        return text
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        compact = text.replace("-", "")
        if is_yyyymmdd(compact):
            return compact
    return None


def _empty_import_result(
    as_of_date: str,
    *,
    membership_as_of_date: str | None = None,
    provider: str = "unknown",
    snapshots: list[SectorDailySnapshot] | None = None,
) -> ImportSectorMembershipResult:
    snapshot_list = snapshots or []
    return ImportSectorMembershipResult(
        market_review_run_id=None,
        as_of_date=as_of_date,
        membership_as_of_date=membership_as_of_date or as_of_date,
        provider=provider,
        sector_count=len(snapshot_list),
        member_count=sum(len(snapshot.constituents) for snapshot in snapshot_list),
        missing_bar_count=0,
        would_insert_count=0,
        would_update_count=0,
        would_delete_count=0,
        inserted_count=0,
        updated_count=0,
        deleted_count=0,
        unchanged_count=0,
        changed=False,
        snapshots=snapshot_list,
    )


def _lineage(request: ImportSectorMembershipRequest) -> dict[str, str | None]:
    return {"source_file": str(request.source_file) if request.source_file else None}


def _json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _snapshot_record_count(snapshots: Sequence[SectorDailySnapshot]) -> int:
    return len(snapshots) + sum(len(snapshot.constituents) for snapshot in snapshots)


def _find_market_review_run_id(conn: sqlite3.Connection, as_of_date: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM market_review_runs WHERE as_of_date = ?",
        (as_of_date,),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def _diff_existing_snapshots(
    conn: sqlite3.Connection,
    market_review_run_id: int,
    as_of_date: str,
    snapshots: Sequence[SectorDailySnapshot],
) -> tuple[int, int, int, int]:
    expected_sector_keys = {snapshot.sector_code for snapshot in snapshots}
    expected_constituent_keys = {
        (snapshot.sector_code, constituent.ts_code)
        for snapshot in snapshots
        for constituent in snapshot.constituents
    }
    existing_sector_rows = {
        row["sector_code"]: row
        for row in conn.execute(
            """
            SELECT *
            FROM sector_daily_snapshots
            WHERE market_review_run_id = ?
            """,
            (market_review_run_id,),
        ).fetchall()
    }
    existing_constituent_rows = {
        (row["sector_code"], row["ts_code"]): row
        for row in conn.execute(
            """
            SELECT *
            FROM sector_constituents
            WHERE market_review_run_id = ?
            """,
            (market_review_run_id,),
        ).fetchall()
    }

    inserted = 0
    updated = 0
    unchanged = 0
    for snapshot in snapshots:
        existing = existing_sector_rows.get(snapshot.sector_code)
        if existing is None:
            inserted += 1
        elif _sector_row_signature(existing) != _sector_snapshot_signature(as_of_date, snapshot):
            updated += 1
        else:
            unchanged += 1
        for constituent in snapshot.constituents:
            existing_constituent = existing_constituent_rows.get((snapshot.sector_code, constituent.ts_code))
            if existing_constituent is None:
                inserted += 1
            elif _constituent_row_signature(existing_constituent) != _constituent_signature(snapshot, constituent):
                updated += 1
            else:
                unchanged += 1

    stale_sector_count = len(set(existing_sector_rows) - expected_sector_keys)
    stale_constituent_count = len(set(existing_constituent_rows) - expected_constituent_keys)
    return inserted, updated, stale_sector_count + stale_constituent_count, unchanged


def _delete_stale_snapshot_rows(
    conn: sqlite3.Connection,
    market_review_run_id: int,
    snapshots: Sequence[SectorDailySnapshot],
) -> None:
    sector_codes = [snapshot.sector_code for snapshot in snapshots]
    if not sector_codes:
        conn.execute("DELETE FROM sector_constituents WHERE market_review_run_id = ?", (market_review_run_id,))
        conn.execute("DELETE FROM sector_daily_snapshots WHERE market_review_run_id = ?", (market_review_run_id,))
        return

    sector_placeholders = ",".join("?" for _ in sector_codes)
    conn.execute(
        f"""
        DELETE FROM sector_constituents
        WHERE market_review_run_id = ?
          AND sector_code NOT IN ({sector_placeholders})
        """,
        (market_review_run_id, *sector_codes),
    )
    conn.execute(
        f"""
        DELETE FROM sector_daily_snapshots
        WHERE market_review_run_id = ?
          AND sector_code NOT IN ({sector_placeholders})
        """,
        (market_review_run_id, *sector_codes),
    )

    for snapshot in snapshots:
        member_codes = [constituent.ts_code for constituent in snapshot.constituents]
        if not member_codes:
            conn.execute(
                """
                DELETE FROM sector_constituents
                WHERE market_review_run_id = ?
                  AND sector_code = ?
                """,
                (market_review_run_id, snapshot.sector_code),
            )
            continue
        member_placeholders = ",".join("?" for _ in member_codes)
        conn.execute(
            f"""
            DELETE FROM sector_constituents
            WHERE market_review_run_id = ?
              AND sector_code = ?
              AND ts_code NOT IN ({member_placeholders})
            """,
            (market_review_run_id, snapshot.sector_code, *member_codes),
        )


def _upsert_sector_snapshot(
    conn: sqlite3.Connection,
    market_review_run_id: int,
    as_of_date: str,
    snapshot: SectorDailySnapshot,
) -> None:
    conn.execute(
        """
        INSERT INTO sector_daily_snapshots
          (
            market_review_run_id, as_of_date, sector_code, sector_name, provider,
            rank_overall, return_1d, return_3d, return_5d, return_10d,
            breadth_score, volume_score, persistence_score, leader_count, metrics_json
          )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(market_review_run_id, sector_code) DO UPDATE SET
          as_of_date = excluded.as_of_date,
          sector_name = excluded.sector_name,
          provider = excluded.provider,
          rank_overall = excluded.rank_overall,
          return_1d = excluded.return_1d,
          return_3d = excluded.return_3d,
          return_5d = excluded.return_5d,
          return_10d = excluded.return_10d,
          breadth_score = excluded.breadth_score,
          volume_score = excluded.volume_score,
          persistence_score = excluded.persistence_score,
          leader_count = excluded.leader_count,
          metrics_json = excluded.metrics_json
        """,
        _sector_snapshot_signature(as_of_date, snapshot, market_review_run_id=market_review_run_id),
    )


def _upsert_sector_constituent(
    conn: sqlite3.Connection,
    market_review_run_id: int,
    snapshot: SectorDailySnapshot,
    constituent: SectorConstituentSnapshot,
) -> None:
    conn.execute(
        """
        INSERT INTO sector_constituents
          (
            market_review_run_id, sector_code, sector_name, ts_code, name,
            rank_in_sector, role, score, metrics_json
          )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(market_review_run_id, sector_code, ts_code) DO UPDATE SET
          sector_name = excluded.sector_name,
          name = excluded.name,
          rank_in_sector = excluded.rank_in_sector,
          role = excluded.role,
          score = excluded.score,
          metrics_json = excluded.metrics_json
        """,
        _constituent_signature(snapshot, constituent, market_review_run_id=market_review_run_id),
    )


def _sector_snapshot_signature(
    as_of_date: str,
    snapshot: SectorDailySnapshot,
    *,
    market_review_run_id: int | None = None,
) -> tuple[object, ...]:
    values: tuple[object, ...] = (
        as_of_date,
        snapshot.sector_code,
        snapshot.sector_name,
        snapshot.provider,
        snapshot.rank_overall,
        snapshot.return_1d,
        snapshot.return_3d,
        snapshot.return_5d,
        snapshot.return_10d,
        snapshot.breadth_score,
        snapshot.volume_score,
        snapshot.persistence_score,
        snapshot.leader_count,
        _json_dumps(snapshot.metrics),
    )
    if market_review_run_id is None:
        return values
    return (market_review_run_id, *values)


def _sector_row_signature(row: sqlite3.Row) -> tuple[object, ...]:
    return (
        row["as_of_date"],
        row["sector_code"],
        row["sector_name"],
        row["provider"],
        row["rank_overall"],
        row["return_1d"],
        row["return_3d"],
        row["return_5d"],
        row["return_10d"],
        row["breadth_score"],
        row["volume_score"],
        row["persistence_score"],
        row["leader_count"],
        row["metrics_json"],
    )


def _constituent_signature(
    snapshot: SectorDailySnapshot,
    constituent: SectorConstituentSnapshot,
    *,
    market_review_run_id: int | None = None,
) -> tuple[object, ...]:
    values: tuple[object, ...] = (
        snapshot.sector_code,
        snapshot.sector_name,
        constituent.ts_code,
        constituent.name,
        constituent.rank_in_sector,
        constituent.role,
        constituent.score,
        _json_dumps(constituent.metrics),
    )
    if market_review_run_id is None:
        return values
    return (market_review_run_id, *values)


def _constituent_row_signature(row: sqlite3.Row) -> tuple[object, ...]:
    return (
        row["sector_code"],
        row["sector_name"],
        row["ts_code"],
        row["name"],
        row["rank_in_sector"],
        row["role"],
        row["score"],
        row["metrics_json"],
    )
