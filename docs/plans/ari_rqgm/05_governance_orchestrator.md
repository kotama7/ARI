# Task 05: GovernanceOrchestrator

> **Status**: planned · **Depends on**: 00, 02, 04 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

## 1. Purpose

ARI-RQGM needs an epoch-boundary institution that decides whether the prompt-defined
components used during the epoch (generator / reviewer / adversary / defender / judge /
router / utility policy) are still trustworthy, and that evaluates candidate replacement
prompts — without letting any component judge itself or its same-role rivals, and without
letting the audit machinery mutate any registry directly.

Today ARI has no such layer. The closest analogue is the lineage-decision hook
(`stagnation → deterministic pivot → LLM judge → append-only JSONL`), which governs
*research direction*, not *component trustworthiness*. This task designs the
**GovernanceOrchestrator**: a single facade that consolidates observation collection,
reliability assessment, evidence assembly, prosecution, defense, adjudication,
replay-pool maintenance and governance self-audit into one epoch-boundary call,
`audit_epoch(...)`, producing one `GovernanceReport`. The report is *advisory input* to
the RegistryTransitionEngine (Task 09); it never applies sanctions itself.

## 2. Scope

- Design of the public facade: `GovernanceOrchestrator.audit_epoch(...) -> GovernanceReport`.
- Design of the internal submodule groups (all private, none exported):
  - **ReliabilityAssessment** — ReliabilityMonitor, MetaReliabilityMonitor.
  - **EvidenceAssembly** — EvidenceClerk, EvidenceAuditChecker, SourceRefValidator.
  - **ProsecutionDecision** — Auditor, Prosecutor, BondAccounting.
  - **DefenseGeneration** — Defender.
  - **AdjudicationPanel** — GovernanceJudge, ReplayBoard, AnchorBoard, JuryPanel.
  - **GovernanceSelfAudit** — MetaMonitor-style audit of the governance components themselves.
- The nine-step internal pipeline of `audit_epoch` (observe → assess → assemble → prosecute
  → defend → adjudicate → update replay pool → self-audit → report).
- Schema drafts: `GovernanceReport`, `ImpeachmentMotion`, `EvidenceBundle`,
  `ComparisonObservation`, `ReliabilityAssessment` entries, `ImpeachmentOutcome`.
- The **same-role accusation prohibition** and the **observations-not-accusations rule**
  (global invariants 4–7), stated as design rules here and enforced deterministically by
  the ConstitutionalKernel (Task 04).
