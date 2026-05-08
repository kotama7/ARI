"""Scheme dispatch for ``ari clone``.

Each resolver returns a Path to a *materialised* artifact in the workdir
provided by the caller. The artifact is either a tarball/zip (then
extracted by the orchestrator in ari.clone) or a directory (copied
verbatim).

Adding a resolver:
    - implement ``resolve(ref: str, workdir: Path, **kwargs) -> Path``
    - register it via the ``_RESOLVERS`` table below

file:// and https://. ari:// is added; gh: and doi:
are added.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from .file import resolve as _resolve_file
from .https import resolve as _resolve_https


_RESOLVERS: dict[str, Callable[..., Path]] = {
    "file://": _resolve_file,
    "https://": _resolve_https,
    "http://": _resolve_https,
}


def resolve(
    ref: str,
    workdir: Path,
    *,
    registry: Optional[str] = None,
    token: Optional[str] = None,
) -> Path:
    """Look up the resolver for ``ref``'s scheme and invoke it."""
    for prefix, fn in _RESOLVERS.items():
        if ref.startswith(prefix):
            return fn(ref, workdir, registry=registry, token=token)
    if ref.startswith("ari://"):
        try:
            from .ari import resolve as _resolve_ari
        except ImportError as e:
            raise NotImplementedError(
                "ari:// resolver is added (ari-registry support)"
            ) from e
        return _resolve_ari(ref, workdir, registry=registry, token=token)
    if ref.startswith("gh:"):
        try:
            from .gh import resolve as _resolve_gh
        except ImportError as e:
            raise NotImplementedError("gh: resolver is added") from e
        return _resolve_gh(ref, workdir, token=token)
    if ref.startswith("doi:"):
        try:
            from .doi import resolve as _resolve_doi
        except ImportError as e:
            raise NotImplementedError("doi: resolver is added") from e
        return _resolve_doi(ref, workdir, token=token)
    raise ValueError(f"unknown ref scheme: {ref!r}")


__all__ = ["resolve"]
