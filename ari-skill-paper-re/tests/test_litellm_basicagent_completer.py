"""Tests for the BasicAgent-compatible LiteLLM completer.

Verifies the **structural** parts of the bridge — Responses-shaped
``FunctionToolParam`` ↔ Chat Completions tool params, typed
``ChatCompletionMessageFunctionToolCall`` coercion — using real vendor tool
classes. Real ``litellm.acompletion`` is replaced by an inline async
function (in a single test) only because hitting a real LLM API is not
feasible in unit tests; everything else uses production code.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

import _vendor_path  # noqa: F401, E402

from _litellm_completer import (  # noqa: E402
    LiteLLMTurnCompleter,
    _responses_tool_to_chat_completions,
    get_litellm_basicagent_completer_config,
)
from paperbench.solvers.basicagent.tools import (  # noqa: E402
    BashTool,
    PythonTool,
    ReadFileChunk,
    SearchFile,
    SubmitTool,
)
from preparedness_turn_completer.turn_completer import TurnCompleter  # noqa: E402


pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "ToolCls",
    [BashTool, PythonTool, ReadFileChunk, SearchFile, SubmitTool],
)
def test_tool_conversion_for_each_vendor_tool(ToolCls):
    rtool = ToolCls().get_oai_tool_call()
    ctool = _responses_tool_to_chat_completions(rtool)
    assert ctool["type"] == "function"
    assert ctool["function"]["name"]
    assert "parameters" in ctool["function"]
    # Idempotent: passing an already-converted tool yields the same dict.
    assert _responses_tool_to_chat_completions(ctool) == ctool


def test_basicagent_config_builds_real_completer():
    cls = get_litellm_basicagent_completer_config()
    cfg = cls(
        model="gpt-5-mini",
        basicagent_tools=[BashTool(), PythonTool(), SubmitTool()],
    )
    completer = cfg.build()
    assert isinstance(completer, LiteLLMTurnCompleter)
    assert isinstance(completer, TurnCompleter)
    assert completer.model == "gpt-5-mini"
    # 3 tools converted to Chat Completions shape
    assert len(completer.tools) == 3
    names = [t["function"]["name"] for t in completer.tools]
    assert "bash" in names
    assert "submit" in names
    # ``retry_config`` is exposed for vendor api.py's hasattr check.
    assert hasattr(completer, "retry_config")


def test_litellm_config_passthrough_without_basicagent_tools():
    """Without basicagent_tools, the SimpleJudge code path still works."""
    cfg = LiteLLMTurnCompleter.Config(model="gpt-4o-2024-08-06")
    completer = cfg.build()
    assert isinstance(completer, LiteLLMTurnCompleter)
    assert completer.model == "gpt-4o-2024-08-06"
    assert completer.tools is None


async def test_async_completion_coerces_tool_calls_to_typed_subclass(monkeypatch):
    """The agent loop's ``parse_basic_agent_tool_calls`` asserts each
    tool_call is a ``ChatCompletionMessageFunctionToolCall``; we must
    construct exactly that type from litellm's looser response dict."""
    from openai.types.chat import ChatCompletionMessageFunctionToolCall

    cls = get_litellm_basicagent_completer_config()
    cfg = cls(model="gpt-5-mini", basicagent_tools=[BashTool()])
    completer = cfg.build()

    # Simulate a litellm response with a tool_call. We construct a minimal
    # response object with the attributes litellm actually returns.
    class _Fn:
        def __init__(self, name, args):
            self.name = name
            self.arguments = args

    class _TC:
        def __init__(self, id, name, args):
            self.id = id
            self.type = "function"
            self.function = _Fn(name, args)

        def model_dump(self):
            return {
                "id": self.id,
                "type": "function",
                "function": {
                    "name": self.function.name,
                    "arguments": self.function.arguments,
                },
            }

    class _Msg:
        role = "assistant"
        content = None
        refusal = None
        tool_calls = [_TC("tc-1", "bash", '{"cmd": "ls"}')]

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]
        usage = None
        _response_ms = 5.0

    async def _fake_acompletion(**kwargs):
        # Verify our completer is passing tools through to litellm.
        assert "tools" in kwargs, "tools were not forwarded to litellm.acompletion"
        assert kwargs["tools"][0]["function"]["name"] == "bash"
        return _Resp()

    import litellm
    monkeypatch.setattr(litellm, "acompletion", _fake_acompletion)

    out = await completer.async_completion([{"role": "user", "content": "hi"}])
    msgs = out.output_messages
    assert len(msgs) == 1
    tcs = msgs[0].tool_calls or []
    assert len(tcs) == 1
    assert isinstance(tcs[0], ChatCompletionMessageFunctionToolCall)
    assert tcs[0].function.name == "bash"
    assert tcs[0].function.arguments == '{"cmd": "ls"}'
    assert tcs[0].id == "tc-1"
