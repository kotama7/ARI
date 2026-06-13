# ari_skill_memory

Importable library package providing the memory backend abstraction used by
both the FastMCP server (`src/server.py`) and ari-core's viz layer.

## Contents

- `README.md` — this file.
- `__init__.py` — public surface (`get_backend`, `MemoryBackend`) & layout (module docstring is authoritative).
- `access_log.py` — access auditing shared across backends.
- `audit.py` — re-hashes node_report artifact refs vs disk (`audit_node_report`/`audit_checkpoint`/`summarize`), tagging each verified/missing/mismatch/unhashed; CLI `python -m ari_skill_memory.audit`.
- `config.py` — config loading shared across backends.
- `consolidation.py` — pure `consolidate_from_node_report` deriving typed-memory specs (experiment_result/failure_case/reflection) from a node_report; `write_consolidated` persists them via the typed writer.
- `context_builder.py` — `build_verified_context` ranks ancestor claim memory by evidence strength (rerun_passed > grounded > ungrounded), folding in reproducibility status, and emits `usable_for_claims` for paper/figure pipeline hooks.
- `provenance.py` — derives `ArtifactRef`s + sha256 from node_report (`refs_from_node_report`, `sha256_of`, `node_work_dir`, `load_node_report`); points at on-disk evidence without re-storing node_report fields.
- `retriever.py` — typed reads over the backend: `search_research_memory` (kind/artifact-filtered semantic search), `ancestor_typed_memory` (deterministic ancestor handoff), `fold_reproducibility` (latest repro status per target).
- `schemas.py` — thin typed-index dataclasses `ResearchMemory` / `ArtifactRef` with `MemoryKind`/`ReproStatus` vocab, validation, and `to_metadata()` (promotes `mem_kind`); points at node_report rather than copying it.
- `writer.py` — typed write helpers over `backend.add_memory`: `add_typed_memory` stamps `type`+`mem_kind`+provenance refs, with per-kind shims (`add_experiment_result`/`add_failure_case`/…) and append-only `add_reproducibility_event`.
- `backends/` — backend implementations behind the `get_backend()` factory.
  - `README.md` — backends index.
  - `__init__.py` — the `get_backend()` factory + `MemoryBackend` selection (module docstring is authoritative).
  - `base.py` — the `MemoryBackend` abstract interface.
  - `in_memory.py` — test-only `InMemoryBackend`.
  - `letta_backend.py` — production Letta backend.
  - `letta_client.py` — Letta HTTP client.
