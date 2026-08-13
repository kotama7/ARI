---
sources:
  - path: ari-skill-tool-registry/src/models.py
    role: implementation
  - path: ari-skill-tool-registry/src/providers.py
    role: implementation
  - path: ari-skill-tool-registry/src/sources.py
    role: implementation
  - path: ari-skill-tool-registry/src/admission.py
    role: implementation
  - path: ari-skill-tool-registry/src/catalog.py
    role: implementation
  - path: ari-skill-tool-registry/src/broker.py
    role: implementation
  - path: ari-skill-tool-registry/src/storage.py
    role: implementation
  - path: ari-skill-tool-registry/src/tooluniverse_adapter.py
    role: implementation
  - path: ari-skill-tool-registry/providers/tooluniverse-support-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/tooluniverse/1.3.1+ari.1/provider-manifest-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/tooluniverse/1.3.1+ari.1/verified-lock-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/tooluniverse/1.3.1+ari.2/build-recipe-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/tooluniverse/1.3.1+ari.2/provider-manifest-v1.json
    role: config
  - path: ari-skill-tool-registry/src/openroad_adapter.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_contracts.py
    role: schema
  - path: ari-skill-tool-registry/src/openroad_identity.py
    role: schema
  - path: ari-skill-tool-registry/src/openroad_verification.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_local.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_results.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_hpc.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_hpc_workspace.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_worker.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_promotion.py
    role: implementation
  - path: ari-skill-tool-registry/providers/openroad-support-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/openroad/0.6.1+orfs-26q3-gcd-nangate45/verified-lock-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/openroad/0.6.1+orfs-26q3-gcd-nangate45-slurm-cpu/verified-lock-v1.json
    role: config
  - path: ari-skill-tool-registry/src/qiskit_adapter.py
    role: implementation
  - path: ari-skill-tool-registry/src/qiskit_contracts.py
    role: schema
  - path: ari-skill-tool-registry/src/qiskit_remote.py
    role: implementation
  - path: ari-skill-tool-registry/providers/qiskit-support-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/qiskit/core-0.3.1+aer-0.17.2-local-ideal/verified-lock-v1.json
    role: config
last_verified: 2026-08-07
---

# Federated Scientific Tool Registry

`ari-skill-tool-registry` imports large MCP collections behind five stable
operations: `discover`, `describe`, `invoke`, `get_status`, and `get_result`.
Six MCP tools carry them, because `invoke_scheduled` is the same dispatch
operation on a second surface: a Provider's side-effect class follows its
permissions, so putting `scheduler` on the shared `invoke` would raise the
envelope of every leaf behind it.
The Skill is enabled by default, but enabling it enables no leaf: only sources
present in the selected catalog can execute, and the checked-in `CATALOG.lock`
is empty by design, so the Skill flag and the catalog are two independent gates.
The model never receives every leaf schema, and adding a collection does not
require editing one file per leaf.

## Boundary and lifecycle

```text
few reviewed sources.yaml records
  -> isolated provider discovery
  -> canonical descriptors and visible origin chains
  -> graph, supply-chain, conformance, and scientific admission
  -> reviewed CATALOG.lock + derived catalog.index.json
  -> immutable five-operation runtime broker
```

`sources.yaml` is operator input and is not read by runtime. A changed sync emits
pending artifacts and a review diff. Only explicit `--approve` replaces the
active lock, and an already-running broker never observes that replacement.

Each `tool_ref` is an opaque digest of execution-relevant identity: provider and
adapter versions/digests, provider leaf name, schema, explicit defaults,
permissions and effects, determinism, semantic execution metadata, method
identity, and async lifecycle. Policy and source aliases are deliberately
excluded, so policy reassessment cannot masquerade as implementation drift.

## Progressive disclosure

`discover` returns bounded summaries and at most 25 results per page. `describe`
returns at most 4,000 characters per page and binds its cursor to the catalog,
tool, and section. `invoke` accepts only a full `tool_ref` from the active lock;
an unqualified name, stale identity, invalid arguments, or insufficient admission
fails closed. Provider-specific output is normalized to
`ari.result-envelope/v1`.

