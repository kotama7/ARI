"""Immutable build records for evidence-grounded scientific papers."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


PAPER_ARTIFACT_V1 = "ari.paper-artifact/v1"
PAPER_MODEL_CALL_V1 = "ari.paper-model-call/v1"
PAPER_MODEL_CALL_BATCH_V1 = "ari.paper-model-call-batch/v1"
PAPER_REVISION_V1 = "ari.paper-revision/v1"
PAPER_COMPILE_V1 = "ari.paper-compile/v1"
PAPER_REVIEW_SET_V1 = "ari.paper-review-set/v1"
PAPER_BUILD_V1 = "ari.paper-build/v1"
SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
ZERO_DIGEST = "sha256:" + "0" * 64
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")


class PaperContractError(ValueError):
    """A paper build is malformed or has lost scientific provenance."""


def canonical_paper_digest(value: Any) -> str:
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


class _StrictPaperModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _DigestBoundPaperModel(_StrictPaperModel):
    digest_field: ClassVar[str]

    @classmethod
    def create(cls, **values: Any):
        values = dict(values)
        values[cls.digest_field] = ZERO_DIGEST
        return cls.model_validate(values, context={"bind_paper_digest": True})

    def digest_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={self.digest_field})

    @model_validator(mode="after")
    def _digest_matches(self, info: ValidationInfo):
        expected = canonical_paper_digest(self.digest_payload())
        if info.context and info.context.get("bind_paper_digest"):
            object.__setattr__(self, self.digest_field, expected)
        elif getattr(self, self.digest_field) != expected:
            raise ValueError(f"{self.digest_field} does not match paper payload")
        return self


PaperArtifactRole = Literal[
    "science-data",
    "figure-batch",
    "retrieval-records",
    "ear-manifest",
    "template",
    "rubric",
    "prompt",
    "raw-model-response",
    "draft-tex",
    "final-tex",
    "bibtex",
    "pdf",
    "compile-stdout",
    "compile-stderr",
    "claim-links",
    "hard-gate",
    "semantic-review",
    "text-review",
    "visual-review",
    "code-bundle-lock",
    "authoring-record",
    "manuscript-profile",
    "manuscript-context",
    "manuscript-readiness",
    "section-briefs",
    "manuscript-authoring-binding",
    "publication-decision",
]


class PaperArtifactV1(_StrictPaperModel):
    schema_version: Literal["ari.paper-artifact/v1"] = PAPER_ARTIFACT_V1
    role: PaperArtifactRole
    relative_path: str
    digest: str = Field(pattern=SHA256_PATTERN)
    media_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(ge=0)

    @field_validator("relative_path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("paper artifact path must be safe and relative")
        return value


class PaperModelUsageV1(_StrictPaperModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    cost_status: Literal["reported", "unavailable"] = "unavailable"

    @model_validator(mode="after")
    def _cost_matches_status(self) -> "PaperModelUsageV1":
        if (self.cost_usd is not None) != (self.cost_status == "reported"):
            raise ValueError("paper model cost and status differ")
        return self


class PaperModelCallV1(_DigestBoundPaperModel):
    digest_field = "call_digest"
    schema_version: Literal["ari.paper-model-call/v1"] = PAPER_MODEL_CALL_V1
    call_id: str
    purpose: Literal[
        "initial-authoring",
        "figure-insertion",
        "reflection",
        "refinement",
        "text-review",
    ]
    model: str = Field(min_length=1, max_length=512)
    model_revision: str | None = Field(default=None, max_length=512)
    provider: str = Field(min_length=1, max_length=256)
    prompt_digest: str = Field(pattern=SHA256_PATTERN)
    prompt_artifact: PaperArtifactV1
    raw_response_artifact: PaperArtifactV1
    sampling: dict[str, Any] = Field(default_factory=dict, max_length=64)
    usage: PaperModelUsageV1 = Field(default_factory=PaperModelUsageV1)
    call_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("call_id")
    @classmethod
    def _call_id(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("paper model call_id is invalid")
        return value

    @field_validator("sampling")
    @classmethod
    def _finite_sampling(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("paper sampling must be finite JSON") from exc
        return value

    @model_validator(mode="after")
    def _raw_role(self) -> "PaperModelCallV1":
        if (
            self.prompt_artifact.role != "prompt"
            or self.prompt_artifact.digest != self.prompt_digest
        ):
            raise ValueError("paper model call lacks exact prompt evidence")
        if self.raw_response_artifact.role != "raw-model-response":
            raise ValueError("paper model call lacks raw response evidence")
        return self


class PaperModelCallBatchV1(_DigestBoundPaperModel):
    """Ordered call provenance for one bounded paper operation."""

    digest_field = "batch_digest"
    schema_version: Literal["ari.paper-model-call-batch/v1"] = PAPER_MODEL_CALL_BATCH_V1
    operation: Literal["authoring", "refinement", "text-review"]
    calls: tuple[PaperModelCallV1, ...] = Field(default_factory=tuple, max_length=100)
    batch_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _unique_calls(self) -> "PaperModelCallBatchV1":
        call_ids = [call.call_id for call in self.calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("paper model call batch contains duplicate call IDs")
        return self


class PaperRevisionV1(_DigestBoundPaperModel):
    digest_field = "revision_digest"
    schema_version: Literal["ari.paper-revision/v1"] = PAPER_REVISION_V1
    revision: int = Field(ge=0, le=100)
    parent_revision_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    reason: Literal[
        "initial", "figure-insertion", "reflection", "refinement", "finalize"
    ]
    tex_artifact: PaperArtifactV1
    bib_artifact: PaperArtifactV1 | None = None
    model_call_id: str | None = None
    claim_anchors: tuple[str, ...] = Field(default_factory=tuple, max_length=100_000)
    citation_keys: tuple[str, ...] = Field(default_factory=tuple, max_length=100_000)
    figure_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    math_digest: str = Field(pattern=SHA256_PATTERN)
    revision_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _coherent(self) -> "PaperRevisionV1":
        if self.tex_artifact.role not in {"draft-tex", "final-tex"}:
            raise ValueError("paper revision tex artifact has the wrong role")
        if self.bib_artifact is not None and self.bib_artifact.role != "bibtex":
            raise ValueError("paper revision bibliography has the wrong role")
        if self.revision == 0 and self.parent_revision_digest is not None:
            raise ValueError("initial paper revision cannot name a parent")
        if self.revision > 0 and self.parent_revision_digest is None:
            raise ValueError("paper revision lacks a parent digest")
        for values in (self.claim_anchors, self.citation_keys, self.figure_ids):
            if len(values) != len(set(values)):
                raise ValueError("paper revision identities must be unique")
        return self


class PaperCompileV1(_DigestBoundPaperModel):
    digest_field = "compile_digest"
    schema_version: Literal["ari.paper-compile/v1"] = PAPER_COMPILE_V1
    status: Literal["completed", "failed", "timed-out", "tool-unavailable"]
    commands: tuple[tuple[str, ...], ...] = Field(min_length=1, max_length=8)
    execution_identities: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    log_artifacts: tuple[PaperArtifactV1, ...] = Field(min_length=2, max_length=32)
    pdf_artifact: PaperArtifactV1 | None = None
    environment_digest: str = Field(pattern=SHA256_PATTERN)
    compile_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _compile_status(self) -> "PaperCompileV1":
        if any(
            artifact.role not in {"compile-stdout", "compile-stderr"}
            for artifact in self.log_artifacts
        ):
            raise ValueError("paper compile log artifact has the wrong role")
        if self.status == "tool-unavailable":
            if self.execution_identities:
                raise ValueError("unavailable paper compiler cannot claim executions")
        elif len(self.execution_identities) != len(self.commands):
            raise ValueError("paper compile command provenance is incomplete")
        if self.status == "completed":
            if self.pdf_artifact is None or self.pdf_artifact.role != "pdf":
                raise ValueError("completed paper compile lacks a PDF")
        elif self.pdf_artifact is not None:
            raise ValueError("failed paper compile cannot claim a final PDF")
        return self


class PaperReviewSetV1(_StrictPaperModel):
    schema_version: Literal["ari.paper-review-set/v1"] = PAPER_REVIEW_SET_V1
    text_review: PaperArtifactV1 | None = None
    visual_review: PaperArtifactV1 | None = None
    semantic_review: PaperArtifactV1 | None = None
    hard_gate: PaperArtifactV1 | None = None
    visual_score: float | None = Field(default=None, ge=0, le=1)
    visual_passing_score: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _roles_match(self) -> "PaperReviewSetV1":
        expected = {
            "text_review": "text-review",
            "visual_review": "visual-review",
            "semantic_review": "semantic-review",
            "hard_gate": "hard-gate",
        }
        for field, role in expected.items():
            artifact = getattr(self, field)
            if artifact is not None and artifact.role != role:
                raise ValueError(f"paper {field} artifact has the wrong role")
        if (self.visual_score is None) != (self.visual_passing_score is None):
            raise ValueError(
                "paper visual score and passing score must be recorded together"
            )
        if self.visual_score is not None and self.visual_review is None:
            raise ValueError("paper visual acceptance lacks a visual review artifact")
        return self


class PaperGateSummaryV1(_StrictPaperModel):
    mode: Literal["off", "warn", "strict"]
    status: Literal["pass", "blocked", "error"]
    blocking_error_count: int = Field(ge=0)
    report_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _status_matches_count(self) -> "PaperGateSummaryV1":
        if self.status == "pass" and self.blocking_error_count:
            raise ValueError("passing paper gate reports blocking errors")
        if self.status == "blocked" and self.blocking_error_count == 0:
            raise ValueError("blocked paper gate lacks blocking errors")
        return self


class PaperNumericCoverageV1(_StrictPaperModel):
    result_mentions: int = Field(ge=0)
    linked_mentions: int = Field(ge=0)
    excluded_mentions: int = Field(ge=0)
    unresolved_anchors: int = Field(ge=0)
    uncovered_mentions: int = Field(ge=0)
    exclusion_policy_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _coverage_is_possible(self) -> "PaperNumericCoverageV1":
        if self.linked_mentions + self.excluded_mentions > self.result_mentions:
            raise ValueError("paper numeric coverage exceeds detected mentions")
        if self.excluded_mentions and self.exclusion_policy_digest is None:
            raise ValueError("excluded paper numbers require a policy digest")
        return self


class PaperBuildV1(_DigestBoundPaperModel):
    digest_field = "build_digest"
    schema_version: Literal["ari.paper-build/v1"] = PAPER_BUILD_V1
    build_id: str
    run_id: str
    build_revision: int = Field(ge=0, le=100)
    parent_build_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    status: Literal["draft", "blocked", "compile-error", "finalized"]
    input_artifacts: tuple[PaperArtifactV1, ...] = Field(min_length=4, max_length=32)
    venue_id: str
    venue_version: str = Field(min_length=1, max_length=128)
    template_digest: str = Field(pattern=SHA256_PATTERN)
    rubric_id: str
    rubric_version: str = Field(min_length=1, max_length=128)
    rubric_digest: str = Field(pattern=SHA256_PATTERN)
    ear_digest: str = Field(pattern=SHA256_PATTERN)
    revisions: tuple[PaperRevisionV1, ...] = Field(min_length=1, max_length=101)
    model_calls: tuple[PaperModelCallV1, ...] = Field(
        default_factory=tuple, max_length=101
    )
    compile: PaperCompileV1 | None = None
    reviews: PaperReviewSetV1 = Field(default_factory=PaperReviewSetV1)
    gate: PaperGateSummaryV1 | None = None
    numeric_coverage: PaperNumericCoverageV1 | None = None
    final_artifacts: tuple[PaperArtifactV1, ...] = Field(
        default_factory=tuple, max_length=16
    )
    blocking_reasons: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    build_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("build_id", "run_id", "venue_id", "rubric_id")
    @classmethod
    def _safe_ids(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("paper build identity is invalid")
        return value

    @model_validator(mode="after")
    def _coherent(self) -> "PaperBuildV1":
        if (self.build_revision == 0) != (self.parent_build_digest is None):
            raise ValueError("paper build parent lineage is inconsistent")
        input_roles = [artifact.role for artifact in self.input_artifacts]
        required_inputs = {
            "science-data",
            "figure-batch",
            "retrieval-records",
            "ear-manifest",
        }
        if not required_inputs.issubset(input_roles) or len(input_roles) != len(
            set(input_roles)
        ):
            raise ValueError(
                "paper build input artifact set is incomplete or duplicated"
            )
        revision_numbers = [revision.revision for revision in self.revisions]
        if revision_numbers != list(range(len(self.revisions))):
            raise ValueError("paper revisions must be contiguous and ordered")
        for index, revision in enumerate(self.revisions[1:], start=1):
            if (
                revision.parent_revision_digest
                != self.revisions[index - 1].revision_digest
            ):
                raise ValueError("paper revision does not bind its direct parent")
        call_ids = [call.call_id for call in self.model_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("paper model call IDs must be unique")
        if any(
            revision.model_call_id is not None
            and revision.model_call_id not in set(call_ids)
            for revision in self.revisions
        ):
            raise ValueError("paper revision names an unknown model call")
        if self.status == "finalized":
            if self.blocking_reasons:
                raise ValueError("finalized paper cannot retain blocking reasons")
            if (
                self.gate is None
                or self.gate.mode == "off"
                or self.gate.status != "pass"
            ):
                raise ValueError("finalized paper lacks a passing hard gate")
            if self.numeric_coverage is None or (
                self.numeric_coverage.unresolved_anchors
                or self.numeric_coverage.uncovered_mentions
            ):
                raise ValueError("finalized paper has incomplete numeric coverage")
            if self.compile is None or self.compile.status != "completed":
                raise ValueError("finalized paper lacks a completed compile")
            final_roles = {artifact.role for artifact in self.final_artifacts}
            if not {"final-tex", "bibtex", "pdf"}.issubset(final_roles):
                raise ValueError("finalized paper artifact lock is incomplete")
        elif self.status in {"blocked", "compile-error"} and not self.blocking_reasons:
            raise ValueError("non-final paper must explain why it is blocked")
        return self


def parse_paper_build(value: Any) -> PaperBuildV1:
    try:
        if isinstance(value, str):
            value = json.loads(value)
        return PaperBuildV1.model_validate(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PaperContractError(f"invalid PaperBuildV1: {exc}") from exc


def parse_paper_model_call_batch(value: Any) -> PaperModelCallBatchV1:
    try:
        if isinstance(value, str):
            value = json.loads(value)
        return PaperModelCallBatchV1.model_validate(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PaperContractError(f"invalid PaperModelCallBatchV1: {exc}") from exc


__all__ = [
    "PAPER_ARTIFACT_V1",
    "PAPER_BUILD_V1",
    "PAPER_COMPILE_V1",
    "PAPER_MODEL_CALL_BATCH_V1",
    "PAPER_MODEL_CALL_V1",
    "PAPER_REVIEW_SET_V1",
    "PAPER_REVISION_V1",
    "PaperArtifactV1",
    "PaperBuildV1",
    "PaperCompileV1",
    "PaperContractError",
    "PaperGateSummaryV1",
    "PaperModelCallBatchV1",
    "PaperModelCallV1",
    "PaperModelUsageV1",
    "PaperNumericCoverageV1",
    "PaperReviewSetV1",
    "PaperRevisionV1",
    "canonical_paper_digest",
    "parse_paper_build",
    "parse_paper_model_call_batch",
]
