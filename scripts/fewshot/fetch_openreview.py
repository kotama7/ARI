#!/usr/bin/env python3
"""Fetch a paper + review(s) from OpenReview into a fewshot example pair.

Requires: pip install openreview-py

Usage (via sync.py):
    manifest.yaml entry:
      - id: my_paper
        source: openreview
        forum_id: "..."

Output: <out_dir>/<id>.{pdf, txt, json}
"""

from __future__ import annotations

import json
from pathlib import Path


def fetch(entry: dict, out_dir: Path) -> None:
    try:
        import openreview  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "openreview-py not installed. Install with: pip install openreview-py"
        ) from e

    eid = entry["id"]
    forum_id = entry["forum_id"]
    api_url = entry.get("api_url", "https://api2.openreview.net")
    client = openreview.api.OpenReviewClient(baseurl=api_url)

    # Paper PDF
    notes = client.get_notes(forum=forum_id)
    if not notes:
        raise RuntimeError(f"no notes for forum {forum_id}")
    submission = next(
        (n for n in notes if "title" in (n.content or {})), notes[0]
    )
    content = submission.content or {}
    title = content.get("title", {}).get("value", "") if isinstance(
        content.get("title"), dict
    ) else content.get("title", "")

    # Collect reviews (first one for now)
    reviews = [
        n for n in notes
        if (n.content or {}).get("rating") or (n.content or {}).get("summary")
    ]
    if not reviews:
        raise RuntimeError(f"no reviews found for forum {forum_id}")

    first = reviews[0].content or {}

    def _v(key: str, default=None):
        v = first.get(key)
        if isinstance(v, dict) and "value" in v:
            return v["value"]
        return v if v is not None else default

    review_json = {
        "_source": "OpenReview",
        "_forum_id": forum_id,
        "title": title,
        "soundness": _v("soundness"),
        "presentation": _v("presentation"),
        "contribution": _v("contribution"),
        "overall": _v("rating"),
        "confidence": _v("confidence"),
        "strengths": _v("strengths") or _v("summary_of_strengths"),
        "weaknesses": _v("weaknesses") or _v("summary_of_weaknesses"),
        "questions": _v("questions"),
        "limitations": _v("limitations"),
        "decision": "accept" if (_v("rating") or 0) >= 6 else "reject",
    }
    (out_dir / f"{eid}.json").write_text(json.dumps(review_json, indent=2))

    # Try to download the PDF + extract a .txt excerpt
    pdf_url = content.get("pdf", {}).get("value") if isinstance(
        content.get("pdf"), dict
    ) else content.get("pdf")
    if pdf_url:
        try:
            raw = client.get_attachment(submission.id, "pdf")
            (out_dir / f"{eid}.pdf").write_bytes(raw)
            try:
                import fitz  # type: ignore
                doc = fitz.open(out_dir / f"{eid}.pdf")
                text = "\n".join(p.get_text() for p in doc)
                (out_dir / f"{eid}.txt").write_text(text[:20000])
                doc.close()
            except Exception:
                pass
        except Exception:
            pass


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: fetch_openreview.py <forum_id> <out_dir>", file=sys.stderr)
        sys.exit(1)
    fetch({"id": "cli", "forum_id": sys.argv[1]}, Path(sys.argv[2]))
