"""Immutable literature, idea, and research-contract records.

The models in this module form the scientific hand-off between retrieval,
ideation, evaluation, transformation, and publication.  Digest-bound records
are deliberately strict: a consumer either receives the exact object selected
by the idea stage or rejects it.  In particular, consumers must not silently
re-extract a metric or evidence vocabulary from prose.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


RETRIEVAL_RECORD_V1 = "ari.retrieval-record/v1"
SURVEY_SNAPSHOT_V1 = "ari.survey-snapshot/v1"
METRIC_CONTRACT_V1 = "ari.metric-contract/v1"
IDEA_CANDIDATE_V1 = "ari.idea-candidate/v1"
IDEA_REJECTION_V1 = "ari.idea-rejection/v1"
IDEA_GENERATION_LOCK_V1 = "ari.idea-generation-lock/v1"
IDEA_GENERATION_PROVENANCE_V1 = "ari.idea-generation-provenance/v1"
IDEA_SET_V1 = "ari.idea-set/v1"
RESEARCH_CONTRACT_V1 = "ari.research-contract/v1"
RESEARCH_ARTIFACT_REF_V1 = "ari.research-artifact-ref/v1"
CITATION_EDGE_V1 = "ari.citation-edge/v1"

SHA256_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_ZERO_DIGEST = "sha256:" + ("0" * 64)
_SAFE_TOKEN = re.compile(r"^[a-z0-9][a-z0-9._:/@+-]{0,255}$")


class ResearchContractError(ValueError):
    """A research hand-off is malformed, tampered with, or inconsistent."""


def canonical_digest(value: Any) -> str:
    """Return the stable digest of a JSON-compatible value or Pydantic model."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _DigestBoundModel(_StrictModel):
    """Base for records whose digest covers every field except itself."""

    _digest_field: ClassVar[str]

    @classmethod
    def create(cls, **values: Any):
        values[cls._digest_field] = _ZERO_DIGEST
        return cls.model_validate(values, context={"bind_research_digest": True})

    def digest_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={self._digest_field})

    @model_validator(mode="after")
    def _digest_matches(self, info: ValidationInfo):
        expected = canonical_digest(self.digest_payload())
        if info.context and info.context.get("bind_research_digest"):
            object.__setattr__(self, self._digest_field, expected)
        elif getattr(self, self._digest_field) != expected:
            raise ValueError(
                f"{self._digest_field} does not match the canonical payload"
            )
        return self


class ResearchArtifactRefV1(_StrictModel):
    """Content-addressed research artifact under a checkpoint/workspace root."""

    schema_version: Literal["ari.research-artifact-ref/v1"] = (
        RESEARCH_ARTIFACT_REF_V1
    )
    logical_name: str = Field(min_length=1, max_length=512)
    digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    media_type: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=128)
    source_run_id: str | None = Field(default=None, max_length=256)

    @field_validator("logical_name")
    @classmethod
    def _safe_relative_name(cls, value: str) -> str:
        from pathlib import PurePosixPath

        path = PurePosixPath(value)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError("logical_name must be a safe relative path")
        return path.as_posix()


