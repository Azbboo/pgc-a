#!/usr/bin/env bash
set -euo pipefail

DATE=""
ACCOUNT="paper-main"
OPERATOR=""
MODE="--dry-run"
DB_PATH="${PGC_DB_PATH:-data/pgc_trading.db}"

while [[ $# -gt 0 ]]; do
  case "$1" in
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
    --apply)
      MODE="--apply"
      shift
      ;;
    --dry-run)
      MODE="--dry-run"
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

mkdir -p .pgc-runs
LOG_FILE=".pgc-runs/daily-pipeline-${DATE}.log"

COMMAND=(
  python3 -m pgc_trading.cli.main
  ops daily-pipeline
  --date "$DATE"
  --account "$ACCOUNT"
  --db-path "$DB_PATH"
  "$MODE"
)

if [[ -n "$OPERATOR" ]]; then
  COMMAND+=(--operator "$OPERATOR")
fi

PYTHONPATH=src "${COMMAND[@]}" 2>&1 | tee "$LOG_FILE"
exit "${PIPESTATUS[0]}"
