---
sources:
  - path: ari-core/ari/memory_contract.py
    role: schema
  - path: ari-core/ari/memory_cli.py
    role: implementation
  - path: ari-skill-memory/src/ari_skill_memory/writer.py
    role: implementation
  - path: ari-skill-memory/src/ari_skill_memory/retriever.py
    role: implementation
last_verified: 2026-08-02
---

# Research memory contract

ARI memory is a lineage-scoped index, not scientific evidence. The canonical
stored form is `ari.memory-record/v1`; the canonical search response is
`ari.memory-retrieval/v1`; portable snapshots use `ari.memory-backup/v1`.
Their JSON Schemas are shipped as
`ari-core/ari/schemas/memory_record_v1.schema.json` and
`memory_retrieval_v1.schema.json`, plus `memory_backup_v1.schema.json`.

## Immutable records

`MemoryRecordV1` binds the record kind and text to its source run, source node,
ordered ancestor lineage, artifact references, node-report reference, metric
pointer, confidence, reproducibility event and creating tool. `record_id` and
`record_digest` are the same SHA-256 content address over the normalized record
payload. Retrieval and restore revalidate that address and reject mutation.

Artifact references carry a safe relative path, complete SHA-256 digest, byte
size, role and `verified`/`unverified` state. A write is `verified` only when the
writer reads the file under the declared artifact root and obtains the claimed
digest. A metric pointer requires an explicit unit. A node-report reference
requires the report digest. Memory text and `unverified` references are never
sufficient evidence for a paper claim.

Writes are append-only and idempotent by record digest. Reproducibility status
is represented by a new `reproducibility_event`; it never mutates the target.
The public MCP surface intentionally has no clear/delete tool. Administrative
checkpoint purge remains a backend operation used by explicit restore and
deployment recovery.

## Retrieval provenance

Every search returns backend, client/server version, embedding model and model
version, ranking method, determinism flag, query digest, candidate/returned
counts, bound and filter evidence. Letta embedding rank is explicitly
non-deterministic; the in-memory keyword ranker is marked test-only and
deterministic. Typed filtering uses the validated canonical record rather than
mutable backend projections. Legacy unversioned rows are excluded.

## Backup, restore and migration

`ari memory backup` writes deterministic `memory_backup.v1.json.gz` with a
root digest, sorted record-digest index, verified logical record order and
per-ReAct-entry digests. Restore
validates the complete document before writing and supports `skip`, `merge`
and `overwrite`; records are deduplicated by content digest. The file is
checkpoint-namespace independent and may be restored into a clean Letta
deployment.

Runtime launch and resume never inspect legacy memory files. Operators must run
`ari memory migrate` explicitly. The offline migrator validates v0.5 JSONL,
converts it to conservative v1 records, writes and verifies a portable backup,
then archives the source file. Cross-experiment global memory is reported but
never imported.

## Deployment support

All production modes use Letta; `InMemoryBackend` requires a test-namespace
marker and cannot be selected by workflow configuration.

| Mode | Status | Scope / gate |
|---|---|---|
| Letta Cloud | Supported | HTTPS endpoint and API key; health check required |
| Docker Compose | Supported, preferred for local workstations | Postgres-backed compose file and clean-start test |
| Apptainer / Singularity | Supported, preferred on HPC | portable start script, environment-file and runtime checks |
| pip | Supported fallback | local server only; static clean-launch checks, no silent fallback from a failed container path |

Support owner for all four paths is the ARI maintainers team. The pip fallback
is retained because containerless hosts remain supported; its status must be
re-evaluated for v1.1 using deployment issues and usage reports. No deployment
path may silently fall back to the test backend.

## Consumer rule

Use `get_verified_context` for paper or figure claims. Consumers may display
ungrounded memory as supplementary context, but only records whose artifact
references are all verified and whose latest replay event is not
`rerun_failed` belong in `usable_for_claims`.
