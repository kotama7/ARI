# Tool Registry Requirements

## Runtime

- Python 3.13 or newer
- `mcp`, `pydantic`, `jsonschema`, `pyyaml`, and `ari-skill-hpc>=0.3.0`
- optional ToolUniverse only in a separate Provider environment; production
  uses the exact `1.3.1+ari.1` or `1.3.1+ari.2` wheel and its checked-in runtime
  lock, never a package registry extra, and the registry process never imports it
- optional local Qiskit environment containing exactly Qiskit `2.5.1`, Aer
  `0.17.2`, and Qiskit MCP server `0.3.1`
- optional IBM Runtime environment containing exactly Qiskit `2.5.1`, Qiskit
  IBM Runtime `0.48.0`, Qiskit MCP server `0.3.1`, and IBM Runtime MCP server
  `0.6.1`
- optional OpenROAD local environment materializing the exact x86_64 SIF and
  inner OpenROAD binary fixed by the selected verified profile; the retained
  SIF is external to Git and must pass full-digest verification before launch
- an immutable reviewed `CATALOG.lock`; the committed default is empty by
  design, and a populated machine-specific catalog is selected at startup with
  `ARI_TOOL_REGISTRY_LOCK`/`ARI_TOOL_REGISTRY_INDEX`
- an optional ARI checkpoint for artifacts and record/replay evidence

The component is enabled by default. Enabling it does not enable any leaf
provider; only sources present in the selected reviewed lock can execute, so the
Skill flag and the catalog are two independent gates.

## Required invariants

- The public MCP surface contains exactly `discover`, `describe`, `invoke`,
  `get_status`, and `get_result`.
- Runtime accepts only an exact opaque `tool_ref`; bare names never dispatch.
- Runtime does not import `sources.yaml`, sync providers, alter admission, or
  replace its active snapshot.
- Production configuration accepts exactly four source kinds: generic direct
  `stdio-mcp`, the reviewed `tooluniverse` collection, and the reviewed
  `openroad` and `qiskit` experiment-profile sources. `StaticCatalogSource`,
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
  typed resource request, exact thread/CPU agreement, and exactly one pinned
  execution substrate: a digest-pinned clean container, or the reviewed
  PRoot/SIF/unsquashfs/worker-Python portable runtime. Which one is a site
  property; that there is exactly one is the invariant, and the lock's
  environment requirements and runtime target are derived from whichever the
  profile pins. Caller arguments cannot override any of these fields.
- Physical cluster, partition, and node selectors are accepted only from a
  regular, Git-ignored site configuration containing a 256-bit random nonce.
  Tracked manifests, evidence, snapshots, locks, filenames, tests, and docs may
  contain only the resulting salted `site_identity_digest`; promotion scans all
  tracked and non-ignored candidate files before and after execution and fails
  closed on a clear selector or nonce. The independent repository gate also
  scans staged blob bytes and symlink targets, and `.githooks/pre-commit` invokes
  it whenever the private site configuration is materialized. A configured
  promotion checkout sets the local `ari.sitePrivacy.required` guard and fails
  rather than skipping if that configuration disappears.
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
- Formal Provider promotion is evidence- and human-approval-bound eligibility,
  not activation. The committed default `CATALOG.lock` remains empty; a run
  must explicitly freeze the materialized Provider and Capability Binding Lock.

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
  `scientifically_admitted`; those levels require leaf evidence. An ARI-patched
  source may omit `verified_lock_path`; it is then collection-wide, carries no
  leaf promotion, and fails closed if it asserts replay or scientific validation
  evidence. The retained exact wheel is required in every case.
- Changed leaf input/output/default schemas require the separate
  `--approve-schema-changes` operator flag.

## Qiskit source admission

- The checked-in verified scope is exactly Qiskit MCP `0.3.1` plus Aer
  `0.17.2` local-ideal Bell-state execution under
  `ari.quantum.sample.local-ideal/v1`. IBM Runtime, remote simulator, and IBM
  hardware remain candidate until credential scope, exact live backend,
  configuration/calibration snapshot, and backend-bound golden/replay evidence
  are independently approved.
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

## OpenROAD source admission

- The checked-in verified scopes are two independent OpenROAD MCP `0.6.1` /
  ORFS 26Q3 identities for the exact GCD placed database and Nangate45
  PDK/library under `ari.eda.openroad.place-route/v1`: x86_64 one-thread
  local-MCP CPU and anonymous exclusive-node SLURM CPU.
- The lock fixes the OCI manifest, external retained SIF, inner OpenROAD,
  profile, workspace, golden/replay, and registration evidence by full digest.
  Absence or drift of the local SIF fails closed.
- Its independent ORFS reference sets `SKIP_CTS_REPAIR_TIMING=1` because the
  pinned binary raises SIGILL in default CTS timing repair. It is not evidence
  of full default-flow parity.
- The SLURM lock requests zero GPUs and discloses only a salted site digest. Why
  no GPU can be granted is read from the reviewed scheduler snapshot rather than
  asserted for every site: promotion compares the live controller against that
  snapshot's declared values plus the invariants that are not site
  characteristics, and refuses a snapshot claiming GPU authority.
  GPU use, another design/PDK/corner, another site/runtime identity, or another
  image is outside both verified scopes and requires an independently approved
  Provider identity.

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
