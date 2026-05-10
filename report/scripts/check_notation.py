#!/usr/bin/env python3
"""Gate 3 — every math symbol used in the body must be defined in
shared/notation.tex.

Strategy:
  * collect every \\newcommand{\\NAME}{...} from shared/notation.tex → defined
  * scan en/chapters/*.tex for usages of these macros
  * additionally scan for any \\<word> usage inside math mode that doesn't
    appear in the LaTeX kernel / amsmath whitelist; flag if undefined.

Heuristic: undefined-macro detection in math mode is hard without a real
TeX parse, so we instead enforce a *registration* rule:
  * any macro mentioned in the body that is part of `notation.tex`'s
    namespace (alphabet keywords like Nodes, Tree, children, …)
    must come from notation.tex (no shadow definitions)

Usage: python check_notation.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPORT_ROOT = Path(__file__).resolve().parent.parent
NOTATION = REPORT_ROOT / "shared" / "notation.tex"
EN_CHAPTERS = REPORT_ROOT / "en" / "chapters"

DEF_RE = re.compile(r"\\newcommand\{\\([A-Za-z]+)\}")


def main() -> int:
    if not NOTATION.exists():
        print("[check_notation] missing shared/notation.tex")
        return 1
    defined = set(DEF_RE.findall(NOTATION.read_text(encoding="utf-8")))
    if not defined:
        print("[check_notation] no \\newcommand entries found")
        return 1

    if not EN_CHAPTERS.exists():
        print(f"[check_notation] no en/chapters; defined={len(defined)} macros")
        return 0

    used: set[str] = set()
    use_re = re.compile(r"\\([A-Za-z]+)\b")
    for f in EN_CHAPTERS.glob("*.tex"):
        text = f.read_text(encoding="utf-8")
        # crude math-mode extraction; covers $...$, equation/align envs, \[...\]
        math_chunks: list[str] = []
        math_chunks += re.findall(r"\$[^$\n]+\$", text)
        math_chunks += re.findall(
            r"\\begin\{(?:equation|align|gather|multline)\*?\}.*?\\end\{(?:equation|align|gather|multline)\*?\}",
            text, re.DOTALL)
        math_chunks += re.findall(r"\\\[.*?\\\]", text, re.DOTALL)
        for chunk in math_chunks:
            for name in use_re.findall(chunk):
                if name in defined:
                    used.add(name)

    # Cross-check: every macro referenced in math mode that *looks* like a
    # custom symbol (capitalised, or matches a notation prefix) but isn't
    # defined in notation.tex is flagged.
    suspicious: set[str] = set()
    notation_prefixes = ("Node", "Tree", "Reals", "Nat", "axes", "utility",
                          "policy", "rubric", "paper", "judge", "depth",
                          "novelty", "softmax", "branch", "score", "Refine",
                          "ckpt", "lineage", "indicator", "Prob")
    for f in EN_CHAPTERS.glob("*.tex"):
        text = f.read_text(encoding="utf-8")
        for chunk in re.findall(r"\$[^$\n]+\$|\\\[.*?\\\]", text, re.DOTALL):
            for name in use_re.findall(chunk):
                if any(name.startswith(p) for p in notation_prefixes) and name not in defined:
                    suspicious.add(name)

    if suspicious:
        print(f"[check_notation] {len(suspicious)} undefined symbol(s):")
        for s in sorted(suspicious):
            print(f"  - \\{s}")
        return 1
    print(f"[check_notation] OK ({len(defined)} defined, {len(used)} used)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
