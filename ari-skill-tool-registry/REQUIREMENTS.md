# Tool Registry Requirements

## Runtime

- Python 3.13 or newer
- `mcp`, `pydantic`, `jsonschema`, `pyyaml`, and `ari-skill-hpc>=0.3.0`
- optional `tooluniverse==1.3.1` only in a separate provider environment; it is
  not imported by the registry process
- optional local Qiskit environment containing exactly Qiskit `2.5.1`, Aer
  `0.17.2`, and Qiskit MCP server `0.3.1`
- optional IBM Runtime environment containing exactly Qiskit `2.5.1`, Qiskit
  IBM Runtime `0.48.0`, Qiskit MCP server `0.3.1`, and IBM Runtime MCP server
  `0.6.1`
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
- Qiskit local ideal, local noisy, remote simulator, and IBM hardware profiles
  use separate capability references. Every profile fixes QPY bytes/version,
  parameter units, target, transpilation, shots, backend method, and all
  applicable seeds/noise/mitigation fields.
- Qiskit remote execution must snapshot and verify backend identity before
  submission, publish the common asynchronous lifecycle, preserve raw provider
  evidence, and cancel on timeout. A backend/target mismatch fails closed.
- `QISKIT_IBM_TOKEN` is admitted only through `quantum.ibm-runtime`, forwarded
  only to the isolated Runtime provider, and value-redacted from every result,
  exception, diagnostic, lock, cassette, and artifact boundary.

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

## Qiskit source admission

- Both provider releases and the Qiskit/Aer/Runtime scientific distributions
  must exactly match `providers/qiskit-support-v1.json`; ranges, runtime install,
  modified package trees, alternate entry points, and added provider arguments
  or environment fail closed.
- The source contains profiles, not wrappers around all upstream tools. Only the
  reviewed transpile and sampling lifecycle is reachable internally; account
  listing/deletion and arbitrary provider operations are not catalog leaves.
- Circuit input is absolute, digest-pinned QPY. Its header format and producing
  Qiskit major/minor/patch must match the profile. Every binding has an explicit
  `rad` or dimensionless unit; the reviewed Runtime MCP does not accept remote
  bindings.
- Local profiles require Aer, a simulator seed, fixed CPU parallelism, and an
  explicit ideal/noise boundary. Remote profiles require value-free instance
  and access-tier identities, backend snapshot verification, and no claimed
  simulator seed.
- Reproducible/scientific admission requires exact replay/golden files whose
  bytes, profile/experiment/method identity, shots, counts, and declared
  statistical bounds all validate. A digest string without the file is rejected.
- Same backend, target, and software-stack profiles share an independence group.
  Multiple wrappers or runs on that lineage are not independent-method evidence.

## Environment

| Variable | Purpose |
|---|---|
| `ARI_CHECKPOINT_DIR` | Writes lock, provenance, cassettes, and raw artifacts under `ear/catalog` |
| `ARI_HPC_LEDGER_PATH` | Optional absolute durable C06 idempotency ledger used by OpenROAD SLURM profiles |
| `ARI_SCHEDULER_PATH` | Fixed search path for shell-free scheduler control commands |
| `ARI_TOOL_REGISTRY_LOCK` | Selects a reviewed lock at process startup |
| `ARI_TOOL_REGISTRY_INDEX` | Selects the derived index matching that lock |
| `ARI_TOOL_REGISTRY_CASSETTES` | Selects a credential-free replay store |
| `QISKIT_IBM_TOKEN` | Optional IBM Quantum Runtime credential, available only through the named credential scope |

The manifest also permits only the fixed platform/TLS variables needed by the
isolated stdio process. The generic direct-MCP adapter remains credential-free;
only the reviewed Qiskit Runtime adapter requests the scoped credential bridge.
