"""MCP fixture whose call leaves a child in the server process group."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.types import Tool


server = Server("registry-stdio-hanging-fixture")


@server.list_tools()
async def list_tools(
    _request: types.ListToolsRequest,
) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            Tool(
                name="spawn_and_hang",
                description="Spawn a child and wait until the transport cancels the call",
                inputSchema={
                    "type": "object",
                    "properties": {"pid_file": {"type": "string"}},
                    "required": ["pid_file"],
                    "additionalProperties": False,
                },
            )
        ]
    )


@server.call_tool(validate_input=False)
async def call_tool(name: str, arguments: dict[str, Any]):
    if name != "spawn_and_hang":
        raise ValueError(name)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    Path(str(arguments["pid_file"])).write_text(str(child.pid), encoding="utf-8")
    await asyncio.sleep(60)
    return {"status": "unexpected"}


async def main() -> None:
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
