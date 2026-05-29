#!/usr/bin/env bash
# start.sh — bring up the four long-running ARI services on this host:
#
#   1. Letta server          (memory backend)          :8283
#   2. ari-registry server   (publish/clone backend)   :8290
#   3. ARI Viz GUI           (React dashboard)          :8765
#   4. CLI shim server       (claude/codex as OpenAI)   :8900
#
# Each service has its own PID + log files under $HOME/.ari/. Every
# invocation performs a clean restart — any prior instance is killed
# before the new one is launched.
#
# Usage:
#   ./start.sh              # restart all four
#   ./start.sh letta        # restart only the Letta server
#   ./start.sh registry     # restart only the registry
#   ./start.sh gui          # restart only the GUI
#   ./start.sh shim         # restart only the CLI shim
#   ./start.sh status       # show running services (no restart)
#   ./start.sh stop         # stop everything started by this script
set -euo pipefail

ARI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARI_HOME="${ARI_HOME:-$HOME/.ari}"
mkdir -p "${ARI_HOME}"

# Service config ------------------------------------------------------------
LETTA_PORT="${LETTA_PORT:-8283}"
REGISTRY_PORT="${ARI_REGISTRY_PORT:-8290}"
GUI_PORT="${ARI_GUI_PORT:-8765}"
SHIM_PORT="${ARI_CLI_SHIM_PORT:-8900}"

GUI_PIDFILE="${ARI_GUI_PIDFILE:-${ARI_HOME}/gui.pid}"
GUI_LOG="${ARI_GUI_LOG:-${ARI_HOME}/gui.log}"

# CLI shim — note ARI_CLI_SHIM_LOG is the module's log *level* (INFO/DEBUG),
# so the log *file* path uses a distinct env var.
SHIM_PIDFILE="${ARI_CLI_SHIM_PIDFILE:-${ARI_HOME}/cli-shim.pid}"
SHIM_LOG="${ARI_CLI_SHIM_LOGFILE:-${ARI_HOME}/cli-shim.log}"

LETTA_PIDFILE="${ARI_LETTA_PIDFILE:-${ARI_HOME}/letta.pid}"
REGISTRY_DATA="${ARI_REGISTRY_DATA:-${ARI_HOME}/registry-data}"
REGISTRY_PIDFILE="${REGISTRY_DATA}/registry.pid"

# Pretty output -------------------------------------------------------------
if [[ -t 1 ]]; then
  C_GREEN=$'\e[32m'; C_YELLOW=$'\e[33m'; C_RED=$'\e[31m'
  C_BOLD=$'\e[1m'; C_RESET=$'\e[0m'
else
  C_GREEN=""; C_YELLOW=""; C_RED=""; C_BOLD=""; C_RESET=""
fi

info()  { echo "${C_BOLD}[start.sh]${C_RESET} $*"; }
ok()    { echo "${C_GREEN}[ok]${C_RESET} $*"; }
warn()  { echo "${C_YELLOW}[warn]${C_RESET} $*"; }
fail()  { echo "${C_RED}[fail]${C_RESET} $*" >&2; }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_pid_alive() {
  local pid="${1:-}"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

_port_open() {
  local port="$1"
  # ss is in default PATH on Linux; fall back to /bin/ss for sandboxed shells.
  ss -ltn 2>/dev/null | awk -v p=":${port}" 'index($4, p) {found=1} END{exit !found}'
}

_http_ok() {
  local url="$1"
  curl -fsS -m 2 -o /dev/null "${url}" 2>/dev/null
}

_wait_until() {
  local what="$1" check_cmd="$2" deadline="${3:-90}" need="${4:-1}"
  local end=$(( $(date +%s) + deadline ))
  local streak=0
  # Require ${need} consecutive successes — a single passing check during
  # restarts can come from the old instance still draining its accept
  # queue while the new one is still in alembic migration.
  while (( $(date +%s) < end )); do
    if eval "${check_cmd}" >/dev/null 2>&1; then
      streak=$((streak + 1))
      if (( streak >= need )); then
        return 0
      fi
    else
      streak=0
    fi
    sleep 2
  done
  fail "timeout waiting for ${what}"
  return 1
}

# ---------------------------------------------------------------------------
# Letta — defer to the existing scripts/letta/start_*.sh launchers.
# Auto-pick apptainer when available + SIF exists, else pip.
# Both launcher scripts already kill any prior PID, so re-running here
# performs a clean restart.
# ---------------------------------------------------------------------------
start_letta() {
  local mode="${ARI_LETTA_MODE:-auto}"
  local sif="${ARI_LETTA_SIF:-${ARI_ROOT}/scripts/letta/letta.sif}"
  if [[ "${mode}" == "auto" ]]; then
    if (command -v apptainer >/dev/null 2>&1 || command -v singularity >/dev/null 2>&1) \
       && [[ -f "${sif}" ]]; then
      mode="singularity"
    else
      mode="pip"
    fi
  fi

  case "${mode}" in
    singularity|apptainer)
      info "Starting Letta via apptainer (${sif})"
      bash "${ARI_ROOT}/scripts/letta/start_singularity.sh"
      ;;
    pip)
      info "Starting Letta via pip"
      bash "${ARI_ROOT}/scripts/letta/start_pip.sh"
      ;;
    *)
      fail "Unknown ARI_LETTA_MODE=${mode} (expected auto|singularity|pip)"
      return 1
      ;;
  esac

  # Letta does an alembic migration on every boot — health may flicker
  # off mid-restart. Require 3 consecutive 200s and allow up to 5 min.
  _wait_until "Letta health" \
    "_http_ok http://localhost:${LETTA_PORT}/v1/health/" 300 3 || return 1
  ok "Letta ready at http://localhost:${LETTA_PORT}"
}

