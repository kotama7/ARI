"""ari-skill-benchmark MCP Server.

Provides experiment result analysis, visualization, and statistical testing.
"""

from __future__ import annotations

import json
import os
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from mcp.server.fastmcp import FastMCP
from scipy import stats

mcp = FastMCP("benchmark-skill")


def _load_data(result_path: str) -> pd.DataFrame:
    """Load data from CSV, JSON, or npy file into a DataFrame."""
    ext = os.path.splitext(result_path)[1].lower()
    if ext == ".csv":
        return pd.read_csv(result_path)
    elif ext == ".json":
        with open(result_path, "r") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            return pd.DataFrame(raw)
        return pd.DataFrame(raw)
    elif ext == ".npy":
        arr = np.load(result_path, allow_pickle=True)
        if arr.ndim == 1:
            return pd.DataFrame({"value": arr})
        return pd.DataFrame(arr)
    else:
        raise ValueError(f"Unsupported file format: {ext}")


@mcp.tool()
def analyze_results(result_path: str, metrics: list[str]) -> dict[str, Any]:
    """Analyze a result file (CSV/JSON/npy) and return a summary with statistics.

    Args:
        result_path: Path to the result file (CSV, JSON, or npy).
        metrics: List of metric names to analyze (e.g. ["throughput", "latency"]).

    Returns:
        Dictionary with "summary" and "statistics" keys.
    """
    df = _load_data(result_path)

    summary: dict[str, Any] = {}
    statistics: dict[str, Any] = {}

    for metric in metrics:
        if metric not in df.columns:
            summary[metric] = {"error": f"metric '{metric}' not found in data"}
            continue

        col = pd.to_numeric(df[metric], errors="coerce").dropna()

        summary[metric] = {
            "count": int(len(col)),
            "mean": float(col.mean()),
            "std": float(col.std()),
            "min": float(col.min()),
            "max": float(col.max()),
        }

        statistics[metric] = {
            "median": float(col.median()),
            "q25": float(col.quantile(0.25)),
            "q75": float(col.quantile(0.75)),
            "variance": float(col.var()),
        }

    return {"summary": summary, "statistics": statistics}


@mcp.tool()
def plot(
    data: dict[str, Any],
    plot_type: str,
    output_path: str,
    title: str = "",
    xlabel: str = "",
    ylabel: str = "",
) -> dict[str, str]:
    """Generate a result graph and save it to a file.

    Args:
        data: Data to plot. For bar/line/scatter: {"x": [...], "y": [...]}. For heatmap: {"values": [[...], ...]}.
        plot_type: One of "bar", "line", "scatter", "heatmap".
        output_path: File path where the image will be saved.
        title: Chart title.
        xlabel: X-axis label.
        ylabel: Y-axis label.

    Returns:
        Dictionary with "image_path" key.
    """
    fig, ax = plt.subplots()

    if plot_type == "bar":
        x = data.get("x", list(range(len(data.get("y", [])))))
        y = data["y"]
        ax.bar(x, y)
    elif plot_type == "line":
        x = data.get("x", list(range(len(data.get("y", [])))))
        y = data["y"]
        ax.plot(x, y)
    elif plot_type == "scatter":
        ax.scatter(data["x"], data["y"])
    elif plot_type == "heatmap":
        values = np.array(data["values"])
        im = ax.imshow(values, aspect="auto")
        fig.colorbar(im, ax=ax)
    else:
        raise ValueError(f"Unsupported plot_type: {plot_type}")

    if title:
        ax.set_title(title)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)

    return {"image_path": output_path}


@mcp.tool()
def statistical_test(
    data_a: list[float],
    data_b: list[float],
    test: str,
) -> dict[str, Any]:
    """Perform a statistical significance test between two datasets.

    Args:
        data_a: First dataset (list of numbers).
        data_b: Second dataset (list of numbers).
        test: Test type — one of "ttest", "mannwhitney", "wilcoxon".

    Returns:
        Dictionary with "pvalue", "significant", and "test" keys.
    """
    a = np.array(data_a, dtype=float)
    b = np.array(data_b, dtype=float)

    if test == "ttest":
        stat, pvalue = stats.ttest_ind(a, b)
    elif test == "mannwhitney":
        stat, pvalue = stats.mannwhitneyu(a, b, alternative="two-sided")
    elif test == "wilcoxon":
        stat, pvalue = stats.wilcoxon(a, b)
    else:
        raise ValueError(f"Unsupported test: {test}")

    return {
        "pvalue": float(pvalue),
        "significant": bool(pvalue < 0.05),
        "test": test,
    }


if __name__ == "__main__":
    mcp.run()
