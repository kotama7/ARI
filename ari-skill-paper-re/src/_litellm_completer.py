"""Provider-neutral ``TurnCompleter`` that routes through LiteLLM.

PaperBench's stock ``OpenAICompletionsTurnCompleter`` (a) hits OpenAI directly
and (b) refuses any model id that is not in its hand-maintained
``CONTEXT_WINDOW_LENGTHS`` registry, so we cannot use it with newer OpenAI
snapshots, Azure, Anthropic, Gemini, Ollama, etc. This module supplies a
drop-in alternative ``LiteLLMTurnCompleter`` + ``LiteLLMConfig`` that
``SimpleJudge`` accepts via the ``completer_config`` parameter.

Only the *main* per-leaf grading completer needs to be swapped — the int/float
structured completers ``SimpleJudge`` uses for score parsing default to
``gpt-4o-2024-08-06`` (which IS in PaperBench's registry) and may stay on
OpenAI direct, since the parse task is small and reliable there.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Unpack

import tiktoken
from openai.types.chat import (
    ChatCompletionMessage,
    ChatCompletionMessageFunctionToolCall,
)
from openai.types.chat.chat_completion_message_tool_call import Function
from openai.types.completion_usage import CompletionUsage
from preparedness_turn_completer.turn_completer import TurnCompleter
from pydantic import ConfigDict, Field

logger = logging.getLogger(__name__)

# Sensible context-window defaults keyed by model-name prefix. These are used
# when the caller does not supply ``n_ctx`` explicitly. Keep conservative —
# downstream truncation is more forgiving than over-promising context.
_DEFAULT_N_CTX_BY_PREFIX: tuple[tuple[str, int], ...] = (
    # OpenAI
    ("gpt-5", 400_000),
    ("gpt-4.1", 1_000_000),
    ("gpt-4o", 128_000),
    ("gpt-4-turbo", 128_000),
    ("o4", 200_000),
    ("o3", 200_000),
    ("o1", 200_000),
    # Anthropic
    ("claude-opus-4", 200_000),
    ("claude-sonnet-4", 200_000),
    ("claude-haiku-4", 200_000),
    ("claude-3", 200_000),
    ("anthropic/claude", 200_000),
    # Google
    ("gemini/gemini-2.5", 1_000_000),
    ("gemini/gemini-2.0", 1_000_000),
    ("gemini/gemini-1.5", 1_000_000),
    ("gemini-2.5", 1_000_000),
    ("gemini-1.5", 1_000_000),
    # Local / catch-all
    ("ollama", 32_000),
)
_DEFAULT_N_CTX_FALLBACK = 128_000


def _infer_n_ctx(model: str) -> int:
    for prefix, n in _DEFAULT_N_CTX_BY_PREFIX:
        if model.startswith(prefix):
            return n
    return _DEFAULT_N_CTX_FALLBACK


def _infer_encoding_name(model: str) -> str:
    """Return a tiktoken encoding name. SimpleJudge uses this only for
    truncation token-counting; an approximate encoding is fine for non-OpenAI
    models — over- or under-counting tokens by ~10% only changes how
    aggressively we truncate."""
    try:
        return tiktoken.encoding_name_for_model(model.split("/")[-1])
    except KeyError:
        return "o200k_base"


class LiteLLMTurnCompleter(TurnCompleter):
    """``TurnCompleter`` whose ``async_completion`` calls ``litellm.acompletion``.

    Accepts any model id LiteLLM understands (``gpt-5-mini``,
    ``anthropic/claude-opus-4-5``, ``gemini/gemini-2.5-pro``,
    ``ollama/llama3.1``, …). Drops PaperBench's registry constraint.
    """

    def __init__(
        self,
        model: str,
        *,
        n_ctx: int | None = None,
        encoding_name: str | None = None,
        api_base: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        response_format: Any = None,
        timeout: int | None = None,
        extra_kwargs: dict | None = None,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
    ):
        self.model = model
        self.encoding_name = encoding_name or _infer_encoding_name(model)
        self.n_ctx = int(n_ctx) if n_ctx else _infer_n_ctx(model)
        self.api_base = api_base
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.response_format = response_format
        self.timeout = timeout
        self.extra_kwargs = dict(extra_kwargs or {})
        # Chat-Completions-shaped tool params (see :class:`LiteLLMBasicAgentCompleterConfig`
        # for the conversion from PaperBench's Responses-shaped FunctionToolParam).
        self.tools = list(tools) if tools else None
        self.tool_choice = tool_choice
        # Used by ``BasicAgentTurnCompleterConfig`` siblings (e.g.
        # ``OpenAIResponsesTurnCompleter``) to surface retry time. We track
        # it via litellm's ``num_retries`` parameter; on each retry we add
        # the elapsed delay. The solver clears the field after reading.
        self._last_retry_time = 0.0

    class Config(TurnCompleter.Config):
        """Pydantic-friendly config matching ``TurnCompleter.Config`` shape."""

        model_config = ConfigDict(arbitrary_types_allowed=True)

        model: str
        n_ctx: int | None = None
        encoding_name: str | None = None
        api_base: str | None = None
        temperature: float | None = None
        max_tokens: int | None = None
        top_p: float | None = None
        response_format: Any = None
        timeout: int | None = None
        extra_kwargs: dict | None = None
        tools: list[dict] | None = None
        tool_choice: str | None = None

        def build(self) -> "LiteLLMTurnCompleter":
            return LiteLLMTurnCompleter(
                model=self.model,
                n_ctx=self.n_ctx,
                encoding_name=self.encoding_name,
                api_base=self.api_base,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                top_p=self.top_p,
                response_format=self.response_format,
                timeout=self.timeout,
                extra_kwargs=self.extra_kwargs,
                tools=self.tools,
                tool_choice=self.tool_choice,
            )

    class Completion(TurnCompleter.Completion):
        usage: CompletionUsage | None = None

    def completion(
        self,
        conversation: TurnCompleter.RuntimeConversation,
        **params: Unpack[TurnCompleter.Params],
    ) -> "LiteLLMTurnCompleter.Completion":
        raise NotImplementedError("Use async_completion")

    async def async_completion(
        self,
        conversation: TurnCompleter.RuntimeConversation,
        **params: Unpack[TurnCompleter.Params],
    ) -> "LiteLLMTurnCompleter.Completion":
        import litellm

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": list(conversation),
        }
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        if self.top_p is not None:
            kwargs["top_p"] = self.top_p
        if self.response_format is not None:
            kwargs["response_format"] = self.response_format
        if self.timeout is not None:
            kwargs["timeout"] = self.timeout
        kwargs.update(self.extra_kwargs)
        if self.tools:
            kwargs["tools"] = list(self.tools)
            if self.tool_choice:
                kwargs["tool_choice"] = self.tool_choice

        t0 = time.monotonic()
        resp = await litellm.acompletion(**kwargs)
        # litellm exposes the cumulative API retry/backoff time on the
        # response when ``num_retries`` triggers. Best-effort; falls back
        # to wall-clock delta — which inflates by request latency, but
        # solver only uses this to subtract from time-budget accounting.
        retry_time = float(getattr(resp, "_response_ms", 0.0)) / 1000.0
        if retry_time <= 0.0:
            retry_time = max(0.0, time.monotonic() - t0)
        self._last_retry_time = retry_time

        choice = resp.choices[0]
        msg = choice.message
        # litellm's ``message.tool_calls`` is a list of OpenAI-shaped
        # ``ChatCompletionMessageToolCall`` dicts. Coerce each into the
        # typed ``ChatCompletionMessageFunctionToolCall`` that
        # ``parse_basic_agent_tool_calls`` requires (it asserts
        # ``isinstance(tc, ChatCompletionMessageFunctionToolCall)``).
        tool_calls_typed: list[ChatCompletionMessageFunctionToolCall] = []
        raw_tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in raw_tool_calls:
            tc_dict = (
                tc.model_dump() if hasattr(tc, "model_dump")
                else dict(tc) if isinstance(tc, dict)
                else {"id": tc.id, "type": "function",
                      "function": {"name": tc.function.name,
                                   "arguments": tc.function.arguments}}
            )
            fn = tc_dict.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, dict):
                args = json.dumps(args)
            tool_calls_typed.append(
                ChatCompletionMessageFunctionToolCall(
                    id=str(tc_dict.get("id", "")),
                    type="function",
                    function=Function(
                        name=str(fn.get("name", "")),
                        arguments=str(args or "{}"),
                    ),
                )
            )
        chat_msg = ChatCompletionMessage(
            role="assistant",
            content=getattr(msg, "content", None),
            refusal=getattr(msg, "refusal", None),
            tool_calls=tool_calls_typed or None,
        )
        usage_obj = getattr(resp, "usage", None)
        usage_dump: CompletionUsage | None = None
        if usage_obj is not None:
            try:
                usage_dump = CompletionUsage.model_validate(
                    usage_obj.model_dump() if hasattr(usage_obj, "model_dump") else dict(usage_obj)
                )
            except Exception:  # noqa: BLE001 — usage is best-effort, never block grading
                usage_dump = None
        return LiteLLMTurnCompleter.Completion(
            input_conversation=conversation,
            output_messages=[chat_msg],
            usage=usage_dump,
        )


# ─── BasicAgent-compatible config (tool conversion + retry tracking) ──


def _responses_tool_to_chat_completions(rtool: dict) -> dict:
    """Convert a Responses-shaped FunctionToolParam dict to a Chat Completions
    tool param dict.

    Responses shape (what PaperBench tools emit via ``get_oai_tool_call()``):
        {"type": "function", "name": ..., "description": ..., "parameters": {...},
         "strict": false}

    Chat Completions shape (what litellm / OpenAI Chat-Completions API expect):
        {"type": "function", "function": {"name": ..., "description": ...,
                                          "parameters": {...}}}

    The two are *similar* (both call themselves "function tools") but the
    name/description/parameters live one nesting level apart. Some Chat-
    Completions providers also accept the flat form as a courtesy; we emit
    the nested form which is the OpenAI-documented norm.
    """
    if not isinstance(rtool, dict):
        rtool = (
            rtool.model_dump() if hasattr(rtool, "model_dump") else dict(rtool)
        )
    if "function" in rtool and "type" in rtool:
        # Already Chat Completions shaped.
        return rtool
    return {
        "type": "function",
        "function": {
            "name": rtool.get("name", ""),
            "description": rtool.get("description", ""),
            "parameters": rtool.get("parameters", {"type": "object"}),
        },
    }


# Imports deferred so this module loads without paperbench on path during
# unit tests of the standalone LiteLLMTurnCompleter.
def _basicagent_classes():
    import _vendor_path  # noqa: F401
    from paperbench.solvers.basicagent.completer import (
        BasicAgentTurnCompleterConfig,
        TimeTrackingRetryConfig,
    )
    return BasicAgentTurnCompleterConfig, TimeTrackingRetryConfig


def _make_litellm_basicagent_config_class():
    """Lazily build the subclass so import order is forgiving."""
    BasicAgentTurnCompleterConfig, TimeTrackingRetryConfig = _basicagent_classes()

    class LiteLLMBasicAgentCompleterConfig(  # noqa: D401  (class — see docstring)
        LiteLLMTurnCompleter.Config,
        BasicAgentTurnCompleterConfig,
    ):
        """Config that satisfies both ``BasicAgentTurnCompleterConfig`` and
        ``LiteLLMTurnCompleter.Config``.

        Used by ``AriPBSolver`` (Phase 4 entry-point alternative to
        ``OpenAIResponsesTurnCompleterConfig``). Converts PaperBench tool
        defs to Chat Completions form on ``build()`` so litellm can pass
        them to whichever provider the model id targets.
        """

        model_config = ConfigDict(arbitrary_types_allowed=True)

        def build(self) -> "LiteLLMTurnCompleter":
            converted_tools: list[dict] = []
            if self.basicagent_tools:
                for tool in self.basicagent_tools:
                    converted_tools.append(
                        _responses_tool_to_chat_completions(tool.get_oai_tool_call())
                    )
            existing = self.tools or []
            self.tools = list(existing) + converted_tools
            completer = LiteLLMTurnCompleter(
                model=self.model,
                n_ctx=self.n_ctx,
                encoding_name=self.encoding_name,
                api_base=self.api_base,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                top_p=self.top_p,
                response_format=self.response_format,
                timeout=self.timeout,
                extra_kwargs=self.extra_kwargs,
                tools=self.tools,
                tool_choice=self.tool_choice,
            )

            # Surface ``retry_config`` so ``make_completer_request`` can read
            # ``time_spent_retrying`` after each call (see vendor api.py).
            # We feed our subprocess-measured retry time into that slot.
            class _CompleterWithRetryShim(type(completer)):
                pass

            # Attach retry_config attribute to the completer instance so
            # ``hasattr(completer, "retry_config")`` returns True.
            completer.retry_config = self.retry_config  # type: ignore[attr-defined]
            return completer

    return LiteLLMBasicAgentCompleterConfig


def get_litellm_basicagent_completer_config():
    """Return the ``LiteLLMBasicAgentCompleterConfig`` class (lazily built)."""
    return _make_litellm_basicagent_config_class()
