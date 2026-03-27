from __future__ import annotations
"""Shared mutable state."""
from pathlib import Path

_settings_path: "Path" = Path.home() / ".ari" / "settings.json"
_ari_home: "Path" = Path.home() / ".ari"
_port: int = 9886
_server_port: int = 9886
_clients: list = []
_loop = None
_checkpoint_dir: "Path | None" = None
_last_mtime: float = 0.0
_last_proc = None
_last_log_fh = None
_last_log_path: "str | None" = None
_last_experiment_md: "str | None" = None
_gpu_monitor_proc = None
