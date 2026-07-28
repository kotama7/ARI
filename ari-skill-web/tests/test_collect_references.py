"""Tests for collect_references_iterative and refactored search helpers."""
import sys, os, json, asyncio
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_s2_paper(title, year="2023", cite_key="", bibtex=""):
    return {
        "title": title,
        "authors": [{"name": "Author A"}],
        "year": year,
        "abstract": f"Abstract of {title}",
        "citationStyles": {"bibtex": bibtex or f"@article{{{cite_key or 'key'},\n  title={{{title}}}\n}}"},
    }


def _make_s2_response(papers):
    """Simulate Semantic Scholar API JSON response."""
    return json.dumps({"data": papers}).encode()


def _run_async(coro):
    # A FRESH loop per call: a shared asyncio.get_event_loop() leaks state
    # across the async tests in this file (a prior test can leave it closed),
    # which surfaced as an order-dependent "coroutine was never awaited" failure.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# _search_s2_sync tests
# ---------------------------------------------------------------------------

def test_search_s2_sync_returns_list():
    from server import _search_s2_sync
    # Real API call (may return 0 results but should not error)
    result = _search_s2_sync("computational methods survey", limit=3)
    assert isinstance(result, list)
    for p in result:
        assert "title" in p
        assert "cite_key" in p
        assert "bibtex" in p


def test_search_s2_sync_with_mock():
    from server import _search_s2_sync
    papers = [_make_s2_paper("Paper A", cite_key="paperA2023")]
    mock_resp = MagicMock()
    mock_resp.read.return_value = _make_s2_response(papers)
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("server._req.urlopen", return_value=mock_resp):
        result = _search_s2_sync("test query", limit=5)
    assert len(result) == 1
    assert result[0]["title"] == "Paper A"
    assert result[0]["cite_key"] != ""


def test_search_s2_sync_handles_error():
    from server import _search_s2_sync
    with patch("server._req.urlopen", side_effect=Exception("timeout")):
        result = _search_s2_sync("test query")
    assert result == []


# ---------------------------------------------------------------------------
# _parse_s2_paper tests
# ---------------------------------------------------------------------------

def test_parse_s2_paper_extracts_cite_key():
    from server import _parse_s2_paper
    p = _make_s2_paper("Test Paper", cite_key="author2023test")
    result = _parse_s2_paper(p)
    assert result["title"] == "Test Paper"
    assert result["cite_key"] != ""
    assert result["year"] == "2023"


def test_parse_s2_paper_no_bibtex():
    from server import _parse_s2_paper
    p = {"title": "No BibTeX", "authors": [], "year": "2024",
         "abstract": "...", "citationStyles": {}}
    result = _parse_s2_paper(p)
    assert result["cite_key"] == ""
    assert result["bibtex"] == ""


# ---------------------------------------------------------------------------
# search_semantic_scholar (refactored) tests
# ---------------------------------------------------------------------------

def test_search_semantic_scholar_returns_dict():
    from server import search_semantic_scholar
    result = _run_async(search_semantic_scholar("computational methods", limit=2))
    assert isinstance(result, dict)
    assert "papers" in result
    assert "count" in result


def test_search_semantic_scholar_with_mock():
    from server import search_semantic_scholar
    papers = [_make_s2_paper("Paper X")]
    mock_resp = MagicMock()
    mock_resp.read.return_value = _make_s2_response(papers)
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("server._search_s2_sync", return_value=[{
        "title": "Paper X", "authors": ["A"], "year": "2023",
        "abstract": "...", "bibtex": "@article{x,...}", "cite_key": "x2023",
    }]):
        result = _run_async(search_semantic_scholar("test", limit=5))
    assert result["count"] == 1
    assert result["papers"][0]["title"] == "Paper X"


# ---------------------------------------------------------------------------
# _format_papers_for_llm tests
# ---------------------------------------------------------------------------

def test_format_papers_empty():
    from server import _format_papers_for_llm
    assert _format_papers_for_llm([]) == "(none yet)"


def test_format_papers_list():
    from server import _format_papers_for_llm
    papers = [
        {"title": "Paper A", "year": "2023"},
        {"title": "Paper B", "year": "2024"},
    ]
    result = _format_papers_for_llm(papers)
    assert "1. Paper A (2023)" in result
    assert "2. Paper B (2024)" in result


# ---------------------------------------------------------------------------
# _parse_query_response tests
# ---------------------------------------------------------------------------

