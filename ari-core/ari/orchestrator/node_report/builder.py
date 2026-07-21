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
    # node scope: *root* is the node's work_dir (see the caller), so the
    # agent's results.json / *.log belong in files_changed.
    if PathManager.is_meta_file(rel.name, scope="node"):
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
    deleted: list[dict] = []
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
            deleted.append({"path": rel})

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
    # Bare variable assignment, e.g. ``CXX=${CXX:-g++}``, ``CXXFLAGS="..."``, and
    # Makefile-style ``CC ?= cc`` / ``CFLAGS := ...`` / ``X += ...``. Without this,
    # such lines (which merely set env/Make vars) get mis-classified as the build
    # or run command and the actual command is skipped (Bug 3b / the ``CC ?= cc``
    # run_command bug).
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*[:?+]?=", s):
        return True
    return False


def _extract_from_makefile(text: str) -> tuple[str, str]:
    """Extract (build, run) as ``make <target>`` invocations from a Makefile.

    A Makefile is NOT a shell script: variable assignments (``CC ?= cc``),
    target headers (``candidate: dep``) and TAB-indented recipes are not
    standalone commands. We collect the phony/build targets and express build/run
    as ``make <target>`` — e.g. build ``make candidate``, run ``make check``.
    """
    targets: list[str] = []
    for raw in text.splitlines():
        if not raw or raw[0] in ("\t", " ", "#"):  # recipe / indented / comment
            continue
        # ``name:`` target header, but NOT ``name :=`` (a Make assignment).
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_.\-]*)\s*:(?!=)", raw)
        if m:
            t = m.group(1)
            if not t.startswith(".") and t not in targets:
                targets.append(t)
    if not targets:
        return ("", "")

    def _pick(prefs: tuple[str, ...]) -> str:
        for p in prefs:
            if p in targets:
                return p
        return ""

    build_t = _pick(("candidate", "all", "build")) or targets[0]
    run_t = _pick(("run", "check", "selftest"))
    build = f"make {build_t}" if build_t else ""
    run = f"make {run_t}" if run_t else ""
    return (build, run)


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
        # A Makefile is parsed structurally (targets -> ``make <target>``), not
        # line-by-line: its variable assignments and recipes are not commands.
        if path.name.lower() in ("makefile", "gnumakefile"):
            _mb, _mr = _extract_from_makefile(text)
            if not build and _mb:
                build = _mb
            if not run and _mr:
                run = _mr
            if build and run:
                break
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
            # Inline result blob (e.g. ``{"type":"result","stdout":...}``) — this
            # is captured stdout, NOT a produced file. Drop it: ``artifacts`` must
            # list only real on-disk files (the stdout lives in what_was_done /
            # evaluator_reason). Without this, every node showed a phantom
            # ``{"filename":"result","role":"unknown"}`` with no backing file.
            return None
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
    # Attach the agent's own light per-file explanation (finish JSON ``file_notes``)
    # to each changed entry, matched by path. Best-effort: files the agent did not
    # note simply carry no ``note`` (the diff itself is authoritative).
    _file_notes = getattr(node, "file_notes", None) or {}
    if _file_notes:
        for _bucket in ("added", "modified", "deleted"):
            for _entry in files_changed.get(_bucket, []):
                _note = _file_notes.get(_entry.get("path"))
                if isinstance(_note, str) and _note.strip():
                    _entry["note"] = _note.strip()

    self_assessment, next_steps = derive_self_assessment_from_evaluator(
        eval_result or {}, node,
    )
    # Prefer the agent's OWN self-reviewed next steps (LLM self-review). Under the
    # deterministic scorer the evaluator emits no graded axes, so the axis-derived
    # ``next_steps`` above is empty; the agent's self-review is the real source.
    _agent_next = [str(s).strip() for s in (getattr(node, "agent_next_steps", []) or []) if str(s).strip()]
    if _agent_next:
        next_steps = _agent_next
    # self_assessment is the node's OWN assessment (LLM self-review): headline =
    # the agent's summary; concerns = the agent's self-flagged caveats. ``succeeded``
    # stays the deterministic has_real_data ground truth (objective, non-gameable).
    # The evaluator's terse reason ("ok") lives in ``evaluator_reason``, so we do not
    # duplicate it here as a misleading headline that contradicts succeeded.
    self_assessment["headline"] = (getattr(node, "agent_summary", "") or "").strip()
    _agent_concerns = [str(c).strip() for c in (getattr(node, "agent_concerns", []) or []) if str(c).strip()]
    if _agent_concerns:
        self_assessment["concerns"] = _agent_concerns

    artifacts_in = list(getattr(node, "artifacts", []) or [])
    artifacts_out: list[dict] = []
    for a in artifacts_in:
        rec = _artifact_to_record(a, work_dir)
        if rec is not None:
            artifacts_out.append(rec)

    # Auto-capture PRODUCED output files from the work_dir. The agent rarely
    # DECLARES its outputs, so ``artifacts`` was empty even when e.g.
    # ``selftest_out.txt`` / ``*.csv`` / plots existed on disk. Include only
    # produced-OUTPUT roles (data_output / log / figure) so scaffolding source
    # (.c/.h/Makefile/.md -> "unknown"), compiled binaries, ``.o`` build junk,
    # and ARI-internal JSON (node_report/results/... -> "unknown") are all
    # excluded. Top-level only (skips the uploads/ subdir); deduped against the
    # agent-declared list.
    _declared = {r.get("filename") for r in artifacts_out if isinstance(r, dict)}
    try:
        for _f in sorted(work_dir.iterdir()):
            if not _f.is_file():
                continue
            _nm = _f.name
            # Skip dot-files and ARI-internal ``_``-prefixed files (e.g.
            # _run_env.json) as well as declared/meta files. ``scope="node"``:
            # work_dir is this node's dir, so results.json / *.log here are the
            # agent's own outputs, not ARI metadata.
            if (_nm in _declared or _nm.startswith(".") or _nm.startswith("_")
                    or PathManager.is_meta_file(_nm, scope="node")):
                continue
            if classify_artifact_role(_nm, work_dir) not in (
                "data_output", "log", "figure"):
                continue
            _rec = {"filename": _nm,
                    "role": classify_artifact_role(_nm, work_dir)}
            try:
                _rec["size"] = _f.stat().st_size
                _rec["sha256"] = _sha256_file(_f)
            except OSError:
                pass
            artifacts_out.append(_rec)
            _declared.add(_nm)
    except OSError:
        pass

    build_cmd, run_cmd = extract_build_run_commands(work_dir)

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
        "depth": int(getattr(node, "depth", 0) or 0),
        "status": status_value,
        "started_at": started_at,
        "completed_at": completed_at,
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
    }
    # (1) label / raw_label / original_direction — ALWAYS emitted. An
    # ``ARI_REPORT_MINIMAL`` switch used to strip these from the report while the
    # label kept steering the search (NODE ROLE in the system prompt, the child's
    # task line, and diversity_bonus in node selection). Suppressing a LIVE variable
    # from the record does not make it inert — it only removes the evidence, which
    # is how a label confound survived an entire 4-arm study undetected (the
    # ABLATION share of children ran 0/1/3/4 across arms, invisible in the
    # deliverable). Remove a variable's influence by turning the FEATURE off
    # (``ARI_BFTS_NO_LABEL``); never hide a live one.
    # ONE switch governs the whole label feature. ``ARI_BFTS_NO_LABEL`` already
    # turns the label OFF at every use site (system-prompt role, child task line,
    # frontier selection); it now ALSO stops the label from being RECORDED here.
    # The old warning — "never hide a LIVE variable" — does not apply: under
    # NO_LABEL the label drives nothing, so it is an inert field, and recording an
    # inert tag only invited the confusion of "the feature is off yet the label
    # still shows up". No separate ARI_REPORT_MINIMAL is needed for this.
    from ari.agent.loop import labels_disabled as _labels_off
    if not _labels_off():
        report["label"] = label_value
        report["raw_label"] = getattr(node, "raw_label", "") or ""
        report["original_direction"] = getattr(node, "original_direction", None)
    # else: ARI_BFTS_NO_LABEL — the label feature is OFF, so the keys are OMITTED
    # ENTIRELY from the record (not merely emptied): "feature off" ⇒ "field
    # absent". All node_report consumers read these via .get(), so their absence
    # is safe.
    # (2) Compute-environment provenance — AGENT-AUTHORED, not auto-scraped. The
    # framework no longer reads _run_env.json and embeds machine info here (that
    # leaked the hostname/partition into the deliverable). Instead the agent,
    # having queried the real env via the `describe_environment` tool, records a
    # free-text note of the toolchain/hardware it used (grounded in tool output,
    # anti-fabrication — see loop.py `_ground_environment`). So the agent chooses
    # what to disclose; no hostname/partition is embedded automatically.
    _env = str(getattr(node, "agent_environment", "") or "").strip()
    if _env:
        report["environment"] = _env
    return report


def write_node_report(
    *,
    node: Any,
    work_dir: Path,
    parent_work_dir: Path | None,
    eval_result: dict | None = None,
    delta_vs_parent: str | None = None,
    what_was_done: str | None = None,
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
                "files_changed": {"added": [], "modified": [], "deleted": [], "inherited_unchanged": []},
                "metrics": {},
                "artifacts": [],
                "depth": int(getattr(node, "depth", 0) or 0),
            }, indent=2))
        except Exception:
            pass
        return out_path


# Phase 3E (REFACTORING.md §3 + orchestrator/REFACTORING.md §2 Step 1)
# moved this module into a package; ``reconstruct_report_from_legacy``
# is re-exported from ``ari.orchestrator.node_report.__init__`` and the
# ``legacy_reconstruct`` shim sub-module — importing it here would
# create a cycle (the migrations module pulls helpers from this file).
