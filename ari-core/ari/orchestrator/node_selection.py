"""Common node-selection helpers shared by transform / generate_ear / bfts.

`filter_nodes` is the single source of truth for "which nodes contribute
downstream" — used identically by `nodes_to_science_data` (criteria=
``for_synthesis``), the EAR `code/` builder (``for_code``), the EVOLUTION.md
narrative (``for_narrative``), and bfts.expand sibling deduplication.

`select_source_files_for_publication` is the *file-level* selection used by
both the EAR `code/` writer and transform's LLM-input source loader: both
must see the exact same bytes (FR-SS-5).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

logger = logging.getLogger(__name__)


Criteria = Literal["for_synthesis", "for_code", "for_narrative"]


# ── per-criterion predicates ─────────────────────────────────────────────

def is_relevant_for_synthesis(node: dict, report: dict | None) -> bool:
    """Should this node be passed into `nodes_to_science_data`'s LLM prompt?"""
    if node.get("has_real_data") and node.get("metrics"):
        return True
    if report and report.get("self_assessment", {}).get("succeeded"):
        return True
    if report:
        fc = report.get("files_changed") or {}
        if fc.get("added") or fc.get("modified"):
            return True
    return False


def contributes_code(node: dict, report: dict | None) -> bool:
    """Does this node contribute publishable code/data files?

    Returns True if the node's report shows non-empty files_changed.added
    or modified. With no report we conservatively return True (legacy
    checkpoint fallback).
    """
    if not report:
        return True  # legacy fallback — be conservative.
    if report.get("migration_source") == "auto":
        # Auto-reconstructed reports are not trustworthy enough to *exclude*
        # nodes; treat as conservative-include (FR-NS-FALLBACK-2).
        return True
    fc = report.get("files_changed") or {}
    return bool(fc.get("added") or fc.get("modified"))


def is_narrative_step(node: dict, report: dict | None) -> bool:
    """Should this node show up as a step in EVOLUTION.md?"""
    if not report:
        # Legacy fallback: include unless explicitly failed/abandoned.
        status = node.get("status")
        if status in ("failed", "abandoned"):
            return False
        return True
    status = node.get("status") or report.get("status")
    return status == "success"


_PREDICATES: dict[Criteria, Callable[[dict, dict | None], bool]] = {
    "for_synthesis": is_relevant_for_synthesis,
    "for_code": contributes_code,
    "for_narrative": is_narrative_step,
}


# ── public dispatcher ────────────────────────────────────────────────────

def filter_nodes(
    nodes: list[dict],
    reports: dict[str, dict],
    criteria: Criteria,
    *,
    always_include_node_ids: Iterable[str] = (),
) -> list[dict]:
    """Apply the *criteria* predicate to *nodes*, preserving order.

    *always_include_node_ids* always pass (best-node guard, FR-NS-FALLBACK-3).

    Emits a warning log when more than 50% of *successful* nodes are dropped
    (FR-NS-FALLBACK-5) — a sanity signal for "filter too aggressive".
    """
    pred = _PREDICATES[criteria]
    always = set(always_include_node_ids or ())
    out: list[dict] = []
    for n in nodes:
        nid = n.get("id")
        if nid in always:
            out.append(n)
            continue
        if pred(n, reports.get(nid)):
            out.append(n)

    # FR-NS-FALLBACK-5: surface anomalous skip rates.
    successful = [n for n in nodes if n.get("status") == "success"]
    if successful:
        kept_ids = {n.get("id") for n in out}
        kept_success = [n for n in successful if n.get("id") in kept_ids]
        skipped = len(successful) - len(kept_success)
        if skipped * 2 > len(successful):
            logger.warning(
                "filter_nodes(%s): skipped %d/%d successful nodes (>50%%) — "
                "filter may be too aggressive or reports may be stale",
                criteria, skipped, len(successful),
            )
    return out


def collect_excluded(
    nodes: list[dict],
    reports: dict[str, dict],
    criteria: Criteria,
    *,
    always_include_node_ids: Iterable[str] = (),
) -> list[dict]:
    """Return [{node_id, criterion, reason}] for nodes that *failed* the filter.

    Mirrors `filter_nodes` but inverts the result, with a short reason string
    so `_provenance.json::excluded_nodes` and warning logs can explain why.
    """
    pred = _PREDICATES[criteria]
    always = set(always_include_node_ids or ())
    excluded: list[dict] = []
    for n in nodes:
        nid = n.get("id")
        if nid in always:
            continue
        if pred(n, reports.get(nid)):
            continue
        report = reports.get(nid)
        reason = _explain_exclusion(criteria, n, report)
        excluded.append({"node_id": nid, "criterion": criteria, "reason": reason})
    return excluded


def _explain_exclusion(criteria: Criteria, node: dict, report: dict | None) -> str:
    if criteria == "for_code":
        if not report:
            return "no node_report and would-be conservative include disabled"
        fc = (report.get("files_changed") or {})
        if not (fc.get("added") or fc.get("modified")):
            return "files_changed.added and modified are both empty"
        return "filter declined"
    if criteria == "for_synthesis":
        if not node.get("has_real_data"):
            return "has_real_data=false and self_assessment did not certify success"
        if not node.get("metrics"):
            return "metrics empty"
        return "filter declined"
    if criteria == "for_narrative":
        status = node.get("status") or (report or {}).get("status")
        return f"status={status!r} is not success"
    return "filter declined"


# ── parent chain ─────────────────────────────────────────────────────────

