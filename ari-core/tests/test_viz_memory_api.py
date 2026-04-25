"""Viz memory API tests —-migration _api_checkpoint_memory uses the backend library, not
direct JSONL reads. Tests wire the in-memory backend and assert the
new response schema (entries[], global==[], error field).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch


def _add_library_path():
    mem_src = Path(__file__).resolve().parents[2] / "ari-skill-memory" / "src"
    if str(mem_src) not in sys.path:
        sys.path.insert(0, str(mem_src))


def test_memory_api_reads_backend(tmp_path, monkeypatch):
    _add_library_path()
    from ari.viz import api_state
    from ari_skill_memory.backends import get_backend, clear_backend_cache

    monkeypatch.setenv("ARI_MEMORY_BACKEND", "in_memory")
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "root")
    ckpt = tmp_path / "ckpt_X"
    ckpt.mkdir()
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ckpt))

    clear_backend_cache()
    b = get_backend(checkpoint_dir=ckpt)
    b.add_memory("root", "baseline 12000", {"step": 1})
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "child_1")
    b.add_memory("child_1", "improved 280000", {"step": 2})
    b.react_add("ran kernel", {"node_id": "root"})

    with patch.object(api_state, "_resolve_checkpoint_dir", return_value=ckpt):
        r = api_state._api_checkpoint_memory("ckpt_X")

    assert r["error"] is None
    assert r["global"] == []                        # §3: no global memory
    # Two mcp sources + one file_client source
    sources = {e["source"] for e in r["entries"]}
    assert sources == {"mcp", "file_client"}
    assert {"root", "child_1"}.issubset(set(r["by_node"].keys()))


def test_memory_api_missing_checkpoint():
    from ari.viz import api_state
    with patch.object(api_state, "_resolve_checkpoint_dir", return_value=None):
        r = api_state._api_checkpoint_memory("nope")
    assert r == {"error": "checkpoint not found"}


def test_memory_api_reports_backend_errors(tmp_path, monkeypatch):
    _add_library_path()
    from ari.viz import api_state
    ckpt = tmp_path / "ckpt_bad"
    ckpt.mkdir()

    class _BoomBackend:
        def list_all_nodes(self):
            raise RuntimeError("letta unreachable")
        def list_react_entries(self):
            return []

    def _bad_get_backend(*a, **kw):  # noqa: D401
        return _BoomBackend()

    # Inject a failing backend — monkeypatch the module that api_state imports.
    import ari_skill_memory.backends as _b_mod
    with patch.object(_b_mod, "get_backend", side_effect=_bad_get_backend), \
         patch.object(api_state, "_resolve_checkpoint_dir", return_value=ckpt):
        r = api_state._api_checkpoint_memory("ckpt_bad")

    assert r["error"] and "letta" in r["error"].lower()
    assert r["entries"] == []
    assert r["global"] == []
