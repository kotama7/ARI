"""ari-skill-memory: FastMCP dispatcher over the backend library.

The heavy lifting lives in ``ari_skill_memory.backends``; this module
only exposes the tools over the MCP transport.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ari.public.call_context import (
    CallContextAuthorizationError,
    ToolCallContextV1,
    verify_tool_context,
)
from ari_skill_memory import audit as _audit
from ari_skill_memory import consolidation, context_builder, retriever, writer
from ari_skill_memory.backends import get_backend

log = logging.getLogger(__name__)

mcp = FastMCP("memory-skill")


def _backend():
    return get_backend()


def _authorized_context(
    raw_context: dict | None,
    *,
    tool_name: str,
    requirement: str = "node",
) -> ToolCallContextV1:
    """Verify the transport-issued context capability for one tool."""

    # Literal by design: manifest conformance statically inventories every
    # provider environment read; this name is injected and reserved by core.
    authority_key = os.environ.get("ARI_CONTEXT_AUTHORITY_KEY", "")
    if not authority_key:
        raise PermissionError("ARI call-context authority is unavailable")
    try:
        return verify_tool_context(
            raw_context,
            tool_name=tool_name,
            authority_key=authority_key,
            requirement=requirement,
        )
    except CallContextAuthorizationError as exc:
        raise PermissionError(f"ARI call context refused: {exc}") from exc


def _require_self(context: ToolCallContextV1, node_id: str) -> None:
    node = context.node_context
    if node is None or node.node_id != node_id:
        raise PermissionError("node write target is not the authorized self node")


def _require_readable(
    context: ToolCallContextV1,
    node_ids: list[str],
    *,
    include_self: bool,
) -> None:
    node = context.node_context
    if node is None:
        raise PermissionError("node context is required for memory reads")
    allowed = set(node.ancestor_node_ids)
    if include_self:
        allowed.add(node.node_id)
    refused = sorted(set(node_ids) - allowed)
    if refused:
        raise PermissionError(
            f"memory read crosses the authorized lineage: {refused}"
        )


def _record_context(context: ToolCallContextV1, tool_name: str) -> dict:
    node = context.node_context
    if node is None:
        raise PermissionError("node context is required for memory writes")
    return {
        "run_id": context.run_id,
        "ancestor_ids": list(node.ancestor_node_ids),
        "created_by_tool_ref": f"memory-skill:{tool_name}",
    }


def _checkpoint_root() -> Path:
    value = os.environ.get("ARI_CHECKPOINT_DIR", "")
    if not value:
        raise RuntimeError("ARI_CHECKPOINT_DIR is required for memory provenance")
    root = Path(value).resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise RuntimeError("ARI_CHECKPOINT_DIR must be a real directory")
    return root


# ─ Node-scope MCP tools ───────────────────────────────────────────────

@mcp.tool()
def add_memory(
    node_id: str,
    text: str,
    metadata: dict | None = None,
    ari_context: dict | None = None,
) -> dict:
    """Add a node-scoped memory entry.

    The transport-signed NodeContext must authorize ``node_id`` as self.
    """
    context = _authorized_context(ari_context, tool_name="add_memory")
    _require_self(context, node_id)
    return writer.add_observation(
        _backend(),
        node_id,
        text,
        attributes=metadata,
        **_record_context(context, "add_memory"),
    )


@mcp.tool()
def search_memory(
    query: str,
    ancestor_ids: list[str],
    limit: int = 5,
    ari_context: dict | None = None,
) -> dict:
    """Search ancestor-scoped memory.

    Returns entries whose ``node_id`` is in ``ancestor_ids``, ranked by
    relevance. Siblings and children are never returned. Entries belonging to
    a node ARI governance logically erased come back LABELLED
    (``erased`` / ``erasure_event_id`` / ``erasure_note``, at the top level
    and inside ``metadata``), never silently dropped — the backend applies
    that marker, so every consumer sees it, not only this MCP surface. See
    :mod:`ari_skill_memory.erasure`.
    """
    context = _authorized_context(ari_context, tool_name="search_memory")
    _require_readable(context, ancestor_ids, include_self=False)
    assert context.node_context is not None
    return _backend().search_memory(
        query,
        ancestor_ids,
        limit,
        reader_node_id=context.node_context.node_id,
    )


@mcp.tool()
def get_node_memory(node_id: str, ari_context: dict | None = None) -> dict:
    """Return all entries for a single node.

    Labelled with the erasure marker when that node was logically erased
    (the entries are still returned — erasure withdraws the standing of a
    judgment, not the measurements).
    """
    context = _authorized_context(ari_context, tool_name="get_node_memory")
    _require_readable(context, [node_id], include_self=True)
    assert context.node_context is not None
    return _backend().get_node_memory(
        node_id,
        reader_node_id=context.node_context.node_id,
    )


# ─ Core-memory introspection ───────────────────────────────────

@mcp.tool()
def get_experiment_context(ari_context: dict | None = None) -> dict:
    """Return stable, experiment-level facts from Letta core memory."""
    _authorized_context(
        ari_context,
        tool_name="get_experiment_context",
        requirement="run",
    )
    return _backend().get_experiment_context()


# ─ Typed research-memory tools (Phase 1) ──────────────────────────────
# Callers are loop/pipeline hooks (PLAN §2 principle 8/9), not LLM pulls.
# Write tools require a transport-signed NodeContext and can only target self.

@mcp.tool()
def add_experiment_result(
    node_id: str,
    text: str,
    metric_ptr: dict | None = None,
    artifact_refs: list[dict] | None = None,
    node_report_ref: dict | None = None,
    ari_context: dict | None = None,
) -> dict:
    """Record a typed experiment_result (CoW: self node only)."""
    context = _authorized_context(ari_context, tool_name="add_experiment_result")
    _require_self(context, node_id)
    return writer.add_experiment_result(
        _backend(), node_id, text, metric_ptr=metric_ptr,
        artifact_refs=artifact_refs, node_report_ref=node_report_ref,
        artifact_root=_checkpoint_root(),
        **_record_context(context, "add_experiment_result"),
    )


@mcp.tool()
def add_failure_case(
    node_id: str,
    text: str,
    artifact_refs: list[dict] | None = None,
    node_report_ref: dict | None = None,
    ari_context: dict | None = None,
) -> dict:
    """Record a typed failure_case (CoW: self node only)."""
    context = _authorized_context(ari_context, tool_name="add_failure_case")
    _require_self(context, node_id)
    return writer.add_failure_case(
        _backend(), node_id, text,
        artifact_refs=artifact_refs, node_report_ref=node_report_ref,
        artifact_root=_checkpoint_root(),
        **_record_context(context, "add_failure_case"),
    )


@mcp.tool()
def add_procedure_memory(
    node_id: str,
    text: str,
    node_report_ref: dict | None = None,
    ari_context: dict | None = None,
) -> dict:
    """Record a reusable procedure (CoW: self node only)."""
    context = _authorized_context(ari_context, tool_name="add_procedure_memory")
    _require_self(context, node_id)
    return writer.add_procedure_memory(
        _backend(), node_id, text, node_report_ref=node_report_ref,
        **_record_context(context, "add_procedure_memory"),
    )


@mcp.tool()
def add_reflection(
    node_id: str,
    text: str,
    confidence: float | None = None,
    node_report_ref: dict | None = None,
    ari_context: dict | None = None,
) -> dict:
    """Record a reflection (CoW: self node only). Not usable for paper claims."""
    context = _authorized_context(ari_context, tool_name="add_reflection")
    _require_self(context, node_id)
    return writer.add_reflection(
        _backend(), node_id, text, confidence=confidence,
        node_report_ref=node_report_ref,
        **_record_context(context, "add_reflection"),
    )


@mcp.tool()
def add_reproducibility_event(
    node_id: str,
    target_memory_id: str,
    status: str,
    artifact_refs: list[dict] | None = None,
    text: str | None = None,
    ari_context: dict | None = None,
) -> dict:
    """Append an append-only reproducibility status event (CoW: self node only)."""
    context = _authorized_context(
        ari_context,
        tool_name="add_reproducibility_event",
    )
    _require_self(context, node_id)
    return writer.add_reproducibility_event(
        _backend(), node_id, target_memory_id, status,
        artifact_refs=artifact_refs, text=text,
        artifact_root=_checkpoint_root(),
        **_record_context(context, "add_reproducibility_event"),
    )


@mcp.tool()
def search_research_memory(
    query: str,
    ancestor_ids: list[str],
    kinds: list[str] | None = None,
    require_artifacts: bool = False,
    limit: int = 5,
    ari_context: dict | None = None,
) -> dict:
    """Ancestor-scoped typed search, filtered by kind / artifact presence.

    Erased nodes' entries are labelled, not hidden (see ``search_memory``)."""
    context = _authorized_context(ari_context, tool_name="search_research_memory")
    _require_readable(context, ancestor_ids, include_self=True)
    return retriever.search_research_memory(
        _backend(), query, ancestor_ids, kinds=kinds,
        require_artifacts=require_artifacts, limit=limit,
        reader_node_id=context.node_context.node_id if context.node_context else "",
    )


