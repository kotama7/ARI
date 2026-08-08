# Task 17: Capability Provider Semantics and Binding

> **Status**: in progress · **Depends on**: 01, 04, 12, 16 · **Implementation
> checkpoint**: 2026-08-07 · **This is a temporary task plan** — see
> [INDEX.md](INDEX.md). The semantic facade over `skill.yaml`/`SKILLS.lock`,
> ontology, deterministic Binder, enforcement view, provenance, exact
> ToolUniverse leaf projection/result normalization, frozen dependency-lock
> validation, live substitution diagnostics, and tests have landed. The exact
> upstream 1.3.1 lock remains a failed `candidate`; a distinct metadata-only
> `1.3.1+ari.1` Provider now has a formally human-approved, closed verified
> lock limited to anonymous `PubMed_search_articles`. Exact-scope verified
> locks have also landed for credential-free Qiskit local Aer and two separate
> OpenROAD GCD/Nangate45 profiles: local CPU and anonymous exclusive-node SLURM
> CPU. IBM Quantum Runtime/hardware, OpenROAD GPU, other design/PDK scopes, and
> remote-transport parity remain outside those promotions; no synthetic report
> is substituted.

## 1. Purpose

Introduce the canonical `ARI Capability Provider Federation` vocabulary and a
deterministic, RQGM-independent Capability Binder without replacing ARI's
existing MCP execution stack. The task turns semantic requirements from a
Research Contract or Knowledge Skill into an immutable mapping to concrete
Provider tools, and makes that mapping the sole execution authority in enforce
mode.

The central separation is:

```text
Knowledge Skill says which semantic capability is required.
Provider says which capability it can supply.
Capability Binder proves compatibility and fixes a tool_ref.
MCP transports the invocation.
Provider success is not scientific verification.
```

## 2. Scope

- Canonical Provider names as semantic aliases/facades over
  `SkillManifestV1`, `SkillConfig`, `SkillConnection`, and `SkillsLockV1`.
- A reviewed, versioned Capability Ontology and Provider provision records.
- Provider catalog status, immutable catalog snapshot, registration report,
  source/schema drift detection, and revocation semantics.
- `CapabilityBindingRequestV1`, `CapabilityBindingV1`,
  `CapabilityBindingLockV1`, `CapabilityBindingRevisionV1`, and
  `CapabilityBindingReportV1`.
- A pure deterministic binder and typed `unsatisfied` result.
- Bound visibility and invocation for direct MCP, nested ToolUniverse broker,
  remote MCP transports, existing `ari-skill-*`, SLURM, local process, and
  delegated Claude/Codex CLI paths.
- `legacy`, `audit`, and `enforce` compatibility behavior.

## 3. Non-goals

- No second MCP client, Provider launcher, `tools/list` discovery path,
  credential system, execution request type, or result envelope.
- No reimplementation or vendoring of ToolUniverse.
- No flattening of the ToolUniverse catalog into thousands of agent-visible
  tools.
- No automatic Provider install/update from a branch, tag, package `latest`,
  or network search during a run.
- No fuzzy capability classification, tool-name substring binding, or LLM
  fallback.
- No `provider.yaml`, `PROVIDERS.lock`, mass `ari-skill-*` rename, or second
  schema source.
- No Harness selection or verdict authority.
- No production implementation under `ari.rqgm.evaluation`.

## 4. Current state and formal correction

The following branch behavior is the compatibility baseline:

- `skill_manifest.py` validates executable stdio entrypoints, tool policies,
  side effects, environment and credential scopes, permissions, result schema,
  determinism, phases, and timeouts.
- `SKILLS.lock` binds declarations to live `tools/list` input/output schemas
  and Provider identities and is immutable on resume.
- `MCPClient` creates fully qualified tool refs, rejects collisions, and
  retains unique bare-name aliases for legacy callers.
- `MCPClient.list_tools` filters by phase, call context, and user-disabled
  tools, but has no semantic Binding Lock.
- `CapabilityGatedMCPClient` currently maps tool-name substrings to a small RQGM
  resource matrix; unknown names pass through ungoverned and installation
  failure is fail-open.
- `MCPClient.to_claude_mcp_config` and `secure_stdio_proxy` carry configuration
  and an allowlist into delegated CLI agents.
- `ari-skill-tool-registry` already pins ToolUniverse and other source
  distributions in `CATALOG.lock`, normalizes schemas, classifies admission,
  detects drift, and dispatches through a reviewed broker.

The formal design keeps those implementations and changes their meaning:

| Existing object | New canonical API | Source of truth rule |
|---|---|---|
| `SkillManifestV1` | `ari.providers.CapabilityProviderManifest` | Same class object and `skill.yaml`; no copy. |
| `SkillConfig` | `CapabilityProviderConfig` | Same configuration instance. |
| `SkillConnection` | `MCPProviderConnection` | Same connection/runtime; new transports implement its protocol. |
| `SkillsLockV1` / `SKILLS.lock` | `ProviderLock` | Same bytes and resume semantics. |
| tool-registry `CatalogLockV1` | nested federation source lock | Referenced by the Provider snapshot; never duplicated into `SKILLS.lock`. |

The old Python names remain compatibility imports and the old file/package
names remain stable. New public documentation and UI always call them
Capability Providers.

## 5. Provider data model

### 5.1 `CapabilityProviderIdentity`

The immutable semantic view contains:

