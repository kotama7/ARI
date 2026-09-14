"""Provider adapters for catalog sync and immutable leaf invocation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import re
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Protocol

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models import (
    ProviderAsyncLifecycleV1,
    canonical_json,
    credential_field_paths,
    sanitize_text,
    sha256_digest,
)


STDIO_ADAPTER_ID = "ari.stdio-mcp"
STDIO_ADAPTER_VERSION = "1.0.0"
_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_PYTHON_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_CREDENTIAL_RE = re.compile(
    r"(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|PRIVATE_?KEY|CREDENTIAL)",
    re.IGNORECASE,
)
_SAFE_PARENT_ENV = (
    "LANG",
    "LC_ALL",
    "PATH",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
)


class ProviderAdapterError(RuntimeError):
    """Base class for provider startup, transport, and protocol failures."""


class ProviderLaunchError(ProviderAdapterError):
    pass


class ProviderProtocolError(ProviderAdapterError):
    pass


class ProviderDriftError(ProviderAdapterError):
    pass


class PythonStdioLauncherV1(BaseModel):
    """Shell-free, digest-bound Python MCP launcher."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command_kind: str = "python"
    python_executable: str
    package_root: str
    entrypoint: str | None = None
    python_module: str | None = None
    python_callable: str | None = None
    arguments: list[str] = Field(default_factory=list, max_length=64)
    literal_env: dict[str, str] = Field(default_factory=dict)
    expected_architecture: str = ""
    identity_globs: list[str] = Field(
        default_factory=lambda: [
            "**/*.py",
            "pyproject.toml",
            "requirements*.txt",
            "*.lock",
        ],
        max_length=64,
    )

    @field_validator("command_kind")
    @classmethod
    def _python_only(cls, value: str) -> str:
        if value != "python":
            raise ValueError("generic stdio sources support command_kind=python only")
        return value

    @field_validator("arguments")
    @classmethod
    def _safe_arguments(cls, values: list[str]) -> list[str]:
        for value in values:
            if "\x00" in value or "\n" in value or "\r" in value:
                raise ValueError("launcher arguments cannot contain controls")
            if len(value) > 4_096:
                raise ValueError("launcher argument exceeds 4096 characters")
        return values

    @field_validator("identity_globs")
    @classmethod
    def _safe_identity_globs(cls, values: list[str]) -> list[str]:
        normalized = sorted(set(values))
        for value in normalized:
            path = Path(value)
            if not value or path.is_absolute() or ".." in path.parts:
                raise ValueError("identity_globs must stay within package_root")
        required = {"**/*.py", "pyproject.toml", "requirements*.txt", "*.lock"}
        missing = sorted(required - set(normalized))
        if missing:
            raise ValueError(
                "identity_globs cannot weaken the provider source/dependency "
                f"closure; missing {missing}"
            )
        return normalized

    @field_validator("literal_env")
    @classmethod
    def _safe_literal_environment(cls, value: dict[str, str]) -> dict[str, str]:
        for name, content in value.items():
            if not _ENV_NAME_RE.fullmatch(name):
                raise ValueError(f"invalid literal environment name: {name}")
            if _CREDENTIAL_RE.search(name):
                raise ValueError(
                    f"credentials cannot be embedded in source metadata: {name}"
                )
            if "\x00" in content:
                raise ValueError(f"literal environment value contains NUL: {name}")
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def _safe_paths(self) -> "PythonStdioLauncherV1":
        root = Path(self.package_root)
        executable = Path(self.python_executable)
        if not root.is_absolute() or not executable.is_absolute():
            raise ValueError("python_executable and package_root must be absolute")
        if (self.entrypoint is None) == (self.python_module is None):
            raise ValueError("exactly one of entrypoint or python_module is required")
        if self.entrypoint is not None:
            relative = Path(self.entrypoint)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("entrypoint must be safe and package-relative")
        if self.python_module is not None and not _PYTHON_MODULE_RE.fullmatch(
            self.python_module
        ):
            raise ValueError("python_module must be a safe dotted Python module")
        if self.python_callable is not None:
            if self.python_module is None or not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*", self.python_callable
            ):
                raise ValueError(
                    "python_callable requires a module and a safe function name"
                )
        return self

    def resolve(self, *, require_exists: bool = True) -> tuple[Path, Path, Path]:
        root = Path(self.package_root).resolve()
        # Preserve a virtual-environment launcher path.  Resolving its symlink to
        # the base interpreter would bypass ``pyvenv.cfg`` and silently execute
        # outside the pinned provider environment.
        executable = Path(os.path.abspath(self.python_executable))
        if self.entrypoint is not None:
            entrypoint = (root / self.entrypoint).resolve()
        else:
            assert self.python_module is not None
            parts = self.python_module.split(".")
            if parts[0] == root.name:
                parts = parts[1:]
            module_path = root.joinpath(*parts)
            if not parts:
                file_candidate = root / "__init__.py"
                package_candidate = root / "__main__.py"
            else:
                file_candidate = module_path.with_suffix(".py")
                package_candidate = module_path / "__main__.py"
            matches = [
                candidate
                for candidate in (file_candidate, package_candidate)
                if candidate.is_file()
            ]
            if len(matches) > 1:
                if not parts and self.python_callable is not None:
                    entrypoint = file_candidate.resolve()
                elif not parts and self.python_callable is None:
                    entrypoint = package_candidate.resolve()
                else:
                    raise ProviderLaunchError(
                        "python_module resolves to both a module and a package"
                    )
            else:
                entrypoint = (matches[0] if matches else file_candidate).resolve()
        try:
            entrypoint.relative_to(root)
        except ValueError as exc:
            raise ProviderLaunchError(
                "provider entrypoint escapes package root"
            ) from exc
        if require_exists:
            if not executable.is_file():
                raise ProviderLaunchError(
                    f"provider Python interpreter does not exist: {executable}"
                )
            if not entrypoint.is_file():
                raise ProviderLaunchError(
                    f"provider entrypoint does not exist: {entrypoint}"
                )
        return root, executable, entrypoint

    def command_arguments(self, resolved_entrypoint: Path) -> list[str]:
        if self.python_callable is not None:
            assert self.python_module is not None
            code = (
                f"from {self.python_module} import {self.python_callable} as "
                "_ari_entry; _ari_entry()"
            )
            return ["-c", code, *self.arguments]
        if self.python_module is not None:
            return ["-m", self.python_module, *self.arguments]
        return [str(resolved_entrypoint), *self.arguments]

    def working_directory(self, root: Path) -> Path:
        if (
            self.python_module is not None
            and self.python_module.split(".")[0] == root.name
        ):
            return root.parent
        return root


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
    except OSError as exc:
        raise ProviderLaunchError(f"cannot digest provider file {path}: {exc}") from exc
    return f"sha256:{hasher.hexdigest()}"


