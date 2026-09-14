"""RQGM boundary prompt evolution + always-visible meta step (plan 07 §5.4,
plan 11 §5.4 — the live-path wiring fix).

Covers the two live-run gaps found in the B8 v9 audit trail:

* FIX-A — ``RQGMRuntime.run_epoch_audit`` used to pass a hardcoded
  ``candidate_prompts=()`` into ``audit_epoch`` (nothing ever supplied
  candidates). The boundary window now mints PromptMutator candidates for
  every EVOLVABLE role with an ACTIVE incumbent: deterministic sorted-role
  order, LLM-less knob kinds when no LLM is injected, per-role/total caps
  from ``rqgm.prompt_evolution``, Task 12 budget gating, Task 07 record
  persistence, idempotent re-runs, and ``prompt_evolution_skipped`` when
  disabled.
* FIX-B — the enabled meta-evolution path emitted NO audit event when the
  live runtime had no invokers registered (B8: registry 12c/25p, meta
  enabled, zero meta lines). Every boundary now leaves a ``meta_evolution``
  (or the pinned ``meta_evolution_skipped``) line with an outcome.
* FIX-C — the final wiring gap (v10 audit): ``RQGMRuntime`` constructed the
  MetaEvolutionCoordinator WITHOUT an invoker map, so every registered+
  active meta agent skipped on ``no invoker registered``. The runtime now
  wires deterministic live invokers (``_meta_invokers``): ``prompt_mutator``
  delegates to PromptMutator under the plan-11 budget with cross-channel
  dedup by deterministic candidate id (never duplicating a FIX-A record);
  ``clean_room_generator`` is a REACHED deterministic no-op deferring to the
  Task 08 boundary pass (its live actor). Division of labor: FIX-A stays the
  pre-audit minting authority for evolvable roles under the plan-07 caps;
  the meta channel adds at most ``max_meta_candidates_per_epoch`` proposals
  for roles FIX-A left uncovered, routed through the coordinator's
  kernel-gated forwarding.

No test calls a real LLM: mutators/evaluators are deterministic fakes (P2).
"""

from __future__ import annotations

import json

import pytest

from ari.config import ARIConfig
from ari.rqgm.store import ImmutableAuditLog, RqgmStateStore
from ari.rqgm.events import TransitionEvent
from ari.rqgm.prompt_evolution import (
    STAGES,
    CandidateValidationPipeline,
    build_adoption_request,
    candidate_from_dict,
    load_prompt_evolution_log,
)
from ari.rqgm.prompt_loader import evolved_prompt_path
from ari.rqgm.prompt_spec import build_founding_specs

#: Deterministic expectation for a calm, LLM-less default-config boundary:
#: evolvable roles with active founding incumbents, sorted, truncated by
#: ``max_total_candidates_per_epoch`` (default 4); the mutator's own role
#: (``prompt_mutator``) is excluded (same-role generation prohibition).
#:
#: ``failure_summary_compressor_prompt_v2`` displaced ``generator_prompt_v2``
#: from the truncated four when the plan-11 §5.2 recommendation roles gained
#: founding prompts + components: the list is alphabetical, and having an
#: ACTIVE INCUMBENT is exactly what makes a role eligible. Its presence here
#: is the load-bearing evidence that these roles are now genuinely governed
#: rather than vocabulary-only — an ineligible role never appears.
#: ``replay_selector_prompt_v2`` sorts after the cap and so is minted in a
#: later boundary, not never (see the ordering assertion below).
EXPECTED_CALM_CANDIDATES = [
    "adversary_prompt_v2",
    "clean_room_generator_prompt_v2",
    "defender_prompt_v2",
    "failure_summary_compressor_prompt_v2",
]


@pytest.fixture(autouse=True)
def _isolate_rqgm_globals(monkeypatch):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    yield
    from ari import cost_tracker

    cost_tracker.set_default_metadata(epoch=None)


def _runtime(tmp_path, rqgm=None):
    from ari.rqgm.runtime import RQGMRuntime

    cfg = ARIConfig(
        ari={"mode": "ari_rqgm"},
        rqgm={"enabled": True, **(rqgm or {})},
    )
    runtime = RQGMRuntime(cfg, checkpoint_dir=tmp_path)  # llm=None
    ep = runtime.ensure_epoch(1, checkpoint_dir=tmp_path, run_id="r")
    assert ep is not None and ep.epoch_id == "epoch_000"
    return runtime


