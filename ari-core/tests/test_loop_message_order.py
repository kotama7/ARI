"""Tool-message protocol ordering (P1 of PLAN_claims_fulfillment_final).

The API requires every assistant tool_calls message to be followed by its complete,
contiguous block of tool responses. On 3 of 5 real runs the ROOT node died with
"tool_call_ids did not have response messages": a handler-driven USER injection
(the contract obligation, right after make_metric_spec) was appended INSIDE the
results loop, landing BETWEEN the responses of an assistant that had batched two
tool_calls. The injections are now deferred past the loop; repair_tool_message_order
is the defense-in-depth guard applied to the send window.
"""
from __future__ import annotations

from ari.agent.loop import repair_tool_message_order


def _asst(*tc_ids):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": t, "function": {"name": "f", "arguments": "{}"}}
                           for t in tc_ids]}


def _tool(tc_id, content="ok"):
    return {"role": "tool", "tool_call_id": tc_id, "content": content}


def test_interleaved_user_moved_after_tool_block():
    # The EXACT real-run failure shape: user message between two tool responses.
    msgs = [
        {"role": "system", "content": "s"},
        _asst("a", "b"),
        _tool("a"),
        {"role": "user", "content": "METRIC-CORRECTNESS CONTRACT ..."},  # injected
        _tool("b"),
        {"role": "user", "content": "next step?"},
    ]
    out = repair_tool_message_order(msgs)
    roles = [(m["role"], m.get("tool_call_id")) for m in out]
    assert roles == [
        ("system", None),
        ("assistant", None),
        ("tool", "a"),
        ("tool", "b"),                      # contiguous block restored
        ("user", None),                     # obligation moved AFTER the block
        ("user", None),
    ]
    assert "METRIC-CORRECTNESS" in out[4]["content"]   # order among displaced kept


def test_incomplete_pairing_drops_assistant_keeps_innocents():
    # window cut lost tool(b): the broken assistant + its partial response are
    # dropped instead of being sent (the API would reject the whole request).
    msgs = [
        {"role": "system", "content": "s"},
        _asst("a", "b"),
        _tool("a"),
        {"role": "user", "content": "carry on"},
        # tool("b") missing
    ]
    out = repair_tool_message_order(msgs)
    assert [(m["role"]) for m in out] == ["system", "user"]
    assert out[1]["content"] == "carry on"


def test_valid_sequences_unchanged():
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "go"},
        _asst("x"),
        _tool("x"),
        {"role": "assistant", "content": "done"},
    ]
    assert repair_tool_message_order(msgs) == msgs


def test_multiple_assistants_each_repaired_independently():
    msgs = [
        _asst("a"), _tool("a"),
        _asst("b", "c"), _tool("b"), {"role": "user", "content": "mid"}, _tool("c"),
        _asst("d"), _tool("d"),
    ]
    out = repair_tool_message_order(msgs)
    ids = [m.get("tool_call_id") for m in out if m.get("role") == "tool"]
    assert ids == ["a", "b", "c", "d"]
    # the mid user message sits after the b/c block, before the next assistant
    u = next(i for i, m in enumerate(out) if m.get("role") == "user")
    assert out[u - 1].get("tool_call_id") == "c"
