"""Ancestor-scope invariant test.

Three sibling branches × 50 entries × several queries, asserting no
sibling contamination. Runs against InMemoryBackend (deterministic
keyword scoring) and against LettaBackend wired to a FakeLettaClient in
both pre-filter and over-fetch-fallback modes.
"""
from __future__ import annotations

import os


def _seed(add_fn, set_node_env, branch, n):
    for i in range(n):
        set_node_env(branch)
        add_fn(branch, f"branch={branch} idx={i} metric={1000 + i}", {"i": i})


def _check(search_fn, my_ancestors, sibling_branches):
    for q in ("metric", "idx", "branch"):
        r = search_fn(q, my_ancestors, limit=10)
        for e in r["results"]:
            text = e["text"]
            for sib in sibling_branches:
                assert f"branch={sib}" not in text, (
                    f"sibling contamination: {text!r} in ancestors={my_ancestors}"
                )


def test_in_memory_ancestor_scope(backend, monkeypatch):
    def _set(n):
        monkeypatch.setenv("ARI_CURRENT_NODE_ID", n)

    for branch in ("A", "B", "C"):
        _seed(backend.add_memory, _set, branch, 50)

    _check(backend.search_memory, my_ancestors=["A"], sibling_branches=["B", "C"])
    _check(backend.search_memory, my_ancestors=["B"], sibling_branches=["A", "C"])
    _check(backend.search_memory, my_ancestors=["C"], sibling_branches=["A", "B"])


def test_letta_backend_pre_filter(fake_letta_backend, monkeypatch):
    backend, fake = fake_letta_backend
    fake.supports_pre_filter = True
    def _set(n):
        monkeypatch.setenv("ARI_CURRENT_NODE_ID", n)
    for branch in ("A", "B", "C"):
        _seed(backend.add_memory, _set, branch, 20)
    _check(backend.search_memory, my_ancestors=["A"], sibling_branches=["B", "C"])
    _check(backend.search_memory, my_ancestors=["B"], sibling_branches=["A", "C"])


def test_letta_backend_over_fetch_fallback(fake_letta_backend, monkeypatch):
    backend, fake = fake_letta_backend
    # Flip the fake to reject pre-filter so LettaBackend falls back.
    fake.supports_pre_filter = False

    def _set(n):
        monkeypatch.setenv("ARI_CURRENT_NODE_ID", n)

    for branch in ("A", "B", "C"):
        _seed(backend.add_memory, _set, branch, 20)

    _check(backend.search_memory, my_ancestors=["A"], sibling_branches=["B", "C"])
    _check(backend.search_memory, my_ancestors=["B"], sibling_branches=["A", "C"])
