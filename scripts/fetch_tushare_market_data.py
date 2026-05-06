#!/usr/bin/env python3
"""Fetch daily Tushare market data for PGC raw entry events.

The token is intentionally read from TUSHARE_TOKEN and is never stored by this
script. Cached market data is written under data/tushare/.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import tushare as ts


ROOT = Path(__file__).resolve().parents[1]
RAW_EVENTS_PATH = ROOT / "data" / "pgc_raw_events.json"
OUT_DIR = ROOT / "data" / "tushare"


@dataclass(frozen=True)
class FetchConfig:
    input_path: Path
    out_dir: Path
    start_date: str
    end_date: str
    refresh: bool
    sleep_seconds: float


def yyyymmdd_to_dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d")


def dt_to_yyyymmdd(value: datetime) -> str:
    return value.strftime("%Y%m%d")


def load_events(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def infer_date_window(events: list[dict], start_date: str | None, end_date: str | None) -> tuple[str, str]:
    entry_dates = sorted(str(event["entry_date"]) for event in events if event.get("entry_date"))
    if not entry_dates:
        raise ValueError("No entry_date found in raw events.")

    inferred_start = dt_to_yyyymmdd(yyyymmdd_to_dt(entry_dates[0]) - timedelta(days=120))
    inferred_end = entry_dates[-1]
    return start_date or inferred_start, end_date or inferred_end


def ensure_dirs(out_dir: Path) -> None:
    for subdir in ["daily", "adj_factor", "daily_basic"]:
        (out_dir / subdir).mkdir(parents=True, exist_ok=True)


def cached_path(config: FetchConfig, dataset: str, ts_code: str) -> Path:
    return config.out_dir / dataset / f"{ts_code}.csv"


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if "trade_date" in df.columns:
        df = df.sort_values("trade_date")
    return df.reset_index(drop=True)


def call_with_retry(func, *, retries: int = 3, sleep_seconds: float = 1.5) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return func()
        except Exception as exc:  # Tushare raises broad exceptions for API errors.
            last_error = exc
            if attempt < retries:
                time.sleep(sleep_seconds * attempt)
    assert last_error is not None
    raise last_error


def fetch_one(pro, config: FetchConfig, dataset: str, ts_code: str) -> tuple[str, int, str]:
    path = cached_path(config, dataset, ts_code)
    if path.exists() and not config.refresh:
        try:
            return dataset, len(pd.read_csv(path)), "cached"
        except Exception:
            pass

    if dataset == "daily":
        df = call_with_retry(
            lambda: pro.daily(ts_code=ts_code, start_date=config.start_date, end_date=config.end_date),
            sleep_seconds=config.sleep_seconds,
        )
    elif dataset == "adj_factor":
        df = call_with_retry(
            lambda: pro.adj_factor(ts_code=ts_code, start_date=config.start_date, end_date=config.end_date),
            sleep_seconds=config.sleep_seconds,
        )
    elif dataset == "daily_basic":
        df = call_with_retry(
            lambda: pro.daily_basic(
                ts_code=ts_code,
                start_date=config.start_date,
                end_date=config.end_date,
                fields=(
                    "ts_code,trade_date,turnover_rate,turnover_rate_f,volume_ratio,"
                    "pe,pb,ps,dv_ratio,total_mv,circ_mv"
                ),
            ),
            sleep_seconds=config.sleep_seconds,
        )
    else:
        raise ValueError(f"Unsupported dataset: {dataset}")

    df = normalize_frame(df)
    df.to_csv(path, index=False)
    time.sleep(config.sleep_seconds)
    return dataset, len(df), "fetched"


def fetch_trade_calendar(pro, config: FetchConfig) -> int:
    path = config.out_dir / "trade_cal.csv"
    if path.exists() and not config.refresh:
        return len(pd.read_csv(path))
    df = call_with_retry(
        lambda: pro.trade_cal(exchange="SSE", start_date=config.start_date, end_date=config.end_date),
        sleep_seconds=config.sleep_seconds,
    )
    df = normalize_frame(df)
    df.to_csv(path, index=False)
    time.sleep(config.sleep_seconds)
    return len(df)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Tushare market data for PGC raw events.")
    parser.add_argument("--input", default=str(RAW_EVENTS_PATH), help="Path to pgc_raw_events.json.")
    parser.add_argument("--out-dir", default=str(OUT_DIR), help="Output cache directory.")
    parser.add_argument("--start-date", help="YYYYMMDD start date. Defaults to 120 calendar days before first entry.")
    parser.add_argument("--end-date", help="YYYYMMDD end date. Defaults to last entry_date.")
    parser.add_argument("--refresh", action="store_true", help="Refetch and overwrite cached CSV files.")
    parser.add_argument("--sleep", type=float, default=0.22, help="Seconds to sleep between API calls.")
    args = parser.parse_args()

    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        print("TUSHARE_TOKEN is required in the environment.", file=sys.stderr)
        return 2

    events = load_events(Path(args.input))
    start_date, end_date = infer_date_window(events, args.start_date, args.end_date)
    config = FetchConfig(
        input_path=Path(args.input),
        out_dir=Path(args.out_dir),
        start_date=start_date,
        end_date=end_date,
        refresh=args.refresh,
        sleep_seconds=args.sleep,
    )

    ensure_dirs(config.out_dir)
    ts.set_token(token)
    pro = ts.pro_api(token)

    ts_codes = sorted({event["ts_code"] for event in events if event.get("ts_code")})
    print(
        json.dumps(
            {
                "ts_codes": len(ts_codes),
                "start_date": config.start_date,
                "end_date": config.end_date,
                "out_dir": str(config.out_dir),
            },
            ensure_ascii=False,
        )
    )

    calendar_rows = fetch_trade_calendar(pro, config)
    print(json.dumps({"dataset": "trade_cal", "rows": calendar_rows}, ensure_ascii=False))

    summary: dict[str, dict[str, int]] = {
        "daily": {"cached": 0, "fetched": 0, "rows": 0},
        "adj_factor": {"cached": 0, "fetched": 0, "rows": 0},
        "daily_basic": {"cached": 0, "fetched": 0, "rows": 0},
    }
    failures: list[dict[str, str]] = []

    for index, ts_code in enumerate(ts_codes, start=1):
        for dataset in ["daily", "adj_factor", "daily_basic"]:
            try:
                dataset_name, rows, status = fetch_one(pro, config, dataset, ts_code)
                summary[dataset_name][status] += 1
                summary[dataset_name]["rows"] += rows
            except Exception as exc:
                failures.append({"ts_code": ts_code, "dataset": dataset, "error": str(exc)})
        if index % 25 == 0 or index == len(ts_codes):
            print(json.dumps({"progress": index, "total": len(ts_codes), "summary": summary}, ensure_ascii=False))

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_path": str(config.input_path),
        "start_date": config.start_date,
        "end_date": config.end_date,
        "ts_code_count": len(ts_codes),
        "summary": summary,
        "failures": failures,
    }
    (config.out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"done": True, "failures": len(failures), "manifest": str(config.out_dir / "manifest.json")}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
