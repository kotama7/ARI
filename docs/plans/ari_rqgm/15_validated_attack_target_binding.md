# Task 15: ValidatedAttackRecord Target Binding

> **Status**: planned · **Depends on**: 05, 06 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

> **2026-07-28 implementation amendment.** The historical plan below records
> the original paper-role-only landing and is retained for audit history.
> The research `generator` is now a founding registered component.
> `RQGMRuntime` stamps each node once with producer component, prompt hash,
> and epoch before persistence/adversarial review. The seven exploration case
> types resolve to that generator only when the stamp matches the epoch-frozen
> incumbent; legacy, missing, or mismatched provenance remains targetless.
> Therefore statements below that the generator is unregistered or the seven
> types are necessarily unbound are superseded by this amendment.

## 1. Purpose

A validated attack proves — after a Defender response and an ArtifactJudge verdict — that a
governed component's output was defective. Task 05 designed the consequence: the
ReliabilityMonitor counts the attacks a component is implicated in, the Prosecutor files an
impeachment motion at `ATTACK_THRESHOLD` (`ari-core/ari/rqgm/governance/_prosecution.py:34`,
`:91-92`), and the RegistryTransitionEngine lands the sanction. **That chain has never been
reachable.** `build_reliability_entries` counts `ValidatedAttackRecord`s whose
`target_component_id` matches the component
(`ari-core/ari/rqgm/governance/_reliability.py:37-39`, `:60-64`), and the sole producer —
`ValidatedAttackRecord.to_dict` (`ari-core/ari/rqgm/adversarial/records.py:475-499`) — **never
emits that key**. `validated_attack_involvement` is therefore structurally `0` for every
component in every epoch, for all seven exploration adversaries
(`ari-core/ari/rqgm/adversarial/engine.py:463-491`) and for the paper set's eighth
(`paper_self_preference`, [../ari_rqgm_paper/05](../ari_rqgm_paper/05_adversarial_self_preference.md)).

This is a **pre-existing defect in shipped code**, discovered during the paper-set pillar audit,
not a missing feature of a future task. It is invisible in CI because
`ari-core/tests/test_rqgm_governance.py:100-107` exercises the counter with **hand-built dicts**
that carry `target_component_id="reviewer_v3"` — a key no production record has ever had — and
because no caller passes `affected_components` either (`round.py:227`,
`ari-core/ari/rqgm/evaluation/smoke.py:212-214`). The fixture proves the consumer; nothing proves
the producer.

This task designs the one field that closes it, and only that field:

- `target_component_id` on `ValidatedAttackRecord`, emitted **only when non-empty**;
- the deterministic role → epoch-frozen-`component_id` resolution that fills it at construction;
- which case types bind a target today and which provably cannot yet;
- the regression that keeps every existing record byte-identical.

**Why it matters.** This field is the only thing standing between a *detected* component and an
*accountable* one. It serves the method's defining pillars directly: **P2** — attacks on
artifacts and evaluations must have consequences, and a consequence that cannot be counted is not
a consequence; **P3** — the adversary is inside the audit network and holds no unilateral power,
so its findings must reach a *distinct* prosecutor to bite at all; **P4** — the constitution's
impeachment chain is invoked by evidence, and unbound evidence invokes nothing. Two downstream
paper-set plans are blocked on this task and say so:
[../ari_rqgm_paper/05](../ari_rqgm_paper/05_adversarial_self_preference.md) §10 R7 (the
field layer of its two-layer bridge) and
[../ari_rqgm_paper/07](../ari_rqgm_paper/07_claim_gate_handoff_and_evaluation.md) §5.8 PI3 (whose
control assertion — a motion filed against a scripted `always_accept` `paper_reviewer` — is the
anti-collusion regression test).

## 2. Scope

- One additive field on `ValidatedAttackRecord` (`records.py:443-499`) with a **conditional**
  `to_dict` emit and a symmetric `validated_from_dict` read.
- The `target_component_id` passthrough on `make_validated_attack_record` (`records.py:529-576`)
  and its constructive-prevention rule (no self-binding), plus the matching deterministic
  re-check in `validated_attack_violations` (`records.py:579-606`).
- The producer-side resolution in `AdversarialRound` (`round.py:220-233`): implicated ROLE →
  epoch-frozen active `component_id`, using the round's existing `_active_components()` map
  (`round.py:131-141`).
- The **binding table**: which `case_type` names which accountable role, and the proof that the
  seven exploration types resolve to nothing today (§5.4).
- One optional property added to the `validated_attack` branch of
  `ari-core/ari/schemas/rqgm_attack_records.schema.json` (`:153-189`), additive-only per that
  schema's own evolution policy (`:5`).
- The byte-identity regression: existing records' JSON is unchanged; the round-trip identity at
  `ari-core/tests/test_rqgm_adversarial.py:248-251` holds.
- The end-to-end test that the chain now closes: 2 bound validated attacks → `classify_target`
  → `file` → motion → `resolve_transition` (§9).

## 3. Non-goals

- **No new config key.** Constitutional accountability is not opt-out; a
  `rqgm.adversarial.bind_targets` flag would let a run turn impeachment off silently. The field
  is gated only by whatever already gates the adversarial loop (`rqgm.adversarial.enabled`,
  `round.py:168-169`) and by `ari.mode` / `paper.mode` upstream.
- **No new record type, no new checkpoint file, no new store.** Validated attacks ride
  `rqgm_adversarial_cases.jsonl` + `rqgm_audit.jsonl`, both already registered
  (`ari-core/ari/paths.py:84`, `:455-456`).
- **No change to artifact-only targeting.** The *adversary* still attacks artifacts and only
  artifacts: `TARGET_ARTIFACT_TYPES` (`records.py:53-64`) and `raw_attack_violations`'
  smuggle check (`records.py:291-297`) are untouched. The binding designed here exists **only on
  the post-adjudication, judge-authored record** — see §5.2.
- **No `affected_components` rename, no `affected_components` population for the seven**
  (§5.5).
- **No `UtilityRecord` target binding.** `UtilityRecord.to_dict` (`records.py:640-660`) has the
  same gap, and `_evidence.py:64` admits utility records as evidence when they name a target.
  Out of scope: the penalty channel's target is the *node*, not a component, and re-pointing it
  is a Task 10 recompute-contract question. Recorded as R5.
- **No registration of a `generator` / `reviewer` component** to give the seven exploration
  adversaries a resolvable target. `FOUNDING_COMPONENT_TABLE`'s stated contract is "one entry per
  component id the RUNTIME actually stamps today" (`prompt_spec.py:219-231`); nothing stamps a
  generator id. That is a Task 05/07 decision (R2), not a side effect of this fix.
- **No governance-side change.** `_reliability.py`, `_prosecution.py`, `_evidence.py` are read as
  specifications and consumed unchanged. If this task has to edit a consumer, the diagnosis was
  wrong.
