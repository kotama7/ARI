#!/usr/bin/env python3
"""Trunk-state docs<->source staleness checker (subtask 027).

WHAT THIS ADDS (and, deliberately, what it does NOT).
=====================================================
Docs under ``docs/`` declare, in YAML front-matter, the source files they
document plus a ``last_verified`` date::

    ---
    sources:
      - path: ari-core/ari/orchestrator
        role: implementation
    last_verified: 2026-05-26
    ---

Two gates already cover the docs<->source relationship, in both directions, and
this checker MUST NOT re-implement either of them (see
``docs/refactoring/009_quality_scripts_plan.md`` §5.3 and subtask 027 §7.1):

  * ``scripts/docs/check_doc_sources.py`` -- FORWARD: every declared
    ``sources[].path`` resolves on disk; ``role`` vocabulary; ``--require-all``
    coverage. (Hard gate in ``docs-sync.yml``.)
  * ``scripts/docs/check_ref_coupling.py`` -- REVERSE, PR-DIFF: a source changed
    *on the current branch* must bump the referencing doc's ``last_verified``
    (advisory in ``docs-change-coupling.yml``).

The ONE dimension neither gate covers is **trunk-state staleness**: a source
whose newest commit *already on ``main``* is more recent than the referencing
doc's ``last_verified`` -- i.e. drift introduced by some earlier, already-merged
PR that forgot to bump the date. ``check_ref_coupling.py`` is a merge-base diff
gate and cannot see that (it only fires on same-PR co-changes);
``check_doc_sources.py`` only checks path existence, not recency. This script
fills exactly that gap and nothing else.

To avoid forking front-matter parsing, it REUSES ``parse_doc`` /
``is_translation`` from ``scripts/docs/check_ref_coupling.py`` rather than
re-deriving them.

Design refs: ``docs/refactoring/subtasks/027_add_docs_source_sync_checker_script.md``
§7.2 (Outcome A), ``docs/refactoring/009_quality_scripts_plan.md`` §5.3.

Determinism (ARI design principle P2): stdlib + PyYAML only, no LLM, no network;
findings are sorted, so two runs on the same tree are byte-identical. Git is
consulted read-only and fails *open* (advisory) when history is unavailable.

Exit convention (matches the ``scripts/docs/`` family):
  * ``0`` -- no net-new staleness (allowlisted findings do not fail) or
    ``--warning-only``;
  * ``1`` -- staleness beyond the frozen baseline when not ``--warning-only``;
  * ``2`` -- environment error (missing PyYAML).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    sys.stderr.write(
        "check_docs_source_sync: PyYAML is required (pip install pyyaml).\n"
    )
    raise SystemExit(2)

# Top-level ``scripts/`` checker -> parents[1] is the repo root (like
# ``scripts/readme_sync.py``), NOT the ``scripts/docs/`` parents[2] convention.
REPO_ROOT = Path(__file__).resolve().parents[1]

# Reuse the reverse-direction gate's front-matter parser instead of forking it
# (subtask 027 §7.2: "reuse, do not fork"). check_ref_coupling itself roots at
# the same repo root, so this is a pure-function import with no side effects.
_DOCS_SCRIPTS = REPO_ROOT / "scripts" / "docs"
if str(_DOCS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_DOCS_SCRIPTS))
from check_ref_coupling import is_translation, parse_doc  # noqa: E402

DEFAULT_ALLOW = REPO_ROOT / "scripts" / "check_docs_source_sync.allow.yaml"


def _git_last_commit_date(repo_root: Path, source: str) -> _dt.date | None:
    """Committer date (YYYY-MM-DD) of the newest commit touching ``source``.

    For a directory source this is the newest commit under it (git semantics).
    Returns ``None`` when git or the history is unavailable, or the path has no
    commit -- the caller then skips the pair (fail open, advisory).
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "log", "-1", "--format=%cs", "--", source],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    if not out:
        return None
    try:
        return _dt.date.fromisoformat(out)
    except ValueError:
        return None


def english_masters(docs_dir: Path, repo_root: Path) -> list[Path]:
    """Every English master doc (ja/zh translations tracked elsewhere)."""
    out: list[Path] = []
    if not docs_dir.exists():
        return out
    for p in sorted(docs_dir.rglob("*.md")):
        rel = p.relative_to(repo_root).as_posix()
        if is_translation(rel):
            continue
        out.append(p)
    return out


