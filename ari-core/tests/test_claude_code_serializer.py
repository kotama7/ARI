"""Tests for ari.llm.claude_code.serializer — deterministic prompt building."""

from __future__ import annotations

import pytest

from ari.llm.claude_code.serializer import (
    ClaudeCodeSerializeError,
    build_repair_prompt,
    serialize_messages,
)

MESSAGES = [
    {"role": "user", "content": "first question"},
    {"role": "assistant", "content": "first answer"},
    {"role": "user", "content": "second question"},
]
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def test_same_input_same_prompt():
    a = serialize_messages(MESSAGES, system="SYS", response_schema=SCHEMA)
    b = serialize_messages(
        [dict(m) for m in MESSAGES], system="SYS", response_schema=SCHEMA
    )
    assert a.prompt == b.prompt
    assert a.system == b.system
    assert a.schema_json == b.schema_json


def test_role_order_preserved():
    out = serialize_messages(MESSAGES)
    first_u = out.prompt.index("first question")
    first_a = out.prompt.index("first answer")
    second_u = out.prompt.index("second question")
    assert first_u < first_a < second_u
    # Message envelope format per docs.
    assert '<message role="user">' in out.prompt
    assert '<message role="assistant">' in out.prompt
    assert out.prompt.startswith("<conversation>")


def test_system_messages_folded_into_system_text():
    out = serialize_messages(
        [{"role": "system", "content": "in-band sys"}] + MESSAGES,
        system="explicit sys",
    )
    assert "explicit sys" in out.system
    assert "in-band sys" in out.system
    # System text stays out of the conversation body.
    assert "in-band sys" not in out.prompt


def test_schema_embedded_in_prompt_transport():
    out = serialize_messages(MESSAGES, response_schema=SCHEMA)
    assert "<response_contract>" in out.prompt
    assert '"ok"' in out.prompt
    assert out.schema_json is not None
    # Canonical (sorted-keys) schema JSON is stable.
    assert out.schema_json == serialize_messages(
        MESSAGES, response_schema=dict(reversed(list(SCHEMA.items())))
    ).schema_json


def test_schema_not_embedded_for_native_transport():
    out = serialize_messages(
        MESSAGES, response_schema=SCHEMA, embed_schema_in_prompt=False
    )
    assert "<response_contract>" in out.prompt
    assert "<json_schema>" not in out.prompt
    assert out.schema_json is not None


def test_no_schema_no_contract_block():
    out = serialize_messages(MESSAGES)
    assert "<response_contract>" not in out.prompt
    assert out.schema_json is None


def test_tool_role_rejected():
    with pytest.raises(ClaudeCodeSerializeError):
        serialize_messages(
            [{"role": "tool", "content": "result", "tool_call_id": "t1"}]
        )


def test_assistant_tool_calls_rejected():
    with pytest.raises(ClaudeCodeSerializeError):
        serialize_messages(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "t1", "type": "function"}],
                }
            ]
        )


def test_llmmessage_dataclass_accepted():
    from ari.llm.client import LLMMessage

    out = serialize_messages([LLMMessage(role="user", content="hello")])
    assert "hello" in out.prompt


def test_repair_prompt_is_deterministic_and_carries_errors():
    base = serialize_messages(MESSAGES, response_schema=SCHEMA)
    r1 = build_repair_prompt(base, "not json", ["<root>: 'ok' is required"])
    r2 = build_repair_prompt(base, "not json", ["<root>: 'ok' is required"])
    assert r1 == r2
    assert "previous_invalid_output" in r1
    assert "'ok' is required" in r1
    assert base.prompt in r1