def launcher_identity(launcher: PythonStdioLauncherV1) -> dict[str, Any]:
    root, executable, entrypoint = launcher.resolve()
    closure_paths: set[Path] = {entrypoint}
    for pattern in launcher.identity_globs:
        closure_paths.update(
            path
            for path in root.glob(pattern)
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        )
    if len(closure_paths) > 50_000:
        raise ProviderLaunchError("provider identity closure exceeds 50,000 files")
    package_files: list[dict[str, Any]] = []
    total_bytes = 0
    for path in sorted(closure_paths, key=lambda item: item.as_posix()):
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise ProviderLaunchError(
                f"provider identity file escapes package root: {path}"
            ) from exc
        size = resolved.stat().st_size
        if size > 50_000_000:
            raise ProviderLaunchError(
                f"provider identity file exceeds 50 MB: {relative}"
            )
        total_bytes += size
        if total_bytes > 500_000_000:
            raise ProviderLaunchError("provider identity closure exceeds 500 MB")
        package_files.append(
            {
                "path": relative.as_posix(),
                "size": size,
                "digest": _file_digest(resolved),
            }
        )
    identity = {
        "command_kind": launcher.command_kind,
        "python_executable": str(executable),
        "python_resolved_executable": str(executable.resolve()),
        "python_digest": _file_digest(executable),
        "package_root": str(root),
        "package_files": package_files,
        "arguments": launcher.arguments,
        "literal_env": launcher.literal_env,
        "expected_architecture": launcher.expected_architecture,
        "identity_globs": launcher.identity_globs,
    }
    if launcher.python_module is not None:
        identity["python_module"] = launcher.python_module
        identity["module_entrypoint"] = entrypoint.relative_to(root).as_posix()
        identity["python_callable"] = launcher.python_callable
    else:
        identity["entrypoint"] = entrypoint.relative_to(root).as_posix()
    return identity


