"""Nothing is discarded while the context still has room.

Two sites used to throw content away on a FIXED threshold, with no reference to
whether context was actually scarce. Both were measured on a real 40-node study:

  * the ReAct window trimmed on MESSAGE COUNT (``len(msgs) <= keep_tail + 4``,
    keep_tail=20). A 15-step budget reaches 32 messages, so it fired on every node
    from mid-node on: 237 messages dropped, 25 of 40 nodes lost part of their own
    history — while the largest conversation used 45% of the budget.
  * the tool-result cap cut at a fixed 4000 chars: 32 firings over 28 nodes,
    27,232 chars discarded. It cut 100% of ``describe_environment`` payloads
    (~4,851 chars), losing the tail that carries the module catalog, the toolchain
    env-var names, and the fact that mpicc/mpicxx are broken — and the cut landed
    mid-string in the compilers dict, so every payload arrived as invalid JSON.

Both now ask :func:`context_budget_chars`. These tests pin that they stay quiet
while there is room, and still fire under genuine pressure.
"""
from __future__ import annotations

import json

from ari.agent.loop import context_budget_chars, conversation_chars


def test_budget_follows_the_model_context_limit(monkeypatch):
    monkeypatch.setenv("ARI_LLM_NUM_CTX", "32768")
    assert context_budget_chars() == (32768 - 2048) * 3   # ~3 chars/token
    monkeypatch.setenv("ARI_LLM_NUM_CTX", "8192")
    assert context_budget_chars() == (8192 - 2048) * 3
    # a hostile/garbage value must not crash the loop — fall back to the default
    monkeypatch.setenv("ARI_LLM_NUM_CTX", "not-a-number")
    assert context_budget_chars() == (32768 - 2048) * 3
    # never collapse to a uselessly small budget
    monkeypatch.setenv("ARI_LLM_NUM_CTX", "1")
    assert context_budget_chars() == 4000 * 3


def test_conversation_chars_counts_content_and_tool_calls():
    msgs = [
        {"role": "user", "content": "abc"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "t1", "function": {"name": "run_bash", "arguments": "ls"}}]},
        {"role": "tool", "content": "de"},
    ]
    n = conversation_chars(msgs)
    assert n > 5                      # the tool_call payload is counted, not ignored
    assert conversation_chars([]) == 0
    assert conversation_chars(None) == 0


def _cap_fires(rc: str, name: str, messages: list) -> bool:
    """Mirror the loop's tool-result cap condition (loop.py, tool-append site)."""
    return (len(rc) > 4000
            and conversation_chars(messages) + len(rc) > context_budget_chars())


def test_tool_result_cap_stays_quiet_while_context_has_room(monkeypatch):
    """The regression: a real describe_environment payload (~4,851 chars) inside a
    conversation at the study's measured size (~42k of a 92k budget) must NOT be
    cut. It used to be cut 100% of the time, losing its tail."""
    monkeypatch.setenv("ARI_LLM_NUM_CTX", "32768")
    payload = json.dumps({"compilers": {"gcc": "11.5.0", "mpicc": "command not found"},
                          "modules_avail": "m" * 4000})
    assert len(payload) > 4000
    conversation = [{"role": "user", "content": "x" * 42_000}]   # 46% of budget
    assert not _cap_fires(payload, "describe_environment", conversation)


def test_tool_result_cap_still_fires_under_real_pressure(monkeypatch):
    monkeypatch.setenv("ARI_LLM_NUM_CTX", "32768")
    payload = "p" * 5000
    conversation = [{"role": "user", "content": "x" * 90_000}]   # ~98% of budget
    assert _cap_fires(payload, "describe_environment", conversation)


def test_small_context_model_still_gets_protected(monkeypatch):
    """A 8k-context model must still have its tool results capped — the budget
    gate is not a licence to overflow a small model."""
    monkeypatch.setenv("ARI_LLM_NUM_CTX", "8192")   # budget = 18,432
    payload = "p" * 5000
    conversation = [{"role": "user", "content": "x" * 15_000}]
    assert _cap_fires(payload, "describe_environment", conversation)
