# Task 19: RQGM Governance Integration

> **Status**: in progress · **Depends on**: 02–12, 14–18,
> `ari_rqgm_paper/07` · **Implementation checkpoint**: 2026-08-03 · **This is a
> temporary task plan** — see [INDEX.md](INDEX.md). Fixed roles, admission and
> resume ordering, prompt/tool integration, Kernel findings, assurance
> frontier classes, dedicated evidence, adversarial/governance signals,
> surfaces, and tests have landed. End-to-end certify/publication evidence over
> promoted external Harnesses remains gated by Task 18's external prerequisites.

## 1. Purpose

Connect the RQGM-independent Knowledge, Provider Binding, and Assurance layers
to RQGM's fixed institution, run admission, execution epochs, AgentLoop, BFTS
frontiers, Evidence Clerk, adversarial engine, transition audit, and
certification-bound publication. RQGM governs authority and use of fixed
evidence; it does not decide procedural content, choose Providers/Harnesses by
LLM, or recompute scientific verdicts.

## 2. Scope

- Fixed roles/components and deny-by-default capability matrix.
- `ari.rqgm.knowledge_bridge` and `ari.rqgm.assurance_bridge` only; no reverse
  import from production core layers.
- Stable CK-KNW/CK-CAP/CK-HAR findings and constitutional hash amendment.
- Foundation bootstrap, run admission, execution epoch open, resume, and
  append-only revision order.
- Deterministic prompt/use and bound tool insertion before AgentLoop.
- Screen/validate/certify insertion and typed three-frontier semantics.
- Dedicated Knowledge Use, Capability Binding, and Harness Attestation
  evidence records.
- Deterministic adversarial pre-signals and governance misuse criteria.
- Agent MCP, human CLI, and Dashboard surfaces with separate catalogs.
- Compatibility modes, persistent artifacts, and publication interlock.

## 3. Non-goals

- No individual Knowledge Skill, Provider, tool, or Harness in
  `ComponentRegistry`.
- No LLM in Knowledge Binder, Capability Binder, Harness Resolver, fixed
  verifier decision logic, or Constitutional Kernel.
- No catalog administration through research-node MCP.
- No Harness choice through the agent's free tool selection.
- No verdict override, target rewrite, or scientific reinterpretation by the
  Kernel or adversarial LLM.
- No impeachment for an ordinary failed candidate.
- No production mechanism in `ari.rqgm.evaluation`.
- No output/prompt/artifact change in `simple_bfts` with compatibility defaults.

## 4. Fixed layer and Component Registry boundary

The fixed procedure set is:

```text
constitutional_kernel_v1
knowledge_binder_v1
capability_binder_v1
harness_resolver_v1
fixed_verifier_v1
audit_log_v1
```

`fixed_verifier` already exists in `FIXED_ROLES`; it is reused. Task 19 adds
`knowledge_binder`, `capability_binder`, and `harness_resolver` to
`FIXED_ROLES`. The first enabled run's feature-gated founding/admission
transaction registers every row with:

```text
tier: fixed
prompt_id: null
status: active
capabilities: exact fixed procedure grants from §6
```

The current `FOUNDING_COMPONENT_TABLE` has no kernel/verifier/audit-log rows
despite the role vocabulary. Adding those rows only in the new feature
admission transaction preserves all-off historical bytes. A pre-Task-19
checkpoint cannot enable the transaction on resume; it must remain at
off/legacy/off or start a new run.

Fixed procedures are code-reviewed, deterministic, prompt-evolution exempt,
impeachment exempt, incumbent-competition exempt, and unable to write arbitrary
checkpoint paths. They do not use an LLM or network for admission, binding, or
resolution. Harness execution may launch a lock-declared network-denied
substrate; that launch is not a selection decision.

Registry boundaries are:

