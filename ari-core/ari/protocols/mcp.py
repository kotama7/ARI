"""MCPToolCaller Protocol (RQGM Task 11 §5.7, docs/plans/ari_rqgm/11).

Fulfills the deferral noted in :mod:`ari.protocols` ("More Protocols
(MCPClient, ...) land in subsequent phases when their adopters are ready"):
the first adopters are the RQGM tool-surface proxies —
:class:`ari.rqgm.kernel.CapabilityGatedMCPClient` (Task 04) and
:class:`ari.rqgm.meta_evolution.MetaSandboxMCPProxy` (Task 11) — which wrap
:class:`ari.mcp.client.MCPClient` behind the same duck-type.

Purely structural: no call site changes, no ``isinstance`` requirement
(consumers assert the surface duck-typed, per the contract-snapshot
robustness convention), and deliberately minimal — only the members callers
actually read (``tool_manager`` also reads ``_COW_TOOLS``).
"""

from __future__ import annotations

from typing import Any, Protocol


class MCPToolCaller(Protocol):
    """The caller-facing surface of ``MCPClient`` and its proxies."""

    @property
    def _COW_TOOLS(self) -> frozenset:  # noqa: N802 - MCPClient attribute
        """Tools whose results are copy-on-write per node."""
        ...

    def list_tools(self, phase: "str | None" = None) -> "list[dict]":
        """Tool definitions available for *phase* (``None`` == all)."""
        ...

    def call_tool(
        self, tool_name: str, args: dict, *, cow_node_id: "str | None" = None
    ) -> dict:
        """Dispatch one tool call; always the ``{"result"}|{"error"}``
        envelope, never an exception for a denied/unknown tool."""
        ...

    def to_claude_mcp_config(self, *args: Any, **kwargs: Any) -> dict:
        """The ``mcpServers`` config block for Claude-driven skills."""
        ...

    def close_all(self) -> None:
        """Shut down owned server connections."""
        ...
