# Task 03: Writer / Reviewer Governed Roles (constitutional amendment)

> **Status**: planned · **Depends on**: 00, 02, ../ari_rqgm/04, ../ari_rqgm/07 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

## 1. Purpose

The paper-archive co-evolution path needs two *governed* prompt-defined roles whose bytes RQGM
evolves at epoch boundaries — a manuscript **writer** and a manuscript **reviewer**. Today the
manuscript writer/reviewer live only inside the ungoverned `ari-skill-paper` subprocess
(`ari-skill-paper/src/prompts/{paper_writer.md, academic_reviewer.md}`), which imports zero
`ari.rqgm`. The whole point of this plan set is to bring co-evolution to paper writing **without**
governing that subprocess. This task designs the constitutional amendment that makes writer and
reviewer first-class governed roles inside ari-core:

- **promote** the existing context-scope-only `paper_writer` entry to a full **EVOLVABLE role**
  (writer task agent), unifying it with the whitelist it already owns;
- **add** a brand-new evaluable EVALUATOR role `paper_reviewer` (manuscript reviewer), distinct
  from the exploration `reviewer` (`evaluator/peer_review`);
- register both in the four constitutional tables (`EVOLVABLE_ROLES`, `CAPABILITY_MATRIX`,
  `CONTEXT_VIEW_WHITELISTS`, the founding prompt/component tables) and re-pin `CONSTITUTION_HASH`;
- **lift** the seed prompts from `ari-skill-paper`'s copies into ari-core governed founding
  templates, leaving the skill's copies untouched for `linear` mode;
- specify how the governed prompt bytes *drive* the dumb skill executor (the skill is the hands);
- reuse the EXISTING `RegistryTransitionEngine` (../ari_rqgm/09) + prompt-evolution pipeline
  (../ari_rqgm/07) verbatim to co-evolve the two roles at the paper-archive epoch boundary, and
  reuse the EXISTING same-role isolation the reviewer already enjoys.

This task consumes decisions from [00_paper_pipeline_investigation.md](00_paper_pipeline_investigation.md)
(where writer/reviewer live today, the skill tool surface) and
[02_paper_draft_archive_search.md](02_paper_draft_archive_search.md) (the archive substrate + the
draft `NodeExecutor` that these roles' prompts drive). It sits on top of the parent set's kernel
([../ari_rqgm/04_constitutional_kernel.md](../ari_rqgm/04_constitutional_kernel.md)) and
prompt-evolution machinery
([../ari_rqgm/07_prompt_spec_and_prompt_evolution.md](../ari_rqgm/07_prompt_spec_and_prompt_evolution.md)),
adding **two roles and two founding templates — no new mechanism**.

## 2. Scope

- The constitutional amendment adding `paper_writer` and `paper_reviewer` to the frozen rule
  tables in `ari-core/ari/rqgm/`:
  - `EVOLVABLE_ROLES` in `ari/rqgm/events.py` (both roles);
  - the capability matrix (`_EVOLVABLE_ROLES` → `_build_capability_matrix`) in
    `ari/rqgm/kernel_rules.py` (both roles → institutional + meta grants);
  - `CONTEXT_VIEW_WHITELISTS` in `ari/rqgm/kernel_rules.py` (`paper_writer` **unifies** with its
    existing entry; `paper_reviewer` is new);
  - the founding prompt table and founding component table in `ari/rqgm/prompt_spec.py`;
  - the role-required constraint table `REQUIRED_CONSTRAINTS_BY_ROLE` in `ari/rqgm/prompt_spec.py`;
  - `CONSTITUTION_HASH` re-pin (`ari/rqgm/kernel_rules.py` + the pin in
    `ari-core/tests/test_rqgm_kernel.py`).
- The seed-prompt LIFT: two new committed founding templates under
  `ari-core/ari/prompts/rqgm/{paper_writer.md, paper_reviewer.md}` lifted (byte-copied, then
  contract-annotated) from `ari-skill-paper/src/prompts/{paper_writer.md, academic_reviewer.md}`.
- The paper-writer context view (`build_paper_writer_context`, already present) and a new
  paper-reviewer context view (`build_paper_reviewer_context`) in `ari/rqgm/context_views.py`.
- The prompt-injection contract that lets the governed `paper_writer` prompt drive
  `ari-skill-paper`'s `write_paper_iterative` / `paper_refine` executor calls (an additive,
  default-empty override argument; §5.8).
- The writer/reviewer co-evolution at the paper-archive epoch boundary, expressed entirely in
  terms of the reused `PromptMutator` / the candidate-validation stage checks (the pure functions
  `CandidateValidationPipeline` bundles — `static_validation_failures` /
  `constitutional_validation_failures` / `check_output_against_schema`, called DIRECTLY, because the
  pipeline OBJECT is instantiated nowhere; §5.9) / `build_adoption_request` /
  `GovernanceOrchestrator.audit_epoch` / `RegistryTransitionEngine.resolve_transition` surfaces
  (§5.9). The orchestrator is *constructed* by doc 01 §5.4; this task only pins where its
  `audit_epoch` call sits in the boundary sequence and what it consumes.
- The `review_record` the governed `paper_reviewer` appends per score (§5.8) — an existing record
  type in the existing `rqgm_audit.jsonl`, and the reason `paper_reviewer_v1`'s founding-component
  row is operative rather than nominal.
- Same-role isolation for `paper_reviewer` (the reviewer never scores against another reviewer's
  output, and never authors its own successor) — reused unchanged from the exploration reviewer.

## 3. Non-goals

- **No new governance mechanism.** The candidate lifecycle, the six validation stages, the
  transition table, the kernel checks, the mutator, and the boundary transaction are the parent
  set's, used verbatim. This task adds rows to tables, not code paths.
- **No anchor / utility policy.** Where the `paper_reviewer`'s `anchor_evaluation` cases come
  from — the APReS-equivalent accept/reject corpus — and how utility is scored and frozen into
  the epoch fingerprint is owned by
  [04_anchor_utility_and_epoch_winners.md](04_anchor_utility_and_epoch_winners.md). This task
  only states that the reviewer's `anchor_evaluation` stage consumes those cases and that the
  writer has none.
- **No `paper_self_preference` adversary.** The AI-authorship / over-leniency detector and the
  displaced-accepted-AI-paper → replay dual objective is
  [05_adversarial_self_preference.md](05_adversarial_self_preference.md)'s scope. This task only
  registers the two roles the adversary later attacks.
- **No archive / search substrate.** `PaperArchiveStrategy`, the draft `NodeExecutor` wrapping,
  best-belief selection, lazy compile, and `paper_draft_archive.jsonl` are
  [02_paper_draft_archive_search.md](02_paper_draft_archive_search.md). This task supplies the
  *prompt* the executor uses, not the executor.
- **No mode switch / runtime construction.** `paper.mode`, `resolve_paper_mode`, and
  `PaperArchiveRuntime` construction are
  [01_paper_execution_mode.md](01_paper_execution_mode.md). This task's roles are constructed
  only when effective mode is `rqgm_archive`.
- **No claim-gate change.** The claim-evidence hard gate stays Layer-0, never evolves, never
  kernel-wraps a governed role; the reviewer scores drafts but never overrides the gate. Handoff
  is [07_claim_gate_handoff_and_evaluation.md](07_claim_gate_handoff_and_evaluation.md).
- **No governance of the `ari-skill-paper` subprocess.** The skill keeps its own prompt copies,
  imports no `ari.rqgm`, and is byte-identical under `linear`.

## 4. Existing ARI touchpoints

All paths repo-relative. Verified against branch `RQGM` (ari-core v0.9.1).