## Admission levels

| Level | Required evidence |
|---|---|
| `discovered` | Candidate and transparent leaf origin are known |
| `callable` | MCP conformance, immutable provider pin, verified launcher, allowed permissions |
| `reproducible` | Callable plus pinned dependencies and offline replay fixture |
| `scientifically_admitted` | Reproducible plus validation, limitations, semantics, units, and method identity |

Discovery is not authority. The registry reports evidence and policy decisions;
it does not declare an upstream collection scientifically correct.

## Multiple collections and conflicts

Collections compose through the same canonical descriptor and adapter boundary.
Execution-identical aliases collapse while retaining every source/origin chain.
Tools with a similar capability remain distinct by default. The catalog records
whether overlap is an exact duplicate, the same backend, a semantic near-match,
or an independent method. Diverse discovery can prefer different independence
groups, but results are not averaged automatically and disagreement is preserved.

This allows ToolUniverse, future collection packages, OpenROAD flows, quantum
simulators, or other MCP bundles to coexist without embedding package-specific
routing logic in the agent. A direct stdio MCP source needs no custom leaf code.
A non-stdio collection needs one `CatalogSource` plus one `ProviderAdapter`, with
contract, supply-chain, record/replay, and scientific conformance fixtures.

## ToolUniverse 1.3.1 / 1.3.1+ari.1 / 1.3.1+ari.2 adapter

ToolUniverse is integrated as one compact collection, not thousands of public
MCP tools. The registry itself does not import ToolUniverse. The isolated
provider process exposes ToolUniverse's compact discovery/info/execute surface;
operator sync expands selected leaves into canonical descriptors, and runtime
dispatch maps an exact locked leaf back through `execute_tool`.

The upstream `1.3.1` support record remains `candidate`: its `fitz` requirement
resolves an unrelated distribution whose `pyxnat`/`pathlib==1.0.1` chain breaks
the supported Python runtime. ARI does not weaken that record. A distinct
`1.3.1+ari.1` Provider artifact applies one metadata-only correction—replace
that dependency with `PyMuPDF==1.26.4` and assign a local version—without source
code changes. The support record pins upstream commit/wheel, patch,
deterministic build recipe, byte-identical two-build wheel, full runtime lock,
package tree, license, and Provider manifest. The retained wheel is supplied
from an operator artifact store and must match its full SHA-256;
package-registry resolution is not a production path.

A second patched artifact, `1.3.1+ari.2`, carries that metadata correction
unchanged and additionally raises the compact response ceiling: `smcp.SMCP`
response `max_chars` moves from 100,000 to 2,000,000 at both serialization
sites. Unlike `ari.1` it does change source code. Upstream caps every compact
MCP response at 100,000 characters and, when structural trimming cannot fit,
falls back to raw string truncation that emits invalid JSON, which makes
whole-collection enumeration impossible: `get_tool_info(detail_level=full)`
exceeds the ceiling for the largest leaves even at batch size one. Measured over
all 2,601 loaded leaves the largest single response is 510,904 characters and
only two exceed 100,000, so 2,000,000 admits the worst observed batch with
roughly threefold headroom while staying well under the 7,103,230-character
full-collection dump. This record pins its own patch, deterministic build
recipe, byte-identical two-build wheel
`sha256:5c2e9a254e353e5941d59f8e279dd7c55777eb46c84457f1eefcaef7aa4a60c9`,
runtime lock, package tree, and Provider manifest exactly as `ari.1` does.

An ARI-patched-wheel ToolUniverse source may omit its verified lock. Such a
source is collection-wide and carries no leaf promotion, so it must not assert
`evidence.replay_fixture_digest` or `evidence.scientific_validation_digest`:
those levels require leaf evidence bound to a verified lock. Without one the
source stays `callable` and can reach neither `reproducible` nor
`scientifically_admitted`. The retained exact wheel is still required in every
case.

