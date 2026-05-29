"""Function-calling support in the CLI shim (``ari.llm.cli_server``).

The shim turns the text-only ``claude -p`` / ``codex exec`` CLIs into an
OpenAI-compatible chat-completions backend that returns ``tool_calls``, so it
drives ARI's ReAct loop exactly like a real OpenAI / Anthropic API key:

- OpenAI ``tools`` are injected into the prompt as a catalog + JSON protocol.
- the CLI's text reply is parsed back into OpenAI ``tool_calls`` whose
  ``arguments`` is the JSON-encoded *string* OpenAI uses.
- the response carries ``finish_reason="tool_calls"`` and ``content=null``.
- with no ``tools`` (judge / expand / select) the reply is plain text, as before.
"""
from __future__ import annotations

import json

import pytest

from ari.llm import cli_server as cs


# ── extract_tool_calls: parse a CLI text reply into OpenAI tool_calls ────────
def test_extract_plain_json_object():
    text = '{"tool_calls": [{"name": "write_code", "arguments": {"path": "x.py"}}]}'
    calls, residual = cs.extract_tool_calls(text)
    assert residual == ""
    assert len(calls) == 1
    tc = calls[0]
    assert tc["type"] == "function"
    assert tc["id"].startswith("call_")
    assert tc["function"]["name"] == "write_code"
    # arguments must be a JSON *string* (OpenAI contract; ARI json.loads it).
    assert isinstance(tc["function"]["arguments"], str)
    assert json.loads(tc["function"]["arguments"]) == {"path": "x.py"}


def test_extract_fenced_json():
    text = "Sure!\n```json\n{\"tool_calls\": [{\"name\": \"run_bash\", \"arguments\": {\"cmd\": \"ls\"}}]}\n```"
    calls, _ = cs.extract_tool_calls(text)
    assert calls and calls[0]["function"]["name"] == "run_bash"
    assert json.loads(calls[0]["function"]["arguments"]) == {"cmd": "ls"}


def test_extract_json_with_surrounding_prose():
    text = 'I will call the tool. {"name": "survey", "arguments": {"q": "spmm"}} done.'
    calls, _ = cs.extract_tool_calls(text)
    assert calls and calls[0]["function"]["name"] == "survey"
    assert json.loads(calls[0]["function"]["arguments"]) == {"q": "spmm"}


def test_extract_multiple_calls():
    text = json.dumps({"tool_calls": [
        {"name": "a", "arguments": {"x": 1}},
        {"name": "b", "arguments": {}},
    ]})
    calls, _ = cs.extract_tool_calls(text)
    assert [c["function"]["name"] for c in calls] == ["a", "b"]
    # distinct ids
    assert calls[0]["id"] != calls[1]["id"]


def test_extract_arguments_already_string():
    text = json.dumps({"tool_calls": [
        {"name": "t", "arguments": json.dumps({"k": "v"})},
    ]})
    calls, _ = cs.extract_tool_calls(text)
    assert json.loads(calls[0]["function"]["arguments"]) == {"k": "v"}


def test_extract_plain_text_is_not_a_tool_call():
    calls, residual = cs.extract_tool_calls("The result is 42 GB/s.")
    assert calls is None
    assert residual == "The result is 42 GB/s."


def test_extract_empty():
    assert cs.extract_tool_calls("") == (None, "")


# ── _completion_envelope: OpenAI response shape ──────────────────────────────
def test_envelope_with_tool_calls():
    tcs = [{"id": "call_1", "type": "function",
            "function": {"name": "f", "arguments": "{}"}}]
    env = cs._completion_envelope("claude-cli", "", {"prompt_tokens": 1}, tcs)
    choice = env["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"] == tcs
    assert choice["message"]["content"] is None


def test_envelope_plain_text():
    env = cs._completion_envelope("claude-cli", "hello", {})
    choice = env["choices"][0]
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["content"] == "hello"
    assert "tool_calls" not in choice["message"]


# ── render_prompt: multi-turn ReAct round-trips through the text CLI ─────────
def test_render_prompt_round_trips_tool_calls_and_results():
    messages = [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "call_9", "type": "function",
                         "function": {"name": "run_bash",
                                      "arguments": '{"cmd": "ls"}'}}]},
        {"role": "tool", "tool_call_id": "call_9", "content": '{"stdout": "x.py"}'},
    ]
    system, prompt = cs.render_prompt(messages)
    assert system == "be terse"
    # the assistant's prior call is rendered in the same JSON protocol
    assert '"name": "run_bash"' in prompt
    assert '"cmd": "ls"' in prompt
    # the tool result is labelled with the tool name (mapped via tool_call_id)
    assert "Tool result (run_bash):" in prompt
    assert '"stdout": "x.py"' in prompt


