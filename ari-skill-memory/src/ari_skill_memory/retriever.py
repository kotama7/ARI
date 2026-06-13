"""Typed retrieval (Phase 1 — index over node_report).

Thin layer over existing ``backend.search_memory`` / ``bulk_get_node_memory``.
Filters by ``kind`` (metadata ``type``/``mem_kind``), artifact presence, and
ancestor scope. Kind filtering is currently a Python post-filter over an
over-fetched semantic result — correct but bounded; the Letta-side
``mem_kind`` top-level filter + pagination are the Phase 2/4 scale fix.

All callers are loop/pipeline hooks; never an LLM pull (PLAN §3).
"""
from __future__ import annotations

from typing import Any


def _kind_of(metadata: dict) -> str | None:
    return metadata.get("mem_kind") or metadata.get("type")


def search_research_memory(
    backend: Any,
    query: str,
    ancestor_ids: list[str],
    *,
    kinds: list[str] | None = None,
    require_artifacts: bool = False,
    limit: int = 5,
) -> dict:
    """Ancestor-scoped semantic search, post-filtered by kind / artifacts.

    Over-fetches from the underlying semantic search so the kind/artifact
    post-filter still returns up to ``limit`` matches.
    """
    overfetch = max(limit * 8, 40)
    raw = backend.search_memory(query, ancestor_ids, limit=overfetch)
    kinds_set = set(kinds) if kinds else None
    out: list[dict] = []
    for r in raw.get("results", []) or []:
        md = r.get("metadata", {}) or {}
        if kinds_set is not None and _kind_of(md) not in kinds_set:
            continue
        if require_artifacts and not md.get("artifact_refs"):
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return {"results": out}


def ancestor_typed_memory(
    backend: Any,
    ancestor_ids: list[str],
    *,
    kinds: list[str] | None = None,
) -> list[dict]:
    """Deterministic, full handoff of ancestor entries of the given kinds.

    Uses ``bulk_get_node_memory`` (no semantic search). Order follows
    ``ancestor_ids`` (root → parent). This is the typed form of the loop's
    Tier-1(b) ancestor-core path.
    """
    by_node = backend.bulk_get_node_memory(list(ancestor_ids)).get("by_node", {})
    kinds_set = set(kinds) if kinds else None
    out: list[dict] = []
    for aid in ancestor_ids:
        for e in by_node.get(aid, []) or []:
            md = e.get("metadata", {}) or {}
            if kinds_set is not None and _kind_of(md) not in kinds_set:
                continue
            out.append({
                "entry_id": e.get("entry_id"),
                "node_id": aid,
                "text": e.get("text", ""),
                "metadata": md,
            })
    return out


def fold_reproducibility(
    backend: Any, ancestor_ids: list[str]
) -> dict[str, dict]:
    """Resolve the latest reproducibility status per target memory id.

    Reads append-only ``reproducibility_event`` entries in ancestor scope and
    keeps the most recent (by ``ts`` if present, else insertion order) per
    ``repro_target_id``.
    """
    events = ancestor_typed_memory(backend, ancestor_ids, kinds=["reproducibility_event"])
    latest: dict[str, dict] = {}
    for i, e in enumerate(events):
        md = e["metadata"]
        target = md.get("repro_target_id")
        if not target:
            continue
        ts = md.get("ts", i)
        cur = latest.get(target)
        if cur is None or ts >= cur.get("_ts", -1):
            latest[target] = {"status": md.get("repro_status"), "_ts": ts}
    return {k: {"status": v["status"]} for k, v in latest.items()}
