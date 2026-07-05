"""BaseModelBackend Protocol (Phase 3 — subtask 008; 006_target_architecture_plan §3).

Describes the structural contract any LLM/model backend must satisfy so that
callers (:class:`ari.agent.loop.AgentLoop`, the BFTS orchestrator,
:mod:`ari.agent.react_driver`, and the viz launch paths) can swap in alternative
backends without inheriting from the concrete class.

The current canonical implementation is :class:`ari.llm.client.LLMClient`
(also exposed as the naming alias :data:`ari.llm.LiteLLMBackend`); this Protocol
is satisfied *structurally* — exactly how
:class:`ari.evaluator.llm_evaluator.LLMEvaluator` satisfies
:class:`ari.protocols.evaluator.Evaluator` — so existing callers keep working
with no subclassing and no change to the public ``LLMClient(config)`` surface.

An implementation may also expose an injected ``mcp_client`` attribute (set
post-construction at ``ari/core.py``); it is documented here but intentionally
*not* a typed Protocol field, to keep the ``runtime_checkable`` structural check
lenient (mirroring the ``Evaluator`` precedent, which types only the method).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, Protocol, runtime_checkable

if TYPE_CHECKING:  # avoid any import cycle; annotations are lazy strings
    from ari.llm.client import LLMMessage, LLMResponse


@runtime_checkable
class BaseModelBackend(Protocol):
    """Minimal structural contract callers rely on, grounded in live call sites.

    Callers treat :class:`ari.llm.client.LLMResponse` as the return contract.
    ``complete`` is the sole method invoked by ``react_driver``/``agent/loop``/
    ``orchestrator/bfts``/``viz``; ``set_context`` attaches per-node metadata;
    ``stream`` is included for completeness (no in-tree caller today).
    """

    def complete(
        self,
        messages: list[LLMMessage] | list[dict],
        tools: list[dict] | None = None,
        require_tool: bool = True,
        *,
        node_id: str | None = None,
        phase: str | None = None,
        skill: str | None = None,
        work_dir: str | None = None,
    ) -> LLMResponse:
        """Send messages to the model and return the response envelope."""
        ...

    def set_context(
        self,
        *,
        node_id: str | None = None,
        phase: str | None = None,
        skill: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        """Attach context forwarded as metadata on subsequent ``complete`` calls."""
        ...

    def stream(self, messages: list[LLMMessage]) -> Iterator[str]:
        """Optional: yield text chunks. Not every backend implements streaming."""
        ...
