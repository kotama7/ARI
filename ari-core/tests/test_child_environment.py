"""Minimal MCP child environment and credential-scope security tests."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ari.config import SkillConfig
from ari.mcp.child_environment import (
    CredentialScopeDriftError,
    ManagedEnvironmentOverrideError,
    MissingRequiredEnvironmentError,
    SecretRedactor,
    UnclassifiedCredentialError,
    build_child_environment,
)
from ari.mcp.client import MCPClient
from ari.mcp.connection import SkillConnection
from ari.mcp.invoke_runtime import invoke_with_retries
from ari.result import ResultEnvelopeNormalizer, ToolCallContextV1, utc_now_iso


FIXTURE_SERVER = Path(__file__).parent / "fixtures" / "mcp_env_server.py"
ECHO_SERVER = Path(__file__).parent / "fixtures" / "stdio_env_echo.py"


def _skill(**updates) -> SkillConfig:
    values = {
        "name": "environment-fixture",
        "package": "ari-skill-environment-fixture",
        "version": "1.0.0",
        "path": str(FIXTURE_SERVER.parents[1]),
        "entrypoint": str(FIXTURE_SERVER.relative_to(FIXTURE_SERVER.parents[1])),
        "phase": "bfts",
        "manifest_digest": "a" * 64,
        "environment_policy": "complete",
        "optional_env": ["FIXTURE_ALLOWED"],
        "credential_scopes": {
            "fixture.secret": {
                "required_env": [],
                "optional_env": ["FIXTURE_SECRET"],
            }
        },
        "tool_capabilities": {
            "inspect_environment": "ari.fixture.environment.inspect"
        },
        "tool_policies": {
            "inspect_environment": {
                "phases": ["bfts"],
                "side_effects": "read-only",
                "determinism": "deterministic",
                "timeout_class": "bounded",
                "permissions": [],
                "result_schema": "ari.result-envelope/v1",
            }
        },
    }
    values.update(updates)
    return SkillConfig(**values)


def test_builder_does_not_mutate_or_copy_parent_environment(tmp_path: Path):
    parent = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/parent/home",
        "ARI_CHECKPOINT_DIR": str(tmp_path),
        "FIXTURE_ALLOWED": "visible",
        "FIXTURE_SECRET": "secret-marker",
        "FIXTURE_UNDECLARED": "must-not-cross",
    }
    original = dict(parent)

    child = build_child_environment(
        _skill(),
        skill_path=FIXTURE_SERVER.parents[1],
        ari_core_root=Path(__file__).parents[1],
        parent_env=parent,
    )

    assert parent == original
    assert child.values["FIXTURE_ALLOWED"] == "visible"
    assert child.values["FIXTURE_SECRET"] == "secret-marker"
    assert "FIXTURE_UNDECLARED" not in child.values
    assert child.values["HOME"] != parent["HOME"]
    assert Path(child.values["HOME"]).is_relative_to(tmp_path)
    assert child.credential_env_names == ("FIXTURE_SECRET",)
    assert child.active_credential_scope_ids == ("fixture.secret",)
    assert "secret-marker" not in json.dumps(child.credential_scope_identities)
    assert "FIXTURE_SECRET" not in child.transport_values()


def test_complete_policy_fails_closed_for_invalid_declarations(tmp_path: Path):
    base = {
        "PATH": "/bin",
        "ARI_CHECKPOINT_DIR": str(tmp_path),
        "FIXTURE_TOKEN": "value",
    }
    kwargs = {
        "skill_path": FIXTURE_SERVER.parents[1],
        "ari_core_root": Path(__file__).parents[1],
        "parent_env": base,
    }
    with pytest.raises(UnclassifiedCredentialError, match="classify"):
        build_child_environment(
            _skill(optional_env=["FIXTURE_TOKEN"], credential_scopes={}),
            **kwargs,
        )
    with pytest.raises(MissingRequiredEnvironmentError, match="FIXTURE_REQUIRED"):
        build_child_environment(
            _skill(required_env=["FIXTURE_REQUIRED"]),
            **kwargs,
        )
    with pytest.raises(ManagedEnvironmentOverrideError, match="HOME"):
        build_child_environment(_skill(optional_env=["HOME"]), **kwargs)


def test_redactor_covers_raw_and_json_escaped_credential_values():
    secret = "first-line\nsecond-line"
    redactor = SecretRedactor({secret: "<redacted:fixture.secret>"})

    assert secret not in redactor.text(f"raw={secret}")
    serialized = json.dumps({"credential": secret})
    redacted = redactor.text(serialized)
    assert "first-line\\nsecond-line" not in redacted
    assert "<redacted:fixture.secret>" in redacted


def test_real_mcp_child_redacts_secret_and_records_value_free_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
):
    secret = "ari-fixture-secret-984317"
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("FIXTURE_ALLOWED", "visible")
    monkeypatch.setenv("FIXTURE_SECRET", secret)
    monkeypatch.setenv("FIXTURE_UNDECLARED", "must-not-cross")
    monkeypatch.setenv("HOME", "/parent/home-that-must-not-cross")

    lock_path = tmp_path / "SKILLS.lock"
    client = MCPClient([_skill()], skill_lock_path=lock_path)
    tools = client.list_tools(phase="bfts")
    assert [tool["name"] for tool in tools] == ["inspect_environment"]

    envelope = client.call_tool_envelope(
        tools[0]["tool_ref"],
        {
            "names": [
                "FIXTURE_ALLOWED",
                "FIXTURE_SECRET",
                "FIXTURE_UNDECLARED",
                "HOME",
            ]
        },
        context=ToolCallContextV1(run_id="fixture-run", phase="bfts"),
    )
    mcp_config, allowed = client.to_claude_mcp_config(phase="bfts")
    client.close_all()

    serialized = envelope.model_dump_json()
    assert envelope.status == "ok"
    assert envelope.provenance.credential_scope_ids == ["fixture.secret"]
    assert secret not in serialized
    assert "<redacted:fixture.secret>" in serialized
    assert "must-not-cross" not in serialized
    assert "/parent/home-that-must-not-cross" not in serialized

    lock_text = lock_path.read_text(encoding="utf-8")
    assert secret not in lock_text
    assert '"scope_id": "fixture.secret"' in lock_text
    locked = json.loads(lock_text)
    assert locked["skills"][0]["credential_scopes"][0]["present_env"] == [
        "FIXTURE_SECRET"
    ]

    config_text = json.dumps(mcp_config, sort_keys=True)
    assert secret not in config_text
    server = mcp_config["mcpServers"]["environment-fixture"]
    assert server["args"][:2] == ["-m", "ari.mcp.secure_stdio_proxy"]
    proxy_spec = json.loads(server["args"][3])
    assert proxy_spec["command"]
    assert proxy_spec["credential_markers"] == {
        "FIXTURE_SECRET": "fixture.secret"
    }
    assert server["_ariCredentialEnv"] == ["FIXTURE_SECRET"]
    assert "FIXTURE_SECRET" not in server["env"]
    assert allowed == ["mcp__environment-fixture__inspect_environment"]

    captured = capfd.readouterr()
    assert secret not in captured.err
    assert "<redacted:fixture.secret>" in captured.err


def test_secure_stdio_proxy_filters_merged_parent_env_and_both_outputs():
    secret = "proxy-secret-573912"
    spec = json.dumps(
        {
            "command": sys.executable,
            "args": [str(ECHO_SERVER)],
            "env_names": [
                "FIXTURE_ALLOWED",
                "FIXTURE_SECRET",
                "PATH",
                "PYTHONPATH",
            ],
            "credential_markers": {"FIXTURE_SECRET": "fixture.secret"},
        },
        sort_keys=True,
    )
    environment = dict(os.environ)
    environment.update(
        {
            "FIXTURE_ALLOWED": "visible",
            "FIXTURE_SECRET": secret,
            "FIXTURE_UNDECLARED": "must-not-cross",
            "PYTHONPATH": str(Path(__file__).parents[1]),
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "ari.mcp.secure_stdio_proxy",
            "--spec",
            spec,
        ],
        input="inspect\n",
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
        check=True,
    )

    assert secret not in completed.stdout
    assert secret not in completed.stderr
    assert "must-not-cross" not in completed.stdout
    assert '"undeclared": null' in completed.stdout
    assert "<redacted:fixture.secret>" in completed.stdout
    assert "<redacted:fixture.secret>" in completed.stderr


def test_reconnect_refuses_credential_authority_drift(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("FIXTURE_SECRET", "initial-secret")
    skill = _skill()
    first = SkillConnection(skill)
    first._server_params()
    assert skill.credential_scope_identities[0]["present_env"] == ["FIXTURE_SECRET"]

    monkeypatch.delenv("FIXTURE_SECRET")
    with pytest.raises(CredentialScopeDriftError, match="authority changed"):
        SkillConnection(skill)._server_params()


def test_invoke_reports_reconnect_environment_drift_as_nonretryable_admission():
    class DroppedConnection:
        def call_tool(self, tool_name: str, args: dict, timeout: int) -> dict:
            raise OSError("connection dropped")

        def redact_text(self, value: str) -> str:
            return value

    class DriftedConnection(DroppedConnection):
        def call_tool(self, tool_name: str, args: dict, timeout: int) -> dict:
            raise CredentialScopeDriftError("credential authority changed")

    envelope = invoke_with_retries(
        connection=DroppedConnection(),
        reconnect=lambda _connection: DriftedConnection(),
        tool_name="inspect_environment",
        tool_ref="ari-skill-fixture/inspect@sha256:" + "a" * 64,
        args={},
        timeout=1,
        context=ToolCallContextV1(run_id="fixture-run"),
        normalizer=ResultEnvelopeNormalizer(),
        started_at=utc_now_iso(),
        logger=logging.getLogger(__name__),
    )

    assert envelope.status == "error"
    assert envelope.error is not None
    assert envelope.error.kind == "admission"
    assert envelope.error.retryable is False
    assert "authority changed" in envelope.error.message
