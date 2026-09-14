"""OpenAI-compatible HTTP shim that serves agentic CLIs (`claude -p`,
`codex exec`) as chat-completion backends.

ARI talks to every model through ``litellm`` (see ``ari/llm/client.py``).
litellm speaks the OpenAI ``/v1/chat/completions`` protocol, so this shim lets
ARI drive the Claude Code / Codex CLIs by pointing ``base_url`` at it — no
changes to the agent loop required.

Register in ARI config (config/*.yaml or the GUI wizard)::

    llm:
      backend: openai
      model: openai/claude-cli   # "openai/" => litellm routes to base_url
      base_url: http://localhost:8900/v1
      api_key: dummy             # litellm requires a key; the shim ignores it

The ``openai/`` prefix tells litellm to use its OpenAI-compatible handler and
dial ``base_url``; litellm strips the prefix before calling, so the shim sees
``claude-cli``. ``parse_model`` also tolerates the prefix defensively.

Virtual models (the ``model`` field selects engine + mode)::

    claude-cli            claude -p, text + tool_calls -> drives ARI's ReAct loop
    claude-cli-agent      claude -p, own tool loop     -> final text only
    codex-cli             codex exec, text + tool_calls-> drives ARI's ReAct loop
    codex-cli-agent       codex exec, full auto        -> final text only

    # append ":<alias>" to pick the underlying model, e.g.
    claude-cli:sonnet     codex-cli-agent:gpt-5-codex

Endpoints::

    POST /v1/chat/completions   OpenAI chat completions (non-stream + stream)
    GET  /v1/models             list the virtual models
    GET  /healthz               liveness probe (used by start.sh)

Function calling: the plain modes (``claude-cli`` / ``codex-cli``) accept the
OpenAI ``tools`` / ``tool_choice`` request fields and return OpenAI
``tool_calls`` with ``finish_reason="tool_calls"``, so they drive ARI's own
ReAct tool loop identically to a real OpenAI / Anthropic API key. Because the
CLIs only emit final text (no native structured tool-use is exposed to the
caller), the shim injects the tool catalog into the prompt, asks the CLI to
emit a tool call as a JSON object, and parses that back into OpenAI
``tool_calls`` (``arguments`` is the JSON-encoded string OpenAI uses). When no
``tools`` are sent the response is plain text exactly as before (judge / expand
/ select). The ``-agent`` modes still return only the CLI's final text (the CLI
runs its *own* tool loop), so they are for whole-task delegation, not ReAct.

IMPORTANT — billing / auth (see also the project docs): the shim shells out to
the real ``claude`` / ``codex`` binaries, so requests consume tokens against
whatever auth those CLIs use (subscription login *or* API key).

Isolation — launch recipe. Every ``claude`` subprocess is started with
``--strict-mcp-config`` (only servers from an explicit ``--mcp-config`` are
used; ambient project/user MCP configs are ignored — without this a nested
claude inherited the parent session's project and booted all 15 ari-skill
servers per call). The ``codex`` path is symmetric and its isolation is
UNCONDITIONAL too: every ``codex`` subprocess gets ``--ignore-user-config``
(the analogue of ``--strict-mcp-config`` — the user's ``~/.codex/config.toml``
mcp_servers are never loaded; auth still resolves from ``CODEX_HOME``) AND
``-c features.apps=false`` (codex bundles curated apps — GitHub / Calendar /
Sites, ~129 tools — WITH the binary, which ``--ignore-user-config`` does NOT
remove; leaving them on is a hermeticity + safety hole and ~5x the input
tokens). The MCP-direct path then injects the same server set via
``-c mcp_servers.<name>.{command,args,env}`` (BARE key) with a per-server
``enabled_tools`` allowlist. So the caller's ``{"mcpServers": …}`` +
``mcp__server__tool`` allowlist drives BOTH engines identically — attaching a
server, detaching MCP (no config → plain mode), or detaching memory (server
omitted, or its write tools filtered out of the allowlist) is honored the same
way whichever CLI runs. When the shim itself is started from inside a Claude
Code session, sever the parent-session linkage by launching with a sanitized
environment::

    env -i HOME="$HOME" PATH="$PATH" \
        python -m ari.llm.cli_server --port 8900

(the shim warns at startup when ``CLAUDECODE`` / ``CLAUDE_CODE_*`` are still
present; it never auto-sanitizes because auth setups vary).

Knobs: ``ARI_CLI_SHIM_CLAUDE_MAX_TURNS=<int>`` appends ``--max-turns N`` to
cap the delegated claude's internal tool loop (unset = no flag); it depends
on the installed ``claude`` CLI version supporting ``--max-turns``.
``ARI_CLI_SHIM_CLAUDE_BARE=1`` adds ``--bare`` — CAVEAT: per ``claude --help``
bare mode reads auth strictly from ``ANTHROPIC_API_KEY`` (OAuth/keychain are
never read), so it MUST NOT be used with subscription (login) auth; keep it
for API-key setups only.
"""

from __future__ import annotations

import argparse
import atexit
import base64
import binascii
import json
import logging
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("ari.llm.cli_server")

# ──────────────────────────────────────────────────────────────────────────
# Configuration (all overridable via env)
# ──────────────────────────────────────────────────────────────────────────
DEFAULT_PORT = int(os.environ.get("ARI_CLI_SHIM_PORT", "8900"))
TIMEOUT = float(os.environ.get("ARI_CLI_SHIM_TIMEOUT", "1800"))
MAX_CONCURRENCY = int(os.environ.get("ARI_CLI_SHIM_MAX_CONCURRENCY", "4"))
CLAUDE_BIN = os.environ.get("ARI_CLI_SHIM_CLAUDE_BIN", "claude")
CODEX_BIN = os.environ.get("ARI_CLI_SHIM_CODEX_BIN", "codex")
# codex reasoning effort (`-c model_reasoning_effort=<x>`), e.g. minimal | low |
# medium | high. `--ignore-user-config` drops the user's config default, so
# without this codex uses its compiled default, which for a reasoning model is
# slow — ARI drives MANY calls per run (a full paper pipeline hit the 90-min
# per-stage subprocess cap on iterative citation collection alone). Empty =
# don't override (codex default). Set e.g. ARI_CLI_SHIM_CODEX_REASONING=low to
# make the whole pipeline tractable.
CODEX_REASONING = os.environ.get("ARI_CLI_SHIM_CODEX_REASONING", "").strip()
# Linux limits each individual argv string to MAX_ARG_STRLEN (normally 128
# KiB), independently of ARG_MAX.  Keep substantial headroom for UTF-8 and use
# codex's documented ``-`` stdin transport above this size.
_CODEX_ARG_PROMPT_MAX_BYTES = 64 * 1024
# Pass `claude --bare`: minimal mode (no CLAUDE.md/hooks/auto-memory). Strongly
# cuts the per-call input-token overhead but forces ANTHROPIC_API_KEY auth —
# bare mode never reads OAuth/keychain credentials (see `claude --help`), so
# it breaks subscription-auth setups. API-key setups only.
CLAUDE_BARE = os.environ.get("ARI_CLI_SHIM_CLAUDE_BARE", "0") == "1"


def _env_int(name: str) -> int:
    """Read an int env knob; unset/blank/garbage -> 0 (feature off)."""
    try:
        return int(os.environ.get(name, "") or 0)
    except ValueError:
        return 0


# Optional cap on the delegated claude's internal tool loop (--max-turns N).
# Upstreams the wrapper-script workaround; 0/unset = no flag.
CLAUDE_MAX_TURNS = _env_int("ARI_CLI_SHIM_CLAUDE_MAX_TURNS")
# Permission mode for claude-cli-agent (claude --permission-mode ...).
CLAUDE_AGENT_PERMISSION = os.environ.get(
    "ARI_CLI_SHIM_CLAUDE_AGENT_PERMISSION", "acceptEdits"
)
# Optional per-call spend cap for claude (claude --max-budget-usd).
MAX_BUDGET_USD = os.environ.get("ARI_CLI_SHIM_MAX_BUDGET_USD", "").strip()
# Working dir for agent-mode runs (file edits / commands land here). When
# unset each request gets a throwaway temp dir.
SHIM_CWD = os.environ.get("ARI_CLI_SHIM_CWD", "").strip()

# Cap simultaneous CLI subprocesses so a burst of requests can't fork-bomb the
# host. Acquired for the duration of each completion.
_slots = threading.BoundedSemaphore(max(1, MAX_CONCURRENCY))

# ``codex exec`` normally exposes its own apply_patch tool according to model
# catalog metadata.  Text-catalog requests must not expose that tool: it
# competes with caller-owned functions and operates in codex's private cwd.
# Build one process-scoped catalog lazily, preserving every bundled model field
# while disabling native shell/patch capabilities.  The required-tool response
# schema below then makes the caller-owned JSON protocol unambiguous.
_CODEX_TEXT_CATALOG_LOCK = threading.Lock()
_CODEX_TEXT_CATALOG_PATH: str | None = None


