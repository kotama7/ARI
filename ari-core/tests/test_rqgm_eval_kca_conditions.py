"""Task-20 H/K comparison axes remain orthogonal to the B0-B8 ladder."""

from __future__ import annotations

import json

import pytest

from ari.config import ARIConfig
from ari.config.kca_runtime import KCAAdmissionConfigError, resolve_kca_modes
from ari.rqgm.evaluation.conditions import (
    ASSURANCE_CONDITION_IDS,
    CONDITION_IDS,
    FULL_KCA_CONDITION_ALIAS,
    KNOWLEDGE_CAPABILITY_CONDITION_IDS,
    evaluation_condition_overlay,
    expand_condition,
    factorial_condition_id,
    factorial_condition_overlay,
    load_matrix,
    parse_factorial_condition_id,
)


MATRIX = load_matrix()


def test_task20_axis_vocabularies_are_closed_and_separate():
    assert ASSURANCE_CONDITION_IDS == (
        "H0_assurance_off",
        "H1_assurance_audit",
        "H2_assurance_screen_enforced",
        "H3_assurance_full_certification",
    )
    assert KNOWLEDGE_CAPABILITY_CONDITION_IDS == (
        "K0_legacy_no_knowledge",
        "K1_knowledge_injection_only",
        "K2_capability_binding_audit",
        "K3_capability_binding_enforced",
    )
    assert set(MATRIX["conditions"]) == set(CONDITION_IDS)
    assert set(MATRIX["assurance_conditions"]) == set(ASSURANCE_CONDITION_IDS)
    assert set(MATRIX["knowledge_capability_conditions"]) == set(
        KNOWLEDGE_CAPABILITY_CONDITION_IDS
    )
    assert FULL_KCA_CONDITION_ALIAS not in MATRIX["knowledge_capability_conditions"]


def test_task20_does_not_change_any_b_expansion():
    reduced = {"conditions": MATRIX["conditions"]}
    assert {
        cid: expand_condition(MATRIX, cid) for cid in CONDITION_IDS
    } == {
        cid: expand_condition(reduced, cid) for cid in CONDITION_IDS
    }


@pytest.mark.parametrize("b", CONDITION_IDS)
@pytest.mark.parametrize("h", ASSURANCE_CONDITION_IDS)
@pytest.mark.parametrize("k", KNOWLEDGE_CAPABILITY_CONDITION_IDS)
def test_factorial_identity_round_trips_and_overlay_is_deterministic(b, h, k):
    condition_id = factorial_condition_id(b, h, k)
    assert parse_factorial_condition_id(condition_id) == (b, h, k)
    first = factorial_condition_overlay(
        MATRIX, b_condition=b, h_condition=h, k_condition=k
    )
    second = evaluation_condition_overlay(MATRIX, condition_id)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    cfg = ARIConfig.model_validate(first)
    assert cfg.rqgm.eval.enabled is True
    assert cfg.rqgm.eval.kca_conditions.b == b
    assert cfg.rqgm.eval.kca_conditions.h == h
    assert cfg.rqgm.eval.kca_conditions.k == k


def test_k4_is_only_the_k3_h3_reporting_alias():
    overlay = factorial_condition_overlay(
        MATRIX,
        b_condition="B8",
        h_condition="H3_assurance_full_certification",
        k_condition="K3_capability_binding_enforced",
    )
    cfg = ARIConfig.model_validate(overlay)
    assert cfg.rqgm.eval.kca_conditions.reporting_alias == FULL_KCA_CONDITION_ALIAS
    assert cfg.knowledge.mode == "enforce"
    assert cfg.capability_binding.mode == "enforce"
    assert cfg.assurance.mode == "enforce"
    with pytest.raises(ValueError, match="reporting alias"):
        evaluation_condition_overlay(
            MATRIX,
            "B8__H3_assurance_full_certification__"
            + FULL_KCA_CONDITION_ALIAS,
        )


def test_enforce_interlock_is_measured_not_silently_rewritten():
    invalid = ARIConfig.model_validate(factorial_condition_overlay(
        MATRIX,
        b_condition="B8",
        h_condition="H2_assurance_screen_enforced",
        k_condition="K0_legacy_no_knowledge",
    ))
    assert invalid.assurance.mode == "enforce"
    assert invalid.capability_binding.mode == "legacy"
    with pytest.raises(KCAAdmissionConfigError):
        resolve_kca_modes(invalid)

    valid = ARIConfig.model_validate(factorial_condition_overlay(
        MATRIX,
        b_condition="B8",
        h_condition="H3_assurance_full_certification",
        k_condition="K3_capability_binding_enforced",
    ))
    modes = resolve_kca_modes(valid)
    assert (modes.knowledge, modes.capability_binding, modes.assurance) == (
        "enforce", "enforce", "enforce"
    )
