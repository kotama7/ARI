"""Centralised path management for ARI.

Every component that needs to create or resolve directories should go
through :class:`PathManager` instead of constructing paths ad-hoc.
This keeps the on-disk layout in one place and makes testing trivial
(just pass a custom *workspace_root*).

Typical on-disk layout produced by PathManager (the **flat** layout — the
only layout new runs write today)::

    {workspace_root}/
    ├── checkpoints/
    │   └── {run_id}/              # checkpoint_dir
    │       ├── experiment.md
    │       ├── meta.json
    │       ├── launch_config.json
    │       ├── tree.json
    │       ├── results.json
    │       ├── idea.json
    │       ├── cost_trace.jsonl
    │       ├── cost_summary.json
    │       ├── ari.log
    │       ├── uploads/           # user-uploaded files
    │       └── ...
    ├── experiments/
    │   └── {run_id}/              # per-run bucket — keeps same-topic runs separated
    │       └── {node_id}/         # per-node work directory
    └── staging/
        └── {timestamp}/           # pre-launch upload staging

Runtime path resolution is owned by :class:`RuntimePathResolver`;
:class:`PathManager` is a thin facade that delegates to it (subtask 006).
The resolver additionally understands the *bucketed* run-directory layout
that subtask 005 will populate later::

    {workspace_root}/
    └── runs/
        └── {run_id}/
            ├── workspace/         # per-node scratch  (was experiments/{run_id}/{node_id})
            ├── checkpoints/       # ARI metadata json (was the flat checkpoint root)
            ├── artifacts/         # figures, LaTeX, refs.bib, produced outputs
            ├── traces/            # cost_trace.jsonl, access/lineage logs
            └── reports/           # node_report.json, review/repro/ors_*.json

The resolver resolves run-scoped files **bucket-first, then flat**, so a
bucketed run resolves from the buckets while the flat layout (today's
reality, and what new runs still write) resolves exactly as before. This
is purely additive and behaviour-preserving: nothing writes the bucketed
layout in this subtask.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

# ── bucketed-layout (subtask 005 target) classification ────────────────────
#
# Sub-buckets that hold *files* under ``runs/<run_id>/`` (``workspace/`` holds
# per-node directories, not run-scoped files, and is handled separately).
_RUN_FILE_BUCKETS: tuple[str, ...] = ("checkpoints", "artifacts", "traces", "reports")

# Files that live under ``runs/<id>/traces/`` in the bucketed layout.
_TRACE_FILES: frozenset[str] = frozenset({
    "cost_trace.jsonl",
    "cost_summary.json",
    "viz_access.jsonl",
    "memory_access.jsonl",
    "memory_access.summary.json",
    "lineage_decisions.jsonl",
})

# Files that live under ``runs/<id>/reports/`` in the bucketed layout.
_REPORT_FILES: frozenset[str] = frozenset({
    "node_report.json",
    "review_report.json",
    "reproducibility_report.json",
})

# File extensions produced as run artifacts (figures, LaTeX, bibliography).
_ARTIFACT_EXTENSIONS: frozenset[str] = frozenset({
    ".tex", ".pdf", ".bbl", ".bib", ".png", ".svg",
})

_MEMORY_ACCESS_RE = re.compile(r"^memory_access\.[^/]+\.jsonl$")
_ORS_RE = re.compile(r"^ors_.*\.json$")


class RuntimePathResolver:
    """Single seam that resolves every runtime directory/file ARI touches.

    The resolver owns two things that used to be scattered across the core:

    1. **Workspace-root resolution** implementing subtask 004's policy
       (``workspace/`` wins) — see :meth:`resolve_workspace_root`.
    2. **Run-scoped file resolution** that is *dual-layout aware*: it prefers
       the bucketed ``runs/<run_id>/<bucket>/`` layout (subtask 005's target)
       when present on disk, and otherwise falls back to today's **flat**
       checkpoint layout. This lets 005's on-disk migration land later
       without a flag-day.

    :class:`PathManager` delegates to this class, so the flat-layout return
    values of every :class:`PathManager` method are produced here and stay
    byte-identical.

    Parameters
    ----------
    workspace_root : str | Path
        Top-level directory under which *checkpoints/*, *experiments/*,
        *staging/*, and (bucketed) *runs/* live. Defaults to ``.`` (cwd),
        matching :class:`PathManager`'s historical default.
    """

    def __init__(self, workspace_root: str | Path = ".") -> None:
        self._root = Path(workspace_root).resolve()

    # ── roots ─────────────────────────────────────────────────────────

    @property
    def root(self) -> Path:
        """Resolved workspace root."""
        return self._root

    @property
    def checkpoints_root(self) -> Path:
        return self._root / "checkpoints"

    @property
    def experiments_root(self) -> Path:
        return self._root / "experiments"

    @property
    def staging_root(self) -> Path:
        return self._root / "staging"

    @property
    def paper_registry_root(self) -> Path:
        return self._root / "paper_registry"

    @property
    def runs_root(self) -> Path:
        """``{workspace_root}/runs/`` — parent of the bucketed per-run dirs
        (subtask 005 target layout). Inert until 005 populates it."""
        return self._root / "runs"

    # ── flat per-run paths (behaviour-preserving) ─────────────────────

    def checkpoint_dir(self, run_id: str) -> Path:
        """``checkpoints/{run_id}/`` (flat layout — what new runs write)."""
        return self.checkpoints_root / run_id

    def log_dir(self, run_id: str) -> Path:
        """Logs live inside the checkpoint dir (not a separate tree)."""
        return self.checkpoint_dir(run_id)

    def log_file(self, run_id: str) -> Path:
        return self.log_dir(run_id) / "ari.log"

    def uploads_dir(self, run_id: str) -> Path:
        """``checkpoints/{run_id}/uploads/``"""
        return self.checkpoint_dir(run_id) / "uploads"

    def cost_trace(self, run_id: str) -> Path:
        return self.checkpoint_dir(run_id) / "cost_trace.jsonl"

    def cost_summary(self, run_id: str) -> Path:
        return self.checkpoint_dir(run_id) / "cost_summary.json"

    def idea_file(self, run_id: str) -> Path:
        return self.checkpoint_dir(run_id) / "idea.json"

    def node_work_dir(self, run_id: str, node_id: str) -> Path:
        """``experiments/{run_id}/{node_id}/`` (flat/legacy node scratch)."""
        return self.experiments_root / run_id / node_id

    def new_staging_dir(self) -> Path:
        """Create and return a fresh staging directory with a timestamp name."""
        ts = time.strftime("%Y%m%d%H%M%S")
        d = self.staging_root / ts
        d.mkdir(parents=True, exist_ok=True)
        return d

    def ensure_checkpoint(self, run_id: str) -> Path:
        """Create and return the checkpoint directory for *run_id*."""
        d = self.checkpoint_dir(run_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def ensure_uploads(self, run_id: str) -> Path:
        d = self.uploads_dir(run_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def ensure_node_work_dir(self, run_id: str, node_id: str) -> Path:
        """Create and return a node work directory."""
        d = self.node_work_dir(run_id, node_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── bucketed (subtask 005 target) layout — dual-layout aware ──────

    def run_dir(self, run_id: str) -> Path:
        """``runs/{run_id}/`` — the bucketed per-run parent (005 target)."""
        return self.runs_root / run_id

    @staticmethod
    def bucket_for(name: str) -> str:
        """Classify a run-scoped filename into its 005 target sub-bucket.

        Returns one of ``checkpoints``/``artifacts``/``traces``/``reports``.
        This only *orders* the dual-layout search in :meth:`checkpoint_file`
        (which scans every bucket), so an imperfect classification never
        yields a wrong path — it only changes which bucket is checked first.
        """
        _, ext = os.path.splitext(name)
        if name in _TRACE_FILES or _MEMORY_ACCESS_RE.match(name):
            return "traces"
        if name in _REPORT_FILES or _ORS_RE.match(name):
            return "reports"
        if name.startswith("fig_") or ext in _ARTIFACT_EXTENSIONS:
            return "artifacts"
        # Metadata (META_FILES), logs, and anything unknown default to the
        # checkpoints bucket.
        return "checkpoints"

    def checkpoint_file(self, run_id: str, name: str) -> Path:
        """Resolve a run-scoped file, **bucket-first then flat**.

        If the bucketed ``runs/{run_id}/<bucket>/{name}`` exists on disk it
        is returned (checking the classified bucket first, then the others);
        otherwise the flat ``checkpoints/{run_id}/{name}`` path is returned.
        Because new runs still write flat, and no bucket exists on disk yet,
        this returns exactly the flat path today (behaviour-preserving).
        """
        run_dir = self.run_dir(run_id)
        primary = self.bucket_for(name)
        ordered = (primary, *(b for b in _RUN_FILE_BUCKETS if b != primary))
        for bucket in ordered:
            candidate = run_dir / bucket / name
            if candidate.exists():
                return candidate
        # Flat fallback (today's reality; the write path stays flat here).
        return self.checkpoint_dir(run_id) / name

    def artifacts_dir(self, run_id: str) -> Path:
        """``runs/{run_id}/artifacts/`` if present, else the flat checkpoint root."""
        bucket = self.run_dir(run_id) / "artifacts"
        return bucket if bucket.is_dir() else self.checkpoint_dir(run_id)

    def traces_dir(self, run_id: str) -> Path:
        """``runs/{run_id}/traces/`` if present, else the flat checkpoint root."""
        bucket = self.run_dir(run_id) / "traces"
        return bucket if bucket.is_dir() else self.checkpoint_dir(run_id)

    def reports_dir(self, run_id: str) -> Path:
        """``runs/{run_id}/reports/`` if present, else the flat checkpoint root."""
        bucket = self.run_dir(run_id) / "reports"
        return bucket if bucket.is_dir() else self.checkpoint_dir(run_id)

    def workspace_dir(self, run_id: str, node_id: str) -> Path:
        """Per-node scratch dir, dual-layout aware.

        Returns ``runs/{run_id}/workspace/{node_id}`` when the bucketed
        ``workspace/`` dir exists, else the legacy
        ``experiments/{run_id}/{node_id}`` (== :meth:`node_work_dir`).
        """
        bucket_root = self.run_dir(run_id) / "workspace"
        if bucket_root.is_dir():
            return bucket_root / node_id
        return self.node_work_dir(run_id, node_id)

    # ── env-driven helpers — the single owner of the run pin ──────────
    #
    # ``ARI_CHECKPOINT_DIR`` is the single env var that pins ARI to a
    # specific run. Routing reads/writes through the resolver keeps every
    # caller independent of the spelling.

    @staticmethod
    def checkpoint_dir_from_env() -> Path | None:
        """Return ``Path(ARI_CHECKPOINT_DIR)`` when set, else ``None``."""
        val = os.environ.get("ARI_CHECKPOINT_DIR", "").strip()
        return Path(val) if val else None

    @staticmethod
    def set_checkpoint_dir_env(checkpoint_dir: str | Path) -> None:
        """Set ``ARI_CHECKPOINT_DIR`` so child processes inherit the run pin."""
        os.environ["ARI_CHECKPOINT_DIR"] = str(checkpoint_dir)

    @staticmethod
    def _infer_workspace_root(checkpoint_dir: str | Path) -> Path:
        """Infer *workspace_root* from an existing checkpoint directory.

        Walks up from *checkpoint_dir* to find the outermost ``checkpoints/``
        ancestor and uses its parent as the workspace root. Falls back to the
        direct parent of *checkpoint_dir* if no ``checkpoints/`` ancestor
        exists (e.g. test environments that skip the ``checkpoints/`` nesting).

        This is the verbatim recovery algorithm relied on by
        ``from_checkpoint_dir`` (both here and on :class:`PathManager`).
        """
        p = Path(checkpoint_dir).resolve()
        best = None
        cur = p
        while cur != cur.parent:
            if cur.name == "checkpoints" and cur.parent.name != "checkpoints":
                best = cur.parent
            cur = cur.parent
        if best is not None:
            return best
        return p.parent

    @classmethod
    def from_checkpoint_dir(cls, checkpoint_dir: str | Path) -> "RuntimePathResolver":
        """Build a resolver whose workspace root is inferred from a checkpoint dir."""
        return cls(cls._infer_workspace_root(checkpoint_dir))

    @classmethod
    def from_env(cls) -> "RuntimePathResolver":
        """Build a resolver from the current process env (``ARI_CHECKPOINT_DIR``)."""
        ckpt = cls.checkpoint_dir_from_env()
        if ckpt is not None:
            return cls.from_checkpoint_dir(ckpt)
        return cls()

    @classmethod
    def resolve_workspace_root(cls, workspace_root: str | Path | None = None) -> Path:
        """Resolve the canonical workspace root per subtask 004's policy.

        Precedence (first match wins), implementing 004 P2 (``workspace/`` wins):

        1. ``ARI_CHECKPOINT_DIR`` — recover the root via :meth:`_infer_workspace_root`.
        2. An explicit *workspace_root* argument.
        3. ``ARI_ROOT`` env → ``{ARI_ROOT}/workspace``.
        4. ``{repo_root}/workspace`` (matches ``auto_config()``), when running
           from inside the ARI checkout.
        5. Current working directory (last resort — matches ``PathManager()``).

        This is the single function that owns "what is the workspace root".
        It is *additive*: ``PathManager()``'s default constructor still
        resolves to the cwd, so existing behaviour is unchanged until a caller
        opts in to this policy (deferred to 005 per the 006 plan).
        """
        ckpt = cls.checkpoint_dir_from_env()
        if ckpt is not None:
            return cls._infer_workspace_root(ckpt)
        if workspace_root is not None:
            return Path(workspace_root).resolve()
        ari_root = os.environ.get("ARI_ROOT", "").strip()
        if ari_root:
            return (Path(ari_root) / "workspace").resolve()
        repo_root = Path(__file__).resolve().parents[2]
        if (repo_root / "ari-core").is_dir():
            return (repo_root / "workspace").resolve()
        return Path(".").resolve()

    def __repr__(self) -> str:
        return f"RuntimePathResolver(root={self._root})"


class PathManager:
    """Single source of truth for every directory ARI touches.

    Thin facade over :class:`RuntimePathResolver`: every method keeps its
    exact signature and (for the flat layout) return value while the actual
    resolution is delegated to the resolver.

    Parameters
    ----------
    workspace_root : str | Path
        Top-level directory under which *checkpoints/*, *experiments/*,
        and *staging/* live.  Defaults to ``./`` (current working directory)
        which preserves backward compatibility with config.yaml defaults.
    """

    # Files that are ARI metadata — never copied into node work dirs.
    META_FILES: frozenset[str] = frozenset({
        "experiment.md",
        "launch_config.json",
        "meta.json",
        "tree.json",
        "nodes_tree.json",
        "bfts_tree.json",
        "results.json",
        "idea.json",
        "cost_trace.jsonl",
        "cost_summary.json",
        "workflow.yaml",
        "ari.log",
        ".ari_pid",
        ".pipeline_started",
        "evaluation_criteria.json",
        # Internal access logs — written by viz/memory backends at the
        # checkpoint root. These are diagnostics, not experiment artefacts,
        # and must not be copied into node work_dirs nor surfaced as files.
        "viz_access.jsonl",
        "memory_access.jsonl",
        "memory_access.summary.json",
        # Per-node self-report. Each child must generate its own; never
        # inherit the parent's via the work_dir physical-copy data path.
        "node_report.json",
    })

    # File extensions that are ARI internal — never copied into node work dirs.
    META_EXTENSIONS: frozenset[str] = frozenset({".log"})

    # Filename patterns (regex, full-match) that are ARI metadata.
    # Used in addition to META_FILES for rotated/timestamped variants.
    _META_PATTERNS: tuple[re.Pattern, ...] = (
        re.compile(r"^memory_access\.[^/]+\.jsonl$"),
    )

    def __init__(self, workspace_root: str | Path = ".") -> None:
        self._resolver = RuntimePathResolver(workspace_root)
        # Kept for backward compatibility with internal callers / __repr__.
        self._root = self._resolver.root

    # ── resolver access ───────────────────────────────────────────────

    @property
    def resolver(self) -> RuntimePathResolver:
        """The underlying :class:`RuntimePathResolver` this facade delegates to."""
        return self._resolver

    # ── properties ────────────────────────────────────────────────────

    @property
    def root(self) -> Path:
        """Resolved workspace root."""
        return self._resolver.root

    @property
    def checkpoints_root(self) -> Path:
        return self._resolver.checkpoints_root

    @property
    def experiments_root(self) -> Path:
        return self._resolver.experiments_root

    @property
    def staging_root(self) -> Path:
        return self._resolver.staging_root

    @property
    def paper_registry_root(self) -> Path:
        """``{workspace_root}/paper_registry/`` — cross-checkpoint store
        for externally-imported papers used by PaperBench audit runs.

        Imported papers (paper.pdf + optional AD/AE Appendix PDFs + per-
        paper manifest entry) are shared across all checkpoints because
        the same paper can be evaluated under many rubrics. Layout::

            {workspace_root}/paper_registry/
            ├── manifest.jsonl                 # one paper per line
            └── papers/
                └── <paper_id>/
                    ├── paper.pdf              # required
                    ├── ad.pdf                 # optional (AD Appendix)
                    └── ae.pdf                 # optional (AE Appendix)

        Override the location with the ``ARI_PAPER_REGISTRY_DIR`` env
        var when ``viz/api_paperbench.py`` is consulted standalone.
        """
        return self._resolver.paper_registry_root

    @property
    def runs_root(self) -> Path:
        """``{workspace_root}/runs/`` — parent of the bucketed per-run dirs
        (subtask 005 target). Inert until 005 populates it."""
        return self._resolver.runs_root

    # ── project-scoped (per-run) paths ────────────────────────────────
    #
    # ARI no longer maintains a global config/data directory.  Every
    # configuration and memory file lives under the active checkpoint, so
    # the user can ``rm -rf ~/.ari`` without losing anything.

    @staticmethod
    def project_settings_path(checkpoint_dir: str | Path) -> Path:
        """``{checkpoint_dir}/settings.json`` — per-experiment settings."""
        return Path(checkpoint_dir) / "settings.json"

    @staticmethod
    def project_memory_path(checkpoint_dir: str | Path) -> Path:
        """``{checkpoint_dir}/memory.json`` — per-experiment agent memory."""
        return Path(checkpoint_dir) / "memory.json"

    # ── per-run directories ───────────────────────────────────────────

    def checkpoint_dir(self, run_id: str) -> Path:
        """``checkpoints/{run_id}/``"""
        return self._resolver.checkpoint_dir(run_id)

    def log_dir(self, run_id: str) -> Path:
        """Logs live inside the checkpoint dir (not a separate tree)."""
        return self._resolver.log_dir(run_id)

    def log_file(self, run_id: str) -> Path:
        return self._resolver.log_file(run_id)

    def uploads_dir(self, run_id: str) -> Path:
        """``checkpoints/{run_id}/uploads/``"""
        return self._resolver.uploads_dir(run_id)

    def cost_trace(self, run_id: str) -> Path:
        return self._resolver.cost_trace(run_id)

    def cost_summary(self, run_id: str) -> Path:
        return self._resolver.cost_summary(run_id)

    def idea_file(self, run_id: str) -> Path:
        return self._resolver.idea_file(run_id)

    # ── per-node work directories ─────────────────────────────────────

    def node_work_dir(self, run_id: str, node_id: str) -> Path:
        """``experiments/{run_id}/{node_id}/``

        Keyed by *run_id* (not a topic slug) so runs that share an
        experiment name never write into the same bucket.
        """
        return self._resolver.node_work_dir(run_id, node_id)

    # ── staging (pre-launch uploads) ──────────────────────────────────

    def new_staging_dir(self) -> Path:
        """Create and return a fresh staging directory with a timestamp name."""
        return self._resolver.new_staging_dir()

    # ── bucketed (subtask 005 target) accessors — dual-layout aware ───
    #
    # Additive: these resolve the bucketed layout when present on disk and
    # otherwise degrade to the flat checkpoint root. Nothing writes the
    # bucketed layout in this subtask.

    def run_dir(self, run_id: str) -> Path:
        """``runs/{run_id}/`` — bucketed per-run parent (005 target)."""
        return self._resolver.run_dir(run_id)

    def checkpoint_file(self, run_id: str, name: str) -> Path:
        """Resolve a run-scoped file bucket-first then flat (see resolver)."""
        return self._resolver.checkpoint_file(run_id, name)

    def artifacts_dir(self, run_id: str) -> Path:
        """Bucketed ``artifacts/`` if present, else the flat checkpoint root."""
        return self._resolver.artifacts_dir(run_id)

    def traces_dir(self, run_id: str) -> Path:
        """Bucketed ``traces/`` if present, else the flat checkpoint root."""
        return self._resolver.traces_dir(run_id)

    def reports_dir(self, run_id: str) -> Path:
        """Bucketed ``reports/`` if present, else the flat checkpoint root."""
        return self._resolver.reports_dir(run_id)

    def workspace_dir(self, run_id: str, node_id: str) -> Path:
        """Bucketed ``workspace/{node_id}`` if present, else legacy node_work_dir."""
        return self._resolver.workspace_dir(run_id, node_id)

    # ── directory creation helpers ────────────────────────────────────

    def ensure_checkpoint(self, run_id: str) -> Path:
        """Create and return the checkpoint directory for *run_id*."""
        return self._resolver.ensure_checkpoint(run_id)

    def ensure_uploads(self, run_id: str) -> Path:
        return self._resolver.ensure_uploads(run_id)

    def ensure_node_work_dir(self, run_id: str, node_id: str) -> Path:
        """Create and return a node work directory."""
        return self._resolver.ensure_node_work_dir(run_id, node_id)

    # ── classification helpers ────────────────────────────────────────

    @classmethod
    def is_meta_file(cls, filename: str) -> bool:
        """Return True if *filename* is ARI metadata (should not be copied to nodes)."""
        if filename in cls.META_FILES:
            return True
        _, ext = os.path.splitext(filename)
        if ext in cls.META_EXTENSIONS:
            return True
        return any(p.match(filename) for p in cls._META_PATTERNS)

    # ── slug helpers ──────────────────────────────────────────────────

    @staticmethod
    def slugify(text: str, max_len: int = 40) -> str:
        """Turn *text* into a safe directory-name slug."""
        slug = re.sub(r"[^a-zA-Z0-9_-]", "_", text).strip("_")[:max_len]
        return re.sub(r"_+", "_", slug)

    # ── env-driven helpers ────────────────────────────────────────────
    #
    # ``ARI_CHECKPOINT_DIR`` is the single env var that pins ARI to a
    # specific run.  These helpers exist so that no other module needs
    # to read the env variable directly — callers go through
    # ``PathManager`` (which delegates to :class:`RuntimePathResolver`)
    # and stay independent of the spelling.

    @staticmethod
    def checkpoint_dir_from_env() -> Path | None:
        """Return ``Path(ARI_CHECKPOINT_DIR)`` when set, else ``None``.

        The env var is treated as the canonical run pin used by every
        ARI subprocess (CLI, MCP servers, viz).  Returning ``None`` lets
        callers preserve their existing fallback semantics (cwd lookup,
        explicit ``--checkpoint`` argument, etc.).
        """
        return RuntimePathResolver.checkpoint_dir_from_env()

    @staticmethod
    def set_checkpoint_dir_env(checkpoint_dir: str | Path) -> None:
        """Set ``ARI_CHECKPOINT_DIR`` so child processes inherit the run pin.

        ARI uses an env-var hand-off when spawning MCP skills, Letta and
        delete subprocesses so they bind to the same checkpoint as the
        parent.  Going through this helper keeps every writer routed
        through PathManager (Phase 1 receiving-criterion §10).
        """
        RuntimePathResolver.set_checkpoint_dir_env(checkpoint_dir)

    @classmethod
    def from_env(cls) -> "PathManager":
        """Build a :class:`PathManager` from the current process env.

        - If ``ARI_CHECKPOINT_DIR`` is set, infer the workspace root via
          :meth:`from_checkpoint_dir` so ``experiments/`` and
          ``staging/`` resolve as siblings of the active checkpoint.
        - Otherwise fall back to the current working directory, matching
          the behaviour of ``PathManager()``.
        """
        ckpt = cls.checkpoint_dir_from_env()
        if ckpt is not None:
            return cls.from_checkpoint_dir(ckpt)
        return cls()

    # ── factory: build from checkpoint_dir path ───────────────────────

    @classmethod
    def from_checkpoint_dir(cls, checkpoint_dir: str | Path) -> "PathManager":
        """Infer *workspace_root* from an existing checkpoint directory.

        Walks up from *checkpoint_dir* to find the outermost ``checkpoints/``
        ancestor and uses its parent as the workspace root.  Falls back to
        the direct parent of *checkpoint_dir* if no ``checkpoints/`` ancestor
        exists (e.g. test environments that skip the ``checkpoints/`` nesting).
        """
        return cls(RuntimePathResolver._infer_workspace_root(checkpoint_dir))

    # ── repr ──────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"PathManager(root={self._root})"
