# ari-skill-memory

Ancestor-scoped node memory for ARI's BFTS tree, backed by
[Letta](https://docs.letta.com) (ex-MemGPT). Prevents cross-contamination
between parallel search branches and gives downstream skills a single
in-process library + MCP surface for storing and recalling experiment
observations.

**v0.6.0 — Letta is the sole production backend.** The v0.5.x JSONL store
(`memory_store.jsonl`) and cross-experiment "global memory"
(`~/.ari/global_memory.jsonl`) have been removed. A test-only
`InMemoryBackend` is retained for unit tests.

## Concept

In BFTS, nodes at the same depth run in parallel as independent branches.
Each branch should only learn from its own ancestors — not from sibling
branches — so runs don't cross-contaminate:

```
root (surveys literature → saves to memory)
 ├─ node_A (can recall root memory)
 │    ├─ node_A1 (can recall root + node_A — NOT node_A2)
 │    └─ node_A2 (can recall root + node_A — NOT node_A1)
 └─ node_B (can recall root — NOT node_A or its children)
```

`search_memory(query, ancestor_ids, …)` enforces the invariant via
metadata pre-filter (Postgres / Cloud Letta) or an over-fetch + post-filter
fallback (SQLite pip path).

## MCP tools

| Tool | Description |
|------|-------------|
| `add_memory(node_id, text, metadata)` | Store an entry scoped to a node. Rejects writes whose `node_id` ≠ `$ARI_CURRENT_NODE_ID` (Copy-on-Write). |
| `search_memory(query, ancestor_ids, limit)` | Retrieve ancestor-scoped entries ranked by Letta relevance score ∈ [0, 1]. |
| `get_node_memory(node_id)` | All entries for a specific node, chronological. |
| `clear_node_memory(node_id)` | Debug-only per-node clear (same CoW rule as write). |
| `get_experiment_context()` | Stable facts from Letta core memory — goal, primary metric, hardware, etc. |

## Library API

The backend is also importable in-process by `ari-core` (viz, pipeline):

```python
from ari_skill_memory.backends import get_backend
backend = get_backend(checkpoint_dir="...")
backend.add_memory(...); backend.react_add(...); backend.health()
```

Helpers beyond the MCP surface: `list_all_nodes`, `bulk_get_node_memory`,
`bulk_import`, `list_react_entries`, `purge_checkpoint`, `health`,
plus the three ReAct-trace methods (`react_add`, `react_search`,
`react_get_all`) that back `ari.memory.letta_client.LettaMemoryClient`.

## Storage

- Letta agent per checkpoint: `ari_agent_<sha1(abspath(checkpoint))[:12]>`
- Node-scope archival collection: `ari_node_<ckpt_hash>`
- ReAct-trace archival collection: `ari_react_<ckpt_hash>`
- Access-log telemetry: `{checkpoint}/memory_access.jsonl` (append-only,
  rotated at `ARI_MEMORY_ACCESS_LOG_MAX_MB`, 100 MB default)
- Portable snapshot: `{checkpoint}/memory_backup.jsonl.gz` (written at
  pipeline-stage boundaries and on shutdown; auto-restored on `ari resume`)

## Determinism (P2)

v0.5.x declared "no LLM calls, fully deterministic". v0.6.0 **relaxes P2
for this skill**: Letta embedding search is not bit-reproducible across
versions. Stored `text` bytes are CoW-protected (ancestor writes are
refused; Letta self-edit is disabled by default via
`ARI_MEMORY_LETTA_DISABLE_SELF_EDIT=true`), so numerical experiment
results remain reproducible even if BFTS *trajectory* may diverge
across re-runs. See `docs/PHILOSOPHY.md`.

## Deployment

Letta runs in one of three local modes plus Letta Cloud — picked by
`ari setup` and overrideable via `ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA`:

- **Docker Compose** (`scripts/letta/docker-compose.yml`) — laptop default,
  Postgres-backed, supports metadata pre-filter.
- **Singularity / Apptainer** (`scripts/letta/start_singularity.sh`) —
  HPC default; SLURM-aware data dir.
- **pip** (`scripts/letta/start_pip.sh`) — container-less fallback,
  SQLite-backed (over-fetch ancestor scoping).
- **Letta Cloud** — set `LETTA_BASE_URL=https://api.letta.com` +
  `LETTA_API_KEY`.

Runtime helpers:

```bash
ari memory start-local [--path=auto|docker|singularity|pip]
ari memory stop-local
ari memory health
ari memory prune-local --yes
ari memory migrate [--checkpoint ...] [--react]   # one-shot v0.5.x → v0.6.0
ari memory backup  [--checkpoint ...]
ari memory restore [--checkpoint ...] [--on-conflict=skip|overwrite|merge]
ari memory compact-access [--checkpoint ...]
```

## Tests

```bash
PYTHONPATH=src:tests pytest -q
# 24 passed — ancestor scope, CoW, access log, ReAct trace, backup/restore, isolation, score contract
```

Unit tests run against `InMemoryBackend` (and a `FakeLettaClient` for
`LettaBackend`-specific paths); no running Letta server required.
Integration tests against a real Letta live behind `ARI_TEST_LETTA=1`.
