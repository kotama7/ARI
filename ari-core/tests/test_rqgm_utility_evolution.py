"""RQGM Task 14 — governed utility evolution
(docs/concepts/rqgm_architecture.md "Governed utility evolution";
docs/reference/rqgm_schemas.md "Governed utility-evolution schema (Task 14)").

The defining claim of Constitutional ARI-RQGM is that the search is
tree-structured **and that at each epoch boundary the entire score — the
utility function itself — is rewritten**. The CONSEQUENCE half was always
live (``frontier_repair`` can destroy every score a retired utility policy
produced); the CAUSE half did not exist. These tests pin the cause:

* the role limbo, closed (``utility_policy`` / ``policy_mutator`` were named
  by live code while being in NEITHER half of ``events.ROLES``);
* the capability matrix parity that stops a new role being CK-ACC-001-blocked
  in every tier (the ``failure_summary_compressor`` drift);
* ``capture_utility_policy``'s precedence — the ONE function whose static-cfg
  read made ``utility_policy_hash`` a permanent constant;
* the identity bridge (one value, three names: policy body hash ==
  ``prompt_hash`` == ``utility_policy_hash``);
* ``PolicyMutator``'s contract (candidates only, deterministic, no scores in,
  no raw attack text out);
* ``validate_utility_policy`` — one case per CK-UTL code lives in
  ``test_rqgm_kernel.py``'s ``_FIXTURES`` (structurally enforced there:
  ``set(_FIXTURES) == set(SEVERITY)``); this file pins the semantics that
  matter most.

No test calls a real LLM: the four default mutation kinds are pure
arithmetic (P2).
"""

from __future__ import annotations

import json

import pytest
import yaml

from ari.config import ARIConfig
from ari.rqgm import events, kernel_rules, meta_rules
from ari.rqgm.events import canonical_json, hash12
from ari.rqgm.kernel import ConstitutionalKernel
from ari.rqgm.prompt_loader import (
    PromptImmutabilityError,
    active_prompt_view,
    evolved_policy_path,
    write_evolved_policy_body,
)
from ari.rqgm.prompt_spec import (
    TEMPLATE_REF_KINDS,
    UTILITY_POLICY_PROMPT_ID,
    build_founding_specs,
    founding_registration_events,
    founding_utility_policy_spec,
    utility_policy_spec,
)
from ari.rqgm.registry import (
    GovernedPromptEntry,
    GovernedPromptRegistry,
    apply_registry_event,
)
from ari.rqgm.state import (
    capture_utility_policy,
    seal_utility_policy,
    utility_policy_body,
)
from ari.rqgm.store import RqgmRuntimeState
from ari.rqgm.utility_evolution import (
    KNOB_MUTATION_KINDS,
    MUTATION_KINDS,
    UTILITY_POLICY_HASH_KEY,
    PolicyMutator,
    UtilityPolicyCandidate,
    UtilityPolicyStamp,
    propose_utility_policy,
    utility_policy_candidate_from_dict,
)


def _cfg(**rqgm) -> ARIConfig:
    return ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": True, **rqgm})


def _evidence(*axes) -> list[dict]:
    """Abstract evidence (Task 06 ``abstract_view`` shape) — never raw text."""
    return [
        {"record_id": f"fs_{i:06d}", "failure_mode": "unsupported_claim",
         "affected_axes": [axis]}
        for i, axis in enumerate(axes)
    ]


#: The canonical five axes at explicit equal weights.
#:
#: NOTE ``ARIConfig().evaluator.axis_weights`` defaults to ``{}`` ("empty =>
#: equal weights, handled by the formula"), so a DEFAULT-cfg policy body
#: carries no axis keys and ``axis_reweighting`` has nothing to reweight —
#: it returns None and the boundary falls through to the next configured
#: kind (``composite_swap``), which is why a default run still rewrites.
#: Materialising the five axes into the default body would change the
#: epoch-0 policy hash, and the ``b192196ced57`` pin must stay green
#: (plan 14 §8.3), so the empty default is deliberately preserved.
_EQUAL_WEIGHTS = {
    "clarity_of_contribution": 0.2, "comparative_rigor": 0.2,
    "measurement_validity": 0.2, "novelty": 0.2, "reproducibility": 0.2,
}


def _body(**over) -> dict:
    """A policy body with explicit axis weights (see _EQUAL_WEIGHTS)."""
    out = utility_policy_body(
        ARIConfig(evaluator={"axis_weights": dict(_EQUAL_WEIGHTS)})
    )
    out.update(over)
    return out


# ── the role limbo, closed (§5.2 / §11.1) ───────────────────────────────────


def test_the_role_limbo_is_closed():
    """THE DIAGNOSIS, EXECUTABLE (plan 14 §9): every role named by live code
    must be a member of the role vocabulary.

    This test FAILS on pre-Task-14 code. ``frontier_repair.INVALIDATE_ROLES``
    declared ``utility_policy`` unlaunderable, ``records.UtilityRecord``
    stamped ``role="utility_policy"``, and the epoch fingerprint hashed a
    ``utility_policy`` — while the role was in neither ``EVOLVABLE_ROLES``
    nor ``FIXED_ROLES``, so no registry entry could ever represent it and the
    retirement frontier_repair waits for could never fire.
    """
    from ari.rqgm import frontier_repair
    from ari.rqgm.adversarial import records

    named = (
        set(frontier_repair.INVALIDATE_ROLES)
        | set(frontier_repair.RECOMPUTE_ROLES)
        | {records.UTILITY_POLICY_ROLE}
        | set(frontier_repair._ROLE_STALE_REASONS)
    )
    missing = sorted(named - set(events.ROLES))
    assert not missing, f"roles named by live code but absent from ROLES: {missing}"


def test_roles_partition_cleanly():
    # #78b: ROLES is now a THREE-way partition — evolvable, governance-actor,
    # fixed — the governance actors being neither prompt-evolvable nor
    # constitutionally immutable (they are impeachable institutional actors).
    assert events.ROLES == (
        events.EVOLVABLE_ROLES
        + events.GOVERNANCE_ACTOR_ROLES
        + events.FIXED_ROLES
    )
    assert len(set(events.ROLES)) == len(events.ROLES), "duplicate role"
    assert not set(events.EVOLVABLE_ROLES) & set(events.FIXED_ROLES)
    assert not set(events.EVOLVABLE_ROLES) & set(events.GOVERNANCE_ACTOR_ROLES)
    assert not set(events.GOVERNANCE_ACTOR_ROLES) & set(events.FIXED_ROLES)
    assert "utility_policy" in events.EVOLVABLE_ROLES
    assert "policy_mutator" in events.EVOLVABLE_ROLES
    assert set(events.GOVERNANCE_ACTOR_ROLES) == {
        "auditor", "evidence_clerk", "governance_judge",
    }


