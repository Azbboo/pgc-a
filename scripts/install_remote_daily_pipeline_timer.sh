#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${PGC_REMOTE_HOST:-root@150.158.121.150}"
REMOTE_CURRENT_DIR="${PGC_REMOTE_CURRENT_DIR:-/opt/pgc/app}"
REMOTE_DB_PATH="${PGC_REMOTE_DB_PATH:-/opt/pgc/data/pgc_trading.db}"
REMOTE_BACKUP_DIR="${PGC_REMOTE_BACKUP_DIR:-/opt/pgc/backups}"
REMOTE_LOG_DIR="${PGC_REMOTE_LOG_DIR:-/opt/pgc/logs}"
REMOTE_HEALTH_URL="${PGC_REMOTE_HEALTH_URL:-http://127.0.0.1:8020/api/health}"
SERVICE_NAME="${PGC_DAILY_PIPELINE_SERVICE:-pgc-daily-pipeline.service}"
TIMER_NAME="${PGC_DAILY_PIPELINE_TIMER:-pgc-daily-pipeline.timer}"
ON_CALENDAR="${PGC_DAILY_PIPELINE_ON_CALENDAR:-Mon..Fri *-*-* 16:20:00 Asia/Shanghai}"
ACCOUNT="paper-main"
OPERATOR="system-daily-pipeline"
MODE="dry-run"
ACTION="preview"
APPROVAL_ID="${PGC_TIMER_ACTIVATION_APPROVAL_ID:-}"
MIN_DRY_RUN_EVIDENCE="${PGC_TIMER_MIN_DRY_RUN_EVIDENCE:-3}"
DRY_RUN_EVIDENCE_FILES=()

usage() {
  cat <<'USAGE'
Usage: install_remote_daily_pipeline_timer.sh [--dry-run|--check-activation|--enable|--status] [--operator NAME] [--mode dry-run|apply] [--account ACCOUNT]
       [--approval-id ID] [--dry-run-evidence PATH]... [--min-dry-runs COUNT]

Preview, enable, or inspect the remote systemd timer for the post-close daily pipeline.
The scheduled command always uses --date latest-closed and --include-market-review.
Preview is the default. Enabling the timer requires the explicit --enable flag.
M58 activation also requires an approval id and repeated dry-run evidence logs.

Examples:
  scripts/install_remote_daily_pipeline_timer.sh --dry-run
  scripts/install_remote_daily_pipeline_timer.sh --operator system-daily-pipeline --mode dry-run
  scripts/install_remote_daily_pipeline_timer.sh --dry-run --operator system-daily-pipeline --mode apply
  scripts/install_remote_daily_pipeline_timer.sh --check-activation --operator system-daily-pipeline --mode apply --approval-id OPS-YYYYMMDD --dry-run-evidence .pgc-runs/daily-pipeline-YYYYMMDD.log
  scripts/install_remote_daily_pipeline_timer.sh --enable --operator system-daily-pipeline --mode apply --approval-id OPS-YYYYMMDD --dry-run-evidence .pgc-runs/daily-pipeline-YYYYMMDD.log
  scripts/install_remote_daily_pipeline_timer.sh --status

Environment overrides:
  PGC_REMOTE_HOST                    default: root@150.158.121.150
  PGC_REMOTE_CURRENT_DIR             default: /opt/pgc/app
  PGC_REMOTE_DB_PATH                 default: /opt/pgc/data/pgc_trading.db
  PGC_REMOTE_BACKUP_DIR              default: /opt/pgc/backups
  PGC_REMOTE_LOG_DIR                 default: /opt/pgc/logs
  PGC_REMOTE_HEALTH_URL              default: http://127.0.0.1:8020/api/health
  PGC_DAILY_PIPELINE_ON_CALENDAR     default: Mon..Fri *-*-* 16:20:00 Asia/Shanghai
  PGC_TIMER_ACTIVATION_APPROVAL_ID   optional approval id used with --enable
  PGC_TIMER_MIN_DRY_RUN_EVIDENCE     default: 3
USAGE
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --dry-run)
      ACTION="preview"
      shift
      ;;
    --enable)
      ACTION="enable"
      shift
      ;;
    --check-activation)
      ACTION="check-activation"
      shift
      ;;
    --status)
      ACTION="status"
      shift
      ;;
    --operator)
      OPERATOR="${2:-}"
      if [[ -z "$OPERATOR" ]]; then
        printf 'timer install error: --operator requires a value\n' >&2
        exit 2
      fi
      shift 2
      ;;
    --approval-id)
      APPROVAL_ID="${2:-}"
      if [[ -z "$APPROVAL_ID" ]]; then
        printf 'timer install error: --approval-id requires a value\n' >&2
        exit 2
      fi
      shift 2
      ;;
    --dry-run-evidence)
      if [[ -z "${2:-}" ]]; then
        printf 'timer install error: --dry-run-evidence requires a path\n' >&2
        exit 2
      fi
      DRY_RUN_EVIDENCE_FILES+=("$2")
      shift 2
      ;;
    --min-dry-runs)
      MIN_DRY_RUN_EVIDENCE="${2:-}"
      if [[ ! "$MIN_DRY_RUN_EVIDENCE" =~ ^[1-9][0-9]*$ ]]; then
        printf 'timer install error: --min-dry-runs must be a positive integer\n' >&2
        exit 2
      fi
      shift 2
      ;;
    --mode)
      MODE="${2:-}"
      if [[ "$MODE" != "dry-run" && "$MODE" != "apply" ]]; then
        printf 'timer install error: --mode must be dry-run or apply\n' >&2
        exit 2
      fi
      shift 2
      ;;
    --account)
      ACCOUNT="${2:-}"
      if [[ -z "$ACCOUNT" ]]; then
        printf 'timer install error: --account requires a value\n' >&2
        exit 2
      fi
      shift 2
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! "$MIN_DRY_RUN_EVIDENCE" =~ ^[1-9][0-9]*$ ]]; then
  printf 'timer install error: PGC_TIMER_MIN_DRY_RUN_EVIDENCE must be a positive integer\n' >&2
  exit 2
