#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${PGC_REMOTE_HOST:-root@150.158.121.150}"
REMOTE_DB_PATH="${PGC_REMOTE_DB_PATH:-/opt/pgc/data/pgc_trading.db}"
REMOTE_BACKUP_DIR="${PGC_REMOTE_BACKUP_DIR:-/opt/pgc/backups}"
REMOTE_RELEASE_DIR="${PGC_REMOTE_RELEASE_DIR:-/opt/pgc/releases}"
REMOTE_CURRENT_DIR="${PGC_REMOTE_CURRENT_DIR:-/opt/pgc/app}"
REMOTE_SERVICE="${PGC_REMOTE_SERVICE:-pgc-api.service}"
REMOTE_HEALTH_URL="${PGC_REMOTE_HEALTH_URL:-http://127.0.0.1:8020/api/health}"
REMOTE_REVISION_PATH="${PGC_REMOTE_REVISION_PATH:-/opt/pgc/.deployed-revision}"
REMOTE_RELEASE_MARKER="${PGC_REMOTE_RELEASE_MARKER:-/opt/pgc/.deployed-release}"
ARTIFACT_DIR="${PGC_ARTIFACT_DIR:-.pgc-release}"
RELEASE_TAG="${PGC_RELEASE_TAG:-}"
API_WRITE_TOKEN="${PGC_API_WRITE_TOKEN:-}"

usage() {
  cat <<'USAGE'
Usage: deploy_remote.sh [--dry-run] [--release-tag TAG] [--create-git-tag] [--skip-tests] [--allow-dirty]

Build and deploy a tagged PGC release through the standard M20 sequence:
version tag -> local tests -> remote backup -> source upload -> remote migrations
-> service restart -> /api/health gate.

Environment overrides:
  PGC_REMOTE_HOST         default: root@150.158.121.150
  PGC_REMOTE_DB_PATH      default: /opt/pgc/data/pgc_trading.db
  PGC_REMOTE_BACKUP_DIR   default: /opt/pgc/backups
  PGC_REMOTE_RELEASE_DIR  default: /opt/pgc/releases
  PGC_REMOTE_CURRENT_DIR  default: /opt/pgc/app
  PGC_REMOTE_SERVICE      default: pgc-api.service
  PGC_REMOTE_HEALTH_URL   default: http://127.0.0.1:8020/api/health
  PGC_REMOTE_REVISION_PATH default: /opt/pgc/.deployed-revision
  PGC_REMOTE_RELEASE_MARKER default: /opt/pgc/.deployed-release
  PGC_RELEASE_TAG         optional explicit release tag
  PGC_ARTIFACT_DIR        default: .pgc-release
  PGC_API_WRITE_TOKEN     optional API write-token value for remote systemd

Examples:
  scripts/deploy_remote.sh --dry-run
  scripts/deploy_remote.sh --release-tag pgc-v0.1.0-20260508-gabc1234
USAGE
}

DRY_RUN=0
CREATE_GIT_TAG=0
SKIP_TESTS=0
ALLOW_DIRTY=0

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --release-tag)
      RELEASE_TAG="${2:-}"
      if [[ -z "$RELEASE_TAG" ]]; then
        printf 'deploy error: --release-tag requires a value\n' >&2
        exit 2
      fi
      shift 2
      ;;
    --create-git-tag)
      CREATE_GIT_TAG=1
      shift
      ;;
    --skip-tests)
      SKIP_TESTS=1
      shift
      ;;
    --allow-dirty)
      ALLOW_DIRTY=1
      shift
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GIT_SHA_FULL="$(git rev-parse HEAD)"

if [[ -z "$RELEASE_TAG" ]]; then
  GIT_SHA="$(git rev-parse --short=12 HEAD)"
  RELEASE_TAG="$(PYTHONPATH=src python3 -m pgc_trading.cli.main ops version --git-sha "$GIT_SHA" | awk -F= '/^release_tag=/{print $2}')"
fi

