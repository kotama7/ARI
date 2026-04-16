"""Tests for cross-experiment global memory tools."""
from __future__ import annotations

import json
from unittest.mock import patch


def test_add_global_memory_appends(tmp_path):
    import src.server as srv
    gpath = tmp_path / "global_memory.jsonl"
    with patch.object(srv, "GLOBAL_PATH", gpath):
        assert srv.add_global_memory("pytorch flash-attn wheel broken on sm_86", tags=["pytorch"])["ok"] is True
        assert srv.add_global_memory("SLURM default QOS = normal", tags=["slurm", "hpc"])["ok"] is True

        lines = gpath.read_text().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert "flash-attn" in first["text"]
        assert first["tags"] == ["pytorch"]
        assert first["ts"] > 0


def test_search_global_memory_tag_filter(tmp_path):
    import src.server as srv
    gpath = tmp_path / "global_memory.jsonl"
    gpath.write_text(
        json.dumps({"text": "pytorch flash-attn broken", "tags": ["pytorch"], "metadata": {}, "ts": 1}) + "\n"
        + json.dumps({"text": "slurm partition GPU dev", "tags": ["slurm"], "metadata": {}, "ts": 2}) + "\n"
        + json.dumps({"text": "flash-attn patch available", "tags": ["pytorch", "workaround"], "metadata": {}, "ts": 3}) + "\n"
    )
    with patch.object(srv, "GLOBAL_PATH", gpath):
        r = srv.search_global_memory("flash-attn", tags=["pytorch"], limit=10)
        texts = [e["text"] for e in r["results"]]
        assert any("flash-attn broken" in t for t in texts)
        assert any("patch available" in t for t in texts)
        assert not any("slurm" in t for t in texts)


def test_search_global_memory_keyword_only(tmp_path):
    import src.server as srv
    gpath = tmp_path / "global_memory.jsonl"
    gpath.write_text(
        json.dumps({"text": "flash-attn hits sm_86", "tags": [], "metadata": {}, "ts": 1}) + "\n"
        + json.dumps({"text": "unrelated note", "tags": [], "metadata": {}, "ts": 2}) + "\n"
    )
    with patch.object(srv, "GLOBAL_PATH", gpath):
        r = srv.search_global_memory("flash-attn", tags=None, limit=10)
        assert len(r["results"]) == 1
        assert "flash-attn" in r["results"][0]["text"]


def test_list_global_memory_sorted_desc(tmp_path):
    import src.server as srv
    gpath = tmp_path / "global_memory.jsonl"
    gpath.write_text(
        json.dumps({"text": "old", "tags": [], "metadata": {}, "ts": 1}) + "\n"
        + json.dumps({"text": "new", "tags": [], "metadata": {}, "ts": 100}) + "\n"
        + json.dumps({"text": "mid", "tags": [], "metadata": {}, "ts": 50}) + "\n"
    )
    with patch.object(srv, "GLOBAL_PATH", gpath):
        r = srv.list_global_memory(limit=10)
        assert r["total"] == 3
        assert [e["text"] for e in r["entries"]] == ["new", "mid", "old"]


def test_global_memory_isolated_from_per_node_store(tmp_path):
    """Global memory must not leak into per-node STORE_PATH and vice versa."""
    import src.server as srv
    store = tmp_path / "node_memory.jsonl"
    gpath = tmp_path / "global_memory.jsonl"
    with patch.object(srv, "STORE_PATH", store), patch.object(srv, "GLOBAL_PATH", gpath):
        srv.add_memory("node_A", "per-node fact", {})
        srv.add_global_memory("cross-experiment fact", tags=["x"])

        assert json.loads(store.read_text().splitlines()[0])["text"] == "per-node fact"
        assert json.loads(gpath.read_text().splitlines()[0])["text"] == "cross-experiment fact"

        r = srv.search_memory("fact", ancestor_ids=["node_A"], limit=5)
        assert len(r["results"]) == 1
        assert "per-node" in r["results"][0]["text"]

        g = srv.search_global_memory("fact", limit=5)
        assert len(g["results"]) == 1
        assert "cross-experiment" in g["results"][0]["text"]
