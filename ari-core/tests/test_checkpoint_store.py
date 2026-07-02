"""Unit tests for JsonCheckpointStore + module back-compat shims (subtask 010).

Guards the checkpoint-format contract: byte-identical JSON, 3-tier
``load_nodes_tree`` precedence, the 1.0 s throttle, and — critically — the
``_INCR_LAST_SAVE_MONO`` module-attribute monkeypatch surface that
``tests/test_gui_errors.py`` relies on.
"""

from __future__ import annotations

import json

import ari.checkpoint as ck
from ari.checkpoint import JsonCheckpointStore
from ari.protocols import CheckpointStore


def test_store_satisfies_protocol():
    assert isinstance(JsonCheckpointStore(), CheckpointStore)


def test_module_shims_still_importable():
    # Every historical import path must keep resolving.
    from ari.checkpoint import (  # noqa: F401
        load_nodes_tree,
        load_nodes_tree_json,
        load_tree_json,
        save_nodes_tree_json,
        save_prompt_versions_json,
        save_results_json,
        save_tree_incremental,
        save_tree_json,
    )

    # The throttle bookkeeping stays a module attribute for the monkeypatch.
    assert isinstance(ck._INCR_LAST_SAVE_MONO, dict)
    assert ck._INCR_LOCK is not None
    assert ck._INCR_DEFAULT_MIN_INTERVAL_S == 1.0


def test_save_tree_json_byte_identical(tmp_path):
    tree = {
        "run_id": "r",
        "created_at": "t",
        "nodes": [{"id": "a", "status": "pending", "utf8": "café"}],
    }
    expected = json.dumps(tree, indent=2, ensure_ascii=False)

    ck.save_tree_json(tmp_path, tree)  # module shim
    d2 = tmp_path / "d2"
    d2.mkdir()
    JsonCheckpointStore().save_tree_json(d2, tree)  # store

    assert (tmp_path / "tree.json").read_text() == expected
    assert (d2 / "tree.json").read_text() == expected


def test_all_writers_roundtrip(tmp_path):
    ck.save_nodes_tree_json(tmp_path, {"nodes": [{"id": "n"}]})
    ck.save_results_json(tmp_path, {"score": 1})
    ck.save_prompt_versions_json(tmp_path, {"agent/system": {"call_count": 2}})

    assert ck.load_nodes_tree_json(tmp_path) == {"nodes": [{"id": "n"}]}
    assert json.loads((tmp_path / "results.json").read_text()) == {"score": 1}
    assert json.loads((tmp_path / "prompt_versions.json").read_text()) == {
        "agent/system": {"call_count": 2}
    }


def test_load_nodes_tree_precedence(tmp_path):
    # Nothing present.
    assert ck.load_nodes_tree(tmp_path) is None

    # nodes_tree.json is used when tree.json is absent.
    (tmp_path / "nodes_tree.json").write_text(json.dumps({"nodes": [{"id": "n"}]}))
    assert ck.load_nodes_tree(tmp_path)["nodes"][0]["id"] == "n"

    # tree.json takes precedence.
    (tmp_path / "tree.json").write_text(json.dumps({"nodes": [{"id": "t"}]}))
    assert ck.load_nodes_tree(tmp_path)["nodes"][0]["id"] == "t"

    # A nodes-less dict resolves to None (GUI empty-tree semantics).
    (tmp_path / "tree.json").write_text(json.dumps({"run_id": "x"}))
    assert ck.load_nodes_tree(tmp_path) is None


def test_load_nodes_tree_legacy_node_glob(tmp_path):
    nd = tmp_path / "node_1"
    nd.mkdir()
    (nd / "tree.json").write_text(json.dumps({"nodes": [{"id": "leg"}]}))
    assert ck.load_nodes_tree(tmp_path)["nodes"][0]["id"] == "leg"

    # An empty "{}" node tree is skipped (size <= 2).
    empty = tmp_path / "node_0"
    empty.mkdir()
    (empty / "tree.json").write_text("{}")
    assert ck.load_nodes_tree(tmp_path)["nodes"][0]["id"] == "leg"


def test_incremental_throttle_and_force_via_module_shim(tmp_path, monkeypatch):
    # Exactly the isolation pattern test_gui_errors.py uses.
    monkeypatch.setattr(ck, "_INCR_LAST_SAVE_MONO", {}, raising=True)
    calls: list[int] = []

    ck.save_tree_incremental(tmp_path, lambda: calls.append(1), force=False)
    assert calls == [1]  # first call always goes through

    ck.save_tree_incremental(tmp_path, lambda: calls.append(1), force=False)
    assert calls == [1]  # throttled within 1.0 s

    ck.save_tree_incremental(tmp_path, lambda: calls.append(1), force=True)
    assert calls == [1, 1]  # force bypasses the throttle

    # The monkeypatched module dict (not a stale captured one) was populated.
    assert str(tmp_path) in ck._INCR_LAST_SAVE_MONO


def test_store_instance_throttle_is_isolated(tmp_path):
    calls: list[int] = []
    s1 = JsonCheckpointStore()
    s1.save_tree_incremental(tmp_path, lambda: calls.append(1))
    s1.save_tree_incremental(tmp_path, lambda: calls.append(1))  # throttled
    assert calls == [1]

    # A separate instance owns a separate throttle map → not throttled.
    JsonCheckpointStore().save_tree_incremental(tmp_path, lambda: calls.append(1))
    assert calls == [1, 1]
