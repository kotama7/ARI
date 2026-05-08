"""Filesystem storage backend for the ari-registry.

Layout:
    <data_dir>/artifacts/<id>/bundle.tar.gz
    <data_dir>/artifacts/<id>/manifest.lock
    <data_dir>/artifacts/<id>/meta.json   ({"visibility":..., "owner":..., "created_at":...})

The artifact id is content-addressed: ``sha256(bundle.tar.gz)[:16]``.
This trades some collision risk for shorter URLs (FR-RG5; O-7 default 16).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_VALID_VISIBILITY = {"staged", "unlisted", "public", "private-token"}


class StorageError(RuntimeError):
    pass


class FilesystemStorage:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).resolve()
        self.artifacts_dir = self.data_dir / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    # ── id derivation ──────────────────────────────────────────────
    @staticmethod
    def derive_id(bundle_bytes: bytes) -> str:
        return hashlib.sha256(bundle_bytes).hexdigest()[:16]

    def _artifact_dir(self, artifact_id: str) -> Path:
        return self.artifacts_dir / artifact_id

    # ── CRUD ───────────────────────────────────────────────────────
    def put(
        self,
        bundle_bytes: bytes,
        manifest_bytes: bytes,
        *,
        visibility: str,
        owner: str,
    ) -> dict:
        if visibility not in _VALID_VISIBILITY:
            raise StorageError(f"invalid visibility: {visibility}")
        artifact_id = self.derive_id(bundle_bytes)
        adir = self._artifact_dir(artifact_id)
        if adir.exists():
            # Idempotent re-upload: if the existing meta says different owner
            # or visibility, refuse — this would otherwise let a non-owner
            # overwrite a record.
            existing = json.loads((adir / "meta.json").read_text(encoding="utf-8"))
            if existing.get("owner") and existing["owner"] != owner:
                raise StorageError("artifact id already exists under a different owner")
            return {
                "id": artifact_id,
                "visibility": existing.get("visibility", visibility),
                "owner": existing.get("owner", owner),
                "created_at": existing.get("created_at"),
                "duplicate": True,
            }
        adir.mkdir(parents=True, exist_ok=True)
        (adir / "bundle.tar.gz").write_bytes(bundle_bytes)
        (adir / "manifest.lock").write_bytes(manifest_bytes)
        meta = {
            "id": artifact_id,
            "visibility": visibility,
            "owner": owner,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sha256": hashlib.sha256(bundle_bytes).hexdigest(),
            "length": len(bundle_bytes),
        }
        (adir / "meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return meta

    def get_meta(self, artifact_id: str) -> Optional[dict]:
        meta_path = self._artifact_dir(artifact_id) / "meta.json"
        if not meta_path.exists():
            return None
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def get_bundle_path(self, artifact_id: str) -> Optional[Path]:
        p = self._artifact_dir(artifact_id) / "bundle.tar.gz"
        return p if p.exists() else None

    def get_manifest_bytes(self, artifact_id: str) -> Optional[bytes]:
        p = self._artifact_dir(artifact_id) / "manifest.lock"
        return p.read_bytes() if p.exists() else None

    def set_visibility(self, artifact_id: str, target: str) -> dict:
        if target not in _VALID_VISIBILITY:
            raise StorageError(f"invalid target visibility: {target}")
        adir = self._artifact_dir(artifact_id)
        meta_path = adir / "meta.json"
        if not meta_path.exists():
            raise StorageError("artifact not found")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        # FR-RG6: visibility flow is staged → unlisted | public.
        # Demoting (public → staged) is forbidden.
        order = {"staged": 0, "unlisted": 1, "public": 2, "private-token": 1}
        cur = order.get(meta.get("visibility", "staged"), 0)
        nxt = order.get(target, 0)
        if nxt < cur:
            raise StorageError(
                f"visibility downgrade not allowed: {meta.get('visibility')} → {target}"
            )
        meta["visibility"] = target
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        return meta

    def delete(self, artifact_id: str, owner: str) -> bool:
        adir = self._artifact_dir(artifact_id)
        if not adir.exists():
            return False
        meta_path = adir / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("owner") and meta["owner"] != owner:
                raise StorageError("not owner")
        shutil.rmtree(adir)
        return True

    def list_public(self) -> list[dict]:
        out: list[dict] = []
        for child in self.artifacts_dir.iterdir():
            meta_path = child / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if meta.get("visibility") == "public":
                out.append({"id": meta["id"], "sha256": meta.get("sha256"), "length": meta.get("length")})
        return out
