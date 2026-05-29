# ari_skill_memory

Importable library package providing the memory backend abstraction used by
both the FastMCP server (`src/server.py`) and ari-core's viz layer.

## Contents

- `README.md` — this file.
- `__init__.py` — public surface (`get_backend`, `MemoryBackend`) & layout (module docstring is authoritative).
- `access_log.py` — access auditing shared across backends.
- `config.py` — config loading shared across backends.
- `backends/` — backend implementations behind the `get_backend()` factory.
  - `README.md` — backends index.
  - `__init__.py` — the `get_backend()` factory + `MemoryBackend` selection (module docstring is authoritative).
  - `base.py` — the `MemoryBackend` abstract interface.
  - `in_memory.py` — test-only `InMemoryBackend`.
  - `letta_backend.py` — production Letta backend.
  - `letta_client.py` — Letta HTTP client.
