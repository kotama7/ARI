# Task 14: Governed Utility Evolution

> **Status**: planned · **Depends on**: 00, 02, 04, 07, 09, 10 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

## 1. Purpose

The defining claim of Constitutional ARI-RQGM is that the search is tree-structured **and that at
each epoch boundary the entire score — the utility function itself — is rewritten**. The shipped
`ari-core/ari/rqgm/` package implements exactly one half of that sentence.

The **consequence** half is built and live. `frontier_repair.py:99-101` declares
`INVALIDATE_ROLES = {"generator", "router", "utility_policy"}` because "the node's very direction
(generator/router) or its score's policy (`utility_policy`) came from the retired prompt — **no
recompute can launder that**"; `frontier_repair.py:86,694` stamps the invalidated nodes with
`UTILITY_INVALIDATED_REASON`; `UtilityRecord` is a live record type
(`adversarial/engine.py:41,986`) whose `frozen_policy` carries "the by-value frozen weights …
in every UtilityRecord" (`adversarial/engine.py:947-948`) precisely so that a policy change leaves
old scores reconstructible rather than silently re-interpreted; and `utility_policy` is already
inside the deterministic epoch identity (`state.py:270`, hashed at `state.py:276-287`).

The **cause** half does not exist:

- `state.py:313-337` — `capture_utility_policy(cfg)` reads only the **static resolved cfg**. The
  frozen policy is therefore byte-identical in every epoch of a run and `utility_policy_hash` is a
  permanent constant. Its own docstring says so: "In v1 the frozen policy is constant across epochs
  within a run (status quo B-17); per-epoch re-weighting is a Task 10/13 decision"
  (`state.py:318-320`).
- **No transition rule targets utility, weight, or axis.** The T1–T19 table
  (`transition_rules.py:77-151`) is complete and closed, and nothing in it can rewrite a score.
- `utility_policy` is in **neither** `EVOLVABLE_ROLES` (`events.py:57-68`) **nor** `FIXED_ROLES`
  (`events.py:73-77`), so it is in neither half of `ROLES` (`events.py:79`) — a role limbo. The
  frontier-repair engine, the `UtilityRecord` envelope and the epoch fingerprint all name a role
  that the vocabulary does not contain.

The gap is not paper-specific and not adversarial-loop-specific: with a constant policy hash, the
retirement that `frontier_repair` is waiting for is never emitted, and **the exploration phase
violates the rewrite too**. This is the fourth unwired seam in the package — after founding
registration, boundary candidate generation, and the meta invoker — and like those it is fixed
**once, here, at the parent level**. The paper-archive set inherits it topology-agnostically and
builds no local utility machinery
([../ari_rqgm_paper/04_anchor_utility_and_epoch_winners.md](../ari_rqgm_paper/04_anchor_utility_and_epoch_winners.md)).

This task designs the cause half: the governed object, its proposer, its adoption edges, its
constitutional legality rules, and the one-line seam in `freeze_epoch` where an adopted policy
becomes the epoch's frozen policy.

## 2. Scope

- Resolving the role limbo: `utility_policy` and the reserved-but-frozen `policy_mutator`
  (`meta_rules.py:103-108`) enter `EVOLVABLE_ROLES` and the capability matrix.
- The governed object: how the PromptSpec lifecycle accommodates a **policy-dict spec whose
  `prompt_hash` IS `utility_policy_hash`** (§5.3 decision), including its founding registration,
  its write-once body store, and its `source.kind`.
- `PolicyMutator` — the boundary proposer (a `PromptMutator` analog, `prompt_evolution.py:495-508`)
  that emits utility-policy candidates and nothing else.
- Adoption edges: the T-table rules the `utility_policy` role rides, and the guards that apply.
- `ConstitutionalKernel` validation of what a **legal** utility policy is: weight bounds and
  normalisation, `composite` / `frontier_score` membership in the allowed sets, the capability
  matrix row, and the `constitution_hash` re-pin (`kernel_rules.py:292-304`).
- **The core change**: `capture_utility_policy` reads the **adopted** policy from the registry,
  falling back to `cfg` at epoch 0 and under `simple_bfts`.
- Closing the cause→consequence circuit: the two colliding "policy hashes" (§5.8).
- Explicitly **overturning invariant I-11** ("axes frozen per run") and enumerating every plan that
  relies on it, with what each must now say (§5.10).
- Config keys (`rqgm.utility_evolution.*`) and their one schema home.

## 3. Non-goals

- No implementation in this task plan (design only; implementation follows the plan and is a
  deletion-criteria item).
- **No re-litigation of score comparability.** The comparability apparatus already exists — the
  `INVALIDATE_ROLES` path (`frontier_repair.py:96-101`) and the by-value `frozen_policy`
  (`adversarial/records.py:616-618`, `adversarial/engine.py:947-948`). This task **cites** it and
  wires the cause into it; it does not rebuild it and does not add a second recompute path.
- **No removal or weakening of `MetricSpecWeightCap`** (`meta_evolution.py:1242-1294`). It forbids
  *ungoverned* weight smuggling and stays correct verbatim (§5.9).
- No change to `simple_bfts`. Under the default mode nothing here is imported, constructed, or
  written (01 §8.1 identity policy).
- No new BFTS strategy, no new composite formula, no new frontier-score kind. The candidate space is
  exactly the closed sets the typed config already declares
  (`config/__init__.py:106-110,224-228`).
