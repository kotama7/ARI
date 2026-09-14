#!/usr/bin/env python3
"""Check that intra-docs links and HTML hrefs resolve to real files.

Gate: docs/最終統合計画書.md §4 items 1-2
  1. every relative / ``docs/``-prefixed link in a ``.md`` resolves on disk;
  2. every local ``.md``/media ``href``/``src`` in index.html & docs.html exists.

External links (http/https/mailto) are ignored.  Fragments used to be ignored
too -- ``_clean_target`` dropped everything after ``#`` -- so a link whose FILE
existed passed no matter what heading it claimed, and ~650 in-page ``#frag``
links were never looked at at all.  Both are checked now (item 3):

  3. every ``#fragment`` resolves to a heading in the target document, using the
     slug VitePress would generate for it.

The slug rule is not guessed.  ``slugify`` below was fitted against the built
site: 1376/1376 distinct rendered headings in ``docs/.vitepress/dist`` produce
their exact ``id=`` attribute.  It matters that it is exact in both directions --
a rule that is too lax silently passes broken anchors, and one that is too
strict fails good ones and gets switched off.

Exit 1 if any link is broken, 0 otherwise.  ``--json`` for machine-readable
output.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"

MD_LINK = re.compile(r"\]\(\s*(<[^>]+>|[^)\s]+)")
HTML_REF = re.compile(r'(?:href|src)\s*=\s*"([^"]+)"')

EXTERNAL = ("http://", "https://", "mailto:", "tel:", "//", "data:")
DEPLOYMENT_ROOTS = {"/ARI/"}


def _split_target(raw: str) -> tuple[str | None, str | None]:
    """``(path, fragment)`` for a link, either half None when absent/skippable.

    ``path`` is None for an in-page ``#frag`` link -- which is a link to check,
    not a link to skip, so the fragment still comes back.
    """
    t = raw.strip()
    if t.startswith("<") and t.endswith(">"):
        t = t[1:-1].strip()
    if t.startswith(EXTERNAL) or "://" in t or t in DEPLOYMENT_ROOTS:
        return None, None
    if t == "":
        return None, None
    # drop a markdown link title: (path "title")
    if " " in t:
        t = t.split(" ", 1)[0]
    path, _, frag = t.partition("#")
    return (path or None), (frag or None)


def _clean_target(raw: str) -> str | None:
    """Back-compat shim: the on-disk half only."""
    return _split_target(raw)[0]


# ── VitePress heading slugs ──────────────────────────────────────────────────
# Fitted against docs/.vitepress/dist: every one of the 1376 distinct rendered
# headings there slugifies to its exact `id=`. The three rules that are easy to
# get wrong, all confirmed from that corpus:
#   * ASCII punctuation becomes '-', it is not deleted -- `exit_code=127` is
#     `exit-code-127`, and `_` is punctuation here (`ARI_CHECKPOINT_DIR` ->
#     `ari-checkpoint-dir`), so an anchor written with an underscore is broken.
#   * non-ASCII survives -- `Skills と core` -> `skills-と-core`.
#   * a slug that would start with a digit is prefixed `_`, since an HTML id
#     cannot -- `## 1. Environment` -> `_1-environment`.
SLUG_PUNCT = re.compile(r"[!-/:-@\[-`{-~]")
SLUG_COMBINING = re.compile(r"[̀-ͯ]")
MD_LINK_TEXT = re.compile(r"\[([^\]]*)\]\([^)]*\)")
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")


def slugify(text: str) -> str:
    s = unicodedata.normalize("NFKD", text)
    s = SLUG_COMBINING.sub("", s)
    s = SLUG_PUNCT.sub("-", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-").lower()
    return "_" + s if s[:1].isdigit() else s


_HEADINGS_CACHE: dict[Path, set[str]] = {}


def heading_slugs(path: Path) -> set[str]:
    """Anchors a markdown file offers, as VitePress would emit them.

    Fence-aware, because a ``#`` comment inside a shell block is not a heading.
    Repeats get the ``-1`` / ``-2`` suffix VitePress appends (two `##
    Configuration` headings give `configuration` and `configuration-1`).
    """
    if path in _HEADINGS_CACHE:
        return _HEADINGS_CACHE[path]
    out: set[str] = set()
    seen: dict[str, int] = {}
    fence: str | None = None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        _HEADINGS_CACHE[path] = out
        return out
    for line in lines:
        f = FENCE_RE.match(line)
        if f:
            if fence is None:
                fence = f.group(1)[0]
            elif line.strip()[:1] == fence:
                fence = None
            continue
        if fence is not None:
            continue
        m = HEADING_RE.match(line)
        if not m:
            continue
        base = slugify(MD_LINK_TEXT.sub(r"\1", m.group(2)))
        if not base:
            continue
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.add(base if n == 0 else f"{base}-{n}")
    _HEADINGS_CACHE[path] = out
    return out


def _anchor_source(resolved: Path) -> Path | None:
    """The markdown whose headings a fragment should be checked against."""
    if resolved.suffix == ".md":
        return resolved if resolved.is_file() else None
    if resolved.suffix:            # .html / media -- not ours to slugify
        return None
    for cand in (resolved.with_suffix(".md"), resolved / "index.md"):
        if cand.is_file():
            return cand
    return None


def _report_name(path: Path) -> str:
    """Repo-relative name for a finding, or the plain path when outside it.

    ``check_markdown`` needs this for every file it scans, not only for the
    files it reports on, so it must not raise when ``DOCS`` has been pointed
    somewhere outside ``REPO_ROOT``.
    """
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve(target: str, from_file: Path) -> Path:
    if target.startswith("/"):
        return REPO_ROOT / target.lstrip("/")
    if target.startswith("docs/"):
        return REPO_ROOT / target
    return (from_file.parent / target).resolve()


def _exists_cleanurl(p: Path) -> bool:
    """Resolve like a static host + VitePress clean URLs.

    A landing link into the VitePress docs is extensionless (``docs/concepts/
    PHILOSOPHY``); it resolves at deploy to the built ``.html`` and corresponds
    to a markdown source. Accept the link if the path exists OR its VitePress
    source / built page does."""
    if p.exists():
        return True
    # VitePress copies ``docs/public/**`` to the deployment root. A source link
    # such as ``report/en.pdf`` therefore resolves even though the authored
    # file lives at ``docs/public/report/en.pdf``.
    try:
        public_target = DOCS / "public" / p.relative_to(DOCS)
    except ValueError:
        public_target = None
    if public_target is not None and public_target.exists():
        return True
    if p.suffix == "":
        if p.with_suffix(".md").exists():
            return True
        if (p / "index.md").exists():
            return True
        if p.with_suffix(".html").exists():
            return True
    return False


MARKDOWN_EXCLUDE_DIRS = ("node_modules", ".vitepress")


def _markdown_files() -> list[Path]:
    out = []
    for md in sorted(DOCS.rglob("*.md")):
        rel_parts = md.relative_to(DOCS).parts[:-1]
        if any(seg in rel_parts for seg in MARKDOWN_EXCLUDE_DIRS):
            continue
        out.append(md)
    return out


def check_markdown(findings: list) -> None:
    for md in _markdown_files():
        text = md.read_text(encoding="utf-8")
        rel = _report_name(md)
        for m in MD_LINK.finditer(text):
            target, frag = _split_target(m.group(1))
            if target is None and frag is None:
                continue
            if target is None:
                # in-page anchor: check it against this file's own headings
                if frag not in heading_slugs(md):
                    findings.append({"file": rel, "target": f"#{frag}",
                                     "kind": "anchor"})
                continue
            resolved = _resolve(target, md)
            if not _exists_cleanurl(resolved):
                findings.append({"file": rel, "target": target, "kind": "file"})
                continue
            if frag is None:
                continue
            source = _anchor_source(resolved)
            if source is not None and frag not in heading_slugs(source):
                findings.append({"file": rel, "target": f"{target}#{frag}",
                                 "kind": "anchor"})


# docs/report/ holds the imported report HTML build (P8); its dense intra-report
# relative links are governed by the report build, not this gate. node_modules/
# and .vitepress/ (dist + cache) are VitePress build/dependency artifacts, not
# hand-authored source HTML.
HTML_EXCLUDE_DIRS = ("report", "node_modules", ".vitepress")


def _html_files() -> list[Path]:
    out = []
    for html in sorted(DOCS.rglob("*.html")):
        rel = html.relative_to(DOCS).as_posix()
        if any(seg in rel.split("/")[:-1] for seg in HTML_EXCLUDE_DIRS):
            continue
        out.append(html)
    return out


def check_html(findings: list) -> None:
    for html in _html_files():
        text = html.read_text(encoding="utf-8")
        rel = html.relative_to(REPO_ROOT).as_posix()
        for m in HTML_REF.finditer(text):
            target = _clean_target(m.group(1))
            if target is None:
                continue
            resolved = _resolve(target, html)
            if not _exists_cleanurl(resolved):
                findings.append({"file": rel, "target": target, "kind": "file"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--md-only", action="store_true", help="skip HTML href checks")
    parser.add_argument("--html-only", action="store_true", help="skip markdown link checks")
    args = parser.parse_args(argv)

    findings: list[dict] = []
    if not args.html_only:
        check_markdown(findings)
    if not args.md_only:
        check_html(findings)

    files = [f for f in findings if f.get("kind") != "anchor"]
    anchors = [f for f in findings if f.get("kind") == "anchor"]

    if args.json:
        print(json.dumps({"broken": findings}, ensure_ascii=False, indent=2))
    else:
        for f in files:
            print(f"{f['file']}: broken link -> {f['target']}")
        for f in anchors:
            print(f"{f['file']}: no such heading -> {f['target']}")
        print(f"\n{len(files)} broken link(s), {len(anchors)} broken anchor(s)")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
