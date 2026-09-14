"""Bounded citation traversal and explicit reranker tests."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from retrieval import normalize_record


def _paper(paper_id: str) -> dict:
    return {
        "paperId": paper_id,
        "title": f"Paper {paper_id}",
        "authors": [{"name": "A"}],
        "year": 2025,
        "abstract": "Evidence",
        "url": f"https://www.semanticscholar.org/paper/{paper_id}",
    }


def test_citation_walk_detects_cycles_and_stays_bounded(tmp_path, monkeypatch):
    from server import walk_citations

    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    graph = {"a": [_paper("B")], "b": [_paper("A")]}
    with (
        patch("server._s2_paper_by_id", side_effect=lambda value: _paper(value)),
        patch(
            "server._s2_graph_page",
            side_effect=lambda value, _direction, _limit: graph[value],
        ),
    ):
        result = walk_citations(["s2:A"], max_depth=5, max_nodes=10, request_budget=10)

    assert result["count"] == 2
    assert result["requests_used"] == 3
    assert result["expanded_nodes"] == 2
    assert result["partial"] is False
    assert {
        (edge["source_id"], edge["target_id"]) for edge in result["citation_edges"]
    } == {
        ("s2:a", "s2:b"),
        ("s2:b", "s2:a"),
    }


def test_citation_walk_returns_explicit_partial_at_request_budget(
    tmp_path, monkeypatch
):
    from server import walk_citations

    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    with (
        patch("server._s2_paper_by_id", return_value=_paper("A")),
        patch("server._s2_graph_page", return_value=[_paper("B")]),
    ):
        result = walk_citations(["A"], max_depth=4, max_nodes=10, request_budget=2)

    assert result["partial"] is True
    assert result["partial_reason"] == "request-budget-exhausted"
    assert result["requests_used"] == 2
    assert result["count"] == 2


def test_deterministic_search_never_calls_the_reranker():
    from server import search_papers

    with (
        patch("server._provider_search", new=AsyncMock(return_value=[_paper("A")])),
        patch(
            "server._llm_call",
            new=AsyncMock(side_effect=AssertionError("LLM must not be called")),
        ),
    ):
        result = asyncio.run(
            search_papers("bounded search", provider="semantic-scholar", mode="live")
        )
    assert result["count"] == 1


def test_explicit_reranker_returns_model_and_digest_provenance():
    from server import rerank_retrieval_records

    records = [
        normalize_record(
            _paper(paper_id),
            provider="semantic-scholar",
            query="ranking",
            retrieved_at=datetime.now(timezone.utc),
        ).model_dump(mode="json")
        for paper_id in ("A", "B")
    ]
    with patch("server._llm_call", new=AsyncMock(return_value="[1, 0]")):
        result = asyncio.run(
            rerank_retrieval_records("Which is relevant?", records, max_results=2)
        )

    assert result["ordered_canonical_ids"] == ["s2:b", "s2:a"]
    assert result["provenance"]["model"]
    assert result["provenance"]["prompt_digest"].startswith("sha256:")
    assert result["provenance"]["input_digest"].startswith("sha256:")
    assert result["provenance"]["output_digest"].startswith("sha256:")


def test_reranker_rejects_an_unparseable_selection():
    from server import rerank_retrieval_records

    record = normalize_record(
        _paper("A"),
        provider="semantic-scholar",
        query="ranking",
        retrieved_at=datetime.now(timezone.utc),
    ).model_dump(mode="json")
    with patch("server._llm_call", new=AsyncMock(return_value="not-json")):
        with pytest.raises(ValueError, match="no valid"):
            asyncio.run(rerank_retrieval_records("question", [record]))
