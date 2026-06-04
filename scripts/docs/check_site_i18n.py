#!/usr/bin/env python3
"""Gate: HTML-site i18n integrity — surface parity, no orphan t-ids, version.

Companion to ``check_i18n_js.py`` (which it reuses, not re-implements). Where
``check_i18n_js`` asserts the *key parity* invariant per surface, this gate adds
the three checks that close the homepage i18n debt (see docs/README.md,
"Homepage static site"):

  (a) surface parity        — landing.{en,ja,zh}.js declare an identical key set
                              (reuses ``check_i18n_js.parity_errors``). The docs
                              surface moved to VitePress in L3, so only the
                              landing remains an i18n-JS surface.
  (b) t-id ⊆ surface dict   — every ``id="t-<key>"`` in index.html resolves to a
                              key in the landing dict (orphan t-ids = 0). An
                              orphan renders English-frozen in ja/zh.
  (c) en→ja/zh co-change    — keys added to a surface's en dict since the merge
                              base must also exist in ja/zh (best-effort; needs
                              a git base — subsumed by (a) at the final state).
  (d) version single source — docs/version.json parses, matches report/en
                              ``\\date{vX.Y.Z, ...}``, and index.html carries no
                              hard-coded ``vX.Y.Z`` footer literal (version.js
                              injects it into #ari-version at runtime).

Pure stdlib (git via subprocess, optional). Exit 1 on any hard finding.
``--json`` for machine-readable output.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import check_i18n_js as ki  # reuse keys_of / duplicates / parity_errors

REPO_ROOT = ki.REPO_ROOT
DOCS = REPO_ROOT / "docs"
I18N = ki.I18N

# surface -> the HTML page whose t-ids must be a subset of that surface dict.
# (The docs surface moved to VitePress in L3; only the bespoke landing remains
# a t-id/i18n-JS surface.)
SURFACE_HTML = {"landing": "index.html"}

TID_RE = re.compile(r'id="t-([^"]+)"')
VERSION_FOOTER_RE = re.compile(r"v\d+\.\d+\.\d+\s*[·•]")  # "v0.8.0 · ..." literal
DATE_VERSION_RE = re.compile(r"\\date\{\s*(v\d+\.\d+\.\d+)")


def tids_of(html: Path) -> set[str]:
    return set(TID_RE.findall(html.read_text(encoding="utf-8")))


def git_keys_at_base(rel_path: str) -> set[str] | None:
    """Key set of a surface dict at the PR merge base, or None if unavailable."""
    bases = ["origin/main", "main", "origin/HEAD"]
    base = None
    for ref in bases:
        r = subprocess.run(
            ["git", "merge-base", "HEAD", ref],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            base = r.stdout.strip()
            break
    if not base:
        return None
    r = subprocess.run(
        ["git", "show", f"{base}:{rel_path}"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None  # file did not exist at base (newly added surface)
    out: set[str] = set()
    for line in r.stdout.splitlines():
        m = ki.KEY_RE.match(line)
        if m:
            out.add(m.group(1))
    return out


def check(strict_cochange: bool) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    # (a) surface parity
    for surface in ki.SURFACES:
        errs, _ = ki.parity_errors(surface)
        errors.extend(f"[parity] {e}" for e in errs)

    # (b) t-id ⊆ surface en dict (orphan = 0)
    for surface, html_name in SURFACE_HTML.items():
        en_file = ki.surface_file(surface, "en")
        html = DOCS / html_name
        if not en_file.exists() or not html.exists():
            continue
        dict_keys = set(ki.keys_of(en_file))
        orphans = sorted(tids_of(html) - dict_keys)
        if orphans:
            errors.append(
                f"[orphan] {html_name}: {len(orphans)} t-id(s) not in "
                f"{surface}.en.js: {orphans}"
            )

    # (c) en -> ja/zh co-change since merge base
    for surface in ki.SURFACES:
        base_keys = git_keys_at_base(f"docs/i18n/{surface}.en.js")
        if base_keys is None:
            continue  # no git base available — (a) already enforces parity now
        now_en = set(ki.keys_of(ki.surface_file(surface, "en")))
        added = now_en - base_keys
        for lang in ("ja", "zh"):
            f = ki.surface_file(surface, lang)
            if not f.exists():
                continue
            now_lang = set(ki.keys_of(f))
            untranslated = sorted(added - now_lang)
            if untranslated:
                msg = (
                    f"[co-change] {surface}.{lang}.js missing newly-added en "
                    f"key(s): {untranslated}"
                )
                (errors if strict_cochange else warnings).append(msg)

    # (d) version single source
    vjson = DOCS / "version.json"
    declared = None
    if not vjson.exists():
        errors.append("[version] docs/version.json missing")
    else:
        try:
            declared = json.loads(vjson.read_text(encoding="utf-8")).get("version")
        except (ValueError, OSError) as exc:
            errors.append(f"[version] docs/version.json unparseable: {exc}")
        if not declared:
            errors.append("[version] docs/version.json has no 'version' field")

    report_tex = REPO_ROOT / "report" / "en" / "main.tex"
    if declared and report_tex.exists():
        m = DATE_VERSION_RE.search(report_tex.read_text(encoding="utf-8"))
        if m and m.group(1) != declared:
            errors.append(
                f"[version] version.json {declared!r} != report \\date "
                f"{m.group(1)!r}"
            )

    # report PDF copies (P6) must stay byte-identical to the report/ source.
    report_dst = DOCS / "assets" / "report"
    if report_dst.exists():
        for lang in ("en", "ja", "zh"):
            src = REPO_ROOT / "report" / lang / "main.pdf"
            dst = report_dst / f"{lang}.pdf"
            if dst.exists():
                if not src.exists():
                    errors.append(f"[report-pdf] source report/{lang}/main.pdf missing")
                elif src.read_bytes() != dst.read_bytes():
                    errors.append(
                        f"[report-pdf] docs/assets/report/{lang}.pdf is stale; "
                        f"re-run scripts/docs/sync_report_pdf.sh"
                    )

    index_html = DOCS / "index.html"
    if index_html.exists():
        # footer version must be injected (version.js), not a hard-coded literal.
        footer_region = index_html.read_text(encoding="utf-8")
        m = re.search(r"<footer>.*?</footer>", footer_region, re.S)
        if m and VERSION_FOOTER_RE.search(m.group(0)):
            errors.append(
                "[version] index.html footer hard-codes a version literal; "
                "use #ari-version + version.js instead"
            )

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument(
        "--strict-cochange", action="store_true",
        help="treat co-change findings as errors (default: warnings)",
    )
    args = ap.parse_args(argv)

    errors, warnings = check(args.strict_cochange)

    if args.json:
        print(json.dumps({"errors": errors, "warnings": warnings},
                         ensure_ascii=False, indent=2))
    else:
        for w in warnings:
            print(f"WARN  {w}")
        for e in errors:
            print(f"ERROR {e}")
        if not errors and not warnings:
            print("[check_site_i18n] OK — surface parity, no orphan t-ids, "
                  "version single-sourced")
        else:
            print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
