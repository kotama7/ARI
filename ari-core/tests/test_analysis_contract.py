"""Public scientific-analysis contract tests."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from ari.public.analysis import (
    AnalysisRequestV1,
    AnalysisResultV1,
    MetricSampleSetV1,
    RunComparisonRequestV1,
    StatisticalTestRequestV1,
    canonical_analysis_digest,
)


def _sample(unit: str = "ms") -> dict:
    return {
        "metric_id": "latency",
        "unit": unit,
        "observations": [{"value": 1}, {"value": 2}],
    }


def test_analysis_request_is_frozen_and_rejects_unknown_fields():
    request = AnalysisRequestV1(datasets=[_sample()])
    assert request.schema_version == "ari.analysis-request/v1"
    with pytest.raises(ValidationError):
        request.missing_policy = "drop"
    with pytest.raises(ValidationError, match="Extra inputs"):
        AnalysisRequestV1(datasets=[_sample()], surprise=True)


def test_sample_requires_exactly_one_input_and_an_explicit_unit():
    with pytest.raises(ValidationError, match="exactly one"):
        MetricSampleSetV1(metric_id="x", unit="s")
    with pytest.raises(ValidationError, match="exactly one"):
        MetricSampleSetV1(
            metric_id="x",
            unit="s",
            observations=[],
            source={
                "workspace": {"root": "/tmp"},
                "relative_path": "x.json",
                "expected_digest": "sha256:" + "0" * 64,
            },
        )
    with pytest.raises(ValidationError, match="unit"):
        MetricSampleSetV1(metric_id="x", unit="", observations=[])


def test_multiple_comparison_policy_is_mandatory():
    comparison = {
        "comparison_id": "a",
        "group_a": _sample(),
        "group_b": _sample(),
        "test_family": "mann_whitney",
    }
    with pytest.raises(ValidationError, match="explicit correction"):
        StatisticalTestRequestV1(
            comparisons=[comparison, {**comparison, "comparison_id": "b"}]
        )


def test_run_comparison_rejects_metric_or_unit_split_brain():
    base = {
        "run_id": "a",
        "metric_id": "latency",
        "unit": "ms",
        "value": 1,
        "backend_id": "cpu",
        "environment_digest": "sha256:" + "1" * 64,
    }
    with pytest.raises(ValidationError, match="units do not match"):
        RunComparisonRequestV1(
            runs=[base, {**base, "run_id": "b", "unit": "s"}], direction="lower"
        )


def test_canonical_digest_rejects_non_json_nan():
    with pytest.raises(ValueError):
        canonical_analysis_digest({"value": math.nan})


def test_result_kind_requires_exactly_one_matching_payload():
    common = {
        "input_digest": "sha256:" + "2" * 64,
        "library_versions": {"numpy": "1"},
    }
    with pytest.raises(ValidationError, match="content does not match"):
        AnalysisResultV1(kind="summary", **common)
