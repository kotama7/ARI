"""Remote-mode bearer-token authentication for the ARI GUI (MN-8, ADR-13).

Trust model (gui_refresh task 09 Wave 5b, RR-P0-3 auth sub-scope,
plan 09 §Deployment trust modes, ADR-05 decision 5 -> ADR-13)
----------------------------------------------------------------
* **Local mode** (the default: ``ARI_GUI_BIND`` unset/blank, so the bind
  resolves to loopback only): **no authentication** — the loopback bind
  (MN-4) plus same-origin CORS is the protection, and the default local
  experience stays exactly as before.
* **Remote mode** (``ARI_GUI_BIND`` names a non-loopback host, including
  the wildcard forms ``'::'`` / ``'0.0.0.0'`` / ``''``): **every** HTTP
  request except the ``/health/*`` prefix must carry
  ``Authorization: Bearer <token>`` where the token is ``ARI_GUI_TOKEN``.
  If ``ARI_GUI_TOKEN`` is unset while remote-bound the server generates a
  random 32-hex token at startup and prints it **once** to stderr
  (``server.py`` banner) — fail-secure: a remote bind is never silently
  unauthenticated. Failures answer 401 with a typed JSON body; the
  comparison is constant-time (``hmac.compare_digest``); the token is
  never written to logs (``viz_access.jsonl`` paths are redacted via
  :func:`redact_token_in_path`).
* **SSE + WebSocket**: browsers cannot set headers on ``EventSource`` or
  the WS handshake, so both also accept the same token as the ``token``
  query parameter (accepted tradeoff, recorded in ADR-13; the access-log
  redaction above covers the query form).
* No cookies are used, so there is no CSRF surface; sessions, logout and
  multi-user are deferred to a future multi-tenant ADR (ADR-13
  consequences — single-operator research tool).

``ARI_GUI_AUTH`` (env kill-switch, ADR-07 register):

* owner: gui_refresh task 09 (security, performance, and operations);
* default: unset/on — the remote token gate is enforced whenever the
  bind is non-loopback (loopback binds are always unauthenticated);
* rollback: ``ARI_GUI_AUTH=0`` (or ``false``) disables the gate and
  restores the pre-MN-8 unauthenticated remote bind — the documented
  escape hatch for trusted-network topologies that terminate their own
  auth (e.g. an authenticating reverse proxy);
* removal gate: none — fail-secure remote auth is permanent policy
  (ADR-13); the switch only exists as the ADR-07 rollback lever.

The three policy helpers (:func:`is_remote_bind`, :func:`resolve_token`,
:func:`check_authorization`) are pure so ``tests/test_gui_remote_auth.py``
covers the matrix without sockets. The module-level active-token cache is
resolved once per process (``init_auth`` — called by ``server.py`` at
startup so the generated-token banner prints exactly once; request-path
readers use :func:`active_token`).
"""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import threading
import urllib.parse
from typing import Iterable, Mapping


# ──────────────────────────────────────────────────────────────────────
# Pure policy helpers
# ──────────────────────────────────────────────────────────────────────

def is_remote_bind(hosts: Iterable[str]) -> bool:
    """True when any bound host exposes a non-loopback interface.

    ``hosts`` is the ``server.resolve_bind_hosts`` output: the loopback
    default ``["127.0.0.1", "::1"]`` or a single explicit override. The
    wildcard forms (``""``, ``"::"``, ``"0.0.0.0"``) and any LAN address
    are remote; ``localhost``/``127.x.y.z``/``::1`` (bracketed or not)
    are loopback. Pure — no DNS, no sockets.
    """
    for raw in hosts:
        host = (raw or "").strip().lower()
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        if host == "localhost" or host == "::1":
            continue
        if host.startswith("127."):
            continue
        return True
    return False


def resolve_token(env: Mapping[str, str], remote: bool) -> "tuple[str | None, bool]":
    """Resolve the active auth token -> ``(token | None, generated)``.

    * local bind (``remote=False``) -> ``(None, False)``: no auth, the
      default loopback experience is unchanged (even when ``ARI_GUI_TOKEN``
      happens to be exported — local mode is defined by the bind alone);
    * ``ARI_GUI_AUTH=0|false`` kill-switch -> ``(None, False)``;
    * remote + ``ARI_GUI_TOKEN`` set -> ``(that token, False)``;
    * remote + unset -> ``(random 32-hex token, True)`` — fail-secure:
      never silently unauthenticated on a remote bind. The caller
      (``server.py``) is responsible for printing the one-time banner.
    """
    if not remote:
        return None, False
    if (env.get("ARI_GUI_AUTH") or "").strip().lower() in ("0", "false"):
        return None, False
    configured = (env.get("ARI_GUI_TOKEN") or "").strip()
    if configured:
        return configured, False
    return secrets.token_hex(16), True


