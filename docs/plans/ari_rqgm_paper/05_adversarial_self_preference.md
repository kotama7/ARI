# Task 05: Adversarial Self-Preference (paper-phase)

> **Status**: planned · **Depends on**: 00, 03, 04, [../ari_rqgm/06](../ari_rqgm/06_adversarial_evolution.md) · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

> **Implementation note (wave 3c, 2026-07-16).** Landed, replacing the wave-3b
> forged-evidence bridge. Deltas from this plan, each recorded where it lands:
> 1. **Founding rows live in the gated `PAPER_FOUNDING_*` tables**, NOT
>    inserted alphabetically into the shared `FOUNDING_PROMPT_TABLE` adversary
>    block (§5.6). This preserves exploration byte-identity the same way plan
>    03 does for the writer/reviewer rows, and SUPERSEDES §5.6/§9's "insert
>    alphabetically so the rollup winner is unchanged" sketch. Consequence
>    (recorded, not silent): because the gated block registers after the seven,
>    the adversary role's rollup winner **in paper mode** becomes
>    `adversary_paper_self_preference` rather than `adversary_reproducibility`
>    — harmless (every adversary still stamps its own `adversary_{type}_v1` id
>    via the family guard, so no record bytes change; only
>    `active_prompt_hashes["adversary"]`, which already differs from
>    exploration in paper mode, moves). §9's "rollup unperturbed" assertion is
>    dropped.
> 2. **`CONSTITUTION_HASH` DID move** (564a204dc694 → 6643c12a510e), but NOT
>    from the founding rows (§3's claim that founding rows leave it unaffected
>    is confirmed empirically). It moved because the **wave-3c incumbent-
>    adoption fix** added transition-table row **T21 (`active -> shadow`)**, the
>    paper-role shadow-standby supersession edge (plan 03 §5.9); the table
>    feeds `_canonical_rules_payload`, so the new row re-pins the hash.
> 3. **The trigger is organic and anchor-driven.** `_score_reviewer_on_anchor`
>    (paper_runtime.py) fires a REAL `paper_self_preference` adversarial round
>    against the drafts the incumbent reviewer OVER-ACCEPTED (accepted an anchor
>    case whose ground truth is reject). The anchor supplies the pre-signal
>    (§5.1 clause 3, extended: the direct per-draft anchor over-acceptance joins
>    the gate-finding and authorship-margin signals); the genuine
>    adversary→Defender→ArtifactJudge round produces the ValidatedAttackRecord
>    whose `target_component_id` resolves to `paper_reviewer_v1` (Task 15). The
>    forged `_emit_anchor_attack` is DELETED.
> 4. Tests: `ari-core/tests/test_paper_self_preference.py` (§9).

## 1. Purpose

The RQGM paper's §5.4 is about a *self-preference* failure of an evolving reviewer: an
LLM manuscript reviewer that co-evolves to please the writer drifts into **over-leniency
toward AI-authored papers** — it accepts machine-written drafts a fair reviewer would
reject. The paper's remedy is an adversary that surfaces the "papers the displaced
evaluator accepted", pools them, and imposes a **dual objective** on the next generation
of reviewer prompts: *keep rejecting the AI papers you were fooled by* **while** *keeping
your accuracy on the human ground-truth anchor*.

This task ports that §5.4 loop to ARI's paper-archive co-evolution (the best-first draft
tree of [02_paper_draft_archive_search.md](02_paper_draft_archive_search.md), scored by
the governed `paper_reviewer` role of
[03_writer_reviewer_governed_roles.md](03_writer_reviewer_governed_roles.md), anchored by
the ground-truth corpus of
[04_anchor_utility_and_epoch_winners.md](04_anchor_utility_and_epoch_winners.md)). The
central design claim is that the *adversarial machinery* is largely reused. ARI's
exploration-phase adversarial loop
([../ari_rqgm/06_adversarial_evolution.md](../ari_rqgm/06_adversarial_evolution.md)) is
*already* built, *already* paper-phase aware, and *already* topology-agnostic:

- the attack → defense → adjudication loop (`AdversaryEngine` / `Defender` /
  `ArtifactJudge`, `ari-core/ari/rqgm/adversarial/engine.py`) runs unchanged;
- validated attacks accumulate in the **`AdversarialReplayPool`**
  (`ari-core/ari/rqgm/adversarial/pool.py`) — described in
  [../ari_rqgm/06](../ari_rqgm/06_adversarial_evolution.md) §5.8 verbatim as "ARI's
  analogue of the RQGM paper's *artifacts the displaced evaluator accepted*";
