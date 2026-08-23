# Task 18: Scientific Assurance and Harness Registry

> **Status**: in progress · **Depends on**: 01, 04, 12, 16, 17,
> `ari_rqgm_paper/07` · **Implementation checkpoint**: 2026-08-04 · **This is a
> temporary task plan** — see [INDEX.md](INDEX.md). Contracts, resolver/locks,
> isolated fixed-runner path, target-bound Attestation, native HPC verifier
> core, fail-closed typed external parity reports, PaperBench upstream API and
> deterministic aggregation compatibility checks, and tests have landed.
> Official end-to-end runner parity, pinned datasets/containers/licenses, real
> accelerator matrices, and verified catalog promotion remain external
> completion gates; the production catalog stays empty rather than admitting
> placeholders.

## 1. Purpose

Build the RQGM-independent `ARI Harness Registry` and `Scientific Assurance`
layer that resolves declared verification properties to independently pinned
Harnesses, runs them outside agent tool choice, and issues artifact-bound
Attestations. This task separates scientific failure from infrastructure
failure and separates fixed verification from evaluation, review, and
governance.

```text
Verification Contract fixes what must be shown.
Harness Resolver fixes how it will be checked.
Harness Lock fixes exact code/data/oracle/container identities.
Fixed Verifier executes the lock against an immutable target.
Attestation records scoped facts.
RQGM governs actors that misuse those facts; it does not recompute them.
```

## 2. Scope

- Verification Contract, requirement/proposal, auxiliary-request, and
  monotonic admission semantics.
- Harness manifest, catalog snapshot, registration, status, suite, baseline
  lock, lock revision, run request, property result, and Attestation.
- Pure deterministic Harness resolution with complete property coverage.
- Secure runner reuse of ARI's typed execution/workspace/result contracts.
- Typed `benchmark`, `artifact_verifier`, `reproduction`, and
  `claim_verifier` kinds.
- Screen/validate/certify tiers and target/frontier/publication semantics.
- Native GEMM, SpMM, and Stencil artifact verifiers with non-degenerate test
  matrices, explicit oracles/error models, metamorphic checks, sanitizers,
  negative controls, and evidence.
- Pinned external drivers for PaperBench, Inspect, Harbor, and upstream-native
  runners, including initial catalog entries.
- Registration tests, upstream parity, drift detection, isolation, retry, and
  resume rules.

## 3. Non-goals

- No authoritative Harness selection by Generator, Router, Evaluator,
  Reviewer, MCP tool choice, or Capability Provider.
- No embedding Harness IDs in `MetricCorrectnessV1`.
- No replacement of the current claim-evidence hard gate.
- No reimplementation of PaperBench's rollout/reproduce/grade bridge.
- No copying external framework repositories or large datasets into ARI.
- No claim that a benchmark validates an arbitrary BFTS artifact.
- No weighted correctness/performance objective.
- No constant-pass stub, single-shape smoke implementation, empty adapter, or
  unverified placeholder counted as complete.
- No implementation under `ari.rqgm.evaluation`.

## 4. Harness kinds and non-substitutability

`HarnessManifestV1.kind` is a closed enum:

| Kind | Subject | Initial examples | Constitutional use |
|---|---|---|---|
| `benchmark` | a model/agent on a fixed task set | SciCode, ScienceAgentBench, KernelBench, ComputeEval, scBench | Measures system ability; cannot admit an arbitrary node when `accepts_external_target=false`. |
| `artifact_verifier` | this run's program, library, binary, kernel, or data artifact | native GEMM/SpMM/Stencil correctness | May gate node correctness only when target interface and all property scopes match. |
| `reproduction` | paper/repository/experiment package | PaperBench, CORE-Bench | Assures reproducibility properties, separately from artifact correctness. |
| `claim_verifier` | a claim and its cited/measured evidence | current claim-evidence hard gate | Assures transcription/derivation/evidence consistency, not the underlying computation. |

Invariants:

1. Registering SciCode or KernelBench does not certify an arbitrary GEMM.
2. Only an `artifact_verifier` with matching external-target, target-kind, and
   property coverage can gate a BFTS candidate.
3. `claim_verifier` cannot replace program correctness.
4. `reproduction` and artifact correctness remain different requirements.
5. Knowledge self-report and Provider success are never Harness evidence.
6. A benchmark result may inform Task 20 meta-evaluation but cannot silently
   become a node Attestation.