def test_utility_policy_is_evolvable_not_fixed():
    """The score is EVOLVABLE, not FIXED. The fixed layer is "kernel / fixed
    verifier / audit log never evolve"; a score that never changes is
    precisely what P1 forbids. FIXED_ROLES was the other way out of the
    limbo and is rejected explicitly (plan 14 §5.2)."""
    assert "utility_policy" not in events.FIXED_ROLES
    assert set(events.FIXED_ROLES) == {
        "constitutional_kernel",
        "knowledge_binder",
        "capability_binder",
        "harness_resolver",
        "fixed_verifier",
        "audit_log",
    }


def test_policy_mutator_moved_from_frozen_to_evolving_meta():
    """meta_rules' own comment prescribed this exit: the frozen names "are
    not in the Task 02 role vocabulary yet, so they cannot be registered — a
    later task extends ari.rqgm.events.ROLES when they gain implementations".
    Task 14 is that later task."""
    assert "policy_mutator" in meta_rules.META_EVOLVING_ROLES
    assert "policy_mutator" not in meta_rules.META_FROZEN_ROLES
    assert "policy_mutator" in meta_rules.META_ROLES
    # The still-frozen names keep their reservation.
    assert set(meta_rules.META_FROZEN_ROLES) == {
        "candidate_selector", "anchor_case_selector", "prompt_distiller"
    }


def test_meta_hard_denied_flags_make_registry_writes_a_schema_violation():
    """P3/R4: the proposer may only EMIT candidates. At tier meta the
    alternative is a schema violation, not a mere capability denial."""
    for flag in ("can_modify_registry", "can_activate_candidates"):
        assert flag in meta_rules.META_HARD_DENIED_FLAGS


# ── capability parity (§5.2 / §9) ───────────────────────────────────────────


def test_every_evolvable_role_has_at_least_one_capability_row():
    """The ``failure_summary_compressor`` regression: a role in
    EVOLVABLE_ROLES with NO matrix row is CK-ACC-001-blocked in every tier,
    silently."""
    matrix_roles = {role for role, _tier in kernel_rules.CAPABILITY_MATRIX}
    assert not set(events.EVOLVABLE_ROLES) - matrix_roles


def test_utility_policy_capability_row_is_a_document_not_an_actor():
    caps = kernel_rules.CAPABILITY_MATRIX[("utility_policy", "institutional")]
    assert caps == frozenset({("read", "records"), ("append", "records")})
    # No invoke, no write, no activate: a policy that could invoke or write
    # the registry is not a policy (plan 14 §5.6).
    assert not {a for a, _r in caps} & {"invoke", "write", "activate"}
    # Strictly narrower than _INSTITUTIONAL_BASE (no active_prompt_text, no
    # checkpoint_artifacts).
    assert caps < kernel_rules.CAPABILITY_MATRIX[("judge", "institutional")]


def test_policy_mutator_caps_mirror_prompt_mutator_exactly():
    """No authority the other meta agents lack, no immunity they lack (P3)."""
    for tier in ("institutional", "meta"):
        assert (
            kernel_rules.CAPABILITY_MATRIX[("policy_mutator", tier)]
            == kernel_rules.CAPABILITY_MATRIX[("prompt_mutator", tier)]
        )


def test_constitution_hash_covers_utility_policy_rules(monkeypatch):
    """UTILITY_POLICY_RULES is frozen code INSIDE the pin: a tunable weight
    bound would be a tunable constitution (plan 14 §5.6)."""
    original = kernel_rules.constitution_hash()
    patched = dict(kernel_rules.UTILITY_POLICY_RULES)
    patched["axis_weight_min"] = 0.0  # would permit axis abolition
    monkeypatch.setattr(kernel_rules, "UTILITY_POLICY_RULES", patched)
    assert kernel_rules.constitution_hash() != original
    monkeypatch.undo()
    assert kernel_rules.constitution_hash() == original


def test_constitution_hash_matches_the_module_constant():
    from tests.test_rqgm_kernel import _EXPECTED_CONSTITUTION_HASH

    assert kernel_rules.CONSTITUTION_HASH == kernel_rules.constitution_hash()
    assert kernel_rules.CONSTITUTION_HASH == _EXPECTED_CONSTITUTION_HASH


# ── capture_utility_policy precedence (§5.7 — THE CORE CHANGE) ──────────────


def test_registries_none_is_byte_identical_to_today():
    """Branch 1 (simple_bfts / stub / pre-RQGM): the cfg branch, verbatim.

    Pinned against test_rqgm_epoch_state.py's frozen fixture cfg and its
    ``b192196ced57`` golden — the epoch-0 pin the plan requires to stay green
    BECAUSE the fallback is byte-identical to the pre-Task-14 function
    (plan 14 §8.3).
    """
    from types import SimpleNamespace

    fixed = SimpleNamespace(
        evaluator=SimpleNamespace(
            composite="harmonic_mean", axis_weights={"novelty": 1.0}
        ),
        bfts=SimpleNamespace(
            frontier_score="scientific_plus_diversity",
            depth_penalty_lambda=0.05, ucb_c=0.5,
        ),
    )
    policy = capture_utility_policy(fixed)
    assert policy == capture_utility_policy(fixed, registries=None)
    assert policy["utility_policy_hash"] == "b192196ced57"
    assert set(policy) == {
        "composite", "axis_weights", "frontier_score",
        "depth_penalty_lambda", "ucb_c", "utility_policy_hash",
    }
    # Total over pre-RQGM cfg objects and stub configs (duck-typed getattr).
    assert capture_utility_policy(SimpleNamespace())["composite"] == (
        "harmonic_mean"
    )
    assert capture_utility_policy(
        SimpleNamespace(), registries=None
    )["composite"] == "harmonic_mean"


def test_registry_without_a_utility_policy_entry_falls_back_to_cfg():
    """Branch 2: epoch 0 before founding registration; a resumed pre-14
    checkpoint. The run continues with a constant policy, exactly as it was
    launched (plan 14 §8.5)."""
    cfg = ARIConfig()
    state = RqgmRuntimeState()
    assert capture_utility_policy(cfg, registries=state) == (
        capture_utility_policy(cfg)
    )


