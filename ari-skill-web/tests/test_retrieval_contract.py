"""Provider-neutral retrieval and cassette contract tests."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from retrieval import alias_groups, normalize_record


def _s2_row(paper_id: str = "ABC") -> dict:
    return {
        "paperId": paper_id,
        "externalIds": {"DOI": "https://doi.org/10.1000/TEST", "ArXiv": "2401.00001v2"},
        "title": "A reproducible paper",
        "authors": [{"name": "Ada Example"}],
        "year": 2024,
        "abstract": "Measured evidence.",
        "citationCount": 7,
        "url": f"https://www.semanticscholar.org/paper/{paper_id}",
    }


def test_provider_records_retain_distinct_origins_and_shared_aliases():
    now = datetime.now(timezone.utc)
    records = (
        normalize_record(
            _s2_row(), provider="semantic-scholar", query="test", retrieved_at=now
        ),
        normalize_record(
            {
                "arxiv_id": "2401.00001v5",
                "title": "A reproducible paper",
                "url": "https://arxiv.org/abs/2401.00001v5",
            },
            provider="arxiv",
            query="test",
            retrieved_at=now,
        ),
        normalize_record(
            {
                "alphaxiv_id": "ax-record-9",
                "arxivId": "2401.00001v3",
                "title": "A reproducible paper",
                "url": "https://alphaxiv.org/abs/2401.00001",
            },
            provider="alphaxiv",
            query="test",
            retrieved_at=now,
        ),
    )

    assert [record.canonical_id for record in records] == [
        "s2:abc",
        "arxiv:2401.00001",
        "alphaxiv:ax-record-9",
    ]
    assert alias_groups(records) == [
        [
            "alphaxiv:ax-record-9",
            "arxiv:2401.00001",
            "s2:abc",
        ]
    ]
    assert "doi:10.1000/test" in records[0].aliases


@pytest.mark.parametrize(
    ("provider", "row", "prefix"),
    [
        ("semantic-scholar", _s2_row(), "s2:"),
        (
            "arxiv",
            {"arxiv_id": "2402.00002v4", "title": "arXiv result"},
            "arxiv:",
        ),
        (
            "alphaxiv",
            {
                "alphaxiv_id": "result-2",
                "arxiv_id": "2402.00002",
                "title": "AlphaXiv result",
            },
            "alphaxiv:",
        ),
        (
            "duckduckgo",
            {"url": "https://example.org/result", "title": "Web result"},
            "duckduckgo:",
        ),
    ],
)
def test_provider_fixtures_normalize_to_one_public_contract(provider, row, prefix):
    record = normalize_record(
        row,
        provider=provider,
        query="fixture query",
        retrieved_at=datetime.now(timezone.utc),
    )

    assert record.schema_version == "ari.retrieval-record/v1"
    assert record.provider == provider
    assert record.canonical_id.startswith(prefix)
    assert record.payload_digest.startswith("sha256:")


def test_record_replay_is_offline_and_exact(tmp_path, monkeypatch):
    from server import search_papers

    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    with patch("server._provider_search", new=AsyncMock(return_value=[_s2_row()])):
        recorded = asyncio.run(
            search_papers("reproducibility", max_results=4, provider="semantic-scholar")
        )

    assert recorded["snapshot_ref"].endswith(
        recorded["survey_snapshot_digest"].removeprefix("sha256:") + ".json"
    )
    with patch(
        "server._provider_search",
        new=AsyncMock(side_effect=AssertionError("network must not run")),
    ):
        replayed = asyncio.run(
            search_papers(
                "reproducibility",
                max_results=4,
                provider="semantic-scholar",
                mode="replay",
                snapshot_ref=recorded["snapshot_ref"],
            )
        )

    assert replayed["records"] == recorded["records"]
    assert replayed["survey_snapshot"] == recorded["survey_snapshot"]
    assert replayed["survey_snapshot_digest"] == recorded["survey_snapshot_digest"]
    assert replayed["execution_mode"] == "replay"


def test_replay_rejects_parameter_substitution(tmp_path, monkeypatch):
    from server import search_papers

    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    with patch("server._provider_search", new=AsyncMock(return_value=[_s2_row()])):
        recorded = asyncio.run(
            search_papers("same query", max_results=2, provider="semantic-scholar")
        )

    with pytest.raises(ValueError, match="parameters"):
        asyncio.run(
            search_papers(
                "same query",
                max_results=3,
                provider="semantic-scholar",
                mode="replay",
                snapshot_ref=recorded["snapshot_ref"],
            )
        )


def test_replay_rejects_tampered_cassette(tmp_path, monkeypatch):
    from server import search_papers

    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    with patch("server._provider_search", new=AsyncMock(return_value=[_s2_row()])):
        recorded = asyncio.run(
            search_papers("tamper test", provider="semantic-scholar")
        )
    cassette = next(
        item
        for item in recorded["survey_snapshot"]["artifacts"]
        if item["role"] == "raw-provider-cassette"
    )
    path = Path(tmp_path, cassette["logical_name"])
    path.write_bytes(path.read_bytes() + b" ")

    with pytest.raises(ValueError, match="artifact digest mismatch"):
        asyncio.run(
            search_papers(
                "tamper test",
                provider="semantic-scholar",
                mode="replay",
                snapshot_ref=recorded["snapshot_ref"],
            )
        )


def test_record_requires_a_workspace(monkeypatch):
    from server import search_papers

    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    provider = AsyncMock(return_value=[_s2_row()])
    with patch("server._provider_search", new=provider):
        with pytest.raises(ValueError, match="record mode requires"):
            asyncio.run(search_papers("no workspace", provider="semantic-scholar"))
    provider.assert_not_awaited()


def test_pinned_provider_outage_is_explicit_and_never_falls_back():
    from server import RetrievalProviderError, search_papers

    with (
        patch("server._search_s2_raw_sync", side_effect=TimeoutError("offline")),
        patch(
            "server._arxiv_provider_rows",
            side_effect=AssertionError("fallback must not run"),
        ),
    ):
        with pytest.raises(RetrievalProviderError, match="semantic-scholar"):
            asyncio.run(
                search_papers(
                    "provider outage",
                    provider="semantic-scholar",
                    mode="live",
                )
            )


def test_arxiv_provider_uses_supported_client_api(monkeypatch):
    from server import _arxiv_provider_rows

    observed = {}

    class Search:
        def __init__(self, **kwargs):
            observed["search"] = kwargs

    class Client:
        def results(self, search):
            observed["client_search"] = search
            return iter(
                [
                    SimpleNamespace(
                        get_short_id=lambda: "2401.00001v3",
                        title="A current arxiv-py result",
                        authors=[SimpleNamespace(name="Ada Example")],
                        published=datetime(2024, 1, 2, tzinfo=timezone.utc),
                        summary="Measured evidence.",
                        entry_id="https://arxiv.org/abs/2401.00001v3",
                        license=None,
                    )
                ]
            )

    fake = SimpleNamespace(
        Search=Search,
        Client=Client,
        SortCriterion=SimpleNamespace(Relevance="relevance"),
    )
    monkeypatch.setitem(sys.modules, "arxiv", fake)

    rows = _arxiv_provider_rows("reproducibility", limit=2)

    assert observed["search"]["max_results"] == 2
    assert observed["client_search"] is not None
    assert rows == [
        {
            "id": "2401.00001",
            "arxiv_id": "2401.00001",
            "title": "A current arxiv-py result",
            "authors": ["Ada Example"],
            "year": 2024,
            "published": "2024-01-02T00:00:00+00:00",
            "abstract": "Measured evidence.",
            "url": "https://arxiv.org/abs/2401.00001v3",
            "license": None,
        }
    ]


def test_fetch_record_preserves_raw_body_and_replays_offline(tmp_path, monkeypatch):
    from network_policy import FetchedResponse
    from server import fetch_url

    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    fetched = FetchedResponse(
        url="https://example.org/data.txt",
        status=200,
        headers={
            "content-type": "text/plain; charset=utf-8",
            "etag": '"abc"',
        },
        body=b"measured source text",
        redirect_chain=(),
        pinned_ip="93.184.216.34",
    )
    with patch("server.fetch_pinned", return_value=fetched):
        recorded = fetch_url("https://example.org/data.txt")

    assert any(
        item["role"] == "raw-http-body"
        for item in recorded["survey_snapshot"]["artifacts"]
    )
    with patch("server.fetch_pinned", side_effect=AssertionError("network called")):
        replayed = fetch_url(
            "https://example.org/data.txt",
            mode="replay",
            snapshot_ref=recorded["snapshot_ref"],
        )
    assert replayed["text"] == recorded["text"]
    assert replayed["records"] == recorded["records"]
