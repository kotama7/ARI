#!/usr/bin/env bash
# ============================================================================
# colors.sh — Terminal colors and logging helpers
# ============================================================================

if [ -t 1 ]; then
  GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
  CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
else
  GREEN=''; YELLOW=''; RED=''; CYAN=''; BOLD=''; RESET=''
fi

info()  { echo -e "  ${CYAN}🐜${RESET} $*"; }
ok()    { echo -e "  ${GREEN}✔${RESET}  $*"; }
warn()  { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
fail()  { echo -e "  ${RED}✘${RESET}  $*"; }