def compute_findings(repo_root: Path, docs_dir: Path | None = None) -> list[dict]:
    """Return sorted trunk-state-staleness findings for the given tree.

    A finding is emitted per (doc, source) pair whose source's newest commit
    date is strictly after the doc's ``last_verified``. Docs lacking ``sources``
    or ``last_verified`` are skipped (that is the job of other gates).
    """
    docs_dir = docs_dir if docs_dir is not None else repo_root / "docs"
    findings: list[dict] = []
    for doc in english_masters(docs_dir, repo_root):
        docrel = doc.relative_to(repo_root).as_posix()
        sources, last_verified = parse_doc(doc.read_text(encoding="utf-8"))
        if not sources or last_verified is None:
            continue
        for source in sources:
            sdate = _git_last_commit_date(repo_root, source)
            if sdate is None:
                continue  # no history for this path -> fail open, skip
            if sdate > last_verified:
                findings.append({
                    "doc": docrel,
                    "source": source,
                    "last_verified": last_verified.isoformat(),
                    "source_last_commit": sdate.isoformat(),
                })
    findings.sort(key=lambda f: (f["doc"], f["source"]))
    return findings


def load_allowlist(path: Path | str | None) -> set[tuple[str, str]]:
    """Load the frozen (doc, source) baseline. Missing file -> empty set."""
    if not path:
        return set()
    p = Path(path)
    if not p.exists():
        return set()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    pairs: set[tuple[str, str]] = set()
    if isinstance(data, dict):
        for entry in data.get("known-offenders") or []:
            if isinstance(entry, dict) and "doc" in entry and "source" in entry:
                pairs.add((str(entry["doc"]), str(entry["source"])))
    return pairs


def partition_findings(
    findings: list[dict], allow: set[tuple[str, str]]
) -> tuple[list[dict], list[dict]]:
    """Split findings into (new, known) by the (doc, source) allowlist."""
    new = [f for f in findings if (f["doc"], f["source"]) not in allow]
    known = [f for f in findings if (f["doc"], f["source"]) in allow]
    return new, known


def _render_json(findings: list[dict], allow: set[tuple[str, str]]) -> str:
    new, known = partition_findings(findings, allow)
    return json.dumps({
        "checker": "check_docs_source_sync",
        "version": 1,
        "target": "docs",
        "summary": {"total": len(findings), "new": len(new), "known": len(known)},
        "findings": [
            {**f, "allowlisted": (f["doc"], f["source"]) in allow}
            for f in findings
        ],
    }, ensure_ascii=False, indent=2)


def _render_text(findings: list[dict], allow: set[tuple[str, str]]) -> str:
    new, known = partition_findings(findings, allow)
    lines: list[str] = []
    if new:
        lines.append(
            f"[check_docs_source_sync] {len(new)} doc<->source pair(s) stale "
            f"beyond baseline (source newer than last_verified):"
        )
        for f in new:
            lines.append(
                f"  - {f['doc']} (last_verified={f['last_verified']})"
                f" <- {f['source']} last committed {f['source_last_commit']}"
            )
    else:
        lines.append(
            "[check_docs_source_sync] OK -- no net-new trunk-state staleness "
            f"({len(known)} known/allowlisted)"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument(
        "--warning-only", action="store_true",
        help="advisory: report findings but always exit 0 (default posture)",
    )
    ap.add_argument(
        "--allow", default=str(DEFAULT_ALLOW),
        help="frozen (doc, source) baseline YAML (default: sibling .allow.yaml)",
    )
    ap.add_argument("--output", help="write the report to a file instead of stdout")
    args = ap.parse_args(argv)

    findings = compute_findings(REPO_ROOT)
    allow = load_allowlist(args.allow)
    new, _known = partition_findings(findings, allow)

    report = _render_json(findings, allow) if args.json else _render_text(findings, allow)
    if args.output:
        Path(args.output).write_text(report + "\n", encoding="utf-8")
    else:
        print(report)

    if args.warning_only:
        return 0
    return 1 if new else 0


if __name__ == "__main__":
    raise SystemExit(main())
