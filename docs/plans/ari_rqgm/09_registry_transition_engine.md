# Task 09: RegistryTransitionEngine

> **Status**: planned · **Depends on**: 00, 02, 04, 05, 07 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

> **Implemented amendment (2026-07-28):** T16 is no longer a mid-epoch
> exception. It force-closes the current epoch and atomically commits the
> quarantine plus a freshly fingerprinted epoch-open in the same boundary
> transaction. Any older “sole mid-epoch edge” wording below is retained only
> as planning history and is superseded by the permanent architecture and
> schema references.

## 1. Purpose

ARI-RQGM promotes, demotes, quarantines, and retires prompt-defined components
(generator / reviewer / adversary / defender / judge / router / prompt mutator /
clean-room generator / replay selector). Today nothing in ARI changes which prompt
version a role uses at run time; under `ari_rqgm` mode, the active component set
must be able to change — but only in a controlled, auditable, epoch-boundary
transaction, and only through one engine.

This task designs the **RegistryTransitionEngine**: the single component allowed
to change `status` fields in PromptRegistry / ComponentRegistry (Task 02). It
consumes the `GovernanceReport` (Task 05) and `CandidateEvaluation` results
(Task 07), resolves them deterministically against a **fixed, non-evolving state
transition table**, produces an `EpochTransition` record, has it validated by the
ConstitutionalKernel (Task 04), and commits it atomically at the epoch boundary.
Emergency quarantine is designed here as the **sole** mid-epoch exception.

Global invariants owned or enforced by this task: #1 (active set fixed within an
epoch), #2 (updates only at epoch boundary, except constitutional emergency),
#10 (registry status updates happen only through RegistryTransitionEngine),
#11 (every transition validated by ConstitutionalKernel), #16/#17 (the transition
rule itself is part of the fixed constitutional layer and never evolves).

## 2. Scope

- The complete component/prompt **state machine**: statuses, allowed edges,
  triggering inputs, and guards (Section 5.2).
- The **EpochTransition** schema and its decomposition into Task 02's
  transitions event log (Section 6).
- `RegistryTransitionEngine` public API: `resolve_transition`, `apply`,
  `emergency_quarantine`, `allowed_transitions` (Section 7).
- **Epoch-boundary transaction semantics**: resolve → kernel-validate → prepare →
  apply → commit, with crash/resume recovery on ARI's flat-file checkpoint state
  (Section 5.3).
- **Emergency quarantine** semantics: trigger class, fallback policy, audit
  record, and why nothing else may run mid-epoch (Section 5.4).
- Deterministic (LLM-free) resolution rules and their config thresholds.
- Wiring into `ari_rqgm` mode only; `simple_bfts` constructs nothing.

## 3. Non-goals

- Registry **schemas** themselves (PromptRegistry / ComponentRegistry / EpochState
  are Task 02; this task only writes their `status` fields through the Task 02 API).
  Likewise the persistence layer: the `rqgm_transitions.jsonl` event format
  (hash-chained typed events) and the combined `rqgm_registry.json` snapshot are
  Task 02 §5.1/§5.6/§6; this task supplies event payloads, not file formats.
- Producing the inputs: GovernanceReport assembly, impeachment, adjudication
  (Task 05); candidate replay/anchor/shadow evaluation (Task 07); clean-room
  request content (Task 08 — this task only *emits* `CleanRoomGenerationRequest`
  stubs on retirement).
- Consequences of retirement on the search tree: staling records and rebuilding
  the frontier is Task 10 (FrontierRepairEngine); this task hands it the committed
  `EpochTransition`.
- ConstitutionalKernel internals (Task 04) — this task defines *what* the
  TransitionValidator must check, not how the kernel is built.
- Meta-tier authority rules (Task 11) beyond honoring `tier` in guards.
- Any LLM-driven judgment. The engine is deterministic by design (see 5.1).
- Any change to BFTS behavior, `simple_bfts` mode, or VirSci; nothing here is
  enabled by default.

## 4. Existing ARI touchpoints

All paths repo-relative; verified to exist on branch `RQGM`.

- `ari-core/ari/orchestrator/lineage_decision.py` — the closed action set
  `VALID_ACTIONS = {continue, switch_to_idea, fanout, terminate}` with
  `_parse_decision` rejecting unknown actions is the repo's precedent for a
  **closed transition vocabulary with safe degradation**; `append_decision_log`
  (append-only `lineage_decisions.jsonl`, self-contained records, never raises)
  is the template Task 02 follows for the transitions log.