- No re-scoring of nodes under the new policy. A rewrite **invalidates**; it never re-weights old
  scores in place (`10_frontier_repair_and_selective_erasure.md`:515-518 "this task must not
  silently re-weight" survives verbatim).
- No paper-local utility evolution. The paper phase gains this by inheriting the parent path
  (§5.11).
- The validated-attack → impeachment chain is **not** this task's problem; it is Task 15's.
- No new CLI command/flag and no `ari.public.*` symbol ⇒ no contract-snapshot regeneration (01 §4
  budget decision).

## 4. Existing ARI touchpoints

All paths repo-relative. Verified against branch `RQGM` (ari-core v0.9.1).

| Touchpoint | File / symbol | Why it matters here |
|---|---|---|
| **The absent cause** | `ari-core/ari/rqgm/state.py:313-337` — `capture_utility_policy(cfg)` | Reads only `cfg.evaluator.composite/axis_weights` and `cfg.bfts.frontier_score/depth_penalty_lambda/ucb_c`; `policy["utility_policy_hash"] = hash12(canonical_json(policy))` (line 336). Static cfg ⇒ constant hash ⇒ no retirement ever fires. Its docstring defers per-epoch re-weighting to "a Task 10/13 decision" (lines 318-320) — this task is that decision. **The single line this plan changes** is line 368. |
| **The freeze seam** | `ari-core/ari/rqgm/state.py:340-373` — `freeze_epoch(registries, cfg, …)` | Line 366-367 already reads `registries.components.active_set()` / `registries.prompts.active_prompt_hashes()`; line 368 calls `capture_utility_policy(cfg)` **without** `registries`. The adopted policy is one argument away. |
| **The boundary transaction** | `ari-core/ari/rqgm/store.py:505-547` — `run_boundary` | Lines 530-538 apply `registry_events` to registry **copies** and build a `tentative` state; line 539 calls `freeze_epoch(tentative, cfg, …)`. The new epoch is frozen over the **post-transition** registries — so an adopted policy is in force for the next epoch by construction, with zero new plumbing. `open_epoch` (lines 462-503) is the epoch-0 twin. |
| **The live consequence** | `ari-core/ari/rqgm/frontier_repair.py:96-101` `INVALIDATE_ROLES`; `:86` `UTILITY_INVALIDATED_REASON`; `:90-94` `_ROLE_STALE_REASONS`; `:694` the flag call | Already treats a retired `utility_policy` as unlaunderable. Waiting for a retirement that today cannot exist. |
| **The retirement→repair join** | `ari-core/ari/rqgm/frontier_repair.py:600-611`, `:223-228`, `:258-264` | `retired_hashes` = `{e["prompt_hash"] for e in transition.retirements}`; `direct` = records whose **`prompt_hash`** is in that set; a `direct` record whose `role ∈ INVALIDATE_ROLES` invalidates its node. The join key is a record's `prompt_hash` — §5.8 is about making the right value land there. |
| **Retirement events** | `ari-core/ari/rqgm/transition_engine.py:580-591` | Each committed retirement is audited with `component_id` / `prompt_id` / `prompt_hash` / `role` — everything the repair engine needs, for any role. |
| **Repair ordering** | `ari-core/ari/rqgm/runtime.py:1014-1019` | Frontier repair runs "strictly after the committed apply and strictly before the boundary window closes (main thread, no node in flight)". A policy rewrite's invalidation lands in the same window as a prompt retirement's — no new ordering rule. |
| **Role vocabulary (the limbo)** | `ari-core/ari/rqgm/events.py:57-68` `EVOLVABLE_ROLES`, `:73-77` `FIXED_ROLES`, `:79` `ROLES` | `utility_policy` is in neither. `ACTIVE_STATUSES` (`:51`) is what makes a registry entry part of the frozen active set. |
| **Reserved proposer name** | `ari-core/ari/rqgm/meta_rules.py:99-108` — `META_FROZEN_ROLES` includes **`policy_mutator`** | "Reserved NAMES only: they are not in the Task 02 role vocabulary yet, so they cannot be registered — **a later task extends `ari.rqgm.events.ROLES` when they gain implementations**." Task 14 is that later task; the proposer's name is not invented here, it is un-frozen. `META_EVOLVING_ROLES` (`:92-97`) is where it lands. |
| **Capability matrix (the trap)** | `ari-core/ari/rqgm/kernel_rules.py:115-134` — `_EVOLVABLE_ROLES` | A **second copy** of the evolvable-role list, with a standing amendment note: `failure_summary_compressor` was in `events.EVOLVABLE_ROLES` but missing here, so "every capability lookup for the role was CK-ACC-001-blocked in every tier". Adding a role to `events.py` without adding a matrix row is a known, already-committed failure mode. |
| **Constitution hash** | `ari-core/ari/rqgm/kernel_rules.py:257-289` `_canonical_rules_payload`, `:292-304` `constitution_hash`; pin at `ari-core/tests/test_rqgm_kernel.py:69` | Covers the transition table, capability matrix, severity map and whitelists. Any table this task touches re-pins `_EXPECTED_CONSTITUTION_HASH` (asserted in 6 places: `test_rqgm_kernel.py:726,728,729,822,1056,1154`). Precedent for a reviewed amendment + re-pin: the `paper_writer` note at `kernel_rules.py:224-233`. |
| **Epoch invariance check** | `ari-core/ari/rqgm/kernel.py:538-589` — `validate_epoch_invariance`; CK-EPO-001 at `:579-587` | `frozen = set(epoch["active_prompt_hashes"].values())`; any record whose `prompt_hash` is outside it is CK-EPO-001. The moment `utility_policy` joins the active prompt hashes, every `UtilityRecord` must carry **that** hash or warn — the forcing function behind §5.8. |
| **The transition table** | `ari-core/ari/rqgm/transition_rules.py` (T1–T20), `EMERGENCY_EDGE` | Keyed by `(from_status, to_status)`; every row is role-agnostic EXCEPT **T20** (`active→retired`, §5.5), the utility_policy supersession edge the kernel role-scopes. T1→T6→T7 and T11/T17 apply to any registry entry. **Amended 2026-07-16 (§5.5): the original "no new rule ids" decision could not fire on the happy path; T20 was added** — see §5.5 for the execution evidence and the author-accepted design decision. |
| **Adoption guards** | `ari-core/ari/rqgm/transition_engine.py` `_role_opening`, `_active_after`, `resolve_transition`, `_maybe_supersede_utility_policy` | T6's `role_opening_available` / `one_adoption_per_role_per_boundary` guards are role-generic. For `utility_policy`, when there is no opening (a healthy incumbent) `_maybe_supersede_utility_policy` fires T20 to displace it, scoped hard to that role (behavioural roles keep sanction-only). `governance_report=None` returns early with `no_governance_report` — a missing audit silently disables adoption exactly as for prompts. |
| **Registry entries** | `ari-core/ari/rqgm/registry.py:79-84` `GovernedPromptEntry` ("Text is referenced by *source*, never inlined"), `:166-172` `active_prompt_hashes`, `:174-212` `resolve_text`, `:214-225` `registry_version` | The `source.kind` dispatcher raises on unknown kinds (`:212`) — the policy body needs a kind. `active_prompt_hashes()` hands `freeze_epoch` a `role → prompt_hash` map for free. |
| **Write-once bodies** | `ari-core/ari/rqgm/prompt_loader.py:62-81` `write_evolved_prompt_body`, `:84-96` `active_prompt_view`, `:122-159` `load_versioned` (unknown-kind raise at `:147-150`, hash refusal at `:151-158`) | The evolved-body storage discipline the policy body copies verbatim: write-once, `PromptImmutabilityError` on differing bytes, refuse bytes that no longer hash to the registered identity. |
| **Founding tables** | `ari-core/ari/rqgm/prompt_spec.py:153-217` `FOUNDING_PROMPT_TABLE`, `:219-231` (the "one entry per component id the RUNTIME actually stamps today" contract), `:232-259` `FOUNDING_COMPONENT_TABLE`, `:407-418` `founding_registration_events` | Founding specs are "the SOLE `active`-on-creation exception" (`:22-23`). The tables are "frozen code constants, so the emitted sequence — and therefore `registry_version()` and the `epoch_000` fingerprint — is reproducible" (`:412-414`) — a claim §5.3 must amend, not break. |
| **The founding bootstrap call** | `ari-core/ari/rqgm/runtime.py:376-386` | The one call site of `founding_registration_events()`; `self.cfg` is in scope. |
| **Incumbent discovery** | `ari-core/ari/rqgm/runtime.py:676-724` — `_active_evolvable_incumbents` | `latest.pop(PromptMutator.ROLE, None)` (`:694`) is the same-role-generation exclusion; `spec is None → continue` (`:715`) makes an unknown role degrade silently. The pattern `PolicyMutator` mirrors and the reason `utility_policy` must be popped from the *prompt* mutation loop. |
| **The proposer template** | `ari-core/ari/rqgm/prompt_evolution.py:495-508` `PromptMutator` ("Deliberately exposes no registry/store write surface"), `:532-575` `propose`, `:556-569` knob-only kinds keep incumbent bytes, `:466-494` `candidate_budget_reason` | The exact class shape, LLM-optionality, and per-epoch candidate budget `PolicyMutator` inherits. |
| **UtilityRecord** | `ari-core/ari/rqgm/adversarial/records.py:612-660`, `:632-634`, `:633` (`prompt_hash = utility_policy_hash (not prompt-backed)`), `:685-728` `make_utility_record`, `:725` | The record already declares `component_id="utility_policy_v1"`, `role=UTILITY_POLICY_ROLE` (`:80`) and `prompt_hash=policy_hash`: **it was written against a registry entry that does not exist**. Task 14 creates that entry. |
| **The other policy** | `ari-core/ari/rqgm/adversarial/engine.py:920-963` `UtilityPenaltyPolicy` (`payload()` at `:947-959`, `policy_hash` at `:961-963`), `:979-1020` `apply_utility_penalty` (`:1000-1001`, `:1018`) | The hash a `UtilityRecord` actually carries today is `hash12` over `{penalty_cap, severity_weights, verdict_factors}` — a **different** policy from `capture_utility_policy`'s `{composite, axis_weights, frontier_score, depth_penalty_lambda, ucb_c}`. §5.8 reconciles them. |
| **Record schema** | `ari-core/ari/schemas/rqgm_utility_record.schema.json:5,22-23,63-78` | `frozen_policy` requires `penalty_cap`/`severity_weights`/`verdict_factors`; `utility_policy_hash` is `^[0-9a-f]{12}$`; the description's "the policy is not prompt-backed" is the sentence this task retires. |
| **Epoch schema** | `ari-core/ari/schemas/epoch_state.schema.json:49,60` | `utility_policy.utility_policy_hash` is already required and hash12-shaped — no epoch-schema change. |
| **Recompute (must not re-weight)** | `ari-core/ari/rqgm/frontier_repair.py:362-435` — `MetricRecomputer` | Reads only `frozen_policy["severity_weights"/"verdict_factors"/"penalty_cap"]` (`:401-404`) and copies the record forward (`:417`). Additive `frozen_policy` keys are invisible to it — the compatibility budget §5.8 spends. |
| **The weight cap** | `ari-core/ari/rqgm/meta_evolution.py:1242-1294` — `MetricSpecWeightCap` | "the epoch-frozen weight regime (Task 02 `utility_policy`) outranks any weights a node smuggles through `make_metric_spec`"; attached by `wrap_node_executor` only, absent under `simple_bfts`. Stays verbatim (§5.9). |
| **The candidate space** | `ari-core/ari/config/__init__.py:106-110` (`frontier_score` Literal), `:121-131` (`depth_penalty_lambda`, `ucb_c`), `:217-222` (`axis_weights`), `:224-228` (`composite` Literal); `ari-core/ari/evaluator/llm_evaluator.py:33-39` `AXIS_NAMES` | The closed sets a legal policy must live in. The kernel does not invent them; it pins them. |
| **Numeric defaults home** | `ari-core/ari/configs/defaults.yaml:15-18` (`rqgm.epoch`), `:101-108` (`rqgm.prompt_evolution`), `:133-137` (`rqgm.frontier_repair`) | Where `rqgm.utility_evolution.*` lands, and where the candidate budget this task **reuses** already lives (one schema home, 01 §5.1). |
| **Hard pins that must stay green** | `ari-core/tests/test_rqgm_epoch_state.py:361` (`utility_policy_hash == "b192196ced57"`), `:379-392`; `ari-core/tests/test_rqgm_founding_bootstrap.py:77-88`; `ari-core/tests/test_rqgm_prompt_spec.py:111-117,222-226` | The epoch-0 policy pin stays green **only because** the fallback is byte-identical to today (§5.7); the founding-inventory and active-set pins are the ones this task deliberately extends. |

## 5. Proposed design

### 5.1 The diagnosis in one paragraph

`frontier_repair` can already destroy every score that a retired utility policy produced. Nothing
can retire a utility policy, because no registry entry represents one, because the role is not in
the vocabulary, because the policy is a function of static config rather than of governed state.
The fix is therefore not a new mechanism — it is **four small facts made true**: (1) the role
exists; (2) an entry exists; (3) something proposes a successor; (4) `freeze_epoch` reads the
successor instead of the config. The T-table, the kernel, the transaction, the repair engine and
the record schema are all already role-generic and need only the additions in §5.5-§5.8.

### 5.2 The role limbo, resolved

`ari-core/ari/rqgm/events.py`:

```python
#: Governed roles whose incumbent may be REPLACED at an epoch boundary
#: (Tasks 03/05/06/07/08/11/14). Prompt-defined, except ``utility_policy``,
#: whose incumbent is a policy document (Task 14 §5.3) — the role is
#: evolvable in exactly the same sense: one incumbent, replaced only through
#: the RegistryTransitionEngine at a boundary.
EVOLVABLE_ROLES: tuple[str, ...] = (
    "generator", "reviewer", "adversary", "defender", "judge", "router",
    "prompt_mutator", "clean_room_generator", "replay_selector",
    "failure_summary_compressor",
    "policy_mutator",     # Task 14: un-frozen from meta_rules.META_FROZEN_ROLES
    "utility_policy",     # Task 14: the governed score itself
)
```

Two roles, not one, and both are forced:

- **`utility_policy`** — the governed object. It is *evolvable*, not *fixed*: the fixed layer is
  "kernel / fixed verifier / audit log never evolve" (`events.py:70-72`), and a score that never
  changes is precisely the thing P1 forbids. Putting it in `FIXED_ROLES` would have been the other
  way out of the limbo and is rejected here explicitly.
- **`policy_mutator`** — the proposer. The name is **not invented**: `meta_rules.py:103-108`
  reserves it and states the exit condition ("a later task extends `ari.rqgm.events.ROLES` when
  they gain implementations"). It moves from `META_FROZEN_ROLES` to `META_EVOLVING_ROLES`
  (`meta_rules.py:92-97`).

Both roles need capability-matrix rows or every lookup for them is CK-ACC-001-blocked — the exact
regression `kernel_rules.py:125-133` records for `failure_summary_compressor`. In
`kernel_rules.py:139-156`:

```python
# Constitutional amendment (Task 14):
#  * ``policy_mutator`` is a meta-tier proposer with the same minimal grants
#    as ``prompt_mutator``: it joins ``_EVOLVABLE_ROLES`` below.
#  * ``utility_policy`` is NOT added to ``_EVOLVABLE_ROLES``: it is a passive
#    policy document, not an actor. It gets ONE explicit institutional row
#    narrower than ``_INSTITUTIONAL_BASE`` — no ``invoke``, no
#    ``read active_prompt_text``, no ``read checkpoint_artifacts``. The only
#    thing stamped in its name is the UtilityRecord (records.py:632-634).
_UTILITY_POLICY_CAPS: frozenset[_Cap] = frozenset({
    ("read", "records"),
    ("append", "records"),
})
matrix[("utility_policy", "institutional")] = _UTILITY_POLICY_CAPS
```

`policy_mutator` joins `_EVOLVABLE_ROLES` (`kernel_rules.py:115-134`), receiving
`_INSTITUTIONAL_BASE` and `_META_BASE` like its siblings; its entry is registered at `tier: meta`,
where `META_HARD_DENIED_FLAGS` (`meta_rules.py:44-53`) already makes `can_modify_registry` /
`can_activate_candidates` a **schema violation** rather than a mere denial. Both edits change
`CONSTITUTION_HASH`; `_EXPECTED_CONSTITUTION_HASH` (`test_rqgm_kernel.py:69`) is re-pinned in the
same reviewed diff, exactly as the `paper_writer` amendment did (`kernel_rules.py:224-233`).

`REQUIRED_CONSTRAINTS_BY_ROLE` (`prompt_spec.py:52-63`) gains one row, copied verbatim from
`prompt_mutator`:

```python
"policy_mutator": ("Emit candidates only; never write to the registry.",),
```

`utility_policy` gets **no** constraint clause: constraint clauses are instructions to an actor,
and the utility policy is a document. (This table is not covered by `constitution_hash` —
`_canonical_rules_payload` (`kernel_rules.py:257-289`) does not read it — so the row costs no
second re-pin.)

### 5.3 The governed object: a policy-backed PromptSpec, not a second spec type

**Decision: the utility policy is registered as a `PromptSpec` / `GovernedPromptEntry` whose
`template_ref.kind` / `source.kind` is `"policy"`, and whose `prompt_hash` IS
`utility_policy_hash`. A parallel `UtilitySpec` type is rejected.**

The identity arithmetic already lines up exactly, with no new hashing scheme:

- `capture_utility_policy` computes `policy["utility_policy_hash"] = hash12(canonical_json(policy))`
  over the policy body **before** the hash key is inserted (`state.py:336`) — pinned by
  `test_rqgm_epoch_state.py:387-390`.
- Prompt identity is `hash12(text)` over the template bytes (`prompt_spec.py:6-10`).
- So if the policy body's bytes **are** `canonical_json({composite, axis_weights, frontier_score,
  depth_penalty_lambda, ucb_c})`, then `hash12(bytes) == utility_policy_hash` by construction. One
  scheme, no second implementation — the doctrine stated at `prompt_spec.py:8-10` and
  `registry.py:6-8`.

Why a `UtilitySpec` analog is the wrong answer:

1. **The retirement→repair join is prompt-keyed.** `frontier_repair.py:606-611` reads
   `prompt_hash` off `transition.retirements`; `:223-228` matches records on `prompt_hash`. A
   separate spec type needs a parallel retirement channel, a parallel audit event
   (`transition_engine.py:580-591`), and a parallel repair entry point — three duplications for one
   object.
2. **The freeze seam is prompt-keyed.** `registries.prompts.active_prompt_hashes()`
   (`registry.py:166-172`) already yields `role → prompt_hash`; `freeze_epoch` already copies it
   (`state.py:367`). A `utility_policy` prompt entry means `active_prompt_hashes["utility_policy"]`
   *is* the epoch's policy hash, for free, in the same map the kernel's CK-EPO-001 check reads
   (`kernel.py:548`).
3. **The record already assumes it.** `UtilityRecord`'s defaults are
   `component_id="utility_policy_v1"`, `role="utility_policy"`, `prompt_hash = <policy hash>`
   (`records.py:632-634,725`) with the comment "not prompt-backed". The record was written against
   a registry entry that was never created. Creating it costs one row; inventing a type contradicts
   the record.
4. **The lifecycle is not worth duplicating.** A second spec type re-implements the ten statuses
   (`transition_rules.py:45-54`), the T1–T19 spine, `registry_version()` (`registry.py:214-225`),
   the `prompt_registered` / `prompt_status_change` event types (`events.py:86+`), the snapshot
   writers, and every kernel validator. The only thing it buys is a purer name.

The costs, stated plainly and accepted:

- **`source.kind` gains a third value.** `registry.py:174-212` dispatches on
  `committed_template` / `checkpoint_file` and raises on anything else (`:212`). Task 14 adds
  `policy`: read the write-once body under `{ckpt}/rqgm_prompts/<prompt_id>.json`, refuse bytes
  whose `hash12` ≠ the registered `prompt_hash` — the identical refusal as `:205-210`. Body storage
  is `write_evolved_policy_body`, a `.json` sibling of `write_evolved_prompt_body`
  (`prompt_loader.py:62-81`), write-once, `PromptImmutabilityError` on differing bytes. The
  never-inline contract (`registry.py:81-84`) is honored: the event payload carries the path, the
  file carries the bytes.
- **The `GovernedPromptLoader` must never serve it.** `active_prompt_view`
  (`prompt_loader.py:84-96`) keys the view by `template_ref["key"] or prompt_id`; a policy spec
  carries no loader key, so nothing would ever request it — but relying on "nobody asks" leaves the
  `unknown template_ref kind` raise (`prompt_loader.py:147-150`) one careless call away. Decision:
  `active_prompt_view` **filters out** specs whose `template_ref.kind == "policy"`. A utility policy
  is not a prompt to render; it is a policy to freeze.
- **`PromptMutator` must never target it.** `_active_evolvable_incumbents`
  (`runtime.py:676-724`) gains `latest.pop(UTILITY_POLICY_ROLE, None)` next to the existing
  `latest.pop(PromptMutator.ROLE, None)` (`:694`). Asking a template-rewriting LLM to mutate a
  policy document as prose is exactly the confusion the separate `PolicyMutator` exists to prevent.
  (Today the role would be skipped anyway by `spec is None → continue` at `:715`; the explicit pop
  makes the intent load-bearing rather than incidental.)
- **The spec body.** `PromptSpec.spec` (`prompt_spec.py:97-99`) carries the policy contract, not a
  copy of the bytes: `role_instruction: ""`, `constitutional_constraints: []`,
  `input_contract: {"required_fields": []}`, `output_schema: {}`, `rubric: {}`,
  `calibration_policy: {}`, `budget_policy: {}` — and one Task-14 key, `utility_policy_ref`, naming
  the body path. The body is never inlined into the spec: two copies of a hashed object is exactly
  the split-brain `registry.py:288-293` refuses.

**Founding registration (epoch 0).** The founding utility policy is `capture_utility_policy(cfg)` —
i.e. today's behavior, exactly. But it is **cfg-derived**, so it cannot live in
`FOUNDING_PROMPT_TABLE`, whose whole contract is "frozen code constants … reproducible across boots
and machines" (`prompt_spec.py:412-414`). Decision:

```python
# planned: ari-core/ari/rqgm/prompt_spec.py
def founding_utility_policy_spec(cfg) -> PromptSpec:
    """The epoch-0 utility policy as a founding spec. cfg-derived, so it is
    NOT a member of FOUNDING_PROMPT_TABLE (that table's reproducibility claim
    is about code constants). Pure: bytes -> spec, no I/O."""

