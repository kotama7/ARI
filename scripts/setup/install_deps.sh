#!/usr/bin/env bash
# ============================================================================
# install_deps.sh — Step 2: Python dependencies (uv + lockfile-based)
#
# Why uv + lockfile (v0.7.4+):
#   `pip install -r requirements.txt` with a loose pin set like
#   `pydantic>=2.0` doesn't roundtrip stably: a second install can leave
#   pydantic on an older version while pip pulls a newer pydantic-core
#   transitively, producing the cryptic
#     SystemError: The installed pydantic-core version (X) is
#     incompatible with the current pydantic version, which requires (Y)
#   that crashed `ari registry serve` in production. uv with a frozen
#   requirements.lock installs the exact set every time, eliminating
#   the drift class.
# ============================================================================

echo ""
echo -e "${BOLD}  🐜 [2/6] $(m step2)${RESET}"
echo ""

colony_say

REQ_FILE="$ARI_ROOT/requirements.txt"
LOCK_FILE="$ARI_ROOT/requirements.lock"

if [ ! -f "$REQ_FILE" ]; then
  fail "requirements.txt not found: $REQ_FILE"
  exit 1
fi

# ----------------------------------------------------------------------------
# Bootstrap uv if missing. The Astral installer drops a static binary into
# ~/.local/bin so no compiler / system pip is needed. Fall back to
# `pip install --user uv` for environments without curl/wget (rare).
# ----------------------------------------------------------------------------
if ! command -v uv &>/dev/null; then
  info "uv not found — bootstrapping via Astral installer"
  if command -v curl &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh \
      || { fail "uv installer failed (curl)"; exit 1; }
  elif command -v wget &>/dev/null; then
    wget -qO- https://astral.sh/uv/install.sh | sh \
      || { fail "uv installer failed (wget)"; exit 1; }
  else
    warn "neither curl nor wget — falling back to 'pip install --user uv'"
    $PIP install --user uv \
      || { fail "could not install uv via pip"; exit 1; }
  fi
  # Astral installer drops the binary in ~/.local/bin (and updates shell
  # rc files for future sessions). Make it visible in the current shell.
  export PATH="$HOME/.local/bin:$PATH"
  hash -r 2>/dev/null || true
  command -v uv &>/dev/null \
    || { fail "uv still not on PATH after install"; exit 1; }
fi
ok "uv: $(uv --version 2>&1 | head -1)"

# ----------------------------------------------------------------------------
# Target the project venv detect_env.sh prepared. We pass --python
# explicitly so we don't accidentally install into a different env that
# happens to be active in the parent shell.
# ----------------------------------------------------------------------------
VENV_PY="${VENV_DIR:-$ARI_ROOT/.venv}/bin/python"
if [ ! -x "$VENV_PY" ]; then
  fail "venv python not found: $VENV_PY — detect_env.sh should have created it"
  exit 1
fi

# ----------------------------------------------------------------------------
# Regenerate the lockfile if requirements.txt is newer than the lock, or
# if no lockfile exists at all. ARI_FORCE_RELOCK=1 forces regeneration.
# We compile against the venv's interpreter so Requires-Python markers
# resolve correctly (mcp>=1.1 needs Python>=3.10, etc.).
# ----------------------------------------------------------------------------
if [ "${ARI_FORCE_RELOCK:-0}" = "1" ] \
   || [ ! -f "$LOCK_FILE" ] \
   || [ "$REQ_FILE" -nt "$LOCK_FILE" ]; then
  info "Generating $LOCK_FILE from requirements.txt"
  if ! uv pip compile "$REQ_FILE" --python "$VENV_PY" \
        --output-file "$LOCK_FILE" >/dev/null 2>&1; then
    fail "uv pip compile failed — run manually for details:"
    echo "    uv pip compile $REQ_FILE --python $VENV_PY -o $LOCK_FILE"
    exit 1
  fi
  ok "Lockfile written: $LOCK_FILE ($(wc -l <"$LOCK_FILE") pinned)"
else
  ok "Lockfile up to date: $LOCK_FILE"
fi

# ----------------------------------------------------------------------------
# Install from the lockfile. `uv pip install -r lock` upgrades/downgrades
# every package to the pinned version but does NOT remove unrelated
# packages already in the venv (unlike `uv pip sync`). That's the right
# semantics here because ari-core / ari-skill-* are installed in editable
# mode by install_core.sh and aren't in requirements.lock.
# ----------------------------------------------------------------------------
if run_with_ants "$(m step2)" \
     uv pip install --python "$VENV_PY" -r "$LOCK_FILE"; then
  : # success — run_with_ants already reported
else
  fail "Bulk install from lockfile failed. Re-run with:"
  echo "    uv pip install --python $VENV_PY -r $LOCK_FILE"
  exit 1
fi

# ----------------------------------------------------------------------------
# v0.7.0: optional ari-registry server deps were once gated behind
# --with-registry. Now that requirements.txt always lists them and the
# lockfile pins them, this flag is informational only. Keep the check so
# CI invocations passing --with-registry don't error out.
# ----------------------------------------------------------------------------
if [ "${WITH_REGISTRY:-0}" = "1" ]; then
  ok "ari-registry deps already covered by lockfile (fastapi / uvicorn / python-multipart)"
fi
