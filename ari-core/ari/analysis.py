"""Versioned deterministic statistical-analysis contracts.

The models in this module describe scientific inputs and outputs independently
of a particular statistics MCP implementation.  File-backed samples are always
bound to a closed workspace and an expected digest; callers therefore cannot
silently analyse a different file on replay.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ari.execution import WorkspaceRefV1


ANALYSIS_REQUEST_V1 = "ari.analysis-request/v1"
STATISTICAL_TEST_REQUEST_V1 = "ari.statistical-test-request/v1"
RUN_COMPARISON_REQUEST_V1 = "ari.run-comparison-request/v1"
ANALYSIS_RESULT_V1 = "ari.analysis-result/v1"

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")


def canonical_analysis_digest(value: Any) -> str:
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


def _validate_digest(value: str | None, field: str) -> str | None:
    if value is not None and not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"{field} must use sha256:<64 lowercase hex> format")
    return value


def _validate_id(value: str | None, field: str) -> str | None:
    if value is not None and not _ID_RE.fullmatch(value):
        raise ValueError(f"{field} contains unsupported characters")
    return value


class AnalysisDataSourceV1(BaseModel):
    """Digest-bound numeric column in a closed workspace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace: WorkspaceRefV1
    relative_path: str
    format: Literal["auto", "csv", "json", "npy"] = "auto"
    value_column: str | None = None
    replicate_id_column: str | None = None
    pair_id_column: str | None = None
    backend_id_column: str | None = None
    environment_digest_column: str | None = None
    expected_digest: str
    max_bytes: int = Field(default=64 * 1024 * 1024, ge=1, le=256 * 1024 * 1024)

    @field_validator("relative_path")
    @classmethod
    def _safe_path(cls, value: str) -> str:
        pure = PurePosixPath(value)
        if (
            not value
            or pure.is_absolute()
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            raise ValueError("analysis source path must be safe and relative")
        return value

    @field_validator("expected_digest")
    @classmethod
    def _digest(cls, value: str) -> str:
        assert _validate_digest(value, "expected_digest") is not None
        return value

    @field_validator(
        "value_column",
        "replicate_id_column",
        "pair_id_column",
        "backend_id_column",
        "environment_digest_column",
    )
    @classmethod
    def _column(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or len(value) > 256):
            raise ValueError("analysis source column name is invalid")
        return value


class AnalysisObservationV1(BaseModel):
    """One observed value and the identities needed to assess independence."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=True)

    value: float | None
    replicate_id: str | None = None
    pair_id: str | None = None
    backend_id: str | None = None
    environment_digest: str | None = None

    @field_validator("replicate_id", "pair_id", "backend_id")
    @classmethod
    def _identity(cls, value: str | None, info: Any) -> str | None:
        return _validate_id(value, info.field_name)

    @field_validator("environment_digest")
    @classmethod
    def _environment_digest(cls, value: str | None) -> str | None:
        return _validate_digest(value, "environment_digest")


class MetricSampleSetV1(BaseModel):
    """A unit-bearing metric sample supplied inline or by immutable source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_id: str
    unit: str
    observations: list[AnalysisObservationV1] | None = Field(
        default=None, max_length=1_000_000
    )
    source: AnalysisDataSourceV1 | None = None

    @field_validator("metric_id")
    @classmethod
    def _metric_id(cls, value: str) -> str:
        checked = _validate_id(value, "metric_id")
        assert checked is not None
        return checked

    @field_validator("unit")
    @classmethod
    def _unit(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 128:
            raise ValueError("measurement unit must be explicit and non-empty")
        return value

    @model_validator(mode="after")
    def _one_input(self) -> "MetricSampleSetV1":
        if (self.observations is None) == (self.source is None):
            raise ValueError("sample set requires exactly one of observations or source")
        return self


class AnalysisArtifactTargetV1(BaseModel):
    """Optional closed-workspace destination for deterministic result artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace: WorkspaceRefV1
    relative_directory: str = "analysis"

    @field_validator("relative_directory")
    @classmethod
    def _directory(cls, value: str) -> str:
        pure = PurePosixPath(value)
        if (
            not value
            or pure.is_absolute()
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            raise ValueError("analysis artifact directory must be safe and relative")
        return value.rstrip("/")


class AnalysisRequestV1(BaseModel):
    """Deterministic summary request for one or more metrics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.analysis-request/v1"] = ANALYSIS_REQUEST_V1
    datasets: list[MetricSampleSetV1] = Field(min_length=1, max_length=1_024)
    missing_policy: Literal["error", "drop"] = "error"
    confidence_level: float = Field(default=0.95, gt=0.0, lt=1.0)
    analysis_plan_digest: str | None = None
    artifact_target: AnalysisArtifactTargetV1 | None = None

    @field_validator("analysis_plan_digest")
    @classmethod
    def _plan_digest(cls, value: str | None) -> str | None:
        return _validate_digest(value, "analysis_plan_digest")

    @model_validator(mode="after")
    def _unique_metrics(self) -> "AnalysisRequestV1":
        metric_ids = [dataset.metric_id for dataset in self.datasets]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("analysis request metric_id values must be unique")
        return self


class StatisticalComparisonV1(BaseModel):
    """One pre-declared two-sample or paired comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    comparison_id: str
    group_a: MetricSampleSetV1
    group_b: MetricSampleSetV1
    test_family: Literal[
        "auto",
        "welch_t",
        "student_t",
        "paired_t",
        "mann_whitney",
        "wilcoxon",
    ] = "auto"
    pairing: Literal["unpaired", "ordered", "pair_id"] = "unpaired"
    alternative: Literal["two-sided", "less", "greater"] = "two-sided"
    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)
    confidence_level: float = Field(default=0.95, gt=0.0, lt=1.0)

    @field_validator("comparison_id")
    @classmethod
    def _comparison_id(cls, value: str) -> str:
        checked = _validate_id(value, "comparison_id")
        assert checked is not None
        return checked

    @model_validator(mode="after")
    def _compatible_samples(self) -> "StatisticalComparisonV1":
        if self.group_a.metric_id != self.group_b.metric_id:
            raise ValueError("comparison metric identities do not match")
        if self.group_a.unit != self.group_b.unit:
            raise ValueError("comparison units do not match")
        paired_family = self.test_family in {"paired_t", "wilcoxon"}
        if paired_family and self.pairing == "unpaired":
            raise ValueError("paired test family requires ordered or pair_id pairing")
        if not paired_family and self.pairing != "unpaired" and self.test_family != "auto":
            raise ValueError("paired input requires paired_t, wilcoxon, or auto")
        if (
            self.pairing == "ordered"
            and self.group_a.observations is not None
            and self.group_b.observations is not None
            and len(self.group_a.observations) != len(self.group_b.observations)
        ):
            raise ValueError("ordered paired samples must have equal lengths")
        return self


class StatisticalTestRequestV1(BaseModel):
    """A family of comparisons with an explicit multiplicity policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.statistical-test-request/v1"] = (
        STATISTICAL_TEST_REQUEST_V1
    )
    comparisons: list[StatisticalComparisonV1] = Field(min_length=1, max_length=10_000)
    correction: Literal["none", "bonferroni", "holm", "benjamini_hochberg"] = "none"
    missing_policy: Literal["error", "drop"] = "error"
    analysis_plan_digest: str | None = None
    artifact_target: AnalysisArtifactTargetV1 | None = None

    @field_validator("analysis_plan_digest")
    @classmethod
    def _plan_digest(cls, value: str | None) -> str | None:
        return _validate_digest(value, "analysis_plan_digest")

    @model_validator(mode="after")
    def _family_policy(self) -> "StatisticalTestRequestV1":
        ids = [item.comparison_id for item in self.comparisons]
        if len(ids) != len(set(ids)):
            raise ValueError("comparison_id values must be unique")
        if len(ids) > 1 and self.correction == "none":
            raise ValueError("multiple comparisons require an explicit correction")
        return self


class RunRecordV1(BaseModel):
    """One scalar run outcome with environment and provenance identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    run_id: str
    metric_id: str
    unit: str
    value: float
    backend_id: str
    environment_digest: str
    replicate_id: str | None = None
    execution_attempt_id: str | None = None
    input_digest: str | None = None
    provenance_digest: str | None = None
    library_versions: dict[str, str] = Field(default_factory=dict, max_length=256)

    @field_validator(
        "run_id", "metric_id", "backend_id", "replicate_id", "execution_attempt_id"
    )
    @classmethod
    def _ids(cls, value: str | None, info: Any) -> str | None:
        checked = _validate_id(value, info.field_name)
        if info.field_name in {"run_id", "metric_id", "backend_id"}:
            assert checked is not None
        return checked

    @field_validator("unit")
    @classmethod
    def _unit(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("run comparison unit must be explicit")
        return value

    @field_validator("environment_digest", "input_digest", "provenance_digest")
    @classmethod
    def _digests(cls, value: str | None, info: Any) -> str | None:
        checked = _validate_digest(value, info.field_name)
        if info.field_name == "environment_digest":
            assert checked is not None
        return checked

    @field_validator("library_versions")
    @classmethod
    def _versions(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not key or not item for key, item in value.items()):
            raise ValueError("library version names and values must be non-empty")
        return dict(sorted(value.items()))


class RunComparisonRequestV1(BaseModel):
    """Rank runs while retaining compatibility and independence caveats."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.run-comparison-request/v1"] = (
        RUN_COMPARISON_REQUEST_V1
    )
    runs: list[RunRecordV1] = Field(min_length=2, max_length=100_000)
    direction: Literal["higher", "lower"]
    baseline_run_id: str | None = None
    require_compatible_environment: bool = True
    analysis_plan_digest: str | None = None
    artifact_target: AnalysisArtifactTargetV1 | None = None

    @field_validator("baseline_run_id")
    @classmethod
    def _baseline(cls, value: str | None) -> str | None:
        return _validate_id(value, "baseline_run_id")

    @field_validator("analysis_plan_digest")
    @classmethod
    def _plan_digest(cls, value: str | None) -> str | None:
        return _validate_digest(value, "analysis_plan_digest")

    @model_validator(mode="after")
    def _compatible_runs(self) -> "RunComparisonRequestV1":
        run_ids = [run.run_id for run in self.runs]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("run_id values must be unique")
        if len({run.metric_id for run in self.runs}) != 1:
            raise ValueError("run comparison metric identities do not match")
        if len({run.unit for run in self.runs}) != 1:
            raise ValueError("run comparison units do not match")
        if self.baseline_run_id is not None and self.baseline_run_id not in run_ids:
            raise ValueError("baseline_run_id does not identify a supplied run")
        return self


