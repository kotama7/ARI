from __future__ import annotations
"""ARI viz: HTTP/WebSocket server and main entry point."""

import argparse
import asyncio
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import logging

try:
    import websockets
    from websockets.server import serve as ws_serve
except ImportError:
    raise SystemExit("websockets package required: pip install websockets")

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Shared state
# ──────────────────────────────────────────────



from . import state as _st
from .api_state import _load_nodes_tree, _broadcast, _do_broadcast, _api_models, _api_checkpoints, _api_checkpoint_summary, _api_delete_checkpoint, _api_switch_checkpoint, _api_ear, _watcher_thread, _api_checkpoint_files, _api_checkpoint_file_read, _api_checkpoint_file_save, _api_checkpoint_file_upload, _api_checkpoint_file_delete, _api_checkpoint_compile, _resolve_paper_file, _api_checkpoint_filetree, _api_checkpoint_filecontent, _api_checkpoint_memory, _resolve_checkpoint_dir, _api_lineage_decisions
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


# Phase 3B (viz/REFACTORING.md §2 Step 1): WebSocket handler lives in
# ``ari.viz.websocket``.  Re-exported here so the existing reference
# from ``main()`` keeps working without modification.
from .websocket import _ws_handler  # noqa: F401


# ──────────────────────────────────────────────
# HTTP server (serves React dashboard build)
# ──────────────────────────────────────────────
DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"
REACT_DIST_DIR = Path(__file__).parent / "static" / "dist"
REACT_INDEX = REACT_DIST_DIR / "index.html"


# Phase 3B (viz/REFACTORING.md §2 Step 1): UI helpers live in
# ``ari.viz.ui_helpers``.  ``_REDACT_KEYS`` is also re-exported here
# because the older route-handler chain inside this file uses the
# constant in-place; the new module owns the canonical copy.
from .ui_helpers import (  # noqa: F401
    _REDACT_KEYS,
    _build_experiment_detail_config,
    _collect_resource_metrics,
    _extract_goal_from_md,
)


import socket as _socket

# Phase 3B PR-3B-1: HTTP request handler + access log live in
# ``ari.viz.routes``.
from .routes import _Handler, _write_access_log  # noqa: F401



class _DualStackServer(ThreadingHTTPServer):
    """Bind a single IPv6 socket that also accepts IPv4 connections.

    Distros that resolve `localhost` to ::1 (e.g. systemd-resolved overriding
    /etc/hosts) get ERR_CONNECTION_REFUSED otherwise, since plain "" + AF_INET
    only listens on 0.0.0.0.
    """
    address_family = _socket.AF_INET6

    def server_bind(self) -> None:
        try:
            self.socket.setsockopt(_socket.IPPROTO_IPV6, _socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        super().server_bind()


_access_log_lock = threading.Lock()


_st._server_port: int = 9886  # default; updated when server starts


def _http_thread(port: int) -> None:
    _st._server_port = port
    # Clean up any orphaned GPU monitor from previous server run
    _pid_file = Path.home() / 'ARI/logs/gpu_monitor.pid'
    if _pid_file.exists():
        try:
            _old_pid = int(_pid_file.read_text().strip())
            import os as _os_gm2
            try:
                _os_gm2.kill(_old_pid, 9)
            except ProcessLookupError:
                pass
        except Exception:
            pass
        try:
            _pid_file.unlink()
        except Exception:
            pass
    # Auto-restore last checkpoint on startup (use _api_checkpoints for consistency)
    if _st._checkpoint_dir is None:
        try:
            _all_ckpts = _api_checkpoints()
            if _all_ckpts:
                _newest = max(_all_ckpts, key=lambda c: c.get("mtime", 0))
                _np = Path(_newest["path"])
                if _np.exists():
                    _st.set_active_checkpoint(_np)
                    _st._last_mtime = 0.0
                    # Restore launch config from checkpoint or parent dir
                    for _lc_cand in [_np / "launch_config.json", _np.parent / "launch_config.json"]:
                        if _lc_cand.exists():
                            try:
                                _st._launch_config = json.loads(_lc_cand.read_text())
                                _st._launch_llm_model = _st._launch_config.get("llm_model", "")
                                _st._launch_llm_provider = _st._launch_config.get("llm_provider", "")
                                break
                            except Exception:
                                pass
        except Exception:
            pass
            import logging
            logging.getLogger(__name__).info(f"Auto-restored checkpoint: {_st._checkpoint_dir.name}")
    try:
        srv = _DualStackServer(("", port), _Handler)
    except OSError:
        # IPv6 unavailable (rare on modern Linux) — fall back to IPv4-only.
        srv = ThreadingHTTPServer(("", port), _Handler)
    srv.serve_forever()


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

async def _main(checkpoint: Path, port: int) -> None:
    _st.set_active_checkpoint(checkpoint)
    _st._port = port
    _st._loop = asyncio.get_running_loop()

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
    ap.add_argument("--checkpoint", required=False, default=None, type=Path,
                    help="Path to checkpoint directory (optional; can be selected in GUI)")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    if args.checkpoint and not args.checkpoint.exists():
        raise SystemExit(f"Checkpoint not found: {args.checkpoint}")

    try:
        asyncio.run(_main(args.checkpoint or None, args.port))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()