class RetrievalRecordV1(_StrictModel):
    """Provider-neutral, content-addressed literature or web record."""

    schema_version: Literal["ari.retrieval-record/v1"] = RETRIEVAL_RECORD_V1
    canonical_id: str = Field(min_length=1, max_length=256)
    provider: str = Field(min_length=1, max_length=128)
    provider_record_id: str | None = Field(default=None, max_length=512)
    provider_version: str | None = Field(default=None, max_length=128)
    query: str = Field(min_length=1, max_length=4096)
    retrieved_at: datetime | None = None
    title: str = Field(min_length=1, max_length=2048)
    abstract: str = Field(default="", max_length=100_000)
    authors: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    year: int | None = Field(default=None, ge=0, le=9999)
    citation_count: int | None = Field(default=None, ge=0)
    source_url: str | None = Field(default=None, max_length=8192)
    payload_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    aliases: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    license: str | None = Field(default=None, max_length=512)
    use_restriction: str | None = Field(default=None, max_length=2048)

    @field_validator("canonical_id", "provider")
    @classmethod
    def _safe_identity(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SAFE_TOKEN.fullmatch(normalized):
            raise ValueError("identity must be a lowercase stable token")
        return normalized

    @field_validator("retrieved_at")
    @classmethod
    def _timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("retrieved_at must include a timezone")
        return value

    @field_validator("authors", "aliases")
    @classmethod
    def _unique_nonempty(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in values if item.strip())
        if len(normalized) != len(set(normalized)):
            raise ValueError("values must be unique")
        return normalized


class CitationEdgeV1(_StrictModel):
    schema_version: Literal["ari.citation-edge/v1"] = CITATION_EDGE_V1
    source_id: str = Field(min_length=1, max_length=256)
    target_id: str = Field(min_length=1, max_length=256)
    relation: Literal["cites", "is-cited-by", "related"]
    provider: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def _not_self_edge(self):
        if self.source_id == self.target_id:
            raise ValueError("citation self-edges are not allowed")
        return self


SurveyMode = Literal["live", "record", "replay", "frozen", "inline"]


class SurveySnapshotV1(_DigestBoundModel):
    """Exact retrieval input consumed by one idea-generation attempt."""

    _digest_field = "snapshot_digest"

    schema_version: Literal["ari.survey-snapshot/v1"] = SURVEY_SNAPSHOT_V1
    snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    mode: SurveyMode
    provider: str = Field(min_length=1, max_length=128)
    provider_version: str | None = Field(default=None, max_length=128)
    query: str = Field(min_length=1, max_length=4096)
    retrieved_at: datetime | None = None
    byte_reproducible: bool
    records: tuple[RetrievalRecordV1, ...] = Field(
        default_factory=tuple, max_length=100_000
    )
    citation_edges: tuple[CitationEdgeV1, ...] = Field(
        default_factory=tuple, max_length=1_000_000
    )
    artifacts: tuple[ResearchArtifactRefV1, ...] = Field(
        default_factory=tuple, max_length=10_000
    )
    warnings: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)

    @model_validator(mode="after")
    def _snapshot_is_consistent(self):
        ids = [record.canonical_id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("snapshot canonical IDs must be unique")
        id_set = set(ids)
        for edge in self.citation_edges:
            if edge.source_id not in id_set or edge.target_id not in id_set:
                raise ValueError("citation edges must reference snapshot records")
        if self.mode == "replay" and not self.byte_reproducible:
            raise ValueError("replay snapshots must be byte reproducible")
        if self.mode in {"live", "record"} and self.retrieved_at is None:
            raise ValueError("live/record snapshots require retrieved_at")
        return self


MetricDirection = Literal["higher", "lower", "target", "none"]
ComparisonScope = Literal[
    "same-environment", "cross-environment", "within-subject", "not-applicable"
]
NormalizationCeiling = Literal["measured", "not-applicable"]


class MetricContractV1(_StrictModel):
    """Idea-owned metric vocabulary; evaluator enforcement is read-only."""

    schema_version: Literal["ari.metric-contract/v1"] = METRIC_CONTRACT_V1
    name: str = Field(min_length=1, max_length=256)
    unit: str = Field(min_length=1, max_length=128)
    direction: MetricDirection
    comparison_scope: ComparisonScope
    rationale: str = Field(min_length=1, max_length=4096)
    required_evidence: tuple[str, ...] = Field(min_length=1, max_length=128)
    correctness_required: bool
    normalization_ceiling: NormalizationCeiling
    target_value: float | None = None

    @field_validator("unit")
    @classmethod
    def _known_unit(cls, value: str) -> str:
        normalized = value.strip()
        if normalized.lower() in {"", "?", "unknown", "unspecified", "tbd"}:
            raise ValueError("metric unit must be explicit")
        return normalized

    @field_validator("required_evidence")
    @classmethod
    def _evidence_vocabulary(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in values if item.strip())
        if not normalized:
            raise ValueError("required_evidence cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("required_evidence must be unique")
        return normalized

    @model_validator(mode="after")
    def _target_is_consistent(self):
        if self.direction == "target" and self.target_value is None:
            raise ValueError("target direction requires target_value")
        if self.direction != "target" and self.target_value is not None:
            raise ValueError("target_value requires target direction")
        return self


class IdeaCandidateV1(_DigestBoundModel):
    _digest_field = "candidate_id"

    schema_version: Literal["ari.idea-candidate/v1"] = IDEA_CANDIDATE_V1
    candidate_id: str = Field(pattern=SHA256_DIGEST_PATTERN)
    title: str = Field(min_length=1, max_length=512)
    hypothesis: str = Field(min_length=1, max_length=10_000)
    description: str = Field(min_length=1, max_length=20_000)
    experiment_plan: str = Field(min_length=1, max_length=100_000)
    falsification_conditions: tuple[str, ...] = Field(min_length=1, max_length=64)
    metric_contract: MetricContractV1
    citations: tuple[str, ...] = Field(min_length=1, max_length=1_000)
    artifact_references: tuple[str, ...] = Field(default_factory=tuple)
    limitations: tuple[str, ...] = Field(min_length=1, max_length=64)
    source_snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    generation_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    generator_adapter: str = Field(min_length=1, max_length=128)
    novelty_score: float | None = Field(default=None, ge=0, le=1)
    feasibility_score: float | None = Field(default=None, ge=0, le=1)
    overall_score: float | None = Field(default=None, ge=0, le=1)

    @field_validator(
        "falsification_conditions", "citations", "artifact_references", "limitations"
    )
    @classmethod
    def _unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in values if item.strip())
        if len(normalized) != len(set(normalized)):
            raise ValueError("candidate lists must contain unique values")
        return normalized


class IdeaRejectionV1(_StrictModel):
    schema_version: Literal["ari.idea-rejection/v1"] = IDEA_REJECTION_V1
    raw_candidate_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    title: str = Field(default="", max_length=512)
    reasons: tuple[str, ...] = Field(min_length=1, max_length=64)
    generator_adapter: str = Field(min_length=1, max_length=128)


class IdeaGenerationLockV1(_DigestBoundModel):
    """Deterministic generation inputs, excluding timestamps and model output."""

    _digest_field = "generation_lock_digest"

    schema_version: Literal["ari.idea-generation-lock/v1"] = (
        IDEA_GENERATION_LOCK_V1
    )
    generation_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    adapter: str = Field(min_length=1, max_length=128)
    adapter_version: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=512)
    api_base_identity: str | None = Field(default=None, max_length=2048)
    prompt_digests: tuple[str, ...] = Field(min_length=1, max_length=128)
    temperatures: tuple[float, ...] = Field(min_length=1, max_length=128)
    seed: int | None = None
    source_snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    topic_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    experiment_context_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    vendor_commit: str | None = Field(default=None, max_length=64)
    vendor_license: str | None = Field(default=None, max_length=128)
    model_revision: str | None = Field(default=None, max_length=256)
    generation_parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("prompt_digests")
    @classmethod
    def _prompt_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not re.fullmatch(SHA256_DIGEST_PATTERN, value):
                raise ValueError("prompt digests must use canonical SHA-256")
        return values


