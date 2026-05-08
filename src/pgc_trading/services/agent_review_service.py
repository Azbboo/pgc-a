"""Application service for TradingAgents advisory reviews."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pgc_trading.agents.tradingagents_adapter import (
    TradingAgentsExecutionResult,
    TradingAgentsPaths,
    TradingAgentsRunConfig,
    TradingAgentsRunner,
    TradingAgentsUnavailable,
    build_input_snapshot,
    unavailable_result,
)
from pgc_trading.config import Paths
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult, ServiceWarning
from pgc_trading.storage.database import connect


@dataclass(frozen=True)
class ReviewDailyPickRequest:
    daily_pick_id: int
    account_key: str | None = None
    account_id: int | None = None
    mode: str = "local_snapshot_mode"
    llm_provider: str = "deepseek"
    online_tools: bool = False
    deep_think_llm: str = "deepseek-v4-pro"
    quick_think_llm: str = "deepseek-v4-pro"
    max_debate_rounds: int = 3
    max_risk_discuss_rounds: int = 1


@dataclass(frozen=True)
class AgentReviewResult:
    input_snapshot_id: int | None
    agent_run_id: int | None
    agent_decision_id: int | None
    action: str | None
    confidence: float | None
    risk_level: str | None
    summary: str | None
    artifact_paths: list[str] = field(default_factory=list)


class AgentRunner(Protocol):
    def run(
        self,
        snapshot: dict[str, Any],
        config: TradingAgentsRunConfig,
        paths: TradingAgentsPaths,
    ) -> TradingAgentsExecutionResult:
        ...


class AgentReviewService:
    """Run an external TradingAgents review without touching signal or ledger tables."""

    def __init__(
        self,
        db_path: Path | None = None,
        *,
        runner: AgentRunner | None = None,
        paths: TradingAgentsPaths | None = None,
    ):
        self.db_path = db_path or Paths().db_path
        self.runner = runner or TradingAgentsRunner()
        self.paths = paths or TradingAgentsPaths()

    def review_daily_pick(
        self,
        request: ReviewDailyPickRequest,
        ctx: RequestContext,
    ) -> ServiceResult[AgentReviewResult]:
        errors = _validate_request(request)
        if errors:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=_empty_result(),
                errors=errors,
            )

        with connect(self.db_path) as conn:
            candidate = _load_candidate(conn, request)
            if isinstance(candidate, ServiceError):
                return ServiceResult(
                    status="validation_failed",
                    request_id=ctx.request_id,
                    data=_empty_result(),
                    errors=[candidate],
                )
            snapshot_record = _build_snapshot_record(candidate)
            config = _build_config(request)

            if ctx.dry_run:
                return ServiceResult(
                    status="success",
                    request_id=ctx.request_id,
                    data=AgentReviewResult(
                        input_snapshot_id=None,
                        agent_run_id=None,
                        agent_decision_id=None,
                        action="no_opinion",
                        confidence=None,
                        risk_level="unknown",
                        summary="dry-run only; no TradingAgents review was persisted",
                        artifact_paths=[],
                    ),
                    warnings=[
                        ServiceWarning(
                            code="AGENT_REVIEW_DRY_RUN",
                            message="Input snapshot was built but no agent tables or artifacts were written.",
                        )
                    ],
                    lineage={"daily_pick_id": request.daily_pick_id, "signal_id": candidate["signal_id"]},
                )

            conn.execute("BEGIN")
            try:
                operation_id = _reserve_operation(conn, request, ctx, candidate)
                input_snapshot_id = _upsert_input_snapshot(conn, snapshot_record, candidate)
                agent_run_id = _insert_agent_run(conn, input_snapshot_id, candidate, config)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        self.paths.ensure()
        snapshot = snapshot_record["payload"]
        try:
            external_result = self.runner.run(snapshot, config, self.paths)
            run_status = "completed"
            service_status = "success"
            warnings: list[ServiceWarning] = []
            error_message = None
        except TradingAgentsUnavailable as exc:
            external_result = unavailable_result(str(exc))
            run_status = "skipped"
            service_status = "skipped"
            error_message = str(exc)
            warnings = [
                ServiceWarning(
                    code="TRADINGAGENTS_UNAVAILABLE",
                    message=str(exc),
                )
            ]
        except Exception as exc:  # pragma: no cover - defensive boundary around external package
            external_result = unavailable_result(f"TradingAgents review failed: {exc}")
            run_status = "failed"
            service_status = "failed"
            error_message = str(exc)
            warnings = []

        artifact_paths = _write_artifacts(self.paths, agent_run_id, external_result)
        with connect(self.db_path) as conn:
            conn.execute("BEGIN")
            try:
                _finish_agent_run(conn, agent_run_id, run_status, error_message)
                artifact_ids = _insert_artifacts(conn, agent_run_id, artifact_paths)
                decision_id = _insert_agent_decision(conn, agent_run_id, candidate, external_result, artifact_ids)
                result = AgentReviewResult(
                    input_snapshot_id=input_snapshot_id,
                    agent_run_id=agent_run_id,
                    agent_decision_id=decision_id,
                    action=external_result.action,
                    confidence=external_result.confidence,
                    risk_level=external_result.risk_level,
                    summary=external_result.summary,
                    artifact_paths=[str(path) for path in artifact_paths.values()],
                )
                _finish_operation(conn, operation_id, service_status, result, error_message)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        return ServiceResult(
            status=service_status,
            request_id=ctx.request_id,
            data=result,
            created_ids={
                "input_snapshot": input_snapshot_id,
                "agent_run": agent_run_id,
                "agent_decision": decision_id,
            },
            warnings=warnings,
            lineage={
                "daily_pick_id": request.daily_pick_id,
                "signal_id": candidate["signal_id"],
                "agent_run_id": agent_run_id,
                "agent_decision_id": decision_id,
            },
        )


def _validate_request(request: ReviewDailyPickRequest) -> list[ServiceError]:
    errors: list[ServiceError] = []
    if request.daily_pick_id <= 0:
        errors.append(ServiceError("INVALID_DAILY_PICK_ID", "daily_pick_id must be greater than zero."))
    if request.account_key is None and request.account_id is None:
        errors.append(ServiceError("ACCOUNT_REQUIRED", "account_key or account_id is required."))
    if request.max_debate_rounds <= 0 or request.max_risk_discuss_rounds <= 0:
        errors.append(ServiceError("INVALID_AGENT_ROUNDS", "agent debate rounds must be greater than zero."))
    return errors


def _load_candidate(conn: sqlite3.Connection, request: ReviewDailyPickRequest) -> dict[str, Any] | ServiceError:
    account = _resolve_account(conn, request.account_key, request.account_id)
    if isinstance(account, ServiceError):
        return account
    row = conn.execute(
        """
        SELECT
          dp.id AS daily_pick_id,
          dp.review_date,
          dp.planned_buy_date,
          dp.score AS daily_pick_score,
          dp.selection_reason,
          ss.id AS signal_id,
          ss.ts_code,
          ss.name,
          ss.score AS signal_score,
          ss.signal_rank,
          ss.features_json,
          ss.raw_event_id,
          ss.feature_snapshot_id,
          sr.strategy_key,
          sr.strategy_version,
          re.entry_date,
          re.entry_time,
          re.entry_price
        FROM daily_picks dp
        JOIN strategy_signals ss ON ss.id = dp.signal_id
        JOIN strategy_runs sr ON sr.id = dp.strategy_run_id
        LEFT JOIN raw_events re ON re.id = ss.raw_event_id
        WHERE dp.id = ?
        """,
        (request.daily_pick_id,),
    ).fetchone()
    if row is None:
        return ServiceError(
            "DAILY_PICK_NOT_FOUND",
            f"Daily pick {request.daily_pick_id} was not found.",
            entity_type="daily_pick",
            entity_id=request.daily_pick_id,
        )

    recent_bars = _load_recent_bars(conn, row["ts_code"], row["review_date"])
    daily_basic = _load_daily_basic_snapshot(conn, row["ts_code"], row["review_date"])
    diagnostic_market = _load_diagnostic_market_context(conn, row["ts_code"], row["review_date"])
    external_items = _load_external_items(conn, row["ts_code"], row["review_date"])
    features = _json_loads(row["features_json"], {})
    market_summary = _market_summary(row["review_date"], recent_bars)
    open_positions = _open_positions_count(conn, account["id"])
    portfolio_context = {
        "account_id": account["id"],
        "account_key": account["account_key"],
        "account_type": account["account_type"],
        "max_positions": account["max_positions"],
        "open_positions": open_positions,
        "free_slots": max(0, int(account["max_positions"]) - open_positions),
    }
    source_refs = [
        f"daily_picks:{row['daily_pick_id']}",
        f"strategy_signals:{row['signal_id']}",
        f"market_bars:{row['ts_code']}:{row['review_date']}",
    ]
    if daily_basic is not None:
        source_refs.append(f"daily_basic_snapshots:{row['ts_code']}:{daily_basic['trade_date']}")
    source_refs.extend(_diagnostic_market_refs(row["ts_code"], diagnostic_market))
    source_refs.extend(f"agent_external_items:{item['id']}" for item in external_items)
    return {
        "daily_pick_id": int(row["daily_pick_id"]),
        "signal_id": int(row["signal_id"]),
        "strategy_id": row["strategy_key"],
        "strategy_version": row["strategy_version"],
        "ts_code": row["ts_code"],
        "name": row["name"],
        "review_date": row["review_date"],
        "planned_buy_date": row["planned_buy_date"],
        "score": float(row["daily_pick_score"]),
        "signal_rank": row["signal_rank"],
        "selection_reason": row["selection_reason"],
        "features": features,
        "raw_event": {
            "raw_event_id": row["raw_event_id"],
            "entry_date": row["entry_date"],
            "entry_time": row["entry_time"],
            "entry_price": row["entry_price"],
        },
        "market_summary": market_summary,
        "daily_basic": daily_basic,
        "external_data": {
            "market_diagnostics": diagnostic_market,
            "items": _external_items_context(external_items),
        },
        "analysis_contexts": _build_analysis_contexts(
            ts_code=row["ts_code"],
            name=row["name"],
            review_date=row["review_date"],
            features=features,
            market_summary=market_summary,
            daily_basic=daily_basic,
            diagnostic_market=diagnostic_market,
            external_items=external_items,
            portfolio_context=portfolio_context,
        ),
        "portfolio_context": portfolio_context,
        "source_refs": source_refs,
    }


def _resolve_account(
    conn: sqlite3.Connection,
    account_key: str | None,
    account_id: int | None,
) -> dict[str, Any] | ServiceError:
    if account_id is not None:
        row = conn.execute("SELECT * FROM portfolio_accounts WHERE id = ?", (account_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM portfolio_accounts WHERE account_key = ?", (account_key,)).fetchone()
    if row is None:
        return ServiceError("ACCOUNT_NOT_FOUND", "Portfolio account was not found.")
    return {
        "id": int(row["id"]),
        "account_key": row["account_key"],
        "account_type": row["account_type"],
        "max_positions": int(row["max_positions"]),
    }


def _load_recent_bars(conn: sqlite3.Connection, ts_code: str, as_of_date: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT trade_date, open, high, low, close, vol, amount
            FROM market_bars
            WHERE ts_code = ? AND trade_date <= ?
            ORDER BY trade_date DESC
            LIMIT 10
            """,
            (ts_code, as_of_date),
        ).fetchall()
    ]


