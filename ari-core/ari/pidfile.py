"""PID file management for ARI experiment processes.

Provides a single source of truth for writing, reading, and cleaning up
.ari_pid files so that both the CLI and the GUI dashboard can reliably
detect whether an experiment is running.
"""
from __future__ import annotations

import atexit
import os
import signal
from contextlib import contextmanager
from pathlib import Path

PID_FILENAME = ".ari_pid"


def write_pid(checkpoint_dir: Path) -> Path:
    """Write the current process PID to the checkpoint directory."""
    pid_file = checkpoint_dir / PID_FILENAME
    pid_file.write_text(str(os.getpid()))
    return pid_file


def remove_pid(checkpoint_dir: Path) -> None:
    """Remove the PID file if it exists (idempotent)."""
    try:
        (checkpoint_dir / PID_FILENAME).unlink(missing_ok=True)
    except Exception:
        pass


def check_pid(checkpoint_dir: Path) -> str:
    """Check if the process recorded in .ari_pid is alive.

    Returns "running" if the PID file exists and the process is alive,
    "stopped" otherwise.
    """
    pid_file = checkpoint_dir / PID_FILENAME
    if not pid_file.exists():
        return "stopped"
    try:
        pid = int(pid_file.read_text().strip())
        if pid <= 0:
            return "stopped"
        os.kill(pid, 0)
        return "running"
    except (ValueError, ProcessLookupError):
        return "stopped"
    except PermissionError:
        # Process exists but owned by another user
        return "running"


def read_pid(checkpoint_dir: Path) -> int | None:
    """Read the PID from .ari_pid, or None if unavailable."""
    pid_file = checkpoint_dir / PID_FILENAME
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text().strip())
        return pid if pid > 0 else None
    except (ValueError, OSError):
        return None


@contextmanager
def pid_context(checkpoint_dir: Path):
    """Context manager that writes .ari_pid on enter and removes on exit.

    Also registers an atexit handler and SIGTERM handler as safety nets.
    """
    pid_file = write_pid(checkpoint_dir)

    def _cleanup():
        try:
            pid_file.unlink(missing_ok=True)
        except Exception:
            pass

    atexit.register(_cleanup)

    prev_handler = signal.getsignal(signal.SIGTERM)

    def _sigterm(signum, frame):
        _cleanup()
        # Re-raise with previous handler
        if callable(prev_handler):
            prev_handler(signum, frame)
        else:
            raise SystemExit(128 + signum)

    try:
        signal.signal(signal.SIGTERM, _sigterm)
    except (OSError, ValueError):
        # signal.signal can fail in non-main threads
        pass

    try:
        yield pid_file
    finally:
        _cleanup()
        atexit.unregister(_cleanup)
        try:
            signal.signal(signal.SIGTERM, prev_handler)
        except (OSError, ValueError):
            pass
