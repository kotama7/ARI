"""ari-registry: minimal HTTP registry for curated EAR bundles.

Endpoints (FR-RG2):
    POST   /artifact                upload tarball + manifest (token auth)
    GET    /artifact/<id>           download tarball
    HEAD   /artifact/<id>           metadata only (sha256, visibility, length)
    GET    /artifact/<id>/manifest.lock
    POST   /artifact/<id>/promote   change visibility (token auth)
    DELETE /artifact/<id>           remove (owner-only)
    GET    /healthz, /version

Storage layout (FR-RG3):
    <data_dir>/artifacts/<id>/bundle.tar.gz
    <data_dir>/artifacts/<id>/manifest.lock
    <data_dir>/artifacts/<id>/meta.json
    <data_dir>/tokens.db   (sqlite, hashed bearer tokens)
"""

import os
from pathlib import Path


def resolve_data_dir(explicit: Path | str | None = None) -> Path:
    """Resolve the registry data dir (Phase DR2 §6 helper).

    Priority:
        1. ``explicit`` (function arg / CLI flag)
        2. ``ARI_REGISTRY_DATA`` env var
        3. ``~/.ari/registry-data`` — DEPRECATED since v0.5.0,
           emits a ``DeprecationWarning`` until v1.0 removes it.

    Centralising the lookup eliminates the duplicated chain in
    ``app.py`` and ``cli.py``.
    """
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("ARI_REGISTRY_DATA", "").strip()
    if env:
        return Path(env)
    legacy = Path.home() / ".ari" / "registry-data"
    from ari._deprecation import warn_deprecated_path
    warn_deprecated_path(
        legacy,
        replacement="ARI_REGISTRY_DATA environment variable",
    )
    return legacy


from .app import build_app  # noqa: F401,E402
