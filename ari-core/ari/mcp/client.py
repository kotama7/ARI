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
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ari.config import SkillConfig

logger = logging.getLogger(__name__)


def _normalize_phases(phase: str | list[str] | None) -> list[str]:
    """Coerce SkillConfig.phase into a flat list of phase strings."""
    if phase is None:
        return ["all"]
    if isinstance(phase, str):
        return [phase]
    return [str(p) for p in phase]


def _phase_matches(skill_phase: str | list[str], want: str) -> bool:
    """True iff a skill declared `skill_phase` should be exposed for `want`."""
    phases = _normalize_phases(skill_phase)
    return want in phases or "all" in phases


def _phase_is_disabled(skill_phase: str | list[str]) -> bool:
    """True iff the skill is fully disabled (phase == 'none' or ['none'])."""
    phases = [p for p in _normalize_phases(skill_phase) if p]
    return phases == ["none"]

MAX_RETRIES = 3
RETRY_DELAY = 0.5
DEFAULT_TOOL_TIMEOUT = 300   # seconds
# Tools that perform internal LLM calls or heavy processing need longer timeouts
SLOW_TOOL_TIMEOUT = 600      # seconds
_SLOW_TOOLS = frozenset({"generate_ideas", "write_paper_iterative", "review_compiled_paper",
                          "collect_references_iterative", "reproduce_from_paper"})


class _SkillConnection:
    """Persistent connection to a single MCP Skill server."""

    def __init__(self, skill: SkillConfig) -> None:
        self.skill = skill
        self._session: ClientSession | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._context_stack: Any = None

    def _skill_path(self) -> Path:
        import os as _os
        path = self.skill.path
        # Resolve {{ari_root}} template in skill path
        ari_root = _os.environ.get("ARI_ROOT", str(Path(__file__).parents[3]))
        path = path.replace("{{ari_root}}", ari_root)
        return Path(path)

    @staticmethod
    def _resolve_python(skill_path: Path) -> str:
        """Return the best Python interpreter for a skill.

        Priority:
        1. Skill-local venv  (<skill>/.venv/bin/python)
        2. Python recorded by setup.sh  ($ARI_ROOT/.ari_python)
        3. sys.executable (fallback)
        """
        # 1. Skill-local venv
        skill_python = skill_path / ".venv" / "bin" / "python"
        if skill_python.is_file():
            return str(skill_python)

        # 2. Recorded by setup.sh
        import os as _os
        ari_root = _os.environ.get("ARI_ROOT", str(Path(__file__).parents[3]))
        marker = Path(ari_root) / ".ari_python"
        if marker.is_file():
            recorded = marker.read_text().strip()
            if recorded and Path(recorded).is_file():
                return recorded

        # 3. Fallback
        return sys.executable

    def _server_params(self) -> StdioServerParameters:
        import os
        skill_path = self._skill_path()
        python = self._resolve_python(skill_path)
        # Expose ari-core on the skill subprocess's PYTHONPATH so the skill
        # can `from ari import cost_tracker` and wire itself into the shared
        # cost_trace.jsonl. ari-core is kept last so the skill's own src/
        # layout wins on name collisions.
        ari_core_root = str(Path(__file__).parents[2])
        pythonpath = os.pathsep.join([str(skill_path), ari_core_root])
        return StdioServerParameters(
            command=python,
            args=[str(skill_path / "src" / "server.py")],
            env={**os.environ, "PYTHONPATH": pythonpath},
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

    def _ensure_loop(self) -> None:
        """Ensure the dedicated event loop thread is running.

        A single daemon thread runs ``loop.run_forever()`` for the
        lifetime of this connection.  All coroutines are submitted via
        ``asyncio.run_coroutine_threadsafe`` and therefore serialised on
        the loop — no concurrent ``run_until_complete`` conflicts.
        """
        if (
            self._loop is not None
            and not self._loop.is_closed()
            and self._loop_thread is not None
            and self._loop_thread.is_alive()
        ):
            return
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, daemon=True,
        )
        self._loop_thread.start()

    def _run(self, coro: Any, timeout: int = DEFAULT_TOOL_TIMEOUT) -> Any:
        """Run a coroutine on the connection's dedicated event loop thread.

        Thread-safe: concurrent callers are queued on the single loop via
        ``asyncio.run_coroutine_threadsafe``, so there is no risk of
        "This event loop is already running".
        """
        self._ensure_loop()
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

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

    def call_tool(self, tool_name: str, args: dict, timeout: int = DEFAULT_TOOL_TIMEOUT) -> dict:
        self.ensure_connected()

        async def _call() -> dict:
            assert self._session is not None
            result = await self._session.call_tool(tool_name, args)
            parts = [p.text for p in result.content if hasattr(p, "text")]
            text = "\n".join(parts) if parts else ""
            if not text:
                return {"error": f"Tool '{tool_name}' returned empty response — the tool may have crashed or timed out."}
            return {"result": text}

        return self._run(_call(), timeout=timeout)

    def close(self) -> None:
        if self._loop and not self._loop.is_closed():
            # Submit _stop() to the loop thread (same path as _run)
            future = asyncio.run_coroutine_threadsafe(self._stop(), self._loop)
            try:
                future.result(timeout=30)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._loop_thread is not None:
                self._loop_thread.join(timeout=5)
            self._loop.close()
        self._loop_thread = None