## 5. Verification Contract

### 5.1 Types

`VerificationRequirementV1` contains:

```text
property_id
target_kind
required_methods
required_tier                 # screen | validate | certify
required_verdict              # normally pass
failure_policy
scope                         # language/hardware/architecture/dtype/domain
tolerance_policy_ref/digest   # no free mutable numeric override
independence_requirement
determinism_requirement
source_requirement_refs
```

Example:

```json
{
  "property_id": "numerical-equivalence",
  "target_kind": "shared-library",
  "required_methods": ["differential-testing", "metamorphic-testing"],
  "required_tier": "screen",
  "required_verdict": "pass",
  "failure_policy": "exclude-from-scientific-frontier",
  "scope": {
    "language": ["c", "cpp"],
    "hardware": ["cpu"],
    "dtype": ["float64"]
  }
}
```

`VerificationRequirementProposalV1` and
`AuxiliaryVerificationRequestV1` are non-authoritative. They identify the
proposer, prompt/epoch, evidence, requested property/method/tier/scope, and
parent Verification Contract/active Harness lock digests. A proposed Harness
ID is stored only as `non_authoritative_hint` and excluded from resolver input.

`VerificationContractV1` contains run/Research Contract digest, canonical
sorted requirements, baseline Knowledge obligation refs, admission confidence,
human-review identity when required, property vocabulary digest, schema
version, and its own full SHA-256. It is frozen/mint-once using the same
canonical JSON/digest-bound pattern as `ResearchContractV1`.

### 5.2 Admission and monotonicity

Baseline admission performs:

```text
Research Contract requirements
∪ admitted baseline Knowledge Skill evaluation obligations
→ normalize by property vocabulary
→ reject contradictory scope/method/tolerance
→ preserve the stronger tier/method/tolerance requirement
→ mint VerificationContractV1
```

Knowledge obligations declare properties and methods, never Harness IDs. They
may add a requirement or strengthen tier/method/scope; they cannot delete a
Research Contract requirement, lower `certify→validate→screen`, remove a
required method, relax tolerance, or change a required verdict.

After run start, the baseline Verification Contract is immutable. An admitted
auxiliary request forms an append-only requirement revision referenced from a
`HarnessLockRevisionV1`; only monotonic additions/strengthenings are legal. A
next-epoch Knowledge Skill with a new obligation stays inactive until the
revision has complete coverage.

Low-confidence automatically derived requirements require authenticated human
review before enforce admission. Required requirements with `assurance.off`
are a run-admission error.

## 6. Harness contracts

### 6.1 `HarnessManifestV1`

Every manifest contains:

- `id`, `version`, `kind`, and status
  `candidate | verified | deprecated | revoked`;
- description, maintainer, tags, subject/target types, and
  `accepts_external_target`;
- supported languages, hardware, architectures, dtypes, and domains;
- provided assurance properties, methods, tiers, and exact scope;
- target interface contract and digest;
- source repository and full commit SHA;
- dataset revision/full SHA-256;
- oracle revision/full SHA-256;
- driver revision/full SHA-256;
- container reference and resolved image/SIF digest;
- separate implementation/data/model/container licenses;
- network policy, credential policy, filesystem policy, resource requirements,
  and timeout;
- scorer determinism and nondeterminism declaration;
- hidden-test policy and oracle independence;
- tolerance/error-model policy digest;
- expected normalized result schema/digest;
- infrastructure-failure classification/retry policy;
- negative-control metadata/report digest; and
- upstream parity metadata/report digest.

Mutable tags and shortened hashes are schema errors. Fields that do not apply
use explicit `none` enums rather than an omitted ambiguous identity.

### 6.2 Catalog and suite types

`HarnessCatalogSnapshotV1` freezes sorted manifests, status-at-snapshot,
registration report digests, catalog source revision, property vocabulary,
driver protocol version, and its own digest.

`HarnessRequirementV1` is the resolver-normalized atom derived from a
Verification Requirement: one property/method/tier/target/scope/tolerance and
source refs.

`HarnessSuiteV1` records the ordered exact Harness set, each coverage bitset,
the union coverage proof, aggregate resource declaration, verification
environment constraints, and resolver objective tuple.

### 6.3 Lock types