class AnalysisArtifactV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str
    digest: str
    size_bytes: int = Field(ge=0)
    media_type: str
    logical_role: Literal["analysis-json", "analysis-table"]

    @field_validator("digest")
    @classmethod
    def _digest(cls, value: str) -> str:
        assert _validate_digest(value, "artifact digest") is not None
        return value


class AnalysisSummaryV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_id: str
    unit: str
    count: int = Field(ge=1)
    missing_count: int = Field(ge=0)
    mean: float
    std: float | None
    variance: float | None
    minimum: float
    q25: float
    median: float
    q75: float
    maximum: float
    mean_confidence_interval: tuple[float, float] | None
    constant_data: bool
    independence_status: Literal["verified", "declared", "not-established"]
    source_digest: str


class StatisticalComparisonResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    comparison_id: str
    metric_id: str
    unit: str
    test_family: str
    alternative: str
    pairing: str
    sample_count_a: int = Field(ge=1)
    sample_count_b: int = Field(ge=1)
    missing_count_a: int = Field(ge=0)
    missing_count_b: int = Field(ge=0)
    statistic: float
    p_value: float
    adjusted_p_value: float
    alpha: float
    significant: bool
    effect_size_name: str
    effect_size: float
    confidence_interval_name: str
    confidence_interval: tuple[float, float]
    assumptions: dict[str, Any]
    input_digest: str


class RunComparisonResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_id: str
    unit: str
    direction: Literal["higher", "lower"]
    ranking: list[dict[str, Any]]
    baseline_run_id: str
    environment_compatible: bool
    environment_groups: list[dict[str, Any]]
    independence_status: Literal["declared", "not-established"]
    independent_replicate_count: int | None
    provenance_differences: list[dict[str, Any]]


class AnalysisResultV1(BaseModel):
    """Machine-readable deterministic output shared by analysis providers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.analysis-result/v1"] = ANALYSIS_RESULT_V1
    kind: Literal["summary", "statistical-test", "run-comparison"]
    input_digest: str
    analysis_plan_digest: str | None = None
    library_versions: dict[str, str]
    summaries: list[AnalysisSummaryV1] = Field(default_factory=list)
    comparisons: list[StatisticalComparisonResultV1] = Field(default_factory=list)
    run_comparison: RunComparisonResultV1 | None = None
    artifacts: list[AnalysisArtifactV1] = Field(default_factory=list)

    @field_validator("input_digest", "analysis_plan_digest")
    @classmethod
    def _digests(cls, value: str | None, info: Any) -> str | None:
        checked = _validate_digest(value, info.field_name)
        if info.field_name == "input_digest":
            assert checked is not None
        return checked

    @model_validator(mode="after")
    def _kind_content(self) -> "AnalysisResultV1":
        populated = {
            "summary": bool(self.summaries),
            "statistical-test": bool(self.comparisons),
            "run-comparison": self.run_comparison is not None,
        }
        if not populated[self.kind] or sum(populated.values()) != 1:
            raise ValueError("analysis result content does not match its kind")
        return self


__all__ = [
    "ANALYSIS_REQUEST_V1",
    "ANALYSIS_RESULT_V1",
    "RUN_COMPARISON_REQUEST_V1",
    "STATISTICAL_TEST_REQUEST_V1",
    "AnalysisArtifactTargetV1",
    "AnalysisArtifactV1",
    "AnalysisDataSourceV1",
    "AnalysisObservationV1",
    "AnalysisRequestV1",
    "AnalysisResultV1",
    "AnalysisSummaryV1",
    "MetricSampleSetV1",
    "RunComparisonRequestV1",
    "RunComparisonResultV1",
    "RunRecordV1",
    "StatisticalComparisonResultV1",
    "StatisticalComparisonV1",
    "StatisticalTestRequestV1",
    "canonical_analysis_digest",
]
