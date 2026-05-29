#!/usr/bin/env python3
"""Check that intra-docs links and HTML hrefs resolve to real files.

Gate: docs/最終統合計画書.md §4 items 1-2
  1. every relative / ``docs/``-prefixed link in a ``.md`` resolves on disk;
  2. every local ``.md``/media ``href``/``src`` in index.html & docs.html exists.

External links (http/https/mailto), pure anchors (``#frag``) and in-page
fragments are ignored -- only the on-disk target is validated.  Exit 1 if any
link is broken, 0 otherwise.  ``--json`` for machine-readable output.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"

MD_LINK = re.compile(r"\]\(\s*(<[^>]+>|[^)\s]+)")
HTML_REF = re.compile(r'(?:href|src)\s*=\s*"([^"]+)"')

EXTERNAL = ("http://", "https://", "mailto:", "tel:", "//", "data:")


def _clean_target(raw: str) -> str | None:
    """Strip <>, titles, and #fragment; return on-disk target or None to skip."""
    t = raw.strip()
    if t.startswith("<") and t.endswith(">"):
        t = t[1:-1].strip()
    if t.startswith(EXTERNAL) or "://" in t:
        return None
    if t.startswith("#") or t == "":
        return None
    # drop a markdown link title: (path "title")
    if " " in t:
        t = t.split(" ", 1)[0]
    # drop fragment
    t = t.split("#", 1)[0]
    if t == "":
        return None
    return t


def _resolve(target: str, from_file: Path) -> Path:
    if target.startswith("/"):
        return REPO_ROOT / target.lstrip("/")
    if target.startswith("docs/"):
        return REPO_ROOT / target
    return (from_file.parent / target).resolve()


def check_markdown(findings: list) -> None:
    for md in sorted(DOCS.rglob("*.md")):
        text = md.read_text(encoding="utf-8")
        for m in MD_LINK.finditer(text):
            target = _clean_target(m.group(1))
            if target is None:
                continue
            resolved = _resolve(target, md)
            if not resolved.exists():
                findings.append({
                    "file": md.relative_to(REPO_ROOT).as_posix(),
                    "target": target,
                })


def check_html(findings: list) -> None:
    for name in ("index.html", "docs.html"):
        html = DOCS / name
        if not html.exists():
            continue
        text = html.read_text(encoding="utf-8")
        for m in HTML_REF.finditer(text):
            target = _clean_target(m.group(1))
            if target is None:
                continue
            resolved = _resolve(target, html)
            if not resolved.exists():
                findings.append({
                    "file": f"docs/{name}",
                    "target": target,
                })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--md-only", action="store_true", help="skip HTML href checks")
    args = parser.parse_args(argv)

    findings: list[dict] = []
    check_markdown(findings)
    if not args.md_only:
        check_html(findings)

    if args.json:
        print(json.dumps({"broken": findings}, ensure_ascii=False, indent=2))
    else:
        for f in findings:
            print(f"{f['file']}: broken link -> {f['target']}")
        print(f"\n{len(findings)} broken link(s)")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
