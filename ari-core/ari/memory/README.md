# ari.memory

Backend abstraction for ancestor-scoped node memory: `LettaMemoryClient`
(default), `FileMemoryClient` (legacy JSONL), `LocalMemoryClient` (tests),
plus v0.5→v0.6 auto-migration.

## Contents

- `README.md` — this file.
- `__init__.py` — `MemoryClient` protocol, backends, migration map.
- `auto_migrate.py` — v0.5.x → v0.6.0 auto-migration on first launch.
- `backend.py` — TODO
- `client.py` — abstract `MemoryClient` ABC.
- `file_client.py` — `FileMemoryClient` (legacy JSONL).
- `letta_client.py` — `LettaMemoryClient` (default).
- `local_client.py` — `LocalMemoryClient` (tests).

## See also

- **`MemoryClient` protocol, backends & migration** → the `__init__.py` module docstring (authoritative).
- **Memory architecture** → `docs/concepts/memory.md`, `docs/concepts/architecture.md`.
- **MCP-facing wrapper** → `ari-skill-memory/`.
