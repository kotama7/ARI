"""REST API: checkpoint delete + switch.

Phase 3B PR-3B-2 (viz/REFACTORING.md §2 Step 2): extracted from
``ari/viz/api_state.py``.  ``api_state.py`` keeps a re-export facade
so downstream callers (and the route table inside ``server.py``) see
the same names regardless of where each function landed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import state as _st


log = logging.getLogger(__name__)

# Phase 3B PR-3B-2: bare-name wrappers that defer to ``api_state``
# at call time so ``monkeypatch.setattr(api_state, name, ...)``
# in tests intercepts the helper this module's functions call.
def _broadcast(*args, **kwargs):  # noqa: D401
    from . import api_state as _as
    return _as._broadcast(*args, **kwargs)

def _load_nodes_tree(*args, **kwargs):  # noqa: D401
    from . import api_state as _as
    return _as._load_nodes_tree(*args, **kwargs)




def _api_delete_checkpoint(body: bytes) -> dict:
    """Delete a checkpoint directory and associated log files."""
    import shutil
    data = json.loads(body)
    path = data.get("path", "")
    if not path:
        return {"error": "path required"}
    p = Path(path)
    # Resolve symlinks (e.g. /home/ may be a symlink on some HPC systems)
    try:
        p = p.resolve()
    except Exception:
        log.debug("path resolve failed: %s", path, exc_info=True)
        pass
    if not p.exists():
        # Try without resolving (path might already be canonical)
        p = Path(path)
        if not p.exists():
            return {"error": f"not found: {path}"}
    # Safety: must be inside a checkpoints directory
    if "checkpoints" not in str(p) and "checkpoints" not in str(path):
        return {"error": "refusing to delete outside checkpoints/"}
    try:
        _resolved_del = str(p.resolve())
        if _st._checkpoint_dir and str(Path(_st._checkpoint_dir).resolve()) == _resolved_del:
            _st.set_active_checkpoint(None)  # Deselect if deleting active checkpoint
            _st._last_log_path = None   # Clear log path to stop stale log display
            _st._last_experiment_md = None
            _st._last_proc = None       # Clear process ref to stop log streaming
        _st._running_procs.pop(_resolved_del, None)  # Clean up process tracking
        # Clean up sub-experiment cache for the deleted checkpoint
        _del_name = p.name
        _st._sub_experiments.pop(_del_name, None)
        # Collect log files in parent dir that were created around the same time
        parent = p.parent
        deleted_logs = []
        try:
            ckpt_mtime = p.stat().st_mtime
            for log_f in parent.glob("ari_run_*.log"):
                # Delete logs created within 60s of the checkpoint
                if abs(log_f.stat().st_mtime - ckpt_mtime) < 60:
                    log_f.unlink()
                    deleted_logs.append(log_f.name)
        except Exception:
            log.debug("log cleanup error", exc_info=True)
            pass
        # Best-effort memory purge before removing the checkpoint dir so the
        # Letta agent + archival entries bound to this checkpoint are cleaned.
        # Failures are logged but never block the on-disk delete.
        try:
            from ari.memory import get_backend
            backend = get_backend(checkpoint_dir=p)
            backend.purge_checkpoint()
        except Exception as _e:
            log.warning("memory purge failed for %s: %s", p, _e)
        shutil.rmtree(str(p))
        # Also remove the sibling experiments/{run_id}/ directory that
        # holds per-node work_dirs created by PathManager.ensure_node_work_dir.
        # Without this, deleting a checkpoint leaves orphan node work_dirs
        # under {workspace}/experiments/ that nothing references anymore.
        #
        # Historically the CLI minted its own run_id (LLM title + fresh
        # timestamp) that differed from the GUI-prepared checkpoint dir
        # name, so the naive join below missed the real experiments dir.
        # We now also search for siblings that share the 14-char timestamp
        # prefix or any node_{checkpoint_name}_* subdir — covering both
        # aligned and legacy orphans.
        deleted_experiments = []
        try:
            from ari.paths import PathManager as _PM_del
            _pm_del = _PM_del.from_checkpoint_dir(p)
            _exp_root = _pm_del.experiments_root
            _primary = _exp_root / _del_name
            if _primary.is_dir():
                shutil.rmtree(str(_primary))
                deleted_experiments.append(str(_primary))
            # Fallbacks only kick in when the aligned-name match was not
            # found — otherwise we would risk deleting unrelated projects
            # that happen to share the same 14-digit timestamp second.
            if not deleted_experiments and _exp_root.is_dir():
                # Node-directory match: experiments/*/node_{ckpt_name}_*.
                # This handles legacy orphans where the CLI minted its own
                # run_id (so the dir name differs) but node_ids still embed
                # the checkpoint name. Precise enough that same-timestamp
                # siblings belonging to other projects stay intact.
                for _cand in _exp_root.iterdir():
                    if not _cand.is_dir():
                        continue
                    try:
                        _node_dirs = list(_cand.glob(f"node_{_del_name}_*"))
                    except OSError:
                        _node_dirs = []
                    if _node_dirs:
                        shutil.rmtree(str(_cand))
                        deleted_experiments.append(str(_cand))
        except Exception:
            log.debug("experiments dir cleanup error", exc_info=True)
            pass
        # Also clean up zero-byte orphan logs in parent
        try:
            for log_f in parent.glob("ari_run_*.log"):
                if log_f.stat().st_size == 0:
                    log_f.unlink()
                    deleted_logs.append(log_f.name)
        except Exception:
            log.debug("empty log cleanup error", exc_info=True)
            pass
        result = {"ok": True, "deleted": str(p), "cleaned_logs": len(deleted_logs)}
        if deleted_experiments:
            result["deleted_experiments"] = deleted_experiments
            result["experiments_cleaned"] = len(deleted_experiments)
        return result
    except Exception as e:
        return {"error": str(e)}




def _api_switch_checkpoint(body: bytes) -> dict:
    """Switch active checkpoint directory."""
    data = json.loads(body)
    path = data.get("path", "")
    if not path:
        return {"error": "path required"}
    p = Path(path)
    if not p.exists():
        return {"error": f"not found: {path}"}
    _st.set_active_checkpoint(p)
    _st._last_mtime = 0.0  # force reload
    # Clear stale project-specific state from previous checkpoint
    if _st._last_log_fh:
        try:
            _st._last_log_fh.close()
        except Exception:
            pass
    _st._last_log_fh = None
    _st._last_experiment_md = None
    # Restore log path from checkpoint (project-isolated log)
    _log_candidates = sorted(
        p.glob("ari_run_*.log"),
        key=lambda f: f.stat().st_mtime, reverse=True
    ) if p.exists() else []
    _log_candidates = [c for c in _log_candidates if c.stat().st_size > 0]
    if _log_candidates:
        _st._last_log_path = _log_candidates[0]
    else:
        _st._last_log_path = None
    # Restore launch_config from checkpoint so /state shows correct values.
    # If launch_config.json does not exist, clear stale config from previous project.
    _lc_path = p / "launch_config.json"
    if _lc_path.exists():
        try:
            _st._launch_config = json.loads(_lc_path.read_text())
            _st._launch_llm_model = _st._launch_config.get("llm_model", "")
            _st._launch_llm_provider = _st._launch_config.get("llm_provider", "")
        except Exception:
            pass
    else:
        _st._launch_config = None
        _st._launch_llm_model = None
        _st._launch_llm_provider = None
    # Broadcast updated tree immediately
    tree = _load_nodes_tree()
    if tree:
        _broadcast(tree)
    return {"ok": True, "path": str(p)}

