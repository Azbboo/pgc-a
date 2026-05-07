"""Daily review application service."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any

from pgc_trading.config import Paths
from pgc_trading.features.cpb_v2_inputs import (
    CONTEXT_FEATURE_VERSIONS as CPB_V2_CONTEXT_FEATURE_VERSIONS,
    FEATURE_VERSION as CPB_V2_FEATURE_VERSION,
    build_cpb_v2_feature_enrichment,
)
from pgc_trading.features.contracting_pullback import (
    ContractingPullbackSnapshot,
    FEATURE_VERSION as CONTRACTING_PULLBACK_FEATURE_VERSION,
    MarketBarInput,
    RawEventInput,
    build_contracting_pullback_snapshot,
    features_json,
)
from pgc_trading.market.calendar import is_yyyymmdd
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult, ServiceWarning
from pgc_trading.services.data_quality_service import (
    DailyReviewReadinessRequest,
    DataQualityService,
)
from pgc_trading.storage.database import connect
from pgc_trading.strategies.cpb_6157 import (
    Cpb6157Params,
    PARAMS as CPB_6157_PARAMS,
    STRATEGY_KEY as CPB_6157_STRATEGY_KEY,
    STRATEGY_VERSION as CPB_6157_STRATEGY_VERSION,
)
from pgc_trading.strategies.cpb_v2 import (
    CpbV2Params,
    PARAMS as CPB_V2_PARAMS,
    STRATEGY_KEY as CPB_V2_STRATEGY_KEY,
)


VALID_RUN_TYPES = {"research", "backtest", "validation", "paper", "live"}
StrategyParams = Cpb6157Params | CpbV2Params


@dataclass(frozen=True)
class RunDailyReviewRequest:
    as_of_date: str
    strategy_version: str = CPB_6157_STRATEGY_VERSION
    max_daily_picks: int = 1
    run_type: str = "paper"
    force_new_run: bool = True


@dataclass(frozen=True)
class DailyPickDTO:
    id: int | None
    strategy_run_id: int | None
    signal_id: int | None
    ts_code: str
    name: str
    review_date: str
    planned_buy_date: str | None
    score: float
    signal_rank: int
    selection_reason: str
    features: dict[str, Any]


@dataclass(frozen=True)
class RunDailyReviewResult:
    feature_run_id: int | None
    strategy_run_id: int | None
    signals_count: int
    daily_pick_id: int | None
    daily_pick: DailyPickDTO | None
    skipped_reason: str | None = None


@dataclass(frozen=True)
class _StrategyDefinition:
    strategy_version_id: int
    strategy_key: str
    strategy_version: str
    params: StrategyParams
    params_json: str
    params_hash: str
    feature_version: str


@dataclass(frozen=True)
class _StrategyAdapter:
    params_type: type[StrategyParams]
    default_params: StrategyParams
    feature_version: str


@dataclass(frozen=True)
class _ReviewCandidate:
    event: RawEventInput
    snapshot: ContractingPullbackSnapshot


@dataclass(frozen=True)
class _SignalDraft:
    event: RawEventInput
    snapshot: ContractingPullbackSnapshot
    planned_buy_date: str | None
    score: float
    signal_rank: int
    signal_status: str


@dataclass(frozen=True)
class _PersistedReview:
    feature_run_id: int
    strategy_run_id: int
    feature_snapshot_ids: list[int]
    signal_ids: list[int]
    daily_pick_id: int | None
    daily_pick: DailyPickDTO | None


_STRATEGY_REGISTRY: dict[str, _StrategyAdapter] = {
    CPB_6157_STRATEGY_KEY: _StrategyAdapter(
        params_type=Cpb6157Params,
        default_params=CPB_6157_PARAMS,
        feature_version=CONTRACTING_PULLBACK_FEATURE_VERSION,
    ),
    CPB_V2_STRATEGY_KEY: _StrategyAdapter(
        params_type=CpbV2Params,
        default_params=CPB_V2_PARAMS,
        feature_version=CPB_V2_FEATURE_VERSION,
    ),
}


class DailyReviewService:
    """Run deterministic daily feature and strategy review without portfolio writes."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def run_daily_review(
        self,
        request: RunDailyReviewRequest,
        ctx: RequestContext,
    ) -> ServiceResult[RunDailyReviewResult]:
        validation_errors = _validate_request(request)
        if validation_errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_result(),
                errors=validation_errors,
            )

        if not ctx.dry_run and not request.force_new_run:
            with connect(self.db_path) as conn:
                previous = _completed_operation_result(conn, ctx)
                if previous is not None:
                    return previous

        readiness = DataQualityService(self.db_path).check_daily_review_readiness(
            DailyReviewReadinessRequest(
                as_of_date=request.as_of_date,
                strategy_version=request.strategy_version,
            ),
            RequestContext(
                request_id=ctx.request_id,
                dry_run=ctx.dry_run,
                operator=ctx.operator,
                source=ctx.source,
            ),
        )
        if readiness.status == "validation_failed":
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_result(),
                warnings=readiness.warnings,
                errors=readiness.errors,
                lineage=readiness.lineage,
            )
        if readiness.data is not None and readiness.data.readiness == "blocker":
            return _blocked_result(self.db_path, request, ctx, readiness)

        if ctx.dry_run:
            with connect(self.db_path) as conn:
                strategy = _resolve_strategy(conn, request)
                if isinstance(strategy, ServiceError):
                    return ServiceResult(
                        status="failed",
                        request_id=ctx.request_id,
                        data=_empty_result(),
                        warnings=readiness.warnings,
                        errors=[strategy],
                    )
                planned_buy_date = _next_open_date(conn, request.as_of_date)
                candidates = _build_review_candidates(conn, request, strategy, planned_buy_date)
                signal_drafts = _build_signal_drafts(request, candidates, planned_buy_date)
                daily_pick = (
                    _daily_pick_dto(None, None, signal_drafts[0])
                    if signal_drafts and request.max_daily_picks
                    else None
                )
                return ServiceResult(
                    status="success",
                    request_id=ctx.request_id,
                    data=RunDailyReviewResult(
                        feature_run_id=None,
                        strategy_run_id=None,
                        signals_count=len(signal_drafts),
                        daily_pick_id=None,
                        daily_pick=daily_pick,
                        skipped_reason=_skipped_reason(candidates, signal_drafts),
                    ),
                    warnings=readiness.warnings,
                    lineage=_lineage(request, strategy, None, None, None),
                )

        with connect(self.db_path) as conn:
            conn.execute("BEGIN")
            try:
                operation_id = _reserve_operation(conn, request, ctx)
                strategy = _resolve_strategy(conn, request)
                if isinstance(strategy, ServiceError):
                    result = ServiceResult(
                        status="failed",
                        request_id=ctx.request_id,
                        data=_empty_result(),
                        warnings=readiness.warnings,
                        errors=[strategy],
                    )
                    _finish_operation(conn, operation_id, result)
                    conn.commit()
                    return result

                planned_buy_date = _next_open_date(conn, request.as_of_date)
                candidates = _build_review_candidates(conn, request, strategy, planned_buy_date)
                signal_drafts = _build_signal_drafts(request, candidates, planned_buy_date)
                persisted = _persist_review(conn, request, strategy, candidates, signal_drafts)
                result_data = RunDailyReviewResult(
                    feature_run_id=persisted.feature_run_id,
                    strategy_run_id=persisted.strategy_run_id,
                    signals_count=len(signal_drafts),
                    daily_pick_id=persisted.daily_pick_id,
                    daily_pick=persisted.daily_pick,
                    skipped_reason=_skipped_reason(candidates, signal_drafts),
                )
                service_result = ServiceResult(
                    status="success",
                    request_id=ctx.request_id,
                    data=result_data,
                    created_ids={
                        "feature_run_id": persisted.feature_run_id,
                        "strategy_run_id": persisted.strategy_run_id,
                        "feature_snapshot_ids": persisted.feature_snapshot_ids,
                        "signal_ids": persisted.signal_ids,
                        **({"daily_pick_id": persisted.daily_pick_id} if persisted.daily_pick_id else {}),
                    },
                    warnings=readiness.warnings,
                    lineage=_lineage(
                        request,
                        strategy,
                        persisted.feature_run_id,
                        persisted.strategy_run_id,
                        persisted.daily_pick_id,
                    ),
                )
                _write_domain_event(conn, persisted, ctx)
                _finish_operation(conn, operation_id, service_result)
                conn.commit()
                return service_result
            except Exception:
                conn.rollback()
                raise


