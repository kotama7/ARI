# Task 16: Knowledge Skill Registry and Separation Foundation

> **Status**: in progress · **Depends on**: 00–15 · **Implementation checkpoint**:
> 2026-08-05 · **This is a temporary task plan** — see [INDEX.md](INDEX.md).
> Internal contracts, catalogs, deterministic admission/composition, immutable
> run artifacts, pinned Git/Open Agent Skills/ToolUniverse Knowledge import
> adapters, compatibility surfaces, schemas, and tests have landed. Three
> separately pinned Intel performance Knowledge Skills are registered as
> candidates through self-contained external import materials; no Provider or
> Harness was activated. Final
> completion remains coupled to Tasks 17–20's external parity and 68-criterion
> evidence gate; this Task is not being reported complete early.

> **Initiative sequence.** The canonical ARI-RQGM plan is a flat numbered task
> sequence, not a parent/child plan system. The initiative **ARI
> Knowledge–Capability–Assurance Separation** is therefore represented by the
> consecutive Tasks 16–20: this foundation and Knowledge Skill Registry;
> Task 17 Capability Provider semantics and binding; Task 18 Scientific
> Assurance and Harness Registry; Task 19 RQGM governance integration; and
> Task 20 meta-evaluation. These files extend this indexed plan set and are not
> a second master plan.

## 1. Problem statement

ARI currently uses the word “Skill” for an executable MCP server package. That
name conflates three different objects that require different trust,
reproducibility, and authority rules:

1. procedural knowledge that tells an agent what to do and why;
2. an execution provider that exposes operations; and
3. an independent verifier that determines whether an artifact or claim meets
   a declared property.

The conflation is not merely editorial. On the RQGM branch today:

| Current implementation | Actual semantics | Consequence |
|---|---|---|
| `SkillManifestV1` and each `ari-skill-*/skill.yaml` | executable MCP Capability Provider manifest: entrypoint, tool schemas, permissions, credentials, timeouts, and side effects | It cannot also be the manifest for non-executable procedural knowledge. |
| `SkillConfig` | Capability Provider runtime configuration | Public terminology masks the authority being configured. |
| `SkillConnection` | local stdio MCP Provider connection | MCP transport is mislabeled as a Skill. |
| `SKILLS.lock` / `SkillsLockV1` | immutable Provider and live `tools/list` schema snapshot | It already is the Provider Lock and must not be reimplemented. |
| `default_tool_policy` | tool-name substring inference; an unknown name returns `None` and is dispatched as ungoverned | RQGM does not fail closed on unknown execution authority. |
| `MCPClient.to_claude_mcp_config` | delegates provider configuration and the visible tool allowlist to CLI agents | Binding enforcement must cover both in-process calls and delegated CLI calls. |
| `enrich_hints_from_mcp` | copies live MCP descriptions and signatures into the agent task prompt | Provider-authored text currently enters instruction context and must become untrusted data. |
| `RQGMRuntime.ensure_epoch` | founding registration and immediate `epoch_000` open | The first execution epoch is frozen before the Research Contract and the new locks exist. |
| Evidence Clerk map | maps `node_report` to `fixed_verifier_result` | Execution provenance is being mislabeled as program-correctness evidence. |
| `ari.rqgm.evaluation` and `scripts/rqgm_eval` | B0–B8 meta-evaluation, failure injection, detection, and cost measurement | Production Knowledge, Binding, and Assurance runtime must not be placed there. |

The branch already contains a provider federation asset:
`ari-skill-tool-registry` pins ToolUniverse and other sources in
`CATALOG.lock`, performs discovery/admission, and dispatches through a small
MCP broker surface. Tasks 16–20 reuse that asset. They do not create a second
ToolUniverse client, MCP client, or scientific-tool catalog.

The formal correction is:

```text
Knowledge Skill        = non-executable procedural knowledge
Capability Provider    = executable authority and operations
Harness                = independent verification definition and driver
RQGM                    = governance over actors' use of authority and evidence
Task 13                 = evaluation of those mechanisms, never their runtime
```

## 2. Scope

This initiative specifies the future implementation of:

- `ARI Knowledge Skill Registry`, including immutable packages, imports,
  catalog snapshots, deterministic selection/admission, epoch locks, node use,
  prompt composition, provenance, lifecycle, and revocation taint;
- the shared contract foundation consumed by Task 17's `ARI Capability
  Provider Federation` and deterministic Capability Binder;
- the shared contract foundation consumed by Task 18's `ARI Harness Registry`
  and `Scientific Assurance` runtime;
- Task 19's fixed-role, run-admission, BFTS, Evidence Clerk, adversarial,
  frontier, publication, CLI/MCP/UI, and constitutional integration; and
- Task 20's orthogonal extension of Task 13 evaluation.

The implementation sequence is Wave A through Wave L in §25. No wave is
complete with a pass-through stub, an empty driver, a constant-pass verifier,
an unreviewed placeholder, or a TODO-only adapter.

## 3. Non-goals

- Do not treat Knowledge Skill text as an execution runtime.
- Do not replace MCP with a Knowledge Skill format.
- Do not reimplement ToolUniverse inside ARI.
- Do not execute scripts, notebooks, or binaries merely because they arrived
  in an external Skill repository.
- Do not destructively rename every existing `ari-skill-*` package.
- Do not use Knowledge Skill selection as Harness selection.
- Do not treat a successful Provider response as correctness proof.
- Do not treat Harness pass as general or mathematical correctness outside
  its declared scope.
- Do not register each Knowledge Skill, Provider, tool, or Harness as an RQGM
  Component.
- Do not put Task 20 `eval_*` fixtures in production catalogs or replay pools.
- Do not implement production runtime under `ari.rqgm.evaluation`.
- Do not add `provider.yaml` or `PROVIDERS.lock` during Tasks 16–20.
- Do not change `MetricCorrectnessV1` to carry a Harness ID.
- Do not implement code, config, schemas, tests, or permanent documentation as
  part of writing this plan.

## 4. Terminology correction

The following terms are normative throughout Tasks 16–20.

**Knowledge Skill**
: Content-addressed, non-executable procedural knowledge describing what to
  do, why, when, in which order, and under which decision principles.

**Capability**
: A versioned semantic execution ability such as
  `ari.execution.compile/v1` or `ari.literature.search/v1`.

**Capability Provider**
: An executable subject that provides one or more Capabilities, for example
  ToolUniverse, an external MCP server, `ari-skill-coding`, a SLURM adapter, a
  local process adapter, a robot arm, a sensor, or a laboratory API.

**MCP**
: A transport and discovery protocol used to connect to a Capability
  Provider. MCP is not a Skill.

**Tool**
: An atomic operation published by a Provider.

**Capability Binding**
: The deterministic fixation of a Knowledge Skill or Research Contract's
  semantic `capability_ref` to a concrete, run-available `tool_ref`.

**Harness**
: An independent evaluation substrate that verifies a declared property of
  an artifact or claim.

**RQGM**
: The institution that governs how Skill, Provider, Evaluator, Reviewer, and
  other actors generated, used, ignored, or distorted authority and evidence.

The boundaries are strict:

```text
Knowledge Skill != Capability Provider
Capability Provider != Harness
Harness != Evaluator
MCP != Skill
Tool description != procedural knowledge
Skill instruction != executable authority
```

The compatibility vocabulary is fixed as follows:

| Legacy public name | Canonical product name | Task 16–20 compatibility |
|---|---|---|
| Skill package / `ari-skill-*` | Capability Provider package | On-disk/package name retained; UI and new docs say Capability Provider. |
| `SkillManifestV1` | `CapabilityProviderManifest` | Same Python class object and schema; new canonical re-export, old name deprecated. |
| `SkillConfig` | `CapabilityProviderConfig` | Same Python class object; old name deprecated. |
| `SkillConnection` | `MCPProviderConnection` | Same implementation; no second transport. |
| `SKILLS.lock` / `SkillsLockV1` | Provider Lock / `ProviderLock` | Existing bytes and resume rules remain canonical. |

## 5. Architectural decision

The authoritative flow is:

```text
User Goal / Root Proposal
        ↓
Research Contract
        ↓
