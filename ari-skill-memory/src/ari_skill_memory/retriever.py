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

from ari.public.memory import (
    MemoryRecordV1,
    MemoryRetrievalV1,
    canonical_memory_digest,
)


def _record_of(entry: dict) -> MemoryRecordV1 | None:
    metadata = entry.get("metadata", {}) or {}
    raw = metadata.get("memory_record")
    if not isinstance(raw, dict):
        return None
    record = MemoryRecordV1.model_validate(raw)
    if record.text != entry.get("text", ""):
        raise ValueError("memory record text disagrees with indexed passage")
    if entry.get("node_id") and record.source_node_id != entry.get("node_id"):
        raise ValueError("memory record source node disagrees with backend metadata")
    if metadata.get("record_digest") != record.record_digest:
        raise ValueError("memory record digest projection is inconsistent")
    return record


def search_research_memory(
    backend: Any,
    query: str,
    ancestor_ids: list[str],
    *,
    kinds: list[str] | None = None,
    require_artifacts: bool = False,
    limit: int = 5,
    reader_node_id: str = "",
) -> dict:
    """Ancestor-scoped semantic search, post-filtered by kind / artifacts.

    Over-fetches from the underlying semantic search so the kind/artifact
    post-filter still returns up to ``limit`` matches.
    """
    overfetch = max(limit * 8, 40)
    raw = backend.search_memory(
        query,
        ancestor_ids,
        limit=overfetch,
        reader_node_id=reader_node_id,
    )
    kinds_set = set(kinds) if kinds else None
    out: list[dict] = []
    legacy_excluded = 0
    for r in raw.get("results", []) or []:
        record = _record_of(r)
        if record is None:
            legacy_excluded += 1
            continue
        if kinds_set is not None and record.kind not in kinds_set:
            continue
        if require_artifacts and not record.artifact_refs:
            continue
        out.append({**r, "record": record.model_dump(mode="json")})
        if len(out) >= limit:
            break
    if "provenance" not in raw:
        raise RuntimeError("memory backend omitted retrieval provenance")
    provenance = dict(raw["provenance"])
    filter_evidence = dict(provenance.get("filter_evidence") or {})
    filter_evidence["typed_filter"] = {
        "kinds": sorted(kinds_set) if kinds_set is not None else None,
        "require_artifacts": require_artifacts,
        "input_candidate_count": len(raw.get("results") or []),
        "legacy_records_excluded": legacy_excluded,
    }
    provenance["filter_evidence"] = filter_evidence
    provenance["returned_count"] = len(out)
    provenance["limit"] = limit
    provenance["query_digest"] = canonical_memory_digest(
        {
            "backend_query_digest": provenance["query_digest"],
            "kinds": sorted(kinds_set) if kinds_set is not None else None,
            "require_artifacts": require_artifacts,
            "limit": limit,
        }
    )
    return MemoryRetrievalV1(
        results=out,
        provenance=provenance,
    ).model_dump(mode="json")


def ancestor_typed_memory(
    backend: Any,
    ancestor_ids: list[str],
    *,
    kinds: list[str] | None = None,
    reader_node_id: str = "",
) -> list[dict]:
    """Deterministic, full handoff of ancestor entries of the given kinds.

    Uses ``bulk_get_node_memory`` (no semantic search). Order follows
    ``ancestor_ids`` (root → parent). This is the typed form of the loop's
    Tier-1(b) ancestor-core path.
    """
    by_node = backend.bulk_get_node_memory(
        list(ancestor_ids),
        reader_node_id=reader_node_id,
    ).get("by_node", {})
    kinds_set = set(kinds) if kinds else None
    out: list[dict] = []
    for aid in ancestor_ids:
        for e in by_node.get(aid, []) or []:
            md = e.get("metadata", {}) or {}
            record = _record_of({**e, "node_id": aid})
            if record is None:
                continue
            if kinds_set is not None and record.kind not in kinds_set:
                continue
            out.append({
                "entry_id": e.get("entry_id"),
                "record_id": record.record_id,
                "node_id": aid,
                "text": e.get("text", ""),
                "ts": e.get("ts"),
                "metadata": md,
                "record": record.model_dump(mode="json"),
            })
    return out


def fold_reproducibility(
    backend: Any, ancestor_ids: list[str], *, reader_node_id: str = ""
) -> dict[str, dict]:
    """Resolve the latest reproducibility status per target memory id.

    Reads append-only ``reproducibility_event`` entries in ancestor scope and
    keeps the most recent (by ``ts`` if present, else insertion order) per
    ``repro_target_id``.
    """
    events = ancestor_typed_memory(
        backend,
        ancestor_ids,
        kinds=["reproducibility_event"],
        reader_node_id=reader_node_id,
    )
    latest: dict[str, dict] = {}
    for i, e in enumerate(events):
        record = e["record"]
        target = record.get("repro_target_id")
        if not target:
            continue
        ts = e.get("ts")
        if not isinstance(ts, (int, float)):
            ts = i
        cur = latest.get(target)
        if cur is None or ts >= cur.get("_ts", -1):
            latest[target] = {"status": record.get("repro_status"), "_ts": ts}
    return {k: {"status": v["status"]} for k, v in latest.items()}