def _adopted_state(tmp_path, body: dict, *, status="active") -> RqgmRuntimeState:
    spec = utility_policy_spec(body, prompt_id="utility_policy_prompt_v2")
    write_evolved_policy_body(tmp_path, spec.prompt_id, canonical_json(body))
    comps, prompts = {}, {}
    apply_registry_event(
        comps, prompts, "prompt_registered",
        {
            "prompt_id": spec.prompt_id, "role": "utility_policy",
            "status": status, "prompt_hash": spec.prompt_hash,
            "prompt_sha256": spec.full_sha256,
            "source": {"kind": "policy",
                       "path": spec.template_ref["path"]},
        },
    )
    return RqgmRuntimeState(prompts=GovernedPromptRegistry(prompts))


def test_adopted_policy_wins_over_cfg(tmp_path):
    """Branch 3 — the whole point of Task 14: the frozen policy is the
    ADOPTED one, so utility_policy_hash stops being a constant."""
    body = {
        "composite": "weighted_min",
        "axis_weights": {"novelty": 0.5, "reproducibility": 0.5},
        "frontier_score": "ucb_like",
        "depth_penalty_lambda": 0.1,
        "ucb_c": 1.5,
    }
    state = _adopted_state(tmp_path, body)
    frozen = capture_utility_policy(
        ARIConfig(), registries=state, checkpoint_dir=tmp_path
    )
    assert frozen["composite"] == "weighted_min"
    assert frozen["frontier_score"] == "ucb_like"
    assert frozen["axis_weights"] == {"novelty": 0.5, "reproducibility": 0.5}
    # The adopted hash IS the registered prompt_hash (the identity bridge).
    assert frozen["utility_policy_hash"] == (
        state.prompts.active_prompt_hashes()["utility_policy"]
    )
    # ... and it is NOT the cfg policy's hash: the score was rewritten.
    assert frozen["utility_policy_hash"] != (
        capture_utility_policy(ARIConfig())["utility_policy_hash"]
    )


def test_probationary_active_policy_is_also_adopted(tmp_path):
    """ACTIVE_STATUSES is what places an entry in the frozen active set, and
    a probationary_active policy is serving (T6 adopts onto probation)."""
    body = dict(utility_policy_body(ARIConfig()), ucb_c=1.25)
    state = _adopted_state(tmp_path, body, status="probationary_active")
    frozen = capture_utility_policy(
        ARIConfig(), registries=state, checkpoint_dir=tmp_path
    )
    assert frozen["ucb_c"] == 1.25


def test_tampered_body_falls_back_to_cfg_with_a_warning(tmp_path, caplog):
    """A tampered body degrades to the cfg branch (the incumbent regime,
    always safe) — never a raise into the run (plan 14 §5.7)."""
    body = dict(utility_policy_body(ARIConfig()), ucb_c=1.75)
    state = _adopted_state(tmp_path, body)
    # In-place mutation of a governed body: the bytes no longer hash to the
    # registered identity.
    evolved_policy_path(tmp_path, "utility_policy_prompt_v2").write_text(
        canonical_json(dict(body, ucb_c=1.99)), encoding="utf-8"
    )
    with caplog.at_level("WARNING"):
        frozen = capture_utility_policy(
            ARIConfig(), registries=state, checkpoint_dir=tmp_path
        )
    assert frozen == capture_utility_policy(ARIConfig())
    assert any("utility policy" in r.message.lower() for r in caplog.records)


def test_missing_body_file_falls_back_to_cfg_never_raises(tmp_path):
    body = dict(utility_policy_body(ARIConfig()), ucb_c=1.75)
    state = _adopted_state(tmp_path, body)
    evolved_policy_path(tmp_path, "utility_policy_prompt_v2").unlink()
    assert capture_utility_policy(
        ARIConfig(), registries=state, checkpoint_dir=tmp_path
    ) == capture_utility_policy(ARIConfig())


def test_capture_is_deterministic_and_seal_is_over_the_body_alone():
    """P2: content-only, no wall clock. The hash is computed over the
    canonical JSON of the OTHER keys, before the hash key is inserted."""
    body = utility_policy_body(ARIConfig())
    sealed = seal_utility_policy(body)
    assert sealed["utility_policy_hash"] == hash12(canonical_json(body))
    assert "utility_policy_hash" not in body  # seal never mutates the body
    assert seal_utility_policy(body) == sealed


# ── the identity bridge (§5.3): one value, three names ──────────────────────


def test_identity_bridge_one_value_three_names():
    """hash12(canonical_json(body)) == capture's hash == the entry's
    prompt_hash. One scheme, no second implementation — this arithmetic IS
    why a policy is registered as a "prompt"."""
    cfg = ARIConfig()
    body = utility_policy_body(cfg)
    spec = founding_utility_policy_spec(cfg)
    assert spec.prompt_hash == hash12(canonical_json(body))
    assert spec.prompt_hash == capture_utility_policy(cfg)["utility_policy_hash"]
    assert spec.full_sha256[:12] == spec.prompt_hash


def test_founding_policy_spec_shape():
    spec = founding_utility_policy_spec(ARIConfig())
    assert spec.prompt_id == UTILITY_POLICY_PROMPT_ID
    assert spec.role == "utility_policy"
    assert spec.status == "active"          # founding: active on creation
    assert spec.generation_mode == "founding"
    assert spec.evolvable is True
    assert spec.template_ref == {
        "kind": "policy", "path": "rqgm_prompts/utility_policy_prompt_v1.json"
    }
    # The body is NEVER inlined into the spec: two copies of a hashed object
    # is exactly the split-brain the registry refuses.
    assert spec.spec["utility_policy_ref"] == spec.template_ref["path"]
    assert "composite" not in spec.spec
    # A document, not an actor: no instruction, no constraint clauses.
    assert spec.spec["role_instruction"] == ""
    assert spec.spec["constitutional_constraints"] == []


def test_policy_kind_is_in_the_closed_template_ref_vocabulary():
    """R7: the kind vocabulary is closed and its parity with the dispatcher
    is asserted."""
    assert "policy" in TEMPLATE_REF_KINDS
    assert set(TEMPLATE_REF_KINDS) == {"package", "checkpoint", "policy"}


