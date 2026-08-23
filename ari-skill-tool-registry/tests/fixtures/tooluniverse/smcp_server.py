"""Compact ToolUniverse-shaped MCP fixture launched with ``python -m``."""

from __future__ import annotations

import json
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool


server = Server("tooluniverse-compact-fixture")


def _leaf(index: int) -> dict[str, Any]:
    name = f"TU_measure_{index:04d}"
    return {
        "name": name,
        "type": "BaseRESTTool",
        "category": "safe_data",
        "source_file": "data/safe_tools.json",
        "description": f"Measure fixture value {index}",
        "parameter": {
            "type": "object",
            "properties": {
                "value": {"type": "integer"},
                "scale": {"type": "number", "default": 1.0},
            },
            "required": ["value"],
            "additionalProperties": False,
        },
        "return_schema": {
            "type": "object",
            "properties": {"value": {"type": "number"}},
            "required": ["value"],
        },
    }


LEAVES = [_leaf(index) for index in range(205)]
LEAVES.extend(
    [
        {
            **_leaf(9001),
            "name": "TU_dynamic_loader",
            "type": "MCPAutoLoaderTool",
            "category": "mcp_auto_loader_remote",
        },
        {
            **_leaf(9002),
            "name": "TU_unprofiled",
            "type": "UnknownTool",
            "category": "unreviewed",
        },
        {
            **_leaf(9003),
            "name": "TU_needs_key",
            "required_api_keys": ["EXAMPLE_API_KEY"],
        },
        {
            **_leaf(9004),
            "name": "TU_auth_failure",
        },
    ]
)
BY_NAME = {item["name"]: item for item in LEAVES}


COMPACT_TOOLS = [
    Tool(name=name, description=name, inputSchema={"type": "object"})
    for name in ("list_tools", "grep_tools", "get_tool_info", "execute_tool")
]


@server.list_tools()
async def list_tools(_request: types.ListToolsRequest) -> types.ListToolsResult:
    return types.ListToolsResult(tools=COMPACT_TOOLS)


@server.call_tool(validate_input=False)
async def call_tool(name: str, arguments: dict[str, Any]):
    if name == "list_tools":
        offset = int(arguments.get("offset", 0))
        limit = int(arguments.get("limit", 250))
        fields = arguments.get("fields") or ["name"]
        page = LEAVES[offset : offset + limit]
        summaries = [
            {field: leaf[field] for field in fields if field in leaf} for leaf in page
        ]
        next_offset = offset + len(page)
        has_more = next_offset < len(LEAVES)
        return {
            "total_tools": len(LEAVES),
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
            "next_offset": next_offset if has_more else None,
            "tools": summaries,
        }
    if name == "get_tool_info":
        names = arguments.get("tool_names")
        if isinstance(names, str):
            return BY_NAME.get(names) or {"name": names, "error": "not found"}
        definitions = [
            BY_NAME.get(item) or {"name": item, "error": "not found"}
            for item in names or []
        ]
        return {
            "total_requested": len(names or []),
            "total_found": sum("error" not in item for item in definitions),
            "tools": definitions,
        }
    if name == "execute_tool":
        leaf_name = arguments.get("tool_name")
        leaf_arguments = arguments.get("arguments") or {}
        if leaf_name == "TU_auth_failure":
            return {
                "status": "error",
                "error": "Unauthorized: invalid API key",
                "error_type": "AuthenticationError",
            }
        if leaf_name not in BY_NAME:
            return {
                "status": "error",
                "error": f"unknown leaf {leaf_name}",
                "error_type": "ValidationError",
            }
        return {
            "status": "ok",
            "value": leaf_arguments.get("value", 0) * leaf_arguments.get("scale", 1.0),
        }
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


def run_stdio_server() -> None:
    import asyncio

    asyncio.run(main())


if __name__ == "__main__":
    run_stdio_server()
