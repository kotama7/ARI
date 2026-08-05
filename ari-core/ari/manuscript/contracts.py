"""Strict, digest-bound contracts for the Manuscript Complete boundary.

The contracts intentionally separate deterministic research facts and fixed
policy decisions from stochastic authoring annotations.  All downstream paper
backends receive the same immutable context/readiness/brief identities.
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from ari.manuscript.digest import (
    SHA256_PATTERN,
    ZERO_DIGEST,
    canonical_digest,
    safe_relative_path,
)


MANUSCRIPT_REQUIREMENT_PROFILE_V1 = "ari.manuscript-requirement-profile/v1"
MANUSCRIPT_ARTIFACT_REF_V1 = "ari.manuscript-artifact-ref/v1"
MANUSCRIPT_NODE_SNAPSHOT_V1 = "ari.manuscript-node-snapshot/v1"
MANUSCRIPT_EXPLORATION_SNAPSHOT_V1 = "ari.manuscript-exploration-snapshot/v1"
MANUSCRIPT_OMISSION_MANIFEST_V1 = "ari.manuscript-omission-manifest/v1"
MANUSCRIPT_CONTEXT_V1 = "ari.manuscript-context/v1"
MANUSCRIPT_READINESS_V1 = "ari.manuscript-readiness/v1"
MANUSCRIPT_SECTION_BRIEF_V1 = "ari.manuscript-section-brief/v1"
MANUSCRIPT_SECTION_BRIEF_BUNDLE_V1 = "ari.manuscript-section-brief-bundle/v1"
MANUSCRIPT_AUTHORING_BINDING_V1 = "ari.manuscript-authoring-binding/v1"
RESEARCH_REPAIR_REQUEST_V1 = "ari.research-repair-request/v1"
RESEARCH_REPAIR_PLAN_V1 = "ari.research-repair-plan/v1"
MANUSCRIPT_PUBLICATION_DECISION_V1 = "ari.manuscript-publication-decision/v1"
MANUSCRIPT_PUBLICATION_LOCK_V1 = "ari.manuscript-publication-lock/v1"
MANUSCRIPT_SEGMENT_RECORD_V1 = "ari.manuscript-segment-record/v1"
MANUSCRIPT_TRANSITION_V1 = "ari.manuscript-transition/v1"

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}$")

RequirementStatus = Literal["satisfied", "not_applicable", "unavailable", "missing"]
EvidenceLane = Literal["publishable", "exploratory", "contextual_negative", "excluded"]
OmissionReason = Literal[
    "budget_exceeded",
    "not_relevant_by_profile",
    "duplicate",
    "missing_on_disk",
    "digest_mismatch",
    "parse_failure",
    "stale",
    "policy_excluded",
    "unsafe_path",
]
RepairKind = Literal[
    "artifact_recovery",
    "projection_rebuild",
    "literature_search",
    "baseline_comparison",
    "repetition_or_uncertainty",
    "ablation",
    "validation_experiment",
    "assurance_certification",
    "method_clarification",
    "limitation_disclosure",
    "human_decision",
]


class ManuscriptContractError(ValueError):
    """A manuscript artifact is malformed or has lost its source binding."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DigestBoundModel(StrictModel):
    digest_field: ClassVar[str]

    @classmethod
    def create(cls, **values: Any):
        values = dict(values)
        values[cls.digest_field] = ZERO_DIGEST
        return cls.model_validate(values, context={"bind_manuscript_digest": True})

    def digest_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={self.digest_field})

    @model_validator(mode="after")
    def _digest_matches(self, info: ValidationInfo):
        expected = canonical_digest(self.digest_payload())
        if info.context and info.context.get("bind_manuscript_digest"):
            object.__setattr__(self, self.digest_field, expected)
        elif getattr(self, self.digest_field) != expected:
            raise ValueError(f"{self.digest_field} does not match manuscript payload")
        return self


