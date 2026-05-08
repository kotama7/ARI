"""Test the GUI `_api_node_report(run_id, node_id)` endpoint added for the
v0.7.0 Tree-page Report tab."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from ari.viz import api_state


def test_api_node_report_returns_loaded_json(tmp_path: Path):
    workspace = tmp_path / "ws"
    run_id = "exp"
    ckpt = workspace / "checkpoints" / run_id
    ckpt.mkdir(parents=True)
    wd = workspace / "experiments" / run_id / "node_a"
    wd.mkdir(parents=True)
    report = {
        "schema_version": 1,
        "node_id": "node_a",
        "label": "improve",
        "depth": 1,
        "status": "success",
        "files_changed": {"added": [], "modified": [], "deleted": [],
                          "inherited_unchanged": []},
        "metrics": {"x": 1.0},
        "artifacts": [],
        "self_assessment": {"succeeded": True, "headline": "ok",
                            "concerns": []},
    }
    (wd / "node_report.json").write_text(json.dumps(report))

    with patch.object(api_state, "_resolve_checkpoint_dir", return_value=ckpt):
        out = api_state._api_node_report(run_id, "node_a")

    assert out["run_id"] == run_id
    assert out["node_id"] == "node_a"
    assert out["report"]["schema_version"] == 1
    assert out["report"]["self_assessment"]["headline"] == "ok"


def test_api_node_report_missing_checkpoint_returns_error():
    with patch.object(api_state, "_resolve_checkpoint_dir", return_value=None):
        out = api_state._api_node_report("ghost", "node_a")
    assert "error" in out


def test_api_node_report_missing_report_returns_error(tmp_path: Path):
    workspace = tmp_path / "ws"
    ckpt = workspace / "checkpoints" / "exp"
    ckpt.mkdir(parents=True)
    # No experiments/<run_id>/<node_id>/node_report.json.
    with patch.object(api_state, "_resolve_checkpoint_dir", return_value=ckpt):
        out = api_state._api_node_report("exp", "node_missing")
    assert "error" in out
    assert out["node_id"] == "node_missing"
