# Task 04: ConstitutionalKernel

> **Status**: planned · **Depends on**: 00, 02 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

> **Implemented amendment (2026-07-28):** T16 no longer leaves a changed
> serving set inside the same epoch. It forms a forced
> close/quarantine/open boundary with a fresh fingerprint. Earlier
> “mid-epoch emergency” wording below is superseded by the permanent
> architecture and schema references.

## 1. Purpose

ARI-RQGM lets prompt-defined components (generator / reviewer / adversary / defender /
judge / prompt mutator / clean-room generator / replay selector) evolve across epochs.
The system therefore needs a layer that **cannot** evolve and that mechanically decides
whether every state change follows permitted procedure. That layer is the
**ConstitutionalKernel**: a set of non-evolving, fully deterministic checkers over
schemas, hashes, capability tables, registry diffs, dependency links, and transition
rules.

The kernel is **NOT an LLM judge**. It never answers "is this research decision
correct?" — only "does this event follow permitted procedure?". It contains zero LLM
calls, zero network calls, and zero wall-clock-dependent decisions, in line with ARI
design principle P2 (determinism) and with the existing precedent of `ari-skill-memory`,
which explicitly declares "no LLM calls".

This task designs the kernel: its check set, its verdict model, which violations
**hard-block** registry transitions / frontier updates and which only **warn**, and the
exact points in ARI where enforcement adapters call it.

## 2. Scope

- Design of the `ConstitutionalKernel` class and its eight core `validate_*` entry
  points (schema, hashes, capability, epoch invariance, transition, role separation,
  selective erasure, audit-log integrity), plus the closed set of four
  downstream-specified entry points (`validate_clean_room_bundle` /
  `validate_contamination_free`, Task 08; `validate_authority_non_expansion`,
  Task 11; `validate_context_scope`, Task 12) whose input contracts live in their
  owning plans but whose code families, severities, and blocking behavior are fixed
  here (§5.4, §5.5).
- The deterministic violation catalogue (stable violation codes) covering all
  detection targets in the spec: schema violation; prompt_hash mismatch; active prompt
  change mid-epoch; out-of-scope access; access to retired prompt text; same-role
  impeachment; EvidenceBundle authored by anyone but EvidenceClerk; ImpeachmentMotion
  authored by anyone but Auditor; Judge directly modifying registry;
  retired-prompt-derived record used in frontier; stale record score usage; transition
  rule violation; audit-log tampering.
- The **blocking matrix**: which violation classes hard-block which state changes
  (epoch transition commit, registry writes, frontier rebuild commit) and which are
  warn-and-flag in mid-epoch contexts.
- The enforcement-adapter design: pre-flight capability gate at the MCP choke point,
  boundary gates in RegistryTransitionEngine / FrontierRepairEngine, admissibility
  filter in GovernanceOrchestrator, and a best-effort per-node warn hook in the BFTS
  loop.
- Determinism guarantees, `constitution_hash` derivation, and the rules-in-code policy
  that makes the kernel non-evolving by construction.
- Config sketch (`rqgm.kernel.*`), test plan, and migration/compatibility stance.

## 3. Non-goals

- **No LLM judging of any kind.** Research-quality judgment (review, adjudication of
  attacks, impeachment decisions) belongs to Layer 1/2 components designed in Tasks
  05–08. The kernel validates only procedure.
- **No decision-making about transitions.** The kernel validates an `EpochTransition`
  produced by the RegistryTransitionEngine (Task 09); it never composes one.
- **No evidence assembly, prosecution, or defense** — GovernanceOrchestrator internals
  (Task 05).
- **No redesign of ARI's existing fixed verifiers.** The results.json authoritative
  merge (`ari-core/ari/evaluator/llm_evaluator.py`), the sterile gate in
  `ari-core/ari/cli/bfts_loop.py`, and the paper-phase claim-evidence hard gate
  (`ari-core/ari/pipeline/claim_gate/`) already form a de-facto fixed layer. They stay
  where they are and keep their ownership; the kernel is a sibling in Layer 0, not a
  replacement or a wrapper for them.
- **No audit-log writing.** Record stores, `rqgm_audit.jsonl`, and the (optional) hash
  chain format are Task 02 deliverables. The kernel only *verifies* them.
- **No frontier repair.** Staling records and rebuilding the frontier is Task 10; the
  kernel only validates the result.
- **No OS-level sandboxing.** The flat checkpoint filesystem is readable by every MCP
  skill via `ARI_CHECKPOINT_DIR`; hard filesystem isolation is out of scope. The kernel
  provides pre-flight denial at the MCP tool boundary plus post-hoc detection from
  logs; a stronger access-guard design (for clean-room contamination) is Task 08.
- **No implementation in this task.** This is a plan.

## 4. Existing ARI touchpoints

All paths repo-relative; verified to exist on branch `RQGM`.