```text
provider_id
package
package_version
source_repository
source_full_commit_sha
package_sha256
entrypoint_or_transport
manifest_sha256
environment_policy_digest
credential_scope_identities
tool_refs
input_schema_sha256_by_tool
output_schema_sha256_by_tool
tool_policy_digest_by_tool
capability_provisions_by_tool
provider_status
provider_registration_report_digest
provider_lock_digest
nested_source_lock_digests
```

It is derived from the existing manifest/lock plus reviewed Provider catalog
metadata. It cannot launch a Provider and is not another manifest.

### 5.2 Provider catalog

`ari-core/config/providers/catalog.yaml` and `builtin/*.yaml` register Provider
identity references, status, maintainer, source/license information, and the
explicit capability-provision mapping. They refer to existing `skill.yaml`
manifests by full digest; they do not repeat entrypoint/tool declarations.

Provider status is `candidate | verified | deprecated | revoked`, with the
same transition rules as Task 16's Knowledge catalog. Active use is derived
from the Provider Lock and Binding Lock. Revocation is terminal for new locks
and append-only taint for old records.

`ProviderCatalogSnapshotV1` contains sorted Provider identities, catalog
revision/digest, each referenced manifest and registration-report digest, the
current ontology digest, the existing `SKILLS.lock` digest, every nested
`CATALOG.lock` digest, and its own full SHA-256. It is a run-frozen semantic
projection, not a launch configuration.

## 6. Capability Ontology

### 6.1 Canonical refs

Initial contracts include:

```text
ari.code.inspect/v1
ari.code.edit/v1
ari.execution.compile/v1
ari.execution.run/v1
ari.execution.benchmark/v1
ari.execution.slurm-submit/v1
ari.literature.search/v1
ari.profiling.hardware-counters/v1
ari.data.read/v1
ari.result.emit/v1
```

The slash/version is part of the identity. A free-form tag is never sufficient
for binding.

### 6.2 `CapabilityContractV1`

Each immutable contract contains:

- canonical ref and version;
- semantic input fields, units, required/optional semantics, and constraints;
- semantic output fields, units, status/error semantics, and artifact rules;
- side-effect class (`read-only`, `workspace-write`, `scheduler-submit`,
  `external-write`, `physical-actuation`, or a reviewed extension);
- determinism class and declared nondeterminism fields;
- call-context requirements;
- required permissions and credential-scope class;
- resource type and environment requirements;
- compatibility rules for Provider input/output schemas;
- deprecation/replacement metadata; and
- canonical full digest.

Two tools declaring the same ref are not equivalent until their schemas and
policies pass this contract.

### 6.3 Other ontology types

`CapabilityRequirementV1` carries the ref, required/optional state, semantic
constraints, role/phase/context, side-effect ceiling, permitted credential
scopes, environment/resource constraints, explicit Provider pin, and source
provenance.

`CapabilityProvisionV1` carries Provider/tool refs, contract ref and digest,
schema compatibility evidence, side effects, determinism, context,
permissions, credentials, resources, reproducibility grade, declared cost, and
registration report reference.

`CapabilityOntologySnapshotV1` freezes sorted contracts, explicit legacy alias
rules, property vocabulary version, source revision, and full digest.

### 6.4 Legacy capability tags

Current manifests use unversioned dotted tags and the current validator does
not accept `/`. Migration is explicit:

1. A reviewed table maps each known existing tag to exactly one canonical
   contract, for example `ari.execution.shell` to the reviewed run/process
   contract selected for that tool. The actual table is checked into
   `config/capabilities/legacy_aliases.yaml`.
2. Provider snapshots retain both `declared_capability_ref` and normalized
   `capability_ref`, plus the alias-table digest.
3. The manifest validator is extended to accept canonical versioned refs for
   new declarations without requiring edits to existing manifests.
4. No algorithm appends `/v1`, matches substrings, consults descriptions, or
   maps an unknown tag. Unknown tags are audit findings and are ineligible in
   enforce mode.
5. Prior `SKILLS.lock` and `tool_ref` identities remain unchanged; normalization
   is an additive semantic projection.

## 7. Provider adapters and federation

All adapters normalize into the existing MCP/runtime call and result contracts:

| Adapter | Definitive implementation |
|---|---|
| local MCP stdio | existing `SkillConnection` and `MCPClient`; no change of transport semantics |
| external MCP stdio | existing child-environment/secure-stdio controls plus pinned executable/package/source identity |
| external MCP HTTP or supported remote transport | a transport implementation behind `MCPProviderConnectionProtocol`, using the repository's MCP SDK and the same discovery/lock builder; no parallel client API |
| ToolUniverse | existing `ari-skill-tool-registry` source/provider/catalog/admission/broker implementation and pinned `CATALOG.lock` |
| SLURM | existing `ari-skill-hpc` typed job lifecycle and execution identity; classified as `ari.execution.slurm-submit/v1` provisions |
| local process | existing `ari-skill-coding`/execution contracts and closed-workspace policies |
| instruments/laboratory APIs | remote Provider adapter with physical-actuation side effect, explicit credentials/network/resource policy, and human admission; never auto-enabled |

ARI owns manifest normalization, source/version pinning, admission, credential
scope, live discovery, capability classification, lock, binding, result
normalization, and provenance. The upstream framework continues to own its
scientific operations.

Physical scheduler topology is never Provider catalog content. Cluster,
partition, and node selectors are runtime-only values in a Git-ignored site
configuration protected by a 256-bit nonce. Provider manifests, snapshots,
locks, evidence, fixtures, documentation, and test fixtures persist only the
salted full SHA-256 site identity. Registration and promotion fail closed if the
private configuration is Git-tracked or non-ignored, or if any tracked or
non-ignored candidate file exposes a clear selector or nonce. Resume resolves
the digest against the same operator-supplied private site configuration; it
does not recover or substitute a node name from tracked data.
The repository gate additionally inspects staged blob bytes, filenames, and
symlink targets, so a sanitized worktree cannot conceal an already-staged
selector. The configured promotion checkout runs this gate through
`.githooks/pre-commit`; diagnostics identify only the field class and never echo
the private value.

