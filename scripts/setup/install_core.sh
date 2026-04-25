#!/usr/bin/env bash
# ============================================================================
# install_core.sh — Step 1: Install ari-core and skill plugins
# ============================================================================

echo ""
echo -e "${BOLD}  🐜 [1/6] $(m step1)${RESET}"
echo ""

colony_say

# ari-core imports ari_skill_memory at runtime (viz, pipeline, memory
# client). Install the memory skill first so ari-core's editable install
# can resolve the import path without pip hitting PyPI.
if [ -f "$ARI_ROOT/ari-skill-memory/pyproject.toml" ]; then
  $PIP install -e "$ARI_ROOT/ari-skill-memory/" >/dev/null 2>&1 || {
    warn "ari-skill-memory install failed — ari-core import of ari_skill_memory will break"
  }
fi

if [ -f "$ARI_ROOT/ari-core/pyproject.toml" ] || [ -f "$ARI_ROOT/ari-core/setup.py" ]; then
  run_with_ants "ari-core" $PIP install -e "$ARI_ROOT/ari-core/" || {
    fail "$(m core_fail): $ARI_ROOT/ari-core/"
    exit 1
  }
else
  fail "$(m core_fail): $ARI_ROOT/ari-core/"
  exit 1
fi

SKILL_COUNT=0
SKILL_FAIL=0
SKILL_NAMES=""

# Count skills first for progress bar
SKILL_TOTAL=0
for skill_dir in "$ARI_ROOT"/ari-skill-*/; do
  [ -d "$skill_dir" ] || continue
  if [ -f "$skill_dir/pyproject.toml" ] || [ -f "$skill_dir/setup.py" ]; then
    SKILL_TOTAL=$((SKILL_TOTAL + 1))
  fi
done

SKILL_IDX=0
for skill_dir in "$ARI_ROOT"/ari-skill-*/; do
  [ -d "$skill_dir" ] || continue
  if [ -f "$skill_dir/pyproject.toml" ] || [ -f "$skill_dir/setup.py" ]; then
    skill_name=$(basename "$skill_dir" | sed 's/ari-skill-//')
    SKILL_IDX=$((SKILL_IDX + 1))
    ant_progress $SKILL_IDX $SKILL_TOTAL "$skill_name"
    if $PIP install -e "$skill_dir" &>/dev/null; then
      SKILL_COUNT=$((SKILL_COUNT + 1))
      SKILL_NAMES="${SKILL_NAMES} ${skill_name}"
    else
      SKILL_FAIL=$((SKILL_FAIL + 1))
    fi
  fi
done
# Clear progress bar line
[ -t 1 ] && printf "\r%*s\r" 80 ""

ok "$SKILL_COUNT $(m skills_ok)"
if [ -n "$SKILL_NAMES" ]; then
  echo -e "     ${CYAN}→${RESET}${SKILL_NAMES}"
fi
if [ $SKILL_FAIL -gt 0 ]; then
  warn "$SKILL_FAIL skill(s) skipped (non-fatal)"
fi

# Ensure the reviewer rubric directory is present (v0.6.0+ rubric-driven review).
RUBRIC_DIR="$ARI_ROOT/ari-core/config/reviewer_rubrics"
if [ -d "$RUBRIC_DIR" ]; then
  RUBRIC_N=$(find "$RUBRIC_DIR" -maxdepth 1 -name "*.yaml" -o -name "*.yml" 2>/dev/null | wc -l)
  if [ "$RUBRIC_N" -gt 0 ]; then
    ok "Reviewer rubrics: $RUBRIC_N available in $RUBRIC_DIR"
  else
    warn "reviewer_rubrics dir exists but contains no YAMLs"
  fi
else
  warn "reviewer_rubrics dir missing at $RUBRIC_DIR"
fi

# Record the Python path used for installation so that ari-core can launch
# skill servers with the correct interpreter regardless of the active venv.
ARI_PYTHON_PATH="$(command -v "$PYTHON")"
ARI_PYTHON_PATH="$(cd "$(dirname "$ARI_PYTHON_PATH")" && pwd)/$(basename "$ARI_PYTHON_PATH")"
ARI_ROOT_REAL="$(cd "$ARI_ROOT" && pwd -P)"

# If the detected Python lives inside a skill-specific venv (ari-skill-*/.venv/),
# resolve to the base interpreter that created that venv instead.
case "$ARI_PYTHON_PATH" in
  "$ARI_ROOT"/ari-skill-*/.venv/*|"$ARI_ROOT_REAL"/ari-skill-*/.venv/*)
    BASE_PYTHON="$($PYTHON -c 'import sys, os; print(os.path.join(sys.base_prefix, "bin", "python3"))')"
    if [ -x "$BASE_PYTHON" ]; then
      warn "Detected skill venv Python — resolving to base: $BASE_PYTHON"
      ARI_PYTHON_PATH="$BASE_PYTHON"
    fi
    ;;
esac

echo "$ARI_PYTHON_PATH" > "$ARI_ROOT/.ari_python"
ok "Python path saved: $ARI_PYTHON_PATH → .ari_python"
