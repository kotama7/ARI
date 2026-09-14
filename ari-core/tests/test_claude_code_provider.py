"""Integration tests for the claude_code backend (mock runners, no real CLI).

Covers the spec's mock-runner matrix: backend selection through LLMClient,
strict mode = subprocess runner, low_overhead = SDK runner, both normalize to
the same LLMResponse, session ids are never reused, no interactive/`/clear`
usage, ARI-side schema validation with a single repair retry, and provenance
persistence.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import types
from dataclasses import dataclass, field

import pytest

from ari.config import ClaudeCodeSettings, LLMConfig
from ari.llm.claude_code import (
    ClaudeCodeProvider,
    ClaudeCodeRunError,
    ClaudeCodeSchemaError,
    ClaudeCodeSdkUnavailableError,
    ClaudeCodeToolsUnsupportedError,
    ClaudeCodeUnsupportedFlagError,
)
from ari.llm.claude_code.cli_runner import ClaudeCliRunner
from ari.llm.claude_code.sdk_runner import ClaudeSdkRunner
from ari.llm.client import LLMClient, LLMResponse

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
}


@pytest.fixture(autouse=True)
def _isolate_claude_auth_env(monkeypatch):
    """bare/home auto-resolution reads ANTHROPIC_* — pin them absent so the
    tests behave the same on developer machines that export a key."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)


# ── fake `claude` subprocess ───────────────────────────────────────────────
class _FakeProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def envelope(result_text, *, session="sess-1", structured=None, is_error=False):
    env = {
        "type": "result",
        "subtype": "success",
        "is_error": is_error,
        "result": result_text,
        "session_id": session,
        "num_turns": 1,
        "usage": {
            "input_tokens": 10,
            "cache_creation_input_tokens": 5,
            "cache_read_input_tokens": 1,
            "output_tokens": 3,
        },
        "total_cost_usd": 0.01,
    }
    if structured is not None:
        env["structured_output"] = structured
    return env


def install_fake_claude(monkeypatch, envelopes, calls):
    """Patch subprocess.run inside cli_runner with a scripted fake."""

    def fake_run(argv, **kw):
        argv = list(argv)
        if "--version" in argv:
            return _FakeProc(stdout="9.9.9 (Claude Code)\n")
        calls.append({"argv": argv, **{k: kw.get(k) for k in ("input", "cwd", "env", "timeout")}})
        item = envelopes.pop(0)
        if isinstance(item, _FakeProc):
            return item
        return _FakeProc(stdout=json.dumps(item))

    monkeypatch.setattr(
        "ari.llm.claude_code.cli_runner.subprocess.run", fake_run
    )


def settings(**overrides) -> ClaudeCodeSettings:
    return ClaudeCodeSettings(**overrides)


