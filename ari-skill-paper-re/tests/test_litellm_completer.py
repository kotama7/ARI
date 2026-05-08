"""Tests for ``_litellm_completer.LiteLLMTurnCompleter``.

The completer is the drop-in replacement for ``OpenAICompletionsTurnCompleter``
inside ``judge_submission`` — the goal is provider-neutrality and lifting the
``CONTEXT_WINDOW_LENGTHS`` allow-list constraint that was crashing
``grade_with_simplejudge`` for any model not in PaperBench's pinned dict.

These tests inject a fake ``litellm`` so they never touch the network.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

_spec = importlib.util.spec_from_file_location(
    "paper_re_litellm_completer", SRC / "_litellm_completer.py"
)
LC = importlib.util.module_from_spec(_spec)
sys.modules["paper_re_litellm_completer"] = LC
_spec.loader.exec_module(LC)


# ── shape: Config / build / completer attrs ─────────────────────────────────

def test_config_build_returns_completer_with_attrs():
    cfg = LC.LiteLLMTurnCompleter.Config(model="gpt-5-mini")
    completer = cfg.build()
    assert isinstance(completer, LC.LiteLLMTurnCompleter)
    assert completer.model == "gpt-5-mini"
    assert completer.n_ctx == 400_000  # gpt-5* prefix default
    assert completer.encoding_name in ("o200k_base", "cl100k_base")


def test_n_ctx_inferred_per_provider():
    for model, expected in [
        ("gpt-5-mini", 400_000),
        ("gpt-4o-2024-11-20", 128_000),
        ("gpt-4.1", 1_000_000),
        ("o4-mini", 200_000),
        ("anthropic/claude-opus-4-5", 200_000),
        ("gemini/gemini-2.5-pro", 1_000_000),
        ("ollama/llama3.1", 32_000),
        ("totally-unknown-model-xyz", 128_000),  # fallback
    ]:
        completer = LC.LiteLLMTurnCompleter.Config(model=model).build()
        assert completer.n_ctx == expected, (model, completer.n_ctx)


def test_explicit_n_ctx_overrides_default():
    cfg = LC.LiteLLMTurnCompleter.Config(model="gpt-5", n_ctx=50_000)
    assert cfg.build().n_ctx == 50_000


def test_completion_sync_raises():
    completer = LC.LiteLLMTurnCompleter.Config(model="gpt-5").build()
    with pytest.raises(NotImplementedError):
        completer.completion(conversation=[])


# ── async_completion: integration with a fake litellm ──────────────────────


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content
        self.refusal = None


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeUsage:
    def __init__(self):
        self.prompt_tokens = 10
        self.completion_tokens = 20
        self.total_tokens = 30

    def model_dump(self):
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


class _FakeResponse:
    def __init__(self, content: str = "Hello"):
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()


def _install_fake_litellm(monkeypatch, captured_kwargs: dict, content: str = "yes"):
    fake = types.ModuleType("litellm")

    async def acompletion(**kwargs):
        captured_kwargs.update(kwargs)
        return _FakeResponse(content)

    fake.acompletion = acompletion
    monkeypatch.setitem(sys.modules, "litellm", fake)


@pytest.mark.asyncio
async def test_async_completion_forwards_messages_and_model(monkeypatch):
    captured: dict = {}
    _install_fake_litellm(monkeypatch, captured, content="0\n\nThis is the score.")

    completer = LC.LiteLLMTurnCompleter.Config(
        model="anthropic/claude-opus-4-5",
        temperature=0.7,
        max_tokens=512,
        timeout=60,
    ).build()

    conv = [
        {"role": "system", "content": "you are a judge"},
        {"role": "user", "content": "score this"},
    ]
    result = await completer.async_completion(conversation=conv)

    assert captured["model"] == "anthropic/claude-opus-4-5"
    assert captured["messages"] == conv
    assert captured["temperature"] == 0.7
    assert captured["max_tokens"] == 512
    assert captured["timeout"] == 60

    assert len(result.output_messages) == 1
    msg = result.output_messages[0]
    assert msg.role == "assistant"
    assert msg.content == "0\n\nThis is the score."
    assert result.usage is not None
    assert result.usage.total_tokens == 30


@pytest.mark.asyncio
async def test_async_completion_only_sends_set_kwargs(monkeypatch):
    """Don't leak ``None`` for unset optional params — some providers reject it."""
    captured: dict = {}
    _install_fake_litellm(monkeypatch, captured, content="ok")

    completer = LC.LiteLLMTurnCompleter.Config(model="gpt-5-mini").build()
    await completer.async_completion(conversation=[{"role": "user", "content": "hi"}])

    assert "temperature" not in captured
    assert "max_tokens" not in captured
    assert "top_p" not in captured
    assert "response_format" not in captured
    assert "api_base" not in captured


@pytest.mark.asyncio
async def test_async_completion_handles_missing_usage(monkeypatch):
    fake = types.ModuleType("litellm")

    class _NoUsageResp:
        choices = [_FakeChoice("answer")]
        usage = None

    async def acompletion(**kwargs):
        return _NoUsageResp()

    fake.acompletion = acompletion
    monkeypatch.setitem(sys.modules, "litellm", fake)

    completer = LC.LiteLLMTurnCompleter.Config(model="gpt-5-mini").build()
    result = await completer.async_completion(conversation=[{"role": "user", "content": "hi"}])
    assert result.usage is None
    assert result.output_messages[0].content == "answer"


# ── integration: bridge wires the new completer ────────────────────────────


def test_bridge_uses_litellm_completer():
    """Sanity: ``judge_submission`` references ``LiteLLMTurnCompleter`` in source.

    A regression where someone reverts to the OpenAI direct client would put us
    back into the registry-allow-list trap. This is a structural guard, not a
    behavior test.
    """
    bridge_src = (SRC / "_paperbench_bridge.py").read_text()
    assert "LiteLLMTurnCompleter" in bridge_src
    assert "LiteLLMTurnCompleter.Config(model=judge_model)" in bridge_src
