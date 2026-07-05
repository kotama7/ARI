"""Per-node structured self-report (`node_report.json`).

Each BFTS node, on completion (`mark_success` / `mark_failed`), writes a
structured `node_report.json` to its work_dir. The report is the canonical
substrate that downstream stages (`generate_ear`, `nodes_to_science_data`,
`bfts.expand`, viz) consume to make deterministic, auditable decisions about
"which nodes contribute to the published code/", "what changed across the
search trajectory", etc.

"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ari.paths import PathManager

logger = logging.getLogger(__name__)


SCHEMA_VERSION = 1

# File patterns that should never be considered "source files" produced by a
# node. These are agent / shell side-effects, build outputs, or ARI internals
# that pollute files_changed and confuse downstream selection.
_FILES_CHANGED_BLOCKLIST_NAMES: frozenset[str] = frozenset({
    "node_report.json",
    "memory_access.jsonl",
    "viz_access.jsonl",
    "cost_trace.jsonl",
    "nodes_tree.json",
    "tree.json",
    "bfts_tree.json",
    "science_data.json",
    "raw_metrics.json",
    "eval_scores.json",
    ".DS_Store",
    "Thumbs.db",
})

_FILES_CHANGED_BLOCKLIST_DIRS: frozenset[str] = frozenset({
    ".git",
    ".cache",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    ".ipynb_checkpoints",
    ".venv",
    "venv",
    "build",
    "dist",
    "target",
    ".tox",
    ".mypy_cache",
    ".ruff_cache",
})

_BUILD_KEYWORDS = (
    "g++", "gcc", "clang", "clang++",
    "make ", "cmake", "ninja",
    "cargo build", "cargo install",
    "go build",
    "rustc",
    "javac",
    "scalac",
    "kotlinc",
    "nvcc",
    "ifort", "gfortran",
    "python -m pip", "pip install", "pip3 install",
    "uv pip",
    "conda install",
    "npm install", "yarn install", "pnpm install",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path, *, chunk_size: int = 65536) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _is_blocklisted(path: Path, *, root: Path) -> bool:
    """Return True if *path* (relative to *root*) is in a blocked dir or name."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    if rel.name in _FILES_CHANGED_BLOCKLIST_NAMES:
        return True
    if PathManager.is_meta_file(rel.name):
        return True
    for part in rel.parts[:-1]:
        if part in _FILES_CHANGED_BLOCKLIST_DIRS:
            return True
    return False


def _walk_files(root: Path) -> Iterable[Path]:
    """Yield regular files under *root*, skipping blocklisted dirs/names."""
    if not root.exists() or not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        # In-place prune blocklisted dirs so we don't descend into them.
        dirnames[:] = [d for d in dirnames if d not in _FILES_CHANGED_BLOCKLIST_DIRS]
        d = Path(dirpath)
        for fn in filenames:
            p = d / fn
            if _is_blocklisted(p, root=root):
                continue
            yield p


# ── files_changed ─────────────────────────────────────────────────────────

def compute_files_changed(
    parent_work_dir: Path | None,
    child_work_dir: Path,
) -> dict:
    """Compute the {added, modified, deleted, inherited_unchanged} sets.

    Comparison is by relative path within the work_dir tree, with sha256 used
    to distinguish modified vs inherited_unchanged. Blocklisted files
    (META_FILES, build caches, node_report.json itself, etc.) are ignored.

    If *parent_work_dir* is None or missing on disk, all child files are
    treated as `added`.
    """
    added: list[dict] = []
    modified: list[dict] = []
    deleted: list[str] = []
    inherited: list[dict] = []

    child_root = Path(child_work_dir)
    parent_root = Path(parent_work_dir) if parent_work_dir else None

    child_files: dict[str, Path] = {
        str(p.relative_to(child_root)): p for p in _walk_files(child_root)
    }
    parent_files: dict[str, Path] = (
        {str(p.relative_to(parent_root)): p for p in _walk_files(parent_root)}
        if parent_root and parent_root.exists()
        else {}
    )

    for rel, child_path in sorted(child_files.items()):
        try:
            child_sha = _sha256_file(child_path)
        except OSError:
            continue
        parent_path = parent_files.get(rel)
        if parent_path is None:
            added.append({"path": rel, "sha256": child_sha})
            continue
        try:
            parent_sha = _sha256_file(parent_path)
        except OSError:
            modified.append({"path": rel,
                             "sha256_before": "",
                             "sha256_after": child_sha})
            continue
        if parent_sha == child_sha:
            inherited.append({"path": rel, "sha256": child_sha})
        else:
            modified.append({"path": rel,
                             "sha256_before": parent_sha,
                             "sha256_after": child_sha})

    for rel in sorted(parent_files):
        if rel not in child_files:
            deleted.append(rel)

    return {
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "inherited_unchanged": inherited,
    }


