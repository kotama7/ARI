#!/usr/bin/env python3
"""Fetch an arXiv preprint into a fewshot example (paper text only; reviews
must be supplied separately as synthetic scores because arXiv has no reviews).

Usage via sync.py:
    - id: my_paper
      source: arxiv
      arxiv_id: "2408.06292"
      synthetic_review: { overall: 7, soundness: 3, ... }
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path


def fetch(entry: dict, out_dir: Path) -> None:
    eid = entry["id"]
    arxiv_id = entry["arxiv_id"]
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"

    req = urllib.request.Request(
        pdf_url, headers={"User-Agent": "ari-fewshot-fetcher/1.0"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        (out_dir / f"{eid}.pdf").write_bytes(resp.read())

    try:
        import fitz  # type: ignore
        doc = fitz.open(out_dir / f"{eid}.pdf")
        text = "\n".join(p.get_text() for p in doc)
        (out_dir / f"{eid}.txt").write_text(text[:20000])
        doc.close()
    except Exception:
        pass

    synth = entry.get("synthetic_review") or {}
    if synth:
        review = dict(synth)
        review["_source"] = f"arXiv:{arxiv_id}"
        review["_note"] = "Synthetic scores (arXiv has no peer reviews)"
        (out_dir / f"{eid}.json").write_text(json.dumps(review, indent=2))
