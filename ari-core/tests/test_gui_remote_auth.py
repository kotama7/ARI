"""gui_refresh Wave 5b (task 09) — RR-P0-3 auth sub-scope / MN-8 / ADR-13:
remote-mode bearer-token authentication.

Covers:

* ``ari.viz.auth.is_remote_bind`` — pure bind classification (loopback
  default vs wildcard/LAN overrides), no sockets;
* ``ari.viz.auth.resolve_token`` — local => no auth (even with a token
  exported), remote + ``ARI_GUI_TOKEN`` => that token, remote + unset =>
  generated 32-hex fail-secure token, ``ARI_GUI_AUTH=0`` kill-switch;
* ``ari.viz.auth.check_authorization`` — Bearer header / ``token=`` query
  acceptance matrix, constant-time comparison (``hmac.compare_digest``
  referenced by source);
* ``_Handler`` gate — loopback default unauthenticated, remote 401
  (typed body + ``WWW-Authenticate``, token not echoed) on missing/wrong
  credentials across GET/POST/PUT/PATCH/DELETE, 200 with the token,
  ``/health/*`` exemption, SSE query-token acceptance on the
  EventSource-consumed streams (``/api/v1/events/stream``, paperbench
  run logs; the fetch-consumed legacy ``/api/logs`` uses the header);
* ``ari.viz.websocket._ws_process_request`` — WS handshake 401 vs
  query-token/header acceptance;
* token hygiene — ``viz_access.jsonl`` path redaction (``token=***``)
  and the one-time generated-token stderr banner (``server.py``).

Socketless handlers (``_Handler.__new__``) everywhere, mirroring
``test_gui_bind_cors.py``.
"""

from __future__ import annotations

import asyncio
import inspect
import io
import json
import re
import time

import pytest

from ari.viz import auth
from ari.viz import routes
from ari.viz import server
from ari.viz import state as _st
from ari.viz.routes import _Handler
from ari.viz.websocket import _ws_process_request


TOKEN = "wave5b-remote-token-0123456789abcdef"


@pytest.fixture(autouse=True)
def _clean_auth(monkeypatch):
    """Pristine auth env + cache before and after every test."""
    monkeypatch.delenv("ARI_GUI_BIND", raising=False)
    monkeypatch.delenv("ARI_GUI_TOKEN", raising=False)
    monkeypatch.delenv("ARI_GUI_AUTH", raising=False)
    auth._reset_for_tests()
    yield
    auth._reset_for_tests()


def _activate_remote(monkeypatch, token: "str | None" = TOKEN):
    """Point the resolver at a remote bind (optionally with a fixed token)."""
    monkeypatch.setenv("ARI_GUI_BIND", "0.0.0.0")
    if token is not None:
        monkeypatch.setenv("ARI_GUI_TOKEN", token)
    return auth.init_auth()


def _make_handler(path: str = "/api/capabilities", headers: dict | None = None):
    h = _Handler.__new__(_Handler)
    h.path = path
    h.headers = headers if headers is not None else {"Host": "192.0.2.7:8765"}
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


# ──────────────────────────────────────────────────────────────────────
# is_remote_bind (pure)
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("hosts,expected", [
    (["127.0.0.1", "::1"], False),      # loopback default (ARI_GUI_BIND unset)
    (["127.0.0.1"], False),
    (["::1"], False),
    (["[::1]"], False),
    (["localhost"], False),
    (["127.0.0.53"], False),            # any 127/8 alias
    (["::"], True),                     # legacy all-interfaces dual-stack
    (["0.0.0.0"], True),                # IPv4 wildcard
    ([""], True),                       # pre-MN-4 wildcard form
    (["192.168.10.5"], True),           # explicit LAN interface
    (["fe80::1"], True),
    ([], False),                        # nothing bound => nothing remote
])
def test_is_remote_bind_matrix(hosts, expected):
    assert auth.is_remote_bind(hosts) is expected


# ──────────────────────────────────────────────────────────────────────
# resolve_token (pure given env mapping)
# ──────────────────────────────────────────────────────────────────────

def test_resolve_token_local_mode_is_no_auth_even_with_token():
    assert auth.resolve_token({}, remote=False) == (None, False)
    # Local mode is defined by the bind alone — an exported token is inert.
    assert auth.resolve_token({"ARI_GUI_TOKEN": TOKEN}, remote=False) == (None, False)


def test_resolve_token_remote_uses_configured_token():
    assert auth.resolve_token({"ARI_GUI_TOKEN": f"  {TOKEN}  "}, remote=True) == (TOKEN, False)


def test_resolve_token_remote_without_token_generates_32_hex():
    token, generated = auth.resolve_token({}, remote=True)
    assert generated is True
    assert re.fullmatch(r"[0-9a-f]{32}", token)
    # fail-secure: two resolutions never share a generated token
    other, _ = auth.resolve_token({}, remote=True)
    assert other != token