- Determinism posture per submodule (pure rule vs. LLM-with-total-fallback), fail-open
  degradation, and per-audit budget caps (consuming Task 12's `rqgm.governance` config).
- Wiring plan: where the facade is constructed and where `audit_epoch` is called from
  the BFTS run loop, gated on `ari.mode == "ari_rqgm"`.
- Persistence plan for governance records (append-only, checkpoint-scoped).

## 3. Non-goals

- **No implementation in this task.** This is a plan.
- **No registry mutation.** Promotion / demotion / quarantine / retirement decisions are
  produced only as `recommendations` in the GovernanceReport; applying them is Task 09
  (RegistryTransitionEngine), validated by the kernel (invariants 10–11). Emergency
  quarantine is also Task 09's exception path, not a GovernanceOrchestrator capability.
- **No deterministic checker design.** Schema/hash/capability/role-separation checks are
  Task 04 (ConstitutionalKernel). This plan only *consumes* them.
- **No attack generation.** RawAttackRecord / DefenderResponse / ValidatedAttackRecord
  production during the epoch is Task 06 (adversarial evolution). `audit_epoch` reads
  those records from the audit log and the AdversarialReplayPool; it does not create
  in-epoch attacks.
- **No prompt evolution or clean-room generation.** Candidate PromptSpecs arrive as
  inputs (`candidate_prompts`); generating them is Tasks 07/08/11. The ReplayBoard /
  AnchorBoard *evaluate* candidates; they do not create them.
- **No frontier changes.** Selective erasure and frontier rebuild are Task 10.
- **No mid-epoch governance API.** In v1 the facade has exactly one public entry point,
  invoked at the epoch boundary. Per-node governance levels (which nodes get
  adversary/defender/judge attention mid-epoch) are Task 12 cost policy plus Task 06 flow.
- **No change to simple_bfts.** Under the default mode the orchestrator is never
  constructed and no new file is written.
- **No CLI surface change** (keeps the contract-snapshot budget at zero for v1).

## 4. Existing ARI touchpoints

All paths repo-relative; verified to exist on branch `RQGM`.

| Touchpoint | Why it matters to this task |
|---|---|
| `ari-core/ari/cli/bfts_loop.py` — `_run_loop` outer `while` head (~line 181) and the lineage-decision hook block (~lines 721–827) | The epoch boundary hook site. The lineage hook is the working template to mirror: config-gated, rate-limited, deterministic-rule-first, best-effort `try/except` + `log.warning`, append-only JSONL audit. `audit_epoch` is invoked here in `ari_rqgm` mode. |
| `ari-core/ari/orchestrator/lineage_decision.py` — `VALID_ACTIONS`, `LineageDecision.fallback_continue`, `_parse_decision`, `append_decision_log` | Governance precedent: closed action set, malformed-LLM-output → safe default, self-contained JSONL records that never raise into the loop. Every LLM-backed submodule below copies this shape. |
| `ari-core/ari/cli/lineage.py` — `_load_lineage_decision_config`, `_execute_lineage_decision` | Precedent for loading governance config and for the separation between *deciding* and *executing* a decision (here: GovernanceOrchestrator decides, Task 09 executes). |
| `ari-core/ari/protocols/stores.py` — `TraceStore`, `CheckpointStore` | Where a `GovernanceStore`/`AuditStore` Protocol would sit (Task 02 owns the store; this plan only names the read/write interface it needs). |
| `ari-core/ari/paths.py` — `PathManager.META_FILES`, `_TRACE_FILES` | Any new checkpoint-root governance file must be registered here or it contaminates node work dirs and `node_report.files_changed`. |
| `ari-core/ari/prompts/_provenance.py` — `record_prompt_use`, `hash12` | Every governance prompt render is recorded to `prompt_trace.jsonl` with the existing `sha256[:12]` scheme. `prompt_hash` in all governance records **is** this `hash12` value (no second hash scheme). |
| `ari-core/ari/prompts/registry.py` — `PromptRegistry`, `PromptEntry` | The proto-PromptSpec that Task 02/07 extend; `audit_epoch` receives the extended `prompt_registry` and reads role/status/hash from it. |
| `ari-core/ari/core.py` — `build_runtime` | Composition root. In `ari_rqgm` mode the GovernanceOrchestrator is constructed here (config-conditional wiring, precedent: `hpc_enabled`, `axis_mode`) and handed to `_run_loop` by *wrapping* an existing returned object — never by extending the 6-tuple (4 positional call sites). |
| `ari-core/ari/config/__init__.py` — `ARIConfig`, `apply_bfts_env_overrides` | `load_config` filters unknown top-level YAML keys, so `rqgm.governance.*` must live inside the typed `RQGMConfig` block that Task 01 adds to `ARIConfig`. |
| `ari-core/ari/cost_tracker.py` — `CallRecord`, `set_default_metadata` | Per-audit cost attribution: governance LLM calls tagged `phase="governance"`, `skill="governance_orchestrator"`, plus the additive `epoch` metadata field (Task 02/12). |
| `ari-core/ari/evaluator/llm_evaluator.py` — results.json merge; `ari-core/ari/cli/bfts_loop.py` sterile gate | The existing "deterministic evidence beats LLM opinion" precedents. The AdjudicationPanel follows the same doctrine: ReplayBoard/AnchorBoard deterministic scores bound what the GovernanceJudge may conclude. |
| `ari-core/ari/orchestrator/node_report/builder.py` — `build_node_report` | Node reports are a primary observation source for the ReliabilityMonitor (per-node axis scores, file-diff evidence, concerns). |
| `ari-core/ari/trace_store.py` — `JsonlTraceStore.append_trace` | Dormant per-node trace seam; a candidate secondary observation channel, not required for v1. |
| `ari-core/ari/schemas/node_report.schema.json` | Pattern for the new `governance_report.schema.json` (draft-07, `schema_version: const 1`, loadable via `ari.schemas.load`). |
| `ari-core/ari/viz/api_orchestrator.py` — launch gates (~lines 128–163) | If a GovernanceReport ever influences child-run launches, it rides additive `meta.json` fields read by these gates (out of scope for v1; noted for Task 09/02). |

## 5. Proposed design

### 5.1 Facade and placement

One public class, one public method, one public return type:

```python
# ari-core/ari/rqgm/governance/__init__.py  (proposed new package; final home
# coordinated with Task 02's ari/rqgm/ package layout)
__all__ = ["GovernanceOrchestrator", "GovernanceReport"]
```

Everything else lives in underscore-private modules and is **not** re-exported, not
added to `ari.public.*`, and not exposed as MCP tools:

```
ari-core/ari/rqgm/governance/
  __init__.py          # facade export only
  _pipeline.py         # audit_epoch step sequencing
  _reliability.py      # ReliabilityMonitor, MetaReliabilityMonitor
  _evidence.py         # EvidenceClerk, EvidenceAuditChecker, SourceRefValidator
  _prosecution.py      # Auditor, Prosecutor, BondAccounting
  _defense.py          # Defender
  _adjudication.py     # GovernanceJudge, ReplayBoard, AnchorBoard, JuryPanel
  _self_audit.py       # GovernanceSelfAudit
  _records.py          # dataclasses for all record types in §6
```

Rationale: the spec's fine-grained actor names are a *conceptual* vocabulary. Exposing
them as public API would freeze a dozen unstable interfaces into the contract-snapshot
surface. Only the facade is a commitment; internal actors can be refactored freely until
their behavior is pinned by tests.

External API (spec-fixed signature):

```python
governance_report = governance_orchestrator.audit_epoch(
    epoch_state=epoch_state,                    # Task 02 EpochState
    audit_log=audit_log,                        # Task 02 ImmutableAuditLog reader
    component_registry=component_registry,      # Task 02
    prompt_registry=prompt_registry,            # Task 02/07
    candidate_prompts=candidate_prompts,        # Task 07/08 candidates, may be empty
    adversarial_replay_pool=adversarial_replay_pool,  # Task 06, may be None
)
```

`audit_epoch` is **read-only** with respect to registries, the frontier, `tree.json`,
and node state. Its only writes are: governance records appended to the RQGM audit log,
prompt-provenance lines via `record_prompt_use`, the step-7 AdversarialReplayPool update
— new/updated `AdversarialReplayCase` records appended to Task 06's append-only case log
(working name `rqgm_adversarial_cases.jsonl`), from which the derived pool snapshot is
rebuilt: the pool is a pure projection of appended records, never an in-place mutation
(§5.3 step 7; §6.1 `replay_pool_updates`; Task 06 §5.8) — and the returned
`GovernanceReport` (also appended to the audit log as a record). Applying any
recommendation is Task 09.

### 5.2 Call site and mode gating

In `simple_bfts` mode (default): the `ari/rqgm/governance` package is never imported by
the run path; nothing changes.

In `ari_rqgm` mode: `_run_loop` invokes `audit_epoch` at the epoch boundary determined
by Task 02's EpochState (the head of the outer `while` is the mechanical hook point;
whether an epoch is N outer iterations, N completed nodes, or an event is Task 02's
decision — this plan treats "boundary reached" as an opaque predicate on EpochState).
The call follows the lineage-hook discipline exactly:

