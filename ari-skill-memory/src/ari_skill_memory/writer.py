"""Typed write helpers (Phase 1 — index over node_report).

Thin layer over the existing ``backend.add_memory``: it stamps a typed
``kind`` + minimal provenance refs into the entry metadata. It does NOT
modify the backend or re-store node_report fields — heavy provenance stays
in node_report (pointed at by ``node_report_ref``).

Caller is a loop/pipeline hook (PLAN §2 principle 8/9), never relied upon to
be an LLM action. CoW still applies: ``node_id`` must equal
``$ARI_CURRENT_NODE_ID`` at write time.
"""
from __future__ import annotations

from typing import Any

from .schemas import MEMORY_KINDS, REPRO_STATUSES, ArtifactRef


def _refs_payload(artifact_refs: list[ArtifactRef] | list[dict] | None) -> list[dict]:
    out: list[dict] = []
    for a in artifact_refs or []:
        out.append(a.to_dict() if isinstance(a, ArtifactRef) else dict(a))
    return out


def add_typed_memory(
    backend: Any,
    node_id: str,
    kind: str,
    text: str,
    *,
    metric_ptr: dict | None = None,
    artifact_refs: list[ArtifactRef] | list[dict] | None = None,
    node_report_ref: dict | None = None,
    extra: dict | None = None,
) -> dict:
    """Write one typed memory entry via ``backend.add_memory``.

    Stamps both ``type`` (legacy/nested, used by existing readers incl. the
    loop's Tier-1(b) filter) and ``mem_kind`` (forward-compat top-level facet
    for Phase 2 Letta-side filtering) so neither path silently misses it.
    """
    if kind not in MEMORY_KINDS:
        raise ValueError(f"unknown MemoryKind {kind!r}")
    metadata: dict = {
        "type": kind,
        "mem_kind": kind,
        "metric_ptr": metric_ptr,
        "artifact_refs": _refs_payload(artifact_refs),
        "node_report_ref": node_report_ref,
    }
    if extra:
        metadata.update(extra)
    return backend.add_memory(node_id, text, metadata)


def add_experiment_result(backend, node_id, text, **kw) -> dict:
    return add_typed_memory(backend, node_id, "experiment_result", text, **kw)


def add_failure_case(backend, node_id, text, **kw) -> dict:
    return add_typed_memory(backend, node_id, "failure_case", text, **kw)


def add_procedure_memory(backend, node_id, text, **kw) -> dict:
    return add_typed_memory(backend, node_id, "procedure", text, **kw)


def add_reflection(backend, node_id, text, *, confidence: float | None = None, **kw) -> dict:
    extra = kw.pop("extra", None) or {}
    if confidence is not None:
        extra["confidence"] = confidence
    return add_typed_memory(backend, node_id, "reflection", text, extra=extra, **kw)


def add_reproducibility_event(
    backend,
    node_id: str,
    target_memory_id: str,
    status: str,
    *,
    artifact_refs: list[ArtifactRef] | list[dict] | None = None,
    text: str | None = None,
) -> dict:
    """Append-only reproducibility status event (PLAN §5.4 — never mutates).

    The target memory stays byte-stable; ``retriever.fold_reproducibility``
    resolves the latest status per target at read time.
    """
    if status not in REPRO_STATUSES:
        raise ValueError(f"unknown ReproStatus {status!r}")
    body = text or f"reproducibility: {target_memory_id} -> {status}"
    return add_typed_memory(
        backend,
        node_id,
        "reproducibility_event",
        body,
        artifact_refs=artifact_refs,
        extra={"repro_target_id": target_memory_id, "repro_status": status},
    )
