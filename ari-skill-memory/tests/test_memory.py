"""Tests for the node-scope MCP tool surface."""
from __future__ import annotations

import os

import pytest


def test_add_memory_returns_ok(backend):
    r = backend.add_memory("nX", "tool slurm_submit result=ok", {})
    assert r["ok"] is True
    assert "id" in r


def test_search_memory_ancestor_only(backend, monkeypatch):
    # seed three nodes — only root + child are ancestors of nX
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "root")
    backend.add_memory("root", "MFLOPS baseline 12000", {})
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "node_child1")
    backend.add_memory("node_child1", "MFLOPS improved 280000", {})
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "node_sibling")
    backend.add_memory("node_sibling", "MFLOPS sibling 100", {})

    r = backend.search_memory(
        "MFLOPS", ancestor_ids=["root", "node_child1"], limit=10
    )
    texts = [x["text"] for x in r["results"]]
    assert any("baseline" in t for t in texts)
    assert any("improved" in t for t in texts)
    assert not any("sibling" in t for t in texts)


def test_search_memory_empty_ancestors(backend):
    r = backend.search_memory("something", ancestor_ids=[], limit=5)
    assert r["results"] == []


def test_get_node_memory(backend, monkeypatch):
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "n1")
    backend.add_memory("n1", "entry A", {})
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "n2")
    backend.add_memory("n2", "entry B", {})

    r = backend.get_node_memory("n1")
    assert len(r["entries"]) == 1
    assert r["entries"][0]["text"] == "entry A"


def test_clear_node_memory(backend, monkeypatch):
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "n1")
    backend.add_memory("n1", "to delete", {})
    r = backend.clear_node_memory("n1")
    assert r["removed"] == 1
    assert backend.get_node_memory("n1")["entries"] == []


def test_search_score_ordering(backend, monkeypatch):
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "root")
    backend.add_memory("root", "MFLOPS", {})
    backend.add_memory("root", "MFLOPS MFLOPS high result", {})
    r = backend.search_memory("MFLOPS high", ancestor_ids=["root"], limit=5)
    assert r["results"][0]["score"] >= r["results"][-1]["score"]


def test_score_contract_is_float(backend, monkeypatch):
    """search_memory score is a float in [0, 1]."""
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", "root")
    backend.add_memory("root", "alpha beta gamma", {})
    r = backend.search_memory("alpha", ancestor_ids=["root"], limit=5)
    score = r["results"][0]["score"]
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0
