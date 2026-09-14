"""Constitutional K/C/A resource and authority amendment (Tasks 16–19).

This module is imported by :mod:`ari.rqgm.kernel_rules`; it is not a second
constitution.  Keeping the additive Knowledge/Capability/Assurance table in
one small module makes the authority boundary reviewable while the canonical
constitution hash still covers the fully composed matrix and severity map.
"""

from __future__ import annotations


RESOURCE_CLASSES: tuple[str, ...] = (
    "research_contract",
    "knowledge_catalog",
    "knowledge_skill_bodies",
    "knowledge_lock",
    "capability_ontology",
    "provider_registry",
    "provider_lock",
    "capability_binding",
    "provider_execution",
    "verification_contract",
    "harness_catalog",
    "harness_lock",
    "target_snapshot",
    "harness_execution",
    "harness_attestations",
)

SEVERITY: dict[str, str] = {
    **{f"CK-KNW-{index:03d}": "block" for index in range(1, 16)},
    **{f"CK-CAP-{index:03d}": "block" for index in range(1, 19)},
    **{f"CK-HAR-{index:03d}": "block" for index in range(1, 21)},
}


def extend_capability_matrix(
    matrix: dict[tuple[str, str], frozenset[tuple[str, str]]],
    *,
    fixed_readonly: frozenset[tuple[str, str]],
) -> None:
    """Apply the fixed-procedure and institutional K/C/A grants in place."""

    integrity_resources = frozenset(
        ("read", resource)
        for resource in RESOURCE_CLASSES
        if resource != "provider_execution" and resource != "harness_execution"
    )
    matrix[("constitutional_kernel", "fixed")] = (
        fixed_readonly | integrity_resources
    )
    matrix[("knowledge_binder", "fixed")] = frozenset({
        ("read", "research_contract"),
        ("read", "knowledge_catalog"),
        ("read", "knowledge_skill_bodies"),
        ("read", "capability_ontology"),
        ("invoke", "knowledge_lock"),
    })
    matrix[("capability_binder", "fixed")] = frozenset({
        ("read", "research_contract"),
        ("read", "knowledge_lock"),
        ("read", "capability_ontology"),
        ("read", "provider_registry"),
        ("read", "provider_lock"),
        ("invoke", "capability_binding"),
    })
    matrix[("harness_resolver", "fixed")] = frozenset({
        ("read", "research_contract"),
        ("read", "verification_contract"),
        ("read", "harness_catalog"),
        ("invoke", "harness_lock"),
    })
    matrix[("fixed_verifier", "fixed")] = fixed_readonly | frozenset({
        ("read", "verification_contract"),
        ("read", "harness_lock"),
        ("read", "target_snapshot"),
        ("invoke", "harness_execution"),
    })

    # Institutional actors request and consume fixed outputs; none receives a
    # catalog/lock write. Exact tool authority is enforced separately by the
    # active Capability Binding Lock at the MCP choke point.
    matrix[("generator", "institutional")] |= frozenset({
        ("read", "research_contract"),
        ("read", "knowledge_skill_bodies"),
        ("read", "knowledge_lock"),
        ("read", "capability_binding"),
        ("read", "verification_contract"),
        ("read", "harness_attestations"),
        ("invoke", "provider_execution"),
    })
    matrix[("router", "institutional")] |= frozenset({
        ("read", "research_contract"),
        ("read", "knowledge_catalog"),
    })
    for role in ("reviewer", "paper_reviewer"):
        matrix[(role, "institutional")] |= frozenset({
            ("read", "verification_contract"),
            ("read", "harness_attestations"),
        })


__all__ = ["RESOURCE_CLASSES", "SEVERITY", "extend_capability_matrix"]