### 7.1 ToolUniverse composite binding

The outer Provider in `SKILLS.lock` exposes broker operations such as
`discover`, `describe`, `invoke`, `get_status`, and `get_result`. Leaf tools
are pinned in the nested `CATALOG.lock`. A leaf binding therefore stores:

```text
subject_provider_ref     # ToolUniverse source identity
subject_tool_ref         # exact leaf in CATALOG.lock
subject_schema_digests
nested_catalog_lock_digest
dispatch_provider_ref    # ari-skill-tool-registry outer provider
dispatch_tool_ref        # exact broker invoke operation in SKILLS.lock
dispatch_schema_digests
fixed_route_arguments
```

The agent sees only the semantic bound leaf facade. Runtime translates it to
the fixed broker route; the model cannot replace `subject_tool_ref` or discover
an unbound leaf at invocation time. ToolUniverse Knowledge collections use a
separate Knowledge URI, digest, import report, and lock.

The generic contracts currently private to `ari-skill-tool-registry`
(`CanonicalToolDescriptorV1`, source identity, catalog/admission interfaces)
move to the single semantic owner `ari.providers`; the package retains
compatibility re-exports. Its launch/broker code remains in the package.

## 8. Fixed Capability Binder

### 8.1 Contracts

`CapabilityBindingRequestV1` contains Research Contract, Knowledge lock,
ontology snapshot, Provider catalog snapshot/lock, role, phase, call context,
environment, user-disabled tools, explicit pins, and all source digests.

Each `CapabilityBindingV1` records:

```text
capability_ref and capability_contract_digest
requirement_digest and source requirement refs
provider_identity_digest and provider_status
tool_ref (plus composite route fields when nested)
provider_lock_digest and manifest_digest
input/output schema digests and policy digest
role / phase / call-context constraints
side-effect and credential-scope decision
environment feasibility evidence
determinism / reproducibility / cost rank fields
selection rank tuple and tie-break reason
```

`CapabilityBindingLockV1` stores sorted requirements, exact bindings,
`unsatisfied` requirements, every input snapshot/environment digest, mode,
producer `capability_binder_v1`, `prompt_hash: null`, and its own full digest.

`CapabilityBindingRevisionV1` is append-only with `parent_lock_digest`,
`baseline_lock_digest`, added requirements/bindings, next epoch, and digest.
It cannot delete/change a baseline binding. Rebinding an existing capability
requires a new run because provider substitution changes execution authority;
a revision may add only a new capability or a stronger constraint fulfilled by
the same pinned tool.

`CapabilityBindingReportV1` records all rejected candidates and stable reason
codes without copying credentials or secrets.

### 8.2 Eligibility

A candidate is eligible only if all are true:

1. exact canonical `capability_ref` and compatible contract digest;
2. Provider status is verified and not revoked/deprecated;
3. Provider and tool exist in the frozen Provider Lock;
4. explicit Provider/tool pin, when present, matches exactly;
5. role authority permits the capability and operation;
6. phase policy permits it;
7. call-context requirements are satisfied;
8. side effect is at or below the Knowledge/Research authority ceiling;
9. no forbidden capability matches;
10. credential scopes are a subset of the signed call context;
11. environment, transport, resource, and network requirements are satisfied;
12. live input/output schema digests equal Provider Lock;
13. provision schemas conform to the semantic Capability Contract; and
14. nested routes bind both subject and dispatch locks.

### 8.3 Deterministic selection

Requirements sort by `(required desc, capability_ref, requirement_digest)`.
Pins are hard constraints. Eligible candidates sort by this total key:

```text
(
  contract_compatibility_rank,
  provider_verified_rank,
  role_phase_context_specificity_rank,
  side_effect_rank,
  determinism_rank,
  reproducibility_rank,
  environment_feasibility_rank,
  declared_resource_cost_canonical_tuple,
  fully_qualified_tool_ref
)
```

Lower is better and every enum/rank is frozen in the ontology snapshot. The
first entry wins. The resolver never reads the wall clock, network, LLM, live
catalog, or unpinned environment values. The canonical output is byte-identical
for identical inputs.

No eligible candidate produces typed `unsatisfied` with all stable rejection
codes. It never chooses by name similarity, description, bare tool name,
provider order, environment discovery after admission, or model preference.

## 9. Runtime enforcement and visibility

The exact surface is:

```text
visible_tools
=
Provider Lock tools
∩ active Capability Binding Lock
∩ role authority
∩ phase policy
∩ signed call context
∩ complement(user.disabled_tools)
```

Skill body text has no effect on this set. A single bound-provider facade is
installed at the current `MCPClient` choke point and preserves call context,
copy-on-write node IDs, standard result envelopes, close behavior, and
delegated CLI conversion. The definitive implementation adds an optional
`ToolAuthorizationViewProtocol` to the existing `ari.protocols.mcp` surface;
`ari.capability_binding` constructs and injects the view, while `ari.mcp`
imports only the protocol and never the binding implementation. This is not a
second MCP client or discovery cache. `None` selects exact legacy behavior.
The existing RQGM `CapabilityGatedMCPClient` remains the outer constitutional
audit/denial adapter and consumes the semantic decision in audit/enforce
instead of inferring it from the name. A missing/failed authorization view is
a run-admission error in enforce mode, never the current fail-open install
fallback.

