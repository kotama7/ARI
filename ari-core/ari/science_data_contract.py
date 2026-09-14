"""Canonical scientific-data hand-off contracts.

``ScienceDataV1`` deliberately keeps executed facts, deterministic derivations,
and stochastic interpretation in separate digest-bound sections.  A model
annotation can therefore be replaced, rejected, or replayed without changing
the identity of the measurements and claims that a paper is allowed to cite.

The legacy flat ``science_data.json`` shape is supported only by the explicit
``migrate_legacy_science_data`` reader.  New producers must emit v1 directly.
"""

from __future__ import annotations

import json
import math
from typing import Any, Literal

from pydantic import (
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from ari.claim_gate_contract import parse_metric_gate_contract
from ari.execution import MeasurementRecordV1
from ari.pipeline.claim_gate.numeric import (
    FORMULAS,
    formula_registry_digest,
    recompute,
    required_roles,
)
from ari.science_data_base import (
    DigestBoundScienceModel as _DigestBoundModel,
    SCIENCE_ARTIFACT_REF_V1,
    SCIENCE_DATA_V1,
    SCIENCE_DERIVED_V1,
    SCIENCE_INTERPRETATION_V1,
    SCIENCE_PROVENANCE_V1,
    SCIENCE_RAW_V1,
    SHA256_DIGEST_PATTERN,
    ZERO_DIGEST as _ZERO_DIGEST,
    ScienceArtifactRefV1,
    ScienceDataError,
    ScienceEnvironmentV1,
    StrictScienceModel as _StrictModel,
    canonical_science_digest,
    finite_json as _finite_json,
    safe_id as _safe_id,
)
from ari.science_data_derived import (
    ScienceClaimEvidenceV1,
    ScienceClaimV1,
    ScienceDerivedV1,
    ScienceEvidenceResultV1,
    ScienceInterpretationV1,
    ScienceMetricSummaryV1,
    ScienceNumericAssertionV1,
    ScienceOperandV1,
    ScienceProvenanceV1,
)


ScienceSourceKind = Literal["typed-measurement", "legacy-untyped"]


class ScienceConfigurationV1(_StrictModel):
    """One executed configuration and its exact evidence sources."""

    config_id: str
    run_id: str
    node_id: str
    rank: int = Field(ge=1)
    label: str = Field(default="", max_length=256)
    source_kind: ScienceSourceKind
    claim_eligible: bool
    parameters: dict[str, Any] = Field(default_factory=dict, max_length=10_000)
    measurements: dict[str, int | float] = Field(
        default_factory=dict, max_length=10_000
    )
    measurement_records: tuple[MeasurementRecordV1, ...] = Field(
        default_factory=tuple, max_length=10_000
    )
    predictions: dict[str, Any] = Field(default_factory=dict, max_length=10_000)
    scores: dict[str, Any] = Field(default_factory=dict, max_length=10_000)
    legacy_metrics: dict[str, int | float] = Field(
        default_factory=dict, max_length=10_000
    )
    environment: ScienceEnvironmentV1 = Field(default_factory=ScienceEnvironmentV1)
    source_artifacts: tuple[ScienceArtifactRefV1, ...] = Field(
        default_factory=tuple, max_length=10_000
    )
    provenance_labels: dict[str, str] = Field(default_factory=dict, max_length=10_000)

    @field_validator("config_id", "run_id", "node_id")
    @classmethod
    def _ids(cls, value: str, info: ValidationInfo) -> str:
        return _safe_id(value, info.field_name)

    @field_validator("parameters", "predictions", "scores")
    @classmethod
    def _json_fields(
        cls, value: dict[str, Any], info: ValidationInfo
    ) -> dict[str, Any]:
        return _finite_json(value, info.field_name)

    @field_validator("measurements", "legacy_metrics")
    @classmethod
    def _finite_metrics(
        cls, value: dict[str, int | float], info: ValidationInfo
    ) -> dict[str, int | float]:
        for metric, number in value.items():
            if (
                not metric
                or metric.startswith("_")
                or isinstance(number, bool)
                or not isinstance(number, (int, float))
                or not math.isfinite(float(number))
            ):
                raise ValueError(f"{info.field_name} contains an invalid metric")
        return value

    @model_validator(mode="after")
    def _source_consistent(self) -> "ScienceConfigurationV1":
        if self.source_kind == "typed-measurement":
            if not self.measurement_records:
                raise ValueError(
                    "typed measurement source requires measurement records"
                )
            metric_ids = [record.metric_id for record in self.measurement_records]
            if len(metric_ids) != len(set(metric_ids)):
                raise ValueError(
                    "typed measurement records must have unique metric IDs"
                )
            if any(
                record.execution_status != "completed"
                for record in self.measurement_records
            ):
                raise ValueError(
                    "claim-eligible measurements must have completed execution"
                )
            record_values = {
                record.metric_id: float(record.value)
                for record in self.measurement_records
            }
            if set(record_values) != set(self.measurements) or any(
                not math.isclose(
                    record_values[key],
                    float(self.measurements[key]),
                    rel_tol=0,
                    abs_tol=0,
                )
                for key in record_values
            ):
                raise ValueError("measurement projection differs from typed records")
            if not self.claim_eligible:
                raise ValueError("validated typed measurements must be claim eligible")
            if not any(
                source.role == "measurement-set" for source in self.source_artifacts
            ):
                raise ValueError(
                    "typed measurements require a measurement-set artifact"
                )
        elif self.claim_eligible:
            raise ValueError("legacy-untyped metrics cannot be claim eligible")
        if self.claim_eligible and not self.source_artifacts:
            raise ValueError(
                "claim-eligible measurements require content-addressed sources"
            )
        return self


class ScienceRawV1(_DigestBoundModel):
    digest_field = "raw_digest"

    schema_version: Literal["ari.science-raw/v1"] = SCIENCE_RAW_V1
    raw_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    tree_artifact: ScienceArtifactRefV1
    configurations: tuple[ScienceConfigurationV1, ...] = Field(
        min_length=1, max_length=100_000
    )
    node_report_status: Literal["complete", "partial", "missing", "legacy"]
    measurement_status: Literal["complete", "partial", "missing", "legacy"]

    @model_validator(mode="after")
    def _unique_configurations(self) -> "ScienceRawV1":
        config_ids = [item.config_id for item in self.configurations]
        node_ids = [item.node_id for item in self.configurations]
        if len(config_ids) != len(set(config_ids)):
            raise ValueError("science configuration IDs must be unique")
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("science node IDs must be unique")
        return self


class ScienceDataV1(_StrictModel):
    """Immutable hand-off from executed experiments to figures and papers."""

    schema_version: Literal["ari.science-data/v1"] = SCIENCE_DATA_V1
    run_id: str
    raw: ScienceRawV1
    derived: ScienceDerivedV1
    interpretation: ScienceInterpretationV1
    metric_contract: dict[str, Any] | None = None
    limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    provenance: ScienceProvenanceV1
    migration_status: Literal["native-v1", "legacy-explicit"] = "native-v1"
    deterministic_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    science_data_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @field_validator("run_id")
    @classmethod
    def _run_id(cls, value: str) -> str:
        return _safe_id(value, "run_id")

    @field_validator("metric_contract")
    @classmethod
    def _metric_contract(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        _finite_json(value, "metric_contract")
        try:
            contract = parse_metric_gate_contract(value)
        except ValueError as exc:
            raise ValueError(
                "metric_contract is not a canonical digest-bound contract"
            ) from exc
        return contract.model_dump(mode="json")

    @classmethod
    def create(cls, **values: Any) -> "ScienceDataV1":
        values = dict(values)
        values.setdefault("schema_version", SCIENCE_DATA_V1)
        values["deterministic_digest"] = _ZERO_DIGEST
        values["science_data_digest"] = _ZERO_DIGEST
        provisional = cls.model_validate(values, context={"bind_science_data": True})
        return provisional

    def deterministic_payload(self) -> dict[str, Any]:
        return self.model_dump(
            mode="json",
            exclude={"interpretation", "deterministic_digest", "science_data_digest"},
        )

    def complete_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"science_data_digest"})

    @model_validator(mode="after")
    def _digests_match(self, info: ValidationInfo) -> "ScienceDataV1":
        expected_deterministic = canonical_science_digest(self.deterministic_payload())
        if info.context and info.context.get("bind_science_data"):
            object.__setattr__(self, "deterministic_digest", expected_deterministic)
            expected_complete = canonical_science_digest(self.complete_payload())
            object.__setattr__(self, "science_data_digest", expected_complete)
        else:
            if self.deterministic_digest != expected_deterministic:
                raise ValueError("deterministic science-data digest mismatch")
            expected_complete = canonical_science_digest(self.complete_payload())
            if self.science_data_digest != expected_complete:
                raise ValueError("complete science-data digest mismatch")
        if self.interpretation.input_raw_digest != self.raw.raw_digest:
            raise ValueError("interpretation is not bound to this raw section")
        if any(config.run_id != self.run_id for config in self.raw.configurations):
            raise ValueError("configuration run identity differs from science-data run")
        from ari.science_data_validation import validate_science_data_links

        validate_science_data_links(self)
        return self