- No re-weighting of `reliability_score` (the audit's optional score-path channel): the attack
  path is the control channel here, and the ratio arithmetic at `_reliability.py:114` is a Task
  05 concern (R4).
- No implementation in this plan (design only; implementation is a deletion-criteria item).

## 4. Existing ARI touchpoints

All paths repo-relative. Verified against branch `RQGM` (ari-core v0.9.1).

| Touchpoint | File / symbol | Why it matters here |
|---|---|---|
| The broken producer | `ari-core/ari/rqgm/adversarial/records.py` — `ValidatedAttackRecord` (line 443), `to_dict` (line 475), `affected_components` (line 464) | THE defect. `to_dict` emits 22 keys; `target_component_id` is not among them (`:475-499`). `affected_components` is emitted (`:495`) and deserialized (`:514-516`) and read by nothing: `grep -rn affected_components ari-core/ari/rqgm --include=*.py` returns only `records.py`. |
| The consumer that decides | `ari-core/ari/rqgm/governance/_reliability.py` — `build_reliability_entries` (line 31), the counter (lines 60-64), the entry (lines 120-135) | `if rtype == "validated_attack": target = str(rec.get("target_component_id",""))` — the key that never exists ⇒ `attacks_by_target` is always empty ⇒ `validated_attack_involvement: 0` for every entry (`:126`). Its own docstring (`:37-39`) documents the contract the producer never met. |
| The prosecution threshold | `ari-core/ari/rqgm/governance/_prosecution.py` — `ATTACK_THRESHOLD = 2` (line 34), `classify_target` (lines 87-102), `_deterministic_charge` (lines 105-109) | With involvement pinned at 0, `classify_target`'s attack branches (`:91-92`, `:95-96`) are dead code; only the `reliability_score` branch can ever fire, and only for components that author records. |
| The evidence bundle (second consumer of the same key) | `ari-core/ari/rqgm/governance/_evidence.py` — `candidate_refs_for_target` (lines 44-71), `ADMISSIBLE_KIND_BY_TYPE` (lines 29-36) | `validated_attack` is an admissible kind (`:31`), but a validated attack can only be *selected* for a target via `target_component_id` (`:56-63`). Without it, a validated attack reaches a bundle only indirectly, as a `source_refs` lead of a same-role ComparisonObservation (`:64-70`). ⇒ even a floor-triggered motion finds `no_admissible_evidence` (`_prosecution.py:170-177`). **One field feeds both the threshold and the evidence.** |
| The producer's call site | `ari-core/ari/rqgm/adversarial/round.py` — the validation loop (lines 220-233), `make_validated_attack_record(...)` (line 227) | The only production caller. It passes `expected_behavior` and nothing else — no `affected_components`, no target. This is where the resolution lands (§5.3). |
| The epoch-frozen active map | `ari-core/ari/rqgm/adversarial/round.py` — `_active_components` (lines 131-141) | Already present, already injected into all three actors (`:103`, `:110`, `:117`): the frozen epoch's `role -> component_id` map from Task 02 `EpochState`; `{}` while no epoch is open. This is the resolution source (§5.6) — **no new constructor parameter, no registry handle**. |
| The role-resolution idiom | `ari-core/ari/rqgm/adversarial/engine.py` — `_PromptedActor._component_id` (lines 520-543); `ari-core/ari/rqgm/governance/_pipeline.py` — `_actor_id` (lines 279-288), called at `:417-420`; `_reliability.py:73-79` | The sanctioned shape: read `active_set()` / the frozen map, fall back deterministically, never raise (`engine.py:532-537`). The target lookup is the same shape with one deliberate difference — no family guard (§5.6). |
| Where record ids already come from | `ari-core/ari/rqgm/adversarial/engine.py:738-740` (`component_id=self._component_id("adversary", f"adversary_{spec.adversary_type}_v1")`); `records.py:571-573` | The judge's own `component_id`/`prompt_hash`/`epoch_id` are copied onto the validated record from the judgment, which resolved them through the same frozen map. Resolving the *target* from any other source would mix a frozen author with a live target in one record. |
| The registered role set | `ari-core/ari/rqgm/prompt_spec.py` — `FOUNDING_COMPONENT_TABLE` (lines 232-259) and its contract docstring (lines 219-231); `ari-core/ari/rqgm/events.py` — `EVOLVABLE_ROLES` (line 57), `FIXED_ROLES` (line 73), `ACTIVE_STATUSES` (line 51) | Registered roles today: `adversary` (×7), `judge`, `defender`, `router`, `prompt_mutator`, `clean_room_generator`. **No `generator_v1`, no `reviewer_v1`** — which is exactly why the seven exploration types resolve to nothing and stay byte-identical (§5.4). |
| The second producer (eval harness) | `ari-core/ari/rqgm/evaluation/smoke.py:200-219` — `_run_adversarial_stubs` | Calls `make_validated_attack_record(judgment, attack, record_id=...)` with no target and appends `validated.to_dict()` straight to the audit log (`:212-214`). Proof the seam is parent-level, not paper-shaped. Unchanged by this task (§8.4). |
| Record schema | `ari-core/ari/schemas/rqgm_attack_records.schema.json` — the `validated_attack` branch (lines 153-189), `affected_components` (lines 174-177), `required` (lines 181-188) | The branch sets no `additionalProperties: false`, and branch selection is by `record_type` const (`:156`), so the new key cannot break `oneOf` matching. Adding an optional property is exactly the "Additive-only evolution" the schema description pins (`:5`). |
| Kernel schema check | `ari-core/ari/rqgm/kernel.py` — `validate_record_schema` (lines 321-351) | Envelope-based; never rejects unknown keys. The new field needs no kernel rule and moves no `CONSTITUTION_HASH`. |
| The dict-only fixture that hid the bug | `ari-core/tests/test_rqgm_governance.py` — `_clear_case_log` (lines 97-112), `_reviewer_records` (lines 83-95) | `_rec("validated_attack", ..., target_component_id="reviewer_v3")` — a synthetic shape no production record has. §9 pins the producer against the same key so the fixture and the record can never diverge again. |
| Round-trip identity | `ari-core/tests/test_rqgm_adversarial.py:248-251` (`assert from_dict(d).to_dict() == d`), the schema round-trip block (`:226`, `:304`) | The conditional emit must survive `to_dict → from_dict → to_dict` in both the empty and populated cases. |
| Downstream observability | `ari-core/ari/rqgm/evaluation/metrics.py:600-620` | The Task 13 channel extractor reads `impeachment_motion.target_component_id`; a motion only exists downstream of this field, so the eval harness's governance channel is currently unreachable for adversarial causes. |
| The blocked paper plans | `docs/plans/ari_rqgm_paper/05_adversarial_self_preference.md` §5.4 + §10 R7; `docs/plans/ari_rqgm_paper/07_claim_gate_handoff_and_evaluation.md` §5.8 PI3 | Doc 05 owns *which roles* are implicated (`_AFFECTED_ROLES_BY_TYPE["paper_self_preference"] = ("paper_reviewer", "paper_writer")`, one validated record per resolvable role — §5.3) and states the chain is unreachable until this task lands; doc 07's PI3 control assertion is the regression that proves it landed. |

## 5. Proposed design

### 5.1 The defect, stated exactly: a two-layer mismatch

The record and the consumer disagree on **two** independent axes, and fixing either alone changes
nothing:

| Layer | What the record has | What governance reads | Effect |
|---|---|---|---|
| **Field name** | `affected_components` (`records.py:464`, emitted `:495`) | `target_component_id` (`_reliability.py:61`, `_evidence.py:58`, and `ImpeachmentMotion.target_component_id` `governance/_records.py:208`) | The counter's `rec.get("target_component_id","")` is always `""`; the branch at `_reliability.py:62` never runs. |
| **Value space** | a ROLE string (`"paper_reviewer"`, `"generator"`) — the only thing an attack can honestly know | a COMPONENT ID (`"paper_reviewer_v1"`, `"reviewer_v3"`) — what the registry sanctions (`transition_engine.py:669`, `:692`) | Even a rename would bind an accusation to a name the registry cannot resolve: `resolve_transition` would reject it as `unknown component`. |

So the fix is a **field plus a resolution**, not a rename. This task owns both, in ari-core, for
all eight case types; the paper set owns only *which role* its adversary names
([../ari_rqgm_paper/05](../ari_rqgm_paper/05_adversarial_self_preference.md) §5.4).

**This does not weaken artifact-only targeting.** The `RawAttackRecord` still names no component
anywhere — `raw_attack_violations` (`records.py:267-297`) still rejects any `target_artifact` key
containing `"component"` or `"prompt_id"` (`:291-297`), and `TARGET_ARTIFACT_TYPES`
(`records.py:53-64`) is byte-identical. The binding is minted **only after adjudication**, on a
record that (a) exists only for `valid`/`partially_valid` verdicts (invariant 9,
`records.py:543-547`), (b) must be authored by the judge role (`records.py:548-552`), and (c) is
built from a Defender-answered attack. The adversary observes; the judge's verdict is what makes
an observation accountable. That ordering is the P3 statement of this task: **no actor both
accuses and binds.**

### 5.2 The field: `target_component_id`, emitted only when non-empty

```python
# planned: ari-core/ari/rqgm/adversarial/records.py — ValidatedAttackRecord (line 443)
@dataclass(frozen=True)
class ValidatedAttackRecord:
    ...
    affected_components: tuple[str, ...] = ()   # unchanged: the implicated ROLE names
    target_component_id: str = ""               # NEW: the resolved accountable component id
    ...

    def to_dict(self) -> dict:
        d = {
            ...,                                  # the existing 22 keys, same order
            "affected_components": list(self.affected_components),
            "expected_behavior": dict(self.expected_behavior),
            "target_artifact_hash": self.target_artifact_hash,
            "source_refs": list(self.source_refs),
        }
        if self.target_component_id:              # conditional emit — see below
            d["target_component_id"] = self.target_component_id
        return d
```

**Decision: the emit is conditional, and this is load-bearing, not a style choice.** An
unconditional emit would add `"target_component_id": ""` to **every** validated-attack record ever
written — including the seven exploration types, which have no target (§5.4) — and would break
three guarantees at once: the "seven adversaries' record JSON unchanged" regression that
[../ari_rqgm_paper/05](../ari_rqgm_paper/05_adversarial_self_preference.md) §9 asserts as the
proof that the eighth type is additive; the "No new record schemas" claim of the parent
[06](06_adversarial_evolution.md) §6; and the resume-replay byte equality of the JSONL truth
(`test_rqgm_adversarial.py:506-507`, `:801-802`). An empty target is not a target, and a record
that names no one should say nothing — the same absence-is-default convention as
`bfts_web_provenance.json` ([01](01_execution_modes_and_compatibility.md) §6.2). Consumers already
read it absence-tolerantly (`rec.get("target_component_id", "")` at `_reliability.py:61`,
`_evidence.py:58`), so the conditional emit costs no consumer change.

`validated_from_dict` (`records.py:502-526`) reads it symmetrically —
`target_component_id=str(d.get("target_component_id", ""))` — so `from_dict(to_dict(r)) == r` in
both the populated and empty cases, and `from_dict(d).to_dict() == d`
(`test_rqgm_adversarial.py:251`) holds for both old and new records.

**Constructive prevention (mirrors invariant 9's shape).** `make_validated_attack_record`
(`records.py:529-576`) gains `target_component_id: str = ""` and refuses one binding:

```python
if target_component_id and target_component_id == judgment.component_id:
    raise AdversarialRuleError(
        f"validated attack binds its own author {target_component_id!r} as the "
        "accountable component (kernel check 3: role separation — no actor may "
        "both adjudicate and be sentenced by the same record)"
    )
```

with the deterministic re-check appended to `validated_attack_violations` (`records.py:579-606`),
exactly as verdict/role are refused-then-re-checked today. This is the record-level mirror of the
same-role rules governance already enforces downstream (`_prosecution.py:161-167`,
`_evidence.py:96-103`, `governance/_records.py:333` "Reviewer v4 can never impeach Reviewer v3
through this path"). It costs one comparison and makes a judge-implicating case fail loudly at
construction rather than silently produce an unprosecutable motion.

`records.py` stays pure stdlib with no registry import (module docstring `:29-31`): the resolved
id arrives as a plain string.

### 5.3 The producer: resolve at construction, not at the audit-log seam

**Decision: the resolution happens in `AdversarialRound._run` at construction
(`round.py:220-233`), NOT in `_log_all` (`round.py:289-302`).** `_log_all` is a type-agnostic
mirror — `rec.to_dict() if hasattr(rec, "to_dict") else dict(rec)` (`:295`) — that copies every
record shape into `rqgm_audit.jsonl`. Patching a field into the payload there would:

1. make the audit-log copy of a record **differ from the JSONL truth** for the same `record_id`,
   contradicting `_log_all`'s own contract ("JSONL truth + Task 02 audit-log envelope",
   `round.py:290`) and the reload equality tests (`test_rqgm_adversarial.py:506-507`);
2. put a `case_type`-specific branch inside a generic mirror;
3. leave `AdversarialCaseLog` — the pool's source for `AdversarialReplayCase` construction
   (`records.py:811-825` reads the record, not the payload) — reading a record that lacks the
   binding its audit twin has.

At construction, one record exists and both sinks receive identical bytes.

```python
# planned: ari-core/ari/rqgm/adversarial/round.py — module level, beside _EXPECTED_BEHAVIOR (line 42)
#: case_type -> the implicated ROLE names, in priority order (first resolvable
#: wins, §5.4). Closed table, same shape as engine.py's ADVERSARY_SPECS
#: (:463-491). The seven exploration types name no role in v1 (§5.4).
_AFFECTED_ROLES_BY_TYPE: dict[str, tuple[str, ...]] = {}   # paper set adds its row

# inside _run, replacing the make_validated_attack_record(...) call at line 227
roles = _AFFECTED_ROLES_BY_TYPE.get(attack.adversary_type, ())
validated.append(
    make_validated_attack_record(
        judgment,
        attack,
        record_id=self._validated_alloc(),
        expected_behavior=dict(self._expected_behavior(attack.adversary_type)),
        affected_components=roles,
        target_component_id=self._resolve_target(roles),
    )
)

def _resolve_target(self, roles) -> str:
    """First implicated role with a frozen-active component; "" otherwise.

    Fail-open by construction: no epoch open, no registered incumbent, or a
    failing lookup all yield "" — the record then omits the key and the run is
    byte-identical to today (§5.7)."""
    active = self._active_components()          # round.py:131-141 — the FROZEN map
    for role in roles:
        cid = str(active.get(str(role), "") or "")
        if cid:
            return cid
    return ""
```

`_expected_behavior(case_type)` is the paper set's case-typed lookup
([../ari_rqgm_paper/05](../ari_rqgm_paper/05_adversarial_self_preference.md) §5.2) falling back to
the module-level `_EXPECTED_BEHAVIOR` (`round.py:42-46`); this task neither owns nor changes it.

**Landed deviation (recorded, not silent).** The two clauses above conflict: a task that "neither
owns nor changes" the lookup cannot also introduce its call site. Task 15's own diff resolved it in
favour of the first, and §7's contract row — which lists only the two new arguments — is what THIS
task landed: its loop passed `expected_behavior=dict(_EXPECTED_BEHAVIOR)`, because no
`_expected_behavior` method existed in the tree at that time, so writing the call site here would
have been a speculative seam for an unimplemented consumer.

**Superseded downstream (wave 3c, 2026-07-16).** Exactly as this section anticipated, the paper
set's Task 05 introduced the seam and its consumer together: the case-typed
`_EXPECTED_BEHAVIOR_BY_TYPE` table (`round.py:55-61`), the `_expected_behavior` method
(`round.py:212-218`) and its one-line call site (`round.py:407`,
`expected = self._expected_behavior(attack.adversary_type)`) all land in doc 05's diff, where the
requirement is real. The seven exploration types stay byte-identical — the lookup falls back to the
module-level `_EXPECTED_BEHAVIOR`, pinned by
`test_rqgm_adversarial.py::test_the_seven_exploration_types_bind_nothing_and_stay_byte_identical`
(`:1002-1031`). The loop IS seamed today; it was not pre-seamed by this task.

Ordering rule: `_AFFECTED_ROLES_BY_TYPE`'s tuples are **design-time constants in priority order**
(the primarily accountable role first), so the resolution is deterministic without a sort — no wall
clock, no registry iteration order, no LLM (P2).

**Landed deviation — one record per resolvable role, not one target (recorded 2026-07-17).** The
shipped `_run` (`round.py:404-435`) does NOT call a single-target `_resolve_target`; it calls
`_resolve_bindings(roles, judgment) -> [(role, component_id)]` (`round.py:270-303`) and emits ONE
validated record per RESOLVABLE role. Reason: the paper set's row names TWO roles —
`_AFFECTED_ROLES_BY_TYPE["paper_self_preference"] = ("paper_reviewer", "paper_writer")`
(`round.py:97`; the writer gated per node by `_roles_for_node` on the Layer-0 claim gate's
`_paper_writer_unfaithful`, `round.py:251-268`) — and a first-resolvable-wins single target would
bind only the reviewer, leaving the writer permanently unsanctionable
([../ari_rqgm_paper/04](../ari_rqgm_paper/04_anchor_utility_and_epoch_winners.md) §5.1). Each record
still carries a SINGULAR `target_component_id` for its singular consumer (`_reliability.py:61`), but
`affected_components` is the ONE role THAT record binds (`round.py:419`), not the plural observation
trail earlier drafts of this section described. The single-role and targetless (exploration) records
stay byte-identical. Rider: `apply_utility_penalty` sums over the record list
(`UtilityPenaltyPolicy.compute`, `engine.py:1051-1053`, capped), so a two-role case applies two
records' penalty weight to one node; `AdversarialReplayPool` dedup `(case_type,
target_artifact_hash)` collapses the siblings into one case. `_resolve_target` is superseded and
uncalled (removed 2026-07-17).

**`expected_behavior` ≠ `affected_components`.** The first says *who must behave differently*
(and is what `build_failure_summary` turns into `affected_roles`, `records.py:825`); the second
says *who is answerable*. Doc 05's `paper_self_preference` case names both `paper_reviewer` and
`paper_writer` in `expected_behavior`; on the producer side the round emits a SEPARATE validated
record per resolvable role (reviewer always; writer only for a node the claim gate flagged
unfaithful), each record's `affected_components` carrying its own single bound role.

### 5.4 Which case types bind a target

| `case_type` | Attacked artifact class | Implicated role | Registered incumbent today | `target_component_id` |
|---|---|---|---|---|
| `overclaim`, `evidence_gap` | `paper_claim` | `generator` when producer provenance matches | `generator_v1` | `generator_v1` |
| `metric_gaming` | `metric_result` | `generator` when producer provenance matches | `generator_v1` | `generator_v1` |
| `prior_art` | `novelty_claim` | `generator` when producer provenance matches | `generator_v1` | `generator_v1` |
| `reproducibility` | `reproducibility_claim` | `generator` when producer provenance matches | `generator_v1` | `generator_v1` |
| `cost_explosion` | `experiment_plan` | `generator` when producer provenance matches | `generator_v1` | `generator_v1` |
| `prompt_injection` | `proposal` | `generator` when producer provenance matches | `generator_v1` | `generator_v1` |
| `paper_self_preference` (paper set) | `paper_claim` | `paper_reviewer`, `paper_writer` | `paper_reviewer_v1` (always) + `paper_writer_v1` (nodes the claim gate flags `_paper_writer_unfaithful`) under `PaperMode.RQGM_ARCHIVE` ([../ari_rqgm_paper/03](../ari_rqgm_paper/03_writer_reviewer_governed_roles.md) §5.5) | `paper_reviewer_v1` and, per-node, `paper_writer_v1` (one record each — §5.3) |

**Implemented amendment:** the seven exploration types name `generator`, now a registered
founding component. The runtime stamps every research node exactly once with the producing
component identifier, prompt hash, and epoch before persistence and adversarial review.
`_resolve_bindings` accepts `generator_v1` only when those values match the epoch-frozen
incumbent. Legacy records and records with missing, ambiguous, or mismatched provenance remain
targetless; the resolver does not infer responsibility from the attack type alone. The paper
self-preference type follows the same principle for its registered paper roles.

This qualifies — precisely —
[../ari_rqgm_paper/05](../ari_rqgm_paper/05_adversarial_self_preference.md) §5.4 decision 1's
"the seven exploration adversaries get the bridge for free and exploration mode benefits
identically": they get the *bridge* for free; they do not get a *target* until an
artifact-authoring role has an incumbent.

### 5.5 `affected_components` stays, unrenamed and role-shaped

`affected_components` is the record's role-shaped observation of who is implicated (a list, though
after the one-record-per-resolvable-role fan-out of §5.3 each shipped record carries exactly ONE
role — the one it binds; exploration records carry `[]`). It is **kept**, not renamed to
`affected_roles`, and not repurposed to carry component ids:

- Renaming it changes `"affected_components": []` → `"affected_roles": []` in **every** record
  ever written and re-pins the schema branch (`rqgm_attack_records.schema.json:174-177`) — pure
  churn against a field whose only production value is `[]`.
- Filling it with component ids would collide with the parent [06](06_adversarial_evolution.md)
  §6 example (`"affected_components": ["generator_v2", "reviewer_v3"]`, line 419) in the opposite
  direction from the live callers: the paper set passes roles
  ([../ari_rqgm_paper/05](../ari_rqgm_paper/05_adversarial_self_preference.md) §5.2), and roles
  are the only thing a case type knows at design time. The resolution is the bridge; the record
  keeps both ends (`affected_components` = roles observed, `target_component_id` = the incumbent
  bound), which is also what makes an accusation auditable after a boundary retires the component.

The name is imperfect — it holds roles — and that wart is accepted deliberately over a
whole-corpus rewrite. Doc 06 §6's example should be re-annotated to role strings when this task
lands (§11 criterion 6).

### 5.6 The epoch-frozen incumbent rule

**Decision: resolve against the round's epoch-frozen `_active_components()` map
(`round.py:131-141`), never against a live `component_registry.active_set()` read.**

- **Correctness of the accusation.** The accused must be the incumbent that *made the decision the
  attack invalidates*. A live read taken after a boundary adoption would bind the accusation to
  the successor — impeaching `reviewer_v4` for `reviewer_v3`'s leniency, the precise hazard
  `governance/_records.py:333` and `_prosecution.py:161-167` guard downstream. The frozen map is
  the only source that cannot drift under the record.
- **Self-consistency of the record.** The validated record's own `component_id` / `prompt_hash` /
  `epoch_id` are copied from the judgment (`records.py:571-573`), which resolved them through this
  same frozen map (`engine.py:520-543`). Using a different source for the target would produce a
  record whose author is frozen and whose target is live.
- **Determinism (P2).** `_active_components()` is a pure read of Task 02 `EpochState`
  (`ACTIVE_STATUSES`, `events.py:50-51`); no I/O, no ordering surprise, and a re-run over the same
  epoch reproduces the same binding.
- **Zero new wiring.** The round already holds the map and already injects it into all three
  actors (`round.py:103`, `:110`, `:117`). No `component_registry` handle enters
  `AdversarialRound.__init__` (`round.py:58-69`).
- **Agreement with `_actor_id`.** Within an epoch the frozen map and
  `_actor_id(component_registry, role)` (`_pipeline.py:279-288`) agree by construction — the epoch
  freezes the active set. The frozen map is the strictly safer of two readings that coincide, and
  the governance side keeps using `_actor_id` unchanged (`_pipeline.py:417-420`).

**No family guard.** `_PromptedActor._component_id` (`engine.py:520-543`) refuses a rollup winner
outside the actor's own `{family}_v{N}` family, because an actor must never claim another actor's
records. A *target* has no family to compare against: the role's rollup winner **is** the
accountable incumbent by definition. The guard is deliberately absent, and the hazard it would
have masked — a role whose registered family is not unique (e.g. `judge` rolls up to the lineage
judge, not `artifact_judge_v1`, per `prompt_spec.py:198-215`) — is handled by the closed table
instead: v1 names only roles with a single registered family. R3.

### 5.7 Fail-open behaviour and what lights up

Fail-open is unchanged and total. `_resolve_bindings` contributes no `(role, component_id)` entry
for a role when: no epoch is open (`_active_components()` → `{}`, `round.py:136-138`); the role has
no registered incumbent (§5.4); the role would bind the judgment's own author (kernel check 3,
pre-filtered — the binding is dropped, never raised); or the lookup raises (swallowed with a log,
the `engine.py:532-537` precedent). An empty roles tuple (every exploration case) yields `[]`, so
the round emits exactly ONE targetless record ⇒ today's exact behaviour. `AdversarialRound.run`
still never raises into the loop (`round.py:156-165`), and the whole feature costs **zero LLM calls
and one dict lookup per resolvable role** — nothing for
[12](12_cost_control_and_context_budget.md) to budget.

When the field is populated (the `paper_self_preference` case, and any future bound role), the
chain that has been dead since Task 05 shipped runs end to end:

```
ValidatedAttackRecord(target_component_id="paper_reviewer_v1")     # this task
  → ImmutableAuditLog.append (round.py:289-302, unchanged)
  → GovernanceOrchestrator.audit_epoch step 1 (_pipeline.py:396-401)
  → build_reliability_entries: attacks_by_target["paper_reviewer_v1"] (_reliability.py:60-64)
      ⇒ validated_attack_involvement = 2                            (_reliability.py:126)
  → classify_target: attacks >= ATTACK_THRESHOLD ⇒ "file"           (_prosecution.py:34, :89-92)
  → candidate_refs_for_target selects the two attacks               (_evidence.py:56-63)
      (author role "judge" ≠ target role ⇒ NOT same-role-excluded, _evidence.py:99-103)
  → EvidenceBundle with items ⇒ prosecution proceeds                (_prosecution.py:170-177)
  → ImpeachmentMotion(target_component_id="paper_reviewer_v1")      (_prosecution.py:197)
  → adjudication ⇒ GovernanceReport.recommendations
  → resolve_transition ⇒ T9/T10/T11 sanction on a REGISTERED id     (transition_engine.py:669)
```

Two details worth pinning because they change what the tests may assert:

- **A bound target does not need the component to author anything.** `build_reliability_entries`
  unions `attacks_by_target` into its component set (`_reliability.py:73`), so an attacked
  component gets an entry with `validated_attack_involvement = 2` even at `observation_count = 0`
  (`insufficient_data=True`, `reliability_score=None`), and `classify_target`'s attack branch
  fires regardless of the score (`_prosecution.py:89-92`). The binding alone reaches a motion.
  The paper set's `review_record` work
  ([../ari_rqgm_paper/03](../ari_rqgm_paper/03_writer_reviewer_governed_roles.md) §5.8) makes the
  *score* channel work; this task makes the *attack* channel work; they are independent.
- **The score channel could not substitute.** `_reliability.py:114` computes
  `max(0.0, 1.0 - len(attacks)/count)`: with a reviewer authoring many records, two attacks move
  the score by a fraction and never approach `RELIABILITY_FLOOR = 0.4`. The threshold branch —
  i.e. this field — is the control signal, which is why
  [../ari_rqgm_paper/07](../ari_rqgm_paper/07_claim_gate_handoff_and_evaluation.md) §5.8 PI3 binds
  its assertion to the attack path and not to `reliability_score`.

## 6. Data structures / schema changes

### 6.1 `ValidatedAttackRecord` (`ari-core/ari/rqgm/adversarial/records.py`)

One new field with an empty default (`target_component_id: str = ""`, `:443-473`), one
conditional key in `to_dict` (`:475-499`), one symmetric read in `validated_from_dict`
(`:502-526`), one keyword on `make_validated_attack_record` (`:529-576`), one refusal + one
re-check (§5.2). `ADVERSARIAL_RECORD_SCHEMA_VERSION` stays **1**: an optional additive key is not
a schema bump (the schema's own policy, `rqgm_attack_records.schema.json:5`), and bumping it would
invalidate every stored record against `"schema_version": {"const": 1}` (`:69`).

### 6.2 `ari-core/ari/schemas/rqgm_attack_records.schema.json`

Add to the `validated_attack` branch's `properties` (`:155-179`), **not** to `required` (`:181-188`):

```json
"target_component_id": {"type": "string", "minLength": 1}
```

`minLength: 1` encodes §5.2's rule at the schema level: the key is present or absent, never
present-and-empty. The branch keeps no `additionalProperties: false` and is selected by the
`record_type` const (`:156`), so `oneOf` matching is unaffected and old records stay valid. The
`$defs.envelope` (`:54-79`) is untouched. Update the schema `description` (`:5`) to name the field
as the post-adjudication accountability binding, so the "component ids are NOT targets" statement
there and at `records.py:53-55` is not read as contradicted (it is not: raw attacks still cannot
name one — §5.1).

### 6.3 No checkpoint or config surface

No new file (`rqgm_adversarial_cases.jsonl`, `rqgm_audit.jsonl` already in `META_FILES`,
`paths.py:84`, `:455-456`), no `_INTERNAL_JSON_NAMES` entry, no `rqgm.*` key (§3), no
`CONSTITUTION_HASH` movement (`kernel.py:321-351` is envelope-only), no `ari.public.*` symbol ⇒
**zero contract-golden regeneration**.

## 7. API / class changes

| Symbol | Location (planned) | Contract |
|---|---|---|
| `ValidatedAttackRecord.target_component_id` | `ari/rqgm/adversarial/records.py:443` | `str = ""`. The resolved, epoch-frozen accountable component id. Empty == no target == key absent from `to_dict`. |
| `ValidatedAttackRecord.to_dict` | `ari/rqgm/adversarial/records.py:475` | Emits `target_component_id` **only when non-empty**; all other keys and their order unchanged. |
| `validated_from_dict` | `ari/rqgm/adversarial/records.py:502` | Absence-tolerant read (`d.get("target_component_id","")`); round-trip identity preserved for old and new records. |
| `make_validated_attack_record(..., target_component_id="")` | `ari/rqgm/adversarial/records.py:529` | Additive keyword-only default. Raises `AdversarialRuleError` when the target equals `judgment.component_id` (§5.2). Existing callers (`round.py:227`, `smoke.py:212-214`) compile and behave identically. |
| `validated_attack_violations` | `ari/rqgm/adversarial/records.py:579` | Adds the self-binding re-check; every existing violation string unchanged. |
| `_AFFECTED_ROLES_BY_TYPE` | `ari/rqgm/adversarial/round.py` (module level, beside `_EXPECTED_BEHAVIOR:42`) | Closed `case_type -> (role, …)` table in priority order; empty for the seven in v1. The paper set adds `paper_self_preference` ([../ari_rqgm_paper/05](../ari_rqgm_paper/05_adversarial_self_preference.md)). |
| `AdversarialRound._resolve_bindings(roles, judgment) -> list[tuple[str, str]]` | `ari/rqgm/adversarial/round.py:270-303` | Pure read of `_active_components()` (`:131-141`); ONE `(role, component_id)` entry per resolvable role, excluding the judgment's own author (kernel check 3, pre-filtered — dropped, never raised); never raises; `[]` on every fail-open path. No new constructor parameter. Supersedes the single-target `_resolve_target` (removed 2026-07-17). |
| `AdversarialRound._roles_for_node(roles, node) -> tuple[str, ...]` | `ari/rqgm/adversarial/round.py:251-268` | Per-node filter of the implicated roles; only ever DROPS `paper_writer` on a node the Layer-0 claim gate did not flag `_paper_writer_unfaithful`. Never adds a role; exploration nodes pass through unchanged. |
| `AdversarialRound._run` | `ari/rqgm/adversarial/round.py:404-435` | Emits ONE validated record per resolvable role (`_resolve_bindings`), each with `affected_components=(role,)` + its own `target_component_id`; exactly one targetless record when nothing resolves. No change to ordering, markers, budget gates, or `_log_all`. |

Unchanged and deliberately so: `ari/rqgm/governance/_reliability.py`, `_prosecution.py`,
`_evidence.py`, `_pipeline.py`, `transition_engine.py`, `kernel.py`, `kernel_rules.py`,
`ari/rqgm/evaluation/smoke.py`, `prompt_spec.py`.

## 8. Migration / compatibility

1. **Every existing record is byte-identical.** With `_AFFECTED_ROLES_BY_TYPE` empty for the seven
   (§5.4), `_resolve_bindings` returns `[]` for every exploration case ⇒ the round emits one
   targetless record whose `to_dict` emits the same 19 keys in the same order ⇒
   `rqgm_adversarial_cases.jsonl` and the `rqgm_audit.jsonl` mirror are unchanged, and
   `AdversarialReplayPool` dedup keys (`(case_type, target_artifact_hash)`) and `abstract_view`s are
   unaffected (`records.py:811-825` reads neither field).
2. **Old checkpoints load unchanged.** `validated_from_dict` defaults the missing key to `""`;
   `_reliability.py:61` / `_evidence.py:58` already `.get(..., "")`. A record written before this
   task and one written after with no target are the same bytes — there is no migration.
3. **`simple_bfts` and `paper.mode: linear` are untouched.** No `ari.rqgm` module is imported on
   either path ([01](01_execution_modes_and_compatibility.md) §5.3, §8.1); this task adds no
   import, no file, and no config key that could change that.
4. **`smoke.py` is not changed.** `_run_adversarial_stubs` (`:200-219`) keeps calling the
   constructor with no target: its eval doubles run without a component registry, and Task 13's
   `validated_attacks` counts must stay comparable across the ablation matrix. It remains the
   citation that this seam is parent-level, and it picks the binding up for free if a future
   injection needs it (R6).
5. **Forward-compat.** A record carrying `target_component_id` read by an *older* ari-core is
   parsed by `validated_from_dict`'s explicit field list, which drops unknown keys — the safe
   failure direction (today's behaviour: no target). The JSON schema branch has no
   `additionalProperties: false`, so an older validator also accepts it.
6. **The paper set inherits it topology-agnostically.** Nothing here is paper-shaped: the record,
   the table and the resolution live in `ari/rqgm/adversarial/`, and
   [../ari_rqgm_paper/05](../ari_rqgm_paper/05_adversarial_self_preference.md) supplies one table
   row plus one `expected_behavior` row. `PaperArchiveRuntime` constructs the same
   `AdversarialRound`.

## 9. Tests

Unit — extend `ari-core/tests/test_rqgm_adversarial.py` (already the home of the record
round-trip block, `:226-260`):

- **Conditional emit**: `"target_component_id" not in make_validated_attack_record(...).to_dict()`
  when no target is passed; present and equal when one is; `to_dict()` key set and order for a
  targetless record is **identical** to the pre-change golden (the byte-identity regression — a
  literal expected-key list, not a subset check).
- **Round-trip both ways**: `validated_from_dict(d).to_dict() == d` for the empty and populated
  cases (the `:251` pattern); a legacy dict without the key round-trips to a record with `""`.
- **Self-binding refusal**: `make_validated_attack_record(..., target_component_id=<the
  judgment's own component_id>)` raises `AdversarialRuleError`; `validated_attack_violations` on a
  hand-built dict with the same collision returns the matching violation string; a target
  differing from the author yields `[]`.
- **Schema**: a populated record passes `ConstitutionalKernel.validate_record_schema`
  (`kernel.py:321`) and the `rqgm_attack_records.schema.json` `validated_attack` branch; a record
  with `"target_component_id": ""` **fails** the schema (`minLength: 1`) — the emit rule is
  machine-enforced, not just documented.

Producer — `ari-core/tests/test_rqgm_adversarial.py` (the `AdversarialRound` block):

- **Resolution**: a round whose `epoch_state.active_components` maps the implicated role to
  `<role>_v1` and whose case type has a table row stamps `target_component_id == "<role>_v1"` on
  the validated record, and the **same value appears in both sinks** —
  `rqgm_adversarial_cases.jsonl` and the `rqgm_audit.jsonl` payload (the §5.3 no-divergence rule).
- **Epoch-frozen, not live**: mutating the component registry after the epoch is frozen does not
  move the binding; the record names the incumbent from `active_components`.
- **Fail-open matrix**: no epoch open (`active_components == {}`), role absent from the frozen
  map, no table row, and a raising `epoch_state` each yield a record with the key absent and no
  exception out of `run` (`round.py:156-165`).
- **The seven are unchanged (regression)**: a round driven with each of the seven case types
  produces records whose JSON equals the pre-change fixture byte-for-byte
  (`affected_components == []`, no `target_component_id`).

Integration — the chain, in `ari-core/tests/test_rqgm_governance.py` (the fixture that hid the
bug, `:97-112`):

- **Producer↔consumer parity (the test that would have caught this)**: build the audit slice from
  **real** `make_validated_attack_record(...).to_dict()` output — never `_rec(...)` dicts — with
  two records bound to one component; assert `build_reliability_entries` yields
  `validated_attack_involvement == 2` and `classify_target` returns `CLASSIFY_FILE`. Then assert
  the negative control: the same two records built **without** a target yield involvement `0` and
  `classify_target is None` — pinning that the fixture's key and the producer's key are the same
  key forever.
- **Evidence**: `candidate_refs_for_target` (`_evidence.py:44-71`) selects both bound attacks for
  the target and the assembled bundle has non-empty `items` (author role `judge` ≠ target role ⇒
  not same-role-excluded), so `decide_prosecutions` does not record `no_admissible_evidence`
  (`_prosecution.py:174-177`).
- **Motion**: `audit_epoch` files an `ImpeachmentMotion` whose `target_component_id` is the bound
  component, and `resolve_transition` resolves it to a T9/T10/T11 sanction rather than
  `unknown component` (`transition_engine.py:692`) when the component is registered.
- **Zero-authorship target**: a component that authors nothing but carries two bound attacks still
  gets an entry (`_reliability.py:73`) with `insufficient_data=True`, `reliability_score=None`,
  and `classify_target == CLASSIFY_FILE` (§5.7).

Downstream (owned by the paper set, listed here so the sequencing is explicit): doc 07 §5.8 PI3 —
a scripted `always_accept` `paper_reviewer` double accumulates ≥ 2 `paper_self_preference`
validated attacks bound to `paper_reviewer_v1` and the boundary files a motion against it. That
test is red until this task lands and is the anti-collusion regression for the whole method.

CI placement: plain ari-core tests, run by `refactor-guards.yml`; no new workflow, no golden
regeneration (§6.3).

## 10. Risks

- **R1 — A bound target makes an accusation *possible*, not *correct*.** The judge's verdict is an
  LLM output; two validated attacks now automatically clear `ATTACK_THRESHOLD` and file a motion.
  Mitigations already in the substrate, none added here: the attack must survive a Defender
  (`round.py:206-211`) and an adjudication (`:214-217`); the motion needs an independently
  verified evidence bundle (`_prosecution.py:170-177`); the bond ledger caps motions per epoch
  (`_prosecution.py:44-84`); and the motion is adjudicated, not executed. If the threshold proves
  hair-trigger once the channel is live, `ATTACK_THRESHOLD` is a Task 05 constant — tune it there
  with evidence, never by leaving the field unemitted.
> **Landed downstream (wave 3c, 2026-07-16; two-role revision 2026-07-17).** The paper set's Task
> 05 shipped the `_AFFECTED_ROLES_BY_TYPE["paper_self_preference"] = ("paper_reviewer",
> "paper_writer")` row (`round.py:97`) this task's mechanism reads, with `paper_writer` gated
> per-node by `_roles_for_node` (`round.py:251-268`) on the Layer-0 claim gate's
> `_paper_writer_unfaithful` flag and emitted as its OWN validated record via `_resolve_bindings`
> (`round.py:270-303`; §5.3). A REAL paper self-preference adversarial round now produces
> `ValidatedAttackRecord`s with `target_component_id == "paper_reviewer_v1"` (always) and, on an
> unfaithful draft, a second record with `target_component_id == "paper_writer_v1"` in production
> (`paper_runtime.py::_score_reviewer_on_anchor`). So the chain this task designed fires end-to-end
> for the first time in a live run — reliability → prosecution → impeachment → sanction → role
> opening — not only in the §9 unit tests. The seven exploration types bind `generator_v1` since
> `fb7632d` (R2 below).

- **R2 — CLOSED 2026-07-30 (`fb7632d`): the seven exploration adversaries now bind `generator_v1`.**
  The precondition this risk named was met, not waived. `generator_v1` is a founding registered
  component (`ari-core/ari/rqgm/prompt_spec.py:442-443`); all seven case types map to
  `("generator",)` (`ari-core/ari/rqgm/adversarial/round.py:91-97`); and
  `RQGMRuntime.stamp_node_producer` (`ari-core/ari/rqgm/runtime.py:263-295`) write-once-stamps the
  epoch-frozen `producer_component_id` / `producer_prompt_hash` / `producer_epoch_id` on every
  expanded child (`runtime.py:88`) and before the adversarial round (`runtime.py:3397`).
  `_resolve_bindings` (`round.py:277-298`) binds only when all three match the frozen incumbent, so
  legacy, missing or mismatched provenance stays targetless — the resolver never infers
  responsibility from the case type alone. Proven end-to-end by
  `ari-core/tests/test_rqgm_adversarial.py::test_exploration_attack_binds_epoch_stamped_generator`
  (asserts `target_component_id == "generator_v1"`). What is NOT closed: there is still no
  exploration `reviewer_v1` component in `FOUNDING_COMPONENT_TABLE`, so no reviewer binding exists;
  that remains a Task 05/07 decision, filed against [05](05_governance_orchestrator.md) and
  [07](07_prompt_spec_and_prompt_evolution.md).
- **R3 — A role can roll up to the judgment's own author.** The registry rolls a role up to one
  winner (`prompt_spec.py:228-231`). For `judge` that winner is `artifact_judge_v1` —
  `FOUNDING_COMPONENT_TABLE` carries exactly one judge row, and no `lineage_judge` component id
  exists anywhere in the tree — which is the very component that authors the adversarial judgment.
  So a table row naming `judge` is a **self-binding**, refused by
  `make_validated_attack_record` (§5.2). Because that refusal raises and the `for judgment in
  judgments` loop has no per-item isolation, an unguarded self-binding would escape `_run`, be
  swallowed by `run`'s blanket handler (`round.py:212`), and cost the node **every** validated
  record and its utility penalty. Mitigation: the producer pre-filters the case
  (`round.py:280-296`) and drops the BINDING rather than the record — the attack was still
  adjudicated valid, so the finding survives unbound, exactly as all seven are today; the builder's
  refusal is thereby a belt-and-braces programming-error guard that never fires from the live path.
  `test_round_drops_a_self_bound_binding_instead_of_killing_the_round` pins it through the real
  round, and was mutation-checked (disabling the pre-filter fails it with the raise).
- **R4 — The score channel still cannot detect leniency.** `_reliability.py:114`'s attack-ratio
  part is diluted by `observation_count`, so `reliability_score` stays near 1.0 for a busy,
  lenient component even while it is being prosecuted on the attack path. Out of scope (§3);
  recorded so no downstream doc asserts `reliability_score < RELIABILITY_FLOOR` as a detection
  channel. Re-weighting is a Task 05 change.
- **R5 — `UtilityRecord` has the identical gap.** `to_dict` (`records.py:640-660`) emits no
  `target_component_id` while `_evidence.py:64` admits utility records that name a target ⇒ the
  penalty channel contributes no evidence. Deliberately out of scope: the penalty's target is a
  node. If Task 10's recompute contract ever needs it, the shape designed here (optional field,
  conditional emit) transfers verbatim.
- **R6 — `smoke.py`'s second producer drifts.** Two call sites now construct validated records
  (`round.py:227`, `smoke.py:212-214`); only one binds. A future eval injection that needs a bound
  target must add the argument at the smoke site too. Mitigation: the §9 producer test names both
  sinks, and §8.4 pins the decision so the omission is visible rather than accidental.
- **R7 — Ownership overlap with the paper set.** Doc 05 §5.4's table assigns the value-space layer
  to itself and locates the resolution at the `_log_all` seam; this plan owns the resolution in
  ari-core and locates it at construction (§5.3, with reasons). Mitigation: doc 05's substantive
  deliverable — the `paper_self_preference` row naming `paper_reviewer` — is unaffected by where
  the resolution runs; the two docs must be reconciled to one location before implementation, and
  this plan's §5.3 is the one that keeps both sinks byte-equal.
- **R8 — A retired component keeps its accusation.** A bound target may be retired at the boundary
  before the motion resolves. This is correct (the record names who decided, not who serves) and
  the transition engine already rejects actions on unknown components (`transition_engine.py:692`)
  — but the resulting `rejected` note may read as a defect. Mitigation: the §9 motion test asserts
  the registered-component path; the retired-target path is Task 09's existing behaviour.

## 11. Completion criteria

This task is complete when all of the following hold:

1. **The field is specified** — `target_component_id: str = ""` on `ValidatedAttackRecord`, its
   conditional `to_dict` emit, the symmetric `validated_from_dict` read, the
   `make_validated_attack_record` keyword, the self-binding refusal and its deterministic
   re-check (§5.2, §6.1), plus the `minLength: 1` optional schema property that machine-enforces
   the emit rule (§6.2).
2. **The producer is specified** — resolution at construction (not at `_log_all`), the closed
   `_AFFECTED_ROLES_BY_TYPE` table, `_resolve_bindings`'s one-record-per-resolvable-role rule (with
   the per-node `_roles_for_node` writer gate; §5.3), and the epoch-frozen source with its
   no-family-guard decision (§5.3, §5.6).
