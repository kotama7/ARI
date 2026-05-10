"""WebSocket handler extracted from viz/server.py (Phase 3B).

Single async function: streams the latest tree state on connect and
keeps the connection open until the client closes it.  Disconnects are
swallowed (normal lifecycle) so the server thread doesn't churn on
spurious tracebacks.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import websockets

from . import state as _st
from .api_state import _load_nodes_tree


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
