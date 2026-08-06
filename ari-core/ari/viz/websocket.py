"""WebSocket handler extracted from viz/server.py (Phase 3B).

Single async function: streams the latest tree state on connect and
keeps the connection open until the client closes it.  Disconnects are
swallowed (normal lifecycle) so the server thread doesn't churn on
spurious tracebacks.

MN-8 (gui_refresh Wave 5b, ADR-13): when remote token auth is active
(``ari/viz/auth.py``), the handshake is gated by ``_ws_process_request``
— the browser WebSocket API cannot set headers, so the token rides the
``token`` query parameter of the ws URL (same accepted tradeoff as SSE).
``server.py`` passes it to ``ws_serve`` as ``process_request``.
"""

from __future__ import annotations

import http
import json
import urllib.parse
from datetime import datetime, timezone

import websockets

from . import auth as _auth
from . import state as _st
from .api_state import _load_nodes_tree


async def _ws_process_request(path, request_headers):
    """Reject the WS handshake with 401 unless the MN-8 token is presented.

    Legacy ``websockets`` ``process_request`` contract: return ``None`` to
    continue the handshake, or an ``(status, headers, body)`` tuple to
    short-circuit with a plain HTTP response. Accepts the token from the
    ``token`` query parameter (browser clients) or an
    ``Authorization: Bearer`` header (non-browser clients). No-op when no
    token is active (loopback default / ARI_GUI_AUTH=0 kill-switch).
    """
    token = _auth.active_token()
    if token is None:
        return None
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(path or "").query)
    if _auth.check_authorization(request_headers, query, token):
        return None
    body = json.dumps({
        "error": {
            "code": "unauthorized",
            "message": (
                "authentication required: pass '?token=<ARI_GUI_TOKEN>' on "
                "the WebSocket URL (remote mode, MN-8/ADR-13)"
            ),
        },
    }, ensure_ascii=False).encode()
    return (
        http.HTTPStatus.UNAUTHORIZED,
        [("Content-Type", "application/json")],
        body,
    )


async def _ws_handler(websocket) -> None:
    _st._clients.add(websocket)
    try:
        # Send current state on connect
        data = _load_nodes_tree()
        if data:
            await websocket.send(json.dumps({
                "type": "update", "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))
        async for _ in websocket:
            pass  # ignore incoming messages
    except websockets.exceptions.ConnectionClosed:
        # Normal client disconnect (close frame, keepalive timeout, tab closed).
        pass
    finally:
        _st._clients.discard(websocket)
