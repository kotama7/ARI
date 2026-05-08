"""ari-registry backend — POST the bundle to a running ari-registry server.

The HTTP client uses ``urllib`` to keep this backend free of an httpx hard
dependency. (The Zenodo backend uses the same approach.)

Registry config is loaded from ~/.ari/registries.yaml or
{checkpoint}/settings.json's ``registries`` block. The ``default`` registry
is used unless ``metadata['registry']`` overrides it.

When ``ARI_PUBLISH_DRYRUN=true`` the function fabricates a deterministic
``ari://<sha256[:16]>`` ref without making any network calls.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


def _resolve_registries() -> list[dict]:
    """Read registries.yaml or env-provided config. Returns a list of
    dicts with at least ``name``, ``url``, optional ``token``.

    Phase DR2 (DEPRECATION_REMOVAL.md tier B): the legacy
    ``~/.ari/registries.yaml`` fallback emits a DeprecationWarning the
    first time it is honoured.  v1.0 will remove it; users should
    set ``ARI_REGISTRIES_FILE`` or place the file under their
    checkpoint.
    """
    cfg_paths: list[Path | None] = [
        Path(os.environ["ARI_REGISTRIES_FILE"]) if os.environ.get("ARI_REGISTRIES_FILE") else None,
    ]
    legacy = Path.home() / ".ari" / "registries.yaml"
    if legacy.exists():
        from ari._deprecation import warn_deprecated_path
        warn_deprecated_path(
            legacy,
            replacement="ARI_REGISTRIES_FILE env or {checkpoint}/.ari/registries.yaml",
        )
        cfg_paths.append(legacy)
    for p in cfg_paths:
        if p and p.exists():
            try:
                import yaml  # type: ignore
                data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                regs = data.get("registries") or []
                if isinstance(regs, list):
                    return regs
            except Exception:
                continue
    # Fallback: env-only single registry.
    url = os.environ.get("ARI_REGISTRY_URL")
    if url:
        return [{
            "name": "default",
            "url": url,
            "token": os.environ.get("ARI_REGISTRY_TOKEN", ""),
        }]
    return []


def _select_registry(name: Optional[str]) -> Optional[dict]:
    regs = _resolve_registries()
    if not regs:
        return None
    if name:
        for r in regs:
            if r.get("name") == name:
                return r
        return None
    return regs[0]


def _expand_token(token: str) -> str:
    """Allow either env-var-name or literal token in the config."""
    if not token:
        return ""
    if token.startswith("$"):
        return os.environ.get(token[1:], "") or ""
    if token.startswith("${") and token.endswith("}"):
        return os.environ.get(token[2:-1], "") or ""
    return token


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
        # Deterministic dryrun ref — first 16 hex of bundle digest.
        bundle_id = manifest.get("bundle_sha256", "")[:16] or "deadbeefdeadbeef"
        return {
            "ref": f"ari://{bundle_id}",
            "tarball_sha256": tarball_sha256,
            "dryrun": True,
            "registry": "(dryrun)",
        }

    registry_name = metadata.get("registry") or os.environ.get("ARI_REGISTRY_NAME")
    reg = _select_registry(registry_name)
    if not reg:
        raise RuntimeError(
            "no ari-registry configured. Set ARI_REGISTRY_URL, "
            "or write registries.yaml in your checkpoint or working "
            "directory (see docs/registry.md for format). "
            "Note: ~/.ari/ paths are deprecated and will be removed in v1.0."
        )

    base_url = str(reg.get("url", "")).rstrip("/")
    token = _expand_token(str(reg.get("token", "")))
    if not base_url:
        raise RuntimeError("ari-registry config missing 'url'")

    boundary = "----ari-publish-boundary-" + tarball_sha256[:16]
    body = _build_multipart(boundary, tar_path, manifest, visibility, metadata)
    req = urllib.request.Request(
        f"{base_url}/artifact",
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {token}",
            "User-Agent": "ari-publish/0.7.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        body_str = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"registry POST /artifact failed: {e.code} {body_str[:300]}") from e
    return {
        "ref": payload.get("ref") or f"ari://{payload.get('id', '')}",
        "tarball_sha256": tarball_sha256,
        "registry": reg.get("name"),
        "id": payload.get("id"),
        "visibility": payload.get("visibility", "staged"),
    }


def _build_multipart(boundary: str, tar_path: Path, manifest: dict, visibility: str, metadata: dict) -> bytes:
    parts: list[bytes] = []

    def _field(name: str, value: str):
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        parts.append(value.encode("utf-8"))
        parts.append(b"\r\n")

    _field("visibility", visibility)
    _field("manifest", json.dumps(manifest, ensure_ascii=False))
    _field("metadata", json.dumps(metadata, ensure_ascii=False))

    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(b'Content-Disposition: form-data; name="bundle"; filename="bundle.tar.gz"\r\n')
    parts.append(b"Content-Type: application/gzip\r\n\r\n")
    parts.append(tar_path.read_bytes())
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts)


def promote(
    *, ref: str, target: str, extra: dict, dry_run: bool,
) -> dict:
    if dry_run:
        return {"visibility": target, "dryrun": True}
    artifact_id = ref.split("ari://", 1)[-1]
    if "/" in artifact_id:  # ari://<registry-name>/<id>
        artifact_id = artifact_id.split("/", 1)[-1]

    reg = _select_registry(extra.get("registry") or os.environ.get("ARI_REGISTRY_NAME"))
    if not reg:
        raise RuntimeError("no ari-registry configured for promote")
    base_url = str(reg.get("url", "")).rstrip("/")
    token = _expand_token(str(reg.get("token", "")))

    req = urllib.request.Request(
        f"{base_url}/artifact/{artifact_id}/promote",
        data=json.dumps({"target": target}).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "ari-promote/0.7.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        body_str = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"registry POST /promote failed: {e.code} {body_str[:300]}") from e
    return {"visibility": payload.get("visibility", target), "id": artifact_id}
