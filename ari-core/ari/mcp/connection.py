"""Lifecycle and transport for one isolated MCP Skill subprocess."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ari.call_context import (
    CALL_CONTEXT_ARGUMENT,
    CONTEXT_AUTHORITY_ENV,
    ToolCallContextV1,
    authorize_tool_context,
    new_context_authority_key,
)
from ari.config import SkillConfig
from ari.mcp.child_environment import (
    ChildEnvironment,
    CredentialScopeDriftError,
    SecretRedactingPipe,
    build_child_environment,
)
from ari.mcp.dispatch_support import DEFAULT_TOOL_TIMEOUT


class SkillConnection:
    """Persistent, thread-safe connection to one MCP Skill server."""

    def __init__(
        self,
        skill: SkillConfig,
        *,
        context_authority_key: str | None = None,
    ) -> None:
        self.skill = skill
        self._context_authority_key = (
            context_authority_key or new_context_authority_key()
        )
        self._session: ClientSession | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._context_stack: Any = None
        self._child_environment: ChildEnvironment | None = None
        self._stderr_pipe: SecretRedactingPipe | None = None
        self._server_parameters: StdioServerParameters | None = None
        self._expected_credential_scopes = tuple(
            dict(identity) for identity in skill.credential_scope_identities
        )

    def _skill_path(self) -> Path:
        import os

        path = self.skill.path
        ari_root = os.environ.get("ARI_ROOT", str(Path(__file__).parents[3]))
        path = path.replace("{{ari_root}}", ari_root)
        return Path(path)

    @staticmethod
    def _resolve_python(skill_path: Path) -> str:
        """Return the skill-local, setup-recorded, or current interpreter."""

        skill_python = skill_path / ".venv" / "bin" / "python"
        if skill_python.is_file():
            return str(skill_python)

        import os

        ari_root = os.environ.get("ARI_ROOT", str(Path(__file__).parents[3]))
        marker = Path(ari_root) / ".ari_python"
        if marker.is_file():
            recorded = marker.read_text(encoding="utf-8").strip()
            if recorded and Path(recorded).is_file():
                return recorded
        return sys.executable

    def _server_params(self) -> StdioServerParameters:
        if self._server_parameters is not None:
            return self._server_parameters
        skill_path = self._skill_path()
        child_environment = build_child_environment(
            self.skill,
            skill_path=skill_path,
            ari_core_root=Path(__file__).parents[2],
        )
        child_environment = child_environment.with_core_secret(
            CONTEXT_AUTHORITY_ENV,
            self._context_authority_key,
            marker="<redacted:core.call-context-authority>",
        )
        resolved_scopes = tuple(
            dict(identity)
            for identity in child_environment.credential_scope_identities
        )
        if (
            self._expected_credential_scopes
            and resolved_scopes != self._expected_credential_scopes
        ):
            raise CredentialScopeDriftError(
                f"Skill '{self.skill.name}' credential authority changed during run"
            )
        self._child_environment = child_environment
        self.skill.credential_scope_identities = [
            dict(identity) for identity in resolved_scopes
        ]
        self._server_parameters = StdioServerParameters(
            command=self._resolve_python(skill_path),
            args=[str(skill_path / self.skill.entrypoint)],
            env=dict(child_environment.values),
        )
        return self._server_parameters

    @property
    def child_environment(self) -> ChildEnvironment:
        """Return the environment resolved by the latest parameter build."""

        if self._child_environment is None:
            self._server_params()
        assert self._child_environment is not None
        return self._child_environment

    def redact_text(self, value: str) -> str:
        if self._child_environment is None:
            return value
        return self._child_environment.redactor.text(value)

    async def _start(self) -> None:
        import contextlib

        stack = contextlib.AsyncExitStack()
        params = self._server_params()
        assert self._child_environment is not None
        stderr_pipe = SecretRedactingPipe(
            sys.stderr,
            self._child_environment.redactor,
        )
        try:
            read, write = await stack.enter_async_context(
                stdio_client(params, errlog=stderr_pipe.child_writer)
            )
        except BaseException:
            stderr_pipe.close()
            raise
        stderr_pipe.close_parent_writer()
        try:
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except BaseException:
            await stack.aclose()
            stderr_pipe.close()
            raise
        self._session = session
        self._context_stack = stack
        self._stderr_pipe = stderr_pipe

    async def _stop(self) -> None:
        if self._context_stack is not None:
            try:
                await self._context_stack.aclose()
            except Exception:
                pass
            self._context_stack = None
            self._session = None
        if self._stderr_pipe is not None:
            self._stderr_pipe.close()
            self._stderr_pipe = None

    def _ensure_loop(self) -> None:
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
        """Submit a coroutine to the connection's dedicated event loop."""

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
            assert self._child_environment is not None
            result = await self._session.list_tools()
            return [
                {
                    "name": tool.name,
                    "description": self._child_environment.redactor.text(
                        tool.description or ""
                    ),
                    "inputSchema": _public_input_schema(
                        self._child_environment.redactor.value(
                            tool.inputSchema if tool.inputSchema else {}
                        )
                    ),
                    "outputSchema": self._child_environment.redactor.value(
                        tool.outputSchema if tool.outputSchema else {}
                    ),
                    "skill_name": self.skill.name,
                }
                for tool in result.tools
            ]

        return self._run(_list())

    def authorize_args(
        self,
        tool_name: str,
        args: dict,
        context: ToolCallContextV1,
    ) -> dict:
        """Inject a signed, connection-scoped context capability."""

        authorized = dict(args)
        authorized[CALL_CONTEXT_ARGUMENT] = authorize_tool_context(
            context,
            tool_name=tool_name,
            authority_key=self._context_authority_key,
        )
        return authorized

    def call_tool(
        self, tool_name: str, args: dict, timeout: int = DEFAULT_TOOL_TIMEOUT
    ) -> dict:
        self.ensure_connected()

        async def _call() -> dict:
            assert self._session is not None
            result = await self._session.call_tool(tool_name, args)
            parts = [part.text for part in result.content if hasattr(part, "text")]
            rendered = "\n".join(parts) if parts else ""
            structured = getattr(result, "structuredContent", None)
            if not isinstance(structured, dict):
                structured = None
            assert self._child_environment is not None
            rendered = self._child_environment.redactor.text(rendered)
            structured = self._child_environment.redactor.value(structured)
            if not rendered and structured:
                rendered = json.dumps(structured, ensure_ascii=False)
            if not rendered:
                return {
                    "error": (
                        f"Tool '{tool_name}' returned empty response — the tool "
                        "may have crashed or timed out."
                    ),
                    "_error_kind": "protocol",
                    "_retryable": True,
                }
            return {
                "result": rendered,
                "_structured_content": structured,
                "_mcp_is_error": bool(getattr(result, "isError", False)),
            }

        return self._run(_call(), timeout=timeout)

    def close(self) -> None:
        if self._loop and not self._loop.is_closed():
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


__all__ = ["SkillConnection"]


def _public_input_schema(schema: Any) -> Any:
    """Hide the transport-managed context argument from model-facing schemas."""

    if not isinstance(schema, dict):
        return schema
    rendered = dict(schema)
    properties = rendered.get("properties")
    if isinstance(properties, dict) and CALL_CONTEXT_ARGUMENT in properties:
        rendered["properties"] = {
            name: value
            for name, value in properties.items()
            if name != CALL_CONTEXT_ARGUMENT
        }
    required = rendered.get("required")
    if isinstance(required, list):
        kept = [name for name in required if name != CALL_CONTEXT_ARGUMENT]
        if kept:
            rendered["required"] = kept
        else:
            rendered.pop("required", None)
    return rendered
