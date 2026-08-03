"""Contract, reference, and edge-case tests for benchmark-skill."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError
from scipy import stats

from src import server
from src.server import analyze_results, compare_runs, statistical_test


def _observations(values, *, replicate_prefix: str | None = None):
    return [
        {
            "value": value,
            **(
                {"replicate_id": f"{replicate_prefix}-{index}"}
                if replicate_prefix is not None
                else {}
            ),
        }
        for index, value in enumerate(values)
    ]


def _dataset(values, *, metric="latency", unit="ms", **extra):
    return {
        "metric_id": metric,
        "unit": unit,
        "observations": _observations(values),
        **extra,
    }


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _source(path: Path, *, value_column: str | None = None, **extra):
    return {
        "workspace": {"root": str(path.parent)},
        "relative_path": path.name,
        "expected_digest": _digest(path.read_bytes()),
        **({"value_column": value_column} if value_column is not None else {}),
        **extra,
    }


class TestAnalyzeResults:
    def test_inline_summary_is_typed_and_unit_bearing(self):
        result = analyze_results(
            {
                "datasets": [
                    {
                        "metric_id": "throughput",
                        "unit": "GFLOP/s",
                        "observations": _observations(
                            [100, 101, 102, 103, 104], replicate_prefix="trial"
                        ),
                    }
                ],
                "confidence_level": 0.95,
            }
        )
        summary = result["summaries"][0]
        assert result["schema_version"] == "ari.analysis-result/v1"
        assert result["kind"] == "summary"
        assert result["input_digest"].startswith("sha256:")
        assert result["library_versions"]["numpy"] == np.__version__
        assert summary["metric_id"] == "throughput"
        assert summary["unit"] == "GFLOP/s"
        assert summary["count"] == 5
        assert summary["mean"] == pytest.approx(102.0)
        assert summary["std"] == pytest.approx(np.std([100, 101, 102, 103, 104], ddof=1))
        assert summary["mean_confidence_interval"][0] < 102
        assert summary["mean_confidence_interval"][1] > 102
        assert summary["independence_status"] == "declared"

    @pytest.mark.parametrize(
        ("suffix", "write", "column"),
        [
            (
                ".csv",
                lambda path: path.write_text("value,replicate\n1,a\n2,b\n3,c\n", encoding="utf-8"),
                "value",
            ),
            (
                ".json",
                lambda path: path.write_text(json.dumps({"value": [1, 2, 3]}), encoding="utf-8"),
                "value",
            ),
            (
                ".npy",
                lambda path: np.save(path, np.asarray([1.0, 2.0, 3.0])),
                None,
            ),
        ],
    )
    def test_digest_bound_typed_loaders(self, tmp_path, suffix, write, column):
        path = tmp_path / f"values{suffix}"
        write(path)
        source = _source(path, value_column=column)
        if suffix == ".csv":
            source["replicate_id_column"] = "replicate"
        result = analyze_results(
            {"datasets": [{"metric_id": "x", "unit": "1", "source": source}]}
        )
        assert result["summaries"][0]["mean"] == pytest.approx(2.0)
        assert result["summaries"][0]["source_digest"] == _digest(path.read_bytes())

    def test_source_digest_mismatch_fails_closed(self, tmp_path):
        path = tmp_path / "values.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        source = _source(path)
        source["expected_digest"] = "sha256:" + "0" * 64
        with pytest.raises(ValueError, match="source digest mismatch"):
            analyze_results(
                {"datasets": [{"metric_id": "x", "unit": "1", "source": source}]}
            )

    def test_missing_and_nonfinite_values_are_policy_controlled(self):
        request = {
            "datasets": [
                {
                    "metric_id": "x",
                    "unit": "s",
                    "observations": _observations([1.0, None, float("nan"), 3.0]),
                }
            ]
        }
        with pytest.raises(ValueError, match="missing or non-finite"):
            analyze_results(request)
        request["missing_policy"] = "drop"
        summary = analyze_results(request)["summaries"][0]
        assert summary["count"] == 2
        assert summary["missing_count"] == 2
        assert summary["mean"] == pytest.approx(2.0)

    @pytest.mark.parametrize("values", [[], [None, float("nan")]])
    def test_empty_or_all_missing_sample_is_an_explicit_error(self, values):
        with pytest.raises(ValueError, match="empty sample|only missing"):
            analyze_results(
                {
                    "datasets": [_dataset(values)],
                    "missing_policy": "drop",
                }
            )

    def test_missing_unit_is_rejected(self):
        with pytest.raises(ValidationError, match="unit"):
            analyze_results(
                {
                    "datasets": [
                        {"metric_id": "x", "unit": "", "observations": _observations([1])}
                    ]
                }
            )

    def test_constant_and_singleton_data_are_honest(self):
        result = analyze_results(
            {
                "datasets": [
                    _dataset([2, 2, 2], metric="constant", unit="1"),
                    _dataset([7], metric="singleton", unit="count"),
                ]
            }
        )
        constant, singleton = result["summaries"]
        assert constant["constant_data"] is True
        assert constant["std"] == 0
        assert singleton["std"] is None
        assert singleton["mean_confidence_interval"] is None

    def test_summary_properties_hold_across_sizes(self):
        rng = np.random.default_rng(20260802)
        for size in (2, 3, 17, 1_001):
            values = rng.normal(loc=4.0, scale=1.5, size=size)
            summary = analyze_results(
                {"datasets": [_dataset(values.tolist(), metric=f"m{size}", unit="V")]}
            )["summaries"][0]
            assert summary["minimum"] <= summary["q25"]
            assert summary["q25"] <= summary["median"] <= summary["q75"]
            assert summary["q75"] <= summary["maximum"]
            assert summary["mean"] == pytest.approx(float(np.mean(values)))
            assert summary["variance"] == pytest.approx(summary["std"] ** 2)

    def test_content_addressed_machine_and_table_artifacts(self, tmp_path):
        request = {
            "datasets": [_dataset([1, 2, 3], metric="x", unit="s")],
            "artifact_target": {
                "workspace": {"root": str(tmp_path)},
                "relative_directory": "reports",
            },
        }
        first = analyze_results(request)
        second = analyze_results(request)
        assert first == second
        assert {item["logical_role"] for item in first["artifacts"]} == {
            "analysis-json",
            "analysis-table",
        }
        for artifact in first["artifacts"]:
            payload = (tmp_path / artifact["relative_path"]).read_bytes()
            assert _digest(payload) == artifact["digest"]
            assert len(payload) == artifact["size_bytes"]


class TestStatisticalTest:
    def _request(self, a, b, *, family="welch_t", pairing="unpaired", **extra):
        return {
            "comparisons": [
                {
                    "comparison_id": "candidate-vs-baseline",
                    "group_a": _dataset(a),
                    "group_b": _dataset(b),
                    "test_family": family,
                    "pairing": pairing,
                }
            ],
            **extra,
        }

    def test_welch_reference_effect_ci_and_assumptions(self):
        a = [8.2, 8.7, 9.1, 9.4, 9.8, 10.0]
        b = [6.1, 6.5, 6.8, 7.2, 7.4, 7.7]
        expected = stats.ttest_ind(a, b, equal_var=False, alternative="two-sided")
        result = statistical_test(self._request(a, b))["comparisons"][0]
        assert result["statistic"] == pytest.approx(expected.statistic)
        assert result["p_value"] == pytest.approx(expected.pvalue)
        assert result["adjusted_p_value"] == pytest.approx(expected.pvalue)
        assert result["effect_size_name"] == "cohens_d"
        assert result["effect_size"] > 0
        assert result["confidence_interval_name"] == "mean_difference"
        assert result["confidence_interval"][0] > 0
        assert result["sample_count_a"] == len(a)
        assert "normality_a" in result["assumptions"]
        assert "equal_variance" in result["assumptions"]

    def test_mann_whitney_matches_scipy(self):
        a = [1, 2, 2, 4, 5]
        b = [6, 7, 7, 8, 9]
        expected = stats.mannwhitneyu(a, b, alternative="two-sided", method="auto")
        result = statistical_test(self._request(a, b, family="mann_whitney"))[
            "comparisons"
        ][0]
        assert result["statistic"] == pytest.approx(expected.statistic)
        assert result["p_value"] == pytest.approx(expected.pvalue)
        assert -1 <= result["effect_size"] <= 1
        assert all(-1 <= item <= 1 for item in result["confidence_interval"])

    def test_ordered_paired_test_and_length_mismatch(self):
        result = statistical_test(
            self._request(
                [4, 5, 6, 7, 8],
                [1, 2, 4, 4, 6],
                family="paired_t",
                pairing="ordered",
            )
        )["comparisons"][0]
        assert result["pairing"] == "ordered"
        assert result["effect_size_name"] == "cohens_dz"
        with pytest.raises(ValidationError, match="equal lengths"):
            statistical_test(
                self._request([1, 2], [1], family="paired_t", pairing="ordered")
            )

    def test_pair_id_alignment_is_order_independent(self):
        group_a = {
            "metric_id": "latency",
            "unit": "ms",
            "observations": [
                {"value": 4, "pair_id": "p2"},
                {"value": 3, "pair_id": "p1"},
                {"value": 9, "pair_id": "p3"},
            ],
        }
        group_b = {
            "metric_id": "latency",
            "unit": "ms",
            "observations": [
                {"value": 1, "pair_id": "p1"},
                {"value": 3, "pair_id": "p2"},
                {"value": 5, "pair_id": "p3"},
            ],
        }
        request = {
            "comparisons": [
                {
                    "comparison_id": "paired",
                    "group_a": group_a,
                    "group_b": group_b,
                    "test_family": "wilcoxon",
                    "pairing": "pair_id",
                }
            ]
        }
        result = statistical_test(request)["comparisons"][0]
        assert result["assumptions"]["pairing_verified"] is True
        assert result["sample_count_a"] == 3

    def test_unit_mismatch_is_rejected(self):
        request = self._request([1, 2, 3], [4, 5, 6])
        request["comparisons"][0]["group_b"]["unit"] = "s"
        with pytest.raises(ValidationError, match="units do not match"):
            statistical_test(request)

    def test_multiple_comparisons_require_and_apply_correction(self):
        comparison = self._request([1, 2, 3, 4], [4, 5, 6, 7], family="mann_whitney")[
            "comparisons"
        ][0]
        second = json.loads(json.dumps(comparison))
        second["comparison_id"] = "second"
        request = {"comparisons": [comparison, second]}
        with pytest.raises(ValidationError, match="explicit correction"):
            statistical_test(request)
        request["correction"] = "bonferroni"
        results = statistical_test(request)["comparisons"]
        assert results[0]["adjusted_p_value"] == pytest.approx(
            min(1.0, results[0]["p_value"] * 2)
        )
        assert results[0]["assumptions"]["multiple_comparison_correction"] == "bonferroni"

    @pytest.mark.parametrize("correction", ["holm", "benjamini_hochberg"])
    def test_correction_is_monotone_and_bounded(self, correction):
        comparisons = []
        for index, shift in enumerate((0.1, 1.0, 2.0)):
            comparisons.append(
                {
                    "comparison_id": f"c{index}",
                    "group_a": _dataset([1, 2, 3, 4, 5], metric="x"),
                    "group_b": _dataset([1 + shift, 2 + shift, 3 + shift, 4 + shift, 5 + shift], metric="x"),
                    "test_family": "mann_whitney",
                }
            )
        results = statistical_test(
            {"comparisons": comparisons, "correction": correction}
        )["comparisons"]
        assert all(0 <= item["adjusted_p_value"] <= 1 for item in results)
        assert all(item["adjusted_p_value"] >= item["p_value"] for item in results)

    def test_seeded_fixture_is_replayable_and_versions_are_recorded(self):
        rng = np.random.default_rng(42)
        a = rng.normal(10, 1, 100).tolist()
        b = rng.normal(12, 1, 100).tolist()
        request = self._request(a, b)
        first = statistical_test(request)
        second = statistical_test(request)
        assert first == second
        assert first["library_versions"]["numpy"] == np.__version__
        assert first["input_digest"] == second["input_digest"]

    def test_undefined_constant_parametric_and_wilcoxon_data_fail(self):
        with pytest.raises(ValueError, match="constant"):
            statistical_test(self._request([1, 1, 1], [1, 1, 1], family="welch_t"))
        with pytest.raises(ValueError, match="every paired difference is zero"):
            statistical_test(
                self._request([1, 2, 3], [1, 2, 3], family="wilcoxon", pairing="ordered")
            )


class TestCompareRuns:
    def _run(self, run_id, value, *, environment=None, backend="cpu", replicate=None, unit="ms"):
        return {
            "run_id": run_id,
            "metric_id": "latency",
            "unit": unit,
            "value": value,
            "backend_id": backend,
            "environment_digest": environment or ("sha256:" + "1" * 64),
            "replicate_id": replicate,
            "input_digest": "sha256:" + "2" * 64,
            "provenance_digest": "sha256:" + run_id[-1] * 64,
            "library_versions": {"numpy": np.__version__},
        }

    def test_rank_delta_and_shared_substrate_caveat(self):
        result = compare_runs(
            {
                "runs": [
                    self._run("run-a", 10, replicate="trial-a"),
                    self._run("run-b", 8, replicate="trial-b"),
                ],
                "direction": "lower",
                "baseline_run_id": "run-a",
            }
        )["run_comparison"]
        assert result["ranking"][0]["run_id"] == "run-b"
        assert result["ranking"][0]["delta"] == -2
        assert result["environment_compatible"] is True
        assert result["independence_status"] == "declared"
        assert result["environment_groups"][0]["shared_substrate"] is True
        assert result["environment_groups"][0]["independence_inference"] == "not-permitted"

    def test_missing_replicate_identity_is_not_misreported_as_independent(self):
        result = compare_runs(
            {
                "runs": [self._run("run-a", 10), self._run("run-b", 8)],
                "direction": "lower",
            }
        )["run_comparison"]
        assert result["independence_status"] == "not-established"
        assert result["independent_replicate_count"] is None

    def test_environment_mismatch_fails_or_is_explicitly_caveated(self):
        request = {
            "runs": [
                self._run("run-a", 10),
                self._run("run-b", 8, environment="sha256:" + "3" * 64, backend="gpu"),
            ],
            "direction": "lower",
        }
        with pytest.raises(ValueError, match="environments differ"):
            compare_runs(request)
        request["require_compatible_environment"] = False
        result = compare_runs(request)["run_comparison"]
        assert result["environment_compatible"] is False
        assert result["provenance_differences"]
        assert "backend_id" in result["provenance_differences"][0]["changes"]

    def test_run_units_must_match(self):
        with pytest.raises(ValidationError, match="units do not match"):
            compare_runs(
                {
                    "runs": [self._run("run-a", 10), self._run("run-b", 8, unit="s")],
                    "direction": "lower",
                }
            )


def test_public_inventory_has_no_duplicate_plot_tool():
    assert not hasattr(server, "plot")