# ── build/run command extraction ──────────────────────────────────────────

def _read_text_safe(path: Path, *, max_bytes: int = 65536) -> str:
    try:
        with path.open("rb") as fh:
            data = fh.read(max_bytes + 1)
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _looks_like_build_line(line: str) -> bool:
    s = line.strip()
    if not s or s.startswith("#") or s.startswith("//"):
        return False
    return any(kw in s for kw in _BUILD_KEYWORDS)


def _looks_like_shebang_or_directive(line: str) -> bool:
    s = line.strip()
    if (
        not s
        or s.startswith("#")
        or s.startswith("set ")
        or s.startswith("export ")
        or s.startswith("source ")
        or s.startswith("cd ")
        or s.startswith("module ")
        or s.startswith("ulimit ")
        or s.startswith("function ")
        or s.startswith("alias ")
        or s.startswith("shopt ")
    ):
        return True
    # Bare variable assignment, e.g. ``CXX=${CXX:-g++}``, ``CXXFLAGS="..."``.
    # Without this, lines that merely set up env vars but happen to contain
    # build keywords like ``g++`` get mis-classified as build_command and
    # the actual compile + execute lines are skipped (Bug 3b).
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", s):
        return True
    return False


def extract_build_run_commands(work_dir: Path) -> tuple[str, str]:
    """Best-effort extract a (build_command, run_command) pair from work_dir.

    Searches `run_job.sh`, `Makefile`/`makefile`, then any other `*.sh` file.
    Returns ("", "") if nothing usable is found.
    """
    work_dir = Path(work_dir)
    if not work_dir.exists():
        return ("", "")

    candidates: list[Path] = []
    for name in ("run_job.sh", "run.sh", "Makefile", "makefile", "GNUmakefile"):
        p = work_dir / name
        if p.is_file():
            candidates.append(p)
    # Plus any other top-level shell scripts.
    for p in sorted(work_dir.glob("*.sh")):
        if p not in candidates:
            candidates.append(p)

    build = ""
    run = ""
    for path in candidates:
        text = _read_text_safe(path)
        if not text:
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if _looks_like_shebang_or_directive(line):
                continue
            if not build and _looks_like_build_line(line):
                build = line
                continue
            # The first non-build, non-directive command becomes the run line.
            if build and not run and line and not _looks_like_build_line(line):
                # Avoid trivial sbatch / srun wrappers being conflated; we keep them.
                run = line
                break
            if not build and not run and line and not _looks_like_build_line(line):
                # No build keyword present in this file — treat line as run.
                run = line
                # Keep scanning in case a later file has a build line.
        if build and run:
            break

    return (build, run)


# ── artifact role classification ──────────────────────────────────────────

_DATA_OUTPUT_EXTS = {
    ".csv", ".tsv", ".parquet", ".json", ".yaml", ".yml", ".toml",
    ".npy", ".npz", ".h5", ".hdf5", ".pkl",
}
_LOG_EXTS = {".txt", ".log"}
_FIGURE_EXTS = {".png", ".pdf", ".svg", ".jpg", ".jpeg"}
_BINARY_EXTS = {".bin", ".exe", ".so", ".dylib", ".dll"}

