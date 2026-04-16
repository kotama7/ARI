"""Tests for the ari-skill-orchestrator MCP server and the GUI sub-experiment API.

Covers:
  - Orchestrator: recursion budget gate (max_recursion_depth - 1 per child),
    meta.json creation, list_children, HTTP transport endpoints, get_status
    with score/metric details.
  - GUI: api_orchestrator endpoints (_api_list_sub_experiments,
    _api_launch_sub_experiment, _api_get_sub_experiment).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest


# ── Module loader for the orchestrator (it lives outside ari-core) ──────────

@pytest.fixture(scope="module")
def orchestrator():
    src = Path(__file__).resolve().parents[2] / "ari-skill-orchestrator" / "src" / "server.py"
    if not src.exists():
        pytest.skip(f"orchestrator server.py not found at {src}")
    spec = importlib.util.spec_from_file_location("ari_orchestrator_server", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ari_orchestrator_server"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def isolated_logs(tmp_path, monkeypatch):
    """Point ARI_ORCHESTRATOR_LOGS at a clean tmp dir, in dry-run mode."""
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setenv("ARI_ORCHESTRATOR_LOGS", str(logs))
    monkeypatch.setenv("ARI_ORCHESTRATOR_DRY_RUN", "1")
    # Strip any inherited recursion env so tests start clean.
    for k in ("ARI_PARENT_RUN_ID", "ARI_RECURSION_DEPTH", "ARI_MAX_RECURSION_DEPTH"):
        monkeypatch.delenv(k, raising=False)
    return logs


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1: recursion budget guard (max_recursion_depth - 1 per child)
# ─────────────────────────────────────────────────────────────────────────────

def test_recursion_zero_runs_but_child_blocked(orchestrator, isolated_logs):
    """max_recursion_depth=0: experiment runs, but child gets -1 and is blocked."""
    res = orchestrator.tool_run_experiment(
        "# no-recursion\ngoal",
        max_recursion_depth=0,
        logs_dir=isolated_logs,
    )
    assert res["status"] == "started"
    assert res["max_recursion_depth"] == 0
    assert res["child_max_recursion_depth"] == -1


def test_recursion_blocks_negative(orchestrator, isolated_logs):
    """Negative max_recursion_depth (child of a 0-budget parent) must be refused."""
    res = orchestrator.tool_run_experiment(
        "x", max_recursion_depth=-1, logs_dir=isolated_logs,
    )
    assert res["status"] == "blocked"
    assert not any(isolated_logs.iterdir())


def test_recursion_allows_positive(orchestrator, isolated_logs):
    res = orchestrator.tool_run_experiment(
        "# parent\ngoal", max_recursion_depth=3,
        logs_dir=isolated_logs,
    )
    assert res["status"] == "started"
    assert res.get("dry_run") is True
    assert res["max_recursion_depth"] == 3
    assert res["child_max_recursion_depth"] == 2


def test_child_gets_max_minus_one(orchestrator, isolated_logs):
    """Child process should receive max_recursion_depth - 1."""
    res = orchestrator.tool_run_experiment(
        "# parent", max_recursion_depth=5,
        logs_dir=isolated_logs,
    )
    assert res["child_max_recursion_depth"] == 4


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: meta.json + list_children + context propagation
# ─────────────────────────────────────────────────────────────────────────────

def test_meta_json_written(orchestrator, isolated_logs):
    res = orchestrator.tool_run_experiment(
        "# experiment\nstudy convergence behaviour",
        max_recursion_depth=4,
        parent_run_id="parent_abc",
        logs_dir=isolated_logs,
    )
    assert res["status"] == "started"
    ckpt = Path(res["checkpoint_dir"])
    meta_file = ckpt / "meta.json"
    assert meta_file.exists()
    meta = json.loads(meta_file.read_text())
    assert meta["run_id"] == res["run_id"]
    assert meta["parent_run_id"] == "parent_abc"
    assert meta["max_recursion_depth"] == 4
    assert "created_at" in meta
    assert (ckpt / "experiment.md").exists()


def test_env_propagation_makes_child_inherit_parent(orchestrator, isolated_logs, monkeypatch):
    """When ARI_PARENT_RUN_ID/ARI_MAX_RECURSION_DEPTH are set, the launcher honors them."""
    monkeypatch.setenv("ARI_PARENT_RUN_ID", "outer_parent")
    monkeypatch.setenv("ARI_MAX_RECURSION_DEPTH", "5")
    res = orchestrator.tool_run_experiment(
        "# inherits", logs_dir=isolated_logs,
    )
    assert res["status"] == "started"
    meta = json.loads((Path(res["checkpoint_dir"]) / "meta.json").read_text())
    assert meta["parent_run_id"] == "outer_parent"
    assert meta["max_recursion_depth"] == 5


def test_env_propagation_blocks_when_inherited_negative(orchestrator, isolated_logs, monkeypatch):
    """Child spawned by a max=0 parent inherits -1 and is blocked."""
    monkeypatch.setenv("ARI_MAX_RECURSION_DEPTH", "-1")
    res = orchestrator.tool_run_experiment("# blocked", logs_dir=isolated_logs)
    assert res["status"] == "blocked"


def test_env_propagation_zero_runs(orchestrator, isolated_logs, monkeypatch):
    """max=0 from env: experiment runs but cannot spawn children."""
    monkeypatch.setenv("ARI_MAX_RECURSION_DEPTH", "0")
    res = orchestrator.tool_run_experiment("# no children", logs_dir=isolated_logs)
    assert res["status"] == "started"
    assert res["child_max_recursion_depth"] == -1


def test_list_children_returns_correct_children(orchestrator, isolated_logs):
    parent_id = "parent_xyz"
    for i in range(2):
        time.sleep(0.01)
        orchestrator.tool_run_experiment(
            f"# child {i}\ngoal {i}",
            parent_run_id=parent_id,
            max_recursion_depth=3,
            logs_dir=isolated_logs,
        )
    orchestrator.tool_run_experiment(
        "# unrelated\nstandalone",
        max_recursion_depth=3,
        logs_dir=isolated_logs,
    )
    children = orchestrator.tool_list_children(parent_id, logs_dir=isolated_logs)
    assert len(children) == 2
    assert all(c["parent_run_id"] == parent_id for c in children)
    all_runs = orchestrator.tool_list_runs(logs_dir=isolated_logs)
    assert len(all_runs) == 3


def test_get_status_returns_recursion_metadata(orchestrator, isolated_logs):
    res = orchestrator.tool_run_experiment(
        "# rec test\nx",
        parent_run_id="grandparent",
        max_recursion_depth=4,
        logs_dir=isolated_logs,
    )
    status = orchestrator.tool_get_status(res["run_id"], logs_dir=isolated_logs)
    assert status["run_id"] == res["run_id"]
    assert status["parent_run_id"] == "grandparent"
    assert status["max_recursion_depth"] == 4
    assert "best_score" in status
    assert "score_stats" in status


def test_get_status_unknown_run(orchestrator, isolated_logs):
    status = orchestrator.tool_get_status("nonexistent_id", logs_dir=isolated_logs)
    assert "error" in status


def test_list_children_empty_for_unknown_parent(orchestrator, isolated_logs):
    assert orchestrator.tool_list_children("nobody", logs_dir=isolated_logs) == []


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3: LLM/resource config propagation
# ─────────────────────────────────────────────────────────────────────────────

def test_llm_config_propagated_in_response(orchestrator, isolated_logs):
    res = orchestrator.tool_run_experiment(
        "# config test",
        model="gpt-4o",
        llm_backend="openai",
        max_recursion_depth=2,
        logs_dir=isolated_logs,
    )
    assert res["status"] == "started"
    assert res["model"] == "gpt-4o"
    assert res["llm_backend"] == "openai"


def test_llm_config_inherited_from_env(orchestrator, isolated_logs, monkeypatch):
    monkeypatch.setenv("ARI_MODEL", "claude-sonnet-4-20250514")
    monkeypatch.setenv("ARI_BACKEND", "openai")
    res = orchestrator.tool_run_experiment(
        "# inherit config", max_recursion_depth=2, logs_dir=isolated_logs,
    )
    assert res["model"] == "claude-sonnet-4-20250514"
    assert res["llm_backend"] == "openai"


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4: HTTP/SSE transport
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def http_server(orchestrator, isolated_logs):
    srv = orchestrator.start_http_server(0)  # ephemeral port
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield port
    srv.shutdown()
    srv.server_close()


def _http_get(port: int, path: str) -> tuple[int, dict | str]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        body = r.read().decode()
    try:
        return r.status, json.loads(body)
    except json.JSONDecodeError:
        return r.status, body


def _http_post(port: int, path: str, body: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4: new MCP tools (list_files, read_file, get_ear, stop, skills, workflow)
# ─────────────────────────────────────────────────────────────────────────────

def test_list_files_returns_checkpoint_contents(orchestrator, isolated_logs):
    res = orchestrator.tool_run_experiment(
        "# files test", max_recursion_depth=1, logs_dir=isolated_logs,
    )
    ckpt = Path(res["checkpoint_dir"])
    # Create some files
    (ckpt / "results.json").write_text('{"nodes": {}}')
    (ckpt / "subdir").mkdir()
    (ckpt / "subdir" / "data.csv").write_text("a,b\n1,2")

    files = orchestrator.tool_list_files(res["run_id"], logs_dir=isolated_logs)
    assert "files" in files
    paths = [f["path"] for f in files["files"]]
    assert "results.json" in paths
    assert any("data.csv" in p for p in paths)


def test_list_files_unknown_run(orchestrator, isolated_logs):
    res = orchestrator.tool_list_files("no_such_run", logs_dir=isolated_logs)
    assert "error" in res


def test_read_file_returns_content(orchestrator, isolated_logs):
    res = orchestrator.tool_run_experiment(
        "# read test", max_recursion_depth=1, logs_dir=isolated_logs,
    )
    ckpt = Path(res["checkpoint_dir"])
    (ckpt / "notes.txt").write_text("hello world")

    result = orchestrator.tool_read_file(res["run_id"], "notes.txt", logs_dir=isolated_logs)
    assert result["content"] == "hello world"
    assert result["path"] == "notes.txt"


def test_read_file_blocks_path_traversal(orchestrator, isolated_logs):
    res = orchestrator.tool_run_experiment(
        "# traversal test", max_recursion_depth=1, logs_dir=isolated_logs,
    )
    result = orchestrator.tool_read_file(res["run_id"], "../../etc/passwd", logs_dir=isolated_logs)
    assert "error" in result
    assert "traversal" in result["error"].lower()


def test_read_file_not_found(orchestrator, isolated_logs):
    res = orchestrator.tool_run_experiment(
        "# missing file", max_recursion_depth=1, logs_dir=isolated_logs,
    )
    result = orchestrator.tool_read_file(res["run_id"], "no_such.txt", logs_dir=isolated_logs)
    assert "error" in result


def test_get_ear_no_ear_dir(orchestrator, isolated_logs):
    res = orchestrator.tool_run_experiment(
        "# no ear", max_recursion_depth=1, logs_dir=isolated_logs,
    )
    result = orchestrator.tool_get_ear(res["run_id"], logs_dir=isolated_logs)
    assert "error" in result
    assert "not generated" in result["error"].lower()


def test_get_ear_returns_contents(orchestrator, isolated_logs):
    res = orchestrator.tool_run_experiment(
        "# ear test", max_recursion_depth=1, logs_dir=isolated_logs,
    )
    ckpt = Path(res["checkpoint_dir"])
    ear = ckpt / "ear"
    ear.mkdir()
    (ear / "README.md").write_text("# EAR Report")
    (ear / "results.md").write_text("## Results\nmetric=0.95")

    result = orchestrator.tool_get_ear(res["run_id"], logs_dir=isolated_logs)
    assert "README_md" in result
    assert "EAR Report" in result["README_md"]
    assert "results_md" in result
    assert "files" in result


def test_stop_experiment_no_pid(orchestrator, isolated_logs):
    res = orchestrator.tool_run_experiment(
        "# stop test", max_recursion_depth=1, logs_dir=isolated_logs,
    )
    result = orchestrator.tool_stop_experiment(res["run_id"], logs_dir=isolated_logs)
    assert "error" in result  # dry_run has no PID file


def test_list_skills_returns_skills(orchestrator):
    skills = orchestrator.tool_list_skills()
    assert isinstance(skills, list)
    assert len(skills) > 0
    names = [s["name"] for s in skills]
    assert "ari-skill-orchestrator" in names
    # Each skill should have tools list
    for s in skills:
        assert "tools" in s


def test_get_workflow_returns_pipelines(orchestrator):
    wf = orchestrator.tool_get_workflow()
    if "error" in wf:
        pytest.skip(f"workflow.yaml not found: {wf['error']}")
    assert "bfts_pipeline" in wf
    assert "pipeline" in wf
    assert "skills" in wf
    assert "llm" in wf
    assert "resources" in wf
    assert len(wf["bfts_pipeline"]) > 0
    assert len(wf["pipeline"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Phase 5: recursion chain semantics (max=0 runs, child blocked)
# ─────────────────────────────────────────────────────────────────────────────

def test_recursion_chain_depth_2(orchestrator, isolated_logs):
    """max=2: run OK, child max=1 OK, grandchild max=0 OK, great-grandchild blocked."""
    parent = orchestrator.tool_run_experiment(
        "# depth-2 parent", max_recursion_depth=2, logs_dir=isolated_logs,
    )
    assert parent["status"] == "started"
    assert parent["child_max_recursion_depth"] == 1

    # Simulate child inheriting max=1
    child = orchestrator.tool_run_experiment(
        "# depth-2 child", max_recursion_depth=1, logs_dir=isolated_logs,
    )
    assert child["status"] == "started"
    assert child["child_max_recursion_depth"] == 0

    # Simulate grandchild inheriting max=0 (can run, no further children)
    grandchild = orchestrator.tool_run_experiment(
        "# depth-2 grandchild", max_recursion_depth=0, logs_dir=isolated_logs,
    )
    assert grandchild["status"] == "started"
    assert grandchild["child_max_recursion_depth"] == -1

    # Great-grandchild inherits max=-1 → blocked
    blocked = orchestrator.tool_run_experiment(
        "# blocked", max_recursion_depth=-1, logs_dir=isolated_logs,
    )
    assert blocked["status"] == "blocked"


# ─────────────────────────────────────────────────────────────────────────────
# Phase 6: HTTP transport
# ─────────────────────────────────────────────────────────────────────────────

def test_http_post_run_experiment(orchestrator, http_server, isolated_logs):
    status, payload = _http_post(
        http_server,
        "/mcp/run_experiment",
        {"experiment_md": "# http run\ngoal", "max_recursion_depth": 2},
    )
    assert status == 200
    assert payload["status"] == "started"
    assert payload["max_recursion_depth"] == 2
    assert Path(payload["checkpoint_dir"]).exists()


def test_http_post_run_experiment_blocks_recursion(http_server, isolated_logs):
    status, payload = _http_post(
        http_server,
        "/mcp/run_experiment",
        {"experiment_md": "# blocked", "max_recursion_depth": -1},
    )
    assert status == 200
    assert payload["status"] == "blocked"


def test_http_get_list_runs_and_status(orchestrator, http_server, isolated_logs):
    res = orchestrator.tool_run_experiment(
        "# from python\nx",
        parent_run_id="root",
        max_recursion_depth=3,
        logs_dir=isolated_logs,
    )
    rid = res["run_id"]

    status, runs = _http_get(http_server, "/mcp/list_runs")
    assert status == 200
    assert any(r["run_id"] == rid for r in runs)

    status, st = _http_get(http_server, f"/mcp/get_status?run_id={rid}")
    assert status == 200
    assert st["run_id"] == rid
    assert st["parent_run_id"] == "root"


def test_http_get_list_children(orchestrator, http_server, isolated_logs):
    orchestrator.tool_run_experiment(
        "# child", parent_run_id="root_parent",
        max_recursion_depth=3, logs_dir=isolated_logs,
    )
    status, children = _http_get(
        http_server, "/mcp/list_children?parent_run_id=root_parent"
    )
    assert status == 200
    assert len(children) >= 1
    assert all(c["parent_run_id"] == "root_parent" for c in children)


def test_http_sse_logs_endpoint(orchestrator, http_server, isolated_logs, monkeypatch):
    monkeypatch.setenv("ARI_ORCHESTRATOR_SSE_ONESHOT", "1")
    monkeypatch.setenv("ARI_ORCHESTRATOR_SSE_TIMEOUT", "2")
    res = orchestrator.tool_run_experiment(
        "# sse test", logs_dir=isolated_logs, max_recursion_depth=3,
    )
    rid = res["run_id"]
    (Path(res["checkpoint_dir"]) / "orchestrator.log").write_text(
        "first line\nsecond line\n"
    )
    with urllib.request.urlopen(
        f"http://127.0.0.1:{http_server}/mcp/logs/{rid}", timeout=5
    ) as r:
        body = r.read().decode()
    assert "first line" in body
    assert "second line" in body
    assert "[end of log]" in body


def test_http_get_list_files(orchestrator, http_server, isolated_logs):
    res = orchestrator.tool_run_experiment(
        "# http files", max_recursion_depth=1, logs_dir=isolated_logs,
    )
    ckpt = Path(res["checkpoint_dir"])
    (ckpt / "data.json").write_text("{}")
    status, payload = _http_get(http_server, f"/mcp/list_files?run_id={res['run_id']}")
    assert status == 200
    assert "files" in payload


def test_http_get_read_file(orchestrator, http_server, isolated_logs):
    res = orchestrator.tool_run_experiment(
        "# http read", max_recursion_depth=1, logs_dir=isolated_logs,
    )
    ckpt = Path(res["checkpoint_dir"])
    (ckpt / "test.txt").write_text("http content")
    status, payload = _http_get(
        http_server, f"/mcp/read_file?run_id={res['run_id']}&filename=test.txt"
    )
    assert status == 200
    assert payload["content"] == "http content"


def test_http_get_list_skills(http_server):
    status, payload = _http_get(http_server, "/mcp/list_skills")
    assert status == 200
    assert isinstance(payload, list)
    assert len(payload) > 0


def test_http_get_workflow(http_server):
    status, payload = _http_get(http_server, "/mcp/get_workflow")
    assert status == 200
    if "error" not in payload:
        assert "bfts_pipeline" in payload


def test_http_unknown_route_returns_404(http_server):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{http_server}/no-such", timeout=5)
        assert False, "expected 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Phase 7: GUI api_orchestrator endpoints
# ─────────────────────────────────────────────────────────────────────────────

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
    body = json.dumps({
        "experiment_md": "# gui test\ngoal text",
        "max_recursion_depth": 2,
        "parent_run_id": None,
        "dry_run": True,
    }).encode()
    res = _api_launch_sub_experiment(body)
    assert res["ok"] is True
    ck = Path(res["checkpoint_dir"])
    assert (ck / "meta.json").exists()
    meta = json.loads((ck / "meta.json").read_text())
    assert meta["max_recursion_depth"] == 2
    assert meta["recursion_depth"] == 0


def test_gui_launch_sub_experiment_blocks_at_limit(gui_logs):
    from ari.viz.api_orchestrator import _api_launch_sub_experiment
    body = json.dumps({
        "experiment_md": "# blocked",
        "recursion_depth": 3,
        "max_recursion_depth": 3,
        "dry_run": True,
    }).encode()
    res = _api_launch_sub_experiment(body)
    assert res["ok"] is False
    assert "Recursion limit" in res["error"]


def test_gui_list_sub_experiments_returns_disk_records(gui_logs):
    from ari.viz.api_orchestrator import (
        _api_launch_sub_experiment,
        _api_list_sub_experiments,
    )
    for i in range(2):
        time.sleep(0.01)
        _api_launch_sub_experiment(
            json.dumps({
                "experiment_md": f"# r{i}",
                "max_recursion_depth": 3,
                "dry_run": True,
            }).encode()
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
        _api_launch_sub_experiment,
        _api_get_sub_experiment,
    )
    res = _api_launch_sub_experiment(
        json.dumps({
            "experiment_md": "# single",
            "max_recursion_depth": 3,
            "parent_run_id": "p1",
            "dry_run": True,
        }).encode()
    )
    rid = res["run_id"]
    fetched = _api_get_sub_experiment(rid)
    assert fetched["run_id"] == rid
    assert fetched["parent_run_id"] == "p1"


def test_gui_get_sub_experiment_unknown(gui_logs):
    from ari.viz.api_orchestrator import _api_get_sub_experiment
    res = _api_get_sub_experiment("not_a_real_id")
    assert "error" in res


def test_gui_list_sub_experiments_prunes_deleted(gui_logs):
    """Deleted checkpoint dirs must disappear from sub-experiment listing."""
    import shutil
    from ari.viz.api_orchestrator import (
        _api_launch_sub_experiment,
        _api_list_sub_experiments,
    )
    # Launch two sub-experiments
    res_a = _api_launch_sub_experiment(json.dumps({
        "experiment_md": "# keep", "max_recursion_depth": 3, "dry_run": True,
    }).encode())
    time.sleep(0.01)
    res_b = _api_launch_sub_experiment(json.dumps({
        "experiment_md": "# delete me", "max_recursion_depth": 3, "dry_run": True,
    }).encode())
    assert len(_api_list_sub_experiments()["sub_experiments"]) == 2

    # Delete one from disk (simulating rm -rf or GUI delete)
    shutil.rmtree(res_b["checkpoint_dir"])

    listed = _api_list_sub_experiments()
    ids = [s["run_id"] for s in listed["sub_experiments"]]
    assert res_a["run_id"] in ids
    assert res_b["run_id"] not in ids, "Deleted sub-experiment must not appear"


def test_gui_state_helpers_roundtrip():
    from ari.viz import state as _st
    _st._sub_experiments.clear()
    _st.set_sub_experiment("rid_1", {"run_id": "rid_1", "recursion_depth": 0})
    snap = _st.get_sub_experiments()
    assert "rid_1" in snap
    snap.pop("rid_1")
    assert "rid_1" in _st.get_sub_experiments()
    _st._sub_experiments.clear()