- `ari-core/ari/cli/bfts_loop.py:_run_loop` — the outer `while` head is the epoch
  boundary where `apply` will be invoked (per Task 05's boundary hook); the
  lineage-decision hook block (~lines 721–827) is the working pattern:
  config-gated, deterministic-rule-first, best-effort, JSONL audit.
- `ari-core/ari/cli/lineage.py:_mark_parent_terminated` — precedent for an
  additive, forward-signaling status write (`meta.json:parent_terminated`) read
  back as a hard launch gate in `ari-core/ari/viz/api_orchestrator.py`; the
  quarantine/retired statuses use the same "write once, gate everywhere" shape.
- `ari-core/ari/prompts/registry.py` (`PromptRegistry`, `PromptEntry`) and
  `ari-core/ari/prompts/_provenance.py` (`hash12`, `record_prompt_use`) — the
  existing prompt identity layer. `prompt_hash` in every transition **is** the
  existing `hash12 = sha256(text)[:12]`; no second hash scheme.
- `ari-core/ari/config/__init__.py` — `ARIConfig` gains the typed `rqgm` block in
  Task 01; this task adds `rqgm.transition.*` thresholds under it. Note
  `load_config` filters unknown top-level keys, so config must ride the typed
  block, not a raw `rqgm:` YAML key.
- `ari-core/ari/configs/defaults.yaml` + `FilesystemConfigLoader` — sanctioned
  home for numeric transition defaults (probation length, escalation counts).
- `ari-core/ari/core.py:build_runtime` — composition root; the engine is
  constructed here only when `cfg.ari_mode == "ari_rqgm"`, following the
  `hpc_enabled` conditional-wiring precedent (~lines 138–144).
- `ari-core/ari/paths.py:PathManager.META_FILES` / `_TRACE_FILES` —
  `rqgm_transitions.jsonl` and Task 02's registry snapshot (`rqgm_registry.json`)
  are registered here **by Task 02**; this task adds no new checkpoint filenames.
- `ari-core/ari/checkpoint.py` — byte-fixed snapshot-writer pattern
  (`indent=2, ensure_ascii=False`) that Task 02's registry snapshot rewrites
  follow; `ari-core/ari/protocols/stores.py` — home of Task 02's `EpochStore`
  Protocol (next to `TraceStore`/`CheckpointStore`); this engine consumes Task
  02's `RqgmStateStore.begin_transaction` / `EpochTransaction` API rather than
  defining a second store.
- `ari-core/ari/schemas/node_report.schema.json` — sibling location for the new
  `epoch_transition.schema.json`, loadable via `ari.schemas.load`.
- `ari-core/ari/_factory.py:BaseRegistry` — if transition *policies* are ever
  string-keyed in config, this is the sanctioned registry + Literal parity-test
  pattern. (Default: no pluggable policies; the table is fixed.)
- `ari-core/ari/orchestrator/bfts.py` / `ari-core/config/workflow.yaml` — read-only
  context: the engine never touches BFTS state; frontier consequences flow through
  Task 10.
- `ari-core/ari/trace_store.py` — the dormant `append_trace` seam noted for
  per-node audit; the transitions log deliberately does **not** use it (transitions
  are checkpoint-level, not node-level).

## 5. Proposed design

### 5.1 Position and determinism stance

Per the spec's layer design, the **transition rule is Layer 0 (fixed
constitutional layer)** — "components that judge evolve; the constitutional rules
that permit/deny evolution do not evolve." Consequences:

1. `resolve_transition` is a **pure deterministic function** of
   `(epoch_state, governance_report, candidate_evaluations, registries, config)`.
   No LLM calls, no wall clock in any decision, no randomness. All judgment
   already happened upstream (GovernanceOrchestrator adjudication, Task 05;
   candidate evaluation, Task 07). Given identical inputs, the produced
   `EpochTransition` is byte-identical (P2).
2. The transition table lives in a fixed-layer module
   (proposed: `ari-core/ari/rqgm/transition_rules.py`), imported by **both** the
   engine and the kernel's TransitionValidator — single source of truth, no
   duplication drift. It is not an evolution target and not config-swappable;
   only numeric thresholds (Section 6.3) are configurable.
3. Timestamps appear in records for audit but never in hashes or decisions.

### 5.2 State machine

