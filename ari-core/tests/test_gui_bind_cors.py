"""gui_refresh Wave 5a (task 09) — RR-P0-3 / MN-4: loopback bind + same-origin CORS.

Covers:

* ``ari.viz.server.resolve_bind_hosts`` — the pure bind-address selection
  logic (loopback default, ``ARI_GUI_BIND`` override forms), no sockets;
* ``ari.viz.server._make_http_server`` — server-class selection (AF_INET
  vs dual-stack AF_INET6), loopback ephemeral ports only;
* ``ari.viz.routes._origin_allowed`` — the pure same-origin matrix
  (Host-header match, loopback:port forms, scheme/garbage rejection);
* ``_Handler`` CORS behaviour — ``_json`` echo/omission, ``do_OPTIONS``
  preflight grant vs bare 204, SSE stream headers (``/api/logs`` and
  ``/api/v1/events/stream``), and the ``ARI_GUI_CORS_ANY=1`` wildcard
  kill-switch.

Socketless handlers (``_Handler.__new__``) are used everywhere a live
server is avoidable.
"""

from __future__ import annotations

import io
import socket

import pytest

from ari.viz import routes
from ari.viz import state as _st
from ari.viz.routes import _Handler, _cors_wildcard_enabled, _origin_allowed
from ari.viz.server import _DualStackServer, _make_http_server, resolve_bind_hosts


# ──────────────────────────────────────────────────────────────────────
# Bind address resolution (pure — no sockets)
# ──────────────────────────────────────────────────────────────────────

def test_resolve_bind_hosts_default_is_loopback_only():
    assert resolve_bind_hosts(None) == ["127.0.0.1", "::1"]


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_resolve_bind_hosts_blank_is_loopback_only(blank):
    assert resolve_bind_hosts(blank) == ["127.0.0.1", "::1"]


@pytest.mark.parametrize("value,expected", [
    ("::", ["::"]),                       # legacy all-interfaces dual-stack
    ("0.0.0.0", ["0.0.0.0"]),             # IPv4 wildcard only
    ("192.168.10.5", ["192.168.10.5"]),   # a single explicit interface
    (" ::1 ", ["::1"]),                   # whitespace stripped
])
def test_resolve_bind_hosts_override(value, expected):
    assert resolve_bind_hosts(value) == expected


def test_resolve_bind_hosts_reads_ari_gui_bind_env(monkeypatch):
    """The server threads resolve the env var through this function."""
    import os
    monkeypatch.delenv("ARI_GUI_BIND", raising=False)
    assert resolve_bind_hosts(os.environ.get("ARI_GUI_BIND")) == ["127.0.0.1", "::1"]
    monkeypatch.setenv("ARI_GUI_BIND", "::")
    assert resolve_bind_hosts(os.environ.get("ARI_GUI_BIND")) == ["::"]


# ──────────────────────────────────────────────────────────────────────
# Server-class selection (loopback ephemeral ports only)
# ──────────────────────────────────────────────────────────────────────

def test_make_http_server_ipv4_loopback_binds_af_inet():
    srv = _make_http_server("127.0.0.1", 0)
    try:
        assert not isinstance(srv, _DualStackServer)
        assert srv.socket.family == socket.AF_INET
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()


def test_make_http_server_ipv6_loopback_uses_dual_stack_class():
    try:
        srv = _make_http_server("::1", 0)
    except OSError:
        pytest.skip("IPv6 loopback unavailable on this host")
    try:
        assert isinstance(srv, _DualStackServer)
        assert srv.socket.family == socket.AF_INET6
    finally:
        srv.server_close()


