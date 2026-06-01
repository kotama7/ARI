"""Guard: list/summary cards resolve the legacy node_*/tree.json layout (req 07).

Divergence #1 fixed in req 07: `_api_checkpoints` and `_api_checkpoint_summary`
used inline tree.json/nodes_tree.json probes that omitted the legacy
`node_*/tree.json` fallback honored by the canonical
`ari.checkpoint.load_nodes_tree` (and the live WebSocket path). A legacy
checkpoint therefore showed node_count=0 in the list/summary even though the
live tree rendered it. These pin the corrected behavior while confirming the
common (flat tree.json) case is unchanged.
"""
from __future__ import annotations

import json

import pytest

from ari.viz import state as _st
from ari.viz import checkpoint_api


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setattr(_st, "_checkpoint_dir", None, raising=False)
    monkeypatch.setattr(_st, "_last_proc", None, raising=False)
    monkeypatch.setattr(_st, "_running_procs", {}, raising=False)
    yield


def _legacy_checkpoint(root, name="20260101_legacy"):
    """A checkpoint with NO flat tree.json — only node_*/tree.json (legacy)."""
    d = root / name
    (d / "node_abc123").mkdir(parents=True)
    (d / "node_abc123" / "tree.json").write_text(json.dumps({
        "nodes": [
            {"id": "n0", "status": "success", "metrics": {"_scientific_score": 0.8}},
            {"id": "n1", "status": "success", "metrics": {}},
        ]
    }))
    return d


def test_checkpoints_list_counts_legacy_node_tree(isolated, monkeypatch):
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    base = tmp / "checkpoints"
    d = _legacy_checkpoint(base)
    monkeypatch.setattr(checkpoint_api, "_checkpoint_search_bases", lambda: [base])
    items = checkpoint_api._api_checkpoints()
    item = next(i for i in items if i["id"] == d.name)
    # Before the fix this was 0 (legacy node_*/tree.json was ignored here).
    assert item["node_count"] == 2
    assert item["status"] == "completed"
    assert item["best_scientific_score"] == 0.8


def test_summary_loads_legacy_node_tree(isolated, monkeypatch):
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    base = tmp / "checkpoints"
    d = _legacy_checkpoint(base, name="20260101_legacy2")
    monkeypatch.setattr(checkpoint_api, "_resolve_checkpoint_dir", lambda cid: d)
    summary = checkpoint_api._api_checkpoint_summary("20260101_legacy2")
    assert "nodes_tree" in summary, "legacy node_*/tree.json should populate nodes_tree"
    assert len(summary["nodes_tree"]["nodes"]) == 2


def test_summary_prefers_flat_tree_json(isolated, monkeypatch):
    """Common case unchanged: a flat tree.json is read directly."""
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    d = tmp / "checkpoints" / "20260101_flat"
    d.mkdir(parents=True)
    (d / "tree.json").write_text(json.dumps({"nodes": [{"id": "n0", "status": "success"}]}))
    monkeypatch.setattr(checkpoint_api, "_resolve_checkpoint_dir", lambda cid: d)
    summary = checkpoint_api._api_checkpoint_summary("20260101_flat")
    assert summary["nodes_tree"]["nodes"][0]["id"] == "n0"
