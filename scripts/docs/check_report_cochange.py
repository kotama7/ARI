#!/usr/bin/env python3
"""Diff gate: report/{en,ja,zh} paired files must change together in a PR.

``report/`` carries three hand-maintained language editions (en master, ja, zh).
``report/CLAUDE.md`` §3 makes the policy explicit: edit ``en/`` first, then
mirror the edit into ``ja/`` and ``zh/`` *in the same PR*.  Gate 6
(``report/scripts/check_i18n.py``) enforces that the result is structurally
parallel, but it cannot tell that one language was simply left untouched.  This
diff-based gate closes that gap: for every language-paired file changed on the
branch, it requires the other two languages' counterpart to change too.

Paired files are the per-language authored sources:
  * ``report/<lang>/chapters/<name>.tex``
  * ``report/<lang>/strings.tex``
  * ``report/<lang>/main.tex``

Generated artifacts (``main.pdf``, ``main-blx.bib``) and shared, single-copy
files (``report/shared/**``) are NOT paired and never trigger this gate.

Fails (exit 1) on any unpaired change.  Changes are taken from ``git diff`` vs a
base ref's merge-base (``--base-ref``, default ``origin/main``), or from an
explicit newline-delimited list (``--files-from FILE``/``-``) for testing.
Pure stdlib, no dependencies, no network/LLM.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LANGS = ("en", "ja", "zh")

# report/<lang>/<key> where <key> is a per-language authored source.
PAIRED_RE = re.compile(
    r"^report/(?P<lang>en|ja|zh)/(?P<key>chapters/[^/]+\.tex|strings\.tex|main\.tex)$"
)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True, text=True, check=True,
    ).stdout


def changed_from_git(base_ref: str) -> list[str] | None:
    try:
        base = git("merge-base", base_ref, "HEAD").strip()
    except subprocess.CalledProcessError:
        return None
    return [l for l in git("diff", "--name-only", base, "HEAD").splitlines() if l.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-ref", default="origin/main",
                    help="base git ref to diff against (default: origin/main)")
    ap.add_argument("--files-from",
                    help="read changed paths from FILE (or '-' for stdin) instead of git")
    args = ap.parse_args(argv)

    if args.files_from:
        text = sys.stdin.read() if args.files_from == "-" else Path(args.files_from).read_text()
        changed = [l.strip() for l in text.splitlines() if l.strip()]
    else:
        changed = changed_from_git(args.base_ref)
        if changed is None:
            # Hard gate: fail CLOSED. Returning 0 here would turn the only
            # blocking step in docs-change-coupling.yml into a silent no-op
            # whenever base-ref resolution hiccups (shallow checkout, transient
            # git error, unreachable ref).
            print(f"[check_report_cochange] FATAL: cannot resolve base ref "
                  f"{args.base_ref!r}", file=sys.stderr)
            return 1

    changed_set = set(changed)
    # key -> set of langs that changed it
    keys: dict[str, set[str]] = {}
    for path in changed:
        m = PAIRED_RE.match(path)
        if m:
            keys.setdefault(m.group("key"), set()).add(m.group("lang"))

    errors: list[str] = []
    for key in sorted(keys):
        present = keys[key]
        missing = [lang for lang in LANGS
                   if f"report/{lang}/{key}" not in changed_set]
        if missing:
            errors.append(
                f"report/.../{key}: changed in {sorted(present)} "
                f"but NOT in {missing} — mirror the edit in the same PR "
                f"(report/CLAUDE.md §3)"
            )

    if errors:
        print(f"[check_report_cochange] {len(errors)} unpaired change(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    if keys:
        print(f"[check_report_cochange] OK — {len(keys)} paired file(s) "
              f"changed in all three languages")
    else:
        print("[check_report_cochange] OK — no language-paired report files changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