# ---------------------------------------------------------------------------
# ari-registry — the server backing `ari clone ari://...` and `ari publish`.
# scripts/registry/start_local.sh refuses to relaunch when its PID is
# alive, so we kill any prior instance ourselves before invoking it.
# ---------------------------------------------------------------------------
start_registry() {
  if [[ -f "${REGISTRY_PIDFILE}" ]] && _pid_alive "$(cat "${REGISTRY_PIDFILE}" 2>/dev/null)"; then
    _kill_pidfile "Registry" "${REGISTRY_PIDFILE}"
  fi
  info "Starting ari-registry on :${REGISTRY_PORT}"
  ARI_REGISTRY_DATA="${REGISTRY_DATA}" \
  ARI_REGISTRY_PORT="${REGISTRY_PORT}" \
    bash "${ARI_ROOT}/scripts/registry/start_local.sh"

  _wait_until "registry health" \
    "_http_ok http://127.0.0.1:${REGISTRY_PORT}/healthz" 30 || return 1
  ok "ari-registry ready at http://127.0.0.1:${REGISTRY_PORT}"
}

# ---------------------------------------------------------------------------
# Viz GUI — `python -m ari.viz.server` (no checkpoint => user picks one in
# the GUI). Manage PID/log directly because there's no dedicated launcher.
# ---------------------------------------------------------------------------
start_gui() {
  if [[ -f "${GUI_PIDFILE}" ]] && _pid_alive "$(cat "${GUI_PIDFILE}" 2>/dev/null)"; then
    _kill_pidfile "GUI" "${GUI_PIDFILE}"
  fi

  # Prefer the project-local venv's python so pydantic / ari deps are
  # the version set the lockfile pins (see scripts/setup/install_deps.sh).
  # Falling through to `python` on PATH used to land on a stale
  # ~/.local user-site with mismatched pydantic-core.
  VIZ_PY="${ARI_PY:-${ARI_ROOT}/.venv/bin/python}"
  [ -x "${VIZ_PY}" ] || VIZ_PY="python"

  if ! "${VIZ_PY}" -c "import ari.viz.server" 2>/dev/null; then
    fail "ari.viz.server not importable via ${VIZ_PY} — did you run setup.sh?"
    return 1
  fi

  info "Starting ARI Viz on :${GUI_PORT}"
  nohup "${VIZ_PY}" -m ari.viz.server --port "${GUI_PORT}" \
    >>"${GUI_LOG}" 2>&1 &
  echo $! > "${GUI_PIDFILE}"
  disown || true

  _wait_until "GUI port" "_port_open ${GUI_PORT}" 30 || return 1
  ok "ARI Viz ready at http://localhost:${GUI_PORT}/  (log=${GUI_LOG})"
}

