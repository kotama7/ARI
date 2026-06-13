#!/usr/bin/env python3
"""Gate: the three root READMEs share one Markdown heading shape.

``README.md`` / ``README.ja.md`` / ``README.zh.md`` are hand-maintained
translations of one another.  Their prose is localised, but their *section
structure* must stay identical so that a section added (or removed) in one
language is mirrored in the others.  This gate compares the ordered sequence of
ATX heading levels (``#`` depth) across the three files and fails (exit 1) when
they diverge.

Heading *text* is intentionally NOT compared — most headings are translated
(``## Vision`` <-> ``## ビジョン``) while a few stay English (``## Research
Goal``); only the *shape* (how many headings, at what nesting depth, in what
order) is the invariant.

Fenced code blocks are skipped: the READMEs embed example experiment files that
contain ``#`` lines (e.g. ``## Research Goal``) and even a nested ```` ```bash ````
block inside a ```` ```markdown ```` example.  Detection follows CommonMark fence
rules — a fence closes only on a *bare* fence line (no info string) of the same
character and at least the opening length — so an info-string line like
```` ```bash ```` is treated as content, not as a close, and never unbalances
the scan.

Pure stdlib, no dependencies, no network/LLM.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LANGS = ("en", "ja", "zh")
FILES = {
    "en": REPO_ROOT / "README.md",
    "ja": REPO_ROOT / "README.ja.md",
    "zh": REPO_ROOT / "README.zh.md",
}

FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def headings(path: Path) -> list[tuple[int, int, str]]:
    """Return (lineno, depth, text) for every ATX heading outside code fences."""
    out: list[tuple[int, int, str]] = []
    fence: tuple[str, int] | None = None  # (char, length) of the open fence
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = FENCE_RE.match(line)
        if m:
            marker, info = m.group(1), m.group(2).strip()
            char, length = marker[0], len(marker)
            if fence is None:
                fence = (char, length)  # open
            elif char == fence[0] and length >= fence[1] and info == "":
                fence = None  # bare close
            # else: an info-string or shorter/other-char fence -> content
            continue
        if fence is not None:
            continue
        hm = HEADING_RE.match(line)
        if hm and hm.group(2).strip():
            out.append((i, len(hm.group(1)), hm.group(2).strip()))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    missing = [lang for lang, p in FILES.items() if not p.exists()]
    if missing:
        print(f"[check_readme_parity] missing README(s): {missing}")
        return 1

    hs = {lang: headings(p) for lang, p in FILES.items()}
    depth = {lang: [d for _, d, _ in hs[lang]] for lang in LANGS}

    errors: list[str] = []
    if not (depth["en"] == depth["ja"] == depth["zh"]):
        errors.append(
            "heading shape differs: "
            + ", ".join(f"{lang}={len(depth[lang])}" for lang in LANGS)
        )
        n = max(len(depth[lang]) for lang in LANGS)
        for i in range(n):
            row = {lang: (depth[lang][i] if i < len(depth[lang]) else None) for lang in LANGS}
            if len(set(row.values())) > 1:
                ctx = {
                    lang: (hs[lang][i][2] if i < len(hs[lang]) else "<none>")
                    for lang in LANGS
                }
                errors.append(
                    f"first divergence at heading #{i}: "
                    + "; ".join(
                        f"{lang} depth={row[lang]} {ctx[lang]!r}" for lang in LANGS
                    )
                )
                break

    if args.json:
        print(json.dumps(
            {"counts": {lang: len(hs[lang]) for lang in LANGS}, "errors": errors},
            ensure_ascii=False, indent=2,
        ))
    elif errors:
        print(f"[check_readme_parity] {len(errors)} issue(s):")
        for e in errors:
            print(f"  - {e}")
    else:
        print(
            f"[check_readme_parity] OK — {len(depth['en'])} headings, "
            f"identical shape across {', '.join(LANGS)}"
        )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
