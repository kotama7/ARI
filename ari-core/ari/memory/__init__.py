"""ari.memory — backend abstraction for ancestor-scoped node memory.

Three concrete backends share the ``MemoryClient`` Protocol:

- ``LettaMemoryClient`` (default since v0.6.0) — backed by a per-checkpoint
  Letta agent with embedding-ranked search.  See
  ``docs/architecture.md`` (Memory Architecture).
- ``FileMemoryClient`` (legacy) — JSONL store at
  ``$ARI_CHECKPOINT_DIR/memory_store.jsonl`` for v0.5 compatibility.
- ``LocalMemoryClient`` — in-memory dict for tests.

``auto_migrate.py`` ports v0.5.x JSONL data into the active backend on
first launch.

Public symbols:
- ``MemoryClient`` (protocol) — see ``client.py``.
- ``LettaMemoryClient``, ``FileMemoryClient``, ``LocalMemoryClient``.
- ``maybe_auto_migrate`` — first-launch v0.5 → v0.6 importer.

See also:
- ``ari-skill-memory/`` (the MCP-facing wrapper used by skills).
- ``git log -- ari-core/ari/memory/`` for the deprecation tier roadmap.
"""
