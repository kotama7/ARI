"""LettaBackend — Letta-native implementation of MemoryBackend.

The backend delegates to an injected ``client`` (see
``ari_skill_memory.backends.letta_client.LettaClientProtocol``) so
unit tests can substitute a fake without a running Letta server.
When ``client`` is not injected the backend tries to build an HTTP
client against ``LETTA_BASE_URL`` at first use; failures raise
``RuntimeError`` (no fallback — fail fast, fail loud).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from ari_skill_memory.access_log import (
    AccessLog,
    build_read_event,
    build_write_event,
    current_node_id,
)
from ari_skill_memory.backends.base import MemoryBackend
from ari_skill_memory.config import MemoryConfig

log = logging.getLogger(__name__)


class LettaBackend(MemoryBackend):
    """Letta-native backend. Checkpoint-scoped agent + two archival collections."""

    def __init__(self, cfg: MemoryConfig, *, client: Any | None = None) -> None:
        self.cfg = cfg
        self.ckpt_hash = cfg.ckpt_hash
        self.node_collection = f"ari_node_{cfg.ckpt_hash}"
        self.react_collection = f"ari_react_{cfg.ckpt_hash}"
        self.agent_name = f"ari_agent_{cfg.ckpt_hash}"
        self._lock = threading.RLock()
        self._client = client
        self._agent_id: str | None = None
        self._ctx_cache: tuple[float, dict] | None = None
        access_path = cfg.checkpoint_dir / "memory_access.jsonl"
        self._access = AccessLog.for_path(
            access_path,
            enabled=cfg.access_log_enabled,
            max_mb=cfg.access_log_max_mb,
        )
        if cfg.letta_disable_self_edit is False:
            log.warning(
                "ARI_MEMORY_LETTA_DISABLE_SELF_EDIT=false — Letta self-edit "
                "will rewrite archival entries and break CoW for node memory."
            )

    # ─ client lazy-init ────────────────────────────────────────────────
    def _ensure_client(self):
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is not None:
                return self._client
            from ari_skill_memory.backends.letta_client import build_default_client
            self._client = build_default_client(self.cfg)
        return self._client

    def _ensure_agent(self) -> str:
        if self._agent_id is not None:
            return self._agent_id
        client = self._ensure_client()
        with self._lock:
            if self._agent_id is not None:
                return self._agent_id
            aid = client.ensure_agent(
                self.agent_name,
                memory_editing_enabled=not self.cfg.letta_disable_self_edit,
                collections=[self.node_collection, self.react_collection],
            )
            self._agent_id = aid
            self._verify_embedding_compat(aid)
        return aid

    def _verify_embedding_compat(self, agent_id: str) -> None:
        """Cross-check the agent's embedding_config against the configured one.

        The agent's embedding_config is **frozen at creation time** in
        Letta. If a checkpoint's agent was originally built against a
        different embedding handle (most often the MemGPT-hosted
        ``letta/letta-free`` → ``embeddings.memgpt.ai`` endpoint, which
        returns 522 with empty body when its Cloudflare upstream is
        down), every ``add_memory`` call will surface the resulting
        Letta-internal ``Expecting value: line 1 column 1 (char 0)``
        as an opaque 400. This pre-check converts that into a clear,
        actionable error that names the mismatch and the recovery path.
        """
        client = self._ensure_client()
        getter = getattr(client, "get_agent_embedding", None)
        if getter is None:
            return  # client (e.g. older fake) doesn't expose it
        try:
            ec = getter(agent_id) or {}
        except Exception as e:
            log.debug("agent embedding fetch failed: %s", e)
            return
        if not ec:
            return
        configured = (self.cfg.letta_embedding_config or "").strip()
        actual_handle = (ec.get("handle") or "").strip()
        actual_endpoint = (ec.get("embedding_endpoint") or "").strip()
        # Always flag the known-flaky endpoint. We surface a hard error
        # only when the user has explicitly asked for a *different*
        # handle — otherwise we just emit a warning so default
        # deployments still work when memgpt.ai is healthy.
        on_flaky = "embeddings.memgpt.ai" in actual_endpoint
        explicit_choice = configured and configured.lower() not in (
            "", "letta-default", "letta/letta-free",
        )
        if on_flaky and explicit_choice and configured != actual_handle:
            raise RuntimeError(
                "Letta agent embedding mismatch: agent "
                f"{self.agent_name!r} was created with handle "
                f"{actual_handle!r} (endpoint {actual_endpoint!r}) but "
                f"LETTA_EMBEDDING_CONFIG={configured!r}. The agent's "
                "embedding_config is frozen at creation time, so the "
                "mismatched handle will keep being used regardless of "
                "the env override. Recover by purging the checkpoint's "
                "agent (LettaBackend.purge_checkpoint) — the next "
                "add_memory will recreate the agent with the configured "
                "handle. NOTE: purge deletes existing archival passages."
            )
        if on_flaky:
            log.warning(
                "agent %s uses the public embeddings.memgpt.ai endpoint "
                "which returns 522/empty-body when its upstream is "
                "down — set LETTA_EMBEDDING_CONFIG to a self-hosted or "
                "OpenAI handle and purge_checkpoint() to migrate.",
                self.agent_name,
            )

    # ─ CoW helper ──────────────────────────────────────────────────────
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

    # ─ cost tracker helper ─────────────────────────────────────────────
    def _record_cost(
        self, *, op: str, latency_ms: float, embedding_tokens: int = 0
    ) -> None:
        try:
            from ari import cost_tracker  # type: ignore[import]
            cost_tracker.record(
                model="", prompt_tokens=0, completion_tokens=0,
                node_id=current_node_id(),
                phase="memory", skill="ari-skill-memory",
                component="memory", op=op, backend="letta",
                embedding_tokens=embedding_tokens, latency_ms=latency_ms,
            )
        except Exception:
            # cost_tracker may not be installed (standalone skill testing)
            # or may not yet support the new kwargs. Never fail writes
            # because of observability.
            pass

    # ─ MCP tool surface ────────────────────────────────────────────────
    def add_memory(
        self, node_id: str, text: str, metadata: dict | None = None
    ) -> dict:
        cow = self._check_cow(node_id)
        if cow is not None:
            return cow
        client = self._ensure_client()
        agent_id = self._ensure_agent()
        t0 = time.time()
        entry_id = client.archival_insert(
            agent_id=agent_id,
            collection=self.node_collection,
            text=text,
            metadata={
                "node_id": node_id,
                "ari_checkpoint": self.ckpt_hash,
                "kind": "node_scope",
                "ari_metadata": metadata or {},
                "ts": time.time(),
            },
        )
        latency_ms = (time.time() - t0) * 1000.0
        self._record_cost(op="add", latency_ms=latency_ms)
        self._access.write(
            build_write_event(
                node_id=current_node_id(),
                collection="node_scope",
                entry_id=entry_id,
                text=text,
                metadata=metadata or {},
                preview_chars=self.cfg.access_log_preview_chars,
            )
        )
        return {"ok": True, "id": entry_id}

    def search_memory(
        self, query: str, ancestor_ids: list[str], limit: int = 5
    ) -> dict:
        if not ancestor_ids:
            return {"results": []}
        client = self._ensure_client()
        agent_id = self._ensure_agent()
        metadata_filter = {
            "node_id": {"$in": list(ancestor_ids)},
            "ari_checkpoint": self.ckpt_hash,
            "kind": "node_scope",
        }
        t0 = time.time()
        try:
            raw = client.archival_search(
                agent_id=agent_id,
                collection=self.node_collection,
                query=query,
                filter=metadata_filter,
                limit=limit,
            )
            filtered = raw  # client applied filter
        except NotImplementedError:
            # Pre-filter unsupported — overfetch + post-filter.
            overfetch = max(self.cfg.letta_overfetch, limit * 40)
            raw = client.archival_search(
                agent_id=agent_id,
                collection=self.node_collection,
                query=query,
                filter=None,
                limit=overfetch,
            )
            allowed = set(ancestor_ids)
            filtered = [
                r for r in raw
                if r.get("metadata", {}).get("node_id") in allowed
                and r.get("metadata", {}).get("ari_checkpoint") == self.ckpt_hash
                and r.get("metadata", {}).get("kind") == "node_scope"
            ]
            if len(filtered) < min(limit, len(raw)):
                log.warning(
                    "ari-memory: post-filter dropped results below limit "
                    "(raw=%d, kept=%d, limit=%d)", len(raw), len(filtered), limit,
                )
        results = []
        for r in filtered[:limit]:
            md = r.get("metadata", {}) or {}
            results.append({
                "entry_id": r.get("id"),
                "node_id": md.get("node_id", ""),
                "text": r.get("text", ""),
                "metadata": md.get("ari_metadata", {}) or {},
                "score": float(r.get("score", 0.0)),
            })
        latency_ms = (time.time() - t0) * 1000.0
        self._record_cost(op="search", latency_ms=latency_ms)
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
        client = self._ensure_client()
        agent_id = self._ensure_agent()
        entries = client.archival_list(
            agent_id=agent_id,
            collection=self.node_collection,
            filter={
                "node_id": node_id,
                "ari_checkpoint": self.ckpt_hash,
                "kind": "node_scope",
            },
            order_by="ts",
            order="asc",
        )
        return {"entries": [
            {
                "text": e.get("text", ""),
                "metadata": (e.get("metadata", {}) or {}).get("ari_metadata", {}),
                "ts": (e.get("metadata", {}) or {}).get("ts", 0),
            } for e in entries
        ]}

    def clear_node_memory(self, node_id: str) -> dict:
        cow = self._check_cow(node_id)
        if cow is not None:
            return {"removed": 0, "error": cow["error"]}
        client = self._ensure_client()
        agent_id = self._ensure_agent()
        entries = client.archival_list(
            agent_id=agent_id,
            collection=self.node_collection,
            filter={
                "node_id": node_id,
                "ari_checkpoint": self.ckpt_hash,
                "kind": "node_scope",
            },
        )
        for e in entries:
            client.archival_delete(
                agent_id=agent_id,
                collection=self.node_collection,
                entry_id=e["id"],
            )
        return {"removed": len(entries)}

    def get_experiment_context(self) -> dict:
        if self._ctx_cache is not None:
            when, data = self._ctx_cache
            if (time.time() - when) < 60.0:
                return dict(data)
        client = self._ensure_client()
        agent_id = self._ensure_agent()
        ctx = client.read_core_context(agent_id=agent_id)
        self._ctx_cache = (time.time(), ctx)
        return dict(ctx)

    # ─ Library helpers ─────────────────────────────────────────────────
    def list_all_nodes(self) -> dict:
        client = self._ensure_client()
        agent_id = self._ensure_agent()
        entries = client.archival_list(
            agent_id=agent_id,
            collection=self.node_collection,
            filter={"ari_checkpoint": self.ckpt_hash, "kind": "node_scope"},
            order_by="ts",
            order="asc",
        )
        by_node: dict[str, list[dict]] = {}
        for e in entries:
            md = e.get("metadata", {}) or {}
            nid = md.get("node_id", "")
            by_node.setdefault(nid, []).append({
                "entry_id": e.get("id"),
                "text": e.get("text", ""),
                "metadata": md.get("ari_metadata", {}) or {},
                "ts": md.get("ts", 0),
            })
        return {"by_node": by_node}

    def bulk_get_node_memory(self, node_ids: list[str]) -> dict:
        client = self._ensure_client()
        agent_id = self._ensure_agent()
        entries = client.archival_list(
            agent_id=agent_id,
            collection=self.node_collection,
            filter={
                "node_id": {"$in": list(node_ids)},
                "ari_checkpoint": self.ckpt_hash,
                "kind": "node_scope",
            },
            order_by="ts",
            order="asc",
        )
        by_node: dict[str, list[dict]] = {nid: [] for nid in node_ids}
        for e in entries:
            md = e.get("metadata", {}) or {}
            nid = md.get("node_id", "")
            if nid in by_node:
                by_node[nid].append({
                    "text": e.get("text", ""),
                    "metadata": md.get("ari_metadata", {}) or {},
                    "ts": md.get("ts", 0),
                })
        return {"by_node": by_node}

    def purge_checkpoint(self) -> dict:
        client = self._ensure_client()
        try:
            agent_id = self._ensure_agent()
        except Exception:
            return {"removed_node": 0, "removed_react": 0}
        # collect counts before deleting
        removed_node = 0
        removed_react = 0
        try:
            for coll, key in (
                (self.node_collection, "removed_node"),
                (self.react_collection, "removed_react"),
            ):
                entries = client.archival_list(
                    agent_id=agent_id,
                    collection=coll,
                    filter={"ari_checkpoint": self.ckpt_hash},
                )
                for e in entries:
                    client.archival_delete(
                        agent_id=agent_id, collection=coll, entry_id=e["id"]
                    )
                if key == "removed_node":
                    removed_node = len(entries)
                else:
                    removed_react = len(entries)
        finally:
            try:
                client.delete_agent(agent_id=agent_id)
            except Exception as e:
                log.warning("Letta agent cleanup failed: %s", e)
            self._agent_id = None
        return {"removed_node": removed_node, "removed_react": removed_react}

    def bulk_import(self, entries: list[dict], kind: str) -> dict:
        client = self._ensure_client()
        agent_id = self._ensure_agent()
        n = 0
        if kind == "node_scope":
            for e in entries:
                client.archival_insert(
                    agent_id=agent_id,
                    collection=self.node_collection,
                    text=e.get("text", ""),
                    metadata={
                        "node_id": e.get("node_id", ""),
                        "ari_checkpoint": self.ckpt_hash,
                        "kind": "node_scope",
                        "ari_metadata": e.get("metadata", {}) or {},
                        "ts": e.get("ts", time.time()),
                    },
                )
                n += 1
        elif kind == "react_step":
            for e in entries:
                client.archival_insert(
                    agent_id=agent_id,
                    collection=self.react_collection,
                    text=e.get("content") or e.get("text") or "",
                    metadata={
                        "ari_checkpoint": self.ckpt_hash,
                        "kind": "react_step",
                        "node_id": (e.get("metadata") or {}).get("node_id", ""),
                        "step": (e.get("metadata") or {}).get("step"),
                        "ari_metadata": e.get("metadata", {}) or {},
                        "ts": e.get("ts", time.time()),
                    },
                )
                n += 1
        elif kind == "core_seed":
            for e in entries:
                persona = e.get("persona", "")
                human = e.get("human", "")
                ctx = e.get("context") or {}
                self.seed_core_memory(persona, human, ctx)
                n += 1
        else:
            raise ValueError(f"unknown bulk_import kind: {kind!r}")
        return {"imported": n, "kind": kind}

    def list_react_entries(self, limit: int | None = None) -> list[dict]:
        client = self._ensure_client()
        agent_id = self._ensure_agent()
        entries = client.archival_list(
            agent_id=agent_id,
            collection=self.react_collection,
            filter={"ari_checkpoint": self.ckpt_hash, "kind": "react_step"},
            order_by="ts",
            order="asc",
            limit=limit,
        )
        out = []
        for e in entries:
            md = e.get("metadata", {}) or {}
            out.append({
                "id": e.get("id"),
                "content": e.get("text", ""),
                "metadata": md.get("ari_metadata", {}) or {},
                "ts": md.get("ts", 0),
            })
        return out

    def react_add(self, content: str, metadata: dict | None = None) -> None:
        cap = self.cfg.react_max_entry_chars
        if cap and len(content) > cap:
            content = content[:cap] + "…[truncated]"
        client = self._ensure_client()
        agent_id = self._ensure_agent()
        entry_id = client.archival_insert(
            agent_id=agent_id,
            collection=self.react_collection,
            text=content,
            metadata={
                "ari_checkpoint": self.ckpt_hash,
                "kind": "react_step",
                "node_id": (metadata or {}).get("node_id", ""),
                "step": (metadata or {}).get("step"),
                "ari_metadata": metadata or {},
                "ts": time.time(),
            },
        )
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
        client = self._ensure_client()
        agent_id = self._ensure_agent()
        raw = client.archival_search(
            agent_id=agent_id,
            collection=self.react_collection,
            query=query,
            filter={"ari_checkpoint": self.ckpt_hash, "kind": "react_step"},
            limit=limit,
        )
        out = []
        for r in raw:
            md = r.get("metadata", {}) or {}
            out.append({
                "id": r.get("id"),
                "content": r.get("text", ""),
                "metadata": md.get("ari_metadata", {}) or {},
                "ts": md.get("ts", 0),
                "score": float(r.get("score", 0.0)),
            })
        self._access.write(
            build_read_event(
                node_id=current_node_id(),
                collection="react_step",
                query=query,
                ancestor_ids=None,
                limit=limit,
                results=[
                    {"entry_id": r["id"], "src_node_id": "",
                     "score": r["score"]}
                    for r in out
                ],
            )
        )
        return out

    def react_get_all(self) -> list[dict]:
        return self.list_react_entries(limit=None)

    def seed_core_memory(
        self, persona: str, human: str, context: dict | None = None
    ) -> dict:
        client = self._ensure_client()
        agent_id = self._ensure_agent()
        client.write_core_blocks(
            agent_id=agent_id,
            persona=persona,
            human=human,
            context=context or {},
        )
        self._ctx_cache = None
        return {"ok": True, "seeded_at": time.time()}

    def health(self) -> dict:
        client = self._ensure_client()
        t0 = time.time()
        info = client.health()
        latency_ms = (time.time() - t0) * 1000.0
        return {
            "ok": bool(info.get("ok", True)),
            "backend": "letta",
            "latency_ms": latency_ms,
            "server_version": info.get("server_version", ""),
            "namespace": self.ckpt_hash,
        }


__all__ = ["LettaBackend"]
