"""Immutable contracts for the Capability ontology and binding locks."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ari.protocols.integrity import (
    DigestBoundModel,
    SHA256_DIGEST_PATTERN,
    StrictModel,
)
from ari.protocols.scientific_requirements import EnvironmentSnapshotV1


CAPABILITY_REF_PATTERN = r"^ari\.[a-z0-9][a-z0-9.-]*/v[1-9][0-9]*$"
CapabilitySideEffect = Literal[
    "read-only",
    "workspace-write",
    "scheduler-submit",
    "external-write",
    "physical-actuation",
]
CapabilityDeterminism = Literal[
    "deterministic", "conditional", "stochastic", "live-data"
]
CapabilityContext = Literal["none", "run", "node"]
CatalogStatus = Literal["candidate", "verified", "deprecated", "revoked"]
BindingMode = Literal["audit", "enforce"]


class CapabilityContractV1(DigestBoundModel):
    """Versioned semantic meaning of one executable capability."""

    _digest_field = "contract_digest"

    schema_version: Literal["ari.capability-contract/v1"] = (
        "ari.capability-contract/v1"
    )
    capability_ref: str = Field(pattern=CAPABILITY_REF_PATTERN)
    contract_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(min_length=1, max_length=4096)
    status_semantics: dict[str, str] = Field(default_factory=dict)
    artifact_rules: tuple[str, ...] = Field(default_factory=tuple)
    side_effect_class: CapabilitySideEffect
    determinism_class: CapabilityDeterminism
    nondeterminism_fields: tuple[str, ...] = Field(default_factory=tuple)
    context_requirement: CapabilityContext = "none"
    required_permissions: tuple[str, ...] = Field(default_factory=tuple)
    credential_scope_class: str = "none"
    resource_type: str = "process"
    environment_requirements: tuple[str, ...] = Field(default_factory=tuple)
    # Required, but legitimately empty: a contract author must still state
    # its rules, and `[]` is the true statement for a capability whose only
    # named rule was retired. No default -- that would let the question
    # vanish from the next contract without anyone deciding it.
    compatibility_rules: tuple[str, ...]
    deprecated: bool = False
    replacement_ref: str | None = Field(default=None, pattern=CAPABILITY_REF_PATTERN)
    contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _version_and_deprecation_consistent(self):
        version = self.capability_ref.rsplit("/", 1)[1]
        if version != self.contract_version:
            raise ValueError("contract_version must equal capability_ref suffix")
        if self.deprecated != (self.replacement_ref is not None):
            raise ValueError("deprecated contracts require exactly one replacement_ref")
        return self


class CapabilityRequirementV1(DigestBoundModel):
    """A semantic capability need; it grants no executable authority."""

    _digest_field = "requirement_digest"

    schema_version: Literal["ari.capability-requirement/v1"] = (
        "ari.capability-requirement/v1"
    )
    capability_ref: str = Field(pattern=CAPABILITY_REF_PATTERN)
    capability_contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    required: bool = True
    semantic_constraints: dict[str, Any] = Field(default_factory=dict)
    roles: tuple[str, ...] = Field(default_factory=tuple)
    phases: tuple[str, ...] = Field(default_factory=tuple)
    context_requirement: CapabilityContext = "none"
    side_effect_ceiling: CapabilitySideEffect = "read-only"
    permitted_credential_scopes: tuple[str, ...] = Field(default_factory=tuple)
    environment_requirements: tuple[str, ...] = Field(default_factory=tuple)
    resource_types: tuple[str, ...] = Field(default_factory=tuple)
    explicit_provider_pin: str | None = None
    explicit_tool_pin: str | None = None
    forbidden_capability_refs: tuple[str, ...] = Field(default_factory=tuple)
    source_requirement_refs: tuple[str, ...] = Field(min_length=1)
    requirement_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @field_validator(
        "roles",
        "phases",
        "permitted_credential_scopes",
        "environment_requirements",
        "resource_types",
        "source_requirement_refs",
    )
    @classmethod
    def _unique_tokens(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted({item.strip() for item in values if item.strip()}))
        if len(normalized) != len(values):
            raise ValueError("requirement lists must be non-empty and unique")
        return normalized

    @field_validator("forbidden_capability_refs")
    @classmethod
    def _valid_forbidden(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted(set(values)))
        if len(normalized) != len(values) or any(
            re.fullmatch(CAPABILITY_REF_PATTERN, value) is None for value in normalized
        ):
            raise ValueError("forbidden refs must be unique canonical capability refs")
        return normalized


class CapabilityProvisionV1(DigestBoundModel):
    """Reviewed semantic projection of one locked Provider tool."""

    _digest_field = "provision_digest"

    schema_version: Literal["ari.capability-provision/v1"] = (
        "ari.capability-provision/v1"
    )
    provider_id: str
    provider_identity_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    provider_status: CatalogStatus
    tool_ref: str
    subject_tool_ref: str | None = None
    dispatch_tool_ref: str | None = None
    # Which dispatch argument names the subject. Without it the authorization
    # view sees only the dispatch tool, so authorizing one reviewed leaf would
    # authorize every leaf the federated catalog holds -- the call carries the
    # leaf in its arguments and nothing would have compared it.
    subject_argument: str | None = None
    # A leaf whose descriptor declares an asynchronous lifecycle is submitted by
    # one call and completed by others. Those are not separate capabilities --
    # polling a job you were authorized to submit adds no authority -- but they
    # are separate tool_refs, and without them an async Capability binds, runs,
    # and its result is unreachable.
    lifecycle_tool_refs: tuple[str, ...] = Field(default_factory=tuple)
    nested_source_lock_digests: tuple[str, ...] = Field(default_factory=tuple)
    declared_capability_ref: str
    capability_ref: str = Field(pattern=CAPABILITY_REF_PATTERN)
    capability_contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    provider_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    manifest_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    input_schema_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    output_schema_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    policy_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    schema_compatibility_evidence_digest: str = Field(
        pattern=SHA256_DIGEST_PATTERN
    )
    side_effect_class: CapabilitySideEffect
    determinism_class: CapabilityDeterminism
    context_requirement: CapabilityContext = "none"
    roles: tuple[str, ...] = Field(default_factory=tuple)
    phases: tuple[str, ...] = Field(default_factory=tuple)
    permissions: tuple[str, ...] = Field(default_factory=tuple)
    credential_scope_ids: tuple[str, ...] = Field(default_factory=tuple)
    environment_requirements: tuple[str, ...] = Field(default_factory=tuple)
    resource_type: str = "process"
    network_class: str = "none"
    reproducibility_grade: Literal["exact", "bounded", "external", "unknown"]
    declared_resource_cost: tuple[int, int, int] = (0, 0, 0)
    registration_report_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    provision_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _nested_route_is_complete(self):
        composite = self.subject_tool_ref is not None or self.dispatch_tool_ref is not None
        if composite and (
            self.subject_tool_ref is None
            or self.dispatch_tool_ref is None
            or not self.subject_argument
            or not self.nested_source_lock_digests
        ):
            raise ValueError(
                "composite provision must bind subject, dispatch, subject argument, and locks"
            )
        return self


class LegacyCapabilityAliasV1(StrictModel):
    declared_ref: str = Field(min_length=1, max_length=256)
    canonical_ref: str = Field(pattern=CAPABILITY_REF_PATTERN)
    rationale: str = Field(min_length=1, max_length=2048)


class CapabilityOntologySnapshotV1(DigestBoundModel):
    _digest_field = "snapshot_digest"

    schema_version: Literal["ari.capability-ontology-snapshot/v1"] = (
        "ari.capability-ontology-snapshot/v1"
    )
    source_revision: str
    property_vocabulary_version: str
    contracts: tuple[CapabilityContractV1, ...]
    legacy_aliases: tuple[LegacyCapabilityAliasV1, ...] = Field(default_factory=tuple)
    snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _unique_sorted(self):
        refs = [item.capability_ref for item in self.contracts]
        aliases = [item.declared_ref for item in self.legacy_aliases]
        if refs != sorted(refs) or len(refs) != len(set(refs)):
            raise ValueError("ontology contracts must be uniquely sorted by ref")
        if aliases != sorted(aliases) or len(aliases) != len(set(aliases)):
            raise ValueError("legacy aliases must be uniquely sorted")
        return self


class CapabilityBindingRequestV1(DigestBoundModel):
    _digest_field = "request_digest"

    schema_version: Literal["ari.capability-binding-request/v1"] = (
        "ari.capability-binding-request/v1"
    )
    run_id: str
    epoch_id: str
    research_contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    knowledge_skill_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    ontology_snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    provider_catalog_snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    provider_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    requirements: tuple[CapabilityRequirementV1, ...]
    provisions: tuple[CapabilityProvisionV1, ...]
    available_tool_refs: tuple[str, ...]
    role: str
    phase: str
    call_context: CapabilityContext
    authorized_capability_refs: tuple[str, ...]
    granted_credential_scopes: tuple[str, ...] = Field(default_factory=tuple)
    forbidden_capability_refs: tuple[str, ...] = Field(default_factory=tuple)
    user_disabled_tools: tuple[str, ...] = Field(default_factory=tuple)
    environment: EnvironmentSnapshotV1
    mode: BindingMode
    request_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @field_validator("requirements")
    @classmethod
    def _sorted_requirements(
        cls, values: tuple[CapabilityRequirementV1, ...]
    ) -> tuple[CapabilityRequirementV1, ...]:
        keys = [item.requirement_digest for item in values]
        if len(keys) != len(set(keys)):
            raise ValueError("binding requirements must be unique")
        return tuple(sorted(values, key=lambda item: item.requirement_digest))

    @field_validator("provisions")
    @classmethod
    def _sorted_provisions(
        cls, values: tuple[CapabilityProvisionV1, ...]
    ) -> tuple[CapabilityProvisionV1, ...]:
        keys = [item.provision_digest for item in values]
        if len(keys) != len(set(keys)):
            raise ValueError("binding provisions must be unique")
        return tuple(sorted(values, key=lambda item: item.provision_digest))

    @field_validator(
        "available_tool_refs",
        "authorized_capability_refs",
        "granted_credential_scopes",
        "forbidden_capability_refs",
        "user_disabled_tools",
    )
    @classmethod
    def _sorted_unique_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted(set(values)))
        if len(normalized) != len(values):
            raise ValueError("binding request lists must be unique")
        return normalized


class CapabilityBindingV1(DigestBoundModel):
    _digest_field = "binding_digest"

    schema_version: Literal["ari.capability-binding/v1"] = "ari.capability-binding/v1"
    capability_ref: str = Field(pattern=CAPABILITY_REF_PATTERN)
    capability_contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    requirement_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    source_requirement_refs: tuple[str, ...]
    provider_id: str
    provider_identity_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    provider_status: CatalogStatus
    tool_ref: str
    subject_tool_ref: str | None = None
    dispatch_tool_ref: str | None = None
    subject_argument: str | None = None
    lifecycle_tool_refs: tuple[str, ...] = Field(default_factory=tuple)
    provider_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    manifest_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    input_schema_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    output_schema_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    policy_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    role: str
    phase: str
    call_context: CapabilityContext
    side_effect_class: CapabilitySideEffect
    credential_scope_ids: tuple[str, ...]
    environment_evidence_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    determinism_class: CapabilityDeterminism
    reproducibility_grade: str
    declared_resource_cost: tuple[int, int, int]
    selection_rank: tuple[Any, ...]
    tie_break_reason: Literal["only-eligible", "deterministic-rank"]
    binding_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class UnsatisfiedCapabilityV1(StrictModel):
    requirement_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    capability_ref: str = Field(pattern=CAPABILITY_REF_PATTERN)
    required: bool
    rejection_codes: tuple[str, ...] = Field(min_length=1)


class CapabilityBindingLockV1(DigestBoundModel):
    _digest_field = "lock_digest"

    schema_version: Literal["ari.capability-binding-lock/v1"] = (
        "ari.capability-binding-lock/v1"
    )
    run_id: str
    epoch_id: str
    request_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    ontology_snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    provider_catalog_snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    provider_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    environment_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    requirements: tuple[CapabilityRequirementV1, ...]
    bindings: tuple[CapabilityBindingV1, ...]
    unsatisfied: tuple[UnsatisfiedCapabilityV1, ...]
    mode: BindingMode
    producer_component_id: Literal["capability_binder_v1"] = "capability_binder_v1"
    prompt_hash: None = None
    lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class CapabilityBindingRevisionV1(DigestBoundModel):
    _digest_field = "revision_digest"

    schema_version: Literal["ari.capability-binding-revision/v1"] = (
        "ari.capability-binding-revision/v1"
    )
    run_id: str
    next_epoch_id: str
    parent_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    baseline_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    added_requirements: tuple[CapabilityRequirementV1, ...]
    added_bindings: tuple[CapabilityBindingV1, ...]
    revision_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class CapabilityCandidateRejectionV1(StrictModel):
    requirement_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    provision_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    reason_codes: tuple[str, ...] = Field(min_length=1)


class CapabilityBindingReportV1(DigestBoundModel):
    _digest_field = "report_digest"

    schema_version: Literal["ari.capability-binding-report/v1"] = (
        "ari.capability-binding-report/v1"
    )
    request_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    rejected_candidates: tuple[CapabilityCandidateRejectionV1, ...]
    report_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


__all__ = [name for name in globals() if name.endswith("V1")]
