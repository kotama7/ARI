"""ari.llm — thin wrappers around LiteLLM for the agent loop and skills.

Provides ``LLMClient`` and message dataclasses with a single concern:
turn ARI-internal calls into LiteLLM ``completion(...)`` invocations and
record cost via ``ari.cost_tracker``.  No prompt templates live here;
those sit under ``ari/prompts/`` (since Phase PC).

Public symbols:
- ``LLMClient`` — synchronous and async completion + tool calling.

See also:
- ``docs/configuration.md`` (LLM-related env vars).
- ``ari-core/ari/cost_tracker.py`` (cost accounting hooked via litellm callback).
"""
