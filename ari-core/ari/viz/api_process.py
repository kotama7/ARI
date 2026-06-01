"""Experiment process-control service functions (req 05 extraction).

Extracted verbatim from the fat handlers in ``routes.py`` (``/api/stop`` and
``/api/gpu-monitor``). These own the experiment / GPU-monitor subprocess
lifecycle and read/write the shared ``ari.viz.state`` process handles
(``_last_proc``, ``_gpu_monitor_proc``, ``_checkpoint_dir``, ``_settings_path``).

Each function returns a plain ``dict`` (or value); the route handler is
responsible only for serialising it. Behaviour — including signal escalation,
poll/sleep timing, the report shape, and the GPU-monitor response keys — is
preserved byte-for-byte from the pre-extraction handlers. The route keeps the
``ari.viz.state`` reads as direct attribute access (no new setters), so existing
``monkeypatch.setattr(_st, ...)`` test hooks keep working.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import time
from pathlib import Path

from . import state as _st

log = logging.getLogger(__name__)


def _api_gpu_monitor_status() -> dict:
    """GET /api/gpu-monitor — running flag, pid, last 20 log lines, ollama_host.

    Mirrors the pre-extraction handler exactly. NOTE: the route serialises this
    dict with a manual response that does NOT emit Access-Control-Allow-Origin
    (unlike ``_json``); that quirk is preserved by keeping the response-writing
    in the route, not here.
    """
    running = _st._gpu_monitor_proc is not None and _st._gpu_monitor_proc.poll() is None
    pid = _st._gpu_monitor_proc.pid if running else None
    log_tail = ""
    if running:
        try:
            lp = Path.home() / "ARI/logs/gpu_monitor.log"
            if lp.exists():
                lines = lp.read_text().splitlines()
                log_tail = "\n".join(lines[-20:])
        except Exception:
            pass
    oh = ""
    try:
        _sp = _st._settings_path
        s = json.loads(_sp.read_text()) if (_sp is not None and _sp.exists()) else {}
        oh = s.get("ollama_host", "")
    except Exception:
        pass
    return {"running": running, "pid": pid, "log": log_tail, "ollama_host": oh}


def _api_gpu_monitor_action(body: bytes) -> dict:
    """POST /api/gpu-monitor — start/stop the GPU-ollama SLURM monitor.

    ``start`` requires ``confirmed`` (else returns a needs_confirm warning);
    when not already running it launches the monitor script detached and stores
    the handle in ``_st._gpu_monitor_proc``. ``stop`` terminates it.
    """
    data_g = json.loads(body or b'{}')
    action_g = data_g.get("action", "")
    if action_g == "start":
        if not data_g.get("confirmed"):
            return {"ok": False, "needs_confirm": True,
                "msg": "GPU Monitor will continuously submit SLURM jobs. Start only when running a GPU experiment."}
        elif _st._gpu_monitor_proc is None or _st._gpu_monitor_proc.poll() is not None:
            script = Path.home() / "ARI/scripts/gpu_ollama_monitor.sh"
            _gm_log = open(Path.home() / "ARI/logs/gpu_monitor.log", "a")
            _st._gpu_monitor_proc = subprocess.Popen(
                ["bash", str(script)], stdout=_gm_log, stderr=_gm_log,
                start_new_session=True, env=os.environ.copy()
            )
            return {"ok": True, "pid": _st._gpu_monitor_proc.pid}
        else:
            return {"ok": False, "msg": "already running", "pid": _st._gpu_monitor_proc.pid}
    elif action_g == "stop":
        if _st._gpu_monitor_proc and _st._gpu_monitor_proc.poll() is None:
            _st._gpu_monitor_proc.terminate()
        return {"ok": True}
    else:
        return {"ok": False, "msg": "unknown action"}


def _api_stop() -> dict:
    """POST /api/stop — stop all experiment processes.

    Escalates SIGTERM -> SIGKILL on the main experiment (via ``_last_proc`` or
    the checkpoint ``.ari_pid`` fallback), stops the GPU monitor, runs a pkill
    safety net, verifies survivors, and removes the stale PID file. Returns a
    detailed report dict.
    """
    report = {"main": "none", "gpu_monitor": "none", "pkill": []}

    # --- 1. Main experiment process ---
    if _st._last_proc and _st._last_proc.poll() is None:
        pid = _st._last_proc.pid
        # SIGTERM to process group first
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception:
            try: _st._last_proc.terminate()
            except Exception: log.debug("process terminate fallback failed", exc_info=True)
        # Wait up to 5 seconds for graceful shutdown
        for _ in range(50):
            if _st._last_proc.poll() is not None:
                break
            time.sleep(0.1)
        if _st._last_proc.poll() is None:
            # SIGKILL fallback
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except Exception:
                try: _st._last_proc.kill()
                except Exception: log.debug("process kill fallback failed", exc_info=True)
            _st._last_proc.wait(timeout=3)
            report["main"] = f"killed(SIGKILL) pid={pid}"
        else:
            report["main"] = f"stopped(SIGTERM) pid={pid}"
    else:
        # Fallback: GUI restarted or proc handle lost — use .ari_pid
        # from the active checkpoint. Without this, pkill below is the
        # only option and it also kills the GUI process itself.
        from ari.pidfile import read_pid as _read_pid
        _pid = _read_pid(Path(_st._checkpoint_dir)) if _st._checkpoint_dir else None
        if _pid:
            try:
                os.killpg(os.getpgid(_pid), signal.SIGTERM)
            except ProcessLookupError:
                _pid = None  # already gone
            except Exception:
                try: os.kill(_pid, signal.SIGTERM)
                except Exception: log.debug("pidfile SIGTERM failed", exc_info=True)
        if _pid:
            for _ in range(50):
                try:
                    os.kill(_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            try:
                os.kill(_pid, 0)
                # still alive → SIGKILL
                try: os.killpg(os.getpgid(_pid), signal.SIGKILL)
                except Exception: os.kill(_pid, signal.SIGKILL)
                report["main"] = f"killed(SIGKILL) pid={_pid} (via pidfile)"
            except ProcessLookupError:
                report["main"] = f"stopped(SIGTERM) pid={_pid} (via pidfile)"
        else:
            report["main"] = "not running"

    # --- 2. GPU monitor process ---
    if _st._gpu_monitor_proc and _st._gpu_monitor_proc.poll() is None:
        gpu_pid = _st._gpu_monitor_proc.pid
        _st._gpu_monitor_proc.terminate()
        for _ in range(20):
            if _st._gpu_monitor_proc.poll() is not None:
                break
            time.sleep(0.1)
        if _st._gpu_monitor_proc.poll() is None:
            _st._gpu_monitor_proc.kill()
            _st._gpu_monitor_proc.wait(timeout=3)
            report["gpu_monitor"] = f"killed(SIGKILL) pid={gpu_pid}"
        else:
            report["gpu_monitor"] = f"stopped(SIGTERM) pid={gpu_pid}"
    else:
        report["gpu_monitor"] = "not running"

    # --- 3. pkill safety net ---
    for pattern in ["ari-skill", "ari.cli"]:
        try:
            r = subprocess.run(["pkill", "-f", pattern], capture_output=True, timeout=3)
            if r.returncode == 0:
                report["pkill"].append(f"{pattern}: killed")
            else:
                report["pkill"].append(f"{pattern}: no match")
        except Exception as e:
            report["pkill"].append(f"{pattern}: error({e})")

    # --- 4. Verify no survivors ---
    time.sleep(0.3)
    survivors = []
    for pattern in ["ari-skill", "ari.cli", "gpu_ollama_monitor"]:
        try:
            r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and r.stdout.strip():
                pids = r.stdout.strip().split("\n")
                survivors.append({"pattern": pattern, "pids": pids})
        except Exception:
            pass
    report["survivors"] = survivors

    # Clean up PID file (may be stale after SIGKILL)
    if _st._checkpoint_dir:
        from ari.pidfile import remove_pid as _rm_pid
        _rm_pid(Path(_st._checkpoint_dir))

    stopped = report["main"] != "not running"
    return {"ok": True, "stopped": stopped, "report": report}