- In-process `list_tools` returns only the intersection.
- In-process `call_tool` rejects a missing/changed binding before dispatch.
- `to_claude_mcp_config` supplies only Providers needed by bound tools and the
  same exact allowlist to `secure_stdio_proxy`.
- Nested broker dispatch validates subject and dispatch refs/digests again.
- A returned Provider result is normalized through existing
  `ResultEnvelopeV1`/artifact references and recorded as execution provenance,
  never as a Harness Attestation.

The current substring `default_tool_policy` remains only under
`capability_binding.legacy`. In `audit`, it may continue dispatch but the new
binder records `unbound`, `unmapped`, drift, and authority differences. In
`enforce`, the semantic binding path replaces substring inference and unknown
passthrough.

RQGM enforce fails closed on undeclared/missing capability, unregistered
contract, missing Provider manifest/lock, schema drift, unclassified side
effect/credential scope, unknown tool ref, missing binding, revoked Provider,
or environment mismatch.

## 10. Provider registration and promotion

Only authenticated admin CLI or a reviewed PR can register or transition a
Provider. Research-node MCP has no corresponding operation. Verified promotion
requires all of:

1. manifest schema validity;
2. pinned source/package/full digest;
3. live `tools/list` parity;
4. fixed input/output schema digests;
5. Capability Contract conformance;
6. side-effect declaration tests;
7. credential-scope tests;
8. exact environment allowlist tests;
9. timeout, cancellation, and process-group kill tests;
10. result schema/envelope conformance;
11. malicious description fixture containment;
12. path/workspace isolation;
13. revocation behavior;
14. schema drift detection; and
15. unbound invocation rejection.

`ari provider validate-registration` produces a
`CapabilityProviderRegistrationReportV1`; only a complete passing report can
back a human promotion. Candidate registration never changes an existing run
snapshot or lock.

## 11. Failure and security semantics

Stable typed errors distinguish `unsatisfied`, `provider_unavailable`,
`provider_drift`, `schema_mismatch`, `authority_denied`,
`credential_scope_denied`, `environment_mismatch`, `timeout`,
`transport_error`, and `provider_result_error`. No one is converted to a
scientific `fail` verdict.

Security requirements are exact environment allowlist, credential isolation,
secret redaction, full source/package/manifest/schema pins, network/workspace
policy, timeout/resource/process-group controls, unbound-tool rejection,
registry-write denial, untrusted descriptions, collision/squatting checks, and
external drift detection.

A Provider that also hosts a Harness operation is still only an execution
substrate. The trusted fixed verifier must select it from the Harness Lock,
invoke it outside agent tool choice, bind its result to the target, validate
the result schema, and mint the Attestation. The Provider itself cannot issue
an authoritative verdict.

## 12. Migration and resume

- Public canonical aliases are added in `ari.providers` without changing
  serialized class names or existing import behavior.
- `skill.yaml`, `SKILLS.lock`, Provider IDs, and tool refs remain byte-stable.
- Existing direct Providers gain reviewed catalog/ontology projection entries;
  their manifests are not bulk rewritten.
- The explicit capability alias table is snapshot-bound. Changing it creates a
  new Provider/ontology snapshot and never changes prior bindings.
- Binding audit/enforce is forbidden on a pre-Task-17 checkpoint unless a
  baseline Binding Lock was already persisted. A new run is required.
- Resume verifies Provider and live schema identity against the persisted lock;
  it does not update, rediscover into a new lock, or substitute a Provider.
- `simple_bfts + legacy` bypasses `ari.providers` and
  `ari.capability_binding` imports at runtime and preserves the old tool
  surface.

## 13. Planned files and APIs

```text
ari-core/ari/providers/
├── __init__.py
├── models.py             # aliases and derived identities, no launch schema copy
├── compatibility.py      # legacy names/ref mapping diagnostics
├── catalog.py
└── registration.py

ari-core/ari/capability_binding/
├── __init__.py
├── ontology.py
├── models.py
├── resolver.py
├── lock.py
└── validation.py

ari-core/ari/public/providers.py
ari-core/ari/public/capability_binding.py
ari-core/ari/protocols/provider.py
ari-core/config/providers/
ari-core/config/capabilities/
```

Existing files changed during implementation are `skill_manifest.py`,
`skill_lock.py`, `config/skill_runtime.py`, `mcp/{client,connection,
registry_runtime,dispatch_support,lock_runtime,invoke_runtime,
child_environment,secure_stdio_proxy,claude_bridge}.py`,
`protocols/mcp.py`, `rqgm/{tool_policy,kernel}.py`, `agent/{tool_manager,
workflow,loop}.py`, `llm/cli_server.py`, `prompts/llm/mcp_name_resolution.md`,
`viz/api_capabilities.py`, and the tool-registry compatibility seams.

Public calls are read-only `search_providers`, `describe_provider`,
`show_provider_lock`, `show_capability_bindings`, and pure validation/resolution
APIs. Admin transitions are not public LLM tools.

## 14. Tests

### Unit and contract tests