# ── strict mode via provider ───────────────────────────────────────────────
def test_strict_mode_complete_uses_subprocess_runner(tmp_path, monkeypatch):
    calls = []
    install_fake_claude(monkeypatch, [envelope("hello!")], calls)
    provider = ClaudeCodeProvider(
        settings(), "claude-sonnet-5", provenance_root=tmp_path
    )
    assert isinstance(provider._get_runner(), ClaudeCliRunner)
    resp = provider.complete([{"role": "user", "content": "hi"}])
    assert isinstance(resp, LLMResponse)
    assert resp.content == "hello!"
    assert resp.text == "hello!"
    assert resp.provider == "claude_code"
    assert resp.model == "claude-sonnet-5"
    assert resp.usage == {
        "prompt_tokens": 16,
        "completion_tokens": 3,
        "total_tokens": 19,
    }
    assert len(calls) == 1
    argv = calls[0]["argv"]
    assert argv[0] == "claude" and "-p" in argv
    # Prompt travels on stdin, serialized ARI-side.
    assert "<conversation>" in calls[0]["input"]
    # Hermetic env with forced memory suppression.
    assert calls[0]["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert calls[0]["env"]["CLAUDE_CODE_SKIP_PROMPT_HISTORY"] == "1"


def test_provenance_artifacts_written(tmp_path, monkeypatch):
    calls = []
    install_fake_claude(monkeypatch, [envelope("out")], calls)
    provider = ClaudeCodeProvider(
        settings(), "claude-sonnet-5", provenance_root=tmp_path
    )
    resp = provider.complete(
        [{"role": "user", "content": "hi"}], system="SYS", label="unit"
    )
    assert resp.provenance_path is not None
    from pathlib import Path

    d = Path(resp.provenance_path)
    for rel in (
        "prompt.txt",
        "system.txt",
        "command.json",
        "env_allowlist.json",
        "claude_version.txt",
        "stdout.json",
        "stderr.log",
        "result.json",
        "validation.json",
        "input_hashes.json",
        "output_hashes.json",
        "provenance.json",
    ):
        assert (d / rel).exists(), rel
    prov = json.loads((d / "provenance.json").read_text())
    assert prov["provider"] == "claude_code"
    assert prov["mode"] == "strict_reproducibility"
    assert prov["policy"]["resume_used"] is False
    assert prov["policy"]["session_persistence"] is False
    assert prov["session_id"] == "sess-1"
    assert prov["return_code"] == 0
    # System prompt was passed as a file, not inlined into the conversation.
    argv = calls[0]["argv"]
    assert "--system-prompt-file" in argv


def test_session_id_never_reused_across_requests(tmp_path, monkeypatch):
    calls = []
    install_fake_claude(
        monkeypatch,
        [envelope("a", session="sess-A"), envelope("b", session="sess-B")],
        calls,
    )
    provider = ClaudeCodeProvider(
        settings(), "claude-sonnet-5", provenance_root=tmp_path
    )
    provider.complete([{"role": "user", "content": "1"}])
    provider.complete([{"role": "user", "content": "2"}])
    assert len(calls) == 2
    for call in calls:
        joined = " ".join(call["argv"])
        assert "sess-A" not in joined and "sess-B" not in joined
        for bad in ("--resume", "--continue", "--session-id", "--fork-session"):
            assert bad not in call["argv"]
        assert "/clear" not in joined


def test_no_interactive_mode_always_print(tmp_path, monkeypatch):
    calls = []
    install_fake_claude(monkeypatch, [envelope("x")], calls)
    provider = ClaudeCodeProvider(
        settings(), "m", provenance_root=tmp_path
    )
    provider.complete([{"role": "user", "content": "q"}])
    assert "-p" in calls[0]["argv"]


def test_run_error_raises_after_provenance(tmp_path, monkeypatch):
    calls = []
    install_fake_claude(
        monkeypatch, [envelope("Not logged in", is_error=True)], calls
    )
    provider = ClaudeCodeProvider(settings(), "m", provenance_root=tmp_path)
    with pytest.raises(ClaudeCodeRunError, match="is_error"):
        provider.complete([{"role": "user", "content": "q"}])
    # Provenance for the failed call exists.
    dirs = list(tmp_path.iterdir())
    assert dirs and (dirs[0] / "provenance.json").exists()


def test_unknown_flag_fails_loud(tmp_path, monkeypatch):
    calls = []
    install_fake_claude(
        monkeypatch,
        [_FakeProc(stderr="error: unknown option '--no-chrome'", returncode=1)],
        calls,
    )
    provider = ClaudeCodeProvider(settings(), "m", provenance_root=tmp_path)
    with pytest.raises(ClaudeCodeUnsupportedFlagError, match="--no-chrome"):
        provider.complete([{"role": "user", "content": "q"}])
    dirs = list(tmp_path.iterdir())
    prov = json.loads((dirs[0] / "provenance.json").read_text())
    assert "--no-chrome" in prov["unsupported_flags"]


def test_timeout_surfaces_as_run_error(tmp_path, monkeypatch):
    import subprocess as _sp

    def fake_run(argv, **kw):
        if "--version" in argv:
            return _FakeProc(stdout="9.9.9")
        raise _sp.TimeoutExpired(cmd=argv, timeout=kw.get("timeout"))

    monkeypatch.setattr(
        "ari.llm.claude_code.cli_runner.subprocess.run", fake_run
    )
    provider = ClaudeCodeProvider(
        settings(timeout_sec=7), "m", provenance_root=tmp_path
    )
    with pytest.raises(ClaudeCodeRunError, match="timed out after 7s"):
        provider.complete([{"role": "user", "content": "q"}])


# ── schema validation + repair retry ───────────────────────────────────────
def test_schema_valid_json_passes(tmp_path, monkeypatch):
    calls = []
    install_fake_claude(monkeypatch, [envelope('{"ok": true}')], calls)
    provider = ClaudeCodeProvider(settings(), "m", provenance_root=tmp_path)
    obj, resp = provider.structured_complete(
        [{"role": "user", "content": "q"}], SCHEMA
    )
    assert obj == {"ok": True}
    assert json.loads(resp.content) == {"ok": True}
    # Schema was embedded in the prompt (default transport).
    assert '"ok"' in calls[0]["input"]
    validation = json.loads(
        (list(tmp_path.iterdir())[0] / "validation.json").read_text()
    )
    assert validation == {
        "schema_used": True,
        "valid": True,
        "transport": "prompt",
        "errors": [],
    }


def test_schema_invalid_repairs_once_then_succeeds(tmp_path, monkeypatch):
    calls = []
    install_fake_claude(
        monkeypatch,
        [envelope('{"ok": "not-bool"}'), envelope('{"ok": false}')],
        calls,
    )
    provider = ClaudeCodeProvider(settings(), "m", provenance_root=tmp_path)
    obj, resp = provider.structured_complete(
        [{"role": "user", "content": "q"}], SCHEMA
    )
    assert obj == {"ok": False}
    assert len(calls) == 2
    # The retry carries the repair instruction and the invalid output.
    assert "repair_instruction" in calls[1]["input"]
    assert "not-bool" in calls[1]["input"]
    # Retry ran under the same hermetic policy (same isolation argv).
    assert calls[0]["argv"] == calls[1]["argv"]
    # attempt_2 sandbox recorded.
    d = list(tmp_path.iterdir())[0]
    assert (d / "attempt_2" / "prompt.txt").exists()
    assert (d / "attempt_2" / "stdout.json").exists()


def test_schema_invalid_twice_fails(tmp_path, monkeypatch):
    calls = []
    install_fake_claude(
        monkeypatch,
        [envelope("no json here at all"), envelope('{"nope": 1}')],
        calls,
    )
    provider = ClaudeCodeProvider(settings(), "m", provenance_root=tmp_path)
    with pytest.raises(ClaudeCodeSchemaError):
        provider.structured_complete([{"role": "user", "content": "q"}], SCHEMA)
    assert len(calls) == 2  # exactly one repair retry


def test_schema_no_retry_when_disabled(tmp_path, monkeypatch):
    calls = []
    install_fake_claude(monkeypatch, [envelope("not json")], calls)
    provider = ClaudeCodeProvider(
        settings(schema_repair_retries=0), "m", provenance_root=tmp_path
    )
    with pytest.raises(ClaudeCodeSchemaError):
        provider.structured_complete([{"role": "user", "content": "q"}], SCHEMA)
    assert len(calls) == 1


def test_native_transport_uses_structured_output_field(tmp_path, monkeypatch):
    calls = []
    install_fake_claude(
        monkeypatch,
        [envelope('{"ok":true}', structured={"ok": True})],
        calls,
    )
    provider = ClaudeCodeProvider(
        settings(structured_output_transport="native"),
        "m",
        provenance_root=tmp_path,
    )
    obj, _ = provider.structured_complete(
        [{"role": "user", "content": "q"}], SCHEMA
    )
    assert obj == {"ok": True}
    argv = calls[0]["argv"]
    assert "--json-schema" in argv
    assert "StructuredOutput" in argv


# ── LLMClient integration ──────────────────────────────────────────────────
def _client(monkeypatch, tmp_path, **cc_overrides) -> LLMClient:
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    cfg = LLMConfig(
        backend="claude_code",
        model="claude-sonnet-5",
        claude_code=ClaudeCodeSettings(**cc_overrides),
    )
    return LLMClient(cfg)


def test_llmclient_dispatches_claude_code_backend(tmp_path, monkeypatch):
    calls = []
    install_fake_claude(monkeypatch, [envelope("routed")], calls)
    client = _client(monkeypatch, tmp_path)
    resp = client.complete(
        [{"role": "user", "content": "hi"}],
        node_id="n1",
        phase="bfts",
        skill="select_next_node",
    )
    assert resp.content == "routed"
    assert resp.provider == "claude_code"
    assert len(calls) == 1
    # Artifacts landed under {checkpoint}/claude_code/.
    assert (tmp_path / "claude_code").is_dir()
    assert any((tmp_path / "claude_code").iterdir())


def test_llmclient_claude_code_rejects_tools(tmp_path, monkeypatch):
    client = _client(monkeypatch, tmp_path)
    with pytest.raises(ClaudeCodeToolsUnsupportedError):
        client.complete(
            [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "f"}}],
        )


