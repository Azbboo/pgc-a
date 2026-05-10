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
ALLOW_RERUN=0
EVIDENCE_RUN_ID=""

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
  --allow-rerun                  allow an apply rerun after completed writes are detected
  --evidence-run ID              preserve a dry-run evidence log as daily-pipeline-YYYYMMDD-ID.log

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
    --allow-rerun)
      ALLOW_RERUN=1
      shift
      ;;
    --evidence-run)
      EVIDENCE_RUN_ID="${2:-}"
      if [[ -z "$EVIDENCE_RUN_ID" ]]; then
        echo "--evidence-run requires a value" >&2
        exit 2
      fi
      if [[ ! "$EVIDENCE_RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
        echo "--evidence-run must contain only letters, numbers, dots, underscores, or hyphens and start with a letter or number" >&2
        exit 2
      fi
      shift 2
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

if [[ -n "$EVIDENCE_RUN_ID" && "$MODE" != "--dry-run" ]]; then
  echo "--evidence-run is only valid with --dry-run" >&2
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

normalize_requested_date() {
  "$PYTHON_BIN" - "$1" <<'PY'
from __future__ import annotations

import sys

value = sys.argv[1].replace("-", "")
if len(value) != 8 or not value.isdigit():
    print("--date must be YYYYMMDD, YYYY-MM-DD, or latest-closed", file=sys.stderr)
    raise SystemExit(2)
print(value)
PY
}

duplicate_apply_summary() {
  "$PYTHON_BIN" - "$DB_PATH" "$1" <<'PY'
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

db_path = Path(sys.argv[1])
as_of_date = sys.argv[2]

operation_types = (
    "daily_review",
    "portfolio_generate_buy_plan",
    "portfolio_generate_sell_plan",
    "agent_review_daily_pick",
    "position_exit_evaluate",
)

matches: list[str] = []
with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"""
        SELECT id, idempotency_key, operation_type, status, request_json
        FROM operation_requests
        WHERE as_of_date = ?
          AND status IN ('success', 'partial_success', 'skipped')
          AND operation_type IN ({",".join("?" for _ in operation_types)})
        ORDER BY id
        """,
        (as_of_date, *operation_types),
    ).fetchall()

for row in rows:
    try:
        payload = json.loads(row["request_json"])
    except json.JSONDecodeError:
        continue
    if payload.get("dry_run") is False:
        matches.append(f"{row['operation_type']}:{row['idempotency_key']}")

print(f"duplicate_apply_count={len(matches)}")
if matches:
    print(f"duplicate_apply_keys={';'.join(matches[:8])}")
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
  DATE="$(normalize_requested_date "$DATE")"
  echo "resolved_date=$DATE"
fi

mkdir -p "$LOG_DIR"
LOG_BASENAME="daily-pipeline-${DATE}"
if [[ -n "$EVIDENCE_RUN_ID" ]]; then
  LOG_BASENAME="${LOG_BASENAME}-${EVIDENCE_RUN_ID}"
fi
LOG_FILE="${LOG_DIR}/${LOG_BASENAME}.log"
echo "log_file=$LOG_FILE"
if [[ -n "$EVIDENCE_RUN_ID" && -e "$LOG_FILE" ]]; then
  echo "evidence log already exists: $LOG_FILE" >&2
  exit 1
fi
: > "$LOG_FILE"
printf 'resolved_date=%s\n' "$DATE" >> "$LOG_FILE"
printf 'log_file=%s\n' "$LOG_FILE" >> "$LOG_FILE"
if [[ -n "$EVIDENCE_RUN_ID" ]]; then
  printf 'evidence_run_id=%s\n' "$EVIDENCE_RUN_ID" | tee -a "$LOG_FILE"
  printf 'evidence_log_role=dry_run_activation_evidence\n' | tee -a "$LOG_FILE"
fi

emit_log_line() {
  printf '%s\n' "$1" | tee -a "$LOG_FILE"
}

DUPLICATE_SUMMARY="$(duplicate_apply_summary "$DATE")"
printf '%s\n' "$DUPLICATE_SUMMARY" | tee -a "$LOG_FILE"
DUPLICATE_COUNT="$(printf '%s\n' "$DUPLICATE_SUMMARY" | awk -F= '/^duplicate_apply_count=/{print $2}')"

if [[ "$MODE" == "--apply" ]]; then
  if [[ "${DUPLICATE_COUNT:-0}" != "0" && "$ALLOW_RERUN" != "1" ]]; then
    emit_log_line "duplicate_write_guard=blocked"
    echo "duplicate apply writes already exist for resolved_date=$DATE; pass --allow-rerun only after operator review" >&2
    exit 1
  fi
  if [[ "${DUPLICATE_COUNT:-0}" != "0" ]]; then
    emit_log_line "duplicate_write_guard=allow_rerun"
  else
    emit_log_line "duplicate_write_guard=pass"
  fi
else
  emit_log_line "duplicate_write_guard=dry_run"
fi

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

PYTHONPATH=src "${COMMAND[@]}" 2>&1 | tee -a "$LOG_FILE"
exit "${PIPESTATUS[0]}"
