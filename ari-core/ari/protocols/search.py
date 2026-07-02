"""SearchStrategy + NodeExecutor Protocols (subtask 011 §7-D; 006 §3.2/§3.3).

Structural contracts that separate the BFTS **search strategy** (which node to
expand / run next) from the single-node **ReAct executor** (Thought → Action →
Observation over MCP tools), so the run-loop glue
(:func:`ari.cli.bfts_loop._run_loop`) and the composition root
(:func:`ari.core.build_runtime`) can bind to abstractions rather than the
concrete ``BFTS`` / ``AgentLoop`` classes.

Both Protocols are satisfied **structurally** (no subclassing), exactly how
:class:`ari.evaluator.llm_evaluator.LLMEvaluator` satisfies
:class:`ari.protocols.evaluator.Evaluator`:

- :class:`ari.orchestrator.bfts.BFTS` already implements the
  :class:`SearchStrategy` surface (``select_next_node`` /
  ``select_best_to_expand`` / ``should_prune`` / ``expand`` / ``record_run`` /
  ``expansion_count`` / ``diversity_bonus``).
- :class:`ari.agent.loop.AgentLoop` already implements
  :meth:`NodeExecutor.run` (``run(node, experiment) -> Node``).

Introducing these Protocols changes no runtime construction and adds no new LLM
call — they are type-level seams only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ari.memory.client import MemoryClient
    from ari.orchestrator.node import Node


@runtime_checkable
class SearchStrategy(Protocol):
    """Ranking / selection policy: *which* node to run or expand next.

    Grounded in the live call sites in :func:`ari.cli.bfts_loop._run_loop`
    (``select_best_to_expand`` / ``should_prune`` / ``expand`` /
    ``select_next_node``) plus the diversity-accounting surface. Pure
    ranking/selection: no filesystem or prompt-text ownership.
    """

    def select_next_node(
        self, candidates: list[Node], experiment_goal: str, memory: MemoryClient
    ) -> Node:
        """LLM-driven pick of the next node to *run* from ``candidates``."""
        ...

    def select_best_to_expand(
        self, frontier: list[Node], experiment_goal: str, memory: MemoryClient
    ) -> Node:
        """LLM-driven pick of the completed node most worth *expanding*."""
        ...

    def should_prune(self, node: Node, *, current_total: int) -> bool:
        """Hard-cutoff pruning decision for a frontier node."""
        ...

    def expand(self, node: Node, *args, **kwargs) -> list[Node]:
        """Generate at most one child node for ``node``."""
        ...

    def record_run(self, node: Node) -> None:
        """Record that ``node`` has finished executing (diversity accounting)."""
        ...

    def expansion_count(self, node_id: str) -> int:
        """Return how many times ``node_id`` has been expanded."""
        ...

    def diversity_bonus(self, node: Node) -> float:
        """Return the additive selection bonus for an underrepresented label."""
        ...


@runtime_checkable
class NodeExecutor(Protocol):
    """Single-node ReAct executor: run one node to completion.

    Satisfied by :class:`ari.agent.loop.AgentLoop`; the run-loop submits
    ``executor.run(node, experiment)`` to a thread pool.
    """

    def run(self, node: Node, experiment: dict) -> Node:
        """Execute one node (Thought → Action → Observation) and return it."""
        ...