The checked-in `verified-lock-v1.json` promotes only Provider identity
`tooluniverse-pubmed@1.3.1+ari.1` and only exact leaf
`PubMed_search_articles -> ari.literature.search/v1`. Its immutable closure
binds the Provider manifest, artifact, adapter/projection implementation,
CPython 3.13 linux-x86_64 target, live compact `tools/list` schemas,
leaf/spec/input/output and normalized-output schema digests, Capability
contract, evidence bundle, all fifteen registration gates, and an explicit
human-maintainer `candidate -> verified` approval. The approval digest is bound
to the lock and exact capability scope. Changing `status` alone, removing or
changing the approval, changing scope, or altering any evidence byte fails
verification. Other ToolUniverse leaves and the unmodified upstream release
are not promoted.

Tool selection uses declarative category/type profiles rather than per-leaf
wrappers. An ARI-side category filter is applied even when ToolUniverse's CLI
loads a broader background set, and runtime additionally permits only leaf names
in the active `CATALOG.lock`. Dynamic MCP loaders, agentic/composition/code
execution, credential-requiring leaves, ambiguous/unreviewed profiles, and
invalid schemas are quarantined. ToolUniverse v1.3.1's known property-level
`required: true` dialect is deterministically converted to the standard parent
`required` array and recorded in provenance; other invalid schema forms are not
repaired.

A leaf's `source_file` is normalized relative to the reviewed package root
before it reaches either the leaf metadata or `tool_spec_digest`, and a path
outside that package becomes `<outside-reviewed-package>` rather than being
disclosed. Upstream reports `source_file` as an absolute installation path, so
digesting it verbatim pinned the install location instead of the leaf
definition: the same reviewed wheel produced a different leaf identity on every
machine, and the promoting host's absolute paths were written into promotion
evidence.

Capability substitution is an exact semantic projection, never a tool-name or
description similarity decision. A profile names each admitted leaf, its exact
`capability_ref`, semantic result contract, and result normalizer. Sync fails if
that leaf disappears or changes category/type, and runtime fails if its locked
schema or Provider identity drifts. The PubMed projection normalizes the exact
`PubMed_search_articles` response into `ari.retrieval-result/v1` with
record-level content and provenance digests. The verified identity deliberately
admits no credential scope. ToolUniverse reports `NCBI_API_KEY` as optional, but
it is not passed and an anonymous live probe is registration evidence. A keyed
configuration is a different Provider identity and requires its own
credential-scope review and promotion.

The default admission policy explicitly permits the canonical `network-read`
permission used by `ari.literature.search/v1`. It does not broaden this to
network write authority. With the verified source configuration, operator sync
therefore emits one `callable` PubMed leaf; the checked-in default catalog stays
empty and remains a compatibility baseline. Formal promotion changes governed
status, not activation: each enabled run still freezes an environment-specific
catalog and Binding Lock explicitly.

Argument validation always uses the locked canonical schema. Unknown fields,
wrong JSON types, and missing required fields fail in record mode; upstream
coercion is disabled, and explicit `null` is rejected because v1.3.1 silently
removes it. ToolUniverse result caching, persistence, update checks, hooks, and
search are disabled. Every result records collection/wheel/provider/leaf-spec
identity and `upstream_cache: disabled`; ARI cassette/EAR is the only replay
authority. Collection trust is capped below leaf replay or scientific
validation, so importing ToolUniverse never scientifically admits its leaves.

All stdio Providers run behind a value-free supervisor. It starts the real
Provider in a separate process group and reaps that group after normal exit,
timeout, or cancellation; a real-process registration test verifies that a
spawned descendant does not survive. Promotion is the explicit admin command
`scripts/promote_tooluniverse_pubmed.py`; ordinary agent MCP operations expose
neither promotion nor lock rewrite. Installed runtimes use
`providers/tooluniverse-source.example.yaml`, the checked-in dependency and
verified locks, and their installation-specific `provider_digest`.

