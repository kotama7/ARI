#!/usr/bin/env bash
# pip / container-less deployment.
# Brings up a single-user Letta server in a dedicated venv with SQLite
# storage. No Postgres, no Docker, no sudo — just Python.
set -euo pipefail

VENV="${ARI_LETTA_VENV:-$HOME/.ari/letta-venv}"
PIDFILE="${ARI_LETTA_PIDFILE:-$HOME/.ari/letta-pid}"
LOG="${ARI_LETTA_LOG:-$HOME/.ari/letta-pip.log}"

# Inherit provider API keys from the project's .env so embeddings
# and core LLM handles work. Without this, agents created with
# openai/* (or anthropic/*, gemini/*) hit Letta's embedding path
# with no key and surface as opaque 400s on every add_memory.
ARI_ROOT="${ARI_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
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

# Letta <0.10 is the pinned version for pip mode. Any Python 3.10+
# works; we just pick whatever python3 is first on PATH unless the
# caller overrides via ARI_LETTA_PYTHON.
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
# Letta ≥0.10 hardcoded Postgres at 127.0.0.1:5432 even when
# LETTA_PG_URI="" — SQLite mode is broken on those versions. Pin to
# the last release whose SQLite path actually works, and backfill the
# runtime deps that its manifest under-declares (asyncpg, sqlite-vec,
# e2b, e2b_code_interpreter).
python -m pip install --upgrade \
  "letta<0.10" "letta-client" \
  "asyncpg" "sqlite-vec" "e2b" "e2b_code_interpreter" >/dev/null

# SQLite store — no Postgres required (ancestor search uses the
# over-fetch fallback on this path; acceptable for laptop experiments).
export LETTA_PG_URI=""

mkdir -p "$(dirname "${LOG}")"
nohup letta server --host 127.0.0.1 --port 8283 >"${LOG}" 2>&1 &
echo $! >"${PIDFILE}"
echo "Letta pip-mode started (pid=$!)"
echo "Log: ${LOG}"
echo
echo "If the server fails to come up, check the log. Options:"
echo "  * Override Python:  ARI_LETTA_PYTHON=/path/to/python bash $0"
echo "  * Letta Cloud fallback (no local server):"
echo "      export LETTA_BASE_URL=https://api.letta.com"
echo "      export LETTA_API_KEY=<your key>"
