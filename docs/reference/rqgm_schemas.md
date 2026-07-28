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
  - path: ari-core/tests/test_rqgm_state_store.py
    role: test
last_verified: 2026-07-16
---

# RQGM Schema Reference

Formal JSON Schemas for every record the opt-in `ari_rqgm` execution mode
persists.  All of them ship under `ari-core/ari/schemas/` and are loaded by
basename via `ari.schemas.load(name)`.  None of these records exist on a
default `simple_bfts` checkpoint — every reader treats absence as "RQGM
never ran".

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
  event-hash and fingerprint function.
- **`epoch_fingerprint`** (`ari/rqgm/state.py`) —
  `hash12(canonical_json(EpochState payload))` with `created_at`
  (wall-clock metadata), the fingerprint field itself, and `status`
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

## Shared envelope (`rqgm_defs.schema.json`)

**Purpose:** the canonical shared `$defs` every RQGM record schema
references — the `rqgm_record_base` envelope, the closed status / role /
tier vocabularies, and the id/hash formats.  **Owning module:**
`ari/rqgm/events.py` (the Python mirror of the vocabularies).  The copies
of these `$defs` embedded in the other schema files are pinned byte-equal
to this file by `ari-core/tests/test_rqgm_state_store.py`.

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

- **Status lifecycle** (shared by prompts and components; legal
  transitions are the T1–T21 table in `ari/rqgm/transition_rules.py`):
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
  byte-identical); fixed (registered for provenance, constitutionally
  immutable): `constitutional_kernel`, `fixed_verifier`, `audit_log`.
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
| `schema_version` | const `1` |
| `event_id` | `evt_%06d`, per-checkpoint monotonic |
| `event_type` | Closed v1 set: `epoch_transaction_prepare`, `component_registered`, `prompt_registered`, `component_status_change`, `prompt_status_change`, `epoch_close`, `epoch_open`, `epoch_transaction_commit`, `emergency_quarantine` (the sole mid-epoch mutation) |
| `payload` | The event body — the only hashed part |
| `event_hash` | `hash12(canonical_json(payload))` |
| `prev_event_hash` | Chains to the previous line; `""` on the first |
| `ts` / `ts_iso` | Envelope metadata, outside the hash (P2) |

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
| `epoch_fingerprint` | `hash12` excluding `created_at`, `status`, and itself |
| `created_at` | Metadata; excluded from the fingerprint |

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
| `prompts[]` | Prompt entries: text referenced by source (`committed_template` key today; `checkpoint_file` for evolved prompts), `prompt_hash` (`hash12`) **and** full `prompt_sha256`; `spec_ref` is `null` in v1 |

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

## Adversarial-loop schemas (Task 06)

### `rqgm_attack_records.schema.json`

**Purpose:** the four attack-loop record shapes multiplexed into
`rqgm_adversarial_cases.jsonl` (and, as governance evidence, the audit
log).  **Owning module:** `ari/rqgm/adversarial/records.py` (shapes +
constructive-prevention builders), `ari/rqgm/adversarial/round.py` (the
per-node round).

