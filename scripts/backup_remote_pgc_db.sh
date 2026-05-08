#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${PGC_REMOTE_HOST:-root@150.158.121.150}"
REMOTE_DB_PATH="${PGC_REMOTE_DB_PATH:-/opt/pgc/data/pgc_trading.db}"
REMOTE_BACKUP_DIR="${PGC_REMOTE_BACKUP_DIR:-/opt/pgc/backups}"

usage() {
  cat <<'USAGE'
Usage: backup_remote_pgc_db.sh [--dry-run]

Create a timestamped remote SQLite backup before any non-dry-run write.

Environment overrides:
  PGC_REMOTE_HOST        default: root@150.158.121.150
  PGC_REMOTE_DB_PATH     default: /opt/pgc/data/pgc_trading.db
  PGC_REMOTE_BACKUP_DIR  default: /opt/pgc/backups

The script prints the created backup path, for example:
  /opt/pgc/backups/pgc_trading-YYYYMMDD-HHMMSS.db
USAGE
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi

if [[ "$#" -ne 0 ]]; then
  usage >&2
  exit 2
fi

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_PATH="${REMOTE_BACKUP_DIR}/pgc_trading-${TIMESTAMP}.db"

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf 'remote_host=%s\n' "$REMOTE_HOST"
  printf 'source_db=%s\n' "$REMOTE_DB_PATH"
  printf 'backup_path=%s\n' "$BACKUP_PATH"
  exit 0
fi

ssh "$REMOTE_HOST" 'bash -s' -- "$REMOTE_DB_PATH" "$REMOTE_BACKUP_DIR" "$BACKUP_PATH" <<'REMOTE_BACKUP'
set -euo pipefail

db_path="$1"
backup_dir="$2"
backup_path="$3"

mkdir -p "$backup_dir"
test -f "$db_path"
command -v sqlite3 >/dev/null
sqlite3 "$db_path" ".backup $backup_path"
test -s "$backup_path"
printf '%s\n' "$backup_path"
REMOTE_BACKUP