def test_active_prompt_view_never_serves_a_policy():
    """A utility policy is not a prompt to RENDER; it is a policy to freeze.
    Filtering keeps the loader's unknown-kind raise unreachable rather than
    merely unreached (plan 14 §5.3/R7)."""
    specs = build_founding_specs() + [founding_utility_policy_spec(ARIConfig())]
    view = active_prompt_view(specs)
    assert UTILITY_POLICY_PROMPT_ID not in view
    assert not any(
        str(s.template_ref.get("kind")) == "policy" for s in view.values()
    )
    # The prompt specs are all still served.
    assert "rqgm/policy_mutator" in view


def test_founding_registration_events_cfg_none_is_the_pure_table_sequence():
    """cfg=None keeps today's exact contract, so every existing caller and
    test is unaffected (plan 14 §7)."""
    events_none = founding_registration_events()
    ids = [p["prompt_id"] for t, p in events_none if t == "prompt_registered"]
    assert UTILITY_POLICY_PROMPT_ID not in ids


def test_founding_registration_events_with_cfg_appends_the_policy_row():
    evs = founding_registration_events(ARIConfig())
    types = [t for t, _p in evs]
    # Prompt rows first, then component rows — the policy row is appended
    # AFTER the prompt rows and BEFORE the component rows.
    assert types == (
        ["prompt_registered"] * types.count("prompt_registered")
        + ["component_registered"] * types.count("component_registered")
    )
    prompts = [p for t, p in evs if t == "prompt_registered"]
    assert prompts[-1]["prompt_id"] == UTILITY_POLICY_PROMPT_ID
    assert prompts[-1]["role"] == "utility_policy"
    assert prompts[-1]["status"] == "active"
    assert prompts[-1]["source"] == {
        "kind": "policy", "path": "rqgm_prompts/utility_policy_prompt_v1.json"
    }


def test_founding_events_are_reproducible_for_a_fixed_resolved_cfg():
    """The amended reproducibility claim (plan 14 §5.3): reproducible FOR A
    FIXED RESOLVED CFG — and genuinely cfg-dependent (R6)."""
    a = founding_registration_events(ARIConfig())
    b = founding_registration_events(ARIConfig())
    assert a == b
    other = founding_registration_events(
        ARIConfig(evaluator={"axis_weights": {"novelty": 0.9}})
    )
    assert other != a


# ── the write-once policy body store (§5.3 / §6.1) ──────────────────────────


def test_policy_body_is_write_once(tmp_path):
    body = canonical_json(utility_policy_body(ARIConfig()))
    path = write_evolved_policy_body(tmp_path, "utility_policy_prompt_v1", body)
    assert path == evolved_policy_path(tmp_path, "utility_policy_prompt_v1")
    # Identical re-writes are idempotent (resume safety).
    assert write_evolved_policy_body(
        tmp_path, "utility_policy_prompt_v1", body
    ) == path
    # Differing bytes for an existing id: evolution mints a NEW prompt_id.
    with pytest.raises(PromptImmutabilityError):
        write_evolved_policy_body(
            tmp_path, "utility_policy_prompt_v1",
            canonical_json(dict(utility_policy_body(ARIConfig()), ucb_c=9.0)),
        )


def test_resolve_text_refuses_bytes_that_no_longer_match(tmp_path):
    """The identical refusal ``checkpoint_file`` applies (plan 14 §5.3)."""
    body = utility_policy_body(ARIConfig())
    spec = utility_policy_spec(body, prompt_id="utility_policy_prompt_v2")
    write_evolved_policy_body(tmp_path, spec.prompt_id, canonical_json(body))
    reg = GovernedPromptRegistry({
        spec.prompt_id: GovernedPromptEntry(
            prompt_id=spec.prompt_id, role="utility_policy", status="active",
            prompt_hash=spec.prompt_hash, prompt_sha256=spec.full_sha256,
            source={"kind": "policy", "path": spec.template_ref["path"]},
        ),
    })
    text, version_id = reg.resolve_text(spec.prompt_id, checkpoint_dir=tmp_path)
    assert version_id == spec.prompt_hash
    assert json.loads(text) == body

    evolved_policy_path(tmp_path, spec.prompt_id).write_text(
        canonical_json(dict(body, ucb_c=9.0)), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="in-place mutation"):
        reg.resolve_text(spec.prompt_id, checkpoint_dir=tmp_path)


# ── PolicyMutator (§5.4) ────────────────────────────────────────────────────


def test_policy_mutator_exposes_no_registry_or_store_write_surface():
    """The PromptMutator contract: status changes are Task 09's engine,
    kernel-validated (plan 14 §7)."""
    mutator = PolicyMutator()
    for attr in (
        "registry", "store", "prompts", "components", "write", "append",
        "apply", "adopt", "activate", "save", "commit", "registry_writer",
    ):
        assert not hasattr(mutator, attr), f"write surface leaked: {attr}"
    public = {a for a in dir(mutator) if not a.startswith("_")}
    assert public == {"ROLE", "TARGET_ROLE", "META_PROMPT_KEY",
                      "component_id", "propose"}


def test_default_mutation_kinds_are_all_deterministic():
    """The default utility rewrite is FULLY deterministic — the strongest
    available posture for P2 (plan 14 §5.4)."""
    typed = ARIConfig().rqgm.utility_evolution
    assert set(typed.mutation_kinds) == set(KNOB_MUTATION_KINDS)
    assert "freeform_policy_proposal" not in typed.mutation_kinds
    assert "freeform_policy_proposal" in MUTATION_KINDS


@pytest.mark.parametrize("kind", sorted(KNOB_MUTATION_KINDS))
def test_knob_kinds_are_pure_and_deterministic(kind):
    """Same inputs -> identical proposal, twice. No LLM, no clock, no
    randomness."""
    body = _body()
    ev = _evidence("measurement_validity", "measurement_validity", "novelty")
    first = propose_utility_policy(body, evidence=ev, mutation_kind=kind)
    second = propose_utility_policy(body, evidence=ev, mutation_kind=kind)
    assert first == second
    assert first is not None
    assert canonical_json(first) == canonical_json(second)


@pytest.mark.parametrize("kind", sorted(KNOB_MUTATION_KINDS))
def test_knob_kinds_emit_constitutionally_LEGAL_policies(kind):
    """A deterministic proposer should not emit a policy it knows is
    illegal; the kernel still validates it (fail-closed)."""
    body = _body()
    proposed = propose_utility_policy(
        body, evidence=_evidence("novelty", "measurement_validity"),
        mutation_kind=kind,
    )
    assert proposed is not None
    report = ConstitutionalKernel().validate_utility_policy(proposed)
    assert not report.violations, [v.code for v in report.violations]


