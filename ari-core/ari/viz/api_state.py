from __future__ import annotations
import re
"""ARI viz: api_state — checkpoint discovery, tree loading, broadcasting."""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from . import state as _st

import logging
log = logging.getLogger(__name__)


def _check_pid_alive(checkpoint_dir: Path) -> str:
    """Check if the process that owns a checkpoint is still alive via .ari_pid."""
    from ari.pidfile import check_pid
    return check_pid(checkpoint_dir)


def _load_nodes_tree() -> dict | None:
    if _st._checkpoint_dir is None:
        return None
    # tree.json has full data (trace_log, memory, code); nodes_tree.json is lightweight export
    p = _st._checkpoint_dir / "tree.json"
    if not p.exists():
        p = _st._checkpoint_dir / "nodes_tree.json"
    if not p.exists():
        return None
    # Retry once on parse failure (file may be mid-write)
    for _attempt in range(2):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            if _attempt == 0:
                time.sleep(0.15)
        except Exception:
            log.debug("nodes_tree load error", exc_info=True)
            return None
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
            {"id": "openai",    "name": "OpenAI",     "models": ["gpt-5.4", "gpt-5.2", "gpt-4o", "gpt-4o-mini", "o4-mini", "o3", "o3-mini"]},
            {"id": "anthropic", "name": "Anthropic (Claude)", "models": ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]},
            {"id": "gemini",    "name": "Google Gemini", "models": ["gemini/gemini-2.5-pro", "gemini/gemini-2.0-flash", "gemini/gemini-1.5-pro"]},
            {"id": "ollama",    "name": "Ollama (Local)", "models": ["ollama_chat/llama3.3", "ollama_chat/qwen3:8b", "ollama_chat/gemma3:9b", "ollama_chat/mistral"]},
        ]
    }