def _cleanup_codex_text_catalog() -> None:
    path = _CODEX_TEXT_CATALOG_PATH
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


atexit.register(_cleanup_codex_text_catalog)


# ──────────────────────────────────────────────────────────────────────────
# Model routing
# ──────────────────────────────────────────────────────────────────────────
class ShimError(Exception):
    """Raised for client-facing 4xx errors (bad model, bad request)."""


def parse_model(model: str) -> tuple[str, bool, str | None]:
    """Split a virtual model id into ``(engine, agent, real_model)``.

    ``engine`` is "claude" or "codex"; ``agent`` selects the tool-using mode;
    ``real_model`` is the optional ``:alias`` suffix (None => CLI default).
    """
    name = (model or "").strip()
    # litellm normally strips the "openai/" routing prefix, but tolerate it in
    # case a caller passes the model id through verbatim.
    if name.startswith("openai/"):
        name = name[len("openai/"):]
    real_model: str | None = None
    if ":" in name:
        name, real_model = name.split(":", 1)
        real_model = real_model.strip() or None
    agent = name.endswith("-agent")
    if agent:
        name = name[: -len("-agent")]
    if name in ("claude-cli", "claude"):
        return "claude", agent, real_model
    if name in ("codex-cli", "codex"):
        return "codex", agent, real_model
    raise ShimError(
        f"unknown model {model!r}; expected one of claude-cli, "
        f"claude-cli-agent, codex-cli, codex-cli-agent (optional :alias)"
    )


def _content_text(content) -> str:
    """Collapse OpenAI content parts to text while retaining image positions."""
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif part.get("type") in {"image_url", "input_image"}:
                parts.append("\n[attached image]\n")
        return "".join(parts)
    return str(content or "")


_IMAGE_SUFFIXES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_MAX_ATTACHED_IMAGES = 20
_MAX_ATTACHED_IMAGE_BYTES = 32 * 1024 * 1024
_MAX_ATTACHED_TOTAL_BYTES = 100 * 1024 * 1024


def _message_image_payloads(messages: list[dict]) -> list[tuple[str, bytes]]:
    """Decode bounded embedded OpenAI image parts for a CLI invocation.

    Codex accepts filesystem paths via ``codex exec --image`` whereas the
    OpenAI-compatible request carries data URLs.  Only embedded, base64 image
    URLs are admitted: fetching remote URLs inside the local shim would add an
    unrecorded network side effect and an SSRF surface.
    """
    payloads: list[tuple[str, bytes]] = []
    total_bytes = 0
    for message in messages or []:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if (
                not isinstance(part, dict)
                or part.get("type") not in {"image_url", "input_image"}
            ):
                continue
            image_value = part.get("image_url")
            if isinstance(image_value, dict):
                image_value = image_value.get("url")
            if not isinstance(image_value, str) or not image_value:
                raise ShimError("image content part lacks image_url.url")
            if not image_value.startswith("data:"):
                raise ShimError(
                    "cli-shim image inputs must be embedded data URLs; "
                    "remote image fetching is disabled"
                )
            try:
                header, encoded = image_value.split(",", 1)
            except ValueError as exc:
                raise ShimError("malformed image data URL") from exc
            media_type = header[5:].split(";", 1)[0].lower()
            if media_type not in _IMAGE_SUFFIXES or ";base64" not in header.lower():
                raise ShimError(
                    "image data URL must be base64 PNG, JPEG, WEBP, or GIF"
                )
            try:
                payload = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ShimError("image data URL contains invalid base64") from exc
            if not payload or len(payload) > _MAX_ATTACHED_IMAGE_BYTES:
                raise ShimError("attached image is empty or exceeds 32 MiB")
            total_bytes += len(payload)
            if total_bytes > _MAX_ATTACHED_TOTAL_BYTES:
                raise ShimError("attached images exceed the 100 MiB request limit")
            payloads.append((media_type, payload))
            if len(payloads) > _MAX_ATTACHED_IMAGES:
                raise ShimError("request contains more than 20 attached images")
    return payloads


