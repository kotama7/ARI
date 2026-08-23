"""Tests for ari.llm.claude_code.command — argv/env building, no session reuse."""

from __future__ import annotations

import dataclasses

import pytest

from ari.llm.claude_code.command import (
    FORBIDDEN_FLAGS,
    FORCED_ENV,
    assert_no_session_reuse,
    build_strict_command,
    build_subprocess_env,
    parse_unknown_option,
)
from ari.llm.claude_code.policy import MODE_STRICT, ClaudeCodePolicy


def policy(**overrides) -> ClaudeCodePolicy:
    return dataclasses.replace(
        ClaudeCodePolicy(mode=MODE_STRICT, bare=True), **overrides
    )


def _pairs(argv: tuple[str, ...]) -> dict[str, str]:
    """flag -> following token (for flags that take a value)."""
    out = {}
    for i, tok in enumerate(argv):
        if tok.startswith("-"):
            out[tok] = argv[i + 1] if i + 1 < len(argv) else ""
    return out


def test_strict_command_has_all_isolation_flags():
    cmd = build_strict_command(policy(), model="claude-sonnet-5")
    argv = cmd.argv
    assert argv[0] == "claude"
    assert "-p" in argv
    assert "--bare" in argv
    assert "--safe-mode" in argv
    assert "--strict-mcp-config" in argv
    assert "--disable-slash-commands" in argv
    assert "--no-chrome" in argv
    assert "--no-session-persistence" in argv
    pairs = _pairs(argv)
    assert pairs["--output-format"] == "json"
    assert pairs["--max-turns"] == "1"
    assert pairs["--model"] == "claude-sonnet-5"
    assert pairs["--tools"] == ""
    assert pairs["--disallowedTools"] == "*"
    assert pairs["--permission-mode"] == "plan"
    # ALWAYS explicit, even when empty: omitting the flag makes the CLI load
    # user/project/local settings by default (verified by A/B on 2.1.198).
    assert pairs["--setting-sources"] == ""


def test_setting_sources_allowlist_joined():
    cmd = build_strict_command(
        policy(setting_sources=("user", "project")), model="m"
    )
    assert _pairs(cmd.argv)["--setting-sources"] == "user,project"


def test_no_bare_when_policy_says_so():
    cmd = build_strict_command(policy(bare=False), model="m")
    assert "--bare" not in cmd.argv


def test_system_prompt_file_flag():
    cmd = build_strict_command(
        policy(), model="m", system_prompt_file="/tmp/system.txt"
    )
    assert _pairs(cmd.argv)["--system-prompt-file"] == "/tmp/system.txt"


def test_no_session_reuse_flags_ever():
    for schema in (None, '{"type":"object"}'):
        for transport in ("prompt", "native"):
            cmd = build_strict_command(
                policy(structured_output_transport=transport),
                model="m",
                schema_json=schema,
            )
            assert not set(cmd.argv) & set(FORBIDDEN_FLAGS)
            assert "/clear" not in " ".join(cmd.argv)


def test_assert_no_session_reuse_raises():
    with pytest.raises(AssertionError, match="session-reuse"):
        assert_no_session_reuse(("claude", "-p", "--resume", "abc"))


def test_prompt_transport_keeps_strict_profile_with_schema():
    cmd = build_strict_command(
        policy(structured_output_transport="prompt"),
        model="m",
        schema_json='{"type":"object"}',
    )
    assert not cmd.native_schema
    assert "--json-schema" not in cmd.argv
    pairs = _pairs(cmd.argv)
    assert pairs["--max-turns"] == "1"
    assert pairs["--permission-mode"] == "plan"
    assert pairs["--disallowedTools"] == "*"


def test_native_schema_profile():
    # Verified on Claude Code 2.1.198: --json-schema answers via a
    # StructuredOutput TOOL call, so the native profile needs
    # --allowedTools StructuredOutput + permission-mode default + 2 turns.
    cmd = build_strict_command(
        policy(structured_output_transport="native"),
        model="m",
        schema_json='{"type":"object"}',
    )
    assert cmd.native_schema
    pairs = _pairs(cmd.argv)
    assert pairs["--json-schema"] == '{"type":"object"}'
    assert pairs["--allowedTools"] == "StructuredOutput"
    assert pairs["--permission-mode"] == "default"
    assert pairs["--max-turns"] == "2"
    assert "--disallowedTools" not in cmd.argv
    assert pairs["--tools"] == ""  # every other tool still disabled


def test_compat_drop_flags_removed_and_recorded():
    cmd = build_strict_command(
        policy(), model="m", compat_drop_flags=("--no-chrome",)
    )
    assert "--no-chrome" not in cmd.argv
    assert cmd.dropped_flags == ("--no-chrome",)


def test_parse_unknown_option():
    assert (
        parse_unknown_option("error: unknown option '--no-chrome'")
        == "--no-chrome"
    )
    assert parse_unknown_option("some other error") is None
    assert parse_unknown_option("") is None


def test_hermetic_env_allowlist_drops_session_vars():
    base = {
        "PATH": "/usr/bin",
        "HOME": "/home/u",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_SESSION_ID": "parent-session",
        "RANDOM_SECRET": "x",
        "ANTHROPIC_API_KEY": "sk-test",
    }
    env, record = build_subprocess_env(
        hermetic=True, home=None, base_env=base
    )
    assert env["PATH"] == "/usr/bin"
    assert env["ANTHROPIC_API_KEY"] == "sk-test"
    assert "CLAUDECODE" not in env
    assert "CLAUDE_CODE_SESSION_ID" not in env
    assert "RANDOM_SECRET" not in env
    # Memory / prompt-history suppression always forced.
    for k, v in FORCED_ENV.items():
        assert env[k] == v
        assert record[k] == f"<forced:{v}>"
    # Provenance record carries names/markers, never secret values.
    assert record["ANTHROPIC_API_KEY"] == "<inherited>"
    assert "sk-test" not in str(record)


def test_hermetic_env_extra_allowlist():
    base = {"PATH": "/bin", "MY_CA_BUNDLE": "/etc/ca.pem"}
    env, _ = build_subprocess_env(
        hermetic=True, home=None,
        env_allowlist_extra=("MY_CA_BUNDLE",), base_env=base,
    )
    assert env["MY_CA_BUNDLE"] == "/etc/ca.pem"


def test_non_hermetic_env_still_drops_parent_claude_session():
    base = {"PATH": "/bin", "FOO": "bar", "CLAUDE_CODE_SSE_PORT": "1234",
            "CLAUDECODE": "1"}
    env, record = build_subprocess_env(
        hermetic=False, home=None, base_env=base
    )
    assert env["FOO"] == "bar"
    assert "CLAUDE_CODE_SSE_PORT" not in env
    assert "CLAUDECODE" not in env
    assert "<mode>" in record


def test_home_override_recorded():
    env, record = build_subprocess_env(
        hermetic=True, home="/tmp/sandbox-home", base_env={"HOME": "/home/u"}
    )
    assert env["HOME"] == "/tmp/sandbox-home"
    assert record["HOME"] == "<overridden:sandbox>"
