"""
ari-skill-memory: Node-scoped memory MCP server

Design principles:
- Each memory entry has a node_id tag
- search_memory returns only memories from nodes in the ancestor_ids list
- → Only parent node memories are accessible; sibling/child memories are hidden
- Memories are persisted to file (~/.ari/memory_store.jsonl)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import nest_asyncio
nest_asyncio.apply()

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("memory-skill")

STORE_PATH = Path(os.environ.get("ARI_MEMORY_PATH", "~/.ari/memory_store.jsonl")).expanduser()


def _load_all() -> list[dict]:
    if not STORE_PATH.exists():
        return []
    entries = []
    for line in STORE_PATH.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def _append(entry: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STORE_PATH.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _score(text: str, query: str) -> int:
    """Simple keyword match score (deterministic)."""
    q_words = [w.lower() for w in query.split() if w]
    t_lower = text.lower()
    return sum(1 for w in q_words if w in t_lower)


@mcp.tool()
def add_memory(node_id: str, text: str, metadata: dict | None = None) -> dict:
    """Add a memory entry scoped to node_id.

    Args:
        node_id: ID of the node that owns this entry
        text: Text to store
        metadata: Optional metadata (type, step, etc.)

    Returns:
        ok: True
    """
    entry = {
        "node_id": node_id,
        "text": text,
        "metadata": metadata or {},
        "ts": time.time(),
    }
    _append(entry)
    return {"ok": True}


@mcp.tool()
def search_memory(query: str, ancestor_ids: list[str], limit: int = 5) -> dict:
    """Search only memories from ancestor nodes.

    Does not return memories from sibling, child, or unrelated nodes.

    Args:
        query: Search query (keyword match)
        ancestor_ids: List of node IDs allowed to be accessed
                      (in order from root → ... → parent; may include current node itself)
        limit: Maximum number of results to return

    Returns:
        results: list of {node_id, text, metadata, score}
    """
    if not ancestor_ids:
        return {"results": []}

    allowed = set(ancestor_ids)
    entries = _load_all()

    scored = []
    for e in entries:
        if e.get("node_id") not in allowed:
            continue
        score = _score(e.get("text", ""), query)
        if score > 0:
            scored.append({
                "node_id": e["node_id"],
                "text": e["text"],
                "metadata": e.get("metadata", {}),
                "score": score,
            })

    scored.sort(key=lambda x: -x["score"])
    return {"results": scored[:limit]}


@mcp.tool()
def get_node_memory(node_id: str) -> dict:
    """Return all memories for a specific node.

    Args:
        node_id: Node ID to retrieve

    Returns:
        entries: list of {text, metadata, ts}
    """
    entries = _load_all()
    result = [
        {"text": e["text"], "metadata": e.get("metadata", {}), "ts": e.get("ts", 0)}
        for e in entries
        if e.get("node_id") == node_id
    ]
    return {"entries": result}


@mcp.tool()
def clear_node_memory(node_id: str) -> dict:
    """Delete memory for a specific node (for debugging or re-running).

    Args:
        node_id: Node ID to delete

    Returns:
        removed: Number of entries removed
    """
    entries = _load_all()
    kept = [e for e in entries if e.get("node_id") != node_id]
    removed = len(entries) - len(kept)
    STORE_PATH.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in kept) + "\n")
    return {"removed": removed}


if __name__ == "__main__":
    mcp.run()