ARTIFACT_PATH="${ARTIFACT_DIR}/${RELEASE_TAG}.tar.gz"
REMOTE_ARTIFACT_PATH="${REMOTE_RELEASE_DIR}/${RELEASE_TAG}.tar.gz"
WORKTREE_DIRTY=0
if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  WORKTREE_DIRTY=1
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf 'release_tag=%s\n' "$RELEASE_TAG"
  printf 'remote_host=%s\n' "$REMOTE_HOST"
  printf 'remote_db=%s\n' "$REMOTE_DB_PATH"
  printf 'remote_backup_dir=%s\n' "$REMOTE_BACKUP_DIR"
  printf 'remote_release_dir=%s\n' "$REMOTE_RELEASE_DIR"
  printf 'remote_current_dir=%s\n' "$REMOTE_CURRENT_DIR"
  printf 'remote_service=%s\n' "$REMOTE_SERVICE"
  printf 'remote_health_url=%s\n' "$REMOTE_HEALTH_URL"
  printf 'remote_revision_path=%s\n' "$REMOTE_REVISION_PATH"
  printf 'remote_release_marker=%s\n' "$REMOTE_RELEASE_MARKER"
  printf 'artifact_path=%s\n' "$ARTIFACT_PATH"
  printf 'remote_artifact_path=%s\n' "$REMOTE_ARTIFACT_PATH"
  printf 'git_sha=%s\n' "$GIT_SHA_FULL"
  printf 'dirty_worktree=%s\n' "$([[ "$WORKTREE_DIRTY" -eq 1 ]] && printf yes || printf no)"
  printf 'allow_dirty=%s\n' "$([[ "$ALLOW_DIRTY" -eq 1 ]] && printf yes || printf no)"
  printf 'would_run_tests=%s\n' "$([[ "$SKIP_TESTS" -eq 1 ]] && printf no || printf yes)"
  scripts/backup_remote_pgc_db.sh --dry-run
  printf 'would_create_git_tag=%s\n' "$([[ "$CREATE_GIT_TAG" -eq 1 ]] && printf yes || printf no)"
  printf 'would_create_artifact=git archive --format=tar.gz -o %s HEAD\n' "$ARTIFACT_PATH"
  printf 'would_upload=scp %s %s:%s\n' "$ARTIFACT_PATH" "$REMOTE_HOST" "$REMOTE_ARTIFACT_PATH"
  printf 'would_remote_migrate=PYTHONPATH=<release>/src python3 -m pgc_trading.storage.migrate --db-path %s\n' "$REMOTE_DB_PATH"
  if [[ -n "$API_WRITE_TOKEN" ]]; then
    printf 'would_systemd_override=WorkingDirectory=%s PYTHONPATH=%s/src PGC_DB_PATH=%s PGC_API_WRITE_TOKEN=<redacted>\n' "$REMOTE_CURRENT_DIR" "$REMOTE_CURRENT_DIR" "$REMOTE_DB_PATH"
  else
    printf 'would_systemd_override=WorkingDirectory=%s PYTHONPATH=%s/src PGC_DB_PATH=%s PGC_API_WRITE_TOKEN=<preserve-existing-if-present>\n' "$REMOTE_CURRENT_DIR" "$REMOTE_CURRENT_DIR" "$REMOTE_DB_PATH"
  fi
  printf 'would_restart=systemctl restart %s\n' "$REMOTE_SERVICE"
  printf 'would_health_check=curl -fsS %s\n' "$REMOTE_HEALTH_URL"
  printf 'would_write_revision=%s\n' "$REMOTE_REVISION_PATH"
  printf 'would_write_release_marker=%s\n' "$REMOTE_RELEASE_MARKER"
  exit 0
fi

if [[ "$WORKTREE_DIRTY" -eq 1 && "$ALLOW_DIRTY" -ne 1 ]]; then
  printf 'deploy error: worktree has uncommitted changes; commit them or pass --allow-dirty\n' >&2
  exit 2
fi

if [[ "$SKIP_TESTS" -eq 0 ]]; then
  PYTHONPATH=src python3 -m unittest discover -s tests
fi

if [[ "$CREATE_GIT_TAG" -eq 1 ]]; then
  if git rev-parse -q --verify "refs/tags/${RELEASE_TAG}" >/dev/null; then
    printf 'deploy error: git tag already exists: %s\n' "$RELEASE_TAG" >&2
    exit 2
  fi
  git tag "$RELEASE_TAG"
fi

mkdir -p "$ARTIFACT_DIR"
if [[ -e "$ARTIFACT_PATH" ]]; then
  printf 'deploy error: artifact already exists: %s\n' "$ARTIFACT_PATH" >&2
  exit 2
fi

