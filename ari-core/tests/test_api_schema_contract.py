"""Schema-contract guards for stable viz REST endpoints (req 06).

These pin the ALWAYS-present keys of the highest-traffic endpoints so backend
response shapes can't silently drift away from the frontend TypeScript types
(types/index.ts: AppState, Settings, Checkpoint, CheckpointSummary). They assert
a *subset* (additive contract) — extra keys are allowed, matching the wire
policy ({**defaults, **saved} merges, conditional fields) — so they don't
falsely fail when new optional fields are added. (Exception: the
checkpoint-summary not-found path is asserted by exact equality, since
``{"error": "not found"}`` is a fixed error sentinel, not an additive payload.)

Verified against the implementation on 2026-05-30.
"""
from __future__ import annotations

import json

import pytest

from ari.viz import state as _st
from ari.viz import checkpoint_api
from ari.viz import api_settings
from ari.viz import ear
from ari.viz import ui_helpers


@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    monkeypatch.setattr(_st, "_checkpoint_dir", None, raising=False)
    monkeypatch.setattr(_st, "_last_proc", None, raising=False)
    monkeypatch.setattr(_st, "_running_procs", {}, raising=False)
    monkeypatch.setattr(_st, "_settings_path", None, raising=False)
    yield tmp_path


def _make_checkpoint(root, name="20260101_contract"):
    d = root / name
    d.mkdir(parents=True)
    (d / "tree.json").write_text(json.dumps({"nodes": [
        {"id": "n0", "status": "completed", "metrics": {"_scientific_score": 0.5}},
    ]}))
    return d


# ── /api/checkpoints ──────────────────────────────────────────────────────

def test_checkpoints_item_contract(isolated_state, monkeypatch):
    root = isolated_state / "checkpoints"
    _make_checkpoint(root)
    monkeypatch.setattr(checkpoint_api, "_checkpoint_search_bases", lambda: [root])
    items = checkpoint_api._api_checkpoints()
    assert isinstance(items, list) and items, "expected at least one checkpoint"
    item = items[0]
    # Keys the frontend Checkpoint type relies on (always present).
    for key in ("id", "path", "status", "node_count", "review_score", "best_metric", "mtime"):
        assert key in item, f"/api/checkpoints item missing contract key: {key}"
    assert isinstance(item["id"], str)
    assert isinstance(item["node_count"], int)
    assert item["best_metric"] is None  # documented: always-null init


# ── /api/checkpoint/<id>/summary ──────────────────────────────────────────

def test_checkpoint_summary_found_contract(isolated_state, monkeypatch):
    root = isolated_state / "checkpoints"
    d = _make_checkpoint(root, name="20260101_summary")
    monkeypatch.setattr(checkpoint_api, "_resolve_checkpoint_dir", lambda cid: d)
    summary = checkpoint_api._api_checkpoint_summary("20260101_summary")
    assert isinstance(summary, dict)
    # Base keys echoed back for every resolved checkpoint.
    assert summary.get("id") == "20260101_summary"
    assert "path" in summary
    # nodes_tree is loaded from tree.json.
    assert "nodes_tree" in summary and "nodes" in summary["nodes_tree"]


def test_checkpoint_summary_not_found_contract(isolated_state, monkeypatch):
    monkeypatch.setattr(checkpoint_api, "_resolve_checkpoint_dir", lambda cid: None)
    summary = checkpoint_api._api_checkpoint_summary("nope")
    assert summary == {"error": "not found"}


# ── /api/settings ─────────────────────────────────────────────────────────

def test_settings_defaults_contract(isolated_state, monkeypatch):
    # No active settings file -> returns the defaults dict.
    monkeypatch.setattr(_st, "_settings_path", None, raising=False)
    s = api_settings._api_get_settings()
    assert isinstance(s, dict)
    # Keys the frontend Settings type / wizard rely on (always present).
    for key in (
        "llm_model", "llm_provider", "ollama_host", "temperature",
        "retrieval_backend", "slurm_partition", "slurm_walltime",
        "container_mode", "container_pull",
        "vlm_review_enabled", "vlm_review_model",
        "letta_base_url", "letta_embedding_config", "ors",
    ):
        assert key in s, f"/api/settings missing contract key: {key}"
    assert isinstance(s["ors"], dict)
    assert "judge_model" in s["ors"]


def test_settings_merges_saved_over_defaults(isolated_state, monkeypatch):
    sp = isolated_state / "settings.json"
    sp.write_text(json.dumps({"llm_model": "custom/model", "extra_saved": 7}))
    monkeypatch.setattr(_st, "_settings_path", sp, raising=False)
    s = api_settings._api_get_settings()
    assert s["llm_model"] == "custom/model"  # saved overrides default
    assert s["extra_saved"] == 7             # arbitrary saved keys pass through
    assert "ollama_host" in s                # defaults still present


# ── /api/checkpoint/<id>/summary (full body) ──────────────────────────────
# Subtask 065 extension. Counterpart FE type: CheckpointSummary (types/index.ts:237).

def _make_full_checkpoint(root, name="20260101_full"):
    """A checkpoint with the files that make the summary emit its rich keys.

    ``paper_tex`` / ``has_pdf`` / ``review_report`` are emitted by
    ``_api_checkpoint_summary`` only when the matching files exist, so the
    fixture supplies them; that is the current wire behavior being pinned.
    """
    d = root / name
    d.mkdir(parents=True)
    (d / "tree.json").write_text(json.dumps({"nodes": [
        {"id": "n0", "status": "completed", "metrics": {"_scientific_score": 0.5}},
    ]}))
    (d / "review_report.json").write_text(json.dumps({"overall_score": 7.5, "scores": {}}))
    (d / "full_paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}")
    (d / "full_paper.pdf").write_bytes(b"%PDF-1.5\n%%EOF\n")
    return d