def _validate_id(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError("manuscript identity is invalid")
    return value


def _finite_json(value: Any, *, label: str) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite JSON") from exc
    return value


class RequirementSpecV1(StrictModel):
    requirement_id: str
    description: str = Field(min_length=1, max_length=2_000)
    section_targets: tuple[str, ...] = Field(min_length=1, max_length=32)
    applicability_rule_id: str
    authoring_blocking: bool
    publication_blocking: bool
    allowed_terminal_statuses: tuple[RequirementStatus, ...] = (
        "satisfied",
        "not_applicable",
        "unavailable",
        "missing",
    )
    resolver_kinds: tuple[RepairKind, ...] = Field(default_factory=tuple, max_length=16)
    evidence_kinds: tuple[str, ...] = Field(default_factory=tuple, max_length=32)

    @field_validator("requirement_id", "applicability_rule_id")
    @classmethod
    def _ids(cls, value: str) -> str:
        return _validate_id(value)

    @model_validator(mode="after")
    def _unique_values(self) -> "RequirementSpecV1":
        for values in (
            self.section_targets,
            self.allowed_terminal_statuses,
            self.resolver_kinds,
            self.evidence_kinds,
        ):
            if len(values) != len(set(values)):
                raise ValueError("manuscript requirement values must be unique")
        if not self.allowed_terminal_statuses:
            raise ValueError("manuscript requirement permits no terminal state")
        return self


class ManuscriptRequirementProfileV1(DigestBoundModel):
    digest_field = "profile_digest"
    schema_version: Literal["ari.manuscript-requirement-profile/v1"] = (
        MANUSCRIPT_REQUIREMENT_PROFILE_V1
    )
    profile_id: str
    profile_version: str
    paper_family: str
    policy_version: str
    evaluator_compatibility: tuple[str, ...] = Field(min_length=1, max_length=16)
    requirements: tuple[RequirementSpecV1, ...] = Field(min_length=1, max_length=256)
    profile_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("profile_id", "profile_version", "paper_family", "policy_version")
    @classmethod
    def _ids(cls, value: str) -> str:
        return _validate_id(value)

    @model_validator(mode="after")
    def _unique_requirements(self) -> "ManuscriptRequirementProfileV1":
        ids = [item.requirement_id for item in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("manuscript profile has duplicate requirement IDs")
        return self


class ManuscriptArtifactRefV1(StrictModel):
    schema_version: Literal["ari.manuscript-artifact-ref/v1"] = MANUSCRIPT_ARTIFACT_REF_V1
    item_id: str
    kind: str
    relative_path: str | None = None
    digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    size_bytes: int | None = Field(default=None, ge=0)
    source_node_id: str | None = None
    status: Literal[
        "present", "missing", "mismatch", "unhashed", "stale", "invalid"
    ] = "present"
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=128)

    @field_validator("item_id", "kind")
    @classmethod
    def _ids(cls, value: str) -> str:
        return _validate_id(value)

    @field_validator("relative_path")
    @classmethod
    def _path(cls, value: str | None) -> str | None:
        return safe_relative_path(value) if value is not None else None

    @field_validator("metadata")
    @classmethod
    def _metadata_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _finite_json(value, label="manuscript artifact metadata")

    @model_validator(mode="after")
    def _presence_coherent(self) -> "ManuscriptArtifactRefV1":
        if self.status == "present" and self.relative_path is not None:
            if self.digest is None or self.size_bytes is None:
                raise ValueError("present manuscript file lacks digest/size")
        if self.status == "missing" and self.digest is not None:
            raise ValueError("missing manuscript artifact cannot claim a digest")
        return self


class ManuscriptNodeSnapshotV1(StrictModel):
    schema_version: Literal["ari.manuscript-node-snapshot/v1"] = MANUSCRIPT_NODE_SNAPSHOT_V1
    node_id: str
    parent_id: str | None = None
    ancestor_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    depth: int = Field(default=0, ge=0)
    status: str
    label: str = ""
    name: str = ""
    original_direction: str | None = None
    has_real_data: bool = False
    metrics: dict[str, Any] = Field(default_factory=dict, max_length=100_000)
    scientific_score: float | None = None
    valid_for_frontier: bool = True
    assurance_status: str = ""
    assurance_tier: str = ""
    frontier_class: str = ""
    attestation_refs: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    certify_attestation_item_ids: tuple[str, ...] = Field(
        default_factory=tuple, max_length=10_000
    )
    verified_target_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    property_verdicts: dict[str, str] = Field(default_factory=dict, max_length=10_000)
    artifact_item_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=100_000)
    repair_request_id: str | None = None
    repair_requirement_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=256)
    repair_context_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    repair_allowed_changes: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    error_summary: str = ""

    @field_validator("node_id")
    @classmethod
    def _node_id(cls, value: str) -> str:
        return _validate_id(value)

    @field_validator("repair_request_id")
    @classmethod
    def _repair_id(cls, value: str | None) -> str | None:
        return _validate_id(value) if value is not None else None

    @field_validator("metrics")
    @classmethod
    def _metrics_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _finite_json(value, label="manuscript node metrics")

    @model_validator(mode="after")
    def _unique_refs(self) -> "ManuscriptNodeSnapshotV1":
        for values in (
            self.ancestor_ids,
            self.attestation_refs,
            self.certify_attestation_item_ids,
            self.artifact_item_ids,
            self.repair_requirement_ids,
            self.repair_allowed_changes,
        ):
            if len(values) != len(set(values)):
                raise ValueError("manuscript node references must be unique")
        if self.node_id in self.ancestor_ids:
            raise ValueError("manuscript node cannot be its own ancestor")
        return self