fi

MODE_FLAG="--dry-run"
if [[ "$MODE" == "apply" ]]; then
  MODE_FLAG="--apply"
fi

SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"
TIMER_PATH="/etc/systemd/system/${TIMER_NAME}"
PIPELINE_COMMAND="${REMOTE_CURRENT_DIR}/scripts/run_daily_pipeline.sh --date latest-closed --account ${ACCOUNT} --operator ${OPERATOR} --db-path ${REMOTE_DB_PATH} --backup-dir ${REMOTE_BACKUP_DIR} --include-market-review ${MODE_FLAG}"
MANUAL_DRY_RUN_COMMAND="${REMOTE_CURRENT_DIR}/scripts/run_daily_pipeline.sh --date latest-closed --account ${ACCOUNT} --operator ${OPERATOR} --db-path ${REMOTE_DB_PATH} --backup-dir ${REMOTE_BACKUP_DIR} --include-market-review --dry-run"
MANUAL_APPLY_COMMAND="${REMOTE_CURRENT_DIR}/scripts/run_daily_pipeline.sh --date latest-closed --account ${ACCOUNT} --operator ${OPERATOR} --db-path ${REMOTE_DB_PATH} --backup-dir ${REMOTE_BACKUP_DIR} --include-market-review --apply"
REMOTE_HEALTH_COMMAND="cd ${REMOTE_CURRENT_DIR} && PYTHONPATH=src python3 -m pgc_trading.cli.main ops health --db-path ${REMOTE_DB_PATH} --health-url ${REMOTE_HEALTH_URL} --require-current-migrations"
TIMER_ENABLEMENT="preview_only"
if [[ "$ACTION" == "enable" ]]; then
  TIMER_ENABLEMENT="explicit_enable"
elif [[ "$ACTION" == "check-activation" ]]; then
  TIMER_ENABLEMENT="activation_check"
fi