```python
# sketch, inside _run_loop, ari_rqgm mode only
if rqgm_enabled and epoch_state.boundary_reached(...):
    try:
        report = governance.audit_epoch(epoch_state=..., audit_log=..., ...)
        # report handed to RegistryTransitionEngine (Task 09); this plan stops here
    except Exception:
        log.warning("governance audit failed; continuing without report", exc_info=True)
        report = None    # fail-open: BFTS continues; epoch rolls over unchanged
```

Coexistence with the lineage-decision hook: in v1 they are **separate** mechanisms with
separate config, separate rate limiting, and separate JSONL streams (`lineage_decisions.jsonl`
vs. the RQGM audit log). The lineage hook keeps governing research direction per node;
`audit_epoch` governs components per epoch. Unifying the two hooks is explicitly deferred
beyond v1 — the rate-limiting/interplay question is tracked as a risk in §10 of this plan
("Epoch-boundary definition is upstream") — and nothing in this design precludes it.

### 5.3 The nine-step pipeline and its determinism budget

| # | Step | Submodule group | Class | Fallback on failure |
|---|---|---|---|---|
| 1 | Collect observations | pipeline | **Deterministic** scan of the epoch's audit-log slice: ValidatedAttackRecords, ReviewRecords, JudgmentRecords, UtilityRecords, ComparisonObservations, node reports, kernel violation events | Empty observation set → steps 2–6 become no-ops |
| 2 | Assess reliability | ReliabilityAssessment | **Deterministic** aggregation per `(component_id, prompt_hash)`: counts, validated-attack involvement, agreement rates, calibration stats. MetaReliabilityMonitor runs the same aggregation over governance-role components | Missing stats → `reliability_score: null`, flagged `insufficient_data` |
| 3 | Assemble evidence | EvidenceAssembly | **Deterministic**. EvidenceClerk builds EvidenceBundles from record refs + hashes; SourceRefValidator resolves every ref against the audit log / stores; EvidenceAuditChecker verifies bundle completeness and admissibility (drops same-role-authored reports, §5.4) | Unverifiable ref → item excluded with reason; bundle never silently pads |
| 4 | Decide prosecution | ProsecutionDecision | **Rule-first, LLM-second.** Prosecutor applies deterministic thresholds (e.g., ≥N high-severity validated attacks affecting a component, reliability below floor). Only threshold-borderline cases go to the LLM Auditor. BondAccounting deterministically debits a bond per filed motion | LLM failure/malformed → no motion filed (incumbent presumption) |
| 5 | Generate defense | DefenseGeneration | **LLM** Defender writes a rebuttal for each motion, seeing the motion + bundle + the target's own outputs | LLM failure → recorded procedural default defense: "no substantive defense generated; incumbent presumption applies" |
| 6 | Adjudicate | AdjudicationPanel | **Bounded LLM.** ReplayBoard scores candidates/incumbents on AdversarialReplayPool cases; AnchorBoard scores on held-out anchor cases (both deterministic given cached case results, Task 12 caching). GovernanceJudge (LLM) rules each motion `upheld / partially_upheld / dismissed` but **cannot contradict** board scores or fixed-verifier facts; JuryPanel (optional, config-off in v1) aggregates multiple judge samples | LLM failure → `dismissed` (in favor of the incumbent); board failure → `inconclusive`, motion carried to next epoch |
| 7 | Update replay pool | pipeline | **Deterministic** per Task 06 rules: newly upheld attack cases enter the pool; stale/retired-prompt cases marked per Task 10 semantics | Pool update skipped, flagged in report |
| 8 | Governance self-audit | GovernanceSelfAudit | **Deterministic** checks over the governance components' own outputs this epoch (auditor motion precision so far, judge consistency vs. board scores, defender participation rate) + kernel re-validation of all records produced in steps 3–6 | Findings list empty, flagged `self_audit_degraded` |
| 9 | Produce report | pipeline | **Deterministic** serialization of steps 1–8 into a GovernanceReport; appended to the audit log | If even serialization fails, `audit_epoch` raises and the caller's fail-open catch applies |

