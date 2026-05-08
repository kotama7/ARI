"""local-tarball backend — write the bundle to a local directory.

Useful as the zero-dependency fallback (CI, offline use, or when the user
just wants ``ear_published.tar.gz`` next to their checkpoint).

The "ref" returned is a ``file://`` URI, which the ``ari clone`` file
resolver already understands.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


def publish(
    *,
    tar_path: Path,
    manifest: dict,
    metadata: dict,
    visibility: str,
    dry_run: bool,
    tarball_sha256: str,
) -> dict:
    if dry_run:
        return {
            "ref": f"file://(dryrun)/{tar_path.name}",
            "tarball_sha256": tarball_sha256,
            "dryrun": True,
        }
    out_dir = Path(metadata.get("local_tarball_out") or os.environ.get("ARI_LOCAL_TARBALL_OUT") or ".")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "bundle.tar.gz"
    if target.resolve() != tar_path.resolve():
        shutil.copy2(tar_path, target)
    return {
        "ref": f"file://{target.resolve()}",
        "tarball_sha256": tarball_sha256,
        "dryrun": False,
    }


def promote(
    *, ref: str, target: str, extra: dict, dry_run: bool,
) -> dict:
    """local-tarball has no notion of visibility; promote is a no-op."""
    return {"visibility": target, "noop": True}
