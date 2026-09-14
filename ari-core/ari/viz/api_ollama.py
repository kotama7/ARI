from __future__ import annotations
"""ARI viz: api_ollama — GPU/model detection and Ollama proxy.

Proxy policy (gui_refresh task 09, RR-P0-7, MN-5)
-------------------------------------------------
``/api/ollama/<path>`` only relays the allowlisted Ollama API paths
(:data:`OLLAMA_PROXY_ALLOWED_PATHS`) and only when a target is explicitly
configured (settings ``ollama_host`` or the ``OLLAMA_HOST`` env var) or the
effective llm backend is ``ollama`` (which keeps the legacy implicit
``http://localhost:11434`` local dev default). Everything else is refused
with 403 before any upstream connection is opened. There is deliberately no
env kill-switch (ADR-07): the rollback for a refused-but-wanted relay is to
configure the target (``ollama_host`` in Settings or ``OLLAMA_HOST``), which
is itself the explicit opt-in the gate asks for. See migration note MN-5.
"""

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



# MN-5 (RR-P0-7): only the documented Ollama API endpoints are relayed.
# The React frontend itself never calls the proxy (it uses
# GET /api/ollama-resources, verified by grep — services/api/resources.ts is
# the only /api/ollama* caller); this allowlist covers exactly the standard
# Ollama surface the legacy dashboard/ops flows and tests exercised: model
# list/metadata (tags/show), generation/chat, and loaded-model status (ps).
# Anything else — pull/push/create/copy/delete, embeddings, arbitrary
# paths — is refused with 403.
OLLAMA_PROXY_ALLOWED_PATHS = frozenset({
    "/api/tags",
    "/api/show",
    "/api/generate",
    "/api/chat",
    "/api/ps",
})


def _explicit_ollama_host() -> str:
    """Explicitly configured Ollama target, or "" when none is configured.

    Reads the *raw* project settings file (not ``_api_get_settings``, whose
    defaults fold in an implicit ``http://localhost:11434``) plus the
    ``OLLAMA_HOST`` env var, so "configured" genuinely means a user-supplied
    value (settings card or env) — never the legacy implicit default.
    """
    host = ""
    sp = _st._settings_path
    if sp is not None:
        try:
            if sp.exists():
                host = (json.loads(sp.read_text()).get("ollama_host") or "").strip()
        except Exception:
            host = ""
    return host or os.environ.get("OLLAMA_HOST", "").strip()


def _ollama_proxy_refusal(proxy_path: str) -> "str | None":
    """Reason to refuse proxying *proxy_path* with 403, or None when allowed.

    MN-5 (RR-P0-7) gate, checked before any upstream connection:

    * the forwarded path (query string ignored) must be in
      :data:`OLLAMA_PROXY_ALLOWED_PATHS`;
    * a target must be *explicitly* configured — settings ``ollama_host`` or
      the ``OLLAMA_HOST`` env var (covers cli-shim-with-ollama setups) — OR
      the effective llm backend must be ``ollama``, in which case the legacy
      implicit ``http://localhost:11434`` default still applies (preserves
      the local dev flow where the backend *is* ollama). A non-ollama
      backend with no configured host gets 403, never an implicit
      localhost relay.

    Pure function — unit-tested in ``tests/test_gui_path_proxy_hardening.py``.
    """
    import urllib.parse as _up
    if _up.urlparse(proxy_path).path not in OLLAMA_PROXY_ALLOWED_PATHS:
        return f"ollama proxy path not allowed: {proxy_path.split('?')[0]}"
    if _explicit_ollama_host():
        return None
    provider = (_api_get_settings().get("llm_provider") or "").strip().lower()
    if provider == "ollama":
        return None
    return (
        "ollama proxy refused: no ollama_host configured (settings or "
        "OLLAMA_HOST env) and the llm backend is not ollama"
    )


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
    refusal = _ollama_proxy_refusal(path)
    if refusal is not None:
        # MN-5 (RR-P0-7): refuse before opening any upstream connection.
        # The request body was already drained above so HTTP/1.1 keep-alive
        # connections stay parseable.
        msg = json.dumps({"error": refusal}).encode()
        handler.send_response(403)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(msg)))
        handler._send_cors_headers()
        handler.end_headers()
        handler.wfile.write(msg)
        return
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
        # MN-4 (RR-P0-3): same-origin CORS via the shared handler helper
        # (was an unconditional wildcard; see routes.py module docstring).
        handler._send_cors_headers()
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

