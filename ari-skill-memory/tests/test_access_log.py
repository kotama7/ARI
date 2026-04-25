"""Access log tests — writer hooks, rotation, off switch."""
from __future__ import annotations

import json
import os
import time


def _drain(backend):
    # Flush the background queue synchronously.
    backend._access.flush_and_close()


def test_write_event_shape(backend, ckpt_env, monkeypatch):
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "n1")
    r = backend.add_memory("n1", "hello-world", {"k": "v"})
    _drain(backend)
    log_path = ckpt_env / "memory_access.jsonl"
    assert log_path.exists()
    lines = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    writes = [e for e in lines if e["op"] == "write"]
    assert any(e["entry_id"] == r["id"] and e["node_id"] == "n1" for e in writes)


def test_read_event_shape(backend, ckpt_env, monkeypatch):
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "n1")
    r = backend.add_memory("n1", "alpha beta", {})
    backend.search_memory("alpha", ancestor_ids=["n1"], limit=3)
    _drain(backend)
    log_path = ckpt_env / "memory_access.jsonl"
    events = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    reads = [e for e in events if e["op"] == "read"]
    assert reads, "read event missing"
    ev = reads[-1]
    assert ev["query"] == "alpha"
    assert ev["ancestor_ids"] == ["n1"]
    # Results must carry src_node_id (so the Tree dashboard can trace origin)
    assert all("src_node_id" in x for x in ev["results"])


def test_access_log_off(tmp_path, monkeypatch):
    from ari_skill_memory.backends import get_backend, clear_backend_cache
    clear_backend_cache()
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("ARI_MEMORY_BACKEND", "in_memory")
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "n1")
    monkeypatch.setenv("ARI_MEMORY_ACCESS_LOG", "off")
    b = get_backend(checkpoint_dir=tmp_path)
    b.add_memory("n1", "x", {})
    # No file should be created.
    assert not (tmp_path / "memory_access.jsonl").exists()