_INTERNAL_JSON_NAMES = {
    "node_report.json", "tree.json", "nodes_tree.json", "science_data.json",
    "raw_metrics.json", "eval_scores.json", "results.json", "meta.json",
    "launch_config.json", "evaluation_criteria.json",
    # Prompt-provenance rollup (subtask 044) — ARI internal, not a data output.
    "prompt_versions.json",
}


def classify_artifact_role(filename: str, work_dir: Path | None = None) -> str:
    """Classify *filename* into one of:
    "data_output" | "log" | "binary" | "figure" | "unknown".
    """
    name = Path(filename).name
    suffix = Path(filename).suffix.lower()

    if suffix in _FIGURE_EXTS:
        return "figure"
    if name in _INTERNAL_JSON_NAMES:
        # ARI internal JSON, not a publishable data output.
        return "unknown"
    if name.startswith("slurm-") and (name.endswith(".out") or name.endswith(".err")):
        return "log"
    if suffix in _LOG_EXTS:
        return "log"
    if suffix in _DATA_OUTPUT_EXTS:
        return "data_output"
    if suffix in _BINARY_EXTS:
        return "binary"
    if suffix == "":
        # No extension — check executable bit if work_dir is given.
        if work_dir is not None:
            full = Path(work_dir) / filename
            try:
                if full.is_file() and os.access(full, os.X_OK):
                    return "binary"
            except OSError:
                pass
    return "unknown"


# ── self_assessment derivation ────────────────────────────────────────────

def derive_self_assessment_from_evaluator(
    eval_result: dict | None,
    node: Any,
) -> tuple[dict, list[str]]:
    """Map evaluator's per-axis rationales into self_assessment + next_steps.

    Returns (self_assessment, next_steps_hints).

    - axis_score < 0.4 → concerns
    - 0.4 <= axis_score < 0.7 → next_steps_hints
    - axis_score >= 0.7 → not surfaced (high-rated axes aren't "improve me")
    """
    succeeded = bool(getattr(node, "has_real_data", False))
    headline = ""
    concerns: list[str] = []
    next_steps: list[str] = []

    if eval_result:
        rationales = eval_result.get("axis_rationales") or {}
        axis_scores = (
            eval_result.get("axis_scores")
            or eval_result.get("_axis_scores")
            or {}
        )
        for axis, rationale in rationales.items():
            if not rationale:
                continue
            score = axis_scores.get(axis)
            if not isinstance(score, (int, float)):
                continue
            label = f"{axis}: {rationale}"
            if score < 0.4:
                concerns.append(label)
            elif score < 0.7:
                next_steps.append(label)

        reason = eval_result.get("reason") or ""
        sci = eval_result.get("scientific_score")
        if reason:
            headline = reason.strip()
        if sci is not None and headline:
            headline = f"{headline} (scientific_score={sci:.2f})"

    if not headline:
        headline = (getattr(node, "eval_summary", "") or "").strip()

    return (
        {
            "succeeded": succeeded,
            "headline": headline,
            "concerns": concerns,
        },
        next_steps,
    )


# ── artifact path normalisation ──────────────────────────────────────────

def _artifact_to_record(artifact: Any, work_dir: Path) -> dict | None:
    """Normalise a heterogeneous artifact entry to a node_report artifact record."""
    if isinstance(artifact, str):
        # Path-string artifact — common in react_driver.
        try:
            p = Path(artifact)
            name = p.name
        except Exception:
            return None
        full = work_dir / name if not p.is_absolute() else p
        rec: dict[str, Any] = {
            "filename": name,
            "role": classify_artifact_role(name, work_dir),
        }
        try:
            if full.is_file():
                rec["size"] = full.stat().st_size
                rec["sha256"] = _sha256_file(full)
        except OSError:
            pass
        return rec
    if isinstance(artifact, dict):
        # Existing dict shape from result.artifacts (may have type/stdout/path).
        name = (
            artifact.get("filename")
            or artifact.get("name")
            or Path(str(artifact.get("path", ""))).name
            or ""
        )
        if not name:
            # Inline result blob with no filename — represent as an unknown
            # placeholder so downstream code sees something.
            return {
                "filename": str(artifact.get("type", "result")),
                "role": "unknown",
            }
        rec = {
            "filename": name,
            "role": classify_artifact_role(name, work_dir),
        }
        full = work_dir / name
        try:
            if full.is_file():
                rec["size"] = full.stat().st_size
                rec["sha256"] = _sha256_file(full)
        except OSError:
            pass
        return rec
    return None


