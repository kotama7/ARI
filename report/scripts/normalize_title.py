"""Normalize a paper title for cross-source comparison.

Operations:
  1. lowercase
  2. strip LaTeX (\\textit{...} \\emph{...} {...}) and math ($...$)
  3. drop punctuation except hyphens between words
  4. collapse whitespace

Used by fetch_bib.py and check_bib.py to compare titles via rapidfuzz.
"""
from __future__ import annotations

import re

LATEX_CMD_RE = re.compile(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?")
LATEX_GROUP_RE = re.compile(r"\{([^{}]*)\}")
MATH_RE = re.compile(r"\$[^$]*\$")
PUNC_RE = re.compile(r"[^\w\s\-]")  # keep word chars, whitespace, hyphen
WS_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    t = title or ""
    t = MATH_RE.sub(" ", t)
    t = LATEX_CMD_RE.sub(" ", t)
    # iteratively unwrap braces
    while LATEX_GROUP_RE.search(t):
        t = LATEX_GROUP_RE.sub(r"\1", t)
    t = t.lower()
    t = PUNC_RE.sub(" ", t)
    t = WS_RE.sub(" ", t).strip()
    return t


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        print(normalize_title(arg))
