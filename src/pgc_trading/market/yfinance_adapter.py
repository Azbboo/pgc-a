"""Experimental yfinance adapter for historical daily OHLCV bars.

This adapter is intentionally narrower than the Tushare adapter. It does not
provide trade calendars or daily-basic fundamentals, and it keeps Yahoo symbol
mapping metadata with each payload so downstream fetch manifests can preserve
the data-source caveats.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from pgc_trading.market.tushare_adapter import MarketBar, MarketDataPayload, TradeCalendarDay


DownloadFn = Callable[..., Any]


@dataclass(frozen=True)
class YahooTickerMapping:
    ts_code: str
    yahoo_symbol: str
    best_effort: bool = False


class YFinanceConfigurationError(RuntimeError):
    """Raised when the optional yfinance dependency is not installed."""


class YFinanceUnsupportedError(RuntimeError):
    """Raised when a MarketDataAdapter method is outside yfinance's scope."""


class YFinanceAdapter:
    """Network adapter for Yahoo Finance daily OHLCV through yfinance."""

    provider = "yfinance"

    def __init__(self, download: DownloadFn | None = None, timeout: int = 10):
        self._download = download
        self.timeout = timeout

    def fetch_market_data(
        self,
        ts_codes: Sequence[str],
        start_date: str,
        end_date: str,
        include_daily_basic: bool = True,
    ) -> MarketDataPayload:
        download = self._download_func()
        bars: list[MarketBar] = []
        missing_ts_codes: list[str] = []
        mappings: list[YahooTickerMapping] = []

        for ts_code in ts_codes:
            mapping = yahoo_ticker_mapping(ts_code)
            mappings.append(mapping)
            frame = download(
                mapping.yahoo_symbol,
                start=_yyyymmdd_to_iso(start_date),
                end=_exclusive_end_iso(end_date),
                auto_adjust=False,
                actions=False,
                threads=False,
                timeout=self.timeout,
                progress=False,
            )
            symbol_bars = _bars_from_download_frame(frame, ts_code)
            if symbol_bars:
                bars.extend(symbol_bars)
            else:
                missing_ts_codes.append(ts_code)

        return MarketDataPayload(
            bars=tuple(sorted(bars, key=lambda bar: (bar.ts_code, bar.trade_date))),
            daily_basic=(),
            missing_ts_codes=tuple(sorted(set(missing_ts_codes))),
            metadata={
                "yfinance": {
                    "ticker_mappings": [asdict(mapping) for mapping in mappings],
                    "daily_basic_supported": False,
                    "trade_calendar_supported": False,
                    "amount_supported": False,
                    "adjustment_policy": "adj_factor is Adj Close / Close when both values are available",
                }
            },
        )

    def fetch_trade_calendar(
        self,
        start_date: str,
        end_date: str,
        exchange: str = "SSE",
    ) -> Sequence[TradeCalendarDay]:
        raise YFinanceUnsupportedError(
            "yfinance does not provide a reliable trade calendar; use provider='tushare' "
            "for trade_calendar refreshes."
        )

    def _download_func(self) -> DownloadFn:
        if self._download is not None:
            return self._download
        try:
            import yfinance as yf  # type: ignore[import-not-found]
        except ImportError as exc:
            raise YFinanceConfigurationError(
                "yfinance optional dependency is required for provider='yfinance'. "
                "Install it with: python3 -m pip install -e '.[yfinance]'"
            ) from exc
        self._download = yf.download
        return self._download


