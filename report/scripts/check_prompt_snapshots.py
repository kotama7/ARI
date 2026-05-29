#!/usr/bin/env python3
"""Gate 10 — Appendix prompt snapshots match upstream `ari-core` prompts.

For every `report/shared/appendix/prompts/**/*.md`, the file body (after the
`% snapshot-from:` header block) must equal the bytes of the source file named
in that header, and the recorded SHA-256 must match.

Exits non-zero on any mismatch, missing source, or missing snapshot.

Usage: python check_prompt_snapshots.py --root <repo-root>
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

APPENDIX_REL = Path("report/shared/appendix/prompts")
PROMPT_ROOT_REL = Path("ari-core/ari/prompts")
HEADER_RE = re.compile(
    rb"^% snapshot-from: (?P<rel>\S+)@(?P<sha>[0-9a-f]{64}) @ commit (?P<commit>\S+)\n"
    rb"% DO NOT EDIT[^\n]*\n"
    rb"%\n"
)


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def check(root: Path) -> int:
    appendix = root / APPENDIX_REL
    src_root = root / PROMPT_ROOT_REL
    if not appendix.exists():
        print(f"[check_prompt_snapshots] no snapshot directory: {appendix}")
        return 1

    errors: list[str] = []
    seen_src: set[Path] = set()
    for snap in sorted(appendix.rglob("*.md")):
        if snap.name == "README.md":
            continue  # per-directory READMEs are documentation, not prompt snapshots
        raw = snap.read_bytes()
        m = HEADER_RE.match(raw)
        if not m:
            errors.append(f"{snap.relative_to(root)}: missing/invalid snapshot header")
            continue
        rel = Path(m.group("rel").decode())
        declared_sha = m.group("sha").decode()
        body = raw[m.end():]
        actual_sha = _sha256(body)
        if actual_sha != declared_sha:
            errors.append(
                f"{snap.relative_to(root)}: declared sha {declared_sha[:8]}.. "
                f"!= body sha {actual_sha[:8]}.."
            )
        src = root / rel
        if not src.exists():
            errors.append(f"{snap.relative_to(root)}: source missing at {rel}")
            continue
        seen_src.add(src.resolve())
        src_bytes = src.read_bytes()
        if src_bytes != body:
            errors.append(f"{snap.relative_to(root)}: out of sync with {rel} — run `make snapshot-prompts`")

    if src_root.exists():
        for src in sorted(src_root.rglob("*.md")):
            if src.name == "README.md":
                continue  # per-directory READMEs are documentation, not prompts
            if src.resolve() not in seen_src:
                errors.append(f"unsnapshoted prompt: {src.relative_to(root)} — run `make snapshot-prompts`")

    if errors:
        print(f"[check_prompt_snapshots] {len(errors)} issue(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("[check_prompt_snapshots] OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path,
                    help="ARI repo root (the directory containing ari-core/ and report/).")
    args = ap.parse_args()
    return check(args.root.resolve())


if __name__ == "__main__":
    sys.exit(main())