`BaselineHarnessLockV1` records the Research/Verification Contract and catalog
digests, verification environment and oracle bundle digests, exact suite,
manifest/dataset/oracle/driver/container/result-schema digests, coverage proof,
producer `harness_resolver_v1`, `prompt_hash: null`, and lock full digest.

`HarnessLockRevisionV1` records `parent_lock_digest`,
`baseline_lock_digest`, added requirement refs, added or strengthened Harness
entries, next epoch, coverage proof, and full digest. The accepted relationship
is `H_(t+1) ⊇ H_t`, or an additional stronger tier/method for the same
property. It cannot remove a Harness, downgrade version/tier, relax tolerance,
or replace oracle, dataset, driver, container, or prior bytes.

### 6.4 Run/result types

`HarnessRunRequestV1` contains run/node/epoch, active lock, Harness entry,
immutable `WorkspaceRefV1` target, `ResearchArtifactRefV1`, target logical
name/kind/full digest, property atoms, `ExecutionRequestV1`, attempt/retry
identity, and expected result schema.

`HarnessPropertyResultV1` contains property, method, tier, tested scope,
verdict, measurements, tolerance/error-bound evidence, oracle comparison,
coverage, and evidence artifact refs.

`HarnessAttestationV1` contains:

```text
attestation full SHA-256 identity
run_id / node_id / epoch_id
producer_component_id = fixed_verifier_v1
producer_prompt_hash = null
producer_epoch_id
Research Contract digest
Verification Contract digest
Knowledge Skill use digest
Capability Binding Lock digest
baseline Harness Lock digest
active Harness Lock revision digest
Harness Manifest / driver / oracle / dataset / container digests
target logical name / target full SHA-256 / target kind
execution identity / ExecutionResult digest
verdict
per-property verdict / method / scope / metrics
evidence artifact refs
infrastructure status
nondeterminism declaration and observations
retry / attempt identity
```

Verdicts are exactly `pass | fail | inconclusive | infrastructure_error |
tampered`. `fail` means the target failed a scientific property.
`infrastructure_error` means the verifier could not establish that property.
They never normalize to one another.

An Attestation is valid only when its target digest equals the current node
candidate digest, every source/lock/manifest/execution/evidence digest resolves,
the scope covers the requirement, the producer is the fixed verifier, and it
is not stale or revoked for current use.

## 7. Deterministic Harness Resolver

`ari.assurance.resolver` is pure and has no RQGM import, LLM, network, wall
clock, random order, catalog write, contract write, or target access.

Authoritative selection follows one fixed separation:

```text
ResearchContractV1 / VerificationContractV1
  → Evaluator/Reviewer property proposals (non-authoritative)
  → harness_resolver_v1 produces HarnessSuiteV1 + lock candidate
  → ConstitutionalKernel validates coverage, actor authority, digests,
    monotonicity, tier, and tolerance
  → trusted runtime mints BaselineHarnessLockV1/HarnessLockRevisionV1
  → fixed_verifier_v1 executes the locked suite
  → Evidence Clerk admits the Attestation
  → Auditor/Defender/Judge govern contradictory actor conduct
```

An Evaluator-supplied Harness ID remains a stored hint and is excluded from the
resolver input. The Kernel validates procedure and integrity only; it does not
recompute the resolver's scientific property mapping or verifier verdict.

### 7.1 Candidate filter

For each requirement atom, an eligible Harness must have:

1. verified status;
2. exact property coverage;
3. compatible target kind and `accepts_external_target` behavior;
4. compatible language, hardware, architecture, dtype, and domain scope;
5. every required method;
6. tier at least the requested tier;
7. an equal/stricter tolerance policy;
8. the required scorer determinism and oracle independence;
9. feasible pinned driver/container/resources in the frozen verification
   environment; and
10. complete manifest/source/data/oracle/license/registration identities.

### 7.2 Exact set cover

Requirements sort by their canonical tuple. Eligible Harnesses sort by full
ID/version/manifest digest. The reviewed catalog is bounded at 64 compatible
candidates and 128 atoms; over-limit input is `catalog_resolution_limit`, not a
timing fallback.

The resolver performs deterministic branch-and-bound exact set cover and picks
the lexicographically minimum objective:

```text
(
  uncovered_atom_count,            # must be zero
  tier_strength_penalty,
  nondeterministic_scorer_count,
  non_independent_oracle_count,
  aggregate_resource_cost_tuple,
  harness_count,
  sorted_harness_id_version_digest_tuple
)
```

Status, compatibility, required methods, and feasibility are hard filters,
not rankable compromises. A suite that cannot cover every atom emits typed
`unsatisfied` and the exact uncovered atoms. It never chooses a weaker method,
tolerance, tier, or unverified Harness.

Identical Verification Contract, catalog snapshot, and environment yield a
byte-identical suite and lock.

## 8. Secure runner and fixed verifier

The runner reuses existing contracts:

1. trusted runtime resolves the candidate's current `ResearchArtifactRefV1`;
2. `WorkspaceRefV1` creates a closed immutable target snapshot, rejecting
   absolute paths, traversal, symlinks, devices, and digest mismatch;
3. the locked driver constructs `ExecutionRequestV1` with exact executable,
   container, inputs, resource/network/credential policies, and execution ID;
4. existing execution machinery enforces timeout, cancellation,
   process-group kill, logs, output artifacts, and substrate identity;
5. `ExecutionResultV1`/`ResultEnvelopeV1` are normalized by the locked driver;
6. fixed verifier validates result schema, target/source digests, property
   coverage, infrastructure status, and retry policy; and
7. trusted persistence atomically writes the immutable Attestation and audit
   record.

The fixed component receives no arbitrary checkpoint write capability. It
returns a value; a trusted facade writes the exact authorized path. Candidate,
oracle, and verifier use separate filesystem identities. Hidden inputs and
expected outputs are mounted only into the verifier. Network is deny by
default. A manifest requiring network must be permitted by the Verification
Contract and records exact endpoints/substrate limitations.

Duplicate execution identity is idempotent only when every request and target
digest matches. Any mismatch creates a new attempt or `tampered`; stale cached
results are never accepted.

A locked external driver may invoke an LLM scorer when its manifest declares
nondeterminism. The fixed verifier procedure itself still makes no LLM choice;
such a result is ineligible for deterministic artifact-correctness properties
and cannot substitute for native correctness gates.

## 9. Screen, validate, and certify

| Tier | Subjects | Required content | Effect |
|---|---|---|---|
| `screen` | every BFTS node | compile/interface, smoke, small differential, basic boundaries, cheap determinism | all required pass is scientific-frontier admission |
| `validate` | frontier promotion, parent improvement, final candidate set, or auxiliary request | property/metamorphic tests, sanitizers, seeds/repeats, environment consistency, stress/edges | required before parent retirement/best-node replacement |
| `certify` | final artifact, publication result, reproduction package | complete suite, isolated rerun, target digest, environment/container/oracle pins, publication evidence | hard prerequisite for final paper/finalize/publish |

Correctness is a feasibility constraint. Performance utility is read only
after required correctness passes. Code, measurements, or claims without the
required certify Attestation cannot be represented as a verified final result.

## 10. Native HPC artifact verifiers

The initial native suite is:

```text
hpc/gemm-correctness
hpc/spmm-correctness
hpc/stencil-correctness
```

All three accept a manifest-defined C ABI target adapter, build recipe, source
or shared-library artifact, language/toolchain identity, and immutable input
bundle. C, C++, OpenMP, and CUDA adapters are required where applicable;
Stencil also admits MPI through an explicit distributed target interface.
Reference and candidate receive byte-identical input bundles whose digests are
recorded.

### 10.1 GEMM

**Target interface.** `ari_gemm_v1` accepts a versioned descriptor containing
dtype, row/column layout, transpose flags, M/N/K, leading dimensions,
alpha/beta, input/output pointers, device/stream identity, and declared
in-place behavior. Adapters cover C/C++ serial, OpenMP, CUDA runtime/shared
library, and reject an ABI/layout mismatch before numerical scoring.

**Test generation.** A lock-pinned deterministic generator covers non-square
M/N/K; transpose combinations; padded/non-contiguous leading dimensions;
alpha/beta zero, one, negative, fractional; zero/one/small/prime/odd
dimensions; aligned and deliberately misaligned buffers; multiple OpenMP
thread counts; multiple CUDA blocks/streams when declared; repeated runs;
subnormal/normal/extreme finite values; and the declared NaN/Inf policy. Seeds
and generated input digests are locked.