# ---------------------------------------------------------------------------
# CLI shim — `python -m ari.llm.cli_server`. Exposes claude -p / codex exec
# as an OpenAI-compatible endpoint so ARI can register them as an LLM backend
# (backend=openai, base_url=http://localhost:${SHIM_PORT}/v1). The server is a
# passive listener; it only spawns the CLIs when a request arrives.
# ---------------------------------------------------------------------------
start_shim() {
  if [[ -f "${SHIM_PIDFILE}" ]] && _pid_alive "$(cat "${SHIM_PIDFILE}" 2>/dev/null)"; then
    _kill_pidfile "CLI shim" "${SHIM_PIDFILE}"
  fi

  SHIM_PY="${ARI_PY:-${ARI_ROOT}/.venv/bin/python}"
  [ -x "${SHIM_PY}" ] || SHIM_PY="python"

  if ! "${SHIM_PY}" -c "import ari.llm.cli_server" 2>/dev/null; then
    fail "ari.llm.cli_server not importable via ${SHIM_PY} — did you run setup.sh?"
    return 1
  fi

  info "Starting ARI CLI shim on :${SHIM_PORT}"
  nohup "${SHIM_PY}" -m ari.llm.cli_server --port "${SHIM_PORT}" \
    >>"${SHIM_LOG}" 2>&1 &
  echo $! > "${SHIM_PIDFILE}"
  disown || true

  _wait_until "CLI shim health" \
    "_http_ok http://localhost:${SHIM_PORT}/healthz" 30 || return 1
  ok "ARI CLI shim ready at http://localhost:${SHIM_PORT}/v1  (log=${SHIM_LOG})"
}

# ---------------------------------------------------------------------------
# Status / stop
# ---------------------------------------------------------------------------
status() {
  local letta_status registry_status gui_status
  if _http_ok "http://localhost:${LETTA_PORT}/v1/health/"; then
    letta_status="${C_GREEN}up${C_RESET}"
  else
    letta_status="${C_RED}down${C_RESET}"
  fi
  if _http_ok "http://127.0.0.1:${REGISTRY_PORT}/healthz"; then
    registry_status="${C_GREEN}up${C_RESET}"
  else
    registry_status="${C_RED}down${C_RESET}"
  fi
  if [[ -f "${GUI_PIDFILE}" ]] && _pid_alive "$(cat "${GUI_PIDFILE}" 2>/dev/null)"; then
    gui_status="${C_GREEN}up${C_RESET} (pid=$(cat "${GUI_PIDFILE}"))"
  else
    gui_status="${C_RED}down${C_RESET}"
  fi
  local shim_status
  if _http_ok "http://localhost:${SHIM_PORT}/healthz"; then
    shim_status="${C_GREEN}up${C_RESET}"
  else
    shim_status="${C_RED}down${C_RESET}"
  fi
  echo
  echo "  Letta     :${LETTA_PORT}   ${letta_status}"
  echo "  Registry  :${REGISTRY_PORT}   ${registry_status}"
  echo "  GUI       :${GUI_PORT}   ${gui_status}"
  echo "  CLI shim  :${SHIM_PORT}   ${shim_status}"
  echo
}

_kill_pidfile() {
  local label="$1" pidfile="$2"
  [[ -f "${pidfile}" ]] || { warn "${label}: no pidfile at ${pidfile}"; return 0; }
  local pid; pid="$(cat "${pidfile}" 2>/dev/null || true)"
  if _pid_alive "${pid}"; then
    info "Stopping ${label} (pid=${pid})"
    kill "${pid}" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      _pid_alive "${pid}" || break
      sleep 1
    done
    _pid_alive "${pid}" && kill -9 "${pid}" 2>/dev/null || true
  else
    warn "${label}: pid ${pid:-?} not running"
  fi
  rm -f "${pidfile}"
}

stop_all() {
  _kill_pidfile "CLI shim" "${SHIM_PIDFILE}"
  _kill_pidfile "GUI"      "${GUI_PIDFILE}"
  _kill_pidfile "Registry" "${REGISTRY_PIDFILE}"
  _kill_pidfile "Letta"    "${LETTA_PIDFILE}"
  ok "All services stopped"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
cmd="${1:-all}"
case "${cmd}" in
  all|"")
    start_letta
    start_registry
    start_gui
    start_shim
    status
    ;;
  letta)    start_letta;    status ;;
  registry) start_registry; status ;;
  gui)      start_gui;      status ;;
  shim)     start_shim;     status ;;
  status)   status ;;
  stop)     stop_all ;;
  -h|--help|help)
    sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    ;;
  *)
    fail "Unknown command: ${cmd}"
    fail "Run '${BASH_SOURCE[0]} --help' for usage."
    exit 2
    ;;
esac
