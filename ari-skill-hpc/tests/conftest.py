"""Per-skill test bootstrap: pin this skill's root to ``sys.path[0]`` so
tests import the installed-shape ``ari_skill_hpc`` package from this checkout.

The ``remove + insert(0)`` pattern matters when running paths sequentially
in a single ``pytest`` process (e.g. via ``scripts/run_all_tests.sh``).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SKILL_ROOT = str(Path(__file__).resolve().parent.parent)
if _SKILL_ROOT in sys.path:
    sys.path.remove(_SKILL_ROOT)
sys.path.insert(0, _SKILL_ROOT)
