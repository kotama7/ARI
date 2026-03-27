from __future__ import annotations
"""ARI viz: api_experiment."""
"""ARI Experiment Tree Visualizer — WebSocket + HTTP server.

Usage:
    python -m ari.viz.server --checkpoint ./logs/my_ckpt/ [--port 8765]
"""


import argparse
import asyncio
import json
import re
import os
import subprocess
import threading
import time
import urllib.parse
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



from . import state as _st


def _api_run_stage(body: bytes) -> dict:
    """Run a specific ARI stage (resume/paper/review) on the active checkpoint."""
    data = json.loads(body) if body else {}
    stage = data.get("stage", "paper")
    ckpt = str(_st._checkpoint_dir) if _st._checkpoint_dir else ""
    if not ckpt:
        return {"ok": False, "error": "No active checkpoint"}
    if stage == "resume":
        cmd = ["python3", "-m", "ari.cli", "resume", ckpt]
    elif stage == "paper":
        cmd = ["python3", "-m", "ari.cli", "paper", ckpt]
    elif stage == "review":
        cmd = ["python3", "-m", "ari.cli", "review", ckpt]
    else:
        return {"ok": False, "error": f"Unknown stage: {stage}"}
    try:
        _st._last_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(Path(ckpt).parent.resolve()),
            env={**__import__("os").environ},
        )
        return {"ok": True, "pid": _st._last_proc.pid, "stage": stage, "cmd": " ".join(cmd)}
    except Exception as e:
        return {"ok": False, "error": str(e)}