def _candidates(tmp_path):
    return [
        r for r in load_prompt_evolution_log(tmp_path)
        if r.get("record_type") == "prompt_candidate"
    ]


def _audit_events(tmp_path, event_type):
    return [
        line for line in ImmutableAuditLog.read(tmp_path)
        if line.get("event_type") == event_type
    ]


# ── FIX-A (a): calm LLM-less boundary mints deterministic candidates ────────


def test_calm_llmless_boundary_mints_capped_deterministic_candidates(
    tmp_path,
):
    runtime = _runtime(tmp_path)
    report = runtime.run_epoch_audit(tmp_path)
    assert report is not None

    cands = _candidates(tmp_path)
    # Deterministic sorted-role order, capped by the default total cap (4)
    # and the per-role cap (1); LLM-less boundary falls back to the first
    # configured knob kind (threshold_tuning) — incumbent bytes reused.
    assert [c["candidate_id"] for c in cands] == EXPECTED_CALM_CANDIDATES
    assert {c["mutation_kind"] for c in cands} == {"threshold_tuning"}
    assert {c["status"] for c in cands} == {"candidate"}
    assert {c["generation_mode"] for c in cands} == {"mutation"}
    active_hashes = runtime.state.prompts.active_prompt_hashes()
    for cand in cands:
        # Knob kinds keep the incumbent template bytes (new identity only).
        assert cand["prompt_hash"] == active_hashes[cand["role"]]
        # The write-once body landed under {ckpt}/rqgm_prompts/.
        assert evolved_prompt_path(tmp_path, cand["candidate_id"]).exists()

    # The candidates rode into the GovernanceReport's board evaluations.
    evaluated = {e["prompt_id"] for e in report.candidate_evaluations}
    assert evaluated == set(EXPECTED_CALM_CANDIDATES)
    # Empty replay/anchor boards on a calm epoch: inconclusive, never a
    # crash and never a degradation of the report.
    assert {e["verdict"] for e in report.candidate_evaluations} == {
        "inconclusive"
    }

    # The boundary is audit-visible with the proposed outcome.
    events = _audit_events(tmp_path, "prompt_evolution")
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["outcome"] == "proposed"
    assert payload["candidate_ids"] == EXPECTED_CALM_CANDIDATES


def test_boundary_candidate_generation_is_idempotent_on_rerun(tmp_path):
    runtime = _runtime(tmp_path)
    first = runtime.run_epoch_audit(tmp_path)
    assert first is not None
    before = _candidates(tmp_path)

    # An interrupted-boundary re-run (same open epoch) mints nothing new:
    # the deterministic candidate_id is the dedup key.
    second = runtime.run_epoch_audit(tmp_path)
    assert second is not None
    after = _candidates(tmp_path)
    assert [c["record_id"] for c in after] == [
        c["record_id"] for c in before
    ]
    events = _audit_events(tmp_path, "prompt_evolution")
    assert [e["payload"]["outcome"] for e in events] == [
        "proposed", "no_candidates",
    ]
    assert any(
        "already recorded" in reason
        for reason in events[-1]["payload"]["skipped"]
    )


