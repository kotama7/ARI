"""Value-free stdio supervisor that owns the Provider process group.

The MCP SDK owns this proxy process. The proxy starts the actual Provider in a
distinct process group and reaps that complete group on every exit path. It
uses only the standard library, so the Provider environment need not install
ARI.
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
import time
from pathlib import Path
from typing import BinaryIO


_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def _load_spec(raw: str) -> tuple[str, list[str], str, list[str]]:
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise ValueError("proxy spec must be an object")
    command = document.get("command")
    arguments = document.get("arguments")
    cwd = document.get("cwd")
    env_names = document.get("env_names")
    if not isinstance(command, str) or not Path(command).is_absolute():
        raise ValueError("proxy command must be an absolute path")
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        raise ValueError("proxy cwd must be an absolute path")
    if not isinstance(arguments, list) or any(
        not isinstance(item, str) or "\x00" in item for item in arguments
    ):
        raise ValueError("proxy arguments must be NUL-free strings")
    if (
        not isinstance(env_names, list)
        or len(env_names) != len(set(env_names))
        or any(
            not isinstance(name, str) or _ENV_NAME_RE.fullmatch(name) is None
            for name in env_names
        )
    ):
        raise ValueError("proxy env_names must be unique canonical names")
    return command, arguments, cwd, env_names


def _copy(source: BinaryIO, target: BinaryIO) -> None:
    try:
        while chunk := source.readline():
            target.write(chunk)
            target.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            target.close()
        except (OSError, ValueError):
            pass


def _signal_group(process: subprocess.Popen[bytes], signum: int) -> None:
    try:
        if os.name == "nt":  # pragma: no cover - Windows CI owns this branch
            if signum == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        else:
            os.killpg(process.pid, signum)
    except (OSError, ProcessLookupError):
        pass


def _reap_group(process: subprocess.Popen[bytes]) -> int:
    """Terminate the group even when its leader exited before descendants."""

    observed = process.poll()
    _signal_group(process, signal.SIGTERM)
    deadline = time.monotonic() + 2
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    _signal_group(process, signal.SIGKILL)
    try:
        return process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        _signal_group(process, signal.SIGKILL)
        return process.wait()
    except ChildProcessError:
        return observed if observed is not None else 1


def run_proxy(raw_spec: str) -> int:
    command, arguments, cwd, env_names = _load_spec(raw_spec)
    environment = {name: os.environ[name] for name in env_names if name in os.environ}
    environment.setdefault("PATH", os.defpath)
    popen_kwargs: dict[str, object] = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "cwd": cwd,
        "env": environment,
        "bufsize": 0,
    }
    if os.name == "nt":  # pragma: no cover - Windows CI owns this branch
        popen_kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        popen_kwargs["start_new_session"] = True
    process = subprocess.Popen([command, *arguments], **popen_kwargs)
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    def terminate(_signum, _frame) -> None:
        _signal_group(process, signal.SIGTERM)

    for signal_name in ("SIGTERM", "SIGINT"):
        if hasattr(signal, signal_name):
            signal.signal(getattr(signal, signal_name), terminate)

    stdin_thread = threading.Thread(
        target=_copy,
        args=(sys.stdin.buffer, process.stdin),
        name="ari-provider-stdin",
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_copy,
        args=(process.stderr, sys.stderr.buffer),
        name="ari-provider-stderr",
        daemon=True,
    )
    stdin_thread.start()
    stderr_thread.start()
    try:
        _copy(process.stdout, sys.stdout.buffer)
    finally:
        return_code = _reap_group(process)
        stderr_thread.join(timeout=2)
    return return_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    args = parser.parse_args(argv)
    try:
        return run_proxy(args.spec)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"stdio process proxy refused launch: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
