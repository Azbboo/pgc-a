#!/usr/bin/env bash
set -euo pipefail

OPEN_DESIGN_DIR="${OPEN_DESIGN_DIR:-/Users/azboo/Desktop/Person/open-design}"
NODE24_BIN="${NODE24_BIN:-/Users/azboo/.nvm/versions/node/v24.15.0/bin}"
CODEX_BIN_DIR="${CODEX_BIN_DIR:-/Applications/Codex.app/Contents/Resources}"

if [[ ! -d "$OPEN_DESIGN_DIR" ]]; then
  echo "Open Design directory not found: $OPEN_DESIGN_DIR" >&2
  exit 1
fi

if [[ ! -x "$NODE24_BIN/node" ]]; then
  echo "Node 24 runtime not found: $NODE24_BIN/node" >&2
  exit 1
fi

if [[ ! -x "$CODEX_BIN_DIR/codex" ]]; then
  echo "Codex CLI not found: $CODEX_BIN_DIR/codex" >&2
  exit 1
fi

cd "$OPEN_DESIGN_DIR"

export PATH="$NODE24_BIN:$CODEX_BIN_DIR:$PATH"
export OD_CODEX_DISABLE_PLUGINS="${OD_CODEX_DISABLE_PLUGINS:-1}"

exec corepack pnpm tools-dev run web
