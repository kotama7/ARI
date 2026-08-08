"""Digest-bound Verification Contract, Harness, lock, and Attestation models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ari.execution import ExecutionRequestV1, WorkspaceRefV1
from ari.protocols.integrity import (
    DigestBoundModel,
    FULL_GIT_COMMIT_PATTERN,
    SHA256_DIGEST_PATTERN,
    StrictModel,
)
from ari.protocols.scientific_requirements import AssuranceTier
from ari.research_contract import ResearchArtifactRefV1
from ari.assurance.registration_models import (
    HarnessPromotionApprovalV1,  # noqa: F401 -- compatibility re-export
    HarnessRegistrationEvidenceV1,  # noqa: F401 -- compatibility re-export
    HarnessRegistrationGateV1,  # noqa: F401 -- compatibility re-export
    HarnessRegistrationReportV1,  # noqa: F401 -- compatibility re-export
)


HarnessKind = Literal["benchmark", "artifact_verifier", "reproduction", "claim_verifier"]
HarnessStatus = Literal["candidate", "verified", "deprecated", "revoked"]
HarnessVerdict = Literal["pass", "fail", "inconclusive", "infrastructure_error", "tampered"]
RequiredVerdict = Literal["pass"]
ScorerDeterminism = Literal["deterministic", "seeded", "nondeterministic"]

_TIER_RANK = {"screen": 0, "validate": 1, "certify": 2}


def _canonical_values(value: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    normalized: dict[str, tuple[str, ...]] = {}
    for key, items in sorted(value.items()):
        name = key.strip()
        values = tuple(sorted({item.strip() for item in items if item.strip()}))
        if not name or len(values) != len(items):
            raise ValueError("scope keys/values must be non-empty and unique")
        normalized[name] = values
    return normalized


class VerificationScopeV1(StrictModel):
    values: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    @field_validator("values")
    @classmethod
    def _values(cls, value: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
        return _canonical_values(value)

    def is_covered_by(self, supported: "VerificationScopeV1") -> bool:
        for key, required in self.values.items():
            available = set(supported.values.get(key, ()))
            if available and not set(required).issubset(available):
                return False
            if not available and required:
                return False
        return True


class VerificationRequirementV1(DigestBoundModel):
    _digest_field = "requirement_digest"

    schema_version: Literal["ari.verification-requirement/v1"] = (
        "ari.verification-requirement/v1"
    )
    property_id: str
    target_kind: str
    required_methods: tuple[str, ...] = Field(min_length=1)
    required_tier: AssuranceTier
    required_verdict: RequiredVerdict = "pass"
    failure_policy: Literal[
        "exclude-from-scientific-frontier",
        "block-publication",
        "record-only",
    ]
    scope: VerificationScopeV1
    tolerance_policy_ref: str
    tolerance_policy_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    independence_requirement: Literal["independent", "declared", "none"] = "independent"
    determinism_requirement: Literal["deterministic", "seeded", "declared"] = "deterministic"
    source_requirement_refs: tuple[str, ...] = Field(min_length=1)
    requirement_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @field_validator("required_methods", "source_requirement_refs")
    @classmethod
    def _unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted({item.strip() for item in values if item.strip()}))
        if len(normalized) != len(values):
            raise ValueError("requirement values must be non-empty and unique")
        return normalized


class VerificationRequirementProposalV1(DigestBoundModel):
    _digest_field = "proposal_digest"

    schema_version: Literal["ari.verification-requirement-proposal/v1"] = (
        "ari.verification-requirement-proposal/v1"
    )
    run_id: str
    epoch_id: str
    proposer_component_id: str
    proposer_prompt_hash: str | None
    evidence_refs: tuple[str, ...]
    requested_requirement: VerificationRequirementV1
    parent_verification_contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    active_harness_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    non_authoritative_harness_hint: str | None = None
    proposal_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class AuxiliaryVerificationRequestV1(DigestBoundModel):
    _digest_field = "request_digest"

    schema_version: Literal["ari.auxiliary-verification-request/v1"] = (
        "ari.auxiliary-verification-request/v1"
    )
    run_id: str
    next_epoch_id: str
    proposer_component_id: str
    proposer_prompt_hash: str | None
    requested_requirements: tuple[VerificationRequirementV1, ...]
    parent_verification_contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    active_harness_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    non_authoritative_harness_hints: tuple[str, ...] = Field(default_factory=tuple)
    request_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class VerificationContractV1(DigestBoundModel):
    _digest_field = "contract_digest"

    schema_version: Literal["ari.verification-contract/v1"] = (
        "ari.verification-contract/v1"
    )
    run_id: str
    research_contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    requirements: tuple[VerificationRequirementV1, ...]
    baseline_knowledge_obligation_refs: tuple[str, ...] = Field(default_factory=tuple)
    admission_confidence: float = Field(ge=0, le=1)
    human_review_identity: str | None = None
    property_vocabulary_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _requirements_sorted_and_reviewed(self):
        keys = [item.requirement_digest for item in self.requirements]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("Verification requirements must be uniquely sorted")
        if self.admission_confidence < 0.8 and not self.human_review_identity:
            raise ValueError("low-confidence Verification Contract requires human review")
        return self


class PinnedHarnessAssetV1(StrictModel):
    revision: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(pattern=SHA256_DIGEST_PATTERN)
    license: str = Field(min_length=1, max_length=512)


class ContainerPinV1(StrictModel):
    reference: str = Field(min_length=1, max_length=2048)
    resolved_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    license: str = Field(min_length=1, max_length=512)


class HarnessPropertyCoverageV1(StrictModel):
    property_id: str
    methods: tuple[str, ...] = Field(min_length=1)
    tiers: tuple[AssuranceTier, ...] = Field(min_length=1)
    scope: VerificationScopeV1
    tolerance_policy_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class HarnessResourceRequirementsV1(StrictModel):
    cpu_cores: int = Field(ge=0)
    memory_bytes: int = Field(ge=0)
    accelerators: int = Field(ge=0)
    disk_bytes: int = Field(ge=0)
    features: tuple[str, ...] = Field(default_factory=tuple)

    def cost_tuple(self) -> tuple[int, int, int, int]:
        return (self.accelerators, self.cpu_cores, self.memory_bytes, self.disk_bytes)


class HarnessManifestV1(DigestBoundModel):
    _digest_field = "manifest_digest"

    schema_version: Literal["ari.harness-manifest/v1"] = "ari.harness-manifest/v1"
    id: str
    version: str
    kind: HarnessKind
    status: HarnessStatus
    description: str
    maintainer: str
    tags: tuple[str, ...]
    subject_types: tuple[str, ...]
    target_kinds: tuple[str, ...]
    accepts_external_target: bool
    supported_languages: tuple[str, ...]
    supported_hardware: tuple[str, ...]
    #: WHERE THE EVIDENCE WAS ESTABLISHED, for a harness whose verdict depends on
    #: it. Registration evidence is established at a PLACEMENT and does not
    #: transfer, exactly as it does not transfer across sizes -- and the size
    #: case was already enforced by the dataset pin while this one was not.
    #:
    #: Measured, same commit and same clean worktree: an exclusive aarch64 node
    #: at 48 threads scored 15/15 with a clean-control spread of 0.0411; an
    #: exclusive x86 node at 64 threads scored 13/15 at 0.1648, where the
    #: instrument does not resolve; a shared login node reached 0.589. Without
    #: this, the first of those attestations covered all three.
    #:
    #: Empty means the harness does not depend on placement -- a deterministic
    #: verifier does not, and pinning one for it would be a claim about
    #: something that cannot vary. A driver that DOES depend on it refuses when
    #: the pin is missing.
    registered_placement: dict[str, Any] = Field(default_factory=dict)
    supported_architectures: tuple[str, ...]
    supported_dtypes: tuple[str, ...]
    supported_domains: tuple[str, ...]
    properties: tuple[HarnessPropertyCoverageV1, ...]
    target_interface_contract: str
    target_interface_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    source_repository: str
    source_full_commit_sha: str = Field(pattern=FULL_GIT_COMMIT_PATTERN)
    implementation_license: str
    dataset: PinnedHarnessAssetV1
    oracle: PinnedHarnessAssetV1
    driver: PinnedHarnessAssetV1
    model: PinnedHarnessAssetV1
    container: ContainerPinV1
    network_policy: Literal["deny", "allowlisted"]
    network_allowlist: tuple[str, ...] = Field(default_factory=tuple)
    credential_policy: Literal["none", "scoped"]
    credential_scope_ids: tuple[str, ...] = Field(default_factory=tuple)
    filesystem_policy: Literal["isolated-readonly-target", "closed-workspace"]
    resources: HarnessResourceRequirementsV1
    timeout_seconds: int = Field(gt=0, le=604_800)
    scorer_determinism: ScorerDeterminism
    nondeterminism_declaration: str
    hidden_test_policy: Literal["none", "verifier-only"]
    oracle_independence: Literal["independent", "declared-dependent"]
    tolerance_policy_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    expected_result_schema: str
    expected_result_schema_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    infrastructure_failure_policy: Literal["separate", "retry-locked-environment"]
    retry_limit: int = Field(ge=0, le=16)
    negative_control_report_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    upstream_parity_report_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    manifest_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _kind_and_security_consistent(self):
        if self.kind == "benchmark" and self.accepts_external_target:
            raise ValueError("benchmark entries cannot claim arbitrary external target coverage")
        if self.network_policy == "deny" and self.network_allowlist:
            raise ValueError("deny network policy cannot carry an allowlist")
        if self.credential_policy == "none" and self.credential_scope_ids:
            raise ValueError("credential-free Harness cannot carry credential scopes")
        if self.scorer_determinism == "deterministic" and self.nondeterminism_declaration != "none":
            raise ValueError("deterministic scorer must declare nondeterminism as none")
        return self


class HarnessCatalogSnapshotV1(DigestBoundModel):
    _digest_field = "snapshot_digest"

    schema_version: Literal["ari.harness-catalog-snapshot/v1"] = (
        "ari.harness-catalog-snapshot/v1"
    )
    catalog_source_revision: str
    property_vocabulary_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    driver_protocol_version: str
    manifests: tuple[HarnessManifestV1, ...]
    registration_report_digests: dict[str, str]
    registration_evidence_digests: dict[str, str]
    promotion_approval_digests: dict[str, str] = Field(default_factory=dict)
    snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _manifests_sorted(self):
        keys = [(item.id, item.version, item.manifest_digest) for item in self.manifests]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("Harness manifests must be uniquely sorted")
        if set(self.registration_report_digests) != {item.id for item in self.manifests}:
            raise ValueError("every Harness requires one registration report")
        if set(self.registration_evidence_digests) != {
            item.id for item in self.manifests
        }:
            raise ValueError("every Harness requires one registration evidence bundle")
        verified = {item.id for item in self.manifests if item.status == "verified"}
        if set(self.promotion_approval_digests) != verified:
            raise ValueError("every verified Harness requires one promotion approval")
        return self


class HarnessRequirementV1(DigestBoundModel):
    _digest_field = "atom_digest"

    schema_version: Literal["ari.harness-requirement/v1"] = (
        "ari.harness-requirement/v1"
    )
    verification_requirement_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    property_id: str
    method: str
    tier: AssuranceTier
    target_kind: str
    scope: VerificationScopeV1
    tolerance_policy_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    independence_requirement: str
    determinism_requirement: str
    source_requirement_refs: tuple[str, ...]
    atom_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class HarnessCoverageV1(StrictModel):
    harness_manifest_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    covered_atom_digests: tuple[str, ...]


class HarnessSuiteV1(DigestBoundModel):
    _digest_field = "suite_digest"

    schema_version: Literal["ari.harness-suite/v1"] = "ari.harness-suite/v1"
    requirements: tuple[HarnessRequirementV1, ...]
    harness_manifest_digests: tuple[str, ...]
    coverage: tuple[HarnessCoverageV1, ...]
    covered_atom_digests: tuple[str, ...]
    unsatisfied_atom_digests: tuple[str, ...] = Field(default_factory=tuple)
    aggregate_resource_cost: tuple[int, int, int, int]
    verification_environment_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    resolver_objective: tuple[Any, ...]
    suite_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class LockedHarnessV1(StrictModel):
    harness_id: str
    version: str
    kind: HarnessKind
    manifest_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    dataset_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    oracle_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    driver_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    container_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    result_schema_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    tolerance_policy_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    covered_atom_digests: tuple[str, ...]


class BaselineHarnessLockV1(DigestBoundModel):
    _digest_field = "lock_digest"

    schema_version: Literal["ari.baseline-harness-lock/v1"] = (
        "ari.baseline-harness-lock/v1"
    )
    run_id: str
    research_contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    verification_contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    harness_catalog_snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    verification_environment_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    oracle_bundle_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    suite_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    requirements: tuple[HarnessRequirementV1, ...]
    unsatisfied_atom_digests: tuple[str, ...] = Field(default_factory=tuple)
    harnesses: tuple[LockedHarnessV1, ...]
    coverage_proof_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    producer_component_id: Literal["harness_resolver_v1"] = "harness_resolver_v1"
    prompt_hash: None = None
    lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class HarnessLockRevisionV1(DigestBoundModel):
    _digest_field = "revision_digest"

    schema_version: Literal["ari.harness-lock-revision/v1"] = (
        "ari.harness-lock-revision/v1"
    )
    run_id: str
    next_epoch_id: str
    parent_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    baseline_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    added_requirement_refs: tuple[str, ...]
    added_or_strengthened_harnesses: tuple[LockedHarnessV1, ...]
    active_harnesses: tuple[LockedHarnessV1, ...]
    coverage_proof_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    revision_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class HarnessRunRequestV1(DigestBoundModel):
    _digest_field = "request_digest"

    schema_version: Literal["ari.harness-run-request/v1"] = (
        "ari.harness-run-request/v1"
    )
    run_id: str
    node_id: str
    epoch_id: str
    active_harness_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    harness: LockedHarnessV1
    target_workspace: WorkspaceRefV1
    target_artifact: ResearchArtifactRefV1
    target_logical_name: str
    target_kind: str
    target_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    property_atoms: tuple[HarnessRequirementV1, ...]
    execution_request: ExecutionRequestV1
    attempt_id: str
    retry_index: int = Field(ge=0)
    expected_result_schema: str
    request_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _target_identity_matches(self):
        if self.target_artifact.digest != self.target_digest:
            raise ValueError("Harness target artifact digest mismatch")
        if self.target_artifact.logical_name != self.target_logical_name:
            raise ValueError("Harness target logical name mismatch")
        if self.execution_request.input_digests.get(self.target_logical_name) != self.target_digest:
            raise ValueError("ExecutionRequest does not bind the Harness target")
        return self


class HarnessTargetDeclarationV1(DigestBoundModel):
    """Node-authored pointer to a target; it is not evidence or authority."""

    _digest_field = "declaration_digest"

    schema_version: Literal["ari.harness-target-declaration/v1"] = (
        "ari.harness-target-declaration/v1"
    )
    logical_name: str
    target_kind: str
    subject_type: str
    language: str
    hardware: str
    architecture: str
    dtype: str
    interface_contract: str
    target_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    declaration_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class HarnessPropertyResultV1(StrictModel):
    property_id: str
    method: str
    tier: AssuranceTier
    tested_scope: VerificationScopeV1
    verdict: HarnessVerdict
    measurements: dict[str, Any] = Field(default_factory=dict)
    tolerance_evidence: dict[str, Any] = Field(default_factory=dict)
    oracle_comparison: dict[str, Any] = Field(default_factory=dict)
    covered_atom_digests: tuple[str, ...]
    evidence_artifact_refs: tuple[ResearchArtifactRefV1, ...]


class NormalizedHarnessResultV1(StrictModel):
    """Driver-neutral result consumed by the fixed verifier."""

    schema_version: Literal["ari.normalized-harness-result/v1"] = (
        "ari.normalized-harness-result/v1"
    )
    verdict: HarnessVerdict
    property_results: tuple[HarnessPropertyResultV1, ...]
    evidence_artifact_refs: tuple[ResearchArtifactRefV1, ...]
    infrastructure_status: Literal["ready", "failed", "degraded"]
    nondeterminism_observations: tuple[str, ...] = Field(default_factory=tuple)


class HarnessAttestationV1(DigestBoundModel):
    _digest_field = "attestation_digest"

    schema_version: Literal["ari.harness-attestation/v1"] = (
        "ari.harness-attestation/v1"
    )
    run_id: str
    node_id: str
    epoch_id: str
    producer_component_id: Literal["fixed_verifier_v1"] = "fixed_verifier_v1"
    producer_prompt_hash: None = None
    producer_epoch_id: str
    research_contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    verification_contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    knowledge_skill_use_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    capability_binding_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    baseline_harness_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    active_harness_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    harness_manifest_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    driver_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    oracle_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    dataset_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    container_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    target_logical_name: str
    target_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    target_kind: str
    execution_identity: str = Field(pattern=SHA256_DIGEST_PATTERN)
    execution_result_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    verdict: HarnessVerdict
    property_results: tuple[HarnessPropertyResultV1, ...]
    evidence_artifact_refs: tuple[ResearchArtifactRefV1, ...]
    infrastructure_status: Literal["ready", "failed", "degraded"]
    nondeterminism_declaration: str
    nondeterminism_observations: tuple[str, ...]
    attempt_id: str
    retry_index: int = Field(ge=0)
    attestation_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _aggregate_verdict_consistent(self):
        verdicts = {item.verdict for item in self.property_results}
        if self.verdict == "pass" and verdicts != {"pass"}:
            raise ValueError("pass Attestation requires every property to pass")
        if self.verdict == "fail" and "fail" not in verdicts:
            raise ValueError("fail Attestation requires a failed property")
        if self.verdict == "infrastructure_error" and self.infrastructure_status == "ready":
            raise ValueError("infrastructure error requires non-ready infrastructure")
        return self


__all__ = [name for name in globals() if name.endswith("V1")]
