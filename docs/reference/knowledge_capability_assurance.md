---
sources:
  - path: ari-core/ari/knowledge
    role: implementation
  - path: ari-core/ari/providers
    role: implementation
  - path: ari-core/ari/capability_binding
    role: implementation
  - path: ari-core/ari/assurance
    role: implementation
  - path: ari-core/ari/rqgm/admission_builder.py
    role: implementation
last_verified: 2026-08-05
---

# Knowledge, Capability, and Scientific Assurance

ARI separates procedural knowledge, executable authority, and independent
verification. These are three registries with three identities; a shared
package name, transport, vendor, or repository never merges them.

| Concept | Meaning | Canonical implementation |
|---|---|---|
| **Knowledge Skill** | Non-executable, content-addressed knowledge about what to do, why, when, and in what order | `ari.knowledge` |
| **Capability** | Versioned semantic execution contract such as `ari.execution.compile/v1` | `ari.capability_binding` ontology |
| **Capability Provider** | Executable subject that supplies one or more capabilities | `ari.providers`, reusing `ari.mcp` and the existing Provider lock |
| **MCP** | Provider transport and discovery protocol | `ari.mcp` |
| **Tool** | Atomic Provider operation | frozen in the Provider lock |
| **Capability Binding** | Deterministic requirement-to-`tool_ref` resolution for one run/epoch | `ari.capability_binding` |
| **Harness** | Independent verifier for a declared target/property/scope | `ari.assurance` |
| **RQGM** | Governance of who produced, used, ignored, or distorted authority and evidence | `ari.rqgm` bridges |

The normative inequalities are:

```text
Knowledge Skill != Capability Provider
Capability Provider != Harness
Harness != Evaluator
MCP != Skill
Tool description != procedural knowledge
Skill instruction != executable authority
```

## Legacy Provider names

The historical Python and on-disk names describe executable MCP Providers,
not Knowledge Skills:

| Legacy name | Canonical product meaning |
|---|---|
| `SkillManifestV1` / `skill.yaml` | Capability Provider Manifest |
| `SkillConfig` | Capability Provider runtime configuration |
| `SkillConnection` | MCP Provider connection |
| `SKILLS.lock` | Provider and live tool-schema run snapshot |

`CapabilityProviderManifest`, `CapabilityProviderConfig`,
`MCPProviderConnection`, and `ProviderLock` are semantic aliases over the
same existing classes and serialized bytes. `skill.yaml` and `SKILLS.lock`
remain the only canonical v1 files. ARI does not create `provider.yaml` or
`PROVIDERS.lock`, so a run cannot acquire two sources of truth. The package
prefix `ari-skill-*` remains compatible; CLI, API, and UI use “Capability
Provider” when referring to its execution authority.

## Dependency boundary

```text
ari.rqgm.knowledge_bridge -> ari.knowledge
ari.knowledge             -> ari.capability_binding contracts
ari.capability_binding    -> ari.providers / ari.mcp

ari.rqgm.assurance_bridge -> ari.assurance
```

`ari.knowledge` and `ari.assurance` do not import `ari.rqgm`.
`ari.assurance` does not bind Agent tools, and `ari.providers` does not select
Knowledge or Harnesses. Shared contracts live under `ari.protocols` and the
read-only supported API under `ari.public`.

## Run admission and frozen identities

For an enabled `ari_rqgm` run, the trusted coordinator completes this order
before the first research node executes:

```text
foundation bootstrap
  -> catalog snapshots
  -> ResearchContractV1
  -> Router selection proposal
  -> fixed Knowledge admission and EpochKnowledgeSkillLockV1
  -> capability requirement union
  -> fixed CapabilityBindingLockV1
  -> VerificationContractV1
  -> fixed Harness suite resolution and BaselineHarnessLockV1
  -> run admission commit
  -> first execution epoch freeze
  -> Agent execution through bound Providers
  -> target-bound HarnessAttestationV1
```

The admission transaction is stored under
`rqgm/kca/admission-v1/`. Resume loads those persisted snapshots and locks;
it never resolves against the current catalogs. An epoch can only add a Skill,
binding, or Harness through an append-only revision adopted at its boundary.
A node cannot replace its active Knowledge body, binding, or target
Attestation after execution begins.

Instruction identity includes the base and active RQGM prompt hashes, ordered
Knowledge body hashes, composition digest, Capability Binding Lock digest,
Verification Contract digest, and active Harness Lock digest. Provider tool
descriptions are untrusted operation metadata placed below the authoritative
instructions; text in a Knowledge body or Provider description cannot widen
the visible tool set.

