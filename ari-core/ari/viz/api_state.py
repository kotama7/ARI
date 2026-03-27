from __future__ import annotations
"""ARI viz: api_state."""
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


def _load_nodes_tree() -> dict | None:
    if _st._checkpoint_dir is None:
        return None
    # tree.json has full data (trace_log, memory, code); nodes_tree.json is lightweight export
    p = _st._checkpoint_dir / "tree.json"
    if not p.exists():
        p = _st._checkpoint_dir / "nodes_tree.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None



def _broadcast(data: dict) -> None:
    if not _st._clients or _st._loop is None:
        return
    msg = json.dumps({"type": "update", "data": data,
                       "timestamp": datetime.now(timezone.utc).isoformat()})
    asyncio.run_coroutine_threadsafe(_do_broadcast(msg), _st._loop)



async def _do_broadcast(msg: str) -> None:
    dead = set()
    for ws in list(_st._clients):
        try:
            await ws.send(msg)
        except Exception:
            dead.add(ws)
    _st._clients.difference_update(dead)


# ──────────────────────────────────────────────
# API helpers
# ──────────────────────────────────────────────


def _api_models() -> dict:
    """Return available LLM providers and their model suggestions."""
    return {
        "providers": [
            {"id": "openai",    "name": "OpenAI",     "models": ["gpt-5.2", "gpt-4o", "gpt-4o-mini", "o3", "o1-mini"]},
            {"id": "anthropic", "name": "Anthropic (Claude)", "models": ["claude-opus-4-5", "claude-sonnet-4-5", "claude-3-5-haiku-latest"]},
            {"id": "gemini",    "name": "Google Gemini", "models": ["gemini/gemini-2.5-pro", "gemini/gemini-2.0-flash", "gemini/gemini-1.5-pro"]},
            {"id": "ollama",    "name": "Ollama (Local)", "models": ["ollama_chat/llama3.3", "ollama_chat/qwen3:8b", "ollama_chat/gemma3:9b", "ollama_chat/mistral"]},
        ]
    }



