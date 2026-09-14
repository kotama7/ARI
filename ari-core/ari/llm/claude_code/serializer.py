"""Deterministic message → prompt serialization for the Claude Code provider.

ARI keeps the conversation history as its own source of truth (OpenAI-style
``messages``); Claude Code's session history is never the canonical record.
Every request therefore serializes the full message list into ONE prompt
string in a stable, byte-reproducible format. The same (system, messages,
schema) input always yields the same prompt — provenance hashes depend on it.

Format (see docs/reference/claude_code_provider.md):

    <conversation>
    <message role="user">
    ...
    </message>
    <message role="assistant">
    ...
    </message>
    </conversation>

    <response_contract>
    Return only JSON matching the supplied schema.
    <json_schema>
    {...}
    </json_schema>
    </response_contract>

The system prompt is NOT inlined here; it travels separately (via
``--system-prompt-file`` / the SDK ``system_prompt`` option) so that the
conversation body and the system contract are independently hashable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

_ALLOWED_ROLES = ("system", "user", "assistant")

RESPONSE_CONTRACT_PROMPT = (
    "Return only JSON matching the supplied schema. "
    "Do not wrap it in markdown fences and do not add prose."
)
RESPONSE_CONTRACT_NATIVE = (
    "Produce the structured output matching the supplied schema."
)


class ClaudeCodeSerializeError(ValueError):
    """Messages cannot be represented in LLM-API-compatible mode."""


@dataclass(frozen=True)
class SerializedPrompt:
    """Stable serialization of one request.

    ``schema_json`` is the canonical (sorted-keys) JSON text of the response
    schema — the exact bytes saved to schema.json and, for the native
    transport, passed to ``--json-schema``.
    """

    prompt: str
    system: str
    schema_json: str | None


def canonical_schema_json(response_schema: dict) -> str:
    return json.dumps(
        response_schema, sort_keys=True, indent=2, ensure_ascii=False
    )


def serialize_messages(
    messages: list[dict],
    system: str | None = None,
    response_schema: dict | None = None,
    *,
    embed_schema_in_prompt: bool = True,
) -> SerializedPrompt:
    """Serialize OpenAI-style messages into one deterministic prompt string.

    ``system``-role messages found in the list are folded (in order) into the
    system text, after any explicit ``system`` argument. Tool-role messages
    and assistant ``tool_calls`` are rejected: the claude_code backend is an
    LLM API without a tool protocol (see policy.py).
    """
    system_parts: list[str] = []
    if system:
        system_parts.append(str(system))

    body_lines: list[str] = ["<conversation>"]
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            # LLMMessage dataclass or anything with role/content attributes.
            role = getattr(m, "role", None)
            content = getattr(m, "content", None)
            m = {"role": role, "content": content}
        role = m.get("role")
        if role not in _ALLOWED_ROLES:
            raise ClaudeCodeSerializeError(
                f"messages[{i}].role={role!r} is not supported by the "
                f"claude_code backend (allowed: {_ALLOWED_ROLES}). "
                "Tool-protocol messages require a tool-calling backend."
            )
        if m.get("tool_calls"):
            raise ClaudeCodeSerializeError(
                f"messages[{i}] carries tool_calls; the claude_code backend "
                "does not speak the OpenAI tool protocol"
            )
        content = m.get("content")
        content = "" if content is None else str(content)
        if role == "system":
            system_parts.append(content)
            continue
        body_lines.append(f'<message role="{role}">')
        body_lines.append(content)
        body_lines.append("</message>")
    body_lines.append("</conversation>")

    schema_json: str | None = None
    if response_schema is not None:
        schema_json = canonical_schema_json(response_schema)
        body_lines.append("")
        body_lines.append("<response_contract>")
        if embed_schema_in_prompt:
            body_lines.append(RESPONSE_CONTRACT_PROMPT)
            body_lines.append("<json_schema>")
            body_lines.append(schema_json)
            body_lines.append("</json_schema>")
        else:
            body_lines.append(RESPONSE_CONTRACT_NATIVE)
        body_lines.append("</response_contract>")

    return SerializedPrompt(
        prompt="\n".join(body_lines),
        system="\n\n".join(p for p in system_parts if p),
        schema_json=schema_json,
    )


def build_repair_prompt(
    original: SerializedPrompt, invalid_output: str, errors: list[str]
) -> str:
    """Prompt for the single schema-repair retry (same hermetic policy).

    Deterministic function of (original prompt, previous output, validation
    errors); saved verbatim to the retry attempt's provenance.
    """
    return "\n".join(
        [
            original.prompt,
            "",
            "<previous_invalid_output>",
            invalid_output,
            "</previous_invalid_output>",
            "",
            "<repair_instruction>",
            "Your previous output failed JSON schema validation:",
            *[f"- {e}" for e in errors],
            "Return ONLY corrected JSON matching the schema. No prose.",
            "</repair_instruction>",
        ]
    )
