"""PromptLoader — Phase PC0 (PROMPTS_AND_CONFIG.md §2-2 / §2-4).

Provides the same minimal abstraction over "load a prompt template by
key" that ``ari.configs._loader`` does for config blobs.  Tests can
swap in their own loader to exercise prompt drift without modifying
shipped files.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol


def package_prompts_root() -> Path:
    """Return the bundled ``ari-core/ari/prompts/`` directory."""
    return Path(__file__).resolve().parent


class PromptLoader(Protocol):
    """Loads prompt templates from external files."""

    def load(self, key: str) -> str:
        """Load the raw prompt template for *key* (e.g. "agent/system")."""
        ...

    def load_versioned(self, key: str, version: str | None = None) -> tuple[str, str]:
        """Return ``(text, version_id)`` so reproducibility tooling can pin a
        run to a specific prompt revision.
        """
        ...


class FilesystemPromptLoader:
    """Default :class:`PromptLoader` reading ``.md`` files from a directory."""

    def __init__(self, base: Path | None = None) -> None:
        self._base = base or package_prompts_root()

    def load(self, key: str) -> str:
        path = self._base / f"{key}.md"
        return path.read_text(encoding="utf-8")

    def load_versioned(self, key: str, version: str | None = None) -> tuple[str, str]:
        text = self.load(key)
        # Truncated content hash is stable across machines, unlike a git
        # SHA, and we don't need cryptographic strength here.
        return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