def test_axis_reweighting_moves_weight_TOWARD_the_pressured_axis():
    """The direction is the point of P1: when the epoch's evidence says nodes
    keep failing on measurement_validity, the next epoch's score weighs it
    MORE. A proposer that lowered the weight of the axis it keeps failing
    would be tuning the score to flatter the tree."""
    body = _body()
    proposed = propose_utility_policy(
        body,
        evidence=_evidence("measurement_validity", "measurement_validity"),
        mutation_kind="axis_reweighting",
    )
    assert proposed["axis_weights"]["measurement_validity"] > 0.2
    assert abs(sum(proposed["axis_weights"].values()) - 1.0) < 1e-6


def test_axis_reweighting_never_abolishes_an_axis():
    """R4's residual risk, bounded by the floor: even under overwhelming
    single-axis pressure every axis keeps a weight >= axis_weight_min."""
    body = _body()
    for _ in range(20):
        proposed = propose_utility_policy(
            body, evidence=_evidence(*(["novelty"] * 50)),
            mutation_kind="axis_reweighting",
        )
        if proposed is None:
            break
        body = proposed
        assert set(body["axis_weights"]) == {
            "measurement_validity", "novelty", "reproducibility",
            "comparative_rigor", "clarity_of_contribution",
        }
        lo = kernel_rules.UTILITY_POLICY_RULES["axis_weight_min"]
        hi = kernel_rules.UTILITY_POLICY_RULES["axis_weight_max"]
        for axis, w in body["axis_weights"].items():
            assert lo <= w <= hi, f"{axis}={w} escaped [{lo}, {hi}]"


def test_unknown_kind_returns_none_and_warns(caplog):
    with caplog.at_level("WARNING"):
        out = PolicyMutator().propose(
            utility_policy_body(ARIConfig()), mutation_kind="nuke_the_axes",
        )
    assert out is None
    assert any("unknown utility mutation_kind" in r.message
               for r in caplog.records)


def test_freeform_without_an_llm_returns_none():
    """The exact PromptMutator posture (plan 14 §5.4/§7)."""
    assert PolicyMutator(llm=None).propose(
        utility_policy_body(ARIConfig()),
        evidence=_evidence("novelty"),
        mutation_kind="freeform_policy_proposal",
    ) is None


def test_over_budget_returns_none():
    """Budget reuse, one schema home: the existing rqgm.prompt_evolution
    caps, keyed on the TARGET role utility_policy (plan 14 §5.4)."""
    existing = [{
        "record_type": "utility_policy_candidate", "epoch_id": "epoch_000",
        "role": "policy_mutator", "candidate_id": "utility_policy_prompt_v2",
    }]
    assert PolicyMutator().propose(
        _body(),
        evidence=_evidence("novelty"),
        mutation_kind="axis_reweighting",
        epoch_id="epoch_000",
        existing_records=existing,
        cfg=_cfg(),
    ) is None
    # A DIFFERENT epoch is a fresh budget.
    assert PolicyMutator().propose(
        _body(),
        evidence=_evidence("novelty"),
        mutation_kind="axis_reweighting",
        epoch_id="epoch_001",
        existing_records=existing,
        cfg=_cfg(),
    ) is not None


def test_budget_reason_counts_policy_candidates_against_utility_policy_role():
    from ari.rqgm.prompt_evolution import candidate_budget_reason

    records = [{
        "record_type": "utility_policy_candidate", "epoch_id": "epoch_000",
        "role": "policy_mutator",
    }]
    # Keyed on the TARGET role, not the author's.
    assert candidate_budget_reason(
        records, "epoch_000", "utility_policy", _cfg()
    ) is not None
    assert candidate_budget_reason(
        records, "epoch_000", "policy_mutator", _cfg()
    ) is None


def test_the_prompt_channel_cannot_starve_the_utility_rewrite():
    """The caps bound each CHANNEL's own volume; the two channels do not
    share one pot.

    The Task 07 channel saturates ``max_total_candidates_per_epoch`` (4) on
    a default config BEFORE the PolicyMutator runs (its calm-boundary
    expectation is exactly four candidates). Sharing one pot would starve
    the utility rewrite in every default run — P1's cause half structurally
    unreachable again, the exact defect Task 14 exists to remove.
    """
    from ari.rqgm.prompt_evolution import candidate_budget_reason

    saturated = [
        {"record_type": "prompt_candidate", "epoch_id": "epoch_000",
         "role": r}
        for r in ("adversary", "clean_room_generator", "defender", "generator")
    ]
    assert len(saturated) == ARIConfig(
    ).rqgm.prompt_evolution.max_total_candidates_per_epoch
    # The prompt channel IS full ...
    assert candidate_budget_reason(
        saturated, "epoch_000", "judge", _cfg()
    ) is not None
    # ... and the utility channel is still open.
    assert candidate_budget_reason(
        saturated, "epoch_000", "utility_policy", _cfg()
    ) is None
    # Conversely, a full utility channel never blocks a prompt candidate.
    policy_full = [{
        "record_type": "utility_policy_candidate", "epoch_id": "epoch_000",
        "role": "policy_mutator",
    }]
    assert candidate_budget_reason(
        policy_full, "epoch_000", "judge", _cfg()
    ) is None


def test_prompt_channel_budget_is_byte_identical_to_pre_task_14():
    """utility_policy_candidate records did not exist before Task 14, so the
    prompt channel's accounting is unchanged for every pre-existing input."""
    from ari.rqgm.prompt_evolution import candidate_budget_reason

    records = [
        {"record_type": "prompt_candidate", "epoch_id": "epoch_000",
         "role": "judge"},
        {"record_type": "prompt_candidate", "epoch_id": "epoch_001",
         "role": "judge"},
        {"record_type": "meta_agent_output", "epoch_id": "epoch_000",
         "role": "judge"},
    ]
    assert candidate_budget_reason(records, "epoch_000", "judge", _cfg()) == (
        "role 'judge' already has 1 candidate(s) in epoch_000 (cap 1)"
    )
    assert candidate_budget_reason(
        records, "epoch_002", "judge", _cfg()
    ) is None


