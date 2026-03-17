# ari-skill-memory

MCP skill for ancestor-scoped node memory.
Prevents cross-contamination between parallel BFTS search branches.

**Design Principle P2 compliant: No LLM calls. Fully deterministic.**

## Concept

In BFTS, nodes at the same depth run in parallel as independent branches.
Each branch should only learn from its own ancestors — not from sibling branches.

```
root (surveys literature → saves to memory)
 ├─ node_A (can recall root memory)
 │    ├─ node_A1 (can recall root + node_A — NOT node_A2)
 │    └─ node_A2 (can recall root + node_A — NOT node_A1)
 └─ node_B (can recall root — NOT node_A or its children)
```

## Tools

| Tool | Description |
|------|-------------|
| `add_memory` | Store a memory entry scoped to a node_id |
| `search_memory` | Retrieve entries from ancestor nodes only |
| `get_node_memory` | Get all entries for a specific node |
| `clear_node_memory` | Delete entries for a node (for rerun/debug) |

## Storage

Entries are stored in `~/.ari/memory_store.jsonl` (append-only JSONL).

## Tests

```bash
pytest tests/ -q
# 6 passed
```
