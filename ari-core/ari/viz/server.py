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
# HTTP server (serves React dashboard build)
# ──────────────────────────────────────────────
DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"
REACT_DIST_DIR = Path(__file__).parent / "static" / "dist"
REACT_INDEX = REACT_DIST_DIR / "index.html"



class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # suppress request logs
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
            # Clear stale experiment content when process has exited to prevent
            # leaking test data on page reload. Model/provider info is kept
            # (not sensitive, needed for correct CONFIG display).
            if _st._last_proc and _st._last_proc.poll() is not None:
                _st._last_experiment_md = None
            data = _load_nodes_tree() or {}
            # Inject file-based phase flags
            # Validate: _checkpoint_dir must be a real checkpoint (contains tree.json or nodes_tree.json),
            # not a generic dir like "." or "ari-core/"
            _ckpt_valid = False
            if _st._checkpoint_dir:
                _cd = Path(_st._checkpoint_dir)
                _ckpt_valid = _cd.is_absolute() and _cd.exists() and (
                    (_cd / "nodes_tree.json").exists() or (_cd / "tree.json").exists()
                    or (_cd / "idea.json").exists() or (_cd / "experiment.md").exists()
                )
            if _ckpt_valid:
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
                _pipeline_started = (d/".pipeline_started").exists()
                _running_pid = data.get("running_pid")
                # Phase detection (ordered)
                if data["has_review"]:
                    _phase = "review"
                elif data["has_paper"]:
                    _phase = "paper"
                elif _pipeline_started:
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
                    except Exception: log.debug("cost_trace parse error", exc_info=True)
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
                # Try 1: checkpoint dir itself (cli.py copies experiment.md here)
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
                # Try 3: config_path recorded in results.json (the actual file cli.py was given)
                if not _exp_md:
                    _res_f = d / "results.json"
                    if _res_f.exists():
                        try:
                            _rj = json.loads(_res_f.read_text())
                            _cp = _rj.get("config_path", "")
                            if _cp and Path(_cp).exists():
                                _exp_md = Path(_cp).read_text(encoding="utf-8", errors="replace")
                        except Exception:
                            pass
                # Try 4: _last_experiment_md ONLY if a process is currently running
                # (avoids stale test data from previous launches)
                if not _exp_md and _st._last_experiment_md and _st._last_proc and _st._last_proc.poll() is None:
                    _exp_md = _st._last_experiment_md
                if _exp_md:
                    data["experiment_md_content"] = _exp_md[:4000]
                if not data.get("experiment_md_path"):
                    data["experiment_md_path"] = str(d / "experiment.md")
                # Inject experiment_config: key settings for display
                try:
                    import yaml as _yaml
                    _wf_cfg = {}
                    # Determine which profile YAML to load:
                    # launch_config.profile > launch_config.json > default
                    _config_root = Path(__file__).parent.parent.parent / "config"
                    _lc_profile = ""
                    if _st._launch_config:
                        _lc_profile = _st._launch_config.get("profile", "")
                    if not _lc_profile:
                        _lc_tmp = d / "launch_config.json"
                        if _lc_tmp.exists():
                            try: _lc_profile = json.loads(_lc_tmp.read_text()).get("profile", "")
                            except Exception: pass
                    _profile_candidates = [d / "workflow.yaml"]
                    if _lc_profile:
                        _profile_candidates.append(_config_root / "profiles" / f"{_lc_profile}.yaml")
                    _profile_candidates.append(_config_root / "default.yaml")
                    for _wf_path in _profile_candidates:
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
                    # Override LLM info: launch state > launch_config.json > settings
                    _launch_model = _st._launch_llm_model or ""
                    _launch_provider = _st._launch_llm_provider or ""
                    # Priority: in-memory launch config (immediate) > launch_config.json (persisted) > YAML defaults
                    _lc_data = {}
                    if _st._launch_config:
                        _lc_data = dict(_st._launch_config)
                    if not _lc_data:
                        # Check checkpoint dir first, then parent dir (fallback)
                        for _lc_path in [d / "launch_config.json", d.parent / "launch_config.json"]:
                            if _lc_path.exists():
                                try:
                                    _lc_data = json.loads(_lc_path.read_text())
                                    break
                                except Exception:
                                    pass
                    if not _launch_model or not _launch_provider:
                        _launch_model = _launch_model or _lc_data.get("llm_model", "")
                        _launch_provider = _launch_provider or _lc_data.get("llm_provider", "")
                    _settings_model = saved2.get("llm_model", "")
                    _settings_provider = saved2.get("llm_provider", "")
                    _eff_model = _launch_model or _settings_model
                    _eff_provider = _launch_provider or _settings_provider
                    _merged.setdefault("llm", {})
                    _merged["llm"]["model"]   = _eff_model
                    _merged["llm"]["backend"] = _eff_provider
                    _merged["llm"]["base_url"] = saved2.get("ollama_host", "")
                    _backend = _eff_provider
                    # BFTS values: launch_config.json overrides (wizard values) > workflow.yaml > default.yaml
                    data["experiment_config"] = {
                        "llm_model":       _eff_model,
                        "llm_backend":     _backend,
                        "ollama_host":     saved2.get("ollama_host", "") if _backend == "ollama" else "",
                        "max_nodes":       _lc_data.get("max_nodes") or _bfts.get("max_total_nodes",      _default_bfts.get("max_total_nodes", None)),
                        "max_depth":       _lc_data.get("max_depth") or _bfts.get("max_depth",            _default_bfts.get("max_depth", None)),
                        "parallel":        _lc_data.get("parallel")  or _bfts.get("parallel",             _default_bfts.get("max_parallel_nodes", None)),
                        "timeout_node_s":  _lc_data.get("timeout_node_s") or _bfts.get("timeout_per_node",    _default_bfts.get("timeout_per_node", None)),
                        "max_react":       _lc_data.get("max_react") or _bfts.get("max_react_steps", _default_bfts.get("max_react_steps", 80)),
                        "scheduler":       _hpc.get("scheduler", "local"),
                        "partition":       _lc_data.get("partition") or _hpc.get("partition", ""),
                        "cpus":            _lc_data.get("hpc_cpus") or _hpc.get("cpus_per_task", None),
                        "memory_gb":       _lc_data.get("hpc_memory_gb") or _hpc.get("memory_gb", None),
                        "gpus":            _lc_data.get("hpc_gpus") or _hpc.get("gpus", None),
                        "walltime":        _lc_data.get("hpc_walltime") or _hpc.get("walltime", ""),
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
                    log.warning("Failed to build experiment_config", exc_info=True)

                # Inject VirSci ideas from idea.json
                idea_f = d / "idea.json"
                if idea_f.exists():
                    try:
                        idea_data = json.loads(idea_f.read_text())
                        data["ideas"] = idea_data.get("ideas", [])
                        data["gap_analysis"] = idea_data.get("gap_analysis", "")
                        data["idea_primary_metric"] = idea_data.get("primary_metric", "")
                        data["idea_metric_rationale"] = idea_data.get("metric_rationale", "")
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
                        data["experiment_goal"] = " ".join(_goal_lines)
                    elif _md.strip():
                        _first = next((l.lstrip("#").strip() for l in _md.splitlines() if l.strip()), "")
                        data["experiment_goal"] = _first
            # Fallback: experiment_md from project root experiment.md
            # Only serve when a process is currently running to prevent
            # leaking test content from previous launches.
            if not data.get("experiment_md_content") and _st._last_proc and _st._last_proc.poll() is None:
                try:
                    _ari_core = Path(__file__).parent.parent.parent
                    for _cand in [
                        _ari_core / "experiment.md",  # ari-core/experiment.md
                    ]:
                        if _cand.exists() and _cand.stat().st_size > 0:
                            data["experiment_md_content"] = _cand.read_text(encoding="utf-8", errors="replace")[:4000]
                            break
                    if not data.get("experiment_md_content") and _st._last_experiment_md:
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
                    data["experiment_goal"] = " ".join(_glines)
                elif _md2.strip():
                    data["experiment_goal"] = next((l.lstrip("#").strip() for l in _md2.splitlines() if l.strip()), "")
            # Inject running_pid and status
            _pid_now = None
            _exit_code = None
            # Tier 1: in-memory process reference (GUI-spawned)
            if _st._last_proc:
                _poll = _st._last_proc.poll()
                if _poll is None:
                    _pid_now = _st._last_proc.pid
                else:
                    _exit_code = _poll
            # Tier 2: PID file fallback (CLI-spawned or server restarted)
            if _pid_now is None and _ckpt_valid:
                from ari.pidfile import check_pid as _ck_pid, read_pid as _rd_pid
                if _ck_pid(Path(_st._checkpoint_dir)) == "running":
                    _pid_now = _rd_pid(Path(_st._checkpoint_dir))
            data["running_pid"] = _pid_now
            data["is_running"] = bool(_pid_now)
            data["exit_code"] = _exit_code
            # JS-compat aliases
            data["running"] = bool(_pid_now)
            data["pid"] = _pid_now
            if _pid_now:
                data["status_label"] = "🟢 Running"
            elif _exit_code is not None and _exit_code != 0:
                data["status_label"] = f"🔴 Error (exit {_exit_code})"
            else:
                data["status_label"] = "⬛ Stopped"
            # Inject llm_model directly (for model badge fallback)
            if not data.get("llm_model"):
                try:
                    from .api_settings import _api_get_settings as _gs2
                    _s2 = _gs2()
                    _badge_model = _st._launch_llm_model or ""
                    # Fallback: launch_config.json from checkpoint
                    if not _badge_model and _ckpt_valid:
                        _lc2 = Path(_st._checkpoint_dir) / "launch_config.json"
                        if _lc2.exists():
                            try: _badge_model = json.loads(_lc2.read_text()).get("llm_model", "")
                            except Exception: log.debug("launch_config.json read error for badge", exc_info=True)
                    data["llm_model"] = _badge_model or _s2.get("llm_model", "")
                except Exception:
                    log.debug("badge model fallback error", exc_info=True)
            # Inject experiment_config from defaults only when a checkpoint is active
            if "experiment_config" not in data and _st._checkpoint_dir:
                try:
                    import yaml as _yaml_fb
                    from .api_settings import _api_get_settings as _gs3
                    _s3 = _gs3()
                    # Priority: in-memory launch config > launch_config.json > settings
                    _lc_fb = {}
                    if _st._launch_config:
                        _lc_fb = dict(_st._launch_config)
                    if not _lc_fb and _ckpt_valid:
                        _lc3 = Path(_st._checkpoint_dir) / "launch_config.json"
                        if _lc3.exists():
                            try:
                                _lc_fb = json.loads(_lc3.read_text())
                            except Exception: pass
                    _lm = _st._launch_llm_model or _lc_fb.get("llm_model", "") or ""
                    _lp = _st._launch_llm_provider or _lc_fb.get("llm_provider", "") or ""
                    _lm = _lm or _s3.get("llm_model", "")
                    _lp = _lp or _s3.get("llm_provider", "")
                    # Load BFTS/HPC settings from profile-aware config
                    _config_root_fb = Path(__file__).parent.parent.parent / "config"
                    _lc_profile_fb = _lc_fb.get("profile", "")
                    _wf_cfg_fb = {}
                    _fb_candidates = []
                    if _lc_profile_fb:
                        _fb_candidates.append(_config_root_fb / "profiles" / f"{_lc_profile_fb}.yaml")
                    _fb_candidates.append(_config_root_fb / "default.yaml")
                    for _wf_p in _fb_candidates:
                        if _wf_p.exists():
                            _tmp_fb = _yaml_fb.safe_load(_wf_p.read_text()) or {}
                            if _tmp_fb.get("bfts") or _tmp_fb.get("hpc"):
                                _wf_cfg_fb = _tmp_fb
                                break
                    _bfts_fb = _wf_cfg_fb.get("bfts", {})
                    _hpc_fb  = _wf_cfg_fb.get("hpc", {})
                    data["experiment_config"] = {
                        "llm_model": _lm,
                        "llm_backend": _lp,
                        "ollama_host": _s3.get("ollama_host", "") if _lp == "ollama" else "",
                        "max_nodes":       _lc_fb.get("max_nodes") or _bfts_fb.get("max_total_nodes"),
                        "max_depth":       _lc_fb.get("max_depth") or _bfts_fb.get("max_depth"),
                        "parallel":        _lc_fb.get("parallel") or _bfts_fb.get("max_parallel_nodes") or _bfts_fb.get("parallel"),
                        "timeout_node_s":  _lc_fb.get("timeout_node_s") or _bfts_fb.get("timeout_per_node"),
                        "max_react":       _lc_fb.get("max_react") or _bfts_fb.get("max_react_steps", 80),
                        "scheduler":       _hpc_fb.get("scheduler", "local"),
                        "partition":       _lc_fb.get("partition") or _hpc_fb.get("partition", ""),
                        "cpus":            _lc_fb.get("hpc_cpus") or _hpc_fb.get("cpus_per_task"),
                        "memory_gb":       _lc_fb.get("hpc_memory_gb") or _hpc_fb.get("memory_gb"),
                        "gpus":            _lc_fb.get("hpc_gpus") or _hpc_fb.get("gpus"),
                        "walltime":        _lc_fb.get("hpc_walltime") or _hpc_fb.get("walltime", ""),
                    }
                    # Also build experiment_detail_config
                    _default_fb = {}
                    _default_yaml_fb = _config_root_fb / "default.yaml"
                    if _default_yaml_fb.exists():
                        _default_fb = _yaml_fb.safe_load(_default_yaml_fb.read_text()) or {}
                    import copy as _copy_fb
                    _merged_fb = _copy_fb.deepcopy(_default_fb)
                    for _k, _v in _wf_cfg_fb.items():
                        if isinstance(_v, dict) and isinstance(_merged_fb.get(_k), dict):
                            _merged_fb[_k].update(_v)
                        else:
                            _merged_fb[_k] = _v
                    _merged_fb.setdefault("llm", {})
                    _merged_fb["llm"]["model"]   = _lm
                    _merged_fb["llm"]["backend"] = _lp
                    _REDACT_FB = {"api_key", "apikey", "api-key", "token", "secret", "password"}
                    _dl = []
                    for _sk, _sv in _merged_fb.items():
                        if _sk == "skills": continue
                        if isinstance(_sv, dict):
                            _dl.append(f"[{_sk}]")
                            for _dk, _dv in _sv.items():
                                if _dk.lower() in _REDACT_FB or "key" in _dk.lower():
                                    _dl.append(f"  {_dk}: ***")
                                else:
                                    _dl.append(f"  {_dk}: {_dv}")
                        else:
                            _dl.append(f"{_sk}: {_sv}")
                    data["experiment_detail_config"] = "\n".join(_dl)
                except Exception:
                    log.warning("Failed to build experiment_config (fallback)", exc_info=True)
            # Always inject running_pid if missing
            if "running_pid" not in data:
                _pid_now = None
                if _st._last_proc:
                    _poll = _st._last_proc.poll()
                    if _poll is None:
                        _pid_now = _st._last_proc.pid
                # PID file fallback
                if _pid_now is None and _ckpt_valid:
                    from ari.pidfile import check_pid as _ck_pid2, read_pid as _rd_pid2
                    if _ck_pid2(Path(_st._checkpoint_dir)) == "running":
                        _pid_now = _rd_pid2(Path(_st._checkpoint_dir))
                data["running_pid"] = _pid_now
                data["is_running"] = bool(_pid_now)
                data["running"] = bool(_pid_now)
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
            # Serve file content for artifact file paths (restricted to checkpoint dir)
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            fpath = qs.get("path", [""])[0]
            try:
                p = Path(fpath).resolve()
                # Security: restrict to checkpoint directory
                allowed = False
                if _st._checkpoint_dir:
                    try:
                        p.relative_to(_st._checkpoint_dir.resolve())
                        allowed = True
                    except ValueError:
                        pass
                if allowed and p.exists() and p.is_file() and p.stat().st_size < 2_000_000:
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
                Path.home() / ".ari" / "checkpoints" / ckpt_id / fname,
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
        elif self.path == "/api/launch":
            r = _api_launch(body); self._json(r, status=r.pop("_status", 200))
        elif self.path == "/api/run-stage":
            r = _api_run_stage(body); self._json(r, status=r.pop("_status", 200))
        elif self.path == "/api/config/generate":
            self._json(_api_generate_config(body))
        elif self.path == "/api/chat-goal":
            self._json(_api_chat_goal(body))
        elif self.path == "/api/upload":
            r = _api_upload_file(self.headers, body); self._json(r, status=r.pop("_status", 200))
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
            import signal as _sig_stop
            import subprocess as _sp_stop
            import time as _time_stop
            report = {"main": "none", "gpu_monitor": "none", "pkill": []}

            # --- 1. Main experiment process ---
            if _st._last_proc and _st._last_proc.poll() is None:
                pid = _st._last_proc.pid
                # SIGTERM to process group first
                try:
                    os.killpg(os.getpgid(pid), _sig_stop.SIGTERM)
                except Exception:
                    try: _st._last_proc.terminate()
                    except Exception: log.debug("process terminate fallback failed", exc_info=True)
                # Wait up to 5 seconds for graceful shutdown
                for _ in range(50):
                    if _st._last_proc.poll() is not None:
                        break
                    _time_stop.sleep(0.1)
                if _st._last_proc.poll() is None:
                    # SIGKILL fallback
                    try:
                        os.killpg(os.getpgid(pid), _sig_stop.SIGKILL)
                    except Exception:
                        try: _st._last_proc.kill()
                        except Exception: log.debug("process kill fallback failed", exc_info=True)
                    _st._last_proc.wait(timeout=3)
                    report["main"] = f"killed(SIGKILL) pid={pid}"
                else:
                    report["main"] = f"stopped(SIGTERM) pid={pid}"
            else:
                report["main"] = "not running"

            # --- 2. GPU monitor process ---
            if _st._gpu_monitor_proc and _st._gpu_monitor_proc.poll() is None:
                gpu_pid = _st._gpu_monitor_proc.pid
                _st._gpu_monitor_proc.terminate()
                for _ in range(20):
                    if _st._gpu_monitor_proc.poll() is not None:
                        break
                    _time_stop.sleep(0.1)
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
                    r = _sp_stop.run(["pkill", "-f", pattern], capture_output=True, timeout=3)
                    if r.returncode == 0:
                        report["pkill"].append(f"{pattern}: killed")
                    else:
                        report["pkill"].append(f"{pattern}: no match")
                except Exception as e:
                    report["pkill"].append(f"{pattern}: error({e})")

            # --- 4. Verify no survivors ---
            _time_stop.sleep(0.3)
            survivors = []
            for pattern in ["ari-skill", "ari.cli", "gpu_ollama_monitor"]:
                try:
                    r = _sp_stop.run(["pgrep", "-f", pattern], capture_output=True, text=True, timeout=3)
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
            self._json({"ok": True, "stopped": stopped, "report": report})
        elif self.path == "/api/delete-checkpoint":
            self._json(_api_delete_checkpoint(body))
        elif self.path == "/api/workflow":
            r = _api_save_workflow(body); self._json(r, status=r.pop("_status", 200))
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
                    _st._checkpoint_dir = _np
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
        asyncio.run(_main(args.checkpoint or None, args.port))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()

