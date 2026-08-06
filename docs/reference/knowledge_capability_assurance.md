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
Harness Attestation. All three now carry measured clean-task and portability
evidence, clear all sixteen gates, and have been promoted to `verified` on a
recorded approval, so the fixed Knowledge Binder can admit them. The three HPC
optimization Skills followed the same path, so every catalog entry is now
verified on a recorded approval. A threaded clean task first measured
below its own serial baseline because the typed Provider ran the payload in the
batch step, which inherits the whole node in its affinity mask; the Provider now
runs a single-task payload as a bound job step.

### Eligibility is not promotion

Clearing the gates only makes a Skill eligible. `status: verified` in the
catalog additionally requires `ari.knowledge-skill-promotion-approval/v1`,
bound to the exact `skill_ref` (manifest and body bytes) and to the
registration evidence that was reviewed. Catalog loading refuses a verified
entry whose registration decision is not `eligible-for-verified`, whose
approval is absent, or whose approval names other bytes; it equally refuses an
approval attached to an entry nobody promoted. Editing a manifest, a body, or
the evidence invalidates the approval instead of silently carrying it forward.

Promotion has one writer: `scripts/promote_knowledge_skill.py`. It refuses a
Skill whose decision is not `eligible-for-verified`, names the approver and
the basis, and records both the approval and an append-only
`ari.knowledge-skill-status-transition/v1` entry.
`GovernedKnowledgeSkillRegistry.transition` refuses a promotion without a
matching approval as well, so the ledger and the catalog cannot disagree
about who promoted what.

Portability is decided by withdrawing the incumbent Provider and re-offering
the identical capability contracts under a reserved stand-in identity
(`method: synthetic-substitution`), which asks whether the Skill names a
capability or a Provider. It is strictly weaker than executing a second
implementation and is never described as cross-Provider portability. The
original `method: two-providers` rule remains available and unchanged.

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

`compatibility_rules` is a closed vocabulary. It was a free-form string tuple —
digest-bound, documented, and consulted by nothing, so every rule name in the
ontology was inert. A name outside the reviewed table is now refused, and each
name states where it is checked: `measurement-envelope-v1` in core, four
result-shape rules by the Provider that supplies the capability against its own
golden and replay evidence, and the rest explicitly `unenforced`. That last
group is honest rather than fixed: no shipped contract declares
`semantic_inputs` or `semantic_outputs`, so a structural rule has nothing to
compare against, and populating them is separate work.

`measurement-envelope-v1` says a measurement is only interpretable together with
the conditions it was taken under, so a contract claiming it must declare the
`nondeterminism_fields` that are those conditions. One that claims the rule and
names no conditions is refused at load — it is not stating an envelope at all.

A run's requirements come from two sources. Admitted Knowledge Skills declare
what their instructions presuppose, and `capability_binding.required_capability_refs`
lets the operator declare what the run's own task needs. The second exists
because the first was the only one: a domain instrument no Knowledge Skill
happens to mention could hold a contract, a reviewed supplier, admitted
evidence, and a proven invocation path and still never be *asked for*, so it
would never bind. The declaration is config, never model output; a ref outside
the reviewed ontology is refused rather than ignored; the contract — not the
declaration — fixes the side-effect ceiling, resources, and environment; and a
Knowledge Skill's requirement for the same capability is never replaced by it.
Naming a required ref while leaving binding in `legacy` mode is refused, since
the requirement would otherwise be silently dropped.
`optional_capability_refs` binds when supplied and never fails a run.

The prompt-free Capability Binder considers only exact capability refs and
contract digests from verified Providers already present in the existing
Provider lock. It filters by role, phase, call context, side-effect ceiling,
credential scope, environment, disabled tools, and live schema identity. It
then ranks deterministically by exactness, verified status, explicit pin,
context fit, least side effect, determinism, reproducibility, feasibility,
resource cost, and lexicographic `tool_ref` then `subject_tool_ref`. Missing
coverage is `unsatisfied`; there is no substring, bare-name, LLM, or network
fallback.

In enforce mode the Agent sees exactly:

```text
Provider Lock tools
intersect Capability Binding Lock
intersect role authority
intersect phase policy
intersect call context
minus user-disabled tools
```

### Brokered leaves and composite provisions