3. **The binding table is decided** — the seven name no role and are byte-identical; the paper
   set's `paper_self_preference` binds `paper_reviewer` → `paper_reviewer_v1`; the precondition
   for binding the seven is stated, not assumed (§5.4, R2).
4. **The regression is stated and testable** — every existing validated-attack record's JSON is
   unchanged, round-trip identity holds, and the seven's fixtures compare byte-for-byte (§8.1,
   §9).
5. **The chain is proven, not asserted** — a test builds the audit slice from real producer output
   and drives `build_reliability_entries` → `classify_target` → evidence bundle → motion →
   `resolve_transition`, with the targetless negative control (§9). The dict-only fixture at
   `test_rqgm_governance.py:100-107` can no longer diverge from the producer.
6. **Downstream docs can consume it without re-opening it** —
   [../ari_rqgm_paper/05](../ari_rqgm_paper/05_adversarial_self_preference.md) §10 R7 and
   [../ari_rqgm_paper/07](../ari_rqgm_paper/07_claim_gate_handoff_and_evaluation.md) §5.8 PI3
   resolve against this plan's field and location, R7's ownership overlap is settled, and
   [06](06_adversarial_evolution.md) §6's example (line 419) is re-annotated so
   `affected_components` reads as role names (§5.5).
7. **No consumer changed.** The diff touches `records.py`, `round.py`, the record schema and
   tests — nothing under `ari/rqgm/governance/`, no config, no contract golden.

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

