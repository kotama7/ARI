"""``ari ear publish`` — package a curated EAR and ship it to a backend.

Backends live in ``backends/``: ``local_tarball`` (zero deps),
``ari_registry`` (FastAPI client), ``zenodo`` and ``gh``.

The publish flow is:
    curated_dir = {checkpoint}/ear_published/  (curator output)
    + manifest.lock with bundle_sha256
       ↓
    tarball = bundle.tar.gz (deterministic content)
       ↓
    backend.publish(tarball, manifest, metadata) → {ref, visibility, ...}
       ↓
    publish_record.json written to {checkpoint}/

The registered ref + bundle_sha256 are then pushed into the paper's
Code Availability section by ``inject_code_availability``.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ari._factory import BaseRegistry


class PublishError(RuntimeError):
    pass


@dataclass
class PublishRecord:
    backend: str
    ref: str
    bundle_sha256: str
    visibility: str
    timestamp: str
    dry_run: bool
    extra: dict
    promoted_at: Optional[str] = None
    promote_failed_at: Optional[str] = None


def _read_manifest(curated_dir: Path) -> dict:
    p = curated_dir / "manifest.lock"
    if not p.exists():
        raise PublishError(f"manifest.lock not found in {curated_dir} — run `ari ear curate` first")
    return json.loads(p.read_text(encoding="utf-8"))


def _build_tarball(curated_dir: Path, dest_path: Path) -> str:
    """Tar curated_dir into dest_path. Returns sha256 of the tarball.

    Files are added in sorted order with a normalised mtime so the tarball
    is reproducible bit-for-bit across runs (digest stability is enforced
    by manifest.lock anyway, so this is a defence-in-depth nicety).
    """
    members = sorted(p for p in curated_dir.rglob("*") if p.is_file())
    with tarfile.open(dest_path, mode="w:gz") as tar:
        for p in members:
            arcname = p.relative_to(curated_dir).as_posix()
            tarinfo = tar.gettarinfo(str(p), arcname=arcname)
            tarinfo.mtime = 0
            tarinfo.uid = 0
            tarinfo.gid = 0
            tarinfo.uname = ""
            tarinfo.gname = ""
            with p.open("rb") as f:
                tar.addfile(tarinfo, f)
    h = hashlib.sha256()
    with dest_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def publish(
    checkpoint: Path | str,
    *,
    backend: str = "ari-registry",
    visibility: str = "staged",
    dry_run: bool = False,
    metadata: Optional[dict] = None,
) -> PublishRecord:
    """Publish ``{checkpoint}/ear_published/`` to ``backend``.

    Always starts at ``visibility=staged`` regardless of the argument; the
    requested visibility is honoured by ``promote()`` later. (FR-P5)

    ``ARI_PUBLISH_DRYRUN=true`` env var forces ``dry_run=True`` (CI safety).
    """
    if os.environ.get("ARI_PUBLISH_DRYRUN", "").lower() in ("1", "true", "yes"):
        dry_run = True

    ckpt = Path(checkpoint).resolve()
    curated = ckpt / "ear_published"
    if not curated.is_dir():
        raise PublishError(f"ear_published/ not found — run `ari ear curate` first")

    manifest = _read_manifest(curated)
    bundle_sha256 = manifest.get("bundle_sha256", "")
    if not bundle_sha256:
        raise PublishError("manifest.lock has no bundle_sha256")

    metadata = dict(metadata or {})
    metadata.setdefault("checkpoint_id", ckpt.name)
    metadata.setdefault("license", (manifest.get("publish") or {}).get("license"))

    backend_impl = _load_backend(backend)
    with tempfile.TemporaryDirectory(prefix="ari-publish-") as tmp:
        tar_path = Path(tmp) / "bundle.tar.gz"
        tarball_sha = _build_tarball(curated, tar_path)

        result = backend_impl.publish(
            tar_path=tar_path,
            manifest=manifest,
            metadata=metadata,
            visibility="staged",  # always staged on first publish (FR-P5)
            dry_run=dry_run,
            tarball_sha256=tarball_sha,
        )

    record = PublishRecord(
        backend=backend,
        ref=result.get("ref", ""),
        bundle_sha256=bundle_sha256,
        visibility="staged",
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        dry_run=dry_run,
        extra={k: v for k, v in result.items() if k != "ref"},
    )

    record_path = ckpt / "publish_record.json"
    record_path.write_text(
        json.dumps(asdict(record), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return record


def promote(
    checkpoint: Path | str,
    *,
    target: str = "public",
) -> PublishRecord:
    """Promote a previously-staged artifact to ``target`` visibility.

    Requires ``publish_record.json`` to exist (i.e. ``publish()`` ran first).
    Backend-specific semantics are dispatched to the same module that
    handled the original publish.
    """
    ckpt = Path(checkpoint).resolve()
    record_path = ckpt / "publish_record.json"
    if not record_path.exists():
        raise PublishError(f"publish_record.json not found — run `ari ear publish` first")
    data = json.loads(record_path.read_text(encoding="utf-8"))
    backend_name = data.get("backend", "ari-registry")
    backend_impl = _load_backend(backend_name)

    try:
        out = backend_impl.promote(
            ref=data.get("ref", ""),
            target=target,
            extra=data.get("extra") or {},
            dry_run=bool(data.get("dry_run", False)),
        )
        data["visibility"] = out.get("visibility", target)
        data["promoted_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data.setdefault("extra", {}).update(
            {k: v for k, v in out.items() if k not in ("visibility",)}
        )
    except Exception as e:
        data["promote_failed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data.setdefault("extra", {})["promote_error"] = f"{type(e).__name__}: {e}"
        record_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        raise PublishError(f"promote failed: {e}") from e

    record_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return PublishRecord(
        backend=backend_name,
        ref=data.get("ref", ""),
        bundle_sha256=data.get("bundle_sha256", ""),
        visibility=data.get("visibility", target),
        timestamp=data.get("timestamp", ""),
        dry_run=bool(data.get("dry_run", False)),
        extra=data.get("extra", {}),
        promoted_at=data.get("promoted_at"),
        promote_failed_at=data.get("promote_failed_at"),
    )


# ── backend registry (subtask 014) ────────────────────────────────────────
# The four publish backends are unified behind ``ari._factory.BaseRegistry``.
# They stay **lazily** imported (each loader imports its module only when
# resolved) so optional-dependency backends (``zenodo`` / ``gh``) still degrade
# to ``PublishError`` on ``ImportError``. The four backend modules under
# ``backends/`` are referenced ONLY by these string keys — they are live-by-string
# and must never be treated as dead code (subtask 053/057 handoff).
#
# ``BaseRegistry.keys()`` is the canonical key list; a parity test
# (``tests/test_factory_registry.py``) asserts it is a subset of the
# ``publish.schema.json`` backend-name enum and documents the schema-only
# ``s3`` gap (enum lists ``s3`` but no backend module exists — do NOT add one).


def _load_ari_registry_backend():
    from .backends import ari_registry as backend
    return backend


def _load_local_tarball_backend():
    from .backends import local_tarball as backend
    return backend


def _load_zenodo_backend():
    try:
        from .backends import zenodo as backend
    except ImportError as e:
        raise PublishError("zenodo backend not implemented") from e
    return backend


def _load_gh_backend():
    try:
        from .backends import gh as backend
    except ImportError as e:
        raise PublishError("gh backend not implemented") from e
    return backend


_BACKEND_REGISTRY: "BaseRegistry" = BaseRegistry("publish backend", error_cls=PublishError)
_BACKEND_REGISTRY.register_lazy("ari-registry", _load_ari_registry_backend)
_BACKEND_REGISTRY.register_lazy("local-tarball", _load_local_tarball_backend)
_BACKEND_REGISTRY.register_lazy("zenodo", _load_zenodo_backend)
_BACKEND_REGISTRY.register_lazy("gh", _load_gh_backend)


def _load_backend(name: str):
    """Resolve a publish backend module by string key.

    Thin back-compat wrapper delegating to ``_BACKEND_REGISTRY.resolve`` so the
    signature and ``PublishError``-on-unknown-key behaviour are unchanged.
    """
    return _BACKEND_REGISTRY.resolve(name)


__all__ = ["PublishError", "PublishRecord", "publish", "promote"]
