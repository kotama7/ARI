"""File-backed persistent MemoryClient — survives process restarts."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from ari.memory.client import MemoryClient

logger = logging.getLogger(__name__)


class FileMemoryClient(MemoryClient):
    """Client that persists memory to a JSON file.

    - Thread-safe (protected by RLock)
    - Loads existing file on startup
    - Writes to disk on every add()
    - search() uses TF-IDF-style keyword scoring
    """

    def __init__(self, path: str = "~/.ari/memory.json") -> None:
        self._path = Path(path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._store: list[dict] = self._load()
        logger.info("FileMemoryClient: loaded %d entries from %s", len(self._store), self._path)

    def _load(self) -> list[dict]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("FileMemoryClient: failed to load %s: %s", self._path, e)
        return []

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._store, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("FileMemoryClient: failed to save: %s", e)

    def add(self, content: str, metadata: dict | None = None) -> None:
        entry = {
            "content": content,
            "metadata": metadata or {},
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._store.append(entry)
            self._save()

    def search(self, query: str, limit: int = 10) -> list[dict]:
        words = set(query.lower().split())
        with self._lock:
            scored = []
            for m in self._store:
                text = m["content"].lower()
                hits = sum(1 for w in words if w in text)
                if hits:
                    scored.append((hits, m))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [m for _, m in scored[:limit]]

    def get_all(self) -> list[dict]:
        with self._lock:
            return list(self._store)