class ExplorationSnapshotV1(DigestBoundModel):
    digest_field = "snapshot_digest"
    schema_version: Literal["ari.manuscript-exploration-snapshot/v1"] = (
        MANUSCRIPT_EXPLORATION_SNAPSHOT_V1
    )
    run_id: str
    checkpoint_id: str
    exploration_mode: Literal["simple_bfts", "ari_rqgm"] = "simple_bfts"
    selection_policy_digest: str = Field(pattern=SHA256_PATTERN)
    research_contract_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    research_question: str = ""
    nodes: tuple[ManuscriptNodeSnapshotV1, ...] = Field(default_factory=tuple, max_length=100_000)
    artifacts: tuple[ManuscriptArtifactRefV1, ...] = Field(
        default_factory=tuple, max_length=200_000
    )
    scientific_winner_id: str | None = None
    source_digests: dict[str, str] = Field(default_factory=dict, max_length=10_000)
    snapshot_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("run_id", "checkpoint_id")
    @classmethod
    def _ids(cls, value: str) -> str:
        return _validate_id(value)

    @model_validator(mode="after")
    def _coherent(self) -> "ExplorationSnapshotV1":
        node_ids = [node.node_id for node in self.nodes]
        item_ids = [artifact.item_id for artifact in self.artifacts]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("exploration snapshot has duplicate nodes")
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("exploration snapshot has duplicate artifacts")
        if self.scientific_winner_id is not None and self.scientific_winner_id not in node_ids:
            raise ValueError("exploration winner is not in the snapshot")
        known_nodes = set(node_ids)
        for node in self.nodes:
            if node.parent_id is not None and node.parent_id not in known_nodes:
                raise ValueError("manuscript node parent is absent from the snapshot")
            if not set(node.ancestor_ids).issubset(known_nodes):
                raise ValueError("manuscript node ancestor is absent from the snapshot")
        known_items = set(item_ids)
        if any(not set(node.artifact_item_ids).issubset(known_items) for node in self.nodes):
            raise ValueError("node references an unknown manuscript artifact")
        return self


class OmissionV1(StrictModel):
    item_id: str
    reason: OmissionReason
    projection: str
    detail: str = ""
    creates_readiness_failure: bool = False

    @field_validator("item_id", "projection")
    @classmethod
    def _ids(cls, value: str) -> str:
        return _validate_id(value)