def _validate_request(request: RunDailyReviewRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if not is_yyyymmdd(request.as_of_date):
        errors.append(ServiceError(code="VALIDATION_ERROR", message="as_of_date must use YYYYMMDD format."))
    if not request.strategy_version.strip():
        errors.append(ServiceError(code="VALIDATION_ERROR", message="strategy_version is required."))
    if request.max_daily_picks < 0:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="max_daily_picks cannot be negative."))
    if request.max_daily_picks > 1:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="DailyReviewService supports at most one pick per day."))
    if request.run_type not in VALID_RUN_TYPES:
        errors.append(ServiceError(code="VALIDATION_ERROR", message="run_type is invalid."))
    return errors


def _resolve_strategy(
    conn: sqlite3.Connection,
    request: RunDailyReviewRequest,
) -> _StrategyDefinition | ServiceError:
    row = conn.execute(
        """
        SELECT
          sv.id,
          sv.strategy_key,
          sv.strategy_version,
          sv.params_hash,
          ps.params_json
        FROM strategy_versions sv
        LEFT JOIN parameter_sets ps
          ON ps.strategy_version_id = sv.id
         AND ps.params_hash = sv.params_hash
        WHERE sv.strategy_version = ?
        """,
        (request.strategy_version,),
    ).fetchone()
    if row is None:
        return ServiceError(
            code="STRATEGY_VERSION_NOT_FOUND",
            message=f"Strategy version was not found: {request.strategy_version}.",
            severity="blocker",
        )
    adapter = _STRATEGY_REGISTRY.get(row["strategy_key"])
    if adapter is None:
        return ServiceError(
            code="UNSUPPORTED_STRATEGY_VERSION",
            message=f"DailyReviewService does not support strategy key: {row['strategy_key']}.",
            entity_type="strategy_version",
            entity_id=int(row["id"]),
        )

    params_json = row["params_json"] or adapter.default_params.canonical_json()
    try:
        params = _params_from_json(params_json, adapter.params_type)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return ServiceError(
            code="INVALID_STRATEGY_PARAMS",
            message=f"Strategy params are invalid: {exc}",
            entity_type="strategy_version",
            entity_id=int(row["id"]),
        )

    return _StrategyDefinition(
        strategy_version_id=int(row["id"]),
        strategy_key=row["strategy_key"],
        strategy_version=row["strategy_version"],
        params=params,
        params_json=_json_dumps(params.to_dict()),
        params_hash=row["params_hash"],
        feature_version=adapter.feature_version,
    )


