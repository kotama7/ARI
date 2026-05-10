#!/usr/bin/env python3
"""Re-download all reference PDFs that are missing locally.

Reads every shared/references_pdf/<key>.pdf.meta.yaml and, if the matching
<key>.pdf is absent, downloads from `source.preferred_url`. Verifies sha256
against the meta file when possible.

Usage: python pull_pdfs.py
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import yaml

REPORT_ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = REPORT_ROOT / "shared" / "references_pdf"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not PDF_DIR.exists():
        print(f"[pull_pdfs] no PDF dir at {PDF_DIR}; nothing to do")
        return 0
    metas = list(PDF_DIR.glob("*.pdf.meta.yaml"))
    if not metas:
        print("[pull_pdfs] no meta files; nothing to fetch")
        return 0

    import requests
    fetched = skipped = failed = 0
    for meta in metas:
        cfg = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
        key = cfg.get("citekey") or meta.stem.replace(".pdf.meta", "")
        target = PDF_DIR / f"{key}.pdf"
        if target.exists():
            skipped += 1
            continue
        if cfg.get("license", {}).get("closed_access"):
            print(f"[pull_pdfs] skip {key}: closed_access (manual placement required)")
            skipped += 1
            continue
        url = (cfg.get("source") or {}).get("preferred_url")
        if not url:
            print(f"[pull_pdfs] skip {key}: no preferred_url in meta")
            skipped += 1
            continue
        try:
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            target.write_bytes(r.content)
            actual = _sha256(target)
            expected = (cfg.get("file") or {}).get("sha256")
            if expected and actual != expected:
                print(f"[pull_pdfs] WARNING {key}: sha256 mismatch (got {actual[:8]}.. expected {expected[:8]}..)")
            print(f"[pull_pdfs] fetched {key} ({len(r.content)} bytes)")
            fetched += 1
        except Exception as e:
            print(f"[pull_pdfs] FAILED {key}: {e}")
            failed += 1

    print(f"[pull_pdfs] {fetched} fetched, {skipped} skipped, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
