"""Deterministic diagnostic for one Capability Provider substitution.

This module invokes the production binder twice; it does not introduce a
second selection algorithm and it never changes a persisted Binding Lock.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from ari.capability_binding.models import CapabilityBindingRequestV1
from ari.capability_binding.resolver import bind_capabilities
from ari.protocols.integrity import (
    DigestBoundModel,
    SHA256_DIGEST_PATTERN,
    StrictModel,
)


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
    "CapabilityProviderSubstitutionReportV1",
    "ProviderExecutionObservationV1",
    "probe_provider_substitution",
]
