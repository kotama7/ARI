"""Provider compatibility aliases and immutable semantic projections."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ari.capability_binding.models import CatalogStatus
from ari.config import SkillConfig
from ari.mcp.connection import SkillConnection
from ari.protocols.integrity import (
    DigestBoundModel,
    FULL_GIT_COMMIT_PATTERN,
    SHA256_DIGEST_PATTERN,
    StrictModel,
    canonical_digest,
    normalize_sha256,
)
from ari.skill_lock import SkillsLockV1
from ari.skill_manifest import SkillManifestV1


# Canonical product terminology; these are deliberately identical class objects.
CapabilityProviderManifest = SkillManifestV1
CapabilityProviderConfig = SkillConfig
MCPProviderConnection = SkillConnection
ProviderLock = SkillsLockV1


class ProviderSourceV1(StrictModel):
    repository: str = Field(min_length=1, max_length=4096)
    full_commit_sha: str = Field(pattern=FULL_GIT_COMMIT_PATTERN)
    package_sha256: str = Field(pattern=SHA256_DIGEST_PATTERN)
    license: str = Field(min_length=1, max_length=512)


class ProviderCatalogEntryV1(DigestBoundModel):
    _digest_field = "entry_digest"

    schema_version: Literal["ari.provider-catalog-entry/v1"] = (
        "ari.provider-catalog-entry/v1"
    )
    provider_id: str
    runtime_name: str
    package: str
    package_version: str
    status: CatalogStatus
    maintainer: str
    source: ProviderSourceV1
    manifest_sha256: str = Field(pattern=SHA256_DIGEST_PATTERN)
    registration_report_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    declared_capability_refs_by_tool: dict[str, tuple[str, ...]] = Field(
        default_factory=dict
    )
    nested_source_lock_digests: tuple[str, ...] = Field(default_factory=tuple)
    entry_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class CapabilityProviderIdentityV1(DigestBoundModel):
    """Non-executable semantic view over one existing locked Provider."""

    _digest_field = "identity_digest"

    schema_version: Literal["ari.capability-provider-identity/v1"] = (
        "ari.capability-provider-identity/v1"
    )
    provider_id: str
    package: str
    package_version: str
    source_repository: str
    source_full_commit_sha: str = Field(pattern=FULL_GIT_COMMIT_PATTERN)
    package_sha256: str = Field(pattern=SHA256_DIGEST_PATTERN)
    entrypoint_or_transport: str
    manifest_sha256: str = Field(pattern=SHA256_DIGEST_PATTERN)
    environment_policy_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    credential_scope_identities: tuple[str, ...]
    tool_refs: tuple[str, ...]
    input_schema_sha256_by_tool: dict[str, str]
    output_schema_sha256_by_tool: dict[str, str]
    tool_policy_digest_by_tool: dict[str, str]
    capability_refs_by_tool: dict[str, tuple[str, ...]]
    provider_status: CatalogStatus
    provider_registration_report_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    provider_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    nested_source_lock_digests: tuple[str, ...] = Field(default_factory=tuple)
    identity_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class ProviderCatalogSnapshotV1(DigestBoundModel):
    _digest_field = "snapshot_digest"

    schema_version: Literal["ari.provider-catalog-snapshot/v1"] = (
        "ari.provider-catalog-snapshot/v1"
    )
    catalog_source_revision: str
    ontology_snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    provider_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    providers: tuple[CapabilityProviderIdentityV1, ...]
    nested_source_lock_digests: tuple[str, ...] = Field(default_factory=tuple)
    snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _providers_sorted(self):
        keys = [(item.provider_id, item.package_version) for item in self.providers]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("providers must be uniquely sorted")
        return self


class ProviderRegistrationGateV1(StrictModel):
    gate_id: str
    passed: bool
    evidence_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    detail: str = ""


class CapabilityProviderRegistrationReportV1(DigestBoundModel):
    _digest_field = "report_digest"

    schema_version: Literal["ari.capability-provider-registration-report/v1"] = (
        "ari.capability-provider-registration-report/v1"
    )
    provider_id: str
    manifest_sha256: str = Field(pattern=SHA256_DIGEST_PATTERN)
    gates: tuple[ProviderRegistrationGateV1, ...]
    decision: Literal["candidate", "eligible-for-verified", "rejected"]
    report_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _decision_matches_gates(self):
        complete = len(self.gates) == 15 and all(item.passed for item in self.gates)
        if self.decision == "eligible-for-verified" and not complete:
            raise ValueError("verified eligibility requires all fifteen passing gates")
        return self


def derive_provider_identity(
    entry: ProviderCatalogEntryV1,
    lock: SkillsLockV1,
) -> CapabilityProviderIdentityV1:
    """Derive a semantic identity without changing ``SKILLS.lock`` bytes."""

    locked = next(
        (
            item
            for item in lock.skills
            if item.name == entry.runtime_name and item.package == entry.package
        ),
        None,
    )
    if locked is None:
        raise ValueError("Provider catalog entry is absent from frozen SKILLS.lock")
    if normalize_sha256(locked.manifest_digest) != entry.manifest_sha256:
        raise ValueError("Provider manifest digest differs from catalog entry")
    tools = sorted(
        (item for item in lock.tools if item.skill_name == locked.name),
        key=lambda item: item.tool_ref,
    )
    unknown_classifications = set(entry.declared_capability_refs_by_tool) - {
        item.name for item in tools
    }
    if unknown_classifications:
        raise ValueError("Provider catalog classifies a tool outside the Provider Lock")
    provider_lock_digest = canonical_digest(lock)
    return CapabilityProviderIdentityV1.create(
        provider_id=entry.provider_id,
        package=entry.package,
        package_version=entry.package_version,
        source_repository=entry.source.repository,
        source_full_commit_sha=entry.source.full_commit_sha,
        package_sha256=entry.source.package_sha256,
        entrypoint_or_transport=f"mcp+stdio:{locked.entrypoint}",
        manifest_sha256=normalize_sha256(locked.manifest_digest),
        environment_policy_digest=canonical_digest(
            {
                "policy": locked.environment_policy,
                "required_env": locked.required_env,
                "optional_env": locked.optional_env,
            }
        ),
        credential_scope_identities=tuple(
            sorted(normalize_sha256(item.identity_digest) for item in locked.credential_scopes)
        ),
        tool_refs=tuple(item.tool_ref for item in tools),
        input_schema_sha256_by_tool={
            item.tool_ref: normalize_sha256(item.input_schema_digest) for item in tools
        },
        output_schema_sha256_by_tool={
            item.tool_ref: normalize_sha256(item.output_schema_digest) for item in tools
        },
        tool_policy_digest_by_tool={
            item.tool_ref: canonical_digest(item.policy) for item in tools
        },
        capability_refs_by_tool={
            item.tool_ref: tuple(entry.declared_capability_refs_by_tool.get(item.name, ()))
            for item in tools
            if entry.declared_capability_refs_by_tool.get(item.name)
        },
        provider_status=entry.status,
        provider_registration_report_digest=entry.registration_report_digest,
        provider_lock_digest=provider_lock_digest,
        nested_source_lock_digests=entry.nested_source_lock_digests,
    )


__all__ = [
    "CapabilityProviderConfig",
    "CapabilityProviderIdentityV1",
    "CapabilityProviderManifest",
    "CapabilityProviderRegistrationReportV1",
    "MCPProviderConnection",
    "ProviderCatalogEntryV1",
    "ProviderCatalogSnapshotV1",
    "ProviderLock",
    "ProviderRegistrationGateV1",
    "ProviderSourceV1",
    "derive_provider_identity",
]
