# Task 02: Contracts and Deterministic Compiler Core

> **Status**: implemented — §11 re-checked at HEAD: the determinism/tamper and
> omission-conservation tests are green and both `scripts/sync_manuscript_schemas.py --check`
> and `scripts/snapshot_contracts.py --surface all --check` report the shipped
> schemas and digests in sync.
> **Depends on**: 00, 01
> **Gate**: G1 — contract and compiler determinism
> **Plan type**: temporary sub plan; see [INDEX.md](INDEX.md)

## 1. Purpose

Manuscript Complete の topology-neutral な contract、schema、digest、inventory、requirement
profile、context builder、readiness evaluator を fixed code として実装する。Task 02 は runtime
paper path をまだ変更せず、Task 01 fixture に対して決定論的 artifact を生成する compiler
core を完成させる。

## 2. Scope

- `ari-core/ari/manuscript/` package foundation。
- strict versioned Pydantic/data contracts and JSON schemas。
- canonical serialization and digest binding。
- `generic_empirical_v1` requirement profile。
- internal `ExplorationSnapshotV1` and `SimpleBftsSnapshotProvider`。
- complete inventory and manuscript-specific evidence classification inputs。
- `ManuscriptContextV1`、`OmissionManifestV1`、`ManuscriptReadinessReportV1`。
- applicability rule registry and fixed evaluators。
- no-silent-omission accounting。
- contract fixtures and schema snapshots。

## 3. Non-goals

- CLI/pipelineへ compiler を接続しない。
- writer、paper archive、RQGM runtime を変更しない。
- repair plan executionを実装しない。contract skeletonも Task 07 が owner になる field は
  prematureに固定しない。
- KCA verdictを再計算しない。
- ScienceData `claim_eligible` の意味を変更しない。
- LLMを applicability/readiness evaluatorに使用しない。

## 4. Package and dependency direction

Initial package shape:

```text
ari/manuscript/
  __init__.py
  contracts.py
  digest.py
  profiles.py
  applicability.py
  snapshot.py
  inventory.py
  selection.py
  omissions.py
  builder.py
  readiness.py
```

Dependency rule:

```text
contracts/digest <- profiles/applicability
contracts/digest <- snapshot/inventory/selection/omissions
all above <- builder/readiness
ari.manuscript must not import ari.rqgm or paper skill modules
```

RQGM-specific projection is deferred to Task 05。The core accepts optional typed assurance source
records without knowing RQGM governance internals。

## 5. Contracts

### 5.1 Requirement profile

Implement `ari.manuscript-requirement-profile/v1` with:

- stable requirement IDs。
- applicability rule IDs and evaluator version。
- authoring/publication blocking flags。
- admissible terminal status and resolver kinds。
- evidence kinds and target paper sections。
- profile digest over the fully resolved profile。

Profile composition resolves at read time (`ari.manuscript.profiles`, landed 2026-08-14 in commit
`a76ec75`): a `ManuscriptVenueProfileV1` declaration stores its parents at their pinned digests
plus its own deltas, and resolution yields one ordinary `ManuscriptRequirementProfileV1` that
carries no inheritance fields。`compile_manuscript` materializes exactly that resolved profile as
the attempt artifact `requirement_profile.json` (`ari-core/ari/manuscript/coordinator.py`), which
is the only profile artifact downstream consumers read — via `ARI_MANUSCRIPT_PROFILE_PATH` — so no
consumer reinterprets inheritance order。Every declaration stored on disk must pin
`resolved_profile_digest`。

### 5.2 Source snapshot

`ExplorationSnapshotV1` binds:

- run/checkpoint/research-contract identity。
- all nodes, lineage, status, metrics and report refs。
- source artifact inventory。
- current scientific winner and selection policy digest。
- provenance/ScienceData/retrieval/EAR/figures refs when available。
- optional assurance input block。

The snapshot stores safe relative references and digests, not arbitrary absolute host paths。

### 5.3 Context and omission

`ManuscriptContextV1` implements all content blocks from Task 00 §10.3。Every inventory item is
classified as included in one or more blocks or represented in omission manifest。An item may be
referenced rather than embedded and still count as included if the reference is digest-bound and
readable under the artifact reader contract。

`OmissionManifestV1` uses closed reason enums。Unexpected reasons are errors, not free-form strings。

### 5.4 Readiness

Implement requirement statuses:

- `satisfied`
- `not_applicable`
- `unavailable`
- `missing`

Aggregate authoring/publication verdicts are derived fields and validated against per-requirement
results。Serialized input cannot claim `ready` while containing a blocking `missing`。

## 6. `generic_empirical_v1`

Implement the Task 00 §12 requirement table, including at least:

- research question/hypothesis/falsification。
- method/config/environment/protocol。
- primary metric/unit/direction/run IDs。
- conditional uncertainty/baseline/ablation/comparison parity。
- claim-to-measurement coverage input readiness。
- negative result and selection accounting。
- recorded related work and novelty distinction inputs。
- limitations/threats。
- EAR/reproduction inputs。
- conditional assurance certification requirement。
- omission conservation requirement。

Conditional rules rely on typed claim categories/research contract fields。If required claim
classification does not exist, the evaluator emits `missing` or `human_decision`-eligible status;
it does not infer from untrusted prose。

## 7. Determinism and validation

- Canonical JSON key/list ordering is defined per contract。
- Stable IDs do not include wall-clock time, random UUID, absolute path, or model wording。
- Timestamps are observational metadata excluded from normative digest unless inherited source
  contract requires them。
- Unknown fields、unsafe paths、duplicate IDs、digest mismatch、invalid parent references fail。
- Same source snapshot/profile/evaluator version produces byte-identical outputs。
- Input order permutations that are semantically sets produce the same canonical result。

## 8. Selection behavior

Do not alter legacy `filter_nodes` predicates。Task 02 introduces manuscript-specific inventory and
classification helpers that:

- include all nodes in the inventory。
- separate positive candidate、exploratory、contextual-negative、excluded eligibility inputs。
- preserve scientific winner separately from later publication candidate。
- record why a node/source is not embedded or usable。

Assurance-dependent final lane promotion remains deferred to Task 05; core fixtures may provide a
typed mock source record but not an always-pass certifier。

## 9. Tests

- Contract round-trip and strict validation for every schema。
- Digest golden tests and mutation/tamper tests。
- Duplicate node/requirement/item rejection。
- Safe relative path tests。
- Inventory conservation property tests。
- All omission reason branches。
- All applicability rule branches and admissible `not_applicable` proofs。
- Aggregate readiness coherence tests。
- Large/negative/tamper/legacy fixtures from Task 01。
- No `ari.rqgm` or paper-skill import during core compiler tests。
- No network or LLM needed。

## 10. Expected artifacts

- `ari-core/ari/schemas/manuscript_requirement_profile_v1.schema.json`。
- `ari-core/ari/schemas/manuscript_context_v1.schema.json`。
- `ari-core/ari/schemas/manuscript_omission_manifest_v1.schema.json`。
- `ari-core/ari/schemas/manuscript_readiness_v1.schema.json`。
- schema examples/golden fixtures under existing test conventions。
- internal contract documentation generated or checked against schemas。

Public export through `ari.public.manuscript` follows MC-ADR-005。If deferred, tests must still pin
the internal import path and document that it is not stable public API yet。

## 11. Completion criteria

1. All scoped contracts and schemas exist and reject unknown/invalid input。
2. `generic_empirical_v1` is fully materialized and digest-bound。
3. Simple BFTS fixtures compile without paper/RQGM imports。
4. Same input produces byte-identical context/omission/readiness artifacts。
5. Every inventory item is included or omitted with a typed reason。
6. All requirement statuses and aggregate verdict coherence are executable tests。
7. LLM annotation cannot satisfy a factual requirement。
8. ScienceData and legacy node-selection semantics remain unchanged。
9. Task 01 large/negative/tamper/legacy fixture expectations pass。
10. G1 review records schema/digest versions handed to downstream tasks。

## 12. Deletion criteria

This plan may be deleted only when:

1. Completion criteria are satisfied, merged, and CI green。
2. Every contract is documented in permanent schema/reference docs。
3. Applicability rules and evidence-lane input semantics live in code/tests or permanent docs。
4. Public/internal API status is resolved and documented。
5. Schema migration/versioning policy is permanent。
6. Tasks 03–09 no longer rely on this prose as the only definition of a field or invariant。
7. `INDEX.md` records deletion status and reason。

## 13. Delete-after checklist

- [ ] Contract/schema tests are permanent and green。
- [ ] Canonical digest specification is documented permanently。
- [ ] Generic profile and applicability rules have a permanent reference。
- [ ] Inventory/omission conservation invariant is test-owned。
- [ ] ScienceData separation is documented at the implementation boundary。
- [ ] Public API decision is implemented and recorded。
- [ ] Main merge and CI revision are recorded。
- [ ] Downstream-only prose dependencies have been removed。
- [ ] `INDEX.md` is updated before deletion。

## 14. Handoff

Task 03 receives compiler APIs and fixture artifacts。Task 04 receives readiness aggregate semantics。
Tasks 05–08 extend adapters/coordinator around these contracts but do not mutate V1 meanings; any
incompatible change requires a new schema version。