def parse_science_data(value: Any) -> ScienceDataV1:
    """Parse native v1 only; legacy input is intentionally not auto-migrated."""

    if isinstance(value, ScienceDataV1):
        return ScienceDataV1.model_validate(value.model_dump(mode="json"))
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ScienceDataError("science data is not valid JSON") from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCIENCE_DATA_V1:
        raise ScienceDataError(
            "science data is not native ari.science-data/v1; use the explicit legacy reader"
        )
    try:
        return ScienceDataV1.model_validate(value)
    except ValueError as exc:
        raise ScienceDataError(str(exc)) from exc


def science_data_projection(
    value: ScienceDataV1 | dict[str, Any] | str,
) -> dict[str, Any]:
    """Return the old flat view for gates during the bounded migration window.

    The projection is generated from canonical sections.  It never promotes the
    interpretation into measurements, summaries, claims, or numeric assertions.
    """

    science = parse_science_data(value)
    configurations: list[dict[str, Any]] = []
    config_nodes: dict[str, dict[str, Any]] = {}
    for config in science.raw.configurations:
        metrics = dict(config.legacy_metrics)
        metrics.update(config.measurements)
        item: dict[str, Any] = {
            "rank": config.rank,
            "config_id": config.config_id,
            "parameters": config.parameters,
            "metrics": metrics,
            "label": config.label,
            "environment": config.environment.model_dump(mode="json"),
            "_source_kind": config.source_kind,
            "_claim_eligible": config.claim_eligible,
        }
        if config.measurements:
            item["measurements"] = config.measurements
        if config.measurement_records:
            item["measurement_records"] = [
                record.model_dump(mode="json") for record in config.measurement_records
            ]
        if config.predictions:
            item["predictions"] = config.predictions
        if config.scores:
            item["scores"] = config.scores
        if config.provenance_labels:
            item["_provenance"] = config.provenance_labels
        configurations.append(item)
        config_nodes[config.config_id] = {
            "node_id": config.node_id,
            "run_id": config.run_id,
            "environment": config.environment.model_dump(mode="json"),
            "metrics": metrics,
            "claim_eligible": config.claim_eligible,
        }

    per_key_summary = {
        summary.metric_id: {
            "best_value": summary.best_value,
            "min": summary.minimum,
            "max": summary.maximum,
            "n": summary.count,
            "unit": summary.unit,
            "source_config_ids": list(summary.source_config_ids),
        }
        for summary in science.derived.metric_summaries
    }
    claims = [claim.model_dump(mode="json") for claim in science.derived.claims]
    numeric = [
        assertion.model_dump(mode="json")
        for assertion in science.derived.numeric_assertions
    ]
    projection: dict[str, Any] = {
        "schema_version": science.schema_version,
        "science_data_digest": science.science_data_digest,
        "deterministic_digest": science.deterministic_digest,
        "configurations": configurations,
        "per_key_summary": per_key_summary,
        "summary_stats": science.derived.summary_stats,
        "claims": claims,
        "numeric_assertions": numeric,
        "_config_nodes": config_nodes,
        "_anomalies": list(science.derived.anomalies),
        "limitations": list(science.limitations),
        "metric_contract": science.metric_contract,
        "interpretation": science.interpretation.model_dump(mode="json"),
        "migration_status": science.migration_status,
    }
    return projection


