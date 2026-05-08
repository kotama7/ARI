"""file:// resolver — copy a local tarball or directory into workdir.

Used by tests and by reproducibility checks where the curated bundle
already lives on the local filesystem (i.e. the same machine that ran
the experiment).
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional


def resolve(
    ref: str,
    workdir: Path,
    *,
    registry: Optional[str] = None,
    token: Optional[str] = None,
) -> Path:
    src = Path(ref[len("file://"):]) if ref.startswith("file://") else Path(ref)
    if not src.exists():
        raise FileNotFoundError(f"file resolver: source not found: {src}")
    workdir.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        target = workdir / src.name
        shutil.copytree(src, target)
        return target
    target = workdir / src.name
    shutil.copy2(src, target)
    return target
