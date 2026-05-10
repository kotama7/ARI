#!/usr/bin/env python3
"""Inject a language switcher (en | ja | zh) into the generated HTML index.

Usage: python inject_langnav.py html/<lang>/index.html
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


NAV_HTML = """\
<nav class="ari-langnav" style="position:fixed;top:0.6em;right:0.8em;font-size:0.9em;background:#fff;padding:0.2em 0.5em;border:1px solid #ddd;border-radius:4px;">
  <a href="../en/index.html">en</a> |
  <a href="../ja/index.html">ja</a> |
  <a href="../zh/index.html">zh</a>
</nav>
"""


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: inject_langnav.py html/<lang>/index.html", file=sys.stderr)
        return 2
    p = Path(sys.argv[1])
    if not p.exists():
        print(f"[inject_langnav] missing: {p}", file=sys.stderr)
        return 1
    html = p.read_text(encoding="utf-8")
    if 'class="ari-langnav"' in html:
        print("[inject_langnav] already injected")
        return 0
    html = re.sub(r"(<body[^>]*>)", r"\1\n" + NAV_HTML, html, count=1)
    p.write_text(html, encoding="utf-8")
    print(f"[inject_langnav] OK {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