@mcp.tool()
def get_verified_context(
    ancestor_ids: list[str],
    purpose: str = "paper",
    limit: int | None = None,
    ari_context: dict | None = None,
) -> dict:
    """Artifact-grounded, reproducibility-aware context for paper/figure use.

    The PUSH path: its claim lists ground paper assertions, so erased
    ancestors are hard-excluded from them (inside ``build_verified_context``,
    which every caller — this tool and the in-process funnel alike — goes
    through). ``limitations`` deliberately keeps them, labelled: the honest
    record of a direction that was later invalidated is exactly what a
    limitations section is for."""
    context = _authorized_context(ari_context, tool_name="get_verified_context")
    _require_readable(context, ancestor_ids, include_self=True)
    return context_builder.build_verified_context(
        _backend(),
        ancestor_ids,
        purpose=purpose,
        limit=limit,
        reader_node_id=context.node_context.node_id if context.node_context else "",
    )


@mcp.tool()
def audit_memory(
    experiments_root: str,
    run_id: str | None = None,
    ari_context: dict | None = None,
) -> dict:
    """Verify recorded provenance (sha256) against disk for a checkpoint."""
    context = _authorized_context(
        ari_context,
        tool_name="audit_memory",
        requirement="run",
    )
    if run_id is not None and run_id != context.run_id:
        raise PermissionError("audit run_id does not match the authorized run")
    authorized_run_id = run_id or context.run_id
    results = _audit.audit_checkpoint(experiments_root, authorized_run_id)
    return {"summary": _audit.summarize(results), "results": results}


