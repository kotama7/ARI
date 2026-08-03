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
import os

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
        mcp_file = cmd[cmd.index("--mcp-config") + 1]
        captured["mcp_config_on_disk"] = json.load(open(mcp_file))
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
        p = _P()
        p.stdout = stdout
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
    # MCP config exists for the child invocation, then is removed so it cannot
    # become a persistent credential artifact.
    assert "--mcp-config" in cmd
    mcp_file = cmd[cmd.index("--mcp-config") + 1]
    import os as _os
    assert not _os.path.exists(mcp_file)
    assert captured["mcp_config_on_disk"] == mcp_cfg
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
    lines = [line for line in open(audit) if line.strip()]
    assert len(lines) == 3
    # First two events make it into the audit verbatim (system + assistant).
    types = [json.loads(line).get("type") for line in lines]
    assert types == ["system", "assistant", "result"]


# ── Shim isolation hardening (strict MCP / max-turns / env warning) ─────────
def _capture_claude_cmd(monkeypatch, tmp_path, **run_claude_kw) -> list[str]:
    """Invoke run_claude with a stubbed subprocess; return the argv built."""
    captured: dict = {}

    def _fake_run(cmd, input, capture_output, text, timeout, cwd):
        captured["cmd"] = cmd
        return _FakeProc(json.dumps({"result": "ok", "is_error": False,
                                     "usage": {}}))

    monkeypatch.setattr(cs.subprocess, "run", _fake_run)
    cs.run_claude("sys", "p", agent=False, real_model=None, cwd=str(tmp_path),
                  **run_claude_kw)
    return captured["cmd"]


def test_strict_mcp_config_passed_in_text_mode(monkeypatch, tmp_path):
    """Text mode (no mcp_config) must ALSO pass --strict-mcp-config so a
    nested claude never boots ambient project MCP servers (observed: 15
    ari-skill servers forked per plain-text judge/select call)."""
    cmd = _capture_claude_cmd(monkeypatch, tmp_path)
    assert "--strict-mcp-config" in cmd
    assert "--mcp-config" not in cmd  # no explicit config in text mode


def test_strict_mcp_config_passed_exactly_once_in_mcp_mode(monkeypatch, tmp_path):
    """MCP-direct mode keeps --strict-mcp-config (now from the common path)
    exactly once, alongside the explicit --mcp-config strict mode honors."""
    captured: dict = {}

    def _fake_run(cmd, input, capture_output, text, timeout, cwd):
        captured["cmd"] = cmd
        return _FakeProc(json.dumps({"type": "result", "result": "ok",
                                     "usage": {}}))

    monkeypatch.setattr(cs.subprocess, "run", _fake_run)
    cs.run_claude(
        "sys", "p", agent=False, real_model=None, cwd=str(tmp_path),
        mcp_config={"mcpServers": {}}, allowed_mcp_tools=["mcp__a__b"],
    )
    cmd = captured["cmd"]
    assert cmd.count("--strict-mcp-config") == 1
    assert "--mcp-config" in cmd


def test_max_turns_flag_appended_iff_knob_set(monkeypatch, tmp_path):
    monkeypatch.setattr(cs, "CLAUDE_MAX_TURNS", 25)
    cmd = _capture_claude_cmd(monkeypatch, tmp_path)
    assert cmd[cmd.index("--max-turns") + 1] == "25"


def test_max_turns_flag_absent_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(cs, "CLAUDE_MAX_TURNS", 0)
    cmd = _capture_claude_cmd(monkeypatch, tmp_path)
    assert "--max-turns" not in cmd


def test_env_int_parses_and_defaults(monkeypatch):
    monkeypatch.setenv("ARI_CLI_SHIM_CLAUDE_MAX_TURNS", "30")
    assert cs._env_int("ARI_CLI_SHIM_CLAUDE_MAX_TURNS") == 30
    monkeypatch.setenv("ARI_CLI_SHIM_CLAUDE_MAX_TURNS", "not-a-number")
    assert cs._env_int("ARI_CLI_SHIM_CLAUDE_MAX_TURNS") == 0
    monkeypatch.delenv("ARI_CLI_SHIM_CLAUDE_MAX_TURNS", raising=False)
    assert cs._env_int("ARI_CLI_SHIM_CLAUDE_MAX_TURNS") == 0


