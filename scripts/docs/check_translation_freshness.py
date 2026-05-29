#!/usr/bin/env python3
"""Detect translation *content* drift via the ``last_verified`` front-matter.

The parity table (``docs/README.md``) and ``check_doc_links.py`` only see file
*existence* and link targets — they cannot tell that an English doc was updated
while its ``ja/`` / ``zh/`` counterparts were left behind.  This gate closes
that gap with a cheap, deterministic check:

    for every English live doc, its translations must declare a
    ``last_verified`` date that is **>=** the English one.

If English is newer than a translation, the translation is presumed stale.

Staged rollout (mirrors ``check_doc_sources.py``):
  * default          -> stale translations are **warnings** (exit 0).
  * ``--strict``     -> stale translations are **errors** (exit 1).

A missing translation file, or a missing/invalid ``last_verified`` on either
side, is reported so the matrix and the dates stay trustworthy.  ``--json`` for
machine-readable output.

Design: docs/最終統合計画書.md gap G4 — translation freshness governance.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    sys.stderr.write(
        "check_translation_freshness: PyYAML is required (pip install pyyaml).\n"
    )
    raise SystemExit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"
LANGS = ("ja", "zh")

# Docs that legitimately carry no front-matter / last_verified (kept in sync
# with check_doc_sources.py's exemptions).
EXEMPT_FILES = {"docs/README.md"}
EXEMPT_DIR_SEGMENTS = ("_archive",)


def is_exempt(rel: str) -> bool:
    if rel in EXEMPT_FILES:
        return True
    return any(seg in rel.split("/") for seg in EXEMPT_DIR_SEGMENTS)


def split_front_matter(text: str) -> str | None:
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i])
    return None


def last_verified(path: Path):
    """Return (date or None, error_message or None)."""
    fm = split_front_matter(path.read_text(encoding="utf-8"))
    if fm is None:
        return None, "no front-matter"
    try:
        data = yaml.safe_load(fm) or {}
    except yaml.YAMLError as exc:
        return None, f"invalid YAML front-matter: {exc}"
    if not isinstance(data, dict) or "last_verified" not in data:
        return None, "no `last_verified` field"
    val = data["last_verified"]
    if isinstance(val, _dt.date):
        return val, None
    try:
        return _dt.date.fromisoformat(str(val)), None
    except ValueError:
        return None, f"unparseable last_verified: {val!r}"


def english_docs() -> list[Path]:
    out = []
    for p in sorted(DOCS.rglob("*.md")):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if rel.startswith("docs/ja/") or rel.startswith("docs/zh/"):
            continue
        if is_exempt(rel):
            continue
        out.append(p)
    return out


class Finding:
    __slots__ = ("doc", "level", "message")

    def __init__(self, doc, level, message):
        self.doc, self.level, self.message = doc, level, message

    def as_dict(self):
        return {"doc": self.doc, "level": self.level, "message": self.message}

    def __str__(self):
        return f"{self.doc}: [{self.level}] {self.message}"


def check(strict: bool) -> list[Finding]:
    findings: list[Finding] = []
    stale_level = "error" if strict else "warning"
    for en in english_docs():
        rel = en.relative_to(REPO_ROOT).as_posix()
        en_date, en_err = last_verified(en)
        if en_err:
            # Missing/invalid date on the English source is always an error —
            # it makes the whole comparison undecidable.
            findings.append(Finding(rel, "error", f"english {en_err}"))
            continue
        sub = en.relative_to(DOCS).as_posix()
        for lang in LANGS:
            tr = DOCS / lang / sub
            tr_rel = tr.relative_to(REPO_ROOT).as_posix()
            if not tr.exists():
                findings.append(Finding(tr_rel, "error", "translation file missing"))
                continue
            tr_date, tr_err = last_verified(tr)
            if tr_err:
                findings.append(Finding(tr_rel, "error", tr_err))
                continue
            if en_date > tr_date:
                findings.append(Finding(
                    tr_rel, stale_level,
                    f"stale: en last_verified {en_date} > {lang} {tr_date}",
                ))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--strict", action="store_true",
        help="treat stale translations as errors (exit 1), not warnings",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    findings = check(args.strict)
    errors = [f for f in findings if f.level == "error"]
    warnings = [f for f in findings if f.level == "warning"]

    if args.json:
        print(json.dumps({
            "scanned": len(english_docs()),
            "errors": [f.as_dict() for f in errors],
            "warnings": [f.as_dict() for f in warnings],
        }, ensure_ascii=False, indent=2))
    else:
        for f in errors + warnings:
            print(f)
        print(
            f"\nscanned {len(english_docs())} english docs: "
            f"{len(errors)} error(s), {len(warnings)} stale warning(s)"
            + ("" if args.strict else " (stale not enforced)")
        )

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
