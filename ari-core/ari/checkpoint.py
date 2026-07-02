"""Checkpoint JSON I/O — single home for tree.json / nodes_tree.json /
results.json reads and writes (Phase 2 — PR-2B).

Three call sites used to spell out their own JSON layout:

* ``cli.py:_save_checkpoint`` (writes all three files at the end of a
  checkpoint flush).
* ``cli.py:_save_tree_incremental`` (throttled mid-run flush during
  parallel BFTS execution).
* ``viz/api_state.py:_load_nodes_tree`` (reader with the legacy
  ``node_*/tree.json`` fallback).

The helpers below preserve those semantics exactly:

- File names and JSON key order are unchanged.
- ``json.dumps(..., indent=2, ensure_ascii=False)`` is preserved.
- The throttle behaviour from ``_save_tree_incremental`` is reproduced
  via ``save_tree_incremental`` so the same lock + monotonic-clock
  bookkeeping lives in one place.
- ``load_nodes_tree`` keeps the precedence order
  ``tree.json → nodes_tree.json → newest non-empty
  ``node_*/tree.json`` glob`` from ``viz/api_state.py``.

Callers should keep ``Node.to_dict()`` formatting in their own code so
this module stays domain-agnostic; we only handle the on-disk layout.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# write helpers
# ──────────────────────────────────────────────


def _dump(p: Path, data: Any) -> None:
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def save_tree_json(checkpoint_dir: str | Path, tree: dict) -> None:
    """Write ``{checkpoint_dir}/tree.json``.

    *tree* must already be the rich layout used by the CLI:
    ``{"run_id": ..., "experiment_file": ..., "experiment_file_sha256":
    ..., "experiment_file_len": ..., "created_at": ..., "nodes": [...]}``.
    """
    _dump(Path(checkpoint_dir) / "tree.json", tree)


def save_nodes_tree_json(checkpoint_dir: str | Path, nodes: dict) -> None:
    """Write ``{checkpoint_dir}/nodes_tree.json`` (lightweight pipeline export)."""
    _dump(Path(checkpoint_dir) / "nodes_tree.json", nodes)


def save_results_json(checkpoint_dir: str | Path, results: dict) -> None:
    """Write ``{checkpoint_dir}/results.json``."""
    _dump(Path(checkpoint_dir) / "results.json", results)


def save_prompt_versions_json(checkpoint_dir: str | Path, versions: dict) -> None:
    """Write ``{checkpoint_dir}/prompt_versions.json`` (subtask 044).

    Additive run-level prompt-provenance rollup — the human-auditable
    "which prompt versions did this run use" summary aggregated from
    ``prompt_trace.jsonl``. Uses the same ``json.dumps(..., indent=2,
    ensure_ascii=False)`` layout as the other checkpoint writers so JSON
    formatting stays owned by this module.
    """
    _dump(Path(checkpoint_dir) / "prompt_versions.json", versions)


# ──────────────────────────────────────────────
# read helpers
# ──────────────────────────────────────────────


def load_tree_json(checkpoint_dir: str | Path) -> dict | None:
    """Read ``{checkpoint_dir}/tree.json`` if present and parses cleanly."""
    p = Path(checkpoint_dir) / "tree.json"
    return _safe_read_json(p)


def load_nodes_tree_json(checkpoint_dir: str | Path) -> dict | None:
    """Read ``{checkpoint_dir}/nodes_tree.json`` if present and parses cleanly."""
    p = Path(checkpoint_dir) / "nodes_tree.json"
    return _safe_read_json(p)


def load_nodes_tree(checkpoint_dir: str | Path) -> dict | None:
    """Resolve and load the active node tree for the checkpoint.

    Mirrors ``viz/api_state.py:_load_nodes_tree`` exactly:

        1. ``{ckpt}/tree.json``
        2. ``{ckpt}/nodes_tree.json``
        3. newest non-empty ``{ckpt}/node_*/tree.json`` (legacy layout
           where each node owned its own tree).

    Returns ``None`` when nothing is found OR when the resolved file
    parses as an empty / nodes-less dict (the GUI treats both the same
    way).  Includes the same one-shot retry on ``JSONDecodeError`` to
    survive a mid-write race.
    """
    base = Path(checkpoint_dir)
    p = base / "tree.json"
    if not p.exists():
        p = base / "nodes_tree.json"
    if not p.exists():
        candidates = sorted(
            base.glob("node_*/tree.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        chosen: Path | None = None
        for c in candidates:
            try:
                if c.stat().st_size > 2:  # skip empty "{}"
                    chosen = c
                    break
            except OSError:
                continue
        if chosen is None:
            return None
        p = chosen

    for attempt in range(2):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            if attempt == 0:
                time.sleep(0.15)
                continue
            return None
        except Exception:
            log.debug("nodes_tree load error", exc_info=True)
            return None
        if not data or (isinstance(data, dict) and "nodes" not in data):
            return None
        return data
    return None


# ──────────────────────────────────────────────
# throttled incremental writer
# ──────────────────────────────────────────────


_INCR_LOCK = threading.Lock()
_INCR_LAST_SAVE_MONO: dict[str, float] = {}
_INCR_DEFAULT_MIN_INTERVAL_S = 1.0


def save_tree_incremental(
    checkpoint_dir: str | Path,
    writer,
    *,
    force: bool = False,
    throttle_sec: float = _INCR_DEFAULT_MIN_INTERVAL_S,
) -> None:
    """Throttled, thread-safe wrapper around an arbitrary tree writer.

    *writer* is a zero-argument callable that performs the actual writes
    (typically calls ``save_tree_json`` / ``save_nodes_tree_json`` /
    ``save_results_json``).  Multiple worker threads can call this
    concurrently while agents run in parallel; the lock serialises writes
    so partial JSON never reaches the GUI, and the throttle keeps disk
    churn bounded.  Pass ``force=True`` on terminal node transitions to
    bypass the throttle.

    Default interval matches the legacy ``cli.py:_save_tree_incremental``
    (``1.0`` s, slightly tighter than the plan's 0.5 default — Phase 2
    preserves behaviour over the plan's nominal value).
    """
    key = str(checkpoint_dir)
    now = time.monotonic()
    with _INCR_LOCK:
        if not force:
            last = _INCR_LAST_SAVE_MONO.get(key, 0.0)
            if now - last < throttle_sec:
                return
        _INCR_LAST_SAVE_MONO[key] = now
        try:
            writer()
        except Exception:
            log.debug("incremental tree save failed", exc_info=True)


# ──────────────────────────────────────────────
# private helpers
# ──────────────────────────────────────────────


def _safe_read_json(p: Path) -> dict | None:
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None
