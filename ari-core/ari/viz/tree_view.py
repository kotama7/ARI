"""BFTS tree-view adapter — single source of truth for the dashboard tree payload.

Subtask 024 (Phase 4, ``docs/refactoring/subtasks/024_refactor_bfts_tree_visualization_adapter.md``).
This module is the ONE place the viz backend converts a checkpoint's on-disk
BFTS node tree into the tree-view payload consumed by:

* the WebSocket ``{"type":"update","data":<tree>,"timestamp":...}`` message
  (``websocket._ws_handler`` / ``state_sync._broadcast``),
* ``GET /state`` (the inline builder in ``routes.py``), and
* the checkpoint list/summary cards
  (``checkpoint_api._api_checkpoints`` / ``_api_checkpoint_summary``).

It wraps :func:`ari.checkpoint.load_nodes_tree`, which owns the resolution
precedence ``tree.json -> nodes_tree.json -> newest non-empty node_*/tree.json``,
the mid-write ``JSONDecodeError`` retry (2 attempts, 0.15 s), and the empty /
``nodes``-less rejection (returns ``None``). Those semantics live in exactly one
place; this adapter adds no transformation, so the emitted bytes are unchanged.
It is also the single import boundary onto ``ari.checkpoint`` for tree loading —
if a ``ari.public.*`` tree-loading accessor is added later, only this module
changes (024 §7 import boundary).

Contract (KEEP, frozen — 010 §4 Contract D + §6 Contract B): the returned dict
is handed straight to ``json.dumps(..., ensure_ascii=False)`` for the WS ``data``
field and merged into the ``/state`` response, so the shape and key order MUST
stay byte-identical. No key is added, removed, or reordered here.

Status / label vocabulary (single-sourced elsewhere): the canonical node status
and label values live in ``ari.orchestrator.node`` — ``NodeStatus``
(``pending / running / success / failed / abandoned``) and ``NodeLabel``
(``draft / improve / debug / ablation / validation / other``). The consumer-side
derivations the tree view relies on (``scientific_score`` surfaced from
``metrics._scientific_score``, a default ``node_type``) are currently read via
``??`` fallbacks in ``frontend/src/components/Tree/TreeVisualization.tsx``.
Surfacing them as additive backend keys is DEFERRED here because any added key
would alter the emitted bytes (024 §7 step 5 / §11 — "if any risk of changing
emitted bytes, defer the additive keys and land the pure consolidation only").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_tree_view(checkpoint_dir: "str | Path | None") -> dict[str, Any] | None:
    """Return the tree-view payload for *checkpoint_dir*, or ``None``.

    Thin, byte-preserving adapter over :func:`ari.checkpoint.load_nodes_tree`.
    Returns the identical dict that loader produces (``{"nodes": [...], ...}``)
    — no field is added, removed, or reordered — so the WS ``update.data`` frame
    and the ``/state`` tree stay byte-for-byte unchanged. ``None`` is returned
    (and preserved) for a missing / empty / ``nodes``-less tree exactly as the
    loader decides, including the 2-attempt mid-write retry.

    A ``None`` *checkpoint_dir* short-circuits to ``None`` so the active-checkpoint
    caller (``state_sync._load_nodes_tree``) need not special-case it.
    """
    if checkpoint_dir is None:
        return None
    from ari.checkpoint import load_nodes_tree
    return load_nodes_tree(checkpoint_dir)
