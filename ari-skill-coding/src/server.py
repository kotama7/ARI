"""MCP Server for code writing and execution."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from mcp.server import Server
from mcp.types import TextContent, Tool


def _resolve_work_dir(explicit: str | None) -> str:
    """Return the effective work directory: explicit arg > ARI_WORK_DIR env > /tmp/ari_work."""
    wd = explicit or os.environ.get("ARI_WORK_DIR") or "/tmp/ari_work"
    Path(wd).mkdir(parents=True, exist_ok=True)
    return wd

server = Server("coding-skill")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="write_code",
            description="Write code to a file in the specified working directory",
            inputSchema={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "File name to write (e.g. main.py)",
                    },
                    "code": {
                        "type": "string",
                        "description": "Code content to write",
                    },
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory",
                        "default": "/tmp/ari_work",
                    },
                },
                "required": ["filename", "code"],
            },
        ),
        Tool(
            name="run_code",
            description="Execute a Python file and return stdout/stderr/exit_code",
            inputSchema={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "File name to execute",
                    },
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory",
                        "default": "/tmp/ari_work",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds",
                        "default": 60,
                    },
                },
                "required": ["filename"],
            },
        ),
        Tool(
            name="run_bash",
            description="Execute a bash command and return stdout/stderr/exit_code",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Bash command to execute",
                    },
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory",
                        "default": "/tmp/ari_work",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds",
                        "default": 60,
                    },
                },
                "required": ["command"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "write_code":
        result = _write_code(
            filename=arguments["filename"],
            code=arguments["code"],
            work_dir=_resolve_work_dir(arguments.get("work_dir")),
        )
    elif name == "run_code":
        result = _run_code(
            filename=arguments["filename"],
            work_dir=_resolve_work_dir(arguments.get("work_dir")),
            timeout=arguments.get("timeout", 60),
        )
    elif name == "run_bash":
        result = _run_bash(
            command=arguments["command"],
            work_dir=_resolve_work_dir(arguments.get("work_dir")),
            timeout=arguments.get("timeout", 60),
        )
    else:
        result = {"error": f"Unknown tool: {name}"}

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


def _write_code(filename: str, code: str, work_dir: str) -> dict:
    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)
    file_path = work_path / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(code, encoding="utf-8")
    return {
        "path": str(file_path),
        "lines": len(code.splitlines()),
        "status": "written",
    }


def _run_code(filename: str, work_dir: str, timeout: int) -> dict:
    file_path = Path(work_dir) / filename
    if not file_path.exists():
        return {"error": f"File not found: {file_path}", "exit_code": -1}

    try:
        result = subprocess.run(
            ["python3", str(file_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir,
        )
        return {
            "stdout": result.stdout[-4000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
            "exit_code": result.returncode,
            "status": "success" if result.returncode == 0 else "failed",
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Timeout after {timeout}s", "exit_code": -1}
    except Exception as e:
        return {"error": str(e), "exit_code": -1}


def _run_bash(command: str, work_dir: str, timeout: int) -> dict:
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir,
        )
        return {
            "stdout": result.stdout[-4000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
            "exit_code": result.returncode,
            "status": "success" if result.returncode == 0 else "failed",
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Timeout after {timeout}s", "exit_code": -1}
    except Exception as e:
        return {"error": str(e), "exit_code": -1}


async def main() -> None:
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