Statuses are **exactly Task 02's shared `$defs` status enum** (02 §6 owns the
enum; every RQGM record `$ref`s it) — 10 values, and this task defines no
additional statuses (closed `str` Enum, forward-compat rule: an **unknown status
read from a registry file is treated as ineligible for the active set** and
logged — never crashes, mirroring `_parse_decision`'s unknown-action handling):

```
candidate, validated, shadow, probationary_active,
active, warning, probation, quarantine, retired, banned
```

Semantics notes: `warning` and `probation` are **serving states** — the component
remains in the epoch's active set (invariant 1 is not violated; only its
governance posture changes and only at a boundary). `quarantine` removes the
component from the serving set. There is no separate `rejected` status
(Task 02's enum is closed at these 10 values): candidates or shadows that fail
out without ever serving take `retired` as their terminal disposition (T2/T5),
with the rejection reason carried in the event payload and **no**
RetirementEvent / CleanRoomGenerationRequest emitted — those are exclusive to
T17. Never-served `prompt_hash`es entering Task 10's staling set is a harmless
no-op (no dependent frontier records exist). `banned` is absorbing.

**Complete state-transition table.** Edges marked ⚖ are the spec-mandated spine;
unmarked edges are the auxiliary recovery/rejection edges required for the
machine to be total. Every edge additionally carries the three universal guards:
(G1) only RegistryTransitionEngine may write the status; (G2) the edge is inside
a committed epoch-boundary transaction — except the single ⚡ emergency edge;
(G3) `ConstitutionalKernel.validate_transition` passed.

| # | From | To | Triggering input | Edge-specific guards |
|---|------|----|------------------|----------------------|
| T1 ⚖ | candidate | validated | `PromptCandidateValidation` (Task 07): static validation + constitutional validation + schema dry-run all pass | per-role candidate cap (`max_candidates_per_role_per_epoch`) not exceeded; PromptSpec `constitutional_constraints` present |
| T2 | candidate | retired | Any blocking validation failure, or candidate expiry (`candidate_max_age_epochs`) | terminal never-served rejection (no RetirementEvent / clean-room request — T17-only); failure summary retained for Task 08 |
| T3 ⚖ | validated | shadow | Replay evaluation ≥ `replay_pass_threshold` on ≥ `replay_min_cases`; anchor evaluation shows no regression vs incumbent | shadow slot available within `max_shadow_calls_per_epoch`; boundary only |
| T4 | shadow | validated | Insufficient shadow samples (`shadow_min_samples` not reached) after `shadow_max_epochs` | bounded retries (`shadow_retry_limit`); beyond limit → T5 |
| T5 | shadow | retired | Shadow agreement/quality below `shadow_pass_threshold` with sufficient samples | terminal never-served rejection, as T2 |
| T6 ⚖ | shadow | probationary_active | GovernanceReport shadow section: agreement/quality ≥ `shadow_pass_threshold` over ≥ `shadow_min_samples` live-shadow comparisons | role has an opening (incumbent in probation/quarantine/retired, or role unfilled); at most one adoption per role per boundary; boundary only |
| T7 ⚖ | probationary_active | active | GovernanceReport: zero upheld `ValidatedAttackRecord`s attributing degradation to it; performance ≥ incumbent baseline over probation window | served ≥ `probation_min_epochs` full epochs; boundary only |
| T8 | probationary_active | quarantine | Upheld `ImpeachmentOutcome`, or reliability collapse in GovernanceReport | boundary, or ⚡ emergency (T16 conditions) |
| T9 ⚖ | active | warning | GovernanceReport reliability warnings; low-severity validated attacks (`severity ∈ {low}`) affecting the component | boundary only; component keeps serving |
| T10 ⚖ | active | probation | Repeated warnings (≥ `warning_escalation_count` consecutive epochs) or medium-severity validated attacks | boundary only; component keeps serving under intensified shadow comparison |
| T11 ⚖ | active | quarantine | Upheld `ImpeachmentOutcome` (Task 05 adjudication), or high/critical-severity validated attack pattern attributed by GovernanceReport | boundary, or ⚡ emergency (T16); removed from serving set; fallback per 5.4 |
| T12 | warning | active | Clean epoch: no new warnings/attacks in GovernanceReport | boundary only |
| T13 | warning | probation | Recurrence within `warning_memory_epochs` | boundary only |
| T14 | probation | active | Rehabilitation: ≥ `probation_min_epochs` clean epochs while under intensified scrutiny | boundary only |
| T15 | probation | quarantine | Continued degradation or upheld impeachment | boundary, or ⚡ emergency (T16) |
| T16 ⚡ | probationary_active \| active \| warning \| probation | quarantine | **Emergency**: a deterministic ConstitutionalKernel critical violation record naming the component (see 5.4 trigger class) | THE ONLY MID-EPOCH EDGE; requires `transition.emergency == true` + attached kernel violation record; performance signals never qualify |
| T17 ⚖ | quarantine | retired | Adjudication confirmed at boundary: ReplayBoard confirmation over ≥ `retirement_replay_min_cases` replay cases (`max_cases_for_retirement` budget) upholds the impeachment | boundary only; emits `RetirementEvent` + `CleanRoomGenerationRequest` stub; hands retired `prompt_hash` set to Task 10 |
| T18 | quarantine | probationary_active | Exoneration: GovernanceSelfAudit or AdjudicationPanel overturns the impeachment | boundary only; re-enters under probation, never directly to active |
| T19 ⚖ | retired | banned | Contamination/critical finding: e.g. prompt-injection content, audit-log tampering attribution, or repeated clean-room-descendant failure traced to its lineage | boundary only; absorbing; bans reuse of its text and few-shots as clean-room reference beyond the abstract failure summary (Task 08) |

Everything not listed is **forbidden** — notably: `candidate → active` (no
instant activation, invariant 15), any `retired → {active, shadow, ...}`
resurrection, any edge out of `banned`, any in-place substitution of prompt text
without a status edge (invariant 3), and any edge written by an actor other than
the engine (invariant 10; Judge writing the registry is a named kernel violation).
The kernel's TransitionValidator rejects the full complement set: the test suite
enumerates the |S|×|S| matrix and asserts exactly the 19 rows above are
accepted as THIS plan's base table (the shipped `TRANSITION_TABLE` is T1–T21:
these 19 plus the role-scoped amendments T20/T21, see §5.2's amendment note)
(Section 9).

> **Given a permanent home, 2026-08-22.** This table is no longer the only copy.
> The shipped T1–T21 table — every row's triggering input, its edge-specific
> guards, the three universal guards, the T16 `(from, to)` encoding decision, and
> the forbidden-complement rule — is reproduced in
> [`docs/reference/rqgm_schemas.md`, "The fixed transition table"](../../reference/rqgm_schemas.md#the-fixed-transition-table),
> in all three languages
> ([ja](../../ja/reference/rqgm_schemas.md#固定遷移表) ·
> [zh](../../zh/reference/rqgm_schemas.md#固定转换表)), and
> [`docs/concepts/rqgm_architecture.md`, "The epoch cycle"](../../concepts/rqgm_architecture.md#the-epoch-cycle)
> links to it. The permanent copy is written against the shipped
> `TRANSITION_TABLE` (21 rows, T20/T21 included), so where it and the 19-row
> planning table above differ, the permanent page is the one to read. Nothing
> above is amended: the §5.2 text stays as the record of what was designed.

### 5.3 Epoch-boundary transaction semantics

The transition commits as a five-step transaction at the `_run_loop` epoch
boundary (main thread, after `governance_orchestrator.audit_epoch`, before the
next epoch's active-set freeze — matching the spec's core-algorithm ordering):

```
1. FREEZE INPUTS   Snapshot + hash the inputs: governance_report_ref (+ sha256),
                   candidate_evaluation_refs (+ sha256), current registry
                   snapshot hashes, epoch_id. These hashes go into the
                   EpochTransition so it is auditable and replayable.
2. RESOLVE         transition = engine.resolve_transition(...)  # pure, no I/O
3. VALIDATE        constitutional_kernel.validate_transition(transition,
                   registry, epoch_state). Any blocking violation → transition
                   status = "aborted", logged, NO registry change, next epoch
                   starts with the previous active set unchanged (fail-safe:
                   keep serving the incumbent set — never an empty set).
4. PREPARE         Open the Task 02 boundary transaction:
                   store.begin_transaction(transition_id) appends the
                   epoch_transaction_prepare event to
                   {ckpt}/rqgm_transitions.jsonl. The log format — hash-chained
                   typed events (evt_%06d, event_hash/prev_event_hash) — is
                   owned by Task 02 (§5.6/§6 there); this task adds no second
                   format and writes no full-EpochTransition lines.
5. APPLY + COMMIT  (a) decompose the EpochTransition into one per-change
                   component_status_change / prompt_status_change event per
                   adoption/sanction/retirement/ban and submit each via
                   EpochTransaction.add (payloads supplied by this engine:
                   transition_id, rule_id, from/to status, evidence_refs, and
                   the step-1 input hashes — Task 02 §5.6 step 2 delegates
                   change-event payload content to this engine);
                   (b) emit RetirementEvent / CleanRoomGenerationRequest records;
                   (c) next_active_components enters the next EpochState via
                   Task 02's epoch_close/epoch_open events (Task 02 freeze);
                   (d) commit: the Task 02 store appends the
                   epoch_transaction_commit event and rewrites the derived
                   rqgm_registry.json + epoch_state.json snapshots (byte-fixed
                   formatting).
                   Then control passes to FrontierRepairEngine (Task 10) and
                   constitutional_kernel.validate_frontier.
```

**Atomicity and crash recovery on flat files.** ARI has no transactional store;
atomicity is Task 02's crash-recovery rule: on load, events after an
`epoch_transaction_prepare` without its matching `epoch_transaction_commit` are
discarded — the transaction never happened and the previous epoch is still open.
On `ari resume` the run loop reaches the boundary again and re-runs
resolve → validate → apply; because `resolve_transition` is deterministic (§5.1)
over the same frozen inputs, the re-run reproduces a byte-identical
`EpochTransition`. `apply` additionally guards against double-commit: a
`transition_id` whose commit event already exists in the log is a no-op. This
rides the "JSONL is truth, snapshot is derived" precedent (prompt_trace →
prompt_versions) that Task 02 §5.1 adopts — a torn snapshot write can never
corrupt governance state because snapshots are rebuilt from replay. The
registries are never half-written from two epochs: apply runs on the main thread
at the boundary only, and shares no lock with `save_tree_incremental` (separate
file set, separate lock).

**Mid-epoch immutability.** Between commits, registry `status` fields are frozen;
the kernel's epoch-invariance check (Task 04) compares the frozen active-set
hash recorded in EpochState against every record's `prompt_hash`/`component_id`
during the epoch, so any out-of-band mutation is detected even if some code path
bypassed the engine. Mode switching is likewise forbidden mid-transaction
(spec: "Forbidden in principle: ... mid registry transition").

### 5.4 Emergency quarantine — the only mid-epoch exception

- **Trigger class (closed, deterministic):** only ConstitutionalKernel critical
  violation records qualify — active-prompt `prompt_hash` mismatch, audit-log
  tampering attributable to the component, out-of-scope access / retired-prompt
  text access, forged role authority (e.g. a component writing records reserved
  to EvidenceClerk/Auditor). **Never** performance signals, reviewer opinions,
  raw adversary attacks (invariant 8), or any LLM output. Performance concerns
  always wait for the boundary.
- **Mechanics:** `engine.emergency_quarantine(violation, component_id,
  epoch_state)` produces a minimal single-sanction `EpochTransition` with
  `emergency: true` and the violation record attached; the kernel's
  TransitionValidator accepts a mid-epoch commit **only** for this shape (single
  target, target status `quarantine`, `emergency` flag, attached kernel violation
  of a critical class). It is logged to the same transitions log as a single
  Task 02 `emergency_quarantine` event (a reserved type in Task 02's closed
  event set), bracketed by the same prepare/commit transaction protocol.
- **Fallback policy (no empty roles, run never crashes — run-loop discipline
  I-2):** the role falls back to (1) the most recent prior `active` version of
  the role still in an eligible status, else (2) the committed baseline `.md`
  prompt for the role (the `simple_bfts` default, which always exists). The
  fallback assignment is part of the same emergency transition record.
- **Aftermath:** records produced by the component in the current epoch between
  the violation and the quarantine commit are marked `suspect` (a flag consumed
  by Task 05's next audit and Task 10's staleness pass); final disposition
  (T17 retire / T18 exonerate) happens at the next boundary through the normal
  transaction.

### 5.5 Mode gating

- `simple_bfts` (default): the engine class is **never constructed**
  (`build_runtime` conditional, `hpc_enabled` precedent). No registry snapshots,
  no transitions log, no new files appear in the checkpoint. Existing behavior
  byte-identical.
- `ari_rqgm`: constructed in `build_runtime`, invoked only from the epoch
  boundary hook (Task 05) and the kernel's emergency path.
- VirSci on/off is orthogonal: the engine treats VirSciAdapter as one more
  registered component when present; with `virsci.enabled=false` no VirSci
  component/prompt is ever registered, so no transition can reference it.

## 6. Data structures / schema changes

### 6.1 `EpochTransition` (new; JSON Schema `ari-core/ari/schemas/epoch_transition.schema.json`)

```json
{
  "epoch_transition_id": "transition_004_to_005",
  "schema_version": 1,
  "from_epoch": "epoch_004",
  "to_epoch": "epoch_005",
  "created_at": "2026-07-05T00:00:00Z",
  "status": "pending",
  "emergency": false,
  "inputs": {
    "governance_report_ref": "governance_report_epoch_004",
    "governance_report_sha256": "...",
    "candidate_evaluation_refs": ["cand_eval_reviewer_prompt_v5"],
    "candidate_evaluation_sha256s": ["..."],
    "prompt_registry_sha256": "...",
    "component_registry_sha256": "..."
  },
  "adoptions": [
    {"component_id": "reviewer_v5", "prompt_id": "reviewer_prompt_v5",
     "prompt_hash": "a1b2c3d4e5f6", "role": "reviewer", "tier": "institutional",
     "from_status": "shadow", "to_status": "probationary_active",
     "rule_id": "T6", "evidence_refs": ["shadow_eval_00012"]}
  ],
  "sanctions": [
    {"component_id": "generator_v2", "from_status": "active",
     "to_status": "warning", "rule_id": "T9",
     "evidence_refs": ["adv_case_00042"], "severity": "low"}
  ],
  "retirements": [
    {"component_id": "reviewer_v3", "prompt_hash": "0f9e8d7c6b5a",
     "from_status": "quarantine", "to_status": "retired", "rule_id": "T17",
     "retirement_event_id": "retire_00042",
     "evidence_refs": ["impeach_00007", "replay_board_00003"]}
  ],
  "clean_room_requests": [
    {"request_id": "cleanroom_req_00042", "target_role": "reviewer",
     "retirement_event_id": "retire_00042"}
  ],
  "bans": [],
  "next_active_components": {"reviewer": "reviewer_v5", "generator": "generator_v2"},
  "fallbacks": [],
  "kernel_validation": {"passed": true, "checks_run": ["..."], "violations": []}
}
```

Every entry carries the spec-mandated record envelope (`record_id` = the
transition id, `epoch_id`, `component_id`, `prompt_hash`, `role`, `created_at`,
`source_refs` = `evidence_refs`, `status`). `rule_id` pins each change to a table
row (T1–T21, i.e. this §5.2 base table plus the T20/T21 amendments) so audits
are mechanical. `prompt_hash` is the existing `hash12`.

### 6.2 Files (all checkpoint-scoped and owned by Task 02, which registers them in `META_FILES` / `_TRACE_FILES` and node-report blocklists; this task adds no new checkpoint filenames)

| File | Pattern | Writer |
|---|---|---|
| `{ckpt}/rqgm_transitions.jsonl` | append-only JSONL of hash-chained typed events — format owned by Task 02 (§5.6/§6 there) | Task 02 store (`RqgmStateStore`); this engine supplies the per-change and emergency event payloads |
| `{ckpt}/rqgm_registry.json` | single combined ComponentRegistry+PromptRegistry snapshot, rewrite, byte-fixed (Task 02 §5.1: one file keeps the two registries transactionally consistent) | Task 02 store, rewritten at commit (step 5d), triggered only from `apply` |
| `{ckpt}/epoch_state.json` | Task 02 snapshot | `next_active_components` enters via the `epoch_open` event during step 5(c) |

### 6.3 Config (typed, under Task 01's `RQGMConfig`; numeric defaults in `ari-core/ari/configs/defaults.yaml`)

```yaml
rqgm:
  transition:
    replay_pass_threshold: 0.8
    replay_min_cases: 4
    shadow_pass_threshold: 0.7
    shadow_min_samples: 5
    shadow_max_epochs: 2
    shadow_retry_limit: 1
    probation_min_epochs: 1
    warning_escalation_count: 2
    warning_memory_epochs: 3
    retirement_replay_min_cases: 8      # ≤ replay.max_cases_for_retirement (Task 12)
    candidate_max_age_epochs: 3
    max_adoptions_per_role_per_boundary: 1
```

Thresholds are the **only** tunable part; the table topology is fixed code.

## 7. API / class changes

New module (proposed `ari-core/ari/rqgm/transition_engine.py`; not exported via
`ari.public.*`, so no public-API contract-snapshot churn):

```python
# ari/rqgm/transition_rules.py  — Layer 0, fixed, imported by engine AND kernel
class ComponentStatus(str, Enum): ...           # the 10 statuses of §5.2 ==
                                                # Task 02's shared $defs enum
                                                # (parity test against 02 §6)
TRANSITION_TABLE: dict[tuple[str, str], TransitionRule]  # T1..T21 (19 base + T20/T21)
EMERGENCY_EDGE: frozenset[tuple[str, str]]      # the T16 shapes

@dataclass(frozen=True)
class TransitionRule:
    rule_id: str                 # "T6"
    trigger: str                 # machine-readable trigger kind
    guards: tuple[str, ...]      # guard predicate names (all deterministic)
    boundary_only: bool          # False only for T16

# ari/rqgm/transition_engine.py
class RegistryTransitionEngine:
    def __init__(self, config: RQGMTransitionConfig, kernel: ConstitutionalKernel,
                 prompt_registry, component_registry,
                 store: RqgmStateStore): ...   # Task 02's store (§7 there)

    def resolve_transition(self, *, epoch_state, governance_report,
                           candidate_evaluations) -> EpochTransition:
        """Pure and deterministic. No I/O, no LLM, no clock in decisions."""

    def apply(self, transition: EpochTransition) -> AppliedTransition:
        """Kernel-validated prepare→per-change-events→commit via the Task 02
        transaction (§5.3). Double-commit of a transition_id is a guarded
        no-op; interrupted transactions are discarded by Task 02 replay and
        re-run deterministically at the restored boundary."""

    def emergency_quarantine(self, *, violation: KernelViolation,
                             component_id: str, epoch_state) -> EpochTransition:
        """The only mid-epoch path (§5.4). Single-sanction, kernel-gated."""

    @staticmethod
    def allowed_transitions(status: str) -> frozenset[str]: ...

# Persistence: no new store Protocol. The engine consumes Task 02's
# RqgmStateStore / EpochTransaction API (EpochStore Protocol in
# ari/protocols/stores.py, defined by Task 02):
#   with store.begin_transaction(transition_id) as txn:  # prepare event
#       txn.add(event)                                   # per-change events
#   # epoch_transaction_commit event + derived-snapshot rewrite on exit
```

Changed call sites: `ari-core/ari/core.py:build_runtime` (conditional
construction, object attached to the RQGM controller — the 6-tuple return shape
is untouched); the Task 05 epoch-boundary hook in
`ari-core/ari/cli/bfts_loop.py:_run_loop` calls
`resolve_transition` → `apply`; `ari resume` needs no engine-side recovery hook —
Task 02's replay discards uncommitted prepare events and the restored boundary
re-runs `resolve_transition` → `apply` deterministically. Kernel (Task 04) imports
`transition_rules` for its TransitionValidator. Zero CLI-surface change
(config-only activation), so no contract-snapshot regeneration.

## 8. Migration / compatibility

- **`simple_bfts` unchanged, byte-for-byte**: engine never constructed; no new
  files; no imports on the hot path beyond a config check. Smoke-diff test
  asserts the checkpoint file set is identical to pre-RQGM.
- **No changes to frozen contracts**: `tree.json`/`nodes_tree.json`/
  `results.json` names and key order untouched; `Node.to_dict()` untouched;
  frontier consequences (staling) go through Task 10's `Node.metrics` convention,
  not through this engine.
- **Resume**: all transition state is checkpoint-scoped (`rqgm_transitions.jsonl`
  + Task 02 snapshots), so `ari resume` restores it via Task 02 replay without
  touching the contract-frozen `tree.json`; interrupted commits are discarded by
  Task 02's prepare-without-commit rule and re-run deterministically at the
  restored boundary.
- **Forward compat of statuses**: readers treat unknown statuses as
  ineligible-for-active + warn (closed-set degradation, `_parse_decision`
  precedent), so older code reading newer registries degrades safely.
- **New filenames registered** in `PathManager.META_FILES` / `_TRACE_FILES` and
  node-report blocklists so node work dirs and `files_changed` stay clean.
- **VirSci off**: no VirSci component registered ⇒ no transition can name it;
  all engine tests run without VirSci installed.
- Best-effort/fail-safe posture: an aborted or failed transaction leaves the
  previous active set serving; governance failure degrades, never crashes the
  run loop (run-loop hook discipline), with the deliberate exception that a
  *kernel-rejected* transition must not be applied (fail-closed on apply,
  fail-open on run continuation).

## 9. Tests

Unit (pure, no LLM, no network; live under `ari-core/tests/`):

1. **Table exhaustiveness**: enumerate the full 10×10 status matrix; assert
   exactly the edges of §5.2 plus the T20/T21 amendments (21 in the shipped
   table) are accepted by `allowed_transitions` and by the
   kernel's TransitionValidator; assert named forbidden edges
   (candidate→active, retired→active, banned→anything, active→retired directly)
   are rejected with distinct violation codes.
2. **Determinism**: `resolve_transition` twice on identical fixture inputs →
   byte-identical serialized `EpochTransition` (P2).
3. **Guard coverage**: one fixture per rule T1–T21 exercising its trigger and at
   least one guard failure (e.g. T6 without `shadow_min_samples`; T7 before
   `probation_min_epochs`; T17 below `retirement_replay_min_cases`).
4. **Boundary-only enforcement**: a non-emergency transition submitted mid-epoch
   (epoch_state says epoch open) is rejected by the kernel; **an emergency
   transition with a non-critical trigger is rejected**; an emergency transition
   naming two components is rejected (single-sanction shape).
5. **Transaction/crash recovery**: simulate crash after the prepare event,
   before the commit event → Task 02 replay discards the uncommitted events and
   the re-run boundary produces a byte-identical `EpochTransition` and commits
   it; double-`apply` of a committed `transition_id` is a guarded no-op;
   aborted transition leaves registries byte-identical.
6. **Emergency fallback**: quarantining the only active reviewer falls back to
   the prior active version, else the baseline `.md`; the fallback appears in
   the transition record; no role is ever left empty.
7. **Actor separation**: a direct registry status write not going through the
   engine is detected by the kernel epoch-invariance check (integration with
   Task 04 fixtures).

Integration / regression:

8. **simple_bfts regression**: run the existing loop smoke test with
   `mode: simple_bfts`; assert no `rqgm_*` files are created and existing
   checkpoint file bytes match the pre-RQGM golden.
9. **ari_rqgm smoke**: two-epoch stub run (mocked GovernanceReport +
   CandidateEvaluation) commits one adoption and one warning; transitions log
   shows prepare → per-change → commit event sequences (Task 02 format);
   `epoch_state.json` next active set matches `next_active_components`.
10. **META_FILES hygiene**: node work dirs contain no `rqgm_transitions.jsonl`;
    `node_report.files_changed` never lists RQGM files.
11. **No-VirSci environment**: full engine test module passes without VirSci
    installed.

## 10. Risks

- **Split-brain between EpochState and registries on crash.** Mitigated by
  Task 02's prepare/commit event protocol (uncommitted events discarded on
  replay) and snapshot-as-derived-rollup (snapshots rebuilt from the event log
  on mismatch); residual torn-snapshot writes are healed by replay, plus
  write-tmp-then-rename in the Task 02 store.
- **All versions of a role quarantined.** The baseline-`.md` fallback guarantees
  a serving prompt, but a systematically failing baseline would loop; bound with
  `warning_escalation_count`-style circuit breaker plus surfacing in the
  GovernanceReport (accepted residual risk, documented).
- **Table ossification vs. real needs.** The table is deliberately non-evolving;
  if experience demands new edges, that is a *constitutional amendment* = code
  change + test-matrix change + INDEX/permanent-doc update, never a config or
  runtime mutation. Risk: pressure to add a config escape hatch — explicitly
  rejected here.
- **Threshold gaming.** Evolving components could optimize against fixed
  numeric thresholds; partially mitigated because inputs are adjudicated
  (invariant 9) and the adversarial replay pool grows (Task 06); flagged for
  Task 13's failure-injection suite.
- **Score comparability across epochs** (bfts_core invariant I-11): adoptions
  change who scores future nodes; cross-epoch `_scientific_score` comparisons
  used by Rule A / stagnation detection become epoch-relative. This task keeps
  scoring-rule freeze *within* an epoch; the cross-epoch policy is resolved in
  Task 14, which repeals I-11 in favor of a policy frozen per epoch and
  rewritten at boundaries through the governed path. The `utility_policy` role
  rides this task's T-table via the T1→T3→T6 spine plus **one new role-scoped
  edge, T20** (`active → retired` supersession), added by Task 14 §5.5 as an
  amendment on 2026-07-16: the original "no new rule ids" decision could not
  fire on the happy path (T6 needs a role opening that a healthy passive policy
  never yields, and there was no `active → retired` edge), so the score-rewrite
  spine was dead. T20 is role-scoped and kernel-guarded
  (`supersession_successor_adopted`, `utility_policy_role_only`,
  `emits_retirement_event`; engine method `_maybe_supersede_utility_policy`),
  so **behavioural roles' guards and engine topology are unchanged** — but this
  task's table itself grows a row and its `constitution_hash` is re-pinned
  (Task 14 §5.5/§8). See also T21 (paper-role `active → shadow` supersession),
  added by [../ari_rqgm_paper/03](../ari_rqgm_paper/03_writer_reviewer_governed_roles.md)
  §5.9 on the same amendment footing.
- **Emergency path abuse.** Kept narrow by construction: deterministic kernel
  triggers only, single sanction, kernel-validated shape; any widening requires
  changing fixed-layer code.
- **Concurrent runs / lineage children** (state_layer open question 5): v1
  scopes epochs and transitions to a single checkpoint; cross-run constitutions
  ride `meta.json` additively and are out of scope here (Task 02/05 dependency).

## 11. Completion criteria

Task 09 is complete when all of the following hold (concrete forms of the spec's
Task 09 completion criteria):

1. **State transition table exists**: this plan's §5.2 table (T1–T19 base, T20/T21
   added by Tasks 14 and ../ari_rqgm_paper/03: the
   candidate→validated→shadow→probationary_active→active spine;
   active→warning/probation/quarantine; quarantine→retired; retired→banned;
   plus the enumerated auxiliary edges) is reviewed and accepted, each edge with
   a triggering input and guards, and the forbidden-complement rule is stated.
2. **Transition inputs/outputs defined**: inputs are pinned as
   `(EpochState, GovernanceReport, CandidateEvaluation set, current registries,
   rqgm.transition config)` with content hashes recorded; output is the
   `EpochTransition` schema of §6.1 (including adoptions / sanctions /
   retirements / clean_room_requests / bans / fallbacks /
   next_active_components), with §5.3's decomposition into Task 02's
   prepare / per-change / commit event-log format.
3. **ConstitutionalKernel transition validation defined**: §5.3 step 3 and §5.2's
   universal guards specify exactly what `validate_transition` checks (edge
   membership, boundary-only vs. the single emergency shape, actor separation,
   guard evidence presence, no-resurrection/no-instant-activation rules), and
   the shared `transition_rules` module is agreed with Task 04 as the single
   source of truth.
4. **Epoch-boundary transaction semantics defined**: the five-step
   freeze/resolve/validate/prepare/apply-commit protocol, deterministic re-run
   crash recovery on resume (Task 02's replay rule), and the fail-safe
   (incumbent set keeps serving on abort) are specified.
5. **Emergency quarantine defined as the only mid-epoch exception**: closed
   deterministic trigger class, single-sanction shape, fallback policy, suspect
   flagging, and normal-disposition-at-next-boundary are specified.
6. Mode/VirSci stance is explicit: nothing constructed under `simple_bfts`;
   config-only activation; VirSci-independent.

## 12. Deletion criteria

This plan file may be deleted only when all of the following hold:

- The target feature/design is merged into the main branch.
- Corresponding tests have been added.
- CI is green.
- Key design decisions have been moved to permanent docs or code comments.
- No unresolved open questions remain, or they have been moved to another task plan.
- No downstream task depends solely on this plan file.
- INDEX.md task status has been updated to completed/deleted.
- Developers will not be confused by this file's absence.
- The deleted content remains available in git history.

Task-specific deletion criteria (from the spec's Task 09 section):

- The `EpochTransition` schema is implemented (schema file + record type).
- The engine generates transitions (`resolve_transition` produces valid
  `EpochTransition` records from GovernanceReport + CandidateEvaluation fixtures).
- The ConstitutionalKernel validates them (`validate_transition` wired in the
  apply path and covered by the rejection matrix tests).
- Non-epoch-boundary normal transitions are forbidden in code (boundary check
  enforced; only the emergency-quarantine shape passes mid-epoch).
- Tests added (the suite of §9, including the exhaustive edge matrix,
  determinism, crash recovery, and the simple_bfts no-op regression).
- The transition table and transaction protocol have been moved to permanent
  docs (schema reference + architecture overview / developer guide).

## 13. Delete-after checklist

Verify before deleting this file:

- [ ] Implementation is complete.
- [ ] Tests exist.
- [ ] CI is green.
- [ ] Key design decisions have been moved to permanent docs.
- [ ] Unfinished items have been moved to another task plan.
- [ ] INDEX.md has been updated.
- [ ] Deleting this plan file will not strand any developer.
- [ ] The deletion reason can be stated in the commit message.

Task-specific items:

- [ ] The state-transition table is reproduced in the permanent schema
      reference, as the SHIPPED `TRANSITION_TABLE` (21 rows) with each row's
      decision and its reason, and not as this plan's §5.2 prose table.
      AMENDED 2026-08-22 by the maintainer: the criterion said "verbatim", and
      §5.2 here is 19 rows of planning prose with guard names the code no
      longer uses. Reproducing it verbatim would have put a stale table in the
      permanent reference under a criterion that reads as satisfied — the
      failure this whole procedure exists to prevent, arriving through the
      procedure itself.
- [ ] `epoch_transition.schema.json` is committed and loadable via
      `ari.schemas.load`.
- [ ] Registration of `rqgm_transitions.jsonl` / `rqgm_registry.json` /
      `epoch_state.json` in `PathManager.META_FILES` / `_TRACE_FILES` and
      node-report blocklists is verified (owned by Task 02; this task added no
      new checkpoint filenames).
- [ ] The kernel and engine import the transition table from the single shared
      `transition_rules` module (no duplicated table).
- [ ] `simple_bfts` runs create no `rqgm_*` files (regression test green).
- [ ] Emergency quarantine is the only code path that can commit mid-epoch, and
      a test proves every other mid-epoch attempt is rejected.
