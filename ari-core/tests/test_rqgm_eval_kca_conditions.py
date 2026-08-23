"""Task-20 H/K comparison axes remain orthogonal to the B0-B8 ladder."""

from __future__ import annotations

import json

import pytest

from ari.config import ARIConfig
from ari.config.kca_runtime import KCAAdmissionConfigError, resolve_kca_modes
from ari.protocols.integrity import canonical_digest
from ari.rqgm.evaluation.conditions import (
    ASSURANCE_CONDITION_IDS,
    CONDITION_IDS,
    FULL_KCA_CONDITION_ALIAS,
    KNOWLEDGE_CAPABILITY_CONDITION_IDS,
    condition_overlay,
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


def _leaf_paths(value, prefix: str = "") -> dict:
    """``{"rqgm.eval.enabled": True, ...}`` for a nested overlay or dump."""
    if isinstance(value, dict):
        out: dict = {}
        for key, item in value.items():
            out.update(_leaf_paths(item, f"{prefix}.{key}" if prefix else str(key)))
        return out
    return {prefix: value}


def test_existing_b0_b8_exact():
    """Task 20 section 8 criterion 52: B0-B8 keep their meaning and their
    effective config.

    Task 20 adds its axes BESIDE the B ladder rather than inside it, so the
    claim has two halves and both are asserted here.

    The matrix half: a B rung expands to the same bytes when every block Task
    20 added is taken away. The reduced matrix keeps only the block the ladder
    is defined in, so a block added tomorrow is stripped by this test without
    being named in it -- and the floor refuses the degenerate case where
    nothing was stripped and the matrix is compared with itself.

    The run half: the typed config a run is launched with. Every leaf a B rung
    sets must survive verbatim into the B x H x K overlay, and the effective
    ``ARIConfig`` may differ from the B-only one ONLY at leaves the factorial
    overlay itself adds. That is compared over the whole config dump rather
    than over a list of fields, because "unchanged" is a claim about all of
    it: a Task-20 axis that silently defaulted a B rung's flag the other way
    would be caught here even though no test names that flag.
    """
    b_ladder = tuple(cid for cid in CONDITION_IDS if cid != "B9")
    assert set(b_ladder) == {f"B{index}" for index in range(9)}, b_ladder

    reduced = {"conditions": MATRIX["conditions"]}
    stripped = set(MATRIX) - set(reduced)
    assert {"assurance_conditions", "knowledge_capability_conditions"} <= stripped, (
        "the Task-20 blocks are not in the matrix; this test compares the "
        f"matrix with itself. stripped={sorted(stripped)}"
    )

    for cid in b_ladder:
        assert expand_condition(MATRIX, cid) == expand_condition(reduced, cid), cid
        assert condition_overlay(MATRIX, cid) == condition_overlay(reduced, cid), cid

    # And a golden for the ladder itself, because "unchanged" is a claim about
    # bytes and the strip above only says the two matrices agree. The first
    # digest covers what every B rung expands to; the second covers what a run
    # launched on that rung is EFFECTIVELY configured with, read at every leaf
    # any rung sets -- so a shipped default flipping under a rung that does not
    # set the flag moves it too. Neither is a value to update when a rung
    # changes: plan 20 section 2 freezes B0-B8 byte-for-byte, so a moved digest
    # here is the regression, not a stale expectation.
    assert canonical_digest(
        {cid: expand_condition(MATRIX, cid) for cid in b_ladder}
    ) == "sha256:25a8a6c20408bb9148186afa681d3d36220d13feb0f341262a31b363ebed2085"
    ladder_paths = sorted(
        {path for cid in b_ladder for path in _leaf_paths(condition_overlay(MATRIX, cid))}
    )
    assert ladder_paths, "no B rung sets anything; the effective pin is vacuous"
    assert canonical_digest({
        cid: {
            path: _leaf_paths(
                ARIConfig.model_validate(condition_overlay(MATRIX, cid))
                .model_dump(mode="json")
            ).get(path)
            for path in ladder_paths
        }
        for cid in b_ladder
    }) == "sha256:97b97697dcd3c93284e5a1ea56326739a11b589b639d82541f9bfff2c521393d"

    for cid in b_ladder:
        b_overlay = condition_overlay(MATRIX, cid)
        b_leaves = _leaf_paths(b_overlay)
        assert b_leaves, cid
        b_config = _leaf_paths(ARIConfig.model_validate(b_overlay).model_dump(mode="json"))
        for h_condition in ASSURANCE_CONDITION_IDS:
            for k_condition in KNOWLEDGE_CAPABILITY_CONDITION_IDS:
                overlay = factorial_condition_overlay(
                    MATRIX, b_condition=cid, h_condition=h_condition,
                    k_condition=k_condition,
                )
                leaves = _leaf_paths(overlay)
                for path, value in b_leaves.items():
                    assert path in leaves and leaves[path] == value, (
                        cid, h_condition, k_condition, path)
                added = tuple(sorted(set(leaves) - set(b_leaves)))
                assert added, (cid, h_condition, k_condition)
                config = _leaf_paths(
                    ARIConfig.model_validate(overlay).model_dump(mode="json"))
                changed = {
                    path for path in set(b_config) | set(config)
                    if b_config.get(path) != config.get(path)
                }
                stray = {
                    path for path in changed
                    if not any(path == key or path.startswith(key + ".")
                               for key in added)
                }
                assert not stray, (cid, h_condition, k_condition, sorted(stray))


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