| Registry/snapshot | Contains |
|---|---|
| `ComponentRegistry` | institutional actors and fixed procedures only |
| `GovernedKnowledgeSkillRegistry` | immutable procedural content and lifecycle transitions |
| Provider Catalog + Provider Lock | admitted executable subjects and exact live tool schemas |
| Harness Catalog + Harness Lock | immutable verification definitions and selected suite identities |

## 5. Authority separation

### 5.1 Generator

May request another Knowledge Skill, auxiliary capability, or debug
verification; read Attestations; invoke a Provider tool within the active
Binding Lock; and record Skill/Provider failures.

Cannot promote/edit a Skill, register/promote/substitute a Provider, forge a
capability ref, rewrite a lock, invoke an unbound tool, remove a required
Harness, change tolerance/oracle/dataset/driver/container, or override fail.

### 5.2 Router

May emit `KnowledgeSkillSelectionProposalV1`, applicability reasons, and
node/next-epoch candidates. It cannot change catalog status, activate a Skill,
bind a capability/Provider, select a Harness, or expand authority.

### 5.3 Knowledge Binder / fixed

May read the frozen catalog/body, contract, environment, and proposal and
return a pure admission/lock value. It cannot use an LLM/network/clock, write a
catalog/registry/frontier, edit a body, launch a Provider, or select a Harness.

### 5.4 Capability Binder / fixed

May read requirements, ontology, Provider catalog/lock, role/phase/context, and
environment and return a pure Binding Lock. It cannot register/launch/modify a
Provider, change schemas or credentials, edit a Skill, select a Harness, or
write registry/frontier.

### 5.5 Evaluator / Reviewer

May propose required properties, request auxiliary verification, scientifically
evaluate use of Skills/Providers, and explain admitted Attestations. It cannot
select the authoritative Harness, change any catalog/lock, remove a required
property/method, weaken tier/tolerance, override a fixed verdict, or call a
failed artifact correct.

### 5.6 Harness Resolver / fixed

May read Research/Verification Contracts, frozen verified catalog, and frozen
verification environment and return pure resolution/lock values. It cannot use
an LLM/network/clock, write contract/catalog/registry/frontier/target, or alter
verdict/tolerance.

### 5.7 Fixed Verifier / fixed

May read the active lock and immutable target, execute the locked Harness, and
return an Attestation. It cannot select/change a Harness or lock, edit
catalog/oracle/target/frontier/registry, or make semantic paper-claim judgments.

### 5.8 Human / catalog maintainer

Only a reviewed PR or authenticated admin CLI may register, promote,
deprecate, or revoke Knowledge Skills, Providers, and Harnesses. No LLM or
research node receives the admin credential or endpoint.

## 6. Capability matrix

New resource classes are:

```text
research_contract
knowledge_catalog
knowledge_skill_bodies
knowledge_lock
capability_ontology
provider_registry
provider_lock
capability_binding
provider_execution
verification_contract
harness_catalog
harness_lock
target_snapshot
harness_execution
harness_attestations
```

They extend, not replace, the current resources (`records`, `registry`,
`audit_log`, `frontier`, prompt text, checkpoint artifacts, candidates).
Unlisted cells remain deny.

| Role/tier | Exact new grants | Explicit denies |
|---|---|---|
| `constitutional_kernel/fixed` | read all new integrity objects; invoke pure validation only | append/write/activate/invoke execution, catalog/registry/frontier mutation |
| `knowledge_binder/fixed` | read `research_contract`, `knowledge_catalog`, `knowledge_skill_bodies`, `capability_ontology`; invoke pure `knowledge_lock` resolution | catalog/lock persistence, Provider/Harness invocation, registry/frontier write |
| `capability_binder/fixed` | read `research_contract`, `knowledge_lock`, `capability_ontology`, `provider_registry`, `provider_lock`; invoke pure `capability_binding` resolution | Provider registration/execution, credential expansion, Harness selection, registry/frontier write |
| `harness_resolver/fixed` | read `research_contract`, `verification_contract`, `harness_catalog`; invoke pure `harness_lock` resolution | contract/catalog/target/attestation/registry/frontier write |
| `fixed_verifier/fixed` | read `verification_contract`, `harness_lock`, `target_snapshot`; invoke `harness_execution`; return Attestation value | catalog/lock/target/registry/frontier write, Provider free choice |
| `generator/institutional` | read active Knowledge bodies/use and Attestations; invoke `provider_execution` only through signed Binding context; append request/failure records | every catalog/lock/registry write, unbound invocation, Harness execution/selection |
| `router/institutional` | read Research Contract and Knowledge catalog metadata; append selection proposals | body/lock/binding/provider/harness writes or activation |
| `reviewer` / Evaluator | read Verification Contract and Attestations; append requirement/review proposals | Harness lock/resolution/verdict change and catalog writes |
| `audit_log/fixed` | append `audit_log` only, as today | every other new action |

