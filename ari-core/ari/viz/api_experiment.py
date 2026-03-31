from __future__ import annotations
"""ARI viz: api_experiment — launch, run stages, log streaming."""

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from . import state as _st

import logging
log = logging.getLogger(__name__)


def _api_run_stage(body: bytes) -> dict:
    """Run a specific ARI stage (resume/paper/review) on the active checkpoint.

    Note: 'review' maps to 'ari paper' which runs the full post-BFTS pipeline
    (paper generation + review + reproducibility check) via workflow.yaml.
    """
    data = json.loads(body) if body else {}
    stage = data.get("stage", "paper")
    ckpt = str(_st._checkpoint_dir) if _st._checkpoint_dir else ""
    if not ckpt:
        return {"ok": False, "error": "No active checkpoint"}
    if stage == "resume":
        cmd = ["python3", "-m", "ari.cli", "resume", ckpt]
    elif stage in ("paper", "review"):
        # 'ari paper' runs the full post-BFTS pipeline including
        # paper generation, review, and reproducibility check
        cmd = ["python3", "-m", "ari.cli", "paper", ckpt]
        # Mark paper pipeline start immediately so the GUI phase stepper
        # transitions from BFTS to Paper without waiting for subprocess boot.
        try:
            Path(ckpt, ".pipeline_started").touch()
        except Exception:
            pass
    else:
        return {"ok": False, "error": f"Unknown stage: {stage}"}
    try:
        # Build env: inherit current env + load .env files + settings API keys
        proc_env = os.environ.copy()
        _ari_root = _st._ari_root
        _env_candidates = [
            Path(ckpt) / ".env",
            _ari_root / ".env",
            _ari_root / "ari-core" / ".env",
            Path.home() / ".env",
        ]
        for env_path in _env_candidates:
            if env_path.exists():
                try:
                    for line in env_path.read_text().splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, _, v = line.partition("=")
                            k, v = k.strip(), v.strip().strip("'\"")
                            if k and v and (k not in proc_env or not proc_env[k]):
                                proc_env[k] = v
                except Exception:
                    pass
        # Inject API key from settings if not already in env
        from .api_settings import _api_get_settings
        saved = _api_get_settings()
        _api_key = saved.get("api_key", "") or saved.get("llm_api_key", "")
        _provider = saved.get("llm_provider", "") or saved.get("llm_backend", "")
        _model = saved.get("llm_model", "")
        if _api_key and len(_api_key) >= 20 and "test" not in _api_key:
            if _provider == "openai" and not proc_env.get("OPENAI_API_KEY"):
                proc_env["OPENAI_API_KEY"] = _api_key
            elif _provider == "anthropic" and not proc_env.get("ANTHROPIC_API_KEY"):
                proc_env["ANTHROPIC_API_KEY"] = _api_key
        # Inject LLM model/provider from launch_config or settings
        _lc_path = Path(ckpt) / "launch_config.json"
        _lc = {}
        if _lc_path.exists():
            try:
                _lc = json.loads(_lc_path.read_text())
            except Exception:
                pass
        _eff_model = _lc.get("llm_model") or _model
        _eff_provider = _lc.get("llm_provider") or _provider
        if _eff_model:
            proc_env["ARI_MODEL"] = _eff_model
            proc_env["ARI_LLM_MODEL"] = _eff_model
        if _eff_provider:
            proc_env["ARI_BACKEND"] = _eff_provider
        # Partition auto-detect for HPC
        if not proc_env.get("ARI_SLURM_PARTITION"):
            _part = _lc.get("partition", "")
            if not _part:
                try:
                    _sinfo = subprocess.run(["sinfo", "-h", "-o", "%P"], capture_output=True, text=True, timeout=5)
                    _parts = [p.strip().rstrip("*") for p in _sinfo.stdout.strip().splitlines() if p.strip()]
                    if _parts:
                        _part = _parts[0]
                except Exception:
                    pass
            if _part:
                proc_env["ARI_SLURM_PARTITION"] = _part
        _st._last_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(Path(ckpt).parent.resolve()),
            env=proc_env,
        )
        return {"ok": True, "pid": _st._last_proc.pid, "stage": stage, "cmd": " ".join(cmd)}
    except Exception as e:
        return {"ok": False, "error": str(e)}