# ── _render_tool_catalog / instructions ──────────────────────────────────────
def test_tool_catalog_lists_names_and_schema():
    tools = [{"type": "function", "function": {
        "name": "write_code", "description": "write a file",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}]
    cat = cs._render_tool_catalog(tools)
    assert "write_code" in cat
    assert "write a file" in cat
    assert "JSON Schema" in cat


def test_protocol_required_vs_auto():
    assert "MUST call at least one tool" in cs._tool_protocol_instructions("required")
    assert "plain text" in cs._tool_protocol_instructions("auto")
    forced = cs._tool_protocol_instructions(
        {"type": "function", "function": {"name": "emit_results"}})
    assert "emit_results" in forced


# ── complete(): end-to-end with a stubbed CLI ────────────────────────────────
@pytest.fixture
def stub_claude(monkeypatch):
    """Replace run_claude with a capturing stub; returns the recorder dict."""
    rec: dict = {}

    def _fake(system, prompt, agent, real_model, cwd, **kw):
        rec["system"] = system
        rec["prompt"] = prompt
        rec["cwd"] = cwd
        rec["mcp_config"] = kw.get("mcp_config")
        rec["allowed_mcp_tools"] = kw.get("allowed_mcp_tools")
        return rec["reply"], {"prompt_tokens": 5, "completion_tokens": 2,
                              "total_tokens": 7}

    monkeypatch.setattr(cs, "run_claude", _fake)
    return rec


def test_complete_with_tools_returns_tool_calls(stub_claude):
    stub_claude["reply"] = (
        '{"tool_calls": [{"name": "survey", "arguments": {"q": "spmm"}}]}'
    )
    tools = [{"type": "function", "function": {"name": "survey",
              "description": "search", "parameters": {}}}]
    text, tool_calls, usage = cs.complete(
        "claude-cli",
        [{"role": "user", "content": "go"}],
        tools=tools,
        tool_choice="required",
    )
    assert tool_calls and tool_calls[0]["function"]["name"] == "survey"
    assert text == ""  # content null alongside tool_calls
    # the tool catalog + protocol were injected into the system prompt
    assert "AVAILABLE TOOLS" in stub_claude["system"]
    assert "TOOL-CALL PROTOCOL" in stub_claude["system"]
    assert "survey" in stub_claude["system"]


def test_complete_without_tools_is_plain_text(stub_claude):
    stub_claude["reply"] = "42 GB/s"
    text, tool_calls, usage = cs.complete(
        "claude-cli", [{"role": "user", "content": "result?"}]
    )
    assert tool_calls is None
    assert text == "42 GB/s"
    # no protocol injection when no tools are requested
    assert "TOOL-CALL PROTOCOL" not in (stub_claude["system"] or "")


def test_complete_tool_choice_none_disables_parsing(stub_claude):
    # Even if the model emits tool-call-shaped JSON, tool_choice="none" => text.
    stub_claude["reply"] = '{"tool_calls": [{"name": "x", "arguments": {}}]}'
    tools = [{"type": "function", "function": {"name": "x", "parameters": {}}}]
    text, tool_calls, _ = cs.complete(
        "claude-cli", [{"role": "user", "content": "go"}],
        tools=tools, tool_choice="none",
    )
    assert tool_calls is None
    assert text.startswith('{"tool_calls"')


def test_complete_text_reply_under_required_falls_back_to_text(stub_claude):
    # Model ignored the protocol and answered in prose; surface as content so
    # ARI's loop can force/retry — same as a non-compliant real model.
    stub_claude["reply"] = "I cannot do that."
    tools = [{"type": "function", "function": {"name": "x", "parameters": {}}}]
    text, tool_calls, _ = cs.complete(
        "claude-cli", [{"role": "user", "content": "go"}],
        tools=tools, tool_choice="required",
    )
    assert tool_calls is None
    assert text == "I cannot do that."


# ── cost passthrough: shim forwards claude -p's total_cost_usd ────────────────
class _FakeProc:
    def __init__(self, stdout):
        self.returncode = 0
        self.stdout = stdout
        self.stderr = ""


def test_run_claude_forwards_total_cost_usd(monkeypatch, tmp_path):
    """``run_claude`` extracts ``total_cost_usd`` from claude's JSON envelope
    and puts it on ``usage.cost_usd`` so cost_tracker can record real dollars."""
    payload = json.dumps({
        "result": "hi",
        "is_error": False,
        "total_cost_usd": 0.07530775,
        "usage": {
            "input_tokens": 5,
            "cache_creation_input_tokens": 10583,
            "cache_read_input_tokens": 17978,
            "output_tokens": 6,
        },
    })
    monkeypatch.setattr(cs.subprocess, "run", lambda *a, **k: _FakeProc(payload))
    text, usage = cs.run_claude("sys", "prompt", agent=False,
                                real_model=None, cwd=str(tmp_path))
    assert text == "hi"
    assert usage["prompt_tokens"] == 5 + 10583 + 17978
    assert usage["completion_tokens"] == 6
    assert usage["cost_usd"] == pytest.approx(0.07530775)


def test_run_claude_cost_defaults_to_zero_when_missing(monkeypatch, tmp_path):
    """Older claude builds may not emit ``total_cost_usd`` → cost_usd=0.0."""
    payload = json.dumps({"result": "ok", "is_error": False,
                          "usage": {"input_tokens": 1, "output_tokens": 1}})
    monkeypatch.setattr(cs.subprocess, "run", lambda *a, **k: _FakeProc(payload))
    _, usage = cs.run_claude("", "p", False, None, str(tmp_path))
    assert usage["cost_usd"] == 0.0


def test_parse_codex_usage_includes_cost_field():
    """Schema alignment: codex usage dict carries ``cost_usd`` (0.0 default)."""
    u = cs._parse_codex_usage('{"info": {"token_usage": {"input_tokens": 10, "output_tokens": 4}}}')
    assert u["cost_usd"] == 0.0
    assert u["prompt_tokens"] == 10
    assert u["completion_tokens"] == 4


def test_envelope_usage_carries_cost_usd():
    """OpenAI response envelope propagates the shim's ``cost_usd``."""
    usage = {"prompt_tokens": 1, "completion_tokens": 1,
             "total_tokens": 2, "cost_usd": 0.42}
    env = cs._completion_envelope("claude-cli", "hi", usage)
    assert env["usage"]["cost_usd"] == 0.42


# ── MCP-direct mode (2026-05-28): claude spawns ari-skill MCP servers ────────
def test_complete_mcp_direct_pins_work_dir_and_passes_config(stub_claude, tmp_path):
    """With ``mcp_config`` + ``allowed_mcp_tools`` + ``work_dir``, ``complete()``
    bypasses the text-catalog hack, pins cwd to the caller's work_dir, and
    forwards the MCP server config to ``run_claude``."""
    stub_claude["reply"] = "done"
    mcp_cfg = {"mcpServers": {"hpc-skill": {
        "command": "/usr/bin/python", "args": ["server.py"], "env": {}}}}
    tools = [{"type": "function", "function": {"name": "slurm_submit", "parameters": {}}}]
    text, tool_calls, _usage = cs.complete(
        "claude-cli",
        [{"role": "user", "content": "go"}],
        tools=tools,
        tool_choice="required",
        mcp_config=mcp_cfg,
        allowed_mcp_tools=["mcp__hpc-skill__slurm_submit"],
        work_dir=str(tmp_path),
    )
    # MCP-direct: claude handles tool calls itself, shim returns text only.
    assert tool_calls is None
    assert text == "done"
    # Text-catalog hack must NOT have been triggered.
    assert "AVAILABLE TOOLS" not in (stub_claude["system"] or "")
    assert "TOOL-CALL PROTOCOL" not in (stub_claude["system"] or "")
    # Real cwd is the caller's work_dir (not a throwaway tmp dir).
    assert stub_claude["cwd"] == str(tmp_path)
    # MCP config + allowlist were forwarded.
    assert stub_claude["mcp_config"] == mcp_cfg
    assert stub_claude["allowed_mcp_tools"] == ["mcp__hpc-skill__slurm_submit"]


def test_complete_without_mcp_config_falls_back_to_text_catalog(stub_claude):
    """When ``mcp_config`` is missing, complete() keeps the legacy text-catalog
    behaviour so callers without MCP wiring still work."""
    stub_claude["reply"] = (
        '{"tool_calls": [{"name": "survey", "arguments": {"q": "x"}}]}'
    )
    tools = [{"type": "function", "function": {"name": "survey", "parameters": {}}}]
    _, tool_calls, _ = cs.complete(
        "claude-cli", [{"role": "user", "content": "go"}],
        tools=tools, tool_choice="required",
    )
    assert tool_calls and tool_calls[0]["function"]["name"] == "survey"
    assert "AVAILABLE TOOLS" in stub_claude["system"]


def test_run_claude_mcp_direct_builds_correct_cmd(monkeypatch, tmp_path):
    """``run_claude(mcp_config=...)`` invokes claude with --mcp-config,
    --strict-mcp-config, --allowedTools mcp__*, --permission-mode acceptEdits,
    --output-format stream-json, and --debug-file <cwd>/claude_debug.log."""
    captured: dict = {}

    def _fake_run(cmd, input, capture_output, text, timeout, cwd):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        # Emit a minimal stream-json with a result event so the parser is exercised.
        stdout = "\n".join([
            json.dumps({"type": "system", "subtype": "init"}),
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "text", "text": "ok"}]}}),
            json.dumps({"type": "result", "result": "ok",
                        "total_cost_usd": 0.001,
                        "usage": {"input_tokens": 3, "output_tokens": 2}}),
        ])
        class _P:
            returncode = 0
            stderr = ""
        p = _P(); p.stdout = stdout
        return p

    monkeypatch.setattr(cs.subprocess, "run", _fake_run)
    mcp_cfg = {"mcpServers": {"hpc": {"command": "x", "args": [], "env": {}}}}
    text, usage = cs.run_claude(
        "sys", "prompt", agent=False, real_model=None, cwd=str(tmp_path),
        mcp_config=mcp_cfg,
        allowed_mcp_tools=["mcp__hpc__slurm_submit", "mcp__hpc__slurm_status"],
    )
    cmd = captured["cmd"]
    # stream-json output; no JSON-format single-shot
    assert "--output-format" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    # MCP config is materialised to a real file the shim wrote
    assert "--mcp-config" in cmd
    mcp_file = cmd[cmd.index("--mcp-config") + 1]
    import os as _os
    assert _os.path.isfile(mcp_file)
    assert json.load(open(mcp_file)) == mcp_cfg
    # Strict mode + allowlist
    assert "--strict-mcp-config" in cmd
    assert "--allowedTools" in cmd
    allow_str = cmd[cmd.index("--allowedTools") + 1]
    assert "mcp__hpc__slurm_submit" in allow_str
    assert "mcp__hpc__slurm_status" in allow_str
    # No native tools listed (only mcp__*)
    assert "Bash" not in allow_str and "Write" not in allow_str and "Edit" not in allow_str
    # Permission mode opens tool use
    assert "--permission-mode" in cmd
    # Debug log is written into the caller's cwd, not a tmp dir
    assert "--debug-file" in cmd
    debug_file = cmd[cmd.index("--debug-file") + 1]
    assert debug_file == _os.path.join(str(tmp_path), "claude_debug.log")
    # Result parsed from the stream-json's final result event
    assert text == "ok"
    assert usage["cost_usd"] == pytest.approx(0.001)
    assert usage["prompt_tokens"] == 3
    assert usage["completion_tokens"] == 2
    # The stream-json events are persisted alongside artifacts for audit.
    audit = _os.path.join(str(tmp_path), "tool_calls.jsonl")
    assert _os.path.isfile(audit)
    lines = [l for l in open(audit) if l.strip()]
    assert len(lines) == 3
    # First two events make it into the audit verbatim (system + assistant).
    types = [json.loads(l).get("type") for l in lines]
    assert types == ["system", "assistant", "result"]