class MCPClient:
    """MCP client with connection pooling and retry logic."""

    # Tools whose CoW guard reads ARI_CURRENT_NODE_ID inside the
    # pooled memory-skill MCP server. The (set_current_node, write)
    # pair must be atomic across all parallel nodes that share this
    # MCPClient — see ``call_tool(cow_node_id=...)`` below.
    _COW_TOOLS: frozenset = frozenset({"add_memory", "clear_node_memory"})

    def __init__(self, skills: list[SkillConfig], disabled_tools: list[str] | None = None) -> None:
        import threading as _t
        self.skills = skills
        self.disabled_tools: set[str] = set(disabled_tools or [])
        self._connections: dict[str, _SkillConnection] = {}
        self._conn_lock = _t.Lock()
        # Serialises (_set_current_node, memory write) pairs across
        # parallel BFTS nodes. RLock so the same thread can re-enter
        # if a future caller wraps higher-level helpers.
        self._cow_lock = _t.RLock()
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
        """Return skill tools, optionally filtered by phase and disabled_tools."""
        if self._tools_cache is None:
            self._build_tools_cache()

        tools = self._tools_cache
        # Filter by disabled_tools
        if self.disabled_tools:
            tools = [t for t in tools if t["name"] not in self.disabled_tools]
        # Filter by phase. Skill `phase` may be a string or a list; matching is
        # any-of with "all" as wildcard.
        if phase is not None:
            _pm = self._phase_map
            tools = [t for t in tools if _phase_matches(_pm.get(t["name"], "all"), phase)]
        return tools

    def _build_tools_cache(self) -> None:
        """Discover tools from all enabled skills (called once, lazily)."""
        tools: list[dict] = []
        for skill in self.skills:
            # Skip disabled skills (phase: none / [none]) — don't start MCP server
            if _phase_is_disabled(getattr(skill, "phase", "all")):
                logger.info("Skipping disabled skill '%s' (phase=none)", skill.name)
                continue
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

    def call_tool(
        self,
        tool_name: str,
        args: dict,
        *,
        cow_node_id: str | None = None,
    ) -> dict:
        """Call a tool. Reuses connection pool and retries on failure.

        ``cow_node_id`` (optional): when set and ``tool_name`` is a
        CoW-guarded memory tool (``add_memory`` / ``clear_node_memory``),
        ``_set_current_node({node_id: cow_node_id})`` is invoked under a
        process-wide lock immediately before the actual call so the two
        operations are atomic across parallel BFTS nodes that share this
        MCPClient. Without this, the memory skill's ``ARI_CURRENT_NODE_ID``
        env var (set by ``_set_current_node``) is racy and one node's
        write can be rejected by another node's set.
        """
        if cow_node_id and tool_name in self._COW_TOOLS:
            with self._cow_lock:
                self._call_tool_unlocked(
                    "_set_current_node", {"node_id": cow_node_id},
                )
                return self._call_tool_unlocked(tool_name, args)
        return self._call_tool_unlocked(tool_name, args)

    def _call_tool_unlocked(self, tool_name: str, args: dict) -> dict:
        """Internal: same as call_tool but without the CoW gate.

        Holds no locks; safe to call from inside ``_cow_lock`` for the
        atomic (set + write) sequence.
        """
        # ── Trace: log tool call args for propagation debugging ────
        _TRACE_TOOLS = {"make_metric_spec", "generate_ideas", "survey"}
        if tool_name in _TRACE_TOOLS:
            import json as _json_trace
            _args_str = _json_trace.dumps(args, ensure_ascii=False)
            logger.info(
                "[mcp] call_tool %s: args_len=%d args=%s",
                tool_name, len(_args_str), _args_str[:500],
            )
        else:
            logger.debug("[mcp] call_tool %s: args_keys=%s", tool_name, list(args.keys()))
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

        timeout = SLOW_TOOL_TIMEOUT if tool_name in _SLOW_TOOLS else DEFAULT_TOOL_TIMEOUT

        last_error = ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return conn.call_tool(tool_name, args, timeout=timeout)
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