Bulk updates always produce a pending catalog diff. Changes to input schema,
output schema, or defaults are grouped by stable provider/leaf identity and
cannot be approved with ordinary `--approve`; they also require the explicit
`--approve-schema-changes` flag. This keeps running experiments on their old
lock and makes large collection upgrades reviewable.

## OpenROAD profile adapter

OpenROAD-MCP is integrated through the same source/descriptor/broker contracts,
but its upstream interactive tools are never canonical leaves. A reviewed
experiment profile is the leaf. Its execution identity includes a fixed command
sequence, exact input workspace, OpenROAD/ORFS commits and executable/image
digests, PDK and standard-cell library identity/license scope, architecture,
threads, seed, declared outputs, and metric contracts.

Only `request_id` crosses the invocation boundary. The adapter rejects arbitrary
Tcl/shell, caller paths, cwd and environment; its flat brace-list grammar cannot
perform Tcl substitution. Inputs are re-digested after copying to an isolated
run workspace. Output discovery is declaration-based: filesystem scanning is
used only to reject undeclared or symlinked files. Metrics carry a numeric value,
unit, corner, mode, stage, source-report digest, and JSON pointer. Exact golden
and replay fixture files are validated before a source is admitted.

Profiles choose `local-mcp` or `slurm`; this choice and its resources/container
are part of both experiment and method identity. In local mode ARI compiles the
validated typed commands into a private runtime-owned Tcl file, asks MCP to
launch that exact file, and polls only read-only session state. Artifact capture
begins after normal process exit, when OpenROAD has flushed `-metrics`; PTY echo
or a short output lull is never a completion signal. All terminal paths clean up
the session, and interruption cannot resume an ephemeral local run.

The formally promoted local OpenROAD identity is the checked-in
`openroad/0.6.1+orfs-26q3-gcd-nangate45` bundle. Its verified lock digest is
`sha256:fbc4be322a03aa50e666a0dcdb3b1afdfe60fa52bbc570e9cd8f1c800168825e`.
It covers one x86_64, one-thread, local-MCP CPU run over the exact GCD placed
database and Nangate45 PDK/library, with live schema parity, DRC-zero metrics,
golden/replay evidence, an official ORFS reference run, fifteen registration
gates, and human approval. The official reference disabled CTS timing repair
after the pinned binary raised SIGILL, so it is recorded as an independent
reference pass rather than full default-flow parity. The 1.54 GB SIF is an
external retained artifact: Git ignores its bytes, while the lock fixes the OCI
manifest, SIF, and inner OpenROAD full digests and runtime path.

The retained SIF has since been re-materialized, so its digest is now
`sha256:b8af5db8db5feb98720faf0959f6d3d478aac89f41cc9ad9d385467800c6580c`
at 1,540,308,992 bytes under `singularity` 4.5.0-1.el9. The earlier record's
digest could not be reproduced, and no container runtime reproduces one: a SIF
header carries a random UUID and a wall-clock creation time inside the hashed
file. The pinned OCI manifest digest and the inner OpenROAD binary digest did
match exactly, so the payload was proven identical while the envelope could not
be.

The independent
`openroad/0.6.1+orfs-26q3-gcd-nangate45-slurm-cpu` identity is also formally
promoted. Lock
`sha256:def08a69e7c0c13e8e76e026163337f39667ee8467792c16cad91d96ee9bd203`
binds the anonymous exclusive-node CPU site digest, scheduler clients, the
digest-pinned container substrate, runtime-owned metrics lifecycle, terminal
completion evidence, live DRC-zero result, fixtures, gates, and human approval.
It requests zero GPUs. GPU execution, another design/PDK/corner, or another
image is not promoted by either lock. The corresponding human-admin entry points
are `scripts/promote_openroad_gcd_cpu.py` and
`scripts/promote_openroad_gcd_slurm_cpu.py`; neither is exposed over Agent MCP.