Trusted runtime persistence is not a Component role. Each facade has one
schema/path-specific atomic writer and cannot accept an arbitrary checkpoint
path from a fixed component.

## 7. Constitutional Kernel checks

The Kernel verifies integrity, authority, binding, and procedure; it does not
judge numerical/scientific truth. Codes are stable public audit identifiers.

### 7.1 Knowledge codes

| Code | Finding |
|---|---|
| `CK-KNW-001` | unverified/deprecated/revoked authoritative use |
| `CK-KNW-002` | body digest mismatch |
| `CK-KNW-003` | manifest digest mismatch |
| `CK-KNW-004` | in-place body/entry mutation |
| `CK-KNW-005` | node use versus actual composition mismatch |
| `CK-KNW-006` | mid-node substitution |
| `CK-KNW-007` | capability above authority ceiling |
| `CK-KNW-008` | forbidden capability request |
| `CK-KNW-009` | unauthorized catalog/status write |
| `CK-KNW-010` | unpinned external source |
| `CK-KNW-011` | stale Knowledge lock |
| `CK-KNW-012` | revoked entry activated in a new epoch |
| `CK-KNW-013` | registry-write/authority-escalation directive treated as authority |
| `CK-KNW-014` | Harness-bypass/tolerance-change directive treated as authority |
| `CK-KNW-015` | hidden executable or direct attachment launch path |

### 7.2 Capability/Provider codes

| Code | Finding |
|---|---|
| `CK-CAP-001` | unbound tool invocation |
| `CK-CAP-002` | capability ref mismatch |
| `CK-CAP-003` | semantic contract mismatch |
| `CK-CAP-004` | unauthorized Provider/tool selection |
| `CK-CAP-005` | Provider manifest digest mismatch |
| `CK-CAP-006` | live input/output schema mismatch |
| `CK-CAP-007` | Provider version/source drift |
| `CK-CAP-008` | Binding Lock rewrite/non-monotonic revision |
| `CK-CAP-009` | role/phase/context mismatch |
| `CK-CAP-010` | side-effect ceiling exceeded |
| `CK-CAP-011` | credential scope exceeded |
| `CK-CAP-012` | unmapped external tool |
| `CK-CAP-013` | substring/name inference used as authority |
| `CK-CAP-014` | stale Binding Lock |
| `CK-CAP-015` | revoked Provider used in a new binding |
| `CK-CAP-016` | Provider description altered instruction/authority |
| `CK-CAP-017` | capability squatting or collision |
| `CK-CAP-018` | verification/execution environment mismatch |

### 7.3 Harness codes

