from __future__ import annotations
"""ARI viz: api_ollama — GPU/model detection and Ollama proxy."""

import json
import logging
import os

from . import state as _st

log = logging.getLogger(__name__)
from .api_settings import _api_get_settings


def _api_ollama_resources() -> dict:
    """Detect available GPUs and Ollama models for resource selection."""
    import subprocess as sp
    gpus = []
    try:
        out = sp.check_output(["nvidia-smi","--query-gpu=index,name,memory.total","--format=csv,noheader"],
                               stderr=sp.DEVNULL, timeout=5, text=True)
        for line in out.strip().splitlines():
            parts = line.split(",")
            if len(parts) >= 3:
                gpus.append({"index": parts[0].strip(), "name": parts[1].strip(), "memory": parts[2].strip()})
    except Exception:
        log.debug("nvidia-smi not available", exc_info=True)
    # Try Ollama models
    models = []
    try:
        import urllib.request
        base_url = os.environ.get("OLLAMA_BASE_URL","http://localhost:11434")
        resp = urllib.request.urlopen(f"{base_url}/api/tags", timeout=3)
        data = json.loads(resp.read())
        models = [m["name"] for m in data.get("models",[])]
    except Exception:
        log.debug("ollama models list failed", exc_info=True)
    # Always include Auto and CPU options first
    result_gpus = [{"index": "auto", "name": "Auto", "memory": ""}, {"index": "cpu", "name": "CPU only", "memory": ""}] + gpus
    return {"gpus": result_gpus, "models": models, "has_gpu": len(gpus)>0}



def _ollama_proxy(handler):
    """Forward /api/ollama/<path> to the configured ollama_host (streaming passthrough)."""
    import http.client as _hc
    import urllib.parse as _up
    saved = _api_get_settings()
    base = saved.get("ollama_host", "http://localhost:11434").rstrip("/")
    path = handler.path[len("/api/ollama"):]
    length = int(handler.headers.get("Content-Length", 0) or 0)
    body = handler.rfile.read(length) if length > 0 else b""
    method = handler.command
    parsed = _up.urlparse(base)
    host = parsed.hostname or "localhost"
    port = parsed.port or 11434
    try:
        conn = _hc.HTTPConnection(host, port, timeout=600)
        conn.request(method, path, body=body or None, headers={
            "Content-Type": handler.headers.get("Content-Type", "application/json"),
            "Content-Length": str(len(body)),
        })
        resp = conn.getresponse()
        handler.send_response(resp.status)
        ct = resp.getheader("Content-Type", "application/json")
        handler.send_header("Content-Type", ct)
        handler.send_header("Transfer-Encoding", "chunked")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            handler.wfile.write(f"{len(chunk):X}\r\n".encode())
            handler.wfile.write(chunk)
            handler.wfile.write(b"\r\n")
            handler.wfile.flush()
        handler.wfile.write(b"0\r\n\r\n")
        handler.wfile.flush()
        conn.close()
    except Exception as e:
        try:
            msg = f'{{"error": "{e}"}}'.encode()
            handler.send_response(502)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(msg)))
            handler.end_headers()
            handler.wfile.write(msg)
        except Exception:
            log.debug("failed to send proxy error response", exc_info=True)