A SLURM profile pins exactly one execution substrate: either the reviewed
PRoot/unsquashfs/worker-Python portable runtime, or a digest-pinned clean
container. Which one a site uses is a site property; that there is exactly one
is the invariant, and the execution contract admits both. The promoted profile
pins the container, because the reviewed portable build links against a newer
host glibc than the promoting site provides. Isolation is stronger for it rather
than weaker: the closure is the SIF alone instead of the SIF plus the three host
binaries the portable runtime pins — PRoot, `unsquashfs`, and the worker
Python. Its `ContainerRequestV1` declares `runtime: singularity`, no GPU,
`network: none`, `contain_all`, and a clean environment.

What the lock then advertises is derived from that declaration instead of
written out beside it. `environment_requirements` is `cpu`, `exclusive-node`,
`slurm`, plus `proot-sif` or `<runtime>-sif`, so the promoted SLURM lock lists
`cpu`, `exclusive-node`, `singularity-sif`, `slurm`. `runtime_target` follows
the same declaration: `worker_python` is `container-provided` rather than a host
`CPython-3.12`, `execution_substrate` is `singularity-sif`, and `network` is
`isolated` because the container declares `network: none`. The typed job's
`container_digest` must equal exactly what the profile pins — the image digest
for a container run, and no container at all for the PRoot run.

SLURM mode compiles the same reviewed closed commands to a digest-pinned Tcl
program and runs a copied, digest-pinned standard-library worker through C06
`JobRequestV1`. It requires one node/task, exact `cpus_per_task == threads`, a
canonical shared work root, and the one substrate the profile pins — for a
container run, a clean/contained SIF whose digest equals the toolchain image
digest. The compute-node worker rechecks executable, Tcl, and
architecture identity before invoking OpenROAD without a shell. Scheduler handle,
normalized status, environment/module/container digests, logs, and provenance are
included in the result and EAR. Terminal state comes from the scheduler wherever
the scheduler can answer: with accounting storage present it is the scheduler's
own state (`COMPLETED`, exit code 0), and only without it does the nonce-bound
fixed-wrapper record (`fixed-wrapper-completion-v1`) stand in. Either way the job
must have actually succeeded. Cancel waits for terminal scheduler state before
workspace deletion; an ambiguous control/transport result preserves the workspace
for ledger reconciliation.

The GPU limitation is read from the reviewed scheduler snapshot rather than
asserting one site's situation everywhere. A scheduler that declares no GRES
types cannot express a GPU request at all; where it does declare GRES types, the
guarantee instead rests on the allocated node exposing no accelerator. Either
way the profile requests zero GPUs and grants no GPU capability.

Snapshot verification compares the live controller against the values the
reviewed snapshot declares — Slurm version, GRES types, partition `MaxTime`,
node architecture, `CPUTot`, `Sockets`, and `ThreadsPerCore` — and against the
operator's private site configuration for the selectors that never enter the
repository, the cluster and node names. It then asserts a small set of
invariants that are not site characteristics: `Arch=x86_64`,
`Gres=(null)`, and `OverSubscribe=EXCLUSIVE`. A snapshot that claims GPU
authority is refused outright. The same promotion can therefore run at another
scheduler site, while drift between the snapshot and the live controller still
fails closed.

Physical scheduler names are runtime-private. The SLURM promotion command reads
cluster, partition, and node selectors only from a Git-ignored site file with a
256-bit nonce. No tracked profile, snapshot, fixture, evidence file, lock,
filename, test, or document may contain those selectors. Public identity is the
salted full SHA-256 `site_identity_digest`; a pre/post-promotion Git candidate
scan fails closed if the site file becomes trackable or a clear identity leaks.
`scripts/check_site_privacy.py` independently scans both worktree candidates and
staged blob bytes, including filenames and symlink targets; the repository
pre-commit hook invokes it whenever the private site configuration exists.

The scheduler handle's `workspace_scope` and `artifact_scope` are recorded
relative to the declared work root before the evidence is written. The
digest-derived scope names are the publishable part; the prefix only says which
machine ran the promotion. A scope escaping the work root is refused.

