"""Tests for ``_litellm_completer.LiteLLMTurnCompleter``.

The completer is the drop-in replacement for ``OpenAICompletionsTurnCompleter``
inside ``judge_submission`` — the goal is provider-neutrality and lifting the
``CONTEXT_WINDOW_LENGTHS`` allow-list constraint that was crashing
``grade_with_simplejudge`` for any model not in PaperBench's pinned dict.

These tests inject a fake ``litellm`` so they never touch the network.
"""

from __future__ import annotations

import importlib.util
import json
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


def test_paperbench_file_selection_normalizes_private_absolute_paths():
    conversation = [{
        "role": "user",
        "content": (
            "Here are the files in the submission attempt:\n\n"
            "Directory structure:\n"
            "├── jacobi.c\n"
            "└── submission\n"
            "    ├── jacobi.c\n"
            "    └── analyze.py\n\n"
            "Now return a list of the 10 most relevant files in order of relevance "
            "(descending)."
        ),
    }]
    content = (
        "/tmp/ari-cli-shim-abc/jacobi.c\n"
        "/tmp/ari-cli-shim-abc/submission/jacobi.c\n"
        "/tmp/ari-cli-shim-abc/submission/analyze.py"
    )

    assert LC._normalize_paperbench_file_selection(conversation, content) == (
        "jacobi.c\nsubmission/jacobi.c\nsubmission/analyze.py"
    )


def test_file_selection_normalizer_does_not_touch_other_prompts():
    assert LC._normalize_paperbench_file_selection(
        [{"role": "user", "content": "Review this file."}],
        "/tmp/private/result.txt",
    ) == "/tmp/private/result.txt"


def test_paperbench_file_tree_paths_distinguishes_empty_from_other_prompt():
    empty_ranking = [{
        "role": "user",
        "content": (
            "Here are the files in the submission attempt:\n\n"
            "Directory structure:\n\n\n"
            "Now return a list of the 10 most relevant files in order of relevance "
            "(descending)."
        ),
    }]

    assert LC._paperbench_file_tree_paths(empty_ranking) == set()
    assert LC._paperbench_file_tree_paths(
        [{"role": "user", "content": "Review this submission."}]
    ) is None


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


@pytest.mark.asyncio
async def test_async_completion_short_circuits_empty_paperbench_tree(
    tmp_path, monkeypatch
):
    fake = types.ModuleType("litellm")

    async def acompletion(**kwargs):
        raise AssertionError("provider must not be called for an empty file tree")

    fake.acompletion = acompletion
    monkeypatch.setitem(sys.modules, "litellm", fake)
    trace_dir = tmp_path / "calls"
    completer = LC.LiteLLMTurnCompleter.Config(
        model="gpt-5-mini", trace_dir=str(trace_dir)
    ).build()
    conversation = [{
        "role": "user",
        "content": (
            "Here are the files in the submission attempt:\n\n"
            "Directory structure:\n\n\n"
            "Now return a list of the 10 most relevant files in order of relevance "
            "(descending)."
        ),
    }]

    result = await completer.async_completion(conversation=conversation)

    assert result.output_messages[0].content == ""
    assert result.usage is None
    trace = json.loads(next(trace_dir.glob("*.json")).read_text())
    assert trace["error"] is None
    assert trace["response"]["content"] == ""
    assert (
        trace["response"]["synthetic_reason"]
        == "paperbench-empty-submission-tree"
    )


@pytest.mark.asyncio
async def test_async_completion_persists_digest_bound_raw_trace(
    tmp_path, monkeypatch
):
    captured: dict = {}
    _install_fake_litellm(monkeypatch, captured, content="raw judge response")
    trace_dir = tmp_path / "calls"
    completer = LC.LiteLLMTurnCompleter.Config(
        model="gpt-5-mini", trace_dir=str(trace_dir)
    ).build()

    await completer.async_completion(
        conversation=[{"role": "user", "content": "raw judge prompt"}]
    )

    traces = list(trace_dir.glob("*.json"))
    assert len(traces) == 1
    trace = json.loads(traces[0].read_text())
    assert trace["schema_version"] == "ari.model-call-trace/v1"
    assert trace["request"]["messages"][0]["content"] == "raw judge prompt"
    assert trace["response"]["content"] == "raw judge response"
    assert trace["request_digest"] == LC._canonical_digest(trace["request"])
    assert trace["response_digest"] == LC._canonical_digest(trace["response"])


@pytest.mark.asyncio
async def test_async_completion_persists_provider_failure(tmp_path, monkeypatch):
    fake = types.ModuleType("litellm")

    async def acompletion(**kwargs):
        raise RuntimeError("provider unavailable")

    fake.acompletion = acompletion
    monkeypatch.setitem(sys.modules, "litellm", fake)
    trace_dir = tmp_path / "calls"
    completer = LC.LiteLLMTurnCompleter.Config(
        model="gpt-5-mini", trace_dir=str(trace_dir)
    ).build()

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await completer.async_completion(
            conversation=[{"role": "user", "content": "prompt"}]
        )

    trace = json.loads(next(trace_dir.glob("*.json")).read_text())
    assert trace["response"] is None
    assert "provider unavailable" in trace["error"]


# ── integration: bridge wires the new completer ────────────────────────────


def test_bridge_uses_litellm_completer():
    """Sanity: ``judge_submission`` references ``LiteLLMTurnCompleter`` in source.

    A regression where someone reverts to the OpenAI direct client would put us
    back into the registry-allow-list trap. This is a structural guard, not a
    behavior test.
    """
    bridge_src = (SRC / "_paperbench_bridge.py").read_text()
    assert "LiteLLMTurnCompleter" in bridge_src
    assert "int_completer_config=int_cfg" in bridge_src
    assert "float_completer_config=float_cfg" in bridge_src
    assert "trace_dir=trace_value" in bridge_src
    assert bridge_src.count(
        'api_base=os.environ.get("ARI_LLM_API_BASE") or None'
    ) >= 3
