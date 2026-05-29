#!/usr/bin/env bash
# scripts/registry/start_local.sh — uvicorn + sqlite, single-process.
# Suitable for laptop / dev. Production: see docker-compose.yml.
set -euo pipefail

ARI_REGISTRY_DATA="${ARI_REGISTRY_DATA:-$HOME/.ari/registry-data}"
ARI_REGISTRY_HOST="${ARI_REGISTRY_HOST:-127.0.0.1}"
ARI_REGISTRY_PORT="${ARI_REGISTRY_PORT:-8290}"

mkdir -p "$ARI_REGISTRY_DATA"
PIDFILE="$ARI_REGISTRY_DATA/registry.pid"
LOGFILE="$ARI_REGISTRY_DATA/registry.log"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "ari-registry already running (pid $(cat "$PIDFILE"))"
  echo "  url=http://$ARI_REGISTRY_HOST:$ARI_REGISTRY_PORT"
  exit 0
fi

# Prefer the project-local venv's `ari` so we don't accidentally run a
# stale ~/.local/bin/ari (Python 3.9, broken pydantic) or another env's
# ari that happens to be earlier on PATH. setup.sh creates this venv;
# fall back to PATH lookup for legacy installs.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARI_ROOT="${ARI_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
ARI_BIN="${ARI_BIN:-${ARI_ROOT}/.venv/bin/ari}"
[ -x "${ARI_BIN}" ] || ARI_BIN="ari"

export ARI_REGISTRY_DATA
echo "starting ari-registry on $ARI_REGISTRY_HOST:$ARI_REGISTRY_PORT (data=$ARI_REGISTRY_DATA)"
nohup "${ARI_BIN}" registry serve --host "$ARI_REGISTRY_HOST" --port "$ARI_REGISTRY_PORT" \
  >>"$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"
echo "  pid=$(cat "$PIDFILE")  log=$LOGFILE"
echo "  issue a token: ari registry token issue <user>"
