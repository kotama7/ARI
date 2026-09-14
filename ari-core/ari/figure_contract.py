"""Digest-bound contracts for scientific figure specifications and artifacts.

The contract intentionally accepts declarative plotting specifications only.
Model-generated Python, SVG, shell commands, and embedded image payloads are
not part of the public surface: a stochastic planner may select admitted fields,
but the fixed renderer remains the sole owner of numeric values and bytes.
"""

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


FIGURE_SPEC_V1 = "ari.figure-spec/v1"
FIGURE_MANIFEST_V1 = "ari.figure-manifest/v1"
FIGURE_BATCH_V1 = "ari.figure-batch/v1"
FIGURE_FEEDBACK_V1 = "ari.figure-feedback/v1"
FIGURE_ARTIFACT_V1 = "ari.figure-artifact/v1"
FIGURE_ENVIRONMENT_V1 = "ari.figure-environment/v1"
LEGACY_FIGURE_BATCH_V0 = "ari.figure-batch/legacy-v0"
SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
ZERO_DIGEST = "sha256:" + "0" * 64
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class FigureContractError(ValueError):
    """A figure document is malformed, unbound, or scientifically unsafe."""


def canonical_figure_digest(value: Any) -> str:
    """Return the canonical SHA-256 identity of a JSON-compatible value."""

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


def _finite_json(value: Any, field: str) -> Any:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be finite JSON") from exc
    return value


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("figure artifact path must be safe and relative")
    return value


class _StrictFigureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _DigestBoundFigureModel(_StrictFigureModel):
    digest_field: ClassVar[str]

    @classmethod
    def create(cls, **values: Any):
        values = dict(values)
        values[cls.digest_field] = ZERO_DIGEST
        return cls.model_validate(values, context={"bind_figure_digest": True})

    def digest_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={self.digest_field})

    @model_validator(mode="after")
    def _digest_matches(self, info: ValidationInfo):
        expected = canonical_figure_digest(self.digest_payload())
        if info.context and info.context.get("bind_figure_digest"):
            object.__setattr__(self, self.digest_field, expected)
        elif getattr(self, self.digest_field) != expected:
            raise ValueError(
                f"{self.digest_field} does not match the canonical payload"
            )
        return self


class FigureArtifactV1(_StrictFigureModel):
    schema_version: Literal["ari.figure-artifact/v1"] = FIGURE_ARTIFACT_V1
    role: Literal[
        "source-data",
        "spec",
        "png",
        "pdf",
        "raw-planner-response",
        "prompt",
    ]
    relative_path: str
    digest: str = Field(pattern=SHA256_PATTERN)
    media_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(ge=0)

    @field_validator("relative_path")
    @classmethod
    def _path(cls, value: str) -> str:
        return _safe_relative(value)


class FigureSourceV1(_StrictFigureModel):
    artifact_digest: str = Field(pattern=SHA256_PATTERN)
    data_digest: str = Field(pattern=SHA256_PATTERN)
    record_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=100_000)
    node_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=100_000)

    @field_validator("record_ids", "node_ids")
    @classmethod
    def _identities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or len(item) > 256 for item in value):
            raise ValueError("figure source identities must be non-empty and bounded")
        if len(value) != len(set(value)):
            raise ValueError("figure source identities must be unique")
        return value

    @model_validator(mode="after")
    def _has_pointer(self) -> "FigureSourceV1":
        if not self.record_ids and not self.node_ids:
            raise ValueError("figure source requires a record or node pointer")
        return self


class FigureAxisV1(_StrictFigureModel):
    label: str = Field(min_length=1, max_length=256)
    unit: str = Field(min_length=1, max_length=128)
    scale: Literal["linear", "log", "symlog"] = "linear"

    @field_validator("label", "unit")
    @classmethod
    def _trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("figure axis fields must not have surrounding whitespace")
        return value


class FigureUncertaintyV1(_StrictFigureModel):
    kind: Literal["none", "standard-deviation", "standard-error", "confidence-interval"]
    field: str | None = Field(default=None, max_length=256)
    confidence: float | None = Field(default=None, gt=0, lt=1)

    @model_validator(mode="after")
    def _coherent(self) -> "FigureUncertaintyV1":
        if self.kind == "none" and (self.field is not None or self.confidence is not None):
            raise ValueError("uncertainty=none cannot name an uncertainty field")
        if self.kind != "none" and self.field is None:
            raise ValueError("declared uncertainty requires a source field")
        if self.kind == "confidence-interval" and self.confidence is None:
            raise ValueError("confidence intervals require a confidence level")
        if self.kind != "confidence-interval" and self.confidence is not None:
            raise ValueError("confidence is valid only for confidence intervals")
        return self


