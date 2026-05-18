"""ari-skill-memory: FastMCP dispatcher over the backend library.

The heavy lifting lives in ``ari_skill_memory.backends``; this module
only exposes the tools over the MCP transport.
"""
from __future__ import annotations

import logging
import os

import nest_asyncio
nest_asyncio.apply()

from mcp.server.fastmcp import FastMCP

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