def _params_from_json(
    params_json: str,
    params_type: type[StrategyParams],
) -> StrategyParams:
    payload = json.loads(params_json)
    if not isinstance(payload, dict):
        raise ValueError("params_json must be an object")
    valid_fields = {field.name for field in fields(params_type)}
    kwargs = {key: payload[key] for key in valid_fields if key in payload}
    return params_type(**kwargs)


def _build_review_candidates(
    conn: sqlite3.Connection,
    request: RunDailyReviewRequest,
    strategy: _StrategyDefinition,
    planned_buy_date: str | None,
) -> list[_ReviewCandidate]:
    events = _load_raw_events(conn, request.as_of_date)
    candidates: list[_ReviewCandidate] = []
    for event in events:
        bars = _load_market_bars(conn, event.ts_code, request.as_of_date)
        base_params = strategy.params if isinstance(strategy.params, Cpb6157Params) else CPB_6157_PARAMS
        snapshot = build_contracting_pullback_snapshot(
            event,
            bars,
            request.as_of_date,
            params=base_params,
        )
        if strategy.strategy_key == CPB_V2_STRATEGY_KEY:
            snapshot = _build_cpb_v2_snapshot(
                conn,
                event,
                snapshot,
                request,
                planned_buy_date,
                strategy,
            )
        candidates.append(_ReviewCandidate(event=event, snapshot=snapshot))
    return candidates


