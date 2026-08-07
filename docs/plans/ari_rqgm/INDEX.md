# ARI-RQGM Task Plan Index

## Purpose

This directory contains temporary task-level implementation plans for ARI-RQGM.
Each task plan must define completion criteria, deletion criteria, and a delete-after checklist.
Completed plans should be deleted after their essential design decisions are moved to permanent
docs or implementation. This index is NOT a master plan and contains no detailed design; it
manages only the table of contents, progress, dependencies, and deletion status of the task
plans. Auxiliary plans may be added only if this index records their dependencies and deletion
requirements.

## Execution Modes

- `simple_bfts` — preserves current ARI behavior unchanged; the default mode.
- `ari_rqgm` — the opt-in governance/co-evolution mode enabled via config.

Both select the **exploration** strategy. The paper-writing phase has its own orthogonal axis,
`paper.mode: linear | rqgm_archive` (default `linear`, byte-identical to today's paper pipeline),
designed in [../ari_rqgm_paper/INDEX.md](../ari_rqgm_paper/INDEX.md). The two axes are independent:
all four combinations are valid, and `paper.mode` never reads `ari.mode`.

## Active task plans

| ID | Plan | Status | Depends on | Deletion status |
|---|---|---|---|---|
| 00 | 00_current_ari_investigation | completed | none | not deletable |
| 01 | 01_execution_modes_and_compatibility | implemented | 00 | not deletable |
| 02 | 02_epoch_state_and_registry | implemented | 00, 01 | not deletable |
| 03 | 03_proposal_record_router_and_virsci | implemented | 00, 01, 02 | not deletable |
| 04 | 04_constitutional_kernel | implemented | 00, 02 | not deletable |
| 05 | 05_governance_orchestrator | implemented | 00, 02, 04 | not deletable |
| 06 | 06_adversarial_evolution | implemented | 00, 03, 04, 05 | not deletable |
| 07 | 07_prompt_spec_and_prompt_evolution | implemented | 00, 02, 04, 05, 06 | not deletable |
| 08 | 08_clean_room_regeneration | implemented | 00, 04, 07, 09 | not deletable |
| 09 | 09_registry_transition_engine | implemented | 00, 02, 04, 05, 07 | not deletable |
| 10 | 10_frontier_repair_and_selective_erasure | implemented | 00, 02, 04, 09 | not deletable |
| 11 | 11_meta_agent_evolution | implemented | 00, 07, 08, 09 | not deletable |
| 12 | 12_cost_control_and_context_budget | implemented | 00, 01, 02, 03, 04, 05, 06 | not deletable |
| 13 | 13_evaluation_and_ablation | implemented | 00, 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12 | not deletable |
| 14 | 14_governed_utility_evolution | implemented | 00, 02, 04, 07, 09, 10 | not deletable |
| 15 | 15_validated_attack_target_binding | implemented | 05, 06 | not deletable |
| 16 | 16_knowledge_skill_registry_and_separation_foundation | in progress | 00, 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15 | not deletable |
| 17 | 17_capability_provider_semantics_and_binding | in progress | 01, 04, 12, 16 | not deletable |
| 18 | 18_scientific_assurance_and_harness_registry | in progress | 01, 04, 12, 16, 17, ari_rqgm_paper/07 | not deletable |
| 19 | 19_rqgm_governance_integration | in progress | 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 14, 15, 16, 17, 18, ari_rqgm_paper/07 | not deletable |
| 20 | 20_meta_evaluation | in progress | 13, 16, 17, 18, 19 | not deletable |

Status legend: `implemented` = every completion criterion, including required external parity,
has executable evidence on the working branch and the local suite is green; `in progress` =
implementation and tests have landed but at least one completion gate remains; `planned` = design
written and cross-checked, no code or tests landed yet. Plans stay
`not deletable` until their deletion criteria are met (merge to main, CI green, key decisions
migrated to permanent docs). 14 and 15 are auxiliary plans added under the Purpose rule above:
their dependencies are recorded in the table, and their deletion requirements are the standard
ones — each plan's own completion + deletion criteria plus the Plan deletion procedure below.

Tasks 16–20 are the in-progress, consecutively numbered **ARI
Knowledge–Capability–Assurance Separation** initiative. The flat sequence is
intentional: this directory has no parent-task mechanism. Task 16 fixes the
terminology, architecture, shared contracts, and Knowledge Skill Registry;
Task 17 owns Capability Provider semantics and deterministic binding; Task 18
owns the Harness Registry and Scientific Assurance; Task 19 connects the three
layers to fixed RQGM authority, execution, evidence, frontier, and publication;
Task 20 extends Task 13's meta-evaluation without changing B0–B8. The five
plans are part of this canonical index and are not an auxiliary master plan.

## Deleted task plans

| ID | Former plan | Deleted in | Reason |
|---|---|---|---|
| — | — | — | — |

## Global invariants

Only the most important invariants are summarized here; detailed invariants live in the task
plans.

- The active component set, prompt hashes, utility policy, and scoring rule are frozen within an
  epoch — within-epoch only, not constant per run. At each boundary the utility policy itself
  (`composite` / `axis_weights` / `frontier_score`, `ari-core/ari/rqgm/state.py:354-382`) is
  rewritten through the same governed path as prompts — RegistryTransitionEngine, validated by
  the ConstitutionalKernel — per Task 14.
- Prompt changes happen only at epoch boundaries, through the RegistryTransitionEngine, and every
  transition is validated by the ConstitutionalKernel.
- Same-role components cannot file accusations against each other; same-role outputs are
  observations only.
- Raw adversary attacks never touch the BFTS score; only adjudicated ValidatedAttackRecords have
  scoring effect.
- Selective erasure is logical-only: nothing is physically deleted; stale records are excluded
  from frontier scoring AND from best-node selection (`verified_context.select_best_node`:
  paper candidate / archive seed / verified-context lineage; all-erased ⇒ no winner).
- The ConstitutionalKernel, fixed verifier, and audit log never evolve.
- VirSci is optional and must never be a hard dependency.
- `simple_bfts` mode preserves existing ARI behavior unchanged.

## Plan deletion procedure

A plan file is deleted only through the following operation:

1. Satisfy the plan's completion criteria.
2. Satisfy the plan's deletion criteria.
3. Move key design decisions to permanent docs or code comments.
4. Update INDEX.md (status, deletion status, Deleted task plans table).
5. Delete the plan file.
6. State the deletion reason in the commit message.

A plan must NOT be deleted when any of these hold: implementation is incomplete; no tests exist;
CI is failing; open questions remain; a downstream task depends only on this plan; design
decisions have not yet been moved to permanent docs; INDEX.md has not been updated; or deleting
the plan would lose specification.

## Current focus

Tasks 16–20 are `in progress`. The 2026-08-05 implementation checkpoint has
landed the RQGM-independent contracts/catalogs/resolvers, immutable admission
and resume artifacts, deterministic prompt composition and bound tool view,
fixed constitutional roles/checks, node/frontier/evidence/governance wiring,
native GEMM/SpMM/Stencil verifier core, H/K meta-evaluation probes, separate
CLI/MCP/dashboard surfaces, schemas, permanent documentation, pinned external
Knowledge import, three independently pinned candidate Intel performance
Knowledge entries, observed GPU/SLURM admission, exact ToolUniverse semantic
projection/substitution diagnostics, typed external Harness parity reports,
and fixed-verifier resource accounting. A real anonymous-node CPU job passed all three
native reference/negative-control families; the compute node exposed four V100
devices, but they remain non-schedulable for KCA admission because the cluster
advertises no GPU GRES.

The tasks are deliberately not marked `implemented`: verified promotion of
remote Provider routes and Inspect, Harbor, PaperBench,
KernelBench, ComputeEval, and scBench Harness entries still requires authentic
upstream full commits, dataset/container/license pins, official-runner parity,
negative controls, and permitted GPU scheduling/model credentials. The exact
ToolUniverse 1.3.1 upstream lock remains a failed `candidate`, but the separately
identified metadata-only `1.3.1+ari.1` artifact now has a reproducible wheel,
closed runtime lock, full registration evidence, explicit human promotion
approval, and a verified lock restricted
to anonymous `PubMed_search_articles -> ari.literature.search/v1`; all other
ToolUniverse leaves remain unadmitted. PaperBench upstream API/aggregation parity
passes, but official rollout→reproduction→judge parity remains unavailable. The
checked-in external driver facades fail closed and the production Harness
catalog remains empty until those artifacts are supplied; no mutable source,
fabricated pin, skipped parity result, or always-pass placeholder is admitted.

Two additional Provider scopes now have independent, evidence-bound verified
locks: Qiskit MCP 0.3.1 with Qiskit Aer 0.17.2 for anonymous local ideal
simulation only, and OpenROAD MCP 0.6.1 with OpenROAD-flow-scripts 2026-Q3 for
the GCD/Nangate45 local x86_64 CPU flow only. IBM Quantum Runtime, remote
simulators, and hardware remain candidate because no credential-bound backend,
configuration, calibration, QPY, golden, or replay evidence is present.
OpenROAD anonymous exclusive-node SLURM CPU execution is now a separately
promoted GCD/Nangate45 Provider identity; its lock requests zero GPUs and stores
only a salted site digest. OpenROAD GPU execution, other designs/PDKs, and full
default-flow parity remain outside both exact Provider identities and require a
separately named candidate, evidence bundle, human approval, and verified lock. Promotion
does not activate either Provider in the empty checked-in `CATALOG.lock`;
activation remains a separately admitted, run-frozen catalog/Provider/Binding
lock decision.

Tasks 00–13 are implemented on the working branch: the `ari-core/ari/rqgm/` package (mode
resolution, epoch state + registries + hash-chained audit log, proposals/router
with optional VirSci adapter, constitutional kernel, governance orchestrator, adversarial
evolution, prompt-spec lifecycle, clean-room regeneration, registry transition engine, frontier
repair / selective erasure, meta-agent tier, cost control, evaluation/ablation harness), with
the full local suite green and `simple_bfts` behavior unchanged. Remaining before plans become
deletable: merge to main, CI green on the remote, migration of key design decisions into the
permanent docs (execution-mode guide, schema reference, RQGM developer guide), and resolution of
each plan's open items recorded in its deviations. Deviations from plan text discovered during
implementation are recorded in the implementation history; consult the per-task sections of the
permanent docs once written.

Tasks 14 and 15 are NEW and both `implemented` — code + tests landed on the working branch. Both
close seams in the shipped `ari-core/ari/rqgm/` package, and both are fixed once here at the parent
level, so the paper-archive set ([../ari_rqgm_paper/INDEX.md](../ari_rqgm_paper/INDEX.md)) inherits
them topology-agnostically and builds no local machinery for either. Task 14's pillar-P1 guarantee
(the score is rewritten at boundaries) was proven by execution — a `utility_policy_hash` that
changes across real boundaries on the natural governed path via the T20 supersession spine — not by
a green suite alone; an earlier landing shipped inert (the spine was dead) and was caught by an
execution verifier, so treat "the suite is green" as necessary but not sufficient for this task.

- **14 — governed utility evolution** (`implemented`) closed the cause half of the epoch-boundary
  utility rewrite: at epoch boundaries the entire score is rewritten. **The defect it repaired**
  (past tense — the code has landed, see the status note below): only
  `ari-core/ari/rqgm/state.py:270,276` genuinely covered the scoring policy — it puts
  `utility_policy` inside `epoch_fingerprint`, so a rewrite would at least be visible. The
  consequence machinery existed but was bound to the
  wrong policy: `ari-core/ari/rqgm/frontier_repair.py:99-101` carries the right semantic (a node
  whose score's policy came from a retired `utility_policy` is invalidated — "no recompute can
  launder that"), yet the only record bearing that role is `UtilityRecord`, whose
  `utility_policy_hash` is `UtilityPenaltyPolicy`'s hash over `{penalty_cap, severity_weights,
  verdict_factors}` (`ari-core/ari/rqgm/adversarial/engine.py:947-963`) — a **different** policy
  from `capture_utility_policy`'s `{composite, axis_weights, frontier_score, …}`
  (`ari-core/ari/rqgm/state.py:336`). A scoring-policy retirement therefore matched no record at
  all; [14_governed_utility_evolution.md](14_governed_utility_evolution.md) §5.8 closed that
  circuit. The cause half was missing outright: `capture_utility_policy` read only the static
  resolved cfg, so `utility_policy_hash` was a
  permanent constant ("In v1 the frozen policy is constant across epochs within a run … per-epoch
  re-weighting is a Task 10/13 decision"). It now resolves the ADOPTED `utility_policy` entry from
  the registries (`ari-core/ari/rqgm/state.py:354-382`), falling back to the resolved cfg only at
  epoch 0 / `simple_bfts` / a pre-14 resume, so the hash changes across epochs exactly when the
  score is genuinely rewritten through the governed path. At the time of writing,
  no transition rule targeted utility/weight/axis (T20 now does); and
  `utility_policy` is in neither `EVOLVABLE_ROLES` nor `FIXED_ROLES`
  (`ari-core/ari/rqgm/events.py:57,73`). v1 deferred this as the I-11 "axes frozen per run"
  decision ([10_frontier_repair_and_selective_erasure.md](10_frontier_repair_and_selective_erasure.md):515),
  assumed at [13_evaluation_and_ablation.md](13_evaluation_and_ablation.md):435 — **Task 14
  overturns that decision**, and both sites now record the repeal rather than the deferral
  (14 §5.10). The gap is method-wide: the exploration phase violates the rewrite
  too, which is why 14 is a parent task and not a paper-set one.
- **15 — validated-attack target binding** (`implemented`) built the missing rail in the
  validated-attack → impeachment chain. The defect it repaired: `ValidatedAttackRecord.to_dict`
  emitted `affected_components` (ROLE names) and `target_artifact_hash` but never
  `target_component_id`, while `ari-core/ari/rqgm/governance/_reliability.py:37,61` counts a record
  into `validated_attack_involvement` only when `target_component_id` matches — so
  `attacks_by_target` was always empty, the count structurally 0, and the `ATTACK_THRESHOLD = 2`
  route in `classify_target` (`ari-core/ari/rqgm/governance/_prosecution.py:34,89-92`) could never
  file a motion. 15 added the field (emitted only when non-empty, so existing records stay
  byte-identical), resolved ROLE → active `component_id` at record construction against the
  epoch-frozen map, and proved the full chain to a T10 registry sanction in tests.
  **The chain still does not fire in production, by design.** `_AFFECTED_ROLES_BY_TYPE`
  (`ari-core/ari/rqgm/adversarial/round.py`) is deliberately EMPTY for the seven exploration
  adversaries: the artifacts they attack are authored by the `generator` role, which has no
  `FOUNDING_COMPONENT_TABLE` row, so naming it would resolve to `""` and change only record bytes
  for zero governance effect (15 §5.4; 15 forbids closing this by adding a founding row). The
  mechanism is role-driven, so the binding goes live the day an artifact-authoring role has a
  registered incumbent — first at the paper set's `paper_self_preference` → `paper_reviewer`
  ([../ari_rqgm_paper/05_adversarial_self_preference.md](../ari_rqgm_paper/05_adversarial_self_preference.md)),
  whose `paper_reviewer_v1` IS a founding component. Read 15 as "the rail is laid and proven", not
  as "impeachment is now reachable". Jointly owned by 05 (the prosecution path) and 06 (which owns
  `adversarial/records.py`).

**The I-11 repeal has landed (docs).** The sites that relied on I-11 — 01, 06, 07, 09, 10, 13, plus
the seventh site 02's score-comparability note, which the original enumeration missed because it
never types the string "I-11" — now say what
[14_governed_utility_evolution.md](14_governed_utility_evolution.md) §5.10 requires: the deferral to
Task 10 is re-pointed to Task 14 (01, 02, 06, 07, 09), 09 additionally names the **T20** amendment
rather than the withdrawn "no new rule ids" claim (its own T1–T19 base table plus the T20/T21
role-scoped amendments = the shipped T1–T21), Task 10's "must not silently re-weight" survives
verbatim with its owner corrected and §5.8 delta 2 recorded (10), and 13's conditional has fired —
metric 10 is now reported per-weight-regime **always**, with a B9 rung (`utility_evolution.enabled`
on, against B8 with it off) added so B9−B8 measures whether governed rewriting earns its cost. This
resolves the contradiction previously accepted here while 14 was unwritten; the earlier deferral was
reviewed (2026-07-16), not an oversight, since re-opening six `implemented` plans is a
status-bearing change that belonged in 14's own commit. §11 criterion 8 makes landing all six a
completion requirement, and §13 puts them on the delete-after checklist. **Task 14's code has now
landed**, so the six sites describe the branch, not just the design. 14 §5.8's two deltas into Task
06 (`adversarial/engine.py`) and Task 10 (`frontier_repair.py`) shipped inside 14's own change
(recorded in 14 §10 R3); they are additive and argued from those modules' own contracts, but neither
06 nor 10 is deletable until its owner has signed them off.
