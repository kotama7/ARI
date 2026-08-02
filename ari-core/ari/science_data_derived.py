"""Derived, interpretation, and provenance sections of ``ScienceDataV1``."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator

from ari.pipeline.claim_gate.numeric import (
    FORMULAS,
    formula_registry_digest,
    required_roles,
)
from ari.science_data_base import (
    DigestBoundScienceModel,
    SCIENCE_DERIVED_V1,
    SCIENCE_INTERPRETATION_V1,
    SCIENCE_PROVENANCE_V1,
    SHA256_DIGEST_PATTERN,
    ScienceArtifactRefV1,
    ScienceEnvironmentV1,
    StrictScienceModel,
    finite_json,
    safe_id,
)


class ScienceMetricSummaryV1(StrictScienceModel):
    metric_id: str = Field(min_length=1, max_length=256)
    unit: str = Field(default="unknown", min_length=1, max_length=128)
    minimum: float
    maximum: float
    best_value: float
    count: int = Field(ge=1)
    direction: Literal["higher", "lower", "unspecified"] = "unspecified"
    source_config_ids: tuple[str, ...] = Field(min_length=1, max_length=100_000)

    @field_validator("minimum", "maximum", "best_value")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("derived summary values must be finite")
        return value

    @model_validator(mode="after")
    def _range(self) -> "ScienceMetricSummaryV1":
        if self.minimum > self.maximum:
            raise ValueError("metric summary minimum exceeds maximum")
        if not self.minimum <= self.best_value <= self.maximum:
            raise ValueError("metric summary best value lies outside its range")
        if self.count != len(self.source_config_ids):
            raise ValueError("metric summary count differs from its source set")
        if len(self.source_config_ids) != len(set(self.source_config_ids)):
            raise ValueError("metric summary sources must be unique")
        return self


class ScienceOperandV1(StrictScienceModel):
    run_id: str
    node_id: str
    metric_path: str = Field(min_length=1, max_length=1024)
    environment: ScienceEnvironmentV1 = Field(default_factory=ScienceEnvironmentV1)

    @field_validator("run_id", "node_id")
    @classmethod
    def _ids(cls, value: str, info: ValidationInfo) -> str:
        return safe_id(value, info.field_name)


class ScienceNumericAssertionV1(StrictScienceModel):
    id: str
    claim_id: str | None = None
    text_span: str = Field(default="", max_length=4096)
    metric: str = Field(min_length=1, max_length=256)
    value: float
    unit: str = Field(min_length=1, max_length=128)
    formula: str
    operands: dict[str, ScienceOperandV1]
    cross_environment: bool = False
    aggregation: dict[str, Any] = Field(default_factory=dict, max_length=128)
    tolerance: dict[str, float] = Field(default_factory=dict)

    @field_validator("id", "claim_id")
    @classmethod
    def _ids(cls, value: str | None, info: ValidationInfo) -> str | None:
        return safe_id(value, info.field_name) if value is not None else None

    @field_validator("value")
    @classmethod
    def _finite_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("numeric assertion value must be finite")
        return value

    @field_validator("formula")
    @classmethod
    def _formula(cls, value: str) -> str:
        if value not in FORMULAS:
            raise ValueError("numeric assertion formula is not registered")
        return value

    @field_validator("aggregation")
    @classmethod
    def _aggregation(cls, value: dict[str, Any]) -> dict[str, Any]:
        return finite_json(value, "aggregation")

    @field_validator("tolerance")
    @classmethod
    def _tolerance(cls, value: dict[str, float]) -> dict[str, float]:
        if set(value) - {"absolute", "relative"} or any(
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(float(number))
            or number < 0
            for number in value.values()
        ):
            raise ValueError("numeric assertion tolerance is invalid")
        return {key: float(number) for key, number in value.items()}

    @model_validator(mode="after")
    def _roles(self) -> "ScienceNumericAssertionV1":
        if set(self.operands) != set(required_roles(self.formula)):
            raise ValueError("numeric assertion operand roles differ from formula")
        return self


class ScienceEvidenceResultV1(StrictScienceModel):
    run_id: str
    node_id: str
    metric_path: str = Field(min_length=1, max_length=1024)

    @field_validator("run_id", "node_id")
    @classmethod
    def _ids(cls, value: str, info: ValidationInfo) -> str:
        return safe_id(value, info.field_name)


class ScienceClaimEvidenceV1(StrictScienceModel):
    nodes: tuple[str, ...] = Field(default_factory=tuple, max_length=100_000)
    results: tuple[ScienceEvidenceResultV1, ...] = Field(
        default_factory=tuple, max_length=100_000
    )
    figures: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    artifacts: tuple[ScienceArtifactRefV1, ...] = Field(
        default_factory=tuple, max_length=10_000
    )

    @field_validator("nodes")
    @classmethod
    def _nodes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for node_id in value:
            safe_id(node_id, "nodes")
        if len(value) != len(set(value)):
            raise ValueError("claim evidence nodes must be unique")
        return value


class ScienceClaimV1(StrictScienceModel):
    id: str
    text: str = Field(min_length=1, max_length=100_000)
    section: str = Field(min_length=1, max_length=128)
    status: Literal["draft", "supported", "unsupported", "rejected"]
    supported_by: ScienceClaimEvidenceV1
    numeric_assertions: tuple[ScienceNumericAssertionV1, ...] = Field(
        default_factory=tuple, max_length=10_000
    )
    risk: str = Field(default="", max_length=10_000)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return safe_id(value, "claim id")


class ScienceDerivedV1(DigestBoundScienceModel):
    digest_field = "derived_digest"

    schema_version: Literal["ari.science-derived/v1"] = SCIENCE_DERIVED_V1
    derived_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    formula_registry_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    metric_summaries: tuple[ScienceMetricSummaryV1, ...] = Field(
        default_factory=tuple, max_length=10_000
    )
    summary_stats: dict[str, Any] = Field(default_factory=dict, max_length=10_000)
    claims: tuple[ScienceClaimV1, ...] = Field(
        default_factory=tuple, max_length=100_000
    )
    numeric_assertions: tuple[ScienceNumericAssertionV1, ...] = Field(
        default_factory=tuple, max_length=100_000
    )
    anomalies: tuple[dict[str, Any], ...] = Field(
        default_factory=tuple, max_length=100_000
    )

    @field_validator("summary_stats", "anomalies")
    @classmethod
    def _json_fields(cls, value: Any, info: ValidationInfo) -> Any:
        return finite_json(value, info.field_name)

    @model_validator(mode="after")
    def _claim_links(self) -> "ScienceDerivedV1":
        if self.formula_registry_digest != formula_registry_digest():
            raise ValueError("derived section uses a different formula registry")
        claim_ids = [claim.id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("science claim IDs must be unique")
        assertion_ids = [assertion.id for assertion in self.numeric_assertions]
        if len(assertion_ids) != len(set(assertion_ids)):
            raise ValueError("science numeric assertion IDs must be unique")
        known_claims = set(claim_ids)
        if any(
            assertion.claim_id is None or assertion.claim_id not in known_claims
            for assertion in self.numeric_assertions
        ):
            raise ValueError("flattened assertions must reference a known claim")
        nested = {
            assertion.id
            for claim in self.claims
            for assertion in claim.numeric_assertions
        }
        if nested != set(assertion_ids):
            raise ValueError("nested and flattened numeric assertion sets differ")
        flattened = {assertion.id: assertion for assertion in self.numeric_assertions}
        for claim in self.claims:
            for assertion in claim.numeric_assertions:
                flat = flattened[assertion.id]
                if flat.claim_id != claim.id or flat.model_dump(
                    mode="json", exclude={"claim_id"}
                ) != assertion.model_dump(mode="json", exclude={"claim_id"}):
                    raise ValueError("nested and flattened assertions differ")
        return self


class ScienceInterpretationV1(DigestBoundScienceModel):
    """Non-authoritative model annotation; never a numeric evidence source."""

    digest_field = "interpretation_digest"
    schema_version: Literal["ari.science-interpretation/v1"] = SCIENCE_INTERPRETATION_V1
    interpretation_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    status: Literal["ok", "unavailable", "invalid", "legacy-migrated"]
    claim_eligible: Literal[False] = False
    input_raw_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    prompt_digest: str | None = Field(default=None, pattern=SHA256_DIGEST_PATTERN)
    model: str | None = Field(default=None, max_length=512)
    model_revision: str | None = Field(default=None, max_length=512)
    provider: str | None = Field(default=None, max_length=256)
    sampling: dict[str, Any] = Field(default_factory=dict, max_length=128)
    evaluation_protocol: dict[str, Any] = Field(default_factory=dict, max_length=10_000)
    experiment_context: dict[str, Any] = Field(default_factory=dict, max_length=10_000)
    implementation_overview: dict[str, Any] | None = None
    raw_response_artifact: ScienceArtifactRefV1 | None = None
    error_kind: str | None = Field(default=None, max_length=256)
    error_message: str | None = Field(default=None, max_length=4096)

    @field_validator(
        "sampling",
        "evaluation_protocol",
        "experiment_context",
        "implementation_overview",
    )
    @classmethod
    def _json_fields(cls, value: Any, info: ValidationInfo) -> Any:
        if value is not None:
            finite_json(value, info.field_name)
        return value

    @model_validator(mode="after")
    def _status_consistent(self) -> "ScienceInterpretationV1":
        if self.status == "ok":
            if self.raw_response_artifact is None or self.error_kind is not None:
                raise ValueError(
                    "successful interpretation requires raw artifact and no error"
                )
        elif self.status in {"invalid", "unavailable"} and self.error_kind is None:
            raise ValueError("failed interpretation requires an error kind")
        return self


class ScienceProvenanceV1(StrictScienceModel):
    schema_version: Literal["ari.science-provenance/v1"] = SCIENCE_PROVENANCE_V1
    producer_tool_ref: str
    producer_version: str = Field(min_length=1, max_length=256)
    input_artifacts: tuple[ScienceArtifactRefV1, ...] = Field(
        min_length=1, max_length=100_000
    )
    skills_lock: ScienceArtifactRefV1 | None = None
    catalog_lock: ScienceArtifactRefV1 | None = None
    admission_artifacts: tuple[ScienceArtifactRefV1, ...] = Field(
        default_factory=tuple, max_length=100_000
    )
    cassette_artifacts: tuple[ScienceArtifactRefV1, ...] = Field(
        default_factory=tuple, max_length=100_000
    )

    @field_validator("producer_tool_ref")
    @classmethod
    def _tool_ref(cls, value: str) -> str:
        return safe_id(value, "producer_tool_ref")

    @model_validator(mode="after")
    def _unique_artifacts(self) -> "ScienceProvenanceV1":
        identities = [
            (artifact.relative_path, artifact.digest)
            for artifact in self.input_artifacts
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("science provenance input artifacts must be unique")
        return self


__all__ = [
    "ScienceClaimEvidenceV1",
    "ScienceClaimV1",
    "ScienceDerivedV1",
    "ScienceEvidenceResultV1",
    "ScienceInterpretationV1",
    "ScienceMetricSummaryV1",
    "ScienceNumericAssertionV1",
    "ScienceOperandV1",
    "ScienceProvenanceV1",
]
