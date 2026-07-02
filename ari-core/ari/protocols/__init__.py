"""Protocol definitions for ARI core (REFACTORING.md §11-3).

Internal Protocols / ABCs that describe the structural contract
between core sub-systems.  Sub-systems should accept these Protocols
where possible so test stubs and alternative implementations can be
plugged in without subclassing the concrete class.

Currently exposed:

- :class:`Evaluator`        — evaluator strategy (PC6).
- :class:`BaseModelBackend` — LLM/model backend strategy (subtask 008);
  satisfied structurally by :class:`ari.llm.client.LLMClient`.
- :class:`PromptLoader` (re-exported from :mod:`ari.prompts`).
- :class:`ConfigLoader` (re-exported from :mod:`ari.configs`).

More Protocols (MCPClient, MemoryClient, NodeStore, StageRunner) land in
subsequent phases when their adopters are ready.
"""

from ari.protocols.evaluator import Evaluator  # noqa: F401
from ari.protocols.model_backend import BaseModelBackend  # noqa: F401
from ari.prompts._loader import PromptLoader  # noqa: F401
from ari.configs._loader import ConfigLoader  # noqa: F401

__all__ = ["Evaluator", "BaseModelBackend", "PromptLoader", "ConfigLoader"]
