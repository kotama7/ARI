---
sources:
  - path: ari-skill-orchestrator/src/server.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/service.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/registry.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/execution.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/migration.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/runtime.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/contracts.py
    role: schema
last_verified: 2026-08-02
---

# Orchestrator control plane

`ari-skill-orchestrator` is the external asynchronous control surface for ARI.
It owns submission, status, cancellation, lineage quotas, authorization, and safe
result retrieval. It does not own BFTS internals or federated leaf-tool selection.

## Public contracts

All models reject unknown fields and are checked into `ari-skill-orchestrator/schemas/`:

- `RunRequestV1` binds the experiment text, idempotency key, parent, model profile,
  and all recursion/resource/cost limits to `request_digest`.
- `RunHandleV1` identifies an exact run, owner, root, depth, and current state.
- `RunStatusV1` adds timestamps, exit/error state, bounded node progress, and lineage
  budget usage.
- `RunResultV1` returns status plus `ArtifactRefV1` values.
- `ArtifactRefV1` uses the verified `sha256:…` digest as `artifact_id`; it contains
  role, media type, and size but no filesystem path.

The lifecycle is:

```text
submitted -> running -> succeeded | failed
                     -> cancelling -> cancelled | succeeded | failed
submitted -------------------------> cancelled | failed
```

Terminal rows are immutable. State transitions and an append-only event record are
committed in `logs/.ari-orchestrator/runs.sqlite3` using `BEGIN IMMEDIATE`, WAL, and
full synchronization. An exact `(principal_id, idempotency_key)` retry returns the
existing handle if the request digest is equal and fails on a different digest.

## Restart and cancellation

Each run starts a small wrapper in a new process session. The wrapper starts `ari run`
in its own child process group and atomically records a receipt bound to `run_id` and
`request_digest`. Both wrapper and child identities include `/proc` start ticks, so a
reused PID is never signalled or accepted as evidence. On restart:

- a live, identity-matching wrapper remains `running`;
- a valid terminal receipt settles its recorded terminal state;
- a disappeared process without a terminal receipt fails closed;
- a submitted row is never automatically relaunched, avoiding duplicate science.

`stop_experiment` first records `cancelling`, signals the wrapper, waits a bounded
grace interval, then identity-checks and kills child/wrapper process groups if needed.

Durable process execution currently requires Linux `/proc`. The wrapper applies the
declared CPU count to its process affinity when the platform exposes
`sched_setaffinity`, and sets the common OpenMP/BLAS thread ceilings for the child.
Each run receives a private mode-0700 `HOME`; timeout enforcement is owned by the
wrapper rather than delegated to the experiment.

## Authorization and transports

Stdio uses `ARI_ORCHESTRATOR_PRINCIPAL_ID` and optional comma-separated roles in
`ARI_ORCHESTRATOR_PRINCIPAL_ROLES`. Run owners may access their own records; the
`admin` role may inspect all records. Authorization happens before status detail,
artifact discovery, cancellation, and lock inspection.

Stdio and MCP Streamable HTTP invoke the same functions and service. Streamable HTTP
binds to `127.0.0.1` by default and requires
`ARI_ORCHESTRATOR_HTTP_TOKENS_FILE`. The file must be a non-symlink with mode 0600:

```json
{
  "schema_version": "ari.orchestrator-token-digests/v1",
  "tokens": [
    {
      "token_sha256": "<64 lowercase hex characters>",
      "principal_id": "automation-user",
      "roles": []
    }
  ]
}
```

Only token digests are stored. The adapter implements the MCP SDK `TokenVerifier`, so
an OAuth resource-server verifier can replace the local file without changing tools or
service semantics. Configure issuer/resource metadata with
`ARI_ORCHESTRATOR_OAUTH_ISSUER_URL` and `ARI_ORCHESTRATOR_OAUTH_RESOURCE_URL`.

## Quotas

Every request declares per-run and lineage bounds. Deployment ceilings are:

| Environment variable | Default |
|---|---:|
| `ARI_ORCHESTRATOR_MAX_ACTIVE_RUNS` | 16 |
| `ARI_ORCHESTRATOR_MAX_NODES_PER_RUN` | 1000 |
| `ARI_ORCHESTRATOR_MAX_TOTAL_NODES` | 10000 |
| `ARI_ORCHESTRATOR_MAX_DESCENDANT_RUNS` | 1000 |
| `ARI_ORCHESTRATOR_MAX_COST_USD` | 10000 |
| `ARI_ORCHESTRATOR_MAX_CPUS` | 256 |
| `ARI_ORCHESTRATOR_MAX_TIMEOUT_MINUTES` | 2880 |

The registry derives child depth from the parent and atomically checks root-lineage
run, node, and estimated-cost consumption. A caller cannot increase an ancestor's
depth limit. Violations create neither a run row nor a checkpoint.

These values are admission and execution bounds, not a container boundary:
`estimated_cost_usd` is caller-declared, and memory/GPU isolation is not supplied by
this service. Experiment processes still run as the orchestrator's Unix identity with
the configured workspace access. Untrusted or mutually hostile workloads require a
container, scheduler, or separate executor identity outside this control plane.

## Artifact admission

The public API does not accept filenames. A closed set of root outputs is admitted,
and EAR files are added only through a verified `evidence.index.json` or
`ear_published/manifest.lock` v2. Discovery rejects traversal, symlinks (including
parent components), non-regular files, secret-like names, missing records, extra
published files, size drift, and digest drift. Reads rehash the content and cap inline
payloads at 2 MiB. Larger artifacts remain listable by digest but cannot be downloaded
through `read_artifact`; deployments must expose them through a separately authorized
artifact store.

`list_skills(run_id)` and `get_workflow(run_id)` require a valid run-bound
`SKILLS.lock`. They return identity/digest/phase membership only—not entrypoint paths,
environment names, credential scopes, raw schemas, LLM configuration, or resources.

## Credential and environment boundary

The launcher uses `ari.public.execution.build_minimal_environment`; it never copies the
parent environment wholesale. Model credentials can cross only through the manifest's
`model.provider` scope. Credential values are inherited in memory by the child process
but are absent from request JSON, SQLite, metadata, argv, and runner receipts. The tool
schema has no API-key argument. A per-run private `HOME` prevents normal credential and
cache reuse through a shared home directory, but does not replace OS-level isolation.

## Migration and deletion

Normal status/list calls never scan checkpoint directories. For a controlled migration,
run `python ari-skill-orchestrator/src/server.py --repair-registry`. It imports only
safe direct-child checkpoints with `experiment.md`; ambiguous or apparently live legacy
state becomes `failed` and is never relaunched. After verification, remove the old
checkpoint metadata reader according to the release support window.

Version 2 deleted arbitrary `read_file`/`list_files`, substring run matching,
environment copying, raw workflow/Skill configuration, request-level credentials,
scan-derived live state, and the custom REST/SSE implementation. The only network
adapter is authenticated MCP Streamable HTTP.
