#!/usr/bin/env python3
"""Guard directory *placement & naming* policy — the slice ``readme_sync.py`` omits.

ARI's per-directory ``README.md`` gate (``scripts/readme_sync.py``) enforces that
every managed directory *enumerates* its files. It says nothing about whether a
file is in the *right place* or whether a directory has a policy-legal *name*.
This checker owns exactly that orthogonal dimension (subtask 028;
``docs/refactoring/009_quality_scripts_plan.md`` §5.4), and mutates nothing.

It grounds three rules in the LIVE tree (verified 2026-07-02):

  * **Rule A — the config trio.** Three real, confusable-but-distinct directories
    must stay separated and correctly named:
      - ``ari-core/ari/config/``  — Python *locator* CODE (``finder.py`` +
        ``__init__.py`` Pydantic models + ``auto_config()``);
      - ``ari-core/ari/configs/`` — packaged default DATA + loader
        (``defaults.yaml``, ``model_prices.yaml``, ``_loader.py``);
      - ``ari-core/config/``      — shipped rubric/profile/workflow DATA
        (``default.yaml``, ``workflow.yaml``, ``profiles/``, ``reviewer_rubrics/``).
    Rule A asserts each exists with its expected file *kind* and marker files, and
    that NO fourth config-family sibling (a ``config``/``configs`` collision) or a
    ``sonfig*`` directory is ever introduced. **``sonfigs/`` does not exist**
    anywhere in the repo (``find -iname '*sonfig*'`` returns only the doc filename
    ``docs/refactoring/subtasks/003_consolidate_config_configs_sonfigs.md``, never a
    directory); the recurring "config/configs/sonfigs" phrasing in upstream prompts
    is a typo. Rule A turns that myth into a machine-checked invariant.

  * **Rule B — storage/legacy-dir bans (warning-level).** Flags a *new* top-level
    storage-family directory (``checkpoint(s)``/``experiment(s)``/``staging``/
    ``workspace(s)``/``run(s)``) outside the known set (root ``checkpoints/`` +
    ``workspace/{checkpoints,experiments,staging}/``), so a third divergent run-dir
    home cannot appear silently before the 005 consolidation lands.

  * **Rule C — forbidden TRACKED artifacts.** Over the ``git ls-files`` universe
    (NOT the working tree), flags a tracked build artifact
    (``node_modules``/``.venv``/``dist``/``build``/``__pycache__``/``*.egg-info``/
    ``*.pyc``). Scanning the tracked universe is deliberate: the on-disk
    ``ari-core/ari/viz/frontend/node_modules/`` is ``.gitignore``d and untracked
    (``git ls-files | grep -c node_modules`` -> 0), so a working-tree scan would
    false-positive on it. Seeded from the clean current state (nothing tracked).

This checker only *guards*; it never moves, renames, merges, or deletes the trio
(that is subtask 003 / the ``005_directory_consolidation_plan.md`` chain) and never
edits a workflow (CI wiring is 047/032). It stays deterministic (design principle
P2): stdlib + PyYAML only, no LLM, no network, stable sort. It reuses the shared
``scripts/quality/_common.py`` ``Finding`` record + §3 JSON envelope so subtask 031
``generate_quality_report.py`` can aggregate it.

Ships **warning-mode-first** (009 §6): the default and ``--warning-only`` postures
exit 0 on the current (clean) tree; a frozen ``<name>.allow.yaml`` keeps any known
offender out of a future ``--fail-on-regression`` / ``--strict`` ratchet.

Exit convention (matches ``scripts/docs/check_doc_sources.py``): ``0`` = clean,
default/``--warning-only`` posture, or ``--fail-on-regression`` with no net-new
debt; ``1`` = net-new (non-allowlisted) findings under ``--fail-on-regression`` /
``--strict``; ``2`` = usage/environment error (missing PyYAML, git unavailable on a
git target).

Design: docs/refactoring/009_quality_scripts_plan.md §5.4 (spec) + §3 (CLI/allowlist/
exit contract) + §8 (placement, ``scripts/quality/``, ``_common.py``);
docs/refactoring/005_directory_consolidation_plan.md §5.1/§8;
docs/refactoring/000_master_refactoring_plan.md:140 (ST-3-1);
docs/refactoring/subtasks/028_add_directory_policy_checker_script.md (§7 design,
§13 acceptance).
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# scripts/check_directory_policy.py -> parents[1] == repo root (beside
# readme_sync.py; NOT parents[2], which is the scripts/docs/ level).
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "quality"))

# _common imports PyYAML behind its own guard (SystemExit(2) if missing), so this
# checker needs no direct ``import yaml`` -- all YAML I/O goes through _common.
import _common  # noqa: E402  (scripts/quality/_common.py -- shared infrastructure)

CHECKER_NAME = "check_directory_policy"
SCHEMA_VERSION = 1

DEFAULT_CONFIG = REPO_ROOT / "scripts" / "quality" / "check_directory_policy.yaml"
DEFAULT_ALLOW = REPO_ROOT / "scripts" / "quality" / "check_directory_policy.allow.yaml"

# Built-in policy -- every key is overridable via the YAML config so subtask 003's
# landed layout (or a later collision-ban) can be re-encoded without a code edit.
DEFAULT_RULES: dict = {
    # Rule A -- the three canonical config-trio directories + their expected role.
    # ``require_kind``: "py" -> must hold a tracked .py; "data" -> must hold a
    # tracked .yaml/.yml/.json. ``markers``: files that must be present (grounding
    # the role in the LIVE trio).
    "config_trio": [
        {
            "path": "ari-core/ari/config",
            "role": "python-locator-code",
            "require_kind": "py",
            "markers": ["finder.py", "__init__.py"],
        },
        {
            "path": "ari-core/ari/configs",
            "role": "packaged-default-data-and-loader",
            "require_kind": "data",
            "markers": ["_loader.py", "defaults.yaml", "model_prices.yaml"],
        },
        {
            "path": "ari-core/config",
            "role": "rubric-profile-workflow-data",
            "require_kind": "data",
            "markers": ["default.yaml", "workflow.yaml"],
        },
    ],
    # Legal config-family directory basenames (case-insensitive). Anything else in
    # the family under a scan parent is an unexpected collision.
    "config_family_names": ["config", "configs"],
    # Parents (posix, "" == repo root) directly under which a config-family
    # collision could appear -- exactly the parents of the three canonical dirs.
    "config_scan_parents": ["", "ari-core", "ari-core/ari"],
    # Globs for directory basenames banned ANYWHERE (the sonfigs phantom).
    "banned_dir_globs": ["sonfig", "sonfigs", "sonfig*"],
    # Rule B -- storage-family basenames + the known-legal allowlist (top-level).
    "storage_family_names": [
        "checkpoint", "checkpoints", "experiment", "experiments",
        "staging", "workspace", "workspaces", "run", "runs",
    ],
    "storage_allowlist": ["checkpoints", "workspace", "experiments", "staging"],
    # Rule C -- forbidden tracked build-artifact directory basenames + suffixes.
    "forbidden_artifact_dirs": [
        "node_modules", ".venv", "venv", "dist", "build", "__pycache__",
    ],
    "forbidden_artifact_dir_suffixes": [".egg-info"],
    "forbidden_artifact_file_suffixes": [".pyc", ".pyo"],
    # Directory basenames skipped by the filesystem-walk fallback (non-git target).
    "walk_skip_dirs": [".git", "__pycache__", "node_modules", ".venv"],
}

_DATA_SUFFIXES = (".yaml", ".yml", ".json")


@dataclass
class RawFinding:
    """A policy violation before allowlist resolution / envelope shaping."""

    id: str
    severity: str  # "error" | "warning"
    file: str
    kind: str  # "config-trio" | "config-collision" | "banned-dir" | "storage" | "artifact"
    message: str


# ── tracked-universe / filesystem collection ────────────────────────────────


def git_tracked_files(target: Path) -> list[str] | None:
    """Return target-relative posix paths of tracked files, or ``None``.

    ``None`` means ``target`` is not inside a git work tree (or git is absent) --
    the caller then falls back to a filesystem walk. Rule C's "tracked universe"
    semantics (so ``.gitignore``d on-disk ``node_modules/`` is invisible) depend on
    this git-first path being used for the real repo.
    """
    try:
        inside = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True,
        )
    except FileNotFoundError:  # pragma: no cover - git absent
        return None
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(target), "ls-files"],
            capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:  # pragma: no cover - env guard
        return None
    return [ln for ln in out.splitlines() if ln.strip()]


def walk_files(target: Path, skip_dirs: set[str]) -> list[str]:
    """Filesystem-walk fallback for a non-git ``--target`` (e.g. a scratch tree)."""
    files: list[str] = []
    for root, dirs, names in os.walk(target):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for name in names:
            rel = Path(root, name).relative_to(target).as_posix()
            files.append(rel)
    return files


def collect_files(target: Path, skip_dirs: set[str]) -> tuple[list[str], bool]:
    """Return ``(rel_posix_files, from_git)`` for ``target``.

    ``from_git`` is ``True`` when the tracked universe was used (Rule C is then
    authoritative about tracked artifacts); ``False`` on the walk fallback.
    """
    tracked = git_tracked_files(target)
    if tracked is not None:
        return sorted(tracked), True
    return sorted(walk_files(target, skip_dirs)), False


def derive_dirs(files: list[str]) -> set[str]:
    """Every directory (posix) implied by the file list, plus the root ``""``."""
    dirs: set[str] = {""}
    for f in files:
        parts = f.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
    return dirs


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _files_under(files: list[str], dir_path: str) -> list[str]:
    prefix = dir_path + "/" if dir_path else ""
    return [f for f in files if f.startswith(prefix)]


# ── rules ────────────────────────────────────────────────────────────────────


def _matches_banned(name: str, globs: list[str]) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatch(low, g.lower()) for g in globs)


def check_config_trio(
    files: list[str], dirs: set[str], rules: dict
) -> list[RawFinding]:
    """Rule A -- trio existence/role/markers + config-family & sonfigs collisions."""
    findings: list[RawFinding] = []
    canonical = {entry["path"] for entry in rules["config_trio"]}

    # A.1 -- each canonical dir exists, holds its kind, and has its markers.
    for entry in rules["config_trio"]:
        path = entry["path"]
        under = _files_under(files, path)
        if path not in dirs and not under:
            findings.append(RawFinding(
                id=f"trio-missing:{path}", severity="error", file=path,
                kind="config-trio",
                message=(f"canonical config-trio dir '{path}' "
                         f"({entry['role']}) is missing"),
            ))
            continue
        want = entry.get("require_kind")
        if want == "py" and not any(f.endswith(".py") for f in under):
            findings.append(RawFinding(
                id=f"trio-kind:{path}", severity="error", file=path,
                kind="config-trio",
                message=(f"config-trio dir '{path}' must hold Python code "
                         f"(.py) for role '{entry['role']}'"),
            ))
        elif want == "data" and not any(
            f.endswith(_DATA_SUFFIXES) for f in under
        ):
            findings.append(RawFinding(
                id=f"trio-kind:{path}", severity="error", file=path,
                kind="config-trio",
                message=(f"config-trio dir '{path}' must hold data "
                         f"(.yaml/.yml/.json) for role '{entry['role']}'"),
            ))
        for marker in entry.get("markers", []):
            if f"{path}/{marker}" not in files:
                findings.append(RawFinding(
                    id=f"trio-marker:{path}::{marker}", severity="error",
                    file=f"{path}/{marker}", kind="config-trio",
                    message=(f"config-trio dir '{path}' is missing marker "
                             f"file '{marker}' (role '{entry['role']}')"),
                ))

    # A.2 -- no config-family collision under a scan parent; no sonfig* anywhere.
    scan_parents = set(rules["config_scan_parents"])
    family = {n.lower() for n in rules["config_family_names"]}
    banned = rules["banned_dir_globs"]
    for d in sorted(dirs):
        if not d:
            continue
        base = _basename(d)
        if _matches_banned(base, banned):
            findings.append(RawFinding(
                id=f"banned-dir:{d}", severity="error", file=d,
                kind="banned-dir",
                message=(f"banned directory '{d}': 'sonfigs' is a phantom that "
                         "must never exist (the real trio is config/configs)"),
            ))
            continue
        if base.lower() in family and _parent(d) in scan_parents \
                and d not in canonical:
            findings.append(RawFinding(
                id=f"config-collision:{d}", severity="error", file=d,
                kind="config-collision",
                message=(f"unexpected config-family dir '{d}' collides with the "
                         "canonical trio (config=code / configs=data / "
                         "config=rubric-data); do not add a fourth"),
            ))
    return findings


def check_storage_dirs(target: Path, rules: dict) -> list[RawFinding]:
    """Rule B -- a new top-level storage-family dir outside the known set (warn).

    Scans on-disk top-level directories (run/checkpoint dirs are ``.gitignore``d,
    so a tracked-only scan would never see them). Conservative: warning-level.
    """
    findings: list[RawFinding] = []
    if not target.is_dir():
        return findings
    family = {n.lower() for n in rules["storage_family_names"]}
    allow = {n.lower() for n in rules["storage_allowlist"]}
    for child in sorted(target.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        base = child.name
        if base.lower() in family and base.lower() not in allow:
            findings.append(RawFinding(
                id=f"storage:{base}", severity="warning", file=base,
                kind="storage",
                message=(f"new top-level storage-family dir '{base}/' outside the "
                         "known set (checkpoints/workspace/experiments/staging); "
                         "consolidation home is subtask 005"),
            ))
    return findings


def check_tracked_artifacts(
    files: list[str], from_git: bool, rules: dict
) -> list[RawFinding]:
    """Rule C -- a TRACKED build artifact (node_modules/.venv/dist/... /*.pyc)."""
    findings: list[RawFinding] = []
    art_dirs = {n.lower() for n in rules["forbidden_artifact_dirs"]}
    dir_suffixes = tuple(rules["forbidden_artifact_dir_suffixes"])
    file_suffixes = tuple(rules["forbidden_artifact_file_suffixes"])
    seen: set[str] = set()
    for f in files:
        segments = f.split("/")
        hit_dir: str | None = None
        for i, seg in enumerate(segments[:-1]):
            low = seg.lower()
            if low in art_dirs or low.endswith(dir_suffixes):
                hit_dir = "/".join(segments[: i + 1])
                break
        if hit_dir is not None:
            if hit_dir in seen:
                continue
            seen.add(hit_dir)
            findings.append(RawFinding(
                id=f"artifact:{hit_dir}", severity="error", file=hit_dir,
                kind="artifact",
                message=(f"forbidden build artifact '{hit_dir}/' is git-tracked "
                         "(should be .gitignored, not committed)"),
            ))
            continue
        if f.endswith(file_suffixes):
            findings.append(RawFinding(
                id=f"artifact:{f}", severity="error", file=f, kind="artifact",
                message=f"forbidden compiled artifact '{f}' is git-tracked",
            ))
    if not from_git:
        # A walk fallback (non-git target) cannot honor .gitignore; annotate so a
        # consumer does not treat Rule C as authoritative there.
        for fnd in findings:
            fnd.message += " (walk fallback: .gitignore not applied)"
    return findings


# ── config / allowlist / envelope ───────────────────────────────────────────


def load_config(path: Path) -> dict:
    rules = json.loads(json.dumps(DEFAULT_RULES))  # deep copy of defaults
    if path and path.exists():
        data = _common.load_yaml(path)
        for key in DEFAULT_RULES:
            if key in data:
                rules[key] = data[key]
    return rules


def load_allow(path: Path | None) -> tuple[set[str], dict[str, str]]:
    ids: set[str] = set()
    notes: dict[str, str] = {}
    if path is None or not path.exists():
        return ids, notes
    data = _common.load_yaml(path)
    for entry in data.get("known", []) or []:
        if isinstance(entry, str):
            ids.add(entry)
        elif isinstance(entry, dict) and entry.get("id"):
            ids.add(entry["id"])
            if entry.get("note"):
                notes[entry["id"]] = entry["note"]
    return ids, notes


def to_findings(raws: list[RawFinding], allow_ids: set[str]) -> list[_common.Finding]:
    findings = [
        _common.Finding(
            id=r.id, severity=r.severity, file=r.file, line=0, kind=r.kind,
            message=r.message, allowlisted=r.id in allow_ids,
        )
        for r in raws
    ]
    findings.sort(key=lambda f: (f.kind, f.severity, f.id))
    return findings


def build_report(target_rel: str, findings: list[_common.Finding]) -> dict:
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    known = sum(1 for f in findings if f.allowlisted)
    new = sum(1 for f in findings if not f.allowlisted)
    by_kind: dict[str, int] = {}
    for f in findings:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    summary = {
        "errors": errors,
        "warnings": warnings,
        "known": known,
        "new": new,
        "total": len(findings),
        "by_kind": by_kind,
    }
    return json.loads(_common.emit_json(
        CHECKER_NAME, SCHEMA_VERSION, target_rel, summary, findings,
    ))


def render_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        f"# {CHECKER_NAME}",
        "",
        f"Target: `{report['target']}`",
        "",
        f"- errors: **{s['errors']}**  ·  warnings: {s['warnings']}",
        f"- known (allowlisted): {s['known']}  ·  new: **{s['new']}**",
        "",
    ]
    if not report["findings"]:
        lines.append(
            "Directory placement/naming policy is satisfied "
            "(config trio intact; no `sonfigs/`; no forbidden tracked artifacts)."
        )
        return "\n".join(lines) + "\n"
    headers = ["Kind", "Severity", "Path", "Status", "Message"]
    rows = []
    for f in report["findings"]:
        status = "known" if f["allowlisted"] else "**new**"
        rows.append([
            f["kind"], f["severity"], f"`{f['file']}`", status, f["message"],
        ])
    lines.append(_common.render_markdown_table(headers, rows))
    return "\n".join(lines) + "\n"


# ── cli ──────────────────────────────────────────────────────────────────────


def _target_str(target: Path) -> str:
    try:
        rel = target.resolve().relative_to(REPO_ROOT).as_posix()
        return rel or "."
    except ValueError:
        return str(target)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--target", default=str(REPO_ROOT),
                    help="restrict the scan subtree (default: repo root)")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG),
                    help="policy config YAML (default: scripts/quality/%(prog)s.yaml)")
    ap.add_argument("--allow", default=str(DEFAULT_ALLOW),
                    help="frozen allowlist YAML (default: scripts/quality/...allow.yaml)")
    ap.add_argument("--output", default=None,
                    help="write the report to a file instead of stdout")
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown",
                    help="report format (default: markdown)")
    ap.add_argument("--json", action="store_true", help="alias for --format json")
    ap.add_argument("--warning-only", action="store_true",
                    help="force exit 0 regardless of findings (default posture)")
    ap.add_argument("--fail-on-regression", action="store_true",
                    help="exit 1 only on findings not in the allowlist (ratchet)")
    ap.add_argument("--strict", action="store_true",
                    help="alias for --fail-on-regression (subtask 028 §7.7)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    rules = load_config(Path(args.config))
    allow_ids, _notes = load_allow(Path(args.allow) if args.allow else None)
    target = Path(args.target).resolve()

    skip_dirs = set(rules["walk_skip_dirs"])
    files, from_git = collect_files(target, skip_dirs)
    dirs = derive_dirs(files)

    raws: list[RawFinding] = []
    raws += check_config_trio(files, dirs, rules)
    raws += check_storage_dirs(target, rules)
    raws += check_tracked_artifacts(files, from_git, rules)

    findings = to_findings(raws, allow_ids)
    report = build_report(_target_str(target), findings)

    fmt = "json" if args.json else args.format
    text = json.dumps(report, indent=2, ensure_ascii=False) if fmt == "json" \
        else render_markdown(report)
    _common.write_output(text.rstrip("\n"), args.output)

    if args.warning_only:
        return 0
    if args.fail_on_regression or args.strict:
        return 1 if any(not f.allowlisted for f in findings) else 0
    # Default posture is warning-mode-first (028 §7.7 / 009 §6): report, exit 0.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
