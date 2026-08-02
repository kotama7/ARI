"""Deterministic renderer and benchmark-plot migration tests."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

_SERVER_PATH = Path(__file__).resolve().parents[1] / "src" / "server.py"
_SPEC = importlib.util.spec_from_file_location("ari_skill_plot_test_server", _SERVER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SERVER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SERVER)
render_figure = _SERVER.render_figure


def _request(tmp_path: Path, chart_type: str = "bar") -> dict:
    data = {"x": ["a", "b", "c"], "y": [1, 2, 3]}
    if chart_type == "heatmap":
        data = {"values": [[1, 2], [3, 4]]}
    elif chart_type == "hist":
        data = {"y": [1, 2, 2, 3, 4], "bins": 3}
    elif chart_type == "errorbar":
        data["yerr"] = [0.1, 0.2, 0.1]
    return {
        "figure_id": f"migration-{chart_type}",
        "chart_type": chart_type,
        "data": data,
        "source_digest": "sha256:" + "1" * 64,
        "source_record_ids": ["record-a", "record-b"],
        "title": "Benchmark migration",
        "x_label": "Configuration",
        "x_unit": "1",
        "y_label": "Latency",
        "y_unit": "ms",
        "value_unit": "ms",
        "caption": "Latency by configuration.",
        "workspace": {"root": str(tmp_path)},
        "relative_directory": "figures",
    }


@pytest.mark.parametrize("chart_type", ["bar", "line", "scatter", "heatmap", "hist", "errorbar"])
def test_renderer_covers_benchmark_and_scientific_chart_corpus(tmp_path, chart_type):
    manifest = render_figure(_request(tmp_path, chart_type))
    assert manifest["schema_version"] == "ari.figure-manifest/v1"
    assert manifest["chart_type"] == chart_type
    assert manifest["source"]["record_ids"] == ["record-a", "record-b"]
    assert manifest["render_environment"]["backend"] == "agg"
    for artifact in manifest["artifacts"]:
        payload = (tmp_path / artifact["relative_path"]).read_bytes()
        assert "sha256:" + hashlib.sha256(payload).hexdigest() == artifact["digest"]


def test_renderer_is_byte_replayable_in_one_environment(tmp_path):
    first = render_figure(_request(tmp_path, "line"))
    first_bytes = [
        (tmp_path / artifact["relative_path"]).read_bytes() for artifact in first["artifacts"]
    ]
    second = render_figure(_request(tmp_path, "line"))
    second_bytes = [
        (tmp_path / artifact["relative_path"]).read_bytes() for artifact in second["artifacts"]
    ]
    assert first == second
    assert first_bytes == second_bytes


def test_renderer_rejects_missing_units_nonfinite_and_empty_data(tmp_path):
    request = _request(tmp_path)
    request["y_unit"] = ""
    with pytest.raises(ValueError, match="unit"):
        render_figure(request)
    request = _request(tmp_path)
    request["data"]["y"][0] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        render_figure(request)
    request = _request(tmp_path)
    request["data"]["y"] = []
    with pytest.raises(ValueError, match="non-empty"):
        render_figure(request)


def test_renderer_rejects_workspace_escape_and_unknown_fields(tmp_path):
    request = _request(tmp_path)
    request["relative_directory"] = "../escape"
    with pytest.raises(ValueError, match="relative_directory"):
        render_figure(request)
    request = _request(tmp_path)
    request["surprise"] = True
    with pytest.raises(ValueError, match="unknown fields"):
        render_figure(request)