**Oracle and error model.** Screen uses a pinned MPFR/high-precision scalar
reference on small cases. Validate/certify add a pinned trusted BLAS reference
on larger cases with MPFR-sampled cross-checks. Acceptance is elementwise
against a dtype/operation bound based on unit roundoff and accumulation length
(`gamma_K`) scaled by `|alpha| * sum(|A_ik B_kj|) + |beta C_ij|`, plus a
manifest-pinned absolute floor for underflow. It is not one fixed `rtol`.
NaN/Inf equivalence follows the explicit policy and never passes by generic
`isclose` behavior.

**Metamorphic properties.** zero-alpha/beta identity; linear scaling;
transpose equivalence; block decomposition; zero-padding invariance; and
repeated-execution determinism within the declared class.

**Safety and negative controls.** ASan/UBSan for CPU, compute-sanitizer for
CUDA, guard pages/canaries, input immutability, race/determinism repeats. Pinned
wrong implementations include ignored beta, wrong transpose, K-tail omission,
hard-coded shape, alignment assumption, in-place corruption, and parallel
race; every one must fail a named property.

**Evidence.** ABI/build logs, toolchain/container identity, generated case
manifest, input/output/oracle digests, per-element bound summary and worst
counterexample, sanitizer/race logs, timing separated from correctness, and
property results.

### 10.2 SpMM

**Target interface.** `ari_spmm_csr_v1` declares dtype/index width, matrix
dimensions, CSR row pointer/column/value arrays, RHS width/leading dimension,
alpha/beta, layout, device/stream, and output buffer. Duplicate column indices
and unsorted rows are valid and must be accumulated; malformed row pointers,
out-of-range columns, negative sizes, and incompatible buffers are explicit
invalid-input results, not crashes.

**Test generation.** Empty rows, all-empty/zero-nnz matrices, one-nnz rows,
duplicate indices, sorted/unsorted indices, highly irregular and long rows,
rectangular matrices, multiple RHS widths, diagonal/banded/block/random/power-
law patterns, zero values stored in CSR, index-width boundaries, thread/SIMD
configurations, alignment variants, and repeats.

**Oracle/error model.** A pinned serial reference canonicalizes no input and
accumulates each row/RHS in MPFR/high precision. The dtype bound depends on the
actual row accumulation length and absolute sparse products, with duplicate
terms included. Larger certify cases use a pinned trusted sparse library plus
sampled high-precision checks.

**Metamorphic properties.** row permutation with inverse output permutation;
column/RHS permutation; split-and-sum of disjoint nonzeros; duplicate coalescing
equivalence; zero-entry insertion; linearity; and representation-order
invariance.

**Safety and negative controls.** Sanitizers/canaries, read-only CSR inputs,
invalid-input corpus, multiple threads/SIMD, deterministic repeat policy.
Controls include skipping empty rows incorrectly, assuming sorted indices,
overwriting duplicates, RHS-width hard coding, tail loss, and race updates.

**Evidence.** CSR validation report, case/pattern/input digests, oracle and
candidate outputs, row-specific error bounds/counterexamples, invalid-input
status, sanitizer/determinism logs, and property results.

### 10.3 Stencil

**Target interface.** `ari_stencil_v1` declares dimensionality, non-cubic
extents, halo width, coefficients/radius, iteration count, dtype, periodic or
fixed boundary values, in-place/out-of-place mode, thread/grid/MPI topology,
and input/output buffers. The output domain and halo ownership are explicit.

**Test generation.** Zero/one/many iterations; domains smaller than, equal to,
and larger than the stencil radius; non-cubic and odd/prime extents; halo
variants; periodic and fixed boundaries; asymmetric coefficients; constant,
impulse, ramp, random, and extreme finite inputs; in/out-of-place adapters;
thread counts, CUDA decompositions, MPI partitions; and repeats.

**Oracle/error model.** A pinned serial high-precision reference retains the
complete trajectory for small cases. Larger validate/certify cases compare
checkpoints to a pinned trusted reference. Error bounds are dtype-,
coefficient-, neighborhood-, and iteration-dependent; a single final fixed
`rtol` is prohibited.

**Metamorphic properties.** constant-field invariance when coefficients permit;
linearity/superposition; periodic translation equivariance; fixed-boundary
preservation; one multi-iteration run versus chained single iterations;
domain decomposition/halo exchange equivalence; and in-place/out-of-place
equivalence when declared.