- `test_capability_contract_rejects_free_form_or_incompatible_semantics`
- `test_legacy_capability_aliases_are_explicit_and_snapshot_bound`
- `test_provider_aliases_reuse_skill_classes_and_lock_bytes`
- `test_provider_registration_checks_all_fifteen_gates`
- `test_provider_schema_and_manifest_drift_invalidates_binding`
- `test_binding_filters_role_phase_context_side_effect_credentials`
- `test_binding_exact_pin_is_a_hard_constraint`
- `test_binding_lock_is_byte_identical_for_permuted_input_order`
- `test_unknown_capability_has_no_substring_or_llm_fallback`
- `test_binding_revision_adds_but_never_rebinds_or_deletes`
- `test_provider_description_cannot_expand_authority`
- `test_revoked_provider_excluded_from_new_lock_without_rewriting_history`

### Integration tests

- direct local stdio Provider discovery → existing `SKILLS.lock` → semantic
  Binding Lock → call result;
- ToolUniverse composite subject/dispatch binding with both lock digests and
  refusal of a substituted leaf;
- remote transport parity with the same Provider identity and schema lock;
- SLURM typed job invocation with signed call context and credential subset;
- in-process and delegated CLI visible-tool lists are identical;
- unbound invocation succeeds with an audit record in audit mode and is denied
  in enforce mode;
- resume refuses current Provider/schema/catalog substitution; and
- `simple_bfts + legacy` contract snapshots, prompts, and tool lists are
  byte-identical.

### 14.1 Implementation evidence checkpoint (2026-08-04)

- ToolUniverse 1.3.1 is pinned to repository commit
  `9b7ff91ddb45b567cac2fa8ea31b82851e877617`, wheel SHA-256
  `a201a8793a0eaa30a085417b07ec4bffaccc4d955f9754dd122914991d0d59c0`,
  and upstream `uv.lock` SHA-256
  `66be0854d1a508c1a0940f0d56e0c485e31fe33cca09c1b99766ee7bc17ac953`.
- The exact `PubMed_search_articles` leaf was discovered and invoked against
  the live PubMed service. Its reviewed normalizer emitted two
  `ari.retrieval-result/v1` records; a separate live `web-skill` arXiv call
  emitted the same semantic result schema. Tool names and descriptions were
  excluded from binding authority.
- `CapabilityProviderSubstitutionReportV1` re-ran the production Binder twice,
  produced byte-identical decisions, retained both operation observations, and
  rejected ToolUniverse binding with `provider_not_verified`. Its diagnostic
  report digest was
  `sha256:ed7613203c4bff6ac4f58fdfb8505bba9312155ca4006f5db58aea9c07dd92ef`.
- A full environment built from the exact upstream lock fails before compact
  MCP initialization on both Python 3.12 and 3.13: the locked
  `pathlib==1.0.1` imports removed `collections.Sequence`. The partial probe
  environment is therefore operation evidence only; it cannot promote the
  Provider or satisfy an enforce-mode Binding Lock.
- At that checkpoint, remote MCP transport parity and an authenticated
  ToolUniverse promotion report were external gates. No fallback Provider was
  inserted into the production catalog by the diagnostic. Section 14.2 records
  the later resolution for the distinct, anonymous PubMed-only Provider; remote
  transport and every other ToolUniverse leaf remain outside that promotion.

### 14.2 Verified PubMed Provider checkpoint (2026-08-05)

- ARI minted the distinct Provider artifact `tooluniverse-pubmed@1.3.1+ari.1`.
  Its metadata-only patch replaces the erroneous `fitz>=0.0.1.dev2` dependency
  with `PyMuPDF==1.26.4`; ToolUniverse source files are unchanged. Two controlled
  builds produced byte-identical wheel
  `sha256:c976866f024d1c77ee476dc1855940949282ea19fd7227349061eaa0fe1d1b7d`.
- The checked-in runtime lock
  `sha256:dbcc593aeb7fdf14195fb08df68377f23c6df71dbdb3a7a601b920a57c668fec`
  closes 158 packages for CPython 3.13 linux-x86_64, contains PyMuPDF 1.26.4,
  excludes `fitz`, `pyxnat`, and `pathlib`, and passes `pip check`.
- The promotion command executed the live compact MCP surface, an exact
  `PubMed_search_articles` discovery and anonymous PMID query, result
  normalization, Capability-contract comparison, ten registration tests, an
  unbound-leaf rejection, and a real descendant process-group timeout test.
- `registration-evidence-v1.json`, the exact fifteen-gate
  `registration-report-v1.json`, and the explicit human-maintainer
  `promotion-approval-v1.json` are bound into `verified-lock-v1.json` digest
  `sha256:c85e73726b1182c3fe88b682a8bcd0e0d7a57713f7ecb1818056886eaa5442bf`.
  The promotion approval digest is
  `sha256:9317c4ff7e15f488f758fc253b9afd96345abd6d3730405f5669c93a6eabc608`.
  Both digests record this checkpoint and are superseded by the 2026-08-07
  re-promotion in §14.6, which also normalized the leaf identity; the scope
  statements here still hold.
  The lock binds the Provider artifact/manifest, adapter and result projection,
  leaf and schema digests, current Capability contract, runtime target, and
  credential-free scope. Status-only promotion, missing or mutated human
  approval, evidence mutation, scope expansion, schema drift, and revoked-lock
  reuse fail closed.
- This checkpoint does not promote the unmodified upstream artifact, any other
  ToolUniverse leaf, a keyed PubMed variant, or a remote MCP transport. Those
  require distinct identity and registration evidence.
- The default Tool Registry admission vocabulary now admits the ontology's
  exact `network-read` permission. An environment-specific sync from this
  verified artifact produces one `callable` leaf, and an anonymous invocation
  through that generated `CATALOG.lock` returns one normalized
  `ari.retrieval-result/v1` record. The repository's default `CATALOG.lock`
  remains empty and was re-pinned only to the new policy digest.