def test_parse_query_response_valid_json():
    from server import _parse_query_response
    resp = '{"description": "missing baseline", "query": "benchmark optimization methods"}'
    assert _parse_query_response(resp) == "benchmark optimization methods"


def test_parse_query_response_json_in_text():
    from server import _parse_query_response
    resp = 'Here is my query: {"description": "...", "query": "scalability analysis"}'
    assert _parse_query_response(resp) == "scalability analysis"


def test_parse_query_response_invalid():
    from server import _parse_query_response
    assert _parse_query_response("No more citations needed") == ""
    assert _parse_query_response("random text") == ""


# ---------------------------------------------------------------------------
# _parse_selection_response tests
# ---------------------------------------------------------------------------

def test_parse_selection_valid():
    from server import _parse_selection_response
    assert _parse_selection_response("[0, 2, 4]", 5) == [0, 2, 4]


def test_parse_selection_out_of_range():
    from server import _parse_selection_response
    assert _parse_selection_response("[0, 10, 2]", 5) == [0, 2]


def test_parse_selection_embedded():
    from server import _parse_selection_response
    assert _parse_selection_response("Selected: [1, 3]", 5) == [1, 3]


def test_parse_selection_invalid():
    from server import _parse_selection_response
    assert _parse_selection_response("none", 5) == []


def test_parse_selection_empty():
    from server import _parse_selection_response
    assert _parse_selection_response("[]", 5) == []


# ---------------------------------------------------------------------------
# collect_references_iterative tests
# ---------------------------------------------------------------------------

def _mock_paper(title, year="2023"):
    return {
        "title": title, "authors": ["A"], "year": year,
        "abstract": f"Abstract of {title}", "bibtex": f"@article{{k,\n  title={{{title}}}\n}}",
        "cite_key": title.lower().replace(" ", ""),
    }


def test_collect_references_no_summary_returns_round1():
    """Without experiment_summary, should return only round-1 results."""
    from server import collect_references_iterative
    papers = [_mock_paper("Paper A"), _mock_paper("Paper B")]
    with patch("server._search_s2_sync", return_value=papers):
        result = _run_async(collect_references_iterative(
            experiment_summary="",
            keywords="test keywords",
            max_rounds=5,
            min_papers=5,
        ))
    assert result["count"] == 2
    assert result["rounds_used"] == 1


def test_collect_references_deduplication():
    """Duplicate papers (same title) should not appear twice."""
    from server import collect_references_iterative
    papers = [_mock_paper("Same Paper"), _mock_paper("Same Paper"), _mock_paper("Other")]
    with patch("server._search_s2_sync", return_value=papers), \
         patch("server._llm_call", new_callable=AsyncMock,
               return_value="No more citations needed"):
        result = _run_async(collect_references_iterative(
            experiment_summary="Some experiment",
            keywords="test",
            max_rounds=3,
            min_papers=5,
        ))
    titles = [p["title"] for p in result["papers"]]
    assert titles.count("Same Paper") == 1


def test_collect_references_early_termination():
    """LLM saying 'no more citations needed' should stop the loop."""
    from server import collect_references_iterative
    call_count = 0

    async def mock_llm(system, user, **kw):
        nonlocal call_count
        call_count += 1
        return "No more citations needed"

    with patch("server._search_s2_sync", return_value=[_mock_paper("P1")]), \
         patch("server._llm_call", side_effect=mock_llm):
        result = _run_async(collect_references_iterative(
            experiment_summary="Experiment about X",
            keywords="test",
            max_rounds=10,
            min_papers=5,
        ))
    assert result["rounds_used"] == 2  # round 1 + round 2 (terminated)
    # 2 LLM calls now: round-1 relevance filter over the S2 hits (added to close
    # the unfiltered-round-1 gap) + round-2 query gen. fail_open keeps P1 since
    # the mock reply isn't valid selection JSON.
    assert call_count == 2