def _load_daily_basic_snapshot(conn: sqlite3.Connection, ts_code: str, as_of_date: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
          ts_code,
          trade_date,
          turnover_rate,
          turnover_rate_f,
          volume_ratio,
          pe,
          pe_ttm,
          pb,
          ps,
          ps_ttm,
          dv_ratio,
          total_mv,
          circ_mv
        FROM daily_basic_snapshots
        WHERE ts_code = ? AND trade_date <= ?
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        (ts_code, as_of_date),
    ).fetchone()
    return dict(row) if row is not None else None


def _load_diagnostic_market_context(
    conn: sqlite3.Connection,
    ts_code: str,
    as_of_date: str,
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT
              provider,
              trade_date,
              open,
              high,
              low,
              close,
              vol,
              amount,
              adj_factor,
              adj_open,
              adj_high,
              adj_low,
              adj_close
            FROM market_diagnostic_bars
            WHERE ts_code = ?
              AND trade_date <= ?
              AND length(trade_date) = 8
              AND trade_date NOT GLOB '*[^0-9]*'
            ORDER BY provider, trade_date DESC
            LIMIT 80
            """,
            (ts_code, as_of_date),
        ).fetchall()
    ]
    providers: list[dict[str, Any]] = []
    for provider in sorted({str(row["provider"]) for row in rows}):
        provider_rows = [row for row in rows if row["provider"] == provider][:10]
        chronological = list(reversed(provider_rows))
        closes = [float(row["close"]) for row in chronological if row.get("close") is not None]
        latest = provider_rows[0] if provider_rows else {}
        providers.append(
            {
                "provider": provider,
                "status": "partial",
                "last_trade_date": latest.get("trade_date"),
                "last_close": latest.get("close"),
                "recent_5d_ret": _window_ret(closes, 5),
                "recent_10d_ret": _window_ret(closes, 10),
                "recent_bars": chronological,
                "limitations": [
                    "该数据来自隔离诊断表，仅用于 Agent 复核对照。",
                    "不得替代 Tushare 生产行情、交易日历或 readiness gate。",
                ],
            }
        )
    return {
        "status": "partial" if providers else "unavailable",
        "source": "market_diagnostic_bars",
        "providers": providers,
        "limitations": [
            "诊断行情可能来自非官方或实验性 provider。",
            "Agent 只能把它作为外部交叉检查，不得覆盖策略事实来源。",
        ],
    }


def _load_external_items(conn: sqlite3.Connection, ts_code: str, as_of_date: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          id,
          ts_code,
          published_date,
          item_type,
          provider,
          title,
          summary,
          url,
          sentiment,
          importance,
          metadata_json
        FROM agent_external_items
        WHERE ts_code = ?
          AND published_date <= ?
          AND length(published_date) = 8
          AND published_date NOT GLOB '*[^0-9]*'
        ORDER BY published_date DESC, id DESC
        LIMIT 20
        """,
        (ts_code, as_of_date),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["metadata"] = _json_loads(item.pop("metadata_json"), {})
        items.append(item)
    return items


def _market_summary(as_of_date: str, bars: list[dict[str, Any]]) -> dict[str, Any]:
    latest = bars[0] if bars else {}
    closes = [float(row["close"]) for row in reversed(bars) if row.get("close") is not None]
    return {
        "last_trade_date": latest.get("trade_date", as_of_date),
        "last_close": latest.get("close"),
        "recent_5d_ret": _window_ret(closes, 5),
        "recent_10d_ret": _window_ret(closes, 10),
        "recent_bars": list(reversed(bars)),
    }


def _window_ret(closes: list[float], days: int) -> float | None:
    if len(closes) < days + 1:
        return None
    base = closes[-days - 1]
    if base == 0:
        return None
    return closes[-1] / base - 1


def _open_positions_count(conn: sqlite3.Connection, account_id: int) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM positions
        WHERE account_id = ? AND status NOT IN ('closed', 'cancelled')
        """,
        (account_id,),
    ).fetchone()
    return int(row["count"])


def _build_analysis_contexts(
    *,
    ts_code: str,
    name: str,
    review_date: str,
    features: dict[str, Any],
    market_summary: dict[str, Any],
    daily_basic: dict[str, Any] | None,
    diagnostic_market: dict[str, Any],
    external_items: list[dict[str, Any]],
    portfolio_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "technical": _technical_context(features, market_summary, diagnostic_market),
        "fundamental": _fundamental_context(ts_code, name, review_date, features, daily_basic, external_items),
        "news": _news_context(ts_code, name, review_date, external_items),
        "sentiment": _sentiment_context(features, market_summary, daily_basic, portfolio_context, external_items),
    }


def _technical_context(
    features: dict[str, Any],
    market_summary: dict[str, Any],
    diagnostic_market: dict[str, Any],
) -> dict[str, Any]:
    technical_keys = [
        "feature_name",
        "signal_passed",
        "score",
        "pullback_days",
        "amount_contract_ratio",
        "avg_amount_to_ma10",
        "trigger_amount_to_ma10",
        "trigger_pct_chg",
        "bull_body",
        "close_recover",
        "drawdown_from_peak",
        "entry_runup",
        "buy_gap_from_entry",
        "dist_ma20",
        "range_pos_20",
    ]
    return {
        "status": "available",
        "source": "PGC strategy features and local market_bars",
        "features": _pick_existing(features, technical_keys),
        "market_summary": market_summary,
        "external_market_diagnostics": diagnostic_market,
    }


def _fundamental_context(
    ts_code: str,
    name: str,
    review_date: str,
    features: dict[str, Any],
    daily_basic: dict[str, Any] | None,
    external_items: list[dict[str, Any]],
) -> dict[str, Any]:
    fundamental_items = _items_by_type(external_items, {"fundamental", "research_note"})
    if daily_basic is None:
        if fundamental_items:
            return {
                "status": "partial",
                "source": "agent_external_items local cache",
                "external_items": fundamental_items,
                "note": f"{ts_code} {name} 在 {review_date} 前没有本地 daily_basic 记录；仅有外部摘要可供复核。",
                "limitations": [
                    "外部摘要不等同于完整财报快照。",
                    "Agent 不得把摘要当作已验证财务报表。",
                ],
            }
        return {
            "status": "unavailable",
            "source": "daily_basic_snapshots",
            "note": f"{ts_code} {name} 在 {review_date} 前没有本地 daily_basic 记录。",
        }
    return {
        "status": "partial",
        "source": "Tushare daily_basic local cache; no income statement or balance sheet snapshot yet",
        "valuation_liquidity": daily_basic,
        "feature_fundamental_hints": _pick_existing(
            features,
            ["buy_total_mv", "buy_circ_mv", "financial_flag", "industry"],
        ),
        "external_items": fundamental_items,
        "limitations": [
            "当前仅有估值、市值、换手率等 daily_basic 字段。",
            "尚未接入利润表、资产负债表、现金流和公告财务摘要。",
        ],
    }


def _news_context(
    ts_code: str,
    name: str,
    review_date: str,
    external_items: list[dict[str, Any]],
) -> dict[str, Any]:
    news_items = _items_by_type(external_items, {"news", "announcement", "risk_note"})
    if news_items:
        return {
            "status": "available",
            "source": "agent_external_items local cache",
            "items": news_items,
            "note": f"{ts_code} {name} 截至 {review_date} 有已落库外部新闻/公告摘要；Agent 只能引用这些摘要。",
            "limitations": [
                "未落库的实时新闻、公告或社媒内容不可引用。",
                "外部摘要只作风险复核，不改变策略信号。",
            ],
        }
    return {
        "status": "unavailable",
        "source": "not_configured",
        "items": [],
        "note": f"{ts_code} {name} 截至 {review_date} 的新闻/公告数据源尚未接入本地库；Agent 不得编造新闻。",
    }


def _sentiment_context(
    features: dict[str, Any],
    market_summary: dict[str, Any],
    daily_basic: dict[str, Any] | None,
    portfolio_context: dict[str, Any],
    external_items: list[dict[str, Any]],
) -> dict[str, Any]:
    sentiment_items = _items_by_type(external_items, {"sentiment", "news", "announcement", "risk_note"})
    return {
        "status": "partial",
        "source": (
            "market-derived plus agent_external_items local cache"
            if sentiment_items
            else "market-derived only; external social/news sentiment not configured"
        ),
        "derived_signals": {
            "recent_5d_ret": market_summary.get("recent_5d_ret"),
            "recent_10d_ret": market_summary.get("recent_10d_ret"),
            "trigger_pct_chg": features.get("trigger_pct_chg"),
            "trigger_amount_to_ma10": features.get("trigger_amount_to_ma10"),
            "turnover_rate": daily_basic.get("turnover_rate") if daily_basic else None,
            "turnover_rate_f": daily_basic.get("turnover_rate_f") if daily_basic else None,
            "volume_ratio": daily_basic.get("volume_ratio") if daily_basic else None,
            "free_slots": portfolio_context.get("free_slots"),
        },
        "external_items": sentiment_items,
        "limitations": [
            "当前情绪面只由价格、成交额、换手率等市场行为推断。",
            "未落库的新闻情绪、公告情绪、社媒讨论或龙虎榜席位情绪不可引用。",
        ],
    }


def _pick_existing(source: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: source[key] for key in keys if key in source and source[key] is not None}


def _items_by_type(items: list[dict[str, Any]], item_types: set[str]) -> list[dict[str, Any]]:
    return [_agent_external_item_view(item) for item in items if item.get("item_type") in item_types]


def _agent_external_item_view(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "published_date": item["published_date"],
        "item_type": item["item_type"],
        "provider": item["provider"],
        "title": item["title"],
        "summary": item["summary"],
        "url": item.get("url"),
        "sentiment": item.get("sentiment", "unknown"),
        "importance": item.get("importance", "unknown"),
        "metadata": item.get("metadata", {}),
    }


def _external_items_context(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "available" if items else "unavailable",
        "source": "agent_external_items",
        "items": [_agent_external_item_view(item) for item in items],
        "limitations": [
            "外部资料必须先落库为摘要，Agent 不得自行扩展到未提供网页或实时源。",
            "外部资料只用于 advisory 复核，不会写入策略信号或组合账本。",
        ],
    }


def _diagnostic_market_refs(ts_code: str, diagnostic_market: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for provider in diagnostic_market.get("providers", []):
        last_trade_date = provider.get("last_trade_date")
        if last_trade_date:
            refs.append(f"market_diagnostic_bars:{provider.get('provider')}:{ts_code}:{last_trade_date}")
    return refs


def _build_snapshot_record(candidate: dict[str, Any]) -> dict[str, Any]:
    agent_candidate = {
        "signal_id": candidate["signal_id"],
        "daily_pick_id": candidate["daily_pick_id"],
        "strategy_id": candidate["strategy_id"],
        "strategy_version": candidate["strategy_version"],
        "ts_code": candidate["ts_code"],
        "name": candidate["name"],
        "review_date": candidate["review_date"],
        "planned_buy_date": candidate["planned_buy_date"],
        "score": candidate["score"],
        "signal_rank": candidate["signal_rank"],
        "selection_reason": candidate["selection_reason"],
        "features": candidate["features"],
        "raw_event": candidate["raw_event"],
        "market_summary": candidate["market_summary"],
        "daily_basic": candidate["daily_basic"],
        "external_data": candidate["external_data"],
        "analysis_contexts": candidate["analysis_contexts"],
        "portfolio_context": candidate["portfolio_context"],
    }
    return build_input_snapshot(agent_candidate, candidate["review_date"], candidate["source_refs"])


def _build_config(request: ReviewDailyPickRequest) -> TradingAgentsRunConfig:
    return TradingAgentsRunConfig(
        mode=request.mode,
        llm_provider=request.llm_provider,
        online_tools=request.online_tools,
        deep_think_llm=request.deep_think_llm,
        quick_think_llm=request.quick_think_llm,
        max_debate_rounds=request.max_debate_rounds,
        max_risk_discuss_rounds=request.max_risk_discuss_rounds,
    )


def _upsert_input_snapshot(
    conn: sqlite3.Connection,
    snapshot_record: dict[str, Any],
    candidate: dict[str, Any],
) -> int:
    conn.execute(
        """
        INSERT INTO input_snapshots
          (snapshot_type, as_of_date, signal_id, daily_pick_id, source_refs_json, payload_json, content_hash)
        VALUES
          (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_type, content_hash) DO NOTHING
        """,
        (
            snapshot_record["snapshot_type"],
            snapshot_record["as_of_date"],
            candidate["signal_id"],
            candidate["daily_pick_id"],
            snapshot_record["source_refs_json"],
            json.dumps(snapshot_record["payload"], ensure_ascii=False, sort_keys=True),
            snapshot_record["content_hash"],
        ),
    )
    row = conn.execute(
        """
        SELECT id FROM input_snapshots
        WHERE snapshot_type = ? AND content_hash = ?
        """,
        (snapshot_record["snapshot_type"], snapshot_record["content_hash"]),
    ).fetchone()
    return int(row["id"])


def _insert_agent_run(
    conn: sqlite3.Connection,
    input_snapshot_id: int,
    candidate: dict[str, Any],
    config: TradingAgentsRunConfig,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO agent_runs
          (agent_system, agent_version, signal_id, daily_pick_id, input_snapshot_id, as_of_date, config_json, config_hash, status, started_at)
        VALUES
          (?, ?, ?, ?, ?, ?, ?, ?, 'running', CURRENT_TIMESTAMP)
        """,
        (
            config.agent_system,
            config.agent_version,
            candidate["signal_id"],
            candidate["daily_pick_id"],
            input_snapshot_id,
            candidate["review_date"],
            config.to_json(),
            config.hash(),
        ),
    )
    return int(cursor.lastrowid)