A domain instrument reached through a broker is not an ARI Provider and never
appears in the Provider Lock, so the Binder cannot authorize it directly.
`ari.providers.brokered` supplies the missing half: a Provider catalog entry may
carry a `brokered` block naming a federated catalog lock, a dispatch tool, and a
reviewed table from leaf `tool_ref` to ARI `capability_ref`. Each reviewed leaf
becomes one `CapabilityProvisionV1` whose `tool_ref` and `dispatch_tool_ref` are
the broker's dispatch tool — the only ref the run lock contains — and whose
`subject_tool_ref` is the leaf. `nested_source_lock_digests` carries the leaf's
source digests, and the federated lock's own `catalog_digest` joins the
Provider's `nested_source_lock_digests`, so swapping a leaf behind the broker
changes the Provider catalog snapshot that the binding request pins.

A site selects its federated lock with `ARI_TOOL_REGISTRY_LOCK`, and ARI reads
the same variable. This is not a convenience: if ARI projected the packaged
lock while the broker dispatched a site lock, every composite provision would
describe a leaf that is not the one being called. The packaged `CATALOG.lock`
is empty on purpose — a materialized one records absolute local paths and
cannot be committed — so the reviewed leaf-to-capability table lives in the
repository while the lock it refers to stays at the site.

A provision carries only the credential scopes whose values are actually
present. A declared-but-absent credential confers no authority — the child
process is built from present values alone, and the call context already
filters the same way — so carrying the declared set made every provision of a
multi-domain Provider demand every scope it might ever use. Binding an EDA tool
through the broker required granting an IBM Quantum credential that was not set
anywhere. Presence is observed at lock time and frozen into the Provider Lock,
so a token that appears later changes the lock rather than slipping past.

A leaf whose descriptor declares an asynchronous lifecycle is submitted through
the dispatch tool and completed through others. Those are not separate
capabilities — polling a job you were authorized to submit adds no authority —
but they are separate `tool_ref`s, so the composite carries them as
`lifecycle_tool_refs` and the authorization view admits them under the same
binding, phase, and call context. Without that, a bound async capability starts
work whose result the run is not authorized to collect. A synchronous leaf gets
no lifecycle surface.

Four properties are enforced rather than assumed:

- The federated lock is re-authenticated. ARI recomputes `catalog_digest` under
  the broker's own canonicalization and re-checks one admission per tool, unique
  ids, and a single policy digest. An edited lock is refused, not projected.
- Authority is the envelope of both hops. Side-effect class is the worse of the
  leaf's and the dispatch tool's declarations, and a contract's required
  permissions must be granted by both — the broker because the runtime gates it,
  the leaf because it does the work.
- The mapping is never the broker's. A descriptor's own `capability_ref` is the
  broker's namespace; it is recorded as `declared_capability_ref` for drift and
  never read as a mapping. Only the checked-in reviewed table decides.
- Reproducibility is capped by admission. A leaf admitted only `callable` grades
  `unknown` whatever its determinism field claims; `reproducible` grades at best
  `bounded`, `scientifically_admitted` at best `exact`. A leaf admitted below its
  own `required_level`, a quarantined leaf, a reviewed leaf absent from the
  catalog, and a dispatch tool absent from the run lock are all refusals.

### Environment evidence and Provider substitution

`ari.capability_binding.environment` records observed substrate facts before
binding. It executes bounded, shell-free probes for SLURM partitions, local
NVIDIA devices, and the CUDA compiler. If `resources.gpus` is positive, SLURM
is ready, and no local device is visible, it additionally runs one bounded
compute-node `nvidia-smi` query through `srun`. Declared config remains metadata
and cannot fabricate a resource.

It also decides the container runtime by executing it. `shutil.which` finding a
binary is not the fact that matters — a runtime can be installed and refuse to
run — and the two forks of Singularity are installed under different names at
different sites, so `--version` is run and the name that answered is what gets
recorded. The executable's path is deliberately not kept: it is site-dependent
and binding needs none of it.