def _materialize_codex_images(
    payloads: list[tuple[str, bytes]], cwd: str
) -> list[str]:
    """Write request-scoped image files for ``codex exec --image``."""
    paths: list[str] = []
    try:
        for media_type, payload in payloads:
            fd, path = tempfile.mkstemp(
                prefix=".ari-cli-image-",
                suffix=_IMAGE_SUFFIXES[media_type],
                dir=cwd,
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
            paths.append(path)
        return paths
    except Exception:
        for path in paths:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise


def _render_assistant_tool_calls(tool_calls: list[dict]) -> str:
    """Render prior assistant ``tool_calls`` back into the same JSON protocol
    the CLI is asked to emit, so the transcript the model sees is consistent
    with its own earlier actions."""
    calls = []
    for tc in tool_calls or []:
        fn = tc.get("function", {}) or {}
        raw_args = fn.get("arguments", "")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except (json.JSONDecodeError, TypeError):
            args = raw_args
        calls.append({"name": fn.get("name", ""), "arguments": args})
    return json.dumps({"tool_calls": calls}, ensure_ascii=False)


def render_prompt(messages: list[dict]) -> tuple[str, str]:
    """Flatten OpenAI ``messages`` into ``(system_text, prompt_text)``.

    System messages are concatenated separately so claude can receive them via
    ``--system-prompt``; the remaining turns are rendered as a plain transcript
    fed to the CLI on stdin. Assistant ``tool_calls`` and ``tool`` results are
    rendered so a multi-turn ReAct exchange round-trips through the text CLI.
    """
    system_parts: list[str] = []
    turns: list[str] = []
    # Map a tool_call id -> tool name so tool-result turns can be labelled.
    id_to_name: dict[str, str] = {}
    for m in messages or []:
        for tc in m.get("tool_calls") or []:
            cid = tc.get("id")
            name = (tc.get("function", {}) or {}).get("name", "")
            if cid:
                id_to_name[cid] = name
    for m in messages or []:
        role = m.get("role", "user")
        content = _content_text(m.get("content", ""))
        if role == "system":
            system_parts.append(content)
        elif role == "assistant":
            tcs = m.get("tool_calls")
            if tcs:
                rendered = _render_assistant_tool_calls(tcs)
                turns.append(
                    f"Assistant: {content}\n{rendered}" if content
                    else f"Assistant: {rendered}"
                )
            else:
                turns.append(f"Assistant: {content}")
        elif role == "tool":
            name = id_to_name.get(m.get("tool_call_id", ""), "")
            label = f"Tool result ({name})" if name else "Tool result"
            turns.append(f"{label}: {content}")
        else:
            turns.append(f"User: {content}")
    system_text = "\n\n".join(p for p in system_parts if p).strip()
    # A single user turn is by far the common case — send it verbatim so the
    # CLI sees a clean prompt rather than a "User:"-prefixed transcript.
    if len(turns) == 1 and turns[0].startswith("User: "):
        prompt_text = turns[0][len("User: "):]
    else:
        prompt_text = "\n\n".join(turns).strip()
    return system_text, prompt_text


# ──────────────────────────────────────────────────────────────────────────
# Function calling (OpenAI tools <-> text-CLI JSON protocol)
# ──────────────────────────────────────────────────────────────────────────
def _render_tool_catalog(tools: list[dict]) -> str:
    """Render OpenAI ``tools`` into a compact text catalog for the prompt."""
    lines = ["AVAILABLE TOOLS (call via the JSON protocol below):"]
    for t in tools or []:
        fn = t.get("function", t) if isinstance(t, dict) else {}
        name = fn.get("name", "")
        if not name:
            continue
        desc = (fn.get("description", "") or "").strip()
        params = fn.get("parameters", {}) or {}
        lines.append(f"\n- {name}: {desc}".rstrip())
        lines.append(f"  parameters (JSON Schema): {json.dumps(params, ensure_ascii=False)}")
    return "\n".join(lines)


def _tool_protocol_instructions(tool_choice) -> str:
    """Instruction block telling the CLI how to emit tool calls as JSON."""
    forced_name = None
    if isinstance(tool_choice, dict):
        forced_name = (tool_choice.get("function") or {}).get("name")
    must = tool_choice == "required" or forced_name is not None
    out = [
        "TOOL-CALL PROTOCOL:",
        "You are a function-call adapter, not an interactive coding agent.",
        "Do NOT use any CLI-native shell, filesystem, patch, app, MCP, or "
        "network tool. Those tools run inside the CLI's isolated sandbox and "
        "cannot invoke the caller-owned functions listed above.",
        "The ONLY valid way to invoke an available tool is to emit the JSON "
        "object specified below.",
        "To call tools, respond with ONLY a single JSON object and NOTHING "
        "else — no prose, no explanation, no markdown code fences — in exactly "
        "this shape:",
        '{"tool_calls": [{"name": "<tool_name>", "arguments": {<args>}}]}',
        "- `arguments` is a JSON object matching that tool's parameter schema.",
        "- Include multiple entries to call several tools in one turn.",
    ]
    if forced_name:
        out.append(f"- You MUST call the tool named `{forced_name}` this turn.")
    elif must:
        out.append("- You MUST call at least one tool. Do not reply in plain text.")
    else:
        out.append(
            "- If no tool is needed, reply with plain text instead of the JSON object."
        )
    return "\n".join(out)


def _iter_json_candidates(text: str):
    """Yield candidate JSON substrings from ``text`` (whole, fenced, first
    balanced object), most-specific first."""
    s = (text or "").strip()
    if not s:
        return
    # 1) Fenced code blocks (```json ... ``` or ``` ... ```).
    for m in re.finditer(r"```(?:json)?\s*(.*?)```", s, re.DOTALL):
        inner = m.group(1).strip()
        if inner:
            yield inner
    # 2) The whole string.
    yield s
    # 3) First balanced {...} object (handles prose around the JSON).
    start = s.find("{")
    if start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            c = s[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        yield s[start:i + 1]
                        break


def _coerce_tool_calls(obj) -> list[dict] | None:
    """Turn a parsed JSON object into OpenAI ``tool_calls``, or None."""
    raw: list = []
    if isinstance(obj, dict) and isinstance(obj.get("tool_calls"), list):
        raw = obj["tool_calls"]
    elif isinstance(obj, list):
        raw = obj
    elif isinstance(obj, dict) and (obj.get("name") or obj.get("tool")):
        raw = [obj]
    else:
        return None
    calls: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        # Accept {name,arguments}, {tool,arguments}, or nested {function:{...}}.
        fn = entry.get("function") if isinstance(entry.get("function"), dict) else entry
        name = fn.get("name") or entry.get("tool") or entry.get("name")
        if not name:
            continue
        args = fn.get("arguments", entry.get("arguments", {}))
        if isinstance(args, str):
            # Already a JSON string; keep if it parses, else wrap as-is.
            try:
                json.loads(args)
                args_str = args
            except (json.JSONDecodeError, TypeError):
                args_str = json.dumps({"_raw": args}, ensure_ascii=False)
        else:
            args_str = json.dumps(args if args is not None else {}, ensure_ascii=False)
        calls.append({
            "id": f"call_{uuid.uuid4().hex[:24]}",
            "type": "function",
            "function": {"name": str(name), "arguments": args_str},
        })
    return calls or None


def _schema_accepts_null(schema: dict) -> bool:
    """Return whether an input JSON Schema explicitly admits ``null``."""
    if not isinstance(schema, dict):
        return False
    schema_type = schema.get("type")
    if schema_type == "null" or (
        isinstance(schema_type, list) and "null" in schema_type
    ):
        return True
    if schema.get("nullable") is True or schema.get("const", object()) is None:
        return True
    if isinstance(schema.get("enum"), list) and None in schema["enum"]:
        return True
    return any(
        isinstance(branches, list)
        and any(
            isinstance(branch, dict) and _schema_accepts_null(branch)
            for branch in branches
        )
        for branches in (schema.get("anyOf"), schema.get("oneOf"))
    )


def _sanitize_schema_value(value, schema: dict):
    """Undo only artifacts introduced by the Codex strict-output schema.

    Codex requires every declared object property, so optional properties are
    made nullable in :func:`_codex_strict_schema_node`.  A returned null for
    one of those synthetic fields must be removed before the caller validates
    its original input schema.  Required or originally-nullable values remain
    untouched, including nested objects.  Undeclared keys are rejected for a
    closed, property-bearing tool schema while genuinely open object schemas
    retain their JSON Schema ``additionalProperties`` behaviour.
    """
    if not isinstance(schema, dict):
        return value
    if isinstance(value, dict):
        declared = schema.get("properties")
        properties = declared if isinstance(declared, dict) else None
        required = set(schema.get("required") or [])
        additional = schema.get("additionalProperties", None)
        sanitized: dict = {}
        for key, item in value.items():
            if properties is not None and key in properties:
                property_schema = properties[key]
                if not isinstance(property_schema, dict):
                    property_schema = {}
                if (
                    item is None
                    and key not in required
                    and not _schema_accepts_null(property_schema)
                ):
                    continue
                sanitized[key] = _sanitize_schema_value(item, property_schema)
                continue

            # A schema that declares properties is treated as the closed tool
            # argument vocabulary unless it explicitly opts back into extra
            # keys.  A bare {"type": "object"}, however, is genuinely open.
            if properties is not None:
                if additional is True:
                    sanitized[key] = item
                elif isinstance(additional, dict):
                    sanitized[key] = _sanitize_schema_value(item, additional)
                continue
            if additional is False:
                continue
            if isinstance(additional, dict):
                sanitized[key] = _sanitize_schema_value(item, additional)
            else:
                sanitized[key] = item
        return sanitized
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        return [_sanitize_schema_value(item, schema["items"]) for item in value]
    return value


def _sanitize_tool_call_arguments(
    calls: list[dict], tools: list[dict] | None
) -> list[dict]:
    """Remove schema-only nullable fields before caller tool validation."""
    schemas_by_name: dict[str, dict] = {}
    for tool in tools or []:
        fn = tool.get("function", tool) if isinstance(tool, dict) else {}
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        params = fn.get("parameters") or {}
        if isinstance(params, dict):
            schemas_by_name[str(fn["name"])] = params
    for call in calls:
        fn = call.get("function") or {}
        name = str(fn.get("name") or "")
        try:
            arguments = json.loads(fn.get("arguments") or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(arguments, dict):
            continue
        schema = schemas_by_name.get(name)
        if schema is not None:
            arguments = _sanitize_schema_value(arguments, schema)
        fn["arguments"] = json.dumps(arguments, ensure_ascii=False)
    return calls


def extract_tool_calls(
    text: str, *, tools: list[dict] | None = None
) -> tuple[list[dict] | None, str]:
    """Parse a CLI text response into ``(tool_calls, residual_text)``.

    Returns ``(None, text)`` when the response carries no tool-call JSON.
    """
    for cand in _iter_json_candidates(text):
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        calls = _coerce_tool_calls(obj)
        if calls:
            return _sanitize_tool_call_arguments(calls, tools), ""
    return None, text


# ──────────────────────────────────────────────────────────────────────────
# CLI invocation
# ──────────────────────────────────────────────────────────────────────────
def _run(cmd: list[str], stdin_text: str, cwd: str) -> subprocess.CompletedProcess:
    log.info("shim exec: %s (cwd=%s, stdin=%dB)", cmd[0:3], cwd, len(stdin_text))
    return subprocess.run(
        cmd,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        cwd=cwd,
    )


def _codex_text_catalog_model_catalog() -> str:
    """Return a cached bundled codex catalog with native edit tools disabled.

    Codex decides whether to expose ``apply_patch`` from per-model catalog
    metadata, not from a normal feature flag.  Its authoritative
    ``debug models --bundled`` command gives us a version-matched catalog;
    changing only ``apply_patch_tool_type`` and ``shell_type`` avoids a stale
    hand-maintained list as new codex models are released.

    Failure is deliberate and loud.  Silently falling back would let an ARI
    caller believe its tools were used while codex actually edited an isolated
    temporary workspace.
    """
    global _CODEX_TEXT_CATALOG_PATH
    with _CODEX_TEXT_CATALOG_LOCK:
        cached = _CODEX_TEXT_CATALOG_PATH
        if cached and os.path.isfile(cached):
            return cached

        proc = subprocess.run(
            [CODEX_BIN, "debug", "models", "--bundled"],
            input="",
            capture_output=True,
            text=True,
            timeout=min(TIMEOUT, 60),
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "unknown error")[:500]
            raise RuntimeError(
                "codex cannot create an isolated text-tool catalog: " + detail
            )
        try:
            payload = json.loads(proc.stdout)
            models = payload["models"]
            if not isinstance(models, list) or not models:
                raise ValueError("models must be a non-empty list")
            for model in models:
                if not isinstance(model, dict):
                    raise ValueError("each model entry must be an object")
                model["apply_patch_tool_type"] = None
                model["shell_type"] = "disabled"
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"codex returned an invalid bundled model catalog: {exc}"
            ) from exc

        with tempfile.NamedTemporaryFile(
            "w", prefix="ari-codex-text-tools-", suffix=".json", delete=False,
            encoding="utf-8",
        ) as fh:
            json.dump(payload, fh, ensure_ascii=False, sort_keys=True)
            fh.write("\n")
            path = fh.name
        _CODEX_TEXT_CATALOG_PATH = path
        return path


def _codex_strict_schema_node(node: dict, *, nullable: bool = False) -> dict:
    """Convert an input-tool JSON Schema into codex strict-output form.

    Strict structured output requires every declared object property to appear.
    Input tools commonly have optional parameters, so those properties become
    required-but-nullable here; ``extract_tool_calls`` removes their nulls
    before handing the call back to the real tool executor.
    """
    originally_nullable = _schema_accepts_null(node or {})
    out = {
        key: json.loads(json.dumps(value))
        for key, value in (node or {}).items()
        if key not in {"default", "nullable"}
    }
    node_type = out.get("type")
    is_object = node_type == "object" or (
        isinstance(node_type, list) and "object" in node_type
    )
    is_array = node_type == "array" or (
        isinstance(node_type, list) and "array" in node_type
    )
    if is_object or "properties" in out:
        properties = out.get("properties") or {}
        originally_required = set(out.get("required") or [])
        out["type"] = ["object", "null"] if originally_nullable else "object"
        out["properties"] = {
            name: _codex_strict_schema_node(
                schema if isinstance(schema, dict) else {},
                nullable=name not in originally_required,
            )
            for name, schema in properties.items()
        }
        out["required"] = list(properties)
        out["additionalProperties"] = False
    elif is_array and isinstance(out.get("items"), dict):
        out["type"] = ["array", "null"] if originally_nullable else "array"
        out["items"] = _codex_strict_schema_node(out["items"])
    for keyword in ("anyOf", "oneOf", "allOf"):
        if isinstance(out.get(keyword), list):
            out[keyword] = [
                _codex_strict_schema_node(item)
                if isinstance(item, dict)
                else item
                for item in out[keyword]
            ]
    if nullable:
        schema_type = out.get("type")
        if isinstance(schema_type, str):
            out["type"] = [schema_type, "null"]
            if isinstance(out.get("enum"), list) and None not in out["enum"]:
                out["enum"].append(None)
        elif isinstance(schema_type, list):
            if "null" not in schema_type:
                out["type"] = [*schema_type, "null"]
        else:
            out = {"anyOf": [out, {"type": "null"}]}
    return out


def _codex_required_tool_schema(
    tools: list[dict], tool_names: list[str]
) -> dict:
    """Build a strict final-output schema for caller-owned tool calls."""
    names = list(dict.fromkeys(str(name) for name in tool_names if name))
    allowed = set(names)
    variants: list[dict] = []
    for tool in tools or []:
        fn = tool.get("function", tool) if isinstance(tool, dict) else {}
        name = fn.get("name") if isinstance(fn, dict) else None
        if not name or str(name) not in allowed:
            continue
        params = fn.get("parameters") or {"type": "object", "properties": {}}
        variants.append({
            "type": "object",
            "properties": {
                "name": {"type": "string", "enum": [str(name)]},
                "arguments": _codex_strict_schema_node(params),
            },
            "required": ["name", "arguments"],
            "additionalProperties": False,
        })
    if not variants:
        raise ShimError("required tool choice has no named tools")
    item_schema = variants[0] if len(variants) == 1 else {"anyOf": variants}
    return {
        "type": "object",
        "properties": {
            "tool_calls": {
                "type": "array",
                "minItems": 1,
                "items": item_schema,
            },
        },
        "required": ["tool_calls"],
        "additionalProperties": False,
    }


#: Template key for the bare→qualified tool-name table appended to the
#: delegated ``--system-prompt``. Ungoverned (not in FOUNDING_PROMPT_TABLE):
#: it is a mechanical name-mapping notice, not an actor's instructions, so
#: there is no role for RQGM to evolve it under.
_NAME_RESOLUTION_PROMPT_KEY = "llm/mcp_name_resolution"


def mcp_name_resolution_note(allowed_mcp_tools: list[str] | None) -> str:
    """A bare-name → fully-qualified-MCP-name table for the delegated claude.

    ARI's agent prompts name tools BARE (``call survey() NOW``,
    ``WORKFLOW ORDER: (1) generate_ideas() …``) because in-process those are the
    names ``MCPClient.call_tool`` takes. Under MCP delegation claude sees the
    same tools under Claude-Code's namespaced form ``mcp__<server>__<tool>``,
    and a bare name is not callable — it fails with
    ``Error: No such tool available: survey``. Observed 2026-07-20: the
    delegated model dutifully called ``survey()``, got that error, and spent the
    node's whole step budget re-probing instead of doing the work, so the
    exploration phase produced zero artifacts.

    The shim is the only layer that holds BOTH vocabularies, so it publishes the
    mapping. Returns ``""`` when there is nothing to map (no delegation), which
    keeps the non-MCP prompt byte-identical."""
    pairs: list[tuple[str, str]] = []
    for full in allowed_mcp_tools or []:
        parts = str(full).split("__")
        if len(parts) >= 3 and parts[0] == "mcp":
            bare = "__".join(parts[2:])          # tool names may contain "__"
            if bare:
                pairs.append((bare, str(full)))
    if not pairs:
        return ""
    rows = "\n".join(f"  {bare}()  ->  {full}"
                     for bare, full in sorted(set(pairs)))
    # The note body lives in ``ari/prompts/llm/mcp_name_resolution.md`` rather
    # than inline: ari-core carries NO inline prompt literals (the invariant
    # scripts/tests/test_check_prompts.py enforces for this package), and an
    # externalised template also gets a snapshot, so a wording change is
    # reviewable as a diff instead of vanishing into a string concat.
    from ari.prompts import FilesystemPromptLoader

    template = FilesystemPromptLoader().load(_NAME_RESOLUTION_PROMPT_KEY)
    return "\n\n" + template.format(rows=rows).rstrip("\n")


def _materialize_mcp_credential_env(
    mcp_config: dict,
    source_env: dict[str, str] | None = None,
) -> dict:
    """Resolve value-free credential references in a local MCP config copy."""

    source = source_env if source_env is not None else os.environ
    materialized = json.loads(json.dumps(mcp_config))
    servers = materialized.get("mcpServers")
    if not isinstance(servers, dict):
        raise ValueError("mcp_config.mcpServers must be an object")
    for name, server in servers.items():
        if not isinstance(server, dict):
            raise ValueError(f"MCP server {name!r} must be an object")
        refs = server.pop("_ariCredentialEnv", [])
        if not isinstance(refs, list) or any(
            not isinstance(ref, str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", ref)
            for ref in refs
        ):
            raise ValueError(f"MCP server {name!r} has invalid credential env refs")
        environment = server.setdefault("env", {})
        if not isinstance(environment, dict):
            raise ValueError(f"MCP server {name!r} env must be an object")
        for ref in refs:
            value = source.get(ref)
            if not value:
                raise ValueError(
                    f"MCP server {name!r} credential env ref {ref!r} is unavailable"
                )
            environment[ref] = value
    return materialized


def _mcp_credential_values(
    mcp_config: dict,
    source_env: dict[str, str] | None = None,
) -> tuple[str, ...]:
    """Return present local values referenced by an already validated config."""

    source = source_env if source_env is not None else os.environ
    values: set[str] = set()
    for server in (mcp_config.get("mcpServers") or {}).values():
        if not isinstance(server, dict):
            continue
        for name in server.get("_ariCredentialEnv") or []:
            value = source.get(name)
            if value:
                values.add(value)
    return tuple(sorted(values, key=len, reverse=True))


def _redact_mcp_credential_values(text: str | None, values: tuple[str, ...]) -> str:
    rendered = text or ""
    for value in values:
        rendered = rendered.replace(value, "<redacted:credential>")
        escaped = json.dumps(value, ensure_ascii=False)[1:-1]
        rendered = rendered.replace(escaped, "<redacted:credential>")
    return rendered


def _write_claude_mcp_config(mcp_config: dict, cwd: str) -> str:
    """Write a mode-0600 local config and remove partial files on failure."""

    materialized = _materialize_mcp_credential_env(mcp_config)
    path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".mcp.json", dir=cwd, delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
            json.dump(materialized, fh)
        os.chmod(path, 0o600)
        return path
    except BaseException:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise


def _build_claude_command(
    *,
    system: str,
    agent: bool,
    real_model: str | None,
    use_mcp: bool,
    mcp_json_file: str | None,
    allowed_mcp_tools: list[str] | None,
    debug_log: str | None,
) -> list[str]:
    """Build the Claude CLI argv after any secret-bearing file is materialized."""

    output_format = "stream-json" if use_mcp else "json"
    cmd = [
        CLAUDE_BIN,
        "-p",
        "--output-format",
        output_format,
        "--strict-mcp-config",
    ]
    if use_mcp:
        cmd.append("--verbose")
    if CLAUDE_BARE:
        cmd.append("--bare")
    if real_model:
        cmd += ["--model", real_model]
    if system:
        cmd += ["--system-prompt", system]
    if use_mcp:
        if not mcp_json_file or not debug_log:
            raise ValueError("MCP Claude invocation requires config and debug paths")
        cmd += [
            "--mcp-config",
            mcp_json_file,
            "--allowedTools",
            " ".join(allowed_mcp_tools or []),
            "--permission-mode",
            CLAUDE_AGENT_PERMISSION,
            "--debug-file",
            debug_log,
        ]
    elif agent:
        cmd += ["--permission-mode", CLAUDE_AGENT_PERMISSION]
    else:
        cmd += ["--allowedTools", ""]
    if MAX_BUDGET_USD:
        cmd += ["--max-budget-usd", MAX_BUDGET_USD]
    if CLAUDE_MAX_TURNS > 0:
        cmd += ["--max-turns", str(CLAUDE_MAX_TURNS)]
    return cmd


def run_claude(
    system: str,
    prompt: str,
    agent: bool,
    real_model: str | None,
    cwd: str,
    *,
    mcp_config: dict | None = None,
    allowed_mcp_tools: list[str] | None = None,
) -> tuple[str, dict]:
    """Invoke ``claude -p`` and return ``(final_text, usage)``.

    Two operating modes:

    1) **MCP-direct** (preferred for tool-using agent work) — when
       ``mcp_config`` is supplied, claude is started with
       ``--mcp-config <tmpfile> --strict-mcp-config --allowedTools "mcp__..."
       --permission-mode acceptEdits --output-format stream-json
       --debug-file <cwd>/claude_debug.log``. Claude runs its own tool loop
       calling ONLY the supplied MCP servers (no native Bash / Write / Edit),
       and the shim parses the stream-json into ``<cwd>/tool_calls.jsonl`` so
       the per-turn trace is preserved next to the artifacts the agent
       writes. This replaces the legacy text-catalog protocol for callers
       that own MCP servers (i.e. ari-core via LLMClient.mcp_client).

    2) **Plain** — no ``mcp_config``. claude is started with
       ``--allowedTools ""`` (no native tools, no MCP), used for non-tool
       phases like select / judge / expand.
    """
    mcp_json_file: str | None = None
    use_mcp = bool(mcp_config and allowed_mcp_tools)
    credential_values: tuple[str, ...] = ()
    if use_mcp:
        credential_values = _mcp_credential_values(mcp_config)
    debug_log = (
        os.devnull
        if credential_values
        else os.path.join(cwd, "claude_debug.log") if use_mcp else None
    )
    # Delegated CLIs expose MCP tools under qualified names while ARI prompts
    # use their manifest names. Publish the mechanically derived mapping only
    # for delegated calls; plain prompts remain byte-identical.
    effective_system = (system or "") + (
        mcp_name_resolution_note(allowed_mcp_tools) if use_mcp else ""
    )
    if use_mcp:
        # Credential values are materialized only inside the local shim and the
        # temporary file exists only while Claude is running.
        assert mcp_config is not None
        mcp_json_file = _write_claude_mcp_config(mcp_config, cwd)
    cmd = _build_claude_command(
        system=effective_system,
        agent=agent,
        real_model=real_model,
        use_mcp=use_mcp,
        mcp_json_file=mcp_json_file,
        allowed_mcp_tools=allowed_mcp_tools,
        debug_log=debug_log,
    )
    try:
        try:
            proc = _run(cmd, prompt, cwd)
        except subprocess.TimeoutExpired as exc:
            exc.stdout = _redact_mcp_credential_values(exc.stdout, credential_values)
            exc.stderr = _redact_mcp_credential_values(exc.stderr, credential_values)
            raise
    finally:
        if mcp_json_file:
            try:
                os.unlink(mcp_json_file)
            except OSError:
                pass
    proc.stdout = _redact_mcp_credential_values(proc.stdout, credential_values)
    proc.stderr = _redact_mcp_credential_values(proc.stderr, credential_values)
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude exited {proc.returncode}: {(proc.stderr or proc.stdout)[:500]}"
        )

    if use_mcp:
        # stream-json: one JSON object per line; the final ``result`` event
        # carries the assistant's final text + usage + cost. Persist every
        # event to <cwd>/tool_calls.jsonl for post-hoc audit.
        return _parse_claude_stream_json(proc.stdout, cwd)

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"claude returned non-JSON output: {proc.stdout[:500]}") from e
    if data.get("is_error"):
        raise RuntimeError(f"claude reported error: {data.get('result', '')[:500]}")
    text = data.get("result", "") or ""
    u = data.get("usage", {}) or {}
    prompt_tokens = (
        int(u.get("input_tokens", 0) or 0)
        + int(u.get("cache_creation_input_tokens", 0) or 0)
        + int(u.get("cache_read_input_tokens", 0) or 0)
    )
    completion_tokens = int(u.get("output_tokens", 0) or 0)
    # claude -p reports the actual subscription / API cost for the call at the
    # top level; surface it as a non-standard ``cost_usd`` field on the usage
    # block so ari.cost_tracker can record real dollars (litellm's pricing
    # table has no entry for the synthetic "claude-cli" model).
    cost_usd = float(data.get("total_cost_usd", 0.0) or 0.0)
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "cost_usd": cost_usd,
    }
    return text, usage