def test_collect_references_multi_round():
    """Test full multi-round iteration with mocked LLM and S2."""
    from server import collect_references_iterative
    round_papers = {
        "test": [_mock_paper("Initial Paper")],
        "optimization methods": [_mock_paper("Optimization Paper")],
        "scalability analysis": [_mock_paper("Scalability Paper")],
    }
    call_idx = [0]

    def mock_s2(query, limit=10):
        for key, papers in round_papers.items():
            if key in query.lower():
                return papers
        return []

    llm_responses = [
        '{"description": "missing optimization", "query": "optimization methods"}',
        '{"description": "missing scalability", "query": "scalability analysis"}',
        "No more citations needed",
    ]

    async def mock_llm(system, user, **kw):
        if "selector" in system.lower() or "select" in system.lower():
            return "[0]"
        idx = call_idx[0]
        call_idx[0] += 1
        if idx < len(llm_responses):
            return llm_responses[idx]
        return "No more citations needed"

    with patch("server._search_s2_sync", side_effect=mock_s2), \
         patch("server._llm_call", side_effect=mock_llm):
        result = _run_async(collect_references_iterative(
            experiment_summary="Algorithm performance optimization",
            keywords="test",
            max_rounds=10,
            min_papers=3,
        ))
    assert result["count"] >= 2  # at least initial + some from rounds
    titles = [p["title"] for p in result["papers"]]
    assert "Initial Paper" in titles


def test_collect_references_llm_failure_continues():
    """LLM failures should not crash -- rounds are skipped."""
    from server import collect_references_iterative

    async def failing_llm(system, user, **kw):
        raise RuntimeError("LLM unavailable")

    with patch("server._search_s2_sync", return_value=[_mock_paper("P1")]), \
         patch("server._llm_call", side_effect=failing_llm):
        result = _run_async(collect_references_iterative(
            experiment_summary="Experiment",
            keywords="test",
            max_rounds=3,
            min_papers=5,
        ))
    # Should still return round-1 results
    assert result["count"] >= 1
    assert result["papers"][0]["title"] == "P1"


def test_collect_references_keyword_splitting():
    """Long comma-separated keywords should be split into sub-queries."""
    from server import collect_references_iterative
    queries_called = []

    def mock_s2(query, limit=10):
        queries_called.append(query)
        return [_mock_paper(f"Paper for {query}")]

    with patch("server._search_s2_sync", side_effect=mock_s2), \
         patch("server._llm_call", new_callable=AsyncMock,
               return_value="No more citations needed"):
        result = _run_async(collect_references_iterative(
            experiment_summary="Experiment",
            keywords="algorithm design, scalability, evaluation metrics",
            max_rounds=3,
            min_papers=5,
        ))
    # Should have called S2 with each sub-query
    assert len(queries_called) >= 3


def test_collect_references_output_format():
    """Output must match the expected format for downstream consumers."""
    from server import collect_references_iterative
    with patch("server._search_s2_sync", return_value=[_mock_paper("P1")]), \
         patch("server._llm_call", new_callable=AsyncMock,
               return_value="No more citations needed"):
        result = _run_async(collect_references_iterative(
            experiment_summary="Experiment",
            keywords="test keywords",
        ))
    assert "papers" in result
    assert "query" in result
    assert "count" in result
    assert result["query"] == "test keywords"
    for p in result["papers"]:
        assert "title" in p
        assert "authors" in p
        assert "year" in p
        assert "abstract" in p
        assert "bibtex" in p
        assert "cite_key" in p


# ── round-1 fallback relevance filtering + honest round accounting ──────────

_FB_MIX = [
    {"title": "Multicore wavefront diamond blocking for stencils", "year": "2014",
     "abstract": "stencil cache blocking"},
    {"title": "Polyhedral methods to optimize stencils on FPGAs", "year": "2024",
     "abstract": "stencil"},
    {"title": "Solution existence of polynomial optimization problems", "year": "2018",
     "abstract": "unrelated optimization"},
    {"title": "Optimal design of frame structures with Gumbel-Softmax", "year": "2024",
     "abstract": "unrelated"},
]


def _run_collect(monkeypatch, select_reply):
    """S2 dead -> round-1 arXiv fallback, with a scripted relevance selector."""
    import server

    monkeypatch.setattr(server, "_search_s2_sync", lambda q, limit=10: [])
    monkeypatch.setattr(server, "_arxiv_fallback", lambda q, limit=8: list(_FB_MIX))

    async def _fake_llm(sysmsg, user, **kw):
        # the query-generation stage terminates the loop; the selector replies
        # with the scripted value
        if "librarian" in (sysmsg or "").lower():
            return "No more citations needed"
        return select_reply

    monkeypatch.setattr(server, "_llm_call", _fake_llm)
    return asyncio.run(server.collect_references_iterative(
        experiment_summary="cache blocking for a 2D Jacobi stencil",
        keywords="stencil cache blocking", max_rounds=2))