def _api_launch(body: bytes) -> dict:
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        return {"ok": False, "error": f"Invalid request body: {e}"}
    profile = data.get("profile", "")
    experiment_md = data.get("experiment_md", "")
    # Determine checkpoint parent: use _checkpoint_dir's parent (the checkpoints/ root)
    # For a fresh launch, _checkpoint_dir may not exist yet — anchor to ari-core/
    ckpt_parent = None
    if _st._checkpoint_dir:
        ckpt_parent = _st._checkpoint_dir.parent  # e.g. .../checkpoints/
    if ckpt_parent is None:
        # Fallback: use ARI/workspace/ — never write into the source tree (ari-core/)
        ckpt_parent = Path(__file__).resolve().parent.parent.parent.parent / "workspace"
    try:
        ckpt_parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "error": f"Cannot create checkpoint directory {ckpt_parent}: {e}"}
    # Write experiment.md inside the project root (not cwd)
    config_path = ckpt_parent / "experiment.md"
    if experiment_md:
        try:
            config_path.write_text(experiment_md, encoding="utf-8")
        except Exception as e:
            return {"ok": False, "error": f"Failed to write experiment file: {e}"}
    _st._last_experiment_md = experiment_md or (config_path.read_text(encoding="utf-8") if config_path.exists() else "")
    if not config_path.exists():
        return {"ok": False, "error": f"Experiment file not found: {config_path}"}
    cmd = ["python3", "-m", "ari.cli", "run", str(config_path)]
    if profile:
        cmd += ["--profile", profile]
    try:
        import os
        # CWD must be the project root (e.g. ari-core/), not checkpoints/,
        # because auto_config() defaults to ./checkpoints/{run_id}/ which is relative to CWD.
        _resolved_parent = ckpt_parent.resolve()
        if _resolved_parent.name == "checkpoints":
            proc_cwd = str(_resolved_parent.parent)
        else:
            proc_cwd = str(_resolved_parent)
        # Build env: inherit + load .env (project root first, then ~/.env)
        proc_env = os.environ.copy()
        _ari_root = _st._ari_root
        _env_candidates = [
            _ari_root / ".env",              # /ARI/.env (project root)
            _ari_root / "ari-core" / ".env", # /ARI/ari-core/.env
            Path.home() / ".env",            # ~/.env (global fallback)
        ]
        if _st._checkpoint_dir:
            _env_candidates.insert(0, _st._checkpoint_dir / ".env")
        for env_path in _env_candidates:
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
                llm_provider = saved.get("llm_provider", "") or saved.get("llm_backend", "")
                if llm_model:
                    proc_env["ARI_MODEL"] = llm_model
                    proc_env["ARI_LLM_MODEL"] = llm_model
                if llm_provider:
                    proc_env["ARI_BACKEND"] = llm_provider
                # API keys: prefer .env / os.environ (already in proc_env).
                # Only use settings.json key as last resort if no key exists at all,
                # AND it looks like a real key (not a placeholder/test value).
                _api_key = saved.get("api_key", "") or saved.get("llm_api_key", "")
                _is_placeholder = not _api_key or "test" in _api_key or len(_api_key) < 20
                if not _is_placeholder:
                    if llm_provider == "openai" and not proc_env.get("OPENAI_API_KEY"):
                        proc_env["OPENAI_API_KEY"] = _api_key
                    elif llm_provider == "anthropic" and not proc_env.get("ANTHROPIC_API_KEY"):
                        proc_env["ANTHROPIC_API_KEY"] = _api_key
                if llm_provider == "ollama":
                    # Pass the real Ollama URL directly — ollama SDK strips path from OLLAMA_HOST
                    # so proxy routing via /api/ollama path doesn't work
                    _real_ollama = saved.get("ollama_host", "").strip() or "http://localhost:11434"
                    proc_env["OLLAMA_HOST"] = _real_ollama
                    proc_env["ARI_LLM_API_BASE"] = _real_ollama
                else:
                    # Non-Ollama backends: explicitly clear base URL so skills
                    # don't fall back to the Ollama default (http://127.0.0.1:11434)
                    proc_env["ARI_LLM_API_BASE"] = ""
                # Per-skill model overrides → ARI_MODEL_IDEA, ARI_MODEL_CODING, etc.
                for skill in ["idea","bfts","coding","eval","paper","review"]:
                    val = saved.get(f"model_{skill}", "")
                    if val:
                        proc_env[f"ARI_MODEL_{skill.upper()}"] = val
        except Exception:
            log.warning("Failed to inject LLM settings from saved config", exc_info=True)
        # BFTS scope overrides from wizard
        wiz_max_nodes = data.get("max_nodes")
        wiz_max_depth = data.get("max_depth")
        wiz_max_react = data.get("max_react")
        wiz_timeout_min = data.get("timeout_min")
        wiz_workers = data.get("workers")
        if wiz_max_nodes is not None:
            proc_env["ARI_MAX_NODES"] = str(int(wiz_max_nodes))
        if wiz_max_depth is not None:
            proc_env["ARI_MAX_DEPTH"] = str(int(wiz_max_depth))
        if wiz_max_react is not None:
            proc_env["ARI_MAX_REACT"] = str(int(wiz_max_react))
        if wiz_timeout_min is not None:
            proc_env["ARI_TIMEOUT_NODE"] = str(int(wiz_timeout_min) * 60)
        if wiz_workers is not None:
            proc_env["ARI_PARALLEL"] = str(int(wiz_workers))
        # HPC resource overrides from wizard Step 3
        wiz_hpc_cpus = data.get("hpc_cpus")
        wiz_hpc_mem = data.get("hpc_memory_gb")
        wiz_hpc_gpus = data.get("hpc_gpus")
        wiz_hpc_wall = data.get("hpc_walltime")
        wiz_partition = data.get("partition")
        if wiz_hpc_cpus is not None:
            proc_env["ARI_SLURM_CPUS"] = str(int(wiz_hpc_cpus))
        if wiz_hpc_mem is not None:
            proc_env["ARI_SLURM_MEM_GB"] = str(int(wiz_hpc_mem))
        if wiz_hpc_gpus is not None:
            proc_env["ARI_SLURM_GPUS"] = str(int(wiz_hpc_gpus))
        if wiz_hpc_wall:
            proc_env["ARI_SLURM_WALLTIME"] = str(wiz_hpc_wall)
        if wiz_partition:
            proc_env["ARI_SLURM_PARTITION"] = str(wiz_partition)
        # Auto-detect partition if HPC profile but no partition specified
        if not wiz_partition and data.get("profile") == "hpc":
            try:
                import subprocess as _sp_part
                _sinfo = _sp_part.run(["sinfo", "-h", "-o", "%P"], capture_output=True, text=True, timeout=5)
                _parts = [p.strip().rstrip("*") for p in _sinfo.stdout.strip().splitlines() if p.strip()]
                if _parts:
                    proc_env["ARI_SLURM_PARTITION"] = _parts[0]
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
        # Safety net: if provider is set but model is missing, apply a sensible default
        # to prevent config.py from falling back to qwen3:8b for non-ollama providers
        _final_backend = proc_env.get("ARI_BACKEND", "")
        _final_model = proc_env.get("ARI_MODEL", "")
        if _final_backend and not _final_model:
            _provider_defaults = {
                "openai": "gpt-4o",
                "anthropic": "claude-sonnet-4-5",
                "ollama": "qwen3:8b",
            }
            _default = _provider_defaults.get(_final_backend, "")
            if _default:
                proc_env["ARI_MODEL"] = _default
                proc_env["ARI_LLM_MODEL"] = _default
        # Save resolved model/provider to state for dashboard display
        _st._launch_llm_model = proc_env.get("ARI_MODEL") or proc_env.get("ARI_LLM_MODEL") or ""
        _st._launch_llm_provider = proc_env.get("ARI_BACKEND") or ""
        # Build launch config synchronously so /state can display wizard values
        # immediately (before checkpoint dir / launch_config.json exist)
        # Record ALL effective values (not just overrides) so the dashboard
        # can display the actual config used for this experiment.
        _launch_cfg = {
            "llm_model": _st._launch_llm_model or "",
            "llm_provider": _st._launch_llm_provider or "",
            "profile": profile or "",
            "max_nodes": int(proc_env.get("ARI_MAX_NODES", 50)),
            "max_depth": int(proc_env.get("ARI_MAX_DEPTH", 5)),
            "max_react": int(proc_env.get("ARI_MAX_REACT", 80)),
            "timeout_node_s": int(proc_env.get("ARI_TIMEOUT_NODE", 7200)),
            "parallel": int(proc_env.get("ARI_PARALLEL", 4)),
        }
        if proc_env.get("ARI_SLURM_CPUS"):
            _launch_cfg["hpc_cpus"] = int(proc_env["ARI_SLURM_CPUS"])
        if proc_env.get("ARI_SLURM_MEM_GB"):
            _launch_cfg["hpc_memory_gb"] = int(proc_env["ARI_SLURM_MEM_GB"])
        if proc_env.get("ARI_SLURM_GPUS"):
            _launch_cfg["hpc_gpus"] = int(proc_env["ARI_SLURM_GPUS"])
        if proc_env.get("ARI_SLURM_WALLTIME"):
            _launch_cfg["hpc_walltime"] = proc_env["ARI_SLURM_WALLTIME"]
        if proc_env.get("ARI_SLURM_PARTITION"):
            _launch_cfg["partition"] = proc_env["ARI_SLURM_PARTITION"]
        if phase_models:
            _launch_cfg["phase_models"] = {k: v for k, v in phase_models.items() if v}
        _st._launch_config = _launch_cfg
        import time, shutil, re as _re_slug
        # Pre-create checkpoint directory so log and config files are
        # written directly inside it from the start (no watcher/move needed).
        _ts = time.strftime("%Y%m%d%H%M%S")
        # Build slug from experiment text (same approach as cli.py fallback)
        _first_line = ""
        for _line in (experiment_md or "").splitlines():
            _stripped = _line.strip()
            if _stripped and not _stripped.startswith("#"):
                _first_line = _stripped[:60]
                break
        if not _first_line:
            _first_line = "experiment"
        _slug = _re_slug.sub(r"[^a-zA-Z0-9_-]", "_", _first_line).strip("_")[:40]
        _slug = _re_slug.sub(r"_+", "_", _slug)
        if ckpt_parent.name == "checkpoints":
            ckpt_root = ckpt_parent
        else:
            ckpt_root = ckpt_parent / "checkpoints"
        ckpt_root.mkdir(parents=True, exist_ok=True)
        _pre_ckpt = ckpt_root / f"{_ts}_{_slug}"
        _pre_ckpt.mkdir(parents=True, exist_ok=True)
        # Write log, experiment.md, and launch_config.json directly inside
        log_path = _pre_ckpt / f"ari_run_{int(time.time())}.log"
        _st._last_log_path = log_path
        _st._last_log_fh = open(log_path, "w")
        if experiment_md:
            (_pre_ckpt / "experiment.md").write_text(experiment_md, encoding="utf-8")
        (_pre_ckpt / "launch_config.json").write_text(json.dumps(_launch_cfg, indent=2))
        # Point active checkpoint to the pre-created dir immediately
        _st._checkpoint_dir = _pre_ckpt
        _st._last_mtime = 0.0
        # Tell CLI to use this pre-created checkpoint directory
        proc_env["ARI_CHECKPOINT_DIR"] = str(_pre_ckpt)
        _st._last_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=_st._last_log_fh,
            stderr=_st._last_log_fh,
            text=True,
            cwd=proc_cwd,
            env=proc_env,
            start_new_session=True,
        )
        return {"ok": True, "pid": _st._last_proc.pid, "checkpoint_root": str(ckpt_root)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


_st._last_log_path = None
_st._gpu_monitor_proc = None
_st._last_log_fh = None


_ansi_re = __import__("re").compile(r"\x1b\[[0-9;]*[mGKHF]|\x1b\[\?[0-9]+[hl]|\x1b\([AB]")


def _api_logs_sse(wfile) -> None:
    """Stream logs via SSE: tries log file, then checkpoint dir files."""
    import time
    start_msg = b"data: " + json.dumps({"msg": "Log stream started"}).encode() + b"\n\n"
    wfile.write(start_msg)
    wfile.flush()
    try:
        log_offset = 0       # byte offset into the log file
        ckpt_offset = 0      # byte offset into cost_trace.jsonl
        log_remainder = ""   # leftover partial line from log file
        ckpt_remainder = ""  # leftover partial line from cost_trace
        last_log_seen = None  # track which file we're reading
        for _ in range(600):  # tail for up to 10 min
            # Always re-resolve log file (handles new experiments starting)
            # Only show logs if a process is running, _last_log_path was set,
            # or a checkpoint directory exists (may contain log files)
            if not (_st._last_proc and _st._last_proc.poll() is None) and not _st._last_log_path and not (_st._checkpoint_dir and _st._checkpoint_dir.exists()):
                time.sleep(1)
                continue
            log_file = _st._last_log_path
            if not log_file or not log_file.exists() or log_file.stat().st_size == 0:
                # Search in _st._checkpoint_dir only (not parent — avoid orphan logs)
                if not (_st._checkpoint_dir and _st._checkpoint_dir.exists()):
                    time.sleep(1)
                    continue
                # Only search inside the active checkpoint dir itself
                candidates = sorted(
                    _st._checkpoint_dir.glob("ari_run_*.log"),
                    key=lambda p: p.stat().st_mtime, reverse=True
                )
                # Skip zero-byte logs
                candidates = [c for c in candidates if c.stat().st_size > 0]
                if not candidates:
                    # Also check parent (for logs written during launch, not yet moved)
                    # Match by timestamp: checkpoint name starts with YYYYMMDDHHMMSS_
                    _ckpt_name = _st._checkpoint_dir.name
                    _ckpt_ts = _ckpt_name[:14] if len(_ckpt_name) >= 14 and _ckpt_name[:8].isdigit() else ""
                    _parent_logs = sorted(
                        _st._checkpoint_dir.parent.glob("ari_run_*.log"),
                        key=lambda p: p.stat().st_mtime, reverse=True
                    )
                    _parent_logs = [c for c in _parent_logs if c.stat().st_size > 0]
                    if _ckpt_ts and _parent_logs:
                        # Match log by mtime proximity to checkpoint creation
                        import re as _re
                        _ckpt_mtime = _st._checkpoint_dir.stat().st_mtime
                        candidates = [c for c in _parent_logs if abs(c.stat().st_mtime - _ckpt_mtime) < 120]
                    if not candidates:
                        candidates = _parent_logs[:1]  # fallback: most recent
                if candidates:
                    log_file = candidates[0]
            # Reset offset when log file changes (new experiment)
            if log_file != last_log_seen:
                log_offset = 0
                log_remainder = ""
                last_log_seen = log_file
                if log_file:
                    msg = json.dumps({"msg": f"--- Switched to log: {log_file.name} ---"})
                    wfile.write(b"data: " + msg.encode() + b"\n\n")
                    wfile.flush()
            if log_file and log_file.exists():
                with open(log_file, "r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(log_offset)
                    chunk = fh.read(256 * 1024)  # read up to 256 KB of new data
                    log_offset = fh.tell()
                if chunk:
                    chunk = log_remainder + chunk
                    parts = chunk.split("\n")
                    # Last element may be incomplete line — save for next iteration
                    log_remainder = parts.pop()
                    for line in parts:
                        if line.strip():
                            clean = _ansi_re.sub("", line)
                            msg = json.dumps({"msg": clean})
                            wfile.write(b"data: " + msg.encode() + b"\n\n")
                    wfile.flush()
            # Tail checkpoint cost_trace for live progress
            if _st._checkpoint_dir and _st._checkpoint_dir.exists():
                ct = _st._checkpoint_dir / "cost_trace.jsonl"
                if ct.exists():
                    with open(ct, "r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(ckpt_offset)
                        chunk = fh.read(64 * 1024)
                        ckpt_offset = fh.tell()
                    if chunk:
                        chunk = ckpt_remainder + chunk
                        parts = chunk.split("\n")
                        ckpt_remainder = parts.pop()
                        for line in parts:
                            if not line.strip():
                                continue
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
                            except Exception:
                                log.debug("cost_trace SSE parse error", exc_info=True)
                        wfile.flush()
            # Check if process done
            if _st._last_proc and _st._last_proc.poll() is not None:
                break
            time.sleep(1)
    except Exception:
        pass
    wfile.write(b"data: " + json.dumps({"msg": "[end of log]"}).encode() + b"\n\n")
    wfile.flush()