def _parse_claude_stream_json(stdout: str, cwd: str) -> tuple[str, dict]:
    """Parse claude's ``--output-format stream-json`` stdout.

    Behaviour:
      - Every event is appended verbatim to ``<cwd>/tool_calls.jsonl`` for
        post-hoc audit (one JSON object per line, claude's native schema).
      - The trailing ``{"type": "result", ...}`` event carries the final
        assistant text + token / cost usage; we return those.
      - If no result event is present (e.g. claude crashed mid-stream), the
        last assistant text seen is returned with zero usage.
    """
    text = ""
    usage = {
        "prompt_tokens": 0, "completion_tokens": 0,
        "total_tokens": 0, "cost_usd": 0.0,
    }
    audit_path = os.path.join(cwd, "tool_calls.jsonl")
    # Open append so multi-turn runs (resume) accumulate rather than truncate.
    audit_fh = open(audit_path, "a", encoding="utf-8")
    try:
        for line in (stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                # Pass through non-JSON garbage so a stderr/stdout race is
                # still inspectable in the audit file.
                audit_fh.write(line + "\n")
                continue
            audit_fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
            if ev.get("type") == "result":
                text = ev.get("result", "") or text
                u = ev.get("usage", {}) or {}
                prompt_tokens = (
                    int(u.get("input_tokens", 0) or 0)
                    + int(u.get("cache_creation_input_tokens", 0) or 0)
                    + int(u.get("cache_read_input_tokens", 0) or 0)
                )
                usage = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": int(u.get("output_tokens", 0) or 0),
                    "total_tokens": (
                        prompt_tokens + int(u.get("output_tokens", 0) or 0)
                    ),
                    "cost_usd": float(ev.get("total_cost_usd", 0.0) or 0.0),
                }
            elif ev.get("type") == "assistant":
                # Capture the latest assistant text as a fallback if the
                # result event is missing.
                msg = ev.get("message") or {}
                for block in msg.get("content", []) or []:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", text) or text
    finally:
        audit_fh.close()
    return text, usage