def founding_registration_events(cfg=None) -> list[tuple[str, dict]]:
    """... unchanged for cfg=None (the pure-table sequence, so every existing
    caller and test keeps its exact behavior). With a cfg, the utility_policy
    row is appended after the prompt rows and before the component rows."""
```

Amend the `founding_registration_events` docstring (`prompt_spec.py:407-414`): the emitted sequence
is reproducible **for a fixed resolved cfg** — the honest statement, since `registry_version()`
(`registry.py:214-225`) hashes `prompt_sha256` values and the policy's bytes depend on cfg. This is
not a new kind of dependence: `epoch_fingerprint` has always included `utility_policy`
(`state.py:270,276-287`), so the epoch-0 identity of an `ari_rqgm` run has always been cfg-derived.
Task 14 extends that dependence to `registry_version`, and **deliberately changes the `epoch_000`
fingerprint and `registry_version` of every `ari_rqgm` run**. That is declared, not incidental
(§8.3). `simple_bfts` is untouched: it has no registry.

The two founding component rows (`FOUNDING_COMPONENT_TABLE`, sorted by `component_id`,
`prompt_spec.py:232-259`):

```python
# between defender_v1 and prompt_mutator_v1
("policy_mutator_v1", "policy_mutator", "meta", "policy_mutator_prompt_v1",
 {"can_emit_candidates": True,
  "forbidden_targets": list(DEFAULT_FORBIDDEN_TARGETS)}),
# last (after proposal_router_v1)
("utility_policy_v1", "utility_policy", "institutional",
 "utility_policy_prompt_v1", {}),
```

Both roles are singletons, so the `active_set()` "latest wins" rollup (`registry.py:132-141`) is
unperturbed for every existing role — the adversary family stays the sole same-role family
(`prompt_spec.py:230-231`). `policy_mutator_prompt_v1` is a normal committed template
(`rqgm/policy_mutator`, §5.4) and joins `FOUNDING_PROMPT_TABLE` in the meta block; the component id
`utility_policy_v1` is exactly the one `records.py:632` already stamps, so the table's "one entry
per component id the RUNTIME actually stamps today" contract (`prompt_spec.py:219-231`) becomes
*more* true, not less.

### 5.4 The proposer: `PolicyMutator`

A `PromptMutator` analog (`prompt_evolution.py:495-508`), in a new module
`ari-core/ari/rqgm/utility_evolution.py`:

```python
class PolicyMutator:
    """Emits UtilityPolicyCandidate records ONLY.

    Deliberately exposes no registry/store write surface (the PromptMutator
    contract, prompt_evolution.py:496-500): status changes are Task 09's
    engine, kernel-validated. Knob kinds are pure arithmetic over the epoch's
    evidence — no LLM, no clock, no randomness (P2). The freeform kind's
    meta-prompt is the committed ``rqgm/policy_mutator.md``.
    """

    ROLE = "policy_mutator"
    META_PROMPT_KEY = "rqgm/policy_mutator"

    def propose(self, incumbent_policy: dict, *, evidence, mutation_kind,
                epoch_id="", record_seq=0, existing_records=None, cfg=None,
                rationale="") -> "UtilityPolicyCandidate | None":
        ...
