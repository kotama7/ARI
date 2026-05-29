"""ari.llm — thin wrappers around LiteLLM for the agent loop and skills.

Provides ``LLMClient`` and message dataclasses with a single concern:
turn ARI-internal calls into LiteLLM ``completion(...)`` invocations and
record cost via ``ari.cost_tracker``.  No prompt templates live here;
those sit under ``ari/prompts/`` (since Phase PC).

Public symbols:
- ``LLMClient`` — synchronous and async completion + tool calling.
- ``resolve_litellm_model`` — single source of truth for litellm provider
  prefixes (used by both the ReAct client and MCP skills).

See also:
- ``docs/reference/configuration.md`` (LLM-related env vars).
- ``ari-core/ari/cost_tracker.py`` (cost accounting hooked via litellm callback).
"""
from ari.llm.routing import resolve_litellm_model

__all__ = ["resolve_litellm_model"]