| Touchpoint | Relevance |
|---|---|
| `ari-core/ari/schemas/node_report.schema.json`, `ari-core/ari/schemas/__init__.py` (`load`, `schema_path`) | Existing schema home and loader. New RQGM record schemas (Task 02) land beside it; the kernel's `validate_record_schema` consumes them. Note `schema_version: const 1` policy: optional-only additions or explicit version bump. |
| `ari-core/ari/prompts/_loader.py` (`FilesystemPromptLoader.load_versioned` → `sha256(text)[:12]`) and `ari-core/ari/prompts/_provenance.py` (`hash12`, `record_prompt_use`, `prompt_trace.jsonl`) | The single prompt-hash scheme. Kernel hash checks MUST use this exact `hash12` value as `prompt_hash` — no second scheme. `_provenance.py` is also the template for fail-open logging discipline and for the "no wall-clock/git-SHA/host in hashes" rule. |
| `ari-core/ari/prompts/registry.py` (`PromptEntry`, `PromptRegistry`) | Proto-PromptSpec (identity + hash + placeholders). Kernel hash verification resolves expected hashes through the Task 02/07 registry layer built on this. |
| `ari-core/ari/orchestrator/node_report/builder.py` (`_sha256_file`, `build_node_report`) | Existing artifact-hash provenance (full sha256 per file). `validate_hashes` re-checks record `artifact_hash` values against these. |
| `ari-core/ari/orchestrator/lineage_decision.py` (`deterministic_stagnation_pivot`, `append_decision_log`, closed `VALID_ACTIONS` set, total fallback) | The closest existing governance precedent: deterministic-rule-first, closed action vocabulary, append-only JSONL audit, never raises into the run loop. Kernel verdict logging mirrors this shape. |
| `ari-core/ari/cli/bfts_loop.py` (`_run_loop`; lineage hook block ~721–827; sterile gate; retire rules) | Hook site for the per-node warn-only kernel checks and the epoch-boundary gates. The sterile gate (`_sterile=True` ⇒ score clamped 0.0) is the precedent for a deterministic veto flowing through `Node.metrics`. |
| `ari-core/ari/orchestrator/bfts.py` (`should_prune` reads `_sterile`; `frontier_score` strategies) | The least-invasive deterministic veto channel into frontier scoring — the pattern `validate_selective_erasure` enforcement reuses (Task 10 wires it). |
| `ari-core/ari/pipeline/claim_gate/` + `ari-core/ari/public/claim_gate.py` (`run_hard_gate`) | The only existing **blocking** deterministic gate in ARI (error-only dict ⇒ stage failure). Precedent cited for the kernel's hard-block semantics being a deliberate, documented deviation from fail-open hooks. |
| `ari-core/ari/protocols/stores.py` (`CheckpointStore`, `TraceStore` Protocols) | Style home for a `ConstitutionalKernelProtocol` if downstream tasks want a structural seam; concrete impl lives in a sibling module (established Protocol + module-shim pattern). |
| `ari-core/ari/paths.py` (`PathManager.META_FILES`, `_TRACE_FILES`) | The kernel writes no files itself, but any caller-side verdict log filename (Task 02's `rqgm_audit.jsonl`) must be registered here — restated as a cross-task invariant. |
| `ari-core/ari/mcp/client.py` (`MCPClient.call_tool`, `{"result"}/{"error"}` envelope, `_COW_TOOLS`) and `ari-core/ari/agent/tool_manager.py` (`_INTERNAL_MCP_TOOLS` suppression) | The single choke point for every skill invocation: the pre-flight `validate_capability` adapter wraps `call_tool` and must preserve the envelope shape and CoW path. `_INTERNAL_MCP_TOOLS` is the precedent for hiding control tools from the LLM. |
| `ari-core/ari/core.py` (`build_runtime`; `hpc_enabled` skill drop; `axis_mode` dispatch) | Conditional construction precedent. The kernel is instantiated here only when `ari.mode == "ari_rqgm"` (Task 01 config); under `simple_bfts` it is never constructed. |
| `ari-core/ari/config/__init__.py` (`ARIConfig`, `load_config` field filtering) | `rqgm.kernel.*` config rides the typed `RQGMConfig` field Task 01 adds; without it a raw `rqgm:` block is silently dropped. |
| `ari-core/ari/configs/defaults.yaml` (+ `FilesystemConfigLoader`) | Sanctioned home for kernel numeric defaults (e.g. float tolerance) — never for rules. |
| `ari-core/tests/test_prompt_provenance.py` (`test_recorder_is_offline_no_llm_or_network_imports`) | The exact test pattern for enforcing "no LLM/network imports" on kernel modules. |
| `ari-core/ari/lineage.py` + `ari-core/ari/viz/api_orchestrator.py` (launch gates: `parent_terminated`, recursion depth) | Existing deterministic hard gates outside the run loop — precedent that ARI already refuses actions on rule violations at well-defined boundaries. |

## 5. Proposed design

### 5.1 Position and principles

- **Layer 0, fixed.** The kernel belongs to the non-evolving constitutional layer,
  alongside the existing fixed verifiers (results.json merge, sterile gate, claim
  gate), the audit log, and the hash registry. Per global invariant 17 and the spec's
  Layer-design "Never evolving" list, the kernel is deterministic, non-evolving, and
  never an evolution target. (Invariant 16 covers the sibling fixed components —
  fixed verifier, metric recomputer, claim-evidence gate, audit log, hash registry —
  not the kernel itself.)
- **Not an LLM judge** (restated as a completion-criterion sentence): the kernel makes
  no model calls and renders no judgment on scientific merit. Every verdict is a pure
  function of serialized inputs.
- **Pure-function core.** The kernel reads records, registries, frontier snapshots and
  log lines passed to it (or loaded via injected read-only loaders) and returns
  verdicts. It writes nothing. Callers persist verdicts to the Task 02 audit log.
- **Rules in code, not in mutable config.** Role-separation rules and the capability
  matrix are frozen Python constants in the kernel module; the transition table is a
  frozen constant in `ari/rqgm/transition_rules.py` (Task 09's Layer-0 module,
  imported by **both** the engine and the kernel's TransitionValidator — single
  source of truth, no duplication drift). Putting any of them in a checkpoint-scoped
  YAML would create an evolution/tampering channel (any skill can write the flat
  checkpoint dir). Only numeric tolerances live in
  `ari-core/ari/configs/defaults.yaml`.
- **Enforcement principle — "block the institution, not the research."** A blocking
  violation freezes RQGM *state changes* (transition commit, registry write, frontier
  rebuild commit, candidate promotion). It never kills or halts BFTS node execution.
  If an epoch transition is blocked, the previous epoch's active component set carries
  over unchanged and the run continues (behaviorally equivalent to an extended epoch);
  this reconciles fail-closed governance with ARI's "hooks never kill the run"
  invariant (every existing `_run_loop` hook is fail-open; the only blocking precedent
  is the paper-phase claim gate — the kernel deliberately extends that precedent to
  governance state, and this deviation is documented here and, on implementation, in
  permanent docs).

### 5.2 Module layout (proposed)

```
ari-core/ari/rqgm/                  # new package, internal (NOT in ari.public.*)
├── kernel.py                       # ConstitutionalKernel + check implementations
├── kernel_rules.py                 # frozen rule tables: ROLE_RULES, CAPABILITY_MATRIX,
│                                   # SEVERITY, CONSTITUTION_VERSION (NO transition
│                                   # table here — imported from transition_rules.py)
├── transition_rules.py             # Task 09 deliverable: ComponentStatus,
│                                   # TRANSITION_TABLE, EMERGENCY_EDGE — imported by
│                                   # BOTH the engine and the kernel (single source
│                                   # of truth, no duplication drift)
└── kernel_types.py                 # Violation, KernelReport, enums (pure dataclasses)
```

Record schemas/models are Task 02 deliverables (`ari/rqgm/records.py` +
`ari/schemas/*.schema.json`); the kernel imports them read-only.
`transition_rules.py` is a Task 09 deliverable (shown above for layout context
only); the kernel imports it read-only and never duplicates the table into
`kernel_rules.py`.

### 5.3 Verdict model

```python
# kernel_types.py (sketch)
@dataclass(frozen=True)
class Violation:
    code: str            # stable id, e.g. "CK-REG-001" (never renumbered)
    check: str           # "validate_transition", ...
    severity: str        # "block" | "warn"  (fixed per code in kernel_rules.SEVERITY)
    subject_ref: str     # record_id / component_id / prompt_hash / line number
    rule_id: str         # pointer into kernel_rules tables
    detail: str          # deterministic message (no timestamps, no paths outside ckpt)

@dataclass(frozen=True)
class KernelReport:
    context: str                 # "epoch_transition" | "frontier_rebuild" |
                                 # "registry_write" | "node_record" | "capability"
    violations: tuple[Violation, ...]
    @property
    def blocking(self) -> bool:  # any violation with severity == "block"
        ...
```

The kernel **returns** reports; it raises only on programmer error (wrong types).
Severity is part of the constitution (fixed in `kernel_rules.SEVERITY`), not chosen by
callers. Callers apply the blocking matrix (§5.5): in boundary contexts a
`blocking=True` report vetoes the state change; in mid-epoch contexts adapters
downgrade behavior to warn-and-flag (the violation record itself keeps its severity so
the boundary pass can act on it).

### 5.4 The deterministic checks

Core public API (from the spec, unchanged):

```python
class ConstitutionalKernel:
    def validate_record_schema(self, record) -> KernelReport: ...
    def validate_hashes(self, record, registry, artifacts) -> KernelReport: ...
    def validate_capability(self, actor, action, resource) -> KernelReport: ...
    def validate_epoch_invariance(self, epoch_state, event_log) -> KernelReport: ...
    def validate_transition(self, transition, registry, epoch_state) -> KernelReport: ...
    def validate_role_separation(self, record) -> KernelReport: ...
    def validate_selective_erasure(self, frontier, records, prompt_registry) -> KernelReport: ...
    def validate_audit_log_integrity(self, audit_log) -> KernelReport: ...
```

Downstream-specified entry points (implemented in `kernel.py` under this task's
determinism, verdict, and severity rules; their detailed input contracts and
whitelists are owned by the listed plans):

```python
    # Task 08 (clean-room regeneration) — codes CK-CLN-*
    def validate_clean_room_bundle(self, bundle, request, registries) -> KernelReport: ...
    def validate_contamination_free(self, candidate_text, retirement_event,
                                    records) -> KernelReport: ...
    # Task 11 (meta-agent evolution) — invariant-18 sub-check of validate_transition,
    # exposed as a named entry point; codes CK-REG-1x
    def validate_authority_non_expansion(self, candidate_entry,
                                         incumbent_entry) -> KernelReport: ...
    # Task 12 (context budget) — codes CK-CTX-*
    def validate_context_scope(self, role, view) -> KernelReport: ...
```

The kernel API is therefore closed at **twelve** entry points: the eight core checks
plus these four. Downstream plans fill in inputs, whitelists, and fixtures for the
four extension checks but may not add further entry points without reopening this
plan (or its permanent-docs successor). Return-type sketches in Tasks 08/11
(`CheckResult`, `None | Violation`) harmonize to the §5.3 `KernelReport` model at
implementation time — the merged kernel returns `KernelReport` everywhere.

Check semantics and violation codes (codes are frozen once implemented):

1. **`validate_record_schema` (CK-SCH-\*)** — every RQGM record (ProposalRecord,
   ReviewRecord, RawAttackRecord, ValidatedAttackRecord, JudgmentRecord, UtilityRecord,
   GovernanceReport, EpochTransition, …) validates against its Task 02 model. Since
   `jsonschema` is not an ari-core dependency, validation runs through the Task 02
   Pydantic models (`model_validate`); the shipped `ari/schemas/*.schema.json` files
   are the exported reference, snapshot-tested against `model_json_schema()`. Also
   checks the mandatory common envelope: `record_id, epoch_id, component_id,
   prompt_hash, role, created_at, source_refs, status`.
2. **`validate_hashes` (CK-HSH-\*)** — (a) `record.prompt_hash` equals the registry's
   hash for the component's active PromptSpec in `record.epoch_id` (scheme:
   the existing `hash12 = sha256(text)[:12]`); (b) `artifact_hash` fields match
   recomputed full sha256 of the referenced files (same scheme as
   `node_report/builder.py:_sha256_file`); (c) `source_refs` resolve to existing
   records/artifacts.