def provider_digest(launcher: PythonStdioLauncherV1) -> str:
    return sha256_digest(launcher_identity(launcher))


def stdio_adapter_digest() -> str:
    return sha256_digest(
        {
            "adapter_source": _file_digest(Path(__file__).resolve()),
            "process_group_proxy": _file_digest(
                Path(__file__).resolve().with_name("stdio_process_proxy.py")
            ),
        }
    )


class ProviderToolV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    title: str = ""
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    annotations: dict[str, Any] = Field(default_factory=dict)

    @field_validator("description")
    @classmethod
    def _clean_description(cls, value: str) -> str:
        return sanitize_text(value)

    @field_validator("annotations")
    @classmethod
    def _safe_annotations(cls, value: dict[str, Any]) -> dict[str, Any]:
        paths = credential_field_paths(value, "tool_metadata")
        if paths:
            raise ValueError(
                f"provider tool metadata contains credential fields: {paths}"
            )
        if len(canonical_json(value).encode("utf-8")) > 65_536:
            raise ValueError("provider tool metadata exceeds 64 KiB")
        return value


class ProviderResponseV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = ""
    structured: dict[str, Any] | None = None
    is_error: bool = False


class ProviderAdapter(Protocol):
    async def list_tools(self) -> list[ProviderToolV1]: ...

    async def invoke(
        self, name: str, arguments: dict[str, Any]
    ) -> ProviderResponseV1: ...

    async def get_status(
        self,
        lifecycle: ProviderAsyncLifecycleV1,
        provider_handle: str,
    ) -> ProviderResponseV1: ...

    async def get_result(
        self,
        lifecycle: ProviderAsyncLifecycleV1,
        provider_handle: str,
    ) -> ProviderResponseV1: ...

    async def cancel(
        self,
        lifecycle: ProviderAsyncLifecycleV1,
        provider_handle: str,
    ) -> ProviderResponseV1: ...