- `target_component_id` is implemented on `ValidatedAttackRecord` with the conditional emit, the
  symmetric read, the self-binding refusal + re-check, and the schema property.
- The producer-side resolution is implemented in `AdversarialRound` against the epoch-frozen map,
  with the closed table.
- The §9 unit, producer, fail-open, byte-identity and integration tests exist and pass, including
  the producer↔consumer parity test built from real record output.
- The "records are byte-identical for the seven" regression is asserted by a literal expected-key
  comparison, not a subset check.
- R2 (binding the exploration adversaries) is moved to [05](05_governance_orchestrator.md) /
  [07](07_prompt_spec_and_prompt_evolution.md) as an explicit open question, and R5
  (`UtilityRecord`) to [10](10_frontier_repair_and_selective_erasure.md), before this file is
  deleted.
- The "roles are observed, components are bound, and the binding is minted only after
  adjudication" rule (§5.1, §5.6) is captured as a docstring on `ValidatedAttackRecord` and in the
  permanent governance/adversarial reference under `docs/`, so the two-layer mismatch cannot
  silently re-open.

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

- [ ] `ValidatedAttackRecord.target_component_id` implemented; `to_dict` emits it only when
      non-empty; `validated_from_dict` reads it absence-tolerantly.
- [ ] `make_validated_attack_record` refuses a self-binding target; `validated_attack_violations`
      re-checks it.
- [ ] `rqgm_attack_records.schema.json` carries the optional `target_component_id`
      (`minLength: 1`), `required` and `schema_version` unchanged.
- [ ] `AdversarialRound` resolves the implicated role against the epoch-frozen
      `_active_components()` map at construction; both sinks carry identical bytes.
- [ ] The seven exploration adversaries' record JSON is byte-identical (regression test green).
- [ ] The producer↔consumer parity test drives real records through
      `build_reliability_entries` → `classify_target` → evidence bundle → motion.
- [ ] R2 / R5 handed to their owning plans; doc [06](06_adversarial_evolution.md) §6's
      `affected_components` example re-annotated as role names.
- [ ] The accountability-binding rule published in the permanent governance reference.