class OmissionManifestV1(DigestBoundModel):
    digest_field = "manifest_digest"
    schema_version: Literal["ari.manuscript-omission-manifest/v1"] = (
        MANUSCRIPT_OMISSION_MANIFEST_V1
    )
    source_snapshot_digest: str = Field(pattern=SHA256_PATTERN)
    projection: str
    inventory_item_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=200_000)
    included_item_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=200_000)
    omissions: tuple[OmissionV1, ...] = Field(default_factory=tuple, max_length=200_000)
    manifest_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _conserves_inventory(self) -> "OmissionManifestV1":
        inventory = list(self.inventory_item_ids)
        included = list(self.included_item_ids)
        omitted = [item.item_id for item in self.omissions]
        if len(inventory) != len(set(inventory)):
            raise ValueError("omission inventory contains duplicate IDs")
        if len(included) != len(set(included)) or len(omitted) != len(set(omitted)):
            raise ValueError("omission projection contains duplicate IDs")
        if set(included) & set(omitted):
            raise ValueError("manuscript item is both included and omitted")
        if set(included) | set(omitted) != set(inventory):
            raise ValueError("manuscript omission accounting is incomplete")
        return self


class EvidenceRecordV1(StrictModel):
    evidence_id: str
    kind: str
    lane: EvidenceLane
    node_id: str | None = None
    claim_eligible_fact: bool = False
    publishable: bool = False
    metric_values: dict[str, Any] = Field(default_factory=dict, max_length=100_000)
    artifact_item_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=100_000)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=128)

    @field_validator("evidence_id", "kind")
    @classmethod
    def _ids(cls, value: str) -> str:
        return _validate_id(value)

    @field_validator("metric_values")
    @classmethod
    def _metric_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _finite_json(value, label="manuscript evidence metrics")

    @model_validator(mode="after")
    def _lane_coherent(self) -> "EvidenceRecordV1":
        if self.publishable and self.lane != "publishable":
            raise ValueError("non-publishable evidence lane claims publication eligibility")
        if self.lane in {"contextual_negative", "excluded"} and self.claim_eligible_fact:
            raise ValueError("negative/excluded evidence cannot be a positive claim fact")
        for values in (self.artifact_item_ids, self.reason_codes):
            if len(values) != len(set(values)):
                raise ValueError("manuscript evidence references must be unique")
        return self


class ManuscriptAnnotationV1(StrictModel):
    annotation_id: str
    purpose: str
    text: str
    source_refs: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    model_call_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    claim_eligible: Literal[False] = False

    @field_validator("annotation_id", "purpose")
    @classmethod
    def _ids(cls, value: str) -> str:
        return _validate_id(value)


class ManuscriptContextV1(DigestBoundModel):
    digest_field = "context_digest"
    schema_version: Literal["ari.manuscript-context/v1"] = MANUSCRIPT_CONTEXT_V1
    run_id: str
    profile_digest: str = Field(pattern=SHA256_PATTERN)
    source_snapshot_digest: str = Field(pattern=SHA256_PATTERN)
    omission_manifest_digest: str = Field(pattern=SHA256_PATTERN)
    research_question: dict[str, Any] = Field(default_factory=dict, max_length=256)
    claim_characteristics: dict[str, bool] = Field(default_factory=dict, max_length=64)
    contribution_map: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=10_000)
    methods: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=10_000)
    subjects: dict[str, Any] = Field(default_factory=dict, max_length=10_000)
    evidence_records: tuple[EvidenceRecordV1, ...] = Field(default_factory=tuple, max_length=100_000)
    exploration_history: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=100_000)
    negative_results: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=100_000)
    related_work: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=100_000)
    limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    threats_to_validity: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    reproducibility: dict[str, Any] = Field(default_factory=dict, max_length=10_000)
    assurance: dict[str, Any] = Field(default_factory=dict, max_length=10_000)
    annotations: tuple[ManuscriptAnnotationV1, ...] = Field(default_factory=tuple, max_length=10_000)
    context_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("run_id")
    @classmethod
    def _run_id(cls, value: str) -> str:
        return _validate_id(value)

    @model_validator(mode="after")
    def _context_coherent(self) -> "ManuscriptContextV1":
        evidence_ids = [item.evidence_id for item in self.evidence_records]
        annotation_ids = [item.annotation_id for item in self.annotations]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("manuscript context has duplicate evidence IDs")
        if len(annotation_ids) != len(set(annotation_ids)):
            raise ValueError("manuscript context has duplicate annotation IDs")
        for field in (
            self.research_question,
            self.contribution_map,
            self.methods,
            self.subjects,
            self.exploration_history,
            self.negative_results,
            self.related_work,
            self.reproducibility,
            self.assurance,
        ):
            _finite_json(field, label="manuscript context")
        return self


