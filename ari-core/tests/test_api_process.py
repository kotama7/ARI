"""Characterization tests for ari.viz.api_process (req 05 extraction).

These call the REAL extracted service functions (_api_stop,
_api_gpu_monitor_status, _api_gpu_monitor_action) — unlike the older
/api/stop and gpu-monitor tests which re-implemented the logic inline and
never exercised the handler. They pin the dict shapes and the
state-handle behaviour the route handlers depend on.
"""
from __future__ import annotations

from unittest import mock

import pytest

from ari.viz import state as _st
from ari.viz import api_process


@pytest.fixture
def clean_state(monkeypatch):
    """Reset the ari.viz.state globals these functions touch."""
    monkeypatch.setattr(_st, "_last_proc", None, raising=False)
    monkeypatch.setattr(_st, "_gpu_monitor_proc", None, raising=False)
    monkeypatch.setattr(_st, "_checkpoint_dir", None, raising=False)
    monkeypatch.setattr(_st, "_settings_path", None, raising=False)
    yield _st


# ── _api_gpu_monitor_status ──────────────────────────────────────────────────

def test_gpu_monitor_status_not_running(clean_state):
    out = api_process._api_gpu_monitor_status()
    assert out == {"running": False, "pid": None, "log": "", "ollama_host": ""}


def test_gpu_monitor_status_running_reports_pid(clean_state, monkeypatch):
    proc = mock.MagicMock()
    proc.poll.return_value = None  # alive
    proc.pid = 4242
    monkeypatch.setattr(_st, "_gpu_monitor_proc", proc, raising=False)
    out = api_process._api_gpu_monitor_status()
    assert out["running"] is True
    assert out["pid"] == 4242
    # keys are stable regardless of log/settings availability
    assert set(out) == {"running", "pid", "log", "ollama_host"}


# ── _api_gpu_monitor_action ──────────────────────────────────────────────────

def test_gpu_monitor_start_requires_confirmation(clean_state):
    out = api_process._api_gpu_monitor_action(b'{"action": "start"}')
    assert out["ok"] is False
    assert out["needs_confirm"] is True


def test_gpu_monitor_start_when_already_running(clean_state, monkeypatch):
    proc = mock.MagicMock()
    proc.poll.return_value = None  # alive
    proc.pid = 777
    monkeypatch.setattr(_st, "_gpu_monitor_proc", proc, raising=False)
    out = api_process._api_gpu_monitor_action(b'{"action": "start", "confirmed": true}')
    assert out == {"ok": False, "msg": "already running", "pid": 777}


def test_gpu_monitor_stop_terminates_running(clean_state, monkeypatch):
    proc = mock.MagicMock()
    proc.poll.return_value = None  # alive
    monkeypatch.setattr(_st, "_gpu_monitor_proc", proc, raising=False)
    out = api_process._api_gpu_monitor_action(b'{"action": "stop"}')
    assert out == {"ok": True}
    proc.terminate.assert_called_once()


def test_gpu_monitor_unknown_action(clean_state):
    out = api_process._api_gpu_monitor_action(b'{"action": "frobnicate"}')
    assert out == {"ok": False, "msg": "unknown action"}


# ── _api_stop ────────────────────────────────────────────────────────────────

def test_stop_no_process_returns_not_running(clean_state, monkeypatch):
    # No _last_proc, no checkpoint pidfile, and stub the pkill/pgrep shells.
    with mock.patch("ari.viz.api_process.subprocess.run") as run:
        run.return_value = mock.MagicMock(returncode=1, stdout="")
        out = api_process._api_stop()
    assert out["ok"] is True
    assert out["stopped"] is False
    assert out["report"]["main"] == "not running"
    assert out["report"]["gpu_monitor"] == "not running"
    assert "survivors" in out["report"]


def test_stop_kills_running_main_proc(clean_state, monkeypatch):
    proc = mock.MagicMock()
    # Alive on the entry check, then dead so the 5s graceful-wait loop breaks on
    # its first iteration. A small counter avoids StopIteration from the loop's
    # repeated poll() calls (the handler polls more than twice).
    polls = {"n": 0}
    def _poll():
        polls["n"] += 1
        return None if polls["n"] == 1 else 0
    proc.poll.side_effect = _poll
    proc.pid = 31337
    monkeypatch.setattr(_st, "_last_proc", proc, raising=False)

    killed = []
    monkeypatch.setattr(api_process.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(api_process.os, "killpg", lambda pgid, sig: killed.append((pgid, sig)))
    with mock.patch("ari.viz.api_process.subprocess.run") as run:
        run.return_value = mock.MagicMock(returncode=1, stdout="")
        out = api_process._api_stop()

    assert out["stopped"] is True
    assert out["report"]["main"].startswith("stopped(SIGTERM) pid=31337")
    assert killed and killed[0][0] == 31337  # SIGTERM sent to the process group
