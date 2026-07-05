#!/usr/bin/env python3
"""Inline-prompt externalization inventory (warning-mode-first).

Design: ``docs/refactoring/009_quality_scripts_plan.md`` §5.7 (checker block),
§3 (common CLI/JSON contract), §6 (warning-mode-first rollout), §8 (placement +
``scripts/quality/`` bootstrap); ``docs/refactoring/011_prompt_management_plan.md``
§2/§3/§5.x (prompt locations + the inline-prompt verdict vocabulary); the subtask
``docs/refactoring/subtasks/043_add_prompt_checker_script.md``. The frozen
allowlist is seeded from the Subtask 036 census
(``docs/refactoring/reports/hardcoded_prompt_inventory.{md,json}``).

The **NEW slice** (net-new, 009 §5.7): a deterministic ``ast`` scan for the
substantial LLM system/instruction prompts still hardcoded as string literals in
the runtime tree (the skill ``server.py`` files + helpers), reported as
externalization candidates against a frozen allowlist. It is the repeatable,
CI-runnable successor to the one-shot hand inventory of Subtask 036.

The **snapshot-consistency slice is NOT re-implemented** (009 §5.7: "call Gate 10
or leave it alone"). ``--with-snapshots`` shells out to the existing **Gate 10**
(``report/scripts/check_prompt_snapshots.py --root <REPO_ROOT>``), which
byte-verifies ``ari-core/ari/prompts/**/*.md`` against
``report/shared/appendix/prompts/**``. This checker never re-derives Gate 10's
``% snapshot-from:`` SHA-256 header logic; it invokes that script and folds its
pass/fail into the report. Default is OFF so the two gates run independently.

Detection heuristic (009 §5.7 / subtask §7.2 / §17 "structure, not 'You are'"):
a candidate is an assignment/return/argument **string expression** -- implicit
concatenation, a ``+`` ``BinOp`` chain, or an f-string, reconstructed with
``{x}`` placeholders for interpolated values -- that

  (a) opens with a **role marker** ("You are" / "You <verb>" / "act as"),
  (b) spans ``>= min_lines`` physical source lines, and
  (c) is ``>= min_chars`` characters long.

Requiring a role opener keys on *structure*, not a bare "You are": it catches
``BinOp``-split prompts (``"You are an expert reviewer for " + venue + body``)
while ignoring user-message assemblers, tool-schema descriptions, bash
templates, and docstrings that merely happen to contain ``return JSON`` / ``{"``.
Negative control: ``ari-core/ari/agent/loop.py`` yields **0** candidates -- its
system prompt is already externalized to ``agent/system.md``. This checker only
*detects*; it never extracts, renames, or moves any prompt (that is the runtime
work of Subtasks 039/040/041).

Determinism (design principle P2): stdlib ``ast`` + PyYAML only, no LLM, no
network. Same input tree => same candidate report.

Exit convention (matches the ``scripts/quality/`` family + 009 §3):
  0 = clean, advisory default, or ``--warning-only``;
  1 = net-new candidates under ``--fail-on-regression``, OR Gate 10 failed under
      ``--with-snapshots`` (unless ``--warning-only``);
  2 = usage/environment error (Gate 10 script missing, ruff/PyYAML missing, an
      ``ast`` parse failure on a target), matching
      ``scripts/docs/check_doc_sources.py``'s ``SystemExit(2)``.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CHECKER_NAME = "check_prompts"
SCHEMA_VERSION = 1

DEFAULT_CONFIG = REPO_ROOT / "scripts" / "quality" / "check_prompts.yaml"
DEFAULT_ALLOWLIST = REPO_ROOT / "scripts" / "quality" / "check_prompts.allow.yaml"

# The existing snapshot gate this checker defers to (never re-implemented).
GATE10 = REPO_ROOT / "report" / "scripts" / "check_prompt_snapshots.py"

# The Subtask 036 machine-readable census that seeds the allowlist verdicts.
CENSUS_JSON = REPO_ROOT / "scripts" / "quality" / "baselines" / "hardcoded_prompt_inventory.json"

# Verdict vocabulary carried from 036 / 011 §5.x (used for the allowlist tags).
VERDICTS = (
    "EXTRACT_TEMPLATE",
    "MERGE_DUPLICATE",
    "MOVE_TO_CONFIGURABLE_PROMPT",
    "KEEP_INLINE",
    "REVIEW_REQUIRED",
)

# Built-in fallbacks; every key is overridable via scripts/quality/check_prompts.yaml.
DEFAULTS: dict[str, object] = {
    # A candidate MUST match one of these to fire (structure, not a bare "You
    # are"). They catch role-defining openers while rejecting user-message
    # assemblers ("You must produce ...") and schema descriptions.
    "role_markers": [
        r"\byou are\b",
        r"\byou're\b",
        r"\bact as\b",
        (
            r"\byou (?:will|act|extract|analy[sz]e|evaluate|assess|review|"
            r"generate|write|judge|decide|identify|classify|summari[sz]e)\b"
        ),
    ],
    # Recorded as secondary evidence (never sufficient alone).
    "json_markers": [
        r"```json",
        r"\bjson object\b",
        r"\bjson array\b",
        r"respond only with json",
        r"respond with a json",
        r"return only valid json",
        r"\breturn json\b",
        r"valid json",
    ],
    "rubric_markers": [
        r"\brubric\b",
        r"hard constraint",
        r"peer review",
        r"\breviewer\b",
    ],
    "min_lines": 4,
    "min_chars": 200,
    # Default scan scope: ari-core/ari plus every ari-skill-*/src (subtask §7.4).
    "default_targets": ["ari-core/ari"],
    "scan_all_skill_src": True,
    # Pruned during the walk (never parsed).
    "exclude_dir_segments": [
        "tests",
        "__pycache__",
        "node_modules",
        "vendor",
        ".venv",
        ".git",
        "dist",
    ],
    # Vendored KEEP_INLINE files excluded wholesale (036 §3.5): re-writing them
    # forks upstream. Repo-relative posix paths.
    "exclude_files": [
        "ari-skill-paper-re/src/_paperbench_bridge.py",
    ],
}


def _import_common():
    """Load ``scripts/quality/_common.py`` without a package (avoids E402)."""
    common_path = REPO_ROOT / "scripts" / "quality" / "_common.py"
    spec = importlib.util.spec_from_file_location("quality_common", common_path)
    if spec is None or spec.loader is None:
        sys.stderr.write(
            "check_prompts: cannot locate scripts/quality/_common.py\n"
        )
        raise SystemExit(2)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_common = _import_common()


# --------------------------------------------------------------------------- config
def load_config(path: Path | None) -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy of the literal defaults
    override = _common.load_yaml(path) if path and path.exists() else {}
    for key, val in override.items():
        cfg[key] = val
    return cfg


class Markers:
    """Compiled marker sets, evaluated case-insensitively."""

    def __init__(self, cfg: dict):
        self.role = [re.compile(p, re.IGNORECASE) for p in cfg["role_markers"]]
        self.json = [re.compile(p, re.IGNORECASE) for p in cfg["json_markers"]]
        self.rubric = [re.compile(p, re.IGNORECASE) for p in cfg["rubric_markers"]]

    def tags(self, text: str) -> list[str]:
        """Return the marker tags present; empty when no role marker matches."""
        if not any(p.search(text) for p in self.role):
            return []
        tags = ["role"]
        if any(p.search(text) for p in self.json):
            tags.append("json")
        if any(p.search(text) for p in self.rubric):
            tags.append("rubric")
        return tags


# --------------------------------------------------------------------------- targets
def _skill_src_dirs() -> list[str]:
    out = []
    for d in sorted(REPO_ROOT.glob("ari-skill-*")):
        if d.is_dir() and (d / "src").is_dir():
            out.append(f"{d.name}/src")
    return out


def resolve_targets(explicit: list[str] | None, cfg: dict) -> list[str]:
    """Repo-relative scan roots: explicit ``--target``s, else the config default."""
    if explicit:
        return explicit
    targets = list(cfg["default_targets"])
    if cfg.get("scan_all_skill_src"):
        targets += _skill_src_dirs()
    return targets


def iter_py_files(targets: list[str], cfg: dict):
    """Yield ``(repo_rel_path, abs_path)`` for every in-scope ``*.py``."""
    excl = set(cfg["exclude_dir_segments"])
    excl_files = set(cfg["exclude_files"])
    seen: set[str] = set()
    for target in targets:
        base = (REPO_ROOT / target).resolve()
        candidates: list[Path]
        if base.is_file() and base.suffix == ".py":
            candidates = [base]
        elif base.is_dir():
            candidates = sorted(base.rglob("*.py"))
        else:
            continue
        rel_base = base if base.is_dir() else base.parent
        for p in candidates:
            try:
                rel = p.resolve().relative_to(REPO_ROOT).as_posix()
            except ValueError:
                # Out-of-repo target (e.g. a tmp test fixture): key the finding
                # relative to the scan base rather than dropping it.
                rel = p.resolve().relative_to(rel_base).as_posix()
            parts = rel.split("/")
            if any(seg in excl for seg in parts):
                continue
            if p.name.startswith("test_"):
                continue
            if rel in excl_files:
                continue
            if rel not in seen:
                seen.add(rel)
                yield rel, p


# --------------------------------------------------------------------------- detection
@dataclass
class Candidate:
    file: str
    line: int
    name: str | None
    lines: int
    chars: int
    markers: list[str] = field(default_factory=list)
    key: str = ""  # stable identity, assigned by assign_keys()


def assign_keys(cands: list[Candidate]) -> None:
    """Assign each candidate a stable, collision-free ``key`` in place.

    A name key ``<file>::<name>`` survives line drift in large files (subtask
    §11), so it is used only when the name is **unique within its file** -- the
    high-value module-constant prompts (``_SEMANTIC_SYSTEM_PROMPT``,
    ``_QUERY_SYSTEM``, ...). Repeated local names (five ``system_prompt`` in
    ``ari-skill-paper``, two ``analysis_prompt`` in ``ari-skill-transform``) and
    anonymous return/arg literals fall back to the line key ``<file>#L<line>`` so
    ids never collide -- a genuinely NEW same-named prompt is therefore still
    caught as ``new`` rather than silently matching a sibling's entry.
    """
    per_file: dict[str, dict[str, int]] = {}
    for c in cands:
        if c.name:
            per_file.setdefault(c.file, {})
            per_file[c.file][c.name] = per_file[c.file].get(c.name, 0) + 1
    for c in cands:
        if c.name and per_file.get(c.file, {}).get(c.name, 0) == 1:
            c.key = f"{c.file}::{c.name}"
        else:
            c.key = f"{c.file}#L{c.line}"


def stringlike(node: ast.AST | None) -> str | None:
    """Reconstruct a string-valued expression, else ``None``.

    Handles a plain ``str`` constant, an f-string (interpolations become the
    ``{x}`` placeholder), and a ``+`` ``BinOp`` chain combining those with
    non-string operands (also ``{x}``). Implicit adjacent-literal concatenation
    is already folded by the parser into one node. A ``BinOp`` counts as
    string-like only when at least one operand is a real string literal, so
    numeric ``a + b`` is left alone.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                parts.append("{x}")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = stringlike(node.left)
        right = stringlike(node.right)
        if left is None and right is None:
            return None
        return (left if left is not None else "{x}") + (
            right if right is not None else "{x}"
        )
    return None