Rules carried over from repo precedent: every LLM decision has a *total* deterministic
fallback (lineage `fallback_continue` pattern); every LLM render goes through
`load_versioned` + `record_prompt_use`; all governance LLM calls carry
`metadata={"phase": "governance", "skill": "governance_orchestrator", "epoch": epoch_id}`
for cost attribution; step failures degrade the report (recorded in
`degradation_reasons`) instead of aborting the audit.

Governance prompts (auditor / defender / governance judge) are committed `.md` templates
under `ari-core/ari/prompts/` from day one (`scripts/check_prompts.py` flags inline
prompt strings), which means they pass the four prompt-snapshot layers like any other
prompt. Their *evolution* is Task 07/11 scope.

### 5.4 Same-role accusation prohibition (normative)

These rules restate global invariants 4–7 as the operating law of this facade:

1. **Same-role components cannot file impeachment motions.** An ImpeachmentMotion is
   valid only if authored by the Auditor role, and `motion.role != motion.target_role`
   holds structurally (the Auditor is never the target's role). Reviewer v4 cannot
   impeach Reviewer v3; Adversary v2 cannot impeach Adversary v1.
2. **Same-role components cannot submit admissible evidence reports.** An EvidenceBundle
   is valid only if authored by the EvidenceClerk. Generator v3 cannot author Generator
   v1's EvidenceBundle. Bundle *items* whose originating `role` equals the target's role
   are excluded by the EvidenceAuditChecker with reason `same_role_source`.
3. **Same-role outputs are observations, not accusations.** A same-role component's
   disagreement (e.g., Reviewer v4 scoring the same node differently from Reviewer v3)
   is recorded as a `ComparisonObservation` with `admissible_as_evidence: false`. The
   EvidenceClerk may use such observations only as *leads* — pointers telling it which
   primary artifacts (node outputs, fixed-verifier results, cross-role attack records)
   to fetch and independently verify. The observation record itself never appears as an
   evidence item.
4. **GovernanceOrchestrator may audit any output, but no component directly accuses a
   same-role peer.** The pipeline converts observations into motions only via the
   cross-role Auditor path (step 4).
5. **The GovernanceJudge never touches the registry.** Its output is a JudgmentRecord /
   ImpeachmentOutcome inside the report; registry writes are Task 09 only.

Enforcement is **double-layered**: the orchestrator refuses to construct violating
records (constructive prevention, cheap and early), and the ConstitutionalKernel
(Task 04) independently validates every produced record via
`validate_role_separation(record)` — kernel checks "ImpeachmentMotion created by anyone
but Auditor", "EvidenceBundle created by anyone but EvidenceClerk", and the same-role
accusation check. The kernel is the authority; the orchestrator's own checks are an
optimization, not the guarantee. Step 8 re-runs kernel validation over all records the
pipeline produced this epoch, so a buggy or evolved governance component cannot smuggle
a violating record into the report.

### 5.5 BondAccounting (deterministic, v1-minimal)

To discourage frivolous prosecution without an LLM in the loop: each filed motion debits
a fixed bond (config `bond_units_per_motion`) from the epoch's prosecution budget
(`max_motions_per_epoch × bond_units_per_motion`). Bonds are refunded on
`upheld`/`partially_upheld`, forfeited on `dismissed`. A depleted budget means no further
motions this epoch. Balances are pure functions of the epoch's adjudication outcomes,
recorded in the report's `bond_accounting` block, and reset each epoch in v1 (carry-over
penalties are a possible later refinement, noted in §10).

### 5.6 Persistence

Following Task 02's state-layer persistence design
([02_epoch_state_and_registry.md](02_epoch_state_and_registry.md) §5.1: checkpoint-scoped
home, JSONL-as-truth with derived snapshots):

- **Truth = append-only JSONL.** All governance records (observations selected as leads,
  evidence bundles, motions, defenses, adjudications, self-audit findings, and the final
  GovernanceReport) are appended to the RQGM ImmutableAuditLog established by Task 02
  (working name `{ckpt}/rqgm_audit.jsonl`; this plan defers the filename to Task 02).
  Writer modeled on `record_prompt_use`: module lock, no-op without a run pin, never
  raises, additive dataclass fields.