def _api_launch(body: bytes) -> dict:
    data = json.loads(body)
    config_path = data.get("config_path", "experiment.md")
    profile = data.get("profile", "")
    experiment_md = data.get("experiment_md", "")
    # Write experiment.md if content provided
    if experiment_md:
        try:
            Path(config_path).write_text(experiment_md, encoding="utf-8")
        except Exception as e:
            return {"ok": False, "error": f"Failed to write experiment file: {e}"}
    _st._last_experiment_md = experiment_md or (Path(config_path).read_text(encoding="utf-8") if Path(config_path).exists() else "")
    # Also write experiment.md content into checkpoints/ dir as a fallback marker
    try:
        _ckpt_root = Path(config_path).parent.resolve() / "checkpoints"
        _ckpt_root.mkdir(parents=True, exist_ok=True)
        (_ckpt_root / "experiment.md").write_text(_st._last_experiment_md, encoding="utf-8")
    except Exception:
        pass
    if not Path(config_path).exists():
        return {"ok": False, "error": f"Experiment file not found: {config_path}"}
    cmd = ["python3", "-m", "ari.cli", "run", config_path]
    if profile:
        cmd += ["--profile", profile]
    try:
        import os
        proc_cwd = str(Path(config_path).parent.resolve())
        # Build env: inherit + load ~/.env if OPENAI_API_KEY not set
        proc_env = os.environ.copy()
        env_path = Path.home() / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k = k.strip(); v = v.strip()
                    if k not in proc_env or not proc_env[k]:
                        proc_env[k] = v
        # Inject model from saved Settings
        try:
            if _st._settings_path.exists():
                saved = json.loads(_st._settings_path.read_text())
                llm_model = saved.get("llm_model", "")
                llm_provider = saved.get("llm_provider", "")
                if llm_model:
                    proc_env["ARI_MODEL"] = llm_model
                    proc_env["ARI_LLM_MODEL"] = llm_model
                if llm_provider:
                    proc_env["ARI_BACKEND"] = llm_provider
                if llm_provider == "openai" and saved.get("api_key"):
                    proc_env["OPENAI_API_KEY"] = saved["api_key"]
                if llm_provider == "ollama":
                    # Pass the real Ollama URL directly — ollama SDK strips path from OLLAMA_HOST
                    # so proxy routing via /api/ollama path doesn't work
                    _real_ollama = saved.get("ollama_host", "").strip() or "http://localhost:11434"
                    proc_env["OLLAMA_HOST"] = _real_ollama
                # Per-skill model overrides → ARI_MODEL_IDEA, ARI_MODEL_CODING, etc.
                for skill in ["idea","bfts","coding","eval","paper","review"]:
                    val = saved.get(f"model_{skill}", "")
                    if val:
                        proc_env[f"ARI_MODEL_{skill.upper()}"] = val
        except Exception:
            pass
        # Per-phase model overrides from wizard Advanced section
        phase_models = data.get("phase_models", {}) or {}
        for phase, model in phase_models.items():
            if model:
                proc_env[f"ARI_MODEL_{phase.upper()}"] = model
        # Per-experiment default model override (from wizard) takes precedence over Settings
        wiz_model = data.get("llm_model", "") or data.get("model", "")
        wiz_provider = data.get("llm_provider", "")
        if wiz_model:
            proc_env["ARI_MODEL"] = wiz_model
            proc_env["ARI_LLM_MODEL"] = wiz_model
        # Provider override: set regardless of whether model is specified
        if wiz_provider:
            proc_env["ARI_BACKEND"] = wiz_provider
        import time
        log_path = Path(proc_cwd) / "checkpoints" / f"ari_run_{int(time.time())}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _st._last_log_path = log_path
        _st._last_log_fh = open(log_path, "w")  # keep alive as global to prevent GC close
        _st._last_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=_st._last_log_fh,
            stderr=_st._last_log_fh,
            text=True,
            cwd=proc_cwd,
            env=proc_env,
            start_new_session=True,  # detach from server's process group
        )
        # Watch for new checkpoint directory in background
        def _watch_for_checkpoint(ckpt_root: str, before: set):
            import time, threading
            def _watch():
                for _ in range(600):  # poll for up to 10 minutes
                    time.sleep(3)
                    try:
                        current = {d.name for d in Path(ckpt_root).iterdir() if d.is_dir()}
                        new_dirs = current - before
                        if new_dirs:
                            newest = sorted(
                                [Path(ckpt_root) / n for n in new_dirs],
                                key=lambda p: p.stat().st_mtime, reverse=True
                            )[0]
                            _st._checkpoint_dir = newest
                            _st._last_mtime = 0  # force refresh
                            break
                    except Exception:
                        pass
            t = threading.Thread(target=_watch, daemon=True)
            t.start()
        # Detect existing checkpoints before launch
        ckpt_root = Path(proc_cwd) / "checkpoints"
        if not ckpt_root.exists():
            ckpt_root = Path.cwd() / "checkpoints"
        existing = {d.name for d in ckpt_root.iterdir() if d.is_dir()} if ckpt_root.exists() else set()
        _watch_for_checkpoint(str(ckpt_root), existing)
        return {"ok": True, "pid": _st._last_proc.pid, "checkpoint_root": str(ckpt_root)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


_st._last_log_path = None
_st._gpu_monitor_proc = None
_st._last_log_fh = None


def _api_logs_sse(wfile) -> None:
    """Stream logs via SSE: tries log file, then checkpoint dir files."""
    import time
    start_msg = b"data: " + json.dumps({"msg": "Log stream started"}).encode() + b"\n\n"
    wfile.write(start_msg)
    wfile.flush()
    try:
        sent = 0
        ckpt_sent = 0
        last_log_seen = None  # track which file we're reading
        for _ in range(600):  # tail for up to 10 min
            # Always re-resolve log file (handles new experiments starting)
            log_file = _st._last_log_path
            if not log_file or not log_file.exists() or log_file.stat().st_size == 0:
                # Search in _st._checkpoint_dir or fallback to cwd/checkpoints/
                _search_root = (_st._checkpoint_dir.parent if _st._checkpoint_dir and _st._checkpoint_dir.exists()
                                else Path.cwd() / "checkpoints")
                if _search_root.exists():
                    candidates = sorted(
                        _search_root.glob("ari_run_*.log"),
                        key=lambda p: p.stat().st_mtime, reverse=True
                    )
                    # Skip zero-byte logs
                    candidates = [c for c in candidates if c.stat().st_size > 0]
                    if candidates:
                        log_file = candidates[0]
            # Reset sent count when log file changes (new experiment)
            if log_file != last_log_seen:
                sent = 0
                last_log_seen = log_file
                if log_file:
                    msg = json.dumps({"msg": f"--- Switched to log: {log_file.name} ---"})
                    wfile.write(b"data: " + msg.encode() + b"\n\n")
                    wfile.flush()
            if log_file and log_file.exists():
                text = log_file.read_text(encoding="utf-8", errors="replace")
                lines = text.splitlines()
                for line in lines[sent:]:
                    if line.strip():
                        # Strip ANSI escape codes
                        import re as _re_ansi
                        clean = _re_ansi.sub(r"\x1b\[[0-9;]*[mGKHF]|\x1b\[\?[0-9]+[hl]|\x1b\([AB]", "", line)
                        msg = json.dumps({"msg": clean})
                        wfile.write(b"data: " + msg.encode() + b"\n\n")
                        wfile.flush()
                sent = len(lines) if log_file else sent
            # Tail checkpoint cost_trace and nodes_tree for live progress
            if _st._checkpoint_dir and _st._checkpoint_dir.exists():
                ct = _st._checkpoint_dir / "cost_trace.jsonl"
                if ct.exists():
                    lines = ct.read_text(encoding="utf-8", errors="replace").splitlines()
                    for line in lines[ckpt_sent:]:
                        try:
                            d2 = json.loads(line)
                            skill = d2.get("skill","") or d2.get("phase","")
                            model = d2.get("model","")
                            tok = d2.get("total_tokens",0)
                            ts = d2.get("timestamp","")[-8:]
                            nid = d2.get("node_id","")
                            txt = f"[{ts}] {skill or 'thinking'} | model={model.split('/')[-1]} tokens={tok}" + (f" node={nid[:8]}" if nid else "")
                            msg = json.dumps({"msg": txt})
                            wfile.write(b"data: " + msg.encode() + b"\n\n")
                            wfile.flush()
                        except Exception:
                            pass
                    ckpt_sent = len(lines)
            # Check if process done
            if _st._last_proc and _st._last_proc.poll() is not None:
                break
            time.sleep(1)
    except Exception:
        pass
    wfile.write(b"data: " + json.dumps({"msg": "[end of log]"}).encode() + b"\n\n")
    wfile.flush()


