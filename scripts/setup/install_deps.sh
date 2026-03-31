#!/usr/bin/env bash
# ============================================================================
# install_deps.sh — Step 2: Python dependencies (from requirements.txt)
# ============================================================================

echo ""
echo -e "${BOLD}  🐜 [2/6] $(m step2)${RESET}"
echo ""

colony_say

REQ_FILE="$ARI_ROOT/requirements.txt"

if [ ! -f "$REQ_FILE" ]; then
  fail "requirements.txt not found: $REQ_FILE"
  exit 1
fi

# Prefer uv if available (much faster)
if command -v uv &>/dev/null; then
  INSTALLER="uv pip"
  ok "uv detected — turbo mode 🐜💨"
else
  INSTALLER="$PIP"
fi

if run_with_ants "$(m step2)" $INSTALLER install -r "$REQ_FILE"; then
  : # success — message already printed by run_with_ants
else
  warn "Bulk install failed — trying one by one..."
  # Read non-comment, non-empty lines from requirements.txt
  mapfile -t DEPS < <(grep -v '^\s*#' "$REQ_FILE" | grep -v '^\s*$')
  local_idx=0
  local_total=${#DEPS[@]}
  for dep in "${DEPS[@]}"; do
    local_idx=$((local_idx + 1))
    # Strip version specifier for display
    dep_name=$(echo "$dep" | sed 's/[>=<].*//')
    ant_progress $local_idx $local_total "$dep_name"
    if $INSTALLER install "$dep" &>/dev/null; then
      printf "\r%*s\r" 80 ""
      ok "$dep_name"
    else
      printf "\r%*s\r" 80 ""
      fail "$dep_name"
    fi
  done
fi
