"""Real-process conformance tests for the generic stdio MCP adapter."""

from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from providers import (
    ProviderDriftError,
    ProviderLaunchError,
    ProviderProtocolError,
    PythonStdioLauncherV1,
    StdioMCPAdapter,
    provider_digest,
)
from sources import (
    CatalogSourceError,
    StdioCatalogSource,
    StdioSourceSpecV1,
    load_source_specs,
)

from conftest import callable_evidence


FIXTURES = Path(__file__).parent / "fixtures"


def _launcher(
    root: Path = FIXTURES,
    entrypoint: str = "stdio_server.py",
    *,
    architecture: str | None = None,
) -> PythonStdioLauncherV1:
    return PythonStdioLauncherV1(
        python_executable=str(Path(sys.executable).resolve()),
        package_root=str(root.resolve()),
        entrypoint=entrypoint,
        expected_architecture=(
            platform.machine() if architecture is None else architecture
        ),
    )


@pytest.mark.asyncio
async def test_stdio_adapter_initializes_paginates_and_calls_normal_error_large(
    monkeypatch,
):
    launcher = _launcher()
    adapter = StdioMCPAdapter(
        launcher,
        expected_provider_digest=provider_digest(launcher),
        timeout_seconds=10,
    )
    tools = await adapter.list_tools()
    assert [tool.name for tool in tools] == [
        "echo",
        "fail",
        "large",
        "env_probe",
        "submit",
        "job_status",
        "job_result",
        "job_cancel",
    ]

    normal = await adapter.invoke("echo", {"value": 3})
    assert normal.is_error is False
    assert normal.structured == {"status": "ok", "arguments": {"value": 3}}
    failed = await adapter.invoke("fail", {})
    assert failed.is_error is True
    assert "fixture provider failure" in failed.text
    large = await adapter.invoke("large", {})
    assert len(large.text) > 10_000

    monkeypatch.setenv("ARI_SECRET_MARKER", "must-not-cross-provider-boundary")
    environment = await adapter.invoke("env_probe", {})
    assert environment.structured is not None
    assert environment.structured["secret_marker"] is None
    assert environment.structured["user"] == "ari-provider"
    assert "ari-provider-home-" in environment.structured["home"]
    assert (
        Path(environment.structured["executable"]).resolve()
        == Path(sys.executable).resolve()
    )


@pytest.mark.asyncio
async def test_stdio_source_generates_candidates_without_leaf_config_files():
    launcher = _launcher()
    spec = StdioSourceSpecV1(
        source_id="fixture.stdio",
        provider_id="fixture.mcp",
        provider_version="1.0.0",
        provider_digest=provider_digest(launcher),
        launcher=launcher,
        evidence=callable_evidence(),
    )
    source = StdioCatalogSource(spec)
    candidates = await source.sync()
    assert len(candidates) == 8
    echo = next(
        item.descriptor for item in candidates if item.descriptor.name == "echo"
    )
    assert echo.source_ids == ["fixture.stdio"]
    assert echo.provider_digest == spec.provider_digest
    assert echo.capability_ref == "ari.federated.fixture.mcp.echo"
    assert echo.origin_chains[0][-1].kind == "tool"
    assert echo.semantics == {"operation": "identity"}
    assert echo.units == {"value": "1"}
    assert echo.limitations == ["fixture only"]
    assert echo.independence_group == "fixture-independent-method"


@pytest.mark.asyncio
async def test_provider_and_architecture_drift_fail_before_execution(tmp_path: Path):
    copied = tmp_path / "provider"
    copied.mkdir()
    shutil.copy2(FIXTURES / "stdio_server.py", copied / "server.py")
    launcher = _launcher(copied, "server.py")
    pinned = provider_digest(launcher)
    (copied / "server.py").write_text(
        (copied / "server.py").read_text() + "\n# drift\n",
        encoding="utf-8",
    )
    with pytest.raises(ProviderDriftError, match="provider digest drift"):
        await StdioMCPAdapter(
            launcher,
            expected_provider_digest=pinned,
            timeout_seconds=2,
        ).list_tools()


@pytest.mark.asyncio
async def test_provider_identity_covers_imported_modules_and_cannot_be_narrowed(
    tmp_path: Path,
):
    provider = tmp_path / "provider"
    provider.mkdir()
    (provider / "server.py").write_text("from helper import VALUE\n", encoding="utf-8")
    helper = provider / "helper.py"
    helper.write_text("VALUE = 1\n", encoding="utf-8")
    launcher = _launcher(provider, "server.py")
    before = provider_digest(launcher)
    helper.write_text("VALUE = 2\n", encoding="utf-8")
    assert provider_digest(launcher) != before

    with pytest.raises(ValidationError, match="cannot weaken"):
        PythonStdioLauncherV1(
            python_executable=str(Path(sys.executable).resolve()),
            package_root=str(provider.resolve()),
            entrypoint="server.py",
            identity_globs=["server.py"],
        )

    mismatched = _launcher(architecture="definitely-not-this-architecture")
    with pytest.raises(ProviderLaunchError, match="architecture mismatch"):
        await StdioMCPAdapter(
            mismatched,
            expected_provider_digest=provider_digest(mismatched),
            timeout_seconds=2,
        ).list_tools()


@pytest.mark.asyncio
async def test_malformed_stdout_has_bounded_stderr_diagnostic():
    launcher = _launcher(entrypoint="malformed_server.py")
    adapter = StdioMCPAdapter(
        launcher,
        expected_provider_digest=provider_digest(launcher),
        timeout_seconds=2,
    )
    with pytest.raises(ProviderProtocolError) as exc_info:
        await adapter.list_tools()
    message = str(exc_info.value)
    assert "fixture-malformed-diagnostic" in message
    assert len(message) < 3_000


def test_launcher_rejects_shell_and_embedded_credentials():
    with pytest.raises(ValidationError, match="command_kind=python"):
        PythonStdioLauncherV1(
            command_kind="shell",
            python_executable=str(Path(sys.executable).resolve()),
            package_root=str(FIXTURES.resolve()),
            entrypoint="stdio_server.py",
        )
    with pytest.raises(ValidationError, match="cannot be embedded"):
        PythonStdioLauncherV1(
            python_executable=str(Path(sys.executable).resolve()),
            package_root=str(FIXTURES.resolve()),
            entrypoint="stdio_server.py",
            literal_env={"PROVIDER_API_KEY": "not-allowed"},
        )


def test_sources_yaml_cannot_select_static_fixture_source(tmp_path: Path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "ari.catalog-sources/v1",
                "sources": [
                    {
                        "source_id": "fixture.static",
                        "kind": "fixture",
                        "provider_id": "fixture.provider",
                        "provider_version": "1.0.0",
                        "provider_digest": "sha256:" + "0" * 64,
                        "launcher": _launcher().model_dump(mode="json"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CatalogSourceError, match="stdio-mcp"):
        load_source_specs(path)