def test_llmclient_claude_code_stream_fails_loud(tmp_path, monkeypatch):
    from ari.llm.client import LLMMessage

    client = _client(monkeypatch, tmp_path)
    with pytest.raises(NotImplementedError, match="claude_code"):
        list(client.stream([LLMMessage(role="user", content="x")]))


def test_llmclient_records_cost(tmp_path, monkeypatch):
    calls = []
    install_fake_claude(monkeypatch, [envelope("x")], calls)
    recorded = {}

    def fake_record(**kwargs):
        recorded.update(kwargs)

    monkeypatch.setattr("ari.cost_tracker.record", fake_record)
    client = _client(monkeypatch, tmp_path)
    client.complete(
        [{"role": "user", "content": "hi"}], node_id="n9", phase="bfts"
    )
    assert recorded["backend"] == "claude_code"
    assert recorded["cost_usd"] == 0.01
    assert recorded["node_id"] == "n9"
    assert recorded["prompt_tokens"] == 16


# ── low_overhead (SDK) mode ────────────────────────────────────────────────
def make_fake_sdk(seen_queries):
    sdk = types.ModuleType("claude_agent_sdk")
    sdk.__version__ = "0.0-fake"

    @dataclass
    class ClaudeAgentOptions:
        max_turns: int | None = None
        allowed_tools: list = field(default_factory=list)
        disallowed_tools: list = field(default_factory=list)
        permission_mode: str | None = None
        mcp_servers: dict = field(default_factory=dict)
        setting_sources: list | None = None
        env: dict = field(default_factory=dict)
        extra_args: dict = field(default_factory=dict)
        system_prompt: str | None = None
        model: str | None = None
        cwd: str | None = None
        resume: str | None = None
        continue_conversation: bool = False
        fork_session: bool = False

    @dataclass
    class ResultMessage:
        result: str
        session_id: str
        is_error: bool = False
        subtype: str = "success"
        num_turns: int = 1
        usage: dict | None = None
        total_cost_usd: float = 0.002

    async def query(*, prompt, options):
        seen_queries.append({"prompt": prompt, "options": options})
        yield ResultMessage(
            result=f"sdk-answer-{len(seen_queries)}",
            session_id=f"sdk-sess-{len(seen_queries)}",
            usage={"input_tokens": 4, "output_tokens": 2},
        )

    sdk.ClaudeAgentOptions = ClaudeAgentOptions
    sdk.ResultMessage = ResultMessage
    sdk.query = query
    return sdk


