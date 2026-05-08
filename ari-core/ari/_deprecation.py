"""Deprecation warning helpers for v0.5→v1.0 migration paths.

Centralises emission of `DeprecationWarning` for legacy ``~/.ari/`` paths,
deprecated environment-variable aliases, and deprecated config/CLI fields.
Used by Tier-B fallbacks in publish/clone/registry/memory subsystems
(see DEPRECATION_REMOVAL.md).
"""

from __future__ import annotations

import warnings
from pathlib import Path

_DEFAULT_REMOVAL = "v1.0"


def warn_deprecated_path(
    path: Path | str,
    replacement: str,
    removal_version: str = _DEFAULT_REMOVAL,
) -> None:
    """Emit a DeprecationWarning when an `~/.ari/`-style path is touched.

    Args:
        path: The deprecated path being accessed.
        replacement: Human-readable description of the new location.
        removal_version: Version when this fallback will be removed.
    """
    warnings.warn(
        f"Path {path} is deprecated and will be removed in {removal_version}. "
        f"Use {replacement} instead.",
        DeprecationWarning,
        stacklevel=3,
    )


def warn_deprecated_env(
    name: str,
    replacement: str,
    removal_version: str = _DEFAULT_REMOVAL,
) -> None:
    """Emit a DeprecationWarning for a deprecated environment variable."""
    warnings.warn(
        f"Environment variable {name} is deprecated and will be removed in "
        f"{removal_version}. Use {replacement} instead.",
        DeprecationWarning,
        stacklevel=3,
    )


def warn_deprecated_field(
    model: str,
    field: str,
    replacement: str,
    removal_version: str = _DEFAULT_REMOVAL,
) -> None:
    """Emit a DeprecationWarning for a deprecated config/CLI field."""
    warnings.warn(
        f"Field {model}.{field} is deprecated and will be removed in "
        f"{removal_version}. Use {replacement} instead.",
        DeprecationWarning,
        stacklevel=3,
    )