@mcp.tool()
def consolidate_node_memory(
    node_id: str,
    node_report: dict,
    work_dir: str,
    run_id: str | None = None,
    ari_context: dict | None = None,
) -> dict:
    """Derive + write typed memory from a node_report at node end (CoW: self).

    Runs the pure consolidation logic server-side and writes the resulting
    experiment_result / failure_case / reflection entries via the typed
    writer. Caller is the ari-core node-end hook.
    """
    context = _authorized_context(ari_context, tool_name="consolidate_node_memory")
    _require_self(context, node_id)
    if run_id is not None and run_id != context.run_id:
        raise PermissionError("consolidation run_id does not match call context")
    authorized_run_id = run_id or context.run_id
    specs = consolidation.consolidate_from_node_report(
        node_report, work_dir, run_id=authorized_run_id
    )
    results = consolidation.write_consolidated(
        _backend(),
        node_id,
        specs,
        run_id=authorized_run_id,
        ancestor_ids=list(context.node_context.ancestor_node_ids)
        if context.node_context
        else [],
        artifact_root=Path(work_dir),
        created_by_tool_ref="memory-skill:consolidate_node_memory",
    )
    return {
        "written": [
            {
                "kind": s["kind"],
                "ok": r.get("ok", False),
                "id": r.get("id"),
                "record_id": r.get("record_id"),
                "record_digest": r.get("record_digest"),
                "deduplicated": bool(r.get("deduplicated", False)),
            }
            for s, r in zip(specs, results)
        ]
    }

def main() -> None:  # pragma: no cover - server entry
    # Fail fast at startup if the backend is unhealthy.
    try:
        h = _backend().health()
        if not h.get("ok"):
            log.error("ari-skill-memory health check failed: %s", h)
    except Exception as e:
        log.error("ari-skill-memory startup failed: %s", e)
        raise
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
