"""ReAct-trace backend tests (react_add / react_search / react_get_all)."""
from __future__ import annotations


def test_react_add_search_get_all(backend):
    backend.react_add("kernel A ran", {"node_id": "n1", "step": 1})
    backend.react_add("kernel B failed", {"node_id": "n2", "step": 2})
    backend.react_add("kernel A optimized", {"node_id": "n1", "step": 3})

    out = backend.react_search("kernel A", limit=5)
    assert any("kernel A ran" in e["content"] for e in out)
    assert any("kernel A optimized" in e["content"] for e in out)

    all_ = backend.react_get_all()
    assert len(all_) == 3


def test_react_no_ancestor_filtering(backend):
    """ReAct client returns entries across the whole checkpoint (flat, not ancestor-scoped)."""
    backend.react_add("from n1", {"node_id": "n1"})
    backend.react_add("from sibling n2", {"node_id": "n2"})
    out = backend.react_search("from", limit=10)
    # Both branches visible.
    nids = {e["metadata"].get("node_id") for e in out}
    assert nids == {"n1", "n2"}


def test_react_truncate(tmp_path, monkeypatch):
    from ari_skill_memory.backends import get_backend, clear_backend_cache
    clear_backend_cache()
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("ARI_MEMORY_BACKEND", "in_memory")
    monkeypatch.setenv("ARI_REACT_MEMORY_MAX_ENTRY_CHARS", "10")
    b = get_backend(checkpoint_dir=tmp_path)
    b.react_add("a" * 100)
    out = b.react_get_all()
    assert out[-1]["content"].endswith("…[truncated]")
    assert len(out[-1]["content"]) <= len("a" * 10) + len("…[truncated]")