def test_mixed_record_type_log_partitions_the_two_channels(_cfg=_cfg):
    """A single evolution log carrying BOTH channels' records (plan 14
    §5.4/§6.3, the sanctioned per-channel budget deviation): each channel
    counts only its OWN record_type, so a utility_policy_candidate never
    consumes a prompt-channel slot and vice versa. The prompt channel's count
    is byte-identical to a log with the utility records deleted."""
    from ari.rqgm.prompt_evolution import candidate_budget_reason

    mixed = [
        {"record_type": "prompt_candidate", "epoch_id": "epoch_000",
         "role": "judge"},
        {"record_type": "utility_policy_candidate", "epoch_id": "epoch_000",
         "role": "policy_mutator"},
        {"record_type": "utility_policy_candidate", "epoch_id": "epoch_000",
         "role": "policy_mutator"},
    ]
    prompt_only = [r for r in mixed
                   if r["record_type"] == "prompt_candidate"]
    # The prompt channel sees exactly its one prompt_candidate — the two
    # utility records are invisible to it (byte-identical to prompt_only).
    assert (
        candidate_budget_reason(mixed, "epoch_000", "judge", _cfg())
        == candidate_budget_reason(prompt_only, "epoch_000", "judge", _cfg())
    )
    # 'router' has no prompt_candidate yet, so its channel is open in both.
    assert candidate_budget_reason(mixed, "epoch_000", "router", _cfg()) is None
    # The utility channel counts its own records and is full (singleton cap 1).
    assert candidate_budget_reason(
        mixed, "epoch_000", "utility_policy", _cfg()
    ) is not None


def test_candidate_envelope_names_the_PROPOSER_not_the_policy():
    """A candidate is a proposal BY a component (plan 14 §6.2)."""
    cand = PolicyMutator().propose(
        _body(),
        evidence=_evidence("novelty"),
        mutation_kind="axis_reweighting",
        epoch_id="epoch_003",
    )
    assert cand is not None
    assert cand.component_id == "policy_mutator_v1"
    assert cand.role == "policy_mutator"
    assert cand.candidate_id == "utility_policy_prompt_v2"
    # ... while the PROPOSAL rides `policy` + `policy_hash`.
    assert cand.policy_hash == hash12(canonical_json(cand.policy))
    d = cand.to_dict()
    assert d["record_type"] == "utility_policy_candidate"
    assert d["record_id"].startswith("upc_")
    assert utility_policy_candidate_from_dict(d) == cand


def test_candidate_validates_against_its_schema():
    jsonschema = pytest.importorskip("jsonschema")
    from ari import schemas

    cand = PolicyMutator().propose(
        _body(),
        evidence=_evidence("novelty"),
        mutation_kind="axis_reweighting",
        epoch_id="epoch_003",
    )
    jsonschema.validate(
        cand.to_dict(), schemas.load("rqgm_utility_policy_candidate.schema")
    )


def test_candidate_never_carries_raw_attack_text():
    """Raw adjudication material must only ever flow through abstract views
    (the FORBIDDEN_PLACEHOLDERS prohibition, applied to policies)."""
    poisoned = [{
        "record_id": "fs_000001",
        "affected_axes": ["novelty"],
        "raw_attack_text": "SECRET-ATTACK-PAYLOAD",
        "defense_text": "SECRET-DEFENSE-PAYLOAD",
    }]
    cand = PolicyMutator().propose(
        _body(),
        evidence=poisoned,
        mutation_kind="axis_reweighting",
        epoch_id="epoch_001",
    )
    assert cand is not None
    blob = canonical_json(cand.to_dict())
    assert "SECRET-ATTACK-PAYLOAD" not in blob
    assert "SECRET-DEFENSE-PAYLOAD" not in blob
    assert cand.source_refs == ("fs_000001",)


def test_no_op_rewrite_is_not_a_rewrite():
    """Evidence that supports no change mints nothing."""
    assert PolicyMutator().propose(
        _body(),
        evidence=(),  # no pressure
        mutation_kind="axis_reweighting",
        epoch_id="epoch_001",
    ) is None


def test_proposer_cannot_see_scores():
    """P2 / no collusion: `propose` has no frontier/score parameter at all,
    so a policy tuned to flatter the proposer's own tree is not expressible
    (plan 14 §5.4/§9)."""
    import inspect

    params = set(inspect.signature(PolicyMutator.propose).parameters)
    for forbidden in ("frontier", "frontier_scores", "scores", "nodes",
                      "tree", "node", "all_nodes"):
        assert forbidden not in params
    assert params == {
        "self", "incumbent_policy", "evidence", "mutation_kind", "epoch_id",
        "record_seq", "existing_records", "cfg", "parent_prompt_id",
        "incumbent_version", "rationale",
    }


def test_policy_mutator_never_proposes_a_policy_for_its_own_role():
    """No same-role generation: PolicyMutator only ever targets
    utility_policy; its OWN template is evolved by the PromptMutator."""
    assert PolicyMutator.ROLE == "policy_mutator"
    assert PolicyMutator.TARGET_ROLE == "utility_policy"
    assert PolicyMutator.ROLE != PolicyMutator.TARGET_ROLE


# ── validate_utility_policy semantics (§5.6) ────────────────────────────────


def test_axis_abolition_is_blocked():
    """{novelty: 1.0} is formally a policy and substantively the deletion of
    measurement_validity and reproducibility from the method."""
    k = ConstitutionalKernel()
    report = k.validate_utility_policy({
        "composite": "harmonic_mean",
        "axis_weights": {"novelty": 1.0},
        "frontier_score": "ucb_like",
        "depth_penalty_lambda": 0.0,
        "ucb_c": 0.5,
    })
    codes = {v.code for v in report.violations}
    assert "CK-UTL-004" in codes
    assert all(
        kernel_rules.SEVERITY[c] == "block" for c in codes if c != "CK-UTL-006"
    )


def test_composite_outside_the_evaluator_literal_is_blocked():
    """The kernel does not invent the vocabulary, it PINS it: a candidate can
    never name a composite the evaluator cannot compute."""
    from ari.config import EvaluatorConfig

    literal = EvaluatorConfig.model_fields["composite"].annotation
    import typing

    allowed = set(typing.get_args(literal))
    assert set(kernel_rules.UTILITY_POLICY_RULES["allowed_composite"]) == allowed

    report = ConstitutionalKernel().validate_utility_policy(
        dict(_LEGAL, composite="median")
    )
    assert "CK-UTL-002" in {v.code for v in report.violations}