Knowledge Skill Selection Proposal
        ↓
Fixed Knowledge Admission / Composition
        ↓
Knowledge Skill Lock
        ↓
Capability Requirements
        ↓
Fixed Capability Binder
        ↓
Capability Binding Lock
        ↓
Verification Contract
        ↓
Fixed Harness Resolver
        ↓
Harness Lock
        ↓
First Execution Epoch Freeze
        ↓
Agent Execution through Bound Providers
        ↓
Artifact-bound Harness Attestation
        ↓
Scientific Frontier Gate
        ↓
Evidence Clerk
        ↓
Adversarial / Governance Review
        ↓
Certification-bound Publication
```

The three surfaces are separately computed:

```text
InstructionSet
=
BasePrompt
⊕ SelectedKnowledgeSkills

ExecutableSurface
=
Bind(
    RequiredCapabilities,
    ProviderSnapshot,
    RoleAuthority,
    Phase,
    Environment
)

VerificationSurface
=
Resolve(
    VerificationContract,
    HarnessCatalogSnapshot,
    VerificationEnvironment
)
```

Four constitutional invariants follow:

1. A Knowledge Skill may request execution ability but cannot grant it.
2. A Capability Provider may supply ability but cannot determine the research
   procedure or authoritative Harness selection.
3. An Evaluator may propose verification properties but cannot determine the
   authoritative Harness ID.
4. A Harness may issue verdicts within its declared scope but cannot mutate a
   frontier, catalog, registry, contract, or lock.

Relationship to existing design:

| Layer | Question answered |
|---|---|
| ARI Knowledge Skill Registry | What does the scientific agent know, and which procedures and decision principles does it follow? |
| ToolUniverse / MCP Capability Providers | What can the agent actually execute? |
| Capability Binding | Which concrete Provider tool supplies each semantic requirement for this run? |
| ARI Harness Registry | Which fixed verifier can cover each declared property? |
| RQGM | Who used, ignored, concealed, or distorted evidence or authority, and which institutional transition follows? |
| Task 13 / Task 20 | Does Knowledge selection, Provider binding, Harness verification, and governance detect controlled failures at acceptable cost? |

## 6. Layer and dependency boundaries

The future source layout is fixed:

```text
ari-core/ari/knowledge/
    models.py catalog.py importer.py resolver.py composition.py
    lock.py provenance.py registration.py
ari-core/ari/providers/
    models.py compatibility.py catalog.py registration.py
ari-core/ari/capability_binding/
    ontology.py models.py resolver.py lock.py validation.py
ari-core/ari/assurance/
    models.py catalog.py resolver.py lock.py suite.py runner.py
    attestation.py registration.py
    drivers/{native,inspect,harbor,paperbench}.py
ari-core/ari/public/
    knowledge.py providers.py capability_binding.py assurance.py
ari-core/ari/protocols/
    scientific_requirements.py provider.py assurance.py
ari-core/ari/rqgm/
    knowledge_bridge.py assurance_bridge.py