3. **`validate_capability` (CK-ACC-\*)** — pure table lookup:
   `CAPABILITY_MATRIX[(actor_role, tier)]` allows/denies `(action, resource_class)`.
   Detects out-of-scope access, retired-prompt-text access
   (`can_read_retired_prompt_text=False`), meta-agents writing registries
   (`can_modify_registry=False`), meta-agents activating candidates
   (`can_activate_candidates=False`). Used in two modes: **pre-flight** (adapter
   denies the action before it happens) and **post-hoc** (Task 05's self-audit replays
   logged events through the same table).
4. **`validate_epoch_invariance` (CK-EPO-\*)** — over the epoch's event log: every
   record created in epoch E carries a `prompt_hash` that was in E's frozen active set;
   any active-set change event inside E that is not a constitutional emergency
   quarantine is a violation (invariants 1–2).
5. **`validate_transition` (CK-REG-\*)** — for each adoption/sanction/retirement in an
   `EpochTransition`: the `(from_status, to_status)` pair is in the frozen
   `TRANSITION_TABLE` imported from `ari/rqgm/transition_rules.py` (the Task 09-owned
   single source of truth; spine: candidate→validated→shadow→probationary_active→active;
   active→warning|probation|quarantine; quarantine→retired; retired→banned); the
   transition is being committed at an epoch boundary (or is the emergency-quarantine
   exception); the writer is RegistryTransitionEngine (invariant 10); required
   supporting refs exist (a retirement references a GovernanceReport;
   clean-room requests reference a RetirementEvent); no authority expansion for
   evolving governance components (invariant 18: a candidate's declared
   capability set must be ⊆ its predecessor role's fixed cap).
6. **`validate_role_separation` (CK-ROL-\*)** — ImpeachmentMotion author role ==
   Auditor; EvidenceBundle author == EvidenceClerk; accuser role != accused role
   (same-role outputs are observations, never accusations — invariants 4–7); Judge (or
   any actor other than RegistryTransitionEngine) never appears as a registry writer.
7. **`validate_selective_erasure` (CK-ERA-\*)** — the spec's kernel loop, verbatim:
   every frontier record has `stale is False`, `valid_for_frontier is True`, and
   `prompt_hash not in retired_prompt_hashes`; additionally every record depending
   (via `source_refs`/prompt_hash closure) on a retired prompt is marked stale before
   next-epoch scoring (invariant 12), and *nothing was physically deleted* (record ids
   present before repair are still resolvable after — invariant 13).
8. **`validate_audit_log_integrity` (CK-AUD-\*)** — the audit log is append-only:
   sequence numbers strictly increase; previously check-pointed prefix is
   byte-identical (prefix hash comparison against the last boundary's recorded chain
   head in EpochState); if Task 02 enables hash chaining, recompute
   `entry_hash`/`prev_hash` over the canonical serialization. Canonicalization is
   `json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`;
   recorded timestamps are data inside entries, but no check-time wall clock ever
   enters a hash or a verdict (P2).
9. **`validate_clean_room_bundle` / `validate_contamination_free` (CK-CLN-\*)** —
   Task 08's pre-generation bundle screen (closed field set, const-false forbidden
   flags, flag↔field parity, FailureSummary admissibility) and post-generation
   contamination screen (deterministic shingle overlap of candidate text against the
   forbidden corpus). Detailed semantics and thresholds: Task 08 §5/§7. Severity is
   fixed here: contamination ⇒ candidate **blocked** from registration.
