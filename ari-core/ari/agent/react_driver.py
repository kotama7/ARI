"""Generic ReAct loop driver, decoupled from BFTS Node concepts.

Used by pipeline.py for stages declaring a ``react:`` block. Drives an
LLM in a Thought→Action→Observation loop using MCP tools filtered by
phase. Terminates when the agent calls a designated ``final_tool`` or
when ``max_steps`` is exhausted.

Sandbox enforcement: when ``sandbox`` is provided, the driver rejects
tool calls whose arguments reference absolute paths outside the
sandbox directory. This is a defense-in-depth check; the underlying
skill (e.g. coding-skill ``run_bash``) should also constrain its own
working directory.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from ari.llm.client import LLMClient
from ari.mcp.client import MCPClient

log = logging.getLogger(__name__)

_MAX_TOOL_OUTPUT = 4000


def _truncate(text: str, limit: int = _MAX_TOOL_OUTPUT) -> str:
    if not text or len(text) <= limit:
        return text
    half = limit // 2
    return (
        text[:half]
        + f"\n\n... [{len(text) - limit} chars truncated] ...\n\n"
        + text[-half:]
    )


def _build_window(messages: list[dict], max_msgs: int = 50) -> list[dict]:
    """Trim conversation preserving system + initial user + recent pairs."""
    if len(messages) <= max_msgs:
        return list(messages)
    head = messages[:2]
    tail = list(messages[-(max_msgs - 2):])
    while tail and tail[0].get("role") == "tool":
        tail.pop(0)
    if tail and tail[0].get("role") == "assistant" and tail[0].get("tool_calls"):
        needed = {tc["id"] for tc in tail[0]["tool_calls"]}
        present = {m.get("tool_call_id") for m in tail if m.get("role") == "tool"}
        if not needed.issubset(present):
            tail.pop(0)
    return head + tail


_PATH_TOKEN_RE = re.compile(r"(?<![\w/.])(/[A-Za-z0-9._/-]+)")


def _validate_paths_in_args(
    args: Any, sandbox: Path, allow_extra: list[Path] | None = None,
) -> str | None:
    """Reject args containing absolute paths outside the sandbox.

    Scans all string values recursively. An absolute path is allowed iff it
    resolves under ``sandbox`` or any path in ``allow_extra``. Path-traversal
    sequences (``..``) are rejected outright.

    Returns an error string on violation, or ``None`` when clean.
    """
    if sandbox is None:
        return None
    sandbox_r = sandbox.resolve()
    allow = [p.resolve() for p in (allow_extra or [])]

    def _path_ok(token: str) -> bool:
        try:
            p = Path(token).expanduser().resolve()
        except Exception:
            return True  # un-resolvable strings are not paths
        if p == sandbox_r or sandbox_r in p.parents:
            return True
        for a in allow:
            if p == a or a in p.parents:
                return True
        return False

    def _scan_string(s: str) -> str | None:
        if "../" in s or s.endswith("/..") or " .. " in f" {s} ":
            return f"path-traversal pattern in: {s[:120]!r}"
        for tok in _PATH_TOKEN_RE.findall(s):
            if not _path_ok(tok):
                return f"absolute path outside sandbox: {tok}"
        return None

    def _walk(v: Any) -> str | None:
        if isinstance(v, str):
            return _scan_string(v)
        if isinstance(v, dict):
            for x in v.values():
                err = _walk(x)
                if err:
                    return err
        elif isinstance(v, list):
            for x in v:
                err = _walk(x)
                if err:
                    return err
        return None

    return _walk(args)


def _make_final_tool_def(name: str) -> dict:
    """Synthesize a generic final-tool function definition for the LLM."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": (
                "Report the final measured value. Call ONLY when you have a "
                "reliable measurement. This terminates the loop."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {"type": "number", "description": "Measured value"},
                    "unit":  {"type": "string", "description": "Unit"},
                    "notes": {"type": "string", "description": "Conditions/observations"},
                },
                "required": ["value"],
            },
        },
    }


