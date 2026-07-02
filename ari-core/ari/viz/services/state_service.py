"""ARI viz service: ``GET /state`` AppState builder (subtask 062, StateService).

Extracts the ~450-line inline ``/state`` builder that lived in ``routes.py``
``do_GET`` (``elif self.path == "/state":``) into a single, importable,
side-effect-preserving function. The dashboard wire contract is unchanged:
:func:`build_app_state` returns the exact ``data`` dict the inline builder
produced, and ``routes.py`` still owns the ``elif self.path == "/state"``
comparison + the byte-identical HTTP response (``json.dumps(data).encode()`` with
no ``Access-Control-Allow-Origin`` header — the historical inline-none CORS quirk
preserved verbatim; 020 finding F2 / 010 §4 Contract C).

Subtask 021 (§7.1) DEFERRED this extraction to 062 because frozen
source-inspection tests pinned the ``/state`` literals (``"frontier_score"`` /
``"composite"`` / ``"axis_mode"`` / ``experiment_config`` / ``gap_analysis`` /
``idea_primary_metric`` / ``_lc_data.get("...")``) to ``routes.py`` and to the
``ui_helpers``+``websocket``+``routes``+``server`` concat helpers. Those guards
are updated as pure *location pointers* (they now also read
``services/state_service.py``), asserting the SAME literals at the new location —
the same Phase-3B mechanism that let ``server.py`` split into siblings.

Behaviour preserved verbatim from the inline builder:

- Reads ``_st`` module globals at call time (``_last_proc`` / ``_checkpoint_dir``
  / ``_launch_*`` / ``_last_experiment_md``) so ``monkeypatch.setattr(_st, ...)``
  is observed exactly as before.
- **Mutates** ``_st._last_experiment_md = None`` when the tracked process has
  exited (stale-content clearing), identical to the inline behaviour.
- Same globs / YAML profile-merge order (reading ``ari-core/config/`` via
  ``ari.config.finder.package_config_root``) / ``cost_trace.jsonl`` tail / phase
  detection / process-liveness fields.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .. import state as _st
from ..api_state import _load_nodes_tree
from ..api_settings import _api_get_settings
from ..ui_helpers import _extract_goal_from_md

log = logging.getLogger(__name__)


def build_app_state() -> dict:
    """Build the ``GET /state`` ``AppState`` payload dict (verbatim behaviour).

    Returns the same ``data`` dict the former inline ``routes.py`` ``/state``
    branch produced. Callers serialize it with ``json.dumps(data).encode()``.
    """
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
            from ari.config.finder import package_config_root
            _config_root = package_config_root()
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
            _ari_core = Path(__file__).parent.parent.parent.parent
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
        from ..internal_adapters import pid_status as _ck_pid, read_pid as _rd_pid
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
            from ..api_settings import _api_get_settings as _gs2
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
            from ..api_settings import _api_get_settings as _gs3
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
            from ari.config.finder import package_config_root
            _config_root_fb = package_config_root()
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
            from ..internal_adapters import pid_status as _ck_pid2, read_pid as _rd_pid2
            if _ck_pid2(Path(_st._checkpoint_dir)) == "running":
                _pid_now = _rd_pid2(Path(_st._checkpoint_dir))
        data["running_pid"] = _pid_now
        data["is_running"] = bool(_pid_now)
        data["running"] = bool(_pid_now)
    return data