# ──────────────────────────────────────────────────────────────────────
# Same-origin matrix (pure — no sockets)
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("origin,host,port,expected", [
    # Host-header match (the normal same-origin case, any hostname).
    ("http://127.0.0.1:8765", "127.0.0.1:8765", 9886, True),
    ("https://portal.example", "portal.example", 8765, True),  # TLS proxy
    ("HTTP://LOCALHOST:8765", "localhost:8765", 8765, True),   # case-insensitive
    # Loopback forms on the server port (localhost vs 127.0.0.1 alias).
    ("http://localhost:8765", "127.0.0.1:8765", 8765, True),
    ("http://[::1]:8765", None, 8765, True),
    ("http://127.0.0.1:8765", None, 8765, True),
    # Rejections.
    ("http://evil.example:8765", "127.0.0.1:8765", 8765, False),
    ("http://localhost:9999", "127.0.0.1:8765", 8765, False),  # wrong port
    ("http://localhost:8765", None, None, False),  # nothing to match against
    ("null", "127.0.0.1:8765", 8765, False),       # opaque origin
    ("file:///etc/passwd", "127.0.0.1:8765", 8765, False),
    ("", "127.0.0.1:8765", 8765, False),
])
def test_origin_allowed_matrix(origin, host, port, expected):
    assert _origin_allowed(origin, host, port) is expected


def test_cors_wildcard_enabled_env(monkeypatch):
    monkeypatch.delenv("ARI_GUI_CORS_ANY", raising=False)
    assert _cors_wildcard_enabled() is False
    monkeypatch.setenv("ARI_GUI_CORS_ANY", "0")
    assert _cors_wildcard_enabled() is False
    monkeypatch.setenv("ARI_GUI_CORS_ANY", "1")
    assert _cors_wildcard_enabled() is True


# ──────────────────────────────────────────────────────────────────────
# Handler-level CORS (socketless _Handler)
# ──────────────────────────────────────────────────────────────────────

def _make_handler(path: str = "/api/models", headers: dict | None = None):
    h = _Handler.__new__(_Handler)
    h.path = path
    h.headers = headers or {}
    h.wfile = io.BytesIO()
    h.sent = []
    h.send_response = lambda code: h.sent.append(("status", code))
    h.send_header = lambda k, v: h.sent.append((k, v))
    h.end_headers = lambda: h.sent.append(("end", None))
    return h


def _header_map(sent):
    return {k: v for k, v in sent if k not in ("status", "end")}


_OWN = {"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765"}
_CROSS = {"Origin": "http://evil.example:8080", "Host": "127.0.0.1:8765"}


def test_json_echoes_same_origin(monkeypatch):
    monkeypatch.delenv("ARI_GUI_CORS_ANY", raising=False)
    h = _make_handler(headers=dict(_OWN))
    h._json({"ok": True})
    headers = _header_map(h.sent)
    assert headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:8765"
    assert headers["Vary"] == "Origin"


def test_json_omits_acao_for_cross_origin(monkeypatch):
    monkeypatch.delenv("ARI_GUI_CORS_ANY", raising=False)
    h = _make_handler(headers=dict(_CROSS))
    h._json({"ok": True})
    assert "Access-Control-Allow-Origin" not in _header_map(h.sent)


def test_json_omits_acao_without_origin_header(monkeypatch):
    monkeypatch.delenv("ARI_GUI_CORS_ANY", raising=False)
    h = _make_handler(headers={"Host": "127.0.0.1:8765"})
    h._json({"ok": True})
    assert "Access-Control-Allow-Origin" not in _header_map(h.sent)


def test_json_loopback_alias_via_server_port(monkeypatch):
    """Origin localhost:port matches even when Host says 127.0.0.1."""
    monkeypatch.delenv("ARI_GUI_CORS_ANY", raising=False)
    monkeypatch.setattr(_st, "_server_port", 8765)
    h = _make_handler(headers={
        "Origin": "http://localhost:8765", "Host": "127.0.0.1:8765",
    })
    h._json({"ok": True})
    assert _header_map(h.sent)["Access-Control-Allow-Origin"] == "http://localhost:8765"


