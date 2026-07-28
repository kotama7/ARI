"""gui_refresh Wave 5b (task 09) — plan 09 §Operational visibility / MN-9:
health probes + bounded diagnostics.

Covers:

* ``GET /health/live`` — the constant ``{"status": "ok"}``, no dependency
  consulted (still ok when every readiness check raises);
* ``GET /health/ready`` — ``{status, checks{http, websocket, watcher,
  event_bus, active_checkpoint}}``; all-green => ``ok``; a dead watcher
  thread (monkeypatched handle) => ``degraded`` with HTTP 200 — degraded is
  never a 500, and a crashing check reads as ``false``;
* MN-8 interplay — ``/health/*`` stays auth-exempt in remote mode while
  ``GET /api/v1/diagnostics`` requires the bearer token like any endpoint;
* ``GET /api/v1/diagnostics`` — shape (sse{subscribers, buffer_len,
  last_event_id} / watcher{alive, last_scan_age_s} / process{tracked_runs}
  / cache: false / schema+openapi versions), SSE subscriber counting in
  ``events.stream_events``, and no secret/path leakage (the checkpoint
  path keys of ``_st._running_procs`` never ride the payload);
* watcher telemetry seams — ``state_sync._watcher_thread`` self-registers
  its thread handle and stamps a per-scan heartbeat;
* ``ARI_GUI_HEALTH=0`` kill-switch — ``/health/*`` falls back to the
  pre-MN-9 SPA response and the diagnostics route answers the typed 404.

Socketless handlers (``_Handler.__new__``) mirror
``tests/test_gui_remote_auth.py``.
"""

from __future__ import annotations

import io
import json
import threading
import time

import pytest

from ari.viz import auth
from ari.viz import health
from ari.viz import state as _st
from ari.viz import state_sync
from ari.viz.routes import _Handler
from ari.viz.v1 import events as _v1_events
from ari.viz.v1.openapi import OPENAPI_INFO_VERSION
from ari.viz.v1.router import dispatch


