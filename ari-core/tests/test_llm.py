"""Tests for ari/llm/client.py - LLMClient mock tests."""

from unittest.mock import MagicMock, patch

import pytest

from ari.config import LLMConfig
from ari.llm.client import LLMClient, LLMMessage, LLMResponse


@pytest.fixture
def llm_config():
    return LLMConfig(backend="claude", model="claude-sonnet-4-5", api_key="test-key")


@pytest.fixture
def llm_client(llm_config):
    return LLMClient(llm_config)


def test_llm_message_creation():
    msg = LLMMessage(role="user", content="Hello")
    assert msg.role == "user"
    assert msg.content == "Hello"


def test_llm_response_creation():
    resp = LLMResponse(content="Test response")
    assert resp.content == "Test response"
    assert resp.tool_calls is None
    assert resp.usage is None


def test_llm_response_with_usage():
    resp = LLMResponse(
        content="Test",
        usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    )
    assert resp.usage["total_tokens"] == 30


def test_model_name_anthropic(llm_client):
    assert llm_client._model_name() == "anthropic/claude-sonnet-4-5"


def test_model_name_openai():
    cfg = LLMConfig(backend="openai", model="gpt-4o")
    client = LLMClient(cfg)
    assert client._model_name() == "gpt-4o"


def test_model_name_other():
    cfg = LLMConfig(backend="other", model="some-model")
    client = LLMClient(cfg)
    assert client._model_name() == "some-model"


@patch("ari.llm.client.litellm")
def test_complete_basic(mock_litellm, llm_client):
    mock_message = MagicMock()
    mock_message.content = "Hello response"
    mock_message.tool_calls = None

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 5
    mock_usage.total_tokens = 15

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    mock_litellm.completion.return_value = mock_response

    messages = [LLMMessage(role="user", content="Hello")]
    result = llm_client.complete(messages)

    assert result.content == "Hello response"
    assert result.usage["total_tokens"] == 15
    mock_litellm.completion.assert_called_once()


@patch("ari.llm.client.litellm")
def test_complete_with_tool_calls(mock_litellm, llm_client):
    mock_tc = MagicMock()
    mock_tc.id = "call_1"
    mock_tc.type = "function"
    mock_tc.function.name = "search"
    mock_tc.function.arguments = '{"query": "test"}'

    mock_message = MagicMock()
    mock_message.content = ""
    mock_message.tool_calls = [mock_tc]

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = None

    mock_litellm.completion.return_value = mock_response

    messages = [LLMMessage(role="user", content="Search something")]
    result = llm_client.complete(messages, tools=[{"type": "function"}])

    assert result.tool_calls is not None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["function"]["name"] == "search"


@patch("ari.llm.client.litellm")
def test_complete_accepts_phase_and_skill_kwargs(mock_litellm, llm_client):
    """Regression: react_driver passes phase=/skill= to complete().

    Before the fix, complete() rejected these kwargs with
    ``TypeError: ... unexpected keyword argument 'phase'`` and the
    reproducibility ReAct loop burned all 40 steps doing nothing.
    """
    mock_message = MagicMock()
    mock_message.content = "ok"
    mock_message.tool_calls = None
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = None
    mock_litellm.completion.return_value = mock_response

    result = llm_client.complete(
        [LLMMessage(role="user", content="hi")],
        phase="reproduce",
        skill="react_driver",
        node_id="node-7",
    )
    assert result.content == "ok"

    kwargs = mock_litellm.completion.call_args.kwargs
    assert kwargs["metadata"] == {
        "node_id": "node-7",
        "phase": "reproduce",
        "skill": "react_driver",
    }


@patch("ari.llm.client.litellm")
def test_complete_set_context_defaults_propagate(mock_litellm, llm_client):
    """set_context(...) values should appear in metadata when no per-call
    overrides are passed."""
    mock_message = MagicMock()
    mock_message.content = "ok"
    mock_message.tool_calls = None
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = None
    mock_litellm.completion.return_value = mock_response

    llm_client.set_context(node_id="n1", phase="ideate", skill="idea")
    llm_client.complete([LLMMessage(role="user", content="hi")])
    md = mock_litellm.completion.call_args.kwargs["metadata"]
    assert md == {"node_id": "n1", "phase": "ideate", "skill": "idea"}


@patch("ari.llm.client.litellm")
def test_stream(mock_litellm, llm_client):
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta.content = "Hello "

    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta.content = "world"

    chunk3 = MagicMock()
    chunk3.choices = [MagicMock()]
    chunk3.choices[0].delta.content = None

    mock_litellm.completion.return_value = iter([chunk1, chunk2, chunk3])

    messages = [LLMMessage(role="user", content="Hello")]
    result = list(llm_client.stream(messages))

    assert result == ["Hello ", "world"]
