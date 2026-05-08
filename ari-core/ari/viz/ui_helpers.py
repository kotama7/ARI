"""UI helper functions extracted from viz/server.py (Phase 3B).

Three pure helpers used by the dashboard rendering layer:

- :func:`_extract_goal_from_md` — pull the Research Goal section from
  an ``experiment.md`` string.
- :func:`_build_experiment_detail_config` — render the merged
  default → profile → launch config as a redacted text block.
- :func:`_collect_resource_metrics` — sample current process count /
  RSS / load average via ``/proc``.

Each function used to live as a module-level helper in
``ari.viz.server``; the call-sites continue to import them under the
same names so the (large) ``_Handler.do_GET`` dispatch table needs no
edit in this PR.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from . import state as _st
from .api_settings import _api_get_settings


log = logging.getLogger(__name__)

_REDACT_KEYS = {"api_key", "apikey", "api-key", "token", "secret", "password"}


def _extract_goal_from_md(md: str) -> str:
    """Extract the Research Goal section body from an experiment.md string.

    Accepts headings like `## Goal`, `## Research Goal`, or any heading
    containing 'research goal'. Falls back to the first non-empty line
    (stripped of leading #) when no Goal section is found.
    """
    if not md:
        return ""
    goal_lines: list[str] = []
    in_goal = False
    for line in md.splitlines():
        s = line.strip()
        heading = s.lstrip("#").strip().lower() if s.startswith("#") else ""
        if heading in ("goal", "research goal") or "research goal" in heading:
            in_goal = True
            continue
        if in_goal:
            if s.startswith("#"):
                break
            if s:
                goal_lines.append(s)
    if goal_lines:
        return " ".join(goal_lines)
    if md.strip():
        return next((l.lstrip("#").strip() for l in md.splitlines() if l.strip()), "")
    return ""


def _build_experiment_detail_config() -> str:
    """Serialize merged (default + profile + launch) config as a redacted text block.

    Called on-demand by /api/experiment-detail (not on every /state poll).
    """
    try:
        import yaml as _yaml
        import copy as _copy
        from ari.config.finder import package_config_root, find_profile_yaml
        config_root = package_config_root()
        default_cfg = {}
        default_yaml = config_root / "default.yaml"
        if default_yaml.exists():
            default_cfg = _yaml.safe_load(default_yaml.read_text()) or {}
        merged = _copy.deepcopy(default_cfg)

        # Locate workflow.yaml / profile yaml
        ckpt_dir = _st._checkpoint_dir
        lc_profile = ""
        if _st._launch_config:
            lc_profile = _st._launch_config.get("profile", "")
        if not lc_profile and ckpt_dir and ckpt_dir.exists():
            lc_f = ckpt_dir / "launch_config.json"
            if lc_f.exists():
                try:
                    lc_profile = json.loads(lc_f.read_text()).get("profile", "")
                except Exception:
                    pass
        candidates = []
        if ckpt_dir:
            candidates.append(ckpt_dir / "workflow.yaml")
        if lc_profile:
            prof = find_profile_yaml(lc_profile, package_root=config_root)
            if prof is not None:
                candidates.append(prof)
        candidates.append(config_root / "default.yaml")
        for wf_path in candidates:
            if wf_path.exists():
                tmp = _yaml.safe_load(wf_path.read_text()) or {}
                if tmp.get("bfts") or tmp.get("hpc"):
                    for k, v in tmp.items():
                        if isinstance(v, dict) and isinstance(merged.get(k), dict):
                            merged[k].update(v)
                        else:
                            merged[k] = v
                    break

        # Overlay LLM info
        saved = _api_get_settings()
        launch_model = _st._launch_llm_model or saved.get("llm_model", "")
        launch_provider = _st._launch_llm_provider or saved.get("llm_provider", "")
        merged.setdefault("llm", {})
        merged["llm"]["model"] = launch_model
        merged["llm"]["backend"] = launch_provider
        merged["llm"]["base_url"] = saved.get("ollama_host", "")

        lines = []
        for sk, sv in merged.items():
            if sk == "skills":
                continue
            if isinstance(sv, dict):
                lines.append(f"[{sk}]")
                for dk, dv in sv.items():
                    if dk.lower() in _REDACT_KEYS or "key" in dk.lower():
                        lines.append(f"  {dk}: ***")
                    else:
                        lines.append(f"  {dk}: {dv}")
            else:
                lines.append(f"{sk}: {sv}")
        return "\n".join(lines)
    except Exception:
        log.warning("Failed to build experiment_detail_config", exc_info=True)
        return ""


def _collect_resource_metrics() -> dict:
    """Collect system resource metrics for the current user.

    Reads ``/proc`` directly (no external dependencies) to count processes
    and sum RSS for all processes owned by the current UID.
    """
    uid = os.getuid()
    proc_count = 0
    total_rss_kb = 0
    try:
        for entry in os.scandir("/proc"):
            if not entry.name.isdigit():
                continue
            try:
                if os.stat(entry.path).st_uid != uid:
                    continue
                proc_count += 1
                statm = Path(entry.path, "statm").read_text().split()
                total_rss_kb += int(statm[1]) * 4  # pages -> KB
            except (FileNotFoundError, PermissionError, IndexError, ValueError):
                pass
    except Exception:
        pass

    # CPU load average
    try:
        load1, load5, load15 = os.getloadavg()
    except Exception:
        load1 = load5 = load15 = 0.0

    # Experiment-specific: PID of running experiment
    exp_pid = None
    if _st._last_proc and _st._last_proc.poll() is None:
        exp_pid = _st._last_proc.pid

    return {
        "process_count": proc_count,
        "memory_rss_mb": round(total_rss_kb / 1024, 1),
        "cpu_load_1m": round(load1, 2),
        "cpu_load_5m": round(load5, 2),
        "cpu_load_15m": round(load15, 2),
        "cpu_count": os.cpu_count() or 1,
        "experiment_pid": exp_pid,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
