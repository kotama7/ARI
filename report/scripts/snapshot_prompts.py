#!/usr/bin/env python3
"""Snapshot runtime LLM prompts into the report Appendix.

Copies every `ari-core/ari/prompts/**/*.md` into
`report/shared/appendix/prompts/<area>/<name>.md` and prefixes each output with
a header recording the source path, its SHA-256, and the current git commit.

The Appendix verbatim-includes these snapshot files; the report is pinned to
ari-core v0.7.x so the bytes shown in the PDF must match the bytes the system
actually fed to the LLM at that commit.

Usage: python snapshot_prompts.py --root <repo-root>
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

PROMPT_ROOT_REL = Path("ari-core/ari/prompts")
APPENDIX_REL = Path("report/shared/appendix/prompts")
HEADER_FMT = (
    "% snapshot-from: {rel}@{sha} @ commit {commit}\n"
    "% DO NOT EDIT — regenerate via `make snapshot-prompts`.\n"
    "%\n"
)


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _git_commit(root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"],
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "UNKNOWN"


def snapshot(root: Path) -> int:
    src_root = root / PROMPT_ROOT_REL
    dst_root = root / APPENDIX_REL
    if not src_root.exists():
        print(f"[snapshot_prompts] source root not found: {src_root}", file=sys.stderr)
        return 1

    commit = _git_commit(root)
    dst_root.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    seen_dst: set[Path] = set()
    for src in sorted(src_root.rglob("*.md")):
        if src.name == "README.md":
            continue  # per-directory READMEs are documentation, not prompts
        rel = src.relative_to(root)
        body = src.read_bytes()
        sha = _sha256(body)
        header = HEADER_FMT.format(rel=rel.as_posix(), sha=sha, commit=commit).encode()
        dst = dst_root / src.relative_to(src_root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(header + body)
        written.append(dst)
        seen_dst.add(dst)

    for stale in sorted(dst_root.rglob("*.md")):
        if stale.name == "README.md":
            continue  # preserve the appendix's own README (not a prompt snapshot)
        if stale not in seen_dst:
            stale.unlink()
            print(f"[snapshot_prompts] removed stale {stale.relative_to(root)}")

    print(f"[snapshot_prompts] wrote {len(written)} file(s) at commit {commit}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path,
                    help="ARI repo root (the directory containing ari-core/ and report/).")
    args = ap.parse_args()
    return snapshot(args.root.resolve())


if __name__ == "__main__":
    sys.exit(main())