## Knowledge packages

A package contains `SKILL.md`, `skill.meta.yaml`, and optional files under
`references/`. Its manifest is `KnowledgeSkillManifestV1`. Executable fields,
commands, environment/credential declarations, entrypoints, and transports
are schema errors. Scripts and notebooks found during import remain
non-executable attachments. Execution requires separate registration as a
Capability Provider, Harness driver, or trusted build-time importer.

External sources are imported at an immutable full commit plus repository,
subpath, manifest/body/reference full SHA-256, license, and importer version.
Branches, tags, and `latest` are not run-time sources. Tool names mentioned in
prose are recorded only as non-authoritative hints. A fixed, prompt-free
Knowledge Binder checks verified status, applicability, dependencies,
conflicts, authority ceiling, forbidden capabilities, and evaluation
obligations before minting the epoch lock.

### External import adapters

`ari.knowledge.external_importer` supports four candidate-only admin paths:

- an exact Git repository commit and subtree;
- the same Git adapter for explicitly configured scientific Skill sources;
- the [Open Agent Skills specification](https://openagentskills.dev/docs/specification),
  including required YAML frontmatter and optional `references/`, `scripts/`,
  and `assets/`; and
- a ToolUniverse Knowledge collection described by a separate ARI-side
  `ToolUniverseKnowledgeCollectionProfileV1`.

Git import initializes a temporary bare object database, fetches only the
caller-supplied full commit, verifies that exact commit, and reads regular blob
bytes with `ls-tree`/`cat-file`. It never checks out the repository, invokes a
source hook, reads a branch/tag, or runs an imported script. Symlinks,
submodules, special entries, path escapes, unsafe remote-helper schemes, and
URL-embedded credentials are rejected. The material records the repository,
commit, subtree, tree snapshot digest, original `SKILL.md` digest, generated
body/manifest/reference digests, attachment digests/modes, importer version,
and the separate admin-profile digest.

Open Agent Skills frontmatter is source metadata only. `allowed-tools` and
`compatibility` are non-authoritative hints; `scripts/`, notebooks, and assets
are digest-bound attachments with `authority: none`. Capability requirements,
evaluation obligations, authority ceilings, and forbidden capabilities come
only from `KnowledgeSkillImportProfileV1`, supplied outside the untrusted
source. `body_normalization: strict` requires the upstream body to contain all
ARI Knowledge sections. The explicitly reviewed `ari-wrapper-v1` alternative
quotes every upstream line inside a fixed ARI body containing the required
preconditions, authority boundary, failure semantics, expected artifacts,
scientific cautions, and evaluation obligations. Its `curation_notes` come
only from the separately hashed admin profile. Neither mode grants executable
authority. Every import enters with `status: candidate`.

`ari.knowledge-import-material/v1` is self-contained: it stores the normalized
body, manifest, reference digests, attachment digests and source executable
bits, non-authoritative tool hints, exact external provenance, and its own full
SHA-256. A checked-in catalog may reference that one material instead of
creating a second manifest/body source of truth. Catalog loading validates the
entire material offline; it never re-fetches the repository.

```bash
ari knowledge import \
  --source-kind open-agent-skills \
  --repository https://github.com/example/scientific-skills.git \
  --commit 0123456789abcdef0123456789abcdef01234567 \
  --subpath skills/reproduction-method \
  --profile reviewed-import-profile.yaml \
  --output candidate-import-material.json
```

### Registered Intel performance candidates

The catalog pins `intel/intel-performance-skills` at full commit
`e9d0b6410fb1ad7a50fb81e0868fd23ae886882c` and registers three separate
candidate Knowledge identities:

| Knowledge ID | Upstream subtree | Boundary |
|---|---|---|
| `intel.performance-patterns` | `skills/performance-patterns` | x86 C/C++ optimization knowledge; bundled C and executable test assets remain authority-none attachments |
| `intel.linux-perf` | `skills/linux-perf` | profiling knowledge requiring bound hardware-counter capability; `sudo` and host sysctl changes are prohibited |
| `intel.phoronix-test-suite` | `skills/phoronix-test-suite` | workflow knowledge for pre-pinned PTS inputs; runtime refresh, download, install, home, and `/var/lib` writes are prohibited |

The three entries are neither Providers nor Harnesses. They do not activate
`perf`, Phoronix, a compiler, a shell, or a credential; concrete execution is
resolved only from a Capability Binding Lock. A Phoronix score is not a
Harness Attestation. Candidate status also prevents activation by the fixed
Knowledge Binder in enforce mode until the remaining clean-task, portability,
and human-promotion evidence exists.

ToolUniverse collection profiles contain Knowledge subpaths and their admin
profiles, but have no Provider ID, launcher, tool, credential, or transport
field. The resulting identity uses the
`ari://knowledge-source/tooluniverse/...` namespace and emits
`provider_activated: false`; it is independent from ToolUniverse's MCP Provider
and nested Provider locks.

## Capability ontology and Provider binding

`CapabilityContractV1` fixes semantic inputs/outputs, side effects,
determinism, context, permissions, resources, version, and compatibility.
Provider registration checks the live input/output schema against that
contract. A shared text label is insufficient semantic compatibility.

The prompt-free Capability Binder considers only exact capability refs and
contract digests from verified Providers already present in the existing
Provider lock. It filters by role, phase, call context, side-effect ceiling,
credential scope, environment, disabled tools, and live schema identity. It
then ranks deterministically by exactness, verified status, explicit pin,
context fit, least side effect, determinism, reproducibility, feasibility,
resource cost, and lexicographic `tool_ref`. Missing coverage is
`unsatisfied`; there is no substring, bare-name, LLM, or network fallback.

In enforce mode the Agent sees exactly:

```text
Provider Lock tools
intersect Capability Binding Lock
intersect role authority
intersect phase policy
intersect call context
minus user-disabled tools
```

### Environment evidence and Provider substitution

`ari.capability_binding.environment` records observed substrate facts before
binding. It executes bounded, shell-free probes for SLURM partitions, local
NVIDIA devices, and the CUDA compiler. If `resources.gpus` is positive, SLURM
is ready, and no local device is visible, it additionally runs one bounded
compute-node `nvidia-smi` query through `srun`. Declared config remains metadata
and cannot fabricate a resource.

SLURM GPU visibility and scheduler authority are intentionally different. A
device observed on a compute node without advertised GPU GRES is retained under
`metadata.slurm_gpu` and adds `gpu-observed-on-slurm-node`, but it does not add
the `gpu` resource type. It becomes schedulable only when GRES is observed or
the operator explicitly enables the pre-existing
`ARI_SLURM_ALLOW_NO_GRES=1` escape hatch. The complete observation, including
device UUID/model/compute capability/memory/driver and output digests, is part
of the frozen environment identity; resume does not reprobe and silently
replace it. `EnvironmentSnapshotV1` recomputes that canonical full-SHA identity
when persisted data is loaded, so adding a fabricated resource or changing an
observed fact invalidates admission.

ToolUniverse Capability authority is also exact. A reviewed category profile
may map an exact leaf name to a canonical `capability_ref`, equivalence key,
and result normalizer. Substrings and Provider descriptions never participate.
The first projection maps `PubMed_search_articles` to
`ari.literature.search/v1` and converts its live response to
`ari.retrieval-result/v1` with per-record source identity and full payload
digests. Production sync requires the reviewed wheel/package tree, the exact
upstream dependency-lock bytes, a closed installed dependency environment, and
live compact-MCP schema parity.

`probe_provider_substitution` disables the primary Provider's exact locked
tools and invokes the production Binder twice. It emits a digest-bound report
whose binding determinism/status is separate from optional live operation
observations. Thus two Providers can return the same semantic result while the
substitution remains binding-`unsatisfied` because one Provider is candidate,
drifted, or otherwise inadmissible.

## Verification, Harnesses, and Attestations

Harness kinds are closed and non-substitutable:

- `benchmark` evaluates a fixed benchmark subject and cannot verify an
  arbitrary external target;
- `artifact_verifier` verifies a generated program/library for its declared
  target kind and properties;
- `reproduction` evaluates a paper/repository reproduction package;
- `claim_verifier` checks claim/evidence consistency without proving the
  recorded computation correct.

`VerificationContractV1` is mint-once, canonical-JSON and full-SHA bound.
Knowledge evaluation obligations can only add properties/methods; they cannot
remove a requirement, lower `certify -> validate -> screen`, relax tolerance,
or name an authoritative Harness. A fixed Resolver performs exact compatibility
filtering and deterministic set cover. The baseline lock is immutable;
revisions only add a Harness or strengthen a property at an epoch boundary.

The Fixed Verifier receives an immutable target snapshot and executes only the
locked driver, oracle, dataset, and container. It writes a full-SHA
`HarnessAttestationV1` bound to the run/node/epoch, contracts, Knowledge use,
Provider/Binding locks, Harness locks and source assets, target digest,
execution identity, per-property verdicts, and evidence artifacts. Verdicts
are `pass`, `fail`, `inconclusive`, `infrastructure_error`, or `tampered`.
Provider success is never an Attestation, and a candidate failure alone is not
a constitutional violation.

The native `hpc/gemm-correctness`, `hpc/spmm-correctness`, and
`hpc/stencil-correctness` implementations include deterministic generated
cases, independent references, dtype/accumulation-aware error models,
metamorphic/shape/boundary/repeat coverage, and negative controls. Promotion
to a checked-in verified catalog entry remains a release admission action: it
requires a committed source revision, immutable container, license review,
reference pass, negative-control fail, and retained registration report.

Inspect, Harbor, KernelBench/ComputeEval/scBench, and PaperBench adapters do
not fork their upstream frameworks. Their drivers validate a pinned official
route and normalize a strict result envelope. Without a digest-bound official
runner parity report, the registration result is `not_available` and the
entry remains `candidate`; no reduced or local fallback is used.

`ExternalHarnessParityReportV1` is the authoritative parity input. A `passed`
report must bind the Harness Manifest, source revision, dataset, container, and
driver; retain the official invocation, official result, and normalized result
digests; pass a reference; fail a wrong-submission negative control; and prove
result-schema parity. API import, CLI presence, or scorer-unit compatibility can
appear only as `non_authoritative_checks`. The
`passed` schema also rejects shortened source revisions and all-zero digest
placeholders. The
`ari-skill-paper-re/scripts/verify_paperbench_upstream.py` diagnostic runs the
credential-free upstream API and deterministic aggregation checks, but
deliberately emits `official_runner_status: not_available` until the official
rollout, reproduction, and judge route and all external pins are supplied.

### Verification resource accounting

After a valid Attestation has been constructed and revalidated, the RQGM
Assurance bridge records one verifier execution in `cost_trace.jsonl`. The
record binds the Harness, execution identity/attempt, Attestation, node, epoch,
tier, execution status, backend, executor wall interval, and declared
CPU/accelerator/memory allocation. The derived CPU/accelerator/memory values are
allocation × observed wall interval, not utilization samples. Task 20 reports
resource totals and per-valid-node values separately for `screen`, `validate`,
and `certify`. A dollar value is recorded only when an authoritative charge or
price is supplied; otherwise `cost_status: unpriced` prevents an unknown charge
from appearing as free.

## Modes and compatibility

```yaml
knowledge:
  mode: off       # off | audit | enforce
capability_binding:
  mode: legacy    # legacy | audit | enforce
assurance:
  mode: off       # off | audit | enforce
```

The defaults preserve `simple_bfts`. When all three defaults are active, ARI
does not import the new domain packages on the run path and creates no catalog
snapshot, lock, checkpoint field, metric, prompt-byte, or visible-tool change.
Explicit Knowledge, capability, or verification requirements conflict with an
off/legacy mode and fail run admission. `ari_rqgm` enforce requires every
corresponding immutable snapshot and lock.

## Surfaces and administration

Human diagnostic commands are under `ari knowledge`, `ari provider`, and
`ari harness`. The dashboard Governance workspace renders three separate
catalog cards and their locks/provenance. `ari-skill-knowledge` and
`ari-skill-harness` are default-off query/request Capability Providers. Their
MCP requests are non-authoritative; they cannot register, promote, revoke,
rewrite a lock, replace an oracle, change tolerance, or force a pass.

Catalog lifecycle changes require reviewed repository changes or an
authenticated human admin path. Revocation appends taint/status history and
never rewrites old locks, Attestations, or provenance.

## Honest limits

Knowledge quality and the capability ontology require human curation. Two
Providers for the same capability can behave differently. External service,
model, and hardware identity can be only as complete as the substrate exposes.
Static inspection cannot prove all Provider descriptions harmless. Harness
pass applies only to declared properties and scope; only a formal-verifier
Harness proves a formal specification. Nondeterminism and unavailable external
pins remain explicit provenance. Infrastructure error never fails open. RQGM
does not invent a verifier's scientific conclusion; it governs actors that
ignore, suppress, or misrepresent the fixed result.

## Extension gate

New Knowledge, Provider, and Harness entries use their respective registration
gate in `ari.knowledge.registration`, `ari.providers.registration`, and
`ari.assurance.registration`. Candidate files never enter an existing run
lock. A maintainer must retain full source/data/container/license pins and all
gate evidence before changing status to `verified`.
