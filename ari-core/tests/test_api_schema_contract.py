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
