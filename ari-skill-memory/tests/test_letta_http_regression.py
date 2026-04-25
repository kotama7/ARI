"""HTTP-layer regression tests for `_SdkLettaAdapter.archival_insert`.

These tests are the regression guard for the bug where Letta returned
``400 - {'detail': 'Expecting value: line 1 column 1 (char 0)'}`` when
``add_memory`` tried to insert a passage. That JSON-parse error is what
Python's ``json.loads('')`` raises — i.e. Letta received a body it could
not decode as JSON. The earlier FakeLettaClient-based tests only exercised
``_encode``/``_decode`` round-trip and never verified the bytes that
actually go on the wire, so they could not have caught a regression in
the SDK call path. These tests fix that gap by:

  - Using ``respx`` to intercept the real ``letta_client.Letta`` SDK at
    the HTTP boundary.
  - Driving ``_SdkLettaAdapter.archival_insert`` with non-ASCII text
    and metadata (the original failure mode).
  - Asserting the captured outbound request body is valid JSON
    (``json.loads(req.content)`` must succeed).
  - Asserting the body's ``text`` field round-trips through
    ``_SdkLettaAdapter._decode`` back to the original text + metadata.

If the adapter ever sends an unparseable body again — empty body,
malformed escapes, missing content-type, etc. — these tests fail.
"""
from __future__ import annotations

import json

import httpx
import pytest

respx = pytest.importorskip("respx")

from ari_skill_memory.backends.letta_client import _SdkLettaAdapter
from ari_skill_memory.config import MemoryConfig


_BASE = "http://letta-mock.test:8283"
_AGENT = "agent-regr0001"


def _passage_response(text: str, mem_id: str = "mem-001") -> httpx.Response:
    return httpx.Response(
        200,
        json=[{
            "id": mem_id,
            "text": text,
            "created_at": "2025-01-01T00:00:00Z",
        }],
    )


def _make_cfg(tmp_path) -> MemoryConfig:
    return MemoryConfig(
        checkpoint_dir=tmp_path,
        ckpt_hash="deadbeefcafe",
        backend_name="letta",
        letta_base_url=_BASE,
        letta_api_key="",
        letta_embedding_config="letta-default",
        letta_timeout_s=10.0,
        letta_overfetch=200,
        letta_disable_self_edit=True,
        access_log_enabled=False,
        access_log_preview_chars=200,
        access_log_max_mb=100,
        react_search_limit=10,
        react_max_entry_chars=0,
    )


def _make_adapter(tmp_path) -> _SdkLettaAdapter:
    from letta_client import Letta
    return _SdkLettaAdapter(_make_cfg(tmp_path), Letta)


# ---------------------------------------------------------------------------
# Regression: outbound body must be parseable JSON.
# ---------------------------------------------------------------------------

@respx.mock(base_url=_BASE)
def test_archival_insert_request_body_is_valid_json(tmp_path, respx_mock):
    """The exact regression for ``Expecting value: line 1 column 1 (char 0)``.

    Whatever the adapter sends MUST decode as JSON. A body that is empty,
    or that contains invalid escapes, would reproduce the original 400.
    """
    route = respx_mock.post(
        f"/v1/agents/{_AGENT}/archival-memory"
    ).mock(return_value=_passage_response("ok"))

    adapter = _make_adapter(tmp_path)
    adapter.archival_insert(
        agent_id=_AGENT,
        collection="default",
        text="hello",
        metadata={"node_id": "n1"},
    )

    assert route.called, "adapter never reached the HTTP layer"
    body = route.calls.last.request.content
    assert body, "outbound request body is empty (would reproduce 400)"
    # The actual regression assertion. Must not raise.
    parsed = json.loads(body)
    assert isinstance(parsed, dict)
    assert "text" in parsed