def test_low_overhead_uses_sdk_runner_fresh_query_each_request(
    tmp_path, monkeypatch
):
    seen = []
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", make_fake_sdk(seen))
    provider = ClaudeCodeProvider(
        settings(mode="low_overhead"), "claude-sonnet-5",
        provenance_root=tmp_path,
    )
    assert isinstance(provider._get_runner(), ClaudeSdkRunner)
    r1 = provider.complete([{"role": "user", "content": "one"}])
    r2 = provider.complete([{"role": "user", "content": "two"}])
    # Same normalized response type as strict mode.
    assert isinstance(r1, LLMResponse) and isinstance(r2, LLMResponse)
    assert r1.content == "sdk-answer-1"
    assert r2.content == "sdk-answer-2"
    assert r1.usage == {"prompt_tokens": 4, "completion_tokens": 2,
                        "total_tokens": 6}
    assert len(seen) == 2
    for q in seen:
        opts = q["options"]
        # Fresh, stateless query every time: no session reuse, no tools/MCP.
        assert opts.resume is None
        assert opts.continue_conversation is False
        assert opts.fork_session is False
        assert opts.allowed_tools == []
        assert opts.disallowed_tools == ["*"]
        assert opts.mcp_servers == {}
        assert opts.setting_sources == []
        assert opts.max_turns == 1
        assert opts.env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert opts.env["CLAUDE_CODE_SKIP_PROMPT_HISTORY"] == "1"
        # Transcript persistence suppressed via the SDK's CLI-flag escape
        # hatch (no ClaudeAgentOptions field exists for it).
        assert opts.extra_args == {"no-session-persistence": None}
        assert "/clear" not in q["prompt"]
    # The first call's session id never reaches the second call's options.
    assert seen[1]["options"].resume is None


