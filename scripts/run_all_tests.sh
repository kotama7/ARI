#!/usr/bin/env bash
# ============================================================================
# run_all_tests.sh — full multi-package test suite
#
# Runs each skill's tests in its own ``pytest`` process. This avoids the
# cross-skill ``sys.modules['src.server']`` ambiguity that breaks single-shot
# ``pytest`` runs across multiple ari-skill-* packages (each ships its server
# as ``src/server.py``; sharing one Python process means the first import
# poisons every subsequent ``from src.server import …`` and any
# ``unittest.mock.patch('src.server.X')`` in sibling skills).
#
# Usage:   bash scripts/run_all_tests.sh [extra-pytest-args]
# Exit code: 0 if every path passes, 1 if any path fails.
# ============================================================================
set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PATHS=(
  "ari-core/tests"
  "ari-skill-paper/tests"
  "ari-skill-paper-re/tests"
  "ari-skill-web/tests"
  "ari-skill-hpc/tests"
  "ari-skill-idea/tests"
  "ari-skill-evaluator/tests"
  "ari-skill-memory/tests"
  "ari-skill-coding/tests"
  "ari-skill-replicate/tests"
  "ari-skill-vlm/tests"
  "ari-skill-transform/tests"
  "ari-skill-benchmark/tests"
)

failed=()
total_pass=0
total_fail=0
total_skip=0

for p in "${PATHS[@]}"; do
  if [ ! -d "$p" ]; then
    echo "[skip] $p — not present"
    continue
  fi
  printf '\n========== %s ==========\n' "$p"
  # Tee the per-path output so the user sees progress in real time, and
  # capture the bottom line for aggregation.
  log=$(mktemp)
  if pytest "$p" --tb=short -q --no-header -p no:cacheprovider "$@" 2>&1 | tee "$log"; then
    rc=0
  else
    rc=${PIPESTATUS[0]}
  fi
  # Last non-empty line carries the summary, e.g. "30 passed in 0.27s"
  summary=$(grep -Eo '[0-9]+ passed|[0-9]+ failed|[0-9]+ skipped' "$log" | sort -u | paste -sd', ')
  rm -f "$log"
  if [ "$rc" -ne 0 ]; then
    failed+=("$p")
  fi
  pass=$(echo "$summary" | grep -oE '[0-9]+ passed'  | grep -oE '^[0-9]+' || echo 0)
  fail=$(echo "$summary" | grep -oE '[0-9]+ failed'  | grep -oE '^[0-9]+' || echo 0)
  skip=$(echo "$summary" | grep -oE '[0-9]+ skipped' | grep -oE '^[0-9]+' || echo 0)
  total_pass=$((total_pass + pass))
  total_fail=$((total_fail + fail))
  total_skip=$((total_skip + skip))
done

printf '\n========== aggregate ==========\n'
printf 'passed:  %d\nfailed:  %d\nskipped: %d\n' \
  "$total_pass" "$total_fail" "$total_skip"

if [ ${#failed[@]} -ne 0 ]; then
  printf '\nfailing paths:\n'
  for p in "${failed[@]}"; do printf '  - %s\n' "$p"; done
  exit 1
fi
exit 0
