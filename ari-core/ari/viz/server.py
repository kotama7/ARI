from __future__ import annotations
"""ARI viz: HTTP handler & main."""
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
from .api_state import _load_nodes_tree, _broadcast, _do_broadcast, _api_models, _api_checkpoints, _api_checkpoint_summary, _api_delete_checkpoint, _api_switch_checkpoint, _watcher_thread
from .api_settings import _api_get_env_keys, _api_save_env_key, _api_get_settings, _api_save_settings, _api_get_workflow, _api_save_workflow, _api_skill_detail, _api_skills, _api_profiles, _api_detect_scheduler
from .api_experiment import _api_run_stage, _api_launch, _api_logs_sse
from .api_ollama import _api_ollama_resources, _ollama_proxy
from .api_tools import _api_chat_goal, _api_generate_config, _api_upload_file, _api_ssh_test


async def _ws_handler(websocket) -> None:
    _st._clients.add(websocket)
    try:
        # Send current state on connect
        data = _load_nodes_tree()
        if data:
            await websocket.send(json.dumps({
                "type": "update", "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))
        async for _ in websocket:
            pass  # ignore incoming messages
    finally:
        _st._clients.discard(websocket)


# ──────────────────────────────────────────────
# HTTP server (serves dashboard.html)
# ──────────────────────────────────────────────
DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"



class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # suppress request logs
        pass

    def do_GET(self):
        if self.path in ("/logo.png", "/logo"):
            logo_candidates = [
                _st._ari_home / "docs" / "logo.png",
                Path(__file__).parent.parent.parent.parent / "docs" / "logo.png",
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
            if DASHBOARD_PATH.exists():
                html = DASHBOARD_PATH.read_text(encoding="utf-8")
                # Inject project list server-side so it's ready before JS runs
                try:
                    projects = _api_checkpoints()
                    active_path = str(_st._checkpoint_dir) if _st._checkpoint_dir else ""
                    active_id = Path(active_path).name if active_path else ""
                    opts = ['<option value="">— select project —</option>']
                    for c in projects:
                        cid = c["id"]
                        label = cid + (f" ({c['node_count']} nodes)" if c.get("node_count") else "")
                        sel = ' selected' if cid == active_id else ''
                        opts.append(f'<option value="{c["path"]}"{sel}>{label}</option>')
                    opts_html = "".join(opts)
                    html = html.replace(
                        '<option value="">Loading…</option>',
                        opts_html
                    )
                    # Inject active id into project-status
                    if active_id:
                        disp = (active_id[:20] + "...") if len(active_id) > 22 else active_id
                        html = html.replace(
                            '<div class="project-status" id="project-status">—</div>',
                            f'<div class="project-status" id="project-status">{disp}</div>'
                        )
                except Exception:
                    pass
                html_bytes = html.encode("utf-8")
            else:
                html_bytes = b"<h1>dashboard.html not found</h1>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(html_bytes)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("ETag", str(DASHBOARD_PATH.stat().st_mtime if DASHBOARD_PATH.exists() else 0))
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(html_bytes)
        elif self.path.startswith("/static/"):
            fname = self.path[len("/static/"):]
            static_dir = Path(__file__).parent / "static"
            fpath = static_dir / fname
            if fpath.exists() and fpath.is_file():
                ext = fpath.suffix.lower().lstrip('.')
                ct = {'css': 'text/css', 'js': 'application/javascript'}.get(ext, 'application/octet-stream')
                data = fpath.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404); self.end_headers()
        elif self.path.startswith("/memory/"):
            node_id = self.path[len("/memory/"):]
            try:
                node_id = urllib.parse.unquote(node_id)
                store = Path("~/.ari/memory_store.jsonl").expanduser()
                entries = []
                if store.exists():
                    for line in store.read_text().splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            e = json.loads(line)
                            # Match by exact ID or by partial suffix (short IDs in dashboard)
                            _eid = e.get("node_id", "")
                            if _eid == node_id or _eid.endswith(node_id) or node_id.endswith(_eid):
                                entries.append({"text": e.get("text",""), "metadata": e.get("metadata",{})})
                        except Exception:
                            pass
                payload = json.dumps({"entries": entries}, ensure_ascii=False).encode()
            except Exception as ex:
                payload = json.dumps({"entries": [], "error": str(ex)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)
        elif self.path == "/state":
            data = _load_nodes_tree() or {}
            # Inject file-based phase flags
            if _st._checkpoint_dir:
                d = Path(_st._checkpoint_dir)
                data["has_paper"] = (d / "full_paper.tex").exists()
                data["has_pdf"]   = (d / "full_paper.pdf").exists()
                data["has_review"] = (d / "review_report.json").exists()
                # Detect current running phase
                import glob as _glob
                _nt = json.loads((d/"nodes_tree.json").read_text()) if (d/"nodes_tree.json").exists() else {}
                _nodes = _nt.get("nodes", _nt) if isinstance(_nt, dict) else _nt
                _has_nodes = bool(_nodes and len(_nodes) > 0)
                # Fallback: also check tree.json nodes if nodes_tree.json missing
                if not _has_nodes and isinstance(data, dict) and "nodes" in data:
                    _tree_nodes = data.get("nodes", [])
                    if _tree_nodes:
                        _has_nodes = True
                        data["node_count"] = len(_tree_nodes)
                    else:
                        data["node_count"] = 0
                else:
                    data["node_count"] = len(_nodes) if _nodes else 0
                _has_idea  = (d/"idea.json").exists() or (d/"science_data.json").exists()
                _has_code  = bool(_glob.glob(str(d/"**/*.py"), recursive=True) + _glob.glob(str(d/"**/*.f90"), recursive=True))
                _has_eval  = any((d/n).exists() for n in ["evaluation.json","eval_results.json","results.json"])
                _running_pid = data.get("running_pid")
                # Phase detection (ordered)
                if data["has_review"]:
                    _phase = "review"
                elif data["has_paper"]:
                    _phase = "paper"
                elif _has_eval:
                    _phase = "evaluation"
                elif _has_code:
                    _phase = "coding"
                elif _has_nodes:
                    _phase = "bfts"
                elif _has_idea:
                    _phase = "idea"
                elif _running_pid:
                    _phase = "starting"
                else:
                    _phase = "idle"
                data["current_phase"] = _phase
                # Load actual running models from cost_trace
                _ct2 = _st._checkpoint_dir / "cost_trace.jsonl"
                _actual_mods = {}
                if _ct2.exists():
                    try:
                        import json as _jj
                        for _ln in _ct2.read_text().splitlines()[-30:]:
                            if _ln.strip():
                                _ee = _jj.loads(_ln)
                                if _ee.get("skill") and _ee.get("model"):
                                    _actual_mods[_ee["skill"]] = _ee["model"]
                    except Exception: pass
                data["actual_models"] = _actual_mods
                _all_mods = list(set(_actual_mods.values()))
                data["llm_model_actual"] = _all_mods[0] if len(_all_mods)==1 else (", ".join(_all_mods) if _all_mods else None)
                data["phase_flags"] = {
                    "idea": _has_idea,
                    "bfts": _has_nodes,
                    "coding": _has_code,
                    "evaluation": _has_eval,
                    "paper": data["has_paper"],
                    "review": data["has_review"],
                }
                def _check_repro(d):
                    if (d / "reproducibility_report.json").exists(): return True
                    if (d / "repro" / "reproducibility_report.json").exists(): return True
                    # repro/run dir with output = done
                    repro_run = d / "repro" / "run"
                    if repro_run.is_dir() and any(repro_run.iterdir()): return True
                    # repro_output.log with content > 100 bytes
                    repro_log = d / "repro" / "repro_output.log"
                    if repro_log.exists() and repro_log.stat().st_size > 100: return True
                    return False
                data["has_repro"] = _check_repro(d)
                # Inject idea/config info
                for f in ["experiment.md", "goal.md"]:
                    fp = d / f
                    if fp.exists():
                        try:
                            data["experiment_text"] = fp.read_text(encoding="utf-8")[:3000]
                        except Exception:
                            pass
                        break
                wf = d / "workflow.yaml"
                if wf.exists():
                    try:
                        data["workflow_yaml"] = wf.read_text(encoding="utf-8")[:2000]
                    except Exception:
                        pass
                # Checkpoint path for resume
                data["checkpoint_path"] = str(d)
                data["checkpoint_id"] = d.name
                # Inject cost summary
                cost_f = d / "cost_summary.json"
                if cost_f.exists():
                    try:
                        data["cost"] = json.loads(cost_f.read_text())
                    except Exception:
                        pass
                # Inject experiment.md (actual config) into state
                _exp_md = ""
                # Try 1: checkpoint dir itself
                for fname in ("experiment.md", "config.md"):
                    f = d / fname
                    if f.exists():
                        _exp_md = f.read_text(encoding="utf-8", errors="replace")
                        break
                # Try 2: experiments/exp/node_{run_id}_root/experiment.md
                if not _exp_md:
                    run_id = d.name  # e.g. 9f55db693c85
                    exp_dir = d.parent.parent / "experiments" / "exp" / f"node_{run_id}_root"
                    for fname in ("experiment.md", "config.md"):
                        f2 = exp_dir / fname
                        if f2.exists():
                            _exp_md = f2.read_text(encoding="utf-8", errors="replace")
                            break
                # Try 3: project root experiment.md (cwd)
                if not _exp_md:
                    f3 = Path.cwd() / "experiment.md"
                    if f3.exists():
                        _exp_md = f3.read_text(encoding="utf-8", errors="replace")
                # Only inject if we actually have a checkpoint (don't show stale files)
                if not _exp_md and _st._last_experiment_md:
                    _exp_md = _st._last_experiment_md
                if _exp_md:
                    data["experiment_md_content"] = _exp_md[:4000]
                if not data.get("experiment_md_path"):
                    data["experiment_md_path"] = str(d / "experiment.md")
                # Inject experiment_config: key settings for display
                try:
                    import yaml as _yaml
                    _wf_cfg = {}
                    # Try checkpoint workflow.yaml, then default
                    _config_root = Path(__file__).parent.parent.parent / "config"
                    for _wf_path in [d / "workflow.yaml",
                                     _config_root / "profiles" / "hpc.yaml",
                                     _config_root / "default.yaml"]:
                        if _wf_path.exists():
                            _tmp = _yaml.safe_load(_wf_path.read_text()) or {}
                            if _tmp.get("bfts") or _tmp.get("hpc"):
                                _wf_cfg = _tmp
                                break
                    _bfts = _wf_cfg.get("bfts", {})
                    _hpc  = _wf_cfg.get("hpc", {})
                    saved2 = _api_get_settings()
                    # Merge default.yaml for missing fields
                    _default_cfg = {}
                    _default_yaml = _config_root / "default.yaml"
                    if _default_yaml.exists():
                        _default_cfg = _yaml.safe_load(_default_yaml.read_text()) or {}
                    _default_bfts = _default_cfg.get("bfts", {})
                    # Merge default + profile configs for full detail
                    import copy as _copy
                    _merged = _copy.deepcopy(_default_cfg)
                    for _k, _v in _wf_cfg.items():
                        if isinstance(_v, dict) and isinstance(_merged.get(_k), dict):
                            _merged[_k].update(_v)
                        else:
                            _merged[_k] = _v
                    # Override LLM info from settings
                    _merged.setdefault("llm", {})
                    _merged["llm"]["model"]   = saved2.get("llm_model", "?")
                    _merged["llm"]["backend"] = saved2.get("llm_provider", "?")
                    _merged["llm"]["base_url"] = saved2.get("ollama_host", "?")
                    _backend = saved2.get("llm_provider", "?")
                    data["experiment_config"] = {
                        "llm_model":       saved2.get("llm_model", "?"),
                        "llm_backend":     _backend,
                        "ollama_host":     saved2.get("ollama_host", "?") if _backend == "ollama" else "(n/a)",
                        "max_nodes":       _bfts.get("max_total_nodes",      _default_bfts.get("max_total_nodes", "?")),
                        "max_depth":       _bfts.get("max_depth",            _default_bfts.get("max_depth", "?")),
                        "parallel":        _bfts.get("parallel",             _default_bfts.get("max_parallel_nodes", "?")),
                        "timeout_node_s":  _bfts.get("timeout_per_node",    _default_bfts.get("timeout_per_node", "?")),
                        "retries":         _bfts.get("max_retries_per_node", _default_bfts.get("max_retries_per_node", "?")),
                        "score_threshold": _bfts.get("score_threshold",      _default_bfts.get("score_threshold", "?")),
                        "scheduler":       _hpc.get("scheduler", "local"),
                        "partition":       _hpc.get("partition", "local"),
                        "cpus":            _hpc.get("cpus_per_task", "-"),
                        "memory_gb":       _hpc.get("memory_gb", "-"),
                        "walltime":        _hpc.get("walltime", "-"),
                    }
                    # Full YAML detail for display
                    _detail_lines = []
                    _REDACT_KEYS = {"api_key", "apikey", "api-key", "token", "secret", "password"}
                    for _sk, _sv in _merged.items():
                        if _sk == "skills": continue  # skip skills list (too long)
                        if isinstance(_sv, dict):
                            _detail_lines.append(f"[{_sk}]")
                            for _dk, _dv in _sv.items():
                                if _dk.lower() in _REDACT_KEYS or "key" in _dk.lower():
                                    _detail_lines.append(f"  {_dk}: ***")
                                else:
                                    _detail_lines.append(f"  {_dk}: {_dv}")
                        else:
                            _detail_lines.append(f"{_sk}: {_sv}")
                    data["experiment_detail_config"] = "\n".join(_detail_lines)
                except Exception:
                    pass

                # Inject experiment_context + best_nodes from science_data.json
                sci_f = d / "science_data.json"
                if sci_f.exists():
                    try:
                        sci = json.loads(sci_f.read_text())
                        data["experiment_context"] = sci.get("experiment_context", {})
                        confs = sci.get("configurations", [])
                        if confs:
                            data["best_nodes"] = confs[:3]
                            # Collect all unique metric keys (non-underscore)
                            all_keys = set()
                            for c in confs:
                                for k in (c.get("metrics") or {}).keys():
                                    if not k.startswith("_"):
                                        all_keys.add(k)
                            data["all_metric_keys"] = sorted(all_keys)
                    except Exception:
                        pass
                # Inject experiment goal from experiment.md or results.json
                goal_f = d / "results.json"
                if goal_f.exists() and not data.get("experiment_goal"):
                    try:
                        r = json.loads(goal_f.read_text())
                        data["experiment_goal"] = r.get("experiment_goal", "")
                        data["experiment_md_path"] = r.get("config_path", "")
                    except Exception:
                        pass
                # Fallback: extract goal from experiment_md_content
                if not data.get("experiment_goal") and data.get("experiment_md_content"):
                    _md = data["experiment_md_content"]
                    _goal_lines = []
                    _in_goal = False
                    for _gl in _md.splitlines():
                        _gs = _gl.strip()
                        if _gs.startswith("#") and "research goal" in _gs.lower():
                            _in_goal = True
                            continue
                        if _in_goal:
                            if _gs.startswith("#"):
                                break
                            if _gs:
                                _goal_lines.append(_gs)
                    if _goal_lines:
                        data["experiment_goal"] = " ".join(_goal_lines)[:500]
                    elif _md.strip():
                        _first = next((l.lstrip("#").strip() for l in _md.splitlines() if l.strip()), "")
                        data["experiment_goal"] = _first[:200]
            # Fallback: experiment_md from cwd/experiment.md (works even after server restart)
            if not data.get("experiment_md_content"):
                try:
                    # Try checkpoints/experiment.md first (written at launch)
                    _ckpt_md = Path.cwd() / "checkpoints" / "experiment.md"
                    _cwd_md = Path.cwd() / "experiment.md"
                    if _ckpt_md.exists() and _ckpt_md.stat().st_size > 0:
                        data["experiment_md_content"] = _ckpt_md.read_text(encoding="utf-8", errors="replace")[:4000]
                    elif _cwd_md.exists() and _cwd_md.stat().st_size > 0:
                        data["experiment_md_content"] = _cwd_md.read_text(encoding="utf-8", errors="replace")[:4000]
                    elif _st._last_experiment_md:
                        data["experiment_md_content"] = _st._last_experiment_md[:4000]
                except Exception:
                    pass
            # Extract goal from md if not set
            if not data.get("experiment_goal") and data.get("experiment_md_content"):
                _md2 = data["experiment_md_content"]
                _glines, _in_g = [], False
                for _gl in _md2.splitlines():
                    _gs = _gl.strip()
                    if _gs.startswith("#") and "research goal" in _gs.lower():
                        _in_g = True; continue
                    if _in_g:
                        if _gs.startswith("#"): break
                        if _gs: _glines.append(_gs)
                if _glines:
                    data["experiment_goal"] = " ".join(_glines)[:500]
                elif _md2.strip():
                    data["experiment_goal"] = next((l.lstrip("#").strip() for l in _md2.splitlines() if l.strip()), "")[:200]
            # Inject running_pid and status
            _pid_now = None
            if _st._last_proc and _st._last_proc.poll() is None:
                _pid_now = _st._last_proc.pid
            data["running_pid"] = _pid_now
            data["is_running"] = bool(_pid_now)
            # JS-compat aliases
            data["running"] = bool(_pid_now)
            data["pid"] = _pid_now
            data["status_label"] = "🟢 Running" if _pid_now else "⬛ Stopped"
            # Inject llm_model directly (for model badge fallback)
            if not data.get("llm_model"):
                try:
                    from .api_settings import _api_get_settings as _gs2
                    _s2 = _gs2()
                    data["llm_model"] = _s2.get("llm_model", "")
                except Exception:
                    pass
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/gpu-monitor":
            running = _st._gpu_monitor_proc is not None and _st._gpu_monitor_proc.poll() is None
            pid = _st._gpu_monitor_proc.pid if running else None
            log_tail = ""
            try:
                lp = Path.home() / "ARI/logs/gpu_monitor.log"
                if lp.exists():
                    lines = lp.read_text().splitlines()
                    log_tail = "\n".join(lines[-20:])
            except Exception:
                pass
            oh = ""
            try:
                s = json.loads(_st._settings_path.read_text()) if _st._settings_path.exists() else {}
                oh = s.get("ollama_host","")
            except Exception:
                pass
            body = json.dumps({"running":running,"pid":pid,"log":log_tail,"ollama_host":oh}).encode()
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
                p = Path(fpath)
                if p.exists() and p.is_file() and p.stat().st_size < 2_000_000:
                    body = p.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
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
                _st._ari_home / "ari-core" / "checkpoints" / ckpt_id / fname,
                Path.cwd() / "checkpoints" / ckpt_id / fname,
            ]
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
        elif self.path.startswith("/api/checkpoint/") and self.path.endswith("/summary"):
            ckpt_id = self.path[len("/api/checkpoint/"):-len("/summary")]
            self._json(_api_checkpoint_summary(urllib.parse.unquote(ckpt_id)))
        elif self.path == "/api/settings":
            self._json(_api_get_settings())
        elif self.path == "/api/profiles":
            self._json(_api_profiles())
        elif self.path == "/api/upload":
            # Serve upload form page
            self._json({"error": "use POST /api/upload"})
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
            self.end_headers()
            _api_logs_sse(self.wfile)
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
        elif self.path == "/api/launch":
            self._json(_api_launch(body))
        elif self.path == "/api/run-stage":
            self._json(_api_run_stage(body))
        elif self.path == "/api/config/generate":
            self._json(_api_generate_config(body))
        elif self.path == "/api/chat-goal":
            self._json(_api_chat_goal(body))
        elif self.path == "/api/upload":
            self._json(_api_upload_file(self.headers, body))
        elif self.path == "/api/env-keys":
            self._json(_api_save_env_key(body))
        elif self.path == "/api/ssh/test":
            self._json(_api_ssh_test(body))
        elif self.path == "/api/switch-checkpoint":
            self._json(_api_switch_checkpoint(body))
        elif self.path.startswith("/api/ollama/"):
            _ollama_proxy(self)
            return
        elif self.path == "/api/gpu-monitor":
            data_g = json.loads(body or b'{}')
            action_g = data_g.get("action","")
            if action_g == "start":
                if not data_g.get("confirmed"):
                    self._json({"ok": False, "needs_confirm": True,
                        "msg": "GPU Monitor will continuously submit SLURM jobs. Start only when running a GPU experiment."})
                elif _st._gpu_monitor_proc is None or _st._gpu_monitor_proc.poll() is not None:
                    script = Path.home() / "ARI/scripts/gpu_ollama_monitor.sh"
                    import os as _os_gm
                    _gm_log = open(Path.home() / "ARI/logs/gpu_monitor.log", "a")
                    _st._gpu_monitor_proc = subprocess.Popen(
                        ["bash", str(script)], stdout=_gm_log, stderr=_gm_log,
                        start_new_session=True, env=_os_gm.environ.copy()
                    )
                    self._json({"ok": True, "pid": _st._gpu_monitor_proc.pid})
                else:
                    self._json({"ok": False, "msg": "already running", "pid": _st._gpu_monitor_proc.pid})
            elif action_g == "stop":
                if _st._gpu_monitor_proc and _st._gpu_monitor_proc.poll() is None:
                    _st._gpu_monitor_proc.terminate()
                self._json({"ok": True})
            else:
                self._json({"ok": False, "msg": "unknown action"})
        elif self.path == "/api/stop":
            killed = False
            if _st._last_proc and _st._last_proc.poll() is None:
                try:
                    import signal as _sig_stop
                    os.killpg(os.getpgid(_st._last_proc.pid), _sig_stop.SIGTERM)
                except Exception:
                    try: _st._last_proc.terminate()
                    except: pass
                killed = True
            import subprocess as _sp_stop
            try: _sp_stop.run(["pkill","-f","ari-skill"], capture_output=True, timeout=3)
            except: pass
            try: _sp_stop.run(["pkill","-f","ari.cli"], capture_output=True, timeout=3)
            except: pass
            self._json({"ok": True, "stopped": killed, "msg": "停止しました" if killed else "実行中のプロセスなし"})
        elif self.path == "/api/delete-checkpoint":
            self._json(_api_delete_checkpoint(body))
        elif self.path == "/api/workflow":
            self._json(_api_save_workflow(body))
        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


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
    # Auto-restore last checkpoint on startup
    _ckpt_root = Path(__file__).parent.parent.parent / "checkpoints"
    if _ckpt_root.exists():
        dirs = sorted([d for d in _ckpt_root.iterdir() if d.is_dir()], key=lambda x: x.name)
        if dirs:
            _st._checkpoint_dir = dirs[-1]
            _st._last_mtime = 0.0
            import logging
            logging.getLogger(__name__).info(f"Auto-restored checkpoint: {_st._checkpoint_dir.name}")
    srv = ThreadingHTTPServer(("", port), _Handler)
    srv.serve_forever()


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

async def _main(checkpoint: Path, port: int) -> None:
    _st._checkpoint_dir = checkpoint
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
        asyncio.run(_main(args.checkpoint or Path("."), args.port))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()

