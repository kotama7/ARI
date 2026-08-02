"""Paginated MCP fixture used by the generic stdio adapter tests."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool


server = Server("registry-stdio-fixture")


def _tool(
    name: str,
    description: str = "fixture",
    *,
    meta: dict[str, Any] | None = None,
) -> Tool:
    return Tool(
        name=name,
        description=description,
        inputSchema={
            "type": "object",
            "properties": {"value": {"type": "number"}},
            "additionalProperties": True,
        },
        _meta=meta,
    )


PAGE_ONE = [
    _tool(
        "echo",
        "Echo structured arguments",
        meta={
            "ari_semantics": {"operation": "identity"},
            "ari_units": {"value": "1"},
            "ari_limitations": ["fixture only"],
            "ari_independence_group": "fixture-independent-method",
        },
    ),
    _tool("fail", "Return an MCP tool error"),
    _tool("large", "Return a large payload"),
    _tool("env_probe", "Report isolated process identity"),
]
PAGE_TWO = [
    _tool("submit", "Submit a fixture job"),
    _tool("job_status", "Read fixture job status"),
    _tool("job_result", "Read fixture job result"),
    _tool("job_cancel", "Cancel fixture job"),
]


@server.list_tools()
async def list_tools(
    request: types.ListToolsRequest,
) -> types.ListToolsResult:
    cursor = (
        request.params.cursor
        if request is not None and request.params is not None
        else None
    )
    if cursor is None:
        return types.ListToolsResult(tools=PAGE_ONE, nextCursor="page-2")
    if cursor == "page-2":
        return types.ListToolsResult(tools=PAGE_TWO)
    return types.ListToolsResult(tools=[], nextCursor=cursor)


@server.call_tool(validate_input=False)
async def call_tool(name: str, arguments: dict[str, Any]):
    if name == "echo":
        return {"status": "ok", "arguments": arguments}
    if name == "fail":
        return CallToolResult(
            content=[TextContent(type="text", text="fixture provider failure")],
            isError=True,
        )
    if name == "large":
        return {"status": "ok", "payload": "L" * 12_000}
    if name == "env_probe":
        return {
            "status": "ok",
            "home": os.environ.get("HOME"),
            "user": os.environ.get("USER"),
            "secret_marker": os.environ.get("ARI_SECRET_MARKER"),
            "executable": sys.executable,
        }
    if name == "submit":
        return {"status": "SUBMITTED", "job_id": "fixture-job-1"}
    if name == "job_status":
        return {"status": "RUNNING", "job_id": arguments.get("job_id")}
    if name == "job_result":
        return {
            "status": "COMPLETED",
            "job_id": arguments.get("job_id"),
            "value": 42,
        }
    if name == "job_cancel":
        return {"status": "CANCELLED", "job_id": arguments.get("job_id")}
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps({"error": name}))],
        isError=True,
    )


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