10. **`validate_authority_non_expansion` (CK-REG-1x)** — the invariant-18 sub-check of
    `validate_transition` (item 5) exposed as a named entry point for Task 11's
    meta-candidate flow: pure set arithmetic — the candidate's declared capability
    set must be ⊆ the incumbent role's fixed cap. Flag vocabulary and closed action
    vocabulary: Task 11 §5.5/§6.1.
11. **`validate_context_scope` (CK-CTX-\*)** — Task 12's role-view scope check: the
    rendered view's key set must be ⊆ the role's whitelist (for BFTS, the
    `ProposalSummaryView` field whitelist; Task 12 owns the whitelist definition).
    Fail posture — the decision Task 12 defers to this plan — is **warn-and-flag**:
    per §5.1 ("block the institution, not the research") a scope violation never
    blocks node execution; flagged records become boundary-inadmissible (§5.5).

### 5.5 Blocking matrix — hard-block vs warn

Fixed by `kernel_rules.SEVERITY` and the adapter contexts. This is the normative table:

| Violation class (codes) | Mid-epoch / per-node context | Epoch-boundary transaction | Frontier rebuild commit | Registry write (pre-flight) |
|---|---|---|---|---|
| Schema violation on governance records (EpochTransition, GovernanceReport) — CK-SCH-G\* | n/a | **BLOCK** transition | **BLOCK** commit | **DENY** |
| Schema violation on per-node records (ProposalRecord, ReviewRecord, …) — CK-SCH-N\* | warn + flag record `constitutional_flags` | record inadmissible as governance evidence | excluded from frontier candidates | n/a |
| prompt_hash mismatch / artifact_hash mismatch — CK-HSH-\* | warn + flag | flagged records inadmissible; if an *active component's* registered hash mismatches → **BLOCK** transition | mismatched records excluded; **BLOCK** if present after repair | n/a |
| Active-set change mid-epoch (non-emergency) — CK-EPO-\* | warn (detected post-hoc) | affected records inadmissible + **BLOCK** any adoption of the offending component | dependent records excluded | **DENY** (pre-flight on registry mutation attempts) |
| Out-of-scope access / retired-prompt-text access — CK-ACC-\* | **DENY** at MCP pre-flight (returns `{"error": ...}` envelope); post-hoc → warn + flag | derived candidate/evidence inadmissible (clean-room contamination ⇒ candidate **BLOCKED** from registration, Task 08) | n/a | **DENY** |
| Same-role impeachment / wrong-author EvidenceBundle / wrong-author ImpeachmentMotion — CK-ROL-\* | warn + flag at creation time | offending motion/bundle **inadmissible**; any transition citing it as sole support **BLOCKED** | n/a | n/a |
| Judge / meta-agent / any non-RTE actor writing registry — CK-ROL-9\* / CK-ACC-\* | **DENY** pre-flight | **BLOCK** (a transition not produced by RTE is invalid) | n/a | **DENY** |
| Transition-table violation / non-boundary normal transition — CK-REG-\* | n/a | **BLOCK** transition (the sole exception, emergency quarantine, is itself a table entry) | n/a | **DENY** |
| Retired-prompt-derived record in frontier / stale record scored — CK-ERA-\* | warn (should not occur mid-epoch) | **BLOCK** epoch start until repair reruns | **BLOCK** commit; repair must rerun | n/a |
| Audit-log tampering (seq regression, prefix mutation, chain break) — CK-AUD-\* | warn (detected on periodic cheap check) | **BLOCK** transition; epoch enters *governance-suspended* carry-over (active set frozen, no promotions/retirements) until a human or a clean resume clears it | **BLOCK** commit | n/a |
| Clean-room bundle violation / contamination — CK-CLN-\* (Task 08) | **DENY** generation pre-flight (bundle check); post-check findings flag the candidate | contaminated candidate **BLOCKED** from registration (no candidate→validated) | n/a | **DENY** |
| Authority expansion by an evolving candidate — CK-REG-1x via `validate_authority_non_expansion` (Task 11) | n/a | **BLOCK** the adoption of that candidate (other transitions in the same transaction unaffected) | n/a | **DENY** |
| Context-scope violation (role view exceeds whitelist) — CK-CTX-\* (Task 12) | warn + flag (never blocks the expand or node execution) | derived records inadmissible as governance evidence | n/a | n/a |