class StdioMCPAdapter:
    """Official MCP-session adapter with bounded pagination and diagnostics."""

    def __init__(
        self,
        launcher: PythonStdioLauncherV1,
        *,
        expected_provider_digest: str,
        credential_env_values: dict[str, str] | None = None,
        timeout_seconds: float = 30.0,
        max_pages: int = 1_000,
        max_tools: int = 100_000,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.launcher = launcher
        self.expected_provider_digest = expected_provider_digest
        normalized_credentials = dict(sorted((credential_env_values or {}).items()))
        if any(
            not _ENV_NAME_RE.fullmatch(name)
            or not _CREDENTIAL_RE.search(name)
            or not isinstance(value, str)
            or len(value) < 8
            for name, value in normalized_credentials.items()
        ):
            raise ValueError(
                "credential_env_values must contain credential-shaped names and "
                "values of at least eight characters"
            )
        self.credential_env_values = normalized_credentials
        self.timeout_seconds = timeout_seconds
        self.max_pages = max_pages
        self.max_tools = max_tools

    def verify_provider(self) -> None:
        actual = provider_digest(self.launcher)
        if actual != self.expected_provider_digest:
            raise ProviderDriftError(
                f"provider digest drift: expected {self.expected_provider_digest}, got {actual}"
            )

    def _environment(self, isolated_home: Path) -> dict[str, str]:
        environment = {
            "HOME": str(isolated_home),
            "LOGNAME": "ari-provider",
            "USER": "ari-provider",
            "SHELL": "",
            "TERM": "dumb",
            "XDG_CACHE_HOME": str(isolated_home / ".cache"),
            "XDG_CONFIG_HOME": str(isolated_home / ".config"),
            "XDG_DATA_HOME": str(isolated_home / ".local" / "share"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        }
        for name in _SAFE_PARENT_ENV:
            value = os.environ.get(name)
            if value:
                environment[name] = value
        environment.update(self.credential_env_values)
        environment.update(self.launcher.literal_env)
        return environment

    def _credential_values(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    value for value in self.credential_env_values.values()
                },
                key=len,
                reverse=True,
            )
        )

    def _redact_text(self, value: str) -> str:
        for secret in self._credential_values():
            value = value.replace(secret, "[REDACTED]")
        return value

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._redact_text(value)
        if isinstance(value, dict):
            return {
                self._redact_text(str(key)): self._redact_value(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        if isinstance(value, tuple):
            return [self._redact_value(item) for item in value]
        return value

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[ClientSession]:
        self.verify_provider()
        root, executable, entrypoint = self.launcher.resolve()
        if (
            self.launcher.expected_architecture
            and self.launcher.expected_architecture != platform.machine()
        ):
            raise ProviderLaunchError(
                "launcher architecture mismatch: "
                f"expected {self.launcher.expected_architecture}, "
                f"runtime {platform.machine()}"
            )
        with tempfile.TemporaryDirectory(prefix="ari-provider-home-") as home_text:
            home = Path(home_text)
            with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errlog:
                environment = self._environment(home)
                proxy_spec = canonical_json(
                    {
                        "command": str(executable),
                        "arguments": self.launcher.command_arguments(entrypoint),
                        "cwd": str(self.launcher.working_directory(root)),
                        "env_names": sorted(environment),
                    }
                )
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=[
                        str(
                            Path(__file__)
                            .resolve()
                            .with_name("stdio_process_proxy.py")
                        ),
                        "--spec",
                        proxy_spec,
                    ],
                    env=environment,
                    cwd=Path(__file__).resolve().parent,
                )
                operation_failure: ProviderAdapterError | None = None
                try:
                    async with stdio_client(parameters, errlog=errlog) as streams:
                        async with ClientSession(*streams) as session:
                            startup_timeout = max(
                                10.0, min(self.timeout_seconds, 60.0)
                            )
                            async with asyncio.timeout(startup_timeout):
                                await session.initialize()
                            # The session itself may intentionally outlive one
                            # provider call (for example, a stateful EDA run).
                            # Individual calls remain bounded in
                            # ``_call_in_session``; this timeout covers startup
                            # only instead of silently killing a healthy
                            # long-running connection.
                            try:
                                yield session
                            except ProviderAdapterError as exc:
                                # Let both MCP contexts close normally before
                                # re-raising the primary operation error.  If an
                                # operation timeout escapes through the SDK
                                # task group, its stream-shutdown error can
                                # otherwise mask the fail-closed timeout.
                                operation_failure = exc
                except ProviderAdapterError:
                    raise
                except Exception as exc:
                    if operation_failure is not None:
                        raise operation_failure from exc
                    errlog.seek(0)
                    diagnostic = self._redact_text(
                        sanitize_text(errlog.read(), limit=2_000)
                    )
                    message = self._redact_text(
                        f"stdio MCP provider failed: {type(exc).__name__}: {exc}"
                    )
                    if diagnostic:
                        message += f"; stderr={diagnostic}"
                    if isinstance(exc, (OSError, FileNotFoundError)):
                        raise ProviderLaunchError(message) from exc
                    raise ProviderProtocolError(message) from exc
                if operation_failure is not None:
                    raise operation_failure

    async def list_tools(self) -> list[ProviderToolV1]:
        tools: list[ProviderToolV1] = []
        seen_names: set[str] = set()
        cursor: str | None = None
        visited: set[str] = set()
        async with self._session() as session:
            for _page in range(self.max_pages):
                result = await session.list_tools(cursor=cursor)
                for tool in result.tools:
                    annotations = getattr(tool, "annotations", None)
                    if isinstance(annotations, BaseModel):
                        annotations = annotations.model_dump(
                            mode="json", exclude_none=True
                        )
                    if not isinstance(annotations, dict):
                        annotations = {}
                    metadata = getattr(tool, "meta", None)
                    if isinstance(metadata, BaseModel):
                        metadata = metadata.model_dump(mode="json", exclude_none=True)
                    if not isinstance(metadata, dict):
                        metadata = {}
                    conflicts = sorted(
                        key
                        for key in set(metadata) & set(annotations)
                        if metadata[key] != annotations[key]
                    )
                    if conflicts:
                        raise ProviderProtocolError(
                            "provider tool metadata conflicts with annotations: "
                            f"{conflicts}"
                        )
                    merged_annotations = {**metadata, **annotations}
                    if tool.name in seen_names:
                        raise ProviderProtocolError(
                            f"provider returned duplicate tool name: {tool.name}"
                        )
                    seen_names.add(tool.name)
                    tools.append(
                        ProviderToolV1(
                            name=tool.name,
                            title=getattr(tool, "title", None) or "",
                            description=tool.description or "",
                            input_schema=tool.inputSchema or {},
                            output_schema=tool.outputSchema or {},
                            annotations=merged_annotations,
                        )
                    )
                    if len(tools) > self.max_tools:
                        raise ProviderProtocolError(
                            f"provider exceeds max_tools={self.max_tools}"
                        )
                next_cursor = result.nextCursor
                if not next_cursor:
                    return tools
                if next_cursor in visited:
                    raise ProviderProtocolError("provider returned a cursor cycle")
                visited.add(next_cursor)
                cursor = next_cursor
        raise ProviderProtocolError(f"provider exceeds max_pages={self.max_pages}")

    async def _call_in_session(
        self,
        session: ClientSession,
        name: str,
        arguments: dict[str, Any],
    ) -> ProviderResponseV1:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await session.call_tool(name, arguments)
        except TimeoutError as exc:
            raise ProviderProtocolError(f"provider call timed out: {name}") from exc
        text_parts = [part.text for part in result.content if hasattr(part, "text")]
        text = self._redact_text("\n".join(text_parts))
        structured = getattr(result, "structuredContent", None)
        if not isinstance(structured, dict):
            structured = None
        else:
            structured = self._redact_value(structured)
        if not text and structured is not None:
            text = json.dumps(structured, ensure_ascii=False, sort_keys=True)
        if not text:
            raise ProviderProtocolError(f"provider returned an empty response: {name}")
        return ProviderResponseV1(
            text=text,
            structured=structured,
            is_error=bool(getattr(result, "isError", False)),
        )

    async def _call(self, name: str, arguments: dict[str, Any]) -> ProviderResponseV1:
        async with self._session() as session:
            return await self._call_in_session(session, name, arguments)

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[ProviderAdapter]:
        """Keep one verified provider process for a bounded call sequence."""

        async with self._session() as session:
            yield _ConnectedStdioMCPAdapter(self, session)

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ProviderResponseV1:
        return await self._call(name, arguments)

    async def _lifecycle_call(
        self,
        tool_name: str | None,
        lifecycle: ProviderAsyncLifecycleV1,
        provider_handle: str,
    ) -> ProviderResponseV1:
        if tool_name is None:
            raise ProviderProtocolError("provider lifecycle operation is not declared")
        return await self._call(
            tool_name,
            {lifecycle.handle_argument: provider_handle},
        )

    async def get_status(
        self,
        lifecycle: ProviderAsyncLifecycleV1,
        provider_handle: str,
    ) -> ProviderResponseV1:
        return await self._lifecycle_call(
            lifecycle.status_tool, lifecycle, provider_handle
        )

    async def get_result(
        self,
        lifecycle: ProviderAsyncLifecycleV1,
        provider_handle: str,
    ) -> ProviderResponseV1:
        return await self._lifecycle_call(
            lifecycle.result_tool or lifecycle.status_tool,
            lifecycle,
            provider_handle,
        )

    async def cancel(
        self,
        lifecycle: ProviderAsyncLifecycleV1,
        provider_handle: str,
    ) -> ProviderResponseV1:
        return await self._lifecycle_call(
            lifecycle.cancel_tool, lifecycle, provider_handle
        )


class _ConnectedStdioMCPAdapter:
    """One already-initialized session; created only by ``connection``."""

    def __init__(self, owner: StdioMCPAdapter, session: ClientSession) -> None:
        self.owner = owner
        self.session = session

    async def list_tools(self) -> list[ProviderToolV1]:
        raise ProviderProtocolError("connected collection sessions use compact calls")

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ProviderResponseV1:
        return await self.owner._call_in_session(self.session, name, arguments)

    async def get_status(
        self,
        lifecycle: ProviderAsyncLifecycleV1,
        provider_handle: str,
    ) -> ProviderResponseV1:
        return await self.invoke(
            lifecycle.status_tool,
            {lifecycle.handle_argument: provider_handle},
        )

    async def get_result(
        self,
        lifecycle: ProviderAsyncLifecycleV1,
        provider_handle: str,
    ) -> ProviderResponseV1:
        return await self.invoke(
            lifecycle.result_tool or lifecycle.status_tool,
            {lifecycle.handle_argument: provider_handle},
        )

    async def cancel(
        self,
        lifecycle: ProviderAsyncLifecycleV1,
        provider_handle: str,
    ) -> ProviderResponseV1:
        if lifecycle.cancel_tool is None:
            raise ProviderProtocolError("provider lifecycle has no cancel tool")
        return await self.invoke(
            lifecycle.cancel_tool,
            {lifecycle.handle_argument: provider_handle},
        )


class StaticProviderAdapter:
    """Explicitly injected conformance fixture; never production-registered."""

    def __init__(
        self,
        tools: list[ProviderToolV1],
        responses: dict[str, ProviderResponseV1] | None = None,
    ) -> None:
        self._tools = list(tools)
        self.responses = dict(responses or {})
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[ProviderToolV1]:
        return list(self._tools)

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ProviderResponseV1:
        self.calls.append((name, dict(arguments)))
        response = self.responses.get(name)
        if response is None:
            return ProviderResponseV1(
                text=json.dumps({"tool": name, "arguments": arguments}, sort_keys=True),
                structured={"tool": name, "arguments": arguments},
            )
        return response

    async def get_status(
        self,
        lifecycle: ProviderAsyncLifecycleV1,
        provider_handle: str,
    ) -> ProviderResponseV1:
        return await self.invoke(
            lifecycle.status_tool, {lifecycle.handle_argument: provider_handle}
        )

    async def get_result(
        self,
        lifecycle: ProviderAsyncLifecycleV1,
        provider_handle: str,
    ) -> ProviderResponseV1:
        return await self.invoke(
            lifecycle.result_tool or lifecycle.status_tool,
            {lifecycle.handle_argument: provider_handle},
        )

    async def cancel(
        self,
        lifecycle: ProviderAsyncLifecycleV1,
        provider_handle: str,
    ) -> ProviderResponseV1:
        if lifecycle.cancel_tool is None:
            raise ProviderProtocolError("provider lifecycle has no cancel tool")
        return await self.invoke(
            lifecycle.cancel_tool,
            {lifecycle.handle_argument: provider_handle},
        )


__all__ = [
    "ProviderAdapter",
    "ProviderAdapterError",
    "ProviderDriftError",
    "ProviderLaunchError",
    "ProviderProtocolError",
    "ProviderResponseV1",
    "ProviderToolV1",
    "PythonStdioLauncherV1",
    "STDIO_ADAPTER_ID",
    "STDIO_ADAPTER_VERSION",
    "StaticProviderAdapter",
    "StdioMCPAdapter",
    "launcher_identity",
    "provider_digest",
    "stdio_adapter_digest",
]