```

Decisions:

- **Deterministic by default, LLM-optional.** The mutation family is closed and knob-shaped:
  `axis_reweighting`, `composite_swap`, `frontier_score_swap`, `exploration_tuning`
  (`depth_penalty_lambda` / `ucb_c`), plus `freeform_policy_proposal`. The first four are pure
  arithmetic over the boundary's evidence and need no LLM at all; only the fifth consults an LLM and
  returns `None` when none is configured. This is the exact shape of
  `prompt_evolution.py:556-572` ("Knob-only kinds keep the incumbent bytes"; `if self._llm is None:
  return None`). The default `mutation_kinds` list (§6.3) contains only knob kinds, so the default
  utility rewrite is **fully deterministic** — the strongest available posture for P2.
- **Evidence, not scores.** `evidence` is the boundary's already-abstract material: the
  `FailureSummary` `abstract_view` dicts the parent path already assembles
  (`runtime.py:728-731`) and the governance report's reliability entries. Raw attack text never
  reaches it (`prompt_spec.py:65-70` `FORBIDDEN_PLACEHOLDERS` is the same prohibition for
  templates). A policy is never proposed from the frontier's current scores — that is the
  self-referential loop P2 exists to forbid: a score policy tuned to flatter the nodes it already
  produced is collusive co-evolution.
- **No same-role generation.** `PolicyMutator` never proposes a `policy_mutator` policy — there is
  none; its own template is evolved by `PromptMutator` like any other meta template (the
  `clean_room_generator` precedent, `runtime.py:694` pops only the mutator's own role).
- **Budget reuse, one schema home — but PER-CHANNEL, not one shared pot.** The candidate cap is the
  existing `rqgm.prompt_evolution.max_candidates_per_role_per_epoch` (1) and
  `max_total_candidates_per_epoch` (4) via `candidate_budget_reason` (`prompt_evolution.py`), keyed
  on role `utility_policy`. No fork of the budget *schema* (01 §5.1). **Sanctioned deviation
  (2026-07-16):** the two candidate channels do **not** share one pot of 4 — `candidate_budget_reason`
  counts `prompt_candidate` records for behavioural roles and `utility_policy_candidate` records for
  the `utility_policy` role, so each channel holds its OWN per-epoch cap. This is **load-bearing, not
  cosmetic**: the Task 07 prompt channel mints a candidate for every evolvable role with an active
  incumbent and **saturates `max_total_candidates_per_epoch` (4) on a default config before the
  PolicyMutator runs**; a single shared pot would therefore starve the utility rewrite in every
  default run — P1's cause half structurally unreachable again, the exact defect this task removes.
  The utility channel is a singleton role, so its effective cap is `min(per_role, total) == 1`
  candidate/epoch regardless; the prompt channel's counting is **byte-identical to pre-Task-14** when
  the log carries no utility records (`utility_policy_candidate` records did not exist), pinned by
  `test_prompt_channel_budget_is_byte_identical_to_pre_task_14` and
  `test_mixed_record_type_log_partitions_the_two_channels`. `rqgm.utility_evolution.*` holds only
  what is genuinely new (§6.3).
- **Invocation site.** `_run_epoch_boundary` (`runtime.py:966-1030`), in the candidate-minting
  window that already runs between `run_epoch_audit` and `resolve_transition` — the same window
  `_run_meta_evolution` uses (`runtime.py:973-976`), with the same best-effort posture ("a meta
  failure degrades to 'no candidates this epoch', never a delayed boundary"). The candidate is
  registered at `status="candidate"` through the boundary transaction by the existing intake path
  (`runtime.py:978-985`), so the **next** boundary can iterate it up the T1→T6 spine.

The proposer is inside the audit network on the same terms as the seven adversaries and the two
existing meta agents: it is a registered component with a registered, evolvable prompt; a
governance recommendation against it resolves through `resolve_transition`
(`transition_engine.py:414`) into a T9/T10/T11 sanction; `resolve_emergency_quarantine` does not
reject it as an unknown component. **No absolute ruler**: the thing that proposes the score is
itself governed, sanctionable and evolvable (P3).

### 5.5 T-table adoption edges for `utility_policy` — **adoption by SUPERSESSION**

> **AUTHOR-ACCEPTED DESIGN DECISION (2026-07-16).** The original §5.5 ("no new rule ids; T6 adopts
> while T17 retires the incumbent from quarantine, in one boundary transaction") was **internally
> inconsistent and could not fire on the happy path**, and a verifier proved it dead by execution:
> a real `ari_rqgm` runtime at default config drove 12 boundaries and `utility_policy_hash` stayed
> the constant `fed4460f44f6` the whole run. The reason is structural: **T6** (`shadow →
> probationary_active`) is guarded by `role_opening_available`, which is FALSE while a healthy
> `active` incumbent holds the role — and a passive policy document is always `active` and never
> misbehaves, so the opening never appears; **T17** (`quarantine → retired`) requires the incumbent
> to be in `quarantine`, reachable ONLY via a sanction (T8/T11/T15/T16), and a passive policy
> produces no behaviour to sanction. The whole RQGM adoption model replaces only **sanctioned**
> components, never merely-**better** ones — which is correct for behavioural roles but makes P1
> **unsatisfiable** for the utility policy, whose entire purpose (the Red Queen) is to keep changing
> at boundaries as better criteria are found.
>
> **Resolution — the utility policy is adopted by SUPERSESSION.** The utility policy is the
> evaluation *criterion*, not a behavioural actor. A validated, shadow-passed successor that scores
> at least as well on the frozen replay board **displaces the healthy incumbent**: it is *upgrading
> a criterion*, not *punishing a component*. This is the faithful realisation of P1 ("at epoch
> boundaries the entire score is rewritten") and of the RQGM paper's "utility updated at epoch
> boundaries". **Behavioural roles keep the conservative sanction-only replacement model, untouched
> — the supersession path is scoped hard to `utility_policy` in both the engine and the kernel.**

**Decision: one new rule id, `T20` (`active → retired`), scoped to `utility_policy`.**
`transition_rules.py` is keyed by `(from_status, to_status)`; every other row is role-agnostic. T20
is the sole **role-scoped** row: the ConstitutionalKernel (`kernel.py` `_change_violations`) rejects
`active → retired` with `CK-REG-001` for every role except `utility_policy`, so for a behavioural
component retirement still **stages via quarantine** exactly as before (invariant preserved, pinned
by `test_active_to_retired_is_utility_policy_only`). The engine emits T20 **only** inside a same-role
T6 adoption of a shadow-passed successor (`transition_engine.py` `_maybe_supersede_utility_policy`),
so it can never fire without an adoption to justify the displacement. The lifecycle of a utility
policy is therefore:

| Edge | Rule | Guards, and what they mean for a policy |
|---|---|---|
| `candidate → validated` | **T1** | `candidate_cap_not_exceeded` (the §5.4 per-channel budget); `constitutional_constraints_present` — for a policy this is the §5.6 legality check run in the boundary evaluation (`utility_evolution.evaluate_utility_policy_candidate`): an illegal candidate gets `verdict="fail"` and is rejected into a T2 retirement, never reaching shadow. |
| `candidate → retired` | **T2** | Validation failed or the candidate aged out (`candidate_max_age_epochs`). `never_served_rejection` holds trivially: a candidate policy has scored nothing. |
| `validated → shadow` | **T3** | `replay_and_anchor_evaluation_passed`. **A policy's replay is a re-scoring dry run** (`evaluate_utility_policy_candidate`): the evaluation basis is the policy's own dimensions (the governed knobs it re-weights); a legal, non-degenerate re-weighting preserves the incumbent's axis ordering, scoring the `_axis_ranking_agreement`. Deterministic, no LLM, no new pool, and **pool-independent** — the criterion keeps changing at boundaries even before an adversarial replay pool has filled (which is precisely the Red-Queen posture P1 demands). When per-axis-scored replay cases exist, the ordering they induce is the same ordering this board reads. **Honest scope of the gate (recorded 2026-07-16; the emission corrected 2026-07-17):** under the default `axis_mode: dynamic` config the static `axis_weights` map is empty, so `_axis_ranking_agreement` has no incumbent ordering to compare against — **the comparison never runs**. `replay_score` therefore reports that ABSENCE (`None`), and the T3 gate reduces to **legality (CK-UTL) + non-degeneracy**. *(It previously emitted `1.0` here — a hardcoded pass for a comparison that never happened, contradicting §7's "No field carries a quantity nothing produced" in the very row that asserts it. The `no_replay_basis` sentinel already carries the T3 pass for this role — `scores_ok` treats an absent board as abstaining and the waiver covers the count floor — so the `1.0` was load-bearing for nothing. `None` means "not compared"; a real number is reported whenever the comparison genuinely runs, i.e. whenever both static maps are populated.)* The reduced gate is intended, not vacuous: with no ground-truth anchor there is no "strictly better" to gate on, and a criterion that rolls within the legal simplex every boundary is exactly the Red-Queen target-motion P1 wants (throttled by `min_epochs_between_rewrites`, R1). A genuine "at least as well" quality gate requires an **anchored, per-axis-scored basis**; that basis is the paper phase's APReS-equivalent anchor, owned by [../ari_rqgm_paper/04_anchor_utility_and_epoch_winners.md](../ari_rqgm_paper/04_anchor_utility_and_epoch_winners.md) — the paper reviewer's utility is where a "strictly better" supersession gate becomes both possible and meaningful. Exploration-phase supersession stays legality-bounded. |
| `shadow → validated` / `shadow → retired` | **T4** / **T5** | Unchanged **as edges**, but see the vacuous-shadow note below: a `utility_policy` candidate is never retired by T4/T5 for insufficient shadow samples, because it never had any to be short of. |
| `shadow → probationary_active` | **T6** | `role_opening_available` **OR supersession** + `one_adoption_per_role_per_boundary`. For a behavioural role T6 still needs an opening (sanction-only). For `utility_policy`, when there is no opening (the incumbent is healthy) a shadow-passed successor still adopts — and triggers **T20** on the incumbent in the same act (`_maybe_supersede_utility_policy`). `max_adoptions_per_role_per_boundary: 1` ⇒ **at most one utility rewrite per boundary**, structurally. |

**Honest scope of the SHADOW stage (recorded 2026-07-17 — extends the T3 note above to T4/T5/T6).**
Task 09's T6 triggering input is a **live-shadow board**: samples accumulated by running the
candidate alongside the incumbent. A `utility_policy` candidate is a passive policy **document**
(§5.2: no `invoke` grant), so it is never shadow-*executed* and produces **zero** live-shadow
comparisons **by construction**. Its shadow stage is therefore **vacuous** — not merely
under-populated. Consequently:

* `evaluate_utility_policy_candidate` reports the absence rather than a number:
  `shadow_samples: None`, `shadow_score: None`, plus the explicit marker
  `shadow_basis: "vacuous_passive_policy"`. It previously emitted
  `shadow_samples: len(case_refs)` — a count of the policy body's **dict keys** standing in for a
  sample count — and `shadow_score = replay_score`, an unlabelled re-read of the T3 board. Both are
  deleted: **no field reports a quantity nothing produced.**
* Because the counts are absent, the evaluation carries the `no_replay_basis` **and**
  `no_shadow_basis` sentinels and `utility_policy` is a member of
  `transition_engine.NO_REPLAY_BASIS_ROLES`, so the **T3 `replay_min_cases` and T6
  `shadow_min_samples` COUNT floors are waived at the decision site**, in the open, with a note on
  the transition record naming the role and the gate. The waiver is scoped by role exactly like
  this module's other two role-scoped rules (`_maybe_supersede_utility_policy`,
  `_attach_utility_policy_bodies`); **behavioural roles keep Task 09's live-shadow board
  untouched**, and a candidate that reports a score still has to clear its threshold — the waiver
  excuses counts and declared absences, never a score.
* **Two floors, two keys (amended 2026-07-17).** One sentinel read at both gates conflated two
  independent facts, which broke down as soon as the paper roles joined the allowlist: T6's
  vacuousness is STRUCTURAL (never shadow-executed — always true), while T3's absence is
  CIRCUMSTANTIAL for a role whose `case_refs` are real cases (`paper_reviewer`: absent only when
  the pool is empty). `no_replay_basis` now declares the T3 replay-basis absence and
  `no_shadow_basis` the T6 shadow-basis absence. **`utility_policy` declares BOTH,
  unconditionally, and its semantics are unchanged**: its `case_refs` are the policy's own
  DIMENSIONS at every `axis_mode`, so the `replay_min_cases` floor never has anything honest to
  count — which is precisely why the floor must not be re-derived engine-side from
  `replay_score is None` (that would silently re-introduce the `shadow_min_samples: 6` class of
  accidental coupling this section removed, this time on the T3 side at `replay_min_cases: 8`).
  Only the EVALUATOR knows whether its own `case_refs` are countable evidence, so the
  declaration stays with the evaluator.
* This also removes an accidental coupling that was live: `shadow_min_samples: 6` (off-default)
  silently killed every utility rewrite, because the dict-key count happened to be 5.
* **T6 for `utility_policy` therefore reduces to**: CK-UTL legality (the T1 dry-run + the live
  kernel gate on the adoption path, §5.6) + non-degeneracy + the supersession / one-adoption-per-
  boundary guards. The genuine quality gate remains deferred to the paper phase's Task-04 anchor,
  exactly as the T3 note above already records.
* `case_refs` keeps carrying the policy's own **dimensions** — the basis this doc's T3 row defines
  ("the evaluation basis is the policy's own dimensions") — so it still describes what it claims.
  The `no_replay_basis` sentinel is what now states, on the record, that those are *not* executed
  replay cases and cannot be counted as evidence sufficiency.
| `probationary_active → active` | **T7** | `probation_min_epochs_served`. The successor promotes to `active` a boundary after it supersedes; the proposer then mints vN+1 (`_active_utility_policy_identity` returns the new version). |
| `active → retired` | **T20** (NEW, §5.5) | `supersession_successor_adopted` + `utility_policy_role_only` + `emits_retirement_event`. **This is the edge that rewrites the score.** The retirement carries `prompt_hash = <old utility_policy_hash>` and `role = "utility_policy"` (`transition_engine.py` retirement audit); `frontier_repair` reads it, matches every node stamped with that hash (`UTILITY_POLICY_HASH_KEY`, §5.8 delta 2) and every record carrying it, sees `role ∈ INVALIDATE_ROLES`, and invalidates with `UTILITY_INVALIDATED_REASON`. |
| `active → warning/probation/quarantine` | **T9/T10/T11** | A policy is still sanctionable like any component (P3 — no absolute ruler). A **sanctioned** incumbent (already `quarantine`) yields a role opening, so an ordinary T6 fires and the sanctioned incumbent is retired by the pre-existing T17 path — the supersession branch only fires against a *healthy* incumbent. |
| `quarantine → retired` | **T17** | Unchanged: the sanction path's retirement. Emits the same `retirement_event` shape T20 does, so `frontier_repair` is agnostic to which edge retired the policy. |
| `retired → banned` | **T19** | Absorbing; unchanged. |
| `* → quarantine` mid-epoch | **T16** | The **only** mid-epoch edge; applies to a policy too. The within-epoch freeze (§8.1) is not weakened — T16 is the pre-existing, kernel-gated exception, and `run_boundary`'s freeze still governs what the *next* epoch uses. |

The adoption and the supersession retirement are two edges of **one** boundary transaction: T6
adopts the successor `utility_policy` prompt to `probationary_active` while T20 retires the healthy
incumbent policy prompt, and `run_boundary` freezes the new epoch over the post-transition
registries (`active_prompt_hashes()` yields the successor — "latest active wins"). The new policy is
in force and the old policy's scores are invalidated in the same committed transaction, with repair
running strictly after the commit. There is no window in which a node is scored under a policy that
has already been retired. The **component** `utility_policy_v1` (the stable institutional stamper of
`UtilityRecord`, §5.3) is untouched by the swap — only its policy **prompt** is rewritten, which is
exactly the §5.3 identity split (`component_id` stable, `prompt_hash` evolving).

**Blast-radius note (T20).** Adding T20 to `transition_rules.TRANSITION_TABLE` re-pins
`constitution_hash` (the table is inside `_canonical_rules_payload`) and grows the table 19 → 20
rows; `_EXPECTED_CONSTITUTION_HASH` and the two table-size / forbidden-edge tests
(`test_rqgm_kernel.py`, `test_rqgm_transition_engine.py`) are updated as reviewed diffs, exactly the
treatment §8.6 prescribes. `allowed_transitions("active")` now includes `retired`, but the kernel's
role-scope keeps the edge legal only for `utility_policy`.

### 5.6 ConstitutionalKernel: what a legal utility policy is

Legality is **frozen code, never config**: `kernel_rules.py:3-6` — "putting role rules or the
capability matrix in a checkpoint-scoped YAML would create an evolution/tampering channel (any
skill can write the flat checkpoint dir)". A tunable weight bound is a tunable constitution. New
frozen table in `kernel_rules.py`:

```python
# ── legal utility policies (plan 14 §5.6) ──────────────────────────────
#: The closed value spaces a governed utility policy must live in. Mirrors
#: the typed config Literals (config/__init__.py:106-110, 224-228) — the
#: kernel does not invent the vocabulary, it pins it, so a candidate can
#: never name a composite the evaluator cannot compute.
UTILITY_POLICY_RULES: dict = {
    "allowed_composite": ("arithmetic_mean", "geometric_mean",
                          "harmonic_mean", "weighted_min"),
    "allowed_frontier_score": ("depth_penalized", "scientific_only",
                               "scientific_plus_diversity", "ucb_like"),
    "axis_weight_min": 0.05,          # no axis may be zeroed out
    "axis_weight_max": 0.60,          # no axis may dominate
    "axis_weight_sum": 1.0,           # normalised
    "depth_penalty_lambda_max": 0.50,
    "ucb_c_max": 2.0,
    "required_keys": ("composite", "axis_weights", "frontier_score",
                      "depth_penalty_lambda", "ucb_c"),
}
```

`_canonical_rules_payload` (`kernel_rules.py:257-289`) gains a `utility_policy_rules` key, so the
table is inside `constitution_hash` (`:292-304`) and an edit to it is an explicit reviewed diff
plus a re-pin — the same treatment the transition table gets.

New kernel validator, `validate_utility_policy(policy) -> KernelReport`, deterministic and pure
(the `kernel_rules.py:19-20` import-grep test binds it: no LLM, no network, no randomness):

| Check | Violation | Severity |
|---|---|---|
| Every `required_keys` member present; no extra keys | `CK-UTL-001` | block |
| `composite ∈ allowed_composite` | `CK-UTL-002` | block |
| `frontier_score ∈ allowed_frontier_score` | `CK-UTL-003` | block |
| Every axis weight in `[axis_weight_min, axis_weight_max]` | `CK-UTL-004` | block |
| `sum(axis_weights) == axis_weight_sum` within `rqgm.kernel.float_tolerance` | `CK-UTL-005` | block |
| `axis_weights` keys ⊆ the epoch's live axis set | `CK-UTL-006` | warn |
| `depth_penalty_lambda ≤ max`, `ucb_c ≤ max`, both ≥ 0 | `CK-UTL-007` | block |
| `hash12(canonical_json(policy_body)) == the registered prompt_hash` | `CK-UTL-008` | block |

Codes join `SEVERITY` (`kernel_rules.py:170-216`) and are frozen once implemented, never
renumbered. Notes:

- **Why bounds at all.** An unbounded re-weighting is how a governed score gets laundered into an
  ungoverned one: `axis_weights = {novelty: 1.0}` with everything else at 0 is formally a policy and
  substantively the deletion of `measurement_validity` and `reproducibility` from the method. The
  floor/ceiling makes the axis set irreducible; the boundary may re-prioritise, never abolish.
- **Why `CK-UTL-006` warns rather than blocks.** Under `axis_mode: dynamic`
  (`core.py:163-198`, `evaluator/dynamic_axes.py`) the live axis set is not the canonical five
  (`llm_evaluator.py:33-39`), and `EvaluatorConfig.axis_weights` already documents that "unknown
  keys are silently dropped" (`config/__init__.py:217-222`). A stale key is harmless by
  construction; blocking on it would make the kernel wrong about a config the evaluator handles.
- **Capability re-pin.** An adoption that declares capabilities is already checked for authority
  non-expansion (`CK-REG-101`, `kernel_rules.py:194`; `meta_evolution.py` authority checks). A
  utility-policy candidate declares **no** capabilities (`{}` in the founding row) and may not
  acquire any: a policy that could `invoke` or `write registry` is not a policy.
- **Where it is called.** `validate_transition` (`kernel.py:591+`) for every adoption whose target
  role is `utility_policy`, and `CandidateValidationPipeline`'s stage-2 constitutional stage
  (`prompt_evolution.py:687-770`, `constitutional_validation_failures` at `:327`) for the T1 guard
  `constitutional_constraints_present`. One validator, two callers — no duplicate rule copy.

### 5.7 The core change: `capture_utility_policy` reads the adopted policy

```python
# planned: ari-core/ari/rqgm/state.py:313-337
def capture_utility_policy(cfg, registries=None) -> dict:
    """Freeze the utility policy for the epoch about to open (plan 14 §5.7).

    Precedence: the ADOPTED policy in *registries* (the active `utility_policy`
    entry, resolved through GovernedPromptRegistry.resolve_text), else the
    resolved cfg. The cfg branch is byte-identical to the pre-Task-14 function,
    so epoch 0 of every run — and every epoch of a run that never adopts a
    policy — freezes exactly today's policy. Duck-typed getattr reads keep the
    cfg branch total over pre-RQGM cfg objects and stub configs. The hash is
    computed over the canonical JSON of the other keys (P2: content-only, no
    wall clock).
    """
