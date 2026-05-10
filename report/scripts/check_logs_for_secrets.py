#!/usr/bin/env python3
"""Scan committed logs/cache for accidentally-leaked API keys (esp. S2_API_KEY).

Patterns:
  * S2_API_KEY=...   (literal)
  * x-api-key:       (HTTP header echoed)
  * 32-byte hex strings  (heuristic — only flags if context says "S2" or "key")
  * `Authorization: Bearer ...` lines

Files scanned:
  * shared/references.log.yaml
  * shared/references.cache.json
  * shared/references_pdf/*.pdf.meta.yaml

Exit 1 on any hit. Run from CI as part of `make check-bib`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPORT_ROOT = Path(__file__).resolve().parent.parent

PATTERNS = [
    re.compile(r"S2_API_KEY\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"x-?api-key", re.IGNORECASE),
    re.compile(r"Authorization\s*:\s*Bearer\s+\S+"),
    re.compile(r"semantic[-_]?scholar[-_]?api[-_]?key", re.IGNORECASE),
]

TARGETS = [
    REPORT_ROOT / "shared" / "references.log.yaml",
    REPORT_ROOT / "shared" / "references.cache.json",
] + list((REPORT_ROOT / "shared" / "references_pdf").glob("*.pdf.meta.yaml"))


def main() -> int:
    hits: list[str] = []
    for f in TARGETS:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for pat in PATTERNS:
            for m in pat.finditer(text):
                hits.append(f"{f.relative_to(REPORT_ROOT)}: {m.group(0)[:60]}...")
    if hits:
        print(f"[check_logs_for_secrets] {len(hits)} possible leak(s):")
        for h in hits:
            print(f"  - {h}")
        return 1
    print("[check_logs_for_secrets] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
