#!/usr/bin/env python3
"""Gate: docs/i18n/{en,ja,zh}.js declare an identical set of string keys.

The website language switcher loads one flat object per language —
``window.LANGS.<lang> = { 'key': 'text', ... }`` — from ``docs/i18n/<lang>.js``.
A key present in one language but missing from another renders as a blank /
fallback UI string in the untranslated locales.  This gate fails (exit 1) when
the key SETS diverge, or when a file repeats a key.

Values are intentionally NOT compared: a proper noun (``'hero-eyebrow':
'Artificial Research Intelligence'``) legitimately reads the same in every
language, so only the *key set* is the invariant.

Each entry occupies its own line (``  'key': '...'``) in these files, so a
per-line scan of single-quoted keys is unambiguous.  Pure stdlib, no
dependencies, no network/LLM.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
I18N = REPO_ROOT / "docs" / "i18n"
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    missing = [lang for lang in LANGS if not (I18N / f"{lang}.js").exists()]
    if missing:
        print(f"[check_i18n_js] missing i18n file(s): {missing}")
        return 1

    keys = {lang: keys_of(I18N / f"{lang}.js") for lang in LANGS}
    sets = {lang: set(keys[lang]) for lang in LANGS}
    union = set().union(*sets.values())

    errors: list[str] = []
    for lang in LANGS:
        dups = duplicates(keys[lang])
        if dups:
            errors.append(f"{lang}.js: duplicate key(s): {sorted(dups)}")
        miss = sorted(union - sets[lang])
        if miss:
            errors.append(f"{lang}.js: missing key(s): {miss}")

    counts = {lang: len(keys[lang]) for lang in LANGS}
    if args.json:
        print(json.dumps({"counts": counts, "errors": errors}, ensure_ascii=False, indent=2))
    elif errors:
        print(f"[check_i18n_js] {len(errors)} issue(s):")
        for e in errors:
            print(f"  - {e}")
    else:
        print(
            f"[check_i18n_js] OK — {counts['en']} keys in parity across "
            f"{', '.join(LANGS)}"
        )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
