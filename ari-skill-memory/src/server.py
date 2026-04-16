"""
ari-skill-memory: Node-scoped memory MCP server

Design principles:
- Each memory entry has a node_id tag
- search_memory returns only memories from nodes in the ancestor_ids list
- → Only parent node memories are accessible; sibling/child memories are hidden
- Memories are persisted per experiment under
  ``{ARI_CHECKPOINT_DIR}/memory_store.jsonl`` (override with
  ``ARI_MEMORY_PATH``).

Long-term memory (cross-experiment):
- ``add_global_memory`` / ``search_global_memory`` / ``list_global_memory``
  persist to ``~/.ari/global_memory.jsonl`` (override with
  ``ARI_GLOBAL_MEMORY_PATH``). These entries survive across experiments,
  intended for stable lessons (failure modes, reliable hyperparameters,
  reusable scaffolding). Still gated on memory-skill being enabled in
  the workflow — if memory-skill phase=none, none of these tools exist.
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


def _resolve_store_path() -> Path:
    """Pick the per-experiment memory store file.

    Resolution order:
    1. ``ARI_MEMORY_PATH`` — explicit override (tests, custom deployments)
    2. ``ARI_CHECKPOINT_DIR/memory_store.jsonl`` — per-experiment, project-isolated

    Raises ``RuntimeError`` if neither is set — ARI no longer maintains a
    global ``~/.ari/memory_store.jsonl`` fallback.
    """
    explicit = os.environ.get("ARI_MEMORY_PATH")
    if explicit:
        return Path(explicit).expanduser()
    ckpt = os.environ.get("ARI_CHECKPOINT_DIR")
    if ckpt:
        return Path(ckpt).expanduser() / "memory_store.jsonl"
    raise RuntimeError(
        "ari-skill-memory requires ARI_CHECKPOINT_DIR or ARI_MEMORY_PATH "
        "to be set — no global fallback exists."
    )


STORE_PATH = _resolve_store_path()


def _resolve_global_path() -> Path:
    """Pick the cross-experiment long-term memory file.

    Default: ``~/.ari/global_memory.jsonl``. Override with
    ``ARI_GLOBAL_MEMORY_PATH``.
    """
    explicit = os.environ.get("ARI_GLOBAL_MEMORY_PATH")
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".ari" / "global_memory.jsonl"


GLOBAL_PATH = _resolve_global_path()


def _load_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def _append_to(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


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


@mcp.tool()
def add_global_memory(text: str, tags: list[str] | None = None, metadata: dict | None = None) -> dict:
    """Persist a long-term note that survives across experiments.

    Use for stable lessons: reproducible failure modes, reliable
    hyperparameters, environment quirks, reusable scaffolding. Do NOT
    use for transient per-run numbers — prefer add_memory for that.

    Args:
        text: Content to remember across experiments
        tags: Optional keyword tags for retrieval (e.g. ["pytorch", "slurm"])
        metadata: Optional structured metadata

    Returns:
        ok: True
    """
    entry = {
        "text": text,
        "tags": tags or [],
        "metadata": metadata or {},
        "ts": time.time(),
    }
    _append_to(GLOBAL_PATH, entry)
    return {"ok": True}


@mcp.tool()
def search_global_memory(query: str, tags: list[str] | None = None, limit: int = 5) -> dict:
    """Search cross-experiment long-term memory by keyword (and optional tag filter).

    Args:
        query: Search query (keyword match against text and tags)
        tags: Optional — restrict results to entries carrying any of these tags
        limit: Maximum number of results

    Returns:
        results: list of {text, tags, metadata, ts, score}
    """
    entries = _load_file(GLOBAL_PATH)
    tag_filter = set(tags or [])

    scored = []
    for e in entries:
        e_tags = set(e.get("tags", []) or [])
        if tag_filter and not (tag_filter & e_tags):
            continue
        haystack = e.get("text", "") + " " + " ".join(e_tags)
        score = _score(haystack, query)
        if score > 0 or not query.strip():
            scored.append({
                "text": e.get("text", ""),
                "tags": list(e_tags),
                "metadata": e.get("metadata", {}),
                "ts": e.get("ts", 0),
                "score": score,
            })

    scored.sort(key=lambda x: (-x["score"], -x["ts"]))
    return {"results": scored[:limit]}


@mcp.tool()
def list_global_memory(limit: int = 20) -> dict:
    """Return the most recent global memory entries (no query filter).

    Useful for agents that want a quick overview of accumulated long-term
    knowledge before deciding what to search for.
    """
    entries = _load_file(GLOBAL_PATH)
    entries.sort(key=lambda e: -e.get("ts", 0))
    return {"entries": entries[:limit], "total": len(entries)}


if __name__ == "__main__":
    mcp.run()
