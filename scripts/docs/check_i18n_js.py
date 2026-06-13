#!/usr/bin/env python3
"""Gate: the per-surface i18n dictionaries declare identical key sets.

The website language switcher loads one flat object per language, merged into
``window.LANGS.<lang>``. As of the L1 surface split (P3) the dictionaries are
split by surface:

  * ``docs/i18n/landing.{en,ja,zh}.js`` — landing page (index.html)

(The legacy ``docs.{en,ja,zh}.js`` docs-viewer dictionaries were removed in L3
when the documentation surface moved to VitePress, whose locale-routed pages own
their own i18n — see docs/.vitepress/.)

A key present in one language but missing from another renders as a blank /
fallback UI string in the untranslated locales. This gate fails (exit 1) when,
*within a surface*, the key SETS diverge across en/ja/zh, or when a file repeats
a key.

Values are intentionally NOT compared: a proper noun (``'hero-eyebrow':
'Artificial Research Intelligence'``) legitimately reads the same in every
language, so only the *key set* is the invariant.

Each entry occupies its own line (``  'key': '...'``) in these files, so a
per-line scan of single-quoted keys is unambiguous. Pure stdlib, no
dependencies, no network/LLM. ``keys_of`` / ``duplicates`` / ``parity_errors``
are imported by ``check_site_i18n.py`` (reuse, no double implementation).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
I18N = REPO_ROOT / "docs" / "i18n"
SURFACES = ("landing",)  # docs surface moved to VitePress (L3)
LANGS = ("en", "ja", "zh")

# `  'some-key': '...'` — a single-quoted key at line start, then a colon.
KEY_RE = re.compile(r"^\s*'([^']+)'\s*:")


def keys_of(path: Path) -> list[str]:
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = KEY_RE.match(line)
        if m:
            out.append(m.group(1))
    return out


def duplicates(keys: list[str]) -> list[str]:
    seen: set[str] = set()
    dups: list[str] = []
    for k in keys:
        if k in seen and k not in dups:
            dups.append(k)
        seen.add(k)
    return dups


def surface_file(surface: str, lang: str) -> Path:
    return I18N / f"{surface}.{lang}.js"


def parity_errors(surface: str) -> tuple[list[str], dict[str, int]]:
    """Return (errors, per-lang key counts) for one surface."""
    errors: list[str] = []
    missing = [lang for lang in LANGS if not surface_file(surface, lang).exists()]
    if missing:
        names = [f"{surface}.{lang}.js" for lang in missing]
        errors.append(f"missing i18n file(s): {names}")
        return errors, {}

    keys = {lang: keys_of(surface_file(surface, lang)) for lang in LANGS}
    sets = {lang: set(keys[lang]) for lang in LANGS}
    union = set().union(*sets.values())
    for lang in LANGS:
        dups = duplicates(keys[lang])
        if dups:
            errors.append(f"{surface}.{lang}.js: duplicate key(s): {sorted(dups)}")
        miss = sorted(union - sets[lang])
        if miss:
            errors.append(f"{surface}.{lang}.js: missing key(s): {miss}")
    counts = {lang: len(keys[lang]) for lang in LANGS}
    return errors, counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    all_errors: list[str] = []
    all_counts: dict[str, dict[str, int]] = {}
    for surface in SURFACES:
        errors, counts = parity_errors(surface)
        all_errors.extend(errors)
        all_counts[surface] = counts

    if args.json:
        print(json.dumps({"counts": all_counts, "errors": all_errors},
                         ensure_ascii=False, indent=2))
    elif all_errors:
        print(f"[check_i18n_js] {len(all_errors)} issue(s):")
        for e in all_errors:
            print(f"  - {e}")
    else:
        summary = ", ".join(
            f"{s}={all_counts[s].get('en', 0)}" for s in SURFACES
        )
        print(f"[check_i18n_js] OK — key parity across {', '.join(LANGS)} ({summary})")
    return 1 if all_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
