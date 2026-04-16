"""Tests for the Experiment Artifact Repository (issue #4).

Covers:
- generate_ear MCP tool produces the expected directory structure
- README.md / RESULTS.md / environment.json are populated
- GUI /api/ear/{run_id} endpoint returns the same structure
- workflow.yaml schedules generate_ear before write_paper
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

# Make sure ari-skill-transform/src is importable
_TRANSFORM_SRC = (
    Path(__file__).parent.parent.parent / "ari-skill-transform" / "src"
).resolve()
if str(_TRANSFORM_SRC) not in sys.path:
    sys.path.insert(0, str(_TRANSFORM_SRC))


@pytest.fixture
def fake_checkpoint(tmp_path: Path) -> Path:
    """Build a minimal checkpoint directory with tree.json + science_data.json."""
    ckpt = tmp_path / "test_run"
    ckpt.mkdir()
    nodes = [
        {
            "id": "node_aaaaaaaa",
            "parent_id": None,
            "depth": 0,
            "label": "draft",
            "raw_label": "",
            "has_real_data": True,
            "metrics": {"throughput": 100.0, "_scientific_score": 0.45},
            "eval_summary": "baseline run",
            "artifacts": [{"type": "result", "stdout": "throughput=100"}],
        },
        {
            "id": "node_bbbbbbbb",
            "parent_id": "node_aaaaaaaa",
            "depth": 1,
            "label": "improve",
            "raw_label": "",
            "has_real_data": True,
            "metrics": {"throughput": 175.5, "_scientific_score": 0.82},
            "eval_summary": "improved by 75%",
            "artifacts": [{"type": "result", "stdout": "throughput=175.5"}],
        },
        {
            "id": "node_ccccccccc",
            "parent_id": "node_aaaaaaaa",
            "depth": 1,
            "label": "ablation",
            "raw_label": "",
            "has_real_data": False,
            "metrics": {},
            "eval_summary": "ablation no data",
            "artifacts": [],
        },
    ]
    (ckpt / "tree.json").write_text(
        json.dumps({"experiment_goal": "test goal", "nodes": nodes})
    )
    (ckpt / "science_data.json").write_text(
        json.dumps({"experiment_context": {"domain": "test"}})
    )
    return ckpt


# ──────────────────────────────────────────────────────────────────────────────
# generate_ear MCP tool
# ──────────────────────────────────────────────────────────────────────────────


def _get_generate_ear():
    """Import generate_ear from ari-skill-transform/src/server.py."""
    import importlib

    # Ensure transform/src is at position 0 to avoid shadowing by other
    # skill server.py modules that may already be on sys.path.
    ts = str(_TRANSFORM_SRC)
    if ts in sys.path:
        sys.path.remove(ts)
    sys.path.insert(0, ts)

    if "server" in sys.modules:
        del sys.modules["server"]
    module = importlib.import_module("server")
    fn = module.generate_ear
    # mcp.tool() may wrap the function — unwrap if needed.
    if hasattr(fn, "fn"):
        fn = fn.fn
    elif hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def test_generate_ear_creates_directory_structure(fake_checkpoint: Path):
    fn = _get_generate_ear()
    result = fn(str(fake_checkpoint))
    assert "error" not in result, result
    ear = Path(result["ear_dir"])
    assert ear.exists()
    # Required subdirectories
    assert (ear / "code").is_dir()
    assert (ear / "data").is_dir()
    assert (ear / "data" / "figures").is_dir()
    assert (ear / "logs").is_dir()
    assert (ear / "reproducibility").is_dir()


def test_generate_ear_writes_readme_and_results(fake_checkpoint: Path):
    fn = _get_generate_ear()
    result = fn(str(fake_checkpoint))
    ear = Path(result["ear_dir"])
    readme = ear / "README.md"
    results = ear / "RESULTS.md"
    assert readme.exists()
    assert results.exists()
    # README must mention the experiment goal or top result
    readme_text = readme.read_text()
    assert len(readme_text.strip()) > 20
    # RESULTS must include a metrics table
    results_text = results.read_text()
    assert "scientific_score" in results_text or "scientific" in results_text.lower()
    assert result["has_readme"] is True
    assert result["has_results"] is True


def test_generate_ear_environment_json_populated(fake_checkpoint: Path):
    fn = _get_generate_ear()
    fn(str(fake_checkpoint))
    env_path = fake_checkpoint / "ear" / "reproducibility" / "environment.json"
    assert env_path.exists()
    env = json.loads(env_path.read_text())
    assert "python_version" in env
    assert "platform" in env
    assert "cpu_count" in env
    # installed_packages may be empty if pip is unavailable, but the key must exist
    assert "installed_packages" in env


def test_generate_ear_consolidates_metrics(fake_checkpoint: Path):
    fn = _get_generate_ear()
    fn(str(fake_checkpoint))
    raw = json.loads(
        (fake_checkpoint / "ear" / "data" / "raw_metrics.json").read_text()
    )
    # Two nodes have metrics with throughput
    nodes = raw["nodes"]
    assert len(nodes) == 2
    summary = raw["summary"]
    assert "throughput" in summary
    assert summary["throughput"]["max"] == 175.5
    assert summary["throughput"]["min"] == 100.0
    assert summary["throughput"]["count"] == 2


def test_generate_ear_writes_eval_scores(fake_checkpoint: Path):
    fn = _get_generate_ear()
    fn(str(fake_checkpoint))
    scores = json.loads(
        (fake_checkpoint / "ear" / "logs" / "eval_scores.json").read_text()
    )
    # Two nodes have a scientific_score
    assert len(scores) == 2
    assert all("scientific_score" in s for s in scores)


def test_generate_ear_commands_md(fake_checkpoint: Path):
    fn = _get_generate_ear()
    fn(str(fake_checkpoint))
    cmds = (fake_checkpoint / "ear" / "reproducibility" / "commands.md").read_text()
    assert "Reproduction commands" in cmds
    # Top node id (node_bbbbbbbb) should appear in some form
    assert "bbbbbbbb" in cmds


def test_generate_ear_top_node_in_summary(fake_checkpoint: Path):
    fn = _get_generate_ear()
    result = fn(str(fake_checkpoint))
    # Top node by scientific_score is node_bbbbbbbb (0.82 > 0.45)
    assert result["top_node_id"] == "node_bbbbbbbb"


def test_generate_ear_missing_checkpoint(tmp_path: Path):
    fn = _get_generate_ear()
    result = fn(str(tmp_path / "does_not_exist"))
    assert "error" in result


# ──────────────────────────────────────────────────────────────────────────────
# GUI endpoint
# ──────────────────────────────────────────────────────────────────────────────


def test_api_ear_endpoint_structure(fake_checkpoint: Path, monkeypatch):
    """The viz GUI endpoint returns README/RESULTS and a file listing."""
    # Generate the EAR first
    fn = _get_generate_ear()
    fn(str(fake_checkpoint))

    from ari.viz import api_state

    # Force the resolver to find our fake checkpoint
    monkeypatch.setattr(
        api_state, "_resolve_checkpoint_dir", lambda run_id: fake_checkpoint
    )

    out = api_state._api_ear("test_run")
    assert "error" not in out, out
    assert out["readme"]
    assert out["results"]
    files = out["files"]
    # README and RESULTS at the top level
    paths = {f["path"] for f in files}
    assert "README.md" in paths
    assert "RESULTS.md" in paths
    # Subdirectories should appear
    assert any("environment.json" in p for p in paths)
    assert out["file_count"] >= 5


def test_api_ear_endpoint_no_checkpoint(monkeypatch):
    from ari.viz import api_state

    monkeypatch.setattr(api_state, "_resolve_checkpoint_dir", lambda run_id: None)
    out = api_state._api_ear("missing")
    assert out.get("error")


def test_api_ear_endpoint_no_ear_dir(tmp_path: Path, monkeypatch):
    from ari.viz import api_state

    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    monkeypatch.setattr(api_state, "_resolve_checkpoint_dir", lambda run_id: ckpt)
    out = api_state._api_ear("ckpt")
    assert out.get("error")


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline integration
# ──────────────────────────────────────────────────────────────────────────────


def test_workflow_yaml_runs_generate_ear_before_write_paper():
    wf_path = Path(__file__).parent.parent / "config" / "workflow.yaml"
    data = yaml.safe_load(wf_path.read_text())
    pipeline = data.get("pipeline", [])
    stage_order = [s.get("stage", "") for s in pipeline]
    assert "generate_ear" in stage_order, "generate_ear stage not registered"
    assert "write_paper" in stage_order
    assert stage_order.index("generate_ear") < stage_order.index(
        "write_paper"
    ), "generate_ear must run before write_paper"


def test_workflow_yaml_generate_ear_uses_transform_skill():
    wf_path = Path(__file__).parent.parent / "config" / "workflow.yaml"
    data = yaml.safe_load(wf_path.read_text())
    stage = next(
        s for s in data.get("pipeline", []) if s.get("stage") == "generate_ear"
    )
    assert stage.get("skill") == "transform-skill"
    assert stage.get("tool") == "generate_ear"
