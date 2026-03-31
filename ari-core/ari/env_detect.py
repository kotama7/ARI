"""ARI environment detection utilities.

Detects available job schedulers, container runtimes, and HPC resources
without any hardcoded domain knowledge.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Optional


def _run(cmd: list[str], timeout: int = 5) -> Optional[str]:
    """Run a command and return stdout, or None on failure."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def detect_scheduler() -> str:
    """Detect the available job scheduler.

    Returns one of: slurm | pbs | lsf | sge | kubernetes | none
    """
    checks = [
        (["sinfo", "--version"], "slurm"),
        (["qstat", "--version"], "pbs"),
        (["bhosts"], "lsf"),
        (["qhost"], "sge"),
        (["kubectl", "version", "--client"], "kubernetes"),
    ]
    for cmd, name in checks:
        if shutil.which(cmd[0]):
            out = _run(cmd)
            if out is not None:
                return name
    return "none"


def detect_container() -> str:
    """Detect available container runtime.

    Returns one of: docker | singularity | apptainer | none
    """
    for name in ("apptainer", "singularity", "docker"):
        if shutil.which(name):
            return name
    return "none"


def get_slurm_partitions() -> list[dict]:
    """Parse sinfo output into a list of partition dicts.

    Each dict: {name, nodes, cpus, memory, state}
    Returns empty list if SLURM is unavailable.
    """
    if not shutil.which("sinfo"):
        return []
    out = _run(["sinfo", "--noheader", "-o", "%P %D %c %m %a"], timeout=10)
    if not out:
        return []

    partitions = []
    for line in out.strip().splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        name = parts[0].rstrip("*")
        partitions.append({
            "name": name,
            "nodes": parts[1],
            "cpus": parts[2],
            "memory": parts[3],
            "state": parts[4],
        })
    return partitions


def get_environment_summary() -> dict:
    """Return a full environment summary dict."""
    scheduler = detect_scheduler()
    return {
        "scheduler": scheduler,
        "container": detect_container(),
        "partitions": get_slurm_partitions() if scheduler == "slurm" else [],
    }
