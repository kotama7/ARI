from __future__ import annotations
"""Shared mutable state."""
from pathlib import Path
from ari.paths import PathManager

# ``_settings_path`` is the *active* (project-scoped) settings file — updated
# whenever the selected checkpoint changes via ``set_active_checkpoint``.  It
# is ``None`` until a checkpoint is selected; reads return code defaults and
# writes raise an explicit error in that state.  ARI no longer maintains any
# global file under ``~/.ari/``.  Tests may still monkeypatch this attribute
# directly for isolated scenarios.
_settings_path: "Path | None" = None
_ari_root: "Path" = Path(__file__).parent.parent.parent.parent  # /ARI/
_env_write_path: "Path" = Path(__file__).parent.parent.parent.parent / ".env"
_port: int = 9886
_server_port: int = 9886
_clients: set = set()
_loop = None
_checkpoint_dir: "Path | None" = None
_last_mtime: float = 0.0
_last_proc = None
_running_procs: dict = {}  # {resolved_checkpoint_path_str: subprocess.Popen}
_last_log_fh = None
_last_log_path: "str | None" = None
_last_experiment_md: "str | None" = None
_launch_llm_model: "str | None" = None
_launch_llm_provider: "str | None" = None
_launch_config: "dict | None" = None
_gpu_monitor_proc = None
_sub_experiments: dict = {}  # {run_id: meta dict with parent_run_id, recursion_depth, ...}
_staging_dir: "Path | None" = None  # temporary upload staging before launch


def get_sub_experiments() -> dict:
    """Return a snapshot of the sub-experiment registry."""
    return dict(_sub_experiments)


def set_sub_experiment(run_id: str, meta: dict) -> None:
    """Insert or replace a sub-experiment record by run_id."""
    if not run_id:
        return
    _sub_experiments[run_id] = dict(meta)


def set_active_checkpoint(path: "Path | None") -> None:
    """Switch the active checkpoint directory and rebind project-scoped paths.

    Passing ``None`` detaches the active project — ``_settings_path`` becomes
    ``None`` and any settings read returns built-in defaults while a save
    raises an explicit error.  ARI does not maintain a global ``~/.ari``
    location anymore; callers must select or create a project first.
    """
    global _checkpoint_dir, _settings_path
    if path is None:
        _checkpoint_dir = None
        _settings_path = None
        return
    p = Path(path)
    _checkpoint_dir = p
    _settings_path = PathManager.project_settings_path(p)


def active_settings_path() -> "Path | None":
    """Return the settings file that reads/writes should target right now.

    Returns ``None`` when no checkpoint is selected — callers must handle
    that case (e.g. fall back to defaults for reads, refuse the write).
    """
    return _settings_path


def require_checkpoint_dir() -> "str | None":
    """Return error message if _checkpoint_dir is not usable, else None."""
    if _checkpoint_dir is None:
        return "No active project. Select or create a project first."
    if not _checkpoint_dir.exists():
        return f"Checkpoint directory does not exist: {_checkpoint_dir}"
    return None
