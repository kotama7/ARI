"""Immutable contracts for Knowledge Skill registration, admission, and use."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ari.capability_binding.models import (
    CAPABILITY_REF_PATTERN,
    CapabilityRequirementV1,
)
from ari.protocols.integrity import (
    DigestBoundModel,
    FULL_GIT_COMMIT_PATTERN,
    SHA256_DIGEST_PATTERN,
    Sha256Digest,
    StrictModel,
)
from ari.protocols.scientific_requirements import EvaluationObligationV1


KnowledgeCatalogStatus = Literal["candidate", "verified", "deprecated", "revoked"]
KnowledgeMode = Literal["audit", "enforce"]

_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,255}$"
_VERSION_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$"
_SLOT_RANKS = {
    "scientific-safety": 10,
    "scientific-method": 20,
    "domain-method": 30,
    "execution-strategy": 40,
    "reporting": 50,
}


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value.strip())
    if not value.strip() or "\\" in value or path.is_absolute() or ".." in path.parts:
        raise ValueError("path must be safe and POSIX-relative")
    return path.as_posix()


class KnowledgeSkillSourceV1(StrictModel):
    repository: str = Field(min_length=1, max_length=4096)
    commit: str = Field(pattern=FULL_GIT_COMMIT_PATTERN)
    path: str = Field(min_length=1, max_length=1024)
    body_sha256: str = Field(pattern=SHA256_DIGEST_PATTERN)
    manifest_sha256: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @field_validator("path")
    @classmethod
    def _source_path(cls, value: str) -> str:
        return _safe_relative(value)


class KnowledgeSkillLicenseV1(StrictModel):
    body: str = Field(min_length=1, max_length=512)
    references: str = Field(min_length=1, max_length=512)


class KnowledgeSkillReferenceV1(StrictModel):
    path: str
    sha256: str = Field(pattern=SHA256_DIGEST_PATTERN)
    license: str | None = Field(default=None, min_length=1, max_length=512)

    @field_validator("path")
    @classmethod
    def _reference_path(cls, value: str) -> str:
        normalized = _safe_relative(value)
        if not normalized.startswith("references/"):
            raise ValueError("references must stay under references/")
        return normalized


class KnowledgeSkillApplicabilityV1(StrictModel):
    roles: tuple[str, ...] = Field(min_length=1)
    phases: tuple[str, ...] = Field(min_length=1)
    task_tags: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("roles", "phases", "task_tags")
    @classmethod
    def _unique_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted({item.strip() for item in values if item.strip()}))
        if len(normalized) != len(values):
            raise ValueError("applicability values must be non-empty and unique")
        return normalized


class KnowledgeCapabilityRequirementV1(StrictModel):
    ref: str = Field(pattern=CAPABILITY_REF_PATTERN)
    required: bool = True
    semantic_constraints: dict[str, Any] = Field(default_factory=dict)
    explicit_provider_pin: str | None = None


class KnowledgeCapabilitySetV1(StrictModel):
    capabilities: tuple[KnowledgeCapabilityRequirementV1, ...] = Field(
        default_factory=tuple
    )


class KnowledgeAuthorityCeilingV1(StrictModel):
    side_effects: tuple[
        Literal[
            "read-only",
            "workspace-write",
            "scheduler-submit",
            "external-write",
            "physical-actuation",
        ],
        ...,
    ] = Field(min_length=1)

    @field_validator("side_effects")
    @classmethod
    def _unique_effects(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("authority side effects must be unique")
        return values


class KnowledgeCompositionV1(StrictModel):
    slot: Literal[
        "scientific-safety",
        "scientific-method",
        "domain-method",
        "execution-strategy",
        "reporting",
    ]
    priority: int = Field(ge=-1_000_000, le=1_000_000)
    exclusive: bool = False

    @property
    def slot_rank(self) -> int:
        return _SLOT_RANKS[self.slot]


class KnowledgeSkillRefV1(StrictModel):
    id: str = Field(pattern=_ID_PATTERN)
    version: str = Field(pattern=_VERSION_PATTERN)
    body_sha256: str = Field(pattern=SHA256_DIGEST_PATTERN)
    manifest_sha256: str = Field(pattern=SHA256_DIGEST_PATTERN)


class KnowledgeSkillManifestV1(StrictModel):
    """A Knowledge package contract.  Executable fields are schema errors."""

    schema_version: Literal[1] = 1
    id: str = Field(pattern=_ID_PATTERN)
    version: str = Field(pattern=_VERSION_PATTERN)
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1, max_length=4096)
    status: KnowledgeCatalogStatus
    source: KnowledgeSkillSourceV1
    license: KnowledgeSkillLicenseV1
    references: tuple[KnowledgeSkillReferenceV1, ...] = Field(default_factory=tuple)
    applies_to: KnowledgeSkillApplicabilityV1
    requires: KnowledgeCapabilitySetV1 = Field(default_factory=KnowledgeCapabilitySetV1)
    optional_capabilities: tuple[KnowledgeCapabilityRequirementV1, ...] = Field(
        default_factory=tuple
    )
    evaluation_obligations: tuple[EvaluationObligationV1, ...] = Field(
        default_factory=tuple
    )
    authority_ceiling: KnowledgeAuthorityCeilingV1
    forbidden_capabilities: tuple[str, ...] = Field(default_factory=tuple)
    dependencies: tuple[KnowledgeSkillRefV1, ...] = Field(default_factory=tuple)
    conflicts: tuple[str, ...] = Field(default_factory=tuple)
    composition: KnowledgeCompositionV1

    @field_validator("forbidden_capabilities")
    @classmethod
    def _forbidden_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted(set(values)))
        if len(normalized) != len(values) or any(
            re.fullmatch(CAPABILITY_REF_PATTERN, value) is None for value in normalized
        ):
            raise ValueError("forbidden capabilities must be unique canonical refs")
        return normalized

    @field_validator("conflicts")
    @classmethod
    def _conflict_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted(set(values)))
        if len(normalized) != len(values) or any(
            re.fullmatch(_ID_PATTERN, value) is None for value in normalized
        ):
            raise ValueError("conflicts must be unique Knowledge Skill IDs")
        return normalized

    @model_validator(mode="after")
    def _requirements_are_disjoint(self):
        required = [item.ref for item in self.requires.capabilities]
        optional = [item.ref for item in self.optional_capabilities]
        if len(required) != len(set(required)) or len(optional) != len(set(optional)):
            raise ValueError("capability requirements must be unique")
        if set(required) & set(optional):
            raise ValueError("required and optional capabilities must be disjoint")
        if set(required + optional) & set(self.forbidden_capabilities):
            raise ValueError("required capability cannot also be forbidden")
        if self.id in self.conflicts or any(item.id == self.id for item in self.dependencies):
            raise ValueError("a Knowledge Skill cannot depend on or conflict with itself")
        return self

    def exact_ref(self) -> KnowledgeSkillRefV1:
        return KnowledgeSkillRefV1(
            id=self.id,
            version=self.version,
            body_sha256=self.source.body_sha256,
            manifest_sha256=self.source.manifest_sha256,
        )


class KnowledgeSkillEntryV1(DigestBoundModel):
    _digest_field = "entry_digest"

    schema_version: Literal["ari.knowledge-skill-entry/v1"] = (
        "ari.knowledge-skill-entry/v1"
    )
    manifest: KnowledgeSkillManifestV1
    #: THE KEY THE BODY IS FETCHED BY, so it is a trust anchor and not a label:
    #: whatever this names is what a node's prompt is composed from. It was a
    #: bare ``str`` and accepted "", "a" * 12 and an uppercase digest, while
    #: every producer supplied a full content address -- the same shape as the
    #: sibling on the next line, which had the constraint all along.
    body_store_key: str = Field(pattern=SHA256_DIGEST_PATTERN)
    registration_report_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    importer_version: str
    status: KnowledgeCatalogStatus
    entry_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _initial_status_is_not_weaker_than_source(self):
        # ``manifest.status`` records the source package's status at import.
        # ``entry.status`` is the status frozen into this catalog snapshot.
        # They intentionally diverge after an append-only lifecycle transition;
        # requiring equality made verified/deprecated/revoked snapshots
        # impossible without mutating the immutable source manifest.
        if self.manifest.status == "revoked" and self.status != "revoked":
            raise ValueError("a source-revoked Knowledge Skill cannot be reactivated")
        return self


class KnowledgeSkillCatalogSnapshotV1(DigestBoundModel):
    _digest_field = "snapshot_digest"

    schema_version: Literal["ari.knowledge-skill-catalog-snapshot/v1"] = (
        "ari.knowledge-skill-catalog-snapshot/v1"
    )
    catalog_source_revision: str
    importer_version: str
    entries: tuple[KnowledgeSkillEntryV1, ...]
    snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _entries_sorted(self):
        keys = [
            (item.manifest.id, item.manifest.version, item.manifest.source.body_sha256)
            for item in self.entries
        ]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("catalog entries must be uniquely sorted")
        return self


class KnowledgeSkillSelectionProposalV1(DigestBoundModel):
    _digest_field = "proposal_digest"

    schema_version: Literal["ari.knowledge-skill-selection-proposal/v1"] = (
        "ari.knowledge-skill-selection-proposal/v1"
    )
    run_id: str
    epoch_id: str
    research_contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    proposed: tuple[KnowledgeSkillRefV1, ...]
    # Why every other catalog entry was left out. Without it a proposal of
    # zero is indistinguishable from an empty catalog, and the reason a
    # Skill never reached the Binder is unrecoverable from the artifacts.
    not_proposed: tuple["KnowledgeAdmissionFindingV1", ...] = ()
    scope: Literal["epoch", "node"] = "epoch"
    required: bool = True
    reason: str = Field(min_length=1, max_length=8192)
    router_component_id: str
    router_prompt_hash: str | None
    proposal_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class KnowledgeAdmissionContextV1(DigestBoundModel):
    _digest_field = "context_digest"

    schema_version: Literal["ari.knowledge-admission-context/v1"] = (
        "ari.knowledge-admission-context/v1"
    )
    role: str
    phase: str
    task_tags: tuple[str, ...] = Field(default_factory=tuple)
    permitted_side_effects: tuple[str, ...] = Field(min_length=1)
    property_vocabulary: tuple[str, ...]
    context_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class KnowledgeAdmissionFindingV1(StrictModel):
    skill_ref: KnowledgeSkillRefV1
    code: str
    detail: str


class EpochKnowledgeSkillLockV1(DigestBoundModel):
    _digest_field = "lock_digest"

    schema_version: Literal["ari.epoch-knowledge-skill-lock/v1"] = (
        "ari.epoch-knowledge-skill-lock/v1"
    )
    run_id: str
    epoch_id: str
    research_contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    catalog_snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    proposal_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    ontology_snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    context_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    admitted: tuple[KnowledgeSkillRefV1, ...]
    capability_requirements: tuple[CapabilityRequirementV1, ...]
    evaluation_obligations: tuple[EvaluationObligationV1, ...]
    rejected: tuple[KnowledgeAdmissionFindingV1, ...]
    unsatisfied: tuple[KnowledgeAdmissionFindingV1, ...]
    mode: KnowledgeMode
    producer_component_id: Literal["knowledge_binder_v1"] = "knowledge_binder_v1"
    prompt_hash: None = None
    lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class NodeKnowledgeSkillUseV1(DigestBoundModel):
    _digest_field = "use_digest"

    schema_version: Literal["ari.node-knowledge-skill-use/v1"] = (
        "ari.node-knowledge-skill-use/v1"
    )
    run_id: str
    node_id: str
    epoch_id: str
    epoch_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    ordered_skills: tuple[KnowledgeSkillRefV1, ...]
    knowledge_composition_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    use_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class InstructionCompositionV1(DigestBoundModel):
    _digest_field = "instruction_digest"

    schema_version: Literal["ari.instruction-composition/v1"] = (
        "ari.instruction-composition/v1"
    )
    base_prompt_hash: str
    base_prompt_sha256: str = Field(pattern=SHA256_DIGEST_PATTERN)
    active_rqgm_prompt_hashes: tuple[str, ...]
    ordered_knowledge_skill_hashes: tuple[Sha256Digest, ...]
    knowledge_composition_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    capability_binding_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    verification_contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    active_harness_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    instruction_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class KnowledgeSkillUseRecordV1(DigestBoundModel):
    _digest_field = "record_digest"

    schema_version: Literal["ari.knowledge-skill-use-record/v1"] = (
        "ari.knowledge-skill-use-record/v1"
    )
    run_id: str
    node_id: str
    epoch_id: str
    component_id: str
    component_prompt_hash: str | None
    node_use_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    instruction_identity: InstructionCompositionV1
    knowledge_skill_status_at_use: dict[str, KnowledgeCatalogStatus]
    capability_binding_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    verification_contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    active_harness_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    tainted_by_revocation: bool = False
    valid_for_frontier: bool = True
    record_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class KnowledgeRegistrationGateV1(StrictModel):
    gate_id: str
    passed: bool
    evidence_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    detail: str = ""


class KnowledgeSkillRegistrationReportV1(DigestBoundModel):
    _digest_field = "report_digest"

    schema_version: Literal["ari.knowledge-skill-registration-report/v1"] = (
        "ari.knowledge-skill-registration-report/v1"
    )
    skill_ref: KnowledgeSkillRefV1
    gates: tuple[KnowledgeRegistrationGateV1, ...]
    non_authoritative_hints: tuple[str, ...] = Field(default_factory=tuple)
    attachments: tuple[str, ...] = Field(default_factory=tuple)
    decision: Literal["candidate", "eligible-for-verified", "quarantined"]
    report_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _verified_requires_all_gates(self):
        if self.decision == "eligible-for-verified" and (
            len(self.gates) != 16 or not all(item.passed for item in self.gates)
        ):
            raise ValueError("verified eligibility requires all sixteen gates")
        return self


class KnowledgeSkillStatusTransitionV1(DigestBoundModel):
    _digest_field = "transition_digest"

    schema_version: Literal["ari.knowledge-skill-status-transition/v1"] = (
        "ari.knowledge-skill-status-transition/v1"
    )
    skill_ref: KnowledgeSkillRefV1
    from_status: KnowledgeCatalogStatus
    to_status: KnowledgeCatalogStatus
    actor_id: str
    evidence_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    parent_transition_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    transition_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


__all__ = [name for name in globals() if name.endswith("V1")]