def _codex_text_from_stdout(stdout: str) -> str:
    """Recover the latest assistant text from codex's ``--json`` JSONL stream.

    The mirror of the claude path's stdout fallback: used only when the
    ``-o last_msg_file`` output cannot be read, so a lost file does not become
    an indistinguishable empty reply.
    """
    text = ""
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if not isinstance(ev, dict):
            continue
        # Older codex builds nested assistant output below ``msg``; current
        # JSONL uses ``item.completed`` with an ``item`` object.  Inspect both
        # envelopes (and the event itself) so an otherwise successful turn
        # cannot degrade to HTTP 200 + content:null when ``-o`` is empty.
        carriers = [ev]
        carriers.extend(
            value
            for key in ("msg", "item")
            if isinstance((value := ev.get(key)), dict)
        )
        for carrier in carriers:
            for key in ("last_agent_message", "message", "text"):
                val = carrier.get(key)
                if isinstance(val, str) and val.strip():
                    text = val.strip()
                elif isinstance(val, dict):
                    for block in (val.get("content") or []):
                        if (
                            isinstance(block, dict)
                            and isinstance(block.get("text"), str)
                        ):
                            text = block["text"].strip() or text
    return text


def _codex_error_from_stdout(stdout: str) -> str:
    """Extract the actionable failure from a Codex JSONL event stream.

    Recent Codex versions write the generic progress line ``Reading additional
    input from stdin...`` to stderr even when the real failure (for example an
    exhausted account quota) is present in the JSONL stdout.  Preferring stderr
    therefore hid the only diagnostic that could distinguish an ARI bug from
    an external service limit.
    """

    errors: list[str] = []
    for line in (stdout or "").splitlines():
        try:
            event = json.loads(line)
        except Exception:
            continue
        if not isinstance(event, dict):
            continue
        value = None
        if event.get("type") == "error":
            value = event.get("message") or event.get("error")
        elif event.get("type") == "turn.failed":
            value = event.get("error")
        if isinstance(value, dict):
            value = value.get("message") or value.get("error")
        if isinstance(value, str) and value.strip() and value.strip() not in errors:
            errors.append(value.strip())
    return errors[-1][:2_000] if errors else ""


