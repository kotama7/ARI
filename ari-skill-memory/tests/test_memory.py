"""Tests for ari-skill-memory server."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest


def _make_store(entries: list[dict]) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for e in entries:
        f.write(json.dumps(e) + "\n")
    f.close()
    return f.name


@patch("src.server.STORE_PATH")
def test_add_memory(mock_path, tmp_path):
    mock_path.__str__ = lambda s: str(tmp_path / "mem.jsonl")
    import src.server as srv
    with patch.object(srv, "STORE_PATH", tmp_path / "mem.jsonl"):
        result = srv.add_memory("node_abc", "tool slurm_submit result=ok", {})
        assert result["ok"] is True
        data = json.loads((tmp_path / "mem.jsonl").read_text().strip())
        assert data["node_id"] == "node_abc"
        assert "slurm_submit" in data["text"]


@patch("src.server.STORE_PATH")
def test_search_memory_ancestor_only(mock_path, tmp_path):
    import src.server as srv
    store = tmp_path / "mem.jsonl"
    store.write_text(
        json.dumps({"node_id": "root", "text": "MFLOPS baseline 12000", "metadata": {}, "ts": 1}) + "\n"
        + json.dumps({"node_id": "node_child1", "text": "MFLOPS improved 280000", "metadata": {}, "ts": 2}) + "\n"
        + json.dumps({"node_id": "node_sibling", "text": "MFLOPS sibling 100", "metadata": {}, "ts": 3}) + "\n"
    )
    with patch.object(srv, "STORE_PATH", store):
        # ancestor_ids contains only "root" and "node_child1" → sibling is not visible
        result = srv.search_memory("MFLOPS", ancestor_ids=["root", "node_child1"], limit=10)
        texts = [r["text"] for r in result["results"]]
        assert any("baseline" in t for t in texts)
        assert any("improved" in t for t in texts)
        assert not any("sibling" in t for t in texts)


@patch("src.server.STORE_PATH")
def test_search_memory_empty_ancestors(mock_path, tmp_path):
    import src.server as srv
    store = tmp_path / "mem.jsonl"
    store.write_text(json.dumps({"node_id": "root", "text": "something", "metadata": {}, "ts": 1}) + "\n")
    with patch.object(srv, "STORE_PATH", store):
        result = srv.search_memory("something", ancestor_ids=[], limit=5)
        assert result["results"] == []


@patch("src.server.STORE_PATH")
def test_get_node_memory(mock_path, tmp_path):
    import src.server as srv
    store = tmp_path / "mem.jsonl"
    store.write_text(
        json.dumps({"node_id": "n1", "text": "entry A", "metadata": {}, "ts": 1}) + "\n"
        + json.dumps({"node_id": "n2", "text": "entry B", "metadata": {}, "ts": 2}) + "\n"
    )
    with patch.object(srv, "STORE_PATH", store):
        result = srv.get_node_memory("n1")
        assert len(result["entries"]) == 1
        assert result["entries"][0]["text"] == "entry A"


@patch("src.server.STORE_PATH")
def test_clear_node_memory(mock_path, tmp_path):
    import src.server as srv
    store = tmp_path / "mem.jsonl"
    store.write_text(
        json.dumps({"node_id": "n1", "text": "to delete", "metadata": {}, "ts": 1}) + "\n"
        + json.dumps({"node_id": "n2", "text": "to keep", "metadata": {}, "ts": 2}) + "\n"
    )
    with patch.object(srv, "STORE_PATH", store):
        result = srv.clear_node_memory("n1")
        assert result["removed"] == 1
        remaining = srv._load_all()
        assert all(e["node_id"] != "n1" for e in remaining)


@patch("src.server.STORE_PATH")
def test_search_score_ordering(mock_path, tmp_path):
    import src.server as srv
    store = tmp_path / "mem.jsonl"
    store.write_text(
        json.dumps({"node_id": "root", "text": "MFLOPS", "metadata": {}, "ts": 1}) + "\n"
        + json.dumps({"node_id": "root", "text": "MFLOPS MFLOPS high result", "metadata": {}, "ts": 2}) + "\n"
    )
    with patch.object(srv, "STORE_PATH", store):
        result = srv.search_memory("MFLOPS", ancestor_ids=["root"], limit=5)
        assert result["results"][0]["score"] >= result["results"][-1]["score"]
