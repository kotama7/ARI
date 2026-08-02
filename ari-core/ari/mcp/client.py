"""Thread-safe pooled MCP stdio client with bounded retries and typed results."""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ari.config import SkillConfig
from ari.mcp.dispatch_support import (
    COW_TOOLS,
    DEFAULT_TOOL_TIMEOUT,
    MAX_RETRIES,
    RETRY_DELAY,
    SLOW_TOOL_TIMEOUT as SLOW_TOOL_TIMEOUT,
    VERY_SLOW_TOOL_TIMEOUT as VERY_SLOW_TOOL_TIMEOUT,
    ToolNameCollisionError,
    default_call_context,
    log_tool_call,
    phase_is_disabled as _phase_is_disabled,
    phase_matches as _phase_matches,
    resolve_registration as _resolve_registration,
    resolve_tool_timeout as _resolve_tool_timeout,
    runtime_tool_ref as _runtime_tool_ref,
    unresolved_tool_ref as _unresolved_tool_ref,
)
from ari.mcp.lock_runtime import SkillLockController
from ari.protocols.stores import ArtifactStore
from ari.result import (
    DEFAULT_INLINE_RESULT_LIMIT,
    ResultArtifactIntegrityError,
    ResultEnvelopeNormalizer,
    ResultEnvelopeV1,
    ResultErrorKind,
    ToolCallContextV1,
    utc_now_iso,
)
from ari.skill_lock import (
    SkillLockError,
    SkillProviderAdmissionError,
    SkillsLockV1,
)

