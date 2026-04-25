#!/usr/bin/env python3
"""Fetch few-shot example files from a raw.githubusercontent.com URL.

Used for redistributing Apache-2.0 / permissively licensed example corpora
(currently: SakanaAI/AI-Scientist-v2 fewshot_examples).

Manifest entry shape:
    - id: attention
      source: github_raw
      base_url: https://raw.githubusercontent.com/SakanaAI/AI-Scientist-v2/main/ai_scientist/fewshot_examples
      files: [json, pdf, txt]
      license: Apache-2.0
"""

from __future__ import annotations

import urllib.request
from pathlib import Path


def fetch(entry: dict, out_dir: Path) -> None:
    eid = entry["id"]
    base = entry["base_url"].rstrip("/")
    exts = entry.get("files") or ["json"]
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in exts:
        url = f"{base}/{eid}.{ext}"
        dest = out_dir / f"{eid}.{ext}"
        req = urllib.request.Request(
            url, headers={"User-Agent": "ari-fewshot-fetcher/1.0"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                dest.write_bytes(resp.read())
        except Exception as e:
            # Some extensions (txt) may not exist on the remote; skip silently.
            if ext == "json":
                raise RuntimeError(f"required {url} failed: {e}") from e