| Code | Finding |
|---|---|
| `CK-HAR-001` | required property/method/scope coverage missing |
| `CK-HAR-002` | unverified/deprecated/revoked authoritative Harness |
| `CK-HAR-003` | unauthorized actor selected a Harness |
| `CK-HAR-004` | required Harness/requirement removed |
| `CK-HAR-005` | non-monotonic lock revision |
| `CK-HAR-006` | Harness lock digest mismatch |
| `CK-HAR-007` | manifest digest mismatch |
| `CK-HAR-008` | oracle digest mismatch |
| `CK-HAR-009` | dataset digest mismatch |
| `CK-HAR-010` | driver digest mismatch |
| `CK-HAR-011` | container digest mismatch |
| `CK-HAR-012` | current target digest mismatch/substitution |
| `CK-HAR-013` | stale Attestation reuse |
| `CK-HAR-014` | malformed or forged Attestation |
| `CK-HAR-015` | contract/Attestation scope mismatch |
| `CK-HAR-016` | tier downgrade |
| `CK-HAR-017` | tolerance relaxation |
| `CK-HAR-018` | publication without required verifier/certify |
| `CK-HAR-019` | verifier result suppressed or overwritten |
| `CK-HAR-020` | hidden oracle/test access attempt |

### 7.4 Severity and blocking

- Unauthorized writes/rewrites, credential expansion, hidden-oracle access,
  target substitution, forgery, and actual authority escalation are `critical`
  and block in every `ari_rqgm` audit/enforce posture.
- Status, coverage, stale identity, unknown capability, drift, and unbound-use
  findings are `high`; they block the corresponding enforce mode and are
  audit-only in that layer's audit mode.
- A forbidden sentence merely present inside a safely bounded Skill/Provider
  description is `medium` provenance evidence; it becomes critical only if it
  changes composition, authority, binding, or verification behavior.
- New checks do not execute when all corresponding modes are compatibility
  defaults.

The implementation updates `kernel_rules.py`, `authority_manifest.py`,
Kernel validators, schema enums, emergency/blocking context map, audit-only
tests, and the complete deny-by-default complement. The canonical constitution
payload is re-hashed. Existing `CONSTITUTION_HASH`/`constitution_hash` remains
the legacy `hash12` identifier for replay compatibility; the same canonical
payload also mints `CONSTITUTION_SHA256`/`constitution_sha256`, which is the
authoritative full-SHA trust anchor bound into every new lock, epoch, finding,
and Attestation. Both pins and every fixture/report are updated in the same
implementation commit. No code is added without its complement test.

A candidate program's ordinary `fail` is not a CK violation. Concealing,
overwriting, substituting, or claiming success against the fixed record is.

## 8. Run admission and execution epoch order

### 8.1 Current mismatch

The current BFTS path calls `ensure_epoch` before root proposal; that method
registers founding entries and opens `epoch_000`. Research Contract generation
and first Provider-driven work occur later. An execution fingerprint therefore
cannot include contracts/locks that do not yet exist.

### 8.2 Adopted sequence

The enabled path is exactly:

1. `bootstrap_foundation`: replay or write legacy founding registration plus
   the feature-gated fixed-procedure admission transaction; do not open an
   execution epoch.
2. Freeze Knowledge, Provider, Capability Ontology, Harness catalog, and
   verification-environment snapshots. Provider discovery may start pinned
   Providers and mint the existing `SKILLS.lock`; no agent node runs.
3. Generate/select root proposal through existing Task 03 Router machinery.
4. Mint `ResearchContractV1`.
5. Router emits baseline Knowledge selection proposal.
6. Fixed Knowledge Binder emits baseline epoch Knowledge lock.
7. Union Research and Skill capability requirements.
8. Fixed Capability Binder emits baseline Binding Lock.
9. Union Research and Skill evaluation obligations and mint
   `VerificationContractV1`.
10. Fixed Harness Resolver emits the deterministic `HarnessSuiteV1` and
    baseline-lock candidate.
11. Constitutional Kernel validates coverage, actor authority, digests, tier,
    tolerance, and monotonicity; the trusted `admit_run` facade then mints the
    immutable baseline Harness Lock, verifies all remaining config/fixed-role/
    environment interlocks, and writes `run_admission.json`.
12. `open_execution_epoch` freezes all identities in `epoch_000`.
13. Select and validate the root node Knowledge subset and write
    `NodeKnowledgeSkillUseV1`.
14. Compose instruction identity and build the bound visible-tool facade.
15. Begin AgentLoop.
16. After an immutable candidate exists, execute screen and then process
    evidence/frontier.

