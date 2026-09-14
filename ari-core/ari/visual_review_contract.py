"""Versioned, digest-bound contracts for visual scientific review."""

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


VISUAL_REVIEW_V1 = "ari.visual-review/v1"
VISUAL_REVIEW_BATCH_V1 = "ari.visual-review-batch/v1"
VISUAL_CRITERIA_PROFILE_V1 = "ari.visual-criteria-profile/v1"
VISUAL_ARTIFACT_REF_V1 = "ari.visual-artifact-ref/v1"
SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
ZERO_DIGEST = "sha256:" + "0" * 64
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")


class VisualReviewContractError(ValueError):
    """A visual-review document is invalid or has lost provenance."""


def canonical_visual_review_digest(value: Any) -> str:
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


class _StrictReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _DigestBoundReviewModel(_StrictReviewModel):
    digest_field: ClassVar[str]

    @classmethod
    def create(cls, **values: Any):
        values = dict(values)
        values[cls.digest_field] = ZERO_DIGEST
        return cls.model_validate(values, context={"bind_review_digest": True})

    def digest_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={self.digest_field})

    @model_validator(mode="after")
    def _digest_matches(self, info: ValidationInfo):
        expected = canonical_visual_review_digest(self.digest_payload())
        if info.context and info.context.get("bind_review_digest"):
            object.__setattr__(self, self.digest_field, expected)
        elif getattr(self, self.digest_field) != expected:
            raise ValueError(f"{self.digest_field} does not match review payload")
        return self


class VisualArtifactRefV1(_StrictReviewModel):
    schema_version: Literal["ari.visual-artifact-ref/v1"] = VISUAL_ARTIFACT_REF_V1
    role: Literal["review-target", "raw-model-response", "table-source"]
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
            raise ValueError("visual artifact path must be safe and relative")
        return value


class VisualCriterionV1(_StrictReviewModel):
    criterion_id: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1_024)
    required: bool = True


