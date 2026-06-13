#!/usr/bin/env bash
# Copy the committed ARI System Report PDFs into the GitHub Pages tree so the
# homepage can surface them (see docs/README.md, "Homepage static site").
#
# GitHub Pages publishes ONLY docs/, so report/{en,ja,zh}/main.pdf — which live
# outside docs/ — cannot be linked directly. This mirrors them to TWO deploy
# locations: docs/assets/report/<lang>.pdf (bespoke landing) and
# docs/public/report/<lang>.pdf (served by VitePress at /ARI/docs/report/).
# The report/ source is never modified.
#
# Run from the repo root:  bash scripts/docs/sync_report_pdf.sh [--check]
#   --check  verify the copies are byte-identical to the source (no writes);
#            exit 1 on drift. Use this in CI to detect a stale copy.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST_DIRS=("$REPO_ROOT/docs/assets/report" "$REPO_ROOT/docs/public/report")
LANGS=(en ja zh)
CHECK=0
[[ "${1:-}" == "--check" ]] && CHECK=1

rc=0
for dest in "${DEST_DIRS[@]}"; do
  [[ $CHECK -eq 0 ]] && mkdir -p "$dest"
  rel="${dest#$REPO_ROOT/}"
  for lang in "${LANGS[@]}"; do
    src="$REPO_ROOT/report/$lang/main.pdf"
    dst="$dest/$lang.pdf"
    if [[ ! -f "$src" ]]; then
      echo "sync_report_pdf: source missing: report/$lang/main.pdf" >&2
      rc=1; continue
    fi
    if [[ $CHECK -eq 1 ]]; then
      if [[ ! -f "$dst" ]] || ! cmp -s "$src" "$dst"; then
        echo "sync_report_pdf: DRIFT — $rel/$lang.pdf is stale; re-run sync_report_pdf.sh" >&2
        rc=1
      fi
    else
      cp -f "$src" "$dst"
      echo "synced report/$lang/main.pdf -> $rel/$lang.pdf"
    fi
  done
done
exit $rc