No `ensure_epoch` call can bypass steps 1–12. After admission it remains the
node-count boundary API and retains Task 05/09/10 audit/transition/repair
ordering.

## 9. Epoch, revision, and resume semantics

`EpochState` gains full-digest fields listed in Task 16 §20 under a new schema
version. Existing `hash12` component/prompt/epoch IDs remain unchanged for
legacy checkpoints. The new epoch fingerprint includes canonical full digests
and mode values; it does not truncate new trust anchors.

At an epoch boundary:

1. close/audit the current epoch using its frozen identities;
2. process catalog revocation taint without rewriting history;
3. validate a next-epoch Router proposal;
4. create any additive Capability Binding revision;
5. create any additive verification/Harness revision required by new Skills;
6. admit the next Knowledge lock only after capability and Harness coverage;
7. run the existing RegistryTransitionEngine and frontier repair;
8. atomically persist the new lock/revision refs; and
9. open the next epoch with one new fingerprint.

Failure before step 8 leaves the current epoch/locks active and records an
`unsatisfied` next-epoch proposal. There is no partial lock adoption.

Resume first validates `run_admission.json`, catalog snapshots, all baseline
locks, the active revision chain, epoch fingerprint, and Provider live-schema
parity. It never consults current catalog latest. Drift is a typed stop in
enforce, an audit finding without rebinding in audit, and legacy behavior only
in legacy mode.

## 10. Agent runtime insertion

Before each node:

```text
target/goal and node role/phase fixed
  → read epoch Knowledge lock
  → accept an optional Router subset proposal or deterministic applicable default
  → fixed Knowledge Binder validates subset
  → persist NodeKnowledgeSkillUseV1
  → deterministic prompt composition and InstructionCompositionV1
  → build bound visible-tool intersection
  → start AgentLoop with signed ToolCallContextV1
```

No body/catalog/network fetch occurs during AgentLoop. Tool descriptions are
operation/schema data from the bound Provider only. The current
`enrich_hints_from_mcp` path is changed on enabled runs so descriptions cannot
enter the system instruction or create workflow authority. Text demanding
system override, Harness bypass, secrets, registry write, role impersonation,
or retired prompt access is bounded as untrusted data and generates a finding
if acted upon.

In-process and delegated CLI calls go through the same Binding Lock and call
context. The CLI receives only the Provider configs required for bound tools
and the exact allowlist; it cannot use ambient project MCP servers.

## 11. BFTS and frontier integration

### 11.1 Current mismatch and insertion point

Current `bfts_loop.py` appends a completed node to the frontier before the
sterile gate, adversarial round, and persisted node report. Task 19 moves all
scientific frontier admission and parent retirement after fixed screen and
assurance classification:

```text
agent.run
  → candidate artifact/reference selected
  → immutable target snapshot/full digest
  → fixed verifier screen
  → assurance eligibility
  → scientific Evaluator and RQGM adversarial processing
  → node_report with admitted evidence
  → typed frontier classification
  → best-node/parent-retirement/next-expansion decisions
```

The sterile gate remains independent and must also pass. Scientific
eligibility is:

```text
not sterile
AND every required screen property == pass
AND no critical integrity finding
```

Utility ranks only eligible nodes. `fail` is kept in `debug_frontier`;
`inconclusive`/`infrastructure_error` in `uncertified_frontier`; `tampered` is
invalid/stale and not a frontier candidate. Debug/uncertified nodes can seed a
repair proposal but cannot be best/published. Validate is required before
parent retirement or best replacement. Certify is required before final
selection/paper publication.

### 11.2 Typed fields

`Node`, tree serialization, result summaries, and `node_report` add:

```text
knowledge_skill_refs
knowledge_skill_use_digest
capability_binding_lock_digest
bound_tool_refs
assurance_status
assurance_tier
baseline_harness_lock_digest
active_harness_lock_digest
attestation_refs
verified_target_digest
property_verdicts
frontier_class
```

