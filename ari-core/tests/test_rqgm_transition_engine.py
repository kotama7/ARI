"""RQGM Task 09 — RegistryTransitionEngine (docs/plans/ari_rqgm/09 §9).

Covers: the exhaustive edge matrix through ``allowed_transitions`` + the
kernel (§9.1), byte-identical determinism of ``resolve_transition`` (§9.2),
per-rule trigger/guard fixtures T1–T19 (§9.3), boundary-only vs. the single
emergency shape (§9.4), prepare-without-commit crash recovery / double-apply
no-op / abort fail-safe (§9.5), the emergency fallback policy (§9.6), actor
separation via the kernel epoch-invariance check (§9.7), the ``simple_bfts``
zero-file regression (§9.8), the two-epoch ``ari_rqgm`` smoke with the
prepare → per-change → commit event sequence (§9.9), META_FILES hygiene
(§9.10), and the no-VirSci/no-LLM import guarantee (§9.11).

No test calls a real LLM; all inputs are deterministic fixtures (P2).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ari.config import ARIConfig, RQGMTransitionConfig
from ari.rqgm.events import TransitionEvent, canonical_json
from ari.rqgm.kernel import ConstitutionalKernel
from ari.rqgm.kernel_rules import REGISTRY_WRITER
from ari.rqgm.registry import (
    ComponentEntry,
    ComponentRegistry,
    GovernedPromptEntry,
    GovernedPromptRegistry,
)
from ari.rqgm.store import (
    RQGM_TRANSITIONS_FILENAME,
    ImmutableAuditLog,
    RqgmRuntimeState,
    RqgmStateStore,
)
from ari.rqgm.transition_engine import (
    EMERGENCY_TRIGGER_CODES,
    KNOWN_ACTIONS,
    EpochTransition,
    RegistryTransitionEngine,
    build_status_history,
)
from ari.rqgm.transition_rules import (
    EMERGENCY_EDGE,
    TRANSITION_TABLE,
    ComponentStatus,
)

_H = "a" * 12
_H2 = "b" * 12


@pytest.fixture(autouse=True)
def _no_env_pin(monkeypatch):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)


# ── fixture builders ────────────────────────────────────────────────────────


def _comp(cid, role, status, *, prompt_id=None, registered="epoch_000"):
    return ComponentEntry(
        component_id=cid, role=role, tier="institutional", status=status,
        prompt_id=prompt_id, epoch_id_registered=registered,
    )


def _prompt(pid, role, status, *, prompt_hash=_H, registered="epoch_000"):
    return GovernedPromptEntry(
        prompt_id=pid, role=role, status=status, prompt_hash=prompt_hash,
        prompt_sha256=prompt_hash + "0" * 52,
        source={"kind": "committed_template", "key": f"{role}/base"},
        epoch_id_registered=registered,
    )


def _registries(comps=(), prompts=()):
    return (
        ComponentRegistry({c.component_id: c for c in comps}),
        GovernedPromptRegistry({p.prompt_id: p for p in prompts}),
    )


def _epoch(seq=1):
    return SimpleNamespace(epoch_id="epoch_%03d" % seq, epoch_seq=seq)


def _report(recommendations=(), candidate_evaluations=(), *,
            replay_cases_used=0, ban_recommendations=()):
    return {
        "record_id": "govreport_epoch_001",
        "record_type": "governance_report",
        "recommendations": list(recommendations),
        "candidate_evaluations": list(candidate_evaluations),
        "budget_usage": {"llm_calls": 0,
                         "replay_cases_used": int(replay_cases_used),
                         "anchor_cases_used": 0},
        "self_audit": {"ban_recommendations": list(ban_recommendations)},
    }


def _rec(action, target, *, prompt=False, refs=("basis_1",)):
    key = "target_prompt_id" if prompt else "target_component_id"
    return {key: target, "action": action, "basis_refs": list(refs),
            "confidence": 0.9}


def _engine(store=None, audit_log=None, config=None, enforcement="standard"):
    return RegistryTransitionEngine(
        config if config is not None else ARIConfig().rqgm,
        ConstitutionalKernel(),
        store=store,
        enforcement=enforcement,
        audit_log=audit_log,
    )


def _resolve(engine, comps, prompts, report, *, seq=1, history=None,
             suspended=False, evaluations=()):
    return engine.resolve_transition(
        epoch_state=_epoch(seq),
        governance_report=report,
        candidate_evaluations=evaluations,
        components=comps,
        prompts=prompts,
        status_history=history or {},
        governance_suspended=suspended,
    )


def _rules_of(t: EpochTransition) -> list:
    return sorted(e["rule_id"] for e in t.changes())


# ── §9.1 table exhaustiveness through the engine surface ────────────────────


_STATUSES = [s.value for s in ComponentStatus]


def test_allowed_transitions_matches_the_21_row_table():
    accepted = {
        (frm, to)
        for frm in _STATUSES
        for to in RegistryTransitionEngine.allowed_transitions(frm)
    }
    assert accepted == set(TRANSITION_TABLE)
    # Task 14 (plan 14 §5.5): T20 (active -> retired) supersession joins the
    # table (role-scoped to utility_policy in the kernel). Wave 3c (plan
    # ari_rqgm_paper/05 / 03 §5.9): T21 (active -> shadow) paper-role
    # shadow-standby supersession joins it too, so 21 rows.
    assert len(TRANSITION_TABLE) == 21


def test_named_forbidden_edges_rejected():
    assert "active" not in RegistryTransitionEngine.allowed_transitions(
        "candidate")   # no instant activation (invariant 15)
    assert RegistryTransitionEngine.allowed_transitions("banned") == \
        frozenset()    # absorbing
    assert "active" not in RegistryTransitionEngine.allowed_transitions(
        "retired")     # no resurrection
    # Task 14: active -> retired IS now a table row (T20 supersession) but the
    # kernel scopes it to the utility_policy role — for a behavioral component
    # it is still rejected (retirement stages via quarantine).
    assert "retired" in RegistryTransitionEngine.allowed_transitions(
        "active")      # T20 supersession row exists...
    # And the kernel rejects each with CK-REG-001, distinct per-pair detail
    # (active -> retired is rejected for the ROLE-LESS component below —
    # supersession is legal only for utility_policy, tested in the kernel
    # suite).
    k = ConstitutionalKernel()
    details = set()
    for frm, to in [("candidate", "active"), ("retired", "active"),
                    ("banned", "candidate"), ("active", "retired")]:
        t = {"epoch_transition_id": "x", "produced_by": REGISTRY_WRITER,
             "emergency": False,
             "sanctions": [{"component_id": "c1", "from_status": frm,
                            "to_status": to}]}
        report = k.validate_transition(t, None, None)
        codes = [v.code for v in report.violations]
        assert "CK-REG-001" in codes, (frm, to)
        details.update(v.detail for v in report.violations
                       if v.code == "CK-REG-001")
    assert len(details) == 4  # distinct per named edge


def test_unknown_status_is_ineligible_never_a_crash():
    assert RegistryTransitionEngine.allowed_transitions("mystery") == \
        frozenset()
    comps, prompts = _registries([_comp("gen_v1", "generator", "mystery")])
    t = _resolve(_engine(), comps, prompts, _report([_rec("warn", "gen_v1")]))
    assert t.is_empty()
    assert any("unknown status" in n for n in t.notes)


# ── §9.2 determinism (P2) ───────────────────────────────────────────────────


def test_resolve_transition_is_byte_deterministic():
    comps, prompts = _registries(
        [_comp("reviewer_v1", "reviewer", "active",
               prompt_id="reviewer_prompt_v1"),
         _comp("generator_v2", "generator", "shadow",
               prompt_id="generator_prompt_v2")],
        [_prompt("reviewer_prompt_v1", "reviewer", "active"),
         _prompt("generator_prompt_v2", "generator", "shadow",
                 prompt_hash=_H2)],
    )
    report = _report(
        [_rec("warn", "reviewer_v1")],
        [{"prompt_id": "generator_prompt_v2", "role": "generator",
          "verdict": "pass", "shadow_score": 0.9, "shadow_samples": 6,
          "case_refs": ["case_1"]}],
    )

    def run():
        t = _resolve(_engine(), comps, prompts, report)
        return canonical_json(t.to_dict())

    assert run() == run()


# ── §9.3 per-rule trigger + guard fixtures ──────────────────────────────────


def test_t1_candidate_validated_and_cap_guard():
    comps, prompts = _registries(
        prompts=[_prompt("gen_prompt_c1", "generator", "candidate"),
                 _prompt("gen_prompt_c2", "generator", "candidate")],
    )
    evals = [
        {"prompt_id": "gen_prompt_c1", "role": "generator",
         "verdict": "pass"},
        {"prompt_id": "gen_prompt_c2", "role": "generator",
         "verdict": "pass"},
    ]
    t = _resolve(_engine(), comps, prompts, _report(), evaluations=evals)
    # Per-role candidate cap (prompt_evolution default: 1): first sorted id
    # promotes, the second is noted.
    assert _rules_of(t) == ["T1"]
    assert t.adoptions[0]["prompt_id"] == "gen_prompt_c1"
    assert t.adoptions[0]["to_status"] == "validated"
    assert any("candidate cap" in n for n in t.notes)


def test_t2_validation_failure_and_expiry_are_terminal_without_retirement_event():
    comps, prompts = _registries(
        prompts=[_prompt("gen_prompt_bad", "generator", "candidate"),
                 _prompt("gen_prompt_old", "generator", "candidate")],
    )
    evals = [{"prompt_id": "gen_prompt_bad", "role": "generator",
              "verdict": "fail"}]
    t = _resolve(_engine(), comps, prompts, _report(), seq=4,
                 evaluations=evals)  # age 4 >= candidate_max_age_epochs 3
    assert _rules_of(t) == ["T2", "T2"]
    # Never-served rejection: NO RetirementEvent / clean-room request.
    assert t.retirements == [] and t.clean_room_requests == []
    reasons = sorted(e["reason"] for e in t.sanctions)
    assert reasons == ["candidate_expired", "validation_failed"]


def test_t3_replay_guard_pass_and_fail():
    comps, prompts = _registries(
        prompts=[_prompt("gen_prompt_v", "generator", "validated")])
    ok = [{"prompt_id": "gen_prompt_v", "role": "generator",
           "verdict": "pass", "replay_score": 0.9, "anchor_score": 0.85,
           "case_refs": ["c1", "c2", "c3", "c4"]}]
    t = _resolve(_engine(), comps, prompts, _report(), evaluations=ok)
    assert _rules_of(t) == ["T3"]
    assert t.adoptions[0]["to_status"] == "shadow"
    weak = [dict(ok[0], case_refs=["c1", "c2"])]  # below replay_min_cases
    t2 = _resolve(_engine(), comps, prompts, _report(), evaluations=weak)
    assert t2.is_empty()
    assert any("T3" in n and "guard failed" in n for n in t2.notes)


def test_t4_t5_shadow_retry_then_rejection():
    comps, prompts = _registries(
        prompts=[_prompt("gen_prompt_s", "generator", "shadow")])
    # Insufficient samples past shadow_max_epochs: first time T4 retry...
    t = _resolve(_engine(), comps, prompts, _report(), seq=3)
    assert _rules_of(t) == ["T4"]
    assert t.sanctions[0]["to_status"] == "validated"
    # ...but beyond shadow_retry_limit it is the T5 terminal rejection.
    history = {"gen_prompt_s": {"status": "shadow", "since_seq": 0,
                                "rule_counts": {"T4": 1}}}
    t2 = _resolve(_engine(), comps, prompts, _report(), seq=3,
                  history=history)
    assert _rules_of(t2) == ["T5"]
    assert t2.sanctions[0]["to_status"] == "retired"
    # Quality below threshold with sufficient samples is also T5.
    evals = [{"prompt_id": "gen_prompt_s", "role": "generator",
              "verdict": "pass", "shadow_score": 0.2, "shadow_samples": 6}]
    t3 = _resolve(_engine(), comps, prompts, _report(), evaluations=evals)
    assert _rules_of(t3) == ["T5"]


def test_t6_adoption_needs_samples_and_role_opening():
    comps, prompts = _registries(
        prompts=[_prompt("gen_prompt_s", "generator", "shadow")])
    good = [{"prompt_id": "gen_prompt_s", "role": "generator",
             "verdict": "pass", "shadow_score": 0.9, "shadow_samples": 5}]
    t = _resolve(_engine(), comps, prompts, _report(), evaluations=good)
    assert _rules_of(t) == ["T6"]
    assert t.adoptions[0]["to_status"] == "probationary_active"
    # Guard: below shadow_min_samples -> no adoption (and no rejection yet).
    few = [dict(good[0], shadow_samples=2)]
    t2 = _resolve(_engine(), comps, prompts, _report(), evaluations=few)
    assert t2.is_empty()
    # Guard: a healthy incumbent blocks the opening.
    comps2, _ = _registries([_comp("generator_v1", "generator", "active")])
    t3 = _resolve(_engine(), comps2, prompts, _report(), evaluations=good)
    assert t3.is_empty()
    assert any("no role opening" in n for n in t3.notes)


def test_t7_promotion_requires_probation_min_epochs():
    comps, prompts = _registries(
        [_comp("reviewer_v2", "reviewer", "probationary_active",
               prompt_id="reviewer_prompt_v2")],
        [_prompt("reviewer_prompt_v2", "reviewer", "probationary_active",
                 prompt_hash=_H2)],
    )
    # Adopted THIS epoch (since_seq == seq): not served long enough.
    history = {"reviewer_v2": {"status": "probationary_active",
                               "since_seq": 1, "rule_counts": {"T6": 1}}}
    t = _resolve(_engine(), comps, prompts, _report(), seq=1,
                 history=history)
    assert t.is_empty()
    assert any("probation_min_epochs" in n for n in t.notes)
    # One full clean epoch later: T7.
    t2 = _resolve(_engine(), comps, prompts, _report(), seq=2,
                  history=history)
    assert _rules_of(t2) == ["T7"]
    assert t2.adoptions[0]["to_status"] == "active"


def test_t8_t11_t15_quarantine_paths():
    comps, prompts = _registries([
        _comp("a_v1", "adversary", "probationary_active"),
        _comp("g_v1", "generator", "active"),
        _comp("r_v1", "reviewer", "probation"),
    ])
    report = _report([
        _rec("quarantine", "a_v1"),
        _rec("quarantine", "g_v1"),
        _rec("retire", "r_v1"),
    ])
    t = _resolve(_engine(), comps, prompts, report, seq=5)
    assert _rules_of(t) == ["T11", "T15", "T8"]
    by_cid = {e["component_id"]: e for e in t.sanctions}
    assert by_cid["a_v1"]["rule_id"] == "T8"
    assert by_cid["g_v1"]["rule_id"] == "T11"
    assert by_cid["r_v1"]["rule_id"] == "T15"
    # Every removed role gets a fallback entry (baseline: no prior version).
    assert sorted(f["role"] for f in t.fallbacks) == \
        ["adversary", "generator", "reviewer"]
    assert all(f["baseline"] for f in t.fallbacks)


def test_t10_repeated_warnings_escalate_at_warning_escalation_count():
    comps, prompts = _registries([_comp("g_v1", "generator", "active")])
    # One prior committed T9 warning + this one == warning_escalation_count
    # (default 2): the plan's T10 "repeated warnings" trigger fires.
    history = {"g_v1": {"status": "active", "since_seq": 3,
                        "rule_counts": {"T9": 1, "T12": 1}}}
    t = _resolve(_engine(), comps, prompts, _report([_rec("warn", "g_v1")]),
                 seq=5, history=history)
    assert _rules_of(t) == ["T10"]
    assert t.sanctions[0]["to_status"] == "probation"
    assert t.sanctions[0]["reason"] == "repeated_warnings"
    # Below the escalation count the same signal is a plain T9.
    fresh = _resolve(_engine(), comps, prompts,
                     _report([_rec("warn", "g_v1")]), seq=5)
    assert _rules_of(fresh) == ["T9"]


def test_t9_t10_serving_sanctions_keep_the_prompt_serving():
    comps, prompts = _registries(
        [_comp("g_v1", "generator", "active",
               prompt_id="gen_prompt_v1")],
        [_prompt("gen_prompt_v1", "generator", "active")],
    )
    t9 = _resolve(_engine(), comps, prompts, _report([_rec("warn", "g_v1")]))
    assert _rules_of(t9) == ["T9"]
    assert t9.sanctions[0]["severity"] == "low"
    t10 = _resolve(_engine(), comps, prompts,
                   _report([_rec("demote", "g_v1")]))
    assert _rules_of(t10) == ["T10"]
    # Serving posture: NO prompt_status_change event is decomposed.
    for t in (t9, t10):
        types = [ev.event_type for ev in _engine().decompose(t)]
        assert types == ["component_status_change"]
    # The warned component still holds the role (serving semantics).
    assert t9.next_active_components == {"generator": "g_v1"}


def test_t12_t13_warning_recovery_and_recurrence():
    comps, prompts = _registries([_comp("g_v1", "generator", "warning")])
    history = {"g_v1": {"status": "warning", "since_seq": 4,
                        "rule_counts": {"T9": 1}}}
    clean = _resolve(_engine(), comps, prompts, _report(), seq=5,
                     history=history)
    assert _rules_of(clean) == ["T12"]
    recur = _resolve(_engine(), comps, prompts,
                     _report([_rec("warn", "g_v1")]), seq=5, history=history)
    assert _rules_of(recur) == ["T13"]
    assert recur.sanctions[0]["to_status"] == "probation"
    # Outside warning_memory_epochs the recurrence does not escalate.
    old = {"g_v1": {"status": "warning", "since_seq": 0, "rule_counts": {}}}
    stale = _resolve(_engine(), comps, prompts,
                     _report([_rec("warn", "g_v1")]), seq=5, history=old)
    assert stale.is_empty()
    assert any("warning_memory_epochs" in n for n in stale.notes)


def test_t14_rehabilitation_after_clean_probation():
    comps, prompts = _registries([_comp("g_v1", "generator", "probation")])
    history = {"g_v1": {"status": "probation", "since_seq": 3,
                        "rule_counts": {"T10": 1}}}
    t = _resolve(_engine(), comps, prompts, _report(), seq=4,
                 history=history)
    assert _rules_of(t) == ["T14"]
    assert t.adoptions[0]["to_status"] == "active"


def test_t17_retirement_needs_replay_coverage_and_emits_events():
    comps, prompts = _registries(
        [_comp("r_v1", "reviewer", "quarantine",
               prompt_id="rev_prompt_v1")],
        [_prompt("rev_prompt_v1", "reviewer", "quarantine")],
    )
    below = _resolve(_engine(), comps, prompts,
                     _report([_rec("retire", "r_v1")], replay_cases_used=3))
    assert below.is_empty()
    assert any("retirement_replay_min_cases" in n for n in below.notes)
    t = _resolve(_engine(), comps, prompts,
                 _report([_rec("retire", "r_v1")], replay_cases_used=8))
    assert _rules_of(t) == ["T17"]
    entry = t.retirements[0]
    assert entry["retirement_event_id"]
    assert entry["evidence_refs"] == ["basis_1"]
    assert t.clean_room_requests[0]["retirement_event_id"] == \
        entry["retirement_event_id"]
    assert t.clean_room_requests[0]["target_role"] == "reviewer"


def test_t18_exoneration_reenters_under_probation_never_active():
    comps, prompts = _registries([_comp("r_v1", "reviewer", "quarantine")])
    t = _resolve(_engine(), comps, prompts,
                 _report([_rec("no_action", "r_v1")]))
    assert _rules_of(t) == ["T18"]
    assert t.adoptions[0]["to_status"] == "probationary_active"


def test_t19_ban_is_absorbing():
    comps, prompts = _registries([_comp("r_v0", "reviewer", "retired")])
    t = _resolve(_engine(), comps, prompts,
                 _report(ban_recommendations=["r_v0"]))
    assert _rules_of(t) == ["T19"]
    assert t.bans[0]["to_status"] == "banned"
    # Once banned, nothing ever fires again.
    comps2, _ = _registries([_comp("r_v0", "reviewer", "banned")])
    t2 = _resolve(_engine(), comps2, prompts,
                  _report([_rec("retire", "r_v0")],
                          ban_recommendations=["r_v0"],
                          replay_cases_used=99))
    assert t2.is_empty()


def test_retire_recommendation_on_active_stages_via_quarantine():
    comps, prompts = _registries([_comp("g_v1", "generator", "active")])
    t = _resolve(_engine(), comps, prompts, _report([_rec("retire", "g_v1")]))
    assert _rules_of(t) == ["T11"]  # T17 only from quarantine, next boundary
    assert t.retirements == []


def test_unknown_recommendation_action_is_dropped():
    comps, prompts = _registries([_comp("g_v1", "generator", "active")])
    t = _resolve(_engine(), comps, prompts,
                 _report([_rec("obliterate", "g_v1")]))
    assert t.is_empty()
    assert any("unknown recommendation action" in n for n in t.notes)


def test_governance_suspended_freezes_all_changes():
    comps, prompts = _registries([_comp("g_v1", "generator", "active")])
    t = _resolve(_engine(), comps, prompts,
                 _report([_rec("quarantine", "g_v1")]), suspended=True)
    assert t.is_empty()
    assert any("governance_suspended" in n for n in t.notes)
    # And with no report at all, nothing changes either (fail-safe).
    t2 = _resolve(_engine(), comps, prompts, None)
    assert t2.is_empty()
    assert any("no_governance_report" in n for n in t2.notes)


# ── §9.4 boundary-only vs. the single emergency shape ───────────────────────


def test_non_emergency_transition_is_rejected_mid_epoch():
    comps, prompts = _registries([_comp("g_v1", "generator", "active")])
    t = _resolve(_engine(), comps, prompts, _report([_rec("warn", "g_v1")]))
    report = ConstitutionalKernel().validate_transition(
        t.to_dict(), None, None, at_boundary=False)
    assert report.blocking
    assert "CK-REG-002" in [v.code for v in report.violations]


def test_emergency_with_non_critical_trigger_is_rejected():
    comps, prompts = _registries([_comp("g_v1", "generator", "active")])
    engine = _engine()
    t = engine.emergency_quarantine(
        violation={"code": "CK-CTX-001", "severity": "warn",
                   "subject_ref": "g_v1"},
        component_id="g_v1", epoch_state=_epoch(1),
        components=comps, prompts=prompts,
    )
    assert t.status == "rejected"
    assert any("non-critical" in n for n in t.notes)


def test_emergency_naming_two_components_is_rejected_by_the_kernel():
    comps, prompts = _registries([
        _comp("g_v1", "generator", "active"),
        _comp("r_v1", "reviewer", "active"),
    ])
    engine = _engine()
    t = engine.emergency_quarantine(
        violation={"code": "CK-HSH-010", "subject_ref": "g_v1"},
        component_id="g_v1", epoch_state=_epoch(1),
        components=comps, prompts=prompts,
    )
    t.sanctions.append(dict(t.sanctions[0], component_id="r_v1"))
    report = ConstitutionalKernel().validate_transition(
        t.to_dict(), None, None, at_boundary=False)
    assert report.blocking
    assert "CK-REG-006" in [v.code for v in report.violations]


def test_emergency_edges_are_exactly_the_four_t16_shapes():
    assert EMERGENCY_EDGE == frozenset({
        ("probationary_active", "quarantine"),
        ("active", "quarantine"),
        ("warning", "quarantine"),
        ("probation", "quarantine"),
    })
    # The closed trigger class is kernel-critical (block) only — performance
    # signals can never qualify (plan 09 §5.4).
    from ari.rqgm.kernel_rules import SEVERITY

    assert all(SEVERITY[c] == "block" for c in EMERGENCY_TRIGGER_CODES)


# ── §9.5 transaction, crash recovery, double-apply, abort ───────────────────


def _bootstrap(tmp_path, extra_events=()):
    """Registered reviewer (active) + generator shadow candidate, epoch open."""
    store = RqgmStateStore()
    events = [
        TransitionEvent(event_type="component_registered", payload={
            "component_id": "reviewer_v1", "role": "reviewer",
            "tier": "institutional", "status": "active",
            "prompt_id": "reviewer_prompt_v1", "epoch_id": "epoch_000"}),
        TransitionEvent(event_type="prompt_registered", payload={
            "prompt_id": "reviewer_prompt_v1", "role": "reviewer",
            "status": "active", "prompt_hash": _H,
            "prompt_sha256": _H + "0" * 52,
            "source": {"kind": "committed_template", "key": "reviewer/base"},
            "epoch_id": "epoch_000"}),
        TransitionEvent(event_type="component_registered", payload={
            "component_id": "generator_v2", "role": "generator",
            "tier": "institutional", "status": "shadow",
            "prompt_id": "generator_prompt_v2", "epoch_id": "epoch_000"}),
        TransitionEvent(event_type="prompt_registered", payload={
            "prompt_id": "generator_prompt_v2", "role": "generator",
            "status": "shadow", "prompt_hash": _H2,
            "prompt_sha256": _H2 + "0" * 52,
            "source": {"kind": "committed_template", "key": "generator/base"},
            "epoch_id": "epoch_000"}),
    ] + list(extra_events)
    store.apply_transition(tmp_path, "bootstrap", events)
    state = store.open_epoch(tmp_path, ARIConfig(), node_count=0,
                             run_id="t09", prior=store.replay(tmp_path))
    return store, state


def _smoke_report():
    return _report(
        [_rec("warn", "reviewer_v1")],
        [{"prompt_id": "generator_prompt_v2", "role": "generator",
          "verdict": "pass", "shadow_score": 0.9, "shadow_samples": 6,
          "case_refs": ["adv_case_00042"]}],
    )


def _resolve_from_state(engine, tmp_path, state, report):
    return engine.resolve_transition(
        epoch_state=state.epoch,
        governance_report=report,
        candidate_evaluations=report["candidate_evaluations"],
        components=state.components,
        prompts=state.prompts,
        status_history=engine.load_status_history(tmp_path),
    )


# ── BUG-1 (b/c): the candidate → active spine fires once entries ARE in ─────
# the registry (the reproduced gap was that minted candidates were never
# registered, so resolve_transition's sorted(proms) iteration never saw them).


def _register_candidate(store, tmp_path, pid, role, status,
                        *, epoch_id="epoch_000", prompt_hash=_H2):
    """Register a governed prompt entry directly through the Task 02 store —
    the storage face of Task 07 candidate intake — then (re)open the epoch."""
    store.apply_transition(tmp_path, f"intake_{pid}", [
        TransitionEvent(event_type="prompt_registered", payload={
            "prompt_id": pid, "role": role, "status": status,
            "prompt_hash": prompt_hash, "prompt_sha256": prompt_hash + "0" * 52,
            "source": {"kind": "committed_template", "key": f"{role}/base"},
            "epoch_id": epoch_id}),
    ])
    return store.open_epoch(tmp_path, ARIConfig(), node_count=0,
                           run_id="spine", prior=store.replay(tmp_path))


def _spine_eval(pid, role, status):
    """The PASSING board evaluation appropriate to a candidate's current
    spine status (T1 needs a pass verdict; T3 needs replay/anchor over the
    min case count; T6 needs shadow score + samples). Prob-active/active edges
    key on served epochs, not the evaluation."""
    if status == "validated":
        return {"prompt_id": pid, "role": role, "verdict": "pass",
                "replay_score": 0.95, "anchor_score": 0.9,
                "case_refs": ["c1", "c2", "c3", "c4"]}
    if status == "shadow":
        return {"prompt_id": pid, "role": role, "verdict": "pass",
                "shadow_score": 0.9, "shadow_samples": 6}
    return {"prompt_id": pid, "role": role, "verdict": "pass"}


def _drive_boundary(engine, store, tmp_path, state, evaluation, *, step):
    report = _report(candidate_evaluations=[evaluation])
    t = engine.resolve_transition(
        epoch_state=state.epoch, governance_report=report,
        candidate_evaluations=report["candidate_evaluations"],
        components=state.components, prompts=state.prompts,
        status_history=engine.load_status_history(tmp_path),
    )
    applied = engine.apply(t, checkpoint_dir=tmp_path, state=state,
                           cfg=ARIConfig(), node_count=step * 10,
                           run_id="spine")
    assert applied.committed, t.notes
    return applied.state


def test_evolved_candidate_advances_candidate_to_active_across_boundaries(
        tmp_path):
    """BUG-1(c): a minted candidate registered at 'candidate' advances
    candidate→validated→shadow→probationary_active→active across boundaries
    through the REAL engine + kernel + Task 02 store — one gated T-edge per
    boundary, never an instant activation (plan 07 no-instant-activation, plan
    09 T1/T3/T6/T7). A prompt-only candidate on a role with no active
    component has a legitimate T6 opening."""
    store = RqgmStateStore()
    pid, role = "reviewer_prompt_v2", "reviewer"
    state = _register_candidate(store, tmp_path, pid, role, "candidate")
    engine = _engine(store=store, audit_log=ImmutableAuditLog(tmp_path))

    assert state.prompts.get(pid).status == "candidate"
    seen = ["candidate"]
    for step in range(1, 9):
        status = state.prompts.get(pid).status
        state = _drive_boundary(
            engine, store, tmp_path, state,
            _spine_eval(pid, role, status), step=step,
        )
        now = state.prompts.get(pid).status
        if now != seen[-1]:
            seen.append(now)
        if now == "active":
            break
    # Exactly the spec-mandated spine, in order, one edge per boundary.
    assert seen == ["candidate", "validated", "shadow",
                    "probationary_active", "active"]


def test_failing_candidate_never_advances_past_its_gate(tmp_path):
    """BUG-1(c) companion: a candidate that fails its board gate never
    advances. A 'validated' candidate whose replay score is below
    ``replay_pass_threshold`` is held at its T3 gate across every boundary and
    never reaches shadow / probationary_active / active — a failing candidate
    must never reach 'active'."""
    store = RqgmStateStore()
    pid, role = "reviewer_prompt_v9", "reviewer"
    state = _register_candidate(store, tmp_path, pid, role, "validated")
    engine = _engine(store=store, audit_log=ImmutableAuditLog(tmp_path))
    weak = {"prompt_id": pid, "role": role, "verdict": "pass",
            "replay_score": 0.4, "anchor_score": 0.4,   # below threshold 0.8
            "case_refs": ["c1", "c2", "c3", "c4"]}
    for step in range(1, 5):
        state = _drive_boundary(engine, store, tmp_path, state, weak,
                                step=step)
        assert state.prompts.get(pid).status == "validated"  # held at T3 gate
    assert state.prompts.get(pid).status not in (
        "shadow", "probationary_active", "active")


def test_adoption_and_warning_commit_with_prepare_change_commit_sequence(
        tmp_path):
    store, state = _bootstrap(tmp_path)
    engine = _engine(store=store, audit_log=ImmutableAuditLog(tmp_path))
    t = _resolve_from_state(engine, tmp_path, state, _smoke_report())
    assert _rules_of(t) == ["T6", "T9"]
    applied = engine.apply(t, checkpoint_dir=tmp_path, state=state,
                           cfg=ARIConfig(), node_count=10, run_id="t09")
    assert applied.committed and t.status == "committed"
    assert applied.state.epoch.epoch_id == "epoch_001"
    # Registry statuses moved only through the engine's transaction.
    assert applied.state.components.get("generator_v2").status == \
        "probationary_active"
    assert applied.state.components.get("reviewer_v1").status == "warning"
    # The prompt mirror: adoption moves the prompt; the warning does NOT.
    assert applied.state.prompts.get("generator_prompt_v2").status == \
        "probationary_active"
    assert applied.state.prompts.get("reviewer_prompt_v1").status == "active"
    # §9.9 event sequence: prepare -> per-change -> epoch close/open -> commit.
    lines = [json.loads(ln) for ln in
             (tmp_path / RQGM_TRANSITIONS_FILENAME).read_text().splitlines()]
    tail = [l["event_type"] for l in lines][-7:]
    assert tail == [
        "epoch_transaction_prepare",
        "component_status_change",   # T6 adoption
        "prompt_status_change",      # T6 prompt mirror
        "component_status_change",   # T9 warning (no prompt mirror)
        "epoch_close",
        "epoch_open",
        "epoch_transaction_commit",
    ]
    # Every change event is stamped by the engine (kernel CK-REG-004 input).
    for line in lines:
        if line["event_type"].endswith("_status_change"):
            assert line["payload"]["produced_by"] == REGISTRY_WRITER
            assert line["payload"]["transition_id"] == \
                t.epoch_transition_id
    # epoch_state.json freeze: the adopted generator serves the next epoch.
    snap = json.loads((tmp_path / "epoch_state.json").read_text())
    assert snap["active_components"]["generator"] == "generator_v2"
    # next_active_components keeps the warned reviewer serving (§5.2).
    assert t.next_active_components == {
        "generator": "generator_v2", "reviewer": "reviewer_v1"}
    # The committed transition + kernel verdict land in the audit log.
    audit_types = [l["event_type"] for l in ImmutableAuditLog.read(tmp_path)]
    assert "epoch_transition" in audit_types


def test_crash_after_prepare_rerun_is_byte_identical_and_commits(tmp_path):
    store, state = _bootstrap(tmp_path)
    engine = _engine(store=store)
    t1 = _resolve_from_state(engine, tmp_path, state, _smoke_report())
    frozen = canonical_json(t1.to_dict())
    # Simulate the crash: prepare + per-change events, no commit.
    tx = store.begin_transaction(tmp_path, t1.epoch_transition_id)
    tx.__enter__()
    for ev in engine.decompose(t1):
        tx.add(ev)
    # ari resume: replay discards the uncommitted tail...
    state2 = store.load_state(tmp_path)
    assert state2.epoch.epoch_id == "epoch_000"
    assert state2.components.get("generator_v2").status == "shadow"
    # ...and the restored boundary re-runs resolve deterministically.
    t2 = _resolve_from_state(engine, tmp_path, state2, _smoke_report())
    assert canonical_json(t2.to_dict()) == frozen
    applied = engine.apply(t2, checkpoint_dir=tmp_path, state=state2,
                           cfg=ARIConfig(), node_count=10)
    assert applied.committed
    assert applied.state.components.get("generator_v2").status == \
        "probationary_active"


def test_double_apply_of_a_committed_transition_is_a_noop(tmp_path):
    store, state = _bootstrap(tmp_path)
    engine = _engine(store=store)
    t = _resolve_from_state(engine, tmp_path, state, _smoke_report())
    first = engine.apply(t, checkpoint_dir=tmp_path, state=state,
                         cfg=ARIConfig(), node_count=10)
    assert first.committed
    before = (tmp_path / RQGM_TRANSITIONS_FILENAME).read_bytes()
    again = engine.apply(t, checkpoint_dir=tmp_path, state=first.state,
                         cfg=ARIConfig(), node_count=10)
    assert again.noop and not again.committed
    assert (tmp_path / RQGM_TRANSITIONS_FILENAME).read_bytes() == before


def test_double_apply_with_stale_state_is_a_noop(tmp_path):
    # The §5.3 literal rule: a transition_id whose commit event already
    # exists in the log is a no-op EVEN when the caller re-presents the
    # stale pre-commit state (e.g. a buggy resume path).
    store, state = _bootstrap(tmp_path)
    engine = _engine(store=store)
    t = _resolve_from_state(engine, tmp_path, state, _smoke_report())
    first = engine.apply(t, checkpoint_dir=tmp_path, state=state,
                         cfg=ARIConfig(), node_count=10)
    assert first.committed
    before = (tmp_path / RQGM_TRANSITIONS_FILENAME).read_bytes()
    stale = engine.apply(t, checkpoint_dir=tmp_path, state=state,
                         cfg=ARIConfig(), node_count=10)
    assert stale.noop and not stale.committed
    assert (tmp_path / RQGM_TRANSITIONS_FILENAME).read_bytes() == before


def test_kernel_blocked_transition_aborts_without_registry_change(tmp_path):
    store, state = _bootstrap(tmp_path)
    engine = _engine(store=store, audit_log=ImmutableAuditLog(tmp_path))
    bad = EpochTransition(
        epoch_transition_id="transition_000_to_001",
        from_epoch="epoch_000", to_epoch="epoch_001",
    )
    bad.adoptions.append({
        "component_id": "generator_v2", "prompt_id": "generator_prompt_v2",
        "role": "generator", "from_status": "shadow", "to_status": "active",
        "rule_id": "T6", "evidence_refs": [],
    })  # forbidden instant activation: shadow -> active is not a table row
    statuses_before = {
        cid: e.status for cid, e in state.components.entries().items()
    }
    applied = engine.apply(bad, checkpoint_dir=tmp_path, state=state,
                           cfg=ARIConfig(), node_count=10)
    assert applied.aborted and not applied.committed
    assert bad.status == "aborted"
    assert applied.kernel_report.blocking
    # Fail-safe: the boundary still advanced with the incumbent set intact.
    assert applied.state.epoch.epoch_id == "epoch_001"
    statuses_after = {
        cid: e.status
        for cid, e in applied.state.components.entries().items()
    }
    assert statuses_after == statuses_before
    audit_types = [l["event_type"] for l in ImmutableAuditLog.read(tmp_path)]
    assert "kernel_report" in audit_types


# ── §9.6 emergency quarantine + fallback policy ─────────────────────────────


def test_emergency_quarantine_commits_mid_epoch_with_baseline_fallback(
        tmp_path):
    store, state = _bootstrap(tmp_path)
    engine = _engine(store=store, audit_log=ImmutableAuditLog(tmp_path))
    t = engine.emergency_quarantine(
        violation={"code": "CK-HSH-010", "subject_ref": "reviewer_v1"},
        component_id="reviewer_v1", epoch_state=state.epoch,
        components=state.components, prompts=state.prompts,
        checkpoint_dir=tmp_path,
    )
    assert t.status == "committed"
    assert t.emergency is True
    assert t.sanctions[0]["rule_id"] == "T16"
    # The only reviewer is gone: the committed baseline .md is the fallback.
    assert t.fallbacks == [{
        "role": "reviewer", "from_component_id": "reviewer_v1",
        "fallback_component_id": None, "baseline": True}]
    # Mid-epoch: the SAME epoch is still open; only the registry moved.
    after = store.load_state(tmp_path)
    assert after.epoch.epoch_id == "epoch_000"
    assert after.components.get("reviewer_v1").status == "quarantine"
    assert after.prompts.get("reviewer_prompt_v1").status == "quarantine"
    lines = [json.loads(ln) for ln in
             (tmp_path / RQGM_TRANSITIONS_FILENAME).read_text().splitlines()]
    assert lines[-1]["event_type"] == "emergency_quarantine"
    assert lines[-1]["payload"]["suspect_scope"] == {
        "epoch_id": "epoch_000", "component_id": "reviewer_v1"}


def test_emergency_fallback_prefers_the_prior_eligible_version(tmp_path):
    store, state = _bootstrap(tmp_path, extra_events=[
        TransitionEvent(event_type="component_registered", payload={
            "component_id": "reviewer_v0", "role": "reviewer",
            "tier": "institutional", "status": "probation",
            "epoch_id": "epoch_000"}),
    ])
    engine = _engine(store=store)
    t = engine.emergency_quarantine(
        violation={"code": "CK-AUD-003", "subject_ref": "reviewer_v1"},
        component_id="reviewer_v1", epoch_state=state.epoch,
        components=state.components, prompts=state.prompts,
        checkpoint_dir=tmp_path,
    )
    assert t.status == "committed"
    assert t.fallbacks == [{
        "role": "reviewer", "from_component_id": "reviewer_v1",
        "fallback_component_id": "reviewer_v0", "baseline": False}]
    # No role is ever left empty: the prior version keeps serving.
    assert t.next_active_components["reviewer"] == "reviewer_v0"


def test_store_refuses_any_other_mid_epoch_event_type(tmp_path):
    store = RqgmStateStore()
    with pytest.raises(ValueError):
        store.append_mid_epoch_event(tmp_path, TransitionEvent(
            event_type="component_status_change",
            payload={"component_id": "x", "to_status": "quarantine"}))


# ── §9.6.1 emergency quarantine mirrors the linked prompt (T16 == T11) ──────
#
# An emergency (T16) quarantine must remove the linked prompt from the serving
# set exactly as the normal boundary (T11) quarantine does, so an emergency-
# quarantined actor can never be bred back in as an evolution incumbent. Uses
# a real evolvable founding template key so the incumbent resolver runs for
# real (``evaluator/peer_review`` == reviewer_prompt_v1, evolvable=True).

_REVIEWER_KEY = "evaluator/peer_review"


def _bootstrap_with_serving_prompt(tmp_path):
    """Active reviewer component + its ACTIVE linked evolvable prompt, epoch
    open — the shape the incumbent generator would breed at the next
    boundary."""
    store = RqgmStateStore()
    events = [
        TransitionEvent(event_type="component_registered", payload={
            "component_id": "reviewer_v1", "role": "reviewer",
            "tier": "institutional", "status": "active",
            "prompt_id": "reviewer_prompt_v1", "epoch_id": "epoch_000"}),
        TransitionEvent(event_type="prompt_registered", payload={
            "prompt_id": "reviewer_prompt_v1", "role": "reviewer",
            "status": "active", "prompt_hash": _H,
            "prompt_sha256": _H + "0" * 52,
            "source": {"kind": "committed_template", "key": _REVIEWER_KEY},
            "epoch_id": "epoch_000"}),
    ]
    store.apply_transition(tmp_path, "bootstrap", events)
    state = store.open_epoch(tmp_path, ARIConfig(), node_count=0,
                             run_id="t09", prior=store.replay(tmp_path))
    return store, state


def _incumbent_roles(state, ckpt):
    """Roles the prompt-evolution incumbent generator would select."""
    from ari.rqgm.runtime import RQGMRuntime

    rt = RQGMRuntime.__new__(RQGMRuntime)
    return set(rt._active_evolvable_incumbents(state, ckpt, []))


def test_emergency_quarantine_mirrors_linked_prompt_to_quarantine(tmp_path):
    """(a) Both the component AND its linked prompt end quarantine, and the
    transition decomposes to a ``prompt_status_change`` at the T16 rule_id."""
    store, state = _bootstrap_with_serving_prompt(tmp_path)
    engine = _engine(store=store, audit_log=ImmutableAuditLog(tmp_path))
    t = engine.emergency_quarantine(
        violation={"code": "CK-HSH-010", "subject_ref": "reviewer_v1"},
        component_id="reviewer_v1", epoch_state=state.epoch,
        components=state.components, prompts=state.prompts,
        checkpoint_dir=tmp_path,
    )
    assert t.status == "committed"
    # The single sanction now postures the linked prompt too (from the
    # prompt's OWN status), staying one change (the emergency shape).
    sanction = t.sanctions[0]
    assert sanction["rule_id"] == "T16"
    assert sanction["prompt_from_status"] == "active"
    assert sanction["prompt_to_status"] == "quarantine"
    # It decomposes to BOTH a component and a prompt status change at T16.
    events = engine.decompose(t)
    prompt_events = [e for e in events
                     if e.event_type == "prompt_status_change"]
    assert len(prompt_events) == 1
    pe = prompt_events[0].payload
    assert pe["prompt_id"] == "reviewer_prompt_v1"
    assert pe["to_status"] == "quarantine"
    assert pe["rule_id"] == "T16"
    # After commit, the prompt registry entry itself is quarantine.
    after = store.load_state(tmp_path)
    assert after.components.get("reviewer_v1").status == "quarantine"
    assert after.prompts.get("reviewer_prompt_v1").status == "quarantine"


def test_emergency_quarantined_actor_is_not_an_evolution_incumbent(tmp_path):
    """(b) Regression guard for the bug's consequence: the quarantined actor's
    role/prompt must NOT be selected as an active evolution incumbent (else it
    is bred into successor candidates, contradicting quarantine's intent)."""
    store, state = _bootstrap_with_serving_prompt(tmp_path)
    # Before: the active reviewer prompt IS a live evolvable incumbent.
    assert _incumbent_roles(state, tmp_path) == {"reviewer"}

    engine = _engine(store=store)
    t = engine.emergency_quarantine(
        violation={"code": "CK-HSH-010", "subject_ref": "reviewer_v1"},
        component_id="reviewer_v1", epoch_state=state.epoch,
        components=state.components, prompts=state.prompts,
        checkpoint_dir=tmp_path,
    )
    assert t.status == "committed"
    # After: the quarantined role is gone from the incumbent set.
    after = store.load_state(tmp_path)
    assert after.prompts.get("reviewer_prompt_v1").status == "quarantine"
    assert _incumbent_roles(after, tmp_path) == set()


def test_emergency_quarantine_without_linked_prompt_emits_only_component(
        tmp_path):
    """(c) A component with no linked prompt quarantines the component only —
    no prompt posture, no crash."""
    store = RqgmStateStore()
    store.apply_transition(tmp_path, "bootstrap", [
        TransitionEvent(event_type="component_registered", payload={
            "component_id": "router_v1", "role": "router",
            "tier": "institutional", "status": "active",
            "prompt_id": None, "epoch_id": "epoch_000"}),
    ])
    state = store.open_epoch(tmp_path, ARIConfig(), node_count=0,
                             run_id="t09", prior=store.replay(tmp_path))
    engine = _engine(store=store)
    t = engine.emergency_quarantine(
        violation={"code": "CK-HSH-010", "subject_ref": "router_v1"},
        component_id="router_v1", epoch_state=state.epoch,
        components=state.components, prompts=state.prompts,
        checkpoint_dir=tmp_path,
    )
    assert t.status == "committed"
    sanction = t.sanctions[0]
    assert "prompt_to_status" not in sanction
    assert "prompt_from_status" not in sanction
    events = engine.decompose(t)
    assert [e.event_type for e in events] == ["component_status_change"]
    after = store.load_state(tmp_path)
    assert after.components.get("router_v1").status == "quarantine"


def test_emergency_shape_with_prompt_mirror_still_validates(tmp_path):
    """(d) The kernel still accepts the emergency transition (the mirrored
    prompt rides the single sanction, so it stays a one-change T16 shape);
    a non-emergency mid-epoch stamp of the same edge is still rejected."""
    store, state = _bootstrap_with_serving_prompt(tmp_path)
    engine = _engine(store=store)
    t = engine.emergency_quarantine(
        violation={"code": "CK-HSH-010", "subject_ref": "reviewer_v1"},
        component_id="reviewer_v1", epoch_state=state.epoch,
        components=state.components, prompts=state.prompts,
        checkpoint_dir=tmp_path,
    )
    report = ConstitutionalKernel().validate_transition(
        t.to_dict(), None, None, at_boundary=False)
    assert not report.blocking
    assert report.ok
    # The same active->quarantine edge stamped WITHOUT the emergency envelope
    # is still boundary-only and rejected mid-epoch (CK-REG-002).
    non_emergency = dict(t.to_dict(), emergency=False, kernel_violation=None)
    rep2 = ConstitutionalKernel().validate_transition(
        non_emergency, None, None, at_boundary=False)
    assert rep2.blocking
    assert "CK-REG-002" in [v.code for v in rep2.violations]


# ── §9.7 actor separation ───────────────────────────────────────────────────


def test_out_of_band_status_write_is_detected_by_epoch_invariance(tmp_path):
    store, state = _bootstrap(tmp_path)
    # A rogue writer bypasses the engine and appends a bare status change.
    store.append_events(tmp_path, [TransitionEvent(
        event_type="component_status_change",
        payload={"component_id": "reviewer_v1", "from_status": "active",
                 "to_status": "banned"})])
    lines = [json.loads(ln) for ln in
             (tmp_path / RQGM_TRANSITIONS_FILENAME).read_text().splitlines()]
    report = ConstitutionalKernel().validate_epoch_invariance(
        state.epoch, lines)
    assert report.blocking
    assert "CK-EPO-002" in [v.code for v in report.violations]


# ── §9.8 simple_bfts regression (no rqgm files, engine never imported) ──────


def _make_agent():
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
    return agent


def _make_strategy():
    from ari.orchestrator.node import Node

    bfts = MagicMock()
    bfts.should_prune.return_value = False
    counter = {"n": 0}

    def _expand(node, *args, **kwargs):
        counter["n"] += 1
        child = Node(id=f"child_{counter['n']}", parent_id=node.id,
                     depth=node.depth + 1)
        node.children.append(child.id)
        return [child]

    bfts.expand.side_effect = _expand
    bfts.select_best_to_expand.side_effect = lambda f, g, m: f[0]
    bfts.select_next_node.side_effect = lambda p, g, m: p[0]
    bfts.expansion_count.return_value = 0
    bfts.diversity_bonus.return_value = 0.0
    return bfts


def _run_short_loop(tmp_path, strategy, cfg):
    from ari.cli import _run_loop
    from ari.orchestrator.node import Node

    root = Node(id="node_root", parent_id=None, depth=0)
    return _run_loop(
        cfg, strategy, _make_agent(), [root], [root],
        {"goal": "g", "topic": "t", "file": "exp.md"},
        checkpoint_dir=tmp_path, run_id="t09-smoke",
    )


def test_simple_bfts_never_constructs_the_engine(monkeypatch, tmp_path):
    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    sys.modules.pop("ari.rqgm.transition_engine", None)
    cfg = ARIConfig(bfts={"max_total_nodes": 3, "max_parallel_nodes": 1,
                          "timeout_per_node": 60})
    _run_short_loop(tmp_path, _make_strategy(), cfg)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert not any(n.startswith("rqgm") for n in names), names
    assert "epoch_state.json" not in names
    assert "ari.rqgm.transition_engine" not in sys.modules


# ── §9.9 ari_rqgm smoke through the runtime boundary hook ───────────────────


def test_runtime_boundary_routes_through_the_engine(monkeypatch, tmp_path):
    from ari.rqgm.runtime import RQGMRuntime

    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    cfg = ARIConfig(ari={"mode": "ari_rqgm"},
                    rqgm={"enabled": True, "epoch": {"nodes_per_epoch": 2}})
    runtime = RQGMRuntime(cfg, checkpoint_dir=tmp_path)
    ep0 = runtime.ensure_epoch(1, checkpoint_dir=tmp_path, run_id="r")
    assert ep0.epoch_seq == 0
    ep1 = runtime.ensure_epoch(3, checkpoint_dir=tmp_path, run_id="r")
    assert ep1.epoch_seq == 1
    # The boundary rode the engine: an epoch_transition record was audited
    # and the transitions log carries the prepare/commit bracket.
    audit = ImmutableAuditLog.read(tmp_path)
    transitions = [l for l in audit
                   if l.get("event_type") == "epoch_transition"]
    assert transitions
    payload = transitions[-1]["payload"]
    assert payload["produced_by"] == REGISTRY_WRITER
    assert payload["status"] == "committed"
    assert payload["from_epoch"] == "epoch_000"
    assert payload["to_epoch"] == "epoch_001"
    # And it validates against the committed schema.
    jsonschema = pytest.importorskip("jsonschema")
    from ari import schemas

    jsonschema.validate(payload, schemas.load("epoch_transition.schema"))


def test_committed_transition_validates_against_the_schema(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    from ari import schemas

    store, state = _bootstrap(tmp_path)
    engine = _engine(store=store)
    t = _resolve_from_state(engine, tmp_path, state, _smoke_report())
    engine.apply(t, checkpoint_dir=tmp_path, state=state, cfg=ARIConfig(),
                 node_count=10)
    jsonschema.validate(t.to_dict(), schemas.load("epoch_transition.schema"))
    # A T17 transition (retirement + clean-room request) also validates.
    comps, prompts = _registries(
        [_comp("r_v1", "reviewer", "quarantine",
               prompt_id="rev_prompt_v1")],
        [_prompt("rev_prompt_v1", "reviewer", "quarantine")],
    )
    t17 = _resolve(_engine(), comps, prompts,
                   _report([_rec("retire", "r_v1")], replay_cases_used=8))
    jsonschema.validate(t17.to_dict(),
                        schemas.load("epoch_transition.schema"))


# ── §9.10 META_FILES hygiene ────────────────────────────────────────────────


def test_engine_writes_only_task02_registered_filenames():
    from ari import paths
    from ari.rqgm.store import (
        EPOCH_STATE_FILENAME,
        RQGM_AUDIT_FILENAME,
        RQGM_REGISTRY_FILENAME,
    )

    registered = set(paths.PathManager.META_FILES) | set(paths._TRACE_FILES)
    for name in (RQGM_TRANSITIONS_FILENAME, RQGM_AUDIT_FILENAME,
                 EPOCH_STATE_FILENAME, RQGM_REGISTRY_FILENAME):
        assert name in registered, name


# ── §9.11 parity + import guards (no VirSci, no LLM) ────────────────────────


def test_known_actions_parity_with_task05_vocabulary():
    from ari.rqgm.governance._records import RECOMMENDATION_ACTIONS

    assert KNOWN_ACTIONS == RECOMMENDATION_ACTIONS


def test_transition_config_defaults_match_defaults_yaml():
    yaml = pytest.importorskip("yaml")
    root = Path(__file__).resolve().parents[1] / "ari" / "configs"
    doc = yaml.safe_load((root / "defaults.yaml").read_text())
    block = doc["rqgm"]["transition"]
    model = RQGMTransitionConfig()
    assert set(block) == set(model.model_dump())
    for key, value in block.items():
        assert getattr(model, key) == value, key


def test_engine_module_has_no_llm_network_or_virsci_imports():
    import ari.rqgm as rqgm_pkg

    pkg_dir = Path(rqgm_pkg.__file__).parent
    text = (pkg_dir / "transition_engine.py").read_text(encoding="utf-8")
    for name in ("litellm", "openai", "anthropic", "requests", "httpx",
                 "aiohttp", "socket", "virsci"):
        assert f"import {name}" not in text, name
        assert f"from {name}" not in text, name
    # No VirSci coupling at all: the adapter is one more governed component.
    import_lines = [ln for ln in text.splitlines()
                    if ln.strip().startswith(("import ", "from "))]
    assert not any("virsci" in ln.lower() for ln in import_lines)


def test_status_history_fold_is_deterministic_and_crash_filtered():
    events = [
        TransitionEvent(event_type="prompt_registered", payload={
            "prompt_id": "p1", "status": "candidate",
            "epoch_id": "epoch_001"}),
        TransitionEvent(event_type="prompt_status_change", payload={
            "prompt_id": "p1", "to_status": "validated", "rule_id": "T1",
            "transition_id": "transition_001_to_002"}),
        TransitionEvent(event_type="prompt_status_change", payload={
            "prompt_id": "p1", "to_status": "shadow", "rule_id": "T3",
            "transition_id": "transition_002_to_003"}),
    ]
    hist = build_status_history(events)
    assert hist["p1"] == {"status": "shadow", "since_seq": 3,
                          "rule_counts": {"T1": 1, "T3": 1}}
    assert build_status_history(events) == hist


# ── the no_replay_basis waiver (Cluster C: plan 14 §5.5/§7, paper/03 §5.9,
#    paper/04 §5.1/§5.9, paper/05 §5.5) ────────────────────────────────────

def test_waiver_carries_a_declared_no_basis_role_through_T3_and_T6():
    """The waiver's REASON to exist: without it, deleting the fabricated
    counts strands every candidate at `validated` -> T4 -> T5 and the Red
    Queen dies silently. An honest all-absent board must traverse the spine."""
    from ari.rqgm.transition_engine import (
        NO_REPLAY_BASIS_KEY,
        NO_SHADOW_BASIS_KEY,
    )

    honest = {"verdict": "pass", "replay_score": None, "anchor_score": None,
              "case_refs": [], "case_count": 0,
              "shadow_samples": 0, "shadow_score": None,
              NO_REPLAY_BASIS_KEY: True, NO_SHADOW_BASIS_KEY: True}
    for status, rule in (("validated", "T3"), ("shadow", "T6")):
        comps, prompts = _registries(
            prompts=[_prompt("pw", "paper_writer", status)])
        evals = [{"prompt_id": "pw", "role": "paper_writer", **honest}]
        t = _resolve(_engine(), comps, prompts, _report(), evaluations=evals)
        assert _rules_of(t) == [rule], (status, _rules_of(t), t.notes)
        # The waiver is visible in the audit, naming the role and the gate.
        assert any("WAIVED" in n and "paper_writer" in n and rule in n
                   for n in t.notes), t.notes
    # And the honest evidence ref cites the evaluation, never invented cases.
    comps, prompts = _registries(
        prompts=[_prompt("pw", "paper_writer", "validated")])
    t = _resolve(_engine(), comps, prompts, _report(),
                 evaluations=[{"prompt_id": "pw", "role": "paper_writer",
                               **honest}])
    assert t.adoptions[0]["evidence_refs"] == ["candidate_evaluation:pw"]


def test_waiver_is_role_scoped_and_needs_the_declaration():
    """Two independent halves, both required. A behavioural role cannot buy
    the waiver by setting the sentinel (exploration byte-identity: Task 09's
    live-shadow board is untouched), and an exempt role gets nothing unless
    its evaluation actually DECLARES the absence."""
    from ari.rqgm.transition_engine import (
        NO_REPLAY_BASIS_KEY,
        NO_REPLAY_BASIS_ROLES,
        NO_SHADOW_BASIS_KEY,
    )

    assert "generator" not in NO_REPLAY_BASIS_ROLES
    absent = {"verdict": "pass", "replay_score": None, "anchor_score": None,
              "case_refs": [], "shadow_samples": 0, "shadow_score": None}

    # (a) a behavioural role DECLARING the sentinel is still floored.
    comps, prompts = _registries(
        prompts=[_prompt("gen", "generator", "validated")])
    t = _resolve(_engine(), comps, prompts, _report(),
                 evaluations=[{"prompt_id": "gen", "role": "generator",
                               **absent, NO_REPLAY_BASIS_KEY: True,
                               NO_SHADOW_BASIS_KEY: True}])
    assert t.is_empty(), "a global relaxation would break Task 09's board"

    # (b) an exempt role WITHOUT the declaration is still floored.
    comps2, prompts2 = _registries(
        prompts=[_prompt("pw", "paper_writer", "validated")])
    t2 = _resolve(_engine(), comps2, prompts2, _report(),
                  evaluations=[{"prompt_id": "pw", "role": "paper_writer",
                                **absent}])
    assert t2.is_empty()


def test_the_waiver_excuses_counts_never_a_score():
    """The waiver must not become a free pass: a candidate that REPORTS a
    board still fails on its merits at both gates."""
    from ari.rqgm.transition_engine import (
        NO_REPLAY_BASIS_KEY,
        NO_SHADOW_BASIS_KEY,
    )

    # T3: a reported replay board below threshold fails, waiver or not.
    comps, prompts = _registries(
        prompts=[_prompt("pr", "paper_reviewer", "validated")])
    t = _resolve(_engine(), comps, prompts, _report(), evaluations=[{
        "prompt_id": "pr", "role": "paper_reviewer", "verdict": "pass",
        "replay_score": 0.1, "anchor_score": 0.95, "case_refs": ["c1"],
        "shadow_samples": 0, "shadow_score": None, NO_REPLAY_BASIS_KEY: True}])
    assert t.is_empty(), t.notes
    # ...and a reported ANCHOR board below threshold fails too.
    t2 = _resolve(_engine(), comps, prompts, _report(), evaluations=[{
        "prompt_id": "pr", "role": "paper_reviewer", "verdict": "pass",
        "replay_score": 0.95, "anchor_score": 0.1, "case_refs": ["c1"],
        "shadow_samples": 0, "shadow_score": None, NO_REPLAY_BASIS_KEY: True}])
    assert t2.is_empty(), t2.notes
    # T5: a reported shadow board below threshold still retires under the
    # waiver (the waiver covers the sample COUNT, not the quality).
    comps3, prompts3 = _registries(
        prompts=[_prompt("pr", "paper_reviewer", "shadow")])
    t3 = _resolve(_engine(), comps3, prompts3, _report(), evaluations=[{
        "prompt_id": "pr", "role": "paper_reviewer", "verdict": "pass",
        "shadow_samples": 0, "shadow_score": 0.2, NO_SHADOW_BASIS_KEY: True}])
    assert _rules_of(t3) == ["T5"]


def test_a_paper_board_that_HAS_cases_is_counted_never_waived():
    """The replay COUNT floor is waived only for an honestly ABSENT board.

    `paper_reviewer`'s `case_refs` are the pool's REAL case_ids, so a board that
    HAS cases has something honest to count and `replay_min_cases` counts it.
    Declaring `no_replay_basis` unconditionally (as the paper evaluator did) let
    a genuine 1-case board clear the 4-case floor — a permanent, silent disabling
    of `replay_min_cases` for the role, sanctioned by no plan."""
    from ari.rqgm.transition_engine import (
        NO_REPLAY_BASIS_KEY,
        NO_SHADOW_BASIS_KEY,
    )

    comps, prompts = _registries(
        prompts=[_prompt("pr", "paper_reviewer", "validated")])
    real_1_case = {
        "prompt_id": "pr", "role": "paper_reviewer", "verdict": "pass",
        # a genuine board: high score, but ONE case against a floor of 4
        "replay_score": 0.95, "anchor_score": 0.95, "case_refs": ["c1"],
        "shadow_samples": 0, "shadow_score": None, NO_SHADOW_BASIS_KEY: True,
    }
    t = _resolve(_engine(), comps, prompts, _report(),
                 evaluations=[dict(real_1_case)])
    assert t.is_empty(), (
        "a real 1-case board must be held to replay_min_cases", t.notes)
    assert any("T3 replay/anchor guard failed" in n for n in t.notes), t.notes

    # The SAME candidate with a board that clears the floor is adopted — the
    # floor gates on the count, and the count is real.
    t2 = _resolve(_engine(), *_registries(
        prompts=[_prompt("pr", "paper_reviewer", "validated")]), _report(),
        evaluations=[dict(real_1_case, case_refs=["c1", "c2", "c3", "c4"])])
    assert _rules_of(t2) == ["T3"], t2.notes

    # ...and the genuine on-ramp (NO board at all) still passes on the waiver,
    # which is the only thing §5.5 sanctions.
    t3 = _resolve(_engine(), *_registries(
        prompts=[_prompt("pr", "paper_reviewer", "validated")]), _report(),
        evaluations=[{
            "prompt_id": "pr", "role": "paper_reviewer", "verdict": "pass",
            "replay_score": None, "anchor_score": None, "case_refs": [],
            "shadow_samples": 0, "shadow_score": None,
            NO_REPLAY_BASIS_KEY: True, NO_SHADOW_BASIS_KEY: True}])
    assert _rules_of(t3) == ["T3"], t3.notes


def test_the_two_count_floors_are_declared_independently():
    """T3's and T6's floors have different conditions for a paper role, so one
    boolean cannot speak for both. A candidate with a REAL replay board that
    clears the floor must still reach T6 — its shadow stage is vacuous BY
    CONSTRUCTION (no paper role is ever shadow-executed), so without the
    separate T6 declaration it would be retired at T4/T5 for lacking samples no
    paper path can produce, while a candidate with NO board sailed through."""
    from ari.rqgm.transition_engine import (
        NO_REPLAY_BASIS_KEY,
        NO_SHADOW_BASIS_KEY,
    )

    comps, prompts = _registries(
        prompts=[_prompt("pr", "paper_reviewer", "shadow")])
    # T6 with only the REPLAY declaration => no shadow waiver => not adopted.
    t = _resolve(_engine(), comps, prompts, _report(), evaluations=[{
        "prompt_id": "pr", "role": "paper_reviewer", "verdict": "pass",
        "shadow_samples": 0, "shadow_score": None, NO_REPLAY_BASIS_KEY: True}])
    assert not _rules_of(t), t.notes
    # T6 with the SHADOW declaration => the vacuous stage is waived.
    comps2, prompts2 = _registries(
        prompts=[_prompt("pr", "paper_reviewer", "shadow")])
    t2 = _resolve(_engine(), comps2, prompts2, _report(), evaluations=[{
        "prompt_id": "pr", "role": "paper_reviewer", "verdict": "pass",
        "shadow_samples": 0, "shadow_score": None, NO_SHADOW_BASIS_KEY: True}])
    assert _rules_of(t2) == ["T6"], t2.notes
    assert any("shadow_min_samples" in n and "WAIVED" in n for n in t2.notes)


def test_waiver_never_rescues_a_failed_verdict_or_bypasses_the_role_opening():
    """The two gates the waiver deliberately does NOT touch."""
    from ari.rqgm.transition_engine import (
        NO_REPLAY_BASIS_KEY,
        NO_SHADOW_BASIS_KEY,
    )

    ev = {"verdict": "fail", "replay_score": None, "case_refs": [],
          "shadow_samples": 0, "shadow_score": None,
          NO_REPLAY_BASIS_KEY: True, NO_SHADOW_BASIS_KEY: True}
    comps, prompts = _registries(
        prompts=[_prompt("pw", "paper_writer", "validated")])
    t = _resolve(_engine(), comps, prompts, _report(),
                 evaluations=[{"prompt_id": "pw", "role": "paper_writer",
                               **ev}])
    assert t.is_empty(), "a failed verdict must never reach T3"

    # T6 still requires a real role opening — adoption stays sanction-driven.
    comps2, _ = _registries([_comp("paper_writer_v1", "paper_writer", "active")])
    _, prompts2 = _registries(
        prompts=[_prompt("pw", "paper_writer", "shadow")])
    t2 = _resolve(_engine(), comps2, prompts2, _report(), evaluations=[{
        "prompt_id": "pw", "role": "paper_writer", "verdict": "pass",
        "shadow_samples": 0, "shadow_score": None, NO_SHADOW_BASIS_KEY: True}])
    assert t2.is_empty()
    assert any("no role opening" in n for n in t2.notes), t2.notes


# ── #79: CK-REG-101 authority-non-expansion wired to the live path ───────────


def _cap_comp(cid, role, status, capabilities):
    return ComponentEntry(
        component_id=cid, role=role, tier="meta", status=status,
        capabilities=dict(capabilities),
    )


def _cap_state(*comps):
    comp_reg, prompt_reg = _registries(comps=list(comps))
    return RqgmRuntimeState(
        epoch=_epoch(1), components=comp_reg, prompts=prompt_reg,
    )


def test_attach_incumbent_capabilities_resolves_active_incumbent():
    # #79: the RTE attaches the active incumbent of the adoption's role so the
    # stateless kernel can compare CK-REG-101 against it (not a None baseline).
    incumbent = _cap_comp(
        "reviewer_v1", "reviewer", "active",
        {"allowed_targets": ["a"], "forbidden_targets": ["x"]},
    )
    state = _cap_state(incumbent)
    transition = EpochTransition(
        epoch_transition_id="t1", from_epoch="epoch_001", to_epoch="epoch_002",
        adoptions=[{
            "component_id": "reviewer_v2", "role": "reviewer",
            "from_status": "shadow", "to_status": "probationary_active",
            "rule_id": "T6",
            "capabilities": {"allowed_targets": ["a"],
                             "forbidden_targets": ["x"]},
        }],
    )
    _engine()._attach_incumbent_capabilities(transition, state)
    attached = transition.adoptions[0].get("_incumbent_entry")
    assert isinstance(attached, dict)
    assert attached["component_id"] == "reviewer_v1"
    assert attached["capabilities"]["forbidden_targets"] == ["x"]


def test_attach_incumbent_skips_non_capability_and_self_adoption():
    incumbent = _cap_comp("reviewer_v1", "reviewer", "active",
                          {"allowed_targets": ["a"]})
    state = _cap_state(incumbent)
    # (a) an adoption with NO capability fields gets no incumbent attached.
    t = EpochTransition(
        epoch_transition_id="t1", from_epoch="epoch_001", to_epoch="epoch_002",
        adoptions=[{"component_id": "generator_v2", "role": "generator",
                    "from_status": "shadow",
                    "to_status": "probationary_active", "rule_id": "T6"}],
    )
    _engine()._attach_incumbent_capabilities(t, state)
    assert "_incumbent_entry" not in t.adoptions[0]
    # (b) self-adoption (the candidate IS the active incumbent) gets none.
    t2 = EpochTransition(
        epoch_transition_id="t2", from_epoch="epoch_001", to_epoch="epoch_002",
        adoptions=[{"component_id": "reviewer_v1", "role": "reviewer",
                    "from_status": "probationary_active",
                    "to_status": "active", "rule_id": "T8",
                    "capabilities": {"allowed_targets": ["a"]}}],
    )
    _engine()._attach_incumbent_capabilities(t2, state)
    assert "_incumbent_entry" not in t2.adoptions[0]


def test_ck_reg_101_gate_uses_attached_incumbent():
    # #79: with the incumbent attached, a PRESERVING candidate passes and a
    # WIDENING candidate is blocked — the gate compares against the incumbent,
    # not the conservative None deny-all baseline.
    kernel = ConstitutionalKernel()
    incumbent_entry = {
        "component_id": "reviewer_v1", "role": "reviewer", "tier": "meta",
        "status": "active",
        "capabilities": {"allowed_targets": ["a"], "forbidden_targets": ["x"]},
    }

    def _t(caps):
        return EpochTransition(
            epoch_transition_id="t", from_epoch="epoch_001",
            to_epoch="epoch_002",
            adoptions=[{
                "component_id": "reviewer_v2", "role": "reviewer",
                "from_status": "shadow", "to_status": "probationary_active",
                "rule_id": "T6", "capabilities": dict(caps),
                "_incumbent_entry": dict(incumbent_entry),
            }],
        ).to_dict()

    ok = kernel.validate_transition(
        _t({"allowed_targets": ["a"], "forbidden_targets": ["x"]}), None, None,
    )
    assert not any(v.code == "CK-REG-101" for v in ok.violations)
    widened = kernel.validate_transition(
        _t({"allowed_targets": ["a", "b"], "forbidden_targets": ["x"]}),
        None, None,
    )
    assert any(v.code == "CK-REG-101" for v in widened.violations)
    # Sanity: WITHOUT the incumbent the same preserving candidate is
    # deny-all-blocked — proving the attach is what makes it pass.
    no_inc = EpochTransition(
        epoch_transition_id="t", from_epoch="epoch_001", to_epoch="epoch_002",
        adoptions=[{
            "component_id": "reviewer_v2", "role": "reviewer",
            "from_status": "shadow", "to_status": "probationary_active",
            "rule_id": "T6",
            "capabilities": {"allowed_targets": ["a"],
                             "forbidden_targets": ["x"]},
        }],
    ).to_dict()
    assert any(
        v.code == "CK-REG-101"
        for v in kernel.validate_transition(no_inc, None, None).violations
    )
