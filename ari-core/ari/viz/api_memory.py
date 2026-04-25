"""Dashboard memory-management API handlers.

- GET /api/memory/health       — backend reachability for the header pill
- GET /api/memory/detect       — recommended deployment path
- POST /api/memory/start-local — start docker/singularity/pip Letta
- POST /api/memory/stop-local  — stop whatever local Letta is running
- GET /api/checkpoint/{id}/memory_access — per-node provenance
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

log = logging.getLogger(__name__)


def _scripts_root() -> Path:
    # ari-core → parents[2] == ARI repo root
    return Path(__file__).resolve().parents[3] / "scripts" / "letta"


def _api_memory_health(checkpoint_dir: "Path | None") -> dict:
    if checkpoint_dir is None:
        return {
            "status": "unknown",
            "latency_ms": 0.0,
            "namespace": None,
            "server_version": "",
            "detected_deployment": _detect_deployment(),
            "reason": "no active checkpoint",
        }
    try:
        os.environ["ARI_CHECKPOINT_DIR"] = str(checkpoint_dir)
        from ari_skill_memory.backends import get_backend
        backend = get_backend(checkpoint_dir=checkpoint_dir)
        h = backend.health()
        return {
            "status": "ok" if h.get("ok") else "down",
            "latency_ms": h.get("latency_ms", 0.0),
            "namespace": h.get("namespace"),
            "server_version": h.get("server_version", ""),
            "detected_deployment": _detect_deployment(),
        }
    except Exception as e:
        return {
            "status": "down",
            "latency_ms": 0.0,
            "namespace": None,
            "server_version": "",
            "detected_deployment": _detect_deployment(),
            "error": str(e),
        }


def _api_memory_detect() -> dict:
    recommended = _detect_deployment()
    available = []
    reasons: dict[str, str] = {}
    if shutil.which("docker"):
        available.append("docker")
    else:
        reasons["docker"] = "docker not on PATH"
    if shutil.which("singularity") or shutil.which("apptainer"):
        available.append("singularity")
    else:
        reasons["singularity"] = "neither singularity nor apptainer found"
    if shutil.which("python3"):
        available.append("pip")
    return {
        "recommended": recommended,
        "available": available,
        "reasons": reasons,
    }


def _api_memory_start_local(body: bytes) -> dict:
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        data = {}
    path = (data.get("path") or "auto").strip()
    if path == "auto":
        path = _detect_deployment()
    root = _scripts_root()
    cmd: list[str] = []
    if path == "docker":
        cmd = ["docker", "compose", "-f", str(root / "docker-compose.yml"),
               "up", "-d"]
    elif path == "singularity":
        cmd = ["bash", str(root / "start_singularity.sh")]
    elif path == "pip":
        cmd = ["bash", str(root / "start_pip.sh")]
    else:
        return {"ok": False, "error": f"unsupported path: {path}"}
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=300,
        )
        return {"ok": True, "path": path, "stdout": out.stdout[-2000:]}
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError) as e:
        return {"ok": False, "path": path, "error": str(e)}


def _api_memory_stop_local() -> dict:
    root = _scripts_root()
    outputs: list[str] = []
    for cmd in (
        ["docker", "compose", "-f", str(root / "docker-compose.yml"), "down"],
        ["singularity", "instance", "stop", "ari-letta"],
        ["apptainer", "instance", "stop", "ari-letta"],
        ["pkill", "-f", "letta server"],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            outputs.append(f"{cmd[0]} rc={r.returncode}")
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            outputs.append(f"{cmd[0]} timeout")
    return {"ok": True, "attempts": outputs}


def _api_memory_restart(body: bytes) -> dict:
    """Stop the running Letta deployment and start it again.

    Long-lived Letta daemons don't reload env vars, so after the user
    edits provider keys / handles in Settings the server must be
    restarted before the new values take effect. This endpoint is the
    GUI surface for that — it runs ``stop_local`` then ``start_local``
    sequentially and reports both phases.
    """
    stop_result = _api_memory_stop_local()
    # Brief pause so any port held by the previous process is released.
    time.sleep(2)
    start_result = _api_memory_start_local(body)
    return {
        "ok": bool(start_result.get("ok")),
        "stop": stop_result,
        "start": start_result,
    }


def _api_memory_access(
    ckpt_id: str, node_id: str, op: str = "all", limit: int = 200,
    resolver=None,
) -> dict:
    """Return per-node access log view for the Tree page."""
    if resolver is not None:
        d = resolver(ckpt_id)
    else:
        d = None
    if d is None:
        return {"error": "checkpoint not found"}
    log_path = d / "memory_access.jsonl"
    if not log_path.exists():
        return {
            "node_id": node_id, "writes": [], "reads": [], "read_by_entry": {},
            "error": "access log not enabled or not yet written",
        }
    writes: list[dict] = []
    reads: list[dict] = []
    read_by_entry: dict[str, dict] = {}
    try:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("node_id") != node_id:
                continue
            if ev.get("op") == "write" and op in ("write", "all"):
                writes.append(ev)
            elif ev.get("op") == "read" and op in ("read", "all"):
                reads.append(ev)
                for r in ev.get("results", []) or []:
                    eid = r.get("entry_id")
                    if not eid:
                        continue
                    slot = read_by_entry.setdefault(eid, {"count": 0, "last_ts": 0})
                    slot["count"] += 1
                    slot["last_ts"] = max(slot["last_ts"], ev.get("ts", 0))
    except Exception as e:  # pragma: no cover
        return {"error": f"read failed: {e}"}
    writes.sort(key=lambda x: -x.get("ts", 0))
    reads.sort(key=lambda x: -x.get("ts", 0))
    if limit > 0:
        writes = writes[:limit]
        reads = reads[:limit]
    return {
        "node_id": node_id,
        "writes": writes,
        "reads": reads,
        "read_by_entry": read_by_entry,
    }


# ─ helpers ────────────────────────────────────────────────────────────

def _detect_deployment() -> str:
    on_hpc = bool(os.environ.get("SLURM_CLUSTER_NAME") or os.environ.get("SLURM_JOB_ID"))
    if shutil.which("docker") and not on_hpc:
        return "docker"
    if shutil.which("singularity") or shutil.which("apptainer"):
        return "singularity"
    if shutil.which("python3"):
        return "pip"
    return "none"


__all__ = [
    "_api_memory_health",
    "_api_memory_detect",
    "_api_memory_start_local",
    "_api_memory_stop_local",
    "_api_memory_restart",
    "_api_memory_access",
]
