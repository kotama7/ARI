"""Regression tests: Monitor status & Stop fall back to .ari_pid.

When the GUI restarts (or was never the launcher), the in-memory
`_st._last_proc` handle is lost. Without the .ari_pid fallback, the active
checkpoint is incorrectly shown as "stopped" and the Stop button does nothing
except pkill (which also kills the GUI itself).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from ari.pidfile import write_pid
from ari.viz import state as _st
from ari.viz.api_state import _api_checkpoints


@pytest.fixture
def fresh_state(monkeypatch):
    """Isolate viz.state globals for each test."""
    monkeypatch.setattr(_st, "_last_proc", None, raising=False)
    monkeypatch.setattr(_st, "_running_procs", {}, raising=False)
    monkeypatch.setattr(_st, "_checkpoint_dir", None, raising=False)
    yield


@pytest.fixture
def tmp_ckpt_root(tmp_path, monkeypatch):
    """Point the checkpoint search to an isolated tmp dir."""
    root = tmp_path / "checkpoints"
    root.mkdir()
    monkeypatch.setattr(
        "ari.viz.api_state._checkpoint_search_bases",
        lambda: [root],
    )
    return root


def _make_ckpt(root: Path, name: str = "20260416013753_test") -> Path:
    d = root / name
    d.mkdir()
    return d


# ── Status: active checkpoint with live .ari_pid → "running" ────────────


def test_active_checkpoint_uses_pidfile_when_last_proc_none(
    fresh_state, tmp_ckpt_root
):
    ckpt = _make_ckpt(tmp_ckpt_root)
    write_pid(ckpt)  # records our own PID (definitely alive)
    _st._checkpoint_dir = ckpt  # active but no _last_proc

    [info] = _api_checkpoints()
    assert info["id"] == ckpt.name
    assert info["status"] == "running", "PID fallback must mark active as running"


def test_active_checkpoint_with_dead_pid_reports_stopped(
    fresh_state, tmp_ckpt_root
):
    ckpt = _make_ckpt(tmp_ckpt_root)
    # Dead PID: pick a pid that definitely doesn't exist
    (ckpt / ".ari_pid").write_text("999999999")
    _st._checkpoint_dir = ckpt

    [info] = _api_checkpoints()
    assert info["status"] == "stopped"


def test_active_checkpoint_without_pidfile_reports_stopped(
    fresh_state, tmp_ckpt_root
):
    ckpt = _make_ckpt(tmp_ckpt_root)
    _st._checkpoint_dir = ckpt
    assert not (ckpt / ".ari_pid").exists()

    [info] = _api_checkpoints()
    assert info["status"] == "stopped"


def test_nonactive_checkpoint_still_uses_pidfile(fresh_state, tmp_ckpt_root):
    """Regression: pre-existing non-active fallback must continue to work."""
    ckpt = _make_ckpt(tmp_ckpt_root)
    write_pid(ckpt)
    # _checkpoint_dir is None → this checkpoint is non-active

    [info] = _api_checkpoints()
    assert info["status"] == "running"


def test_in_memory_proc_still_wins_over_pidfile(fresh_state, tmp_ckpt_root):
    """If _last_proc is alive, skip the pidfile path entirely."""
    ckpt = _make_ckpt(tmp_ckpt_root)
    (ckpt / ".ari_pid").write_text("999999999")  # dead PID
    _st._checkpoint_dir = ckpt

    class _FakeProc:
        def poll(self):
            return None  # alive

    _st._last_proc = _FakeProc()

    [info] = _api_checkpoints()
    assert info["status"] == "running"


# ── Stop: pidfile fallback hands correct PID to the kill path ──────────


def test_stop_pidfile_fallback_reads_active_checkpoint(tmp_path, fresh_state):
    """Simulate the /api/stop fallback: when _last_proc is None, the handler
    must read the PID from the active checkpoint's .ari_pid."""
    from ari.pidfile import read_pid

    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    (ckpt / ".ari_pid").write_text("12345")
    _st._checkpoint_dir = ckpt

    pid = read_pid(Path(_st._checkpoint_dir))
    assert pid == 12345


def test_stop_pidfile_fallback_handles_missing_pidfile(tmp_path, fresh_state):
    """If .ari_pid is absent, read_pid returns None and the fallback
    degrades gracefully to 'not running'."""
    from ari.pidfile import read_pid

    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    _st._checkpoint_dir = ckpt

    assert read_pid(Path(_st._checkpoint_dir)) is None


def test_stop_pidfile_fallback_kills_real_child(tmp_path, fresh_state):
    """End-to-end: spawn a real child, write its PID, then exercise the exact
    signalling sequence /api/stop uses (killpg → SIGTERM → verify)."""
    import subprocess
    import signal as _sig

    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()

    proc = subprocess.Popen(
        ["python3", "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    try:
        (ckpt / ".ari_pid").write_text(str(proc.pid))
        _st._checkpoint_dir = ckpt
        _st._last_proc = None  # force fallback

        from ari.pidfile import read_pid
        pid = read_pid(Path(_st._checkpoint_dir))
        assert pid == proc.pid

        # Mirror the server.py fallback path
        os.killpg(os.getpgid(pid), _sig.SIGTERM)
        for _ in range(50):
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        assert proc.poll() is not None, "child must exit after SIGTERM via killpg"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)
