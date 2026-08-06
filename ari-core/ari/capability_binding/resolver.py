"""Pure, fail-closed Capability Binder implementation."""

from __future__ import annotations

from typing import Iterable

from ari.capability_binding.models import (
    CapabilityBindingLockV1,
    CapabilityBindingReportV1,
    CapabilityBindingRequestV1,
    CapabilityBindingV1,
    CapabilityCandidateRejectionV1,
    CapabilityProvisionV1,
    CapabilityRequirementV1,
    UnsatisfiedCapabilityV1,
)


class CapabilityBindingError(ValueError):
    """Binding could not produce the authority required by enforce mode."""


_SIDE_EFFECT_RANK = {
    "read-only": 0,
    "workspace-write": 1,
    "scheduler-submit": 2,
    "external-write": 3,
    "physical-actuation": 4,
}
_DETERMINISM_RANK = {
    "deterministic": 0,
    "conditional": 1,
    "stochastic": 2,
    "live-data": 3,
}
_REPRODUCIBILITY_RANK = {"exact": 0, "bounded": 1, "external": 2, "unknown": 3}
_CONTEXT_RANK = {"none": 0, "run": 1, "node": 2}


def _rejection_codes(
    request: CapabilityBindingRequestV1,
    requirement: CapabilityRequirementV1,
    candidate: CapabilityProvisionV1,
) -> tuple[str, ...]:
    """Return the union of independent identity, authority, and environment checks."""

    return tuple(sorted(set(
        _identity_rejection_codes(request, requirement, candidate)
        + _authority_rejection_codes(request, requirement, candidate)
        + _environment_rejection_codes(request, requirement, candidate)
    )))


def _identity_rejection_codes(
    request: CapabilityBindingRequestV1,
    requirement: CapabilityRequirementV1,
    candidate: CapabilityProvisionV1,
) -> list[str]:
    codes: list[str] = []
    if candidate.capability_ref != requirement.capability_ref:
        codes.append("capability_ref_mismatch")
    if candidate.capability_contract_digest != requirement.capability_contract_digest:
        codes.append("capability_contract_mismatch")
    if candidate.provider_status != "verified":
        codes.append("provider_not_verified")
    if candidate.provider_lock_digest != request.provider_lock_digest:
        codes.append("provider_lock_mismatch")
    if candidate.tool_ref not in request.available_tool_refs:
        codes.append("tool_not_in_provider_lock")
    if candidate.tool_ref in request.user_disabled_tools:
        codes.append("tool_disabled")
    if requirement.explicit_provider_pin and candidate.provider_id != requirement.explicit_provider_pin:
        codes.append("provider_pin_mismatch")
    if requirement.explicit_tool_pin and candidate.tool_ref != requirement.explicit_tool_pin:
        codes.append("tool_pin_mismatch")
    return codes


def _authority_rejection_codes(
    request: CapabilityBindingRequestV1,
    requirement: CapabilityRequirementV1,
    candidate: CapabilityProvisionV1,
) -> list[str]:
    codes: list[str] = []
    if requirement.capability_ref not in request.authorized_capability_refs:
        codes.append("role_authority_denied")
    if requirement.roles and request.role not in requirement.roles:
        codes.append("requirement_role_mismatch")
    if candidate.roles and request.role not in candidate.roles:
        codes.append("provider_role_mismatch")
    if requirement.phases and request.phase not in requirement.phases:
        codes.append("requirement_phase_mismatch")
    if candidate.phases and request.phase not in candidate.phases:
        codes.append("provider_phase_mismatch")
    if _CONTEXT_RANK[request.call_context] < _CONTEXT_RANK[requirement.context_requirement]:
        codes.append("call_context_unsatisfied")
    if _CONTEXT_RANK[request.call_context] < _CONTEXT_RANK[candidate.context_requirement]:
        codes.append("provider_context_unsatisfied")
    if _SIDE_EFFECT_RANK[candidate.side_effect_class] > _SIDE_EFFECT_RANK[requirement.side_effect_ceiling]:
        codes.append("side_effect_ceiling_exceeded")
    forbidden = set(request.forbidden_capability_refs) | set(
        requirement.forbidden_capability_refs
    )
    if candidate.capability_ref in forbidden:
        codes.append("forbidden_capability")
    granted = set(request.granted_credential_scopes)
    permitted = set(requirement.permitted_credential_scopes)
    candidate_scopes = set(candidate.credential_scope_ids)
    if not candidate_scopes.issubset(granted):
        codes.append("credential_scope_not_granted")
    if permitted and not candidate_scopes.issubset(permitted):
        codes.append("credential_scope_not_permitted")
    return codes


def _environment_rejection_codes(
    request: CapabilityBindingRequestV1,
    requirement: CapabilityRequirementV1,
    candidate: CapabilityProvisionV1,
) -> list[str]:
    codes: list[str] = []
    features = set(request.environment.features)
    if not set(requirement.environment_requirements).issubset(features):
        codes.append("requirement_environment_mismatch")
    if not set(candidate.environment_requirements).issubset(features):
        codes.append("provider_environment_mismatch")
    if requirement.resource_types and candidate.resource_type not in requirement.resource_types:
        codes.append("resource_type_mismatch")
    if request.environment.resource_types and candidate.resource_type not in request.environment.resource_types:
        codes.append("resource_unavailable")
    return codes