def _build_signal_drafts(
    request: RunDailyReviewRequest,
    candidates: list[_ReviewCandidate],
    planned_buy_date: str | None,
) -> list[_SignalDraft]:
    passed = [candidate for candidate in candidates if candidate.snapshot.signal_passed]
    ranked = sorted(
        passed,
        key=lambda item: (-(item.snapshot.score or 0.0), item.event.ts_code, item.event.id),
    )
    return [
        _SignalDraft(
            event=candidate.event,
            snapshot=candidate.snapshot,
            planned_buy_date=planned_buy_date,
            score=float(candidate.snapshot.score or 0.0),
            signal_rank=idx,
            signal_status="daily_pick" if idx == 1 else "candidate",
        )
        for idx, candidate in enumerate(ranked, start=1)
    ]


def _build_cpb_v2_snapshot(
    conn: sqlite3.Connection,
    event: RawEventInput,
    base_snapshot: ContractingPullbackSnapshot,
    request: RunDailyReviewRequest,
    planned_buy_date: str | None,
    strategy: _StrategyDefinition,
) -> ContractingPullbackSnapshot:
    if not isinstance(strategy.params, CpbV2Params):
        raise TypeError("CPB V2 strategy params must be CpbV2Params")
    enrichment = build_cpb_v2_feature_enrichment(
        base_snapshot.features,
        base_input_hash=base_snapshot.input_hash,
        trigger_age_trading_days=_trigger_age_trading_days(
            conn,
            event.ts_code,
            event.entry_date,
            request.as_of_date,
        ),
        planned_buy_date=planned_buy_date,
        context=_load_cpb_v2_context(conn, event, request.as_of_date),
        params=strategy.params,
    )
    return ContractingPullbackSnapshot(
        raw_event_id=base_snapshot.raw_event_id,
        ts_code=base_snapshot.ts_code,
        review_date=base_snapshot.review_date,
        feature_version=CPB_V2_FEATURE_VERSION,
        features=enrichment.features,
        input_hash=enrichment.input_hash,
    )


def _trigger_age_trading_days(
    conn: sqlite3.Connection,
    ts_code: str,
    entry_date: str,
    as_of_date: str,
) -> int | None:
    row = conn.execute(
        """
        SELECT COUNT(*) AS bar_count
        FROM market_bars
        WHERE ts_code = ?
          AND trade_date >= ?
          AND trade_date <= ?
        """,
        (ts_code, entry_date, as_of_date),
    ).fetchone()
    if row is None or row["bar_count"] is None:
        return None
    bar_count = int(row["bar_count"])
    if bar_count <= 0:
        return None
    return bar_count - 1


def _load_cpb_v2_context(
    conn: sqlite3.Connection,
    event: RawEventInput,
    as_of_date: str,
) -> dict[str, Any]:
    placeholders = ", ".join("?" for _ in CPB_V2_CONTEXT_FEATURE_VERSIONS)
    row = conn.execute(
        f"""
        SELECT feature_version, review_date, features_json
        FROM feature_snapshots
        WHERE raw_event_id = ?
          AND review_date <= ?
          AND feature_version IN ({placeholders})
        ORDER BY review_date DESC, id DESC
        LIMIT 1
        """,
        (event.id, as_of_date, *CPB_V2_CONTEXT_FEATURE_VERSIONS),
    ).fetchone()
    if row is None:
        return {}
    try:
        payload = json.loads(row["features_json"])
    except (TypeError, json.JSONDecodeError):
        return {
            "source_feature_version": row["feature_version"],
            "source_review_date": row["review_date"],
        }
    if not isinstance(payload, dict):
        payload = {}
    return {
        **payload,
        "source_feature_version": row["feature_version"],
        "source_review_date": row["review_date"],
    }