- After explicit maintainer promotion, the closed environment was synchronized
  again. It produced one-tool catalog digest
  `sha256:73e1225dc30b4cfc735858bad4615e08da6723a0f0ced6dd560897d7db3551ff`
  with admission `callable`, `provider_status: verified`, and exact tool ref
  `ari-tool://tooluniverse-pubmed/tooluniverse%3APubMed_search_articles@sha256:0d6249281717b3751c3410dda751bf3ab91ffd85a9117330174d8f1815f3676d`.
  This environment-specific catalog is evidence, not a portable repository
  default; activation still mints a run-specific lock and never mutates resume.
  It was generated before the leaf-identity normalization in §14.6, so its
  catalog and tool-ref digests also belong to this checkpoint.

### 14.3 Verified Qiskit local-Aer Provider checkpoint (2026-08-05)

- The checked-in bundle
  `providers/qiskit/core-0.3.1+aer-0.17.2-local-ideal/` binds Qiskit MCP 0.3.1,
  Qiskit 2.5.1, Aer 0.17.2, one Bell-state QPY, target, seeds, 4,096 shots,
  golden/replay files, live MCP schemas, and the exact virtual leaf
  `ari_qiskit_sample__local_ideal`.
- The live closed run produced counts `00: 2046` and `11: 2050`, rejected an
  unbound invocation, and retained the input/transpiled QPY, raw Aer result,
  and execution transcript by full digest. All fifteen Provider registration
  gates passed.
- Human approval digest
  `sha256:5128140e15e563ceb5827187a1a3ee1630bb0606594d2ae9a60abd1eb2b80a5c`
  authorizes only `ari.quantum.sample.local-ideal/v1`; the verified lock digest
  is
  `sha256:0407982946540409fc37193bd86130d72f86fc1c1447d581ee39dca1da19f220`.
  Both digests are those of the 2026-08-07 re-promotion in §14.6; this exact
  scope is unchanged.
  IBM Runtime, remote simulator, IBM hardware, credentials, and any other
  circuit/profile are outside the lock. They remain candidate until separately
  pinned backend/configuration/calibration identity and backend-bound live
  golden/replay evidence receive human approval.

### 14.4 Verified OpenROAD local-CPU Provider checkpoint (2026-08-05)

- The checked-in bundle
  `providers/openroad/0.6.1+orfs-26q3-gcd-nangate45/` binds OpenROAD MCP 0.6.1,
  ORFS commit `adeb389e7fbf06ef6a939a895c014f69e6f7aa00`, OpenROAD commit
  `7304ba78ade7cb9f78466c6d0231432d72dadd3b`, the exact GCD placed database,
  Nangate45 PDK/library, x86_64 one-thread local-MCP execution, workspace,
  command sequence, live schemas, and golden/replay files.
- The closed Provider run reported zero route DRC errors, 3,603 µm route
  wirelength, and 3,361 vias, then rejected an unbound invocation. The
  independent official ORFS runner produced the pinned final artifact set and
  an empty DRC report. Because its fixed binary raised SIGILL during default CTS
  timing repair, that reference used `SKIP_CTS_REPAIR_TIMING=1` and is recorded
  as an independent reference pass, not full default-flow parity.
- Human approval digest
  `sha256:a9cc1c3cd0d4816d0d672e6726f81b4ae8a554069fa325e84aaf4ca1c10dde47`
  authorizes only `ari.eda.openroad.place-route/v1`; the verified lock digest is
  `sha256:ecd7cc79542acfcfa177186d3bbe154678f1a378454834b6276efb1383eeab28`.
  Both digests record this checkpoint and are superseded by the 2026-08-07
  re-promotion in §14.6; the scope statements below still hold.
  The 1.54 GB SIF remains an external retained artifact, while its OCI, SIF,
  and inner-binary full digests are locked. SLURM, GPU, another design/PDK,
  corner, toolchain, full default-flow parity, or image is explicitly outside
  this identity and is not an unresolved completion condition for its
  promotion. Each broader scope requires a separately named candidate,
  evidence bundle, human approval, and verified lock.
- Every exact-scope promotion changes governed eligibility only. The repository
  default `CATALOG.lock` remains empty; activation requires an
  installation-specific Provider snapshot and run-frozen Capability Binding
  Lock.

### 14.5 Verified OpenROAD anonymous-SLURM-CPU checkpoint (2026-08-05)

- The independent checked-in bundle
  `providers/openroad/0.6.1+orfs-26q3-gcd-nangate45-slurm-cpu/` binds the same
  GCD/Nangate45 scientific profile to one anonymous exclusive-node SLURM CPU
  allocation. It requests zero GPUs and therefore grants no GPU authority.
- Clear cluster, partition, and node selectors exist only in the ignored
  runtime site configuration. That file requires a 256-bit nonce. The tracked
  scheduler snapshot, manifest, evidence, fixtures, and lock contain only the
  salted full SHA-256 `site_identity_digest`; a pre/post-promotion Git
  candidate scan plus the repository pre-commit staged-blob scan fail closed on
  a clear selector, nonce, trackable site file, filename, or symlink target.
- The execution identity fixes SLURM controller-client digests, a
  PRoot 5.3.1 binary and source commit, unsquashfs 4.6.1, the retained ORFS
  SIF, its inner OpenROAD binary, and worker Python. The runtime-owned Tcl
  explicitly opens and closes the metrics sink. Where the scheduler has no
  accounting storage, terminal status additionally requires a
  nonce-bound fixed-wrapper completion record; a missing or forged record
  remains `unknown`. That PRoot closure records this checkpoint; §14.7
  re-promotes the same scientific scope on the digest-pinned container this
  profile now declares.