def test_env_contamination_warning_fires_on_claude_code_vars(caplog):
    with caplog.at_level("WARNING", logger="ari.llm.cli_server"):
        cs._warn_claude_env_contamination(
            {"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli", "HOME": "/h"})
    text = caplog.text
    assert "CLAUDECODE" in text
    assert "CLAUDE_CODE_ENTRYPOINT" in text
    assert "env -i" in text  # recommends the sanitized launch recipe


def test_env_contamination_warning_silent_on_clean_env(caplog):
    with caplog.at_level("WARNING", logger="ari.llm.cli_server"):
        cs._warn_claude_env_contamination({"HOME": "/h", "PATH": "/bin"})
    assert caplog.records == []


def test_mcp_credential_refs_materialize_only_in_local_copy(monkeypatch):
    source = {
        "mcpServers": {
            "paper": {
                "command": "python",
                "args": ["server.py"],
                "env": {"PATH": "/usr/bin"},
                "_ariCredentialEnv": ["OPENAI_API_KEY"],
            }
        }
    }
    monkeypatch.setenv("OPENAI_API_KEY", "credential-marker")

    materialized = cs._materialize_mcp_credential_env(source)

    server = materialized["mcpServers"]["paper"]
    assert server["env"]["OPENAI_API_KEY"] == "credential-marker"
    assert "_ariCredentialEnv" not in server
    # The HTTP-safe request object is not mutated and contains no value.
    assert source["mcpServers"]["paper"]["_ariCredentialEnv"] == [
        "OPENAI_API_KEY"
    ]
    assert "credential-marker" not in json.dumps(source)

    with pytest.raises(ValueError, match="is unavailable"):
        cs._materialize_mcp_credential_env(source, source_env={})


