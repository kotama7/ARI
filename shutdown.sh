#!/usr/bin/env bash
# shutdown.sh — stop every long-running ARI service this host launched:
#
#   1. CLI shim server       (python -m ari.llm.cli_server) :8900
#   2. ARI Viz GUI           (python -m ari.viz.server)   :8765
#   3. ari-registry server   (uvicorn)                    :8290
#   4. Letta server          (apptainer run / pip)        :8283
#      + reap orphan postgres / redis-server (user-owned) that the
#        Letta SIF leaves behind when the apptainer parent dies.
#
# Tries pidfiles first ($HOME/.ari/*.pid), then falls back to apptainer
# instance stop + name-based pgrep so a half-broken state is still
# reaped. Only touches processes owned by ${USER}.
#
# Usage:
#   ./shutdown.sh           # stop everything
#   ./shutdown.sh shim      # stop only the CLI shim
#   ./shutdown.sh gui       # stop only the GUI
#   ./shutdown.sh registry  # stop only the registry
#   ./shutdown.sh letta     # stop only Letta (and its orphans)
set -euo pipefail

ARI_HOME="${ARI_HOME:-$HOME/.ari}"

SHIM_PIDFILE="${ARI_CLI_SHIM_PIDFILE:-${ARI_HOME}/cli-shim.pid}"
GUI_PIDFILE="${ARI_GUI_PIDFILE:-${ARI_HOME}/gui.pid}"
REGISTRY_DATA="${ARI_REGISTRY_DATA:-${ARI_HOME}/registry-data}"
REGISTRY_PIDFILE="${REGISTRY_DATA}/registry.pid"
# Singularity launcher writes letta.pid; pip launcher writes letta-pid
# (no dot). Handle both so we cover whichever mode start.sh picked.
LETTA_PIDFILES=(
  "${ARI_LETTA_PIDFILE:-${ARI_HOME}/letta.pid}"
  "${ARI_HOME}/letta-pid"
)

# Pretty output ------------------------------------------------------------
if [[ -t 1 ]]; then
  C_GREEN=$'\e[32m'; C_YELLOW=$'\e[33m'; C_RED=$'\e[31m'
  C_BOLD=$'\e[1m'; C_RESET=$'\e[0m'
else
  C_GREEN=""; C_YELLOW=""; C_RED=""; C_BOLD=""; C_RESET=""
fi
info()  { echo "${C_BOLD}[shutdown.sh]${C_RESET} $*"; }
ok()    { echo "${C_GREEN}[ok]${C_RESET} $*"; }
warn()  { echo "${C_YELLOW}[warn]${C_RESET} $*"; }

_pid_alive() {
  local pid="${1:-}"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

# Send SIGTERM, wait up to 10s for graceful exit, then SIGKILL.
_kill_pidfile() {
  local label="$1" pidfile="$2"
  if [[ ! -f "${pidfile}" ]]; then
    return 0
  fi
  local pid; pid="$(cat "${pidfile}" 2>/dev/null || true)"
  if _pid_alive "${pid}"; then
    info "Stopping ${label} (pid=${pid})"
    kill "${pid}" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      _pid_alive "${pid}" || break
      sleep 1
    done
    if _pid_alive "${pid}"; then
      warn "${label} did not exit on SIGTERM, sending SIGKILL"
      kill -9 "${pid}" 2>/dev/null || true
    fi
    ok "${label} stopped"
  else
    warn "${label}: pidfile ${pidfile} present but pid ${pid:-?} not running"
  fi
  rm -f "${pidfile}"
}

stop_shim() {
  _kill_pidfile "CLI shim" "${SHIM_PIDFILE}"
}

stop_gui() {
  _kill_pidfile "GUI" "${GUI_PIDFILE}"
}

stop_registry() {
  _kill_pidfile "Registry" "${REGISTRY_PIDFILE}"
}

# Letta is special: apptainer shares the host PID/network namespace, so
# postgres + redis-server spawned inside the SIF survive when the
# apptainer parent dies and keep holding :5432/:6379. We reap them by
# name (only $USER-owned) after killing the parent — mirrors the
# reap_orphans logic in scripts/letta/start_singularity.sh.
stop_letta() {
  local stopped=0
  for pf in "${LETTA_PIDFILES[@]}"; do
    if [[ -f "${pf}" ]]; then
      _kill_pidfile "Letta" "${pf}"
      stopped=1
    fi
  done
  if (( stopped == 0 )); then
    warn "no Letta pidfile found at ${LETTA_PIDFILES[*]}"
  fi

  # Best-effort: any apptainer instance that older launchers created.
  if command -v apptainer >/dev/null 2>&1; then
    apptainer instance stop ari-letta 2>/dev/null || true
  elif command -v singularity >/dev/null 2>&1; then
    singularity instance stop ari-letta 2>/dev/null || true
  fi

  # Reap orphan postgres / redis-server — user-owned only, exact name
  # match so other tenants on this host are untouched.
  local name pids pid
  for name in postgres redis-server; do
    pids="$(pgrep -u "${USER}" -x "${name}" 2>/dev/null || true)"
    [[ -z "${pids}" ]] && continue
    for pid in ${pids}; do
      info "Reaping orphan ${name} (pid=${pid})"
      kill "${pid}" 2>/dev/null || true
    done
  done
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

cmd="${1:-all}"
case "${cmd}" in
  all|"")
    stop_shim
    stop_gui
    stop_registry
    stop_letta
    ok "All ARI services stopped"
    ;;
  shim)     stop_shim ;;
  gui)      stop_gui ;;
  registry) stop_registry ;;
  letta)    stop_letta ;;
  -h|--help|help)
    sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    ;;
  *)
    echo "Unknown command: ${cmd}" >&2
    echo "Run '${BASH_SOURCE[0]} --help' for usage." >&2
    exit 2
    ;;
esac