def check_authorization(headers, query, token: "str | None") -> bool:
    """True when the request presents the active token.

    ``headers`` is any mapping with ``.get`` (the stdlib handler's
    ``self.headers``, the websockets handshake headers, or a plain dict);
    ``query`` is a ``urllib.parse.parse_qs``-style mapping (list values)
    or a plain str->str dict. Accepted credentials:

    * ``Authorization: Bearer <token>`` (scheme case-insensitive);
    * ``token=<token>`` query parameter (SSE ``EventSource`` and the WS
      handshake cannot set headers — ADR-13 tradeoff).

    Comparison is constant-time (``hmac.compare_digest``). With no active
    token (``None``/empty — local mode) every request passes.
    """
    if not token:
        return True
    candidates: "list[str]" = []
    header_val = None
    if headers is not None:
        try:
            header_val = headers.get("Authorization")
        except Exception:
            header_val = None
    if header_val:
        scheme, _, credential = str(header_val).strip().partition(" ")
        credential = credential.strip()
        if scheme.lower() == "bearer" and credential:
            candidates.append(credential)
    if query:
        raw = None
        try:
            raw = query.get("token")
        except Exception:
            raw = None
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else None
        if isinstance(raw, str) and raw:
            candidates.append(raw)
    expected = token.encode("utf-8")
    matched = False
    for candidate in candidates:
        if hmac.compare_digest(candidate.encode("utf-8"), expected):
            matched = True
    return matched


# Token value riding in a query string (SSE/WS form) must never reach the
# access log: viz_access.jsonl records the request path verbatim otherwise.
_TOKEN_QUERY_RE = re.compile(r"(?i)([?&]token=)[^&#]*")


def redact_token_in_path(path: str) -> str:
    """Replace any ``token=`` query value in ``path`` with ``***``."""
    return _TOKEN_QUERY_RE.sub(r"\1***", path or "")


# ──────────────────────────────────────────────────────────────────────
# Process-wide active-token cache
# ──────────────────────────────────────────────────────────────────────

_state_lock = threading.Lock()
# (token | None, generated) once resolved; None = not yet initialized.
_ACTIVE: "tuple[str | None, bool] | None" = None


def init_auth(environ: "Mapping[str, str] | None" = None) -> "tuple[str | None, bool]":
    """Resolve and cache the active token from the environment.

    ``server.py`` calls this once at startup (before binding) so a
    generated token exists — and is printed — exactly once per process.
    Returns ``(token | None, generated)``.
    """
    global _ACTIVE
    env = os.environ if environ is None else environ
    # Lazy import: server.py imports routes.py which imports this module,
    # so a top-level import back into server would be circular.
    from .server import resolve_bind_hosts
    remote = is_remote_bind(resolve_bind_hosts(env.get("ARI_GUI_BIND")))
    with _state_lock:
        _ACTIVE = resolve_token(env, remote)
        return _ACTIVE


def active_token() -> "str | None":
    """The token requests must present, or None when auth is off.

    Falls back to :func:`init_auth` on first use so socketless test
    handlers (and any non-``server.py`` embedding) still get the
    fail-secure resolution.
    """
    with _state_lock:
        cached = _ACTIVE
    if cached is None:
        return init_auth()[0]
    return cached[0]


def _reset_for_tests() -> None:
    """Drop the cached token so tests can re-resolve under a patched env."""
    global _ACTIVE
    with _state_lock:
        _ACTIVE = None


# ──────────────────────────────────────────────────────────────────────
# HTTP handler gate (called by routes._Handler at the top of do_*)
# ──────────────────────────────────────────────────────────────────────

def gate_request(handler) -> bool:
    """The MN-8 single gate: True = proceed, False = a 401 was written.

    Runs before any dispatch or body read in every ``do_GET/do_POST/
    do_PUT/do_PATCH/do_DELETE``. No-op (True) when no token is active —
    the default loopback bind or the ``ARI_GUI_AUTH=0`` kill-switch. The
    ``/health`` / ``/health/*`` prefix stays unauthenticated (liveness
    probes), and the token may arrive as a Bearer header or (for the
    EventSource-consumed SSE streams) the ``token`` query parameter.
    """
    token = active_token()
    if token is None:
        return True
    parsed = urllib.parse.urlsplit(handler.path)
    if parsed.path == "/health" or parsed.path.startswith("/health/"):
        return True
    query = urllib.parse.parse_qs(parsed.query)
    if check_authorization(handler.headers, query, token):
        return True
    _reject_unauthorized(handler)
    return False


def _reject_unauthorized(handler) -> None:
    """401 + typed JSON body; closes the connection so an unread request
    body cannot desync HTTP/1.1 keep-alive. The token is never echoed."""
    body = json.dumps({
        "error": {
            "code": "unauthorized",
            "message": (
                "authentication required: this GUI is bound to a "
                "non-loopback address (remote mode, MN-8/ADR-13). Send "
                "'Authorization: Bearer <ARI_GUI_TOKEN>' (SSE/WebSocket: "
                "'?token=<ARI_GUI_TOKEN>')."
            ),
        },
    }, ensure_ascii=False).encode()
    handler.send_response(401)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("WWW-Authenticate", 'Bearer realm="ari-gui"')
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Connection", "close")
    handler.close_connection = True
    handler.end_headers()
    handler.wfile.write(body)
