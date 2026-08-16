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
  (d) public version pin    — the *published* pin is one register: docs/version.json
                              is the single source, and the three README badges
                              and each report ``\\date{vX.Y.Z, ...}`` must repeat
                              it.  That pin is NOT required to equal the packaged
                              version in ``ari-core/pyproject.toml``: a
                              package-only bump (a contract-preserving release
                              with nothing user-visible to announce) leaves the
                              public pin untouched by design, so the pin may LAG
                              the package.  It must never LEAD it — that would
                              advertise a version that was never packaged.  See
                              docs/about/release_policy.md, "Release checklist"
                              step 2.  index.html must still carry no hard-coded
                              ``vX.Y.Z`` footer literal (version.js injects it
                              into #ari-version at runtime).

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
BADGE_VERSION_RE = re.compile(r"badge/version-(v\d+\.\d+\.\d+)")  # shields.io badge
PYPROJECT_VERSION_RE = re.compile(r'(?m)^version\s*=\s*"([^"]+)"')
SEMVER_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)$")
#: The PACKAGE version may carry a pre-release suffix that the PIN never does.
#: `docs/about/release_policy.md` says ARI follows SemVer 2.0, and PEP 440 lets
#: setuptools read `0.10.0rc1` / `0.10.0.dev0` -- so requiring a bare X.Y.Z from
#: pyproject.toml would fail this gate on any release candidate. Match the
#: release triple and keep whatever follows, so the ordering rule can still be
#: evaluated: a pre-release sorts BEFORE its own final release.
RELEASE_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)(?P<rest>.*)$")

# Public-pin restatements: files that must repeat docs/version.json verbatim.
REPORT_LANGS = ("en", "ja", "zh")
README_FILES = ("README.md", "README.ja.md", "README.zh.md")


def packaged_version() -> str | None:
    """``[project].version`` from ``ari-core/pyproject.toml`` — the PACKAGE version.

    The same single source ``scripts/snapshot_contracts.py`` derives from; read
    here rather than imported so this gate stays stdlib-only and never imports
    ``ari``.  Returns None when the file is absent/unreadable (nothing to check).
    """
    pyproject = REPO_ROOT / "ari-core" / "pyproject.toml"
    if not pyproject.exists():
        return None
    text = pyproject.read_text(encoding="utf-8")
    try:
        import tomllib

        return tomllib.loads(text)["project"]["version"]
    except Exception:
        m = PYPROJECT_VERSION_RE.search(text)
        return m.group(1) if m else None


def semver(value: str) -> tuple[int, int, int] | None:
    """``v0.9.1``/``0.9.1`` -> ``(0, 9, 1)``; None when it is not an X.Y.Z.

    Strict on purpose, and used for the PIN only: the badge and ``\\date``
    regexes already require a bare ``vX.Y.Z``, so a pin that does not parse here
    could not have matched them either.
    """
    m = SEMVER_RE.match(value.strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def release_order(value: str) -> tuple[int, int, int, int] | None:
    """A comparable key that tolerates a pre-release suffix; None if unparseable.

    The fourth element is the pre-release flag, and it is what makes the
    comparison right rather than merely permissive: ``0.10.0rc1`` -> ``(0, 10,
    0, 0)`` sorts BEFORE ``v0.10.0`` -> ``(0, 10, 0, 1)``. A pin of ``v0.10.0``
    against a packaged ``0.10.0rc1`` therefore still reads as the pin LEADING
    the package, which it does -- the final release has not been packaged yet.
    """
    m = RELEASE_RE.match(value.strip())
    if m is None:
        return None
    rest = m.group("rest").strip()
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if rest else 1)


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


def check_version_pin(errors: list[str], warnings: list[str]) -> None:
    """The public version pin, and its relationship to the packaged version.

    Split out of :func:`check` so it can be exercised directly against a
    scratch tree -- see ``scripts/tests/test_check_site_i18n_version.py``.
    Appends to the caller's lists rather than returning, matching how the
    rest of :func:`check` accumulates.
    """
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

    # every public restatement of the pin must repeat docs/version.json.
    for lang in REPORT_LANGS:
        report_tex = REPO_ROOT / "report" / lang / "main.tex"
        if declared and report_tex.exists():
            m = DATE_VERSION_RE.search(report_tex.read_text(encoding="utf-8"))
            if m is None:
                errors.append(
                    f"[version] report/{lang}/main.tex carries no "
                    f"\\date{{vX.Y.Z, ...}} to compare with version.json"
                )
            elif m.group(1) != declared:
                errors.append(
                    f"[version] version.json {declared!r} != report/{lang} "
                    f"\\date {m.group(1)!r}"
                )

    for readme in README_FILES:
        path = REPO_ROOT / readme
        if declared and path.exists():
            m = BADGE_VERSION_RE.search(path.read_text(encoding="utf-8"))
            if m is None:
                errors.append(
                    f"[version] {readme} carries no shields.io "
                    f"version-vX.Y.Z badge to compare with version.json"
                )
            elif m.group(1) != declared:
                errors.append(
                    f"[version] version.json {declared!r} != {readme} badge "
                    f"{m.group(1)!r}"
                )

    # The published pin and the packaged version are two registers, and the rule
    # between them is ordering, not equality: the pin MAY lag the package (a
    # package-only bump ships no public-surface change) but must never lead it.
    packaged = packaged_version()
    if declared and packaged:
        pin, pkg = release_order(declared), release_order(packaged)
        if semver(declared) is None:
            errors.append(
                f"[version] docs/version.json {declared!r} is not a vX.Y.Z version"
            )
        elif pkg is None:
            # The package version is not this gate's to police -- setuptools is
            # the authority on what it accepts, and a shape we cannot parse means
            # the ordering rule cannot be EVALUATED, not that it was violated.
            warnings.append(
                f"[version] ari-core/pyproject.toml version {packaged!r} is not "
                f"an X.Y.Z(suffix) version; pin ordering not checked"
            )
        elif pin is not None and pin > pkg:
            errors.append(
                f"[version] public pin {declared!r} leads ari-core/pyproject.toml "
                f"{packaged!r}; the site would advertise a version that was never "
                f"packaged (the pin may lag a package-only bump, never lead it)"
            )



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

    check_version_pin(errors, warnings)

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
                  "public version pin agrees across docs/version.json, the "
                  "README badges and report/{en,ja,zh} \\date, and does not "
                  "lead ari-core/pyproject.toml")
        else:
            print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
