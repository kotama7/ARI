"""Provenance helpers — derive artifact refs + hashes from node_report.json.

node_report.json is the source of truth (PLAN §2). It already carries
``files_changed`` entries WITH sha256 (added: ``sha256``; modified:
``sha256_after``) and ``artifacts`` entries WITH a classified ``role`` but
NO hash. This module turns those into ``ArtifactRef``s, computing sha256 for
artifacts that lack one, and resolves the node work_dir for dereferencing.
It never re-stores node_report fields; it only points at evidence on disk.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .schemas import ArtifactRef

_CHUNK = 1 << 20  # 1 MiB


def sha256_of(path: Path) -> str | None:
    """sha256 of a file's contents, or None if it does not exist / is unreadable."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK), b""):
                h.update(chunk)
        return h.hexdigest()
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
        return None


def normalize_artifact_path(p: str, base: Path) -> str:
    """Return ``p`` relative to ``base`` when possible, else its basename.

    Keeps refs portable (checkpoint/work_dir-relative) so they survive
    ``cp -r`` of a checkpoint.
    """
    raw = Path(p)
    try:
        if raw.is_absolute():
            return str(raw.relative_to(base))
        # already relative — collapse any leading ./
        return str(raw)
    except ValueError:
        return raw.name


def node_work_dir(experiments_root: Path, run_id: str, node_id: str) -> Path:
    """Resolve a node's work_dir (where node_report.json + artifacts live)."""
    return Path(experiments_root) / run_id / node_id


def load_node_report(experiments_root: Path, run_id: str, node_id: str) -> dict | None:
    """Dereference a ``node_report_ref`` to the on-disk report, or None."""
    p = node_work_dir(experiments_root, run_id, node_id) / "node_report.json"
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def refs_from_node_report(
    node_report: dict, work_dir: Path, *, compute_missing: bool = True
) -> list[ArtifactRef]:
    """Build ArtifactRefs from a node_report.

    - ``files_changed`` (added/modified): sha256 already recorded — reuse it.
    - ``artifacts`` ({filename, role}): no recorded hash.
      * ``compute_missing=True`` (index/write time): hash from disk to
        establish a baseline to store in the memory index.
      * ``compute_missing=False`` (audit time): leave ``sha256=None`` so the
        auditor reports ``unhashed`` rather than re-hashing against itself
        (which would be a circular, meaningless "verification").
    De-duplicated by path; an artifact already covered by files_changed keeps
    its recorded hash.
    """
    work_dir = Path(work_dir)
    by_path: dict[str, ArtifactRef] = {}

    fc = node_report.get("files_changed") or {}
    for entry in (fc.get("added") or []):
        path = entry.get("path")
        if path:
            by_path[path] = ArtifactRef(path=path, sha256=entry.get("sha256"), role="source")
    for entry in (fc.get("modified") or []):
        path = entry.get("path")
        if path and path not in by_path:
            by_path[path] = ArtifactRef(
                path=path, sha256=entry.get("sha256_after") or entry.get("sha256"), role="source"
            )

    for art in (node_report.get("artifacts") or []):
        if not isinstance(art, dict):
            continue
        name = art.get("path") or art.get("filename")
        if not name:
            continue
        path = normalize_artifact_path(name, work_dir)
        if path in by_path:
            # keep files_changed hash; upgrade role if classifier knows better
            if art.get("role") and by_path[path].role in ("unknown", "source"):
                by_path[path].role = art["role"]
            continue
        by_path[path] = ArtifactRef(
            path=path,
            sha256=sha256_of(work_dir / path) if compute_missing else None,
            role=art.get("role") or "unknown",
        )

    return list(by_path.values())
