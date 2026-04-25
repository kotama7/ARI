"""InMemoryBackend — dict-based test fake.

Reachable only from tests and the ``ARI_MEMORY_BACKEND=in_memory``
developer escape hatch. Never on disk for production code paths.

Deterministic keyword-match scoring preserves v0.5.x semantics for
any test that compares retrieval ordering.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any

from ari_skill_memory.access_log import (
    AccessLog,
    build_read_event,
    build_write_event,
    current_node_id,
)
from ari_skill_memory.backends.base import MemoryBackend
from ari_skill_memory.config import MemoryConfig


def _score(text: str, query: str) -> float:
    q_words = [w.lower() for w in (query or "").split() if w]
    t_lower = (text or "").lower()
    hits = sum(1 for w in q_words if w in t_lower)
    if not q_words:
        return 0.0
    return hits / max(1, len(q_words))


class InMemoryBackend(MemoryBackend):
    def __init__(self, cfg: MemoryConfig) -> None:
        self.cfg = cfg
        self._lock = threading.RLock()
        # Entries keyed by id
        self._node_entries: dict[str, dict] = {}
        self._react_entries: list[dict] = []
        self._core_persona: str = ""
        self._core_human: str = ""
        self._core_context: dict = {}
        self._core_seeded_at: float = 0.0
        self._closed = False
        access_path = cfg.checkpoint_dir / "memory_access.jsonl"
        self._access = AccessLog.for_path(
            access_path,
            enabled=cfg.access_log_enabled,
            max_mb=cfg.access_log_max_mb,
        )

    # ─ CoW helpers ─────────────────────────────────────────────────────
    def _check_cow(self, node_id: str) -> dict | None:
        env_node = os.environ.get("ARI_CURRENT_NODE_ID")
        if env_node is None or env_node == "":
            return {"ok": False, "error": "ARI_CURRENT_NODE_ID not set"}
        if node_id != env_node:
            return {
                "ok": False,
                "error": "node_id does not match current node (CoW violation)",
            }
        return None

    # ─ MCP tool surface ────────────────────────────────────────────────
    def add_memory(
        self, node_id: str, text: str, metadata: dict | None = None
    ) -> dict:
        cow = self._check_cow(node_id)
        if cow is not None:
            return cow
        entry_id = str(uuid.uuid4())
        entry = {
            "id": entry_id,
            "node_id": node_id,
            "text": text,
            "metadata": metadata or {},
            "ari_checkpoint": self.cfg.ckpt_hash,
            "kind": "node_scope",
            "ts": time.time(),
        }
        with self._lock:
            self._node_entries[entry_id] = entry
        self._access.write(
            build_write_event(
                node_id=current_node_id(),
                collection="node_scope",
                entry_id=entry_id,
                text=text,
                metadata=entry["metadata"],
                preview_chars=self.cfg.access_log_preview_chars,
            )
        )
        return {"ok": True, "id": entry_id}

    def search_memory(
        self, query: str, ancestor_ids: list[str], limit: int = 5
    ) -> dict:
        if not ancestor_ids:
            return {"results": []}
        allowed = set(ancestor_ids)
        with self._lock:
            cand = [e for e in self._node_entries.values()
                    if e["node_id"] in allowed]
        scored: list[dict] = []
        for e in cand:
            s = _score(e["text"], query)
            if s > 0 or not (query or "").strip():
                scored.append({
                    "entry_id": e["id"],
                    "node_id": e["node_id"],
                    "text": e["text"],
                    "metadata": e["metadata"],
                    "score": s,
                })
        scored.sort(key=lambda x: -x["score"])
        results = scored[:limit]
        self._access.write(
            build_read_event(
                node_id=current_node_id(),
                collection="node_scope",
                query=query,
                ancestor_ids=list(ancestor_ids),
                limit=limit,
                results=[
                    {
                        "entry_id": r["entry_id"],
                        "src_node_id": r["node_id"],
                        "score": r["score"],
                    } for r in results
                ],
            )
        )
        return {"results": results}

    def get_node_memory(self, node_id: str) -> dict:
        with self._lock:
            entries = sorted(
                (e for e in self._node_entries.values()
                 if e["node_id"] == node_id),
                key=lambda e: e["ts"],
            )
        return {"entries": [
            {"text": e["text"], "metadata": e["metadata"], "ts": e["ts"]}
            for e in entries
        ]}

    def clear_node_memory(self, node_id: str) -> dict:
        cow = self._check_cow(node_id)
        if cow is not None:
            return {"removed": 0, "error": cow["error"]}
        with self._lock:
            to_del = [k for k, e in self._node_entries.items()
                      if e["node_id"] == node_id]
            for k in to_del:
                del self._node_entries[k]
        return {"removed": len(to_del)}

    def get_experiment_context(self) -> dict:
        with self._lock:
            ctx = dict(self._core_context)
            ctx["seeded_at"] = self._core_seeded_at
        return ctx

    # ─ Library helpers ─────────────────────────────────────────────────
    def list_all_nodes(self) -> dict:
        with self._lock:
            entries = list(self._node_entries.values())
        by_node: dict[str, list[dict]] = {}
        for e in entries:
            by_node.setdefault(e["node_id"], []).append({
                "entry_id": e["id"],
                "text": e["text"],
                "metadata": e["metadata"],
                "ts": e["ts"],
            })
        for lst in by_node.values():
            lst.sort(key=lambda x: x["ts"])
        return {"by_node": by_node}

    def bulk_get_node_memory(self, node_ids: list[str]) -> dict:
        want = set(node_ids)
        with self._lock:
            entries = [e for e in self._node_entries.values()
                       if e["node_id"] in want]
        entries.sort(key=lambda e: e["ts"])
        by_node: dict[str, list[dict]] = {nid: [] for nid in node_ids}
        for e in entries:
            by_node[e["node_id"]].append({
                "text": e["text"],
                "metadata": e["metadata"],
                "ts": e["ts"],
            })
        return {"by_node": by_node}

    def purge_checkpoint(self) -> dict:
        with self._lock:
            nn = len(self._node_entries)
            nr = len(self._react_entries)
            self._node_entries.clear()
            self._react_entries.clear()
            self._core_persona = ""
            self._core_human = ""
            self._core_seeded_at = 0.0
        return {"removed_node": nn, "removed_react": nr}

    def bulk_import(self, entries: list[dict], kind: str) -> dict:
        n = 0
        if kind == "node_scope":
            with self._lock:
                for e in entries:
                    entry_id = e.get("id") or str(uuid.uuid4())
                    self._node_entries[entry_id] = {
                        "id": entry_id,
                        "node_id": e.get("node_id", ""),
                        "text": e.get("text", ""),
                        "metadata": e.get("metadata", {}) or {},
                        "ari_checkpoint": self.cfg.ckpt_hash,
                        "kind": "node_scope",
                        "ts": e.get("ts", time.time()),
                    }
                    n += 1
        elif kind == "react_step":
            with self._lock:
                for e in entries:
                    entry_id = e.get("id") or str(uuid.uuid4())
                    self._react_entries.append({
                        "id": entry_id,
                        "content": e.get("content") or e.get("text") or "",
                        "metadata": e.get("metadata", {}) or {},
                        "ts": e.get("ts", time.time()),
                    })
                    n += 1
        elif kind == "core_seed":
            persona = ""
            human = ""
            context: dict = {}
            seeded_at = 0.0
            for e in entries:
                persona = e.get("persona") or persona
                human = e.get("human") or human
                if e.get("context"):
                    context = e["context"]
                seeded_at = e.get("seeded_at") or seeded_at
            with self._lock:
                self._core_persona = persona
                self._core_human = human
                self._core_context = context
                self._core_seeded_at = seeded_at
            n += 1
        else:
            raise ValueError(f"unknown bulk_import kind: {kind!r}")
        return {"imported": n, "kind": kind}

    def list_react_entries(self, limit: int | None = None) -> list[dict]:
        with self._lock:
            out = list(self._react_entries)
        out.sort(key=lambda e: e["ts"])
        if limit is not None:
            out = out[-limit:]
        return [
            {"content": e["content"], "metadata": e["metadata"], "ts": e["ts"],
             "id": e["id"]}
            for e in out
        ]

    def react_add(self, content: str, metadata: dict | None = None) -> None:
        cap = self.cfg.react_max_entry_chars
        if cap and len(content) > cap:
            content = content[:cap] + "…[truncated]"
        entry_id = str(uuid.uuid4())
        with self._lock:
            self._react_entries.append({
                "id": entry_id,
                "content": content,
                "metadata": metadata or {},
                "ts": time.time(),
            })
        self._access.write(
            build_write_event(
                node_id=current_node_id(),
                collection="react_step",
                entry_id=entry_id,
                text=content,
                metadata=metadata or {},
                preview_chars=self.cfg.access_log_preview_chars,
            )
        )

    def react_search(self, query: str, limit: int = 10) -> list[dict]:
        with self._lock:
            entries = list(self._react_entries)
        scored: list[tuple[float, dict]] = []
        for e in entries:
            s = _score(e["content"], query)
            if s > 0:
                scored.append((s, e))
        scored.sort(key=lambda x: -x[0])
        picked = [e for _, e in scored[:limit]]
        self._access.write(
            build_read_event(
                node_id=current_node_id(),
                collection="react_step",
                query=query,
                ancestor_ids=None,
                limit=limit,
                results=[{"entry_id": e["id"], "src_node_id": "",
                          "score": s}
                         for s, e in scored[:limit]],
            )
        )
        return [
            {"content": e["content"], "metadata": e["metadata"],
             "ts": e["ts"], "id": e["id"]}
            for e in picked
        ]

    def react_get_all(self) -> list[dict]:
        with self._lock:
            out = list(self._react_entries)
        out.sort(key=lambda e: e["ts"])
        return [
            {"content": e["content"], "metadata": e["metadata"],
             "ts": e["ts"], "id": e["id"]}
            for e in out
        ]

    def seed_core_memory(
        self, persona: str, human: str, context: dict | None = None
    ) -> dict:
        with self._lock:
            self._core_persona = persona
            self._core_human = human
            self._core_context = dict(context or {})
            self._core_seeded_at = time.time()
        return {"ok": True, "seeded_at": self._core_seeded_at}

    def health(self) -> dict:
        return {
            "ok": True,
            "backend": "in_memory",
            "latency_ms": 0.0,
            "server_version": "fake",
            "namespace": self.cfg.ckpt_hash,
        }

    def close(self) -> None:
        self._closed = True


__all__ = ["InMemoryBackend"]