def test_frontier_score_set_mirrors_the_bfts_literal():
    from ari.config import BFTSConfig
    import typing

    allowed = set(typing.get_args(
        BFTSConfig.model_fields["frontier_score"].annotation
    ))
    assert set(
        kernel_rules.UTILITY_POLICY_RULES["allowed_frontier_score"]
    ) == allowed


_LEGAL = {
    "composite": "harmonic_mean",
    "axis_weights": {
        "clarity_of_contribution": 0.15, "comparative_rigor": 0.20,
        "measurement_validity": 0.30, "novelty": 0.20,
        "reproducibility": 0.15,
    },
    "frontier_score": "scientific_plus_diversity",
    "depth_penalty_lambda": 0.05,
    "ucb_c": 0.5,
}


def test_stale_axis_key_under_dynamic_axes_warns_never_blocks():
    """Blocking would make the kernel wrong about a config the evaluator
    handles: EvaluatorConfig.axis_weights silently drops unknown keys."""
    report = ConstitutionalKernel().validate_utility_policy(
        dict(_LEGAL, axis_weights={"novelty": 0.5, "custom_axis": 0.5}),
        live_axes=("novelty",),
    )
    codes = [v.code for v in report.violations]
    assert codes == ["CK-UTL-006"]
    assert all(v.severity == "warn" for v in report.violations)


def test_sum_to_one_is_checked_within_float_tolerance():
    k = ConstitutionalKernel()
    tol = k.tolerances["float_tolerance"]
    assert tol == 1e-9

    def sum_off_by(delta):
        """A legal-bounds weight pair whose sum is 1.0 + delta."""
        return dict(_LEGAL, axis_weights={"x": 0.5, "y": 0.5 + delta})

    # Inside the tolerance: binary float addition never lands exactly on 1.0
    # for real renormalised weights, so an exact `== 1.0` would make
    # CK-UTL-005 fire on legal policies.
    inside = k.validate_utility_policy(sum_off_by(tol / 100))
    assert "CK-UTL-005" not in {v.code for v in inside.violations}
    # Outside it: a genuinely unnormalised policy IS caught.
    outside = k.validate_utility_policy(sum_off_by(1e-3))
    assert "CK-UTL-005" in {v.code for v in outside.violations}
    # ... in both directions, and for a plainly-wrong total.
    assert "CK-UTL-005" in {
        v.code for v in k.validate_utility_policy(sum_off_by(-1e-3)).violations
    }
    assert "CK-UTL-005" in {
        v.code for v in k.validate_utility_policy(
            dict(_LEGAL, axis_weights={"a": 0.3, "b": 0.3})
        ).violations
    }


def test_a_legal_policy_has_no_violations():
    assert not ConstitutionalKernel().validate_utility_policy(
        _LEGAL
    ).violations
    # The seal is ignored for membership checks.
    assert not ConstitutionalKernel().validate_utility_policy(
        seal_utility_policy(_LEGAL)
    ).violations


def test_the_founding_policy_is_legal():
    """The shipped default must itself pass the constitution."""
    report = ConstitutionalKernel().validate_utility_policy(
        capture_utility_policy(ARIConfig())
    )
    assert not report.violations, [v.code for v in report.violations]


def test_validate_utility_policy_is_deterministic():
    k1, k2 = ConstitutionalKernel(), ConstitutionalKernel()
    bad = dict(_LEGAL, composite="median", ucb_c=99.0)
    assert canonical_json(k1.validate_utility_policy(bad).to_dict()) == (
        canonical_json(k2.validate_utility_policy(bad).to_dict())
    )


# ── UtilityPolicyStamp (§5.8 delta 2) ───────────────────────────────────────


class _Node:
    def __init__(self, metrics=None):
        self.id = "node_1"
        self.metrics = metrics if metrics is not None else {}


def test_stamp_writes_the_epoch_policy_hash_on_a_scored_node():
    stamp = UtilityPolicyStamp(
        epoch_state=lambda: type("E", (), {
            "utility_policy": {"utility_policy_hash": "abc123abc123"}
        })()
    )
    node = _Node({"_scientific_score": 0.7})
    assert stamp(node) == "abc123abc123"
    assert node.metrics[UTILITY_POLICY_HASH_KEY] == "abc123abc123"


def test_stamp_skips_unscored_nodes():
    """The stamp records the policy a SCORE was formed under; a node with no
    score has no score to invalidate."""
    stamp = UtilityPolicyStamp(
        epoch_state=lambda: {"utility_policy": {"utility_policy_hash": "a" * 12}}
    )
    node = _Node({})
    assert stamp(node) == ""
    assert UTILITY_POLICY_HASH_KEY not in node.metrics


def test_stamp_is_best_effort_and_never_raises():
    def boom():
        raise RuntimeError("no epoch")

    node = _Node({"_scientific_score": 0.5})
    assert UtilityPolicyStamp(epoch_state=boom)(node) == ""
    assert UTILITY_POLICY_HASH_KEY not in node.metrics
    # A node without a metrics dict is untouched, not crashed.
    assert UtilityPolicyStamp(epoch_state=None)(object()) == ""


def test_stamp_key_matches_the_frontier_repair_constant():
    """One sentinel name, two modules — the join must not drift."""
    from ari.rqgm import frontier_repair

    assert frontier_repair.UTILITY_POLICY_HASH_KEY == UTILITY_POLICY_HASH_KEY
    assert UTILITY_POLICY_HASH_KEY == "_utility_policy_hash"


# ── config parity (§6.3) ────────────────────────────────────────────────────


def test_utility_evolution_config_mirrors_defaults_yaml():
    from pathlib import Path

    import ari.configs

    data = yaml.safe_load(
        (Path(ari.configs.__file__).parent / "defaults.yaml").read_text()
    )
    yaml_ue = (data.get("rqgm") or {}).get("utility_evolution") or {}
    typed = ARIConfig().rqgm.utility_evolution
    assert yaml_ue.get("enabled") == typed.enabled is True
    assert yaml_ue.get("mutation_kinds") == typed.mutation_kinds == [
        "axis_reweighting", "composite_swap", "frontier_score_swap",
        "exploration_tuning",
    ]
    assert (
        yaml_ue.get("min_epochs_between_rewrites")
        == typed.min_epochs_between_rewrites == 1
    )