logger = logging.getLogger(__name__)


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
            args=[str(skill_path / self.skill.entrypoint)],
            env={**os.environ, "PYTHONPATH": pythonpath},
        )

    async def _start(self) -> None:
        """Start the MCP server process and establish session."""
        import contextlib

        stack = contextlib.AsyncExitStack()
        read, write = await stack.enter_async_context(
            stdio_client(self._server_params())
        )
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
            target=self._loop.run_forever,
            daemon=True,
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
                    "outputSchema": t.outputSchema if t.outputSchema else {},
                    "skill_name": self.skill.name,
                }
                for t in result.tools
            ]

        return self._run(_list())

    def call_tool(
        self, tool_name: str, args: dict, timeout: int = DEFAULT_TOOL_TIMEOUT
    ) -> dict:
        self.ensure_connected()

        async def _call() -> dict:
            assert self._session is not None
            result = await self._session.call_tool(tool_name, args)
            parts = [p.text for p in result.content if hasattr(p, "text")]
            text = "\n".join(parts) if parts else ""
            structured = getattr(result, "structuredContent", None)
            if not isinstance(structured, dict):
                structured = None
            if not text and structured:
                text = json.dumps(structured, ensure_ascii=False)
            if not text:
                return {
                    "error": (
                        f"Tool '{tool_name}' returned empty response — the tool "
                        "may have crashed or timed out."
                    ),
                    "_error_kind": "protocol",
                    "_retryable": True,
                }
            return {
                "result": text,
                "_structured_content": structured,
                "_mcp_is_error": bool(getattr(result, "isError", False)),
            }

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
    _COW_TOOLS: frozenset = COW_TOOLS

    def __init__(
        self,
        skills: list[SkillConfig],
        disabled_tools: list[str] | None = None,
        *,
        artifact_store: ArtifactStore | None = None,
        result_inline_limit: int = DEFAULT_INLINE_RESULT_LIMIT,
        skill_lock_path: str | Path | None = None,
        skill_lock_scope: str = "exact",
        strict_provider_loading: bool | None = None,
    ) -> None:
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
        self._tool_ref_registry: dict[str, str] = {}  # tool_ref -> skill.name
        self._tool_name_by_ref: dict[str, str] = {}
        self._tool_ref_by_name: dict[str, str] = {}
        self._tool_metadata_by_ref: dict[str, dict] = {}
        self._tools_cache: list[dict] | None = None
        self._artifact_store = artifact_store
        self._derived_artifact_store: tuple[str, ArtifactStore] | None = None
        self._result_inline_limit = result_inline_limit
        self._skill_lock = SkillLockController(
            skill_lock_path,
            scope=skill_lock_scope,
            strict_provider_loading=strict_provider_loading,
        )
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
        # any-of with "all" as wildcard. Canonical per-tool policy is an
        # additional constraint rather than a replacement for Skill exposure.
        if phase is not None:
            tools = [t for t in tools if self._tool_admits_phase(t["tool_ref"], phase)]
        return tools

    def _build_tools_cache(self) -> None:
        """Discover tools from all enabled skills (called once, lazily).

        Bare names are retained as a compatibility alias only while they are
        unique.  A collision is an admission error; silently selecting the last
        registered Skill would make tool choice order-dependent.
        """
        tools: list[dict] = []
        registry: dict[str, str] = {}
        ref_registry: dict[str, str] = {}
        name_by_ref: dict[str, str] = {}
        ref_by_name: dict[str, str] = {}
        collisions: dict[str, set[str]] = {}
        for skill in self.skills:
            # Skip disabled skills (phase: none / [none]) — don't start MCP server
            if _phase_is_disabled(getattr(skill, "phase", "all")):
                logger.info("Skipping disabled skill '%s' (phase=none)", skill.name)
                continue
            try:
                conn = self._init_connection(skill)
                skill_tools = conn.list_tools()
                enriched_tools = []
                for raw_tool in skill_tools:
                    t = dict(raw_tool)
                    tool_ref = _runtime_tool_ref(skill, t)
                    t["tool_ref"] = tool_ref
                    capability_ref = skill.tool_capabilities.get(t["name"])
                    if capability_ref:
                        t["capability_ref"] = capability_ref
                    policy = skill.tool_policies.get(t["name"])
                    if policy:
                        t["policy"] = policy
                    previous = registry.get(t["name"])
                    if previous is not None and previous != skill.name:
                        collisions.setdefault(t["name"], {previous}).add(skill.name)
                    else:
                        registry[t["name"]] = skill.name
                        ref_by_name[t["name"]] = tool_ref
                    previous_ref = ref_registry.get(tool_ref)
                    if previous_ref is not None and previous_ref != skill.name:
                        raise ToolNameCollisionError(
                            f"immutable tool_ref collision: {tool_ref}"
                        )
                    ref_registry[tool_ref] = skill.name
                    name_by_ref[tool_ref] = t["name"]
                    enriched_tools.append(t)
                tools.extend(enriched_tools)
                logger.info(
                    "Loaded %d tools from skill '%s'", len(skill_tools), skill.name
                )
            except ToolNameCollisionError:
                raise
            except Exception as e:
                if self._skill_lock.strict_provider_loading:
                    self.close_all()
                    raise SkillProviderAdmissionError(
                        f"required MCP Skill '{skill.name}' failed live discovery: "
                        f"{type(e).__name__}: {e}"
                    ) from e
                logger.warning("Failed to load skill '%s': %s", skill.name, e)

        if collisions:
            rendered = "; ".join(
                f"{name}: {', '.join(sorted(owners))}"
                for name, owners in sorted(collisions.items())
            )
            self.close_all()
            raise ToolNameCollisionError(
                "Ambiguous MCP tool names are not admitted; configure one owner "
                f"or use a namespaced registry: {rendered}"
            )

        self._tool_registry = registry
        self._tool_ref_registry = ref_registry
        self._tool_name_by_ref = name_by_ref
        self._tool_ref_by_name = ref_by_name
        self._tool_metadata_by_ref = {tool["tool_ref"]: tool for tool in tools}
        self._tools_cache = tools
        self._phase_map = {
            t["name"]: getattr(
                next(
                    (
                        s
                        for s in self.skills
                        if s.name == self._tool_registry.get(t["name"], "")
                    ),
                    None,
                ),
                "phase",
                "all",
            )
            for t in tools
        }
        self._reconcile_skills_lock()

    def _reconcile_skills_lock(self) -> None:
        """Create or verify the run's immutable live-provider snapshot."""

        try:
            self._skill_lock.reconcile(
                skills=self.skills,
                tools=self._tools_cache or [],
                disabled_tools=self.disabled_tools,
            )
        except SkillLockError:
            self.close_all()
            self._tool_registry = {}
            self._tool_ref_registry = {}
            self._tool_name_by_ref = {}
            self._tool_ref_by_name = {}
            self._tool_metadata_by_ref = {}
            self._tools_cache = None
            self._skill_lock.clear()
            raise

    @property
    def skills_lock(self) -> SkillsLockV1 | None:
        """Return the reconciled snapshot after discovery, if locking is enabled."""

        return self._skill_lock.snapshot

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
                    "_set_current_node",
                    {"node_id": cow_node_id},
                )
                return self._call_tool_unlocked(tool_name, args)
        return self._call_tool_unlocked(tool_name, args)

    def call_tool_envelope(
        self,
        tool_name_or_ref: str,
        args: dict,
        *,
        context: ToolCallContextV1 | None = None,
        cow_node_id: str | None = None,
    ) -> ResultEnvelopeV1:
        """Call a tool and return the canonical typed result envelope.

        ``tool_name_or_ref`` accepts an immutable ``tool_ref`` or a unique bare
        alias during migration.  New federation callers should always pass the
        immutable reference returned by :meth:`list_tools`.
        """

        if self._tools_cache is None:
            started_at = utc_now_iso()
            try:
                self._build_tools_cache()
            except (ToolNameCollisionError, SkillLockError) as exc:
                return self._result_normalizer().error(
                    tool_ref=_unresolved_tool_ref(tool_name_or_ref),
                    kind="admission",
                    message=str(exc),
                    retryable=False,
                    context=context,
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )

        registered_name = self._tool_name_by_ref.get(tool_name_or_ref, tool_name_or_ref)
        if cow_node_id and registered_name in self._COW_TOOLS:
            with self._cow_lock:
                cow_context = context or self._default_call_context(node_id=cow_node_id)
                context_result = self._call_tool_envelope_unlocked(
                    "_set_current_node",
                    {"node_id": cow_node_id},
                    context=cow_context,
                )
                if context_result.status == "error":
                    return context_result
                return self._call_tool_envelope_unlocked(
                    tool_name_or_ref,
                    args,
                    context=cow_context,
                )
        return self._call_tool_envelope_unlocked(
            tool_name_or_ref,
            args,
            context=context,
        )

    def _call_tool_unlocked(self, tool_name: str, args: dict) -> dict:
        """Internal: same as call_tool but without the CoW gate.

        Holds no locks; safe to call from inside ``_cow_lock`` for the
        atomic (set + write) sequence.
        """
        envelope = self._call_tool_envelope_unlocked(tool_name, args)
        return envelope.to_legacy(self._artifact_store_for_call())

    def _call_tool_envelope_unlocked(
        self,
        tool_name_or_ref: str,
        args: dict,
        *,
        context: ToolCallContextV1 | None = None,
    ) -> ResultEnvelopeV1:
        """Typed dispatch implementation; caller owns any required CoW lock."""

        started_at = utc_now_iso()
        normalizer = self._result_normalizer()
        if self._tools_cache is None:
            try:
                self._build_tools_cache()
            except (ToolNameCollisionError, SkillLockError) as exc:
                return normalizer.error(
                    tool_ref=_unresolved_tool_ref(tool_name_or_ref),
                    kind="admission",
                    message=str(exc),
                    retryable=False,
                    context=context,
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )

        tool_name, tool_ref, skill_name, selection_reason = _resolve_registration(
            tool_name_or_ref,
            tool_ref_registry=self._tool_ref_registry,
            tool_name_by_ref=self._tool_name_by_ref,
            tool_registry=self._tool_registry,
            tool_ref_by_name=self._tool_ref_by_name,
        )
        effective_context = context or self._default_call_context()
        if not effective_context.selection_reason:
            effective_context = effective_context.model_copy(
                update={"selection_reason": selection_reason}
            )

        admission_error = self._registration_admission_error(
            requested=tool_name_or_ref,
            tool_name=tool_name,
            tool_ref=tool_ref,
            skill_name=skill_name,
            context=effective_context,
            normalizer=normalizer,
            started_at=started_at,
        )
        if admission_error is not None:
            return admission_error
        assert skill_name is not None

        return self._invoke_registered_tool(
            tool_name=tool_name,
            tool_ref=tool_ref,
            skill_name=skill_name,
            args=args,
            context=effective_context,
            normalizer=normalizer,
            started_at=started_at,
        )

    def _registration_admission_error(
        self,
        *,
        requested: str,
        tool_name: str,
        tool_ref: str,
        skill_name: str | None,
        context: ToolCallContextV1,
        normalizer: ResultEnvelopeNormalizer,
        started_at: str,
    ) -> ResultEnvelopeV1 | None:
        """Return a typed policy rejection, or ``None`` when dispatch is admitted."""

        message = ""
        if not skill_name:
            message = f"Tool '{requested}' not found. Available: {sorted(self._tool_registry)}"
        elif tool_name in self.disabled_tools or tool_ref in self.disabled_tools:
            message = f"Tool '{tool_name}' is disabled by run configuration"
        elif context.phase and not self._tool_admits_phase(tool_ref, context.phase):
            message = f"Tool '{tool_name}' is not admitted in phase '{context.phase}'"
        if not message:
            return None
        return normalizer.error(
            tool_ref=tool_ref,
            kind="admission",
            message=message,
            retryable=False,
            context=context,
            started_at=started_at,
            completed_at=utc_now_iso(),
        )

    def _invoke_registered_tool(
        self,
        *,
        tool_name: str,
        tool_ref: str,
        skill_name: str,
        args: dict,
        context: ToolCallContextV1,
        normalizer: ResultEnvelopeNormalizer,
        started_at: str,
    ) -> ResultEnvelopeV1:
        """Invoke an admitted registration and normalize transport outcomes."""

        log_tool_call(logger, tool_name, args)
        conn = self._connections.get(skill_name)
        if conn is None:
            skill = next((s for s in self.skills if s.name == skill_name), None)
            if skill is None:
                return normalizer.error(
                    tool_ref=tool_ref,
                    kind="admission",
                    message=f"Skill '{skill_name}' not found",
                    retryable=False,
                    context=context,
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )
            conn = self._init_connection(skill)

        skill = next((s for s in self.skills if s.name == skill_name), None)
        timeout_class = None
        if skill is not None:
            timeout_class = skill.tool_timeout_classes.get(tool_name)
        timeout = _resolve_tool_timeout(tool_name, args, timeout_class)

        last_error = ""
        last_kind: ResultErrorKind = "transport"
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = conn.call_tool(tool_name, args, timeout=timeout)
            except (asyncio.CancelledError, concurrent.futures.CancelledError) as e:
                detail = f"{type(e).__name__}: {e}".rstrip()
                return normalizer.error(
                    tool_ref=tool_ref,
                    kind="cancelled",
                    message=f"Tool '{tool_name}' was cancelled. {detail}",
                    retryable=False,
                    context=context,
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )
            except TimeoutError as e:
                last_error = f"{type(e).__name__}: {e}".rstrip()
                last_kind = "timeout"
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}".rstrip()
                last_kind = "transport"
            else:
                try:
                    return normalizer.normalize_legacy(
                        response,
                        tool_ref=tool_ref,
                        context=context,
                        started_at=started_at,
                        completed_at=utc_now_iso(),
                    )
                except (ResultArtifactIntegrityError, OSError) as exc:
                    return normalizer.error(
                        tool_ref=tool_ref,
                        kind="artifact-integrity",
                        message=str(exc),
                        retryable=False,
                        context=context,
                        started_at=started_at,
                        completed_at=utc_now_iso(),
                    )

            logger.warning(
                "Tool '%s' attempt %d/%d failed: %s",
                tool_name,
                attempt,
                MAX_RETRIES,
                last_error,
            )
            # Reconnect in case the connection was dropped.
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

        return normalizer.error(
            tool_ref=tool_ref,
            kind=last_kind,
            message=(
                f"Tool '{tool_name}' failed after {MAX_RETRIES} attempts. "
                f"Last: {last_error}"
            ),
            retryable=True,
            context=context,
            started_at=started_at,
            completed_at=utc_now_iso(),
        )

    def _tool_admits_phase(self, tool_ref: str, phase: str) -> bool:
        skill_name = self._tool_ref_registry.get(tool_ref)
        skill = next((item for item in self.skills if item.name == skill_name), None)
        if skill is None or not _phase_matches(skill.phase, phase):
            return False
        metadata = self._tool_metadata_by_ref.get(tool_ref, {})
        policy = metadata.get("policy")
        tool_phases = (
            policy.get("phases", ["all"]) if isinstance(policy, dict) else ["all"]
        )
        return _phase_matches(tool_phases, phase)

    def _artifact_store_for_call(self) -> ArtifactStore | None:
        if self._artifact_store is not None:
            return self._artifact_store
        checkpoint_dir = os.environ.get("ARI_CHECKPOINT_DIR", "").strip()
        if not checkpoint_dir:
            return None
        if (
            self._derived_artifact_store is None
            or self._derived_artifact_store[0] != checkpoint_dir
        ):
            from ari.artifact_store import CheckpointArtifactStore

            self._derived_artifact_store = (
                checkpoint_dir,
                CheckpointArtifactStore(checkpoint_dir),
            )
        return self._derived_artifact_store[1]

    def _result_normalizer(self) -> ResultEnvelopeNormalizer:
        return ResultEnvelopeNormalizer(
            self._artifact_store_for_call(),
            inline_limit=self._result_inline_limit,
        )

    @staticmethod
    def _default_call_context(node_id: str | None = None) -> ToolCallContextV1:
        return default_call_context(node_id)

    def close_all(self) -> None:
        """Close all connections."""
        for conn in self._connections.values():
            try:
                conn.close()
            except Exception:
                pass
        self._connections.clear()

    def to_claude_mcp_config(
        self,
        phase: str | None = None,
    ) -> tuple[dict, list[str]]:
        """Render this registry for Claude CLI's native MCP interface."""

        if self._tools_cache is None:
            self._build_tools_cache()
        from ari.mcp.claude_bridge import build_claude_mcp_config

        return build_claude_mcp_config(
            skills=self.skills,
            connections=self._connections,
            visible_tools=self.list_tools(phase=phase),
            phase=phase,
        )
