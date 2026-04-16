#!/usr/bin/env bash
# ============================================================================
# verify.sh — Step 6: Final verification
# ============================================================================

echo ""
echo -e "${BOLD}  🐜 [6/6] $(m step6)${RESET}"
echo ""

ERRORS=0

for mod in mcp litellm fitz websockets; do
  if $PYTHON -c "import $mod" 2>/dev/null; then
    ok "$mod ✔"
  else
    fail "$mod — $(m import_fail)"
    ERRORS=$((ERRORS + 1))
  fi
done

if command -v ari &>/dev/null; then
  ok "ari CLI: $(which ari) ✔"
elif $PYTHON -m ari.cli --help &>/dev/null 2>&1; then
  ok "ari CLI: $PYTHON -m ari.cli ✔"
  warn "$(m cli_not_in_path)"
  echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
else
  fail "$(m cli_fail)"
  ERRORS=$((ERRORS + 1))
fi
