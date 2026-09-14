"""Orthogonal Task-20 Knowledge/Capability/Assurance condition overlays."""

from __future__ import annotations

import copy


ASSURANCE_CONDITION_IDS: tuple[str, ...] = (
    "H0_assurance_off",
    "H1_assurance_audit",
    "H2_assurance_screen_enforced",
    "H3_assurance_full_certification",
)
KNOWLEDGE_CAPABILITY_CONDITION_IDS: tuple[str, ...] = (
    "K0_legacy_no_knowledge",
    "K1_knowledge_injection_only",
    "K2_capability_binding_audit",
    "K3_capability_binding_enforced",
)
FULL_KCA_CONDITION_ALIAS = "K4_full_knowledge_capability_assurance"


def expand_assurance_condition(matrix: dict, condition_id: str) -> dict:
    from ari.rqgm.evaluation.conditions import _expand_chain

    conditions = matrix.get("assurance_conditions") or {}
    if not conditions:
        raise ValueError("ablation matrix has no `assurance_conditions:` mapping")
    return _expand_chain(conditions, condition_id, block="assurance")


def assurance_condition_overlay(matrix: dict, condition_id: str) -> dict:
    preset = expand_assurance_condition(matrix, condition_id)
    return {
        key: copy.deepcopy(value)
        for key, value in preset.items()
        if key in {"assurance", "rqgm"} and isinstance(value, dict)
    }


def expand_knowledge_capability_condition(matrix: dict, condition_id: str) -> dict:
    from ari.rqgm.evaluation.conditions import _expand_chain

    if condition_id == FULL_KCA_CONDITION_ALIAS:
        raise ValueError(
            "K4 is the K3 × H3 reporting alias, not an independently "
            "combinable runtime condition"
        )
    conditions = matrix.get("knowledge_capability_conditions") or {}
    if not conditions:
        raise ValueError(
            "ablation matrix has no `knowledge_capability_conditions:` mapping"
        )
    return _expand_chain(conditions, condition_id, block="knowledge/capability")


def knowledge_capability_condition_overlay(matrix: dict, condition_id: str) -> dict:
    preset = expand_knowledge_capability_condition(matrix, condition_id)
    return {
        key: copy.deepcopy(value)
        for key, value in preset.items()
        if key in {"knowledge", "capability_binding", "rqgm"}
        and isinstance(value, dict)
    }


def factorial_condition_id(
    b_condition: str, h_condition: str, k_condition: str
) -> str:
    from ari.rqgm.evaluation.conditions import CONDITION_IDS

    if b_condition not in CONDITION_IDS:
        raise KeyError(f"unknown B condition {b_condition!r}")
    if h_condition not in ASSURANCE_CONDITION_IDS:
        raise KeyError(f"unknown H condition {h_condition!r}")
    if k_condition == FULL_KCA_CONDITION_ALIAS:
        raise ValueError(
            "K4 is the K3 × H3 reporting alias, not an independently "
            "combinable runtime condition"
        )
    if k_condition not in KNOWLEDGE_CAPABILITY_CONDITION_IDS:
        raise KeyError(f"unknown K condition {k_condition!r}")
    return "__".join((b_condition, h_condition, k_condition))


def parse_factorial_condition_id(condition_id: str) -> tuple[str, str, str]:
    parts = tuple(str(condition_id).split("__"))
    if len(parts) != 3:
        raise ValueError("factorial condition id must be B__H__K")
    factorial_condition_id(*parts)
    return parts


def factorial_condition_overlay(
    matrix: dict,
    *,
    b_condition: str,
    h_condition: str,
    k_condition: str,
) -> dict:
    from ari.rqgm.evaluation.conditions import condition_overlay, deep_merge

    overlay = condition_overlay(matrix, b_condition)
    overlay = deep_merge(
        overlay, knowledge_capability_condition_overlay(matrix, k_condition)
    )
    overlay = deep_merge(overlay, assurance_condition_overlay(matrix, h_condition))
    return deep_merge(
        overlay,
        {
            "rqgm": {
                "eval": {
                    "enabled": True,
                    "kca_conditions": {
                        "b": b_condition,
                        "h": h_condition,
                        "k": k_condition,
                        "reporting_alias": (
                            FULL_KCA_CONDITION_ALIAS
                            if h_condition == "H3_assurance_full_certification"
                            and k_condition == "K3_capability_binding_enforced"
                            else None
                        ),
                    },
                }
            }
        },
    )


def evaluation_condition_overlay(matrix: dict, condition_id: str) -> dict:
    from ari.rqgm.evaluation.conditions import condition_overlay

    if "__" not in str(condition_id):
        return condition_overlay(matrix, condition_id)
    b_condition, h_condition, k_condition = parse_factorial_condition_id(condition_id)
    return factorial_condition_overlay(
        matrix,
        b_condition=b_condition,
        h_condition=h_condition,
        k_condition=k_condition,
    )


__all__ = [
    "ASSURANCE_CONDITION_IDS",
    "FULL_KCA_CONDITION_ALIAS",
    "KNOWLEDGE_CAPABILITY_CONDITION_IDS",
    "assurance_condition_overlay",
    "evaluation_condition_overlay",
    "expand_assurance_condition",
    "expand_knowledge_capability_condition",
    "factorial_condition_id",
    "factorial_condition_overlay",
    "knowledge_capability_condition_overlay",
    "parse_factorial_condition_id",
]