class FigureSpecV1(_DigestBoundFigureModel):
    """One declarative plot over an immutable, content-addressed data slice."""

    digest_field = "spec_digest"
    schema_version: Literal["ari.figure-spec/v1"] = FIGURE_SPEC_V1
    figure_id: str
    revision: int = Field(default=0, ge=0, le=100)
    chart_type: Literal["bar", "line", "scatter", "hist", "errorbar", "heatmap"]
    data: dict[str, Any] = Field(max_length=10_000)
    source: FigureSourceV1
    x_field: str | None = Field(default=None, max_length=256)
    y_field: str = Field(min_length=1, max_length=256)
    x_axis: FigureAxisV1
    y_axis: FigureAxisV1
    value_unit: str = Field(min_length=1, max_length=128)
    aggregation: Literal["none", "mean", "median", "sum"] = "none"
    uncertainty: FigureUncertaintyV1 = Field(
        default_factory=lambda: FigureUncertaintyV1(kind="none")
    )
    title: str = Field(default="", max_length=512)
    caption: str = Field(default="", max_length=4_096)
    style_profile: Literal["ari-publication-v1"] = "ari-publication-v1"
    spec_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("figure_id")
    @classmethod
    def _figure_id(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("figure_id is invalid")
        return value

    @field_validator("data")
    @classmethod
    def _data_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("figure data must not be empty")
        return _finite_json(value, "figure data")

    @model_validator(mode="after")
    def _data_and_fields_match(self) -> "FigureSpecV1":
        if canonical_figure_digest(self.data) != self.source.data_digest:
            raise ValueError("figure source data digest does not match the data slice")
        required = {self.y_field}
        if self.x_field is not None:
            required.add(self.x_field)
        if self.uncertainty.field is not None:
            required.add(self.uncertainty.field)
        missing = sorted(required - set(self.data))
        if missing:
            raise ValueError(f"figure fields are absent from the data slice: {missing}")
        if self.chart_type in {"bar", "line", "scatter", "errorbar"} and self.x_field is None:
            raise ValueError("the selected chart type requires an x field")
        if self.chart_type == "errorbar" and self.uncertainty.kind == "none":
            raise ValueError("errorbar charts require declared uncertainty")
        if self.chart_type != "errorbar" and self.uncertainty.kind != "none":
            raise ValueError("uncertainty is rendered only by errorbar charts")
        if self.chart_type == "heatmap" and self.y_field != "values":
            raise ValueError("heatmap data must use the canonical values field")
        return self


class FigureEnvironmentV1(_DigestBoundFigureModel):
    digest_field = "environment_digest"
    schema_version: Literal["ari.figure-environment/v1"] = FIGURE_ENVIRONMENT_V1
    renderer_version: str = Field(min_length=1, max_length=128)
    python_version: str = Field(min_length=1, max_length=128)
    matplotlib_version: str = Field(min_length=1, max_length=128)
    backend: Literal["agg"] = "agg"
    font_family: str = Field(min_length=1, max_length=256)
    font_digest: str = Field(pattern=SHA256_PATTERN)
    platform: str = Field(min_length=1, max_length=512)
    container_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    environment_digest: str = Field(pattern=SHA256_PATTERN)


class FigureFeedbackV1(_DigestBoundFigureModel):
    digest_field = "feedback_digest"
    schema_version: Literal["ari.figure-feedback/v1"] = FIGURE_FEEDBACK_V1
    figure_id: str
    source_manifest_digest: str = Field(pattern=SHA256_PATTERN)
    review_digest: str = Field(pattern=SHA256_PATTERN)
    iteration: int = Field(ge=1, le=2)
    issues: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    suggestions: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    feedback_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("figure_id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("feedback figure_id is invalid")
        return value


class FigureManifestV1(_DigestBoundFigureModel):
    """Reproducible identity of one rendered figure revision."""

    digest_field = "manifest_digest"
    schema_version: Literal["ari.figure-manifest/v1"] = FIGURE_MANIFEST_V1
    spec: FigureSpecV1
    execution_mode: Literal["declarative-fixed-renderer"] = "declarative-fixed-renderer"
    planner: Literal["none", "llm-spec-only"] = "none"
    planner_model: str | None = Field(default=None, max_length=512)
    planner_model_revision: str | None = Field(default=None, max_length=512)
    prompt_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    sampling: dict[str, Any] = Field(default_factory=dict, max_length=128)
    feedback: FigureFeedbackV1 | None = None
    parent_manifest_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    environment: FigureEnvironmentV1
    artifacts: tuple[FigureArtifactV1, ...] = Field(min_length=4, max_length=16)
    limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    manifest_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("sampling")
    @classmethod
    def _sampling_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _finite_json(value, "figure planner sampling")

    @model_validator(mode="after")
    def _manifest_coherent(self) -> "FigureManifestV1":
        roles = [artifact.role for artifact in self.artifacts]
        required = {"source-data", "spec", "png", "pdf"}
        if not required.issubset(roles):
            raise ValueError("figure manifest lacks a required artifact role")
        if len(roles) != len(set(roles)):
            raise ValueError("figure artifact roles must be unique")
        if self.planner == "none":
            if any(
                item is not None
                for item in (self.planner_model, self.prompt_digest, self.feedback)
            ) or self.sampling:
                raise ValueError("deterministic figures cannot claim planner provenance")
        else:
            if not self.planner_model or not self.prompt_digest:
                raise ValueError("LLM-planned figures require model and prompt identity")
            if "raw-planner-response" not in roles or "prompt" not in roles:
                raise ValueError("LLM-planned figures require raw response and prompt artifacts")
        if self.feedback is None:
            if self.spec.revision != 0 or self.parent_manifest_digest is not None:
                raise ValueError("the first figure revision cannot claim a parent")
        else:
            if self.feedback.figure_id != self.spec.figure_id:
                raise ValueError("feedback belongs to a different figure")
            if self.feedback.iteration != self.spec.revision:
                raise ValueError("feedback iteration and figure revision differ")
            if self.parent_manifest_digest != self.feedback.source_manifest_digest:
                raise ValueError("feedback does not bind the parent manifest")
        return self


class FigureBatchV1(_DigestBoundFigureModel):
    digest_field = "batch_digest"
    schema_version: Literal["ari.figure-batch/v1"] = FIGURE_BATCH_V1
    revision: int = Field(ge=0, le=2)
    manifests: tuple[FigureManifestV1, ...] = Field(min_length=1, max_length=100)
    figures: dict[str, str] = Field(min_length=1, max_length=100)
    latex_snippets: dict[str, str] = Field(min_length=1, max_length=100)
    figure_kinds: dict[str, str] = Field(min_length=1, max_length=100)
    batch_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("figures")
    @classmethod
    def _figure_paths(cls, value: dict[str, str]) -> dict[str, str]:
        return {key: _safe_relative(path) for key, path in value.items()}

    @model_validator(mode="after")
    def _maps_match_manifests(self) -> "FigureBatchV1":
        ids = [item.spec.figure_id for item in self.manifests]
        if len(ids) != len(set(ids)):
            raise ValueError("figure batch IDs must be unique")
        expected = set(ids)
        if any(set(mapping) != expected for mapping in (
            self.figures,
            self.latex_snippets,
            self.figure_kinds,
        )):
            raise ValueError("figure batch maps must exactly match manifest IDs")
        for manifest in self.manifests:
            if manifest.spec.revision != self.revision:
                raise ValueError("figure batch mixes revisions")
            pdf = next(item for item in manifest.artifacts if item.role == "pdf")
            if self.figures[manifest.spec.figure_id] != pdf.relative_path:
                raise ValueError("figure path does not match its PDF artifact")
            if self.figure_kinds[manifest.spec.figure_id] != manifest.spec.chart_type:
                raise ValueError("figure kind does not match its specification")
        return self


class LegacyFigureBatchV0(_StrictFigureModel):
    """Read-only index for pre-v1 batches; never accepted as native evidence."""

    schema_version: Literal["ari.figure-batch/legacy-v0"] = LEGACY_FIGURE_BATCH_V0
    figures: dict[str, str]
    latex_snippets: dict[str, str] = Field(default_factory=dict)
    limitations: tuple[str, ...] = (
        "Legacy figures lack source/spec/environment/artifact digest binding.",
    )


def parse_figure_manifest(value: Any) -> FigureManifestV1:
    try:
        if isinstance(value, str):
            value = json.loads(value)
        return FigureManifestV1.model_validate(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FigureContractError(f"invalid FigureManifestV1: {exc}") from exc


def parse_figure_batch(value: Any) -> FigureBatchV1:
    try:
        if isinstance(value, str):
            value = json.loads(value)
        return FigureBatchV1.model_validate(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FigureContractError(f"invalid FigureBatchV1: {exc}") from exc


def read_legacy_figure_batch(value: Any) -> LegacyFigureBatchV0:
    """Explicit offline reader for the old schema-less figures mapping."""

    try:
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict) or value.get("schema_version"):
            raise ValueError("legacy figure input must be an unversioned object")
        return LegacyFigureBatchV0.model_validate(
            {
                "figures": value.get("figures") or {},
                "latex_snippets": value.get("latex_snippets") or {},
            }
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FigureContractError(f"invalid legacy figure batch: {exc}") from exc


__all__ = [
    "FIGURE_ARTIFACT_V1",
    "FIGURE_BATCH_V1",
    "FIGURE_ENVIRONMENT_V1",
    "FIGURE_FEEDBACK_V1",
    "FIGURE_MANIFEST_V1",
    "FIGURE_SPEC_V1",
    "LEGACY_FIGURE_BATCH_V0",
    "FigureArtifactV1",
    "FigureAxisV1",
    "FigureBatchV1",
    "FigureContractError",
    "FigureEnvironmentV1",
    "FigureFeedbackV1",
    "FigureManifestV1",
    "FigureSourceV1",
    "FigureSpecV1",
    "FigureUncertaintyV1",
    "LegacyFigureBatchV0",
    "canonical_figure_digest",
    "parse_figure_batch",
    "parse_figure_manifest",
    "read_legacy_figure_batch",
]
