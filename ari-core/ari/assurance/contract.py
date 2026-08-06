"""Mint-once Verification Contract construction from fixed requirements."""

from __future__ import annotations

from pathlib import Path

import yaml

from ari.assurance.models import (
    VerificationContractV1,
    VerificationRequirementV1,
    VerificationScopeV1,
)
from ari.protocols.integrity import canonical_digest


def load_property_vocabulary(path: str | Path) -> tuple[dict[str, tuple[str, ...]], str]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    properties = {
        str(property_id): tuple(sorted(str(method) for method in methods))
        for property_id, methods in dict(raw.get("properties") or {}).items()
    }
    if any(not methods for methods in properties.values()):
        raise ValueError("every assurance property requires a default method")
    return properties, canonical_digest(raw)


def build_verification_contract(
    *,
    run_id: str,
    research_contract,
    knowledge_obligations: tuple,
    property_vocabulary: dict[str, tuple[str, ...]],
    property_vocabulary_digest: str,
    target_kind: str = "workspace-artifact",
) -> VerificationContractV1:
    """Union Research Contract correctness and Knowledge obligations.

    Knowledge content supplies properties/methods only.  It cannot name a
    Harness, delete the Research Contract baseline, or relax its tolerance.
    """

    tolerance_digest = canonical_digest(
        research_contract.metric_contract.tolerance.model_dump(mode="json")
    )
    tolerance_ref = (
        "research-contract:" + research_contract.metric_contract.contract_digest
    )
    requirements: list[VerificationRequirementV1] = []
    metric = research_contract.metric_contract
    if metric.correctness_required:
        property_id = "artifact-correctness"
        methods = property_vocabulary[property_id]
        requirements.append(
            VerificationRequirementV1.create(
                property_id=property_id,
                target_kind=target_kind,
                required_methods=methods,
                required_tier="screen",
                failure_policy="exclude-from-scientific-frontier",
                scope=VerificationScopeV1(values={}),
                tolerance_policy_ref=tolerance_ref,
                tolerance_policy_digest=tolerance_digest,
                source_requirement_refs=(
                    "research-contract:" + research_contract.contract_digest,
                ),
            )
        )
    obligation_refs: list[str] = []
    for obligation in knowledge_obligations:
        if obligation.property_id not in property_vocabulary:
            raise ValueError(
                f"unknown Knowledge evaluation property: {obligation.property_id}"
            )
        methods = obligation.required_methods or property_vocabulary[
            obligation.property_id
        ]
        source = "knowledge:" + str(obligation.source_skill_digest)
        obligation_refs.append(source)
        requirements.append(
            VerificationRequirementV1.create(
                property_id=obligation.property_id,
                target_kind=target_kind,
                required_methods=methods,
                required_tier=obligation.required_tier,
                failure_policy=(
                    "block-publication"
                    if obligation.required_tier == "certify"
                    else "exclude-from-scientific-frontier"
                ),
                scope=VerificationScopeV1(values=obligation.scope),
                tolerance_policy_ref=tolerance_ref,
                tolerance_policy_digest=tolerance_digest,
                source_requirement_refs=(source,),
            )
        )

    # Merge exact property/scope/tier requirements by unioning methods and
    # provenance; this can only add obligations.
    merged: dict[tuple, VerificationRequirementV1] = {}
    for requirement in requirements:
        key = (
            requirement.property_id,
            requirement.target_kind,
            requirement.required_tier,
            canonical_digest(requirement.scope),
            requirement.tolerance_policy_digest,
        )
        previous = merged.get(key)
        if previous is None:
            merged[key] = requirement
            continue
        merged[key] = VerificationRequirementV1.create(
            **previous.model_dump(
                mode="python",
                exclude={
                    "requirement_digest",
                    "required_methods",
                    "source_requirement_refs",
                },
            ),
            required_methods=tuple(
                sorted(set(previous.required_methods) | set(requirement.required_methods))
            ),
            source_requirement_refs=tuple(
                sorted(
                    set(previous.source_requirement_refs)
                    | set(requirement.source_requirement_refs)
                )
            ),
        )
    human_identity = None
    provenance = metric.formula_provenance
    if provenance.source == "human-admission":
        human_identity = provenance.source_digest
    return VerificationContractV1.create(
        run_id=run_id,
        research_contract_digest=research_contract.contract_digest,
        requirements=tuple(
            sorted(merged.values(), key=lambda item: item.requirement_digest)
        ),
        baseline_knowledge_obligation_refs=tuple(sorted(set(obligation_refs))),
        admission_confidence=metric.confidence,
        human_review_identity=human_identity,
        property_vocabulary_digest=property_vocabulary_digest,
    )


__all__ = ["build_verification_contract", "load_property_vocabulary"]
