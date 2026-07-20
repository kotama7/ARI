"""Tests for ari.llm.claude_code.policy — fail-loud hermetic policy rules."""

from __future__ import annotations

import dataclasses

import pytest

from ari.llm.claude_code.policy import (
    MODE_LOW_OVERHEAD,
    MODE_STRICT,
    ClaudeCodePolicy,
    ClaudeCodePolicyError,
    effective_max_turns,
    validate_policy,
)


def strict_policy(**overrides) -> ClaudeCodePolicy:
    return dataclasses.replace(ClaudeCodePolicy(mode=MODE_STRICT), **overrides)


def test_default_strict_policy_is_valid():
    validate_policy(strict_policy())


def test_default_low_overhead_policy_is_valid():
    validate_policy(ClaudeCodePolicy(mode=MODE_LOW_OVERHEAD))


def test_tools_enabled_fails():
    with pytest.raises(ClaudeCodePolicyError, match="tools"):
        validate_policy(strict_policy(tools=("Bash",)))


def test_missing_deny_all_fails():
    with pytest.raises(ClaudeCodePolicyError, match="disallowed_tools"):
        validate_policy(strict_policy(disallowed_tools=("Bash",)))


def test_session_resume_fails():
    with pytest.raises(ClaudeCodePolicyError, match="resume"):
        validate_policy(strict_policy(session_resume=True))


def test_memory_not_disabled_fails():
    with pytest.raises(ClaudeCodePolicyError, match="disable_auto_memory"):
        validate_policy(strict_policy(disable_auto_memory=False))


def test_prompt_history_not_disabled_fails():
    with pytest.raises(ClaudeCodePolicyError, match="disable_prompt_history"):
        validate_policy(strict_policy(disable_prompt_history=False))


def test_safe_mode_off_fails():
    with pytest.raises(ClaudeCodePolicyError, match="safe_mode"):
        validate_policy(strict_policy(safe_mode=False))


def test_session_persistence_on_fails():
    with pytest.raises(ClaudeCodePolicyError, match="no_session_persistence"):
        validate_policy(strict_policy(no_session_persistence=False))


def test_mcp_enabled_fails():
    with pytest.raises(ClaudeCodePolicyError, match="mcp_servers"):
        validate_policy(strict_policy(mcp_servers=("some-server",)))
    with pytest.raises(ClaudeCodePolicyError, match="strict_mcp_config"):
        validate_policy(strict_policy(strict_mcp_config=False))


def test_loose_permission_mode_fails():
    for mode in ("bypassPermissions", "acceptEdits", "dontAsk", "auto"):
        with pytest.raises(ClaudeCodePolicyError, match="permission_mode"):
            validate_policy(strict_policy(permission_mode=mode))
    validate_policy(strict_policy(permission_mode="default"))
    validate_policy(strict_policy(permission_mode="plan"))


def test_multi_turn_needs_explicit_permission():
    with pytest.raises(ClaudeCodePolicyError, match="allow_multi_turn"):
        validate_policy(strict_policy(max_turns=3))
    validate_policy(strict_policy(max_turns=3, allow_multi_turn=True))


def test_all_violations_reported_at_once():
    try:
        validate_policy(
            strict_policy(tools=("Bash",), safe_mode=False, max_turns=5)
        )
    except ClaudeCodePolicyError as e:
        msg = str(e)
        assert "tools" in msg and "safe_mode" in msg and "max_turns" in msg
    else:
        pytest.fail("expected ClaudeCodePolicyError")


def test_effective_max_turns_native_schema_needs_two():
    p = strict_policy()
    assert effective_max_turns(p, native_schema_call=False) == 1
    assert effective_max_turns(p, native_schema_call=True) == 2


def test_policy_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        strict_policy().max_turns = 5  # type: ignore[misc]
