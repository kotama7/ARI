#!/usr/bin/env bash
# pip / container-less deployment.
# Brings up a single-user Letta server in a dedicated venv with SQLite
# storage. No Postgres, no Docker, no sudo — just Python.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${ARI_LETTA_VENV:-$HOME/.ari/letta-venv}"
PIDFILE="${ARI_LETTA_PIDFILE:-$HOME/.ari/letta-pid}"
LOG="${ARI_LETTA_LOG:-$HOME/.ari/letta-pip.log}"
LETTA_HOST="${ARI_LETTA_HOST:-127.0.0.1}"
LETTA_PORT="${ARI_LETTA_PORT:-8283}"

# Inherit provider API keys from the project's .env so embeddings
# and core LLM handles work. Without this, agents created with
# openai/* (or anthropic/*, gemini/*) hit Letta's embedding path
# with no key and surface as opaque 400s on every add_memory.
ARI_ROOT="${ARI_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
ENV_FILE="${ENV_FILE:-$ARI_ROOT/.env}"
if [[ -f "${ENV_FILE}" ]]; then
  echo "Loading provider keys from ${ENV_FILE}"
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    [[ "$line" != *=* ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    key="${key// /}"
    # strip optional surrounding quotes (single or double)
    val="${val%\"}"; val="${val#\"}"
    val="${val%\'}"; val="${val#\'}"
    # Don't override values already set in the parent shell.
    if [[ -z "${!key:-}" ]]; then
      export "${key}=${val}"
    fi
  done < "${ENV_FILE}"
fi

# The container-less path uses Letta 0.9.1, the last release whose SQLite
# server does not require a sidecar PostgreSQL.  ARI applies a reviewed one-line
# async refresh compatibility patch below for current SQLAlchemy.  The SIF and
# Compose deployments remain the native Letta 0.16.x paths.
PYBIN="${ARI_LETTA_PYTHON:-}"
if [[ -z "${PYBIN}" ]]; then
  for c in python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1; then PYBIN="$c"; break; fi
  done
fi
[[ -n "${PYBIN}" ]] || { echo "no python3 on PATH" >&2; exit 1; }
echo "Using interpreter: $(command -v "$PYBIN") ($("$PYBIN" --version))"

if [[ ! -d "${VENV}" ]]; then
  "${PYBIN}" -m venv "${VENV}"
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

python -m pip install --upgrade pip >/dev/null
# Pin both server and client: an unconstrained client upgrade can change the
# HTTP surface underneath this compatibility deployment.
python -m pip install --upgrade \
  "letta==0.9.1" "letta-client==0.1.324" \
  "asyncpg" "sqlite-vec" "e2b" "e2b_code_interpreter" "orjson" >/dev/null
python "${SCRIPT_DIR}/patch_091_missing_greenlet.py"

# SQLite store — no Postgres required (ancestor search uses the
# over-fetch fallback on this path; acceptable for laptop experiments).
export LETTA_PG_URI=""

mkdir -p "$(dirname "${LOG}")"
declare -a previous_pids=()
if [[ -f "${PIDFILE}" ]]; then
  previous_pids+=("$(cat "${PIDFILE}" 2>/dev/null || true)")
fi
# A crash between bind and PID-file update can leave a live server whose PID
# file is stale.  Include the actual listener, then verify its command before
# signalling anything; this also prevents a new process from health-checking
# an unrelated old server and declaring a failed bind successful.
if command -v lsof >/dev/null 2>&1; then
  while IFS= read -r listener_pid; do
    previous_pids+=("${listener_pid}")
  done < <(lsof -t -iTCP:"${LETTA_PORT}" -sTCP:LISTEN 2>/dev/null || true)
fi
declare -A seen_pids=()
for previous in "${previous_pids[@]}"; do
  if [[ ! "${previous}" =~ ^[0-9]+$ ]]; then
    continue
  fi
  if [[ -n "${seen_pids[${previous}]:-}" ]]; then
    continue
  fi
  seen_pids["${previous}"]=1
  if kill -0 "${previous}" 2>/dev/null; then
    previous_cmd="$(ps -p "${previous}" -o command= 2>/dev/null || true)"
    if [[ "${previous_cmd}" != *"letta server"* || "${previous_cmd}" != *"--port ${LETTA_PORT}"* ]]; then
      echo "Refusing to stop PID ${previous}: process does not identify the Letta listener on port ${LETTA_PORT}" >&2
      exit 1
    fi
    kill "${previous}" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      kill -0 "${previous}" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "${previous}" 2>/dev/null; then
      echo "Letta PID ${previous} did not stop" >&2
      exit 1
    fi
  fi
done
nohup letta server --host "${LETTA_HOST}" --port "${LETTA_PORT}" >"${LOG}" 2>&1 &
echo $! >"${PIDFILE}"
letta_pid=$!
ready=0
for _ in $(seq 1 30); do
  if ! kill -0 "${letta_pid}" 2>/dev/null; then
    break
  fi
  if curl -fsSL --max-time 2 "http://${LETTA_HOST}:${LETTA_PORT}/v1/health" >/dev/null 2>&1; then
    sleep 0.25
    if kill -0 "${letta_pid}" 2>/dev/null; then
      ready=1
      break
    fi
  fi
  sleep 1
done
if [[ "${ready}" != 1 ]]; then
  echo "Letta pip-mode failed its health check; see ${LOG}" >&2
  tail -n 40 "${LOG}" >&2 || true
  exit 1
fi
echo "Letta pip-mode started and healthy (pid=${letta_pid})"
echo "Log: ${LOG}"
echo
echo "If the server fails to come up, check the log. Options:"
echo "  * Override Python:  ARI_LETTA_PYTHON=/path/to/python bash $0"
echo "  * Letta Cloud fallback (no local server):"
echo "      export LETTA_BASE_URL=https://api.letta.com"
echo "      export LETTA_API_KEY=<your key>"
