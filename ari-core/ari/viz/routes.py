"""HTTP request handler + access log (Phase 3B PR-3B-1).

Hosts the ``_Handler`` class (do_GET / do_POST dispatch) and the
``_write_access_log`` helper extracted from ``ari/viz/server.py``.
The dispatch chain inside ``do_GET`` / ``do_POST`` is preserved
verbatim so the HTTP routing order is byte-for-byte identical to
the pre-Phase-3B build.

CORS policy (gui_refresh task 09, RR-P0-3, MN-4)
------------------------------------------------
Responses are **same-origin only**: the request ``Origin`` header is
echoed back in ``Access-Control-Allow-Origin`` only when it matches the
server's own origin (the request ``Host`` header, or a loopback form
``localhost``/``127.0.0.1``/``[::1]`` on the server port). Cross-origin
requests get **no** ACAO header, so browsers refuse the response. The
pre-MN-4 behavior was an unconditional ``Access-Control-Allow-Origin: *``
on ``_json``, OPTIONS preflight, SSE streams, and the manual binary
responses (``/state`` and ``GET /api/gpu-monitor`` were historically
ACAO-less and stay that way).

``ARI_GUI_CORS_ANY`` (env kill-switch, ADR-07 register):

* owner: gui_refresh task 09 (security, performance, and operations);
* default: unset/off — same-origin echo only;
* rollback: ``ARI_GUI_CORS_ANY=1`` restores the legacy wildcard
  (needed only for cross-origin tunnel/portal topologies where the
  page origin cannot match the API origin; the Vite dev server on
  :5173 does **not** need it — its proxy forwards ``/api``, ``/state``
  and ``/ws`` same-origin);
* removal gate: G5 — superseded when shared/remote mode (ADR-05
  authenticated sessions) lands; until then it is the documented
  escape hatch for cross-origin deployments.

Browser security headers (gui_refresh task 09, RR-P0-10, MN-7)
--------------------------------------------------------------
The SPA index (``_serve_spa_index``) and every ``/static/`` response
carry ``Content-Security-Policy``, ``X-Content-Type-Options: nosniff``
and ``Referrer-Policy: no-referrer``. The CSP (built by the pure
``_csp_policy``) is ``default-src 'self'``-based: scripts must come from
the bundled build (the CDN d3 tag was removed the same wave — the GUI is
fully self-contained), ``style-src`` keeps ``'unsafe-inline'`` because
React inline ``style={}`` attributes are pervasive (accepted residual,
tightening tracked in RR-P0-10), ``img-src`` adds ``data:`` for inline
icons, ``connect-src`` names the tree-stream WebSocket origin explicitly
(it listens on HTTP port + 1 — ``'self'`` alone covers only the page's
own port), ``frame-src 'self'`` keeps the PaperWorkspace same-origin PDF
iframes working, and ``frame-ancestors 'none'`` stops the dashboard
being embedded elsewhere. API/JSON responses are deliberately untouched.

``ARI_GUI_CSP`` (env kill-switch, ADR-07 register):

* owner: gui_refresh task 09 (security, performance, and operations);
* default: unset/on — the three headers above are sent;
* rollback: ``ARI_GUI_CSP=0`` drops all three headers (restores the
  exact pre-MN-7 header set; needed only if a deployment topology the
  policy cannot see — e.g. a reverse proxy remapping the WS port —
  breaks under it);
* removal gate: G5 — reviewed with the deployment trust-mode decision
  (ADR-05); a per-profile CSP replaces the on/off switch there.

Remote token auth (gui_refresh task 09 Wave 5b, RR-P0-3, MN-8, ADR-13)
----------------------------------------------------------------------
When the bind is non-loopback (``ARI_GUI_BIND`` names a remote host —
see ``ari/viz/auth.py`` for the full trust model and the ``ARI_GUI_AUTH``
kill-switch register), a single gate at the top of every ``do_GET`` /
``do_POST`` / ``do_PUT`` / ``do_PATCH`` / ``do_DELETE`` requires
``Authorization: Bearer <ARI_GUI_TOKEN>`` before any dispatch runs. The
``/health`` / ``/health/*`` prefix is exempt (liveness probes), and the
EventSource-consumed SSE streams (``/api/v1/events/stream``, paperbench
run logs) accept the same token as the ``token`` query parameter
(``EventSource`` cannot set headers; the WS handshake in
``websocket.py`` accepts it the same way, while the fetch-consumed
legacy ``/api/logs`` stream uses the header). Refusals are 401 with a typed
JSON body; the comparison is constant-time; ``log_request`` redacts any
``token=`` query value so the token never reaches ``viz_access.jsonl``.
Loopback binds (the default) resolve to no active token, so the local
experience — and CORS preflight (``do_OPTIONS``, which browsers send
without credentials) — is unchanged.

Operational visibility (gui_refresh task 09 Wave 5b, MN-9)
----------------------------------------------------------
``GET /health/live`` / ``GET /health/ready`` are JSON probes served by a
dedicated ``do_GET`` branch ahead of the dispatch chain (liveness is a
constant; readiness answers ``degraded`` as an honest 200, never a 500),
inside the MN-8 ``/health`` auth exemption; ``GET /api/v1/diagnostics``
rides the normal v1 delegation (auth REQUIRED in remote mode). Payloads,
policy and the ``ARI_GUI_HEALTH`` ADR-07 kill-switch register live in
``ari/viz/health.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import websockets
from websockets.server import serve as ws_serve

from . import auth as _auth
from . import state as _st
from .api_state import _broadcast, _do_broadcast, _api_models, _api_checkpoints, _api_checkpoint_summary, _api_delete_checkpoint, _api_switch_checkpoint, _api_ear, _watcher_thread, _api_checkpoint_files, _api_checkpoint_file_read, _api_checkpoint_file_save, _api_checkpoint_file_upload, _api_checkpoint_file_delete, _api_checkpoint_compile, _resolve_paper_file, _api_checkpoint_filetree, _api_checkpoint_filecontent, _api_checkpoint_memory, _resolve_checkpoint_dir, _api_lineage_decisions
from .api_memory import _api_memory_access
from .api_settings import _api_get_env_keys, _api_save_env_key, _api_get_settings, _api_save_settings, _api_get_workflow, _api_save_workflow, _api_skill_detail, _api_skills, _api_profiles, _api_detect_scheduler, _api_rubrics
from .api_workflow import _api_get_workflow_flow, _api_save_workflow_flow, _api_get_default_workflow, _api_save_skill_phases, _api_save_disabled_tools
from .api_experiment import _api_run_stage, _api_launch, _api_logs_sse
from .api_ollama import _api_ollama_resources, _ollama_proxy
from .api_tools import _api_chat_goal, _api_generate_config, _api_upload_file, _api_upload_delete, _api_ssh_test
from .api_orchestrator import (
    _api_list_sub_experiments,
    _api_get_sub_experiment,
    _api_launch_sub_experiment,
)
from .api_process import _api_gpu_monitor_status, _api_gpu_monitor_action, _api_stop
from .ui_helpers import (
    _REDACT_KEYS,
    _build_experiment_detail_config,
    _collect_resource_metrics,
)
from .api_state import _api_node_report, _api_ear_clone_verify, _api_ear_curate, _api_ear_publish_yaml_get, _api_ear_publish_yaml_set


log = logging.getLogger(__name__)


# Frontend bundle locations. Mirrors the constants in ``server.py`` —
# ``_serve_spa_index`` reads these directly, so they must resolve in
# this module's namespace too. Both files sit in ``ari/viz/`` so
# ``Path(__file__).parent`` resolves identically.
DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"
REACT_DIST_DIR = Path(__file__).parent / "static" / "dist"
REACT_INDEX = REACT_DIST_DIR / "index.html"


def _static_content_type(extension: str) -> str:
    """Content type for bundled dashboard assets.

    Vite emits module workers with ``.mjs``. Serving them as the fallback
    octet-stream makes browsers reject the module under ``nosniff``.
    """
    return {
        "css": "text/css",
        "js": "application/javascript",
        "mjs": "application/javascript",
        "html": "text/html",
        "svg": "image/svg+xml",
        "png": "image/png",
        "jpg": "image/jpeg",
        "woff": "font/woff",
        "woff2": "font/woff2",
    }.get(extension.lower(), "application/octet-stream")


# Phase 3B PR-3B-1: shared access-log lock so concurrent requests don't
# interleave their viz_access.jsonl lines.
_access_log_lock = threading.Lock()




def _cors_wildcard_enabled() -> bool:
    """True when the ARI_GUI_CORS_ANY kill-switch restores the legacy
    ``Access-Control-Allow-Origin: *`` wildcard (see module docstring)."""
    return os.environ.get("ARI_GUI_CORS_ANY", "").strip().lower() in ("1", "true")


def _csp_enabled() -> bool:
    """True unless the ARI_GUI_CSP kill-switch (MN-7) disables the browser
    security headers on SPA/static responses (see module docstring)."""
    return os.environ.get("ARI_GUI_CSP", "").strip().lower() not in ("0", "false")


def _csp_policy(host_header: str | None, server_port: int | None) -> str:
    """Build the MN-7 Content-Security-Policy value for SPA/static responses.

    Everything is ``'self'``-based except two justified openings:

    * ``style-src 'unsafe-inline'`` — React inline ``style={}`` attributes
      are pervasive across the SPA; accepted residual, tracked in RR-P0-10;
    * ``connect-src`` ws/wss sources — the tree stream listens on HTTP
      port + 1 (``server.py``), and CSP ``'self'`` covers only the page's
      own port. The browser builds the ws URL from
      ``window.location.hostname`` (useWebSocket.ts), which always equals
      the request Host header's hostname, so the sources are derived from
      it; without a usable Host header the loopback aliases are allowed
      instead. When no port is known at all the ws sources are omitted —
      the GUI degrades to polling, exactly as when WS is unreachable.

    Pure function — unit-tested without sockets in
    ``tests/test_gui_csp_headers.py``.
    """
    host = None
    port = server_port
    if host_header:
        try:
            parsed = urllib.parse.urlsplit("//" + host_header.strip())
            if parsed.hostname:
                host = parsed.hostname
            if parsed.port:
                port = parsed.port
        except ValueError:
            host = None
    if host:
        # urlsplit strips IPv6 brackets; CSP host-sources need them back.
        hosts = [f"[{host}]" if ":" in host else host]
    else:
        hosts = list(_LOOPBACK_HOSTS)
    ws_sources = ""
    if port:
        ws_port = port + 1
        ws_sources = "".join(
            f" ws://{h}:{ws_port} wss://{h}:{ws_port}" for h in hosts
        )
    return (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        f"connect-src 'self'{ws_sources}; "
        "frame-src 'self'; "
        "frame-ancestors 'none'"
    )


# Loopback host forms accepted as "the server's own origin" even when the
# Origin header names a different loopback alias than the Host header
# (e.g. page at http://localhost:8765 calling http://127.0.0.1:8765).
_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "[::1]")


def _origin_allowed(origin: str, host_header: str | None, server_port: int | None) -> bool:
    """Same-origin check for MN-4 CORS: does ``origin`` name this server?

    Accepts the origin when its ``host[:port]`` equals the request ``Host``
    header (covers tunnels/reverse proxies that preserve Host) or one of the
    loopback forms on ``server_port``. Pure function — unit-tested without
    sockets in ``tests/test_gui_bind_cors.py``.
    """
    try:
        parsed = urllib.parse.urlsplit(origin.strip())
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    netloc = parsed.netloc.lower()
    if not netloc:
        return False
    candidates: set[str] = set()
    if host_header:
        candidates.add(host_header.strip().lower())
    if server_port:
        for h in _LOOPBACK_HOSTS:
            candidates.add(f"{h}:{server_port}")
    return netloc in candidates


def _codefile_resolve(
    raw_path: str,
    active_checkpoint: "Path | None",
    search_bases: "list[Path]",
) -> "Path | None":
    """Canonical boundary check for ``GET /codefile?path=`` (MN-5, RR-P0-5).

    Returns the canonical (``Path.resolve``, symlink-resolved) target only when
    it is a regular file whose real path sits under the active checkpoint
    directory or under one of the checkpoint search bases
    (``checkpoint_finder._checkpoint_search_bases``). Each boundary root is
    itself resolved before the prefix comparison, so neither ``..`` segments
    nor symlinks pointing outside the tree can escape, and a crafted path that
    merely *contains* a ``checkpoints`` component (the pre-MN-5 loophole) is
    rejected. Anything disallowed — missing file, directory, traversal,
    out-of-base path — yields ``None`` (the handler answers 404, as before).
    Pure function — unit-tested without sockets in
    ``tests/test_gui_path_proxy_hardening.py``.
    """
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if ".." in candidate.parts:
        return None
    try:
        real = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None
    if not real.is_file():
        return None
    roots: "list[Path]" = []
    if active_checkpoint is not None:
        roots.append(Path(active_checkpoint))
    roots.extend(search_bases)
    for root in roots:
        try:
            base = Path(root).resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        try:
            real.relative_to(base)
        except ValueError:
            continue
        return real
    return None


def _write_access_log(checkpoint_dir: Path, entry: dict) -> None:
    log_path = checkpoint_dir / "viz_access.jsonl"
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _access_log_lock:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)


class _Handler(BaseHTTPRequestHandler):
    # HTTP/1.1 enables TCP keep-alive so Chrome's 6-per-origin connection
    # pool isn't drained by short polls. SSE endpoints still send
    # Connection: close so long-lived streams don't hog a keep-alive slot.
    protocol_version = "HTTP/1.1"

    def handle_one_request(self):
        self._req_start = time.monotonic()
        super().handle_one_request()

    def log_request(self, code='-', size='-'):
        try:
            ckpt = _st._checkpoint_dir
            if ckpt is None:
                return
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "method": getattr(self, "command", None) or "-",
                # MN-8: the SSE/WS auth token may ride in the query string —
                # redact it so the token never reaches viz_access.jsonl.
                "path": _auth.redact_token_in_path(getattr(self, "path", None) or "-"),
                "status": int(code) if str(code).isdigit() else code,
                "duration_ms": round(
                    (time.monotonic() - getattr(self, "_req_start", time.monotonic())) * 1000, 2
                ),
                "client": self.client_address[0] if self.client_address else "-",
            }
            _write_access_log(Path(ckpt), entry)
        except Exception:
            pass

    def log_message(self, *args):  # suppress stderr noise
        pass

    def _serve_spa_index(self):
        """Serve the React SPA index.html (from static/dist/ build)."""
        if REACT_INDEX.exists():
            html_bytes = REACT_INDEX.read_bytes()
        elif DASHBOARD_PATH.exists():
            # Fallback to legacy dashboard.html if React build not found
            html_bytes = DASHBOARD_PATH.read_text(encoding="utf-8").encode("utf-8")
        else:
            html_bytes = b"<h1>dashboard not found - run npm build in frontend/</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Length", str(len(html_bytes)))
        self.send_header("Expires", "0")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(html_bytes)

    def _send_security_headers(self) -> None:
        """Emit the MN-7 browser security headers (CSP + nosniff +
        referrer policy) on SPA index / static responses. No-op under the
        ARI_GUI_CSP=0 kill-switch (restores the pre-MN-7 header set)."""
        if not _csp_enabled():
            return
        headers = getattr(self, "headers", None)
        host = headers.get("Host") if headers is not None else None
        port = getattr(_st, "_server_port", None)
        self.send_header("Content-Security-Policy", _csp_policy(host, port))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    def _auth_gate(self) -> bool:
        """MN-8 remote token gate — thin delegate to ``auth.gate_request``
        (see the module docstring and ari/viz/auth.py for the policy).
        Runs first in every method handler, before any dispatch or body
        read. True = proceed; False = a 401 was already written."""
        return _auth.gate_request(self)

    def _cors_origin(self) -> str | None:
        """Value for ``Access-Control-Allow-Origin``, or None to omit it.

        MN-4 same-origin policy: echo the request Origin only when it names
        this server (Host header or loopback:port forms); ``*`` only under
        the ARI_GUI_CORS_ANY kill-switch. See the module docstring.
        """
        if _cors_wildcard_enabled():
            return "*"
        headers = getattr(self, "headers", None)
        if headers is None:
            return None
        origin = headers.get("Origin")
        if not origin:
            return None
        host = headers.get("Host")
        port = getattr(_st, "_server_port", None)
        return origin if _origin_allowed(origin, host, port) else None

    def _send_cors_headers(self) -> None:
        """Emit the MN-4 CORS header(s) — nothing for cross-origin requests."""
        allow = self._cors_origin()
        if allow is None:
            return
        self.send_header("Access-Control-Allow-Origin", allow)
        if allow != "*":
            self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        """Handle CORS preflight requests.

        Browsers preflight cross-origin non-simple requests. Without this
        handler, Python returns 501 and the browser reports 'TypeError:
        Failed to fetch'. MN-4: the CORS grant headers are only sent when
        the Origin passes the same-origin policy (or the ARI_GUI_CORS_ANY
        wildcard kill-switch is on); disallowed origins still get a 204,
        just without any Access-Control-* headers, so the browser blocks
        the actual request.
        """
        self.send_response(204)
        allow = self._cors_origin()
        if allow is not None:
            self.send_header("Access-Control-Allow-Origin", allow)
            if allow != "*":
                self.send_header("Vary", "Origin")
            self.send_header(
                "Access-Control-Allow-Methods",
                "GET, POST, PUT, PATCH, DELETE, OPTIONS",
            )
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, X-Filename, If-Match, Last-Event-ID",
            )
            self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self._auth_gate():  # MN-8: before any dispatch
            return
        # ── Operational health probes (task 09 Wave 5b, MN-9) — payloads,
        # policy + ARI_GUI_HEALTH register in ari/viz/health.py; auth-exempt
        # via the MN-8 /health prefix exemption. handle_probe returns False
        # under the kill-switch so both paths fall through to the pre-MN-9
        # SPA fallback below. Exact matches (probes send no query string).
        if self.path in ("/health/live", "/health/ready"):
            from . import health as _health
            if _health.handle_probe(self):
                return
        if self.path in ("/logo.png", "/logo"):
            logo_candidates = [
                _st._ari_root / "docs" / "assets" / "logo.png",
                Path(__file__).parent.parent.parent.parent / "docs" / "assets" / "logo.png",
            ]
            for lp in logo_candidates:
                if lp.exists():
                    data = lp.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Cache-Control", "public, max-age=3600")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
            self.send_response(404)
            self.end_headers()
            return
        if self.path in ("/", "/index.html"):
            self._serve_spa_index()
            return
        elif self.path.startswith("/static/"):
            fname = self.path[len("/static/"):]
            static_dir = Path(__file__).parent / "static"
            fpath = static_dir / fname
            if fpath.exists() and fpath.is_file():
                ext = fpath.suffix.lower().lstrip('.')
                ct = _static_content_type(ext)
                data = fpath.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(data)))
                # Hashed asset filenames from Vite get long-term caching
                if "/dist/assets/" in self.path:
                    self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                else:
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self._send_security_headers()
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404); self.end_headers()
        elif self.path.startswith("/memory/"):
            # legacy endpoint, kept for backwards
            # compatibility. Forwards to the backend library so Letta-backed
            # checkpoints work.
            node_id = self.path[len("/memory/"):]
            try:
                node_id = urllib.parse.unquote(node_id)
                if _st._checkpoint_dir is None:
                    entries = []
                else:
                    from ari.public.paths import PathManager as _PM_legacy
                    _PM_legacy.set_checkpoint_dir_env(_st._checkpoint_dir)
                    from .internal_adapters import memory_backend
                    backend = memory_backend(_st._checkpoint_dir)
                    raw = backend.get_node_memory(node_id).get("entries", [])
                    entries = [
                        {"text": e.get("text", ""),
                         "metadata": e.get("metadata", {})}
                        for e in raw
                    ]
                payload = json.dumps({"entries": entries}, ensure_ascii=False).encode()
            except Exception as ex:
                payload = json.dumps({"entries": [], "error": str(ex)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(payload)
        elif self.path == "/state":
            # /state AppState builder extracted to services.state_service
            # (subtask 062, StateService). The comparison + byte-identical HTTP
            # response (no ACAO header — inline-none CORS quirk) stay here.
            from .services.state_service import build_app_state
            data = build_app_state()
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/gpu-monitor":
            # NOTE: kept as a manual response (no Access-Control-Allow-Origin
            # header, unlike _json) to preserve the exact pre-extraction wire
            # behaviour; the dict is built by api_process._api_gpu_monitor_status.
            body = json.dumps(_api_gpu_monitor_status()).encode()
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
        elif self.path.startswith("/api/ollama/"):
            # Reverse proxy: forward to configured ollama_host
            _ollama_proxy(self)
            return

        elif self.path.startswith("/codefile"):
            # Serve file content for artifact file paths.
            # MN-5 (RR-P0-5): the boundary is the active checkpoint dir or a
            # canonical checkpoint search base, compared on resolved realpaths
            # via _codefile_resolve — a path merely containing "checkpoints"
            # is no longer sufficient. The search bases are read through the
            # api_state facade so tests that monkeypatch
            # api_state._checkpoint_search_bases are honoured (same pattern
            # as checkpoint_finder._resolve_checkpoint_dir).
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            fpath = qs.get("path", [""])[0]
            try:
                from . import api_state as _as
                p = _codefile_resolve(
                    fpath, _st._checkpoint_dir, _as._checkpoint_search_bases()
                )
                if p is not None and p.stat().st_size < 20_000_000:
                    body = p.read_bytes()
                    ext = p.suffix.lower()
                    ctype_map = {
                        ".pdf": "application/pdf", ".png": "image/png",
                        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".svg": "image/svg+xml", ".eps": "application/postscript",
                        ".tiff": "image/tiff", ".gif": "image/gif",
                    }
                    ctype = ctype_map.get(ext, "text/plain; charset=utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self._send_cors_headers()
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()
            except Exception:
                self.send_response(500)
                self.end_headers()
        # ── New JSON API endpoints ──────────────────────
        elif self.path == "/api/models":
            self._json(_api_models())
        elif re.match(r"^/api/checkpoint/[^/]+/paper\.(pdf|tex)$", self.path):
            m = re.match(r"^/api/checkpoint/([^/]+)/paper\.(pdf|tex)$", self.path)
            ckpt_id = m.group(1); ext = m.group(2)
            fname = "full_paper." + ext
            search_paths = [
                _st._ari_root / "ari-core" / "checkpoints" / ckpt_id / fname,
                _st._ari_root / "workspace" / "checkpoints" / ckpt_id / fname,
            ]
            if _st._checkpoint_dir and _st._checkpoint_dir.name == ckpt_id:
                search_paths.insert(0, _st._checkpoint_dir / fname)
            found = next((p for p in search_paths if p.exists()), None)
            if found:
                ctype = "application/pdf" if ext == "pdf" else "text/plain"
                data = found.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404); self.end_headers()
            return
        elif self.path == "/api/env-keys":
            self._json(_api_get_env_keys())
        elif self.path == "/api/ollama-resources":
            self._json(_api_ollama_resources())
        elif self.path == "/api/checkpoints":
            self._json(_api_checkpoints())
        elif self.path == "/api/rubrics":
            self._json(_api_rubrics())
        elif self.path.startswith("/api/fewshot/"):
            from .api_fewshot import _api_fewshot_list
            rid = self.path[len("/api/fewshot/"):].split("?")[0]
            self._json(_api_fewshot_list(urllib.parse.unquote(rid)))
        elif self.path.startswith("/api/checkpoint/") and self.path.endswith("/summary"):
            ckpt_id = self.path[len("/api/checkpoint/"):-len("/summary")]
            self._json(_api_checkpoint_summary(urllib.parse.unquote(ckpt_id)))
        elif self.path.startswith("/api/checkpoint/") and self.path.endswith("/kca"):
            from .api_kca import _api_checkpoint_kca
            ckpt_id = self.path[len("/api/checkpoint/"):-len("/kca")]
            self._json(_api_checkpoint_kca(urllib.parse.unquote(ckpt_id)))
        elif self.path.startswith("/api/checkpoint/") and self.path.endswith("/memory"):
            ckpt_id = self.path[len("/api/checkpoint/"):-len("/memory")]
            self._json(_api_checkpoint_memory(urllib.parse.unquote(ckpt_id)))
        elif "/memory_access" in self.path and self.path.startswith("/api/checkpoint/"):
            parsed = urllib.parse.urlparse(self.path)
            ckpt_id = parsed.path[len("/api/checkpoint/"):-len("/memory_access")]
            qs = urllib.parse.parse_qs(parsed.query or "")
            node_id = (qs.get("node_id") or [""])[0]
            op = (qs.get("op") or ["all"])[0]
            try:
                limit = int((qs.get("limit") or ["200"])[0])
            except ValueError:
                limit = 200
            self._json(_api_memory_access(
                urllib.parse.unquote(ckpt_id), node_id, op=op, limit=limit,
                resolver=_resolve_checkpoint_dir,
            ))
        elif self.path == "/api/memory/health":
            from .api_memory import _api_memory_health
            self._json(_api_memory_health(_st._checkpoint_dir))
        elif self.path == "/api/memory/detect":
            from .api_memory import _api_memory_detect
            self._json(_api_memory_detect())
        elif self.path.startswith("/api/checkpoint/") and urllib.parse.urlparse(self.path).path.endswith("/files"):
            parsed_p = urllib.parse.urlparse(self.path).path
            ckpt_id = parsed_p[len("/api/checkpoint/"):-len("/files")]
            self._json(_api_checkpoint_files(urllib.parse.unquote(ckpt_id)))
        elif self.path.startswith("/api/checkpoint/") and ("/file/raw" in self.path or "/file?" in self.path):
            parsed = urllib.parse.urlparse(self.path)
            # path = /api/checkpoint/{ckpt_id}/file/raw  or  /api/checkpoint/{ckpt_id}/file
            parts = parsed.path.strip("/").split("/")
            # parts = ["api", "checkpoint", ckpt_id, "file", ...]
            ckpt_id = urllib.parse.unquote(parts[2]) if len(parts) > 2 else ""
            qs = urllib.parse.parse_qs(parsed.query)
            fname = qs.get("name", [""])[0]
            is_raw = len(parts) > 4 and parts[4] == "raw"
            if is_raw:
                # Serve binary file (images, PDFs, etc.)
                fpath, err = _resolve_paper_file(ckpt_id, fname)
                if err:
                    self.send_response(404); self.end_headers()
                else:
                    ext = fpath.suffix.lower()
                    ctype_map = {
                        ".pdf": "application/pdf", ".png": "image/png",
                        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".svg": "image/svg+xml", ".eps": "application/postscript",
                        ".tiff": "image/tiff",
                    }
                    ctype = ctype_map.get(ext, "application/octet-stream")
                    data = fpath.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self._send_cors_headers()
                    self.end_headers()
                    self.wfile.write(data)
                return
            else:
                # Serve text file content as JSON
                self._json(_api_checkpoint_file_read(ckpt_id, fname))
        elif self.path.startswith("/api/checkpoint/") and urllib.parse.urlparse(self.path).path.endswith("/filetree"):
            parsed_ft = urllib.parse.urlparse(self.path)
            ckpt_id_ft = parsed_ft.path[len("/api/checkpoint/"):-len("/filetree")]
            qs_ft = urllib.parse.parse_qs(parsed_ft.query)
            node_id_ft = qs_ft.get("node_id", [""])[0]
            self._json(_api_checkpoint_filetree(urllib.parse.unquote(ckpt_id_ft), node_id_ft))
        elif self.path.startswith("/api/checkpoint/") and "/filecontent" in self.path:
            parsed_fc = urllib.parse.urlparse(self.path)
            parts_fc = parsed_fc.path.strip("/").split("/")
            ckpt_id_fc = urllib.parse.unquote(parts_fc[2]) if len(parts_fc) > 2 else ""
            qs_fc = urllib.parse.parse_qs(parsed_fc.query)
            fpath_fc = qs_fc.get("path", [""])[0]
            node_id_fc = qs_fc.get("node_id", [""])[0]
            self._json(_api_checkpoint_filecontent(ckpt_id_fc, fpath_fc, node_id_fc))
        elif self.path.startswith("/api/ear/") and self.path.endswith("/publish-yaml"):
            from .api_state import _api_ear_publish_yaml_get
            rid = self.path[len("/api/ear/"):-len("/publish-yaml")]
            self._json(_api_ear_publish_yaml_get(urllib.parse.unquote(rid)))
        elif self.path.startswith("/api/ear/"):
            run_id = self.path[len("/api/ear/"):]
            self._json(_api_ear(urllib.parse.unquote(run_id)))
        elif self.path.startswith("/api/nodes/") and self.path.endswith("/report"):
            # /api/nodes/<run_id>/<node_id>/report — v0.7.0 Tree Report tab.
            from .api_state import _api_node_report
            tail = self.path[len("/api/nodes/"):-len("/report")]
            parts = tail.split("/", 1)
            if len(parts) == 2:
                rid, nid = (urllib.parse.unquote(p) for p in parts)
                self._json(_api_node_report(rid, nid))
            else:
                self._json({"error": "expected /api/nodes/<run_id>/<node_id>/report"})
        elif self.path == "/api/capabilities":
            # gui_refresh Wave 1: ARI_GUI_V2 server capability flag
            # (owner: task 03, removal gate: G6 — see api_capabilities).
            from .api_capabilities import _api_capabilities
            self._json(_api_capabilities())
        elif self.path == "/api/settings":
            self._json(_api_get_settings())
        # ── Publish ──
        elif self.path == "/api/publish/settings":
            from .api_publish import _api_publish_settings_get
            self._json(_api_publish_settings_get())
        elif self.path.startswith("/api/publish/") and self.path.endswith("/preview"):
            from .api_publish import _api_publish_preview
            rid = self.path[len("/api/publish/"):-len("/preview")]
            self._json(_api_publish_preview(urllib.parse.unquote(rid)))
        elif self.path.startswith("/api/publish/") and self.path.endswith("/record"):
            from .api_publish import _api_publish_record
            rid = self.path[len("/api/publish/"):-len("/record")]
            self._json(_api_publish_record(urllib.parse.unquote(rid)))
        elif self.path == "/api/profiles":
            self._json(_api_profiles())
        elif self.path == "/api/upload":
            # Serve upload form page
            self._json({"error": "use POST /api/upload"})
        elif self.path == "/api/experiment-detail":
            self._json({"experiment_detail_config": _build_experiment_detail_config()})
        elif self.path == "/api/active-checkpoint":
            self._json({"path": str(_st._checkpoint_dir) if _st._checkpoint_dir else None,
                        "id": _st._checkpoint_dir.name if _st._checkpoint_dir else None})
        elif self.path == "/api/workflow":
            self._json(_api_get_workflow())
        elif self.path.startswith("/api/skill/"):
            skill_name = self.path[len("/api/skill/"):]
            self._json(_api_skill_detail(skill_name))
        elif self.path == "/api/skills":
            self._json(_api_skills())
        elif self.path == "/api/resource-metrics":
            self._json(_collect_resource_metrics())
        elif self.path == "/api/container/info":
            from ari.public.container import get_container_info
            self._json(get_container_info())
        elif self.path == "/api/container/images":
            from ari.public.container import list_images
            self._json({"images": list_images()})
        elif self.path == "/api/workflow/default":
            self._json(_api_get_default_workflow())
        elif self.path == "/api/workflow/flow":
            self._json(_api_get_workflow_flow())
        elif self.path == "/api/scheduler/detect":
            self._json(_api_detect_scheduler())
        elif self.path == "/api/slurm/partitions":
            env = _api_detect_scheduler()
            self._json(env.get("partitions", []))
        elif self.path == "/api/logs":
            # MN-8 note: this legacy stream is consumed via fetch +
            # ReadableStream (MonitorPage), which CAN send the Authorization
            # header — so it does not take the query-token form (the exact
            # match, with no query string, predates MN-8 and is pinned by
            # check_viz_api_schema's route id). The EventSource-consumed SSE
            # endpoints (/api/v1/events/stream, paperbench run logs) accept
            # ?token= because EventSource cannot set headers.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self._send_cors_headers()
            self.send_header("Connection", "close")
            self.end_headers()
            _api_logs_sse(self.wfile)
        elif self.path == "/api/sub-experiments":
            self._json(_api_list_sub_experiments())
        elif self.path.startswith("/api/sub-experiments/"):
            run_id = self.path[len("/api/sub-experiments/"):]
            self._json(_api_get_sub_experiment(urllib.parse.unquote(run_id)))
        elif self.path.startswith("/api/lineage-decisions/"):
            # lineage decisions GUI: stream the contents of
            # {checkpoint}/lineage_decisions.jsonl so the LineageDecisions
            # panel can render every lineage decisions escalation.
            ckpt_name = urllib.parse.unquote(
                self.path[len("/api/lineage-decisions/"):]
            )
            self._json(_api_lineage_decisions(ckpt_name))
        # ── PaperBench (v0.7.2) ──────────────────────────────────────────
        elif self.path == "/api/paperbench/papers":
            from .api_paperbench import _api_list_papers
            self._json(_api_list_papers())
        elif self.path.startswith("/api/paperbench/arxiv/"):
            from .api_paperbench import _api_arxiv_fetch
            aid = urllib.parse.unquote(self.path[len("/api/paperbench/arxiv/"):])
            self._json(_api_arxiv_fetch(aid))
        elif self.path.startswith("/api/paperbench/papers/") and self.path.endswith("/license"):
            from .api_paperbench import _api_paper_license
            pid_pb = self.path[len("/api/paperbench/papers/"):-len("/license")]
            self._json(_api_paper_license(urllib.parse.unquote(pid_pb)))
        elif self.path.startswith("/api/paperbench/run/") and (
            self.path.endswith("/logs") or "/logs?" in self.path
        ):
            # SSE stream for PaperBench job logs. The browser opens an
            # EventSource and we push each appended log line until the
            # job's status leaves {queued, running}. Loops with a short
            # sleep + heartbeat comment so the connection stays alive
            # through HTTP/1.1 keep-alive timeouts.
            from .api_paperbench import _job_logs_since, _job_snapshot, append_job_log  # noqa: F401
            parsed_sse = urllib.parse.urlparse(self.path)
            jid_sse = urllib.parse.unquote(
                parsed_sse.path[len("/api/paperbench/run/"):-len("/logs")]
            )
            q_sse = dict(urllib.parse.parse_qsl(parsed_sse.query))
            try:
                since_idx = int(q_sse.get("since", "0"))
            except ValueError:
                since_idx = 0
            # Last-Event-ID resume support
            last_id = self.headers.get("Last-Event-ID")
            if last_id and last_id.isdigit():
                since_idx = max(since_idx, int(last_id))

            snap0 = _job_snapshot(jid_sse)
            if not snap0:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "job not found"}).encode("utf-8"))
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self._send_cors_headers()
                self.send_header("Connection", "close")
                self.end_headers()
                idx = since_idx
                # Cap the streaming window so a stuck job doesn't hold the
                # worker thread forever. The browser will reconnect using
                # Last-Event-ID when it needs more.
                deadline = time.time() + 300  # 5 min per stream
                try:
                    while True:
                        new_rows = _job_logs_since(jid_sse, idx)
                        for row in new_rows:
                            payload = json.dumps(row, ensure_ascii=False)
                            line = f"id: {idx}\nevent: log\ndata: {payload}\n\n"
                            self.wfile.write(line.encode("utf-8"))
                            self.wfile.flush()
                            idx += 1
                        snap = _job_snapshot(jid_sse)
                        # "interrupted" is the disk-fallback status of a job
                        # whose worker died with a previous server process —
                        # terminal for the stream (no more log lines can come).
                        if snap.get("status") in ("completed", "failed", "interrupted"):
                            done_payload = json.dumps({"status": snap.get("status")}, ensure_ascii=False)
                            self.wfile.write(f"event: done\ndata: {done_payload}\n\n".encode("utf-8"))
                            self.wfile.flush()
                            break
                        if time.time() > deadline:
                            self.wfile.write(": stream-timeout — reconnect\n\n".encode("utf-8"))
                            self.wfile.flush()
                            break
                        # Heartbeat comment to keep proxies from closing the
                        # idle connection. SSE comments start with ':'.
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        time.sleep(1.0)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        elif self.path.startswith("/api/paperbench/run/") and self.path.endswith("/results"):
            from .api_paperbench import _api_run_results
            jid = self.path[len("/api/paperbench/run/"):-len("/results")]
            self._json(_api_run_results(urllib.parse.unquote(jid)))
        elif self.path.startswith("/api/paperbench/run/") and (
            self.path.endswith("/report") or "/report?" in self.path
        ):
            from .api_paperbench import _api_run_report
            parsed = urllib.parse.urlparse(self.path)
            jid = parsed.path[len("/api/paperbench/run/"):-len("/report")]
            q = {k: urllib.parse.unquote(v) for k, v in urllib.parse.parse_qsl(parsed.query)}
            for key in ("languages", "formats"):
                if key in q:
                    q[key] = q[key].split(",")
            self._json(_api_run_report(urllib.parse.unquote(jid), q))
        elif self.path.startswith("/api/paperbench/run/"):
            from .api_paperbench import _api_run_status
            jid = self.path[len("/api/paperbench/run/"):]
            self._json(_api_run_status(urllib.parse.unquote(jid)))
        # ── /api/v1 realtime SSE (gui_refresh Wave 2b, ADR-03) ───────────
        elif self.path.startswith("/api/v1/events/stream"):
            # Must precede the /api/v1/ JSON delegation branch: dispatch()
            # returns dicts, while this endpoint writes a long-lived
            # text/event-stream (same chunked pattern as /api/logs and the
            # paperbench job-log stream, incl. Last-Event-ID resume).
            from .v1 import events as _v1_events
            parsed_ev = urllib.parse.urlparse(self.path)
            if parsed_ev.path != "/api/v1/events/stream":
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "not found"}).encode("utf-8"))
            else:
                q_ev = dict(urllib.parse.parse_qsl(parsed_ev.query))
                topics_ev = None
                if q_ev.get("topics"):
                    topics_ev = {
                        t.strip() for t in q_ev["topics"].split(",") if t.strip()
                    }
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self._send_cors_headers()
                self.send_header("Connection", "close")
                self.end_headers()
                _v1_events.stream_events(
                    self.wfile,
                    run_id=q_ev.get("run_id") or None,
                    topics=topics_ev,
                    # Header wins (native browser auto-reconnect); the
                    # frontend's manual backoff reconnect cannot set headers
                    # on EventSource, so it carries the cursor as the
                    # last_event_id query param instead (eventStream.ts).
                    last_event_id=self.headers.get("Last-Event-ID")
                    or q_ev.get("last_event_id"),
                )
        # ── /api/v1 (gui_refresh Wave 2a, ADR-02/ADR-08) ─────────────────
        elif self.path.startswith("/api/v1/"):
            # Versioned read-only platform: declarative dispatch lives in
            # viz/v1/router.py; error envelopes carry their HTTP status via
            # the same _status pop convention as launch/run-stage.
            from .v1.router import dispatch as _v1_dispatch
            r = _v1_dispatch("GET", self.path)
            self._json(r, status=r.pop("_status", 200))
        else:
            # SPA fallback: serve React index.html for client-side routing
            if not self.path.startswith("/api/"):
                self._serve_spa_index()
            else:
                self.send_response(404)
                self.end_headers()

    def do_POST(self):
        if not self._auth_gate():  # MN-8: before any dispatch/body read
            return
        length = int(self.headers.get("Content-Length", 0))
        if length > 10 * 1024 * 1024:  # 10MB limit
            self.send_response(413)
            self.end_headers()
            return
        body = self.rfile.read(length) if length else b"{}"
        # ── /api/v1 mutations (gui_refresh Wave 3b, task 05 config CRUD) ──
        # Same single-delegation pattern as the do_GET /api/v1/ branch; the
        # v1 router owns body parsing, If-Match, and the typed envelopes.
        if self.path.startswith("/api/v1/"):
            from .v1.router import dispatch as _v1_dispatch
            r = _v1_dispatch("POST", self.path, body=body, headers=self.headers)
            self._json(r, status=r.pop("_status", 200))
        elif self.path == "/api/settings":
            self._json(_api_save_settings(body))
        elif self.path == "/api/memory/start-local":
            from .api_memory import _api_memory_start_local
            self._json(_api_memory_start_local(body))
        elif self.path == "/api/memory/stop-local":
            from .api_memory import _api_memory_stop_local
            self._json(_api_memory_stop_local())
        elif self.path == "/api/memory/restart":
            from .api_memory import _api_memory_restart
            self._json(_api_memory_restart(body))
        elif self.path == "/api/launch":
            r = _api_launch(body); self._json(r, status=r.pop("_status", 200))
        elif self.path == "/api/sub-experiments/launch":
            r = _api_launch_sub_experiment(body); self._json(r, status=r.pop("_status", 200))
        elif self.path == "/api/run-stage":
            r = _api_run_stage(body); self._json(r, status=r.pop("_status", 200))
        elif self.path == "/api/config/generate":
            self._json(_api_generate_config(body))
        elif self.path == "/api/chat-goal":
            self._json(_api_chat_goal(body))
        elif self.path == "/api/upload":
            r = _api_upload_file(self.headers, body); self._json(r, status=r.pop("_status", 200))
        elif self.path == "/api/upload/delete":
            self._json(_api_upload_delete(body))
        elif self.path == "/api/env-keys":
            # ADR-11: name-allowlist rejections carry _status 400.
            r = _api_save_env_key(body); self._json(r, status=r.pop("_status", 200))
        elif self.path == "/api/ssh/test":
            self._json(_api_ssh_test(body))
        elif self.path == "/api/switch-checkpoint":
            self._json(_api_switch_checkpoint(body))
        elif self.path.startswith("/api/ear/") and self.path.endswith("/curate"):
            from .api_state import _api_ear_curate
            rid = self.path[len("/api/ear/"):-len("/curate")]
            self._json(_api_ear_curate(urllib.parse.unquote(rid)))
        elif self.path.startswith("/api/ear/") and self.path.endswith("/publish-yaml"):
            from .api_state import _api_ear_publish_yaml_set
            rid = self.path[len("/api/ear/"):-len("/publish-yaml")]
            self._json(_api_ear_publish_yaml_set(urllib.parse.unquote(rid), body))
        elif self.path == "/api/ear/clone-verify":
            from .api_state import _api_ear_clone_verify
            self._json(_api_ear_clone_verify(body))
        # ── Publish API ───────────────────────────────────
        elif self.path == "/api/publish/settings":
            from .api_publish import _api_publish_settings_set
            self._json(_api_publish_settings_set(body))
        elif self.path.startswith("/api/publish/") and self.path.endswith("/promote"):
            from .api_publish import _api_publish_promote
            rid = self.path[len("/api/publish/"):-len("/promote")]
            self._json(_api_publish_promote(urllib.parse.unquote(rid), body))
        elif self.path.startswith("/api/publish/") and not self.path.endswith(("/preview", "/record", "/settings")):
            from .api_publish import _api_publish_run
            rid = self.path[len("/api/publish/"):]
            r = _api_publish_run(urllib.parse.unquote(rid), body)
            self._json(r, status=r.pop("_status", 200))
        elif self.path.startswith("/api/fewshot/") and self.path.endswith("/sync"):
            from .api_fewshot import _api_fewshot_sync
            rid = self.path[len("/api/fewshot/"):-len("/sync")]
            self._json(_api_fewshot_sync(urllib.parse.unquote(rid)))
        elif self.path.startswith("/api/fewshot/") and self.path.endswith("/upload"):
            from .api_fewshot import _api_fewshot_upload
            rid = self.path[len("/api/fewshot/"):-len("/upload")]
            try:
                fields = json.loads(body or b"{}")
            except Exception as e:
                self._json({"error": f"invalid JSON body: {e}"}, status=400); return
            self._json(_api_fewshot_upload(urllib.parse.unquote(rid), fields))
        elif self.path.startswith("/api/fewshot/") and self.path.endswith("/delete"):
            from .api_fewshot import _api_fewshot_delete
            rest = self.path[len("/api/fewshot/"):-len("/delete")]
            parts = rest.split("/", 1)
            if len(parts) != 2:
                self._json({"error": "path must be /api/fewshot/<rubric>/<example>/delete"}, status=400); return
            self._json(_api_fewshot_delete(
                urllib.parse.unquote(parts[0]),
                urllib.parse.unquote(parts[1]),
            ))
        # ── PaperBench (v0.7.2) ──────────────────────────────────────────
        elif self.path == "/api/paperbench/papers/import":
            from .api_paperbench import _api_import_paper
            try:
                fields = json.loads(body or b"{}")
            except json.JSONDecodeError as e:
                self._json({"error": f"invalid JSON body: {e}"}, status=400); return
            self._json(_api_import_paper(fields))
        elif self.path.startswith("/api/paperbench/papers/") and self.path.endswith("/delete"):
            from .api_paperbench import _api_delete_paper
            pid_pb = self.path[len("/api/paperbench/papers/"):-len("/delete")]
            self._json(_api_delete_paper(urllib.parse.unquote(pid_pb)))
        elif self.path.startswith("/api/paperbench/papers/") and self.path.endswith("/metadata"):
            from .api_paperbench import _api_patch_paper_metadata
            pid_pb = self.path[len("/api/paperbench/papers/"):-len("/metadata")]
            try:
                fields = json.loads(body or b"{}")
            except json.JSONDecodeError as e:
                self._json({"error": f"invalid JSON body: {e}"}, status=400); return
            self._json(_api_patch_paper_metadata(urllib.parse.unquote(pid_pb), fields))
        elif self.path == "/api/paperbench/run":
            from .api_paperbench import _api_launch_run
            try:
                fields = json.loads(body or b"{}")
            except json.JSONDecodeError as e:
                self._json({"error": f"invalid JSON body: {e}"}, status=400); return
            self._json(_api_launch_run(fields))
        elif self.path == "/api/paperbench/cost-estimate":
            from .api_paperbench import _api_cost_estimate
            try:
                fields = json.loads(body or b"{}")
            except json.JSONDecodeError as e:
                self._json({"error": f"invalid JSON body: {e}"}, status=400); return
            self._json(_api_cost_estimate(fields))
        elif self.path.startswith("/api/paperbench/run/") and self.path.endswith("/report"):
            # F6a resolved (gui_refresh Wave 4a): requestPaperbenchReport
            # POSTs {languages, formats}; delegate to the same handler as
            # the GET query-string variant (_api_run_report's contract is
            # "POST body or URL query"). Both methods stay served.
            from .api_paperbench import _api_run_report
            jid = self.path[len("/api/paperbench/run/"):-len("/report")]
            try:
                fields = json.loads(body or b"{}")
            except json.JSONDecodeError as e:
                self._json({"error": f"invalid JSON body: {e}"}, status=400); return
            self._json(_api_run_report(urllib.parse.unquote(jid), fields))
        elif self.path.startswith("/api/ollama/"):
            _ollama_proxy(self)
            return
        elif self.path == "/api/gpu-monitor":
            # MN-6: stop-action challenge refusals carry _status 428.
            r = _api_gpu_monitor_action(body); self._json(r, status=r.pop("_status", 200))
        elif self.path == "/api/stop":
            # MN-6: challenge refusals carry _status 428.
            r = _api_stop(body); self._json(r, status=r.pop("_status", 200))
        elif self.path == "/api/checkpoint/file/save":
            self._json(_api_checkpoint_file_save(body))
        elif self.path == "/api/checkpoint/file/delete":
            self._json(_api_checkpoint_file_delete(body))
        elif self.path == "/api/checkpoint/compile":
            self._json(_api_checkpoint_compile(body))
        elif re.match(r"^/api/checkpoint/[^/]+/file/upload$", self.path):
            m = re.match(r"^/api/checkpoint/([^/]+)/file/upload$", self.path)
            ckpt_id = urllib.parse.unquote(m.group(1))
            fname = self.headers.get("X-Filename", "upload.bin")
            self._json(_api_checkpoint_file_upload(ckpt_id, fname, body))
        elif self.path == "/api/delete-checkpoint":
            # MN-6: challenge refusals carry _status 428.
            r = _api_delete_checkpoint(body); self._json(r, status=r.pop("_status", 200))
        elif self.path == "/api/workflow":
            r = _api_save_workflow(body); self._json(r, status=r.pop("_status", 200))
        elif self.path == "/api/workflow/flow":
            r = _api_save_workflow_flow(body); self._json(r, status=r.pop("_status", 200))
        elif self.path == "/api/workflow/skills":
            r = _api_save_skill_phases(body); self._json(r, status=r.pop("_status", 200))
        elif self.path == "/api/workflow/disabled-tools":
            r = _api_save_disabled_tools(body); self._json(r, status=r.pop("_status", 200))
        elif self.path == "/api/container/pull":
            data_cp = json.loads(body or b'{}')
            try:
                from ari.public.container import ContainerConfig, pull_image
                _cp_cfg = ContainerConfig(
                    image=data_cp.get("image", ""),
                    mode=data_cp.get("mode", "auto"),
                )
                ok = pull_image(_cp_cfg)
                self._json({"ok": ok})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})
        else:
            self.send_response(404)
            self.end_headers()

    # ── /api/v1 mutations (gui_refresh Wave 3b, task 05 config CRUD; Wave
    # 4d adds do_PUT for the ADR-05 secret assignment) ─────────────────────
    # PATCH/PUT/DELETE exist only for the versioned /api/v1 surface;
    # anything else stays 404 exactly as an unknown method did before.

    def do_PATCH(self):
        if not self._auth_gate():  # MN-8: before any dispatch/body read
            return
        length = int(self.headers.get("Content-Length", 0))
        if length > 10 * 1024 * 1024:  # 10MB limit (same as do_POST)
            self.send_response(413)
            self.end_headers()
            return
        body = self.rfile.read(length) if length else b"{}"
        if self.path.startswith("/api/v1/"):
            from .v1.router import dispatch as _v1_dispatch
            r = _v1_dispatch("PATCH", self.path, body=body, headers=self.headers)
            self._json(r, status=r.pop("_status", 200))
        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self):
        if not self._auth_gate():  # MN-8: before any dispatch/body read
            return
        length = int(self.headers.get("Content-Length", 0))
        if length > 10 * 1024 * 1024:  # 10MB limit (same as do_POST)
            self.send_response(413)
            self.end_headers()
            return
        body = self.rfile.read(length) if length else b"{}"
        if self.path.startswith("/api/v1/"):
            from .v1.router import dispatch as _v1_dispatch
            r = _v1_dispatch("PUT", self.path, body=body, headers=self.headers)
            self._json(r, status=r.pop("_status", 200))
        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self):
        if not self._auth_gate():  # MN-8: before any dispatch
            return
        if self.path.startswith("/api/v1/"):
            from .v1.router import dispatch as _v1_dispatch
            r = _v1_dispatch("DELETE", self.path, headers=self.headers)
            self._json(r, status=r.pop("_status", 200))
        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._send_cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
