"""In-memory MemoryClient for local testing (no API key required)."""

from __future__ import annotations

from ari.memory.client import MemoryClient


class LocalMemoryClient(MemoryClient):
    def __init__(self) -> None:
        self._store: list[dict] = []

    def add(self, content: str, metadata: dict | None = None) -> None:
        self._store.append({"content": content, "metadata": metadata or {}})

    def search(self, query: str, limit: int = 10) -> list[dict]:
        # Simple keyword search
        results = [
            m for m in self._store
            if any(word.lower() in m["content"].lower() for word in query.split())
        ]
        return results[:limit]

    def get_all(self) -> list[dict]:
        return list(self._store)
