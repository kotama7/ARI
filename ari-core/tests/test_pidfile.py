"""Tests for ari.pidfile — PID file management."""
import atexit
import os
import signal
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from ari.pidfile import (
    PID_FILENAME,
    check_pid,
    pid_context,
    read_pid,
    remove_pid,
    write_pid,
)


# ── write_pid ──────────────────────────────────────────


def test_write_pid_creates_file(tmp_path):
    result = write_pid(tmp_path)
    assert result == tmp_path / PID_FILENAME
    assert result.exists()
    assert result.read_text().strip() == str(os.getpid())


def test_write_pid_overwrites(tmp_path):
    (tmp_path / PID_FILENAME).write_text("99999")
    write_pid(tmp_path)
    assert (tmp_path / PID_FILENAME).read_text().strip() == str(os.getpid())


# ── remove_pid ─────────────────────────────────────────


def test_remove_pid_deletes_file(tmp_path):
    write_pid(tmp_path)
    remove_pid(tmp_path)
    assert not (tmp_path / PID_FILENAME).exists()


def test_remove_pid_idempotent(tmp_path):
    remove_pid(tmp_path)  # no file — should not raise
    remove_pid(tmp_path)


# ── read_pid ───────────────────────────────────────────


def test_read_pid_returns_pid(tmp_path):
    write_pid(tmp_path)
    assert read_pid(tmp_path) == os.getpid()


def test_read_pid_no_file(tmp_path):
    assert read_pid(tmp_path) is None


def test_read_pid_corrupt(tmp_path):
    (tmp_path / PID_FILENAME).write_text("not-a-number")
    assert read_pid(tmp_path) is None


def test_read_pid_negative(tmp_path):
    (tmp_path / PID_FILENAME).write_text("-1")
    assert read_pid(tmp_path) is None


def test_read_pid_zero(tmp_path):
    (tmp_path / PID_FILENAME).write_text("0")
    assert read_pid(tmp_path) is None


def test_read_pid_whitespace(tmp_path):
    (tmp_path / PID_FILENAME).write_text(f"  {os.getpid()}  \n")
    assert read_pid(tmp_path) == os.getpid()


# ── check_pid ──────────────────────────────────────────


def test_check_pid_running(tmp_path):
    """Current process is alive — should return 'running'."""
    write_pid(tmp_path)
    assert check_pid(tmp_path) == "running"


def test_check_pid_dead(tmp_path):
    """Write a PID that doesn't exist — should return 'stopped'."""
    # Use a PID unlikely to exist
    (tmp_path / PID_FILENAME).write_text("4000000")
    assert check_pid(tmp_path) == "stopped"


def test_check_pid_no_file(tmp_path):
    assert check_pid(tmp_path) == "stopped"


def test_check_pid_corrupt(tmp_path):
    (tmp_path / PID_FILENAME).write_text("garbage")
    assert check_pid(tmp_path) == "stopped"


def test_check_pid_empty(tmp_path):
    (tmp_path / PID_FILENAME).write_text("")
    assert check_pid(tmp_path) == "stopped"


def test_check_pid_whitespace_only(tmp_path):
    (tmp_path / PID_FILENAME).write_text("   \n")
    assert check_pid(tmp_path) == "stopped"


def test_check_pid_negative(tmp_path):
    (tmp_path / PID_FILENAME).write_text("-1")
    assert check_pid(tmp_path) == "stopped"


def test_check_pid_permission_error(tmp_path):
    """PermissionError means the process exists but is owned by another user."""
    write_pid(tmp_path)
    with mock.patch("os.kill", side_effect=PermissionError):
        assert check_pid(tmp_path) == "running"


# ── pid_context ────────────────────────────────────────


def test_pid_context_normal(tmp_path):
    """File created on enter, removed on exit."""
    pid_file = tmp_path / PID_FILENAME
    with pid_context(tmp_path) as pf:
        assert pf == pid_file
        assert pid_file.exists()
        assert pid_file.read_text().strip() == str(os.getpid())
    assert not pid_file.exists()


def test_pid_context_exception(tmp_path):
    """File removed even if body raises."""
    pid_file = tmp_path / PID_FILENAME
    with pytest.raises(RuntimeError):
        with pid_context(tmp_path):
            assert pid_file.exists()
            raise RuntimeError("boom")
    assert not pid_file.exists()


def test_pid_context_registers_atexit(tmp_path):
    with mock.patch("atexit.register") as reg, mock.patch("atexit.unregister"):
        with pid_context(tmp_path):
            reg.assert_called_once()


def test_pid_context_unregisters_atexit(tmp_path):
    with mock.patch("atexit.register"), mock.patch("atexit.unregister") as unreg:
        with pid_context(tmp_path):
            pass
        unreg.assert_called_once()


# ── Integration: subprocess creates and cleans up PID file ─────


def test_pid_cleanup_on_process_exit(tmp_path):
    """Spawn a child that uses pid_context, verify cleanup after exit."""
    script = tmp_path / "child.py"
    script.write_text(
        "import sys; sys.path.insert(0, %r)\n"
        "from ari.pidfile import pid_context\n"
        "from pathlib import Path\n"
        "with pid_context(Path(%r)):\n"
        "    pass\n"
        % (
            str(Path(__file__).resolve().parent.parent),
            str(tmp_path),
        )
    )
    result = subprocess.run([sys.executable, str(script)], capture_output=True, timeout=10)
    assert result.returncode == 0
    assert not (tmp_path / PID_FILENAME).exists()
