#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${PGC_REMOTE_HOST:-root@150.158.121.150}"
REMOTE_DB_PATH="${PGC_REMOTE_DB_PATH:-/opt/pgc/data/pgc_trading.db}"
REMOTE_BACKUP_DIR="${PGC_REMOTE_BACKUP_DIR:-/opt/pgc/backups}"
REMOTE_SERVICE="${PGC_REMOTE_SERVICE:-pgc-api.service}"
REMOTE_HEALTH_URL="${PGC_REMOTE_HEALTH_URL:-http://127.0.0.1:8020/api/health}"

usage() {
  cat <<'USAGE'
Usage: restore_remote_pgc_db.sh BACKUP_PATH
       restore_remote_pgc_db.sh --dry-run BACKUP_PATH

Restore the remote SQLite database from an explicit backup path, restart the
API service, and verify /api/health.

Environment overrides:
  PGC_REMOTE_HOST        default: root@150.158.121.150
  PGC_REMOTE_DB_PATH     default: /opt/pgc/data/pgc_trading.db
  PGC_REMOTE_BACKUP_DIR  default: /opt/pgc/backups
  PGC_REMOTE_SERVICE     default: pgc-api.service
  PGC_REMOTE_HEALTH_URL  default: http://127.0.0.1:8020/api/health

Example:
  scripts/restore_remote_pgc_db.sh /opt/pgc/backups/pgc_trading-YYYYMMDD-HHMMSS.db
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

if [[ "$#" -ne 1 ]]; then
  usage >&2
  exit 2
fi

BACKUP_PATH="$1"
if [[ "$BACKUP_PATH" != /* ]]; then
  printf 'restore error: BACKUP_PATH must be an absolute remote path\n' >&2
  exit 2
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf 'remote_host=%s\n' "$REMOTE_HOST"
  printf 'backup_path=%s\n' "$BACKUP_PATH"
  printf 'target_db=%s\n' "$REMOTE_DB_PATH"
  printf 'service=%s\n' "$REMOTE_SERVICE"
  printf 'health_url=%s\n' "$REMOTE_HEALTH_URL"
  exit 0
fi

ssh "$REMOTE_HOST" 'bash -s' -- \
  "$BACKUP_PATH" \
  "$REMOTE_DB_PATH" \
  "$REMOTE_BACKUP_DIR" \
  "$REMOTE_SERVICE" \
  "$REMOTE_HEALTH_URL" <<'REMOTE_RESTORE'
set -euo pipefail

backup_path="$1"
db_path="$2"
backup_dir="$3"
service="$4"
health_url="$5"

if [[ "$backup_path" != /* ]]; then
  printf 'restore error: backup path must be absolute\n' >&2
  exit 2
fi

test -f "$backup_path"
mkdir -p "$backup_dir"
case "$backup_path" in
  "$backup_dir"/*.db) ;;
  *)
    printf 'restore error: backup path must be a .db file under %s\n' "$backup_dir" >&2
    exit 2
    ;;
esac
if [[ "$backup_path" == "$db_path" ]]; then
  printf 'restore error: backup path must not be the target database path\n' >&2
  exit 2
fi

pre_restore_path="${backup_dir}/pgc_trading-prerestore-$(date +%Y%m%d-%H%M%S).db"
if [[ -f "$db_path" ]]; then
  cp -p "$db_path" "$pre_restore_path"
  printf 'pre_restore_backup=%s\n' "$pre_restore_path"
fi

service_stopped=0
restart_on_error() {
  if [[ "$service_stopped" -eq 1 ]]; then
    systemctl restart "$service" || true
  fi
}
trap restart_on_error ERR

systemctl stop "$service"
service_stopped=1
cp -p "$backup_path" "$db_path"
systemctl restart "$service"
service_stopped=0
trap - ERR

for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS "$health_url" >/tmp/pgc_restore_health.json; then
    printf 'restored_db=%s\n' "$db_path"
    printf 'health_ok=%s\n' "$health_url"
    cat /tmp/pgc_restore_health.json
    printf '\n'
    exit 0
  fi
  sleep 2
done

systemctl status --no-pager "$service" || true
printf 'restore error: /api/health did not pass after restart\n' >&2
exit 1
REMOTE_RESTORE