def test_boundary_candidate_flows_through_the_adoption_path(tmp_path):
    """A live-minted boundary candidate is adoption-capable through the
    EXISTING Task 07 lifecycle seams (the full-smoke flow): six stages with
    injected deterministic components → adoption request → Task 02
    transaction → ``probationary_active`` with hash-verified bytes."""
    runtime = _runtime(tmp_path)
    assert runtime.run_epoch_audit(tmp_path) is not None
    raw = [
        c for c in _candidates(tmp_path)
        if c["candidate_id"] == "adversary_prompt_v2"
    ][0]
    candidate = candidate_from_dict(raw)
    founding = {s.prompt_id: s for s in build_founding_specs()}
    incumbent = founding[candidate.source_prompt_id]

    pipeline = CandidateValidationPipeline(
        checkpoint_dir=tmp_path,
        cfg=runtime.cfg,
        llm=lambda prompt: json.dumps({"attack_claim": "stub"}),
        case_evaluator=lambda cand, case: True,
        known_specs=founding,
        component_roles={"prompt_mutator_v1": "prompt_mutator"},
    )
    for stage in STAGES:
        if stage == "shadow":
            pipeline.record_shadow_observation(
                candidate, incumbent.prompt_id, node_id="node_1",
                candidate_output="shadow-only-output",
            )
        rec = pipeline.run_stage(candidate, stage, incumbent=incumbent)
        assert rec.passed, f"{stage}: {rec.details}"

    request = build_adoption_request(candidate, pipeline)
    assert request is not None
    assert request["to_status"] == "probationary_active"

    store = RqgmStateStore()
    state = store.apply_transition(
        tmp_path, "transition_adoption_smoke",
        [
            TransitionEvent(
                event_type="prompt_registered",
                payload=request["registration_payload"],
            ),
            TransitionEvent(
                event_type="prompt_status_change",
                payload={
                    "prompt_id": request["candidate_id"],
                    "from_status": request["from_status"],
                    "to_status": request["to_status"],
                },
            ),
        ],
    )
    adopted = state.prompts.get(candidate.candidate_id)
    assert adopted is not None
    assert adopted.status == "probationary_active"
    text, version_id = state.prompts.resolve_text(
        candidate.candidate_id, checkpoint_dir=tmp_path
    )
    assert version_id == candidate.prompt_hash
    # Knob-kind adoption serves the incumbent bytes under the new identity.
    inc_text, _ = state.prompts.resolve_text(
        incumbent.prompt_id, checkpoint_dir=tmp_path
    )
    assert text == inc_text


def test_minted_candidates_are_registered_at_candidate_after_one_boundary(
    tmp_path,
):
    """BUG-1 intake (plan 07 §5.3 / plan 09 T1) — the reproduced gap closed.

    Before the fix, a minted candidate was appended to
    ``prompt_evolution.jsonl`` and board-scored but NEVER registered, so
    ``resolve_transition`` (which iterates only registry entries) silently
    dropped it every boundary and the adoption spine was inert. After ONE
    real epoch boundary every minted candidate (all three channels feed the
    single evolution log) now sits in the GovernedPromptRegistry at
    status='candidate' with its checkpoint-scoped body — and NONE is
    auto-activated (the incumbent founding v1 keeps serving)."""
    runtime = _runtime(tmp_path)
    # Cross a real epoch boundary (default nodes_per_epoch=10; epoch_000
    # opened at node_count 1) — the boundary transaction commits the intake.
    runtime.ensure_epoch(11, checkpoint_dir=tmp_path, run_id="r")
    assert runtime.current_epoch.epoch_seq == 1

    minted = [c["candidate_id"] for c in _candidates(tmp_path)]
    assert minted == EXPECTED_CALM_CANDIDATES + [EXPECTED_META_CANDIDATE]

    entries = runtime.state.prompts.entries()
    for cid in minted:
        assert cid in entries, f"{cid} was minted but never registered"
        entry = entries[cid]
        assert entry.status == "candidate"                 # no auto-activation
        assert entry.source.get("kind") == "checkpoint_file"

    # No candidate reached a serving state; the founding incumbents still do.
    serving = {
        e.prompt_id for e in entries.values()
        if e.status in ("active", "probationary_active")
    }
    assert not (serving & set(minted))     # nothing minted was activated
    assert serving                          # founding incumbents keep serving

    # Idempotent/resume-safe: a second boundary never re-registers an id
    # already in the registry (no duplicate prompt_registered).
    from ari.rqgm.store import RQGM_TRANSITIONS_FILENAME

    def _reg_count():
        lines = (tmp_path / RQGM_TRANSITIONS_FILENAME).read_text().splitlines()
        return sum(
            1 for ln in lines
            if json.loads(ln).get("event_type") == "prompt_registered"
            and json.loads(ln).get("payload", {}).get("prompt_id") in minted
        )

    first = _reg_count()
    runtime.ensure_epoch(21, checkpoint_dir=tmp_path, run_id="r")
    assert _reg_count() == first  # the same ids were not registered twice


# ── FIX-A (b): disabled + budget-zero paths ─────────────────────────────────