@pytest.mark.parametrize("off", ["0", "false", " FALSE "])
def test_resolve_token_kill_switch(off):
    env = {"ARI_GUI_TOKEN": TOKEN, "ARI_GUI_AUTH": off}
    assert auth.resolve_token(env, remote=True) == (None, False)


# ──────────────────────────────────────────────────────────────────────
# check_authorization (pure; constant-time)
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("headers,query,expected", [
    ({"Authorization": f"Bearer {TOKEN}"}, {}, True),
    ({"Authorization": f"bearer {TOKEN}"}, {}, True),          # scheme case
    ({}, {"token": [TOKEN]}, True),                            # parse_qs style
    ({}, {"token": TOKEN}, True),                              # plain dict
    ({"Authorization": "Bearer wrong"}, {}, False),
    ({"Authorization": TOKEN}, {}, False),                     # missing scheme
    ({"Authorization": "Basic dXNlcg=="}, {}, False),          # wrong scheme
    ({}, {"token": ["wrong"]}, False),
    ({}, {}, False),
    (None, None, False),
    # either credential slot is sufficient
    ({"Authorization": "Bearer wrong"}, {"token": [TOKEN]}, True),
])
def test_check_authorization_matrix(headers, query, expected):
    assert auth.check_authorization(headers, query, TOKEN) is expected


def test_check_authorization_no_active_token_passes_everything():
    assert auth.check_authorization({}, {}, None) is True
    assert auth.check_authorization(None, None, "") is True


def test_check_authorization_uses_constant_time_compare():
    """MN-8 requires hmac.compare_digest — pin it against refactors."""
    src = inspect.getsource(auth.check_authorization)
    assert "hmac.compare_digest" in src


# ──────────────────────────────────────────────────────────────────────
# Handler gate — loopback default (no auth)
# ──────────────────────────────────────────────────────────────────────

def test_loopback_default_requires_no_auth():
    h = _make_handler(path="/api/capabilities", headers={"Host": "127.0.0.1:8765"})
    h.do_GET()
    assert _statuses(h) == [200]
    assert json.loads(h.wfile.getvalue())["gui_v2"] in (True, False)


def test_loopback_default_post_requires_no_auth(monkeypatch):
    monkeypatch.setattr(routes, "_api_save_settings", lambda body: {"ok": True})
    h = _make_handler(path="/api/settings", headers={"Host": "127.0.0.1:8765", "Content-Length": "2"})
    h.rfile = io.BytesIO(b"{}")
    h.do_POST()
    assert _statuses(h) == [200]


# ──────────────────────────────────────────────────────────────────────
# Handler gate — remote mode enforcement
# ──────────────────────────────────────────────────────────────────────

def test_remote_get_without_token_is_401_typed_body(monkeypatch):
    _activate_remote(monkeypatch)
    h = _make_handler()
    h.do_GET()
    assert _statuses(h) == [401]
    headers = _header_map(h.sent)
    assert headers["WWW-Authenticate"] == 'Bearer realm="ari-gui"'
    assert headers["Connection"] == "close"
    body = json.loads(h.wfile.getvalue())
    assert body["error"]["code"] == "unauthorized"
    assert TOKEN not in json.dumps(body)  # the 401 must never echo the token


def test_remote_get_with_wrong_token_is_401(monkeypatch):
    _activate_remote(monkeypatch)
    h = _make_handler(headers={"Host": "x", "Authorization": "Bearer nope"})
    h.do_GET()
    assert _statuses(h) == [401]


def test_remote_get_with_token_succeeds(monkeypatch):
    _activate_remote(monkeypatch)
    h = _make_handler(headers={"Host": "x", "Authorization": f"Bearer {TOKEN}"})
    h.do_GET()
    assert _statuses(h) == [200]
    assert "gui_v2" in json.loads(h.wfile.getvalue())


@pytest.mark.parametrize("method,path", [
    ("do_POST", "/api/settings"),
    ("do_PUT", "/api/v1/secrets/OPENAI_API_KEY"),
    ("do_PATCH", "/api/v1/config/project"),
    ("do_DELETE", "/api/v1/config/run-drafts/d1"),
])
def test_remote_mutations_without_token_are_401(monkeypatch, method, path):
    _activate_remote(monkeypatch)
    h = _make_handler(path=path, headers={"Host": "x", "Content-Length": "2"})
    h.rfile = io.BytesIO(b"{}")
    getattr(h, method)()
    assert _statuses(h) == [401]


def test_remote_health_prefix_is_exempt(monkeypatch):
    _activate_remote(monkeypatch)
    h = _make_handler(path="/health/live", headers={"Host": "x"})
    h.do_GET()
    assert 401 not in _statuses(h)
    assert 200 in _statuses(h)  # SPA fallback serves the liveness probe


def test_remote_generated_token_is_enforced(monkeypatch):
    """Remote bind with no ARI_GUI_TOKEN: fail-secure generated token."""
    monkeypatch.setenv("ARI_GUI_BIND", "::")
    token, generated = auth.init_auth()
    assert generated is True and re.fullmatch(r"[0-9a-f]{32}", token)
    assert auth.active_token() == token
    refused = _make_handler()
    refused.do_GET()
    assert _statuses(refused) == [401]
    granted = _make_handler(headers={"Host": "x", "Authorization": f"Bearer {token}"})
    granted.do_GET()
    assert _statuses(granted) == [200]


