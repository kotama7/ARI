#!/usr/bin/env bash
# ============================================================================
# 🐜 ARI Setup Script
# Installs ari-core, all skills, and dependencies.
# Works on Linux, macOS, and WSL2 — with or without conda/sudo.
#
# Module layout (scripts/setup/):
#   colors.sh          — Terminal colors & logging helpers
#   spinner.sh         — Ant-march animation for long-running commands
#   messages.sh        — i18n message catalog (en/ja/zh)
#   lang_select.sh     — Interactive language selector
#   detect_env.sh      — OS, shell, Python, pip, git detection
#   install_core.sh    — [1/6] ari-core + skill plugins
#   install_deps.sh    — [2/6] Python dependencies
#   install_pdf.sh     — [3/6] PDF tools (optional)
#   install_latex.sh   — [4/6] LaTeX (optional)
#   install_frontend.sh— [5/6] React dashboard build
#   verify.sh          — [6/6] Final verification
#   banner.sh          — Completion banner & next steps
# ============================================================================
set -euo pipefail

# --- Parse simple flags -----------------------------------------------------
# v0.7.0: --with-registry installs the ari-registry FastAPI server deps
#         (fastapi / uvicorn / python-multipart). The publish flow itself
#         does not require these — they are only needed if you intend to
#         run `ari registry serve` on this host.
WITH_REGISTRY="${ARI_WITH_REGISTRY:-0}"
for arg in "$@"; do
  case "$arg" in
    --with-registry) WITH_REGISTRY=1 ;;
    --without-registry) WITH_REGISTRY=0 ;;
  esac
done
export WITH_REGISTRY

# --- Detect project root ----------------------------------------------------
ARI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
SETUP_DIR="$ARI_ROOT/scripts/setup"

# --- Source a module with existence check -----------------------------------
load() {
  local mod="$SETUP_DIR/$1"
  if [ ! -f "$mod" ]; then
    echo "  ✘  Missing module: $mod" >&2
    exit 1
  fi
  # shellcheck disable=SC1090
  source "$mod"
}

# ============================================================================
#  Bootstrap: colors, spinner, messages, language
# ============================================================================
load colors.sh
load spinner.sh
load messages.sh

echo ""
echo -e "${BOLD}  🐜🐜🐜 ARI Setup 🐜🐜🐜${RESET}"
echo ""
echo "  Artificial Research Intelligence — let the ants do the research!"
echo "  Root: $ARI_ROOT"
echo ""

load lang_select.sh

# ============================================================================
#  Main pipeline
# ============================================================================
load detect_env.sh      # OS, shell, Python, pip, git
load install_core.sh    # [1/6] ari-core + skills
load install_deps.sh    # [2/6] Python dependencies
load setup_env.sh       # Configure .env (API keys + defaults)
load install_letta.sh   # memory backend (uses _env_append_if_absent from setup_env)
load install_paperbench.sh # PaperBench upstream (SimpleJudge) — required for ORS
load install_pdf.sh     # [3/6] PDF tools
load install_latex.sh   # [4/6] LaTeX
load install_frontend.sh # [5/6] React dashboard build
load verify.sh          # [6/6] Final checks
load banner.sh          # Done!