- The live run produced zero route DRC errors, 3,603 µm wirelength, and 3,361
  vias. Submission, wrapper completion, environment, exit code, scheduler
  stdout/stderr, DRC report, metrics, DEF, netlist, and transcript were captured
  by full digest. All fifteen Provider registration gates and the independent
  ORFS reference check passed.
- Human approval digest
  `sha256:b7e25187d93861531311e79a3a1c06eb3905e82005634d75f89ff14ca5c95f97`
  authorizes only this exact CPU scope. The verified lock digest is
  `sha256:a28d59fe22395717075be9def98469bb49335d28dc539ff5b597aa04a7c81893`.
  Both digests are those of the 2026-08-07 re-promotion in §14.6.
  GPU use, another design/PDK/corner, another scheduler site, a changed runtime,
  or full default-flow parity requires a new candidate and independent lock.

### 14.6 Portability re-promotion checkpoint (2026-08-07)

Materializing §14.2–§14.5 in a second environment showed that several locked
identities were bound to the promoting host rather than to the reviewed
artifact, and that one reviewed execution substrate could not run there at all.
All four bundles were re-promoted. The scientific scope of each is unchanged;
the only capability-scope difference is the substrate the SLURM profile pins.

- **Retained SIF digests are irreproducible by construction.** A SIF header
  carries a random UUID and a wall-clock creation time inside the hashed file,
  so no container runtime reproduces `retained_sif_digest`. The pinned OCI
  manifest and inner OpenROAD binary digest did match exactly, so the payload
  was proven identical while the envelope could not be. `openroad-support-v1.json`
  now records the locally materialized SIF and its `singularity` runtime, and the
  bundle was re-promoted: lock
  `sha256:22bebd225e7876414d724c8f560c0906acd7f2f45c94b86408e71d1bc34bffc9`,
  approval `sha256:31175d3941ab7a3ad7eef6891fa378ee0cadf75830153a2d763be8ed56811498`.
  All six workspace inputs, including the independently regenerated
  `3_place.odb`, reproduced bit-for-bit, and `gcd-nangate45-26q3.golden.json`
  was rewritten byte-identical.
- **`tool_spec_digest` pinned the install path, not the leaf.** ToolUniverse
  reports `source_file` as an absolute installation path; it reached both leaf
  metadata and the digest, so the same reviewed wheel produced a different leaf
  identity per machine and the promoting host's paths were written into
  promotion evidence. `tooluniverse_adapter` now expresses `source_file`
  relative to the reviewed package before digesting, and replaces paths outside
  it rather than disclosing them. The PubMed bundle was re-promoted: lock
  `sha256:33789b5a02f45bcdb925e8a2ff79a23866674561ad43b4ac51df5d1996f08f21`,
  approval `sha256:cd25f1d282dede6a4273088370a8336be401ab09a1b4eda280d540b07a627f9d`.
- **Verified locks are invalidated by unrelated in-repo change.**
  `openroad_adapter_digest` binds the `ari-skill-hpc` job contract, and
  `tooluniverse_adapter_digest` binds `sources.py` and the support matrix. A
  concurrent `ari-skill-hpc` commit and an edit to either file are each enough
  to make a checked-in lock fail closed, so both re-promotions were required
  before the suite returned green.

### 14.7 Exactly one pinned execution substrate (2026-08-07)

- **The SLURM profile pins a container, not the PRoot closure.** The reviewed
  PRoot/unsquashfs/worker-Python build links against a newer host glibc than the
  promoting site provides, so the §14.5 profile now carries
  `ContainerRequestV1(runtime="singularity", gpu=false, network="none",
  contain_all=true, clean_environment=true)` instead of
  `OpenRoadPortableRuntimeV1`. Isolation is stronger, not weaker: the closure is
  the SIF alone rather than the SIF plus four host binaries. The re-materialized
  image is `sha256:b8af5db8db5feb98720faf0959f6d3d478aac89f41cc9ad9d385467800c6580c`,
  1,540,308,992 bytes, under `singularity` 4.5.0-1.el9.
- **Both substrates stay admitted; exactly one may be present.** The execution
  contract still accepts the reviewed PRoot/SIF portable runtime, and
  `openroad_verified_artifact` still verifies its bytes. Which substrate a
  profile pins is a site property; that a scheduler profile pins exactly one of
  `portable_runtime` and `container` is the invariant, and a profile declaring
  both or neither is rejected by the execution contract.
- **Environment requirements and runtime target are derived from the profile.**
  The SLURM `environment_requirements` are computed as `cpu`, `exclusive-node`,
  `slurm`, plus `proot-sif` or `<runtime>-sif`, so a container run cannot
  advertise a PRoot requirement; the promoted lock lists `cpu`,
  `exclusive-node`, `singularity-sif`, `slurm`. `runtime_target` follows the same
  declaration: `worker_python` is `container-provided` rather than
  `CPython-3.12`, `execution_substrate` is `singularity-sif` rather than
  `proot-sif`, and `network` is `isolated` rather than `host-uncredentialed`
  because the container declares `network: none`.
- **Scheduler-snapshot verification is site-portable.** The promotion compares
  the live controller against the values *declared in the reviewed snapshot* —
  SLURM version, GRES types, partition `MaxTime`, node architecture, `CPUTot`,
  `Sockets`, `ThreadsPerCore` — and against the operator's private site
  configuration for the selectors that never enter the repository, instead of
  against literals. A short set of invariants that are not site characteristics
  is asserted separately: `Arch=x86_64`, `Gres=(null)`, and
  `OverSubscribe=EXCLUSIVE`. A snapshot claiming GPU authority is refused
  outright. The same promotion can therefore run at another scheduler site, and
  drift between the snapshot and the live controller still fails closed.