- the **dual objective** — reject the pooled AI papers while keeping human-anchor
  accuracy — is imposed at the next boundary. *(Corrected 2026-07-17: this is NOT two
  stages of an existing `CandidateValidationPipeline`. That class
  (`ari-core/ari/rqgm/prompt_evolution.py:724`) is defined but instantiated NOWHERE in
  production — for every role. The two boards are computed by NEW paper-side code:
  `PaperArchiveRuntime._candidate_replay_board` (the pooled `paper_self_preference` replay
  board — the read side the pool never had) and `score_reviewer_on_anchor` (the held-out
  corpus board), emitted from `_paper_candidate_evaluator` as the candidate's
  `replay_score`/`anchor_score` and merged into `candidate_evaluations` for
  `resolve_transition`'s T3 dual gate. See §5.5.)*

What this task actually adds is **one new adversary type** (`paper_self_preference`), a
deterministic pre-signal, one prompt template, one small **human/AI authorship
corpus** with a config home — AND the two dual-objective boards + candidate evaluator +
the candidate constitutional DROP that the "already implemented" framing wrongly assumed
were free (§5.5). The attack loop, record schemas, Judge, replay pool, penalty channel,
selective erasure, and budget ARE reused byte-for-byte; the dual-objective READ side is
new. This doc's job is to specify the new adversary and to specify (not merely "prove")
that boundary machinery.

## 2. Scope

- The `paper_self_preference` adversary type: target artifact class, deterministic
  pre-signal, evidence sources, trigger conditions, and its degradation behavior when no
  authorship corpus is present.
- The one prompt template `ari-core/ari/prompts/rqgm/adversary_paper_self_preference.md`,
  its registration in the four prompt-snapshot layers, and — so the eighth adversary is
  governed on exactly the terms of the seven, with no authority they lack and no immunity
  they lack — its two paper-mode-gated **founding rows** (`FOUNDING_PROMPT_TABLE` +
  `FOUNDING_COMPONENT_TABLE`, §5.6).
- The **human/AI authorship corpus** and its config home
  (`rqgm.paper.self_preference.*`): what it is, its irreducible data cost, and a minimal
  bootstrap so the plan is buildable. This is the *only* new data dependency this doc
  introduces (the accept/reject anchor corpus is
  [04](04_anchor_utility_and_epoch_winners.md)'s).
- The mapping of §5.4's **displaced-reviewer-accepted-AI-papers → replay pool →
  next-epoch dual objective** onto the *existing* `AdversarialReplayPool.admit` (the WRITE
  side, reused) plus the paper-side READ boards that impose the dual objective. *(Corrected
  2026-07-17: the read side is NOT `CandidateValidationPipeline.replay_evaluation`/
  `anchor_evaluation` — that class never runs in production. It is
  `_candidate_replay_board` + `score_reviewer_on_anchor` in `_paper_candidate_evaluator`.
  So: no new pool, reused write side — but a NEW read board, reject AI papers while
  keeping human-anchor accuracy.)*
- The in-phase channel: a validated self-preference attack demotes the over-accepted
  draft through the *existing* `apply_utility_penalty` (§5.4 of
  [../ari_rqgm/06](../ari_rqgm/06_adversarial_evolution.md)).
  **Landed scope (wave 3c, recorded 2026-07-16):** the trigger the anchor supplies is a
  *reviewer accountability* signal — `_score_reviewer_on_anchor` fires the round against a
  synthetic `_over_accepted_node` built from the over-accepted anchor CASE (the reviewer
  accepted a reject-labelled case), so the round's `apply_utility_penalty` demotes that
  synthetic node, and the ValidatedAttackRecord (target `paper_reviewer_v1`) drives the
  reviewer's impeachment/co-evolution — the PRIMARY P2 mechanism, and it is proven to fire
  organically. Demoting the actual over-accepted ARCHIVE draft in-phase (so best-belief
  never hands it to the claim gate) is the SECONDARY safety and is **deferred**: it needs a
  per-completed-archive-draft round at the §5.2 placement. Recorded so the two-channel
  framing above is not read as fully wired for real drafts today.
- The additive touchpoints in the parent-06 code needed for the paper type: the closed
  `ADVERSARY_TYPES` / `ADVERSARY_SPECS` extension, one `_FAILURE_PATTERNS` entry, one
  optional `ArtifactBundle` field, one case-typed `expected_behavior` entry — each shown
  to leave the seven exploration adversaries byte-identical.
- The **paper row of the role→`component_id` bridge** (§5.4): naming `paper_reviewer` as the
  role a `paper_self_preference` case implicates, so doc
  [07](07_claim_gate_handoff_and_evaluation.md) §5.8's PI3 names a channel that can fire.
  The resolution mechanism *and* the record field it populates are parent-owned
  ([../ari_rqgm/15](../ari_rqgm/15_validated_attack_target_binding.md) §5.3; §10 R7).

## 3. Non-goals

- **The `paper_reviewer` / `paper_writer` roles, the capability matrix, context views, the
  founding-table MECHANISM (including its `PAPER_RQGM_ARCHIVE` bootstrap gating), the two
  `paper_writer_v1` / `paper_reviewer_v1` founding rows, and the `CONSTITUTION_HASH`
  re-pin** — owned by
  [03_writer_reviewer_governed_roles.md](03_writer_reviewer_governed_roles.md) §5.5. This
  doc consumes those roles and rides that gating seam verbatim; it does not amend the
  constitution (adding an adversary *type* string is not a role and does not touch
  `kernel_rules.py`; founding rows are not part of `_canonical_rules_payload`
  (kernel_rules.py:257–300), so `CONSTITUTION_HASH` is **unaffected** and there is no
  re-pin coupling with [03](03_writer_reviewer_governed_roles.md)).
  **Owned here, not there:** the eighth adversary's own two founding rows (§5.6).
  [03](03_writer_reviewer_governed_roles.md) §3 explicitly non-goals the adversary and its
  §5.5 appends only the two `paper_*` rows — so if this doc does not carry the adversary's
  rows, no doc does, and the eighth adversary would be the one member of the family that
  cannot be warned, put on probation, or quarantined (§5.6).
- **The accept/reject ground-truth anchor corpus, the reviewer utility policy, and epoch
  winners** — owned by [04_anchor_utility_and_epoch_winners.md](04_anchor_utility_and_epoch_winners.md).
  This doc adds an *authorship* label dimension; it does not re-open anchor curation.
- **The archive search substrate, best-belief selection, and `paper_draft_archive.jsonl`** —
  owned by [02_paper_draft_archive_search.md](02_paper_draft_archive_search.md).
- **The prompt-evolution pipeline, `ReplayBoard`/`AnchorBoard`, and candidate selection
  mechanics** — owned by parent
  [../ari_rqgm/07](../ari_rqgm/07_prompt_spec_and_prompt_evolution.md) and
  [../ari_rqgm/05](../ari_rqgm/05_governance_orchestrator.md). This doc only feeds them
  cases and states the dual-objective *semantics*.
- **Impeachment / governance prosecution of the `paper_reviewer` component** — parent
  [../ari_rqgm/05](../ari_rqgm/05_governance_orchestrator.md). The adversary has no
  impeachment authority (invariant carried from parent-06 §1). The validated-attack →
  `validated_attack_involvement` → `classify_target` chain was unreachable for **all eight**
  adversary types — a pre-existing parent-level defect, not a paper one — and parent task
  [../ari_rqgm/15](../ari_rqgm/15_validated_attack_target_binding.md) has now landed the field
  and the construction-time resolution that repair it (§10 R7). The rail exists; what makes it
  carry traffic for `paper_self_preference` is §5.4's single table row, since `paper_reviewer_v1`
  is a registered founding component. Even then this doc claims **no prosecution authority of its
  own**: it names the answerable role and stops. The `paper_reviewer`'s accountability **in this
  doc** remains exactly two channels it owns — the in-phase draft penalty (§5.2) and the
  next-epoch dual objective → `RegistryTransitionEngine` prompt replacement (§5.5) — with any
  motion being parent-05's to file. What this doc *does* own on the
  prosecution side is the bridge's paper row (§5.4): naming `paper_reviewer` as the role a
  `paper_self_preference` case implicates, so that when parent
  [../ari_rqgm/15](../ari_rqgm/15_validated_attack_target_binding.md) lands the field and the
  resolution, the chain closes with no further change here.
- **Cost numbers and the budget ladder** — owned by
  [06_cost_control_and_budget.md](06_cost_control_and_budget.md) and parent
  [../ari_rqgm/12](../ari_rqgm/12_cost_control_and_context_budget.md). This doc declares
  only the knob names it reuses.
- **Any change to `linear` (`paper.mode: linear`) behavior.** No self-preference
  component is constructed, no prompt registered, no corpus loaded, no file written unless
  effective `PAPER_RQGM_ARCHIVE` is active (global invariant 1).
- **Any change to the exploration-phase seven adversaries.** The additions are strictly
  a new eighth type; the seven remain byte-identical (regression test, §9).

## 4. Existing ARI touchpoints

All paths repo-relative. Verified against branch `RQGM` (ari-core v0.9.1).

| Touchpoint | File / symbol | Why it matters here |
|---|---|---|
| The seven-type table + case vocabulary | `ari-core/ari/rqgm/adversarial/records.py` — `ADVERSARY_TYPES` (line 43), `TARGET_ARTIFACT_TYPES` (line 55), `_FAILURE_PATTERNS` (line 779) | `paper_self_preference` is added to the closed `ADVERSARY_TYPES` (which is also the `case_type` vocabulary, records.py:42) and gets one `_FAILURE_PATTERNS` entry. `TARGET_ARTIFACT_TYPES` is **reused unchanged**: the attack targets the existing `paper_claim` class (§5.2). |
| Adversary dispatch specs | `ari-core/ari/rqgm/adversarial/engine.py` — `ADVERSARY_SPECS` (line 463), `AdversarySpec` (line 453), the `_pre_*` pre-signals (lines 392–450) | One `AdversarySpec("paper_self_preference", "rqgm/adversary_paper_self_preference", "paper_claim", _pre_paper_self_preference)` row and one `_pre_paper_self_preference` function join the seven existing `_pre_*` filters; `AdversaryEngine.attack` (engine.py:642) dispatches it with zero change to its loop. |
| Attack→defense→adjudication loop | `ari-core/ari/rqgm/adversarial/round.py` — `AdversarialRound.run` (line 143), `_EXPECTED_BEHAVIOR` (line 42) | `run(node, ..., paper_candidate=True)` **already** carries the paper-candidate trigger clause (round.py:150, 189–191). One case-typed `_EXPECTED_BEHAVIOR["paper_self_preference"]` entry names `paper_reviewer` as the affected role; the seven types keep the generic default. |
| Deterministic bundle assembly | `ari-core/ari/rqgm/adversarial/engine.py` — `build_artifact_bundle` (line 266), `ArtifactBundle` (line 133), `_collect_gate_findings` (line 168) | Already paper-phase aware: it reads `evaluation/claim_evidence_hard_gate_{final,draft}.json`, `verified_context.json`, `related_refs.json` (engine.py:186–218). One additive optional `ArtifactBundle` field (`reviewer_accept_score`, default `None` = never triggers, mirroring `remaining_node_budget = -1`) and one paper-phase population line feed the self-preference pre-signal. |
| Validated-attack construction | `ari-core/ari/rqgm/adversarial/records.py` — `make_validated_attack_record` (line 529), `ValidatedAttackRecord` (line 443) | Reused verbatim: `case_type` becomes `paper_self_preference`; the constructor still refuses any verdict other than `valid`/`partially_valid` and any non-judge author (invariant 9). `affected_components` for a paper case is the resolvable subset of `("paper_reviewer", "paper_writer")` — the round emits one validated-attack record per resolvable role (the writer bound only when the draft is Layer-0-unfaithful). |
| The replay pool ("displaced evaluator accepted") | `ari-core/ari/rqgm/adversarial/pool.py` — `AdversarialReplayPool.admit` (line 212), `select_for_replay` (line 319), `build_failure_summary` (records.py:811) | Admission, dedup by `(case_type, target_artifact_hash)`, eviction, and the `abstract_view`/`replay_view` split are **untouched**. Self-preference cases are just entries with `case_type="paper_self_preference"`. |
| The dual-objective boards | *(Corrected 2026-07-17)* `ari-core/ari/rqgm/paper_runtime.py` — `_candidate_replay_board` + `_paper_candidate_evaluator`; `ari-core/ari/rqgm/paper_anchor.py` — `score_reviewer_on_anchor`. NOT `CandidateValidationPipeline` (`prompt_evolution.py:724`), which is dead in production for every role. | This IS the §5.4 dual objective, computed by NEW paper-side code (not reused pipeline stages): `_candidate_replay_board` scores a candidate `paper_reviewer` on rejecting the pooled AI papers (`replay_score`), `score_reviewer_on_anchor` on the human anchor (`anchor_score`, [04](04_anchor_utility_and_epoch_winners.md)); both merge into `candidate_evaluations` for the T3 dual gate. |
| Board scoring | `ari-core/ari/rqgm/governance/_adjudication.py` — `board_score` (line 59), `BOARD_HIGH`/`BOARD_LOW` (34–35), `CANDIDATE_PASS_THRESHOLD` (38) | The deterministic mean-over-cached-results board; a candidate must clear `CANDIDATE_PASS_THRESHOLD` on both boards. Reused unchanged. |
| In-phase penalty channel | `ari-core/ari/rqgm/adversarial/engine.py` — `apply_utility_penalty` (line 979), `UtilityPenaltyPolicy` (line 907) | A validated self-preference attack rewrites the over-accepted draft node's `_scientific_score` (sterile-gate precedent), so best-belief selection (§[02](02_paper_draft_archive_search.md)) will not hand the over-accepted draft to the claim gate. Epoch-frozen, deterministic, never resurrects a sterile node. Reused verbatim. |
| Paper entry hook | `ari-core/ari/cli/projects.py` — `_rqgm_paper = getattr(_bfts_paper, "rqgm", None)` (line 163), `run_paper_candidate_escalation` (line 171) | The paper-phase runtime is already discovered here (duck-typed, absent under `linear`). The `PaperArchiveRuntime` (§[01](01_paper_execution_mode.md)) constructs the paper `AdversarialRound` and drives per-draft rounds; this doc adds no new entry point. |
| Persistence + registration | `ari-core/ari/paths.py` — `META_FILES`: `rqgm_adversarial_cases.jsonl` (line 455), `adversarial_replay_pool.json` (line 456) | **Already registered.** Self-preference records ride the existing JSONL truth + snapshot; this doc adds **no** new checkpoint filename (part of the "how little is new" claim). |
| Cost metering label | `ari-core/ari/rqgm/adversarial/engine.py` — `_PromptedActor._complete` (line 553), `phase="governance", skill="rqgm_adversarial"` | Self-preference LLM calls inherit the same cost-tracker labels, so [06](06_cost_control_and_budget.md) / parent [../ari_rqgm/12](../ari_rqgm/12_cost_control_and_context_budget.md) meter them with the same knobs. |
| Prompt registration + snapshots | `ari-core/ari/prompts/` — `FilesystemPromptLoader.load_versioned`, `record_prompt_use`; `ari-core/tests/test_prompt_snapshots.py`, `test_prompt_registry.py` | The new adversary `.md` follows the parent-06 §7 pattern: committed template, registered in the expected-key/hash tests and all four snapshot layers. |
| Founding registry tables | `ari-core/ari/rqgm/prompt_spec.py` — `FOUNDING_PROMPT_TABLE` (line 153, adversary block 184–199), `FOUNDING_COMPONENT_TABLE` (line 232, adversary block 233–247), `founding_registration_events` (line 407) | All seven adversaries are founding prompts **and** founding components; nothing auto-registers an eighth (`test_rqgm_founding_bootstrap.py:76–78` pins registry ids == the tables exactly). This doc adds the two rows that put its adversary on the same terms (§5.6), paper-mode-gated per [03](03_writer_reviewer_governed_roles.md) §5.5. |
| Sanction reachability | `ari-core/ari/rqgm/transition_engine.py` — `resolve_transition` (line 414), `entry = comps.get(component_id)` (line 669), `unknown component` rejection (line 692) | The registry lookup that decides whether a warning/probation/quarantine (or the T16 emergency) can land on a component id at all. It is why the §5.6 rows are about **governance**, not evolvability. |
| Governed vs ungoverned prompt bytes | `ari-core/ari/rqgm/prompt_loader.py` — `GovernedPromptLoader.load_versioned` (line 124), ungoverned delegation (127–130), frozen-spec hash refusal (151–158) | A key with no founding spec is delegated byte-identically and **skips** the tamper refusal; the founding prompt row is what turns the refusal on for `rqgm/adversary_paper_self_preference` (§5.6). |

## 5. Proposed design

### 5.1 The `paper_self_preference` adversary (what it detects)

**§5.4 mapping.** The exploration adversaries attack a *defect in an artifact* (an
overclaim, a gamed metric). The self-preference adversary attacks a **reviewer decision**
that the artifact reveals: *this AI-authored draft was accepted (a high `paper_reviewer`
score) at a quality that a fair reviewer — calibrated against the human ground-truth
anchor of [04](04_anchor_utility_and_epoch_winners.md) — would reject.* To stay inside the
**artifact-only targeting** invariant (parent-06 §1: adversaries attack artifacts, never
components), the *target* is the accepted draft's manuscript, typed as the existing
`paper_claim` class; the *observation* that a component is implicated is carried by two
record fields — one live in the tree today, one not. Stated precisely, because the
difference decides what this doc may claim:

- **Live today — `expected_behavior`.** The `ValidatedAttackRecord`'s `expected_behavior`
  keys (`{paper_reviewer, paper_writer}`, §5.2) are what `build_failure_summary`
  (records.py:811) already derives `affected_roles` from —
  `affected_roles=tuple(sorted(validated.expected_behavior))` (records.py:825), no code
  change. This is the channel the pool's contamination-safe `abstract_view` reads (§5.4).
- **Inert today — `affected_components`.** `affected_components` (records.py:464) is
  declared, serialised (records.py:495) and deserialised (records.py:514–515) — and read by
  **nothing**: `grep -rn affected_components ari-core/ari/rqgm --include=*.py` returns only
  `records.py`, and historically no caller passed it. Every governance consumer keys on
  `target_component_id` instead (`governance/_reliability.py:61`,
  `governance/_evidence.py:57`), which `to_dict` did not emit at all until parent task
  [../ari_rqgm/15](../ari_rqgm/15_validated_attack_target_binding.md) landed it. **So
  `affected_components` is NOT, on its own, "an input to parent-05 governance"** — it is the
  observed ROLE, and roles are not what a prosecutor sentences. It reaches governance only via
  parent-15's construction-time role → `component_id` resolution, and only for a case type that
  §5.4 gives a role row (§10 R7).

Neither field is ever a score channel: the adversary observes, it does not sentence
(parent-06 §1).

**Decision — reuse `paper_claim`, do not add a `draft_manuscript` target type.** The
closed `TARGET_ARTIFACT_TYPES` stays byte-identical (records.py:55). Rationale: the
manuscript's *claims* are exactly what over-acceptance is about, `paper_claim` is already
in the set, and adding a target class would re-pin every record-schema test for no
semantic gain. The suspect draft is always pinpointed by an `attack_evidence_ref` into the
draft archive node (`paper_draft_archive.jsonl` entry + the claim-gate report), so no
precision is lost. (The `draft_manuscript` name from the canonical vocabulary is a
`paper_reviewer` *context-view* field — [03](03_writer_reviewer_governed_roles.md) §6 —
not a target-artifact class.)

**Deterministic pre-signal (`_pre_paper_self_preference`, event-driven, LLM-free).** It
fires — the only condition under which the LLM adversary call is made — when **all** hold:

1. the node is a **paper candidate** (`bundle`-carried, set by the paper `AdversarialRound`
   for archive drafts; false for every exploration node → the type is inert outside the
   paper phase);
2. the `paper_reviewer` **accepted** the draft: `bundle.reviewer_accept_score is not None
   and reviewer_accept_score >= accept_threshold` (default `0.6`, mirroring
   `CANDIDATE_PASS_THRESHOLD`);
3. an **over-acceptance signal** is present — at least one of:
   - a claim-evidence hard-gate finding for this draft (`_collect_gate_findings`, engine.py:168
     — `numeric_mismatch` / `missing_evidence` / `uncovered_numeric` / `invariant_violation`);
   - an **authorship-corpus disagreement**: on the held-out authorship sample (§5.3), the
     frozen incumbent reviewer's mean score on AI-labeled papers exceeds its mean on
     human-labeled papers of matched anchor-quality by ≥ `self_preference_margin` (default
     `0.1`) — the deterministic self-preference statistic;
   - **(third bullet, amended 2026-07-17)** a **direct per-draft anchor over-acceptance**:
     the frozen incumbent ACCEPTED this specific held-out anchor case whose human ground
     truth is `reject` (`paper_self_preference.over_accepted_cases`). This is the signal the
     wave-3c implementation note above already announced as "§5.1 clause 3, extended"; it is
     recorded here in the clause it extends. It rides its own bundle field
     (`anchor_over_accepted_case`, the over-accepted `case_id`) and cites its own evidence —
     `EvidenceRef(path="paper_anchor_corpus.jsonl", pointer=<case_id>)`, the case the
     disagreement was measured on — never `paper_self_preference_stat.json`.

**Why the third bullet is a separate signal with a separate ref (recorded 2026-07-17).**
The two are different subjects measured over different samples: bullet 2 is a **population**
statistic over the authorship split, bullet 3 is a **per-draft** fact about one case. On the
default all-human corpus bullet 2 is `0.0` **by construction** (`compute_self_preference_margin`
returns `0.0` when either authorship half is empty) while bullet 3 is live and real. Collapsing
them — stamping `max(population_margin, 1.0)` into `_self_preference_margin` so bullet 2 would
fire for a per-draft finding — makes a margin RATE in [0,1] unconditionally `1.0`, discards the
computed statistic, and hands Defender and the ArtifactJudge a `{"margin": 0.0}` artifact as the
evidence for its own trigger. **The margin field carries the population statistic by value; the
per-draft signal cites the case.** A field a downstream consumer trusts carries what it claims.

When no authorship corpus is configured, clause 3's second bullet is absent and the
adversary degrades to "gate-finding-only over-acceptance attacks" — never an error, never
a crash (mirrors the web-less `PriorArtAdversary` degradation, parent-06 §5.2). When no
anchor corpus is configured at all, the third bullet is absent too (no case, no verdict),
and with no gate finding the type produces zero attacks and costs zero LLM calls.

```python
# planned: ari-core/ari/rqgm/adversarial/engine.py  (one new pre-signal, joins the seven)
def _pre_paper_self_preference(bundle: ArtifactBundle) -> list[EvidenceRef]:
    # Inert off the paper phase and for un-accepted drafts (fail-safe defaults).
    if not bundle.paper_candidate or bundle.reviewer_accept_score is None:
        return []
    if bundle.reviewer_accept_score < bundle.accept_threshold:
        return []
    # Over-acceptance signal 1: the fixed claim gate already flagged this draft.
    refs = _gate_evidence(
        bundle, ("numeric_mismatch", "missing_evidence",
                 "uncovered_numeric", "invariant_violation")
    )
    # Over-acceptance signal 2: authorship-corpus self-preference margin (the
    # POPULATION statistic, by value — 0.0 on an all-human corpus, so silent).
    if bundle.self_preference_margin >= bundle.self_preference_threshold:
        refs.append(EvidenceRef(path="rqgm/paper_self_preference_stat.json"))
    # Over-acceptance signal 3 (amended 2026-07-17): the DIRECT per-draft anchor
    # over-acceptance, citing the anchor CASE it was measured on.
    if bundle.anchor_over_accepted_case:
        refs.append(EvidenceRef(path="paper_anchor_corpus.jsonl",
                                pointer=bundle.anchor_over_accepted_case))
    return refs
```

The `AdversarySpec` row that registers it (the eighth entry of `ADVERSARY_SPECS`):

```python
# planned: ari-core/ari/rqgm/adversarial/engine.py  ADVERSARY_SPECS += one row
"paper_self_preference": AdversarySpec(
    "paper_self_preference",
    "rqgm/adversary_paper_self_preference",
    "paper_claim",                       # reuse the existing closed target class
    _pre_paper_self_preference,
),
```

### 5.2 The in-run loop is the existing loop (proof of reuse)

The paper `AdversarialRound` is the **same class** as parent-06's (`round.py`), constructed
by the `PaperArchiveRuntime` (§[01](01_paper_execution_mode.md)) with the
`rqgm.adversarial` config slice. It runs once per completed archive draft, invoked with
`paper_candidate=True`, after the draft's `paper_reviewer` score is on the node and after
the claim-gate pre-signals are collected — exactly the parent-06 §5.3 placement, only the
"node" is a draft archive node instead of an exploration node:

```
draft archive node (scored by paper_reviewer)
  → AdversaryEngine.attack(bundle)      # runs paper_self_preference + any fired exploration types
  → RawAttackRecord (adversary_type="paper_self_preference", target: paper_claim)
  → Defender.respond                    # the draft's own defense (claims + evidence refs)
  → ArtifactJudge.adjudicate            # valid | partially_valid | invalid
  → ValidatedAttackRecord (case_type="paper_self_preference", affected_components=["paper_reviewer"])
  → apply_utility_penalty(node, ...)    # in-phase: demote the over-accepted draft
  → (epoch boundary) AdversarialReplayPool.admit(...)   # the §5.4 accumulation
```

Every arrow above is existing code. The only per-round difference the paper type
introduces is (a) the new pre-signal fires, and (b) the round emits one record per
resolvable role from `("paper_reviewer", "paper_writer")`, passing that role's
`affected_components` and the paper-specific `expected_behavior` into
`make_validated_attack_record`:

```python
# planned: ari-core/ari/rqgm/adversarial/round.py  — one case-typed expected-behavior map
_EXPECTED_BEHAVIOR_BY_TYPE = {
    "paper_self_preference": {
        "paper_reviewer": "reject AI-authored drafts whose accepted quality "
                          "exceeds the human-anchor-supported bar",
        "paper_writer":   "produce drafts whose claims are anchor-supported",
    },
}
# the seven exploration types keep the module-level generic _EXPECTED_BEHAVIOR default,
# so their ValidatedAttackRecords are byte-identical.
```

**Failure isolation, ordering, idempotency, budget** — all inherited verbatim from
`AdversarialRound` (round.py): raw attacks logged before any effect; the per-node
`rqgm_adversarial_round` marker (pool.py:139) makes the round at-most-once across resume;
the judge fail-open (`invalid` verdicts, no penalty — safe by invariant 8); the per-epoch
call cap seeded from the JSONL (round.py:100). Nothing is re-specified here.

### 5.3 The human/AI authorship corpus (the one genuinely new data dependency)

The self-preference *statistic* needs papers labeled by **authorship** (`human | ai`), so
the frozen incumbent reviewer's leniency toward AI-authored papers can be measured
deterministically against its treatment of matched human-authored papers. This is the
irreducible data cost of §5.4 — stated plainly, as [04](04_anchor_utility_and_epoch_winners.md)
states the anchor cost.

**Decision — the authorship corpus is the anchor corpus with one extra label dimension,
not a second corpus.** [04](04_anchor_utility_and_epoch_winners.md) already curates a
labeled paper set for the reviewer's accept/reject anchor. This doc requires only that
each entry *also* carry `authorship: human | ai`. Rationale: matched-quality comparison
(the self-preference margin) is only meaningful when the human and AI papers are drawn
from the same accept/reject-labeled pool; sharing the corpus makes the margin an
apples-to-apples statistic and avoids curating and versioning two datasets. A standalone
`corpus_path` override is retained for teams that want a dedicated authorship set.

> **Residual — `self_preference.corpus_path` is declared but inert (2026-07-17, work order #42).**
> The knob exists in config (`config/__init__.py` `RQGMPaperSelfPreferenceConfig`,
> `defaults.yaml`) but nothing reads it: `_attack_over_accepted` (`paper_runtime.py`) sources both
> the over-acceptance cases AND the margin population from `reviewer_anchor_cases(pool)` (04's anchor
> corpus), consuming only `enabled`/`accept_threshold`/`margin`/`sample_size`. Setting a dedicated
> authorship set therefore has no effect today — the shared-corpus default (the paragraph above) is
> the ONLY path that runs. Deferred rather than implemented because the faithful wiring requires
> factoring `load_anchor_corpus` into a `load_corpus_from(anchor_cfg, ckpt)` helper and scoping the
> override to the margin *population* only (the over-acceptance trigger must stay on the reviewer's
> anchor per wave-3c note 3); it is not a one-liner. Until it lands, treat the shared corpus as the
> supported configuration and do not rely on `corpus_path` to redirect the authorship margin.

**Minimal bootstrap (so the plan is buildable).** The AI half is free: ARI's own accepted
archive drafts from prior runs are AI-authored by construction (`authorship: ai`). The
human half is a small seed set of published, accepted human papers labeled
`authorship: human` (a handful suffices — the statistic is a mean over a held-out sample,
not a trained classifier). A run with only the AI half and no human half degrades to
"gate-finding-only" self-preference attacks (§5.1) and a bootstrap-pass on the authorship
statistic — never a failure.

**Held-out sampling (P2-safe).** Scoring rides `sample_size` (default `8`), selected by
the same deterministic content-hash sampling the anchor board uses (`hash(paper_id +
epoch_id) mod N`, engine.py:327 `deterministic_sample` precedent) — no RNG, reproducible
per epoch. The frozen incumbent's per-paper scores are cached (parent-12 caching) so the
margin is a pure function of cached results.

```yaml
# planned config (this doc owns the rqgm.paper.self_preference.* block; it mirrors the
# rqgm.paper.anchor.* pattern that 04 owns).
rqgm:
  paper:
    self_preference:
      enabled: true               # meaningful only under PAPER_RQGM_ARCHIVE
      corpus_path: ""             # "" = reuse 04's anchor corpus + its authorship labels
      sample_size: 8              # held-out papers scored per epoch (mirrors anchor.sample_size)
      accept_threshold: 0.6       # reviewer "accepted" cutoff (= CANDIDATE_PASS_THRESHOLD)
      margin: 0.1                 # self_preference_margin: AI-vs-human mean-score gap that fires
  adversarial:
    types: [overclaim, metric_gaming, prior_art, reproducibility,
            evidence_gap, cost_explosion, prompt_injection,
            paper_self_preference]        # the eighth type appended; harmless off the paper phase
    # REUSED verbatim (do not rename; cite from ari-core/ari/configs/defaults.yaml):
    max_attacks_per_node: 3               # rqgm.adversarial.max_attacks_per_node
    max_adversary_calls_per_epoch: 24     # rqgm.adversarial.max_adversary_calls_per_epoch
```

The reused governance/prompt-evolution caps (`rqgm.governance.full_governance_only_on_top_k:
3`, `rqgm.prompt_evolution.max_total_candidates_per_epoch: 4`) are inherited from
`ari-core/ari/configs/defaults.yaml` unchanged; [06](06_cost_control_and_budget.md) owns
their paper-phase interpretation.

### 5.4 Displaced-reviewer-accepted-AI-papers → replay pool (the accumulation)

At the epoch boundary the GovernanceOrchestrator's admission step (parent-06 §5.8, parent-05
step 7) calls `AdversarialReplayPool.admit(validated, epoch_id)` (pool.py:212) over the
epoch's `ValidatedAttackRecord`s. Self-preference cases (`case_type="paper_self_preference"`,
`severity ≥ pool.min_severity`) become `AdversarialReplayCase`s **through the same code
path** — the pool literally *is* "the AI papers the displaced (prior-epoch) reviewer
accepted". Dedup is `(case_type, target_artifact_hash)` (pool.py:269), so re-confirming the
same over-accepted draft updates `last_confirmed_epoch` instead of duplicating.

The pool's two views are reused with no change of contract:

- `replay_view` (pool.py:354) — the full case material the `ReplayBoard` re-runs against a
  candidate reviewer prompt: the draft refs, the attack, the defense, the judgment, and the
  `expected_behavior` (`{paper_reviewer: reject AI-authored over-acceptance}`).
- `abstract_view` (pool.py:349) — the contamination-safe `FailureSummary`
  (`build_failure_summary`, records.py:811) that clean-room reviewer regeneration
  (parent [../ari_rqgm/08](../ari_rqgm/08_clean_room_regeneration.md)) may read. It needs
  one new `_FAILURE_PATTERNS` entry (records.py:779):

```python
# planned: ari-core/ari/rqgm/adversarial/records.py  _FAILURE_PATTERNS += one entry
"paper_self_preference": (
    "reviewer accepted an AI-authored draft above the human-anchor-supported bar",
    "AI-authored drafts held to the same bar as human-anchor papers",
),
```

`affected_roles` is derived by `build_failure_summary` from the case's
`expected_behavior` keys, so it resolves to `["paper_reviewer", "paper_writer"]`
automatically — no code change (records.py:825).

**The role→`component_id` bridge (the accountability channel, and doc
[07](07_claim_gate_handoff_and_evaluation.md) §5.8's PI3 detection channel).** §5.1 showed
that the implication an attack records is *role*-shaped while every governance consumer
reads a *component*-shaped `target_component_id`. That is a **two-layer** mismatch:

| Layer | Mismatch | Owner |
|---|---|---|
| **Value space** — the generic role→component resolution | the record names a ROLE (`"paper_reviewer"`); `_reliability.py:61` wants a COMPONENT ID (`"paper_reviewer_v1"`) | parent [../ari_rqgm/15](../ari_rqgm/15_validated_attack_target_binding.md) §5.3 |
| **Value space** — *which* role a `paper_self_preference` case implicates | nothing names `paper_reviewer` as the answerable role | **this doc** (§5.4) |
| **Field** | ~~`ValidatedAttackRecord` has no `target_component_id` at all~~ — **LANDED**: parent-15 added the field, the non-empty-only emit and the optional schema property | parent [../ari_rqgm/15](../ari_rqgm/15_validated_attack_target_binding.md) (`implemented`; §10 R7) |

This doc owns one row of the answer: `paper_self_preference` implicates the
`paper_reviewer` AND `paper_writer` roles. **Deliverable:** the `_AFFECTED_ROLES_BY_TYPE` row
(`{"paper_self_preference": ("paper_reviewer", "paper_writer")}`) that parent
[../ari_rqgm/15](../ari_rqgm/15_validated_attack_target_binding.md) §5.3 reads, alongside this
doc's existing `_EXPECTED_BEHAVIOR_BY_TYPE` row. The **resolution itself is parent-15's**: it
happens in `AdversarialRound._run` via `_roles_for_node` (round.py:223) + `_resolve_bindings`
(round.py:241), with the fan-out at round.py:375–393 emitting one record per resolvable role
(the writer bound only when the draft is Layer-0-unfaithful), NOT at the
`_log_all` audit-log mirror (round.py:289–302) — patching the payload at the mirror would make
the `rqgm_audit.jsonl` copy differ from the `rqgm_adversarial_cases.jsonl` truth for the same
`record_id`, contradicting `_log_all`'s own contract (round.py:290) and the reload-equality tests
(`test_rqgm_adversarial.py:506-507`). Resolving at construction gives both sinks identical bytes.
The role is resolved against the **epoch-frozen** `_active_components()` map (round.py:131–141) —
the incumbent that actually made the decision — never a live `active_set()` read
([../ari_rqgm/15](../ari_rqgm/15_validated_attack_target_binding.md) §5.6).

Three decisions pin the shape:

1. **It belongs in ari-core, not in paper-local code** — which is why the mechanism is
   parent-15's and only the role row is this doc's. The seven exploration adversaries get the
   bridge for free. As amended on 2026-07-28, the artifact-authoring
   `generator` is registered and nodes carry write-once producer provenance,
   so the seven exploration types bind only when that provenance matches the
   epoch-frozen incumbent. Legacy or ambiguous nodes still resolve to `""`.
   Nothing here is paper-shaped except *which* role is named.
2. **It is sequenced behind parent-15 and is a safe no-op until then.** With no
   `target_component_id` field on the record, the resolution writes nowhere; doc 05's loop
   (§5.2/§5.5) does not depend on it. This doc adds no dependency edge to its header for
   that reason — but doc [07](07_claim_gate_handoff_and_evaluation.md)'s PI3 control
   assertion does, and must sequence accordingly.
3. **What closes when both land:** `_reliability.py:61` counts the incumbent reviewer's
   `validated_attack_involvement`; at `attacks >= ATTACK_THRESHOLD` (`= 2`,
   `governance/_prosecution.py:34`) `classify_target` returns `CLASSIFY_FILE`
   (`_prosecution.py:89–91`) → an Auditor impeachment motion is filed against the
   `paper_reviewer` component. This is a **control** signal, unlike the eval harness's
   offline P2 reviewer–anchor agreement metric, which is observability only.

Explicitly **not** claimed: the score route. A `reliability_score < RELIABILITY_FLOOR`
(0.4) channel additionally requires the reviewer's own records to carry `agreement` /
`confidence` / `outcome_score` (`_reliability.py`), which is
[03](03_writer_reviewer_governed_roles.md) §5.8's `review_record` work — not this doc's,
and not to be asserted as a detection channel here.

### 5.5 The next-epoch dual objective (the §5.4 remedy)

*(Title corrected 2026-07-17: was "…already implemented". The dual objective IS now
implemented — but by the paper-side `_paper_candidate_evaluator`/`_candidate_replay_board`
described below, NOT by the `CandidateValidationPipeline` this section originally cited. That
class (`prompt_evolution.py:724`) is instantiated nowhere in production for any role; its
`replay_evaluation`/`anchor_evaluation` stages and `select_for_replay` call
(`prompt_evolution.py:938`) are reachable only through `run_stage`, which nothing in
production calls.)*

At the next epoch boundary, candidate `paper_reviewer` prompts (produced by the
prompt-evolution machinery of [03](03_writer_reviewer_governed_roles.md) /
parent [../ari_rqgm/07](../ari_rqgm/07_prompt_spec_and_prompt_evolution.md)) are scored by
`PaperArchiveRuntime._paper_candidate_evaluator` (`paper_runtime.py`), whose evaluation
dicts merge into `candidate_evaluations` and ride the role-agnostic `resolve_transition`
T1→T3→T6 spine. Before scoring, a candidate whose resolved `role_instruction` dropped a
§5.4 clause is DROPPED (the constitutional gate, §5.5.1). The two boards it then computes ARE,
precisely, the §5.4 dual objective:

| Objective (RQGM §5.4) | Producer (actual, 2026-07-17) | Case source | Field | Owner of the case set |
|---|---|---|---|---|
| **Reject the AI papers you were fooled by** | `_candidate_replay_board` (`paper_runtime.py`) | `AdversarialReplayPool.select_for_replay` (`paper_self_preference` cases), re-judged by the candidate | `replay_score` | this doc |
| **Keep human-anchor accuracy** | `score_reviewer_on_anchor` (`paper_anchor.py`), `ties_favor_incumbent` at the T3 gate | [04](04_anchor_utility_and_epoch_winners.md)'s anchor cases | `anchor_score` | [04](04_anchor_utility_and_epoch_winners.md) |

A candidate `paper_reviewer` is adoptable only if it clears `CANDIDATE_PASS_THRESHOLD`
(_adjudication.py:38) on **both** boards — this is the dual constraint verbatim, computed as
`min(s for s in (replay_score, anchor_score) if s is not None) >= CANDIDATE_PASS_THRESHOLD`
in `_paper_candidate_evaluator`. A board with no basis is reported ABSENT (`None`) and never
votes pass; the T3 replay-count floor is waived by role (`no_replay_basis`) only when the
replay board is genuinely absent. Bootstrap epochs (empty pool) are that honest absence, so
the first paper reviewer is never blocked for lacking cases it could not yet have. The
incumbent-presumption ("a candidate that merely ties the incumbent on the human anchor does
not displace it") is preserved at the transition gate, not by a dead pipeline stage.

**§5.5.1 The candidate constitutional gate (wired 2026-07-17).** `_paper_candidate_evaluator`
runs `role_instruction_constraint_failures(role, resolved_text)` (`prompt_evolution.py`) over
every pending candidate and DROPS one whose instruction bytes are missing a
`REQUIRED_CONSTRAINTS_BY_ROLE` §5.4 clause — a `paper_reviewer` without "Do not override the
claim-evidence hard gate." or a `paper_writer` without its anti-fabrication clause never
enters `candidate_evaluations`, so no board score can carry it up the spine (proven by
`test_a_constitutionally_illegal_writer_candidate_never_reaches_active`). This closes the
pillar-4 hole this section previously left open (the metadata-side
`constitutional_validation_failures` is force-satisfied by `PromptMutator.propose:648`, so it
could never catch a clause dropped from the actual instruction). Still unwired: the
`static_validation` and `schema_dry_run` stages — see 03 §5.9's dated residual.

**The `no_replay_basis` / `no_shadow_basis` sentinels and the two COUNT floors (amended
2026-07-17).** This section is the authority the engine's role-scoped waiver cites for
`paper_reviewer`, so it must actually say what the code does. Recorded here, in writing,
following the plan 14 §5.5 dated-amendment convention:

* **What the sentinels are.** An evaluation with no executed case behind a board reports the
  board as ABSENT (`None`/`0`/`[]`) and DECLARES the absence, rather than padding `case_refs`
  / `shadow_samples` with synthetic entries sized to clear a floor. The declaration is a key
  on the evaluation dict; the corresponding COUNT floor is then waived at the decision site,
  in the open, with a note on the transition record naming the role and the gate
  (`transition_engine._waiver_note`). **Scoped hard by role**
  (`transition_engine.NO_REPLAY_BASIS_ROLES` = `{utility_policy, paper_writer,
  paper_reviewer}`); behavioural exploration roles are deliberately excluded so Task 09's
  live-shadow board is untouched and exploration/`simple_bfts`/`linear` resolve
  byte-identically.
* **Two floors, two declarations — they are not the same condition.**
  * `no_replay_basis` waives **T3's `replay_min_cases`**. For `paper_reviewer` it is
    declared **only when the replay board is genuinely absent** — an empty pool, or no
    applicable case re-judgeable. This is exactly the "zero-coverage pass" this section
    already sanctions above, and **nothing more**. A reviewer whose board HAS cases is
    **counted, not waived**: `case_refs` are the pool's REAL `case_id`s, so the floor has
    something honest to count. *(Declaring it unconditionally — as the first implementation
    did — permanently disabled `replay_min_cases: 4` for the role, letting a genuine 1-case
    board clear a 4-case floor. That exceeded every sanction in this plan set and is
    corrected, not blessed.)*
  * `no_shadow_basis` waives **T6's `shadow_min_samples`**. It is declared **always** for the
    paper roles, and the reason is structural rather than circumstantial: **there is no
    shadow-serving path in the paper phase**, so no paper candidate is ever shadow-EXECUTED
    and the stage is vacuous BY CONSTRUCTION — exactly the sense in which a passive
    `utility_policy` document is never shadow-executed (plan 14 §5.5 "Honest scope of the
    SHADOW stage"). No pool state can ever give this stage a sample.
  * **Why they must be separate keys.** One boolean conflated two independent facts. With a
    single sentinel scoped to the honest replay condition, a candidate with a GOOD, REAL
    replay board would clear T3 on its merits and then be retired at T4/T5 for lacking shadow
    samples no paper path can produce — while a candidate with NO board sailed through on the
    waiver. The better board loses: perverse, and the Red Queen dies quietly.
* **What the waiver never touches.** The two BOARDS still gate at
  `CANDIDATE_PASS_THRESHOLD` — a reported score always fails on its merits, waived or not
  (a reported shadow score below threshold still retires via T5). The waiver never rescues a
  failed `verdict`, and T6's `_role_opening` guard is untouched: adoption still requires a
  real sanction against the incumbent. **The waiver excuses counts and declared absences,
  never a score.**

**Boundary-reward, not in-loop reward.** The replay/anchor pass rates influence *which
candidate reviewer prompt becomes active next epoch* (a `RegistryTransitionEngine`
adoption decision, parent [../ari_rqgm/09](../ari_rqgm/09_registry_transition_engine.md)) —
never the current epoch's frontier score. This preserves the within-epoch freeze (global
invariant 7): the active `paper_reviewer` prompt hash and the utility policy are frozen for
the epoch; the dual objective bites only at the boundary, through the same
`RegistryTransitionEngine` that co-evolves every other governed role.

### 5.6 What is new vs what is reused (the bright-spot ledger)

| Concern | Status | Where |
|---|---|---|
| `paper_self_preference` type string | **NEW** (one entry) | `ADVERSARY_TYPES` records.py:43 |
| `_pre_paper_self_preference` pre-signal | **NEW** (one function) | engine.py, §5.1 |
| `ADVERSARY_SPECS` row | **NEW** (one row) | engine.py:463 |
| adversary prompt template | **NEW** (one `.md`) | `ari-core/ari/prompts/rqgm/adversary_paper_self_preference.md` |
| `_FAILURE_PATTERNS` entry | **NEW** (one entry) | records.py:779 |
| case-typed `_EXPECTED_BEHAVIOR` entry | **NEW** (one entry) | round.py:42 |
| `ArtifactBundle` paper fields | **NEW** (optional, fail-safe defaults) | engine.py:133 |
| **founding prompt row** (paper-mode-gated) | **NEW** (one row) | `FOUNDING_PROMPT_TABLE` prompt_spec.py:153 |
| **founding component row** (paper-mode-gated) | **NEW** (one row) | `FOUNDING_COMPONENT_TABLE` prompt_spec.py:232 |
| `_AFFECTED_ROLES_BY_TYPE` entry (the bridge's paper row) | **NEW** (one entry) | round.py:42, §5.4; table + resolution owned by [../ari_rqgm/15](../ari_rqgm/15_validated_attack_target_binding.md) §5.3 |
| human/AI authorship corpus + `rqgm.paper.self_preference.*` | **NEW** (data + config) | §5.3 |
| `RawAttackRecord`/`DefenderResponse`/`JudgmentRecord`/`ValidatedAttackRecord`/`UtilityRecord`/`AdversarialReplayCase` schemas | REUSED | records.py |
| `AdversaryEngine`/`Defender`/`ArtifactJudge`/`apply_utility_penalty`/`should_attack`/`build_artifact_bundle`/`AdversarialRound` | REUSED | engine.py, round.py |
| `AdversarialReplayPool` admit/evict/views/persistence (the WRITE side) | REUSED | pool.py |
| `AdversarialReplayPool.select_for_replay` (the READ side) | **NEW use** — was a write-only sink in paper mode; `_candidate_replay_board` is its first paper reader (2026-07-17) | pool.py, paper_runtime.py |
| the §5.4 dual-objective boards (reject-AI + keep-anchor) | ~~`CandidateValidationPipeline.replay_evaluation`/`anchor_evaluation`~~ **NEW** (2026-07-17): `_candidate_replay_board` + `score_reviewer_on_anchor` in `_paper_candidate_evaluator`; the pipeline class is dead in production | paper_runtime.py, paper_anchor.py |
| candidate constitutional DROP (§5.4 clauses) | **NEW** (2026-07-17): `role_instruction_constraint_failures` wired into `_paper_candidate_evaluator` | prompt_evolution.py, paper_runtime.py |
| `CANDIDATE_PASS_THRESHOLD`, `resolve_transition` T1/T3/T6 spine | REUSED | governance/_adjudication.py, transition_engine.py |
| kernel checks, invariants 8/9, penalty channel, selective erasure, budget, checkpoint files | REUSED | parent-06 |

The additive edits + one corpus + the NEW dual-objective read boards, candidate evaluator,
and constitutional gate (the last three added 2026-07-17, previously mis-attributed to the
never-instantiated `CandidateValidationPipeline`).

**The two founding rows (the eighth adversary joins the audit network).** All seven
existing adversaries are founding prompts *and* founding components
(`adversary_cost_explosion_prompt_v1 … adversary_reproducibility_prompt_v1`,
prompt_spec.py:184–199; `adversary_cost_explosion_v1 … adversary_reproducibility_v1`,
prompt_spec.py:233–247). Nothing auto-registers an eighth
(`ari-core/tests/test_rqgm_founding_bootstrap.py:76–78` asserts the registry's prompt/
component id sets equal the founding tables **exactly**), so without these two rows the
adversary this doc introduces would be the only member of its family outside registry
governance:

```python
# planned: ari-core/ari/rqgm/prompt_spec.py  (FOUNDING_PROMPT_TABLE, prompt_spec.py:153)
# Inserted ALPHABETICALLY inside the adversary block — between
# adversary_overclaim_prompt_v1 (:184) and adversary_prior_art_prompt_v1 (:186) — so the
# family's alphabetically-last member, adversary_reproducibility_prompt_v1, remains the
# role rollup winner and epoch.active_prompt_hashes["adversary"] is unperturbed.
("adversary_paper_self_preference_prompt_v1", "rqgm/adversary_paper_self_preference",
 "adversary", True, {"__reply__": "json_object", "attack_claim": "string"}),

# planned: ari-core/ari/rqgm/prompt_spec.py  (FOUNDING_COMPONENT_TABLE, prompt_spec.py:232)
# Sorted by component_id — between adversary_overclaim_v1 (:239) and
# adversary_prior_art_v1 (:241); the adversary family still rolls up to its
# alphabetically-last member (that table's own docstring, prompt_spec.py:230–231).
("adversary_paper_self_preference_v1", "adversary", "institutional",
 "adversary_paper_self_preference_prompt_v1", {}),
```

**Bootstrap-gated on effective `PAPER_RQGM_ARCHIVE`**, riding
[03](03_writer_reviewer_governed_roles.md) §5.5's gating seam verbatim (the same
`founding_registration_events()` (prompt_spec.py:407) path, which runs only inside the
`PaperArchiveRuntime` doc [01](01_paper_execution_mode.md) constructs). This is **required**
by §8.1/§8.2, not decoration: unconditional rows would register on every `ari_rqgm`
exploration boot, churn `registry_version` and the `epoch_000` `epoch_fingerprint`, and
break this doc's own seven-adversaries-byte-identical regression (§9). `CONSTITUTION_HASH`
is untouched (§3).

**Why these rows — state the payoff correctly.** The payoff is **registry governance and
sanctionability, NOT prompt evolvability.** Adversary prompt evolution is *role*-scoped:
`_active_evolvable_incumbents` (runtime.py:676–724) keeps exactly **one** incumbent per
role (`latest[entry.role] = entry`, runtime.py:694), and `AdversaryEngine` loads each
adversary by its **committed spec key** (`spec.prompt_key` → `_load_prompt` →
`load_versioned`, engine.py:661–672, :545–551). So this row does **not** make the eighth
adversary's prompt mutate — and is not meant to. Six of its seven registered siblings do not
mutate either; they are registered anyway. What the rows buy, and what their absence
uniquely costs, is:

1. **Sanctionability.** `AdversaryEngine` stamps
   `component_id=self._component_id("adversary", f"adversary_{spec.adversary_type}_v1")`
   (engine.py:738–740). The family guard `_component_id` (engine.py:520–541) falls back to
   that ad-hoc id whenever the role rollup winner belongs to another family — which is
   exactly this type's situation — so unregistered records would carry the id
   `adversary_paper_self_preference_v1` while the registry has no such entry. Then
   `resolve_transition` (transition_engine.py:414) does `entry = comps.get(component_id)`
   (:669) and `rejected.append(f"unknown component {component_id!r}")` (:692) — **no
   warning, no probation, no quarantine, and not even the T16 constitutional emergency
   could land on it.** With the row, every sanction edge the seven ride (T9–T19, keyed by
   `(from_status, to_status)`, never by role) reaches it too.
2. **Governed prompt bytes.** `GovernedPromptLoader` governs the key, restoring the
   frozen-spec hash refusal (prompt_loader.py:151–158 — "never serve bytes that no longer
   match the frozen spec identity") that ungoverned keys skip by byte-identical delegation
   (prompt_loader.py:127–130).
3. **No GAP-3 regression.** `test_rqgm_prompt_spec.py:111–117` pins the founding table as
   *exactly* the governed committed inventory ("previously those ran on ad-hoc ids outside
   registry governance"); a committed, runtime-loaded RQGM template with no founding row
   would reopen that gap by construction.

This is P3 in its literal form: the adversary is itself inside the audit network, holding
no authority the seven lack and enjoying no immunity they lack.

## 6. Data structures / schema changes

**No new record schemas.** Self-preference attacks reuse the parent-06 §6 shapes
(`ari-core/ari/schemas/rqgm_attack_records.schema.json`,
`rqgm_replay_pool.schema.json`). The only schema-adjacent change is that the closed
`adversary_type` / `case_type` enumeration gains `paper_self_preference` — an *additive*
member of `ADVERSARY_TYPES` (records.py:43). `raw_attack_violations` (records.py:267) and
`validated_attack_violations` (records.py:579) accept it automatically because they check
membership in that tuple; the record JSON layout is unchanged.

This is also why §5.4's bridge does **not** add a field here: `target_component_id` on
`ValidatedAttackRecord` is parent-owned
([../ari_rqgm/15](../ari_rqgm/15_validated_attack_target_binding.md), §10 R7) precisely
because an unconditional emit would change the layout of every record the seven types
already write, contradicting this section and the §8.3 byte-identity guarantee. This doc
contributes only the *value* the parent's field will carry for `paper_self_preference`
cases (§5.4).

**`ArtifactBundle` additive optional fields** (engine.py:133), read only in
`PAPER_RQGM_ARCHIVE`, with fail-safe defaults so the seven exploration adversaries and all
existing bundle callers are unaffected:

```python
# planned additions to ari-core/ari/rqgm/adversarial/engine.py::ArtifactBundle
paper_candidate: bool = False            # True only for archive draft nodes
reviewer_accept_score: float | None = None   # paper_reviewer score; None == not paper-scored (never fires)
accept_threshold: float = 0.6            # from rqgm.paper.self_preference.accept_threshold
self_preference_margin: float = 0.0      # computed AI-vs-human mean gap (0.0 == no corpus / no gap)
self_preference_threshold: float = 0.1   # from rqgm.paper.self_preference.margin
```

`build_artifact_bundle` (engine.py:266) gains one paper-phase population block, guarded so
that under `linear` and for exploration nodes the block is never entered and the bundle is
byte-identical to today's.

**Self-preference statistic artifact.** The deterministic margin computation writes an
audit artifact `{ckpt}/rqgm/paper_self_preference_stat.json` (byte-fixed formatting, the
`adversarial_replay_pool.json` snapshot precedent) recording, per epoch: the held-out
sample paper ids, the incumbent reviewer's per-paper cached scores, the human/AI means, and
the resulting margin. It is the checkpoint-resolvable `attack_evidence_ref` the pre-signal
cites (§5.1). It lives under the already-registered `{ckpt}/rqgm/` snapshot dir
(pool.py:46 `RQGM_SNAPSHOT_DIRNAME`); its filename is added to
`PathManager.META_FILES` (`ari-core/ari/paths.py`, alongside line 456) and to
`_INTERNAL_JSON_NAMES` (`ari-core/ari/orchestrator/node_report/builder.py`) — the only new
filename this doc registers.

**Pool `abstract_view`**: one new `_FAILURE_PATTERNS` entry (§5.4); the
`AdversarialReplayCase` shape (records.py:829) is unchanged.

## 7. API / class changes

All additions live in the existing internal package `ari-core/ari/rqgm/adversarial/` (kept
out of `ari.public.*` — no public-API contract snapshot churn):

| Symbol | Location (planned) | Contract |
|---|---|---|
| `_pre_paper_self_preference(bundle) -> list[EvidenceRef]` | `ari/rqgm/adversarial/engine.py` | Deterministic, LLM-free (§5.1); `[]` off the paper phase, for un-accepted drafts, and with no over-acceptance signal. |
| `ADVERSARY_SPECS["paper_self_preference"]` | `ari/rqgm/adversarial/engine.py` | `AdversarySpec("paper_self_preference", "rqgm/adversary_paper_self_preference", "paper_claim", _pre_paper_self_preference)`. |
| `"paper_self_preference"` ∈ `ADVERSARY_TYPES` | `ari/rqgm/adversarial/records.py` | Additive closed-set member; also the `case_type`. |
| `_FAILURE_PATTERNS["paper_self_preference"]` | `ari/rqgm/adversarial/records.py` | `(failure_pattern, violated_expectation)` for the contamination-safe abstract view. |
| `_EXPECTED_BEHAVIOR_BY_TYPE["paper_self_preference"]` | `ari/rqgm/adversarial/round.py` | Names `paper_reviewer` / `paper_writer` as affected roles; seven types keep the generic default. |
| `ArtifactBundle.paper_candidate / reviewer_accept_score / accept_threshold / self_preference_margin / self_preference_threshold` | `ari/rqgm/adversarial/engine.py` | Additive optional fields, fail-safe defaults (§6). |
| `compute_self_preference_margin(reviewer, corpus, sample_size, epoch_id) -> float` | `ari/rqgm/paper_self_preference.py` (new small module) | Pure over cached incumbent scores; deterministic held-out sample; writes `paper_self_preference_stat.json`; `0.0` when no corpus. |
| `adversary_paper_self_preference.md` | `ari/prompts/rqgm/` | Committed v1 template (parent-06 §7 posture); registered in the four snapshot layers. |
| `FOUNDING_PROMPT_TABLE += ("adversary_paper_self_preference_prompt_v1", …)` | `ari/rqgm/prompt_spec.py:153` | **NEW** row, alphabetical inside the adversary block (`overclaim` < `paper_self_preference` < `prior_art`), `role="adversary"`, `evolvable=True`, `{"__reply__": "json_object", "attack_claim": "string"}` — identical `(role, tier, evolvable)` posture to the seven. Registered only under effective `PAPER_RQGM_ARCHIVE` (§5.6). Rollup winner unchanged (`adversary_reproducibility_prompt_v1`). |
| `FOUNDING_COMPONENT_TABLE += ("adversary_paper_self_preference_v1", …)` | `ari/rqgm/prompt_spec.py:232` | **NEW** row, sorted by `component_id`; `("adversary", "institutional", "adversary_paper_self_preference_prompt_v1", {})`. Makes the id the engine already stamps (engine.py:738–740) resolvable by `resolve_transition` (transition_engine.py:669) instead of `unknown component` (:692). Paper-mode-gated. |
| `_AFFECTED_ROLES_BY_TYPE["paper_self_preference"] = ("paper_reviewer", "paper_writer")` | `ari/rqgm/adversarial/round.py:98` | **NEW** row only. Parent [../ari_rqgm/15](../ari_rqgm/15_validated_attack_target_binding.md) §5.3 owns the field; resolution runs via `_roles_for_node` (round.py:223) + `_resolve_bindings` (round.py:241) against the epoch-frozen `_active_components()` map (round.py:131–141), with the fan-out at round.py:375–393 emitting one `target_component_id`-bound record per resolvable role (the writer bound only when the draft is Layer-0-unfaithful). LANDED (2026-07-17). The seven exploration adversaries share the mechanism but bind no target (no registered `generator` component — parent-15 §5.4, R2). |

Wiring (all additive, all gated on `PAPER_RQGM_ARCHIVE`; no change under `linear`):

- The `PaperArchiveRuntime` (§[01](01_paper_execution_mode.md)) constructs the paper
  `AdversarialRound` with the `rqgm.adversarial` slice and drives one round per completed
  archive draft with `paper_candidate=True`. No new run entry point — it hangs off the
  existing `projects.py:163` `getattr(_bfts_paper, "rqgm", None)` discovery.
- The GovernanceOrchestrator's admission step (parent-05 step 7) admits self-preference
  cases with no change (same `pool.admit`).
- No CLI command/flag change, no new MCP tool, no `ari.public.*` change ⇒ **zero contract
  golden regeneration** for this task.

## 8. Migration / compatibility

Preserve-existing-behavior policy (normative):

1. **`linear` is identity.** Under `paper.mode: linear` (default) — and under
   `simple_bfts` exploration regardless of paper mode — no self-preference component is
   constructed, no corpus is loaded, **neither founding row is registered**, and
   `paper_self_preference_stat.json` is never written. The paper pipeline is byte-identical
   to today's (global invariant 1).
2. **The seven exploration adversaries are byte-identical.** `paper_self_preference`'s
   pre-signal returns `[]` for every non-paper node (`paper_candidate=False`), so it never
   fires during exploration; the module-level `_EXPECTED_BEHAVIOR` default is unchanged for
   them; the `ArtifactBundle` additions default to fail-safe values that never trigger. The
   §5.6 founding rows are **bootstrap-gated on effective `PAPER_RQGM_ARCHIVE`** ([03](03_writer_reviewer_governed_roles.md)
   §5.5's seam), so an exploration boot registers the same set it does today: unchanged
   `registry_version`, unchanged `epoch_000` `epoch_fingerprint`, and — because the row sits
   alphabetically before `adversary_reproducibility_*` — an unchanged adversary rollup
   winner even when it *is* registered. A regression test pins that an `ari_rqgm`
   exploration run with the eighth type present in `rqgm.adversarial.types` produces a
   byte-identical checkpoint to one without it (§9).
3. **Additive record vocabulary only.** `ADVERSARY_TYPES` / `_FAILURE_PATTERNS` gain one
   member each; no field is renamed or re-typed; the record JSON layout is unchanged. Old
   checkpoints replay unchanged; a stored self-preference case round-trips through
   `case_from_dict` (records.py:864) exactly like the seven types.
4. **Corpus-absent degradation is safe.** With no authorship corpus, the self-preference
   statistic is `0.0`, the second over-acceptance signal is absent, and the type degrades to
   gate-finding-only attacks or to no attacks — never an error (mirrors the web-less
   `PriorArtAdversary`). All tests pass without a corpus and without VirSci.
5. **Resume.** Self-preference cases ride the already-checkpoint-scoped
   `rqgm_adversarial_cases.jsonl` + `adversarial_replay_pool.json`; the per-node round
   marker (pool.py:127) prevents double-attacking a draft after resume; penalties are baked
   into the persisted draft `_scientific_score`. `paper_self_preference_stat.json` is
   epoch-derived and recomputed deterministically on resume.
6. **P2/P5.** The pre-signal, the margin statistic, admission, board scoring, and the
   penalty arithmetic are deterministic. The three LLM steps (attack / defense /
   adjudication) are audit-logged with prompt hashes via `record_prompt_use`. No network,
   no wall-clock in any hash.
7. **Within-epoch freeze (global invariant 7).** The active `paper_reviewer` prompt hash
   and the utility policy are frozen per epoch; the dual objective changes the reviewer only
   at the boundary, through `RegistryTransitionEngine`.

## 9. Tests

Unit (new `ari-core/tests/test_paper_self_preference.py`, listed in
`ari-core/tests/README.md` for the readme-sync gate):

- `_pre_paper_self_preference`: `[]` when not a paper candidate; `[]` when
  `reviewer_accept_score is None`; `[]` below `accept_threshold`; gate-finding evidence when
  a hard-gate finding is present; corpus-margin evidence when `margin ≥ threshold`; empty
  corpus + no gate finding → `[]` (zero LLM cost).
- `compute_self_preference_margin`: deterministic over cached scores; `0.0` on empty/AI-only
  corpus; held-out sample is content-hash-stable per epoch; writes a byte-fixed
  `paper_self_preference_stat.json`.
- Record vocabulary: a `RawAttackRecord`/`ValidatedAttackRecord` with
  `adversary_type`/`case_type = "paper_self_preference"` passes `raw_attack_violations` /
  `validated_attack_violations`; `_FAILURE_PATTERNS["paper_self_preference"]` yields a
  `FailureSummary` with `affected_roles == ["paper_reviewer", "paper_writer"]` and **no** raw
  attack/defense text (contamination check).
- Pool: a self-preference `ValidatedAttackRecord` is admitted (`case_type` respected),
  dedups by `(case_type, target_artifact_hash)`, and its `replay_view` is denied to
  `actor_role="clean_room_generator"` (parent-06 §5.7 check 7, reused).
- Record layout unchanged: a `paper_self_preference` `ValidatedAttackRecord`'s `to_dict()`
  key set is identical to a seven-type record's (no `target_component_id` key added here —
  §6), keeping the §8.3 byte-identity guarantee true.

**The adversary is itself in the audit network (P3)** — the tests that would have caught
the §5.6 gap:

- **Registered.** After a paper bootstrap (`PaperArchiveRuntime`, effective
  `rqgm_archive`), `build_founding_specs()` (prompt_spec.py:326) includes
  `adversary_paper_self_preference_prompt_v1` with `status="active"`, `evolvable=True`, and
  `prompt_hash == load_versioned("rqgm/adversary_paper_self_preference")[1]`; and
  `founding_component_payloads()` (prompt_spec.py:383) includes
  `adversary_paper_self_preference_v1` (`role="adversary"`, tier `institutional`). Follows
  the [03](03_writer_reviewer_governed_roles.md) §9 gated-bootstrap precedent — do **not**
  extend `test_rqgm_founding_bootstrap.py:76–78`, whose exploration-boot equality must keep
  excluding the paper-gated rows (that exclusion *is* §8.2's guarantee).
- **Parity, not privilege.** A table-level parity check over the adversary family: the
  eighth row carries the same `(role, tier, evolvable)` triple as the seven, so it inherits
  exactly their evolution posture (role-level breeding through the rollup incumbent) — no
  more and no less. Asserted as a family invariant, not as "the eighth prompt mutates":
  `_active_evolvable_incumbents` (runtime.py:676–724) admits one incumbent per role.
- **Rollup unperturbed.** The adversary role's rollup winner is
  `adversary_reproducibility_prompt_v1` both with and without the row (alphabetical
  placement, §5.6), so `epoch.active_prompt_hashes["adversary"]` is unchanged.
- **Sanctionable (the load-bearing one).** The `component_id` the engine stamps for
  `paper_self_preference` (the engine.py:738–740 / :520–541 fallback id) resolves to a
  registered registry entry after paper bootstrap: a governance recommendation targeting it
  is resolved by `resolve_transition` into a T9/T10/T11 sanction rather than silently
  dropped, and `resolve_emergency_quarantine` against it is **not** rejected as
  `unknown component` (transition_engine.py:692). One assertion each — the full T9–T19
  matrix is parent [../ari_rqgm/09](../ari_rqgm/09_registry_transition_engine.md)'s
  topology-agnostic inherited coverage.
- **Governed bytes.** `GovernedPromptLoader` raises on tampered
  `rqgm/adversary_paper_self_preference.md` bytes (the frozen-spec refusal,
  prompt_loader.py:151–158) — the check an ungoverned key skips.
- Extend `test_rqgm_prompt_spec.py`'s hardcoded governed-inventory list (:111–117) with the
  new key.

Regression (exploration + linear unchanged):

- **Seven-adversaries-byte-identical**: an `ari_rqgm` exploration smoke run with
  `paper_self_preference` present in `rqgm.adversarial.types` produces a checkpoint triple
  byte-identical to one with the seven-type list — the eighth type never fires off the paper
  phase.
- **`linear` smoke**: `paper.mode: linear` run creates no `rqgm/paper_self_preference_stat.json`,
  no self-preference prompt in `prompt_trace.jsonl`, and a byte-identical manuscript to
  today's linear pipeline.
- New filename `paper_self_preference_stat.json` present in `META_FILES` and
  `_INTERNAL_JSON_NAMES`; node work dirs / `files_changed` uncontaminated (extend the paths
  test).
- Prompt snapshot layers: `adversary_paper_self_preference.md` blessed in
  `test_prompt_snapshots.py`, `_EXPECTED_HASHES`, `_EXPECTED_KEYS`, and the registry
  expected-key test.

Smoke (the §5.4 loop end-to-end, stubbed LLMs returning canned JSON):

- One over-accepted archive draft → self-preference attack → defense → `valid` judgment →
  `ValidatedAttackRecord` → `apply_utility_penalty` demotes the draft's `_scientific_score`
  → the demoted draft is no longer the best-belief selection handed to the claim gate
  (§[02](02_paper_draft_archive_search.md) selection recomputed).
- Epoch-boundary admission → the case is a `paper_self_preference` pool entry.
- Next-epoch dual objective *(mechanism corrected 2026-07-17: the boards are
  `_candidate_replay_board` + `score_reviewer_on_anchor`, not the dead `replay_evaluation`/
  `anchor_evaluation` stages)*: a candidate `paper_reviewer` prompt that flags the pooled AI
  paper clears the replay board (`test_the_replay_board_reads_the_pool_and_the_two_boards_vary_apart`);
  one that also matches the human anchor clears the anchor board; a candidate passing replay but
  failing anchor is **not** adopted, and one passing anchor but failing replay is **not** adopted —
  both boards required, both directions pinned
  (`test_a_candidate_passing_replay_but_failing_anchor_is_not_adopted` +
  `test_a_candidate_failing_EITHER_board_is_not_adoptable`). A candidate whose resolved
  `role_instruction` dropped a §5.4 clause is DROPPED before scoring (§5.5.1,
  `test_a_constitutionally_illegal_writer_candidate_never_reaches_active`).

Resume:

- Round idempotency marker honored across a simulated resume (no double attack on the same
  draft); pool reload equals pre-crash state; the margin statistic recomputes to the same
  value.

CI placement: plain ari-core tests under `refactor-guards.yml`; no new workflow.

## 10. Risks

- **R1 — Authorship-corpus availability.** The human half is a real (if small) data cost;
  without it the self-preference statistic is inert. Mitigation: the AI half is free
  (ARI's own accepted drafts); the type degrades to gate-finding-only over-acceptance
  attacks with no human corpus (§5.1); the plan is buildable at every corpus size, and the
  bright-spot claim does not depend on corpus richness.
- **R2 — Self-preference vs anchor over-fit (the §5.4 tension).** Optimizing the reviewer to
  reject AI papers could depress its human-anchor accuracy. This is exactly why the objective
  is *dual*: a candidate must clear **both** boards, and `ties_favor_incumbent` blocks
  anchor-regressing candidates (§5.5). [07](07_claim_gate_handoff_and_evaluation.md)'s
  ablation measures the joint metric.
- **R3 — The reviewer is also the accept/reject anchor scorer** (its base utility, [04](04_anchor_utility_and_epoch_winners.md)),
  so a self-preference penalty and an anchor-disagreement penalty could double-count on one
  draft. Mitigation: the in-phase penalty is the epoch-frozen `UtilityPenaltyPolicy` with a
  `penalty_cap` (engine.py:918), and `partially_valid` is half-weight; the two channels are
  distinguished by `case_type` in the `UtilityRecord.input_refs` for [../ari_rqgm/10](../ari_rqgm/10_frontier_repair_and_selective_erasure.md)'s recompute.
- **R4 — Judge leniency mirrors reviewer leniency.** If the `ArtifactJudge` shares the
  reviewer's self-preference bias, self-preference attacks never validate. Mitigation: the
  Judge is a distinct evolving role with its own prompt (parent-06 §5.1), audited by parent-05
  GovernanceSelfAudit; [07](07_claim_gate_handoff_and_evaluation.md)'s failure-injection
  suite measures validated-self-preference precision. Accepted residual: a fully-captured
  judge degrades the loop to plain best-of-N — safe (no false penalties), just less effective.
- **R5 — Over-acceptance signal is a proxy.** The margin statistic is a population signal,
  not per-draft proof of self-preference. Mitigation: the pre-signal only *triggers* the LLM
  adversary, which must produce an evidence-cited attack that survives the Defender and Judge
  before any effect (invariant 8); the margin alone never touches a score.
- **R6 — Corpus contamination / injection.** A malicious human-labeled paper could carry an
  injection payload into the reviewer's context during scoring. Mitigation: authorship-corpus
  papers are scored through the same `paper_reviewer` context view whose whitelist the kernel
  enforces ([03](03_writer_reviewer_governed_roles.md)); the `PromptInjectionAdversary`
  (parent-06) already scans quoted text.
- **R7 (RESOLVED by parent task 15 — the field layer has landed) — the validated-attack →
  impeachment chain was dead UPSTREAM, for the seven exploration adversaries too.**
  [../ari_rqgm/15](../ari_rqgm/15_validated_attack_target_binding.md) is now `implemented`:
  `ValidatedAttackRecord` carries `target_component_id`, `to_dict` emits it **only when
  non-empty** (so every pre-existing record stays byte-identical),
  `ari/schemas/rqgm_attack_records.schema.json` declares it as an optional property on the
  `validated_attack` branch, and the ROLE → epoch-frozen `component_id` resolution runs at
  record construction (`round.py`). The full chain is proven in tests through to a T10 registry
  sanction. **This doc's table row (LANDED)** —
  `_AFFECTED_ROLES_BY_TYPE["paper_self_preference"] = ("paper_reviewer", "paper_writer")` (§5.4) — plus its
  `_EXPECTED_BEHAVIOR` rows; that row is what first makes the chain fire in production, because
  `paper_reviewer_v1` is a registered founding component whereas the seven's `generator` is not
  (parent-15 §5.4, R2). Note parent-15 §10 R3: a row must never name a role that rolls up to the
  judgment's own author (`judge` → `artifact_judge_v1`); the producer pre-filters that case and
  drops the binding, keeping the record.

  The historical diagnosis, retained because it is the reason the defect survived CI:
  `_reliability.py:37–39` documents `validated_attack_involvement` as counting
  `ValidatedAttackRecord`s whose `target_component_id` matches the component — but the sole
  producer never emitted that key (`to_dict` emitted `affected_components` and
  `target_artifact_hash` instead), and the schema did not declare it.
  `attacks_by_target` (`_reliability.py:60–66`) was therefore always empty,
  `validated_attack_involvement` is structurally `0`, and the `ATTACK_THRESHOLD` route in
  `classify_target` (`_prosecution.py:34`, `:89–91`) can never fire — for **any** adversary
  type. `test_rqgm_governance.py:100–107` exercises it only with hand-built dicts, which is
  why CI is green over a dead chain. **This is a pre-existing parent-level defect and NOT
  paper-specific**: the parent's own harness appends `validated.to_dict()` with no target
  (`ari-core/ari/rqgm/evaluation/smoke.py:212–214`), and parent
  [../ari_rqgm/05](../ari_rqgm/05_governance_orchestrator.md):183 states the intent
  ("≥N high-severity validated attacks affecting a component") its :297 fixture already
  mocks. Filed as the new parent task
  [../ari_rqgm/15](../ari_rqgm/15_validated_attack_target_binding.md) (against parent-05 +
  parent-06, which owns `records.py`) — **not** fixed here, and not silently assumed:
  §3 and §5.1 now claim no prosecution path from the record. The correct shape for the
  parent is `target_component_id: str = ""` on `ValidatedAttackRecord`, emitted by
  `to_dict` **only when non-empty** — an unconditional emit would add
  `"target_component_id": ""` to every existing record and break the §6/§8.3/§9
  byte-identity guarantee. That parent task also owns the role→component resolution, at
  record construction rather than at the audit-log mirror (parent-15 §5.3); paper mode then
  binds a target through §5.4's role row at no further cost to this doc. Exploration mode
  inherits the mechanism, but binds nothing until an artifact-authoring role has a registered
  incumbent (parent-15 §5.4, R2).

## 11. Completion criteria

This task is complete when all of the following hold:

1. **The `paper_self_preference` adversary is fully specified** — target class (reused
   `paper_claim`), the deterministic `_pre_paper_self_preference` pre-signal with its three
   trigger clauses and corpus-absent degradation, the `ADVERSARY_SPECS` row, and the one
   prompt template — precisely enough that implementation needs no further design (§5.1).
2. **The §5.4 accumulation is mapped to reused machinery** — displaced-reviewer-accepted-AI
   papers become `AdversarialReplayPool` entries with `case_type="paper_self_preference"`
   through the existing `admit`, with one `_FAILURE_PATTERNS` entry; no new pool, view, or
   persistence file (beyond the one statistic artifact) is introduced (§5.4).
3. **The next-epoch dual objective is mapped to reused stages** — reject-AI via
   `replay_evaluation`, keep-anchor via `anchor_evaluation`, both required at
   `CANDIDATE_PASS_THRESHOLD`, `ties_favor_incumbent` honored, boundary-reward only (§5.5).
4. **The human/AI authorship corpus is specified with its data cost and a minimal
   bootstrap** — reuse of [04](04_anchor_utility_and_epoch_winners.md)'s corpus with an
   authorship label, AI-half-free bootstrap, held-out deterministic sampling, and the
   `rqgm.paper.self_preference.*` config home (§5.3).
5. **The reuse ledger is stated** — every reused symbol (engine/round/pool/records/
   prompt_evolution/_adjudication) is named, and the exact NEW deltas are enumerated (§5.6),
   substantiating the bright-spot claim.
6. **Compatibility is nailed down** — `linear` identity, seven-adversaries byte-identity,
   additive-only vocabulary, corpus-absent safety, resume, P2/P5, within-epoch freeze (§8).
7. **The eighth adversary is embedded in the audit network on the same terms as the seven**
   — it is a founding prompt **and** a founding component (paper-mode-gated, §5.6), carries
   the same `(role, tier, evolvable)` posture, and is sanctionable **through the registry**
   rather than resolving to an unregistered ad-hoc id that `resolve_transition` drops as
   `unknown component`. It holds no authority the seven lack and enjoys no immunity they
   lack; the rollup winner, `registry_version`, and `CONSTITUTION_HASH` are unperturbed.
8. **The accountability claim is true as written** — this doc claims the two channels it
   actually has (in-phase draft penalty; boundary dual objective → prompt replacement), does
   **not** claim governance routing from `affected_components`, and contributes the bridge's
   paper row (§5.4) so that doc [07](07_claim_gate_handoff_and_evaluation.md)
   §5.8's PI3 has a real channel once parent
   [../ari_rqgm/15](../ari_rqgm/15_validated_attack_target_binding.md) lands the field and the
   resolution (§10 R7).
9. Downstream tasks can consume this plan without re-opening it: [06](06_cost_control_and_budget.md)
   (the reused caps + the one statistic call), [07](07_claim_gate_handoff_and_evaluation.md)
   (the self-preference detection + dual-objective metrics), parent
   [../ari_rqgm/07](../ari_rqgm/07_prompt_spec_and_prompt_evolution.md) (the replay cases it
   already consumes).

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

Task-specific criteria (all additionally required):

- The `paper_self_preference` adversary type (pre-signal, `ADVERSARY_SPECS` row, prompt
  template, `_FAILURE_PATTERNS` entry) is implemented and dispatchable.
- The two paper-mode-gated founding rows are merged and the eighth adversary is a
  registered, sanctionable governed component exactly like the seven (§5.6, §9).
- §10 R7 is not left dangling: parent
  [../ari_rqgm/15](../ari_rqgm/15_validated_attack_target_binding.md) has either landed
  `target_component_id` and its resolution (in which case §5.4's role row binds and doc
  [07](07_claim_gate_handoff_and_evaluation.md) PI3's motion assertion passes) or the open
  question has been restated in a surviving plan file.
- The human/AI authorship corpus loader + `compute_self_preference_margin` +
  `paper_self_preference_stat.json` are implemented, with the corpus-absent degradation
  path.
- The seven-adversaries-byte-identical regression test and the `linear`-identity smoke test
  pass in CI.
- The §5.4 end-to-end smoke (attack → penalty demotion → pool admission → next-epoch
  dual-objective adoption/rejection) passes.
- `paper_self_preference_stat.json` is registered in `PathManager.META_FILES` and
  node-report `_INTERNAL_JSON_NAMES`.
- The self-preference design (dual objective, corpus label dimension) has been moved to the
  permanent paper-archive co-evolution guide under `docs/`.

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

- [ ] `paper_self_preference` added to `ADVERSARY_TYPES` / `ADVERSARY_SPECS` /
      `_FAILURE_PATTERNS` and dispatched by `AdversaryEngine.attack`.
- [ ] `adversary_paper_self_preference.md` committed and blessed in all four prompt-snapshot
      layers.
- [ ] `adversary_paper_self_preference_prompt_v1` + `adversary_paper_self_preference_v1`
      added to `FOUNDING_PROMPT_TABLE` / `FOUNDING_COMPONENT_TABLE` in alphabetical/id order,
      gated on effective `PAPER_RQGM_ARCHIVE`; the eighth adversary is warn/probation/
      quarantine-reachable through `resolve_transition` (no `unknown component`), and the
      adversary rollup winner + exploration `epoch_000` `registry_version` are unchanged.
- [ ] §5.4's `_AFFECTED_ROLES_BY_TYPE` row (`paper_self_preference` → `paper_reviewer`)
      landed, and §10 R7 filed against parent
      [../ari_rqgm/15](../ari_rqgm/15_validated_attack_target_binding.md), which owns the
      resolution at record construction (no `target_component_id` field and no resolution
      code are added by this task).
- [ ] Human/AI authorship corpus + `rqgm.paper.self_preference.*` config + margin statistic
      implemented, with the corpus-absent fallback.
- [ ] `ArtifactBundle` paper fields added with fail-safe defaults; seven exploration
      adversaries confirmed byte-identical.
- [ ] Displaced-reviewer-accepted-AI-papers admitted to `AdversarialReplayPool` as
      `paper_self_preference` cases.
- [ ] Next-epoch dual objective (reject-AI `replay_evaluation` + keep-anchor
      `anchor_evaluation`, both required) verified end-to-end.
- [ ] `paper_self_preference_stat.json` registered in `META_FILES` /
      `_INTERNAL_JSON_NAMES`.
- [ ] `linear` runs produce no self-preference files and a byte-identical manuscript.