def test_run_claude_redacts_local_credentials_from_outputs_and_audit(
    monkeypatch, tmp_path
):
    secret = "claude-local-secret-92814"
    captured: dict = {}

    def _fake_run(cmd, input, capture_output, text, timeout, cwd):
        mcp_file = cmd[cmd.index("--mcp-config") + 1]
        on_disk = json.load(open(mcp_file))
        assert on_disk["mcpServers"]["paper"]["env"]["OPENAI_API_KEY"] == secret
        captured["debug_file"] = cmd[cmd.index("--debug-file") + 1]

        class _P:
            returncode = 0
            stderr = f"debug credential={secret}"

        result = {
            "type": "result",
            "result": f"provider returned {secret}",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        process = _P()
        process.stdout = json.dumps(result)
        return process

    monkeypatch.setattr(cs.subprocess, "run", _fake_run)
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    config = {
        "mcpServers": {
            "paper": {
                "command": "python",
                "args": ["server.py"],
                "env": {},
                "_ariCredentialEnv": ["OPENAI_API_KEY"],
            }
        }
    }

    response, _usage = cs.run_claude(
        "system",
        "prompt",
        agent=False,
        real_model=None,
        cwd=str(tmp_path),
        mcp_config=config,
        allowed_mcp_tools=["mcp__paper__review"],
    )

    assert captured["debug_file"] == os.devnull
    assert secret not in response
    assert "<redacted:credential>" in response
    audit = (tmp_path / "tool_calls.jsonl").read_text(encoding="utf-8")
    assert secret not in audit
    assert "<redacted:credential>" in audit


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


# ── MCP delegation: bare tool names must be resolvable (2026-07-20) ──────────
#
# ARI's agent prompts name tools BARE (`call survey() NOW`). Under MCP
# delegation claude only has `mcp__<server>__<tool>`, so a bare name fails with
# `Error: No such tool available: survey`. Observed live: the delegated model
# called survey(), got that error, and burned the node's whole step budget
# re-probing — the exploration phase produced ZERO artifacts. The shim is the
# only layer holding both vocabularies, so it publishes the mapping.

def test_name_resolution_note_is_empty_without_delegation():
    """No delegation => the prompt must stay byte-identical."""
    from ari.llm.cli_server import mcp_name_resolution_note

    assert mcp_name_resolution_note(None) == ""
    assert mcp_name_resolution_note([]) == ""
    # entries that are not fully-qualified MCP names contribute nothing
    assert mcp_name_resolution_note(["survey", "mcp__onlytwo"]) == ""


def test_name_resolution_note_maps_bare_to_qualified():
    from ari.llm.cli_server import mcp_name_resolution_note

    note = mcp_name_resolution_note([
        "mcp__web-skill__survey",
        "mcp__idea-skill__generate_ideas",
    ])
    assert "survey()  ->  mcp__web-skill__survey" in note
    assert "generate_ideas()  ->  mcp__idea-skill__generate_ideas" in note
    # the exact failure string the model hit, so it recognises the situation
    assert "No such tool" in note
    # a tool name that itself contains "__" is not truncated
    deep = mcp_name_resolution_note(["mcp__s__a__b"])
    assert "a__b()  ->  mcp__s__a__b" in deep


def test_delegated_claude_gets_the_mapping_in_its_system_prompt(monkeypatch, tmp_path):
    """End-to-end at the shim boundary: the spawned `claude` must receive the
    table, and a NON-delegating call must not."""
    from ari.llm import cli_server

    seen = {}

    class _Proc:
        returncode = 0
        stdout = '{"type":"result","result":"ok"}'
        stderr = ""

    def _fake_run(cmd, prompt, cwd):
        seen["cmd"] = list(cmd)
        return _Proc()

    monkeypatch.setattr(cli_server, "_run", _fake_run)

    def _system_prompt_of(cmd):
        return cmd[cmd.index("--system-prompt") + 1] if "--system-prompt" in cmd else ""

    # (a) delegating
    cli_server.run_claude(
        "SYSTEM: call survey() NOW.", "go", False, None, str(tmp_path),
        mcp_config={"mcpServers": {"web-skill": {"command": "x", "args": []}}},
        allowed_mcp_tools=["mcp__web-skill__survey"],
    )
    sp = _system_prompt_of(seen["cmd"])
    assert "SYSTEM: call survey() NOW." in sp        # caller's prompt preserved
    assert "mcp__web-skill__survey" in sp            # ... plus the mapping

    # (b) NOT delegating -> byte-identical to the caller's own prompt
    seen.clear()
    cli_server.run_claude(
        "SYSTEM: call survey() NOW.", "go", False, None, str(tmp_path),
    )
    assert _system_prompt_of(seen["cmd"]) == "SYSTEM: call survey() NOW."


# ── delegation must not be killed by the phase-vocabulary mismatch ───────────
#
# `complete(phase=...)` is a COST-ATTRIBUTION label ("react", "agent",
# "paper_judge"); `to_claude_mcp_config(phase=...)` filters on the SKILL-ROUTING
# vocabulary ("bfts", "paper", "reproduce"). Passing the former to the latter
# returned ZERO servers for every agent-loop call, so `if mcp_cfg and allowed`
# fell through and delegation NEVER fired for the phase that most needs tools.
# Measured live 2026-07-20: to_claude_mcp_config(phase="coding") -> 0 servers /
# 0 tools, while phase=None -> 13 servers / 62 tools.

class _FakeMCP:
    """Records the phase it is asked for; mimics the real phase filter."""

    BY_PHASE = {
        None: (["web-skill", "idea-skill"],
               ["mcp__web-skill__survey", "mcp__idea-skill__generate_ideas"]),
        "bfts": (["idea-skill"], ["mcp__idea-skill__generate_ideas"]),
    }

    def __init__(self):
        self.asked = []

    def to_claude_mcp_config(self, phase=None):
        self.asked.append(phase)
        servers, allowed = self.BY_PHASE.get(phase, ([], []))
        return ({"mcpServers": {s: {"command": "x", "args": []}} for s in servers}
                if servers else {}), allowed


def _shim_client():
    from ari.config import LLMConfig
    from ari.llm.client import LLMClient
    return LLMClient(LLMConfig(backend="cli-shim", model="claude-cli:sonnet",
                               base_url="http://127.0.0.1:8900/v1"))


def test_delegation_does_not_ask_for_the_cost_attribution_phase(monkeypatch):
    """The regression: a cost label like "react" is not a skill-routing phase."""
    import litellm

    from ari.llm import client as _c

    captured = {}

    def _fake_completion(**kw):
        captured.update(kw)
        class _M:
            content = "ok"
            tool_calls = None
        class _C:
            message = _M()
        class _R:
            choices = [_C()]
            usage = None
        return _R()

    monkeypatch.setattr(litellm, "completion", _fake_completion)
    cli = _shim_client()
    cli.mcp_client = _FakeMCP()
    tools = [{"type": "function", "function": {"name": "survey"}}]

    cli.complete([{"role": "user", "content": "go"}], tools=tools,
                 phase="react", skill="agent_loop")

    # it must NOT have queried the cost label
    assert "react" not in cli.mcp_client.asked, (
        "delegation asked to_claude_mcp_config for the cost-attribution phase"
    )
    eb = captured.get("extra_body") or {}
    assert eb.get("mcp_config"), "delegation did not fire for the agent phase"
    assert cli.last_request_delegated is True
    assert _c._filter_allowed_to_offered is not None


def test_delegated_tools_equal_the_tools_ari_advertised(monkeypatch):
    """The delegated set is the offered set — the two vocabularies cannot drift."""
    import litellm

    def _fake_completion(**kw):
        _fake_completion.kw = kw
        class _M:
            content = "ok"
            tool_calls = None
        class _C:
            message = _M()
        class _R:
            choices = [_C()]
            usage = None
        return _R()

    monkeypatch.setattr(litellm, "completion", _fake_completion)
    cli = _shim_client()
    cli.mcp_client = _FakeMCP()
    # offer ONLY survey, though the server exposes two tools
    cli.complete([{"role": "user", "content": "go"}],
                 tools=[{"type": "function", "function": {"name": "survey"}}],
                 phase="react")
    allowed = (_fake_completion.kw.get("extra_body") or {}).get("allowed_mcp_tools")
    assert allowed == ["mcp__web-skill__survey"], allowed


# ── M7: codex output loss is recovered from stdout, never silently empty ─────
def test_codex_text_from_stdout_recovers_assistant_message():
    """The --json JSONL fallback pulls the latest assistant text out of the
    event stream (mirrors the claude path)."""
    stream = "\n".join([
        json.dumps({"msg": {"type": "agent_message",
                            "last_agent_message": "first"}}),
        json.dumps({"type": "token_count", "usage": {"input_tokens": 3}}),
        json.dumps({"msg": {"type": "agent_message",
                            "last_agent_message": "final answer"}}),
    ])
    assert cs._codex_text_from_stdout(stream) == "final answer"
    assert cs._codex_text_from_stdout("") == ""
    assert cs._codex_text_from_stdout("not json\n{bad") == ""


def _fake_codex_run_dropping_output_file(stdout: str):
    """Return a subprocess.run stand-in that deletes codex's -o last_msg_file
    (simulating a lost output file) and returns the given --json stdout."""
    import os as _os

    def _fake_run(cmd, input, capture_output, text, timeout, cwd):
        if "-o" in cmd:
            path = cmd[cmd.index("-o") + 1]
            try:
                _os.unlink(path)
            except OSError:
                pass
        return _FakeProc(stdout)

    return _fake_run


def test_run_codex_recovers_from_stdout_when_output_file_lost(monkeypatch, tmp_path):
    """M7: a lost last_msg_file must NOT become an empty HTTP-200 reply — the
    turn's text is recovered from the --json stream and a warning is logged."""
    stream = json.dumps({"msg": {"type": "agent_message",
                                 "last_agent_message": "recovered reply"}})
    monkeypatch.setattr(cs.subprocess, "run",
                        _fake_codex_run_dropping_output_file(stream))
    text, _usage = cs.run_codex("sys", "prompt", agent=False,
                                real_model=None, cwd=str(tmp_path))
    assert text == "recovered reply"


def test_run_codex_raises_when_output_lost_and_stdout_empty(monkeypatch, tmp_path):
    """M7: when neither the output file nor the --json stream carries any text,
    run_codex raises so do_POST returns 502 instead of a fabricated empty turn."""
    monkeypatch.setattr(cs.subprocess, "run",
                        _fake_codex_run_dropping_output_file(""))
    with pytest.raises(RuntimeError, match="no recoverable reply|unreadable"):
        cs.run_codex("sys", "prompt", agent=False,
                     real_model=None, cwd=str(tmp_path))


# ── codex MCP-direct: parity with the claude --mcp-config path ──────────────
def test_codex_mcp_overrides_encode_servers_and_tool_allowlist():
    """The engine-neutral {mcpServers} + mcp__s__t allowlist becomes codex
    `-c mcp_servers.*` overrides with a per-server enabled_tools allowlist."""
    cfg = {"mcpServers": {
        "web": {"command": "python", "args": ["-m", "srv"], "env": {"K": "v"}},
        "paper-re": {"command": "python", "args": ["-m", "p"], "env": {}},
    }}
    allowed = ["mcp__web__survey", "mcp__web__fetch", "mcp__paper-re__extract"]
    ov = cs._codex_mcp_overrides(cfg, allowed)
    # BARE keys — codex won't register a quoted server segment as a live server.
    assert "mcp_servers.web.command=\"python\"" in ov
    assert 'mcp_servers.web.args=["-m", "srv"]' in ov
    assert 'mcp_servers.web.env={"K" = "v"}' in ov
    assert 'mcp_servers.web.enabled_tools=["survey", "fetch"]' in ov
    assert 'mcp_servers.paper-re.enabled_tools=["extract"]' in ov   # dash name OK
    # empty env is not emitted
    assert not any("paper-re" in a and ".env=" in a for a in ov)
    # no quoted key ever emitted (would silently fail to attach)
    assert not any('mcp_servers."' in a for a in ov)


def test_codex_mcp_overrides_honor_memory_detachment():
    """Detaching memory is honored two ways, exactly as claude honors it:
    server-level (omitted from the allowlist -> server skipped) and tool-level
    (only the surviving tools land in enabled_tools)."""
    cfg = {"mcpServers": {
        "web": {"command": "python", "args": [], "env": {}},
        "memory": {"command": "python", "args": ["-m", "mem"], "env": {}},
    }}
    # tool-level: memory keeps ONLY search; its write tools were filtered upstream
    ov = cs._codex_mcp_overrides(cfg, ["mcp__web__survey", "mcp__memory__search_memory"])
    assert 'mcp_servers.memory.enabled_tools=["search_memory"]' in ov
    # server-level: memory absent from the allowlist -> not spawned at all
    ov2 = cs._codex_mcp_overrides(cfg, ["mcp__web__survey"])
    assert not any("memory" in a for a in ov2)
    # full MCP detach
    assert cs._codex_mcp_overrides(None, None) == []
    assert cs._codex_mcp_overrides({"mcpServers": {}}, ["x"]) == []


def test_codex_mcp_overrides_encode_astral_unicode_as_raw_utf8():
    """Non-BMP chars (CJK Ext-B 𩸽, math symbols) must be raw UTF-8, NOT json's
    ensure_ascii surrogate pair (\\ud83d\\ude00) which TOML rejects and which
    would make codex refuse the whole config, dropping every server."""
    cfg = {"mcpServers": {"web": {
        "command": "python", "args": ["\U00029E3D"],  # 𩸽 (U+29E3D)
        "env": {"NAME": "\U0001F600rocket"},          # astral emoji
    }}}
    ov = cs._codex_mcp_overrides(cfg, ["mcp__web__t"])
    joined = "".join(ov)
    assert "\\ud83d" not in joined and "\\ude00" not in joined  # no surrogate pairs
    assert "\U00029E3D" in joined and "\U0001F600" in joined     # raw code points


def test_codex_mcp_overrides_skip_name_that_is_not_a_bare_key():
    """A server name with a '.' (or space/quote) can't be a codex -c bare key and
    would corrupt the WHOLE config; it is skipped (fail-loud) not emitted."""
    cfg = {"mcpServers": {
        "ok": {"command": "python", "args": [], "env": {}},
        "bad.name": {"command": "python", "args": [], "env": {}},
    }}
    ov = cs._codex_mcp_overrides(cfg, ["mcp__ok__t", "mcp__bad.name__t"])
    assert "mcp_servers.ok.command=\"python\"" in ov
    assert not any("bad.name" in a for a in ov)   # dotted name dropped, not corrupting


def _capture_codex_cmd(monkeypatch, tmp_path, **run_codex_kw):
    captured: dict = {}

    def _fake_run(cmd, input, capture_output, text, timeout, cwd):
        captured["cmd"] = cmd
        # write the -o last_msg_file so run_codex reads a normal reply
        if "-o" in cmd:
            import os as _os
            with open(cmd[cmd.index("-o") + 1], "w") as f:
                f.write("done")
        return _FakeProc(json.dumps({"msg": {"type": "agent_message",
                                             "last_agent_message": "done"}}))

    monkeypatch.setattr(cs.subprocess, "run", _fake_run)
    text, _usage = cs.run_codex("sys", "p", agent=False, real_model=None,
                                cwd=str(tmp_path), **run_codex_kw)
    return captured["cmd"], text


def test_run_codex_mcp_direct_builds_isolated_cmd(monkeypatch, tmp_path):
    """MCP-direct codex: strict isolation (--ignore-user-config), the server
    overrides, tool bypass, and the --json audit trail — the codex analogue of
    run_claude's --mcp-config/--strict-mcp-config/--allowedTools."""
    cfg = {"mcpServers": {"web": {"command": "python", "args": ["-m", "s"], "env": {}}}}
    cmd, text = _capture_codex_cmd(
        monkeypatch, tmp_path,
        mcp_config=cfg, allowed_mcp_tools=["mcp__web__survey"],
    )
    assert "--ignore-user-config" in cmd          # == claude --strict-mcp-config
    assert "features.apps=false" in cmd            # no ambient github/calendar apps
    assert "mcp_servers.web.command=\"python\"" in cmd
    assert 'mcp_servers.web.enabled_tools=["survey"]' in cmd
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd  # tools can run
    assert "--json" in cmd
    # audit trail persisted next to artifacts, like claude's tool_calls.jsonl
    audit = tmp_path / "tool_calls.jsonl"
    assert audit.is_file() and audit.read_text().strip()
    assert text == "done"


def test_run_codex_plain_still_isolates_but_attaches_nothing(monkeypatch, tmp_path):
    """No mcp_config -> plain path: read-only sandbox, NO mcp_servers overrides,
    no audit file. But --ignore-user-config is STILL passed (unconditional, the
    codex analogue of claude's unconditional --strict-mcp-config), so a plain
    codex call also boots zero ambient MCP servers/plugins = full MCP detach."""
    cmd, _ = _capture_codex_cmd(monkeypatch, tmp_path)
    assert "--ignore-user-config" in cmd            # ambient config never loaded
    assert "features.apps=false" in cmd             # curated apps off in plain mode too
    assert not any("mcp_servers" in a for a in cmd)  # but nothing attached
    assert "--sandbox" in cmd and cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert not (tmp_path / "tool_calls.jsonl").exists()


def test_complete_routes_codex_through_mcp_when_configured(monkeypatch, tmp_path):
    """complete() no longer gates MCP-direct on engine==claude: a codex model
    with mcp_config takes the MCP path (tool_calls stays None, text-catalog
    is bypassed) just like claude."""
    seen: dict = {}

    def _fake_run_codex(system, prompt, agent, real_model, cwd, *,
                        mcp_config=None, allowed_mcp_tools=None):
        seen["mcp_config"] = mcp_config
        seen["allowed"] = allowed_mcp_tools
        return "final", {"prompt_tokens": 1, "completion_tokens": 1,
                         "total_tokens": 2, "cost_usd": 0.0}

    monkeypatch.setattr(cs, "run_codex", _fake_run_codex)
    cfg = {"mcpServers": {"web": {"command": "x", "args": []}}}
    text, tool_calls, _usage = cs.complete(
        "codex-cli", [{"role": "user", "content": "go"}],
        tools=[{"type": "function", "function": {"name": "survey", "parameters": {}}}],
        tool_choice="required",
        mcp_config=cfg, allowed_mcp_tools=["mcp__web__survey"],
        work_dir=str(tmp_path),
    )
    assert seen["mcp_config"] == cfg           # forwarded to codex, not dropped
    assert seen["allowed"] == ["mcp__web__survey"]
    assert tool_calls is None                  # MCP-direct: CLI runs its own loop
    assert text == "final"


def test_run_codex_applies_reasoning_effort_when_set(monkeypatch, tmp_path):
    """ARI_CLI_SHIM_CODEX_REASONING -> `-c model_reasoning_effort=...`, so codex
    (whose operator default is dropped by --ignore-user-config) can be sped up
    across ARI's many calls. Empty = no override."""
    monkeypatch.setattr(cs, "CODEX_REASONING", "low")
    cmd, _ = _capture_codex_cmd(monkeypatch, tmp_path)
    assert 'model_reasoning_effort="low"' in cmd
    # unset -> no override
    monkeypatch.setattr(cs, "CODEX_REASONING", "")
    cmd2, _ = _capture_codex_cmd(monkeypatch, tmp_path)
    assert not any("model_reasoning_effort" in a for a in cmd2)