- **The GPU limitation is read from the snapshot, not asserted everywhere.** A
  scheduler that declares no GRES types cannot express a GPU request at all; a
  scheduler that does declare them can, so the guarantee then rests on the
  allocated node exposing no accelerator. The promoted limitation text is
  selected from the reviewed snapshot. Either way the profile requests zero GPUs
  and grants no GPU capability.
- **Terminal state comes from whichever authority the site actually has.** Where
  the scheduler has accounting storage, the state is the scheduler's own
  (`scheduler_state` `COMPLETED`, `exit_code` 0); where it has none, it is the
  nonce-bound fixed-wrapper record (`reason` `fixed-wrapper-completion-v1`).
  Either way the job must have actually succeeded, and the typed job's
  `container_digest` must equal exactly what the profile pins — the image digest
  for a container run, and no container at all for the PRoot run.
- **Remaining promoting-host paths were removed from the bundles.** The
  scheduler handle's `workspace_scope` and `artifact_scope` are recorded relative
  to the declared work root, because the digest-derived scope names are the
  publishable part while the prefix only says which machine ran the promotion; a
  scope escaping the work root is refused. The SLURM bundle's materialized
  profile moved from `workspace/materialized-profile-v1.json` to
  `materialized/materialized-profile-v1.json`: the workspace must stay
  byte-exactly the declared input set for source admission and the materialized
  profile is not one of those inputs, so it keeps its own bundle ignore rule and
  still retains runtime selectors. The local-CPU OpenROAD and Qiskit materialized
  profiles now record bundle-relative `toolchain.executable_path`,
  `workspace.source_root`, `golden_fixture_path`, `replay_fixture_path`, and
  `circuit.qpy_path`; portable experiment identity already excluded them and the
  sole reader re-derives each from the bundle directory.

### 14.8 ToolUniverse collection enumeration (2026-08-07)

- **A second artifact `tooluniverse/1.3.1+ari.2` raises the SMCP response
  ceiling.** It carries the `1.3.1+ari.1` `fitz>=0.0.1.dev2` →
  `PyMuPDF==1.26.4` metadata fix unchanged and additionally replaces the
  `smcp.SMCP` response `max_chars` of `100_000` with `2_000_000` at both
  serialization sites. Unlike `ari.1` it therefore records
  `source_code_changes: true`.
- **Why the ceiling had to move.** Upstream caps every compact MCP response at
  100,000 characters and, when structural trimming cannot fit, falls back to raw
  string truncation that emits invalid JSON. That makes whole-collection
  enumeration impossible: `get_tool_info(detail_level=full)` exceeds the ceiling
  for the largest leaves even at batch size one. Measured over all 2,601 loaded
  leaves the largest single response is 510,904 characters and only two exceed
  100,000, so 2,000,000 admits the worst observed batch with roughly threefold
  headroom while staying well under the 7,103,230-character full-collection
  dump.
- **It is a Provider artifact, not a promotion.** Two controlled builds produced
  byte-identical wheel
  `sha256:5c2e9a254e353e5941d59f8e279dd7c55777eb46c84457f1eefcaef7aa4a60c9`
  from the same upstream commit `9b7ff91ddb45b567cac2fa8ea31b82851e877617`, and
  its manifest declares `PubMed_search_articles` as `ari.literature.search/v1`.
  The bundle carries a build recipe, patch, runtime lock, and manifest; it
  carries no registration evidence, no human approval, and no verified lock.
- **A collection-wide ToolUniverse source carries no leaf promotion.** An
  `ari-patched-wheel` source may now omit `verified_lock_path`. Such a source
  must not assert `evidence.replay_fixture_digest` or
  `evidence.scientific_validation_digest`, because those levels require leaf
  evidence bound to a verified lock; without one the source stays `callable` and
  can reach neither `reproducible` nor `scientifically_admitted`. The retained
  exact wheel is still required in every case.

## 15. Completion criteria

Task 17 is complete when:

1. all Provider aliases are semantic facades over existing implementations;
2. the ontology and explicit legacy mappings are versioned and snapshot-bound;
3. every binding is deterministic, digest-bound, authority-checked, and
   independently replayable;
4. RQGM enforce has no unbound/unknown/substr-inferred passthrough;
5. ToolUniverse, direct MCP, SLURM, local process, remote MCP, and delegated CLI
   use one binding contract;
6. Provider registration gates and malicious-description tests pass;
7. Provider success cannot be admitted as Harness evidence; and
8. Task 20 criteria 4–6, 16–29, 59, 61–65, and 67–68 pass.

## 16. Deletion criteria

This plan is **not deletable** until the implementation is merged, CI and
upstream adapter parity are green, all compatibility/resume fixtures pass,
the Provider terminology/ontology/binding contracts are in permanent docs,
Task 19 and Task 20 no longer depend solely on this file, and INDEX records the
deletion.

## 17. Delete-after checklist

- [ ] Completion criteria and all owned acceptance tests pass.
- [ ] No duplicate MCP client, manifest, lock, or execution envelope exists.
- [ ] `simple_bfts` byte-compatibility and released-checkpoint resume proven.
- [ ] ToolUniverse composite route and external transport parity reports retained.
- [ ] Permanent Provider extension/security docs published.
- [ ] INDEX updated in the deletion change.
