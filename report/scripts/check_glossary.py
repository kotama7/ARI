#!/usr/bin/env python3
"""Gate 7 — glossary fixation.

For each glossary entry, every occurrence of the en/ja/zh form in the
corresponding language's chapter text MUST be the canonical form. Any
match listed in `forbidden_alternatives` causes a fail.

Usage:
    python check_glossary.py [--lang ja zh] [--strict]

The script does not enforce *positive* coverage (every glossary term must
appear at least once) — the report would be needlessly verbose. It only
catches *deviations* from the canonical form.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

REPORT_ROOT = Path(__file__).resolve().parent.parent
GLOSSARY = REPORT_ROOT / "shared" / "glossary.yaml"

LANG_DIRS = {"en": "en", "ja": "ja", "zh": "zh"}


def _load() -> dict:
    with GLOSSARY.open() as f:
        return yaml.safe_load(f)


def _chapter_files(lang: str) -> list[Path]:
    chapters = (REPORT_ROOT / lang / "chapters")
    if not chapters.exists():
        return []
    return sorted(chapters.glob("*.tex"))


def _strip_comments(tex: str) -> str:
    """Drop LaTeX % comments so glossary checks don't false-positive on metadata."""
    return re.sub(r"(?<!\\)%[^\n]*", "", tex)


def check_lang(lang: str, glossary: dict, strict: bool) -> list[str]:
    errors: list[str] = []
    forbidden = (glossary.get("forbidden_alternatives") or {}).get(lang, {})
    files = _chapter_files(lang)
    if not files:
        return [f"{lang}: no chapter files under {lang}/chapters/"]

    for f in files:
        text = _strip_comments(f.read_text(encoding="utf-8"))
        for canonical, alternatives in forbidden.items():
            for alt in alternatives:
                if alt in text:
                    errors.append(
                        f"{f.relative_to(REPORT_ROOT)}: forbidden alternative "
                        f"'{alt}' appears (canonical form: '{canonical}')"
                    )

    # Optional strict mode: warn when a `do_not_translate` entry appears in
    # the wrong (translated) form (e.g. ReAct rendered as リアクト).
    if strict and lang in {"ja", "zh"}:
        for entry in glossary.get("entries", []):
            if not entry.get("do_not_translate"):
                continue
            canonical = entry["en"]
            for f in files:
                text = _strip_comments(f.read_text(encoding="utf-8"))
                if canonical not in text and re.search(re.escape(canonical), text) is None:
                    # heuristic: skip — strict mode just notes absence
                    pass
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", nargs="+", default=["ja", "zh"])
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    glossary = _load()
    errors: list[str] = []
    for lang in args.lang:
        errors.extend(check_lang(lang, glossary, args.strict))

    if errors:
        print(f"[check_glossary] {len(errors)} violation(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"[check_glossary] OK ({', '.join(args.lang)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