```

Behaviour:

1. If `registries` is `None` (the `simple_bfts` / stub / pre-RQGM path) → the cfg branch, verbatim
   as today.
2. If `registries.prompts.active_prompt_hashes()` has no `utility_policy` key (epoch 0, before
   founding registration; a resumed pre-14 checkpoint) → the cfg branch.
3. Otherwise → resolve the active entry's body via `resolve_text` (`registry.py:174-212`, the new
   `policy` kind), parse the canonical JSON, re-append `utility_policy_hash`, and **verify** that
   `hash12(body) == entry.prompt_hash`. A mismatch is `CK-UTL-008`, and the reader falls back to
   the cfg branch with a WARNING rather than raising into the run — "never raises into the run" is
   the standing contract for every state accessor ("best-effort … never raises into the run",
   01 §7).

`freeze_epoch` (`state.py:340-373`) changes by one argument:

```python
utility_policy=capture_utility_policy(cfg, registries=registries),   # was: (cfg)
```

That is the entire cause-side wiring, and it is correct at both call sites for free:

- `store.open_epoch` (`store.py:462-503`) passes `base` — at epoch 0 there is no `utility_policy`
  entry until founding registration, so branch 2 gives today's policy and
  `test_rqgm_epoch_state.py:361`'s `utility_policy_hash == "b192196ced57"` pin stays green.
- `store.run_boundary` (`store.py:505-547`) passes `tentative`, built at `:534-538` from registry
  copies **after** `apply_registry_event` has applied the transaction's events (`:532-533`). A
  policy adopted in this transaction is therefore the policy the next epoch freezes — no ordering
  work, no new hook, no second pass.

`utility_policy_hash` stops being a constant. `epoch_fingerprint` (`state.py:276-287`), which
already hashes `utility_policy` (`:270`), starts changing across epochs when and only when the
score changes. That is P1's "the entire score is rewritten at the epoch boundary", expressed in the
identity the whole system already agrees on.

### 5.8 Closing the cause→consequence circuit: the two `utility_policy_hash`es

Grounding the design surfaced a join defect that must be fixed here or the circuit stays open.
**There are two different policies whose hashes are both called `utility_policy_hash`:**

| | The **epoch utility policy** | The **penalty policy** |
|---|---|---|
| Body | `{composite, axis_weights, frontier_score, depth_penalty_lambda, ucb_c}` | `{penalty_cap, severity_weights, verdict_factors}` |
| Computed at | `state.py:324-336` | `adversarial/engine.py:947-963` |
| Stored in | `EpochState.utility_policy` (`state.py:241`), `epoch_fingerprint` | `UtilityRecord.utility_policy_hash` **and** `.prompt_hash` (`records.py:722,725`) |

`make_utility_record(..., policy_hash=policy.policy_hash)` (`engine.py:1018`) passes the **penalty**
policy's hash, and `records.py:725` writes it into `prompt_hash`. The two key sets are disjoint, so
the two hashes are never equal. Consequence: retiring the `utility_policy` registry entry puts the
*epoch* policy hash into `retired_hashes` (`frontier_repair.py:606-611`) — where it matches **no
record**, because every `UtilityRecord` carries the *penalty* hash. The cause would fire into a
join that cannot match. Two deltas close it, both minimal:

**Delta 1 — re-point the record's hash (owned here, co-notified to Task 06).**
`apply_utility_penalty` (`engine.py:979-1020`) gains an `epoch_utility_policy: dict | None`
argument, threaded from `AdversarialRound`'s existing epoch handle (`adversarial/round.py:235`,
`_epoch_id` at `engine.py:1035-1043` already resolves the same `epoch_state`). Then:

- `utility_policy_hash` / `prompt_hash` = the **epoch** policy hash (`state.py:336`), i.e. the
  registered `prompt_hash` of the active `utility_policy` entry;
- `frozen_policy` keeps its three schema-required keys (`rqgm_utility_record.schema.json:64-67`) and
  gains an **additive** `utility_policy` object carrying the epoch policy by value.

Nothing regresses: `MetricRecomputer` reads only `severity_weights` / `verdict_factors` /
`penalty_cap` (`frontier_repair.py:401-404`) and copies the record forward (`:417`), so an additive
key is invisible to it, and the by-value promise ("Task 10's recompute under the original epoch's
weights never needs a registry lookup", `records.py:616-618`) now covers both policies instead of
one. And `utility_policy_hash`'s **value is read by nothing today** — a repo-wide grep finds only
writers (`records.py:627,655,671,722`) and the schema pattern (`:63`). It is a write-only field,
so re-pointing it is behavior-preserving for every existing reader; pre-14 records simply never
match a retirement, which is exactly today's behavior.

The forcing function is the kernel, not aesthetics: once `utility_policy` is an active registry
entry, `epoch.active_prompt_hashes["utility_policy"]` is the epoch policy hash, and
`validate_epoch_invariance` (`kernel.py:579-587`) raises **CK-EPO-001 on every `UtilityRecord`**
whose `prompt_hash` is outside that frozen set. Delta 1 is the only way a `UtilityRecord` is a
constitutionally coherent record after §5.2. The schema description's sentence "prompt_hash carries
utility_policy_hash (the policy is not prompt-backed)" (`rqgm_utility_record.schema.json:5`) is
updated: it is now registry-backed, and that is what makes it governable.

**Delta 2 — coverage: the epoch policy stamp.** `apply_utility_penalty` returns `None` when
`penalty <= 0.0` (`engine.py:1000-1001`), so **only attacked-and-penalised nodes carry a
`UtilityRecord`**. Under delta 1 alone, a policy rewrite would invalidate the penalised subset and
leave every unattacked node in the frontier holding an old-policy score — a *random* half-rewrite,
which is worse than none: the frontier would then mix two incomparable score regimes with no marker
saying which is which. P1 says the *entire* score is rewritten. Decision: stamp the epoch's policy
hash on the node itself, at the `wrap_node_executor` seam that already exists for exactly this
class of concern:

```python
# Node.metrics sentinel key, additive, persisted through tree.json, never
# written under simple_bfts — the frontier_repair.py:75-80 convention
# (_stale / _valid_for_frontier / _stale_reason / _erasure_event_id) and the
# engine.py:1006-1008 convention (_pre_penalty_score /
# _validated_attack_penalty).
UTILITY_POLICY_HASH_KEY = "_utility_policy_hash"
```

Written by a `UtilityPolicyStamp` attached by `RQGMRuntime.wrap_node_executor` alongside
`MetricSpecWeightCap` (`meta_evolution.py:1245`), which already holds the epoch handle
(`meta_evolution.py:1254-1264`) and already runs at exactly the moment a node's score is being
formed. `FrontierRepairEngine.repair` then gains one rule: a retirement whose `role` is
`utility_policy` also invalidates every node whose `metrics[UTILITY_POLICY_HASH_KEY]` is in
`retired_hashes`, with `_stale_reason = UTILITY_INVALIDATED_REASON` — the constant that already
exists for it (`frontier_repair.py:86`). This is the same invalidation, reached by the node's own
provenance instead of by a record it may not have.

Why a stamp and not a second record type: a second `utl_`-prefixed emitter would allocate ids from
a second counter (`format_utility_id`, `records.py:130-131`; the schema pins `^utl_[0-9]{6,}$` at
`rqgm_utility_record.schema.json:27`) while `load_rqgm_records` dedupes by `record_id`
(`frontier_repair.py:448-457`) — colliding ids would silently **drop** records. The stamp needs no
allocator, no store, no schema, and rides `tree.json` so it survives resume.

### 5.9 What stays exactly as it is

- **`MetricSpecWeightCap` stays** (`meta_evolution.py:1242-1294`), verbatim, and this plan
  strengthens rather than relaxes it. It suppresses axis weights a **node** smuggles through
  `make_metric_spec`, so "the epoch-frozen weight regime (Task 02 `utility_policy`) outranks any
  weights a node smuggles" (`:1248-1250`). That prohibition is about **ungoverned** weight changes:
  mid-epoch, by a node, with no candidate, no validation, no adoption, no audit — laundering a score
  change through a work product. A **governed boundary rewrite** is its exact opposite: proposed by
  a registered component, validated against the frozen §5.6 rules, adopted through the T-table,
  audited as a transition, and paid for by invalidating everything scored under the old policy. The
  distinction is *who* and *when*, not *whether*. Its clamp comment (`:1276-1279`) — "dropping
  MetricSpec weights lets `_resolve_axis_weights` fall through to the ctor/AxisDef weights — exactly
  the regime `capture_utility_policy` froze at the epoch boundary" — becomes **more** true under
  Task 14, because the regime it falls through to is now the governed one.
- **Score comparability is already handled** (§3, §5.5 T17). The `INVALIDATE_ROLES` decision
  (`frontier_repair.py:96-101`) and the by-value `frozen_policy` (`records.py:616-618`,
  `engine.py:947-948`) are the answer, and this plan cites them rather than rebuilding them. In
  particular Task 10's rule "recomputation under original-epoch weights … this task must not
  silently re-weight" (`10_frontier_repair_and_selective_erasure.md`:515-518) survives **verbatim**:
  a utility rewrite never re-weights an old score, it invalidates it. There is no new recompute
  path, no new comparability apparatus, and no arithmetic that converts an old score into a new one.
- **Selective erasure stays logical.** Nothing is deleted. The retired policy's registry entry, its
  body file and every `UtilityRecord` it produced remain on disk; the nodes are flagged
  `_stale` / `_valid_for_frontier=False` and excluded from frontier scoring (invariant 13).

### 5.10 Invariant I-11 is overturned

**I-11 ("axes frozen per run") is repealed and replaced by: the utility policy is frozen per
EPOCH, and is rewritten at boundaries through the governed path — PolicyMutator →
CandidateValidationPipeline → RegistryTransitionEngine → ConstitutionalKernel — never anywhere
else.** I-11 was never a property of the method; it was a v1 deferral, recorded honestly in each
plan as a deferral, and it contradicts P1. `INDEX.md`'s global invariant already carries the
replacement text; the six reliance sites must now say:

| Site | What it says today | What it must now say |
|---|---|---|
| [01_execution_modes_and_compatibility.md](01_execution_modes_and_compatibility.md):465 (R7) | "Score-comparability interactions (axis freezing vs epoch re-weighting, invariant I-11) are *not* affected by this task … Deferred to Task 10; Task 00 already records the question as Q-40 … and register item B-17." | Keep "not affected by this task" (the wrapper is still pure delegation) and **re-point the deferral**: epoch re-weighting is designed in Task 14, not Task 10; Q-40 / B-17 are answered there. The mode switch documents where the answer lives, not the answer. |
| [06_adversarial_evolution.md](06_adversarial_evolution.md):630 (risk) | "Score-comparability drift (loop invariant I-11) … penalties are epoch-frozen … **Task 10 owns the cross-epoch story.**" | Keep the within-epoch analysis verbatim; re-point ownership: **Task 14 owns the cross-epoch story**; a policy rewrite invalidates rather than reconciles, and `frozen_policy` gains the epoch policy by value (§5.8 delta 1), which is what keeps a penalised node's history readable after the rewrite. |
| [07_prompt_spec_and_prompt_evolution.md](07_prompt_spec_and_prompt_evolution.md):632 (risk) | "Cross-epoch score comparability (I-11 …): prompt swaps change reviewer behavior mid-run **even without axis re-weighting**. Mitigation: … Task 10 owns frontier-side comparability policy." | Drop "even without axis re-weighting" — axis re-weighting is now a first-class, governed event on the same boundary as a prompt swap, and both retire hashes into the same repair pass. Keep the epoch-id and within-epoch-monitoring mitigations verbatim. |
| [09_registry_transition_engine.md](09_registry_transition_engine.md):540 (risk) | "…adoptions change who scores future nodes … This task keeps scoring-rule freeze *within* an epoch; the cross-epoch policy is **owned by Task 10 and must be resolved there before first adoption of an evaluator-role component**." | Keep the within-epoch freeze statement (it is exactly right and this task depends on it). Re-point: the cross-epoch policy is resolved in **Task 14**, and the `utility_policy` role rides this task's T-table via the T1→T3→T6 spine plus **one new role-scoped edge, T20** (`active→retired` supersession, §5.5, amended 2026-07-16) — behavioural roles' guards and topology are unchanged. |
| [10_frontier_repair_and_selective_erasure.md](10_frontier_repair_and_selective_erasure.md):515 (risk) | "recomputation under original-epoch weights keeps within-epoch comparability, but cross-epoch `_scientific_score` comparisons … remain epoch-relative — **owned by Task 02's freeze design; this task must not silently re-weight**." | Both halves survive verbatim; only the owner is corrected (Task 02 froze the policy, Task 14 rewrites it). Add: cross-epoch comparisons remain epoch-relative **by design** — a rewrite invalidates the old regime instead of translating it — and the `utility_policy` member of `INVALIDATE_ROLES` (`frontier_repair.py:99-101`) is the enforcement, now reachable. Record §5.8 delta 2 (the `_utility_policy_hash` sentinel + the role-scoped invalidation rule) as a Task-14 addition to this engine. |
| [13_evaluation_and_ablation.md](13_evaluation_and_ablation.md):435 (risk) | "metric 10 compares scores across an erasure boundary. Mitigation: **Task 10's decision (axes frozen per run) is assumed**; if epoch re-weighting is ever enabled, metric 10 is reported per-weight-regime only." | The conditional has fired. Delete the assumption; **metric 10 is reported per-weight-regime, always**, keyed on `EpochState.utility_policy["utility_policy_hash"]` (which is now epoch-varying and already in the fingerprint). Add an ablation rung that disables `rqgm.utility_evolution.enabled` and measures whether governed rewriting helps — the only honest way to defend P1 empirically. |

The paper set's inherited references —
[../ari_rqgm_paper/04_anchor_utility_and_epoch_winners.md](../ari_rqgm_paper/04_anchor_utility_and_epoch_winners.md):294
and :544 ("../ari_rqgm/10 I-11 decision: axes frozen per run") — are stale for the same reason and
are corrected by that set's own owner, citing this plan. Task 14 does not edit them.

### 5.11 Inheritance: `simple_bfts`, `ari_rqgm`, paper

- **`simple_bfts` is untouched.** No role, no registry, no epoch, no kernel, no `ari.rqgm` import
  (01 §5.3's lazy-import guarantee). `capture_utility_policy` is not called at all. The
  `_utility_policy_hash` sentinel is "never written in `simple_bfts`", exactly like the four
  sentinels beside it (`frontier_repair.py:75-76`). The weight precedence stays
  `MetricSpec > ctor > AxisDef > defaults`, byte-for-byte (`meta_evolution.py:1246-1247`).
- **`ari_rqgm` gains it**, in both phases, through the parent path only. This is the point of
  fixing it here: with `capture_utility_policy` reading the registry, *every* `ari_rqgm` epoch
  boundary — exploration or paper — can rewrite the score, and none of them could before.
- **The paper phase inherits it topology-agnostically.** `PaperArchiveRuntime` reuses
  `ari.rqgm.state` / `ari.rqgm.store` / the transition engine / the kernel verbatim; a paper epoch
  boundary is `run_boundary` like any other, so it freezes the adopted policy like any other. The
  paper set builds **no** local utility machinery and defines **no** paper-local rewrite: its
  `capture_paper_utility_policy`
  ([../ari_rqgm_paper/04_anchor_utility_and_epoch_winners.md](../ari_rqgm_paper/04_anchor_utility_and_epoch_winners.md)
  §5.5) is the paper phase's *policy body producer* and rides this plan's registry seam and
  legality rules unchanged — it does not fork the mechanism. Paper docs cite Task 14; they do not
  reinvent it.

## 6. Data structures / schema changes

### 6.1 New: `{ckpt}/rqgm_prompts/<prompt_id>.json` (the policy body)

Write-once, byte-fixed **canonical JSON** (`canonical_json`, `events.py`), stored beside the Task 07
evolved template bodies under the already-registered `rqgm_prompts/` directory
(`prompt_loader.py:33`, `RQGM_PROMPTS_DIRNAME`) — so no new `PathManager.META_FILES` entry and no
new `_INTERNAL_JSON_NAMES` row is needed:

```json
{
  "axis_weights": {"clarity_of_contribution": 0.15, "comparative_rigor": 0.2,
                   "measurement_validity": 0.3, "novelty": 0.2,
                   "reproducibility": 0.15},
  "composite": "harmonic_mean",
  "depth_penalty_lambda": 0.05,
  "frontier_score": "scientific_plus_diversity",
  "ucb_c": 0.5
}
```

`hash12` of these bytes **is** the entry's `prompt_hash` **is** `utility_policy_hash` — one value,
three names, zero new hashing (§5.3). The file never contains `utility_policy_hash` itself: the
hash is of the body, and `capture_utility_policy` re-appends it to the returned dict exactly as
today (`state.py:336`).

### 6.2 New record: `utility_policy_candidate`

Mirrors `prompt_candidate` (`prompt_evolution.py:1078-1121`) and rides the same evolution log — no
new store:

```json
{
  "record_type": "utility_policy_candidate",
  "schema_version": 1,
  "record_id": "upc_000001",
  "epoch_id": "epoch_003",
  "component_id": "policy_mutator_v1",
  "prompt_hash": "<policy_mutator template hash>",
  "role": "policy_mutator",
  "created_at": "<iso8601, metadata only, never hashed>",
  "status": "candidate",
  "candidate_id": "utility_policy_prompt_v2",
  "parent_prompt_id": "utility_policy_prompt_v1",
  "mutation_kind": "axis_reweighting",
  "policy": { "...": "the §6.1 body" },
  "policy_hash": "<hash12 of the body>",
  "rationale": "<abstract evidence citation; never raw attack text>",
  "source_refs": ["<failure_summary ids>", "<reliability entry ids>"]
}
```

The envelope is the mandatory common one (`kernel_rules.py:59-68`): the author is the
**policy_mutator**, not the policy — a candidate is a proposal by a component, which is why
`component_id`/`role`/`prompt_hash` name the proposer. New schema file
`ari-core/ari/schemas/rqgm_utility_policy_candidate.schema.json`, additive-only, listed in
`ari-core/ari/schemas/README.md`.

### 6.3 Config: `rqgm.utility_evolution.*` (one schema home)

```yaml
# ari-core/ari/configs/defaults.yaml — mirrors the typed
# ari.config.RQGMUtilityEvolutionConfig pydantic defaults; parity pinned by
# ari-core/tests/test_rqgm_utility_evolution.py. Meaningful only when
# ari.mode: ari_rqgm and rqgm.enabled: true agree. Numeric knobs ONLY: the
# legality rules are frozen code (kernel_rules.UTILITY_POLICY_RULES, §5.6).
rqgm:
  utility_evolution:
    enabled: true                # false => today's behavior exactly (§8.2)
    mutation_kinds: [axis_reweighting, composite_swap, frontier_score_swap,
                     exploration_tuning]   # all deterministic; freeform is opt-in
    min_epochs_between_rewrites: 1