#: A TOML bare key (unquoted): letters, digits, ``-``, ``_``. codex's ``-c``
#: dotted-path parser splits the KEY on every ``.`` even inside quotes and does
#: not register a quoted server segment as a live server, so a server name must
#: be a bare key — anything else (a dot, a space, a quote) cannot be attached.
_TOML_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_basic_string(s) -> str:
    """A TOML basic string for a scalar VALUE (command / arg / env / tool name).

    ``ensure_ascii=False`` so the raw UTF-8 character is emitted, NOT a
    ``\\uXXXX`` escape: json's ASCII escaping turns an astral code point (> U+FFFF
    — CJK Ext-B like 𩸽/𠮷, mathematical alphanumerics) into a UTF-16 SURROGATE
    PAIR (``\\ud83d\\ude00``), which TOML rejects (surrogates are not scalar
    values) and codex then refuses the ENTIRE config. Raw UTF-8 is a valid TOML
    basic string; json still escapes ``"``, ``\\`` and control chars exactly as
    TOML requires."""
    return json.dumps(str(s), ensure_ascii=False)


def _toml_string_array(items) -> str:
    """A TOML array of basic strings (args / enabled_tools)."""
    return "[" + ", ".join(_toml_basic_string(x) for x in items) + "]"


def _toml_inline_table(d: dict) -> str:
    """A TOML inline table of string→string (an MCP server's env). Unlike JSON
    (``{"k": "v"}``) TOML wants ``{ "k" = "v" }`` — keys are quoted basic
    strings, so a key/value with special chars is still encoded safely."""
    body = ", ".join(
        f"{_toml_basic_string(k)} = {_toml_basic_string(v)}" for k, v in d.items()
    )
    return "{" + body + "}"


def _codex_mcp_overrides(
    mcp_config: dict | None, allowed_mcp_tools: list[str] | None
) -> list[str]:
    """Translate the shim's engine-neutral MCP payload — the SAME
    ``{"mcpServers": {name: {command,args,env}}}`` dict + ``mcp__server__tool``
    allowlist the claude path consumes — into codex ``-c mcp_servers.*``
    overrides, the direct analogue of claude's ``--mcp-config`` +
    ``--allowedTools``:

      - each server → ``mcp_servers.<name>.{command,args,env}`` (BARE key)
      - its per-server tool allowlist → ``mcp_servers.<name>.enabled_tools``,
        so a memory server stripped of its CoW-guarded write tools (via
        ``disabled_tools``) — or omitted from ``mcpServers`` entirely (via
        ``phase: none``) — is honored EXACTLY as claude honors the filtered
        ``--allowedTools`` / absent ``--mcp-config`` entry. This is how "detach
        memory" and "detach MCP" reach codex.

    A server with zero reachable tools is skipped (codex would otherwise spawn a
    process exposing nothing). A server whose NAME is not a TOML bare key
    (a dot/space/quote — none of ARI's skill names) is skipped with a warning
    rather than silently corrupting the whole ``-c`` config, which would drop
    ALL servers. Returns a flat ``["-c", "k=v", …]`` argv fragment; empty when
    there is nothing to attach.
    """
    servers = (mcp_config or {}).get("mcpServers") or {}
    out: list[str] = []
    for name, spec in servers.items():
        prefix = f"mcp__{name}__"
        tools = [
            t[len(prefix):]
            for t in (allowed_mcp_tools or [])
            if isinstance(t, str) and t.startswith(prefix)
        ]
        if not tools:
            continue
        if not _TOML_BARE_KEY.match(str(name)):
            # codex splits the dotted -c key on interior '.' even inside quotes
            # and won't register a quoted segment as a live server, so a name
            # like "a.b" would corrupt the WHOLE config. Fail loud, skip one.
            log.warning("codex MCP: skipping server %r — name is not a TOML bare "
                        "key ([A-Za-z0-9_-]); its tools are unavailable", name)
            continue
        key = f"mcp_servers.{name}"
        out += ["-c", f"{key}.command={_toml_basic_string(spec.get('command', ''))}"]
        if spec.get("args"):
            out += ["-c", f"{key}.args={_toml_string_array(spec['args'])}"]
        if spec.get("env"):
            out += ["-c", f"{key}.env={_toml_inline_table(spec['env'])}"]
        out += ["-c", f"{key}.enabled_tools={_toml_string_array(tools)}"]
    return out


def _append_codex_audit(stdout: str, cwd: str) -> None:
    """Persist codex's ``--json`` JSONL event stream to ``<cwd>/tool_calls.jsonl``
    for post-hoc audit, mirroring the claude MCP path. Best-effort; each line is
    already a JSON object, so it is passed through verbatim (append, so a resume
    accumulates rather than truncates)."""
    audit_path = os.path.join(cwd, "tool_calls.jsonl")
    try:
        with open(audit_path, "a", encoding="utf-8") as fh:
            for line in (stdout or "").splitlines():
                line = line.strip()
                if line:
                    fh.write(line + "\n")
    except OSError:
        log.warning("codex audit write to %s failed", audit_path, exc_info=True)


