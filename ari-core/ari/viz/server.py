"""ARI Experiment Tree Visualizer — WebSocket + HTTP server.

Usage:
    python -m ari.viz.server --checkpoint ./logs/my_ckpt/ [--port 8765]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Set

try:
    import websockets
    from websockets.server import serve as ws_serve
except ImportError:
    raise SystemExit("websockets package required: pip install websockets")

# ──────────────────────────────────────────────
# Shared state
# ──────────────────────────────────────────────
_clients: Set = set()
_loop: asyncio.AbstractEventLoop | None = None
_last_mtime: float = 0.0
_checkpoint_dir: Path | None = None
_port: int = 8765


def _load_nodes_tree() -> dict | None:
    if _checkpoint_dir is None:
        return None
    p = _checkpoint_dir / "nodes_tree.json"
    if not p.exists():
        # fallback: try tree.json (internal format)
        p = _checkpoint_dir / "tree.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _broadcast(data: dict) -> None:
    if not _clients or _loop is None:
        return
    msg = json.dumps({"type": "update", "data": data,
                       "timestamp": datetime.now(timezone.utc).isoformat()})
    asyncio.run_coroutine_threadsafe(_do_broadcast(msg), _loop)


async def _do_broadcast(msg: str) -> None:
    dead = set()
    for ws in list(_clients):
        try:
            await ws.send(msg)
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)


# ──────────────────────────────────────────────
# File watcher (polling thread)
# ──────────────────────────────────────────────
def _watcher_thread() -> None:
    global _last_mtime
    while True:
        time.sleep(2)
        if _checkpoint_dir is None:
            continue
        for fname in ("nodes_tree.json", "tree.json"):
            p = _checkpoint_dir / fname
            if p.exists():
                try:
                    mtime = p.stat().st_mtime
                    if mtime != _last_mtime:
                        _last_mtime = mtime
                        data = _load_nodes_tree()
                        if data:
                            _broadcast(data)
                except Exception:
                    pass
                break


# ──────────────────────────────────────────────
# WebSocket handler
# ──────────────────────────────────────────────
async def _ws_handler(websocket) -> None:
    _clients.add(websocket)
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
    finally:
        _clients.discard(websocket)


# ──────────────────────────────────────────────
# HTTP server (serves dashboard.html)
# ──────────────────────────────────────────────
DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # suppress request logs
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = DASHBOARD_PATH.read_bytes() if DASHBOARD_PATH.exists() else b"<h1>dashboard.html not found</h1>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
        elif self.path.startswith("/memory/"):
            node_id = self.path[len("/memory/"):]
            try:
                import urllib.parse, pathlib as pathlib
                node_id = urllib.parse.unquote(node_id)
                store = pathlib.Path("~/.ari/memory_store.jsonl").expanduser()
                entries = []
                if store.exists():
                    for line in store.read_text().splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            e = json.loads(line)
                            # Match by exact ID or by partial suffix (short IDs in dashboard)
                            _eid = e.get("node_id", "")
                            if _eid == node_id or _eid.endswith(node_id) or node_id.endswith(_eid):
                                entries.append({"text": e.get("text",""), "metadata": e.get("metadata",{})})
                        except Exception:
                            pass
                payload = json.dumps({"entries": entries}, ensure_ascii=False).encode()
            except Exception as ex:
                payload = json.dumps({"entries": [], "error": str(ex)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)
        elif self.path == "/state":
            data = _load_nodes_tree() or {}
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/codefile"):
            # Serve file content for artifact file paths
            import urllib.parse
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            fpath = qs.get("path", [""])[0]
            try:
                import pathlib
                p = pathlib.Path(fpath)
                if p.exists() and p.is_file() and p.stat().st_size < 2_000_000:
                    body = p.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()
            except Exception:
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()


def _http_thread(port: int) -> None:
    srv = ThreadingHTTPServer(("", port), _Handler)
    srv.serve_forever()


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
async def _main(checkpoint: Path, port: int) -> None:
    global _loop, _checkpoint_dir, _port
    _checkpoint_dir = checkpoint
    _port = port
    _loop = asyncio.get_running_loop()

    # Start file watcher
    t = threading.Thread(target=_watcher_thread, daemon=True)
    t.start()

    # Start HTTP server
    ht = threading.Thread(target=_http_thread, args=(port,), daemon=True)
    ht.start()

    ws_port = port + 1
    print(f"\n  ⚗️  ARI Viz running at \033[1mhttp://localhost:{port}/\033[0m")
    print(f"  📁  Checkpoint: {checkpoint}")
    print(f"  🔌  WebSocket:  ws://localhost:{ws_port}/ws")
    print("  Ctrl+C to stop\n")

    async with ws_serve(_ws_handler, "", ws_port):
        await asyncio.Future()  # run forever


def main() -> None:
    ap = argparse.ArgumentParser(description="ARI Experiment Tree Visualizer")
    ap.add_argument("--checkpoint", required=True, type=Path,
                    help="Path to checkpoint directory")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    if not args.checkpoint.exists():
        raise SystemExit(f"Checkpoint not found: {args.checkpoint}")

    try:
        asyncio.run(_main(args.checkpoint, args.port))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
