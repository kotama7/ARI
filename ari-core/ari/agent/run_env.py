"""Capture-and-read helper for `_run_env.json`.

Each `_run_env.json` records *where and on what hardware* a tool call ran:
hostname, SLURM job id/partition (when applicable), CPU model, thread count.
Skills (hpc, coding) write it from inside the executing process so that the
node_report builder can later attach this metadata to `node_report.json`,
and downstream stages (paper writing, reproducibility check) can recover
"this experiment ran on sx40 partition, hostnameX, Intel Xeon …" instead
of guessing from blank artifacts.

Why a flat JSON file beside the work_dir, not an env var:
- SLURM jobs run on a different node than the agent — env vars don't survive
- run_bash subprocesses are short-lived — same problem
- The work_dir is the one place both the executing process and the orchestrator
  can see, so it's the natural carrier
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_RUN_ENV_FILENAME = "_run_env.json"


def capture_env(
    work_dir: Path | str,
    *,
    executor: str,
    slurm_job_id: str = "",
    slurm_partition: str = "",
) -> dict:
    """Write `<work_dir>/_run_env.json` describing the current host/HW.

    Idempotent in the sense of correctness: each call OVERWRITES the file.
    The latest tool call's environment wins, which matches what the user
    cares about ("where did the LAST measurement come from").

    Returns the dict that was written. Best-effort — never raises.
    """
    info: dict[str, Any] = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "executor": executor or "local",
    }

    # SLURM context (preferred when present; either via arg or env)
    info["slurm_job_id"] = (
        str(slurm_job_id or os.environ.get("SLURM_JOB_ID", "")).strip()
    )
    info["slurm_partition"] = (
        slurm_partition or os.environ.get("SLURM_JOB_PARTITION", "")
    ).strip()
    nodelist = os.environ.get("SLURM_JOB_NODELIST", "").strip()
    if nodelist:
        info["slurm_nodelist"] = nodelist

    # Hostname
    try:
        info["hostname"] = subprocess.run(
            ["hostname"], capture_output=True, text=True, timeout=2,
        ).stdout.strip() or "unknown"
    except Exception:
        info["hostname"] = "unknown"

    # CPU info via lscpu (Linux); fall back to /proc/cpuinfo on parse miss
    info["cpu_info"] = _capture_cpu_info()

    # Memory total
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        info["mem_total_kb"] = int(parts[1])
                    break
    except Exception:
        pass

    # Compiler version (best-effort; helps reproducibility)
    info["compilers"] = _capture_compilers()

    out_path = Path(work_dir) / _RUN_ENV_FILENAME
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(info, indent=2))
    except OSError:
        pass
    return info


def read_run_env(work_dir: Path | str) -> dict:
    """Read `<work_dir>/_run_env.json` if present.

    Returns ``{}`` when the file is missing or unparseable. Used by the
    node_report builder to enrich the report with executor metadata.
    """
    p = Path(work_dir) / _RUN_ENV_FILENAME
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _capture_cpu_info() -> dict:
    """Best-effort CPU summary via lscpu, with /proc/cpuinfo as backup."""
    info: dict[str, Any] = {}
    try:
        out = subprocess.run(
            ["lscpu"], capture_output=True, text=True, timeout=3,
        ).stdout
        for line in out.splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if k == "Model name":
                info["model"] = v
            elif k == "CPU(s)":
                try: info["threads"] = int(v)
                except ValueError: pass
            elif k.startswith("CPU MHz") or k == "CPU max MHz":
                try: info["mhz"] = float(v)
                except ValueError: pass
            elif k == "Architecture":
                info["arch"] = v
            elif k == "Vendor ID":
                info["vendor"] = v
    except Exception:
        pass
    if "model" in info:
        return info

    # Fallback parse /proc/cpuinfo
    try:
        with open("/proc/cpuinfo") as fh:
            text = fh.read()
        m = re.search(r"^model name\s*:\s*(.+)$", text, re.MULTILINE)
        if m: info["model"] = m.group(1).strip()
        info["threads"] = len(re.findall(r"^processor\s*:", text, re.MULTILINE))
        m = re.search(r"^cpu MHz\s*:\s*([\d.]+)", text, re.MULTILINE)
        if m:
            try: info["mhz"] = float(m.group(1))
            except ValueError: pass
    except Exception:
        pass
    return info


def _capture_compilers() -> dict:
    """Record version of common compilers if available."""
    out: dict[str, str] = {}
    for tool, args in (("gcc", ["--version"]),
                       ("g++", ["--version"]),
                       ("python3", ["--version"])):
        try:
            r = subprocess.run(
                [tool, *args], capture_output=True, text=True, timeout=3,
            )
            text = (r.stdout or r.stderr or "").splitlines()
            if text:
                out[tool] = text[0].strip()
        except Exception:
            continue
    return out


def shell_capture_snippet(
    *,
    executor: str = "slurm",
) -> str:
    """Return a portable bash snippet that writes `_run_env.json` in $PWD.

    Used at the *top* of an sbatch script — runs on the compute node, captures
    that node's environment (not the submitting agent's). The snippet writes
    JSON via a heredoc; it never errors-out the surrounding script (errors are
    silently swallowed via `|| true`).
    """
    return rf"""
# ── ari run-env capture (auto-injected) ────────────────────────────────────
{{
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  hn="$(hostname 2>/dev/null || echo unknown)"
  jid="${{SLURM_JOB_ID:-}}"
  part="${{SLURM_JOB_PARTITION:-}}"
  nodelist="${{SLURM_JOB_NODELIST:-}}"
  cpu_model="$(lscpu 2>/dev/null | awk -F: '/^Model name/{{sub(/^ +/,"",$2); print $2; exit}}')"
  cpu_threads="$(lscpu 2>/dev/null | awk -F: '/^CPU\(s\)/{{print $2; exit}}' | tr -d ' ')"
  cpu_mhz="$(lscpu 2>/dev/null | awk -F: '/^CPU max MHz/{{print $2; exit}}' | tr -d ' ')"
  cpu_arch="$(lscpu 2>/dev/null | awk -F: '/^Architecture/{{print $2; exit}}' | tr -d ' ')"
  mem_kb="$(awk '/MemTotal/{{print $2; exit}}' /proc/meminfo 2>/dev/null)"
  gxx_v="$(g++ --version 2>/dev/null | head -1)"
  py_v="$(python3 --version 2>/dev/null)"
  cat > _run_env.json <<JSON_EOF
{{
  "captured_at": "$ts",
  "executor": "{executor}",
  "hostname": "$hn",
  "slurm_job_id": "$jid",
  "slurm_partition": "$part",
  "slurm_nodelist": "$nodelist",
  "cpu_info": {{
    "model": "$cpu_model",
    "threads": ${{cpu_threads:-0}},
    "mhz": ${{cpu_mhz:-0}},
    "arch": "$cpu_arch"
  }},
  "mem_total_kb": ${{mem_kb:-0}},
  "compilers": {{
    "g++": "$gxx_v",
    "python3": "$py_v"
  }}
}}
JSON_EOF
}} 2>/dev/null || true
# ── end run-env capture ───────────────────────────────────────────────────
"""
