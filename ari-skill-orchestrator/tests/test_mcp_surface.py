from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

import server
from ari_skill_orchestrator.auth import HashedTokenVerifier


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "get_ear",
    "get_paper",
    "get_result",
    "get_status",
    "get_workflow",
    "list_artifacts",
    "list_children",
    "list_runs",
    "list_skills",
    "read_artifact",
    "run_experiment",
    "stop_experiment",
}


def test_runtime_manifest_and_compat_metadata_match() -> None:
    runtime = {tool.name for tool in server.mcp._tool_manager.list_tools()}
    manifest = yaml.safe_load((ROOT / "skill.yaml").read_text())
    declared = {tool["name"] for tool in manifest["tools"]}
    compatibility = set(json.loads((ROOT / "mcp.json").read_text())["tools"])
    assert runtime == declared == compatibility == EXPECTED


def test_secret_argument_and_legacy_file_tools_are_deleted() -> None:
    signature = inspect.signature(server.run_experiment)
    assert "llm_api_key" not in signature.parameters
    assert "llm_base_url" not in signature.parameters
    assert "read_file" not in EXPECTED
    assert "list_files" not in EXPECTED
    source = (ROOT / "src" / "server.py").read_text()
    assert "BaseHTTPRequestHandler" not in source
    assert "ThreadingHTTPServer" not in source
    assert "Access-Control-Allow-Origin" not in source


def test_streamable_http_refuses_unauthenticated_start(monkeypatch) -> None:
    monkeypatch.delenv("ARI_ORCHESTRATOR_HTTP_TOKENS_FILE", raising=False)
    monkeypatch.setattr("sys.argv", ["server.py", "--transport", "streamable-http"])
    with pytest.raises(SystemExit) as error:
        server.main()
    assert error.value.code == 2


def test_network_configuration_and_context_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("ARI_ORCHESTRATOR_HTTP_PORT", "0")
    with pytest.raises(PermissionError, match="between 1 and 65535"):
        server._make_mcp()
    monkeypatch.setenv("ARI_ORCHESTRATOR_HTTP_PORT", "9890")
    monkeypatch.setattr(server, "_network_auth_required", True)
    with pytest.raises(PermissionError, match="bearer context"):
        server._principal()


def test_hashed_token_verifier_and_roles(tmp_path: Path) -> None:
    token = "test-bearer-value"
    document = {
        "schema_version": "ari.orchestrator-token-digests/v1",
        "tokens": [
            {
                "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                "principal_id": "http-user",
                "roles": ["reader"],
            }
        ],
    }
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps(document))
    path.chmod(0o600)
    verifier = HashedTokenVerifier(path)
    accepted = asyncio.run(verifier.verify_token(token))
    rejected = asyncio.run(verifier.verify_token("wrong"))
    assert accepted is not None
    assert accepted.client_id == "http-user"
    assert accepted.scopes == ["role:reader"]
    assert rejected is None


def test_token_file_permissions_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "tokens.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "ari.orchestrator-token-digests/v1",
                "tokens": [
                    {
                        "token_sha256": "a" * 64,
                        "principal_id": "user",
                        "roles": [],
                    }
                ],
            }
        )
    )
    path.chmod(0o644)
    with pytest.raises(PermissionError, match="0600"):
        HashedTokenVerifier(path)


def test_token_file_shape_and_symlink_fail_closed(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text(
        json.dumps(
            {
                "schema_version": "ari.orchestrator-token-digests/v1",
                "tokens": [
                    {
                        "token_sha256": "a" * 64,
                        "principal_id": "user",
                        "roles": "admin",
                    }
                ],
            }
        )
    )
    malformed.chmod(0o600)
    with pytest.raises(PermissionError, match="roles"):
        HashedTokenVerifier(malformed)

    symbolic = tmp_path / "symbolic.json"
    symbolic.symlink_to(malformed)
    with pytest.raises(PermissionError, match="invalid"):
        HashedTokenVerifier(symbolic)


def test_authenticated_streamable_http_uses_same_service_contract(
    tmp_path: Path,
) -> None:
    import httpx

    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    token = "http-integration-token"
    token_file = tmp_path / "tokens.json"
    token_file.write_text(
        json.dumps(
            {
                "schema_version": "ari.orchestrator-token-digests/v1",
                "tokens": [
                    {
                        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                        "principal_id": "http-integration-user",
                        "roles": [],
                    }
                ],
            }
        )
    )
    token_file.chmod(0o600)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = os.environ.copy()
    environment.update(
        {
            "ARI_ORCHESTRATOR_HTTP_TOKENS_FILE": str(token_file),
            "ARI_ORCHESTRATOR_HTTP_PORT": str(port),
            "ARI_ORCHESTRATOR_LOGS": str(tmp_path / "logs"),
            "ARI_ORCHESTRATOR_DRY_RUN": "1",
            "ARI_WORKSPACE": str(ROOT.parent),
            "PYTHONPATH": os.pathsep.join(
                [str(ROOT / "src"), str(ROOT.parent / "ari-core")]
            ),
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "src" / "server.py"),
            "--transport",
            "streamable-http",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(
                    process.stderr.read() if process.stderr else "server exited"
                )
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("streamable HTTP server did not start")

        async def round_trip() -> None:
            async with httpx.AsyncClient(
                headers={"Authorization": f"Bearer {token}"}
            ) as http_client:
                async with streamable_http_client(
                    f"http://127.0.0.1:{port}/mcp",
                    http_client=http_client,
                ) as (read_stream, write_stream, _session_id):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        assert {tool.name for tool in tools.tools} == EXPECTED
                        started = await session.call_tool(
                            "run_experiment",
                            {
                                "experiment_md": "# HTTP parity\nscience",
                                "idempotency_key": "http-parity-1",
                            },
                        )
                        assert started.isError is not True
                        handle = started.structuredContent
                        assert handle is not None
                        assert handle["state"] == "succeeded"
                        status = await session.call_tool(
                            "get_status", {"run_id": handle["run_id"]}
                        )
                        assert (
                            status.structuredContent["request_digest"]
                            == handle["request_digest"]
                        )
                        assert (
                            status.structuredContent["principal_id"]
                            == "http-integration-user"
                        )

        asyncio.run(round_trip())
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_stdio_transport_uses_same_service_contract(tmp_path: Path) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    environment = {
        "ARI_ORCHESTRATOR_LOGS": str(tmp_path / "logs"),
        "ARI_ORCHESTRATOR_DRY_RUN": "1",
        "ARI_ORCHESTRATOR_PRINCIPAL_ID": "stdio-integration-user",
        "ARI_WORKSPACE": str(ROOT.parent),
        "PYTHONPATH": os.pathsep.join(
            [str(ROOT / "src"), str(ROOT.parent / "ari-core")]
        ),
    }

    async def round_trip() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(ROOT / "src" / "server.py")],
            env=environment,
            cwd=str(ROOT.parent),
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                started = await session.call_tool(
                    "run_experiment",
                    {
                        "experiment_md": "# stdio parity\nscience",
                        "idempotency_key": "stdio-parity-1",
                    },
                )
                assert started.isError is not True
                handle = started.structuredContent
                assert handle["schema_version"] == "ari.orchestrator-run-handle/v1"
                assert handle["principal_id"] == "stdio-integration-user"
                status = await session.call_tool(
                    "get_status", {"run_id": handle["run_id"]}
                )
                assert status.structuredContent["state"] == "succeeded"
                assert (
                    status.structuredContent["request_digest"]
                    == handle["request_digest"]
                )

    asyncio.run(round_trip())
