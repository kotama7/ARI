"""Letta client abstraction used by LettaBackend.

Letta's public SDK API changes across versions, so we define a small
internal protocol and a single adapter class that wraps the real
``letta-client`` package (or the ``letta`` package when only the
server-mode SDK is installed). Tests inject a fake matching this
protocol.

Protocol surface (all methods sync, raise on Letta failures):

- ``health() -> dict``  with keys ``ok``, ``server_version``.
- ``ensure_agent(name, memory_editing_enabled, collections) -> agent_id``.
- ``delete_agent(agent_id)``.
- ``archival_insert(agent_id, collection, text, metadata) -> entry_id``.
- ``archival_search(agent_id, collection, query, filter, limit) -> list[dict]``
  Each entry has ``id``, ``text``, ``metadata``, ``score`` (optional).
  Raises ``NotImplementedError`` when the deployed store does not
  support metadata pre-filtering — LettaBackend then falls back to
  over-fetch + post-filter.
- ``archival_list(agent_id, collection, filter, order_by, order, limit) -> list[dict]``.
- ``archival_delete(agent_id, collection, entry_id)``.
- ``write_core_blocks(agent_id, persona, human, context)``.
- ``read_core_context(agent_id) -> dict``.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from ari_skill_memory.config import MemoryConfig

log = logging.getLogger(__name__)


class LettaClientProtocol(Protocol):  # pragma: no cover - typing only
    def health(self) -> dict: ...
    def ensure_agent(
        self, name: str, *, memory_editing_enabled: bool,
        collections: list[str],
    ) -> str: ...
    def get_agent_embedding(self, agent_id: str) -> dict: ...
    def delete_agent(self, agent_id: str) -> None: ...
    def archival_insert(
        self, *, agent_id: str, collection: str, text: str, metadata: dict
    ) -> str: ...
    def archival_search(
        self, *, agent_id: str, collection: str, query: str,
        filter: dict | None, limit: int,
    ) -> list[dict]: ...
    def archival_list(
        self, *, agent_id: str, collection: str, filter: dict | None = None,
        order_by: str | None = None, order: str | None = None,
        limit: int | None = None,
    ) -> list[dict]: ...
    def archival_delete(
        self, *, agent_id: str, collection: str, entry_id: str
    ) -> None: ...
    def write_core_blocks(
        self, *, agent_id: str, persona: str, human: str, context: dict
    ) -> None: ...
    def read_core_context(self, *, agent_id: str) -> dict: ...


def build_default_client(cfg: MemoryConfig) -> LettaClientProtocol:
    """Construct the production Letta client.

    Tries ``letta_client.Letta`` (the SDK that ships with newer Letta
    versions). If the SDK isn't installed, raises ``RuntimeError`` —
    there is no fallback store (fail fast, fail loud).
    """
    try:
        from letta_client import Letta  # type: ignore[import]
    except ImportError as e:
        try:
            from letta import client as _legacy  # type: ignore[import]
            return _LegacyLettaAdapter(cfg, _legacy)
        except ImportError:
            raise RuntimeError(
                "Letta SDK not installed. "
                "pip install letta-client or letta, or set "
                "ARI_MEMORY_BACKEND=in_memory for tests."
            ) from e
    return _SdkLettaAdapter(cfg, Letta)


class _SdkLettaAdapter:
    """Adapter over ``letta-client`` targeting Letta server 0.9.x.

    The 0.9 server stores passages as ``{id, text, created_at, embedding}``
    with no server-side tags/metadata/filtering. We encode the ARI
    metadata dict as a JSON footer on the passage text; any filtered
    search raises ``NotImplementedError`` so LettaBackend falls back to
    its overfetch + post-filter path. Tests inject a fake and bypass
    this class entirely.
    """

    _META_SEP = "\n<<<ARI_META>>>\n"
    _DEFAULT_HANDLE = "letta/letta-free"

    def __init__(self, cfg: MemoryConfig, LettaCls: Any) -> None:
        kwargs: dict[str, Any] = {"base_url": cfg.letta_base_url}
        if cfg.letta_api_key:
            kwargs["api_key"] = cfg.letta_api_key
        if cfg.letta_timeout_s and cfg.letta_timeout_s > 0:
            kwargs["timeout"] = max(cfg.letta_timeout_s, 60.0)
        self.cfg = cfg
        self._letta = LettaCls(**kwargs)
        # Letta SDK requires `model=` on agents.create, but ARI never invokes
        # the agent's chat LLM (no agents.messages.send / chat / completion
        # calls anywhere in this skill — only archival_insert/search, which
        # use embeddings). The handle is therefore a fixed mock; the embedding
        # handle below is the one operators actually need to configure.
        self._model = self._DEFAULT_HANDLE
        self._embedding = self._resolve_handle(cfg.letta_embedding_config)

    @classmethod
    def _resolve_handle(cls, value: str) -> str:
        v = (value or "").strip()
        if not v or v == "letta-default":
            return cls._DEFAULT_HANDLE
        return v

    # ─ metadata encoding ───────────────────────────────────────────────
    @classmethod
    def _encode(cls, text: str, metadata: dict) -> str:
        return text + cls._META_SEP + json.dumps(
            metadata, ensure_ascii=False, sort_keys=True, default=str,
        )

    @classmethod
    def _decode(cls, blob: str) -> tuple[str, dict]:
        if not blob or cls._META_SEP not in blob:
            return blob or "", {}
        head, _, tail = blob.rpartition(cls._META_SEP)
        try:
            md = json.loads(tail)
            if isinstance(md, dict):
                return head, md
        except json.JSONDecodeError:
            pass
        return blob, {}

    # ─ protocol methods ────────────────────────────────────────────────
    def health(self) -> dict:
        try:
            r = self._letta.health()
            return {
                "ok": True,
                "server_version": getattr(r, "version", ""),
            }
        except Exception as e:
            raise RuntimeError(f"Letta health check failed: {e}") from e

    def ensure_agent(
        self, name: str, *, memory_editing_enabled: bool,
        collections: list[str],
    ) -> str:
        try:
            page = self._letta.agents.list(name=name, limit=10)
            for a in page:
                if getattr(a, "name", None) == name:
                    return a.id
        except Exception as e:
            log.debug("agents.list(name=%s) failed, will create: %s", name, e)
        a = self._letta.agents.create(
            name=name,
            model=self._model,
            embedding=self._embedding,
            include_base_tools=False,
            memory_blocks=[
                {"label": "persona", "value": ""},
                {"label": "human", "value": ""},
                {"label": "ari_context", "value": ""},
            ],
        )
        return a.id

    def delete_agent(self, agent_id: str) -> None:
        try:
            self._letta.agents.delete(agent_id)
        except Exception as e:
            log.warning("Letta agent delete failed: %s", e)

    def get_agent_embedding(self, agent_id: str) -> dict:
        """Fetch the agent's embedding_config as a plain dict.

        Used by LettaBackend to detect agents created against a flaky
        embedding endpoint (e.g. ``embeddings.memgpt.ai``) — see the
        ``Expecting value: line 1 column 1 (char 0)`` failure mode that
        Letta surfaces when the embedding upstream returns an empty body.
        Returns ``{}`` on any failure so the integrity check degrades to
        a soft warning rather than blocking writes.
        """
        try:
            a = self._letta.agents.retrieve(agent_id)
            ec = getattr(a, "embedding_config", None)
            if ec is None:
                return {}
            if hasattr(ec, "model_dump"):
                return ec.model_dump()
            if hasattr(ec, "dict"):
                return ec.dict()
            if isinstance(ec, dict):
                return dict(ec)
            return {}
        except Exception as e:
            log.debug("get_agent_embedding(%s) failed: %s", agent_id, e)
            return {}

    def archival_insert(
        self, *, agent_id: str, collection: str, text: str, metadata: dict
    ) -> str:
        full_meta = {"collection": collection, **metadata}
        blob = self._encode(text, full_meta)
        result = self._letta.agents.passages.create(
            agent_id=agent_id, text=blob,
        )
        if isinstance(result, list):
            if not result:
                raise RuntimeError("passages.create returned empty list")
            return result[0].id
        return getattr(result, "id")

    def archival_search(
        self, *, agent_id: str, collection: str, query: str,
        filter: dict | None, limit: int,
    ) -> list[dict]:
        # 0.9 has no server-side filter; force backend's overfetch path
        # whenever a filter is requested.
        if filter is not None:
            raise NotImplementedError("passage filter not supported by server")
        page = self._letta.agents.passages.list(
            agent_id=agent_id, search=query, limit=limit,
        )
        return self._rows_from_page(page)

    def archival_list(
        self, *, agent_id: str, collection: str, filter: dict | None = None,
        order_by: str | None = None, order: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        fetch_limit = max(self.cfg.letta_overfetch, (limit or 0) * 10, 200)
        page = self._letta.agents.passages.list(
            agent_id=agent_id, limit=fetch_limit,
        )
        rows = self._rows_from_page(page)
        rows = [r for r in rows if r["metadata"].get("collection") == collection]
        if filter:
            rows = [r for r in rows if _match(r["metadata"], filter)]
        if order_by:
            rows.sort(
                key=lambda r: (r.get("metadata") or {}).get(order_by, 0),
                reverse=(order == "desc"),
            )
        if limit is not None:
            rows = rows[:limit]
        # archival_list callers don't use `score`; drop it for parity
        # with the fake (which omits score from list results).
        return [
            {"id": r["id"], "text": r["text"], "metadata": r["metadata"]}
            for r in rows
        ]

    def archival_delete(
        self, *, agent_id: str, collection: str, entry_id: str
    ) -> None:
        self._letta.agents.passages.delete(entry_id, agent_id=agent_id)

    def write_core_blocks(
        self, *, agent_id: str, persona: str, human: str, context: dict
    ) -> None:
        ctx_value = json.dumps(context or {}, ensure_ascii=False)
        self._update_block(agent_id, "persona", persona)
        self._update_block(agent_id, "human", human)
        self._update_block(agent_id, "ari_context", ctx_value)

    def read_core_context(self, *, agent_id: str) -> dict:
        try:
            blk = self._letta.agents.blocks.retrieve(
                "ari_context", agent_id=agent_id,
            )
            val = getattr(blk, "value", "") or ""
            if val:
                return json.loads(val)
        except Exception as e:
            log.debug("ari_context block not found: %s", e)
        return {}

    # ─ helpers ─────────────────────────────────────────────────────────
    def _rows_from_page(self, page: Any) -> list[dict]:
        items = list(page) if hasattr(page, "__iter__") else page
        out: list[dict] = []
        for p in items or []:
            text, meta = self._decode(getattr(p, "text", "") or "")
            out.append({
                "id": getattr(p, "id", None),
                "text": text,
                "metadata": meta,
                "score": 0.0,
            })
        return out

    def _update_block(self, agent_id: str, label: str, value: str) -> None:
        try:
            self._letta.agents.blocks.update(
                label, agent_id=agent_id, value=value,
            )
            return
        except Exception as e:
            not_found = (
                "NotFound" in type(e).__name__
                or "404" in str(e)
            )
            if not not_found:
                raise
        blk = self._letta.blocks.create(label=label, value=value)
        self._letta.agents.blocks.attach(blk.id, agent_id=agent_id)


def _match(metadata: dict, filter: dict) -> bool:
    for k, v in filter.items():
        if isinstance(v, dict) and "$in" in v:
            if metadata.get(k) not in v["$in"]:
                return False
        elif metadata.get(k) != v:
            return False
    return True


class _LegacyLettaAdapter(_SdkLettaAdapter):  # pragma: no cover - fallback only
    """Stub for older Letta SDKs. Callers inject their own client."""

    def __init__(self, cfg: MemoryConfig, mod: Any) -> None:
        raise RuntimeError(
            "legacy Letta SDK detected — this release targets letta-client. "
            "Install letta-client or supply a client= to LettaBackend."
        )


__all__ = ["LettaClientProtocol", "build_default_client"]
