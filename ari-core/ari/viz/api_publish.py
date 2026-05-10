"""GUI REST endpoints for publish.

5 endpoints (FR-G5):
    GET  /api/publish/settings
    POST /api/publish/settings
    GET  /api/publish/<run_id>/preview
    POST /api/publish/<run_id>
    POST /api/publish/<run_id>/promote
    GET  /api/publish/<run_id>/record

Settings location:
    1. $ARI_PUBLISH_SETTINGS (preferred)
    2. ~/.ari/publish.yaml (DEPRECATED since v0.5.0, removed in v1.0)

Per-checkpoint overrides live in ``{checkpoint}/settings.json`` under
the 'publish' key.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .api_state import _resolve_checkpoint_dir


def _resolve_settings_path() -> Path:
    """Locate publish.yaml, deferring legacy-path detection to call time.

    Phase DR2 (DEPRECATION_REMOVAL.md tier B): the legacy
    ``~/.ari/publish.yaml`` path emits a DeprecationWarning the first
    time it is consulted; v1.0 will drop it in favour of
    ``$ARI_PUBLISH_SETTINGS`` or ``{checkpoint}/settings.json``'s
    publish section.

    Resolved on every call (rather than at module import) so test
    fixtures can monkeypatch HOME / env without re-importing.
    """
    env = os.environ.get("ARI_PUBLISH_SETTINGS", "").strip()
    if env:
        return Path(env)
    legacy = Path.home() / ".ari" / "publish.yaml"
    if legacy.exists():
        from ari._deprecation import warn_deprecated_path
        warn_deprecated_path(
            legacy,
            replacement="ARI_PUBLISH_SETTINGS env or {checkpoint}/settings.json publish section",
        )
    return legacy


def _load_settings() -> dict:
    settings_path = _resolve_settings_path()
    if not settings_path.exists():
        return {
            "default_backend": "ari-registry",
            "auto_promote": False,
            "registries": [],
            "zenodo_sandbox": True,
            "gh_user": "",
        }
    try:
        import yaml  # type: ignore
        return yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        return {"error": f"failed to load {settings_path}: {e}"}


def _save_settings(data: dict) -> dict:
    settings_path = _resolve_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml  # type: ignore
        settings_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return {"ok": True, "path": str(settings_path)}
    except Exception as e:
        return {"error": f"failed to write settings: {e}"}


def _api_publish_settings_get() -> dict:
    return _load_settings()


def _api_publish_settings_set(body: bytes) -> dict:
    try:
        payload = json.loads(body or b"{}")
    except Exception:
        return {"error": "invalid JSON body"}
    return _save_settings(payload)


def _api_publish_preview(run_id: str) -> dict:
    """Return what `ari ear publish` would upload, without uploading."""
    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return {"error": "checkpoint not found"}
    pub_dir = d / "ear_published"
    manifest = pub_dir / "manifest.lock"
    if not manifest.exists():
        return {"error": "ear_published/ not found — run curate first", "needs_curate": True}
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"manifest parse failed: {e}"}
    return {
        "run_id": run_id,
        "ear_published_dir": str(pub_dir),
        "bundle_sha256": data.get("bundle_sha256"),
        "files": [f.get("path") for f in data.get("files") or []],
        "file_count": len(data.get("files") or []),
        "visibility": (data.get("publish") or {}).get("visibility"),
        "license": (data.get("publish") or {}).get("license"),
        "publish": data.get("publish") or {},
    }


def _api_publish_run(run_id: str, body: bytes) -> dict:
    """Wrap ari.publish.publish for the GUI Publish button."""
    try:
        payload = json.loads(body or b"{}")
    except Exception:
        return {"error": "invalid JSON body"}
    backend = payload.get("backend") or "ari-registry"
    visibility = payload.get("visibility") or "staged"
    dry_run = bool(payload.get("dry_run", False))
    metadata = payload.get("metadata") or {}

    if not bool(payload.get("consent", False)) and not dry_run:
        # FR-G3 requires explicit user opt-in before each real publish.
        return {"error": "consent toggle is required to perform a real publish (or use dry_run=true)", "_status": 400}

    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return {"error": "checkpoint not found"}

    try:
        from ari.publish import publish, PublishError
    except Exception as e:
        return {"error": f"ari.publish not importable: {e}"}
    try:
        rec = publish(d, backend=backend, visibility=visibility, dry_run=dry_run, metadata=metadata)
    except PublishError as e:
        return {"error": str(e), "kind": "PublishError"}
    return {
        "backend": rec.backend,
        "ref": rec.ref,
        "bundle_sha256": rec.bundle_sha256,
        "visibility": rec.visibility,
        "dry_run": rec.dry_run,
        "extra": rec.extra,
        "timestamp": rec.timestamp,
    }


def _api_publish_promote(run_id: str, body: bytes) -> dict:
    try:
        payload = json.loads(body or b"{}")
    except Exception:
        payload = {}
    target = payload.get("target") or "public"
    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return {"error": "checkpoint not found"}
    try:
        from ari.publish import promote, PublishError
    except Exception as e:
        return {"error": f"ari.publish not importable: {e}"}
    try:
        rec = promote(d, target=target)
    except PublishError as e:
        return {"error": str(e), "kind": "PublishError"}
    return {
        "ref": rec.ref,
        "visibility": rec.visibility,
        "promoted_at": rec.promoted_at,
    }


def _api_publish_record(run_id: str) -> dict:
    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return {"error": "checkpoint not found"}
    record_path = d / "publish_record.json"
    if not record_path.exists():
        return {"published": False}
    try:
        data = json.loads(record_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"publish_record.json parse failed: {e}"}
    return {"published": True, **data}