Summary of the two hard rules:

- **Hard-block set** (can veto transitions/frontier updates — the task's key
  deliverable): transition-table violations, non-RTE registry writes,
  stale/retired-prompt-derived records reaching the frontier, governance-record schema
  violations, active-component hash mismatches, audit-log tampering, clean-room
  contamination (blocks candidate registration), authority expansion (blocks the
  candidate's adoption), and (pre-flight) capability denials including
  retired-prompt-text access.
- **Warn-and-flag set** (never interrupts research execution): per-node record schema
  and hash anomalies, post-hoc access findings, role-separation findings at creation
  time, context-scope findings. Warned records accumulate `constitutional_flags` and
  become **inadmissible** as governance evidence at the boundary — warnings are
  therefore consequential without ever being able to crash or stall a node.

### 5.6 Enforcement adapters (who calls the kernel, where)

The kernel itself is passive; thin adapters install it (all under `ari_rqgm` mode
only):

1. **Epoch-boundary transaction** (Task 05/09 flow, spec core algorithm steps 12–16):
   `registry_transition_engine.apply(transition)` refuses to commit unless
   `kernel.validate_transition(...)` returns a non-blocking report — the spec's
   `constitutional_kernel.validate_transition(transition)` call. This is a hard gate;
   on block, the previous active set carries over (see §5.1) and the blocked
   transition + report are appended to the audit log.
2. **Frontier rebuild commit** (Task 10): FrontierRepairEngine calls
   `kernel.validate_selective_erasure(frontier, records, prompt_registry)` after
   repair and before the rebuilt frontier replaces the live one — the spec's
   `constitutional_kernel.validate_frontier(...)` step. Hard gate; on block the repair
   reruns (bounded retries), else governance-suspended carry-over.
3. **Governance admissibility filter** (Task 05): `GovernanceOrchestrator.audit_epoch`
   runs `validate_record_schema` + `validate_role_separation` + `validate_hashes`
   over its evidence inputs and drops inadmissible records before any LLM-side
   assessment sees them.
4. **MCP pre-flight capability gate** (Task 05/08/11 wiring): a wrapper object around
   `MCPClient` (duck-typed — callers use only `list_tools`, `call_tool`, `_COW_TOOLS`,
   `to_claude_mcp_config`, `close_all`) consults `validate_capability(actor, action,
   resource)` before dispatch; denial returns the standard `{"error": "..."}` envelope
   so no caller contract changes. The CoW `cow_node_id` path is preserved untouched.
5. **Per-node warn hook** (`_run_loop`, mirroring the lineage hook block): after each
   node completes and its RQGM records are appended, run the cheap checks
   (`validate_record_schema`, `validate_hashes` on the new records) inside
   try/except + warn — best-effort, rate-limitable, never raises (MAP invariant:
   hooks never kill the run). Verdicts are logged to the Task 02 audit log.
6. **Resume integrity pass**: on `ari resume` in `ari_rqgm` mode, before re-entering
   the loop, run `validate_audit_log_integrity` + `validate_selective_erasure` against
   the restored state; blocking findings put the run into governance-suspended
   carry-over rather than refusing to resume.

### 5.7 Determinism guarantees (P2)

- Kernel modules import only stdlib + `pydantic` (already a dependency) + `ari.rqgm`
  types. A grep-style test (pattern:
  `test_prompt_provenance.py::test_recorder_is_offline_no_llm_or_network_imports`)
  forbids `litellm`, `openai`, `anthropic`, `requests`, `httpx`, `aiohttp`, `socket`
  in `ari/rqgm/kernel*.py`.
- Same inputs ⇒ byte-identical `KernelReport` (violations sorted by
  `(code, subject_ref)`), verified by a double-invocation equality test and golden
  fixtures.
- No wall-clock reads in any check; `created_at` fields are compared to *epoch
  metadata*, never to `now()`. No randomness. No environment reads except the run pin
  via injected loaders.
- Float comparisons use a single tolerance constant from
  `ari-core/ari/configs/defaults.yaml` (`rqgm.kernel.float_tolerance`, default `1e-9`).
- `constitution_hash = sha256(canonical_json(transition_rules.TRANSITION_TABLE,
  transition_rules.EMERGENCY_EDGE, ROLE_RULES, CAPABILITY_MATRIX, SEVERITY,
  CONSTITUTION_VERSION))[:12]` — computed at import time over the kernel's own
  `kernel_rules` tables **plus** the Task 09 transition table imported from
  `ari/rqgm/transition_rules.py`, so an edit to `transition_rules.py` changes the
  hash exactly as an edit to `kernel_rules.py` does (the table living outside
  `kernel_rules.py` does not escape the pin). Recorded into `EpochState` (Task 02)
  and additively into `meta.json` for child-run gates. Any rule change is therefore
  visible, reviewable in git, and pinned by a hand-updated hash row in tests (the
  `_EXPECTED_HASHES` pattern) — this is how "non-evolving" is made mechanically
  checkable rather than aspirational.

### 5.8 What the kernel does NOT own (boundary clarifications)

- The `_sterile` clamp, retire rules A/B, and `should_prune` remain owned by
  `bfts_loop.py`/`bfts.py` — they are pre-existing fixed-layer behavior in both modes.
  The kernel neither moves nor wraps them (Task 00 lists them as must-not-break).
- The FixedVerifier / MetricRecomputer / ClaimEvidenceGate roles in the spec's Layer 0
  map to today's results.json merge, `validate_metrics`, and
  `claim_gate` respectively; declaring them formally non-evolving is a permanent-docs
  action at implementation time (deletion criterion), not new code in this task.

## 6. Data structures / schema changes

New (all internal, none in `ari.public.*`):

- `Violation`, `KernelReport` frozen dataclasses (§5.3).
- `kernel_rules.py` frozen tables:
  - `CONSTITUTION_VERSION: int = 1`
  - **No transition table.** The kernel imports `TRANSITION_TABLE` and
    `EMERGENCY_EDGE` from `ari/rqgm/transition_rules.py` (Task 09's Layer-0
    deliverable; each `TransitionRule` carries `boundary_only: bool`, `False` only
    for the emergency-quarantine edge). Single source of truth shared with the
    engine — the table is never duplicated into `kernel_rules.py`, and it is
    covered by `constitution_hash` via import (§5.7).
  - `ROLE_RULES` — `{record_type: required_author_role}` (EvidenceBundle→EvidenceClerk,
    ImpeachmentMotion→Auditor) and the same-role-accusation predicate.
  - `CAPABILITY_MATRIX: {(role, tier): frozenset[(action, resource_class)]}` — tiers
    `fixed | institutional | meta` (Task 11 adds `tier` to ComponentRegistry).
  - `SEVERITY: {violation_code: "block" | "warn"}` — the normative severity map
    backing §5.5.
- Audit-log entry addition (Task 02 schema, additive): `kernel_report` entry type
  carrying `{context, constitution_hash, violations: [...]}` so every verdict is
  replayable.
- `meta.json`: additive optional key `constitution_hash` (read by the existing launch
  gates in `ari-core/ari/viz/api_orchestrator.py`; children of an RQGM run inherit and
  can be gate-checked).
- Config sketch (rides Task 01's typed `RQGMConfig`):

```yaml
ari:
  mode: simple_bfts        # kernel constructed only under ari_rqgm
rqgm:
  enabled: false
  kernel:
    enforcement: standard  # standard | audit_only
    # audit_only: every context downgrades to warn-and-log (for ablation
    # conditions B4–B6 in Task 13 and Stage-1-style rollout). Read once at
    # run start / epoch boundary; never hot-switched mid-epoch.
    audit_chain: auto      # auto = verify chain iff Task 02 chain fields present
```

Numeric defaults (`float_tolerance`) in `ari-core/ari/configs/defaults.yaml` under a
new `rqgm:` key.

No changes to `tree.json` / `nodes_tree.json` / `results.json` / `node_report.json`
schemas. No new checkpoint files written by the kernel itself (verdicts go to Task
02's `rqgm_audit.jsonl`, which Task 02 registers in `META_FILES`/`_TRACE_FILES`).

## 7. API / class changes

- **New**: `ari/rqgm/kernel.py: ConstitutionalKernel` with the eight core `validate_*`
  methods plus the four downstream-specified entry points (§5.4 — Tasks 08/11/12
  own their input contracts; the entry-point set is closed at twelve). `kernel.py`
  imports the transition table from `ari/rqgm/transition_rules.py` (Task 09
  deliverable) rather than defining one. Constructor takes read-only loaders/handles
  only:

```python
class ConstitutionalKernel:
    def __init__(self, *, records_reader, prompt_registry_reader,
                 component_registry_reader, audit_log_reader,
                 rules=kernel_rules, tolerances=None): ...
```

- **New**: `ari/rqgm/kernel_types.py`, `ari/rqgm/kernel_rules.py` (§5.3, §6).
- **Optional new Protocol**: `ConstitutionalKernelProtocol` in
  `ari-core/ari/protocols/` (added only when Tasks 05/09/10 need to bind to it;
  keeps the Protocol + concrete-sibling pattern of `ari/protocols/stores.py`).
- **Changed (additive, mode-gated)**: `ari-core/ari/core.py:build_runtime` constructs
  the kernel under `ari_rqgm` and attaches it to the RQGM controller object (wrapping
  pattern — the 6-tuple return shape is NOT extended; 4 positional call sites depend
  on it).
- **Changed (additive)**: the MCP wrapper adapter (§5.6.4) — a new class, not an edit
  to `MCPClient`; `MCPClient.call_tool` behavior is untouched in `simple_bfts`.
- **No** new CLI commands/flags, no `ari.public.*` symbols, no new MCP tools in this
  task ⇒ zero contract-snapshot regeneration budget for v1.

## 8. Migration / compatibility

- **`simple_bfts` (default): byte-for-byte preserved.** The `ari/rqgm/` package is
  import-inert; `build_runtime` never constructs the kernel; no adapter is installed;
  no config key is required. Existing tests must pass unchanged.
- **`ari_rqgm` is opt-in** via `ari.mode: ari_rqgm` + `rqgm.enabled: true` (Task 01).
  Even then, `kernel.enforcement: audit_only` gives a warn-everything rollout stage
  (mirrors the CI Stage-1-advisory-first policy).
- **VirSci independence**: the kernel has no VirSci awareness; with
  `proposal_router.generators.virsci.enabled=false` nothing changes for the kernel
  (ProposalRecords from any generator validate identically). All four
  mode×VirSci combinations are valid.
- **Fail-open discipline preserved where it matters**: mid-epoch record checks (the
  per-node warn hook, post-hoc access findings) are try/except + warn like every
  existing `_run_loop` hook. The blocking points are (a) RQGM-internal state commits
  (epoch-transition commit, registry write, frontier rebuild commit) and (b) the MCP
  pre-flight capability gate (§5.5, §5.6.4), which DENIES CK-ACC violations even
  mid-epoch — e.g. a retired-prompt-text read — by returning the standard
  `{"error": ...}` envelope rather than dispatching the tool call. All of these exist
  only under `ari_rqgm`; none is installed in `simple_bfts`, whose behavior is
  byte-for-byte preserved.
- **Resume**: kernel state is stateless-by-design; everything it needs is rebuilt from
  Task 02's checkpoint-scoped stores. The resume integrity pass (§5.6.6) degrades to
  governance-suspended carry-over, never a refusal to resume.
- **Mode switching**: kernel construction happens only at run start; enforcement mode
  is re-read only at epoch boundaries (consistent with the spec's mode-switch timing).

## 9. Tests

Unit (new `ari-core/tests/test_rqgm_kernel.py`, listed in `ari-core/tests/README.md`
for the readme-sync gate):

1. Per-check fixtures: for each violation code, one minimal fixture that triggers it
   and one that passes (golden `KernelReport` comparison).
2. Transition table (imported from `ari/rqgm/transition_rules.py`, Task 09): every
   legal `(from, to)` pair passes; every illegal pair blocks; `boundary_only`
   transitions block when stamped mid-epoch; emergency quarantine passes only as a
   forced close/quarantine/open boundary and a standalone mid-epoch append is refused;
   an import-identity test asserts the kernel and the engine consume the same table
   object (no duplicated table in `kernel_rules.py`).
3. Role separation: same-role impeachment blocked-as-inadmissible; wrong-author
   EvidenceBundle/ImpeachmentMotion flagged; RTE-authored registry write passes,
   Judge-authored blocked.
4. Selective erasure: frontier containing a `stale=True` /
   `valid_for_frontier=False` / retired-`prompt_hash` record ⇒ blocking report;
   physical-deletion detection (missing previously-known record id) ⇒ violation.
5. Hashes: prompt_hash uses the `hash12` scheme (cross-check against
   `FilesystemPromptLoader.load_versioned` on a temp file); artifact sha256 mismatch
   detected.
6. Audit-log integrity: seq regression, mutated prefix, broken chain (when fields
   present) each detected; absent chain fields with `audit_chain: auto` ⇒ no chain
   violations.
7. Determinism: double-invocation byte-equality on every fixture; violations sorted;
   no-LLM/network import grep test over `ari/rqgm/kernel*.py`.
8. `constitution_hash`: stable across runs; hand-pinned expected value
   (`_EXPECTED_HASHES` pattern) so any rule-table edit — including an edit to the
   imported `transition_rules.py` — is an explicit reviewed diff.

Integration:

9. Blocked transition ⇒ RTE does not commit; previous active set carried over;
   `kernel_report` audit entry appended (with Task 09 skeleton or a stub RTE).
10. Blocked frontier rebuild ⇒ live frontier unchanged (with Task 10 stub).
11. MCP pre-flight denial returns exactly `{"error": ...}`; CoW path untouched
    (mock `MCPClient`).
12. Per-node warn hook: a kernel exception inside the adapter is swallowed
    (warn logged, run continues) — the fail-open guarantee.
13. `enforcement: audit_only` ⇒ blocking codes downgrade to logged warnings
    everywhere.

Regression / smoke:

14. `simple_bfts` mode: kernel never constructed (assert via constructor spy in a
    `build_runtime` test); full existing suite green untouched.
15. `ari_rqgm` + VirSci off: kernel operates normally on router-only ProposalRecords.

## 10. Risks

- **Fail-closed novelty.** Blocking is precedented only in the paper pipeline; a bug
  in a blocking check could wedge every epoch transition into carry-over. Mitigations:
  `audit_only` rollout mode; governance-suspended carry-over instead of run abort;
  bounded repair retries; every block fully logged and replayable.
- **Capability enforcement is advisory at the filesystem level.** Skills can read the
  flat checkpoint dir regardless of the MCP gate; the kernel detects (post-hoc) but
  cannot prevent direct reads. Honest limitation, owned jointly with Task 08; must be
  stated in permanent docs.
- **Schema-validation dependency choice.** Pydantic-model validation (chosen to avoid
  a new `jsonschema` dependency) must be kept in lockstep with the exported
  `*.schema.json` files; drift is caught by the snapshot test but is a maintenance
  cost. Contract snapshots must stay duck-typed / dependency-version-robust
  (CI installs latest pins).
- **Rule-table ossification.** Rules-in-code means constitution changes require code
  review + hash re-pin. This is intended (non-evolution), but emergency rule fixes
  mid-experiment are impossible by design — document the trade-off.
- **Performance.** `validate_hashes` recomputing artifact sha256 on large outputs
  could be slow per-node; mitigate by hashing only record-referenced files (already
  hashed once by node_report builder — compare stored values, recompute only on
  boundary audits or suspicion).
- **Cross-task coupling.** The kernel validates schemas/logs owned by Task 02 and
  transitions owned by Task 09; interface drift between plans must be reconciled in
  INDEX.md before implementation starts.
- **Epoch-boundary definition landed (2026-07-28, commit `c050ebf`).** The three-way
  choice was decided as **N new BFTS nodes**: `RQGMEpochConfig` declares
  `boundary: Literal["node_count"]` and `nodes_per_epoch` (default 10) in
  `ari-core/ari/config/__init__.py`, and `RqgmRuntime.ensure_epoch`
  (`ari-core/ari/rqgm/runtime.py`) fires `_run_epoch_boundary` once
  `node_count - ep.node_count_at_open >= nodes_per_epoch`, counted from the outer-loop
  head in `ari-core/ari/cli/bfts_loop.py`. The kernel stayed agnostic as planned, and
  `validate_epoch_invariance` fixtures are finalized: the validator
  (`ari-core/ari/rqgm/kernel.py`) is reached in production through
  `RqgmRuntime.check_epoch_invariance`, called from the epoch tick, with CK-EPO-001/002
  fixtures in `ari-core/tests/test_rqgm_kernel.py`. Only the *richer* trigger policy
  (stagnation events) remains deferred to Task 05; it is not a kernel dependency.

## 11. Completion criteria

This task is complete when all of the following hold:

1. **Kernel responsibilities defined**: the eight core `validate_*` entry points each
   have a written input/output contract and semantics, the four downstream-specified
   entry points (Tasks 08/11/12) are enumerated with their code families, severities,
   and owning plans (§5.4), and the kernel's boundary against GovernanceOrchestrator
   (Task 05), RegistryTransitionEngine (Task 09), and FrontierRepairEngine (Task 10)
   is stated (§3, §5.6, §5.8).
2. **"Not an LLM judge" stated**: the plan (and, at implementation time, the module
   docstring + permanent docs) states that the kernel makes zero LLM/network calls and
   judges procedure only — never research correctness (§1, §5.1) — with the enforcing
   import-grep test specified (§5.7, §9.7).
3. **Deterministic check targets enumerated**: all thirteen detection targets from the
   spec (schema violation; prompt_hash mismatch; active prompt change mid-epoch;
   out-of-scope access; retired-prompt-text access; same-role impeachment; wrong-author
   EvidenceBundle; wrong-author ImpeachmentMotion; Judge modifying registry;
   retired-prompt-derived record in frontier; stale record score usage; transition
   rule violation; audit-log tampering) are mapped to stable violation codes and to
   one of the eight core checks (§5.4).
4. **Blocking violations defined**: the blocking matrix (§5.5) fixes, per violation
   class and context, hard-block vs warn — including the two normative sets
   (hard-block set / warn-and-flag set) and the "block the institution, not the
   research" carry-over semantics (§5.1).
5. Determinism guarantees are specified concretely (P2 rules, sorted output,
   double-invocation equality, `constitution_hash` pinning) (§5.7).
6. Enforcement adapter locations are pinned to real ARI seams with file paths (§4,
   §5.6), and the `simple_bfts` no-op guarantee is explicit (§8).
7. Downstream plans (05, 08, 09, 10, 11, 12) can consume this design without
   re-opening kernel-internal questions: the entry-point set is closed at twelve
   (eight core + four downstream-specified), and downstream plans only fill in
   inputs, whitelists, and fixtures for their extension checks; remaining open items
   are recorded in §10 or moved to those plans.

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

Task-specific criteria (in addition to all of the above):

- A minimal ConstitutionalKernel is implemented (the eight core `validate_*` checks
  with the frozen rule tables — transition table imported from Task 09's
  `transition_rules.py` — and the verdict model; the four downstream-specified
  checks land with Tasks 08/11/12 under this plan's verdict/severity model).
- Deterministic check tests exist (per-code fixtures, double-invocation equality,
  no-LLM/network import test, `constitution_hash` pin).
- Critical violations can actually block transition commits and frontier updates
  (integration tests §9.9–9.10 pass against the Task 09/10 implementations or their
  agreed stubs).
- The fixed layer's non-evolution is stated in permanent docs (architecture overview /
  developer guide): kernel, schema checker, hash checker, access control, audit log,
  transition rules, selective-erasure rule, fixed verifier, metric recomputer, and
  claim-evidence hard gate are not evolution targets.

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

- [ ] The blocking matrix (§5.5) is reproduced in permanent docs (schema reference or
      developer guide), not only in this plan.
- [ ] The "kernel is deterministic, non-evolving, and not an LLM judge" statement and
      the fixed layer's non-evolution list are in permanent docs.
- [ ] The `constitution_hash` pin test and the no-LLM/network import test are merged
      and green, and the hash covers the imported Task 09 `transition_rules` tables
      (no duplicated transition table exists in `kernel_rules.py`).
- [ ] Tasks 05, 08, 09, 10, 11, 12 reference the merged kernel API (not this plan)
      for their kernel interactions.
