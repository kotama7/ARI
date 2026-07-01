#!/usr/bin/env python3
"""Source-code size & cyclomatic-complexity gate (warning-mode-first).

Design: ``docs/refactoring/009_quality_scripts_plan.md`` §5.1 (checker block),
§3 (common CLI/JSON contract), §6 (warning-mode-first rollout), §8 (placement +
``scripts/quality/`` bootstrap). Reproduces and freezes the empirical baseline
in ``docs/refactoring/reports/001_complexity_baseline.md`` (subtask 001) and its
sibling ``loc_census.csv``.

Two measurement dimensions:

* **File-size tiers** (all targets, including the frontend): physical LOC
  counted with ``wc -l`` parity (newline bytes, matching ``loc_census.csv``),
  classified into ``warn`` (>500), ``review`` (>800), ``split-required`` (>1200).
* **Cyclomatic complexity** (Python targets only): the ruff McCabe rule invoked
  through the CLI as ``ruff check --select C901 --config
  'lint.mccabe.max-complexity=<N>' --output-format json``. ``radon`` is NOT
  installed and is NOT assumed; NO ``[tool.ruff]`` block is added to
  ``ari-core/pyproject.toml`` -- the rule is selected per invocation so the
  repo-wide lint posture is unchanged. ruff cannot parse TS/TSX, so frontend
  files get the LOC dimension only.

Engine decision (recorded, per 001 §8 ``REVIEW_REQUIRED``): ruff ``C901`` is
chosen over installing ``radon`` because ruff 0.15.2 is already present and no
new dependency is introduced.

Rollout posture (009 §6): a bare run is **advisory** and always exits 0.
``--fail-on-regression`` is the ratchet -- it exits 1 only on net-new debt
(a file/function not covered by the frozen ``check_complexity.allow.yaml``, or
an allowlisted file that has crossed to a *higher* LOC tier). ``--warning-only``
forces exit 0 even under the ratchet. This checker is NOT wired into any
workflow by subtask 025.

Exit convention (matches ``scripts/docs/`` and 009 §3):
  0 = clean, advisory, or ``--warning-only``;
  1 = net-new debt under ``--fail-on-regression``;
  2 = usage/environment error (e.g. ruff not on PATH).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CHECKER_NAME = "check_complexity"
SCHEMA_VERSION = 1

DEFAULT_CONFIG = REPO_ROOT / "scripts" / "quality" / "check_complexity.yaml"
DEFAULT_ALLOWLIST = REPO_ROOT / "scripts" / "quality" / "check_complexity.allow.yaml"

# Frontend TS/TSX is a separate 001 cohort rooted here (Python never lives under
# it), so frontend files are collected only from this subtree for census parity.
FRONTEND_ROOT = "ari-core/ari/viz/frontend/src/"

# LOC tier ordering (rank used to detect tier escalation of allowlisted files).
TIER_ORDER = ["-", "warn", "review", "split-required"]

# Built-in fallbacks; overridable via scripts/quality/check_complexity.yaml.
DEFAULTS: dict[str, object] = {
    "loc_tiers": {"warn": 500, "review": 800, "split_required": 1200},
    "max_complexity": 15,
    "include_tests": False,
    "python_extensions": [".py"],
    "frontend_extensions": [".ts", ".tsx"],
    "exclude_dir_segments": [
        "__pycache__",
        "node_modules",
        "vendor",
        ".venv",
        ".git",
        "dist",
    ],
    "default_targets": ["ari-core/ari"],
}


def _import_common():
    """Load ``scripts/quality/_common.py`` without a package (avoids E402)."""
    common_path = REPO_ROOT / "scripts" / "quality" / "_common.py"
    spec = importlib.util.spec_from_file_location("quality_common", common_path)
    if spec is None or spec.loader is None:
        sys.stderr.write(
            "check_complexity: cannot locate scripts/quality/_common.py\n"
        )
        raise SystemExit(2)
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass (with `from __future__ import
    # annotations`) can resolve the module in sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_common = _import_common()
Finding = _common.Finding


# --------------------------------------------------------------------------- config
def load_config(path: Path) -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy of the literal defaults
    override = _common.load_yaml(path) if path else {}
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(val)
        else:
            cfg[key] = val
    return cfg


# --------------------------------------------------------------------------- targets
def census_targets() -> list[str]:
    """The full 001 census scope: core-prod + every skill ``src/`` + frontend.

    Used for ``--update-baseline`` so the frozen allowlist is comprehensive
    (009 §5.1 / subtask 025 §7.5), regardless of any narrowing ``--target``.
    """
    targets = ["ari-core/ari"]
    for d in sorted(REPO_ROOT.glob("ari-skill-*")):
        if d.is_dir() and (d / "src").is_dir():
            targets.append(f"{d.name}/src")
    targets.append(FRONTEND_ROOT.rstrip("/"))
    return targets


def is_test_file(rel: str) -> bool:
    parts = rel.split("/")
    return "tests" in parts or Path(rel).name.startswith("test_")


def collect_files(targets: list[str], cfg: dict) -> list[tuple[str, str]]:
    """Return sorted ``(repo_rel_path, kind)`` where kind is python|frontend."""
    py_ext = tuple(cfg["python_extensions"])
    fe_ext = tuple(cfg["frontend_extensions"])
    excl = set(cfg["exclude_dir_segments"])
    include_tests = bool(cfg["include_tests"])
    seen: set[tuple[str, str]] = set()

    for target in targets:
        base = (REPO_ROOT / target).resolve()
        if base.is_file():
            candidates = [base]
        elif base.is_dir():
            candidates = []
            for root, dirs, files in os.walk(base):
                dirs[:] = sorted(d for d in dirs if d not in excl)
                for fn in files:
                    candidates.append(Path(root) / fn)
        else:
            continue
        for p in candidates:
            try:
                rel = p.resolve().relative_to(REPO_ROOT).as_posix()
            except ValueError:
                continue
            parts = rel.split("/")
            if any(seg in excl for seg in parts):
                continue
            if not include_tests and is_test_file(rel):
                continue
            name = p.name
            if name.endswith(py_ext) and not rel.startswith("ari-core/ari/viz/frontend/"):
                seen.add((rel, "python"))
            elif rel.startswith(FRONTEND_ROOT) and name.endswith(fe_ext):
                seen.add((rel, "frontend"))
    return sorted(seen)


# --------------------------------------------------------------------------- LOC
def count_loc(rel: str) -> int:
    """Physical line count with ``wc -l`` parity (newline bytes)."""
    return (REPO_ROOT / rel).read_bytes().count(b"\n")


def tier_of(loc: int, tiers: dict) -> str:
    if loc > tiers["split_required"]:
        return "split-required"
    if loc > tiers["review"]:
        return "review"
    if loc > tiers["warn"]:
        return "warn"
    return "-"


# --------------------------------------------------------------------------- complexity
def run_ruff_complexity(py_files: list[str], max_complexity: int) -> list[dict]:
    """Return per-function complexity records via the ruff McCabe CLI.

    Raises ``SystemExit(2)`` only when ruff is genuinely unavailable/erroring --
    a run with zero complexity findings is a normal exit 0/1, not an error.
    """
    if not py_files:
        return []
    if shutil.which("ruff") is None:
        sys.stderr.write(
            "check_complexity: ruff not found on PATH (required for C901).\n"
        )
        raise SystemExit(2)
    cmd = [
        "ruff",
        "check",
        "--select",
        "C901",
        "--config",
        f"lint.mccabe.max-complexity={max_complexity}",
        "--output-format",
        "json",
        *[str(REPO_ROOT / f) for f in py_files],
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    # ruff returns 1 when it *finds* violations (normal); >=2 is a real error.
    if proc.returncode not in (0, 1):
        sys.stderr.write(
            f"check_complexity: ruff failed (exit {proc.returncode}): "
            f"{proc.stderr.strip()}\n"
        )
        raise SystemExit(2)
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        sys.stderr.write("check_complexity: could not parse ruff JSON output.\n")
        raise SystemExit(2)

    msg_re = re.compile(r"`([^`]+)` is too complex \((\d+)")
    out: list[dict] = []
    for d in data:
        if d.get("code") != "C901":
            continue
        filename = d.get("filename", "")
        try:
            rel = Path(filename).resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel = filename
        row = int((d.get("location") or {}).get("row", 0) or 0)
        msg = d.get("message", "")
        m = msg_re.search(msg)
        func = m.group(1) if m else "?"
        cc = int(m.group(2)) if m else 0
        out.append({"file": rel, "line": row, "function": func, "complexity": cc})
    out.sort(key=lambda r: (r["file"], r["function"], r["line"]))
    return out


# --------------------------------------------------------------------------- allowlist
def index_allowlist(allow: dict) -> tuple[dict[str, dict], set[str]]:
    """Return (path -> loc-entry, {``file::function``} complexity identities)."""
    loc_index: dict[str, dict] = {}
    for entry in allow.get("loc", []) or []:
        if isinstance(entry, dict) and "path" in entry:
            loc_index[str(entry["path"])] = entry
    cc_index: set[str] = set()
    for entry in allow.get("complexity", []) or []:
        if isinstance(entry, dict) and "path" in entry and "function" in entry:
            cc_index.add(f"{entry['path']}::{entry['function']}")
    return loc_index, cc_index


def loc_rank(tier: str) -> int:
    return TIER_ORDER.index(tier) if tier in TIER_ORDER else 0


# --------------------------------------------------------------------------- scan
def scan(targets: list[str], cfg: dict, allow: dict) -> list[Finding]:
    tiers = cfg["loc_tiers"]
    max_complexity = int(cfg["max_complexity"])
    loc_index, cc_index = index_allowlist(allow)

    files = collect_files(targets, cfg)
    findings: list[Finding] = []

    # --- LOC dimension (all files) ---
    for rel, _kind in files:
        loc = count_loc(rel)
        tier = tier_of(loc, tiers)
        if tier == "-":
            continue
        covered = rel in loc_index
        escalated = covered and loc_rank(tier) > loc_rank(
            str(loc_index[rel].get("tier", "-"))
        )
        allowlisted = covered and not escalated
        msg = f"{loc} LOC (tier {tier})"
        if escalated:
            msg += f" -- escalated above frozen tier {loc_index[rel].get('tier')}"
        findings.append(
            Finding(
                id=f"loc:{rel}",
                severity=tier,
                file=rel,
                line=0,
                kind="loc",
                message=msg,
                allowlisted=allowlisted,
            )
        )

    # --- Complexity dimension (Python files only) ---
    py_files = [rel for rel, kind in files if kind == "python"]
    for rec in run_ruff_complexity(py_files, max_complexity):
        ident = f"{rec['file']}::{rec['function']}"
        allowlisted = ident in cc_index
        findings.append(
            Finding(
                id=f"cc:{ident}",
                severity="complexity",
                file=rec["file"],
                line=rec["line"],
                kind="complexity",
                message=(
                    f"{rec['function']} is too complex "
                    f"({rec['complexity']} > {max_complexity})"
                ),
                allowlisted=allowlisted,
            )
        )

    findings.sort(key=lambda f: (f.kind, -loc_rank(f.severity), f.file, f.line))
    return findings


def summarize(findings: list[Finding], max_complexity: int) -> dict:
    loc_counts = {"warn": 0, "review": 0, "split-required": 0}
    over_complex = 0
    for f in findings:
        if f.kind == "loc":
            loc_counts[f.severity] = loc_counts.get(f.severity, 0) + 1
        elif f.kind == "complexity":
            over_complex += 1
    known = sum(1 for f in findings if f.allowlisted)
    new = sum(1 for f in findings if not f.allowlisted)
    return {
        "loc": loc_counts,
        "complexity": {"over_max": over_complex, "max_complexity": max_complexity},
        "known": known,
        "new": new,
        "total": len(findings),
    }


# --------------------------------------------------------------------------- baseline
def update_baseline(cfg: dict) -> int:
    """Freeze the current comprehensive offender set into the allowlist file."""
    tiers = cfg["loc_tiers"]
    max_complexity = int(cfg["max_complexity"])
    targets = census_targets()
    files = collect_files(targets, cfg)

    loc_entries: list[dict] = []
    for rel, _kind in files:
        loc = count_loc(rel)
        tier = tier_of(loc, tiers)
        if tier != "-":
            loc_entries.append({"path": rel, "loc": loc, "tier": tier})
    loc_entries.sort(key=lambda e: (-loc_rank(e["tier"]), e["path"]))

    py_files = [rel for rel, kind in files if kind == "python"]
    cc_entries = [
        {
            "path": rec["file"],
            "function": rec["function"],
            "line": rec["line"],
            "complexity": rec["complexity"],
        }
        for rec in run_ruff_complexity(py_files, max_complexity)
    ]

    header = [
        "# check_complexity.allow.yaml -- frozen size/complexity baseline (subtask 025).",
        "# Regenerate: python scripts/check_complexity.py --update-baseline",
        "# Frozen against subtask 001: docs/refactoring/reports/001_complexity_baseline.md",
        f"# scope=census(core-prod + ari-skill-*/src + frontend); max_complexity={max_complexity}",
        "# LOC keyed by path (regression = new path OR escalation to a higher tier);",
        "# complexity keyed by path::function (regression = a net-new over-complex function).",
        "# Findings on these identities are reported 'known' and never fail --fail-on-regression.",
    ]
    _common.dump_yaml_with_header(
        DEFAULT_ALLOWLIST,
        header,
        {"version": SCHEMA_VERSION, "loc": loc_entries, "complexity": cc_entries},
    )
    sys.stderr.write(
        f"check_complexity: wrote {DEFAULT_ALLOWLIST.relative_to(REPO_ROOT)} "
        f"({len(loc_entries)} LOC + {len(cc_entries)} complexity offenders "
        f"frozen).\n"
    )
    return 0


# --------------------------------------------------------------------------- report
def render_markdown(targets: list[str], summary: dict, findings: list[Finding]) -> str:
    lines = [
        "# check_complexity report",
        "",
        f"Targets: `{', '.join(targets)}`",
        "",
        (
            f"LOC offenders -- warn: {summary['loc']['warn']}, "
            f"review: {summary['loc']['review']}, "
            f"split-required: {summary['loc']['split-required']}; "
            f"functions over max-complexity "
            f"({summary['complexity']['max_complexity']}): "
            f"{summary['complexity']['over_max']}; "
            f"known: {summary['known']}, new: {summary['new']}."
        ),
        "",
    ]
    if findings:
        rows = [
            [
                f.kind,
                f.severity,
                f.file + (f":{f.line}" if f.line else ""),
                f.message,
                "known" if f.allowlisted else "NEW",
            ]
            for f in findings
        ]
        lines.append(
            _common.render_markdown_table(
                ["kind", "severity", "location", "detail", "status"], rows
            )
        )
    else:
        lines.append("_No findings._")
    return "\n".join(lines)


# --------------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--target",
        action="append",
        default=None,
        help="restrict the scan to a subtree (repeatable; default: ari-core/ari)",
    )
    p.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="YAML config (default: scripts/quality/check_complexity.yaml)",
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
        help="exit 1 only for net-new debt above the frozen allowlist",
    )
    p.add_argument(
        "--base-ref",
        default="origin/main",
        help="base git ref for diff-scoped context (default: origin/main)",
    )
    p.add_argument(
        "--update-baseline",
        action="store_true",
        help="regenerate check_complexity.allow.yaml from the current tree",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(Path(args.config) if args.config else None)

    if args.update_baseline:
        return update_baseline(cfg)

    targets = args.target or list(cfg["default_targets"])
    allow = _common.load_allowlist(DEFAULT_ALLOWLIST)
    findings = scan(targets, cfg, allow)
    summary = summarize(findings, int(cfg["max_complexity"]))

    out_format = "json" if args.json_alias else args.format
    if out_format == "json":
        text = _common.emit_json(
            CHECKER_NAME, SCHEMA_VERSION, targets, summary, findings
        )
    else:
        text = render_markdown(targets, summary, findings)
    _common.write_output(text, args.output)

    if args.warning_only:
        return 0
    if args.fail_on_regression:
        return 1 if summary["new"] else 0
    # Advisory default (warning-mode-first, 009 §6): report but never block.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