def _api_checkpoints() -> list:
    """List checkpoint directories."""
    ckpt_dirs = []
    search_paths = [
        _st._ari_home / "ari-core" / "checkpoints",
        Path.cwd() / "checkpoints",
        Path.home() / ".ari" / "checkpoints",
    ]
    seen = set()
    for base in search_paths:
        if not base.exists():
            continue
        _SKIP = {"experiments", "__pycache__", ".git"}
        for d in sorted(base.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
            if not d.is_dir() or d in seen or d.name in _SKIP:
                continue
            seen.add(d)
            info = {"id": d.name, "path": str(d), "status": "unknown",
                    "node_count": 0, "review_score": None, "best_metric": None, "mtime": 0}
            try:
                info["mtime"] = int(d.stat().st_mtime)
                # Mark currently active checkpoint as running (PID check)
                if _st._checkpoint_dir and Path(d).resolve() == Path(_st._checkpoint_dir).resolve():
                    if _st._last_proc and _st._last_proc.poll() is None:
                        info["status"] = "running"
                    else:
                        info["status"] = "stopped"
                # Prefer tree.json (has trace_log) over nodes_tree.json
                nt = d / "nodes_tree.json"
                tf = d / "tree.json"
                if tf.exists() and tf.stat().st_size > 0:
                    nt = tf
                if nt.exists() and nt.stat().st_size > 0:
                    try:
                        tree = json.loads(nt.read_text(encoding="utf-8", errors="replace"))
                        nodes = tree.get("nodes", [])
                        info["node_count"] = len(nodes)
                        statuses = {n.get("status") for n in nodes}
                        if "running" in statuses:
                            info["status"] = "running"
                        elif nodes:
                            info["status"] = "completed"
                        # Fallback score from scientific_score if no review
                        if nodes:
                            sci_scores = [n.get("scientific_score") for n in nodes if n.get("scientific_score") is not None]
                            if sci_scores:
                                info["best_scientific_score"] = round(max(sci_scores), 2)
                    except Exception:
                        pass
                rr = d / "review_report.json"
                if rr.exists() and rr.stat().st_size > 0:
                    try:
                        r = json.loads(rr.read_text(encoding="utf-8", errors="replace"))
                        info["review_score"] = r.get("overall_score") or r.get("score")
                        info["status"] = "completed"
                    except Exception:
                        pass
            except Exception:
                pass
            ckpt_dirs.append(info)
    return ckpt_dirs



def _api_checkpoint_summary(ckpt_id: str) -> dict:
    """Return summary for a specific checkpoint."""
    search_paths = [
        _st._ari_home / "ari-core" / "checkpoints" / ckpt_id,
        Path.cwd() / "checkpoints" / ckpt_id,
    ]
    d = None
    for p in search_paths:
        if p.exists():
            d = p
            break
    if d is None:
        return {"error": "not found"}

    result = {"id": ckpt_id, "path": str(d)}
    # Also check repro/ subdir for reproducibility_report.json
    repro_json = d / "reproducibility_report.json"
    if not repro_json.exists():
        repro_json = d / "repro" / "reproducibility_report.json"
    if repro_json.exists() and repro_json.stat().st_size > 0:
        try:
            result["reproducibility_report"] = json.loads(repro_json.read_text())
        except Exception:
            pass

    for fname in ("nodes_tree.json", "review_report.json", "science_data.json",
                  "figures_manifest.json"):
        p = d / fname
        if p.exists() and p.stat().st_size > 0:
            try:
                result[fname.replace(".json", "")] = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except Exception as e:
                result[fname.replace(".json", "")] = {"_parse_error": str(e)}
    # paper tex snippet
    tex = d / "full_paper.tex"
    if tex.exists():
        try:
            result["paper_tex"] = tex.read_text(encoding="utf-8", errors="replace")
            pdf = d / "full_paper.pdf"
            result["has_pdf"] = pdf.exists()
        except Exception:
            result["paper_tex"] = ""
    return result



def _api_delete_checkpoint(body: bytes) -> dict:
    """Delete a checkpoint directory by path."""
    import shutil
    data = json.loads(body)
    path = data.get("path", "")
    if not path:
        return {"error": "path required"}
    p = Path(path)
    # Resolve symlinks (e.g. /home/ → /hs/work0/home/ on RIKEN)
    try:
        p = p.resolve()
    except Exception:
        pass
    if not p.exists():
        # Try without resolving (path might already be canonical)
        p = Path(path)
        if not p.exists():
            return {"error": f"not found: {path}"}
    # Safety: must be inside a checkpoints directory
    if "checkpoints" not in str(p) and "checkpoints" not in str(path):
        return {"error": "refusing to delete outside checkpoints/"}
    try:
        if _st._checkpoint_dir and Path(_st._checkpoint_dir).resolve() == p.resolve():
            _st._checkpoint_dir = None  # Deselect if deleting active checkpoint
        shutil.rmtree(str(p))
        return {"ok": True, "deleted": str(p)}
    except Exception as e:
        return {"error": str(e)}



def _api_switch_checkpoint(body: bytes) -> dict:
    """Switch active checkpoint directory."""
    data = json.loads(body)
    path = data.get("path", "")
    if not path:
        return {"error": "path required"}
    p = Path(path)
    if not p.exists():
        return {"error": f"not found: {path}"}
    _st._checkpoint_dir = p
    _st._last_mtime = 0.0  # force reload
    # Broadcast updated tree immediately
    tree = _load_nodes_tree()
    if tree:
        _broadcast(tree)
    return {"ok": True, "path": str(p)}



def _watcher_thread() -> None:
    while True:
        time.sleep(2)
        if _st._checkpoint_dir is None:
            continue
        for fname in ("nodes_tree.json", "tree.json"):
            p = _st._checkpoint_dir / fname
            if p.exists():
                try:
                    mtime = p.stat().st_mtime
                    if mtime != _st._last_mtime:
                        _st._last_mtime = mtime
                        data = _load_nodes_tree()
                        if data:
                            _broadcast(data)
                except Exception:
                    pass
                break


# ──────────────────────────────────────────────
# WebSocket handler
# ──────────────────────────────────────────────
