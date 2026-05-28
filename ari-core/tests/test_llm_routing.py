"""Single-source-of-truth litellm provider-prefix routing.

Skills used to each duplicate (often partially) the same prefix logic that
``ari.llm.client.LLMClient._model_name`` applied. That divergence caused
synthetic shim models like ``claude-cli`` to fail with ``LLM Provider NOT
provided`` whenever a skill made its own ``litellm.completion`` call. The
fix is twofold:

- :func:`ari.llm.routing.resolve_litellm_model` is the one helper everyone
  calls (the ReAct client and the auto-injector both use it).
- :func:`ari.cost_tracker._install_litellm_metadata_injector` wraps
  ``litellm.completion`` / ``acompletion`` so skills that pass a bare model
  id still route correctly without a per-skill code change.
"""
from __future__ import annotations

import pytest

from ari.llm.routing import resolve_litellm_model
from ari import cost_tracker as ct


# ── resolve_litellm_model: prefix-by-backend rules ───────────────────────────
@pytest.mark.parametrize("backend,model,expected", [
    ("openai",     "gpt-4o",        "gpt-4o"),                  # left alone (litellm infers)
    ("anthropic",  "claude-opus-4-7", "anthropic/claude-opus-4-7"),
    ("claude",     "claude-opus-4-7", "anthropic/claude-opus-4-7"),
    ("ollama",     "qwen3:8b",      "ollama_chat/qwen3:8b"),
    ("cli-shim",   "claude-cli",    "openai/claude-cli"),
    ("cli_shim",   "codex-cli",     "openai/codex-cli"),
    ("",           "gpt-4o",        "gpt-4o"),
])
def test_resolve_applies_backend_prefix(backend, model, expected):
    assert resolve_litellm_model(model, backend=backend) == expected


@pytest.mark.parametrize("model", [
    "openai/claude-cli",
    "anthropic/claude-opus-4-7",
    "ollama_chat/qwen3:8b",
    "gemini/gemini-2.5-pro",
])
def test_resolve_is_idempotent_for_already_prefixed(model):
    # Any backend — already-prefixed models pass through untouched.
    assert resolve_litellm_model(model, backend="cli-shim") == model
    assert resolve_litellm_model(model, backend="anthropic") == model


def test_resolve_falls_back_to_env_backend(monkeypatch):
    monkeypatch.setenv("ARI_BACKEND", "cli-shim")
    assert resolve_litellm_model("claude-cli") == "openai/claude-cli"
    monkeypatch.setenv("ARI_BACKEND", "anthropic")
    assert resolve_litellm_model("claude-opus-4-7") == "anthropic/claude-opus-4-7"


def test_resolve_empty_model_returns_empty():
    assert resolve_litellm_model("") == ""
    assert resolve_litellm_model("", backend="cli-shim") == ""


# ── _apply_ari_routing: model prefix + auto api_base (cli-shim only) ─────────
def test_apply_routing_cli_shim_fills_prefix_and_base(monkeypatch):
    monkeypatch.setenv("ARI_BACKEND", "cli-shim")
    monkeypatch.setenv("ARI_LLM_API_BASE", "http://localhost:8900/v1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    kwargs = {"model": "claude-cli", "messages": []}
    ct._apply_ari_routing(kwargs)
    assert kwargs["model"] == "openai/claude-cli"
    assert kwargs["api_base"] == "http://localhost:8900/v1"
    # placeholder key so litellm's openai handler doesn't refuse the call
    assert kwargs["api_key"] == "cli-shim"


def test_apply_routing_does_not_overwrite_caller_supplied_api_base(monkeypatch):
    monkeypatch.setenv("ARI_BACKEND", "cli-shim")
    monkeypatch.setenv("ARI_LLM_API_BASE", "http://localhost:8900/v1")
    kwargs = {"model": "claude-cli", "api_base": "http://other:9999/v1"}
    ct._apply_ari_routing(kwargs)
    assert kwargs["api_base"] == "http://other:9999/v1"


def test_apply_routing_real_openai_unchanged(monkeypatch):
    monkeypatch.setenv("ARI_BACKEND", "openai")
    monkeypatch.delenv("ARI_LLM_API_BASE", raising=False)
    kwargs = {"model": "gpt-4o", "messages": []}
    ct._apply_ari_routing(kwargs)
    assert kwargs["model"] == "gpt-4o"
    assert "api_base" not in kwargs  # never redirect a real OpenAI call


def test_apply_routing_anthropic_prefixes_no_api_base(monkeypatch):
    monkeypatch.setenv("ARI_BACKEND", "anthropic")
    monkeypatch.setenv("ARI_LLM_API_BASE", "http://localhost:8900/v1")  # should be ignored
    kwargs = {"model": "claude-opus-4-7"}
    ct._apply_ari_routing(kwargs)
    assert kwargs["model"] == "anthropic/claude-opus-4-7"
    assert "api_base" not in kwargs  # only cli-shim auto-fills api_base


# ── injector: skill's bare litellm.completion("claude-cli", ...) routes ──────
def test_injector_normalises_skill_litellm_call(monkeypatch):
    """Simulate a skill calling ``litellm.completion(model="claude-cli", ...)``;
    the wrapper installed by cost_tracker should rewrite kwargs so the call
    actually reaches the shim instead of failing with 'Provider NOT provided'."""
    import litellm as _litellm
    monkeypatch.setenv("ARI_BACKEND", "cli-shim")
    monkeypatch.setenv("ARI_LLM_API_BASE", "http://localhost:8900/v1")
    captured: dict = {}

    def _spy(*args, **kwargs):
        captured.update(kwargs)
        class _R:  # minimal duck-type so the wrapper doesn't blow up
            class _U:
                prompt_tokens = 0
                completion_tokens = 0
            usage = _U()
            model = kwargs.get("model", "")
        return _R()

    orig = _litellm.completion
    _litellm.completion = _spy
    prev_installed = ct._injector_installed
    ct._injector_installed = False
    try:
        ct._install_litellm_metadata_injector()
        # The wrapper is now in place; invoke as a skill would.
        _litellm.completion(model="claude-cli",
                            messages=[{"role": "user", "content": "hi"}])
    finally:
        _litellm.completion = orig
        ct._injector_installed = prev_installed
    assert captured["model"] == "openai/claude-cli"
    assert captured["api_base"] == "http://localhost:8900/v1"
