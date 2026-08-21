---
sources:
  - path: ari-core/ari/schemas
    role: schema
  - path: ari-core/ari/rqgm
    role: implementation
  - path: ari-core/ari/checkpoint.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/orchestrator/bfts.py
    role: implementation
  - path: ari-core/ari/cli/paper_dispatch.py
    role: implementation
  - path: ari-core/ari/configs/defaults.yaml
    role: config
  - path: ari-skill-paper/src/server.py
    role: implementation
  - path: ari-core/tests/test_rqgm_state_store.py
    role: test
last_verified: 2026-08-16
---

# RQGM Schema Reference

Formal JSON Schemas for every record the opt-in `ari_rqgm` execution mode
persists.  All of them ship under `ari-core/ari/schemas/` and can be loaded
by basename via `ari.schemas.load(name)`.  None of these records exist on a
default `simple_bfts` checkpoint — every reader treats absence as "RQGM
never ran".

These schemas are a **reference contract, not a runtime validator.**  Nothing
under `ari/rqgm/` opens one: `jsonschema` is not an `ari-core` dependency, and
no RQGM writer checks a record against a `.schema.json` file before persisting
it.  The record classes are plain dataclasses that *mirror* the schema files —
`ari/rqgm/proposals/records.py` and `ari/rqgm/adversarial/records.py` use
exactly that word in their module docstrings; no Pydantic model backs them, and
no snapshot test asserts that a shipped schema equals a generated
`model_json_schema()`.  Pydantic `model_validate` *is* used inside
`ari/rqgm/`, but only for the separately gated Knowledge/Capability/Assurance
admission, harness, capability-binding, and manuscript documents (plus the
evaluation harness's own `ARIConfig` overlay in `ari/rqgm/evaluation/smoke.py`)
— never for the `rqgm_record_base` envelope or any record inventoried on this
page.

What the kernel enforces at write time is an envelope + shape check,
`ConstitutionalKernel.validate_record_schema` (`ari/rqgm/kernel.py`): the eight
`kernel_rules.ENVELOPE_FIELDS` must be present, `record_id` / `status` / `role`
must be non-empty when present, and a `proposal_record` additionally runs the
proposal-summary field budgets.  A failure is reported as `CK-SCH-G01` (block)
on the governance record types `epoch_transition` / `governance_report`, as
`CK-SCH-N01` (warn) on any other record type, and a budget overrun as
`CK-SCH-N02` (warn).  The per-field types, formats, and closed enums documented
below are therefore upheld by the writers and by the test suite — several
`ari-core/tests/test_rqgm_*.py` modules validate real records against these
schema files, though they reach for `jsonschema` through `pytest.importorskip`
and skip when it is absent — and not by any validation at persist time.

This page documents the **record shapes** (purpose, owning module, key
fields, id/hash discipline).  For the checkpoint **files** those records
live in — creation conditions, source-of-truth vs derived-snapshot
relationships, resume semantics — see
[File Formats Reference](file_formats.md); the
[inventory table](#checkpoint-file-inventory) at the end of this page maps
each file to its schema.  For the config knobs see
[Configuration → Execution mode and RQGM](configuration.md#execution-mode-and-rqgm-governance-opt-in);
for the mode semantics see
[Execution Modes](../guides/execution_modes.md).

## Id and hash discipline

One module owns every RQGM id and hash format:
`ari-core/ari/rqgm/events.py` (RQGM Task 02).  All hashing follows design
principle P2 (determinism): no wall clock, git SHA, hostname, or absolute
path ever enters a hash.

- **`canonical_json(payload)`** — the single canonical JSON form every
  RQGM hash is computed over: sorted keys, no whitespace,
  `ensure_ascii=False` (byte-golden-pinned by tests).
- **`hash12`** — `sha256(text)[:12]`, reused verbatim from
  `ari.prompts._provenance.hash12` (the exact
  `FilesystemPromptLoader.load_versioned` prompt-provenance scheme; no
  second scheme exists).  Schema pattern: `^[0-9a-f]{12}$`.
- **`sha256_hex`** — the full 64-hex digest, used where the complete hash
  matters (`prompt_sha256` / `full_sha256`, `inputs_sha256`, content
  hashes in the governance cache).
- **`payload_hash(payload)`** = `hash12(canonical_json(payload))` — the
  short content-identity function used by prompts, policies, registries, and
  legacy schema-v1 events.
- **Schema-v2 event digest** — full SHA-256 over canonical
  `{schema_version, event_id, event_type, transaction_id, payload,
  prev_event_hash}`. This binds every field that can change replay semantics;
  timestamps remain outside the digest.
- **Epoch identity** (`ari/rqgm/state.py`) —
  `policy_fingerprint` hashes the serving institution plus resolved
  governance settings; `execution_fingerprint` hashes the declared model,
  decoding, tools, environment, and data snapshot; `epoch_fingerprint`
  composes both. `created_at`, `status`, and the composite field itself are
  excluded, so open→closed does not re-fingerprint frozen content.

Id formats (all zero-padded, per-checkpoint counters):

| Format | Producer | Example |
|---|---|---|
| `epoch_%03d` | epoch counter, starts `epoch_000` | `epoch_004` |
| `transition_%03d_to_%03d` | epoch-boundary transition id | `transition_003_to_004` |
| `evt_%06d` | event-log line counter, starts `evt_000000` | `evt_000042` |
| `{role}_v{N}` | component id | `reviewer_v3` |
| `{role}_prompt_v{N}` | prompt id | `reviewer_prompt_v4` |
| `epochstate_{epoch_id}` | `epoch_state.json` record id | `epochstate_epoch_004` |
| `prop_%06d` | ProposalRecord | `prop_000031` |
| `atk_` / `def_` / `jdg_` / `vat_` / `utl_%06d` | adversarial-loop records | `atk_000007` |
| `adv_case_%05d` | AdversarialReplayCase | `adv_case_00003` |
| `pcand_` / `pval_` / `cobs_%05d` | prompt-evolution records | `pcand_00002` |
| `upc_%06d` | UtilityPolicyCandidate (Task 14) | `upc_000004` |
| `erase_` / `rebuild_%05d` | erasure / rebuild events | `erase_00007` |
| `meta_out_` + hash12 | MetaAgentOutputRecord | `meta_out_a1b2c3d4e5f6` |
| 16-hex `cache_key` | governance cache (see below) | `a3f19c02b7d4e881` |

## Constitutional violation codes

Every kernel finding carries a stable `CK-<FAMILY>-<NNN>` code, and its
severity is part of the constitution rather than a caller choice.  Severity
is fixed per code in `ari.rqgm.kernel_rules.SEVERITY` (the
Knowledge/Capability/Harness families are merged in from
`ari/rqgm/kca_kernel_rules.py`), resolved through that one map on **every**
`Violation` construction (`ari/rqgm/kernel.py` `_v`,
`ari/rqgm/kernel_kca_common.py` `violation` — an unknown code is a `KeyError`,
never a defaulted severity), and carried inside `constitution_hash`, so
editing a severity changes the pin.  Codes are frozen once implemented and
never renumbered.

| Family | Owning check | Severity |
|---|---|---|
| `CK-SCH-G01` | `validate_record_schema` — envelope/shape failure on a governance record type (`epoch_transition`, `governance_report`) | block |
| `CK-SCH-N01`, `CK-SCH-N02` | `validate_record_schema` — the same failure on any other record type; proposal-summary field budget exceeded | warn |
| `CK-HSH-001`, `CK-HSH-002`, `CK-HSH-003` | `validate_hashes` — record `prompt_hash` vs the role's registered active hash; `artifact_hashes` vs recomputed sha256; unresolvable artifact or `source_ref` | warn |
| `CK-HSH-010` | `validate_hashes` — an **active** registry entry whose own `prompt_sha256[:12]` disagrees with its registered `prompt_hash` | block |
| `CK-ACC-001`, `CK-ACC-002` | `validate_capability` — `CAPABILITY_MATRIX` miss or a denied Task-11 meta-action flag; retired-prompt-text access (unreadable for every role) | block |
| `CK-EPO-001` | `validate_epoch_invariance` — a record whose `prompt_hash` lies outside the epoch's frozen active set | warn |
| `CK-EPO-002` | `validate_epoch_invariance` — a non-emergency status-change event inside the epoch | block |
| `CK-REG-001`…`CK-REG-007` | `validate_transition` — edge absent from the [T1–T21 table](#the-fixed-transition-table), boundary-only edge stamped mid-epoch, declared `rule_id` contradicting the table, `produced_by` not the RegistryTransitionEngine, required supporting refs missing, invalid emergency shape, `from_status` contradicting the registry | block |
| `CK-REG-101` | `validate_authority_non_expansion` — a candidate declaring more authority than its incumbent (invariant 18) | block |
| `CK-ROL-001`, `CK-ROL-002`, `CK-ROL-003` | `validate_role_separation` — impeachment motion not authored by the Auditor, evidence bundle not by the EvidenceClerk, same-role accusation | warn |
| `CK-ROL-901` | `validate_role_separation` / `validate_capability` — anyone but the RegistryTransitionEngine writing the registry or activating candidates (invariant 10) | block |
| `CK-ERA-001`…`CK-ERA-006` | `validate_selective_erasure` — stale / frontier-invalid / retired-prompt-derived record present in the frontier, un-staled dependent of a retired prompt, physical deletion (invariant 13), `prompt_trace.jsonl` line with an unmapped retired hash | block |
| `CK-AUD-001`, `CK-AUD-002`, `CK-AUD-003` | `validate_audit_log_integrity` — sequence regression, mutated check-pointed prefix, broken hash chain | block |
| `CK-CLN-001`, `CK-CLN-002` | `validate_clean_room_bundle` / `validate_contamination_free` | block |
| `CK-CTX-001` | `validate_context_scope` — a rendered role view exceeds its field whitelist | warn |
| `CK-UTL-001`…`CK-UTL-008` | `validate_utility_policy` — all block **except** `CK-UTL-006` (an axis key outside the epoch's live axis set), which is warn | block / warn |
| `CK-KNW-001`…`015`, `CK-CAP-001`…`018`, `CK-HAR-001`…`020` | `validate_knowledge_integrity` / `validate_capability_binding_integrity` / `validate_harness_integrity` | block |

`severity: block` entitles a verdict to veto a state change wherever an
enforcement path consults it — it does not mean every context acts on it, and
the enforcement mode does not reach every context either.  The sites that
honour [`rqgm.kernel.enforcement`](configuration.md#execution-mode-and-rqgm-governance-opt-in)
route through the helper `ari.rqgm.kernel.should_block`
(`ari/rqgm/runtime.py`, `transition_engine.py`, `frontier_repair.py`, and the
capability-gated MCP wrapper in `kernel.py`); under `audit_only` that helper
returns false for every report while leaving the recorded severities
untouched, so the audit trail stays truthful.  Other sites read
`report.blocking` directly and are therefore unaffected by the enforcement
mode: the clean-room pre/post screens (`ari/rqgm/clean_room.py`), the
meta-candidate admission gate (`ari/rqgm/meta_evolution.py`), and the
governance self-audit escalation (`ari/rqgm/governance/_self_audit.py`).
Deliberately warn-only contexts stay warn-only in either mode: the per-node
hook (`per_node_warn_check`) runs the schema and hash checks without ever
raising, and `validate_context_scope` never blocks node execution.

One escalation is independent of `enforcement`.  A `block`-severity violation
whose code is in `transition_engine.EMERGENCY_TRIGGER_CODES` — `CK-HSH-010`,
`CK-EPO-002`, `CK-AUD-001/002/003`, `CK-ACC-001/002`, `CK-ROL-901` — is handed
from the MCP wrapper to the T16 emergency-quarantine path whatever the mode:
`audit_only` downgrades blocking, not the constitutional fact, and the
emergency transition is itself kernel-validated before it commits.  That path
can only quarantine a **registered component**: the acting component is taken
from the violation, or else resolved from the acting role against the epoch's
frozen `active_components`; when neither yields an id the escalation is logged
and no transition is composed.

## Shared envelope (`rqgm_defs.schema.json`)

**Purpose:** the canonical shared `$defs` every RQGM record schema
references — the `rqgm_record_base` envelope, the closed status / role /
tier vocabularies, and the id/hash formats.  **Owning module:**
`ari/rqgm/events.py` (the Python mirror of the vocabularies).  The copies
of these `$defs` embedded in `epoch_state.schema.json`,
`rqgm_registry.schema.json` and `rqgm_transition_event.schema.json` are
pinned to this file by `ari-core/tests/test_rqgm_state_store.py` — entry by
entry on the parsed JSON, not byte-for-byte — which also pins the
status / role / tier enums and the event-type enum to the `ari.rqgm.events`
vocabulary.

Every governance record carries the eight mandatory `rqgm_record_base`
fields (documented **once** here; the per-schema tables below list only
the record-specific fields):

| Envelope field | Meaning |
|---|---|
| `record_id` | Typed, zero-padded id (formats above) |
| `epoch_id` | `epoch_%03d` the record was produced in |
| `component_id` | Producing component (`{role}_v{N}` or a fixed-engine name) |
| `prompt_hash` | `hash12` of the producing prompt; `null` for kernel/engine-authored records |
| `role` | One of the closed role vocabulary below |
| `created_at` | ISO timestamp — metadata only, never hashed |
| `source_refs` | Checkpoint-relative references to the inputs |
| `status` | Record-specific status vocabulary |

Closed vocabularies:

- **Status lifecycle** (shared by prompts and components; the legal
  transitions are the [T1–T21 table](#the-fixed-transition-table) in
  `ari/rqgm/transition_rules.py`):
  `candidate → validated → shadow → probationary_active → active`, then
  `active → warning | probation | quarantine`, and
  `quarantine → retired → banned`.  `active` and `probationary_active`
  form the frozen per-epoch active set.
- **Roles** — evolvable: `generator`, `reviewer`, `adversary`, `defender`,
  `judge`, `router`, `prompt_mutator`, `clean_room_generator`,
  `replay_selector`, `failure_summary_compressor`, `policy_mutator` and
  `utility_policy` (RQGM Task 14 — the governed score and its proposer),
  `paper_writer` and `paper_reviewer` (paper-archive; registered only under
  the effective `rqgm_archive` paper mode, so an exploration boot is
  byte-identical); governance actors — no prompt-mutation successor path,
  but sanctionable, retirable and bannable like any other component:
  `auditor`, `evidence_clerk`, `governance_judge`; fixed (registered for
  provenance, constitutionally immutable): `constitutional_kernel`,
  `knowledge_binder`, `capability_binder`, `harness_resolver`,
  `fixed_verifier`, `audit_log`.
- **Tiers**: `fixed`, `institutional`, `meta`.

## State and event-log schemas (Task 02)

### `rqgm_transition_event.schema.json`

**Purpose:** the hash-chained, append-only line envelope of
`rqgm_transitions.jsonl` — and, with an independent per-file chain, of
`rqgm_audit.jsonl`.  **Owning module:** `ari/rqgm/events.py`
(`TransitionEvent` / `finalize_event`); persistence in
`ari/rqgm/store.py`.

| Field | Notes |
|---|---|
| `schema_version` | `2` for new events; legacy `1` remains readable |
| `event_id` | `evt_%06d`, per-checkpoint monotonic |
| `event_type` | Closed set: `epoch_transaction_prepare`, `component_registered`, `prompt_registered`, `component_status_change`, `prompt_status_change`, `epoch_close`, `epoch_open`, `epoch_transaction_commit`, `emergency_quarantine` |
| `transaction_id` | Boundary membership; empty only for standalone epoch-open/audit events |
| `payload` | The event body |
| `event_hash` | Full schema-v2 event digest; schema v1 used a 12-hex payload hash |
| `prev_event_hash` | Included in the v2 digest; `""` on the first line |
| `ts` / `ts_iso` | Envelope metadata, outside the digest (P2) |

### `epoch_state.schema.json`

**Purpose:** the derived `epoch_state.json` rollup of the currently open
(or last closed) epoch.  `rqgm_transitions.jsonl` is the source of truth;
the snapshot is disposable and rebuilt from replay on mismatch.
**Owning module:** `ari/rqgm/state.py` (`EpochState`,
`epoch_state_payload`, `epoch_fingerprint`); persisted via
`ari.checkpoint.save_epoch_state_json`.

| Field | Notes |
|---|---|
| `record_id` | `epochstate_epoch_%03d` |
| `epoch_id` / `epoch_seq` / `previous_epoch_id` / `opened_by_transition_id` | Epoch chain position |
| `status` | `open` \| `closed` |
| `run_id` / `node_count_at_open` | Run linkage + boundary bookkeeping |
| `active_components` / `active_prompt_hashes` / `utility_policy` | The per-epoch frozen sets (copied at freeze; global invariants 1–3).  `utility_policy` is the **governed score body** — `composite`, `axis_weights`, `frontier_score`, `depth_penalty_lambda`, `ucb_c` plus the sealed `utility_policy_hash` — captured from the ADOPTED policy by `ari/rqgm/state.py:capture_utility_policy` (the cfg fallback at epoch 0 / `simple_bfts`); see [Governed utility-evolution schema](#governed-utility-evolution-schema-task-14) |
| `registry_version` | `hash12` of the registry as of the freeze |
| `policy_settings` / `policy_fingerprint` | Resolved constitution, thresholds, budgets, and governance settings, plus their 12-hex digest |
| `execution_identity` / `execution_fingerprint` | Declared model/backend/temperature, search and evaluation settings, skills, disabled tools, and explicit model/tool/environment/data revision pins. Missing pins are stored as `unresolved` and set `complete: false` |
| `epoch_fingerprint` | Composite 12-hex identity over policy and execution identity, excluding `created_at`, `status`, and itself |
| `created_at` | Metadata; excluded from the fingerprint |

The shipped schema pins `schema_version` to `1 | 2`.  `ari/rqgm/state.py`
mints a **v3** payload instead — one additional `scientific_identity` block,
plus a `scientific_assurance` copy inside `execution_identity` — whenever the
epoch is frozen with a Knowledge/Capability/Assurance identity
(`KCA_EPOCH_STATE_SCHEMA_VERSION`).  That shape is not declared here, so a v3
snapshot does not validate against the shipped schema; an all-off epoch stays
v2 and byte-identical.

### `rqgm_registry.schema.json`

**Purpose:** the derived `rqgm_registry.json` rollup of ComponentRegistry
+ PromptRegistry in one file so the two stay transactionally consistent on
disk; the event log is the truth.  **Owning module:**
`ari/rqgm/registry.py` (class `GovernedPromptRegistry`; on-disk name stays
`PromptRegistry`); persisted via `ari.checkpoint.save_rqgm_registry_json`.

| Field | Notes |
|---|---|
| `registry_version` | `hash12` |
| `as_of_event_hash` | `event_hash` of the last folded event (`""` when empty) |
| `components[]` | Component entries (status, role, tier; meta-tier entries add the `rqgm_meta` capability flags) |
| `prompts[]` | Prompt entries: text referenced by source (closed `kind` set — `committed_template` for a shipped template, `checkpoint_file` for an evolved prompt, `policy` for a governed utility-policy body), `prompt_hash` (`hash12`) **and** full `prompt_sha256`; `spec_ref` is `null` in v1 |

## Proposal schemas (Task 03)

### `proposal_record.schema.json`

**Purpose:** one line of `proposals/proposal_records.jsonl` — the
append-only proposal truth ("store everything; hand BFTS only the
summary").  **Owning module:** `ari/rqgm/proposals/records.py`
(dataclasses) + `ari/rqgm/proposals/store.py` (persistence, dedup,
`idea.json` projection).

| Field | Notes |
|---|---|
| `record_id` | `prop_%06d` |
| `epoch_id` | `null` in `simple_bfts` record-only mode |
| `role` | const `generator` |
| `generator` | `cheap` \| `mutation` \| `attack_driven` \| `prior_art` \| `virsci` \| `legacy_idea_json` |
| `prompt_hash` | `null` for legacy imports |
| `status` | `candidate` \| `selected` \| `expanded` \| `superseded` |
| `stale` / `valid_for_frontier` | Logical-only flags; read-time semantics owned by frontier repair (Task 10), stored lines never rewritten |
| `source_refs` | Deviates from the envelope's string array: an object (`node_id`, `parent_node_id`, `parent_proposal_id`, `dispatch_head`, ...) |
| `summary` | Inline bounded `ProposalSummaryView` — the only shape BFTS sees |
| `archive_refs` | Checkpoint-relative references into `proposals/archive/<record_id>/` (`raw_output`, `transcript`, `discussion_log`, `retrieval_snapshot`, `generator_config`, ...), never copies |
| `idea_projection` | `{projected, idea_index}` bookkeeping for the maintained `idea.json` compatibility projection |

### `proposal_summary_view.schema.json`

**Purpose:** the bounded proposal summary — the **only** proposal
representation BFTS may consume; full VirSci transcripts are archive-only
and cannot fit the hard character budgets.  **Owning module:**
`ari/rqgm/proposals/records.py`.  Required fields:
`proposal_record_id`, `title`, `short_description`, `hypothesis`,
`experiment_plan[]`, `success_metric`, `novelty_risks[]`,
`expected_artifacts[]`, `dissent_summary`, `scores`.  `schema_version`
lives on the enclosing ProposalRecord; evolution is additive-only.

## Governance schemas (Task 05)

### `governance_report.schema.json`

**Purpose:** the single return type of
`GovernanceOrchestrator.audit_epoch`, appended to `rqgm_audit.jsonl` as a
`governance_report` record — the latest report for an epoch is the *last*
line with that `epoch_id`.  **Owning module:** `ari/rqgm/governance/`
(`_records.py` builders, `_pipeline.py` orchestration).

| Field | Notes |
|---|---|
| `component_id` / `role` | const `governance_orchestrator` / `governance` |
| `status` | const-like enum `final` |
| `governance_level` / `degraded` / `degradation_reasons` | Budget/degradation posture of the audit |
| `reliability` / `observations` / `evidence_bundles` | Per-component reliability inputs (evidence bundles are EvidenceClerk-authored) |
| `impeachment_motions` / `defenses` / `adjudications` | The motion pipeline (Auditor-only motions; same-role accusations rejected) |
| `candidate_evaluations` | Replay/anchor scores feeding the RegistryTransitionEngine |
| `replay_pool_updates` / `self_audit` / `bond_accounting` / `budget_usage` | Boundary bookkeeping |
| `recommendations[]` | `action` is the closed set `promote_candidate` \| `promote` \| `demote` \| `warn` \| `quarantine` \| `retire` \| `no_action`, consumed by Task 09 |

### The motion-pipeline records

Besides the report, `audit_epoch` appends four record types to
`rqgm_audit.jsonl`, all carrying the shared envelope above.  **None of the
four has a standalone schema file** — their shapes are the frozen
dataclasses in `ari/rqgm/governance/_records.py`, and the audit's own
self-audit step re-validates each through the kernel (envelope via
`validate_record_schema`, author via `validate_role_separation`,
CK-ROL-001/002/003).

**`evidence_bundle`** — the EvidenceClerk is the only legal author
(`build_evidence_bundle` raises `GovernanceRuleError` for anyone else), one
bundle per threshold-flagged target, `prompt_hash` always `null` because
the clerk is deterministic.  The clerk's candidate refs are the records naming
the target — validated attacks, utility records, raw attacks, and the
K/C/A provenance types — plus same-role `comparison_observation`s about the
target, which enter only as *leads*: the observation's own `source_refs`
are pulled in for independent verification while the observation ref itself
is still listed, so its exclusion is recorded rather than silent.

`items[]` entries are `{kind, ref, content_hash}`, where `content_hash` is
`payload_hash(record)` — the same `hash12` scheme as everything else on
this page, no second hash — and `kind` comes from a closed
`record_type → kind` map:

| Admissible `record_type` | Bundle `kind` |
|---|---|
| `validated_attack` | `validated_attack` |
| `utility_record` | `utility_record` |
| `judgment_record` | `judgment_record` |
| `review_record` | `review_record` |
| `node_report` | `execution_provenance` |
| `harness_attestation` | `fixed_verifier_result` |
| `knowledge_skill_use` | `instruction_provenance` |
| `capability_binding` | `execution_authority` |

Anything else is inadmissible.  Every rejection is recorded in
`excluded_items[]` as `{ref, reason}`, so a bundle states what it declined
as well as what it carries.  The checks run in a fixed order and the first
match is the reason recorded:

| Order | Reason | Meaning |
|---|---|---|
| 1 | `unresolvable_ref` | The ref does not resolve in the epoch's record slice.  This also flips `verification.all_refs_resolved` to `false` |
| 2 | `unadjudicated_raw_attack` | The ref is a `raw_attack`.  A raw attack is never evidence; only the judge-authored `validated_attack` derived from one is (invariants 8-9) |
| 3 | `same_role_source` | The item's author role equals the target's role.  Same-role output is an observation, never an accusation — this is what excludes a `comparison_observation` about the target, and the target's own review records |
| 4 | `inadmissible_record_type` | The record type is outside the map above |
| 5 | K/C/A integrity reasons | Provenance attachments that fail their own checks: artifact-level (`missing_artifact_reference`, `invalid_artifact_reference`, `unsafe_artifact_reference`, `unresolvable_artifact_reference`, `artifact_digest_mismatch`) plus the per-type checks on attestations, knowledge use, and capability bindings — the full set lives in `_evidence.py` |

Assembly excludes rather than substitutes: it never pads and never raises.
`verification` is `{checked_by: "evidence_audit_checker",
all_refs_resolved}`.  Because a bundle never pads, an empty one cannot
support a prosecution — a flagged target whose bundle has no `items` yields
no motion and a `no_admissible_evidence` entry in `self_audit.findings`.

**Same-role observations are reserved, and not yet produced.**  The design
reserves a governance `comparison_observation` for the case where one
component disagrees with a same-role peer — a reviewer scoring a node
differently from the reviewer that may replace it, say.  Such a record names
its `subject_component_id` and `subject_role`, and its builder sets
`admissible_as_evidence: false` unconditionally: it is an observation, never
an accusation.  That is the "lead, never evidence" rule the clerk implements
above — the observation's own `source_refs` are followed to the primary
artifacts and verified independently, while the observation ref itself lands
in `excluded_items` (reason `same_role_source` when its author role equals
the target's role, `inadmissible_record_type` otherwise), so the exclusion
is recorded rather than silent.

**This path is currently inert.**  The record type, its construction-time
invariant, the lead-following in evidence assembly and the reliability
aggregation over subjects are all implemented, but **no shipped component
emits a governance `comparison_observation` into `rqgm_audit.jsonl`** — the
builder has no production caller.  The report's `observations` array is
therefore empty in every shipped run.  Treat it as reserved design, not as
behaviour a run will exhibit.  The generic same-role exclusion, by contrast,
is live: it applies to any bundle candidate whose author role equals the
target's role, whatever its record type.

The type name is shared with an unrelated shape.  The prompt-evolution
shadow stage writes its own `comparison_observation` — candidate versus
incumbent output hashes and a divergence summary — to
`prompt_evolution.jsonl`, documented under
`rqgm_prompt_evolution.schema.json` below.  The two are told apart by their
file and their fields, not by their `record_type`.

**`impeachment_motion`** — the Auditor is the only legal author, so
Reviewer v4 cannot reach Reviewer v3 through this path at all.  Adds
`target_component_id`, `target_role`, `charge`, `evidence_bundle_id`,
`bond_units` and `requested_action`; `source_refs` is the bundle id alone.
`requested_action` is a strict **subset** of the report's recommendation
vocabulary — `demote` \| `warn` \| `quarantine` \| `retire` — because a
motion never promotes; a value outside it is refused at construction, as is
`target_role: auditor` (the Auditor never impeaches its own role).

**`governance_defense`** — the Defender authors one per motion, carrying
`motion_id`, `defense_text` and `procedural_default`.  On the fallback path
`prompt_hash` is `null` and the text is the fixed procedural default quoted
in the table below.

**`impeachment_outcome`** — the GovernanceJudge authors one per adjudicated
motion.  It exists as a standalone record so Task 09's transition engine
can consume outcomes without parsing whole reports.  It mirrors the
report's `adjudications[]` entry and additionally holds what that entry
only points at: the `rationale` text (the report entry carries
`rationale_ref`, which is this record's id) and `clamped_by_board`, set
when the deterministic boards overrode the judge's verdict.  `outcome` is
the closed set `upheld` \| `partially_upheld` \| `dismissed` \|
`inconclusive`.

**The bond ledger.**  Frivolous prosecution is discouraged without an LLM in
the loop.  Each filed motion posts `rqgm.governance.bond_units_per_motion`
against a per-epoch prosecution budget of
`max_motions_per_epoch × bond_units_per_motion`.  Settlement is a pure
function of the adjudication outcome: `upheld` and `partially_upheld` return
the units, `dismissed` consumes them, and `inconclusive` leaves them posted
— neither returned nor consumed.  The code calls that "carried to the next
epoch", but **no carry mechanism ships**: step 1 reads only the current
epoch's record slice, so an unresolved motion is never re-read, and the next
epoch re-derives its motions from fresh reliability classification.  Once
the budget is depleted, no further motion is filed that epoch whatever the
thresholds say.
Two properties are easy to misread.  `remaining_budget` counts only what
*filing* consumed, so a refund does not restore filing capacity inside the
epoch.  And the ledger is constructed fresh for each `audit_epoch`, so it
resets at every boundary: it does not accumulate penalties across epochs,
which means it under-deters a prosecutor that files frivolously epoch after
epoch.  The result is the report's `bond_accounting` block — `posted`,
`refunded`, `forfeited`, `remaining_budget`.  These are quota counters, not
currency: nothing of value moves between components.

**The `self_audit` block.**  Step 8 audits the judiciary by the yardstick it
applies to everyone else, and it is where the kernel — not the orchestrator
— has the last word.  Every `evidence_bundle`, `impeachment_motion`,
`governance_defense` and `impeachment_outcome` the pipeline just produced is
fed back through `ConstitutionalKernel.validate_record_schema` and
`validate_role_separation`.  The record builders' own refusals are an early
optimisation; this re-run is the guarantee, so a buggy or evolved governance
component cannot smuggle a violating record into the report.  The block
carries:

| Key | Contents |
|---|---|
| `checked_components` | The sorted governance actors examined: auditor, evidence clerk, defender, governance judge |
| `kernel_violations_found` | The violation count from the re-validation |
| `findings` | The deterministic findings raised during the audit.  Exactly four kinds are ever appended: `same_role_prosecution_skipped`, `no_admissible_evidence`, `motion_refused` (prosecution) and `judge_clamped_by_board` (adjudication) |
| `escalations` | `{code}:{subject_ref}` for the violations of every **blocking** kernel report.  **Empty in every shipped run:** the re-validation runs only `validate_record_schema` and `validate_role_separation` over the four produced record types, and for those types both checks can only raise `warn` codes (`CK-SCH-N01`; `CK-ROL-001` / `CK-ROL-002` / `CK-ROL-003`).  The blocking `CK-SCH-G01` needs an `epoch_transition` or `governance_report`, and `CK-ROL-901` needs an `epoch_transition` or `registry_write` — none of which the self-audit is ever handed, the report itself included (step 9 builds it after step 8) |
| `ban_recommendations` | The subjects a contamination-class escalation — `CK-AUD-001` (audit-log append-only violation), `CK-AUD-002` (audit-log prefix tampering), `CK-AUD-003` (broken audit-log hash chain), `CK-ACC-002` (retired-prompt-text access), `CK-ROL-901` (forged registry-writer authority) — or a `contamination` / `clean_room_lineage_failure` finding *would* implicate.  **Reserved design, not behaviour a run will exhibit:** `escalations` is always empty (above) and neither contamination kind is among the four findings the pipeline appends, so the key ships as `[]` on every boundary.  T19's two ends both ship — `_ban_recommendations` writes the key and the RegistryTransitionEngine's `_ban_targets` reads it — what is missing is any upstream producer of a contamination signal to put in it.  A ban would then apply only where the component is actually retired |
| `stats` | `auditor_motion_precision`, `judge_board_clamp_count`, `defender_substantive_rate`.  The two rates are `null` when no motion was filed — never imputed |

Only the first four keys are declared in `governance_report.schema.json`;
`ban_recommendations` and `stats` are additive and ride as undeclared
properties.  If no kernel is available, or the re-validation itself raises,
the block degrades and `self_audit_degraded` joins `degradation_reasons`.

### The audit's determinism budget

The audit has exactly three LLM seams — step 4 (prosecution), step 5
(defense) and step 6 (adjudication) each take an optional renderer.  No
model enters any other step; those run off the epoch's audit-log slice and
the frozen registries alone.  At each seam the rule decides first, and the
model is asked only at the margin.

**Prosecution is rule-first, LLM-second.**  `classify_target`
(`ari/rqgm/governance/_prosecution.py`) reads one ReliabilityMonitor entry
and returns one of three answers.  A component is **filed against outright**
when at least `ATTACK_THRESHOLD` (2) validated attacks are bound to it, or
when its reliability score is below `RELIABILITY_FLOOR` (0.4).  It is
**borderline** — and only then does the LLM Auditor prompt run — when
exactly one validated attack is bound to it, or when its score sits in
`[RELIABILITY_FLOOR, RELIABILITY_FLOOR + BORDERLINE_MARGIN)`, i.e.
`[0.4, 0.5)`.  Everything else is left alone.  All three thresholds are
module constants, fixed in code the way the kernel's rule tables are; only
the budgets under `rqgm.governance` are configuration.  A borderline case
whose auditor reply never arrives or does not parse files nothing at all —
the incumbent presumption, the same shape as
`LineageDecision.fallback_continue`.

Two classes of subject are never prosecuted:

- **`tier: fixed` components.**  The tier check is the classifier's first
  statement and returns "no case" before any threshold is read, so a fixed
  component is unprosecutable however many attacks name it.  Fixed
  procedures are constitutional mechanisms, not institutional incumbents:
  their integrity findings suspend or repair the affected artifact, they do
  not enter impeachment competition.
- **A target whose role is `auditor`.**  The sole Auditor cannot file
  against its own role, so such a target is skipped and recorded as a
  `same_role_prosecution_skipped` entry in `self_audit.findings` rather than
  silently dropped.

`audit_epoch` never aborts on a failing step.  Each of the nine steps has a
total deterministic fallback; taking one flips `degraded` to `true` and
appends a token to `degradation_reasons`.

| Step | On failure |
|---|---|
| 1 collect observations | The epoch's record slice is empty, so steps 2-6 have nothing to work on |
| 2 reliability assessment | No reliability entries.  Independently of step failure, a component that authored nothing this epoch gets `reliability_score: null` with `insufficient_data: true` — a score is never fabricated, and the component stays prosecutable through its validated-attack count |
| 3 evidence assembly | No bundles, therefore no motions.  Per-item failures never reach this row: assembly does not raise, it excludes (above) |
| 4 prosecution decision | No motions.  A *borderline* classification whose auditor call is unavailable or unparseable also files nothing — incumbent presumption; a clear-threshold classification is rule-based and needs no LLM at all |
| 5 defense generation | The defense becomes the fixed procedural default *"no substantive defense generated; incumbent presumption applies"* with `procedural_default: true` |
| 6 adjudication | An unavailable or unparseable judge yields `dismissed`, in favour of the incumbent — the board clamp described below still applies to that fallback.  A board-scoring failure yields `inconclusive`, whose bond is neither refunded nor forfeited but stays posted — the motion is left unresolved rather than decided.  A motion targeting the governance judge itself is recused, producing no outcome record.  A failure in the parallel candidate evaluation yields an empty `candidate_evaluations` |
| 7 replay-pool update | The pool update is skipped and flagged |
| 8 governance self-audit | Kernel re-validation is skipped: `kernel_violations_found` stays 0 and no escalation is raised.  If the whole step fails, the block falls back to a stub with empty `checked_components` and `stats` |
| 9 produce report | The **only** step that may raise.  The caller's fail-open catch (`ari/rqgm/runtime.py`) logs and returns no report; because the facade appends the audit's records only after the pipeline returns, that epoch then contributes no governance records at all, and the run continues |

The schema types `degradation_reasons` as a plain string array — the
vocabulary is enforced by the emitters, not by an enum.  The shipped
pipeline emits these forms and no others:

| Token | Raised when |
|---|---|
| `step_failed:observe`, `step_failed:assess_reliability`, `step_failed:assemble_evidence`, `step_failed:prosecute`, `step_failed:defend`, `step_failed:adjudicate`, `step_failed:evaluate_candidates`, `step_failed:update_replay_pool` | The named step raised and took its fallback above |
| `auditor_llm_fallback:{component_id}` | A borderline target's auditor call was unavailable or unparseable |
| `defender_llm_fallback:{motion_id}` | The defense fell back to the procedural default |
| `judge_llm_fallback:{motion_id}` | No usable judge sample; the motion was dismissed |
| `board_failure:{motion_id}` | Board scoring raised; the motion is `inconclusive` |
| `self_adjudication_recused:{judge_component_id}` | A motion targeted the governance judge, and was left unresolved for external adjudication |
| `replay_pool_update_skipped` | There were upheld cases to add, but the pool exposes no `append_case` |
| `llm_budget_exhausted` | The [`max_llm_calls_per_audit`](configuration.md#execution-mode-and-rqgm-governance-opt-in) cap was hit, or the Task-12 budget manager denied a call |
| `self_audit_degraded` | The self-audit's kernel re-validation was unavailable or raised |

There is no `step_failed:produce_report` token: step 9 is the one step that
does not degrade.

With `llm=None` the audit runs entirely on these rule-only paths, and two
runs over the same inputs produce byte-identical records once `created_at`
is stripped.

**The judge is bounded even when the LLM works.**  The ReplayBoard and
AnchorBoard scores are computed before the GovernanceJudge rules, and the
verdict is bounded by them — the same precedence the evaluator applies when
a node's `results.json` measurements override the LLM's reading of the
truncated artifact text.  A board score is the mean of the subject's stored
case results over at most `rqgm.replay.max_cases_per_epoch` cases, taken in
case-id order; the cap rises to `rqgm.replay.max_cases_for_retirement` when
the motion puts a retirement under consideration (it requests `retire`, or
it targets an already quarantined component), and a present Task-12 budget
manager may lower it further.  With no matching case the board score is
`null` — *unavailable*, never a fabricated number.

The verdict is then checked against the mean of the *available* board
scores for the incumbent.  Both thresholds are module constants in
`ari/rqgm/governance/_adjudication.py`, fixed in code, not configuration:

| Incumbent board mean | Verdict the boards refuse | Clamped to |
|---|---|---|
| ≥ 0.8 (`BOARD_HIGH`) | anything other than `dismissed` | `dismissed` |
| ≤ 0.2 (`BOARD_LOW`) | `dismissed` | `partially_upheld` |

With neither board available there is no bound and the verdict stands.  The
clamp is applied last, after the step-6 fallbacks above, so it bounds a
fallback too: a judge-unavailable `dismissed` against a subject scoring
≤ 0.2 still becomes `partially_upheld`.  A clamp sets
`clamped_by_board: true` on the `impeachment_outcome` record and adds a
`judge_clamped_by_board` finding to `self_audit.findings`, tallied as
`self_audit.stats.judge_board_clamp_count` — a judge that systematically
favours incumbents or challengers is visible in the audit rather than
silently effective.

Candidate prompts are scored on the same boards and **never** by the judge:
a candidate is `pass` when the lowest available board score is at least 0.6
(`CANDIDATE_PASS_THRESHOLD`), `fail` otherwise, and `inconclusive` when
neither board produced a score.  With `rqgm.replay.use_cached_results`
(default on) a wired Task 12 governance cache is consulted before the
pool's stored case results and written back from them;
`candidate_evaluations[].cached` reports that setting, not whether a cache
was present or an individual lookup hit.

With `rqgm.governance.jury_panel_enabled` the judge is sampled three times
and a majority decides; ties break toward the incumbent in the fixed
outcome order `dismissed` > `partially_upheld` > `upheld`.  The default is
`false`, and a single sample decides.

Two report fields are constrained by structure rather than by failure, so
neither raises a degradation token.

**The AnchorBoard needs a held-out corpus, and only the paper phase supplies
one.**  Both boards read their cases off the pool handed to `audit_epoch`:
the ReplayBoard off `pool.cases`, the AnchorBoard off `pool.anchor_cases`.
`AdversarialReplayPool` — the pool an exploration run passes — defines no
`anchor_cases` attribute, so on that path the AnchorBoard reports
*unavailable* rather than a score: `anchor_score` is `null` on every
adjudication and every candidate evaluation, `budget_usage.anchor_cases_used`
stays 0, and both the incumbent board mean that clamps a judge verdict and
the candidate pass rule are decided by the ReplayBoard alone.  A held-out anchor
set reaches the audit only under the paper-archive phase, which swaps in a
pool-shaped adapter carrying one (`ari/rqgm/paper_anchor.py`) — and that
corpus is itself off by default (see the `paper_anchor_corpus.jsonl` entry
below).  Read a `null` anchor score as "no held-out corpus was available",
never as a low score.

**`replay_pool_updates.retired` is inert.**  Only `added` is ever populated
— by the replay cases this epoch's validated attacks are admitted as, plus
the validated-attack refs behind any `upheld` / `partially_upheld` motion.
The `retired` array is initialised empty and nothing appends to it: retiring
a case is a pool-internal operation (`evict_to_cap` marks a case `evicted`
in the snapshot while the JSONL keeps every line ever admitted), and the
audit does not surface it here.  Staleness driven by a *retired prompt* is
handled by frontier repair (Task 10), not reported through this field.

## Adversarial-loop schemas (Task 06)

### `rqgm_attack_records.schema.json`

**Purpose:** the four attack-loop record shapes multiplexed into
`rqgm_adversarial_cases.jsonl` (and, as governance evidence, the audit
log).  **Owning module:** `ari/rqgm/adversarial/records.py` (shapes +
constructive-prevention builders), `ari/rqgm/adversarial/round.py` (the
per-node round).

| Record (`record_type`) | Id / role | Specific fields |
|---|---|---|
| `raw_attack` | `atk_%06d` / `adversary` | `adversary_type` (the shipped-schema enum is the closed seven-type exploration set: `overclaim`, `metric_gaming`, `prior_art`, `reproducibility`, `evidence_gap`, `cost_explosion`, `prompt_injection`; the paper phase adds an eighth, `paper_self_preference` — see [Paper-archive schemas](#paper-archive-schemas-paper-rqgm-archive-mode)); `target_artifact.type` (closed set: `proposal`, `experiment_plan`, `node_report`, `metric_result`, `paper_claim`, `novelty_claim`, `citation_claim`, `reproducibility_claim` — never a component); `attack_claim`; `attack_evidence_refs` (≥ 1 required); `severity_claimed`.  Audit material only — raw attacks never touch a score (invariant 8) |
| `defender_response` | `def_%06d` / `defender` | `raw_attack_id`; `stance` `rebut` \| `concede` \| `propose_fix` |
| `judgment_record` | `jdg_%06d` / `judge` | `raw_attack_id`; `verdict` `valid` \| `partially_valid` \| `invalid`; judge-assigned `severity` (`low`–`critical`); `defense_status`.  Always written, even for `invalid` |
| `validated_attack` | `vat_%06d` / `judge` | `case_type`, `raw_attack_id`, `judgment_id`, `validated`, `verdict`, `severity`, `expected_behavior` (the case-typed `role → expected behaviour` map).  Exists **only** for `valid` / `partially_valid` verdicts (adjudication required, invariant 9).  Carries the accountability binding — see below |

#### The accountability binding on `validated_attack`

Roles are **observed**; components are **bound**; and the binding is minted
**only after adjudication**.  The two target-shaped fields of a
`validated_attack` are not synonyms:

| Field | Value space | Who reads it |
|---|---|---|
| `affected_components` | ROLE names (`["reviewer"]`) — the plural observation of who is implicated.  A role is the only thing an attack can honestly know, and nothing sanctions a role.  (The name holds roles; it is kept unrenamed because renaming it would rewrite every stored record.) | the RQGM viz read model (`RqgmValidatedAttackV1.affected_components`).  **Not** the FailureSummary — its `affected_roles` are the keys of `expected_behavior`, below |
| `target_component_id` | ONE registry-resolvable component id (`"reviewer_v3"`) — the incumbent that made the decision the attack invalidates | `ReliabilityMonitor.validated_attack_involvement`, `EvidenceClerk` target selection ⇒ the whole impeachment chain |

`target_component_id` is **optional and present-or-absent, never
present-and-empty** (`minLength: 1`): an empty target is not a target, and a
record that names no one says nothing — so records that bind nobody are
byte-identical to pre-binding ones and need no migration.  It is resolved
from the implicated role at record construction against the **epoch-frozen**
active component set, never a live registry read (a live read taken after a
boundary adoption would impeach the successor for its predecessor's defect),
and never against the author: a record binding its own judge is refused
(role separation — no actor may both adjudicate and be sentenced by the same
record).

This does not weaken artifact-only targeting.  The adversary still attacks
artifacts and only artifacts; the binding exists solely on the
post-adjudication, judge-authored record.  The adversary observes, and the
judge's verdict is what makes an observation accountable.

In the exploration (`ari_rqgm`) set, the research `generator` is a registered
founding component. Nodes are stamped once with producer component, prompt
hash, and epoch. The seven adversary types bind `generator_v1` only when that
provenance matches the epoch-frozen incumbent. Legacy, missing, or mismatched
provenance remains targetless, so a successor is never blamed for a
predecessor's artifact.

**Where `affected_roles` comes from** — not from `affected_components`, despite
the name.  `build_failure_summary` (`ari/rqgm/adversarial/records.py`) sets
`affected_roles` to `tuple(sorted(validated.expected_behavior))`: the sorted
KEYS of a third role-shaped field, `expected_behavior`, the
`role → expected behaviour` map `AdversarialRound._expected_behavior` stamps
onto the record.  That map is **case-typed**: the seven exploration types all
take one module-level generic template keyed `reviewer` / `generator` /
`judge` — so their records stay byte-identical — while `paper_self_preference`
supplies its own two keys, `paper_reviewer` and `paper_writer`.  The two fields
diverge by construction on a paper case that resolves both bindings: the round
writes one record per resolvable role, each naming its single role in
`affected_components`, while both records carry the same two-key
`expected_behavior` — so both FailureSummaries report both roles.  Reading one
field when you meant the other is a real mistake, not a synonym swap.

### `rqgm_utility_record.schema.json`

**Purpose:** one governed-utility audit record; the adversarial penalty
channel is its sole v1 emitter, and frontier repair (Task 10) re-emits recomputed
records after erasure.  **Owning module:**
`ari/rqgm/adversarial/records.py` (emit) + `ari/rqgm/frontier_repair.py`
(recompute).

| Field | Notes |
|---|---|
| `record_id` | `utl_%06d` |
| `role` | const `utility_policy` |
| `node_id` / `base_score` / `penalty` / `final_score` | The penalty arithmetic per node |
| `input_refs` | `penalty > 0` **requires** ≥ 1 id in `input_refs.validated_attack_ids` (kernel check — raw attacks never score) |
| `utility_policy_hash` / `frozen_policy` | The epoch-frozen policy, embedded **by value** so recompute under the original weights is possible. `frozen_policy` always carries the three penalty keys (`penalty_cap`, `severity_weights`, `verdict_factors`); `frozen_policy.utility_policy` is an **additive, optional** sub-object holding the epoch's scoring policy by value, so a record written after governed utility evolution landed carries BOTH policies and needs no registry lookup to be read after a rewrite. Records written before it exist without the sub-object and still validate. |
| `supersedes` / `recomputed_in_epoch` | Set only on Task-10 recomputed records; the superseded record stays on disk, stale |

Those fields describe recomputation after stale scored-evidence erasure.
Utility-policy retirement takes a different Task-10 path: it re-composes
each node's stored `_axis_scores` under the new policy and records the node
in the enclosing `SelectiveErasureEvent.policy_rescored_node_ids`; missing
raw axes invalidate the node fail-closed.

**No component target — by design, and what that costs downstream.**  The
record names the penalised *node* (`node_id`) and the component that computed
the penalty (`component_id`, which the record class defaults to
`utility_policy_v1`).  It carries no
`target_component_id`: a penalty lands on a node, not on an accused component,
and `UtilityRecord.to_dict` emits neither that field nor `subject_component_id`.
Nor does any sink add one — the audit-log twin is the same `to_dict()` payload
the JSONL truth receives (`AdversarialRound._log_all`).

This is worth stating outright, because the governance side reads as though the
field were there.  `utility_record` is listed in the Evidence Clerk's
admissible-kind map and among the record types `candidate_refs_for_target`
admits (`ari/rqgm/governance/_evidence.py`) — but that selector keeps a record
only when its `target_component_id` / `subject_component_id` equals the
prosecution target's component id.  So a utility record, which has neither,
matches no target: it is scanned into the epoch's record set, and then never
selected.  The penalty channel therefore contributes nothing to any evidence
bundle, and citing it as an evidence source is a mistake — the accountability
that reaches prosecution comes from the `validated_attack` records that caused
the penalty, which carry their own binding (above), not from the penalty.
The Knowledge/Capability/Assurance records stamp `target_component_id` at
construction (`ari/rqgm/runtime.py`) and do match.

The by-value `frozen_policy` discipline keeps this shape additive, so a target
could be added exactly the way `validated_attack` adds one — optional field,
emitted only when non-empty, older records unmigrated — if some future consumer
needs it.  Nothing today does.

### `rqgm_replay_pool.schema.json`

**Purpose:** the derived byte-fixed `rqgm/adversarial_replay_pool.json`
snapshot of the AdversarialReplayPool; `rqgm_adversarial_cases.jsonl`
stays the source of truth and fills any crash tail on load.  **Owning
module:** `ari/rqgm/adversarial/pool.py`; persisted via
`ari.checkpoint.save_adversarial_pool_json`.

| Field | Notes |
|---|---|
| `case_seq` | Monotonic case counter |
| `cases[]` | AdversarialReplayCase: `case_id` (`adv_case_%05d`), `case_type` (the shipped schema's seven exploration types; paper runtime adds the inert-off-phase eighth type described below), `validated_attack_id`, `severity`, `admitted_epoch` / `last_confirmed_epoch`, `status` `active` \| `evicted` (eviction is logical-only), `replay_view` (full materials — `artifact_refs`, the three record ids, and the record's `expected_behavior` map copied by value; denied to role `clean_room_generator`) and `abstract_view` (contamination-safe FailureSummary — `case_type`, `failure_pattern`, `violated_expectation`, `affected_roles`; no raw attack/defense text) |

The two views split the same role information.  `replay_view.expected_behavior`
is the `role → expected behaviour` map taken by value off the
ValidatedAttackRecord; `abstract_view.affected_roles` is that map's sorted key
set and nothing more (see
[The accountability binding on `validated_attack`](#the-accountability-binding-on-validated-attack)).
Because the map is case-typed, the roles a replayed case names depend on its
`case_type`: the seven exploration types share the generic `reviewer` /
`generator` / `judge` template, while a paper-phase `paper_self_preference`
case names `paper_reviewer` and `paper_writer`.  In the shipped schema
`abstract_view` is `additionalProperties: false` — the contamination boundary
is a declared shape, not only the compressor's discipline — whereas
`replay_view` carries no such restriction and is instead gated by capability
(denied to `clean_room_generator`).

## Prompt-evolution schemas (Task 07)

### `rqgm_prompt_spec.schema.json`

**Purpose:** one versioned, immutable prompt identity (PromptSpec) — any
change to the template bytes mints a **new** `prompt_id` + `prompt_hash`;
active prompt text is never mutated in place.  **Owning module:**
`ari/rqgm/prompt_spec.py`; instances are embedded in
`prompt_evolution.jsonl` candidates and rolled up into
`prompt_specs.json`.

| Field | Notes |
|---|---|
| `prompt_id` / `role` / `version` / `status` | Identity + lifecycle position |
| `generation_mode` | `founding` \| `mutation` \| `clean_room` |
| `parent_prompt_id` | Lineage (`null` for founding prompts) |
| `template_ref` | `{kind: package \| checkpoint \| policy, key\|path}` — where the bytes live (committed template, evolved body `rqgm_prompts/<prompt_id>.md`, or a Task-14 governed utility-policy body referenced by `path`) |
| `prompt_hash` / `full_sha256` | `hash12` + full sha256 of the template bytes (the exact `FilesystemPromptLoader.load_versioned` scheme) |
| `evolvable` / `epoch_introduced` | Evolution eligibility + provenance.  Registration rule for a template v1 does **not** evolve: it is registered `evolvable=False` under the NEAREST role of Task 02's closed vocabulary rather than getting a role of its own, because a new role key would change `active_prompt_hashes` and hence `registry_version` for no functional gain.  Six founding rows sit there today — `agent/system`, `pipeline/keyword_librarian`, `viz/wizard_chat_goal`, `viz/wizard_generate_config` under `generator`, the raw-loaded `orchestrator/root_idea_selector` under `router`, and `governance/auditor` under `reviewer` (the last on the same precedent even though `auditor` IS a registrable role for COMPONENTS — `auditor_v1` is founding; impeachability comes from the component, not from the prompt's role).  Row order inside a role is load-bearing: the evolving primary must come LAST for the registry's latest-active-wins rollup, so each of these is placed before its role's primary.  `evolvable=False` is also used for a different reason — the three `rqgm/proposal_*` templates are governed for accountability, not role substitutes |
| `spec` | The behavioural contract: `role_instruction`, `constitutional_constraints[]`, `input_contract.required_fields[]`, `output_schema`, optional `rubric` / `calibration_policy` / `budget_policy`.  `output_schema` reserves exactly ONE key, `__reply__`, for the reply KIND (`bare_index` \| `json_array` \| `json_object` \| `freeform`; absent ⇒ `json_object`); every other key is a required JSON field name mapped to a type name (`list`, `dict`, `string` / `str`, `float`, `int`, `bool`).  The consumer is `check_output_against_schema` (`ari/rqgm/prompt_evolution.py`), which skips `__reply__` in the required-field loop.  The reservation lives in the code only: the shipped schema declares `output_schema` as a required object and says nothing about `__reply__` |

**Quirk (frozen): two founding specs record an EMPTY `required_fields`.**
`input_contract.required_fields[]` is normally the template's extracted
placeholder set, sorted.  Two committed templates are exceptions —
`orchestrator/lineage_decision` and `orchestrator/root_idea_selector` are
listed in `RAW_LOADED_KEYS` (`ari/rqgm/prompt_spec.py`) and their founding
specs get `[]` instead.  This is not a contract choice.  Both bodies are
loaded and used verbatim as system prompts (`_load_system_prompt_versioned` in
`ari/orchestrator/lineage_decision.py` and
`ari/orchestrator/root_idea_selector.py`), never `.format`-ed, so the literal
JSON braces of their "reply ONLY with JSON: `{…}`" line register as
pseudo-placeholders: the extractor reports `"action"` and `"chosen_index"` —
quoted JSON keys, not input names.  Recording those as required inputs would
be worse than recording none, so the founding table records none.  Read it as
an observed, test-pinned exception
(`ari-core/tests/test_rqgm_prompt_spec.py`), not as a pattern: a new template
that takes no inputs should have no placeholders, not a suppression entry.

### `rqgm_prompt_evolution.schema.json`

**Purpose:** the three record shapes multiplexed into
`prompt_evolution.jsonl`.  Adoption into `probationary_active` / `active`
happens **only** through the RegistryTransitionEngine's epoch-boundary
transaction — never through this file.  **Owning module:**
`ari/rqgm/prompt_records.py` (shapes + persistence),
`ari/rqgm/prompt_evolution.py` (pipeline).

| Record (`record_type`) | Id | Specific fields |
|---|---|---|
| `prompt_candidate` | `pcand_%05d` | `candidate_id`, `generation_mode` (`mutation` \| `clean_room`), `mutation_kind` (`freeform_mutation`, `threshold_tuning`, `schema_tightening`, `specialization`, `distillation`), `source_prompt_id`, `failure_summary_refs`, `rationale`, the full embedded `prompt_spec`.  Always born `status: candidate` — no instant activation |
| `prompt_candidate_validation` | `pval_%05d` | `candidate_id`, `stage` (monotonic ladder `static_validation → constitutional_validation → schema_dry_run → replay_evaluation → anchor_evaluation → shadow` — the record chain makes stage skipping detectable), `passed`, `evaluated_by`, `case_results`, `metrics` |
| `comparison_observation` | `cobs_%05d` | `candidate_id`, `incumbent_id`, `input_context_hash`, `node_id`, `candidate_output_hash` / `incumbent_output_hash`, `divergence`.  Hashes and divergence summary only — shadow output text never reaches this file, node metrics, or the frontier |

## Clean-room schemas (Task 08)

### `clean_room_request.schema.json`

**Purpose:** one CleanRoomGenerationRequest, produced from a
RegistryTransitionEngine RetirementEvent (`EpochTransition.
clean_room_requests`) and persisted to `rqgm_cleanroom.jsonl` so pending
requests survive resume.  **Owning module:** `ari/rqgm/clean_room.py`
(requests + pipeline; screen policy in `ari/rqgm/clean_room_rules.py`).

| Field | Notes |
|---|---|
| `component_id` / `trigger` | const `registry_transition_engine` / `retirement_event`; `prompt_hash` is `null` |
| `retirement_event_id` / `target_role` | Which retirement, which role to regenerate (closed role enum) |
| `status` | `pending` \| `generating` \| `generated` \| `rejected_contaminated` \| `failed` \| `superseded` |
| `allowed_inputs` | The five forbidden input flags are **const-false** — a request setting any of them `true` is schema-invalid and kernel-blocked |
| `requirements` / `replay_case_ids` / `budget_policy` | Regeneration requirements; replay cases are evaluation-time only |

### `clean_room_bundle.schema.json`

**Purpose:** the materialized, **closed** input set handed to the
CleanRoomPromptGenerator (`additionalProperties: false` — the bundle is
the entire generator context besides the committed
`rqgm/clean_room_generator` meta-prompt).  **Owning module:**
`ari/rqgm/clean_room.py`.

| Field | Notes |
|---|---|
| `bundle_id` / `request_id` | Linkage to the request |
| `bundle_hash` | `hash12` over the canonical JSON of every other field |
| `role_spec` / `output_schema` / `constitutional_constraints` | What the regenerated prompt must satisfy |
| `abstract_failure_summary` | Contamination-safe failure summary (abstract view only) |
| `replay_requirements` / `cost_budget` | Acceptance requirements + budget |

## Transition schema (Task 09)

### `epoch_transition.schema.json`

**Purpose:** the single output record of one RegistryTransitionEngine
boundary resolution, audited to `rqgm_audit.jsonl` as an
`epoch_transition` record.  Every status change pins a fixed
`rule_id` row of the [T1–T21 table](#the-fixed-transition-table) below (the
T1–T19 base table plus the role-scoped T20 / T21 supersession rows); only the
`rqgm.transition.*` numeric thresholds are configurable.  **Owning
module:** `ari/rqgm/transition_engine.py` — the sole registry status
writer (`produced_by` is const `registry_transition_engine`, kernel
CK-REG-004).

| Field | Notes |
|---|---|
| `epoch_transition_id` | `transition_%03d_to_%03d` |
| `status` | `pending` \| `committed` \| `aborted` \| `rejected` \| `failed` — an aborted/kernel-blocked transition is logged but applies **no** registry change |
| `emergency` | `true` is the T16 shape that quarantines and opens the next epoch in one forced emergency boundary |
| `inputs` | Includes the `inputs_sha256` content hash of the frozen boundary inputs (GovernanceReport + candidate evaluations + registry hashes) so every committed change replays deterministically |
| `adoptions` / `sanctions` / `retirements` / `bans` | Status-change lists, each pinning a `rule_id` |
| `clean_room_requests` | Regeneration requests handed to Task 08 |
| `next_active_components` / `fallbacks` | The next epoch's frozen active set + no-vacancy fallbacks |
| `kernel_validation` (+ optional `kernel_violation`) | The kernel verdict on the transaction |

### The fixed transition table

`ari/rqgm/transition_rules.py` holds the complete, non-evolving transition
table for governed components and prompts, and **both** the
RegistryTransitionEngine (which resolves an edge) and the ConstitutionalKernel's
TransitionValidator (which accepts or refuses it) import that one module — a
single source of truth, so the engine's idea of a legal edge and the kernel's
cannot drift apart.  It is pure data: no LLM call, no I/O, no randomness, no
wall clock.  Only the `rqgm.transition.*` numeric thresholds are configurable;
the *topology* rides inside `constitution_hash`, so adding, removing, or
re-guarding an edge is a constitutional amendment — a code change plus a hand
re-pin of the hash in `ari-core/tests/test_rqgm_kernel.py` — and never a config
value.  The absence of a config escape hatch is the decision, not an oversight:
a table that the running institution could widen would let it vote itself new
powers between two audits.

The ten statuses are Task 02's closed vocabulary
([above](#shared-envelope-rqgm-defs-schema-json)), mirrored member for member by
`transition_rules.ComponentStatus`.  `warning` and `probation` are **serving**
states — the component stays in the epoch's frozen active set and only its
governance posture changes — while `quarantine` removes it from the serving
set.  There is deliberately no `rejected` status: a candidate or shadow that
fails out **without ever having served** takes `retired` as its terminal
disposition (T2 / T5), with the reason carried in the event payload and with
**no** `RetirementEvent` and **no** `CleanRoomGenerationRequest` — those two are
exclusive to T17, the retirement of something that actually served.  `banned` is
absorbing.  A status a reader does not recognise is treated as ineligible for
the active set and logged, never raised.

Three universal guards apply to **every** row, on top of the per-edge guards in
the table:

| | Universal guard |
|---|---|
| **G1** | Only the RegistryTransitionEngine may write a status (global invariant 10 — a Judge writing the registry is a named kernel violation). |
| **G2** | The change commits inside a committed epoch-boundary transaction — the single ⚡ emergency edge is the only exception. |
| **G3** | `ConstitutionalKernel.validate_transition` passed (`CK-REG-001`…`CK-REG-007`). |

⚖ marks the spec-mandated spine; unmarked rows are the auxiliary
recovery/rejection edges that make the machine total; ⚡ is the sole mid-epoch
edge.  The **Guards** column names the deterministic guard predicates the
*engine* evaluates — the kernel itself checks only table membership, `rule_id`
parity, `from_status` agreement with the registry, and the boundary/emergency
shape.

| # | From → To | Triggering input, and the decision the row encodes | Edge-specific guards |
|---|---|---|---|
| T1 ⚖ | `candidate` → `validated` | `candidate_validation_passed` — Task 07's `PromptCandidateValidation`: static validation, constitutional validation, and the schema dry-run all pass.  Validation is a gate, not an endorsement: clearing it only makes the candidate eligible to be *measured*. | `candidate_cap_not_exceeded` (`rqgm.prompt_evolution.max_candidates_per_role_per_epoch`), `constitutional_constraints_present` — a PromptSpec that declares no constraints cannot be validated at all |
| T2 | `candidate` → `retired` | `validation_failed_or_candidate_expired` — any blocking validation failure, or a candidate that waited longer than `candidate_max_age_epochs`. | `never_served_rejection`: terminal, and deliberately *not* a retirement — no `RetirementEvent`, no clean-room request.  The failure summary is kept for the Task 08 abstract-evidence bundle |
| T3 ⚖ | `validated` → `shadow` | `replay_and_anchor_evaluation_passed` — replay score ≥ `replay_pass_threshold` over ≥ `replay_min_cases`, and the anchor evaluation shows no regression against the incumbent. | `shadow_slot_available` (`rqgm.shadow.max_shadow_calls_per_epoch`); boundary only |
| T4 | `shadow` → `validated` | `insufficient_shadow_samples` — after `shadow_max_epochs` the candidate still has fewer than `shadow_min_samples` comparisons.  Under-measured is not the same as failed, so it is re-scheduled rather than rejected. | `shadow_retry_within_limit` (`shadow_retry_limit`); past that limit the disposition is T5 |
| T5 | `shadow` → `retired` | `shadow_quality_below_threshold` — agreement/quality below `shadow_pass_threshold` *with enough samples to say so*. | `never_served_rejection`, exactly as T2 |
| T6 ⚖ | `shadow` → `probationary_active` | `shadow_agreement_passed` — the GovernanceReport's shadow section shows agreement/quality ≥ `shadow_pass_threshold` over ≥ `shadow_min_samples` live-shadow comparisons.  This is the adoption edge, and it lands in *probation*: nothing is ever adopted straight into `active`. | `role_opening_available` (the incumbent is in probation/quarantine/retired, or the role is unfilled), `one_adoption_per_role_per_boundary` (`max_adoptions_per_role_per_boundary`); boundary only |
| T7 ⚖ | `probationary_active` → `active` | `clean_probation_record` — the GovernanceReport attributes zero upheld `ValidatedAttackRecord`s to it and its performance is at least the incumbent baseline over the probation window.  **This is the only way a component earns a full seat.**  Every serving component has served a probation first, so nothing is ever trusted on its evaluation scores alone: the evidence that promotes it is behaviour observed while it was already answering, under intensified scrutiny and reversible by a single boundary. | `probation_min_epochs_served` (`probation_min_epochs` full epochs); boundary only |
| T8 | `probationary_active` → `quarantine` | `upheld_impeachment_or_reliability_collapse` — a probationer loses its provisional seat on the same evidence that would unseat an incumbent. | boundary, or ⚡ as one of the T16 shapes |
| T9 ⚖ | `active` → `warning` | `reliability_warning_or_low_severity_attacks` — GovernanceReport reliability warnings, or validated attacks of `severity: low`. | `component_keeps_serving`; boundary only |
| T10 ⚖ | `active` → `probation` | `repeated_warnings_or_medium_severity_attacks` — ≥ `warning_escalation_count` consecutive warning epochs, or medium-severity validated attacks. | `component_keeps_serving`, under intensified shadow comparison; boundary only |
| T11 ⚖ | `active` → `quarantine` | `upheld_impeachment_or_critical_attack_pattern` — an upheld `ImpeachmentOutcome`, or a high/critical-severity validated attack pattern the GovernanceReport attributes to it. | `fallback_assigned` — the role is never left vacant; boundary, or ⚡ as one of the T16 shapes |
| T12 | `warning` → `active` | `clean_epoch` — a full epoch with no new warnings or attacks in the GovernanceReport.  A warning is a posture, not a debt: it clears itself, and nothing has to be filed to lift it. | boundary only |
| T13 | `warning` → `probation` | `warning_recurrence_within_memory` — recurrence inside `warning_memory_epochs`. | boundary only |
| T14 | `probation` → `active` | `rehabilitation_clean_epochs` — clean epochs served under intensified scrutiny.  Rehabilitation is a real path, not a formality: a sanction is not a slow death sentence. | `probation_min_epochs_served`; boundary only |
| T15 | `probation` → `quarantine` | `continued_degradation_or_upheld_impeachment` | boundary, or ⚡ as one of the T16 shapes |
| T16 ⚡ | `probationary_active` \| `active` \| `warning` \| `probation` → `quarantine` | `constitutional_emergency` — a deterministic ConstitutionalKernel critical-violation record naming the component.  **The only mid-epoch edge in the table.**  Performance signals never qualify: a component that is merely slow or disappointing waits for the boundary, because the epoch freeze is what makes a run auditable and only a constitutional violation is worth breaking it for.  The edge force-closes the current epoch and commits the quarantine plus a freshly fingerprinted epoch-open in the same transaction, so "mid-epoch" never means "outside a boundary transaction". | `emergency_flag_set` (`transition.emergency == true`), `kernel_violation_attached`, `single_sanction`; `boundary_only` is `False` on this row alone |
| T17 ⚖ | `quarantine` → `retired` | `adjudication_confirmed_retirement` — at a boundary, a ReplayBoard confirmation over ≥ `retirement_replay_min_cases` cases (inside the `rqgm.replay.max_cases_for_retirement` budget) upholds the impeachment.  Quarantine is a suspension; retirement is the verdict, and the verdict needs evidence re-run *after* the accusation rather than the evidence that raised it. | `replay_board_confirmation`, `emits_retirement_event` — this edge, and only this edge, emits the `RetirementEvent` + `CleanRoomGenerationRequest` and hands the retired `prompt_hash` set to frontier repair; boundary only |
| T18 | `quarantine` → `probationary_active` | `exoneration` — the GovernanceSelfAudit or the AdjudicationPanel overturns the impeachment.  Re-entry is **into probation, never straight back to `active`**: exoneration restores standing, not seniority. | `re_enters_under_probation`; boundary only |
| T19 ⚖ | `retired` → `banned` | `contamination_or_critical_finding` — prompt-injection content, audit-log tampering attributed to it, or repeated clean-room-descendant failure traced to its lineage.  Retirement ends a component's service; a ban additionally forbids its *text* from being read again, which is why it is a separate, heavier finding. | `absorbing`; bans reuse of its text and few-shots as a clean-room reference beyond the abstract failure summary; boundary only |
| T20 | `active` → `retired` | `superseded_by_adopted_successor` — the `utility_policy` supersession edge.  The utility policy is the evaluation *criterion*, not a behavioural actor, so it is replaced by supersession rather than by sanction: a validated, shadow-passed successor displaces the **healthy** incumbent and retires it carrying the **old** `utility_policy_hash`, which is exactly what makes `frontier_repair` invalidate every node scored under it.  Without this row the score-rewrite spine was dead — T6 needs a role opening that a healthy passive policy never yields. | `supersession_successor_adopted` — emitted only inside a same-role T6 adoption, so a displacement can never happen without a successor to justify it; `utility_policy_role_only`; `emits_retirement_event` |
| T21 | `active` → `shadow` | `superseded_by_adopted_successor` — the paper-role supersession edge (`paper_writer` / `paper_reviewer`).  Paper-role co-evolution is prompt-level, so when a successor prompt adopts, the incumbent has to go somewhere: it is demoted to a **reinstatable** `shadow` standby, which keeps exactly one active entry per paper role instead of leaving two co-active behind a latest-wins rollup.  Unlike T20 this is not a retirement and deletes nothing — a later boundary can re-climb the standby through T6. | `supersession_successor_adopted`, `paper_prompt_role_only` (`transition_rules.PAPER_SUPERSESSION_ROLES`), `reinstatable_standby` |

T20 and T21 are the **only** two exceptions to the sanction-only replacement
model, and each is kernel-guarded to one role family: for every behavioural role
`active → retired` and `active → shadow` stay forbidden and the kernel rejects
them (`CK-REG-001`), so a behavioural component still leaves its seat only
through quarantine.

**How T16 is encoded.**  The table is a `dict` keyed by
`(from_status, to_status)` with exactly 21 entries, one per rule id — which is
what the `|S|×|S|` complement test enumerates.  T16 spans four `from` statuses,
and three of those pairs (`probationary_active` / `active` / `probation` →
`quarantine`) already have boundary rules of their own — T8, T11, T15 — and keep
those rule ids as their table entry.  The T16 *row* is therefore the one pair
with no boundary edge of its own, `warning → quarantine`.  The full four-shape
emergency set lives in `transition_rules.EMERGENCY_EDGE`, and a mid-epoch commit
is legal only as an emergency transition over one of those four shapes.

**Everything not in the table is forbidden**, and four of the absences are
load-bearing rather than accidental: there is no `candidate → active` edge (no
instant activation, global invariant 15); no resurrection out of `retired`; no
edge out of `banned`, which is absorbing; and no in-place substitution of prompt
text without a status edge (global invariant 3), because a prompt that changed
without a transition would be an unaudited change of who is answering.  The
kernel rejects the whole complement: the test suite enumerates the `|S|×|S|`
matrix and asserts that exactly these 21 rows are accepted.

## Frontier-repair schemas (Task 10)

### `selective_erasure_event.schema.json`

**Purpose:** one SelectiveErasureEvent appended (inside the Task 02 audit
envelope) to `rqgm_audit.jsonl` when the FrontierRepairEngine stales the
dependency closure of a retired `prompt_hash`.  Erasure is logical-only
(invariant 13): listed ids are flagged in `rqgm_erasure_state.json`, never
rewritten or deleted.  **Owning module:** `ari/rqgm/frontier_repair.py`.

| Field | Notes |
|---|---|
| `record_id` | `erase_%05d` |
| `component_id` / `role` / `prompt_hash` | const `frontier_repair_engine` / `kernel` / `null` (kernel-authored) |
| `status` | `applied` \| `conservative` \| `halted_expansion` (the fail-closed degradation ladder) |
| `retired_prompt_hashes` / `retired_component_ids` | What was retired |
| `direct_stale_record_ids` / `transitive_stale_record_ids` | The dependency closure |
| `invalidated_node_ids` / `recompute_node_ids` / `abandoned_pending_node_ids` | Node dispositions for stale dependency closure |
| `policy_rescored_node_ids` | Optional/additive #77 list of nodes re-weighted from stored `_axis_scores` under the new utility policy rather than invalidated |
| `trace_stats` | BFS tracer statistics (`rqgm.frontier_repair.max_trace_depth` caps the walk) |

### `frontier_rebuild_event.schema.json`

**Purpose:** one FrontierRebuildEvent appended to `rqgm_audit.jsonl` after
the engine recomputes the frontier declaratively (eligibility + Rule-A
reinstatement of a parent whose winning child was erased).  **Owning
module:** `ari/rqgm/frontier_repair.py`.

| Field | Notes |
|---|---|
| `record_id` | `rebuild_%05d` |
| `component_id` / `role` / `prompt_hash` | const `frontier_repair_engine` / `kernel` / `null` |
| `status` | `applied` \| `conservative` (flagged nodes dropped after a kernel-validation failure) \| `halted_expansion` (run degraded to drain-only) |
| `frontier_before` / `frontier_after` | Node-id lists |
| `removed_node_ids` / `reinstated_node_ids` / `recomputed_utility_node_ids` | The delta |
| `kernel_validation` | `passed` \| `failed` |

### `erasure_state.schema.json`

**Purpose:** the derived, rebuildable `rqgm_erasure_state.json` staleness
rollup — foldable from every erasure/rebuild event in `rqgm_audit.jsonl`.
Staleness is read-time: a record is stale iff its `record_id` is in
`stale_record_ids`; absence of the file means "nothing stale, all valid".
**Owning module:** `ari/rqgm/erasure_state.py`; write funneled through
`ari.checkpoint.save_erasure_state_json`.

| Field | Notes |
|---|---|
| `retired_prompt_hashes` | `hash12 → {retirement_event_id, retired_in_epoch}` |
| `stale_record_ids` | `record_id → erasure event id` |
| `invalid_frontier_node_ids` | `node_id → erasure event id` |
| `last_erasure_event_id` / `last_rebuild_event_id` | Fold cursor |

## Meta-evolution schema (Task 11)

### `rqgm_meta.schema.json`

**Purpose:** the meta-tier `$defs` — the ComponentRegistry `tier` +
capability-flag extension, the MetaAgentOutputRecord line shape of
`rqgm_meta_outputs.jsonl`, and the MetaCandidateEvaluation record consumed
by the RegistryTransitionEngine.  **Owning module:**
`ari/rqgm/meta_rules.py` (the deterministic Python mirror —
`capability_entry_failures` — must agree with the schema) +
`ari/rqgm/meta_evolution.py`.

| Definition | Key fields |
|---|---|
| `capability_flags` | Boolean capability matrix (`can_modify_registry`, `can_activate_candidates`, `can_read_retired_prompt_text`, `can_file_impeachment`, `can_author_evidence_bundle`, `can_emit_candidates`, `can_emit_replay_recommendation`, `can_emit_failure_summary`) + `allowed_targets` / `forbidden_targets` / `max_outputs_per_epoch`.  Flags default to false; hard-denied flags are const-false on `tier: meta` |
| `meta_component_entry` | `component_id`, `role`, `tier`, `status`, `prompt_hash`, `capabilities` |
| `meta_agent_output_record` | `record_id` `meta_out_` + hash12; `status` `recorded` \| `denied`; `output_kind` closed set `prompt_candidate` \| `clean_room_candidate` \| `replay_case_recommendation` \| `failure_summary`; `target_role`; `shadow` / `sandboxed` flags; `input_bundle_hash` / `output_payload_hash` |
| `meta_candidate_evaluation` | `candidate_component_id` vs `incumbent_component_id`, `sandbox` / `shadow` results, `downstream_fate`, `authority_non_expansion_check` `pass` \| `fail` |

## Governance-cache schema (Task 12)

### `rqgm_governance_cache.schema.json`

**Purpose:** one line of the append-only `rqgm_governance_cache.jsonl`
governance result cache.  **Owning module:**
`ari/rqgm/governance_cache.py`; consumed by
`ari/rqgm/governance/_adjudication.py` (the epoch-boundary candidate
evaluation) and the `rqgm.replay.use_cached_results` replay lookups.

| Field | Notes |
|---|---|
| `cache_key` | `sha256(artifact_hash ␟ prompt_hash ␟ role ␟ epoch_id ␟ input_context_hash ␟ output_schema_hash)[:16]` (`␟` = `\x1f`); 16-hex |
| `artifact_hash` / `input_context_hash` / `output_schema_hash` | Full sha256 over canonical JSON |
| `result_ref` / `score` | Pointer to the underlying record + cached score |
| `created_at` | Provenance only — **never** part of the key (P2) |

Entries are never invalidated in place: a retired prompt's entries stop
being addressable because its `prompt_hash` never recurs in a lookup
(invariant 13).  Budget counters and governance-level assignments are not
stored here — they ride `rqgm_audit.jsonl` as `budget_consumed` /
`budget_degraded` / `governance_level` lines (`ari/rqgm/budget.py`).

## Governed utility-evolution schema (Task 14)

### `rqgm_utility_policy_candidate.schema.json`

**Purpose:** one proposed successor **utility policy** — the governed score is
now an evolvable, boundary-rewritable object (RQGM Task 14).  A
`utility_policy_candidate` mirrors a `prompt_candidate` and rides the **same**
`prompt_evolution.jsonl` log — no new store.  Its envelope author is the
`policy_mutator`, not the policy: a candidate is a proposal *by* a component,
so `component_id` / `prompt_hash` name the proposer while the proposed policy
rides `policy` (by value) + `policy_hash`.  **Owning module:**
`ari/rqgm/utility_evolution.py` (`UtilityPolicyCandidate`, `PolicyMutator`);
minted at a boundary and appended via
`ari/rqgm/prompt_records.record_prompt_evolution_event`.

| Field | Notes |
|---|---|
| `record_id` | `upc_%06d` |
| `role` | const `policy_mutator` — the AUTHOR's role; the TARGET role (`utility_policy`) is implied by `record_type` |
| `candidate_id` | The minted candidate identity; also the prompt-registry `prompt_id` on intake |
| `mutation_kind` | Closed set `axis_reweighting` \| `composite_swap` \| `frontier_score_swap` \| `exploration_tuning` \| `freeform_policy_proposal` |
| `policy` | The policy body: `composite`, `axis_weights` (per-axis weight map), `frontier_score`, `depth_penalty_lambda`, `ucb_c`.  The body never contains `utility_policy_hash` — the hash is *of* the body |
| `policy_hash` | `hash12(canonical_json(policy))` — one value, three names: `policy_hash` **is** the intake entry's `prompt_hash` **is** the `utility_policy_hash` the candidate would freeze if adopted |
| `parent_prompt_id` / `rationale` / `source_refs` | Lineage + abstract evidence only — `rationale` / `source_refs` never carry raw attack text |

Legality (the closed value spaces + axis-weight bounds) is **not** expressed in
this schema: it is frozen code in `ari.rqgm.kernel_rules.UTILITY_POLICY_RULES`,
inside `constitution_hash`, and enforced by CK-UTL-001..008 before a candidate
can ever score a node.  Adoption happens **only** through the
RegistryTransitionEngine boundary transaction — the role-agnostic T1→T6 spine,
plus the Task-14 supersession edge **[T20](#the-fixed-transition-table)**
`superseded_by_adopted_successor` (the sole `active → retired` edge,
kernel-guarded to `utility_policy` only) — never through this record.  The evolved policy body
is written write-once to `rqgm_prompts/<candidate_id>.json` (referenced by
source, never inlined), and the adopted policy is what
`ari/rqgm/state.py:capture_utility_policy` freezes into `epoch_state.json`.

## Paper-archive schemas (paper `rqgm_archive` mode)

The paper-archive paper mode (`paper.mode: rqgm_archive`, gated by
`rqgm.paper.enabled`) persists four checkpoint files.  Like `rqgm_state.json`
and the evaluation-harness artifacts, **none of them has a formal JSON
schema** — each shape is owned by its Python module and carried by value — and
all four are absent on a default `linear` paper run (no `ari.rqgm` module loads
on the linear path).

### `paper_archive_state.json` — paper-phase mode provenance

Write-once at paper-phase start.  Shape owned by `ari/rqgm/paper_runtime.py`
(`build_paper_run_start_state`): `schema_version`, `paper_mode`
(`linear` \| `rqgm_archive`), `rqgm_paper_enabled`, `mode_source`
(∈ `config` \| `env` \| `resume`), `created_at` (metadata only, never hashed),
`exploration_mode`, `seed_node_id`, `switch_journal[]`, plus
`evaluation_condition_id` when — and only when — the caller pins an evaluation
condition.  The persisted mode wins on re-invocation — resume never silently
flips the paper mode.  Writer:
`ari.checkpoint.save_paper_archive_state_json`.

`seed_node_id` is the one field write-once cannot keep current: it records
what the FIRST paper invocation started from, while the live seed is
recomputed every round under mechanisms that exist to change it (selective
erasure excluding the recorded seed, an escalation penalty demoting it, and
the penalty replay that re-applies both before selection).  A later
invocation computing a different seed therefore APPENDS
`seed_journal[]` — `{event: "seed_changed", prior_seed_node_id,
seed_node_id}`, chained off the latest entry — instead of rewriting the
record, so the file tells the whole story rather than a silently stale first
line.  Only the ids are journaled: *why* the seed moved is already durable in
`rqgm_audit.jsonl` (erasure events) and `rqgm_adversarial_cases.jsonl`
(validated-attack penalties).

**The `budget_counters` block, and the three keys that are not in it.**  The
file is not only the write-once start record.  `_persist_budget_counters`
(`ari/rqgm/paper_runtime.py`) re-reads it after each archive round — and once
more after the winner's lazy compile — and replaces a `budget_counters` key on
it: `paper_epoch_id`, `draft_expansions`, `adversary_calls`,
`anchor_scoring_calls`, `prompt_candidates` (split per governed role,
`paper_writer` / `paper_reviewer`), and `compiles`.  The three metered counts
(`adversary_calls`, `anchor_scoring_calls`, `prompt_candidates`) are DERIVED
from the current paper epoch's `budget_consumed` lines in
`rqgm_audit.jsonl` — the audit log stays the source of truth, under the same
derive-from-records discipline `GovernanceBudgetManager`'s own restore uses, so
`ari paper` re-invocation never double-counts them.  The other two are
in-process counters (`draft_expansions` is the last round's archive population,
`compiles` the runtime's lazy-compile tally), so a resumed process restates
those two from zero.  The whole write is best-effort and its failure is logged
rather than raised, so an absent block means the mirror never landed — not that
nothing was spent.

Three keys a cost reader may expect are deliberately not there, for two
different reasons.
`governance_cost_usd` and `governance_tokens` are omitted rather than stamped
zero: `GovernanceBudgetManager.consume` accumulates both when a caller supplies
them, but neither paper-phase `consume` site passes a cost or a token count, so
a zero written here would advertise a measured absence of spend that was never
measured.  `draft_levels` is absent for a different reason — the archive
constructs its `AdversarialRound` directly, while the governance level ladder
(`level_with_triggers` / `record_level`) runs only inside
`RQGMRuntime.run_adversarial_round`, so no per-draft level assignment exists to
mirror.  (The one level assignment the paper phase does make belongs to an
exploration node rather than a draft: the paper-candidate escalation runs the
full round, and its assignment lands in `rqgm_audit.jsonl` as a
`governance_level` line, not here.)  So read `budget_counters` as a per-epoch
call tally, never as cost accounting, and do not code against
`governance_cost_usd`, `governance_tokens`, or `draft_levels` — no writer
emits them.

### `paper_draft_archive.jsonl` — the scored draft population

Append-only, byte-fixed, best-effort (a record-write failure never breaks the
paper phase; an absent file reads as empty — a linear run leaves no archive).
Shape owned by `ari/rqgm/paper_archive.py` / `ari/rqgm/paper_draft_executor.py`:
one draft node per line — `schema_version`, `draft_id` / `node_id`, `kind`
(`seed` \| `refine`), `parent_draft_id`, `refine_pass`, `tex_path`,
`tex_sha256`, `writer_prompt_hash` (the framing / `diversity_bonus` key),
`reviewer_prompt_hash`, `review_score` (the governed `paper_reviewer` composite
— the frontier + best-belief ranking key), `suggested_revisions_ref`,
`anchors_preserved`, `decode_seed`, `epoch_id`, the read-time flags
`is_best_belief` / `compiled` (updated in place by `mark_paper_draft_flags`),
and the selective-erasure staleness fields `review_score_stale` /
`stale_at_epoch` / `replacement_reviewer_prompt_hash` (stamped in place by
`erase_paper_reviewer_utilities` when a displaced reviewer's scores are
logically erased — stale rows are ineligible for best-belief and
cross-round winner selection).

Each line also carries `created_at` and the Manuscript-Complete `manuscript_*`
block: the binding fields written with the draft (`manuscript_bound`,
`manuscript_mode`, `manuscript_attempt_id`, the `manuscript_input_fingerprint`
/ `manuscript_binding_digest` / `manuscript_profile_digest` /
`manuscript_context_digest` / `manuscript_readiness_digest` /
`manuscript_brief_bundle_digest` pins, `manuscript_section_brief_digests`, the
`manuscript_allowed_evidence_ids` / `manuscript_contextual_negative_ids` /
`manuscript_forbidden_evidence_ids` lists, `manuscript_required_disclosures`
and `manuscript_omission_count`), then the deterministic diagnostics
`record_paper_draft_manuscript_evaluation` attaches afterwards
(`manuscript_candidate_status`, `manuscript_hard_disqualified` +
`manuscript_hard_disqualification_reasons`,
`manuscript_candidate_artifact_sha256`, `manuscript_candidate_gate_digest` /
`manuscript_candidate_gate_status`, and the
`manuscript_contextual_negative_evidence_mentions` /
`manuscript_forbidden_evidence_mentions` /
`manuscript_missing_required_disclosures` findings).  That attachment is the
one writer here that is **not** best-effort: it is a targeted
last-record-wins rewrite that re-reads the file and raises unless the values
round-trip, because enforce-mode eligibility depends on them.  Under the
default `manuscript.mode: "off"` the block is the empty/false defaults, and a
`manuscript_hard_disqualified` row is excluded from the frontier exactly as a
stale one is.

### `paper_anchor_corpus.jsonl` — the read-only accept/reject anchor

The APReS-equivalent held-out corpus that anchors the `paper_reviewer` utility.
Shape owned by `ari/rqgm/paper_anchor.py` (`PaperAnchorCase`): `case_id`,
`record_type`, `ground_truth_label` (`accept` \| `reject`), `label_source`
(`human_curated` \| `gate_bootstrap`), `manuscript_sha256` / `manuscript_ref` /
`manuscript_text`, `venue`, `authorship` (`human` \| `ai`), `split`
(`train` \| `held_out`, assigned deterministically at load), `origin_epoch_id`,
`expected_behavior`, `results`.  Written **once** by curation/bootstrap tooling
— **never** by a governed role (the anchor is a fixed ground truth, not an
evolvable artifact).  The `max_bootstrap_label_fraction` cap over
`gate_bootstrap` labels is machine-enforced over the corpus **and** the
held-out subset; a breach refuses the whole corpus and falls back to the
no-anchor on-ramp rather than raising.  **Default OFF** (`anchor.enabled: false`): the degraded on-ramp
leaves no corpus, so the default `rqgm_archive` run is reviewed best-of-N until
a curated corpus is supplied.

### `rqgm/paper_self_preference_stat.json` — the self-preference statistic

The per-epoch deterministic AI-vs-human self-preference margin the eighth
adversary cites as its `attack_evidence_ref`.  Written under the `{ckpt}/rqgm/`
snapshot dir, best-effort (never raises into the paper phase).  Shape owned by
`ari/rqgm/paper_self_preference.py` (`compute_self_preference_margin`):
`record_type`, `schema_version`, `epoch_id`, `sample_ids[]`, `per_case_scores`,
`ai_mean`, `human_mean`, `margin` — `mean(reviewer accepts | authorship == ai) −
mean(… | authorship == human)`, **`0.0` when the corpus carries no AI/human
split** (the corpus-absent / AI-only degradation, never an error).

**Where the corpus comes from.**  The statistic has no corpus of its own: it
runs over `reviewer_anchor_cases(pool)` — the same `paper_anchor_corpus.jsonl`
pool the reviewer's anchor utility uses — read with one extra label dimension,
each case's `authorship` (`human` \| `ai`) field documented above.  The AI/human
split is therefore a property of the anchor corpus.  With a corpus that carries
no split, `margin` is `0.0`, the population signal goes silent, and the
adversary still prosecutes on the other two over-acceptance signals — a
claim-gate finding, or the direct per-case disagreement where the incumbent
accepted an anchor case whose ground truth is `reject`.  With no corpus at all
— the default, since `anchor.enabled` is `false` — there are no over-accepted
cases to find and the round never fires.

The knobs are `rqgm.paper.self_preference.*`, meaningful only under the
effective `rqgm_archive` paper mode: `enabled: true`; `sample_size: 8`
(the held-out cases scored per epoch, deterministically the first N by
`case_id`; the same number is applied a second time to the over-accepted subset
and so also bounds how many cases are attacked, under the shared per-epoch
adversary call cap);
`accept_threshold: 0.6` (the reviewer-"accepted" cutoff, mirroring the
governance `CANDIDATE_PASS_THRESHOLD`, also `0.6`) — carried into the attack
bundle for the over-acceptance pre-signal, **not** used by the margin itself,
which binarises the reviewer's `accept_recommendation`; and `margin: 0.1` (the
AI-vs-human gap that fires the deterministic pre-signal).  One knob is
**declared but unwired**: `corpus_path: ""` is described as "`""` reuses the
anchor corpus, a path overrides with a dedicated authorship set", and the `""`
half is what the code does — but nothing reads
`rqgm.paper.self_preference.corpus_path`, so setting a path there has no effect
today.  The only corpus path the loader resolves is
`rqgm.paper.anchor.corpus_path`.

**The eighth adversary type.**  `paper_self_preference` is the eighth member of
the Python `ADVERSARY_TYPES` tuple (`ari/rqgm/adversarial/records.py`, the
write-path validity check `validate_raw_attack` uses), added for the paper
phase and inert off it; the shipped `rqgm_attack_records.schema.json`
`adversary_type` / `case_type` enum documents the seven **exploration** types.
A `paper_self_preference` case implicates the `paper_reviewer` role — and, on a
draft the Layer-0 claim gate confirms unfaithful, also `paper_writer`.  Both
HAVE a registered incumbent under the paper mode (`paper_reviewer_v1`
/ `paper_writer_v1`), so the Task-15 `target_component_id`
binding fires and the validated-attack → impeachment chain runs in production;
off the paper phase both roles resolve to `""` and exploration stays
byte-identical.

## The paper-phase must-not-break register (BP-1 … BP-12)

The paper-archive mode ships with a **closed compatibility register**: exactly
twelve numbered invariants, `BP-1` through `BP-12`.  Most of the individual
rules are also stated where they are enforced; what only this register carries
is that the twelve are **one list**.  A paper-path change is compatible when it
leaves all twelve intact and incompatible otherwise — there is no thirteenth
rule to appeal to, and no rule may be dropped without the register being
re-numbered as a whole.  Reviewing a change against three of them is not a
partial pass; it is not a pass.

The `BP-` prefix (paper) distinguishes these from the exploration set's
`B-1 … B-19`, which a `rqgm_archive` run inherits verbatim — it is still an
`ari_rqgm`-substrate run and must honour them too.  Everything below holds
byte-identically under `paper.mode: linear`; the archive is additive and
config-gated.

- **BP-1 `linear` is identity.**  A config without a `paper:` block, or with
  `paper.mode: linear`, produces a paper phase byte-identical to the
  pre-archive pipeline: the same `WorkflowDriver` stage order, the same fixed
  output paths, the same `full_paper.tex` / `full_paper.pdf`, and no
  `paper_archive_state.json` or `paper_draft_archive.jsonl` left behind.  No
  `ari.rqgm` paper module is imported on the linear path —
  `ari.config._effective_paper_mode_str` mirrors the activation cell
  import-free, and `ari-core/tests/test_paper_mode.py`
  (`test_linear_path_imports_no_rqgm_and_writes_no_state`) asserts the leak set
  is empty.
- **BP-2 The claim gate stays Layer-0, unchanged.**  The
  `claim_evidence_hard_gate` blocking matrix is preserved: a draft-phase report
  never blocks, the objective-integrity `always_block_on` tier blocks at the
  final phase in every mode, and infra errors fail open
  (`ari/pipeline/claim_gate/policy.py`).  The gate is never kernel-wrapped, and
  the best archive draft is handed to the *existing* compile + gate tail
  unchanged.
- **BP-3 The linear stage sequence and file-order execution are unchanged, and
  the archive's seam sits outside them.**  `loop_back_to` remains the only
  rewind, `skip_if_exists` / `depends_on` keep their semantics, and an
  error-only result dict is still a stage failure (`ari/pipeline/driver.py`).
  **The archive plugs in before or around the driver run at the paper entry,
  never inside a stage**: `run_paper_phase` (`ari/cli/paper_dispatch.py`),
  called from `ari/cli/projects.py` and `ari/cli/run.py`, either invokes the
  linear `generate_paper_section` itself or invokes
  `PaperArchiveRuntime.run_archive` with that same linear function handed in as
  the fallback callable.  No workflow stage constructs the archive, so a
  stage's fail-open exception boundary can neither swallow the archive nor be
  widened by it, and removing the archive removes a call site rather than
  editing the stage list.
- **BP-4 `% CLAIM:Cx:NCx` anchor survival.**  `write_paper_iterative` emits the
  anchors and `paper_refine` preserves them — anchor-dropping edits are
  rejected per pass, and net anchor loss keeps the original paper
  (`refined=False`).  The mirrored registries `claim_gate/latex.py` ↔
  `ari-skill-paper/src/claim_links.py` and `claim_gate/numeric.py` ↔
  `ari-skill-transform/src/claims.py` stay in sync.  Draft candidates must
  carry anchors so the winner passes the final gate.
- **BP-5 `ari-skill-paper` is not governed cross-process and is not edited for
  governance.**  It stays a stdio subprocess importing zero `ari.rqgm`
  (`ari-skill-paper/tests/test_writer_prompt_override.py` asserts the empty
  leak set); the governed prompts live in ari-core roles.  The skill's four
  prompt files are the `linear` source and are not moved.  The skill is the
  draft executor's hands (`write_paper_iterative` seeds, `paper_refine`
  refines); `review_compiled_paper` is **not** the archive scorer.
- **BP-6 `select_best_node` semantics are unchanged.**
  `ari/pipeline/verified_context.py` still prefers `has_real_data` and ranks by
  `_scientific_score`.  The archive seeds from that single winner; it does not
  change how the winner is chosen.  (The function additionally drops nodes that
  RQGM selective erasure marked `_valid_for_frontier: False` — a clause nothing
  writes on the default path, so it is inert there.)
- **BP-7 The existing `run_paper_candidate_escalation` hook is preserved.**  Its
  duck-typed `getattr(bfts, "rqgm", None)` detection, its fail-open contract,
  and its light-touch single-node behaviour stay (`ari/rqgm/runtime.py`, called
  from `ari/cli/paper_dispatch.py`); the archive composes with it — running it
  on the winning draft's node — and never removes it.
- **BP-8 Reviewer independence and structural merge.**  `review_compiled_paper`
  sees paper text only: it accepts `vlm_findings_json`, `experiment_summary`,
  and `figures_manifest_json` for workflow compatibility and discards them.
  `merge_reviews` is purely structural — no LLM call, inputs immutable,
  independent and evidence-grounded reviews reported in separate categories.
  The governed `paper_reviewer`'s same-role isolation must not weaken this
  (mirror `peer_review`).
- **BP-9 Opt-in independence.**  Exploration `ari.mode` and paper `paper.mode`
  are orthogonal — all four combinations are legal.  `resolve_paper_mode`
  (`ari/rqgm/paper_mode.py`) reads only `paper.mode` and `rqgm.paper.enabled`,
  never `ari.mode` / `rqgm.enabled`, and the exploration resolver likewise never
  reads the paper axis (mirror the `ari/rqgm/mode.py` VirSci-independence
  discipline).
- **BP-10 Cost is bounded by budget caps, not by topology.**  The bound comes
  from `rqgm.paper.archive.max_expansions` reaching BFTS `max_total_nodes`:
  `should_prune` returns `True` once the running total meets that cap, **before**
  and independently of the `node.depth >= max_depth` clause, in
  `ari/orchestrator/bfts.py` and again in the archive's own
  `PaperArchiveStrategy.should_prune`.  The node count is therefore capped at
  *any* depth and no branching factor can compound into `b^d`.  The other
  bounds are budget-shaped too: lazy LaTeX compile, one best node feeding one
  draft space, `full_governance_only_on_top_k`, per-epoch adversary and
  candidate caps, anchor scoring on a sample, epoch-amortised co-evolution.
  **This invariant does not pin the topology flat** — `archive.depth > 1` is the
  design (default 3), and changing `depth` or `width` is a tuning decision that
  leaves BP-10 intact so long as the expansion cap holds.  Only the caps are
  frozen here.
- **BP-11 Within-epoch freeze.**  The active writer/reviewer prompt hashes and
  the reviewer utility policy are frozen per epoch;
  `PaperArchiveRuntime._freeze_paper_utility_policy` runs once before the round
  loop, and co-evolution happens only at boundaries, through the
  `RegistryTransitionEngine` + `ConstitutionalKernel` `ensure_epoch` call at
  each round head — never mid-archive.
- **BP-12 Checkpoint hygiene.**  New files are registered in
  `PathManager.META_FILES` and, where they are fixed-name JSON, in the node
  report's `_INTERNAL_JSON_NAMES`; formatting is byte-fixed; no wall-clock,
  git SHA, or host value enters any hash; `hash12 = sha256[:12]` remains the
  single prompt-hash scheme; and `CONSTITUTION_HASH` is re-pinned on the
  amendment and asserted in `ari-core/tests/test_rqgm_kernel.py`.

Twelve, and only twelve.  A register that grows silently stops being a
compatibility contract and becomes a style guide, so a genuinely new paper-path
invariant is added by amending this list — and re-reviewing the change against
the amended list — rather than by being asserted somewhere else.

## Paper-archive cost model

The archive's cost is a closed symbolic form over config caps, with no
exponential term.  The form is useless without its symbols, so both are here.

| Symbol | Config knob | Default |
|---|---|---|
| **K** | `rqgm.paper.archive.width` — seed drafts at depth 1 (root branch factor) | 4 |
| **R** | `rqgm.paper.archive.refine_rounds` — refine children per draft | 2 |
| **M** | `rqgm.paper.archive.max_expansions` — **per-epoch** node budget → BFTS `max_total_nodes` | 12 |
| **E** | `rqgm.paper.epoch.rounds` — archive rounds per paper phase; one round = one paper epoch | 2 |
| **T** | `rqgm.governance.full_governance_only_on_top_k` | 3 |
| **A** | `rqgm.adversarial.max_adversary_calls_per_epoch` | 24 |
| **C** | `rqgm.prompt_evolution.max_total_candidates_per_epoch` | 4 |
| **S** | `rqgm.paper.anchor.sample_size` — held-out agreement sample | 8 |

Two further knobs appear in the forms without being budget symbols:
`rqgm.adversarial.max_attacks_per_node` (default 3) and
`rqgm.paper.archive.depth` (default 3, which appears in *no* term — that is the
point of BP-10).  All defaults above are the `ari-core/ari/configs/defaults.yaml`
values.

**Draft population per epoch.**

```text
N_draft = min( K · (1 + R), M )          # = min(4·3, 12) = 12 at defaults
```

**Per-epoch calls, by actor.**

```text
writer (skill)                        =  N_draft                     # seed + refine, one call per draft
paper_reviewer (governed)             =  N_draft                     # one score per draft
paper_self_preference (adversary)     =  min( A, |top-K ∪ paper_cand| · max_attacks_per_node )
co-evolution candidate generation     =  C            if prompt_evolution.enabled else 0
anchor utility scoring                =  C · S        if prompt_evolution.enabled and anchor.enabled else 0
LaTeX compiles (0 LLM)                ≤  T                           # lazy, top-K only
```

**Totals.**

```text
Calls(E) ≈ E · [ N_draft                            (reviewer)
               + min(A, T · max_attacks_per_node)   (adversary)
               + C + C·S                            (co-evolution + anchor) ]
         + E · N_draft                              (writer skill calls)

Tokens(E) ≈ Calls(E) · O(capped context)
```

`Tokens(E)` stays linear because every role's context view is a capped
projection — the `paper_reviewer` sees `{draft_manuscript, verified_context,
science_data, reference_context/anchor_case}`, each capped — so per-call tokens
are bounded and the token total scales with the call total.

Every factor — **K, R, M, E, T, A, C, S** — is a config cap, so `Calls(E)` grows
linearly in each tunable.  `archive.depth` moves no term: a deeper tree
redistributes the same `M` nodes rather than multiplying them, because the
total-node cutoff binds before the depth cutoff (BP-10).

### How the forms line up with the shipped loop

Four terms are enforced exactly as written; three are looser than what ships.
The differences all run in the safe direction — the shipped loop spends less
than the form allows — but a reader sizing a run from this model should know
which is which.

Enforced as written:

- **`N_draft`** is `archive_node_budget` in `ari/rqgm/paper_archive.py`, the
  same `min(width · (1 + refine_rounds), max_expansions)` expression, and it is
  the value `PaperArchiveStrategy` uses as its node budget in both
  `should_prune` and `expand`.
- **Writer = `N_draft`** — the round loop runs the draft executor once per
  draft, one `write_paper_iterative` or `paper_refine` call each.
- **Reviewer = `N_draft`** — the executor scores every draft exactly once.
- **`E`** is `rqgm.paper.epoch.rounds`, the round count of the co-evolution
  loop, and each round opens one epoch.

Looser than what ships:

- **The reviewer term counts scores, not necessarily LLM calls.**  Draft scoring
  is LLM-free unless `rqgm.paper.reviewer.agent_as_judge.enabled` is set
  (default `false`): without an injected score function the reviewer scores the
  venue rubric axes deterministically.  At stock defaults the reviewer
  contributes `N_draft` *governed scores* and **zero** model calls.
- **The anchor term is `S` per epoch, not `C · S`.**  The budget manager's cap
  for the `paper_anchor_scoring` action is `rqgm.paper.anchor.sample_size`
  counted per epoch (`ari/rqgm/budget.py`), and the shipped loop calls the
  anchor scorer once per round, on the *active* reviewer.  `C · S` is the
  stated design intent for per-candidate anchor scoring; no shipped call site
  scores candidates on the anchor.  `rqgm.paper.anchor.enabled` also defaults
  to `false`, which makes the cap `0`, so the term is absent from a stock run
  entirely.
- **Compiles are `≤ 1` per run, not `≤ T`.**  Only the best-belief winner is
  ever compiled, once, gated by `archive.compile_threshold`; `≤ T` is the
  design ceiling for a lazy top-K compile, not the shipped behaviour.
- **The adversary's `A` bound is enforced; its inner product is not the paper
  loop's shape.**  Each adversarial round is gated on the shared
  `adversary_call` budget, so `A` per epoch binds.  The
  `|top-K ∪ paper_cand| · max_attacks_per_node` factor is the inherited
  exploration engine's per-node fan-out (`ari/rqgm/adversarial/engine.py`); the
  paper loop instead fires one round per *over-accepted* draft found on the
  anchor corpus, still under the same `A`.

Consequently a stock-default run — `anchor.enabled: false`,
`agent_as_judge.enabled: false` — spends per epoch roughly `N_draft` writer
skill calls, `N_draft` LLM-free reviewer scores, at most `A` adversary calls,
and at most `C` co-evolution candidate generations, with one compile for the
whole run.  Turning the anchor and the agent-as-judge on is what makes the
reviewer and anchor terms cost model calls.

## Checkpoint file inventory

Full per-file behaviour (creation conditions, truth vs snapshot, resume
semantics) is documented in
[File Formats Reference](file_formats.md#rqgm-epoch-governance-files-opt-in-ari-rqgm-mode);
this table only maps files to schemas and owners.  Every fixed-name file
below is registered in `PathManager.META_FILES`, and every JSONL among them
except the two paper-archive ones (`paper_draft_archive.jsonl`,
`paper_anchor_corpus.jsonl`) is additionally in the `ari/paths.py`
trace-file set; the `proposals/` and `rqgm_prompts/` directories sit on the
node-report directory blocklist (`ari/orchestrator/node_report/builder.py`),
so none of them ever appear in a node's `files_changed`.

| Checkpoint path | Kind | Schema | Writer |
|---|---|---|---|
| `rqgm_state.json` | Mode-provenance snapshot (write-once) | none — shape owned by `ari/rqgm/state.py` (`schema_version`, `mode`, `rqgm_enabled`, `mode_source` ∈ `config\|env\|resume`, `created_at`, `switch_journal[]`) | `ari.checkpoint.save_rqgm_state_json` |
| `constitution.yaml` | Human-readable statement, copy-once from `ari-core/config/constitution.yaml` | none — authoritative rules are frozen code pinned by `constitution_hash` | `ari/rqgm/state.py` (`copy_constitution_if_missing`) |
| `rqgm_transitions.jsonl` | Append-only truth (hash-chained) | `rqgm_transition_event` | `ari/rqgm/store.py` |
| `rqgm_audit.jsonl` | Append-only audit log (independent chain) | envelope `rqgm_transition_event`; record payloads: `governance_report` (+ the motion-pipeline records), kernel reports, `epoch_transition` (+ retirement / clean-room-request records), `selective_erasure_event`, `frontier_rebuild_event`, `paper_utility_erasure` (paper-axis reviewer-replacement erasure), recomputed `rqgm_utility_record`, budget lines | governance / transition / repair engines (+ the paper-archive runtime) via the store |
| `epoch_state.json` | Derived snapshot | `epoch_state` | `ari.checkpoint.save_epoch_state_json` |
| `rqgm_registry.json` | Derived snapshot | `rqgm_registry` | `ari.checkpoint.save_rqgm_registry_json` |
| `proposals/proposal_records.jsonl` | Append-only truth | `proposal_record` (embeds `proposal_summary_view`) | `ari/rqgm/proposals/store.py` |
| `proposals/proposal_index.json` | Derived rollup | none (derived) | `ari/rqgm/proposals/store.py` |
| `rqgm_adversarial_cases.jsonl` | Append-only truth | `rqgm_attack_records` + `rqgm_utility_record` + replay-case lines | `ari/rqgm/adversarial/pool.py` |
| `rqgm/adversarial_replay_pool.json` | Derived snapshot | `rqgm_replay_pool` | `ari.checkpoint.save_adversarial_pool_json` |
| `prompt_evolution.jsonl` | Append-only truth | `rqgm_prompt_evolution` (embeds `rqgm_prompt_spec`) + `rqgm_utility_policy_candidate` (Task 14 rides the same log) | `ari/rqgm/prompt_records.py` |
| `prompt_specs.json` | Derived rollup | rollup of `rqgm_prompt_spec` | `ari.checkpoint.save_prompt_specs_json` |
| `rqgm_prompts/<prompt_id>.{md,json}` | Write-once evolved bytes (`.md` prompt templates; `.json` Task-14 policy bodies) | none — bytes pinned by `prompt_hash` | `ari/rqgm/prompt_loader.py` |
| `rqgm_cleanroom.jsonl` | Append-only truth | `clean_room_request` + `clean_room_bundle` | `ari/rqgm/clean_room.py` |
| `rqgm_erasure_state.json` | Derived snapshot | `erasure_state` | `ari.checkpoint.save_erasure_state_json` |
| `rqgm_meta_outputs.jsonl` | Append-only truth | `rqgm_meta` (`meta_agent_output_record`) | `ari/rqgm/meta_evolution.py` |
| `rqgm_governance_cache.jsonl` | Append-only cache | `rqgm_governance_cache` | `ari/rqgm/governance_cache.py` |
| `rqgm_eval_metrics.json` / `rqgm_injection_provenance.json` | Evaluation-harness artifacts (harness-launched runs only) | none — shapes owned by `ari/rqgm/evaluation/{metrics,injection}.py` | evaluation harness |
| `paper_archive_state.json` | Paper-phase mode-provenance snapshot (write-once, except the append-only `seed_journal[]` and the per-round `budget_counters` mirror) | none — shape owned by `ari/rqgm/paper_runtime.py` | `ari.checkpoint.save_paper_archive_state_json` |
| `paper_draft_archive.jsonl` | Append-only draft population (best-effort) | none — shape owned by `ari/rqgm/paper_archive.py` | `ari/rqgm/paper_draft_executor.py` |
| `paper_anchor_corpus.jsonl` | Read-only anchor corpus (write-once) | none — shape owned by `ari/rqgm/paper_anchor.py` | curation / bootstrap tooling |
| `rqgm/paper_self_preference_stat.json` | Derived per-epoch statistic (best-effort) | none — shape owned by `ari/rqgm/paper_self_preference.py` | `ari/rqgm/paper_self_preference.py` |

## See also

- [File Formats Reference](file_formats.md) — the checkpoint files these
  schemas validate.
- [Configuration Reference](configuration.md#execution-mode-and-rqgm-governance-opt-in)
  — the `ari.mode`, `rqgm.*`, and `proposal_router.*` blocks.
- [Execution Modes](../guides/execution_modes.md) — mode activation and
  the constitutional kernel.
- [RQGM Evaluation](../guides/rqgm_evaluation.md) — the ablation harness
  that consumes `rqgm_eval_metrics.json`.
- `ari-core/ari/schemas/README.md` — one-line index of every shipped
  schema.
