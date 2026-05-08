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

from .app import build_app  # noqa: F401
