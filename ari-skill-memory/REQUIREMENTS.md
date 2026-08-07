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
- Copy-on-Write: every node-scoped MCP call verifies a tool-bound, signed
  `NodeContextV1`; write-side tools accept only its self node and read-side
  tools accept only its ordered ancestor lineage (plus self where applicable).
  Letta self-edit is disabled by default so an ancestor's entries are
  byte-stable.
- Observability: every tool call emits a record to `memory_access.jsonl`
  (writes + reads, `src_node_id` provenance) with cost-tracker
  instrumentation.
- Portability: digest-verified `memory_backup.v1.json.gz` snapshot written at pipeline
  boundaries and on exit so a checkpoint remains `cp -r`-movable.

## Tech stack

- Python 3.11+
- FastMCP (MCP dispatcher)
- `letta-client` (HTTP SDK; pluggable — tests inject a fake)
- Optional: `letta` pip package for container-less deployments

## Environment

Required:
- `ARI_CHECKPOINT_DIR` — per-experiment isolation root.

ari-core also installs a per-connection `ARI_CONTEXT_AUTHORITY_KEY` secret in
the provider process. It is system-managed, cannot be supplied through a Skill
manifest or inherited parent environment, and must never be put in user config,
logs, lockfiles, or model-visible tool arguments. Direct MCP clients are placed
behind `secure_stdio_proxy`, which creates its own authority and injects the
same signed capability contract.

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
| `search_memory(query, ancestor_ids, limit=5)` | versioned results plus backend/model/ranking/filter provenance |
| `get_node_memory(node_id)` | `{"entries": [{text, metadata, ts}]}` |
| `get_experiment_context()` | stable experiment facts dict |

The transport-only `ari_context` argument is intentionally omitted from this
table and from model-facing `tools/list` responses. The manifest declares
`context_requirement: node` for node-scoped tools and
`context_requirement: run` for `audit_memory` and
`get_experiment_context`. Missing, forged, expired-by-connection, tool-mismatched,
or lineage-inconsistent capabilities fail closed before backend access.

Global-memory tools (`add_global_memory`, `search_global_memory`,
`list_global_memory`) were removed in v0.6.0. Callers receive the
standard MCP `tool not found` error.

Per-node clear/delete is also absent from the public and backend surfaces;
research records are append-only. Explicit whole-checkpoint purge remains an
administrative restore/deployment operation.

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

## Verifiable research-memory layer

A typed, artifact-grounded index built **on top of** the node-scope store
(concept: `docs/concepts/verifiable_research_memory.md`). `node_report.json`
is the source of truth; these records carry a `node_report_ref` pointer + a
searchable `text`, never copies of node_report fields.

- `ari.public.memory` — canonical `MemoryRecordV1` / `MemoryRetrievalV1`;
  `schemas.py` retains only the unverified `ArtifactRef` input helper.
- `provenance.py` — `sha256_of`, `normalize_artifact_path`,
  `refs_from_node_report` (reuses `files_changed` sha256; `compute_missing`
  hashes artifacts for an index baseline), `load_node_report`.
- `audit.py` — `audit_node_report` / `audit_checkpoint`: re-hash referenced
  artifacts → `verified | missing | mismatch | unhashed`. CLI:
  `python -m ari_skill_memory.audit <experiments_root> [run_id]`.
- `writer.py` — typed writes (`add_experiment_result` / `add_failure_case` /
  `add_procedure_memory` / `add_reflection` / `add_reproducibility_event`),
  authorized at the MCP boundary; stamp `type` + `mem_kind`.
- `retriever.py` — `search_research_memory(kinds, require_artifacts)`,
  `ancestor_typed_memory` (deterministic, ancestor-scoped, full),
  `fold_reproducibility` (append-only events → latest status per target).
- `consolidation.py` — `consolidate_from_node_report` (pure: node_report →
  typed specs) + `write_consolidated`.
- `context_builder.py` — `build_verified_context`: rerun_passed > grounded >
  ungrounded; `usable_for_claims` = grounded & not rerun_failed.

MCP tools (called by ari-core loop/pipeline hooks, never an LLM pull):
`add_experiment_result`, `add_failure_case`, `add_procedure_memory`,
`add_reflection`, `add_reproducibility_event`, `search_research_memory`,
`get_verified_context`, `audit_memory`, `consolidate_node_memory` — the five
write tools require a signed self-node context. Read requests are checked
against the same signed lineage before the backend's ancestor filter runs.

Invariants: same ancestor-scope predicate as `search_memory`; append-only
state; `archival_list` pages via cursor (the >200-passage ceiling no longer
truncates client-side filters). Gated by `ari.config.consolidation_enabled`
(`ARI_MEMORY_CONSOLIDATE`, default ON).
