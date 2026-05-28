from __future__ import annotations
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
"""

import argparse
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
# Pass `claude --bare`: minimal mode (no CLAUDE.md/hooks/auto-memory). Strongly
# cuts the per-call input-token overhead but forces ANTHROPIC_API_KEY auth.
CLAUDE_BARE = os.environ.get("ARI_CLI_SHIM_CLAUDE_BARE", "0") == "1"
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
    """Collapse an OpenAI message ``content`` (str or content-parts) to text."""
    if isinstance(content, list):
        return "".join(
            p.get("text", "") for p in content if isinstance(p, dict)
        )
    return str(content or "")


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


def extract_tool_calls(text: str) -> tuple[list[dict] | None, str]:
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
            return calls, ""
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
    debug_log = os.path.join(cwd, "claude_debug.log") if use_mcp else None

    if use_mcp:
        cmd = [CLAUDE_BIN, "-p", "--output-format", "stream-json", "--verbose"]
    else:
        cmd = [CLAUDE_BIN, "-p", "--output-format", "json"]
    if CLAUDE_BARE:
        cmd.append("--bare")
    if real_model:
        cmd += ["--model", real_model]
    if system:
        cmd += ["--system-prompt", system]
    if use_mcp:
        # Materialise the MCP server config as a tmp JSON file in cwd so it
        # survives for post-mortem inspection alongside tool_calls.jsonl.
        fh = tempfile.NamedTemporaryFile(
            "w", suffix=".mcp.json", dir=cwd, delete=False, encoding="utf-8",
        )
        try:
            json.dump(mcp_config, fh)
        finally:
            fh.close()
        mcp_json_file = fh.name
        cmd += [
            "--mcp-config", mcp_json_file,
            "--strict-mcp-config",
            "--allowedTools", " ".join(allowed_mcp_tools or []),
            "--permission-mode", CLAUDE_AGENT_PERMISSION,
            "--debug-file", debug_log,
        ]
    elif agent:
        cmd += ["--permission-mode", CLAUDE_AGENT_PERMISSION]
    else:
        # No tools => pure text/JSON generation.
        cmd += ["--allowedTools", ""]
    if MAX_BUDGET_USD:
        cmd += ["--max-budget-usd", MAX_BUDGET_USD]
    proc = _run(cmd, prompt, cwd)
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


def run_codex(
    system: str, prompt: str, agent: bool, real_model: str | None, cwd: str
) -> tuple[str, dict]:
    full_prompt = f"{system}\n\n{prompt}".strip() if system else prompt
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
    if real_model:
        cmd += ["-m", real_model]
    if agent:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        cmd += ["--sandbox", "read-only"]
    # Pass the prompt as a positional argument, NOT on stdin: `codex exec`
    # reading from stdin hangs after the turn starts (it keeps the stream open
    # waiting for more input and never finalises the turn), whereas an argv
    # prompt runs to completion. Very large prompts (>~ARG_MAX) are the only
    # caveat; codex task prompts are well under that.
    cmd.append(full_prompt)
    try:
        proc = _run(cmd, "", cwd)
        if proc.returncode != 0:
            raise RuntimeError(
                f"codex exited {proc.returncode}: {(proc.stderr or proc.stdout)[:500]}"
            )
        try:
            with open(last_msg_file, encoding="utf-8") as f:
                text = f.read().strip()
        except OSError:
            text = ""
    finally:
        try:
            os.unlink(last_msg_file)
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
      supplied, claude engine only): claude spawns the supplied MCP servers
      itself and runs its own internal tool loop. The text-catalog hack is
      bypassed entirely; the final assistant text is returned, and any
      ``emit_results``-style tool call the caller still wants is expected
      to come through MCP (not parsed out of text).

    - **Text-catalog** (legacy, retained for codex and for callers that
      don't own MCP servers): tool catalog + JSON protocol are injected
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

    use_mcp = bool(mcp_config and allowed_mcp_tools and engine == "claude")
    # text-catalog still applies for: (a) codex engine, (b) claude without
    # mcp_config, (c) the legacy plain claude-cli mode when caller has tools
    # but no MCP wiring. claude-cli-agent without mcp_config keeps existing
    # behaviour (runs its OWN bash/edit — preserved for back-compat).
    use_text_catalog = (
        bool(tools) and not agent and not use_mcp and tool_choice != "none"
    )
    if use_text_catalog:
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
                "shim MCP-direct cwd=%s tools=%d debug=%s/claude_debug.log",
                cwd, len(allowed_mcp_tools or []), cwd,
            )
    with _slots:
        try:
            if engine == "claude":
                text, usage = run_claude(
                    system, prompt, agent, real_model, cwd,
                    mcp_config=mcp_config if use_mcp else None,
                    allowed_mcp_tools=allowed_mcp_tools if use_mcp else None,
                )
            else:
                text, usage = run_codex(system, prompt, agent, real_model, cwd)
        finally:
            if tmp_cwd:
                # Throwaway dir only — caller didn't pin work_dir.
                import shutil
                shutil.rmtree(tmp_cwd, ignore_errors=True)

    tool_calls = None
    if use_text_catalog:
        tool_calls, residual = extract_tool_calls(text)
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


def serve(port: int = DEFAULT_PORT) -> None:
    logging.basicConfig(
        level=os.environ.get("ARI_CLI_SHIM_LOG", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
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