Fields are schema-typed, digest validated, and omitted entirely on the all-off
compatibility path. They are not encoded solely as reserved metric keys.

## 12. Evidence Clerk

### 12.1 Record types

The closed admissible map becomes:

```text
record_type: node_report
admissible_kind: execution_provenance

record_type: harness_attestation
admissible_kind: fixed_verifier_result

record_type: knowledge_skill_use
admissible_kind: instruction_provenance

record_type: capability_binding
admissible_kind: execution_authority
```

Historical `node_report` records are not rewritten. On replay they remain
execution provenance and cannot satisfy a correctness requirement.

Existing `EvidenceBundle.items[].content_hash` remains a legacy `hash12` field
for old-record replay. New KCA item schemas also require
`content_sha256`; Evidence Clerk and Kernel use the full value as the trust
anchor and reject an item that supplies only the short hash. Both values are
computed from the same canonical bytes through the shared digest utility.

### 12.2 Harness admission checks

Evidence Clerk verifies author `fixed_verifier_v1`, null prompt hash, schema,
all source refs, target/current artifact equality, lock and manifest/oracle/
dataset/driver/container digests, property/method/scope coverage, evidence
artifact digests, attempt identity, and non-staleness.

### 12.3 Knowledge admission checks

It verifies Skill presence in the epoch lock, body/manifest/status-at-use,
ordered composition digest, node prompt provenance/instruction identity, no
mid-node substitution, and revocation taint.

### 12.4 Binding admission checks

It verifies Binding/Provider Lock digests, Provider/tool/schema identities,
semantic contract, role/phase/context/credential/side-effect decision, and
that every invocation in the execution trace was bound.

An invalid item enters `excluded_items` with a stable reason and cannot be
silently padded. Existing same-role and raw-attack rules remain unchanged.

## 13. Adversarial and governance bridge

`ArtifactBundle` adds:

```text
knowledge_skill_use_records
capability_binding_records
harness_attestations
verification_findings
active_harness_lock_digest
verification_contract_digest
```

Deterministic pre-signals are:

| Fixed observation | Signal |
|---|---|
| Skill requests forbidden authority/bypass | `prompt_injection` / `authority_escalation` |
| unbound invocation or Provider substitution | capability-integrity finding |
| Provider schema drift | reproducibility/integrity finding |
| fixed fail plus a strong correctness claim | `metric_gaming` / `overclaim` |
| required Attestation missing | `evidence_gap` |
| paper/Evaluator treats fail as pass | `overclaim` / `evidence_gap` |
| target/lock/oracle/manifest mismatch | Kernel integrity finding |
| environment identity missing | reproducibility signal |
| infrastructure error alone | no attack signal |

The adversarial LLM receives fixed verdict/binding validity as premises and
asks only which actor's claim, score, selection, or decision contradicts them.
It cannot change a verdict or binding.

Governance-worthy conduct includes deliberate revoked Skill/Provider use,
hidden Skill provenance, deliberate unbound call, concealed schema drift,
false success claims, “verified” without required execution, hidden/stale
Attestation, target substitution, frontier promotion despite fail, or
publication without certify. One wrong candidate, inconclusive result, or
infrastructure error is ordinary exploration and never automatically triggers
impeachment.

Task 10 frontier repair handles revocation/staleness closure. Records retain
`knowledge_skill_hash`, `knowledge_skill_status_at_use`,
`tainted-by-revocation`, and `valid_for_frontier`; nothing is physically
deleted or rewritten.

## 14. Certification-bound publication

Before final paper generation/finalize/publish, the paper runtime verifies:

1. every code/measurement artifact used by a verified claim has a current
   certify Attestation covering its property and scope;
2. publication target digest equals the Attestation target digest;
3. Verification Contract and active Harness lock digests match the run;
4. Attestation is Evidence-Clerk admitted and not revoked/stale/tampered; and
5. the existing claim-evidence hard gate independently passes transcription,
   derivation, and citation checks.

