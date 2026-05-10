#!/usr/bin/env python3
"""Fetch a BibTeX entry from a primary source, verify against Semantic Scholar,
optionally download the PDF, and append to shared/references.bib +
shared/references.log.yaml.

Usage:
    fetch_bib.py 2310.06770                       # arXiv ID
    fetch_bib.py 10.1109/CVPR52733.2024.01234     # DOI
    fetch_bib.py https://openreview.net/forum?id=abc123
    fetch_bib.py --verify-title "ReAct: Synergizing ..."
    fetch_bib.py --interactive
    fetch_bib.py 2310.06770 --with-pdf

Hallucination protection — see REPORT_PLAN.md §9-11.

Exit codes:
  0 — appended (or --verify-title found a matching paper)
  1 — failure / hallucination suspected
  2 — bad arguments
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_ROOT = Path(__file__).resolve().parent.parent
SHARED = REPORT_ROOT / "shared"
BIB_FILE = SHARED / "references.bib"
LOG_FILE = SHARED / "references.log.yaml"
CACHE_FILE = SHARED / "references.cache.json"
PDF_DIR = SHARED / "references_pdf"

ENV_PATH = REPORT_ROOT.parent / ".env"

S2_BASE = "https://api.semanticscholar.org/graph/v1"


# ----------------------------------------------------------------- env
def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k in {"S2_API_KEY"}})
    return env


# ----------------------------------------------------------------- identifiers
ARXIV_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
DOI_RE = re.compile(r"^10\.\d{4,9}/[^\s]+$")
OPENREVIEW_RE = re.compile(r"openreview\.net/(forum|pdf)\?id=([\w-]+)")


def _classify(token: str) -> tuple[str, str]:
    t = token.strip()
    if ARXIV_RE.match(t):
        return "arxiv", t
    if DOI_RE.match(t):
        return "doi", t
    m = OPENREVIEW_RE.search(t)
    if m:
        return "openreview", m.group(2)
    if t.startswith("http"):
        return "url", t
    return "title", t


# ----------------------------------------------------------------- HTTP
def _request(url: str, headers: dict[str, str] | None = None,
             params: dict[str, Any] | None = None,
             method: str = "GET", body: dict | None = None) -> dict:
    import requests  # imported locally so the script also runs on `--help`
    response = requests.request(method, url, headers=headers or {},
                                params=params, json=body, timeout=30)
    response.raise_for_status()
    if "json" in response.headers.get("Content-Type", ""):
        return response.json()
    return {"text": response.text}


# ----------------------------------------------------------------- S2
def s2_paper(paper_id: str, env: dict[str, str]) -> dict | None:
    fields = "title,authors,year,venue,externalIds,publicationVenue,publicationDate,publicationTypes,journal,openAccessPdf,tldr"
    headers = {}
    if env.get("S2_API_KEY"):
        headers["x-api-key"] = env["S2_API_KEY"]
    try:
        return _request(f"{S2_BASE}/paper/{paper_id}",
                        headers=headers, params={"fields": fields})
    except Exception as e:
        print(f"[fetch_bib] S2 lookup failed for {paper_id!r}: {e}", file=sys.stderr)
        return None


def s2_search(title: str, env: dict[str, str], limit: int = 10) -> list[dict]:
    headers = {}
    if env.get("S2_API_KEY"):
        headers["x-api-key"] = env["S2_API_KEY"]
    try:
        data = _request(f"{S2_BASE}/paper/search",
                        headers=headers,
                        params={"query": title, "limit": limit,
                                "fields": "title,authors,year,externalIds"})
        return data.get("data", [])
    except Exception as e:
        print(f"[fetch_bib] S2 search failed: {e}", file=sys.stderr)
        return []


# ----------------------------------------------------------------- arXiv / DOI
def fetch_arxiv(arxiv_id: str) -> dict:
    """Fetch arXiv metadata via export.arxiv.org."""
    import requests, xml.etree.ElementTree as ET
    url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(r.text)
    entry = root.find("a:entry", ns)
    if entry is None:
        raise RuntimeError(f"arXiv: entry not found for {arxiv_id}")
    title = (entry.findtext("a:title", "", ns) or "").strip()
    authors = [a.findtext("a:name", "", ns) for a in entry.findall("a:author", ns)]
    pub = (entry.findtext("a:published", "", ns) or "")[:4]
    summary = (entry.findtext("a:summary", "", ns) or "").strip()
    return {"id": arxiv_id, "title": title, "authors": authors,
            "year": int(pub) if pub.isdigit() else 0, "summary": summary}


def fetch_doi(doi: str) -> dict:
    import requests
    r = requests.get(f"https://doi.org/{doi}",
                     headers={"Accept": "application/x-bibtex"},
                     timeout=30, allow_redirects=True)
    r.raise_for_status()
    return {"doi": doi, "bibtex": r.text}


# ----------------------------------------------------------------- citation key
def make_citekey(authors: list[str], year: int, title: str) -> str:
    if not authors:
        last = "anon"
    else:
        last = re.sub(r"[^a-zA-Z]", "", authors[0].split()[-1] or "anon").lower()
    first_word = re.sub(r"[^a-zA-Z]", "", title.split()[0] if title else "").lower()
    return f"{last}{year}{first_word}"[:40]


# ----------------------------------------------------------------- bib append
def append_bib(entry_text: str) -> None:
    BIB_FILE.write_text(BIB_FILE.read_text(encoding="utf-8") + "\n" + entry_text + "\n",
                        encoding="utf-8")


def append_log(record: dict) -> None:
    import yaml
    log = yaml.safe_load(LOG_FILE.read_text(encoding="utf-8")) or {"records": []}
    log["records"].append(record)
    LOG_FILE.write_text(yaml.safe_dump(log, sort_keys=False, allow_unicode=True),
                        encoding="utf-8")


# ----------------------------------------------------------------- verification
def verify_title_only(title: str, env: dict[str, str]) -> int:
    from rapidfuzz import fuzz
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from normalize_title import normalize_title

    candidates = s2_search(title, env, limit=10)
    if not candidates:
        print("[fetch_bib] HALLUCINATION SUSPECTED: no S2 matches for title")
        return 1
    nt = normalize_title(title)
    best = max(((fuzz.ratio(nt, normalize_title(c.get("title", ""))) / 100.0, c)
                for c in candidates),
               key=lambda x: x[0])
    score, c = best
    if score < 0.90:
        print(f"[fetch_bib] HALLUCINATION SUSPECTED: best S2 match score {score:.2f} < 0.90")
        print(f"  closest: {c.get('title')}  ({c.get('year')})  authors={[a.get('name') for a in c.get('authors',[])][:3]}")
        return 1
    print(f"[fetch_bib] verify-title OK: {c.get('title')!r} match={score:.2f}")
    print(f"  externalIds: {c.get('externalIds')}")
    return 0


def fetch_one(token: str, env: dict[str, str], with_pdf: bool) -> int:
    kind, value = _classify(token)
    print(f"[fetch_bib] kind={kind} value={value!r}")
    if kind == "arxiv":
        primary = fetch_arxiv(value)
        s2_id = f"arXiv:{value}"
    elif kind == "doi":
        primary = fetch_doi(value)
        primary.update({"id": value, "title": "", "authors": [], "year": 0})
        s2_id = f"DOI:{value}"
    elif kind == "title":
        return verify_title_only(value, env)
    else:
        print(f"[fetch_bib] handler for {kind!r} not implemented", file=sys.stderr)
        return 1

    s2 = s2_paper(s2_id, env)
    if s2 is None:
        print("[fetch_bib] S2 verification could not be performed (degraded)")
    else:
        # cross-check title / first author / year
        from rapidfuzz import fuzz
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from normalize_title import normalize_title
        if primary.get("title"):
            score = fuzz.ratio(normalize_title(primary["title"]),
                               normalize_title(s2.get("title", ""))) / 100.0
            if score < 0.90:
                print(f"[fetch_bib] HALLUCINATION/DRIFT: title mismatch score {score:.2f}")
                print(f"  primary: {primary['title']!r}")
                print(f"  s2:      {s2.get('title')!r}")
                return 1

    citekey = make_citekey(primary.get("authors", []), primary.get("year", 0),
                           primary.get("title", ""))
    print(f"[fetch_bib] proposed citation key: {citekey}")

    # Append to bib (caller composes a real entry; here we only stub the
    # @misc form so the workflow is testable end-to-end).
    bib_entry = textwrap.dedent(f"""
        @misc{{{citekey},
          title = {{{primary.get('title','TITLE')}}},
          author = {{{' and '.join(primary.get('authors',[]))}}},
          year = {{{primary.get('year', 0)}}},
          eprint = {{{value if kind=='arxiv' else ''}}},
          archiveprefix = {{arXiv}},
          note = {{auto-fetched {datetime.now(timezone.utc).isoformat()}}}
        }}
        """).strip()
    append_bib(bib_entry)
    append_log({
        "citekey": citekey,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source_type": kind,
        "source_id": value,
        "s2_paperId": (s2 or {}).get("paperId"),
        "http_status": 200,
    })
    print(f"[fetch_bib] appended {citekey} → references.bib + references.log.yaml")

    if with_pdf:
        # Best-effort: try arXiv direct first; full implementation belongs in pull_pdfs.py
        if kind == "arxiv":
            import requests
            url = f"https://arxiv.org/pdf/{value}.pdf"
            r = requests.get(url, timeout=60)
            if r.ok:
                PDF_DIR.mkdir(parents=True, exist_ok=True)
                (PDF_DIR / f"{citekey}.pdf").write_bytes(r.content)
                print(f"[fetch_bib] saved {citekey}.pdf ({len(r.content)} bytes)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("token", nargs="?")
    ap.add_argument("--verify-title", help="only verify a title against S2 search")
    ap.add_argument("--with-pdf", action="store_true")
    ap.add_argument("--interactive", action="store_true")
    args = ap.parse_args()

    env = _load_env()
    if args.verify_title:
        return verify_title_only(args.verify_title, env)
    if args.interactive:
        token = input("enter id/doi/url/title> ").strip()
    else:
        token = args.token
    if not token:
        ap.print_help()
        return 2
    try:
        return fetch_one(token, env, args.with_pdf)
    except Exception as e:
        print(f"[fetch_bib] failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