def run_codex(
    system: str, prompt: str, agent: bool, real_model: str | None, cwd: str,
    *,
    mcp_config: dict | None = None,
    allowed_mcp_tools: list[str] | None = None,
    image_paths: list[str] | None = None,
    text_catalog: bool = False,
    text_catalog_output_schema: dict | None = None,
) -> tuple[str, dict]:
    """Invoke ``codex exec`` and return ``(final_text, usage)``.

    Two operating modes, symmetric with :func:`run_claude`:

    1) **MCP-direct** — when ``mcp_config`` + ``allowed_mcp_tools`` are supplied,
       codex is started with ``--ignore-user-config`` (its analogue of claude's
       ``--strict-mcp-config``: the user's ``~/.codex/config.toml`` mcp_servers
       and curated plugins are NOT loaded, so only the servers we pass are live;
       auth still resolves from ``CODEX_HOME``) plus ``-c mcp_servers.*``
       overrides for each server and its ``enabled_tools`` allowlist. Codex runs
       its own tool loop against ONLY those tools, and the ``--json`` event
       stream is persisted to ``<cwd>/tool_calls.jsonl``. Detaching MCP (no
       config) or memory (server/tool filtered out upstream) is honored here.

    2) **Plain** — no ``mcp_config``: read-only sandbox for non-agent phases,
       full bypass for agent delegation, and NO ``-c mcp_servers`` overrides.
       When ``text_catalog`` is true, a version-matched model catalog disables
       codex's native shell and patch tools.  For required calls,
       ``text_catalog_output_schema`` additionally constrains final output to
       ARI's JSON adapter schema, so the caller executes its own functions in
       the intended workspace.
       ``--ignore-user-config`` is still passed (see below), so a plain codex
       call also boots zero ambient MCP servers — full MCP detach, matching
       claude's unconditional ``--strict-mcp-config``.

    ``--ignore-user-config`` is UNCONDITIONAL for both modes; ARI drives the
    model through the shim model alias, not the user's codex config default.
    """
    use_mcp = bool(mcp_config and allowed_mcp_tools)
    full_prompt = f"{system}\n\n{prompt}".strip() if system else prompt
    output_schema_file = None
    text_catalog_model_catalog = None
    if text_catalog:
        text_catalog_model_catalog = _codex_text_catalog_model_catalog()
    if text_catalog_output_schema:
        with tempfile.NamedTemporaryFile(
            "w+", suffix=".schema.json", dir=cwd, delete=False,
            encoding="utf-8",
        ) as schema_fh:
            json.dump(
                text_catalog_output_schema,
                schema_fh,
                ensure_ascii=False,
                sort_keys=True,
            )
            schema_fh.write("\n")
            output_schema_file = schema_fh.name
    with tempfile.NamedTemporaryFile(
        "w+", suffix=".txt", dir=cwd, delete=False
    ) as fh:
        last_msg_file = fh.name
    cmd = [
        CODEX_BIN, "exec",
        "--skip-git-repo-check",
        "--json",
        "-o", last_msg_file,
    ]
    # Strict isolation, UNCONDITIONAL — the codex analogue of claude's
    # unconditional --strict-mcp-config. Never load the user's
    # ~/.codex/config.toml, so no ambient MCP server OR curated plugin
    # (github / calendar / …) leaks into ANY ARI call, plain or MCP-direct — the
    # same guarantee claude gives in text mode. Detaching MCP entirely is then
    # honored identically: no mcp_config -> no -c overrides -> codex has zero
    # MCP servers. Auth still resolves from CODEX_HOME (per `codex exec --help`);
    # ARI owns the model via the alias -> -m, so not inheriting the user's model
    # default is correct, not a regression.
    cmd.append("--ignore-user-config")
    # Disable codex's bundled curated apps (GitHub / Google Calendar / Sites /
    # …). They are installed WITH the codex binary — neither --ignore-user-config
    # nor a clean CODEX_HOME removes them — so without this an ARI agent would
    # have ~129 ambient external tools (a hermeticity AND safety hole: an
    # autonomous run could create calendar events or push to GitHub), the exact
    # contamination claude's mcp__* allowlist forbids. It also cuts per-call
    # input tokens ~5x (their schemas are otherwise injected every turn).
    cmd += ["-c", "features.apps=false"]
    if text_catalog:
        # This request carries caller-owned OpenAI-style tools rendered as a
        # text catalog.  Codex's native shell has the same familiar names as
        # some catalogs (notably PaperBench's ``bash``), but runs in codex's
        # own read-only sandbox and bypasses the caller's tool loop.  Disable
        # both native shell implementations so the model can only emit our
        # JSON protocol, which ``complete`` converts back into tool_calls.
        cmd += ["-c", "features.shell_tool=false"]
        cmd += ["-c", "features.unified_exec=false"]
    if text_catalog_model_catalog:
        cmd += [
            "-c",
            "model_catalog_json=" + _toml_basic_string(text_catalog_model_catalog),
        ]
    if output_schema_file:
        cmd += ["--output-schema", output_schema_file]
    # Reasoning effort: --ignore-user-config drops the operator's default, and a
    # reasoning model at its compiled default is slow across ARI's many calls.
    if CODEX_REASONING:
        cmd += ["-c", f"model_reasoning_effort={_toml_basic_string(CODEX_REASONING)}"]
    if use_mcp:
        cmd += _codex_mcp_overrides(mcp_config, allowed_mcp_tools)
    if real_model:
        cmd += ["-m", real_model]
    for image_path in image_paths or []:
        cmd += ["--image", image_path]
    if use_mcp or agent:
        # Tool-using delegation: let the agent's tool loop run without approval
        # prompts (codex exec is non-interactive anyway). MCP tool subprocesses
        # are external to codex's sandbox regardless; this also frees native
        # workspace edits, matching claude's acceptEdits.
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        cmd += ["--sandbox", "read-only"]
    # Short prompts remain positional for compatibility with older codex
    # builds.  Large PaperBench judge prompts routinely cross Linux's
    # per-string MAX_ARG_STRLEN even when total ARG_MAX is much larger.  Modern
    # codex documents ``-`` as an explicit stdin prompt; subprocess.run closes
    # the pipe after writing, so the turn finalises normally.
    if len(full_prompt.encode("utf-8")) > _CODEX_ARG_PROMPT_MAX_BYTES:
        cmd.append("-")
        stdin_prompt = full_prompt
    else:
        cmd.append(full_prompt)
        stdin_prompt = ""
    try:
        proc = _run(cmd, stdin_prompt, cwd)
        if proc.returncode != 0:
            detail = _codex_error_from_stdout(proc.stdout)
            if not detail:
                detail = (proc.stderr or proc.stdout)[:500]
            raise RuntimeError(
                f"codex exited {proc.returncode}: {detail}"
            )
        if use_mcp:
            _append_codex_audit(proc.stdout, cwd)
        read_error = None
        try:
            with open(last_msg_file, encoding="utf-8") as f:
                text = f.read().strip()
        except OSError as exc:
            read_error = exc
            text = ""
        # ``codex exec -o`` can also leave the pre-created file empty while its
        # JSONL stream contains a completed agent_message.  Treat missing and
        # empty output identically; an empty successful envelope is never a
        # useful chat-completions response.
        if not text:
            text = _codex_text_from_stdout(proc.stdout)
            if not text:
                detail = (
                    f"unreadable ({read_error})" if read_error else "empty"
                )
                raise RuntimeError(
                    f"codex output {detail} and no assistant text in the --json "
                    "stream; the turn produced no recoverable reply"
                ) from read_error
            log.warning(
                "codex last_msg_file %s; recovered %d chars from the --json stream",
                "unreadable" if read_error else "empty",
                len(text),
            )
    finally:
        try:
            os.unlink(last_msg_file)
        except OSError:
            pass
        if output_schema_file:
            try:
                os.unlink(output_schema_file)
            except OSError:
                pass
    # Best-effort usage from the JSONL event stream (token_count events).
    usage = _parse_codex_usage(proc.stdout)
    return text, usage


def _parse_codex_usage(stdout: str) -> dict:
    prompt_tokens = completion_tokens = 0
    cost_usd = 0.0
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Codex emits token-count info nested under varying keys across
        # versions; scan for the common ones without hard-coding a schema.
        info = ev.get("info") if isinstance(ev.get("info"), dict) else ev
        tu = info.get("token_usage") or info.get("usage") or {}
        if isinstance(tu, dict):
            prompt_tokens = int(tu.get("input_tokens", prompt_tokens) or prompt_tokens)
            completion_tokens = int(
                tu.get("output_tokens", completion_tokens) or completion_tokens
            )
        # Forward-compatible: pick up cost if a future codex version reports it.
        for key in ("total_cost_usd", "cost_usd"):
            for src in (ev, info):
                if isinstance(src, dict) and src.get(key) is not None:
                    try:
                        cost_usd = float(src[key])
                    except (TypeError, ValueError):
                        pass
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "cost_usd": cost_usd,
    }


def complete(
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice=None,
    *,
    mcp_config: dict | None = None,
    allowed_mcp_tools: list[str] | None = None,
    work_dir: str | None = None,
) -> tuple[str, list[dict] | None, dict]:
    """Run the selected CLI and return ``(text, tool_calls, usage)``.

    Tool plumbing has two paths:

    - **MCP-direct** (when ``mcp_config`` + ``allowed_mcp_tools`` are
      supplied, either engine): the CLI spawns the supplied MCP servers
      itself and runs its own internal tool loop — claude via ``--mcp-config``
      + ``--strict-mcp-config`` + ``--allowedTools``, codex via
      ``--ignore-user-config`` + ``-c mcp_servers.*`` + per-server
      ``enabled_tools``. The text-catalog hack is bypassed entirely; the final
      assistant text is returned, and any ``emit_results``-style tool call the
      caller still wants is expected to come through MCP (not parsed from text).

    - **Text-catalog** (legacy, for callers that don't own MCP servers, either
      engine without ``mcp_config``): tool catalog + JSON protocol are injected
      into the system prompt and the CLI's text reply is parsed back into
      OpenAI ``tool_calls`` — making the shim drive ARI's ReAct loop
      exactly like a real OpenAI / Anthropic backend.

    ``tool_choice == "none"`` disables tool calling (plain text reply).

    When ``work_dir`` is supplied it is used as the subprocess cwd (and is
    NOT rmtree'd on exit), so the agent's debug log / artifacts land in the
    caller's node directory. Without it, behaviour is preserved: ``SHIM_CWD``
    is used if set, else a throwaway temp dir that is removed on completion.
    """
    engine, agent, real_model = parse_model(model)
    system, prompt = render_prompt(messages)
    image_payloads = _message_image_payloads(messages)
    if image_payloads and engine != "codex":
        raise ShimError(
            "multimodal requests require codex-cli; claude-cli image "
            "attachment forwarding is not implemented"
        )

    use_mcp = bool(mcp_config and allowed_mcp_tools and engine in ("claude", "codex"))
    # text-catalog still applies for: (a) either engine WITHOUT mcp_config,
    # (b) the legacy plain claude-cli mode when caller has tools but no MCP
    # wiring. An -agent model without mcp_config keeps existing behaviour (runs
    # its OWN bash/edit — preserved for back-compat).
    use_text_catalog = (
        bool(tools) and not agent and not use_mcp and tool_choice != "none"
    )
    codex_required_tool_names: list[str] = []
    codex_output_schema: dict | None = None
    if use_text_catalog:
        forced_name = None
        if isinstance(tool_choice, dict):
            forced_name = (tool_choice.get("function") or {}).get("name")
        codex_requires_schema = engine == "codex" and (
            tool_choice == "required" or forced_name is not None
        )
        if codex_requires_schema:
            if forced_name:
                codex_required_tool_names = [str(forced_name)]
            else:
                for tool in tools or []:
                    fn = tool.get("function", tool) if isinstance(tool, dict) else {}
                    name = fn.get("name") if isinstance(fn, dict) else None
                    if name:
                        codex_required_tool_names.append(str(name))
            if not codex_required_tool_names:
                raise ShimError("required tool choice has no named tools")
            codex_output_schema = _codex_required_tool_schema(
                tools or [], codex_required_tool_names
            )
        catalog = _render_tool_catalog(tools)
        instr = _tool_protocol_instructions(tool_choice)
        tool_block = f"{catalog}\n\n{instr}"
        system = f"{system}\n\n{tool_block}".strip() if system else tool_block

    if not prompt and not system:
        raise ShimError("no prompt content in messages")

    # Resolve the working directory. Priority: explicit per-request work_dir
    # > server-wide SHIM_CWD > throwaway tmp dir. Per-request cwd is NOT
    # cleaned up — its whole point is to persist agent artifacts.
    tmp_cwd = None
    cwd = work_dir or SHIM_CWD
    if not cwd:
        tmp_cwd = tempfile.mkdtemp(prefix="ari-cli-shim-")
        cwd = tmp_cwd
    else:
        os.makedirs(cwd, exist_ok=True)
        if use_mcp:
            log.info(
                "shim MCP-direct engine=%s cwd=%s tools=%d (audit=%s/tool_calls.jsonl)",
                engine, cwd, len(allowed_mcp_tools or []), cwd,
            )
    image_paths = _materialize_codex_images(image_payloads, cwd)
    with _slots:
        try:
            if engine == "claude":
                text, usage = run_claude(
                    system, prompt, agent, real_model, cwd,
                    mcp_config=mcp_config if use_mcp else None,
                    allowed_mcp_tools=allowed_mcp_tools if use_mcp else None,
                )
            else:
                codex_kwargs = {
                    "mcp_config": mcp_config if use_mcp else None,
                    "allowed_mcp_tools": allowed_mcp_tools if use_mcp else None,
                }
                if image_paths:
                    codex_kwargs["image_paths"] = image_paths
                if use_text_catalog:
                    codex_kwargs["text_catalog"] = True
                if codex_output_schema:
                    codex_kwargs["text_catalog_output_schema"] = (
                        codex_output_schema
                    )
                text, usage = run_codex(
                    system, prompt, agent, real_model, cwd,
                    **codex_kwargs,
                )
        finally:
            for image_path in image_paths:
                try:
                    os.unlink(image_path)
                except OSError:
                    pass
            if tmp_cwd:
                # Throwaway dir only — caller didn't pin work_dir.
                import shutil
                shutil.rmtree(tmp_cwd, ignore_errors=True)

    tool_calls = None
    if use_text_catalog:
        tool_calls, residual = extract_tool_calls(text, tools=tools)
        if tool_calls is not None:
            text = residual  # OpenAI sends content=null alongside tool_calls
    # MCP-direct: claude's internal loop handles tool calls itself; the
    # outer caller sees only the final text. tool_calls stays None.
    return text, tool_calls, usage


