"""MemoryBackend ABC."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MemoryBackend(ABC):
    """Abstract backend for node-scope + react-trace memory.

    Public MCP tool surface (–,):
        add_memory, search_memory, get_node_memory, clear_node_memory,
        get_experiment_context

    Library-only helpers:
        list_all_nodes, bulk_get_node_memory, purge_checkpoint,
        bulk_import, list_react_entries, react_add, react_search,
        react_get_all, health
    """

    # ─ MCP tool surface ────────────────────────────────────────────────
    @abstractmethod
    def add_memory(
        self, node_id: str, text: str, metadata: dict | None = None
    ) -> dict: ...

    @abstractmethod
    def search_memory(
        self, query: str, ancestor_ids: list[str], limit: int = 5
    ) -> dict: ...

    @abstractmethod
    def get_node_memory(self, node_id: str) -> dict: ...

    @abstractmethod
    def clear_node_memory(self, node_id: str) -> dict: ...

    @abstractmethod
    def get_experiment_context(self) -> dict: ...

    # ─ Library-only helpers ────────────────────────────────────────────
    @abstractmethod
    def list_all_nodes(self) -> dict: ...

    @abstractmethod
    def bulk_get_node_memory(self, node_ids: list[str]) -> dict: ...

    @abstractmethod
    def purge_checkpoint(self) -> dict: ...

    @abstractmethod
    def bulk_import(self, entries: list[dict], kind: str) -> dict: ...

    @abstractmethod
    def list_react_entries(self, limit: int | None = None) -> list[dict]: ...

    @abstractmethod
    def react_add(self, content: str, metadata: dict | None = None) -> None: ...

    @abstractmethod
    def react_search(self, query: str, limit: int = 10) -> list[dict]: ...

    @abstractmethod
    def react_get_all(self) -> list[dict]: ...

    @abstractmethod
    def seed_core_memory(
        self, persona: str, human: str, context: dict | None = None
    ) -> dict: ...

    @abstractmethod
    def health(self) -> dict: ...

    # ─ Optional cleanup ────────────────────────────────────────────────
    def close(self) -> None:  # noqa: B027
        """Release resources. Default is no-op."""
        return None


__all__ = ["MemoryBackend"]
