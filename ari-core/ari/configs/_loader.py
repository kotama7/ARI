"""ConfigLoader — Phase PC0 (PROMPTS_AND_CONFIG.md §2-3 / §2-4).

Provides a tiny abstraction over "load a YAML/JSON config blob from
the bundled ``ari/configs/`` directory".  The ``ConfigLoader`` class
stays as a Protocol so future loaders (remote, in-memory for tests)
can plug in without touching call-sites.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


def package_configs_root() -> Path:
    """Return the bundled ``ari-core/ari/configs/`` directory."""
    return Path(__file__).resolve().parent


class ConfigLoader(Protocol):
    """Loads non-Pydantic config values (lookup tables, defaults)."""

    def load(self, key: str) -> Any:
        """Load a YAML/JSON config blob (e.g. "model_prices")."""
        ...


class FilesystemConfigLoader:
    """Default :class:`ConfigLoader` that reads from a directory tree.

    The default base is the bundled ``ari/configs/`` so callers can
    instantiate without arguments and get the shipped defaults.  Tests
    can pass their own *base* to swap fixtures in.
    """

    def __init__(self, base: Path | None = None) -> None:
        self._base = base or package_configs_root()

    def load(self, key: str) -> Any:
        """Resolve *key* to a YAML or JSON file under the base dir.

        Search order: ``{base}/{key}.yaml`` → ``{base}/{key}.yml`` →
        ``{base}/{key}.json``.  Raises :class:`FileNotFoundError`
        otherwise so missing config surfaces loudly rather than as a
        silent ``None``.
        """
        for ext in (".yaml", ".yml"):
            p = self._base / f"{key}{ext}"
            if p.exists():
                import yaml  # local import keeps test paths optional
                return yaml.safe_load(p.read_text(encoding="utf-8"))
        json_p = self._base / f"{key}.json"
        if json_p.exists():
            return json.loads(json_p.read_text(encoding="utf-8"))
        raise FileNotFoundError(
            f"config '{key}' not found under {self._base}"
        )
