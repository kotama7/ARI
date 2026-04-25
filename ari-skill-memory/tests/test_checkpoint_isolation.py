"""Per-checkpoint isolation — two checkpoints must not see each other."""
from __future__ import annotations

import os

import pytest


def test_two_checkpoints_do_not_leak(tmp_path, monkeypatch):
    from ari_skill_memory.backends import get_backend, clear_backend_cache

    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; b.mkdir()

    clear_backend_cache()
    monkeypatch.setenv("ARI_MEMORY_BACKEND", "in_memory")

    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "root")
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(a))
    ba = get_backend(checkpoint_dir=a)
    ba.add_memory("root", "A-only", {})

    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(b))
    bb = get_backend(checkpoint_dir=b)
    bb.add_memory("root", "B-only", {})

    # search from A should only see A's entry
    ra = ba.search_memory("A-only", ancestor_ids=["root"], limit=5)
    assert any("A-only" in e["text"] for e in ra["results"])
    assert not any("B-only" in e["text"] for e in ra["results"])

    rb = bb.search_memory("B-only", ancestor_ids=["root"], limit=5)
    assert any("B-only" in e["text"] for e in rb["results"])
    assert not any("A-only" in e["text"] for e in rb["results"])


def test_checkpoint_dir_required(monkeypatch):
    from ari_skill_memory.config import load_config
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    with pytest.raises(RuntimeError):
        load_config()
