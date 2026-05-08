"""Phase 8 regression — search_memory must surface ancestor entries.

Production observation: in a real run against Letta 0.16.7, every
``search_memory`` call returned ``results: []`` despite 84 ``add_memory``
writes. Root cause (verified by inspecting ``letta.sif``): the SDK call
``passages.list(search=q)`` maps to ``GET /archival-memory?search=q``,
which routes through ``query_agent_passages_async`` with the default
``embed_query=False`` and ends in a SQL substring filter
(``LOWER(text) LIKE LOWER(%q%)``) — NOT semantic search. Long natural-
language queries like ``"Validate the loopline performance model"``
never substring-match structured passages like
``"RESULT SUMMARY metrics=[GFlops_per_s=15.82, ...]"``, so ancestor
entries are silently invisible.

Fix: skip the substring-matching path and use the real semantic route
``passages.search`` (``GET /archival-memory/search``,
``embed_query=True``) with an over-fetch budget, then post-filter by
ancestor metadata. Embedding-ranked order is preserved (no ts re-sort)
so the child sees entries most relevant to its query first.
"""

from __future__ import annotations

import pytest


def _add_as(b, monkeypatch, node_id, text, metadata=None):
    """Helper: write to the given node_id, satisfying the CoW check."""
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", node_id)
    return b.add_memory(node_id=node_id, text=text, metadata=metadata or {})


def test_fallback_to_archival_list_when_embedding_misses(fake_letta_backend, monkeypatch):
    """Reproduces the production bug — ancestor's stored summary does
    not lexically overlap with the child's query, so the (lexical-stub)
    embedding search returns 0 hits. The fallback path must still find
    it via archival_list + metadata filter."""
    b, fake = fake_letta_backend
    fake.supports_pre_filter = False  # match the live server

    # Parent ('orm_root') writes a result summary.
    _add_as(b, monkeypatch, "orm_root",
        "RESULT SUMMARY metrics=[GFlops_per_s=15.82, GB_per_s=33.74, K=512]",
        {"type": "result_summary"},
    )
    # And a couple of unrelated entries from sibling branches that
    # MUST NOT leak into ancestor-scoped search.
    _add_as(b, monkeypatch, "sibling_X",
        "UNRELATED data from a different branch", {"type": "noise"})
    _add_as(b, monkeypatch, "sibling_Y", "MORE noise", {"type": "noise"})

    # Child query phrased like a real prompt — no lexical overlap with
    # the result summary, so the embedding pass returns nothing.
    out = b.search_memory(
        query="Validate the loopline performance model",
        ancestor_ids=["orm_root"],
        limit=5,
    )
    results = out.get("results") or []
    assert len(results) >= 1
    # The recovered entry is the parent's, not a sibling's.
    titles = [r.get("text", "") for r in results]
    assert any("RESULT SUMMARY" in t for t in titles)
    assert all("UNRELATED" not in t and "MORE noise" not in t for t in titles)


def test_fallback_does_not_leak_other_ancestors(fake_letta_backend, monkeypatch):
    """The fallback path must respect the ancestor_ids filter — it
    does NOT degrade into a global search of the agent's whole pool."""
    b, fake = fake_letta_backend
    fake.supports_pre_filter = False
    _add_as(b, monkeypatch, "A", "A's secret")
    _add_as(b, monkeypatch, "B", "B's secret")
    _add_as(b, monkeypatch, "C", "C's secret")

    out = b.search_memory(
        query="totally unrelated query",
        ancestor_ids=["A"],
        limit=5,
    )
    texts = [r["text"] for r in out["results"]]
    assert any("A's secret" in t for t in texts)
    assert all("B's secret" not in t and "C's secret" not in t for t in texts)


def test_fallback_preserves_semantic_rank_order(fake_letta_backend, monkeypatch):
    """When the fallback fires the ancestor-scoped post-filter must
    NOT re-sort the results; the embedding-rank order returned by
    ``passages.search`` is what callers want (entries most relevant to
    the query first). For a query that semantically matches a specific
    entry, that entry should rank higher than the others."""
    import time
    b, fake = fake_letta_backend
    fake.supports_pre_filter = False
    _add_as(b, monkeypatch, "P", "oldest")
    time.sleep(0.01)
    _add_as(b, monkeypatch, "P", "middle")
    time.sleep(0.01)
    _add_as(b, monkeypatch, "P", "newest entry mentioning the special keyword vorpal")

    # Query that lexically matches only the third entry — the fake
    # client scores by keyword overlap, simulating real semantic rank.
    out = b.search_memory(
        query="vorpal keyword",
        ancestor_ids=["P"],
        limit=5,
    )
    texts = [r["text"] for r in out["results"]]
    assert len(texts) == 3
    # The semantically matching entry must come first.
    assert "vorpal" in texts[0]


def test_fallback_does_not_resort_by_ts(fake_letta_backend, monkeypatch):
    """Regression: prior implementation force-sorted by ts descending,
    discarding ranker output. Verify the post-filter no longer does
    that — when the underlying client returns rows in a specific
    order, that order survives the ancestor filter."""
    import time
    b, fake = fake_letta_backend
    fake.supports_pre_filter = False
    # Insert "zebra" oldest, "alpha" newest, both matching the query
    # equally (each entry contains "match" exactly once).
    _add_as(b, monkeypatch, "P", "zebra match")
    time.sleep(0.01)
    _add_as(b, monkeypatch, "P", "alpha match")

    out = b.search_memory(query="match", ancestor_ids=["P"], limit=5)
    texts = [r["text"] for r in out["results"]]
    assert set(texts) == {"zebra match", "alpha match"}
    # With equal scores the fake preserves insertion order. If the
    # post-filter re-sorted by ts (newest-first), "alpha match" would
    # win even though its rank is identical. Prove insertion order
    # survived — i.e. the post-filter did NOT inject a ts re-sort.
    assert texts[0] == "zebra match"


def test_embedding_search_path_still_used_when_it_works(fake_letta_backend, monkeypatch):
    """When the embedding search returns ancestor matches, the fallback
    list call should not run unnecessarily — though invoking it as a
    safety net is acceptable. We assert at least the search path fired."""
    b, fake = fake_letta_backend
    fake.supports_pre_filter = False
    _add_as(b, monkeypatch, "orm_root",
        "loopline model derived from STREAM",
        {"type": "result_summary"},
    )
    out = b.search_memory(
        query="loopline performance model",
        ancestor_ids=["orm_root"],
        limit=5,
    )
    # Got at least one ancestor result.
    assert len(out["results"]) >= 1
    assert any("loopline" in r["text"] for r in out["results"])
    # The embedding search path was exercised.
    assert len(fake.search_calls) >= 1


def test_empty_ancestors_short_circuits(fake_letta_backend, monkeypatch):
    """search_memory with empty ancestor_ids must short-circuit BEFORE
    any backend call — no fallback should fire either."""
    b, fake = fake_letta_backend
    fake.supports_pre_filter = False
    _add_as(b, monkeypatch, "P", "hi")
    out = b.search_memory(query="anything", ancestor_ids=[], limit=5)
    assert out == {"results": []}
    assert len(fake.search_calls) == 0
