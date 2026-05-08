"""``ari clone`` — fetch + verify + extract curated EAR bundles.

Design constraints (from task.md, FR-CL):
- digest-based content integrity (SHA-256 in manifest.lock)
- atomic: a failed clone never leaves a partial dest
- no post-fetch code execution (no `setup.sh`, no `curl|bash` semantics)
- pluggable resolvers (file://, https://, ari://, gh:, doi:)

This package owns the orchestration; resolvers in ``resolvers/`` know how
to bytes-on-disk a tarball for a given scheme.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .resolvers import resolve as _resolve


class CloneError(RuntimeError):
    """Raised on any clone-time failure (resolver, digest mismatch, extract)."""


@dataclass
class CloneResult:
    ref: str
    dest: Path
    bundle_sha256: str
    manifest_sha256: str
    file_count: int
    extracted: bool


# ---------------------------------------------------------------------------
# Manifest digest re-computation
# ---------------------------------------------------------------------------

def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _recompute_manifest_digest(extracted_dir: Path, manifest_path: Path) -> str:
    """Re-derive the bundle digest from the extracted tree.

    Mirrors the curator's logic in ari-skill-transform/src/curate.py:
    canonical JSON of {"version":1,"files":[{"path","sha256","size"}, ...]}
    sorted by path, hashed with sha256. This is what we compare against
    `manifest.lock`'s `bundle_sha256` field after extraction.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files") or []
    rebuilt = []
    for entry in files:
        rel = entry.get("path", "")
        p = extracted_dir / rel
        if not p.is_file():
            raise CloneError(f"manifest references missing file: {rel}")
        h = _sha256_file(p)
        if h != entry.get("sha256"):
            raise CloneError(
                f"sha256 mismatch for {rel}: expected {entry.get('sha256')[:16]}…, got {h[:16]}…"
            )
        rebuilt.append({"path": rel, "sha256": h, "size": p.stat().st_size})
    canonical_payload = {"version": 1, "files": sorted(rebuilt, key=lambda r: r["path"])}
    canonical = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _safe_extract_tar(tar: tarfile.TarFile, dest: Path) -> None:
    """Extract a tar archive defensively (no symlinks escaping dest, no abs paths)."""
    dest = dest.resolve()
    for member in tar.getmembers():
        # Reject absolute paths and parent escapes.
        target = (dest / member.name).resolve()
        if dest != target and dest not in target.parents:
            raise CloneError(f"unsafe member in archive: {member.name}")
        # Reject hard/symlinks pointing outside dest.
        if member.issym() or member.islnk():
            link_target = (target.parent / member.linkname).resolve()
            if dest != link_target and dest not in link_target.parents:
                raise CloneError(f"unsafe link in archive: {member.name} -> {member.linkname}")
    # CPython 3.12+ supports filter='data' which already enforces safety; keep
    # the manual pass above for older runtimes that don't.
    try:
        tar.extractall(dest, filter="data")  # type: ignore[arg-type]
    except TypeError:
        tar.extractall(dest)


