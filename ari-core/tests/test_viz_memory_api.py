"""Tests for the viz memory API endpoint (_api_checkpoint_memory)."""
from __future__ import annotations

import json
from unittest.mock import patch


def test_memory_api_reads_mcp_store(tmp_path, monkeypatch):
    from ari.viz import api_state

    monkeypatch.setenv("ARI_GLOBAL_MEMORY_PATH", str(tmp_path / "no_global.jsonl"))
    ckpt = tmp_path / "ckpt_X"
    ckpt.mkdir()
    (ckpt / "memory_store.jsonl").write_text(
        json.dumps({"node_id": "root", "text": "baseline 12000", "metadata": {"step": 1}, "ts": 1}) + "\n"
        + json.dumps({"node_id": "child_1", "text": "improved 280000", "metadata": {"step": 2}, "ts": 2}) + "\n",
        encoding="utf-8",
    )

    with patch.object(api_state, "_resolve_checkpoint_dir", return_value=ckpt):
        r = api_state._api_checkpoint_memory("ckpt_X")

    assert r["count"] == 2
    assert r["entries"][0]["source"] == "mcp"
    assert set(r["by_node"].keys()) == {"root", "child_1"}
    assert r["global"] == []


def test_memory_api_merges_file_client_store(tmp_path, monkeypatch):
    from ari.viz import api_state

    monkeypatch.setenv("ARI_GLOBAL_MEMORY_PATH", str(tmp_path / "no_global.jsonl"))
    ckpt = tmp_path / "ckpt_Y"
    ckpt.mkdir()
    (ckpt / "memory_store.jsonl").write_text(
        json.dumps({"node_id": "root", "text": "mcp entry", "metadata": {}, "ts": 1}) + "\n",
        encoding="utf-8",
    )
    (ckpt / "memory.json").write_text(
        json.dumps([
            {"content": "file-client entry", "metadata": {"node_id": "root"}, "ts": "2025-01-01T00:00:00Z"},
            {"content": "unscoped entry", "metadata": {}, "ts": "2025-01-02T00:00:00Z"},
        ]),
        encoding="utf-8",
    )

    with patch.object(api_state, "_resolve_checkpoint_dir", return_value=ckpt):
        r = api_state._api_checkpoint_memory("ckpt_Y")

    sources = {e["source"] for e in r["entries"]}
    assert sources == {"mcp", "file_client"}
    assert r["count"] == 3
    assert "_unscoped" in r["by_node"]


def test_memory_api_returns_global_entries(tmp_path, monkeypatch):
    from ari.viz import api_state

    gpath = tmp_path / "global_memory.jsonl"
    gpath.write_text(
        json.dumps({"text": "pytorch wheel broken on sm_86", "tags": ["pytorch"], "metadata": {}, "ts": 100}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARI_GLOBAL_MEMORY_PATH", str(gpath))

    ckpt = tmp_path / "ckpt_Z"
    ckpt.mkdir()

    with patch.object(api_state, "_resolve_checkpoint_dir", return_value=ckpt):
        r = api_state._api_checkpoint_memory("ckpt_Z")

    assert len(r["global"]) == 1
    assert r["global"][0]["source"] == "global"
    assert r["global"][0]["tags"] == ["pytorch"]
    assert r["count"] == 1


def test_memory_api_missing_checkpoint(tmp_path):
    from ari.viz import api_state

    with patch.object(api_state, "_resolve_checkpoint_dir", return_value=None):
        r = api_state._api_checkpoint_memory("nope")

    assert r == {"error": "checkpoint not found"}
