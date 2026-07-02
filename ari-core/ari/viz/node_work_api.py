"""REST API: per-node work-dir filetree + filecontent + memory listing.

Phase 3B PR-3B-2 (viz/REFACTORING.md §2 Step 2): extracted from
``ari/viz/api_state.py``.  ``api_state.py`` keeps a re-export facade
so downstream callers (and the route table inside ``server.py``) see
the same names regardless of where each function landed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import state as _st


log = logging.getLogger(__name__)

# Phase 3B PR-3B-2: module-level constants restored from
# ``api_state.py``.  Used by the per-node filetree/filecontent walks.
_BINARY_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".o", ".a", ".dll", ".dylib", ".exe",
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".ico",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".bin", ".dat", ".pkl", ".pickle", ".npy", ".npz", ".h5", ".hdf5",
    ".pt", ".pth", ".ckpt", ".safetensors",
    ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flac",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
}

_SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".tox", ".mypy_cache",
              ".pytest_cache", ".ruff_cache", "dist", ".eggs", "*.egg-info"}


# Phase 3B PR-3B-2: bare-name wrappers that defer to ``api_state``
# at call time so ``monkeypatch.setattr(api_state, name, ...)``
# in tests intercepts the helper this module's functions call.
def _resolve_checkpoint_dir(*args, **kwargs):  # noqa: D401
    from . import api_state as _as
    return _as._resolve_checkpoint_dir(*args, **kwargs)



def _resolve_node_work_dir(ckpt_dir: Path, node_id: str) -> Path | None:
    """Locate a node's work directory under the checkpoint's workspace.

    Layout: ``{workspace_root}/experiments/{run_id}/{node_id}/`` where
    ``run_id == ckpt_dir.name``. A legacy fallback scans
    ``experiments/*/{node_id}/`` for directories produced before the
    run_id-keyed layout was introduced.
    """
    from ari.paths import PathManager
    pm = PathManager.from_checkpoint_dir(ckpt_dir)
    run_id = ckpt_dir.name
    candidate = pm.experiments_root / run_id / node_id
    if candidate.exists() and candidate.is_dir():
        return candidate
    # Legacy fallback: older runs wrote experiments/{topic_slug}/{node_id}/.
    # Prefer a bucket whose name matches the run_id's topic slug suffix
    # (``YYYYMMDDHHMMSS_<slug>``) so same-topic runs don't collide.
    legacy_slug: str | None = None
    m = re.match(r'^[0-9]{8,14}_(.+)$', run_id)
    if m:
        legacy_slug = m.group(1)
    exp_root = pm.experiments_root
    if exp_root.exists():
        if legacy_slug is not None:
            cand = exp_root / legacy_slug / node_id
            if cand.exists() and cand.is_dir():
                return cand
        for bucket in exp_root.iterdir():
            if not bucket.is_dir():
                continue
            cand = bucket / node_id
            if cand.exists() and cand.is_dir():
                return cand
    return None



def _api_checkpoint_filetree(ckpt_id: str, node_id: str = "") -> dict:
    """Return the directory tree for a checkpoint, or a specific node.

    When *node_id* is provided, return the tree of that node's work
    directory under ``experiments/{run_id}/{node_id}/``. Otherwise, return
    the full checkpoint directory tree.
    """
    d = _resolve_checkpoint_dir(ckpt_id)
    if d is None:
        return {"error": "checkpoint not found"}
    is_node_view = bool(node_id)
    if is_node_view:
        nd = _resolve_node_work_dir(d, node_id)
        if nd is None:
            return {"error": f"node work_dir not found for {node_id}"}
        d = nd

    from ari.paths import PathManager

    def _build_tree(base: Path, rel_prefix: str = "") -> list[dict]:
        entries: list[dict] = []
        try:
            children = sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return entries
        for child in children:
            name = child.name
            if name.startswith(".") and name not in (".env",):
                continue
            # When viewing a node's work_dir, hide ARI metadata files
            # (node_report.json, viz_access.jsonl, memory_access.jsonl, …)
            # so they don't masquerade as experiment artefacts.
            if is_node_view and child.is_file() and PathManager.is_meta_file(name):
                continue
            rel = f"{rel_prefix}/{name}" if rel_prefix else name
            if child.is_dir():
                if name in _SKIP_DIRS or name.endswith(".egg-info"):
                    continue
                sub = _build_tree(child, rel)
                entries.append({"name": name, "path": rel, "type": "dir", "children": sub})
            elif child.is_file():
                ext = child.suffix.lower()
                try:
                    size = child.stat().st_size
                except Exception:
                    size = 0
                is_text = ext not in _BINARY_EXTENSIONS and size < 10_000_000
                entries.append({
                    "name": name,
                    "path": rel,
                    "type": "file",
                    "size": size,
                    "ext": ext,
                    "readable": is_text,
                })
        return entries

    tree = _build_tree(d)
    return {"id": ckpt_id, "path": str(d), "tree": tree}



def _api_checkpoint_filecontent(ckpt_id: str, filepath: str, node_id: str = "") -> dict:
    """Read a file's content from a checkpoint directory, or a node's work dir."""
    d = _resolve_checkpoint_dir(ckpt_id)
    if d is None:
        return {"error": "checkpoint not found"}
    if node_id:
        nd = _resolve_node_work_dir(d, node_id)
        if nd is None:
            return {"error": f"node work_dir not found for {node_id}"}
        d = nd
    target = (d / filepath).resolve()
    # Security: must be inside base dir
    try:
        target.relative_to(d.resolve())
    except ValueError:
        return {"error": "path traversal denied"}
    if not target.exists() or not target.is_file():
        return {"error": "file not found"}
    if target.stat().st_size > 5_000_000:
        return {"error": "file too large (>5MB)"}
    ext = target.suffix.lower()
    if ext in _BINARY_EXTENSIONS:
        return {"error": "binary file — cannot display"}
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": str(e)}
    return {"name": filepath, "content": content}



def _api_checkpoint_memory(ckpt_id: str) -> dict:
    """Return memory entries for a checkpoint, grouped by node_id.-process backend library — viz never spawns the MCP skill.
    """
    d = _resolve_checkpoint_dir(ckpt_id)
    if d is None:
        return {"error": "checkpoint not found"}

    entries: list[dict] = []
    err: str | None = None

    try:
        from ari.paths import PathManager as _PM_mem
        _PM_mem.set_checkpoint_dir_env(d)
        from ari.memory import get_backend
        backend = get_backend(checkpoint_dir=d)
        # node-scope entries
        for nid, lst in backend.list_all_nodes().get("by_node", {}).items():
            for e in lst:
                entries.append({
                    "node_id": nid,
                    "text": e.get("text", ""),
                    "metadata": e.get("metadata", {}) or {},
                    "ts": e.get("ts"),
                    "source": "mcp",
                })
        # react-trace entries
        for e in backend.list_react_entries():
            md = e.get("metadata", {}) or {}
            entries.append({
                "node_id": md.get("node_id", ""),
                "text": e.get("content", ""),
                "metadata": md,
                "ts": e.get("ts"),
                "source": "file_client",
            })
    except Exception as e:  # pragma: no cover - depends on Letta deployment
        err = f"memory backend unavailable: {e}"
        log.warning("viz: %s", err)

    by_node: dict[str, list[dict]] = {}
    for e in entries:
        by_node.setdefault(e.get("node_id") or "_unscoped", []).append(e)

    return {
        "id": ckpt_id,
        "entries": entries,
        "by_node": by_node,
        # Global memory is removed in v0.6.0. The field is retained
        # so the existing frontend schema keeps working.
        "global": [],
        "error": err,
        "count": len(entries),
    }

