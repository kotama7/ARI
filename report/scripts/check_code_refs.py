#!/usr/bin/env python3
"""Gate 2 — verify code:* references in shared/code_refs.yaml are valid.

For every entry:
  * the file exists at <repo_root>/<path>
  * `line` is within bounds
  * `anchor` substring appears within ±3 lines of `line` (drift tolerance)

Usage:
    python check_code_refs.py [--root <repo-root>]

Exit code 0 if all entries pass, 1 otherwise.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPORT_ROOT = Path(__file__).resolve().parent.parent     # report/
DEFAULT_REPO = REPORT_ROOT.parent                        # ARI/
CODE_REFS = REPORT_ROOT / "shared" / "code_refs.yaml"

DRIFT = 3   # tolerate ±3 lines of drift before failing


def _load_refs():
    with CODE_REFS.open() as f:
        return yaml.safe_load(f)


def _check_entry(slug: str, entry: dict, repo_root: Path) -> list[str]:
    errors = []
    path = repo_root / entry["path"]
    if not path.exists():
        return [f"{slug}: file not found: {path}"]
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    line_no = int(entry["line"])
    if line_no < 1 or line_no > len(lines):
        return [f"{slug}: line {line_no} out of range (1..{len(lines)}) for {path}"]
    anchor = entry["anchor"]
    window_lo = max(0, line_no - 1 - DRIFT)
    window_hi = min(len(lines), line_no - 1 + DRIFT + 1)
    window = "\n".join(lines[window_lo:window_hi])
    if anchor not in window:
        errors.append(
            f"{slug}: anchor '{anchor}' not found within ±{DRIFT} lines of "
            f"{entry['path']}:{line_no} (saw lines {window_lo+1}..{window_hi})"
        )
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=DEFAULT_REPO,
                    help="Repository root (default: parent of report/)")
    args = ap.parse_args()

    refs = _load_refs()
    entries = refs.get("entries", {})
    errors: list[str] = []
    for slug, entry in entries.items():
        errors.extend(_check_entry(slug, entry, args.root))

    if errors:
        print(f"[check_code_refs] {len(errors)} problem(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"[check_code_refs] OK ({len(entries)} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