**Safety and negative controls.** Sanitizers/compute-sanitizer, halo canaries,
MPI rank consistency, race/repeat checks. Controls include wrong boundary,
missing halo exchange, one-iteration-only, off-by-one edge, in-place overwrite,
non-cubic indexing, and parallel race.

**Evidence.** interface/build logs, domain/topology/input/reference trajectory
digests, boundary/halo checks, per-iteration error summaries and first
counterexample, sanitizer/race/MPI logs, and property results.

## 11. External Harness drivers and initial catalog

Driver protocol methods are `identity`, `prepare`, `build_request`,
`normalize_result`, and `parity_probe`. They operate only from a frozen
manifest/lock/request and emit normalized typed results. They do not resolve a
Harness or mutate a contract.

The checked-in catalog entries are explicit:

```text
ari-core/config/harnesses/
├── catalog.yaml
└── builtin/
    ├── paperbench.yaml
    ├── scicode.yaml
    ├── core_bench.yaml
    ├── scienceagentbench.yaml
    ├── kernelbench.yaml
    ├── compute_eval.yaml
    ├── scbench.yaml
    ├── gemm_correctness.yaml
    ├── spmm_correctness.yaml
    └── stencil_correctness.yaml
```

| Driver | Initial entries | Definitive reuse |
|---|---|---|
| `paperbench` | `reproduction/paperbench` | existing `_paperbench_bridge.py` Stage 1 `rollout_submission`, Stage 2 `reproduce_submission`/`server.run_reproduce`, Stage 3 `judge_submission`/SimpleJudge; immutable container checks, reproduction record, grading snapshot, negative controls, and fail-loud substrate checks retained |
| `inspect` | `science/scicode`, `science/core-bench` | pinned official Inspect/Inspect Evals implementations; SciCode's recommended Inspect route and the official Inspect CORE-Bench task are invoked rather than translated into a new runner |
| `harbor` | `science/scienceagentbench` | pinned Harbor task/dataset runner and ScienceAgentBench dataset packaging; container/task/test identities recorded |
| `native` upstream wrapper | `gpu/kernelbench`, `gpu/compute-eval`, `bio/scbench` | each project's pinned official runner/CLI inside `ExecutionRequestV1`; KernelBench's upstream evaluator, NVIDIA ComputeEval's release/test/benchmark commands, and scBench's official runner remain authoritative |
| `native` ARI | `hpc/gemm-correctness`, `hpc/spmm-correctness`, `hpc/stencil-correctness` | §10 implementation |

PaperBench and CORE-Bench are `reproduction`. The three HPC entries are
`artifact_verifier`. SciCode, ScienceAgentBench, KernelBench, ComputeEval, and
scBench are initially `benchmark` with `accepts_external_target: false`; they
cannot gate an arbitrary BFTS node. The existing deterministic claim-evidence
hard gate is separately registered as `claim_verifier` and called directly by
trusted runtime, not through agent-selected `ari-skill-evaluator` invocation.

Every external entry begins `candidate` and becomes verified only after:

- official-runner output parity at the pinned commit;
- pinned dataset/release/model/oracle/driver/container digests;
- result-schema normalization parity;
- infrastructure-error separation;
- all implementation/data/model/container licenses;
- reproducible invocation record and upstream scorer drift sentinel;
- reference/oracle pass, clean control pass, and negative-control fail; and
- hidden-test isolation.

The external repositories and datasets are referenced by identity and fetched
during authenticated admin installation into a content-addressed cache. They
are not copied into the ARI source tree or fetched by a run resolver.

## 12. Registration and lifecycle

Human PR review or authenticated admin CLI is the only status writer. Verified
promotion requires:

1. reference/oracle pass;
2. wrong implementation negative-control fail;
3. clean-control pass;
4. official runner parity;
5. target/oracle/test isolation;
6. deterministic scorer or complete nondeterminism declaration;
7. infrastructure failure separation;
8. timeout/resource declaration and enforcement;
9. source/dataset/model/container license completeness;
10. source revisions and full digests;
11. candidate inability to read hidden tests;
12. multiple-run stability within declared limits;
13. normalized result schema conformance;
14. full SHA-256 integrity; and
15. malicious Harness sandbox fixture containment.

