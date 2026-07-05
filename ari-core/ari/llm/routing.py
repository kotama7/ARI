"""litellm provider-prefix resolution for ARI.

ARI talks to every LLM through litellm. litellm routes to the right backend
from a model id's prefix (``anthropic/``, ``ollama_chat/``, ``openai/``, ...);
without a prefix it can only resolve a handful of well-known model families
(``gpt-*``, etc.). The ARI agent ReAct client (``ari.llm.client``) applies the
prefix rules at every call, but MCP skills (idea, transform, evaluator, ...)
and the GUI's chat endpoint historically each duplicated their own (often
incomplete) version. That divergence let synthetic shim models like
``claude-cli`` route fine through the ReAct client but fail (`LLM Provider NOT
provided`) when a skill made its own ``litellm.completion`` call.

This module is the single source of truth: every caller that builds a litellm
model id should pass it through :func:`resolve_litellm_model` so the same
``(model, backend)`` inputs always produce the same routable id.
"""
from __future__ import annotations

import os

_KNOWN_PREFIXES = (
    "openai/",
    "anthropic/",
    "claude/",
    "ollama_chat/",
    "ollama/",
    "huggingface/",
    "azure/",
    "groq/",
    "together_ai/",
    "gemini/",
    "vertex_ai/",
    "bedrock/",
)


# Subtask 014 decision — KEEP as-is (NOT adopted into ``ari._factory``).
# ``resolve_litellm_model`` *transforms* a model id (adds a provider prefix)
# rather than *constructing* an object, and it is public-adjacent
# (re-exported at ``ari.llm.__init__:17`` and called across core + skills).
# Forcing it into the registry pattern for symmetry is discouraged
# (subtask 014 §7.2 step 3, §17); the signature and return values are frozen.
def resolve_litellm_model(model: str, backend: str | None = None) -> str:
    """Apply ARI's provider-prefix rules to a litellm model id.

    - ``anthropic`` / ``claude``  → ``anthropic/<model>``
    - ``ollama``                  → ``ollama_chat/<model>``
    - ``cli-shim`` / ``cli_shim`` → ``openai/<model>`` (litellm dials ``api_base``)
    - ``openai`` (or unknown)     → returned unchanged (litellm infers
      from well-known names like ``gpt-*``)

    Already-prefixed model ids are returned as-is. ``backend`` defaults to
    the ``ARI_BACKEND`` environment variable, so skills that have only the
    raw env value can call ``resolve_litellm_model(model)`` directly.
    """
    if not model:
        return model
    if any(model.startswith(p) for p in _KNOWN_PREFIXES):
        return model
    if backend is None:
        backend = os.environ.get("ARI_BACKEND", "")
    if backend in ("anthropic", "claude"):
        return f"anthropic/{model}"
    if backend == "ollama":
        return f"ollama_chat/{model}"
    if backend in ("cli-shim", "cli_shim"):
        return f"openai/{model}"
    return model
