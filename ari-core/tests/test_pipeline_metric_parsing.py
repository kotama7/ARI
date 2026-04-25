"""Tests for pipeline.parse_metric_from_experiment_md.

Regression: when the user pre-supplies experiment.md with a ``Metrics:``
line and the agent never calls generate_ideas, the pipeline used to
write an empty evaluation_criteria.json. Strategy 3 in
``ari.pipeline`` extracts the first metric token from experiment.md
as a last-resort source.
"""

from __future__ import annotations

import pytest

from ari.pipeline import parse_metric_from_experiment_md


class TestParseMetricFromExperimentMd:
    def test_basic_metrics_line(self) -> None:
        md = (
            "We propose an implementation of CSR-format SpMM for CPUs.\n"
            "Metrics: GB/s, GFlops/s\n"
        )
        assert parse_metric_from_experiment_md(md) == "GB/s"

    def test_singular_metric(self) -> None:
        md = "Goal: classify images.\nMetric: accuracy\n"
        assert parse_metric_from_experiment_md(md) == "accuracy"

    def test_dash_separator(self) -> None:
        md = "Metrics - throughput tokens/s, latency ms\n"
        assert parse_metric_from_experiment_md(md) == "throughput"

    def test_case_insensitive(self) -> None:
        md = "METRICS: F1, precision, recall\n"
        assert parse_metric_from_experiment_md(md) == "F1"

    def test_indented_line(self) -> None:
        # Leading whitespace is allowed (e.g. inside a bulleted block).
        md = "Body text.\n   metrics: BLEU, ROUGE\n"
        assert parse_metric_from_experiment_md(md) == "BLEU"

    def test_no_metrics_line_returns_empty(self) -> None:
        md = "Just a paragraph with no Metrics declaration.\n"
        assert parse_metric_from_experiment_md(md) == ""

    def test_empty_text(self) -> None:
        assert parse_metric_from_experiment_md("") == ""

    def test_first_line_only(self) -> None:
        md = "Metrics: throughput, latency\nMetrics: ignored, second\n"
        assert parse_metric_from_experiment_md(md) == "throughput"

    def test_strips_trailing_punctuation(self) -> None:
        md = "Metrics: GFlops/s.\n"
        assert parse_metric_from_experiment_md(md) == "GFlops/s"