class IdeaGenerationProvenanceV1(_StrictModel):
    schema_version: Literal["ari.idea-generation-provenance/v1"] = (
        IDEA_GENERATION_PROVENANCE_V1
    )
    lock: IdeaGenerationLockV1
    generated_at: datetime
    output_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    requested_adapter: str = Field(min_length=1, max_length=128)
    actual_adapter: str = Field(min_length=1, max_length=128)
    fallback_reason: str | None = Field(default=None, max_length=4096)

    @field_validator("generated_at")
    @classmethod
    def _generated_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("generated_at must include a timezone")
        return value


class IdeaSetV1(_DigestBoundModel):
    _digest_field = "idea_set_digest"

    schema_version: Literal["ari.idea-set/v1"] = IDEA_SET_V1
    idea_set_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    topic: str = Field(min_length=1, max_length=20_000)
    source_snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    generation: IdeaGenerationProvenanceV1
    candidates: tuple[IdeaCandidateV1, ...] = Field(default_factory=tuple)
    rejections: tuple[IdeaRejectionV1, ...] = Field(default_factory=tuple)
    selected_candidate_id: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )

    @model_validator(mode="after")
    def _set_is_consistent(self):
        if self.generation.lock.source_snapshot_digest != self.source_snapshot_digest:
            raise ValueError("generation lock and idea set use different snapshots")
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate IDs must be unique")
        if self.selected_candidate_id is not None and (
            self.selected_candidate_id not in candidate_ids
        ):
            raise ValueError("selected candidate is not in the candidate set")
        return self