def migrate_legacy_science_data(
    value: dict[str, Any] | str,
    *,
    run_id: str,
    logical_name: str = "science_data.legacy.json",
) -> ScienceDataV1:
    """Explicit offline conversion of the pre-v1 flat checkpoint format."""

    from ari.science_data_migration import migrate_legacy_document

    return migrate_legacy_document(
        value,
        run_id=run_id,
        logical_name=logical_name,
    )


__all__ = [
    "FORMULAS",
    "SCIENCE_ARTIFACT_REF_V1",
    "SCIENCE_DATA_V1",
    "SCIENCE_DERIVED_V1",
    "SCIENCE_INTERPRETATION_V1",
    "SCIENCE_PROVENANCE_V1",
    "SCIENCE_RAW_V1",
    "ScienceArtifactRefV1",
    "ScienceClaimEvidenceV1",
    "ScienceClaimV1",
    "ScienceConfigurationV1",
    "ScienceDataError",
    "ScienceDataV1",
    "ScienceDerivedV1",
    "ScienceEnvironmentV1",
    "ScienceEvidenceResultV1",
    "ScienceInterpretationV1",
    "ScienceMetricSummaryV1",
    "ScienceNumericAssertionV1",
    "ScienceOperandV1",
    "ScienceProvenanceV1",
    "ScienceRawV1",
    "canonical_science_digest",
    "formula_registry_digest",
    "migrate_legacy_science_data",
    "parse_science_data",
    "recompute",
    "required_roles",
    "science_data_projection",
]
