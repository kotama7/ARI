"""Conformance tests for the fixed registry-facing MCP surface."""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

import pytest

from providers import PythonStdioLauncherV1, StdioMCPAdapter, provider_digest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_OPERATIONS = [
    "discover",
    "describe",
    "invoke",
    "get_status",
    "get_result",
]


def _registry_launcher() -> PythonStdioLauncherV1:
    return PythonStdioLauncherV1(
        python_executable=str(Path(sys.executable).resolve()),
        package_root=str(PACKAGE_ROOT.resolve()),
        entrypoint="src/server.py",
        expected_architecture=platform.machine(),
    )


@pytest.mark.asyncio
async def test_real_registry_server_exposes_exactly_five_broker_operations():
    launcher = _registry_launcher()
    adapter = StdioMCPAdapter(
        launcher,
        expected_provider_digest=provider_digest(launcher),
        timeout_seconds=10,
    )

    tools = await adapter.list_tools()

    assert [tool.name for tool in tools] == PUBLIC_OPERATIONS
    assert all("ari-tool://" not in json.dumps(tool.input_schema) for tool in tools)
    assert all(
        "provider_tool_name" not in json.dumps(tool.input_schema) for tool in tools
    )


@pytest.mark.asyncio
async def test_real_registry_server_discovers_from_frozen_default_lock():
    launcher = _registry_launcher()
    adapter = StdioMCPAdapter(
        launcher,
        expected_provider_digest=provider_digest(launcher),
        timeout_seconds=10,
    )

    response = await adapter.invoke("discover", {"query": "quantum", "top_k": 5})
    document = json.loads(response.text)

    assert response.is_error is False
    assert document["schema_version"] == "ari.discovery-result/v1"
    assert document["results"] == []
    assert document["catalog_digest"].startswith("sha256:")
