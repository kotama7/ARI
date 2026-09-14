"""Thin transform-facing adapter over the core EAR publication service."""

from __future__ import annotations

from ari.public.publish import PublishError, promote, publish


def publish_ear_record(
    checkpoint_dir: str,
    *,
    backend: str,
    visibility: str,
    dry_run: bool,
) -> dict:
    try:
        record = publish(
            checkpoint_dir,
            backend=backend,
            visibility=visibility,
            dry_run=dry_run,
        )
    except PublishError as exc:
        return {"error": str(exc), "kind": "PublishError"}
    return {
        "backend": record.backend,
        "ref": record.ref,
        "bundle_sha256": record.bundle_sha256,
        "visibility": record.visibility,
        "timestamp": record.timestamp,
        "dry_run": record.dry_run,
        "extra": record.extra,
    }


def promote_ear_record(checkpoint_dir: str, *, target: str) -> dict:
    try:
        record = promote(checkpoint_dir, target=target)
    except PublishError as exc:
        return {"error": str(exc), "kind": "PublishError"}
    return {
        "ref": record.ref,
        "visibility": record.visibility,
        "promoted_at": record.promoted_at,
        "promote_failed_at": record.promote_failed_at,
    }


__all__ = ["promote_ear_record", "publish_ear_record"]
