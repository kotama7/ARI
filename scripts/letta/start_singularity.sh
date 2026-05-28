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
# /app/openapi_*.json, /var/run/redis, ...). We use an ext3 *image*
# file rather than a host directory because Singularity-CE in setuid
# mode refuses sandbox-style (directory) overlays for non-root users
# ("only root user can use sandbox as overlay in setuid mode"). The
# image is sparse, so the configured size is an upper bound, not an
# upfront allocation — typical actual usage is a few MB.
#
# Replaces the older --writable-tmpfs path, which capped at ~64 MiB
# and was exhausted by Letta's openapi schema dump on startup.
OVERLAY_IMG="${ARI_LETTA_OVERLAY:-$HOME/.ari/letta-overlay.img}"
OVERLAY_SIZE_MIB="${ARI_LETTA_OVERLAY_SIZE_MIB:-1024}"
mkdir -p "${PGDATA_DIR}" "${LOG_DIR}" "$(dirname "${OVERLAY_IMG}")" "$(dirname "${PIDFILE}")"

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

# Materialize the ext3 overlay image on first launch. If a legacy
# directory exists at the same path (older revisions of this script
# defaulted to a directory overlay), refuse to clobber it and let the
# user clean up explicitly — the contents may include a previous
# Letta's openapi dump or Redis state.
if [[ -d "${OVERLAY_IMG}" ]]; then
  echo "ERROR: ${OVERLAY_IMG} is a directory (legacy sandbox overlay)." >&2
  echo "  Singularity-CE setuid mode rejects directory overlays for"  >&2
  echo "  non-root. Remove it (rm -rf '${OVERLAY_IMG}') or point"    >&2
  echo "  ARI_LETTA_OVERLAY at a new .img path."                      >&2
  exit 1
fi
if [[ ! -f "${OVERLAY_IMG}" ]]; then
  # --create-dir is critical: the bare ext3 image has every path owned
  # by root, so when overlayfs copy-ups happen the upper /app inherits
  # root ownership and Letta (running as the host user under setuid
  # Singularity) fails to write /app/openapi_*.json with EACCES.
  # Pre-creating these paths in the overlay upper layer makes them
  # owned by the host user, while overlayfs still merges in the lower
  # layer's /app/letta/server/... source from the image.
  #
  #   /app       — Letta dumps openapi_*.json into its WORKDIR
  #   /var/run   — Redis writes its pid/socket here
  echo "creating ext3 overlay (${OVERLAY_SIZE_MIB} MiB, sparse) → ${OVERLAY_IMG}"
  "${RUNTIME}" overlay create \
    --size "${OVERLAY_SIZE_MIB}" \
    --sparse \
    --create-dir /app \
    --create-dir /var/run \
    "${OVERLAY_IMG}"
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
# dies (either via this script's SIGTERM above, or via an external
# crash). They get reparented to PID 1 and keep listening on 5432/6379
# with a stale FUSE mount, which causes opaque "Transport endpoint is
# not connected" errors on the next pgvector access.
#
# We scan by *process name* (not port) so the reap is robust against:
#   - `ss -ltnp` declining to attribute a PID to a listener (e.g.
#     IPv4 :5432 on this host shows up without `pid=`),
#   - multiple listeners on the same port (IPv4 + IPv6), where the
#     previous port-based awk-then-exit logic only caught the first.
# `pgrep -u $USER -x` matches only our processes by exact comm, so
# foreign-user daemons sharing the host network namespace are left
# alone.
reap_orphans() {
  local name pids pid
  for name in postgres redis-server; do
    pids="$(pgrep -u "${USER}" -x "${name}" 2>/dev/null || true)"
    [[ -z "${pids}" ]] && continue
    for pid in ${pids}; do
      echo "Reaping orphan ${name} (pid=${pid})"
      kill "${pid}" 2>/dev/null || true
    done
  done
  # Give children a chance to checkpoint/exit cleanly, then SIGKILL
  # whatever is still around so the new container can bind 5432/6379.
  for _ in 1 2 3 4 5; do
    pgrep -u "${USER}" -x postgres >/dev/null 2>&1 || \
      pgrep -u "${USER}" -x redis-server >/dev/null 2>&1 || break
    sleep 1
  done
  for name in postgres redis-server; do
    pgrep -u "${USER}" -x "${name}" 2>/dev/null \
      | xargs -r kill -9 2>/dev/null || true
  done
}
reap_orphans

# --pwd /app: the SIF's OCI CMD is the relative path
#   "./letta/server/startup.sh"
# which Docker resolves under WORKDIR=/app. Apptainer inherits the host
# CWD instead, so we set it explicitly here.
#
# --overlay <img>: persistent ext3 image overlay for in-image writes
# (Postgres socket dir, /app/openapi_*.json, /var/run/redis, ...).
# Image form (not directory) is required because Singularity-CE in
# setuid mode forbids sandbox overlays for non-root. Sparse image, so
# the configured size is an upper bound. Replaces --writable-tmpfs,
# which capped at ~64MB and was exhausted by Letta's openapi schema
# dump on startup. PGDATA is bound separately so it isn't hidden
# inside the overlay.
nohup "${RUNTIME}" run \
  --pwd /app \
  --overlay "${OVERLAY_IMG}" \
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