```

Deliberately **absent**, because they already have a home (01 §5.1):

- candidate caps → `rqgm.prompt_evolution.max_candidates_per_role_per_epoch` /
  `max_total_candidates_per_epoch` (`defaults.yaml:101-108`), consumed via
  `candidate_budget_reason` (`prompt_evolution.py`) keyed on role `utility_policy` — **per channel,
  not one shared pot** (§5.4 sanctioned deviation): the prompt channel counts `prompt_candidate`
  records and the utility channel counts `utility_policy_candidate` records, so a saturated prompt
  channel (four candidates on a default boundary) can never starve the singleton utility rewrite;
- adoption caps → `rqgm.transition.max_adoptions_per_role_per_boundary` (`defaults.yaml:71`);
- shadow sampling → `rqgm.shadow.*`; invalidation posture → `rqgm.frontier_repair.*`;
- **weight bounds → nowhere in YAML.** They are constitutional (§5.6).

Typed model `RQGMUtilityEvolutionConfig` on `RQGMConfig` (01 §6.1), whose `extra: allow`
(`config/__init__.py`, `RQGMConfig`) means an older ari-core reading a config that sets these keys
silently gets today's behavior — the safest failure direction (01 §8.7).

### 6.4 Amended schemas

- `ari-core/ari/schemas/rqgm_utility_record.schema.json` — description line updated (the policy is
  registry-backed; `prompt_hash` / `utility_policy_hash` carry the **epoch** policy hash);
  `frozen_policy` gains an optional `utility_policy` object. Required keys unchanged, so every
  record ever written still validates (§8.4).
- `ari-core/ari/schemas/epoch_state.schema.json` — **unchanged**. `utility_policy.utility_policy_hash`
  is already required and hash12-shaped (`:49,60`); only its *value* stops being constant.
- No change to `rqgm_state.json`, the registry snapshot shape, the transitions event vocabulary
  (`events.py:86+`: `prompt_registered` / `prompt_status_change` already carry everything), or the
  audit-log envelope.

## 7. API / class changes

All new code lives in the internal `ari-core/ari/rqgm/` package (no `ari.public.*` export, no CLI
surface ⇒ zero contract-golden regeneration).

| Symbol | Location (planned) | Contract |
|---|---|---|
| `PolicyMutator` | `ari/rqgm/utility_evolution.py` | §5.4. `ROLE = "policy_mutator"`, `META_PROMPT_KEY = "rqgm/policy_mutator"`. `propose(...) -> UtilityPolicyCandidate \| None` — never raises; `None` when over budget, when the kind is unknown, or when a freeform kind has no LLM. **No registry/store write surface** (attribute test, `prompt_evolution.py:496-500` precedent). |
| `UtilityPolicyCandidate` | `ari/rqgm/utility_evolution.py` | Frozen dataclass; §6.2 layout; `to_dict()`. |
| `propose_utility_policy(...)` | `ari/rqgm/utility_evolution.py` | The four deterministic knob kinds as pure functions of `(incumbent_policy, evidence)`. No LLM, no clock, no randomness (P2; bound by the `kernel_rules.py:19-20` import-grep test extended to this module). |
| `UtilityPolicyStamp` | `ari/rqgm/utility_evolution.py` | §5.8 delta 2. Attached by `wrap_node_executor` only; writes `node.metrics["_utility_policy_hash"]`; best-effort, never raises into a node. |
| `capture_utility_policy(cfg, registries=None)` | `ari/rqgm/state.py:313-337` | **Changed, additively.** §5.7 precedence; the `registries=None` branch is byte-identical to today. |
| `freeze_epoch(...)` | `ari/rqgm/state.py:340-373` | **Changed, one line**: passes `registries` through (`:368`). Signature unchanged. |
| `founding_utility_policy_spec(cfg) -> PromptSpec` | `ari/rqgm/prompt_spec.py` | Pure; the epoch-0 policy as a founding (`active`-on-creation) spec, `template_ref={"kind": "policy", "path": …}`. |
| `founding_registration_events(cfg=None)` | `ari/rqgm/prompt_spec.py:407-418` | **Changed, additively.** `cfg=None` → today's exact sequence (every existing caller/test unaffected); with a cfg → the `utility_policy` row is appended after the prompt rows. Docstring amended: reproducible **for a fixed resolved cfg**. |
| `write_evolved_policy_body(ckpt, prompt_id, body_json)` | `ari/rqgm/prompt_loader.py` | Write-once `.json` sibling of `write_evolved_prompt_body` (`:62-81`); `PromptImmutabilityError` on differing bytes; identical re-writes idempotent (resume safety). |
| `GovernedPromptRegistry.resolve_text` | `ari/rqgm/registry.py:174-212` | **Changed, additively**: `source.kind == "policy"` reads the §6.1 body and applies the same hash refusal as `checkpoint_file` (`:205-210`). |
| `active_prompt_view(specs)` | `ari/rqgm/prompt_loader.py:84-96` | **Changed**: skips `template_ref.kind == "policy"` specs — a policy is never rendered (§5.3). |
| `ConstitutionalKernel.validate_utility_policy(policy)` | `ari/rqgm/kernel.py` | §5.6; pure; returns a `KernelReport`; called from `validate_transition` and the candidate pipeline's constitutional stage. |
| `UTILITY_POLICY_RULES`, `_UTILITY_POLICY_CAPS`, `CK-UTL-00{1..8}` | `ari/rqgm/kernel_rules.py` | §5.6/§5.2. Inside `_canonical_rules_payload` ⇒ inside `constitution_hash` ⇒ `_EXPECTED_CONSTITUTION_HASH` re-pinned (`test_rqgm_kernel.py:69`). |
| `EVOLVABLE_ROLES` += `policy_mutator`, `utility_policy` | `ari/rqgm/events.py:57-68` | §5.2; docstring amended (the roles are no longer all prompt-defined). |
| `META_EVOLVING_ROLES` += `policy_mutator`; `META_FROZEN_ROLES` −= `policy_mutator` | `ari/rqgm/meta_rules.py:92-108` | §5.2; the exit the module's own comment prescribes. |
| `FOUNDING_PROMPT_TABLE` += `policy_mutator_prompt_v1`; `FOUNDING_COMPONENT_TABLE` += `policy_mutator_v1`, `utility_policy_v1` | `ari/rqgm/prompt_spec.py:153-259` | §5.3; both roles are singletons ⇒ no rollup perturbation. |
| `REQUIRED_CONSTRAINTS_BY_ROLE` += `policy_mutator` | `ari/rqgm/prompt_spec.py:52-63` | §5.2; verbatim copy of the `prompt_mutator` clause. |
| `apply_utility_penalty(..., epoch_utility_policy=None)` | `ari/rqgm/adversarial/engine.py:979-1020` | **Changed, additively** (§5.8 delta 1). `None` ⇒ today's exact record. Co-owned with Task 06. |
| `FrontierRepairEngine.repair` | `ari/rqgm/frontier_repair.py:574+` | **Changed, additively** (§5.8 delta 2): a `role == "utility_policy"` retirement also invalidates nodes stamped with the retired hash. New module constant `UTILITY_POLICY_HASH_KEY` beside `:77-80`. Co-owned with Task 10. |
| `_active_evolvable_incumbents` | `ari/rqgm/runtime.py:676-724` | **Changed, one line**: `latest.pop(UTILITY_POLICY_ROLE, None)` (§5.3). |
| `RQGMRuntime._run_epoch_boundary` | `ari/rqgm/runtime.py` | **Changed, additively**: the `PolicyMutator` call joins `_run_meta_evolution` in the candidate-minting window; AND the pending utility_policy candidates' dry-run evaluations (`_utility_policy_candidate_evaluations`, §5.5 blocker 1) are merged into the `candidate_evaluations` passed to `resolve_transition` so the criterion iterates the spine. |
| `RQGMRuntime._utility_policy_candidate_evaluations` | `ari/rqgm/runtime.py` | **New** (§5.5 blocker 1). Per boundary, the §5.5 dry-run evaluation for every pending utility_policy registry entry (candidate/validated/shadow), merged into `candidate_evaluations`. Fail-open; reads the successor body write-once from the checkpoint (runtime-side, so `resolve_transition` stays pure). |
| `evaluate_utility_policy_candidate(...)`, `_axis_ranking_agreement(...)` | `ari/rqgm/utility_evolution.py` | **New** (§5.5). The deterministic §5.5 dry-run, emitting the FULL board the role-agnostic spine reads: **T1** kernel legality → `verdict` (illegal ⇒ `verdict: "fail"` with `replay_score: None` — the finding is the verdict, not a 0.0 nobody computed); **T3** `replay_score` = axis-ordering agreement over the policy's own dimensions (pool-independent) when the comparison RUNS, `None` when it cannot (empty static maps under the default `axis_mode: dynamic` — see §5.5's corrected scope note), `case_refs` = those dimensions; **T6** shadow = **VACUOUS by construction** (§5.5 "Honest scope of the SHADOW stage") ⇒ `shadow_samples: None`, `shadow_score: None`, `shadow_basis: "vacuous_passive_policy"`, plus the `no_replay_basis` (T3) + `no_shadow_basis` (T6) sentinels that waive the two COUNT floors by role at the decision site (`transition_engine.NO_REPLAY_BASIS_ROLES`). No field carries a quantity nothing produced. No LLM, no clock (P2). |
| `T20` (`active → retired`) | `ari/rqgm/transition_rules.py` `TRANSITION_TABLE` | **New rule** (§5.5, amended 2026-07-16): `superseded_by_adopted_successor`, guards `supersession_successor_adopted` / `utility_policy_role_only` / `emits_retirement_event`. Grows the table 19→20 ⇒ `constitution_hash` re-pin (`_EXPECTED_CONSTITUTION_HASH`, §8.6). |
| `RegistryTransitionEngine._maybe_supersede_utility_policy` | `ari/rqgm/transition_engine.py` | **New** (§5.5): inside a same-role T6 adoption with no opening (healthy incumbent), emits the T20 retirement for the incumbent policy prompt (old hash + role). Scoped to `utility_policy` AND bare-prompt candidates; behavioural roles never reach it. |
| `RegistryTransitionEngine._attach_utility_policy_bodies` | `ari/rqgm/transition_engine.py` | **New** (§5.6 blocker 4): apply-side, resolves each utility_policy adoption's body and attaches `entry["policy"]` so the kernel legality gate fires on the LIVE path. Keeps `resolve_transition` pure. |
| `ConstitutionalKernel._change_violations` | `ari/rqgm/kernel.py` | **Changed** (§5.5): role-scopes T20 — `active → retired` yields `CK-REG-001` for every role except `utility_policy`, so behavioural retirement still stages via quarantine. |
| `rqgm/policy_mutator.md` | `ari-core/ari/prompts/rqgm/` | New committed template (externalized from day one, `scripts/check_prompts.py` doctrine); consumed only by the opt-in `freeform_policy_proposal` kind. |

## 8. Migration / compatibility

1. **`simple_bfts` is identity.** No RQGM import, no role, no registry, no sentinel, no file. The
   only code this task touches on a `simple_bfts` path is `capture_utility_policy`'s signature —
   which `simple_bfts` never calls. Task 00's must-not-break register (00 §5.8, B-1…B-19) holds
   verbatim, including B-17 (which this task now *answers* rather than preserves — see §5.10).
2. **`rqgm.utility_evolution.enabled: false` is today's behavior exactly.** `PolicyMutator` is never
   constructed, no candidate is minted, no adoption resolves, `active_prompt_hashes` still carries
   the founding `utility_policy` entry, and `capture_utility_policy` returns the founding policy —
   which is `capture_utility_policy(cfg)` — in every epoch. The hash is constant again, i.e. exactly
   the pre-14 system, reachable by one flag. This is the ablation rung 13 §5.10 needs.
3. **`ari_rqgm` epoch-0 identity changes, deliberately.** Two founding prompt rows and two founding
   component rows change `registry_version()` (`registry.py:214-225`) and therefore the `epoch_000`
   `epoch_fingerprint` for every `ari_rqgm` run. This is unavoidable — the registry genuinely
   contains two more governed objects — and it is declared here so the diff to
   `test_rqgm_founding_bootstrap.py:77-88` (which pins the founding id sets and the eight-role
   `active_prompt_hashes` set, now ten) is a reviewed expectation update, not a surprise.
   `test_rqgm_epoch_state.py:361`'s `utility_policy_hash == "b192196ced57"` pin **stays green**: it
   exercises `freeze_epoch` over fixture registries with no `utility_policy` entry, i.e. §5.7
   branch 2, i.e. the cfg fallback.
   This identity change — together with the `CONSTITUTION_HASH` re-pin in item 6 — is the largest
   blast radius in this plan set, and it was **reviewed and accepted by the author (2026-07-16)** on
   the ground that P1 ("at epoch boundaries the entire score is rewritten") cannot be honoured by a
   registry that does not contain the policy as a governed object. It is recorded here as an
   accepted decision so that a reviewer meeting the `epoch_000` diff does not re-open it.
4. **Old records stay valid.** A pre-14 `UtilityRecord` carries the penalty-policy hash under
   `utility_policy_hash`/`prompt_hash` and a `frozen_policy` with only the three required keys. It
   validates against the amended schema (the new sub-object is optional), it recomputes correctly
   (`MetricRecomputer` reads only the three keys, `frontier_repair.py:401-404`), and it simply never
   matches a `utility_policy` retirement — which is precisely today's behavior. No migration script,
   no rewrite of an append-only log (invariant 13 forbids it anyway).
5. **Old checkpoints resume.** A checkpoint whose registry has no `utility_policy` entry takes §5.7
   branch 2 forever: the run continues with a constant policy, exactly as it was launched. Founding
   registration is skipped for a non-empty registry (`runtime.py:370-374`), so a resumed pre-14 run
   is never retro-fitted mid-flight — a run's governed object set is fixed at its founding, which is
   the same rule 01 §5.5 applies to the mode itself.
6. **CONSTITUTION_HASH re-pin is a reviewed diff**, in the same commit, following the two
   documented precedents (`kernel_rules.py:125-133`, `:224-233`): the amendment is explained in a
   code comment naming what changed and why, and `_EXPECTED_CONSTITUTION_HASH` is updated in
   `test_rqgm_kernel.py`. **Two causes re-pin it here**: the `UTILITY_POLICY_RULES` +
   `CK-UTL-00{1..8}` addition (§5.6) AND the **T20** table row (§5.5, amended 2026-07-16) — both are
   inside `_canonical_rules_payload`. The table-size (`19 → 20`) and forbidden-edge assertions in
   `test_rqgm_kernel.py` / `test_rqgm_transition_engine.py` are updated in the same reviewed diff.
7. **Zero contract churn.** No CLI command/flag, no `ari.public.*` symbol, no MCP tool ⇒
   `scripts/snapshot_contracts.py --surface cli --check` and `--surface public --check` stay green
   with no golden regeneration (01 §4 budget decision).
8. **Fail-open at the loop, fail-closed at the constitution.** A `PolicyMutator` failure degrades to
   "no candidate this epoch" (`runtime.py:973-976` posture); a policy that fails §5.6 is **blocked**
   — the boundary proceeds with the incumbent policy, which is always safe because the incumbent is
   what produced the current frontier. There is no path in which a rewrite fails *open* into an
   unvalidated score.

## 9. Tests

Unit — new `ari-core/tests/test_rqgm_utility_evolution.py` (listed in `ari-core/tests/README.md`
for the readme-sync gate):

- **Role vocabulary.** `utility_policy` and `policy_mutator` ∈ `EVOLVABLE_ROLES`; `ROLES` ==
  `EVOLVABLE_ROLES + FIXED_ROLES` with no duplicates; `policy_mutator` ∈ `META_EVOLVING_ROLES` and
  ∉ `META_FROZEN_ROLES`; **the limbo regression test**: every role named by
  `frontier_repair.INVALIDATE_ROLES` ∪ `RECOMPUTE_ROLES` ∪ `{records.UTILITY_POLICY_ROLE}` is a
  member of `events.ROLES` (this test fails on today's code — it is the diagnosis, executable).
- **Capability parity** (the `failure_summary_compressor` regression, `kernel_rules.py:125-133`):
  every member of `events.EVOLVABLE_ROLES` has at least one `CAPABILITY_MATRIX` row, so no role is
  CK-ACC-001-blocked in every tier; `("utility_policy", "institutional")` grants exactly
  `{("read","records"), ("append","records")}` and no `invoke`/`write`/`activate`.
- **`capture_utility_policy` precedence.** `registries=None` → byte-identical to today (assert
  against the frozen dict from `test_rqgm_epoch_state.py:379-392`); registries without a
  `utility_policy` entry → the cfg branch; registries **with** an active entry → the adopted body,
  and `policy["utility_policy_hash"] == entry.prompt_hash`; tampered body bytes → cfg fallback +
  WARNING, never a raise.
- **The identity bridge.** For any legal policy body, `hash12(canonical_json(body))` ==
  `capture_utility_policy`'s hash over the same body == the founding entry's `prompt_hash` — one
  value, three names (§5.3).
- **`PolicyMutator`.** No registry/store write surface (attribute test); each knob kind is pure and
  deterministic (same inputs → identical candidate, twice, in separate processes); an unknown kind →
  `None` + warning; over-budget → `None` (via `candidate_budget_reason` on role `utility_policy`);
  `freeform_policy_proposal` with `llm=None` → `None`; a candidate never carries raw attack text.
- **`validate_utility_policy`.** One case per CK-UTL code; the `{novelty: 1.0}` axis-abolition
  candidate is CK-UTL-004-blocked; a policy naming a composite outside
  `EvaluatorConfig.composite`'s Literal (`config/__init__.py:224-228`) is CK-UTL-002-blocked; a
  stale axis key under `axis_mode: dynamic` is CK-UTL-006 **warn**, not block; sum-to-one is checked
  within `rqgm.kernel.float_tolerance`.
- **Constitution.** `CONSTITUTION_HASH` changes when `UTILITY_POLICY_RULES` changes and is stable
  otherwise; `_EXPECTED_CONSTITUTION_HASH` matches the new value in all six assertion sites.

Integration (`ari-core/tests/test_rqgm_utility_boundary.py`) — **the P1 test (NATURAL PATH)**:

- **The primary P1 proof drives the natural path** (`test_p1_epoch_boundary_rewrites_the_entire_score`).
  It boots a real `ari_rqgm` runtime at **default config** and drives real boundaries through
  `ensure_epoch → _run_epoch_boundary` — it **hand-builds NO transition**. The mint → evaluate →
  supersede → retire spine runs entirely on its own (candidate → validated (T1) → shadow (T3) →
  probationary_active + incumbent retired (T6 + T20)), and the test only OBSERVES, asserting, in the
  plan's order:
  1. the rewrite epoch's `utility_policy["utility_policy_hash"]` **differs from the prior epoch's**
     — the score was rewritten, by the engine, with no help from the test;
     `active_prompt_hashes["utility_policy"]` is the new hash (the same map CK-EPO-001 reads);
  2. `epoch_fingerprint` changed — the rewrite is inside the epoch identity (`state.py`);
  3. the committed transition carries a **T20** retirement with `role == "utility_policy"` and
     `prompt_hash ==` the retiring policy's hash (the `retirement_event` audit), and no
     `no_governance_report` note — the audit actually ran;
  4. every node scored under the old policy is `_valid_for_frontier is False` with
     `_stale_reason == "utility_invalidated"` (reached through the node's own `_utility_policy_hash`
     provenance, §5.8 delta 2) — no recompute laundered it;
  5. `MetricRecomputer` was not invoked for any of them (invalidate, never re-weight);
  6. **MUTATION-CHECK.** Breaking any one spine link turns assertion 1 red — verified empirically by
     killing the evaluation merge (blocker 1) and the supersession branch (blocker 2): each freezes
     the run to a single distinct hash across ≥3 boundaries.
- **The kernel gate on the LIVE path** (`test_kernel_blocks_an_illegal_candidate_on_the_live_adoption_path`):
  an ILLEGAL successor that slips a fabricated passing evaluation past the T1 legality gate is still
  **blocked at the T6 adoption** by `validate_transition → validate_utility_policy` once `apply`
  attaches its body (§5.6 blocker 4); the transition aborts (CK-UTL-*), the incumbent keeps serving,
  and the hash is unchanged — no rewrite fails OPEN into an unvalidated score.
- **The proposer keeps offering successors** (`test_the_proposer_keeps_offering_successors_across_boundaries`):
  driving ≥12 boundaries, the lineage climbs `v2 → v3 → …` (the dead spine minted exactly one
  candidate then went silent — blocker 3).
- **The downstream consequence, in isolation** (`test_downstream_consequence_of_a_hand_built_transition`):
  the OLD hand-built machinery, re-purposed and explicitly labelled NOT the P1 proof — GIVEN a
  committed retirement, `frontier_repair` invalidates old-policy nodes. It proves the consequence
  side alone; it does not (and must not be read to) prove the natural path produces a transition —
  that conflation is exactly what a green suite once hid.
- **Ungoverned smuggling still blocked** (§5.9): in the same run, a node that returns
  `axis_weights` through `make_metric_spec` is suppressed by `MetricSpecWeightCap` and audited as
  `metric_spec_weight_override_suppressed` (`meta_evolution.py:1280-1291`) — a governed rewrite does
  not open an ungoverned channel.
- **P2 / no collusion**: a `PolicyMutator` handed evidence that would reward the current frontier's
  own top nodes produces a candidate identical to one produced from the abstract evidence alone —
  the proposer cannot see scores, so it cannot tune the score to flatter its own tree.
- **P3 / no absolute ruler**: `policy_mutator_v1` is a registered active component after bootstrap;
  a governance recommendation against it resolves into a T9/T10/T11 sanction rather than being
  silently dropped; `resolve_emergency_quarantine` against it is not rejected as an unknown
  component (`transition_engine.py:692`); a sanctioned `policy_mutator` mints no candidates.
- **P4 / constitutional binding**: an illegal candidate never reaches `probationary_active` — the
  T1 guard blocks it at `candidate → validated`, the audit log records the violation code, and the
  epoch freezes the incumbent policy.

Regression (must stay green untouched):

- The full existing ari-core suite (CI `refactor-guards.yml`).
- `test_rqgm_epoch_state.py:361` (`b192196ced57`) and `:379-392` — the cfg fallback is byte-identical.
- `test_rqgm_prompt_spec.py:222-226` — every `evolvable=True` founding spec's role ∈
  `EVOLVABLE_ROLES` (now true of `utility_policy_prompt_v1` and `policy_mutator_prompt_v1` **because
  of** §5.2, which is the point).
- Default `ari run` smoke: no `rqgm_prompts/` directory, no `_utility_policy_hash` key in any
  `tree.json` node, no `ari.rqgm.*` in `sys.modules`.

Deliberately updated expectations (reviewed diffs, §8.3): `test_rqgm_prompt_spec.py:111-117`
(founding inventory + the new template key) and `test_rqgm_founding_bootstrap.py:77-88` (founding id
sets; `active_prompt_hashes` roles 8 → 10; `active_components` gains `policy_mutator_v1` and
`utility_policy_v1`).

CI placement: plain ari-core tests; no new workflow. Any future RQGM-specific checker follows the
Stage-1-advisory-first policy.

## 10. Risks

- **R1 — Mass invalidation empties the frontier.** A utility rewrite invalidates every node scored
  under the old policy (§5.8 delta 2). At an early boundary that can be the whole tree, and
  `rebuild_frontier` (`frontier_repair.py:288-304`) would return a small or empty list. Mitigation:
  `rqgm.utility_evolution.min_epochs_between_rewrites` (§6.3); `max_adoptions_per_role_per_boundary:
  1` caps it at one rewrite per boundary; the run never crashes (the `conservative` →
  `halted_expansion` ladder, `frontier_repair.py:735-748`, already handles an empty frontier by
  draining). **Accepted as the honest cost of P1**: if a score rewrite were cheap, it would not be a
  rewrite. The ablation rung (§5.10, 13) is where the cost/benefit is measured rather than asserted.
- **R2 — Two policies, one name.** `utility_policy_hash` means the epoch policy in `state.py` and
  the penalty policy in `adversarial/engine.py` (§5.8). Delta 1 makes the record's field mean the
  epoch policy, which is a **semantic** re-point of a field whose value nothing reads today. Risk:
  a future reader of an old JSONL misinterprets a pre-14 record. Mitigation: the schema description
  records the change and the version boundary; `frozen_policy` carries both policies by value from
  here on, so a record is self-describing without a registry lookup — which was already the design
  intent (`records.py:616-618`).
- **R3 — Task 06 / Task 10 co-ownership.** Delta 1 touches `adversarial/engine.py` (Task 06's
  module) and delta 2 touches `frontier_repair.py` (Task 10's). Both are additive and both are
  argued from those modules' own stated contracts, but neither plan is deletable until its owner has
  signed the change. Recorded here so the dependency is visible rather than discovered at merge.
- **R4 — The proposer is a new authority.** Something now proposes the score. Mitigation is the
  whole of §5.4/§5.6: it is deterministic by default; it may only emit candidates
  (`META_HARD_DENIED_FLAGS`, `meta_rules.py:44-53`, makes the alternative a schema violation); it
  cannot see scores; its output is kernel-validated against frozen bounds; it is itself a
  registered, sanctionable, evolvable component (P3). The residual risk — a proposer that gradually
  steers the axes toward what it can satisfy — is exactly what the axis floor
  (`axis_weight_min: 0.05`) and the ablation rung exist to bound and to detect.
- **R5 — Determinism of the freeform kind.** `freeform_policy_proposal` consults an LLM, so a run
  that enables it loses byte-reproducibility of its candidate stream (P2's standing tension with
  every LLM-backed evolution path in this package). Mitigation: it is **off by default**
  (§6.3 `mutation_kinds`); the resulting candidate is still kernel-validated and still hash-pinned,
  so an irreproducible *proposal* can never become an unvalidated *policy*.
- **R6 — `registry_version` becomes cfg-dependent.** §5.3/§8.3. Two `ari_rqgm` runs with different
  `axis_weights` now have different `epoch_000` registry versions. Accepted: the epoch fingerprint
  was always cfg-dependent (`state.py:270`), so this aligns the two identities rather than splitting
  them. The alternative — a founding policy that ignores cfg — would silently discard every user's
  configured weights at epoch 0, which is a far worse surprise.
- **R7 — The `policy` source kind widens `resolve_text`.** `registry.py:174-212` is a small
  dispatcher; a third kind is a third code path that a future reader might extend to a fourth. Guard:
  the kind vocabulary is closed in `TEMPLATE_REF_KINDS` (`prompt_spec.py:44`) and its parity with
  the dispatcher is asserted; `active_prompt_view` filters policies out so the loader's raise
  (`prompt_loader.py:147-150`) stays unreachable rather than merely unreached.
- **R8 — Reviewers read §5.9 as a contradiction.** "Weights are capped" and "weights are rewritten"
  are adjacent sentences. Guard: §5.9 is written to be quoted, and the completion criteria (§11.8)
  require the distinction to land in a permanent doc, not only here — the plan file is deleted, the
  confusion would not be.

## 11. Completion criteria

This task is complete when all of the following hold:

1. **The limbo is closed** — `utility_policy` and `policy_mutator` are members of
   `EVOLVABLE_ROLES` (`events.py:57-68`), `policy_mutator` has moved from `META_FROZEN_ROLES` to
   `META_EVOLVING_ROLES` (`meta_rules.py:92-108`), both have `CAPABILITY_MATRIX` rows, and the
   executable regression test (§9: every role named by `INVALIDATE_ROLES` / `RECOMPUTE_ROLES` /
   `UTILITY_POLICY_ROLE` is in `events.ROLES`) passes.
2. **The governed object exists** — a `utility_policy_v1` component and a
   `utility_policy_prompt_v1` policy-backed spec are registered at founding, their `prompt_hash` is
   `utility_policy_hash` by construction (§5.3), and the body is stored write-once under
   `{ckpt}/rqgm_prompts/` with the hash refusal on read.
3. **The proposer exists and is governed** — `PolicyMutator` emits candidates only, is
   deterministic by default, and `policy_mutator_v1` is a registered, sanctionable, evolvable meta
   component that holds no authority the other meta agents lack and enjoys no immunity they lack.
4. **The adoption path runs** — a utility-policy candidate traverses T1 → T3 → T6 → T7 on the
   T-table, at most one rewrite per boundary, with the healthy incumbent **superseded** (retired by
   **T20**, the new `active → retired` role-scoped edge, §5.5) in the same transaction. The path is
   proven on the **natural** boundary flow, not a hand-built transition (§9).
5. **Legality is constitutional** — `UTILITY_POLICY_RULES` and `CK-UTL-00{1..8}` are frozen code
   inside `constitution_hash`, `_EXPECTED_CONSTITUTION_HASH` is re-pinned, and an illegal candidate
   is blocked before it can ever score a node.
6. **The core change is in** — `capture_utility_policy(cfg, registries)` reads the adopted policy
   with the cfg fallback at epoch 0 / `simple_bfts` / pre-14 resume, `freeze_epoch` passes
   `registries`, and `utility_policy_hash` is demonstrably **not** constant across a run's epochs.
7. **The circuit is closed** — the P1 integration test (§9) passes end to end: a boundary rewrites
   the policy, the fingerprint changes, the incumbent is retired, and **every** node scored under
   the old policy leaves the frontier flagged `utility_invalidated`, with no recompute.
8. **I-11 is overturned in writing** — all six reliance sites (01:465, 06:630, 07:632, 09:540,
   10:515, 13:435) say what §5.10 requires, `INDEX.md`'s global invariant reads "frozen per epoch,
   rewritten at boundaries through the governed path", and the governed-rewrite ↔ ungoverned-smuggle
   distinction (§5.9) is stated where a reader of `MetricSpecWeightCap` will find it.
9. **Nothing else moved** — `simple_bfts` is byte-identical (full suite + the §9 identity
   assertions), `MetricSpecWeightCap` is unchanged, no second comparability apparatus exists, and
   the paper set cites this plan instead of forking it.

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

- The §5.3 decision (policy-backed PromptSpec, not a `UtilitySpec` analog) and its rationale live in
  a permanent doc or in `prompt_spec.py` / `registry.py` module docstrings — a future reader must
  not have to re-derive why a policy is a "prompt".
- The §5.8 two-hash reconciliation is recorded in `rqgm_utility_record.schema.json`'s description
  and in `adversarial/records.py`'s `UtilityRecord` docstring, replacing the "not prompt-backed"
  sentence, so the version boundary in the JSONL is self-documenting.
- The §5.9 distinction (governed boundary rewrite vs ungoverned weight smuggling) is in
  `MetricSpecWeightCap`'s class docstring and in the permanent RQGM developer guide.
- The I-11 repeal has landed in every §5.10 site **and** in the permanent execution-mode /
  architecture docs — the invariant is quoted outside `docs/plans/`, so deleting the plans must not
  resurrect the old text.
- The P1 integration test (§9) exists, is green in CI, and is named such that a future contributor
  who breaks the rewrite sees why.
- Task 06 and Task 10 have accepted their co-owned deltas (R3), or the deltas have been re-homed.

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

- [ ] `utility_policy` and `policy_mutator` are in `EVOLVABLE_ROLES` and in the capability matrix;
      the role-limbo regression test passes.
- [ ] `utility_policy_v1` / `utility_policy_prompt_v1` / `policy_mutator_v1` /
      `policy_mutator_prompt_v1` are founding registrations; the founding-inventory and
      `active_prompt_hashes` expectations were updated as reviewed diffs.
- [ ] `capture_utility_policy(cfg, registries)` reads the adopted policy; `freeze_epoch` passes it;
      the epoch-0 fallback pin (`test_rqgm_epoch_state.py:361`) is still green.
- [ ] `UTILITY_POLICY_RULES` + `CK-UTL-00{1..8}` are frozen code; `_EXPECTED_CONSTITUTION_HASH` is
      re-pinned in all six sites with an amendment comment.
- [ ] The P1 integration test asserts: hash changed, fingerprint changed, incumbent retired,
      old-policy nodes `utility_invalidated`, no `no_governance_report` note, no recompute.
- [ ] `MetricSpecWeightCap` is unchanged and its docstring carries the §5.9 distinction.
- [ ] `_utility_policy_hash` is never written under `simple_bfts`; default runs have no
      `rqgm_prompts/`.
- [ ] I-11's repeal is published in the permanent docs and reflected at 01:465, 06:630, 07:632,
      09:540, 10:515, 13:435 and in INDEX.md.
- [ ] `capture_utility_policy`'s docstring (`ari-core/ari/rqgm/state.py:318-320`) no longer defers
      per-epoch re-weighting to "a Task 10/13 decision" — this task is that decision, so the
      citation is stale the moment the code lands.
- [ ] Task 06 (record delta) and Task 10 (repair delta) have signed off, or the deltas are re-homed.
- [ ] The paper set's Task-14 inheritance statement points here and defines no local utility
      machinery.
