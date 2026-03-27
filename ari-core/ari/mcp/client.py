"""MCP client for calling Skills (MCP Servers) via stdio protocol.

Features:
- Connection pooling: MCP server processes stay alive across calls
- Retry logic: up to MAX_RETRIES attempts per tool call
- Thread-safe: uses asyncio loop per thread
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ari.config import SkillConfig

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 0.5


class _SkillConnection:
    """Persistent connection to a single MCP Skill server."""

    def __init__(self, skill: SkillConfig) -> None:
        self.skill = skill
        self._session: ClientSession | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._context_stack: Any = None

    def _skill_path(self) -> Path:
        import os as _os
        path = self.skill.path
        # Resolve {{ari_root}} template in skill path
        ari_root = _os.environ.get("ARI_ROOT", str(Path(__file__).parents[3]))
        path = path.replace("{{ari_root}}", ari_root)
        return Path(path)

    def _server_params(self) -> StdioServerParameters:
        import os
        skill_path = self._skill_path()
        return StdioServerParameters(
            command=sys.executable,
            args=[str(skill_path / "src" / "server.py")],
            env={**os.environ, "PYTHONPATH": str(skill_path)},
        )

    async def _start(self) -> None:
        """Start the MCP server process and establish session."""
        import contextlib
        stack = contextlib.AsyncExitStack()
        read, write = await stack.enter_async_context(stdio_client(self._server_params()))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._session = session
        self._context_stack = stack

    async def _stop(self) -> None:
        if self._context_stack is not None:
            try:
                await self._context_stack.aclose()
            except Exception:
                pass
            self._context_stack = None
            self._session = None

    def _run(self, coro: Any) -> Any:
        """Run a coroutine safely regardless of calling thread context.

        When called from a thread that already has a running event loop
        (e.g. asyncio executor thread), create a fresh loop in the current
        thread to avoid 'This event loop is already running' errors.
        """
        import threading as _threading

        # Check if there's already a running loop in the current thread
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if running is not None:
            # We're inside a running loop (e.g. executor thread spawned by asyncio).
            # Create a brand-new loop for this MCP call.
            new_loop = asyncio.new_event_loop()
            try:
                return new_loop.run_until_complete(coro)
            finally:
                new_loop.close()
        else:
            # Normal sync context — use per-connection loop.
            if self._loop is None or self._loop.is_closed():
                self._loop = asyncio.new_event_loop()
            return self._loop.run_until_complete(coro)

    def ensure_connected(self) -> None:
        if self._session is None:
            self._run(self._start())

    def list_tools(self) -> list[dict]:
        self.ensure_connected()

        async def _list() -> list[dict]:
            assert self._session is not None
            result = await self._session.list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": t.inputSchema if t.inputSchema else {},
                    "skill_name": self.skill.name,
                }
                for t in result.tools
            ]

        return self._run(_list())

    def call_tool(self, tool_name: str, args: dict) -> dict:
        self.ensure_connected()

        async def _call() -> dict:
            assert self._session is not None
            result = await self._session.call_tool(tool_name, args)
            parts = [p.text for p in result.content if hasattr(p, "text")]
            return {"result": "\n".join(parts) if parts else ""}

        return self._run(_call())

    def close(self) -> None:
        if self._loop and not self._loop.is_closed():
            self._loop.run_until_complete(self._stop())
            self._loop.close()


class MCPClient:
    """MCP client with connection pooling and retry logic."""

    def __init__(self, skills: list[SkillConfig]) -> None:
        self.skills = skills
        self._connections: dict[str, _SkillConnection] = {}
        self._conn_lock = __import__('threading').Lock()
        self._tool_registry: dict[str, str] = {}  # tool_name -> skill.name
        self._tools_cache: list[dict] | None = None
        atexit.register(self.close_all)

    def _get_conn(self, skill_name: str) -> _SkillConnection | None:
        return self._connections.get(skill_name)

    def _init_connection(self, skill: SkillConfig) -> _SkillConnection:
        with self._conn_lock:
            if skill.name not in self._connections:
                conn = _SkillConnection(skill)
                self._connections[skill.name] = conn
            return self._connections[skill.name]

    def list_tools(self, phase: str | None = None) -> list[dict]:
        """Return skill tools, optionally filtered by phase ('bfts' | 'pipeline' | None=all)."""
        if self._tools_cache is not None:
            if phase is None:
                return self._tools_cache
            _pm = getattr(self, '_phase_map', {})
            return [t for t in self._tools_cache if _pm.get(t['name'], 'all') in (phase, 'all')]

        tools: list[dict] = []
        for skill in self.skills:
            try:
                conn = self._init_connection(skill)
                skill_tools = conn.list_tools()
                for t in skill_tools:
                    self._tool_registry[t["name"]] = skill.name
                tools.extend(skill_tools)
                logger.info("Loaded %d tools from skill '%s'", len(skill_tools), skill.name)
            except Exception as e:
                logger.warning("Failed to load skill '%s': %s", skill.name, e)

        self._tools_cache = tools
        self._phase_map = {t["name"]: getattr(
            next((s for s in self.skills if s.name == self._tool_registry.get(t["name"],"")), None),
            "phase", "all") for t in tools}

        if phase is None:
            return self._tools_cache
        return [t for t in self._tools_cache if self._phase_map.get(t["name"], "all") in (phase, "all")]

    def call_tool(self, tool_name: str, args: dict) -> dict:
        """Call a tool. Reuses connection pool and retries on failure."""
        skill_name = self._tool_registry.get(tool_name)
        if not skill_name:
            registered = list(self._tool_registry.keys())
            return {
                "error": (
                    f"Tool '{tool_name}' not found. "
                    f"Available: {registered}"
                )
            }

        conn = self._connections.get(skill_name)
        if conn is None:
            skill = next((s for s in self.skills if s.name == skill_name), None)
            if skill is None:
                return {"error": f"Skill '{skill_name}' not found"}
            conn = self._init_connection(skill)

        last_error = ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return conn.call_tool(tool_name, args)
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(
                    "Tool '%s' attempt %d/%d failed: %s",
                    tool_name, attempt, MAX_RETRIES, last_error,
                )
                # Reconnect in case the connection was dropped
                try:
                    conn.close()
                    self._connections.pop(skill_name, None)  # invalidate before re-init
                    conn = self._init_connection(
                        next(s for s in self.skills if s.name == skill_name)
                    )
                    self._connections[skill_name] = conn
                except Exception:
                    pass
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * attempt)

        return {
            "error": (
                f"Tool '{tool_name}' failed after {MAX_RETRIES} attempts. "
                f"Last: {last_error}"
            )
        }

    def close_all(self) -> None:
        """Close all connections."""
        for conn in self._connections.values():
            try:
                conn.close()
            except Exception:
                pass
        self._connections.clear()