| Touchpoint | File / symbol | Why it matters here |
|---|---|---|
| Evolvable role vocabulary | `ari-core/ari/rqgm/events.py` — `EVOLVABLE_ROLES` (lines 57–68) | The closed tuple every governed role must be in. `paper_writer`/`paper_reviewer` are appended here; a role absent from it is treated as non-evolving by the whole stack. Parity is asserted by `test_rqgm_kernel.py::test_all_evolvable_roles_in_matrix` (each `EVOLVABLE_ROLES` member must have institutional **and** meta capability rows). |
| Capability matrix | `ari-core/ari/rqgm/kernel_rules.py` — `_EVOLVABLE_ROLES` (lines 115–134), `_build_capability_matrix` (lines 139–163), `CAPABILITY_MATRIX` (line 161) | The grant table `validate_capability` (../ari_rqgm/04 §5.4 item 3) reads. Both new roles are added to `_EVOLVABLE_ROLES`, so they inherit `_INSTITUTIONAL_BASE` (read records/active_prompt_text/checkpoint_artifacts, append/invoke records) and `_META_BASE` — identical to `generator`/`reviewer`. The 2026-07-14 `failure_summary_compressor` amendment (lines 125–133) is the exact precedent: a role in `EVOLVABLE_ROLES` but missing from the matrix is `CK-ACC-001`-blocked in every tier. |
| Context-scope whitelists | `ari-core/ari/rqgm/kernel_rules.py` — `CONTEXT_VIEW_WHITELISTS` (lines 234–252) | Already carries a `paper_writer` entry `{verified_context, science_data, claim_registry}` from the 2026-07-15 amendment (lines 222–251), added **deliberately NOT as an EVOLVABLE role** ("the paper skill is a separate ungoverned subprocess"). This task **reverses that deliberate exclusion** (§5.2) and adds a `paper_reviewer` row. `validate_context_scope` (../ari_rqgm/04 §5.4 item 11, `CK-CTX-*`, warn-and-flag) reads it. |
| Constitution hash | `ari-core/ari/rqgm/kernel_rules.py` — `constitution_hash()` / `CONSTITUTION_HASH` (lines 292–304); `_canonical_rules_payload` (lines 257–289) | The pin over all rule tables. Because `_canonical_rules_payload` serializes `capability_matrix` and `context_view_whitelists`, adding the two roles **necessarily** changes the hash. The pin `_EXPECTED_CONSTITUTION_HASH = "4fa36f2bd302"` in `ari-core/tests/test_rqgm_kernel.py:69` (and lines 726–729, 822, 1056, 1154) must be recomputed and re-pinned with an amendment comment (§5.7). |
| Founding prompt table | `ari-core/ari/rqgm/prompt_spec.py` — `FOUNDING_PROMPT_TABLE` (lines 153–217), `founding_spec_from_entry` (lines 262–323), `build_founding_specs` (lines 326–351) | Where each governed committed template becomes a v1 `active` founding `PromptSpec` (`prompt_hash == load_versioned(key)[1]`, pure bytes → spec). Two rows are appended for the lifted templates. The primary-last-per-role rollup convention applies (both roles are single-template, so ordering is trivial). |
| Founding component table | `ari-core/ari/rqgm/prompt_spec.py` — `FOUNDING_COMPONENT_TABLE` (lines 232–259), `founding_component_payloads` (lines 383–404) | The `(component_id, role, tier, prompt_id, capabilities)` bootstrap the runtime stamps. `paper_writer_v1` / `paper_reviewer_v1` are appended (institutional tier, empty extra capabilities), sorted by `component_id`. |
| Role-required constraints | `ari-core/ari/rqgm/prompt_spec.py` — `REQUIRED_CONSTRAINTS_BY_ROLE` (lines 52–63) | Machine-checkable constraint clauses each role's spec must carry verbatim, enforced by `constitutional_validation_failures` (`ari/rqgm/prompt_evolution.py:342`). Both new roles get entries (the writer's anti-fabrication clause, the reviewer's do-not-override-the-gate clause). |
| Transition table (topology-agnostic) | `ari-core/ari/rqgm/transition_rules.py` — `TRANSITION_TABLE` T1–T19 (lines 77–151), `allowed_transitions` (lines 166–171) | The status lifecycle is keyed by `(from_status, to_status)`, **not by role** — it is role- and topology-agnostic. `paper_writer`/`paper_reviewer` components ride the exact same `candidate → validated → shadow → probationary_active → active` spine with zero new rows. "Transition presence" for a role is *automatic* once it is a registered evolvable component (§5.6). |
| Prompt-evolution pipeline | `ari-core/ari/rqgm/prompt_evolution.py` — `PromptMutator.propose` (lines 532–666), `CandidateValidationPipeline` (lines 687–1076), `build_adoption_request` (lines 1122–1149), `candidate_budget_reason` (lines 466–489) | The six-stage candidate lifecycle and the mutator that emits candidates for *any* role string. Called with `role="paper_writer"`/`"paper_reviewer"` unchanged. The same-role separation check (lines 401–405) already forbids a `paper_reviewer` component from authoring `paper_reviewer` candidates. |
| Registry role rollup / adoption | `ari-core/ari/rqgm/transition_engine.py` — `resolve_transition` (line 414), `_role_opening` (lines 1332–1344), `_active_after` (lines 1346–1362), `adopt` (line 1048); `ari/rqgm/registry.py:active_prompt_hashes` (line 166) | The boundary-only T6 adoption (`one_adoption_per_role_per_boundary`, `role_opening_available`) and the `role -> component_id` "latest active wins" rollup. Works per-role: a `paper_writer` adoption is independent of a `paper_reviewer` adoption, both fenced to the boundary. |
| Same-role isolation precedent | `ari-core/ari/rqgm/context_views.py` — `build_reviewer_context` (lines 146–158), `build_paper_writer_context` (lines 205–223), `PAPER_WRITER_FIELDS` (lines 47–50) | The exploration reviewer's isolation is *constructive* — the builder has no parameter for other reviewers' outputs. `build_paper_writer_context` already exists. A sibling `build_paper_reviewer_context` follows the same shape (§5.3). |
| Skill writer/reviewer (the hands) | `ari-skill-paper/src/server.py` — `write_paper_iterative` (line 1092), `paper_refine` (line 2447), `review_compiled_paper` (line 2085); `ari-skill-paper/src/prompts/{paper_writer.md, academic_reviewer.md}` | The dumb draft executor. `write_paper_iterative` currently `_load_prompt`s its own `paper_writer.md`/`academic_reviewer.md` internally with no override. §5.8 adds one additive default-empty override argument so the governed prompt can drive it while `linear` stays byte-identical. |
| Peer-review call site | `ari-core/ari/evaluator/llm_evaluator.py` — `load_versioned("evaluator/peer_review")` (line 439) | The exploration `reviewer` render/score path. The `paper_reviewer` scoring is the paper-phase analog but runs entirely in ari-core (never through the skill's `review_compiled_paper`), producing the draft score `PaperArchiveStrategy` selects on (schema owned by doc 02). It emits **no** component-attributed record, which is why §5.8 adds the `review_record` append rather than inheriting one. |
| Observation record types | `ari-core/ari/rqgm/governance/_records.py` — `OBSERVATION_RECORD_TYPES` (lines 76–84); `governance/_evidence.py` — `ADMISSIBLE_KIND_BY_TYPE` (line 35), `EXCLUDE_SAME_ROLE` (line 38, applied at lines 97–103) | `review_record` is **already** a step-1 observation type and an admissible bundle kind. §5.8's reviewer append reuses it verbatim — no new record schema. The same-role rule drops a component's own records from bundles against it, so reviewer records are a reliability signal, never self-testimony. |
| Reliability / prosecution | `ari-core/ari/rqgm/governance/_reliability.py` — `build_reliability_entries` (lines 31–46, calibration at 103–118); `governance/_prosecution.py` — `RELIABILITY_FLOOR = 0.4` (line 35), `classify_target` | Turns authored records into `reliability_score`. A component that authors nothing gets `observation_count=0` → `None` + `insufficient_data` → `classify_target` returns `None` forever: registration without records is unenforceable. This is the gap §5.8 closes for `paper_reviewer_v1`. |
| Audit → adopt boundary order | `ari-core/ari/rqgm/runtime.py` — `run_epoch_audit` / `audit_epoch` (lines 548–564), `_run_epoch_boundary` (lines 966–1000); `ari/rqgm/transition_engine.py` — `resolve_transition` (lines 414–423), the `None` early-return (lines 456–459) | The exploration precedent §5.9 mirrors: candidates are minted at `:548` *inside* `run_epoch_audit` **before** `audit_epoch` at `:552`, then the report is passed to `resolve_transition`. `governance_report` is a required kwarg, and `None` returns early with `no_governance_report` — a missing audit disables adoption **silently**. |
| Audit-log sink | `ari-core/ari/rqgm/store.py` — `ImmutableAuditLog.append` / `.read`; `ari/paths.py:78` — `rqgm_audit.jsonl` in `META_FILES`; `ari/rqgm/adversarial/round.py` — `_log_all` (lines 290–302) | The already-registered checkpoint file and the append idiom §5.8 mirrors (JSONL truth, then the Task 02 envelope, fail-open per record). No new checkpoint file, no `paths.py` edit (§6.4). |
| Paper-quality rubric precedent | `ari-core/ari/evaluator/dynamic_axes.py` — `GENERIC_AXES` (line 84), `rubric_to_axes` (line 164), composed by `build_axes_for_run` (line 449); rubric resolved by `ari-core/ari/core.py` — `_load_rubric_dict_for_axes` (line 27) | The dynamic per-rubric scoring axes (venue rubric → score dimensions) the `paper_reviewer`'s rubric reuses; the reviewer's `output_schema` mirrors `academic_reviewer.md`'s `accept_recommendation` contract. **Amended 2026-07-17:** this row named the machinery but not how a *deterministic* scorer READS an axis, and these are judge-prompt axes — the module's only consumers are `axes_to_prompt_section` (render into a judge prompt) and `axes_to_weights` (weight LLM-produced scores), so it ships no reader. That gap is what the withdrawn `_RUBRIC_AXES` prompt-keyword scanner filled by inventing its own axis source. The binding rule for the LLM-free path (a reader declares the subject it measures; it reads an axis when the axis's own **rubric** bytes name that subject; an unreadable axis is ABSENT, never a constant) is specified in §5.8 — not left to the implementation. |

## 5. Proposed design

### 5.1 The amendment in one paragraph

Add exactly two roles to the closed evolvable vocabulary and give each one founding template.
`paper_writer` is **promoted** from the context-scope-only entry it is today into a full evolvable
writer role; `paper_reviewer` is a **new** evolvable evaluator role. Both flow through the existing
capability matrix (institutional tier), the existing transition spine, the existing candidate
lifecycle, and the existing boundary adoption — no new mechanism. The constitution hash moves once
and is re-pinned. Everything downstream (mutation, shadow, adoption, kernel validation) already
handles arbitrary role strings, so the amendment is "data, not code."

### 5.2 `paper_writer`: promote context-scope-only → EVOLVABLE (the collision to resolve)

There is a real, pre-existing collision to resolve — exactly the kind
[../ari_rqgm/01](../ari_rqgm/01_execution_modes_and_compatibility.md) resolved for "config home".
The 2026-07-15 amendment added `paper_writer` to `CONTEXT_VIEW_WHITELISTS`
(`kernel_rules.py:247–251`) **and explicitly documented** (in that block and in
`test_rqgm_kernel.py:64–68`) that it is *deliberately NOT an `EVOLVABLE_ROLES` member* because "the
paper skill is a separate ungoverned subprocess package in v1." This plan set is precisely the v2
that reverses that decision: with the governed writer role living in ari-core (not the subprocess),
the deliberate exclusion no longer holds.

**Decision:** promote in place, do not fork. `paper_writer` becomes an `EVOLVABLE_ROLES` member and
gains capability-matrix + transition presence; its existing whitelist entry
`{verified_context, science_data, claim_registry}` is **unified** into that role's context view
(no new key set, no `paper_writer_v2` variant name). Rationale: minting a second role name would
split the one whitelist the kernel already pins and the one `build_paper_writer_context` builder
already renders (`context_views.py:205–223`); promotion keeps a single source of truth and lets the
existing leak-regression posture ride unchanged.

```python
# planned: ari-core/ari/rqgm/events.py  (EVOLVABLE_ROLES, append)
EVOLVABLE_ROLES: tuple[str, ...] = (
    "generator", "reviewer", "adversary", "defender", "judge", "router",
    "prompt_mutator", "clean_room_generator", "replay_selector",
    "failure_summary_compressor",
    # Paper-archive co-evolution (plan ari_rqgm_paper/03): promote the paper
    # writer from a context-scope-only entry to a full evolvable role, and add
    # the manuscript reviewer. Both drive the ari-skill-paper executor (hands);
    # the skill remains ungoverned.
    "paper_writer",
    "paper_reviewer",
)

# planned: ari-core/ari/rqgm/kernel_rules.py  (_EVOLVABLE_ROLES, append the same two)
_EVOLVABLE_ROLES: tuple[str, ...] = (
    "generator", "reviewer", "adversary", "defender", "judge", "router",
    "prompt_mutator", "clean_room_generator", "replay_selector",
    "failure_summary_compressor",
    "paper_writer",     # institutional + meta grants, identical to `generator`
    "paper_reviewer",   # institutional + meta grants, identical to `reviewer`
)
```

`_build_capability_matrix` then assigns `(paper_writer, institutional)` and `(paper_writer, meta)`
(and the reviewer pair) the same `_INSTITUTIONAL_BASE` / `_META_BASE` grants every other evolvable
role gets. Neither role may write the registry or activate candidates (only the
`registry_transition_engine`, `REGISTRY_WRITER`, can — invariant 10); neither reads retired prompt
text. This is exactly the `failure_summary_compressor` fix precedent (`kernel_rules.py:125–133`).

The `paper_writer` whitelist stays byte-identical:

```python
# ari-core/ari/rqgm/kernel_rules.py  (CONTEXT_VIEW_WHITELISTS — paper_writer UNCHANGED, unified)
"paper_writer": frozenset({
    "verified_context",
    "science_data",
    "claim_registry",
}),
```

### 5.3 `paper_reviewer`: new evaluator role, context view, same-role isolation

`paper_reviewer` is a **distinct** evaluator role — NOT the exploration `reviewer`
(`evaluator/peer_review`). Rationale: the exploration reviewer scores *proposals/nodes* against a
research rubric; the paper reviewer scores a *rendered manuscript draft* against a venue rubric and
against the accept/reject anchor corpus (doc 04). Sharing the role would conflate two utility
policies and two anchor sets. Its context view (brief canonical set):

```python
# planned: ari-core/ari/rqgm/kernel_rules.py  (CONTEXT_VIEW_WHITELISTS, add paper_reviewer)
"paper_reviewer": frozenset({
    "draft_manuscript",     # the archive draft under review (rendered LaTeX / section text)
    "verified_context",     # the same Layer-0 verified evidence the writer saw
    "science_data",         # metrics/results backing the claims
    "reference_context",    # the anchor/reference-case projection (owned by doc 04)
}),
```

`reference_context` is the paper-reviewer's window onto the ground-truth anchor case; its exact
contents and curation are owned by
[04_anchor_utility_and_epoch_winners.md](04_anchor_utility_and_epoch_winners.md). The reviewer
**never** sees the writer's raw transcript, other drafts' reviewer outputs, frontier/utility
scores, or governance internals — the exclusion is constructive (the builder has no parameter for
them), mirroring `build_reviewer_context` (`context_views.py:146–158`):

```python
# planned: ari-core/ari/rqgm/context_views.py  (sibling of build_paper_writer_context)
PAPER_REVIEWER_VIEW_ROLE = "paper_reviewer"
PAPER_REVIEWER_FIELDS: frozenset[str] = CONTEXT_VIEW_WHITELISTS[PAPER_REVIEWER_VIEW_ROLE]

def build_paper_reviewer_context(
    draft_manuscript, verified_context, science_data, reference_context
) -> dict:
    """Paper-reviewer row: EXACTLY the four whitelisted fields, deterministic
    projection. Other drafts' reviews, the writer transcript, and every
    frontier/utility signal have no parameter here (same-role isolation is
    constructive, like build_reviewer_context). The returned key set is exactly
    PAPER_REVIEWER_FIELDS so validate_context_scope("paper_reviewer", view)
    passes and flags any foreign field a caller adds."""
    return {
        "draft_manuscript": _scrub(_plain(draft_manuscript), frozenset()),
        "verified_context": _scrub(_plain(verified_context), frozenset()),
        "science_data": _scrub(_plain(science_data), frozenset()),
        "reference_context": _scrub(_plain(reference_context), frozenset()),
    }
```

**Same-role isolation** (mirror `peer_review`) has two layers, both reused unchanged:

1. *Scoring-time* — the reviewer scores each draft in isolation; no other draft's reviewer output
   is ever passed in (constructive, above).
2. *Co-evolution-time* — a `paper_reviewer` component may never author a `paper_reviewer`
   candidate. This is already enforced by `constitutional_validation_failures`
   (`prompt_evolution.py:401–405`): "only prompt_mutator/clean_room_generator may emit candidates"
   and "same-role generation" are `CK`-flagged. No change needed — the check keys on the role
   string, which `paper_reviewer` now is.

### 5.4 Role-required constitutional constraints

Each role's founding + candidate specs must carry machine-checkable constraint clauses verbatim
(`REQUIRED_CONSTRAINTS_BY_ROLE`, enforced by `constitutional_validation_failures`
`prompt_evolution.py:342–347`). Decision — one clause per role, lifted from the skill prompts'
existing guardrails and the Layer-0 invariant:

```python
# planned: ari-core/ari/rqgm/prompt_spec.py  (REQUIRED_CONSTRAINTS_BY_ROLE, add)
"paper_writer": (
    # from ari-skill-paper/src/prompts/paper_writer.md "Do NOT hallucinate results,
    # hardware specs, or citations not present in the experiment data."
    "Do not fabricate results, hardware specs, or citations absent from the "
    "verified experiment data.",
),
"paper_reviewer": (
    # the Layer-0 gate is never overridable by an evolvable evaluator, and a
    # reviewer never writes frontier scores (mirror the exploration reviewer).
    "Do not override the claim-evidence hard gate.",
    "Do not directly modify frontier scores.",
),
```

These are the *only* constitutional coupling the roles have to the claim gate: the reviewer is
constrained by a clause that any candidate must carry to pass `constitutional_validation`; the gate
itself stays Layer-0 and is never kernel-wrapped (global invariant; handoff owned by
[07_claim_gate_handoff_and_evaluation.md](07_claim_gate_handoff_and_evaluation.md)).

### 5.5 Seed-prompt LIFT and founding-table entries

The governed founding prompts are **lifted** from the skill's committed copies into ari-core
committed templates, so the governed writer/reviewer start from exactly today's proven behavior and
the skill keeps its copies for `linear`:

- `ari-skill-paper/src/prompts/paper_writer.md`   → `ari-core/ari/prompts/rqgm/paper_writer.md`
- `ari-skill-paper/src/prompts/academic_reviewer.md` → `ari-core/ari/prompts/rqgm/paper_reviewer.md`

The lift is a byte-copy of the instruction body, plus the standard new-prompt checklist (the four
snapshot layers per ../ari_rqgm/07 §5.2): the copied bytes define `prompt_hash = sha256(bytes)[:12]`
via `founding_spec_from_entry`, so the founding specs are `active`-on-creation and verifiable with
zero new hashing. Two rows are appended to each founding table:

```python
# planned: ari-core/ari/rqgm/prompt_spec.py  (FOUNDING_PROMPT_TABLE, append)
#   writer returns the ENTIRE corrected LaTeX document → freeform reply kind.
("paper_writer_prompt_v1", "rqgm/paper_writer", "paper_writer", True,
 {"__reply__": "freeform"}),
#   reviewer returns the academic_reviewer.md JSON contract (overall/strengths/
#   weaknesses/suggestions/accept_recommendation) → json_object with the
#   selection-bearing field typed.
("paper_reviewer_prompt_v1", "rqgm/paper_reviewer", "paper_reviewer", True,
 {"__reply__": "json_object", "accept_recommendation": "string"}),

# planned: ari-core/ari/rqgm/prompt_spec.py  (FOUNDING_COMPONENT_TABLE, append; sorted by id)
("paper_reviewer_v1", "paper_reviewer", "institutional",
 "paper_reviewer_prompt_v1", {}),
("paper_writer_v1", "paper_writer", "institutional",
 "paper_writer_prompt_v1", {}),
```

Both are `evolvable=True`, tier `institutional` (task agents, not meta), empty extra capability
maps (the matrix grants are role-derived, §5.2). Because each role has exactly one founding
template, the "primary template last per role" rollup convention (`FOUNDING_PROMPT_TABLE` docstring)
is satisfied trivially — `role -> prompt_v1` is unambiguous.

**Bootstrap gating.** The founding specs/components enter the registry ONLY when effective paper
mode is `rqgm_archive` (they ride the same `founding_registration_events()` the exploration roles
do, but that bootstrap runs only inside `PaperArchiveRuntime`, constructed by doc 01). Under
`linear` (default), none of `rqgm/paper_writer.md` / `rqgm/paper_reviewer.md` is loaded, no founding
spec is built, and the skill's own copies are the only prompts in play — byte-identical to today.

### 5.6 Transition presence (topology-agnostic, automatic)

"Transition presence" for the two roles is **not** a new table. `TRANSITION_TABLE`
(`transition_rules.py:77–151`) is keyed by `(from_status, to_status)` — it is role- and
topology-agnostic (the parent set proved this by bolting the same table onto the exploration tree).
A `paper_writer_v2` or `paper_reviewer_v2` candidate rides the identical
`candidate → validated → shadow → probationary_active → active` spine (T1, T3, T6, T7) and the same
sanction edges (T9–T19). No `paper_*` rows are added; adding them would be the only way to *break*
the invariant that the constitution is role-agnostic. The kernel's `validate_transition`
(../ari_rqgm/04 §5.4 item 5) checks table membership and boundary/RTE shape — all satisfied by the
existing rows.

The only role-aware piece is the boundary *adoption*: `_role_opening` / `_active_after`
(`transition_engine.py:1332–1362`) and the T6 guard `one_adoption_per_role_per_boundary` operate
per role string, so a `paper_writer` adoption and a `paper_reviewer` adoption are independent, each
fenced to at most one per boundary — exactly the exploration semantics, no change.

### 5.7 `CONSTITUTION_HASH` re-pin

`_canonical_rules_payload` (`kernel_rules.py:257–289`) serializes `capability_matrix` and
`context_view_whitelists`. Adding `(paper_writer, institutional)`, `(paper_writer, meta)`,
`(paper_reviewer, institutional)`, `(paper_reviewer, meta)` to the matrix and the `paper_reviewer`
whitelist row **necessarily** changes `constitution_hash()`. This is a deliberate, reviewed
amendment, so the pin is recomputed and re-pinned (the `failure_summary_compressor` / `paper_writer`
amendments are the exact precedent):

```python
# planned: ari-core/tests/test_rqgm_kernel.py  (re-pin + amendment comment)
# Re-pinned <impl-date>: constitutional amendment (plan ari_rqgm_paper/03)
# promoting `paper_writer` to a full EVOLVABLE role (capability-matrix +
# transition presence, unifying its existing context-scope whitelist) and
# adding the new evaluable `paper_reviewer` role (institutional grants + a
# {draft_manuscript, verified_context, science_data, reference_context}
# context view). The paper roles drive the ungoverned ari-skill-paper
# executor; the skill itself is not governed.
_EXPECTED_CONSTITUTION_HASH = "<recompute at implementation>"   # was "4fa36f2bd302"
```

The five read sites in `test_rqgm_kernel.py` (lines 69, 726–729, 822, 1056, 1154) all consume the
one constant, so the re-pin is a single-line change plus the comment. `record_constitution_hash`
(`ari/rqgm/state.py:136–167`) additively records the new value into `{ckpt}/meta.json` — additive,
no migration.

### 5.8 How the governed prompts drive the skill executor (the skill is the hands)

The governed `paper_writer` prompt is the **source of truth** for the writer instruction under
`rqgm_archive`; `ari-skill-paper` is the dumb executor that renders/compiles LaTeX (doc 02 owns the
`NodeExecutor` wrapping). Today `write_paper_iterative` / `paper_refine` `_load_prompt` their own
`paper_writer.md` internally with no override (`server.py:1092`, `:2447`). Decision — add ONE
additive, default-empty override argument to each drafting tool:

```python
# planned (additive, backward-compatible): ari-skill-paper/src/server.py
async def write_paper_iterative(
    ...,                             # every existing parameter unchanged
    writer_prompt_override: str = "",  # "" ⇒ load paper_writer.md (linear byte-identical)
) -> dict: ...

async def paper_refine(
    ...,
    writer_prompt_override: str = "",
) -> dict: ...
```

- When `writer_prompt_override == ""` (the `linear` default, and the value any non-RQGM caller
  passes), the skill loads its own `paper_writer.md` exactly as today — **byte-identical**.
- Under `rqgm_archive`, the draft `NodeExecutor` (doc 02) resolves the epoch's **active**
  `paper_writer` prompt text via the governed loader (`GovernedPromptLoader`, ../ari_rqgm/07 §5.5)
  and passes it as `writer_prompt_override`; the skill uses that text as the section-drafting
  instruction. Passing an instruction *string* is not governance — the skill still evolves nothing;
  the evolving bytes live only in ari-core.

**The reviewer never touches the skill.** Per the brief's executor spec, `review_compiled_paper` is
NOT used as the archive scorer. The governed `paper_reviewer` runs entirely in ari-core: ari-core
renders the active `paper_reviewer` prompt over `build_paper_reviewer_context(...)` and scores the
draft through the agent-as-judge path (the `evaluator/peer_review` analog,
`llm_evaluator.py:439`), emitting the draft score that `PaperArchiveStrategy` best-belief-selects on
(schema `paper_draft_archive.jsonl`, owned by doc 02). The skill's *internal* review/revise loop
(`max_revision_rounds`, driven by `academic_reviewer.md`) stays a mechanical intra-tool rendering
detail — it is the "hands," not the archive scorer, and it is left untouched.

**How the score is dimensioned, and how the prompt drives it (re-specified 2026-07-17 —
SUPERSEDES the "prompt DECLARES the criteria" reading recorded earlier the same day).** The default
path is **deterministic and LLM-free**, not the `llm_evaluator.py:439` render the paragraphs above
describe. The earlier reading of this bullet list derived the scoring axes from the REVIEWER PROMPT
(a `_RUBRIC_AXES` table of prompt trigger words, clause-scoped by `_CRITERION_MARKERS`, weighted by
the share of "criterion clauses" each axis won). **That was an invention and is withdrawn.** No plan
sanctioned it — §4's "Paper-quality rubric precedent" row named
`dynamic_axes.py` — `GENERIC_AXES` (line 84) / `rubric_to_axes` (line 164) as the machinery "the
`paper_reviewer`'s rubric reuses", while `grep -rn "dynamic_axes\|rubric_to_axes\|GENERIC_AXES"
ari-core/ari/rqgm/paper_runtime.py` returned NOTHING. It also failed on its own terms, measured:

* **It produced ZERO discrimination.** Under the SHIPPED founding prompt a 100-char stub (0 claims,
  0 sections) and a rich 8000-char draft (8 claims, 6 sections) BOTH scored exactly **1.0**. The
  reading zeroed every axis the prompt did not name, and the founding bytes honestly declare ONE
  criterion, so the whole score collapsed to `1.0 - sat(env_leaks/4)` — 1.0 for nearly every draft.
  In-epoch best-belief selection was degenerate **by default**, which the previous "Residual"
  recorded as a known thinness rather than treating as the defect it was.
* **It put the axis vocabulary inside the bytes being judged.** Sourcing dimensions from the
  reviewer's own evolving prompt lets a candidate MINT or DELETE score dimensions by wording. The
  earlier text argued this was unscoreable because a reviewer's own utility is its anchor agreement
  — true, but it misses that the reviewer's dimensions decide the WRITER's utility, and the writer
  co-evolves against exactly that surface.

The reading is now:

* **The dimensions are the VENUE's, not the reviewer's.** The axis set is
  `dynamic_axes.build_axes_for_run(rubric=...)` — that module's own public composer over
  `GENERIC_AXES` (the domain-agnostic floor) + `rubric_to_axes` (venue rubric -> score dimensions) —
  with the rubric resolved from the same `ARI_RUBRIC` source the exploration evaluator uses
  (`core._load_rubric_dict_for_axes`). No rubric on disk => `GENERIC_AXES` alone, which is that
  module's own documented degradation ("callers degrade to the generic floor"), not a local default.
* **The prompt supplies EMPHASIS over those axes** (`emphasised_axes`): an axis is emphasised when
  the prompt names it, and the vocabulary is the RUBRIC's — a word of the axis's own venue-authored
  name. An emphasised axis counts double (`_EMPHASIS_MULTIPLIER`). Bounded on purpose: the reviewer's
  bytes RE-RANK the venue's dimensions and can never delete one. Two different reviewer prompts still
  score the same draft differently and can rank two drafts oppositely — the property best-belief
  selection depends on — while a prompt that names no rubric axis WARNs `PROMPT-INDEPENDENT`, because
  the score is then the venue's own weighting and evolving those bytes cannot move it.
* **NEW RULE — how an LLM-free reader binds to a rubric axis (the rule this plan lacked).** §4 named
  the axis machinery but never said how a *deterministic* scorer reads an axis, and the axes are
  judge-prompt axes: `dynamic_axes`' only consumers are `axes_to_prompt_section` (render INTO a judge
  prompt) and `axes_to_weights` (weight LLM-PRODUCED axis scores). There is no reader in that module.
  So one is specified here rather than assumed in code: each reader declares the SUBJECT it measures —
  a property of the MEASUREMENT itself — and reads an axis when the axis's own **rubric bytes** (name
  + description, venue-authored) name that subject. Matching against rubric bytes and never against
  the reviewer's prompt is what keeps the trust boundary above intact. Every read stays a bounded
  [0,1] read of the draft TEXT (§5.5: no compile): `% CLAIM` anchors, `\section` count, body length,
  environment-identifier leakage.
* **An axis no reader can read is ABSENT — excluded from the composite, never scored by a constant.**
  `novelty` ("Does the work advance beyond existing approaches?") has no deterministic read of a .tex
  file, so the LLM-free composite covers the readable subset and says so, rather than fabricating a
  number for the rest. This is the same discipline `governance/_reliability.py:110-119` applies to a
  missing calibration part, and the same one that removed the `stated_confidence()` constant (below).
  Pinned by a test asserting `axis_draft_score(novelty, ...) is None`.
* **Measured consequence (2026-07-17).** Under the shipped founding prompt (rubric `neurips`, 13
  axes, 11 readable, `novelty`/`significance` ABSENT): stub **0.170447**, rich draft **1.0** — it
  DISCRIMINATES. The founding prompt emphasises exactly `{reproducibility}`, and the one criterion it
  actually declares still bites (a leaky draft scores strictly below the same draft without leaks).
  Pinned by tests.
* This is not a scoreable surface for a candidate to game: a reviewer's OWN utility is its held-out
  anchor agreement (doc 04 §5.1), never the draft scores it emits.

**Full rubric coverage via the judge — LANDED as opt-in (2026-07-19).** An axis like `novelty` is
only scoreable by the agent-as-judge path (an injected `score_fn`, which receives the prompt and is
where an LLM-backed scorer plugs in). That path is now implemented in `ari/rqgm/paper_judge.py`
(`build_agent_as_judge_score_fn`): it renders the ACTIVE reviewer prompt as the emphasis over the
venue rubric axes, scores the draft with the real `LLMClient`, and combines the per-axis scores on
the SAME weighting (`_rubric_draft_score`'s, emphasis-doubled) so judge and rubric are interchangeable
on one scale. `cli/paper_dispatch.py` injects it as `reviewer_score_fn` (shared by `ari paper`, `ari run` and `ari resume`) **only when
`rqgm.paper.reviewer.agent_as_judge.enabled`** (env `ARI_PAPER_AGENT_AS_JUDGE`); OFF by default, so
the deterministic LLM-free composite (which honestly covers the readable subset) stays the on-ramp
scorer and no run puts live LLM calls on the draft path unless it asks. **Fail-open is absolute:** any
LLM error, empty reply, or reply naming no rubric axis degrades to the deterministic rubric via
`deterministic_rubric_score_fn` — never a fabricated constant.

Verified live 2026-07-19 against the cli-shim on two real archive drafts: the judge returned genuinely
different scores (0.28 vs 0.21) where the rubric would tie mature drafts at the ceiling, and the active
reviewer prompt moved the score (0.28 neutral → 0.20 novelty-emphasised) — so the reviewer role's
co-evolution actually moves best-belief selection (§5.8).

**Context isolation and the evidence channel.** The judge carries EXACTLY the
`PAPER_REVIEWER_FIELDS` whitelist as capped strings (asserted in `_paper_reviewer_string_view`),
because the archive's inputs are a `.tex` draft and JSON evidence blobs rather than the record
projections `build_paper_reviewer_context` maps — that builder's `_plain` keeps only dicts, so a raw
string maps to `{}`. An adversarial audit on 2026-07-19 found the first cut satisfied the KEY SET
while leaving three of the four VALUES structurally empty in every production run: `cli/projects.py`
passes the CLI's `{goal, topic, file}` dict, which has none of the keys the judge read, and
`PaperArchiveRuntime._build_experiment` stores those keys as PATHS (`_p(name)` → `str(ckpt / name)`)
because the paper SKILL resolves them server-side. The judge renders in-process, so it now resolves
each channel itself (`_resolve_evidence`: read a path, pass through inline content, else fall back to
the canonical checkpoint file), and `cli/paper_dispatch.py` passes `checkpoint_dir`. A channel that still
has no content is LOGGED by name — a judge scoring with no Layer-0 evidence cannot check a claim, and
that must not be silent.

**Hardening from the same audit.** The combination refuses a reply covering less than
`_MIN_AXIS_COVERAGE` (0.5) of the rubric's total axis weight, so a reply naming one low-weight axis is
no longer combined into a confident-looking score best-belief consumes as a full rubric verdict;
non-finite values (`json.loads` accepts a bare `NaN`, which survives naive clamping) are rejected
rather than propagated into selection and the audit log; and because a judge score and a fallback
rubric score are the same float to every consumer, the score_fn carries `judged` / `degraded`
provenance counters that `cli/paper_dispatch.py` logs after the archive — a run whose LLM was down for every
call is no longer indistinguishable from a fully judged one. `agent_as_judge.max_tokens` is a real
bound: `LLMClient.complete` gained an optional `max_tokens` (off by default, so every existing caller
is byte-identical) rather than the config declaring a cost control nothing enforced.

**The remaining explicit decision** (still deferred) is the co-evolution `llm=` / `adversary_llm=`
mutator+adversary wiring in production: the judge lands the SCORE seam, not the prompt-mutation or
attack LLM seams. A default paper run at `epoch.rounds: 2` does not witness a changed active reviewer
hash regardless (that needs ~5 boundaries / `rounds: 8`, see §5.5), so those seams remain a separate
decision from this one.

**Every governed reviewer score also authors a `review_record`.** Emitting the draft score alone
would leave `paper_reviewer_v1` registered but *structurally invisible to the audit network*: the
component would author nothing, so `build_reliability_entries` (`governance/_reliability.py:31–45`)
would report `observation_count=0` → `reliability_score: None` + `insufficient_data` for it forever,
`classify_target` would return `None` permanently, and the row would violate
`FOUNDING_COMPONENT_TABLE`'s own stated contract (`prompt_spec.py:219–231`: "one entry per component
id the RUNTIME actually stamps today"). Registration would be nominal, not operative. Decision —
each governed `paper_reviewer` score additionally appends one **`review_record`** into
`rqgm_audit.jsonl` via `ImmutableAuditLog.append`. This is the parent set's **existing** step-1
observation type (`governance/_records.py:76–84` `OBSERVATION_RECORD_TYPES`; admissible kind at
`governance/_evidence.py:35`; parent
[../ari_rqgm/05](../ari_rqgm/05_governance_orchestrator.md) §5.3 step 1) — **no new record schema,
no new type**. The append mirrors `AdversarialRound._log_all` (`adversarial/round.py:290–302`),
which already writes the JSONL truth and then the Task 02 audit envelope for every adversarial
record:

```python
# planned: the envelope each paper_reviewer score appends — ENVELOPE_FIELDS
# (kernel_rules.py:58–68) plus the observation payload the reliability
# monitor already reads. No new fields, no new record type.
{
    "record_type": "review_record",
    "record_id": ...,
    "epoch_id": ...,                      # the frozen paper epoch
    "component_id": "paper_reviewer_v1",  # the epoch's active reviewer rollup
    "role": "paper_reviewer",
    "prompt_hash": ...,                   # the epoch-frozen active reviewer hash
    "confidence": ...,                    # the reviewer's own stated confidence.
                                          # OMITTED ENTIRELY when no confidence
                                          # source is wired (2026-07-17, below)
    "outcome_score": ...,                 # the draft score it emitted
    "agreement": ...,                     # vs the doc 04 anchor label, when the case carries one
    "node_id": ...,                       # the draft id (paper_draft_archive.jsonl key)
    "source_refs": [...],
}
```

`confidence` + `outcome_score` are what make the row *assessable*: `build_reliability_entries` means
`|confidence − outcome_score|` into `calibration_error` (`_reliability.py:103–109`) and folds
`1 − calibration_error` into `reliability_score` (`:117–118`), so a reviewer whose stated confidence
drifts from the scores it actually emits falls below `RELIABILITY_FLOOR` (0.4,
`governance/_prosecution.py:35`) and becomes prosecutable. This is also the artifact doc 04 already
assumes exists for the frontier-repair staleness closure. **`confidence` is written only when a
confidence source is actually wired** — see the 2026-07-17 amendment below; the row stays assessable
without it (`outcome_score`, `agreement`, and attack involvement are unaffected).

> **Calibration source — landed decision (wave 3c, 2026-07-16).** The
> calibration pair `confidence`/`outcome_score` rides the **anchor**
> `review_record`s, not the per-draft ones: a *DRAFT* `review_record` carries
> the reviewer's held-out anchor `agreement` (its trust signal) instead of a
> self-graded confidence, because a reviewer's per-draft self-confidence is
> only meaningfully assessable against ground truth (there is no ground truth
> for a fresh AI draft). Each held-out ANCHOR case the reviewer scores emits a
> `review_record` carrying `confidence` + `outcome_score` (calibration) **and**
> `agreement` (accuracy). This SANCTIONS the anchor-driven source over the
> plan's original "every draft review_record carries confidence + outcome_score
> for per-draft calibration" — the code and this plan now agree
> (`paper_runtime.py::GovernedPaperReviewer.score` / `_score_reviewer_on_anchor`).
> When there is no anchor (the on-ramp) the DRAFT record falls back to
> `confidence` + `outcome_score` so the row stays assessable.

> **Confidence is a SOURCE, not a default — amended 2026-07-17.** The decision
> above says each anchor `review_record` carries `confidence`, but never said
> where the number comes from when nothing states one. The implementation
> answered with a constant: `stated_confidence()` returned a hardcoded `1.0`
> whenever no `confidence_fn` was injected — **which is the production wiring**
> (`cli/projects.py` passes none), so `1.0` was the confidence stamped on every
> anchor record in every real run, and the per-draft on-ramp fallback used
> `confidence = score`, fabricating perfect calibration. Both are withdrawn.
>
> The constant did not merely add noise, it **corrupted the channel
> algebraically**. An anchor record's `outcome_score` IS its `agreement`, so
> `calibration_error = mean|1.0 − agreement| = 1 − agreement_rate`, and
> `reliability_score = mean[1 − attack_ratio, agreement_rate,
> 1 − calibration_error]` therefore averaged **one signal twice under two
> names** while presenting the parts as independent evidence — and that score
> gates `RELIABILITY_FLOOR`. Measured: `agreement_rate 0.5` ⇒
> `calibration_error 0.5` ⇒ `reliability_score 0.667`; the honest value is
> `0.75`.
>
> **Rule:** when no confidence source is wired, `stated_confidence()` is `None`
> and the `confidence` field is **omitted from the record**. Absent ⇒ explicit
> absence, never a constant. `_reliability.py:102–107` already filters
> non-numeric confidence out of `calibrations`, so `calibration_error` becomes
> ABSENT and `reliability_score` averages only the parts that actually exist —
> the discipline that module already applies to every other missing part. A
> reviewer whose stated confidence drifts from its outcomes is still
> prosecutable the moment a real confidence source is wired; until then the
> calibration part is honestly missing rather than silently self-satisfied.

**Same-role exclusion — the record is a reliability signal, not testimony.** The reviewer's own
`review_record`s are same-role-excluded from an evidence bundle assembled *against* it:
`_evidence.py:97–103` drops any ref whose author `role` equals the target's role with reason
`EXCLUDE_SAME_ROLE` (`same_role_source`). They drive reliability and classification (step 1 →
`build_reliability_entries` → `classify_target`), never admissibility — a `paper_reviewer` cannot
testify for or against itself, mirroring the parent fixture
(`ari-core/tests/test_rqgm_governance.py:84–95`, reviewer_v3's own `review_record`s). This is the
audit-network counterpart of §5.3's co-evolution-time isolation.

`paper_writer_v1` stamps **nothing** by design: the writer authors the draft, whose provenance is
`paper_draft_archive.jsonl` (doc 02), not the audit log. Its founding row is justified by the
adoption path rather than by observation — `_role_opening` / `_active_after`
(`transition_engine.py:1332–1362`) need a registered incumbent for the role for a `paper_writer_v2`
adoption to have an opening to fill (§5.6). Its accountability is the reviewer's score plus the doc
05 adversary, not a reliability entry.

Under `linear`, none of the above runs: the executor is never wrapped, `writer_prompt_override` is
never set, no `review_record` is appended, and the skill is the same subprocess it is today.

### 5.9 Writer/reviewer co-evolution at the epoch boundary (reused verbatim)

> **Framing honesty (wave 3c, 2026-07-16; design in
> [04](04_anchor_utility_and_epoch_winners.md) §5.1, revised 2026-07-16;
> LANDED).** BOTH prompts now co-evolve via prompt adoption. `paper_reviewer`
> has the accept/reject anchor and the doc-05 adversary, which OPEN its role
> (impeachment → sanction), so a validated successor prompt can adopt
> (§5.8/doc 05). The **writer** now has an anchor too — the Layer-0
> claim-evidence gate's deterministic faithfulness (`writer_faithfulness_score`,
> `WRITER_ANCHOR_DESCRIPTOR`, landed on the anchor board by
> `PaperAnchorPool.record_writer_faithfulness`, keyed on `prompt_hash` alone) —
> so an unfaithful writer is sanctioned through a REAL round, its role opens,
> and the successor that used to wait at `shadow` adopts via the SAME T6. Proven
> by execution: the active writer `prompt_hash` moves
> `f38a15f0f140 → b2c36f9a8232` over 8 rounds, and the causal control (faithful
> drafts) yields zero writer attacks and a constant hash. So "co-evolution of the
> two roles" below means, as implemented: BOTH prompts co-evolve via adoption.
>
> **The honest nuances that remain.** (a) The writer's *DRAFT* winners are still
> epoch-local — best-belief selection under the in-epoch-frozen reviewer (§5.6);
> only the PROMPT co-evolves cross-epoch. (b) The writer adopts only on a
> REGRESSION: a better challenger alone never displaces a faithful incumbent
> (the conservative behavioral-role model — sanction opens a role, comparison
> does not). (c) The writer-targeted attack rides the `paper_self_preference`
> round, which fires only on an over-accepted anchor case, so an unfaithful
> writer under a reviewer that over-accepts nothing is not sanctioned today.
> (`paper_writer_v1`'s founding row was justified precisely because the adoption
> MECHANISM is role-driven and was already in place, awaiting only the anchor —
> which is exactly how the anchor landed with no new transition edge.)

Co-evolution of the two roles is the parent set's prompt-evolution pipeline with `role` set to
`"paper_writer"` / `"paper_reviewer"` — no new class, no new stage. Within a paper-archive epoch the
active writer/reviewer prompt hashes are **frozen** (global invariant "within-epoch freeze"); a new
prompt may only *become* active at a boundary through `RegistryTransitionEngine`, kernel-validated.

Per boundary, for each role R ∈ {`paper_writer`, `paper_reviewer`}:

1. **Propose.** `PromptMutator.propose(role=R, incumbent=<active R spec>, failure_summaries=...,
   mutation_kind=..., epoch_id=..., existing_records=...)` (`prompt_evolution.py:532`) emits at most
   `rqgm.prompt_evolution.max_candidates_per_role_per_epoch` candidates (budget gate
   `candidate_budget_reason`, `:466`), capped by
   `rqgm.prompt_evolution.max_total_candidates_per_epoch` (default **4**, reused from
   `ari-core/ari/configs/defaults.yaml`). The mutator writes candidates ONLY — never the registry.
2. **Validate.** *(Corrected 2026-07-17; static_validation + schema_dry_run wired 2026-07-18 — what
   actually runs.)* The class `CandidateValidationPipeline` (`prompt_evolution.py:724`) that this
   step originally cited as "runs the six stages monotonically" **is instantiated NOWHERE** — for
   EVERY governed role, not just the paper roles (a repo-wide grep finds only its definition,
   docstrings, and tests; `select_for_replay` has one call site, `prompt_evolution.py:938`, reachable
   only through `run_stage`, which nothing in production calls). So the stages are NOT run through the
   pipeline OBJECT. Instead `PaperArchiveRuntime._paper_candidate_evaluator` (`paper_runtime.py`)
   calls the pipeline's **pure-function stage checks DIRECTLY**, in the plan's monotonic order, over
   every pending paper candidate — reusing the parent set's functions verbatim (one definition of
   each stage, never a paper-local copy). A candidate that fails a deterministic stage is DROPPED
   (never emits an evaluation, so no board score can carry it up the spine); the passing candidates'
   evaluation dicts merge into `candidate_evaluations` and ride the role-agnostic `resolve_transition`
   T1→T3→T6 spine — the same path the utility_policy criterion uses. Which stages run always, and
   which are LLM-gated:
   - **`static_validation` — WIRED, DETERMINISTIC (always; 2026-07-18).** Before a candidate is
     scored, `_paper_candidate_evaluator` reconstructs the candidate `PromptSpec` from the append-only
     `prompt_evolution.jsonl` (keyed by `candidate_id`, the spec a text-only `GovernedPromptEntry`
     does not carry — closing this step's earlier residual verbatim) and calls
     `static_validation_failures` (`prompt_evolution.py:163`): placeholder-contract-vs-declared,
     hash discipline, template_ref/generation_mode/mutation_kind legality, size budget, lineage. A
     failure DROPS. When the log carries no matching record the stage is an explicit skip — never a
     fabricated pass.
   - **`constitutional_validation` — WIRED, DETERMINISTIC (always).** Two complementary reads, both
     keyed on the single authority `REQUIRED_CONSTRAINTS_BY_ROLE`:
     (a) *metadata side* — `constitutional_validation_failures` (`:327`) over the reconstructed spec:
     the declared `constitutional_constraints` carry the §5.4 clauses, provenance legality,
     no-instant-activation, and same-role separation (`:401-405`);
     (b) *byte side* — `role_instruction_constraint_failures` over the RESOLVED `role_instruction`
     bytes. The byte side is load-bearing because `PromptMutator.propose` force-injects the §5.4
     clauses into the metadata list (`:681-686`), so metadata can never catch a candidate whose
     instruction BYTES dropped the clause the mutator meta-prompt requires verbatim
     (`rqgm/prompt_mutator.md:22-24`). The byte side runs even without a reconstructed spec, so it
     gates every pending candidate.
   - **`schema_dry_run` — WIRED, LLM-GATED (runs only when an LLM reply seam is injected; 2026-07-18).**
     It renders the candidate prompt to a reply and checks it against the role's founding
     `output_schema` (`PAPER_FOUNDING_PROMPT_TABLE`) via `check_output_against_schema` — a
     non-deterministic, budgeted LLM call, INCOMPATIBLE with this deterministic (P2) evaluator's
     default path. It is therefore behind the injected `schema_dry_run_fn` seam
     (`(role, prompt_text, output_schema) -> reply_text`): it RUNS when the seam is wired (DROPPING a
     schema-nonconforming reply, terminal on failure) and is a **documented SKIP** when it is not
     (production — `cli/projects.py:219` — injects none). **A skip is never a fabricated pass**: the
     stage simply does not run and the candidate proceeds to the boards. The seam is deliberately
     distinct from `llm` (the mutator's prompt→str seam, which emits a mutated PROMPT, not a
     schema-checkable reply). Until an LLM reply source is wired in production, a candidate whose
     reply would not conform is still caught at RUNTIME (an unparseable reviewer verdict binarizes to
     a miss; a writer render failure fails open to the incumbent draft).
   - **`replay_evaluation` + `anchor_evaluation` — computed by the boards, not via the pipeline.** The
     dual objective (§5.4) is computed by `_candidate_replay_board` (the pooled `paper_self_preference`
     replay board) and `score_reviewer_on_anchor` (the held-out corpus board), emitted as the
     candidate's `replay_score` / `anchor_score` — never one number copied into both.
   - `anchor_evaluation` — **the asymmetry, at the CANDIDATE stage** — the `paper_reviewer`
     candidate is scored on agreement with the accept/reject anchor labels on a held-out sample
     (cases + utility policy owned by
     [04_anchor_utility_and_epoch_winners.md](04_anchor_utility_and_epoch_winners.md); ties favor
     the incumbent, `_case_evaluation` `metrics["ties_favor_incumbent"]=True` at `:834`). A
     `paper_writer` CANDIDATE has no held-out corpus of its own to be scored against (a candidate
     prompt has written no drafts yet), so its `anchor_evaluation` runs with an empty anchor set (an
     empty set is a zero-coverage pass, `:924–927`) and it climbs to `shadow` via
     `_no_basis_eval` (**renamed + re-specified 2026-07-17**; it was `_epoch_local_eval`, which
     fabricated `case_refs` sized to clear `replay_min_cases` and a `replay_score: 1.0`). The
     climb now rests on the **role-scoped `no_replay_basis` / `no_shadow_basis` waiver** recorded
     in doc [05](05_adversarial_self_preference.md) §5.5 and doc
     [04](04_anchor_utility_and_epoch_winners.md) §5.9 — **not** on a zero-coverage pass carried
     by synthetic refs. `_no_basis_eval` computes nothing and therefore reports nothing: boards
     `None`, counts `0`/`[]`, both absences DECLARED, and the two COUNT floors waived by role at
     the decision site with a note on the transition record. **This is NOT "the writer has no
     anchor"**: the writer's anchor is the Layer-0 claim gate's faithfulness of the ACTIVE
     writer's real drafts (doc 04 §5.1), which lands on the AnchorBoard and drives the SANCTION
     that opens the role — the channel a candidate cannot supply. T6's `_role_opening` guard is
     untouched, so the waiting shadow writer still adopts only on a real sanction. So: writer
     DRAFT winners are epoch-local (§5.6), writer PROMPT adoption is anchor-driven.
3. **Audit** (once per boundary, over both roles — not per-R). `GovernanceOrchestrator.audit_epoch(
   epoch_state=..., audit_log=ImmutableAuditLog.read(ckpt), component_registry=...,
   prompt_registry=..., candidate_prompts=<the step-1 candidates>, adversarial_replay_pool=...,
   budget_manager=...)` → `GovernanceReport` (`runtime.py:552–564`). **Step order is load-bearing
   and is the exploration precedent's, not an invention:** `runtime.py:548` mints this boundary's
   candidates *inside* `run_epoch_audit` **before** `audit_epoch` at `:552`, so the step-1
   candidates ride the report's `candidate_evaluations` into step 4 — which is why Audit sits
   *between* Validate and Adopt and not before Propose. This is the step that assesses
   `paper_writer`/`paper_reviewer` reliability from the §5.8 `review_record`s, assembles
   `EvidenceClerk` bundles, files `Auditor` motions against a captured reviewer, adjudicates them,
   scores candidates into `report.candidate_evaluations` (`governance/_pipeline.py:628–630`
   `evaluate_candidates`), and admits
   self-preference cases to the replay pool via `pool.admit` in its internal step 7
   (`_pipeline.py:653–662`; doc 05 §5.4). Gated by `rqgm.governance.enabled` and skipped under
   `governance_suspended` (`runtime.py:513–530`); fail-open — a failure degrades to `report=None`
   (see the step-4 note). The orchestrator itself is constructed by doc 01 §5.4 and inherited
   verbatim — this task adds no governance code.
4. **Adopt.** `build_adoption_request` (`:1122`) hands a fully-validated candidate to
   `RegistryTransitionEngine.resolve_transition` (`transition_engine.py:414`), which stamps the
   boundary-only T6 `shadow → probationary_active` adoption under `role_opening_available` +
   `one_adoption_per_role_per_boundary`. The kernel's `validate_transition` gates it. The demoted
   incumbent goes to `shadow` standby (never deleted), so regression at the next boundary reinstates
   it.

   > **Shadow standby — landed via a constitutional edit (wave 3c, 2026-07-16).**
   > Paper-role co-evolution is **PROMPT-level** (the mutator mints *unpaired*
   > `paper_reviewer_prompt_v2` candidates; the `paper_reviewer_v1` COMPONENT
   > persists and its active prompt changes v1→v2). Before wave 3c the "demoted
   > incumbent goes to shadow" promise was **not implementable**: the transition
   > table had NO `active → shadow` edge, so on adoption BOTH the incumbent and
   > successor prompts ended `active` and only latest-active-wins hid the
   > incumbent. The fix adds transition-table row **T21 (`active → shadow`)**,
   > the paper-role shadow-standby supersession edge (kernel-guarded to
   > `PAPER_SUPERSESSION_ROLES`; behavioral/utility roles keep their models),
   > emitted inside a paper-role T6 adoption
   > (`transition_engine._shadow_superseded_paper_prompt`). Result: exactly ONE
   > active prompt per paper role, the incumbent in reinstatable `shadow`
   > standby. This is the edit that re-pinned `CONSTITUTION_HASH`
   > (564a204dc694 → 6643c12a510e).

   The call carries the step-3 report — `governance_report` is a **required** keyword arg
   (`transition_engine.py:414–423`), so the sequence cannot be run without step 3:

   ```python
   # planned: the paper boundary's adopt call, mirroring the exploration
   # precedent verbatim (runtime.py:988-998 _run_epoch_boundary)
   engine.resolve_transition(
       epoch_state=st.epoch,
       governance_report=report,                 # ← the step-3 GovernanceReport
       candidate_evaluations=getattr(report, "candidate_evaluations", None) or (),
       components=st.components,
       prompts=st.prompts,
       status_history=engine.load_status_history(ckpt),
       governance_suspended=self.governance_suspended,
   )
   ```

   **NOTE — a missing audit silently disables ALL adoption.** `governance_report=None` does not
   raise: `resolve_transition` returns early with the note
   `no_governance_report: no state changes resolved` and simply re-emits the incumbent active set
   (`transition_engine.py:456–459`). Combined with step 3's fail-open posture, an unwired or failed
   audit degrades the whole boundary to a no-op *quietly* — the roles stay pinned at v1 and nothing
   co-evolves, with no error surfaced. This is why §11 requires a smoke test asserting the resolved
   transition carries **no** `no_governance_report` note: it is the only signal that distinguishes
   "governance ran and adopted nothing" from "governance never ran."

Cost is epoch-amortized and top-K-gated: full governance (adversarial + co-evolution) applies only
to `rqgm.governance.full_governance_only_on_top_k` (default **3**) drafts, reused verbatim
(cost model owned by [06_cost_control_and_budget.md](06_cost_control_and_budget.md) and
[../ari_rqgm/12_cost_control_and_context_budget.md](../ari_rqgm/12_cost_control_and_context_budget.md)).

**Degraded on-ramp.** When `rqgm.paper.prompt_evolution.enabled: false`, steps 1–2 are skipped
entirely and step 4 has no candidate to adopt: the two roles stay pinned at their founding v1
prompts for the whole run (best-of-N reviewed drafts with NO co-evolution — the cheap on-ramp,
analogous to the parent set's B4/B5 baselines). The roles are still *registered* (so scoring works)
but never evolve. This is the `rqgm.prompt_evolution.enabled=false` structural-inertness pattern
applied to the paper phase.

Step 3 is **orthogonally gated** on `rqgm.governance.enabled` (`runtime.py:513–530`), not on
`prompt_evolution.enabled` — the two knobs are independent by inheritance. So even on the cheap
on-ramp the audit still runs and still assesses `paper_reviewer_v1` from its §5.8 `review_record`s:
a self-preferring reviewer remains reliability-assessable and prosecutable even in a run where
nothing co-evolves. Only `rqgm.governance.enabled=false` removes the paper roles from the audit
network entirely, and that is the same switch that removes the exploration roles from it.

**Which stages run deterministically-always vs LLM-gated (2026-07-18).** The candidate-validation
stages Step 2 runs, and their execution condition:

| Stage | Wired? | Runs when |
|---|---|---|
| `static_validation` | yes | ALWAYS (deterministic P2), from the log-reconstructed spec; explicit skip if no log record |
| `constitutional_validation` (metadata + `role_instruction` bytes) | yes | ALWAYS (deterministic P2); the byte side runs even with no reconstructed spec |
| `schema_dry_run` | yes | ONLY when the `schema_dry_run_fn` LLM reply seam is injected; a documented SKIP (never a fabricated pass) when not — production injects none |
| `replay_evaluation` | yes | ALWAYS, via `_candidate_replay_board` (pooled `paper_self_preference` cases); ABSENT ⇒ role-scoped waiver |
| `anchor_evaluation` | yes | ALWAYS, via `score_reviewer_on_anchor` (held-out corpus); writer has no candidate corpus ⇒ `_no_basis_eval` |

`static_validation` + `constitutional_validation` were wired 2026-07-18 by reconstructing the
candidate `PromptSpec` from the append-only `prompt_evolution.jsonl` (keyed by `candidate_id`) — the
spec a text-only `GovernedPromptEntry` does not carry — and calling `static_validation_failures` /
`constitutional_validation_failures` verbatim before scoring. This CLOSES this section's earlier
"static_validation needs the candidate spec the evaluator does not hold" residual.

**Residual — `schema_dry_run` has no production LLM reply source (2026-07-18).** The stage is wired
behind the `schema_dry_run_fn` seam and runs whenever that seam is injected (proven by
`test_schema_dry_run_runs_only_with_an_llm_injected`), but `cli/projects.py:219` constructs
`PaperArchiveRuntime` with no seam, so in production it is an honest SKIP — never a fabricated pass.
Wiring a real LLM reply source puts a budgeted, non-deterministic call on the candidate path and is a
separate, explicit decision — the same CLASS of decision as §5.8's agent-as-judge `score_fn` render,
which was taken on 2026-07-19 (landed opt-in behind `rqgm.paper.reviewer.agent_as_judge.enabled`);
this one has NOT been taken, so `schema_dry_run` remains an honest SKIP in production. Until then a
candidate whose reply would not conform to the founding `output_schema` is
caught at RUNTIME instead: an unparseable reviewer verdict binarizes to a miss
(`paper_reviewer_agreement`), so a schema-breaking reviewer scores badly on the boards and is not
adopted; a writer render failure fails open to the incumbent draft. So the accurate statement is
"the deterministic stages (static + constitutional) run monotonically over every paper candidate,
and schema_dry_run runs when an LLM reply seam is injected" — not the original "the six stages run
monotonically" (which claimed a pipeline object that is never instantiated).

## 6. Data structures / schema changes

### 6.1 Frozen-table edits (constitutional; all additive)

| Table | File / symbol | Edit |
|---|---|---|
| `EVOLVABLE_ROLES` | `ari/rqgm/events.py:57` | append `"paper_writer"`, `"paper_reviewer"` |
| `_EVOLVABLE_ROLES` | `ari/rqgm/kernel_rules.py:115` | append the same two (→ institutional + meta grants via `_build_capability_matrix`) |
| `CONTEXT_VIEW_WHITELISTS` | `ari/rqgm/kernel_rules.py:234` | `paper_writer` row **unchanged** (unified); add `paper_reviewer` → `{draft_manuscript, verified_context, science_data, reference_context}` |
| `REQUIRED_CONSTRAINTS_BY_ROLE` | `ari/rqgm/prompt_spec.py:52` | add `paper_writer` (anti-fabrication) and `paper_reviewer` (do-not-override-gate, do-not-modify-frontier) |
| `PAPER_FOUNDING_PROMPT_TABLE` | `ari/rqgm/prompt_spec.py` | `paper_writer_prompt_v1` (`rqgm/paper_writer`, freeform), `paper_reviewer_prompt_v1` (`rqgm/paper_reviewer`, json_object). **LANDED CORRECTION** (was "append to the shared `FOUNDING_PROMPT_TABLE`"): the rows live in a SEPARATE **paper-mode-gated** table threaded through `founding_registration_events(include_paper=...)`, so an exploration boot is byte-identical (the shared table stays frozen). Wave 3c adds a third gated row here, `adversary_paper_self_preference_prompt_v1` (doc 05 §5.6). |
| `PAPER_FOUNDING_COMPONENT_TABLE` | `ari/rqgm/prompt_spec.py` | `paper_reviewer_v1`, `paper_writer_v1` (sorted by `component_id`), also gated. Wave 3c adds `adversary_paper_self_preference_v1` (doc 05 §5.6). |
| `CONSTITUTION_HASH` pin | `tests/test_rqgm_kernel.py` | recompute + re-pin + amendment comment. The plan-03 roles/whitelist re-pin to 564a204dc694; wave 3c's T21 edge (below) re-pins again to **6643c12a510e**. The paper founding rows do NOT ride the pin (they are not in `_canonical_rules_payload`). |
| `TRANSITION_TABLE` | `ari/rqgm/transition_rules.py` | plan-03 **no change** (topology-agnostic, §5.6). **Wave 3c amends this**: T21 (`active → shadow`) is added — the paper-role shadow-standby supersession edge that fixes the incumbent-stays-active adoption bug (§5.9). It IS constitutional (feeds `constitution_hash`). |

### 6.2 New committed prompt templates

Two founding templates lifted from the skill, passing the ../ari_rqgm/07 §5.2 four-layer new-prompt
checklist (extraction snapshot, provenance hash, contract snapshot, `check_prompts.py`):

- `ari-core/ari/prompts/rqgm/paper_writer.md`   — freeform LaTeX writer instruction.
- `ari-core/ari/prompts/rqgm/paper_reviewer.md` — JSON reviewer contract with `accept_recommendation`.

These are the SOLE `active`-on-creation founding bodies for the two roles; every later prompt enters
at `candidate` and climbs the six-stage lifecycle.

### 6.3 New context-view symbols

`PAPER_REVIEWER_VIEW_ROLE`, `PAPER_REVIEWER_FIELDS`, `build_paper_reviewer_context` in
`ari/rqgm/context_views.py` (§5.3). `build_paper_writer_context` already exists (`:205`) and is
unchanged — promotion adds no new writer builder.

### 6.4 No new checkpoint files owned here

The two roles co-evolve inside the parent set's existing logs — `prompt_evolution.jsonl`,
`prompt_specs.json`, `rqgm_transitions.jsonl`, `rqgm_registry.json` (all already `META_FILES` /
`_INTERNAL_JSON_NAMES`). The paper-phase provenance files `paper_archive_state.json` and
`paper_draft_archive.jsonl` are registered by docs 01/02, not here. This task creates **no** new
checkpoint-root file.

The §5.8 `review_record` rows are **not** an exception: they ride the already-registered
`rqgm_audit.jsonl` (`ari/paths.py:78` `META_FILES`), which the parent set's `ImmutableAuditLog`
already owns and which every adversarial record already flows into via `AdversarialRound._log_all`
(`adversarial/round.py:290–302`). New *rows* of an existing type in an existing file — no new file,
no new schema, no `paths.py` edit.

## 7. API / class changes

All new code is data appended to existing `ari-core/ari/rqgm/` modules plus one new context builder;
nothing is exported via `ari.public.*` (no public-API contract-snapshot churn).

| Symbol | Location (planned) | Contract |
|---|---|---|
| `paper_writer` (role) | `ari/rqgm/events.py:EVOLVABLE_ROLES`; `ari/rqgm/kernel_rules.py:_EVOLVABLE_ROLES` | Full evolvable writer role; institutional + meta grants; unifies the existing `paper_writer` context whitelist. |
| `paper_reviewer` (role) | same two tables | New evolvable evaluator role; institutional + meta grants; new context view. |
| `PAPER_REVIEWER_VIEW_ROLE`, `PAPER_REVIEWER_FIELDS` | `ari/rqgm/context_views.py` | Aliased from the constitution-pinned `CONTEXT_VIEW_WHITELISTS["paper_reviewer"]` (one source, no drift). |
| `build_paper_reviewer_context(draft_manuscript, verified_context, science_data, reference_context)` | `ari/rqgm/context_views.py` | Deterministic projection whose key set == `PAPER_REVIEWER_FIELDS`; same-role isolation constructive. |
| `paper_writer_prompt_v1`, `paper_reviewer_prompt_v1` | `ari/rqgm/prompt_spec.py:FOUNDING_PROMPT_TABLE` | Founding `active` v1 specs; `prompt_hash == load_versioned(key)[1]`. |
| `paper_writer_v1`, `paper_reviewer_v1` | `ari/rqgm/prompt_spec.py:FOUNDING_COMPONENT_TABLE` | Founding institutional components, one prompt each. |
| `writer_prompt_override: str = ""` | `ari-skill-paper/src/server.py:write_paper_iterative`, `:paper_refine` | Additive, default-empty; `""` ⇒ load `paper_writer.md` (linear byte-identical); non-empty ⇒ use the governed text. The ONLY skill change. |

Changed (existing) code — all additive:

- `ari/rqgm/events.py`, `ari/rqgm/kernel_rules.py`, `ari/rqgm/prompt_spec.py`,
  `ari/rqgm/context_views.py` — table appends + one builder (above).
- `ari-skill-paper/src/server.py` — the two optional override args (§5.8). No import of `ari.rqgm`.
- `ari-core/tests/test_rqgm_kernel.py` — the `_EXPECTED_CONSTITUTION_HASH` re-pin.
- No CLI command/flag change; no `ari.public.*` change; no MCP contract-snapshot regeneration beyond
  the new skill tool arguments (whose contract snapshot lives in the skill's own suite, updated as a
  reviewed additive diff).

## 8. Migration / compatibility

Preserve-existing-behavior policy (normative):

1. **`linear` is identity.** Under the default paper mode, no `PaperArchiveRuntime` is constructed,
   `rqgm/paper_writer.md` / `rqgm/paper_reviewer.md` are never loaded, no founding paper spec is
   built, `writer_prompt_override` is never set, and the `ari-skill-paper` subprocess is
   byte-identical to today. The constitution amendment is inert on the paper path when the mode is
   off (the tables exist but no paper component is registered).
2. **Exploration mode unaffected.** Adding two evolvable roles does not touch any exploration role.
   The exploration `simple_bfts`/`ari_rqgm` behavior is unchanged; `test_rqgm_kernel.py`'s existing
   exploration fixtures still pass once the single hash pin is updated.
3. **Skill backward-compat.** The two new skill arguments are keyword-only with empty defaults;
   every existing caller (pipeline, tests, `linear`) omits them and gets identical behavior. The
   skill imports zero `ari.rqgm` — the plan-set invariant that we do not govern the subprocess
   holds.
4. **Whitelist non-widening.** The `paper_writer` view stays exactly `{verified_context,
   science_data, claim_registry}` — promotion adds capability/transition presence, not context.
   `paper_reviewer`'s view is a fresh, minimal four-field set. No governed role gains raw-transcript
   or retired-prompt-text access (matrix grants forbid it).
5. **Claim gate untouched.** No governed role wraps or overrides the Layer-0 claim-evidence gate;
   the reviewer's constraint clause is a candidate-admission check, not a gate hook. Handoff stays
   doc 07's.
6. **Additive `CONSTITUTION_HASH`.** The re-pin is a one-line reviewed diff; `record_constitution_hash`
   writes the new value additively into `meta.json` (no rewrite of old checkpoints — old runs have
   no paper roles and no paper archive).
7. **Degraded on-ramp is byte-cheap.** `rqgm.paper.prompt_evolution.enabled=false` registers the two
   roles but never mutates them — the roles' cost is one writer render + one reviewer score per
   draft, i.e. ≈ today's per-draft cost (doc 06).

## 9. Tests

**Unit** (extend `ari-core/tests/test_rqgm_kernel.py` and a new
`ari-core/tests/test_rqgm_paper_roles.py`, listed in `ari-core/tests/README.md` for the readme-sync
gate):

- `paper_writer` and `paper_reviewer` are in `EVOLVABLE_ROLES` **and** have institutional + meta
  rows in `CAPABILITY_MATRIX` (extend `test_all_evolvable_roles_in_matrix`,
  `test_rqgm_kernel.py:734–742`).
- Neither role has `("write","registry")` nor `("activate","candidates")` in any tier;
  `validate_capability` denies both (`CK-ACC-001`).
- `CONTEXT_VIEW_WHITELISTS["paper_writer"]` is unchanged; `["paper_reviewer"]` ==
  `{draft_manuscript, verified_context, science_data, reference_context}`.
  `build_paper_reviewer_context` returns exactly that key set and `validate_context_scope(
  "paper_reviewer", view)` passes; adding a foreign key flags `CK-CTX-001`.
- `constitution_hash()` equals the new pin (all five read sites), and re-pinning is proven necessary
  by a "hash differs from `4fa36f2bd302`" assertion.
- Founding: `build_founding_specs()` includes `paper_writer_prompt_v1` / `paper_reviewer_prompt_v1`
  with `status="active"`, `prompt_hash == load_versioned("rqgm/paper_writer")[1]` (resp. reviewer);
  `founding_component_payloads()` includes `paper_writer_v1` / `paper_reviewer_v1`.
- `REQUIRED_CONSTRAINTS_BY_ROLE`: a `paper_reviewer` candidate whose resolved `role_instruction`
  lacks "Do not override the claim-evidence hard gate." is DROPPED by `_paper_candidate_evaluator`
  before scoring (`role_instruction_constraint_failures`; enforcement is live as of 2026-07-17 —
  see §5.9 step 2, wired into the candidate evaluator rather than the never-instantiated
  `CandidateValidationPipeline`), proven end-to-end by
  `test_a_constitutionally_illegal_writer_candidate_never_reaches_active` +
  `test_candidate_missing_a_54_clause_is_dropped_before_scoring`; a `paper_reviewer` component
  authoring a `paper_reviewer` candidate is same-role-flagged by `constitutional_validation_failures`
  (`:401-405`).
- **Deterministic candidate-validation stages (wired 2026-07-18, §5.9 step 2).** The stage checks
  run directly over every pending paper candidate before scoring:
  - `static_validation`: a candidate whose log-reconstructed spec declares a placeholder its template
    bytes lack (drift) is DROPPED, while a mutator-faithful spec still scores —
    `test_candidate_failing_static_validation_is_dropped_before_scoring` +
    `test_constitutionally_clean_candidate_with_a_recorded_spec_still_adopts`.
  - `constitutional_validation` (metadata side): a candidate whose recorded `constitutional_constraints`
    dropped a §5.4 clause is DROPPED even when its bytes still carry it —
    `test_candidate_failing_constitutional_metadata_validation_is_dropped`.
  - `schema_dry_run` (LLM-gated): skipped (never a fabricated pass) with no seam, and RUNS — dropping a
    non-conforming reply, passing a conforming one — only when the `schema_dry_run_fn` seam is injected
    — `test_schema_dry_run_runs_only_with_an_llm_injected`.

**Regression (linear unchanged):**

- Full existing ari-core suite green after the single hash re-pin (CI `refactor-guards.yml`).
- Skill: `write_paper_iterative(...)` / `paper_refine(...)` with `writer_prompt_override=""` produce
  byte-identical output to the pre-change tool (golden compare in the skill's suite); the skill
  imports no `ari.rqgm`.
- Prompt-snapshot/extraction/provenance gates green with the two lifted templates added (four-layer
  checklist).

**Smoke (`rqgm_archive` co-evolution):**

- A one-epoch paper-archive run (stubbed LLM) registers both roles, drives the writer via
  `writer_prompt_override`, scores drafts with the governed reviewer (not `review_compiled_paper`),
  and at the boundary adopts at most one `paper_writer` and one `paper_reviewer` candidate through
  `RegistryTransitionEngine` (T6), kernel-validated.
- `rqgm.paper.prompt_evolution.enabled=false`: both roles stay at v1, no candidate is minted, best-of-N
  reviewed selection still runs.

**The reviewer is inside the audit network (§5.8, P3):**

- After a one-epoch `rqgm_archive` smoke run, `build_reliability_entries` yields an entry for
  `paper_reviewer_v1` with `observation_count > 0`, `insufficient_data=False`, and a **non-None**
  `reliability_score` — i.e. the founding row is operative, not nominal.
- Every appended `review_record` carries the full `ENVELOPE_FIELDS` set (`kernel_rules.py:58–68`)
  with `role="paper_reviewer"`, `component_id="paper_reviewer_v1"`, and a `prompt_hash` equal to the
  epoch's frozen active reviewer hash (within-epoch freeze holds across the whole archive round).
- A synthetically mis-calibrated reviewer double (`confidence` far from `outcome_score`) drives
  `reliability_score` below `RELIABILITY_FLOOR` (0.4) so `classify_target` returns `CLASSIFY_FILE`,
  and the resulting `Auditor` motion is accepted by `resolve_transition`. (Do **not** assert the
  validated-attack route: nothing writes `target_component_id` today — that is a parent-05 gap, doc
  05 R7, not this task's.)
- Same-role exclusion: an evidence bundle built *against* `paper_reviewer_v1` excludes that
  component's own `review_record`s with reason `same_role_source` (`_evidence.py:97–103`) — the
  records inform reliability, never admissibility.
- No new file: the rows land in the existing `rqgm_audit.jsonl`; the checkpoint-root file set is
  byte-identical to doc 01/02's registration (§6.4).

**The boundary runs Propose → Validate → Audit → Adopt (§5.9, P4):**

- The smoke boundary calls `GovernanceOrchestrator.audit_epoch` **before** `resolve_transition`, and
  the resolved `EpochTransition.notes` contains **no** `no_governance_report` note — the regression
  that catches a silently unwired audit.
- Negative control: with the orchestrator stubbed to return `None`, `resolve_transition` returns
  early with note `no_governance_report: no state changes resolved` (`transition_engine.py:456–459`)
  and **zero** adoptions resolve, while no exception is raised — pinning the silent-disable failure
  mode so it can never be mistaken for "nothing was worth adopting."
- An impeachment motion against a scripted always-accept `paper_reviewer` double (doc 07 PI3) is
  filed and adjudicated within the step-3 audit, and the resulting recommendation is resolved by
  step 4 into a sanction transition rather than dropped.

**Resume:**

- A run co-evolved to `paper_writer_prompt_v2` / `paper_reviewer_prompt_v2` resumes with the
  persisted active hashes (registry checkpoint-first); no mid-epoch prompt flip; within-epoch freeze
  holds.

## 10. Risks

- **R1 — Hash-pin drift.** Forgetting the `CONSTITUTION_HASH` re-pin fails every kernel test loudly.
  *Mitigation:* the re-pin is a deletion-criteria item and the amendment comment names this task; the
  five read sites consume one constant.
- **R2 — Role-string typos.** `"paper_reveiwer"` in one table but not another leaves capability
  lookups `CK-ACC-001`-blocked (the `failure_summary_compressor` bug class). *Mitigation:*
  `test_all_evolvable_roles_in_matrix` parity test + a whitelist/founding-table parity test over the
  literal role strings.
- **R3 — Skill override widens the skill's surface.** The optional argument could be misread as
  "governing the subprocess." *Mitigation:* it is a plain input string with an empty default; the
  skill still evolves nothing and imports no `ari.rqgm`; a skill test asserts `""` ⇒ byte-identical.
- **R4 — Writer/reviewer co-drift.** Epoch-local writer DRAFT winners can co-drift with a lenient
  reviewer. *Mitigation (strengthened, 2026-07-16):* the writer's own claim-gate faithfulness anchor
  (doc 04 §5.1) is reviewer-independent, so a writer that pleases a lenient reviewer by overclaiming
  is sanctioned by the gate regardless of what the reviewer thinks; plus the `paper_self_preference`
  adversary (doc 05) + the reviewer's anchor grounding (doc 04) bound the reviewer; the writer's
  anti-fabrication constraint (§5.4) is a hard admission gate; ties favor the incumbent.
  *Residual:* the writer sanction rides the self-preference round, so it needs an over-accepted
  anchor case to fire — a lenient reviewer that over-accepts nothing is the one configuration in
  which the co-drift guard is silent.
- **R5 — Two paper roles vs one reviewer role confusion.** Reusing `reviewer` for manuscripts would
  conflate two anchor sets/utility policies. *Mitigation:* `paper_reviewer` is deliberately distinct
  (§5.3), documented, and its context view/rubric differ.
- **R6 — Skill's internal reviewer still runs.** `write_paper_iterative`'s `academic_reviewer.md`
  intra-tool loop is not the archive scorer, which could confuse readers. *Mitigation:* §5.8 states
  the boundary explicitly — internal loop = mechanical hands, governed `paper_reviewer` = archive
  scorer; both are documented, and the archive score comes only from the governed role.

## 11. Completion criteria

This task is complete when all of the following hold:

1. **Two roles registered** — `paper_writer` (promoted) and `paper_reviewer` (new) are in
   `EVOLVABLE_ROLES` and `_EVOLVABLE_ROLES`, each with institutional + meta capability rows and no
   registry-write/candidate-activate grant (§5.2).
2. **Context views defined** — `paper_writer`'s whitelist is unified unchanged; `paper_reviewer`'s
   `{draft_manuscript, verified_context, science_data, reference_context}` whitelist +
   `build_paper_reviewer_context` exist and are kernel-scope-checked, with same-role isolation stated
   (§5.3).
3. **Constraints + founding tables** — `REQUIRED_CONSTRAINTS_BY_ROLE`, `FOUNDING_PROMPT_TABLE`, and
   `FOUNDING_COMPONENT_TABLE` carry the two roles; the two lifted templates exist under
   `ari/prompts/rqgm/` and pass the four-layer checklist (§5.4, §5.5).
4. **Hash re-pinned** — `CONSTITUTION_HASH` recomputed and re-pinned in `test_rqgm_kernel.py` with an
   amendment comment (§5.7).
5. **Prompt-driven executor contract** — the additive `writer_prompt_override` seam is specified,
   `linear` byte-identity is preserved, and the reviewer-scores-in-ari-core (never
   `review_compiled_paper`) decision is written down (§5.8).
6. **Co-evolution reuses the parent machinery** — writer/reviewer co-evolution is expressed entirely
   via `PromptMutator` / the candidate-validation stage checks called DIRECTLY as pure functions
   (`static_validation_failures` → `constitutional_validation_failures` + the byte-side
   `role_instruction_constraint_failures` → the LLM-gated `check_output_against_schema`, in the
   monotonic order; the `CandidateValidationPipeline` OBJECT is instantiated nowhere) /
   `build_adoption_request` / `RegistryTransitionEngine`, with the two roles' anchor asymmetry
   (reviewer → accept/reject corpus;
   writer → Layer-0 claim-gate faithfulness) routed to doc 04, the top-K +
   `max_total_candidates_per_epoch` budgets reused, and the `prompt_evolution.enabled=false` on-ramp
   defined (§5.9).
7. **The governed reviewer is reliability-assessable** — each `paper_reviewer` score emits a
   `review_record` into the epoch's `rqgm_audit.jsonl` slice, so `paper_reviewer_v1` has
   `observation_count > 0` and a non-None `reliability_score`, its registration is operative rather
   than nominal, and the `FOUNDING_COMPONENT_TABLE` "the runtime stamps it" contract
   (`prompt_spec.py:219–231`) holds. The records feed reliability, and are same-role-excluded from
   any bundle against the reviewer itself (§5.8).
8. **The boundary is audited, not just adopted** — the paper boundary runs
   Propose → Validate → Audit → Adopt in the `runtime.py:548–564` / `:966–1000` order; an impeachment
   motion against a scripted always-accept `paper_reviewer` (doc 07 PI3) is filed and adjudicated;
   and a smoke test asserts the resolved transition carries **no** `no_governance_report` note, so a
   missing audit cannot silently disable all adoption (§5.9).
9. Downstream tasks consume without re-opening: doc 04 (anchor cases feed
   `anchor_evaluation`; `reference_context`), doc 05 (`paper_self_preference` attacks these two
   roles), doc 06 (co-evolution cost), doc 07 (best-draft handoff; the reviewer never overrides the
   gate).

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

- `paper_writer` (promoted) and `paper_reviewer` (new) are implemented in all four constitutional
  tables with the `CONSTITUTION_HASH` re-pinned, and the promotion note in
  `kernel_rules.py`/`test_rqgm_kernel.py` (2026-07-15 "deliberately NOT EVOLVABLE") is superseded and
  updated.
- The two founding templates exist under `ari/prompts/rqgm/`, pass the four-layer new-prompt
  checklist, and their founding specs are `active`-on-creation with verifiable hashes.
- The `writer_prompt_override` seam is implemented with a skill test proving `""` ⇒ byte-identical
  `linear` behavior and the skill importing no `ari.rqgm`.
- Co-evolution smoke tests (adopt at most one candidate per role per boundary) and the
  `prompt_evolution.enabled=false` on-ramp test pass.
- Same-role isolation for `paper_reviewer` is covered (constructive + candidate-authoring flag).
- The constitutional-amendment rationale (promote-in-place, distinct reviewer role, skill-as-hands)
  is migrated to the permanent RQGM roles/kernel doc under `docs/`.

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

- [ ] `paper_writer` promoted to `EVOLVABLE_ROLES` + capability matrix (institutional + meta);
      `paper_reviewer` added likewise.
- [ ] `CONTEXT_VIEW_WHITELISTS["paper_reviewer"]` + `build_paper_reviewer_context` implemented;
      `paper_writer` whitelist unified unchanged.
- [ ] `REQUIRED_CONSTRAINTS_BY_ROLE`, `FOUNDING_PROMPT_TABLE`, `FOUNDING_COMPONENT_TABLE` carry both
      roles; the two lifted `ari/prompts/rqgm/*.md` templates pass all four snapshot layers.
- [ ] `CONSTITUTION_HASH` recomputed + re-pinned in `test_rqgm_kernel.py` with amendment comment;
      the superseded 2026-07-15 "deliberately NOT EVOLVABLE" note updated.
- [ ] `writer_prompt_override` added to `write_paper_iterative`/`paper_refine` (default-empty,
      linear byte-identical, no `ari.rqgm` import in the skill).
- [ ] Co-evolution via reused `PromptMutator` / the candidate-validation stage checks called
      directly (`static_validation_failures` → `constitutional_validation_failures` +
      `role_instruction_constraint_failures` → LLM-gated `check_output_against_schema`; the pipeline
      object is not instantiated) / `RegistryTransitionEngine` smoke-tested; anchor asymmetry
      (reviewer anchored, writer epoch-local) wired to doc 04.
- [ ] Each governed `paper_reviewer` score appends a `review_record` (existing type, existing
      `rqgm_audit.jsonl`) with the full envelope; `build_reliability_entries` reports
      `observation_count > 0` + non-None `reliability_score` for `paper_reviewer_v1`; same-role
      exclusion from bundles against it is covered.
- [ ] The boundary sequence is Propose → Validate → **Audit** → Adopt, with `audit_epoch` feeding
      `resolve_transition(governance_report=…, candidate_evaluations=…)`; the `no_governance_report`
      silent-disable path is pinned by a negative-control test.
- [ ] `rqgm.paper.prompt_evolution.enabled=false` on-ramp (roles registered, never evolve) tested,
      including that step 3 still audits under `rqgm.governance.enabled=true`.
- [ ] Amendment rationale migrated to the permanent RQGM roles/kernel guide under `docs/`.
