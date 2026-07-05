"""HTTP request handler + access log (Phase 3B PR-3B-1).

Hosts the ``_Handler`` class (do_GET / do_POST dispatch) and the
``_write_access_log`` helper extracted from ``ari/viz/server.py``.
The dispatch chain inside ``do_GET`` / ``do_POST`` is preserved
verbatim so the HTTP routing order is byte-for-byte identical to
the pre-Phase-3B build.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import websockets
from websockets.server import serve as ws_serve

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


# Phase 3B PR-3B-1: shared access-log lock so concurrent requests don't
# interleave their viz_access.jsonl lines.
_access_log_lock = threading.Lock()




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
                "path": getattr(self, "path", None) or "-",
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
        self.end_headers()
        self.wfile.write(html_bytes)

    def do_OPTIONS(self):
        """Handle CORS preflight requests.

        When users access the dashboard through SSH tunnels, reverse proxies,
        or HPC web portals the browser may treat API calls as cross-origin and
        send a preflight OPTIONS request before the actual POST.  Without this
        handler, Python returns 501 and the browser blocks the request with
        'TypeError: Failed to fetch'.
        """
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Filename")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
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
                ct = {
                    'css': 'text/css', 'js': 'application/javascript',
                    'html': 'text/html', 'svg': 'image/svg+xml',
                    'png': 'image/png', 'jpg': 'image/jpeg',
                    'woff': 'font/woff', 'woff2': 'font/woff2',
                }.get(ext, 'application/octet-stream')
                data = fpath.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(data)))
                # Hashed asset filenames from Vite get long-term caching
                if "/dist/assets/" in self.path:
                    self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                else:
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
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
            self.send_header("Access-Control-Allow-Origin", "*")
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
            # Serve file content for artifact file paths
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            fpath = qs.get("path", [""])[0]
            try:
                p = Path(fpath).resolve()
                # Security: allow files inside active checkpoint or any checkpoints/ dir
                allowed = False
                if _st._checkpoint_dir:
                    try:
                        p.relative_to(_st._checkpoint_dir.resolve())
                        allowed = True
                    except ValueError:
                        pass
                if not allowed and "checkpoints" in str(p):
                    # Also allow any file under a checkpoints/ directory
                    for parent in p.parents:
                        if parent.name == "checkpoints":
                            allowed = True
                            break
                if allowed and p.exists() and p.is_file() and p.stat().st_size < 20_000_000:
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
                self.send_header("Access-Control-Allow-Origin", "*")
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
                    self.send_header("Access-Control-Allow-Origin", "*")
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
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
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
                self.send_header("Access-Control-Allow-Origin", "*")
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
                        if snap.get("status") in ("completed", "failed"):
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
        else:
            # SPA fallback: serve React index.html for client-side routing
            if not self.path.startswith("/api/"):
                self._serve_spa_index()
            else:
                self.send_response(404)
                self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > 10 * 1024 * 1024:  # 10MB limit
            self.send_response(413)
            self.end_headers()
            return
        body = self.rfile.read(length) if length else b"{}"
        if self.path == "/api/settings":
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
            self._json(_api_save_env_key(body))
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
        elif self.path.startswith("/api/ollama/"):
            _ollama_proxy(self)
            return
        elif self.path == "/api/gpu-monitor":
            self._json(_api_gpu_monitor_action(body))
        elif self.path == "/api/stop":
            self._json(_api_stop())
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
            self._json(_api_delete_checkpoint(body))
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

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
