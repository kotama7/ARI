#!/usr/bin/env python3
"""Diff gate (warn): a changed source must bump its referencing docs.

Every live English doc declares, in YAML front-matter, the source files it
documents::

    ---
    sources:
      - path: ari-core/ari/orchestrator
        role: implementation
    last_verified: 2026-05-26
    ---

When one of those sources changes on a branch, the doc that references it is
presumed to need re-verification, so its ``last_verified`` date should be bumped
in the same PR.  This script diffs the branch against a base ref, maps each
changed source path back to the docs that reference it (a changed file matches a
declared source if it equals it, or lives beneath a declared directory), and
reports referencing docs whose ``last_verified`` was NOT advanced.

Default severity is WARNING (exit 0) — the coupling is advisory while the habit
builds; ``--strict`` turns unbumped docs into errors (exit 1).  Only English
master docs are mapped (translations track staleness via
``check_translation_freshness.py``).  ``--json`` for machine output.

Design: complements ``check_doc_sources.py`` (which checks the forward direction
— that declared sources exist) by checking the reverse, change-coupling
direction.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    sys.stderr.write("check_ref_coupling: PyYAML is required (pip install pyyaml).\n")
    raise SystemExit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"


def git(*args: str):
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True, text=True, check=True,
    ).stdout


def split_front_matter(text: str) -> str | None:
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i])
    return None


def parse_doc(text: str) -> tuple[list[str], _dt.date | None]:
    """Return (declared source paths, last_verified date or None)."""
    fm = split_front_matter(text)
    if fm is None:
        return [], None
    try:
        data = yaml.safe_load(fm) or {}
    except yaml.YAMLError:
        return [], None
    if not isinstance(data, dict):
        return [], None
    sources: list[str] = []
    raw = data.get("sources")
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict) and "path" in entry:
                sources.append(str(entry["path"]))
    lv = data.get("last_verified")
    date: _dt.date | None = None
    if isinstance(lv, _dt.date):
        date = lv
    elif lv is not None:
        try:
            date = _dt.date.fromisoformat(str(lv))
        except ValueError:
            date = None
    return sources, date


def is_translation(rel: str) -> bool:
    return rel.startswith("docs/ja/") or rel.startswith("docs/zh/")


def english_docs() -> list[Path]:
    return [
        p for p in sorted(DOCS.rglob("*.md"))
        if not is_translation(p.relative_to(REPO_ROOT).as_posix())
    ]


def matches(changed_path: str, source: str) -> bool:
    """A changed file matches a declared source if equal or beneath its dir."""
    return changed_path == source or changed_path.startswith(source.rstrip("/") + "/")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-ref", default="origin/main",
                    help="base git ref to diff against (default: origin/main)")
    ap.add_argument("--strict", action="store_true",
                    help="treat unbumped referencing docs as errors (exit 1)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    try:
        base = git("merge-base", args.base_ref, "HEAD").strip()
    except subprocess.CalledProcessError:
        # Advisory mode tolerates an unresolvable base (exit 0, the workflow
        # runs this step continue-on-error). --strict fails CLOSED so a future
        # promotion to a hard gate cannot silently no-op.
        print(f"[check_ref_coupling] cannot resolve base ref {args.base_ref!r}",
              file=sys.stderr)
        return 1 if args.strict else 0
    changed = [l for l in git("diff", "--name-only", base, "HEAD").splitlines() if l.strip()]

    findings: list[dict] = []
    for doc in english_docs():
        docrel = doc.relative_to(REPO_ROOT).as_posix()
        sources, cur_lv = parse_doc(doc.read_text(encoding="utf-8"))
        if not sources:
            continue
        triggers = sorted({
            c for c in changed for s in sources
            if matches(c, s) and c != docrel
        })
        if not triggers:
            continue
        # Did this doc's last_verified advance relative to the base?
        try:
            old_text = git("show", f"{base}:{docrel}")
        except subprocess.CalledProcessError:
            continue  # doc is new on this branch -> nothing to bump
        _, old_lv = parse_doc(old_text)
        bumped = cur_lv is not None and (old_lv is None or cur_lv > old_lv)
        if not bumped:
            findings.append({
                "doc": docrel,
                "last_verified": str(cur_lv) if cur_lv else None,
                "sources_changed": triggers,
            })

    level = "error" if args.strict else "warning"
    if args.json:
        print(json.dumps({
            "base": base,
            "level": level,
            "findings": findings,
        }, ensure_ascii=False, indent=2))
    elif findings:
        print(f"[check_ref_coupling] {len(findings)} doc(s) reference a changed "
              f"source without bumping last_verified ({level}):")
        for f in findings:
            print(f"  - {f['doc']} (last_verified={f['last_verified']})")
            for s in f["sources_changed"]:
                print(f"      <- changed source: {s}")
        if not args.strict:
            print("  (advisory — re-run with --strict to enforce)")
    else:
        print("[check_ref_coupling] OK — no referenced source changed without a "
              "last_verified bump")
    return 1 if (findings and args.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