def _persist_review(
    conn: sqlite3.Connection,
    request: RunDailyReviewRequest,
    strategy: _StrategyDefinition,
    candidates: list[_ReviewCandidate],
    signal_drafts: list[_SignalDraft],
) -> _PersistedReview:
    input_market_fetch_run_id = _latest_market_fetch_run_id(conn, request.as_of_date)
    feature_run_id = _insert_feature_run(conn, request, strategy, input_market_fetch_run_id)
    snapshot_ids = _insert_feature_snapshots(conn, feature_run_id, candidates)
    strategy_run_id = _insert_strategy_run(conn, request, strategy, feature_run_id)
    signal_ids = _insert_strategy_signals(conn, strategy_run_id, snapshot_ids, signal_drafts)
    daily_pick_id = None
    daily_pick = None
    if signal_drafts and request.max_daily_picks:
        daily_pick_id = _insert_daily_pick(
            conn,
            strategy_run_id,
            signal_ids[0],
            signal_drafts[0],
        )
        daily_pick = _daily_pick_dto(daily_pick_id, signal_ids[0], signal_drafts[0], strategy_run_id)

    conn.execute("UPDATE feature_runs SET status = 'completed' WHERE id = ?", (feature_run_id,))
    conn.execute("UPDATE strategy_runs SET status = 'completed' WHERE id = ?", (strategy_run_id,))
    return _PersistedReview(
        feature_run_id=feature_run_id,
        strategy_run_id=strategy_run_id,
        feature_snapshot_ids=list(snapshot_ids.values()),
        signal_ids=signal_ids,
        daily_pick_id=daily_pick_id,
        daily_pick=daily_pick,
    )


def _load_raw_events(conn: sqlite3.Connection, as_of_date: str) -> list[RawEventInput]:
    rows = conn.execute(
        """
        SELECT id, ts_code, code, name, entry_date, entry_time, entry_price
        FROM raw_events
        WHERE is_valid = 1
          AND entry_date <= ?
        ORDER BY id
        """,
        (as_of_date,),
    ).fetchall()
    return [
        RawEventInput(
            id=int(row["id"]),
            ts_code=row["ts_code"],
            code=row["code"],
            name=row["name"],
            entry_date=row["entry_date"],
            entry_time=row["entry_time"],
            entry_price=float(row["entry_price"]),
        )
        for row in rows
    ]


def _load_market_bars(
    conn: sqlite3.Connection,
    ts_code: str,
    as_of_date: str,
) -> list[MarketBarInput]:
    rows = conn.execute(
        """
        SELECT
          ts_code,
          trade_date,
          open,
          high,
          low,
          close,
          vol,
          amount,
          adj_open,
          adj_high,
          adj_low,
          adj_close
        FROM market_bars
        WHERE ts_code = ?
          AND trade_date <= ?
        ORDER BY trade_date
        """,
        (ts_code, as_of_date),
    ).fetchall()
    return [
        MarketBarInput(
            ts_code=row["ts_code"],
            trade_date=row["trade_date"],
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            vol=row["vol"],
            amount=row["amount"],
            adj_open=row["adj_open"],
            adj_high=row["adj_high"],
            adj_low=row["adj_low"],
            adj_close=row["adj_close"],
        )
        for row in rows
    ]


def _latest_market_fetch_run_id(conn: sqlite3.Connection, as_of_date: str) -> int | None:
    row = conn.execute(
        """
        SELECT MAX(fetch_run_id) AS fetch_run_id
        FROM market_bars
        WHERE trade_date <= ?
          AND fetch_run_id IS NOT NULL
        """,
        (as_of_date,),
    ).fetchone()
    if row is None or row["fetch_run_id"] is None:
        return None
    return int(row["fetch_run_id"])