@respx.mock(base_url=_BASE)
def test_archival_insert_with_non_ascii_text_and_metadata(tmp_path, respx_mock):
    """Non-ASCII text + metadata must produce a parseable body.

    This is the realistic scenario — ARI nodes routinely include
    Japanese summaries and unicode identifiers. ``ensure_ascii=False``
    in ``_encode`` is what makes this round-trip survive; if it ever
    regresses to ``ensure_ascii=True`` (or the SDK's serializer
    strips invalid bytes), this test fails.
    """
    route = respx_mock.post(
        f"/v1/agents/{_AGENT}/archival-memory"
    ).mock(return_value=_passage_response("ok"))

    adapter = _make_adapter(tmp_path)
    text = "実験ノード結果: GFlops_per_s mean=12.502 — α/β τ=0.7"
    metadata = {
        "node_id": "ノード_α",
        "tags": ["性能", "ベンチマーク", "α"],
        "label": "日本語ラベル",
    }
    adapter.archival_insert(
        agent_id=_AGENT,
        collection="default",
        text=text,
        metadata=metadata,
    )

    assert route.called
    raw = route.calls.last.request.content
    parsed = json.loads(raw)  # must not raise

    sent_text = parsed["text"]
    decoded_text, decoded_meta = _SdkLettaAdapter._decode(sent_text)
    assert decoded_text == text
    assert decoded_meta.get("collection") == "default"
    assert decoded_meta.get("node_id") == "ノード_α"
    assert decoded_meta.get("tags") == ["性能", "ベンチマーク", "α"]
    assert decoded_meta.get("label") == "日本語ラベル"


@respx.mock(base_url=_BASE)
def test_archival_insert_with_control_chars_and_quotes(tmp_path, respx_mock):
    """Embedded quotes, newlines, backslashes must remain valid JSON.

    These are the bytes most likely to confuse a half-finished JSON
    encoder — if the adapter ever stops escaping them properly, the
    server's parser would explode in exactly the same way as the
    original bug.
    """
    route = respx_mock.post(
        f"/v1/agents/{_AGENT}/archival-memory"
    ).mock(return_value=_passage_response("ok"))

    adapter = _make_adapter(tmp_path)
    text = 'line1\nline2\twith "quotes" and \\backslash'
    metadata = {
        "raw": 'value with "quotes"\nand newline',
        "path": "C:\\Users\\test",
    }
    adapter.archival_insert(
        agent_id=_AGENT,
        collection="c",
        text=text,
        metadata=metadata,
    )

    assert route.called
    parsed = json.loads(route.calls.last.request.content)
    decoded_text, decoded_meta = _SdkLettaAdapter._decode(parsed["text"])
    assert decoded_text == text
    assert decoded_meta["raw"] == metadata["raw"]
    assert decoded_meta["path"] == metadata["path"]


@respx.mock(base_url=_BASE)
def test_archival_insert_with_empty_metadata(tmp_path, respx_mock):
    """Empty metadata must still produce a valid body — collection
    becomes the only metadata field, but JSON serialization must not
    short-circuit to an empty string."""
    route = respx_mock.post(
        f"/v1/agents/{_AGENT}/archival-memory"
    ).mock(return_value=_passage_response("ok"))

    adapter = _make_adapter(tmp_path)
    adapter.archival_insert(
        agent_id=_AGENT,
        collection="default",
        text="",
        metadata={},
    )

    assert route.called
    body = route.calls.last.request.content
    assert body, "empty body would reproduce the original 400"
    parsed = json.loads(body)
    assert "text" in parsed
    _, decoded_meta = _SdkLettaAdapter._decode(parsed["text"])
    assert decoded_meta == {"collection": "default"}


@respx.mock(base_url=_BASE)
def test_archival_insert_returns_id_from_real_sdk_response(tmp_path, respx_mock):
    """End-to-end through the real SDK serializer/deserializer.

    Asserts that ``archival_insert`` returns the id parsed out of the
    SDK's typed response when the server replies with a list. The
    earlier FakeLettaClient never went through the SDK's response
    parsing layer at all.
    """
    respx_mock.post(
        f"/v1/agents/{_AGENT}/archival-memory"
    ).mock(return_value=httpx.Response(
        200,
        json=[{
            "id": "mem-12345",
            "text": "anything",
            "created_at": "2025-01-01T00:00:00Z",
        }],
    ))
    adapter = _make_adapter(tmp_path)
    out = adapter.archival_insert(
        agent_id=_AGENT, collection="default",
        text="ping", metadata={"k": "v"},
    )
    assert out == "mem-12345"


@respx.mock(base_url=_BASE)
def test_archival_insert_propagates_server_400(tmp_path, respx_mock):
    """If the server actually returns 400, the SDK must surface it.

    This guards the *opposite* direction: we should not silently swallow
    a real 400 (which would mask exactly the kind of bug we're guarding
    against here).
    """
    respx_mock.post(
        f"/v1/agents/{_AGENT}/archival-memory"
    ).mock(return_value=httpx.Response(
        400,
        json={"detail": "Expecting value: line 1 column 1 (char 0)"},
    ))
    adapter = _make_adapter(tmp_path)
    with pytest.raises(Exception):
        adapter.archival_insert(
            agent_id=_AGENT, collection="c",
            text="x", metadata={},
        )
