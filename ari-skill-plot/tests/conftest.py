"""Per-skill test bootstrap: pin this skill's root to ``sys.path[0]`` so
tests under this directory can ``from src.X import …`` (or ``from server
import …``) without picking up a sibling skill's ``src``.

The ``remove + insert(0)`` pattern matters when running paths sequentially
in a single ``pytest`` process (e.g. via ``scripts/run_all_tests.sh`` or
ad-hoc multi-path invocations): a previous skill's conftest may have
already pinned its own root, and a plain ``if not in: insert`` would
leave that earlier path ahead of ours.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SKILL_ROOT = str(Path(__file__).resolve().parent.parent)
if _SKILL_ROOT in sys.path:
    sys.path.remove(_SKILL_ROOT)
sys.path.insert(0, _SKILL_ROOT)