def _next_open_date(conn: sqlite3.Connection, as_of_date: str) -> str | None:
    row = conn.execute(
        """
        SELECT cal_date
        FROM trade_calendar
        WHERE is_open = 1
          AND cal_date > ?
        ORDER BY cal_date
        LIMIT 1
        """,
        (as_of_date,),
    ).fetchone()
    return None if row is None else row["cal_date"]


def _insert_feature_run(
    conn: sqlite3.Connection,
    request: RunDailyReviewRequest,
    strategy: _StrategyDefinition,
    input_market_fetch_run_id: int | None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO feature_runs
          (feature_version, as_of_date, input_market_fetch_run_id, status)
        VALUES
          (?, ?, ?, 'started')
        """,
        (strategy.feature_version, request.as_of_date, input_market_fetch_run_id),
    )
    return int(cursor.lastrowid)


def _insert_feature_snapshots(
    conn: sqlite3.Connection,
    feature_run_id: int,
    candidates: list[_ReviewCandidate],
) -> dict[int, int]:
    snapshot_ids: dict[int, int] = {}
    for candidate in candidates:
        snapshot = candidate.snapshot
        cursor = conn.execute(
            """
            INSERT INTO feature_snapshots
              (
                feature_run_id,
                raw_event_id,
                ts_code,
                review_date,
                feature_version,
                features_json,
                input_hash
              )
            VALUES
              (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feature_run_id,
                snapshot.raw_event_id,
                snapshot.ts_code,
                snapshot.review_date,
                snapshot.feature_version,
                features_json(snapshot.features),
                snapshot.input_hash,
            ),
        )
        snapshot_ids[snapshot.raw_event_id] = int(cursor.lastrowid)
    return snapshot_ids


def _insert_strategy_run(
    conn: sqlite3.Connection,
    request: RunDailyReviewRequest,
    strategy: _StrategyDefinition,
    feature_run_id: int,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO strategy_runs
          (
            strategy_version_id,
            strategy_key,
            strategy_version,
            as_of_date,
            params_json,
            params_hash,
            feature_run_id,
            run_type,
            status
          )
        VALUES
          (?, ?, ?, ?, ?, ?, ?, ?, 'started')
        """,
        (
            strategy.strategy_version_id,
            strategy.strategy_key,
            strategy.strategy_version,
            request.as_of_date,
            strategy.params_json,
            strategy.params_hash,
            feature_run_id,
            request.run_type,
        ),
    )
    return int(cursor.lastrowid)


def _insert_strategy_signals(
    conn: sqlite3.Connection,
    strategy_run_id: int,
    snapshot_ids: dict[int, int],
    signal_drafts: list[_SignalDraft],
) -> list[int]:
    signal_ids: list[int] = []
    for draft in signal_drafts:
        cursor = conn.execute(
            """
            INSERT INTO strategy_signals
              (
                strategy_run_id,
                feature_snapshot_id,
                raw_event_id,
                ts_code,
                name,
                review_date,
                planned_buy_date,
                score,
                signal_rank,
                signal_status,
                features_json
              )
            VALUES
              (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                strategy_run_id,
                snapshot_ids[draft.event.id],
                draft.event.id,
                draft.event.ts_code,
                draft.event.name,
                draft.snapshot.review_date,
                draft.planned_buy_date,
                draft.score,
                draft.signal_rank,
                draft.signal_status,
                features_json(draft.snapshot.features),
            ),
        )
        signal_ids.append(int(cursor.lastrowid))
    return signal_ids