def test_json_wildcard_kill_switch(monkeypatch):
    monkeypatch.setenv("ARI_GUI_CORS_ANY", "1")
    h = _make_handler(headers=dict(_CROSS))
    h._json({"ok": True})
    headers = _header_map(h.sent)
    assert headers["Access-Control-Allow-Origin"] == "*"
    assert "Vary" not in headers


# ── OPTIONS preflight ────────────────────────────────────────────────

def test_options_same_origin_grants_preflight(monkeypatch):
    monkeypatch.delenv("ARI_GUI_CORS_ANY", raising=False)
    h = _make_handler(path="/api/launch", headers=dict(_OWN))
    h.do_OPTIONS()
    assert ("status", 204) in h.sent
    headers = _header_map(h.sent)
    assert headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:8765"
    assert headers["Vary"] == "Origin"
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        assert method in headers["Access-Control-Allow-Methods"]
    assert "If-Match" in headers["Access-Control-Allow-Headers"]
    assert "Access-Control-Max-Age" in headers


def test_options_cross_origin_bare_204(monkeypatch):
    monkeypatch.delenv("ARI_GUI_CORS_ANY", raising=False)
    h = _make_handler(path="/api/launch", headers=dict(_CROSS))
    h.do_OPTIONS()
    assert ("status", 204) in h.sent
    headers = _header_map(h.sent)
    assert not any(k.startswith("Access-Control") for k in headers)
    assert headers["Content-Length"] == "0"


def test_options_wildcard_kill_switch(monkeypatch):
    monkeypatch.setenv("ARI_GUI_CORS_ANY", "1")
    h = _make_handler(path="/api/launch", headers=dict(_CROSS))
    h.do_OPTIONS()
    headers = _header_map(h.sent)
    assert headers["Access-Control-Allow-Origin"] == "*"
    assert "Vary" not in headers


# ── SSE streams ──────────────────────────────────────────────────────

def test_sse_logs_same_origin_headers(monkeypatch):
    monkeypatch.delenv("ARI_GUI_CORS_ANY", raising=False)
    monkeypatch.setattr(routes, "_api_logs_sse", lambda wfile: None)
    h = _make_handler(path="/api/logs", headers=dict(_OWN))
    h.do_GET()
    headers = _header_map(h.sent)
    assert headers["Content-Type"] == "text/event-stream"
    assert headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:8765"
    assert headers["Vary"] == "Origin"


def test_sse_logs_cross_origin_no_acao(monkeypatch):
    monkeypatch.delenv("ARI_GUI_CORS_ANY", raising=False)
    monkeypatch.setattr(routes, "_api_logs_sse", lambda wfile: None)
    h = _make_handler(path="/api/logs", headers=dict(_CROSS))
    h.do_GET()
    headers = _header_map(h.sent)
    assert headers["Content-Type"] == "text/event-stream"
    assert "Access-Control-Allow-Origin" not in headers


def test_sse_v1_events_cross_origin_no_acao(monkeypatch):
    monkeypatch.delenv("ARI_GUI_CORS_ANY", raising=False)
    from ari.viz.v1 import events as _v1_events
    monkeypatch.setattr(_v1_events, "stream_events", lambda wfile, **kw: None)
    h = _make_handler(path="/api/v1/events/stream", headers=dict(_CROSS))
    h.do_GET()
    headers = _header_map(h.sent)
    assert headers["Content-Type"] == "text/event-stream"
    assert "Access-Control-Allow-Origin" not in headers


def test_sse_v1_events_same_origin_echo(monkeypatch):
    monkeypatch.delenv("ARI_GUI_CORS_ANY", raising=False)
    from ari.viz.v1 import events as _v1_events
    monkeypatch.setattr(_v1_events, "stream_events", lambda wfile, **kw: None)
    h = _make_handler(path="/api/v1/events/stream", headers=dict(_OWN))
    h.do_GET()
    assert _header_map(h.sent)["Access-Control-Allow-Origin"] == "http://127.0.0.1:8765"