# ──────────────────────────────────────────────────────────────────────────
# OpenAI response envelopes
# ──────────────────────────────────────────────────────────────────────────
def _completion_envelope(
    model: str, text: str, usage: dict, tool_calls: list[dict] | None = None
) -> dict:
    message: dict = {"role": "assistant", "content": text or None}
    finish = "stop"
    if tool_calls:
        message["tool_calls"] = tool_calls
        message["content"] = text or None
        finish = "tool_calls"
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish,
            }
        ],
        "usage": usage,
    }


def _chunk(model: str, cid: str, delta: dict, finish: str | None) -> str:
    obj = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(obj)}\n\n"


VIRTUAL_MODELS = ["claude-cli", "claude-cli-agent", "codex-cli", "codex-cli-agent"]


# ──────────────────────────────────────────────────────────────────────────
# HTTP handler
# ──────────────────────────────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    server_version = "ARICliShim/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # quieter access log
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, code: int, message: str, etype: str = "invalid_request_error") -> None:
        self._send_json(code, {"error": {"message": message, "type": etype}})

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._send_json(200, {"status": "ok"})
            return
        if path in ("/v1/models", "/models"):
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": m, "object": "model", "owned_by": "ari-cli-shim"}
                        for m in VIRTUAL_MODELS
                    ],
                },
            )
            return
        self._send_error(404, f"not found: {path}", "not_found")

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path not in ("/v1/chat/completions", "/chat/completions"):
            self._send_error(404, f"not found: {path}", "not_found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b""
            req = json.loads(raw or b"{}")
        except (ValueError, json.JSONDecodeError) as e:
            self._send_error(400, f"invalid request body: {e}")
            return

        model = req.get("model", "")
        messages = req.get("messages", [])
        tools = req.get("tools")
        tool_choice = req.get("tool_choice")
        stream = bool(req.get("stream", False))
        # litellm's openai-compatible handler passes ``extra_body`` fields as
        # top-level keys on the request body. Accept either form so other
        # clients that DO nest under ``extra_body`` also work.
        eb = req.get("extra_body") or {}
        mcp_config = req.get("mcp_config") or eb.get("mcp_config")
        allowed_mcp_tools = (
            req.get("allowed_mcp_tools") or eb.get("allowed_mcp_tools")
        )
        work_dir = req.get("work_dir") or eb.get("work_dir")

        try:
            text, tool_calls, usage = complete(
                model, messages, tools, tool_choice,
                mcp_config=mcp_config,
                allowed_mcp_tools=allowed_mcp_tools,
                work_dir=work_dir,
            )
        except ShimError as e:
            self._send_error(400, str(e))
            return
        except subprocess.TimeoutExpired:
            self._send_error(504, f"CLI timed out after {TIMEOUT}s", "timeout")
            return
        except Exception as e:  # noqa: BLE001 — surface CLI failures as 502
            log.exception("shim completion failed")
            self._send_error(502, f"CLI backend error: {e}", "api_error")
            return

        if not stream:
            self._send_json(
                200, _completion_envelope(model, text, usage, tool_calls)
            )
            return

        # Single-chunk SSE: clients that require stream=true still work; we
        # don't get token-level streaming from the JSON output format.
        cid = f"chatcmpl-{uuid.uuid4().hex}"
        if tool_calls:
            # OpenAI streams tool_calls as deltas carrying an ``index``.
            first_delta: dict = {
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {
                        "index": i,
                        "id": tc["id"],
                        "type": tc["type"],
                        "function": tc["function"],
                    }
                    for i, tc in enumerate(tool_calls)
                ],
            }
            finish = "tool_calls"
        else:
            first_delta = {"role": "assistant", "content": text}
            finish = "stop"
        # SSE body has no Content-Length; under HTTP/1.1 the client would
        # block waiting for more data. Delimit the body by EOF: close the
        # connection after the final event.
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for piece in (
            _chunk(model, cid, first_delta, None),
            _chunk(model, cid, {}, finish),
            "data: [DONE]\n\n",
        ):
            self.wfile.write(piece.encode("utf-8"))
        self.wfile.flush()


class _DualStackServer(ThreadingHTTPServer):
    """IPv6 socket that also accepts IPv4 (mirrors ari.viz.server)."""

    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self) -> None:
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        super().server_bind()


def _warn_claude_env_contamination(environ=None) -> None:
    """Warn (non-fatal) when the shim inherits a Claude Code session env.

    ``CLAUDECODE`` / ``CLAUDE_CODE_*`` in the environment mean the shim was
    started from inside a claude session; the nested ``claude`` subprocesses
    then link back to the parent session (observed: ambient project MCP
    servers booting per call before --strict-mcp-config, session cross-talk).
    Never auto-sanitizes — auth setups vary — only recommends the recipe.
    """
    env = os.environ if environ is None else environ
    hits = sorted(
        k for k in env if k == "CLAUDECODE" or k.startswith("CLAUDE_CODE_")
    )
    if hits:
        log.warning(
            "Claude Code session variables inherited from the parent process: "
            "%s. The nested claude CLI may link back to that session. "
            "Recommended: launch the shim with a sanitized environment, e.g. "
            "`env -i HOME=\"$HOME\" PATH=\"$PATH\" python -m ari.llm.cli_server`.",
            ", ".join(hits),
        )


def serve(port: int = DEFAULT_PORT) -> None:
    logging.basicConfig(
        level=os.environ.get("ARI_CLI_SHIM_LOG", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _warn_claude_env_contamination()
    srv = _DualStackServer(("", port), _Handler)
    log.info(
        "ARI CLI shim listening on http://localhost:%d/v1  "
        "(models: %s; concurrency=%d; claude_bare=%s)",
        port, ", ".join(VIRTUAL_MODELS), MAX_CONCURRENCY, CLAUDE_BARE,
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def main() -> None:
    ap = argparse.ArgumentParser(description="OpenAI-compatible shim for claude/codex CLIs")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()
    serve(args.port)


if __name__ == "__main__":
    main()