TOKEN = "wave5b-health-token-0123456789abcdef"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Pristine auth/env/bus/watcher seams before and after every test."""
    monkeypatch.delenv("ARI_GUI_BIND", raising=False)
    monkeypatch.delenv("ARI_GUI_TOKEN", raising=False)
    monkeypatch.delenv("ARI_GUI_AUTH", raising=False)
    monkeypatch.delenv("ARI_GUI_HEALTH", raising=False)
    monkeypatch.setattr(state_sync, "_watcher_thread_handle", None)
    monkeypatch.setattr(state_sync, "_watcher_heartbeat_ts", None)
    monkeypatch.setattr(_st, "_ws_server_started", False)
    monkeypatch.setattr(_st, "_running_procs", {}, raising=False)
    auth._reset_for_tests()
    _v1_events._reset_for_tests()
    yield
    auth._reset_for_tests()
    _v1_events._reset_for_tests()


def _make_handler(path: str, headers: dict | None = None):
    h = _Handler.__new__(_Handler)
    h.path = path
    h.headers = headers if headers is not None else {"Host": "127.0.0.1:8765"}
    h.wfile = io.BytesIO()
    h.sent = []
    h.send_response = lambda code: h.sent.append(("status", code))
    h.send_header = lambda k, v: h.sent.append((k, v))
    h.end_headers = lambda: h.sent.append(("end", None))
    return h


def _statuses(h):
    return [v for k, v in h.sent if k == "status"]


def _header_map(sent):
    return {k: v for k, v in sent if k not in ("status", "end")}


class _FakeThread:
    def __init__(self, alive: bool):
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


def _all_green(monkeypatch, tmp_path):
    """Point every readiness seam at a healthy subsystem."""
    monkeypatch.setattr(_st, "_ws_server_started", True)
    monkeypatch.setattr(state_sync, "_watcher_thread_handle", _FakeThread(True))
    monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path)
    # event_bus: the real ari.viz.v1.events import satisfies the check.


# ──────────────────────────────────────────────────────────────────────
# /health/live — always ok, no dependencies
# ──────────────────────────────────────────────────────────────────────


def test_health_live_is_constant_ok():
    assert health.health_live() == {"status": "ok"}


def test_health_live_http_ok_even_when_every_check_raises(monkeypatch):
    def _boom():
        raise RuntimeError("subsystem down")

    for fn in ("_check_websocket", "_check_watcher", "_check_event_bus",
               "_check_active_checkpoint"):
        monkeypatch.setattr(health, fn, _boom)
    h = _make_handler("/health/live")
    h.do_GET()
    assert _statuses(h) == [200]
    assert json.loads(h.wfile.getvalue()) == {"status": "ok"}


# ──────────────────────────────────────────────────────────────────────
# /health/ready — ok vs degraded, never 500
# ──────────────────────────────────────────────────────────────────────


def test_health_ready_all_green_is_ok(monkeypatch, tmp_path):
    _all_green(monkeypatch, tmp_path)
    body = health.health_ready()
    assert body["status"] == "ok"
    assert body["checks"] == {
        "http": True,
        "websocket": True,
        "watcher": True,
        "event_bus": True,
        "active_checkpoint": True,
    }


def test_health_ready_degraded_when_watcher_dead(monkeypatch, tmp_path):
    _all_green(monkeypatch, tmp_path)
    monkeypatch.setattr(
        state_sync, "_watcher_thread_handle", _FakeThread(False)
    )
    h = _make_handler("/health/ready")
    h.do_GET()
    assert _statuses(h) == [200]  # degraded is never a 500
    body = json.loads(h.wfile.getvalue())
    assert body["status"] == "degraded"
    assert body["checks"]["watcher"] is False
    assert body["checks"]["http"] is True
    assert body["checks"]["websocket"] is True
    assert body["checks"]["event_bus"] is True
    assert body["checks"]["active_checkpoint"] is True


def test_health_ready_crashing_check_reads_false_never_500(
    monkeypatch, tmp_path
):
    _all_green(monkeypatch, tmp_path)

    def _boom():
        raise RuntimeError("bus exploded")

    monkeypatch.setattr(health, "_check_event_bus", _boom)
    h = _make_handler("/health/ready")
    h.do_GET()
    assert _statuses(h) == [200]
    body = json.loads(h.wfile.getvalue())
    assert body["status"] == "degraded"
    assert body["checks"]["event_bus"] is False


def test_health_ready_missing_checkpoint_dir_is_not_ready(monkeypatch, tmp_path):
    _all_green(monkeypatch, tmp_path)
    monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path / "deleted")
    body = health.health_ready()
    assert body["status"] == "degraded"
    assert body["checks"]["active_checkpoint"] is False


# ──────────────────────────────────────────────────────────────────────
# MN-8 interplay: /health/* exempt, diagnostics gated
# ──────────────────────────────────────────────────────────────────────


def _activate_remote(monkeypatch):
    monkeypatch.setenv("ARI_GUI_BIND", "0.0.0.0")
    monkeypatch.setenv("ARI_GUI_TOKEN", TOKEN)
    return auth.init_auth()


def test_remote_health_probes_are_auth_exempt(monkeypatch):
    _activate_remote(monkeypatch)
    for path in ("/health/live", "/health/ready"):
        h = _make_handler(path, headers={"Host": "x"})
        h.do_GET()
        assert _statuses(h) == [200], path
        body = json.loads(h.wfile.getvalue())
        assert body["status"] in ("ok", "degraded")


def test_remote_diagnostics_requires_token(monkeypatch):
    _activate_remote(monkeypatch)
    refused = _make_handler("/api/v1/diagnostics", headers={"Host": "x"})
    refused.do_GET()
    assert _statuses(refused) == [401]
    granted = _make_handler(
        "/api/v1/diagnostics",
        headers={"Host": "x", "Authorization": f"Bearer {TOKEN}"},
    )
    granted.do_GET()
    assert _statuses(granted) == [200]
    assert json.loads(granted.wfile.getvalue())["schema_version"] == 1


# ──────────────────────────────────────────────────────────────────────
# GET /api/v1/diagnostics — shape + bounded scalars
# ──────────────────────────────────────────────────────────────────────


def test_diagnostics_shape_and_scalars(monkeypatch, tmp_path):
    _v1_events.publish("tree", "run-x")
    monkeypatch.setattr(
        _st, "_running_procs",
        {str(tmp_path / "a"): object(), str(tmp_path / "b"): object()},
    )
    monkeypatch.setattr(
        state_sync, "_watcher_heartbeat_ts", time.time() - 5.0
    )
    r = dispatch("GET", "/api/v1/diagnostics")
    assert "_status" not in r
    assert r["schema_version"] == 1
    assert r["openapi_version"] == OPENAPI_INFO_VERSION
    assert r["cache"] is False  # no cache subsystem yet — explicit false
    assert r["sse"] == {"subscribers": 0, "buffer_len": 1, "last_event_id": 1}
    assert r["watcher"]["alive"] is False  # no watcher thread in this test
    assert 4.0 <= r["watcher"]["last_scan_age_s"] <= 60.0
    assert r["process"] == {"tracked_runs": 2}
    assert r["request_id"].startswith("req-")
    assert set(r.keys()) == {
        "schema_version", "sse", "watcher", "process", "cache",
        "openapi_version", "request_id",
    }


def test_diagnostics_never_leaks_paths_or_tokens(monkeypatch, tmp_path):
    """plan 09: raw metrics carry no secret/path leakage — the checkpoint
    path keys of _running_procs and the auth token must not appear."""
    monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path)
    monkeypatch.setattr(
        _st, "_running_procs", {str(tmp_path / "20260101_run"): object()}
    )
    monkeypatch.setenv("ARI_GUI_TOKEN", TOKEN)
    wire = json.dumps(dispatch("GET", "/api/v1/diagnostics"))
    assert str(tmp_path) not in wire
    assert "20260101_run" not in wire
    assert TOKEN not in wire


def test_diagnostics_watcher_never_ran_age_is_none():
    r = dispatch("GET", "/api/v1/diagnostics")
    assert r["watcher"] == {"alive": False, "last_scan_age_s": None}


def test_stream_events_counts_subscribers():
    """MN-9: bus_stats().subscribers is 1 inside a live stream_events call
    and returns to 0 after the client disconnects."""
    seen: list[int] = []

    class _W:
        def write(self, _b):
            seen.append(_v1_events.bus_stats()["subscribers"])
            raise BrokenPipeError

        def flush(self):
            pass

    assert _v1_events.bus_stats()["subscribers"] == 0
    _v1_events.stream_events(_W())
    assert seen == [1]
    assert _v1_events.bus_stats()["subscribers"] == 0


# ──────────────────────────────────────────────────────────────────────
# Watcher telemetry seams (state_sync._watcher_thread)
# ──────────────────────────────────────────────────────────────────────


def test_watcher_thread_registers_handle_and_heartbeat(monkeypatch):
    class _Stop(Exception):
        pass

    calls = {"n": 0}

    def fake_sleep(_s):
        calls["n"] += 1
        if calls["n"] > 1:
            raise _Stop

    monkeypatch.setattr(time, "sleep", fake_sleep)
    monkeypatch.setattr(_st, "_checkpoint_dir", None)
    with pytest.raises(_Stop):
        state_sync._watcher_thread()
    assert state_sync._watcher_thread_handle is threading.current_thread()
    assert state_sync._watcher_heartbeat_ts is not None
    # The self-registered (current, alive) thread satisfies the check.
    assert health._check_watcher() is True
    assert health._watcher_last_scan_age_s() >= 0.0


# ──────────────────────────────────────────────────────────────────────
# ARI_GUI_HEALTH kill-switch (MN-9, ADR-07 register in health.py)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("off", ["0", "false", " FALSE "])
def test_health_enabled_kill_switch_matrix(monkeypatch, off):
    assert health.health_enabled() is True
    monkeypatch.setenv("ARI_GUI_HEALTH", off)
    assert health.health_enabled() is False
    monkeypatch.setenv("ARI_GUI_HEALTH", "1")
    assert health.health_enabled() is True


def test_kill_switch_restores_pre_mn9_spa_fallback(monkeypatch):
    monkeypatch.setenv("ARI_GUI_HEALTH", "0")
    h = _make_handler("/health/live")
    h.do_GET()
    assert _statuses(h) == [200]
    # Pre-MN-9 wire behavior: the SPA fallback (HTML), not a JSON probe.
    assert _header_map(h.sent)["Content-Type"].startswith("text/html")


def test_kill_switch_disables_diagnostics_with_typed_404(monkeypatch):
    monkeypatch.setenv("ARI_GUI_HEALTH", "0")
    r = dispatch("GET", "/api/v1/diagnostics")
    assert r["_status"] == 404
    assert r["error"]["code"] == "not_found"
    assert r["error"]["request_id"].startswith("req-")
