"""Subtask 024 — BFTS tree-visualization adapter (``ari.viz.tree_view``).

Locks the contract that the WS ``update`` message, ``GET /state``, and the
checkpoint list/summary cards all resolve the BFTS node tree through the single
adapter ``build_tree_view`` — a byte-preserving wrapper over
``ari.checkpoint.load_nodes_tree`` (024 §13 Acceptance Criteria):

1. Exactly one backend function produces the tree-view payload; the WS handler,
   watcher broadcast, and the ``/state`` branch all route through it.
2. ``/state`` no longer re-reads tree.json/nodes_tree.json to recount
   ``node_count``; the value is identical to before for empty / nodes-present /
   legacy ``node_*/tree.json`` layouts.
3. The adapter output is byte-identical to ``ari.checkpoint.load_nodes_tree``
   (no added/removed/reordered key) for empty, single, multi, nodes_tree-only,
   and legacy layouts.
4. ``api_state`` re-exports are intact.
"""
from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

from ari import checkpoint as _ckpt
from ari.viz import state as _st
from ari.viz import api_state, checkpoint_api, state_sync
from ari.viz.tree_view import build_tree_view


# ── layout fixtures ──────────────────────────────────────────────────────────

def _flat_tree(root, n=2):
    root.mkdir(parents=True, exist_ok=True)
    (root / "tree.json").write_text(json.dumps({
        "run_id": "r", "created_at": "t",
        "nodes": [{"id": f"n{i}", "status": "success", "metrics": {}} for i in range(n)],
    }))
    return root


def _nodes_tree_only(root, n=3):
    root.mkdir(parents=True, exist_ok=True)
    (root / "nodes_tree.json").write_text(json.dumps({
        "experiment_goal": "g",
        "nodes": [{"id": f"n{i}", "status": "success"} for i in range(n)],
    }))
    return root


def _legacy_tree(root, n=2):
    (root / "node_abc").mkdir(parents=True, exist_ok=True)
    (root / "node_abc" / "tree.json").write_text(json.dumps({
        "nodes": [{"id": f"n{i}", "status": "success", "metrics": {}} for i in range(n)],
    }))
    return root


# ── criterion 3: byte-identical to the canonical loader ──────────────────────

@pytest.mark.parametrize("make,expected_nodes", [
    (_flat_tree, 2),
    (_nodes_tree_only, 3),
    (_legacy_tree, 2),
])
def test_adapter_matches_canonical_loader(tmp_path, make, expected_nodes):
    d = make(tmp_path / "ckpt")
    got = build_tree_view(d)
    ref = _ckpt.load_nodes_tree(d)
    assert got == ref, "adapter must return the canonical loader dict unchanged"
    assert got is not None and len(got["nodes"]) == expected_nodes
    # Byte-shape: the dict serializes identically (WS/`/state` use json.dumps).
    assert json.dumps(got, ensure_ascii=False) == json.dumps(ref, ensure_ascii=False)


def test_adapter_none_for_none_dir():
    assert build_tree_view(None) is None


def test_adapter_none_for_empty_and_nodesless(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert build_tree_view(empty) is None  # no tree files
    (empty / "tree.json").write_text("{}")  # nodes-less dict → None
    assert build_tree_view(empty) is None


def test_adapter_preserves_midwrite_retry_reject(tmp_path):
    d = tmp_path / "trunc"
    d.mkdir()
    (d / "tree.json").write_text('{"nodes": [{"id":')  # truncated
    assert build_tree_view(d) is None


# ── criterion 1: all loaders route through the one adapter ────────────────────

def test_all_loaders_route_through_adapter(tmp_path, monkeypatch):
    d = _flat_tree(tmp_path / "ckpt", n=2)
    sentinel = {"nodes": [{"id": "SENTINEL"}], "_via": "adapter"}
    monkeypatch.setattr("ari.viz.tree_view.build_tree_view", lambda cd: sentinel)

    # state_sync._load_nodes_tree (active checkpoint) → adapter
    monkeypatch.setattr(_st, "_checkpoint_dir", d, raising=False)
    assert state_sync._load_nodes_tree() is sentinel
    # checkpoint_api._load_nodes_tree(dir) → adapter
    assert checkpoint_api._load_nodes_tree(d) is sentinel
    # facade re-export resolves to the same delegating wrapper
    assert api_state._load_nodes_tree() is sentinel


def test_api_state_facade_reexports_adapter():
    assert api_state.build_tree_view is build_tree_view
    # Existing facade names still resolve (import-path contract, 024 §10).
    assert hasattr(api_state, "_load_nodes_tree")
    assert hasattr(api_state, "_broadcast")


# ── criterion 1/Contract D: the WS ``update`` envelope shape is unchanged ─────

def test_ws_broadcast_envelope_shape(monkeypatch):
    """``state_sync._broadcast`` still emits exactly {type,data,timestamp}."""
    captured = {}

    def _capture(msg):  # replace the async _do_broadcast with a sync recorder
        captured["msg"] = msg
        return None

    monkeypatch.setattr("ari.viz.api_state._do_broadcast", _capture, raising=False)
    monkeypatch.setattr(_st, "_clients", {object()}, raising=False)
    monkeypatch.setattr(_st, "_loop", object(), raising=False)
    monkeypatch.setattr(state_sync.asyncio, "run_coroutine_threadsafe",
                        lambda coro, loop: None)

    state_sync._broadcast({"nodes": [{"id": "n0"}]})
    parsed = json.loads(captured["msg"])
    assert parsed["type"] == "update"
    assert parsed["data"] == {"nodes": [{"id": "n0"}]}
    assert set(parsed.keys()) == {"type", "data", "timestamp"}


# ── criterion 2/3: /state node_count identical for all layouts (round-trip) ───

@pytest.fixture
def _isolated_state(monkeypatch, tmp_path):
    monkeypatch.setattr(_st, "_last_proc", None, raising=False)
    monkeypatch.setattr(_st, "_running_procs", {}, raising=False)
    monkeypatch.setattr(_st, "_launch_llm_model", "openai/gpt-4o", raising=False)
    monkeypatch.setattr(_st, "_launch_llm_provider", "openai", raising=False)
    monkeypatch.setattr(_st, "_settings_path", None, raising=False)
    yield


def _state_node_count(ckpt):
    from ari.viz.server import _Handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/state")
        resp = conn.getresponse()
        assert resp.status == 200
        payload = json.loads(resp.read())
        conn.close()
    finally:
        srv.shutdown()
    return payload


# Legacy ``node_*/tree.json``-only checkpoints do not set ``node_count`` in
# ``/state`` (that block is gated on a root-level tree/idea/experiment marker via
# ``_ckpt_valid`` — unchanged by 024); the legacy node_count precedence is
# exercised through the list/summary path in ``test_checkpoint_legacy_tree.py``,
# which now flows through this same adapter. Here we pin the two layouts that DO
# reach the /state node_count de-dup.
@pytest.mark.parametrize("make,expected", [
    (lambda r: _flat_tree(r, 2), 2),
    (lambda r: _nodes_tree_only(r, 3), 3),
])
def test_state_node_count_matches_layout(_isolated_state, monkeypatch, tmp_path, make, expected):
    ckpt = make(tmp_path / "checkpoints" / "20260101_state")
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt, raising=False)
    payload = _state_node_count(ckpt)
    assert payload["node_count"] == expected
    # node_count agrees with the emitted tree (the de-dup source).
    assert payload["node_count"] == len(payload.get("nodes", []))