def test_checkpoint_summary_full_body_contract(isolated_state, monkeypatch):
    # Counterpart FE type: CheckpointSummary (types/index.ts:237).
    root = isolated_state / "checkpoints"
    d = _make_full_checkpoint(root)
    monkeypatch.setattr(checkpoint_api, "_resolve_checkpoint_dir", lambda cid: d)
    summary = checkpoint_api._api_checkpoint_summary("20260101_full")
    assert isinstance(summary, dict)
    # Keys the frontend CheckpointSummary type reads for a fully-populated run.
    for key in ("id", "path", "nodes_tree", "paper_tex", "has_pdf", "review_report"):
        assert key in summary, f"/api/checkpoint/<id>/summary missing contract key: {key}"
    assert isinstance(summary["nodes_tree"], dict)
    assert isinstance(summary["nodes_tree"].get("nodes"), list)
    assert isinstance(summary["paper_tex"], str)
    assert isinstance(summary["has_pdf"], bool)
    assert isinstance(summary["review_report"], dict)
    # ``error`` is the not-found sentinel only; it must not appear on success.
    assert "error" not in summary


# ── /api/workflow ─────────────────────────────────────────────────────────
# Subtask 065 extension. Counterpart FE type: WorkflowData (types/index.ts:159).

def test_workflow_schema_contract(isolated_state, monkeypatch):
    # Counterpart FE type: WorkflowData (types/index.ts:159).
    ckpt = isolated_state / "wf_ckpt"
    ckpt.mkdir()
    (ckpt / "workflow.yaml").write_text(
        "llm:\n  backend: openai\n  model: gpt-4o\n"
        "pipeline: []\nbfts_pipeline: []\nskills: []\ndisabled_tools: []\n"
    )
    # Route _api_get_workflow at the temp checkpoint's workflow.yaml.
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt, raising=False)
    result = api_settings._api_get_workflow()
    assert isinstance(result, dict)
    assert result.get("ok") is True
    for key in ("ok", "workflow", "path", "skill_mcp", "disabled_tools",
                "bfts_pipeline", "paper_pipeline", "full_pipeline"):
        assert key in result, f"/api/workflow missing contract key: {key}"
    assert isinstance(result["workflow"], dict)
    # WorkflowData.workflow declares pipeline + skills sub-keys.
    assert "pipeline" in result["workflow"]
    assert "skills" in result["workflow"]
    assert result["path"] == str(ckpt / "workflow.yaml")
    # ``error`` is emitted only on the failure path; absent on success.
    assert "error" not in result


# ── /api/resource-metrics ─────────────────────────────────────────────────
# Subtask 065 extension. Counterpart FE type: ResourceMetrics (types/index.ts:174).

def test_resource_metrics_contract(isolated_state):
    # Counterpart FE type: ResourceMetrics (types/index.ts:174).
    m = ui_helpers._collect_resource_metrics()
    assert isinstance(m, dict)
    for key in ("process_count", "memory_rss_mb", "cpu_load_1m", "cpu_load_5m",
                "cpu_load_15m", "cpu_count", "experiment_pid", "timestamp"):
        assert key in m, f"/api/resource-metrics missing contract key: {key}"
    assert isinstance(m["process_count"], int)
    assert isinstance(m["cpu_count"], int)
    assert isinstance(m["timestamp"], str)
    # No experiment process is tracked in the isolated state.
    assert m["experiment_pid"] is None


# ── /api/nodes/<run_id>/<node_id>/report ──────────────────────────────────
# Subtask 065 extension. Counterpart FE type: NodeReportResponse (api.ts:155-160).

def test_node_report_found_contract(isolated_state, monkeypatch):
    # Counterpart FE type: NodeReportResponse (api.ts:155) wrapping NodeReport (api.ts:124).
    run_id, node_id = "20260101_report", "n0"
    d = isolated_state / "checkpoints" / run_id
    d.mkdir(parents=True)
    # Layout _api_node_report probes: {workspace}/experiments/{run_id}/{node_id}/.
    rp = isolated_state / "experiments" / run_id / node_id / "node_report.json"
    rp.parent.mkdir(parents=True)
    rp.write_text(json.dumps({
        "schema_version": 1,
        "node_id": node_id,
        "files_changed": {"added": [], "modified": [], "deleted": [],
                          "inherited_unchanged": []},
    }))
    monkeypatch.setattr(ear, "_resolve_checkpoint_dir", lambda rid: d)
    resp = ear._api_node_report(run_id, node_id)
    assert isinstance(resp, dict)
    for key in ("run_id", "node_id", "report"):
        assert key in resp, f"node report missing contract key: {key}"
    assert resp["run_id"] == run_id
    assert resp["node_id"] == node_id
    assert isinstance(resp["report"], dict)
    assert "files_changed" in resp["report"]


def test_node_report_not_found_contract(isolated_state, monkeypatch):
    monkeypatch.setattr(ear, "_resolve_checkpoint_dir", lambda rid: None)
    resp = ear._api_node_report("nope", "n0")
    assert resp == {"error": "checkpoint not found"}