class RequirementResultV1(StrictModel):
    requirement_id: str
    applicable: bool
    applicability_trace: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    status: RequirementStatus
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple, max_length=100_000)
    reason_code: str
    explanation: str = Field(default="", max_length=4_000)
    authoring_blocking: bool
    publication_blocking: bool
    resolver_kind: RepairKind | None = None
    repair_request_id: str | None = None
    evaluator_version: str

    @field_validator("requirement_id", "reason_code", "evaluator_version")
    @classmethod
    def _ids(cls, value: str) -> str:
        return _validate_id(value)

    @model_validator(mode="after")
    def _status_coherent(self) -> "RequirementResultV1":
        if not self.applicable and self.status != "not_applicable":
            raise ValueError("non-applicable requirement must use not_applicable")
        if self.applicable and self.status == "not_applicable":
            raise ValueError("applicable requirement cannot use not_applicable")
        if self.status in {"satisfied", "not_applicable"} and self.repair_request_id:
            raise ValueError("terminal satisfied requirement cannot name a repair request")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("readiness evidence refs must be unique")
        return self


class ManuscriptReadinessReportV1(DigestBoundModel):
    digest_field = "readiness_digest"
    schema_version: Literal["ari.manuscript-readiness/v1"] = MANUSCRIPT_READINESS_V1
    run_id: str
    profile_digest: str = Field(pattern=SHA256_PATTERN)
    context_digest: str = Field(pattern=SHA256_PATTERN)
    evaluator_version: str
    requirement_results: tuple[RequirementResultV1, ...] = Field(min_length=1, max_length=256)
    authoring_verdict: Literal[
        "ready", "ready_with_disclosures", "repair_required", "blocked"
    ]
    publication_verdict: Literal["ready", "blocked"]
    counts: dict[RequirementStatus, int]
    readiness_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _verdict_coherent(self) -> "ManuscriptReadinessReportV1":
        ids = [item.requirement_id for item in self.requirement_results]
        if len(ids) != len(set(ids)):
            raise ValueError("readiness has duplicate requirement IDs")
        expected_counts = {
            status: sum(item.status == status for item in self.requirement_results)
            for status in ("satisfied", "not_applicable", "unavailable", "missing")
        }
        if dict(self.counts) != expected_counts:
            raise ValueError("readiness counts differ from requirement results")
        author_missing = any(
            item.authoring_blocking and item.status == "missing"
            for item in self.requirement_results
        )
        author_unavailable = any(
            item.authoring_blocking and item.status == "unavailable"
            for item in self.requirement_results
        )
        any_disclosure = any(
            item.status == "unavailable" for item in self.requirement_results
        )
        expected_author = (
            "blocked"
            if author_unavailable
            else "repair_required"
            if author_missing
            else "ready_with_disclosures"
            if any_disclosure
            else "ready"
        )
        publication_block = any(
            item.publication_blocking and item.status in {"missing", "unavailable"}
            for item in self.requirement_results
        )
        if self.authoring_verdict != expected_author:
            raise ValueError("authoring verdict differs from requirement results")
        if self.publication_verdict != ("blocked" if publication_block else "ready"):
            raise ValueError("publication verdict differs from requirement results")
        return self


class SectionBriefV1(DigestBoundModel):
    digest_field = "brief_digest"
    schema_version: Literal["ari.manuscript-section-brief/v1"] = MANUSCRIPT_SECTION_BRIEF_V1
    section_id: str
    context_digest: str = Field(pattern=SHA256_PATTERN)
    readiness_digest: str = Field(pattern=SHA256_PATTERN)
    allowed_evidence_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=100_000)
    contextual_negative_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=100_000)
    forbidden_evidence_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=100_000)
    required_disclosures: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    content_items: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=100_000)
    omitted_item_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=100_000)
    character_budget: int = Field(ge=1, le=2_000_000)
    brief_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("section_id")
    @classmethod
    def _section_id(cls, value: str) -> str:
        return _validate_id(value)

    @model_validator(mode="after")
    def _brief_coherent(self) -> "SectionBriefV1":
        groups = (
            self.allowed_evidence_ids,
            self.contextual_negative_ids,
            self.forbidden_evidence_ids,
            self.omitted_item_ids,
        )
        if any(len(values) != len(set(values)) for values in groups):
            raise ValueError("section brief contains duplicate references")
        if set(self.allowed_evidence_ids) & set(self.forbidden_evidence_ids):
            raise ValueError("section brief both allows and forbids evidence")
        _finite_json(self.content_items, label="section brief content")
        return self


