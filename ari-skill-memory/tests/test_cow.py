"""CoW enforcement — writes must match ARI_CURRENT_NODE_ID."""
from __future__ import annotations

import os


def test_cow_violation_add(backend, monkeypatch):
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "child")
    # Seed ancestor entries first from its own turn.
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "ancestor")
    backend.add_memory("ancestor", "original", {})
    # Now switch to child and try to write as ancestor.
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "child")
    r = backend.add_memory("ancestor", "mutation", {})
    assert r == {"ok": False, "error": "node_id does not match current node (CoW violation)"}
    # Original entry unchanged.
    entries = backend.get_node_memory("ancestor")["entries"]
    assert len(entries) == 1
    assert entries[0]["text"] == "original"


def test_cow_violation_clear(backend, monkeypatch):
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "ancestor")
    backend.add_memory("ancestor", "A", {})
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "child")
    r = backend.clear_node_memory("ancestor")
    assert "error" in r
    assert backend.get_node_memory("ancestor")["entries"]


def test_cow_missing_env(backend, monkeypatch):
    monkeypatch.delenv("ARI_CURRENT_NODE_ID", raising=False)
    r = backend.add_memory("any", "x", {})
    assert r == {"ok": False, "error": "ARI_CURRENT_NODE_ID not set"}
