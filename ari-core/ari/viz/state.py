from __future__ import annotations
"""Shared mutable state."""
from pathlib import Path

_settings_path: "Path" = Path.home() / ".ari" / "settings.json"
_ari_home: "Path" = Path.home() / ".ari"
_ari_root: "Path" = Path(__file__).parent.parent.parent.parent  # /ARI/
_env_write_path: "Path" = Path(__file__).parent.parent.parent.parent / ".env"
_port: int = 9886
_server_port: int = 9886
_clients: set = set()
_loop = None
_checkpoint_dir: "Path | None" = None
_last_mtime: float = 0.0
_last_proc = None
_last_log_fh = None
_last_log_path: "str | None" = None
_last_experiment_md: "str | None" = None
_launch_llm_model: "str | None" = None
_launch_llm_provider: "str | None" = None
_launch_config: "dict | None" = None
_gpu_monitor_proc = None


def require_checkpoint_dir() -> "str | None":
    """Return error message if _checkpoint_dir is not usable, else None."""
    if _checkpoint_dir is None:
        return "No active project. Select or create a project first."
    if not _checkpoint_dir.exists():
        return f"Checkpoint directory does not exist: {_checkpoint_dir}"
    return None
