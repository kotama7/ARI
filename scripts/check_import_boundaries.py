#!/usr/bin/env python3
"""Enforce the ARI module-layering contract as an AST import-graph gate.

ARI declares, verbatim in ``ari-core/ari/public/__init__.py``, that *"Skills
must only import from ``ari.public.*``"*.  That contract is stated but, until
this script, unenforced.  This checker parses every skill and core module with
the stdlib :mod:`ast` and reports the two boundary rules:

  * **B1** — every ``ari-skill-*/src/**`` module may import from ``ari-core``
    only via ``ari.public.*`` / ``ari.protocols.*``; any other ``ari.<internal>``
    segment crossing the skill->core seam is a violation.
  * **B2** — ``ari-core/ari/**`` must not import any ``ari_skill_*`` package,
    with the single sanctioned exception of ``ari_skill_memory`` (the first
    core->skill edge, editable-installed by ``setup.sh``).

It ships in **warning mode first**: findings are reported but the default and
``--warning-only`` postures exit 0, and a frozen allowlist keeps the known
historical debt out of a future ratchet (``--fail-on-regression``).  This script
only *reads*; it never edits code and never widens ``ari.public.*`` (that is the
B1 ADAPT runtime work, later subtasks).

Design: docs/refactoring/003_dependency_boundary_report.md §3 (B1) / §4 (B2) /
§15 (enforcement roadmap); docs/refactoring/009_quality_scripts_plan.md §5.2
(common script contract, warning-mode-first rollout).

AST, not grep: guarded (``try/except ImportError``) and in-function imports are
the norm on the skill->core seam, and comments (e.g. the ``settingsConstants.ts``
``ari_skill_memory`` doc comment) must not be flagged.  ``ast.walk`` sees every
real import at any depth and never sees comments or strings.

Exit convention (matches ``scripts/docs/check_doc_sources.py``): ``0`` = clean,
default/``--warning-only`` posture, or ``--fail-on-regression`` with no net-new
debt; ``1`` = net-new findings under ``--fail-on-regression``; ``2`` =
usage/environment error (e.g. missing PyYAML).
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    sys.stderr.write(
        "check_import_boundaries: PyYAML is required (pip install pyyaml).\n"
    )
    raise SystemExit(2)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "scripts" / "quality" / "check_import_boundaries.yaml"
DEFAULT_ALLOW = REPO_ROOT / "scripts" / "quality" / "check_import_boundaries.allow.yaml"

CHECKER_NAME = "check_import_boundaries"
SCHEMA_VERSION = 1

# Config defaults -- every key is overridable via the YAML config so that the
# B1 ADAPT subtask can widen ``ari.public.*`` (e.g. add ``ari.public.lineage``)
# without touching this script.
DEFAULT_RULES: dict = {
    # B1 -- the only import roots a skill may use to reach core.
    "allowed_skill_import_roots": ["ari.public", "ari.protocols"],
    # B2 -- the sole sanctioned core->skill package(s).
    "sanctioned_core_to_skill": ["ari_skill_memory"],
    # Off by default: flag a skill importing another skill (no such edge today).
    "flag_cross_skill_imports": False,
    # Off by default (None): once B2 ADAPT centralizes the memory edge, set this
    # to e.g. "ari-core/ari/memory" to flag ari_skill_memory imports outside it.
    "restrict_memory_edge_to": None,
    # Off by default: flag ari-core/ari/cli/** importing ari.viz.* (§7.5).
    "forbid_core_to_viz_from_cli": False,
}


@dataclass(frozen=True)
class Edge:
    """A single import statement resolved to its imported module."""

    file: str  # posix path relative to the scan target
    line: int
    module: str  # ``node.module`` for ``from`` imports; alias name for ``import``
    kind: str  # "import" | "from"


@dataclass
class Finding:
    rule: str  # "B1" | "B2" | "CORE_VIZ"
    package: str
    file: str
    line: int
    imported_module: str
    severity: str
    message: str
    allowlisted: bool

    @property
    def id(self) -> str:
        # Stable identity keyed on <scan-relative file>::<imported module>.
        # For the default full-repo target this is the repo-relative id used by
        # the seeded allowlist; occurrences on multiple lines share one id.
        return f"{self.file}::{self.imported_module}"


# -- discovery / parsing ----------------------------------------------------


def collect_imports(abs_path: Path, rel_path: str) -> list[Edge]:
    """Walk every ``ast.Import`` / ``ast.ImportFrom`` at all depths.

    Relative (``level > 0``) imports are intra-package and never a cross-seam
    violation, so they are skipped.  Syntax/decoding errors yield no edges.
    """
    try:
        tree = ast.parse(abs_path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, ValueError):  # pragma: no cover
        return []
    edges: list[Edge] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                edges.append(Edge(rel_path, node.lineno, alias.name, "import"))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # intra-package relative import
            if node.module:
                edges.append(Edge(rel_path, node.lineno, node.module, "from"))
    return edges


def iter_skill_files(target: Path):
    """Yield ``(skill_name, path)`` for every ``ari-skill-*/src/**/*.py``."""
    for skill_dir in sorted(target.glob("ari-skill-*")):
        src = skill_dir / "src"
        if not src.is_dir():
            continue
        name = skill_dir.name[len("ari-skill-"):]
        for py in sorted(src.rglob("*.py")):
            yield name, py


def iter_core_files(target: Path):
    """Yield every ``ari-core/ari/**/*.py``."""
    core = target / "ari-core" / "ari"
    if not core.is_dir():
        return
    for py in sorted(core.rglob("*.py")):
        yield py


# -- rules ------------------------------------------------------------------


def _under_roots(module: str, roots: list[str]) -> bool:
    return any(module == r or module.startswith(r + ".") for r in roots)


def b1_violation(edge: Edge, rules: dict) -> bool:
    """True if a skill edge crosses the seam into a non-public core module."""
    top = edge.module.split(".")[0]
    if top == "ari":
        # A bare ``ari`` (``import ari`` / ``from ari import x``) reaches only the
        # top-level package at segment granularity, not an internal submodule --
        # this is the sanctioned cost_tracker fallback shape and is not a
        # violation.  A qualified ``ari.<seg>`` must be under an allowed root.
        if len(edge.module.split(".")) == 1:
            return False
        return not _under_roots(edge.module, rules["allowed_skill_import_roots"])
    if rules.get("flag_cross_skill_imports") and top.startswith("ari_skill_"):
        return True
    return False


def b2_violation(edge: Edge, rules: dict) -> bool:
    """True if a core edge imports a non-sanctioned ari_skill_* package."""
    top = edge.module.split(".")[0]
    if not top.startswith("ari_skill_"):
        return False
    sanctioned = set(rules.get("sanctioned_core_to_skill") or [])
    if top in sanctioned:
        restrict = rules.get("restrict_memory_edge_to")
        if restrict and top == "ari_skill_memory":
            base = restrict.rstrip("/")
            if edge.file != base and not edge.file.startswith(base + "/"):
                return True  # sanctioned edge, but outside the allowed seam
        return False
    return True


def core_viz_violation(edge: Edge) -> bool:
    return edge.module == "ari.viz" or edge.module.startswith("ari.viz.")


# -- assembly ---------------------------------------------------------------


def build_findings(target: Path, rules: dict, allow_ids: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    roots = ", ".join(rules["allowed_skill_import_roots"])

    for name, py in iter_skill_files(target):
        rel = py.relative_to(target).as_posix()
        for edge in collect_imports(py, rel):
            if b1_violation(edge, rules):
                fid = f"{rel}::{edge.module}"
                findings.append(
                    Finding(
                        "B1", name, rel, edge.line, edge.module, "error",
                        f"skill '{name}' imports private '{edge.module}' "
                        f"(skills may only import from: {roots})",
                        fid in allow_ids,
                    )
                )

    forbid_viz = bool(rules.get("forbid_core_to_viz_from_cli"))
    for py in iter_core_files(target):
        rel = py.relative_to(target).as_posix()
        edges = collect_imports(py, rel)
        for edge in edges:
            if b2_violation(edge, rules):
                fid = f"{rel}::{edge.module}"
                findings.append(
                    Finding(
                        "B2", "ari-core", rel, edge.line, edge.module, "error",
                        f"core imports non-sanctioned skill '{edge.module}' "
                        "(only ari_skill_memory is sanctioned)",
                        fid in allow_ids,
                    )
                )
            if forbid_viz and rel.startswith("ari-core/ari/cli/") \
                    and core_viz_violation(edge):
                fid = f"{rel}::{edge.module}"
                findings.append(
                    Finding(
                        "CORE_VIZ", "ari-core", rel, edge.line, edge.module,
                        "warning",
                        f"core cli imports dashboard '{edge.module}' "
                        "(invert via a callback/port)",
                        fid in allow_ids,
                    )
                )

    findings.sort(key=lambda f: (f.file, f.line, f.imported_module, f.rule))
    return findings


# -- config / allowlist -----------------------------------------------------


def load_config(path: Path) -> dict:
    rules = dict(DEFAULT_RULES)
    if path and path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key in DEFAULT_RULES:
            if key in data:
                rules[key] = data[key]
    return rules


def load_allow(path: Path | None) -> tuple[set[str], dict[str, str]]:
    ids: set[str] = set()
    notes: dict[str, str] = {}
    if path is None or not path.exists():
        return ids, notes
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for entry in data.get("known", []) or []:
        if isinstance(entry, str):
            ids.add(entry)
        elif isinstance(entry, dict) and entry.get("id"):
            ids.add(entry["id"])
            if entry.get("note"):
                notes[entry["id"]] = entry["note"]
    return ids, notes


# -- emitters ---------------------------------------------------------------


def to_report(target_str: str, findings: list[Finding]) -> dict:
    b1 = sum(1 for f in findings if f.rule == "B1")
    b2 = sum(1 for f in findings if f.rule == "B2")
    known = sum(1 for f in findings if f.allowlisted)
    new = sum(1 for f in findings if not f.allowlisted)
    return {
        "checker": CHECKER_NAME,
        "version": SCHEMA_VERSION,
        "target": target_str,
        "summary": {
            "b1": b1, "b2": b2, "known": known, "new": new, "total": len(findings),
        },
        "findings": [
            {
                "id": f.id,
                "rule": f.rule,
                "kind": f.rule.lower(),
                "package": f.package,
                "file": f.file,
                "line": f.line,
                "imported_module": f.imported_module,
                "severity": f.severity,
                "message": f.message,
                "allowlisted": f.allowlisted,
                "status": "known" if f.allowlisted else "new",
            }
            for f in findings
        ],
    }


def render_json(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=False)


def render_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        f"# {CHECKER_NAME}",
        "",
        f"Target: `{report['target']}`",
        "",
        f"- B1 (skill -> private core): **{s['b1']}**",
        f"- B2 (core -> non-sanctioned skill): **{s['b2']}**",
        f"- known (allowlisted): {s['known']}  ·  new: **{s['new']}**",
        "",
    ]
    if not report["findings"]:
        lines.append("No import-boundary violations found.")
        return "\n".join(lines) + "\n"
    lines += [
        "| Rule | Package | Imported module | Location | Status |",
        "|------|---------|-----------------|----------|--------|",
    ]
    for f in report["findings"]:
        status = "known" if f["allowlisted"] else "**new**"
        lines.append(
            f"| {f['rule']} | {f['package']} | `{f['imported_module']}` "
            f"| `{f['file']}:{f['line']}` | {status} |"
        )
    return "\n".join(lines) + "\n"


# -- cli --------------------------------------------------------------------


def _target_str(target: Path) -> str:
    try:
        rel = target.relative_to(REPO_ROOT).as_posix()
        return rel or "."
    except ValueError:
        return str(target)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--target", default=str(REPO_ROOT),
                    help="restrict the scan subtree (default: repo root)")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG),
                    help="rule config YAML (default: scripts/quality/%(prog)s.yaml)")
    ap.add_argument("--allow", default=str(DEFAULT_ALLOW),
                    help="frozen allowlist YAML (default: scripts/quality/...allow.yaml)")
    ap.add_argument("--output", default=None,
                    help="write the report to a file instead of stdout")
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown",
                    help="report format (default: markdown)")
    ap.add_argument("--json", action="store_true",
                    help="alias for --format json")
    ap.add_argument("--warning-only", action="store_true",
                    help="force exit 0 regardless of findings (default posture)")
    ap.add_argument("--fail-on-regression", action="store_true",
                    help="exit 1 only on findings not in the allowlist (ratchet)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    rules = load_config(Path(args.config))
    allow_ids, _notes = load_allow(Path(args.allow) if args.allow else None)
    target = Path(args.target).resolve()

    findings = build_findings(target, rules, allow_ids)
    report = to_report(_target_str(target), findings)

    fmt = "json" if args.json else args.format
    text = render_json(report) if fmt == "json" else render_markdown(report)

    if args.output:
        Path(args.output).write_text(text + ("\n" if not text.endswith("\n") else ""),
                                     encoding="utf-8")
    else:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")

    if args.warning_only:
        return 0
    if args.fail_on_regression:
        return 1 if any(not f.allowlisted for f in findings) else 0
    # Default posture is warning-mode-first (subtask 026 §1/§17): report, exit 0.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
