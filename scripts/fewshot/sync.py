#!/usr/bin/env python3
"""Sync the few-shot corpus into ari-core/config/reviewer_rubrics/fewshot_examples/.

Reads manifest.yaml and dispatches to the appropriate fetcher:
    - openreview → fetch_openreview.py
    - arxiv      → fetch_arxiv.py
    - synthetic  → no-op (already committed)

Usage:
    python scripts/fewshot/sync.py                # sync all venues
    python scripts/fewshot/sync.py --venue neurips  # one venue only
    python scripts/fewshot/sync.py --dry-run      # plan only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML required: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST = Path(__file__).resolve().parent / "manifest.yaml"
FEWSHOT_ROOT = REPO_ROOT / "ari-core" / "config" / "reviewer_rubrics" / "fewshot_examples"


def sync_entry(venue: str, entry: dict, dry_run: bool) -> str:
    source = entry.get("source", "").lower()
    eid = entry.get("id", "unknown")
    out_dir = FEWSHOT_ROOT / venue
    out_dir.mkdir(parents=True, exist_ok=True)
    target_json = out_dir / f"{eid}.json"
    if source == "synthetic":
        return (
            f"  [skip] {venue}/{eid}: synthetic, already committed"
            if target_json.exists()
            else f"  [WARN] {venue}/{eid}: synthetic declared but missing"
        )
    if source == "github_raw":
        if dry_run:
            return f"  [plan] {venue}/{eid}: github_raw {entry.get('base_url')}/{eid}.*"
        try:
            from fetch_github_raw import fetch as _fetch_gh  # type: ignore
        except ImportError:
            return f"  [error] fetch_github_raw unavailable"
        try:
            _fetch_gh(entry, out_dir)
            return f"  [ok] {venue}/{eid}: fetched from GitHub raw"
        except Exception as e:
            return f"  [error] {venue}/{eid}: {e}"
    if source == "openreview":
        if dry_run:
            return f"  [plan] {venue}/{eid}: OpenReview forum {entry.get('forum_id')}"
        try:
            from fetch_openreview import fetch  # type: ignore
        except ImportError:
            return f"  [error] fetch_openreview unavailable (install openreview-py)"
        try:
            fetch(entry, out_dir)
            return f"  [ok] {venue}/{eid}: fetched from OpenReview"
        except Exception as e:
            return f"  [error] {venue}/{eid}: {e}"
    if source == "arxiv":
        if dry_run:
            return f"  [plan] {venue}/{eid}: arXiv {entry.get('arxiv_id')}"
        try:
            from fetch_arxiv import fetch  # type: ignore
        except ImportError:
            return f"  [error] fetch_arxiv unavailable"
        try:
            fetch(entry, out_dir)
            return f"  [ok] {venue}/{eid}: fetched from arXiv"
        except Exception as e:
            return f"  [error] {venue}/{eid}: {e}"
    return f"  [unknown source] {venue}/{eid}: {source}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--venue", default="", help="Sync only this venue id")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not MANIFEST.exists():
        print(f"Missing manifest: {MANIFEST}", file=sys.stderr)
        return 1
    data = yaml.safe_load(MANIFEST.read_text()) or {}
    venues = [args.venue] if args.venue else list(data.keys())

    print(f"Syncing fewshot corpus ({'dry-run' if args.dry_run else 'live'})")
    for v in venues:
        entries = data.get(v, []) or []
        print(f"[{v}] ({len(entries)} entries)")
        for entry in entries:
            print(sync_entry(v, entry, args.dry_run))
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
