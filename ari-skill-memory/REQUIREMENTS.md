# ari-skill-memory Requirements

## Overview

MCP Server providing ancestor-scoped memory for ARI BFTS nodes.
Stores per-node memories and restricts retrieval to the ancestor chain only.

Design Principle P2 compliant: **No LLM calls. Fully deterministic.**

## Design

- Storage: `~/.ari/memory_store.jsonl` (append-only JSONL)
- Scope: `search_memory` only returns entries from nodes in `ancestor_ids`
- Siblings and unrelated nodes are invisible to each other

## Tech Stack

- Python 3.11+
- FastMCP
- JSONL (append-only flat file)

## Tool Specifications

### add_memory(node_id, text, metadata=None)
Add a memory entry tagged with node_id. Returns `{"ok": true}`.

### search_memory(query, ancestor_ids, limit=5)
Keyword search over entries from ancestor_ids only. Returns scored results.

### get_node_memory(node_id)
Return all memory entries for a specific node.

### clear_node_memory(node_id)
Delete all memory entries for a node. Returns count removed.
