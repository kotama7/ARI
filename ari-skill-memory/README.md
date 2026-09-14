# ari-skill-memory

Ancestor-scoped node memory for ARI's BFTS tree, backed by
[Letta](https://docs.letta.com) (ex-MemGPT). Prevents cross-contamination
between parallel search branches and gives downstream skills a single
in-process library + MCP surface for storing and recalling experiment
observations.

**v0.7.0 — versioned, content-addressed memory.** Letta remains the sole
production backend. The v0.5.x JSONL store
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
| `add_memory(node_id, text, metadata)` | Store an entry scoped to the signed context's self node; any other target is rejected. |
| `search_memory(query, ancestor_ids, limit)` | Retrieve entries from the signed ancestor lineage, ranked by Letta relevance score ∈ [0, 1]. |
| `get_node_memory(node_id)` | Chronological entries for self or a signed ancestor. |
| `get_experiment_context()` | Stable facts from Letta core memory — goal, primary metric, hardware, etc. |

Every node-scoped call carries an immutable `RunContextV1` +
`NodeContextV1`. ari-core signs a transport-only `ari_context` capability for
the selected tool after arguments leave the model; the tool schema shown to
the model does not contain it. The server verifies the signature, tool name,
run id, and lineage digest before performing any I/O. Run-scoped tools
(`audit_memory` and `get_experiment_context`) require the signed run context
but no node lineage.

### Typed verifiable-research-memory tools

The artifact-grounded / reproducibility-aware layer (`writer.py`,
`retriever.py`, `context_builder.py`, `consolidation.py`, `audit.py`,
`provenance.py`, `schemas.py`) feeding v0.9.0's verified-claims gate. Write
tools are CoW-guarded (the target must be the signed context's self node);
callers are loop/pipeline hooks, not LLM pulls.

| Tool | Description |
|------|-------------|
| `add_experiment_result(node_id, text, metric_ptr, artifact_refs, node_report_ref)` | Record a typed `experiment_result` entry. |
| `add_failure_case(node_id, text, artifact_refs, node_report_ref)` | Record a typed `failure_case` (a limitation, not a claim). |
| `add_procedure_memory(node_id, text, node_report_ref)` | Record a reusable `procedure`. |
| `add_reflection(node_id, text, confidence, node_report_ref)` | Record a `reflection` — not usable for paper claims. |
| `add_reproducibility_event(node_id, target_memory_id, status, artifact_refs, text)` | Append-only repro status event; never mutates the target. |
| `search_research_memory(query, ancestor_ids, kinds, require_artifacts, limit)` | Ancestor-scoped typed search, filtered by kind / artifact presence. |
| `get_verified_context(ancestor_ids, purpose, limit)` | Artifact-grounded, repro-aware context for paper/figure use. Returns `usable_for_claims` = grounded and not `rerun_failed`. |
| `audit_memory(experiments_root, run_id)` | Verify recorded provenance (sha256) against disk for a checkpoint. |
| `consolidate_node_memory(node_id, node_report, work_dir, run_id)` | Derive + write typed memory from a `node_report` at node end (CoW: self). |

Writes persist the public, content-addressed `MemoryRecordV1` contract.
Searches return `MemoryRetrievalV1`, including backend/server/model versions,
ranking determinism, query digest, result bound, and filter evidence. See
[`docs/reference/memory_contract.md`](../docs/reference/memory_contract.md).

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
- Record event ledger: `{checkpoint}/memory_events.jsonl` (append-only)
- Portable snapshot: `{checkpoint}/memory_backup.v1.json.gz` (written at
  pipeline-stage boundaries and on shutdown; auto-restored on `ari resume`)

## Determinism (P2)

v0.5.x declared "no LLM calls, fully deterministic". v0.6.0 **relaxes P2
for this skill**: Letta embedding search is not bit-reproducible across
versions. Stored `text` bytes are CoW-protected (ancestor writes are
refused; Letta self-edit is disabled by default via
`ARI_MEMORY_LETTA_DISABLE_SELF_EDIT=true`), so numerical experiment
results remain reproducible even if BFTS *trajectory* may diverge
across re-runs. See `docs/concepts/PHILOSOPHY.md`.

## Deployment

Letta runs in one of three local modes plus Letta Cloud — picked by
`ari setup` and overrideable via `ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA`:

- **Docker Compose** (`scripts/letta/docker-compose.yml`) — laptop default,
  Postgres-backed, supports metadata pre-filter.
- **Singularity / Apptainer** (`scripts/letta/start_singularity.sh`) —
  HPC default; SLURM-aware data dir.
- **pip** (`scripts/letta/start_pip.sh`) — supported container-less fallback,
  SQLite-backed (over-fetch ancestor scoping).
- **Letta Cloud** — set `LETTA_BASE_URL=https://api.letta.com` +
  `LETTA_API_KEY`.

Runtime helpers:

```bash
ari memory start-local [--path=auto|docker|singularity|pip]
ari memory stop-local
ari memory health
ari memory prune-local --yes
ari memory migrate [--checkpoint ...] [--react]   # explicit offline v0.5 → v1 records
ari memory backup  [--checkpoint ...]
ari memory restore [--checkpoint ...] [--on-conflict=skip|overwrite|merge]
ari memory compact-access [--checkpoint ...]
```

Docker, Apptainer/Singularity, pip, and Letta Cloud are supported by the ARI
maintainers. Docker is preferred on workstations and Apptainer on HPC. The pip
fallback is retained for containerless hosts and is scheduled for support
re-evaluation in v1.1. None may silently fall back to `InMemoryBackend`; that
backend requires an explicit test-checkpoint marker.

Migration is offline and explicit: `ari run` / `ari resume` never inspect or
rename legacy files. `ari memory migrate` validates v0.5 entries, converts them
to `MemoryRecordV1`, writes a verified v1 backup, and only then archives the
legacy source.

## Tests

```bash
PYTHONPATH=src:tests pytest -q
```

Coverage spans ancestor scope, CoW, access log, ReAct trace, backup/restore,
isolation, and score contract, plus the typed research-memory layer
(`test_research_memory_phase1`, `test_research_memory_typed`,
`test_consolidation`, `test_verified_context`, `test_archival_pagination`,
`test_server_typed_tools`).

Unit tests run against `InMemoryBackend` (and a `FakeLettaClient` for
`LettaBackend`-specific paths); no running Letta server required.
Integration tests against a real Letta live behind `ARI_TEST_LETTA=1`.
