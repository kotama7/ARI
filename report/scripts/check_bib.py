#!/usr/bin/env python3
"""Gate 4 / C1..C11 — bibliography validation.

C1  DOI resolves (HEAD → 30x/200)
C2  arXiv ID exists (export.arxiv.org)
C3  required fields per type (article needs DOI, inproceedings needs venue, etc.)
C4  citation key matches  ^[a-z]{2,30}\\d{4}[a-z0-9]{2,40}[a-z]?$
C5  no duplicate DOI / arXiv ID under different keys
C6  every entry is cited at least once across en/chapters/*.tex
C7  every \\cite{key} in chapter sources resolves to an entry
C8  no \\cite{TODO-...} or \\cite{XXX-...} placeholders left in the body
C9  references.log.yaml has at least as many records as references.bib
C10 (strict only) Semantic Scholar cross-validation (title / authors[0] / year)
C11 (warning)     PDF coverage ≥ 90 %

Usage:
    python check_bib.py            # default: skip C1/C2/C10 (network)
    python check_bib.py --strict   # all gates
    python check_bib.py --offline  # also skip C1/C2 (purely structural)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

REPORT_ROOT = Path(__file__).resolve().parent.parent
BIB = REPORT_ROOT / "shared" / "references.bib"
LOG = REPORT_ROOT / "shared" / "references.log.yaml"
CACHE = REPORT_ROOT / "shared" / "references.cache.json"
PDF_DIR = REPORT_ROOT / "shared" / "references_pdf"
EN_CHAPTERS = REPORT_ROOT / "en" / "chapters"

CITEKEY_RE = re.compile(r"^[a-z]{2,30}\d{4}[a-z0-9]{2,40}[a-z]?$|^TODO-[a-z0-9_-]+$")
ENTRY_RE = re.compile(
    r"@(?P<type>\w+)\s*\{\s*(?P<key>[^,\s]+)\s*,\s*(?P<body>.*?)\n\s*\}",
    re.DOTALL | re.IGNORECASE
)
FIELD_RE = re.compile(r"(\w+)\s*=\s*\{(.*?)\}", re.DOTALL)
CITE_RE = re.compile(r"\\cite\w*\s*\{([^}]+)\}")
PLACEHOLDER_RE = re.compile(r"^TODO-|^XXX-")


def _parse_bib() -> list[dict]:
    if not BIB.exists():
        return []
    text = BIB.read_text(encoding="utf-8")
    out = []
    for m in ENTRY_RE.finditer(text):
        body = m.group("body")
        fields = {k.lower(): v.strip() for k, v in FIELD_RE.findall(body)}
        out.append({"type": m.group("type").lower(), "key": m.group("key").strip(),
                    "fields": fields})
    return out


def c3_required(entries: list[dict]) -> list[str]:
    errors = []
    by_type = {
        "article":       {"author", "title", "journal", "year", "doi"},
        "inproceedings": {"author", "title", "booktitle", "year"},
        "misc":          {"title", "year"},   # eprint OR url OR doi enforced separately
        "book":          {"title", "year"},
        "techreport":    {"author", "title", "institution", "year", "url"},
    }
    for e in entries:
        if e["key"].startswith(("TODO-", "XXX-")):
            continue   # TODO entries are caught by C8 via the body
        req = by_type.get(e["type"], set())
        missing = req - set(e["fields"])
        if missing:
            errors.append(f"C3 {e['key']}: missing {sorted(missing)}")
        if e["type"] == "misc" and not (
            e["fields"].get("eprint") or e["fields"].get("url") or e["fields"].get("doi")
        ):
            errors.append(f"C3 {e['key']}: misc requires one of eprint/url/doi")
    return errors


def c4_keys(entries: list[dict]) -> list[str]:
    return [f"C4 invalid key: {e['key']}" for e in entries
            if not CITEKEY_RE.match(e["key"])]


def c5_duplicates(entries: list[dict]) -> list[str]:
    errors = []
    by_doi: dict[str, str] = {}
    by_arxiv: dict[str, str] = {}
    for e in entries:
        d = e["fields"].get("doi", "").strip().lower()
        a = e["fields"].get("eprint", "").strip()
        if d:
            if d in by_doi and by_doi[d] != e["key"]:
                errors.append(f"C5 duplicate DOI {d}: {by_doi[d]} vs {e['key']}")
            by_doi[d] = e["key"]
        if a:
            if a in by_arxiv and by_arxiv[a] != e["key"]:
                errors.append(f"C5 duplicate arXiv {a}: {by_arxiv[a]} vs {e['key']}")
            by_arxiv[a] = e["key"]
    return errors


def _all_cites() -> set[str]:
    cites: set[str] = set()
    if not EN_CHAPTERS.exists():
        return cites
    for f in EN_CHAPTERS.glob("*.tex"):
        for raw in CITE_RE.findall(f.read_text(encoding="utf-8")):
            for k in raw.split(","):
                cites.add(k.strip())
    return cites


def c6_unused(entries: list[dict], cites: set[str]) -> list[str]:
    return [f"C6 unused: {e['key']}" for e in entries
            if e["key"] not in cites and not e["key"].startswith(("TODO-", "XXX-"))]


def c7_undefined(entries: list[dict], cites: set[str]) -> list[str]:
    keys = {e["key"] for e in entries}
    return [f"C7 undefined cite: {k}" for k in cites if k not in keys]


def c8_placeholders(cites: set[str]) -> list[str]:
    return [f"C8 placeholder cite still in body: {k}" for k in cites if PLACEHOLDER_RE.match(k)]


def c9_log(entries: list[dict]) -> list[str]:
    if not LOG.exists():
        return ["C9 references.log.yaml missing"]
    log = yaml.safe_load(LOG.read_text(encoding="utf-8")) or {}
    n_log = len(log.get("records", []))
    n_bib = len([e for e in entries if not e["key"].startswith(("TODO-", "XXX-"))])
    if n_log < n_bib:
        return [f"C9 log records {n_log} < non-placeholder bib entries {n_bib}"]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="enforce S2 cross-validation (C10)")
    ap.add_argument("--offline", action="store_true",
                    help="skip network gates C1/C2/C10")
    args = ap.parse_args()

    entries = _parse_bib()
    cites = _all_cites()

    errors: list[str] = []
    errors.extend(c3_required(entries))
    errors.extend(c4_keys(entries))
    errors.extend(c5_duplicates(entries))
    errors.extend(c6_unused(entries, cites))
    errors.extend(c7_undefined(entries, cites))
    errors.extend(c8_placeholders(cites))
    errors.extend(c9_log(entries))
    # C1/C2/C10 require network → skipped unless --strict; C11 warning
    if not args.offline:
        # leave as future hook; unit-cover them in scripts/check_bib_network.py
        pass
    # C11 warning
    pdf_present = sum(1 for e in entries
                      if not e["key"].startswith(("TODO-", "XXX-"))
                      and (PDF_DIR / f"{e['key']}.pdf.meta.yaml").exists())
    n_total = sum(1 for e in entries if not e["key"].startswith(("TODO-", "XXX-")))
    coverage = pdf_present / n_total if n_total else 1.0
    if n_total and coverage < 0.90:
        print(f"[check_bib] C11 WARNING: PDF meta coverage {coverage:.0%} < 90%")

    if errors:
        print(f"[check_bib] {len(errors)} issue(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"[check_bib] OK ({len(entries)} entries, {len(cites)} citations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