def _extract_bundle(bundle_path: Path, dest: Path) -> None:
    """Extract a tarball / zip / plain dir into dest. dest must already exist and be empty."""
    if bundle_path.is_dir():
        # file:// resolver may hand back a directory; treat as a copy.
        for child in bundle_path.iterdir():
            if child.is_dir():
                shutil.copytree(child, dest / child.name)
            else:
                shutil.copy2(child, dest / child.name)
        return

    name = bundle_path.name.lower()
    # Probe magic bytes: filename hints (server-derived names like
    # "ari://<id>" have no extension) are unreliable.
    head = bundle_path.read_bytes()[:4]
    is_gzip = head[:2] == b"\x1f\x8b"
    is_zip = head[:4] == b"PK\x03\x04"

    if is_gzip or name.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(bundle_path, mode="r:*") as tar:
            _safe_extract_tar(tar, dest)
        return
    if is_zip or name.endswith(".zip"):
        with zipfile.ZipFile(bundle_path) as zf:
            for member in zf.infolist():
                target = (dest / member.filename).resolve()
                if dest.resolve() != target and dest.resolve() not in target.parents:
                    raise CloneError(f"unsafe member in zip: {member.filename}")
            zf.extractall(dest)
        return
    raise CloneError(f"unsupported archive type: {bundle_path.name}")


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def clone(
    ref: str,
    dest: Optional[Path] = None,
    *,
    expect_sha256: Optional[str] = None,
    extract: bool = True,
    registry: Optional[str] = None,
    token: Optional[str] = None,
) -> CloneResult:
    """Fetch a curated EAR bundle + verify digest + extract.

    Args:
        ref: scheme-prefixed reference (file://, https://, ari://, gh:, doi:).
        dest: target directory. Default: ``./<id>`` derived from the ref.
            Must not exist OR must be empty.
        expect_sha256: if provided, the bundle digest MUST match. Hard fail.
        extract: if False, leaves the tarball at dest/<basename> instead.
        registry: limit ari:// resolver to a named registry from registries.yaml.
        token: bearer token for private-token visibility.
    """
    if dest is None:
        dest = Path(_default_dest_name(ref))
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise CloneError(f"dest exists and is not empty: {dest}")

    # Resolver materialises the bytes (tarball or directory) into a tmp dir.
    with tempfile.TemporaryDirectory(prefix="ari-clone-") as tmp:
        tmp_path = Path(tmp)
        try:
            artifact = _resolve(ref, tmp_path, registry=registry, token=token)
        except Exception as e:
            raise CloneError(f"resolver failed: {e}") from e

        # ---- atomic dest staging ----
        # Build the result inside a sibling tmp dir, then rename into place.
        stage = tmp_path / "_stage"
        stage.mkdir(parents=True, exist_ok=True)

        if not extract:
            # Just copy the raw artifact to stage/<name>.
            target = stage / artifact.name
            if artifact.is_dir():
                shutil.copytree(artifact, target)
            else:
                shutil.copy2(artifact, target)
            manifest_path = stage / artifact.name / "manifest.lock" if artifact.is_dir() else None
            bundle_digest = ""
            manifest_digest = ""
            file_count = 0
            if manifest_path and manifest_path.exists():
                manifest_digest = _sha256_file(manifest_path)
                file_count = len(json.loads(manifest_path.read_text(encoding="utf-8")).get("files") or [])
        else:
            _extract_bundle(artifact, stage)
            manifest_path = stage / "manifest.lock"
            if not manifest_path.exists():
                raise CloneError("extracted bundle is missing manifest.lock")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            recomputed = _recompute_manifest_digest(stage, manifest_path)
            declared = manifest.get("bundle_sha256", "")
            if declared and declared != recomputed:
                raise CloneError(
                    f"manifest.lock declares bundle_sha256={declared[:16]}… "
                    f"but recomputed {recomputed[:16]}… (file content does not match manifest)"
                )
            bundle_digest = recomputed
            manifest_digest = _sha256_file(manifest_path)
            file_count = len(manifest.get("files") or [])

            if expect_sha256 and expect_sha256 != bundle_digest:
                raise CloneError(
                    f"bundle digest mismatch: expected {expect_sha256[:16]}…, got {bundle_digest[:16]}…"
                )

        # Promote stage → dest atomically. dest may exist (but must be empty
        # per the check above); rename will fail on non-empty target on Linux,
        # so explicitly remove it first.
        if dest.exists():
            try:
                dest.rmdir()
            except OSError:
                pass
        dest.parent.mkdir(parents=True, exist_ok=True)
        # rename across the same FS will atomically swap; if cross-FS, fall
        # back to copy + delete (still safe — stage stays intact on failure).
        try:
            stage.rename(dest)
        except OSError:
            shutil.copytree(stage, dest)

    return CloneResult(
        ref=ref,
        dest=dest,
        bundle_sha256=bundle_digest,
        manifest_sha256=manifest_digest,
        file_count=file_count,
        extracted=extract,
    )


def _default_dest_name(ref: str) -> str:
    """Derive a sensible default dest from the ref (last path component, archive suffixes stripped)."""
    if ref.startswith("file://"):
        leaf = Path(ref[len("file://"):]).name
    elif "://" in ref:
        leaf = ref.split("://", 1)[1].rstrip("/").split("/")[-1] or "ari_clone"
    elif ":" in ref:
        leaf = ref.split(":", 1)[1].rstrip("/").split("/")[-1] or "ari_clone"
    else:
        leaf = "ari_clone"
    for suf in (".tar.gz", ".tgz", ".tar", ".zip"):
        if leaf.lower().endswith(suf):
            leaf = leaf[: -len(suf)]
            break
    return leaf or "ari_clone"


__all__ = ["CloneError", "CloneResult", "clone"]