| Record (`record_type`) | Id / role | Specific fields |
|---|---|---|
| `raw_attack` | `atk_%06d` / `adversary` | `adversary_type` (the shipped-schema enum is the closed seven-type exploration set: `overclaim`, `metric_gaming`, `prior_art`, `reproducibility`, `evidence_gap`, `cost_explosion`, `prompt_injection`; the paper phase adds an eighth, `paper_self_preference` — see [Paper-archive schemas](#paper-archive-schemas-paper-rqgm_archive-mode)); `target_artifact.type` (closed set: `proposal`, `experiment_plan`, `node_report`, `metric_result`, `paper_claim`, `novelty_claim`, `citation_claim`, `reproducibility_claim` — never a component); `attack_claim`; `attack_evidence_refs` (≥ 1 required); `severity_claimed`.  Audit material only — raw attacks never touch a score (invariant 8) |
| `defender_response` | `def_%06d` / `defender` | `raw_attack_id`; `stance` `rebut` \| `concede` \| `propose_fix` |
| `judgment_record` | `jdg_%06d` / `judge` | `raw_attack_id`; `verdict` `valid` \| `partially_valid` \| `invalid`; judge-assigned `severity` (`low`–`critical`); `defense_status`.  Always written, even for `invalid` |
| `validated_attack` | `vat_%06d` / `judge` | `case_type`, `raw_attack_id`, `judgment_id`, `validated`, `verdict`, `severity`.  Exists **only** for `valid` / `partially_valid` verdicts (adjudication required, invariant 9).  Carries the accountability binding — see below |

#### The accountability binding on `validated_attack`

Roles are **observed**; components are **bound**; and the binding is minted
**only after adjudication**.  The two target-shaped fields of a
`validated_attack` are not synonyms:

| Field | Value space | Who reads it |
|---|---|---|
| `affected_components` | ROLE names (`["reviewer"]`) — the plural observation of who is implicated.  A role is the only thing an attack can honestly know, and nothing sanctions a role.  (The name holds roles; it is kept unrenamed because renaming it would rewrite every stored record.) | the FailureSummary's `affected_roles` |
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

In the exploration (`ari_rqgm`) set the seven adversary types bind nothing:
the artifacts they attack are authored by the `generator` role, which has no
registered component (nothing stamps a `generator_v1` id), so their records
carry `affected_components: []` and no `target_component_id`.  The mechanism
is role-driven — the day an artifact-authoring role has a registered
incumbent, naming it binds those case types with no other change.

### `rqgm_utility_record.schema.json`

**Purpose:** one governed-utility audit record; the §5.4 penalty channel
is its sole v1 emitter, and frontier repair (Task 10) re-emits recomputed
records after erasure.  **Owning module:**
`ari/rqgm/adversarial/records.py` (emit) + `ari/rqgm/frontier_repair.py`
(recompute).

| Field | Notes |
|---|---|
| `record_id` | `utl_%06d` |
| `role` | const `utility_policy` |
| `node_id` / `base_score` / `penalty` / `final_score` | The penalty arithmetic per node |
| `input_refs` | `penalty > 0` **requires** ≥ 1 id in `input_refs.validated_attack_ids` (kernel check — raw attacks never score) |
| `utility_policy_hash` / `frozen_policy` | The epoch-frozen policy, embedded **by value** so recompute under the original weights is possible |
| `supersedes` / `recomputed_in_epoch` | Set only on Task-10 recomputed records; the superseded record stays on disk, stale |

### `rqgm_replay_pool.schema.json`

**Purpose:** the derived byte-fixed `rqgm/adversarial_replay_pool.json`
snapshot of the AdversarialReplayPool; `rqgm_adversarial_cases.jsonl`
stays the source of truth and fills any crash tail on load.  **Owning
module:** `ari/rqgm/adversarial/pool.py`; persisted via
`ari.checkpoint.save_adversarial_pool_json`.

| Field | Notes |
|---|---|
| `case_seq` | Monotonic case counter |
| `cases[]` | AdversarialReplayCase: `case_id` (`adv_case_%05d`), `case_type` (the seven-type set), `validated_attack_id`, `severity`, `admitted_epoch` / `last_confirmed_epoch`, `status` `active` \| `evicted` (eviction is logical-only), `replay_view` (full materials — denied to role `clean_room_generator`) and `abstract_view` (contamination-safe FailureSummary — no raw attack/defense text) |

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
| `evolvable` / `epoch_introduced` | Evolution eligibility + provenance |
| `spec` | The behavioural contract: `role_instruction`, `constitutional_constraints[]`, `input_contract.required_fields[]`, `output_schema`, optional `rubric` / `calibration_policy` / `budget_policy` |

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
`epoch_transition` record.  Every status change pins a fixed T1–T21
`rule_id` row of `ari/rqgm/transition_rules.py` (the T1–T19 base table plus
the role-scoped T20 / T21 supersession rows); only the
`rqgm.transition.*` numeric thresholds are configurable.  **Owning
module:** `ari/rqgm/transition_engine.py` — the sole registry status
writer (`produced_by` is const `registry_transition_engine`, kernel
CK-REG-004).

| Field | Notes |
|---|---|
| `epoch_transition_id` | `transition_%03d_to_%03d` |
| `status` | `pending` \| `committed` \| `aborted` \| `rejected` \| `failed` — an aborted/kernel-blocked transition is logged but applies **no** registry change |
| `emergency` | `true` is the sole mid-epoch shape (single sanction to quarantine) |
| `inputs` | Includes the `inputs_sha256` content hash of the frozen boundary inputs (GovernanceReport + candidate evaluations + registry hashes) so every committed change replays deterministically |
| `adoptions` / `sanctions` / `retirements` / `bans` | Status-change lists, each pinning a `rule_id` |
| `clean_room_requests` | Regeneration requests handed to Task 08 |
| `next_active_components` / `fallbacks` | The next epoch's frozen active set + no-vacancy fallbacks |
| `kernel_validation` (+ optional `kernel_violation`) | The kernel verdict on the transaction |

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
| `invalidated_node_ids` / `recompute_node_ids` / `abandoned_pending_node_ids` | Node dispositions |
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
plus the Task-14 supersession edge **T20** `superseded_by_adopted_successor`
(`ari/rqgm/transition_rules.py`; the sole `active → retired` edge, kernel-guarded
to `utility_policy` only) — never through this record.  The evolved policy body
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
`exploration_mode`, `seed_node_id`, `switch_journal[]`.  The persisted mode
wins on re-invocation — resume never silently flips the paper mode.  Writer:
`ari.checkpoint.save_paper_archive_state_json`.

### `paper_draft_archive.jsonl` — the scored draft population

Append-only, byte-fixed, best-effort (a record-write failure never breaks the
paper phase; an absent file reads as empty — a linear run leaves no archive).
Shape owned by `ari/rqgm/paper_archive.py` / `ari/rqgm/paper_draft_executor.py`:
one draft node per line — `schema_version`, `draft_id` / `node_id`, `kind`
(`seed` \| `refine`), `parent_draft_id`, `refine_pass`, `tex_path`,
`tex_sha256`, `writer_prompt_hash` (the framing / `diversity_bonus` key),
`reviewer_prompt_hash`, `review_score` (the governed `paper_reviewer` composite
— the frontier + best-belief ranking key), `suggested_revisions_ref`,
`anchors_preserved`, `decode_seed`, `epoch_id`, and the read-time flags
`is_best_belief` / `compiled` (updated in place by `mark_paper_draft_flags`).

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
`gate_bootstrap` labels is machine-enforced (it degrades to no held-out split,
never raises).  **Default OFF** (`anchor.enabled: false`): the degraded on-ramp
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

**The eighth adversary type.**  `paper_self_preference` is the eighth member of
the Python `ADVERSARY_TYPES` tuple (`ari/rqgm/adversarial/records.py`, the
write-path validity check `validate_raw_attack` uses), added for the paper
phase and inert off it; the shipped `rqgm_attack_records.schema.json`
`adversary_type` / `case_type` enum documents the seven **exploration** types.
A `paper_self_preference` case implicates the `paper_reviewer` role, which —
unlike the seven's `generator` — HAS a registered incumbent (`paper_reviewer_v1`
under the paper mode), so the Task-15 `target_component_id` binding fires and the
validated-attack → impeachment chain runs in production; off the paper phase the
role resolves to `""` and exploration stays byte-identical.

## Checkpoint file inventory

Full per-file behaviour (creation conditions, truth vs snapshot, resume
semantics) is documented in
[File Formats Reference](file_formats.md#rqgm-epoch-governance-files-opt-in-ari_rqgm-mode);
this table only maps files to schemas and owners.  Every file below is
registered by name in `PathManager.META_FILES` (the JSONL truths
additionally in the trace-file set), and the `proposals/` and
`rqgm_prompts/` directories sit on the node-report directory blocklist
(`ari/orchestrator/node_report/builder.py`), so none of them ever appear
in a node's `files_changed`.

| Checkpoint path | Kind | Schema | Writer |
|---|---|---|---|
| `rqgm_state.json` | Mode-provenance snapshot (write-once) | none — shape owned by `ari/rqgm/state.py` (`schema_version`, `mode`, `rqgm_enabled`, `mode_source` ∈ `config\|env\|resume`, `created_at`, `switch_journal[]`) | `ari.checkpoint.save_rqgm_state_json` |
| `constitution.yaml` | Human-readable statement, copy-once from `ari-core/config/constitution.yaml` | none — authoritative rules are frozen code pinned by `constitution_hash` | `ari/rqgm/state.py` (`copy_constitution_if_missing`) |
| `rqgm_transitions.jsonl` | Append-only truth (hash-chained) | `rqgm_transition_event` | `ari/rqgm/store.py` |
| `rqgm_audit.jsonl` | Append-only audit log (independent chain) | envelope `rqgm_transition_event`; record payloads: `governance_report` (+ the motion-pipeline records), kernel reports, `epoch_transition` (+ retirement / clean-room-request records), `selective_erasure_event`, `frontier_rebuild_event`, recomputed `rqgm_utility_record`, budget lines | governance / transition / repair engines via the store |
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
| `paper_archive_state.json` | Paper-phase mode-provenance snapshot (write-once) | none — shape owned by `ari/rqgm/paper_runtime.py` | `ari.checkpoint.save_paper_archive_state_json` |
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