def test_round1_arxiv_fallback_is_relevance_filtered(monkeypatch):
    """A bare keyword fallback is low precision. Before this, round-1 fallback
    papers bypassed the selector entirely (it only ran on rounds >=2), so an
    "optimization" keyword shipped polynomial-opt / topology-opt papers into the
    bibliography — and one was cited in the e2e run's paper."""
    out = _run_collect(monkeypatch, "[0, 1]")
    titles = [p["title"] for p in out["papers"]]
    assert len(titles) == 2, titles
    assert all("stencil" in t.lower() for t in titles), titles


def test_round1_filter_fails_open_when_the_selector_is_unusable(monkeypatch):
    """``_parse_selection_response`` returns [] both for "nothing relevant" and
    for an unparseable reply. Dropping everything on round 1 would ship a paper
    with NO references — strictly worse than an imprecise bibliography — so the
    round-1 caller keeps the candidates."""
    out = _run_collect(monkeypatch, "not json at all")
    assert out["count"] == len(_FB_MIX), out["count"]


def test_rounds_used_is_reported_alongside_productive_rounds(monkeypatch):
    """``rounds_used`` counts loop ITERATIONS. With the retrieval backend down
    every round no-ops, so a bare rounds_used=13 read as productive work that
    never happened; productive_rounds / s2_available / fallback_used make the
    outage visible."""
    out = _run_collect(monkeypatch, "[0, 1]")
    assert out["s2_available"] is False
    assert out["fallback_used"] is True
    assert out["productive_rounds"] <= out["rounds_used"]
    assert out["productive_rounds"] == 1      # only round 1 added anything


def test_round1_s2_hits_are_relevance_filtered():
    """Regression: round-1 Semantic Scholar hits are now run through the
    relevance selector (previously added UNFILTERED). An off-topic keyword
    match is dropped when there is an experiment to judge against."""
    from server import collect_references_iterative
    on = _mock_paper("Cache blocking for 2D Jacobi stencils")
    off = _mock_paper("Phased-array antenna tiling for radar")
    with patch("server._search_s2_sync", return_value=[on, off]), \
         patch("server._llm_call", new_callable=AsyncMock, return_value="[0]"):
        result = _run_async(collect_references_iterative(
            experiment_summary="2D Jacobi stencil cache blocking bandwidth",
            keywords="tiling",
            max_rounds=1,
            min_papers=5,
        ))
    titles = [p["title"] for p in result["papers"]]
    assert "Cache blocking for 2D Jacobi stencils" in titles
    assert "Phased-array antenna tiling for radar" not in titles  # off-topic dropped


def test_search_s2_sync_retries_on_429_then_succeeds(monkeypatch):
    """A transient S2 429 is RETRIED (backoff), not dropped straight to the
    arXiv fallback: first call 429s, second returns papers."""
    import urllib.error as _ue, io
    from server import _search_s2_sync
    calls = {"n": 0}
    def fake_urlopen(req, timeout=15):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _ue.HTTPError(req.full_url, 429, "Too Many Requests",
                                {"Retry-After": "0"}, io.BytesIO(b""))
        class _R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self):
                return json.dumps({"data": [_make_s2_paper("Paper R", cite_key="r2023")]}).encode()
        return _R()
    monkeypatch.setattr("server._req.urlopen", fake_urlopen)
    monkeypatch.setattr("server._time.sleep", lambda s: None)
    out = _search_s2_sync("q", limit=3)
    assert calls["n"] == 2                       # retried once, then succeeded
    assert out and out[0]["title"] == "Paper R"


def test_search_s2_sync_gives_up_after_persistent_429(monkeypatch):
    """Persistent 429 -> [] (caller falls back to arXiv), never raises."""
    import urllib.error as _ue, io
    from server import _search_s2_sync
    n = {"c": 0}
    def always_429(req, timeout=15):
        n["c"] += 1
        raise _ue.HTTPError(req.full_url, 429, "rate", {"Retry-After": "0"}, io.BytesIO(b""))
    monkeypatch.setattr("server._req.urlopen", always_429)
    monkeypatch.setattr("server._time.sleep", lambda s: None)
    assert _search_s2_sync("q") == []
    assert n["c"] >= 2                           # attempted more than once


def test_search_s2_sync_non_429_fails_fast(monkeypatch):
    """A non-429 error is NOT retried (fail fast to [])."""
    from server import _search_s2_sync
    n = {"c": 0}
    def boom(req, timeout=15):
        n["c"] += 1
        raise Exception("connection reset")
    monkeypatch.setattr("server._req.urlopen", boom)
    monkeypatch.setattr("server._time.sleep", lambda s: None)
    assert _search_s2_sync("q") == []
    assert n["c"] == 1                           # no retry on non-429
