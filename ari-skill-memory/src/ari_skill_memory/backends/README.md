# ari_skill_memory.backends

Memory backend implementations behind the `get_backend()` factory: a
per-checkpoint Letta-backed production store plus a test-only in-memory store.

## Contents

- `README.md` — this file.
- `__init__.py` — the `get_backend()` factory + `MemoryBackend` selection (module docstring is authoritative).
- `base.py` — the `MemoryBackend` abstract interface.
- `in_memory.py` — test-only `InMemoryBackend`.
- `letta_backend.py` — production Letta backend.
- `letta_client.py` — Letta HTTP client.