Completed outputs, scheduler logs/provenance, and success/failure/cancel transcripts are stored
content-addressably. Provider-returned artifact references are an internal
adapter protocol: the broker removes the reserved field and independently checks
safe digest-prefixed names, symlink absence, size, and SHA-256 before adding them
to `ResultEnvelopeV1`. Record/replay keeps those references without contacting
the provider. Profiles sharing the same design inputs and PDK/library use one
independence group, so version disagreement is not counted as independent
scientific evidence.

## Qiskit profile adapter

The official Qiskit core and IBM Runtime MCP providers are supply-chain inputs,
not public catalog leaves. One reviewed `QiskitExperimentV1` becomes one virtual
async leaf. Its QPY circuit/version, parameter units, transpilation target and
seed, shots, simulator/noise/Runtime backend, mitigation, evidence, and
limitations are immutable; the caller supplies only `request_id`.

Local ideal, local noisy, remote simulator, and IBM hardware sampling use four
different capability references. ARI uses the official core MCP for transpiling
and an exact distribution-checked worker for Aer execution. Remote profiles use
only the reviewed Runtime setup, backend snapshot, sampler, status, result, and
cancel leaves; account-management leaves are never published. Backend/target
mismatch fails before submission, and every live snapshot and job/result record
is retained as a verified artifact.

`QISKIT_IBM_TOKEN` reaches only the isolated Runtime process through the named
credential scope and is exact-value redacted at the provider boundary. Locks,
cassettes, artifacts, and identities contain neither the token nor a raw
instance CRN. See [Qiskit and IBM Quantum experiment profiles](qiskit_profiles.md)
for the scientific contract, operator procedure, update/rollback, and deletion
gates.

The only formally promoted Qiskit identity is the checked-in
`qiskit/core-0.3.1+aer-0.17.2-local-ideal` bundle. Its verified lock digest is
`sha256:57b60bbdb84ba0364e038a6df51f3de2a48cdf8c776d31066efeec5ea68be195`.
It covers the credential-free seeded Bell-state local-Aer profile and
`ari.quantum.sample.local-ideal/v1` only. The lock binds the QPY bytes/version,
target, software stack, seeds, counts bounds, live MCP schema, golden/replay
evidence, fifteen Provider gates, and human approval. The IBM Runtime MCP,
remote simulator, and IBM hardware remain candidate: no credential was admitted
and no exact live backend/configuration/calibration identity or backend-bound
golden/replay evidence was available. Those cannot inherit local-Aer promotion.
The corresponding human-admin entry point is
`scripts/promote_qiskit_local_aer.py`; it is not exposed over Agent MCP.

Provider promotion changes governed eligibility, not activation. Every promoted
identity remains absent from the checked-in empty `CATALOG.lock`; an operator
must materialize the exact environment, sync/review the source, and freeze a new
Provider/Capability Binding Lock for a run.

### Reaching an ARI Capability

A leaf in this catalog is not an ARI Provider and never appears in
`SKILLS.lock`, so the Capability Binder cannot authorize it directly. The
`ari.provider.tool-registry` entry in `ari-core/config/providers/catalog.yaml`
bridges the two: its `brokered` block names this catalog lock, the default
dispatch tool (`invoke`), a per-leaf `dispatch_tool_by_leaf` override that routes
a scheduler-submitting leaf to `invoke_scheduled`, and a reviewed table from leaf
`tool_ref` to ARI `capability_ref`. Each reviewed leaf becomes a composite
`CapabilityProvisionV1` whose callable identity is the dispatch surface its route
names and whose semantic identity is the leaf. A descriptor's own
`capability_ref` belongs to this registry's namespace and is never read as that
mapping; only the checked-in table decides.

ARI resolves the lock with `ARI_TOOL_REGISTRY_LOCK`, the same variable the
broker uses, and falls back to the packaged path when it is unset. Both must
resolve to one lock or ARI would describe leaves the broker is not dispatching.
A materialized lock records absolute local paths and stays out of the
repository, which is why the reviewed table is checked in and the lock is not.