def scan_file(rel: str, path: Path, markers: Markers, cfg: dict) -> list[Candidate]:
    """AST-scan one file for role-marked multi-line prompt literals."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:  # a genuinely unparseable target is an env error
        sys.stderr.write(f"check_prompts: cannot parse {rel}: {exc}\n")
        raise SystemExit(2)
    except (UnicodeDecodeError, ValueError):  # pragma: no cover - defensive
        return []

    min_lines = int(cfg["min_lines"])
    min_chars = int(cfg["min_chars"])
    out: list[Candidate] = []

    def visit(node: ast.AST, parent: ast.AST | None, name: str | None) -> None:
        text = stringlike(node)
        if text is not None:
            # A bare string statement is a docstring / no-op, never an active
            # prompt; a string nested inside a larger string expression is not a
            # root -- skip both so we emit each prompt exactly once.
            if isinstance(parent, ast.Expr) or stringlike(parent) is not None:
                return
            tags = markers.tags(text)
            span = (node.end_lineno or node.lineno) - node.lineno + 1
            if tags and span >= min_lines and len(text) >= min_chars:
                out.append(
                    Candidate(rel, node.lineno, name, span, len(text), tags)
                )
            return
        for child in ast.iter_child_nodes(node):
            child_name = name
            if isinstance(node, ast.Assign) and child is node.value:
                if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    child_name = node.targets[0].id
            elif (
                isinstance(node, ast.AnnAssign)
                and child is node.value
                and isinstance(node.target, ast.Name)
            ):
                child_name = node.target.id
            visit(child, node, child_name)

    visit(tree, None, None)
    out.sort(key=lambda c: (c.file, c.line))
    return out


def scan_targets(targets: list[str], cfg: dict) -> list[Candidate]:
    markers = Markers(cfg)
    findings: list[Candidate] = []
    for rel, path in iter_py_files(targets, cfg):
        findings.extend(scan_file(rel, path, markers, cfg))
    findings.sort(key=lambda c: (c.file, c.line))
    assign_keys(findings)
    return findings


# --------------------------------------------------------------------------- allowlist
def load_allow(path: Path | None) -> dict[str, dict]:
    """Return ``{id: entry}`` from a ``check_prompts.allow.yaml`` baseline."""
    if path is None or not path.exists():
        return {}
    data = _common.load_yaml(path)
    out: dict[str, dict] = {}
    for entry in data.get("known", []) or []:
        if isinstance(entry, str):
            out[entry] = {"id": entry}
        elif isinstance(entry, dict) and entry.get("id"):
            out[entry["id"]] = entry
    return out


# --------------------------------------------------------------------------- 036 census
def _census_verdicts() -> dict[str, tuple[str, str]]:
    """Map ``(file, line)`` -> ``(verdict, prompt_id)`` from the 036 JSON twin.

    Best-effort enrichment for ``--update-baseline`` only; a missing or malformed
    census yields an empty map (the baseline still freezes, verdicts default to
    ``REVIEW_REQUIRED``). The normal scan never reads this file.
    """
    if not CENSUS_JSON.exists():
        return {}
    try:
        data = json.loads(CENSUS_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):  # pragma: no cover - defensive
        return {}
    owner_re = re.compile(r"([\w./-]+\.py):(\d+)")
    out: dict[str, tuple[str, str]] = {}
    regimes = data.get("regimes", {})
    rows: list[dict] = []
    for key in ("inline_prompts", "keep_inline_vendored_and_fallback", "rubric_builders"):
        rows.extend(regimes.get(key, []) or [])
    for row in rows:
        owner = str(row.get("owner", ""))
        m = owner_re.search(owner)
        if not m:
            continue
        verdict = str(row.get("classification", "REVIEW_REQUIRED"))
        if verdict not in VERDICTS:
            verdict = "REVIEW_REQUIRED"
        pid = str(row.get("prompt_id", ""))
        out[f"{m.group(1)}:{m.group(2)}"] = (verdict, pid)
    return out


def _verdict_for(cand: Candidate, census: dict[str, tuple[str, str]]) -> tuple[str, str]:
    """Closest 036 verdict for a candidate (same file, within +/- 6 lines)."""
    best: tuple[str, str] | None = None
    best_delta = 7
    for key, (verdict, pid) in census.items():
        cfile, _, cline = key.rpartition(":")
        if cfile != cand.file:
            continue
        delta = abs(int(cline) - cand.line)
        if delta < best_delta:
            best_delta = delta
            best = (verdict, pid)
    return best if best is not None else ("REVIEW_REQUIRED", "")


# --------------------------------------------------------------------------- findings
def build_findings(cands: list[Candidate], allow: dict[str, dict]) -> list[dict]:
    findings: list[dict] = []
    for c in cands:
        entry = allow.get(c.key)
        allowlisted = entry is not None
        verdict = str((entry or {}).get("verdict", "")) or "unclassified"
        findings.append(
            {
                "id": c.key,
                "severity": "info" if allowlisted else "warning",
                "file": c.file,
                "line": c.line,
                "name": c.name,
                "lines": c.lines,
                "chars": c.chars,
                "markers": c.markers,
                "verdict": verdict,
                "allowlisted": allowlisted,
                "status": "known" if allowlisted else "new",
            }
        )
    return findings


# --------------------------------------------------------------------------- Gate 10
def run_gate10() -> tuple[str, int]:
    """Invoke Gate 10 and return ``(status, exit_code)``; never re-implement it."""
    if not GATE10.exists():
        try:
            shown = GATE10.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            shown = str(GATE10)
        sys.stderr.write(
            f"check_prompts: Gate 10 script missing at {shown} "
            "(needed for --with-snapshots).\n"
        )
        raise SystemExit(2)
    proc = subprocess.run(
        [sys.executable, str(GATE10), "--root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return "pass", 0
    if proc.returncode == 1:
        return "fail", 1
    sys.stderr.write(
        f"check_prompts: Gate 10 errored (exit {proc.returncode}): "
        f"{proc.stderr.strip()}\n"
    )
    raise SystemExit(2)


# --------------------------------------------------------------------------- report
def summarize(findings: list[dict], snapshots: str) -> dict:
    by_verdict: dict[str, int] = {}
    for f in findings:
        by_verdict[f["verdict"]] = by_verdict.get(f["verdict"], 0) + 1
    known = sum(1 for f in findings if f["allowlisted"])
    return {
        "candidates": len(findings),
        "known": known,
        "new": len(findings) - known,
        "by_verdict": by_verdict,
        "snapshots": snapshots,
    }


def render_json(targets: list[str], summary: dict, findings: list[dict]) -> str:
    return json.dumps(
        {
            "checker": CHECKER_NAME,
            "version": SCHEMA_VERSION,
            "target": targets,
            "summary": summary,
            "findings": findings,
        },
        ensure_ascii=False,
        indent=2,
    )


def render_markdown(targets: list[str], summary: dict, findings: list[dict]) -> str:
    lines = [
        "# check_prompts report",
        "",
        f"Targets: `{', '.join(targets)}`",
        "",
        (
            f"Inline-prompt candidates: **{summary['candidates']}** "
            f"(known: {summary['known']}, new: **{summary['new']}**); "
            f"snapshots (Gate 10): {summary['snapshots']}."
        ),
        "",
    ]
    if summary["by_verdict"]:
        by = ", ".join(f"{k}: {v}" for k, v in sorted(summary["by_verdict"].items()))
        lines += [f"By verdict — {by}.", ""]
    if findings:
        rows = [
            [
                f["file"] + f":{f['line']}",
                f["name"] or "(anon)",
                str(f["lines"]),
                str(f["chars"]),
                ",".join(f["markers"]),
                f["verdict"],
                "known" if f["allowlisted"] else "NEW",
            ]
            for f in findings
        ]
        lines.append(
            _common.render_markdown_table(
                ["location", "name", "lines", "chars", "markers", "verdict", "status"],
                rows,
            )
        )
    else:
        lines.append("_No inline-prompt candidates._")
    return "\n".join(lines)


# --------------------------------------------------------------------------- baseline
def update_baseline(cfg: dict) -> int:
    """Freeze the current comprehensive candidate set into the allowlist file."""
    targets = resolve_targets(None, cfg)
    cands = scan_targets(targets, cfg)
    census = _census_verdicts()

    known: list[dict] = []
    for c in cands:
        verdict, pid = _verdict_for(c, census)
        entry: dict[str, object] = {
            "id": c.key,
            "file": c.file,
            "line": c.line,
            "name": c.name,
            "lines": c.lines,
            "chars": c.chars,
            "markers": c.markers,
            "verdict": verdict,
        }
        if pid:
            entry["prompt_id"] = pid
        known.append(entry)
    known.sort(key=lambda e: (e["file"], e["line"]))

    header = [
        "# check_prompts.allow.yaml -- frozen inline-prompt baseline (subtask 043).",
        "# Regenerate: python scripts/check_prompts.py --update-baseline",
        "# Seeded from the Subtask 036 census "
        "(docs/refactoring/reports/hardcoded_prompt_inventory.{md,json}).",
        "# Each entry is keyed by id '<file>::<name>' (or '<file>#L<line>' when the",
        "# prompt literal is anonymous). Findings on a known id are reported 'known'",
        "# and never fail --fail-on-regression; NET-NEW role-marked prompts do.",
        "# 'verdict' carries the 036/011 §5.x classification (EXTRACT_TEMPLATE,",
        "# MERGE_DUPLICATE, MOVE_TO_CONFIGURABLE_PROMPT, KEEP_INLINE, REVIEW_REQUIRED);",
        "# EXTRACT_TEMPLATE entries SHRINK as subtasks 039/040/041 externalize them.",
        "# Do NOT hand-edit findings away -- tune scripts/quality/check_prompts.yaml.",
    ]
    _common.dump_yaml_with_header(
        DEFAULT_ALLOWLIST, header, {"version": SCHEMA_VERSION, "known": known}
    )
    sys.stderr.write(
        f"check_prompts: wrote {DEFAULT_ALLOWLIST.relative_to(REPO_ROOT)} "
        f"({len(known)} inline-prompt candidates frozen).\n"
    )
    return 0


# --------------------------------------------------------------------------- cli
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--target",
        action="append",
        default=None,
        help="restrict the scan to a subtree (repeatable; "
        "default: ari-core/ari + each ari-skill-*/src)",
    )
    p.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="YAML config (default: scripts/quality/check_prompts.yaml)",
    )
    p.add_argument(
        "--allow",
        default=str(DEFAULT_ALLOWLIST),
        help="frozen allowlist YAML (default: scripts/quality/check_prompts.allow.yaml)",
    )
    p.add_argument("--output", default=None, help="write the report to a file")
    p.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="report format (json = aggregator building block)",
    )
    p.add_argument(
        "--json",
        dest="json_alias",
        action="store_true",
        help="convenience alias for --format json",
    )
    p.add_argument(
        "--warning-only",
        action="store_true",
        help="force exit 0 regardless of findings (advisory; default posture)",
    )
    p.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="exit 1 only for net-new candidates above the frozen allowlist",
    )
    p.add_argument(
        "--base-ref",
        default="origin/main",
        help="base git ref for diff-scoped context (default: origin/main)",
    )
    p.add_argument(
        "--with-snapshots",
        action="store_true",
        help="additionally invoke Gate 10 (report/scripts/check_prompt_snapshots.py) "
        "and fold its result in (default off)",
    )
    p.add_argument(
        "--update-baseline",
        action="store_true",
        help="regenerate check_prompts.allow.yaml from the current tree",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(Path(args.config) if args.config else None)

    if args.update_baseline:
        return update_baseline(cfg)

    targets = resolve_targets(args.target, cfg)
    allow = load_allow(Path(args.allow) if args.allow else None)
    cands = scan_targets(targets, cfg)
    findings = build_findings(cands, allow)

    snapshots = "skipped"
    gate_fail = False
    if args.with_snapshots:
        snapshots, code = run_gate10()
        gate_fail = code != 0

    summary = summarize(findings, snapshots)
    out_format = "json" if args.json_alias else args.format
    text = (
        render_json(targets, summary, findings)
        if out_format == "json"
        else render_markdown(targets, summary, findings)
    )
    _common.write_output(text, args.output)

    if args.warning_only:
        return 0
    if gate_fail:
        return 1
    if args.fail_on_regression and summary["new"]:
        return 1
    # Advisory default (warning-mode-first, 009 §6; mirrors the sibling
    # scripts/quality/ checkers): report but never block on historical debt.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
