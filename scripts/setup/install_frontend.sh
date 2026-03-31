#!/usr/bin/env bash
# ============================================================================
# install_frontend.sh — Step 5: Build React/TypeScript dashboard frontend
# ============================================================================

echo ""
echo -e "${BOLD}  🐜 [5/6] $(m step5)${RESET}"
echo ""

FRONTEND_DIR="$ARI_ROOT/ari-core/ari/viz/frontend"

if [ ! -d "$FRONTEND_DIR" ]; then
  warn "Frontend directory not found: $FRONTEND_DIR"
  return 0
fi

# Check for Node.js
if command -v node &>/dev/null; then
  NODE_VERSION="$(node --version 2>/dev/null)"
  ok "Node.js: $NODE_VERSION"
else
  warn "$(m frontend_skip)"
  return 0
fi

# Check for npm
if ! command -v npm &>/dev/null; then
  warn "npm not found — skipping frontend build"
  return 0
fi

# Install dependencies and build
cd "$FRONTEND_DIR"

if run_with_ants "npm install" npm install --no-audit --no-fund 2>&1; then
  : # success
else
  warn "npm install failed — skipping frontend build"
  cd "$ARI_ROOT"
  return 0
fi

if run_with_ants "vite build" npx vite build 2>&1; then
  ok "$(m frontend_ok)"
else
  warn "Frontend build failed — dashboard will use fallback HTML"
fi

cd "$ARI_ROOT"
