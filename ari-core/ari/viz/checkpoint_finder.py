"""Checkpoint discovery + PID liveness probe.

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



def _checkpoint_search_bases() -> list[Path]:
    """Return the canonical list of directories that may contain checkpoint subdirs."""
    _ari_root = Path(__file__).parent.parent.parent.parent  # ARI/
    return [
        _ari_root / "workspace" / "checkpoints",
        _ari_root / "checkpoints",
        Path(__file__).parent.parent.parent / "checkpoints",   # ari-core/checkpoints
        _ari_root / "ari-core" / "checkpoints",
        Path.cwd() / "checkpoints",
        Path.cwd() / "ari-core" / "checkpoints",
        Path(__file__).resolve().parents[2] / "checkpoints",
    ]



def _check_pid_alive(checkpoint_dir: Path) -> str:
    """Check if the process that owns a checkpoint is still alive via .ari_pid."""
    from ari.pidfile import check_pid
    return check_pid(checkpoint_dir)




def _resolve_checkpoint_dir(ckpt_id: str) -> Path | None:
    """Locate a checkpoint directory by id across known search paths.

    Phase 3B PR-3B-2: defer the ``_checkpoint_search_bases`` lookup to
    the ``api_state`` facade at call time so tests that
    ``monkeypatch.setattr(api_state, "_checkpoint_search_bases", ...)``
    are honoured here even though this function lives in a sibling
    module.
    """
    from . import api_state as _as
    for base in _as._checkpoint_search_bases():
        p = base / ckpt_id
        if p.exists():
            return p
    return None