print_summary() {
  printf 'remote_host=%s\n' "$REMOTE_HOST"
  printf 'action=%s\n' "$ACTION"
  printf 'timer_enablement=%s\n' "$TIMER_ENABLEMENT"
  printf 'service_path=%s\n' "$SERVICE_PATH"
  printf 'timer_path=%s\n' "$TIMER_PATH"
  printf 'working_directory=%s\n' "$REMOTE_CURRENT_DIR"
  printf 'db_path=%s\n' "$REMOTE_DB_PATH"
  printf 'backup_dir=%s\n' "$REMOTE_BACKUP_DIR"
  printf 'log_dir=%s\n' "$REMOTE_LOG_DIR"
  printf 'health_url=%s\n' "$REMOTE_HEALTH_URL"
  printf 'on_calendar=%s\n' "$ON_CALENDAR"
  printf 'mode=%s\n' "$MODE"
  printf 'pipeline_command=%s\n' "$PIPELINE_COMMAND"
  printf 'manual_dry_run_command=%s\n' "$MANUAL_DRY_RUN_COMMAND"
  printf 'manual_apply_command=%s\n' "$MANUAL_APPLY_COMMAND"
  printf 'health_command=%s\n' "$REMOTE_HEALTH_COMMAND"
  printf 'minimum_dry_run_evidence=%s\n' "$MIN_DRY_RUN_EVIDENCE"
  printf 'dry_run_evidence_count=%s\n' "${#DRY_RUN_EVIDENCE_FILES[@]}"
  printf 'activation_approval_id=%s\n' "${APPROVAL_ID:-missing}"
  local evidence_file
  for evidence_file in "${DRY_RUN_EVIDENCE_FILES[@]}"; do
    printf 'activation_evidence_file=%s\n' "$evidence_file"
  done
  printf 'status_command=systemctl status %s --no-pager\n' "$TIMER_NAME"
  printf 'service_status_command=systemctl status %s --no-pager\n' "$SERVICE_NAME"
  printf 'timer_list_command=systemctl list-timers --all %s --no-pager\n' "$TIMER_NAME"
  printf 'journal_command=journalctl -u %s -n 100 --no-pager\n' "$SERVICE_NAME"
  printf 'rollback_command=systemctl disable --now %s\n' "$TIMER_NAME"
  printf 'duplicate_write_guard=run_daily_pipeline.sh blocks completed apply runs unless --allow-rerun is passed\n'
}

validate_activation_decision() {
  local failures=0
  local evidence_file
  local previous_file
  local required_pattern
  local required_label
  local resolved_date
  local -a seen_files=()

  if [[ -z "$APPROVAL_ID" ]]; then
    printf 'activation_decision_error=missing_approval_id\n' >&2
    failures=1
  fi

  if [[ "${#DRY_RUN_EVIDENCE_FILES[@]}" -lt "$MIN_DRY_RUN_EVIDENCE" ]]; then
    printf 'activation_decision_error=insufficient_dry_run_evidence required=%s actual=%s\n' "$MIN_DRY_RUN_EVIDENCE" "${#DRY_RUN_EVIDENCE_FILES[@]}" >&2
    failures=1
  fi

  for evidence_file in "${DRY_RUN_EVIDENCE_FILES[@]}"; do
    for previous_file in "${seen_files[@]}"; do
      if [[ "$previous_file" == "$evidence_file" ]]; then
        printf 'activation_decision_error=duplicate_evidence_file file=%s\n' "$evidence_file" >&2
        failures=1
      fi
    done
    seen_files+=("$evidence_file")

    if [[ ! -f "$evidence_file" ]]; then
      printf 'activation_decision_error=missing_evidence_file file=%s\n' "$evidence_file" >&2
      failures=1
      continue
    fi

    resolved_date="$(awk -F= '/^resolved_date=/{print $2; exit}' "$evidence_file")"
    if [[ -z "$resolved_date" ]]; then
      printf 'activation_decision_error=invalid_evidence file=%s missing=resolved_date\n' "$evidence_file" >&2
      failures=1
    else
      printf 'activation_evidence_date=%s file=%s\n' "$resolved_date" "$evidence_file"
    fi

    while IFS='|' read -r required_label required_pattern; do
      if [[ -z "$required_label" ]]; then
        continue
      fi
      if ! grep -Eq "$required_pattern" "$evidence_file"; then
        printf 'activation_decision_error=invalid_evidence file=%s missing=%s\n' "$evidence_file" "$required_label" >&2
        failures=1
      fi
    done <<'REQUIREMENTS'
pipeline_status_pass|^pipeline_status=pass$
report_would_write|^report_would_write=true$
market_review_would_write|^market_review_would_write=true$
dry_run_backup_none|^backup_path=none$
dry_run_changed_false|^changed=false$
duplicate_apply_count_zero|^duplicate_apply_count=0$
duplicate_write_guard_dry_run|^duplicate_write_guard=dry_run$
REQUIREMENTS
  done

  if [[ "$failures" != "0" ]]; then
    return 1
  fi
  return 0
}

