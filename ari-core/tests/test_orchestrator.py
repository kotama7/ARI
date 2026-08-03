"""Regression tests for the dashboard's internal sub-experiment adapter.

The external MCP control plane has its own package-level contract, lifecycle,
authorization, and artifact suite under ``ari-skill-orchestrator/tests``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


@pytest.fixture
def gui_logs(tmp_path, monkeypatch):
    logs = tmp_path / "gui_sub_ckpts"
    logs.mkdir()
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(logs))
    from ari.viz import state as _st

    _st._sub_experiments.clear()
    return logs


def test_gui_launch_sub_experiment_writes_meta_and_returns_ok(gui_logs):
    from ari.viz.api_orchestrator import _api_launch_sub_experiment

    body = json.dumps(
        {
            "experiment_md": "# gui test\ngoal text",
            "max_recursion_depth": 2,
            "parent_run_id": None,
            "dry_run": True,
        }
    ).encode()
    result = _api_launch_sub_experiment(body)
    assert result["ok"] is True
    checkpoint = Path(result["checkpoint_dir"])
    assert (checkpoint / "meta.json").exists()
    metadata = json.loads((checkpoint / "meta.json").read_text())
    assert metadata["max_recursion_depth"] == 2
    assert metadata["recursion_depth"] == 0


def test_gui_launch_sub_experiment_blocks_at_limit(gui_logs):
    from ari.viz.api_orchestrator import _api_launch_sub_experiment

    body = json.dumps(
        {
            "experiment_md": "# blocked",
            "recursion_depth": 3,
            "max_recursion_depth": 3,
            "dry_run": True,
        }
    ).encode()
    result = _api_launch_sub_experiment(body)
    assert result["ok"] is False
    assert "Recursion limit" in result["error"]


def test_gui_list_sub_experiments_returns_disk_records(gui_logs):
    from ari.viz.api_orchestrator import (
        _api_launch_sub_experiment,
        _api_list_sub_experiments,
    )

    for index in range(2):
        time.sleep(0.01)
        _api_launch_sub_experiment(
            json.dumps(
                {
                    "experiment_md": f"# r{index}",
                    "max_recursion_depth": 3,
                    "dry_run": True,
                }
            ).encode()
        )
    listed = _api_list_sub_experiments()
    assert "sub_experiments" in listed
    assert len(listed["sub_experiments"]) >= 2
    for item in listed["sub_experiments"]:
        assert "run_id" in item
        assert "recursion_depth" in item
        assert "max_recursion_depth" in item


def test_gui_get_sub_experiment_by_id(gui_logs):
    from ari.viz.api_orchestrator import (
        _api_get_sub_experiment,
        _api_launch_sub_experiment,
    )

    result = _api_launch_sub_experiment(
        json.dumps(
            {
                "experiment_md": "# single",
                "max_recursion_depth": 3,
                "parent_run_id": "p1",
                "dry_run": True,
            }
        ).encode()
    )
    fetched = _api_get_sub_experiment(result["run_id"])
    assert fetched["run_id"] == result["run_id"]
    assert fetched["parent_run_id"] == "p1"


def test_gui_get_sub_experiment_unknown(gui_logs):
    from ari.viz.api_orchestrator import _api_get_sub_experiment

    assert "error" in _api_get_sub_experiment("not_a_real_id")


def test_gui_list_sub_experiments_prunes_deleted(gui_logs):
    """Deleted checkpoint dirs must disappear from sub-experiment listing."""

    import shutil

    from ari.viz.api_orchestrator import (
        _api_launch_sub_experiment,
        _api_list_sub_experiments,
    )

    kept = _api_launch_sub_experiment(
        json.dumps(
            {"experiment_md": "# keep", "max_recursion_depth": 3, "dry_run": True}
        ).encode()
    )
    time.sleep(0.01)
    deleted = _api_launch_sub_experiment(
        json.dumps(
            {
                "experiment_md": "# delete me",
                "max_recursion_depth": 3,
                "dry_run": True,
            }
        ).encode()
    )
    assert len(_api_list_sub_experiments()["sub_experiments"]) == 2
    shutil.rmtree(deleted["checkpoint_dir"])
    identifiers = [
        item["run_id"]
        for item in _api_list_sub_experiments()["sub_experiments"]
    ]
    assert kept["run_id"] in identifiers
    assert deleted["run_id"] not in identifiers


def test_gui_state_helpers_roundtrip():
    from ari.viz import state as _st

    _st._sub_experiments.clear()
    _st.set_sub_experiment("rid_1", {"run_id": "rid_1", "recursion_depth": 0})
    snapshot = _st.get_sub_experiments()
    assert "rid_1" in snapshot
    snapshot.pop("rid_1")
    assert "rid_1" in _st.get_sub_experiments()
    _st._sub_experiments.clear()
