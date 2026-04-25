"""Backup/restore round-trip for checkpoint-scoped Letta collections."""
from __future__ import annotations

import gzip
import json
import os


def test_backup_restore_roundtrip(ckpt_env, monkeypatch):
    # Import here so the env is already configured.
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ari-core"))
    from ari.memory_cli import _do_backup, _do_restore, _backup_path
    from ari_skill_memory.backends import get_backend

    b = get_backend(checkpoint_dir=ckpt_env)
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "root")
    b.add_memory("root", "alpha", {"k": "v"})
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "child")
    b.add_memory("child", "beta", {"q": 1})
    b.react_add("ran kernel", {"node_id": "root"})

    n = _do_backup(ckpt_env)
    assert n >= 3
    assert _backup_path(ckpt_env).exists()

    # Purge and restore.
    b.purge_checkpoint()
    assert b.list_all_nodes().get("by_node") == {}
    res = _do_restore(ckpt_env, on_conflict="overwrite")
    assert res["restored"] >= 3
    # Entries back.
    all_nodes = b.list_all_nodes()["by_node"]
    assert "root" in all_nodes
    assert "child" in all_nodes
    assert len(b.react_get_all()) == 1
