"""Minimal protocol boundary between Provider discovery and binding."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CapabilityProviderProtocol(Protocol):
    """Existing Provider transport surface; MCP is one implementation."""

    def list_tools(self) -> list[dict[str, Any]]: ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...

    def close(self) -> None: ...


__all__ = ["CapabilityProviderProtocol"]
