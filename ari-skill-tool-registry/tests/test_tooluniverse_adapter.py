"""ToolUniverse collection expansion, policy, runtime, and replay tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from broker import CatalogBroker
from catalog import build_catalog, catalog_diff, write_reviewable_catalog
from models import AdmissionEvidenceV1, sha256_digest
from providers import (
    ProviderProtocolError,
    ProviderResponseV1,
    ProviderToolV1,
    PythonStdioLauncherV1,
    StaticProviderAdapter,
    provider_digest,
)
from sources import (
    StdioCatalogSource,
    StdioSourceSpecV1,
    ToolUniverseCatalogSource,
    ToolUniverseCategoryProfileV1,
    ToolUniversePinV1,
    ToolUniverseSourceSpecV1,
)
from storage import CassetteStore, RegistryArtifactStore
from tooluniverse_adapter import ToolUniverseCompactAdapter


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
SUPPORT = PACKAGE_ROOT / "providers" / "tooluniverse-support-v1.json"


def _pin() -> ToolUniversePinV1:
    document = json.loads(SUPPORT.read_text(encoding="utf-8"))
    return ToolUniversePinV1.model_validate(document["releases"][0])


def _launcher() -> PythonStdioLauncherV1:
    return PythonStdioLauncherV1(
        python_executable=str(Path(sys.executable).resolve()),
        package_root=str(FIXTURES.resolve()),
        python_module="tooluniverse.smcp_server",
        python_callable="run_stdio_server",
        identity_globs=[
            "**/*",
            "**/*.py",
            "*.lock",
            "pyproject.toml",
            "requirements*.txt",
        ],
    )


def _source_spec(
    *,
    profiles: list[ToolUniverseCategoryProfileV1] | None = None,
) -> ToolUniverseSourceSpecV1:
    launcher = _launcher()
    values: dict[str, Any] = {
        "source_id": "tooluniverse.fixture",
        "provider_digest": "sha256:" + "0" * 64,
        "launcher": launcher,
        "support_release": _pin().version,
        "profiles": profiles
        or [
            ToolUniverseCategoryProfileV1(
                profile_id="read-only-data",
                categories=["safe_data"],
                side_effects="read-only",
                determinism="live-data",
                permissions=["network"],
                limitations=["fixture data only"],
                backend_lineage=["fixture-api"],
            )
        ],
        "evidence": AdmissionEvidenceV1(
            protocol_conformance=True,
            provider_pinned=True,
            launcher_verified=True,
            dependencies_pinned=True,
            limitations_documented=True,
            architecture="ToolUniverse compact MCP fixture",
        ),
        "timeout_seconds": 15,
        "page_size": 100,
        "info_batch_size": 40,
    }
    provisional = ToolUniverseSourceSpecV1.model_validate(values)
    values["provider_digest"] = provider_digest(provisional.effective_launcher)
    return ToolUniverseSourceSpecV1.model_validate(values)


def _leaf(index: int, **updates: Any) -> dict[str, Any]:
    value = {
        "name": f"TU_bulk_{index:04d}",
        "type": "BaseRESTTool",
        "category": "safe_data",
        "source_file": "data/bulk.json",
        "description": f"Bulk leaf {index}",
        "parameter": {
            "type": "object",
            "properties": {
                "value": {"type": "integer"},
                "scale": {"type": "number", "default": 1.0},
            },
            "required": ["value"],
            "additionalProperties": False,
        },
        "return_schema": {"type": "object"},
    }
    value.update(updates)
    return value


class CompactTransport:
    def __init__(self, leaves: list[dict[str, Any]]) -> None:
        self.leaves = {leaf["name"]: leaf for leaf in leaves}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self):
        raise AssertionError("collection adapter must use compact invocation")

    async def invoke(self, name: str, arguments: dict[str, Any]):
        self.calls.append((name, dict(arguments)))
        if name == "list_tools":
            values = list(self.leaves.values())
            offset = arguments["offset"]
            limit = arguments["limit"]
            fields = arguments["fields"]
            page = values[offset : offset + limit]
            next_offset = offset + len(page)
            payload = {
                "total_tools": len(values),
                "offset": offset,
                "limit": limit,
                "has_more": next_offset < len(values),
                "next_offset": next_offset if next_offset < len(values) else None,
                "tools": [
                    {field: leaf[field] for field in fields if field in leaf}
                    for leaf in page
                ],
            }
        elif name == "get_tool_info":
            names = arguments["tool_names"]
            payload = {
                "total_requested": len(names),
                "total_found": len(names),
                "tools": [self.leaves[item] for item in names],
            }
        elif name == "execute_tool":
            leaf_name = arguments["tool_name"]
            if leaf_name == "TU_auth_failure":
                payload = {
                    "status": "error",
                    "error": "Unauthorized: invalid API key",
                    "error_type": "AuthenticationError",
                }
            else:
                leaf_arguments = arguments["arguments"]
                payload = {
                    "status": "ok",
                    "value": leaf_arguments.get("value", 0)
                    * leaf_arguments.get("scale", 1.0),
                }
        else:
            raise AssertionError(name)
        return ProviderResponseV1(
            text=json.dumps(payload, sort_keys=True), structured=payload
        )

    async def get_status(self, lifecycle, provider_handle):
        raise AssertionError("not asynchronous")

    async def get_result(self, lifecycle, provider_handle):
        raise AssertionError("not asynchronous")

    async def cancel(self, lifecycle, provider_handle):
        raise AssertionError("not asynchronous")


def _adapter(
    spec: ToolUniverseSourceSpecV1,
    transport: CompactTransport,
    *,
    allowed: set[str] | None = None,
) -> ToolUniverseCompactAdapter:
    return ToolUniverseCompactAdapter(
        spec.effective_launcher,
        expected_provider_digest=spec.provider_digest,
        pin=spec.pin.model_dump(mode="json"),
        include_categories=spec.include_categories,
        exclude_categories=spec.exclude_categories,
        allowed_leaf_names=allowed,
        leaf_spec_digests=(
            {name: sha256_digest(transport.leaves[name]) for name in allowed}
            if allowed is not None
            else None
        ),
        timeout_seconds=spec.timeout_seconds,
        page_size=spec.page_size,
        info_batch_size=spec.info_batch_size,
        max_pages=spec.max_pages,
        max_tools=spec.max_tools,
        transport=transport,
        verify_package=False,
    )


def test_production_adapter_rejects_package_tree_masquerading_as_reviewed_wheel():
    spec = _source_spec()
    with pytest.raises(ProviderProtocolError, match="package_root must be"):
        ToolUniverseCompactAdapter(
            spec.effective_launcher,
            expected_provider_digest=spec.provider_digest,
            pin=spec.pin.model_dump(mode="json"),
        )


@pytest.mark.asyncio
async def test_one_compact_adapter_expands_one_thousand_leaves_without_leaf_code():
    spec = _source_spec()
    transport = CompactTransport([_leaf(index) for index in range(1_000)])
    adapter = _adapter(spec, transport)

    tools = await adapter.list_tools()

    assert len(tools) == 1_000
    assert tools[0].annotations["ari_tooluniverse"]["category"] == "safe_data"
    list_calls = [call for call in transport.calls if call[0] == "list_tools"]
    info_calls = [call for call in transport.calls if call[0] == "get_tool_info"]
    assert len(list_calls) == 10
    assert len(info_calls) == 25
    assert all(len(call[1]["tool_names"]) <= 40 for call in info_calls)


@pytest.mark.asyncio
async def test_pinned_property_required_dialect_is_normalized_without_type_coercion():
    spec = _source_spec()
    leaf = _leaf(1)
    leaf["parameter"] = {
        "type": "object",
        "properties": {
            "value": {"type": "integer", "required": True},
            "scale": {"type": "number", "required": False, "default": 1.0},
        },
    }
    adapter = _adapter(spec, CompactTransport([leaf]))

    tool = (await adapter.list_tools())[0]

    assert tool.input_schema["required"] == ["value"]
    assert "required" not in tool.input_schema["properties"]["value"]
    assert tool.input_schema["properties"]["value"]["type"] == "integer"
    assert tool.annotations["ari_tooluniverse"]["schema_normalizations"]


@pytest.mark.asyncio
async def test_collection_profiles_quarantine_dynamic_unreviewed_and_auth_leaves():
    spec = _source_spec()
    leaves = [
        _leaf(1),
        _leaf(
            2,
            name="TU_dynamic",
            type="MCPAutoLoaderTool",
            category="mcp_auto_loader_remote",
        ),
        _leaf(3, name="TU_unreviewed", category="other"),
        _leaf(4, name="TU_needs_key", required_api_keys=["EXAMPLE_API_KEY"]),
        _leaf(
            5,
            name="TU_invalid_schema",
            parameter={
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": True,
            },
        ),
    ]
    adapter = _adapter(spec, CompactTransport(leaves))
    result = await build_catalog(
        [ToolUniverseCatalogSource(spec, adapter=adapter, verify_source=False)]
    )

    assert [tool.name for tool in result.lock.tools] == ["TU_bulk_0001"]
    assert {item.reason_code for item in result.lock.quarantined} == {
        "policy-excluded",
        "schema-drift",
        "unsupported-profile",
    }
    descriptor = result.lock.tools[0]
    assert descriptor.origin_chains[0][1].kind == "collection"
    assert (
        descriptor.origin_chains[0][-1].digest
        == descriptor.annotations["ari_tooluniverse"]["tool_spec_digest"]
    )
    assert result.lock.admissions[0].level == "callable"
    assert "not leaf scientific validation" in " ".join(descriptor.limitations)


@pytest.mark.asyncio
async def test_locked_runtime_is_strict_records_provenance_and_replays_offline(
    tmp_path: Path,
):
    spec = _source_spec()
    leaves = [_leaf(1), _leaf(2, name="TU_auth_failure")]
    sync_transport = CompactTransport(leaves)
    sync_adapter = _adapter(spec, sync_transport)
    result = await build_catalog(
        [ToolUniverseCatalogSource(spec, adapter=sync_adapter, verify_source=False)]
    )
    by_name = {tool.name: tool for tool in result.lock.tools}
    runtime_transport = CompactTransport(leaves)
    runtime_adapter = _adapter(
        spec,
        runtime_transport,
        allowed=set(by_name),
    )
    artifacts = RegistryArtifactStore(tmp_path / "artifacts")
    cassettes = CassetteStore(tmp_path / "cassettes", artifact_store=artifacts)
    broker = CatalogBroker(
        result.lock,
        index=result.index,
        adapters={spec.source_id: runtime_adapter},
        artifact_store=artifacts,
        cassette_store=cassettes,
    )

    descriptor = by_name["TU_bulk_0001"]
    wrong_type = await broker.invoke(descriptor.tool_ref, {"value": "3"}, mode="record")
    assert wrong_type["status"] == "error"
    unknown = await broker.invoke(
        descriptor.tool_ref, {"value": 3, "extra": 1}, mode="record"
    )
    assert unknown["status"] == "error"
    null_value = await broker.invoke(
        descriptor.tool_ref, {"value": 3, "scale": None}, mode="live"
    )
    assert null_value["status"] == "error"

    recorded = await broker.invoke(descriptor.tool_ref, {"value": 3}, mode="record")
    assert recorded["status"] == "ok"
    provenance = recorded["structured_content"]["_ari_collection_provenance"]
    assert provenance["collection_version"] == "1.3.1"
    assert provenance["upstream_cache"] == "disabled"
    assert provenance["leaf_spec_digest"].startswith("sha256:")
    assert runtime_transport.calls[-1] == (
        "execute_tool",
        {
            "tool_name": "TU_bulk_0001",
            "arguments": {"scale": 1.0, "value": 3},
        },
    )

    class OfflineAdapter:
        async def invoke(self, name, arguments):
            raise AssertionError("offline replay must not start ToolUniverse")

    replay_broker = CatalogBroker(
        result.lock,
        index=result.index,
        adapters={spec.source_id: OfflineAdapter()},
        cassette_store=cassettes,
    )
    replayed = await replay_broker.invoke(
        descriptor.tool_ref, {"value": 3}, mode="replay"
    )
    assert replayed["status"] == "ok"
    assert "_registry_replay" in replayed["structured_content"]

    auth = await broker.invoke(
        by_name["TU_auth_failure"].tool_ref,
        {"value": 1},
        mode="record",
    )
    assert auth["status"] == "error"
    assert len(cassettes.list_records()) == 1

    with pytest.raises(ProviderProtocolError, match="active catalog lock"):
        await runtime_adapter.invoke("TU_not_locked", {"value": 1})


@pytest.mark.asyncio
async def test_real_module_compact_server_and_direct_source_contract_coexist():
    spec = _source_spec()
    source = ToolUniverseCatalogSource(spec, verify_source=False)
    direct_launcher = PythonStdioLauncherV1(
        python_executable=str(Path(sys.executable).resolve()),
        package_root=str(FIXTURES.resolve()),
        entrypoint="stdio_server.py",
    )
    direct_spec = StdioSourceSpecV1(
        source_id="direct.fixture",
        provider_id="direct.fixture",
        provider_version="1.0.0",
        provider_digest=provider_digest(direct_launcher),
        launcher=direct_launcher,
        evidence=AdmissionEvidenceV1(
            protocol_conformance=True,
            provider_pinned=True,
            launcher_verified=True,
        ),
    )
    direct = StdioCatalogSource(
        direct_spec,
        adapter=StaticProviderAdapter(
            [
                ProviderToolV1(
                    name="direct_measure",
                    input_schema={"type": "object"},
                )
            ]
        ),
    )

    result = await build_catalog([source, direct])

    assert len(result.lock.tools) == 207
    assert len(result.lock.quarantined) == 3
    first = next(item for item in result.lock.tools if item.name == "TU_measure_0000")
    assert first.adapter_id == "ari.tooluniverse-compact"
    assert first.capability_ref == "ari.tooluniverse.safe_data.tu_measure_0000"
    assert any(tool.name == "direct_measure" for tool in result.lock.tools)


@pytest.mark.asyncio
async def test_schema_update_requires_separate_explicit_approval(tmp_path: Path):
    spec = _source_spec()
    first_transport = CompactTransport([_leaf(1)])
    first = await build_catalog(
        [
            ToolUniverseCatalogSource(
                spec,
                adapter=_adapter(spec, first_transport),
                verify_source=False,
            )
        ]
    )
    changed_leaf = _leaf(1)
    changed_leaf["parameter"] = {
        **changed_leaf["parameter"],
        "properties": {
            **changed_leaf["parameter"]["properties"],
            "method": {"type": "string"},
        },
    }
    second_transport = CompactTransport([changed_leaf])
    second = await build_catalog(
        [
            ToolUniverseCatalogSource(
                spec,
                adapter=_adapter(spec, second_transport),
                verify_source=False,
            )
        ]
    )
    difference = catalog_diff(first.lock, second.lock)
    assert difference["schema_changes"][0]["changed_fields"] == ["input_schema"]

    lock_path = tmp_path / "CATALOG.lock"
    index_path = tmp_path / "catalog.index.json"
    write_reviewable_catalog(lock_path=lock_path, index_path=index_path, result=first)
    blocked = write_reviewable_catalog(
        lock_path=lock_path,
        index_path=index_path,
        result=second,
        approve=True,
    )
    assert blocked["status"] == "pending-review"
    assert blocked["schema_approval_required"] is True
    approved = write_reviewable_catalog(
        lock_path=lock_path,
        index_path=index_path,
        result=second,
        approve=True,
        approve_schema_changes=True,
    )
    assert approved["status"] == "approved"
