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


def test_inheritance_reads_are_logged(backend, ckpt_env, monkeypatch):
    # The deterministic ancestor-inheritance reads (get_node_memory /
    # bulk_get_node_memory, used by build_working_context_messages) must be
    # logged like search_memory — previously they were UNLOGGED, so the
    # memory_access ledger showed ~0 reads even though descendants do inherit.
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "root")
    backend.add_memory("root", "RESULT SUMMARY root", {"type": "result_summary"})
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "child")  # descendant inherits
    backend.get_node_memory("root")
    backend.bulk_get_node_memory(["root"])
    _drain(backend)
    events = [json.loads(l) for l in (ckpt_env / "memory_access.jsonl").read_text().splitlines() if l.strip()]
    reads = [e for e in events if e["op"] == "read"]
    queries = {e.get("query") for e in reads}
    assert "inherit:get_node_memory" in queries
    assert "inherit:bulk_get_node_memory" in queries
    gnm = next(e for e in reads if e["query"] == "inherit:get_node_memory")
    # reader = descendant, source = the ancestor whose conclusions are inherited
    assert gnm["node_id"] == "child" and gnm["ancestor_ids"] == ["root"]
    assert all("src_node_id" in x for x in gnm["results"])
    assert any(x.get("type") == "result_summary" for x in gnm["results"])


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