`HarnessRegistrationReportV1` records each gate and upstream parity metadata.
Candidate/deprecated/revoked entries never enter a new authoritative lock.
Revocation appends taint to historical attestations and does not alter them.

## 13. Failure semantics

| Result | Scientific/frontier effect | Governance effect |
|---|---|---|
| `pass` | requirement satisfied; may enter scientific frontier | none by itself |
| `fail` | excluded from scientific frontier, retained in debug | none for an ordinary attempt |
| `inconclusive` | uncertified; auxiliary verification may add methods | no penalty |
| `infrastructure_error` | uncertified; retry on locked compatible environment | no scientific failure and no penalty |
| `tampered` | target/lock/result invalidated | Kernel integrity finding and evidence for responsible concealment/substitution |

Retry identity and total budget are locked. A retry cannot switch Harness,
oracle, dataset, tolerance, driver, or container. It may use a pre-approved
equivalent verification environment already enumerated in the lock; otherwise
a next-epoch monotonic revision is required.

## 14. Planned files and persistence

```text
ari-core/ari/assurance/
├── __init__.py
├── models.py
├── catalog.py
├── resolver.py
├── lock.py
├── suite.py
├── runner.py
├── attestation.py
├── registration.py
└── drivers/
    ├── native.py
    ├── inspect.py
    ├── harbor.py
    └── paperbench.py

ari-core/ari/public/assurance.py
ari-core/ari/protocols/assurance.py
ari-core/config/harnesses/{catalog.yaml,builtin/*.yaml}
ari-core/ari/schemas/{verification_contract_v1,harness_manifest_v1,
    harness_catalog_snapshot_v1,harness_lock_v1,
    harness_lock_revision_v1,harness_run_request_v1,
    harness_attestation_v1}.schema.json
```

Checkpoint artifacts use the exact paths in Task 16 §13 and are registered as
internal metadata in `PathManager`; they cannot be inherited into candidate
workspaces. Existing execution logs/artifact refs remain in the existing
execution store and are referenced rather than copied.

## 15. Tests

### Contract/resolver/runner tests

- `test_verification_contract_is_mint_once_and_full_sha256`
- `test_skill_obligation_union_only_strengthens_contract`
- `test_evaluator_harness_hint_is_excluded_from_resolution_input`
- `test_benchmark_cannot_cover_arbitrary_artifact_requirement`
- `test_harness_exact_set_cover_is_byte_deterministic`
- `test_unsatisfied_coverage_never_falls_back_to_weaker_harness`
- `test_baseline_lock_is_immutable_and_revision_is_monotonic`
- `test_tier_downgrade_tolerance_relaxation_and_identity_swap_rejected`
- `test_runner_isolates_target_oracle_hidden_tests_and_checkpoint`
- `test_attestation_binds_current_target_and_every_source_digest`
- `test_fail_inconclusive_infrastructure_and_tampered_are_distinct`
- `test_retry_is_idempotent_and_cannot_reuse_stale_result`
- `test_revocation_taints_without_rewriting_attestation`

### Native verifier tests

- reference passes and every named negative control fails for GEMM, SpMM, and
  Stencil;
- all target adapters and ABI mismatch behavior;
- deterministic generation for every case/seed manifest;
- dtype/accumulation/iteration-aware error bounds;
- metamorphic properties, multiple shapes/patterns/boundaries/threads/repeats;
- ASan/UBSan/compute-sanitizer/race and invalid-input policies; and
- exact input identity between reference and candidate.

### External driver tests

- pinned official runner parity for Inspect/SciCode, Inspect/CORE-Bench,
  Harbor/ScienceAgentBench, KernelBench, ComputeEval, scBench, and PaperBench;
- upstream scorer/schema drift rejection;
- clean/reference pass, negative control fail, hidden-test isolation;
- mutable tag/branch/container rejection and license completeness;
- infrastructure failures normalize separately; and
- PaperBench uses the current bridge and refuses any local fallback or skipped
  negative control for verified registration.

### 15.1 Implementation evidence checkpoint (2026-08-04)

- `ExternalHarnessParityReportV1` now makes official invocation/result and
  normalized-result digests, reference pass, negative-control fail, schema
  parity, and source/dataset/container/driver pins jointly mandatory for a
  `passed` report. Partial compatibility and forged report digests fail closed.
