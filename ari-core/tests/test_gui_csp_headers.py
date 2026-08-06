"""gui_refresh Wave 5a (task 09) — RR-P0-10 / MN-7: browser security
headers (CSP + nosniff + referrer policy) on SPA/static responses.

Covers:

* the pure ``_csp_policy`` builder: 'self'-based directive set (script-src
  without 'unsafe-inline'; style-src WITH it — accepted residual tracked in
  RR-P0-10), the ws/wss connect-src sources on HTTP port + 1 derived from
  the request Host header (loopback-alias fallback, IPv6 re-bracketing,
  no-port omission), frame-src 'self' (PaperWorkspace same-origin PDF
  iframes) and frame-ancestors 'none';
* header emission on ``GET /`` (``_serve_spa_index``) and ``GET /static/...``
  via socketless ``_Handler`` instances (same pattern as
  test_gui_bind_cors.py);
* scope: ``_json`` API responses deliberately carry none of the three
  headers;
* the ``ARI_GUI_CSP=0`` kill-switch restoring the exact pre-MN-7 header set.

Register/announcement: risk_register.md row RR-P0-10 (closed Wave 5a with
the style-src residual noted), migration_notes.md MN-7. The companion
frontend guard (no external <script src> in index.html, so script-src
'self' holds) is src/__tests__/indexHtmlNoExternalScripts.test.ts.
"""

from __future__ import annotations

import io

import pytest

from ari.viz import state as _st
from ari.viz import routes as _routes
from ari.viz.routes import (
    _Handler,
    _csp_enabled,
    _csp_policy,
    _static_content_type,
)


SECURITY_HEADERS = (
    "Content-Security-Policy",
    "X-Content-Type-Options",
    "Referrer-Policy",
)


@pytest.fixture(autouse=True)
def _default_env(monkeypatch, tmp_path):
    """CSP on, fixed server port, and a self-contained static bundle."""
    monkeypatch.delenv("ARI_GUI_CSP", raising=False)
    monkeypatch.setattr(_st, "_server_port", 8765)
    react_dist = tmp_path / "static" / "dist"
    react_dist.mkdir(parents=True)
    react_index = react_dist / "index.html"
    react_index.write_text("<!doctype html><title>fixture</title>", encoding="utf-8")
    monkeypatch.setattr(_routes, "REACT_DIST_DIR", react_dist)
    monkeypatch.setattr(_routes, "REACT_INDEX", react_index)


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


def _header_map(sent):
    return {k: v for k, v in sent if k not in ("status", "end")}


# ──────────────────────────────────────────────────────────────────────
# _csp_policy (pure)
# ──────────────────────────────────────────────────────────────────────

def test_policy_directive_set():
    p = _csp_policy("localhost:8765", 8765)
    directives = dict(
        (part.split(" ", 1) + [""])[:2] for part in p.split("; ")
    )
    assert directives["default-src"] == "'self'"
    assert directives["script-src"] == "'self'"  # no unsafe-inline for scripts
    assert directives["style-src"] == "'self' 'unsafe-inline'"  # RR-P0-10 residual
    assert directives["img-src"] == "'self' data:"
    assert directives["frame-src"] == "'self'"  # PaperWorkspace PDF iframes
    assert directives["frame-ancestors"] == "'none'"
    assert directives["connect-src"].startswith("'self'")


def test_policy_ws_sources_from_host_header():
    """useWebSocket.ts dials ws://<location.hostname>:<port+1>; the policy
    must allow exactly that origin (host from the Host header)."""
    p = _csp_policy("localhost:8765", 9999)  # Host port wins over server port
    assert "connect-src 'self' ws://localhost:8766 wss://localhost:8766; " in p


def test_policy_ws_sources_ipv6_rebracketed():
    p = _csp_policy("[::1]:8765", None)
    assert "ws://[::1]:8766 wss://[::1]:8766" in p


def test_policy_ws_sources_loopback_fallback_without_host():
    p = _csp_policy(None, 8765)
    for alias in ("localhost", "127.0.0.1", "[::1]"):
        assert f"ws://{alias}:8766" in p
        assert f"wss://{alias}:8766" in p


def test_policy_omits_ws_sources_without_any_port():
    """No usable port -> no ws sources; the GUI degrades to polling (same
    as when WS is unreachable), never to a broken directive."""
    p = _csp_policy("localhost", None)
    assert "connect-src 'self'; " in p
    assert "ws:" not in p


def test_policy_garbage_host_falls_back_to_loopback():
    p = _csp_policy("cache_object:foo[", 8765)
    assert "ws://localhost:8766" in p


# ──────────────────────────────────────────────────────────────────────
# _csp_enabled / kill-switch
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "value,expected",
    [(None, True), ("", True), ("1", True), ("0", False), ("false", False), ("False", False)],
)
def test_csp_enabled_env(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("ARI_GUI_CSP", raising=False)
    else:
        monkeypatch.setenv("ARI_GUI_CSP", value)
    assert _csp_enabled() is expected


# ──────────────────────────────────────────────────────────────────────
# Header emission (socketless _Handler)
# ──────────────────────────────────────────────────────────────────────

def test_spa_index_carries_security_headers():
    h = _make_handler("/")
    h.do_GET()
    headers = _header_map(h.sent)
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    csp = headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "ws://127.0.0.1:8766" in csp  # Host-header-derived ws origin
    assert h.wfile.getvalue()  # body still served


def test_spa_fallback_route_carries_security_headers():
    """Client-side routes (e.g. /#/... deep links resolved as /somepath)
    are served by the same _serve_spa_index and get the same headers."""
    h = _make_handler("/some/spa/route")
    h.do_GET()
    assert "Content-Security-Policy" in _header_map(h.sent)


def test_static_response_carries_security_headers():
    h = _make_handler("/static/dist/index.html")
    h.do_GET()
    headers = _header_map(h.sent)
    for name in SECURITY_HEADERS:
        assert name in headers, name
    assert h.wfile.getvalue()


def test_module_worker_has_javascript_content_type():
    assert _static_content_type("mjs") == "application/javascript"


def test_kill_switch_restores_pre_mn7_header_set(monkeypatch):
    monkeypatch.setenv("ARI_GUI_CSP", "0")
    for path in ("/", "/static/dist/index.html"):
        h = _make_handler(path)
        h.do_GET()
        headers = _header_map(h.sent)
        for name in SECURITY_HEADERS:
            assert name not in headers, (path, name)
        assert h.wfile.getvalue()  # content still served


def test_json_api_responses_stay_out_of_scope():
    """MN-7 covers document/static responses only — API JSON is untouched."""
    h = _make_handler("/api/models")
    h._json({"ok": True})
    headers = _header_map(h.sent)
    for name in SECURITY_HEADERS:
        assert name not in headers, name
