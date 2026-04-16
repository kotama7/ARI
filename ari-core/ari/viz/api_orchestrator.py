from __future__ import annotations
"""ARI viz: api_orchestrator — sub-experiment registry, launch, and listing.

Backs the GUI sub-experiment endpoints. Sub-experiment records live alongside
checkpoints as ``meta.json`` files; this module reads them, caches them in
``state._sub_experiments``, and exposes a launch helper that enforces the
recursion-depth ceiling.
"""

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import state as _st


DEFAULT_MAX_RECURSION_DEPTH = 3


def _logs_root() -> Path:
    """Resolve the directory under which sub-experiment checkpoints live.

    Honors ``ARI_ORCHESTRATOR_LOGS`` for tests; otherwise defaults to the
    workspace's ``checkpoints/`` directory adjacent to the project root.
    """
    override = os.environ.get("ARI_ORCHESTRATOR_LOGS")
    if override:
        return Path(override)
    return Path(_st._ari_root) / "workspace" / "checkpoints"


def _scan_disk() -> dict:
    """Scan checkpoint dirs for meta.json files and return {run_id: meta}."""
    found: dict = {}
    base = _logs_root()
    if not base.exists():
        return found
    for ck in base.iterdir():
        if not ck.is_dir():
            continue
        meta_file = ck / "meta.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text())
        except Exception:
            continue
        if not isinstance(meta, dict):
            continue
        run_id = meta.get("run_id") or ck.name
        record = dict(meta)
        record["checkpoint_dir"] = str(ck)
        found[run_id] = record
    return found


def _api_list_sub_experiments() -> dict:
    """Return all known sub-experiments (disk-authoritative).

    Replaces the in-memory cache with what is actually on disk so that
    deleted checkpoints no longer appear in the listing.
    """
    disk = _scan_disk()
    # Replace cache entirely — stale entries for deleted checkpoints are dropped.
    _st._sub_experiments.clear()
    for rid, meta in disk.items():
        _st.set_sub_experiment(rid, meta)
    items = list(_st.get_sub_experiments().values())
    items.sort(
        key=lambda m: (m.get("created_at") or "", m.get("run_id") or ""),
        reverse=True,
    )
    return {"sub_experiments": items}


def _api_get_sub_experiment(run_id: str) -> dict:
    if not run_id:
        return {"error": "run_id required"}
    disk = _scan_disk()
    if run_id in disk:
        _st.set_sub_experiment(run_id, disk[run_id])
        return disk[run_id]
    cache = _st.get_sub_experiments()
    if run_id in cache:
        return cache[run_id]
    return {"error": f"run_id '{run_id}' not found"}


def _slugify(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]", "_", text or "experiment")
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:maxlen] or "experiment"


def _api_launch_sub_experiment(body: bytes) -> dict:
    """Launch a child experiment with recursion-depth enforcement.

    Body fields:
      experiment_md (str, required)
      max_recursion_depth (int, default 3)
      parent_run_id (str, optional)
      recursion_depth (int, optional, default 0)
      dry_run (bool, optional) — skip subprocess launch (used by tests)
    """
    try:
        data = json.loads(body) if body else {}
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return {"ok": False, "error": f"Invalid request body: {e}"}

    experiment_md = data.get("experiment_md", "")
    parent_run_id = data.get("parent_run_id") or None
    recursion_depth = int(data.get("recursion_depth", 0) or 0)
    _raw_mrd = data.get("max_recursion_depth")
    max_recursion_depth = int(_raw_mrd) if _raw_mrd is not None else DEFAULT_MAX_RECURSION_DEPTH
    dry_run = bool(data.get("dry_run"))

    if recursion_depth >= max_recursion_depth:
        return {
            "ok": False,
            "error": (
                f"Recursion limit reached: recursion_depth={recursion_depth} "
                f">= max_recursion_depth={max_recursion_depth}"
            ),
            "recursion_depth": recursion_depth,
            "max_recursion_depth": max_recursion_depth,
            "parent_run_id": parent_run_id,
        }

    base = _logs_root()
    base.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
    first_line = ""
    for line in (experiment_md or "").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            first_line = stripped[:60]
            break
    run_id = f"{ts}_{_slugify(first_line)}"
    ckpt_dir = base / run_id
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "recursion_depth": recursion_depth,
        "max_recursion_depth": max_recursion_depth,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checkpoint_dir": str(ckpt_dir),
    }
    (ckpt_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    if experiment_md:
        (ckpt_dir / "experiment.md").write_text(experiment_md, encoding="utf-8")

    _st.set_sub_experiment(run_id, meta)

    pid = None
    if not dry_run:
        cmd = [
            "python3", "-m", "ari.cli", "run",
            str(ckpt_dir / "experiment.md"),
        ]
        proc_env = os.environ.copy()
        proc_env["ARI_PARENT_RUN_ID"] = run_id
        proc_env["ARI_RECURSION_DEPTH"] = str(recursion_depth + 1)
        proc_env["ARI_MAX_RECURSION_DEPTH"] = str(max_recursion_depth)
        proc_env["ARI_CHECKPOINT_DIR"] = str(ckpt_dir)
        try:
            log_fh = open(ckpt_dir / "orchestrator.log", "w")
            proc = subprocess.Popen(
                cmd,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                cwd=str(_st._ari_root / "ari-core"),
                env=proc_env,
                start_new_session=True,
            )
            pid = proc.pid
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "run_id": run_id,
                "checkpoint_dir": str(ckpt_dir),
            }

    return {
        "ok": True,
        "run_id": run_id,
        "pid": pid,
        "checkpoint_dir": str(ckpt_dir),
        "parent_run_id": parent_run_id,
        "recursion_depth": recursion_depth,
        "max_recursion_depth": max_recursion_depth,
    }
