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


def _load_spec(raw: str) -> tuple[str, list[str], list[str], dict[str, str]]:
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
    return command, args, env_names, markers


def _copy_input(source: BinaryIO, target: BinaryIO) -> None:
    try:
        while chunk := source.read(64 * 1024):
            target.write(chunk)
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
) -> None:
    try:
        while chunk := source.readline():
            target.write(redactor.apply(chunk))
            target.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass


def run_proxy(raw_spec: str) -> int:
    command, args, env_names, markers = _load_spec(raw_spec)
    environment = {
        name: os.environ[name]
        for name in env_names
        if name in os.environ
    }
    environment.setdefault("PATH", os.defpath)
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
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_copy_redacted,
        args=(process.stderr, sys.stderr.buffer, redactor),
        daemon=True,
    )
    input_thread.start()
    stderr_thread.start()
    _copy_redacted(process.stdout, sys.stdout.buffer, redactor)
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


if __name__ == "__main__":
    raise SystemExit(main())
