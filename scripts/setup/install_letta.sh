#!/usr/bin/env bash
# ============================================================================
# install_letta.sh
#   Brings up a local Letta for new ARI installs. Auto-detects the best
#   deployment path (docker > singularity > pip) and records the choice
#   in .env so subsequent ari run / ari viz re-attempt the same path.
# ============================================================================

# Helper: call m() if it yields a non-empty string, else use the literal.
# messages.sh has no Letta strings yet, so this keeps the UI readable
# across languages until translations are added.
m_safe() {
  local key="$1"; local default="$2"
  local out=""
  if declare -F m >/dev/null 2>&1; then
    out="$(m "$key" 2>/dev/null)"
  fi
  if [ -z "$out" ]; then
    printf '%s' "$default"
  else
    printf '%s' "$out"
  fi
}

# Stub _env_append_if_absent when it isn't yet defined (e.g. when this
# module is sourced in a non-setup.sh context). The real implementation
# lives in setup_env.sh.
if ! declare -F _env_append_if_absent >/dev/null 2>&1; then
  _env_append_if_absent() {
    local line="$1"
    local key="${line%%=*}"
    key="${key# }"; key="${key#\#}"; key="${key# }"
    key="${key%%=*}"
    local env_file="${ENV_FILE:-$ARI_ROOT/.env}"
    [ -f "$env_file" ] || return 0
    if ! grep -qE "^[[:space:]]*#?[[:space:]]*${key}=" "$env_file" 2>/dev/null; then
      printf '%s\n' "$line" >> "$env_file"
    fi
  }
fi

echo ""
echo -e "${BOLD}  🐜 $(m_safe install_letta_title "Installing Letta (memory backend)")${RESET}"
echo ""

# Optional escape hatch — CI / container builds set SKIP_LETTA_SETUP=1.
if [[ "${SKIP_LETTA_SETUP:-0}" == "1" ]]; then
  info "$(m_safe install_letta_skip "SKIP_LETTA_SETUP=1 → skipping Letta install")"
  return 0 2>/dev/null || exit 0
fi

# If Letta is already reachable, we're done.
URL="${LETTA_BASE_URL:-http://localhost:8283}"
if curl -fsS "${URL}/v1/health/" >/dev/null 2>&1 \
    || curl -fsS "${URL}/v1/health"  >/dev/null 2>&1; then
  ok "$(m_safe install_letta_ext "Using external Letta at ${URL}")"
  _env_append_if_absent "LETTA_BASE_URL=${URL}"
  return 0 2>/dev/null || exit 0
fi

# Pick a deployment path based on what actually works (not just what's on PATH).
# docker may be installed but the daemon socket inaccessible — fall back.
_docker_works() {
  command -v docker >/dev/null 2>&1 || return 1
  docker info >/dev/null 2>&1
}

ARI_DETECTED_LETTA_PATH="none"
ON_HPC=0
if [[ -n "${SLURM_CLUSTER_NAME:-}" ]] || [[ -n "${SLURM_JOB_ID:-}" ]]; then
  ON_HPC=1
fi
if _docker_works && [[ "${ON_HPC}" -eq 0 ]]; then
  ARI_DETECTED_LETTA_PATH="docker"
elif command -v singularity >/dev/null 2>&1 || command -v apptainer >/dev/null 2>&1; then
  ARI_DETECTED_LETTA_PATH="singularity"
elif command -v python3 >/dev/null 2>&1; then
  ARI_DETECTED_LETTA_PATH="pip"
fi

# Warn when docker is present but unusable — common on systems where the
# user isn't in the `docker` group.
if command -v docker >/dev/null 2>&1 && ! _docker_works; then
  warn "$(m_safe install_letta_docker_no_perm "docker found but daemon not accessible — falling back to ${ARI_DETECTED_LETTA_PATH}. Add your user to the 'docker' group to use the docker path.")"
fi

info "$(m_safe install_letta_detected "Detected path:") ${ARI_DETECTED_LETTA_PATH}"

# Non-interactive: proceed with the detected path silently.
PROMPT="y"
if [[ "${ARI_NONINTERACTIVE:-0}" != "1" ]] && [[ -t 0 ]]; then
  printf "  🐜 %s [Y/n]: " \
    "$(m_safe install_letta_prompt "Install and start now?")"
  read -r PROMPT || PROMPT="y"
fi
PROMPT="${PROMPT:-y}"
if [[ "${PROMPT,,}" == "n" ]]; then
  warn "$(m_safe install_letta_skipped "Letta install deferred — run 'ari memory start-local' later.")"
  _env_append_if_absent "# ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA=${ARI_DETECTED_LETTA_PATH}"
  return 0 2>/dev/null || exit 0
fi

SCRIPT="${ARI_ROOT}/scripts/letta"
case "${ARI_DETECTED_LETTA_PATH}" in
  docker)
    docker compose -f "${SCRIPT}/docker-compose.yml" up -d
    ;;
  singularity)
    bash "${SCRIPT}/start_singularity.sh"
    ;;
  pip)
    bash "${SCRIPT}/start_pip.sh"
    ;;
  *)
    warn "$(m_safe install_letta_none "No viable Letta deployment. Set LETTA_BASE_URL manually.")"
    return 0 2>/dev/null || exit 0
    ;;
esac

# Poll for health.
for _i in $(seq 1 30); do
  if curl -fsS "${URL}/v1/health/" >/dev/null 2>&1 \
      || curl -fsS "${URL}/v1/health"  >/dev/null 2>&1; then
    ok "$(m_safe install_letta_up "Letta reachable at ${URL}")"
    _env_append_if_absent "ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA=${ARI_DETECTED_LETTA_PATH}"
    _env_append_if_absent "LETTA_BASE_URL=${URL}"
    return 0 2>/dev/null || exit 0
  fi
  sleep 2
done

warn "$(m_safe install_letta_timeout "Letta not reachable after 60 s — retry with 'ari memory start-local'.")"
_env_append_if_absent "# ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA=${ARI_DETECTED_LETTA_PATH}"