# ── trace_log summarisation ──────────────────────────────────────────────

def _trace_log_summary(trace_log: list[str] | None) -> str:
    if not trace_log:
        return ""
    n = len(trace_log)
    return f"ReAct loop {n} steps. Full log in tree.json::trace_log."


# ── public builder ────────────────────────────────────────────────────────

@dataclass
class NodeReportInputs:
    """Lightweight bundle of everything build_node_report needs.

    We avoid coupling to the live ``Node`` dataclass to stay test-friendly.
    """
    node_id: str
    parent_id: str | None
    ancestor_ids: list[str]
    label: str
    raw_label: str
    depth: int
    status: str
    started_at: str
    completed_at: str
    original_direction: str | None
    metrics: dict
    artifacts: list
    eval_summary: str | None
    trace_log: list[str]


def build_node_report(
    *,
    node: Any,
    work_dir: Path,
    parent_work_dir: Path | None,
    eval_result: dict | None = None,
    delta_vs_parent: str | None = None,
    what_was_done: str | None = None,
    migration_source: str = "fresh",
) -> dict:
    """Construct a node_report dict for *node* by gathering everything we know.

    *node* may be either a live ``Node`` instance or a duck-typed object with
    matching attributes. The function never raises on missing fields; absent
    data becomes empty/null in the returned dict so the schema remains valid.
    """
    work_dir = Path(work_dir)

    label_value = getattr(node, "label", "")
    if hasattr(label_value, "value"):
        label_value = label_value.value
    label_value = str(label_value or "other")

    status_value = getattr(node, "status", "")
    if hasattr(status_value, "value"):
        status_value = status_value.value
    status_value = str(status_value or "")

    files_changed = compute_files_changed(parent_work_dir, work_dir)

    self_assessment, next_steps = derive_self_assessment_from_evaluator(
        eval_result or {}, node,
    )

    artifacts_in = list(getattr(node, "artifacts", []) or [])
    artifacts_out: list[dict] = []
    for a in artifacts_in:
        rec = _artifact_to_record(a, work_dir)
        if rec is not None:
            artifacts_out.append(rec)

    build_cmd, run_cmd = extract_build_run_commands(work_dir)

    # Run-environment capture: where did this node's tool calls actually run?
    # Populated by ari.agent.run_env (writes _run_env.json from inside the
    # executing process — slurm_submit on the compute node, run_bash locally).
    # Empty dict means no skill captured anything (older runs, dry-run, etc.).
    try:
        from ari.agent.run_env import read_run_env as _read_run_env
        run_env = _read_run_env(work_dir) or {}
    except Exception:
        run_env = {}

    metrics = dict(getattr(node, "metrics", {}) or {})
    if eval_result:
        if "scientific_score" in eval_result and "_scientific_score" not in metrics:
            metrics["_scientific_score"] = eval_result["scientific_score"]
        axis_scores = eval_result.get("axis_scores") or eval_result.get("_axis_scores")
        if axis_scores and "_axis_scores" not in metrics:
            metrics["_axis_scores"] = dict(axis_scores)

    evaluator_reason = ""
    if eval_result:
        evaluator_reason = (eval_result.get("reason") or "").strip()
    if not evaluator_reason:
        evaluator_reason = (getattr(node, "eval_summary", "") or "").strip()

    started_at = getattr(node, "created_at", "") or ""
    completed_at = getattr(node, "completed_at", "") or _utc_now_iso()

    report = {
        "schema_version": SCHEMA_VERSION,
        "node_id": getattr(node, "id", ""),
        "parent_id": getattr(node, "parent_id", None),
        "ancestor_ids": list(getattr(node, "ancestor_ids", []) or []),
        "label": label_value,
        "raw_label": getattr(node, "raw_label", "") or "",
        "depth": int(getattr(node, "depth", 0) or 0),
        "status": status_value,
        "started_at": started_at,
        "completed_at": completed_at,
        "original_direction": getattr(node, "original_direction", None)
            or (eval_result.get("original_direction") if eval_result else None),
        "files_changed": files_changed,
        "what_was_done": what_was_done or "",
        "delta_vs_parent": delta_vs_parent or "",
        "metrics": metrics,
        "self_assessment": self_assessment,
        "next_steps_hints": next_steps,
        "build_command": build_cmd,
        "run_command": run_cmd,
        "artifacts": artifacts_out,
        "evaluator_reason": evaluator_reason,
        "trace_log_summary": _trace_log_summary(getattr(node, "trace_log", None)),
        "migration_source": migration_source,
        # Compute-resource provenance (PR-resource-capture). Empty when no
        # tool wrote `_run_env.json` (legacy runs, dry-run, evaluation-only).
        "executor": run_env.get("executor", "") or "",
        "hostname": run_env.get("hostname", "") or "",
        "slurm_job_id": run_env.get("slurm_job_id", "") or "",
        "slurm_partition": run_env.get("slurm_partition", "") or "",
        "slurm_nodelist": run_env.get("slurm_nodelist", "") or "",
        "cpu_info": dict(run_env.get("cpu_info") or {}),
        "mem_total_kb": int(run_env.get("mem_total_kb") or 0) or 0,
        "compilers": dict(run_env.get("compilers") or {}),
    }
    return report


