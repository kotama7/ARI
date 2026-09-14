"""Provider-neutral async handle dispatch and polling tests."""

from __future__ import annotations

import json

from ari.config import SkillConfig
from ari.mcp.client import MCPClient


class _AsyncConnection:
    def __init__(self, skill: SkillConfig, statuses: list[str] | None = None):
        self.skill = skill
        self.statuses = list(statuses or ["RUNNING", "COMPLETED"])
        self.calls: list[tuple[str, dict, int]] = []

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": name,
                "description": name,
                "inputSchema": {"type": "object", "properties": {}},
                "skill_name": self.skill.name,
            }
            for name in ("submit", "status", "result", "cancel")
        ]

    def call_tool(self, name: str, args: dict, timeout: int) -> dict:
        self.calls.append((name, args, timeout))
        if name == "submit":
            payload = {"job_id": "job-17", "status": "submitted"}
        elif name == "status":
            state = self.statuses.pop(0) if self.statuses else "COMPLETED"
            payload = {"job_id": args["job_id"], "status": state}
        elif name == "result":
            payload = {"job_id": args["job_id"], "metric": 0.91}
        else:
            payload = {"job_id": args["job_id"], "cancelled": True}
        return {"result": json.dumps(payload)}

    def close(self) -> None:
        pass


def _skill() -> SkillConfig:
    capabilities = {
        "submit": "ari.fixture.job.submit",
        "status": "ari.fixture.job.status",
        "result": "ari.fixture.job.result",
        "cancel": "ari.fixture.job.cancel",
    }
    lifecycle = {
        "handle_field": "job_id",
        "state_field": "status",
        "status": {
            "capability_ref": capabilities["status"],
            "handle_argument": "job_id",
        },
        "result": {
            "capability_ref": capabilities["result"],
            "handle_argument": "job_id",
        },
        "cancel": {
            "capability_ref": capabilities["cancel"],
            "handle_argument": "job_id",
        },
        "states": {
            "submitted_states": ["submitted", "PENDING"],
            "running_states": ["RUNNING"],
            "succeeded_states": ["COMPLETED"],
            "failed_states": ["FAILED"],
            "cancelled_states": ["CANCELLED"],
        },
        "poll_interval_seconds": 0.01,
        "max_wait_seconds": 10,
    }
    base_policy = {
        "phases": ["all"],
        "side_effects": "read-only",
        "determinism": "live-data",
        "timeout_class": "bounded",
        "timeout_budget": None,
        "async_lifecycle": None,
        "permissions": [],
        "context_requirement": "none",
        "result_schema": "ari.result-envelope/v1",
    }
    policies = {name: dict(base_policy) for name in capabilities}
    policies["submit"] = {
        **base_policy,
        "timeout_class": "async",
        "async_lifecycle": lifecycle,
    }
    return SkillConfig(
        name="async-fixture",
        package="ari-skill-async-fixture",
        version="1.0.0",
        path="/tmp/async-fixture",
        tool_capabilities=capabilities,
        tool_policies=policies,
        tool_timeout_classes={
            name: str(policy["timeout_class"]) for name, policy in policies.items()
        },
    )


def _client(monkeypatch, statuses: list[str] | None = None):
    skill = _skill()
    connection = _AsyncConnection(skill, statuses)
    client = MCPClient([skill])
    monkeypatch.setattr(client, "_init_connection", lambda _skill: connection)
    return client, connection


def test_submission_returns_portable_immutable_handle(monkeypatch):
    client, _ = _client(monkeypatch)
    envelope = client.call_tool_envelope("submit", {"payload": "x"})

    assert envelope.status == "submitted"
    handle = envelope.async_handle
    assert handle is not None
    assert handle.handle_id == "job-17"
    assert handle.schema_version == "ari.async-tool-handle/v1"
    assert client._tool_name_by_ref[handle.status.tool_ref] == "status"
    assert client._tool_name_by_ref[handle.result.tool_ref] == "result"
    assert client._tool_name_by_ref[handle.cancel.tool_ref] == "cancel"
    assert handle == handle.model_validate_json(handle.model_dump_json())


def test_wait_polls_and_fetches_result(monkeypatch):
    client, connection = _client(monkeypatch, ["RUNNING", "COMPLETED"])
    submitted = client.call_tool_envelope("submit", {})
    result = client.wait_for_async(submitted.async_handle, timeout_seconds=1)

    assert result.status == "ok"
    assert result.structured_content["metric"] == 0.91
    assert [call[0] for call in connection.calls] == [
        "submit",
        "status",
        "status",
        "result",
    ]
    assert all(
        args.get("job_id") == "job-17"
        for name, args, _timeout in connection.calls
        if name != "submit"
    )


def test_cancel_uses_declared_capability(monkeypatch):
    client, connection = _client(monkeypatch)
    submitted = client.call_tool_envelope("submit", {})
    cancelled = client.cancel_async(submitted.async_handle)

    assert cancelled.status == "cancelled"
    assert connection.calls[-1][0:2] == ("cancel", {"job_id": "job-17"})


def test_unknown_provider_state_fails_closed(monkeypatch):
    client, _ = _client(monkeypatch, ["MYSTERY"])
    submitted = client.call_tool_envelope("submit", {})
    status = client.get_async_status(submitted.async_handle)

    assert status.status == "error"
    assert status.error is not None
    assert status.error.kind == "protocol"
    assert status.error.retryable is True


def test_missing_declared_handle_is_protocol_error(monkeypatch):
    client, connection = _client(monkeypatch)
    original = connection.call_tool

    def _without_handle(name: str, args: dict, timeout: int) -> dict:
        if name == "submit":
            return {"result": json.dumps({"status": "submitted"})}
        return original(name, args, timeout)

    monkeypatch.setattr(connection, "call_tool", _without_handle)
    envelope = client.call_tool_envelope("submit", {})
    assert envelope.status == "error"
    assert envelope.error is not None
    assert envelope.error.kind == "protocol"


def test_wait_timeout_can_cancel(monkeypatch):
    client, connection = _client(monkeypatch, ["RUNNING"] * 20)
    submitted = client.call_tool_envelope("submit", {})
    result = client.wait_for_async(
        submitted.async_handle,
        timeout_seconds=0,
        cancel_on_timeout=True,
    )

    assert result.status == "error"
    assert result.error is not None and result.error.kind == "timeout"
    assert connection.calls[-1][0] == "cancel"
