"""Deterministic diagnostic for one Capability Provider substitution.

This module invokes the production binder twice; it does not introduce a
second selection algorithm and it never changes a persisted Binding Lock.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from ari.capability_binding.models import (
    CapabilityBindingRequestV1,
    CapabilityProvisionV1,
)
from ari.capability_binding.resolver import bind_capabilities
from ari.protocols.integrity import (
    DigestBoundModel,
    SHA256_DIGEST_PATTERN,
    StrictModel,
    canonical_digest,
)


# Reserved identity for the stand-in offered by the abstraction probe.  It is
# never a Provider: it exists only inside a diagnostic request and cannot be
# reached from a persisted catalog, lock, or run.
SYNTHETIC_SUBSTITUTE_PROVIDER_ID = "ari.provider.synthetic-substitute"


class ProviderExecutionObservationV1(StrictModel):
    provider_id: str
    tool_ref: str
    capability_ref: str
    invocation_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    result_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    result_schema: str
    status: Literal["success", "error"]
    source_record_count: int = Field(ge=0)
    source_identity_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class CapabilityProviderSubstitutionReportV1(DigestBoundModel):
    _digest_field = "report_digest"

    schema_version: Literal["ari.capability-provider-substitution-report/v1"] = (
        "ari.capability-provider-substitution-report/v1"
    )
    capability_ref: str
    capability_contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    primary_provider_id: str
    baseline_request_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    baseline_lock_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    primary_tool_ref: str | None = None
    disabled_primary_tool_refs: tuple[str, ...]
    replacement_request_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    replacement_lock_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    replacement_provider_id: str | None = None
    replacement_tool_ref: str | None = None
    binding_status: Literal["passed", "unsatisfied", "invalid"]
    binding_deterministic: bool
    binding_reason_codes: tuple[str, ...]
    execution_status: Literal["passed", "failed", "not_measured"]
    execution_observations: tuple[ProviderExecutionObservationV1, ...]
    report_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @field_validator("execution_observations")
    @classmethod
    def _ordered_observations(
        cls, values: tuple[ProviderExecutionObservationV1, ...]
    ) -> tuple[ProviderExecutionObservationV1, ...]:
        keys = [(item.provider_id, item.tool_ref) for item in values]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("execution observations must be uniquely sorted")
        return values


def _audit_request(
    request: CapabilityBindingRequestV1, **updates
) -> CapabilityBindingRequestV1:
    payload = request.model_dump(mode="python")
    payload.pop("request_digest", None)
    payload["mode"] = "audit"
    payload.update(updates)
    return CapabilityBindingRequestV1.create(**payload)


def synthetic_substitute_provision(
    provision: CapabilityProvisionV1,
) -> CapabilityProvisionV1:
    """Re-offer one provision under a reserved non-incumbent identity.

    Everything the capability contract fixes is preserved -- contract digest,
    side-effect class, context requirement, environment requirements, resource
    type, permissions, roles, phases.  Only the Provider identity and the tool
    reference change.  A requirement that binds to the incumbent but not to
    this stand-in is tied to that Provider rather than to the capability, which
    is the only thing the abstraction probe is entitled to conclude.
    """

    payload = provision.model_dump(mode="python")
    payload.pop("provision_digest", None)
    payload.update(
        provider_id=SYNTHETIC_SUBSTITUTE_PROVIDER_ID,
        provider_identity_digest=canonical_digest(
            {"synthetic_substitute_for": provision.provider_identity_digest}
        ),
        tool_ref=f"{SYNTHETIC_SUBSTITUTE_PROVIDER_ID}/{provision.tool_ref}",
        subject_tool_ref=None,
        dispatch_tool_ref=None,
        nested_source_lock_digests=(),
    )
    return CapabilityProvisionV1.create(**payload)


class CapabilityAbstractionReportV1(DigestBoundModel):
    """Whether one Skill's requirements survive losing their incumbent.

    This is not portability evidence about a Provider ecosystem: no second
    implementation is executed and none is claimed.  It answers the narrower,
    artifact-level question of whether the requirement set names a capability
    or a Provider.
    """

    _digest_field = "report_digest"

    schema_version: Literal["ari.capability-abstraction-report/v1"] = (
        "ari.capability-abstraction-report/v1"
    )
    incumbent_provider_id: str
    synthetic_provider_id: Literal[SYNTHETIC_SUBSTITUTE_PROVIDER_ID] = (
        SYNTHETIC_SUBSTITUTE_PROVIDER_ID
    )
    baseline_request_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    baseline_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    substituted_request_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    substituted_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    disabled_incumbent_tool_refs: tuple[str, ...]
    covered_capability_refs: tuple[str, ...]
    provider_bound_capability_refs: tuple[str, ...]
    status: Literal["passed", "failed", "vacuous"]
    deterministic: bool
    report_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @field_validator(
        "disabled_incumbent_tool_refs",
        "covered_capability_refs",
        "provider_bound_capability_refs",
    )
    @classmethod
    def _sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("abstraction report values must be unique and sorted")
        return value


def probe_capability_abstraction(
    request: CapabilityBindingRequestV1,
    *,
    incumbent_provider_id: str,
) -> CapabilityAbstractionReportV1:
    """Disable the incumbent, offer the same contracts, and re-run the binder.

    Only capabilities the incumbent actually won in the baseline are judged:
    a capability that never bound cannot demonstrate anything about Provider
    independence, and reading it as a failure would re-import the environment
    into an artifact-level gate.
    """

    baseline_request = _audit_request(request)
    baseline_a, _ = bind_capabilities(baseline_request)
    baseline_b, _ = bind_capabilities(baseline_request)
    deterministic = baseline_a.model_dump_json() == baseline_b.model_dump_json()
    incumbent_refs = {
        item.capability_ref
        for item in baseline_a.bindings
        if item.provider_id == incumbent_provider_id
    }
    disabled = tuple(
        sorted(
            {
                item.tool_ref
                for item in request.provisions
                if item.provider_id == incumbent_provider_id
            }
        )
    )
    substitutes = tuple(
        synthetic_substitute_provision(item)
        for item in request.provisions
        if item.provider_id == incumbent_provider_id
    )
    substituted_request = _audit_request(
        request,
        provisions=tuple(request.provisions) + substitutes,
        available_tool_refs=tuple(
            sorted(
                set(request.available_tool_refs)
                | {item.tool_ref for item in substitutes}
            )
        ),
        user_disabled_tools=tuple(
            sorted(set(request.user_disabled_tools) | set(disabled))
        ),
    )
    substituted_a, _ = bind_capabilities(substituted_request)
    substituted_b, _ = bind_capabilities(substituted_request)
    deterministic = deterministic and (
        substituted_a.model_dump_json() == substituted_b.model_dump_json()
    )
    rebound = {item.capability_ref for item in substituted_a.bindings}
    covered = tuple(sorted(incumbent_refs & rebound))
    lost = tuple(sorted(incumbent_refs - rebound))
    if not incumbent_refs:
        status = "vacuous"
    elif lost:
        status = "failed"
    else:
        status = "passed"
    return CapabilityAbstractionReportV1.create(
        incumbent_provider_id=incumbent_provider_id,
        baseline_request_digest=baseline_request.request_digest,
        baseline_lock_digest=baseline_a.lock_digest,
        substituted_request_digest=substituted_request.request_digest,
        substituted_lock_digest=substituted_a.lock_digest,
        disabled_incumbent_tool_refs=disabled,
        covered_capability_refs=covered,
        provider_bound_capability_refs=lost,
        status=status,
        deterministic=deterministic,
    )


def _binding_for(lock, capability_ref: str):
    return next(
        (item for item in lock.bindings if item.capability_ref == capability_ref),
        None,
    )


def _provider_rejection_codes(
    report,
    request: CapabilityBindingRequestV1,
    *,
    capability_ref: str,
    provider_id: str,
) -> tuple[str, ...]:
    provision_digests = {
        item.provision_digest
        for item in request.provisions
        if item.capability_ref == capability_ref and item.provider_id == provider_id
    }
    return tuple(
        sorted(
            {
                code
                for item in report.rejected_candidates
                if item.provision_digest in provision_digests
                for code in item.reason_codes
            }
        )
    )


def _execution_status(
    observations: tuple[ProviderExecutionObservationV1, ...],
    *,
    capability_ref: str,
    primary_provider_id: str,
    replacement_provider_id: str | None,
) -> Literal["passed", "failed", "not_measured"]:
    if not observations:
        return "not_measured"
    alternatives = {
        item.provider_id for item in observations if item.provider_id != primary_provider_id
    }
    replacement_id = replacement_provider_id
    if replacement_id is None and len(alternatives) == 1:
        replacement_id = next(iter(alternatives))
    by_provider = {item.provider_id: item for item in observations}
    required = (
        by_provider.get(primary_provider_id),
        by_provider.get(replacement_id or ""),
    )
    if all(
        item is not None
        and item.status == "success"
        and item.capability_ref == capability_ref
        for item in required
    ) and len({item.result_schema for item in required if item is not None}) == 1:
        return "passed"
    return "failed"


def probe_provider_substitution(
    request: CapabilityBindingRequestV1,
    *,
    capability_ref: str,
    primary_provider_id: str,
    execution_observations: tuple[ProviderExecutionObservationV1, ...] = (),
) -> CapabilityProviderSubstitutionReportV1:
    """Disable one Provider's exact tools and re-run the production binder."""

    matching_requirements = tuple(
        item for item in request.requirements if item.capability_ref == capability_ref
    )
    disabled = tuple(
        sorted(
            {
                item.tool_ref
                for item in request.provisions
                if item.provider_id == primary_provider_id
            }
        )
    )
    base_values = {
        "capability_ref": capability_ref,
        "capability_contract_digest": (
            matching_requirements[0].capability_contract_digest
            if len(matching_requirements) == 1
            else "sha256:" + "0" * 64
        ),
        "primary_provider_id": primary_provider_id,
        "baseline_request_digest": request.request_digest,
        "disabled_primary_tool_refs": disabled,
        "execution_observations": tuple(
            sorted(
                execution_observations,
                key=lambda item: (item.provider_id, item.tool_ref),
            )
        ),
    }
    if len(matching_requirements) != 1 or not disabled:
        return CapabilityProviderSubstitutionReportV1.create(
            **base_values,
            binding_status="invalid",
            binding_deterministic=False,
            binding_reason_codes=(
                (
                    "requirement_not_unique"
                    if len(matching_requirements) != 1
                    else "primary_provider_absent"
                ),
            ),
            execution_status="not_measured",
        )

    baseline_request = _audit_request(request)
    base_values["baseline_request_digest"] = baseline_request.request_digest
    baseline_a, baseline_report = bind_capabilities(baseline_request)
    baseline_b, _ = bind_capabilities(baseline_request)
    baseline = _binding_for(baseline_a, capability_ref)
    deterministic = baseline_a.model_dump_json() == baseline_b.model_dump_json()
    if baseline is None or baseline.provider_id != primary_provider_id:
        unsatisfied = next(
            (
                item
                for item in baseline_a.unsatisfied
                if item.capability_ref == capability_ref
            ),
            None,
        )
        reasons = _provider_rejection_codes(
            baseline_report,
            baseline_request,
            capability_ref=capability_ref,
            provider_id=primary_provider_id,
        ) or (
            unsatisfied.rejection_codes
            if unsatisfied is not None
            else ("primary_provider_not_selected",)
        )
        primary_tool = next(
            (
                item.tool_ref
                for item in request.provisions
                if item.provider_id == primary_provider_id
                and item.capability_ref == capability_ref
            ),
            None,
        )
        replacement_provider = (
            baseline.provider_id
            if baseline is not None and baseline.provider_id != primary_provider_id
            else None
        )
        return CapabilityProviderSubstitutionReportV1.create(
            **base_values,
            baseline_lock_digest=baseline_a.lock_digest,
            primary_tool_ref=primary_tool,
            replacement_provider_id=replacement_provider,
            replacement_tool_ref=(
                baseline.tool_ref if replacement_provider is not None else None
            ),
            binding_status="unsatisfied",
            binding_deterministic=deterministic,
            binding_reason_codes=tuple(sorted(reasons)),
            execution_status=_execution_status(
                execution_observations,
                capability_ref=capability_ref,
                primary_provider_id=primary_provider_id,
                replacement_provider_id=replacement_provider,
            ),
        )

    replacement_request = _audit_request(
        request,
        user_disabled_tools=tuple(
            sorted(set(request.user_disabled_tools) | set(disabled))
        ),
    )
    replacement_a, _ = bind_capabilities(replacement_request)
    replacement_b, _ = bind_capabilities(replacement_request)
    replacement = _binding_for(replacement_a, capability_ref)
    deterministic = deterministic and (
        replacement_a.model_dump_json() == replacement_b.model_dump_json()
    )
    if replacement is None or replacement.provider_id == primary_provider_id:
        unsatisfied = next(
            (
                item
                for item in replacement_a.unsatisfied
                if item.capability_ref == capability_ref
            ),
            None,
        )
        reasons = (
            unsatisfied.rejection_codes
            if unsatisfied is not None
            else ("replacement_provider_not_distinct",)
        )
        return CapabilityProviderSubstitutionReportV1.create(
            **base_values,
            baseline_lock_digest=baseline_a.lock_digest,
            primary_tool_ref=baseline.tool_ref,
            replacement_request_digest=replacement_request.request_digest,
            replacement_lock_digest=replacement_a.lock_digest,
            binding_status="unsatisfied",
            binding_deterministic=deterministic,
            binding_reason_codes=tuple(sorted(reasons)),
            execution_status="not_measured",
        )

    execution_status = _execution_status(
        execution_observations,
        capability_ref=capability_ref,
        primary_provider_id=primary_provider_id,
        replacement_provider_id=replacement.provider_id,
    )
    return CapabilityProviderSubstitutionReportV1.create(
        **base_values,
        baseline_lock_digest=baseline_a.lock_digest,
        primary_tool_ref=baseline.tool_ref,
        replacement_request_digest=replacement_request.request_digest,
        replacement_lock_digest=replacement_a.lock_digest,
        replacement_provider_id=replacement.provider_id,
        replacement_tool_ref=replacement.tool_ref,
        binding_status="passed",
        binding_deterministic=deterministic,
        binding_reason_codes=(),
        execution_status=execution_status,
    )


__all__ = [
    "CapabilityAbstractionReportV1",
    "CapabilityProviderSubstitutionReportV1",
    "ProviderExecutionObservationV1",
    "SYNTHETIC_SUBSTITUTE_PROVIDER_ID",
    "probe_capability_abstraction",
    "probe_provider_substitution",
    "synthetic_substitute_provision",
]
