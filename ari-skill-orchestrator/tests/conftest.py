from __future__ import annotations

import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
for path in (PACKAGE_ROOT / "src", REPOSITORY_ROOT / "ari-core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