def _api_checkpoints() -> list:
    """List checkpoint directories."""
    ckpt_dirs = []
    _ari_root = Path(__file__).parent.parent.parent.parent  # ARI/
    search_paths = [
        Path(__file__).parent.parent.parent / "checkpoints",  # ari-core/checkpoints
        _ari_root / "workspace" / "checkpoints",              # ARI/workspace/checkpoints
        _st._ari_home / "ari-core" / "checkpoints",
        Path.cwd() / "checkpoints",
        Path.home() / ".ari" / "checkpoints",
    ]
    seen = set()
    for base in search_paths:
        if not base.exists():
            continue
        _SKIP = {"experiments", "__pycache__", ".git"}
        _TS_PAT = re.compile(r'^[0-9]{8,14}_')
        for d in sorted(base.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
            if not d.is_dir() or d in seen or d.name in _SKIP:
                continue
            # Only treat directories matching YYYYMMDDHHMMSS_* as valid checkpoints
            if not _TS_PAT.match(d.name):
                continue
            seen.add(d)
            info = {"id": d.name, "path": str(d), "status": "unknown",
                    "node_count": 0, "review_score": None, "best_metric": None, "mtime": 0}
            try:
                info["mtime"] = int(d.stat().st_mtime)
                _resolved = str(Path(d).resolve())
                # Check if this is the active checkpoint with a tracked process
                _is_active = bool(
                    _st._checkpoint_dir
                    and _resolved == str(Path(_st._checkpoint_dir).resolve())
                )
                # Check in-memory process tracking (supports multiple experiments)
                _tracked_proc = _st._running_procs.get(_resolved)
                if _tracked_proc and _tracked_proc.poll() is not None:
                    # Process finished — remove from tracking
                    del _st._running_procs[_resolved]
                    _tracked_proc = None
                _proc_alive = bool(
                    (_is_active and _st._last_proc and _st._last_proc.poll() is None)
                    or _tracked_proc
                )
                # Phase 1: Determine status from process tracking / PID file
                if _proc_alive:
                    info["status"] = "running"
                elif _is_active:
                    info["status"] = "stopped"
                elif not _is_active:
                    # Non-active: check .ari_pid (handles cross-instance case)
                    _pid_status = _check_pid_alive(d)
                    if _pid_status == "running":
                        info["status"] = "running"
                    # else: leave "unknown" for tree.json to refine
                # Phase 2: Refine status from tree.json node data
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
                        # Only refine status when process-based checks left it "unknown"
                        if nodes and info["status"] not in ("running", "stopped"):
                            if "running" in statuses:
                                # Tree says running but no live process → orphaned
                                info["status"] = "stopped"
                            else:
                                info["status"] = "completed"
                        # Fallback score from scientific_score if no review
                        if nodes:
                            sci_scores = [n.get("scientific_score") for n in nodes if n.get("scientific_score") is not None]
                            if sci_scores:
                                info["best_scientific_score"] = round(max(sci_scores), 2)
                    except Exception:
                        log.debug("checkpoint node parsing error: %s", d.name, exc_info=True)
                        pass
                rr = d / "review_report.json"
                if rr.exists() and rr.stat().st_size > 0:
                    try:
                        r = json.loads(rr.read_text(encoding="utf-8", errors="replace"))
                        info["review_score"] = r.get("overall_score") or r.get("score")
                        info["status"] = "completed"
                    except Exception:
                        log.debug("review_report.json parse error: %s", d.name, exc_info=True)
                        pass
            except Exception:
                log.warning("checkpoint listing error: %s", d.name, exc_info=True)
                pass
            ckpt_dirs.append(info)
    return ckpt_dirs



def _api_checkpoint_summary(ckpt_id: str) -> dict:
    """Return summary for a specific checkpoint."""
    _ari_root = Path(__file__).parent.parent.parent.parent  # ARI/
    search_paths = [
        _st._ari_home / "ari-core" / "checkpoints" / ckpt_id,
        _ari_root / "workspace" / "checkpoints" / ckpt_id,
        Path.cwd() / "checkpoints" / ckpt_id,
        Path.cwd() / "ari-core" / "checkpoints" / ckpt_id,
        Path(__file__).resolve().parents[2] / "checkpoints" / ckpt_id,
        Path.home() / ".ari" / "checkpoints" / ckpt_id,
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
            log.debug("reproducibility_report parse error", exc_info=True)
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
    """Delete a checkpoint directory and associated log files."""
    import shutil
    data = json.loads(body)
    path = data.get("path", "")
    if not path:
        return {"error": "path required"}
    p = Path(path)
    # Resolve symlinks (e.g. /home/ may be a symlink on some HPC systems)
    try:
        p = p.resolve()
    except Exception:
        log.debug("path resolve failed: %s", path, exc_info=True)
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
        _resolved_del = str(p.resolve())
        if _st._checkpoint_dir and str(Path(_st._checkpoint_dir).resolve()) == _resolved_del:
            _st._checkpoint_dir = None  # Deselect if deleting active checkpoint
            _st._last_log_path = None   # Clear log path to stop stale log display
            _st._last_experiment_md = None
            _st._last_proc = None       # Clear process ref to stop log streaming
        _st._running_procs.pop(_resolved_del, None)  # Clean up process tracking
        # Collect log files in parent dir that were created around the same time
        parent = p.parent
        deleted_logs = []
        try:
            ckpt_mtime = p.stat().st_mtime
            for log_f in parent.glob("ari_run_*.log"):
                # Delete logs created within 60s of the checkpoint
                if abs(log_f.stat().st_mtime - ckpt_mtime) < 60:
                    log_f.unlink()
                    deleted_logs.append(log_f.name)
        except Exception:
            log.debug("log cleanup error", exc_info=True)
            pass
        shutil.rmtree(str(p))
        # Also clean up zero-byte orphan logs in parent
        try:
            for log_f in parent.glob("ari_run_*.log"):
                if log_f.stat().st_size == 0:
                    log_f.unlink()
                    deleted_logs.append(log_f.name)
        except Exception:
            log.debug("empty log cleanup error", exc_info=True)
            pass
        return {"ok": True, "deleted": str(p), "cleaned_logs": len(deleted_logs)}
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
    # Clear stale project-specific state from previous checkpoint
    if _st._last_log_fh:
        try:
            _st._last_log_fh.close()
        except Exception:
            pass
    _st._last_log_fh = None
    _st._last_experiment_md = None
    # Restore log path from checkpoint (project-isolated log)
    _log_candidates = sorted(
        p.glob("ari_run_*.log"),
        key=lambda f: f.stat().st_mtime, reverse=True
    ) if p.exists() else []
    _log_candidates = [c for c in _log_candidates if c.stat().st_size > 0]
    if _log_candidates:
        _st._last_log_path = _log_candidates[0]
    else:
        _st._last_log_path = None
    # Restore launch_config from checkpoint so /state shows correct values.
    # If launch_config.json does not exist, clear stale config from previous project.
    _lc_path = p / "launch_config.json"
    if _lc_path.exists():
        try:
            _st._launch_config = json.loads(_lc_path.read_text())
            _st._launch_llm_model = _st._launch_config.get("llm_model", "")
            _st._launch_llm_provider = _st._launch_config.get("llm_provider", "")
        except Exception:
            pass
    else:
        _st._launch_config = None
        _st._launch_llm_model = None
        _st._launch_llm_provider = None
    # Broadcast updated tree immediately
    tree = _load_nodes_tree()
    if tree:
        _broadcast(tree)
    return {"ok": True, "path": str(p)}



def _watcher_thread() -> None:
    _last_mtimes: dict[str, float] = {}
    _last_ckpt: "Path | None" = None
    while True:
        time.sleep(1)
        if _st._checkpoint_dir is None:
            continue
        # Reset mtime cache when checkpoint directory changes
        if _st._checkpoint_dir != _last_ckpt:
            _last_mtimes.clear()
            _last_ckpt = _st._checkpoint_dir
        # Check both files for changes (tree.json preferred by _load_nodes_tree)
        changed = False
        for fname in ("tree.json", "nodes_tree.json"):
            p = _st._checkpoint_dir / fname
            if not p.exists():
                continue
            try:
                mtime = p.stat().st_mtime
                if mtime != _last_mtimes.get(fname, 0):
                    _last_mtimes[fname] = mtime
                    changed = True
            except Exception:
                log.debug("watcher mtime check error", exc_info=True)
                pass
        if not changed:
            continue
        data = _load_nodes_tree()
        if data:
            _broadcast(data)


# ──────────────────────────────────────────────
# WebSocket handler
# ──────────────────────────────────────────────
