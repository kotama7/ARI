#!/usr/bin/env python3
"""Shared infrastructure for the ``scripts/quality/`` source-code checker family.

This is the first artifact of refactoring subtask 025 and the common substrate
the sibling quality checkers (026-031 and the aggregator 058) reuse, per
``docs/refactoring/009_quality_scripts_plan.md`` §8. Keeping the JSON schema,
allowlist loader, Markdown writer, and ``--base-ref`` diff resolver in one place
is the single up-front de-duplication the plan calls for.

Provided:

* ``Finding`` -- the stable finding record (the §3 JSON schema of 009).
* ``emit_json`` -- serialize a checker run into the §3 envelope.
* ``render_markdown_table`` -- a plain GitHub-flavoured Markdown table.
* ``load_allowlist`` -- read a ``<name>.allow.yaml`` baseline (missing -> empty).
* ``changed_files`` -- a ``--base-ref`` git-diff resolver mirroring
  ``scripts/docs/check_ref_coupling.py`` (``merge-base`` + ``diff --name-only``).
* ``write_output`` -- stdout-or-file writer.

Determinism (design principle P2): stdlib + PyYAML only, no LLM, no network.
This mirrors the ``scripts/docs/`` house style (PyYAML the sole non-stdlib dep).
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    sys.stderr.write(
        "scripts/quality/_common: PyYAML is required (pip install pyyaml).\n"
    )
    raise SystemExit(2)

# scripts/quality/_common.py -> parents[2] == repo root (one deeper than the
# top-level scripts/ checkers, which use parents[1]).
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Finding:
    """One checker finding, matching the §3 JSON schema of 009.

    ``allowlisted`` is ``True`` when the finding is fully covered by the frozen
    baseline (a "known" offender that never fails ``--fail-on-regression``);
    ``False`` marks net-new debt.
    """

    id: str
    severity: str
    file: str
    line: int
    kind: str
    message: str
    allowlisted: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "kind": self.kind,
            "message": self.message,
            "allowlisted": self.allowlisted,
        }


def load_yaml(path: Path) -> dict[str, Any]:
    """Parse a YAML mapping; a missing file yields an empty mapping."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        sys.stderr.write(f"quality/_common: {path} is not a YAML mapping.\n")
        raise SystemExit(2)
    return data


def load_allowlist(path: Path) -> dict[str, Any]:
    """Load a ``<name>.allow.yaml`` baseline; a missing file -> empty allowlist."""
    return load_yaml(path)


def emit_json(
    checker: str,
    version: int,
    target: Any,
    summary: dict[str, Any],
    findings: list[Finding],
) -> str:
    """Serialize a run into the stable §3 envelope the aggregator consumes."""
    return json.dumps(
        {
            "checker": checker,
            "version": version,
            "target": target,
            "summary": summary,
            "findings": [f.as_dict() for f in findings],
        },
        ensure_ascii=False,
        indent=2,
    )


def render_markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a GitHub-flavoured Markdown table (padded for readability)."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt(cells: list[Any]) -> str:
        return (
            "| "
            + " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells))
            + " |"
        )

    sep = "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |"
    return "\n".join([fmt(headers), sep, *[fmt(r) for r in rows]])


def changed_files(base_ref: str) -> list[str] | None:
    """Repo-relative paths changed vs ``merge-base(base_ref, HEAD)``.

    Returns ``None`` when the base ref cannot be resolved so advisory callers can
    fall back to a full scan -- mirroring ``check_ref_coupling.py``'s tolerant
    base handling (a movable ``origin/<branch>`` is never trusted blindly).
    """
    try:
        base = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "merge-base", base_ref, "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "diff", "--name-only", base, "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return [ln for ln in out.splitlines() if ln.strip()]


def write_output(text: str, output: str | None) -> None:
    """Write ``text`` to ``output`` (a file path) or stdout when ``output`` is None."""
    if output:
        Path(output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def dump_yaml_with_header(path: Path, header_lines: list[str], body: dict[str, Any]) -> None:
    """Write a YAML file with a leading comment header (PyYAML drops comments)."""
    header = "\n".join(header_lines)
    dumped = yaml.safe_dump(body, sort_keys=False, allow_unicode=True)
    path.write_text(header + "\n" + dumped, encoding="utf-8")
