"""Tests for typed MCP result normalization and artifact externalization."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import CancelledError

import pytest
from pydantic import ValidationError

from ari.artifact_store import CheckpointArtifactStore
from ari.config import SkillConfig
from ari.mcp.client import MCPClient, _runtime_tool_ref
from ari.result import (
    ResultArtifactIntegrityError,
    ResultEnvelopeNormalizer,
    ResultEnvelopeV1,
    ToolCallContextV1,
)


START = "2026-08-02T00:00:00Z"
END = "2026-08-02T00:00:01Z"
TOOL_REF = "ari-skill-fixture/inspect@sha256:" + ("a" * 64)


def _normalize(normalizer: ResultEnvelopeNormalizer, response: dict):
    return normalizer.normalize_legacy(
        response,
        tool_ref=TOOL_REF,
        context=ToolCallContextV1(
            run_id="run-1",
            node_id="node-1",
            phase="bfts",
            selection_reason="test",
        ),
        started_at=START,
        completed_at=END,
    )


def test_short_json_result_is_structured_and_round_trips():
    raw = json.dumps({"metric": 12.5, "status": "ok"})
    envelope = _normalize(ResultEnvelopeNormalizer(), {"result": raw})

    assert envelope.schema_version == "ari.result-envelope/v1"
    assert envelope.status == "ok"
    assert envelope.structured_content == {"metric": 12.5, "status": "ok"}
    assert envelope.artifacts == []
    assert envelope.provenance.run_id == "run-1"
    assert envelope.provenance.node_id == "node-1"
    assert envelope.provenance.duration_ms == 1_000
    assert envelope.to_legacy() == {"result": raw}


def test_large_result_is_externalized_and_losslessly_materialized(tmp_path):
    store = CheckpointArtifactStore(tmp_path)
    raw = json.dumps({"payload": "測" * 4_100}, ensure_ascii=False)
    envelope = _normalize(
        ResultEnvelopeNormalizer(store, inline_limit=4_000),
        {"result": raw},
    )

    assert envelope.content_truncated is True
    assert len(envelope.content) <= 4_000
    assert envelope.structured_content == {}
    assert len(envelope.artifacts) == 1
    artifact = envelope.artifacts[0]
    payload = raw.encode("utf-8")
    assert artifact.digest == f"sha256:{hashlib.sha256(payload).hexdigest()}"
    assert artifact.size == len(payload)
    assert artifact.media_type == "application/json"
    assert store.get(artifact.logical_name).read_text() == raw
    assert envelope.materialize_content(store) == raw
    assert envelope.to_legacy(store) == {"result": raw}


def test_content_address_is_deterministic_and_deduplicated(tmp_path):
    store = CheckpointArtifactStore(tmp_path)
    normalizer = ResultEnvelopeNormalizer(store, inline_limit=10)
    raw = "same-result" * 20
    first = _normalize(normalizer, {"result": raw})
    second = _normalize(normalizer, {"result": raw})

    assert first.artifacts == second.artifacts
    assert len(first.content) <= 10
    assert len(list((tmp_path / "artifacts" / "mcp-results").rglob("*.txt"))) == 1


def test_materialization_fails_closed_after_artifact_tampering(tmp_path):
    store = CheckpointArtifactStore(tmp_path)
    envelope = _normalize(
        ResultEnvelopeNormalizer(store, inline_limit=10),
        {"result": "x" * 100},
    )
    artifact = envelope.artifacts[0]
    store.get(artifact.logical_name).write_text("tampered")

    with pytest.raises(ResultArtifactIntegrityError, match="digest mismatch"):
        envelope.materialize_content(store)
    assert "digest mismatch" in envelope.to_legacy(store)["error"]


def test_tool_error_is_typed_but_preserves_legacy_result_shape():
    raw = json.dumps({"error": "invalid scientific input", "code": "bad-unit"})
    envelope = _normalize(ResultEnvelopeNormalizer(), {"result": raw})

    assert envelope.status == "error"
    assert envelope.error is not None
    assert envelope.error.kind == "tool"
    assert envelope.error.retryable is False
    assert envelope.to_legacy() == {"result": raw}


def test_transport_error_is_typed_and_preserves_outer_error_shape():
    envelope = _normalize(
        ResultEnvelopeNormalizer(),
        {
            "error": "connection closed",
            "_error_kind": "transport",
            "_retryable": True,
        },
    )

    assert envelope.status == "error"
    assert envelope.error is not None
    assert envelope.error.kind == "transport"
    assert envelope.error.retryable is True
    assert envelope.to_legacy() == {"error": "connection closed"}


def test_without_store_result_remains_lossless_and_unbounded():
    raw = "z" * 4_001
    envelope = _normalize(
        ResultEnvelopeNormalizer(artifact_store=None, inline_limit=4_000),
        {"result": raw},
    )
    assert envelope.content == raw
    assert envelope.content_truncated is False
    assert envelope.artifacts == []


def test_envelope_rejects_inconsistent_error_status():
    provenance = _normalize(ResultEnvelopeNormalizer(), {"result": "ok"}).provenance
    with pytest.raises(ValidationError, match="status=error requires error"):
        ResultEnvelopeV1(status="error", provenance=provenance)


def test_malformed_legacy_response_is_a_typed_protocol_error():
    envelope = _normalize(ResultEnvelopeNormalizer(), {})

    assert envelope.status == "error"
    assert envelope.error is not None
    assert envelope.error.kind == "protocol"
    assert envelope.error.retryable is True


class _FakeConnection:
    def __init__(self, skill: SkillConfig, response: dict):
        self.skill = skill
        self.response = response
        self.calls: list[tuple[str, dict, int]] = []

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": "inspect",
                "description": "fixture",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
                "skill_name": self.skill.name,
            }
        ]

    def call_tool(self, name: str, args: dict, timeout: int) -> dict:
        self.calls.append((name, args, timeout))
        return self.response

    def close(self) -> None:
        pass


class _RaisingConnection(_FakeConnection):
    def __init__(self, skill: SkillConfig, exception: BaseException):
        super().__init__(skill, {})
        self.exception = exception

    def call_tool(self, name: str, args: dict, timeout: int) -> dict:
        self.calls.append((name, args, timeout))
        raise self.exception


def _skill_config() -> SkillConfig:
    return SkillConfig(
        name="fixture-skill",
        package="ari-skill-fixture",
        version="1.0.0",
        path="/tmp/fixture",
        tool_refs={"inspect": "ari-skill-fixture/inspect@sha256:" + ("b" * 64)},
        tool_capabilities={"inspect": "ari.fixture.inspect"},
        tool_policies={
            "inspect": {
                "phases": ["bfts"],
                "side_effects": "read-only",
                "determinism": "deterministic",
                "timeout_class": "bounded",
                "permissions": ["workspace-read"],
                "result_schema": "ari.result-envelope/v1",
            }
        },
        tool_timeout_classes={"inspect": "bounded"},
    )


def test_mcp_client_exposes_runtime_tool_ref_and_typed_dispatch(tmp_path, monkeypatch):
    skill = _skill_config()
    raw = json.dumps({"payload": "x" * 200})
    connection = _FakeConnection(skill, {"result": raw})
    store = CheckpointArtifactStore(tmp_path)
    client = MCPClient(
        [skill],
        artifact_store=store,
        result_inline_limit=50,
    )
    monkeypatch.setattr(client, "_init_connection", lambda _skill: connection)

    tool = client.list_tools()[0]
    assert tool["tool_ref"].startswith("ari-skill-fixture/inspect@sha256:")
    assert tool["capability_ref"] == "ari.fixture.inspect"
    assert tool["policy"]["determinism"] == "deterministic"

    envelope = client.call_tool_envelope(
        tool["tool_ref"],
        {"query": "q"},
        context=ToolCallContextV1(run_id="run-typed", node_id="node-typed"),
    )
    assert envelope.status == "ok"
    assert envelope.content_truncated is True
    assert envelope.provenance.tool_ref == tool["tool_ref"]
    assert envelope.provenance.selection_reason == "immutable-tool-ref"
    assert envelope.provenance.run_id == "run-typed"
    assert envelope.to_legacy(store) == {"result": raw}

    # The compatibility API traverses the same typed normalization path and then
    # materializes the content-addressed raw artifact without changing its shape.
    assert client.call_tool("inspect", {"query": "legacy"}) == {"result": raw}


def test_typed_dispatch_enforces_disabled_and_phase_policy(monkeypatch):
    skill = _skill_config()
    connection = _FakeConnection(skill, {"result": "ok"})
    client = MCPClient([skill], disabled_tools=["inspect"])
    monkeypatch.setattr(client, "_init_connection", lambda _skill: connection)
    tool_ref = client._tools_cache[0]["tool_ref"] if client._tools_cache else None
    if tool_ref is None:
        client._build_tools_cache()
        tool_ref = client._tools_cache[0]["tool_ref"]

    disabled = client.call_tool_envelope(tool_ref, {})
    assert disabled.error is not None
    assert disabled.error.kind == "admission"
    assert "disabled" in disabled.error.message
    assert connection.calls == []

    client.disabled_tools.clear()
    wrong_phase = client.call_tool_envelope(
        tool_ref,
        {},
        context=ToolCallContextV1(phase="paper"),
    )
    assert wrong_phase.error is not None
    assert wrong_phase.error.kind == "admission"
    assert "phase 'paper'" in wrong_phase.error.message
    assert connection.calls == []
    assert client.list_tools(phase="paper") == []
    assert [tool["name"] for tool in client.list_tools(phase="bfts")] == ["inspect"]


def test_runtime_tool_ref_changes_when_input_schema_changes():
    skill = _skill_config()
    base = {"name": "inspect", "inputSchema": {"type": "object"}}
    changed = {
        "name": "inspect",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    }
    assert _runtime_tool_ref(skill, base) != _runtime_tool_ref(skill, changed)


def test_runtime_tool_ref_changes_when_output_schema_changes():
    skill = _skill_config()
    base = {"name": "inspect", "inputSchema": {"type": "object"}}
    changed = {
        **base,
        "outputSchema": {
            "type": "object",
            "required": ["measurement"],
            "properties": {"measurement": {"type": "number"}},
        },
    }
    assert _runtime_tool_ref(skill, base) != _runtime_tool_ref(skill, changed)


@pytest.mark.parametrize(
    ("exception", "kind", "expected_calls"),
    [
        (TimeoutError("deadline"), "timeout", 3),
        (CancelledError("stopped"), "cancelled", 1),
    ],
)
def test_mcp_client_types_timeout_and_cancellation(
    exception, kind, expected_calls, monkeypatch
):
    skill = _skill_config()
    connection = _RaisingConnection(skill, exception)
    client = MCPClient([skill])
    monkeypatch.setattr(client, "_init_connection", lambda _skill: connection)
    monkeypatch.setattr("ari.mcp.invoke_runtime.RETRY_DELAY", 0)

    envelope = client.call_tool_envelope("inspect", {})

    assert envelope.status == "error"
    assert envelope.error is not None
    assert envelope.error.kind == kind
    assert len(connection.calls) == expected_calls


class _ContextConnection(_FakeConnection):
    def __init__(self, skill: SkillConfig, response: dict):
        super().__init__(skill, response)
        self.contexts = []

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": "add_memory",
                "description": "fixture",
                "inputSchema": {"type": "object"},
                "skill_name": self.skill.name,
            }
        ]

    def authorize_args(self, tool_name, args, context):
        self.contexts.append(context)
        return {**args, "ari_context": {"transport_injected": True}}


def test_immutable_tool_ref_preserves_explicit_node_context(monkeypatch):
    from ari.call_context import ToolCallContextV1

    skill = SkillConfig(
        name="memory",
        package="ari-skill-memory",
        path="/tmp/memory",
        tool_policies={
            "add_memory": {
                "phases": ["bfts"],
                "context_requirement": "node",
            }
        },
    )
    connection = _ContextConnection(skill, {"result": "ok"})
    client = MCPClient([skill])
    monkeypatch.setattr(client, "_init_connection", lambda _skill: connection)
    add_memory_ref = next(
        tool["tool_ref"] for tool in client.list_tools() if tool["name"] == "add_memory"
    )

    context = ToolCallContextV1.for_node(
        run_id="run-1",
        node_id="node-1",
        phase="bfts",
    )
    envelope = client.call_tool_envelope(
        add_memory_ref,
        {"node_id": "node-1", "text": "fact"},
        context=context,
    )

    assert envelope.status == "ok"
    assert [call[0] for call in connection.calls] == ["add_memory"]
    assert connection.calls[0][1]["ari_context"] == {"transport_injected": True}
    assert connection.contexts == [context.model_copy(update={"selection_reason": "immutable-tool-ref"})]
