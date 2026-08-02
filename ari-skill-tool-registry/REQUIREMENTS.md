# Tool Registry Requirements

## Runtime

- Python 3.13 or newer
- `mcp`, `pydantic`, `jsonschema`, `pyyaml`, and `ari-skill-hpc>=0.3.0`
- optional `tooluniverse==1.3.1` only in a separate provider environment; it is
  not imported by the registry process
- an immutable reviewed `CATALOG.lock`; the committed default is empty
- an optional ARI checkpoint for artifacts and record/replay evidence

The component is default-off. Enabling it does not enable any leaf provider;
only sources present in the reviewed lock can execute.

## Required invariants

- The public MCP surface contains exactly `discover`, `describe`, `invoke`,
  `get_status`, and `get_result`.
- Runtime accepts only an exact opaque `tool_ref`; bare names never dispatch.
- Runtime does not import `sources.yaml`, sync providers, alter admission, or
  replace its active snapshot.
- Production configuration accepts generic direct `stdio-mcp` and the reviewed
  `tooluniverse` collection source. `StaticCatalogSource`,
  `StaticProviderAdapter`, and package-verification bypasses are injection seams
  for conformance tests, not selectable production kinds.
- Launchers execute no shell string and forward no undeclared parent
  environment or embedded credentials.
- Every leaf has a visible source-to-provider-to-tool origin chain. Cycles,
  excessive depth, missing leaf identity, source failure, and identity drift are
  quarantined or fail closed.
- Provider responses are normalized to `ari.result-envelope/v1`; large raw
  content becomes a content-addressed artifact.
- Record/replay cassettes contain no credential values and bind exact arguments,
  catalog, policy, selection evidence, raw response, and normalized result.
- Exact duplicate identities may collapse. Semantic near-matches remain
  distinct; scientific equivalence requires reviewed units, semantics, backend
  and data lineage, and method identity evidence.
- An OpenROAD `slurm` profile requires a canonical shared `work_root`, one-node
  typed resource request, exact thread/CPU agreement, a digest-pinned clean
  container matching the toolchain image digest, and a worker Python path inside
  that image. Caller arguments cannot override any of these fields.
- Scheduler submission, status, cancellation, result, logs, module/environment
  snapshots, and container identity use the C06 contracts. A workspace is removed
  only after terminal scheduler state; ambiguous delivery fails closed and keeps
  reconciliation evidence.

## Source admission

A source owner must provide an immutable provider digest and value-free evidence.
`callable` requires protocol conformance, provider pinning, launcher verification,
and permitted capabilities. `reproducible` additionally requires dependency
pinning and a replay fixture digest. `scientifically_admitted` additionally
requires validation evidence, limitations, semantics, units, and method identity.

Source updates are operator-only. Unapproved changes produce pending lock/index
files and a review diff. Approval must be explicit and occurs outside an active
run.

## ToolUniverse source admission

- The release record must exactly match
  `providers/tooluniverse-support-v1.json`; version ranges and refresh-on-start
  installs are rejected.
- `package_root` must be the installed `tooluniverse` directory whose complete
  non-cache file tree matches the reviewed wheel. The launcher must use the
  fixed stdio callable and include `**/*` in its identity closure.
- The source declares category profiles rather than leaf wrappers. The adapter
  independently enforces include/exclude categories and active-lock leaf names,
  even when upstream loading is broader.
- Dynamic MCP loaders, agentic/composition/code-execution types, direct
  credential requirements, ambiguous/unreviewed profiles, and unrecognized
  schema dialects remain quarantined.
- ToolUniverse type coercion, result cache, FastMCP update checks, hooks, and
  search are disabled. Explicit `null` is rejected because upstream removes it
  before execution.
- Collection-level evidence cannot promote every leaf to `reproducible` or
  `scientifically_admitted`; those levels require leaf evidence.
- Changed leaf input/output/default schemas require the separate
  `--approve-schema-changes` operator flag.

## Environment

| Variable | Purpose |
|---|---|
| `ARI_CHECKPOINT_DIR` | Writes lock, provenance, cassettes, and raw artifacts under `ear/catalog` |
| `ARI_HPC_LEDGER_PATH` | Optional absolute durable C06 idempotency ledger used by OpenROAD SLURM profiles |
| `ARI_SCHEDULER_PATH` | Fixed search path for shell-free scheduler control commands |
| `ARI_TOOL_REGISTRY_LOCK` | Selects a reviewed lock at process startup |
| `ARI_TOOL_REGISTRY_INDEX` | Selects the derived index matching that lock |
| `ARI_TOOL_REGISTRY_CASSETTES` | Selects a credential-free replay store |

The manifest also permits only the fixed platform/TLS variables needed by the
isolated stdio process. Provider credentials are not supported by the generic
adapter until a value-free credential-scope bridge is admitted and tested.