def _rank(
    request: CapabilityBindingRequestV1,
    candidate: CapabilityProvisionV1,
) -> tuple:
    specificity = -(
        int(bool(candidate.roles))
        + int(bool(candidate.phases))
        + int(candidate.context_requirement != "none")
    )
    return (
        0,
        0,
        specificity,
        _SIDE_EFFECT_RANK[candidate.side_effect_class],
        _DETERMINISM_RANK[candidate.determinism_class],
        _REPRODUCIBILITY_RANK[candidate.reproducibility_grade],
        0,
        candidate.declared_resource_cost,
        candidate.tool_ref,
    )


def _binding(
    request: CapabilityBindingRequestV1,
    requirement: CapabilityRequirementV1,
    candidate: CapabilityProvisionV1,
    eligible_count: int,
) -> CapabilityBindingV1:
    rank = _rank(request, candidate)
    return CapabilityBindingV1.create(
        capability_ref=requirement.capability_ref,
        capability_contract_digest=requirement.capability_contract_digest,
        requirement_digest=requirement.requirement_digest,
        source_requirement_refs=requirement.source_requirement_refs,
        provider_id=candidate.provider_id,
        provider_identity_digest=candidate.provider_identity_digest,
        provider_status=candidate.provider_status,
        tool_ref=candidate.tool_ref,
        subject_tool_ref=candidate.subject_tool_ref,
        dispatch_tool_ref=candidate.dispatch_tool_ref,
        provider_lock_digest=candidate.provider_lock_digest,
        manifest_digest=candidate.manifest_digest,
        input_schema_digest=candidate.input_schema_digest,
        output_schema_digest=candidate.output_schema_digest,
        policy_digest=candidate.policy_digest,
        role=request.role,
        phase=request.phase,
        call_context=request.call_context,
        side_effect_class=candidate.side_effect_class,
        credential_scope_ids=candidate.credential_scope_ids,
        environment_evidence_digest=request.environment.identity_digest,
        determinism_class=candidate.determinism_class,
        reproducibility_grade=candidate.reproducibility_grade,
        declared_resource_cost=candidate.declared_resource_cost,
        selection_rank=rank,
        tie_break_reason="only-eligible" if eligible_count == 1 else "deterministic-rank",
    )


def bind_capabilities(
    request: CapabilityBindingRequestV1,
) -> tuple[CapabilityBindingLockV1, CapabilityBindingReportV1]:
    """Bind each exact requirement without discovery, fuzzy matching, or LLMs."""

    bindings: list[CapabilityBindingV1] = []
    unsatisfied: list[UnsatisfiedCapabilityV1] = []
    rejections: list[CapabilityCandidateRejectionV1] = []
    requirements = sorted(
        request.requirements,
        key=lambda item: (not item.required, item.capability_ref, item.requirement_digest),
    )
    candidates = sorted(request.provisions, key=lambda item: item.tool_ref)
    for requirement in requirements:
        eligible: list[CapabilityProvisionV1] = []
        observed_codes: set[str] = set()
        for candidate in candidates:
            if candidate.capability_ref != requirement.capability_ref:
                continue
            codes = _rejection_codes(request, requirement, candidate)
            if codes:
                observed_codes.update(codes)
                rejections.append(
                    CapabilityCandidateRejectionV1(
                        requirement_digest=requirement.requirement_digest,
                        provision_digest=candidate.provision_digest,
                        reason_codes=codes,
                    )
                )
            else:
                eligible.append(candidate)
        if not eligible:
            unsatisfied.append(
                UnsatisfiedCapabilityV1(
                    requirement_digest=requirement.requirement_digest,
                    capability_ref=requirement.capability_ref,
                    required=requirement.required,
                    rejection_codes=tuple(sorted(observed_codes or {"no_candidate"})),
                )
            )
            continue
        eligible.sort(key=lambda item: _rank(request, item))
        bindings.append(_binding(request, requirement, eligible[0], len(eligible)))

    bindings.sort(key=lambda item: (item.capability_ref, item.requirement_digest))
    unsatisfied.sort(key=lambda item: (item.capability_ref, item.requirement_digest))
    lock = CapabilityBindingLockV1.create(
        run_id=request.run_id,
        epoch_id=request.epoch_id,
        request_digest=request.request_digest,
        ontology_snapshot_digest=request.ontology_snapshot_digest,
        provider_catalog_snapshot_digest=request.provider_catalog_snapshot_digest,
        provider_lock_digest=request.provider_lock_digest,
        environment_digest=request.environment.identity_digest,
        requirements=tuple(requirements),
        bindings=tuple(bindings),
        unsatisfied=tuple(unsatisfied),
        mode=request.mode,
    )
    report = CapabilityBindingReportV1.create(
        request_digest=request.request_digest,
        lock_digest=lock.lock_digest,
        rejected_candidates=tuple(
            sorted(
                rejections,
                key=lambda item: (item.requirement_digest, item.provision_digest),
            )
        ),
    )
    if request.mode == "enforce" and any(item.required for item in unsatisfied):
        refs = ", ".join(item.capability_ref for item in unsatisfied if item.required)
        raise CapabilityBindingError(f"required capabilities are unsatisfied: {refs}")
    return lock, report


def bound_tool_refs(lock: CapabilityBindingLockV1) -> frozenset[str]:
    return frozenset(binding.tool_ref for binding in lock.bindings)


def validate_binding_revision(
    baseline: CapabilityBindingLockV1,
    revision_bindings: Iterable[CapabilityBindingV1],
) -> None:
    old = {item.capability_ref: item.tool_ref for item in baseline.bindings}
    for item in revision_bindings:
        previous = old.get(item.capability_ref)
        if previous is not None and previous != item.tool_ref:
            raise CapabilityBindingError("binding revisions cannot rebind existing capability")


__all__ = [
    "CapabilityBindingError",
    "bind_capabilities",
    "bound_tool_refs",
    "validate_binding_revision",
]
