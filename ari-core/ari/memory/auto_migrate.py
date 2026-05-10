"""Auto-migrate v0.5.x checkpoints on first v0.6.0 launch.

LETTA_BACKEND_SPEC.md §16.2. Callers (cli `run` / `resume` / `viz`) invoke
``maybe_auto_migrate(checkpoint_dir)`` once at startup.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)


def _has_source(ckpt: Path) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    node = ckpt / "memory_store.jsonl"
    if node.exists():
        sources["node_scope"] = node
    react = ckpt / "memory.json"
    if react.exists():
        sources["react_step"] = react
    return sources


def maybe_auto_migrate(checkpoint_dir: str | Path) -> dict:
    """Run a one-shot import if v0.5.x files exist and Letta is empty.

    Returns a status dict; never raises — the caller keeps going either
    way (failed migrations surface in the dashboard banner per §16.2).
    """
    ckpt = Path(checkpoint_dir).expanduser().resolve()
    if not ckpt.is_dir():
        return {"ran": False, "reason": "checkpoint_dir not a directory"}

    sources = _has_source(ckpt)
    if not sources:
        return {"ran": False, "reason": "no v0.5.x source files"}

    # Surface legacy global_memory.jsonl (removed in v0.6.0 per §3).
    global_path = Path.home() / ".ari" / "global_memory.jsonl"
    if global_path.exists():
        log.warning(
            "WARNING: %s found — global memory is removed in v0.6.0. "
            "See LETTA_BACKEND_SPEC.md §3. File left untouched.",
            global_path,
        )

    from ari.paths import PathManager
    PathManager.set_checkpoint_dir_env(ckpt)
    try:
        from ari_skill_memory.backends import get_backend
        backend = get_backend(checkpoint_dir=ckpt)
    except Exception as e:
        return {"ran": False, "reason": f"backend unavailable: {e}"}

    # If the checkpoint's Letta collections already have content, skip.
    try:
        already_node = sum(
            len(v) for v in backend.list_all_nodes().get("by_node", {}).values()
        )
    except Exception:
        already_node = 0
    try:
        already_react = len(backend.list_react_entries())
    except Exception:
        already_react = 0

    imported: dict[str, int] = {}
    ts = int(time.time())

    if "node_scope" in sources and already_node == 0:
        src = sources["node_scope"]
        entries = _load_jsonl(src)
        if entries:
            res = backend.bulk_import(entries, kind="node_scope")
            imported["node_scope"] = int(res.get("imported", 0))
        src.rename(ckpt / f"memory_store.jsonl.migrated-{ts}")

    if "react_step" in sources and already_react == 0:
        src = sources["react_step"]
        entries = _load_json_list(src)
        if entries:
            res = backend.bulk_import(entries, kind="react_step")
            imported["react_step"] = int(res.get("imported", 0))
        src.rename(ckpt / f"memory.json.migrated-{ts}")

    if not imported:
        return {"ran": True, "imported": {}}

    log.info("auto-migrate imported %s", imported)
    return {"ran": True, "imported": imported}


def _load_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _load_json_list(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


__all__ = ["maybe_auto_migrate"]
