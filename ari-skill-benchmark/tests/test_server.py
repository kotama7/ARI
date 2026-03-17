"""Tests for ari-skill-benchmark MCP server tools."""

from __future__ import annotations

import csv
import json
import os
import tempfile

import numpy as np
import pytest

from src.server import analyze_results, plot, statistical_test


# ── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "results.csv"
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["throughput", "latency"])
        writer.writeheader()
        for i in range(10):
            writer.writerow({"throughput": 100 + i, "latency": 10.0 + i * 0.5})
    return str(path)


@pytest.fixture
def json_file(tmp_path):
    path = tmp_path / "results.json"
    data = [
        {"throughput": 100 + i, "latency": 10.0 + i * 0.5} for i in range(10)
    ]
    with open(path, "w") as f:
        json.dump(data, f)
    return str(path)


@pytest.fixture
def npy_file(tmp_path):
    path = tmp_path / "results.npy"
    arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    np.save(str(path), arr)
    return str(path)


# ── analyze_results tests ────────────────────────────────────────────


class TestAnalyzeResults:
    def test_csv(self, csv_file):
        result = analyze_results(csv_file, ["throughput", "latency"])
        assert "summary" in result
        assert "statistics" in result
        assert "throughput" in result["summary"]
        assert "latency" in result["summary"]
        assert result["summary"]["throughput"]["count"] == 10
        assert result["summary"]["throughput"]["mean"] == pytest.approx(104.5)
        assert result["statistics"]["throughput"]["median"] == pytest.approx(104.5)

    def test_json(self, json_file):
        result = analyze_results(json_file, ["throughput"])
        assert result["summary"]["throughput"]["count"] == 10
        assert result["summary"]["throughput"]["min"] == pytest.approx(100.0)
        assert result["summary"]["throughput"]["max"] == pytest.approx(109.0)

    def test_npy(self, npy_file):
        result = analyze_results(npy_file, ["value"])
        assert result["summary"]["value"]["count"] == 5
        assert result["summary"]["value"]["mean"] == pytest.approx(3.0)

    def test_missing_metric(self, csv_file):
        result = analyze_results(csv_file, ["nonexistent"])
        assert "error" in result["summary"]["nonexistent"]

    def test_unsupported_format(self, tmp_path):
        path = tmp_path / "data.txt"
        path.write_text("hello")
        with pytest.raises(ValueError, match="Unsupported file format"):
            analyze_results(str(path), ["x"])


# ── plot tests ────────────────────────────────────────────────────────


class TestPlot:
    def test_bar(self, tmp_path):
        out = str(tmp_path / "bar.png")
        result = plot(
            data={"x": ["a", "b", "c"], "y": [1, 2, 3]},
            plot_type="bar",
            output_path=out,
            title="Bar Chart",
            xlabel="Category",
            ylabel="Value",
        )
        assert result["image_path"] == out
        assert os.path.isfile(out)

    def test_line(self, tmp_path):
        out = str(tmp_path / "line.png")
        result = plot(
            data={"x": [1, 2, 3], "y": [10, 20, 30]},
            plot_type="line",
            output_path=out,
        )
        assert os.path.isfile(result["image_path"])

    def test_scatter(self, tmp_path):
        out = str(tmp_path / "scatter.png")
        result = plot(
            data={"x": [1, 2, 3, 4], "y": [5, 6, 7, 8]},
            plot_type="scatter",
            output_path=out,
        )
        assert os.path.isfile(result["image_path"])

    def test_heatmap(self, tmp_path):
        out = str(tmp_path / "heatmap.png")
        result = plot(
            data={"values": [[1, 2], [3, 4]]},
            plot_type="heatmap",
            output_path=out,
        )
        assert os.path.isfile(result["image_path"])

    def test_bar_no_x(self, tmp_path):
        out = str(tmp_path / "bar_no_x.png")
        result = plot(
            data={"y": [10, 20, 30]},
            plot_type="bar",
            output_path=out,
        )
        assert os.path.isfile(result["image_path"])

    def test_unsupported_type(self, tmp_path):
        with pytest.raises(ValueError, match="Unsupported plot_type"):
            plot(
                data={"y": [1]},
                plot_type="pie",
                output_path=str(tmp_path / "x.png"),
            )

    def test_creates_parent_dirs(self, tmp_path):
        out = str(tmp_path / "sub" / "dir" / "chart.png")
        result = plot(
            data={"y": [1, 2]},
            plot_type="bar",
            output_path=out,
        )
        assert os.path.isfile(result["image_path"])


# ── statistical_test tests ───────────────────────────────────────────


class TestStatisticalTest:
    def test_ttest_significant(self):
        np.random.seed(42)
        a = np.random.normal(10, 1, 100).tolist()
        b = np.random.normal(12, 1, 100).tolist()
        result = statistical_test(a, b, "ttest")
        assert result["test"] == "ttest"
        assert result["pvalue"] < 0.05
        assert result["significant"] is True

    def test_ttest_not_significant(self):
        np.random.seed(42)
        a = np.random.normal(10, 1, 100).tolist()
        b = np.random.normal(10, 1, 100).tolist()
        result = statistical_test(a, b, "ttest")
        assert result["test"] == "ttest"
        assert result["significant"] is False

    def test_mannwhitney(self):
        np.random.seed(42)
        a = np.random.normal(10, 1, 50).tolist()
        b = np.random.normal(12, 1, 50).tolist()
        result = statistical_test(a, b, "mannwhitney")
        assert result["test"] == "mannwhitney"
        assert "pvalue" in result
        assert isinstance(result["significant"], bool)

    def test_wilcoxon(self):
        np.random.seed(42)
        a = np.random.normal(10, 1, 30).tolist()
        b = np.random.normal(12, 1, 30).tolist()
        result = statistical_test(a, b, "wilcoxon")
        assert result["test"] == "wilcoxon"
        assert "pvalue" in result

    def test_unsupported_test(self):
        with pytest.raises(ValueError, match="Unsupported test"):
            statistical_test([1, 2], [3, 4], "anova")

    def test_output_schema(self):
        result = statistical_test([1, 2, 3, 4, 5], [6, 7, 8, 9, 10], "ttest")
        assert set(result.keys()) == {"pvalue", "significant", "test"}
        assert isinstance(result["pvalue"], float)
        assert isinstance(result["significant"], bool)
        assert isinstance(result["test"], str)