BACKUP_PATH="$(scripts/backup_remote_pgc_db.sh)"
git archive --format=tar.gz -o "$ARTIFACT_PATH" HEAD

ssh "$REMOTE_HOST" 'bash -s' -- "$REMOTE_RELEASE_DIR" <<'REMOTE_PREP'
set -euo pipefail
release_root="$1"
mkdir -p "$release_root"
REMOTE_PREP

scp "$ARTIFACT_PATH" "$REMOTE_HOST:$REMOTE_ARTIFACT_PATH"

ssh "$REMOTE_HOST" 'bash -s' -- \
  "$RELEASE_TAG" \
  "$REMOTE_RELEASE_DIR" \
  "$REMOTE_CURRENT_DIR" \
  "$REMOTE_DB_PATH" \
  "$REMOTE_SERVICE" \
  "$REMOTE_HEALTH_URL" \
  "$REMOTE_ARTIFACT_PATH" \
  "$GIT_SHA_FULL" \
  "$REMOTE_REVISION_PATH" \
  "$REMOTE_RELEASE_MARKER" \
  "$API_WRITE_TOKEN" <<'REMOTE_DEPLOY'
set -euo pipefail

release_tag="$1"
release_root="$2"
current_dir="$3"
db_path="$4"
service="$5"
health_url="$6"
artifact_path="$7"
git_sha="$8"
revision_path="$9"
release_marker="${10}"
api_write_token="${11}"
release_dir="${release_root}/${release_tag}"
service_override_dir="/etc/systemd/system/${service}.d"
service_override_path="${service_override_dir}/pgc-release.conf"

systemd_env_value() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '"%s"' "$value"
}

preserve_existing_api_write_token() {
  local path="$1"
  if [[ -f "$path" ]]; then
    grep -E '^Environment=PGC_API_WRITE_TOKEN=' "$path" | tail -n 1 || true
  fi
}

if [[ -e "$release_dir" ]]; then
  printf 'deploy error: release directory already exists: %s\n' "$release_dir" >&2
  exit 2
fi
if [[ -e "$current_dir" && ! -L "$current_dir" ]]; then
  printf 'deploy error: current dir exists and is not a symlink: %s\n' "$current_dir" >&2
  exit 2
fi

mkdir -p "$release_dir"
mkdir -p "$(dirname "$current_dir")"
test -s "$artifact_path"
tar -xzf "$artifact_path" -C "$release_dir"
PYTHONPATH="${release_dir}/src" python3 -m pgc_trading.storage.migrate --db-path "$db_path"
ln -sfn "$release_dir" "$current_dir"
mkdir -p "$service_override_dir"
api_write_token_line=""
if [[ -n "$api_write_token" ]]; then
  api_write_token_line="Environment=PGC_API_WRITE_TOKEN=$(systemd_env_value "$api_write_token")"
else
  api_write_token_line="$(preserve_existing_api_write_token "$service_override_path")"
fi
cat > "$service_override_path" <<SERVICE_OVERRIDE
[Service]
WorkingDirectory=$current_dir
Environment=PYTHONPATH=$current_dir/src
Environment=PGC_DB_PATH=$db_path
SERVICE_OVERRIDE
if [[ -n "$api_write_token_line" ]]; then
  printf '%s\n' "$api_write_token_line" >> "$service_override_path"
fi
systemctl daemon-reload
systemctl restart "$service"

for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS "$health_url" >/tmp/pgc_deploy_health.json; then
    mkdir -p "$(dirname "$revision_path")" "$(dirname "$release_marker")"
    printf '%s\n' "$git_sha" > "$revision_path"
    printf '%s\n' "$release_tag" > "$release_marker"
    printf 'release_dir=%s\n' "$release_dir"
    printf 'service_override=%s\n' "$service_override_path"
    printf 'health_ok=%s\n' "$health_url"
    cat /tmp/pgc_deploy_health.json
    printf '\n'
    exit 0
  fi
  sleep 2
done

systemctl status --no-pager "$service" || true
printf 'deploy error: /api/health did not pass after restart\n' >&2
exit 1
REMOTE_DEPLOY

printf 'release_tag=%s\n' "$RELEASE_TAG"
printf 'backup_path=%s\n' "$BACKUP_PATH"
printf 'artifact_path=%s\n' "$ARTIFACT_PATH"
printf 'git_sha=%s\n' "$GIT_SHA_FULL"
