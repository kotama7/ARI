"""Verification Contract admission and monotonic requirement union."""

from __future__ import annotations

from collections import defaultdict

from ari.assurance.models import (
    VerificationContractV1,
    VerificationRequirementV1,
)
from ari.protocols.scientific_requirements import EvaluationObligationV1


_TIER_RANK = {"screen": 0, "validate": 1, "certify": 2}


def _scope_key(requirement: VerificationRequirementV1) -> tuple:
    return tuple((key, values) for key, values in requirement.scope.values.items())


def union_verification_requirements(
    requirements: tuple[VerificationRequirementV1, ...],
) -> tuple[VerificationRequirementV1, ...]:
    """Union methods/sources and retain the strongest tier; never weaken."""

    groups: dict[tuple, list[VerificationRequirementV1]] = defaultdict(list)
    tolerance_by_property: dict[tuple[str, str, tuple], set[str]] = defaultdict(set)
    for item in requirements:
        scope = _scope_key(item)
        tolerance_by_property[(item.property_id, item.target_kind, scope)].add(
            item.tolerance_policy_digest
        )
        groups[
            (
                item.property_id,
                item.target_kind,
                scope,
                item.tolerance_policy_ref,
                item.tolerance_policy_digest,
                item.independence_requirement,
                item.determinism_requirement,
                item.required_verdict,
                item.failure_policy,
            )
        ].append(item)
    conflicts = [key for key, digests in tolerance_by_property.items() if len(digests) > 1]
    if conflicts:
        raise ValueError("contradictory tolerance policies for one verification scope")
    merged: list[VerificationRequirementV1] = []
    for items in groups.values():
        first = items[0]
        tier = max(items, key=lambda item: _TIER_RANK[item.required_tier]).required_tier
        merged.append(
            VerificationRequirementV1.create(
                property_id=first.property_id,
                target_kind=first.target_kind,
                required_methods=tuple(
                    sorted({method for item in items for method in item.required_methods})
                ),
                required_tier=tier,
                required_verdict=first.required_verdict,
                failure_policy=first.failure_policy,
                scope=first.scope,
                tolerance_policy_ref=first.tolerance_policy_ref,
                tolerance_policy_digest=first.tolerance_policy_digest,
                independence_requirement=first.independence_requirement,
                determinism_requirement=first.determinism_requirement,
                source_requirement_refs=tuple(
                    sorted({ref for item in items for ref in item.source_requirement_refs})
                ),
            )
        )
    return tuple(sorted(merged, key=lambda item: item.requirement_digest))


def obligations_to_requirements(
    *,
    obligations: tuple[EvaluationObligationV1, ...],
    defaults_by_property: dict[str, VerificationRequirementV1],
) -> tuple[VerificationRequirementV1, ...]:
    """Translate only properties/methods; Harness IDs are not accepted input."""

    converted: list[VerificationRequirementV1] = []
    for obligation in obligations:
        baseline = defaults_by_property.get(obligation.property_id)
        if baseline is None:
            raise ValueError(f"no admitted Verification template for {obligation.property_id}")
        scope = baseline.scope
        if obligation.scope:
            from ari.assurance.models import VerificationScopeV1

            scope = VerificationScopeV1(values=obligation.scope)
        methods = tuple(sorted(set(baseline.required_methods) | set(obligation.required_methods)))
        tier = (
            obligation.required_tier
            if _TIER_RANK[obligation.required_tier] > _TIER_RANK[baseline.required_tier]
            else baseline.required_tier
        )
        source = (
            f"knowledge:{obligation.source_skill_digest}"
            if obligation.source_skill_digest
            else "knowledge:unbound"
        )
        converted.append(
            VerificationRequirementV1.create(
                **baseline.model_dump(
                    mode="python",
                    exclude={
                        "requirement_digest",
                        "required_methods",
                        "required_tier",
                        "scope",
                        "source_requirement_refs",
                    },
                ),
                required_methods=methods,
                required_tier=tier,
                scope=scope,
                source_requirement_refs=tuple(
                    sorted(set(baseline.source_requirement_refs) | {source})
                ),
            )
        )
    return tuple(converted)


def mint_verification_contract(
    *,
    run_id: str,
    research_contract_digest: str,
    research_requirements: tuple[VerificationRequirementV1, ...],
    knowledge_requirements: tuple[VerificationRequirementV1, ...],
    baseline_knowledge_obligation_refs: tuple[str, ...],
    admission_confidence: float,
    human_review_identity: str | None,
    property_vocabulary_digest: str,
) -> VerificationContractV1:
    return VerificationContractV1.create(
        run_id=run_id,
        research_contract_digest=research_contract_digest,
        requirements=union_verification_requirements(
            (*research_requirements, *knowledge_requirements)
        ),
        baseline_knowledge_obligation_refs=tuple(
            sorted(set(baseline_knowledge_obligation_refs))
        ),
        admission_confidence=admission_confidence,
        human_review_identity=human_review_identity,
        property_vocabulary_digest=property_vocabulary_digest,
    )


def assert_monotonic_requirement_revision(
    baseline: tuple[VerificationRequirementV1, ...],
    revised: tuple[VerificationRequirementV1, ...],
) -> None:
    new_by_scope = {
        (item.property_id, item.target_kind, _scope_key(item)): item for item in revised
    }
    for old in baseline:
        new = new_by_scope.get((old.property_id, old.target_kind, _scope_key(old)))
        if new is None:
            raise ValueError("Verification revision removed a required property")
        if _TIER_RANK[new.required_tier] < _TIER_RANK[old.required_tier]:
            raise ValueError("Verification revision downgraded assurance tier")
        if not set(old.required_methods).issubset(new.required_methods):
            raise ValueError("Verification revision removed a required method")
        if new.tolerance_policy_digest != old.tolerance_policy_digest:
            raise ValueError("Verification revision changed tolerance policy")
        if new.required_verdict != old.required_verdict:
            raise ValueError("Verification revision changed required verdict")


__all__ = [
    "assert_monotonic_requirement_revision",
    "mint_verification_contract",
    "obligations_to_requirements",
    "union_verification_requirements",
]