def run_react(
    llm: LLMClient,
    mcp: MCPClient,
    *,
    system_prompt: str,
    user_prompt: str,
    agent_phase: str,
    final_tool: str,
    max_steps: int = 40,
    sandbox: Path | None = None,
    allow_paths: list[Path] | None = None,
    log_dir: Path | None = None,
) -> dict:
    """Run a ReAct loop until ``final_tool`` is called or ``max_steps`` reached.

    Returns a dict with keys:
        status:            "completed" | "max_steps" | "no_tool"
        final_args:        dict | None — args the LLM passed to final_tool
        messages:          list[dict] — full conversation log
        tool_calls_count:  int
    """
    raw_tools = mcp.list_tools(phase=agent_phase)
    tool_defs: list[dict] = [
        {
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
            },
        }
        for t in raw_tools
    ]
    tool_names = [t["function"]["name"] for t in tool_defs]
    if final_tool not in tool_names:
        tool_defs.append(_make_final_tool_def(final_tool))
        tool_names.append(final_tool)
    log.info(
        "react_driver: phase=%s, %d tools available: %s (final=%s, max_steps=%d)",
        agent_phase, len(tool_defs), tool_names, final_tool, max_steps,
    )

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]

    final_args: dict | None = None
    tool_calls_count = 0
    status = "max_steps"

    for step in range(1, max_steps + 1):
        try:
            resp = llm.complete(
                _build_window(messages), tools=tool_defs, require_tool=False,
                phase=agent_phase, skill="react_driver",
            )
        except Exception as e:
            log.error("react_driver step %d LLM error: %s", step, e)
            messages.append({
                "role": "user",
                "content": (
                    f"[System] LLM call failed ({type(e).__name__}: {e}). "
                    "Continue with available information."
                ),
            })
            continue

        content = resp.content or ""
        if "</think>" in content:
            content = content.split("</think>")[-1].strip()

        assistant_msg: dict = {"role": "assistant", "content": content}
        if resp.tool_calls:
            assistant_msg["tool_calls"] = resp.tool_calls
        messages.append(assistant_msg)

        called_names = [tc["function"]["name"] for tc in (resp.tool_calls or [])]
        log.info(
            "react_driver step %d/%d: tools=%s content_len=%d",
            step, max_steps, called_names or "(text-only)", len(content),
        )

        if not resp.tool_calls:
            if not content:
                messages.append({
                    "role": "user",
                    "content": (
                        f"[System] Empty response. Call a tool to proceed, "
                        f"or call {final_tool}() if you have a measurement."
                    ),
                })
                continue
            status = "no_tool"
            break

        for tc in resp.tool_calls:
            tool_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}

            # Sandbox enforcement (skip for the final reporting tool).
            if sandbox is not None and tool_name != final_tool:
                err = _validate_paths_in_args(args, sandbox, allow_extra=allow_paths)
                if err:
                    log.warning(
                        "react_driver sandbox violation in '%s': %s",
                        tool_name, err,
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(
                            {"error": f"sandbox violation: {err}"},
                            ensure_ascii=False,
                        ),
                    })
                    tool_calls_count += 1
                    continue

            tool_calls_count += 1

            # Final tool: capture and synthesize a confirmation, do not dispatch.
            if tool_name == final_tool:
                final_args = args
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(
                        {"ok": True, "recorded": args}, ensure_ascii=False,
                    ),
                })
                continue

            # Regular MCP dispatch.
            try:
                result = mcp.call_tool(tool_name, args)
            except Exception as e:
                result = {"error": f"{tool_name} failed: {type(e).__name__}: {e}"}
            text = json.dumps(result, ensure_ascii=False, default=str)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": _truncate(text, 5000),
            })

        if final_args is not None:
            log.info(
                "react_driver: final_tool '%s' invoked at step %d: %s",
                final_tool, step, final_args,
            )
            status = "completed"
            break

        if step == max_steps - 5 and final_args is None:
            messages.append({
                "role": "user",
                "content": (
                    f"[System] 5 steps remaining. If you already have a "
                    f"measurement, call {final_tool}() now. Otherwise run "
                    "the benchmark immediately and report the result."
                ),
            })

    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            entries = []
            for m in messages:
                e: dict = {
                    "role": m.get("role", ""),
                    "content": (m.get("content") or "")[:500],
                }
                if m.get("tool_calls"):
                    e["tool_calls"] = [
                        tc["function"]["name"] for tc in m["tool_calls"]
                    ]
                if m.get("tool_call_id"):
                    e["tool_call_id"] = m["tool_call_id"]
                entries.append(e)
            (log_dir / "react_log.json").write_text(
                json.dumps(entries, indent=2, ensure_ascii=False),
            )
        except Exception as e:
            log.warning("react_driver: failed to persist log: %s", e)

    return {
        "status":           status,
        "final_args":       final_args,
        "messages":         messages,
        "tool_calls_count": tool_calls_count,
    }