- **No new snapshot file from this task.** The latest report is discoverable by scanning
  the JSONL for `record_type == "governance_report"`; `epoch_state.json` (Task 02) may
  carry a `last_governance_report_id` pointer as a derived convenience.
- Any filename this task does introduce is registered in
  `ari/paths.py:PathManager.META_FILES` (+ `_TRACE_FILES` for JSONL, + the node-report
  blocklists) before first write.
- Timestamps (`created_at`) never enter any hash (P2); record identity hashes, if Task 02
  adopts hash-chaining, are computed over a canonicalized record with volatile fields
  excluded — this plan takes whichever integrity scheme Task 02 lands.

## 6. Data structures / schema changes

All records carry the spec-mandated common envelope:
`record_id, epoch_id, component_id, prompt_hash, role, created_at, source_refs, status`
plus `record_type` and `schema_version` for JSONL multiplexing. `prompt_hash` is the
existing `hash12` (`sha256[:12]`) value, or `null` for deterministic (non-prompted)
authors.

### 6.1 GovernanceReport (draft, `schema_version: 1`)

```json
{
  "record_type": "governance_report",
  "schema_version": 1,
  "record_id": "govreport_epoch_004",
  "epoch_id": "epoch_004",
  "component_id": "governance_orchestrator",
  "prompt_hash": null,
  "role": "governance",
  "created_at": "2026-07-05T12:00:00Z",
  "status": "final",
  "source_refs": ["rqgm_audit.jsonl#epoch_004"],
  "governance_level": 1,
  "degraded": false,
  "degradation_reasons": [],
  "reliability": [
    {
      "component_id": "reviewer_v3", "role": "reviewer", "prompt_hash": "a1b2c3d4e5f6",
      "observation_count": 41, "validated_attack_involvement": 3,
      "agreement_rate": 0.71, "calibration_error": 0.18,
      "reliability_score": 0.55, "insufficient_data": false,
      "evidence_refs": ["adv_case_00042", "obs_00031"]
    }
  ],
  "observations": ["obs_00031"],
  "evidence_bundles": ["evb_00012"],
  "impeachment_motions": ["imp_00007"],
  "defenses": ["def_00007"],
  "adjudications": [
    {
      "motion_id": "imp_00007", "outcome": "partially_upheld",
      "judge_component_id": "governance_judge_v1", "judge_prompt_hash": "0f9e8d7c6b5a",
      "replay_result_ref": "replay_epoch_004_reviewer", "anchor_result_ref": "anchor_epoch_004_reviewer",
      "rationale_ref": "adj_00007"
    }
  ],
  "candidate_evaluations": [
    {
      "prompt_id": "reviewer_prompt_v4", "role": "reviewer",
      "replay_score": 0.83, "anchor_score": 0.79,
      "verdict": "pass", "case_refs": ["adv_case_00042"], "cached": true
    }
  ],
  "replay_pool_updates": { "added": ["adv_case_00051"], "retired": [] },
  "self_audit": {
    "checked_components": ["auditor_v1", "governance_judge_v1", "defender_v2"],
    "kernel_violations_found": 0,
    "findings": [],
    "escalations": []
  },
  "recommendations": [
    {
      "target_component_id": "reviewer_v3", "target_prompt_id": "reviewer_prompt_v3",
      "action": "demote", "basis_refs": ["imp_00007", "adj_00007"], "confidence": 0.7
    },
    {
      "target_prompt_id": "reviewer_prompt_v4",
      "action": "promote_candidate", "basis_refs": ["candidate_evaluations[0]"], "confidence": 0.8
    }
  ],
  "bond_accounting": { "posted": 1, "refunded": 1, "forfeited": 0, "remaining_budget": 1 },
  "budget_usage": { "llm_calls": 5, "replay_cases_used": 6, "anchor_cases_used": 4 }
}
```

`recommendations[].action` is a closed set:
`promote_candidate | promote | demote | warn | quarantine | retire | no_action`
(exact vocabulary reconciled with Task 09's transition table; unknown actions must be
droppable by Task 09 the way `_parse_decision` drops unknown lineage actions). A JSON
Schema `governance_report.schema.json` is added beside
`ari-core/ari/schemas/node_report.schema.json`, draft-07, `schema_version: const 1`,
and validated by the kernel's `validate_record_schema`.

### 6.2 ComparisonObservation (same-role output; never admissible)

```json
{
  "record_type": "comparison_observation", "schema_version": 1,
  "record_id": "obs_00031", "epoch_id": "epoch_004",
  "component_id": "reviewer_v4", "role": "reviewer", "prompt_hash": "b2c3d4e5f6a1",
  "created_at": "...", "status": "recorded",
  "subject_component_id": "reviewer_v3", "subject_role": "reviewer",
  "observation_type": "verdict_disagreement",
  "payload": { "node_id": "node_017", "observer_verdict_ref": "rev_00120", "subject_verdict_ref": "rev_00098" },
  "admissible_as_evidence": false,
  "source_refs": ["rev_00120", "rev_00098"]
}
```