class SectionBriefBundleV1(DigestBoundModel):
    digest_field = "bundle_digest"
    schema_version: Literal["ari.manuscript-section-brief-bundle/v1"] = (
        MANUSCRIPT_SECTION_BRIEF_BUNDLE_V1
    )
    run_id: str
    profile_digest: str = Field(pattern=SHA256_PATTERN)
    context_digest: str = Field(pattern=SHA256_PATTERN)
    readiness_digest: str = Field(pattern=SHA256_PATTERN)
    renderer_version: str
    briefs: tuple[SectionBriefV1, ...] = Field(min_length=1, max_length=64)
    bundle_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _bundle_coherent(self) -> "SectionBriefBundleV1":
        ids = [brief.section_id for brief in self.briefs]
        if len(ids) != len(set(ids)):
            raise ValueError("section brief bundle has duplicate sections")
        for brief in self.briefs:
            if brief.context_digest != self.context_digest or brief.readiness_digest != self.readiness_digest:
                raise ValueError("section brief is bound to another manuscript attempt")
        return self


class ManuscriptAuthoringBindingV1(DigestBoundModel):
    digest_field = "binding_digest"
    schema_version: Literal["ari.manuscript-authoring-binding/v1"] = (
        MANUSCRIPT_AUTHORING_BINDING_V1
    )
    run_id: str
    attempt_id: str
    source_snapshot_digest: str = Field(pattern=SHA256_PATTERN)
    profile_digest: str = Field(pattern=SHA256_PATTERN)
    context_digest: str = Field(pattern=SHA256_PATTERN)
    readiness_digest: str = Field(pattern=SHA256_PATTERN)
    brief_bundle_digest: str = Field(pattern=SHA256_PATTERN)
    paper_mode: Literal["linear", "rqgm_archive"]
    backend_version: str
    target_build_id: str
    target_build_revision: int = Field(ge=0, le=10_000)
    binding_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("run_id", "attempt_id", "backend_version", "target_build_id")
    @classmethod
    def _ids(cls, value: str) -> str:
        return _validate_id(value)


class RepairBudgetV1(StrictModel):
    max_rounds: int = Field(default=2, ge=0, le=100)
    max_new_nodes: int = Field(default=8, ge=0, le=100_000)
    max_experiment_runs: int = Field(default=12, ge=0, le=100_000)
    max_llm_calls: int = Field(default=8, ge=0, le=100_000)
    max_resource_units: float | None = Field(default=None, ge=0)