def test_prompt_evolution_disabled_emits_skipped_event(tmp_path):
    runtime = _runtime(tmp_path, rqgm={"prompt_evolution": {"enabled": False}})
    report = runtime.run_epoch_audit(tmp_path)
    assert report is not None  # the audit itself still runs
    assert report.candidate_evaluations == []
    assert _candidates(tmp_path) == []
    # Task 14 (plan 14 §5.3): {ckpt}/rqgm_prompts/ now also holds the
    # FOUNDING utility-policy body (a .json), written by the bootstrap
    # regardless of prompt_evolution. The regression this line guards is
    # "prompt evolution disabled => no EVOLVED template bodies", which is
    # exactly the .md files.
    assert not list((tmp_path / "rqgm_prompts").glob("*.md"))
    events = _audit_events(tmp_path, "prompt_evolution_skipped")
    assert len(events) == 1
    assert events[0]["payload"]["reason"] == "prompt_evolution.enabled=false"
    assert _audit_events(tmp_path, "prompt_evolution") == []


@pytest.mark.parametrize("overrides", [
    {"max_total_candidates_per_epoch": 0},
    {"max_candidates_per_role_per_epoch": 0},
])
def test_budget_zero_config_generates_nothing(tmp_path, overrides):
    runtime = _runtime(tmp_path, rqgm={"prompt_evolution": overrides})
    report = runtime.run_epoch_audit(tmp_path)
    assert report is not None
    assert report.candidate_evaluations == []
    assert _candidates(tmp_path) == []
    events = _audit_events(tmp_path, "prompt_evolution")
    assert len(events) == 1
    assert events[0]["payload"]["outcome"] == "no_candidates"
    assert events[0]["payload"]["candidate_ids"] == []


# ── FIX-B (c): the meta step is always audit-visible at a boundary ──────────
# ── FIX-C: live invokers are wired; the meta channel routes a candidate ─────

#: The meta channel's deterministic pick on a calm LLM-less founding
#: boundary: the first sorted evolvable role the FIX-A path left uncovered
#: (``prompt_mutator`` itself is excluded — same-role/cross-generation rule).
#: Moved from ``judge`` to ``generator`` when the plan-11 §5.2 recommendation
#: roles gained founding prompts: ``failure_summary_compressor`` sorts inside
#: the plan-07 cap of 4 and displaced ``generator`` out of it, so ``generator``
#: became the first role the FIX-A path leaves uncovered. The invariant this
#: pins — the two channels never mint the same candidate — is unchanged; only
#: which role each covers moved.
EXPECTED_META_CANDIDATE = "generator_prompt_v2"

#: The clean-room invoker is REACHED (a deterministic no-op deferring to the
#: Task 08 boundary pass) — never the old ``no invoker registered`` gap.
CLEAN_ROOM_REACHED_SKIP = "empty output from clean_room_generator_v1"

#: Task 14 (plan 14 §5.2/§5.4): ``policy_mutator`` is now a registered+active
#: meta component, so the coordinator SEES it — but its actor is deliberately
#: not routed through the meta channel. PolicyMutator is invoked directly
#: from ``_run_epoch_boundary`` (plan 14 §5.4) and emits its own
#: ``utility_policy_candidate`` record type, which is outside the
#: coordinator's closed ``meta_rules.OUTPUT_KINDS`` vocabulary. So it keeps
#: the coordinator's explicit ``no invoker`` skip line — exactly the posture
#: ``RQGMRuntime._meta_invokers``'s docstring prescribes for a meta role
#: without a coordinator-routed actor ("actors are never faked").
POLICY_MUTATOR_NO_INVOKER_SKIP = (
    "no invoker registered for role 'policy_mutator' (policy_mutator_v1)"
)

#: The two plan-11 §5.2 recommendation roles are now REACHED (their invokers
#: are registered) but produce nothing in these fixtures: both are pure
#: functions of the epoch's abstract failure summaries, and no adversarial
#: replay case has been admitted here. So they take the ``clean_room``
#: posture — a reached deterministic no-op logged as ``empty output`` —
#: rather than the ``no invoker`` gap they used to leave. Sorted after
#: ``clean_room_generator_v1`` because ``_active_meta_agents`` walks the
#: component view in component_id order.
REPLAY_SELECTOR_REACHED_SKIP = "empty output from replay_selector_v1"
FAILURE_COMPRESSOR_REACHED_SKIP = (
    "empty output from failure_summary_compressor_v1"
)