def yahoo_ticker_mapping(ts_code: str) -> YahooTickerMapping:
    """Map project ts_code values to Yahoo Finance symbols."""

    normalized = ts_code.strip().upper()
    code, separator, exchange = normalized.rpartition(".")
    if not separator or not code or not exchange:
        raise ValueError(f"Unsupported ts_code for yfinance: {ts_code!r}. Expected CODE.EXCHANGE.")
    if exchange == "SH":
        return YahooTickerMapping(ts_code=normalized, yahoo_symbol=f"{code}.SS")
    if exchange == "SZ":
        return YahooTickerMapping(ts_code=normalized, yahoo_symbol=f"{code}.SZ")
    if exchange == "BJ":
        return YahooTickerMapping(ts_code=normalized, yahoo_symbol=f"{code}.BJ", best_effort=True)
    raise ValueError(f"Unsupported ts_code exchange for yfinance: {ts_code!r}.")


def _bars_from_download_frame(frame: object, ts_code: str) -> tuple[MarketBar, ...]:
    records = _records_from_frame(frame)
    bars: list[MarketBar] = []
    for record in records:
        flattened = _flatten_record(record)
        trade_date = _trade_date_from_record(flattened)
        if trade_date is None:
            continue

        open_price = _maybe_float(flattened.get("open"))
        high = _maybe_float(flattened.get("high"))
        low = _maybe_float(flattened.get("low"))
        close = _maybe_float(flattened.get("close"))
        volume = _maybe_float(flattened.get("volume"))
        adj_close = _maybe_float(flattened.get("adj_close"))
        adj_factor = _adj_factor(close, adj_close)

        bars.append(
            MarketBar(
                ts_code=ts_code,
                trade_date=trade_date,
                open=open_price,
                high=high,
                low=low,
                close=close,
                vol=volume,
                amount=None,
                adj_factor=adj_factor,
                adj_open=_adjusted(open_price, adj_factor),
                adj_high=_adjusted(high, adj_factor),
                adj_low=_adjusted(low, adj_factor),
                adj_close=adj_close if adj_factor is not None else None,
            )
        )
    return tuple(sorted(bars, key=lambda bar: bar.trade_date))


def _records_from_frame(frame: object) -> list[Mapping[object, object]]:
    if frame is None:
        return []
    if isinstance(frame, list):
        return [record for record in frame if isinstance(record, Mapping)]

    try:
        if bool(getattr(frame, "empty", False)):
            return []
    except TypeError:
        pass

    source = frame.reset_index() if hasattr(frame, "reset_index") else frame
    if hasattr(source, "to_dict"):
        return list(source.to_dict("records"))
    if isinstance(source, tuple):
        return [record for record in source if isinstance(record, Mapping)]
    raise TypeError("yfinance download returned an unsupported frame type.")


def _flatten_record(record: Mapping[object, object]) -> dict[str, object]:
    flattened: dict[str, object] = {}
    for key, value in record.items():
        flattened[_canonical_column_name(_column_name(key))] = value
    return flattened


def _column_name(key: object) -> str:
    if isinstance(key, tuple):
        parts = [str(part) for part in key if part not in (None, "")]
        for part in parts:
            if _canonical_column_name(part) in _KNOWN_COLUMNS:
                return part
        return "_".join(parts)
    return str(key)


def _canonical_column_name(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _trade_date_from_record(record: Mapping[str, object]) -> str | None:
    for key in ("date", "datetime", "index"):
        if key in record:
            return _date_to_yyyymmdd(record[key])
    return None


def _date_to_yyyymmdd(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")

    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%Y%m%d")
        except ValueError:
            return None
    if len(text) >= 8 and text[:8].isdigit():
        return text[:8]
    return None


def _yyyymmdd_to_iso(value: str) -> str:
    return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")


def _exclusive_end_iso(value: str) -> str:
    return (datetime.strptime(value, "%Y%m%d") + timedelta(days=1)).strftime("%Y-%m-%d")


def _maybe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _adj_factor(close: float | None, adj_close: float | None) -> float | None:
    if close is None or adj_close is None or close <= 0:
        return None
    return adj_close / close


def _adjusted(value: float | None, adj_factor: float | None) -> float | None:
    if value is None or adj_factor is None:
        return None
    return value * adj_factor


_KNOWN_COLUMNS = {
    "date",
    "datetime",
    "index",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
}
