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
from .api_process import _api_gpu_monitor_status, _api_gpu_monitor_action, _api_stop
from .ui_helpers import (
    _REDACT_KEYS,
    _build_experiment_detail_config,
    _collect_resource_metrics,
    _extract_goal_from_md,
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
                    from ari.paths import PathManager as _PM_legacy
                    _PM_legacy.set_checkpoint_dir_env(_st._checkpoint_dir)
                    from ari_skill_memory.backends import get_backend
                    backend = get_backend(checkpoint_dir=_st._checkpoint_dir)
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
                # Always expose checkpoint_id / checkpoint_path when dir exists
                # so File Explorer can browse files before marker files appear.
                if _cd.is_absolute() and _cd.exists():
                    data.setdefault("checkpoint_path", str(_cd))
                    data.setdefault("checkpoint_id", _cd.name)
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
                # node_count is derived from the already-loaded tree (``data`` ==
                # _load_nodes_tree(), i.e. the same tree emitted over the WS and in
                # this /state payload). Subtask 024 §8.4 / §13.2: /state no longer
                # re-reads tree.json/nodes_tree.json a second time to recount — the
                # precedence + legacy ``node_*/tree.json`` fallback already live in
                # ari.checkpoint.load_nodes_tree via the viz.tree_view adapter that
                # produced ``data``, so the value is identical to before for empty,
                # nodes-present, and legacy layouts.
                _tree_nodes = data.get("nodes", []) if isinstance(data, dict) else []
                data["node_count"] = len(_tree_nodes) if _tree_nodes else 0
                _has_idea  = (d/"idea.json").exists() or (d/"science_data.json").exists()
                _has_code  = bool(_glob.glob(str(d/"**/*.py"), recursive=True) + _glob.glob(str(d/"**/*.f90"), recursive=True))
                _has_eval  = any((d/n).exists() for n in ["evaluation.json","eval_results.json","results.json"])
                _pipeline_started = (d/".pipeline_started").exists()
                _running_pid = data.get("running_pid")
                # Phase detection (ordered — later phases take priority).
                # Each marker indicates the phase is ACTIVE or COMPLETED,
                # so later phases must be checked first.
                if data["has_review"]:
                    _phase = "review"
                elif data["has_paper"] or _pipeline_started:
                    _phase = "paper"
                elif _has_idea:
                    # idea.json exists → Idea phase is DONE, BFTS is active.
                    # Even before nodes_tree.json is written, the root node
                    # is already running (implementing + submitting experiments).
                    _phase = "bfts"
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
                    "bfts": _has_idea,  # BFTS starts as soon as idea is done
                    "paper": data["has_paper"] or _pipeline_started,
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
                # Try 2: config_path recorded in results.json (the actual file cli.py was given)
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
                    _eval_cfg = _wf_cfg.get("evaluator", {})
                    _hpc  = _wf_cfg.get("hpc", {})
                    saved2 = _api_get_settings()
                    # Merge default.yaml for missing fields
                    _default_cfg = {}
                    _default_yaml = _config_root / "default.yaml"
                    if _default_yaml.exists():
                        _default_cfg = _yaml.safe_load(_default_yaml.read_text()) or {}
                    _default_bfts = _default_cfg.get("bfts", {})
                    _default_eval = _default_cfg.get("evaluator", {})
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
                        "frontier_score":  _lc_data.get("frontier_score") or _bfts.get("frontier_score", _default_bfts.get("frontier_score", "scientific_plus_diversity")),
                        "composite":       _lc_data.get("composite") or _eval_cfg.get("composite", _default_eval.get("composite", "harmonic_mean")),
                        "axis_mode":       _lc_data.get("axis_mode") or _eval_cfg.get("axis_mode", _default_eval.get("axis_mode", "dynamic")),
                        "scheduler":       _hpc.get("scheduler", "local"),
                        "partition":       _lc_data.get("partition") or _hpc.get("partition", ""),
                        "cpus":            _lc_data.get("hpc_cpus") or _hpc.get("cpus_per_task", None),
                        "memory_gb":       _lc_data.get("hpc_memory_gb") or _hpc.get("memory_gb", None),
                        "gpus":            _lc_data.get("hpc_gpus") or _hpc.get("gpus", None),
                        "walltime":        _lc_data.get("hpc_walltime") or _hpc.get("walltime", ""),
                    }
                    # Detail config is served via /api/experiment-detail (not in /state)
                    # to keep 5-second polling payload small.
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
                            # best_nodes mirrors configurations[:3] verbatim —
                            # including the typed split fields (parameters /
                            # measurements / predictions / scores / _typed_source)
                            # when nodes_to_science_data populated them. Frontend
                            # consumers can render parameters as the experiment
                            # configuration and measurements as the headline
                            # numbers without re-classifying the flat metrics
                            # bag themselves.
                            data["best_nodes"] = confs[:3]
                            # Collect all unique metric keys (non-underscore)
                            all_keys = set()
                            for c in confs:
                                for k in (c.get("metrics") or {}).keys():
                                    if not k.startswith("_"):
                                        all_keys.add(k)
                            data["all_metric_keys"] = sorted(all_keys)
                            # Surface the primary metric name + best value
                            # alongside best_nodes so the GUI can label the
                            # leaderboard with the right scalar without
                            # re-deriving it. Shape mirrors science_data.json
                            # so consumers can introspect even when stats
                            # were not computed (legacy run).
                            data["summary_stats"] = sci.get("summary_stats", {})
                            # Provenance of the typed split — "results.json"
                            # (D contract), "llm_evaluator" (C contract), or
                            # absent (legacy). One value per best_node.
                            data["typed_split_sources"] = [
                                c.get("_typed_source") or ""
                                for c in confs[:3]
                            ]
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
                    data["experiment_goal"] = _extract_goal_from_md(data["experiment_md_content"])
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
                data["experiment_goal"] = _extract_goal_from_md(data["experiment_md_content"])
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
                    # Detail config is served via /api/experiment-detail (not in /state)
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
            from ari.container import get_container_info
            self._json(get_container_info())
        elif self.path == "/api/container/images":
            from ari.container import list_images
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
                from ari.container import ContainerConfig, pull_image
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
