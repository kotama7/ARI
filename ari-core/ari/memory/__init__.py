"""ari.memory — the two-tier memory boundary and the sole core→skill funnel.

Two deliberately **separate** abstractions back agent memory; they do NOT share
types and are NOT merged (subtask 013; ``007_subtask_index.md:627`` — "Unify
without changing tool names/schema or the ABC methods"):

1. ``MemoryClient`` (narrow ABC, ``client.py``) — the 3-method ReAct-trace view
   (``add`` / ``search`` / ``get_all``) consumed by the agent loop and BFTS.
   Concrete impls: ``LettaMemoryClient`` (default since v0.6.0),
   ``FileMemoryClient`` (legacy JSONL, migration-only), ``LocalMemoryClient``
   (tests).
2. ``MemoryBackend`` (rich ABC, ``ari_skill_memory.backends.base``) — the
   ~17-method node-scoped + typed + ``react_*`` API produced by the skill
   factory ``get_backend``.

``LettaMemoryClient`` is a thin adapter whose three methods forward to the
backend's ``react_add`` / ``react_search`` / ``react_get_all``, so the intended
layering is ``MemoryClient`` (narrow) → ``MemoryBackend`` (rich) → Letta /
in-memory.  New code that needs the rich API should obtain a backend via
``ari.memory.get_backend`` rather than re-reaching into the skill.

**Funnel policy (the one allowed core→skill edge).** ``ari_skill_memory`` may be
imported **only** from within ``ari/memory/**`` — specifically ``backend.py``
(the sanctioned forwards ``get_backend`` / ``clear_backend_cache`` /
``build_verified_context``), ``letta_client.py``, and ``auto_migrate.py``.
Every other ``ari-core`` module reaches the skill backend through the
``ari.memory`` re-exports below, so the sanctioned edge (introduced v0.6.0) is
confined to one directory and a future import-boundary checker (subtask 026) can
allow-list ``ari/memory/**`` instead of a dozen scattered files.

The skill-touching forwards are lazy (they import ``ari_skill_memory`` only when
called), so ``import ari.memory`` succeeds even when the skill is not installed.

See also:
- ``ari/memory/README.md``, ``docs/concepts/memory.md`` / ``architecture.md``.
- ``ari-skill-memory/`` — the MCP-facing wrapper used by skills.
- ``git log -- ari-core/ari/memory/`` for the deprecation-tier roadmap.
"""
from __future__ import annotations

from ari.memory.auto_migrate import maybe_auto_migrate
from ari.memory.backend import (
    build_verified_context,
    clear_backend_cache,
    get_backend,
)
from ari.memory.client import MemoryClient
from ari.memory.file_client import FileMemoryClient
from ari.memory.letta_client import LettaMemoryClient
from ari.memory.local_client import LocalMemoryClient

__all__ = [
    "MemoryClient",
    "LettaMemoryClient",
    "FileMemoryClient",
    "LocalMemoryClient",
    "maybe_auto_migrate",
    "get_backend",
    "clear_backend_cache",
    "build_verified_context",
]
