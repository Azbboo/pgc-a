"""Tushare market-data adapter.

The token is read from the environment at adapter construction time and is not
persisted by this module. Tests can inject any object matching
``MarketDataAdapter`` to avoid network access.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class MarketBar:
    ts_code: str
    trade_date: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    vol: float | None = None
    amount: float | None = None
    adj_factor: float | None = None
    adj_open: float | None = None
    adj_high: float | None = None
    adj_low: float | None = None
    adj_close: float | None = None


@dataclass(frozen=True)
class DailyBasicSnapshot:
    ts_code: str
    trade_date: str
    turnover_rate: float | None = None
    turnover_rate_f: float | None = None
    volume_ratio: float | None = None
    pe: float | None = None
    pe_ttm: float | None = None
    pb: float | None = None
    ps: float | None = None
    ps_ttm: float | None = None
    dv_ratio: float | None = None
    total_share: float | None = None
    float_share: float | None = None
    free_share: float | None = None
    total_mv: float | None = None
    circ_mv: float | None = None


@dataclass(frozen=True)
class TradeCalendarDay:
    exchange: str
    cal_date: str
    is_open: bool
    pretrade_date: str | None = None


@dataclass(frozen=True)
class MarketDataPayload:
    bars: Sequence[MarketBar] = field(default_factory=tuple)
    daily_basic: Sequence[DailyBasicSnapshot] = field(default_factory=tuple)
    missing_ts_codes: Sequence[str] = field(default_factory=tuple)


@runtime_checkable
class MarketDataAdapter(Protocol):
    provider: str

    def fetch_market_data(
        self,
        ts_codes: Sequence[str],
        start_date: str,
        end_date: str,
        include_daily_basic: bool = True,
    ) -> MarketDataPayload: ...

    def fetch_trade_calendar(
        self,
        start_date: str,
        end_date: str,
        exchange: str = "SSE",
    ) -> Sequence[TradeCalendarDay]: ...


class TushareConfigurationError(RuntimeError):
    """Raised when real Tushare fetching is not explicitly configured."""


class TushareAdapter:
    """Network adapter for Tushare Pro APIs."""

    provider = "tushare"

    def __init__(self, token_env_var: str = "TUSHARE_TOKEN"):
        token = _required_env_token(token_env_var)

        import tushare as ts  # type: ignore[import-not-found]

        ts.set_token(token)
        self._pro = ts.pro_api(token)

    def fetch_market_data(
        self,
        ts_codes: Sequence[str],
        start_date: str,
        end_date: str,
        include_daily_basic: bool = True,
    ) -> MarketDataPayload:
        import pandas as pd  # type: ignore[import-not-found]

        bars: list[MarketBar] = []
        daily_basic: list[DailyBasicSnapshot] = []
        missing_ts_codes: list[str] = []

        for ts_code in ts_codes:
            daily = _normalize_frame(
                self._pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            )
            adj = _normalize_frame(
                self._pro.adj_factor(ts_code=ts_code, start_date=start_date, end_date=end_date)
            )
            if daily.empty:
                missing_ts_codes.append(ts_code)
            else:
                adj_columns = ["ts_code", "trade_date", "adj_factor"]
                adj_for_merge = (
                    adj[adj_columns]
                    if not adj.empty and all(column in adj.columns for column in adj_columns)
                    else pd.DataFrame(columns=adj_columns)
                )
                merged = pd.merge(
                    daily,
                    adj_for_merge,
                    on=["ts_code", "trade_date"],
                    how="left",
                )
                for row in merged.to_dict("records"):
                    adj_factor = _maybe_float(row.get("adj_factor"))
                    bars.append(
                        MarketBar(
                            ts_code=str(row["ts_code"]),
                            trade_date=str(row["trade_date"]),
                            open=_maybe_float(row.get("open")),
                            high=_maybe_float(row.get("high")),
                            low=_maybe_float(row.get("low")),
                            close=_maybe_float(row.get("close")),
                            vol=_maybe_float(row.get("vol")),
                            amount=_maybe_float(row.get("amount")),
                            adj_factor=adj_factor,
                            adj_open=_adjusted(row.get("open"), adj_factor),
                            adj_high=_adjusted(row.get("high"), adj_factor),
                            adj_low=_adjusted(row.get("low"), adj_factor),
                            adj_close=_adjusted(row.get("close"), adj_factor),
                        )
                    )

            if include_daily_basic:
                basic = _normalize_frame(
                    self._pro.daily_basic(
                        ts_code=ts_code,
                        start_date=start_date,
                        end_date=end_date,
                        fields=(
                            "ts_code,trade_date,turnover_rate,turnover_rate_f,volume_ratio,"
                            "pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,total_share,float_share,"
                            "free_share,total_mv,circ_mv"
                        ),
                    )
                )
                for row in basic.to_dict("records"):
                    daily_basic.append(
                        DailyBasicSnapshot(
                            ts_code=str(row["ts_code"]),
                            trade_date=str(row["trade_date"]),
                            turnover_rate=_maybe_float(row.get("turnover_rate")),
                            turnover_rate_f=_maybe_float(row.get("turnover_rate_f")),
                            volume_ratio=_maybe_float(row.get("volume_ratio")),
                            pe=_maybe_float(row.get("pe")),
                            pe_ttm=_maybe_float(row.get("pe_ttm")),
                            pb=_maybe_float(row.get("pb")),
                            ps=_maybe_float(row.get("ps")),
                            ps_ttm=_maybe_float(row.get("ps_ttm")),
                            dv_ratio=_maybe_float(row.get("dv_ratio")),
                            total_share=_maybe_float(row.get("total_share")),
                            float_share=_maybe_float(row.get("float_share")),
                            free_share=_maybe_float(row.get("free_share")),
                            total_mv=_maybe_float(row.get("total_mv")),
                            circ_mv=_maybe_float(row.get("circ_mv")),
                        )
                    )

        return MarketDataPayload(
            bars=tuple(bars),
            daily_basic=tuple(daily_basic),
            missing_ts_codes=tuple(sorted(set(missing_ts_codes))),
        )

    def fetch_trade_calendar(
        self,
        start_date: str,
        end_date: str,
        exchange: str = "SSE",
    ) -> Sequence[TradeCalendarDay]:
        df = _normalize_frame(
            self._pro.trade_cal(exchange=exchange, start_date=start_date, end_date=end_date)
        )
        return tuple(
            TradeCalendarDay(
                exchange=str(row.get("exchange") or exchange),
                cal_date=str(row["cal_date"]),
                is_open=bool(int(row["is_open"])),
                pretrade_date=str(row["pretrade_date"]) if row.get("pretrade_date") else None,
            )
            for row in df.to_dict("records")
        )


def _normalize_frame(df):
    if df.empty:
        return df
    if "trade_date" in df.columns:
        df = df.sort_values("trade_date")
    elif "cal_date" in df.columns:
        df = df.sort_values("cal_date")
    return df.reset_index(drop=True)


def _required_env_token(token_env_var: str) -> str:
    token = os.environ.get(token_env_var, "").strip()
    if not token:
        raise TushareConfigurationError(
            f"{token_env_var} is required in the environment for real Tushare fetches."
        )
    return token


def _maybe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except TypeError:
        pass
    return float(value)


def _adjusted(value: object, adj_factor: float | None) -> float | None:
    base = _maybe_float(value)
    if base is None or adj_factor is None:
        return None
    return base * adj_factor