Program correctness and claim consistency remain two independent hard gates.
Neither can satisfy the other.

## 15. MCP, CLI, and Dashboard

### 15.1 Agent-facing MCP

The default-off `ari-skill-knowledge` Provider exposes only:

```text
search_knowledge_skills
describe_knowledge_skill
list_active_knowledge_skills
request_knowledge_skill
```

The default-off `ari-skill-harness` Provider exposes only:

```text
search_harnesses
describe_harness
request_auxiliary_verification
read_attestation
list_verification_requirements
```

Provider operations exposed to an agent are only the tools already in the
active Binding Lock. The following names/capabilities do not exist on any
agent MCP surface:

```text
register_skill / promote_skill / revoke_skill / rewrite_knowledge_lock
register_provider / promote_provider / revoke_provider
rewrite_provider_lock / rewrite_capability_binding
register_harness / promote_harness / revoke_harness
rewrite_harness_lock / change_tolerance / replace_oracle / force_pass
```

Request tools append non-authoritative proposals through a narrow trusted
facade. Resolution/execution occur internally and never depend on which MCP
tool an LLM chooses.

### 15.2 Human CLI

Diagnostic commands:

```text
ari knowledge search
ari knowledge show
ari knowledge validate-manifest
ari knowledge validate-registration
ari knowledge lock show
ari knowledge use show

ari provider search
ari provider show
ari provider validate-manifest
ari provider probe
ari provider lock show
ari provider bindings show

ari harness search
ari harness show
ari harness validate-manifest
ari harness validate-registration
ari harness resolve
ari harness lock show
ari harness verify
ari harness suite run
ari harness attestation show
```

The import command is admin-gated:

```text
ari knowledge import
```

`ari knowledge import` and every register/promote/deprecate/revoke operation
are admin commands under an authenticated local/admin credential gate, write
registration reports, and refuse to target a running lock. Diagnostic commands
cannot transition status.

The status-changing command namespace is deliberately separate:

```text
ari admin knowledge register|promote|deprecate|revoke
ari admin provider register|promote|deprecate|revoke
ari admin harness register|promote|deprecate|revoke
```

### 15.3 Dashboard

Wave L adds separate pages for Knowledge Catalog/active epoch/node provenance;
Provider Catalog/status/source/credential scope and bound/unsatisfied
capabilities; and Harness Catalog/Verification Contract/baseline+revision/
per-node Attestations/property coverage/failure/infrastructure/publication
certification/trust/license/source. The three catalogs never share one “Skill”
list or status filter.

## 16. Config and compatibility wiring

Task 16's `knowledge`, `capability_binding`, and `assurance` modes are typed
siblings of existing ARI/RQGM config, not members of `rqgm.eval`. One effective
mode resolver enforces:

- all three compatibility defaults under `simple_bfts`;
- explicit requirement/off conflicts as admission errors;
- RQGM enforce locks and fixed components as mandatory;
- mode freeze in `run_admission.json`; and
- no resume-time mode upgrade.

When `simple_bfts + off/legacy/off`, lazy guards prevent importing the new
packages and prevent checkpoint files, metrics, reserved fields, snapshots,
locks, prompt differences, or tool visibility differences. Existing
`ari.mode`, `rqgm.enabled`, and Task 13 B0 effective config are unchanged.

## 17. Planned files

```text
ari-core/ari/rqgm/knowledge_bridge.py
ari-core/ari/rqgm/assurance_bridge.py
ari-core/ari/rqgm/{events,prompt_spec,kernel_rules,kernel,
    authority_manifest,transition_rules,meta_rules,runtime,state,store}.py
ari-core/ari/rqgm/governance/{_records,_evidence,_pipeline}.py
ari-core/ari/rqgm/adversarial/{records,engine,round}.py
ari-core/ari/rqgm/frontier_repair.py
ari-core/ari/core.py
ari-core/ari/cli/bfts_loop.py
ari-core/ari/orchestrator/{node.py,bfts.py,node_report/builder.py}
ari-core/ari/agent/{tool_manager,workflow,loop}.py
ari-core/ari/paths.py
ari-core/ari/config/{__init__.py,defaults.yaml}
ari-skill-knowledge/{src/server.py,skill.yaml,pyproject.toml,README.md,tests/}
ari-skill-harness/{src/server.py,skill.yaml,pyproject.toml,README.md,
    REQUIREMENTS.md,tests/}
```

