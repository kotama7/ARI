"""Text-JSON tool-call recovery + safe parent-log rendering (handoff study).

Root cause of the "every ollama node scores 0" run: ollama-served qwen2.5-coder
emits a tool call as assistant *content* — ``{"name": "write_code", "arguments":
{...}}`` (often ```json-fenced) — instead of a structured ``tool_calls`` entry.
The loop's JSON branch only recognises a ``{"status": ...}`` finish, so the text
call was neither executed nor terminal: it burned a step as unrecognised text and
the node never ran anything. gpt-oss (OpenAI/Cerebras) emits structured calls and
was never affected — so the failure was ollama-specific, not a schema bug.

Two fixes are guarded here:
  (a) ``_extract_text_toolcall`` recovers a text-JSON call into the exact shape a
      structured entry has, so the normal execution path runs it.
  (b) ``_render_parent_execution_log`` reconstructs a parent's log in the ``→
      tool(args)`` / ``← result`` arrow vocabulary only — never the raw
      ``[user]``/``[assistant]`` transcript that made full_log-arm children
      few-shot-imitate the format and emit their own calls as text.
"""
import json

from ari.agent.loop import _extract_text_toolcall, _render_parent_execution_log

_TOOLS = [
    {"type": "function", "function": {"name": "write_code", "parameters": {}}},
    {"type": "function", "function": {"name": "run_bash", "parameters": {}}},
    {"type": "function", "function": {"name": "emit_results", "parameters": {}}},
]


def test_recovers_plain_text_json_call():
    tc = _extract_text_toolcall(
        '{"name": "write_code", "arguments": {"filename": "c.c", "code": "x"}}', _TOOLS)
    assert tc is not None
    assert tc["function"]["name"] == "write_code"
    # arguments must be a JSON *string* (execute_tool_calls does json.loads on it)
    assert json.loads(tc["function"]["arguments"]) == {"filename": "c.c", "code": "x"}


def test_recovers_fenced_call_with_trailing_junk():
    # ```json fence + a hallucinated "[user] Step N..." continuation after the obj.
    raw = ('```json\n{"name": "run_bash", "arguments": {"command": "make"}}\n```\n'
           '[user] Step 2/35 (33 steps remaining): call a tool...')
    tc = _extract_text_toolcall(raw, _TOOLS)
    assert tc is not None and tc["function"]["name"] == "run_bash"
    assert json.loads(tc["function"]["arguments"]) == {"command": "make"}


def test_recovers_call_with_think_block():
    raw = '<think>I should write the file</think>\n{"name":"write_code","arguments":{"filename":"a"}}'
    tc = _extract_text_toolcall(raw, _TOOLS)
    assert tc is not None and tc["function"]["name"] == "write_code"


def test_finish_blob_is_not_recovered():
    # {"status": ...} is a finish — must fall through to the finish handler.
    assert _extract_text_toolcall('{"status": "success", "metrics": {"g": 1.0}}', _TOOLS) is None


def test_unknown_tool_is_not_recovered():
    # a call to a tool outside the allowlist (e.g. the seeded "gemm" reference)
    assert _extract_text_toolcall('{"name": "gemm", "arguments": {"n": 8}}', _TOOLS) is None


def test_prose_is_not_recovered():
    assert _extract_text_toolcall("Let me think about the approach first.", _TOOLS) is None
    assert _extract_text_toolcall("", _TOOLS) is None
    assert _extract_text_toolcall('{"name": "write_code"}', _TOOLS) is None  # no arguments


def test_no_tools_means_no_recovery():
    assert _extract_text_toolcall('{"name": "write_code", "arguments": {}}', None) is None


def _write_full_log(pdir, *, trace_log=None, messages=None):
    (pdir).mkdir(parents=True, exist_ok=True)
    (pdir / "full_log.json").write_text(json.dumps({
        "trace_log": trace_log or [],
        "messages": messages or [],
    }))


def test_render_prefers_trace_log(tmp_path):
    p = tmp_path / "parent"
    _write_full_log(p, trace_log=["→ run_bash({\"command\":\"ls\"})", "  ← ok"])
    out = _render_parent_execution_log(p, limit=10_000)
    assert "→ run_bash" in out and "← ok" in out


def test_render_fallback_is_arrow_only_no_transcript(tmp_path):
    # A poisoned parent: empty trace_log, text-JSON assistant calls, and the
    # ephemeral step-nudge user turns. The reconstruction must NOT reproduce the
    # [user]/[assistant] transcript (that is what induced child imitation).
    p = tmp_path / "parent"
    _write_full_log(p, trace_log=[], messages=[
        {"role": "system", "content": "You are a research agent..."},
        {"role": "user", "content": "Experiment goal: optimize GEMM..."},   # goal
        {"role": "assistant",
         "content": '{"name": "write_code", "arguments": {"filename": "c.c", "code": "x"}}'},
        {"role": "user",
         "content": "Step 1/35 (34 steps remaining): Do NOT write text plans..."},  # nudge
        {"role": "assistant", "content": '{"name": "run_bash", "arguments": {"command": "make"}}'},
        {"role": "tool", "content": "compiled ok"},
    ])
    out = _render_parent_execution_log(p, limit=10_000)
    assert "[assistant]" not in out
    assert "[user]" not in out
    assert "steps remaining" not in out       # step-nudge scaffolding dropped
    assert "→ write_code(" in out             # text-JSON call normalised to arrow
    assert "→ run_bash(" in out
    assert "← compiled ok" in out             # tool result kept in arrow form


def test_render_empty_when_no_content(tmp_path):
    p = tmp_path / "parent"
    _write_full_log(p, trace_log=[], messages=[
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "goal"},
    ])
    assert _render_parent_execution_log(p, limit=10_000) == ""
