"""Operational health probes + bounded diagnostics for the ARI GUI (MN-9).

gui_refresh task 09 Wave 5b, plan 09 §Operational visibility
------------------------------------------------------------
Three read-only surfaces, all built here so ``routes.py`` / the v1 router
stay thin delegates:

* ``GET /health/live`` -> :func:`health_live` — the constant
  ``{"status": "ok"}``. No dependencies are consulted: if the HTTP
  handler can answer at all, the process is live. Never anything else.
* ``GET /health/ready`` -> :func:`health_ready` — ``{"status":
  "ok"|"degraded", "checks": {http, websocket, watcher, event_bus,
  active_checkpoint}}``. Each check is evaluated independently and a
  crashing check reads as ``false`` — a readiness probe **never answers
  500** (plan 09: degraded/recovery states must be observable, not
  exceptions). ``degraded`` is an honest 200.
* ``GET /api/v1/diagnostics`` -> :func:`diagnostics` — bounded scalars
  only (plan 09 §Operational visibility: SSE connection stats, watcher
  lag, tracked processes; "raw metrics に secret/path leakage を含めない"):
  ``sse {subscribers, buffer_len, last_event_id}``, ``watcher {alive,
  last_scan_age_s}``, ``process {tracked_runs}``, ``cache: false`` (no
  cache subsystem exists yet — stated explicitly rather than omitted),
  plus the payload ``schema_version`` and the served ``openapi_version``.
  No secret, no filesystem path, nothing beyond counts/ages/versions.

Auth posture (MN-8/ADR-13): the ``/health`` prefix is exempt from the
remote token gate (liveness probes must work without credentials — the
gate in ``ari/viz/auth.py`` already carves it out), while
``/api/v1/diagnostics`` rides the normal ``do_GET`` gate and therefore
REQUIRES the bearer token in remote mode like every other endpoint.

``ARI_GUI_HEALTH`` (env kill-switch, ADR-07 register):

* owner: gui_refresh task 09 (security, performance, and operations);
* default: unset/on — the three surfaces above are served;
* rollback: ``ARI_GUI_HEALTH=0`` (or ``false``) restores the exact
  pre-MN-9 wire behavior — ``/health/live`` and ``/health/ready`` fall
  through to the SPA fallback (they were never API paths before) and
  ``GET /api/v1/diagnostics`` answers the typed 404 envelope (it did
  not exist in the v1 table);
* removal gate: G5 — reviewed with the release-gate decision on
  operational visibility; until then the switch is the ADR-07 rollback
  lever for probe-scraping topologies that must not see the new JSON.

The check helpers read process-wide seams (``state._ws_server_started``,
``state_sync._watcher_thread_handle`` / ``_watcher_heartbeat_ts``,
``state._running_procs``, the v1 event bus) and are module-level so
``tests/test_gui_health_diagnostics.py`` can monkeypatch each
independently.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from . import state as _st
from . import state_sync as _ss

log = logging.getLogger(__name__)


def health_enabled() -> bool:
    """True unless the ARI_GUI_HEALTH kill-switch (MN-9) disables the
    health/diagnostics surfaces (see the module docstring register)."""
    return os.environ.get("ARI_GUI_HEALTH", "").strip().lower() not in (
        "0",
        "false",
    )


# ──────────────────────────────────────────────────────────────────────
# Individual readiness checks (each independently monkeypatchable)
# ──────────────────────────────────────────────────────────────────────


def _check_websocket() -> bool:
    """WS server started — ``server._main`` flips ``_st._ws_server_started``
    once ``ws_serve`` is live (False in embeddings that never start it)."""
    return bool(getattr(_st, "_ws_server_started", False))


def _check_watcher() -> bool:
    """The ``state_sync._watcher_thread`` polling thread is alive.

    The thread registers itself in ``state_sync._watcher_thread_handle``
    on entry, so this reflects the real thread however it was started.
    """
    handle = getattr(_ss, "_watcher_thread_handle", None)
    return handle is not None and handle.is_alive()


def _watcher_last_scan_age_s() -> "float | None":
    """Seconds since the watcher last completed a scan tick (None = never).

    The heartbeat is stamped once per poll loop in
    ``state_sync._watcher_thread`` — a live thread shows an age around its
    1 s poll interval; a stuck/dead one shows the age growing unbounded.
    """
    ts = getattr(_ss, "_watcher_heartbeat_ts", None)
    if not ts:
        return None
    return max(0.0, round(time.time() - float(ts), 3))


def _check_event_bus() -> bool:
    """v1 event bus importable + publishable (``publish`` callable over a
    non-empty topic vocabulary). Import failure reads as not-ready, never
    an exception — simple_bfts/no-GUI paths still never load viz.v1
    because this module is only imported by the GUI routes."""
    try:
        from .v1 import events as _ev

        return callable(getattr(_ev, "publish", None)) and bool(
            getattr(_ev, "TOPICS", ())
        )
    except Exception:
        return False


def _check_active_checkpoint() -> bool:
    """An active checkpoint is selected and still exists on disk."""
    try:
        ckpt = _st._checkpoint_dir
        return ckpt is not None and Path(ckpt).exists()
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────
# Probe payload builders
# ──────────────────────────────────────────────────────────────────────


def health_live() -> dict:
    """``GET /health/live`` body — constant, dependency-free liveness."""
    return {"status": "ok"}


# (check label, module-global function name) — resolved late through
# globals() so tests can monkeypatch the individual _check_* functions.
_READY_CHECKS = (
    ("websocket", "_check_websocket"),
    ("watcher", "_check_watcher"),
    ("event_bus", "_check_event_bus"),
    ("active_checkpoint", "_check_active_checkpoint"),
)


def health_ready() -> dict:
    """``GET /health/ready`` body — never raises, never a 500.

    ``http`` is constitutively true (this function only runs inside a
    successfully dispatched HTTP request); every other check degrades to
    ``false`` on its own exception so one broken subsystem cannot take
    the probe down with it.
    """
    checks: dict[str, bool] = {"http": True}
    for name, fn_name in _READY_CHECKS:
        try:
            checks[name] = bool(globals()[fn_name]())
        except Exception:
            log.debug("readiness check %s failed", name, exc_info=True)
            checks[name] = False
    status = "ok" if all(checks.values()) else "degraded"
    return {"status": status, "checks": checks}


def handle_probe(handler) -> bool:
    """Serve ``/health/live`` / ``/health/ready`` onto a ``routes._Handler``.

    The thin ``do_GET`` delegate: answers the probe named by
    ``handler.path`` and returns True, or returns False (writing nothing)
    under the ``ARI_GUI_HEALTH=0`` kill-switch so the caller falls through
    to the pre-MN-9 SPA fallback.
    """
    if not health_enabled():
        return False
    body = health_live() if handler.path == "/health/live" else health_ready()
    handler._json(body)
    return True


def diagnostics():
    """``GET /api/v1/diagnostics`` payload — a :class:`DiagnosticsV1`.

    Bounded scalars only; every sub-collector degrades to its zero shape
    on failure (diagnostics must stay readable exactly when things are
    broken). No secrets and no filesystem paths ride this payload —
    ``tracked_runs`` is a count, never the checkpoint-path keys of
    ``_st._running_procs``.
    """
    from .v1 import dto
    from .v1.openapi import OPENAPI_INFO_VERSION

    sse = dto.DiagnosticsSseV1()
    try:
        from .v1 import events as _ev

        stats = _ev.bus_stats()
        sse = dto.DiagnosticsSseV1(
            subscribers=int(stats.get("subscribers", 0)),
            buffer_len=int(stats.get("buffer_len", 0)),
            last_event_id=int(stats.get("last_event_id", 0)),
        )
    except Exception:
        log.debug("diagnostics: event bus stats failed", exc_info=True)

    try:
        watcher = dto.DiagnosticsWatcherV1(
            alive=_check_watcher(),
            last_scan_age_s=_watcher_last_scan_age_s(),
        )
    except Exception:
        log.debug("diagnostics: watcher stats failed", exc_info=True)
        watcher = dto.DiagnosticsWatcherV1()

    try:
        tracked = len(getattr(_st, "_running_procs", {}) or {})
    except Exception:
        tracked = 0

    return dto.DiagnosticsV1(
        sse=sse,
        watcher=watcher,
        process=dto.DiagnosticsProcessV1(tracked_runs=tracked),
        openapi_version=OPENAPI_INFO_VERSION,
    )
