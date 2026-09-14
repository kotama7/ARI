# ari.memory

Backend abstraction for ancestor-scoped node memory: `LettaMemoryClient`
(default), `FileMemoryClient` (legacy JSONL), `LocalMemoryClient` (tests),
plus explicit offline v0.5→v1 migration.

## Contents

- `README.md` — this file.
- `__init__.py` — `MemoryClient` protocol, backends, migration map.
- `backend.py` — sanctioned core→skill funnel: lazy forwards (`get_backend` / `clear_backend_cache` / `build_verified_context`) to the rich `MemoryBackend`.
- `client.py` — abstract `MemoryClient` ABC.
- `file_client.py` — `FileMemoryClient` (legacy JSONL).
- `letta_client.py` — `LettaMemoryClient` (default).
- `local_client.py` — `LocalMemoryClient` (tests).

## See also

- **`MemoryClient` protocol, backends & migration** → the `__init__.py` module docstring (authoritative).
- **Memory architecture** → `docs/concepts/memory.md`, `docs/concepts/architecture.md`.
- **MCP-facing wrapper** → `ari-skill-memory/`.