class ResearchRepairRequestV1(DigestBoundModel):
    digest_field = "request_digest"
    schema_version: Literal["ari.research-repair-request/v1"] = RESEARCH_REPAIR_REQUEST_V1
    request_id: str
    source_context_digest: str = Field(pattern=SHA256_PATTERN)
    requirement_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    kind: RepairKind
    target_claim_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    target_node_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    fixed_variables: dict[str, Any] = Field(default_factory=dict, max_length=1_000)
    allowed_changes: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    required_capability_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    required_harness_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    preconditions: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    success_predicate_id: str
    stop_conditions: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    budget: RepairBudgetV1
    authority_digest: str = Field(pattern=SHA256_PATTERN)
    status: Literal[
        "pending", "running", "satisfied", "failed", "exhausted", "cancelled"
    ] = "pending"
    request_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("request_id", "success_predicate_id")
    @classmethod
    def _ids(cls, value: str) -> str:
        return _validate_id(value)

    @model_validator(mode="after")
    def _request_coherent(self) -> "ResearchRepairRequestV1":
        for values in (
            self.requirement_ids,
            self.target_claim_ids,
            self.target_node_ids,
            self.allowed_changes,
            self.required_capability_ids,
            self.required_harness_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("repair request contains duplicate identities")
        _finite_json(self.fixed_variables, label="repair fixed variables")
        return self


class ResearchRepairPlanV1(DigestBoundModel):
    digest_field = "plan_digest"
    schema_version: Literal["ari.research-repair-plan/v1"] = RESEARCH_REPAIR_PLAN_V1
    run_id: str
    source_context_digest: str = Field(pattern=SHA256_PATTERN)
    readiness_digest: str = Field(pattern=SHA256_PATTERN)
    policy: Literal["disabled", "explicit", "auto"]
    budget: RepairBudgetV1
    authority_digest: str = Field(pattern=SHA256_PATTERN)
    requests: tuple[ResearchRepairRequestV1, ...] = Field(default_factory=tuple, max_length=10_000)
    plan_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _plan_coherent(self) -> "ResearchRepairPlanV1":
        ids = [item.request_id for item in self.requests]
        if len(ids) != len(set(ids)):
            raise ValueError("repair plan has duplicate request IDs")
        for item in self.requests:
            if item.source_context_digest != self.source_context_digest:
                raise ValueError("repair request belongs to another context")
            if item.authority_digest != self.authority_digest:
                raise ValueError("repair request expands or changes authority")
            if (
                item.budget.max_new_nodes > self.budget.max_new_nodes
                or item.budget.max_experiment_runs > self.budget.max_experiment_runs
                or item.budget.max_llm_calls > self.budget.max_llm_calls
            ):
                raise ValueError("repair request exceeds plan budget")
        return self


class PublicationSubVerdictV1(StrictModel):
    gate: Literal[
        "manuscript_readiness",
        "claim_evidence",
        "assurance",
        "build_compile",
        "reproduction",
        "freshness",
    ]
    status: Literal["pass", "fail", "not_required"]
    artifact_digests: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)

    @model_validator(mode="after")
    def _verdict_has_reason(self) -> "PublicationSubVerdictV1":
        if self.status == "fail" and not self.reason_codes:
            raise ValueError("failed publication gate lacks a reason")
        if len(self.artifact_digests) != len(set(self.artifact_digests)):
            raise ValueError("publication gate contains duplicate artifacts")
        return self


class PublicationDecisionV1(DigestBoundModel):
    digest_field = "decision_digest"
    schema_version: Literal["ari.manuscript-publication-decision/v1"] = (
        MANUSCRIPT_PUBLICATION_DECISION_V1
    )
    run_id: str
    attempt_id: str
    paper_build_digest: str = Field(pattern=SHA256_PATTERN)
    authoring_binding_digest: str = Field(pattern=SHA256_PATTERN)
    readiness_digest: str = Field(pattern=SHA256_PATTERN)
    subverdicts: tuple[PublicationSubVerdictV1, ...] = Field(min_length=6, max_length=6)
    decision: Literal["publishable", "blocked"]
    decision_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _decision_coherent(self) -> "PublicationDecisionV1":
        expected = {
            "manuscript_readiness",
            "claim_evidence",
            "assurance",
            "build_compile",
            "reproduction",
            "freshness",
        }
        names = [item.gate for item in self.subverdicts]
        if set(names) != expected or len(names) != len(set(names)):
            raise ValueError("publication decision gate set is incomplete")
        should_publish = all(item.status != "fail" for item in self.subverdicts)
        if self.decision != ("publishable" if should_publish else "blocked"):
            raise ValueError("publication decision is not the logical AND of its gates")
        return self


class PublicationLockV1(DigestBoundModel):
    """Final immutable interlock for one already-publishable exact build."""

    digest_field = "lock_digest"
    schema_version: Literal["ari.manuscript-publication-lock/v1"] = (
        MANUSCRIPT_PUBLICATION_LOCK_V1
    )
    run_id: str
    attempt_id: str
    decision_digest: str = Field(pattern=SHA256_PATTERN)
    paper_build_digest: str = Field(pattern=SHA256_PATTERN)
    authoring_binding_digest: str = Field(pattern=SHA256_PATTERN)
    pdf_digest: str = Field(pattern=SHA256_PATTERN)
    freshness_verified: Literal[True] = True
    lock_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("run_id", "attempt_id")
    @classmethod
    def _lock_identity(cls, value: str) -> str:
        return _validate_id(value)