def test_low_overhead_writes_sdk_trace(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", make_fake_sdk(seen))
    provider = ClaudeCodeProvider(
        settings(mode="low_overhead"), "m", provenance_root=tmp_path
    )
    resp = provider.complete([{"role": "user", "content": "q"}])
    from pathlib import Path

    d = Path(resp.provenance_path)
    trace = [
        json.loads(line)
        for line in (d / "trace.jsonl").read_text().splitlines()
    ]
    assert trace and trace[-1]["event"] == "ResultMessage"
    prov = json.loads((d / "provenance.json").read_text())
    assert prov["sdk_version"] == "0.0-fake"
    assert prov["mode"] == "low_overhead"


def test_sdk_unavailable_fails_loud(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    provider = ClaudeCodeProvider(
        settings(mode="low_overhead"), "m", provenance_root=tmp_path
    )
    with pytest.raises(ClaudeCodeSdkUnavailableError, match="claude-agent-sdk"):
        provider.complete([{"role": "user", "content": "q"}])


def test_sdk_fallback_to_cli_only_when_configured(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    calls = []
    install_fake_claude(monkeypatch, [envelope("via-cli")], calls)
    provider = ClaudeCodeProvider(
        settings(mode="low_overhead", sdk_fallback_to_cli=True),
        "m",
        provenance_root=tmp_path,
    )
    resp = provider.complete([{"role": "user", "content": "q"}])
    assert resp.content == "via-cli"
    assert isinstance(provider._get_runner(), ClaudeCliRunner)
    prov_dirs = list(tmp_path.iterdir())
    prov = json.loads((prov_dirs[0] / "provenance.json").read_text())
    assert prov["sdk_fell_back_to_cli"] is True


def test_sdk_missing_policy_critical_option_fails(tmp_path, monkeypatch):
    seen = []
    sdk = make_fake_sdk(seen)

    # An SDK whose options lack `env` and `extra_args` (memory suppression
    # and --no-session-persistence impossible).
    @dataclass
    class OldOptions:
        max_turns: int | None = None
        allowed_tools: list = field(default_factory=list)
        disallowed_tools: list = field(default_factory=list)
        permission_mode: str | None = None
        mcp_servers: dict = field(default_factory=dict)
        setting_sources: list | None = None

    sdk.ClaudeAgentOptions = OldOptions
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", sdk)
    from ari.llm.claude_code.policy import ClaudeCodePolicyError

    provider = ClaudeCodeProvider(
        settings(mode="low_overhead"), "m", provenance_root=tmp_path
    )
    with pytest.raises(ClaudeCodePolicyError, match="policy-critical"):
        provider.complete([{"role": "user", "content": "q"}])


def test_sdk_sandbox_home_injected_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    seen = []
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", make_fake_sdk(seen))
    provider = ClaudeCodeProvider(
        settings(mode="low_overhead", home_mode="sandbox"),
        "m",
        provenance_root=tmp_path,
    )
    provider.complete([{"role": "user", "content": "q"}])
    opts = seen[0]["options"]
    assert opts.env["HOME"].endswith("/home")
    assert opts.env["HOME"].startswith(str(tmp_path))


def test_repair_retry_books_cost_per_attempt(tmp_path, monkeypatch):
    calls = []
    install_fake_claude(
        monkeypatch,
        [envelope('{"ok": "not-bool"}'), envelope('{"ok": true}')],
        calls,
    )
    booked = []
    monkeypatch.setattr(
        "ari.cost_tracker.record", lambda **kw: booked.append(kw)
    )
    provider = ClaudeCodeProvider(settings(), "m", provenance_root=tmp_path)
    provider.structured_complete([{"role": "user", "content": "q"}], SCHEMA)
    # Two claude invocations -> two cost records (review finding: retries
    # must not be silently unbooked).
    assert len(booked) == 2
    assert all(b["cost_usd"] == 0.01 for b in booked)


def test_no_secret_values_in_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-super-secret-value")
    calls = []
    install_fake_claude(monkeypatch, [envelope("x")], calls)
    provider = ClaudeCodeProvider(settings(), "m", provenance_root=tmp_path)
    resp = provider.complete([{"role": "user", "content": "q"}])
    from pathlib import Path

    d = Path(resp.provenance_path)
    for f in d.rglob("*"):
        if f.is_file():
            assert "sk-super-secret-value" not in f.read_text(
                encoding="utf-8", errors="ignore"
            ), f
    # ...while the subprocess env itself DID carry the key (hermetic
    # allowlist passes auth through).
    assert calls[0]["env"]["ANTHROPIC_API_KEY"] == "sk-super-secret-value"


# ── config wiring ──────────────────────────────────────────────────────────
def test_env_overrides_for_claude_code(monkeypatch):
    from ari.config import ARIConfig, _apply_llm_env_overrides

    for var in (
        "ARI_MODEL", "ARI_LLM_MODEL", "ARI_LLM_API_BASE", "ARI_SEED",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ARI_BACKEND", "claude_code")
    monkeypatch.setenv("ARI_CLAUDE_CODE_MODE", "low_overhead")
    monkeypatch.setenv("ARI_CLAUDE_CODE_MODEL", "claude-sonnet-5")
    # A non-default value, so this asserts the override actually applied
    # (policy-level multi-turn gating is validated separately).
    monkeypatch.setenv("ARI_CLAUDE_CODE_MAX_TURNS", "2")
    monkeypatch.setenv("ARI_CLAUDE_CODE_TIMEOUT_SEC", "45")
    monkeypatch.setenv("ARI_CLAUDE_CODE_RECORD_PROVENANCE", "0")
    monkeypatch.setenv("ARI_CLAUDE_CODE_BIN", "/opt/bin/claude")
    cfg = ARIConfig()
    _apply_llm_env_overrides(cfg)
    assert cfg.llm.backend == "claude_code"
    assert cfg.llm.model == "claude-sonnet-5"
    cc = cfg.llm.claude_code
    assert cc.mode == "low_overhead"
    assert cc.max_turns == 2
    assert cc.timeout_sec == 45
    assert cc.record_provenance is False
    assert cc.claude_bin == "/opt/bin/claude"


def test_auto_config_applies_claude_code_env_overrides(monkeypatch):
    from ari.config import auto_config

    monkeypatch.setenv("ARI_BACKEND", "claude_code")
    monkeypatch.setenv("ARI_CLAUDE_CODE_MODE", "low_overhead")
    monkeypatch.setenv("ARI_CLAUDE_CODE_TIMEOUT_SEC", "77")
    cfg = auto_config()
    assert cfg.llm.claude_code.mode == "low_overhead"
    assert cfg.llm.claude_code.timeout_sec == 77


def test_gui_env_injection_path_reaches_dispatch(tmp_path, monkeypatch):
    """The GUI wizard selects a provider by exporting ARI_BACKEND/ARI_MODEL
    into the child env (api_experiment.py). Simulate that path end-to-end:
    env -> load_config -> LLMClient -> claude_code dispatch."""
    import yaml as _yaml

    from ari.config import load_config

    for var in ("ARI_LLM_MODEL", "ARI_LLM_API_BASE", "ARI_SEED"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ARI_BACKEND", "claude_code")
    monkeypatch.setenv("ARI_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    fpath = tmp_path / "c.yaml"
    fpath.write_text(_yaml.dump({"llm": {"backend": "ollama", "model": "qwen3:8b"}}))
    cfg = load_config(str(fpath))
    assert cfg.llm.backend == "claude_code"
    assert cfg.llm.model == "claude-sonnet-5"

    calls = []
    install_fake_claude(monkeypatch, [envelope("gui-routed")], calls)
    client = LLMClient(cfg.llm)
    resp = client.complete([{"role": "user", "content": "hi"}])
    assert resp.content == "gui-routed"
    assert resp.provider == "claude_code"


def test_gui_launcher_knows_claude_code_provider():
    """Regression guard on the GUI backend sources: provider default-model
    fill and ANTHROPIC_API_KEY mapping must include claude_code (the
    frontend dropdowns offer it; see viz/frontend Wizard/Settings)."""
    from pathlib import Path

    import ari.viz.api_experiment as api_experiment
    import ari.viz.api_settings as api_settings

    exp_src = Path(api_experiment.__file__).read_text(encoding="utf-8")
    set_src = Path(api_settings.__file__).read_text(encoding="utf-8")
    assert '"claude_code": "claude-sonnet-5"' in exp_src
    assert '"claude_code", "claude-code"' in exp_src or (
        '"claude_code"' in exp_src and "ANTHROPIC_API_KEY" in exp_src
    )
    assert '"claude_code": "ANTHROPIC_API_KEY"' in set_src


def test_env_override_invalid_mode_ignored(monkeypatch):
    from ari.config import ARIConfig, _apply_claude_code_env_overrides

    monkeypatch.setenv("ARI_CLAUDE_CODE_MODE", "interactive")
    cfg = ARIConfig()
    _apply_claude_code_env_overrides(cfg)
    assert cfg.llm.claude_code.mode == "strict_reproducibility"


def test_invalid_settings_rejected_at_provider_construction(tmp_path):
    from ari.llm.claude_code.policy import ClaudeCodePolicyError

    with pytest.raises(ClaudeCodePolicyError, match="tools"):
        ClaudeCodeProvider(
            settings(tools=["Bash"]), "m", provenance_root=tmp_path
        )
    with pytest.raises(ClaudeCodePolicyError, match="allow_multi_turn"):
        ClaudeCodeProvider(
            settings(max_turns=4), "m", provenance_root=tmp_path
        )


def test_routing_maps_claude_code_to_anthropic_for_direct_litellm():
    # Direct litellm callers (MCP skills) get a deterministic route; the
    # LLMClient path never reaches litellm on this backend.
    from ari.llm.routing import resolve_litellm_model

    assert (
        resolve_litellm_model("claude-sonnet-5", "claude_code")
        == "anthropic/claude-sonnet-5"
    )


def test_record_provenance_off_leaves_no_dirs(tmp_path, monkeypatch):
    calls = []
    install_fake_claude(monkeypatch, [envelope("x")], calls)
    provider = ClaudeCodeProvider(
        settings(record_provenance=False), "m", provenance_root=tmp_path
    )
    resp = provider.complete([{"role": "user", "content": "q"}])
    assert resp.provenance_path is None
    assert list(tmp_path.iterdir()) == []


def test_llmclient_never_reaches_litellm_on_this_backend(tmp_path, monkeypatch):
    """The claim `test_routing_maps_claude_code_to_anthropic_for_direct_litellm`
    makes in a comment, asserted in code.

    `complete()` used to route this backend around litellm, the branch was lost
    in a merge, and only the streaming guard came back. Every symptom then
    pointed at the environment -- litellm asked for an ANTHROPIC_API_KEY, so the
    four tests that caught it read as "no key on this machine" rather than "the
    configured backend was silently replaced". Failing on the dispatch itself is
    what makes the next such loss say so.
    """

    import litellm

    def explode(*args, **kwargs):  # pragma: no cover - the point is not calling it
        raise AssertionError(
            "backend=claude_code reached litellm.completion; the CLI provider "
            "dispatch in LLMClient.complete() is gone again"
        )

    monkeypatch.setattr(litellm, "completion", explode)
    calls = []
    install_fake_claude(monkeypatch, [envelope("routed")], calls)
    client = _client(monkeypatch, tmp_path)

    resp = client.complete([{"role": "user", "content": "hi"}])

    assert resp.provider == "claude_code"
    assert len(calls) == 1