def _finish_agent_run(
    conn: sqlite3.Connection,
    agent_run_id: int,
    status: str,
    error_message: str | None,
) -> None:
    conn.execute(
        """
        UPDATE agent_runs
        SET status = ?, error_message = ?, finished_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, error_message, agent_run_id),
    )


def _write_artifacts(
    paths: TradingAgentsPaths,
    agent_run_id: int,
    result: TradingAgentsExecutionResult,
) -> dict[str, Path]:
    prefix = paths.results_dir / f"agent_run_{agent_run_id:06d}"
    artifacts: dict[str, Path] = {}
    decision_path = prefix.with_name(f"{prefix.name}_decision.json")
    decision_path.write_text(json.dumps(result.raw_decision, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    artifacts["decision_json"] = decision_path
    if result.raw_state is not None:
        raw_state_path = prefix.with_name(f"{prefix.name}_state.json")
        raw_state_path.write_text(json.dumps(result.raw_state, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        artifacts["raw_state"] = raw_state_path
    if result.final_report:
        report_path = prefix.with_name(f"{prefix.name}_report.md")
        report_path.write_text(result.final_report, encoding="utf-8")
        artifacts["final_report"] = report_path
    return artifacts


def _insert_artifacts(
    conn: sqlite3.Connection,
    agent_run_id: int,
    artifact_paths: dict[str, Path],
) -> dict[str, int]:
    ids: dict[str, int] = {}
    for artifact_type, path in artifact_paths.items():
        content_hash = _file_hash(path)
        conn.execute(
            """
            INSERT INTO agent_artifacts
              (agent_run_id, artifact_type, path, content_hash)
            VALUES
              (?, ?, ?, ?)
            ON CONFLICT(agent_run_id, artifact_type, path) DO UPDATE SET
              content_hash = excluded.content_hash
            """,
            (agent_run_id, artifact_type, str(path), content_hash),
        )
        row = conn.execute(
            """
            SELECT id FROM agent_artifacts
            WHERE agent_run_id = ? AND artifact_type = ? AND path = ?
            """,
            (agent_run_id, artifact_type, str(path)),
        ).fetchone()
        ids[artifact_type] = int(row["id"])
    return ids


def _insert_agent_decision(
    conn: sqlite3.Connection,
    agent_run_id: int,
    candidate: dict[str, Any],
    result: TradingAgentsExecutionResult,
    artifact_ids: dict[str, int],
) -> int:
    raw_decision = dict(result.raw_decision)
    if "decision_json" in artifact_ids:
        raw_decision["raw_output_ref"] = f"agent_artifacts:{artifact_ids['decision_json']}"
    cursor = conn.execute(
        """
        INSERT INTO agent_decisions
          (agent_run_id, signal_id, daily_pick_id, action, confidence, risk_level, summary, supporting_points_json, risk_points_json, raw_decision_json)
        VALUES
          (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            agent_run_id,
            candidate["signal_id"],
            candidate["daily_pick_id"],
            result.action,
            result.confidence,
            result.risk_level,
            result.summary,
            json.dumps(result.supporting_points, ensure_ascii=False),
            json.dumps(result.risk_points, ensure_ascii=False),
            json.dumps(raw_decision, ensure_ascii=False, sort_keys=True),
        ),
    )
    return int(cursor.lastrowid)


