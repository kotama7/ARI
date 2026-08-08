"""Provider-neutral MCP broker with a fixed five-tool LLM surface."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from broker import BrokerError, CatalogBroker
from catalog import build_catalog_index, load_catalog_index, load_catalog_lock
from storage import CassetteStore, RegistryArtifactStore


server = Server("tool-registry-skill")
_BROKER: CatalogBroker | None = None


def _package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _configured_broker() -> CatalogBroker:
    global _BROKER
    if _BROKER is not None:
        return _BROKER
    package_root = _package_root()
    lock_path = Path(
        os.environ.get("ARI_TOOL_REGISTRY_LOCK", str(package_root / "CATALOG.lock"))
    )
    lock = load_catalog_lock(lock_path)
    configured_index = os.environ.get("ARI_TOOL_REGISTRY_INDEX", "").strip()
    index_path = (
        Path(configured_index)
        if configured_index
        else lock_path.with_name("catalog.index.json")
    )
    index = (
        load_catalog_index(index_path, expected_catalog_digest=lock.catalog_digest)
        if index_path.is_file()
        else build_catalog_index(lock)
    )

    checkpoint = os.environ.get("ARI_CHECKPOINT_DIR", "").strip()
    configured_cassettes = os.environ.get("ARI_TOOL_REGISTRY_CASSETTES", "").strip()
    artifact_store = None
    cassette_store = None
    if checkpoint:
        artifact_store = RegistryArtifactStore(Path(checkpoint) / "ear" / "catalog")
    if configured_cassettes:
        cassette_root = Path(configured_cassettes)
        cassette_store = CassetteStore(
            cassette_root,
            artifact_store=artifact_store,
        )
    elif artifact_store is not None:
        cassette_store = CassetteStore(
            artifact_store.root / "cassettes",
            artifact_store=artifact_store,
        )
    _BROKER = CatalogBroker(
        lock,
        index=index,
        artifact_store=artifact_store,
        cassette_store=cassette_store,
    )
    return _BROKER


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Expose federation operations, never leaf-provider schemas."""

    return [
        Tool(
            name="discover",
            description=(
                "Search the immutable federated catalog. Returns bounded summaries "
                "and opaque tool_ref values; it does not execute candidates."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "maxLength": 2000},
                    "constraints": {
                        "type": "object",
                        "description": (
                            "Optional capability/provider/source/admission filters; "
                            "pass next_cursor here as constraints.cursor."
                        ),
                    },
                    "strategy": {
                        "type": "string",
                        "enum": ["lexical", "exact", "diverse"],
                        "default": "lexical",
                    },
                    "top_k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 25,
                        "default": 10,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="describe",
            description=(
                "Read a paginated descriptor section for one exact tool_ref. "
                "Provider text and schemas are treated as untrusted data."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tool_ref": {"type": "string"},
                    "section": {
                        "type": "string",
                        "enum": [
                            "summary",
                            "schema",
                            "provenance",
                            "admission",
                            "limitations",
                            "all",
                        ],
                        "default": "summary",
                    },
                    "cursor": {"type": "string", "default": ""},
                },
                "required": ["tool_ref"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="invoke",
            description=(
                "Invoke one admitted leaf by immutable tool_ref in live, record, "
                "or replay mode. Bare or unqualified names are refused."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tool_ref": {"type": "string"},
                    "args": {"type": "object"},
                    "mode": {
                        "type": "string",
                        "enum": ["live", "record", "replay"],
                        "default": "live",
                    },
                    # The transport injects the call context under this name for
                    # any tool declaring context_requirement: run. A schema that
                    # refuses it refuses every authorized call -- which is what
                    # this one did, so no bound Capability could ever be
                    # dispatched through the broker.
                    "ari_context": {"type": "object"},
                },
                "required": ["tool_ref", "args"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="invoke_scheduled",
            description=(
                "Invoke one admitted leaf that submits work to a scheduler. Same "
                "operation as invoke; a separate surface because a Provider's "
                "side-effect class follows its permissions, so carrying "
                "scheduler authority on the shared surface would raise the "
                "envelope of every leaf dispatched through it."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tool_ref": {"type": "string"},
                    "args": {"type": "object"},
                    "mode": {
                        "type": "string",
                        "enum": ["live", "record", "replay"],
                        "default": "live",
                    },
                    # The transport injects the call context under this name for
                    # any tool declaring context_requirement: run. A schema that
                    # refuses it refuses every authorized call -- which is what
                    # this one did, so no bound Capability could ever be
                    # dispatched through the broker.
                    "ari_context": {"type": "object"},
                },
                "required": ["tool_ref", "args"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="get_status",
            description=(
                "Poll an asynchronous registry handle using lifecycle operations "
                "bound into its immutable descriptor."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "handle": {"type": "object"},
                    "ari_context": {"type": "object"},
                },
                "required": ["handle"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="get_result",
            description=(
                "Fetch the final normalized result for an asynchronous registry handle."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "handle": {"type": "object"},
                    "ari_context": {"type": "object"},
                },
                "required": ["handle"],
                "additionalProperties": False,
            },
        ),
    ]


def _render(value: Any) -> list[TextContent]:
    return [
        TextContent(
            type="text",
            text=json.dumps(value, ensure_ascii=False, sort_keys=True),
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        broker = _configured_broker()
        if name == "discover":
            result = broker.discover(
                query=str(arguments.get("query") or ""),
                constraints=arguments.get("constraints") or {},
                strategy=arguments.get("strategy", "lexical"),
                top_k=int(arguments.get("top_k", 10)),
            )
        elif name == "describe":
            result = broker.describe(
                tool_ref=str(arguments.get("tool_ref") or ""),
                section=arguments.get("section", "summary"),
                cursor=str(arguments.get("cursor") or ""),
            )
        elif name in ("invoke", "invoke_scheduled"):
            # Identical dispatch. The surfaces differ only in the authority they
            # declare, which is the whole point: the split is about what a route
            # may do, not about what it does differently.
            result = await broker.invoke(
                tool_ref=str(arguments.get("tool_ref") or ""),
                arguments=arguments.get("args") or {},
                mode=arguments.get("mode", "live"),
            )
        elif name == "get_status":
            result = await broker.get_status(arguments.get("handle") or {})
        elif name == "get_result":
            result = await broker.get_result(arguments.get("handle") or {})
        else:
            result = {"error": f"unknown registry operation: {name}"}
    except (BrokerError, OSError, ValueError) as exc:
        result = {
            "schema_version": "ari.registry-error/v1",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return _render(result)


async def main() -> None:
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