def _meta_outputs(tmp_path):
    from ari.rqgm.meta_evolution import load_meta_outputs_log

    return load_meta_outputs_log(tmp_path)


def test_live_boundary_wires_invokers_and_routes_a_meta_candidate(tmp_path):
    """The v10 wiring gap, closed: a real ``ari_rqgm`` boundary (founding
    registry, ``llm=None``) now leaves ``meta_evolution`` at
    ``outcome=proposed`` with a recorded+routed PromptMutator output — no
    ``no invoker registered`` skip for any registered meta agent."""
    runtime = _runtime(tmp_path)
    runtime.ensure_epoch(11, checkpoint_dir=tmp_path, run_id="r")  # boundary
    assert runtime.current_epoch.epoch_seq == 1

    events = _audit_events(tmp_path, "meta_evolution")
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["outcome"] == "proposed"
    assert payload["candidate_count"] == 1
    assert payload["output_count"] == 1
    # FIX-C's guard, scoped precisely (Task 14): no meta agent whose actor
    # the COORDINATOR routes may skip on ``no invoker registered``.
    # ``policy_mutator`` is the one deliberate exception — its actor is
    # invoked directly from ``_run_epoch_boundary`` (plan 14 §5.4) and emits
    # a ``utility_policy_candidate``, a record type outside the
    # coordinator's closed ``meta_rules.OUTPUT_KINDS`` vocabulary, so it is
    # not routable here and its invoker is honestly absent rather than
    # faked. That it is REACHED at all is asserted by the Task 14 boundary
    # tests (tests/test_rqgm_utility_boundary.py).
    no_invoker = [s for s in payload["skipped"] if "no invoker registered" in s]
    assert no_invoker == [POLICY_MUTATOR_NO_INVOKER_SKIP]
    assert payload["skipped"] == [
        CLEAN_ROOM_REACHED_SKIP,
        FAILURE_COMPRESSOR_REACHED_SKIP,
        POLICY_MUTATOR_NO_INVOKER_SKIP,
        REPLAY_SELECTOR_REACHED_SKIP,
    ]

    # Exactly one meta output: the mutator's, recorded then kernel-routed.
    outputs = _audit_events(tmp_path, "meta_agent_output")
    assert len(outputs) == 1
    out = outputs[0]["payload"]
    assert out["component_id"] == "prompt_mutator_v1"
    assert out["role"] == "prompt_mutator"
    assert out["output_kind"] == "prompt_candidate"
    assert out["target_role"] == "generator"
    assert out["candidate_ref"] == EXPECTED_META_CANDIDATE
    assert out["status"] == "recorded"
    assert out["shadow"] is False
    assert [r["record_id"] for r in _meta_outputs(tmp_path)] == [
        out["record_id"]
    ]

    # The routed candidate sits in the Task 07 intake at status:candidate,
    # stamped with its meta-output provenance.
    cands = _candidates(tmp_path)
    ids = [c["candidate_id"] for c in cands]
    # No double-generation across FIX-A + meta in ONE boundary: FIX-A's
    # capped set plus EXACTLY one meta addition, all ids distinct.
    assert ids == EXPECTED_CALM_CANDIDATES + [EXPECTED_META_CANDIDATE]
    assert len(ids) == len(set(ids))
    meta_cand = cands[-1]
    assert meta_cand["status"] == "candidate"
    assert meta_cand["epoch_id"] == "epoch_000"
    assert meta_cand["mutation_kind"] == "threshold_tuning"  # llm=None knob
    assert meta_cand["generated_by"]["component_id"] == "prompt_mutator_v1"
    assert meta_cand["generated_by"]["meta_output_record_id"] == \
        out["record_id"]
    assert evolved_prompt_path(tmp_path, EXPECTED_META_CANDIDATE).exists()


