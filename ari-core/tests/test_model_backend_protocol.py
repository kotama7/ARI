"""Conformance guard for the BaseModelBackend Protocol (subtask 008).

Asserts the concrete ``LLMClient`` structurally satisfies the new
``ari.protocols.BaseModelBackend`` (no subclassing), that the Protocol is
importable + ``runtime_checkable``, and that the ``LiteLLMBackend`` naming alias
points at ``LLMClient``. Pins the additive, contract-preserving shape 008 froze.
"""
from __future__ import annotations

from typing import runtime_checkable

from ari.llm.client import LLMClient
from ari.protocols import BaseModelBackend
from ari.public.config_schema import LLMConfig


def _client() -> LLMClient:
    # Side-effect-free construction (no network until complete() is called).
    return LLMClient(LLMConfig(backend="claude", model="claude-sonnet-4-5", api_key="x"))


def test_base_model_backend_importable_and_runtime_checkable():
    assert BaseModelBackend.__name__ == "BaseModelBackend"
    # @runtime_checkable marks the Protocol for isinstance() support.
    assert getattr(BaseModelBackend, "_is_runtime_protocol", False) is True
    assert runtime_checkable(BaseModelBackend) is BaseModelBackend  # idempotent


def test_llmclient_satisfies_base_model_backend():
    client = _client()
    assert isinstance(client, BaseModelBackend)
    # The structural methods the Protocol declares are present on the concrete class.
    for method in ("complete", "set_context", "stream"):
        assert callable(getattr(client, method))


def test_litellm_backend_alias_is_llmclient():
    from ari.llm import LiteLLMBackend

    assert LiteLLMBackend is LLMClient


def test_public_llm_client_unchanged():
    # 008 must not perturb the public surface: ari.public.llm.LLMClient is the
    # same object as ari.llm.client.LLMClient.
    from ari.public.llm import LLMClient as PublicLLMClient

    assert PublicLLMClient is LLMClient
