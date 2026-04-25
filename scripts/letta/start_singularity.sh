#!/usr/bin/env bash
# Singularity / Apptainer deployment for HPC.
#
# Why this script does NOT use `apptainer instance start`:
#   Docker-derived SIFs have an empty %startscript, so `instance start`
#   only spawns appinit and never invokes the OCI ENTRYPOINT/CMD
#   (`docker-entrypoint.sh ./letta/server/startup.sh`). `apptainer run`
#   does invoke the OCI CMD via the runscript shim, which is what we
#   actually want.
#
# Why we don't bind ${DATA_ROOT}:/app/letta like the docker-compose path:
#   Docker named-volume mounts copy image content on first init, so the
#   compose volume preserves /app/letta source. Apptainer bind mounts
#   are pure overlays — they would mask the bundled Letta source
#   (including letta/server/startup.sh). We persist Postgres data
#   instead, since the Letta SIF starts an internal pgvector when no
#   external LETTA_PG_URI is set.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${ARI_LETTA_SIF:-${SCRIPT_DIR}/letta.sif}"
PGDATA_DIR="${ARI_LETTA_PGDATA:-${SLURM_TMPDIR:+${SLURM_TMPDIR}/letta-pgdata}}"
PGDATA_DIR="${PGDATA_DIR:-$HOME/.ari/letta-pgdata}"
PIDFILE="${ARI_LETTA_PIDFILE:-$HOME/.ari/letta.pid}"
LOG_DIR="${ARI_LETTA_LOG_DIR:-$HOME/.ari/letta-logs}"
# Persistent rw overlay for in-image writes (Postgres socket dir,
# /app/openapi_*.json, /var/run/redis, ...). Sized only by the host
# filesystem, unlike --writable-tmpfs which defaults to a few dozen MB
# and gets exhausted by Letta's openapi schema dump on startup.
OVERLAY_DIR="${ARI_LETTA_OVERLAY:-$HOME/.ari/letta-overlay}"
mkdir -p "${PGDATA_DIR}" "${LOG_DIR}" "${OVERLAY_DIR}" "$(dirname "${PIDFILE}")"

# Singularity scrubs most host env vars from the container by default,
# so the project's .env (which typically holds OPENAI_API_KEY etc.)
# must be passed in explicitly via --env-file. Otherwise agents created
# with openai/* embedding handles fail at archival_insert with no key.
ARI_ROOT="${ARI_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
ENV_FILE="${ENV_FILE:-$ARI_ROOT/.env}"
ENV_ARGS=()
if [[ -f "${ENV_FILE}" ]]; then
  echo "Passing provider keys from ${ENV_FILE} into the Letta container"
  ENV_ARGS+=(--env-file "${ENV_FILE}")
fi

RUNTIME="$(command -v singularity || command -v apptainer || true)"
if [[ -z "${RUNTIME}" ]]; then
  echo "ERROR: neither singularity nor apptainer is on PATH" >&2
  exit 1
fi

if [[ ! -f "${IMAGE}" ]]; then
  echo "pulling letta image → ${IMAGE}"
  "${RUNTIME}" pull "${IMAGE}" docker://letta/letta:latest
fi

# Idempotent restart: stop any prior `apptainer run` we launched, plus
# any leftover `apptainer instance` from older versions of this script.
if [[ -f "${PIDFILE}" ]]; then
  prev="$(cat "${PIDFILE}" 2>/dev/null || true)"
  if [[ -n "${prev}" ]] && kill -0 "${prev}" 2>/dev/null; then
    echo "Stopping previous Letta (pid=${prev})"
    kill "${prev}" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      kill -0 "${prev}" 2>/dev/null || break
      sleep 1
    done
    kill -9 "${prev}" 2>/dev/null || true
  fi
  rm -f "${PIDFILE}"
fi
"${RUNTIME}" instance stop ari-letta 2>/dev/null || true

# Apptainer shares the host PID/network namespace, so Postgres and Redis
# spawned with `&` inside the SIF survive when the apptainer parent
# dies. They keep listening on 5432/6379 with a stale FUSE mount, which
# causes opaque "Transport endpoint is not connected" errors on the
# next pgvector access. Reap any such orphans we own before restarting.
for port in 5432 6379; do
  owner="$(ss -ltnp 2>/dev/null | awk -v p=":${port}" '
    index($4, p) && match($0, /pid=[0-9]+/) {
      print substr($0, RSTART+4, RLENGTH-4); exit
    }')"
  if [[ -n "${owner}" ]] && \
     [[ "$(ps -o user= -p "${owner}" 2>/dev/null | tr -d ' ')" == "${USER}" ]]; then
    echo "Reaping orphan internal daemon on :${port} (pid=${owner})"
    kill "${owner}" 2>/dev/null || true
    sleep 1
    kill -9 "${owner}" 2>/dev/null || true
  fi
done

# --pwd /app: the SIF's OCI CMD is the relative path
#   "./letta/server/startup.sh"
# which Docker resolves under WORKDIR=/app. Apptainer inherits the host
# CWD instead, so we set it explicitly here.
#
# --overlay <dir>: persistent host-backed rw overlay for in-image
# writes (Postgres socket dir, /app/openapi_*.json, /var/run/redis,
# ...). Replaces --writable-tmpfs because that defaults to ~64MB which
# Letta's openapi schema dump exhausts on startup. PGDATA is bound
# separately so it isn't hidden inside the overlay.
nohup "${RUNTIME}" run \
  --pwd /app \
  --overlay "${OVERLAY_DIR}" \
  --bind "${PGDATA_DIR}:/var/lib/postgresql/data" \
  "${ENV_ARGS[@]}" \
  "${IMAGE}" \
  >"${LOG_DIR}/ari-letta.out" 2>"${LOG_DIR}/ari-letta.err" &
echo $! >"${PIDFILE}"
disown

echo "Letta starting (pid=$(cat "${PIDFILE}"))"
echo "PGDATA:   ${PGDATA_DIR}"
echo "Logs:     ${LOG_DIR}/ari-letta.{out,err}"
echo "Set LETTA_BASE_URL=http://localhost:8283 in your .env"
echo
echo "First boot performs Postgres initdb + alembic migration; the"
echo "health endpoint typically comes up in 30-60s. Tail the log with:"
echo "  tail -f ${LOG_DIR}/ari-letta.err"