class ManuscriptSegmentRecordV1(DigestBoundModel):
    """Immutable transaction record for one selected pipeline segment set."""

    digest_field = "record_digest"
    schema_version: Literal["ari.manuscript-segment-record/v1"] = (
        MANUSCRIPT_SEGMENT_RECORD_V1
    )
    run_id: str
    source_attempt_id: str
    invocation_id: str
    execution_index: int = Field(ge=0, le=100_000)
    segments: tuple[Literal["evidence", "authoring", "verification"], ...] = Field(
        min_length=1, max_length=3
    )
    workflow_digest: str = Field(pattern=SHA256_PATTERN)
    enabled_stages: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    disabled_stages: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    input_artifacts: tuple[ManuscriptArtifactRefV1, ...] = Field(
        default_factory=tuple, max_length=100_000
    )
    output_artifacts: tuple[ManuscriptArtifactRefV1, ...] = Field(
        default_factory=tuple, max_length=100_000
    )
    status: Literal["completed", "blocked", "failed"]
    blocking_reason: str = ""
    record_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("run_id", "source_attempt_id", "invocation_id")
    @classmethod
    def _identity(cls, value: str) -> str:
        return _validate_id(value)

    @model_validator(mode="after")
    def _segment_coherent(self) -> "ManuscriptSegmentRecordV1":
        if len(self.segments) != len(set(self.segments)):
            raise ValueError("segment record contains duplicate segments")
        if len(self.enabled_stages) != len(set(self.enabled_stages)):
            raise ValueError("segment record contains duplicate enabled stages")
        if len(self.disabled_stages) != len(set(self.disabled_stages)):
            raise ValueError("segment record contains duplicate disabled stages")
        if set(self.enabled_stages) & set(self.disabled_stages):
            raise ValueError("pipeline stage is both enabled and disabled")
        for artifacts in (self.input_artifacts, self.output_artifacts):
            paths = [item.relative_path for item in artifacts if item.relative_path]
            if len(paths) != len(set(paths)):
                raise ValueError("segment record contains duplicate artifact paths")
        if self.status != "completed" and not self.blocking_reason:
            raise ValueError("non-completed segment record lacks a reason")
        return self


class ManuscriptTransitionV1(DigestBoundModel):
    digest_field = "transition_digest"
    schema_version: Literal["ari.manuscript-transition/v1"] = MANUSCRIPT_TRANSITION_V1
    sequence: int = Field(ge=0)
    run_id: str
    attempt_id: str
    from_state: str
    to_state: str
    reason_code: str
    artifact_digests: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    parent_transition_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    transition_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _transition_coherent(self) -> "ManuscriptTransitionV1":
        if (self.sequence == 0) != (self.parent_transition_digest is None):
            raise ValueError("manuscript transition parent lineage is inconsistent")
        return self


def _parse(model, value: Any, label: str):
    try:
        if isinstance(value, (str, bytes, bytearray)):
            value = json.loads(value)
        return model.model_validate(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ManuscriptContractError(f"invalid {label}: {exc}") from exc


def parse_manuscript_context(value: Any) -> ManuscriptContextV1:
    return _parse(ManuscriptContextV1, value, "ManuscriptContextV1")


def parse_manuscript_readiness(value: Any) -> ManuscriptReadinessReportV1:
    return _parse(ManuscriptReadinessReportV1, value, "ManuscriptReadinessReportV1")


def parse_repair_plan(value: Any) -> ResearchRepairPlanV1:
    return _parse(ResearchRepairPlanV1, value, "ResearchRepairPlanV1")


def parse_publication_decision(value: Any) -> PublicationDecisionV1:
    return _parse(PublicationDecisionV1, value, "PublicationDecisionV1")


__all__ = [name for name in globals() if name.endswith("V1") or name in {
    "EvidenceLane",
    "ManuscriptContractError",
    "OmissionReason",
    "RepairKind",
    "RequirementStatus",
    "canonical_digest",
    "parse_manuscript_context",
    "parse_manuscript_readiness",
    "parse_publication_decision",
    "parse_repair_plan",
}]
