# ari-skill-memory/src

Source root for the memory skill — ancestor-scoped node memory for the BFTS
tree, backed by Letta. Holds the FastMCP server plus the importable
`ari_skill_memory` library package (the backend abstraction).

## Contents

- `README.md` — this file.
- `__init__.py` — empty package marker.
- `server.py` — FastMCP server exposing the store/recall tools.
- `ari_skill_memory/` — importable library package: the memory backend abstraction.
  - `README.md` — ari_skill_memory index.
  - `__init__.py` — public surface (`get_backend`, `MemoryBackend`) & layout (module docstring is authoritative).
  - `access_log.py` — access auditing shared across backends.
  - `audit.py` — TODO
  - `config.py` — config loading shared across backends.
  - `consolidation.py` — TODO
  - `context_builder.py` — TODO
  - `provenance.py` — TODO
  - `retriever.py` — TODO
  - `schemas.py` — TODO
  - `writer.py` — TODO
  - `backends/` — backend implementations behind the `get_backend()` factory.
    - `README.md` — backends index.
    - `__init__.py` — the `get_backend()` factory + `MemoryBackend` selection (module docstring is authoritative).
    - `base.py` — the `MemoryBackend` abstract interface.
    - `in_memory.py` — test-only `InMemoryBackend`.
    - `letta_backend.py` — production Letta backend.
    - `letta_client.py` — Letta HTTP client.

## See also

- The skill root `README.md` for concept & lifecycle.