`ari-skill-harness` is never the authoritative resolver/runner. It is a
read-only/query/request Capability Provider whose legacy prefix is documented.

## 18. Tests

### Fixed authority and Kernel

- fixed component founding rows have tier fixed, prompt null, exact grants;
- no fixed role is mutation/impeachment/competition eligible;
- complete capability matrix and deny-by-default complement snapshots;
- every CK-KNW/CAP/HAR code has positive, complement, enforce, and audit test;
- constitution hash/authority manifest/schema pins agree; and
- ordinary fail emits no CK finding while concealment does.

### Admission/epoch/resume

- first execution epoch cannot open before all baseline digests;
- foundation bootstrap alone opens no epoch;
- atomic admission leaves no partial locks;
- later Skill waits for additive Binding/Harness coverage;
- active revisions change only at epoch boundary;
- resume uses persisted snapshots and independently catches stale Skill,
  Binding, and Attestation;
- pre-Task-19 resume mode upgrade is rejected; and
- all-off legacy path remains byte-identical.

### Agent/BFTS/evidence/governance

- Knowledge subset/composition/use freezes before AgentLoop;
- direct and delegated tool surfaces equal the Binding intersection;
- provider-description/Skill-body injections cannot change authority;
- screen occurs before scientific frontier/best/retirement;
- fail/debug, inconclusive+infrastructure/uncertified, pass/scientific, and
  tampered/invalid classifications;
- typed node/report serialization and digest validation;
- Evidence Clerk admits only valid dedicated records and reclassifies
  node_report as provenance;
- adversary treats fixed facts as premises;
- ordinary failure never impeaches; false-success/suppression can reach the
  existing validated-attack/governance chain; and
- certify plus independent claim gate are both required for publication.

### Surfaces

- MCP schema snapshot contains only allowed query/request operations;
- every forbidden admin/force-pass operation is absent and invocation denied;
- CLI diagnostic/admin authorization boundaries;
- Dashboard catalogs and terminology remain separate; and
- public API/CLI/MCP contract snapshots updated deliberately.

## 19. Completion criteria

Task 19 is complete when:

1. fixed roles, matrix, constitution amendment, admission order, and resume are
   implemented and proven;
2. the first node cannot execute without all required contracts/locks;
3. AgentLoop has immutable Knowledge use and bound tools;
4. assurance gates the correct BFTS decisions without weighted correctness;
5. dedicated evidence records replace node_report-as-verifier semantics;
6. adversarial/governance distinguish ordinary failure from misconduct;
7. certification and claim-evidence publication gates are independent;
8. no LLM/admin surface can select/rewrite/force an authoritative result;
9. `simple_bfts` bytes remain unchanged; and
10. Task 20 criteria 7–15, 16–52, 55–68 pass in their owning integration suites.

## 20. Deletion criteria

This plan is **not deletable** until implementation is merged, all
constitution/evidence/frontier/publication tests are green, released
checkpoint resume is proven, permanent architecture/runtime/security/CLI docs
contain the normative behavior, Task 20 no longer depends solely on this file,
and INDEX records deletion.

## 21. Delete-after checklist

- [ ] Completion criteria and owned acceptance tests pass.
- [ ] Constitution hash, authority manifest, schema, and complement fixtures agree.
- [ ] First-node and resume ordering proven on integration fixtures.
- [ ] Evidence/adversarial/frontier/publication semantics documented permanently.
- [ ] MCP/CLI/UI authority snapshots retained.
- [ ] INDEX updated in the deletion change.
