#!/usr/bin/env bash
# ============================================================================
# install_paperbench.sh — initialize the PaperBench submodule and pip-install
# its packages editable. REQUIRED — ari-skill-paper-re imports the upstream
# directly via _paperbench_bridge.py with no local fallback.
#
# Submodule mount point: ari-skill-paper-re/vendor/paperbench  (per rubric.md §8)
# Upstream URL:          https://github.com/openai/preparedness  (monorepo)
# Actual paperbench pkg: <mount>/project/paperbench
# Sibling deps installed: project/common/{alcatraz, nanoeval, nanoeval_alcatraz,
#                                          preparedness_turn_completer}
#
# Note: openai/preparedness is a monorepo; paperbench lives under project/
# inside it. Editable pip install of project/paperbench/ + the common siblings
# makes ``import paperbench`` resolve from sys.path without any path tricks.
#
# Failure semantics: any error → exit non-zero so setup.sh stops.
# ============================================================================

echo ""
echo -e "${BOLD}  🐜 PaperBench upstream (SimpleJudge) — required for ORS${RESET}"
echo ""

if ! command -v git >/dev/null 2>&1; then
  fail "git not on PATH — required to fetch PaperBench submodule"
  exit 1
fi

PB_ROOT="$ARI_ROOT/ari-skill-paper-re/vendor/paperbench"
PB_PROJECT="$PB_ROOT/project/paperbench"
COMMON_DIR="$PB_ROOT/project/common"

# 1) Make sure the submodule is fetched (and not incomplete).
# An incomplete checkout (dir exists but pyproject.toml missing) happens when
# git-lfs is absent and the smudge filter kills the checkout. Detect and retry.
_pb_needs_checkout=0
if [ ! -d "$PB_PROJECT" ]; then
  _pb_needs_checkout=1
elif [ ! -f "$PB_PROJECT/pyproject.toml" ]; then
  warn "PaperBench checkout appears incomplete (pyproject.toml missing) — re-initialising"
  ( cd "$ARI_ROOT" && git submodule deinit -f -- ari-skill-paper-re/vendor/paperbench 2>/dev/null || true )
  _pb_needs_checkout=1
fi

if [ "$_pb_needs_checkout" -eq 1 ]; then
  if [ -f "$ARI_ROOT/.gitmodules" ] && grep -q "vendor/paperbench" "$ARI_ROOT/.gitmodules" 2>/dev/null; then
    # Without git-lfs, the upstream repo's filter.lfs.process still invokes
    # `git-lfs filter-process` and checkout aborts. Override LFS filters for
    # this command only (source + pointer files suffice for ORS).
    _pb_git=(git)
    if ! command -v git-lfs >/dev/null 2>&1; then
      warn "git-lfs not found — skipping LFS file download (source-only checkout)"
      _pb_git+=(
        -c filter.lfs.smudge=
        -c filter.lfs.clean=
        -c filter.lfs.process=
        -c filter.lfs.required=false
      )
      export GIT_LFS_SKIP_SMUDGE=1
    fi
    if ! ( cd "$ARI_ROOT" && "${_pb_git[@]}" submodule update --init --depth 1 -- ari-skill-paper-re/vendor/paperbench ); then
      fail "git submodule init failed for ari-skill-paper-re/vendor/paperbench"
      exit 1
    fi
    ok "PaperBench submodule initialized"
  else
    fail ".gitmodules missing vendor/paperbench entry. Run: git submodule add https://github.com/openai/preparedness.git ari-skill-paper-re/vendor/paperbench"
    exit 1
  fi
fi

if [ ! -d "$PB_PROJECT" ]; then
  fail "PaperBench submodule still missing at $PB_PROJECT — aborting setup"
  exit 1
fi

# 2) Resolve installer.
if command -v uv &>/dev/null; then
  INSTALLER="uv pip"
else
  INSTALLER="${PIP:-pip}"
fi

# 3) Install in dependency order: common siblings first, then paperbench.
#    Required siblings (per project/paperbench/pyproject.toml dependencies):
#      - chz (PyPI), nanoeval, nanoeval_alcatraz, alcatraz, preparedness_turn_completer
PB_PKGS=()
for sib in alcatraz nanoeval nanoeval_alcatraz preparedness_turn_completer; do
  [ -f "$COMMON_DIR/$sib/pyproject.toml" ] && PB_PKGS+=("$COMMON_DIR/$sib")
done
[ -f "$PB_PROJECT/pyproject.toml" ] && PB_PKGS+=("$PB_PROJECT")

if [ "${#PB_PKGS[@]}" -eq 0 ]; then
  fail "No PaperBench pyproject.toml found under $PB_ROOT — submodule incomplete?"
  exit 1
fi

for pkg_dir in "${PB_PKGS[@]}"; do
  pkg_name="$(basename "$pkg_dir")"
  if run_with_ants "PaperBench: $pkg_name" $INSTALLER install -e "$pkg_dir" --quiet; then
    ok "$pkg_name installed"
  else
    fail "$pkg_name install failed — aborting"
    exit 1
  fi
done

ok "PaperBench install complete"
