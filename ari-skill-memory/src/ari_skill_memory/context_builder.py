"""Verified context for paper / figure generation (Phase 1).

"Artifact-grounded generation" (PLAN §4.5 / §8.4): paper claims must rest on
artifact-grounded, ideally reproduced, memory — not free-form reflection.
``build_verified_context`` ranks ancestor-scoped typed memory by evidence
strength and folds in append-only reproducibility status:

  priority: rerun_passed > artifact-grounded > (ungrounded → supplementary)

Callers are the paper/figure pipeline hooks (never an LLM pull).
"""
from __future__ import annotations

from typing import Any

from . import erasure, retriever

# Strongest first. paper_claim / experiment_result carry claims; failure_case
# is a limitation, not a claim; reflection is supplementary only.
_CLAIM_KINDS = ("paper_claim", "experiment_result")


def _evidence_rank(entry: dict, repro: dict[str, dict]) -> int:
    """0 = strongest. Lower sorts first."""
    md = entry.get("metadata", {}) or {}
    status = (repro.get(entry.get("entry_id") or "", {}) or {}).get("status")
    grounded = bool(md.get("artifact_refs"))
    if status == "rerun_passed":
        return 0
    if grounded:
        return 1
    if status == "rerun_failed":
        return 3  # demote: claimed but failed reproduction
    return 2      # ungrounded, unverified


def build_verified_context(
    backend: Any,
    ancestor_ids: list[str],
    *,
    purpose: str = "paper",
    limit: int | None = None,
) -> dict:
    """Build artifact-grounded, reproducibility-aware context for ``ancestor_ids``.

    Returns:
      - ``claims``      : ranked claim-bearing memory (each annotated with
                          ``grounded`` and ``repro_status``).
      - ``limitations`` : failure_case memory (for honest limitations).
      - ``usable_for_claims`` : the subset safe to assert in paper body
                          (grounded and not rerun_failed).
    """
    # Selective erasure (plan 10 §3, settled): a node whose generator or
    # scoring policy was retired must not GROUND a paper assertion, so the
    # claim lists are built from the surviving ancestors only. Limitations are
    # built from the full set — the honest record of a direction that was
    # later invalidated is exactly what a limitations section is for, and its
    # entries carry the backend's erasure marker. Filtering here rather than
    # at the MCP tool covers the in-process funnel callers too. Inert without
    # the rollup (non-RQGM checkpoints).
    grounding_ids = erasure.drop_erased(ancestor_ids)
    repro = retriever.fold_reproducibility(backend, grounding_ids)
    claim_entries = retriever.ancestor_typed_memory(
        backend, grounding_ids, kinds=list(_CLAIM_KINDS)
    )
    failures = retriever.ancestor_typed_memory(
        backend, ancestor_ids, kinds=["failure_case"]
    )

    annotated: list[dict] = []
    for e in claim_entries:
        md = e.get("metadata", {}) or {}
        status = (repro.get(e.get("entry_id") or "", {}) or {}).get("status")
        annotated.append({
            "entry_id": e.get("entry_id"),
            "node_id": e.get("node_id"),
            "text": e.get("text", ""),
            "kind": md.get("mem_kind") or md.get("type"),
            "grounded": bool(md.get("artifact_refs")),
            "artifact_refs": md.get("artifact_refs") or [],
            "repro_status": status,
        })
    annotated.sort(key=lambda e: _evidence_rank(
        {"metadata": {"artifact_refs": e["artifact_refs"]}, "entry_id": e["entry_id"]}, repro
    ))
    if limit is not None:
        annotated = annotated[:limit]

    usable = [
        e for e in annotated
        if e["grounded"] and e["repro_status"] != "rerun_failed"
    ]

    return {
        "claims": annotated,
        "limitations": [
            {"node_id": f.get("node_id"), "text": f.get("text", "")} for f in failures
        ],
        "usable_for_claims": usable,
    }