class VisualCriteriaProfileV1(_DigestBoundReviewModel):
    digest_field = "profile_digest"
    schema_version: Literal["ari.visual-criteria-profile/v1"] = (
        VISUAL_CRITERIA_PROFILE_V1
    )
    profile_id: str
    target_kind: Literal["figure", "table"]
    version: str = Field(min_length=1, max_length=64)
    criteria: tuple[VisualCriterionV1, ...] = Field(min_length=1, max_length=64)
    passing_score: float = Field(ge=0, le=1)
    profile_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("profile_id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("visual criteria profile_id is invalid")
        return value

    @model_validator(mode="after")
    def _unique_criteria(self) -> "VisualCriteriaProfileV1":
        ids = [item.criterion_id for item in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("visual criteria IDs must be unique")
        return self


class VisualRegionV1(_StrictReviewModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _inside(self) -> "VisualRegionV1":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("visual issue region lies outside the target")
        return self


class VisualIssueV1(_StrictReviewModel):
    issue_id: str
    criterion_id: str = Field(min_length=1, max_length=128)
    severity: Literal["info", "minor", "major", "blocking"]
    message: str = Field(min_length=1, max_length=4_096)
    suggestion: str = Field(default="", max_length=4_096)
    evidence: str = Field(default="", max_length=4_096)
    region: VisualRegionV1 | None = None
    page: int | None = Field(default=None, ge=1, le=100_000)

    @field_validator("issue_id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("visual issue_id is invalid")
        return value


class VisualModelUsageV1(_StrictReviewModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    cost_status: Literal["reported", "unavailable"] = "unavailable"

    @model_validator(mode="after")
    def _cost_status(self) -> "VisualModelUsageV1":
        if (self.cost_usd is not None) != (self.cost_status == "reported"):
            raise ValueError("visual review cost status and value differ")
        return self


class VisualReviewV1(_DigestBoundReviewModel):
    digest_field = "review_digest"
    schema_version: Literal["ari.visual-review/v1"] = VISUAL_REVIEW_V1
    target_kind: Literal["figure", "table"]
    target_id: str
    figure_id: str | None = None
    source_manifest_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    target_artifact: VisualArtifactRefV1
    context_digest: str = Field(pattern=SHA256_PATTERN)
    criteria_profile_id: str
    criteria_profile_digest: str = Field(pattern=SHA256_PATTERN)
    iteration: int = Field(default=0, ge=0, le=2)
    status: Literal[
        "completed",
        "artifact-error",
        "limit-error",
        "model-error",
        "schema-error",
    ]
    score: float | None = Field(default=None, ge=0, le=1)
    issues: tuple[VisualIssueV1, ...] = Field(default_factory=tuple, max_length=1_000)
    summary: str = Field(default="", max_length=8_192)
    model: str | None = Field(default=None, max_length=512)
    model_revision: str | None = Field(default=None, max_length=512)
    provider: str | None = Field(default=None, max_length=256)
    prompt_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    sampling: dict[str, Any] = Field(default_factory=dict, max_length=64)
    usage: VisualModelUsageV1 = Field(default_factory=VisualModelUsageV1)
    raw_response_artifact: VisualArtifactRefV1 | None = None
    error_kind: str | None = Field(default=None, max_length=256)
    error_message: str | None = Field(default=None, max_length=4_096)
    review_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("target_id", "criteria_profile_id")
    @classmethod
    def _ids(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("visual review identity is invalid")
        return value

    @field_validator("sampling")
    @classmethod
    def _sampling(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("visual review sampling must be finite JSON") from exc
        return value

    @model_validator(mode="after")
    def _status_coherent(self) -> "VisualReviewV1":
        if self.target_kind == "figure":
            if self.figure_id != self.target_id or self.source_manifest_digest is None:
                raise ValueError("figure review lacks manifest/figure identity")
        elif self.figure_id is not None or self.source_manifest_digest is not None:
            raise ValueError("table review cannot claim figure manifest identity")
        if self.status == "completed":
            if (
                self.score is None
                or not self.model
                or not self.prompt_digest
                or self.raw_response_artifact is None
                or self.error_kind is not None
            ):
                raise ValueError("completed visual review lacks model evidence")
        elif self.score is not None or self.error_kind is None:
            raise ValueError("failed visual review must retain an explicit typed error")
        if self.raw_response_artifact is not None and (
            self.raw_response_artifact.role != "raw-model-response"
        ):
            raise ValueError("visual raw response artifact has the wrong role")
        criteria = [item.criterion_id for item in self.issues]
        issue_ids = [item.issue_id for item in self.issues]
        if len(issue_ids) != len(set(issue_ids)) or any(not item for item in criteria):
            raise ValueError("visual issues must have unique identities")
        return self


class VisualReviewBatchV1(_DigestBoundReviewModel):
    digest_field = "batch_review_digest"
    schema_version: Literal["ari.visual-review-batch/v1"] = VISUAL_REVIEW_BATCH_V1
    source_batch_digest: str = Field(pattern=SHA256_PATTERN)
    iteration: int = Field(ge=0, le=2)
    reviews: tuple[VisualReviewV1, ...] = Field(min_length=1, max_length=100)
    aggregation: Literal["minimum-fail-closed"] = "minimum-fail-closed"
    score: float = Field(ge=0, le=1)
    failure_count: int = Field(ge=0)
    issues: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    suggestions: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    review_text: str = Field(default="", max_length=100_000)
    batch_review_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _aggregate_matches(self) -> "VisualReviewBatchV1":
        ids = [item.target_id for item in self.reviews]
        if len(ids) != len(set(ids)):
            raise ValueError("visual batch target IDs must be unique")
        if any(item.iteration != self.iteration for item in self.reviews):
            raise ValueError("visual batch mixes figure iterations")
        failures = sum(item.status != "completed" for item in self.reviews)
        if self.failure_count != failures:
            raise ValueError("visual batch failure count is inconsistent")
        expected = (
            0.0
            if failures
            else min(float(item.score) for item in self.reviews if item.score is not None)
        )
        if self.score != expected:
            raise ValueError("visual batch score is not minimum/fail-closed")
        return self


def parse_visual_review(value: Any) -> VisualReviewV1:
    try:
        if isinstance(value, str):
            value = json.loads(value)
        return VisualReviewV1.model_validate(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise VisualReviewContractError(f"invalid VisualReviewV1: {exc}") from exc


def parse_visual_review_batch(value: Any) -> VisualReviewBatchV1:
    try:
        if isinstance(value, str):
            value = json.loads(value)
        return VisualReviewBatchV1.model_validate(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise VisualReviewContractError(
            f"invalid VisualReviewBatchV1: {exc}"
        ) from exc


__all__ = [
    "VISUAL_ARTIFACT_REF_V1",
    "VISUAL_CRITERIA_PROFILE_V1",
    "VISUAL_REVIEW_BATCH_V1",
    "VISUAL_REVIEW_V1",
    "VisualArtifactRefV1",
    "VisualCriteriaProfileV1",
    "VisualCriterionV1",
    "VisualIssueV1",
    "VisualModelUsageV1",
    "VisualRegionV1",
    "VisualReviewBatchV1",
    "VisualReviewContractError",
    "VisualReviewV1",
    "canonical_visual_review_digest",
    "parse_visual_review",
    "parse_visual_review_batch",
]