def write_node_report(
    *,
    node: Any,
    work_dir: Path,
    parent_work_dir: Path | None,
    eval_result: dict | None = None,
    delta_vs_parent: str | None = None,
    what_was_done: str | None = None,
    migration_source: str = "fresh",
) -> Path:
    """Build and write `node_report.json` into *work_dir*.

    Returns the report path. Errors during build are caught and logged so we
    never block the calling pipeline; the function still attempts to write a
    minimal stub if possible.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = work_dir / "node_report.json"
    try:
        report = build_node_report(
            node=node,
            work_dir=work_dir,
            parent_work_dir=parent_work_dir,
            eval_result=eval_result,
            delta_vs_parent=delta_vs_parent,
            what_was_done=what_was_done,
            migration_source=migration_source,
        )
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        # Update the node's pointer field if it has one.
        try:
            setattr(node, "node_report_path", str(out_path.relative_to(work_dir.parent.parent))
                    if work_dir.parent.parent.exists() else "node_report.json")
        except Exception:
            pass
        return out_path
    except Exception as exc:  # noqa: BLE001 — we promise not to block the caller.
        logger.warning("node_report: build failed for %s: %s",
                       getattr(node, "id", "<unknown>"), exc)
        try:
            out_path.write_text(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "node_id": getattr(node, "id", ""),
                "status": "error",
                "error": str(exc),
                "migration_source": migration_source,
                "files_changed": {"added": [], "modified": [], "deleted": [], "inherited_unchanged": []},
                "metrics": {},
                "artifacts": [],
                "depth": int(getattr(node, "depth", 0) or 0),
                "label": "other",
            }, indent=2))
        except Exception:
            pass
        return out_path


# Phase 3E (REFACTORING.md §3 + orchestrator/REFACTORING.md §2 Step 1)
# moved this module into a package; ``reconstruct_report_from_legacy``
# is re-exported from ``ari.orchestrator.node_report.__init__`` and the
# ``legacy_reconstruct`` shim sub-module — importing it here would
# create a cycle (the migrations module pulls helpers from this file).
