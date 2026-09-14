"""Ensure this checkout's historically named ``src`` package wins."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent / "src")
for _name in [name for name in sys.modules if name == "src" or name.startswith("src.")]:
    del sys.modules[_name]
if _ROOT in sys.path:
    sys.path.remove(_ROOT)
sys.path.insert(0, _ROOT)
