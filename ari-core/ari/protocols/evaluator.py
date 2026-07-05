"""Evaluator Protocol (Phase PC6 — REFACTORING.md §11-3 / evaluator §3 Step 2).

Describes the structural contract any evaluator must satisfy so that
:class:`AgentLoop` and the BFTS orchestrator can swap in alternative
implementations (e.g. regex-only extractor for tests, peer-review
LLM for real runs) without inheriting from the concrete class.

The current canonical implementation is
:class:`ari.evaluator.llm_evaluator.LLMEvaluator`; this Protocol is
satisfied structurally so existing callers keep working.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Evaluator(Protocol):
    """Extract metrics + scores from a completed node's artifacts.

    The canonical implementation
    (:class:`ari.evaluator.llm_evaluator.LLMEvaluator`) is async and
    keyword-driven; the Protocol matches that shape.  An alternative
    implementation may use regex, table lookup, or another LLM —
    callers should treat the return dict as the contract.

    The contract covers the **actual** runtime surface callers rely on
    (subtask 009): the async :meth:`evaluate`, the synchronous
    :meth:`evaluate_sync` entry point that :class:`ari.agent.loop.AgentLoop`
    invokes, and the mutable :attr:`metric_spec` attribute (a
    ``MetricSpec``; typed ``Any`` here to keep ``ari.protocols`` free of an
    ``ari.evaluator`` import). ``runtime_checkable`` matches instances
    structurally, so ``LLMEvaluator`` satisfies this with no subclassing.
    """

    #: Mutable metric specification the evaluator scores against (a
    #: ``ari.evaluator...MetricSpec``); present on every instance.
    metric_spec: Any

    async def evaluate(
        self,
        goal: str,
        artifacts: list[dict],
        summary: str,
        node_id: str | None = None,
        node_label: str | None = None,
    ) -> dict[str, Any]:
        """Return ``{"score", "reason", "has_real_data",
        "has_paper_section", "metrics", ...}`` for a finished node.
        """
        ...

    def evaluate_sync(
        self,
        goal: str,
        artifacts: list[dict],
        summary: str,
        node_id: str | None = None,
        node_label: str | None = None,
    ) -> dict[str, Any]:
        """Synchronous counterpart of :meth:`evaluate` (called from
        ``AgentLoop``); returns the same result dict.
        """
        ...