def test_kill_switch_restores_unauthenticated_remote(monkeypatch):
    monkeypatch.setenv("ARI_GUI_BIND", "0.0.0.0")
    monkeypatch.setenv("ARI_GUI_TOKEN", TOKEN)
    monkeypatch.setenv("ARI_GUI_AUTH", "0")
    assert auth.init_auth() == (None, False)
    h = _make_handler()
    h.do_GET()
    assert _statuses(h) == [200]


# ──────────────────────────────────────────────────────────────────────
# SSE — query-token acceptance (EventSource cannot set headers)
# ──────────────────────────────────────────────────────────────────────

def test_legacy_logs_stream_uses_bearer_header(monkeypatch):
    """/api/logs is fetch-consumed (headers available) — header auth, and
    the exact-match dispatch (no query form) is unchanged by MN-8."""
    _activate_remote(monkeypatch)
    monkeypatch.setattr(routes, "_api_logs_sse", lambda wfile: None)
    refused = _make_handler(path="/api/logs", headers={"Host": "x"})
    refused.do_GET()
    assert _statuses(refused) == [401]
    granted = _make_handler(
        path="/api/logs",
        headers={"Host": "x", "Authorization": f"Bearer {TOKEN}"},
    )
    granted.do_GET()
    assert _statuses(granted) == [200]
    assert _header_map(granted.sent)["Content-Type"] == "text/event-stream"


def test_sse_paperbench_logs_accepts_query_token(monkeypatch):
    """EventSource consumer (ResultsView) — query token passes the gate;
    the stubbed missing job then 404s (proof the request got past auth)."""
    _activate_remote(monkeypatch)
    from ari.viz import api_paperbench as _pb
    monkeypatch.setattr(_pb, "_job_snapshot", lambda jid: None)
    h = _make_handler(path=f"/api/paperbench/run/j1/logs?token={TOKEN}", headers={"Host": "x"})
    h.do_GET()
    assert _statuses(h) == [404]

    wrong = _make_handler(path="/api/paperbench/run/j1/logs?token=wrong", headers={"Host": "x"})
    wrong.do_GET()
    assert _statuses(wrong) == [401]


def test_sse_v1_events_accepts_query_token(monkeypatch):
    _activate_remote(monkeypatch)
    from ari.viz.v1 import events as _v1_events
    monkeypatch.setattr(_v1_events, "stream_events", lambda wfile, **kw: None)
    h = _make_handler(path=f"/api/v1/events/stream?token={TOKEN}", headers={"Host": "x"})
    h.do_GET()
    assert _statuses(h) == [200]
    assert _header_map(h.sent)["Content-Type"] == "text/event-stream"


# ──────────────────────────────────────────────────────────────────────
# WebSocket handshake (ws_serve process_request)
# ──────────────────────────────────────────────────────────────────────

def test_ws_handshake_loopback_is_open():
    assert asyncio.run(_ws_process_request("/", {})) is None


def test_ws_handshake_remote_requires_token(monkeypatch):
    _activate_remote(monkeypatch)
    refused = asyncio.run(_ws_process_request("/", {}))
    assert refused is not None
    status, _headers, body = refused
    assert int(status) == 401
    assert json.loads(body)["error"]["code"] == "unauthorized"


def test_ws_handshake_remote_accepts_query_token(monkeypatch):
    _activate_remote(monkeypatch)
    assert asyncio.run(_ws_process_request(f"/?token={TOKEN}", {})) is None


def test_ws_handshake_remote_accepts_bearer_header(monkeypatch):
    _activate_remote(monkeypatch)
    result = asyncio.run(
        _ws_process_request("/", {"Authorization": f"Bearer {TOKEN}"})
    )
    assert result is None


# ──────────────────────────────────────────────────────────────────────
# Token hygiene — access log redaction + one-time banner
# ──────────────────────────────────────────────────────────────────────

def test_access_log_redacts_query_token(monkeypatch, tmp_path):
    _activate_remote(monkeypatch)
    monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path)
    h = _make_handler(path=f"/api/v1/events/stream?token={TOKEN}", headers={"Host": "x"})
    h.command = "GET"
    h.client_address = ("192.0.2.9", 55555)
    h._req_start = time.monotonic()
    h.log_request(200)
    logged = (tmp_path / "viz_access.jsonl").read_text(encoding="utf-8")
    assert TOKEN not in logged
    assert "token=***" in logged


def test_generated_token_banner_prints_once_to_stderr(capsys):
    token = "cafe" * 8
    server._print_generated_token_banner(token)
    captured = capsys.readouterr()
    assert f"ARI_GUI_TOKEN={token}" in captured.err
    assert "ONCE" in captured.err
    assert token not in captured.out  # stderr only
