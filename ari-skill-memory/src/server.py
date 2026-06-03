"""ari-skill-memory: FastMCP dispatcher over the backend library.

The heavy lifting lives in ``ari_skill_memory.backends``; this module
only exposes the tools over the MCP transport.
"""
from __future__ import annotations

import logging
import os
import sys

import nest_asyncio

# Python 3.14 + nest-asyncio patched event loops triggers anyio/asyncio glue that
# can fail with AttributeError ('NoneType' has no attribute 'set_name') inside
# mcp.run(); stdio FastMCP does not rely on nested loop patching on 3.14+.
if sys.version_info < (3, 14):
    nest_asyncio.apply()

from mcp.server.fastmcp import FastMCP

from ari_skill_memory import audit as _audit
from ari_skill_memory import consolidation, context_builder, retriever, writer
from ari_skill_memory.backends import get_backend

log = logging.getLogger(__name__)

mcp = FastMCP("memory-skill")


def _backend():
    return get_backend()


# ─ Node-scope MCP tools ───────────────────────────────────────────────

@mcp.tool()
def add_memory(node_id: str, text: str, metadata: dict | None = None) -> dict:
    """Add a node-scoped memory entry.

    CoW precondition: ``node_id`` must equal ``$ARI_CURRENT_NODE_ID``.
    """
    return _backend().add_memory(node_id, text, metadata)


@mcp.tool()
def search_memory(
    query: str, ancestor_ids: list[str], limit: int = 5
) -> dict:
    """Search ancestor-scoped memory.

    Returns entries whose ``node_id`` is in ``ancestor_ids``, ranked by
    relevance. Siblings and children are never returned.
    """
    return _backend().search_memory(query, ancestor_ids, limit)


@mcp.tool()
def get_node_memory(node_id: str) -> dict:
    """Return all entries for a single node."""
    return _backend().get_node_memory(node_id)


@mcp.tool()
def clear_node_memory(node_id: str) -> dict:
    """Clear a node's entries (CoW-protected — self only)."""
    return _backend().clear_node_memory(node_id)


# ─ Core-memory introspection ───────────────────────────────────

@mcp.tool()
def get_experiment_context() -> dict:
    """Return stable, experiment-level facts from Letta core memory."""
    return _backend().get_experiment_context()


# ─ Typed research-memory tools (Phase 1) ──────────────────────────────
# Callers are loop/pipeline hooks (PLAN §2 principle 8/9), not LLM pulls.
# Write tools are CoW-guarded (node_id must equal $ARI_CURRENT_NODE_ID); the
# ari-core MCPClient routes them through the _set_current_node bridge — keep
# their names in MCPClient._COW_TOOLS in sync.

@mcp.tool()
def add_experiment_result(
    node_id: str,
    text: str,
    metric_ptr: dict | None = None,
    artifact_refs: list[dict] | None = None,
    node_report_ref: dict | None = None,
) -> dict:
    """Record a typed experiment_result (CoW: self node only)."""
    return writer.add_experiment_result(
        _backend(), node_id, text, metric_ptr=metric_ptr,
        artifact_refs=artifact_refs, node_report_ref=node_report_ref,
    )


@mcp.tool()
def add_failure_case(
    node_id: str,
    text: str,
    artifact_refs: list[dict] | None = None,
    node_report_ref: dict | None = None,
) -> dict:
    """Record a typed failure_case (CoW: self node only)."""
    return writer.add_failure_case(
        _backend(), node_id, text,
        artifact_refs=artifact_refs, node_report_ref=node_report_ref,
    )


@mcp.tool()
def add_procedure_memory(
    node_id: str,
    text: str,
    node_report_ref: dict | None = None,
) -> dict:
    """Record a reusable procedure (CoW: self node only)."""
    return writer.add_procedure_memory(
        _backend(), node_id, text, node_report_ref=node_report_ref,
    )


@mcp.tool()
def add_reflection(
    node_id: str,
    text: str,
    confidence: float | None = None,
    node_report_ref: dict | None = None,
) -> dict:
    """Record a reflection (CoW: self node only). Not usable for paper claims."""
    return writer.add_reflection(
        _backend(), node_id, text, confidence=confidence,
        node_report_ref=node_report_ref,
    )


@mcp.tool()
def add_reproducibility_event(
    node_id: str,
    target_memory_id: str,
    status: str,
    artifact_refs: list[dict] | None = None,
    text: str | None = None,
) -> dict:
    """Append an append-only reproducibility status event (CoW: self node only)."""
    return writer.add_reproducibility_event(
        _backend(), node_id, target_memory_id, status,
        artifact_refs=artifact_refs, text=text,
    )


@mcp.tool()
def search_research_memory(
    query: str,
    ancestor_ids: list[str],
    kinds: list[str] | None = None,
    require_artifacts: bool = False,
    limit: int = 5,
) -> dict:
    """Ancestor-scoped typed search, filtered by kind / artifact presence."""
    return retriever.search_research_memory(
        _backend(), query, ancestor_ids, kinds=kinds,
        require_artifacts=require_artifacts, limit=limit,
    )


@mcp.tool()
def get_verified_context(
    ancestor_ids: list[str], purpose: str = "paper", limit: int | None = None
) -> dict:
    """Artifact-grounded, reproducibility-aware context for paper/figure use."""
    return context_builder.build_verified_context(
        _backend(), ancestor_ids, purpose=purpose, limit=limit,
    )


@mcp.tool()
def audit_memory(experiments_root: str, run_id: str | None = None) -> dict:
    """Verify recorded provenance (sha256) against disk for a checkpoint."""
    results = _audit.audit_checkpoint(experiments_root, run_id)
    return {"summary": _audit.summarize(results), "results": results}


@mcp.tool()
def consolidate_node_memory(
    node_id: str,
    node_report: dict,
    work_dir: str,
    run_id: str | None = None,
) -> dict:
    """Derive + write typed memory from a node_report at node end (CoW: self).

    Runs the pure consolidation logic server-side and writes the resulting
    experiment_result / failure_case / reflection entries via the typed
    writer. Caller is the ari-core node-end hook.
    """
    specs = consolidation.consolidate_from_node_report(
        node_report, work_dir, run_id=run_id
    )
    results = consolidation.write_consolidated(_backend(), node_id, specs)
    return {
        "written": [
            {"kind": s["kind"], "ok": r.get("ok", False), "id": r.get("id")}
            for s, r in zip(specs, results)
        ]
    }


@mcp.tool()
def _set_current_node(node_id: str) -> dict:
    """ari-core→skill CoW bridge.

    Because the stdio-pooled memory skill inherits its env at spawn time,
    this tool is called by the agent loop immediately before each memory
    write so the skill process's ``$ARI_CURRENT_NODE_ID`` stays in sync
    with the BFTS node currently executing."""
    if not node_id:
        return {"ok": False, "error": "node_id required"}
    os.environ["ARI_CURRENT_NODE_ID"] = str(node_id)
    return {"ok": True, "node_id": str(node_id)}


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