def test_weight_bounds_are_NOT_in_yaml():
    """Legality is frozen code, never config: a tunable weight bound is a
    tunable constitution, and any skill can write the checkpoint dir."""
    from pathlib import Path

    import ari.configs

    text = (Path(ari.configs.__file__).parent / "defaults.yaml").read_text()
    for key in ("axis_weight_min", "axis_weight_max", "axis_weight_sum",
                "allowed_composite", "allowed_frontier_score"):
        assert key not in text


def test_unknown_utility_evolution_keys_parse_warn_free():
    """extra: allow — an older ari-core reading a config that sets future
    keys silently gets today's behavior (the safest failure direction)."""
    cfg = _cfg(utility_evolution={"enabled": True, "future_key": 7})
    assert cfg.rqgm.utility_evolution.enabled is True


# ── determinism of the module itself (P2) ───────────────────────────────────


def test_utility_evolution_module_makes_no_llm_or_network_calls():
    """The import-grep discipline (kernel_rules' no-LLM/network test),
    extended to this module: the knob path is pure arithmetic. Only the
    opt-in freeform kind touches an injected LLM callable."""
    from pathlib import Path

    import ari.rqgm.utility_evolution as mod

    src = Path(mod.__file__).read_text()
    for forbidden in ("import requests", "import httpx", "urllib.request",
                      "import random", "from random import",
                      "openai", "anthropic", "litellm"):
        assert forbidden not in src, f"{forbidden!r} in utility_evolution.py"


# ── the vacuous shadow board (plan 14 §5.5 "Honest scope of the SHADOW
#    stage" / §7 contract row) ─────────────────────────────────────────────

def test_the_dry_run_reports_its_vacuous_shadow_board_as_absent():
    """A passive policy document is never shadow-EXECUTED, so it must report
    zero live-shadow comparisons as ABSENT — never borrow the T3 basis count.

    Regression: `shadow_samples` used to be `len(case_refs)`, i.e. a count of
    the policy body's DICT KEYS (always the 5 constitutional required_keys)
    standing in for a shadow-execution sample count, and `shadow_score` was an
    unlabelled verbatim copy of `replay_score`. `transition_engine` trusted
    both as the T6 gate.
    """
    from ari.config import ARIConfig
    from ari.rqgm.state import utility_policy_body
    from ari.rqgm.transition_engine import (
        NO_REPLAY_BASIS_KEY,
        NO_REPLAY_BASIS_ROLES,
        NO_SHADOW_BASIS_KEY,
    )
    from ari.rqgm.utility_evolution import evaluate_utility_policy_candidate

    body = utility_policy_body(ARIConfig())
    ev = evaluate_utility_policy_candidate(body, prompt_id="p1")

    assert ev["shadow_samples"] is None, "a dict-key count is not a sample count"
    assert ev["shadow_score"] is None
    assert ev["shadow_basis"] == "vacuous_passive_policy"
    # The absence is DECLARED, so the engine's role-scoped waiver — not a
    # fabricated count — is what carries the policy to T6.
    assert ev[NO_SHADOW_BASIS_KEY] is True
    assert ev[NO_REPLAY_BASIS_KEY] is True
    assert ev["role"] in NO_REPLAY_BASIS_ROLES
    # ...and the T3 board under the SHIPPED default (`axis_mode: dynamic` =>
    # both static `axis_weights` maps empty) is ABSENT, not 1.0: the ranking
    # comparison never ran, so there is no agreement to report. This was the
    # fourth fabricated 1.0 — a hardcoded pass for a comparison that never
    # happened, flatly contradicting §7's "No field carries a quantity nothing
    # produced". The sentinel above already carries the T3 pass.
    assert body.get("axis_weights") == {}, "premise: the default map is empty"
    assert ev["replay_score"] is None and ev["verdict"] == "pass"


def test_the_dry_run_reports_a_REAL_agreement_when_the_comparison_runs():
    """The other half of the absence contract: when both static `axis_weights`
    maps ARE populated (`axis_mode` not dynamic) the re-ranking comparison
    genuinely runs, so a real number is reported — `None` is reserved for "the
    comparison did not happen", never used to duck a board that exists."""
    from ari.config import ARIConfig
    from ari.rqgm.state import utility_policy_body
    from ari.rqgm.utility_evolution import evaluate_utility_policy_candidate

    body = utility_policy_body(ARIConfig())
    cand = dict(body, axis_weights={"a": 0.6, "b": 0.4})
    inc = dict(body, axis_weights={"a": 0.7, "b": 0.3})
    ev = evaluate_utility_policy_candidate(
        cand, prompt_id="p1", incumbent_body=inc)
    assert isinstance(ev["replay_score"], float)   # preserved ordering => 1.0
    assert ev["replay_score"] == 1.0
    # an INVERTED ordering is a real disagreement, scored as such
    inv = evaluate_utility_policy_candidate(
        dict(body, axis_weights={"a": 0.2, "b": 0.8}), prompt_id="p2",
        incumbent_body=inc)
    assert inv["replay_score"] == 0.0


def test_an_illegal_candidate_reports_no_board_rather_than_a_zero():
    """`verdict: "fail"` IS the finding (T2 retires on it). A `replay_score:
    0.0` would be a score nobody computed — the dry-run never scored it."""
    from ari.config import ARIConfig
    from ari.rqgm.state import utility_policy_body
    from ari.rqgm.utility_evolution import evaluate_utility_policy_candidate

    class _Blocking:
        def validate_utility_policy(self, *a, **k):
            return type("R", (), {"blocking": True})()

    ev = evaluate_utility_policy_candidate(
        utility_policy_body(ARIConfig()), prompt_id="p1", kernel=_Blocking())
    assert ev["verdict"] == "fail"
    assert ev["replay_score"] is None and ev["anchor_score"] is None
    assert ev["shadow_score"] is None and ev["shadow_samples"] is None


def test_shadow_min_samples_no_longer_silently_kills_the_utility_rewrite():
    """The config-insensitivity the dict-key coincidence hid: `shadow_samples`
    was 5, so `shadow_min_samples: 6` (off-default) killed every rewrite. The
    count floor is now waived by role, so the knob cannot disable P1."""
    from ari.config import ARIConfig
    from ari.rqgm.state import utility_policy_body
    from ari.rqgm.utility_evolution import evaluate_utility_policy_candidate

    cfg = ARIConfig()
    cfg.rqgm.transition.shadow_min_samples = 6
    ev = evaluate_utility_policy_candidate(
        utility_policy_body(cfg), prompt_id="p1")
    assert ev["shadow_samples"] is None    # nothing to be short of
