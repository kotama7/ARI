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

export ARI_REGISTRY_DATA
echo "starting ari-registry on $ARI_REGISTRY_HOST:$ARI_REGISTRY_PORT (data=$ARI_REGISTRY_DATA)"
nohup ari registry serve --host "$ARI_REGISTRY_HOST" --port "$ARI_REGISTRY_PORT" \
  >>"$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"
echo "  pid=$(cat "$PIDFILE")  log=$LOGFILE"
echo "  issue a token: ari registry token issue <user>"
