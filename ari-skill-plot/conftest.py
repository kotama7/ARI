"""Per-skill import bootstrap for isolated plot tests."""

from __future__ import annotations

import sys
from pathlib import Path

_SKILL_ROOT = str(Path(__file__).resolve().parent)
if _SKILL_ROOT in sys.path:
    sys.path.remove(_SKILL_ROOT)
sys.path.insert(0, _SKILL_ROOT)
for _module_name in [name for name in sys.modules if name == "src" or name.startswith("src.")]:
    del sys.modules[_module_name]
