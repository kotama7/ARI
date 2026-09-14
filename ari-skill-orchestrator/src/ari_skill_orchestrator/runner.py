"""Crash-observable wrapper for one ARI CLI process.

The wrapper is intentionally stdlib-only.  It writes an atomic receipt before
and after the child, owns child process-group cancellation, and never serializes
the inherited credential environment.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


_child: subprocess.Popen[bytes] | None = None
_cancel_requested = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _start_ticks(pid: int) -> int | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        tail = raw[raw.rfind(")") + 2 :].split()
        return int(tail[19])
    except (OSError, ValueError, IndexError):
        return None


def _atomic_receipt(path: Path, value: dict[str, object]) -> None:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    directory_fd = os.open(
        path.parent,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
    temporary = f".{path.name}.{secrets.token_hex(12)}.tmp"
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        try:
            view = memoryview(encoded.encode("utf-8"))
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(
            temporary,
            path.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    except Exception:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except OSError:
            pass
        raise
    finally:
        os.close(directory_fd)


def _terminate_child() -> None:
    global _cancel_requested
    _cancel_requested = True
    child = _child
    if child is None or child.poll() is not None:
        return
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def _signal_handler(_signum: int, _frame: object) -> None:
    _terminate_child()


def _prepare(arguments: argparse.Namespace) -> tuple[Path, Path, list[str]]:
    receipt = Path(arguments.receipt)
    log_path = Path(arguments.log)
    command = list(arguments.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("runner requires a command")
    if arguments.cpus < 1:
        raise ValueError("runner requires a positive CPU limit")
    if not math.isfinite(arguments.timeout_seconds) or arguments.timeout_seconds <= 0:
        raise ValueError("runner requires a finite positive timeout")
    _apply_cpu_affinity(arguments.cpus)
    return receipt, log_path, command


def _apply_cpu_affinity(cpus: int) -> None:
    if hasattr(os, "sched_getaffinity") and hasattr(os, "sched_setaffinity"):
        available = sorted(os.sched_getaffinity(0))
        if available:
            os.sched_setaffinity(0, set(available[:cpus]))


def _signal_process_group(child: subprocess.Popen[bytes], signum: int) -> None:
    try:
        os.killpg(child.pid, signum)
    except ProcessLookupError:
        pass


def _stop_and_wait(child: subprocess.Popen[bytes]) -> int:
    _signal_process_group(child, signal.SIGTERM)
    try:
        return child.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        _signal_process_group(child, signal.SIGKILL)
        return child.wait()


def _wait_for_exit(
    child: subprocess.Popen[bytes], timeout_seconds: float
) -> tuple[int, bool, str | None]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            return child.wait(timeout=0.2), False, None
        except subprocess.TimeoutExpired:
            if _cancel_requested:
                return _stop_and_wait(child), False, None
            if time.monotonic() >= deadline:
                return (
                    _stop_and_wait(child),
                    True,
                    "ARI run exceeded its declared timeout",
                )


def _execute_child(
    arguments: argparse.Namespace,
    command: list[str],
    log_path: Path,
    receipt: Path,
    initial: dict[str, object],
) -> tuple[int, bool, str | None, int | None]:
    global _child
    descriptor = os.open(
        log_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as log_handle:
        _child = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            cwd=arguments.cwd,
            start_new_session=True,
        )
        child_start_ticks = _start_ticks(_child.pid)
        _atomic_receipt(
            receipt,
            {
                **initial,
                "state": "running",
                "child_pid": _child.pid,
                "child_start_ticks": child_start_ticks,
            },
        )
        if _cancel_requested:
            _signal_process_group(_child, signal.SIGTERM)
        return_code, timed_out, error = _wait_for_exit(
            _child, float(arguments.timeout_seconds)
        )
        return return_code, timed_out, error, child_start_ticks


def run(arguments: argparse.Namespace) -> int:
    receipt, log_path, command = _prepare(arguments)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    initial: dict[str, object] = {
        "schema_version": "ari.orchestrator-runner-receipt/v1",
        "run_id": arguments.run_id,
        "request_digest": arguments.request_digest,
        "wrapper_pid": os.getpid(),
        "wrapper_start_ticks": _start_ticks(os.getpid()),
        "state": "starting",
        "started_at": _now(),
    }
    _atomic_receipt(receipt, initial)
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    return_code = 127
    error: str | None = None
    timed_out = False
    child_start_ticks: int | None = None
    try:
        return_code, timed_out, error, child_start_ticks = _execute_child(
            arguments, command, log_path, receipt, initial
        )
    except (OSError, ValueError) as exc:
        error = f"runner could not execute ARI CLI: {exc}"
        if _child is not None and _child.poll() is None:
            return_code = _stop_and_wait(_child)

    state = (
        "cancelled"
        if _cancel_requested
        else (
            "failed" if timed_out else ("succeeded" if return_code == 0 else "failed")
        )
    )
    final = {
        **initial,
        "state": state,
        "child_pid": _child.pid if _child is not None else None,
        "child_start_ticks": child_start_ticks,
        "exit_code": return_code,
        "completed_at": _now(),
        "error": error,
    }
    _atomic_receipt(receipt, final)
    return 0 if state == "succeeded" else (130 if state == "cancelled" else 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="ARI orchestrator process wrapper")
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--request-digest", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--timeout-seconds", required=True, type=float)
    parser.add_argument("--cpus", required=True, type=int)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
