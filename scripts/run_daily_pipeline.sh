#!/usr/bin/env bash
set -euo pipefail

DATE=""
ACCOUNT="paper-main"
OPERATOR=""
MODE="--dry-run"
DB_PATH="${PGC_DB_PATH:-data/pgc_trading.db}"
BACKUP_DIR=""
LOG_DIR="${PGC_DAILY_PIPELINE_LOG_DIR:-.pgc-runs}"
INCLUDE_MARKET_REVIEW=0
PYTHON_BIN="${PGC_PYTHON:-python3}"

usage() {
  cat <<'USAGE'
Usage: run_daily_pipeline.sh --date YYYYMMDD|YYYY-MM-DD|latest-closed [options]

Options:
  --account ACCOUNT              portfolio account key (default: paper-main)
  --operator OPERATOR            operator name; required with --apply
  --db-path PATH                 SQLite database path (default: PGC_DB_PATH or data/pgc_trading.db)
  --backup-dir PATH              backup destination forwarded to ops daily-pipeline --apply
  --include-market-review        include market review and market-plan context linking
  --apply                        persist writes after creating a database backup
  --dry-run                      preview writes (default)

Environment:
  PGC_DAILY_PIPELINE_LOG_DIR     default: .pgc-runs
  PGC_DAILY_PIPELINE_NOW_DATE    test override for latest-closed resolution
  PGC_DAILY_PIPELINE_NOW_TIME    test override for latest-closed resolution
  PGC_DAILY_PIPELINE_CLOSE_TIME  default: 153000 Asia/Shanghai
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --date)
      DATE="${2:-}"
      shift 2
      ;;
    --account)
      ACCOUNT="${2:-}"
      shift 2
      ;;
    --operator)
      OPERATOR="${2:-}"
      shift 2
      ;;
    --db-path)
      DB_PATH="${2:-}"
      shift 2
      ;;
    --backup-dir)
      BACKUP_DIR="${2:-}"
      shift 2
      ;;
    --apply)
      MODE="--apply"
      shift
      ;;
    --dry-run)
      MODE="--dry-run"
      shift
      ;;
    --include-market-review)
      INCLUDE_MARKET_REVIEW=1
      shift
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$DATE" ]]; then
  echo "--date is required" >&2
  exit 2
fi

if [[ "$MODE" == "--apply" && -z "$OPERATOR" ]]; then
  echo "--operator is required with --apply" >&2
  exit 2
fi

resolve_latest_closed_date() {
  "$PYTHON_BIN" - "$DB_PATH" \
    "${PGC_DAILY_PIPELINE_NOW_DATE:-}" \
    "${PGC_DAILY_PIPELINE_NOW_TIME:-}" \
    "${PGC_DAILY_PIPELINE_CLOSE_TIME:-153000}" <<'PY'
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

db_path = Path(sys.argv[1])
override_date = sys.argv[2]
override_time = sys.argv[3]
close_time = sys.argv[4]

if not db_path.exists():
    print(f"database not found: {db_path}", file=sys.stderr)
    raise SystemExit(1)

now = datetime.now(ZoneInfo("Asia/Shanghai"))
today = override_date or now.strftime("%Y%m%d")
current_time = override_time or now.strftime("%H%M%S")
if len(today) != 8 or not today.isdigit():
    print("PGC_DAILY_PIPELINE_NOW_DATE must be YYYYMMDD", file=sys.stderr)
    raise SystemExit(2)
if len(current_time) != 6 or not current_time.isdigit():
    print("PGC_DAILY_PIPELINE_NOW_TIME must be HHMMSS", file=sys.stderr)
    raise SystemExit(2)
if len(close_time) != 6 or not close_time.isdigit():
    print("PGC_DAILY_PIPELINE_CLOSE_TIME must be HHMMSS", file=sys.stderr)
    raise SystemExit(2)

operator = "<=" if current_time >= close_time else "<"
with sqlite3.connect(db_path) as conn:
    row = conn.execute(
        f"""
        SELECT MAX(cal_date)
        FROM trade_calendar
        WHERE is_open = 1
          AND cal_date {operator} ?
        """,
        (today,),
    ).fetchone()

resolved = row[0] if row else None
if not resolved:
    print(f"no closed trading day found on or before {today}", file=sys.stderr)
    raise SystemExit(1)
if resolved > today:
    print(f"resolved future trading day unexpectedly: {resolved}", file=sys.stderr)
    raise SystemExit(1)
print(resolved)
PY
}

market_bar_count() {
  "$PYTHON_BIN" - "$DB_PATH" "$1" <<'PY'
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

db_path = Path(sys.argv[1])
as_of_date = sys.argv[2]

with sqlite3.connect(db_path) as conn:
    row = conn.execute(
        "SELECT COUNT(*) FROM market_bars WHERE trade_date = ?",
        (as_of_date,),
    ).fetchone()
print(int(row[0] if row else 0))
PY
}

if [[ "$DATE" == "latest-closed" ]]; then
  DATE="$(resolve_latest_closed_date)"
  echo "resolved_date=$DATE"
  if [[ "$(market_bar_count "$DATE")" -le 0 ]]; then
    echo "market data missing for resolved_date=$DATE" >&2
    exit 1
  fi
else
  echo "resolved_date=$DATE"
fi

mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/daily-pipeline-${DATE}.log"
echo "log_file=$LOG_FILE"

COMMAND=(
  "$PYTHON_BIN" -m pgc_trading.cli.main
  ops daily-pipeline
  --date "$DATE"
  --account "$ACCOUNT"
  --db-path "$DB_PATH"
  "$MODE"
)

if [[ -n "$OPERATOR" ]]; then
  COMMAND+=(--operator "$OPERATOR")
fi

if [[ -n "$BACKUP_DIR" ]]; then
  COMMAND+=(--backup-dir "$BACKUP_DIR")
fi

if [[ "$INCLUDE_MARKET_REVIEW" == "1" ]]; then
  COMMAND+=(--include-market-review)
fi

PYTHONPATH=src "${COMMAND[@]}" 2>&1 | tee "$LOG_FILE"
exit "${PIPESTATUS[0]}"
