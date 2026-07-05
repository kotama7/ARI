"""Protocol definitions for ARI core (REFACTORING.md §11-3).

Internal Protocols / ABCs that describe the structural contract
between core sub-systems.  Sub-systems should accept these Protocols
where possible so test stubs and alternative implementations can be
plugged in without subclassing the concrete class.

Currently exposed:

- :class:`Evaluator`        — evaluator strategy (PC6).
- :class:`BaseModelBackend` — LLM/model backend strategy (subtask 008);
  satisfied structurally by :class:`ari.llm.client.LLMClient`.
- :class:`SearchStrategy`   — BFTS ranking/selection strategy (subtask 011);
  satisfied structurally by :class:`ari.orchestrator.bfts.BFTS`.
- :class:`NodeExecutor`     — single-node ReAct executor (subtask 011);
  satisfied structurally by :class:`ari.agent.loop.AgentLoop`.
- :class:`CheckpointStore`  — checkpoint JSON I/O store (subtask 010; the
  storage member of the ``NodeStore`` roadmap entry); satisfied structurally by
  :class:`ari.checkpoint.JsonCheckpointStore`.
- :class:`TraceStore`       — execution-trace + node-report store (subtask 010);
  satisfied structurally by :class:`ari.trace_store.JsonlTraceStore`.
- :class:`ArtifactStore`    — by-logical-name artefact ABC (subtask 010);
  concrete :class:`ari.artifact_store.CheckpointArtifactStore`.
- :class:`PromptLoader` (re-exported from :mod:`ari.prompts`).
- :class:`ConfigLoader` (re-exported from :mod:`ari.configs`).

The storage stores above (subtask 010) realise the roadmap's ``NodeStore``
entry. More Protocols (MCPClient, MemoryClient, StageRunner) land in subsequent
phases when their adopters are ready.
"""

from ari.protocols.evaluator import Evaluator  # noqa: F401
from ari.protocols.model_backend import BaseModelBackend  # noqa: F401
from ari.protocols.search import NodeExecutor, SearchStrategy  # noqa: F401
from ari.protocols.stores import (  # noqa: F401
    ArtifactStore,
    CheckpointStore,
    TraceStore,
)
from ari.prompts._loader import PromptLoader  # noqa: F401
from ari.configs._loader import ConfigLoader  # noqa: F401

__all__ = [
    "Evaluator",
    "BaseModelBackend",
    "SearchStrategy",
    "NodeExecutor",
    "CheckpointStore",
    "TraceStore",
    "ArtifactStore",
    "PromptLoader",
    "ConfigLoader",
]
