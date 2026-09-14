"""Hermetic-execution policy for the Claude Code LLM provider.

The claude_code backend drives Claude Code as a *stateless LLM API*, not as
an agent executor. This module is the single place where that contract is
encoded and enforced. Every runner (CLI subprocess, Agent SDK) receives a
validated, frozen :class:`ClaudeCodePolicy`; a policy that would let Claude
Code keep state between requests (session resume), reach tools/MCP/memory,
or load user configuration fails loudly here instead of degrading silently.

A future agent-executor mode (tools enabled, multi-turn) must be a separate
backend name (``claude_code_agent_executor``), NOT a relaxation of this
policy — see docs/reference/claude_code_provider.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

MODE_STRICT = "strict_reproducibility"
MODE_LOW_OVERHEAD = "low_overhead"
VALID_MODES = (MODE_STRICT, MODE_LOW_OVERHEAD)

#: Structured output transports (see command.py):
#: - "prompt": schema is embedded in the prompt; the strictest flag profile
#:   (--permission-mode plan, --max-turns 1, --disallowedTools "*") is kept.
#: - "native": the schema is passed via --json-schema. Verified on Claude
#:   Code 2.1.198: structured output is delivered through a StructuredOutput
#:   TOOL call, which "plan" permission mode denies and which consumes one
#:   extra turn — so this transport requires --permission-mode default,
#:   --allowedTools StructuredOutput and max_turns >= 2 for the schema call.
TRANSPORT_PROMPT = "prompt"
TRANSPORT_NATIVE = "native"
VALID_TRANSPORTS = (TRANSPORT_PROMPT, TRANSPORT_NATIVE)

#: Highest max_turns reachable without ``allow_multi_turn``: the native
#: schema transport needs exactly one extra turn for the StructuredOutput
#: tool round-trip.
_NATIVE_TRANSPORT_MAX_TURNS = 2

#: Permission modes acceptable in LLM API mode. "plan" is the default;
#: "default" is what the native schema transport switches to per-call (and
#: is harmless with --tools ""). Anything looser (acceptEdits, dontAsk,
#: auto, bypassPermissions) signals an agent-executor intent and is refused.
_ALLOWED_PERMISSION_MODES = ("plan", "default")


class ClaudeCodePolicyError(ValueError):
    """A policy violates the LLM-API-compatible hermetic contract."""


@dataclass(frozen=True)
class ClaudeCodePolicy:
    """Frozen, validated execution policy for one provider instance.

    Field defaults ARE the hermetic contract; ``validate_policy`` rejects
    configurations that weaken it without an explicit, recorded opt-in.
    """

    mode: Literal["strict_reproducibility", "low_overhead"]
    max_turns: int = 1
    tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ("*",)
    disable_auto_memory: bool = True
    disable_prompt_history: bool = True
    bare: bool = True
    safe_mode: bool = True
    strict_mcp_config: bool = True
    disable_slash_commands: bool = True
    no_chrome: bool = True
    no_session_persistence: bool = True
    permission_mode: str = "plan"
    setting_sources: tuple[str, ...] = ()
    # --- policy extensions beyond CLI flags -------------------------------
    #: MCP servers the subprocess may see. Must stay empty in LLM API mode.
    mcp_servers: tuple[str, ...] = ()
    #: Session reuse (--resume/--continue/--session-id/continue_conversation).
    #: Must stay False; there is deliberately no code path that sets it.
    session_resume: bool = False
    #: Explicit user opt-in required for max_turns > 1 (except the native
    #: schema transport's fixed 2-turn profile).
    allow_multi_turn: bool = False
    #: How response_schema reaches Claude Code (see module constants).
    structured_output_transport: str = TRANSPORT_PROMPT
    #: True when the "bare" value was auto-resolved (no ANTHROPIC_API_KEY ->
    #: bare dropped so OAuth auth keeps working). Recorded in provenance.
    bare_auto_resolved: bool = field(default=False, compare=False)


def validate_policy(policy: ClaudeCodePolicy) -> None:
    """Fail loudly on any policy that weakens the hermetic LLM-API contract.

    Raises :class:`ClaudeCodePolicyError` listing *every* violation, not just
    the first, so a misconfigured YAML is fixable in one pass.
    """
    errors: list[str] = []

    if policy.mode not in VALID_MODES:
        errors.append(
            f"mode={policy.mode!r} is not one of {VALID_MODES}"
        )
    if policy.tools:
        errors.append(
            f"tools={list(policy.tools)!r} must be empty: the claude_code "
            "backend is an LLM API, not an agent executor"
        )
    if "*" not in policy.disallowed_tools:
        errors.append(
            f"disallowed_tools={list(policy.disallowed_tools)!r} must "
            'contain "*" (deny-all)'
        )
    if policy.mcp_servers:
        errors.append(
            f"mcp_servers={list(policy.mcp_servers)!r} must be empty"
        )
    if not policy.strict_mcp_config:
        errors.append("strict_mcp_config must be True (MCP suppression)")
    if policy.session_resume:
        errors.append(
            "session_resume must be False: resume/--continue/session_id "
            "reuse is forbidden in LLM API mode"
        )
    if not policy.disable_auto_memory:
        errors.append("disable_auto_memory must be True")
    if not policy.disable_prompt_history:
        errors.append("disable_prompt_history must be True")
    if not policy.safe_mode:
        errors.append("safe_mode must be True")
    if not policy.no_session_persistence:
        errors.append("no_session_persistence must be True")
    if not policy.disable_slash_commands:
        errors.append("disable_slash_commands must be True")
    if not policy.no_chrome:
        errors.append("no_chrome must be True")
    if policy.permission_mode not in _ALLOWED_PERMISSION_MODES:
        errors.append(
            f"permission_mode={policy.permission_mode!r} is not one of "
            f"{_ALLOWED_PERMISSION_MODES} (looser modes belong to a future "
            "agent-executor backend, not LLM API mode)"
        )
    if policy.setting_sources and set(policy.setting_sources) - {"user", "project", "local"}:
        errors.append(
            f"setting_sources={list(policy.setting_sources)!r} contains "
            "unknown sources (allowed: user, project, local — default empty)"
        )
    if policy.structured_output_transport not in VALID_TRANSPORTS:
        errors.append(
            f"structured_output_transport="
            f"{policy.structured_output_transport!r} is not one of "
            f"{VALID_TRANSPORTS}"
        )
    if policy.max_turns < 1:
        errors.append(f"max_turns={policy.max_turns} must be >= 1")
    elif policy.max_turns > 1 and not policy.allow_multi_turn:
        # The native transport's 2-turn profile is applied per-call by the
        # command builder and does not require raising the base max_turns;
        # a raised BASE value always needs the explicit opt-in.
        errors.append(
            f"max_turns={policy.max_turns} > 1 requires the explicit "
            "allow_multi_turn opt-in (llm.claude_code.allow_multi_turn)"
        )

    if errors:
        raise ClaudeCodePolicyError(
            "claude_code policy rejected (LLM API compatibility mode):\n- "
            + "\n- ".join(errors)
        )


def effective_max_turns(policy: ClaudeCodePolicy, *, native_schema_call: bool) -> int:
    """max_turns actually passed to Claude Code for one call.

    The native --json-schema transport needs one extra turn for the
    StructuredOutput tool round-trip (verified on 2.1.198).
    """
    if native_schema_call:
        return max(policy.max_turns, _NATIVE_TRANSPORT_MAX_TURNS)
    return policy.max_turns