def test_meta_channel_with_injected_llm_uses_the_llm_backed_kind(tmp_path):
    """With an injected (deterministic fake) LLM the degrade ladder picks
    the first configured LLM-backed kind (``freeform_mutation``) in BOTH
    channels; the meta candidate carries the fake bytes' hash."""
    from types import SimpleNamespace

    from ari.rqgm.events import hash12
    from ari.rqgm.runtime import RQGMRuntime

    reply = "Deterministically rewritten role instruction (fake; test only)."

    class _FakeLLM:
        def __init__(self):
            self.calls = []

        def complete(self, messages, require_tool=False, **kwargs):
            self.calls.append({"messages": messages, "kwargs": kwargs})
            return SimpleNamespace(content=reply)

    llm = _FakeLLM()
    cfg = ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": True})
    runtime = RQGMRuntime(cfg, checkpoint_dir=tmp_path, llm=llm)
    ep = runtime.ensure_epoch(1, checkpoint_dir=tmp_path, run_id="r")
    assert ep is not None and ep.epoch_id == "epoch_000"
    runtime.ensure_epoch(11, checkpoint_dir=tmp_path, run_id="r")
    assert runtime.current_epoch.epoch_seq == 1

    cands = _candidates(tmp_path)
    ids = [c["candidate_id"] for c in cands]
    assert ids == EXPECTED_CALM_CANDIDATES + [EXPECTED_META_CANDIDATE]
    assert len(ids) == len(set(ids))
    assert {c["mutation_kind"] for c in cands} == {"freeform_mutation"}
    meta_cand = cands[-1]
    assert meta_cand["prompt_hash"] == hash12(reply)
    assert meta_cand["generated_by"]["meta_output_record_id"]
    # The mutator's LLM seam is cost-tagged (phase/skill metadata).
    assert llm.calls
    assert {c["kwargs"].get("phase") for c in llm.calls} == {"governance"}
    assert {c["kwargs"].get("skill") for c in llm.calls} == {"prompt_mutator"}
    events = _audit_events(tmp_path, "meta_evolution")
    assert events[-1]["payload"]["outcome"] == "proposed"


def test_meta_channel_honors_prompt_evolution_disabled(tmp_path):
    """``rqgm.prompt_evolution.enabled=false`` turns the Task 07 intake off:
    the meta channel mints nothing either (the ``_process_clean_room``
    precedent) — but both invokers stay REACHED, never absent."""
    runtime = _runtime(tmp_path,
                       rqgm={"prompt_evolution": {"enabled": False}})
    runtime.ensure_epoch(11, checkpoint_dir=tmp_path, run_id="r")
    assert runtime.current_epoch.epoch_seq == 1
    assert _candidates(tmp_path) == []
    # Task 14 (plan 14 §5.3): {ckpt}/rqgm_prompts/ now also holds the
    # FOUNDING utility-policy body (a .json), written by the bootstrap
    # regardless of prompt_evolution. The regression this line guards is
    # "prompt evolution disabled => no EVOLVED template bodies", which is
    # exactly the .md files.
    assert not list((tmp_path / "rqgm_prompts").glob("*.md"))
    assert _meta_outputs(tmp_path) == []
    events = _audit_events(tmp_path, "meta_evolution")
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["outcome"] == "no_op"
    assert payload["candidate_count"] == 0
    assert payload["skipped"] == [
        CLEAN_ROOM_REACHED_SKIP,
        FAILURE_COMPRESSOR_REACHED_SKIP,
        POLICY_MUTATOR_NO_INVOKER_SKIP,
        "empty output from prompt_mutator_v1",
        REPLAY_SELECTOR_REACHED_SKIP,
    ]


def test_meta_budget_zero_boundary_routes_nothing(tmp_path):
    """``rqgm.meta_evolution.max_meta_candidates_per_epoch: 0``: the invoker
    prechecks the plan-11 budget and stands down BEFORE proposing (no
    orphan body writes) — FIX-A's plan-07 channel is untouched."""
    runtime = _runtime(
        tmp_path,
        rqgm={"meta_evolution": {"max_meta_candidates_per_epoch": 0}},
    )
    runtime.ensure_epoch(11, checkpoint_dir=tmp_path, run_id="r")
    assert [c["candidate_id"] for c in _candidates(tmp_path)] == \
        EXPECTED_CALM_CANDIDATES
    assert not evolved_prompt_path(
        tmp_path, EXPECTED_META_CANDIDATE
    ).exists()
    assert _meta_outputs(tmp_path) == []
    payload = _audit_events(tmp_path, "meta_evolution")[0]["payload"]
    assert payload["outcome"] == "no_op"
    assert payload["candidate_count"] == 0
    assert payload["skipped"] == [
        CLEAN_ROOM_REACHED_SKIP,
        FAILURE_COMPRESSOR_REACHED_SKIP,
        POLICY_MUTATOR_NO_INVOKER_SKIP,
        "empty output from prompt_mutator_v1",
        REPLAY_SELECTOR_REACHED_SKIP,
    ]