if [[ "$ACTION" == "preview" ]]; then
  print_summary
  printf 'activation_decision=preview_only\n'
  printf 'would_write_service=%s\n' "$SERVICE_PATH"
  printf 'would_write_timer=%s\n' "$TIMER_PATH"
  printf 'would_enable_timer=systemctl enable --now %s only after --enable\n' "$TIMER_NAME"
  printf 'enable_command=scripts/install_remote_daily_pipeline_timer.sh --enable --operator %s --mode %s --account %s\n' "$OPERATOR" "$MODE" "$ACCOUNT"
  exit 0
fi

if [[ "$ACTION" == "check-activation" ]]; then
  print_summary
  if validate_activation_decision; then
    printf 'activation_decision=ready\n'
    exit 0
  fi
  printf 'activation_decision=blocked\n'
  exit 1
fi

if [[ "$ACTION" == "status" ]]; then
  print_summary
  ssh "$REMOTE_HOST" 'bash -s' -- "$SERVICE_NAME" "$TIMER_NAME" <<'REMOTE_STATUS'
set -euo pipefail

service_name="$1"
timer_name="$2"

printf 'timer_enabled='
systemctl is-enabled "$timer_name" 2>/dev/null || true
printf 'timer_active='
systemctl is-active "$timer_name" 2>/dev/null || true
systemctl list-timers --all "$timer_name" --no-pager || true
systemctl status "$timer_name" --no-pager || true
journalctl -u "$service_name" -n 100 --no-pager || true
REMOTE_STATUS
  exit 0
fi

if ! validate_activation_decision; then
  printf 'activation_decision=blocked\n' >&2
  exit 2
fi

print_summary
printf 'activation_decision=ready\n'

ssh "$REMOTE_HOST" 'bash -s' -- \
  "$SERVICE_NAME" \
  "$TIMER_NAME" \
  "$SERVICE_PATH" \
  "$TIMER_PATH" \
  "$REMOTE_CURRENT_DIR" \
  "$REMOTE_DB_PATH" \
  "$REMOTE_BACKUP_DIR" \
  "$REMOTE_LOG_DIR" \
  "$REMOTE_HEALTH_URL" \
  "$ON_CALENDAR" \
  "$PIPELINE_COMMAND" <<'REMOTE_INSTALL'
set -euo pipefail

service_name="$1"
timer_name="$2"
service_path="$3"
timer_path="$4"
working_dir="$5"
db_path="$6"
backup_dir="$7"
log_dir="$8"
health_url="$9"
on_calendar="${10}"
pipeline_command="${11}"

mkdir -p "$backup_dir" "$log_dir"
test -x "${working_dir}/scripts/run_daily_pipeline.sh"
test -f "$db_path"
curl -fsS "$health_url" >/tmp/pgc_daily_pipeline_health.json
cd "$working_dir"
PYTHONPATH=src python3 -m pgc_trading.cli.main ops health \
  --db-path "$db_path" \
  --health-url "$health_url" \
  --require-current-migrations

cat > "$service_path" <<SERVICE_UNIT
[Unit]
Description=PGC post-close daily pipeline
After=network-online.target pgc-api.service
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$working_dir
Environment=PYTHONPATH=$working_dir/src
Environment=PGC_DB_PATH=$db_path
Environment=PGC_DAILY_PIPELINE_LOG_DIR=$log_dir
Environment=TZ=Asia/Shanghai
ExecStartPre=/usr/bin/curl -fsS $health_url
ExecStart=$pipeline_command
SERVICE_UNIT

cat > "$timer_path" <<TIMER_UNIT
[Unit]
Description=Run PGC post-close daily pipeline after A-share close

[Timer]
OnCalendar=$on_calendar
Persistent=true
Unit=$service_name

[Install]
WantedBy=timers.target
TIMER_UNIT

systemctl daemon-reload
systemctl enable --now "$timer_name"
systemctl status "$timer_name" --no-pager
printf 'service_path=%s\n' "$service_path"
printf 'timer_path=%s\n' "$timer_path"
printf 'journal_command=journalctl -u %s -n 100 --no-pager\n' "$service_name"
printf 'rollback_command=systemctl disable --now %s\n' "$timer_name"
REMOTE_INSTALL
