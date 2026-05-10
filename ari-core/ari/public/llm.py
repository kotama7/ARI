"""Public re-export of :class:`ari.llm.client.LLMClient` (Phase 4).

Lets skills use ARI's litellm wrapper without touching the
``ari.llm.client`` private module path; the wrapper reuses our cost
tracker integration so this is the recommended path.
"""

from ari.llm.client import LLMClient  # noqa: F401

__all__ = ["LLMClient"]