def test_plan07_budget_zero_keeps_the_channels_separate(tmp_path):
    """The plan-07 caps govern the plan-07 path only: with
    ``max_total_candidates_per_epoch: 0`` FIX-A mints nothing, while the
    meta channel still books its ≤1 proposal against the SEPARATE plan-11
    budget — one candidate total, no duplicates, coherent audit lines."""
    runtime = _runtime(
        tmp_path,
        rqgm={"prompt_evolution": {"max_total_candidates_per_epoch": 0}},
    )
    runtime.ensure_epoch(11, checkpoint_dir=tmp_path, run_id="r")
    pe_events = _audit_events(tmp_path, "prompt_evolution")
    assert pe_events[0]["payload"]["outcome"] == "no_candidates"
    assert pe_events[0]["payload"]["candidate_ids"] == []
    cands = _candidates(tmp_path)
    # First sorted evolvable role: nothing was covered, so `adversary`.
    assert [c["candidate_id"] for c in cands] == ["adversary_prompt_v2"]
    assert cands[0]["generated_by"]["meta_output_record_id"]
    payload = _audit_events(tmp_path, "meta_evolution")[0]["payload"]
    assert payload["outcome"] == "proposed"
    assert payload["candidate_count"] == 1


def test_meta_step_rerun_is_idempotent_within_the_boundary_window(tmp_path):
    """Resume idempotency: a crashed boundary window re-runs audit + meta
    against the same open epoch — the meta channel finds its recorded
    output on disk and stands down (no duplicate meta outputs, no
    duplicate candidate records); a resumed process behaves identically."""
    runtime = _runtime(tmp_path)
    report = runtime.run_epoch_audit(tmp_path)
    assert report is not None
    runtime._run_meta_evolution(report)
    meta_before = [r["record_id"] for r in _meta_outputs(tmp_path)]
    cands_before = [c["record_id"] for c in _candidates(tmp_path)]
    assert len(meta_before) == 1
    assert len(cands_before) == len(EXPECTED_CALM_CANDIDATES) + 1

    # Crash-window re-run: the same pre-commit sequence, same open epoch.
    report2 = runtime.run_epoch_audit(tmp_path)
    runtime._run_meta_evolution(report2)
    assert [r["record_id"] for r in _meta_outputs(tmp_path)] == meta_before
    assert [c["record_id"] for c in _candidates(tmp_path)] == cands_before
    events = _audit_events(tmp_path, "meta_evolution")
    assert [e["payload"]["outcome"] for e in events] == ["proposed", "no_op"]
    assert events[-1]["payload"]["skipped"] == [
        CLEAN_ROOM_REACHED_SKIP,
        FAILURE_COMPRESSOR_REACHED_SKIP,
        POLICY_MUTATOR_NO_INVOKER_SKIP,
        "empty output from prompt_mutator_v1",
        REPLAY_SELECTOR_REACHED_SKIP,
    ]

    # Resumed process over the same checkpoint: still a reached no-op —
    # even without a governance report (different input-bundle hash), the
    # per-epoch guard keys on (component, epoch, kind), not the record id.
    from ari.rqgm.runtime import RQGMRuntime

    cfg = ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": True})
    resumed = RQGMRuntime(cfg, checkpoint_dir=tmp_path)
    ep = resumed.ensure_epoch(1, checkpoint_dir=tmp_path, run_id="r")
    assert ep is not None and ep.epoch_id == "epoch_000"
    resumed._run_meta_evolution(None)
    assert [r["record_id"] for r in _meta_outputs(tmp_path)] == meta_before
    assert [c["record_id"] for c in _candidates(tmp_path)] == cands_before