Turning an observed fact into an ontology resource class is a separate act, and
`config/capabilities/resource_derivations.yaml` is where it happens. Each row
names what it emits, what must already be present, and the reason; a row without
a rationale is refused at load, because a derivation without a reason is an
alias and an alias is what the table exists to prevent. Rows are applied to a
fixpoint so one may consume what another emitted, nothing can invent a fact the
prober did not observe, and the rows that fired are recorded in
`metadata.derived_from_review` — so a binding that depended on a derived
resource class can be audited back to the sentence that allowed it. The shipped
table records that Apptainer and SingularityCE both execute SIF and that neither
podman nor docker does, then derives `eda-cpu` from CPU plus a SIF runtime.

Outbound reach is observed from the route table rather than by contacting
anything. A default route is the kernel saying it has a path off this host: it
is necessary and not sufficient — a proxy or firewall can still refuse the call
— which is the standing `sinfo` answering gives the scheduler. The stronger
evidence, resolving a name or opening a connection, would be an outbound request
to somebody else's service made only to describe our own substrate. On an
air-gapped node there is no route and the retrieval capability stays unsupplied.

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

The composite-provision path has been called end to end. A real materialized
OpenROAD leaf — a `scientifically_admitted` descriptor — was bound in enforce
mode, dispatched through the broker's `invoke`, polled to completion through the
bound lifecycle tools, and returned CTS-plus-routing metrics inside the ranges
its promotion golden fixes: 0 DRC errors, 3603 um wire length, 3361 vias, in
about fifty seconds inside the pinned SIF.

Getting there took three fixes, and each had made the path unusable rather than
merely awkward. The broker's tool schemas set `additionalProperties: false`
without declaring `ari_context`, so the transport's injected call context was
rejected and no context-gated broker tool could ever be called. The result
normalizer treated the presence of an `error` key as failure, so every Provider
returning `ari.result-envelope/v1` — the schema ARI itself defines — had its
successes reported as tool errors with the message `null`. And a bound
asynchronous capability had no authority over its own lifecycle tools, so it
could start work and never collect it.

`ari.literature.search/v1` was blocked by its own contract, not by the envelope
rule. It declared `read-only` while both the reviewed PubMed leaf and the
broker's `invoke` declare `stateful`, so nothing could ever supply it. The
contract was wrong: an admitted retrieval writes the record that makes it
evidence — cassettes and content-addressed payloads land in the run's EAR — and
the ladder grades a call by what it does to this substrate, not by whether it
mutates the remote index. It is now `workspace-write`, and the reviewed PubMed
leaf builds a composite against it. Registering that mapping needs a site lock
containing the leaf; the reviewed table names leaves across all of a site's
sources, so a site that wants both EDA and retrieval materializes one lock over
both rather than a lock per domain.

`ari.quantum.sample.local-ideal/v1` is supplied. Its promoted local-Aer bundle
was materialized but never registered, so a site source was assembled from the
bundle's own materialized profile — nothing invented, since a wrong value fails
the catalog build — and the leaf now binds and runs: 4096 shots of a seeded
Bell circuit returning `{"00": 2046, "11": 2050}` and no other outcome, inside
the ranges the promotion golden fixes, in about ten seconds. That is the bridge
working on a second domain and a second adapter kind, from one lock holding
both sources.

Its `environment_requirements: [cpu]` was the same category error and is
corrected. `quantum-simulator` now has a derivation row from `cpu` alone. That
row was deliberately withheld while nothing supplied the capability — a row that
fires on every substrate and makes an unsupplied capability look resolved is
worse than none — and is simply accurate now: a seeded two-qubit CPU statevector
pass needs a CPU and nothing else. What bounds it is the digest-pinned artifact
the catalog verifies, which no derivation can see; a substrate claim is not an
availability claim.

The CUDA contract's `slurm` requirement was the same category error and now
reads `slurm-controller`, the feature the prober actually emits; `gpu-slurm`
gained a derivation from the two halves the prober emits separately. Its
`cuda-12.9`, `nvidia-sm70`, and `exclusive-node` requirements remain
unsatisfiable: they are version, hardware-generation, and allocation facts that
need a GPU node to observe and could not be verified from a login node.

## Extension gate

New Knowledge, Provider, and Harness entries use their respective registration
gate in `ari.knowledge.registration`, `ari.providers.registration`, and
`ari.assurance.registration`. Candidate files never enter an existing run
lock. A maintainer must retain full source/data/container/license pins and all
gate evidence before changing status to `verified`.