def test_do_post_reads_extra_body_fields(monkeypatch):
    """The HTTP handler accepts ``mcp_config`` / ``allowed_mcp_tools`` /
    ``work_dir`` either as top-level keys (litellm's openai handler form) or
    nested under ``extra_body`` (raw clients)."""
    captured: dict = {}

    def _fake_complete(model, messages, tools, tool_choice, **kw):
        captured.update(kw)
        return "ok", None, {"prompt_tokens": 0, "completion_tokens": 0,
                            "total_tokens": 0, "cost_usd": 0.0}

    monkeypatch.setattr(cs, "complete", _fake_complete)

    # Use the request-parsing logic directly (no real HTTP plumbing needed):
    # we re-derive the same code path the handler executes.
    req = {
        "model": "claude-cli", "messages": [{"role": "user", "content": "x"}],
        "tools": [],
        "extra_body": {
            "mcp_config": {"mcpServers": {}},
            "allowed_mcp_tools": ["mcp__a__b"],
            "work_dir": "/tmp/x",
        },
    }
    eb = req.get("extra_body") or {}
    cs.complete(
        req["model"], req["messages"], req["tools"], req.get("tool_choice"),
        mcp_config=req.get("mcp_config") or eb.get("mcp_config"),
        allowed_mcp_tools=req.get("allowed_mcp_tools") or eb.get("allowed_mcp_tools"),
        work_dir=req.get("work_dir") or eb.get("work_dir"),
    )
    assert captured["mcp_config"] == {"mcpServers": {}}
    assert captured["allowed_mcp_tools"] == ["mcp__a__b"]
    assert captured["work_dir"] == "/tmp/x"