def _insert_daily_pick(
    conn: sqlite3.Connection,
    strategy_run_id: int,
    signal_id: int,
    draft: _SignalDraft,
) -> int:
    reason = _selection_reason(draft)
    cursor = conn.execute(
        """
        INSERT INTO daily_picks
          (strategy_run_id, signal_id, review_date, planned_buy_date, score, selection_reason)
        VALUES
          (?, ?, ?, ?, ?, ?)
        """,
        (
            strategy_run_id,
            signal_id,
            draft.snapshot.review_date,
            draft.planned_buy_date,
            draft.score,
            reason,
        ),
    )
    return int(cursor.lastrowid)


def _selection_reason(draft: _SignalDraft) -> str:
    return f"highest_score_rank_{draft.signal_rank}: {draft.score:.4f}"


def _daily_pick_dto(
    daily_pick_id: int | None,
    signal_id: int | None,
    draft: _SignalDraft,
    strategy_run_id: int | None = None,
) -> DailyPickDTO:
    return DailyPickDTO(
        id=daily_pick_id,
        strategy_run_id=strategy_run_id,
        signal_id=signal_id,
        ts_code=draft.event.ts_code,
        name=draft.event.name,
        review_date=draft.snapshot.review_date,
        planned_buy_date=draft.planned_buy_date,
        score=draft.score,
        signal_rank=draft.signal_rank,
        selection_reason=_selection_reason(draft),
        features=draft.snapshot.features,
    )


def _skipped_reason(
    candidates: list[_ReviewCandidate],
    signal_drafts: list[_SignalDraft],
) -> str | None:
    if not candidates:
        return "no_valid_raw_events"
    if not signal_drafts:
        return "no_strategy_signals"
    return None


def _blocked_result(
    db_path: Path,
    request: RunDailyReviewRequest,
    ctx: RequestContext,
    readiness: ServiceResult[Any],
) -> ServiceResult[RunDailyReviewResult]:
    result = ServiceResult(
        status="blocked",
        request_id=ctx.request_id,
        data=_empty_result("data_quality_blocker"),
        created_ids={
            "data_quality_event_ids": readiness.data.data_quality_event_ids
            if readiness.data is not None
            else []
        },
        warnings=readiness.warnings,
        errors=readiness.errors
        or [
            ServiceError(
                code="DATA_QUALITY_BLOCKED",
                message="Daily review is blocked by open data-quality blocker event(s).",
                severity="blocker",
            )
        ],
        lineage={
            "as_of_date": request.as_of_date,
            "strategy_version": request.strategy_version,
            "readiness": readiness.data.readiness if readiness.data is not None else None,
        },
    )
    if ctx.dry_run:
        return result

    with connect(db_path) as conn:
        conn.execute("BEGIN")
        try:
            operation_id = _reserve_operation(conn, request, ctx)
            _write_blocked_domain_event(conn, operation_id, request, result, ctx)
            _finish_operation(conn, operation_id, result)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return result


def _empty_result(skipped_reason: str | None = None) -> RunDailyReviewResult:
    return RunDailyReviewResult(
        feature_run_id=None,
        strategy_run_id=None,
        signals_count=0,
        daily_pick_id=None,
        daily_pick=None,
        skipped_reason=skipped_reason,
    )


