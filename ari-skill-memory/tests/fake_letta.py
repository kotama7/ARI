"""In-process fake Letta client matching LettaClientProtocol.

Used by LettaBackend tests so we exercise letta_backend.py code paths
without a running Letta server."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field


@dataclass
class _Entry:
    id: str
    text: str
    metadata: dict


@dataclass
class FakeLettaClient:
    supports_pre_filter: bool = True
    # agent_id -> collection -> list[entry]
    _archival: dict[str, dict[str, list[_Entry]]] = field(default_factory=dict)
    # agent_id -> label -> value
    _core: dict[str, dict[str, str]] = field(default_factory=dict)
    # name -> id
    _agents: dict[str, str] = field(default_factory=dict)
    _health_ok: bool = True
    version: str = "fake-0"
    # Tests can pre-set the embedding config that get_agent_embedding
    # will return — used by integrity-check tests that simulate a
    # checkpoint whose Letta agent was created with a flaky handle.
    embedding_config: dict = field(default_factory=lambda: {
        "handle": "letta/letta-free",
        "embedding_endpoint": "https://embeddings.memgpt.ai",
        "embedding_model": "letta-free",
    })
    # For test visibility
    insert_calls: list[dict] = field(default_factory=list)
    search_calls: list[dict] = field(default_factory=list)

    # ─ client protocol ─────────────────────────────────────────────────
    def health(self) -> dict:
        if not self._health_ok:
            raise RuntimeError("fake-letta down")
        return {"ok": True, "server_version": self.version}

    def set_health(self, ok: bool) -> None:
        self._health_ok = ok

    def ensure_agent(self, name, *, memory_editing_enabled, collections):
        if name in self._agents:
            return self._agents[name]
        aid = f"agent-{uuid.uuid4().hex[:8]}"
        self._agents[name] = aid
        self._archival[aid] = {c: [] for c in collections}
        self._core[aid] = {"persona": "", "human": "", "ari_context": ""}
        return aid

    def get_agent_embedding(self, agent_id):
        return dict(self.embedding_config)

    def delete_agent(self, agent_id):
        self._archival.pop(agent_id, None)
        self._core.pop(agent_id, None)
        for k, v in list(self._agents.items()):
            if v == agent_id:
                self._agents.pop(k, None)

    def archival_insert(self, *, agent_id, collection, text, metadata):
        entry_id = f"mem-{uuid.uuid4().hex[:8]}"
        self._archival.setdefault(agent_id, {}).setdefault(collection, []).append(
            _Entry(id=entry_id, text=text, metadata=dict(metadata))
        )
        self.insert_calls.append(
            {"agent_id": agent_id, "collection": collection,
             "text": text, "metadata": dict(metadata)}
        )
        return entry_id

    def archival_search(self, *, agent_id, collection, query, filter, limit):
        self.search_calls.append(
            {"agent_id": agent_id, "collection": collection,
             "query": query, "filter": filter, "limit": limit}
        )
        if filter is not None and not self.supports_pre_filter:
            raise NotImplementedError("pre-filter not supported")
        entries = list(self._archival.get(agent_id, {}).get(collection, []))
        if filter is not None:
            entries = [e for e in entries if _match(e.metadata, filter)]
        q_words = [w.lower() for w in (query or "").split() if w]
        scored: list[tuple[float, _Entry]] = []
        for e in entries:
            hits = sum(1 for w in q_words if w in e.text.lower())
            score = hits / max(1, len(q_words)) if q_words else 0.0
            scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        out = []
        for s, e in scored[:limit]:
            out.append({
                "id": e.id,
                "text": e.text,
                "metadata": e.metadata,
                "score": s,
            })
        return out

    def archival_list(
        self, *, agent_id, collection, filter=None,
        order_by=None, order=None, limit=None,
    ):
        entries = list(self._archival.get(agent_id, {}).get(collection, []))
        if filter is not None:
            entries = [e for e in entries if _match(e.metadata, filter)]
        out = [
            {"id": e.id, "text": e.text, "metadata": dict(e.metadata)}
            for e in entries
        ]
        if order_by:
            out.sort(
                key=lambda x: (x["metadata"] or {}).get(order_by, 0),
                reverse=(order == "desc"),
            )
        if limit is not None:
            out = out[:limit]
        return out

    def archival_delete(self, *, agent_id, collection, entry_id):
        lst = self._archival.get(agent_id, {}).get(collection, [])
        self._archival[agent_id][collection] = [
            e for e in lst if e.id != entry_id
        ]

    def write_core_blocks(self, *, agent_id, persona, human, context):
        self._core.setdefault(agent_id, {})
        self._core[agent_id]["persona"] = persona
        self._core[agent_id]["human"] = human
        self._core[agent_id]["ari_context"] = json.dumps(
            context or {}, ensure_ascii=False
        )

    def read_core_context(self, *, agent_id):
        val = self._core.get(agent_id, {}).get("ari_context", "")
        if not val:
            return {}
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return {}


def _match(metadata: dict, filter: dict) -> bool:
    for k, v in filter.items():
        if isinstance(v, dict) and "$in" in v:
            if metadata.get(k) not in v["$in"]:
                return False
        elif metadata.get(k) != v:
            return False
    return True