class ResearchContractV1(_DigestBoundModel):
    """Mint-once scientific contract selected from an admitted idea candidate."""

    _digest_field = "contract_digest"

    schema_version: Literal["ari.research-contract/v1"] = RESEARCH_CONTRACT_V1
    contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    idea_set_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    selected_candidate_id: str = Field(pattern=SHA256_DIGEST_PATTERN)
    source_snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    title: str = Field(min_length=1, max_length=512)
    hypothesis: str = Field(min_length=1, max_length=10_000)
    experiment_plan: str = Field(min_length=1, max_length=100_000)
    falsification_conditions: tuple[str, ...] = Field(min_length=1, max_length=64)
    metric_contract: MetricContractV1
    citations: tuple[str, ...] = Field(min_length=1, max_length=1_000)
    artifact_references: tuple[str, ...] = Field(default_factory=tuple)
    limitations: tuple[str, ...] = Field(min_length=1, max_length=64)
    generation_lock_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


def mint_research_contract(
    idea_set: IdeaSetV1,
    candidate_id: str | None = None,
) -> ResearchContractV1:
    """Select one admitted candidate and mint its immutable run contract."""

    selected = candidate_id or idea_set.selected_candidate_id
    if selected is None:
        raise ResearchContractError("idea set has no selected candidate")
    candidate = next(
        (item for item in idea_set.candidates if item.candidate_id == selected), None
    )
    if candidate is None:
        raise ResearchContractError("selected candidate is not admitted")
    return ResearchContractV1.create(
        idea_set_digest=idea_set.idea_set_digest,
        selected_candidate_id=candidate.candidate_id,
        source_snapshot_digest=candidate.source_snapshot_digest,
        title=candidate.title,
        hypothesis=candidate.hypothesis,
        experiment_plan=candidate.experiment_plan,
        falsification_conditions=candidate.falsification_conditions,
        metric_contract=candidate.metric_contract,
        citations=candidate.citations,
        artifact_references=candidate.artifact_references,
        limitations=candidate.limitations,
        generation_lock_digest=candidate.generation_lock_digest,
    )


def validate_research_handoff(
    *,
    snapshot: SurveySnapshotV1,
    idea_set: IdeaSetV1,
    contract: ResearchContractV1 | None,
) -> None:
    """Verify cross-record digests, citations, artifacts, and selection identity."""

    if idea_set.source_snapshot_digest != snapshot.snapshot_digest:
        raise ResearchContractError("idea set does not reference the supplied snapshot")
    citation_ids = {record.canonical_id for record in snapshot.records}
    artifact_digests = {artifact.digest for artifact in snapshot.artifacts}
    for candidate in idea_set.candidates:
        missing_citations = set(candidate.citations) - citation_ids
        if missing_citations:
            raise ResearchContractError(
                f"candidate references unknown citations: {sorted(missing_citations)}"
            )
        missing_artifacts = set(candidate.artifact_references) - artifact_digests
        if missing_artifacts:
            raise ResearchContractError(
                f"candidate references unknown artifacts: {sorted(missing_artifacts)}"
            )
    if contract is None:
        if idea_set.selected_candidate_id is not None:
            raise ResearchContractError("selected idea is missing a research contract")
        return
    expected = mint_research_contract(idea_set, contract.selected_candidate_id)
    if contract != expected:
        raise ResearchContractError("research contract differs from selected candidate")


def parse_survey_snapshot(document: dict[str, Any]) -> SurveySnapshotV1:
    try:
        return SurveySnapshotV1.model_validate(document)
    except Exception as exc:
        raise ResearchContractError(f"invalid survey snapshot: {exc}") from exc