Invariant: `admissible_as_evidence` is `false` whenever `role == subject_role`; the
EvidenceAuditChecker rejects any bundle item pointing at such a record.

### 6.3 EvidenceBundle (EvidenceClerk-only author)

```json
{
  "record_type": "evidence_bundle", "schema_version": 1,
  "record_id": "evb_00012", "epoch_id": "epoch_004",
  "component_id": "evidence_clerk", "role": "evidence_clerk", "prompt_hash": null,
  "created_at": "...", "status": "verified",
  "target_component_id": "reviewer_v3", "target_role": "reviewer",
  "items": [
    { "kind": "validated_attack", "ref": "adv_case_00042", "content_hash": "…sha256…" },
    { "kind": "fixed_verifier_result", "ref": "node_017/node_report.json#files_changed", "content_hash": "…" },
    { "kind": "utility_record", "ref": "util_00077", "content_hash": "…" }
  ],
  "excluded_items": [
    { "ref": "obs_00031", "reason": "same_role_source" },
    { "ref": "raw_attack_00090", "reason": "unadjudicated_raw_attack" }
  ],
  "verification": { "checked_by": "evidence_audit_checker", "all_refs_resolved": true },
  "source_refs": ["adv_case_00042", "util_00077"]
}
```

Note `unadjudicated_raw_attack`: raw adversary attacks are inadmissible until a Judge
produced a ValidatedAttackRecord (global invariants 8–9).

### 6.4 ImpeachmentMotion / ImpeachmentOutcome (Auditor-only author)

```json
{
  "record_type": "impeachment_motion", "schema_version": 1,
  "record_id": "imp_00007", "epoch_id": "epoch_004",
  "component_id": "auditor_v1", "role": "auditor", "prompt_hash": "c3d4e5f6a1b2",
  "created_at": "...", "status": "filed",
  "target_component_id": "reviewer_v3", "target_role": "reviewer",
  "charge": "systematic_overclaim_acceptance",
  "evidence_bundle_id": "evb_00012",
  "bond_units": 1,
  "requested_action": "demote",
  "source_refs": ["evb_00012"]
}
```

`ImpeachmentOutcome` mirrors the adjudication entry (motion_id, outcome, refs) as a
standalone record so Task 09 can consume outcomes without parsing full reports.

### 6.5 Config sketch (inside Task 01's typed `RQGMConfig`)

```yaml
ari:
  mode: simple_bfts          # governance inert unless ari_rqgm
rqgm:
  enabled: false
  governance:
    default_level: 1
    full_governance_only_on_top_k: 3
    judge_on_disputed_only: true
    impeachment_only_at_epoch_boundary: true
    max_llm_calls_per_audit: 12
    max_motions_per_epoch: 2
    bond_units_per_motion: 1
    jury_panel_enabled: false      # JuryPanel off in v1
    fail_mode: open                # open = degrade to no-action report (repo discipline)
  replay:
    max_cases_per_epoch: 8
    max_cases_for_retirement: 12
    use_cached_results: true
```

Budget keys duplicate none of Task 12's semantics; Task 12 owns the numbers, this plan
owns the consumption points. No new env vars in v1 (avoids `docs/reference/` SemVer
freeze until the surface stabilizes).

## 7. API / class changes

New (all additive, none public beyond the facade):

```python
# ari-core/ari/rqgm/governance/__init__.py
class GovernanceOrchestrator:
    def __init__(
        self,
        cfg,                        # RQGMConfig.governance + .replay slices
        *,
        kernel,                     # ConstitutionalKernel (Task 04) — required
        llm=None,                   # governance-phase LLMClient; None → pure-deterministic mode
        audit_writer=None,          # Task 02 append-only writer; None → in-memory (tests)
    ) -> None: ...

    def audit_epoch(
        self,
        *,
        epoch_state,
        audit_log,
        component_registry,
        prompt_registry,
        candidate_prompts=(),
        adversarial_replay_pool=None,
    ) -> "GovernanceReport": ...

@dataclass
class GovernanceReport:            # typed mirror of §6.1; .to_dict() for JSONL
    ...
```

- `llm=None` yields a fully deterministic audit (steps 4–6 use rule-only paths); this is
  the CI-friendly configuration and the guaranteed-degradation floor.
- Changed call sites: `ari-core/ari/core.py:build_runtime` gains a config-conditional
  construction block (`ari_rqgm` only); `ari-core/ari/cli/bfts_loop.py:_run_loop` gains
  the boundary hook of §5.2. Both are wrapped/gated so `simple_bfts` byte-behavior is
  untouched. No change to the `build_runtime` return tuple arity.
