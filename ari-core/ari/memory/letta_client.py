"""LettaMemoryClient — MemoryClient ABC backed by a Letta ``ari_react_*`` collection.

See LETTA_BACKEND_SPEC.md §5.5. Swapped in for ``FileMemoryClient`` at
``ari.core.build_runtime``; ``FileMemoryClient`` is retained only for the
v0.5.x migration CLI.

Unlike MCP ``search_memory`` (ancestor-scoped), this client intentionally
returns results from across the whole checkpoint regardless of the
calling node — matching the pre-v0.6.0 ReAct semantics (§5.5.3).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from ari.memory.client import MemoryClient

log = logging.getLogger(__name__)


class LettaMemoryClient(MemoryClient):
    def __init__(self, checkpoint_dir: str | Path) -> None:
        self._ckpt = Path(checkpoint_dir).expanduser().resolve()
        from ari.paths import PathManager
        PathManager.set_checkpoint_dir_env(self._ckpt)
        from ari_skill_memory.backends import get_backend
        self._backend = get_backend(checkpoint_dir=self._ckpt)
        log.info(
            "LettaMemoryClient: ready for checkpoint %s", self._ckpt,
        )

    def add(self, content: str, metadata: dict | None = None) -> None:
        try:
            self._backend.react_add(content, metadata or {})
        except Exception as e:  # pragma: no cover - Letta down
            log.warning("LettaMemoryClient.add failed: %s", e)

    def search(self, query: str, limit: int = 10) -> list[dict]:
        limit_env = os.environ.get("ARI_REACT_MEMORY_SEARCH_LIMIT")
        if limit_env:
            try:
                limit = int(limit_env)
            except ValueError:
                pass
        try:
            return [
                {
                    "content": e["content"],
                    "metadata": e["metadata"],
                    "ts": e["ts"],
                }
                for e in self._backend.react_search(query, limit=limit)
            ]
        except Exception as e:
            log.warning("LettaMemoryClient.search failed: %s", e)
            return []

    def get_all(self) -> list[dict]:
        try:
            return [
                {
                    "content": e["content"],
                    "metadata": e["metadata"],
                    "ts": e["ts"],
                }
                for e in self._backend.react_get_all()
            ]
        except Exception as e:
            log.warning("LettaMemoryClient.get_all failed: %s", e)
            return []


__all__ = ["LettaMemoryClient"]
