"""Driver protocol for locked, RQGM-independent scientific assurance."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class HarnessDriverProtocol(Protocol):
    """A driver executes one already-resolved Harness; it never selects one."""

    def identity(self) -> dict[str, Any]: ...

    def prepare(self, manifest: Any, request: Any) -> Any: ...

    def build_request(self, manifest: Any, request: Any) -> Any: ...

    def normalize_result(self, manifest: Any, request: Any, result: Any) -> Any: ...

    def parity_probe(self, manifest: Any) -> Any: ...


__all__ = ["HarnessDriverProtocol"]