- New schema file: `ari-core/ari/schemas/governance_report.schema.json`.
- New prompt templates (committed `.md`, externalized): `governance/auditor.md`,
  `governance/defender.md`, `governance/governance_judge.md` under
  `ari-core/ari/prompts/` — added to the prompt snapshot layers per the standard
  new-prompt checklist.
- No `ari.public.*` additions, no CLI additions, no MCP tool additions in v1.

## 8. Migration / compatibility

- **simple_bfts preserved verbatim**: the governance package is imported only inside the
  `ari_rqgm` conditional in `build_runtime`; the `_run_loop` hook is inert when
  `rqgm.enabled` is false. Zero new files are written in default mode.
- **Fail-open discipline**: `audit_epoch` failures degrade to "no report this epoch";
  the run loop never blocks or crashes on governance (matching every existing optional
  hook). Fail-closed enforcement points (blocking a *transition* on kernel violations)
  belong to Task 04/09, not to this facade.
- **VirSci independence**: nothing in this design references VirSci. `audit_epoch`
  audits whatever generators produced ProposalRecords; with `virsci.enabled=false` the
  pipeline is unchanged.
- **Resume**: `audit_epoch` consumes only checkpoint-persisted inputs (audit log,
  registries, epoch state), so a resumed run can re-enter governance at the next
  boundary; the JSONL append-only log makes a re-run of a crashed audit idempotent at
  the record level (new record_ids, prior partial records remain as history, and the
  report generated last wins via the `epoch_state` pointer).
- **Contract snapshots**: no public-API / CLI / MCP-name churn; prompt snapshot layers
  are extended (not modified) by the three new templates.
- **Additive records**: all dataclasses follow the `CallRecord`/`PromptUseRecord`
  convention — new fields default, absence tolerated by readers.

## 9. Tests

Unit (pure, no LLM, no network — deterministic fixtures of synthetic audit-log slices):

1. **Facade smoke**: `audit_epoch` with empty audit log returns a valid, empty,
   non-degraded report; schema-validates against `governance_report.schema.json`.
2. **ReliabilityMonitor**: known synthetic record mix → exact expected aggregation
   (counts, rates); insufficient data flagged, never fabricated.
3. **EvidenceAssembly**: bundle assembly resolves refs and content hashes; same-role
   items excluded with `same_role_source`; unadjudicated raw attacks excluded;
   unresolvable ref → excluded, `all_refs_resolved=false`, no exception.
4. **Same-role prohibition (constructive)**: attempts to build a motion authored by the
   target's role, or a bundle authored by a non-clerk, are refused by the orchestrator.
5. **Same-role prohibition (kernel)**: a hand-crafted violating record passed through
   `ConstitutionalKernel.validate_role_separation` is rejected — proving the guarantee
   does not depend on the orchestrator's own good behavior (integration with Task 04's
   test fixtures).
6. **Prosecution thresholds + bonds**: deterministic threshold cases file/skip motions
   exactly; motion count capped by budget; bond ledger arithmetic (post/refund/forfeit)
   exact.
7. **Fallback totality**: with `llm=None` and with an LLM stub that raises/returns
   garbage, every step completes; outcomes are the documented defaults (no motion /
   procedural defense / dismissed); `degradation_reasons` populated; no exception
   escapes `audit_epoch` except on report-serialization failure.
8. **Adjudication bounding**: GovernanceJudge output contradicting ReplayBoard/AnchorBoard
   deterministic scores is clamped/overridden and flagged in self-audit.
9. **Budget caps**: `max_llm_calls_per_audit` and replay/anchor case caps respected with
   a counting LLM stub.
10. **Determinism**: same inputs, `llm=None` → byte-identical reports after stripping
    `created_at`/`record_id` volatiles.

Integration / regression:

11. **simple_bfts regression**: existing BFTS loop tests pass unchanged; grep-level
    assertion that no `rqgm` file appears in a default-mode checkpoint.
12. **ari_rqgm smoke**: `_run_loop` with `mode=ari_rqgm`, stub LLM, tiny node budget —
    `audit_epoch` fires at the boundary, a report lands in the audit log, the run
    completes, and tree/results checkpoints are unaffected in shape.
13. **META_FILES hygiene**: any new governance filename is in `META_FILES`/`_TRACE_FILES`
    and never appears in `node_report.files_changed` of a child node.
14. **Cost attribution**: governance LLM calls appear in `cost_trace.jsonl` with
    `phase="governance"` and the epoch tag.

## 10. Risks

- **Epoch-boundary definition settled count-driven (2026-07-28, commit `c050ebf`).**
  Boundaries fire every `rqgm.epoch.nodes_per_epoch` new BFTS nodes
  (`RqgmRuntime.ensure_epoch`, `ari-core/ari/rqgm/runtime.py`), so the event-driven
  contingency never arose and the rate-limiting re-review it was conditioned on is not
  owed: the epoch tick and the lineage hook coexist in `_run_loop`
  (`ari-core/ari/cli/bfts_loop.py`) with separate rate limits and separate audit logs
  (`rqgm_audit.jsonl` vs `lineage_decisions.jsonl`). The §5.2 placement held —
  `audit_epoch` runs first inside `_run_epoch_boundary`, before the transaction.
