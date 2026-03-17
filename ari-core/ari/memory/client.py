"""Abstract Memory client interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class MemoryClient(ABC):
    @abstractmethod
    def add(self, content: str, metadata: dict | None = None) -> None:
        """Add a memory entry."""
        ...

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search memories by query."""
        ...

    @abstractmethod
    def get_all(self) -> list[dict]:
        """Retrieve all stored memories."""
        ...
