"""Centralised filesystem primitives for the ARI dashboard backend (subtask 023).

Single home for the traversal-validation guard, byte-size limits, file
classification sets, content-type table, and read/write/delete helpers that were
previously hand-rolled and duplicated across ``file_api.py`` and
``node_work_api.py`` (and, still inline, the file-serving branches of
``routes.py``). Extracting them here collapses the incompatible path-traversal
guard styles to one validator (:func:`safe_resolve`) and the scattered
magic-number size limits to named constants — **without** changing any
wire-visible endpoint, content-type, status code, header, or byte threshold
(dashboard API contract — ``010`` §4; frozen by ``020``).

Scope realised here (subtask 023 §3 / §8, safe subset): ``file_api.py`` and
``node_work_api.py`` delegate their guards, size limits, classification sets, and
read/write/delete to this module. Function names, signatures, response-dict
shapes, and the exact error sentinels ("path traversal denied",
"file too large (>5MB)"/"(>20MB)") are unchanged.

DEFERRED (REVIEW_REQUIRED — see ``ari/viz/services/__init__.py``): the inline
file-serving branches in ``routes.py`` (``/codefile``,
``/api/checkpoint/<id>/paper.<ext>``, ``.../file/raw``, ``/logo``, ``/static``,
``_serve_spa_index``, ``_write_access_log``) and ``api_tools`` upload/delete are
NOT migrated here, because (a) ``routes.py`` is pinned by frozen
source-inspection tests (``test_server.py`` / ``test_data_flow.py`` /
``test_page_requirements.py`` / ``test_settings_roundtrip.py`` /
``test_launch_config.py`` / ``test_default_provider.py`` /
``test_api_lineage_decisions.py`` / ``test_file_explorer.py`` concat scans) and
the route-literal contract snapshot
(``test_contract_snapshots.py::test_viz_route_literals_no_drift``); and (b) the
two content-type maps differ by a ``.gif`` member — folding them into one shared
table would change ``/file/raw``'s served content-type for ``.gif`` files, a wire
change, not a mechanical move. :func:`content_type_for` below is the canonical
table that that deferred migration will adopt.

Framework-free by design: stdlib only, synchronous reads (subtask 023 §17). No
new dependency.
"""
from __future__ import annotations

from pathlib import Path

# ── byte-size limits (named; mirror the historical literals exactly) ─────────
MAX_TEXT_READ = 5_000_000          # text read cap ("file too large (>5MB)")
MAX_BINARY_SERVE = 20_000_000      # paper binary serve cap ("(>20MB)")
MAX_TREE_TEXT = 10_000_000         # filetree "readable" text cutoff
MAX_POST_BODY = 10 * 1024 * 1024   # do_POST body cap (routes.py; adoption deferred)


# ── file classification (single source of truth) ─────────────────────────────
TEXT_EXTENSIONS = {
    ".tex", ".bib", ".sty", ".cls", ".bst", ".bbl",
    ".txt", ".md", ".csv",
}

BINARY_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".o", ".a", ".dll", ".dylib", ".exe",
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".ico",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".bin", ".dat", ".pkl", ".pickle", ".npy", ".npz", ".h5", ".hdf5",
    ".pt", ".pth", ".ckpt", ".safetensors",
    ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flac",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
}

SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".tox", ".mypy_cache",
             ".pytest_cache", ".ruff_cache", "dist", ".eggs", "*.egg-info"}


# ── content-type table (canonical; superset of the two routes.py maps) ───────
_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".eps": "application/postscript",
    ".tiff": "image/tiff",
    ".gif": "image/gif",
}


def content_type_for(ext: str, *, default: str) -> str:
    """Return the HTTP ``Content-Type`` for a file extension.

    Canonical table for the dashboard's binary file-serving endpoints. The
    *default* is caller-chosen so the two historical fallbacks are both
    reproducible byte-for-byte: ``text/plain; charset=utf-8`` for ``/codefile``
    and ``application/octet-stream`` for ``.../file/raw``. *ext* is matched
    case-insensitively and must carry the leading dot (e.g. ``".png"``).
    """
    return _CONTENT_TYPES.get(ext.lower(), default)


# ── traversal-safe path resolution (one validator, was several styles) ───────
def safe_resolve(base: Path, rel: str) -> tuple[Path | None, str | None]:
    """Resolve *rel* under *base*, rejecting path traversal.

    Returns ``(resolved_path, None)`` when the canonicalised target stays inside
    *base*, else ``(None, "path traversal denied")`` — the exact sentinel the
    file endpoints already return. Existence / size / binary checks stay with the
    caller so each endpoint's error strings remain byte-identical.
    """
    target = (base / rel).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return None, "path traversal denied"
    return target, None


# ── read / write / delete helpers ────────────────────────────────────────────
def read_text(path: Path) -> str:
    """UTF-8 text read with ``errors="replace"`` (matches the file endpoints)."""
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, content: str) -> None:
    """UTF-8 text write."""
    path.write_text(content, encoding="utf-8")


def write_bytes(path: Path, data: bytes) -> None:
    """Binary write."""
    path.write_bytes(data)


def delete(path: Path) -> None:
    """Remove *path* (``Path.unlink``)."""
    path.unlink()
