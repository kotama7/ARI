"""Append-only memory access log.

Records write/read events to ``{ckpt}/memory_access.jsonl`` so the viz
dashboard can answer "what memory was written / read at this node?".
This is telemetry, not the memory store itself — it is tolerant of
partial Letta outages for debugging.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_FLUSH_INTERVAL_S = 2.0
_MAX_QUEUE = 4096


class AccessLog:
    """Per-checkpoint bounded-queue append writer.

    One instance per checkpoint_dir. The writer is backed by a daemon
    thread that flushes every ``_FLUSH_INTERVAL_S`` seconds. On process
    exit the queue is drained.
    """

    _INSTANCES: dict[str, "AccessLog"] = {}
    _INSTANCES_LOCK = threading.Lock()
    _DROP_COUNTER = 0
    _DROP_LOCK = threading.Lock()

    @classmethod
    def for_path(cls, path: Path, enabled: bool, max_mb: int) -> "AccessLog":
        key = str(path.resolve())
        with cls._INSTANCES_LOCK:
            inst = cls._INSTANCES.get(key)
            if inst is None:
                inst = cls(path, enabled=enabled, max_mb=max_mb)
                cls._INSTANCES[key] = inst
            return inst

    def __init__(self, path: Path, *, enabled: bool, max_mb: int) -> None:
        self.path = path
        self.enabled = enabled
        self.max_mb = max_mb
        self._q: "queue.Queue[dict | None]" = queue.Queue(maxsize=_MAX_QUEUE)
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        if enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._worker = threading.Thread(
                target=self._run, name=f"ari-memory-access[{path.name}]", daemon=True
            )
            self._worker.start()
            atexit.register(self.flush_and_close)

    # ─ public API ──────────────────────────────────────────────────────
    def write(self, event: dict) -> None:
        if not self.enabled:
            return
        try:
            self._q.put_nowait(event)
        except queue.Full:
            with AccessLog._DROP_LOCK:
                AccessLog._DROP_COUNTER += 1
            log.warning(
                "ari-memory: access log queue full (dropped=%d)",
                AccessLog._DROP_COUNTER,
            )

    def flush_and_close(self) -> None:
        if not self.enabled or self._worker is None:
            return
        # Put the None sentinel BEFORE setting the stop flag so the worker
        # drains everything already queued.
        try:
            self._q.put(None, timeout=1.0)
        except queue.Full:
            pass
        self._worker.join(timeout=3.0)
        self._stop.set()

    # ─ worker ──────────────────────────────────────────────────────────
    def _run(self) -> None:
        buf: list[dict] = []
        last_flush = time.time()
        while True:
            try:
                item = self._q.get(timeout=_FLUSH_INTERVAL_S)
            except queue.Empty:
                item = "__timeout__"
            if item is None:
                break
            if isinstance(item, dict):
                buf.append(item)
            if buf and (
                item == "__timeout__"
                or (time.time() - last_flush) >= _FLUSH_INTERVAL_S
            ):
                self._flush(buf)
                buf.clear()
                last_flush = time.time()
        if buf:
            self._flush(buf)

    def _flush(self, events: list[dict]) -> None:
        if not events:
            return
        try:
            self._maybe_rotate()
            with self.path.open("a", encoding="utf-8") as f:
                for ev in events:
                    f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("ari-memory: access log write failed: %s", e)

    def _maybe_rotate(self) -> None:
        try:
            size_mb = self.path.stat().st_size / (1024 * 1024)
        except OSError:
            return
        if size_mb < self.max_mb:
            return
        ts = int(time.time())
        rotated = self.path.with_name(f"{self.path.stem}.{ts}.jsonl")
        try:
            self.path.rename(rotated)
            log.info("ari-memory: rotated access log -> %s", rotated.name)
        except OSError as e:
            log.warning("ari-memory: rotation failed: %s", e)


def build_write_event(
    *, node_id: str, collection: str, entry_id: str, text: str, metadata: dict,
    preview_chars: int,
) -> dict:
    return {
        "ts": time.time(),
        "node_id": node_id,
        "op": "write",
        "collection": collection,
        "entry_id": entry_id,
        "text_preview": (text or "")[:preview_chars],
        "metadata": metadata or {},
    }


def build_read_event(
    *, node_id: str, collection: str, query: str,
    ancestor_ids: list[str] | None, limit: int, results: list[dict],
) -> dict:
    return {
        "ts": time.time(),
        "node_id": node_id,
        "op": "read",
        "collection": collection,
        "query": query,
        "ancestor_ids": ancestor_ids,
        "limit": limit,
        "results": results,
    }


def current_node_id() -> str:
    return os.environ.get("ARI_CURRENT_NODE_ID", "") or ""


__all__ = [
    "AccessLog",
    "build_write_event",
    "build_read_event",
    "current_node_id",
]
