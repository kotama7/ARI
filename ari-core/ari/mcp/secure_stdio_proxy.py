"""Value-redacting, exact-environment stdio proxy for direct MCP clients.

Claude CLI and similar clients may merge their own parent environment into an
MCP server declaration.  This proxy is the trust boundary: it launches the real
provider with exactly the environment names admitted by ARI, and removes known
credential values from provider stdout/stderr before forwarding either stream.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
from typing import BinaryIO

from ari.call_context import (
    CALL_CONTEXT_ARGUMENT,
    CONTEXT_AUTHORITY_ENV,
    ToolCallContextV1,
    authorize_tool_context,
    new_context_authority_key,
)


_ENV_NAME_RE = re.compile(r"[A-Z_][A-Z0-9_]*")


class _ByteRedactor:
    def __init__(self, markers: dict[str, str], environment: dict[str, str]) -> None:
        replacements: dict[bytes, bytes] = {}
        for name, marker in markers.items():
            secret = environment.get(name, "")
            if not secret:
                continue
            rendered = f"<redacted:{marker}>".encode("utf-8")
            replacements[secret.encode("utf-8")] = rendered
            escaped = json.dumps(secret, ensure_ascii=False)[1:-1].encode("utf-8")
            replacements[escaped] = rendered
        self._pairs = tuple(
            sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True)
        )

    def apply(self, payload: bytes) -> bytes:
        for secret, marker in self._pairs:
            payload = payload.replace(secret, marker)
        return payload


def _load_spec(
    raw: str,
) -> tuple[
    str,
    list[str],
    list[str],
    dict[str, str],
    dict[str, str],
    ToolCallContextV1 | None,
]:
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid proxy spec JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("proxy spec must be an object")
    command = document.get("command")
    args = document.get("args", [])
    env_names = document.get("env_names", [])
    markers = document.get("credential_markers", {})
    context_requirements = document.get("context_requirements", {})
    raw_context = document.get("call_context")
    if not isinstance(command, str) or not command:
        raise ValueError("proxy command must be a non-empty string")
    if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        raise ValueError("proxy args must be strings")
    if not isinstance(env_names, list) or any(
        not isinstance(name, str) or not _ENV_NAME_RE.fullmatch(name)
        for name in env_names
    ):
        raise ValueError("proxy env_names must contain canonical names")
    if len(env_names) != len(set(env_names)):
        raise ValueError("proxy env_names must be unique")
    if not isinstance(markers, dict) or any(
        name not in env_names
        or not isinstance(marker, str)
        or not marker
        for name, marker in markers.items()
    ):
        raise ValueError("proxy credential_markers must reference admitted env names")
    if not isinstance(context_requirements, dict) or any(
        not isinstance(name, str)
        or not name
        or requirement not in {"run", "node"}
        for name, requirement in context_requirements.items()
    ):
        raise ValueError("proxy context_requirements must map tools to run/node")
    context = None
    if context_requirements:
        if raw_context is None:
            raise ValueError("proxy context-requiring tools need call_context")
        try:
            context = ToolCallContextV1.model_validate(raw_context)
        except Exception as exc:
            raise ValueError("proxy call_context is malformed") from exc
        unsatisfied = sorted(
            name
            for name, requirement in context_requirements.items()
            if not context.satisfies(requirement)
        )
        if unsatisfied:
            raise ValueError(
                f"proxy call_context does not authorize tools: {unsatisfied}"
            )
    elif raw_context is not None:
        raise ValueError("proxy call_context requires context_requirements")
    return command, args, env_names, markers, context_requirements, context


def _copy_input(
    source: BinaryIO,
    target: BinaryIO,
    *,
    context_requirements: dict[str, str] | None = None,
    call_context: ToolCallContextV1 | None = None,
    authority_key: str | None = None,
) -> None:
    try:
        while chunk := source.readline():
            target.write(
                _inject_call_context(
                    chunk,
                    context_requirements=context_requirements or {},
                    call_context=call_context,
                    authority_key=authority_key,
                )
            )
            target.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            target.close()
        except (OSError, ValueError):
            pass


def _copy_redacted(
    source: BinaryIO,
    target: BinaryIO,
    redactor: _ByteRedactor,
    *,
    sanitize_tool_schemas: bool = False,
) -> None:
    try:
        while chunk := source.readline():
            if sanitize_tool_schemas:
                chunk = _strip_context_from_tool_schemas(chunk)
            target.write(redactor.apply(chunk))
            target.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass


def run_proxy(raw_spec: str) -> int:
    (
        command,
        args,
        env_names,
        markers,
        context_requirements,
        call_context,
    ) = _load_spec(raw_spec)
    environment = {
        name: os.environ[name]
        for name in env_names
        if name in os.environ
    }
    environment.setdefault("PATH", os.defpath)
    authority_key = None
    if context_requirements:
        authority_key = new_context_authority_key()
        environment[CONTEXT_AUTHORITY_ENV] = authority_key
        markers = {
            **markers,
            CONTEXT_AUTHORITY_ENV: "core.call-context-authority",
        }
    redactor = _ByteRedactor(markers, environment)

    popen_kwargs: dict[str, object] = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": environment,
        "bufsize": 0,
    }
    if os.name == "nt":  # pragma: no cover - exercised in Windows CI
        popen_kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        popen_kwargs["start_new_session"] = True
    process = subprocess.Popen([command, *args], **popen_kwargs)
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    def _terminate(_signum, _frame) -> None:
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGTERM)
            else:  # pragma: no cover - exercised in Windows CI
                process.terminate()
        except (OSError, ProcessLookupError):
            pass

    for signal_name in ("SIGTERM", "SIGINT"):
        if hasattr(signal, signal_name):
            signal.signal(getattr(signal, signal_name), _terminate)

    input_thread = threading.Thread(
        target=_copy_input,
        args=(sys.stdin.buffer, process.stdin),
        kwargs={
            "context_requirements": context_requirements,
            "call_context": call_context,
            "authority_key": authority_key,
        },
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_copy_redacted,
        args=(process.stderr, sys.stderr.buffer, redactor),
        daemon=True,
    )
    input_thread.start()
    stderr_thread.start()
    _copy_redacted(
        process.stdout,
        sys.stdout.buffer,
        redactor,
        sanitize_tool_schemas=True,
    )
    return_code = process.wait()
    stderr_thread.join(timeout=5)
    return return_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, help="value-free JSON launch spec")
    args = parser.parse_args(argv)
    try:
        return run_proxy(args.spec)
    except (OSError, ValueError) as exc:
        print(f"secure stdio proxy refused launch: {exc}", file=sys.stderr)
        return 2


def _inject_call_context(
    payload: bytes,
    *,
    context_requirements: dict[str, str],
    call_context: ToolCallContextV1 | None,
    authority_key: str | None,
) -> bytes:
    """Override any caller context with a proxy-issued capability."""

    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return payload

    def inject(message):
        if not isinstance(message, dict) or message.get("method") != "tools/call":
            return message
        params = message.get("params")
        if not isinstance(params, dict):
            return message
        tool_name = params.get("name")
        arguments = params.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        else:
            arguments = dict(arguments)
        arguments.pop(CALL_CONTEXT_ARGUMENT, None)
        requirement = context_requirements.get(str(tool_name))
        if requirement:
            if call_context is None or authority_key is None:
                return message
            arguments[CALL_CONTEXT_ARGUMENT] = authorize_tool_context(
                call_context,
                tool_name=str(tool_name),
                authority_key=authority_key,
            )
        params = dict(params)
        params["arguments"] = arguments
        message = dict(message)
        message["params"] = params
        return message

    if isinstance(document, list):
        document = [inject(message) for message in document]
    else:
        document = inject(document)
    suffix = b"\n" if payload.endswith(b"\n") else b""
    return json.dumps(
        document,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + suffix


def _strip_context_from_tool_schemas(payload: bytes) -> bytes:
    """Remove the transport-only argument from tools/list responses."""

    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return payload
    if not isinstance(document, dict):
        return payload
    result = document.get("result")
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        return payload
    changed = False
    for tool in tools:
        schema = tool.get("inputSchema") if isinstance(tool, dict) else None
        if not isinstance(schema, dict):
            continue
        properties = schema.get("properties")
        if isinstance(properties, dict) and CALL_CONTEXT_ARGUMENT in properties:
            schema["properties"] = {
                name: value
                for name, value in properties.items()
                if name != CALL_CONTEXT_ARGUMENT
            }
            changed = True
        required = schema.get("required")
        if isinstance(required, list) and CALL_CONTEXT_ARGUMENT in required:
            kept = [name for name in required if name != CALL_CONTEXT_ARGUMENT]
            if kept:
                schema["required"] = kept
            else:
                schema.pop("required", None)
            changed = True
    if not changed:
        return payload
    suffix = b"\n" if payload.endswith(b"\n") else b""
    return json.dumps(
        document,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + suffix


if __name__ == "__main__":
    raise SystemExit(main())
