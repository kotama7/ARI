"""Centralised path management for ARI.

Every component that needs to create or resolve directories should go
through :class:`PathManager` instead of constructing paths ad-hoc.
This keeps the on-disk layout in one place and makes testing trivial
(just pass a custom *workspace_root*).

Typical on-disk layout produced by PathManager::

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
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path


class PathManager:
    """Single source of truth for every directory ARI touches.

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
        "results.json",
        "idea.json",
        "cost_trace.jsonl",
        "cost_summary.json",
        "workflow.yaml",
        "ari.log",
        ".ari_pid",
        ".pipeline_started",
        "evaluation_criteria.json",
    })

    # File extensions that are ARI internal — never copied into node work dirs.
    META_EXTENSIONS: frozenset[str] = frozenset({".log"})

    def __init__(self, workspace_root: str | Path = ".") -> None:
        self._root = Path(workspace_root).resolve()

    # ── properties ────────────────────────────────────────────────────

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

    # ── per-node work directories ─────────────────────────────────────

    def node_work_dir(self, run_id: str, node_id: str) -> Path:
        """``experiments/{run_id}/{node_id}/``

        Keyed by *run_id* (not a topic slug) so runs that share an
        experiment name never write into the same bucket.
        """
        return self.experiments_root / run_id / node_id

    # ── staging (pre-launch uploads) ──────────────────────────────────

    def new_staging_dir(self) -> Path:
        """Create and return a fresh staging directory with a timestamp name."""
        ts = time.strftime("%Y%m%d%H%M%S")
        d = self.staging_root / ts
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── directory creation helpers ────────────────────────────────────

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

    # ── classification helpers ────────────────────────────────────────

    @classmethod
    def is_meta_file(cls, filename: str) -> bool:
        """Return True if *filename* is ARI metadata (should not be copied to nodes)."""
        if filename in cls.META_FILES:
            return True
        _, ext = os.path.splitext(filename)
        return ext in cls.META_EXTENSIONS

    # ── slug helpers ──────────────────────────────────────────────────

    @staticmethod
    def slugify(text: str, max_len: int = 40) -> str:
        """Turn *text* into a safe directory-name slug."""
        slug = re.sub(r"[^a-zA-Z0-9_-]", "_", text).strip("_")[:max_len]
        return re.sub(r"_+", "_", slug)

    # ── factory: build from checkpoint_dir path ───────────────────────

    @classmethod
    def from_checkpoint_dir(cls, checkpoint_dir: str | Path) -> "PathManager":
        """Infer *workspace_root* from an existing checkpoint directory.

        Walks up from *checkpoint_dir* to find the outermost ``checkpoints/``
        ancestor and uses its parent as the workspace root.  Falls back to
        the direct parent of *checkpoint_dir* if no ``checkpoints/`` ancestor
        exists (e.g. test environments that skip the ``checkpoints/`` nesting).
        """
        p = Path(checkpoint_dir).resolve()
        # Walk up to find outermost checkpoints/ directory
        best = None
        cur = p
        while cur != cur.parent:
            if cur.name == "checkpoints" and cur.parent.name != "checkpoints":
                best = cur.parent
            cur = cur.parent
        if best is not None:
            return cls(best)
        # Fallback: use direct parent so experiments/ is a sibling of checkpoint_dir
        return cls(p.parent)

    # ── repr ──────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"PathManager(root={self._root})"
