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
  echo "    export PATH=\"\$ARI_ROOT/.venv/bin:\$PATH\""
  echo "    # pip install --user の場合のみ: export PATH=\"\$HOME/.local/bin:\$PATH\""
else
  fail "$(m cli_fail)"
  ERRORS=$((ERRORS + 1))
fi

# v0.7.0: ear subcommand (curate / publish / promote / status).
# Loaded lazily inside cli.py — confirm it registered without errors.
if $PYTHON -m ari.cli ear --help &>/dev/null 2>&1; then
  ok "ari ear (EAR curation/publish) ✔"
else
  warn "ari ear subcommand not available (curate/publish/promote disabled)"
fi

# v0.7.0: clone subcommand (digest-verified bundle fetch).
if $PYTHON -m ari.cli clone --help &>/dev/null 2>&1; then
  ok "ari clone (curated bundle fetch) ✔"
else
  warn "ari clone subcommand not available"
fi

# v0.7.0: registry subcommand (server admin + token mint).
if $PYTHON -m ari.cli registry --help &>/dev/null 2>&1; then
  ok "ari registry (server admin) ✔"
else
  warn "ari registry subcommand not available"
fi

# v0.7.0: optional ari-registry server deps (FastAPI + uvicorn + python-multipart).
if $PYTHON -c "import fastapi, uvicorn, multipart" 2>/dev/null; then
  ok "ari-registry server deps (fastapi, uvicorn, python-multipart) ✔"
else
  warn "ari-registry server deps missing — pip install fastapi uvicorn[standard] python-multipart  (only required if you run 'ari registry serve')"
fi

# confirm Letta is reachable. Warning only:
# a user might defer Letta install and set it up manually later.
URL="${LETTA_BASE_URL:-http://localhost:8283}"
if curl -fsS "${URL}/v1/health/" >/dev/null 2>&1 \
    || curl -fsS "${URL}/v1/health"  >/dev/null 2>&1; then
  ok "Letta reachable at ${URL} ✔"
else
  warn "Letta not reachable at ${URL} — run 'ari memory start-local' before 'ari run'."
fi
