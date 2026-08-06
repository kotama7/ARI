from __future__ import annotations
"""ARI viz: HTTP/WebSocket server and main entry point.

Bind policy (gui_refresh task 09, RR-P0-3, MN-4)
------------------------------------------------
The HTTP server and the WebSocket server bind **loopback only** by
default (``127.0.0.1`` and, when available, ``::1`` — both are bound so
distros that resolve ``localhost`` to ``::1`` keep working). The
pre-MN-4 behavior — dual-stack bind on **all interfaces** (``""``) —
exposed every endpoint to the LAN/cluster network with no
authentication.

``ARI_GUI_BIND`` (env kill-switch, ADR-07 register):

* owner: gui_refresh task 09 (security, performance, and operations);
* default: unset — loopback only (``127.0.0.1`` + ``::1``);
* rollback: ``ARI_GUI_BIND='::'`` restores the old all-interfaces
  dual-stack bind (or ``ARI_GUI_BIND='0.0.0.0'`` for IPv4-wildcard
  only, or any single address to bind exactly that interface);
* removal gate: none — loopback-by-default is permanent policy
  (plan 09 §Deployment trust modes: remote exposure must stay an
  explicit opt-in).

Remote token auth (gui_refresh task 09 Wave 5b, RR-P0-3, MN-8, ADR-13)
----------------------------------------------------------------------
A non-loopback ``ARI_GUI_BIND`` activates bearer-token auth for every
HTTP request (except ``/health/*``) and the WS handshake — policy,
``ARI_GUI_TOKEN``/``ARI_GUI_AUTH`` semantics and the ADR-07 kill-switch
register live in ``ari/viz/auth.py``. ``_main`` resolves the token once
at startup; when none was configured the generated token is printed
**once** to stderr by ``_print_generated_token_banner`` (fail-secure —
a remote bind never starts silently unauthenticated) and never logged.
"""

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
# from ``main()`` keeps working without modification.  MN-8 adds the
# handshake auth gate (``_ws_process_request``) next to it.
from .websocket import _ws_handler, _ws_process_request  # noqa: F401

# MN-8 (ADR-13): remote-mode bearer-token auth (policy + token cache).
from . import auth as _auth


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


def resolve_bind_hosts(value: str | None) -> list[str]:
    """Resolve ``ARI_GUI_BIND`` into the list of hosts to bind (MN-4).

    * unset / blank -> loopback default ``["127.0.0.1", "::1"]`` (both
      loopback families, so ``localhost`` works regardless of whether the
      distro resolves it to IPv4 or IPv6);
    * any explicit value -> bind exactly that single host (``"::"`` restores
      the pre-MN-4 all-interfaces dual-stack bind, ``"0.0.0.0"`` gives
      IPv4-wildcard only).

    Pure function so the selection logic is unit-testable without sockets
    (``tests/test_gui_bind_cors.py``).
    """
    if value is None or not value.strip():
        return ["127.0.0.1", "::1"]
    return [value.strip()]


def _make_http_server(host: str, port: int) -> ThreadingHTTPServer:
    """Build one HTTP server for ``host``.

    IPv6 literals (and the legacy ``""`` wildcard) go through
    ``_DualStackServer`` (AF_INET6, V6ONLY off — a no-op for ``::1``);
    everything else is a plain AF_INET ``ThreadingHTTPServer``.
    """
    if host == "" or ":" in host:
        try:
            return _DualStackServer((host, port), _Handler)
        except OSError:
            if host in ("", "::"):
                # IPv6 unavailable (rare on modern Linux) — keep the
                # pre-MN-4 IPv4-only wildcard fallback for the wildcard
                # forms.
                return ThreadingHTTPServer(("", port), _Handler)
            raise
    return ThreadingHTTPServer((host, port), _Handler)


def _bind_http_servers(hosts: list[str], port: int) -> list[ThreadingHTTPServer]:
    """Bind one server per host, tolerating a missing loopback family.

    The loopback default is ``["127.0.0.1", "::1"]``; if one family cannot
    bind (e.g. IPv6 disabled) the GUI still serves on the other. Raises
    only when *no* host binds.
    """
    servers: list[ThreadingHTTPServer] = []
    last_err: OSError | None = None
    for host in hosts:
        try:
            servers.append(_make_http_server(host, port))
        except OSError as e:
            last_err = e
    if not servers:
        raise last_err if last_err is not None else OSError("no bindable host")
    return servers


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
    servers = _bind_http_servers(
        resolve_bind_hosts(os.environ.get("ARI_GUI_BIND")), port
    )
    for extra in servers[1:]:
        threading.Thread(target=extra.serve_forever, daemon=True).start()
    servers[0].serve_forever()


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def _print_generated_token_banner(token: str) -> None:
    """One-time stderr banner for a startup-generated MN-8 token.

    Printed only when the bind is remote and ``ARI_GUI_TOKEN`` was unset
    (fail-secure token generation, ADR-13). stderr only — the token must
    never reach log files, and this is its single appearance.
    """
    import sys
    print(
        "\n"
        "  ============================================================\n"
        "  ARI GUI is bound to a non-loopback address and ARI_GUI_TOKEN\n"
        "  is not set. A random access token was generated for this run\n"
        "  (MN-8, ADR-13). It is printed here ONCE and never logged:\n"
        "\n"
        f"      ARI_GUI_TOKEN={token}\n"
        "\n"
        "  Every request must send 'Authorization: Bearer <token>'\n"
        "  (SSE/WebSocket: '?token=<token>'). Set ARI_GUI_TOKEN to pin\n"
        "  a stable token across restarts.\n"
        "  ============================================================\n",
        file=sys.stderr,
    )


async def _main(checkpoint: Path, port: int) -> None:
    _st.set_active_checkpoint(checkpoint)
    _st._port = port
    _st._loop = asyncio.get_running_loop()

    # MN-8 (ADR-13): resolve the auth token once, before anything binds,
    # so a remote bind is never reachable unauthenticated — not even for
    # the startup window — and the generated-token banner prints once.
    _token, _generated = _auth.init_auth()
    if _generated and _token:
        _print_generated_token_banner(_token)

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

    # MN-4: same bind policy as the HTTP side (loopback unless
    # ARI_GUI_BIND overrides). asyncio's create_server accepts a host
    # sequence, so the loopback default binds 127.0.0.1 and ::1 together.
    ws_hosts = resolve_bind_hosts(os.environ.get("ARI_GUI_BIND"))
    ws_bind: str | list[str] = ws_hosts[0] if len(ws_hosts) == 1 else ws_hosts
    try:
        # MN-8: process_request gates the handshake when remote token auth
        # is active (no-op on the loopback default).
        async with ws_serve(
            _ws_handler, ws_bind, ws_port, process_request=_ws_process_request
        ):
            # MN-9: readiness telemetry for GET /health/ready (health.py).
            _st._ws_server_started = True
            await asyncio.Future()  # run forever
    except OSError:
        if len(ws_hosts) < 2:
            raise
        # Secondary loopback family unavailable (e.g. no ::1) — IPv4 only.
        async with ws_serve(
            _ws_handler, ws_hosts[0], ws_port,
            process_request=_ws_process_request,
        ):
            _st._ws_server_started = True  # MN-9 readiness telemetry
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