def _reserve_operation(
    conn: sqlite3.Connection,
    request: RunDailyReviewRequest,
    ctx: RequestContext,
) -> int | None:
    if not ctx.idempotency_key:
        return None

    request_json = _json_dumps(
        {
            "as_of_date": request.as_of_date,
            "strategy_version": request.strategy_version,
            "max_daily_picks": request.max_daily_picks,
            "run_type": request.run_type,
            "force_new_run": request.force_new_run,
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
                operation_type = 'daily_review',
                account_id = NULL,
                as_of_date = ?,
                request_json = ?,
                response_json = NULL,
                error_code = NULL,
                error_message = NULL,
                operator = ?,
                started_at = CURRENT_TIMESTAMP,
                finished_at = NULL
            WHERE id = ?
            """,
            (ctx.request_id, request.as_of_date, request_json, ctx.operator, existing["id"]),
        )
        return int(existing["id"])

    cursor = conn.execute(
        """
        INSERT INTO operation_requests
          (
            idempotency_key,
            request_id,
            operation_type,
            as_of_date,
            status,
            request_json,
            operator
          )
        VALUES
          (?, ?, 'daily_review', ?, 'started', ?, ?)
        """,
        (
            ctx.idempotency_key,
            ctx.request_id,
            request.as_of_date,
            request_json,
            ctx.operator,
        ),
    )
    return int(cursor.lastrowid)


def _completed_operation_result(
    conn: sqlite3.Connection,
    ctx: RequestContext,
) -> ServiceResult[RunDailyReviewResult] | None:
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
    result: ServiceResult[RunDailyReviewResult],
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
            _operation_status(result.status),
            _json_dumps(result),
            first_error.code if first_error else None,
            first_error.message if first_error else None,
            operation_id,
        ),
    )


def _operation_status(status: str) -> str:
    if status in {"success", "partial_success", "skipped"}:
        return status
    return "failed"


def _write_domain_event(
    conn: sqlite3.Connection,
    persisted: _PersistedReview,
    ctx: RequestContext,
) -> None:
    conn.execute(
        """
        INSERT INTO domain_events
          (event_type, entity_type, entity_id, payload_json, source, operator)
        VALUES
          ('daily_review_completed', 'strategy_run', ?, ?, ?, ?)
        """,
        (
            persisted.strategy_run_id,
            _json_dumps(
                {
                    "feature_run_id": persisted.feature_run_id,
                    "strategy_run_id": persisted.strategy_run_id,
                    "daily_pick_id": persisted.daily_pick_id,
                    "signal_ids": persisted.signal_ids,
                }
            ),
            _domain_event_source(ctx.source),
            ctx.operator,
        ),
    )


def _write_blocked_domain_event(
    conn: sqlite3.Connection,
    operation_id: int | None,
    request: RunDailyReviewRequest,
    result: ServiceResult[RunDailyReviewResult],
    ctx: RequestContext,
) -> None:
    if operation_id is None:
        return
    conn.execute(
        """
        INSERT INTO domain_events
          (event_type, entity_type, entity_id, payload_json, source, operator)
        VALUES
          ('daily_review_blocked', 'operation_request', ?, ?, ?, ?)
        """,
        (
            operation_id,
            _json_dumps(
                {
                    "as_of_date": request.as_of_date,
                    "strategy_version": request.strategy_version,
                    "errors": [asdict(error) for error in result.errors],
                }
            ),
            _domain_event_source(ctx.source),
            ctx.operator,
        ),
    )


def _lineage(
    request: RunDailyReviewRequest,
    strategy: _StrategyDefinition,
    feature_run_id: int | None,
    strategy_run_id: int | None,
    daily_pick_id: int | None,
) -> dict[str, int | str | None]:
    return {
        "as_of_date": request.as_of_date,
        "strategy_version_id": strategy.strategy_version_id,
        "strategy_version": strategy.strategy_version,
        "params_hash": strategy.params_hash,
        "feature_run_id": feature_run_id,
        "strategy_run_id": strategy_run_id,
        "daily_pick_id": daily_pick_id,
    }


def _service_result_from_json(
    response_json: str,
    request_id: str | None,
) -> ServiceResult[RunDailyReviewResult]:
    payload = json.loads(response_json)
    data = payload.get("data")
    result = None
    if data is not None:
        pick = data.get("daily_pick")
        result = RunDailyReviewResult(
            feature_run_id=data.get("feature_run_id"),
            strategy_run_id=data.get("strategy_run_id"),
            signals_count=int(data.get("signals_count", 0)),
            daily_pick_id=data.get("daily_pick_id"),
            daily_pick=DailyPickDTO(**pick) if pick is not None else None,
            skipped_reason=data.get("skipped_reason"),
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


def _domain_event_source(source: str) -> str:
    if source in {"manual", "scheduler", "broker_import", "migration"}:
        return source
    return "system"


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