def load_survey_snapshot_ref(
    checkpoint_dir: str,
    logical_name: str,
    *,
    max_bytes: int = 128 * 1024 * 1024,
) -> SurveySnapshotV1:
    """Load a snapshot through a closed workspace and verify every artifact.

    This is the common hand-off used by retrieval, idea, and paper Skills.  A
    digest-valid snapshot whose referenced cassette or raw payload was changed
    is still rejected before scientific consumption.
    """

    from pathlib import Path

    from ari.execution import WorkspaceRefV1

    if not checkpoint_dir:
        raise ResearchContractError("snapshot loading requires a checkpoint root")
    if not logical_name:
        raise ResearchContractError("snapshot loading requires a logical name")
    workspace = WorkspaceRefV1(root=str(Path(checkpoint_dir).expanduser().resolve()))
    payload = workspace.read_bytes(logical_name, max_bytes=max_bytes)
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ResearchContractError("survey snapshot is not valid JSON") from exc
    snapshot = parse_survey_snapshot(document)
    for artifact in snapshot.artifacts:
        artifact_payload = workspace.read_bytes(
            artifact.logical_name, max_bytes=max_bytes
        )
        digest = "sha256:" + hashlib.sha256(artifact_payload).hexdigest()
        if digest != artifact.digest:
            raise ResearchContractError(
                f"survey artifact digest mismatch: {artifact.logical_name}"
            )
    return snapshot


def parse_idea_set(document: dict[str, Any]) -> IdeaSetV1:
    try:
        return IdeaSetV1.model_validate(document)
    except Exception as exc:
        raise ResearchContractError(f"invalid idea set: {exc}") from exc


def parse_research_contract(document: dict[str, Any]) -> ResearchContractV1:
    try:
        return ResearchContractV1.model_validate(document)
    except Exception as exc:
        raise ResearchContractError(f"invalid research contract: {exc}") from exc


def parse_research_contract_document(document: dict[str, Any]) -> ResearchContractV1 | None:
    """Read the typed contract embedded in ``idea.json``; never infer one.

    Legacy documents return ``None``.  A document declaring the typed format but
    containing no valid contract fails closed so callers cannot fall back to an
    LLM-derived vocabulary for a rejected new-format idea set.
    """

    raw = document.get("research_contract")
    declares_typed = document.get("typed_schema_version") == RESEARCH_CONTRACT_V1
    if raw is None:
        if declares_typed:
            raise ResearchContractError(
                "typed idea document has no admitted research contract"
            )
        return None
    if not isinstance(raw, dict):
        raise ResearchContractError("research_contract must be an object")
    contract = parse_research_contract(raw)
    advertised = document.get("research_contract_digest")
    if advertised is not None and advertised != contract.contract_digest:
        raise ResearchContractError("advertised research contract digest differs")
    return contract


def metric_gate_projection(contract: ResearchContractV1) -> dict[str, Any]:
    """Project a research contract into the existing deterministic claim gate."""

    metric = contract.metric_contract
    claims = [
        {
            "claim": condition,
            "required_evidence": list(metric.required_evidence),
        }
        for condition in contract.falsification_conditions
    ]
    return {
        "schema_version": RESEARCH_CONTRACT_V1,
        "research_contract_digest": contract.contract_digest,
        "key": metric.name,
        "unit": metric.unit,
        "direction": metric.direction,
        "comparison_scope": metric.comparison_scope,
        "claims": claims,
        "correctness_required": metric.correctness_required,
        "ceiling_must_be_measured": metric.normalization_ceiling == "measured",
        "required_measured": list(metric.required_evidence),
    }


__all__ = [
    "CITATION_EDGE_V1",
    "IDEA_CANDIDATE_V1",
    "IDEA_GENERATION_LOCK_V1",
    "IDEA_GENERATION_PROVENANCE_V1",
    "IDEA_REJECTION_V1",
    "IDEA_SET_V1",
    "METRIC_CONTRACT_V1",
    "RESEARCH_ARTIFACT_REF_V1",
    "RESEARCH_CONTRACT_V1",
    "RETRIEVAL_RECORD_V1",
    "SURVEY_SNAPSHOT_V1",
    "CitationEdgeV1",
    "IdeaCandidateV1",
    "IdeaGenerationLockV1",
    "IdeaGenerationProvenanceV1",
    "IdeaRejectionV1",
    "IdeaSetV1",
    "MetricContractV1",
    "ResearchArtifactRefV1",
    "ResearchContractError",
    "ResearchContractV1",
    "RetrievalRecordV1",
    "SurveySnapshotV1",
    "canonical_digest",
    "load_survey_snapshot_ref",
    "metric_gate_projection",
    "mint_research_contract",
    "parse_idea_set",
    "parse_research_contract",
    "parse_research_contract_document",
    "parse_survey_snapshot",
    "validate_research_handoff",
]