Authority is the envelope of both hops: the composite's side-effect class is the
worse of the leaf's and `invoke`'s, and a contract's required permissions must be
granted by both. `invoke` declares `stateful`, so no `read-only` capability can
be supplied through it today. `ari.literature.search/v1` was once recorded under
that rule, but what actually blocked it was its own contract: an admitted
retrieval writes the record that makes it evidence, and the ladder grades a call
by what it does to that substrate rather than by whether it mutates the remote
index. The contract now reads `workspace-write`, so the reviewed PubMed leaf can
compose against it; registering that mapping still needs a review decision and a
site lock that carries the leaf.

A leaf whose descriptor declares an asynchronous lifecycle is submitted through
`invoke` and completed through `get_status` and `get_result`. Those are named in
the entry's `lifecycle_tools` and travel on the binding, so the authorization
view admits them under the same binding, phase, and call context. They are not
separate capabilities: polling a job you were authorized to submit adds no
authority. Without them a bound async capability starts work and cannot collect
it, which is what happened before they were carried.

Because the broker is one process with one credential surface, a composite
carries every credential scope the Provider declares **whose value is actually
present**. On a host where `QISKIT_IBM_TOKEN` is unset — the shipped state — the
broker's IBM Quantum scope records no present value, the composite carries no
scopes, and binding the OpenROAD leaf requires no credential grant at all. An
earlier version of this page said the opposite, that an explicit grant was
required or nothing would bind; that was written before the presence filter and
was wrong afterwards. The grant becomes required exactly when the token is set,
which is the case where the authority is real.

The four broker tools that carry a call context — `invoke`, `invoke_scheduled`,
`get_status`, and `get_result` — declare `ari_context` in their input schemas.
They are `context_requirement: run`, so the transport injects the authorized call
context under that name; a schema with `additionalProperties: false` that omits it
refuses every authorized call.

One rough edge remains and is not a defect in the result normalizer. ARI wraps
the broker's own `ari.result-envelope/v1` in a second envelope, so a brokered
async submission puts its handle in `structured_content.structured_content`
while the outer `async_handle` stays null. That field carries
`ari.async-tool-handle/v1`, which drives `get_async_status` / `get_async_result`
/ `cancel_async` and is built for manifest-declared ARI async tools; a brokered
leaf's handle is `ari.registry-handle/v1`, the broker's own protocol. Converting
one to the other is mechanically possible — the binding now knows the lifecycle
tool refs and the broker returns its state map — but it has no caller today, and
adding an uncalled converter would repeat the mistake this work spent its time
undoing. Until something needs it, a brokered async caller polls the bound
lifecycle tools directly.

## Record, replay, and EAR

Record mode stores exact normalized arguments, catalog and policy digests,
selection reason, rejected alternatives, raw response digest or artifact, and
the normalized result. Replay uses the same cassette key and matching catalog
without starting a provider. `{checkpoint}/ear/catalog/` contains `CATALOG.lock`,
value-free provenance, cassettes, and content-addressed raw artifacts; the
default EAR curator includes this directory.

## Operator procedure

```bash
cd ari-skill-tool-registry
python src/sync_catalog.py                 # create or write pending review
python src/sync_catalog.py --approve       # only after reviewing the diff
python src/sync_catalog.py --approve --approve-schema-changes  # schema review
python scripts/verify_tooluniverse.py --help
python scripts/verify_openroad.py --help
python scripts/verify_qiskit.py --help
python scripts/promote_openroad_gcd_cpu.py --help
python scripts/promote_qiskit_local_aer.py --help
python scripts/sync_contracts.py           # CI drift check
pytest -q
```

Never add a hand-written production record per leaf, expose leaf schemas directly
as LLM tools, refresh the catalog during a run, dispatch a bare name, return raw
provider-shaped results, or register static fixtures in production. Those paths
are excluded by the contract and regression suite.