- **Recommendation-vocabulary drift vs. Task 09.** If the transition table and the
  `recommendations[].action` set diverge, reports become partially unusable. Mitigation:
  closed set, unknown-action-dropping required of Task 09, and a shared constant module
  once both are implemented.
- **Cost blowup.** Defense + adjudication per motion is multiple LLM calls. Mitigation:
  hard caps (`max_motions_per_epoch`, `max_llm_calls_per_audit`), rule-first prosecution,
  `judge_on_disputed_only`, cached replay results (Task 12).
- **Garbage-in role metadata.** Same-role checks are only as good as `role`/`component_id`
  stamping on epoch records (Task 02). A mislabeled record could evade the prohibition.
  Mitigation: kernel schema validation rejects records missing the envelope; self-audit
  re-validates; Task 13's failure injection includes a mislabeled-role case.
- **Judge capture / bias.** An evolved GovernanceJudge could systematically favor
  incumbents or challengers. Mitigation: board-score bounding (§5.3 step 6), self-audit
  consistency stats feeding MetaReliabilityMonitor, and invariant 18 (authority cannot
  expand) enforced by capability fields in the ComponentRegistry (Task 02/11).
- **Monolithic `_run_loop`.** Adding another hook to a ~925-line function increases
  fragility. Mitigation: the hook is ≤ ~20 lines delegating to the facade; any loop
  refactor is out of scope and tracked by Task 01's open questions.
- **Bond design is a stub.** Epoch-reset bonds may under-deter serial frivolous
  prosecution across epochs. Acceptable for v1; carry-over penalties are a candidate
  refinement for Task 11's meta-evolution constraints.

## 11. Completion criteria

Task 05 (this plan's design work) is complete when all of the following hold:

1. **External API defined**: the exact `audit_epoch` keyword signature and the
   `GovernanceReport` return type are specified (§5.1, §7), including read-only
   semantics, fail-open behavior, and the `llm=None` deterministic floor — stable enough
   for Task 09 to design `resolve_transition` against without re-negotiation.
2. **Internal submodules defined**: all six submodule groups (ReliabilityAssessment,
   EvidenceAssembly, ProsecutionDecision, DefenseGeneration, AdjudicationPanel,
   GovernanceSelfAudit) have named actors, responsibilities, determinism class, and
   total fallbacks (§5.3), and are confirmed as private, non-exported internals (§5.1).
3. **GovernanceReport schema draft exists**: §6.1 draft with the mandatory common record
   envelope, closed recommendation action set, and a named JSON Schema file location,
   plus drafts for the supporting records (ComparisonObservation, EvidenceBundle,
   ImpeachmentMotion/Outcome) in §6.2–6.4.
4. **Same-role direct impeachment prohibition stated**: §5.4 states invariants 4–7
   normatively — same-role motions forbidden, same-role evidence inadmissible,
   observations-not-accusations, Auditor-only motions, EvidenceClerk-only bundles,
   Judge-never-writes-registry — with double-layered enforcement delegated to the
   ConstitutionalKernel (Task 04) as the authority.
5. Downstream plans (06, 09, 12, 13) can cite this plan's section numbers for the
   attack-record admissibility rule, the recommendation vocabulary, the budget knobs,
   and the failure-injection hooks respectively, without contradiction at time of
   writing.

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

- The GovernanceOrchestrator skeleton (facade + private submodule modules + nine-step
  pipeline with deterministic fallbacks) is implemented.
- The GovernanceReport schema exists (`governance_report.schema.json` + typed record),
  and reports validate against it.
- The same-role accusation prohibition is checked by the ConstitutionalKernel
  (`validate_role_separation` rejects same-role motions and non-clerk/non-auditor
  authorship), with tests proving the kernel — not only the orchestrator — enforces it.
- `audit_epoch` is callable at an epoch boundary without breaking existing BFTS:
  `simple_bfts` regression suite passes unchanged, and an `ari_rqgm` smoke run completes
  with a report in the audit log.
- Tests for the facade, submodules, fallbacks, budgets, and mode gating (§9) have been
  added.

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

- [ ] The `audit_epoch` public API and GovernanceReport schema are documented in the
      permanent schema reference / architecture docs (not only here).
- [ ] The same-role accusation prohibition and observations-not-accusations rule are
      stated in permanent docs and enforced by ConstitutionalKernel tests.
- [ ] The recommendation action vocabulary is reconciled with Task 09's transition
      table (shared constant or documented mapping).
- [ ] Governance record filenames are registered in `PathManager.META_FILES` /
      `_TRACE_FILES` and the node-report blocklists.
- [ ] `simple_bfts` mode demonstrably writes no governance files (regression test
      referenced from permanent docs or CI).