```

Configuration and schemas are:

```text
ari-core/config/knowledge_skills/{catalog.yaml,builtin/*.yaml}
ari-core/config/providers/{catalog.yaml,builtin/*.yaml}
ari-core/config/capabilities/{ontology.yaml,builtin/*.yaml}
ari-core/config/harnesses/{catalog.yaml,builtin/*.yaml}
ari-core/ari/schemas/knowledge_skill_manifest_v1.schema.json
ari-core/ari/schemas/knowledge_skill_catalog_snapshot_v1.schema.json
ari-core/ari/schemas/epoch_knowledge_skill_lock_v1.schema.json
ari-core/ari/schemas/node_knowledge_skill_use_v1.schema.json
ari-core/ari/schemas/capability_contract_v1.schema.json
ari-core/ari/schemas/capability_binding_lock_v1.schema.json
ari-core/ari/schemas/verification_contract_v1.schema.json
ari-core/ari/schemas/harness_manifest_v1.schema.json
ari-core/ari/schemas/harness_catalog_snapshot_v1.schema.json
ari-core/ari/schemas/harness_lock_v1.schema.json
ari-core/ari/schemas/harness_lock_revision_v1.schema.json
ari-core/ari/schemas/harness_run_request_v1.schema.json
ari-core/ari/schemas/harness_attestation_v1.schema.json
```

Two default-off compatibility Provider packages expose only agent-facing read
and request surfaces:

```text
ari-skill-knowledge/   # search/describe/list/request; never catalog admin
ari-skill-harness/     # search/describe/request/read; never resolve/run/admin
```

They retain `skill.yaml` because that filename is the v1 Provider wire format.
Authoritative admission, binding, resolution, and verification remain inside
the trusted ARI runtime.

The allowed dependency direction is:

```text
ari.rqgm.knowledge_bridge
        ↓
ari.knowledge
        ↓
ari.capability_binding
        ↓
ari.providers / ari.mcp

ari.rqgm.assurance_bridge
        ↓
ari.assurance
```

The following imports are forbidden and receive architecture tests:

```text
ari.knowledge -> ari.rqgm
ari.assurance -> ari.rqgm
ari.providers -> ari.knowledge
ari.providers -> ari.assurance
ari.mcp -> ari.knowledge
ari.assurance -> ari.capability_binding
```

Shared digest/reference/protocol types live in `ari.protocols` or existing
`ari.public` contracts. New contracts reuse `research_contract.canonical_digest`
and its canonical JSON/full SHA-256 convention; they do not add another hash
algorithm. Harness execution reuses `WorkspaceRefV1`, `ExecutionRequestV1`,
`ExecutionResultV1`, `ResultEnvelopeV1`, `ResearchArtifactRefV1`, call context,
credential scopes, typed errors, and checkpoint-resume primitives.

Cross-layer orchestration lives in `ari.core`/`RQGMRuntime`: the two RQGM
bridges never import each other, and Knowledge/Binding/Assurance exchange only
digest-bound values defined in common protocols. This preserves every
forbidden dependency even when Skill obligations feed Verification admission.

## 7. Authority separation

Task 19 owns the complete capability matrix. The architectural allocation is
already closed here:

| Actor | May | Must never |
|---|---|---|
| Generator | request another Skill/capability/debug verification; read attestations; invoke bound tools | promote or edit a Skill/Provider/Harness; edit locks; invoke unbound tools; change tolerance/oracle/data/driver/container; suppress fail |
| Router | emit `KnowledgeSkillSelectionProposalV1` and reasons | activate Skills, bind tools, select Harnesses, expand authority, write catalogs |
| `knowledge_binder_v1` / fixed | pure admission over proposal, contract, environment, and frozen catalog | LLM, network, clock, catalog/registry/frontier write, Provider launch, Harness selection |
| `capability_binder_v1` / fixed | pure binding over requirements, ontology, Provider Lock, authority, and environment | Provider registration/execution mutation, schema/credential expansion, Skill edit, Harness selection, registry/frontier write |
| Evaluator / Reviewer | propose properties and auxiliary verification; interpret admitted attestations | choose the authoritative Harness, weaken requirements/tier/tolerance, override verdict, certify a failed artifact |
| `harness_resolver_v1` / fixed | pure deterministic resolution over frozen contracts/catalog/environment | LLM, network, clock, contract/catalog/target/frontier write |
| existing `fixed_verifier_v1` / fixed | execute the locked Harness on an immutable target and emit an attestation | select a Harness, edit a lock/catalog/oracle/target/frontier, judge paper-claim meaning |
| Human/catalog maintainer | authenticated register/promote/deprecate/revoke operations | expose admin operations to research nodes or LLM MCP surfaces |

The existing `fixed_verifier` role is reused; Task 18 adds scientific
verification responsibility to that identity rather than creating a second
fixed verifier.

## 8. Threat model

### 8.1 Knowledge Skill threats

- prompt injection and privilege-escalation instructions;
- hidden executable content or a `SKILL.md`-to-script launch path;
- mutable branch, tag, `latest`, body substitution, or stale lock reuse;
- malicious references, path traversal, and symlink escape;
- conflicting Skill composition;
- instructions to omit verification, choose a favored Provider, obtain a
  secret, write a registry, or weaken policy.

### 8.2 Capability Provider threats

- tool-description injection;
- capability squatting or semantic mislabeling;
- live schema drift, Provider substitution, or mutable upstream packages;
- credential-scope expansion and side-effect misclassification;
- unbound invocation, bare-name collision, and tool-name substring inference;
- compromised external providers;
- one Provider attempting to supply both instruction and execution authority.

### 8.3 Harness threats

- Generator self-grading or Evaluator Harness shopping;
- tolerance gaming, oracle poisoning, target substitution, stale attestation;
- hidden-test leakage, malicious Harness code, or compromised container;
- environment/scorer drift and catalog revocation;
- evidence suppression or verifier-result override;
- repeated false acceptance or infrastructure failure mislabeled as failure;
- misuse of a benchmark as an arbitrary-artifact verifier.

### 8.4 Cross-layer threats

- a Skill expanding Provider authority or directly selecting a Harness;
- a Provider injecting Skill text or issuing its own Attestation;
- an Evaluator selecting a favorable Skill, Provider, and Harness together;
- mixed stale/new provenance such as old Skill + new Provider + old
  Attestation;
- partial-digest target substitution;
- same-component collusion across instruction, execution, and verification.

## 9. Global invariants

1. All trust anchors are full `sha256:<64 lowercase hex>` digests. Existing
   RQGM `hash12` identifiers remain compatibility/display keys only.
2. Manifests, snapshots, contracts, locks, and attestations use canonical JSON,
   are frozen/mint-once, and reject digest mismatch.
3. A Knowledge Skill contains no executable entrypoint and receives no secret,
   credential, environment, arbitrary file, or network access.
4. An imported script/notebook/binary remains a non-executable attachment
   until separately registered as a Provider, Harness Driver, or trusted
   build-time importer.
5. `SKILL.md` can request only semantic capabilities. Concrete tool names are
   non-authoritative hints and never participate in binding.
6. Catalog writers are authenticated humans/admin CLI. LLMs, Generator,
   Router, Evaluator, and Reviewer have no write surface.
7. `active` is lock membership, not a mutable catalog status.
8. No run fetches a mutable Skill, Provider, Harness, dataset, oracle, driver,
   model, or container after admission.
9. The first scientific node cannot execute until every required baseline
   snapshot, contract, lock, and verification-environment identity exists.
10. Node execution freezes Knowledge use, binding, and Harness revision for the
    node; changes become append-only next-epoch revisions.
11. Resume reconstructs persisted snapshots and locks and never re-resolves
    against current catalogs.
12. Knowledge obligations can only add Verification requirements; they cannot
    weaken or remove existing requirements.
13. Capability visibility is the intersection of Provider Lock, active Binding
    Lock, role, phase, call context, and user-disabled-tool complement.
14. RQGM binding enforcement fails closed on unknown capability, Provider,
    schema, side effect, credential scope, tool ref, or missing lock.
15. Harness lock revisions are monotonic; baseline bytes never change.
16. Attestation target digest must equal the current candidate artifact digest.
17. A failed candidate is a scientific result, not automatically a
    constitutional offense; concealment or misrepresentation is governance
    evidence.
18. `benchmark`, `artifact_verifier`, `reproduction`, and `claim_verifier` are
    disjoint typed Harness kinds.
19. Provider success is not Attestation, Knowledge self-report is not
    correctness evidence, and claim consistency is not program correctness.
20. With `simple_bfts` and all new features at compatibility defaults, no new
    import, file, metric, field, snapshot, lock, prompt byte, or visible tool
    occurs.

## 10. Knowledge Skill data model

### 10.1 Package and manifest

The canonical package is:

```text
knowledge-skills/<skill-id>/
├── SKILL.md
├── skill.meta.yaml
└── references/
```

`SKILL.md` supports the required sections `When to use`, `Preconditions`,
`Procedure`, `Decision points`, `Failure conditions`, `Expected artifacts`,
`Scientific cautions`, and `Evaluation obligations`.

`skill.meta.yaml` is represented by `KnowledgeSkillManifestV1` and contains:

```yaml
schema_version: 1
id: hpc.gemm.optimization
version: 1.0.0
title: GEMM Optimization
description: Dense GEMMを正当性を維持しながら最適化する手続き知識
status: verified
source:
  repository: <pinned repository URL>
  commit: <full commit SHA>
  path: knowledge-skills/hpc.gemm.optimization
  body_sha256: <full SHA-256>
  manifest_sha256: <full SHA-256>
license:
  body: Apache-2.0
  references: CC-BY-4.0
references:
  - path: references/error-model.md
    sha256: <full SHA-256>
applies_to:
  roles: [generator]
  phases: [bfts]
  task_tags: [gemm, dense-linear-algebra]
requires:
  capabilities:
    - {ref: ari.code.inspect/v1, required: true}
    - {ref: ari.code.edit/v1, required: true}
    - {ref: ari.execution.compile/v1, required: true}
    - {ref: ari.execution.benchmark/v1, required: true}
optional_capabilities:
  - {ref: ari.profiling.hardware-counters/v1}
  - {ref: ari.execution.slurm-submit/v1}
evaluation_obligations:
  - property_id: numerical-equivalence
    required_methods: [differential-testing]
  - {property_id: performance-regression}
  - {property_id: reproducibility}
authority_ceiling:
  side_effects: [read-only, workspace-write]
forbidden_capabilities:
  - ari.registry.write/v1
  - ari.publish.external/v1
dependencies: []
conflicts: []
composition: {slot: domain-method, priority: 100}
```

The schema rejects `entrypoint`, `transport`, `command`, `required_env`,
`credential_scope`, executable tool declarations, server processes, and
container launch commands. It also rejects absolute reference paths, `..`,
symlinks, device files, sockets, and references whose full digest is absent.

The body must not authoritatively say “call `run_bash`”, “use ToolUniverse X”,
“invoke function Y”, or “execute this Python entrypoint”. It may say “use a
compile capability” or “use literature search”. A concrete tool example is
stored as `non_authoritative_hint` in the import report and excluded from all
resolution inputs. An authoritative `harness_id` field is rejected; a Harness
name mentioned in body prose is likewise retained only as a non-authoritative
hint and is excluded from Harness Resolver inputs.

### 10.2 Required types

| Type | Core fields and producer | Consumer / persistent artifact |
|---|---|---|
| `KnowledgeSkillManifestV1` | immutable package metadata, source/full commit, body/manifest/reference digests, licenses, applicability, requirements, obligations, authority, dependency/conflict/composition; importer/admin | catalog and binder; Git catalog entry plus content-addressed body store |
| `KnowledgeSkillCatalogSnapshotV1` | ordered verified/candidate/deprecated/revoked entries with entry digests, catalog source revision, importer version, snapshot digest; run admission | binder/resume; `knowledge/catalog_snapshot.json` |
| `KnowledgeSkillSelectionProposalV1` | run/epoch, Research Contract digest, proposed exact IDs/versions/digests, node/epoch scope, reason, Router identity/prompt; Router | fixed binder; append-only proposal record |
| `EpochKnowledgeSkillLockV1` | catalog/proposal/contract digests, admitted ordered entries, requirement and obligation unions, rejected/unsatisfied reasons, lock digest; fixed binder | composer/binding/admission; `knowledge/locks/epoch_<n>.json` |
| `NodeKnowledgeSkillUseV1` | node/epoch, lock digest, exact subset/order/body digests, composition digest; trusted runtime before node start | composer/Evidence Clerk; `knowledge/node_use/<node_id>.json` |
| `KnowledgeSkillUseRecordV1` | actual instruction identity, status-at-use, component/prompt/epoch, binding/verification/Harness digests, revocation taint fields; composer after rendering | audit/adversarial/resume; append-only record |
| `KnowledgeSkillRegistrationReportV1` | schema/integrity/license/authority/path/boundary/clean-task/portability results and status decision; admin validator | human promotion; registration report artifact |
| `CapabilityRequirementV1` | canonical capability ref, required flag, semantic constraints, context, side-effect ceiling, forbidden refs, provenance source; Research Contract or Skill | Task 17 binder; common type in `ari.capability_binding.models` |
| `EvaluationObligationV1` | property ID, methods, tier floor, scope, Skill provenance; Skill importer | Verification Contract union; common type in `ari.protocols.scientific_requirements` |

### 10.3 Catalog and import

The built-in catalog is Git-reviewed at
`ari-core/config/knowledge_skills/`:

```text
ari-core/config/knowledge_skills/
├── catalog.yaml
├── builtin/
│   ├── hpc_gemm_optimization.yaml
│   ├── hpc_spmm_optimization.yaml
│   ├── hpc_stencil_optimization.yaml
│   ├── literature_systematic_review.yaml
│   └── scientific_reproduction.yaml
├── import_profiles/
│   ├── intel_linux_perf.yaml
│   ├── intel_performance_patterns.yaml
│   └── intel_phoronix_test_suite.yaml
└── imports/
    ├── intel_linux_perf.json
    ├── intel_performance_patterns.json
    └── intel_phoronix_test_suite.json
```

Registration begins as `candidate`; promotion to `verified` requires all of:

1. manifest schema validity;
2. full SHA-256 integrity;
3. full source commit pin;
4. complete body/reference licenses;
5. no executable entrypoint/transport/command;
6. no automatic script/notebook/binary launch path;
7. every capability ref in the frozen ontology;
8. no forbidden authority request;
9. explicit authority ceiling;
10. every evaluation obligation in the property vocabulary;
11. reference path/symlink isolation;
12. prompt-composition schema conformance;
13. body-size and required-section policy;
14. hostile-instruction boundary fixtures;
15. successful use on at least one clean task; and
16. portability across at least two verified Providers whenever the frozen
    Provider catalog contains two compatible candidates. If it contains fewer,
    the report records `not_applicable_no_second_provider`; it cannot claim a
    portability pass.

Import adapters are limited to:

- a closed local directory;
- Git repository + full commit SHA + subpath;
- Open Agent Skills-compatible layout;
- ToolUniverse Knowledge Skill collections; and
- explicitly configured scientific Skill repositories using the same Git
  adapter.

The admin/import operation downloads into a temporary closed workspace,
resolves a full commit, copies only manifest/body/references as knowledge
artifacts, validates licenses and paths, hashes every byte, records importer
version, and then creates a candidate registration PR/report. Runtime never
reads a branch, tag, or `latest`.

Open Agent packages that do not use ARI's eight required section headings are
not silently weakened. The admin profile must explicitly select
`ari-wrapper-v1`; that deterministic adapter quotes every upstream line inside
fixed ARI precondition, authority, failure, artifact, caution, and evaluation
sections. The self-contained import material is the single checked-in source
for the normalized body and manifest and separately binds the original
`SKILL.md`, exact tree, references, attachment modes, and admin profile.

The initial real import pins `intel/intel-performance-skills` at full commit
`e9d0b6410fb1ad7a50fb81e0868fd23ae886882c` and registers
`intel.performance-patterns`, `intel.linux-perf`, and
`intel.phoronix-test-suite` independently as `candidate`. Host `sudo`/sysctl,
mutable PTS download/install, home or `/var/lib` writes, concrete tool names,
cross-Skill invocation text, and bundled code/scripts grant no authority. The
executable mutex benchmark script is retained only as a digest-bound
`authority: none` attachment. These entries require separate clean-task,
portability, and human promotion evidence before a verified epoch lock can
admit them.

ToolUniverse's Provider identity and Knowledge collection identity are
different URIs and digests. Registering or enabling one never enables the
other.

Catalog status is exactly `candidate | verified | deprecated | revoked`.
`active` is derived from a lock. `quarantined` is a registration finding, not
a catalog state. A legacy imported `retired` label normalizes once to
`deprecated`; no new record emits `retired`. Allowed transitions are
`candidate→verified`, `candidate|verified→deprecated|revoked`, and
`deprecated→revoked`; `revoked` is terminal. Body changes mint a new version
and digest and never overwrite an entry.

`GovernedKnowledgeSkillRegistry`, `KnowledgeSkillEntry`,
`KnowledgeSkillStatusTransition`, and `KnowledgeSkillBodyStore` reuse the
Prompt Registry's append-only transition, immutable body, epoch-frozen view,
provenance, selective invalidation, and resume reconstruction patterns but use
a separate namespace/schema. Knowledge content is not a PromptSpec and is not
stored in the Prompt Registry.

## 11. Provider and Capability data model

Task 17 is normative. This task fixes its boundary:

- `CapabilityProviderManifest`, `CapabilityProviderConfig`,
  `MCPProviderConnection`, and `ProviderLock` are semantic aliases/facades over
  `SkillManifestV1`, `SkillConfig`, `SkillConnection`, and `SkillsLockV1`.
- `CapabilityProviderIdentity` and `ProviderCatalogSnapshotV1` are derived,
  digest-bound views over manifests, existing `SKILLS.lock`, reviewed Provider
  status metadata, and nested federation locks. They are not a second launch
  manifest or tool-schema source of truth.
- `CapabilityContractV1`, `CapabilityProvisionV1`,
  `CapabilityOntologySnapshotV1`, `CapabilityBindingRequestV1`,
  `CapabilityBindingV1`, `CapabilityBindingLockV1`,
  `CapabilityBindingRevisionV1`, and `CapabilityBindingReportV1` provide the
  semantic layer absent from today's name-based tool registry.
- Existing unversioned tags are normalized only by a reviewed explicit alias
  table. Unknown tags never receive fuzzy, substring, or automatic `/v1`
  mapping.
- ToolUniverse leaf bindings carry both the nested `subject_tool_ref` from
  `CATALOG.lock` and the outer broker `dispatch_tool_ref` from `SKILLS.lock`.
  The existing broker performs dispatch; ARI does not flatten thousands of
  leaf tools into the prompt.

## 12. Harness and Assurance data model

Task 18 is normative. Four types never collapse:

| Kind | Meaning | Gate use |
|---|---|---|
| `benchmark` | evaluates a model/agent on a fixed task set, e.g. SciCode or KernelBench | cannot validate an arbitrary node when `accepts_external_target=false` |
| `artifact_verifier` | validates the generated program/binary/library against declared target/property scope | only kind eligible for node correctness when coverage matches |
| `reproduction` | validates paper/repository/experiment reproducibility, e.g. PaperBench or CORE-Bench | separate from artifact correctness |
| `claim_verifier` | checks claim/evidence transcription and derivation consistency | does not prove recorded computation is correct |

Required contracts are `VerificationContractV1`,
`VerificationRequirementV1`, `VerificationRequirementProposalV1`,
`AuxiliaryVerificationRequestV1`, `HarnessManifestV1`,
`HarnessCatalogSnapshotV1`, `HarnessRequirementV1`, `HarnessSuiteV1`,
`BaselineHarnessLockV1`, `HarnessLockRevisionV1`, `HarnessRunRequestV1`,
`HarnessPropertyResultV1`, `HarnessAttestationV1`, and
`HarnessRegistrationReportV1`.

## 13. Catalog and lock model

The three catalog namespaces and their run locks are independent:

```text
ari://knowledge/hpc/gemm-optimization@1.0.0
ari://provider/science/tooluniverse@1.0.0
ari://harness/science/scicode@1.0.0
ari://harness/hpc/gemm-correctness@1.0.0
ari://suite/hpc/cpu-kernel-certification@1.0.0
```

`ari-registry`'s EAR artifact API is not reused as a remote Harness or
Knowledge registry. A remote catalog uses separate namespaces, schemas, and
endpoints, while artifact bytes continue to use `ResearchArtifactRefV1`.

Run persistence is:

```text
knowledge/catalog_snapshot.json
knowledge/locks/epoch_<n>.json
knowledge/node_use/<node_id>.json
provider_catalog_snapshot.json
SKILLS.lock                         # unchanged canonical Provider Lock
capability_binding/baseline.json
capability_binding/revisions/epoch_<n>.json
assurance/verification_contract.json
assurance/harness_catalog_snapshot.json
assurance/locks/baseline.json
assurance/locks/revisions/epoch_<n>.json
assurance/attestations/<full_sha256>.json
run_admission.json
```

These paths are internal metadata and are excluded from candidate workspaces.
They are created only when the corresponding mode is `audit` or `enforce`.
Every lock includes the full digest of its source snapshot and contract;
runtime uses the persisted object rather than recomputing it.

## 14. Deterministic Skill admission algorithm

`knowledge_binder_v1` is a pure resolver with no LLM, network, wall clock,
randomness, Provider launch, Harness selection, or write authority. Given the
same canonical proposal, catalog snapshot, Research Contract, role/phase/task
environment, it emits byte-identical output:

1. Verify proposal, catalog, contract, and environment digests and schema
   versions.
2. Resolve every proposal entry by exact `(id, version, body_sha256,
   manifest_sha256)`; no latest/version range is allowed at run time.
3. Admit only `verified` entries; reject revoked/deprecated/candidate entries
   from authoritative use.
4. Check role, phase, task tags, preconditions, and declared scope.
5. Compute the full dependency closure; reject missing/cyclic dependencies and
   every declared conflict.
6. Reject executable fields/attachments, unpinned sources, missing licenses,
   forbidden authority, or an authority ceiling above the Research Contract.
7. Validate every capability against the frozen ontology and every evaluation
   obligation against the frozen property vocabulary.
8. Sort the admitted set by `(composition.slot_rank, -priority, id, version,
   body_sha256)`. Slot ranks are fixed in code and schema:
   `scientific-safety=10`, `scientific-method=20`, `domain-method=30`,
   `execution-strategy=40`, `reporting=50`. Two entries in an exclusive slot
   are `unsatisfied`, never arbitrarily selected.
9. Union required/optional capabilities and evaluation obligations while
   preserving every source Skill digest. A union may only strengthen the
   Research Contract.
10. Emit an immutable lock with admitted, rejected, and `unsatisfied` reasons,
    then compute its canonical full SHA-256.

In `knowledge.enforce`, any required rejected/unsatisfied entry blocks run or
next-epoch admission. In `knowledge.audit`, a structurally valid verified
Skill remains injectable when downstream capability/verification coverage is
unsatisfied, and that unsatisfied state is recorded; corrupt, unverified,
revoked, executable, path-escaping, or authority-violating content is never
injected in any mode. There is no LLM fallback.

The Router's proposal has no activation effect until this algorithm succeeds.
For a later epoch, a Skill with a new obligation first emits an
`AuxiliaryVerificationRequestV1`; Task 18 must issue a monotonic Harness lock
revision with complete coverage before Task 19 activates the Skill.

## 15. Deterministic Capability Binding algorithm

Task 17 implements the algorithm. Its hard filters are exact canonical
capability contract compatibility, verified/admitted Provider, presence in the
frozen Provider Lock, optional explicit Provider pin, role/phase/context,
side-effect ceiling, forbidden capability exclusion, credential scope,
environment feasibility, and exact input/output schema digest.

Explicit user/Research Contract pins are hard constraints, not soft ranking
preferences. Remaining candidates sort by:

1. exact semantic contract version and compatibility rule;
2. verified Provider status;
3. role/phase/context specificity;
4. least side effect;
5. scorer/operation determinism;
6. reproducibility grade;
7. environment feasibility grade;
8. declared resource cost; and
9. lexicographic fully qualified `tool_ref`.

Missing coverage emits `unsatisfied`; it never triggers substring selection,
LLM choice, network installation, bare-name fallback, or ungoverned pass-through.

## 16. Deterministic Harness resolution algorithm

Task 18 implements the algorithm. It first hard-filters verified status,
property/target/language/hardware/architecture/method/tier compatibility and
verification-environment feasibility. It then computes the exact covering
suite over the bounded reviewed catalog with this lexicographic objective:

1. zero uncovered required property/method/scope atoms;
2. stronger tier without weakening the contract;
3. deterministic scorer;
4. independent oracle;
5. lower declared resource cost;
6. fewer Harnesses; and
7. lexicographically sorted Harness IDs and versions.

The catalog admission limit is 64 compatible candidates and 128 requirement
atoms; exceeding either is an explicit deterministic admission error, not a
wall-clock timeout. The resolver uses exhaustive branch-and-bound over sorted
candidates, so identical inputs produce a byte-identical suite. No complete
cover means `unsatisfied`; no weaker fallback is admitted.

## 17. Prompt composition and provenance

Current `AgentLoop` puts tool descriptions into `post_survey_hint` and appends
working context after the node task. The adopted implementation deliberately
changes that layout while preserving `simple_bfts` bytes when Knowledge is
off:

1. **system instruction message**: constitutional constraints → run
   invariants → base and active RQGM role prompt → ordered Knowledge Skill
   bodies;
2. **user data message**: verified context, bounded and labeled as data;
3. **user task message**: node-specific goal and task; and
4. **structured tool surface**: only bound tool schemas/descriptions, supplied
   through the LLM tool API or a final explicitly untrusted data block.

This message-role separation is the safe implementation-specific refinement
of the abstract order. It avoids elevating verified context or Provider text
to system authority. Knowledge bodies are rendered exactly as:

```text
<knowledge-skill
  skill_id="..."
  skill_sha256="sha256:..."
  authority="instruction-only">
...
</knowledge-skill>
```

Their text cannot override constitutional/system instructions, tool policy,
binding, Verification Contract, tolerance, registry status, or secret policy.
Directives to ignore instructions, escalate authority, bypass verification,
change tolerances, write registries, or expose secrets remain inert content and
produce audit findings.

`InstructionCompositionV1` records at least:

```text
base_prompt_hash
base_prompt_sha256
active_rqgm_prompt_hashes
ordered_knowledge_skill_hashes
knowledge_composition_digest
capability_binding_lock_digest
verification_contract_digest
active_harness_lock_digest
```

Existing `hash12` prompt IDs remain component/provenance compatibility fields;
the composition identity and all new trust anchors use full SHA-256. A base
prompt hash alone must never be reported as the instruction identity after a
Skill body is added.

## 18. Runtime sequence

```text
bootstrap fixed institutional foundation (no execution epoch)
  → snapshot Knowledge / Provider / Harness catalogs and ontology
  → root proposal and idea selection
  → mint ResearchContractV1
  → Router selection proposal
  → fixed Knowledge admission and baseline Knowledge lock
  → union capability requirements
  → fixed Capability binding and Binding lock
  → union Research + Skill verification requirements
  → mint VerificationContractV1
  → fixed Harness resolution and baseline Harness lock
  → run admission gate
  → open first execution epoch with all digests
  → freeze node Knowledge subset and instruction identity
  → expose only bound tools and run agent
  → snapshot candidate and execute locked screen Harnesses
  → frontier/evidence/adversarial/governance processing
```

## 19. Run admission

`RQGMRuntime.ensure_epoch` cannot preserve its current “bootstrap and open
immediately” behavior under enforcement. Task 19 splits it into:

```text
RQGMRuntime.bootstrap_foundation
RQGMRuntime.admit_run
RQGMRuntime.open_execution_epoch
```

`ensure_epoch` remains the post-admission compatibility boundary hook. The
fresh RQGM BFTS call site uses the three explicit methods; it cannot call
`ensure_epoch` before admission. A pre-admission `ensure_epoch` in enforce
mode returns a typed admission error rather than opening an epoch.

Before the first node, admission requires Research Contract, Knowledge catalog
snapshot, epoch Knowledge lock, Provider Lock, Capability Binding Lock,
Verification Contract, Harness catalog snapshot, baseline/active Harness lock,
verification environment identity, and oracle bundle identity. Missing or
inconsistent objects fail closed.

## 20. Epoch and resume semantics

Run start freezes all three catalog snapshots. Before each execution epoch,
the runtime freezes the next epoch Knowledge set, active Binding revision, and
active Harness revision. Before each node, it freezes a subset of the epoch
Knowledge lock and its prompt composition. No node can add, remove, or replace
them while running.

The first execution epoch identity includes full digests of:

```text
research_contract
knowledge_catalog_snapshot
knowledge_skill_lock
provider_lock
capability_binding_lock
verification_contract
baseline_harness_lock
active_harness_lock
harness_catalog_snapshot
verification_environment
oracle_bundle
```

A later Skill/capability/Harness addition uses append-only revision objects
with `parent_lock_digest` and `baseline_lock_digest`, adopted only at an epoch
boundary. Resume validates and reuses persisted objects. Catalog files on the
current checkout are never consulted to silently “upgrade” a resumed run.

Pre-Task-16 checkpoints resume only with
`knowledge.off + capability_binding.legacy + assurance.off`. Enabling a new
mode on such a checkpoint is rejected; users start a new run that references
prior artifacts. This avoids mutating historical epoch identities.

## 21. BFTS integration

The future order is:

```text
Knowledge use + Capability Binding frozen
  → agent.run
  → candidate artifact snapshot and full digest
  → fixed verifier screen
  → assurance eligibility
  → Evaluator and RQGM adversarial/governance processing
  → node_report
  → scientific/debug/uncertified frontier classification
```

Correctness is a feasibility constraint, never a weighted objective:

```text
eligible(node) = every required screen property verdict is pass
```

`0.8 * performance + 0.2 * correctness` is prohibited. After eligibility,
the existing epoch-frozen utility policy ranks candidates.

Frontiers are typed:

- `scientific_frontier`: all required screen verdicts pass;
- `debug_frontier`: correctness fail, retained for repair/counterexamples;
- `uncertified_frontier`: inconclusive or infrastructure error.

`pass` may advance scientifically. `fail` cannot, but does not normally
impeach. `inconclusive` and `infrastructure_error` cannot publish and carry no
governance penalty; infrastructure error is retryable. `tampered` invalidates
artifact/lock/attestation and creates a Kernel integrity finding.

Typed node/tree/report fields are `knowledge_skill_refs`,
`knowledge_skill_use_digest`, `capability_binding_lock_digest`,
`bound_tool_refs`, `assurance_status`, `assurance_tier`,
`baseline_harness_lock_digest`, `active_harness_lock_digest`,
`attestation_refs`, `verified_target_digest`, `property_verdicts`, and
`frontier_class`. They are not packed into reserved metrics.

Screen applies to every BFTS node and covers compile/interface, smoke,
small differential cases, boundary cases, and cheap determinism. Validate
adds property/metamorphic tests, sanitizers, seeds, repeats, environment
consistency, stress, and edges for promotion candidates. Certify performs the
complete isolated, digest-bound suite for the final artifact/reproduction.
Parent retirement and best-node replacement require validate; publication
requires certify.

## 22. RQGM evidence and governance integration

Task 19 corrects the current Evidence Clerk semantics:

```text
node_report            -> execution_provenance
harness_attestation    -> fixed_verifier_result
knowledge_skill_use    -> instruction_provenance
capability_binding     -> execution_authority
```

`ArtifactBundle` gains Knowledge use records, Binding records, Harness
attestations, verification findings, active Harness lock digest, and
Verification Contract digest. Deterministic pre-signals cover forbidden Skill
authority, unbound invocation, Provider drift, verifier-fail/overclaim,
missing attestation, target/lock/oracle mismatch, and missing environment.
An LLM adversary may identify which claim, score, selection, or decision
contradicts fixed evidence; it may not rejudge the binding or verifier result.

Revocation and retirement use Task 10's logical, append-only staleness closure.
Historical records remain and gain `tainted-by-revocation` and
`valid_for_frontier`; no physical deletion or record rewrite occurs.

## 23. Security model

### Knowledge isolation

Knowledge packages are non-executable, content-addressed snapshots. They see
no secrets, credentials, process environment, arbitrary files, or network.
Importer path traversal/symlink escape is rejected. Reference bytes are
digest-bound. Prompt boundaries prevent constitutional override. Revoked
bodies cannot enter a new lock.

### Provider isolation

Providers use exact environment allowlists, separate credential scopes,
secret redaction, source/package/manifest/schema pins, process-group kill,
timeouts, resource/network/workspace policy, and call context. Unbound tools
cannot execute in enforce mode. Provider descriptions are untrusted. Provider
processes have no registry/catalog/lock write surface. Drift and capability
squatting fail admission.

### Harness isolation

The candidate is an immutable closed-workspace snapshot. Verifier and target
write domains are separate; oracle/hidden tests are inaccessible to the
candidate. Network is deny by default, no secrets are passed, resources and
timeouts are bounded, process groups are killed, stdout/stderr are artifacts,
and all input/output/container bytes are digested. Harness code cannot read the
entire checkpoint. Traversal/symlink escape is rejected. Execution identities
are idempotent and stale result reuse is refused on resume.

Knowledge, Provider, and Harness code never share one undifferentiated
workspace or credential set.

## 24. Config and compatibility

Typed top-level sections are:

```yaml
knowledge:
  mode: off          # off | audit | enforce
capability_binding:
  mode: legacy       # legacy | audit | enforce
assurance:
  mode: off          # off | audit | enforce
```

The resolved dotted keys are `knowledge.mode`, `capability_binding.mode`, and
`assurance.mode`; these are the only switches for the three production layers.

- `knowledge.off`: no selection, injection, snapshot, lock, or record.
- `knowledge.audit`: select/inject/record valid verified Skills; downstream
  unsatisfied coverage is reported but does not block.
- `knowledge.enforce`: verified Skill, locks, and matching provenance required.
- `capability_binding.legacy`: current discovery/visibility/dispatch unchanged.
- `capability_binding.audit`: compute/record binding while leaving legacy
  dispatch available and recording every unbound call.
- `capability_binding.enforce`: expose and invoke bound tools only.
- `assurance.off`: no new execution or artifacts.
- `assurance.audit`: run/record Harnesses without frontier/publication blocks.
- `assurance.enforce`: screen gates scientific frontier; certify gates
  publication.

Defaults are `off / legacy / off`, preserving `simple_bfts` bytes. One config
resolver combines these modes with existing `ari.mode` and `rqgm.enabled`; no
second RQGM master switch is introduced. It rejects:

- an explicit Knowledge requirement with `knowledge.off`;
- a required capability with legacy binding;
- required Verification requirements with `assurance.off`; and
- RQGM enforce mode without the corresponding catalog snapshot and lock.

Mode values are frozen in `run_admission.json` and cannot change on resume.

## 25. Implementation waves

Every row lists the required files, producer, consumer, schema/persistent
artifact, migration, tests, acceptance gate, and prerequisite task.

| Wave | Planned files | Producer → consumer | Schema / persistent artifact | Migration | Unit test | Integration test | Acceptance gate | Prerequisite |
|---|---|---|---|---|---|---|---|---|
| **A — Terminology and contract foundation** | `ari/knowledge/models.py`, `ari/providers/{models,compatibility}.py`, `ari/capability_binding/models.py`, `ari/assurance/models.py`, `ari/protocols/{scientific_requirements,provider,assurance}.py`, `ari/public/{knowledge,providers,capability_binding,assurance}.py`, listed JSON Schemas | admin/config constructors → all registries/resolvers/public consumers | canonical full-SHA contract objects; no checkpoint write | canonical Provider aliases over existing Skill types; no duplicate manifest/lock | `test_kca_contracts.py`, `test_provider_compatibility_aliases.py`, schema/contract snapshots | public import and legacy deserialization round trip | frozen models, full digests, forbidden dependency scan, old bytes equal | Task 16 |
| **B — Catalog and immutable snapshots** | `ari/knowledge/{catalog,importer,registration}.py`, `ari/providers/{catalog,registration}.py`, `ari/capability_binding/ontology.py`, `ari/assurance/{catalog,registration}.py`, `config/{knowledge_skills,providers,capabilities,harnesses}` | authenticated admin/importer → run admission | three catalog snapshots + ontology snapshot + registration reports | bootstrap reviewed legacy Provider references without rewriting manifests; candidate entries never auto-lock | `test_{knowledge,provider,harness}_registration.py`, `test_capability_ontology.py` | pin/import/revoke/resume snapshot tests | source/full commit/digest/license pins; promotion gates pass | A |
| **C — Knowledge selection and composition** | `ari/knowledge/{resolver,composition,lock,provenance}.py`, `ari/rqgm/knowledge_bridge.py`, Router proposal seam, `agent/loop.py`, prompt provenance | Router → fixed Knowledge Binder → composer/Evidence Clerk | proposal, epoch lock, node use, use record, instruction composition | off path bypasses imports and preserves prompt bytes | `test_knowledge_resolver.py`, `test_knowledge_composition.py`, hostile body fixtures | root/child node prompt + epoch change + resume | deterministic lock/composition; no authority escalation; provenance matches | A, B |
| **D — Capability Provider binding** | `ari/capability_binding/{resolver,lock,validation}.py`, `ari/providers/*`, existing `mcp/{client,dispatch_support,claude_bridge,secure_stdio_proxy}.py`, `rqgm/kernel.py`, `ari-skill-tool-registry` compatibility re-exports | fixed Capability Binder → in-process/delegated-CLI provider facade | Provider catalog snapshot, existing `SKILLS.lock`, baseline/revision Binding locks/reports | explicit legacy capability alias table; preserve bare-name behavior only in legacy | `test_capability_binding.py`, `test_bound_tool_visibility.py`, `test_provider_drift.py` | direct MCP + ToolUniverse composite route + delegated CLI parity | exact binding, fail-closed enforce, byte-identical legacy surface | A–C, Task 17 |
| **E — Constitutional authority** | `rqgm/{events,prompt_spec,kernel_rules,authority_manifest,kernel,transition_rules,meta_rules}.py`, schema/tests/snapshots | founding/admission runtime → Kernel/audit | fixed component rows, capability matrix, constitution hash, CK-KNW/CAP/HAR findings | feature-gated admission transaction; pre-16 resume stays off/legacy/off | `test_rqgm_kca_authority.py`, complement and hash pin tests | forbidden write/invoke matrix tests | fixed roles prompt-null/immutable; all new cells deny by default | A–D, Task 19 |
| **F — Harness resolver and secure runner** | `ari/assurance/{resolver,lock,suite,runner,attestation}.py`, `drivers/native.py`, existing `execution.py`, `result.py` | fixed Resolver → trusted persistence → existing fixed Verifier | Verification Contract, baseline/revision locks, run request/result, Attestation | reuse execution/result/workspace artifacts; no second runner | `test_harness_resolver.py`, `test_harness_lock.py`, `test_harness_runner_isolation.py` | immutable target, driver/oracle/container mismatch, retry/resume | complete deterministic coverage and valid target-bound attestation | A, B, Task 18 |
| **G — Run admission and BFTS integration** | `core.py`, `rqgm/runtime.py`, `cli/bfts_loop.py`, `orchestrator/{node.py,bfts.py,node_report/builder.py}`, `paths.py`, config | admission coordinator → execution epoch → AgentLoop → verifier → frontier | `run_admission.json`, expanded epoch state, typed node/report fields | `ensure_epoch` post-admission compatibility; all-off short circuit | `test_rqgm_run_admission.py`, `test_assurance_frontier.py`, `test_kca_resume.py` | first-node ordering, screen/validate/certify, resume | no execution before locks; correct three-frontier semantics | C–F, Task 19 |
| **H — Evidence and Governance bridge** | `rqgm/assurance_bridge.py`, `governance/{_records,_evidence,_pipeline}.py`, `adversarial/{records,engine,round}.py`, `frontier_repair.py` | trusted runtime records → Evidence Clerk → adversary/governance | three new record types, expanded ArtifactBundle, taint records | node_report reclassified prospectively; old evidence records retain historical bytes and are not correctness proof | `test_rqgm_kca_evidence.py`, `test_rqgm_assurance_adversarial.py` | fail vs concealment vs infrastructure scenarios | only valid attestations admitted; ordinary failure not impeached | E–G, Task 19 |
| **I — Native HPC verifier suite** | `ari/assurance/drivers/native.py`, native oracle/test-generation modules, `config/harnesses/builtin/{gemm,spmm,stencil}_correctness.yaml` | fixed Verifier → native drivers/oracles → Attestation | target interface/oracle/error model/evidence manifests | no smoke-only verifier promoted; candidates promoted after controls | `test_native_{gemm,spmm,stencil}_verifier.py` | C/C++/OpenMP/CUDA/MPI closed-workspace matrix | references pass, negative controls fail, sanitizer/determinism/stress pass | F, Task 18 |
| **J — External adapters** | `ari/assurance/drivers/{inspect,harbor,paperbench}.py`, Provider adapter modules, `ari-skill-tool-registry` seams, catalog manifests | Resolver/Verifier or Binder → pinned upstream runner/provider | upstream commit/data/container/source digests and normalized results | reuse PaperBench Stage 1→2→3 and existing federation; no framework fork | per-adapter parity and drift tests | official runner parity, negative controls, infrastructure split | pinned/licensed/parity-verified adapters only | D, F, I, Task 17/18 |
| **K — Task 13 meta-evaluation** | `ari/rqgm/evaluation/{conditions,injection,metrics,smoke}.py`, `scripts/rqgm_eval/{ablation_matrix,failure_injections,run_ablation}.py`, tests | eval campaign → production runtime under controlled H/K overlays → reports | H/K condition metadata, injection provenance, extended eval metrics | existing B0–B8 expansion/effective config unchanged | `test_rqgm_eval_{kca_conditions,kca_injection,kca_metrics}.py` | matched campaign, clean controls, portability/substitution panels | no eval fixture enters production or learning/replay | G–J, Task 20 |
| **L — CLI / MCP / Dashboard / docs** | CLI command groups, `ari-skill-{knowledge,harness}`, `viz/api_capabilities.py`, dashboard components, `docs/{reference,guides,concepts}`, `CHANGELOG.md` | humans/read-only agent surfaces → runtime/query APIs | no new authoritative MCP write object; views over persisted contracts | legacy UI “Skill” relabeled Provider without package rename; multilingual term glossary | CLI/MCP permission and snapshot tests, UI component tests | separate catalog views, admin auth, read-only agent flows | no register/promote/rewrite/force-pass MCP tool; docs and UI terms separated | B–K |

## 26. Migration

The migration decision is singular and non-destructive:

1. **Phase 1 — semantic API migration (Tasks 16–20):** `skill.yaml` and
   `SKILLS.lock` remain the sole canonical
   Provider files. `ari.providers` exposes canonical semantic names over the
   same class objects and bytes. Old Python names remain import-compatible but
   emit deprecation guidance in documentation/type docs, not runtime warnings
   that would change CLI output.
2. **Phase 2 — manifest filename decision:** every new v1 Provider also uses
   `skill.yaml`; `provider.yaml` is rejected, preventing two sources of truth.
3. **Phase 3 — lock filename decision:** `PROVIDERS.lock` is not introduced;
   `SKILLS.lock` remains canonical. Any later major-format proposal must
   provide a one-to-one offline migration and resume proof before this decision
   can be superseded; Tasks 16–20 contain no unresolved format branch.
4. UI/docs immediately display “Capability Provider” and explicitly annotate
   the legacy package/file name. Knowledge Skills are always displayed in a
   separate catalog.
5. Pre-initiative checkpoints resume only at compatibility defaults; locks and
   historical records are never rewritten.

This avoids a broad rename that would break `simple_bfts`, launcher configs,
contract snapshots, delegated CLI MCP config, or existing `ari-skill-*`
installations.

## 27. Unit tests

The implementation must add, at minimum, these named suites:

- `test_knowledge_manifest_rejects_execution_fields`
- `test_knowledge_import_rejects_traversal_symlink_and_mutable_source`
- `test_knowledge_admission_is_byte_deterministic`
- `test_router_proposal_cannot_activate_skill`
- `test_knowledge_composition_boundary_defeats_hostile_directives`
- `test_instruction_identity_includes_all_skill_and_lock_digests`
- `test_provider_compatibility_aliases_are_same_objects`
- `test_capability_alias_table_has_no_fuzzy_fallback`
- `test_binding_is_byte_deterministic_and_fail_closed`
- `test_harness_resolution_is_byte_deterministic_and_complete`
- `test_lock_revisions_are_monotonic`
- `test_attestation_target_binding_and_full_digests`
- `test_no_forbidden_dependency_edges`
- `test_all_off_path_does_not_import_new_packages`

Tasks 17–20 provide the full per-layer test matrices.

## 28. Integration tests

Required cross-layer scenarios are:

1. one unchanged GEMM Knowledge Skill binds to two verified Providers in two
   matched runs and produces distinct Provider provenance but identical Skill
   identity;
2. two Skills bind requirements to the same Provider without conflating Skill
   identity;
3. ToolUniverse Provider and ToolUniverse Knowledge source are separately
   registered/enabled/locked;
4. direct MCP and delegated CLI surfaces expose the same bound intersection;
5. a later-epoch Skill with a new obligation activates only after monotonic
   Binding and Harness revisions;
6. screen fail goes to debug, infrastructure error goes to uncertified, and
   pass goes to scientific frontier;
7. stale Skill, stale Binding, and stale Attestation are independently
   detected on resume;
8. PaperBench rollout→reproduction→grading is invoked through the existing
   bridge and normalized as a reproduction Attestation;
9. certify Attestation target digest equals the publication claim target;
10. `simple_bfts` with defaults produces byte-identical prompts/tools and no
    new artifact paths.

## 29. Acceptance criteria

Task 20 §8 is the single numbered, machine-verifiable list of all 68 acceptance
criteria. Tasks 16–19 own the tests mapped there. No task may declare complete
from prose review alone; every criterion has a named unit/integration/contract
test or an upstream parity report.

## 30. Documentation changes

Wave L updates, but this planning task does not yet edit:

- `docs/reference/skills.md` — the branch has this file; the requested
  `docs/skills.md` path does not exist — to explain the legacy Provider
  filename and canonical terminology;
- `docs/reference/mcp_tools.md` and new Knowledge/Provider/Harness file-format
  references;
- `docs/concepts/rqgm_architecture.md` and
  `docs/concepts/rqgm_runtime_walkthrough.md` with the admitted execution
  sequence and evidence semantics;
- `docs/guides/rqgm_evaluation.md` with orthogonal H/K conditions while
  preserving B0–B8;
- execution-mode, extension, catalog-maintainer, and assurance guides;
- dashboard help and `CHANGELOG.md`.

English is the canonical identifier/schema language. Japanese documentation
uses one reviewed glossary mapping the same identifiers; translated prose does
not introduce alternate status, capability, or verdict names.

## 31. Honest limits

- Knowledge Skills are procedural knowledge, not guarantees of scientific
  success or correctness; quality depends on empirical evaluation and human
  governance.
- The semantic capability ontology requires human curation. Providers that
  satisfy the same ref can still behave differently.
- External API, hardware, model, or Provider revisions that cannot be fully
  pinned must be explicitly recorded as unverified substrate provenance.
- Static checks cannot prove all Provider descriptions harmless.
- Harness pass guarantees only declared properties within declared scope. Only
  a formal-verifier Harness proves a formal specification.
- GPU nondeterminism and Provider-side revision that cannot be pinned remain in
  the Attestation.
- An external benchmark with an LLM scorer cannot replace a deterministic
  artifact-correctness gate.
- Initial catalog trust roots depend on code review and human governance.
- No claim extends beyond Harness property/domain coverage.
- Infrastructure error never fails open into verified status.
- RQGM does not generate a verifier's mathematical conclusion; it governs who
  ignored or distorted fixed evidence.
- Separating Knowledge and Provider authority does not guarantee an external
  Provider is benign.

## 32. Dependencies on existing Tasks

| Existing task | Reused contract or constraint |
|---|---|
| 00–01 | worktree inventory; `simple_bfts` byte compatibility and `ari.mode` interlock |
| 02 | immutable epoch state, event store, registry freeze, resume reconstruction |
| 03 | existing Router as proposal producer; no second Router |
| 04 | fixed constitutional validation, deny-by-default matrix, audit findings |
| 05–06 | Evidence Clerk/governance and adversarial record flow |
| 07–08 | PromptSpec provenance/immutable body patterns and clean-room authority boundaries |
| 09–10 | boundary-only transitions, append-only retirement/taint/frontier repair |
| 11–12 | fixed/meta role rules, context and cost accounting |
| 13 | B0–B8 meta-evaluation machinery; production code must not depend on it |
| 14 | epoch-frozen utility identity and policy provenance |
| 15 | producer component/prompt/epoch binding for accountable evidence |
| `ari_rqgm_paper/07` | independent claim-evidence gate and publication handoff; certify becomes an additional hard prerequisite, not a replacement |

Task order is `16 → 17 → 18 → 19 → 20`. Tasks 17 and 18 may implement their
RQGM-independent cores in parallel after Task 16 contracts freeze; Task 19
requires both. Task 20 requires the production path from Task 19.

## 33. Explicit deviations from the previous plan

1. **No master plan exists.** INDEX explicitly defines a flat canonical task
   set, so this initiative is Tasks 16–20 rather than a parallel parent plan.
2. **Task 13 prose versus executable conditions.** Task 13's historical plan
   contains a B9 proposal, while the current `ablation_matrix.yaml`, evaluation
   code, guide, and changelog expose B0–B8. The worktree implementation is the
   authority: Tasks 16–20 freeze B0–B8 and add H/K namespaces. They neither
   redefine an existing B condition nor use the unrealized B9 label.
3. **Existing fixed verifier is reused.** `events.py` already names
   `fixed_verifier`; scientific execution is added to `fixed_verifier_v1`, not
   a duplicate role.
4. **Fixed-role provenance gap is closed only when enabled.** The fixed role
   vocabulary exists but the current founding component table has no kernel,
   verifier, or audit-log rows. Task 19 uses a feature-gated admission
   transaction with prompt-null fixed components; all-off legacy runs retain
   their bytes.
5. **`node_report` is not correctness evidence.** The current Evidence Clerk
   map is prospectively corrected; historical bytes remain untouched.
6. **Tool-name policy becomes legacy only.** Substring inference and unknown
   passthrough remain solely in `capability_binding.legacy`; audit records the
   gap and enforce blocks it.
7. **Tool descriptions lose instruction authority.** Existing dynamic
   descriptions are moved to bounded, structured untrusted data after binding.
8. **Epoch bootstrap is split.** The existing immediate `ensure_epoch` open is
   replaced on the enabled path by foundation → admission → execution epoch.
9. **Tool Registry is reused.** The current ToolUniverse federation and
   `CATALOG.lock` are normalized behind `ari.providers`; no duplicate provider
   discovery or dispatch stack is introduced.
10. **PaperBench is reused.** Its existing three-stage bridge is the
    reproduction driver; rollout/reproduce/grade are not reimplemented.
11. **Legacy filenames remain canonical.** The plan chooses no
    `provider.yaml`/`PROVIDERS.lock` migration in this initiative, eliminating
    a dual-source ambiguity.
12. **Prompt ordering is message-role safe.** Knowledge remains lower than
    constitutional system instructions, while verified context and Provider
    descriptions remain data; this intentionally refines the abstract linear
    order after inspection of current `AgentLoop` construction.

## 34. Completion criteria

Task 16 is complete only when Waves A–C are implemented; the contract and
architecture tests are green; the Knowledge registration/admission/composition
path has no executable authority; the off path is byte-identical; Tasks 17–20
consume the frozen contracts without a duplicate schema; and every owned item
in Task 20's 68-criterion matrix passes.

## 35. Deletion criteria

This plan is **not deletable** until Tasks 16–20 are implemented and merged,
CI is green, permanent architecture/file-format/security/extension docs carry
all normative decisions, migration and resume tests pass on released
checkpoints, upstream adapter parity reports are retained, INDEX is updated,
and deleting this file would lose no requirement or threat rationale.

## 36. Delete-after checklist

- [ ] Task 16 completion criteria satisfied.
- [ ] Downstream Tasks 17–20 completed and no longer depend only on this file.
- [ ] All 68 acceptance criteria linked to permanent tests/docs.
- [ ] Compatibility and resume migrations proven on released fixtures.
- [ ] Key terminology, authority, threat, and lock decisions moved to permanent docs.
- [ ] INDEX status/deletion tables updated in the same change that deletes this file.