def build_parent_chain(best_node_id: str, nodes: list[dict]) -> list[dict]:
    """Return [root, ..., best] in order by walking parent_id pointers.

    Tolerates missing nodes (broken chain) — stops walking when parent is
    not found. Always includes the best node itself if present.
    """
    by_id = {n.get("id"): n for n in nodes}
    if best_node_id not in by_id:
        return []
    chain: list[dict] = []
    cur_id: str | None = best_node_id
    seen: set[str] = set()
    while cur_id and cur_id in by_id and cur_id not in seen:
        seen.add(cur_id)
        chain.append(by_id[cur_id])
        cur_id = by_id[cur_id].get("parent_id")
    chain.reverse()
    return chain


# ── source-file selection (file I/O free) ─────────────────────────────────

@dataclass(frozen=True)
class SourceSelection:
    """Pure-metadata file selection. ``files`` is sorted by rel_path."""
    files: tuple[tuple[str, str], ...] = ()  # ((node_id, rel_path), ...)
    excluded_nodes: tuple[dict, ...] = ()

    def as_dict(self) -> dict:
        return {
            "files": [{"node_id": nid, "rel_path": rel} for nid, rel in self.files],
            "excluded_nodes": list(self.excluded_nodes),
        }


def select_source_files_for_publication(
    nodes: list[dict],
    reports: dict[str, dict],
    best_node_id: str,
) -> SourceSelection:
    """Decide which (node_id, rel_path) pairs land in the published code/.

    File-I/O free; consults only node + node_report metadata. Walks the best
    node's ancestor chain in depth order and overlays each node's
    ``files_changed``: a deeper node's added/modified file wins on a path
    collision, and a deeper node's *deletion* removes an ancestor's file.
    Together this reconstructs the best node's actual work_dir, mirroring how
    a child runs inside a physical copy of its parent's tree.

    Publication is chain-only: nodes off the best node's lineage are never
    published even if their results are reported by the all-nodes synthesis
    set. Such off-chain contributing nodes are recorded in
    ``excluded_nodes`` so that asymmetry is auditable rather than silent.

    Falls back to enumerating the *best* node's own files_changed if the
    chain has no contributing nodes (or the best report itself is missing).
    """
    chain = build_parent_chain(best_node_id, nodes)
    contributing = filter_nodes(
        chain, reports, "for_code",
        always_include_node_ids={best_node_id},
    )
    excluded = list(collect_excluded(
        chain, reports, "for_code",
        always_include_node_ids={best_node_id},
    ))

    # rel_path -> (node_id, depth). Deletions are applied from the *full*
    # chain (a delete-only node carries no added/modified and so is filtered
    # out of `contributing`); added/modified only from contributing nodes.
    contributing_ids = {n.get("id") for n in contributing}
    selection: dict[str, tuple[str, int]] = {}
    for node in chain:  # root -> best, ascending depth
        nid = node.get("id")
        report = reports.get(nid)
        if not report:
            continue
        depth = int(node.get("depth", 0) or 0)
        fc = report.get("files_changed") or {}
        if nid in contributing_ids:
            for entry in (fc.get("added") or []) + (fc.get("modified") or []):
                rel = entry.get("path") if isinstance(entry, dict) else None
                if not rel:
                    continue
                existing = selection.get(rel)
                if existing is None or depth >= existing[1]:
                    selection[rel] = (nid, depth)
        # A deletion at this depth overlays away any shallower contribution.
        for entry in (fc.get("deleted") or []):
            rel = entry.get("path") if isinstance(entry, dict) else entry
            if rel:
                selection.pop(rel, None)

    files = tuple(sorted(
        ((nid, rel) for rel, (nid, _depth) in selection.items()),
        key=lambda x: x[1],
    ))

    # FR-NS: record off-chain nodes that would contribute code but lie
    # outside the published lineage, so _provenance.json::excluded_nodes
    # surfaces the chain-only/all-nodes asymmetry.
    chain_ids = {n.get("id") for n in chain}
    off_chain = [n for n in nodes if n.get("id") not in chain_ids]
    for n in filter_nodes(off_chain, reports, "for_code"):
        excluded.append({
            "node_id": n.get("id"),
            "criterion": "for_code",
            "reason": "off the best-node lineage; results may be reported "
                      "but source is not part of the published chain",
        })

    return SourceSelection(
        files=files,
        excluded_nodes=tuple(excluded),
    )


# ── source-file loader (does file I/O) ───────────────────────────────────

def load_selected_sources(
    selection: SourceSelection,
    *,
    work_dir_for: Callable[[str], Path],
    size_budget: int | None = None,
) -> dict[str, dict]:
    """Read bytes for every (node_id, rel_path) in *selection*.

    *work_dir_for* maps a node_id to its on-disk work_dir Path. We pass a
    callable rather than a PathManager so callers can inject test fixtures
    without mocking the whole class.

    Returns ``{rel_path: {"bytes", "sha256", "size", "from_node_id"}}``.

    If *size_budget* is set, files are added in selection order until the
    budget is exhausted; remaining files are silently skipped (caller can
    look at the difference in keys to know which were dropped).
    """
    out: dict[str, dict] = {}
    total = 0
    for node_id, rel_path in selection.files:
        try:
            full = work_dir_for(node_id) / rel_path
        except Exception:
            continue
        if not full.is_file():
            continue
        try:
            size = full.stat().st_size
        except OSError:
            continue
        if size_budget is not None and total + size > size_budget:
            continue
        try:
            data = full.read_bytes()
        except OSError:
            continue
        out[rel_path] = {
            "bytes": data,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": size,
            "from_node_id": node_id,
        }
        total += size
    return out