def test_meta_disabled_boundary_keeps_the_pinned_skipped_event(tmp_path):
    runtime = _runtime(tmp_path, rqgm={"meta_evolution": {"enabled": False}})
    runtime.ensure_epoch(11, checkpoint_dir=tmp_path, run_id="r")
    assert runtime.current_epoch.epoch_seq == 1
    skipped = _audit_events(tmp_path, "meta_evolution_skipped")
    assert len(skipped) == 1
    assert skipped[0]["payload"]["reason"] == "meta_evolution.enabled=false"
    assert _audit_events(tmp_path, "meta_evolution") == []


def test_meta_failure_and_skips_are_audit_visible(tmp_path):
    runtime = _runtime(tmp_path)

    class _Boom:
        def run_epoch_boundary_step(self, **kwargs):
            raise RuntimeError("boom")

    runtime._meta_evolution = _Boom()
    runtime._run_meta_evolution(None)
    events = _audit_events(tmp_path, "meta_evolution")
    assert events[-1]["payload"]["outcome"] == "failed"
    assert "RuntimeError: boom" in events[-1]["payload"]["reason"]

    # Governance-suspended carry-over: skip, with the reason on record.
    runtime.governance_suspended = True
    runtime._run_meta_evolution(None)
    events = _audit_events(tmp_path, "meta_evolution")
    assert events[-1]["payload"] == {
        "epoch_id": "epoch_000",
        "outcome": "skipped",
        "reason": "governance_suspended",
    }

    # No coordinator (kernel unavailable): skip, with the reason on record.
    runtime.governance_suspended = False
    runtime._meta_evolution = None
    runtime.kernel = None
    runtime._run_meta_evolution(None)
    events = _audit_events(tmp_path, "meta_evolution")
    assert events[-1]["payload"]["outcome"] == "skipped"
    assert "no MetaEvolutionCoordinator" in events[-1]["payload"]["reason"]


# ── constraints: simple_bfts untouched (mode-gap guard) ─────────────────────


def test_simple_bfts_run_writes_no_evolution_files(monkeypatch, tmp_path):
    """The generation path lives behind ``RQGMRuntime`` only — a default
    (simple_bfts) loop must produce neither prompt_evolution.jsonl nor
    rqgm_prompts/ (mirrors the sibling zero-file regressions)."""
    from unittest.mock import MagicMock
    from types import SimpleNamespace

    from ari.cli import _run_loop
    from ari.orchestrator.node import Node

    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    cfg = ARIConfig(bfts={"max_total_nodes": 2, "max_parallel_nodes": 1,
                          "timeout_per_node": 60})
    agent = MagicMock()
    agent.hints = SimpleNamespace(provided_files=[], slurm_partition="",
                                  slurm_max_cpus=0)
    agent.memory = MagicMock()
    agent.memory.search.return_value = []

    def _run(node, exp_data):
        node.mark_running()
        node.mark_success(eval_summary="ok")
        node.has_real_data = True
        return node

    agent.run.side_effect = _run
    bfts = MagicMock()
    bfts.should_prune.return_value = False

    def _expand(node, *args, **kwargs):
        child = Node(id="child_1", parent_id=node.id, depth=node.depth + 1)
        node.children.append(child.id)
        return [child]

    bfts.expand.side_effect = _expand
    bfts.select_best_to_expand.side_effect = (
        lambda frontier, goal, mem: frontier[0]
    )
    bfts.select_next_node.side_effect = lambda pending, goal, mem: pending[0]
    bfts.expansion_count.return_value = 0
    bfts.diversity_bonus.return_value = 0.0
    del bfts.rqgm
    root = Node(id="node_root", parent_id=None, depth=0)
    _run_loop(
        cfg, bfts, agent, [root], [root],
        {"goal": "g", "topic": "t", "file": "exp.md"},
        checkpoint_dir=tmp_path, run_id="simple-evolution-guard",
    )
    assert not (tmp_path / "prompt_evolution.jsonl").exists()
    assert not (tmp_path / "rqgm_prompts").exists()
    assert not (tmp_path / "rqgm_audit.jsonl").exists()