def _reserve_operation(
    conn: sqlite3.Connection,
    request: ReviewDailyPickRequest,
    ctx: RequestContext,
    candidate: dict[str, Any],
) -> int | None:
    if ctx.idempotency_key is None:
        return None
    request_json = json.dumps(asdict(request), ensure_ascii=False, sort_keys=True)
    existing = conn.execute(
        "SELECT id FROM operation_requests WHERE idempotency_key = ?",
        (ctx.idempotency_key,),
    ).fetchone()
    if existing is not None:
        conn.execute(
            """
            UPDATE operation_requests
            SET request_id = ?,
                operation_type = 'agent_review_daily_pick',
                account_id = ?,
                as_of_date = ?,
                status = 'started',
                request_json = ?,
                response_json = NULL,
                error_code = NULL,
                error_message = NULL,
                operator = ?,
                started_at = CURRENT_TIMESTAMP,
                finished_at = NULL
            WHERE id = ?
            """,
            (
                ctx.request_id,
                candidate["portfolio_context"]["account_id"],
                candidate["review_date"],
                request_json,
                ctx.operator,
                existing["id"],
            ),
        )
        return int(existing["id"])
    cursor = conn.execute(
        """
        INSERT INTO operation_requests
          (idempotency_key, request_id, operation_type, account_id, as_of_date, status, request_json, operator, started_at)
        VALUES
          (?, ?, 'agent_review_daily_pick', ?, ?, 'started', ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            ctx.idempotency_key,
            ctx.request_id,
            candidate["portfolio_context"]["account_id"],
            candidate["review_date"],
            request_json,
            ctx.operator,
        ),
    )
    return int(cursor.lastrowid)


def _finish_operation(
    conn: sqlite3.Connection,
    operation_id: int | None,
    status: str,
    result: AgentReviewResult,
    error_message: str | None,
) -> None:
    if operation_id is None:
        return
    conn.execute(
        """
        UPDATE operation_requests
        SET status = ?, response_json = ?, error_message = ?, finished_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            status,
            json.dumps(asdict(result), ensure_ascii=False, sort_keys=True),
            error_message,
            operation_id,
        ),
    )


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_loads(value: str | None, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _empty_result() -> AgentReviewResult:
    return AgentReviewResult(
        input_snapshot_id=None,
        agent_run_id=None,
        agent_decision_id=None,
        action=None,
        confidence=None,
        risk_level=None,
        summary=None,
        artifact_paths=[],
    )
