# ari-skill-memory — Requirements

## Overview

MCP server + importable Python library that provides ancestor-scoped
memory for ARI BFTS nodes, backed by [Letta](https://docs.letta.com).
Stores per-node observations and restricts retrieval to the ancestor
chain so parallel branches do not cross-contaminate.

From v0.6.0 Letta is the sole production backend; a test-only
`InMemoryBackend` is kept so unit tests do not require a running
Letta server. The v0.5.x file-based stores (`memory_store.jsonl`,
`~/.ari/global_memory.jsonl`) are removed — cross-experiment "global
memory" is no longer a feature.

## Design

- Storage: per-checkpoint Letta agent `ari_agent_<sha1(abspath)[:12]>`
  with two archival collections (`ari_node_*`, `ari_react_*`) and a
  seeded core-memory block (`persona`, `human`, `ari_context`).
- Scope: `search_memory` strictly filters by `ancestor_ids` (pre-filter
  on Postgres/Cloud, over-fetch + post-filter on SQLite).
- Copy-on-Write: write-side MCP tools reject `node_id` ≠
  `$ARI_CURRENT_NODE_ID`; Letta self-edit disabled by default so an
  ancestor's entries are byte-stable.
- Observability: every tool call emits a record to `memory_access.jsonl`
  (writes + reads, `src_node_id` provenance) with cost-tracker
  instrumentation.
- Portability: `memory_backup.jsonl.gz` snapshot written at pipeline
  boundaries and on exit so a checkpoint remains `cp -r`-movable.

## Tech stack

- Python 3.11+
- FastMCP (MCP dispatcher)
- `letta-client` (HTTP SDK; pluggable — tests inject a fake)
- Optional: `letta` pip package for container-less deployments

## Environment

Required:
- `ARI_CHECKPOINT_DIR` — per-experiment isolation root.
- `ARI_CURRENT_NODE_ID` — set by ari-core on every skill subprocess
  spawn; validates writes against the active BFTS node.

Connection (defaults suitable for local Docker Compose / Singularity):
- `LETTA_BASE_URL` (default `http://localhost:8283`)
- `LETTA_API_KEY` (required for Letta Cloud)
- `LETTA_EMBEDDING_CONFIG` (default `letta-default`). The Letta agent's
  chat LLM is hardcoded to `letta/letta-free`: ARI never invokes the
  agent's chat API (only `archival_insert` / `archival_search`, which
  use embeddings only), so the LLM handle is a fixed mock that satisfies
  the Letta SDK's mandatory `model=` argument on `agents.create`.

Tuning:
- `ARI_MEMORY_LETTA_TIMEOUT_S` (default 10)
- `ARI_MEMORY_LETTA_OVERFETCH` (default 200 — post-filter path)
- `ARI_MEMORY_LETTA_DISABLE_SELF_EDIT` (default true; CoW-safe)
- `ARI_MEMORY_ACCESS_LOG` (`on`/`off`, default `on`)
- `ARI_MEMORY_ACCESS_LOG_MAX_MB` (default 100)
- `ARI_MEMORY_AUTO_RESTORE` (default true — on `ari resume`)

Developer escape hatch (tests only):
- `ARI_MEMORY_BACKEND=in_memory`

## MCP tool surface

| Tool | Return |
|------|--------|
| `add_memory(node_id, text, metadata=None)` | `{"ok": bool, "id": str, "error"?: str}` |
| `search_memory(query, ancestor_ids, limit=5)` | `{"results": [{entry_id, node_id, text, metadata, score}]}` |
| `get_node_memory(node_id)` | `{"entries": [{text, metadata, ts}]}` |
| `clear_node_memory(node_id)` | `{"removed": int, "error"?: str}` |
| `get_experiment_context()` | stable experiment facts dict |
| `_set_current_node(node_id)` | ari-core ↔ skill CoW bridge (internal) |

Global-memory tools (`add_global_memory`, `search_global_memory`,
`list_global_memory`) were removed in v0.6.0. Callers receive the
standard MCP `tool not found` error.

## Library-only helpers

Used by the viz dashboard and migration CLI (not exposed via MCP):

- `list_all_nodes()` — group all entries by `node_id` for a checkpoint.
- `bulk_get_node_memory(node_ids)` — batch fetch for deep trees.
- `purge_checkpoint()` — drop both collections and the agent; used by
  `ari delete <checkpoint>`.
- `bulk_import(entries, kind)` — migration entry point.
- `list_react_entries(limit=None)` / `react_add` / `react_search` /
  `react_get_all` — ReAct-trace surface consumed by
  `ari.memory.letta_client.LettaMemoryClient`.
- `health()` — ping Letta and report latency.