- PaperBench upstream API identity and deterministic score aggregation passed
  against vendored commit `51052cede8cc608f95bb00346635e03759013e5a`;
  reference score was 1.0 and the negative control score was 0.0. The
  compatibility report digest is
  `sha256:828f7e3819bdbc552d822a8705a667fb0ea00d2283dfddc61e4a4b662a4cda1e`.
- That result is explicitly not official-runner parity. The pinned PaperBench
  dataset/container, scoped rollout/judge credentials, end-to-end official
  invocation, and reference/wrong-submission normalized-result comparison were
  unavailable. Inspect and Harbor executables were also unavailable; Docker's
  client existed but its daemon was inaccessible, while Apptainer had no
  reviewed pinned SIF for these Harnesses.
- Native GEMM, SpMM, and Stencil reference/negative-control families passed in
  a real anonymous-node CPU SLURM job. They remain candidate, as requested: the result is
  not a substitute for a pinned isolated Harness container and promotion
  report.

### 15.2 Correctness-family registry checkpoint (2026-08-07)

- A correctness family now declares itself once, in
  `ari/assurance/native_hpc_family.py`, and supplies three things: the hidden
  cases and the oracle that judges them (`verify`), the independent `reference`
  implementation that is also the parity probe's clean control, and the ctypes
  ABI its candidates are called through. The set of verifiable kernels used to
  be written out in five places — a `Literal`, the facade's dispatch dict, the
  parity probe's reference table, the ABI dispatch dict, and two argparse
  `choices` tuples — so a family added to four of them was dispatchable, scored,
  and attested while the probe never touched it, and the probe still reported
  `passed`.
- `NativeKind` is now `str` rather than a closed `Literal`; the name still
  appears in a report because a verdict has to say what it verified. ABI
  adapters self-register through a decorator and the candidate host accepts
  `abi_adapter_kinds()`; the worker validates `--kind` against
  `registered_native_families()`; the parity probe iterates the registry instead
  of a table. Registering one name twice is refused, so no import order can
  decide which oracle judged a run.
- `native_hpc_family.py` joins the native driver digest, because the registry
  decides which oracle judges a run. That digest now also raises when one of its
  files is absent instead of letting it drop out silently.
- This does not make correctness families free the way pinned problems are.
  Adding one is still an ARI change, reviewed like any other, because an oracle
  a caller could supply is an oracle a caller could weaken. What changed is that
  the set is declared in one place per family instead of five places per set.
- **The cost, and it is real.** The native driver digest changed, so all three
  correctness harnesses — `hpc/gemm-correctness`, `hpc/spmm-correctness`, and
  `hpc/stencil-correctness` — now refuse to run with `native Harness driver
  bytes drifted`. Their manifests were **not** re-pinned: a signature covers
  what was signed, and re-pinning would make three human-maintainer attestations
  describe code nobody approved. They need re-attestation, and both the refusal
  and the absence of a re-pin are asserted by a test so neither can be undone by
  accident.

## 16. Completion criteria

Task 18 is complete when:

1. contracts, catalog, exact resolver, locks, secure runner, and Attestations
   are implemented independently of RQGM;
2. no actor-supplied Harness ID can bypass deterministic resolution;
3. all required coverage is exact and full or admission is `unsatisfied`;
4. target/oracle/dataset/driver/container/result identities are immutable;
5. native HPC verifiers meet the full §10 matrix and controls;
6. every external driver has pinned official parity and no placeholder path;
7. PaperBench is reused, not reimplemented;
8. claim verification remains separate from program correctness; and
9. Task 20 criteria 30–58 and 60–62, 64–68 pass.

## 17. Deletion criteria

This plan is **not deletable** until implementation and all native/external
parity suites are merged and green, permanent Harness format/security/driver
extension documentation exists, pinned licenses and registration reports are
retained, Task 19/20 no longer depend solely on this file, and INDEX records
the deletion.

## 18. Delete-after checklist

- [ ] Completion criteria and owned acceptance tests pass.
- [ ] Native GEMM/SpMM/Stencil references and negative controls retained.
- [ ] External official-runner parity reports retained for every verified entry.
- [ ] Security/isolation/resume/revocation tests pass on released fixtures.
- [ ] Permanent assurance and Harness extension docs published.
- [ ] INDEX updated in the deletion change.
